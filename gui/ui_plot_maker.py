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
    QCheckBox, QLineEdit, QGroupBox, QFormLayout,
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

    def render_mpl(self, fig):
        """출판용 matplotlib 렌더(고화질 PNG/PDF/SVG). 미지원 모드는 NotImplementedError."""
        raise NotImplementedError

    def csv_table(self):
        """CSV 내보내기용 (headers, rows) 반환. 지원 안 하면 None."""
        return None


# ── Time series ───────────────────────────────────────────────────────
@register_mode
class TimeSeriesMode(PlotMode):
    key = "timeseries"
    label = "Time series"

    def __init__(self, host):
        super().__init__(host)
        self._series = []   # [[label, axis 'L'/'R', color|None, name|None], ...]
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
        b_l.clicked.connect(lambda: self._add("L"))
        b_r.clicked.connect(lambda: self._add("R"))
        row.addWidget(b_l)
        row.addWidget(b_r)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        b_c = QPushButton("🎨 Color")
        b_n = QPushButton("✎ Name")
        b_del = QPushButton("− Remove")
        b_c.clicked.connect(self._pick_color)
        b_n.clicked.connect(self._rename)
        b_del.clicked.connect(self._remove)
        row2.addWidget(b_c)
        row2.addWidget(b_n)
        row2.addWidget(b_del)
        lay.addLayout(row2)
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setToolTip("선반에서 컬럼 선택 후 [+ Left/Right Y].\n"
                              "더블클릭 = 좌↔우 전환, 🎨 = 색 지정, ✎ = 범례 이름 지정.")
        self._list.itemDoubleClicked.connect(self._toggle_axis)
        lay.addWidget(self._list)
        self._w = w
        return w

    def _add(self, axis):
        for lab in self.host.selected_columns():
            if not any(s[0] == lab and s[1] == axis for s in self._series):
                self._series.append([lab, axis, None, None])
        self._refresh_list()
        self.render()

    def _sel_indices(self):
        return sorted(it.data(Qt.ItemDataRole.UserRole)
                      for it in self._list.selectedItems())

    def _remove(self):
        idx = set(self._sel_indices())
        if not idx:
            return
        self._series = [s for i, s in enumerate(self._series) if i not in idx]
        self._refresh_list()
        self.render()

    def _toggle_axis(self, item):
        i = item.data(Qt.ItemDataRole.UserRole)
        if i is not None and 0 <= i < len(self._series):
            self._series[i][1] = "R" if self._series[i][1] == "L" else "L"
            self._refresh_list()
            self.render()

    def _pick_color(self):
        from PyQt6.QtWidgets import QColorDialog
        idx = self._sel_indices()
        if not idx:
            self.host.set_status("색을 바꿀 시리즈를 목록에서 선택하세요.")
            return
        c = QColorDialog.getColor()
        if not c.isValid():
            return
        for i in idx:
            self._series[i][2] = c.name()
        self._refresh_list()
        self.render()

    def _rename(self):
        from PyQt6.QtWidgets import QInputDialog
        idx = self._sel_indices()
        if not idx:
            self.host.set_status("이름을 바꿀 시리즈를 목록에서 선택하세요.")
            return
        i = idx[0]
        cur = self._series[i][3] or self._auto_name(self._series[i][0])
        text, ok = QInputDialog.getText(self._w, "Series name",
                                        "범례 이름 (빈칸 = 자동):", text=cur)
        if not ok:
            return
        self._series[i][3] = text.strip() or None
        self._refresh_list()
        self.render()

    def _auto_name(self, lab):
        """기본 범례 이름: 컬럼명(데이터셋 여러 개면 'NO2 (CH1)'처럼 채널 꼬리표)."""
        import re
        ds, _, col = lab.partition(":")
        if len(self.host.shelf) <= 1:
            return col
        m = re.search(r"(CH\d+|cold|warm|hot|ROI\d+|PNs|ANs)", ds, re.I)
        tag = m.group(1) if m else ds[:10]
        return f"{col} ({tag})"

    def _display(self, lab, name):
        return name if name else self._auto_name(lab)

    def _refresh_list(self):
        from PyQt6.QtGui import QColor
        self._list.clear()
        for i, (lab, axis, color, name) in enumerate(self._series):
            disp = self._display(lab, name)
            it = QListWidgetItem(f"[{axis}] {disp}")
            it.setToolTip(lab)
            if color:
                it.setForeground(QColor(color))
            it.setData(Qt.ItemDataRole.UserRole, i)
            self._list.addItem(it)

    def on_shelf_changed(self):
        valid = set(self.host.column_choices())
        self._series = [s for s in self._series if s[0] in valid]
        if self._w:
            self._refresh_list()

    def to_config(self):
        return {"series": self._series}

    def from_config(self, cfg):
        self._series = []
        for s in cfg.get("series", []):
            s = list(s)
            while len(s) < 4:
                s.append(None)
            self._series.append([s[0], s[1], s[2], s[3]])
        if self._w:
            self._refresh_list()

    def _proc(self, y, t):
        """리샘플+평활 적용 → (x, y). 시간 없으면 인덱스."""
        if t is not None:
            xs, ys = resample_mean(t, y, self.host.resample_sec)
        else:
            xs, ys = np.arange(len(y), dtype=float), y
        return xs, smooth(ys, self.host.smooth_n)

    def render(self):
        host = self.host
        host.clear_plot()
        use_right = any(s[1] == "R" for s in self._series)
        host.enable_right_axis(use_right)
        any_time = False
        n = 0
        for lab, axis, color, name in self._series:
            res = host.resolve(lab)
            if res is None:
                continue
            ds, col, y, t = res
            if t is not None:
                any_time = True
            xs, ys = self._proc(y, t)
            ci = color or _PALETTE[n % len(_PALETTE)]
            disp = self._display(lab, name)
            if axis == "R":
                curve = pg.PlotDataItem(xs, ys, pen=pg.mkPen(ci, width=2),
                                        name=f"{disp} (R)")
                host.vb_right.addItem(curve)
                if host.legend is not None:
                    host.legend.addItem(curve, f"{disp} (R)")
            else:
                host.p1.plot(xs, ys, pen=pg.mkPen(ci, width=2), name=disp)
            n += 1
        host.set_time_axis(any_time)
        host.p1.setLabel("bottom", host.lbl("xlabel", "Time" if any_time else "index"))
        host.p1.setLabel("left", host.lbl("ylabel", "Value (left)"))
        if use_right:
            host.set_right_label(host.lbl("rlabel", "Value (right)"))
        host.p1.setTitle(host.lbl("title", f"Time series — {n} series"))
        host.autoscale()
        if n:
            host.set_status(f"{n} series"
                            + (f" · resample {host.resample_sec}s" if host.resample_sec else "")
                            + (f" · smooth {host.smooth_n}" if host.smooth_n > 1 else ""))

    def render_mpl(self, fig):
        import matplotlib.dates as mdates
        host = self.host
        ax = fig.add_subplot(111)
        ax_r = None
        any_time = False
        n = 0
        hl, ll = [], []   # 두 축 범례 통합
        for lab, axis, color, name in self._series:
            res = host.resolve(lab)
            if res is None:
                continue
            ds, col, y, t = res
            xs, ys = self._proc(y, t)
            if t is not None:
                xv = [datetime.fromtimestamp(v) for v in xs]
                any_time = True
            else:
                xv = xs
            ci = color or _PALETTE[n % len(_PALETTE)]
            disp = self._display(lab, name)
            if axis == "R":
                if ax_r is None:
                    ax_r = ax.twinx()
                    ax_r.set_ylabel(host.lbl("rlabel", "Value (right)"))
                line, = ax_r.plot(xv, ys, color=ci, lw=1.6, label=f"{disp} (R)")
            else:
                line, = ax.plot(xv, ys, color=ci, lw=1.6, label=disp)
            hl.append(line)
            ll.append(line.get_label())
            n += 1
        ax.set_xlabel(host.lbl("xlabel", "Time" if any_time else "index"))
        ax.set_ylabel(host.lbl("ylabel", "Value (left)"))
        ax.set_title(host.lbl("title", f"Time series — {n} series"))
        ax.grid(True, alpha=0.3)
        if any_time:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
            fig.autofmt_xdate()
        if hl:
            ax.legend(hl, ll, loc="best", fontsize=9)

    def csv_table(self):
        host = self.host
        cols, time_ref = {}, None
        for lab, axis, color, name in self._series:
            r = host.resolve(lab)
            if r is None:
                continue
            ds, col, y, t = r
            xs, ys = self._proc(y, t)
            if t is None:
                xs = None
            key = self._display(lab, name)
            while key in cols:        # 이름 충돌 방지
                key += "_2"
            cols[key] = (xs, ys)
            if time_ref is None and xs is not None:
                time_ref = xs
        if not cols:
            return None
        if time_ref is not None:
            headers = ["datetime"] + list(cols.keys())
            rows = []
            for i, tv in enumerate(time_ref):
                row = [datetime.fromtimestamp(tv).strftime("%Y-%m-%d %H:%M:%S")]
                for lab in cols:
                    xs, ys = cols[lab]
                    if xs is time_ref and i < len(ys):
                        row.append(f"{ys[i]:.6g}")
                    elif xs is not None:
                        row.append(f"{np.interp(tv, xs, ys):.6g}")
                    else:
                        row.append("")
                rows.append(row)
            return headers, rows
        headers = ["index"] + list(cols.keys())
        n = max(len(v[1]) for v in cols.values())
        rows = [[i] + [f"{cols[l][1][i]:.6g}" if i < len(cols[l][1]) else ""
                       for l in cols] for i in range(n)]
        return headers, rows


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
        self._chk_ct = QCheckBox("Color by time")
        self._chk_ct.setToolTip("점을 시각 순서대로 색칠(시간축 있을 때)")
        self._chk_ct.toggled.connect(lambda *_: self.render())
        lay.addWidget(self._chk_ct)
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
        return {"x": self._cx.currentText(), "y": self._cy.currentText(),
                "color_time": self._chk_ct.isChecked()}

    def from_config(self, cfg):
        if self._w:
            self._cx.setCurrentText(cfg.get("x", ""))
            self._cy.setCurrentText(cfg.get("y", ""))
            self._chk_ct.setChecked(bool(cfg.get("color_time", False)))

    def _xy(self):
        """선택한 X/Y → (xv, yv, tcolor). 다른 데이터셋이면 시간 보간. tcolor=X시각(없으면 None)."""
        host = self.host
        rx = host.resolve(self._cx.currentText())
        ry = host.resolve(self._cy.currentText())
        if rx is None or ry is None:
            return None
        dx, cx, xv, tx = rx
        dy, cy, yv, ty = ry
        if dx is not dy and tx is not None and ty is not None:
            mt = np.isfinite(ty) & np.isfinite(yv)
            if mt.sum() >= 2:
                o = np.argsort(ty[mt])
                yv = np.interp(tx, ty[mt][o], yv[mt][o], left=np.nan, right=np.nan)
                xv = xv.copy()
            tcolor = tx
        else:
            n = min(len(xv), len(yv))
            xv, yv = xv[:n], yv[:n]
            tcolor = tx[:n] if tx is not None else None
        return xv, yv, tcolor

    def render(self):
        host = self.host
        host.clear_plot()
        host.enable_right_axis(False)
        host.set_time_axis(False)
        xy = self._xy()
        if xy is None:
            host.set_status("Pick X and Y columns.")
            return
        xv, yv, tcolor = xy
        m = np.isfinite(xv) & np.isfinite(yv)
        if self._chk_ct.isChecked() and tcolor is not None and np.isfinite(tcolor[m]).any():
            tc = tcolor[m].astype(float)
            lo, hi = np.nanmin(tc), np.nanmax(tc)
            frac = (tc - lo) / (hi - lo) if hi > lo else np.zeros_like(tc)
            cmap = pg.colormap.get("viridis")
            brushes = [pg.mkBrush(cmap.map(f, mode="qcolor")) for f in frac]
            sp = pg.ScatterPlotItem(x=xv[m], y=yv[m], size=6, pen=None, brush=brushes)
            host.p1.addItem(sp)
        else:
            host.p1.plot(xv[m], yv[m], pen=None, symbol="o", symbolSize=5,
                         symbolBrush=(33, 150, 243, 120), symbolPen=None, name="data")
        host.p1.setLabel("bottom", host.lbl("xlabel", self._cx.currentText()))
        host.p1.setLabel("left", host.lbl("ylabel", self._cy.currentText()))
        r = regress(xv, yv)
        if r:
            slope, inter, r2, n = r
            xline = np.array([np.nanmin(xv[m]), np.nanmax(xv[m])])
            host.p1.plot(xline, slope * xline + inter,
                         pen=pg.mkPen("#D32F2F", width=2), name="fit")
            host.p1.setTitle(host.lbl("title",
                             f"y = {slope:.4g}·x + {inter:.4g}   R² = {r2:.4f}   n = {n}"))
            host.set_status(f"slope={slope:.5g}  intercept={inter:.5g}  R²={r2:.5f}  n={n}")
        else:
            host.p1.setTitle(host.lbl("title", "Scatter"))
            host.set_status("Not enough finite points for regression.")
        host.autoscale()

    def render_mpl(self, fig):
        host = self.host
        ax = fig.add_subplot(111)
        xy = self._xy()
        if xy is None:
            ax.set_title("Scatter — pick X and Y")
            return
        xv, yv, tcolor = xy
        m = np.isfinite(xv) & np.isfinite(yv)
        if self._chk_ct.isChecked() and tcolor is not None and np.isfinite(tcolor[m]).any():
            sc = ax.scatter(xv[m], yv[m], s=16, c=tcolor[m], cmap="viridis",
                            alpha=0.7, edgecolors="none")
            cb = fig.colorbar(sc, ax=ax)
            cb.set_label("time (epoch s)")
        else:
            ax.scatter(xv[m], yv[m], s=14, c="#2196F3", alpha=0.5, edgecolors="none",
                       label="data")
        ax.set_xlabel(host.lbl("xlabel", self._cx.currentText()))
        ax.set_ylabel(host.lbl("ylabel", self._cy.currentText()))
        r = regress(xv, yv)
        if r:
            slope, inter, r2, n = r
            xline = np.array([np.nanmin(xv[m]), np.nanmax(xv[m])])
            ax.plot(xline, slope * xline + inter, color="#D32F2F", lw=2,
                    label=f"y={slope:.4g}x+{inter:.4g}\n$R^2$={r2:.4f}, n={n}")
            ax.set_title(host.lbl("title",
                         f"y = {slope:.4g}·x + {inter:.4g}   R² = {r2:.4f}   n = {n}"))
        else:
            ax.set_title(host.lbl("title", "Scatter"))
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=9)

    def csv_table(self):
        xy = self._xy()
        if xy is None:
            return None
        xv, yv, _ = xy
        m = np.isfinite(xv) & np.isfinite(yv)
        headers = [self._cx.currentText(), self._cy.currentText()]
        rows = [[f"{a:.6g}", f"{b:.6g}"] for a, b in zip(xv[m], yv[m])]
        return headers, rows


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
        host.p1.setLabel("bottom", host.lbl("xlabel", "Averaging time τ (s)"))
        host.p1.setLabel("left", host.lbl("ylabel", "Allan deviation σ(τ)"))
        imin = int(np.argmin(ad))
        host.p1.setTitle(host.lbl("title",
                         f"Allan deviation — min σ={ad[imin]:.3g} @ τ={taus[imin]:.0f}s"))
        host.set_status(f"optimal averaging ≈ {taus[imin]:.0f} s  (min Allan dev {ad[imin]:.3g})")
        host.autoscale()

    def render_mpl(self, fig):
        host = self.host
        ax = fig.add_subplot(111)
        res = host.resolve(self._c.currentText())
        out = None
        if res:
            ds, col, y, t = res
            out = allan_deviation(t, y)
        if out is None:
            ax.set_title("Allan deviation — insufficient/irregular data")
            return
        taus, ad = out
        ax.loglog(taus, ad, "o-", color="#2196F3", lw=1.8, ms=5,
                  label=self._c.currentText())
        imin = int(np.argmin(ad))
        ax.axvline(taus[imin], color="#888", ls="--", lw=1)
        ax.set_xlabel(host.lbl("xlabel", r"Averaging time $\tau$ (s)"))
        ax.set_ylabel(host.lbl("ylabel", r"Allan deviation $\sigma(\tau)$"))
        ax.set_title(host.lbl("title",
                     f"Allan deviation — min σ={ad[imin]:.3g} @ τ={taus[imin]:.0f}s"))
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(loc="best", fontsize=9)

    def csv_table(self):
        res = self.host.resolve(self._c.currentText())
        if not res:
            return None
        ds, col, y, t = res
        out = allan_deviation(t, y)
        if out is None:
            return None
        taus, ad = out
        return ["tau_s", "allan_dev"], [[f"{a:.6g}", f"{b:.6g}"] for a, b in zip(taus, ad)]


# ── Correlation heatmap ───────────────────────────────────────────────
@register_mode
class HeatmapMode(PlotMode):
    key = "heatmap"
    label = "Correlation heatmap"

    def __init__(self, host):
        super().__init__(host)
        self._w = None

    def options_widget(self):
        if self._w is not None:
            return self._w
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("선반에서 컬럼 2개 이상 선택\n(없으면 전체 컬럼 사용).\n"
                             "시간축이 있으면 첫 컬럼 시각격자에 맞춰 정렬."))
        b = QPushButton("↻ Compute")
        b.clicked.connect(self.render)
        lay.addWidget(b)
        lay.addStretch(1)
        self._w = w
        return w

    def _matrix(self):
        """선택(또는 전체) 컬럼들의 Pearson 상관행렬 → (names, 2D ndarray) 또는 None."""
        import pandas as pd
        host = self.host
        labels = host.selected_columns() or host.column_choices()
        labels = list(dict.fromkeys(labels))
        series, ref_t = {}, None
        for lab in labels:
            r = host.resolve(lab)
            if r is None:
                continue
            ds, col, y, t = r
            series[lab] = (y, t)
            if ref_t is None and t is not None:
                ref_t = t
        if len(series) < 2:
            return None
        data = {}
        if ref_t is not None:
            for lab, (y, t) in series.items():
                if t is not None:
                    m = np.isfinite(t) & np.isfinite(y)
                    if m.sum() >= 2:
                        o = np.argsort(t[m])
                        data[lab] = np.interp(ref_t, t[m][o], y[m][o],
                                              left=np.nan, right=np.nan)
                        continue
                yy = np.full(len(ref_t), np.nan)
                n = min(len(ref_t), len(y))
                yy[:n] = y[:n]
                data[lab] = yy
        else:
            n = min(len(y) for y, _ in series.values())
            for lab, (y, t) in series.items():
                data[lab] = y[:n]
        corr = pd.DataFrame(data).corr()
        return list(corr.columns), corr.to_numpy()

    @staticmethod
    def _short(names):
        return [n.split(":")[-1] for n in names]

    def render(self):
        host = self.host
        host.clear_plot()
        host.enable_right_axis(False)
        host.set_time_axis(False)
        mat = self._matrix()
        if mat is None:
            host.set_status("상관 히트맵: 컬럼 2개 이상 필요.")
            host.p1.setTitle("Correlation heatmap — need ≥2 columns")
            return
        names, C = mat
        img = pg.ImageItem()
        img.setOpts(axisOrder="row-major")
        img.setImage(C)
        img.setLevels([-1, 1])
        try:
            lut = pg.colormap.getFromMatplotlib("bwr").getLookupTable(0.0, 1.0, 256)
            img.setLookupTable(lut)
        except Exception:
            pass
        host.p1.addItem(img)
        short = self._short(names)
        ticks = [(i + 0.5, s) for i, s in enumerate(short)]
        host.p1.getAxis("bottom").setTicks([ticks])
        host.p1.getAxis("left").setTicks([ticks])
        # 셀 값 주석
        for i in range(len(names)):
            for j in range(len(names)):
                ti = pg.TextItem(f"{C[i, j]:.2f}", anchor=(0.5, 0.5),
                                 color="w" if abs(C[i, j]) > 0.5 else "k")
                ti.setPos(j + 0.5, i + 0.5)
                host.p1.addItem(ti)
        host.p1.invertY(True)
        host.p1.setTitle(host.lbl("title", "Correlation matrix (Pearson r)"))
        host.autoscale()
        host.set_status(f"{len(names)} columns")

    def render_mpl(self, fig):
        mat = self._matrix()
        ax = fig.add_subplot(111)
        if mat is None:
            ax.set_title("Correlation heatmap — need ≥2 columns")
            return
        names, C = mat
        short = self._short(names)
        im = ax.imshow(C, vmin=-1, vmax=1, cmap="bwr")
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(short, rotation=45, ha="right")
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(short)
        for i in range(len(names)):
            for j in range(len(names)):
                ax.text(j, i, f"{C[i, j]:.2f}", ha="center", va="center",
                        fontsize=8, color="white" if abs(C[i, j]) > 0.5 else "black")
        fig.colorbar(im, ax=ax, shrink=0.8)
        ax.set_title(self.host.lbl("title", "Correlation matrix (Pearson r)"))

    def csv_table(self):
        mat = self._matrix()
        if mat is None:
            return None
        names, C = mat
        short = self._short(names)
        headers = [""] + short
        rows = [[short[i]] + [f"{C[i, j]:.4f}" for j in range(len(names))]
                for i in range(len(names))]
        return headers, rows


# ── Histogram ─────────────────────────────────────────────────────────
@register_mode
class HistogramMode(PlotMode):
    key = "histogram"
    label = "Histogram"

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
        lay.addWidget(QLabel("Column:"))
        lay.addWidget(self._c)
        lay.addWidget(QLabel("Bins:"))
        self._bins = QSpinBox()
        self._bins.setRange(5, 500)
        self._bins.setValue(40)
        self._bins.valueChanged.connect(lambda *_: self.render())
        lay.addWidget(self._bins)
        self._chk_lod = QCheckBox("Show ≈3σ (LOD)")
        self._chk_lod.setToolTip("평균+3σ 위치에 검출한계 추정선")
        self._chk_lod.toggled.connect(lambda *_: self.render())
        lay.addWidget(self._chk_lod)
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
        return ({"col": self._c.currentText(), "bins": self._bins.value(),
                 "lod": self._chk_lod.isChecked()} if self._w else {})

    def from_config(self, cfg):
        if self._w:
            self._c.setCurrentText(cfg.get("col", ""))
            self._bins.setValue(int(cfg.get("bins", 40)))
            self._chk_lod.setChecked(bool(cfg.get("lod", False)))

    def _vals(self):
        r = self.host.resolve(self._c.currentText())
        if not r:
            return None
        y = r[2]
        return y[np.isfinite(y)]

    def render(self):
        host = self.host
        host.clear_plot()
        host.enable_right_axis(False)
        host.set_time_axis(False)
        v = self._vals()
        if v is None or v.size == 0:
            host.set_status("Pick a column.")
            host.p1.setTitle("Histogram — pick a column")
            return
        counts, edges = np.histogram(v, bins=self._bins.value())
        x = (edges[:-1] + edges[1:]) / 2.0
        widths = np.diff(edges)
        host.p1.addItem(pg.BarGraphItem(x=x, height=counts, width=widths * 0.95,
                                        brush=(33, 150, 243, 150), pen=None))
        mu, md, sd = float(np.mean(v)), float(np.median(v)), float(np.std(v))
        host.p1.addItem(pg.InfiniteLine(mu, angle=90,
                        pen=pg.mkPen("#D32F2F", width=2), label="mean"))
        host.p1.addItem(pg.InfiniteLine(md, angle=90,
                        pen=pg.mkPen("#388E3C", width=1, style=Qt.PenStyle.DashLine),
                        label="median"))
        if self._chk_lod.isChecked():
            host.p1.addItem(pg.InfiniteLine(mu + 3 * sd, angle=90,
                            pen=pg.mkPen("#7B1FA2", width=1, style=Qt.PenStyle.DotLine),
                            label="≈3σ"))
        host.p1.setLabel("bottom", host.lbl("xlabel", self._c.currentText()))
        host.p1.setLabel("left", host.lbl("ylabel", "count"))
        host.p1.setTitle(host.lbl("title", f"Histogram — μ={mu:.3g} σ={sd:.3g} n={v.size}"))
        host.autoscale()
        host.set_status(f"n={v.size}  μ={mu:.4g}  median={md:.4g}  σ={sd:.4g}")

    def render_mpl(self, fig):
        host = self.host
        ax = fig.add_subplot(111)
        v = self._vals()
        if v is None or v.size == 0:
            ax.set_title("Histogram — pick a column")
            return
        ax.hist(v, bins=self._bins.value(), color="#2196F3", alpha=0.75,
                edgecolor="white")
        mu, md, sd = float(np.mean(v)), float(np.median(v)), float(np.std(v))
        ax.axvline(mu, color="#D32F2F", lw=2, label=f"mean={mu:.3g}")
        ax.axvline(md, color="#388E3C", lw=1.2, ls="--", label=f"median={md:.3g}")
        if self._chk_lod.isChecked():
            ax.axvline(mu + 3 * sd, color="#7B1FA2", lw=1, ls=":",
                       label=f"≈3σ={mu + 3 * sd:.3g}")
        ax.set_xlabel(host.lbl("xlabel", self._c.currentText()))
        ax.set_ylabel(host.lbl("ylabel", "count"))
        ax.set_title(host.lbl("title", f"Histogram — μ={mu:.3g} σ={sd:.3g} n={v.size}"))
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)

    def csv_table(self):
        v = self._vals()
        if v is None or v.size == 0:
            return None
        counts, edges = np.histogram(v, bins=self._bins.value())
        x = (edges[:-1] + edges[1:]) / 2.0
        return ["bin_center", "count"], [[f"{a:.6g}", int(b)] for a, b in zip(x, counts)]


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
        # 라벨 오버라이드(빈 문자열=자동). 모드가 host.lbl(key, default)로 참조.
        self.custom = {"title": "", "xlabel": "", "ylabel": "", "rlabel": ""}
        self._modes = [cls(self) for cls in _MODES]
        self._mode = self._modes[0]
        self._init_ui()
        self._rebuild_mode_options()

    def lbl(self, key, default):
        """라벨 오버라이드가 있으면 그것을, 없으면 기본값을 반환."""
        v = (self.custom.get(key) or "").strip()
        return v if v else default

    # ── UI ────────────────────────────────────────────────────────────
    def _init_ui(self):
        from gui.flow_layout import FlowLayout
        root = QVBoxLayout(self)

        # 폭이 좁아지면 버튼이 다음 줄로 흐르게(잘림 방지)
        bar = FlowLayout(spacing=6)
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

        # 출판용 DPI(벡터 PDF/SVG에는 영향 없음, PNG에만 적용)
        bar.addWidget(QLabel("DPI:"))
        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(72, 1200)
        self._dpi_spin.setValue(300)
        self._dpi_spin.setSingleStep(50)
        self._dpi_spin.setToolTip("Publish PNG 해상도(벡터 PDF/SVG는 무관)")
        bar.addWidget(self._dpi_spin)
        for txt, fn, tip in (
                ("🖼 Publish", self._export_publish,
                 "matplotlib 고화질 출력 (PNG 고해상도 / 벡터 PDF·SVG)"),
                ("📷 PNG", self._export_png, "현재 화면 그대로 빠른 PNG (pyqtgraph 2400px)"),
                ("📑 CSV", self._export_csv, "시계열 데이터 CSV"),
                ("💾 Save", self._save_cfg, "플롯 설정 저장"),
                ("📂 Load", self._load_cfg, "플롯 설정 불러오기")):
            b = QPushButton(txt)
            b.setToolTip(tip)
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

        # 출판용 라벨 오버라이드(빈칸 = 자동)
        gb = QGroupBox("Labels (override, blank=auto)")
        fl = QFormLayout(gb)
        self._ed_title = QLineEdit()
        self._ed_x = QLineEdit()
        self._ed_y = QLineEdit()
        self._ed_r = QLineEdit()
        for ed in (self._ed_title, self._ed_x, self._ed_y, self._ed_r):
            ed.editingFinished.connect(self._on_labels_changed)
        fl.addRow("Title", self._ed_title)
        fl.addRow("X", self._ed_x)
        fl.addRow("Y-left", self._ed_y)
        fl.addRow("Y-right", self._ed_r)
        lv.addWidget(gb)
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
        # 히트맵이 남긴 invertY/커스텀틱을 원복(다른 모드 오염 방지)
        self.p1.invertY(False)
        for axn in ("bottom", "left"):
            self.p1.getAxis(axn).setTicks(None)
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

    def autoscale(self):
        """데이터에 맞춰 양축 범위 재설정. 빈 우측 ViewBox가 X를 [0,1]에 묶어
        시간축이 깨지던 문제(autorange 미작동)를 매 render 끝에 강제 해소한다."""
        vb = self.p1.getViewBox()
        self.vb_right.enableAutoRange(y=True)
        vb.enableAutoRange(x=True, y=True)
        vb.autoRange()
        self.update_views()

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
        self.add_paths(paths)

    def add_paths(self, paths):
        """파일 경로 목록을 선반에 로드(결과뷰어의 'Send to Plot Maker' 등에서 호출)."""
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
        return added

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

    def _on_labels_changed(self):
        self.custom = {"title": self._ed_title.text(), "xlabel": self._ed_x.text(),
                       "ylabel": self._ed_y.text(), "rlabel": self._ed_r.text()}
        self._mode.render()

    # ── Export / config ────────────────────────────────────────────────
    @staticmethod
    def _apply_korean_font(matplotlib):
        """한글 라벨이 □□로 깨지지 않게 한글 지원 폰트를 1회 설정(있으면)."""
        if getattr(PlotMakerWidget, "_kfont_done", False):
            return
        PlotMakerWidget._kfont_done = True
        try:
            from matplotlib import font_manager as fm
            avail = {f.name for f in fm.fontManager.ttflist}
            for cand in ("Malgun Gothic", "NanumGothic", "AppleGothic",
                         "Noto Sans CJK KR", "Noto Sans KR", "Gulim", "Batang"):
                if cand in avail:
                    matplotlib.rcParams["font.family"] = cand
                    break
            matplotlib.rcParams["axes.unicode_minus"] = False   # 음수 기호 깨짐 방지
        except Exception:
            pass

    def _export_publish(self):
        """현재 모드를 matplotlib로 재렌더 → 고화질 PNG / 벡터 PDF·SVG."""
        out, _ = QFileDialog.getSaveFileName(
            self, "Publish (high quality)", "plot.png",
            "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if not out:
            return
        if not os.path.splitext(out)[1]:
            out += ".png"
        try:
            import matplotlib
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
        except Exception as e:
            QMessageBox.warning(self, "Publish", f"matplotlib 사용 불가: {e}")
            return
        self._apply_korean_font(matplotlib)
        try:
            fig = Figure(figsize=(10, 5.5))
            FigureCanvasAgg(fig)          # savefig용 캔버스 부착(백엔드 무관)
            self._mode.render_mpl(fig)
            fig.tight_layout()
            fig.savefig(out, dpi=self._dpi_spin.value(), bbox_inches="tight")
            ext = os.path.splitext(out)[1].lstrip(".").upper()
            extra = f" @ {self._dpi_spin.value()}dpi" if ext == "PNG" else " (vector)"
            self.set_status(f"Published: {os.path.basename(out)} [{ext}{extra}]")
        except NotImplementedError:
            QMessageBox.information(self, "Publish",
                                   "이 모드는 아직 고화질 출력을 지원하지 않습니다.")
        except Exception as e:
            QMessageBox.warning(self, "Publish", f"Failed: {e}")

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
        """현재 모드가 제공하는 데이터(csv_table)를 CSV로 저장."""
        table = self._mode.csv_table()
        if not table:
            QMessageBox.information(self, "CSV",
                                   "현재 모드/선택에 내보낼 데이터가 없습니다.")
            return
        headers, rows = table
        out, _ = QFileDialog.getSaveFileName(self, "Export CSV", "plotmaker.csv",
                                             "CSV (*.csv)")
        if not out:
            return
        if not out.lower().endswith(".csv"):
            out += ".csv"
        try:
            import csv
            with open(out, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(headers)
                w.writerows(rows)
            self.set_status(f"CSV saved: {os.path.basename(out)} ({len(rows)} rows)")
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
            "labels": dict(self.custom),
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
        lab = cfg.get("labels", {})
        self._ed_title.setText(lab.get("title", ""))
        self._ed_x.setText(lab.get("xlabel", ""))
        self._ed_y.setText(lab.get("ylabel", ""))
        self._ed_r.setText(lab.get("rlabel", ""))
        self.custom = {"title": lab.get("title", ""), "xlabel": lab.get("xlabel", ""),
                       "ylabel": lab.get("ylabel", ""), "rlabel": lab.get("rlabel", "")}
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
