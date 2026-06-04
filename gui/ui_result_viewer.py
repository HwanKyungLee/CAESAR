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
    "R 트렌드 (시계열)": "r_trend",
    "R(λ) 곡선": "r_curve",
    "α trace (평균 스펙트럼)": "alpha_trace",
    "배열 스펙트럼": "array",
    "레퍼런스 스펙트럼": "reference",
    "농도·fit 시계열": "concentration",
}
_KIND_KO = {
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

        self._lbl = QLabel("결과 파일/폴더를 열어보세요 (R트렌드 / R(λ) / α / 레퍼런스 / 농도·fit).")
        self._lbl.setStyleSheet("color:#666;")
        bar.addWidget(self._lbl, 1)
        root.addLayout(bar)

        # 좌: 폴더 파일목록(형태별 그룹) / 우: 플롯 2단(위=주, 아래=보조)
        hsplit = QSplitter(Qt.Orientation.Horizontal)
        self._list = QListWidget()
        self._list.setMinimumWidth(230)
        self._list.itemClicked.connect(self._on_list_item)
        hsplit.addWidget(self._list)

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

    # ──────────────────────────────────────────────────────────────
    def _open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "결과 파일 선택", "",
            "결과 파일 (*.dat *.csv *.txt *.tsv);;모든 파일 (*)")
        if path:
            self._path = path
            self._reload()

    def _open_folder(self):
        """폴더를 받아 내부 결과파일을 형태별로 그룹·목록화. 항목 클릭 → 표시."""
        import glob
        d = QFileDialog.getExistingDirectory(self, "결과 폴더 선택")
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
        if name.endswith(".tsv") or "rms_cm" in head or name.endswith("_fit.tsv"):
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
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                if ln.startswith("# wavelength_nm:"):
                    try:
                        wave = np.array([float(v) for v in ln.split(":", 1)[1].strip().split("\t")
                                         if v.strip()], dtype=float)
                    except Exception:
                        pass
                    continue
                if ln.startswith("#") or ln.lower().startswith("row_idx"):
                    continue
                p = ln.rstrip().split("\t")
                if len(p) > 4:
                    try:
                        rows.append([float(x) for x in p[3:]])
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
