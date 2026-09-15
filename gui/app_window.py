import os
import re
import copy
import math
import datetime
import json
import warnings
import numpy as np
import pandas as pd
import pyqtgraph as pg
pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')


# [PyQt6] Modules
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QFileDialog,
                             QTableWidget, QTableWidgetItem, QMessageBox,
                             QProgressBar, QGroupBox, QLineEdit, QScrollArea, QDialog,
                             QComboBox, QSplitter, QTabWidget, QTabBar, QDoubleSpinBox, QSpinBox,
                             QCheckBox, QMenu)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QColor, QShortcut, QKeySequence

from core.engine import UniversalEngine
from .worker import AnalysisWorker, AlphaExportWorker
from .test_fit_dialog import TestFitDialog
from core.data_io import DataIO
from core.paths import (WV_CAL_DIR, DEFAULT_OUTPUT_DIR, DEFAULT_CAMPAIGN,
                        resolve_ref_path, out_path as _out_path,
                        campaign_dir as _campaign_dir, special_dir as _special_dir)
from core.__version__ import __version__
from core import run_meta
from .ui_dialogs import *
from .app_window_policy import _scenario_gas_policy, _channel_worker_gas_policy
from .app_window_cavity import CavityTabMixin          # §3
from .app_window_inputs import InputsAlphaMixin       # §4~§6
from .app_window_fitsetup import FitSetupMixin        # §7~§9
from .app_window_dataload import DataLoadMixin        # §10
from .app_window_run import AnalysisRunMixin          # §11


class CAESARAnalyzer(CavityTabMixin, InputsAlphaMixin, FitSetupMixin,
                     DataLoadMixin, AnalysisRunMixin, QMainWindow):
    """
    Main Window Controller for Augur v1.0 (CAESAR 분석 소프트웨어, 구 "CAESAR Pro").
    Integrates and commands all modules (Engine, Generators, Calibrations, Worker Threads, and Monitors).
    """
    # ══════════════════════════════════════════════════════════════════════
    #  CAESARAnalyzer — 메서드 목차 (각 섹션은 "§N" 으로 검색)
    # ══════════════════════════════════════════════════════════════════════
    #   §1  Init & UI 구성 (init_ui, showEvent, shortcuts)
    #   §2  Setup 탭: daily-run + R/Leff 차트
    #   §3  Cavity 탭 + FWHM/ILS 검증  -> gui/app_window_cavity.py (CavityTabMixin)
    #   §4  입력: I0 / dark / offset / flags  -> gui/app_window_inputs.py
    #   §5  알파 생성 (export + generator)  -> gui/app_window_inputs.py
    #   §6  I0 / R 진단 (auto-extract, diagnostic plot)  -> gui/app_window_inputs.py
    #   §7  다이얼로그 런처: ref / R / wavecal  -> gui/app_window_fitsetup.py
    #   §8  Test Fit (탭1 자동 최적화+Apply / 탭2 1-scan 미리보기 — gui/test_fit_dialog.py)  -> gui/app_window_fitsetup.py
    #   §9  핏 범위 + 레퍼런스 관리  -> gui/app_window_fitsetup.py
    #   §10 데이터 로드 + 채널 분배  -> gui/app_window_dataload.py
    #   §11 분석 실행 / 워커 / autosave / closeEvent  -> gui/app_window_run.py
    #   §12 결과 테이블 / QC / fast 렌더
    #   §13 저장 + 결과뷰어 연동
    #   §14 채널 탭 + 시나리오 config
    # ══════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════
    # §1  Init & UI 구성 (init_ui, showEvent, shortcuts)
    # ══════════════════════════════════════════════════════════════════════
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
        self.setWindowTitle(f'Augur v{__version__}')
        # 시작 크기만 모니터 작업영역 안으로 제한(작은 화면에서 잘리지 않게).
        # setMaximumSize로 잠그면 '최대화' 자체가 막히므로 쓰지 않는다 —
        # 내용발 창 팽창은 왼쪽 스크롤(AsNeeded)이 이미 차단함.
        try:
            from PyQt6.QtGui import QGuiApplication
            avail = QGuiApplication.primaryScreen().availableGeometry()
            w = min(int(1400 * s), avail.width() - 40)
            h = min(int(850 * s), avail.height() - 60)
            self.resize(w, h)
        except Exception:
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
        # 시작 시 스크롤 없이 화면에 들어오도록 여백/간격 압축
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(3)
        self._left_col = left_layout   # α 파이프라인을 분석 영역으로 합치기 위해 참조 보관

        # ── 채널 탭 바 ─────────────────────────────────────────────────
        # 채널마다 독립 설정(references/wavecal/parameters/fit range)을 두고 병렬 피팅.
        # 겉은 탭, 속은 '현재 채널 설정 갈아끼우기'(_capture/_apply_config 재사용).
        self._channel_configs = {1: None}   # ch -> config dict(스냅샷)
        self._channel_files = {1: []}        # ch -> 그 채널이 들고 있는 데이터 파일 리스트(자동분배 안 함)
        self._active_channel = 1
        self._switching_channel = False

        # 캠페인 = 산출물의 최상위 스코프(채널보다 바깥) → 채널 탭 위에 따로 한 줄.
        # 저장 경로 output/{campaign}/{YYYY-MM-DD}/{kind}/ 의 첫 조각이 된다.
        _camp_bar = QHBoxLayout()
        _camp_bar.addWidget(QLabel("Campaign:"))
        self._ed_campaign = QLineEdit()
        self._ed_campaign.setPlaceholderText(DEFAULT_CAMPAIGN)
        self._ed_campaign.setToolTip(
            "Campaign name — the top-level folder for everything this measurement produces\n"
            "(fitting / alpha / R / figures / calibration).  e.g. yeosu_2026, araon_2026\n"
            "Letters, digits, _ and - only; other characters become '_'.\n"
            "Empty = 'default'.  Remembered between sessions.")
        self._ed_campaign.setText(
            self._qsettings.value("campaign", "", type=str))
        self._ed_campaign.editingFinished.connect(
            lambda: self._qsettings.setValue(
                "campaign", self._ed_campaign.text().strip()))
        _camp_bar.addWidget(self._ed_campaign, 1)
        left_layout.addLayout(_camp_bar)

        _chtab_bar = QHBoxLayout()
        self._channel_tabbar = QTabBar()
        self._channel_tabbar.setExpanding(False)
        i0 = self._channel_tabbar.addTab("CH1")
        self._channel_tabbar.setTabData(i0, 1)
        self._channel_tabbar.currentChanged.connect(self._on_channel_tab_changed)
        _chtab_bar.addWidget(self._channel_tabbar, 1)
        _btn_addc = QPushButton("+"); _btn_addc.setFixedWidth(int(30 * self._s))
        _btn_addc.setToolTip("Add channel (copy current channel settings to a new channel)")
        _btn_addc.clicked.connect(self._add_channel_tab)
        _btn_delc = QPushButton("X"); _btn_delc.setFixedWidth(int(30 * self._s))
        _btn_delc.setToolTip("Delete current channel")
        _btn_delc.clicked.connect(self._del_channel_tab)
        _chtab_bar.addWidget(_btn_addc); _chtab_bar.addWidget(_btn_delc)
        _chtab_bar.addWidget(QLabel("Label:"))
        self._ed_ch_datalabel = QLineEdit()
        self._ed_ch_datalabel.setFixedWidth(int(80 * self._s))
        self._ed_ch_datalabel.setPlaceholderText("auto")
        self._ed_ch_datalabel.setToolTip(
            "Default: auto-distributed by alpha header channel number (# channel=N) → leave empty (campaign-independent).\n"
            "Override label for special cases only: maps alpha matching filename/header label/'ch{N}' to this channel.")
        _chtab_bar.addWidget(self._ed_ch_datalabel)
        _chtab_bar.addWidget(QLabel("Time shift:"))
        self.spin_time_shift = QDoubleSpinBox()
        self.spin_time_shift.setRange(-24.0, 24.0)
        self.spin_time_shift.setDecimals(1)
        self.spin_time_shift.setSingleStep(1.0)
        self.spin_time_shift.setValue(0.0)
        self.spin_time_shift.setSuffix(" h")
        self.spin_time_shift.setFixedWidth(int(72 * self._s))
        self.spin_time_shift.setToolTip(
            "Hours to add to this channel's timestamps in the output (result Time·conc tab).\n"
            "Pure time shift — no timezone labels. 0 = leave times exactly as recorded.\n"
            "e.g. instrument logged local time but you want UTC output → enter the negative of\n"
            "your UTC offset (Korea local = UTC+9 → enter −9). Half-hours (e.g. −9.5) allowed.")
        _chtab_bar.addWidget(self.spin_time_shift)
        _chtab_bar.addWidget(QLabel("Gas T:"))
        self.spin_gas_temp = QDoubleSpinBox()
        self.spin_gas_temp.setRange(0.0, 600.0)
        self.spin_gas_temp.setDecimals(0)
        self.spin_gas_temp.setValue(0.0)
        self.spin_gas_temp.setFixedWidth(int(60 * self._s))
        self.spin_gas_temp.setToolTip(
            "Actual gas temperature of this channel (°C) — for ppb density (n_air). 0 = auto (recommended).\n"
            "auto: reads per-channel measured cell gas temperature from HK on raw fit (tempcell, CH1≈34/CH2≈31.5°C)\n"
            "(confirmed 2026-06-10: tempcell = gas temperature through the cell. 75°C is the cell-heater setpoint, unused).\n"
            "Note: Hot alpha files generated before this fix may have 75°C baked into the T_C column\n"
            "→ when fitting those, enter the measured value here manually or regenerate the alpha.")
        _chtab_bar.addWidget(self.spin_gas_temp)
        # L4: 시나리오(전 채널 핏세팅) 로드/저장 — 분석의 출발점이라 왼쪽 상단 상주
        _btn_scn_load = QPushButton("Load")
        _btn_scn_load.setFixedWidth(int(30 * self._s))
        _btn_scn_load.setToolTip("Load fit scenario (all channels)")
        _btn_scn_load.clicked.connect(self.load_scenario)
        _chtab_bar.addWidget(_btn_scn_load)
        _btn_scn_save = QPushButton("Save")
        _btn_scn_save.setFixedWidth(int(30 * self._s))
        _btn_scn_save.setToolTip("Save fit scenario (all channels)")
        _btn_scn_save.clicked.connect(self.save_scenario)
        _chtab_bar.addWidget(_btn_scn_save)
        left_layout.addLayout(_chtab_bar)

        # --- 1. Reference Management Section ---
        grp_ref = QGroupBox("References")
        grp_ref.setMinimumHeight(int(110 * self._s))   # 내부 스크롤 있음 — 과대 고정높이가 화면을 밀어내던 것 축소
        lay_ref = QVBoxLayout()

        # Reference List Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(int(70 * self._s))
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
        btn_mask = QPushButton("Mask")
        btn_mask.clicked.connect(self.open_mask_dialog)
        btn_mask.setStyleSheet("color: #cc0000; font-weight: bold;") 
        
        layout_load.addWidget(btn_batch)
        layout_load.addWidget(btn_add)
        layout_load.addWidget(btn_mask)
        lay_ref.addLayout(layout_load)
        
        # Lock References Button (L5: dirty면 빨강으로 강조)
        btn_lock = QPushButton("Lock References (Commit)")
        btn_lock.clicked.connect(self.lock_ref)
        btn_lock.setStyleSheet("font-weight: bold; padding: 5px;")
        self._btn_lock_ref = btn_lock
        self._refs_dirty = False
        lay_ref.addWidget(btn_lock)
        
        # ILS 콘볼루션 UI 제거: Stage2 레퍼런스가 이미 ILS 적용됨 — 이중 콘볼루션
        # 위험만 있던 섹션이라 토글 버튼(_btn_toggle_ils)·클로저는 들어냈다.
        # 아래 위젯(spin_fwhm_nm 등)은 FWHM 자동계산 의존성 때문에 '생성만' 유지하고,
        # 영구히 숨긴 컨테이너에 담아둔다(패널에 표시 안 됨).
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

        grp_ref.setLayout(lay_ref)
        left_layout.addWidget(grp_ref)
        
        # --- 2. Fit Range & Calibration Section ---
        grp_set = QGroupBox("Fit Range")
        lay_set = QVBoxLayout()
        
        # Pixel-based Selection
        layout_px = QHBoxLayout()
        btn_load_wl = QPushButton("Load X-axis")
        btn_load_wl.clicked.connect(self.load_wavelength_cal)
        layout_px.addWidget(btn_load_wl)

        # 현재 채널에 로드된 wavecal 파일명 상시 표시 — "어느 칼리브로 핏 중인지"가
        # 안 보여서 생긴 0608/0523 오정렬 사고의 재발 방지(채널 전환 시 자동 갱신).
        # 긴 파일명이 패널 폭을 밀어내지 않게: 고정폭(min=max) + 중간 생략(전체 경로는 툴팁).
        # ※ SizePolicy.Ignored는 폭을 0으로 접어 라벨이 사라지므로 쓰지 않는다.
        self.lbl_wavecal = QLabel("wavecal: none")
        self.lbl_wavecal.setStyleSheet("color: #B71C1C; font-weight: bold; padding: 2px;")
        self.lbl_wavecal.setToolTip("Wavelength calibration loaded for this channel tab. Red = not loaded.")
        self.lbl_wavecal.setFixedWidth(int(180 * self._s))
        layout_px.addWidget(self.lbl_wavecal)

        self.lbl_fwhm_display = QLabel("FWHM: —")
        self.lbl_fwhm_display.setStyleSheet("color: #757575; font-weight: bold; padding: 3px;")
        self.lbl_fwhm_display.setFixedWidth(int(85 * self._s))
        layout_px.addWidget(self.lbl_fwhm_display)
        layout_px.addStretch(1)
        # 이 행(layout_px)은 이제 calib만: Load X-axis · wavecal · FWHM
        lay_set.addLayout(layout_px)

        # Px 입력칸은 아래 범위 행(layout_nm)으로 이동 — 여기선 위젯만 생성
        self.txt_min = QLineEdit("0")
        self.txt_min.setFixedWidth(int(46 * self._s))
        self.txt_max = QLineEdit("2047")
        self.txt_max.setFixedWidth(int(46 * self._s))
        btn_sel = QPushButton("Vis.")
        btn_sel.setToolTip("Vis. Select — drag range on the spectrum")
        btn_sel.clicked.connect(self.open_selector)
        
        # Fit 범위(nm) — 현재 채널 탭의 범위. 채널별 독립 설정(refs/wavecal/범위)은 좌측 채널 탭으로.
        layout_nm = QHBoxLayout()
        layout_nm.addWidget(QLabel("nm"))
        self.spin_fit_start_nm = QDoubleSpinBox()
        self.spin_fit_start_nm.setRange(200, 1000)
        self.spin_fit_start_nm.setDecimals(1)
        self.spin_fit_start_nm.setValue(435.0)
        self.spin_fit_start_nm.setMaximumWidth(int(58 * self._s))
        layout_nm.addWidget(self.spin_fit_start_nm)
        layout_nm.addWidget(QLabel("~"))
        self.spin_fit_end_nm = QDoubleSpinBox()
        self.spin_fit_end_nm.setRange(200, 1000)
        self.spin_fit_end_nm.setDecimals(1)
        self.spin_fit_end_nm.setValue(480.0)
        self.spin_fit_end_nm.setMaximumWidth(int(58 * self._s))
        layout_nm.addWidget(self.spin_fit_end_nm)

        # 'nm 범위 적용' 버튼 제거 — 스핀 수정 완료 시 자동으로 px 동기화
        self.spin_fit_start_nm.editingFinished.connect(self._auto_apply_nm)
        self.spin_fit_end_nm.editingFinished.connect(self._auto_apply_nm)

        # px 입력칸 — nm 핏범위 바로 뒤 (R창과 위치 스왑)
        layout_nm.addWidget(QLabel(" px"))
        layout_nm.addWidget(self.txt_min)
        layout_nm.addWidget(QLabel("~"))
        layout_nm.addWidget(self.txt_max)

        layout_nm.addSpacing(12)
        layout_nm.addWidget(QLabel("Unit:"))
        self.cb_fit_unit = QComboBox()
        self.cb_fit_unit.addItems(["nm", "px"])
        self.cb_fit_unit.setToolTip(
            "nm: fit by range (nm). px: fit by Min/Max (pixels) above.\n"
            "Reference scenarios (e.g. Cold 775-1550) reproduce pixel indices exactly when set to px.\n"
            "For alpha fitting, px slices the alpha to that pixel range before fitting.")
        self.cb_fit_unit.setFixedWidth(int(50 * self._s))
        layout_nm.addWidget(self.cb_fit_unit)

        layout_nm.addWidget(btn_sel)
        layout_nm.addStretch(1)
        lay_set.addLayout(layout_nm)

        # F2: 핏 단위가 진짜 모드 스위치 — px 모드면 px칸 활성/nm칸 비활성,
        # nm 모드면 nm칸 활성/px칸은 자동계산 표시(비활성). 적용 버튼 불필요.
        def _on_fit_unit_changed(*_):
            is_px = (self.cb_fit_unit.currentText() == 'px')
            self.txt_min.setEnabled(is_px)
            self.txt_max.setEnabled(is_px)
            self.spin_fit_start_nm.setEnabled(not is_px)
            self.spin_fit_end_nm.setEnabled(not is_px)
            if not is_px:
                self._auto_apply_nm()   # nm 모드 진입 시 px 자동 동기화
        self.cb_fit_unit.currentTextChanged.connect(_on_fit_unit_changed)
        _on_fit_unit_changed()

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

        # 4열 그리드(라벨+필드 쌍) — 한 줄에 위젯을 길게 늘어놓아 가로폭이
        # 화면을 넘던 것을 행렬로 재배치 (기능 숨김 없이 전부 보이게).
        from PyQt6.QtWidgets import QGridLayout
        _pg = QGridLayout()
        _pg.setHorizontalSpacing(3)
        _pg.setVerticalSpacing(3)

        self.spin_step_limit = QDoubleSpinBox()
        self.spin_step_limit.setRange(0.01, 10.0)
        self.spin_step_limit.setSingleStep(0.1)
        self.spin_step_limit.setDecimals(2)
        self.spin_step_limit.setValue(0.5)
        self.spin_step_limit.setToolTip("Maximum pixels that can be moved per frame")

        self.spin_poly_deg = QSpinBox()
        self.spin_poly_deg.setRange(0, 10)
        self.spin_poly_deg.setValue(3)

        self.spin_lambda = QDoubleSpinBox()
        self.spin_lambda.setRange(0.0, 10.0)
        self.spin_lambda.setSingleStep(0.0001)
        self.spin_lambda.setDecimals(6)
        self.spin_lambda.setValue(0.0000)
        self.spin_lambda.setToolTip("Ridge Penalty: 0 = Off, 1e-4 = Monitoring")

        self.chk_robust = QCheckBox("Robust")
        self.chk_robust.setToolTip("Robust (IRLS): auto-ignore spike noise and cosmic rays")
        self.chk_robust.setChecked(False)

        self.chk_allow_neg = QCheckBox("± Neg")
        self.chk_allow_neg.setToolTip(
            "Checked: gas coefficient lower bound 0→−∞ (NNLS off). Noise of near-zero gases can go negative,\n"
            "removing positive-rectification bias → unbiased PNs difference. Default = on (unbiased).")
        self.chk_allow_neg.setChecked(True)

        self.ref_props = {}
        btn_props = QPushButton("Properties")
        btn_props.setStyleSheet("font-weight: bold;")
        btn_props.clicked.connect(self.open_ref_properties)

        self.spin_rms_thresh = QDoubleSpinBox()
        self.spin_rms_thresh.setRange(1.0, 50.0)
        self.spin_rms_thresh.setSingleStep(1.0)
        self.spin_rms_thresh.setDecimals(1)
        self.spin_rms_thresh.setValue(10.0)
        self.spin_rms_thresh.setToolTip(
            "OK RMS Threshold(%): OK when RMS residual < (signal mean × threshold).\n"
            "10% = standard DOAS quality criterion.\n"
            "Lower = stricter. Raise only if data is extremely noisy.")

        self.chk_qc = QCheckBox("QC")
        self.chk_qc.setToolTip(
            "Checked: for 'Unstable' rows above the threshold (OK RMS Threshold) or below the SNR floor,\n"
            "set gas concentration to NaN to exclude from time-series·stats·export. Reason shown in Status.\n"
            "Rows where the fit failed (clouds/low light; e.g. NO2 runs negative while CHOCHO·H2O rise to offset)\n"
            "are filtered automatically. Standard DOAS QA/QC. Default = off (flag-only philosophy — enable to exclude).")
        self.chk_qc.setChecked(False)
        self.spin_qc_k = QDoubleSpinBox()
        self.spin_qc_k.setRange(0.0, 30.0)
        self.spin_qc_k.setDecimals(1)
        self.spin_qc_k.setSingleStep(1.0)
        self.spin_qc_k.setValue(8.0)
        self.spin_qc_k.setToolTip(
            "Auto QC sensitivity (0 = off). After the fit, from each channel's RMS distribution,\n"
            "threshold = 10^(median(log10 RMS) + K·MAD) auto-detects outliers → gas value NaN.\n"
            "No magic number needed. Lower K = stricter. Default 8 (removes runaways, keeps 96%).\n"
            "Entering a value in 'RMS max' takes priority (manual override).")
        self.spin_qc_rms = QDoubleSpinBox()
        self.spin_qc_rms.setRange(0.0, 1.0)
        self.spin_qc_rms.setDecimals(10)
        self.spin_qc_rms.setSingleStep(1e-8)
        self.spin_qc_rms.setValue(0.0)
        self.spin_qc_rms.setToolTip(
            "Absolute RMS max (0 = off). Rows above this are QC-excluded (gas value NaN).\n"
            "Key criterion for catching cloud/low-light fit failures (relative RMS misses these).\n"
            "Cold alpha recommended ≈ 5e-8 (normal max≈8e-8, runaway min≈8e-8). Tune from data.")
        self.spin_qc_snr = QDoubleSpinBox()
        self.spin_qc_snr.setRange(0.0, 1e9)
        self.spin_qc_snr.setDecimals(0)
        self.spin_qc_snr.setValue(0.0)
        self.spin_qc_snr.setToolTip("Additional SNR floor (0 = off). Rows below this are also QC-excluded.")
        self.chk_settle = QCheckBox("Settling")
        self.chk_settle.setToolTip(
            "Skip settling scans: drop the first N scans of EACH bin (purge transient right\n"
            "after a He/ZA cycle — cavity not yet refilled, so gas reads biased LOW).\n"
            "Non-destructive flag (Status='Settling', gas→NaN). Applied after the fit and on\n"
            "Reapply, so you can toggle N without refitting. Bin/scan# read from the File column.")
        self.chk_settle.setChecked(False)
        self.spin_settle_n = QSpinBox()
        self.spin_settle_n.setRange(0, 30)
        self.spin_settle_n.setValue(3)
        self.spin_settle_n.setToolTip("N scans dropped at each bin start (measured transient ≈ 3).")

        self.btn_reapply_qc = QPushButton("Reapply")
        self.btn_reapply_qc.setToolTip(
            "Reapply the following in order, without refitting:\n"
            "  1) OK RMS% — re-judge OK/Unstable when threshold changes\n"
            "  2) Kalman Q/R — recompute the _Smooth column with new Q/R\n"
            "3) Settling skip () — drop first N scans/bin (gas→NaN)\n"
            "  4) Auto QC (K/RMS max/SNR) — re-filter gas values to NaN\n"
            "Tikhonov λ and Robust change the fit matrix itself, so they need a refit.\n"
            "Restores original concentrations before re-filtering, so it's safe to press multiple times.")
        self.btn_reapply_qc.clicked.connect(self.reapply_qc)

        self.spin_kalman_q = QDoubleSpinBox()
        self.spin_kalman_q.setRange(0.0001, 1.0)
        self.spin_kalman_q.setSingleStep(0.0005)
        self.spin_kalman_q.setDecimals(4)
        self.spin_kalman_q.setValue(0.0005)
        self.spin_kalman_q.setToolTip(
            "Kalman Q — process noise / tracking speed\n"
            "Higher = tracks rapid changes faster (e.g. vehicle plumes)\n"
            "Lower = smoother output for stable ambient monitoring")
        self.spin_kalman_r = QDoubleSpinBox()
        self.spin_kalman_r.setRange(0.001, 1.0)
        self.spin_kalman_r.setSingleStep(0.01)
        self.spin_kalman_r.setDecimals(3)
        self.spin_kalman_r.setValue(0.050)
        self.spin_kalman_r.setToolTip(
            "Kalman R — measurement noise / smoothing strength\n"
            "Higher = stronger smoothing (stable background)\n"
            "Lower = faster response, less smoothing")

        # ── 그리드 배치: 4열(라벨·필드 쌍) × 4행 — 전 기능이 한 화면에 들어옴 ──
        def _lbl(t):
            l = QLabel(t); l.setStyleSheet("padding-right:2px;"); return l
        # ── BASIC (항상 보임): 실제 핏 결과에 직접 영향 주는 것만 ──
        # r0
        _pg.addWidget(_lbl("Step"), 0, 0); _pg.addWidget(self.spin_step_limit, 0, 1)
        _pg.addWidget(_lbl("Poly Deg"),  0, 2); _pg.addWidget(self.spin_poly_deg,  0, 3)
        _pg.addWidget(self.chk_allow_neg, 0, 4, 1, 2)
        _pg.addWidget(btn_props,         0, 6, 1, 2)
        # r1: QC 핵심 + 정착 스캔 제외(⏱ Settling, N)
        _pg.addWidget(self.chk_qc,        1, 0, 1, 2)
        _pg.addWidget(_lbl("K"),     1, 2); _pg.addWidget(self.spin_qc_k,      1, 3)
        _pg.addWidget(self.chk_settle,    1, 4); _pg.addWidget(self.spin_settle_n, 1, 5)
        _pg.addWidget(self.btn_reapply_qc,1, 6, 1, 2)
        # r2: 가스별 Shift/Squeeze 요약 한 줄 (테이블이 접혀 있을 때의 요약)
        from PyQt6.QtWidgets import QSizePolicy as _SPsq
        self.lbl_shsq = QLabel("Sh/Sq: (lock refs to show)")
        self.lbl_shsq.setStyleSheet("color:#555;")
        self.lbl_shsq.setToolTip("Per-gas Shift/Squeeze modes — expand the table below to edit")
        self.lbl_shsq.setSizePolicy(_SPsq.Policy.Ignored, _SPsq.Policy.Preferred)
        _pg.addWidget(self.lbl_shsq, 2, 0, 1, 8)
        lay_calib_main.addLayout(_pg)

        # ── 종 정책 테이블 상시 노출 (C1) ──────────────────────────────
        # shift/squeeze link 정책은 피팅 결과를 좌우하는 1급 결정인데 지금껏
        # ⚙️ Properties 팝업 안에만 있었고 메인엔 위 한 줄 요약뿐이었다.
        # 논문 방식("NO2를 맞추고 나머지는 그 값에 link")이 화면에서 안 보였다.
        # 팝업은 그대로 남는다 — 넓은 창 + Cancel 되돌리기가 필요한 경우가 있다.
        self._btn_shsq_tbl = QPushButton("▼ Reference policy (Shift / Squeeze / T / bands)")
        self._btn_shsq_tbl.setFlat(True)
        self._btn_shsq_tbl.setStyleSheet("text-align:left; color:#1565C0; font-weight:bold;")
        self._btn_shsq_tbl.setToolTip(
            "Per-gas fitting policy, always visible and editable here.\n"
            "Edits apply immediately (no OK button) — use  Properties if you want\n"
            "a wider view with Cancel.")
        self._btn_shsq_tbl.clicked.connect(self._toggle_shsq_table)
        lay_calib_main.addWidget(self._btn_shsq_tbl)

        from gui.ref_properties_dialog import RefPropertiesTable
        self.tbl_shsq = RefPropertiesTable([], {})
        self.tbl_shsq.setMinimumHeight(int(120 * self._s))
        self.tbl_shsq.setMaximumHeight(int(220 * self._s))
        self.tbl_shsq.changed.connect(self._on_shsq_table_changed)
        # 명시적 플래그 — isVisible()은 부모 탭이 숨으면 False라 토글이 어긋난다
        # (이 파일의 _adv_params_visible과 같은 방식).
        self._shsq_table_visible = True
        self.tbl_shsq.setVisible(True)
        lay_calib_main.addWidget(self.tbl_shsq)

        # ── ADVANCED (접이, 기본 닫힘): 우리 데이터엔 보통 불필요한 것 ──
        # Tikhonov λ(조건수 안정→0 권장), Robust(알파 60s평균이라 효과 작음·QC가 행단위 대체),
        # Kalman(핏이 아니라 사후평활 — 결과는 raw, _Smooth 컬럼만 생성), OK RMS%(자동 QC가 대체).
        self._adv_params_visible = False
        self._btn_adv_params = QPushButton("▶ Advanced (Tikhonov · Robust · Kalman · RMS%)")
        self._btn_adv_params.setStyleSheet(
            "text-align:left; color:#78909C; border:1px solid #ECEFF1; padding:2px 6px; font-size:11px;")
        lay_calib_main.addWidget(self._btn_adv_params)
        self._adv_params_container = QWidget()
        self._adv_params_container.setVisible(False)
        _apg = QGridLayout(self._adv_params_container)
        _apg.setHorizontalSpacing(3); _apg.setVerticalSpacing(3)
        _apg.setContentsMargins(0, 0, 0, 0)
        _apg.addWidget(_lbl("Tik λ"), 0, 0); _apg.addWidget(self.spin_lambda, 0, 1)
        _apg.addWidget(self.chk_robust, 0, 2, 1, 2)
        _apg.addWidget(_lbl("OK RMS%"), 0, 4); _apg.addWidget(self.spin_rms_thresh, 0, 5)
        _apg.addWidget(_lbl("Kal Q"), 1, 0); _apg.addWidget(self.spin_kalman_q, 1, 1)
        _apg.addWidget(_lbl("R"), 1, 2); _apg.addWidget(self.spin_kalman_r, 1, 3)
        lay_calib_main.addWidget(self._adv_params_container)

        def _toggle_adv_params():
            self._adv_params_visible = not self._adv_params_visible
            self._adv_params_container.setVisible(self._adv_params_visible)
            self._btn_adv_params.setText(
                ("▼ " if self._adv_params_visible else "▶ ")
                + "Advanced (Tikhonov · Robust · Kalman · RMS%)")
        self._btn_adv_params.clicked.connect(_toggle_adv_params)

        # 스핀박스 폭 제한
        for _sb, _w in [(self.spin_step_limit, 64), (self.spin_poly_deg, 50),
                        (self.spin_lambda, 90), (self.spin_rms_thresh, 60),
                        (self.spin_qc_k, 55), (self.spin_kalman_q, 80),
                        (self.spin_kalman_r, 70)]:
            _sb.setMaximumWidth(int(_w * self._s))

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
        grp_ctl = QGroupBox("Analysis (RUN)")
        lay_ctl = QVBoxLayout()
        
        # 한 줄: Load + RUN/STOP/Save (세로 공간 절약)
        layout_row1 = QHBoxLayout()
        btn_load = QPushButton("Load Data")
        btn_load.clicked.connect(self.load_data)
        layout_row1.addWidget(btn_load)
        self.b_run = QPushButton("RUN")
        self.b_run.clicked.connect(self.start_analysis)
        self.b_stop = QPushButton("STOP")
        self.b_stop.clicked.connect(self.stop_analysis)
        self.b_stop.setEnabled(False)
        self.b_save = QPushButton("Save")
        self.b_save.clicked.connect(self.save)
        layout_row1.addWidget(self.b_run)
        layout_row1.addWidget(self.b_stop)
        layout_row1.addWidget(self.b_save)

        layout_perf = QHBoxLayout()
        layout_perf.addWidget(QLabel("Update/N:"))
        self.spin_update = QSpinBox()
        self.spin_update.setRange(1, 1000)
        self.spin_update.setValue(10)
        self.spin_update.setMaximumWidth(int(60 * self._s))
        self.spin_update.setToolTip("Refresh plots every N scans")
        layout_perf.addWidget(self.spin_update)

        # Fitting mode: Fast (parallel) merges the old Normal+Turbo; Step replaces Observe.
        layout_perf.addWidget(QLabel("Mode:"))
        self.cb_display_mode = QComboBox()
        self.cb_display_mode.addItems(["Fast (parallel)", "Step (slow)"])
        self.cb_display_mode.setToolTip(
            "Fast: parallel multi-core fitting; results fill in as they arrive "
            "(no live per-scan spectrum view). Recommended.\n"
            "Step: sequential, 200ms/scan delay — inspect each fit one at a time.")
        self.cb_display_mode.setFixedWidth(int(120 * self._s))
        layout_perf.addWidget(self.cb_display_mode)

        layout_perf.addSpacing(8)
        self.chk_auto_save = QCheckBox("Auto-save")
        self.chk_auto_save.setToolTip(
            "Checked: when analysis finishes (after QC), auto-save with the existing filename rule without asking.\n"
            "Location = last Save folder (else Output\\fitting). Recommended for overnight runs.\n"
            "(autosave TSV is separate, for crash recovery — this is the formal result save)")
        self.chk_auto_save.setChecked(True)
        layout_perf.addWidget(self.chk_auto_save)
        layout_perf.addStretch(1)

        # (RUN 중 α 저장 옵션 제거 — α 생성은 Alpha Generator 팝업이 전담)
        lay_ctl.addLayout(layout_row1)
        lay_ctl.addLayout(layout_perf)
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
        # 왼쪽 패널을 스크롤로 감싸 기능이 늘어나도 화면(세로)을 넘지 않게 한다.
        # 내용이 화면보다 길면 패널 안에 세로 스크롤바가 생기고 창 크기는 안 커진다.
        _left_scroll = QScrollArea()
        _left_scroll.setWidgetResizable(True)
        _left_scroll.setWidget(left_widget)
        # 가로 스크롤바 AlwaysOff 금지: Off면 Qt가 '내용 최소폭만큼 패널을 넓혀야 한다'고
        # 판단해 내용이 넓어질 때(핏세팅 로드 등) 왼쪽이 오른쪽 그래프 영역을 침범한다.
        # AsNeeded면 내용이 넘칠 때 패널 안에 작은 가로 스크롤바가 생길 뿐 폭은 불변.
        _left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        _left_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # 시작 시 왼쪽이 좁게 접혀(스플리터 재분배) 사용자가 매번 늘려야 하던 것 방지.
        # 실제 폭은 showEvent에서 내용 실측(sizeHint)으로 정함 — 고정값(470)이 내용보다
        # 좁아 우측 버튼들(가스T/Properties/QC재적용/Save 등)이 잘리던 문제 해결.
        self._left_scroll = _left_scroll
        self._left_inner = left_widget
        splitter.addWidget(_left_scroll)
        splitter.setCollapsible(0, False)   # 왼쪽 패널이 0으로 접히는 것 방지
        
        # =========================================================
        # [Right] Monitor Tab Area
        # =========================================================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # Main Tab Widget
        self.main_tabs = QTabWidget()

        # Daily Run(Scenario + Setup Status) — 별도 탭 대신 Setup 상단으로 흡수
        self.daily_run_tab = QWidget()
        self.setup_daily_run_tab()

        # 모든 메인 탭을 스크롤 컨테이너로 격리 — 탭 내용의 최소크기(예: Setup 1808px)가
        # 창/스플리터로 전파돼 '로드할 때마다 화면이 넘치거나 뭉개지던' 전역 원인 차단.
        # 내용이 뷰포트보다 크면 탭 안에 스크롤바만 생기고 창 크기는 불변.
        self._tab_pages = {}   # 내용위젯 → 스크롤페이지 (setCurrentWidget 호환용)
        def _tab_scroll(widget):
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setWidget(widget)
            sa.setFrameShape(QScrollArea.Shape.NoFrame)
            self._tab_pages[widget] = sa
            return sa

        # Tab 0: Setup (Daily Run 흡수 + Tools/α파이프라인/Cavity/진단)
        self.setup_tab = QWidget()
        self.setup_cavity_tab()
        self.main_tabs.addTab(_tab_scroll(self.setup_tab), "Setup")

        # Tab 2: Analysis Monitor
        self.monitor = MonitorWidget(self.engine)
        self.main_tabs.addTab(_tab_scroll(self.monitor), "Analysis Monitor")

        # Tab 3: Result Viewer (저장된 R/α/레퍼런스/농도 결과 파일을 불러와 표시)
        from .ui_result_viewer import ResultViewerWidget
        self.result_viewer = ResultViewerWidget(self)
        self.main_tabs.addTab(_tab_scroll(self.result_viewer), "Result Lab")

        # Tab 4: Plot Maker (여러 결과를 메모리에 올려 자유 합성·시계열/산점도/Allan)
        from .ui_plot_maker import PlotMakerWidget
        self.plot_maker = PlotMakerWidget(self)
        # Plot Maker는 스크롤 영역으로 감싸지 않는다 — 플롯이 남는 공간을 채우는
        # 위젯이라, 스크롤로 감싸면 툴바가 여러 줄일 때 전체가 세로 스크롤돼 불편.
        # 직접 붙이면 툴바(상단 고정)+플롯(stretch)으로 스크롤 없이 한 화면에 들어온다.
        self.main_tabs.addTab(self.plot_maker, "Plot Maker")
        self._tab_pages[self.plot_maker] = self.plot_maker
        # 결과뷰어 → Plot Maker 브리지: 선택 파일을 선반에 싣고 탭 전환
        self.result_viewer.send_to_plotmaker.connect(
            lambda paths: (self.plot_maker.add_paths(paths),
                           self.main_tabs.setCurrentWidget(self._tab_pages[self.plot_maker])))
        # 결과뷰어·Plot Maker 탭에서는 왼쪽 분석패널을 접어 그래프가 전체 폭을 쓰게 한다.
        self.main_tabs.currentChanged.connect(self._on_main_tab_changed)

        right_layout.addWidget(self.main_tabs)
        
        # Keep Existing Signal Connections
        self.monitor.cb_view.currentIndexChanged.connect(self.refresh_viewer)
        self.monitor.roi_selected.connect(self.apply_roi_from_graph)

        splitter.addWidget(right_widget)
        # 시작 시 좌:우 분배 명시 — 왼쪽이 너무 좁게 시작해 사용자가 매번 스플리터를
        # 조정해야 하던 것 방지. 실제 창 크기가 확정되는 첫 show 이후에 적용해야
        # 초기 레이아웃 재계산에 덮어써지지 않는다(showEvent에서 1회).
        self._splitter = splitter
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self._splitter_inited = False

        self._setup_shortcuts()

    def showEvent(self, ev):
        super().showEvent(ev)
        if not getattr(self, '_splitter_inited', False):
            self._splitter_inited = True
            try:
                # 왼쪽 폭 = 내용 실측폭 그대로(+스크롤바 여유) → 어떤 DPI/배율에서도
                # 위젯이 잘리지 않게. 상한은 창의 55%(그래프 영역 확보). 세로 스크롤바
                # 폭까지 더해 가로 스크롤이 안 생기게 한다.
                sbw = self._left_scroll.verticalScrollBar().sizeHint().width() or 16
                need = self._left_inner.sizeHint().width() + sbw + 6
                _lw = min(need, int(self.width() * 0.55))
                _lw = max(_lw, int(360 * self._s))
                self._left_min_w = _lw          # 탭 복원 시 사용
                self._left_scroll.setMinimumWidth(_lw)
                self._splitter.setSizes([_lw, max(400, self.width() - _lw)])
            except Exception:
                pass
            # 첫 표시 직후 현재 탭 기준으로 좌패널 접힘 상태 동기화
            self._on_main_tab_changed(self.main_tabs.currentIndex())

    def _on_main_tab_changed(self, _idx):
        """결과뷰어/Plot Maker 탭에서는 왼쪽 분석패널을 접어 그래프에 전체 폭을 준다.
        다른 탭으로 돌아오면 원래 폭으로 복원. (사용자는 스플리터로 다시 조절 가능)"""
        if not getattr(self, "_splitter_inited", False):
            return
        page = self.main_tabs.currentWidget()
        wide_pages = (self._tab_pages.get(self.result_viewer),
                      self._tab_pages.get(self.plot_maker))
        if page in wide_pages:
            if not getattr(self, "_left_collapsed", False):
                self._saved_sizes = self._splitter.sizes()
                self._left_collapsed = True
            self._splitter.setCollapsible(0, True)
            self._left_scroll.setMinimumWidth(0)
            self._splitter.setSizes([0, max(400, self.width())])
        elif getattr(self, "_left_collapsed", False):
            self._left_collapsed = False
            self._splitter.setCollapsible(0, False)
            lw = getattr(self, "_left_min_w", int(360 * self._s))
            self._left_scroll.setMinimumWidth(lw)
            sizes = getattr(self, "_saved_sizes", None)
            self._splitter.setSizes(sizes if sizes else
                                    [lw, max(400, self.width() - lw)])

    def _setup_shortcuts(self):
        """Register keyboard shortcuts for common operations."""
        QShortcut(QKeySequence("F5"),      self).activated.connect(self.start_analysis)
        QShortcut(QKeySequence("Escape"),  self).activated.connect(self.stop_analysis)
        QShortcut(QKeySequence("Ctrl+S"),  self).activated.connect(self.save)

    # =========================================================
    # Tab 0: Daily Run
    # =========================================================
    # ══════════════════════════════════════════════════════════════════════
    # §2  Setup 탭: daily-run + R/Leff 차트
    # ══════════════════════════════════════════════════════════════════════
    def setup_daily_run_tab(self):
        """Build the Daily Run tab: scenario, setup status checklist, R trend charts."""
        lay = QVBoxLayout(self.daily_run_tab)

        # ── Scenario + Setup Status (R 표시는 Setup 탭 Cavity Diagnostics로 일원화) ──
        left_w = QWidget()
        left_v = QVBoxLayout(left_w)

        # (Fit Scenario 저장/로드 그룹 제거 — 왼쪽 패널 채널탭바 📋/💾 버튼으로 일원화, S2)

        grp_status = QGroupBox("Setup Status")
        grp_status.setStyleSheet("QGroupBox { font-weight: bold; color: #1565C0; }")
        lay_status = QVBoxLayout()

        self.lbl_st_wl    = QLabel("Wavelength calibration: not loaded")
        self.lbl_st_i0    = QLabel("I₀ (Zero-Air): not set (auto from ZA scans)")
        self.lbl_st_r     = QLabel("R-Curve: not loaded (auto from He scans)")
        self.lbl_st_refs  = QLabel("References: not locked")
        self.lbl_st_range = QLabel("Fit range: 0–2047 px (full sensor)")
        # 위 다섯은 "로드됐나"만 본다. 이건 "그날 데이터가 성립하나"를 본다 —
        # He 빠진 구간은 R(t)가 외삽되고 결과는 경로길이가 틀린 농도가 되는데
        # 위 다섯은 전부 초록불이다.
        self.lbl_st_audit = QLabel("Day audit: not run  (checks ZA/He cadence in raw)")

        for lbl in (self.lbl_st_wl, self.lbl_st_i0, self.lbl_st_r,
                    self.lbl_st_refs, self.lbl_st_range, self.lbl_st_audit):
            lbl.setStyleSheet("padding: 2px 6px; font-size: 11px;")
            lay_status.addWidget(lbl)

        _st_btns = QHBoxLayout()
        btn_refresh = QPushButton("Refresh Status")
        btn_refresh.clicked.connect(self._refresh_setup_status)
        _st_btns.addWidget(btn_refresh)
        self.btn_day_audit = QPushButton("Audit Day")
        self.btn_day_audit.setToolTip(
            "Scan the loaded raw files' ZA/He flag timeline and report missing or\n"
            "over-long gaps in the calibration sequence.\n"
            "A missing He block means R(t) is extrapolated across it — the resulting\n"
            "concentrations have the wrong path length, and nothing else on this\n"
            "checklist would notice.\n"
            "Read-only: it changes no data. Runs in the background (raw is ~2 GB/day).")
        self.btn_day_audit.clicked.connect(self._start_day_audit)
        _st_btns.addWidget(self.btn_day_audit)
        lay_status.addLayout(_st_btns)
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
                f"Wavelength: {wl.min():.2f}–{wl.max():.2f} nm  ({len(wl)} px)")
            self.lbl_st_wl.setStyleSheet("color: #2E7D32; padding: 2px 6px; font-size: 11px;")
            # Auto-correct txt_max if it still holds the default 2047 and wl is shorter
            try:
                n = len(wl)
                if int(self.txt_max.text()) >= n:
                    self.txt_max.setText(str(n - 1))
            except ValueError:
                pass
        else:
            self.lbl_st_wl.setText("Wavelength calibration: not loaded")
            self.lbl_st_wl.setStyleSheet("color: #c62828; padding: 2px 6px; font-size: 11px;")

        # 입력 종류 판별 — 알파면 I0/R가 이미 반영돼 있어 '해당 없음(✅)'으로 표시.
        _green = "color: #2E7D32; padding: 2px 6px; font-size: 11px;"
        _amber = "color: #e65100; padding: 2px 6px; font-size: 11px;"
        _gray = "color: #757575; padding: 2px 6px; font-size: 11px;"
        _is_alpha = False
        try:
            _f0 = self._entry_filepath(self.file_list[0]) if getattr(self, 'file_list', None) else None
            _is_alpha = bool(_f0) and DataIO._is_alpha_trace_format(_f0)
        except Exception:
            pass

        # I₀
        i0_ok = hasattr(self, 'i0_data') and self.i0_data is not None
        if i0_ok:
            self.lbl_st_i0.setText(
                f"I₀: loaded ({len(self.i0_data)} px,  mean={self.i0_data.mean():.1f})")
            self.lbl_st_i0.setStyleSheet(_green)
        elif _is_alpha:
            self.lbl_st_i0.setText("I₀: N/A  (already applied in alpha)")
            self.lbl_st_i0.setStyleSheet(_gray)
        else:
            self.lbl_st_i0.setText("I₀: auto from ZA scans during run")
            self.lbl_st_i0.setStyleSheet(_amber)

        # R-curve
        r_ok = hasattr(self, 'r_data') and self.r_data is not None
        if r_ok:
            r_arr = np.asarray(self.r_data, dtype=float)
            r_fin = r_arr[np.isfinite(r_arr)]
            if len(r_fin) > 0:
                r_med = float(np.median(r_fin))
                leff  = self.spin_d_len.value() / (1.0 - r_med)
                self.lbl_st_r.setText(
                    f"R: {r_med*100:.4f}%  Leff ≈ {leff:.0f} cm")
            else:
                self.lbl_st_r.setText("R: loaded (no finite values in pixel range)")
            self.lbl_st_r.setStyleSheet(_green)
            self._update_daily_r_chart()
        elif _is_alpha:
            self.lbl_st_r.setText("R: N/A  (already applied in alpha)")
            self.lbl_st_r.setStyleSheet(_gray)
        else:
            self.lbl_st_r.setText("R-Curve: auto from He scans during run")
            self.lbl_st_r.setStyleSheet("color: #e65100; padding: 2px 6px; font-size: 11px;")

        # References locked
        refs_ok = hasattr(self, 'engine') and len(self.engine.gas_list) > 0
        if refs_ok:
            self.lbl_st_refs.setText(
                f"References locked: {', '.join(self.engine.gas_list)}")
            self.lbl_st_refs.setStyleSheet("color: #2E7D32; padding: 2px 6px; font-size: 11px;")
        else:
            self.lbl_st_refs.setText("References: not locked  (lock before RUN)")
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
                    f"Fit range: px {fmin}–{fmax}  ({lo:.1f}–{hi:.1f} nm,  {rng} px)")
            else:
                self.lbl_st_range.setText(
                    f"Fit range: px {fmin}–{fmax}  ({rng} px)")
            self.lbl_st_range.setStyleSheet("color: #2E7D32; padding: 2px 6px; font-size: 11px;")
        except ValueError:
            self.lbl_st_range.setText("Fit range: invalid pixel values")
            self.lbl_st_range.setStyleSheet("color: #c62828; padding: 2px 6px; font-size: 11px;")

        self._render_day_audit()   # 캐시된 감사 결과는 Refresh로 지워지지 않는다

    # ── 측정일 감사 (D1) ───────────────────────────────────────────────
    _AUDIT_STYLE = {
        "PASS": "color: #2E7D32; padding: 2px 6px; font-size: 11px;",
        "WARN": "color: #e65100; padding: 2px 6px; font-size: 11px;",
        "FAIL": "color: #c62828; padding: 2px 6px; font-weight: bold; font-size: 11px;",
        "SKIP": "color: #757575; padding: 2px 6px; font-size: 11px;",
    }

    def _raw_days(self):
        """로드된 파일 중 **raw만** 날짜별로 묶는다 → [(YYYY-MM-DD, [경로…])].

        알파는 감사 대상이 아니다 — ZA는 I₀로, He는 R로 소비돼 알파 파일엔 안 남는다
        (`fit_optimizer_handoff.md` §12). 알파만 로드된 상태면 빈 목록이고 SKIP이 뜬다.
        """
        jobs = {}
        for entry in getattr(self, 'file_list', None) or []:
            try:
                fp = self._entry_filepath(entry)
            except Exception:
                continue
            if not fp or not os.path.exists(fp):
                continue
            m = re.match(r'^(\d{4}-\d{2}-\d{2})-\d+', os.path.basename(fp))
            if not m:
                continue
            try:
                if DataIO._is_alpha_trace_format(fp):
                    continue
            except Exception:
                pass
            jobs.setdefault(m.group(1), []).append(fp)
        return sorted((d, sorted(f)) for d, f in jobs.items())

    def _start_day_audit(self):
        """로드된 raw의 ZA/He 케이던스 감사를 백그라운드로 시작."""
        if getattr(self, '_audit_worker', None) is not None:
            return
        jobs = self._raw_days()
        if not jobs:
            self.lbl_st_audit.setText(
                "Day audit: no raw files loaded  "
                "(alpha input has no ZA/He blocks to check)")
            self.lbl_st_audit.setStyleSheet(self._AUDIT_STYLE["SKIP"])
            return
        from gui.r_workers import DayAuditWorker
        n = sum(len(f) for _d, f in jobs)
        self.btn_day_audit.setEnabled(False)
        self.lbl_st_audit.setText(
            f"Day audit: scanning {n} raw file(s) over {len(jobs)} day(s)...")
        self.lbl_st_audit.setStyleSheet(self._AUDIT_STYLE["SKIP"])
        w = DayAuditWorker(jobs)
        w.progress.connect(lambda d: self.lbl_st_audit.setText(f"Day audit: {d}…"))
        w.done.connect(self._on_day_audit_done)
        w.failed.connect(self._on_day_audit_failed)
        self._audit_worker = w
        w.start()

    def _on_day_audit_failed(self, msg):
        self._audit_worker = None
        self.btn_day_audit.setEnabled(True)
        self.lbl_st_audit.setText(f"Day audit: failed ({msg})")
        self.lbl_st_audit.setStyleSheet(self._AUDIT_STYLE["SKIP"])

    def _on_day_audit_done(self, reports):
        self._audit_worker = None
        self.btn_day_audit.setEnabled(True)
        self._day_audit = reports          # {date: AuditReport} — save()가 meta에 싣는다
        self._render_day_audit()
        worst = self._day_audit_worst()
        if worst in ("WARN", "FAIL"):
            # 조용히 지나가면 안 되는 발견이라 상태줄에도 남긴다(자동 차단은 하지 않음 —
            # 판정은 보고이고, RUN 여부는 사람이 정한다).
            lines = [f"{d}: {m}" for d, rep in sorted(reports.items())
                     for s, m in rep.messages if s in ("WARN", "FAIL")]
            self.status.setText(f"Day audit {worst} — " + " | ".join(lines[:3]))
            self.status.setStyleSheet(
                "color: %s; font-weight: bold;" % ("#c62828" if worst == "FAIL" else "#e65100"))

    def _day_audit_worst(self):
        rank = {"SKIP": 0, "PASS": 1, "WARN": 2, "FAIL": 3}
        reports = getattr(self, '_day_audit', None) or {}
        return max((r.status for r in reports.values()),
                   key=lambda s: rank.get(s, 0), default="SKIP")

    def _render_day_audit(self):
        """캐시된 감사 결과를 한 줄로. 결과가 없으면 안내만."""
        if not hasattr(self, 'lbl_st_audit'):
            return
        reports = getattr(self, '_day_audit', None)
        if not reports:
            if getattr(self, '_audit_worker', None) is None:
                self.lbl_st_audit.setText(
                    "Day audit: not run  (checks ZA/He cadence in raw)")
                self.lbl_st_audit.setStyleSheet(self._AUDIT_STYLE["SKIP"])
            return
        worst = self._day_audit_worst()
        bad = [(d, m) for d, rep in sorted(reports.items())
               for s, m in rep.messages if s in ("WARN", "FAIL")]
        if bad:
            d, m = bad[0]
            more = f"  (+{len(bad) - 1} more)" if len(bad) > 1 else ""
            txt = f"Day audit {worst}: {d} — {m}{more}"
        else:
            n_blk = sum(len(b) for rep in reports.values() for b in rep.blocks.values())
            txt = (f"Day audit {worst}: "
                   f"{len(reports)} day(s), {n_blk} ZA/He blocks, no gaps")
        self.lbl_st_audit.setText(txt)
        self.lbl_st_audit.setToolTip(
            "\n".join(f"{d}: {rep.summary()}" for d, rep in sorted(reports.items())))
        self.lbl_st_audit.setStyleSheet(self._AUDIT_STYLE.get(worst, self._AUDIT_STYLE["SKIP"]))

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

    def _update_daily_rt_chart(self, cold_results, hot_pns_results=None, hot_ans_results=None):
        """Populate the R time-series chart in Daily Run from R Calibrator results.

        Accepts both new format (cold_results = [{label,results,color},...])
        and legacy format (cold_results = list of result dicts).
        """
        if not hasattr(self, '_daily_rt_pw'):
            return
        self._daily_rt_pw.clear()
        self._daily_rt_pw.addLegend(offset=(10, 10))

        import datetime as _dt

        # Format detection
        if (isinstance(cold_results, list) and cold_results and
                isinstance(cold_results[0], dict) and 'results' in cold_results[0]):
            channels = cold_results   # new format
        else:
            channels = []
            for res, color, lbl in [
                (cold_results,    '#2196F3', 'Cold'),
                (hot_pns_results, '#FF6F00', 'Hot PNs'),
                (hot_ans_results, '#D32F2F', 'Hot ANs'),
            ]:
                if res:
                    channels.append({"label": lbl, "results": res, "color": color})

        def _plot_series(results, color, label):
            if not results:
                return
            pts = [(r['timestamp'], r['r_mean'])
                   for r in results
                   if r.get('r_mean') is not None and r.get('timestamp') is not None]
            if not pts:
                return
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

        for ch in channels:
            _plot_series(ch["results"], ch["color"], ch["label"])

        n = sum(len(ch["results"]) for ch in channels)
        self._daily_rt_pw.setTitle(f"R time series — {n} cycles")

    def _update_setup_rt_charts(self, cold_results, hot_pns_results=None,
                                hot_ans_results=None, out_dir=None):
        """Populate the R(t)/Leff(t) plots in the Setup tab Cavity Diagnostics panel.

        Accepts both new format (cold_results = [{label,results,color},...])
        and legacy format (cold_results = list of result dicts).
        """
        if not hasattr(self, '_setup_r_trend_pw'):
            return

        import datetime as _dt

        # Format detection
        if (isinstance(cold_results, list) and cold_results and
                isinstance(cold_results[0], dict) and 'results' in cold_results[0]):
            channels = cold_results   # new format: [{label, results, color}, ...]
        else:
            channels = []
            for res, color, lbl in [
                (cold_results,    '#2196F3', 'Cold'),
                (hot_pns_results, '#FF6F00', 'Hot PNs'),
                (hot_ans_results, '#D32F2F', 'Hot ANs'),
            ]:
                if res:
                    channels.append({"label": lbl, "results": res, "color": color})

        self._setup_r_trend_pw.clear()
        self._setup_r_trend_pw.addLegend(offset=(10, 10))
        self._setup_leff_pw.clear()
        self._setup_leff_pw.addLegend(offset=(10, 10))
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

        n = 0
        for ch in channels:
            results = ch["results"]
            color   = ch["color"]
            label   = ch["label"]
            ch_key  = label   # used for dat file path lookup
            if not results:
                continue
            kept_r = [r for r in results
                      if r.get('r_mean') is not None and r.get('timestamp') is not None]
            kept_l = [r for r in results
                      if r.get('leff_mean') is not None and r.get('timestamp') is not None]
            n += len(kept_r)
            if kept_r:
                ts_r = [_ts(r['timestamp']) for r in kept_r]
                rv   = [r['r_mean'] * 100 for r in kept_r]
                pdi  = self._setup_r_trend_pw.plot(
                    ts_r, rv, pen=pg.mkPen(color, width=2),
                    symbol='o', symbolSize=6, name=label)
                _register_clickable(pdi, kept_r, ch_key, color)
            if kept_l:
                ts_l  = [_ts(r['timestamp']) for r in kept_l]
                lv    = [r['leff_mean'] for r in kept_l]
                pdi_l = self._setup_leff_pw.plot(
                    ts_l, lv, pen=pg.mkPen(color, width=2),
                    symbol='s', symbolSize=6, name=label)
                _register_clickable(pdi_l, kept_l, ch_key, color)

        self._setup_r_trend_pw.setTitle(
            f"R time-series — {n} cycles  (click a point → R(λ) spectrum tab)")
        self._setup_leff_pw.setTitle(f"Leff time-series — {n} cycles")

        # ── R-cal 품질 readout: 채널별 R̄·Leff·contrast·valid%·cycle수 ──
        if hasattr(self, '_setup_rt_readout'):
            def _med(vals):
                v = [x for x in vals if x is not None and np.isfinite(x)]
                return float(np.median(v)) if v else float('nan')
            lines = []
            for ch in channels:
                res = [r for r in ch["results"] if r.get('r_mean') is not None]
                if not res:
                    continue
                r_pct    = _med([r['r_mean'] for r in res]) * 100.0
                leff     = _med([r.get('leff_mean') for r in res])
                contrast = _med([r.get('he_za_contrast') for r in res])
                valid    = _med([r.get('valid_frac') for r in res]) * 100.0
                # 낮은 contrast/valid = 인젝션 불량 신호 → 경고 마크
                flag = "" if (np.isfinite(valid) and valid < 30.0) else ""
                con_str = f"{contrast:.2f}" if np.isfinite(contrast) else "n/a"
                lines.append(
                    f"{ch['label']:<8} R̄={r_pct:6.3f}%  Leff={leff:5.2f}km  "
                    f"contrast={con_str}  valid={valid:4.0f}%  n={len(res)}{flag}")
            self._setup_rt_readout.setText(
                "R-cal quality (median/ch):\n" + "\n".join(lines) if lines
                else "R-cal quality: no valid cycles")

        # R(λ) 탭을 가장 최근 cycle로 미리 채움 — 클릭 전에도 비어있지 않게(탭 전환은 안 함).
        try:
            _latest, _lc = None, None
            for ch in channels:
                for r in ch["results"]:
                    if r.get('wave_nm_full') is not None and r.get('timestamp') is not None:
                        if _latest is None or _ts(r['timestamp']) > _ts(_latest['timestamp']):
                            _latest, _lc = r, ch["color"]
            if _latest is not None:
                self._show_setup_r_spectrum_from_result(_latest, _lc, switch_tab=False)
        except Exception:
            pass

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
        _key = rec["ch_key"]
        # 레거시 고정 이름 매핑 먼저 시도; 없으면 새 포맷 R_{label} 사용
        ch_subdir = {"cold": "R_Cold", "hot_pns": "R_Hot_PNs",
                     "hot_ans": "R_Hot_ANs"}.get(_key, f"R_{_key}")
        dat_path = os.path.join(out_dir, ch_subdir, file_date, f"{base}_R.dat")
        if not os.path.exists(dat_path):
            dat_path = os.path.join(out_dir, file_date, f"{base}_R.dat")
        roi = r.get("fit_window_nm", (400, 500))
        # 메모리에 R(λ) 곡선이 있으면 디스크 재읽기 없이 바로 그림(더 견고).
        if r.get('wave_nm_full') is not None and r.get('r_curve_fit') is not None:
            self._show_setup_r_spectrum_from_result(r, rec["color"], switch_tab=True)
        else:
            self._show_setup_r_spectrum(dat_path, roi, rec["color"])

    def _show_setup_r_spectrum_from_result(self, r, color, switch_tab=True):
        """R(λ) 스펙트럼 탭을 result dict의 메모리 배열(wave_nm_full/r_curve_raw/fit)로 그림.
        디스크 _R.dat 재읽기 불필요. switch_tab=False면 탭 전환 없이 갱신만(자동 미리채움용)."""
        if not hasattr(self, 'plot_diagnostic'):
            return
        try:
            wave  = np.asarray(r.get('wave_nm_full'), dtype=float)
            r_raw = np.asarray(r.get('r_curve_raw'),  dtype=float)
            r_fit = np.asarray(r.get('r_curve_fit'),  dtype=float)
        except Exception:
            return
        if wave is None or not len(wave):
            return
        self.p1.clear()
        try:
            self.p2.clear()
        except Exception:
            pass
        self.p1.plot(wave, r_raw, pen=None, symbol='o', symbolSize=3,
                     symbolBrush=(150, 150, 150, 150))
        self.p1.plot(wave, r_fit, pen=pg.mkPen(color, width=2.5))
        roi = r.get('fit_window_nm')
        if roi:
            try:
                self.p1.addItem(pg.LinearRegionItem(
                    [roi[0], roi[1]], movable=False, brush=(0, 255, 0, 20)))
            except Exception:
                pass
        self.plot_diagnostic.setLabel('left', 'Reflectance R', color='b')
        self.plot_diagnostic.setLabel('bottom', 'Wavelength (nm)')
        self.plot_diagnostic.setTitle(f"R(λ) — {r.get('filename', 'latest')}")
        fin = np.isfinite(r_fit)
        if fin.any():
            self.p1.vb.setYRange(float(np.nanmin(r_fit[fin])), 1.0, padding=0.1)
        if switch_tab and hasattr(self, '_diag_tabs'):
            self._diag_tabs.setCurrentIndex(0)

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
            self.plot_diagnostic.setTitle(f"No data file: {os.path.basename(dat_path)}")
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
            self.plot_diagnostic.setTitle(f"plot failed: {e}")

    # ══════════════════════════════════════════════════════════════════════
    # §12 결과 테이블 / QC / fast 렌더
    # ══════════════════════════════════════════════════════════════════════
    @staticmethod
    def _shsq_text(gases, props):
        """가스별 Shift/Squeeze 모드 한 줄 요약 (Link 관계 포함).

        ⚠ Center를 빠뜨리면 안 된다. 예전엔 모드 사다리가 Link/Limit/Fix 아니면
        전부 'Free'로 떨어져서 `Center -5.25, 1.9`가 **'Free'로 표시**됐다 —
        의미가 정확히 반대다(Free=제약 없음, Center=선언된 중심에 앵커).
        이 함수는 RUN 직전 확인 다이얼로그도 쓰므로 밤샘 런의 마지막 검문이 거짓이 된다.
        모르는 모드는 'Free'로 뭉개지 말고 이름 그대로 드러낸다."""
        props = props or {}

        def fmt(mode, val, default_mode, default_val):
            mode = mode or default_mode
            raw = str(val if val not in (None, '') else default_val).strip()
            compact = raw.replace(' ', '')
            if mode == 'Link':
                return f"→{raw}"
            if mode == 'Limit':
                return f"[{compact}]"
            if mode == 'Fix':
                return f"={compact}"
            if mode == 'Center':
                return f"@{compact}"      # 중심,반폭 — 0이 아니라 여기에 앵커된다
            if mode == 'Free':
                return 'Free'
            return f"?{mode}"             # 모르는 모드를 Free로 속이지 않는다

        def one(g):
            p = props.get(g, {})
            sh = fmt(p.get('sh_mode'), p.get('sh_val'), 'Limit', '-0.5, 0.5')
            sq = fmt(p.get('sq_mode'), p.get('sq_val'), 'Fix', '1.0')
            return f"{g} Sh{sh}·Sq{sq}"
        return "Sh/Sq:  " + "  │  ".join(one(g) for g in gases)

    def _toggle_shsq_table(self):
        show = not getattr(self, '_shsq_table_visible', True)
        self._shsq_table_visible = show
        self.tbl_shsq.setVisible(show)
        self._btn_shsq_tbl.setText(
            ("▼ " if show else "▶ ") + "Reference policy (Shift / Squeeze / T / bands)")

    def _on_shsq_table_changed(self):
        """상시 노출 테이블은 OK 버튼이 없다 — 편집 즉시 ref_props에 반영.

        ⚙️ Properties 팝업과 달리 되돌리기가 없으므로, 값을 **읽어 담기만** 하고
        엔진이나 결과는 건드리지 않는다(다음 RUN/Test Fit부터 적용)."""
        try:
            self.ref_props = self.tbl_shsq.get_properties()
        except Exception as e:                  # noqa: BLE001 — 편집 중 반쪽 상태 방어
            print(f"[ref policy] not applied: {e}")
            return
        if hasattr(self, 'lbl_shsq'):
            gases = list(getattr(self.engine, 'gas_list', []) or [])
            if gases:
                self.lbl_shsq.setText(self._shsq_text(gases, self.ref_props))

    def _refresh_shsq_summary(self):
        """Parameters 그리드의 Sh/Sq 요약 라벨 + 상시 노출 테이블 갱신.

        가스 목록이 바뀌는 지점(레퍼런스 락·채널 전환·시나리오 적용)에서 이미
        전부 호출되고 있어서, 테이블 재구성도 여기에 붙인다(새 훅을 만들지 않는다)."""
        gases = list(getattr(self.engine, 'gas_list', []) or [])
        if hasattr(self, 'tbl_shsq'):
            # 재구성 중의 changed 시그널이 ref_props를 덮어쓰지 않게 막는다
            self.tbl_shsq.blockSignals(True)
            try:
                self.tbl_shsq.set_gases(gases, getattr(self, 'ref_props', {}))
            except Exception as e:              # noqa: BLE001 — 표시가 핏을 막지 않는다
                print(f"[ref policy] table rebuild failed: {e}")
            finally:
                self.tbl_shsq.blockSignals(False)
        if not hasattr(self, 'lbl_shsq'):
            return
        if not gases:
            self.lbl_shsq.setText("Sh/Sq: (lock refs to show)")
            return
        self.lbl_shsq.setText(self._shsq_text(gases, getattr(self, 'ref_props', {})))

    def _compact_table_columns(self, cols):
        """결과 테이블을 좁은 패널에서 한눈에 들어오게 압축.
        기본 컬럼폭(~100px)×13컬럼 = 1300px가 가로 스크롤 뒤로 숨던 것을,
        내용에 맞는 고정폭 + 작은 폰트로 줄인다(정보 제거 없음, 필요시 드래그로 확장)."""
        try:
            from PyQt6.QtGui import QFont
            f = self.table.font()
            f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
            self.table.setFont(f)
            widths = {"Ch": 34, "File": 88, "Time": 118, "RMS": 58, "Chi2": 44,
                      "SNR": 52, "Status": 72, "Shift": 44, "Squeeze": 52}
            s = getattr(self, '_s', 1.0)
            for i, c in enumerate(cols):
                self.table.setColumnWidth(i, int(widths.get(c, 56) * s))   # 가스 컬럼 기본 56
            self.table.horizontalHeader().setStretchLastSection(False)
        except Exception:
            pass

    def update_table(self, result_dict, row_index):
        """Triggered by the worker thread per result."""
        self.results.append(result_dict)
        self._autosave_row(result_dict)   # 크래시 나도 여기까지는 디스크에 남음
        # Fast (batch) mode: do NOT touch the table/plots per result — that can't keep
        # up with parallel bursts (tens of thousands of rows → GUI freeze). Just collect
        # + autosave; a light timer (_flush_fast) updates the progress bar, and the
        # whole table+plots are rendered ONCE at the end (_render_fast_results).
        # Step mode renders live, one slow scan at a time.
        if getattr(self, '_fast_mode_active', False):
            return
        self._apply_row_to_table(result_dict, row_index)

    def _write_row_cells(self, result_dict, row, multi):
        """Write the cells of one table row (no plots / scroll / progress bar)."""
        if row >= self.table.rowCount():
            self.table.setRowCount(row + 1)
        c = 0
        if multi:
            self.table.setItem(row, 0, QTableWidgetItem(f"CH{result_dict.get('Channel', 1)}"))
            c = 1
        self.table.setItem(row, c + 0, QTableWidgetItem(str(result_dict.get('File', ''))))
        self.table.setItem(row, c + 1, QTableWidgetItem(str(result_dict.get('Time', ''))))
        self.table.setItem(row, c + 2, QTableWidgetItem(f"{result_dict.get('RMS', 0):.2e}"))
        self.table.setItem(row, c + 3, QTableWidgetItem(f"{result_dict.get('Chi2', 0):.2f}"))
        self.table.setItem(row, c + 4, QTableWidgetItem(f"{result_dict.get('SNR', 0):.1f}"))
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
        for i, gas_name in enumerate(self.engine.gas_list):
            self.table.setItem(row, c + 6 + i, QTableWidgetItem(f"{result_dict.get(gas_name, 0):.2e}"))
        go = len(self.engine.gas_list)
        self.table.setItem(row, c + 6 + go,     QTableWidgetItem(f"{result_dict.get('Shift', 0):.2f}"))
        self.table.setItem(row, c + 6 + go + 1, QTableWidgetItem(f"{result_dict.get('Squeeze', 1):.4f}"))

    def _apply_row_to_table(self, result_dict, row_index):
        """Live per-row update (Step mode): cells + conc plot + scroll + progress bar."""
        multi = getattr(self, '_multi_channel_mode', False)
        if multi:
            row = self._next_table_row
            self._next_table_row += 1
        else:
            row = row_index
        self._write_row_cells(result_dict, row, multi)
        if hasattr(self.monitor, 'update_conc'):
            self.monitor.update_conc(result_dict, row_index)
        import time as _t
        if (_t.monotonic() - getattr(self, '_last_scroll_t', 0.0)) >= 0.15:
            self._last_scroll_t = _t.monotonic()
            item = self.table.item(row, 0)
            if item:
                self.table.scrollToItem(item)
        n = len(self.results)
        self.pbar.setValue(n)
        # E2: Step 모드도 진행 숫자를 한 줄로 보여준다(예전엔 막대만 움직였다).
        # 처리율·ETA는 넣지 않는다 — 워커가 emit하는 건 progress/total_ready 둘뿐이라
        # 어떤 속도 예측도 근거가 없다(있는 척하면 밤샘 런의 판단을 흐린다).
        if not getattr(self, '_fast_mode_active', False) and n % 10 == 0:
            self.status.setText(self._progress_text(n))

    def _progress_text(self, n):
        """RUN 진행 한 줄. 숫자는 실제로 아는 것만 — 완료/전체 스캔."""
        total = self.pbar.maximum() or n
        tag = f"{self._workers_total} CH · " if getattr(self, '_multi_channel_mode', False) else ""
        return (f"Fitting… {tag}{n:,} / {total:,} scans"
                "   (settings frozen for this run — edits apply to the next RUN)")

    def _flush_fast(self):
        """Fast mode: light periodic feedback while fitting (progress bar + status).
        The heavy table/plot render is done once at the end in _render_fast_results."""
        n = len(self.results)
        self.pbar.setValue(n)
        self.status.setText(self._progress_text(n))

    def _render_fast_results(self):
        """Render everything ONCE after a Fast run: table (capped preview) + plots.
        Full results live in self.results + the autosave file (open in result viewer)."""
        res = self.results
        if not res:
            return
        cap = getattr(self, '_fast_table_cap', 5000)
        n_show = min(len(res), cap)
        multi = getattr(self, '_multi_channel_mode', False)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(n_show)
            for row in range(n_show):
                self._write_row_cells(res[row], row, multi)
        finally:
            self.table.setUpdatesEnabled(True)
        if hasattr(self.monitor, 'rebuild_conc'):
            self.monitor.rebuild_conc(res)
        if hasattr(self.monitor, 'rebuild_trend'):
            self.monitor.rebuild_trend(res)
        self.pbar.setValue(len(res))
        if len(res) > n_show:
            self.status.setText(
                f"Fast complete: {len(res):,} scans fitted — table previews only {n_show:,} rows, "
                f"see full results in the graph + autosave file (Result Viewer).")

    def _fast_finalize(self):
        """End of a Fast run: stop the feedback timer and render results once."""
        t = getattr(self, '_fast_timer', None)
        if t is not None:
            t.stop()
        if getattr(self, '_fast_mode_active', False):
            self._render_fast_results()
        self._fast_mode_active = False
        if hasattr(self.monitor, 'flush_plots'):
            self.monitor.flush_plots()

    def analysis_finished(self, stopped=False):
        """Re-enables UI once ALL channel workers have finished."""
        self._analysis_running = False
        if stopped:
            # Stop requested — re-enable immediately regardless of pending workers
            self._fast_finalize()
            self._autosave_close()
            self.b_run.setEnabled(True)
            self.b_stop.setEnabled(False)
            self.status.setText("Analysis stopped by user.")
            self.status.setStyleSheet("color: red; font-weight: bold;")
            return

        # Count completed workers; wait until the last one finishes
        self._workers_done = getattr(self, '_workers_done', 0) + 1
        total = getattr(self, '_workers_total', 1)

        if self._workers_done < total:
            # Still waiting for other channels
            remaining = total - self._workers_done
            self.status.setText(
                f"CH{self._workers_done} done — waiting for {remaining} more channel(s)..."
            )
            return

        # All workers finished
        self.b_run.setEnabled(True)
        self.b_stop.setEnabled(False)
        # Stop the Fast flush timer, drain remaining buffered rows, redraw plots.
        self._fast_finalize()
        n_ch = total
        ch_label = f"{n_ch}-channel " if n_ch > 1 else ""
        # ── 자동 품질필터(QC): 핏 종료 후 채널별 RMS 분포에서 robust 이상치 제외 ──
        qc_changed = self._apply_auto_qc()
        if qc_changed:
            self._refresh_after_qc(qc_changed)

        self._autosave_close()
        was_stopped = getattr(self, '_stop_requested', False)
        self._stop_requested = False
        if was_stopped:
            self.status.setText(f"Stopped — partial results ({len(self.results):,} rows)")
            self.status.setStyleSheet("color: orange; font-weight: bold;")
        else:
            self.status.setText(f"{ch_label}Analysis Completed!")
            self.status.setStyleSheet("color: green; font-weight: bold;")
        # L3: 완료 시 자동 저장 (QC 적용 후, 정식 파일명 규칙)
        saved_msg = ""
        if (not was_stopped and hasattr(self, 'chk_auto_save')
                and self.chk_auto_save.isChecked() and self.results):
            try:
                self.save(auto=True)
                saved_msg = "\n Auto-saved (see status bar)"
            except Exception as _e:
                saved_msg = f"\n Auto-save failed: {_e}"

        qc_msg = f"\nAuto QC excluded: {len(qc_changed)} rows (gas → NaN)" if qc_changed else ""
        head = "Analyzed up to the stop point." if was_stopped else f"All files analyzed successfully ({n_ch} channel(s))."
        QMessageBox.information(self, "Done", f"{head}{qc_msg}{saved_msg}")

    def reapply_qc(self):
        """재핏 없이 OK RMS% → Kalman Q/R → 자동 QC 순서로 후처리 재적용."""
        if not getattr(self, 'results', None):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Reapply", "No analysis results. Run a fit first.")
            return
        self._reapply_ok_rms_status()
        self._reapply_kalman()
        changed = self._apply_auto_qc()
        self._refresh_after_qc(changed)
        from PyQt6.QtWidgets import QMessageBox
        K = self.spin_qc_k.value() if hasattr(self, 'spin_qc_k') else 8.0
        kq = self.spin_kalman_q.value() if hasattr(self, 'spin_kalman_q') else 0.0005
        kr = self.spin_kalman_r.value() if hasattr(self, 'spin_kalman_r') else 0.050
        rms_pct = self.spin_rms_thresh.value() if hasattr(self, 'spin_rms_thresh') else 10.0
        _settle_on = hasattr(self, 'chk_settle') and self.chk_settle.isChecked()
        _settle_str = (f", Settling (first {self.spin_settle_n.value()}/bin)"
                       if _settle_on else "")
        _n_settle = sum(1 for r in self.results if str(r.get('Status', '')) == 'Settling')
        QMessageBox.information(self, "Reapply",
                                f"Reapplied OK RMS% ({rms_pct:.1f}%), Kalman (Q={kq}, R={kr}), "
                                f"QC (K={K:g}){_settle_str}.\n"
                                f"Excluded: {len(changed)} / {len(self.results):,} rows"
                                + (f"  (settling {_n_settle})" if _settle_on else ""))

    def _reapply_ok_rms_status(self):
        """OK RMS% 임계 변경을 반영해 각 행의 OK/Unstable 상태를 재판정.
        _qc_orig_status를 갱신해두면 이후 _apply_auto_qc()가 복원 시 새 상태를 쓴다."""
        import numpy as _np
        thresh = self.spin_rms_thresh.value() / 100.0 if hasattr(self, 'spin_rms_thresh') else 0.10
        for r in self.results:
            sig_mean = r.get('_signal_mean')
            if sig_mean is None:
                continue
            try:
                sig_mean = float(sig_mean)
                rms = float(r.get('RMS', _np.nan))
            except (TypeError, ValueError):
                continue
            if not (_np.isfinite(sig_mean) and sig_mean > 0 and _np.isfinite(rms)):
                continue
            orig_st = str(r.get('_qc_orig_status', r.get('Status', '')))
            if orig_st.startswith('Skip') or orig_st.startswith('Error'):
                continue
            new_st = 'OK' if rms < sig_mean * thresh else 'Unstable'
            r['_qc_orig_status'] = new_st

    def _reapply_kalman(self):
        """현재 Kalman Q/R 값으로 _Smooth 컬럼을 채널별로 재계산.
        _qc_orig_sm을 새 값으로 갱신해두면 _apply_auto_qc()가 복원 후 QC를 재적용한다."""
        import numpy as _np
        try:
            from core.physics import KalmanTracker
        except ImportError:
            from CAESAR.core.physics import KalmanTracker
        kq = self.spin_kalman_q.value() if hasattr(self, 'spin_kalman_q') else 0.0005
        kr = self.spin_kalman_r.value() if hasattr(self, 'spin_kalman_r') else 0.050
        gas_list = self.engine.gas_list

        by_ch: dict = {}
        for i, r in enumerate(self.results):
            by_ch.setdefault(r.get('Channel', 1), []).append(i)

        for indices in by_ch.values():
            kf = KalmanTracker(num_variables=len(gas_list), q_noise=kq, r_noise=kr)
            for i in indices:
                r = self.results[i]
                raw = []
                orig_d = r.get('_qc_orig', {})
                for nm in gas_list:
                    v = orig_d.get(nm) if orig_d else r.get(nm)
                    try:
                        fv = float(v)
                        raw.append(fv if _np.isfinite(fv) else 0.0)
                    except (TypeError, ValueError):
                        raw.append(0.0)
                smooth = kf.process(raw)
                if '_qc_orig_sm' not in r:
                    r['_qc_orig_sm'] = {}
                for gi, nm in enumerate(gas_list):
                    r['_qc_orig_sm'][nm] = float(smooth[gi])

    def _apply_auto_qc(self):
        """핏 종료 후 채널별 RMS 분포에서 robust 임계(log median+K·MAD)로 이상치를 자동
        검출해 그 행의 가스 농도를 NaN으로 제외한다. 매직넘버 입력 불필요.
        원본 농도를 r['_qc_orig']에 백업하고 매 호출마다 복원 후 재필터하므로,
        K를 바꿔 여러 번 재적용해도 비파괴적이다.
        반환: 제외된 행들의 self.results 인덱스 리스트."""
        import numpy as _np
        # 재적용 전 상태 기록(복원·제외 양방향 변경행 추적 → 테이블 부분갱신용)
        prev_status = [str(r.get('Status', '')) for r in self.results]
        # ── (a) 원본 백업 / 복원: 재적용을 비파괴로 ──
        for r in self.results:
            if '_qc_orig' not in r:
                r['_qc_orig'] = {nm: r.get(nm) for nm in self.engine.gas_list}
                r['_qc_orig_sm'] = {nm: r.get(f"{nm}_Smooth")
                                    for nm in self.engine.gas_list if f"{nm}_Smooth" in r}
                r['_qc_orig_status'] = r.get('Status', '')
            else:
                for nm, v in r['_qc_orig'].items():
                    r[nm] = v
                for nm, v in r.get('_qc_orig_sm', {}).items():
                    r[f"{nm}_Smooth"] = v
                if not str(r.get('Status', '')).startswith('QC-Excluded'):
                    r['Status'] = r.get('_qc_orig_status', r.get('Status', ''))
        # ── (b) 정착(settling) 스캔 제외 — QC와 독립(자체 체크박스), 복원 뒤라 비파괴 ──
        # 각 빈 첫 N스캔 = 캘(He/ZA) 복귀 직후 퍼지 과도 → 농도 저편향. File의 '[NNNN]'이
        # 빈 내 스캔#. gas→NaN + Status='Settling'으로 flag(지우지 않음 — 복원/토글 가능).
        if hasattr(self, 'chk_settle') and self.chk_settle.isChecked():
            import re as _re
            n_settle = self.spin_settle_n.value() if hasattr(self, 'spin_settle_n') else 3
            for r in self.results:
                if str(r.get('Status', '')).startswith('QC-Excluded'):
                    continue
                m = _re.search(r'\[(\d+)\]', str(r.get('File', '')))
                si = int(m.group(1)) if m else -1
                if 0 <= si < n_settle:
                    for nm in self.engine.gas_list:
                        r[nm] = float('nan')
                        if f"{nm}_Smooth" in r:
                            r[f"{nm}_Smooth"] = float('nan')
                    r['Status'] = 'Settling'
        def _status_changed():
            return [i for i, r in enumerate(self.results)
                    if str(r.get('Status', '')) != prev_status[i]]
        if not (hasattr(self, 'chk_qc') and self.chk_qc.isChecked()):
            return _status_changed()   # 복원만 (이전 QC 해제) — settling은 위에서 이미 적용
        K = self.spin_qc_k.value() if hasattr(self, 'spin_qc_k') else 8.0
        if K <= 0:
            return _status_changed()   # 자동 끔(수동 RMS상한만 사용) — 복원만
        # 채널별 RMS 수집 → log공간 robust 임계 (단일 진실원: core.result_io)
        # min_n=1: 이 경로는 핏 결과 전체라 채널마다 표본이 충분 — 기존 동작(표본수
        # 무관 계산) 보존. 결과뷰어 QC는 부분 파일도 다루므로 min_n=5를 쓴다.
        from core.result_io import robust_rms_thresholds
        _rms_list, _ch_list = [], []
        for r in self.results:
            try:
                _rms_list.append(float(r.get('RMS', float('nan'))))
            except Exception:
                _rms_list.append(float('nan'))
            _ch_list.append(r.get('Channel', 1))
        thr_by_ch = robust_rms_thresholds(_rms_list, _ch_list, K=K, min_n=1)
        for r in self.results:
            # 워커 수동 QC(QC-Excluded)·정착(Settling) 행은 이미 제외됨 → 유지
            if str(r.get('Status', '')).startswith(('QC-Excluded', 'Settling')):
                continue
            try:
                rms = float(r.get('RMS', float('nan')))
            except Exception:
                rms = float('nan')
            thr = thr_by_ch.get(r.get('Channel', 1), float('inf'))
            if _np.isfinite(rms) and rms > thr:
                for nm in self.engine.gas_list:
                    r[nm] = float('nan')
                    if f"{nm}_Smooth" in r:
                        r[f"{nm}_Smooth"] = float('nan')
                r['Status'] = f"QC-Auto (rms={rms:.1e}>{thr:.1e})"
        return _status_changed()

    def _refresh_after_qc(self, changed_idx):
        """자동 QC 적용/재적용 후 농도 시계열을 벌크 재구성하고, 상태가 바뀐 행만 테이블에
        다시 그린다(2만행 전체 재렌더/행별 setData = O(n²) 멈춤 방지)."""
        # 농도 시계열 벌크 재구성(곡선당 setData 1회 → 빠름)
        try:
            if hasattr(self, 'monitor') and hasattr(self.monitor, 'rebuild_conc'):
                self.monitor.rebuild_conc(self.results)
        except Exception:
            pass
        # 변경된 행만 테이블 Status/가스 셀 갱신(복원·제외 양방향)
        try:
            from PyQt6.QtWidgets import QTableWidgetItem
            from PyQt6.QtGui import QColor
            multi = getattr(self, '_multi_channel_mode', False)
            c = 1 if multi else 0
            self.table.setUpdatesEnabled(False)
            for i in changed_idx:
                if i >= self.table.rowCount():
                    continue
                r = self.results[i]
                st = str(r.get('Status', ''))
                it = QTableWidgetItem(st)
                if st.startswith('QC-') or st not in ("OK", "Recovered"):
                    it.setBackground(QColor(255, 100, 100))
                elif st == "Recovered":
                    it.setBackground(QColor(255, 220, 100))
                self.table.setItem(i, c + 5, it)
                for gi, gas in enumerate(self.engine.gas_list):
                    try:
                        txt = f"{float(r.get(gas, 0)):.2e}"
                    except (TypeError, ValueError):
                        txt = "nan"
                    self.table.setItem(i, c + 6 + gi, QTableWidgetItem(txt))
            self.table.setUpdatesEnabled(True)
        except Exception:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass

    def _results_date_range(self):
        """결과 Time에서 데이터(raw) 날짜범위 'YYMMDD' 또는 'YYMMDD-YYMMDD'. 없으면 ''."""
        import re as _re
        ds = set()
        for r in getattr(self, 'results', []):
            m = _re.search(r'(\d{2})(\d{2})-(\d{2})-(\d{2})', str(r.get('Time', '')))
            if m:
                ds.add(m.group(2) + m.group(3) + m.group(4))   # YYMMDD
        if not ds:
            return ''
        lo, hi = min(ds), max(ds)
        return lo if lo == hi else f"{lo}-{hi}"

    def _channel_settings_tag(self, ch):
        """채널 ch 세팅 → (라벨, 파일명용 짧은 태그). 채널별 윈도우/poly/shift/가스T 인코딩."""
        cfg = self._channel_configs.get(ch) or {}
        lbl = (cfg.get('data_label') or '').strip() or f'CH{ch}'
        if cfg.get('fit_unit') == 'px':
            win = f"px{cfg.get('f_min', '?')}-{cfg.get('f_max', '?')}"
        else:
            try:
                win = f"{float(cfg.get('fit_start_nm', 0)):.0f}-{float(cfg.get('fit_end_nm', 0)):.0f}nm"
            except Exception:
                win = "win?"
        poly = cfg.get('poly_deg', '?')
        rp = cfg.get('ref_props', {}) or {}
        pg = next((r.get('name') for r in cfg.get('refs', []) if r.get('name')), None)
        sh = "Sh?"
        if pg and pg in rp:
            m = rp[pg].get('sh_mode', '')
            v = str(rp[pg].get('sh_val', '')).replace(' ', '')
            sh = f"Sh[{v}]" if m == 'Limit' else f"Sh{m}"
        try:
            gasT = float(cfg.get('gas_temp', 0) or 0)
        except Exception:
            gasT = 0
        gtag = f"_gT{int(gasT)}" if gasT > 0 else ""
        return lbl, f"{win}_Poly{poly}_{sh}{gtag}"

    # ══════════════════════════════════════════════════════════════════════
    # §13 저장 + 결과뷰어 연동
    # ══════════════════════════════════════════════════════════════════════
    def save(self, auto=False):
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

        # 파일명: 데이터(raw) 날짜범위 + 채널라벨 + 핵심세팅 (실행날짜 X)
        _drange = self._results_date_range() or now_str
        _albl, _atag = self._channel_settings_tag(self._active_channel)
        default_fname = f"{_drange}_{_albl}_{_atag}.dat"

        if auto:
            # L3: 완료 시 자동 저장 — 다이얼로그 없이 기존 파일명 규칙으로
            _base = self._dlg_dir('save') or os.path.join(DEFAULT_OUTPUT_DIR, 'fitting')
            os.makedirs(_base, exist_ok=True)
            path = os.path.join(_base, default_fname)
        else:
            _start = os.path.join(self._dlg_dir('save'), default_fname) if self._dlg_dir('save') else default_fname
            path, _ = QFileDialog.getSaveFileName(self, "Save Data (auto per-channel name if multi-channel)", _start, "Data Files (*.dat);;CSV Files (*.csv)")
            self._dlg_dir('save', path)

        if path:
            try:
                df = pd.DataFrame(self.results)
                
                if 'Params' in df.columns:
                    df = df.drop(columns=['Params'])
                    
                current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                robust_on = hasattr(self, 'chk_robust') and self.chk_robust.isChecked()
                robust_status = "ON" if robust_on else "OFF"

                kalman_q = self.spin_kalman_q.value()
                kalman_r = self.spin_kalman_r.value()
                rms_thresh_pct = self.spin_rms_thresh.value()
                temporal_i0 = "ON" if self.chk_temporal_i0.isChecked() else "OFF"
                dark_loaded = "YES" if (hasattr(self, 'dark_data') and self.dark_data is not None) else "NO"
                dark_scale_val = self.spin_dark_scale.value()
                offset_loaded = "YES" if (hasattr(self, 'offset_data') and self.offset_data is not None) else "NO"
                offset_scale_val = self.spin_offset_scale.value()
                stray_light_val = self.spin_stray_light.value()

                from core.provenance import code_version as _codever

                # ── QC / ±Neg / 데이터기간: 폴더명·_SETTINGS.txt·인라인헤더 공용으로 먼저 계산 ──
                # (인라인 헤더에 넣어야 머지/슬라이스 후에도 .dat 자체에 세팅이 남는다.)
                allow_neg_on = hasattr(self, 'chk_allow_neg') and self.chk_allow_neg.isChecked()
                allow_neg = "ON" if allow_neg_on else "OFF"
                qc_on = hasattr(self, 'chk_qc') and self.chk_qc.isChecked()
                qc_k = self.spin_qc_k.value() if hasattr(self, 'spin_qc_k') else 0.0
                if qc_on and qc_k > 0:
                    qc_str = f"ON  (auto threshold K={qc_k:g}·MAD)"
                elif qc_on:
                    qc_str = "ON  (auto off — manual RMS max only)"
                else:
                    qc_str = "OFF"
                try:
                    _tt = pd.to_datetime(df['Time'], errors='coerce').dropna()
                    span_str = (f"{_tt.min():%Y-%m-%d %H:%M} ~ {_tt.max():%Y-%m-%d %H:%M}"
                                if len(_tt) else (_drange or "(unknown)"))
                except Exception:
                    span_str = _drange or "(unknown)"

                # ── etalon–기체 공선성 진단(보고 전용, 핏 불변) ──
                # 이번 런이 실제 쓴 etalon 주파수(Params.etalon_freq)에서, 현재
                # 핏창·poly·레퍼런스로 differential 공간 r·VIF를 계산해 헤더에 기록.
                # (shift/squeeze는 0/1 — 서브픽셀 이동은 r에 영향 미미)
                collin_line = "n/a (engine not ready or no etalon freq)"
                try:
                    _ef = next((float(r.get('Params', {}).get('etalon_freq', 0.0))
                                for r in self.results
                                if r.get('Params', {}).get('etalon_freq')), 0.0)
                    if _ef > 0 and self.engine.is_engine_ready():
                        from core.doas_fit import DoasFitter as _DF
                        _pi = np.arange(f_min_px, f_max_px + 1, dtype=float)
                        _diag = _DF(self.engine).etalon_collinearity(
                            _pi, _ef, poly_deg, getattr(self, 'ref_props', {}))
                        collin_line = _DF.format_etalon_collinearity(_diag)
                except Exception as _ce:
                    collin_line = f"n/a ({_ce})"

                header_lines = [
                    "# ==========================================================",
                    "# Augur Analysis Report",
                    f"# Generated: {current_time}",
                    f"# Code Version: {_codever()}",
                    f"# Data Period: {span_str}",
                    f"# Fit Range: Pixel {f_min_px}-{f_max_px} ({wl_str})",
                    f"# Polynomial Degree: {poly_deg}",
                    f"# Tikhonov Lambda: {lam_val:g}",
                    f"# Robust Fitting (IRLS): {robust_status}",
                    f"# Allow Negative Gas (±Neg): {allow_neg}",
                    f"# Auto QC: {qc_str}",
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
                    f"# Etalon-Gas Collinearity (diagnostic only, fit unchanged): {collin_line}",
                    "# ==========================================================\n"
                ]

                header_txt = "\n".join(header_lines)
                is_csv = path.endswith('.csv')
                ext = '.csv' if is_csv else '.dat'

                def _write_df(_df, _path, _ch_hdr=""):
                    with open(_path, 'w', encoding='utf-8') as f:
                        if _ch_hdr:
                            f.write(_ch_hdr + "\n")
                        f.write(header_txt)
                        if is_csv:
                            _df.to_csv(f, index=False, lineterminator='\n')
                        else:
                            _df.to_csv(f, sep='\t', index=False, lineterminator='\n')

                def _build_meta(_df, _ch, campaign):
                    """이 파일 몫의 meta. **파일명보다 먼저** 필요하다 — runid가 이름이 된다.

                    실제 조립은 `_build_run_meta`(메서드)가 한다 — autosave 파일명도 같은
                    runid를 써야 하므로 클로저에 가둬둘 수 없다."""
                    try:
                        _t = pd.to_datetime(_df['Time'], errors='coerce').dropna()
                        days = sorted({d.strftime('%Y-%m-%d') for d in _t})
                    except Exception:
                        days = []
                    return self._build_run_meta(_ch, campaign=campaign,
                                                data_days=days, rows=_meta_rows(_df))

                def _meta_rows(_df):
                    """행수 요약. Status 문자열이 자유형식이라 고정 3분류 대신 실측 집계."""
                    out = {"total": int(len(_df))}
                    if 'Status' in _df.columns:
                        counts = _df['Status'].astype(str).value_counts()
                        out["by_status"] = {str(k): int(v) for k, v in counts.items()}
                    return out

                def _ch_header(ch):
                    """채널별 세팅 헤더 한 줄(파일 상단)."""
                    lbl, tag = self._channel_settings_tag(int(ch))
                    cfg = self._channel_configs.get(int(ch)) or {}
                    return (f"# Channel {int(ch)} ({lbl}) settings: {tag}  "
                            f"gas_temp={cfg.get('gas_temp', 0)}°C  refs={','.join(g for g in self.engine.gas_list)}")

                # ── 배치: output/{campaign}/{YYYY-MM-DD}/fitting/ (A3) ──
                # 디렉터리는 **시간축만** 인코딩한다. 옛 `{창}/{날짜}/{neg}/{QC}/` 4단은
                # 파일시스템을 인덱스로 쓴 것이라 패싯 순서가 고정됐다("QC 끈 것 전부"를
                # 보려면 창 폴더를 전부 걸어야 함). 이제 그 패싯은 전부 `.meta.json`에
                # 있으므로 폴더로 나눌 이유가 없다.
                # 세팅 구분은 파일명의 **runid**가 한다 — 다른 세팅 = 다른 runid = 다른
                # 파일이라 서로 못 덮는다. 같은 세팅 재핏만 같은 이름으로 와서
                # `_archive`로 밀린다(비파괴 — 이전 버전 전부 보존).
                # 핏은 스캔 단위 독립이라 날짜별로 잘라 저장해도 무손실.
                from core.result_io import archive_existing
                campaign = (getattr(self, '_ed_campaign', None)
                            and self._ed_campaign.text().strip()) or DEFAULT_CAMPAIGN

                chans = sorted(df['Channel'].dropna().unique()) if 'Channel' in df.columns else []
                base_dir = os.path.dirname(path) or (self._dlg_dir('save') or '.')
                arch_base = _campaign_dir(base_dir, campaign)   # {base}/{campaign}/_archive/…
                _tt_all = pd.to_datetime(df['Time'], errors='coerce')
                day_keys = _tt_all.dt.strftime('%y%m%d').where(_tt_all.notna(), 'nodate')
                multi = len(chans) > 1

                written, n_files, n_archived, runids = [], 0, 0, []
                for day_tag in sorted(day_keys.unique()):
                    dsub = df[day_keys == day_tag]
                    if multi:
                        targets = [(ch, dsub[dsub['Channel'] == ch]) for ch in chans]
                    else:
                        targets = [((chans[0] if chans else self._active_channel), dsub)]
                    for ch, ssub in targets:
                        if ssub.empty:
                            continue
                        meta = _build_meta(ssub, ch, campaign)
                        lbl, _tag = self._channel_settings_tag(int(ch))
                        fpath = _out_path(base_dir, campaign, day_tag, kind='fitting',
                                          channel=ch, label=lbl,
                                          runid=(meta or {}).get('runid'), ext=ext)
                        os.makedirs(os.path.dirname(fpath), exist_ok=True)
                        # 밀려나는 `.dat`의 meta도 같이 보낸다 — 안 그러면 아카이브된
                        # 결과가 설정 없는 고아가 되고, 새 meta가 그 자리를 덮는다.
                        if archive_existing(fpath, arch_base):
                            n_archived += 1
                            archive_existing(run_meta.meta_path_for(fpath), arch_base)
                        _write_df(ssub, fpath, _ch_header(ch) if multi else "")
                        if meta:
                            run_meta.write_meta(fpath, meta)   # `.dat` 포맷 불변 — 옆에 쓴다
                            runids.append(meta['runid'])
                        n_files += 1
                        written.append(f"{os.path.basename(fpath)}  ({len(ssub)} rows)")

                self._autosave_retire()   # E3: 정식 저장 성공 → autosave는 역할 끝

                n_days = day_keys.nunique()
                arch_note = f", {n_archived} previous → _archive" if n_archived else ""
                rid_disp = "/".join(sorted(set(runids))) or "no-runid"
                if auto:
                    self.status.setText(
                        f"Auto-saved → {campaign}/{n_days} day(s)/fitting  "
                        f"[{rid_disp}] ({n_files} file{arch_note})")
                else:
                    _shown = written if len(written) <= 12 else written[:12] + [f"… +{len(written)-12} more"]
                    QMessageBox.information(
                        self, "Success",
                        "Saved!\n\n"
                        f"{base_dir}\\{campaign}\\{{YYYY-MM-DD}}\\fitting\n"
                        f"   runid {rid_disp}  (±Neg={allow_neg} / QC={qc_str})\n"
                        f"   {n_days} day(s), {n_files} file(s){arch_note}\n\n"
                        "Saved files:\n  " + "\n  ".join(_shown) +
                        "\n\n※ Every .dat has a .meta.json beside it with the full settings,\n"
                        "   and the same settings stay in the .dat's top # header.\n"
                        "※ The file dialog now picks the LOCATION; the name is uniform\n"
                        "   ({date}_{CH}_{label}_{runid}) so different settings never collide.")
                
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
        def _fail(msg):
            self.status.setText(f"Double-click: {msg}")
            self.status.setStyleSheet("color: red; font-weight: bold;")

        # Bring the Analysis Monitor into view regardless of which main tab the
        # user is currently looking at — otherwise the replay can render correctly
        # in the background while looking, from the user's seat, like nothing happened.
        try:
            self.main_tabs.setCurrentWidget(self._tab_pages.get(self.monitor, self.monitor))
        except Exception:
            pass

        # File name lives in col 0 normally, but col 1 when the "Ch" column is
        # prepended in multi-channel mode.
        fc = 1 if getattr(self, '_multi_channel_mode', False) else 0
        item = self.table.item(row, fc)
        if item is None:
            _fail(f"no cell at row {row}, col {fc}")
            return
        fname = item.text()

        # 클릭한 행의 채널부터 먼저 알아낸다 — 결과 테이블은 모든 채널 탭의 결과를 한
        # 테이블에 같이 보여주지만, 그 파일 경로는 self.file_list(= 지금 선택돼 있는 채널
        # 탭의 파일목록)가 아니라 self._channel_files[그 행의 채널]에만 들어있다. 예전엔
        # self.file_list만 뒤져서, CH3 탭을 보고 있는 동안 CH1/CH2 결과행을 더블클릭하면
        # "파일을 못 찾음"으로 조용히 실패했다(지금은 메시지로 뜸).
        ch_txt = self.table.item(row, 0).text() if fc == 1 else ''
        want_ch = int(ch_txt.replace('CH', '')) if ch_txt.startswith('CH') else None
        search_list = self._channel_files.get(want_ch, self.file_list) if want_ch else self.file_list

        entry = self._entry_from_display_name(fname, search_list)
        if not entry:
            _fail(f"'{fname}' not found in CH{want_ch or self._active_channel}'s file list "
                  "(switch to that channel's tab and try again)")
            return
        filepath = self._entry_filepath(entry)
        row_idx  = self._row_index_from_display_name(fname)

        # 파일명으로 결과 조회 (행 인덱스가 아니라 → 정렬/순서 어긋나도 안전).
        # 멀티채널이면 같은 파일명이 채널마다 있을 수 있으니 클릭한 행의 채널까지 일치시킨다.
        def _match(r):
            if r.get('File') != fname:
                return False
            return want_ch is None or int(r.get('Channel', 1)) == want_ch
        _res = (self.results[row] if (row < len(self.results) and _match(self.results[row]))
                else next((r for r in self.results if _match(r)), None))
        if _res is None:
            _fail(f"no stored result matches '{fname}'" + (f" CH{want_ch}" if want_ch else ""))
            return
        params = _res.get('Params')
        if not params:
            _fail(f"'{fname}' has no saved fit parameters (Status={_res.get('Status', '?')})")
            return

        # 클릭한 결과의 채널로 Monitor 표시채널을 맞춰 채널필터에 막히지 않게 한다.
        ch = 1
        try:
            ch = int(params.get('channel', _res.get('Channel', 1)))
            if hasattr(self.monitor, 'cb_fit_channel'):
                self.monitor.cb_fit_channel.setCurrentIndex(max(0, min(ch - 1, self.monitor.cb_fit_channel.count() - 1)))
        except Exception:
            pass

        # self.engine / txt_min / txt_max only ever reflect the currently active
        # channel TAB (_apply_config swaps them on every tab switch) — if the
        # clicked result is a different channel, replaying with them would rebuild
        # the model using the wrong references/wavecal/fit-range. Build that
        # channel's own (throwaway) engine instead, same as the parallel-fit
        # workers already do via _build_engine_from_config.
        replay_engine = self.engine
        f_min_txt, f_max_txt = self.txt_min.text(), self.txt_max.text()
        if ch != self._active_channel:
            cfg = self._channel_configs.get(ch)
            if cfg is not None:
                try:
                    replay_engine = self._build_engine_from_config(cfg)
                    f_min_txt = cfg.get('f_min', f_min_txt)
                    f_max_txt = cfg.get('f_max', f_max_txt)
                except Exception as e:
                    print(f"Replay: falling back to active engine for CH{ch}: {e}")

        try:
            f_min, f_max = int(f_min_txt), int(f_max_txt)

            # load_measurement_with_hk handles alpha_trace.dat, Araon Mega-Matrix,
            # and plain 1D spectra internally — unlike the naive load_measurement
            # (fixed column-count CSV parser), which chokes on alpha_trace.dat's
            # ragged field counts. Always route through it, passing the fit's own
            # channel so Mega-Matrix multi-channel rows slice the right columns.
            pixel_idx, intensity_raw, _, _, _ = DataIO.load_measurement_with_hk(
                filepath, f_min, f_max, row_index=row_idx, channel=ch)

            intensity_fit, _, intensity_poly, _, _ = replay_engine.get_model_components(
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

            # Components 탭도 replay_engine의 gas_list/interpolators로 그려야 하므로
            # monitor의 엔진 참조를 렌더링 동안만 바꿔치기하고 원복한다.
            old_monitor_engine = self.monitor.engine
            self.monitor.engine = replay_engine
            try:
                self.monitor.update_spectrum(
                    pixel_idx, intensity_raw, intensity_fit, intensity_poly, params, f"{fname} (Replay)"
                )
            finally:
                self.monitor.engine = old_monitor_engine
            view_ch = getattr(self.monitor, '_view_channel', 1)
            if view_ch != ch:
                _fail(f"replay is CH{ch} but Monitor 'Show channel' is stuck on CH{view_ch} "
                      "— plot was skipped by the channel filter.")
            else:
                self.status.setText(f"Replay: {fname} (CH{ch})")
                self.status.setStyleSheet("color: green;")
        except Exception as e:
            print(f"Double-click viewer failed to load: {e}")
            _fail(f"failed to load '{fname}': {e}")
                
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
                ri  = self._row_index_from_display_name(fname)
                try:
                    pixel_idx, intensity_raw, _, _, _ = DataIO.load_measurement_with_hk(fp, pixel_min=0, row_index=ri)
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


    @staticmethod
    def _load_wavecal_array(path):
        """wavecal 파일 → 1D nm 배열(load_wavelength_cal과 동일 파싱). 실패 시 None."""
        try:
            try:
                df = pd.read_csv(path, sep=r'\s+', header=None)
            except Exception:
                df = pd.read_csv(path, sep=',', header=None)
            for i in range(df.shape[1]):
                col = pd.to_numeric(df.iloc[:, i], errors='coerce').dropna()
                if len(col) > 10:
                    return col.values.flatten()
        except Exception:
            pass
        return None

    def _build_engine_from_config(self, cfg):
        """채널 config(dict)로 독립 UniversalEngine 생성(자체 wavecal+references+scaling).
        채널별 병렬 피팅용. 실패한 ref는 건너뛴다."""
        from core.engine import UniversalEngine
        eng = UniversalEngine()
        wave = None
        wlp = resolve_ref_path(cfg.get('wl_path', ''))
        if wlp and os.path.exists(wlp):
            wave = self._load_wavecal_array(wlp)
        if wave is None:   # 폴백: 현재 로드된 마스터 wavecal
            wl = getattr(self, 'wavelengths', None)
            wave = np.asarray(wl, dtype=float).flatten() if wl is not None else None
        if wave is not None:
            eng.set_wavelength_axis(wave)
        for ref in cfg.get('refs', []):
            ref_path = resolve_ref_path(ref.get('path', ''))
            if os.path.exists(ref_path):
                try:
                    eng.add_reference(name=ref['name'], filepath=ref_path,
                                      wave_nm=wave, multiplier=10.0 ** ref.get('mult', 0))
                except Exception as e:
                    print(f"[ch engine] ref failed {ref.get('name')}: {e}")
        try:
            eng.apply_ils_convolution(0.0)
        except Exception:
            pass
        return eng

    # ── 채널 탭(독립 설정) ─────────────────────────────────────────────
    # ══════════════════════════════════════════════════════════════════════
    # §14 채널 탭 + 시나리오 config
    # ══════════════════════════════════════════════════════════════════════
    def _on_channel_tab_changed(self, idx):
        """탭 전환 — 현재 채널 설정을 저장하고 선택 채널 설정을 UI/엔진에 로드."""
        if self._switching_channel or idx < 0:
            return
        ch = self._channel_tabbar.tabData(idx)
        if ch is None or ch == self._active_channel:
            return
        # 현재 채널 스냅샷 저장(단, 방금 삭제된 채널은 다시 저장하지 않음)
        if self._active_channel in self._channel_configs:
            self._channel_configs[self._active_channel] = self._capture_config()
            self._channel_files[self._active_channel] = list(self.file_list)
        self._active_channel = ch
        cfg = self._channel_configs.get(ch)
        if cfg is not None:
            self._switching_channel = True
            try:
                self._apply_config(cfg, load_refs=True)
            finally:
                self._switching_channel = False
        # 표/그래프를 이 채널이 들고 있는 데이터로 교체
        self._show_channel_files(ch)

    def _show_channel_files(self, ch):
        """선택 채널이 보유한 파일 리스트를 표에 표시(소유권은 그대로).

        피팅 결과가 이미 있으면(self.results) 표는 건드리지 않는다 — 멀티채널 결과 테이블은
        모든 채널을 한 표에 같이 보여주는 게 원래 의도라(Ch 칼럼으로 구분), 탭을 바꿀 때마다
        그 채널의 '입력 파일 목록' 미리보기로 표를 갈아치우면 방금 돌린 피팅 결과가 통째로
        사라진 것처럼 보인다. file_list 자체는(Setup 등 다른 코드가 참조하므로) 그대로 갱신한다."""
        self.file_list = list(self._channel_files.get(ch, []))
        if self.results:
            self.status.setText(f"CH{ch} config — results table kept ({len(self.results)} rows)")
            return
        self.table.setRowCount(len(self.file_list))
        self.table.clearContents()
        for i, fp in enumerate(self.file_list):
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(self._entry_filepath(fp))))
        self.status.setText(f"CH{ch} — {len(self.file_list)} file(s)")
        if self.file_list:
            self._auto_detect_channels()

    def _add_channel_tab(self):
        """— 현재 채널 설정을 복사한 새 채널 탭 생성(시작값=복사본)."""
        import copy
        self._channel_configs[self._active_channel] = self._capture_config()
        new_ch = (max(self._channel_configs.keys()) + 1) if self._channel_configs else 1
        self._channel_configs[new_ch] = copy.deepcopy(self._channel_configs[self._active_channel])
        self._channel_files[new_ch] = []          # 새 채널 데이터는 비어서 시작(설정만 복사)
        i = self._channel_tabbar.addTab(f"CH{new_ch}")
        self._channel_tabbar.setTabData(i, new_ch)
        self._channel_tabbar.setCurrentIndex(i)   # currentChanged → 복사본 적용

    def _del_channel_tab(self):
        """— 현재 채널 삭제(최소 1채널 유지)."""
        if self._channel_tabbar.count() <= 1:
            return
        idx = self._channel_tabbar.currentIndex()
        ch = self._channel_tabbar.tabData(idx)
        self._channel_configs.pop(ch, None)
        self._channel_files.pop(ch, None)
        # 제거된 채널을 다시 저장하지 않도록 active를 무효화 후 removeTab
        # → currentChanged가 인접 채널을 로드.
        self._active_channel = None
        self._channel_tabbar.removeTab(idx)

    @staticmethod
    def _time_shift_hours(val):
        """저장값 → 출력 시각에 그대로 더할 시프트(시간, float).
        신규 포맷은 float. 레거시 'input_tz' 문자열 호환: 'KST(+9)'는 옛 동작(출력 −9h)과
        같게 −9.0, 그 외/'UTC'/빈값은 0.0으로 매핑."""
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().upper()
        if s.startswith('KST'):
            return -9.0
        try:
            return float(s.replace('UTC', '').replace('H', '').strip() or 0)
        except ValueError:
            return 0.0

    def _capture_config(self):
        """현재 UI/엔진 설정 전체를 dict로 캡처 — 채널 전환·복사·시나리오 저장에 재사용.
        (레퍼런스 경로·배율, wavecal, 픽셀/nm 핏레인지, poly/step/λ/robust/kalman, cavity)"""
        refs_data = []
        for rw in getattr(self, 'ref_widgets', []):
            if rw['n'].text() and rw['fp']:
                refs_data.append({"name": rw['n'].text(), "path": rw['fp'], "mult": rw['mult'].value()})
        return {
            "wl_path": getattr(self, 'loaded_wl_path', ""),
            "refs": refs_data,
            "data_label": self._ed_ch_datalabel.text().strip() if hasattr(self, '_ed_ch_datalabel') else "",
            "time_shift_h": self.spin_time_shift.value() if hasattr(self, 'spin_time_shift') else 0.0,
            "gas_temp": self.spin_gas_temp.value() if hasattr(self, 'spin_gas_temp') else 0.0,
            "f_min": self.txt_min.text(),
            "f_max": self.txt_max.text(),
            "fit_start_nm": self.spin_fit_start_nm.value(),
            "fit_end_nm": self.spin_fit_end_nm.value(),
            "fit_unit": self.cb_fit_unit.currentText() if hasattr(self, 'cb_fit_unit') else "nm",
            "poly_deg": self.spin_poly_deg.value(),
            "step_limit": self.spin_step_limit.value() if hasattr(self, 'spin_step_limit') else 0.5,
            "ref_props": dict(getattr(self, 'ref_props', {})),
            "tikhonov_lambda": self.spin_lambda.value() if hasattr(self, 'spin_lambda') else 0.0,
            "use_robust": self.chk_robust.isChecked() if hasattr(self, 'chk_robust') else False,
            "allow_negative_gas": self.chk_allow_neg.isChecked(),
            "kalman_q": self.spin_kalman_q.value() if hasattr(self, 'spin_kalman_q') else 0.0005,
            "kalman_r": self.spin_kalman_r.value() if hasattr(self, 'spin_kalman_r') else 0.050,
            "cavity_d": self.spin_d_len.value() if hasattr(self, 'spin_d_len') else 100.0,
            "rl_factor": self.spin_rl_factor.value() if hasattr(self, 'spin_rl_factor') else 1.0,
        }

    def _calibration_state(self):
        """`.meta.json`용 캘리브 세트 식별자. `_capture_config`가 안 담는 것들만 모은다.

        파일은 **basename**으로 남긴다 — 절대경로를 넣으면 같은 캘리브가 머신마다 다른
        runid가 된다. 'Auto from ZA/He scans'처럼 파일이 아닌 상태도 그 문구 그대로 남겨야
        "무엇으로 보정했나"가 보존된다."""
        def _lbl(name, default=""):
            w = getattr(self, name, None)
            return w.text().strip() if w is not None else default

        def _val(name, default=None):
            w = getattr(self, name, None)
            return w.value() if w is not None else default

        return {
            "wavecal": os.path.basename(getattr(self, 'loaded_wl_path', "") or ""),
            "ils_fwhm_nm": _val('spin_fwhm_nm'),
            "ils_fwhm_px": _val('spin_fwhm'),
            "i0": _lbl('lbl_i0_path'),
            "r": _lbl('lbl_r_path'),
            "dark": _lbl('lbl_dark_path'),
            "dark_scale": _val('spin_dark_scale'),
            "offset": _lbl('lbl_offset_path'),
            "offset_scale": _val('spin_offset_scale'),
            "stray_light": _val('spin_stray_light'),
            "temporal_i0": bool(getattr(self, 'chk_temporal_i0', None)
                                and self.chk_temporal_i0.isChecked()),
            "d_cm": _val('spin_d_len'),
            "rl_factor": _val('spin_rl_factor'),
        }

    def _qc_state(self):
        """`.meta.json`용 QC/후처리 상태. 재핏 없이 적용되는 값이라 **저장 시점**이 정본이다."""
        def _val(name, default=None):
            w = getattr(self, name, None)
            return w.value() if w is not None else default

        def _chk(name):
            w = getattr(self, name, None)
            return bool(w is not None and w.isChecked())

        return {
            "enabled": _chk('chk_qc'),
            "auto_k": _val('spin_qc_k'),
            "rms_max": _val('spin_qc_rms'),
            "snr_floor": _val('spin_qc_snr'),
            "settling": _chk('chk_settle'),
            "settling_n": _val('spin_settle_n'),
            "ok_rms_pct": _val('spin_rms_thresh'),
            "tikhonov": _val('spin_lambda', 0.0),
            "robust": _chk('chk_robust'),
            "kalman_q": _val('spin_kalman_q'),
            "kalman_r": _val('spin_kalman_r'),
        }

    def _apply_config(self, scenario, load_refs=True):
        """_capture_config 로 만든 dict를 UI/엔진에 복원. load_refs=False면 레퍼런스/엔진은 건드리지 않음."""
        self.txt_min.setText(str(scenario.get("f_min", "")))
        self.txt_max.setText(str(scenario.get("f_max", "")))
        if hasattr(self, '_ed_ch_datalabel'):
            self._ed_ch_datalabel.setText(scenario.get("data_label", ""))
        if hasattr(self, 'spin_time_shift'):
            self.spin_time_shift.setValue(
                self._time_shift_hours(scenario.get("time_shift_h", scenario.get("input_tz", 0.0))))
        if hasattr(self, 'spin_gas_temp'):
            self.spin_gas_temp.setValue(scenario.get("gas_temp", 0.0))
        if "fit_start_nm" in scenario:
            self.spin_fit_start_nm.setValue(scenario["fit_start_nm"])
        if "fit_end_nm" in scenario:
            self.spin_fit_end_nm.setValue(scenario["fit_end_nm"])
        if hasattr(self, 'cb_fit_unit') and "fit_unit" in scenario:
            self.cb_fit_unit.setCurrentText(scenario.get("fit_unit", "nm"))
        self.spin_poly_deg.setValue(scenario.get("poly_deg", 3))
        if hasattr(self, 'spin_step_limit'):
            self.spin_step_limit.setValue(scenario.get("step_limit", 0.5))
        self.ref_props = scenario.get("ref_props", {})
        if hasattr(self, 'spin_lambda'):
            self.spin_lambda.setValue(scenario.get("tikhonov_lambda", 0.0))
        if hasattr(self, 'chk_robust'):
            self.chk_robust.setChecked(scenario.get("use_robust", False))
        if hasattr(self, 'chk_allow_neg'):
            value, provenance = _scenario_gas_policy(
                scenario, self.chk_allow_neg.isChecked())
            self.chk_allow_neg.setChecked(value)
            self._gas_policy_provenance = provenance
            if provenance.startswith("legacy"):
                QMessageBox.warning(
                    self, "Legacy Fit Scenario",
                    "This scenario does not record the ±Neg gas policy. "
                    "The current checkbox value was preserved; verify it before running.")
        if hasattr(self, 'spin_kalman_q'):
            self.spin_kalman_q.setValue(scenario.get("kalman_q", 0.0005))
        if hasattr(self, 'spin_kalman_r'):
            self.spin_kalman_r.setValue(scenario.get("kalman_r", 0.050))
        if hasattr(self, 'spin_d_len') and "cavity_d" in scenario:
            self.spin_d_len.setValue(scenario["cavity_d"])
        if hasattr(self, 'spin_rl_factor') and "rl_factor" in scenario:
            self.spin_rl_factor.setValue(scenario["rl_factor"])

        wl_path = resolve_ref_path(scenario.get("wl_path", ""))
        if wl_path and os.path.exists(wl_path):
            self.load_wavelength_cal(auto_path=wl_path)
        elif hasattr(self, 'lbl_wavecal'):
            self.lbl_wavecal.setText("wavecal: none")
            self.lbl_wavecal.setStyleSheet("color: #B71C1C; font-weight: bold; padding: 2px;")
            self.lbl_wavecal.setToolTip("No wavelength calibration loaded for this channel tab.")
        # L7: 가스별 Sh/Sq 모드 요약 갱신
        self._refresh_shsq_summary()

        if load_refs:
            refs = scenario.get("refs", [])
            # 기존 레퍼런스 UI/엔진 초기화 후 재구성
            for rw in getattr(self, 'ref_widgets', []):
                rw['w'].deleteLater()
            if hasattr(self, 'ref_widgets'):
                self.ref_widgets.clear()
            self.engine.clear_engine()
            for ref in refs:
                ref_path = resolve_ref_path(ref['path'])
                if os.path.exists(ref_path):
                    self.add_ref_row(name=ref['name'], path=ref_path)
                    self.ref_widgets[-1]['mult'].setValue(ref.get('mult', 0))
            if refs:
                self.lock_ref(silent=True)   # 채널 전환/시나리오 적용 자동 재락 — 팝업 없음

    def save_scenario(self):
        """모든 채널 탭 설정을 하나의 JSON으로 저장(v2). load_scenario로 채널 탭 복원."""
        # 현재 채널 스냅샷
        if self._active_channel in self._channel_configs:
            self._channel_configs[self._active_channel] = self._capture_config()
        chans = {c: v for c, v in self._channel_configs.items() if v is not None}
        if not chans:
            chans = {1: self._capture_config()}
        scenario = {
            "version": 2,
            "active": self._active_channel if self._active_channel in chans else sorted(chans)[0],
            "channels": {str(c): cfg for c, cfg in chans.items()},
        }
        cfg = chans.get(scenario["active"], next(iter(chans.values())))
        robust_str = "Robust" if cfg.get("use_robust") else "Std"

        # 파일명: 채널별 특징(라벨[윈도우_Ppoly_가스T]) 나열 → 한눈에 시나리오 구분
        def _ch_short(c, cc):
            lbl = (cc.get('data_label') or '').strip() or f"CH{c}"
            if cc.get('fit_unit') == 'px':
                win = f"{cc.get('f_min', '?')}-{cc.get('f_max', '?')}px"
            else:
                try:
                    win = f"{float(cc.get('fit_start_nm', 0)):.0f}-{float(cc.get('fit_end_nm', 0)):.0f}nm"
                except Exception:
                    win = "win?"
            try:
                gt = float(cc.get('gas_temp', 0) or 0)
            except Exception:
                gt = 0
            gtag = f"_gT{int(gt)}" if gt > 0 else ""
            return f"{lbl}[{win}_P{cc.get('poly_deg', '?')}{gtag}]"
        parts = [_ch_short(c, chans[c]) for c in sorted(chans)]
        default_fname = f"FitSet_{'_'.join(parts)}_{robust_str}.json"
        _start = os.path.join(self._dlg_dir('scenario'), default_fname) if self._dlg_dir('scenario') else default_fname
        path, _ = QFileDialog.getSaveFileName(self, "Save Fit Scenario", _start, "JSON Files (*.json)")
        self._dlg_dir('scenario', path)
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(scenario, f, indent=4)
                QMessageBox.information(self, "Success", f"{len(chans)} channels config saved!\nFile: {os.path.basename(path)}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Save Failed:\n{e}")

    def load_scenario(self):
        """저장된 fit 설정 JSON 복원. v2(채널들) / v1(단일) 모두 지원."""
        path, _ = QFileDialog.getOpenFileName(self, "Load Fit Scenario", self._dlg_dir('scenario'), "JSON Files (*.json)")
        if not path:
            return
        self._dlg_dir('scenario', path)
        self._scenario_name = os.path.splitext(os.path.basename(path))[0]  # .meta.json provenance
        try:
            with open(path, 'r', encoding='utf-8') as f:
                scenario = json.load(f)
            if isinstance(scenario, dict) and "channels" in scenario:   # v2 멀티채널
                chans = {int(c): cfg for c, cfg in scenario["channels"].items()}
                legacy_channels = [ch for ch, cfg in chans.items()
                                   if "allow_negative_gas" not in cfg]
                if legacy_channels:
                    fallback = self.chk_allow_neg.isChecked()
                    for ch in legacy_channels:
                        chans[ch] = dict(chans[ch], allow_negative_gas=fallback)
                    self._legacy_gas_policy_channels = tuple(legacy_channels)
                    QMessageBox.warning(
                        self, "Legacy Fit Scenario",
                        f"Channels {legacy_channels} do not record the ±Neg policy. "
                        f"They were explicitly migrated to the current value ({fallback}); verify before RUN.")
                self._load_channel_scenario(chans, scenario.get("active", sorted(chans)[0]))
                QMessageBox.information(self, "Auto-Load Success",
                                        f"{len(chans)} channels config restored (channel tabs).\n[Load Data] then RUN!")
            else:   # v1 단일(하위호환)
                self._apply_config(scenario, load_refs=True)
                self._channel_configs = {1: self._capture_config()}
                QMessageBox.information(self, "Success", "Config restored (single channel).")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load scenario:\n{e}")

    def _load_channel_scenario(self, chans, active):
        """여러 채널 config를 채널 탭으로 복원."""
        tb = self._channel_tabbar
        self._switching_channel = True
        while tb.count() > 0:
            tb.removeTab(0)
        for ch in sorted(chans):
            i = tb.addTab(f"CH{ch}")
            tb.setTabData(i, ch)
        self._switching_channel = False
        self._channel_configs = dict(chans)
        # 채널 데이터 저장소: 기존 보유분 유지, 신규 채널만 빈 리스트
        self._channel_files = {ch: self._channel_files.get(ch, []) for ch in chans}
        if active not in chans:
            active = sorted(chans)[0]
        self._active_channel = active
        # 활성 탭 선택(핸들러 억제) 후 직접 apply
        for i in range(tb.count()):
            if tb.tabData(i) == active:
                self._switching_channel = True
                tb.setCurrentIndex(i)
                self._switching_channel = False
                break
        self._apply_config(chans[active], load_refs=True)
