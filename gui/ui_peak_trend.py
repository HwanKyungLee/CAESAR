"""Setup 탭 피크 트렌드 뷰어 — flag별(ZA/He/Sampling) 피크값 시계열.

raw .dat 를 읽어 행별 peak intensity 를 flag(ZA=500/He=510/Sampling=1)별로 모아,
ZA/He 는 측정 cycle 단위, Sampling 은 시간 bin 단위로 평균·min/max 를 그린다.
시간축은 bytepack(=박사님 doy)로 계산(naive). tools/plot_spectra_by_date.py 의 GUI판.
"""
import os
from datetime import datetime, timedelta

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QComboBox, QCheckBox, QDoubleSpinBox, QFileDialog, QMessageBox,
)

from core.raw_parser import (
    RawParser, FLAG_ZA, FLAG_HE, FLAG_AMBIENT, SPEC_PRIMARY, SPEC_SECONDARY,
)
from gui.dlg_dir import dlg_dir

_LABEL = {FLAG_ZA: "ZA (500)", FLAG_HE: "He (510)", FLAG_AMBIENT: "Sampling (1)"}
_COLOR = {FLAG_ZA: "#2196F3", FLAG_HE: "#FF6F00", FLAG_AMBIENT: "#388E3C"}


def _find_files(raw_dir, prefix):
    hits = []
    for root, _d, names in os.walk(raw_dir):
        for n in names:
            if n.startswith(prefix) and n.endswith(".dat"):
                hits.append(os.path.join(root, n))
    return sorted(hits)


def _stats(seg):
    return float(np.nanmean(seg)), float(np.nanmin(seg)), float(np.nanmax(seg))


def _group_events(ts, pk, gap_min):
    """gap_min 분 이상 끊기면 새 cycle. 반환 (T,avg,lo,hi) datetime 배열."""
    if len(ts) == 0:
        return (np.array([]),) * 4
    order = np.argsort(ts); ts, pk = np.array(ts)[order], np.array(pk)[order]
    gap = timedelta(minutes=gap_min)
    T, A, LO, HI = [], [], [], []
    start = 0
    for i in range(1, len(ts)):
        if ts[i] - ts[i - 1] > gap:
            a, lo, hi = _stats(pk[start:i])
            T.append(ts[start] + (ts[i - 1] - ts[start]) / 2); A.append(a); LO.append(lo); HI.append(hi)
            start = i
    a, lo, hi = _stats(pk[start:])
    T.append(ts[start] + (ts[-1] - ts[start]) / 2); A.append(a); LO.append(lo); HI.append(hi)
    return np.array(T), np.array(A), np.array(LO), np.array(HI)


def _bin_series(ts, pk, bin_min):
    if len(ts) == 0:
        return (np.array([]),) * 4
    order = np.argsort(ts); ts, pk = np.array(ts)[order], np.array(pk)[order]
    t0 = ts[0]; width = timedelta(minutes=bin_min)
    keys = np.array([int((t - t0) / width) for t in ts])
    T, A, LO, HI = [], [], [], []
    for k in np.unique(keys):
        seg = pk[keys == k]
        a, lo, hi = _stats(seg)
        T.append(t0 + width * (int(k) + 0.5)); A.append(a); LO.append(lo); HI.append(hi)
    return np.array(T), np.array(A), np.array(LO), np.array(HI)


class PeakTrendWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(dict)        # flag -> {T(epoch), A, LO, HI, n}
    failed = pyqtSignal(str)

    def __init__(self, raw_dir, dates, ch_block, flags, gap_min, bin_min, p_lo, p_hi):
        super().__init__()
        self.raw_dir = raw_dir; self.dates = dates; self.ch_block = ch_block
        self.flags = set(flags); self.gap_min = gap_min; self.bin_min = bin_min
        self.p_lo = p_lo; self.p_hi = p_hi

    def run(self):
        try:
            raw_ts = {f: [] for f in self.flags}
            raw_pk = {f: [] for f in self.flags}
            for date_str in self.dates:
                prefix = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                year = int(date_str[:4])
                files = _find_files(self.raw_dir, prefix)
                if not files:
                    self.progress.emit(f"{prefix}: no files"); continue
                for fi, path in enumerate(files):
                    self.progress.emit(f"{prefix}: {fi+1}/{len(files)} {os.path.basename(path)}")
                    try:
                        parser = RawParser(path)
                        ch_key = next((c for c, b in parser.layout.spec_blocks.items()
                                       if b == self.ch_block), None)
                        if ch_key is None:
                            continue
                        for row, specs in parser.iter_rows_with_spectra(channels=(ch_key,)):
                            if row.flag not in self.flags:
                                continue
                            sp = specs.get(ch_key)
                            if sp is None or sp.size == 0:
                                continue
                            bp = row.bytepack_sec
                            if bp != bp:   # NaN
                                continue
                            t = datetime(year, 1, 1) + timedelta(seconds=float(bp))
                            raw_pk[row.flag].append(float(np.nanmax(sp[self.p_lo:self.p_hi])))
                            raw_ts[row.flag].append(t)
                    except Exception as e:
                        self.progress.emit(f"  skip {os.path.basename(path)}: {e}")
            out = {}
            for f in self.flags:
                ts, pk = raw_ts[f], raw_pk[f]
                if not ts:
                    continue
                if f == FLAG_AMBIENT:
                    T, A, LO, HI = _bin_series(ts, pk, self.bin_min)
                else:
                    T, A, LO, HI = _group_events(ts, pk, self.gap_min)
                out[f] = {
                    "T": np.array([t.timestamp() for t in T]),
                    "A": A, "LO": LO, "HI": HI, "n": len(ts),
                }
            self.done.emit(out)
        except Exception as e:
            import traceback
            self.failed.emit(f"{e}\n{traceback.format_exc()}")


class PeakTrendDialog(QDialog):
    def __init__(self, parent=None, default_dir=""):
        super().__init__(parent)
        self.setWindowTitle("📈 Peak Trend (He / ZA / Sampling)")
        self.resize(980, 600)
        self._worker = None
        self._build(default_dir)

    def _build(self, default_dir):
        root = QVBoxLayout(self)

        # raw 폴더
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Raw folder:"))
        self._ed_dir = QLineEdit(default_dir or dlg_dir("peaktrend_raw"))
        r1.addWidget(self._ed_dir, 1)
        b = QPushButton("…"); b.setFixedWidth(34); b.clicked.connect(self._pick_dir)
        r1.addWidget(b)
        root.addLayout(r1)

        # 날짜/채널/flag/bin
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Dates (YYYYMMDD, space-sep):"))
        self._ed_dates = QLineEdit()
        self._ed_dates.setPlaceholderText("e.g. 20260601 20260602")
        r2.addWidget(self._ed_dates, 1)
        r2.addWidget(QLabel("Channel:"))
        self._cb_ch = QComboBox(); self._cb_ch.addItems(["PNs/Cold (primary)", "ANs (secondary)"])
        r2.addWidget(self._cb_ch)
        root.addLayout(r2)

        r3 = QHBoxLayout()
        self._ck_za = QCheckBox("ZA"); self._ck_za.setChecked(True)
        self._ck_he = QCheckBox("He"); self._ck_he.setChecked(True)
        self._ck_amb = QCheckBox("Sampling"); self._ck_amb.setChecked(True)
        for c in (self._ck_za, self._ck_he, self._ck_amb):
            r3.addWidget(c)
        r3.addSpacing(16)
        r3.addWidget(QLabel("Sampling bin (min):"))
        self._sp_bin = QDoubleSpinBox(); self._sp_bin.setRange(0.1, 120); self._sp_bin.setValue(1.0); self._sp_bin.setDecimals(1)
        r3.addWidget(self._sp_bin)
        r3.addWidget(QLabel("cycle gap (min):"))
        self._sp_gap = QDoubleSpinBox(); self._sp_gap.setRange(0.5, 120); self._sp_gap.setValue(5.0); self._sp_gap.setDecimals(1)
        r3.addWidget(self._sp_gap)
        r3.addWidget(QLabel("peak px:"))
        self._sp_lo = QDoubleSpinBox(); self._sp_lo.setRange(0, 2048); self._sp_lo.setValue(0); self._sp_lo.setDecimals(0)
        self._sp_hi = QDoubleSpinBox(); self._sp_hi.setRange(1, 2048); self._sp_hi.setValue(2048); self._sp_hi.setDecimals(0)
        r3.addWidget(self._sp_lo); r3.addWidget(QLabel("~")); r3.addWidget(self._sp_hi)
        r3.addStretch(1)
        root.addLayout(r3)

        # 플롯
        self._pw = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self._pw.setBackground("w"); self._pw.showGrid(x=True, y=True, alpha=0.3)
        self._pw.addLegend(offset=(10, 10))
        self._pw.setLabel("left", "Peak counts"); self._pw.setLabel("bottom", "Time")
        root.addWidget(self._pw, 1)

        # 실행/상태
        run = QHBoxLayout()
        self._btn_run = QPushButton("▶ Plot")
        self._btn_run.setStyleSheet("font-weight:bold; padding:6px;")
        self._btn_run.clicked.connect(self._run)
        run.addWidget(self._btn_run, 1)
        self._lbl = QLabel(""); self._lbl.setStyleSheet("color:#1565C0;")
        run.addWidget(self._lbl, 2)
        root.addLayout(run)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Raw folder", self._ed_dir.text() or dlg_dir("peaktrend_raw"))
        if d:
            dlg_dir("peaktrend_raw", d); self._ed_dir.setText(d)

    def _run(self):
        raw_dir = self._ed_dir.text().strip()
        if not os.path.isdir(raw_dir):
            QMessageBox.warning(self, "Folder", "Specify a valid Raw folder."); return
        dates = self._ed_dates.text().split()
        if not dates:
            QMessageBox.warning(self, "Dates", "Enter at least one YYYYMMDD date."); return
        dlg_dir("peaktrend_raw", raw_dir)
        flags = []
        if self._ck_za.isChecked(): flags.append(FLAG_ZA)
        if self._ck_he.isChecked(): flags.append(FLAG_HE)
        if self._ck_amb.isChecked(): flags.append(FLAG_AMBIENT)
        if not flags:
            QMessageBox.warning(self, "Flag", "Select at least one of ZA/He/Sampling."); return
        ch_block = SPEC_SECONDARY if self._cb_ch.currentIndex() == 1 else SPEC_PRIMARY
        self._btn_run.setEnabled(False); self._pw.clear()
        self._worker = PeakTrendWorker(
            raw_dir, sorted(dates), ch_block, flags,
            self._sp_gap.value(), self._sp_bin.value(),
            int(self._sp_lo.value()), int(self._sp_hi.value()))
        self._worker.progress.connect(lambda m: self._lbl.setText(m))
        self._worker.done.connect(self._plot)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_fail(self, msg):
        self._btn_run.setEnabled(True)
        self._lbl.setText("❌ Failed")
        QMessageBox.warning(self, "Failed", msg)

    def _plot(self, out):
        self._btn_run.setEnabled(True)
        self._pw.clear()
        if not out:
            self._lbl.setText("No data"); return
        for flag in (FLAG_ZA, FLAG_HE, FLAG_AMBIENT):
            d = out.get(flag)
            if not d or len(d["T"]) == 0:
                continue
            col = _COLOR[flag]
            T = d["T"]
            self._pw.plot(T, d["HI"], pen=pg.mkPen(col, width=1, style=Qt.PenStyle.DotLine))
            self._pw.plot(T, d["LO"], pen=pg.mkPen(col, width=1, style=Qt.PenStyle.DotLine))
            self._pw.plot(T, d["A"], pen=pg.mkPen(col, width=1.5), symbol="o", symbolSize=5,
                          symbolBrush=col, name=f"{_LABEL[flag]} (avg·min/max, {d['n']} rows)")
        self._lbl.setText("✅ Done (avg points + min/max dotted)")
