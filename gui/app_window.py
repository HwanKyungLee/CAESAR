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
                             QComboBox, QSplitter, QTabWidget, QTabBar, QDoubleSpinBox, QSpinBox,
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
        _chtab_bar = QHBoxLayout()
        self._channel_tabbar = QTabBar()
        self._channel_tabbar.setExpanding(False)
        i0 = self._channel_tabbar.addTab("CH1")
        self._channel_tabbar.setTabData(i0, 1)
        self._channel_tabbar.currentChanged.connect(self._on_channel_tab_changed)
        _chtab_bar.addWidget(self._channel_tabbar, 1)
        _btn_addc = QPushButton("➕"); _btn_addc.setFixedWidth(int(30 * self._s))
        _btn_addc.setToolTip("채널 추가(현재 채널 설정을 복사해서 새 채널 생성)")
        _btn_addc.clicked.connect(self._add_channel_tab)
        _btn_delc = QPushButton("✕"); _btn_delc.setFixedWidth(int(30 * self._s))
        _btn_delc.setToolTip("현재 채널 삭제")
        _btn_delc.clicked.connect(self._del_channel_tab)
        _chtab_bar.addWidget(_btn_addc); _chtab_bar.addWidget(_btn_delc)
        _chtab_bar.addWidget(QLabel("Label:"))
        self._ed_ch_datalabel = QLineEdit()
        self._ed_ch_datalabel.setFixedWidth(int(80 * self._s))
        self._ed_ch_datalabel.setPlaceholderText("자동")
        self._ed_ch_datalabel.setToolTip(
            "기본은 알파 헤더의 채널번호(# channel=N)로 자동 분배 → 비워두면 됨(캠페인 무관).\n"
            "특수 케이스만 라벨 override: 파일명/헤더 label/'ch{N}' 중 매칭되는 알파를 이 채널로.")
        _chtab_bar.addWidget(self._ed_ch_datalabel)
        _chtab_bar.addWidget(QLabel("TZ:"))
        self.cb_input_tz = QComboBox()
        self.cb_input_tz.addItems(["UTC", "KST(+9)"])
        self.cb_input_tz.setFixedWidth(int(80 * self._s))
        self.cb_input_tz.setToolTip(
            "이 채널 데이터(계기시각)의 타임존. 출력 시각(결과 Time·농도탭)을 UTC로 통일.\n"
            "KST(+9) 선택 시 결과 시각을 −9h 해서 UTC로 변환. (Cold 6월·Hot 6월=UTC, Hot 5월=KST)")
        _chtab_bar.addWidget(self.cb_input_tz)
        _chtab_bar.addWidget(QLabel("Gas T:"))
        self.spin_gas_temp = QDoubleSpinBox()
        self.spin_gas_temp.setRange(0.0, 600.0)
        self.spin_gas_temp.setDecimals(0)
        self.spin_gas_temp.setValue(0.0)
        self.spin_gas_temp.setFixedWidth(int(60 * self._s))
        self.spin_gas_temp.setToolTip(
            "이 채널 가스의 실제 온도(°C) — ppb 밀도(n_air) 보정용. 0 = 자동(권장).\n"
            "자동: raw 핏 시 HK의 채널별 실측 셀 가스온도(tempcell, CH1≈34/CH2≈31.5°C)를 읽음\n"
            "(박사님 확인 2026-06-10: tempcell = 셀 통과 가스온도. 75°C는 셀히터 설정값이라 미사용).\n"
            "주의: 기존(이 수정 전) 생성된 Hot 알파 파일은 T_C 컬럼에 75°C가 박혀 있을 수 있음\n"
            "→ 그 알파로 핏할 땐 여기에 실측값을 수동 입력하거나 알파를 재생성.")
        _chtab_bar.addWidget(self.spin_gas_temp)
        # L4: 시나리오(전 채널 핏세팅) 로드/저장 — 분석의 출발점이라 왼쪽 상단 상주
        _btn_scn_load = QPushButton("📋")
        _btn_scn_load.setFixedWidth(int(30 * self._s))
        _btn_scn_load.setToolTip("Load fit scenario (all channels)")
        _btn_scn_load.clicked.connect(self.load_scenario)
        _chtab_bar.addWidget(_btn_scn_load)
        _btn_scn_save = QPushButton("💾")
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
        btn_mask = QPushButton("✂️ Mask")
        btn_mask.clicked.connect(self.open_mask_dialog)
        btn_mask.setStyleSheet("color: #cc0000; font-weight: bold;") 
        
        layout_load.addWidget(btn_batch)
        layout_load.addWidget(btn_add)
        layout_load.addWidget(btn_mask)
        lay_ref.addLayout(layout_load)
        
        # Lock References Button (L5: dirty면 빨강으로 강조)
        btn_lock = QPushButton("🔒 Lock References (Commit)")
        btn_lock.clicked.connect(self.lock_ref)
        btn_lock.setStyleSheet("font-weight: bold; padding: 5px;")
        self._btn_lock_ref = btn_lock
        self._refs_dirty = False
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
        # ILS 콘볼루션 UI 제거(F2): Stage2 레퍼런스가 이미 ILS 적용됨 — 이중 콘볼루션
        # 위험만 있던 섹션. 위젯(spin_fwhm_nm 등)은 FWHM 자동계산 의존성 때문에 생성만 유지.
        self._btn_toggle_ils.setVisible(False)

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
        self.lbl_wavecal = QLabel("📐 wavecal: none")
        self.lbl_wavecal.setStyleSheet("color: #B71C1C; font-weight: bold; padding: 2px;")
        self.lbl_wavecal.setToolTip("Wavelength calibration loaded for this channel tab. Red = not loaded.")
        self.lbl_wavecal.setFixedWidth(int(180 * self._s))
        layout_px.addWidget(self.lbl_wavecal)

        self.lbl_fwhm_display = QLabel("💡 FWHM: —")
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

        layout_nm.addSpacing(12)
        layout_nm.addWidget(QLabel("Unit:"))
        self.cb_fit_unit = QComboBox()
        self.cb_fit_unit.addItems(["nm", "px"])
        self.cb_fit_unit.setToolTip(
            "nm: Fit 범위(nm)로 핏. px: 위의 Min/Max(픽셀)로 핏.\n"
            "박사님 시나리오(예: Cold 775-1550)는 px로 두면 픽셀 인덱스를 정확히 재현합니다.\n"
            "알파 피팅 시 px면 알파를 해당 픽셀구간으로 슬라이스해 핏합니다.")
        self.cb_fit_unit.setFixedWidth(int(50 * self._s))
        layout_nm.addWidget(self.cb_fit_unit)
        # px 입력칸 + Vis 버튼을 같은 행에 (calib 행에서 옮겨옴)
        layout_nm.addWidget(QLabel(" px"))
        layout_nm.addWidget(self.txt_min)
        layout_nm.addWidget(QLabel("~"))
        layout_nm.addWidget(self.txt_max)
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

        self.chk_robust = QCheckBox("🛡 Robust")
        self.chk_robust.setToolTip("Robust (IRLS): auto-ignore spike noise and cosmic rays")
        self.chk_robust.setChecked(False)

        self.chk_allow_neg = QCheckBox("± Neg")
        self.chk_allow_neg.setToolTip(
            "체크: 가스 계수 하한 0→−∞ (NNLS 해제). 0 근처 가스의 노이즈가 음수로도 나와\n"
            "양의 정류(rectification) 편향이 사라짐 → PNs 차분 비편향. 기본=꺼짐(≥0 강제).")
        self.chk_allow_neg.setChecked(False)

        self.ref_props = {}
        btn_props = QPushButton("⚙️ Properties")
        btn_props.setStyleSheet("font-weight: bold;")
        btn_props.clicked.connect(self.open_ref_properties)

        self.spin_rms_thresh = QDoubleSpinBox()
        self.spin_rms_thresh.setRange(1.0, 50.0)
        self.spin_rms_thresh.setSingleStep(1.0)
        self.spin_rms_thresh.setDecimals(1)
        self.spin_rms_thresh.setValue(10.0)
        self.spin_rms_thresh.setToolTip(
            "OK RMS Threshold(%): RMS residual < (signal mean × threshold) 이면 OK.\n"
            "10% = standard DOAS quality criterion.\n"
            "Lower = stricter. Raise only if data is extremely noisy.")

        self.chk_qc = QCheckBox("🚫 QC")
        self.chk_qc.setToolTip(
            "체크: RMS가 임계(위 OK RMS Threshold)를 넘는 'Unstable' 행, 또는 아래 SNR 하한 미만 행의\n"
            "가스 농도를 NaN으로 빼서 시계열·통계·내보내기에서 제외한다. Status에 사유 표기.\n"
            "구름/저광량 등으로 핏이 실패한 행(예: NO2가 -로 폭주하고 CHOCHO·H2O가 상쇄상승)을\n"
            "자동으로 걸러냄. 표준 DOAS QA/QC. 기본=켜짐.")
        self.chk_qc.setChecked(True)
        self.spin_qc_k = QDoubleSpinBox()
        self.spin_qc_k.setRange(0.0, 30.0)
        self.spin_qc_k.setDecimals(1)
        self.spin_qc_k.setSingleStep(1.0)
        self.spin_qc_k.setValue(8.0)
        self.spin_qc_k.setToolTip(
            "자동 QC 민감도(0=자동끔). 핏 종료 후 채널별 RMS 분포에서\n"
            "임계 = 10^(median(log10 RMS) + K·MAD)로 이상치를 자동 검출 → 가스값 NaN.\n"
            "매직넘버 입력 불필요. K 작을수록 엄격. 기본 8 (폭주 제거·96% 보존).\n"
            "'RMS상한'에 값을 직접 넣으면 그게 우선(수동 오버라이드).")
        self.spin_qc_rms = QDoubleSpinBox()
        self.spin_qc_rms.setRange(0.0, 1.0)
        self.spin_qc_rms.setDecimals(10)
        self.spin_qc_rms.setSingleStep(1e-8)
        self.spin_qc_rms.setValue(0.0)
        self.spin_qc_rms.setToolTip(
            "절대 RMS 상한(0=사용 안 함). 이 값을 넘는 행은 가스값을 NaN으로 QC 제외.\n"
            "구름/저광량으로 핏 실패한 행을 잡는 핵심 기준(상대 RMS는 이런 행을 놓침).\n"
            "콜드 알파 권장 ≈ 5e-8 (정상 max≈8e-8, 폭주 min≈8e-8). 데이터 보고 튜닝.")
        self.spin_qc_snr = QDoubleSpinBox()
        self.spin_qc_snr.setRange(0.0, 1e9)
        self.spin_qc_snr.setDecimals(0)
        self.spin_qc_snr.setValue(0.0)
        self.spin_qc_snr.setToolTip("추가 SNR 하한(0=사용 안 함). 이 값 미만 행도 QC 제외.")
        self.btn_reapply_qc = QPushButton("Reapply")
        self.btn_reapply_qc.setToolTip(
            "재핏 없이 현재 K(또는 RMS상한/SNR) 설정으로 자동 QC만 다시 적용.\n"
            "원본 농도를 복원 후 재필터하므로 K를 바꿔가며 여러 번 눌러도 안전.")
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
        # r1: QC 핵심
        _pg.addWidget(self.chk_qc,        1, 0, 1, 2)
        _pg.addWidget(_lbl("K"),     1, 2); _pg.addWidget(self.spin_qc_k,      1, 3)
        _pg.addWidget(self.btn_reapply_qc,1, 6, 1, 2)
        # r2: 가스별 Shift/Squeeze 요약
        from PyQt6.QtWidgets import QSizePolicy as _SPsq
        self.lbl_shsq = QLabel("Sh/Sq: (lock refs to show)")
        self.lbl_shsq.setStyleSheet("color:#555;")
        self.lbl_shsq.setToolTip("Per-gas Shift/Squeeze modes (edit in ⚙️ Properties)")
        self.lbl_shsq.setSizePolicy(_SPsq.Policy.Ignored, _SPsq.Policy.Preferred)
        _pg.addWidget(self.lbl_shsq, 2, 0, 1, 8)
        lay_calib_main.addLayout(_pg)

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

        # Observe/Turbo 체크박스 2개 → 표시 모드 콤보 1개로 통합
        layout_perf.addWidget(QLabel("Display:"))
        self.cb_display_mode = QComboBox()
        self.cb_display_mode.addItems(["Normal", "Observe (slow)", "Turbo (no plots)"])
        self.cb_display_mode.setToolTip(
            "일반: Update Every N대로 그래프 갱신\n"
            "관찰: 스캔당 200ms 지연 — 핏 과정을 눈으로 확인\n"
            "터보: 그래프 갱신 끔 — 최고 속도(밤샘 런 권장)")
        self.cb_display_mode.setFixedWidth(int(100 * self._s))
        layout_perf.addWidget(self.cb_display_mode)

        layout_perf.addSpacing(8)
        self.chk_auto_save = QCheckBox("Auto-save")
        self.chk_auto_save.setToolTip(
            "체크: 분석이 끝나면(QC 적용 후) 묻지 않고 기존 파일명 규칙으로 자동 저장.\n"
            "저장 위치 = 마지막 Save 폴더(없으면 Output\\fitting). 밤샘 런 권장.\n"
            "(autosave TSV는 크래시 대비 별도 — 이것은 정식 결과 저장)")
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
        self.main_tabs.addTab(_tab_scroll(self.setup_tab), "🛠️ Setup")

        # Tab 2: Analysis Monitor
        self.monitor = MonitorWidget(self.engine)
        self.main_tabs.addTab(_tab_scroll(self.monitor), "📈 Analysis Monitor")

        # Tab 3: Result Viewer (저장된 R/α/레퍼런스/농도 결과 파일을 불러와 표시)
        from .ui_result_viewer import ResultViewerWidget
        self.result_viewer = ResultViewerWidget(self)
        self.main_tabs.addTab(_tab_scroll(self.result_viewer), "📂 Result Viewer")

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
                self._left_scroll.setMinimumWidth(_lw)
                self._splitter.setSizes([_lw, max(400, self.width() - _lw)])
            except Exception:
                pass

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

        # (Fit Scenario 저장/로드 그룹 제거 — 왼쪽 패널 채널탭바 📋/💾 버튼으로 일원화, S2)

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
                f"✅  I₀: loaded ({len(self.i0_data)} px,  mean={self.i0_data.mean():.1f})")
            self.lbl_st_i0.setStyleSheet(_green)
        elif _is_alpha:
            self.lbl_st_i0.setText("✅  I₀: N/A  (already applied in alpha)")
            self.lbl_st_i0.setStyleSheet(_gray)
        else:
            self.lbl_st_i0.setText("ℹ️   I₀: auto from ZA scans during run")
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
                    f"✅  R: {r_med*100:.4f}%  Leff ≈ {leff:.0f} cm")
            else:
                self.lbl_st_r.setText("✅  R: loaded (no finite values in pixel range)")
            self.lbl_st_r.setStyleSheet(_green)
            self._update_daily_r_chart()
        elif _is_alpha:
            self.lbl_st_r.setText("✅  R: N/A  (already applied in alpha)")
            self.lbl_st_r.setStyleSheet(_gray)
        else:
            self.lbl_st_r.setText("ℹ️   R-Curve: auto from He scans during run")
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

        # Daily Run(Scenario + Setup Status) 흡수 — Setup 좌측 상단
        if hasattr(self, 'daily_run_tab'):
            control_layout.addWidget(self.daily_run_tab)

        # Group: Daily-use tools
        grp_calib = QGroupBox("Tools")
        lay_calib = QVBoxLayout()

        btn_calib_tool = QPushButton("🔍 Wavelength Calibration Tool")
        btn_calib_tool.clicked.connect(self.open_wavelength_calibration)

        btn_ref_gen = QPushButton("✂️ Reference Generator")
        btn_ref_gen.clicked.connect(self.open_reference_generator)
        btn_ref_gen.setStyleSheet("font-weight: bold;")

        btn_r_trend = QPushButton("📈 R Trend Monitor")
        btn_r_trend.clicked.connect(self.open_r_trend_monitor)
        btn_r_trend.setStyleSheet("font-weight: bold;")
        btn_r_trend.setToolTip(
            "raw .dat 파일 디렉토리를 스캔해서 파일마다 R 값을 계산하고\n"
            "반사율 시계열 그래프(PNG)와 결과(.dat)를 저장합니다.\n"
            "Cold / Hot 채널 분리 처리, Sellmeier 기반 Rayleigh 모델 사용."
        )

        btn_peak_trend = QPushButton("📈 Peak Trend (He/ZA)")
        btn_peak_trend.clicked.connect(self.open_peak_trend)
        btn_peak_trend.setToolTip(
            "raw .dat 를 읽어 flag별(ZA/He/Sampling) peak intensity 시계열을 그림.\n"
            "ZA/He는 cycle, Sampling은 시간bin 단위 avg·min/max → 이상치·주입주기 점검.")

        lay_calib.addWidget(btn_calib_tool)
        lay_calib.addWidget(btn_ref_gen)
        lay_calib.addWidget(btn_r_trend)
        lay_calib.addWidget(btn_peak_trend)
        grp_calib.setLayout(lay_calib)
        control_layout.addWidget(grp_calib)

        # S-B: Test Fit — RUN 전에 첫 알파 스캔 1개만 핏해 잔차·농도·shift를 즉석 확인.
        # 24일 밤샘 핏 전에 세팅 검증(콜드 8px 오정렬 같은 사고를 RUN 전에 잡음).
        btn_test_fit = QPushButton("🧪 Test Fit (1 scan)")
        btn_test_fit.setStyleSheet("font-weight: bold; padding: 6px; border: 1px solid #A5D6A7;")
        btn_test_fit.setToolTip(
            "Fit only the first loaded alpha scan and pop up data+model overlay,\n"
            "residual, reference overlays, retrieved ppb and shift/squeeze.\n"
            "Use to validate settings before a long RUN.")
        btn_test_fit.clicked.connect(self._test_fit)
        control_layout.addWidget(btn_test_fit)

        # Alpha Generator — raw → alpha 생성은 별도 팝업창에서(분석=알파 피팅과 분리).
        # 분석(좌측)은 알파를 넣고 RUN해 피팅. 알파 생성만 여기 Setup에서 창으로.
        btn_alpha_gen = QPushButton("🧪 Alpha Generator")
        btn_alpha_gen.clicked.connect(self.open_alpha_generator)
        btn_alpha_gen.setStyleSheet("font-weight: bold; padding: 8px; border: 1px solid #90CAF9;")
        btn_alpha_gen.setToolTip(
            "팝업창에서 raw 측정파일을 받아 α 스펙트럼(*_alpha_trace.dat)을 생성한다.\n"
            "wavecal/핏레인지/cavity/flags 는 이 메인 UI 설정을 그대로 사용.")
        control_layout.addWidget(btn_alpha_gen)

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
        _rl_hint = QLabel("  ← CH1 0.933 / CH2 0.995 / CH3 0.997")
        from PyQt6.QtWidgets import QSizePolicy as _SP
        _rl_hint.setSizePolicy(_SP.Policy.Ignored, _SP.Policy.Preferred)
        _rl_hint.setToolTip("Reference RL factors: CH1 0.9330 / CH2 0.9950 / CH3 0.9968")
        lay_rl.addWidget(_rl_hint)
        lay_rl.addStretch()
        lay_physics.addRow("RL (Purge 보정):", lay_rl)

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
        self._diag_tabs.addTab(tab_spectral, "📊 R(λ) Spectrum")

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
        self._diag_tabs.addTab(tab_trend, "📈 R/Leff Trend")

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

        self.rb_fwhm_alpha_engine = QRadioButton("Engine α (latest)")
        self.rb_fwhm_alpha_engine.setToolTip("Auto: latest *_alpha_trace.dat from alpha_save_dir")
        self.rb_fwhm_alpha_file   = QRadioButton("Load from file")
        self.rb_fwhm_alpha_engine.setChecked(True)
        row_a1 = QHBoxLayout()
        row_a1.addWidget(self.rb_fwhm_alpha_engine)
        row_a1.addWidget(self.rb_fwhm_alpha_file)
        ctl_lay.addRow("α source:", row_a1)

        btn_pick_alpha = QPushButton("📂 Pick α file…")
        btn_pick_alpha.clicked.connect(self._fwhm_pick_alpha_file)
        self.lbl_fwhm_alpha = QLabel("(auto)")
        self.lbl_fwhm_alpha.setStyleSheet("color: #555;")
        row_a2 = QHBoxLayout()
        row_a2.addWidget(btn_pick_alpha)
        row_a2.addWidget(self.lbl_fwhm_alpha, stretch=1)
        ctl_lay.addRow("α file:", row_a2)

        row_btn = QHBoxLayout()
        self.btn_fwhm_run = QPushButton("🌀 Run Validation")
        self.btn_fwhm_run.setStyleSheet("font-weight: bold;")
        self.btn_fwhm_run.clicked.connect(self._fwhm_run_validation)
        self.btn_fwhm_set_active = QPushButton("✅ Set as NO2 ref")
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

    def export_alpha_files(self, file_list=None, out_dir=None, avg_sec=None,
                           status_cb=None, done_cb=None, drnam_mat=None, ch_tab_map=None,
                           progress_cb=None, channels=None, gen_px_range=None):
        """BBCEAS alpha만 계산해 저장(피팅 없음). Hot 2채널이면 채널별로 각각.

        Alpha Generator 팝업이 raw 파일목록/출력폴더/avgsec를 넘겨 호출할 수 있다.
        인자가 없으면(레거시) 메인 file_list/프롬프트/메인 avgsec를 사용.
        wavecal/핏레인지/cavity/flags 는 항상 메인 UI 설정을 재사용한다.
        drnam_mat: 박사님 _avg_60s.mat 경로를 주면 그 std_t 그리드에 binning + 전체 2048px
        + per-bin .dat(ch{N}_{YYYYMMDD}_NNNNNN.dat) 박사님 형식으로 출력.
        반환: True(시작됨) / False(검증 실패)."""
        flist = list(file_list) if file_list is not None else getattr(self, 'file_list', None)
        if not flist:
            QMessageBox.warning(self, "No Files", "먼저 측정(raw) 파일을 로드하세요.")
            return False
        # raw 채널 → 핏세팅 탭 매핑(Alpha Generator). 비우면 raw 채널 N → 탭 N.
        self._alpha_ch_tab_map = {int(k): int(v) for k, v in (ch_tab_map or {}).items()}
        # 생성할 채널 선택(None=전체). 이미 만든 채널 재생성 방지용.
        self._alpha_sel_channels = set(int(c) for c in channels) if channels else None
        if getattr(self, 'wavelengths', None) is None and self.engine._wave_axis is None:
            QMessageBox.warning(self, "No Wavelength Cal",
                                "파장 캘리브레이션 파일을 먼저 로드하세요.")
            return False
        if out_dir is None:
            out_dir = QFileDialog.getExistingDirectory(self, "Alpha 파일 저장 폴더 선택", self._dlg_dir('alpha_out'))
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
                QMessageBox.warning(self, "std_t 실패",
                                    "박사님 _avg_60s.mat 에서 std_t_st/std_t_end 를 읽지 못했습니다.")
                return False
            self._alpha_drnam_bins = bins
            import re as _re
            m = _re.search(r'(\d{4})-(\d{2})-(\d{2})', os.path.basename(self._entry_filepath(flist[0])))
            self._alpha_drnam_date = (m.group(1) + m.group(2) + m.group(3)) if m else ""

        configs = self._build_alpha_channel_configs(n_ch, full_px=bool(drnam_mat),
                                                    gen_px_range=gen_px_range)
        if not configs:
            QMessageBox.warning(self, "채널 설정 실패",
                                "채널별 파장보정/픽셀 범위를 만들 수 없습니다.\n"
                                f"Hot(≥2ch)은 {self._WV_CAL_BASE}\\roi1,roi2 의 Calib 파일이 필요합니다.")
            return False
        _sel = getattr(self, '_alpha_sel_channels', None)
        _want = _sel if _sel is not None else set(range(1, n_ch + 1))
        got = set(c['channel'] for c in configs)
        _missing = sorted(_want - got)
        if _missing:
            QMessageBox.warning(self, "일부 채널 wavecal 없음",
                                f"선택한 채널 중 {sorted(got)}만 생성됩니다. 빠진 채널: {_missing}.\n"
                                f"빠진 채널은 wavecal(채널 탭 또는 {self._WV_CAL_BASE}\\roiN)이 없어 건너뜁니다.\n"
                                "계속 진행합니다.")

        # 채널별 워커를 순차 실행(큐). Hot=2채널 → PNs, ANs 각각 생성.
        self._alpha_queue      = list(configs)
        self._alpha_file_list  = flist
        self._alpha_out_dir    = out_dir
        self._alpha_avgsec     = float(avg_sec) if avg_sec is not None else 60.0
        self._alpha_dark       = getattr(self, 'dark_data', None)
        self._alpha_done_msgs  = []
        self._alpha_status_cb  = status_cb   # 팝업 진행표시(옵션)
        self._alpha_user_done_cb = done_cb   # 팝업 완료콜백(옵션)
        self._alpha_progress_cb = progress_cb  # 팝업 진행바(done, total) 콜백(옵션)
        self._alpha_total       = 0
        self._alpha_ch_done     = 0          # 완료된 채널 수(멀티채널 진행 표시용)
        self._alpha_n_ch        = n_ch
        self.status.setText(f"📁 Alpha 내보내기 시작 ({n_ch}채널)...")
        self._start_next_alpha_export()
        return True

    # wv_cal 자동탐색 베이스 (채널별 파장보정 — 사용자 지정 위치)
    _WV_CAL_BASE = r"C:\Doasis_Work\Output\wv_cal"

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
            self.status.setText(f"✅ Alpha 내보내기 완료 → {self._alpha_out_dir}")
            cb = getattr(self, '_alpha_user_done_cb', None)
            if cb:   # Alpha Generator 팝업이 띄운 경우 콜백으로 알림(자체 메시지)
                cb(self._alpha_out_dir, list(done))
            else:
                QMessageBox.information(
                    self, "Alpha Export 완료",
                    "채널별 α 저장 완료:\n" + "\n".join(done) +
                    f"\n\n저장 위치:\n{self._alpha_out_dir}\n"
                    "파일명: {소스}_{채널}_alpha_trace.dat\n"
                    "결과 뷰어 / 분석(RUN)에 사용 가능.")
            return
        cfg = self._alpha_queue.pop(0)
        self._alpha_status(f"📁 Alpha [{cfg['label']}] 계산 중 (px {cfg['pixel_min']}~{cfg['pixel_max']})...")
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
            channel       = cfg['channel'],
            avg_sec       = self._alpha_avgsec,
            channel_label = cfg['label'],
            std_t_bins    = getattr(self, '_alpha_drnam_bins', None),
            drnam_date    = getattr(self, '_alpha_drnam_date', ''),
            drnam_chlabel = f"ch{cfg['channel']}",
            # wide 형식: 멀티채널이면 ch{N}/ 하위폴더로 분리(단일이면 평면)
            channel_subdir = (f"ch{cfg['channel']}" if int(getattr(self, '_detected_channels', 1) or 1) > 1 else ""),
        )
        n_ch_tot = max(1, int(getattr(self, '_alpha_n_ch', 1) or 1))
        self._alpha_export_worker.total_ready.connect(
            lambda tot: setattr(self, '_alpha_total', max(1, int(tot))))
        self._alpha_export_worker.progress.connect(
            lambda n, lbl=cfg['label']: self._alpha_on_progress(n, lbl, n_ch_tot))
        self._alpha_export_worker.status_msg.connect(lambda m: print(f"[AlphaExport] {m}"))
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
                                "먼저 메인에서 파장 캘리브레이션을 로드하세요\n"
                                "(Alpha 생성은 그 설정을 사용합니다).")
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
        self._alpha_status(f"📁 [{lbl}] {pct}%  ({done:,}/{tot:,} 스캔)")
        cb = getattr(self, '_alpha_progress_cb', None)
        if cb:
            cb(pct, 100)

    def _on_alpha_channel_done(self, result, label):
        if str(result).startswith("ERROR"):
            self._alpha_done_msgs.append(f"  [{label}] 실패: {result}")
            self.status.setText(f"❌ Alpha [{label}] 실패")
        else:
            self._alpha_done_msgs.append(f"  [{label}] ✅")
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
            self.main_tabs.setCurrentWidget(self._tab_pages.get(self.setup_tab, self.setup_tab))   # switch to Setup tab
            
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
                # 파일명은 lbl_wavecal(생략표시)에만 — 여기(FWHM 라벨)는 짧게 상태만
                self.lbl_fwhm_display.setText("💡 WL ✓")
                if hasattr(self, 'lbl_wavecal'):
                    from PyQt6.QtGui import QFontMetrics
                    from PyQt6.QtCore import Qt as _Qt
                    _fm = QFontMetrics(self.lbl_wavecal.font())
                    _el = _fm.elidedText(f"📐 {os.path.basename(filepath)}",
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

    def _test_fit(self):
        """S-B/S-C: 첫 알파 스캔 1개만 핏 → 데이터/모델/잔차/레퍼런스 오버레이 팝업.
        실제 핏 경로(DoasFitter + get_model_components)를 그대로 써서 RUN과 동일하게 검증."""
        from PyQt6.QtWidgets import QMessageBox
        if not self.engine.is_engine_ready():
            QMessageBox.warning(self, "Test Fit", "Lock references first.")
            return
        files = self._channel_files.get(self._active_channel) or self.file_list
        if not files:
            QMessageBox.warning(self, "Test Fit", "Load data first.")
            return
        fp = self._entry_filepath(files[0])
        try:
            # ── 알파 첫 데이터행 + 파장헤더 읽기 ──
            wave_nm_file = None
            alpha_start = None
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
                        _iT, _iP = idx.get('T_C'), idx.get('P_mbar')
                        continue
                    if alpha_start is not None:
                        row = cols
                        break
            if wave_nm_file is None or row is None:
                QMessageBox.warning(self, "Test Fit",
                                    "Not an alpha file (no wavelength header).\n"
                                    "Test Fit currently supports alpha (*_alpha_trace.dat) input.")
                return
            if _iT is not None and _iT < len(row):
                T_C = float(row[_iT])
            if _iP is not None and _iP < len(row):
                P_mbar = float(row[_iP])
            n_pix = len(wave_nm_file)
            alpha = np.array([float(v) for v in row[alpha_start:alpha_start + n_pix]], dtype=float)

            # ── 핏 윈도우 슬라이스(px/nm — 활성 채널 설정) ──
            unit = self.cb_fit_unit.currentText() if hasattr(self, 'cb_fit_unit') else 'nm'
            if unit == 'px':
                pmin, pmax = int(self.txt_min.text()), int(self.txt_max.text())
                # 알파 헤더 px offset 보정
                px0 = int(wave_nm_file is not None and 0)  # alpha 헤더 첫 px
                sl = slice(max(0, pmin), min(n_pix, pmax + 1))
            else:
                lo, hi = self.spin_fit_start_nm.value(), self.spin_fit_end_nm.value()
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
            out = fitter.execute_varpro_fit(
                vp_pixel, a, np.eye(len(a)), active, fixed, linked, t0, lb, ub,
                self.spin_poly_deg.value(), 0.0, vp_center, 1.0, rp, T_C,
                self.spin_lambda.value(), self.chk_robust.isChecked(),
                allow_negative_gas=self.chk_allow_neg.isChecked() if hasattr(self, 'chk_allow_neg') else False)
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
            n_air = 2.68678e19 * (P_mbar / 1013.25) * (273.15 / (T_C + 273.15))
            ppb = {}
            for gi, nm in enumerate(eng.gas_list):
                sc = eng.scaling_factors.get(nm, 1.0); mu = eng.multipliers.get(nm, 1.0)
                ppb[nm] = (gas_coeffs[gi] * mu / sc) / n_air * 1e9

            self._show_test_fit_popup(fp, wl, a, full_model, resid, gas_models,
                                      ppb, opt_shifts, opt_squeezes, rms, T_C, P_mbar)
        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Test Fit failed", f"{e}\n\n{traceback.format_exc()[-600:]}")

    def _show_test_fit_popup(self, fp, wl, data, model, resid, gas_models,
                             ppb, shifts, squeezes, rms, T_C, P_mbar):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel
        import pyqtgraph as pg
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Test Fit — {os.path.basename(fp)}")
        dlg.resize(int(900 * self._s), int(640 * self._s))
        lay = QVBoxLayout(dlg)
        # 요약 라벨
        gtxt = "  ".join(f"{g}={ppb[g]:.2f}" for g in ppb)
        lay.addWidget(QLabel(
            f"<b>ppb:</b> {gtxt}    <b>RMS:</b> {rms:.2e}    "
            f"<b>Shift:</b> {shifts[0]:+.2f}px  <b>Squeeze:</b> {squeezes[0]:.4f}    "
            f"T={T_C:.1f}°C P={P_mbar:.0f}mb"))
        # 위: 데이터+모델 (+ 가스 성분 오버레이 S-C)
        pw1 = pg.PlotWidget(); pw1.setBackground('w'); pw1.showGrid(x=True, y=True, alpha=0.3)
        pw1.addLegend(offset=(10, 10))
        pw1.plot(wl, data, pen=pg.mkPen('#1976D2', width=2), name='α data')
        pw1.plot(wl, model, pen=pg.mkPen('#D32F2F', width=1.5), name='model')
        _pal = ["#388E3C", "#7B1FA2", "#0097A7", "#C2185B", "#5D4037"]
        if gas_models is not None:
            for gi, nm in enumerate(self.engine.gas_list):
                gm = gas_models[gi] if gi < len(gas_models) else None
                if gm is not None and len(gm) == len(wl):
                    pw1.plot(wl, gm, pen=pg.mkPen(_pal[gi % len(_pal)], width=1, style=Qt.PenStyle.DashLine),
                             name=f'{nm}')
        pw1.setLabel('left', 'α (cm⁻¹)'); pw1.setLabel('bottom', 'Wavelength (nm)')
        lay.addWidget(pw1, 2)
        # 아래: 잔차 (S-C)
        pw2 = pg.PlotWidget(); pw2.setBackground('w'); pw2.showGrid(x=True, y=True, alpha=0.3)
        pw2.plot(wl, resid, pen=pg.mkPen('#455A64', width=1))
        pw2.setLabel('left', 'Residual'); pw2.setLabel('bottom', 'Wavelength (nm)')
        pw2.setTitle(f"Residual (RMS={rms:.2e})")
        lay.addWidget(pw2, 1)
        dlg.show()

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
                self.status.setText(f"🔒 {success_count} references locked (auto, channel switch)")
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
                self.status.setText("⚠️ no references to lock (channel switch)")
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
        """Scans a selected folder (하위폴더 재귀) and loads all valid measurement files.
        날짜별 폴더(예: out/ch1/2026-05-18/...)에 흩어진 알파도 폴더 하나만 고르면 다 로드."""
        folder_path = QFileDialog.getExistingDirectory(self, "Select Measurement Folder (하위폴더 포함)", self._dlg_dir('data'))
        if folder_path:
            self._dlg_dir('data', folder_path)
            import glob as _glob
            valid_extensions = ('.dat', '.txt', '.csv')
            files = []
            for ext in valid_extensions:
                files += _glob.glob(os.path.join(folder_path, f'*{ext}'))
                files += _glob.glob(os.path.join(folder_path, '**', f'*{ext}'), recursive=True)
            # 파일명(날짜+스캔) 기준 정렬 — 하위폴더가 흩어져도 시간순 유지
            files = sorted(set(files), key=lambda f: (os.path.basename(f), f))
            if not files:
                QMessageBox.warning(self, "No Data",
                                    "선택한 폴더(하위폴더 포함)에 .dat/.txt/.csv 파일이 없습니다.")
                return
            # 날짜가 여러 개면 다중선택(특정 날짜만 피팅 가능)
            import re as _re
            def _date_of(f):
                m = _re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', os.path.basename(f))
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else "(날짜없음)"
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
        warn = ("\n\n⚠️ DUPLICATE scans found (same date-scan in >1 folder —\n"
                "possible mislabeled alphas):\n" + "\n".join(dupwarn)) if dupwarn else ""
        ret = QMessageBox.question(self, "Auto-distribute channels",
                                   "Distribute alpha files to channel tabs by label:\n\n" + "\n".join(lines)
                                   + warn
                                   + "\n\nProceed? (No = all into current channel)",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return False
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
        self.status.setText("📦 distributed: " + " · ".join(
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
        self.status.setText(f"📁 CH{ch} — {len(self.file_list)} file(s){_rng}")
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
            label = ch_labels.get(n, f"{n}채널")
            self.lbl_channel_info.setText(label)
            # (채널별 설정은 좌측 채널 탭으로 — 여기선 감지 정보만 표시)
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
        # 채널 탭 목록 → 다이얼로그 '적용 채널'로 범위를 채널별 설정
        tb = self._channel_tabbar
        channels = [(tb.tabData(i), tb.tabText(i)) for i in range(tb.count())]
        # 채널별 대표 스펙트럼 경로 — '적용 채널' 바꾸면 그 채널 데이터로 그래프 갱신
        channel_paths = {}
        for ch, _lbl in channels:
            flist = self._channel_files.get(ch)
            if flist:
                channel_paths[int(ch)] = self._entry_filepath(flist[len(flist) // 2])
        self.sel_dlg = RangeSelectorDialog(mid_file, mn, mx, self.engine, channels=channels,
                                           channel_paths=channel_paths,
                                           active_channel=self._active_channel)
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
        self.status.setText(f"✅ CH{ch} Fit 범위 = {lo:.1f}~{hi:.1f} nm")

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
        """채널별 데이터 파일 그룹. **기본: 알파 헤더의 채널 인덱스(# channel=N)로 자동
        분배** → 캠페인 무관(라벨 타이핑 불필요). 채널 config에 data_label을 적어두면 그게
        우선(파일명/헤더 label/채널index 어느 거로든 매칭). 둘 다 없으면 기존 _alpha_groups."""
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
            # 1) 사용자가 적은 data_label override(파일명/헤더label/'chN' 매칭)
            for ch, lbl in labels.items():
                if lbl and (lbl in name or lbl == hdr_lbl or lbl == f"ch{ch}"):
                    assigned = ch
                    break
            # 2) 기본: 헤더 채널 인덱스 → 같은 번호 탭(generic)
            if assigned is None and hdr_ch in tab_chs:
                assigned = hdr_ch
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
                "References were changed but 🔒 Lock was not pressed.\n"
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
            QMessageBox.warning(self, "데이터 없음",
                                "어느 채널에도 데이터가 없습니다.\n채널 탭을 선택하고 데이터를 로드하세요.")
            self._analysis_running = False
            return
        if empty_chs:
            self.status.setText(f"⚠️ 데이터 없는 채널 건너뜀: {', '.join('CH'+str(c) for c in empty_chs)}")
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
        
        # 표시 모드 콤보(일반/관찰/터보)
        _disp = self.cb_display_mode.currentText() if hasattr(self, 'cb_display_mode') else "Normal"
        delay_ms = 200 if _disp.startswith("Observe") else 0
        if _disp.startswith("Turbo"):
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

        # 채널 = 좌측 채널 탭. 각 탭이 자기 데이터로 병렬 피팅(현재 탭 설정 먼저 스냅샷).
        if self._active_channel in self._channel_configs:
            self._channel_configs[self._active_channel] = self._capture_config()
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
                tz_ch = cfg.get('input_tz', 'UTC')
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
                eng_ch = self.engine; rp_ch = getattr(self, 'ref_props', {})
                p0_ch, lo_ch, hi_ch = p0, bounds_low, bounds_high
                funit_ch = self.cb_fit_unit.currentText() if hasattr(self, 'cb_fit_unit') else 'nm'
                fnm_lo_ch = self.spin_fit_start_nm.value(); fnm_hi_ch = self.spin_fit_end_nm.value()
                tz_ch = self.cb_input_tz.currentText() if hasattr(self, 'cb_input_tz') else 'UTC'
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
            w.allow_negative_gas = self.chk_allow_neg.isChecked() if hasattr(self, 'chk_allow_neg') else False
            w.qc_enabled = self.chk_qc.isChecked() if hasattr(self, 'chk_qc') else True
            w.qc_rms_abs = self.spin_qc_rms.value() if hasattr(self, 'spin_qc_rms') else 0.0
            w.qc_snr_min = self.spin_qc_snr.value() if hasattr(self, 'spin_qc_snr') else 0.0
            w.kalman_q = kq_ch
            w.kalman_r = kr_ch
            # 알파 피팅 핏범위(px면 알파를 픽셀구간으로 슬라이스)
            w.fit_unit = funit_ch
            w.fit_lo_nm = fnm_lo_ch
            w.fit_hi_nm = fnm_hi_ch
            # 입력 TZ → UTC 변환(KST면 결과 시각 −9h)
            w.tz_offset_sec = -9 * 3600 if str(tz_ch).upper().startswith('KST') else 0
            # 가스온도 오버라이드(>0이면 ppb 밀도보정에 그 온도 사용; 0=자동 HK)
            w.gas_temp_override = gtemp_ch if gtemp_ch > 0 else None
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

            # L2: RUN 확인 다이얼로그용 채널별 설정 요약
            _wlname = os.path.basename(wl_ch) if wl_ch else '⚠️없음'
            _gt = f"{gtemp_ch:.0f}°C" if gtemp_ch > 0 else "auto"
            _gases = list(eng_ch.gas_list)
            self._run_summary.append(
                f"CH{ch} {lbl_ch or ''}\n"
                f"   📐 {_wlname}\n"
                f"   range px {pmin}-{pmax} ({funit_ch}) · Poly{cfg.get('poly_deg', self.spin_poly_deg.value()) if ch != self._active_channel and self._channel_configs.get(ch) else self.spin_poly_deg.value()}\n"
                f"   refs {len(_gases)}: {', '.join(_gases)}\n"
                f"   {self._shsq_text(_gases, rp_ch)}\n"
                f"   TZ {tz_ch} · GasT {_gt}")
            self._workers.append(w)

        if not self._workers:
            QMessageBox.warning(self, "채널/데이터 불일치",
                                "채널 탭에 매칭되는 데이터가 없습니다.\n"
                                "(알파 파일명의 _PNs_/_ANs_ 채널과 탭 수를 확인하세요)")
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
        self.status.setText("🏃 Analysis in progress...")

        # Switch to the Analysis Monitor automatically
        self.main_tabs.setCurrentWidget(self._tab_pages.get(self.monitor, self.monitor))

        # 크래시 대비 실시간 자동저장 시작 (결과 도착마다 TSV append)
        self._autosave_start()

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
            # 논블로킹 정지: w.wait()로 UI 스레드를 막으면 '응답없음'이 뜬다.
            # stop()이 is_running=False로 만들면 워커는 현재 스캔만 끝내고 루프를
            # 빠져나와 finished를 emit → analysis_finished()가 정상 흐름으로 호출되어
            # UI 복구 + 자동 QC(부분 결과 대상)를 수행한다.
            self._stop_requested = True
            for w in running:
                w.stop()
            self.status.setText("🛑 Stopping… (finishing current scan)")
            self.status.setStyleSheet("color: red; font-weight: bold;")
            self.b_stop.setEnabled(False)
            
    # ── 실시간 자동저장(autosave) ─────────────────────────────────────────
    # 밤샘 런이 크래시로 죽어도 그 시점까지의 결과가 디스크에 남도록, 결과가
    # 도착할 때마다 TSV에 append한다(50행마다 flush). 완료 시 정식 Save와 별개로
    # _autosave/ 폴더에 전체 기록이 남는다(QC 적용 전 원본값 기준).
    def _autosave_start(self):
        try:
            import time as _t
            try:
                from gui.dlg_dir import dlg_dir
                base = dlg_dir('save_results') or r'C:\Doasis_Work\Output\fitting'
            except Exception:
                base = os.getcwd()
            folder = os.path.join(base, '_autosave')
            os.makedirs(folder, exist_ok=True)
            self._autosave_path = os.path.join(
                folder, f'autosave_{_t.strftime("%Y%m%d_%H%M%S")}.tsv')
            cols = ['File', 'Channel', 'Time', 'RMS', 'Chi2', 'SNR', 'Status',
                    'Shift', 'Squeeze']
            for g in self.engine.gas_list:
                cols += [g, f'{g}_Error', f'{g}_Smooth']
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

    @staticmethod
    def _shsq_text(gases, props):
        """가스별 Shift/Squeeze 모드 한 줄 요약 (Link 관계 포함)."""
        props = props or {}
        def one(g):
            p = props.get(g, {})
            shm = p.get('sh_mode', 'Limit'); shv = str(p.get('sh_val', '-0.5, 0.5')).replace(' ', '')
            sqm = p.get('sq_mode', 'Fix');   sqv = str(p.get('sq_val', '1.0')).replace(' ', '')
            sh = f"→{p.get('sh_val','').strip()}" if shm == 'Link' else \
                 (f"[{shv}]" if shm == 'Limit' else (f"={shv}" if shm == 'Fix' else 'Free'))
            sq = f"→{p.get('sq_val','').strip()}" if sqm == 'Link' else \
                 (f"[{sqv}]" if sqm == 'Limit' else (f"={sqv}" if sqm == 'Fix' else 'Free'))
            return f"{g} Sh{sh}·Sq{sq}"
        return "Sh/Sq:  " + "  │  ".join(one(g) for g in gases)

    def _refresh_shsq_summary(self):
        """Parameters 그리드의 가스별 Sh/Sq 요약 라벨 갱신."""
        if not hasattr(self, 'lbl_shsq'):
            return
        gases = list(getattr(self.engine, 'gas_list', []) or [])
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
        """Triggered by the worker thread to update the table row-by-row."""
        self.results.append(result_dict)
        self._autosave_row(result_dict)   # 크래시 나도 여기까지는 디스크에 남음

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

        # 농도 시계열 탭 갱신(가스별 ppb)
        if hasattr(self.monitor, 'update_conc'):
            self.monitor.update_conc(result_dict, row_index)

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
            self._autosave_close()
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
        # ── 자동 품질필터(QC): 핏 종료 후 채널별 RMS 분포에서 robust 이상치 제외 ──
        qc_changed = self._apply_auto_qc()
        if qc_changed:
            self._refresh_after_qc(qc_changed)

        self._autosave_close()
        was_stopped = getattr(self, '_stop_requested', False)
        self._stop_requested = False
        if was_stopped:
            self.status.setText(f"🛑 Stopped — partial results ({len(self.results):,} rows)")
            self.status.setStyleSheet("color: orange; font-weight: bold;")
        else:
            self.status.setText(f"✅ {ch_label}Analysis Completed!")
            self.status.setStyleSheet("color: green; font-weight: bold;")
        # L3: 완료 시 자동 저장 (QC 적용 후, 정식 파일명 규칙)
        saved_msg = ""
        if (not was_stopped and hasattr(self, 'chk_auto_save')
                and self.chk_auto_save.isChecked() and self.results):
            try:
                self.save(auto=True)
                saved_msg = "\n💾 Auto-saved (see status bar)"
            except Exception as _e:
                saved_msg = f"\n⚠️ Auto-save failed: {_e}"

        qc_msg = f"\nAuto QC excluded: {len(qc_changed)} rows (gas → NaN)" if qc_changed else ""
        head = "Analyzed up to the stop point." if was_stopped else f"All files analyzed successfully ({n_ch} channel(s))."
        QMessageBox.information(self, "Done", f"{head}{qc_msg}{saved_msg}")

    def reapply_qc(self):
        """재핏 없이 현재 K 설정으로 자동 QC만 다시 적용(원본 농도 복원 후 재필터)."""
        if not getattr(self, 'results', None):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "QC", "No analysis results. Run a fit first.")
            return
        changed = self._apply_auto_qc()
        # 복원만 됐을 수도 있으니 항상 새로고침(전체 conc 재구성)
        self._refresh_after_qc(changed)
        from PyQt6.QtWidgets import QMessageBox
        K = self.spin_qc_k.value() if hasattr(self, 'spin_qc_k') else 8.0
        QMessageBox.information(self, "Reapply QC",
                                f"Reapplied with K={K:g}.\nExcluded: {len(changed)} / {len(self.results):,} rows")

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
        def _status_changed():
            return [i for i, r in enumerate(self.results)
                    if str(r.get('Status', '')) != prev_status[i]]
        if not (hasattr(self, 'chk_qc') and self.chk_qc.isChecked()):
            return _status_changed()   # 복원만 (이전 QC 해제)
        K = self.spin_qc_k.value() if hasattr(self, 'spin_qc_k') else 8.0
        if K <= 0:
            return _status_changed()   # 자동 끔(수동 RMS상한만 사용) — 복원만
        # 채널별 RMS 수집 → log공간 robust 임계
        by_ch = {}
        for r in self.results:
            try:
                rms = float(r.get('RMS', float('nan')))
            except Exception:
                rms = float('nan')
            if _np.isfinite(rms) and rms > 0:
                by_ch.setdefault(r.get('Channel', 1), []).append(rms)
        thr_by_ch = {}
        for ch, arr in by_ch.items():
            la = _np.log10(_np.asarray(arr))
            med = _np.median(la)
            mad = _np.median(_np.abs(la - med))
            thr_by_ch[ch] = 10 ** (med + K * mad) if mad > 0 else float('inf')
        for r in self.results:
            if str(r.get('Status', '')).startswith('QC-Excluded'):   # 워커 수동 QC는 유지
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
            _base = self._dlg_dir('save') or r'C:\Doasis_Work\Output\fitting'
            os.makedirs(_base, exist_ok=True)
            path = os.path.join(_base, default_fname)
        else:
            _start = os.path.join(self._dlg_dir('save'), default_fname) if self._dlg_dir('save') else default_fname
            path, _ = QFileDialog.getSaveFileName(self, "Save Data (멀티채널이면 채널별 자동명)", _start, "Data Files (*.dat);;CSV Files (*.csv)")
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

                def _ch_header(ch):
                    """채널별 세팅 헤더 한 줄(파일 상단)."""
                    lbl, tag = self._channel_settings_tag(int(ch))
                    cfg = self._channel_configs.get(int(ch)) or {}
                    return (f"# Channel {int(ch)} ({lbl}) settings: {tag}  "
                            f"gas_temp={cfg.get('gas_temp', 0)}°C  refs={','.join(g for g in self.engine.gas_list)}")

                # 채널 2개 이상이면 채널별 파일로 — 파일명=날짜범위_채널라벨_세팅
                chans = sorted(df['Channel'].dropna().unique()) if 'Channel' in df.columns else []
                out_dir = os.path.dirname(path) or (self._dlg_dir('save') or '.')
                if len(chans) > 1:
                    written = []
                    for ch in chans:
                        sub = df[df['Channel'] == ch]
                        lbl, tag = self._channel_settings_tag(int(ch))
                        fname = f"{_drange}_{lbl}_{tag}{ext}".lstrip('_')
                        cpath = os.path.join(out_dir, fname)
                        _write_df(sub, cpath, _ch_header(ch))
                        written.append(f"CH{int(ch)} → {fname} ({len(sub)} rows)")
                    if auto:
                        self.status.setText("💾 Auto-saved: " + " / ".join(written))
                    else:
                        QMessageBox.information(self, "Success",
                                               "🎉 Per-channel results saved!\n\n" + "\n".join(written))
                else:
                    _write_df(df, path)
                    if auto:
                        self.status.setText(f"💾 Auto-saved: {os.path.basename(path)}")
                    else:
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
        wlp = cfg.get('wl_path', '')
        if wlp and os.path.exists(wlp):
            wave = self._load_wavecal_array(wlp)
        if wave is None:   # 폴백: 현재 로드된 마스터 wavecal
            wl = getattr(self, 'wavelengths', None)
            wave = np.asarray(wl, dtype=float).flatten() if wl is not None else None
        if wave is not None:
            eng.set_wavelength_axis(wave)
        for ref in cfg.get('refs', []):
            if os.path.exists(ref.get('path', '')):
                try:
                    eng.add_reference(name=ref['name'], filepath=ref['path'],
                                      wave_nm=wave, multiplier=10.0 ** ref.get('mult', 0))
                except Exception as e:
                    print(f"[ch engine] ref 실패 {ref.get('name')}: {e}")
        try:
            eng.apply_ils_convolution(0.0)
        except Exception:
            pass
        return eng

    # ── 채널 탭(독립 설정) ─────────────────────────────────────────────
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
        """선택 채널이 보유한 파일 리스트를 표에 표시(소유권은 그대로)."""
        self.file_list = list(self._channel_files.get(ch, []))
        self.table.setRowCount(len(self.file_list))
        self.table.clearContents()
        for i, fp in enumerate(self.file_list):
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(self._entry_filepath(fp))))
        self.status.setText(f"📁 CH{ch} — {len(self.file_list)} file(s)")
        if self.file_list:
            self._auto_detect_channels()

    def _add_channel_tab(self):
        """➕ — 현재 채널 설정을 복사한 새 채널 탭 생성(시작값=복사본)."""
        import copy
        self._channel_configs[self._active_channel] = self._capture_config()
        new_ch = (max(self._channel_configs.keys()) + 1) if self._channel_configs else 1
        self._channel_configs[new_ch] = copy.deepcopy(self._channel_configs[self._active_channel])
        self._channel_files[new_ch] = []          # 새 채널 데이터는 비어서 시작(설정만 복사)
        i = self._channel_tabbar.addTab(f"CH{new_ch}")
        self._channel_tabbar.setTabData(i, new_ch)
        self._channel_tabbar.setCurrentIndex(i)   # currentChanged → 복사본 적용

    def _del_channel_tab(self):
        """✕ — 현재 채널 삭제(최소 1채널 유지)."""
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
            "input_tz": self.cb_input_tz.currentText() if hasattr(self, 'cb_input_tz') else "UTC",
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
            "kalman_q": self.spin_kalman_q.value() if hasattr(self, 'spin_kalman_q') else 0.0005,
            "kalman_r": self.spin_kalman_r.value() if hasattr(self, 'spin_kalman_r') else 0.050,
            "cavity_d": self.spin_d_len.value() if hasattr(self, 'spin_d_len') else 100.0,
            "rl_factor": self.spin_rl_factor.value() if hasattr(self, 'spin_rl_factor') else 1.0,
        }

    def _apply_config(self, scenario, load_refs=True):
        """_capture_config 로 만든 dict를 UI/엔진에 복원. load_refs=False면 레퍼런스/엔진은 건드리지 않음."""
        self.txt_min.setText(str(scenario.get("f_min", "")))
        self.txt_max.setText(str(scenario.get("f_max", "")))
        if hasattr(self, '_ed_ch_datalabel'):
            self._ed_ch_datalabel.setText(scenario.get("data_label", ""))
        if hasattr(self, 'cb_input_tz'):
            self.cb_input_tz.setCurrentText(scenario.get("input_tz", "UTC"))
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
        if hasattr(self, 'spin_kalman_q'):
            self.spin_kalman_q.setValue(scenario.get("kalman_q", 0.0005))
        if hasattr(self, 'spin_kalman_r'):
            self.spin_kalman_r.setValue(scenario.get("kalman_r", 0.050))
        if hasattr(self, 'spin_d_len') and "cavity_d" in scenario:
            self.spin_d_len.setValue(scenario["cavity_d"])
        if hasattr(self, 'spin_rl_factor') and "rl_factor" in scenario:
            self.spin_rl_factor.setValue(scenario["rl_factor"])

        wl_path = scenario.get("wl_path", "")
        if wl_path and os.path.exists(wl_path):
            self.load_wavelength_cal(auto_path=wl_path)
        elif hasattr(self, 'lbl_wavecal'):
            self.lbl_wavecal.setText("📐 wavecal: none")
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
                if os.path.exists(ref['path']):
                    self.add_ref_row(name=ref['name'], path=ref['path'])
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
                QMessageBox.information(self, "Success", f"{len(chans)}채널 설정 저장!\nFile: {os.path.basename(path)}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Save Failed:\n{e}")

    def load_scenario(self):
        """저장된 fit 설정 JSON 복원. v2(채널들) / v1(단일) 모두 지원."""
        path, _ = QFileDialog.getOpenFileName(self, "Load Fit Scenario", self._dlg_dir('scenario'), "JSON Files (*.json)")
        if not path:
            return
        self._dlg_dir('scenario', path)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                scenario = json.load(f)
            if isinstance(scenario, dict) and "channels" in scenario:   # v2 멀티채널
                chans = {int(c): cfg for c, cfg in scenario["channels"].items()}
                self._load_channel_scenario(chans, scenario.get("active", sorted(chans)[0]))
                QMessageBox.information(self, "Auto-Load Success",
                                        f"🚀 {len(chans)}채널 설정 복원됨(채널 탭).\n[Load Data] 후 RUN 하세요!")
            else:   # v1 단일(하위호환)
                self._apply_config(scenario, load_refs=True)
                self._channel_configs = {1: self._capture_config()}
                QMessageBox.information(self, "Success", "📂 설정 복원됨(단일 채널).")
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
 