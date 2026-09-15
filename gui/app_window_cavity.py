"""gui/app_window_cavity.py
CAESARAnalyzer §3 — Cavity 탭 + FWHM/ILS 검증 (gui/app_window.py에서 분리).

**순수 이동이다.** 메서드 본문은 한 글자도 안 고쳤다 — 호출부가 전부 self.xxx()라
믹스인으로 옮기는 것만으로 동작이 같다. 로직 개선은 다음 PR로.
가드는 tools/test_app_window_smoke.py (표면 골든 + 믹스인 이름 충돌 검사).
"""
import os
import re
import numpy as np
import pandas as pd
import pyqtgraph as pg

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QRadioButton, QTabWidget,
                             QVBoxLayout, QWidget)

from core.data_io import DataIO


class CavityTabMixin:
    """Cavity 탭 구성 + FWHM/ILS 검증 + alpha QC. CAESARAnalyzer에 믹스인된다."""

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

