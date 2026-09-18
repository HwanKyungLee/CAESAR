import os
import re
import numpy as np
import pyqtgraph as pg
pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')


# [PyQt6] Modules
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel,
                             QTableWidget, QProgressBar, QGroupBox, QLineEdit,
                             QScrollArea, QComboBox, QSplitter, QTabWidget, QTabBar,
                             QDoubleSpinBox, QSpinBox, QCheckBox)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QShortcut, QKeySequence

from core.engine import UniversalEngine
from core.data_io import DataIO
from core.paths import DEFAULT_CAMPAIGN
from core.__version__ import __version__
from .ui_dialogs import *
# 재수출 — 정의는 app_window_policy.py. tools/test_test_fit_dialog.py가 여기서 가져간다.
from .app_window_policy import _scenario_gas_policy, _channel_worker_gas_policy  # noqa: F401
from .app_window_cavity import CavityTabMixin          # §3
from .app_window_inputs import InputsAlphaMixin       # §4~§6
from .app_window_fitsetup import FitSetupMixin        # §7~§9
from .app_window_dataload import DataLoadMixin        # §10
from .app_window_run import AnalysisRunMixin          # §11
from .app_window_results import ResultsQCMixin         # §12
from .app_window_save import SaveExportMixin           # §13
from .app_window_channels import ChannelConfigMixin    # §14


class CAESARAnalyzer(CavityTabMixin, InputsAlphaMixin, FitSetupMixin, DataLoadMixin,
                     AnalysisRunMixin, ResultsQCMixin, SaveExportMixin,
                     ChannelConfigMixin, QMainWindow):
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
    #   §12 결과 테이블 / QC / fast 렌더  -> gui/app_window_results.py
    #   §13 저장 + 결과뷰어 연동  -> gui/app_window_save.py
    #   §14 채널 탭 + 시나리오 config  -> gui/app_window_channels.py
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
            "Low-signal retry trigger(%): when RMS ≥ (signal mean × threshold), the scan is\n"
            "refit once in defensive mode (auto pre-calibration of shift/squeeze).\n"
            "This is NOT the OK/Unstable label — that comes from Chi2 (residual vs the scan's own\n"
            "pixel noise), because a small alpha shrinks the denominator here and would mark\n"
            "perfectly good fits Unstable. Lower = more scans get the defensive refit.")

        self.chk_qc = QCheckBox("QC")
        self.chk_qc.setToolTip(
            "Checked: rows above 'RMS max' or below the SNR floor get gas concentration NaN,\n"
            "excluding them from time-series·stats·export. The reason is prepended to Status.\n"
            "Catches cloud/low-light fit failures (NO2 runs negative while CHOCHO·H2O rise to offset).\n"
            "NOTE: the OK/Unstable label is NOT a criterion — it is relative RMS (signal strength), so\n"
            "using it would delete low-concentration rows that fit perfectly (chi2~1) and bias the mean up.\n"
            "Both thresholds default to 0 = off, so QC alone excludes nothing until you set one.\n"
            "Standard DOAS QA/QC. Default = off (flag-only philosophy — enable to exclude).")
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
            "Step: sequential — inspect each fit one at a time (pace = the delay box).")
        self.cb_display_mode.setFixedWidth(int(120 * self._s))
        layout_perf.addWidget(self.cb_display_mode)

        # Step 모드 스캔당 지연. 예전엔 200ms 하드코딩이었고, 그 값의 진짜 이유는
        # "그리는 쪽이 핏을 못 따라간다"는 백프레셔였다. 이제 emit 자체에 20fps
        # 상한이 걸려 있어(worker._run) 렌더 보호는 거기서 한다 — 여기 값은 순수하게
        # '사람이 한 핏씩 보는 속도'다. 0 = 지연 없음(핏 속도 그대로).
        self.spin_step_delay = QSpinBox()
        self.spin_step_delay.setRange(0, 2000)
        self.spin_step_delay.setValue(200)
        self.spin_step_delay.setSingleStep(50)
        self.spin_step_delay.setSuffix(" ms")
        self.spin_step_delay.setMaximumWidth(int(80 * self._s))
        self.spin_step_delay.setToolTip(
            "Step mode only: delay per scan, so you can watch each fit.\n"
            "0 = no delay (runs at fit speed ~2.5ms/scan; plots are capped at 20fps anyway).")
        self.spin_step_delay.setEnabled(self.cb_display_mode.currentText().startswith("Step"))
        self.cb_display_mode.currentTextChanged.connect(
            lambda t: self.spin_step_delay.setEnabled(t.startswith("Step")))
        layout_perf.addWidget(self.spin_step_delay)

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

