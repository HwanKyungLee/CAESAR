"""gui/ui_dialogs_r.py
R 시계열: _RTrendWorker, RCalibratorDialog(RTrendMonitorDialog 별칭)
"""
import sys
import os
import math
import datetime
import time
import json
import numpy as np
import pandas as pd
import pyqtgraph as pg
from core.data_io import ui_scale as _ui_scale
pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['axes.unicode_minus'] = False

# [PyQt6] Backend
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector
from matplotlib.ticker import ScalarFormatter

from scipy.optimize import curve_fit, least_squares, lsq_linear
from scipy.interpolate import interp1d
from scipy.signal import convolve
from scipy.signal import find_peaks
from scipy.stats import norm
from scipy.signal.windows import tukey
from scipy.ndimage import gaussian_filter1d
from numpy.polynomial import chebyshev

from core.data_io import DataIO

# [PyQt6] Modules
from gui.dlg_dir import dlg_dir
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QFileDialog,
                             QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
                             QProgressBar, QGroupBox, QLineEdit, QScrollArea, QDialog,
                             QComboBox, QSplitter, QTabWidget, QDoubleSpinBox, QSpinBox,
                             QCheckBox, QGridLayout, QInputDialog, QRadioButton, QButtonGroup,
                             QSplashScreen, QDialogButtonBox, QStackedWidget, QFormLayout,
                             QTextEdit, QFrame)
from PyQt6.QtCore import Qt, QThread, QTimer, QSettings, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPixmap
# =============================================================================
# R Trend Monitor Components (UI + Worker)
# =============================================================================

from gui.r_workers import (_LiveStream, _RTrendWorker, _RTExportWorker,
                           _ChannelRWorker)


# ── 채널 색상 팔레트 ─────────────────────────────────────────────────────────
_CH_COLORS = [
    '#2196F3',  # blue
    '#FF6F00',  # orange
    '#D32F2F',  # red
    '#388E3C',  # green
    '#7B1FA2',  # purple
    '#0097A7',  # teal
    '#795548',  # brown
]


class RCalibratorDialog(QDialog):
    """R Calibrator — 채널별 반사율 교정 & R(t) 계산."""

    data_ready = pyqtSignal(object, object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("R Calibrator — per-channel reflectance calibration")
        self.resize(1100, 760)
        self._worker   = None
        self._t_start  = None
        self._timer    = QTimer(self)
        self._timer.timeout.connect(self._tick_elapsed)
        self._all_results = []
        self._ch_rows     = []   # list of QFrame per-channel row widgets

        self._init_ui()

        if parent is not None:
            if hasattr(parent, 'spin_d_len'):
                self._spin_cavity_len.setValue(parent.spin_d_len.value())
            if hasattr(parent, 'spin_rl_factor'):
                self._spin_rl.setValue(parent.spin_rl_factor.value())

        self._load_from_left_panel()

    def _pick_dir(self, line_edit):
        d = QFileDialog.getExistingDirectory(self, "Select folder", dlg_dir("r_folder"))
        dlg_dir("r_folder", d)
        if d: line_edit.setText(d)

    def _pick_file(self, line_edit):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select file", dlg_dir("r_file"), "Text files (*.txt *.dat *.csv);;All Files (*)")
        dlg_dir("r_file", f)
        if f: line_edit.setText(f)

    @staticmethod
    def _norm_date(s, default):
        """'20260531' 또는 '2026-05-31' → '2026-05-31'. 빈 값이면 default."""
        s = (s or "").strip().replace("-", "")
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        return default

    @staticmethod
    def _files_in_range(directory, lo, hi):
        """directory(및 하위폴더)에서 파일명 날짜(YYYY-MM-DD)가 [lo,hi]인 .dat 정렬 반환.
        부모폴더를 주면 월별 하위폴더를 함께 스캔해 월 경계를 넘는다."""
        import glob, re
        pats = (glob.glob(os.path.join(directory, "*.dat")) +
                glob.glob(os.path.join(directory, "**", "*.dat"), recursive=True))
        out = []
        for f in set(pats):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(f))
            if m and lo <= m.group(1) <= hi:
                out.append(f)
        return sorted(out)

    def _init_ui(self):
        main = QVBoxLayout(self)
        main.setSpacing(5)

        # ── 채널 목록 ────────────────────────────────────────────────────────
        grp_ch = QGroupBox("Channels")
        grp_ch_lay = QVBoxLayout(grp_ch)
        grp_ch_lay.setSpacing(3)
        grp_ch_lay.setContentsMargins(6, 6, 6, 4)

        hdr = QHBoxLayout()
        btn_load_panel = QPushButton("🔄  Load channels from left panel")
        btn_load_panel.setStyleSheet(
            "background-color:#1565C0;color:white;font-weight:bold;")
        btn_load_panel.setToolTip(
            "Reads the left panel's channel settings (wavecal·R-window·TZ) to fill the rows.\n"
            "Click to sync if you changed or added channels.")
        btn_load_panel.clicked.connect(self._load_from_left_panel)
        hdr.addWidget(btn_load_panel)
        btn_add_ch = QPushButton("＋  Add channel")
        btn_add_ch.setFixedWidth(100)
        btn_add_ch.clicked.connect(
            lambda: self._add_ch_row(
                self._make_ch_row_widget(len(self._ch_rows) + 1)))
        hdr.addWidget(btn_add_ch)
        hdr.addStretch(1)
        grp_ch_lay.addLayout(hdr)

        self._ch_scroll = QScrollArea()
        self._ch_scroll.setWidgetResizable(True)
        self._ch_scroll.setMinimumHeight(70)
        self._ch_scroll.setMaximumHeight(230)
        self._ch_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._ch_container = QWidget()
        self._ch_vlay = QVBoxLayout(self._ch_container)
        self._ch_vlay.setContentsMargins(0, 0, 0, 0)
        self._ch_vlay.setSpacing(2)
        self._ch_vlay.addStretch(1)
        self._ch_scroll.setWidget(self._ch_container)
        grp_ch_lay.addWidget(self._ch_scroll)
        main.addWidget(grp_ch)

        # ── 공통 설정 ─────────────────────────────────────────────────────────
        grp_common = QGroupBox("Common settings")
        gl = QGridLayout(grp_common)
        gl.setSpacing(4)
        gl.setColumnStretch(1, 1)

        gl.addWidget(QLabel("Result folder:"), 0, 0, Qt.AlignmentFlag.AlignRight)
        self._le_out_dir = QLineEdit(".")
        btn_out = QPushButton("📂"); btn_out.setFixedWidth(28)
        btn_out.clicked.connect(lambda: self._pick_dir(self._le_out_dir))
        _od = QHBoxLayout(); _od.addWidget(self._le_out_dir, stretch=1); _od.addWidget(btn_out)
        _od_w = QWidget(); _od_w.setLayout(_od)
        gl.addWidget(_od_w, 0, 1)

        gl.addWidget(QLabel("Date range (optional):"), 1, 0, Qt.AlignmentFlag.AlignRight)
        self._le_date_start = QLineEdit()
        self._le_date_start.setPlaceholderText("YYYYMMDD start (e.g. 20260531)")
        self._le_date_end = QLineEdit()
        self._le_date_end.setPlaceholderText("YYYYMMDD end (e.g. 20260601)")
        _dr = QHBoxLayout()
        _dr.addWidget(self._le_date_start); _dr.addWidget(QLabel("~")); _dr.addWidget(self._le_date_end)
        _drw = QWidget(); _drw.setLayout(_dr)
        gl.addWidget(_drw, 1, 1)

        gl.addWidget(QLabel("Cavity:"), 2, 0, Qt.AlignmentFlag.AlignRight)
        from PyQt6.QtWidgets import QDoubleSpinBox as _DSB
        _cav = QHBoxLayout()
        _cav.addWidget(QLabel("Length (cm):"))
        self._spin_cavity_len = _DSB()
        self._spin_cavity_len.setRange(1.0, 10000.0); self._spin_cavity_len.setDecimals(2)
        self._spin_cavity_len.setValue(51.8); self._spin_cavity_len.setFixedWidth(90)
        _cav.addWidget(self._spin_cavity_len); _cav.addSpacing(16)
        _cav.addWidget(QLabel("RL Factor:"))
        self._spin_rl = _DSB()
        self._spin_rl.setRange(0.001, 1.0); self._spin_rl.setDecimals(4)
        self._spin_rl.setSingleStep(0.001); self._spin_rl.setValue(1.0); self._spin_rl.setFixedWidth(80)
        _cav.addWidget(self._spin_rl); _cav.addStretch()
        _cav_w = QWidget(); _cav_w.setLayout(_cav)
        gl.addWidget(_cav_w, 2, 1)
        main.addWidget(grp_common)

        # ── 실행 버튼들 ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_run = QPushButton("▶  Start")
        btn_run.setStyleSheet(
            "background-color:#4CAF50;color:white;font-weight:bold;height:36px;")
        btn_run.clicked.connect(self._run)
        self._btn_run = btn_run
        btn_row.addWidget(btn_run)

        # Start 시 scan 결과를 그대로 α R(t) npz에 증분 머지(재스캔 0). 기본 ON이라
        # 사용자가 npz를 따로 관리할 필요 없음 — 기존 npz엔 머지(덮어쓰기 아님),
        # 없으면 생성. 단순히 트렌드만 볼 땐 끄면 npz를 안 건드린다.
        self._chk_auto_npz = QCheckBox("Auto-update α R(t) npz")
        self._chk_auto_npz.setChecked(True)
        self._chk_auto_npz.setToolTip(
            "Start 계산 결과를 R_<channel>.npz에 자동 증분 머지합니다(재스캔 없음).\n"
            "기존 npz가 있으면 새 knot만 시간순 머지+중복제거(덮어쓰지 않음),\n"
            "없으면 새로 만듭니다. 끄면 Start가 npz를 건드리지 않습니다.")
        btn_row.addWidget(self._chk_auto_npz)

        # 이미 npz에 계산돼 있는 파일은 다시 스캔하지 않음(속도). 트렌드 플롯은
        # 기존 트렌드 dat을 불러와 합쳐서 전체를 보여준다.
        self._chk_skip_done = QCheckBox("Skip already-computed")
        self._chk_skip_done.setChecked(True)
        self._chk_skip_done.setToolTip(
            "npz의 processed_files에 이미 있는 파일은 다시 계산하지 않습니다(재실행·연장이 빨라짐).\n"
            "전체 트렌드는 기존 {channel}_R_trend.dat을 불러와 새 결과와 합쳐 표시합니다.\n"
            "끄면 선택 범위 전체를 매번 다시 계산합니다.")
        btn_row.addWidget(self._chk_skip_done)

        # 평소엔 Start(auto-update 체크) 하나로 npz가 증분 관리된다. Rebuild는
        # 설정 변경/손상 시 npz를 처음부터 다시 만드는 비상용 탈출구(덮어쓰기).
        btn_rt = QPushButton("🔁  Rebuild npz (full)")
        btn_rt.setStyleSheet(
            "background-color:#1976D2;color:white;font-weight:bold;height:36px;")
        btn_rt.setToolTip(
            "Recompute every file from scratch and OVERWRITE R_<channel>.npz.\n"
            "Use only when settings changed (cavity/RL/R-window) or the npz is damaged.\n"
            "Normal incremental updates are handled by Start's 'Auto-update' checkbox.")
        btn_rt.clicked.connect(self._export_rt_for_alpha)
        self._btn_rt_export = btn_rt
        btn_row.addWidget(btn_rt)

        btn_verify = QPushButton("🔍  Verify npz")
        btn_verify.setStyleSheet(
            "background-color:#00796B;color:white;font-weight:bold;height:36px;")
        btn_verify.setToolTip(
            "Read-only check of each channel's R_<channel>.npz (no scanning):\n"
            "• missing days (calendar days with no knot → R interpolated)\n"
            "• uncomputed files (in the raw folder but not yet in the npz)")
        btn_verify.clicked.connect(self._verify_npz)
        self._btn_rt_verify = btn_verify
        btn_row.addWidget(btn_verify)

        # 계단 가드 수동 분절 — 운영자가 아는 이벤트(거울 청소/재정렬 시각)를
        # npz에 기록하면 α 생성 시 그 시각에서 R(t) PCHIP 보간이 강제 분절된다.
        btn_breaks = QPushButton("⛓  R(t) Breaks…")
        btn_breaks.setStyleSheet(
            "background-color:#5D4037;color:white;font-weight:bold;height:36px;")
        btn_breaks.setToolTip(
            "Manual step-change breaks for R(t) interpolation (step guard).\n"
            "Enter known events (mirror cleaning / realignment) as datetimes;\n"
            "alpha generation will NOT interpolate across these times.\n"
            "Knots are never deleted — only the interpolation is segmented.")
        btn_breaks.clicked.connect(self._edit_manual_breaks)
        self._btn_rt_breaks = btn_breaks
        btn_row.addWidget(btn_breaks)
        main.addLayout(btn_row)

        # ── 진행 표시줄 ────────────────────────────────────────────────────────
        prog_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setRange(0, 0); self._progress.setFixedHeight(16)
        self._progress.setVisible(False)
        self._lbl_elapsed = QLabel("")
        self._lbl_elapsed.setStyleSheet("color:#555;font-size:11px;min-width:80px;")
        prog_row.addWidget(self._progress, stretch=1); prog_row.addWidget(self._lbl_elapsed)
        main.addLayout(prog_row)

        # ── 스플리터: 로그/테이블 · 시계열/스펙트럼 ──────────────────────────
        main_splitter = QSplitter(Qt.Orientation.Vertical)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._log = QTextEdit()
        self._log.setReadOnly(True); self._log.setFontFamily("Consolas"); self._log.setFontPointSize(9)
        top_splitter.addWidget(self._log)

        self.tableWidget = QTableWidget(0, 4)
        self.tableWidget.setHorizontalHeaderLabels(["Time", "File", "Channel", "R_mean (%)"])
        self.tableWidget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tableWidget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tableWidget.itemSelectionChanged.connect(self._on_table_row_selected)
        top_splitter.addWidget(self.tableWidget)
        top_splitter.setSizes([400, 600])

        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        _date_axis = pg.DateAxisItem(orientation='bottom')
        self._pw = pg.PlotWidget(axisItems={'bottom': _date_axis}, title="R time-series")
        self._pw.setBackground('w'); self._pw.showGrid(x=True, y=True, alpha=0.3)
        self._pw.setLabel('left', 'R mean (%)'); self._pw.setLabel('bottom', 'Time')
        bottom_splitter.addWidget(self._pw)

        self._spectrum_pw = pg.PlotWidget(title="R(λ) per wavelength")
        self._spectrum_pw.setBackground('w'); self._spectrum_pw.showGrid(x=True, y=True, alpha=0.3)
        self._spectrum_pw.setLabel('left', 'Reflectance R')
        self._spectrum_pw.setLabel('bottom', 'Wavelength (nm)')
        self._spectrum_pw.addLegend()
        bottom_splitter.addWidget(self._spectrum_pw)
        bottom_splitter.setSizes([600, 400])

        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(bottom_splitter)
        main_splitter.setSizes([280, 500])
        main.addWidget(main_splitter, stretch=1)

    # ── 채널 행 관리 ──────────────────────────────────────────────────────────
    def _make_ch_row_widget(self, ch_num, label="", raw_dir="", raw_ch=1,
                             wv_ok=False, r_start=435.0, r_end=480.0, tz_str="UTC"):
        """채널 한 행 QFrame 위젯 생성."""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet(
            "QFrame{background:#FAFAFA;border:1px solid #CCC;border-radius:3px;}")
        row = QHBoxLayout(frame)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(5)

        lbl_num = QLabel(f"CH{ch_num}")
        lbl_num.setStyleSheet("font-weight:bold;color:#1565C0;")
        lbl_num.setFixedWidth(34)
        row.addWidget(lbl_num)

        le_label = QLineEdit(label)
        le_label.setPlaceholderText("label")
        le_label.setFixedWidth(80)
        row.addWidget(le_label)

        le_raw_dir = QLineEdit(raw_dir)
        le_raw_dir.setPlaceholderText("Raw data folder")
        row.addWidget(le_raw_dir, stretch=1)

        btn_dir = QPushButton("📂")
        btn_dir.setFixedWidth(28)
        btn_dir.clicked.connect(
            lambda _ch=ch_num, _le=le_raw_dir: self._pick_raw_dir(_le, _ch))
        row.addWidget(btn_dir)

        cb_raw_ch = QComboBox()
        cb_raw_ch.addItems(["ch 1", "ch 2", "ch 3"])
        cb_raw_ch.setCurrentIndex(raw_ch - 1)
        cb_raw_ch.setFixedWidth(62)
        cb_raw_ch.setToolTip(
            "Which ROI to read in the raw file (dio_channel)\n"
            "ch1: spec 0–2048 (Cold / Hot PNs)\n"
            "ch2: spec 2048–4096 (Hot ANs)\n"
            "Hot 2-channel: same raw_dir, set ch1·ch2 separately")
        row.addWidget(cb_raw_ch)

        lbl_wv = QLabel("✅ wavecal" if wv_ok else "❌ no wavecal")
        lbl_wv.setStyleSheet(
            "color:#2E7D32;font-weight:bold;" if wv_ok else "color:#C62828;")
        lbl_wv.setFixedWidth(104)
        lbl_wv.setToolTip("Wavecal status loaded from the left panel")
        row.addWidget(lbl_wv)

        # R창: 편집 가능 스핀박스 (기본값 = 핏범위에서 자동 채움)
        row.addWidget(QLabel("R-window:"))
        sp_r_start = QDoubleSpinBox()
        sp_r_start.setRange(300.0, 1000.0); sp_r_start.setDecimals(1)
        sp_r_start.setValue(r_start); sp_r_start.setFixedWidth(58)
        sp_r_start.setToolTip("R calc wavelength window start (nm)")
        row.addWidget(sp_r_start)
        row.addWidget(QLabel("–"))
        sp_r_end = QDoubleSpinBox()
        sp_r_end.setRange(300.0, 1000.0); sp_r_end.setDecimals(1)
        sp_r_end.setValue(r_end); sp_r_end.setFixedWidth(58)
        sp_r_end.setToolTip("R calc wavelength window end (nm)")
        row.addWidget(sp_r_end)

        lbl_tz = QLabel(tz_str)
        lbl_tz.setStyleSheet("color:#555;font-size:11px;")
        lbl_tz.setFixedWidth(36)
        lbl_tz.setToolTip("TZ — set in left panel")
        row.addWidget(lbl_tz)

        btn_del = QPushButton("✕")
        btn_del.setFixedWidth(22)
        btn_del.setStyleSheet("color:#AAA;")
        btn_del.setToolTip("Delete this channel row")
        btn_del.clicked.connect(lambda _f=frame: self._del_ch_row(_f))
        row.addWidget(btn_del)

        frame.le_label    = le_label
        frame.le_raw_dir  = le_raw_dir
        frame.cb_raw_ch   = cb_raw_ch
        frame.lbl_wv      = lbl_wv
        frame.sp_r_start  = sp_r_start
        frame.sp_r_end    = sp_r_end
        frame.lbl_tz      = lbl_tz
        frame._ch_num     = ch_num
        frame._panel_data = {}   # filled by _load_from_left_panel
        return frame

    def _pick_raw_dir(self, line_edit, ch_num):
        d = QFileDialog.getExistingDirectory(self, "Select Raw folder", dlg_dir("r_raw_dir"))
        if d:
            dlg_dir("r_raw_dir", d)
            line_edit.setText(d)
            QSettings("CAESAR", "app").setValue(f"r_calib/ch{ch_num}/raw_dir", d)

    def _add_ch_row(self, frame):
        idx = self._ch_vlay.count() - 1  # insert before trailing stretch
        self._ch_vlay.insertWidget(idx, frame)
        self._ch_rows.append(frame)

    def _del_ch_row(self, frame):
        if frame in self._ch_rows:
            self._ch_rows.remove(frame)
        self._ch_vlay.removeWidget(frame)
        frame.setParent(None)
        frame.deleteLater()

    def _clear_ch_rows(self):
        for frame in list(self._ch_rows):
            self._ch_vlay.removeWidget(frame)
            frame.setParent(None)
            frame.deleteLater()
        self._ch_rows.clear()

    def _load_from_left_panel(self):
        """왼쪽 패널 채널 설정 → 채널 행 동기화."""
        parent = self.parent()
        if parent is None or not hasattr(parent, '_channel_configs'):
            self._log.append("[load channels] no channels in left panel (add a channel).")
            return
        try:
            if hasattr(parent, '_capture_config') and hasattr(parent, '_active_channel'):
                parent._channel_configs[parent._active_channel] = parent._capture_config()
        except Exception:
            pass
        chcfgs = {k: v for k, v in (parent._channel_configs or {}).items() if v}
        if not chcfgs:
            self._log.append("[load channels] no channels configured in the left panel.")
            return

        self._clear_ch_rows()
        qs = QSettings("CAESAR", "app")

        for ch in sorted(chcfgs):
            cfg     = chcfgs[ch]
            wl_path = cfg.get('wl_path', '')
            wave_ok = bool(wl_path) and os.path.isfile(wl_path)
            label   = (cfg.get('data_label') or f'CH{ch}').strip() or f'CH{ch}'

            # R창 기본값: QSettings 저장값 우선, 없으면 핏범위
            fit_s = float(cfg.get('fit_start_nm') or 435.0)
            fit_e = float(cfg.get('fit_end_nm') or 480.0)
            r_start = float(qs.value(f"r_calib/ch{ch}/r_start", fit_s))
            r_end   = float(qs.value(f"r_calib/ch{ch}/r_end",   fit_e))

            # 좌패널 'Time shift'(출력 시각에 더할 시프트) → R-calc는 '데이터의 UTC
            # 오프셋'이 필요(부호 반대). 레거시 'input_tz' 문자열(KST(+9))도 호환.
            _tsv = cfg.get('time_shift_h', cfg.get('input_tz', 0.0))
            if isinstance(_tsv, (int, float)):
                _shift = float(_tsv)
            elif str(_tsv).strip().upper().startswith('KST'):
                _shift = -9.0
            else:
                _shift = 0.0
            tz_h   = -_shift                       # 데이터 UTC 오프셋 = −(출력 시프트)
            tz_str = f"UTC{tz_h:+g}" if tz_h else "UTC"

            raw_dir = qs.value(f"r_calib/ch{ch}/raw_dir", "")
            raw_ch  = int(qs.value(f"r_calib/ch{ch}/raw_ch", 1))

            frame = self._make_ch_row_widget(
                ch, label, raw_dir, raw_ch, wave_ok, r_start, r_end, tz_str)

            frame._panel_data['ts_tz_hours'] = tz_h
            frame._panel_data['wl_path']        = wl_path

            if wave_ok:
                try:
                    wv = np.loadtxt(wl_path)
                    frame._panel_data['wave_nm'] = (
                        wv.ravel() if wv.ndim == 1 else wv[:, 0])
                except Exception as e:
                    frame._panel_data['wave_nm'] = None
                    self._log.append(f"  [CH{ch}] wavecal load failed: {e}")
            else:
                frame._panel_data['wave_nm'] = None

            self._add_ch_row(frame)

        self._log.append(f"[load channels] {len(chcfgs)} channels synced")

    def _collect_channel_cfgs(self, RTP):
        """채널 행 → (label, raw_dir, wave_nm, RTConfig, file_list, out_path) 목록."""
        import os as _os
        try:
            import sys as _s
            _td = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
            if _td not in _s.path:
                _s.path.insert(0, _td)
            from r_batch_calculator import (
                SPEC_START_DEFAULT, SPEC_END_DEFAULT, SPEC_START_ANS, SPEC_END_ANS,
                COL_PRESS_COLD, COL_TEMP_COLD, COL_PRESS_HOT_ANS, COL_TEMP_HOT)
        except ImportError:
            SPEC_START_DEFAULT = 2053; SPEC_END_DEFAULT = 4101
            SPEC_START_ANS = 4101;     SPEC_END_ANS = 6149
            COL_PRESS_COLD = 6160;     COL_TEMP_COLD = 6173
            COL_PRESS_HOT_ANS = 6164;  COL_TEMP_HOT = 6155

        out_dir = self._le_out_dir.text().strip() or "."
        ds = self._le_date_start.text().strip()
        de = self._le_date_end.text().strip()

        def _flist(d):
            if not d:
                return None
            if ds or de:
                lo = self._norm_date(ds, "0000-00-00")
                hi = self._norm_date(de, "9999-99-99")
                # 범위 내 0개면 [] 그대로 반환한다. 예전엔 `or None`이라 빈 결과가
                # None→"디렉토리 전체 스캔"으로 둔갑해(콜드처럼 해당 기간 데이터가
                # 없는 채널이 폴더를 통째로 긁었다). []는 scan_directory가 즉시 빠져나옴.
                return self._files_in_range(d, lo, hi)
            return None

        tasks = []
        for frame in self._ch_rows:
            label   = frame.le_label.text().strip() or f"ch{frame._ch_num}"
            raw_dir = frame.le_raw_dir.text().strip()
            if not raw_dir:
                self._log.append(f"  [{label}] no raw_dir → skipped")
                continue
            wave_nm = frame._panel_data.get('wave_nm')
            if wave_nm is None:
                self._log.append(
                    f"  [{label}] no wavecal → skipped (load from left panel and retry)")
                continue

            dio_ch  = frame.cb_raw_ch.currentIndex() + 1  # 1-based
            fit_win = (frame.sp_r_start.value(), frame.sp_r_end.value())
            tz_h    = frame._panel_data.get('ts_tz_hours', 0)

            if dio_ch >= 2:  # ch2, ch3 → ANs 영역
                spec_s, spec_e = SPEC_START_ANS,     SPEC_END_ANS
                col_p,  col_t  = COL_PRESS_HOT_ANS,  COL_TEMP_HOT
            else:            # ch1 default
                spec_s, spec_e = SPEC_START_DEFAULT,  SPEC_END_DEFAULT
                col_p,  col_t  = COL_PRESS_COLD,      COL_TEMP_COLD

            rtcfg = RTP.RTConfig(
                fit_window_nm=fit_win, col_press=col_p, col_temp=col_t,
                spec_start=spec_s, spec_end=spec_e,
                ts_tz_hours=tz_h, label=label, dio_channel=dio_ch)

            flist = _flist(raw_dir)
            # 날짜범위가 설정됐는데 그 안에 파일이 0개면 채널을 명시적으로 스킵한다.
            # (예: 콜드가 멈춰 19~26 데이터가 없을 때 "여기서 끝" — 전체 스캔 안 함)
            if flist is not None and len(flist) == 0:
                self._log.append(
                    f"  [{label}] no files in date range "
                    f"{ds or '*'}~{de or '*'} → skipped")
                continue
            tasks.append((label, raw_dir, wave_nm, rtcfg,
                          flist, _os.path.join(out_dir, f"R_{label}.npz")))
        return tasks

    def _warn_flag_mismatch(self):
        """패널 primary ZA/He flag가 R-cal이 실제 쓰는 raw_parser.FLAG_ZA/HE(스칼라)와
        다르면 로그 경고. R-cal 파이프라인(scan_directory/reflectance_calc)은 모듈 전역
        flag를 쓰므로 패널 flag와 연동되지 않는다 — 불일치를 가시화만 한다(차단 X).
        R-cal은 pure-injecting(500/510)만 쓰는 게 옳고, Alpha Generator의 I0/He 선택과
        일치해야 R(t)와 α의 기준이 어긋나지 않는다."""
        parent = self.parent()
        if parent is None or not hasattr(parent, 'txt_flag_za'):
            return
        try:
            from core.raw_parser import FLAG_ZA as _RZA, FLAG_HE as _RHE
        except Exception:
            return

        def _primary(txt, default):
            try:
                vals = parent._parse_flags(txt) if hasattr(parent, '_parse_flags') else None
                return int(vals[0]) if vals else default
            except Exception:
                return default
        p_za = _primary(parent.txt_flag_za.text(), _RZA)
        p_he = _primary(parent.txt_flag_he.text(), _RHE)
        diffs = []
        if p_za != _RZA:
            diffs.append(f"ZA primary={p_za}(panel)≠{_RZA}(R-cal)")
        if p_he != _RHE:
            diffs.append(f"He primary={p_he}(panel)≠{_RHE}(R-cal)")
        if diffs:
            self._log.append(
                f"⚠️ [flag mismatch] R-cal uses raw_parser pure-injecting flags "
                f"({_RZA}/{_RHE}), NOT the left-panel flags: " + "; ".join(diffs) +
                f". R(t)/R-cal proceeds with {_RZA}/{_RHE}; set panel ZA/He back to "
                f"{_RZA}/{_RHE} to keep R consistent with Alpha Generator's I0/He selection.")

    # ── 계산 시작 ─────────────────────────────────────────────────────────────
    def _run(self):
        """채널별 scan_directory → 시계열 + 스펙트럼 플롯."""
        if not self._ch_rows:
            QMessageBox.warning(self, "No channels",
                "Load channels first.\nClick the '🔄 Load channels from left panel' button.")
            return
        self._warn_flag_mismatch()

        RTP = self._rt_import()
        if RTP is None:
            return

        qs = QSettings("CAESAR", "app")
        for frame in self._ch_rows:
            ch = frame._ch_num
            qs.setValue(f"r_calib/ch{ch}/raw_dir", frame.le_raw_dir.text().strip())
            qs.setValue(f"r_calib/ch{ch}/raw_ch",  frame.cb_raw_ch.currentIndex() + 1)
            qs.setValue(f"r_calib/ch{ch}/r_start", frame.sp_r_start.value())
            qs.setValue(f"r_calib/ch{ch}/r_end",   frame.sp_r_end.value())

        tasks = self._collect_channel_cfgs(RTP)
        if not tasks:
            QMessageBox.warning(self, "Config error",
                "No runnable channels:\n"
                "• Set each channel's Raw Dir\n"
                "• Wavecal must be loaded from the left panel")
            return

        out_dir = self._le_out_dir.text().strip() or "."
        channel_cfgs = [
            {"label":     label, "raw_dir": raw_dir, "wave_nm": wave,
             "rtcfg":     cfg,   "file_list": flist, "npz_path": npz_path,
             "color":     _CH_COLORS[i % len(_CH_COLORS)]}
            for i, (label, raw_dir, wave, cfg, flist, npz_path) in enumerate(tasks)
        ]

        self._log.clear(); self._pw.clear(); self._spectrum_pw.clear()
        self.tableWidget.setRowCount(0); self._all_results.clear()
        self._btn_run.setEnabled(False)
        self._progress.setVisible(True)
        self._t_start = time.time(); self._timer.start(1000)
        self._lbl_elapsed.setText("Elapsed: 00:00")

        self._worker = _ChannelRWorker(
            channel_cfgs, out_dir,
            self._spin_cavity_len.value(), self._spin_rl.value(),
            auto_npz=self._chk_auto_npz.isChecked(),
            skip_done=self._chk_skip_done.isChecked())
        self._worker.log.connect(self._log.append)
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    # ── R(t) 공통 태스크 빌더 ──────────────────────────────────────────────
    def _build_rt_tasks(self, RTP):
        """채널 행에서 태스크 목록 반환 (_collect_channel_cfgs로 위임)."""
        return self._collect_channel_cfgs(RTP)

    def _rt_import(self):
        """rt_precompute 임포트 + 경로 보장. 실패 시 None 반환."""
        import sys as _sys, os as _os
        _td = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
        if _td not in _sys.path:
            _sys.path.insert(0, _td)
        try:
            import rt_precompute as RTP
            return RTP
        except Exception as e:
            QMessageBox.critical(self, "Error", f"rt_precompute import failed:\n{e}")
            return None

    def _lock_rt_buttons(self, locked):
        self._btn_rt_export.setEnabled(not locked)
        self._btn_rt_verify.setEnabled(not locked)
        self._btn_rt_breaks.setEnabled(not locked)

    # ── 계단 가드: 수동 분절 편집 ───────────────────────────────────────────
    def _edit_manual_breaks(self):
        """채널별 R_<ch>.npz의 수동 분절 시각을 편집한다(step guard).
        knot/omr_d는 건드리지 않고 manual_breaks_sec 메타만 교체 저장.
        α 생성 시 이 시각에서 R(t) PCHIP 보간이 강제 분절된다."""
        import os as _os
        from PyQt6.QtWidgets import QInputDialog
        RTP = self._rt_import()
        if RTP is None:
            return
        tasks = self._build_rt_tasks(RTP)
        if not tasks:
            QMessageBox.warning(self, "Input error",
                                "Set a left-panel channel (incl. wavecal) + raw folder.")
            return
        for label, _raw_dir, _wave, _rtcfg, _flist, npz_path in tasks:
            if not _os.path.exists(npz_path):
                self._log.append(f"[breaks] [{label}] no npz yet — skipped")
                continue
            try:
                year = RTP.npz_year(npz_path)
                z = RTP.load_rt(npz_path)
            except Exception as e:
                self._log.append(f"[breaks] [{label}] npz load failed: {e}")
                continue
            if year is None:
                self._log.append(f"[breaks] [{label}] year unknown (no processed file "
                                 f"names) — cannot edit breaks by datetime")
                continue
            from datetime import datetime as _dtm, timedelta as _tdl
            base = _dtm(year, 1, 1)
            cur = "\n".join(
                (base + _tdl(seconds=float(s))).strftime("%Y-%m-%d %H:%M")
                for s in sorted(z.get("manual_breaks_sec", [])))
            text, ok = QInputDialog.getMultiLineText(
                self, f"R(t) manual breaks — {label}",
                f"[{label}] one datetime per line (YYYY-MM-DD HH:MM).\n"
                "Interpolation will not cross these times. Empty = no manual breaks.",
                cur)
            if not ok:
                continue
            try:
                secs = RTP.parse_break_datetimes(text.splitlines(), year)
                saved = RTP.set_manual_breaks(npz_path, secs)
            except Exception as e:
                QMessageBox.warning(self, "Breaks error", f"[{label}] {e}")
                continue
            self._log.append(
                f"[breaks] [{label}] {len(saved)} manual break(s) saved → "
                f"{_os.path.basename(npz_path)}")
            try:
                for _ln in RTP.step_report(npz_path)["lines"]:
                    self._log.append(f"[{label}] {_ln}")
            except Exception:
                pass

    # ── 전체 재계산(Rebuild) ────────────────────────────────────────────────
    def _export_rt_for_alpha(self):
        """현재 설정으로 채널별 R(t)를 처음부터 재계산해 R_<채널>.npz를 **덮어쓴다**.
        평소 증분은 Start의 Auto-update가 담당 — 이건 설정변경/손상 시 비상용."""
        RTP = self._rt_import()
        if RTP is None:
            return

        out_dir = self._le_out_dir.text().strip() or "."
        tasks = self._build_rt_tasks(RTP)
        if not tasks:
            QMessageBox.warning(self, "Input error",
                                "Set a left-panel channel (incl. wavecal) + raw folder (Cold or Hot), or\n"
                                "set Cold/Hot folder + wavecal file.")
            return

        # 덮어쓰기 경고 — 기존 누적 npz가 있으면 명시적으로 확인받는다.
        import os as _os
        existing = [t[5] for t in tasks if _os.path.exists(t[5])]
        if existing:
            names = "\n".join(f"  • {_os.path.basename(p)}" for p in existing)
            ans = QMessageBox.warning(
                self, "Rebuild npz — overwrite?",
                "다음 npz를 처음부터 다시 계산해 **덮어씁니다**(증분 아님):\n"
                f"{names}\n\n"
                "평소 추가는 Start의 'Auto-update α R(t) npz'로 충분합니다.\n"
                "설정(cavity/RL/R-window)을 바꿨거나 npz가 손상된 경우에만 사용하세요.\n\n"
                "계속할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if ans != QMessageBox.StandardButton.Yes:
                return

        self._warn_flag_mismatch()
        self._log.append(f"[R(t) export] {len(tasks)} channels parallel compute start → {out_dir}")
        self._lock_rt_buttons(True)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("R(t) compute prep…")
        self._rt_export_worker = _RTExportWorker(tasks)
        self._rt_export_worker.log.connect(self._log.append)

        def _on_prog(done, total, label):
            self._progress.setRange(0, max(total, 1))
            self._progress.setValue(done)
            self._progress.setFormat(f"R(t) [{label}] {done}/{total} files parsed  %p%")
        self._rt_export_worker.progress.connect(_on_prog)

        def _done(summary):
            self._log.append(f"[R(t) export done] {summary}")
            self._progress.setVisible(False)
            self._progress.setFormat("")
            self._lock_rt_buttons(False)
            QMessageBox.information(
                self, "R(t) saved",
                f"{summary}\n\nLocation: {out_dir}\nFile: R_<channel>.npz\n\n"
                "Assign this file as 'R(t) file' in Alpha Generator to\n"
                "apply channel-window-based R during alpha generation.")

        self._rt_export_worker.finished.connect(_done)
        self._rt_export_worker.start()

    # ── npz 검증 (읽기 전용) ─────────────────────────────────────────────────
    def _verify_npz(self):
        """채널별 R_<채널>.npz를 읽어 '빈 날(knot 0)'과 '미계산 파일(raw엔 있으나
        npz엔 없음)'을 보고한다. 스캔하지 않으므로 즉시 끝난다(읽기 전용)."""
        import os as _os
        RTP = self._rt_import()
        if RTP is None:
            return

        tasks = self._build_rt_tasks(RTP)
        if not tasks:
            QMessageBox.warning(self, "Input error",
                                "Set a left-panel channel (incl. wavecal) + raw folder.")
            return

        summary_lines = []   # 다이얼로그 본문(요약)
        detail_lines  = []   # 펼침(상세: 미계산 파일 목록)
        any_issue = False

        for label, raw_dir, wave, rtcfg, flist, npz_path in tasks:
            try:
                rep = RTP.verify_npz(npz_path, raw_dir, file_list=flist)
            except Exception as e:
                summary_lines.append(f"[{label}]  ❌ verify failed: {e}")
                continue

            if not rep["exists"]:
                summary_lines.append(
                    f"[{label}]  ⚠️ no npz yet ({_os.path.basename(npz_path)}) — "
                    f"{rep['n_raw']} raw files uncomputed")
                any_issue = True
                continue

            gaps = rep["gaps"]
            unc  = rep["uncomputed"]
            status = "✅ clean" if (not gaps and not unc) else "⚠️ issues"
            if gaps or unc:
                any_issue = True
            summary_lines.append(
                f"[{label}]  {status}  knots={rep['n_knots']}, raw={rep['n_raw']}, "
                f"computed={rep['n_processed']}")
            # 날짜/시각 커버리지 — npz에 실제로 들어있는 데이터 구간(항상 표시)
            if rep.get("first_dt"):
                cov = (f"      • coverage: {rep['first_dt']} ~ {rep['last_dt']}"
                       f"  ({rep['n_days']} days)")
                if rep["n_days"] and gaps:
                    cov += f", {gaps['n_days']} empty"
                summary_lines.append(cov)
            elif rep["first"]:
                summary_lines.append(
                    f"      • coverage: {rep['first']} ~ {rep['last']}")

            if gaps:
                shown = ", ".join(gaps["missing"][:12]) + (
                    f" … (+{gaps['n_days'] - 12})" if gaps["n_days"] > 12 else "")
                summary_lines.append(f"      • missing days ({gaps['n_days']}): {shown}")
            if unc:
                summary_lines.append(f"      • uncomputed files: {len(unc)}")
                detail_lines.append(f"[{label}] uncomputed files ({len(unc)}):")
                detail_lines += [f"    {b}" for b in unc[:200]]
                if len(unc) > 200:
                    detail_lines.append(f"    … (+{len(unc) - 200} more)")

            # 계단 가드 — 후보/수동 분절 보고(읽기 전용; knot은 그대로)
            try:
                srep = RTP.step_report(npz_path)
                for ln in srep["lines"]:
                    summary_lines.append(f"      • {ln}")
            except Exception as e:
                summary_lines.append(f"      • step-guard report failed: {e}")

        msg = QMessageBox(self)
        msg.setWindowTitle("Verify npz")
        msg.setIcon(QMessageBox.Icon.Warning if any_issue else QMessageBox.Icon.Information)
        msg.setText(
            ("아래 항목을 확인하세요. 빈 날·미계산 파일은 그 구간 R이 보간으로만 "
             "채워짐을 뜻합니다.\n해당 날짜/파일을 Start로 계산하면 자동 삽입됩니다.\n\n"
             if any_issue else "모든 채널 npz가 깨끗합니다 (빈 날·미계산 파일 없음).\n\n")
            + "\n".join(summary_lines))
        if detail_lines:
            msg.setDetailedText("\n".join(detail_lines))
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
        self._log.append("[verify] " + " | ".join(summary_lines))

    def _on_data_ready(self, arg0, arg1, arg2, out_dir):
        """arg0 = new [{label,results,color},...] 또는 legacy cold_results list."""
        self._pw.clear()
        self._pw.addLegend(offset=(10, 10))
        self._all_results.clear()
        self.tableWidget.setRowCount(0)

        # Format detection
        if (isinstance(arg0, list) and arg0 and
                isinstance(arg0[0], dict) and 'results' in arg0[0]):
            channels = arg0   # new channel-driven format
        else:
            # Legacy format: map fixed 3 channels
            channels = []
            for res, color, name in [
                (arg0, '#2196F3', 'Cold'),
                (arg1, '#FF6F00', 'Hot PNs'),
                (arg2, '#D32F2F', 'Hot ANs'),
            ]:
                if res:
                    channels.append({"label": name, "results": res, "color": color})

        def _plot_fill(results, color_hex, name):
            if not results:
                return
            times = np.array([r["timestamp"].replace(tzinfo=None).timestamp()
                              for r in results], dtype=float)
            r_pct = np.array([r["r_mean"] * 100.0 for r in results], dtype=float)
            r_std = np.array([r["r_std"]  * 100.0 for r in results], dtype=float)
            pen  = pg.mkPen(color=color_hex, width=2)
            brsh = pg.mkBrush(color_hex)
            self._pw.plot(times, r_pct, pen=pen, symbol='o', symbolSize=7,
                         symbolBrush=brsh, name=name)
            err = pg.ErrorBarItem(
                x=times, y=r_pct, top=r_std, bottom=r_std, beam=0,
                pen=pg.mkPen(color_hex, width=1, style=Qt.PenStyle.DotLine))
            self._pw.addItem(err)
            for r in results:
                ri = self.tableWidget.rowCount()
                self.tableWidget.insertRow(ri)
                self.tableWidget.setItem(ri, 0, QTableWidgetItem(
                    r["timestamp"].strftime('%Y-%m-%d %H:%M')))
                self.tableWidget.setItem(ri, 1, QTableWidgetItem(r["filename"]))
                self.tableWidget.setItem(ri, 2, QTableWidgetItem(name))
                self.tableWidget.setItem(ri, 3, QTableWidgetItem(
                    f"{r['r_mean'] * 100:.4f}"))
                file_date  = "-".join(r["filename"].split("-")[:3])
                base_fname = os.path.splitext(r["filename"])[0]
                # 새 형식: R_{name}; 레거시 호환 매핑
                _legacy = {"cold": "R_Cold", "hot_pns": "R_Hot_PNs",
                           "hot_ans": "R_Hot_ANs"}
                ch_subdir = _legacy.get(name.lower().replace(" ", "_"), f"R_{name}")
                dat_path  = os.path.join(
                    out_dir, ch_subdir, file_date, f"{base_fname}_R.dat")
                if not os.path.exists(dat_path):
                    dat_path = os.path.join(out_dir, file_date, f"{base_fname}_R.dat")
                self._all_results.append({
                    "channel": name, "color": color_hex,
                    "dat_path": dat_path, "roi": r.get("fit_window_nm", (400, 500))})

        for ch in channels:
            _plot_fill(ch["results"], ch["color"], ch["label"])

        # ── 중간 빈 날 알림 ───────────────────────────────────────────────────
        # auto_npz 머지 후 워커가 채널별 npz_gaps(달력상 knot 0개인 날)를 첨부한다.
        # 있으면 한 번에 모아 경고 팝업 — 그 구간 R은 보간으로만 채워짐을 알린다.
        gap_lines = []
        for ch in channels:
            g = ch.get("npz_gaps")
            if g:
                shown = ", ".join(g["missing"][:12]) + (
                    f" … (+{g['n_days'] - 12})" if g["n_days"] > 12 else "")
                gap_lines.append(
                    f"[{ch['label']}] {g['n_days']} day(s) missing "
                    f"({g['first']}~{g['last']}):\n    {shown}")
        if gap_lines:
            QMessageBox.warning(
                self, "Missing days in R(t)",
                "아래 날짜는 npz에 데이터(knot)가 없어 알파에서 R이 보간으로만 "
                "채워집니다.\n해당 날짜 데이터를 나중에 계산해 Start하면 자동으로 "
                "중간에 삽입됩니다.\n\n" + "\n\n".join(gap_lines))

        all_r = [r["r_mean"] * 100 for ch in channels for r in ch["results"]]
        if all_r:
            arr = np.array(all_r, dtype=float)
            med = float(np.median(arr)); sd = float(np.std(arr))
            margin = max(sd * 4.0, 0.0015)
            self._pw.setYRange(med - margin, min(med + margin, 100.0 + 5e-4), padding=0)

        # 부모 윈도우(app_window)의 슬롯으로 전달
        self.data_ready.emit(channels, [], [], out_dir)

    def _on_table_row_selected(self):
        """테이블 행 클릭 시 해당 파일의 _R.dat를 읽어 스펙트럼 플롯에 렌더링"""
        sel = self.tableWidget.selectedItems()
        if not sel: return
        
        row = sel[0].row()
        if row >= len(self._all_results): return
        
        info = self._all_results[row]
        dat_path = info["dat_path"]
        
        self._spectrum_pw.clear()
        
        if not os.path.exists(dat_path):
            self._spectrum_pw.setTitle(f"No data file: {os.path.basename(dat_path)}")
            return
            
        try:
            # 3번째 줄부터 데이터 시작 (skiprows=2)
            data = np.loadtxt(dat_path, skiprows=2)
            wave = data[:, 0]
            r_raw = data[:, 1]
            r_fit = data[:, 2]
            
            roi_min, roi_max = info["roi"]
            color = info["color"]

            self._spectrum_pw.setTitle(f"R(λ) - {os.path.basename(dat_path)}")
            
            # 원본 데이터 (흐릿한 점)
            self._spectrum_pw.plot(wave, r_raw, pen=None, symbol='o', symbolSize=3, symbolBrush=(150,150,150,150), name="Raw Data")
            # 피팅 데이터 (선명한 선)
            self._spectrum_pw.plot(wave, r_fit, pen=pg.mkPen(color, width=2.5), name="5th Poly Fit")
            
            # ROI 영역 표시
            lr = pg.LinearRegionItem([roi_min, roi_max], movable=False, brush=(0,255,0,20))
            self._spectrum_pw.addItem(lr)
            
        except Exception as e:
            self._spectrum_pw.setTitle(f"plot failed: {e}")

    def _tick_elapsed(self):
        if self._t_start is not None:
            m, s = divmod(int(time.time() - self._t_start), 60)
            self._lbl_elapsed.setText(f"Elapsed: {m:02d}:{s:02d}")

    def _on_done(self, out_dir: str):
        self._timer.stop(); self._progress.setVisible(False)
        m, s = divmod(int(time.time() - self._t_start) if self._t_start else 0, 60)
        self._lbl_elapsed.setText(f"done ({m:02d}:{s:02d})")
        self._t_start = None; self._btn_run.setEnabled(True)
        
        if out_dir:
            self._log.append(f"\n✅ done → result folder: {out_dir}")
        else:
            self._log.append("\n❌ error — check the log above.")

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.quit()
            if not self._worker.wait(3000):
                self._worker.terminate(); self._worker.wait()
        super().closeEvent(event)


# 이전 이름으로 import하는 코드와의 하위 호환
RTrendMonitorDialog = RCalibratorDialog