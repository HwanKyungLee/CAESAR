"""gui/monitor_widget.py
MonitorWidget — ui_dialogs_ref.py에서 분리(클래스 단위).
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
                             QSplashScreen, QDialogButtonBox, QStackedWidget, QFormLayout)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPixmap


class MonitorWidget(QWidget):
    """
    [V11.0 Ultra-fast Hybrid Monitor - Anti-Flicker & Easy Navigation]
    """
    roi_selected = pyqtSignal(int, int)
    
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.wavelengths = None
        self.latest_fit_data = None
        self.latest_raw_data = None

        # Graph object cache (key to anti-flicker rendering)
        self.plot_items = {}
        self.curve_items = {}

        # ── R Viewer 자동갱신 타이머 ──────────────────────────────
        from PyQt6.QtCore import QTimer
        self._r_auto_timer = QTimer(self)
        self._r_auto_timer.timeout.connect(self._r_auto_refresh)

        layout = QVBoxLayout(self)

        # ── 표시 채널 선택 ───────────────────────────────────────────
        # 병렬 채널(CH1=PNs, CH2=ANs …) 피팅이 섞여 찍히는 것을 막기 위해
        # Components / Fit View 탭은 선택된 채널의 스캔만 렌더한다.
        self._view_channel = 1
        self._latest_by_channel = {}
        _chbar = QHBoxLayout()
        _chbar.addWidget(QLabel("Show channel:"))
        self.cb_fit_channel = QComboBox()
        self.cb_fit_channel.addItems(["CH1", "CH2", "CH3"])
        self.cb_fit_channel.setFixedWidth(80)
        self.cb_fit_channel.currentIndexChanged.connect(self._on_view_channel_changed)
        _chbar.addWidget(self.cb_fit_channel)
        _chbar.addStretch(1)
        layout.addLayout(_chbar)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.init_tab_components_pg()
        self.init_tab_fit_view_pg()
        self.init_tab_conc_pg()
        self.init_tab_trend_pg()
        self.init_tab_viewer_pg()
        self.init_tab_hq_mpl()
        # R Viewer 탭 제거(중복): 거울 반사율은 Setup 탭 → Cavity Diagnostics 한 곳에서만.
        # init_tab_r_viewer() 및 _r_* 헬퍼는 호출하지 않음(정의는 남겨두되 미사용).

    # Shared toolbar factory
    def _create_reset_toolbar(self, target_glw=None, target_pw=None):
        toolbar = QHBoxLayout()
        btn = QPushButton("🔄 Reset View (Auto Range)")
        btn.setStyleSheet("background-color: #f5f5f5; font-weight: bold; border: 1px solid #ccc; padding: 4px;")
        if target_glw:
            btn.clicked.connect(lambda: self._reset_glw_views(target_glw))
        elif target_pw:
            btn.clicked.connect(lambda: target_pw.enableAutoRange(axis='xy', enable=True))
        toolbar.addWidget(btn)
        toolbar.addStretch()
        return toolbar

    def _reset_glw_views(self, glw):
        """Reset all graphs in the GraphicsLayoutWidget to their original auto-range."""
        for item in glw.ci.items:
            if isinstance(item, pg.PlotItem):
                item.enableAutoRange(axis='xy', enable=True)

    # =========================================================
    # [Tab 1] Components (anti-flicker & residual display)
    # =========================================================
    def init_tab_components_pg(self):
        self.tab_comp = QWidget()
        layout = QVBoxLayout(self.tab_comp)
        
        self.glw_comp = pg.GraphicsLayoutWidget()
        layout.addLayout(self._create_reset_toolbar(target_glw=self.glw_comp))
        layout.addWidget(self.glw_comp)
        
        self.tabs.addTab(self.tab_comp, "🧩 Components (Fast)")

    # =========================================================
    # [Tab 2] Fit View
    # =========================================================
    def init_tab_fit_view_pg(self):
        self.tab_spec = QWidget()
        layout = QVBoxLayout(self.tab_spec)
        
        self.glw_spec = pg.GraphicsLayoutWidget()
        layout.addLayout(self._create_reset_toolbar(target_glw=self.glw_spec))
        
        self.p_meas = self.glw_spec.addPlot(row=0, col=0)
        self.p_meas.setLabel('left', 'Intensity')
        self.p_meas.addLegend(offset=(10, 10))
        
        self.p_resid = self.glw_spec.addPlot(row=1, col=0)
        self.p_resid.setLabel('left', 'Residual')
        self.p_resid.setXLink(self.p_meas)
        self.p_resid.addLegend(offset=(10, 10))
        
        self.curve_meas = self.p_meas.plot(pen=None, symbol='o', symbolSize=3, symbolBrush='gray', name='Meas')
        self.curve_fit = self.p_meas.plot(pen=pg.mkPen('r', width=2), name='Fit')
        self.curve_resid = self.p_resid.plot(pen=pg.mkPen('b', width=1), name='Resid')
        
        self.p_resid.addItem(pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('k', style=Qt.PenStyle.DashLine)))
        
        layout.addWidget(self.glw_spec)
        self.tabs.addTab(self.tab_spec, "📊 Fit View (Fast)")

    # =========================================================
    # [Tab 3] Trend (full dataset with free zoom/scroll)
    # =========================================================
    def init_tab_trend_pg(self):
        self.tab_trend = QWidget()
        layout = QVBoxLayout(self.tab_trend)
        
        self.glw_trend = pg.GraphicsLayoutWidget()
        layout.addLayout(self._create_reset_toolbar(target_glw=self.glw_trend))
        
        self.p_sh = self.glw_trend.addPlot(row=0, col=0, title="Δ Shift Trend (ref: first scan)")
        self.p_sq = self.glw_trend.addPlot(row=1, col=0, title="Squeeze Trend")
        self.p_rms = self.glw_trend.addPlot(row=2, col=0, title="RMS Error Trend")
        self.p_rms.setLogMode(y=True)

        self.p_sh.setLabel('left', 'Δ Shift (px)')
        self.p_sq.setLabel('left', 'Squeeze')
        self.p_rms.setLabel('left', 'RMS')
        for p in [self.p_sh, self.p_sq, self.p_rms]:
            p.setClipToView(True)
            p.showGrid(x=True, y=True)
            p.setLabel('bottom', 'File Index')
            p.addLegend(offset=(10, 10))

        # Channel colour palette  CH1=blue  CH2=orange  CH3=green
        _CH_COLORS = {1: '#1f77b4', 2: '#ff7f0e', 3: '#2ca02c'}

        # _trend_curves[ch][metric] → PlotDataItem
        # _trend_data[ch][metric]   → list
        self._trend_curves = {}
        self._trend_data   = {}
        for ch, col in _CH_COLORS.items():
            pen = pg.mkPen(col, width=1.5)
            lbl = f"CH{ch}"
            self._trend_curves[ch] = {
                'sh':  self.p_sh.plot(pen=pen, symbol='o', symbolSize=4, symbolBrush=col, name=lbl),
                'sq':  self.p_sq.plot(pen=pen, symbol='o', symbolSize=4, symbolBrush=col, name=lbl),
                'rms': self.p_rms.plot(pen=pen, symbol='o', symbolSize=4, symbolBrush=col, name=lbl),
            }
            self._trend_data[ch] = {'x': [], 'sh': [], 'sq': [], 'rms': [],
                                     'sh_ref': None}   # baseline shift for Δ display

        # Legacy single-channel aliases (keep for any external code that reads them)
        self.curve_sh  = self._trend_curves[1]['sh']
        self.curve_sq  = self._trend_curves[1]['sq']
        self.curve_rms = self._trend_curves[1]['rms']
        self.x_data, self.y_sh, self.y_sq, self.y_rms = \
            self._trend_data[1]['x'], self._trend_data[1]['sh'], \
            self._trend_data[1]['sq'], self._trend_data[1]['rms']
        
        layout.addWidget(self.glw_trend)
        self.tabs.addTab(self.tab_trend, "📈 Trend (Fast)")

    # =========================================================
    # [Tab 4] Viewer
    # =========================================================
    def init_tab_viewer_pg(self):
        self.tab_view = QWidget()
        l_view = QVBoxLayout(self.tab_view)
        
        h_ctrl = QHBoxLayout()
        self.cb_view = QComboBox()
        self.cb_view.addItem("Measurement")
        
        self.chk_autofit = QCheckBox("Auto-Fit Y")
        self.chk_autofit.setChecked(True)
        self.chk_raw = QCheckBox("Show Raw Data")
        self.chk_raw.toggled.connect(self.refresh_current_plot) 
        
        b_snap = QPushButton("📸 Snapshot")
        b_snap.clicked.connect(self.snapshot_overlay)
        b_clear = QPushButton("🗑️ Clear")
        b_clear.clicked.connect(self.clear_overlays)
        
        h_ctrl.addWidget(QLabel("Data Target:"))
        h_ctrl.addWidget(self.cb_view)
        h_ctrl.addWidget(self.chk_autofit)
        h_ctrl.addWidget(self.chk_raw)
        h_ctrl.addWidget(b_snap)
        h_ctrl.addWidget(b_clear)
        h_ctrl.addStretch(1)
        
        l_view.addLayout(h_ctrl)
        
        self.pw_view = pg.PlotWidget()
        l_view.addLayout(self._create_reset_toolbar(target_pw=self.pw_view))
        self.pw_view.addLegend()
        self.pw_view.showGrid(x=True, y=True)
        self.curve_view = self.pw_view.plot(pen=pg.mkPen('b', width=1.5), name='Current')
        
        self.region = pg.LinearRegionItem()
        self.region.setZValue(10)
        self.pw_view.addItem(self.region)
        self.region.sigRegionChangeFinished.connect(self.on_select_span_pg)
        
        l_view.addWidget(self.pw_view)
        
        grp_stat = QGroupBox("📊 Statistics")
        h_stat = QHBoxLayout(grp_stat)
        self.lbl_max = QLabel("Max: 0"); self.lbl_min = QLabel("Min: 0")
        self.lbl_mean = QLabel("Mean: 0"); self.lbl_sat = QLabel("Status: OK")
        self.lbl_sat.setStyleSheet("color: green; font-weight: bold")
        h_stat.addWidget(self.lbl_max); h_stat.addWidget(self.lbl_min); h_stat.addWidget(self.lbl_mean); h_stat.addWidget(self.lbl_sat)
        l_view.addWidget(grp_stat)
        
        # 탭 제거(2026-06-12, 미사용 확인): 위젯은 update 경로 의존성 때문에 생성 유지
        # self.tabs.addTab(self.tab_view, "Quick View (raw)")

    # =========================================================
    # [Tab 5] HQ Export
    # =========================================================
    def init_tab_hq_mpl(self):
        self.tab_hq = QWidget()
        l_hq = QVBoxLayout(self.tab_hq)
        
        h_ctrl = QHBoxLayout()
        btn_render = QPushButton("🎨 Render High-Quality Graph")
        btn_render.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 5px;")
        btn_render.clicked.connect(self.render_hq_plot)
        h_ctrl.addWidget(btn_render)
        h_ctrl.addWidget(QLabel("👈 Click only when saving or exporting for publication!"))
        h_ctrl.addStretch(1)
        l_hq.addLayout(h_ctrl)
        
        self.fig_hq = Figure(figsize=(6, 5), dpi=120)
        self.cv_hq = FigureCanvas(self.fig_hq)
        self.tb_hq = NavigationToolbar(self.cv_hq, self.tab_hq)
        
        l_hq.addWidget(self.tb_hq)
        l_hq.addWidget(self.cv_hq)
        
        # 탭 제거(2026-06-12, 미사용 확인 — 고해상도 내보내기는 결과뷰어 📷 PNG로 대체)
        # self.tabs.addTab(self.tab_hq, "HQ Export")


    # [Tab 6] R Viewer — 거울 반사율 시계열 + 스펙트럼 뷰어
    # =========================================================
    def init_tab_r_viewer(self):
        self.tab_r = QWidget()
        lay = QVBoxLayout(self.tab_r)

        from PyQt6.QtWidgets import QLineEdit, QComboBox

        # ── 행1: R 결과 폴더 ──────────────────────────────────
        row1 = QHBoxLayout()
        self._r_dir_edit = QLineEdit()
        self._r_dir_edit.setPlaceholderText("R result folder  (contains R_Cold / R_Hot_PNs / R_Hot_ANs)")
        btn_r = QPushButton("📂"); btn_r.setFixedWidth(30)
        btn_r.clicked.connect(lambda: self._r_pick(self._r_dir_edit))
        row1.addWidget(QLabel("Result folder:")); row1.addWidget(self._r_dir_edit, 4); row1.addWidget(btn_r)
        lay.addLayout(row1)

        # ── 행2: 원본 Cold .dat 폴더 ──────────────────────────
        row2 = QHBoxLayout()
        self._r_cold_edit = QLineEdit()
        self._r_cold_edit.setPlaceholderText("Cold raw folder  (for timestamps; if absent, inferred from filename date)")
        btn_c = QPushButton("📂"); btn_c.setFixedWidth(30)
        btn_c.clicked.connect(lambda: self._r_pick(self._r_cold_edit))
        row2.addWidget(QLabel("Cold raw:")); row2.addWidget(self._r_cold_edit, 4); row2.addWidget(btn_c)
        lay.addLayout(row2)

        # ── 행3: 원본 Hot .dat 폴더 ───────────────────────────
        row3 = QHBoxLayout()
        self._r_hot_edit = QLineEdit()
        self._r_hot_edit.setPlaceholderText("Hot raw folder  (for timestamps; if absent, inferred from filename date)")
        btn_h = QPushButton("📂"); btn_h.setFixedWidth(30)
        btn_h.clicked.connect(lambda: self._r_pick(self._r_hot_edit))
        row3.addWidget(QLabel("Hot raw:")); row3.addWidget(self._r_hot_edit, 4); row3.addWidget(btn_h)
        lay.addLayout(row3)

        # ── 행4: 컨트롤 ───────────────────────────────────────
        row4 = QHBoxLayout()
        btn_load = QPushButton("▶ Load")
        btn_load.setStyleSheet("background-color:#4CAF50;color:white;font-weight:bold;")
        btn_load.clicked.connect(self._r_load_all)

        # 자동갱신 토글 버튼
        from PyQt6.QtWidgets import QSpinBox
        self._r_auto_btn = QPushButton("🔄 Auto-refresh OFF")
        self._r_auto_btn.setCheckable(True)
        self._r_auto_btn.setFixedWidth(130)
        self._r_auto_btn.setStyleSheet(
            "QPushButton{background:#888;color:white;font-weight:bold;border-radius:4px;}"
            "QPushButton:checked{background:#FF5722;color:white;}"
        )
        self._r_auto_btn.toggled.connect(self._r_toggle_auto)

        self._r_interval_spin = QSpinBox()
        self._r_interval_spin.setRange(1, 60)
        self._r_interval_spin.setValue(5)
        self._r_interval_spin.setSuffix(" min")
        self._r_interval_spin.setFixedWidth(65)
        self._r_interval_spin.setToolTip("Auto-refresh interval (min)")
        self._r_interval_spin.valueChanged.connect(self._r_update_interval)

        self._r_last_lbl = QLabel("")
        self._r_last_lbl.setStyleSheet("color:#555; font-size:11px;")

        # 채널 가시성 체크박스
        self._r_chk = {}
        for ch, col in [("Cold","#1f77b4"), ("Hot PNs","#d62728"), ("Hot ANs","#ff7f0e")]:
            chk = QCheckBox(ch)
            chk.setChecked(True)
            chk.setStyleSheet(f"color:{col}; font-weight:bold;")
            chk.stateChanged.connect(self._r_update_visibility)
            self._r_chk[ch] = chk
        self._r_info_lbl = QLabel("—")
        self._r_info_lbl.setStyleSheet("color:#1565C0; font-weight:bold;")
        # 표시 단위 콤보박스 (R % / Leff km)
        self._r_mode_cb = QComboBox()
        self._r_mode_cb.addItems(["R (%)", "Leff (km)"])
        self._r_mode_cb.setToolTip("Switch time-series/spectrum between reflectance (R) and effective path (Leff)")
        self._r_mode_cb.currentIndexChanged.connect(self._r_on_display_change)
        row4.addWidget(btn_load)
        row4.addWidget(self._r_auto_btn)
        row4.addWidget(self._r_interval_spin)
        row4.addWidget(self._r_last_lbl)
        row4.addWidget(QLabel("  Channel:"))
        for chk in self._r_chk.values(): row4.addWidget(chk)
        row4.addWidget(QLabel("  Unit:"))
        row4.addWidget(self._r_mode_cb)
        row4.addWidget(self._r_info_lbl, 1)
        lay.addLayout(row4)

        # ── 그래프 영역 ────────────────────────────────────────
        self._r_glw = pg.GraphicsLayoutWidget()
        lay.addWidget(self._r_glw)

        # 시계열 플롯 — DateAxisItem (KST = UTC+9)
        _date_ax = pg.DateAxisItem(orientation='bottom', utcOffset=9*3600)
        self._r_p_ts = self._r_glw.addPlot(
            row=0, col=0,
            title="R time-series  |  Wheel: Y-zoom  Ctrl+Wheel: X-zoom  Right-click: pan  Click point: spectrum",
            axisItems={'bottom': _date_ax})
        self._r_p_ts.setLabel('left',   'R (%)')
        self._r_p_ts.setLabel('bottom', 'Time (KST)')
        self._r_p_ts.showGrid(x=True, y=True, alpha=0.4)
        self._r_p_ts.addLegend(offset=(10, 10))

        # 채널별 커브
        _CH = {"Cold":"#1f77b4", "Hot PNs":"#d62728", "Hot ANs":"#ff7f0e"}
        self._r_curves = {}
        self._r_marks  = {}
        for ch, col in _CH.items():
            self._r_curves[ch] = self._r_p_ts.plot(
                pen=pg.mkPen(col, width=2),
                symbol='o', symbolSize=6, symbolBrush=col,
                symbolPen=None, name=ch)
            self._r_marks[ch] = self._r_p_ts.plot(
                pen=None, symbol='star', symbolSize=16,
                symbolBrush=pg.mkBrush(255,80,0,230),
                symbolPen=pg.mkPen('k', width=1))

        # 수직선 (마우스 커서)
        self._r_vline = pg.InfiniteLine(angle=90, movable=False,
                                         pen=pg.mkPen('gray', style=Qt.PenStyle.DashLine))
        self._r_p_ts.addItem(self._r_vline, ignoreBounds=True)
        self._r_p_ts.scene().sigMouseMoved.connect(self._r_on_mouse_move)
        self._r_p_ts.scene().sigMouseClicked.connect(self._r_on_ts_click)

        # 스펙트럼 플롯
        self._r_glw.nextRow()
        self._r_p_sp = self._r_glw.addPlot(row=1, col=0,
                                             title="R spectrum  (shown when a time-series point is clicked)")
        self._r_p_sp.setLabel('left',   'R (%)')
        self._r_p_sp.setLabel('bottom', 'Wavelength (nm)')
        self._r_p_sp.showGrid(x=True, y=True, alpha=0.4)
        self._r_p_sp.addLegend(offset=(10, 10))
        self._r_curve_sp = self._r_p_sp.plot(pen=pg.mkPen('#1f77b4', width=1.5), name='R(λ)')

        # 내부 데이터  {ch: [(label, wave, r, ts_unix), ...]}
        self._r_data = {}
        self._r_ch_colors = _CH
        self._r_sel_ch  = None   # 마지막으로 클릭한 채널
        self._r_sel_idx = 0

        self.tabs.addTab(self.tab_r, "🪞 R Viewer")

    # ── 헬퍼 ─────────────────────────────────────────────────

    _R_D_CM = 51.8   # 캐비티 길이 [cm]

    @staticmethod
    def _r_mean_r(r_arr, trim=0.05):
        """엣지 픽셀 제외(양쪽 trim×100%) 후 평균 R (0~1)"""
        n = len(r_arr)
        lo, hi = int(n * trim), n - int(n * trim)
        return float(np.mean(r_arr[lo:hi])) if lo < hi else float(np.mean(r_arr))

    @classmethod
    def _r_leff_from_r(cls, r_arr, trim=0.05):
        """중앙 픽셀 평균 R → Leff (km).  Leff = d / (1-R)"""
        mean_r = cls._r_mean_r(r_arr, trim)
        omr = 1.0 - mean_r          # (1-R), 0~1
        if omr <= 0.0:
            return np.nan
        return cls._R_D_CM / omr * 1e-5   # cm → km

    def _r_on_display_change(self):
        """R/Leff 모드 전환 시 시계열·스펙트럼 동시 갱신"""
        self._r_draw_all()
        if self._r_sel_ch and self._r_sel_ch in self._r_data:
            self._r_show_spectrum(self._r_sel_ch, self._r_sel_idx)

    def _r_use_leff(self):
        return hasattr(self, '_r_mode_cb') and self._r_mode_cb.currentIndex() == 1

    # ── 자동갱신 ─────────────────────────────────────────────

    def _r_toggle_auto(self, checked: bool):
        """자동갱신 ON/OFF 토글."""
        if checked:
            interval_ms = self._r_interval_spin.value() * 60 * 1000
            self._r_auto_timer.start(interval_ms)
            self._r_auto_btn.setText("🔄 Auto-refresh ON")
        else:
            self._r_auto_timer.stop()
            self._r_auto_btn.setText("🔄 Auto-refresh OFF")
            self._r_last_lbl.setText("")

    def _r_update_interval(self, value: int):
        """스핀박스 변경 시 이미 실행 중이면 타이머 재시작."""
        if self._r_auto_timer.isActive():
            self._r_auto_timer.start(value * 60 * 1000)

    def _r_auto_refresh(self):
        """타이머 틱마다 호출 — 파일 다시 읽고 그래프 갱신."""
        self._r_load_all()
        import datetime
        now = datetime.datetime.now().strftime("%H:%M:%S")
        self._r_last_lbl.setText(f"Updated: {now}")

    def _r_pick(self, line_edit):
        from PyQt6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "Select folder", dlg_dir("ref_folder"))
        dlg_dir("ref_folder", d)
        if d: line_edit.setText(d)

    @staticmethod
    def _r_date_epoch(label):
        """YYYY-MM-DD-NNN → 해당 날짜 자정 UTC unix timestamp"""
        import calendar, datetime as _dt
        p = label.split("-")
        try:
            return float(calendar.timegm(_dt.date(int(p[0]),int(p[1]),int(p[2])).timetuple()))
        except Exception:
            return 0.0

    @staticmethod
    def _r_read_col1(raw_path, flag=500):
        """raw .dat에서 flag=500인 첫 행의 col1(UTC초) 반환. 없으면 None."""
        try:
            with open(raw_path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    tok = line.strip().split("\t")
                    if len(tok) < 5: continue
                    try:
                        if int(tok[4].strip()) == flag:
                            return float(tok[1].strip())
                    except Exception:
                        continue
        except Exception:
            pass
        return None

    def _r_get_ts(self, label, raw_dir):
        """label(YYYY-MM-DD-NNN)에 해당하는 unix timestamp(UTC epoch) 반환.

        Cold .dat  col1 = UTC seconds since UTC midnight  → day_epoch + col1
        Hot  .dat  col1 = KST seconds since KST midnight  → (day_epoch - 9h) + col1
          KST midnight = UTC midnight - 9h (같은 KST 날짜 기준)
          예) KST 2026-05-18 00:00 = UTC 2026-05-17 15:00
          따라서 UTC epoch = UTC_midnight_of_KSTdate - 9*3600 + col1_kst
        """
        day_epoch = self._r_date_epoch(label)
        # 경로에 'hot'이 포함되면 KST 기준 파일
        is_hot = raw_dir is not None and "hot" in raw_dir.lower()
        tz_offset = -9 * 3600 if is_hot else 0  # Hot: KST→UTC 보정

        if raw_dir:
            src = label + ".dat"
            for candidate in [
                os.path.join(raw_dir, src),
                os.path.join(raw_dir, "-".join(label.split("-")[:3]), src),
            ]:
                if os.path.exists(candidate):
                    col1 = self._r_read_col1(candidate)
                    if col1 is not None:
                        return day_epoch + tz_offset + col1
        # 원본 없을 때: 파일명 시퀀스로 1시간 간격 추정
        try:
            seq = int(label.split("-")[3]) - 1
        except Exception:
            seq = 0
        return day_epoch + tz_offset + seq * 3600.0

    def _r_load_records(self, ch_dir, raw_dir=None):
        """*_R.dat 읽기 → [(label, wave, r, ts_unix), ...] 시간순

        타임스탬프 전략:
          1순위: raw_dir 있으면 원본 .dat col1(UTC초, flag=500) 사용  → 정확한 절대 시각
          2순위: raw_dir 없으면 파일명 (YYYY-MM-DD-NNN) 날짜 기반 추정
                 - 날짜 자정 UTC + (NNN-1)×3600  — 하루 25+파일 시 날짜 경계 충돌 방지:
                   전체 파일을 (날짜, 일련번호) 순 정렬 후 global index × 3600 으로 단조증가 보장
        """
        # ── 1단계: 파일 목록 수집 ─────────────────────────────────────────
        raw_list = []   # [(label, fp)]
        for root, _, fnames in os.walk(ch_dir):
            for fn in sorted(fnames):
                if not fn.endswith("_R.dat"): continue
                label = fn.replace("_R.dat", "")
                raw_list.append((label, os.path.join(root, fn)))
        # 파일명 사전순 정렬 (YYYY-MM-DD-NNN 포맷은 사전순 = 시간순)
        raw_list.sort(key=lambda x: x[0])

        # ── 2단계: 타임스탬프 계산 ────────────────────────────────────────
        records = []
        for global_idx, (label, fp) in enumerate(raw_list):
            try:
                rows = []
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        s = line.strip()
                        if not s or s.startswith("#"): continue
                        parts = s.split("\t")
                        try: rows.append([float(x) for x in parts])
                        except ValueError: continue
                if not rows: continue
                d = np.array(rows)

                # 타임스탬프 결정
                if raw_dir:
                    ts = self._r_get_ts(label, raw_dir)   # 원본에서 실제 시각 읽기
                else:
                    # 날짜 자정 + (NNN-1)시간; 단, 하루 24h 초과 시 global index로 보정
                    day_epoch = self._r_date_epoch(label)
                    try:
                        seq = int(label.split("-")[3]) - 1
                    except Exception:
                        seq = global_idx
                    ts_cand = day_epoch + seq * 3600.0
                    # 이전 레코드와 충돌(≤0 간격) 나면 global_idx 기반으로 대체
                    if records and ts_cand <= records[-1][3]:
                        ts_cand = records[-1][3] + 3600.0
                    ts = ts_cand

                records.append((label, d[:, 0], d[:, 1], ts))
            except Exception:
                continue
        # records는 이미 시간순 (raw_list가 사전순 = 시간순)
        return records

    def _r_load_all(self):
        base     = self._r_dir_edit.text().strip()
        cold_raw = self._r_cold_edit.text().strip() or None
        hot_raw  = self._r_hot_edit.text().strip()  or None
        if not base or not os.path.isdir(base):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Warning", "Select an R result folder."); return

        sub = {
            "Cold":    (os.path.join(base, "R_Cold"),    cold_raw),
            "Hot PNs": (os.path.join(base, "R_Hot_PNs"), hot_raw),
            "Hot ANs": (os.path.join(base, "R_Hot_ANs"), hot_raw),
        }
        self._r_data = {}
        total = 0
        for ch, (d, raw) in sub.items():
            if os.path.isdir(d):
                recs = self._r_load_records(d, raw)
                self._r_data[ch] = recs
                total += len(recs)

        has_real = cold_raw or hot_raw
        self._r_info_lbl.setText(
            f"{total} files total  ({'actual time' if has_real else 'estimated time — set raw folder for accuracy'})")
        self._r_draw_all()

    def _r_draw_all(self):
        """3채널 모두 시계열 플롯에 그리기  (R % 또는 Leff km, 엣지 trimmed mean)"""
        use_leff = self._r_use_leff()
        all_ys = []

        for ch, recs in self._r_data.items():
            if not recs:
                self._r_curves[ch].setData([], [])
                self._r_marks[ch].setData([], [])
                continue
            ts = np.array([r[3] for r in recs])
            if use_leff:
                ys = np.array([self._r_leff_from_r(r[2]) for r in recs])
            else:
                ys = np.array([self._r_mean_r(r[2]) * 100.0 for r in recs])
            self._r_curves[ch].setData(ts, ys)
            self._r_marks[ch].setData([], [])
            all_ys.append(ys[np.isfinite(ys)])
            self._r_curves[ch].setVisible(self._r_chk[ch].isChecked())
            self._r_marks[ch].setVisible(self._r_chk[ch].isChecked())

        # y축 레이블·범위
        if use_leff:
            self._r_p_ts.setLabel('left', 'Leff (km)')
            pad_min = 0.5
        else:
            self._r_p_ts.setLabel('left', 'R (%)')
            pad_min = 0.02

        if all_ys:
            flat = np.concatenate(all_ys)
            flat = flat[np.isfinite(flat)]
            if len(flat):
                span = flat.max() - flat.min()
                pad  = max(span * 0.20, pad_min)
                self._r_p_ts.setYRange(flat.min()-pad, flat.max()+pad, padding=0)
        self._r_p_ts.enableAutoRange(axis='x')

        # 첫 채널 첫 파일 스펙트럼 기본 표시
        for ch in ["Cold", "Hot PNs", "Hot ANs"]:
            if self._r_data.get(ch):
                self._r_sel_ch  = ch
                self._r_sel_idx = 0
                self._r_show_spectrum(ch, 0)
                break

    def _r_update_visibility(self):
        for ch in self._r_chk:
            vis = self._r_chk[ch].isChecked()
            self._r_curves[ch].setVisible(vis)
            self._r_marks[ch].setVisible(vis)

    def _r_nearest(self, ts_x):
        """ts_x(unix)에 가장 가까운 (채널, 인덱스) 반환"""
        best_ch, best_idx, best_d = None, 0, float('inf')
        for ch, recs in self._r_data.items():
            if not recs or not self._r_chk[ch].isChecked(): continue
            ts_arr = np.array([r[3] for r in recs])
            idx    = int(np.argmin(np.abs(ts_arr - ts_x)))
            d      = abs(ts_arr[idx] - ts_x)
            if d < best_d:
                best_ch, best_idx, best_d = ch, idx, d
        return best_ch, best_idx

    def _r_on_mouse_move(self, pos):
        if not self._r_p_ts.sceneBoundingRect().contains(pos): return
        mp = self._r_p_ts.vb.mapSceneToView(pos)
        self._r_vline.setPos(mp.x())
        ch, idx = self._r_nearest(mp.x())
        if ch is None: return
        lbl, _, r, ts = self._r_data[ch][idx]
        import datetime as _dt
        kst = _dt.datetime.fromtimestamp(ts + 9*3600, tz=_dt.timezone.utc)
        if self._r_use_leff():
            val_str = f"Leff={self._r_leff_from_r(r):.3f} km"
        else:
            val_str = f"R={self._r_mean_r(r)*100:.5f}%"
        self._r_p_ts.setTitle(
            f"R time-series  |  near cursor: [{ch}] {lbl}  "
            f"{kst.strftime('%m-%d %H:%M')} KST  {val_str}"
        )

    def _r_on_ts_click(self, event):
        from PyQt6.QtCore import Qt as _Qt
        if event.button() != _Qt.MouseButton.LeftButton: return
        pos = event.scenePos()
        if not self._r_p_ts.sceneBoundingRect().contains(pos): return
        mp  = self._r_p_ts.vb.mapSceneToView(pos)
        ch, idx = self._r_nearest(mp.x())
        if ch is None: return
        self._r_sel_ch  = ch
        self._r_sel_idx = idx
        self._r_show_spectrum(ch, idx)

    def _r_show_spectrum(self, ch, idx):
        if ch not in self._r_data or idx >= len(self._r_data[ch]): return
        label, wave, r, ts = self._r_data[ch][idx]
        use_leff = self._r_use_leff()
        color = self._r_ch_colors.get(ch, '#1f77b4')
        self._r_curve_sp.setPen(pg.mkPen(color, width=1.5))

        if use_leff:
            r_safe = np.clip(r, 0.0, 1.0 - 1e-9)
            y_sp   = self._R_D_CM / (1.0 - r_safe) * 1e-5   # km per pixel
            self._r_p_sp.setLabel('left', 'Leff (km)')
        else:
            y_sp = r * 100.0
            self._r_p_sp.setLabel('left', 'R (%)')

        self._r_curve_sp.setData(wave, y_sp)

        # 선택 마커 (시계열 위에)
        for c in self._r_marks: self._r_marks[c].setData([], [])
        ts_arr = np.array([rec[3] for rec in self._r_data[ch]])
        if use_leff:
            ys_arr = np.array([self._r_leff_from_r(rec[2]) for rec in self._r_data[ch]])
        else:
            ys_arr = np.array([self._r_mean_r(rec[2])*100.0 for rec in self._r_data[ch]])
        self._r_marks[ch].setData([ts_arr[idx]], [ys_arr[idx]])

        # y축 범위: 엣지 제외한 1~99%ile 기준
        y_fin = y_sp[np.isfinite(y_sp)]
        if len(y_fin):
            n = len(y_sp)
            lo, hi = int(n*0.05), n - int(n*0.05)
            y_core = y_sp[lo:hi] if lo < hi else y_sp
            y_core = y_core[np.isfinite(y_core)]
            if len(y_core):
                p01 = float(np.percentile(y_core, 1))
                p99 = float(np.percentile(y_core, 99))
                pad = max((p99-p01)*0.15, 0.02 if not use_leff else 0.1)
                self._r_p_sp.setYRange(p01-pad, p99+pad, padding=0)

        import datetime as _dt
        kst = _dt.datetime.fromtimestamp(ts + 9*3600, tz=_dt.timezone.utc)
        kst_str = kst.strftime('%Y-%m-%d %H:%M KST')
        kst_short = kst.strftime('%m-%d %H:%M')

        if use_leff:
            leff = self._r_leff_from_r(r)
            val_str   = f"Leff={leff:.3f} km"
            info_str  = f"[{ch}]  {label}  {kst_short} KST  {val_str}"
        else:
            mean_r = self._r_mean_r(r)
            val_str  = f"R_mean={mean_r*100:.5f}%  R_max={float(np.max(r))*100:.5f}%"
            info_str = f"[{ch}]  {label}  {kst_short} KST  R={mean_r*100:.5f}%"

        self._r_p_sp.setTitle(f"[{ch}]  {label}  {kst_str}  {val_str}")
        self._r_info_lbl.setText(info_str)


    # ---------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------
    def refresh_current_plot(self):
        idx = self.cb_view.currentIndex()
        if idx >= 0: self.cb_view.currentIndexChanged.emit(idx)

    def set_wavelengths(self, wl):
        self.wavelengths = wl

    def get_x_axis(self, x_indices):
        if self.wavelengths is not None and len(self.wavelengths) > np.max(x_indices):
            return self.wavelengths[x_indices.astype(int)], "Wavelength (nm)"
        return x_indices, "Pixel Index"

    def on_select_span_pg(self):
        min_x, max_x = self.region.getRegion()
        x_data = self.curve_view.xData
        y_data = self.curve_view.yData
        if x_data is None or len(x_data) == 0: return
        
        idx_min = np.searchsorted(x_data, min_x)
        idx_max = np.searchsorted(x_data, max_x)
        if idx_max <= idx_min: return
        
        y_subset = y_data[idx_min:idx_max]
        self.update_stats(y_subset)
        
        if self.wavelengths is not None and len(self.wavelengths) > 0:
            px_min = np.abs(self.wavelengths - min_x).argmin()
            px_max = np.abs(self.wavelengths - max_x).argmin()
            self.roi_selected.emit(int(px_min), int(px_max))
        else:
            self.roi_selected.emit(int(min_x), int(max_x))
            
        if self.chk_autofit.isChecked() and len(y_subset) > 0:
            self.pw_view.setYRange(np.min(y_subset)*0.9, np.max(y_subset)*1.1)

    def snapshot_overlay(self):
        x = self.curve_view.xData
        y = self.curve_view.yData
        if x is None: return
        snap = self.pw_view.plot(x, y, pen=pg.mkPen('gray', style=Qt.PenStyle.DashLine), name='Snapshot')
        self.overlay_artists.append(snap)
        
    def clear_overlays(self):
        for line in self.overlay_artists: 
            self.pw_view.removeItem(line)
        self.overlay_artists = []
        
    def update_stats(self, y):
        if y is None or len(y) == 0: return
        ymax, ymin, ymean = np.max(y), np.min(y), np.mean(y)
        def format_val(v): return f"{v:.2e}" if (abs(v) > 10000 or abs(v) < 0.01 and v != 0) else f"{v:.2f}"
        
        self.lbl_max.setText(f"Max: {format_val(ymax)}")
        self.lbl_min.setText(f"Min: {format_val(ymin)}")
        self.lbl_mean.setText(f"Mean: {format_val(ymean)}")
        
        if ymax > 60000: 
            self.lbl_sat.setText("⚠️ SATURATED"); self.lbl_sat.setStyleSheet("color: red; font-weight: bold")
        else: 
            self.lbl_sat.setText("Status: OK"); self.lbl_sat.setStyleSheet("color: green; font-weight: bold")
            
    def plot_viewer(self, x, y, title, color='b', style='-', xband=None):
        self.latest_raw_data = (x, y, title)
        x_plot, x_label = self.get_x_axis(x)
        self.pw_view.setLabel('bottom', x_label)
        self.pw_view.setTitle(title)

        pen = pg.mkPen(color, width=1.5) if style == '-' else None
        sym = 'o' if style != '-' else None

        self.curve_view.setData(x_plot, y, pen=pen, symbol=sym, symbolSize=3, symbolBrush=color)
        self._apply_view_range(x_plot, np.asarray(y, dtype=float), xband, x_label)
        self.update_stats(y)

    def _apply_view_range(self, x_plot, y, xband, x_label):
        """Keep newly drawn data inside the visible viewport.

        - xband=(lo,hi) in nm: zoom to that target band (e.g. fit range 400~500)
          and fit Y to the data inside the band. Only honoured when the x-axis is
          in wavelength units.
        - else, if 'auto fit' is on: full autoRange.
        - else (manual zoom kept): only auto-fit when the new data's x-range does
          NOT overlap the current view, so a new dataset never lands fully
          off-screen (the "그래프 화면 넘어가서 안 보임" bug).
        """
        x_plot = np.asarray(x_plot, dtype=float)
        if x_plot.size == 0:
            return
        if xband is not None and str(x_label).startswith("Wavelength"):
            lo, hi = float(xband[0]), float(xband[1])
            if hi < lo:
                lo, hi = hi, lo
            self.pw_view.setXRange(lo, hi, padding=0.02)
            m = (x_plot >= lo) & (x_plot <= hi)
            yb = y[m] if np.any(m) else y
            yb = yb[np.isfinite(yb)]
            if yb.size:
                ylo, yhi = float(yb.min()), float(yb.max())
                pad = (yhi - ylo) * 0.1 or abs(yhi) * 0.1 or 1.0
                self.pw_view.setYRange(ylo - pad, yhi + pad, padding=0)
            return
        if self.chk_autofit.isChecked():
            self.pw_view.autoRange()
            return
        try:
            (xmin, xmax), _ = self.pw_view.getViewBox().viewRange()
            dxmin, dxmax = float(np.nanmin(x_plot)), float(np.nanmax(x_plot))
            if dxmax < xmin or dxmin > xmax:   # no overlap → data is off-screen
                self.pw_view.autoRange()
        except Exception:
            self.pw_view.autoRange()

    # ---------------------------------------------------------
    # Real-Time Rendering Methods
    # ---------------------------------------------------------
    def _on_view_channel_changed(self, idx):
        """채널 콤보 변경 → 새로 선택된 채널의 마지막 스캔을 즉시 다시 렌더."""
        self._view_channel = idx + 1
        data = self._latest_by_channel.get(self._view_channel)
        if data:
            self.update_spectrum(*data)

    def update_spectrum(self, pixel_idx, intensity_raw, intensity_fit, intensity_poly, fit_params, title):
        # 채널 필터: 어느 채널 스캔이든 최신본은 보관하되, 선택 채널만 화면에 렌더
        ch = int(fit_params.get('channel', 1)) if isinstance(fit_params, dict) else 1
        self._latest_by_channel[ch] = (pixel_idx, intensity_raw, intensity_fit, intensity_poly, fit_params, title)
        if ch != getattr(self, '_view_channel', 1):
            return
        self.latest_fit_data = (pixel_idx, intensity_raw, intensity_fit, intensity_poly, fit_params, title)

        if self.tabs.currentIndex() == 0:
            self.update_components(pixel_idx, intensity_raw, intensity_fit, intensity_poly, fit_params)
            
        x_plot, x_label = self.get_x_axis(pixel_idx)
        self.p_meas.setLabel('bottom', x_label)
        self.p_resid.setLabel('bottom', x_label)
        self.p_meas.setTitle(title)
        
        self.curve_meas.setData(x_plot, intensity_raw)
        self.curve_fit.setData(x_plot, intensity_fit)
        self.curve_resid.setData(x_plot, intensity_raw - intensity_fit)

    def update_components(self, pixel_idx, intensity_raw, intensity_fit, intensity_poly, fit_params):
        """
        Refreshes the per-gas component view using an anti-flicker technique.

        Anti-flicker pattern
        --------------------
        pyqtgraph PlotItem.plot() is slow — calling it every frame causes visible
        flickering.  Instead, we create all PlotDataItem objects ONCE (stored in
        self.curve_items) and then only call setData() on subsequent frames.
        setData() pushes new pixel arrays directly to the GPU without re-allocating
        the plot item, making updates fast enough for real-time display.

        The layout is rebuilt from scratch only when the number of gases changes.
        """
        gas_list = self.engine.gas_list
        if not gas_list: return

        # 1. Create plot frames only when the gas SET changes (개수뿐 아니라 이름까지).
        #    채널마다 H2O vs H2O-HITRAN처럼 이름이 달라 개수만 보면 옛 곡선키가 남아
        #    KeyError('H2O_data')가 났음 → 가스 이름 튜플로 판정.
        current_gas_count = len(gas_list)
        gas_key = tuple(gas_list)
        if "layout_ready" not in self.plot_items or self.plot_items.get("gas_key") != gas_key:
            self.glw_comp.clear()
            self.curve_items = {}
            cols = 2
            
            for i, name in enumerate(gas_list):
                p = self.glw_comp.addPlot(title=name)
                self.curve_items[f"{name}_data"] = p.plot(pen=None, symbol='o', symbolSize=2, symbolBrush='gray')
                self.curve_items[f"{name}_fit"] = p.plot(pen='r', width=1.5)
                if (i+1) % cols == 0: self.glw_comp.nextRow()
                
            self.p_poly_view = self.glw_comp.addPlot(title="Polynomial Baseline")
            self.curve_items["poly_raw"] = self.p_poly_view.plot(pen=None, symbol='o', symbolSize=1, symbolBrush='gray')
            self.curve_items["poly_fit"] = self.p_poly_view.plot(pen='b', width=1.5)
            if (current_gas_count+1) % cols == 0: self.glw_comp.nextRow()
            
            self.p_res_view = self.glw_comp.addPlot(title="Residual")
            self.curve_items["residual"] = self.p_res_view.plot(pen='b')
            self.p_res_view.addItem(pg.InfiniteLine(angle=0, pen=pg.mkPen('k', style=Qt.PenStyle.DashLine)))
            
            self.plot_items["layout_ready"] = True
            self.plot_items["gas_count"] = current_gas_count
            self.plot_items["gas_key"] = gas_key

        # 2. Update data smoothly without recreating frames
        x_plot, _ = self.get_x_axis(pixel_idx)
        residual = intensity_raw - intensity_fit 

        for i, name in enumerate(gas_list):
            if f"{name}_data" not in self.curve_items:
                continue   # 곡선 미생성(가스셋 전환 직후 등) — 다음 갱신에서 재구성
            gas_fit = self.engine.get_individual_gas_contribution(pixel_idx, fit_params['shifts'], fit_params['squeezes'], fit_params['gas_coeffs'], i)
            self.curve_items[f"{name}_data"].setData(x_plot, residual + gas_fit)
            self.curve_items[f"{name}_fit"].setData(x_plot, gas_fit)
            
        self.curve_items["poly_raw"].setData(x_plot, intensity_raw)
        self.curve_items["poly_fit"].setData(x_plot, intensity_poly)
        self.curve_items["residual"].setData(x_plot, residual)

    def update_trend(self, data: dict):
        """
        Appends one new data point to the trend graphs for the correct channel.

        Routes by data['channel'] so CH1 and CH2 (etc.) each draw their own
        colour-coded curves without overwriting each other.

        Trend graphs keep the entire history in memory so the user can freely
        zoom and scroll without data being thrown away.  Auto-range is only
        applied along the X-axis (file index) to follow new data, while Y-axis
        zoom is left under user control.
        """
        idx     = data.get('idx', 0)
        shift   = data.get('shift', 0.0)
        squeeze = data.get('squeeze', 1.0)
        rms     = data.get('rms', 0.0)
        ch      = data.get('channel', 1)

        # Fall back to CH1 bucket if an unsupported channel number arrives
        if ch not in self._trend_data:
            ch = 1

        td = self._trend_data[ch]
        td['x'].append(idx)

        # Δ shift: relative to the first scan's shift per channel so small
        # drifts are immediately visible instead of a constant offset.
        if td['sh_ref'] is None:
            td['sh_ref'] = shift
        td['sh'].append(shift - td['sh_ref'])

        td['sq'].append(squeeze)
        td['rms'].append(rms)

        # Redraw throttle: in Fast mode results arrive in bursts; calling setData()
        # (which re-uploads the whole array) per scan is O(n²) and freezes the GUI.
        # Append every point but only redraw every ~150ms; flush_plots() forces a
        # final draw at the end. (Harmless in Step mode — scans are slower than 150ms.)
        import time as _t
        if (_t.monotonic() - getattr(self, '_last_trend_draw', 0.0)) < 0.15:
            return
        self._last_trend_draw = _t.monotonic()
        self._redraw_trend(ch)

    def _redraw_trend(self, ch):
        td = self._trend_data[ch]
        tc = self._trend_curves[ch]
        tc['sh'].setData(td['x'], td['sh'])
        tc['sq'].setData(td['x'], td['sq'])
        rms_arr = np.array(td['rms'])
        rms_arr[rms_arr <= 0] = 1e-9
        tc['rms'].setData(td['x'], rms_arr)
        if self.p_sh.getViewBox().autoRangeEnabled():
            self.p_sh.enableAutoRange(axis='x', enable=True)
        if self.p_sq.getViewBox().autoRangeEnabled():
            self.p_sq.enableAutoRange(axis='x', enable=True)
        if self.p_rms.getViewBox().autoRangeEnabled():
            self.p_rms.enableAutoRange(axis='x', enable=True)

    def flush_plots(self):
        """Force a final redraw of trend + concentration curves (call when a run
        finishes) so the last throttled-out points are drawn."""
        for ch in list(self._trend_data.keys()):
            if self._trend_data[ch]['x']:
                self._redraw_trend(ch)
        for gas in getattr(self, '_conc_gases', []) or []:
            for ch in self._CONC_CH_COLORS:
                d = self._conc_data[gas][ch]
                if d['x']:
                    self._conc_curves[gas][ch].setData(d['x'], d['y'])

    def clear_trend(self):
        """Clears trend history for all channels."""
        for ch, td in self._trend_data.items():
            for k in ('x', 'sh', 'sq', 'rms'):
                td[k].clear()
            td['sh_ref'] = None   # reset baseline so next run starts from 0
            tc = self._trend_curves[ch]
            tc['sh'].setData([], [])
            tc['sq'].setData([], [])
            tc['rms'].setData([], [])
        # Keep legacy aliases consistent
        self.x_data = self._trend_data[1]['x']
        self.y_sh   = self._trend_data[1]['sh']
        self.y_sq   = self._trend_data[1]['sq']
        self.y_rms  = self._trend_data[1]['rms']

    # =========================================================
    # [Tab] 농도 시계열 (가스별 ppb) — 레퍼런스 넣은 기체 전부
    # =========================================================
    _CONC_CH_COLORS = {1: '#1f77b4', 2: '#ff7f0e', 3: '#2ca02c'}

    def init_tab_conc_pg(self):
        """가스별 농도(ppb) 시계열 탭. 가스 플롯은 RUN 시작 시 setup_conc_plots로 구성.
        시간축(datetime) + 가스 선택(전체/개별) + PNG 추출."""
        self.tab_conc = QWidget()
        layout = QVBoxLayout(self.tab_conc)

        bar = QHBoxLayout()
        btn_reset = QPushButton("🔄 Reset View")
        btn_reset.setStyleSheet("background-color:#f5f5f5; font-weight:bold; border:1px solid #ccc; padding:4px;")
        btn_reset.clicked.connect(lambda: self._reset_glw_views(self.glw_conc))
        bar.addWidget(btn_reset)
        bar.addWidget(QLabel("Show gas:"))
        self.cb_conc_gas = QComboBox()
        self.cb_conc_gas.addItem("All")
        self.cb_conc_gas.setFixedWidth(140)
        self.cb_conc_gas.currentIndexChanged.connect(lambda *_: self._relayout_conc())
        bar.addWidget(self.cb_conc_gas)
        btn_png = QPushButton("📷 Save PNG")
        btn_png.clicked.connect(self._export_conc_png)
        bar.addWidget(btn_png)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.glw_conc = pg.GraphicsLayoutWidget()
        layout.addWidget(self.glw_conc)
        # gas → PlotItem,  gas → {ch: curve},  gas → {ch: {'x':[], 'y':[]}}
        self._conc_plots  = {}
        self._conc_curves = {}
        self._conc_data   = {}
        self._conc_gases  = []
        self.tabs.addTab(self.tab_conc, "🧪 Conc")

    @staticmethod
    def _conc_time_x(result_dict, row_index):
        """result_dict['Time']('%Y-%m-%d %H:%M:%S') → epoch초(시간축용). 실패 시 None."""
        ts = str(result_dict.get('Time', ''))
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
            try:
                from datetime import datetime as _dt
                return _dt.strptime(ts, fmt).timestamp()
            except (ValueError, TypeError):
                pass
        return None

    def setup_conc_plots(self, gas_list):
        """RUN 시작 시 — 레퍼런스 가스마다 농도 시계열 플롯 1개씩(채널별 곡선) 재구성."""
        self.glw_conc.clear()
        self._conc_plots, self._conc_curves, self._conc_data = {}, {}, {}
        self._conc_gases = list(gas_list)
        self._conc_use_time = None     # 첫 점에서 결정(시간 파싱 가능하면 True)
        for gas in self._conc_gases:
            ax = pg.DateAxisItem(orientation='bottom')
            p = pg.PlotItem(axisItems={'bottom': ax})
            p.setTitle(f"{gas}  concentration")
            p.setLabel('left', f"{gas} (ppb)")
            p.setLabel('bottom', 'Time')
            p.showGrid(x=True, y=True)
            p.setClipToView(True)
            p.addLegend(offset=(10, 10))
            self._conc_plots[gas] = p
            self._conc_curves[gas] = {}
            self._conc_data[gas] = {}
            for ch, col in self._CONC_CH_COLORS.items():
                pen = pg.mkPen(col, width=1.5)
                self._conc_curves[gas][ch] = p.plot(pen=pen, symbol='o', symbolSize=4,
                                                    symbolBrush=col, name=f"CH{ch}")
                self._conc_data[gas][ch] = {'x': [], 'y': []}
        # 가스 선택 콤보 갱신
        if hasattr(self, 'cb_conc_gas'):
            self.cb_conc_gas.blockSignals(True)
            self.cb_conc_gas.clear()
            self.cb_conc_gas.addItem("All")
            for gas in self._conc_gases:
                self.cb_conc_gas.addItem(gas)
            self.cb_conc_gas.setCurrentIndex(0)
            self.cb_conc_gas.blockSignals(False)
        self._relayout_conc()

    def _relayout_conc(self):
        """가스 선택(전체/개별)에 따라 보이는 플롯 레이아웃 재배치(데이터 유지)."""
        if not hasattr(self, 'glw_conc'):
            return
        sel = self.cb_conc_gas.currentText() if hasattr(self, 'cb_conc_gas') else "All"
        gases = self._conc_gases if sel in ("All", "") else [sel]
        self.glw_conc.clear()
        for r, gas in enumerate(gases):
            if gas in self._conc_plots:
                self.glw_conc.addItem(self._conc_plots[gas], row=r, col=0)

    def update_conc(self, result_dict, row_index):
        """결과 1건(result_dict)에서 가스별 ppb를 뽑아 해당 채널 곡선에 추가(x=측정시각)."""
        if not self._conc_gases:
            return
        ch = result_dict.get('Channel', 1)
        if ch not in self._CONC_CH_COLORS:
            ch = 1
        x = self._conc_time_x(result_dict, row_index)
        if x is None:
            x = float(row_index)     # 시각 파싱 실패 시 스캔 # 폴백
        # Append every point; throttle the (O(n)) setData redraw to ~150ms so Fast-mode
        # bursts don't trigger O(n²) freezes. flush_plots() forces a final draw.
        for gas in self._conc_gases:
            if gas not in result_dict:
                continue
            try:
                y = float(result_dict.get(gas, 0.0))
            except (TypeError, ValueError):
                continue
            d = self._conc_data[gas][ch]
            d['x'].append(x)
            d['y'].append(y)
        import time as _t
        if (_t.monotonic() - getattr(self, '_last_conc_draw', 0.0)) < 0.15:
            return
        self._last_conc_draw = _t.monotonic()
        for gas in self._conc_gases:
            for cch in self._CONC_CH_COLORS:
                d = self._conc_data[gas][cch]
                if d['x']:
                    self._conc_curves[gas][cch].setData(d['x'], d['y'])
            p = self._conc_plots[gas]
            if p.getViewBox().autoRangeEnabled():
                p.enableAutoRange(axis='x', enable=True)

    def rebuild_trend(self, results):
        """Rebuild shift/squeeze/RMS trend curves from the full results list in one
        pass (bulk), for Fast mode which renders once at the end instead of per scan."""
        if not getattr(self, '_trend_data', None):
            return
        for ch in self._trend_data:
            td = self._trend_data[ch]
            for k in ('x', 'sh', 'sq', 'rms'):
                td[k].clear()
            td['sh_ref'] = None
        for i, r in enumerate(results):
            ch = r.get('Channel', 1)
            if ch not in self._trend_data:
                ch = 1
            td = self._trend_data[ch]
            sh = float(r.get('Shift', 0.0)); sq = float(r.get('Squeeze', 1.0))
            rms = float(r.get('RMS', 0.0) or 0.0)
            td['x'].append(i)
            if td['sh_ref'] is None:
                td['sh_ref'] = sh
            td['sh'].append(sh - td['sh_ref'])
            td['sq'].append(sq)
            td['rms'].append(rms)
        for ch in list(self._trend_data.keys()):
            if self._trend_data[ch]['x']:
                self._redraw_trend(ch)

    def clear_conc(self):
        """농도 시계열 히스토리 초기화."""
        for gas in self._conc_gases:
            for ch in self._CONC_CH_COLORS:
                self._conc_data[gas][ch] = {'x': [], 'y': []}
                self._conc_curves[gas][ch].setData([], [])

    def rebuild_conc(self, results):
        """결과 리스트 전체로 농도 시계열을 한 번에 재구성(벌크).
        update_conc를 행마다 호출하면 매번 전체 배열을 setData해 O(n²)로 멈춘다.
        여기선 데이터를 모은 뒤 곡선당 setData를 1회만 호출한다(자동 QC 후 사용)."""
        if not getattr(self, '_conc_gases', None):
            return
        for gas in self._conc_gases:
            for ch in self._CONC_CH_COLORS:
                self._conc_data[gas][ch] = {'x': [], 'y': []}
        for i, r in enumerate(results):
            ch = r.get('Channel', 1)
            if ch not in self._CONC_CH_COLORS:
                ch = 1
            x = self._conc_time_x(r, i)
            if x is None:
                x = float(i)
            for gas in self._conc_gases:
                if gas not in r:
                    continue
                try:
                    y = float(r.get(gas, 0.0))
                except (TypeError, ValueError):
                    continue
                d = self._conc_data[gas][ch]
                d['x'].append(x)
                d['y'].append(y)
        for gas in self._conc_gases:
            for ch in self._CONC_CH_COLORS:
                d = self._conc_data[gas][ch]
                self._conc_curves[gas][ch].setData(d['x'], d['y'])

    def _export_conc_png(self):
        """현재 농도 그래프(보이는 레이아웃)를 PNG로 저장."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        try:
            from gui.dlg_dir import dlg_dir
            start = dlg_dir("conc_png")
        except Exception:
            start = ""
        path, _ = QFileDialog.getSaveFileName(self, "Save concentration plot PNG",
                                              start or "concentration.png", "PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith('.png'):
            path += '.png'
        try:
            from gui.dlg_dir import dlg_dir
            dlg_dir("conc_png", path)
        except Exception:
            pass
        try:
            import pyqtgraph.exporters as pgex
            exporter = pgex.ImageExporter(self.glw_conc.scene())
            exporter.export(path)
            QMessageBox.information(self, "Saved", f"PNG saved:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"PNG save failed:\n{e}")

    # =========================================================
    # [HQ Export] 
    # =========================================================
    def render_hq_plot(self):
        """
        Renders a publication-quality Matplotlib figure from the latest fit data.

        Uses Matplotlib instead of pyqtgraph because Matplotlib produces
        vector-quality output (PDF, SVG, high-DPI PNG) suitable for papers.
        The interactive pyqtgraph tabs are optimized for speed; this tab is
        optimized for appearance — render only when you need to export.
        """
        if self.latest_fit_data is None:
            QMessageBox.warning(self, "No Data", "Please run the analysis or double-click to load data first!")
            return
            
        pixel_idx, intensity_raw, intensity_fit, intensity_poly, fit_params, title = self.latest_fit_data
        x_plot, x_label = self.get_x_axis(pixel_idx)
        residual = intensity_raw - intensity_fit
        
        self.fig_hq.clear()
        
        ax1 = self.fig_hq.add_subplot(211)
        ax1.plot(x_plot, intensity_raw, 'k.', markersize=2, alpha=0.4, label='Measured')
        ax1.plot(x_plot, intensity_fit, 'r-', lw=1.5, label='Fitted')
        ax1.set_title(f"High-Quality Export: {title}", fontweight='bold')
        ax1.set_ylabel("Intensity")
        ax1.legend(loc='upper right')
        ax1.grid(True, linestyle=':', alpha=0.6)
        
        ax2 = self.fig_hq.add_subplot(212, sharex=ax1)
        ax2.plot(x_plot, residual, 'b-', lw=1.2, label='Residual')
        ax2.axhline(0, color='k', linestyle='--', alpha=0.5)
        rms = np.sqrt(np.mean(residual**2))
        ax2.set_title(f"Residual (RMS = {rms:.2e})", color='green', fontsize=10)
        ax2.set_xlabel(x_label)
        ax2.set_ylabel("Residual")
        ax2.legend(loc='upper right')
        ax2.grid(True, linestyle=':', alpha=0.6)
        
        self.fig_hq.tight_layout()
        self.cv_hq.draw()
