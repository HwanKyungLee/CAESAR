import os
import math
import datetime
import json
import numpy as np
import pandas as pd
import pyqtgraph as pg
pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')


# [PyQt6] Modules
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QFileDialog,
                             QTableWidget, QTableWidgetItem, QMessageBox,
                             QProgressBar, QGroupBox, QLineEdit, QScrollArea, QDialog,
                             QComboBox, QSplitter, QTabWidget, QDoubleSpinBox, QSpinBox,
                             QCheckBox, QFormLayout, QMenu, QRadioButton)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QColor, QShortcut, QKeySequence

from core.engine import UniversalEngine
from .worker import AnalysisWorker, AlphaExportWorker, AlphaFitWorker
from core.data_io import DataIO
from .ui_dialogs import *

class CAESARAnalyzer(QMainWindow):
    """
    Main Window Controller for CAESAR Pro v1.0.
    Integrates and commands all modules (Engine, Generators, Calibrations, Worker Threads, and Monitors).
    """
    def __init__(self):
        super().__init__()
        
        # Initialize Core System Modules
        self.engine = UniversalEngine()
        self.file_list = []
        self.results = []
        self.ref_widgets = []
        
        self.calib_squeeze = 1.0

        # Per-button "last used directory" memory (survives restarts).
        self._qsettings = QSettings("CAESAR", "app")

        self.init_ui()

    def _dlg_dir(self, key, save=None):
        """Last-directory memory for file dialogs, keyed per button (공용 모듈 위임)."""
        from gui.dlg_dir import dlg_dir
        return dlg_dir(key, save)

    def init_ui(self):
        from core.data_io import ui_scale
        s = ui_scale()
        self._s = s
        self.setWindowTitle('CAESAR Pro v1.0')
        self.resize(int(1400 * s), int(850 * s))

        # ILS state tracking
        self._ils_applied = False

        # Create horizontal splitter (Left: Control Panel / Right: Monitor Tabs)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # =========================================================
        # [Left] Main Control Panel
        # =========================================================
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # --- 1. Reference Management Section ---
        grp_ref = QGroupBox("1. Reference")
        grp_ref.setMinimumHeight(int(250 * self._s))
        lay_ref = QVBoxLayout()

        # Reference List Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(int(100 * self._s))
        self.ref_in = QWidget()
        self.ref_lay = QVBoxLayout()
        self.ref_in.setLayout(self.ref_lay)
        self.scroll.setWidget(self.ref_in)
        lay_ref.addWidget(self.scroll)
        
        # Load and Mask Buttons
        layout_load = QHBoxLayout()
        btn_batch = QPushButton("Batch")
        btn_batch.clicked.connect(self.batch_load_refs)
        btn_add = QPushButton("Add")
        btn_add.clicked.connect(self.add_ref_row)
        btn_mask = QPushButton("✂️ Mask")
        btn_mask.clicked.connect(self.open_mask_dialog)
        btn_mask.setStyleSheet("color: #cc0000; font-weight: bold;") 
        
        layout_load.addWidget(btn_batch)
        layout_load.addWidget(btn_add)
        layout_load.addWidget(btn_mask)
        lay_ref.addLayout(layout_load)
        
        # Lock References Button
        btn_lock = QPushButton("🔒 Lock References (Commit)")
        btn_lock.clicked.connect(self.lock_ref)
        btn_lock.setStyleSheet("font-weight: bold; padding: 5px;")
        lay_ref.addWidget(btn_lock)
        
        # ILS Convolution (advanced) — hidden by default.
        # Not needed when references are pre-convolved by the Reference Generator
        # (Stage 2). Only useful when loading raw high-resolution cross-sections.
        self._ils_visible = False
        self._btn_toggle_ils = QPushButton(
            "▶  ILS 콘볼루션 (고급 — Stage 2 레퍼런스 사용 시 불필요)")
        self._btn_toggle_ils.setStyleSheet(
            "text-align: left; color: #9e9e9e; "
            "border: 1px solid #E0E0E0; padding: 3px 8px; font-size: 11px;")
        self._btn_toggle_ils.setToolTip(
            "레퍼런스 제너레이터(Stage 2)로 이미 ILS를 적용한 레퍼런스를\n"
            "사용하는 경우 이 기능은 필요 없습니다 (이중 콘볼루션 위험).\n"
            "raw 고해상도 크로스섹션을 직접 로드할 때만 사용하세요.")
        lay_ref.addWidget(self._btn_toggle_ils)

        self._ils_container = QWidget()
        self._ils_container.setVisible(False)
        layout_conv = QHBoxLayout(self._ils_container)
        layout_conv.setContentsMargins(0, 0, 0, 0)
        layout_conv.addWidget(QLabel("ILS:"))

        self.spin_fwhm_nm = QDoubleSpinBox()
        self.spin_fwhm_nm.setRange(0.0, 20.0)
        self.spin_fwhm_nm.setDecimals(3)
        self.spin_fwhm_nm.setSuffix(" nm")
        self.spin_fwhm_nm.setToolTip(
            "Gaussian FWHM in nm (auto-filled from wavelength calibration)\n"
            "σ = FWHM / 2.3548  — used to convolve cross-sections to match ILS")
        self.spin_fwhm_nm.valueChanged.connect(self._update_fwhm_px_from_nm)
        layout_conv.addWidget(self.spin_fwhm_nm)

        layout_conv.addWidget(QLabel("="))
        self.spin_fwhm = QDoubleSpinBox()
        self.spin_fwhm.setRange(0, 50)
        self.spin_fwhm.setDecimals(2)
        self.spin_fwhm.setSuffix(" px")
        self.spin_fwhm.setToolTip(
            "Gaussian FWHM in pixels (auto-filled from nm spinbox)\n"
            "Can also be set directly; nm display will not update.")
        self.spin_fwhm.valueChanged.connect(self._on_ils_dirty)
        layout_conv.addWidget(self.spin_fwhm)

        layout_conv.addWidget(QLabel("L:"))
        self.spin_fwhm_lorentzian = QDoubleSpinBox()
        self.spin_fwhm_lorentzian.setRange(0, 20)
        self.spin_fwhm_lorentzian.setValue(0.0)
        self.spin_fwhm_lorentzian.setDecimals(2)
        self.spin_fwhm_lorentzian.setSuffix(" px")
        self.spin_fwhm_lorentzian.setToolTip(
            "Lorentzian FWHM — optical aberrations, grating scatter\n"
            "0.0 = pure Gaussian ILS")
        self.spin_fwhm_lorentzian.valueChanged.connect(self._on_ils_dirty)
        layout_conv.addWidget(self.spin_fwhm_lorentzian)

        self.btn_apply_ils = QPushButton("Apply ILS")
        self.btn_apply_ils.setStyleSheet("font-weight: bold;")
        self.btn_apply_ils.clicked.connect(self.apply_convolution)
        layout_conv.addWidget(self.btn_apply_ils)
        lay_ref.addWidget(self._ils_container)

        def _toggle_ils():
            self._ils_visible = not self._ils_visible
            self._ils_container.setVisible(self._ils_visible)
            self._btn_toggle_ils.setText(
                "▼  ILS 콘볼루션 (고급 — Stage 2 레퍼런스 사용 시 불필요)"
                if self._ils_visible else
                "▶  ILS 콘볼루션 (고급 — Stage 2 레퍼런스 사용 시 불필요)")
        self._btn_toggle_ils.clicked.connect(_toggle_ils)

        grp_ref.setLayout(lay_ref)
        left_layout.addWidget(grp_ref)
        
        # --- 2. Fit Range & Calibration Section ---
        grp_set = QGroupBox("2. Fit Range & Calibration")
        lay_set = QVBoxLayout()
        
        # Pixel-based Selection
        layout_px = QHBoxLayout()
        btn_load_wl = QPushButton("Load X-Axis (nm)")
        btn_load_wl.clicked.connect(self.load_wavelength_cal)
        layout_px.addWidget(btn_load_wl)
        
        self.lbl_fwhm_display = QLabel("💡 FWHM: Pending")
        self.lbl_fwhm_display.setStyleSheet("color: #757575; font-weight: bold; padding: 3px;")
        layout_px.addWidget(self.lbl_fwhm_display)
        layout_px.addStretch(1)
        
        layout_px.addWidget(QLabel("Pixel Min:"))
        self.txt_min = QLineEdit("0")
        self.txt_min.setFixedWidth(int(50 * self._s))
        layout_px.addWidget(self.txt_min)
        layout_px.addWidget(QLabel("Max:"))
        self.txt_max = QLineEdit("2047")
        self.txt_max.setFixedWidth(int(50 * self._s))
        layout_px.addWidget(self.txt_max)
        
        btn_sel = QPushButton("Vis. Select")
        btn_sel.clicked.connect(self.open_selector)
        layout_px.addWidget(btn_sel)
        lay_set.addLayout(layout_px)
        
        # Wavelength-based Selection — 시작 nm ~ 끝 nm 직접 입력
        layout_nm = QHBoxLayout()
        layout_nm.addWidget(QLabel("Fit 범위(nm):"))
        self.spin_fit_start_nm = QDoubleSpinBox()
        self.spin_fit_start_nm.setRange(200, 1000)
        self.spin_fit_start_nm.setDecimals(1)
        self.spin_fit_start_nm.setValue(435.0)
        layout_nm.addWidget(self.spin_fit_start_nm)
        layout_nm.addWidget(QLabel("~"))
        self.spin_fit_end_nm = QDoubleSpinBox()
        self.spin_fit_end_nm.setRange(200, 1000)
        self.spin_fit_end_nm.setDecimals(1)
        self.spin_fit_end_nm.setValue(480.0)
        layout_nm.addWidget(self.spin_fit_end_nm)

        btn_apply_nm = QPushButton("nm 범위 적용")
        btn_apply_nm.clicked.connect(self.set_range_from_nm)
        layout_nm.addWidget(btn_apply_nm)
        lay_set.addLayout(layout_nm)

        # 채널별 Fit 범위(nm) — ≥2채널 감지 시에만 표시. 위 메인 행 = CH1(ROI1).
        self._ch_fit_nm = {}     # ch -> (start_spin, end_spin)
        self._ch_fit_rows = {}   # ch -> 행 위젯(표시/숨김)
        for _ch, _roi in ((2, 'ROI2'), (3, 'ROI3')):
            _roww = QWidget()
            _rl = QHBoxLayout(_roww)
            _rl.setContentsMargins(0, 0, 0, 0)
            _rl.addWidget(QLabel(f"  └ CH{_ch}({_roi}) nm:"))
            _s = QDoubleSpinBox(); _s.setRange(200, 1000); _s.setDecimals(1); _s.setValue(435.0)
            _e = QDoubleSpinBox(); _e.setRange(200, 1000); _e.setDecimals(1); _e.setValue(480.0)
            _rl.addWidget(_s); _rl.addWidget(QLabel("~")); _rl.addWidget(_e); _rl.addStretch(1)
            _roww.setVisible(False)
            lay_set.addWidget(_roww)
            self._ch_fit_nm[_ch] = (_s, _e)
            self._ch_fit_rows[_ch] = _roww

        grp_set.setLayout(lay_set)
        left_layout.addWidget(grp_set)
        
        # --- Parameters Section (Collapsible) ---
        self._params_visible = True
        self._btn_toggle_params = QPushButton("▼  Parameters")
        self._btn_toggle_params.setStyleSheet(
            "text-align: left; font-weight: bold; "
            "border: 1px solid #B0BEC5; padding: 4px 8px;")
        left_layout.addWidget(self._btn_toggle_params)

        self._params_container = QWidget()
        lay_params_outer = QVBoxLayout(self._params_container)
        lay_params_outer.setContentsMargins(0, 0, 0, 0)

        grp_calib = QGroupBox("Parameters")
        lay_calib_main = QVBoxLayout()

        lay_calib = QHBoxLayout()
        lay_calib.addWidget(QLabel("Step Limit:"))
        self.spin_step_limit = QDoubleSpinBox()
        self.spin_step_limit.setRange(0.01, 10.0)
        self.spin_step_limit.setSingleStep(0.1)
        self.spin_step_limit.setDecimals(2)
        self.spin_step_limit.setValue(0.5)
        self.spin_step_limit.setToolTip("Maximum pixels that can be moved per frame")
        lay_calib.addWidget(self.spin_step_limit)

        lay_calib.addWidget(QLabel("Poly Deg:"))
        self.spin_poly_deg = QSpinBox()
        self.spin_poly_deg.setRange(0, 10)
        self.spin_poly_deg.setValue(3)
        lay_calib.addWidget(self.spin_poly_deg)

        lay_calib.addWidget(QLabel("Tikhonov λ:"))
        self.spin_lambda = QDoubleSpinBox()
        self.spin_lambda.setRange(0.0, 10.0)
        self.spin_lambda.setSingleStep(0.0001)
        self.spin_lambda.setDecimals(6)
        self.spin_lambda.setValue(0.0000)
        self.spin_lambda.setToolTip("Ridge Penalty: 0 = Off, 1e-4 = Monitoring")
        lay_calib.addWidget(self.spin_lambda)

        self.chk_robust = QCheckBox("🛡️ Robust (IRLS)")
        self.chk_robust.setToolTip("Auto-ignore spike noise and cosmic rays")
        self.chk_robust.setChecked(False)
        lay_calib.addWidget(self.chk_robust)

        self.ref_props = {}
        btn_props = QPushButton("⚙️ Properties")
        btn_props.setStyleSheet("font-weight: bold;")
        btn_props.clicked.connect(self.open_ref_properties)
        lay_calib.addWidget(btn_props)
        lay_calib_main.addLayout(lay_calib)

        lay_thresh = QHBoxLayout()
        lay_thresh.addWidget(QLabel("OK RMS Threshold (%):"))
        self.spin_rms_thresh = QDoubleSpinBox()
        self.spin_rms_thresh.setRange(1.0, 50.0)
        self.spin_rms_thresh.setSingleStep(1.0)
        self.spin_rms_thresh.setDecimals(1)
        self.spin_rms_thresh.setValue(10.0)
        self.spin_rms_thresh.setToolTip(
            "A fit is accepted as OK when RMS residual < (signal mean × threshold).\n"
            "10% = standard DOAS quality criterion.\n"
            "Lower = stricter. Raise only if data is extremely noisy.")
        lay_thresh.addWidget(self.spin_rms_thresh)
        lay_thresh.addWidget(QLabel("  (10% = standard DOAS criterion)"))
        lay_calib_main.addLayout(lay_thresh)

        lay_kalman = QHBoxLayout()
        lay_kalman.addWidget(QLabel("🔄 Kalman  Q:"))
        self.spin_kalman_q = QDoubleSpinBox()
        self.spin_kalman_q.setRange(0.0001, 1.0)
        self.spin_kalman_q.setSingleStep(0.0005)
        self.spin_kalman_q.setDecimals(4)
        self.spin_kalman_q.setValue(0.0005)
        self.spin_kalman_q.setToolTip(
            "Kalman Q — process noise / tracking speed\n"
            "Higher = tracks rapid changes faster (e.g. vehicle plumes)\n"
            "Lower = smoother output for stable ambient monitoring")
        lay_kalman.addWidget(self.spin_kalman_q)
        lay_kalman.addWidget(QLabel("R:"))
        self.spin_kalman_r = QDoubleSpinBox()
        self.spin_kalman_r.setRange(0.001, 1.0)
        self.spin_kalman_r.setSingleStep(0.01)
        self.spin_kalman_r.setDecimals(3)
        self.spin_kalman_r.setValue(0.050)
        self.spin_kalman_r.setToolTip(
            "Kalman R — measurement noise / smoothing strength\n"
            "Higher = stronger smoothing (stable background)\n"
            "Lower = faster response, less smoothing")
        lay_kalman.addWidget(self.spin_kalman_r)
        lay_calib_main.addLayout(lay_kalman)

        grp_calib.setLayout(lay_calib_main)
        lay_params_outer.addWidget(grp_calib)
        left_layout.addWidget(self._params_container)

        def _toggle_params():
            self._params_visible = not self._params_visible
            self._params_container.setVisible(self._params_visible)
            self._btn_toggle_params.setText(
                "▼  Parameters" if self._params_visible else "▶  Parameters (hidden)")
        self._btn_toggle_params.clicked.connect(_toggle_params)

        # --- 3. Analysis Control Section ---
        grp_ctl = QGroupBox("3. Analysis")
        lay_ctl = QVBoxLayout()
        
        layout_row1 = QHBoxLayout()
        btn_load = QPushButton("Load Data")
        btn_load.clicked.connect(self.load_data)
        layout_row1.addWidget(btn_load)
        
        layout_row2 = QHBoxLayout()
        self.b_run = QPushButton("RUN")
        self.b_run.clicked.connect(self.start_analysis)
        self.b_stop = QPushButton("STOP")
        self.b_stop.clicked.connect(self.stop_analysis)
        self.b_stop.setEnabled(False)
        self.b_save = QPushButton("Save")
        self.b_save.clicked.connect(self.save)
        
        layout_row2.addWidget(self.b_run)
        layout_row2.addWidget(self.b_stop)
        layout_row2.addWidget(self.b_save)
        
        layout_perf = QHBoxLayout()
        layout_perf.addWidget(QLabel("Update Graph Every:"))
        self.spin_update = QSpinBox()
        self.spin_update.setRange(1, 1000)
        self.spin_update.setValue(10)
        layout_perf.addWidget(self.spin_update)
        layout_perf.addWidget(QLabel("files"))
        
        self.chk_observe = QCheckBox("Observe (Slow Mode)")
        self.chk_observe.setStyleSheet("font-weight: bold; color: #1565C0;")
        layout_perf.addWidget(self.chk_observe)
        
        self.chk_turbo = QCheckBox("Turbo")
        layout_perf.addWidget(self.chk_turbo)
        
        lay_ctl.addLayout(layout_row1)
        lay_ctl.addLayout(layout_perf)
        lay_ctl.addLayout(layout_row2)
        grp_ctl.setLayout(lay_ctl)
        left_layout.addWidget(grp_ctl)
        
        # Status Bar, Progress Bar, and Result Table
        self.status = QLabel("Ready")
        self.pbar = QProgressBar()
        self.table = QTableWidget()
        self.table.cellDoubleClicked.connect(self.on_table_double_click)
        self.table.cellClicked.connect(self.on_table_single_click)
        
        # Enable right-click context menu on the file list for the "Set as I0" action
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)

        left_layout.addWidget(self.status)
        left_layout.addWidget(self.pbar)
        left_layout.addWidget(self.table)
        splitter.addWidget(left_widget)
        
        # =========================================================
        # [Right] Monitor Tab Area
        # =========================================================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # Main Tab Widget
        self.main_tabs = QTabWidget()

        # Tab 0: Daily Run (scenario + setup status checklist + R trend)
        self.daily_run_tab = QWidget()
        self.setup_daily_run_tab()
        self.main_tabs.addTab(self.daily_run_tab, "📋 Daily Run")

        # Tab 1: Cavity Setup
        self.setup_tab = QWidget()
        self.setup_cavity_tab()
        self.main_tabs.addTab(self.setup_tab, "🛠️ Setup")

        # Tab 2: Analysis Monitor
        self.monitor = MonitorWidget(self.engine)
        self.main_tabs.addTab(self.monitor, "📈 Analysis Monitor")

        # Tab 3: Result Viewer (저장된 R/α/레퍼런스/농도 결과 파일을 불러와 표시)
        from .ui_result_viewer import ResultViewerWidget
        self.result_viewer = ResultViewerWidget(self)
        self.main_tabs.addTab(self.result_viewer, "📂 결과 뷰어")

        right_layout.addWidget(self.main_tabs)
        
        # Keep Existing Signal Connections
        self.monitor.cb_view.currentIndexChanged.connect(self.refresh_viewer)
        self.monitor.roi_selected.connect(self.apply_roi_from_graph)

        splitter.addWidget(right_widget)

        self._setup_shortcuts()

    def _setup_shortcuts(self):
        """Register keyboard shortcuts for common operations."""
        QShortcut(QKeySequence("F5"),      self).activated.connect(self.start_analysis)
        QShortcut(QKeySequence("Escape"),  self).activated.connect(self.stop_analysis)
        QShortcut(QKeySequence("Ctrl+S"),  self).activated.connect(self.save)

    # =========================================================
    # Tab 0: Daily Run
    # =========================================================
    def setup_daily_run_tab(self):
        """Build the Daily Run tab: scenario, setup status checklist, R trend charts."""
        lay = QVBoxLayout(self.daily_run_tab)

        # ── Scenario + Setup Status (R 표시는 Setup 탭 Cavity Diagnostics로 일원화) ──
        left_w = QWidget()
        left_v = QVBoxLayout(left_w)

        grp_scenario = QGroupBox("💾 Fit Scenario")
        grp_scenario.setStyleSheet("QGroupBox { font-weight: bold; color: #2E7D32; }")
        lay_scen = QHBoxLayout()
        btn_save_scen = QPushButton("📥 Save Settings")
        btn_load_scen = QPushButton("📂 Load Settings")
        btn_save_scen.clicked.connect(self.save_scenario)
        btn_load_scen.clicked.connect(self.load_scenario)
        lay_scen.addWidget(btn_save_scen)
        lay_scen.addWidget(btn_load_scen)
        grp_scenario.setLayout(lay_scen)
        left_v.addWidget(grp_scenario)

        grp_status = QGroupBox("✅ Setup Status")
        grp_status.setStyleSheet("QGroupBox { font-weight: bold; color: #1565C0; }")
        lay_status = QVBoxLayout()

        self.lbl_st_wl    = QLabel("❌  Wavelength calibration: not loaded")
        self.lbl_st_i0    = QLabel("⚠️   I₀ (Zero-Air): not set (auto from ZA scans)")
        self.lbl_st_r     = QLabel("⚠️   R-Curve: not loaded (auto from He scans)")
        self.lbl_st_refs  = QLabel("❌  References: not locked")
        self.lbl_st_range = QLabel("⚠️   Fit range: 0–2047 px (full sensor)")

        for lbl in (self.lbl_st_wl, self.lbl_st_i0, self.lbl_st_r,
                    self.lbl_st_refs, self.lbl_st_range):
            lbl.setStyleSheet("padding: 2px 6px; font-size: 11px;")
            lay_status.addWidget(lbl)

        btn_refresh = QPushButton("🔄 Refresh Status")
        btn_refresh.clicked.connect(self._refresh_setup_status)
        lay_status.addWidget(btn_refresh)
        grp_status.setLayout(lay_status)
        left_v.addWidget(grp_status)
        left_v.addStretch(1)
        lay.addWidget(left_w)

    # ──────────────────────────────────────────────────────────────────
    # Daily Run helpers
    # ──────────────────────────────────────────────────────────────────
    def _refresh_setup_status(self):
        """Update all checklist labels in the Daily Run tab."""
        if not hasattr(self, 'lbl_st_wl'):
            return  # tab not built yet

        # Wavelength calibration
        wl_ok = hasattr(self, 'wavelengths') and self.wavelengths is not None
        if wl_ok:
            wl = np.asarray(self.wavelengths).flatten()
            self.lbl_st_wl.setText(
                f"✅  Wavelength: {wl.min():.2f}–{wl.max():.2f} nm  ({len(wl)} px)")
            self.lbl_st_wl.setStyleSheet("color: #2E7D32; padding: 2px 6px; font-size: 11px;")
            # Auto-correct txt_max if it still holds the default 2047 and wl is shorter
            try:
                n = len(wl)
                if int(self.txt_max.text()) >= n:
                    self.txt_max.setText(str(n - 1))
            except ValueError:
                pass
        else:
            self.lbl_st_wl.setText("❌  Wavelength calibration: not loaded")
            self.lbl_st_wl.setStyleSheet("color: #c62828; padding: 2px 6px; font-size: 11px;")

        # I₀
        i0_ok = hasattr(self, 'i0_data') and self.i0_data is not None
        if i0_ok:
            self.lbl_st_i0.setText(
                f"✅  I₀: loaded ({len(self.i0_data)} px,  mean={self.i0_data.mean():.1f})")
            self.lbl_st_i0.setStyleSheet("color: #2E7D32; padding: 2px 6px; font-size: 11px;")
        else:
            self.lbl_st_i0.setText("⚠️   I₀: not set  (auto-extracted from ZA scans during run)")
            self.lbl_st_i0.setStyleSheet("color: #e65100; padding: 2px 6px; font-size: 11px;")

        # R-curve
        r_ok = hasattr(self, 'r_data') and self.r_data is not None
        if r_ok:
            r_arr = np.asarray(self.r_data, dtype=float)
            r_fin = r_arr[np.isfinite(r_arr)]
            if len(r_fin) > 0:
                r_med = float(np.median(r_fin))
                leff  = self.spin_d_len.value() / (1.0 - r_med)
                self.lbl_st_r.setText(
                    f"✅  R: {r_med*100:.4f}%  Leff ≈ {leff:.0f} cm")
            else:
                self.lbl_st_r.setText("✅  R: loaded (no finite values in pixel range)")
            self.lbl_st_r.setStyleSheet("color: #2E7D32; padding: 2px 6px; font-size: 11px;")
            self._update_daily_r_chart()
        else:
            self.lbl_st_r.setText("⚠️   R-Curve: not loaded  (auto from He scans during run)")
            self.lbl_st_r.setStyleSheet("color: #e65100; padding: 2px 6px; font-size: 11px;")

        # References locked
        refs_ok = hasattr(self, 'engine') and len(self.engine.gas_list) > 0
        if refs_ok:
            self.lbl_st_refs.setText(
                f"✅  References locked: {', '.join(self.engine.gas_list)}")
            self.lbl_st_refs.setStyleSheet("color: #2E7D32; padding: 2px 6px; font-size: 11px;")
        else:
            self.lbl_st_refs.setText("❌  References: not locked  (lock before RUN)")
            self.lbl_st_refs.setStyleSheet("color: #c62828; padding: 2px 6px; font-size: 11px;")

        # Fit range
        try:
            fmin = int(self.txt_min.text())
            fmax = int(self.txt_max.text())
            rng  = fmax - fmin
            if wl_ok:
                wl = np.asarray(self.wavelengths).flatten()
                lo = wl[fmin] if fmin < len(wl) else 0
                hi = wl[min(fmax, len(wl)-1)]
                self.lbl_st_range.setText(
                    f"✅  Fit range: px {fmin}–{fmax}  ({lo:.1f}–{hi:.1f} nm,  {rng} px)")
            else:
                self.lbl_st_range.setText(
                    f"✅  Fit range: px {fmin}–{fmax}  ({rng} px)")
            self.lbl_st_range.setStyleSheet("color: #2E7D32; padding: 2px 6px; font-size: 11px;")
        except ValueError:
            self.lbl_st_range.setText("❌  Fit range: invalid pixel values")
            self.lbl_st_range.setStyleSheet("color: #c62828; padding: 2px 6px; font-size: 11px;")

    def _update_fwhm_px_from_nm(self, nm_val):
        """Convert FWHM nm → px using loaded wavelength axis; update spin_fwhm."""
        if hasattr(self, 'wavelengths') and self.wavelengths is not None:
            wl = np.asarray(self.wavelengths).flatten()
            if len(wl) > 2:
                mid  = len(wl) // 2
                disp = abs(float(wl[mid+1] - wl[mid-1])) / 2.0
            else:
                disp = 0.051
        else:
            disp = 0.051  # nm/px rough estimate from default calibration

        if disp > 0:
            self.spin_fwhm.blockSignals(True)
            self.spin_fwhm.setValue(round(nm_val / disp, 2))
            self.spin_fwhm.blockSignals(False)
        self._on_ils_dirty()

    def _on_ils_dirty(self):
        """Mark ILS as requiring re-application; turn Apply ILS button orange."""
        self._ils_applied = False
        if hasattr(self, 'btn_apply_ils'):
            self.btn_apply_ils.setStyleSheet(
                "font-weight: bold;")

    def _update_daily_r_chart(self):
        """Plot current R(λ) in the Daily Run tab."""
        if not hasattr(self, '_daily_r_pw'):
            return
        if not (hasattr(self, 'r_data') and self.r_data is not None):
            return
        self._daily_r_pw.clear()
        r_arr = np.asarray(self.r_data, dtype=float)
        if hasattr(self, 'wavelengths') and self.wavelengths is not None:
            wl = np.asarray(self.wavelengths).flatten()
            x  = wl[:len(r_arr)] if len(wl) >= len(r_arr) else np.arange(len(r_arr))
            self._daily_r_pw.setLabel('bottom', 'Wavelength (nm)')
        else:
            x = np.arange(len(r_arr))
            self._daily_r_pw.setLabel('bottom', 'Pixel')
        r_fin = r_arr[np.isfinite(r_arr)]
        if len(r_fin) > 0:
            r_med = float(np.median(r_fin))
            d     = self.spin_d_len.value()
            leff  = d / (1.0 - r_med)
            self._daily_r_pw.plot(x, r_arr * 100,
                                  pen=pg.mkPen('#6A1B9A', width=1.5))
            self._daily_r_pw.addLine(
                y=r_med * 100,
                pen=pg.mkPen('r', width=1.5, style=Qt.PenStyle.DashLine))
            self._daily_r_pw.setTitle(
                f"R(λ)  median={r_med*100:.4f}%  Leff≈{leff:.0f} cm")

    def _update_daily_rt_chart(self, cold_results, hot_pns_results, hot_ans_results):
        """Populate the R time-series chart in Daily Run from R Trend Monitor results.

        Each result dict has keys: timestamp (datetime), r_mean, r_std, leff_mean, …
        Three channels: Cold, Hot PNs(roi1), Hot ANs(roi2).
        """
        if not hasattr(self, '_daily_rt_pw'):
            return
        self._daily_rt_pw.clear()
        self._daily_rt_pw.addLegend(offset=(10, 10))

        import datetime as _dt

        def _plot_series(results, color, label):
            if not results:
                return
            pts = [(r['timestamp'], r['r_mean'])
                   for r in results
                   if r.get('r_mean') is not None and r.get('timestamp') is not None]
            if not pts:
                return
            # Convert datetime → Unix epoch float for DateAxisItem.
            # Strip tzinfo first so the chosen-tz wall clock is shown (matches monitor).
            ts = []
            for t, _ in pts:
                if isinstance(t, _dt.datetime):
                    ts.append(t.replace(tzinfo=None).timestamp())
                else:
                    ts.append(float(t))
            rv = [r * 100 for _, r in pts]
            self._daily_rt_pw.plot(ts, rv,
                                   pen=pg.mkPen(color, width=2),
                                   symbol='o', symbolSize=5,
                                   name=label)

        _plot_series(cold_results,    '#2196F3', 'Cold')
        _plot_series(hot_pns_results, '#FF6F00', 'Hot PNs')
        _plot_series(hot_ans_results, '#D32F2F', 'Hot ANs')
        n = ((len(cold_results) if cold_results else 0)
             + (len(hot_pns_results) if hot_pns_results else 0)
             + (len(hot_ans_results) if hot_ans_results else 0))
        self._daily_rt_pw.setTitle(f"R time series — {n} cycles (Cold/Hot)")

    def _update_setup_rt_charts(self, cold_results, hot_pns_results, hot_ans_results, out_dir=None):
        """Populate the R(t)/Leff(t) plots in the Setup tab Cavity Diagnostics panel.

        시계열 점을 클릭하면 그 파일의 _R.dat 를 읽어 'R(λ) 스펙트럼' 탭에
        파장별 R 곡선을 그린다(A형). 클릭→파일 매핑을 위해 채널별 결과 리스트와
        out_dir 을 _setup_rt_click_map 에 저장한다.
        """
        if not hasattr(self, '_setup_r_trend_pw'):
            return

        import datetime as _dt

        COLORS = [
            ('#2196F3', 'Cold',    'cold'),
            ('#FF6F00', 'Hot PNs', 'hot_pns'),
            ('#D32F2F', 'Hot ANs', 'hot_ans'),
        ]

        self._setup_r_trend_pw.clear()
        self._setup_r_trend_pw.addLegend(offset=(10, 10))
        self._setup_leff_pw.clear()
        self._setup_leff_pw.addLegend(offset=(10, 10))
        # id(PlotDataItem) -> {results, ch_key, color, out_dir}  (점 클릭 매핑용)
        self._setup_rt_click_map = {}

        def _ts(t):
            if isinstance(t, _dt.datetime):
                return t.replace(tzinfo=None).timestamp()
            return float(t)

        def _register_clickable(pdi, kept, ch_key, color):
            self._setup_rt_click_map[id(pdi)] = {
                "results": kept, "ch_key": ch_key,
                "color": color, "out_dir": out_dir,
            }
            try:
                pdi.sigPointsClicked.connect(self._on_setup_rt_point_clicked)
            except Exception:
                pass

        for results, (color, label, ch_key) in zip(
                [cold_results, hot_pns_results, hot_ans_results], COLORS):
            if not results:
                continue
            # 클릭 인덱스가 결과와 1:1로 맞도록, 플롯에 쓰는 것과 동일한 필터 리스트 사용
            kept_r = [r for r in results
                      if r.get('r_mean') is not None and r.get('timestamp') is not None]
            kept_l = [r for r in results
                      if r.get('leff_mean') is not None and r.get('timestamp') is not None]
            if kept_r:
                ts = [_ts(r['timestamp']) for r in kept_r]
                rv = [r['r_mean'] * 100 for r in kept_r]
                pdi = self._setup_r_trend_pw.plot(ts, rv,
                                                  pen=pg.mkPen(color, width=2),
                                                  symbol='o', symbolSize=6,
                                                  name=label)
                _register_clickable(pdi, kept_r, ch_key, color)
            if kept_l:
                ts = [_ts(r['timestamp']) for r in kept_l]
                lv = [r['leff_mean'] for r in kept_l]
                pdi_l = self._setup_leff_pw.plot(ts, lv,
                                                 pen=pg.mkPen(color, width=2),
                                                 symbol='s', symbolSize=6,
                                                 name=label)
                _register_clickable(pdi_l, kept_l, ch_key, color)

        n = ((len(cold_results) if cold_results else 0)
             + (len(hot_pns_results) if hot_pns_results else 0)
             + (len(hot_ans_results) if hot_ans_results else 0))
        self._setup_r_trend_pw.setTitle(f"R 시계열 — {n} cycles  (점 클릭 → R(λ) 스펙트럼 탭)")
        self._setup_leff_pw.setTitle(f"Leff 시계열 — {n} cycles")

        # Auto-switch to the time-series tab
        if hasattr(self, '_diag_tabs'):
            self._diag_tabs.setCurrentIndex(1)

    def _on_setup_rt_point_clicked(self, plot_item, points, *args):
        """시계열 점 클릭 → 해당 파일의 _R.dat 를 읽어 R(λ) 스펙트럼 탭에 표시."""
        rec = getattr(self, '_setup_rt_click_map', {}).get(id(plot_item))
        if not rec or not points:
            return
        try:
            idx = points[0].index()
        except Exception:
            return
        results = rec["results"]
        if idx is None or idx < 0 or idx >= len(results):
            return
        r = results[idx]
        fname = r.get("filename", "")
        out_dir = rec.get("out_dir") or "."
        file_date = "-".join(fname.split("-")[:3])
        base = os.path.splitext(fname)[0]
        ch_subdir = {"cold": "R_Cold", "hot_pns": "R_Hot_PNs",
                     "hot_ans": "R_Hot_ANs"}.get(rec["ch_key"], "R_Cold")
        dat_path = os.path.join(out_dir, ch_subdir, file_date, f"{base}_R.dat")
        if not os.path.exists(dat_path):
            dat_path = os.path.join(out_dir, file_date, f"{base}_R.dat")
        roi = r.get("fit_window_nm", (400, 500))
        self._show_setup_r_spectrum(dat_path, roi, rec["color"])

    def _show_setup_r_spectrum(self, dat_path, roi, color):
        """R(λ) 스펙트럼 탭(plot_diagnostic)에 _R.dat 의 raw R 점 + 5차 피팅 선을 그림."""
        if not hasattr(self, 'plot_diagnostic'):
            return
        self.p1.clear()
        try:
            self.p2.clear()
        except Exception:
            pass
        # 스펙트럼 탭으로 전환
        if hasattr(self, '_diag_tabs'):
            self._diag_tabs.setCurrentIndex(0)
        if not os.path.exists(dat_path):
            self.plot_diagnostic.setTitle(f"데이터 파일 없음: {os.path.basename(dat_path)}")
            return
        try:
            data = np.loadtxt(dat_path, skiprows=2)
            wave, r_raw, r_fit = data[:, 0], data[:, 1], data[:, 2]
            self.p1.plot(wave, r_raw, pen=None, symbol='o', symbolSize=3,
                         symbolBrush=(150, 150, 150, 150))
            self.p1.plot(wave, r_fit, pen=pg.mkPen(color, width=2.5))
            try:
                roi_min, roi_max = roi
                self.p1.addItem(pg.LinearRegionItem(
                    [roi_min, roi_max], movable=False, brush=(0, 255, 0, 20)))
            except Exception:
                pass
            self.plot_diagnostic.setLabel('left', 'Reflectance R', color='b')
            self.plot_diagnostic.setLabel('bottom', 'Wavelength (nm)')
            self.plot_diagnostic.setTitle(f"R(λ) — {os.path.basename(dat_path)}")
            fin = np.isfinite(r_fit)
            if fin.any():
                self.p1.vb.setYRange(float(np.nanmin(r_fit[fin])), 1.0, padding=0.1)
        except Exception as e:
            self.plot_diagnostic.setTitle(f"플롯 실패: {e}")

    def setup_cavity_tab(self):
        """Configure the layout for the Pre-Analysis Cavity Setup tab."""
        # Main horizontal layout: Controls on Left, Diagnostics on Right
        main_layout = QHBoxLayout(self.setup_tab)
        
        # --- Left Panel: Controls ---
        control_layout = QVBoxLayout()
        
        # Group 1: Daily-use tools
        grp_calib = QGroupBox("1. Tools")
        lay_calib = QVBoxLayout()

        btn_calib_tool = QPushButton("🔍 Wavelength Calibration Tool")
        btn_calib_tool.clicked.connect(self.open_wavelength_calibration)

        btn_ref_gen = QPushButton("✂️ Reference Generator")
        btn_ref_gen.clicked.connect(self.open_reference_generator)
        btn_ref_gen.setStyleSheet("font-weight: bold;")

        btn_r_trend = QPushButton("📈 R Trend Monitor (거울 반사율 시계열)")
        btn_r_trend.clicked.connect(self.open_r_trend_monitor)
        btn_r_trend.setStyleSheet("font-weight: bold;")
        btn_r_trend.setToolTip(
            "raw .dat 파일 디렉토리를 스캔해서 파일마다 R 값을 계산하고\n"
            "반사율 시계열 그래프(PNG)와 결과(.dat)를 저장합니다.\n"
            "Cold / Hot 채널 분리 처리, Sellmeier 기반 Rayleigh 모델 사용."
        )

        lay_calib.addWidget(btn_calib_tool)
        lay_calib.addWidget(btn_ref_gen)
        lay_calib.addWidget(btn_r_trend)
        grp_calib.setLayout(lay_calib)
        control_layout.addWidget(grp_calib)

        # Group 2: 2단계 분석 (Raw → Alpha → 피팅)
        grp_alpha_two = QGroupBox("2. 2단계 분석  (Raw → Alpha → 피팅)")
        lay_alpha_two = QVBoxLayout()

        lbl_alpha_desc = QLabel(
            "측정 파일에서 먼저 α 스펙트럼을 추출(1단계)한 뒤,\n"
            "저장된 α 파일을 불러와 DOAS 피팅을 수행(2단계)합니다.")
        lbl_alpha_desc.setStyleSheet("color: #546E7A; font-size: 11px; padding: 2px 0;")
        lay_alpha_two.addWidget(lbl_alpha_desc)

        btn_step1 = QPushButton("▶  1단계: Raw → Alpha 파일 생성")
        btn_step1.clicked.connect(self.export_alpha_files)
        btn_step1.setStyleSheet(
            "font-weight: bold; "
            "padding: 6px; border: 1px solid #90CAF9;")
        btn_step1.setToolTip(
            "He/ZA 캘리브레이션 → ambient 스캔마다 α(cm⁻¹) 계산\n"
            "→ 지정 폴더에 {소스파일명}_alpha_trace.dat 저장.\n"
            "먼저 '측정 파일 로드'와 '파장 캘리브레이션 로드'를 완료하세요.")
        lay_alpha_two.addWidget(btn_step1)

        # ambient 시간평균 창 (박사님 Step2 avgsec, 기본 60초). DOAS 피팅 안정용.
        lay_avgsec = QHBoxLayout()
        lay_avgsec.addWidget(QLabel("ambient 평균(초):"))
        self.spin_alpha_avgsec = QDoubleSpinBox()
        self.spin_alpha_avgsec.setRange(0.0, 600.0)
        self.spin_alpha_avgsec.setDecimals(0)
        self.spin_alpha_avgsec.setSingleStep(10.0)
        self.spin_alpha_avgsec.setValue(60.0)
        self.spin_alpha_avgsec.setFixedWidth(90)
        self.spin_alpha_avgsec.setToolTip(
            "α 계산 전 ambient 스펙트럼을 이 초만큼 시간평균해 노이즈를 줄인다.\n"
            "박사님 기본값 60초. 단일 스캔(~1초)은 noise가 커 DOAS 피팅이 불안정.\n"
            "0 = 평균 없이 스캔별 α.")
        lay_avgsec.addWidget(self.spin_alpha_avgsec)
        lay_avgsec.addStretch(1)
        lay_alpha_two.addLayout(lay_avgsec)

        # Alpha save dir (also used by main RUN → save_alpha checkbox)
        lay_alpha_save = QHBoxLayout()
        self.chk_save_alpha = QCheckBox("RUN 중 α 저장 (직접 분석 병행)")
        self.chk_save_alpha.setToolTip(
            "메인 RUN 버튼으로 직접 분석할 때도 각 스캔의 α 스펙트럼을\n"
            "파일로 함께 저장합니다. 2단계 분석과 독립적으로 동작합니다.\n"
            "파일명: {원본파일명}_alpha.dat  단위: cm⁻¹")
        self.lbl_alpha_dir = QLabel("(저장 폴더 미설정)")
        self.lbl_alpha_dir.setStyleSheet("color: gray; font-size: 11px;")
        btn_alpha_dir = QPushButton("폴더")
        btn_alpha_dir.setFixedWidth(50)
        btn_alpha_dir.clicked.connect(self.browse_alpha_save_dir)
        lay_alpha_save.addWidget(self.chk_save_alpha)
        lay_alpha_save.addWidget(self.lbl_alpha_dir, 1)
        lay_alpha_save.addWidget(btn_alpha_dir)
        lay_alpha_two.addLayout(lay_alpha_save)

        btn_step2 = QPushButton("▶  2단계: Alpha 파일 → 피팅")
        btn_step2.clicked.connect(self.run_alpha_fit)
        btn_step2.setStyleSheet(
            "font-weight: bold; "
            "padding: 6px; border: 1px solid #A5D6A7;")
        btn_step2.setToolTip(
            "1단계로 생성한 *_alpha_trace.dat 파일을 선택하여\n"
            "DOAS 피팅 수행 → *_fit.tsv 결과 저장.\n"
            "먼저 '레퍼런스 Lock'과 '파장 캘리브레이션 로드'를 완료하세요.")
        lay_alpha_two.addWidget(btn_step2)

        grp_alpha_two.setLayout(lay_alpha_two)
        control_layout.addWidget(grp_alpha_two)

        # R-Curve Generator (standalone tool for offline R derivation)
        btn_r_gen = QPushButton("📊 R-Curve Generator (offline .mat / separate files)")
        btn_r_gen.clicked.connect(self.open_r_generator)
        btn_r_gen.setStyleSheet("padding: 4px;")
        btn_r_gen.setToolTip(
            "별도 He/ZA 파일(또는 .mat)에서 R-Curve를 계산합니다.\n"
            "Araon 측정 파일처럼 He/ZA가 내장된 경우에는 불필요합니다.\n"
            "(R은 RUN 중 자동 추출되거나 R Trend Monitor로 배치 계산됩니다.)")
        control_layout.addWidget(btn_r_gen)

        # Group 3: Cavity Setup — only d, RL, Leff (everything else from raw file)
        grp_physics = QGroupBox("3. Cavity Setup")
        lay_physics = QFormLayout()

        # Auto-detected channel info (read-only — updated when files are loaded)
        self._detected_channels = 1   # updated by _auto_detect_channels()
        self.lbl_channel_info = QLabel("—  (파일 로드 후 자동 감지)")
        self.lbl_channel_info.setStyleSheet("color: #546E7A; font-style: italic;")
        lay_physics.addRow("채널 감지:", self.lbl_channel_info)

        # Cavity Length
        self.spin_d_len = QDoubleSpinBox()
        self.spin_d_len.setRange(1.0, 1000.0)
        self.spin_d_len.setValue(51.8)
        self.spin_d_len.setDecimals(1)
        self.spin_d_len.setToolTip("CAESAR Araon 2025: CH1=51.8 cm, CH2=51.7 cm, CH3=51.1 cm")
        self.spin_d_len.valueChanged.connect(self.update_leff)
        lay_physics.addRow("Cavity Length d (cm):", self.spin_d_len)

        # Purge Gas Length Ratio (RL)
        lay_rl = QHBoxLayout()
        self.spin_rl_factor = QDoubleSpinBox()
        self.spin_rl_factor.setRange(0.01, 1.0)
        self.spin_rl_factor.setSingleStep(0.001)
        self.spin_rl_factor.setDecimals(4)
        self.spin_rl_factor.setValue(1.0)
        self.spin_rl_factor.setFixedWidth(int(80 * self._s))
        self.spin_rl_factor.setToolTip(
            "퍼지 가스 유효 캐비티 보정 계수 RL = d_eff / d\n"
            "거울 오염 방지용 퍼지 가스가 흐르는 구간은 샘플이 없으므로\n"
            "유효 측정 경로가 물리적 길이보다 짧아집니다.\n"
            "MATLAB 기준 (CAESAR Araon 2025 ASIA-AQ 실측):\n"
            "  CH1 (NO2/CHOCHO): 0.9330\n"
            "  CH2 (HONO/HCHO): 0.9950\n"
            "  CH3 (NO2/CHOCHO): 0.9968\n"
            "1.0 = 보정 없음 (기본값; 측정값 있으면 반드시 입력)"
        )
        lay_rl.addWidget(self.spin_rl_factor)
        lay_rl.addWidget(QLabel("  ← CH1: 0.9330 / CH2: 0.9950 / CH3: 0.9968"))
        lay_rl.addStretch()
        lay_physics.addRow("RL (Purge 보정):", lay_rl)

        # Effective path length display (L_eff = d / (1 - R_mean))
        self.lbl_leff = QLabel("L_eff: — (auto-calculated from He scans during RUN)")
        self.lbl_leff.setStyleSheet("color: #0277BD; font-weight: bold;")
        lay_physics.addRow("Effective Path:", self.lbl_leff)

        grp_physics.setLayout(lay_physics)
        control_layout.addWidget(grp_physics)

        # ▶ Manual Override (collapsed by default)
        # I₀ / R / flags / T / P all come from raw file HK data.
        # This section is only for edge cases: separate files, non-standard flags, fallback T/P.
        self._manual_override_visible = False
        self._btn_toggle_override = QPushButton("▶  Manual Override  (I₀, R, flags, T/P fallback)")
        self._btn_toggle_override.setStyleSheet(
            "text-align: left; color: #546E7A; "
            "border: 1px solid #CFD8DC; padding: 3px 8px;")
        control_layout.addWidget(self._btn_toggle_override)

        self._manual_override_container = QWidget()
        self._manual_override_container.setVisible(False)
        _ov_outer = QVBoxLayout(self._manual_override_container)
        _ov_outer.setContentsMargins(0, 0, 0, 0)

        grp_ov = QGroupBox("⚙️ Manual Override")
        grp_ov.setStyleSheet("QGroupBox { color: #546E7A; }")
        lay_ov = QFormLayout()

        # I0 Setup
        self.lbl_i0_path = QLabel("Auto from ZA scans")
        self.lbl_i0_path.setStyleSheet("color: #546E7A;")
        btn_browse_i0 = QPushButton("Browse I₀")
        btn_browse_i0.clicked.connect(self.browse_i0_file)
        btn_auto_i0 = QPushButton("🔍 Auto from ZA scans")
        btn_auto_i0.clicked.connect(self.auto_extract_i0)
        lay_i0 = QHBoxLayout()
        lay_i0.addWidget(self.lbl_i0_path)
        lay_i0.addWidget(btn_browse_i0)
        lay_i0.addWidget(btn_auto_i0)
        lay_ov.addRow("I₀ (Zero-Air):", lay_i0)

        # Temporal I0 interpolation toggle
        self.chk_temporal_i0 = QCheckBox("Temporal I₀ interpolation (correct lamp drift)")
        self.chk_temporal_i0.setToolTip(
            "Pre-scans the dataset for periodic ZA calibration files and linearly\n"
            "interpolates I0 between them so each ambient file uses the closest\n"
            "calibration rather than a single fixed reference."
        )
        lay_ov.addRow("", self.chk_temporal_i0)

        # R Curve Setup
        self.lbl_r_path = QLabel("Auto from He scans")
        self.lbl_r_path.setStyleSheet("color: #546E7A;")
        btn_browse_r = QPushButton("Browse R")
        btn_browse_r.clicked.connect(self.browse_r_file)
        lay_r = QHBoxLayout()
        lay_r.addWidget(self.lbl_r_path)
        lay_r.addWidget(btn_browse_r)
        lay_ov.addRow("R (Reflectivity):", lay_r)

        # Measurement State Flags — CAESAR Araon 2025: ZA=500~503 / He=510~513 / Ambient=1
        # ※ 500/510만 pure injecting 상태 (cavity가 ZA/He로 완전히 채워진 시점).
        #   501-503/511-513은 setflow/wait 전환구간 — cavity 미충전이라 I0 평균에 넣으면 오염됨.
        #   이 필드에 적힌 값들만 ZA/He로 평균되고, 나머지는 silently drop (ambient에도 안 들어감).
        lay_flags = QHBoxLayout()
        self.txt_flag_za = QLineEdit("500")
        self.txt_flag_za.setFixedWidth(int(130 * self._s))
        self.txt_flag_za.setToolTip(
            "Zero-Air I₀로 평균에 들어갈 flag 번호 (쉼표로 여러 값)\n"
            "CAESAR Araon: 500=injecting(pure), 501=setflow, 502/503=wait\n"
            "★ 기본값 500 (strict) — 501-503은 cavity 미충전이라 I0 오염시킴.\n"
            "  예전 데이터 호환 필요시 \"500,501,502,503\"으로 수동 입력 가능."
        )
        lay_flags.addWidget(QLabel("ZA:"))
        lay_flags.addWidget(self.txt_flag_za)
        lay_flags.addSpacing(8)
        self.txt_flag_he = QLineEdit("510")
        self.txt_flag_he.setFixedWidth(int(130 * self._s))
        self.txt_flag_he.setToolTip(
            "Helium R-cal에 들어갈 flag 번호 (쉼표로 여러 값)\n"
            "CAESAR Araon: 510=injecting(pure), 511=setflow, 512/513=wait\n"
            "★ 기본값 510 (strict) — 511-513은 cavity 미충전이라 R-cal 오염시킴.\n"
            "  예전 데이터 호환 필요시 \"510,511,512,513\"으로 수동 입력 가능."
        )
        lay_flags.addWidget(QLabel("He:"))
        lay_flags.addWidget(self.txt_flag_he)
        lay_flags.addWidget(QLabel("Amb:"))
        self.txt_flag_amb = QLineEdit("1")
        self.txt_flag_amb.setFixedWidth(int(50 * self._s))
        self.txt_flag_amb.setToolTip(
            "Ambient(대기) 측정 플래그 번호\n"
            "MATLAB Alpha 스크립트 기준: flag==1"
        )
        lay_flags.addWidget(self.txt_flag_amb)
        lay_flags.addStretch()
        lay_ov.addRow("측정 상태 플래그:", lay_flags)

        # Temperature / Pressure — fallback only; normally read per-scan from HK data
        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(-50.0, 100.0)
        self.spin_temp.setValue(25.0)
        self.spin_temp.setToolTip(
            "Fallback temperature (°C) — used only when HK data is unavailable\n"
            "Normally T is read per-scan from col 75 of the raw .dat file"
        )
        lay_ov.addRow("Temperature °C (fallback):", self.spin_temp)

        self.spin_pres = QDoubleSpinBox()
        self.spin_pres.setRange(500.0, 1500.0)
        self.spin_pres.setValue(1013.25)
        self.spin_pres.setToolTip(
            "Fallback pressure (mbar) — used only when HK data is unavailable\n"
            "Normally P is read per-scan from col 76 of the raw .dat file"
        )
        lay_ov.addRow("Pressure mbar (fallback):", self.spin_pres)

        grp_ov.setLayout(lay_ov)
        _ov_outer.addWidget(grp_ov)
        control_layout.addWidget(self._manual_override_container)

        def _toggle_override():
            self._manual_override_visible = not self._manual_override_visible
            self._manual_override_container.setVisible(self._manual_override_visible)
            self._btn_toggle_override.setText(
                "▼  Manual Override  (I₀, R, flags, T/P fallback)"
                if self._manual_override_visible else
                "▶  Manual Override  (I₀, R, flags, T/P fallback)")
        self._btn_toggle_override.clicked.connect(_toggle_override)

        # Group 2b: Detector Corrections (collapsible — rarely needed in daily ops)
        self._det_corr_visible = False
        self._btn_toggle_det = QPushButton("▶  Detector Corrections (dark / offset / stray light)")
        self._btn_toggle_det.setStyleSheet(
            "text-align: left; color: #546E7A; "
            "border: 1px solid #E0E0E0; padding: 3px 8px;")
        control_layout.addWidget(self._btn_toggle_det)

        self._det_corr_container = QWidget()
        self._det_corr_container.setVisible(False)
        _det_outer = QVBoxLayout(self._det_corr_container)
        _det_outer.setContentsMargins(0, 0, 0, 0)

        grp_det = QGroupBox("3b. Detector Corrections")
        lay_det = QFormLayout()

        # Dark Current Setup
        self.lbl_dark_path = QLabel("Not loaded")
        self.lbl_dark_path.setStyleSheet("color: gray;")
        btn_browse_dark = QPushButton("Browse Dark")
        btn_browse_dark.clicked.connect(self.browse_dark_file)
        self.spin_dark_scale = QDoubleSpinBox()
        self.spin_dark_scale.setRange(0.0, 1000.0)
        self.spin_dark_scale.setValue(1.0)
        self.spin_dark_scale.setDecimals(4)
        self.spin_dark_scale.setSingleStep(0.01)
        self.spin_dark_scale.setFixedWidth(int(75 * self._s))
        self.spin_dark_scale.setToolTip("t_meas / t_dark  (1.0 = same integration time as measurement)")

        lay_dark = QHBoxLayout()
        lay_dark.addWidget(self.lbl_dark_path)
        lay_dark.addWidget(btn_browse_dark)
        lay_dark.addWidget(QLabel("×"))
        lay_dark.addWidget(self.spin_dark_scale)
        lay_det.addRow("Dark Current:", lay_dark)

        # Detector Offset Setup
        self.lbl_offset_path = QLabel("Not loaded")
        self.lbl_offset_path.setStyleSheet("color: gray;")
        btn_browse_offset = QPushButton("Browse Offset")
        btn_browse_offset.clicked.connect(self.browse_offset_file)
        self.spin_offset_scale = QDoubleSpinBox()
        self.spin_offset_scale.setRange(0.0, 1000.0)
        self.spin_offset_scale.setValue(1.0)
        self.spin_offset_scale.setDecimals(4)
        self.spin_offset_scale.setSingleStep(0.01)
        self.spin_offset_scale.setFixedWidth(int(75 * self._s))
        self.spin_offset_scale.setToolTip("n_meas / n_offset  (scan count ratio; 1.0 = same number of scans)")

        lay_offset = QHBoxLayout()
        lay_offset.addWidget(self.lbl_offset_path)
        lay_offset.addWidget(btn_browse_offset)
        lay_offset.addWidget(QLabel("×"))
        lay_offset.addWidget(self.spin_offset_scale)
        lay_det.addRow("Det. Offset:", lay_offset)

        # Stray Light Correction
        self.spin_stray_light = QDoubleSpinBox()
        self.spin_stray_light.setRange(0.0, 0.10)
        self.spin_stray_light.setValue(0.0)
        self.spin_stray_light.setDecimals(4)
        self.spin_stray_light.setSingleStep(0.001)
        self.spin_stray_light.setToolTip(
            "Stray light fraction ε  (Platt & Stutz 2008)\n"
            "I_corr = (I − ε·mean(I)) / (1 − ε)\n"
            "Typical UV: 0.001–0.01  |  0.0 = disabled"
        )
        lay_det.addRow("Stray Light ε:", self.spin_stray_light)

        grp_det.setLayout(lay_det)
        _det_outer.addWidget(grp_det)
        control_layout.addWidget(self._det_corr_container)

        def _toggle_det():
            self._det_corr_visible = not self._det_corr_visible
            self._det_corr_container.setVisible(self._det_corr_visible)
            self._btn_toggle_det.setText(
                "▼  Detector Corrections (dark / offset / stray light)"
                if self._det_corr_visible else
                "▶  Detector Corrections (dark / offset / stray light)")
        self._btn_toggle_det.clicked.connect(_toggle_det)

        control_layout.addStretch(1)
        main_layout.addLayout(control_layout, stretch=1)
        
        # --- Right Panel: Diagnostic Viewer ---
        viewer_layout = QVBoxLayout()
        grp_viewer = QGroupBox("Cavity Diagnostics")
        lay_v = QVBoxLayout()
        lay_v.setContentsMargins(4, 4, 4, 4)

        self._diag_tabs = QTabWidget()

        # ── Tab 0: I0 & R(λ) spectral viewer ────────────────────────────────
        tab_spectral = QWidget()
        lay_spectral = QVBoxLayout(tab_spectral)
        lay_spectral.setContentsMargins(0, 0, 0, 0)

        self.plot_diagnostic = pg.PlotWidget(title="I0 & R(λ) 스펙트럼")
        self.plot_diagnostic.showGrid(x=True, y=True, alpha=0.3)
        self.plot_diagnostic.setLabel('left', 'Intensity (I0)', color='k')
        self.plot_diagnostic.setLabel('bottom', 'Pixel / Wavelength')

        self.p1 = self.plot_diagnostic.plotItem
        self.p2 = pg.ViewBox()
        self.p1.showAxis('right')
        self.p1.scene().addItem(self.p2)
        self.p1.getAxis('right').linkToView(self.p2)
        self.p2.setXLink(self.p1)
        self.p1.getAxis('right').setLabel('Reflectivity (R)', color='b')

        def updateViews():
            self.p2.setGeometry(self.p1.vb.sceneBoundingRect())
            self.p2.linkedViewChanged(self.p1.vb, self.p2.XAxis)

        updateViews()
        self.p1.vb.sigResized.connect(updateViews)

        lay_spectral.addWidget(self.plot_diagnostic)
        self._diag_tabs.addTab(tab_spectral, "📊 R(λ) 스펙트럼")

        # ── Tab 1: R(t) + Leff(t) time-series from R Trend Monitor ──────────
        tab_trend = QWidget()
        lay_trend = QVBoxLayout(tab_trend)
        lay_trend.setContentsMargins(0, 0, 0, 0)
        lay_trend.setSpacing(2)

        _ts_ax_r = pg.DateAxisItem(orientation='bottom')
        self._setup_r_trend_pw = pg.PlotWidget()
        self._setup_r_trend_pw.setAxisItems({'bottom': _ts_ax_r})
        self._setup_r_trend_pw.setLabel('left', 'R (%)')
        self._setup_r_trend_pw.showGrid(x=True, y=True, alpha=0.3)
        self._setup_r_trend_pw.setTitle("R 시계열 (R Trend Monitor 실행 후 표시)")

        _ts_ax_l = pg.DateAxisItem(orientation='bottom')
        self._setup_leff_pw = pg.PlotWidget()
        self._setup_leff_pw.setAxisItems({'bottom': _ts_ax_l})
        self._setup_leff_pw.setLabel('left', 'Leff (km)')
        self._setup_leff_pw.showGrid(x=True, y=True, alpha=0.3)
        self._setup_leff_pw.setTitle("Leff 시계열")

        lay_trend.addWidget(self._setup_r_trend_pw, stretch=1)
        lay_trend.addWidget(self._setup_leff_pw, stretch=1)
        self._diag_tabs.addTab(tab_trend, "📈 R/Leff 시계열")

        # ── Tab 2: FWHM Best-Match (validate sweep refs against measured α) ──
        from matplotlib.figure import Figure as _FwhmFigure
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as _FwhmCanvas

        tab_fwhm = QWidget()
        lay_fwhm = QVBoxLayout(tab_fwhm)
        lay_fwhm.setContentsMargins(4, 4, 4, 4)
        lay_fwhm.setSpacing(4)

        ctl = QGroupBox("Sweep folder + α source")
        ctl_lay = QFormLayout(ctl)

        self._fwhm_sweep_folder = None
        self._fwhm_alpha_file_path = None
        self._fwhm_best_ref_path = None
        self._fwhm_last_scores = None

        btn_pick_folder = QPushButton("📁 Sweep Folder…")
        btn_pick_folder.clicked.connect(self._fwhm_pick_sweep_folder)
        self.lbl_fwhm_folder = QLabel("Not selected")
        self.lbl_fwhm_folder.setStyleSheet("color: #d32f2f;")
        row_f = QHBoxLayout()
        row_f.addWidget(btn_pick_folder)
        row_f.addWidget(self.lbl_fwhm_folder, stretch=1)
        ctl_lay.addRow("Folder:", row_f)

        self.rb_fwhm_alpha_engine = QRadioButton("Engine α (auto — latest *_alpha_trace.dat)")
        self.rb_fwhm_alpha_file   = QRadioButton("Load from file")
        self.rb_fwhm_alpha_engine.setChecked(True)
        row_a1 = QHBoxLayout()
        row_a1.addWidget(self.rb_fwhm_alpha_engine)
        row_a1.addWidget(self.rb_fwhm_alpha_file)
        ctl_lay.addRow("α source:", row_a1)

        btn_pick_alpha = QPushButton("📂 Pick α file…")
        btn_pick_alpha.clicked.connect(self._fwhm_pick_alpha_file)
        self.lbl_fwhm_alpha = QLabel("(auto from alpha_save_dir)")
        self.lbl_fwhm_alpha.setStyleSheet("color: #555;")
        row_a2 = QHBoxLayout()
        row_a2.addWidget(btn_pick_alpha)
        row_a2.addWidget(self.lbl_fwhm_alpha, stretch=1)
        ctl_lay.addRow("α file:", row_a2)

        row_btn = QHBoxLayout()
        self.btn_fwhm_run = QPushButton("🌀 Run Validation")
        self.btn_fwhm_run.setStyleSheet("font-weight: bold;")
        self.btn_fwhm_run.clicked.connect(self._fwhm_run_validation)
        self.btn_fwhm_set_active = QPushButton("✅ Set best as active NO2 ref")
        self.btn_fwhm_set_active.setEnabled(False)
        self.btn_fwhm_set_active.clicked.connect(self._fwhm_set_active_ref)
        row_btn.addWidget(self.btn_fwhm_run)
        row_btn.addWidget(self.btn_fwhm_set_active)
        ctl_lay.addRow(row_btn)

        self.lbl_fwhm_best = QLabel("")
        self.lbl_fwhm_best.setStyleSheet("color: #2E7D32; font-weight: bold;")
        self.lbl_fwhm_best.setWordWrap(True)
        ctl_lay.addRow(self.lbl_fwhm_best)

        lay_fwhm.addWidget(ctl)

        self._fwhm_fig    = _FwhmFigure(figsize=(5, 3), tight_layout=True)
        self._fwhm_ax     = self._fwhm_fig.add_subplot(111)
        self._fwhm_canvas = _FwhmCanvas(self._fwhm_fig)
        lay_fwhm.addWidget(self._fwhm_canvas, stretch=1)

        self._diag_tabs.addTab(tab_fwhm, "🎯 FWHM Best-Match")

        lay_v.addWidget(self._diag_tabs)
        grp_viewer.setLayout(lay_v)
        viewer_layout.addWidget(grp_viewer)

        main_layout.addLayout(viewer_layout, stretch=2)

    # ── FWHM Best-Match (Setup tab Tab 2) ──────────────────────────────
    def _fwhm_pick_sweep_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose FWHM sweep folder", self._dlg_dir('fwhm'))
        self._dlg_dir('fwhm', d)
        if not d:
            return
        self._fwhm_sweep_folder = d
        import glob
        n = len(glob.glob(os.path.join(d, "Ref_*_FWHM*nm.dat")))
        self.lbl_fwhm_folder.setText(f"✅ {d}  ({n} sweep refs)")
        self.lbl_fwhm_folder.setStyleSheet("color: #2E7D32; font-weight: bold;")

    def _fwhm_pick_alpha_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Pick α file", self._dlg_dir('fwhm_alpha'),
            "Data Files (*.dat *.txt *.csv);;All Files (*)"
        )
        self._dlg_dir('fwhm_alpha', f)
        if not f:
            return
        self._fwhm_alpha_file_path = f
        self.rb_fwhm_alpha_file.setChecked(True)
        self.lbl_fwhm_alpha.setText(f"✅ {os.path.basename(f)}")
        self.lbl_fwhm_alpha.setStyleSheet("color: #2E7D32; font-weight: bold;")

    def _fwhm_auto_find_latest_alpha(self):
        """Find newest *_alpha_trace.dat in self.alpha_save_dir (if set)."""
        import glob
        base = getattr(self, "alpha_save_dir", None)
        if not base or not os.path.isdir(base):
            return None
        cands = glob.glob(os.path.join(base, "*_alpha_trace.dat"))
        if not cands:
            return None
        cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return cands[0]

    def _fwhm_load_alpha(self, path):
        """Return (wavelength_nm, alpha) arrays.

        Two file formats are supported:

        1. ``wavelength_nm  alpha``  two-column text (our generator output).
        2. Single column = α only — 박사님 format (one α value per line,
           blank-line separated, no wavelength axis). In this case the
           wavelength axis is taken from the main calibration
           (``self.wavelengths``) so the polynomial baseline fit uses
           real nm, not pixel indices.
        """
        df = pd.read_csv(path, sep=r'\s+', header=None, comment='#', engine='python')
        if df.shape[1] >= 2:
            wl  = pd.to_numeric(df.iloc[:, 0], errors='coerce').to_numpy()
            val = pd.to_numeric(df.iloc[:, 1], errors='coerce').to_numpy()
        else:
            # Strip blank-line NaNs before assigning a wavelength axis
            val = pd.to_numeric(df.iloc[:, 0], errors='coerce').to_numpy()
            val = val[np.isfinite(val)]
            if hasattr(self, 'wavelengths') and self.wavelengths is not None:
                wl_full = np.asarray(self.wavelengths, dtype=float).flatten()
                n = min(len(wl_full), len(val))
                wl  = wl_full[:n]
                val = val[:n]
            else:
                wl = np.arange(len(val), dtype=float)
        ok = np.isfinite(wl) & np.isfinite(val)
        if ok.sum() < 50:
            raise ValueError("Too few valid (wavelength, alpha) rows. "
                             "If this is 박사님 single-column α format, load "
                             "the wavelength calibration in the main window first.")
        return wl[ok], val[ok]

    def _fwhm_parse_fwhm_from_name(self, fname):
        import re
        m = re.search(r"FWHM([0-9.]+)nm", fname)
        return float(m.group(1)) if m else None

    def _fwhm_run_validation(self):
        import glob
        from scipy.interpolate import interp1d

        if not self._fwhm_sweep_folder:
            QMessageBox.warning(self, "FWHM Best-Match", "Pick a sweep folder first.")
            return

        ref_files = sorted(glob.glob(
            os.path.join(self._fwhm_sweep_folder, "Ref_*_FWHM*nm.dat")
        ))
        if not ref_files:
            QMessageBox.warning(self, "FWHM Best-Match",
                "No Ref_*_FWHM*nm.dat files found in the selected folder.")
            return

        if self.rb_fwhm_alpha_file.isChecked():
            alpha_path = self._fwhm_alpha_file_path
            if not alpha_path:
                QMessageBox.warning(self, "FWHM Best-Match",
                    "α source = file, but no file picked.")
                return
        else:
            alpha_path = self._fwhm_auto_find_latest_alpha()
            if not alpha_path:
                QMessageBox.warning(self, "FWHM Best-Match",
                    "No *_alpha_trace.dat found in alpha_save_dir.\n"
                    "Run alpha export first, or pick a file manually.")
                return

        try:
            wl_a, a = self._fwhm_load_alpha(alpha_path)
        except Exception as e:
            QMessageBox.critical(self, "FWHM Best-Match", f"α load failed:\n{e}")
            return

        # Each ref file is one column of cross-section values on the ref's
        # native wavelength grid. We need a wavelength axis for the ref. We
        # interpolate α onto ref pixel index here only as a fallback; the
        # preferred path is when ref length == len(wl_a) (target grid match).
        scores = {}
        for fpath in ref_files:
            fname = os.path.basename(fpath)
            fv = self._fwhm_parse_fwhm_from_name(fname)
            if fv is None:
                continue
            try:
                ref_vals = np.loadtxt(fpath, comments="#")
            except Exception:
                continue
            ref_vals = np.asarray(ref_vals).flatten()
            # Align by length: assume ref was generated on the same target
            # wavelength grid as the α file (both come from the calibration).
            n = min(len(ref_vals), len(a))
            if n < 50:
                continue
            r_fit = ref_vals[:n]
            a_fit = a[:n]
            wl_fit = wl_a[:n]
            # Normalized polynomial basis to avoid ill-conditioning
            wn = (wl_fit - wl_fit.mean()) / max(1e-9, wl_fit.std())
            # ── Numerical conditioning ───────────────────────────────────
            # Raw cross-sections are O(1e-19) while the polynomial basis is
            # O(1). With lstsq's default rcond the ref column's singular
            # value (~1e-18) falls below the truncation threshold and the
            # column is silently dropped → c_ref ≈ 0 and residual_RMS is
            # constant across every FWHM (verified on Dr.Nam's α + our
            # sweep, May 2026). Two complementary fixes:
            #   · rescale the ref column to std=1 (caller can recover the
            #     real concentration via coef[0] / ref_scale if needed)
            #   · pass rcond=1e-30 to suppress any further truncation
            ref_scale = max(float(np.std(r_fit)), 1e-30)
            r_norm = (r_fit - float(np.mean(r_fit))) / ref_scale
            A = np.column_stack([r_norm, np.ones_like(wn), wn, wn**2, wn**3])
            coef, *_ = np.linalg.lstsq(A, a_fit, rcond=1e-30)
            resid = a_fit - A @ coef
            scores[fv] = (float(np.sqrt(np.mean(resid**2))), fpath)

        if not scores:
            QMessageBox.warning(self, "FWHM Best-Match",
                "Could not score any ref file (length mismatch with α?).")
            return

        best_fv = min(scores, key=lambda k: scores[k][0])
        best_rms, best_path = scores[best_fv]
        self._fwhm_best_ref_path = best_path
        self._fwhm_last_scores   = scores

        # Plot
        self._fwhm_ax.clear()
        fvs  = np.array(sorted(scores.keys()))
        rms  = np.array([scores[v][0] for v in fvs])
        self._fwhm_ax.plot(fvs, rms, 'o-', color='#6a1b9a')
        self._fwhm_ax.axvline(best_fv, color='red', ls='--',
                              label=f"best = {best_fv:.3f} nm")
        self._fwhm_ax.set_xlabel("FWHM (nm)")
        self._fwhm_ax.set_ylabel("RMS residual")
        self._fwhm_ax.set_title(f"FWHM Best-Match — α: {os.path.basename(alpha_path)}")
        self._fwhm_ax.legend()
        self._fwhm_canvas.draw()

        self.lbl_fwhm_best.setText(
            f"🏆 Best FWHM = {best_fv:.3f} nm  (RMS = {best_rms:.3e})\n"
            f"   → {os.path.basename(best_path)}"
        )
        self.btn_fwhm_set_active.setEnabled(True)

    def _fwhm_set_active_ref(self):
        if not self._fwhm_best_ref_path:
            QMessageBox.warning(self, "FWHM Best-Match", "Run validation first.")
            return
        try:
            # Mirror the Reference-Generator save path: register the file with
            # both the engine *and* the visible reference table on the left.
            try:
                self.add_ref_row(name="NO2", path=self._fwhm_best_ref_path)
            except Exception:
                # Fallback path: engine-only registration (no table row).
                ok, msg = self.engine.add_reference("NO2", self._fwhm_best_ref_path)
                if not ok:
                    QMessageBox.warning(self, "FWHM Best-Match",
                                        f"Engine refused the reference:\n{msg}")
                    return
            QMessageBox.information(
                self, "FWHM Best-Match",
                f"Registered NO2 reference (engine + table):\n"
                f"{os.path.basename(self._fwhm_best_ref_path)}"
            )
        except Exception as e:
            QMessageBox.critical(self, "FWHM Best-Match",
                                 f"Failed to register reference:\n{e}")

    def browse_i0_file(self):
        """Browse and set the I0 (Zero-air) measurement file."""
        filepath, _ = QFileDialog.getOpenFileName(self, "Select I0 File", self._dlg_dir('i0'), "Data Files (*.dat *.txt *.csv)")
        self._dlg_dir('i0', filepath)
        if filepath:
            self.set_i0_path(filepath)

    def browse_dark_file(self):
        """Browse and load a dark current spectrum (.dat/.txt/.csv 또는 MATLAB .mat)."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select Dark Spectrum", self._dlg_dir('dark'),
            "Data Files (*.dat *.txt *.csv *.mat);;All Files (*)")
        if not filepath:
            return
        self._dlg_dir('dark', filepath)
        try:
            import numpy as np
            if filepath.lower().endswith(".mat"):
                import scipy.io
                mat = scipy.io.loadmat(filepath)
                # MATLAB 구조체: Dark_240224.ch1
                struct_keys = [k for k in mat.keys() if not k.startswith('_')]
                if not struct_keys:
                    raise ValueError("mat 파일에 데이터 키가 없습니다.")
                struct_key = struct_keys[0]
                struct = mat[struct_key]
                ch_key = "ch1"
                if hasattr(struct, 'dtype') and ch_key in struct.dtype.names:
                    dark_raw = np.asarray(struct[ch_key][0, 0], dtype=float).flatten()
                else:
                    dark_raw = np.asarray(struct, dtype=float).flatten()
            else:
                _, dark_raw = DataIO.load_measurement(filepath, pixel_min=0)
            self.dark_data = dark_raw
            self.lbl_dark_path.setText(os.path.basename(filepath))
            self.lbl_dark_path.setStyleSheet("color: green; font-weight: bold;")
            self.status.setText(
                f"Dark current loaded: {os.path.basename(filepath)}  "
                f"({len(dark_raw)} px, mean={dark_raw.mean():.1f})"
            )
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Failed to load dark file:\n{e}")

    def browse_offset_file(self):
        """Browse and load a detector offset spectrum (ADC pedestal, integration-time independent)."""
        filepath, _ = QFileDialog.getOpenFileName(self, "Select Offset Spectrum", self._dlg_dir('offset'), "Data Files (*.dat *.txt *.csv)")
        self._dlg_dir('offset', filepath)
        if not filepath:
            return
        try:
            _, offset_raw = DataIO.load_measurement(filepath, pixel_min=0)
            self.offset_data = offset_raw
            self.lbl_offset_path.setText(os.path.basename(filepath))
            self.lbl_offset_path.setStyleSheet("color: green; font-weight: bold;")
            self.status.setText(f"Detector offset loaded: {os.path.basename(filepath)}")
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Failed to load offset file:\n{e}")

    def _parse_flags(self, text):
        """'500, 503' → [500, 503]. Returns list of ints; falls back to [] on parse error."""
        try:
            return [int(v.strip()) for v in text.split(',') if v.strip()]
        except ValueError:
            return []

    def browse_alpha_save_dir(self):
        """Browse and set the output directory for intermediate alpha spectra."""
        d = QFileDialog.getExistingDirectory(self, "Alpha 중간 저장 폴더 선택", self._dlg_dir('alpha_save'))
        self._dlg_dir('alpha_save', d)
        if d:
            self.alpha_save_dir = d
            self.lbl_alpha_dir.setText(os.path.basename(d) or d)
            self.lbl_alpha_dir.setStyleSheet("color: #1565C0; font-weight: bold;")

    def export_alpha_files(self):
        """피팅 없이 BBCEAS alpha만 계산해 저장. Hot 2채널이면 채널별로 각각 저장."""
        if not hasattr(self, 'file_list') or not self.file_list:
            QMessageBox.warning(self, "No Files", "먼저 측정 파일을 로드하세요.")
            return
        if getattr(self, 'wavelengths', None) is None and self.engine._wave_axis is None:
            QMessageBox.warning(self, "No Wavelength Cal",
                                "파장 캘리브레이션 파일을 먼저 로드하세요.")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Alpha 파일 저장 폴더 선택", self._dlg_dir('alpha_out'))
        self._dlg_dir('alpha_out', out_dir)
        if not out_dir:
            return

        n_ch = int(getattr(self, '_detected_channels', 1) or 1)
        configs = self._build_alpha_channel_configs(n_ch)
        if not configs:
            QMessageBox.warning(self, "채널 설정 실패",
                                "채널별 파장보정/픽셀 범위를 만들 수 없습니다.\n"
                                f"Hot(≥2ch)은 {self._WV_CAL_BASE}\\roi1,roi2 의 Calib 파일이 필요합니다.")
            return

        # 채널별 워커를 순차 실행(큐). Hot=2채널 → PNs, ANs 각각 생성.
        self._alpha_queue     = list(configs)
        self._alpha_out_dir   = out_dir
        self._alpha_dark      = getattr(self, 'dark_data', None)
        self._alpha_done_msgs = []
        self.status.setText(f"📁 Alpha 내보내기 시작 ({n_ch}채널)...")
        self._start_next_alpha_export()

    # wv_cal 자동탐색 베이스 (채널별 파장보정 — 사용자 지정 위치)
    _WV_CAL_BASE = r"C:\Doasis_Work\Output\wv_cal"

    def _channel_wave_cal(self, n_ch, ch):
        """채널 → per-pixel 파장 배열. 1ch=로드된 cal, ≥2ch=Output\\wv_cal\\{roi1,roi2,..} 최신 Calib."""
        if n_ch == 1:
            wl = getattr(self, 'wavelengths', None)
            return np.asarray(wl, dtype=float).flatten() if wl is not None else None
        roi = {1: 'roi1', 2: 'roi2', 3: 'roi3'}.get(ch)
        if roi:
            import glob
            d = os.path.join(self._WV_CAL_BASE, roi)
            cands = sorted(glob.glob(os.path.join(d, 'Calib_*.txt'))) if os.path.isdir(d) else []
            if cands:
                try:
                    return np.loadtxt(cands[-1]).flatten()
                except Exception:
                    pass
        wl = getattr(self, 'wavelengths', None)   # 폴백: 로드된 단일 cal
        return np.asarray(wl, dtype=float).flatten() if wl is not None else None

    def _fit_nm_for_channel(self, ch):
        """채널별 Fit 범위(nm). CH1/단일 = 메인 스핀, CH2/CH3 = 전용 행(노출 시).
        반환은 항상 (lo, hi) 정렬."""
        n_active = int(getattr(self, '_detected_channels', 1) or 1)
        if ch in getattr(self, '_ch_fit_nm', {}) and ch <= n_active:
            s, e = self._ch_fit_nm[ch]
            lo, hi = s.value(), e.value()
        else:
            lo, hi = self.spin_fit_start_nm.value(), self.spin_fit_end_nm.value()
        return (lo, hi) if lo <= hi else (hi, lo)

    def _build_alpha_channel_configs(self, n_ch):
        """채널마다 (채널idx, 라벨, 파장슬라이스, pixel_min/max) — 채널별 nm 핏레인지를 채널 cal로 변환."""
        label_for = {1: 'Cold'} if n_ch == 1 else {1: 'PNs', 2: 'ANs', 3: 'CH3'}
        configs = []
        for ch in range(1, n_ch + 1):
            wave_full = self._channel_wave_cal(n_ch, ch)
            if wave_full is None or len(wave_full) == 0:
                continue
            start_nm, end_nm = self._fit_nm_for_channel(ch)
            pmin = int(np.abs(wave_full - start_nm).argmin())
            pmax = int(np.abs(wave_full - end_nm).argmin())
            if pmin > pmax:
                pmin, pmax = pmax, pmin
            if pmax <= pmin:
                pmax = pmin + 1
            configs.append(dict(channel=ch, label=label_for.get(ch, f'CH{ch}'),
                                wave_nm=wave_full[pmin:pmax],
                                pixel_min=pmin, pixel_max=pmax))
        return configs

    def _start_next_alpha_export(self):
        if not getattr(self, '_alpha_queue', None):
            done = getattr(self, '_alpha_done_msgs', [])
            self.status.setText(f"✅ Alpha 내보내기 완료 → {self._alpha_out_dir}")
            QMessageBox.information(
                self, "Alpha Export 완료",
                "채널별 α 저장 완료:\n" + "\n".join(done) +
                f"\n\n저장 위치:\n{self._alpha_out_dir}\n"
                "파일명: {소스}_{채널}_alpha_trace.dat\n"
                "결과 뷰어 / 2단계 피팅에 사용 가능.")
            return
        cfg = self._alpha_queue.pop(0)
        self.status.setText(
            f"📁 Alpha [{cfg['label']}] 계산 중 (px {cfg['pixel_min']}~{cfg['pixel_max']})...")
        self._alpha_export_worker = AlphaExportWorker(
            file_list     = self.file_list,
            pixel_min     = cfg['pixel_min'],
            pixel_max     = cfg['pixel_max'],
            wave_nm       = cfg['wave_nm'],
            flag_za       = self._parse_flags(self.txt_flag_za.text()),
            flag_he       = self._parse_flags(self.txt_flag_he.text()),
            flag_amb      = self._parse_flags(self.txt_flag_amb.text()),
            rl_factor     = self.spin_rl_factor.value(),
            cavity_len    = self.spin_d_len.value(),
            output_dir    = self._alpha_out_dir,
            dark_spectrum = self._alpha_dark,
            channel       = cfg['channel'],
            avg_sec       = self.spin_alpha_avgsec.value(),
            channel_label = cfg['label'],
        )
        self._alpha_export_worker.progress.connect(
            lambda n, lbl=cfg['label']: self.status.setText(f"📁 [{lbl}] {n} 스캔..."))
        self._alpha_export_worker.status_msg.connect(lambda m: print(f"[AlphaExport] {m}"))
        self._alpha_export_worker.finished.connect(
            lambda res, lbl=cfg['label']: self._on_alpha_channel_done(res, lbl))
        self._alpha_export_worker.start()

    def _on_alpha_channel_done(self, result, label):
        if str(result).startswith("ERROR"):
            self._alpha_done_msgs.append(f"  [{label}] 실패: {result}")
            self.status.setText(f"❌ Alpha [{label}] 실패")
        else:
            self._alpha_done_msgs.append(f"  [{label}] ✅")
        self._start_next_alpha_export()

    def run_alpha_fit(self):
        """저장된 alpha_trace.dat 파일을 선택해서 DOAS 피팅을 실행한다."""
        if not hasattr(self.engine, 'gas_list') or not self.engine.gas_list:
            QMessageBox.warning(self, "레퍼런스 없음",
                                "먼저 레퍼런스 스펙트럼을 로드하세요.")
            return

        alpha_files, _ = QFileDialog.getOpenFileNames(
            self, "Alpha Trace 파일 선택", self._dlg_dir('alpha_fit'),
            "Alpha Trace (*.dat);;All Files (*)"
        )
        if not alpha_files:
            return
        self._dlg_dir('alpha_fit', alpha_files[0])

        output_dir = QFileDialog.getExistingDirectory(
            self, "결과 저장 폴더 선택",
            os.path.dirname(alpha_files[0])
        )
        if not output_dir:
            return

        poly_deg = self.spin_poly_deg.value()

        try:
            pixel_min = int(self.txt_min.text())
        except (AttributeError, ValueError):
            pixel_min = 0

        try:
            pixel_max = int(self.txt_max.text())
        except (AttributeError, ValueError):
            pixel_max = None

        self._alpha_fit_worker = AlphaFitWorker(
            alpha_files=alpha_files,
            engine=self.engine,
            poly_deg=poly_deg,
            output_dir=output_dir,
            pixel_min=pixel_min,
            pixel_max=pixel_max,
            # raw 핏과 동일한 VarPro 설정 전달 → raw↔alpha 일치
            ref_properties=getattr(self, 'ref_props', None),
            step_limit=self.spin_step_limit.value() if hasattr(self, 'spin_step_limit') else 0.5,
            tikhonov_lambda=self.spin_lambda.value() if hasattr(self, 'spin_lambda') else 0.0,
            use_robust=self.chk_robust.isChecked() if hasattr(self, 'chk_robust') else False,
        )
        self._alpha_fit_worker.progress.connect(
            lambda n: self.status.setText(f"📊 Alpha 피팅: {n}행 처리 중...")
        )
        self._alpha_fit_worker.status_msg.connect(
            lambda msg: print(f"[AlphaFit] {msg}")
        )
        self._alpha_fit_worker.finished.connect(self._on_alpha_fit_done)
        self._alpha_fit_worker.start()
        self.status.setText("📊 Alpha 피팅 시작...")

    def _on_alpha_fit_done(self, result):
        if result.startswith("ERROR"):
            QMessageBox.warning(self, "Alpha 피팅 실패", result)
            self.status.setText("Alpha 피팅 실패")
        else:
            QMessageBox.information(
                self, "Alpha 피팅 완료",
                f"DOAS 피팅 결과 저장 완료!\n\n저장 위치:\n{result}\n\n"
                f"각 파일: {{소스파일명}}_fit.tsv\n"
                f"형식: row_idx / T / P / 가스별 ppb / rms"
            )
            self.status.setText(f"Alpha 피팅 완료 -> {result}")

    def auto_extract_i0(self):
        """Scans the loaded file list for ZA-flagged files and averages them to form I0."""
        if not hasattr(self, 'file_list') or not self.file_list:
            QMessageBox.warning(self, "No Files", "Load a measurement file list first.")
            return

        flag_za_list = self._parse_flags(self.txt_flag_za.text()) if hasattr(self, 'txt_flag_za') else [500, 501, 502, 503]
        # I₀ 추출: 500(injecting)만 사용
        za_meas_flag = 500 if 500 in flag_za_list else flag_za_list[0] if flag_za_list else 500
        za_spectra = []
        for entry in self.file_list:
            fp = self._entry_filepath(entry)
            ri = self._entry_row_index(entry)
            try:
                _, raw, flag, _, _ = DataIO.load_measurement_with_hk(fp, pixel_min=0, row_index=ri)
                if flag == za_meas_flag and len(raw) > 0:
                    za_spectra.append(raw)
            except Exception:
                pass

        if not za_spectra:
            QMessageBox.information(self, "Not Found", "No ZA-flagged scans found in the current file list.")
            return

        # Trim to common length and average
        min_len = min(len(s) for s in za_spectra)
        i0_avg = np.mean([s[:min_len] for s in za_spectra], axis=0)
        self.i0_data = i0_avg
        self.lbl_i0_path.setText(f"Auto ({len(za_spectra)} ZA scans averaged)")
        self.lbl_i0_path.setStyleSheet("color: blue; font-weight: bold;")
        self.status.setText(f"Auto I0: averaged {len(za_spectra)} ZA scans.")
        self.update_diagnostic_plot()
        self._refresh_setup_status()

    def update_leff(self):
        """Recalculates and displays L_eff = d / (1 - R_mean) whenever R or d changes."""
        if not hasattr(self, 'r_data') or self.r_data is None:
            self.lbl_leff.setText("L_eff: — (load R-curve first)")
            return
        d = self.spin_d_len.value()
        r_mean = np.mean(self.r_data)
        r_min  = np.min(self.r_data)
        r_max  = np.max(self.r_data)
        leff_mean = d / (1.0 - r_mean)
        leff_min  = d / (1.0 - r_max)   # higher R → longer path
        leff_max  = d / (1.0 - r_min)
        self.lbl_leff.setText(
            f"L_eff ≈ {leff_mean:,.0f} cm  "
            f"(range {leff_min:,.0f} – {leff_max:,.0f} cm,  R̄ = {r_mean:.6f})"
        )

    def browse_r_file(self):
        """Browse and set the Reflectivity (R-Curve) file."""
        filepath, _ = QFileDialog.getOpenFileName(self, "Select R-Curve File", self._dlg_dir('rcurve'), "Data Files (*.dat *.txt *.csv)")
        self._dlg_dir('rcurve', filepath)
        if filepath:
            self.lbl_r_path.setText(os.path.basename(filepath))
            self.lbl_r_path.setStyleSheet("color: blue; font-weight: bold;")
            
            # 🌟 Load R data and plot
            try:
                # Load logic for a standard R-Curve file (2-column data)
                df = pd.read_csv(filepath, sep=None, engine='python', header=None, comment='#')
                # Assumes column 1 is wavelength/pixel, column 2 is R value
                r_y = pd.to_numeric(df.iloc[:, -1], errors='coerce').dropna().values
                self.r_data = r_y
                self.update_diagnostic_plot()
                self.update_leff()
            except Exception as e:
                print(f"Error loading R file: {e}")
                QMessageBox.warning(self, "Load Error", "Failed to parse Reflectivity (R) file.")
            self._refresh_setup_status()

    def show_table_context_menu(self, pos):
        """Shows context menu on the measurement table."""
        row = self.table.rowAt(pos)
        if row < 0:
            return
            
        menu = QMenu()
        action_i0 = menu.addAction("🎯 Set as I0 (Zero-Air)")
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        
        if action == action_i0:
            self.set_i0_from_table(row)

    def set_i0_from_table(self, row):
        """Extracts the filepath from the table row and sets it as I0."""
        fname = self.table.item(row, 0).text()
        entry = self._entry_from_display_name(fname)
        filepath = self._entry_filepath(entry) if entry else None

        if filepath:
            self.set_i0_path(filepath)
            self.main_tabs.setCurrentIndex(1)   # switch to Setup tab
            
    def set_i0_path(self, filepath):
        """Updates the I0 state, loads data, and updates UI."""
        self.lbl_i0_path.setText(os.path.basename(filepath))
        self.lbl_i0_path.setStyleSheet("color: blue; font-weight: bold;")
        self.status.setText(f"🎯 I0 set to: {os.path.basename(filepath)}")
        
        # 🌟 Load I0 data and plot
        try:
            # Load I0 file using the same method as the engine (most stable)
            _, intensity_raw = DataIO.load_measurement(filepath, pixel_min=0)
            self.i0_data = intensity_raw
            self.update_diagnostic_plot()
        except Exception as e:
            print(f"Error loading I0 file: {e}")
            QMessageBox.warning(self, "Load Error", "Failed to read I0 measurement file.")
        self._refresh_setup_status()

    def update_diagnostic_plot(self):
        """Draws I0 and R on the diagnostic viewer."""
        self.p1.clear()
        self.p2.clear()
        
        # Apply wavelength (nm) axis if loaded, otherwise use pixel axis
        x_axis = None
        if hasattr(self, 'wavelengths') and self.wavelengths is not None:
            x_axis = np.array(self.wavelengths).flatten()
            self.plot_diagnostic.setLabel('bottom', 'Wavelength (nm)')
        else:
            self.plot_diagnostic.setLabel('bottom', 'Pixel Index')
            
        # 1. Draw I0 as a black line (Left Y-axis)
        if hasattr(self, 'i0_data') and self.i0_data is not None:
            x = x_axis if (x_axis is not None and len(x_axis) == len(self.i0_data)) else np.arange(len(self.i0_data))
            self.p1.plot(x, self.i0_data, pen=pg.mkPen('k', width=1.5), name="I0 (Zero-Air)")
            
        # 2. Draw R as a blue dashed line (Right Y-axis)
        if hasattr(self, 'r_data') and self.r_data is not None:
            x = x_axis if (x_axis is not None and len(x_axis) == len(self.r_data)) else np.arange(len(self.r_data))
            
            curve_r = pg.PlotCurveItem(x, self.r_data, pen=pg.mkPen('b', width=2, style=Qt.PenStyle.DashLine))
            self.p2.addItem(curve_r)

            # Zoom in around the actual R values so ±0.01% changes are visible
            r_arr    = np.asarray(self.r_data, dtype=float)
            r_finite = r_arr[np.isfinite(r_arr)]
            if len(r_finite) > 0:
                r_mean = float(np.mean(r_finite))
                r_std  = float(np.std(r_finite))
                margin = max(r_std * 5.0, 5e-4)   # ≥ ±0.05 % window
                self.p2.setYRange(
                    max(0.0,    r_mean - margin),
                    min(1.0001, r_mean + margin),
                    padding=0,
                )
            else:
                self.p2.autoRange()


    def _on_r_curve_update(self, wave_nm, r_curve):
        """Called by worker whenever a new R-curve is derived from ZA/He pair."""
        self.r_data = np.array(r_curve)
        self._r_auto_derived = True   # mark: this R came from a run, not a manual load
        if wave_nm is not None and len(wave_nm) == len(r_curve):
            self.wavelengths = np.array(wave_nm)
        self.update_diagnostic_plot()
        self.update_leff()
        self._refresh_setup_status()

    def open_ref_properties(self):
        """Opens the RefPropertiesDialog to configure Shift/Squeeze bounds."""
        if not hasattr(self, 'engine') or len(self.engine.gas_list) == 0:
            QMessageBox.warning(self, "Warning", "Please load and lock references first!")
            return
            
        dialog = RefPropertiesDialog(self, self.engine.gas_list, getattr(self, 'ref_props', {}))
        if dialog.exec():
            self.ref_props = dialog.get_properties()
            print("⚙️ Reference properties successfully saved:", self.ref_props)

    def open_reference_generator(self):
        """Opens the Ultimate Reference Generator, auto-syncing available lamp/wavelength data."""
        wave_data = getattr(self, 'wavelengths', None)
        dialog = ReferenceGeneratorDialog(self, current_wavelengths=wave_data)
        
        lamp_data = getattr(self, 'spectrum', None)
        if lamp_data is not None:
            dialog.auto_load_lamp_data(lamp_data)
            print("✅ [Generator Sync] Lamp data and wavelength axis auto-configured.")
            
        # Assuming add_ref_row exists in the remaining parts of BBCEASAnalyzer
        dialog.reference_saved.connect(self.add_ref_row) 
        dialog.exec()


    def open_r_generator(self):
        """Opens the R-Curve Generator dialog. On success, loads the result directly into r_data."""
        wave_data = getattr(self, 'wavelengths', None)
        dialog = R_GeneratorDialog(self, wavelengths=wave_data)
        if dialog.exec() and hasattr(dialog, 'r_curve_result'):
            self.r_data = dialog.r_curve_result
            self.update_diagnostic_plot()
            self.update_leff()
            self.status.setText(f"✅ R-Curve loaded ({len(self.r_data)} pixels)")
            print(f"✅ R-Curve auto-loaded: {len(self.r_data)} pixels, mean R = {self.r_data.mean():.6f}")

    def open_r_trend_monitor(self):
        """R Trend Monitor: raw .dat 파일 디렉토리를 스캔해 파일별 R 시계열을 계산·저장·플롯."""
        from .ui_dialogs_r import RTrendMonitorDialog
        dialog = RTrendMonitorDialog(self)
        if hasattr(dialog, 'data_ready'):
            dialog.data_ready.connect(self._update_daily_rt_chart)
            dialog.data_ready.connect(self._update_setup_rt_charts)
        dialog.exec()

    def open_wavelength_calibration(self):
        """Opens the interactive Wavelength Calibration tool."""
        dialog = WavelengthCalibrationDialog(self)

        def on_calib_done(data):
            print(f"📡 Signal Received: {len(data)} wavelength points transferred.")

            # 1. Store wavelength data in main memory
            self.wavelengths = data 
            if hasattr(self, 'engine'):
                self.engine.wavelengths = data
                print("✅ [Engine Sync] Wavelength data synced.")

            # 2. Instantly apply to graphs if the method exists
            if hasattr(self, 'apply_new_wavelength'):
                self.apply_new_wavelength(data)
                print("🚀 [Automation] X-axis automatically updated to nm.")

            # 3. Store the lamp spectrum used during calibration for the generator
            if hasattr(dialog, 'spectrum') and dialog.spectrum is not None:
                self.spectrum = dialog.spectrum
                print("✅ [Lamp Sync] Lamp data auto-saved for the reference generator.")

            # 4. Smart UI Update for FWHM Label + auto-fill nm spinbox
            fwhm_text = "✅ Wavelength Updated"
            if hasattr(dialog, 'fwhm_records') and dialog.fwhm_records:
                valid_fwhms = [v['fwhm_nm'] for v in dialog.fwhm_records.values()
                               if v.get('fwhm_nm') is not None]
                if valid_fwhms:
                    avg_fwhm  = float(np.mean(valid_fwhms))
                    avg_sigma = avg_fwhm / 2.3548
                    fwhm_text = (f"💡 FWHM={avg_fwhm:.3f} nm  "
                                 f"σ={avg_sigma:.3f} nm  "
                                 f"({len(valid_fwhms)} peaks)")
                    # Auto-populate the nm spinbox (triggers px conversion)
                    if hasattr(self, 'spin_fwhm_nm'):
                        self.spin_fwhm_nm.blockSignals(True)
                        self.spin_fwhm_nm.setValue(avg_fwhm)
                        self.spin_fwhm_nm.blockSignals(False)
                        # Now compute px using the just-loaded wavelength axis
                        self._update_fwhm_px_from_nm(avg_fwhm)

            target_label = getattr(self, 'lbl_fwhm_display', getattr(self, 'fwhm_label', None))
            if target_label:
                target_label.setText(fwhm_text)
                target_label.setStyleSheet("color: #2E7D32; font-weight: bold;")

            self._refresh_setup_status()

        dialog.calibration_finished.connect(on_calib_done)
        dialog.exec()

    def apply_new_wavelength(self, wl_array):
        """Immediately applies newly calibrated wavelengths to the UI monitor."""
        try:
            self.monitor.set_wavelengths(wl_array)
            self.monitor.refresh_current_plot()
            
            msg = f"✅ Wavelength Updated: {wl_array.min():.2f} ~ {wl_array.max():.2f} nm"
            self.status.setText(msg)
            self.status.setStyleSheet("color: blue; font-weight: bold;")
            
            QMessageBox.information(self, "Applied", "New wavelength calibration applied to the system instantly.")
        except Exception as e:
            QMessageBox.critical(self, "Application Failed", f"Error during auto-apply: {e}")

    # ---------------------------------------------------------
    # Utility and Data Loading Functions
    # ---------------------------------------------------------
    def guess_gas_name(self, filename):
        """
        Attempts to identify the gas species from common substrings in the filename.

        Checks for known species names (NO2, O3, H2O, etc.) in the uppercased filename.
        Falls back to the filename prefix before the first underscore if nothing matches.
        Example: 'NO2_Vandaele_1998.txt' → 'NO2', 'ref_data.dat' → 'ref'.
        """
        fname = filename.upper()
        targets = ["CHOCHO", "GLYOXAL", "NO2", "H2O", "O4", "O3", "HONO", "HCHO"]
        for t in targets: 
            if t in fname: 
                return "CHOCHO" if t == "GLYOXAL" else t
        # Fallback: Extract prefix before the first underscore
        return os.path.basename(filename).split('_')[0]
    
    def load_wavelength_cal(self, auto_path=None):
        """Loads the wavelength calibration file (X-axis in nm)."""
        # If auto_path is provided, bypass the dialog and load directly
        if auto_path and os.path.exists(auto_path):
            filepath = auto_path
            self.loaded_wl_path = filepath # 🌟 Remember path for saving scenarios
        else:
            filepath, _ = QFileDialog.getOpenFileName(self, "Load Wavelengths (nm)", self._dlg_dir('wavecal'), "Text/CSV (*.txt *.csv *.dat)")
            self._dlg_dir('wavecal', filepath)
            if not filepath: return
            self.loaded_wl_path = filepath # 🌟 Remember path for saving scenarios
            
        try:
            try: 
                df = pd.read_csv(filepath, sep=r'\s+', header=None)
            except Exception: 
                df = pd.read_csv(filepath, sep=',', header=None)
                
            wl_data = None
            # Find the first column that contains actual numeric data
            for i in range(df.shape[1]):
                col = pd.to_numeric(df.iloc[:, i], errors='coerce').dropna()
                if len(col) > 10: 
                    wl_data = col.values.flatten()
                    break
                    
            if wl_data is not None:
                self.wavelengths = wl_data
                self.engine.set_wavelength_axis(wl_data)  # register immediately so pixel_to_wavelength works before lock_ref
                self.monitor.set_wavelengths(wl_data)
                self.lbl_fwhm_display.setText(f"💡 WL Loaded: {os.path.basename(filepath)}")
                # Recompute px from nm spinbox with the new dispersion
                if hasattr(self, 'spin_fwhm_nm') and self.spin_fwhm_nm.value() > 0:
                    self._update_fwhm_px_from_nm(self.spin_fwhm_nm.value())
                self._refresh_setup_status()
                # Show popup only if loaded manually
                if not auto_path:
                    QMessageBox.information(self, "Loaded", f"X-Axis Calibration Loaded.\nRange: {wl_data.min():.2f} ~ {wl_data.max():.2f} nm")
            else:
                QMessageBox.warning(self, "Error", "No valid numeric data found in the file.")
                
        except Exception as e: 
            QMessageBox.critical(self, "Error", f"Failed to load wavelength file:\n{str(e)}")

    def set_range_from_nm(self):
        """Converts user-input nm range into pixel indices based on loaded wavelength data."""
        if self.monitor.wavelengths is None:
            QMessageBox.warning(self, "Error", "Please load the X-Axis (nm) wavelength file first!")
            return
            
        min_nm = self.spin_fit_start_nm.value()
        max_nm = self.spin_fit_end_nm.value()
        if min_nm > max_nm:
            min_nm, max_nm = max_nm, min_nm

        wl = self.monitor.wavelengths
        idx_min = np.abs(wl - min_nm).argmin()
        idx_max = np.abs(wl - max_nm).argmin()
        
        start = min(idx_min, idx_max)
        end = max(idx_min, idx_max)

        self.txt_min.setText(str(start))
        self.txt_max.setText(str(end))
        self.status.setText(f"Range Set: {min_nm:.1f}nm ~ {max_nm:.1f}nm (Pixels {start}~{end})")

    def batch_load_refs(self):
        """Batch load multiple reference files at once."""
        files, _ = QFileDialog.getOpenFileNames(self, "Select References", self._dlg_dir('refs'), "All Files (*.*)")
        if files:
            self._dlg_dir('refs', files[0])
        if files: 
            for f in sorted(files): 
                self.add_ref_row(self.guess_gas_name(f), f)
            
    def get_auto_scale_exponent(self, filepath):
        """
        Calculates the integer power-of-10 multiplier needed to bring a reference
        cross-section into the ~1e-19 cm² range expected by the engine.

        Example: if the file peak is 1e-38 (very small), exponent = -19 - (-38) = 19,
        so the spinner shows 19 and the engine multiplies by 10^19.
        """
        try:
            _, intensity_raw = DataIO.load_reference(filepath)
            
            if intensity_raw is None or len(intensity_raw) == 0: 
                return 0
                
            max_val = np.max(np.abs(intensity_raw))
            if max_val == 0: 
                return 0
                
            current_exp = math.floor(math.log10(max_val))
            target_exp = -19 
            return target_exp - current_exp
            
        except Exception: 
            return 0

    # ---------------------------------------------------------
    # Reference List Management (Add, Delete, Mask, Lock)
    # ---------------------------------------------------------
    def add_ref_row(self, name=None, path=None):
        """Adds a new row to the reference list UI."""
        widget_row = QWidget()
        layout_row = QHBoxLayout(widget_row)
        layout_row.setContentsMargins(0, 0, 0, 0)
        
        layout_row.addWidget(QLabel("x1e"))
        spin_mult = QSpinBox()
        spin_mult.setRange(-100, 100)
        spin_mult.setFixedWidth(int(50 * self._s))

        if path:
            spin_mult.setValue(self.get_auto_scale_exponent(path))
        else:
            spin_mult.setValue(0)

        txt_name = QLineEdit()
        txt_name.setFixedWidth(int(80 * self._s))
        lbl_path = QLabel("...")

        btn_select = QPushButton("S")
        btn_delete = QPushButton("X")
        btn_delete.setFixedWidth(int(30 * self._s))
        
        def select_file_wrapper():
            f, _ = QFileDialog.getOpenFileName(self, "Select Reference", self._dlg_dir('refs'), "All Files (*.*)")
            self._dlg_dir('refs', f)
            if f:
                lbl_path.setText(os.path.basename(f))
                txt_name.setText(self.guess_gas_name(f))
                spin_mult.setValue(self.get_auto_scale_exponent(f))
                for item in self.ref_widgets:
                    if item['w'] == widget_row: 
                        item['fp'] = f
                        break
                        
        btn_select.clicked.connect(select_file_wrapper)
        btn_delete.clicked.connect(lambda: self.del_ref(widget_row))
        
        layout_row.addWidget(spin_mult)
        layout_row.addWidget(txt_name)
        layout_row.addWidget(lbl_path)
        layout_row.addWidget(btn_select)
        layout_row.addWidget(btn_delete)
        
        if name: 
            txt_name.setText(name)
        if path: 
            lbl_path.setText(os.path.basename(path))
            
        ref_entry = {'w': widget_row, 'n': txt_name, 'p': lbl_path, 'fp': path, 'mult': spin_mult, 'btn': btn_select}
        self.ref_widgets.append(ref_entry)
        
        self.ref_lay.addWidget(widget_row)
        print(f"✅ Slot Added: {name if name else 'Empty'}")
        
    def del_ref(self, widget): 
        """Removes a reference row from the UI."""
        widget.deleteLater()
        self.ref_widgets = [x for x in self.ref_widgets if x['w'] != widget]

    def open_mask_dialog(self):
        """Opens the dialog to apply masking (zeroing out noise) to loaded references."""
        if not self.engine.is_engine_ready():
            QMessageBox.warning(self, "Warning", "Please load references and click the 'Lock' button first.")
            return
        
        dlg = MaskDialog(self.engine.gas_list)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            name = data['name']
            
            if data['mode'] == 'manual':
                try:
                    mn, mx = map(int, data['range'].split('-'))
                    if self.engine.apply_manual_mask(name, mn, mx):
                        QMessageBox.information(self, "Success", f"Manual masking applied to {name}.")
                        self.refresh_viewer() 
                except Exception:
                    QMessageBox.warning(self, "Error", "Invalid range format. (e.g., 400-500)")
            else:
                thresh = data['threshold']
                if self.engine.apply_auto_mask(name, thresh):
                    QMessageBox.information(self, "Success", f"Signals below {thresh}% were removed from {name}.")
                    self.refresh_viewer() 
                else:
                    QMessageBox.warning(self, "Error", "Auto-masking failed.")

    def lock_ref(self):
        """
        Commits all configured references from the UI into the UniversalEngine.

        'Locking' means:
          1. The engine is cleared of any previous references.
          2. Each reference file is loaded, resampled to the instrument wavelength
             axis, scaled by its 10^exponent multiplier, and stored.
          3. A zero-FWHM convolution pass is run to initialize the interpolators.

        After locking, the engine is ready to call get_basis_matrix() for fitting.
        """
        self.engine.clear_engine()
        success_count = 0
        
        raw_wave = getattr(self.engine, 'wavelengths', 
                           getattr(self, 'wavelengths', 
                                   getattr(self, 'wave_data', None)))

        current_wave = None
        if raw_wave is not None:
            if isinstance(raw_wave, tuple):
                current_wave = np.array(raw_wave[ 0 ]).flatten()
            else:
                current_wave = np.array(raw_wave).flatten()

        for widget in self.ref_widgets:
            if widget['n'].text() and widget['fp']:
                exponent = widget['mult'].value()
                multiplier = 10.0 ** exponent
                
                success, msg = self.engine.add_reference(
                    name=widget['n'].text(), 
                    filepath=widget['fp'], 
                    wave_nm=current_wave,
                    multiplier=multiplier
                )
                
                if success: 
                    success_count += 1
                else:
                    print(f"⚠️ Lock Failed ({widget['n'].text()}): {msg}")
                    
        # Register wavelength axis in the engine (required for pixel_to_wavelength)
        if current_wave is not None:
            self.engine.set_wavelength_axis(current_wave)

        # Apply zero convolution initially (refreshes internal interpolators)
        self.engine.apply_ils_convolution(0.0)
        
        if success_count > 0:
            QMessageBox.information(self, "Locked", f"{success_count} references have been successfully locked into the Engine.")

            # Dynamically update the Result Table headers
            if hasattr(self, 'table'):
                cols = ["File", "Time", "RMS", "Chi2", "SNR", "Status"] + self.engine.gas_list + ["Shift", "Squeeze"]
                self.table.setColumnCount(len(cols))
                self.table.setHorizontalHeaderLabels(cols)
                
            # Update Monitor dropdown list
            if hasattr(self, 'monitor') and hasattr(self.monitor, 'cb_view'):
                self.monitor.cb_view.clear()
                self.monitor.cb_view.addItem("Measurement")
                for name in self.engine.gas_list:
                    self.monitor.cb_view.addItem(f"Ref: {name}")
            # ILS was applied to the old interpolators — mark dirty so user re-applies
            self._ils_applied = False
            if hasattr(self, 'btn_apply_ils'):
                self.btn_apply_ils.setStyleSheet(
                    "font-weight: bold;")
            self._refresh_setup_status()
        else:
            QMessageBox.warning(self, "Error", "No valid references found to lock, or an error occurred.")


    # ---------------------------------------------------------
    # Measurement Data Loading & UI State Logic
    # ---------------------------------------------------------
    def load_data(self):
        """
        Smart router that allows choosing between file or folder loading
        using a single button to keep the main UI clean.
        """
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Select Load Method")
        msg_box.setText("How would you like to load the measurement data?")
        msg_box.setIcon(QMessageBox.Icon.Question)
        
        # Add custom buttons
        btn_files = msg_box.addButton("📄 Select Files", QMessageBox.ButtonRole.ActionRole)
        btn_folder = msg_box.addButton("📁 Load Entire Folder", QMessageBox.ButtonRole.ActionRole)
        msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        
        msg_box.exec()
        
        # Route to the appropriate function based on user selection
        if msg_box.clickedButton() == btn_files:
            self._load_files()
        elif msg_box.clickedButton() == btn_folder:
            self._load_folder()

    def _load_files(self):
        """Loads specific measurement files selected by the user."""
        files, _ = QFileDialog.getOpenFileNames(self, "Select Measurement Files", self._dlg_dir('data'), "Data Files (*.dat *.txt *.csv)")
        if files:
            self._dlg_dir('data', files[0])
            self._update_file_table(sorted(files))

    def _load_folder(self):
        """Scans a selected folder and loads all valid measurement files."""
        folder_path = QFileDialog.getExistingDirectory(self, "Select Measurement Folder", self._dlg_dir('data'))
        if folder_path:
            self._dlg_dir('data', folder_path)
            # Filter files by valid extensions (.dat, .txt, .csv)
            valid_extensions = ('.dat', '.txt', '.csv')
            files = [
                os.path.join(folder_path, f) 
                for f in os.listdir(folder_path) 
                if f.lower().endswith(valid_extensions)
            ]
            
            if files:
                self._update_file_table(sorted(files))
            else:
                QMessageBox.warning(self
                                    , "No Data", "No analyzable files (.dat, .txt, .csv) found in the selected folder.")

    # ── file_list entry helpers ──────────────────────────────────────────────
    def _entry_filepath(self, entry):
        """Returns the raw filepath string from a file_list entry (str or tuple)."""
        return entry[0] if isinstance(entry, tuple) else entry

    def _entry_display_name(self, entry):
        """Returns the display name shown in the table for a file_list entry."""
        if isinstance(entry, tuple):
            fp, ri = entry
            return f"{os.path.basename(fp)} [{ri:04d}]"
        return os.path.basename(entry)

    def _entry_row_index(self, entry):
        """Returns the scan row index (0 for single-scan / plain files)."""
        return entry[1] if isinstance(entry, tuple) else 0

    def _entry_from_display_name(self, display_name):
        """Finds the file_list entry whose display name matches display_name."""
        return next((e for e in self.file_list if self._entry_display_name(e) == display_name), None)

    # ────────────────────────────────────────────────────────────────────────

    def _update_file_table(self, file_list):
        """
        Stores file paths and shows them in the table.

        Araon Mega-Matrix files contain many scans per row — expansion into
        individual (filepath, row_index) entries is deferred to the Worker
        thread so the UI never freezes during large folder loads.
        After loading, auto-detect the channel count from the first file.
        """
        self.file_list = list(file_list)          # plain strings only — no expansion here
        self.table.setRowCount(len(self.file_list))
        self.table.clearContents()

        for i, fp in enumerate(self.file_list):
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(fp)))

        self.status.setText(f"📁 {len(self.file_list)} file(s) loaded.")
        self._auto_detect_channels()

    def _auto_detect_channels(self):
        """Detect how many spectrum channels the loaded files contain and update the UI label."""
        if not self.file_list:
            return
        try:
            first = self._entry_filepath(self.file_list[0])
            from core.data_io import DataIO
            n = DataIO.detect_channels(first)
            self._detected_channels = n
            ch_names = {1: "CH1", 2: "CH1+CH2", 3: "CH1+CH2+CH3"}
            ch_labels = {
                1: "1채널  (Cold / single-cavity)",
                2: "2채널  (Hot:  CH1 PNs 180°C  +  CH2 ANs 300°C)",
                3: "3채널  (CH1 + CH2 + CH3)",
            }
            label = ch_labels.get(n, f"{n}채널")
            self.lbl_channel_info.setText(label)
            # 채널별 Fit 범위(nm) 행: 감지된 채널 수만큼만 노출
            for _ch, _roww in getattr(self, '_ch_fit_rows', {}).items():
                _roww.setVisible(_ch <= n)
            colours = {1: "#1565C0", 2: "#6A1B9A", 3: "#2E7D32"}
            self.lbl_channel_info.setStyleSheet(
                f"color: {colours.get(n, '#333')}; font-weight: bold;")
            self.status.setText(
                f"📁 {len(self.file_list)} file(s) loaded  —  {ch_names.get(n, str(n)+'CH')} 감지됨")
        except Exception as e:
            print(f"[channel detect] {e}")

    def apply_convolution(self):
        """Applies Instrument Line Shape blur (Voigt kernel) based on entered FWHM values."""
        if not self.engine.is_engine_ready():
            QMessageBox.warning(self, "Warning", "Please load references first.")
            return

        fwhm_g = self.spin_fwhm.value()
        fwhm_l = self.spin_fwhm_lorentzian.value()
        self.engine.apply_ils_convolution(fwhm_g, fwhm_l)
        self.refresh_viewer()
        label = (f"Voigt (G={fwhm_g:.2f}, L={fwhm_l:.2f} px)"
                 if fwhm_l > 0.1 else f"Gaussian FWHM={fwhm_g:.2f} px")

        # Mark ILS as applied → button turns green
        self._ils_applied = True
        if hasattr(self, 'btn_apply_ils'):
            self.btn_apply_ils.setStyleSheet(
                "font-weight: bold;")

        self._refresh_setup_status()
        QMessageBox.information(self, "Applied", f"ILS Blur ({label}) successfully applied.")
        
    def open_selector(self):
        """Opens the visual RangeSelectorDialog."""
        if not self.file_list: 
            return
        try: 
            mn, mx = int(self.txt_min.text()), int(self.txt_max.text())
        except Exception: 
            mn, mx = 0, 950
            
        # Use the middle file as a representative spectrum for the visual preview
        mid_entry = self.file_list[len(self.file_list) // 2]
        mid_file = self._entry_filepath(mid_entry)
        self.sel_dlg = RangeSelectorDialog(mid_file, mn, mx, self.engine)
        self.sel_dlg.apply_range.connect(self.update_range)
        self.sel_dlg.exec()
        
    def update_range(self, min_idx, max_idx):
        """Updates the text boxes with the visual selection."""
        if getattr(self, '_analysis_running', False):
            return
        self.txt_min.setText(str(min_idx))
        self.txt_max.setText(str(max_idx))

    def apply_roi_from_graph(self, min_val, max_val):
        """Updates the fitting range directly from the fast monitor ROI selection."""
        if getattr(self, '_analysis_running', False):
            return
        self.txt_min.setText(str(min_val))
        self.txt_max.setText(str(max_val))
        self.status.setText(f"Range Selected: {min_val} ~ {max_val}")

    # ---------------------------------------------------------
    # Multithreading Analysis Execution (Worker)
    # ---------------------------------------------------------
    def _alpha_channel_groups(self, file_list):
        """입력이 모두 알파trace 파일이면 파일명(_PNs_/_ANs_/_CH3_/_Cold_)으로
        채널 그룹화해 {채널idx: [entries]} 반환. 하나라도 알파trace가 아니면 None
        (= 일반 raw 입력이므로 기존 채널 검출 로직 사용)."""
        if not file_list:
            return None
        label_to_ch = {'pns': 1, 'ans': 2, 'ch3': 3, 'cold': 1}
        groups = {}
        for entry in file_list:
            fp = entry if isinstance(entry, str) else self._entry_filepath(entry)
            name = os.path.basename(str(fp)).lower()
            if 'alpha_trace' not in name:
                return None
            ch = 1
            for lbl, c in label_to_ch.items():
                if f'_{lbl}_' in name:
                    ch = c
                    break
            groups.setdefault(ch, []).append(entry)
        return groups or None

    def start_analysis(self):
        """
        Validates settings, builds the initial parameter vector p0, and starts
        the AnalysisWorker background thread.

        p0 layout: [shift, squeeze, gas_0, gas_1, …, poly_0, poly_1, …]
          - shift    : initial wavelength offset guess (pixels)
          - squeeze  : initial stretch factor (dimensionless, ~1.0)
          - gas_i    : initial concentration guess for each loaded gas
          - poly_j   : initial polynomial coefficient guesses
        """
        if not self.file_list: 
            return
        if not self.engine.is_engine_ready(): 
            QMessageBox.warning(self, "Warning", "Please lock references into the Engine first.")
            return
            
        try:
            pixel_min, pixel_max = int(self.txt_min.text()), int(self.txt_max.text())
        except Exception:
            QMessageBox.warning(self, "Input Error", "Please enter valid integers for Pixel Min/Max.")
            return
        self._analysis_running = True
        
        self.results = []

        # Multi-channel state
        n_ch = self._detected_channels
        # 알파trace 파일 입력이면 파일명(_PNs_/_ANs_/_CH3_)으로 채널 그룹화 →
        # 채널별 워커로 분리해 CH1/CH2 트렌드가 섞이지 않게 한다.
        self._alpha_groups = self._alpha_channel_groups(self.file_list)
        if self._alpha_groups:
            n_ch = len(self._alpha_groups)
        self._multi_channel_mode = (n_ch > 1)
        self._workers = []
        self._workers_done = 0
        self._workers_total = n_ch
        self._next_table_row = 0   # dynamic row counter for multi-channel append
        self._scan_counts = {}     # channel → expanded-scan count (progress denominator)

        # 🌟 UI Table Reset: start empty — rows are added dynamically as scans complete
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(0)

        # Lock in column headers dynamically based on loaded gases
        # Add "Ch" prefix column when multiple channels detected
        if self._multi_channel_mode:
            cols = ["Ch", "File", "Time", "RMS", "Chi2", "SNR", "Status"] + self.engine.gas_list + ["Shift", "Squeeze"]
        else:
            cols = ["File", "Time", "RMS", "Chi2", "SNR", "Status"] + self.engine.gas_list + ["Shift", "Squeeze"]
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        
        # Progress bar: maximum is unknown until the worker expands Araon files.
        # Set to 0 (indeterminate / busy animation) until scan_count_ready fires.
        self.pbar.setMinimum(0)
        self.pbar.setMaximum(0)
        self.pbar.setValue(0)
        
        self.monitor.clear_trend()

        # R-curve from a previous run is in fit-pixel-range length, not full-spectrum
        # length, so the slicing guard below would misfire. Clear it so this run
        # derives R fresh from its own He/ZA scans.
        if getattr(self, '_r_auto_derived', False):
            self.r_data = None
            self._r_auto_derived = False

        # Configure Initial Parameters and Bounds
        num_gases = len(self.engine.gas_list)
        
        start_shift = 0.0  
        step_limit_val = self.spin_step_limit.value()
        
        poly_deg = self.spin_poly_deg.value()
        num_poly_params = poly_deg + 1
        
        # p0 layout: [shift, squeeze, gas_0 ... gas_N, poly_0 ... poly_P]
        # bounds_low / bounds_high define the search box for the optimizer:
        #   - shift is unconstrained globally (rolling window applied inside the worker)
        #   - squeeze is limited to ±5% of 1.0  (physically reasonable range)
        #   - gas concentrations are lower-bounded at 0 (NNLS ensures this anyway)
        p0 = [start_shift, self.calib_squeeze] + [0.1] * num_gases + [0] * num_poly_params
        bounds_low  = [-np.inf, 0.95] + [0.0]    * num_gases + [-np.inf] * num_poly_params
        bounds_high = [ np.inf, 1.05] + [np.inf] * num_gases + [ np.inf] * num_poly_params
        
        interval = self.spin_update.value()
        
        # Dynamic delay control based on UI Checkboxes
        delay_ms = 200 if self.chk_observe.isChecked() else 0
        if self.chk_turbo.isChecked(): 
            interval = -1
            delay_ms = 0
            
        # [ BBCEAS Data Preparation ]
        sliced_i0   = None
        sliced_r    = None
        sliced_dark = None
        cavity_d    = self.spin_d_len.value()

        if hasattr(self, 'i0_data') and self.i0_data is not None:
            if len(self.i0_data) > pixel_max:
                sliced_i0 = self.i0_data[pixel_min:pixel_max]
            else:
                QMessageBox.warning(self, "Warning", "I0 data length is shorter than Fit Max Pixel.")
                return

        if hasattr(self, 'r_data') and self.r_data is not None:
            if len(self.r_data) > pixel_max:
                sliced_r = self.r_data[pixel_min:pixel_max]
            else:
                # Plain 1D files (alpha traces, pre-computed OD) run in linear mode
                # and never use R — silently ignore stale R from a previous BBCEAS run.
                # Only block when the input is a BBCEAS Araon Mega-Matrix file.
                first_is_matrix = (bool(self.file_list) and
                                   DataIO.is_araon_mega_matrix(self.file_list[0]))
                if first_is_matrix:
                    QMessageBox.warning(self, "Warning", "Reflectivity (R) data length mismatch.")
                    return
                # else: sliced_r stays None → fallback handled below

        if hasattr(self, 'dark_data') and self.dark_data is not None:
            if len(self.dark_data) >= pixel_max:
                sliced_dark = self.dark_data[pixel_min:pixel_max]

        sliced_offset = None
        if hasattr(self, 'offset_data') and self.offset_data is not None:
            if len(self.offset_data) >= pixel_max:
                sliced_offset = self.offset_data[pixel_min:pixel_max]
            else:
                QMessageBox.warning(self, "Warning", "Offset data length is shorter than Fit Max Pixel — offset ignored.")

        use_temporal = self.chk_temporal_i0.isChecked()

        if sliced_i0 is None or sliced_r is None:
            # Check if the first file is an Araon Mega-Matrix — if so, the worker
            # will auto-derive I0 and R from the He/ZA rows embedded in each file.
            has_embedded_calib = bool(self.file_list) and DataIO.is_araon_mega_matrix(self.file_list[0])
            if has_embedded_calib:
                ans = QMessageBox.question(
                    self, "BBCEAS 자동 캘리브레이션",
                    "R / I₀ 파일이 별도로 로드되지 않았습니다.\n\n"
                    "측정 파일 내에 He 스캔(flag 510~513)과 ZA 스캔(flag 500~503)이\n"
                    "포함돼 있어 R-curve(flag 510)와 I₀(flag 500)를 자동 계산합니다.\n\n"
                    "피팅을 시작합니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if ans == QMessageBox.StandardButton.No:
                    self.b_run.setEnabled(True)
                    return
            else:
                ans = QMessageBox.question(
                    self, "Missing BBCEAS Params",
                    "I0 or R is missing.\nFallback to standard DOAS (Log intensity ratio)?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if ans == QMessageBox.StandardButton.No:
                    self.b_run.setEnabled(True)
                    return

        # Initialize and fire Worker Thread(s) — one per detected channel
        # All channels run in parallel from the same file list
        flag_za  = self._parse_flags(self.txt_flag_za.text())
        flag_he  = self._parse_flags(self.txt_flag_he.text())
        flag_amb = self._parse_flags(self.txt_flag_amb.text())

        ch_list = sorted(self._alpha_groups) if self._alpha_groups else list(range(1, n_ch + 1))
        for ch in ch_list:
            files_for_ch = self._alpha_groups[ch] if self._alpha_groups else self.file_list
            w = AnalysisWorker(
                self.engine, files_for_ch, pixel_min, pixel_max,
                p0, (bounds_low, bounds_high), interval, delay_ms,
                ref_properties=getattr(self, 'ref_props', {}),
                i0_array=sliced_i0, r_array=sliced_r, cavity_len=cavity_d,
                dark_array=sliced_dark,
                dark_scale_factor=self.spin_dark_scale.value(),
                offset_array=sliced_offset,
                offset_scale_factor=self.spin_offset_scale.value(),
                stray_light_fraction=self.spin_stray_light.value(),
                use_temporal_i0=use_temporal,
                flag_za=flag_za,
                flag_he=flag_he,
                flag_amb=flag_amb,
                save_alpha=self.chk_save_alpha.isChecked(),
                alpha_save_dir=getattr(self, 'alpha_save_dir', ''),
                rl_factor=self.spin_rl_factor.value(),
                channel=ch
            )

            w.step_limit = step_limit_val
            w.tikhonov_lambda = self.spin_lambda.value()
            w.use_robust_fitting = self.chk_robust.isChecked()
            w.kalman_q = self.spin_kalman_q.value()
            w.kalman_r = self.spin_kalman_r.value()
            w.temperature = self.spin_temp.value()
            w.pressure = self.spin_pres.value()
            w.ok_rms_threshold = self.spin_rms_thresh.value() / 100.0

            # Connect signals
            #   Progress is driven by completed-result count vs total scans across
            #   ALL channels (see update_table / _on_scan_count_ready), NOT by each
            #   worker's local file counter — otherwise parallel workers race and the
            #   bar caps at 100/N % (the "2채널이면 50%에서 멈춤" bug).
            w.result_ready.connect(self.update_table)
            w.plot_update.connect(self.monitor.update_spectrum)
            w.trend_update.connect(self.monitor.update_trend)
            w.finished.connect(self.analysis_finished)
            w.r_curve_update.connect(self._on_r_curve_update)
            w.scan_count_ready.connect(lambda n, ch=ch: self._on_scan_count_ready(n, ch))

            self._workers.append(w)

        # Keep self.worker pointing to CH1 worker for legacy stop/wait references
        self.worker = self._workers[0]

        # Lock UI controls to prevent interference
        self.b_run.setEnabled(False)
        self.b_stop.setEnabled(True)
        self.status.setText("🏃 Analysis in progress...")

        # Switch to the Analysis Monitor tab automatically (index 2 in new 3-tab layout)
        self.main_tabs.setCurrentIndex(2)

        for w in self._workers:
            w.start()
        
    def _on_scan_count_ready(self, total_scans, ch=1):
        """Called once a worker has finished expanding all files into individual scans.

        Progress denominator = SUM of expanded-scan counts across every channel
        worker (each worker reports its own count for its channel). The bar value
        is the number of completed results (see update_table), so it reaches 100%
        only when every channel's every scan is done.
        """
        self._scan_counts[ch] = total_scans
        total_all = max(1, sum(self._scan_counts.values()))
        self.pbar.setMaximum(total_all)
        if self._multi_channel_mode:
            # Multi-channel: rows arrive interleaved from parallel workers — grow dynamically
            n_ch = self._workers_total
            self.status.setText(
                f"🏃 {total_all:,} scans ({n_ch} CH) / {len(self.file_list)} file(s) — processing..."
            )
        else:
            # Single-channel: pre-allocate rows for O(1) update_table writes
            self.table.setRowCount(total_scans)
            self.status.setText(f"🏃 {total_scans:,} scans / {len(self.file_list)} file(s) — processing...")

    def stop_analysis(self):
        """Safely stops all worker threads and re-enables UI controls."""
        workers = getattr(self, '_workers', [])
        if not workers and hasattr(self, 'worker'):
            workers = [self.worker]   # legacy fallback

        running = [w for w in workers if w.isRunning()]
        if running:
            for w in running:
                w.stop()
            self.status.setText("🛑 Halting analysis... please wait.")
            self.status.setStyleSheet("color: red; font-weight: bold;")
            self.b_stop.setEnabled(False)
            for w in running:
                w.wait()
            self.analysis_finished(stopped=True)
            
    def update_table(self, result_dict, row_index):
        """Triggered by the worker thread to update the table row-by-row."""
        self.results.append(result_dict)

        multi = getattr(self, '_multi_channel_mode', False)

        if multi:
            # Parallel workers share a dynamic row counter — use next free row
            row = self._next_table_row
            self._next_table_row += 1
            if row >= self.table.rowCount():
                self.table.setRowCount(row + 1)
            # col 0: channel tag (CH1 / CH2 / CH3)
            ch = result_dict.get('Channel', 1)
            self.table.setItem(row, 0, QTableWidgetItem(f"CH{ch}"))
            c = 1   # column offset for remaining fields
        else:
            row = row_index
            if row >= self.table.rowCount():
                self.table.setRowCount(row + 1)
            c = 0   # no Ch column

        # col c+0: filename + scan index
        self.table.setItem(row, c + 0, QTableWidgetItem(str(result_dict['File'])))
        # col c+1: measurement timestamp
        self.table.setItem(row, c + 1, QTableWidgetItem(str(result_dict.get('Time', ''))))
        # col c+2..4: fit quality metrics
        self.table.setItem(row, c + 2, QTableWidgetItem(f"{result_dict.get('RMS', 0):.2e}"))
        self.table.setItem(row, c + 3, QTableWidgetItem(f"{result_dict.get('Chi2', 0):.2f}"))
        self.table.setItem(row, c + 4, QTableWidgetItem(f"{result_dict.get('SNR', 0):.1f}"))

        # col c+5: status with conditional background colour
        item_status = QTableWidgetItem(str(result_dict.get('Status', '')))
        try:
            status = result_dict.get('Status', '')
            if status not in ("OK", "Recovered"):
                item_status.setBackground(QColor(255, 100, 100))
            elif status == "Recovered":
                item_status.setBackground(QColor(255, 220, 100))
        except Exception:
            pass
        self.table.setItem(row, c + 5, item_status)

        # col c+6+i: gas concentrations, then Shift, Squeeze
        for i, gas_name in enumerate(self.engine.gas_list):
            self.table.setItem(row, c + 6 + i, QTableWidgetItem(f"{result_dict.get(gas_name, 0):.2e}"))

        gas_offset = len(self.engine.gas_list)
        self.table.setItem(row, c + 6 + gas_offset,     QTableWidgetItem(f"{result_dict.get('Shift', 0):.2f}"))
        self.table.setItem(row, c + 6 + gas_offset + 1, QTableWidgetItem(f"{result_dict.get('Squeeze', 1):.4f}"))

        # Force UI scroll to follow the latest row
        item = self.table.item(row, 0)
        if item:
            self.table.scrollToItem(item)

        # Advance progress bar by completed-result count (works for both single- and
        # multi-channel: denominator is the summed scan count across all workers).
        self.pbar.setValue(len(self.results))
        
    def analysis_finished(self, stopped=False):
        """Re-enables UI once ALL channel workers have finished."""
        self._analysis_running = False
        if stopped:
            # Stop requested — re-enable immediately regardless of pending workers
            self.b_run.setEnabled(True)
            self.b_stop.setEnabled(False)
            self.status.setText("🛑 Analysis stopped by user.")
            self.status.setStyleSheet("color: red; font-weight: bold;")
            return

        # Count completed workers; wait until the last one finishes
        self._workers_done = getattr(self, '_workers_done', 0) + 1
        total = getattr(self, '_workers_total', 1)

        if self._workers_done < total:
            # Still waiting for other channels
            remaining = total - self._workers_done
            self.status.setText(
                f"✅ CH{self._workers_done} done — waiting for {remaining} more channel(s)..."
            )
            return

        # All workers finished
        self.b_run.setEnabled(True)
        self.b_stop.setEnabled(False)
        n_ch = total
        ch_label = f"{n_ch}-channel " if n_ch > 1 else ""
        self.status.setText(f"✅ {ch_label}Analysis Completed!")
        self.status.setStyleSheet("color: green; font-weight: bold;")
        QMessageBox.information(self, "Done", f"All files analyzed successfully ({n_ch} channel(s)).")

    def save(self):
        """
        Exports all analysis results to a tab-separated .dat or .csv file.

        The auto-generated filename encodes the key fit settings so you can
        identify the run later without opening the file:
          e.g.  240420_1523_Result_NO2_H2O_445.0-465.0nm_Poly3_L0.0001_Robust_Step[0.5]_...dat

        A metadata header block is prepended with the exact fit parameters,
        followed by the data table (one row per measurement file).
        """
        if not hasattr(self, 'results') or not self.results:
            QMessageBox.warning(self, "Warning", "No analysis results to save. Please RUN the analysis first.")
            return
            
        now_str = datetime.datetime.now().strftime("%y%m%d_%H%M") 
        
        gas_list_str = "_".join(self.engine.gas_list) if hasattr(self, 'engine') and self.engine.gas_list else "NoRefs"
        poly_deg = self.spin_poly_deg.value()
        step_val = self.spin_step_limit.value() if hasattr(self, 'spin_step_limit') else 0.5
        
        # 1. Read pixel indices from UI text boxes
        try:
            f_min_px = int(self.txt_min.text())
            f_max_px = int(self.txt_max.text())
        except Exception:
            f_min_px, f_max_px = 0, 0
            
        wl_str = f"{f_min_px}-{f_max_px}px" # Default fallback
        
        # 🌟 2. Convert Pixel to Wavelength (nm) for filename clarity!
        wl_array = None
        if hasattr(self, 'monitor') and getattr(self.monitor, 'wavelengths', None) is not None:
            wl_array = self.monitor.wavelengths
            
        if wl_array is not None and len(wl_array) > max(f_min_px, f_max_px):
            try:
                wl_min = wl_array[f_min_px]
                wl_max = wl_array[f_max_px]
                wl_str = f"{wl_min:.1f}-{wl_max:.1f}nm" # e.g., 445.0-465.0nm
            except Exception as e:
                print(f"Filename wavelength conversion error: {e}")

        # =========================================================
        # 3. Trace linked Shift/Squeeze properties for filename
        # =========================================================
        sh_str, sq_str = "Sh[None]", "Sq[None]"
        if hasattr(self, 'engine') and self.engine.gas_list and hasattr(self, 'ref_props'):
            first_gas = self.engine.gas_list[0]
            
            def get_real_value(gas, prop_prefix):
                curr_gas = gas
                visited = set() 
                
                while curr_gas and curr_gas not in visited:
                    visited.add(curr_gas)
                    props = self.ref_props.get(curr_gas, {})
                    mode = props.get(f"{prop_prefix}_mode", "Limit")
                    val = str(props.get(f"{prop_prefix}_val", "")).strip()
                    
                    if mode == "Free":
                        return "Free"
                    elif mode == "Link":
                        curr_gas = val 
                    else:
                        return val.replace(" ", "") 
                return "Unknown"

            real_sh = get_real_value(first_gas, "sh")
            real_sq = get_real_value(first_gas, "sq")
            
            sh_str = f"Sh[{real_sh}]"
            sq_str = f"Sq[{real_sq}]"

        lam_val = self.spin_lambda.value() if hasattr(self, 'spin_lambda') else 0.0
        robust_str = "Robust" if hasattr(self, 'chk_robust') and self.chk_robust.isChecked() else "Std"

        default_fname = f"{now_str}_Result_{gas_list_str}_{wl_str}_Poly{poly_deg}_L{lam_val:g}_{robust_str}_Step[{step_val}]_{sh_str}_{sq_str}.dat"
        
        _start = os.path.join(self._dlg_dir('save'), default_fname) if self._dlg_dir('save') else default_fname
        path, _ = QFileDialog.getSaveFileName(self, "Save Data", _start, "Data Files (*.dat);;CSV Files (*.csv)")
        self._dlg_dir('save', path)

        if path:
            try:
                df = pd.DataFrame(self.results)
                
                if 'Params' in df.columns:
                    df = df.drop(columns=['Params'])
                    
                current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                robust_status = "ON" if hasattr(self, 'chk_robust') and self.chk_robust.isChecked() else "OFF"
                
                kalman_q = self.spin_kalman_q.value()
                kalman_r = self.spin_kalman_r.value()
                rms_thresh_pct = self.spin_rms_thresh.value()
                temporal_i0 = "ON" if self.chk_temporal_i0.isChecked() else "OFF"
                dark_loaded = "YES" if (hasattr(self, 'dark_data') and self.dark_data is not None) else "NO"
                dark_scale_val = self.spin_dark_scale.value()
                offset_loaded = "YES" if (hasattr(self, 'offset_data') and self.offset_data is not None) else "NO"
                offset_scale_val = self.spin_offset_scale.value()
                stray_light_val = self.spin_stray_light.value()

                header_lines = [
                    "# ==========================================================",
                    "# CAESAR Pro Analysis Report",
                    f"# Generated: {current_time}",
                    f"# Fit Range: Pixel {f_min_px}-{f_max_px} ({wl_str})",
                    f"# Polynomial Degree: {poly_deg}",
                    f"# Tikhonov Lambda: {lam_val:g}",
                    f"# Robust Fitting (IRLS): {robust_status}",
                    f"# Step Limit: {step_val} px",
                    f"# OK RMS Threshold: {rms_thresh_pct:.1f}%  (fit accepted when RMS/signal < threshold)",
                    f"# Kalman Filter: Q={kalman_q:.4f}, R={kalman_r:.3f}  (concentration columns = raw fit; _Smooth = Kalman-filtered)",
                    f"# Dark Current Subtraction: {dark_loaded}  (scale={dark_scale_val:.4f})",
                    f"# Detector Offset Subtraction: {offset_loaded}  (scale={offset_scale_val:.4f})",
                    f"# Stray Light Correction: {'ON' if stray_light_val > 0 else 'OFF'}  (epsilon={stray_light_val:.4f})",
                    f"# Temporal I0 Interpolation: {temporal_i0}",
                    f"# Purge Gas RL Factor: {self.spin_rl_factor.value():.4f}  (1.0 = no correction; CAESAR CH1=0.9330 CH2=0.9950 CH3=0.9968)",
                    f"# Measurement Flags: Ambient={self.txt_flag_amb.text().strip()}, ZA={self.txt_flag_za.text().strip()}, He={self.txt_flag_he.text().strip()}",
                    f"# Reference Constraints: {sh_str}, {sq_str}",
                    "# ==========================================================\n"
                ]

                with open(path, 'w', encoding='utf-8') as f:
                    f.write("\n".join(header_lines))
                    
                    if path.endswith('.csv'):
                        df.to_csv(f, index=False, lineterminator='\n')
                    else:
                        df.to_csv(f, sep='\t', index=False, lineterminator='\n')
                    
                QMessageBox.information(self, "Success", f"🎉 Analysis results saved successfully!\nFile: {os.path.basename(path)}")
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"An error occurred while saving:\n{e}")

    # ---------------------------------------------------------
    # Viewer Events (Table Click Sync)
    # ---------------------------------------------------------
    def on_table_double_click(self, row, col):
        """
        Replays the stored fit for a completed row.

        Double-clicking a result row re-evaluates the engine model using the
        fit parameters (shifts, squeezes, gas_coeffs, etc.) that were saved for
        that file, then sends the result to the monitor — allowing you to inspect
        any individual spectrum without re-running the full analysis.
        """
        # File name lives in col 0 normally, but col 1 when the "Ch" column is
        # prepended in multi-channel mode.
        fc = 1 if getattr(self, '_multi_channel_mode', False) else 0
        item = self.table.item(row, fc)
        if item is None:
            return
        fname = item.text()
        entry = self._entry_from_display_name(fname)
        if not entry:
            return
        filepath = self._entry_filepath(entry)
        row_idx  = self._entry_row_index(entry)

        # 파일명으로 결과 조회 (행 인덱스가 아니라 → 정렬/순서 어긋나도 안전).
        # 멀티채널이면 같은 파일명이 채널마다 있을 수 있으니 클릭한 행의 채널까지 일치시킨다.
        ch_txt = self.table.item(row, 0).text() if fc == 1 else ''
        want_ch = int(ch_txt.replace('CH', '')) if ch_txt.startswith('CH') else None
        def _match(r):
            if r.get('File') != fname:
                return False
            return want_ch is None or int(r.get('Channel', 1)) == want_ch
        _res = (self.results[row] if (row < len(self.results) and _match(self.results[row]))
                else next((r for r in self.results if _match(r)), None))
        if _res is not None:
            params = _res.get('Params')
            if params is None:
                return

            # 클릭한 결과의 채널로 Monitor 표시채널을 맞춰 채널필터에 막히지 않게 한다.
            try:
                ch = int(params.get('channel', _res.get('Channel', 1)))
                if hasattr(self.monitor, 'cb_fit_channel'):
                    self.monitor.cb_fit_channel.setCurrentIndex(max(0, min(ch - 1, self.monitor.cb_fit_channel.count() - 1)))
            except Exception:
                pass

            try:
                f_min, f_max = int(self.txt_min.text()), int(self.txt_max.text())

                # For Araon Mega-Matrix entries use HK loader to get the correct row
                if isinstance(entry, tuple):
                    pixel_idx, intensity_raw, _, _, _ = DataIO.load_measurement_with_hk(
                        filepath, f_min, f_max, row_index=row_idx)
                else:
                    pixel_idx, intensity_raw = DataIO.load_measurement(filepath, f_min, f_max)
                
                intensity_fit, _, intensity_poly, _, _ = self.engine.get_model_components(
                    pixel_idx, 
                    shifts=params['shifts'], 
                    squeezes=params['squeezes'], 
                    gas_coeffs=params['gas_coeffs'], 
                    poly_coeffs=params['poly_coeffs'],
                    etalon_amp=params.get('etalon_amp', 0.0),
                    etalon_freq=params.get('etalon_freq', 0.0),
                    etalon_phase=params.get('etalon_phase', 0.0)
                )
                
                self.monitor.tabs.setCurrentIndex(0) 
                
                self.monitor.update_spectrum(
                    pixel_idx, intensity_raw, intensity_fit, intensity_poly, params, f"{fname} (Replay)"
                )
            except Exception as e: 
                print(f"Double-click viewer failed to load: {e}")
                
    def on_table_single_click(self, row, col):
        # 결과가 있으면 클릭만으로 그 스캔 fit 그래프(리플레이) 표시; 없으면 기존 raw 뷰어.
        fc = 1 if getattr(self, '_multi_channel_mode', False) else 0
        if 0 <= row < self.table.rowCount() and self.table.item(row, fc) is not None:
            fname = self.table.item(row, fc).text()
            if any(r.get('File') == fname for r in self.results):
                self.on_table_double_click(row, col)
                return
        if self.monitor.tabs.currentIndex() == 3 and self.monitor.cb_view.currentIndex() == 0:
            self.refresh_viewer()
            
    def refresh_viewer(self):
        """Updates the fast viewer tab with raw measurement or reference data."""
        idx = self.monitor.cb_view.currentIndex()
        # Target fit band (nm) — used to zoom the reference view to the fit window.
        try:
            band = (self.spin_fit_start_nm.value(), self.spin_fit_end_nm.value())
        except Exception:
            band = None

        if idx == 0: # Measurement Data
            row = self.table.currentRow()
            if row < 0 or row >= self.table.rowCount():
                return

            fc = 1 if getattr(self, '_multi_channel_mode', False) else 0
            it = self.table.item(row, fc)
            if it is None:
                return
            fname = it.text()
            entry = self._entry_from_display_name(fname)
            if entry:
                fp  = self._entry_filepath(entry)
                ri  = self._entry_row_index(entry)
                try:
                    if isinstance(entry, tuple):
                        pixel_idx, intensity_raw, _, _, _ = DataIO.load_measurement_with_hk(fp, pixel_min=0, row_index=ri)
                    else:
                        pixel_idx, intensity_raw = DataIO.load_measurement(fp, pixel_min=0)
                    self.monitor.plot_viewer(pixel_idx, intensity_raw, f"Meas: {fname}", 'b')
                except Exception as e:
                    print(f"Viewer load failed: {e}")
        else: # Reference Data
            ref_name = self.monitor.cb_view.currentText().replace("Ref: ", "")
            is_raw = self.monitor.chk_raw.isChecked() 
            
            if is_raw and ref_name in self.engine.raw_references:
                y = self.engine.raw_references[ref_name]
                self.monitor.plot_viewer(np.arange(len(y)), y, f"Ref (RAW): {ref_name}", 'r', style='.', xband=band)
            elif ref_name in self.engine.interpolators:
                y = self.engine.interpolators[ref_name](np.arange(len(self.engine.raw_references[ref_name])))
                self.monitor.plot_viewer(np.arange(len(y)), y, f"Ref (Conv): {ref_name}", 'r', style='-', xband=band)


    def save_scenario(self):
        """
        Serializes the current fit configuration to a JSON file.

        Everything needed to reproduce a run is stored:
          - Reference file paths and their 10^exponent multipliers
          - Wavelength calibration file path
          - Pixel range, polynomial degree, step limit
          - Shift/Squeeze mode constraints per gas (ref_props)
          - Tikhonov λ, Robust flag, Kalman Q and R

        The JSON can be reloaded via load_scenario() to instantly restore the
        entire setup including auto-locking the references.
        """
        # 1. Extract gas list and basic info
        gas_list_str = "_".join(self.engine.gas_list) if hasattr(self, 'engine') and self.engine.gas_list else "NoRefs"
        f_min = self.txt_min.text()
        f_max = self.txt_max.text()
        poly = self.spin_poly_deg.value()
        
        # Prepare new parameter info for filename
        lam_val = self.spin_lambda.value()
        robust_str = "Robust" if self.chk_robust.isChecked() else "Std"
        
        # e.g., FitSet_NO2_H2O_1453-1646px_Poly4_L0.0001_Robust.json
        default_fname = f"FitSet_{gas_list_str}_{f_min}-{f_max}px_Poly{poly}_L{lam_val:g}_{robust_str}.json"

        # 2. Collect existing data
        refs_data = []
        if hasattr(self, 'ref_widgets'):
            for rw in self.ref_widgets:
                if rw['n'].text() and rw['fp']:
                    refs_data.append({
                        "name": rw['n'].text(),
                        "path": rw['fp'],
                        "mult": rw['mult'].value()
                    })

        scenario_data = {
            "wl_path": getattr(self, 'loaded_wl_path', ""), 
            "refs": refs_data,                              
            "f_min": f_min,
            "f_max": f_max,
            "poly_deg": poly,
            "step_limit": getattr(self, 'spin_step_limit', None).value() if hasattr(self, 'spin_step_limit') else 0.5,
            "ref_props": getattr(self, 'ref_props', {}),
            "tikhonov_lambda": lam_val,
            "use_robust": self.chk_robust.isChecked(),
            "kalman_q": self.spin_kalman_q.value() if hasattr(self, 'spin_kalman_q') else 0.0005,
            "kalman_r": self.spin_kalman_r.value() if hasattr(self, 'spin_kalman_r') else 0.050
        }

        # 3. Open file save dialog
        _start = os.path.join(self._dlg_dir('scenario'), default_fname) if self._dlg_dir('scenario') else default_fname
        path, _ = QFileDialog.getSaveFileName(self, "Save Fit Scenario", _start, "JSON Files (*.json)")
        self._dlg_dir('scenario', path)
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(scenario_data, f, indent=4)
                QMessageBox.information(self, "Success", f"Scenario saved!\nFile: {os.path.basename(path)}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Save Failed:\n{e}")

    def load_scenario(self):
        """
        Restores a saved fit configuration from a JSON file.

        Full automation sequence:
          1. Restore all numeric UI parameters (pixel range, poly, lambda, etc.)
          2. Auto-load the wavelength calibration file (if the path still exists)
          3. Add each reference file back to the UI list with its multiplier
          4. Auto-click 'Lock' to commit references to the engine

        After load_scenario() the user only needs to click 'Load Data' then 'RUN'.
        """
        path, _ = QFileDialog.getOpenFileName(self, "Load Fit Scenario", self._dlg_dir('scenario'), "JSON Files (*.json)")
        if not path: return
        self._dlg_dir('scenario', path)
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                scenario = json.load(f)
                
            # 1. Restore UI parameters
            self.txt_min.setText(str(scenario.get("f_min", "")))
            self.txt_max.setText(str(scenario.get("f_max", "")))
            self.spin_poly_deg.setValue(scenario.get("poly_deg", 3))
            if hasattr(self, 'spin_step_limit'):
                self.spin_step_limit.setValue(scenario.get("step_limit", 0.5))
            self.ref_props = scenario.get("ref_props", {})
            
            # Restore lambda and robust settings
            if hasattr(self, 'spin_lambda'):
                self.spin_lambda.setValue(scenario.get("tikhonov_lambda", 0.0))
            if hasattr(self, 'chk_robust'):
                self.chk_robust.setChecked(scenario.get("use_robust", False))
            if hasattr(self, 'spin_kalman_q'):
                self.spin_kalman_q.setValue(scenario.get("kalman_q", 0.0005))
            if hasattr(self, 'spin_kalman_r'):
                self.spin_kalman_r.setValue(scenario.get("kalman_r", 0.050))
            
            # 🌟 2. Auto-load wavelength file
            wl_path = scenario.get("wl_path", "")
            if wl_path and os.path.exists(wl_path):
                self.load_wavelength_cal(auto_path=wl_path) 
                
            # 🌟 3. Auto-load references
            refs = scenario.get("refs", [])
            if refs:
                # Clear existing reference UI
                if hasattr(self, 'ref_widgets'):
                    for rw in self.ref_widgets:
                        rw['w'].deleteLater()
                    self.ref_widgets.clear()
                self.engine.clear_engine()
                
                # Add gases one by one from scenario
                for ref in refs:
                    if os.path.exists(ref['path']):
                        self.add_ref_row(name=ref['name'], path=ref['path'])
                        self.ref_widgets[-1]['mult'].setValue(ref.get('mult', 0))
                        
                # 🌟 4. Auto-click 'Lock' to finalize engine setup!
                self.lock_ref()
                
                QMessageBox.information(self, "Auto-Load Success", 
                                        "🚀 [Full-Auto Mode Activated]\n"
                                        "Wavelengths, References, Locks, and Parameters have all been automatically configured!\n"
                                        "You can now simply [Load Data] and hit RUN!")
            else:
                QMessageBox.information(self, "Success", "📂 Scenario parameters loaded successfully!")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load scenario:\n{e}")
 