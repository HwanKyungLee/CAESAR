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
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QFileDialog,
                             QTableWidget, QTableWidgetItem, QMessageBox,
                             QProgressBar, QGroupBox, QLineEdit, QScrollArea, QDialog,
                             QComboBox, QSplitter, QTabWidget, QTabBar, QDoubleSpinBox, QSpinBox,
                             QCheckBox, QFormLayout, QMenu, QRadioButton)
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


def _scenario_gas_policy(scenario, current):
    """Restore an explicit saved policy; old files visibly preserve the current UI policy."""
    if "allow_negative_gas" not in scenario:
        warnings.warn("legacy scenario has no allow_negative_gas; preserving current checkbox value",
                      RuntimeWarning, stacklevel=2)
        return bool(current), "legacy scenario fallback: current checkbox"
    value = scenario["allow_negative_gas"]
    if not isinstance(value, bool):
        raise TypeError("scenario allow_negative_gas must be bool")
    return value, "scenario"


def _channel_worker_gas_policy(use_cfg, cfg, live_value):
    if not isinstance(live_value, bool):
        raise TypeError("live allow_negative_gas must be bool")
    return _scenario_gas_policy(cfg, live_value)[0] if use_cfg else live_value

class CAESARAnalyzer(QMainWindow):
    """
    Main Window Controller for Augur v1.0 (CAESAR 분석 소프트웨어, 구 "CAESAR Pro").
    Integrates and commands all modules (Engine, Generators, Calibrations, Worker Threads, and Monitors).
    """
    # ══════════════════════════════════════════════════════════════════════
    #  CAESARAnalyzer — 메서드 목차 (각 섹션은 "§N" 으로 검색)
    # ══════════════════════════════════════════════════════════════════════
    #   §1  Init & UI 구성 (init_ui, showEvent, shortcuts)
    #   §2  Setup 탭: daily-run + R/Leff 차트
    #   §3  Cavity 탭 + FWHM/ILS 검증
    #   §4  입력: I0 / dark / offset / flags
    #   §5  알파 생성 (export + generator)
    #   §6  I0 / R 진단 (auto-extract, diagnostic plot)
    #   §7  다이얼로그 런처: ref / R / wavecal
    #   §8  Test Fit (탭1 자동 최적화+Apply / 탭2 1-scan 미리보기 — gui/test_fit_dialog.py)
    #   §9  핏 범위 + 레퍼런스 관리
    #   §10 데이터 로드 + 채널 분배
    #   §11 분석 실행 / 워커 / autosave / closeEvent
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
    # §3  Cavity 탭 + FWHM/ILS 검증
    # ══════════════════════════════════════════════════════════════════════
    def setup_cavity_tab(self):
        """Configure the layout for the Pre-Analysis Cavity Setup tab."""
        # Main horizontal layout: Controls on Left, Diagnostics on Right
        main_layout = QHBoxLayout(self.setup_tab)
        
        # --- Left Panel: Controls ---
        control_layout = QVBoxLayout()

        # Daily Run(Scenario + Setup Status) 흡수 — Setup 좌측 상단
        if hasattr(self, 'daily_run_tab'):
            control_layout.addWidget(self.daily_run_tab)

        # Group: Daily-use tools
        grp_calib = QGroupBox("Tools")
        lay_calib = QVBoxLayout()

        btn_calib_tool = QPushButton("Wavelength Calibration Tool")
        btn_calib_tool.clicked.connect(self.open_wavelength_calibration)

        btn_ref_gen = QPushButton("Reference Generator")
        btn_ref_gen.clicked.connect(self.open_reference_generator)
        btn_ref_gen.setStyleSheet("font-weight: bold;")

        btn_r_trend = QPushButton("R Calibrator")
        btn_r_trend.clicked.connect(self.open_r_trend_monitor)
        btn_r_trend.setStyleSheet("font-weight: bold;")
        btn_r_trend.setToolTip(
            "Per-channel reflectance calibration (R Calibrator).\n"
            "Auto-loads left-panel channel settings → computes/saves R time-series per channel.\n"
            "Includes saving R(t).npz for α and incremental append."
        )

        # Peak Trend 버튼은 제거(2026-06): R(t) 시간보간이 인젝션 불량 구간 스킵·보간을
        #   처리하고 R Calibrator가 같은 scan_directory를 재사용하므로 일상 흐름에서 중복.
        #   ui_peak_trend.py / open_peak_trend()는 raw peak 디버깅용으로 보존(배선만 해제).

        lay_calib.addWidget(btn_calib_tool)
        lay_calib.addWidget(btn_ref_gen)
        lay_calib.addWidget(btn_r_trend)
        grp_calib.setLayout(lay_calib)
        control_layout.addWidget(grp_calib)

        # Group: α Pipeline — raw→α 생성과 RUN 전 1-scan 검증. 캘리브 유틸(Tools)과
        #   성격이 달라 별도 그룹으로 분리하고, 매일 쓰는 핵심 동작이라 강조(bold+테두리) 유지.
        grp_pipe = QGroupBox("α Pipeline")
        lay_pipe = QVBoxLayout()

        # Alpha Generator — raw → alpha 생성은 별도 팝업창에서(분석=알파 피팅과 분리).
        # 분석(좌측)은 알파를 넣고 RUN해 피팅. 알파 생성만 여기 Setup에서 창으로.
        btn_alpha_gen = QPushButton("Alpha Generator")
        btn_alpha_gen.clicked.connect(self.open_alpha_generator)
        btn_alpha_gen.setStyleSheet("font-weight: bold; padding: 8px; border: 1px solid #90CAF9;")
        btn_alpha_gen.setToolTip(
            "Takes raw measurement files in a popup and generates α spectra (*_alpha_trace.dat).\n"
            "wavecal/fit-range/cavity/flags use this main window's settings.")

        # Test Fit — RUN 전에 세팅을 검증: 탭1(자동 파라미터 최적화 추천+Apply) +
        # 탭2(첫 알파 스캔 1개 즉석 핏 미리보기, 기존 동작 그대로).
        btn_test_fit = QPushButton("Test Fit")
        btn_test_fit.setStyleSheet("font-weight: bold; padding: 6px; border: 1px solid #A5D6A7;")
        btn_test_fit.setToolTip(
            "Optimize tab: auto-recommend poly/shift/squeeze/step_limit from a 12-scan\n"
            "sample (worker thread, human must click Apply).\n"
            "Preview tab: fit only the first loaded alpha scan and show data+model\n"
            "overlay, residual, reference overlays, retrieved ppb and shift/squeeze.")
        btn_test_fit.clicked.connect(self._open_test_fit_dialog)

        lay_pipe.addWidget(btn_alpha_gen)
        lay_pipe.addWidget(btn_test_fit)
        grp_pipe.setLayout(lay_pipe)
        control_layout.addWidget(grp_pipe)

        # S-A: 고급 설정 구분선 — Cavity/Override/Detector는 캠페인 시작 때 한 번 맞추고
        # 평소엔 안 건드리므로 접이식 '고급' 영역으로 묶는다.
        _adv_hdr = QLabel("──  Advanced (set once per campaign)  ──")
        _adv_hdr.setStyleSheet("color:#90A4AE; font-size:11px; padding-top:4px;")
        control_layout.addWidget(_adv_hdr)

        # Group 3: Cavity Setup — only d, RL, Leff (everything else from raw file)
        self._cavity_visible = False
        self._btn_toggle_cavity = QPushButton("▶ Cavity Setup (d, RL, L_eff)")
        self._btn_toggle_cavity.setStyleSheet(
            "text-align: left; color: #546E7A; border: 1px solid #CFD8DC; padding: 3px 8px;")
        control_layout.addWidget(self._btn_toggle_cavity)
        self._cavity_container = QWidget()
        self._cavity_container.setVisible(False)
        _cav_outer = QVBoxLayout(self._cavity_container)
        _cav_outer.setContentsMargins(0, 0, 0, 0)
        grp_physics = QGroupBox("Cavity Setup")
        lay_physics = QFormLayout()

        # Auto-detected channel info (read-only — updated when files are loaded)
        self._detected_channels = 1   # updated by _auto_detect_channels()
        self.lbl_channel_info = QLabel("—  (auto-detected after load)")
        self.lbl_channel_info.setStyleSheet("color: #546E7A; font-style: italic;")
        lay_physics.addRow("Channel detect:", self.lbl_channel_info)

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
            "Purge-gas effective cavity correction RL = d_eff / d\n"
            "The purge-gas region (preventing mirror contamination) has no sample,\n"
            "so the effective measurement path is shorter than the physical length.\n"
            "MATLAB reference (CAESAR Araon 2025 ASIA-AQ measured):\n"
            "  CH1 (NO2/CHOCHO): 0.9330\n"
            "  CH2 (HONO/HCHO): 0.9950\n"
            "  CH3 (NO2/CHOCHO): 0.9968\n"
            "1.0 = no correction (default; enter the measured value if available)"
        )
        lay_rl.addWidget(self.spin_rl_factor)
        _rl_hint = QLabel("  ← CH1 0.933 / CH2 0.995 / CH3 0.997")
        from PyQt6.QtWidgets import QSizePolicy as _SP
        _rl_hint.setSizePolicy(_SP.Policy.Ignored, _SP.Policy.Preferred)
        _rl_hint.setToolTip("Reference RL factors: CH1 0.9330 / CH2 0.9950 / CH3 0.9968")
        lay_rl.addWidget(_rl_hint)
        lay_rl.addStretch()
        lay_physics.addRow("RL (Purge correction):", lay_rl)

        # Effective path length display (L_eff = d / (1 - R_mean))
        self.lbl_leff = QLabel("L_eff: — (auto from He scans)")
        from PyQt6.QtWidgets import QSizePolicy as _SP2
        self.lbl_leff.setSizePolicy(_SP2.Policy.Ignored, _SP2.Policy.Preferred)
        self.lbl_leff.setStyleSheet("color: #0277BD; font-weight: bold;")
        lay_physics.addRow("Effective Path:", self.lbl_leff)

        grp_physics.setLayout(lay_physics)
        _cav_outer.addWidget(grp_physics)
        control_layout.addWidget(self._cavity_container)

        def _toggle_cavity():
            self._cavity_visible = not self._cavity_visible
            self._cavity_container.setVisible(self._cavity_visible)
            self._btn_toggle_cavity.setText(
                ("▼ " if self._cavity_visible else "▶ ") + "Cavity Setup (d, RL, L_eff)")
        self._btn_toggle_cavity.clicked.connect(_toggle_cavity)

        # ▶ Manual Override (collapsed by default)
        # I₀ / R / flags / T / P all come from raw file HK data.
        # This section is only for edge cases: separate files, non-standard flags, fallback T/P.
        self._manual_override_visible = False
        self._btn_toggle_override = QPushButton("▶ Manual Override")
        self._btn_toggle_override.setStyleSheet(
            "text-align: left; color: #546E7A; "
            "border: 1px solid #CFD8DC; padding: 3px 8px;")
        control_layout.addWidget(self._btn_toggle_override)

        self._manual_override_container = QWidget()
        self._manual_override_container.setVisible(False)
        _ov_outer = QVBoxLayout(self._manual_override_container)
        _ov_outer.setContentsMargins(0, 0, 0, 0)

        grp_ov = QGroupBox("Manual Override")
        grp_ov.setStyleSheet("QGroupBox { color: #546E7A; }")
        lay_ov = QFormLayout()

        # I0 Setup
        self.lbl_i0_path = QLabel("Auto from ZA scans")
        self.lbl_i0_path.setStyleSheet("color: #546E7A;")
        # 라벨이 좌측 컬럼 최소폭을 키우지 않게 축소 허용(긴 경로는 툴팁/말줄임).
        from PyQt6.QtWidgets import QSizePolicy as _SPi0
        self.lbl_i0_path.setSizePolicy(_SPi0.Policy.Ignored, _SPi0.Policy.Preferred)
        btn_browse_i0 = QPushButton("Browse I₀")
        btn_browse_i0.clicked.connect(self.browse_i0_file)
        btn_auto_i0 = QPushButton("Auto")   # 텍스트 축약(폭 절감) — 설명은 툴팁
        btn_auto_i0.setToolTip("Auto-extract I₀ by averaging ZA-flagged scans in the loaded files.")
        btn_auto_i0.clicked.connect(self.auto_extract_i0)
        lay_i0 = QHBoxLayout()
        lay_i0.addWidget(self.lbl_i0_path, 1)
        lay_i0.addWidget(btn_browse_i0)
        lay_i0.addWidget(btn_auto_i0)
        lay_ov.addRow("I₀ (Zero-Air):", lay_i0)

        # Temporal I0 interpolation toggle
        self.chk_temporal_i0 = QCheckBox("Temporal I₀ (lamp drift)")
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
            "Flag numbers averaged into Zero-Air I₀ (comma-separated)\n"
            "CAESAR Araon: 500=injecting(pure), 501=setflow, 502/503=wait\n"
            "default 500 (strict) — 501-503 are cavity-unfilled and contaminate I0.\n"
            "  For legacy data, you can manually enter \"500,501,502,503\" here."
        )
        lay_flags.addWidget(QLabel("ZA:"))
        lay_flags.addWidget(self.txt_flag_za)
        lay_flags.addSpacing(8)
        self.txt_flag_he = QLineEdit("510")
        self.txt_flag_he.setFixedWidth(int(130 * self._s))
        self.txt_flag_he.setToolTip(
            "Flag numbers used for Helium R-cal (comma-separated)\n"
            "CAESAR Araon: 510=injecting(pure), 511=setflow, 512/513=wait\n"
            "default 510 (strict) — 511-513 are cavity-unfilled and contaminate R-cal.\n"
            "  For legacy data, you can manually enter \"510,511,512,513\" here."
        )
        lay_flags.addWidget(QLabel("He:"))
        lay_flags.addWidget(self.txt_flag_he)
        lay_flags.addWidget(QLabel("Amb:"))
        self.txt_flag_amb = QLineEdit("1")
        self.txt_flag_amb.setFixedWidth(int(50 * self._s))
        self.txt_flag_amb.setToolTip(
            "Ambient measurement flag number\n"
            "MATLAB Alpha script convention: flag==1"
        )
        lay_flags.addWidget(self.txt_flag_amb)
        lay_flags.addStretch()
        lay_ov.addRow("Measurement state flags:", lay_flags)

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
                "▼ Manual Override"
                if self._manual_override_visible else
                "▶ Manual Override")
        self._btn_toggle_override.clicked.connect(_toggle_override)

        # Group 2b: Detector Corrections (collapsible — rarely needed in daily ops)
        self._det_corr_visible = False
        self._btn_toggle_det = QPushButton("▶ Detector Corrections")
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
                "▼ Detector Corrections"
                if self._det_corr_visible else
                "▶ Detector Corrections")
        self._btn_toggle_det.clicked.connect(_toggle_det)

        control_layout.addStretch(1)
        # 좌측 컨트롤 컬럼을 컨테이너로 감싸 최대폭을 건다. Manual Override/Detector 등
        # 접이식 섹션을 펼칠 때 안쪽 넓은 행이 컬럼 '최소폭'을 키워 우측 Cavity Diagnostics를
        # 밀어내던 문제 차단 — 펼침이 옆이 아니라 아래(스크롤)로 가게 한다. 캡은 접힘 자연폭보다
        # 넉넉해 상단 행 클리핑 위험 없음.
        _left_container = QWidget()
        _left_container.setLayout(control_layout)
        _left_container.setMaximumWidth(int(520 * self._s))   # 초기 폴백; 아래서 접힘폭으로 정밀화
        main_layout.addWidget(_left_container, stretch=1)
        self._setup_left_container = _left_container
        # 접이식 섹션은 시작 시 모두 숨김 → 이 시점 레이아웃이 곧 '접힘 자연폭'.
        # 이벤트루프 첫 틱에 그 폭으로 최대폭을 못박아 펼침 시 옆으로 커지는 점프를 0으로.
        from PyQt6.QtCore import QTimer as _QTimer

        def _cap_left_to_collapsed():
            w = _left_container.sizeHint().width()
            if w > 0:
                _left_container.setMaximumWidth(w)
        _QTimer.singleShot(0, _cap_left_to_collapsed)

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

        self.plot_diagnostic = pg.PlotWidget(title="I0 & R(λ) spectrum")
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
        self._diag_tabs.addTab(tab_spectral, "R(λ) Spectrum")

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
        self._setup_r_trend_pw.setTitle("R time-series (shown after running R Trend Monitor)")

        _ts_ax_l = pg.DateAxisItem(orientation='bottom')
        self._setup_leff_pw = pg.PlotWidget()
        self._setup_leff_pw.setAxisItems({'bottom': _ts_ax_l})
        self._setup_leff_pw.setLabel('left', 'Leff (km)')
        self._setup_leff_pw.showGrid(x=True, y=True, alpha=0.3)
        self._setup_leff_pw.setTitle("Leff time-series")

        # R-cal 품질 readout — 채널별 R̄·Leff·He/ZA contrast·valid%·cycle수.
        # 인젝션 불량(낮은 contrast/valid)을 알파 굽기 전에 한눈에 잡는 게이지.
        self._setup_rt_readout = QLabel("R-cal quality: (run R Calibrator)")
        self._setup_rt_readout.setStyleSheet(
            "color:#37474F; font-family:Consolas,monospace; font-size:11px; padding:2px 4px;")
        # 줄바꿈 끄고 높이 상한 — 좁은 폭에서 라벨이 줄바꿈으로 부풀어 패널이 스크롤되던 것 방지.
        self._setup_rt_readout.setWordWrap(False)
        self._setup_rt_readout.setMaximumHeight(int(74 * self._s))
        from PyQt6.QtWidgets import QSizePolicy as _SPrt
        self._setup_rt_readout.setSizePolicy(_SPrt.Policy.Ignored, _SPrt.Policy.Maximum)
        self._setup_rt_readout.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay_trend.addWidget(self._setup_rt_readout)

        lay_trend.addWidget(self._setup_r_trend_pw, stretch=1)
        lay_trend.addWidget(self._setup_leff_pw, stretch=1)
        self._diag_tabs.addTab(tab_trend, "R/Leff Trend")

        # ── Tab 2: Pipeline Health — RUN 전에 "이 산출물로 긴 핏을 돌려도 되나?"를 사전점검 ──
        # α 폴더 스캔(너희가 반복적으로 데인 "조용히 오염된 알파" — 트렁케이트·6175 bin당
        # 1트레이스·flatline 퇴화)에 더해, core/health_checks.py 배터리(웨이브칼·레퍼런스
        # 공선성·Rayleigh 물리·R(t) 물리성)를 같이 돌려 전체 핏 파이프라인을 한 번에 판정한다.
        # (기존엔 α 파일 품질만 봤다 — fit_optimizer_handoff.md §7·§10-C-4 미연결 항목 연결.)
        from PyQt6.QtWidgets import QSizePolicy
        tab_aqc = QWidget()
        lay_aqc = QVBoxLayout(tab_aqc)
        lay_aqc.setContentsMargins(4, 4, 4, 4)
        lay_aqc.setSpacing(4)

        _aqc_ctl = QHBoxLayout()
        _btn_aqc_dir = QPushButton("α Folder…")
        _btn_aqc_dir.clicked.connect(self._alpha_qc_pick_folder)
        self.lbl_aqc_dir = QLabel("(none)")
        self.lbl_aqc_dir.setStyleSheet("color:#555;")
        self.lbl_aqc_dir.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        _btn_aqc_rnpz = QPushButton("R(t) npz…")
        _btn_aqc_rnpz.setToolTip(
            "Optional: R_<channel>.npz (R Trend ▸ 'save R(t) for α') to physics-check R/Leff.\n"
            "Skipped if not set.")
        _btn_aqc_rnpz.clicked.connect(self._pipeline_qc_pick_r_npz)
        self.lbl_aqc_rnpz = QLabel("(none)")
        self.lbl_aqc_rnpz.setStyleSheet("color:#555;")
        self._aqc_r_npz = None
        self._btn_aqc_run = QPushButton("Run Pipeline Check")
        self._btn_aqc_run.setStyleSheet("font-weight:bold;")
        self._btn_aqc_run.clicked.connect(self._alpha_qc_run)
        self._aqc_folder = None
        self.chk_aqc_auto = QCheckBox("Auto-check after Alpha Gen")
        self.chk_aqc_auto.setToolTip(
            "When Alpha Generator finishes, jump to this tab with the output folder\n"
            "pre-filled and (if checked) run the health check automatically.")
        self._btn_aqc_fitwin = QPushButton("Fit window")
        self._btn_aqc_fitwin.setToolTip(
            "Zoom X to the fit window (Setup ▸ fit start~end nm) and auto-fit Y to the\n"
            "mean α inside it — strips the edge noise so the real structure is visible.")
        self._btn_aqc_fitwin.clicked.connect(self._alpha_qc_zoom_fit)
        self._btn_aqc_full = QPushButton("⤢ Full")
        self._btn_aqc_full.setToolTip("Reset to the full wavelength range (auto-range).")
        self._btn_aqc_full.clicked.connect(
            lambda: self._aqc_pw.enableAutoRange(axis='xy', enable=True))
        _aqc_ctl.addWidget(_btn_aqc_dir)
        _aqc_ctl.addWidget(self.lbl_aqc_dir, stretch=1)
        _aqc_ctl.addWidget(_btn_aqc_rnpz)
        _aqc_ctl.addWidget(self.lbl_aqc_rnpz)
        _aqc_ctl.addWidget(self.chk_aqc_auto)
        _aqc_ctl.addWidget(self._btn_aqc_fitwin)
        _aqc_ctl.addWidget(self._btn_aqc_full)
        _aqc_ctl.addWidget(self._btn_aqc_run)
        lay_aqc.addLayout(_aqc_ctl)

        self.lbl_aqc_readout = QLabel(
            "Pipeline health: pick an α folder (optional) and Run Pipeline Check — "
            "checks α files + wavecal + references + Rayleigh + R(t).")
        self.lbl_aqc_readout.setStyleSheet(
            "color:#37474F; font-family:Consolas,monospace; font-size:11px; padding:2px 4px;")
        self.lbl_aqc_readout.setWordWrap(False)
        self.lbl_aqc_readout.setMaximumHeight(int(150 * self._s))
        self.lbl_aqc_readout.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Maximum)
        self.lbl_aqc_readout.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay_aqc.addWidget(self.lbl_aqc_readout)

        self._aqc_pw = pg.PlotWidget()
        self._aqc_pw.showGrid(x=True, y=True, alpha=0.3)
        self._aqc_pw.setLabel('left', 'α (optical depth)')
        self._aqc_pw.setLabel('bottom', 'Wavelength (nm)')
        self._aqc_pw.setTitle("mean α + min/max envelope")
        self._aqc_pw.addLegend(offset=(10, 10))
        lay_aqc.addWidget(self._aqc_pw, stretch=1)

        self._tab_aqc = tab_aqc
        self._diag_tabs.addTab(tab_aqc, "Pipeline Health")

        # ── Tab 3: FWHM Best-Match (validate sweep refs against measured α) ──
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

        btn_pick_folder = QPushButton("Sweep Folder…")
        btn_pick_folder.clicked.connect(self._fwhm_pick_sweep_folder)
        self.lbl_fwhm_folder = QLabel("Not selected")
        self.lbl_fwhm_folder.setStyleSheet("color: #d32f2f;")
        row_f = QHBoxLayout()
        row_f.addWidget(btn_pick_folder)
        row_f.addWidget(self.lbl_fwhm_folder, stretch=1)
        ctl_lay.addRow("Folder:", row_f)

        self.rb_fwhm_alpha_engine = QRadioButton("Engine α (latest)")
        self.rb_fwhm_alpha_engine.setToolTip("Auto: latest *_alpha_trace.dat from alpha_save_dir")
        self.rb_fwhm_alpha_file   = QRadioButton("Load from file")
        self.rb_fwhm_alpha_folder = QRadioButton("Folder (mean α)")
        self.rb_fwhm_alpha_folder.setToolTip(
            "Point at a folder of *_alpha_trace.dat (recursively) — every scan in every\n"
            "file is averaged into one mean α spectrum, then matched against the sweep.")
        self.rb_fwhm_alpha_engine.setChecked(True)
        row_a1 = QHBoxLayout()
        row_a1.addWidget(self.rb_fwhm_alpha_engine)
        row_a1.addWidget(self.rb_fwhm_alpha_file)
        row_a1.addWidget(self.rb_fwhm_alpha_folder)
        ctl_lay.addRow("α source:", row_a1)

        btn_pick_alpha = QPushButton("Pick α file…")
        btn_pick_alpha.clicked.connect(self._fwhm_pick_alpha_file)
        self.lbl_fwhm_alpha = QLabel("(auto)")
        self.lbl_fwhm_alpha.setStyleSheet("color: #555;")
        row_a2 = QHBoxLayout()
        row_a2.addWidget(btn_pick_alpha)
        row_a2.addWidget(self.lbl_fwhm_alpha, stretch=1)
        ctl_lay.addRow("α file:", row_a2)

        btn_pick_alpha_dir = QPushButton("Pick α folder…")
        btn_pick_alpha_dir.clicked.connect(self._fwhm_pick_alpha_folder)
        self.lbl_fwhm_alpha_dir = QLabel("(none)")
        self.lbl_fwhm_alpha_dir.setStyleSheet("color: #555;")
        self._fwhm_alpha_folder = None
        row_a3 = QHBoxLayout()
        row_a3.addWidget(btn_pick_alpha_dir)
        row_a3.addWidget(self.lbl_fwhm_alpha_dir, stretch=1)
        ctl_lay.addRow("α folder:", row_a3)

        row_btn = QHBoxLayout()
        self.btn_fwhm_run = QPushButton("Run Validation")
        self.btn_fwhm_run.setStyleSheet("font-weight: bold;")
        self.btn_fwhm_run.clicked.connect(self._fwhm_run_validation)
        self.btn_fwhm_set_active = QPushButton("Set as NO2 ref")
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

        # FWHM Best-Match 탭 비활성화(2026-06): Reference Generator가 Hg 측정 dynamic ILS를
        # 이미 적용(Ref_*_Dynamic-ILS-Applied)하므로 중복이고, 단일-NO2-ref 매칭은 잔차가
        # 광대역 구조에 지배돼 작동 안 함(featureless, 실데이터 검증). 코드·메서드(_fwhm_*)는
        # 전부 보존 — 재활성화는 아래 addTab 주석만 해제하면 됨.
        self._tab_fwhm = tab_fwhm   # 미부착 보존(C++ GC 방지용 참조)
        # self._diag_tabs.addTab(tab_fwhm, "🎯 FWHM Best-Match")

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
        self.lbl_fwhm_folder.setText(f"{d}  ({n} sweep refs)")
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
        self.lbl_fwhm_alpha.setText(f"{os.path.basename(f)}")
        self.lbl_fwhm_alpha.setStyleSheet("color: #2E7D32; font-weight: bold;")

    def _fwhm_pick_alpha_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, "Pick α folder (averages every *_alpha_trace.dat)",
            self._dlg_dir('fwhm_alpha_dir'))
        self._dlg_dir('fwhm_alpha_dir', d)
        if not d:
            return
        self._fwhm_alpha_folder = d
        self.rb_fwhm_alpha_folder.setChecked(True)
        self.lbl_fwhm_alpha_dir.setText(f"{d}")
        self.lbl_fwhm_alpha_dir.setStyleSheet("color: #2E7D32; font-weight: bold;")

    def _fwhm_mean_alpha_from_file(self, path):
        """alpha_trace.dat 한 파일의 모든 ambient 행 α를 평균 → (wave_nm, alpha_mean).
        단일 패스로 읽는다(행마다 파일 재읽기 회피)."""
        from core.data_io import DataIO
        first_px, t_idx, p_idx, px_start, wave_nm = DataIO._alpha_layout(path)
        rows = []
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith('#') or s.startswith('row_idx'):
                    continue
                parts = s.split('\t')
                try:
                    rows.append(np.array([float(v) for v in parts[first_px:]], dtype=float))
                except ValueError:
                    continue
        if not rows:
            raise ValueError(f"no α data rows in {os.path.basename(path)}")
        L = min(len(r) for r in rows)
        arr = np.array([r[:L] for r in rows], dtype=float)
        alpha_mean = np.nanmean(arr, axis=0)
        if wave_nm is not None and len(wave_nm) >= L:
            wl = np.asarray(wave_nm, dtype=float)[:L]
        elif hasattr(self, 'wavelengths') and self.wavelengths is not None \
                and len(np.asarray(self.wavelengths).flatten()) >= L:
            wl = np.asarray(self.wavelengths, dtype=float).flatten()[:L]
        else:
            wl = np.arange(L, dtype=float)
        return wl, alpha_mean

    def _fwhm_mean_alpha_from_folder(self, folder):
        """폴더(재귀) 내 모든 *_alpha_trace.dat의 평균 α를 다시 평균 → (wave_nm, alpha_mean, n_files).
        파일마다 파장축이 다르면 첫 파일 그리드로 보간해 합친다."""
        import glob
        files = sorted(glob.glob(os.path.join(folder, '**', '*_alpha_trace.dat'),
                                 recursive=True))
        if not files:
            raise ValueError("폴더에 *_alpha_trace.dat 가 없습니다(하위폴더 포함 검색).")
        ref_wl, means = None, []
        for fp in files:
            try:
                wl, a = self._fwhm_mean_alpha_from_file(fp)
            except Exception:
                continue
            if ref_wl is None:
                ref_wl, means = wl, [a]
            elif len(wl) == len(ref_wl) and np.allclose(wl, ref_wl, atol=1e-3):
                means.append(a)
            else:
                means.append(np.interp(ref_wl, wl, a, left=np.nan, right=np.nan))
        if not means:
            raise ValueError("읽을 수 있는 α 파일이 없습니다.")
        alpha_mean = np.nanmean(np.array(means), axis=0)
        return ref_wl, alpha_mean, len(means)

    # ── Pipeline Health / QC ─────────────────────────────────────────────────
    def _alpha_qc_pick_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, "Pick α folder to health-check", self._dlg_dir('aqc_dir'))
        self._dlg_dir('aqc_dir', d)
        if not d:
            return
        self._aqc_folder = d
        self.lbl_aqc_dir.setText(f"{d}")
        self.lbl_aqc_dir.setStyleSheet("color:#2E7D32; font-weight:bold;")

    def _pipeline_qc_pick_r_npz(self):
        """R(t) npz(R_<channel>.npz) 선택 — core.health_checks.check_r용. 선택 안 하면 SKIP."""
        fp, _ = QFileDialog.getOpenFileName(
            self, "Pick R(t) npz (optional, for R physics check)",
            self._dlg_dir('rt_path'), "R(t) npz (*.npz);;All Files (*)")
        if not fp:
            return
        self._dlg_dir('rt_path', fp)
        self._aqc_r_npz = fp
        self.lbl_aqc_rnpz.setText(f"{os.path.basename(fp)}")
        self.lbl_aqc_rnpz.setStyleSheet("color:#2E7D32; font-weight:bold;")

    def _pipeline_health_checks(self):
        """core/health_checks.py 배터리를 현재 로드된 엔진 상태로 실행.
        조립만 GUI 책임 — 판정 로직은 순수함수(health_checks.py)에 있어 CLI(tools/validate_pipeline.py)와 공유."""
        from core import health_checks as HC
        results = []
        wave = getattr(self.engine, '_wave_axis', None)
        wave = np.asarray(wave, dtype=float).flatten() if wave is not None else None
        if wave is not None and wave.size > 1:
            results.append(("wavecal", *HC.check_wavecal(wave)))
        else:
            results.append(("wavecal", HC.SKIP, "웨이브칼 미로드 (Setup에서 로드)", {}))
        gas_list = list(getattr(self.engine, 'gas_list', []) or [])
        if gas_list and wave is not None:
            refs = {}
            for name in gas_list:
                interp = self.engine.interpolators.get(name)
                if interp is not None:
                    try:
                        refs[name] = np.asarray(interp(wave), dtype=float)
                    except Exception:
                        pass
            results.append(("references", *HC.check_references(refs, wl=wave)))
        else:
            results.append(("references", HC.SKIP, "레퍼런스 미로드 (Setup에서 Lock)", {}))
        results.append(("rayleigh", *HC.check_rayleigh()))
        results.append(("R(t)", *HC.check_r(getattr(self, '_aqc_r_npz', None))))
        return results

    def _alpha_qc_scan_folder(self, folder, status_cb=None):
        """폴더(재귀) 내 모든 *_alpha_trace.dat를 단일패스로 스캔 → 건강성 통계.
        평균/엔벨로프(전역 픽셀별), 파일별 스캔수·NaN율·flatline, 날짜 커버리지,
        이상 파일 목록(스캔수 과소=6175형, flatline=퇴화, NaN과다)을 모은다."""
        import glob, re as _re
        from core.data_io import DataIO
        files = sorted(glob.glob(os.path.join(folder, '**', '*_alpha_trace.dat'),
                                 recursive=True))
        if not files:
            raise ValueError("폴더에 *_alpha_trace.dat 가 없습니다(하위폴더 포함).")
        g_sum = g_cnt = g_min = g_max = wl_ref = None
        n_scans_total = 0
        per_file = []            # (name, n_scans, nan_frac, flat, mag)
        dates = set()
        for k, fp in enumerate(files):
            if status_cb and (k % 25 == 0):
                status_cb(k + 1, len(files))
            try:
                fpx, t_idx, p_idx, ps, wl = DataIO._alpha_layout(fp)
            except Exception:
                per_file.append((os.path.basename(fp), 0, 1.0, True, np.nan)); continue
            rows = []
            try:
                with open(fp, encoding='utf-8', errors='replace') as fh:
                    for ln in fh:
                        s = ln.strip()
                        if not s or s.startswith('#') or s.startswith('row_idx'):
                            continue
                        try:
                            rows.append(np.array([float(v) for v in s.split('\t')[fpx:]],
                                                 dtype=float))
                        except ValueError:
                            continue
            except Exception:
                per_file.append((os.path.basename(fp), 0, 1.0, True, np.nan)); continue
            if not rows:
                per_file.append((os.path.basename(fp), 0, 1.0, True, np.nan)); continue
            L = min(len(r) for r in rows)
            arr = np.array([r[:L] for r in rows], dtype=float)
            n = len(rows); n_scans_total += n
            nanf = float(np.mean(~np.isfinite(arr)))
            with np.errstate(invalid='ignore', divide='ignore'):
                msp = np.nanmean(arr, axis=0)
                _std = np.nanstd(msp)
                mag = float(np.nanmedian(np.abs(msp)))
            flat = bool(not np.isfinite(_std) or _std < 1e-12) or (n == 1)
            per_file.append((os.path.basename(fp), n, nanf, flat, mag))
            m = _re.search(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})', os.path.basename(fp))
            if m:
                dates.add(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
            if g_sum is None:
                g_sum = np.zeros(L); g_cnt = np.zeros(L)
                g_min = np.full(L, np.inf); g_max = np.full(L, -np.inf)
                wl_ref = (np.asarray(wl, float)[:L]
                          if wl is not None and len(wl) >= L else np.arange(L, dtype=float))
            Lc = min(L, len(g_sum))
            sub = arr[:, :Lc]; fin = np.isfinite(sub)
            g_sum[:Lc] += np.where(fin, sub, 0.0).sum(axis=0)
            g_cnt[:Lc] += fin.sum(axis=0)
            with np.errstate(invalid='ignore'):
                g_min[:Lc] = np.minimum(g_min[:Lc], np.nanmin(np.where(fin, sub, np.nan), axis=0))
                g_max[:Lc] = np.maximum(g_max[:Lc], np.nanmax(np.where(fin, sub, np.nan), axis=0))
        mean = np.where(g_cnt > 0, g_sum / np.maximum(g_cnt, 1), np.nan)
        scans = np.array([p[1] for p in per_file if p[1] > 0], dtype=float)
        med_scans = float(np.median(scans)) if len(scans) else 0.0
        # 이상 판정: 스캔수<max(2, 0.3×median)=과소(6175형), flatline, NaN>5%
        low_thr = max(2.0, 0.3 * med_scans)
        anomalies = [p for p in per_file
                     if p[1] < low_thr or p[3] or p[2] > 0.05]
        return dict(wl=wl_ref, mean=mean, lo=g_min, hi=g_max,
                    n_files=len(files), n_scans=n_scans_total, med_scans=med_scans,
                    dates=sorted(dates), per_file=per_file, anomalies=anomalies)

    def _alpha_qc_after_export(self, out_dir):
        """Alpha Generator 완료 훅: 출력폴더를 Pipeline Health에 자동 연결하고 탭으로 포커스.
        'Auto-check' 체크 시 점검까지 자동 실행 — 생성→점검 흐름을 끊기지 않게."""
        if not out_dir or not hasattr(self, 'lbl_aqc_dir'):
            return
        self._aqc_folder = out_dir
        self.lbl_aqc_dir.setText(f"{out_dir}")
        self.lbl_aqc_dir.setStyleSheet("color:#2E7D32; font-weight:bold;")
        try:
            if hasattr(self, '_diag_tabs') and hasattr(self, '_tab_aqc'):
                self._diag_tabs.setCurrentWidget(self._tab_aqc)
        except Exception:
            pass
        if getattr(self, 'chk_aqc_auto', None) is not None and self.chk_aqc_auto.isChecked():
            self._alpha_qc_run()
        elif hasattr(self, 'lbl_aqc_readout'):
            self.lbl_aqc_readout.setText(
                "Pipeline health: folder set from last export — click  Run Pipeline Check.")

    def _alpha_qc_run(self):
        """전체 파이프라인 헬스체크: α 폴더 스캔(선택) + wavecal/references/Rayleigh/R(t)
        (core/health_checks.py, tools/validate_pipeline.py와 로직 공유). α 폴더는 선택사항 —
        없으면 그 항목만 SKIP하고 나머지 4개 물리 체크는 그대로 돈다."""
        from core import health_checks as HC
        self._btn_aqc_run.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        r = None
        try:
            if self._aqc_folder:
                def _st(k, n):
                    self.status.setText(f"Pipeline Health scanning α {k}/{n}…")
                    QApplication.processEvents()
                r = self._alpha_qc_scan_folder(self._aqc_folder, status_cb=_st)
            pipe_results = self._pipeline_health_checks()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self._btn_aqc_run.setEnabled(True)
            QMessageBox.critical(self, "Pipeline Health", f"check failed:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self._btn_aqc_run.setEnabled(True)

        # ── plot: mean α + min/max envelope (폴더 스캔했을 때만) ──
        self._aqc_pw.clear()
        if r is not None:
            wl, mean, lo, hi = r['wl'], r['mean'], r['lo'], r['hi']
            self._aqc_plot_data = (wl, mean, lo, hi)   # 🔍 Fit window 버튼용
            fin = np.isfinite(wl) & np.isfinite(mean)
            if fin.any():
                try:
                    c_lo = pg.PlotCurveItem(wl[fin], np.where(np.isfinite(lo[fin]), lo[fin], np.nan),
                                            pen=pg.mkPen((180, 180, 180, 120)))
                    c_hi = pg.PlotCurveItem(wl[fin], np.where(np.isfinite(hi[fin]), hi[fin], np.nan),
                                            pen=pg.mkPen((180, 180, 180, 120)))
                    self._aqc_pw.addItem(c_lo); self._aqc_pw.addItem(c_hi)
                    self._aqc_pw.addItem(pg.FillBetweenItem(c_lo, c_hi, brush=(120, 170, 255, 50)))
                except Exception:
                    pass
                self._aqc_pw.plot(wl[fin], mean[fin], pen=pg.mkPen('#1565C0', width=2),
                                  name="mean α")
            self._aqc_pw.setTitle(f"mean α + envelope — {r['n_files']} files, {r['n_scans']:,} scans")
        else:
            self._aqc_pw.setTitle("(α folder not set — file-level scan skipped)")

        # ── α 폴더 스캔 결과를 같은 4단계(PASS/WARN/FAIL/SKIP)로 편입 ──
        alpha_lines = []
        if r is not None:
            nan_files = sum(1 for p in r['per_file'] if p[2] > 0.05)
            flat_files = sum(1 for p in r['per_file'] if p[3])
            low_files = sum(1 for p in r['per_file']
                            if p[1] < max(2.0, 0.3 * r['med_scans']))
            mags = np.array([p[4] for p in r['per_file'] if np.isfinite(p[4])])
            mag_str = (f"{np.nanmin(mags):.1e}~{np.nanmax(mags):.1e}" if len(mags) else "n/a")
            dts = r['dates']
            date_str = (f"{dts[0]}~{dts[-1]} ({len(dts)}d)" if dts else "n/a")
            n_anom = len(r['anomalies']); n_files = max(r['n_files'], 1)
            frac = n_anom / n_files
            a_status = HC.PASS if n_anom == 0 else (HC.WARN if frac < 0.2 else HC.FAIL)
            a_msg = (f"{r['n_files']} files, {r['n_scans']:,} scans, {n_anom} anomalies "
                     f"(low-scan={low_files}, flatline={flat_files}, NaN>5%={nan_files})")
            alpha_lines.append(f"files={r['n_files']}  scans={r['n_scans']:,}  "
                                f"median scans/file={r['med_scans']:.0f}")
            alpha_lines.append(f"dates: {date_str}   |α| range: {mag_str}")
            for name, n, nf, flat, mag in r['anomalies'][:6]:
                tag = []
                if flat: tag.append("FLAT")
                if n < max(2.0, 0.3 * r['med_scans']): tag.append(f"scans={n}")
                if nf > 0.05: tag.append(f"NaN={nf*100:.0f}%")
                alpha_lines.append(f"   • {name}: {','.join(tag)}")
            if n_anom > 6:
                alpha_lines.append(f"   … +{n_anom - 6} more")
        else:
            a_status, a_msg = HC.SKIP, "α folder not set"
        pipe_results.insert(0, ("α files", a_status, a_msg, {}))

        overall_status, overall_msg = HC.overall(pipe_results)

        def _esc(s):   # HTML 이스케이프 + 공백/들여쓰기 보존
            return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                     .replace(' ', '&nbsp;'))
        _CLR = {HC.PASS: '#2E7D32', HC.WARN: '#E65100', HC.FAIL: '#C62828', HC.SKIP: '#78909C'}
        _ICON = {HC.PASS: '', HC.WARN: '', HC.FAIL: '', HC.SKIP: ''}
        html = [f'<span style="color:{_CLR[overall_status]}; font-weight:bold;">'
                f'{_ICON[overall_status]} {_esc(overall_msg)}</span>']
        for name, status, msg, _m in pipe_results:
            html.append(f'<span style="color:{_CLR[status]};">'
                        f'{_ICON[status]} {_esc(name)}: {_esc(msg)}</span>')
        for ln in alpha_lines:
            html.append(f'<span style="color:{_CLR[a_status]};">{_esc(ln)}</span>')
        self.lbl_aqc_readout.setText('<br>'.join(html))
        self.lbl_aqc_readout.setStyleSheet(
            "font-family:Consolas,monospace; font-size:11px; padding:2px 4px;")
        self.status.setText(f"Pipeline Health: {overall_status} — {overall_msg}")

    def _alpha_qc_zoom_fit(self):
        """🔍 Fit window: X를 Setup의 핏범위(start~end nm)로 줌 + 그 구간 mean α에 Y 오토핏.
        가장자리(저 R·저광량)의 거대한 노이즈 엔벨로프를 빼고 캠페인 평균 흡수 구조를 본다.
        Y는 엔벨로프가 아니라 mean에 맞춘다(엔벨로프 기준이면 mean이 또 0처럼 눌림)."""
        data = getattr(self, '_aqc_plot_data', None)
        if not data:
            QMessageBox.information(self, "Pipeline Health",
                "α 폴더를 지정하고 먼저  Run Pipeline Check를 실행하세요.")
            return
        wl, mean, _lo, _hi = data
        lo_nm = float(self.spin_fit_start_nm.value())
        hi_nm = float(self.spin_fit_end_nm.value())
        if hi_nm < lo_nm:
            lo_nm, hi_nm = hi_nm, lo_nm
        m = np.isfinite(wl) & np.isfinite(mean) & (wl >= lo_nm) & (wl <= hi_nm)
        if not m.any():
            QMessageBox.information(self, "Pipeline Health",
                f"핏범위 {lo_nm:.0f}~{hi_nm:.0f} nm 안에 데이터가 없습니다.\n"
                "Setup의 fit start/end nm를 확인하세요.")
            return
        ys = mean[m]
        ylo, yhi = float(np.nanmin(ys)), float(np.nanmax(ys))
        span = yhi - ylo
        pad = span * 0.15 if span > 0 else (abs(yhi) * 0.5 or 1e-9)
        self._aqc_pw.setXRange(lo_nm, hi_nm, padding=0.02)
        self._aqc_pw.setYRange(ylo - pad, yhi + pad, padding=0)
        self._aqc_pw.setTitle(
            f"mean α — fit window {lo_nm:.0f}~{hi_nm:.0f} nm  (edge noise excluded)")

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
        # wide alpha_trace(헤더 # wavelength_nm + 시간×픽셀 행, datetime에 공백 있음)는
        # 공백 split이 깨지므로 전용 리더로 모든 행을 평균한 대표 α를 쓴다.
        from core.data_io import DataIO
        if DataIO._is_alpha_trace_format(path):
            return self._fwhm_mean_alpha_from_file(path)
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
                             "If this is the per-bin single-column α format, load "
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

        # α source: folder(평균) / file / engine(최신). folder는 폴더 내 모든 알파를 평균.
        alpha_label = ""
        if self.rb_fwhm_alpha_folder.isChecked():
            if not self._fwhm_alpha_folder:
                QMessageBox.warning(self, "FWHM Best-Match",
                    "α source = folder, but no folder picked.")
                return
            try:
                wl_a, a, n_files = self._fwhm_mean_alpha_from_folder(self._fwhm_alpha_folder)
            except Exception as e:
                QMessageBox.critical(self, "FWHM Best-Match", f"α folder load failed:\n{e}")
                return
            alpha_label = f"{os.path.basename(self._fwhm_alpha_folder.rstrip('/\\'))} (mean of {n_files} files)"
        else:
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
                        "Run alpha export first, or pick a file/folder manually.")
                    return
            try:
                wl_a, a = self._fwhm_load_alpha(alpha_path)
            except Exception as e:
                QMessageBox.critical(self, "FWHM Best-Match", f"α load failed:\n{e}")
                return
            alpha_label = os.path.basename(alpha_path)

        # Each ref file is one column of cross-section values on the ref's
        # native wavelength grid. We need a wavelength axis for the ref. We
        # interpolate α onto ref pixel index here only as a fallback; the
        # preferred path is when ref length == len(wl_a) (target grid match).
        scores = {}
        self._fwhm_legacy_mismatch = False   # 레거시 단일컬럼 ref 길이 불일치 감지용
        for fpath in ref_files:
            fname = os.path.basename(fpath)
            fv = self._fwhm_parse_fwhm_from_name(fname)
            if fv is None:
                continue
            try:
                ref_raw = np.loadtxt(fpath, comments="#")
            except Exception:
                continue
            ref_raw = np.asarray(ref_raw)
            if ref_raw.ndim == 2 and ref_raw.shape[1] >= 2:
                # 2-column (wavelength_nm, cross_section) → α 파장축에 보간 정렬(정확).
                # 인덱스 정렬과 달리 α가 sub-window/다른 그리드여도 올바르게 겹친다.
                ref_wl, ref_y = ref_raw[:, 0], ref_raw[:, 1]
                ref_on_a = np.interp(wl_a, ref_wl, ref_y, left=np.nan, right=np.nan)
                m = np.isfinite(ref_on_a) & np.isfinite(a)
                r_fit, a_fit, wl_fit = ref_on_a[m], a[m], wl_a[m]
            else:
                # legacy 단일컬럼(파장축 없음) → 같은 그리드 가정(인덱스 정렬).
                # 길이가 다르면 정렬이 어긋나 RMS가 평평해지므로 경고 플래그를 세운다.
                ref_y = ref_raw.flatten()
                if len(ref_y) != len(a):
                    self._fwhm_legacy_mismatch = True
                n = min(len(ref_y), len(a))
                r_fit, a_fit, wl_fit = ref_y[:n], a[:n], wl_a[:n]
            if len(r_fit) < 50:
                continue
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
        self._fwhm_ax.set_title(f"FWHM Best-Match — α: {alpha_label}")
        self._fwhm_ax.legend()
        self._fwhm_canvas.draw()

        _warn = ("\n legacy single-column refs with length≠α detected — index-aligned "
                 "(may be unreliable). Re-run the FWHM Sweep to save wavelength-tagged refs."
                 if self._fwhm_legacy_mismatch else "")
        self.lbl_fwhm_best.setText(
            f"Best FWHM = {best_fv:.3f} nm  (RMS = {best_rms:.3e})\n"
            f"   → {os.path.basename(best_path)}{_warn}"
        )
        if self._fwhm_legacy_mismatch:
            self.lbl_fwhm_best.setStyleSheet("color: #E65100; font-weight: bold;")
        else:
            self.lbl_fwhm_best.setStyleSheet("color: #2E7D32; font-weight: bold;")
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

    # ══════════════════════════════════════════════════════════════════════
    # §4  입력: I0 / dark / offset / flags
    # ══════════════════════════════════════════════════════════════════════
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
                    raise ValueError("No data key in the mat file.")
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
        d = QFileDialog.getExistingDirectory(self, "Select Alpha spool folder", self._dlg_dir('alpha_save'))
        self._dlg_dir('alpha_save', d)
        if d:
            self.alpha_save_dir = d
            self.lbl_alpha_dir.setText(os.path.basename(d) or d)
            self.lbl_alpha_dir.setStyleSheet("color: #1565C0; font-weight: bold;")

    @staticmethod
    def _read_drnam_std_t(mat_path):
        """박사님 _avg_60s.mat 에서 std_t bin 경계(st,end)를 연초기준 초 (N,2)로.
        std_t_st/std_t_end(doy) → sec=(doy-1)*86400. 실패 시 None."""
        try:
            import scipy.io as sio
            m = sio.loadmat(mat_path)
            st = np.asarray(m['std_t_st'], dtype=float).flatten()
            en = np.asarray(m['std_t_end'], dtype=float).flatten()
            n = min(len(st), len(en))
            return np.column_stack([(st[:n] - 1.0) * 86400.0, (en[:n] - 1.0) * 86400.0])
        except Exception:
            return None

    # ══════════════════════════════════════════════════════════════════════
    # §5  알파 생성 (export + generator)
    # ══════════════════════════════════════════════════════════════════════
    def export_alpha_files(self, file_list=None, out_dir=None, avg_sec=None,
                           status_cb=None, done_cb=None, drnam_mat=None, ch_tab_map=None,
                           progress_cb=None, channels=None, gen_px_range=None, rt_map=None):
        """BBCEAS alpha만 계산해 저장(피팅 없음). Hot 2채널이면 채널별로 각각.

        Alpha Generator 팝업이 raw 파일목록/출력폴더/avgsec를 넘겨 호출할 수 있다.
        인자가 없으면(레거시) 메인 file_list/프롬프트/메인 avgsec를 사용.
        wavecal/핏레인지/cavity/flags 는 항상 메인 UI 설정을 재사용한다.
        drnam_mat: 박사님 _avg_60s.mat 경로를 주면 그 std_t 그리드에 binning + 전체 2048px
        + per-bin .dat(ch{N}_{YYYYMMDD}_NNNNNN.dat) 박사님 형식으로 출력.
        반환: True(시작됨) / False(검증 실패)."""
        flist = list(file_list) if file_list is not None else getattr(self, 'file_list', None)
        if not flist:
            QMessageBox.warning(self, "No Files", "Load measurement (raw) files first.")
            return False
        # raw 채널 → 핏세팅 탭 매핑(Alpha Generator). 비우면 raw 채널 N → 탭 N.
        self._alpha_ch_tab_map = {int(k): int(v) for k, v in (ch_tab_map or {}).items()}
        # 생성할 채널 선택(None=전체). 이미 만든 채널 재생성 방지용.
        self._alpha_sel_channels = set(int(c) for c in channels) if channels else None
        if getattr(self, 'wavelengths', None) is None and self.engine._wave_axis is None:
            QMessageBox.warning(self, "No Wavelength Cal",
                                "Load a wavelength calibration file first.")
            return False
        if out_dir is None:
            out_dir = QFileDialog.getExistingDirectory(self, "Select Alpha output folder", self._dlg_dir('alpha_out'))
            self._dlg_dir('alpha_out', out_dir)
        if not out_dir:
            return False

        # 채널 수: 넘겨받은 raw 첫 파일에서 감지(메인 _detected_channels도 갱신해 per-ch 설정 일치)
        try:
            from core.data_io import DataIO
            n_ch = int(DataIO.detect_channels(self._entry_filepath(flist[0])) or 1)
        except Exception:
            n_ch = int(getattr(self, '_detected_channels', 1) or 1)
        self._detected_channels = n_ch
        # 현재 채널 탭 설정을 스냅샷(알파 생성이 채널 탭의 wavecal/범위 사용)
        if self._active_channel in self._channel_configs:
            self._channel_configs[self._active_channel] = self._capture_config()

        # 박사님 형식이면 전체 2048px + std_t 그리드
        self._alpha_drnam_bins = None
        self._alpha_drnam_date = ""
        if drnam_mat:
            bins = self._read_drnam_std_t(drnam_mat)
            if bins is None or not len(bins):
                QMessageBox.warning(self, "std_t failed",
                                    "Could not read std_t_st/std_t_end from _avg_60s.mat.")
                return False
            self._alpha_drnam_bins = bins
            import re as _re
            m = _re.search(r'(\d{4})-(\d{2})-(\d{2})', os.path.basename(self._entry_filepath(flist[0])))
            self._alpha_drnam_date = (m.group(1) + m.group(2) + m.group(3)) if m else ""

        configs = self._build_alpha_channel_configs(n_ch, full_px=bool(drnam_mat),
                                                    gen_px_range=gen_px_range)
        if not configs:
            QMessageBox.warning(self, "Channel config failed",
                                "Could not build per-channel wavecal/pixel range.\n"
                                f"Hot (≥2ch) needs the {self._WV_CAL_BASE}\\roi1,roi2 Calib files.")
            return False
        _sel = getattr(self, '_alpha_sel_channels', None)
        _want = _sel if _sel is not None else set(range(1, n_ch + 1))
        got = set(c['channel'] for c in configs)
        _missing = sorted(_want - got)
        if _missing:
            QMessageBox.warning(self, "Some channels lack wavecal",
                                f"Only {sorted(got)} of the selected channels will be generated. Missing: {_missing}.\n"
                                f"Missing channels lack wavecal (channel tab or {self._WV_CAL_BASE}\\roiN)), skipped.\n"
                                "Continuing.")

        # 채널별 워커를 순차 실행(큐). Hot=2채널 → PNs, ANs 각각 생성.
        self._alpha_queue      = list(configs)
        self._alpha_file_list  = flist
        self._alpha_out_dir    = out_dir
        self._alpha_avgsec     = float(avg_sec) if avg_sec is not None else 60.0
        self._alpha_rt_map     = dict(rt_map or {})   # {raw채널 -> R(t) npz 경로} 채널별
        self._alpha_dark       = getattr(self, 'dark_data', None)
        self._alpha_done_msgs  = []
        self._alpha_status_cb  = status_cb   # 팝업 진행표시(옵션)
        self._alpha_user_done_cb = done_cb   # 팝업 완료콜백(옵션)
        self._alpha_progress_cb = progress_cb  # 팝업 진행바(done, total) 콜백(옵션)
        self._alpha_total       = 0
        self._alpha_ch_done     = 0          # 완료된 채널 수(멀티채널 진행 표시용)
        self._alpha_n_ch        = n_ch
        self.status.setText(f"Alpha export started ({n_ch} channels)...")
        self._start_next_alpha_export()
        return True

    # wv_cal 자동탐색 베이스 (채널별 파장보정 — 레포 번들 reference_data/wv_cal)
    _WV_CAL_BASE = WV_CAL_DIR

    def _channel_wl_path(self, ch):
        """채널 ch의 wavecal 파일 경로 — 채널 탭 config. 활성 채널은 현재 로드된 경로."""
        if ch == self._active_channel:
            return getattr(self, 'loaded_wl_path', '')
        cfg = self._channel_configs.get(ch) or {}
        return cfg.get('wl_path', '')

    def _channel_wave_cal(self, n_ch, ch):
        """채널(탭) → per-pixel 파장 배열. 우선순위: 채널 탭 wavecal(wl_path) →
        1ch=로드된 cal → ≥2ch=Output\\wv_cal\\{roi1,roi2,..} 최신 Calib."""
        wlp = self._channel_wl_path(ch)
        if wlp and os.path.exists(wlp):
            arr = self._load_wavecal_array(wlp)
            if arr is not None and len(arr):
                return np.asarray(arr, dtype=float).flatten()
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
        """채널별 Fit 범위(nm) — 채널 탭 config. 활성 채널은 현재 스핀값. (lo,hi) 정렬."""
        if ch == self._active_channel:
            lo, hi = self.spin_fit_start_nm.value(), self.spin_fit_end_nm.value()
        else:
            cfg = self._channel_configs.get(ch)
            if cfg:
                lo, hi = cfg.get('fit_start_nm', 435.0), cfg.get('fit_end_nm', 480.0)
            else:
                lo, hi = self.spin_fit_start_nm.value(), self.spin_fit_end_nm.value()
        return (lo, hi) if lo <= hi else (hi, lo)

    def _fit_unit_for_channel(self, ch):
        """채널의 핏 단위('nm'|'px'). 활성 채널은 콤보, 아니면 config."""
        if ch == self._active_channel and hasattr(self, 'cb_fit_unit'):
            return self.cb_fit_unit.currentText()
        cfg = self._channel_configs.get(ch)
        return cfg.get('fit_unit', 'nm') if cfg else 'nm'

    def _fit_px_for_channel(self, ch):
        """채널의 핏범위 픽셀(f_min, f_max). 활성=txt_min/max, 아니면 config."""
        if ch == self._active_channel:
            try:
                a, b = int(self.txt_min.text()), int(self.txt_max.text())
            except Exception:
                a, b = 0, 2047
        else:
            cfg = self._channel_configs.get(ch) or {}
            try:
                a, b = int(cfg.get('f_min', 0)), int(cfg.get('f_max', 2047))
            except Exception:
                a, b = 0, 2047
        return (a, b) if a <= b else (b, a)

    def _build_alpha_channel_configs(self, n_ch, full_px=False, gen_px_range=None):
        """채널마다 (채널idx, 라벨, 파장슬라이스, pixel_min/max).
        full_px=True(박사님 형식)면 핏윈도우 무시하고 전체 2048px 사용."""
        tab_map = getattr(self, '_alpha_ch_tab_map', {}) or {}
        sel = getattr(self, '_alpha_sel_channels', None)
        configs = []
        for ch in range(1, n_ch + 1):
            if sel is not None and ch not in sel:
                continue   # 사용자가 선택 안 한 채널은 생성 안 함(이미 만든 채널 재생성 방지)
            # raw 채널 ch가 어느 채널 탭 설정(wavecal/범위)을 쓸지(기본: 같은 번호 탭)
            tab = int(tab_map.get(ch, ch))
            wave_full = self._channel_wave_cal(n_ch, tab)
            if wave_full is None or len(wave_full) == 0:
                continue
            if full_px:
                pmin, pmax = 0, len(wave_full)
            elif gen_px_range is not None:
                # Alpha Generator의 '생성 px' 범위 — 핏레인지와 독립.
                # 알파엔 이 구간만 저장되므로 핏 윈도우보다 넉넉하게(기본 700~1700).
                pmin = max(0, min(int(gen_px_range[0]), len(wave_full) - 1))
                pmax = max(pmin + 1, min(int(gen_px_range[1]), len(wave_full)))
            elif self._fit_unit_for_channel(tab) == 'px':
                pmin, pmax = self._fit_px_for_channel(tab)
                pmin = max(0, min(pmin, len(wave_full) - 1))
                pmax = max(pmin + 1, min(pmax, len(wave_full)))
            else:
                start_nm, end_nm = self._fit_nm_for_channel(tab)
                pmin = int(np.abs(wave_full - start_nm).argmin())
                pmax = int(np.abs(wave_full - end_nm).argmin())
                if pmin > pmax:
                    pmin, pmax = pmax, pmin
                if pmax <= pmin:
                    pmax = pmin + 1
            # 라벨: 매핑된 탭의 data_label(사용자 지정) 있으면 그걸, 없으면 CH{ch}
            _tcfg = self._channel_configs.get(tab) or {}
            lbl = (_tcfg.get('data_label') or '').strip() or f'CH{ch}'
            configs.append(dict(channel=ch, label=lbl,
                                wave_nm=wave_full[pmin:pmax],
                                pixel_min=pmin, pixel_max=pmax))
        return configs

    def _start_next_alpha_export(self):
        if not getattr(self, '_alpha_queue', None):
            done = getattr(self, '_alpha_done_msgs', [])
            self.status.setText(f"Alpha export complete  {self._alpha_out_dir}")
            cb = getattr(self, '_alpha_user_done_cb', None)
            if cb:   # Alpha Generator 팝업이 띄운 경우 콜백으로 알림(자체 메시지)
                cb(self._alpha_out_dir, list(done))
            else:
                QMessageBox.information(
                    self, "Alpha Export complete",
                    "Per-channel α saved:\n" + "\n".join(done) +
                    f"\n\nLocation:\n{self._alpha_out_dir}\n"
                    "Filename: {source}_{channel}_alpha_trace.dat\n"
                    "Usable in Result Viewer / Analysis (RUN).")
            # close-the-loop: 생성한 폴더를 Pipeline Health에 자동 연결 → 점검 까먹지 않게.
            self._alpha_qc_after_export(self._alpha_out_dir)
            return
        cfg = self._alpha_queue.pop(0)
        self._alpha_status(f"Alpha [{cfg['label']}] computing (px {cfg['pixel_min']}~{cfg['pixel_max']})...")
        self._alpha_export_worker = AlphaExportWorker(
            file_list     = self._alpha_file_list,
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
            # dark scale·detector offset·stray light — RUN 경로와 물리 일치(기본값=무회귀).
            dark_scale_factor    = self.spin_dark_scale.value(),
            offset_spectrum      = getattr(self, 'offset_data', None),
            offset_scale_factor  = self.spin_offset_scale.value(),
            stray_light_fraction = self.spin_stray_light.value(),
            channel       = cfg['channel'],
            avg_sec       = self._alpha_avgsec,
            channel_label = cfg['label'],
            std_t_bins    = getattr(self, '_alpha_drnam_bins', None),
            drnam_date    = getattr(self, '_alpha_drnam_date', ''),
            drnam_chlabel = f"ch{cfg['channel']}",
            # wide 형식: 멀티채널이면 ch{N}/ 하위폴더로 분리(단일이면 평면)
            channel_subdir = (f"ch{cfg['channel']}" if int(getattr(self, '_detected_channels', 1) or 1) > 1 else ""),
            rt_path        = getattr(self, '_alpha_rt_map', {}).get(cfg['channel']),   # 채널별 R(t)
            campaign       = self._campaign(),   # A3: {out}/{campaign}/{날짜}/alpha/…
        )
        n_ch_tot = max(1, int(getattr(self, '_alpha_n_ch', 1) or 1))
        self._alpha_export_worker.total_ready.connect(
            lambda tot: setattr(self, '_alpha_total', max(1, int(tot))))
        self._alpha_export_worker.progress.connect(
            lambda n, lbl=cfg['label']: self._alpha_on_progress(n, lbl, n_ch_tot))
        # 로그(print) + GUI 상태줄/팝업 둘 다 — Indexing/cache/saved 진행이 사용자에게 보이게
        self._alpha_export_worker.status_msg.connect(
            lambda m, _lbl=cfg['label']: (print(f"[AlphaExport] {m}"),
                                          self._alpha_status(f"[{_lbl}] {m}")))
        self._alpha_export_worker.finished.connect(
            lambda res, lbl=cfg['label']: self._on_alpha_channel_done(res, lbl))
        self._alpha_export_worker.start()

    def _alpha_status(self, msg):
        """alpha export 진행 표시 — 메인 상태바 + (팝업 콜백 있으면) 팝업에도."""
        self.status.setText(msg)
        cb = getattr(self, '_alpha_status_cb', None)
        if cb:
            cb(msg)

    def open_alpha_generator(self):
        """Raw → Alpha 생성 팝업창. 메인 UI 설정(wavecal/핏레인지/cavity/flags) 재사용."""
        if getattr(self, 'wavelengths', None) is None and self.engine._wave_axis is None:
            QMessageBox.warning(self, "No Wavelength Cal",
                                "Load a wavelength calibration in the main window first\n"
                                "(Alpha generation uses that setting).")
            return
        from .ui_alpha_gen import AlphaGeneratorDialog
        dlg = AlphaGeneratorDialog(self)
        dlg.exec()

    def open_peak_trend(self):
        """flag별(ZA/He/Sampling) 피크 트렌드 뷰어 팝업."""
        from .ui_peak_trend import PeakTrendDialog
        dlg = PeakTrendDialog(self, default_dir=self._dlg_dir('data'))
        dlg.exec()

    def _alpha_on_progress(self, done, lbl, n_ch_tot):
        """알파 생성 진행을 %로 표시(채널 내 비율 + 채널 진척 합산) + 팝업 진행바 콜백."""
        tot = max(1, int(getattr(self, '_alpha_total', 1)))
        frac = min(1.0, done / tot)
        ch_done = int(getattr(self, '_alpha_ch_done', 0))
        pct = int(((ch_done + frac) / max(1, n_ch_tot)) * 100)
        self._alpha_status(f"[{lbl}] {pct}%  ({done:,}/{tot:,} scans)")
        cb = getattr(self, '_alpha_progress_cb', None)
        if cb:
            cb(pct, 100)

    def _on_alpha_channel_done(self, result, label):
        if str(result).startswith("ERROR"):
            self._alpha_done_msgs.append(f"  [{label}] failed: {result}")
            self.status.setText(f"Alpha [{label}] failed")
        else:
            self._alpha_done_msgs.append(f"[{label}] ")
        self._alpha_ch_done = int(getattr(self, '_alpha_ch_done', 0)) + 1
        self._alpha_total = 0   # 다음 채널 total 재설정 대기
        # 끝난 워커를 wait()로 완전 종료시키고 참조 보관 — 다음 채널 워커로 덮어쓸 때
        # 실행 중인 QThread가 GC돼 "Destroyed while thread is still running"으로
        # 다음 채널이 시작 못 하던 버그 수정.
        w = getattr(self, '_alpha_export_worker', None)
        if w is not None:
            try:
                w.wait(10000)
            except Exception:
                pass
            self._alpha_finished_workers = getattr(self, '_alpha_finished_workers', [])
            self._alpha_finished_workers.append(w)
            self._alpha_export_worker = None
        self._start_next_alpha_export()

    # ══════════════════════════════════════════════════════════════════════
    # §6  I0 / R 진단 (auto-extract, diagnostic plot)
    # ══════════════════════════════════════════════════════════════════════
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
        action_i0 = menu.addAction("Set as I0 (Zero-Air)")
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
            self.main_tabs.setCurrentWidget(self._tab_pages.get(self.setup_tab, self.setup_tab))   # switch to Setup tab
            
    def set_i0_path(self, filepath):
        """Updates the I0 state, loads data, and updates UI."""
        self.lbl_i0_path.setText(os.path.basename(filepath))
        self.lbl_i0_path.setStyleSheet("color: blue; font-weight: bold;")
        self.status.setText(f"I0 set to: {os.path.basename(filepath)}")
        
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

    # ══════════════════════════════════════════════════════════════════════
    # §7  다이얼로그 런처: ref / R / wavecal
    # ══════════════════════════════════════════════════════════════════════
    def open_ref_properties(self):
        """Opens the RefPropertiesDialog to configure Shift/Squeeze bounds."""
        if not hasattr(self, 'engine') or len(self.engine.gas_list) == 0:
            QMessageBox.warning(self, "Warning", "Please load and lock references first!")
            return
            
        dialog = RefPropertiesDialog(self, self.engine.gas_list, getattr(self, 'ref_props', {}))
        if dialog.exec():
            self.ref_props = dialog.get_properties()
            print("⚙️ Reference properties successfully saved:", self.ref_props)
            self._refresh_shsq_summary()   # L7: 그리드 요약 갱신

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

    # open_r_generator / R_GeneratorDialog 제거됨(2026-06): R Calibrator가 R(λ)·R(t)
    # 계산을 흡수했고 이 다이얼로그는 UI 버튼이 없는 죽은 경로였음.

    def open_r_trend_monitor(self):
        """R Calibrator: 채널별 반사율 교정 및 R(t) 계산."""
        from .ui_dialogs_r import RCalibratorDialog
        dialog = RCalibratorDialog(self)
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
            fwhm_text = "Wavelength Updated"
            if hasattr(dialog, 'fwhm_records') and dialog.fwhm_records:
                valid_fwhms = [v['fwhm_nm'] for v in dialog.fwhm_records.values()
                               if v.get('fwhm_nm') is not None]
                if valid_fwhms:
                    avg_fwhm  = float(np.mean(valid_fwhms))
                    avg_sigma = avg_fwhm / 2.3548
                    fwhm_text = (f"FWHM={avg_fwhm:.3f} nm  "
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
            
            msg = f"Wavelength Updated: {wl_array.min():.2f} ~ {wl_array.max():.2f} nm"
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
                # 파일명은 lbl_wavecal(생략표시)에만 — 여기(FWHM 라벨)는 짧게 상태만
                self.lbl_fwhm_display.setText("WL ")
                if hasattr(self, 'lbl_wavecal'):
                    from PyQt6.QtGui import QFontMetrics
                    from PyQt6.QtCore import Qt as _Qt
                    _fm = QFontMetrics(self.lbl_wavecal.font())
                    _el = _fm.elidedText(f"{os.path.basename(filepath)}",
                                         _Qt.TextElideMode.ElideMiddle, int(180 * self._s))
                    self.lbl_wavecal.setText(_el)
                    self.lbl_wavecal.setStyleSheet("color: #1565C0; font-weight: bold; padding: 2px;")
                    self.lbl_wavecal.setToolTip(f"Wavecal for this channel:\n{filepath}")
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

    # ══════════════════════════════════════════════════════════════════════
    # §8  Test Fit (탭1 자동 최적화+Apply / 탭2 1-scan 미리보기 — gui/test_fit_dialog.py)
    # ══════════════════════════════════════════════════════════════════════
    def _open_test_fit_dialog(self):
        """🧪 Test Fit 버튼 핸들러 — 탭1(자동 파라미터 최적화)+탭2(1스캔 미리보기) 다이얼로그.
        옛 _test_fit의 사전 가드만 여기 유지하고, 실제 계산은 각 탭이 필요할 때 수행한다."""
        from PyQt6.QtWidgets import QMessageBox
        if not self.engine.is_engine_ready():
            QMessageBox.warning(self, "Test Fit", "Lock references first.")
            return
        files = self._channel_files.get(self._active_channel) or self.file_list
        if not files:
            QMessageBox.warning(self, "Test Fit", "Load data first.")
            return
        TestFitDialog(self).show()

    def _current_fit_px_window(self):
        """현재 활성 채널의 핏 윈도우 설정을 단위 무관 원시값으로 반환.

        반환: (unit, lo, hi). unit='px'면 lo/hi=검출기 픽셀 번호(int, 정수 텍스트박스 값
        그대로), unit='nm'이면 lo/hi=파장(nm, float). 실제 배열 인덱스로의 변환은 호출부가
        각자의 wave 축(파일마다 px_start가 다를 수 있음) 기준으로 한다 — 여기서 미리
        인덱스화하면 그 축을 모르는 채로 계산하게 돼 틀릴 수 있다."""
        unit = self.cb_fit_unit.currentText() if hasattr(self, 'cb_fit_unit') else 'nm'
        if unit == 'px':
            return unit, int(self.txt_min.text()), int(self.txt_max.text())
        return unit, self.spin_fit_start_nm.value(), self.spin_fit_end_nm.value()

    def _compute_1scan_preview(self):
        """S-B/S-C: 첫 알파 스캔 1개만 핏 → (fp, wl, a, full_model, resid, gas_models, ppb,
        opt_shifts, opt_squeezes, rms, T_C, P_mbar, collin) 튜플 반환(TestFitDialog 탭2용).
        실제 핏 경로(DoasFitter + get_model_components)를 그대로 써서 RUN과 동일하게 검증.
        실패 시 None(호출부가 사유 표시)."""
        from PyQt6.QtWidgets import QMessageBox
        files = self._channel_files.get(self._active_channel) or self.file_list
        if not files:
            return None
        fp = self._entry_filepath(files[0])
        # ── 알파 첫 데이터행 + 파장헤더 읽기 ──
        wave_nm_file = None
        alpha_start = None
        px_start = 0
        T_C, P_mbar = 25.0, 1013.25
        row = None
        with open(fp, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if line.startswith('# wavelength_nm'):
                    wave_nm_file = np.array([float(x) for x in line.split(':')[1].split()])
                if line.startswith('#'):
                    continue
                cols = line.rstrip('\n').split('\t')
                if cols and cols[0] == 'row_idx':
                    idx = {c: i for i, c in enumerate(cols)}
                    alpha_start = next(i for i, c in enumerate(cols) if c.startswith('px'))
                    try:   # 알파의 첫 픽셀 번호(예: 'px700' → 700) — px 핏단위 슬라이스 보정용
                        px_start = int(cols[alpha_start][2:])
                    except ValueError:
                        px_start = 0
                    _iT, _iP = idx.get('T_C'), idx.get('P_mbar')
                    continue
                if alpha_start is not None:
                    row = cols
                    break
        if wave_nm_file is None or row is None:
            QMessageBox.warning(self, "Test Fit",
                                "Not an alpha file (no wavelength header).\n"
                                "Test Fit currently supports alpha (*_alpha_trace.dat) input.")
            return None
        if _iT is not None and _iT < len(row):
            T_C = float(row[_iT])
        if _iP is not None and _iP < len(row):
            P_mbar = float(row[_iP])
        n_pix = len(wave_nm_file)
        alpha = np.array([float(v) for v in row[alpha_start:alpha_start + n_pix]], dtype=float)

        # ── 핏 윈도우 슬라이스(px/nm — 활성 채널 설정) ──
        unit, lo, hi = self._current_fit_px_window()
        if unit == 'px':
            pmin, pmax = int(lo), int(hi)
            # px 값은 '검출기 픽셀 번호' — 알파가 px_start부터 저장돼 있으므로
            # 배열 인덱스로는 px_start를 빼서 슬라이스(워커 _alpha_fit_slice와 동일 의미).
            sl = slice(max(0, pmin - px_start), max(1, min(n_pix, pmax - px_start + 1)))
        else:
            i0 = int(np.abs(wave_nm_file - lo).argmin())
            i1 = int(np.abs(wave_nm_file - hi).argmin())
            sl = slice(min(i0, i1), max(i0, i1) + 1)
        wl = wave_nm_file[sl]
        a = alpha[sl]

        # ── DoasFitter (RUN과 동일) ──
        from core.doas_fit import DoasFitter
        from scipy.interpolate import interp1d as _i1d
        eng = self.engine
        fitter = DoasFitter(eng)
        wax = np.asarray(eng._wave_axis, dtype=float).flatten()
        vp_pixel = np.asarray(_i1d(wax, np.arange(len(wax)), bounds_error=False,
                                   fill_value='extrapolate')(wl), dtype=float)
        vp_center = vp_pixel[len(vp_pixel) // 2]
        rp = getattr(self, 'ref_props', {})
        active, fixed, linked, t0, lb, ub = fitter.setup_fit_parameters(
            rp, 0.0, [0.0, 1.0], self.spin_step_limit.value())
        # (구식 etalon 위상 append 제거 — doas_fit가 etalon을 sin·cos 선형열로
        #  처리한 뒤로는 위상이 비선형 파라미터가 아니다. 워커와 동일하게 theta는
        #  shift/squeeze만. 전부 Fix면 theta=[]여도 doas_fit가 선형해 1회로 처리.)
        out = fitter.execute_varpro_fit(
            vp_pixel, a, np.ones(len(a)), active, fixed, linked, t0, lb, ub,
            self.spin_poly_deg.value(), 0.0, vp_center, 1.0, rp, T_C,
            self.spin_lambda.value(), self.chk_robust.isChecked(),
            allow_negative_gas=self.chk_allow_neg.isChecked())
        opt_shifts, opt_squeezes, gas_coeffs, poly_c, etal_amp, best_ep, perr = out
        full_model, *_ = eng.get_model_components(
            vp_pixel, opt_shifts, opt_squeezes, gas_coeffs, poly_c,
            etalon_amp=etal_amp, etalon_freq=0.0, etalon_phase=best_ep)
        resid = a - full_model
        # 가스별 기여(진짜 레퍼런스 오버레이, S-C): 핏이 내부에서 쓰는 것과 동일식
        gas_models = []
        for gi, nm in enumerate(eng.gas_list):
            px_sh = (vp_pixel - vp_center) * opt_squeezes[gi] + vp_center + opt_shifts[gi]
            try:
                refv = eng.interpolators[nm](px_sh) / eng.scaling_factors.get(nm, 1.0)
                gas_models.append(gas_coeffs[gi] * refv)
            except Exception:
                gas_models.append(None)
        rms = float(np.sqrt(np.mean(resid ** 2)))
        from core.physics import air_number_density
        n_air = air_number_density(T_C, P_mbar)   # ppb 환산 단일 출처
        ppb = {}
        for gi, nm in enumerate(eng.gas_list):
            sc = eng.scaling_factors.get(nm, 1.0); mu = eng.multipliers.get(nm, 1.0)
            ppb[nm] = (gas_coeffs[gi] * mu / sc) / n_air * 1e9

        # etalon–기체 공선성 진단(보고 전용, 핏 불변) — RUN과 동일한 FFT 검출
        # 주파수(워커 기본 밴드 0.02~0.40 rad/px)에서 평가. 실패해도 팝업은 뜬다.
        try:
            e_f_diag = fitter.detect_etalon_frequency(
                vp_pixel, a, self.spin_poly_deg.value(), 0.02, 0.40)
            collin = fitter.etalon_collinearity(
                vp_pixel, e_f_diag, self.spin_poly_deg.value(), rp,
                temperature=T_C, fit_sign=1.0,
                opt_shifts=opt_shifts, opt_squeezes=opt_squeezes,
                absolute_center=vp_center)
        except Exception:
            collin = None

        return (fp, wl, a, full_model, resid, gas_models, ppb, opt_shifts, opt_squeezes,
                rms, T_C, P_mbar, collin)

    def _apply_test_fit_recommendations(self, result):
        """TestFitDialog 탭1의 [Apply] 콜백 — 추천된 ref_props/poly/step_limit을 라이브
        상태에 반영한다. worker가 이미 t_ref/t_coeff/active_bands_nm(사용자 몫)을 보존해
        조립했으므로 여기서는 그대로 덮어쓰기만 하면 된다. 사람이 버튼을 눌러야만 호출됨
        (자동 적용 금지, docs/fit_optimizer_handoff.md §15-E 불변식4)."""
        for gas, props in result["proposed_ref_props"].items():
            self.ref_props[gas] = dict(props)
        self.spin_poly_deg.setValue(result["proposed_poly_deg"])
        if result.get("proposed_step_limit") is not None:
            self.spin_step_limit.setValue(result["proposed_step_limit"])
        self._refresh_shsq_summary()

    # ══════════════════════════════════════════════════════════════════════
    # §9  핏 범위 + 레퍼런스 관리
    # ══════════════════════════════════════════════════════════════════════
    def _auto_apply_nm(self):
        """nm 스핀 수정 완료 시 px 자동 동기화(웨이브칼 없으면 조용히 패스 — 팝업 금지).
        init 중에는 monitor가 아직 없을 수 있음 — hasattr 가드 필수."""
        if not hasattr(self, 'monitor'):
            return
        if getattr(self.monitor, 'wavelengths', None) is None:
            return
        self.set_range_from_nm()

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
        self._mark_refs_dirty()
        print(f"✅ Slot Added: {name if name else 'Empty'}")

    def _mark_refs_dirty(self):
        """L5: 레퍼런스 변경 후 Lock 안 된 상태 표시 — Lock 버튼 빨강 + RUN 시 경고."""
        self._refs_dirty = True
        if hasattr(self, '_btn_lock_ref'):
            self._btn_lock_ref.setStyleSheet(
                "font-weight: bold; padding: 5px; background-color: #FFCDD2; color: #B71C1C;")

    def del_ref(self, widget):
        """Removes a reference row from the UI."""
        widget.deleteLater()
        self.ref_widgets = [x for x in self.ref_widgets if x['w'] != widget]
        self._mark_refs_dirty()

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

    def lock_ref(self, silent=False):
        """
        Commits all configured references from the UI into the UniversalEngine.

        silent=True: 채널 탭 전환 등 자동 재락 경로 — 모달 팝업 없이 상태라벨만.
        (사용자가 직접 Lock 버튼을 눌렀을 때만 팝업.)

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
            self._refs_dirty = False     # L5: 잠금 완료 → dirty 해제
            if hasattr(self, '_btn_lock_ref'):
                self._btn_lock_ref.setStyleSheet("font-weight: bold; padding: 5px;")
            if silent:
                self.status.setText(f"{success_count} references locked (auto, channel switch)")
            else:
                QMessageBox.information(self, "Locked", f"{success_count} references have been successfully locked into the Engine.")

            # Dynamically update the Result Table headers
            if hasattr(self, 'table'):
                cols = ["File", "Time", "RMS", "Chi2", "SNR", "Status"] + self.engine.gas_list + ["Shift", "Squeeze"]
                self.table.setColumnCount(len(cols))
                self.table.setHorizontalHeaderLabels(cols)
                self._compact_table_columns(cols)
                
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
            self._refresh_shsq_summary()
        else:
            if silent:
                self.status.setText("no references to lock (channel switch)")
            else:
                QMessageBox.warning(self, "Error", "No valid references found to lock, or an error occurred.")


    # ---------------------------------------------------------
    # Measurement Data Loading & UI State Logic
    # ---------------------------------------------------------
    # ══════════════════════════════════════════════════════════════════════
    # §10 데이터 로드 + 채널 분배
    # ══════════════════════════════════════════════════════════════════════
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
        btn_files = msg_box.addButton("Select Files", QMessageBox.ButtonRole.ActionRole)
        btn_folder = msg_box.addButton("Load Entire Folder", QMessageBox.ButtonRole.ActionRole)
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
        """Scans a selected folder (하위폴더 재귀) and loads all valid measurement files.
        날짜별 폴더(예: out/ch1/2026-05-18/...)에 흩어진 알파도 폴더 하나만 고르면 다 로드."""
        folder_path = QFileDialog.getExistingDirectory(self, "Select Measurement Folder (incl. subfolders)", self._dlg_dir('data'))
        if folder_path:
            self._dlg_dir('data', folder_path)
            valid_extensions = ('.dat', '.txt', '.csv')
            # os.walk + 가지치기: '_'로 시작하는 폴더(_archive/_derived/_autosave 등)와
            # legacy_unified(옛 알파 리네임 사본)는 스캔 제외 — 안 하면 같은 스캔이
            # 여러 벌(신규+사본+아카이브) 쓸려 들어와 중복 경고+수천 파일 렉.
            # 그 폴더를 보고 싶으면 '직접' 루트로 고르면 됨(루트 자체는 가지치기 안 함).
            _SKIP_DIRS = {'legacy_unified'}
            # 측정(raw) 또는 알파 파일만: 둘 다 'YYYY-MM-DD-NNN'으로 시작한다
            # (raw=2026-05-18-001.dat, 알파=2026-05-18-001_ANs_alpha_trace.dat).
            # FWHM_Analysis_·Calib_·Ref_ 같은 분석/레퍼런스 파일은 이 접두가 아니라
            # 제외 — 안 막으면 알파처럼 스캔으로 오인돼 핏이 오염된다(2026-07-09 FWHM 사고).
            import re as _re_meas
            _MEAS_RE = _re_meas.compile(r'^\d{4}-\d{2}-\d{2}-\d+')
            files, _n_skip = [], 0
            for _root, _dirs, _names in os.walk(folder_path):
                _dirs[:] = [d for d in _dirs
                            if not d.startswith('_') and d not in _SKIP_DIRS]
                for _fn in _names:
                    if _fn.lower().endswith(valid_extensions):
                        if _MEAS_RE.match(_fn):
                            files.append(os.path.join(_root, _fn))
                        else:
                            _n_skip += 1
            if _n_skip:
                self.status.setText(f"Skipped {_n_skip} non-measurement file(s) (FWHM/Calib/Ref 등)")
            # 파일명(날짜+스캔) 기준 정렬 — 하위폴더가 흩어져도 시간순 유지
            files = sorted(set(files), key=lambda f: (os.path.basename(f), f))
            if not files:
                QMessageBox.warning(self, "No Data",
                                    "No .dat/.txt/.csv files in the selected folder (incl. subfolders).")
                return
            # 날짜가 여러 개면 다중선택(특정 날짜만 피팅 가능)
            import re as _re
            def _date_of(f):
                m = _re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', os.path.basename(f))
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else "(no date)"
            dates = sorted(set(_date_of(f) for f in files))
            if len(dates) > 1:
                sel = self._pick_dates(dates)
                if sel is None:
                    return   # 취소
                files = [f for f in files if _date_of(f) in sel]
                if not files:
                    QMessageBox.warning(self, "No selection", "No dates selected.")
                    return
            # L10: 알파 헤더(label)로 채널 자동분배 — cold/ch1/ch2가 섞인 루트 폴더를
            # 한 번에 로드해 3채널 탭에 나눠 넣기. 분배 안 되면 기존(활성 채널) 동작.
            if self._distribute_channels(files):
                return
            self._update_file_table(files)

    @staticmethod
    def _alpha_head_label(fp):
        """알파 wide 헤더에서 label 추출 ('# channel=N  label=Cold'). 없으면 None."""
        import re as _re
        try:
            with open(fp, encoding='utf-8', errors='replace') as fh:
                for _ in range(4):
                    ln = fh.readline()
                    if not ln:
                        break
                    m = _re.search(r'#\s*channel=\d+\s+label=(\S+)', ln)
                    if m:
                        return m.group(1)
        except OSError:
            pass
        return None

    def _distribute_channels(self, files):
        """알파 라벨 그룹이 2개 이상이고 채널 탭 라벨과 매칭되면 자동분배.
        반환 True=분배 완료(테이블은 활성 채널 분량 표시), False=해당 없음."""
        # 라벨별 그룹화 (라벨 없는 파일이 섞이면 분배하지 않음 — raw 등)
        groups = {}
        for f in files:
            lab = self._alpha_head_label(f)
            if lab is None:
                return False
            groups.setdefault(lab.lower(), []).append(f)
        if len(groups) < 2:
            return False
        # 채널 탭 라벨 수집 (활성 채널은 현재 입력칸, 나머지는 config 스냅샷)
        tab_label = {}
        for ch in self._channel_configs:
            if ch == self._active_channel:
                lab = self._ed_ch_datalabel.text().strip() if hasattr(self, '_ed_ch_datalabel') else ''
            else:
                lab = ((self._channel_configs.get(ch) or {}).get('data_label') or '').strip()
            tab_label[ch] = lab.lower()
        # 매핑: 그룹라벨 == 탭라벨 (탭라벨 비어있으면 'ch{N}'으로 간주)
        mapping = {}
        for ch, lab in tab_label.items():
            key = lab or f'ch{ch}'
            if key in groups:
                mapping[ch] = key
        if len(mapping) < 2:
            return False
        # 확인 다이얼로그
        lines = [f"  CH{ch} ← {mapping[ch]} ({len(groups[mapping[ch]])} files)" for ch in sorted(mapping)]
        unmatched = [k for k in groups if k not in mapping.values()]
        if unmatched:
            lines.append(f"  (unmatched labels: {', '.join(unmatched)} — not distributed)")
        # 중복 스캔(같은 날짜-스캔이 다른 폴더에 중복 — 라벨 오염 의심) 경고
        import re as _re2
        def _scankey(f):
            m = _re2.search(r'(\d{4}-\d{2}-\d{2}-\d{3})', os.path.basename(f))
            return m.group(1) if m else os.path.basename(f)
        dupwarn = []
        for ch, key in mapping.items():
            keys = [_scankey(f) for f in groups[key]]
            ndup = len(keys) - len(set(keys))
            if ndup:
                dupwarn.append(f"  CH{ch}({key}): {ndup} duplicate scans")
        warn = ("\n\n DUPLICATE scans found (same date-scan in >1 folder —\n"
                "possible mislabeled alphas):\n" + "\n".join(dupwarn)) if dupwarn else ""
        ret = QMessageBox.question(self, "Auto-distribute channels",
                                   "Distribute alpha files to channel tabs by label:\n\n" + "\n".join(lines)
                                   + warn
                                   + "\n\nProceed? (No = all into current channel)",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return False
        self.results = []   # 새로 분배한 파일셋에 대한 결과가 아니므로 이전 Run 결과 무효화
        for ch, key in mapping.items():
            # 파일명(날짜+스캔) 기준 정렬 — 폴더가 흩어져도 시간순 보장(전체경로 정렬 X)
            self._channel_files[ch] = sorted(groups[key], key=lambda f: os.path.basename(f))
        # 활성 채널 분량만 테이블 표시(없으면 첫 매칭 채널)
        act = self._active_channel if self._active_channel in mapping else sorted(mapping)[0]
        self.file_list = list(self._channel_files.get(act, []))
        self.table.setRowCount(len(self.file_list))
        self.table.clearContents()
        for i, fp in enumerate(self.file_list):
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(fp)))
        total = sum(len(self._channel_files[c]) for c in mapping)
        self.status.setText("distributed: " + " · ".join(
            f"CH{c} {len(self._channel_files[c])}" for c in sorted(mapping)) + f" (total {total})")
        self._auto_detect_channels()
        return True

    def _pick_dates(self, dates):
        """날짜 다중선택 다이얼로그. 반환: 선택 날짜 set, None=취소. 기본 전체 선택."""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                                     QPushButton, QLabel, QAbstractItemView)
        dlg = QDialog(self)
        dlg.setWindowTitle("Select dates to fit")
        dlg.resize(int(280 * self._s), int(420 * self._s))
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"{len(dates)} dates found — select (multi):"))
        lw = QListWidget()
        lw.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for d in dates:
            lw.addItem(d)
        lw.selectAll()
        lay.addWidget(lw)
        bar = QHBoxLayout()
        b_all = QPushButton("All"); b_all.clicked.connect(lw.selectAll)
        b_none = QPushButton("None"); b_none.clicked.connect(lw.clearSelection)
        b_ok = QPushButton("OK"); b_ok.clicked.connect(dlg.accept)
        b_cancel = QPushButton("Cancel"); b_cancel.clicked.connect(dlg.reject)
        for b in (b_all, b_none, b_ok, b_cancel):
            bar.addWidget(b)
        lay.addLayout(bar)
        from PyQt6.QtWidgets import QDialog as _QD
        if dlg.exec() != _QD.DialogCode.Accepted:
            return None
        return set(i.text() for i in lw.selectedItems())

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

    @staticmethod
    def _row_index_from_display_name(display_name):
        """Table display names always end in ' [NNNN]' (worker.py appends the scan's
        real row index even for single-scan files — see _write_row_cells/'File').
        A plain (non-tuple) file_list entry has no row index of its own, so pull the
        actual scan row straight out of that suffix instead of assuming 0 — a multi-
        scan file (Mega-Matrix/alpha_trace) needs the real row to re-load the right
        scan, not just its first one."""
        m = re.search(r'\[(\d+)\]\s*$', display_name)
        return int(m.group(1)) if m else 0

    def _entry_from_display_name(self, display_name, file_list=None):
        """Finds the file_list entry for display_name's file, ignoring the trailing
        ' [NNNN]' scan-row suffix for plain entries (which don't carry a row index —
        use _row_index_from_display_name for that).

        file_list defaults to self.file_list (the currently active channel tab's
        files) but callers that already know which channel the display_name belongs
        to (e.g. a multi-channel results table row) should pass that channel's own
        list explicitly — self.file_list only ever holds one channel's files."""
        for e in (self.file_list if file_list is None else file_list):
            if isinstance(e, tuple):
                if self._entry_display_name(e) == display_name:
                    return e
            elif display_name.startswith(os.path.basename(e) + " ["):
                return e
        return None

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
        # 새 데이터를 로드하면 이전 Run의 결과는 이 파일셋에 대한 게 아니므로 무효 —
        # 지워야 _show_channel_files의 '결과 있으면 표 유지' 가드가 새로 로드한 파일목록을
        # 계속 가리지 않는다(안 지우면 채널탭 넘겨봐도 예전 결과화면이 계속 붙어있어 다른
        # 채널에 데이터가 제대로 들어갔는지 확인이 안 됨).
        self.results = []
        # 로드한 데이터를 '현재 활성 채널'이 소유(자동분배 X) — RUN이 채널마다 자기 리스트로 핏
        if getattr(self, '_active_channel', None) is not None:
            self._channel_files[self._active_channel] = list(self.file_list)
        self.table.setRowCount(len(self.file_list))
        self.table.clearContents()

        for i, fp in enumerate(self.file_list):
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(fp)))

        ch = getattr(self, '_active_channel', 1)
        # L6: 파일 수 + 날짜범위 요약
        import re as _re
        _ds = sorted({m.group(0) for fp in self.file_list
                      for m in [_re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(fp))] if m})
        _rng = f" · {_ds[0]}~{_ds[-1]}" if len(_ds) > 1 else (f" · {_ds[0]}" if _ds else "")
        self.status.setText(f"CH{ch} — {len(self.file_list)} file(s){_rng}")
        self._auto_detect_channels()
        self._refresh_setup_status()   # 입력 종류(알파/raw) 반영 → I0/R status 갱신

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
            label = ch_labels.get(n, f"{n}CH")
            self.lbl_channel_info.setText(label)
            # (채널별 설정은 좌측 채널 탭으로 — 여기선 감지 정보만 표시)
            colours = {1: "#1565C0", 2: "#6A1B9A", 3: "#2E7D32"}
            self.lbl_channel_info.setStyleSheet(
                f"color: {colours.get(n, '#333')}; font-weight: bold;")
            self.status.setText(
                f"{len(self.file_list)} file(s) loaded  —  {ch_names.get(n, str(n)+'CH')} detected")
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
        # 채널 탭 목록 → 다이얼로그 '적용 채널'로 범위를 채널별 설정
        tb = self._channel_tabbar
        channels = [(tb.tabData(i), tb.tabText(i)) for i in range(tb.count())]
        # 채널별 대표 스펙트럼 경로 — '적용 채널' 바꾸면 그 채널 데이터로 그래프 갱신
        # channel_files: 전체 리스트 → 다이얼로그의 File 콤보/★Score(추천)용
        channel_paths = {}
        channel_files = {}
        for ch, _lbl in channels:
            flist = self._channel_files.get(ch)
            if flist:
                channel_paths[int(ch)] = self._entry_filepath(flist[len(flist) // 2])
                channel_files[int(ch)] = [self._entry_filepath(e) for e in flist]
        # Vis.에서 ★Score/수동으로 고른 '채널별 대표 알파'를 세션 내내 기억 —
        # 다이얼로그는 매번 새로 만들어지므로 선택을 여기(app_window)에 보관해 넘긴다.
        if not hasattr(self, '_vis_chosen_alpha'):
            self._vis_chosen_alpha = {}
        # 채널별 핏레인지(nm) — 다이얼로그가 채널 전환 시 그 채널의 범위를 보여주게.
        # (활성 채널은 스핀박스, 나머지는 채널 config 스냅샷에서)
        channel_ranges = {}
        for ch, _lbl in channels:
            try:
                if ch == self._active_channel:
                    lo_nm = float(self.spin_fit_start_nm.value())
                    hi_nm = float(self.spin_fit_end_nm.value())
                else:
                    cfg = self._channel_configs.get(ch) or {}
                    lo_nm = float(cfg.get('fit_start_nm', 435.0))
                    hi_nm = float(cfg.get('fit_end_nm', 480.0))
                channel_ranges[int(ch)] = (lo_nm, hi_nm, True)
            except (TypeError, ValueError):
                pass
        self.sel_dlg = RangeSelectorDialog(mid_file, mn, mx, self.engine, channels=channels,
                                           channel_paths=channel_paths,
                                           active_channel=self._active_channel,
                                           channel_files=channel_files,
                                           chosen_files=self._vis_chosen_alpha,
                                           channel_ranges=channel_ranges)
        self.sel_dlg.apply_range.connect(self.update_range)
        self.sel_dlg.apply_channel.connect(self._set_channel_range_from_selector)
        self.sel_dlg.exec()

    def update_range(self, min_idx, max_idx):
        """Updates the text boxes with the visual selection."""
        if getattr(self, '_analysis_running', False):
            return
        self.txt_min.setText(str(min_idx))
        self.txt_max.setText(str(max_idx))

    def _set_channel_range_from_selector(self, ch, lo, hi, is_nm):
        """Vis.Select에서 고른 범위를 해당 채널의 nm 범위로 설정."""
        if getattr(self, '_analysis_running', False):
            return
        if lo > hi:
            lo, hi = hi, lo
        if not is_nm:
            # 픽셀 선택이면 마스터 wavecal로 nm 변환(가능할 때)
            wl = getattr(self, 'wavelengths', None)
            if wl is not None and len(wl) > int(hi):
                lo, hi = float(wl[int(lo)]), float(wl[int(hi)])
        if ch == self._active_channel:
            self.spin_fit_start_nm.setValue(lo)
            self.spin_fit_end_nm.setValue(hi)
            self.set_range_from_nm()   # 픽셀 범위(txt_min/max)도 갱신
        else:
            cfg = self._channel_configs.get(ch)
            if cfg is not None:
                cfg['fit_start_nm'] = lo
                cfg['fit_end_nm'] = hi
        self.status.setText(f"CH{ch} Fit range = {lo:.1f}~{hi:.1f} nm")

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
    @staticmethod
    def _alpha_file_meta(fp):
        """알파 파일 헤더에서 (channel_index, label) 추출. 우리 Alpha Export가
        '# channel=N  label=X' 를 항상 기록 → 캠페인 무관 generic 매핑용.
        반환: (int 또는 None, str 소문자 또는 '')."""
        ch, lbl = None, ''
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                for _ in range(15):
                    ln = f.readline()
                    if not ln or not ln.startswith('#'):
                        break
                    if 'channel=' in ln:
                        try:
                            ch = int(ln.split('channel=', 1)[1].strip().split()[0])
                        except (ValueError, IndexError):
                            pass
                    if 'label=' in ln:
                        lbl = ln.split('label=', 1)[1].strip().split()[0].lower()
        except Exception:
            pass
        return ch, lbl

    def _channel_data_groups(self):
        """채널별 데이터 파일 그룹. **알파 헤더의 채널 인덱스(# channel=N)가 최우선**
        → 캠페인 무관(라벨 타이핑 불필요). 헤더 인덱스가 없을 때만 data_label로 매칭
        (파일명/헤더 label/채널index 어느 거로든). 둘 다 없으면 기존 _alpha_groups."""
        if self._active_channel in self._channel_configs:
            self._channel_configs[self._active_channel] = self._capture_config()
        labels = {ch: ((cfg.get('data_label') or '').strip().lower())
                  for ch, cfg in self._channel_configs.items() if cfg}
        tab_chs = set(self._channel_configs.keys())
        groups = {}
        for entry in self.file_list:
            fp = self._entry_filepath(entry)
            name = os.path.basename(str(fp)).lower()
            hdr_ch, hdr_lbl = self._alpha_file_meta(fp)
            assigned = None
            # 1) 알파 헤더의 채널 인덱스(# channel=N)가 최우선 — 유일하게 권위 있는 값.
            #    라벨은 표시용 문자열이라 언제든 바뀔 수 있고, 라벨을 먼저 보면
            #    "파일명 _ANs_ ↔ 다른 탭의 data_label 'ANs'" 처럼 교차 매칭돼
            #    ROI1 알파가 ch2로 들어가는 사고가 난다(2026-07 실제 발생 위험).
            if hdr_ch in tab_chs:
                assigned = hdr_ch
            # 2) 헤더 인덱스가 없을 때(일반 raw 입력 등)만 data_label로 매칭
            if assigned is None:
                for ch, lbl in labels.items():
                    if lbl and (lbl in name or lbl == hdr_lbl or lbl == f"ch{ch}"):
                        assigned = ch
                        break
            if assigned is not None:
                groups.setdefault(assigned, []).append(entry)
        if groups:
            return groups
        return self._alpha_groups

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

    # ══════════════════════════════════════════════════════════════════════
    # §11 분석 실행 / 워커 / autosave / closeEvent
    # ══════════════════════════════════════════════════════════════════════
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
        # L5: Lock 안 된 레퍼런스 변경이 있으면 경고
        if getattr(self, '_refs_dirty', False):
            ret = QMessageBox.question(
                self, "References not locked",
                "References were changed but  Lock was not pressed.\n"
                "The engine will fit with the previously locked set. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return
            
        try:
            pixel_min, pixel_max = int(self.txt_min.text()), int(self.txt_max.text())
        except Exception:
            QMessageBox.warning(self, "Input Error", "Please enter valid integers for Pixel Min/Max.")
            return
        self._analysis_running = True
        
        self.results = []

        # ── 채널 = 좌측 채널 탭. 각 탭이 자기 데이터를 보유(자동분배 안 함) ──
        # 현재 활성 채널 데이터 동기화(로드 후 탭 전환 안 했을 수 있음)
        if self._active_channel in self._channel_configs:
            self._channel_files[self._active_channel] = list(self.file_list)
        active_chs = sorted(c for c, v in self._channel_configs.items() if v is not None) \
                     or [self._active_channel]
        chs_with_data = [c for c in active_chs if self._channel_files.get(c)]
        empty_chs = [c for c in active_chs if not self._channel_files.get(c)]
        if not chs_with_data:
            QMessageBox.warning(self, "No data",
                                "No data in any channel.\nSelect a channel tab and load data.")
            self._analysis_running = False
            return
        if empty_chs:
            self.status.setText(f"Skipped channels with no data: {', '.join('CH'+str(c) for c in empty_chs)}")

        # ── 핏은 알파 입력 전용 (2026-06 워크플로 변경) ──────────────────────
        # 워크플로가 'raw→알파 생성 후 알파 핏'으로 통일됨. raw(Araon mega-matrix/
        # plain) 직접 핏은 거부한다. raw→알파 변환은 Setup의 Alpha Generator 담당.
        # ※ AnalysisWorker.run 의 raw 핏 분기는 당분간 보존(되돌리기 쉽게) — 이 가드만
        #   제거하면 raw 핏이 복원된다. R Trend Monitor·Alpha Generator 등 raw를 쓰는
        #   다른 기능은 별도 경로라 영향 없음.
        _raw_chs = []
        for _c in chs_with_data:
            _f = self._entry_filepath(self._channel_files[_c][0])
            try:
                if not (_f and DataIO._is_alpha_trace_format(_f)):
                    _raw_chs.append(_c)
            except Exception:
                _raw_chs.append(_c)
        if _raw_chs:
            QMessageBox.warning(
                self, "Alpha input required",
                "Fitting now supports alpha (*_alpha_trace.dat) input only.\n"
                f"Channels that look like raw: {', '.join('CH'+str(c) for c in _raw_chs)}\n\n"
                "Generate raw → alpha first with the Alpha Generator in Setup,\n"
                "then load the generated alpha files to fit.")
            self._analysis_running = False
            return

        self._alpha_groups = {c: list(self._channel_files[c]) for c in chs_with_data}
        n_ch = len(chs_with_data)
        self._multi_channel_mode = (n_ch > 1)
        self._workers = []
        self._run_summary = []   # L2: 채널별 설정 요약(RUN 확인 다이얼로그)
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
        self._compact_table_columns(cols)

        # Progress bar: maximum is unknown until the worker expands Araon files.
        # Set to 0 (indeterminate / busy animation) until scan_count_ready fires.
        self.pbar.setMinimum(0)
        self.pbar.setMaximum(0)
        self.pbar.setValue(0)
        
        self.monitor.clear_trend()

        # 농도 시계열 탭: 레퍼런스 가스(채널 union)별 플롯 구성 + 히스토리 초기화
        conc_gases = list(getattr(self.engine, 'gas_list', []) or [])
        for _ch, _cfg in self._channel_configs.items():
            if _cfg:
                for _r in _cfg.get('refs', []):
                    _nm = _r.get('name')
                    if _nm and _nm not in conc_gases:
                        conc_gases.append(_nm)
        if hasattr(self.monitor, 'setup_conc_plots'):
            self.monitor.setup_conc_plots(conc_gases)

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
        
        # Fitting mode: Fast (parallel) vs Step (sequential, slow, inspect each fit).
        _disp = self.cb_display_mode.currentText() if hasattr(self, 'cb_display_mode') else "Fast (parallel)"
        _fast_mode = _disp.startswith("Fast")
        if _fast_mode:
            interval = -1     # no live per-scan spectrum overlay; results fill in as chunks arrive
            delay_ms = 0
        else:                 # Step
            delay_ms = 200     # 200ms/scan so each fit can be inspected live
            
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

        # 알파 입력이면 I0/R 경고 자체를 건너뜀 — 알파는 이미 BBCEAS(I0·R) 적용된
        # 산물이라 워커가 I0/R를 쓰지 않는다. (매 RUN마다 Yes 누르던 노이즈 제거)
        _first = self._entry_filepath(self.file_list[0]) if self.file_list else None
        _is_alpha_input = bool(_first) and DataIO._is_alpha_trace_format(_first)

        if (sliced_i0 is None or sliced_r is None) and not _is_alpha_input:
            # Check if the first file is an Araon Mega-Matrix — if so, the worker
            # will auto-derive I0 and R from the He/ZA rows embedded in each file.
            has_embedded_calib = bool(self.file_list) and DataIO.is_araon_mega_matrix(self.file_list[0])
            if has_embedded_calib:
                ans = QMessageBox.question(
                    self, "BBCEAS auto-calibration",
                    "R / I₀ files were not loaded separately.\n\n"
                    "He scans (flag 510~513) and ZA scans (flag 500~503) in the measurement file\n"
                    "are present, so R-curve (flag 510) and I₀ (flag 500) are computed automatically.\n\n"
                    "Start fitting?",
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

        # 채널 = 좌측 채널 탭. 각 탭이 자기 데이터로 병렬 피팅(현재 탭 설정 먼저 스냅샷).
        if self._active_channel in self._channel_configs:
            self._channel_configs[self._active_channel] = self._capture_config()
        # .meta.json 용 동결: 핏설정·캘리브는 **이 숫자를 만든 값**이어야 하므로 RUN 시점에
        # 얼려둔다(RUN 뒤 Save 전에 UI를 만져도 meta는 안 흔들린다). QC는 재핏 없는 후처리라
        # 저장 시점 값이 맞아서 여기서 얼리지 않는다 — save()가 그때 읽는다.
        self._run_frozen = {
            "configs": copy.deepcopy(self._channel_configs),
            "calibration": self._calibration_state(),
        }
        ch_list = sorted(self._alpha_groups)        # 데이터 있는 채널만(early 블록에서 구성)
        per_channel = len(ch_list) > 1
        self._workers_total = len(ch_list)
        self._scan_counts = {}

        for ch in ch_list:
            files_for_ch = self._alpha_groups.get(ch) or []
            if not files_for_ch:
                continue   # 데이터 없는 채널 스킵
            # 활성+단일이면 라이브 엔진/설정, 아니면(병렬 or 비활성 채널) 채널 config로 빌드
            use_cfg = per_channel or (ch != self._active_channel)

            # 채널별 설정 vs 공용(라이브)
            if use_cfg:
                cfg = self._channel_configs[ch]
                neg_ch = _channel_worker_gas_policy(True, cfg, self.chk_allow_neg.isChecked())
                eng_ch = self._build_engine_from_config(cfg)
                rp_ch = cfg.get('ref_props', {})
                ng = len(eng_ch.gas_list)
                npoly = int(cfg.get('poly_deg', 3)) + 1
                p0_ch = [0.0, self.calib_squeeze] + [0.1] * ng + [0] * npoly
                lo_ch = [-np.inf, 0.95] + [0.0] * ng + [-np.inf] * npoly
                hi_ch = [np.inf, 1.05] + [np.inf] * ng + [np.inf] * npoly
                funit_ch = cfg.get('fit_unit', 'nm')
                fnm_lo_ch = float(cfg.get('fit_start_nm', 435.0))
                fnm_hi_ch = float(cfg.get('fit_end_nm', 480.0))
                tz_val_ch = cfg.get('time_shift_h', cfg.get('input_tz', 0.0))
                gtemp_ch = float(cfg.get('gas_temp', 0.0) or 0.0)
                wl_ch = cfg.get('wl_path', '')
                lbl_ch = (cfg.get('data_label') or '').strip()
                if funit_ch == 'px':
                    # 박사님 시나리오: 픽셀 인덱스를 그대로 사용(예 Cold 775-1550)
                    try:
                        pmin, pmax = int(cfg.get('f_min', 0)), int(cfg.get('f_max', 2047))
                    except Exception:
                        pmin, pmax = pixel_min, pixel_max
                    if pmin > pmax:
                        pmin, pmax = pmax, pmin
                else:
                    wax = getattr(eng_ch, '_wave_axis', None)
                    if wax is not None:
                        wa = np.asarray(wax, dtype=float).flatten()
                        pmin = int(np.abs(wa - fnm_lo_ch).argmin())
                        pmax = int(np.abs(wa - fnm_hi_ch).argmin())
                        if pmin > pmax:
                            pmin, pmax = pmax, pmin
                    else:
                        pmin, pmax = pixel_min, pixel_max
                cav_ch = cfg.get('cavity_d', cavity_d); rl_ch = cfg.get('rl_factor', 1.0)
                lam_ch = cfg.get('tikhonov_lambda', 0.0); rob_ch = cfg.get('use_robust', False)
                step_ch = cfg.get('step_limit', 0.5)
                kq_ch = cfg.get('kalman_q', self.spin_kalman_q.value())
                kr_ch = cfg.get('kalman_r', self.spin_kalman_r.value())
            else:
                neg_ch = _channel_worker_gas_policy(False, {}, self.chk_allow_neg.isChecked())
                eng_ch = self.engine; rp_ch = getattr(self, 'ref_props', {})
                p0_ch, lo_ch, hi_ch = p0, bounds_low, bounds_high
                funit_ch = self.cb_fit_unit.currentText() if hasattr(self, 'cb_fit_unit') else 'nm'
                fnm_lo_ch = self.spin_fit_start_nm.value(); fnm_hi_ch = self.spin_fit_end_nm.value()
                tz_val_ch = self.spin_time_shift.value() if hasattr(self, 'spin_time_shift') else 0.0
                gtemp_ch = float(self.spin_gas_temp.value()) if hasattr(self, 'spin_gas_temp') else 0.0
                wl_ch = getattr(self, 'loaded_wl_path', '')
                lbl_ch = self._ed_ch_datalabel.text().strip() if hasattr(self, '_ed_ch_datalabel') else ''
                pmin, pmax = pixel_min, pixel_max
                cav_ch = cavity_d; rl_ch = self.spin_rl_factor.value()
                lam_ch = self.spin_lambda.value(); rob_ch = self.chk_robust.isChecked()
                step_ch = step_limit_val
                kq_ch = self.spin_kalman_q.value(); kr_ch = self.spin_kalman_r.value()

            w = AnalysisWorker(
                eng_ch, files_for_ch, pmin, pmax,
                p0_ch, (lo_ch, hi_ch), interval, delay_ms,
                ref_properties=rp_ch,
                i0_array=sliced_i0, r_array=sliced_r, cavity_len=cav_ch,
                dark_array=sliced_dark,
                dark_scale_factor=self.spin_dark_scale.value(),
                offset_array=sliced_offset,
                offset_scale_factor=self.spin_offset_scale.value(),
                stray_light_fraction=self.spin_stray_light.value(),
                use_temporal_i0=use_temporal,
                flag_za=flag_za,
                flag_he=flag_he,
                flag_amb=flag_amb,
                save_alpha=False,   # α 저장은 Alpha Generator 전담
                alpha_save_dir=getattr(self, 'alpha_save_dir', ''),
                rl_factor=rl_ch,
                channel=ch
            )

            w.step_limit = step_ch
            w.tikhonov_lambda = lam_ch
            w.use_robust_fitting = rob_ch
            w.allow_negative_gas = neg_ch
            w.qc_enabled = self.chk_qc.isChecked() if hasattr(self, 'chk_qc') else True
            w.qc_rms_abs = self.spin_qc_rms.value() if hasattr(self, 'spin_qc_rms') else 0.0
            w.qc_snr_min = self.spin_qc_snr.value() if hasattr(self, 'spin_qc_snr') else 0.0
            w.kalman_q = kq_ch
            w.kalman_r = kr_ch
            # 알파 피팅 핏범위(px면 알파를 픽셀구간으로 슬라이스)
            w.fit_unit = funit_ch
            w.fit_lo_nm = fnm_lo_ch
            w.fit_hi_nm = fnm_hi_ch
            # 채널 시각에 그대로 더할 시프트(시간→초). 순수 시간이동, TZ 라벨 없음.
            w.tz_offset_sec = int(round(self._time_shift_hours(tz_val_ch) * 3600))
            # 가스온도 오버라이드(>0이면 ppb 밀도보정에 그 온도 사용; 0=자동 HK)
            w.gas_temp_override = gtemp_ch if gtemp_ch > 0 else None
            w.temperature = self.spin_temp.value()
            w.pressure = self.spin_pres.value()
            w.ok_rms_threshold = self.spin_rms_thresh.value() / 100.0
            # Fast mode → parallel chunked fitting (AnalysisWorker._run_parallel).
            # Step mode → existing sequential loop (with delay for live inspection).
            w.parallel = _fast_mode
            # Channels run as concurrent workers, each with its OWN process pool.
            # Total process budget = ~half the machine's logical cores (adapts per PC,
            # leaving the other half for the GUI/OS). That budget is split across the
            # active channels so adding channels never multiplies the load
            # (e.g. without this, 3ch × 6 = 18 procs on 12 cores → ~100% + lag).
            import os as _os
            _budget = max(2, (_os.cpu_count() or 4) // 2)
            w.fit_nproc = max(1, _budget // max(1, len(self._alpha_groups)))

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

            # L2: RUN 확인 다이얼로그용 채널별 설정 요약
            _wlname = os.path.basename(wl_ch) if wl_ch else 'none'
            _gt = f"{gtemp_ch:.0f}°C" if gtemp_ch > 0 else "auto"
            _gases = list(eng_ch.gas_list)
            self._run_summary.append(
                f"CH{ch} {lbl_ch or ''}\n"
                f"{_wlname}\n"
                f"   range px {pmin}-{pmax} ({funit_ch}) · Poly{cfg.get('poly_deg', self.spin_poly_deg.value()) if ch != self._active_channel and self._channel_configs.get(ch) else self.spin_poly_deg.value()}\n"
                f"   refs {len(_gases)}: {', '.join(_gases)}\n"
                f"   {self._shsq_text(_gases, rp_ch)}\n"
                f"   Shift {self._time_shift_hours(tz_val_ch):+g}h · GasT {_gt}")
            self._workers.append(w)

        if not self._workers:
            QMessageBox.warning(self, "Channel/data mismatch",
                                "No data matches the channel tabs.\n"
                                "(check the _PNs_/_ANs_ channel in the alpha filename and the number of tabs)")
            self.b_run.setEnabled(True)
            return

        # Keep self.worker pointing to CH1 worker for legacy stop/wait references
        self.worker = self._workers[0]

        # ── L2: RUN 직전 설정 확인 — TZ 혼합·구버전 wavecal·온도 실수 등 예방 ──
        if not getattr(self, '_skip_run_confirm', False) and self._run_summary:
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit, \
                QDialogButtonBox, QCheckBox as _QCB
            _qcK = self.spin_qc_k.value() if hasattr(self, 'spin_qc_k') else 0
            _qc = (f"K={_qcK:g}" if (hasattr(self, 'chk_qc') and self.chk_qc.isChecked()
                                     and _qcK > 0) else "off")
            _asave = "on" if (hasattr(self, 'chk_auto_save')
                              and self.chk_auto_save.isChecked()) else "off"
            txt = ("\n\n".join(self._run_summary)
                   + f"\n\nCommon: AutoQC {_qc} · auto-save {_asave}"
                   + f" · files {sum(len(v) for v in self._alpha_groups.values())}")
            dlg = QDialog(self)
            dlg.setWindowTitle("Start with these settings?")
            dlg.resize(int(560 * self._s), int(380 * self._s))
            lay = QVBoxLayout(dlg)
            ed = QPlainTextEdit(txt)
            ed.setReadOnly(True)
            ed.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
            lay.addWidget(ed)
            _cb = _QCB("Don't ask again this session")
            lay.addWidget(_cb)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                  | QDialogButtonBox.StandardButton.Cancel)
            bb.button(QDialogButtonBox.StandardButton.Ok).setText("▶ Start")
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            lay.addWidget(bb)
            ok = dlg.exec()
            if _cb.isChecked():
                self._skip_run_confirm = True
            if not ok:
                self._analysis_running = False
                self.status.setText("RUN cancelled (settings review)")
                return

        # Lock UI controls to prevent interference
        self.b_run.setEnabled(False)
        self.b_stop.setEnabled(True)
        self.status.setText("Analysis in progress...")

        # Switch to the Analysis Monitor automatically
        self.main_tabs.setCurrentWidget(self._tab_pages.get(self.monitor, self.monitor))

        # 크래시 대비 실시간 자동저장 시작 (결과 도착마다 TSV append)
        self._autosave_start()

        # Fast mode: buffer incoming results and flush the table in batches on a timer
        # (see update_table / _flush_fast) so large parallel runs don't freeze the GUI.
        self._fast_mode_active = bool(_fast_mode)
        if self._fast_mode_active:
            self._fast_pending = []
            self._fast_rows_shown = 0
            self._fast_cap_noted = False
            self._fast_table_cap = 5000   # live-table preview cap (full data in plots+autosave)
            if not hasattr(self, '_fast_timer'):
                from PyQt6.QtCore import QTimer
                self._fast_timer = QTimer(self)
                self._fast_timer.setInterval(250)
                self._fast_timer.timeout.connect(self._flush_fast)
            self._fast_timer.start()

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
                f"{total_all:,} scans ({n_ch} CH) / {len(self.file_list)} file(s) — processing..."
            )
        elif getattr(self, '_fast_mode_active', False):
            # Fast mode renders the table once at the end (capped) — don't pre-allocate
            # tens of thousands of empty rows here (memory + slow).
            self.status.setText(f"Fast: {total_scans:,} scans / {len(self.file_list)} file(s) — fitting...")
        else:
            # Single-channel Step: pre-allocate rows for O(1) update_table writes
            self.table.setRowCount(total_scans)
            self.status.setText(f"{total_scans:,} scans / {len(self.file_list)} file(s) — processing...")

    def stop_analysis(self):
        """Safely stops all worker threads and re-enables UI controls."""
        workers = getattr(self, '_workers', [])
        if not workers and hasattr(self, 'worker'):
            workers = [self.worker]   # legacy fallback

        running = [w for w in workers if w.isRunning()]
        if running:
            # 논블로킹 정지: w.wait()로 UI 스레드를 막으면 '응답없음'이 뜬다.
            # stop()이 is_running=False로 만들면 워커는 현재 스캔만 끝내고 루프를
            # 빠져나와 finished를 emit → analysis_finished()가 정상 흐름으로 호출되어
            # UI 복구 + 자동 QC(부분 결과 대상)를 수행한다.
            self._stop_requested = True
            for w in running:
                w.stop()
            self.status.setText("Stopping… (finishing current scan)")
            self.status.setStyleSheet("color: red; font-weight: bold;")
            self.b_stop.setEnabled(False)

    def _active_workers(self):
        """모든 백그라운드 워커(분석 핏 + 알파 생성)를 한 곳에서 모은다.
        Fast 핏·알파 생성은 ProcessPoolExecutor 자식을 띄우므로, 창을 그냥 닫으면
        QThread가 중간에 죽으며 자식 프로세스가 고아(orphan)로 남아 CPU를 계속 먹는다."""
        ws = list(getattr(self, '_workers', []) or [])
        w0 = getattr(self, 'worker', None)
        if w0 is not None and w0 not in ws:
            ws.append(w0)
        ax = getattr(self, '_alpha_export_worker', None)
        if ax is not None:
            ws.append(ax)
        return [w for w in ws if w is not None and w.isRunning()]

    def closeEvent(self, event):
        """창을 닫을 때 실행 중인 워커를 깨끗이 정지시켜 고아 프로세스를 막는다.
        stop()이 is_running=False로 만들면 워커는 현재 청크를 마치고 루프를 빠져나오며
        ProcessPoolExecutor의 with 블록이 풀을 정리한다. wait()로 정리를 기다리되,
        제한시간을 넘기면 terminate()로 강제 종료한다(좀비 방지)."""
        running = self._active_workers()
        if running:
            reply = QMessageBox.question(
                self, "Confirm exit",
                f"{len(running)} background task(s) are running.\n"
                "Stop and exit? (running fits/alpha generation will be aborted)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for w in running:
                try:
                    w.stop()
                except Exception:
                    pass
            for w in running:
                try:
                    if not w.wait(8000):       # 정상 정리 대기(최대 8초)
                        w.terminate()          # 안 멈추면 강제 종료 → 자식 정리
                        w.wait(2000)
                except Exception:
                    pass
        event.accept()

    def _campaign(self):
        """산출물 최상위 스코프. 비면 'default' — save()·autosave가 같은 값을 써야 한다."""
        w = getattr(self, '_ed_campaign', None)
        return (w.text().strip() if w is not None else "") or DEFAULT_CAMPAIGN

    def _input_layout(self, ch):
        """이 채널의 **첫 입력 파일**이 어떤 raw 구성에서 나왔는지. 모르면 None.

        알파 입력이면 그 헤더의 `# raw_layout:` 줄(알파 생성 때 기록됨)을 읽고, raw 입력이면
        열 수로 레지스트리를 본다 — 판단은 `core.run_meta.layout_from_input`이 한다.
        """
        try:
            files = (self._channel_files.get(int(ch)) or self.file_list or [])
            if not files:
                return None
            return run_meta.layout_from_input(self._entry_filepath(files[0]))
        except Exception:                       # noqa: BLE001 — provenance가 저장을 막지 않는다
            return None

    def _build_run_meta(self, ch, *, campaign=None, data_days=(), rows=None):
        """채널 하나의 `.meta.json`. 실패하면 None(저장 자체는 살린다).

        save()와 autosave가 **같은 runid**를 쓰도록 한 곳에 둔다 — autosave 파일명이
        `{runid}.tsv`인데 나중에 저장되는 결과의 runid와 다르면 그 이름이 거짓말이 된다.
        `data_days`·`rows`는 runid 해시에 안 들어가므로 autosave가 비워 불러도
        같은 값이 나온다.
        """
        try:
            ch = int(ch) if ch is not None else int(self._active_channel)
            frozen = getattr(self, '_run_frozen', None) or {}
            cfg = ((frozen.get('configs') or self._channel_configs).get(ch)
                   or self._channel_configs.get(ch) or {})
            from core.provenance import code_version as _cv
            meta = run_meta.build_meta(
                cfg, channel=ch,
                qc=self._qc_state(),
                calibration=frozen.get('calibration') or self._calibration_state(),
                data_days=data_days, rows=rows,
                campaign=campaign if campaign is not None else self._campaign(),
                scenario=getattr(self, '_scenario_name', None),
                code_version=_cv(), app_version=__version__,
                # 이 결과가 어떤 raw 구성에서 나왔나(B안). 선택은 데이터(열 수)가 하고
                # 여기선 기록만 한다 — 사람이 친 campaign 라벨과 달라도 그건 정보다.
                layout=self._input_layout(ch),
            )
            # 측정일 감사(D1) 결과를 결과 파일에 붙인다 — "이 농도가 R(t) 외삽 구간
            # 위에서 나왔나"를 나중에 물을 수 있어야 한다. runid 해시엔 안 들어간다
            # (설정이 아니라 그날 데이터의 성질).
            audit = getattr(self, '_day_audit', None) or {}
            hit = {d: audit[d].to_meta() for d in data_days if d in audit}
            if hit:
                meta['day_audit'] = hit
            return meta
        except Exception as e:                  # noqa: BLE001 — meta가 저장을 막지 않는다
            print(f"[run_meta] no sidecar: {e}")
            return None

    def _run_runids(self):
        """이번 런에 걸린 채널들의 runid(정렬·중복제거). autosave 파일명용."""
        chans = sorted((getattr(self, '_run_frozen', None) or {}).get('configs')
                       or self._channel_configs or {self._active_channel: None})
        out = []
        for ch in chans:
            m = self._build_run_meta(ch)
            if m and m.get('runid') not in out:
                out.append(m['runid'])
        return out

    def _autosave_retire(self):
        """정식 저장이 성공했으면 그 런의 autosave를 치운다 (E3).

        autosave의 존재 이유는 "이 런은 아직 정식 저장이 없다"이므로, 저장이 끝나면
        남아 있을 이유가 없다 — 남겨두면 `_autosave/`가 어느 게 미완인지 알 수 없는
        더미가 된다. **지우지 않고** `_archive/`로 옮긴다(헌장 ①).
        """
        p = getattr(self, '_autosave_path', None)
        if not p or not os.path.exists(p):
            return
        try:
            self._autosave_close()
            from core.result_io import archive_existing
            from gui.dlg_dir import dlg_dir
            base = dlg_dir('save_results') or os.path.join(DEFAULT_OUTPUT_DIR, 'fitting')
            archive_existing(p, _campaign_dir(base, self._campaign()))
            self._autosave_path = None
        except Exception as e:                  # noqa: BLE001 — 정리 실패가 저장을 무르지 않는다
            print(f"[autosave] retire skipped: {e}")

    # ── 실시간 자동저장(autosave) ─────────────────────────────────────────
    # 밤샘 런이 크래시로 죽어도 그 시점까지의 결과가 디스크에 남도록, 결과가
    # 도착할 때마다 TSV에 append한다(50행마다 flush). 완료 시 정식 Save와 별개로
    # _autosave/ 폴더에 전체 기록이 남는다(QC 적용 전 원본값 기준).
    def _autosave_start(self):
        try:
            import time as _t
            try:
                from gui.dlg_dir import dlg_dir
                base = dlg_dir('save_results') or os.path.join(DEFAULT_OUTPUT_DIR, 'fitting')
            except Exception:
                base = os.getcwd()
            # E3: 캠페인 안으로 + 이름을 runid로. 예전 `autosave_20260908_143207.tsv`는
            # 실행 시각뿐이라 여러 런 뒤 _autosave/를 열면 어느 설정이었는지 열어봐야 알았다.
            folder = _special_dir(base, self._campaign(), '_autosave')
            os.makedirs(folder, exist_ok=True)
            rids = self._run_runids()
            stem = "_".join(rids) if rids else f'autosave_{_t.strftime("%Y%m%d_%H%M%S")}'
            self._autosave_path = os.path.join(folder, f'{stem}.tsv')
            # 같은 설정으로 다시 돌리면 이름이 겹친다 — 남아 있는 건 **정식 저장이 안 된
            # 런**(크래시 등)이므로 덮지 않고 _archive로 밀어둔다(헌장 ①: 지우지 말 것).
            if os.path.exists(self._autosave_path):
                from core.result_io import archive_existing
                archive_existing(self._autosave_path, _campaign_dir(base, self._campaign()))
            cols = ['File', 'Channel', 'Time', 'RMS', 'Chi2', 'SNR', 'Status',
                    'Shift', 'Squeeze', 'T_used_C', 'P_used_mbar']
            for g in self.engine.gas_list:
                cols += [g, f'{g}_RealConc', f'{g}_Error', f'{g}_Smooth']
            self._autosave_cols = cols
            self._autosave_fh = open(self._autosave_path, 'w', encoding='utf-8')
            self._autosave_fh.write('\t'.join(cols) + '\n')
            self._autosave_fh.flush()
            self._autosave_n = 0
        except Exception:
            self._autosave_fh = None

    def _autosave_row(self, result_dict):
        fh = getattr(self, '_autosave_fh', None)
        if fh is None:
            return
        try:
            vals = []
            for c in self._autosave_cols:
                v = result_dict.get(c, '')
                if isinstance(v, float):
                    vals.append(f'{v:.6g}')
                else:
                    vals.append(str(v))
            fh.write('\t'.join(vals) + '\n')
            self._autosave_n += 1
            if self._autosave_n % 50 == 0:
                fh.flush()
        except Exception:
            pass

    def _autosave_close(self):
        fh = getattr(self, '_autosave_fh', None)
        if fh is not None:
            try:
                fh.flush()
                fh.close()
            except Exception:
                pass
            self._autosave_fh = None

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
