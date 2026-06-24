"""Plot Maker (플롯 메이커)
==========================
여러 결과 파일을 **메모리에 올려두고(데이터 선반)** 임의의 컬럼을 자유롭게
조합해 그래프를 만드는 탭. 결과 뷰어가 "파일 하나 빠르게 보기"라면, 여기는
"여러 소스를 합성·가공해 분석/논문용 그림 만들기"가 목적이다.

모드(렌더 방식)는 레지스트리(`@register_mode`)로 등록한다. 새 모드를 추가하려면
`PlotMode`를 상속한 클래스를 하나 만들고 데코레이터만 붙이면 콤보에 자동 등장한다.

1차 제공 모드:
  · Time series      : 좌/우 Y축에 임의 컬럼 배치(이중축), 시간축 자동
  · Scatter + 회귀   : 가스 vs 가스 산점도 + 최소제곱 직선(slope/R²/n)
  · Allan deviation  : 평균화시간 vs Allan 편차(log-log) — 최적 적분시간/검출한계

공통 가공(모드 횡단): 시간 리샘플(분/시 평균), rolling 평활.
"""
from __future__ import annotations

import os
import json
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QComboBox, QSplitter, QTreeWidget, QTreeWidgetItem, QListWidget,
    QListWidgetItem, QMessageBox, QSpinBox, QSizePolicy, QStackedWidget,
)
from PyQt6.QtCore import Qt

from gui.result_viewer_io import detect, detect_sep, read_numeric, load_fit_table

_PALETTE = ["#2196F3", "#FF6F00", "#D32F2F", "#388E3C", "#7B1FA2",
            "#0097A7", "#C2185B", "#5D4037", "#455A64", "#689F38"]

# 리샘플 콤보 라벨 → 초. 0 = 원본 유지.
_RESAMPLE = {"Raw": 0, "1 min": 60, "5 min": 300, "10 min": 600,
             "30 min": 1800, "1 hour": 3600}


# ══════════════════════════════════════════════════════════════════════
# 데이터 모델 / 로더
# ══════════════════════════════════════════════════════════════════════
class Dataset:
    """결과 파일 하나를 공통 테이블로 정규화한 메모리 표현.

    time : epoch초 ndarray 또는 None(시간축 없음)
    cols : {컬럼명: float ndarray}  (가스 ppb, RMS, 일반 수치 등)
    """
    __slots__ = ("name", "path", "time", "cols")

    def __init__(self, name, path, time, cols):
        self.name = name
        self.path = path
        self.time = time
        self.cols = cols

    def __len__(self):
        return max((len(v) for v in self.cols.values()), default=0)


def load_dataset(path) -> Dataset:
    """파일 종류를 자동 판별해 Dataset으로 읽는다(기존 뷰어 파서 재사용)."""
    name = os.path.splitext(os.path.basename(path))[0]
    kind = detect(path)

    # ① fit/리포트 → 가스 + RMS + (시각)
    if kind == "fit":
        t = load_fit_table(path)
        cols = {g: v for g, v in t["gases"].items()}
        if t.get("rms") is not None:
            cols["RMS"] = t["rms"]
        return Dataset(name, path, t.get("time"), cols)

    # ② 일반 표(csv/tsv/농도) → pandas로 시간컬럼 + 수치컬럼
    try:
        import pandas as pd
        sep = detect_sep(path)
        df = pd.read_csv(path, sep=sep if sep else r"\s+",
                         comment="#", engine="python")
        df.columns = [str(c).strip() for c in df.columns]
        time, tcol = None, None
        for c in df.columns:
            if c.lower() in ("time", "datetime", "timestamp", "date"):
                dt = pd.to_datetime(df[c], errors="coerce")
                if dt.notna().mean() > 0.5:
                    tt = dt.to_numpy(dtype="datetime64[ns]").astype("int64") / 1e9
                    tt[dt.isna().to_numpy()] = np.nan
                    time, tcol = tt, c
                    break
        cols = {}
        for c in df.columns:
            if c == tcol:
                continue
            y = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
            if np.isfinite(y).any():
                cols[c] = y
        if cols:
            return Dataset(name, path, time, cols)
    except Exception:
        pass

    # ③ 마지막 폴백: 순수 숫자배열
    d = read_numeric(path)
    cols = {f"col{j}": d[:, j] for j in range(d.shape[1])}
    return Dataset(name, path, None, cols)


# ══════════════════════════════════════════════════════════════════════
# 공통 가공 헬퍼
# ══════════════════════════════════════════════════════════════════════
def resample_mean(t, y, sec):
    """시간 t(epoch초)를 sec 간격 버킷으로 묶어 평균. t 없으면 그대로."""
    if not sec or t is None:
        return t, y
    m = np.isfinite(t) & np.isfinite(y)
    if m.sum() == 0:
        return t, y
    tt, yy = t[m], y[m]
    o = np.argsort(tt)
    tt, yy = tt[o], yy[o]
    bins = np.floor(tt / sec).astype(np.int64)
    ub, inv = np.unique(bins, return_inverse=True)
    cnt = np.bincount(inv)
    xs = np.bincount(inv, weights=tt) / cnt
    ys = np.bincount(inv, weights=yy) / cnt
    return xs, ys


def smooth(y, n):
    """rolling 평균(center, NaN 무시). n<=1이면 그대로."""
    if n <= 1:
        return y
    import pandas as pd
    return pd.Series(y).rolling(n, min_periods=1, center=True).mean().to_numpy()


def regress(x, y):
    """최소제곱 직선 적합 → (slope, intercept, r2, n) 또는 None."""
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 2:
        return None
    x, y = x[m], y[m]
    slope, inter = np.polyfit(x, y, 1)
    yhat = slope * x + inter
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return slope, inter, r2, int(m.sum())


def allan_deviation(t, y):
    """비중첩 Allan 편차. 시각으로 균일 격자에 보간 후 2의 거듭제곱 구간평균.
    반환 (taus[s], adev) 또는 None."""
    if t is None:
        return None
    m = np.isfinite(t) & np.isfinite(y)
    if m.sum() < 16:
        return None
    tt, yy = t[m], y[m]
    o = np.argsort(tt)
    tt, yy = tt[o], yy[o]
    dt = float(np.median(np.diff(tt)))
    if dt <= 0:
        return None
    grid = np.arange(tt[0], tt[-1], dt)
    yi = np.interp(grid, tt, yy)
    n = len(yi)
    taus, ad = [], []
    mm = 1
    while mm <= n // 2:
        k = n // mm
        ym = yi[:k * mm].reshape(k, mm).mean(axis=1)
        d = np.diff(ym)
        ad.append(float(np.sqrt(0.5 * np.mean(d ** 2))))
        taus.append(mm * dt)
        mm *= 2
    return np.array(taus), np.array(ad)


# ══════════════════════════════════════════════════════════════════════
# 모드 레지스트리
# ══════════════════════════════════════════════════════════════════════
_MODES = []


def register_mode(cls):
    _MODES.append(cls)
    return cls


class PlotMode:
    """모드 베이스. 새 모드는 이걸 상속하고 @register_mode 붙이면 끝.

    host(PlotMakerWidget)가 제공하는 것:
      · host.shelf            : {name: Dataset}
      · host.column_choices() : ["ds:col", ...] 전체 컬럼 목록
      · host.resolve(label)   : "ds:col" → (Dataset, col, y, t)
      · host.resample_sec / host.smooth_n : 전역 가공 파라미터
      · host.pw / host.p1 / host.vb_right  : 플롯 위젯/뷰박스
      · host.set_status(text) : 하단 상태라벨
    """
    key = ""
    label = ""

    def __init__(self, host):
        self.host = host

    def options_widget(self) -> QWidget | None:
        """모드별 입력 UI(좌패널 하단). 없으면 None."""
        return None

    def on_shelf_changed(self):
        """선반(데이터셋 목록)이 바뀌면 호출 — 콤보 재구성 등."""

    def to_config(self) -> dict:
        return {}

    def from_config(self, cfg: dict):
        pass

    def render(self):
        raise NotImplementedError


# ── Time series ───────────────────────────────────────────────────────
@register_mode
class TimeSeriesMode(PlotMode):
    key = "timeseries"
    label = "Time series"

    def __init__(self, host):
        super().__init__(host)
        self._series = []   # [(label, axis 'L'/'R')]
        self._w = None

    def options_widget(self):
        if self._w is not None:
            return self._w
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        b_l = QPushButton("+ Left Y")
        b_r = QPushButton("+ Right Y")
        b_del = QPushButton("− Remove")
        b_l.clicked.connect(lambda: self._add("L"))
        b_r.clicked.connect(lambda: self._add("R"))
        b_del.clicked.connect(self._remove)
        for b in (b_l, b_r, b_del):
            row.addWidget(b)
        lay.addLayout(row)
        self._list = QListWidget()
        self._list.setToolTip("선반에서 컬럼을 고른 뒤 [+ Left/Right Y]. 항목 더블클릭 시 좌↔우 전환.")
        self._list.itemDoubleClicked.connect(self._toggle_axis)
        lay.addWidget(self._list)
        self._w = w
        return w

    def _add(self, axis):
        for lab in self.host.selected_columns():
            if (lab, axis) not in self._series:
                self._series.append((lab, axis))
        self._refresh_list()
        self.render()

    def _remove(self):
        for it in self._list.selectedItems():
            tup = it.data(Qt.ItemDataRole.UserRole)
            if tup in self._series:
                self._series.remove(tup)
        self._refresh_list()
        self.render()

    def _toggle_axis(self, item):
        tup = item.data(Qt.ItemDataRole.UserRole)
        if tup in self._series:
            i = self._series.index(tup)
            self._series[i] = (tup[0], "R" if tup[1] == "L" else "L")
            self._refresh_list()
            self.render()

    def _refresh_list(self):
        self._list.clear()
        for lab, axis in self._series:
            it = QListWidgetItem(f"[{axis}] {lab}")
            it.setData(Qt.ItemDataRole.UserRole, (lab, axis))
            self._list.addItem(it)

    def on_shelf_changed(self):
        # 사라진 데이터셋의 시리즈 정리
        valid = set(self.host.column_choices())
        self._series = [(l, a) for (l, a) in self._series if l in valid]
        if self._w:
            self._refresh_list()

    def to_config(self):
        return {"series": self._series}

    def from_config(self, cfg):
        self._series = [tuple(s) for s in cfg.get("series", [])]
        if self._w:
            self._refresh_list()

    def render(self):
        host = self.host
        host.clear_plot()
        use_right = any(a == "R" for _, a in self._series)
        host.enable_right_axis(use_right)
        any_time = False
        n_left = n_right = 0
        for lab, axis in self._series:
            res = host.resolve(lab)
            if res is None:
                continue
            ds, col, y, t = res
            x = t if t is not None else np.arange(len(y), dtype=float)
            if t is not None:
                any_time = True
            xs, ys = resample_mean(x if t is not None else None, y, host.resample_sec)
            if xs is None:
                xs, ys = x, y
            ys = smooth(ys, host.smooth_n)
            if axis == "R":
                col_i = _PALETTE[(n_left + n_right) % len(_PALETTE)]
                curve = pg.PlotDataItem(xs, ys, pen=pg.mkPen(col_i, width=2),
                                        name=f"{lab} (R)")
                host.vb_right.addItem(curve)
                if host.legend is not None:
                    host.legend.addItem(curve, f"{lab} (R)")
                n_right += 1
            else:
                col_i = _PALETTE[(n_left + n_right) % len(_PALETTE)]
                host.p1.plot(xs, ys, pen=pg.mkPen(col_i, width=2), name=lab)
                n_left += 1
        host.set_time_axis(any_time)
        host.p1.setLabel("bottom", "Time" if any_time else "index")
        host.p1.setLabel("left", "Value (left)")
        if use_right:
            host.set_right_label("Value (right)")
        host.p1.setTitle(f"Time series — {n_left + n_right} series")
        host.update_views()
        if n_left + n_right:
            host.set_status(f"{n_left} left · {n_right} right series"
                            + (f" · resample {host.resample_sec}s" if host.resample_sec else "")
                            + (f" · smooth {host.smooth_n}" if host.smooth_n > 1 else ""))


# ── Scatter + regression ──────────────────────────────────────────────
@register_mode
class ScatterMode(PlotMode):
    key = "scatter"
    label = "Scatter + regression"

    def __init__(self, host):
        super().__init__(host)
        self._w = None

    def options_widget(self):
        if self._w is not None:
            return self._w
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self._cx = QComboBox()
        self._cy = QComboBox()
        for c in (self._cx, self._cy):
            c.currentIndexChanged.connect(lambda *_: self.render())
        lay.addWidget(QLabel("X:"))
        lay.addWidget(self._cx)
        lay.addWidget(QLabel("Y:"))
        lay.addWidget(self._cy)
        lay.addStretch(1)
        self._w = w
        self.on_shelf_changed()
        return w

    def on_shelf_changed(self):
        if not self._w:
            return
        choices = self.host.column_choices()
        for c in (self._cx, self._cy):
            cur = c.currentText()
            c.blockSignals(True)
            c.clear()
            c.addItems(choices)
            if cur in choices:
                c.setCurrentText(cur)
            c.blockSignals(False)

    def to_config(self):
        if not self._w:
            return {}
        return {"x": self._cx.currentText(), "y": self._cy.currentText()}

    def from_config(self, cfg):
        if self._w:
            self._cx.setCurrentText(cfg.get("x", ""))
            self._cy.setCurrentText(cfg.get("y", ""))

    def render(self):
        host = self.host
        host.clear_plot()
        host.enable_right_axis(False)
        host.set_time_axis(False)
        rx = host.resolve(self._cx.currentText())
        ry = host.resolve(self._cy.currentText())
        if rx is None or ry is None:
            host.set_status("Pick X and Y columns.")
            return
        dx, cx, xv, tx = rx
        dy, cy, yv, ty = ry
        # 다른 데이터셋이면 시간축으로 정렬(Y를 X 시각에 보간)
        if dx is not dy and tx is not None and ty is not None:
            mt = np.isfinite(ty) & np.isfinite(yv)
            if mt.sum() >= 2:
                o = np.argsort(ty[mt])
                yv = np.interp(tx, ty[mt][o], yv[mt][o], left=np.nan, right=np.nan)
                xv = xv.copy()
        else:
            n = min(len(xv), len(yv))
            xv, yv = xv[:n], yv[:n]
        m = np.isfinite(xv) & np.isfinite(yv)
        host.p1.plot(xv[m], yv[m], pen=None, symbol="o", symbolSize=5,
                     symbolBrush=(33, 150, 243, 120), symbolPen=None, name="data")
        host.p1.setLabel("bottom", self._cx.currentText())
        host.p1.setLabel("left", self._cy.currentText())
        r = regress(xv, yv)
        if r:
            slope, inter, r2, n = r
            xline = np.array([np.nanmin(xv[m]), np.nanmax(xv[m])])
            host.p1.plot(xline, slope * xline + inter,
                         pen=pg.mkPen("#D32F2F", width=2), name="fit")
            host.p1.setTitle(f"y = {slope:.4g}·x + {inter:.4g}   R² = {r2:.4f}   n = {n}")
            host.set_status(f"slope={slope:.5g}  intercept={inter:.5g}  R²={r2:.5f}  n={n}")
        else:
            host.p1.setTitle("Scatter")
            host.set_status("Not enough finite points for regression.")
        host.update_views()


# ── Allan deviation ───────────────────────────────────────────────────
@register_mode
class AllanMode(PlotMode):
    key = "allan"
    label = "Allan deviation"

    def __init__(self, host):
        super().__init__(host)
        self._w = None

    def options_widget(self):
        if self._w is not None:
            return self._w
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self._c = QComboBox()
        self._c.currentIndexChanged.connect(lambda *_: self.render())
        lay.addWidget(QLabel("Signal:"))
        lay.addWidget(self._c)
        lay.addWidget(QLabel("최적 적분시간 = 곡선 최저점.\n−½ 기울기 = 백색잡음(평균화 이득)."))
        lay.addStretch(1)
        self._w = w
        self.on_shelf_changed()
        return w

    def on_shelf_changed(self):
        if not self._w:
            return
        choices = self.host.column_choices()
        cur = self._c.currentText()
        self._c.blockSignals(True)
        self._c.clear()
        self._c.addItems(choices)
        if cur in choices:
            self._c.setCurrentText(cur)
        self._c.blockSignals(False)

    def to_config(self):
        return {"signal": self._c.currentText()} if self._w else {}

    def from_config(self, cfg):
        if self._w:
            self._c.setCurrentText(cfg.get("signal", ""))

    def render(self):
        host = self.host
        host.clear_plot()
        host.enable_right_axis(False)
        host.set_time_axis(False)
        res = host.resolve(self._c.currentText())
        if res is None:
            host.set_status("Pick a signal (needs a time axis).")
            return
        ds, col, y, t = res
        out = allan_deviation(t, y)
        if out is None:
            host.set_status("Allan needs ≥16 finite points on a regular time axis.")
            host.p1.setTitle("Allan deviation — insufficient/irregular data")
            return
        taus, ad = out
        host.p1.setLogMode(x=True, y=True)
        host.p1.plot(taus, ad, pen=pg.mkPen("#2196F3", width=2), symbol="o",
                     symbolSize=6, symbolBrush="#2196F3", name=self._c.currentText())
        host.p1.setLabel("bottom", "Averaging time τ (s)")
        host.p1.setLabel("left", "Allan deviation σ(τ)")
        imin = int(np.argmin(ad))
        host.p1.setTitle(f"Allan deviation — min σ={ad[imin]:.3g} @ τ={taus[imin]:.0f}s")
        host.set_status(f"optimal averaging ≈ {taus[imin]:.0f} s  (min Allan dev {ad[imin]:.3g})")
        host.update_views()


# ══════════════════════════════════════════════════════════════════════
# 메인 위젯
# ══════════════════════════════════════════════════════════════════════
class PlotMakerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.shelf = {}        # name → Dataset
        self.resample_sec = 0
        self.smooth_n = 1
        self.legend = None
        self._modes = [cls(self) for cls in _MODES]
        self._mode = self._modes[0]
        self._init_ui()
        self._rebuild_mode_options()

    # ── UI ────────────────────────────────────────────────────────────
    def _init_ui(self):
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        b_add = QPushButton("➕ Add data")
        b_add.clicked.connect(self._add_data)
        bar.addWidget(b_add)
        b_rm = QPushButton("🗑 Remove")
        b_rm.setToolTip("선반에서 선택한 데이터셋 제거")
        b_rm.clicked.connect(self._remove_data)
        bar.addWidget(b_rm)

        bar.addWidget(QLabel("  Mode:"))
        self._mode_combo = QComboBox()
        for m in self._modes:
            self._mode_combo.addItem(m.label)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        bar.addWidget(self._mode_combo)

        bar.addWidget(QLabel("  Resample:"))
        self._res_combo = QComboBox()
        self._res_combo.addItems(list(_RESAMPLE.keys()))
        self._res_combo.currentIndexChanged.connect(self._on_transform_changed)
        bar.addWidget(self._res_combo)
        bar.addWidget(QLabel("Smooth:"))
        self._smooth_spin = QSpinBox()
        self._smooth_spin.setRange(1, 999)
        self._smooth_spin.setValue(1)
        self._smooth_spin.setToolTip("rolling 평균 점 수(1=끔)")
        self._smooth_spin.valueChanged.connect(self._on_transform_changed)
        bar.addWidget(self._smooth_spin)

        bar.addStretch(1)
        for txt, fn in (("📷 PNG", self._export_png), ("📑 CSV", self._export_csv),
                        ("💾 Save", self._save_cfg), ("📂 Load", self._load_cfg)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            bar.addWidget(b)
        root.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)

        # 좌: 선반 트리 + 모드 옵션
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Data shelf"))
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        lv.addWidget(self._tree, 1)
        lv.addWidget(QLabel("Options"))
        self._opt_stack = QStackedWidget()
        for m in self._modes:
            w = m.options_widget() or QWidget()
            self._opt_stack.addWidget(w)
        lv.addWidget(self._opt_stack, 1)
        left.setMinimumWidth(240)
        split.addWidget(left)

        # 우: 플롯
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.pw = pg.PlotWidget()
        self.pw.setBackground("w")
        self.pw.showGrid(x=True, y=True, alpha=0.3)
        self.p1 = self.pw.plotItem
        self.legend = self.p1.addLegend(offset=(10, 10))
        # 우측 Y축용 보조 ViewBox
        self.vb_right = pg.ViewBox()
        self.p1.scene().addItem(self.vb_right)
        self.p1.getAxis("right").linkToView(self.vb_right)
        self.vb_right.setXLink(self.p1)
        self.p1.vb.sigResized.connect(self.update_views)
        rv.addWidget(self.pw, 1)
        self._status = QLabel("")
        self._status.setStyleSheet("color:#444;")
        self._status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        rv.addWidget(self._status)
        split.addWidget(right)
        split.setSizes([260, 820])
        root.addWidget(split, 1)

    # ── 플롯 헬퍼(모드에서 호출) ────────────────────────────────────────
    def clear_plot(self):
        # 이전 legend를 명시적으로 제거(아직 scene에 붙어 있으면) 후 plotItem clear.
        if self.legend is not None:
            sc = self.legend.scene()
            if sc is not None:
                sc.removeItem(self.legend)
        self.p1.clear()
        self.vb_right.clear()
        self.p1.setLogMode(x=False, y=False)
        self.legend = self.p1.addLegend(offset=(10, 10))

    def enable_right_axis(self, on):
        self.p1.showAxis("right", show=on)
        self.vb_right.setGeometry(self.p1.vb.sceneBoundingRect())

    def set_right_label(self, text):
        self.p1.setLabel("right", text)

    def set_time_axis(self, on):
        ax = pg.DateAxisItem(orientation="bottom") if on else pg.AxisItem(orientation="bottom")
        self.pw.setAxisItems({"bottom": ax})

    def update_views(self):
        self.vb_right.setGeometry(self.p1.vb.sceneBoundingRect())
        self.vb_right.linkedViewChanged(self.p1.vb, self.vb_right.XAxis)

    def set_status(self, text):
        self._status.setText(text)

    # ── 선반 ────────────────────────────────────────────────────────────
    def column_choices(self):
        return [f"{name}:{col}" for name, ds in self.shelf.items() for col in ds.cols]

    def selected_columns(self):
        out = []
        for it in self._tree.selectedItems():
            data = it.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and data[0] == "col":
                out.append(f"{data[1]}:{data[2]}")
        return out

    def resolve(self, label):
        """"ds:col" → (Dataset, col, y, t) 또는 None."""
        if not label or ":" not in label:
            return None
        name, col = label.split(":", 1)
        ds = self.shelf.get(name)
        if ds is None or col not in ds.cols:
            return None
        return ds, col, ds.cols[col], ds.time

    def _add_data(self):
        from gui.dlg_dir import dlg_dir
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add result file(s)", dlg_dir("result"),
            "Result files (*.dat *.csv *.txt *.tsv);;All Files (*)")
        if not paths:
            return
        dlg_dir("result", paths[0])
        added = 0
        for p in paths:
            try:
                ds = load_dataset(p)
            except Exception as e:
                QMessageBox.warning(self, "Load failed", f"{os.path.basename(p)}: {e}")
                continue
            name = ds.name
            i = 2
            while name in self.shelf:        # 이름 충돌 → 번호
                name = f"{ds.name}#{i}"
                i += 1
            ds.name = name
            self.shelf[name] = ds
            added += 1
        if added:
            self._refresh_tree()
            self._notify_modes()
            self.set_status(f"Added {added} dataset(s) · {len(self.shelf)} on shelf")

    def _remove_data(self):
        names = set()
        for it in self._tree.selectedItems():
            data = it.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple):
                names.add(data[1])
        for n in names:
            self.shelf.pop(n, None)
        if names:
            self._refresh_tree()
            self._notify_modes()

    def _refresh_tree(self):
        self._tree.clear()
        for name, ds in self.shelf.items():
            top = QTreeWidgetItem([f"{name}  ({len(ds)}×{len(ds.cols)})"])
            top.setData(0, Qt.ItemDataRole.UserRole, ("ds", name))
            tip = "time axis ✓" if ds.time is not None else "no time axis"
            top.setToolTip(0, f"{ds.path}\n{tip}")
            for col in ds.cols:
                ch = QTreeWidgetItem([col])
                ch.setData(0, Qt.ItemDataRole.UserRole, ("col", name, col))
                top.addChild(ch)
            self._tree.addTopLevelItem(top)
            top.setExpanded(True)

    def _notify_modes(self):
        for m in self._modes:
            m.on_shelf_changed()

    # ── 모드 전환 / 가공 변경 ───────────────────────────────────────────
    def _rebuild_mode_options(self):
        idx = self._modes.index(self._mode)
        self._opt_stack.setCurrentIndex(idx)

    def _on_mode_changed(self, idx):
        self._mode = self._modes[idx]
        self._opt_stack.setCurrentIndex(idx)
        self._mode.render()

    def _on_transform_changed(self, *_):
        self.resample_sec = _RESAMPLE.get(self._res_combo.currentText(), 0)
        self.smooth_n = self._smooth_spin.value()
        self._mode.render()

    # ── Export / config ────────────────────────────────────────────────
    def _export_png(self):
        import pyqtgraph.exporters as pgex
        out, _ = QFileDialog.getSaveFileName(self, "Export PNG", "plot.png", "PNG (*.png)")
        if not out:
            return
        if not out.lower().endswith(".png"):
            out += ".png"
        try:
            ex = pgex.ImageExporter(self.p1)
            ex.parameters()["width"] = 2400
            ex.export(out)
            self.set_status(f"PNG saved: {os.path.basename(out)} (2400px)")
        except Exception as e:
            QMessageBox.warning(self, "PNG export", f"Failed: {e}")

    def _export_csv(self):
        """현재 시계열 모드의 시리즈를 공유 시간축으로 합쳐 CSV 저장."""
        if self._mode.key != "timeseries" or not self._mode._series:
            QMessageBox.information(self, "CSV", "Add series in Time series mode first.")
            return
        out, _ = QFileDialog.getSaveFileName(self, "Export CSV", "plotmaker.csv",
                                             "CSV (*.csv)")
        if not out:
            return
        cols, time_ref = {}, None
        for lab, _axis in self._mode._series:
            r = self.resolve(lab)
            if r is None:
                continue
            ds, col, y, t = r
            xs, ys = resample_mean(t, y, self.resample_sec) if t is not None else (None, y)
            ys = smooth(ys if xs is not None else y, self.smooth_n)
            cols[lab] = (xs, ys)
            if time_ref is None and xs is not None:
                time_ref = xs
        try:
            import csv
            with open(out, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if time_ref is not None:
                    headers = ["datetime"] + list(cols.keys())
                    w.writerow(headers)
                    for i, tv in enumerate(time_ref):
                        row = [datetime.fromtimestamp(tv).strftime("%Y-%m-%d %H:%M:%S")]
                        for lab in cols:
                            xs, ys = cols[lab]
                            if xs is time_ref and i < len(ys):
                                row.append(f"{ys[i]:.6g}")
                            else:   # 다른 격자 → 보간
                                row.append(f"{np.interp(tv, xs, ys):.6g}"
                                           if xs is not None else "")
                        w.writerow(row)
                else:
                    w.writerow(["index"] + list(cols.keys()))
                    n = max(len(v[1]) for v in cols.values())
                    for i in range(n):
                        row = [i] + [f"{cols[l][1][i]:.6g}" if i < len(cols[l][1]) else ""
                                     for l in cols]
                        w.writerow(row)
            self.set_status(f"CSV saved: {os.path.basename(out)}")
        except Exception as e:
            QMessageBox.warning(self, "CSV export", f"Failed: {e}")

    def _save_cfg(self):
        out, _ = QFileDialog.getSaveFileName(self, "Save plot config", "plot.pmcfg.json",
                                             "Plot config (*.json)")
        if not out:
            return
        cfg = {
            "datasets": {n: ds.path for n, ds in self.shelf.items()},
            "mode": self._mode.key,
            "resample": self._res_combo.currentText(),
            "smooth": self._smooth_spin.value(),
            "mode_cfg": {m.key: m.to_config() for m in self._modes},
        }
        try:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            self.set_status(f"Config saved: {os.path.basename(out)}")
        except Exception as e:
            QMessageBox.warning(self, "Save config", f"Failed: {e}")

    def _load_cfg(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load plot config", "",
                                              "Plot config (*.json);;All (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Load config", f"Failed: {e}")
            return
        missing = []
        for name, p in cfg.get("datasets", {}).items():
            if name in self.shelf:
                continue
            if not (p and os.path.isfile(p)):
                missing.append(name)
                continue
            try:
                ds = load_dataset(p)
                ds.name = name
                self.shelf[name] = ds
            except Exception:
                missing.append(name)
        self._refresh_tree()
        self._notify_modes()
        self._res_combo.setCurrentText(cfg.get("resample", "Raw"))
        self._smooth_spin.setValue(int(cfg.get("smooth", 1)))
        for m in self._modes:
            m.from_config(cfg.get("mode_cfg", {}).get(m.key, {}))
        # 모드 선택 복원
        for i, m in enumerate(self._modes):
            if m.key == cfg.get("mode"):
                self._mode_combo.setCurrentIndex(i)
                break
        self._on_transform_changed()
        if missing:
            self.set_status(f"Loaded · missing datasets: {', '.join(missing)}")
        else:
            self.set_status(f"Config loaded: {os.path.basename(path)}")
