"""gui/monitor_widget.py
MonitorWidget — ui_dialogs_ref.py에서 분리(클래스 단위).
"""
import sys
import os
import datetime
import time
import numpy as np
import pyqtgraph as pg
pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')

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

    # Shared toolbar factory
    def _create_reset_toolbar(self, target_glw=None, target_pw=None):
        toolbar = QHBoxLayout()
        btn = QPushButton("Reset View (Auto Range)")
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
        
        self.tabs.addTab(self.tab_comp, "Components (Fast)")

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
        self.tabs.addTab(self.tab_spec, "Fit View (Fast)")

    # =========================================================
    # [Tab 3] Trend (full dataset with free zoom/scroll)
    # =========================================================
    def init_tab_trend_pg(self):
        self.tab_trend = QWidget()
        layout = QVBoxLayout(self.tab_trend)
        
        self.glw_trend = pg.GraphicsLayoutWidget()
        layout.addLayout(self._create_reset_toolbar(target_glw=self.glw_trend))
        
        # x축 = 측정시각(DateAxisItem). 채널별로 자기 시간에 찍혀 CH1/CH2가 같은 시간축에
        # 겹쳐 그려진다(예전 통합 File Index는 채널을 끼워넣어 '띄엄띄엄'으로 보였음).
        self.p_sh = self.glw_trend.addPlot(row=0, col=0, title="Δ Shift Trend (ref: first scan)",
                                           axisItems={'bottom': pg.DateAxisItem(orientation='bottom')})
        self.p_sq = self.glw_trend.addPlot(row=1, col=0, title="Squeeze Trend",
                                           axisItems={'bottom': pg.DateAxisItem(orientation='bottom')})
        self.p_rms = self.glw_trend.addPlot(row=2, col=0, title="RMS Error Trend",
                                            axisItems={'bottom': pg.DateAxisItem(orientation='bottom')})
        self.p_rms.setLogMode(y=True)

        self.p_sh.setLabel('left', 'Δ Shift (px)')
        self.p_sq.setLabel('left', 'Squeeze')
        self.p_rms.setLabel('left', 'RMS')
        for p in [self.p_sh, self.p_sq, self.p_rms]:
            p.setClipToView(True)
            p.showGrid(x=True, y=True)
            p.setLabel('bottom', 'Time')
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
        self.tabs.addTab(self.tab_trend, "Trend (Fast)")

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
        
        h_ctrl.addWidget(QLabel("Data Target:"))
        h_ctrl.addWidget(self.cb_view)
        h_ctrl.addWidget(self.chk_autofit)
        h_ctrl.addWidget(self.chk_raw)
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
        
        grp_stat = QGroupBox("Statistics")
        h_stat = QHBoxLayout(grp_stat)
        self.lbl_max = QLabel("Max: 0"); self.lbl_min = QLabel("Min: 0")
        self.lbl_mean = QLabel("Mean: 0"); self.lbl_sat = QLabel("Status: OK")
        self.lbl_sat.setStyleSheet("color: green; font-weight: bold")
        h_stat.addWidget(self.lbl_max); h_stat.addWidget(self.lbl_min); h_stat.addWidget(self.lbl_mean); h_stat.addWidget(self.lbl_sat)
        l_view.addWidget(grp_stat)
        
        # 탭 제거(2026-06-12, 미사용 확인): 위젯은 update 경로 의존성 때문에 생성 유지
        # self.tabs.addTab(self.tab_view, "Quick View (raw)")

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

    def update_stats(self, y):
        if y is None or len(y) == 0: return
        ymax, ymin, ymean = np.max(y), np.min(y), np.mean(y)
        def format_val(v): return f"{v:.2e}" if (abs(v) > 10000 or abs(v) < 0.01 and v != 0) else f"{v:.2f}"
        
        self.lbl_max.setText(f"Max: {format_val(ymax)}")
        self.lbl_min.setText(f"Min: {format_val(ymin)}")
        self.lbl_mean.setText(f"Mean: {format_val(ymean)}")
        
        if ymax > 60000: 
            self.lbl_sat.setText("SATURATED"); self.lbl_sat.setStyleSheet("color: red; font-weight: bold")
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
            
        # Polynomial Baseline 뷰: 점 = 브로드밴드 신호(diff_data + poly = signal−etalon),
        # 선 = 피팅된 폴리. intensity_poly가 0이 아니면 폴리가 실제 적용된 것.
        self.curve_items["poly_raw"].setData(x_plot, intensity_raw + intensity_poly)
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
        # x = 측정시각(epoch초). data에 'Time'이 있으면 그걸 쓰고, 없으면 idx 폴백.
        _x = self._conc_time_x(data, idx)
        td['x'].append(_x if _x is not None else idx)

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
        btn_reset = QPushButton("Reset View")
        btn_reset.setStyleSheet("background-color:#f5f5f5; font-weight:bold; border:1px solid #ccc; padding:4px;")
        btn_reset.clicked.connect(lambda: self._reset_glw_views(self.glw_conc))
        bar.addWidget(btn_reset)
        bar.addWidget(QLabel("Show gas:"))
        self.cb_conc_gas = QComboBox()
        self.cb_conc_gas.addItem("All")
        self.cb_conc_gas.setFixedWidth(140)
        self.cb_conc_gas.currentIndexChanged.connect(lambda *_: self._relayout_conc())
        bar.addWidget(self.cb_conc_gas)
        btn_png = QPushButton("Save PNG")
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
        self.tabs.addTab(self.tab_conc, "Conc")

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
            x = self._conc_time_x(r, i)        # 측정시각(epoch초); 실패 시 행번호 폴백
            td['x'].append(x if x is not None else float(i))
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
