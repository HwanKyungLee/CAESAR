"""결과 뷰어 (Result Viewer)
===========================
파이프라인이 저장한 결과 파일을 GUI에 다시 넣어 바로 볼 수 있게 하는 탭.

지원(헤더/컬럼으로 자동 판별, 수동 선택도 가능):
  · R 트렌드   : Cold_*.dat / Hot_*.dat  (timestamp, R_mean, Leff, …) → R/Leff 시계열
  · R(λ) 곡선  : *_R.dat (wavelength_nm, R_raw, R_fitted, omr_d, Leff_km) → R(λ) + Leff(λ)
  · α 스펙트럼 : optical_depth 배열(헤더 없는 숫자) → α vs 픽셀/파장
  · 레퍼런스   : *.csv (Wavelength, Reflectivity …) → 스펙트럼
  · 농도 피팅  : *.csv (시간 + 가스 농도 컬럼) → 농도 시계열
"""
from __future__ import annotations

import os
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QComboBox, QSplitter, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt


# 수동 선택 콤보 라벨 ↔ 내부 kind 매핑
_KIND_BY_LABEL = {
    "자동 판별": "auto",
    "fit 결과 (가스별 ppb·RMS)": "fit",
    "R 트렌드 (시계열)": "r_trend",
    "R(λ) 곡선": "r_curve",
    "α trace (평균 스펙트럼)": "alpha_trace",
    "배열 스펙트럼": "array",
    "레퍼런스 스펙트럼": "reference",
    "농도·fit 시계열": "concentration",
}
_KIND_KO = {
    "fit": "fit 결과 (가스별 ppb·RMS)",
    "r_trend": "R 트렌드 (시계열)",
    "r_curve": "R(λ) 곡선",
    "alpha_trace": "α trace (평균 스펙트럼)",
    "array": "배열 스펙트럼",
    "reference": "레퍼런스 스펙트럼",
    "concentration": "농도·fit 시계열",
}
_PALETTE = ["#2196F3", "#FF6F00", "#D32F2F", "#388E3C", "#7B1FA2",
            "#0097A7", "#C2185B", "#5D4037"]


class ResultViewerWidget(QWidget):
    """저장된 결과 파일을 불러와 종류를 자동 판별하고 알맞은 그래프로 표시."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = None
        self._init_ui()

    # ──────────────────────────────────────────────────────────────
    def _init_ui(self):
        root = QVBoxLayout(self)

        # 상단 바: 파일/폴더 열기 + 종류 콤보 + 상태 라벨
        bar = QHBoxLayout()
        self._btn = QPushButton("📂 파일 열기")
        self._btn.setFixedWidth(110)
        self._btn.clicked.connect(self._open)
        bar.addWidget(self._btn)
        self._btn_folder = QPushButton("📁 폴더 열기")
        self._btn_folder.setFixedWidth(110)
        self._btn_folder.clicked.connect(self._open_folder)
        bar.addWidget(self._btn_folder)

        bar.addWidget(QLabel("종류:"))
        self._combo = QComboBox()
        self._combo.addItems(list(_KIND_BY_LABEL.keys()))
        self._combo.setFixedWidth(160)
        self._combo.currentIndexChanged.connect(self._reload)
        bar.addWidget(self._combo)

        self._lbl = QLabel("결과 파일/폴더를 열어보세요 (fit / R트렌드 / R(λ) / α / 레퍼런스).")
        self._lbl.setStyleSheet("color:#666;")
        bar.addWidget(self._lbl, 1)
        root.addLayout(bar)

        # fit 분석 컨트롤 바: 가스 선택 + 다중파일 비교 + 통계 라벨
        fbar = QHBoxLayout()
        fbar.addWidget(QLabel("가스:"))
        self._gas_combo = QComboBox()
        self._gas_combo.setFixedWidth(140)
        self._gas_combo.currentIndexChanged.connect(self._on_gas_changed)
        fbar.addWidget(self._gas_combo)
        self._btn_compare = QPushButton("📊 선택파일 겹쳐비교")
        self._btn_compare.setFixedWidth(150)
        self._btn_compare.clicked.connect(self._overlay_compare)
        fbar.addWidget(self._btn_compare)
        self._btn_td = QPushButton("🧪 NO2/PNs/ANs")
        self._btn_td.setFixedWidth(150)
        self._btn_td.setToolTip("Cold/PNs(ROI1)/ANs(ROI2) 결과 3개 선택 → 시간정렬·차분으로\n"
                                "NO2=Cold, PNs=PNs−Cold, ANs=ANs−PNs 유도농도 플롯")
        self._btn_td.clicked.connect(self._derive_no2_pns_ans)
        fbar.addWidget(self._btn_td)
        self._stats_lbl = QLabel("")
        self._stats_lbl.setStyleSheet("color:#444;")
        fbar.addWidget(self._stats_lbl, 1)
        root.addLayout(fbar)

        # 좌: 폴더 파일목록(형태별 그룹) / 우: 플롯 2단(위=주, 아래=보조)
        hsplit = QSplitter(Qt.Orientation.Horizontal)
        self._list = QListWidget()
        self._list.setMinimumWidth(230)
        # 다중 선택 → 여러 fit 파일 겹쳐비교 가능
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.itemClicked.connect(self._on_list_item)
        hsplit.addWidget(self._list)

        self._fit_cache = None   # 최근 로드한 fit 테이블(포인트클릭 α 팝업용)

        psplit = QSplitter(Qt.Orientation.Vertical)
        self._pw_top = pg.PlotWidget()
        self._pw_bot = pg.PlotWidget()
        for pw in (self._pw_top, self._pw_bot):
            pw.setBackground('w')
            pw.showGrid(x=True, y=True, alpha=0.3)
            pw.addLegend(offset=(10, 10))
        psplit.addWidget(self._pw_top)
        psplit.addWidget(self._pw_bot)
        psplit.setSizes([400, 250])
        hsplit.addWidget(psplit)
        hsplit.setSizes([240, 780])
        root.addWidget(hsplit, 1)

    # ── NO2 / PNs / ANs 유도 농도 (TD-CEAS) ──────────────────────────
    @staticmethod
    def _load_result_time_gas(path, gas='NO2'):
        """결과파일(_fit/_CH*.dat 등)에서 (시각 epoch[], gas 농도[])를 정렬해 반환."""
        import pandas as pd
        from datetime import datetime
        df = pd.read_csv(path, sep=None, engine='python', comment='#')
        df.columns = [str(c).strip() for c in df.columns]
        gcol = next((c for c in df.columns if c.lower() == gas.lower()), None)
        tcol = next((c for c in df.columns if c.lower() == 'time'), None)
        if gcol is None:
            raise RuntimeError(f"{os.path.basename(path)}: '{gas}' 컬럼 없음 (컬럼: {list(df.columns)[:8]})")
        gv = pd.to_numeric(df[gcol], errors='coerce').to_numpy(dtype=float)
        if tcol is None:
            t = np.arange(len(gv), dtype=float)
        else:
            t = np.full(len(gv), np.nan)
            for i, s in enumerate(df[tcol].astype(str)):
                for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
                    try:
                        t[i] = datetime.strptime(s, fmt).timestamp(); break
                    except ValueError:
                        pass
        m = np.isfinite(t) & np.isfinite(gv)
        t, gv = t[m], gv[m]
        o = np.argsort(t)
        return t[o], gv[o]

    def _derive_no2_pns_ans(self):
        """Cold/PNs/ANs 결과 3개 → 시간정렬·차분 → NO2/PNs/ANs 유도농도 플롯.
        NO2=Cold, PNs=PNs채널−Cold, ANs=ANs채널−PNs채널."""
        from PyQt6.QtWidgets import QMessageBox
        from gui.dlg_dir import dlg_dir
        paths = {}
        for role, title in (('Cold', "① Cold 결과 선택 (NO2)"),
                            ('PNs', "② PNs(ROI1, 180°C) 결과 선택"),
                            ('ANs', "③ ANs(ROI2, 300°C) 결과 선택")):
            p, _ = QFileDialog.getOpenFileName(self, title, dlg_dir("result"),
                                               "결과 (*.dat *.csv *.tsv *.txt);;모든 파일 (*)")
            if not p:
                return
            dlg_dir("result", p); paths[role] = p
        try:
            ct, cn = self._load_result_time_gas(paths['Cold'])
            pt, pn = self._load_result_time_gas(paths['PNs'])
            at, an = self._load_result_time_gas(paths['ANs'])
        except Exception as e:
            QMessageBox.warning(self, "로드 실패", str(e)); return
        if ct is None or len(ct) < 2:
            QMessageBox.warning(self, "데이터 부족", "Cold 결과에 Time/NO2가 부족합니다."); return
        # 시간정렬: PNs/ANs 채널 NO2를 Cold 시각격자에 보간(범위 밖은 NaN)
        pn_i = np.interp(ct, pt, pn, left=np.nan, right=np.nan) if len(pt) >= 2 else np.full_like(ct, np.nan)
        an_i = np.interp(ct, at, an, left=np.nan, right=np.nan) if len(at) >= 2 else np.full_like(ct, np.nan)
        no2 = cn
        pns = pn_i - cn
        ans = an_i - pn_i

        # 위: 유도농도(NO2/PNs/ANs), 아래: 원시 채널 NO2
        ax1 = pg.DateAxisItem(orientation='bottom')
        self._pw_top.setAxisItems({'bottom': ax1})
        self._pw_top.clear()
        self._pw_top.addLegend(offset=(10, 10))
        self._pw_top.plot(ct, no2, pen=pg.mkPen('#1f77b4', width=2), name='NO2 (Cold)')
        self._pw_top.plot(ct, pns, pen=pg.mkPen('#ff7f0e', width=2), name='PNs (=PNs−Cold)')
        self._pw_top.plot(ct, ans, pen=pg.mkPen('#2ca02c', width=2), name='ANs (=ANs−PNs)')
        self._pw_top.setLabel('left', '농도 (ppb)')
        self._pw_top.setLabel('bottom', '시간')

        ax2 = pg.DateAxisItem(orientation='bottom')
        self._pw_bot.setAxisItems({'bottom': ax2})
        self._pw_bot.clear()
        self._pw_bot.addLegend(offset=(10, 10))
        self._pw_bot.plot(ct, cn, pen=pg.mkPen('#1f77b4'), name='Cold NO2')
        self._pw_bot.plot(ct, pn_i, pen=pg.mkPen('#ff7f0e'), name='PNs채널 NO2')
        self._pw_bot.plot(ct, an_i, pen=pg.mkPen('#2ca02c'), name='ANs채널 NO2')
        self._pw_bot.setLabel('left', '채널 NO2 (ppb)')
        self._pw_bot.setLabel('bottom', '시간')
        self._lbl.setText("🧪 유도농도: NO2=Cold, PNs=PNs−Cold, ANs=ANs−PNs (Cold 시각격자에 정렬). "
                          "음수는 노이즈/시간불일치.")
        self._lbl.setStyleSheet("color:#1565C0;")

    # ──────────────────────────────────────────────────────────────
    def _open(self):
        from gui.dlg_dir import dlg_dir
        path, _ = QFileDialog.getOpenFileName(
            self, "결과 파일 선택", dlg_dir("result"),
            "결과 파일 (*.dat *.csv *.txt *.tsv);;모든 파일 (*)")
        if path:
            dlg_dir("result", path)
            self._path = path
            self._reload()

    def _open_folder(self):
        """폴더를 받아 내부 결과파일을 형태별로 그룹·목록화. 항목 클릭 → 표시."""
        import glob
        from gui.dlg_dir import dlg_dir
        d = QFileDialog.getExistingDirectory(self, "결과 폴더 선택", dlg_dir("result_folder"))
        if d:
            dlg_dir("result_folder", d)
        if not d:
            return
        files = []
        for ext in ("*.dat", "*.csv", "*.txt", "*.tsv"):
            files += glob.glob(os.path.join(d, ext))
            files += glob.glob(os.path.join(d, "**", ext), recursive=True)
        files = sorted(set(files))
        groups = {}
        for f in files:
            try:
                k = self._detect(f)
            except Exception:
                k = "array"
            groups.setdefault(k, []).append(f)
        self._list.clear()
        order = ["r_trend", "concentration", "r_curve", "array", "reference"]
        n = 0
        for k in order + [g for g in groups if g not in order]:
            for f in groups.get(k, []):
                it = QListWidgetItem(f"[{_KIND_KO.get(k, k)}] {os.path.basename(f)}")
                it.setData(Qt.ItemDataRole.UserRole, f)
                self._list.addItem(it)
                n += 1
        if n:
            self._lbl.setText(f"📁 {os.path.basename(d)} — 결과파일 {n}개. 왼쪽 목록에서 선택.")
            self._lbl.setStyleSheet("color:#1565C0;")
        else:
            self._lbl.setText(f"📁 {os.path.basename(d)} — 결과파일(.dat/.csv/.txt/.tsv) 없음.")
            self._lbl.setStyleSheet("color:#C62828;")

    def _on_list_item(self, item):
        f = item.data(Qt.ItemDataRole.UserRole)
        if f:
            self._path = f
            self._reload()

    def _reload(self):
        if not self._path:
            return
        forced = _KIND_BY_LABEL.get(self._combo.currentText(), "auto")
        kind = self._detect(self._path) if forced == "auto" else forced
        self._pw_top.clear()
        self._pw_bot.clear()
        self._pw_bot.show()
        try:
            handler = {
                "fit": self._plot_fit,
                "r_trend": self._plot_r_trend,
                "r_curve": self._plot_r_curve,
                "alpha_trace": self._plot_alpha_trace,
                "reference": self._plot_reference,
                "concentration": self._plot_concentration,
                "array": self._plot_array,
            }.get(kind, self._plot_array)
            handler(self._path)
            auto = "" if forced != "auto" else " (자동판별)"
            self._lbl.setText(f"✅ {os.path.basename(self._path)}  —  {_KIND_KO.get(kind, kind)}{auto}")
            self._lbl.setStyleSheet("color:#1565C0;")
        except Exception as e:
            self._lbl.setText(f"❌ 표시 실패: {e}  (종류를 수동 선택해 보세요)")
            self._lbl.setStyleSheet("color:#C62828;")

    # ── 자동 판별 ──────────────────────────────────────────────────
    @staticmethod
    def _detect(path: str) -> str:
        name = os.path.basename(path).lower()
        lines = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for _ in range(40):
                    ln = f.readline()
                    if not ln:
                        break
                    lines.append(ln)
        except OSError:
            return "array"
        head = "".join(lines).lower()

        if "timestamp" in head and "r_mean" in head:
            return "r_trend"
        if "wavelength_nm" in head and ("r_fitted" in head or "r_raw" in head):
            return "r_curve"
        if name.endswith("_r.dat"):
            return "r_curve"
        if "_alpha_trace" in name or "alpha export" in head:
            return "alpha_trace"
        # fit 결과: 헤더 row_idx … rms_cm-1 (가스별 ppb 컬럼)
        if name.endswith("_fit.tsv") or ("row_idx" in head and "rms_cm" in head):
            return "fit"
        if name.endswith(".tsv") or "rms_cm" in head:
            return "concentration"
        if "wavelength" in head and "reflect" in head:
            return "reference"
        if any(k in head for k in ("datetime", "timestamp", "doy", "no2", "hcho",
                                   "ppb", "ppt", "concentration", "conc")):
            return "concentration"
        return "array"

    # ── 공통: 구분자 추정 후 숫자 표 읽기 ──────────────────────────
    @staticmethod
    def _read_numeric(path, sep=None):
        return np.loadtxt(path, comments="#", delimiter=sep, ndmin=2)

    @staticmethod
    def _detect_sep(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                s = ln.strip()
                if not s or s.startswith("#"):
                    continue
                if "\t" in s:
                    return "\t"
                if "," in s:
                    return ","
                return None   # whitespace
        return None

    @staticmethod
    def _set_time_axis(pw, on: bool):
        ax = pg.DateAxisItem(orientation="bottom") if on else pg.AxisItem(orientation="bottom")
        pw.setAxisItems({"bottom": ax})

    # ── R 트렌드 (.dat) → R/Leff 시계열 ────────────────────────────
    def _plot_r_trend(self, path):
        ts, rmean, rstd, leff = [], [], [], []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                s = ln.rstrip("\n")
                if not s.strip() or s.startswith("#") or s.lower().startswith("timestamp"):
                    continue
                c = s.split("\t")
                if len(c) < 7:
                    continue
                try:
                    t = datetime.strptime(c[0].strip(), "%Y-%m-%d %H:%M")
                    rmean.append(float(c[2]) * 100.0)
                    rstd.append(float(c[3]) * 100.0)
                    leff.append(float(c[6]))
                    ts.append(t.timestamp())
                except (ValueError, IndexError):
                    continue
        if not ts:
            raise ValueError("R 트렌드 데이터 행을 찾지 못했습니다")
        ts = np.array(ts); rmean = np.array(rmean); rstd = np.array(rstd); leff = np.array(leff)
        self._set_time_axis(self._pw_top, True)
        self._set_time_axis(self._pw_bot, True)
        col = _PALETTE[0]
        self._pw_top.plot(ts, rmean, pen=pg.mkPen(col, width=2), symbol="o",
                          symbolSize=6, symbolBrush=col, name="R_mean (%)")
        err = pg.ErrorBarItem(x=ts, y=rmean, top=rstd, bottom=rstd, beam=0,
                              pen=pg.mkPen(col, width=1, style=Qt.PenStyle.DotLine))
        self._pw_top.addItem(err)
        self._pw_top.setLabel("left", "R (%)")
        self._pw_top.setTitle(f"R 시계열 — {len(ts)} cycles")
        # 0.9999 근처 변동 보이게 타이트 줌
        med = float(np.median(rmean)); sd = float(np.std(rmean))
        margin = max(sd * 4.0, 0.0015)
        self._pw_top.setYRange(med - margin, min(med + margin, 100.0 + 5e-4), padding=0)

        self._pw_bot.plot(ts, leff, pen=pg.mkPen(col, width=2), symbol="s",
                          symbolSize=5, symbolBrush=col, name="Leff (km)")
        self._pw_bot.setLabel("left", "Leff (km)")
        self._pw_bot.setLabel("bottom", "Date / Time")
        self._pw_bot.setTitle("Leff 시계열")

    # ── 파일별 R(λ) (_R.dat) → R(λ) + Leff(λ) ─────────────────────
    def _plot_r_curve(self, path):
        d = np.loadtxt(path, comments="#", ndmin=2)
        if d.shape[1] < 3:
            raise ValueError("R(λ) 컬럼이 부족합니다 (wave, R_raw, R_fit 필요)")
        wave, r_raw, r_fit = d[:, 0], d[:, 1], d[:, 2]
        self._set_time_axis(self._pw_top, False)
        self._set_time_axis(self._pw_bot, False)
        self._pw_top.plot(wave, r_raw, pen=None, symbol="o", symbolSize=3,
                          symbolBrush=(150, 150, 150, 140), name="R_raw")
        self._pw_top.plot(wave, r_fit, pen=pg.mkPen(_PALETTE[3], width=2.5),
                          name="R 5th-poly fit")
        self._pw_top.setLabel("left", "Reflectance R")
        self._pw_top.setTitle(f"R(λ) — {os.path.basename(path)}")
        fin = np.isfinite(r_fit)
        if fin.any():
            self._pw_top.setYRange(float(np.nanmin(r_fit[fin])), 1.0, padding=0.1)
        if d.shape[1] >= 5:
            self._pw_bot.plot(wave, d[:, 4], pen=pg.mkPen(_PALETTE[0], width=2),
                              name="Leff (km)")
            self._pw_bot.setLabel("left", "Leff (km)")
            self._pw_bot.setLabel("bottom", "Wavelength (nm)")
            self._pw_bot.show()
        else:
            self._pw_bot.hide()

    # ── α trace (alpha_trace.dat) → 평균 α 스펙트럼 ±1σ ─────────────
    def _plot_alpha_trace(self, path):
        wave = None
        rows = []
        alpha_start = 3   # 'px' 헤더에서 정함(구:3, 신:5 — doy/datetime 추가)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                if ln.startswith("# wavelength_nm:"):
                    try:
                        wave = np.array([float(v) for v in ln.split(":", 1)[1].strip().split("\t")
                                         if v.strip()], dtype=float)
                    except Exception:
                        pass
                    continue
                if ln.lower().startswith("row_idx"):
                    cols = ln.rstrip("\n").split("\t")
                    fp = next((i for i, c in enumerate(cols) if c.startswith("px")), None)
                    if fp is not None:
                        alpha_start = fp
                    continue
                if ln.startswith("#"):
                    continue
                p = ln.rstrip().split("\t")
                if len(p) > alpha_start:
                    try:
                        rows.append([float(x) for x in p[alpha_start:]])
                    except ValueError:
                        pass
        if not rows:
            raise ValueError("alpha 데이터 행이 없습니다")
        a = np.array(rows, dtype=float)
        if wave is None or len(wave) != a.shape[1]:
            wave = np.arange(a.shape[1], dtype=float)
        m = np.nanmean(a, axis=0); s = np.nanstd(a, axis=0)
        self._set_time_axis(self._pw_top, False)
        self._pw_top.plot(wave, m + s, pen=pg.mkPen((255, 140, 0, 90), width=1))
        self._pw_top.plot(wave, m - s, pen=pg.mkPen((255, 140, 0, 90), width=1))
        self._pw_top.plot(wave, m, pen=pg.mkPen(_PALETTE[1], width=2), name="mean α")
        self._pw_top.setLabel("left", "α (cm⁻¹)")
        self._pw_top.setLabel("bottom", "Wavelength (nm)")
        self._pw_top.setTitle(f"α 평균 스펙트럼 — {os.path.basename(path)} ({a.shape[0]} scans, ±1σ)")
        self._pw_bot.hide()

    # ── 레퍼런스 스펙트럼 (.csv) ───────────────────────────────────
    def _plot_reference(self, path):
        sep = self._detect_sep(path)
        d = np.loadtxt(path, comments="#", delimiter=sep, ndmin=2)
        if d.shape[1] >= 2:
            x, y = d[:, 0], d[:, 1]
        else:
            x, y = np.arange(len(d)), d[:, 0]
        self._set_time_axis(self._pw_top, False)
        self._pw_top.plot(x, y, pen=pg.mkPen(_PALETTE[4], width=2), name="reference")
        self._pw_top.setLabel("left", "Value")
        self._pw_top.setLabel("bottom", "Wavelength (nm)")
        self._pw_top.setTitle(f"레퍼런스 — {os.path.basename(path)}")
        self._pw_bot.hide()

    # ── 농도 시계열 (.csv) ─────────────────────────────────────────
    def _plot_concentration(self, path):
        import pandas as pd
        sep = self._detect_sep(path) or r"\s+"
        df = pd.read_csv(path, sep=sep, comment="#", engine="python")
        # 첫 컬럼을 시간축으로 시도
        xcol = df.columns[0]
        x_dt = pd.to_datetime(df[xcol], errors="coerce")
        if x_dt.notna().mean() > 0.5:
            x = x_dt.view("int64") / 1e9   # ns → s (epoch)
            self._set_time_axis(self._pw_top, True)
            self._pw_top.setLabel("bottom", "Date / Time")
            ycols = df.columns[1:]
        else:
            x = np.arange(len(df))
            self._set_time_axis(self._pw_top, False)
            self._pw_top.setLabel("bottom", "index")
            ycols = df.columns
        n = 0
        for i, c in enumerate(ycols):
            y = pd.to_numeric(df[c], errors="coerce").to_numpy()
            if not np.isfinite(y).any():
                continue
            self._pw_top.plot(np.asarray(x, float), y,
                              pen=pg.mkPen(_PALETTE[i % len(_PALETTE)], width=2),
                              name=str(c))
            n += 1
        if n == 0:
            raise ValueError("숫자 농도 컬럼을 찾지 못했습니다")
        self._pw_top.setLabel("left", "Concentration")
        self._pw_top.setTitle(f"농도 시계열 — {os.path.basename(path)} ({n} columns)")
        self._pw_bot.hide()

    # ── α/일반 숫자 배열 → vs 픽셀(또는 1열 vs 2열) ───────────────
    def _plot_array(self, path):
        sep = self._detect_sep(path)
        d = np.loadtxt(path, comments="#", delimiter=sep, ndmin=2)
        self._set_time_axis(self._pw_top, False)
        if d.shape[1] == 1:
            y = d[:, 0]
            self._pw_top.plot(np.arange(len(y)), y,
                              pen=pg.mkPen(_PALETTE[1], width=1.5), name="value")
            self._pw_top.setLabel("bottom", "Pixel / index")
        else:
            # 첫 컬럼을 x로 가정(파장일 수 있음), 나머지 컬럼들 플롯
            x = d[:, 0]
            for j in range(1, min(d.shape[1], 9)):
                self._pw_top.plot(x, d[:, j],
                                  pen=pg.mkPen(_PALETTE[(j - 1) % len(_PALETTE)], width=1.5),
                                  name=f"col{j}")
            self._pw_top.setLabel("bottom", "col0 (x)")
        self._pw_top.setLabel("left", "Value (α / optical depth 등)")
        self._pw_top.setTitle(f"배열 — {os.path.basename(path)}  shape={d.shape}")
        self._pw_bot.hide()

    # ── fit 결과 (_fit.tsv) → 가스별 ppb + RMS + 통계 ────────────────
    @staticmethod
    def _load_fit_table(path):
        """헤더 위치 기반 파싱(구·신 포맷). 구: row_idx T_C P_mbar <gases> rms_cm-1.
        신: row_idx doy datetime T_C P_mbar <gases> rms_cm-1.
        반환: {'row_idx','T','P','rms','doy','time'(epoch초),'gases':{name:ndarray}}."""
        import datetime as _dt
        hdr, rows = None, []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                s = ln.rstrip("\n")
                if not s.strip() or s.startswith("#"):
                    continue
                if s.lower().startswith("row_idx"):
                    hdr = s.split("\t")
                    continue
                if hdr is None:
                    continue
                rows.append(s.split("\t"))
        if hdr is None or not rows:
            raise ValueError("fit 결과 헤더/데이터 행을 찾지 못했습니다")
        idx = {n: i for i, n in enumerate(hdr)}
        rms_i = idx.get("rms_cm-1", len(hdr) - 1)
        p_i = idx.get("P_mbar", 2)
        gas_cols = list(range(p_i + 1, rms_i))   # P_mbar 다음 ~ rms 직전 = 가스들

        def colf(j):
            out = np.full(len(rows), np.nan)
            for k, r in enumerate(rows):
                if j is not None and j < len(r):
                    try:
                        out[k] = float(r[j])
                    except ValueError:
                        pass
            return out

        out = {"row_idx": colf(idx.get("row_idx", 0)), "T": colf(idx.get("T_C")),
               "P": colf(p_i), "rms": colf(rms_i), "doy": colf(idx.get("doy")),
               "time": None, "gases": {}, "path": path}
        for j in gas_cols:
            out["gases"][hdr[j]] = colf(j)

        # datetime 컬럼 → epoch 초(시간축용)
        di = idx.get("datetime")
        if di is not None:
            ts = np.full(len(rows), np.nan)
            for k, r in enumerate(rows):
                if di < len(r) and r[di].strip():
                    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                        try:
                            ts[k] = _dt.datetime.strptime(r[di].strip(), fmt).timestamp()
                            break
                        except ValueError:
                            pass
            if np.isfinite(ts).any():
                out["time"] = ts
        return out

    def _sync_gas_combo(self, names):
        """가스 콤보를 fit 파일의 가스목록으로 (선택 유지하며) 갱신."""
        want = ["전체"] + list(names)
        cur = self._gas_combo.currentText()
        have = [self._gas_combo.itemText(i) for i in range(self._gas_combo.count())]
        if have == want:
            return
        self._gas_combo.blockSignals(True)
        self._gas_combo.clear()
        self._gas_combo.addItems(want)
        if cur in want:
            self._gas_combo.setCurrentText(cur)
        self._gas_combo.blockSignals(False)

    def _on_gas_changed(self, _idx):
        # fit 모드에서 가스 선택 바뀌면 현재 파일 다시 그림
        if self._fit_cache and self._path:
            self._pw_top.clear(); self._pw_bot.clear(); self._pw_bot.show()
            self._plot_fit(self._path)

    def _plot_fit(self, path):
        t = self._load_fit_table(path)
        self._fit_cache = t
        self._sync_gas_combo(list(t["gases"].keys()))
        sel = self._gas_combo.currentText() or "전체"
        names = list(t["gases"].keys()) if sel in ("전체", "") else [sel]

        # x축: 실제 시각(datetime)이 있으면 그걸로(실시간 시계열), 없으면 row_idx
        has_time = t.get("time") is not None and np.isfinite(t["time"]).any()
        x = t["time"] if has_time else t["row_idx"]
        self._set_time_axis(self._pw_top, has_time)
        self._set_time_axis(self._pw_bot, has_time)
        xlabel = "Date / Time" if has_time else "row_idx (≈시간)"

        stats = []
        for i, g in enumerate(names):
            y = t["gases"].get(g)
            if y is None:
                continue
            col = _PALETTE[i % len(_PALETTE)]
            self._pw_top.plot(x, y, pen=pg.mkPen(col, width=2), symbol="o",
                              symbolSize=4, symbolBrush=col, name=f"{g} (ppb)")
            fin = y[np.isfinite(y)]
            if fin.size:
                mu, sd = float(np.mean(fin)), float(np.std(fin))
                if sd > 0:
                    om = np.abs(y - mu) > 3 * sd
                    nout = int(np.sum(om))
                    if om.any():
                        self._pw_top.plot(x[om], y[om], pen=None, symbol="x",
                                          symbolSize=11, symbolBrush=(211, 47, 47))
                else:
                    nout = 0
                stats.append(f"{g}: μ={mu:.3g}±{sd:.2g} ppb · ±3σ이상치 {nout}")
        self._pw_top.setLabel("left", "농도 (ppb)")
        self._pw_top.setLabel("bottom", xlabel)
        self._pw_top.setTitle(f"fit 결과 — {os.path.basename(path)} ({len(x)} scans)")

        self._pw_bot.show()
        self._pw_bot.plot(x, t["rms"], pen=pg.mkPen(_PALETTE[2], width=2), name="RMS")
        self._pw_bot.setLabel("left", "RMS (cm⁻¹)")
        self._pw_bot.setLabel("bottom", xlabel)
        self._pw_bot.setTitle("RMS 시계열")

        self._stats_lbl.setText("   |   ".join(stats))
        # 포인트 클릭 → 해당 scan의 α 스펙트럼 팝업(형제 alpha_trace.dat 있으면)
        try:
            self._pw_top.scene().sigMouseClicked.disconnect(self._on_fit_point_clicked)
        except (TypeError, RuntimeError):
            pass
        self._pw_top.scene().sigMouseClicked.connect(self._on_fit_point_clicked)

    def _overlay_compare(self):
        """목록에서 다중 선택된 fit 파일들의 현재 가스 ppb·RMS를 겹쳐 비교."""
        items = self._list.selectedItems()
        paths = []
        for it in items:
            p = it.data(Qt.ItemDataRole.UserRole)
            if p and (p.lower().endswith("_fit.tsv") or self._detect(p) == "fit"):
                paths.append(p)
        if not paths:
            self._stats_lbl.setText("⚠️ 비교하려면 목록에서 fit 파일을 2개 이상 선택하세요.")
            return
        gas = self._gas_combo.currentText()
        self._pw_top.clear(); self._pw_bot.clear(); self._pw_bot.show()
        self._set_time_axis(self._pw_top, False)
        self._set_time_axis(self._pw_bot, False)
        summ = []
        for i, p in enumerate(paths):
            try:
                t = self._load_fit_table(p)
            except Exception:
                continue
            g = gas if gas in t["gases"] else next(iter(t["gases"]), None)
            if g is None:
                continue
            col = _PALETTE[i % len(_PALETTE)]
            lbl = os.path.basename(p).replace("_fit.tsv", "")
            y = t["gases"][g]
            self._pw_top.plot(t["row_idx"], y, pen=pg.mkPen(col, width=2), name=f"{lbl}:{g}")
            self._pw_bot.plot(t["row_idx"], t["rms"],
                              pen=pg.mkPen(col, width=1, style=Qt.PenStyle.DashLine),
                              name=f"{lbl} RMS")
            fin = y[np.isfinite(y)]
            if fin.size:
                summ.append(f"{lbl}: μ={float(np.mean(fin)):.3g}±{float(np.std(fin)):.2g}")
        self._pw_top.setLabel("left", "농도 (ppb)")
        self._pw_top.setLabel("bottom", "row_idx (≈시간)")
        self._pw_top.setTitle(f"비교 — {gas} ({len(paths)} files)")
        self._pw_bot.setLabel("left", "RMS (cm⁻¹)")
        self._stats_lbl.setText("   |   ".join(summ))

    def _on_fit_point_clicked(self, ev):
        """ppb 그래프 클릭 → 가장 가까운 scan의 α 스펙트럼을 팝업(형제 alpha_trace)."""
        t = self._fit_cache
        if not t or self._path is None:
            return
        try:
            vb = self._pw_top.getViewBox()
            mp = vb.mapSceneToView(ev.scenePos())
            xclick = float(mp.x())
        except Exception:
            return
        # 플롯에 쓴 x축(시간 우선, 없으면 row_idx)으로 가장 가까운 점을 찾는다
        xarr = t["time"] if (t.get("time") is not None and np.isfinite(t["time"]).any()) else t["row_idx"]
        j = int(np.nanargmin(np.abs(xarr - xclick)))
        row_idx = int(t["row_idx"][j])
        alpha_path = self._sibling_alpha(self._path)
        if not alpha_path:
            self._stats_lbl.setText(f"row {row_idx}: 형제 alpha_trace.dat을 못 찾아 α 팝업 불가")
            return
        self._show_alpha_popup(alpha_path, row_idx)

    @staticmethod
    def _sibling_alpha(fit_path):
        """`*_fit.tsv` 옆의 대응 `*_alpha_trace.dat` 경로 추정."""
        base = os.path.basename(fit_path)
        stem = base[:-8] if base.endswith("_fit.tsv") else os.path.splitext(base)[0]
        d = os.path.dirname(fit_path)
        cands = [os.path.join(d, stem + "_alpha_trace.dat"),
                 os.path.join(d, stem + ".dat")]
        import glob
        cands += glob.glob(os.path.join(d, stem + "*alpha_trace.dat"))
        for c in cands:
            if os.path.isfile(c):
                return c
        return None

    def _show_alpha_popup(self, alpha_path, row_idx):
        """alpha_trace.dat에서 row_idx 행의 α 스펙트럼을 팝업으로 표시."""
        wave = None
        target = None
        alpha_start = 3
        with open(alpha_path, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                if ln.startswith("# wavelength_nm:"):
                    try:
                        wave = np.array([float(v) for v in ln.split(":", 1)[1].strip().split("\t")
                                         if v.strip()], dtype=float)
                    except Exception:
                        pass
                    continue
                if ln.lower().startswith("row_idx"):
                    cols = ln.rstrip("\n").split("\t")
                    fp = next((i for i, c in enumerate(cols) if c.startswith("px")), None)
                    if fp is not None:
                        alpha_start = fp
                    continue
                if ln.startswith("#"):
                    continue
                p = ln.rstrip().split("\t")
                if len(p) > alpha_start:
                    try:
                        if int(float(p[0])) == row_idx:
                            target = np.array([float(x) for x in p[alpha_start:]], dtype=float)
                            break
                    except ValueError:
                        continue
        if target is None:
            self._stats_lbl.setText(f"alpha_trace에 row {row_idx} 없음")
            return
        if wave is None or len(wave) != len(target):
            wave = np.arange(len(target), dtype=float)
        from PyQt6.QtWidgets import QDialog, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle(f"α 스펙트럼 — row {row_idx} ({os.path.basename(alpha_path)})")
        dlg.resize(720, 460)
        lay = QVBoxLayout(dlg)
        pw = pg.PlotWidget()
        pw.setBackground("w"); pw.showGrid(x=True, y=True, alpha=0.3)
        pw.plot(wave, target, pen=pg.mkPen(_PALETTE[1], width=1.5))
        pw.setLabel("left", "α (cm⁻¹)"); pw.setLabel("bottom", "Wavelength (nm)")
        pw.setTitle(f"α — row {row_idx}")
        lay.addWidget(pw)
        dlg.show()
