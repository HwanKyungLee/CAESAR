import sys
import os
import math
import datetime
import time
import json
import numpy as np
import pandas as pd
import pyqtgraph as pg
pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.family'] = 'Malgun Gothic'
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

from data_io import DataIO

# [PyQt6] Modules
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, 
                             QProgressBar, QGroupBox, QLineEdit, QScrollArea, QDialog, 
                             QComboBox, QSplitter, QTabWidget, QDoubleSpinBox, QSpinBox, 
                             QCheckBox, QGridLayout, QInputDialog, QRadioButton, QButtonGroup,
                             QSplashScreen, QDialogButtonBox, QStackedWidget, QFormLayout)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPixmap

class NavigationHelper:
    """
    Helper class providing mouse wheel zoom, drag panning, 
    and double-click reset functionality for Matplotlib graphs.
    """
    def __init__(self, ax, base_scale=1.2, mode='pan_left'):
        self.ax = ax
        self.base_scale = base_scale
        self.mode = mode
        
        # State variables
        self.is_panning = False
        self.x0 = None
        self.y0 = None
        
        # Connect canvas events
        self.canvas = ax.figure.canvas
        self.canvas.mpl_connect('scroll_event', self.zoom)
        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('button_release_event', self.on_release)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)
        self.canvas.mpl_connect('button_press_event', self.on_double_click)
    
    def zoom(self, event):
        """Zoom in/out using the mouse wheel."""
        # Ignore if the mouse is outside the graph area
        if event.inaxes != self.ax: 
            return
            
        cur_xlim = self.ax.get_xlim()
        cur_ylim = self.ax.get_ylim()
        xdata = event.xdata
        ydata = event.ydata
        
        if xdata is None or ydata is None: 
            return
            
        # Determine scale factor based on scroll direction (up = zoom out, down = zoom in)
        scale_factor = 1 / self.base_scale if event.button == 'up' else self.base_scale
            
        # Calculate new width and height
        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor
        
        # Calculate ratio based on cursor position to keep the view fixed under the cursor
        relx = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
        rely = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])
        
        # Set new axis limits
        self.ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * relx])
        self.ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * rely])
        
        self.canvas.draw_idle()

    def on_press(self, event):
        """Store the starting position for drag panning."""
        if event.inaxes != self.ax: 
            return
            
        # Enable panning on left (1) or right (3) click based on mode
        target_button = 1 if self.mode == 'pan_left' else 3
        
        if event.button == target_button: 
            self.is_panning = True
            self.x0 = event.xdata
            self.y0 = event.ydata

    def on_release(self, event):
        """Stop drag panning on mouse release."""
        self.is_panning = False

    def on_motion(self, event):
        """Pan the graph when dragging the mouse."""
        if not self.is_panning or event.xdata is None or event.ydata is None: 
            return
            
        # Calculate distance moved
        dx = event.xdata - self.x0
        dy = event.ydata - self.y0
        
        # Move the view by subtracting the distance from current limits
        self.ax.set_xlim(self.ax.get_xlim() - dx)
        self.ax.set_ylim(self.ax.get_ylim() - dy)
        
        self.canvas.draw_idle()

    def on_double_click(self, event):
        """Reset zoom and pan state on left double-click."""
        if event.dblclick and event.button == 1 and event.inaxes == self.ax:
            self.ax.relim()       # Recalculate data limits
            self.ax.autoscale()   # Autoscale axis limits to fit data
            self.canvas.draw_idle()


# =============================================================================
# 4. Setup & Calibration Dialogs (Preparation)
# =============================================================================
class WavelengthCalibrationDialog(QDialog):
    calibration_finished = pyqtSignal(np.ndarray)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🛠️ Wavelength Calibration Tool (Interactive)")
        self.resize(1100, 700)
        
        # --- Internal Data Variables ---
        self.spectrum = None
        self.pixels = None
        self.peak_markers = []  # Stores the X markers displayed on the graph
        self.fwhm_records = {}

        # Initialize UI
        self.init_ui()
        
    def init_ui(self):
        # -----------------------------------------------------
        # Main Layout (Left: Graph / Right: Control Panel)
        # -----------------------------------------------------
        layout = QHBoxLayout()
        
        # [Left] Graph Area
        left_layout = QVBoxLayout()
        self.figure, self.ax = plt.subplots()
        self.canvas = FigureCanvas(self.figure)
        left_layout.addWidget(self.canvas)
        
        # Connect mouse click event (Click to add/analyze peak)
        self.canvas.mpl_connect('button_press_event', self.on_graph_click)
        
        # Help Label
        self.help_label = QLabel("💡 Tip: Click near a peak on the graph to automatically snap to the exact pixel.")
        self.help_label.setStyleSheet("color: #666; font-size: 11px;")
        left_layout.addWidget(self.help_label)
        layout.addLayout(left_layout, stretch=3)
        
        # [Right] Control Panel
        right_layout = QVBoxLayout()
        
        # 1. Load Lamp Data Button
        btn_load = QPushButton("1. Load Lamp Spectrum (.csv/.dat)")
        btn_load.clicked.connect(self.load_spectrum)
        right_layout.addWidget(btn_load)
        
        # 2. Auto Suggest Peaks Button
        btn_find = QPushButton("2. Auto Suggest Peaks (Prominent)")
        btn_find.clicked.connect(self.find_peaks_auto)
        right_layout.addWidget(btn_find)
        
        # Peak Table Setup
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Pixel Index", "True Wavelength (nm)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        right_layout.addWidget(self.table)
        
        # Delete Table Row Button
        btn_del = QPushButton("❌ Delete Selected Peak (or Press 'Del')")
        btn_del.clicked.connect(self.delete_selected_row)
        btn_del.setStyleSheet("color: #cc0000;")
        right_layout.addWidget(btn_del)
        
        # 3. Fitting Button
        btn_fit = QPushButton("3. Fit & Check R²")
        btn_fit.clicked.connect(self.fit_calibration)
        right_layout.addWidget(btn_fit)
        
        btn_save_fwhm = QPushButton("💾 Save FWHM & Sigma Records")
        btn_save_fwhm.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        btn_save_fwhm.clicked.connect(self.save_fwhm_data)
        right_layout.addWidget(btn_save_fwhm)

        # 4. Save & Apply Button
        btn_apply = QPushButton("4. Save & Apply to Main")
        btn_apply.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; height: 40px;")
        btn_apply.clicked.connect(self.save_and_apply)
        right_layout.addWidget(btn_apply)
        
        layout.addLayout(right_layout, stretch=1)
        self.setLayout(layout)

    # ---------------------------------------------------------
    # Interaction: Precise Peak Snapping & FWHM Calculation
    # ---------------------------------------------------------
    def on_graph_click(self, event):
        # 1. Ignore clicks outside the graph area
        if event.inaxes is None or event.xdata is None: 
            return

        # Raw rounded x-coordinate from the mouse click
        raw_click_px = int(round(event.xdata))

        # 2. Fetch actual Y data currently drawn on the graph
        lines = event.inaxes.get_lines()
        if not lines: 
            return
        actual_y_data = lines[0].get_ydata()

        # 🌟 Auto-snap to the highest local peak (magnetic effect)
        search_window = 10  # Search ±10 pixels around the click
        start_idx = max(0, raw_click_px - search_window)
        end_idx = min(len(actual_y_data), raw_click_px + search_window + 1)
        
        # 1. Find the local maximum integer pixel first
        local_max_idx = np.argmax(actual_y_data[start_idx:end_idx])
        int_snapped_px = start_idx + local_max_idx
        
        # 2. Refine to sub-pixel accuracy using Gaussian Fit
        snapped_px = self.get_subpixel_peak(int_snapped_px, actual_y_data)

        # =========================================================
        # 🟢 [Left Click] (event.button == 1): Add peak to table (Sorted)
        # =========================================================
        if event.button == 1:
            if hasattr(self, 'table'):
                data_list = []
                for row in range(self.table.rowCount()):
                    item_px = self.table.item(row, 0)
                    item_wave = self.table.item(row, 1)
                    if item_px:
                        try:
                            px_val = float(item_px.text())
                            wv_val = item_wave.text() if item_wave else ""
                            data_list.append((px_val, wv_val))
                        except ValueError:
                            pass
                
                data_list.append((round(snapped_px, 3), ""))
                
                # 🌟 3. Sort ascending by pixel number
                data_list.sort(key=lambda x: x[0])
                
                # 4. Clear table and refill with sorted data
                self.table.setSortingEnabled(False)
                self.table.setRowCount(0)
                
                for idx, (px, wv) in enumerate(data_list):
                    self.table.insertRow(idx)
                    
                    item_px_new = QTableWidgetItem(str(px))
                    item_px_new.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(idx, 0, item_px_new)
                    
                    item_wave_new = QTableWidgetItem(wv)
                    item_wave_new.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(idx, 1, item_wave_new)
                
                # 5. Redraw graph markers
                self.refresh_graph_markers()
                
                msg = f"✅ [Left Click] Peak registered: {snapped_px} px"
                if hasattr(self, 'help_label'):
                    self.help_label.setText(msg)
                    self.help_label.setStyleSheet("color: #2E7D32; font-weight: bold; font-size: 13px;")

        # =========================================================
        # 🔵 [Right Click] (event.button == 3): Calculate & Preview FWHM
        # =========================================================
        elif event.button == 3:
            current_wave = getattr(self, 'wavelengths', getattr(self, 'wave_data', None))
            fwhm_px, fwhm_nm = self.calculate_fwhm(snapped_px, actual_y_data, current_wave)

            if fwhm_nm is not None:
                msg = f"🔍 [Right Click] 📍 Pixel: {snapped_px} | 📏 FWHM: {fwhm_nm:.3f} nm ({fwhm_px:.1f} px)"
                self.fwhm_records[round(snapped_px, 3)] = {"fwhm_nm": fwhm_nm, "fwhm_px": fwhm_px}
            elif fwhm_px is not None:
                msg = f"🔍 [Right Click] 📍 Pixel: {snapped_px} | 📏 FWHM: {fwhm_px:.1f} px (nm calculation pending)"
                self.fwhm_records[round(snapped_px, 3)] = {"fwhm_nm": None, "fwhm_px": fwhm_px}
            else:
                msg = f"❌ [Right Click] FWHM Calculation Failed"
                
            print(msg)
            
            if hasattr(self, 'help_label'):
                self.help_label.setText(msg)
                self.help_label.setStyleSheet("color: #1565C0; font-weight: bold; font-size: 13px;")

    # ---------------------------------------------------------
    # UI and Graph Management Utilities
    # ---------------------------------------------------------
    def keyPressEvent(self, event):
        """Detect Delete key press within the table."""
        if event.key() == Qt.Key.Key_Delete and self.table.hasFocus():
            self.delete_selected_row()
        else:
            super().keyPressEvent(event)

    def delete_selected_row(self):
        """Delete selected table row and update markers."""
        current_row = self.table.currentRow()
        if current_row >= 0:
            self.table.removeRow(current_row)
            self.refresh_graph_markers()

    def refresh_graph_markers(self):
        """Refresh X markers on the graph based on table data."""
        if self.spectrum is None: 
            return
        
        # 1. Remove existing markers
        for m in self.peak_markers:
            try:
                m.remove()
            except Exception:
                pass
        self.peak_markers = []
        
        # 2. Re-plot markers at pixels listed in the table
        for row in range(self.table.rowCount()):
            try:
                px = float(self.table.item(row, 0).text())
                y_val = self.spectrum[int(round(px))] 
                m = self.ax.scatter(px, y_val, color='red', marker='x', s=100, zorder=5)
                self.peak_markers.append(m)
            except: 
                pass
        
        self.canvas.draw_idle()

    # ---------------------------------------------------------
    # Data Processing & Fitting Logic
    # ---------------------------------------------------------
    def _gaussian_model(self, x, a, mu, sigma, offset):
        """Gaussian mathematical model for FWHM calculation."""
        return a * np.exp(-((x - mu)**2) / (2 * sigma**2)) + offset

    def get_subpixel_peak(self, peak_pixel, intensities):
        """
        Calculates the exact sub-pixel peak position using Center of Mass (Centroid) 
        and Gaussian fitting. Ensures a float sub-pixel value is always returned.
        """
        try:
            # 1. 수은 램프 등 뾰족한 피크에 맞게 탐색 범위를 ±5 픽셀로 좁힘
            window = 5  
            start = max(0, int(peak_pixel) - window)
            end = min(len(intensities), int(peak_pixel) + window + 1)
            
            x_data = np.arange(start, end)
            y_data = intensities[start:end]
            
            # 2. 베이스라인(배경 노이즈) 제거
            y_bg_removed = y_data - np.min(y_data)
            mass_sum = np.sum(y_bg_removed)
            
            # 3. 1차 계산: 무게중심(Centroid) 공식을 이용한 소수점 중심 찾기
            if mass_sum == 0:
                return float(peak_pixel)
            centroid_x = np.sum(x_data * y_bg_removed) / mass_sum
            
            # 4. 2차 계산: 가우시안 피팅을 위한 초기값 (무게중심 결과를 이용)
            offset_guess = np.min(y_data)
            a_guess = np.max(y_data) - offset_guess
            mu_guess = centroid_x  # 정수 대신 앞서 구한 무게중심을 초기값으로!
            sigma_guess = 1.0      # 뾰족한 피크를 위해 넓이(sigma) 추정치 감소
            
            p0_guess = [a_guess, mu_guess, sigma_guess, offset_guess]
            
            # 5. 최적화 진행 (curve_fit)
            popt, _ = curve_fit(self._gaussian_model, x_data, y_data, p0=p0_guess, maxfev=2000)
            sub_pixel_mu = popt
            
            # 6. 피팅이 너무 이상한 곳으로 튀었다면, 안전하게 무게중심 값 반환
            if abs(sub_pixel_mu - peak_pixel) > window:
                return centroid_x
                
            return sub_pixel_mu
            
        except Exception as e:
            # 가우시안 피팅 실패 시, 기존처럼 정수로 포기하지 않고 무게중심(Centroid) 값을 최종 반환!
            print(f"Gaussian fit failed for pixel {peak_pixel}, using Centroid fallback.")
            try:
                # Fallback to pure Center of Mass
                window = 5
                start = max(0, int(peak_pixel) - window)
                end = min(len(intensities), int(peak_pixel) + window + 1)
                x_data = np.arange(start, end)
                y_bg = intensities[start:end] - np.min(intensities[start:end])
                return np.sum(x_data * y_bg) / np.sum(y_bg)
            except:
                return float(peak_pixel)
    
    def calculate_fwhm(self, peak_pixel, intensities, current_wavelengths=None):
        """Extract data around the peak, apply Gaussian fit, and calculate FWHM."""
        try:
            # 1. Extract data around the clicked peak (±15 pixels)
            window = 15
            start = max(0, int(peak_pixel) - window)
            end = min(len(intensities), int(peak_pixel) + window + 1)
            
            x_data = np.arange(start, end)
            y_data = intensities[start:end]
            
            # 2. Set initial estimates
            offset_guess = np.min(y_data)
            a_guess = np.max(y_data) - offset_guess
            mu_guess = peak_pixel
            sigma_guess = 2.0
            
            # 3. Curve Fitting
            p0_guess = [a_guess, mu_guess, sigma_guess, offset_guess]
            popt, _ = curve_fit(self._gaussian_model, x_data, y_data, p0=p0_guess)
            a, mu, sigma, offset = popt
            
            # 4. Calculate FWHM (2.355 * sigma)
            fwhm_pixels = 2.3548 * abs(sigma)
            
            # 5. Convert to nm if wavelength calibration data is available
            fwhm_nm = None
            if current_wavelengths is not None and len(current_wavelengths) > end:
                dispersion = (current_wavelengths[end-1] - current_wavelengths[start]) / (end - 1 - start)
                fwhm_nm = fwhm_pixels * dispersion
                
            return fwhm_pixels, fwhm_nm
            
        except Exception as e:
            print(f"FWHM calculation failed (noisy data or non-peak): {e}")
            return None, None

    def load_spectrum(self):
        """Load calibration spectrum dynamically using a robust header mapping for LightField."""
        filename, _ = QFileDialog.getOpenFileName(self, "Open Lamp Spectrum", "", "Data Files (*.dat *.txt *.csv)")
        if not filename: 
            return
            
        try:
            # 1. 파일 확장자에 따른 데이터 로딩
            if filename.lower().endswith('.csv'):
                try:
                    df = pd.read_csv(filename, on_bad_lines='skip')
                except TypeError:
                    df = pd.read_csv(filename, error_bad_lines=False)
            else:
                try:
                    df = pd.read_csv(filename, comment='#', sep=r'\s+', engine='python', on_bad_lines='skip')
                except TypeError:
                    df = pd.read_csv(filename, comment='#', sep=r'\s+', engine='python', error_bad_lines=False)

            # 2. 🌟 LightField 및 범용 헤더 매핑 사전 (Alias Dictionary)
            # 약자, 풀네임 등을 모두 표준화된 키워드로 연결합니다.
            header_aliases = {
                # Y축 (Intensity)
                'i': 'intensity', 'intensity': 'intensity', 'counts': 'intensity',
                # X축 (Wavelength or Pixel/Column)
                'w': 'wavelength', 'wavelength': 'wavelength',
                'x': 'column', 'column': 'column', 'pixel': 'column',
                # 메타데이터 및 그룹화용
                'f': 'frame', 'frame': 'frame',
                'y': 'row', 'row': 'row',
                'r': 'roi', 'roi': 'roi',
                'ests': 'ests', 'exposurestarttimestamp': 'ests',
                'eets': 'eets', 'exposureendtimestamp': 'eets',
                'ftn': 'ftn', 'frametrackingnumber': 'ftn',
                'gtw': 'gtw', 'gatetrackingdelay': 'gtw',
                'mtp': 'mtp', 'modulationtrackingphase': 'mtp'
            }

            # 3. 데이터프레임 헤더 전처리 (대소문자 무시, 공백 및 언더바 제거)
            original_cols = df.columns.tolist()
            clean_cols = []
            for col in original_cols:
                # "Exposure Start Time Stamp" -> "exposurestarttimestamp" 형태로 변환
                raw_str = str(col).strip().lower().replace(" ", "").replace("_", "")
                # 사전에 매핑된 표준 이름이 있으면 가져오고, 없으면 전처리된 이름 그대로 사용
                clean_cols.append(header_aliases.get(raw_str, raw_str))
            
            df.columns = clean_cols

            # 4. 표준화된 헤더 이름을 기반으로 X축, Y축 데이터 추출
            x_col = None
            if 'wavelength' in clean_cols:
                x_col = 'wavelength'
            elif 'column' in clean_cols:
                x_col = 'column'

            y_col = 'intensity' if 'intensity' in clean_cols else None

            # 5. 데이터 결정 및 할당
            if x_col and y_col:
                # Frame이나 Row가 여러 개 저장된 데이터일 경우 X축 기준으로 평균을 냅니다.
                avg_spec = df.groupby(x_col)[y_col].mean()
                self.spectrum = avg_spec.values
                self.pixels = avg_spec.index.values
            elif y_col:
                # X축 정보가 없고 Intensity만 있는 경우
                self.spectrum = df[y_col].values
                self.pixels = np.arange(len(self.spectrum))
            else:
                # 💡 안전망: 매핑 사전에 없는 완전히 낯선 형식일 경우 가장 마지막 열 강제 사용
                print(f"Warning: Expected headers not found. Found columns: {original_cols}. Using the last column.")
                self.spectrum = df.iloc[:, -1].values
                if x_col:
                    self.pixels = df[x_col].values
                else:
                    self.pixels = np.arange(len(self.spectrum))

            # 6. 그래프 업데이트
            self.ax.clear()
            self.ax.plot(self.pixels, self.spectrum, 'k-', alpha=0.7, label='Lamp Spectrum')
            
            # Wavelength 값이 있으면 X축 라벨을 변경해줍니다.
            if x_col == 'wavelength':
                self.ax.set_xlabel('Wavelength (nm)')
            else:
                self.ax.set_xlabel('Pixel Index')
                
            self.ax.set_ylabel('Intensity')
            self.ax.legend()
            self.canvas.draw()
            self.table.setRowCount(0)
            
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load file: {e}")

    def find_peaks_auto(self):
        """Automatically find prominent peaks and add them to the table."""
        if self.spectrum is None: 
            return
        # Extract peaks with top 10% prominence
        peaks, _ = find_peaks(self.spectrum, prominence=np.max(self.spectrum) * 0.1)
        self.table.setRowCount(0)
        
        for p in peaks:
            # Refine the automated integer peak to sub-pixel precision
            sub_px = self.get_subpixel_peak(p, self.spectrum)
            self.add_row(pixel_val=round(sub_px, 3))
        self.refresh_graph_markers()

    def add_row(self, pixel_val=""):
        """Add an empty row to the table."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(pixel_val)))
        self.table.setItem(row, 1, QTableWidgetItem(""))
        self.table.selectRow(row)

    def fit_calibration(self):
        """Perform 2nd-order polynomial fitting based on input Pixel-Wavelength pairs."""
        pixel_list = []
        wavelength_list = []
        
        # 1. Extract and validate table data
        for row in range(self.table.rowCount()):
            item_px = self.table.item(row, 0)
            item_wave = self.table.item(row, 1)
            
            if item_px and item_wave:
                txt_px = item_px.text().strip()
                txt_wave = item_wave.text().strip()
                
                if not txt_px or not txt_wave:
                    continue
                    
                try:
                    val_px = float(txt_px)
                    val_wave = float(txt_wave)
                    pixel_list.append(val_px)
                    wavelength_list.append(val_wave)
                except ValueError:
                    continue
                    
        # 2. Check for minimum required data points
        if len(pixel_list) < 3:
            QMessageBox.warning(self, "Insufficient Data", "Please input at least 3 (Pixel, Wavelength) pairs for accurate 2nd-order polynomial fitting!")
            return
            
        # 3. Polynomial Fitting (Degree 2)
        self.poly_coeffs = np.polyfit(pixel_list, wavelength_list, 2)

        # 4. Calculate R² (Coefficient of Determination) Accuracy
        fitted_waves = np.polyval(self.poly_coeffs, pixel_list)
        y_mean = np.mean(wavelength_list)
        ss_tot = np.sum((wavelength_list - y_mean)**2)
        ss_res = np.sum((wavelength_list - fitted_waves)**2)
        r_squared = 1 - (ss_res / ss_tot)
        
        # 5. Generate wavelengths for the full pixel range
        total_pixels = len(self.spectrum) if hasattr(self, 'spectrum') and self.spectrum is not None else 2048
        self.wavelengths = np.polyval(self.poly_coeffs, np.arange(total_pixels))
        
        if not hasattr(self, 'fwhm_records'):
            self.fwhm_records = {}
            
        self.fwhm_records.clear()  # 이전에 남아있던 찌꺼기 데이터 초기화
        
        if hasattr(self, 'spectrum') and self.spectrum is not None:
            # pixel_list는 사용자가 테이블에 등록해둔 픽셀들입니다.
            for px in pixel_list:  
                fwhm_px, fwhm_nm = self.calculate_fwhm(px, self.spectrum, self.wavelengths)
                if fwhm_px is not None:
                    # 딕셔너리에 자동으로 쏙쏙 저장합니다.
                    self.fwhm_records[round(px, 3)] = {"fwhm_nm": fwhm_nm, "fwhm_px": fwhm_px}

        # 상태 메시지에 평균 FWHM도 바로 보여주기 위한 계산
        valid_fwhms = [data['fwhm_nm'] for data in self.fwhm_records.values() if data.get('fwhm_nm') is not None]
        avg_fwhm_str = ""
        if valid_fwhms:
            avg_fwhm_str = f" | Avg FWHM: {sum(valid_fwhms)/len(valid_fwhms):.3f} nm"

        # 6. Visualize Fitting Results
        poly_func = np.poly1d(self.poly_coeffs)
        
        # 7. Output Status Message
        msg = f"✅ Fitting Complete! R² = {r_squared:.5f} | Eq: {self.poly_coeffs[0]:.2e}x² + {self.poly_coeffs[1]:.4f}x + {self.poly_coeffs[2]:.2f}"
        print(msg)
        if hasattr(self, 'help_label'):
            self.help_label.setText(msg)
            self.help_label.setStyleSheet("color: #1565C0; font-weight: bold; font-size: 13px;")

        # 8. 피팅 결과 팝업창 띄우기
        self.show_fit_result_popup(pixel_list, wavelength_list, poly_func, r_squared)

    def show_fit_result_popup(self, px, wave, func, r2):
        """Display fitting results in a separate popup window."""
        fit_win = QDialog(self)
        fit_win.setWindowTitle(f"Fit Result (R² = {r2:.6f})")
        fit_win.setMinimumSize(500, 400)
        
        v_lay = QVBoxLayout(fit_win)
        fig, ax = plt.subplots()
        canvas = FigureCanvas(fig)
        v_lay.addWidget(canvas)
        
        ax.plot(px, wave, 'ro', label='Data')
        full_px = np.linspace(min(px) - 50, max(px) + 50, 100)
        ax.plot(full_px, func(full_px), 'b-', label=f'Fit (R²={r2:.6f})')
        ax.set_xlabel("Pixel")
        ax.set_ylabel("Wavelength (nm)")
        ax.legend()
        ax.grid(True)
        
        btn_close = QPushButton("OK")
        btn_close.clicked.connect(fit_win.accept)
        v_lay.addWidget(btn_close)
        
        canvas.draw()
        fit_win.exec()

    def save_and_apply(self):
        """Save the calculated wavelengths and apply them to the main window (Emit Signal)."""
        # 1. Data Validation
        if not hasattr(self, 'wavelengths') or self.wavelengths is None:
            QMessageBox.warning(self, "Warning", "Please click '3. Fit & Check R²' to complete the calculation first.")
            return

        # 2. Smart Filename Generation (Date + Lamp + Wavelength Range)
        date_str = datetime.datetime.now().strftime("%Y%m%d")
        w_min = int(round(np.min(self.wavelengths)))
        w_max = int(round(np.max(self.wavelengths)))
        range_str = f"{w_min}-{w_max}nm"
        suggested_name = f"Calib_{date_str}_Hg_{range_str}_Poly2.txt"

        # 3. Specify Save Path
        filters = "Text Files (*.txt);;Data Files (*.dat);;CSV Files (*.csv)"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save & Apply Calibration", suggested_name, filters
        )

        if save_path:
            # Generate Metadata Header including FWHM
            avg_fwhm_str = "No FWHM recorded"
            
            # fwhm_records 바구니가 존재하고 비어있지 않다면
            if hasattr(self, 'fwhm_records') and self.fwhm_records:
                # 에러 없이 nm 단위로 잘 계산된 FWHM 값들만 리스트로 뽑아냅니다
                valid_fwhms = [data['fwhm_nm'] for data in self.fwhm_records.values() if data.get('fwhm_nm') is not None]
                
                # 유효한 값이 1개라도 있으면 평균을 계산합니다
                if valid_fwhms:
                    avg_fwhm = sum(valid_fwhms) / len(valid_fwhms)
                    avg_fwhm_str = f"Average FWHM: {avg_fwhm:.3f} nm (calculated from {len(valid_fwhms)} peaks)"

            header_msg = f"BBCEAS Wavelength Calibration Result\nGenerated: {date_str}\nInfo: {avg_fwhm_str}"
            # =========================================================

            try:
                # 4. Write to File
                if save_path.endswith('.csv'):
                    np.savetxt(save_path, self.wavelengths, fmt='%.6f', delimiter=',', header=header_msg, encoding='utf-8')
                else:
                    np.savetxt(save_path, self.wavelengths, fmt='%.6f', header=header_msg, encoding='utf-8')

                # 5. Transmit signal to Main App
                self.calibration_finished.emit(self.wavelengths)
                
                # 6. Completion Message & Close
                QMessageBox.information(
                    self, "Success", 
                    f"Successfully saved and applied to the main engine!\nFilename: {os.path.basename(save_path)}"
                )
                self.accept()
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error occurred while saving file:\n{e}")
    def save_fwhm_data(self):
        """Export accumulated FWHM and Sigma records to a text file."""
        if not hasattr(self, 'fwhm_records') or not self.fwhm_records:
            QMessageBox.warning(self, "No Data", "저장할 FWHM 데이터가 없습니다.\n먼저 그래프의 피크를 우클릭하여 FWHM을 계산해 주세요.")
            return

        # 자동 파일명 생성
        date_str = datetime.datetime.now().strftime("%Y%m%d")
        suggested_name = f"FWHM_Analysis_{date_str}.txt"

        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save FWHM & Sigma Data", suggested_name, "Text Files (*.txt);;CSV Files (*.csv)"
        )

        if save_path:
            try:
                with open(save_path, 'w', encoding='utf-8') as f:
                    # 헤더 (설명창) 작성
                    f.write("# BBCEAS FWHM & Sigma Analysis Records\n")
                    f.write(f"# Generated: {date_str}\n")
                    f.write("# Formula: abs(Sigma) = FWHM / 2.3548\n")
                    f.write("-" * 60 + "\n")
                    
                    # 엑셀/오리진(Origin)에서 붙여넣기 좋게 Tab으로 열 구분
                    if save_path.endswith('.csv'):
                        f.write("Pixel,FWHM(nm),FWHM(px),abs_Sigma(nm),abs_Sigma(px)\n")
                    else:
                        f.write("Pixel\tFWHM(nm)\tFWHM(px)\tabs_Sigma(nm)\tabs_Sigma(px)\n")
                    
                    # 픽셀 번호가 작은 순서대로(왼쪽에서 오른쪽) 정렬하여 기록
                    for px in sorted(self.fwhm_records.keys()):
                        data = self.fwhm_records[px]
                        
                        # FWHM 값 가져오기
                        f_nm = data['fwhm_nm']
                        f_px = data['fwhm_px']
                        
                        # Sigma 값 역산하기 (FWHM = 2.3548 * sigma)
                        s_nm = f_nm / 2.3548 if f_nm is not None else None
                        s_px = f_px / 2.3548 if f_px is not None else None

                        # 빈 값이면 N/A 처리, 있으면 소수점 4자리까지 출력
                        str_f_nm = f"{f_nm:.4f}" if f_nm is not None else "N/A"
                        str_f_px = f"{f_px:.4f}" if f_px is not None else "N/A"
                        str_s_nm = f"{s_nm:.4f}" if s_nm is not None else "N/A"
                        str_s_px = f"{s_px:.4f}" if s_px is not None else "N/A"
                        
                        if save_path.endswith('.csv'):
                            f.write(f"{px},{str_f_nm},{str_f_px},{str_s_nm},{str_s_px}\n")
                        else:
                            f.write(f"{px}\t{str_f_nm}\t{str_f_px}\t{str_s_nm}\t{str_s_px}\n")

                QMessageBox.information(self, "Success", f"FWHM 데이터가 성공적으로 저장되었습니다!\n파일명: {os.path.basename(save_path)}")
            
            except Exception as e:
                QMessageBox.critical(self, "Error", f"파일 저장 중 오류가 발생했습니다:\n{e}")

class CalibrationScanner(QDialog):
    """
    Smart scanner dialog that iterates through a specified shift range 
    to find the optimal wavelength shift by minimizing the RMS error.
    """
    apply_result = pyqtSignal(float)
    
    def __init__(self, engine, y_data, pixel_min, pixel_max, poly_order):
        super().__init__()
        self.setWindowTitle(f"🔍 Shift Scanner (Poly Order: {poly_order})")
        self.resize(800, 600)
        
        # --- Initialize Analysis Data ---
        self.engine = engine
        self.y_data = y_data
        self.pixel_min = pixel_min
        self.pixel_max = pixel_max
        self.poly_order = poly_order
        
        # Result Storage
        self.best_shift = 0.0
        self.min_rms = 0.0
        
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # --- Top: Control Panel ---
        h_layout = QHBoxLayout()
        
        h_layout.addWidget(QLabel("Scan Range (±):"))
        self.spin_range = QSpinBox()
        self.spin_range.setRange(1, 500)
        self.spin_range.setValue(20)
        h_layout.addWidget(self.spin_range)
        
        h_layout.addWidget(QLabel("Step:"))
        self.spin_step = QDoubleSpinBox()
        self.spin_step.setRange(0.01, 10.0)
        self.spin_step.setSingleStep(0.1)
        self.spin_step.setValue(0.5)
        h_layout.addWidget(self.spin_step)
        
        self.btn_scan = QPushButton("Start Scan")
        self.btn_scan.clicked.connect(self.run_scan)
        h_layout.addWidget(self.btn_scan)
        
        layout.addLayout(h_layout)
        
        # --- Center: Scan Result Graph Area ---
        self.fig = Figure(figsize=(6, 4))
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)
        layout.addWidget(self.canvas)
        
        # --- Bottom: Status Label and Apply Button ---
        self.lbl_res = QLabel("Ready...")
        self.lbl_res.setStyleSheet("font-weight: bold; color: #333;")
        layout.addWidget(self.lbl_res)
        
        self.btn_apply = QPushButton("Apply Found Shift")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; height: 35px;")
        self.btn_apply.clicked.connect(self.apply_and_close)
        layout.addWidget(self.btn_apply)
        
        # Attach the previously optimized NavigationHelper
        self.nav = NavigationHelper(self.ax, mode='pan_left')
        
    def run_scan(self):
        """Explore the defined range to find the shift with the minimum RMS error."""
        scan_range = self.spin_range.value()
        step = self.spin_step.value()
        shifts = np.arange(-scan_range, scan_range + step / 100, step)
        rms_list = []
        
        # Extract the data subset and X-axis indices for fitting
        y_subset = self.y_data[self.pixel_min:self.pixel_max]
        x_subset = np.arange(self.pixel_min, self.pixel_max)
        squeeze = 1.0  # Squeeze is fixed to 1.0 since the scanner only looks for Shift
        
        # Update UI state (Lock buttons and prevent freezing)
        self.btn_scan.setEnabled(False)
        self.lbl_res.setText("Scanning... Please wait.")
        self.lbl_res.setStyleSheet("font-weight: bold; color: #E65100;")
        QApplication.processEvents() # Prevent UI freeze
        
        # 🌟 Scanning Loop (Ultra-fast due to the optimized engine)
        for shift_val in shifts:
            try:
                # 1. Generate Basis Matrix
                A = self.engine.get_basis_matrix(x_subset, shift_val, squeeze, self.poly_order)
                
                # 2. Linear Least Squares Calculation
                # Replaced unused variables with *_ for cleaner memory handling
                coeffs, *_ = np.linalg.lstsq(A, y_subset, rcond=None)
                
                # 3. Generate Model Spectrum and Calculate RMS Error
                y_fit = A @ coeffs
                rms = np.sqrt(np.mean((y_subset - y_fit)**2))
                rms_list.append(rms)
            except Exception:
                rms_list.append(np.nan)
                
        # --- Visualization: Draw the U-shaped Error Curve ---
        self.ax.clear()
        self.ax.plot(shifts, rms_list, 'b.-', label='RMS Error Curve')
        self.ax.set_xlabel("Shift (Pixels or nm)")
        self.ax.set_ylabel("RMS Error")
        self.ax.set_yscale('log')
        self.ax.grid(True, linestyle='--', alpha=0.7)
        
        # Find the minimum RMS point (Optimal Shift)
        min_idx = np.nanargmin(rms_list)
        self.best_shift = shifts[min_idx]
        self.min_rms = rms_list[min_idx]
        
        # Mark the optimal point with a vertical line on the graph
        self.ax.axvline(self.best_shift, color='r', linestyle='-', linewidth=2, label=f'Best Shift: {self.best_shift:.2f}')
        self.ax.legend()
        self.canvas.draw()
        
        # Restore UI state and display results
        self.lbl_res.setText(f"✅ Found Optimal Shift: {self.best_shift:.2f} (RMS: {self.min_rms:.2e})")
        self.lbl_res.setStyleSheet("font-weight: bold; color: #2E7D32;")
        
        self.btn_apply.setEnabled(True)
        self.btn_scan.setEnabled(True)
        
    def apply_and_close(self):
        """Send the optimal shift value back to the main window and close the dialog."""
        self.apply_result.emit(self.best_shift)
        self.accept()

class RangeSelectorDialog(QDialog):
    """
    Dialog for visually selecting the fitting range by dragging over the data.
    Supports overlaying reference spectra for precise visual alignment.
    """
    apply_range = pyqtSignal(int, int)

    def __init__(self, data_path, pixel_min, pixel_max, engine):
        super().__init__()
        self.setWindowTitle("🔍 Fit Range Selector")
        self.resize(900, 600)
        
        # --- Initialize Analysis Data & State ---
        self.engine = engine
        self.data_path = data_path
        self.min_sel = int(pixel_min)
        self.max_sel = int(pixel_max)
        
        self.x = None
        self.y = None
        self.span = None
        
        self.setup_ui()
        self.load_plot()

    def setup_ui(self):
        # Main Vertical Layout
        self.main_layout = QVBoxLayout(self)
        
        # --- 1. Top Control Panel ---
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Overlay Reference:"))
        
        self.combo = QComboBox()
        self.combo.addItems(["None"] + self.engine.gas_list)
        self.combo.currentTextChanged.connect(self.update_ref)
        top_layout.addWidget(self.combo)
        
        top_layout.addStretch(1)
        top_layout.addWidget(QLabel("🖱️ Left: Select Range | Right: Pan | Wheel: Zoom"))
        self.main_layout.addLayout(top_layout)
        
        # --- 2. Center Graph Area ---
        self.fig = Figure(figsize=(8, 5))
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.ax2 = self.ax.twinx()  # Secondary Y-axis for reference overlay
        
        # Attach the optimized NavigationHelper (Right-click pan mode)
        self.nav = NavigationHelper(self.ax, mode='pan_right')
        self.main_layout.addWidget(self.canvas) 
        
        # --- 3. Bottom Button Area ---
        btns_layout = QHBoxLayout()
        self.b_apply = QPushButton("Apply Range")
        self.b_apply.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; height: 35px;")
        self.b_apply.clicked.connect(self.emit_apply)
        
        self.b_close = QPushButton("Close")
        self.b_close.clicked.connect(self.reject)
        
        btns_layout.addWidget(self.b_apply)
        btns_layout.addWidget(self.b_close)
        self.main_layout.addLayout(btns_layout)

    def load_plot(self):
        """Loads selected data, plots it, and activates the SpanSelector."""
        try:
            pixel_idx, intensity_raw = DataIO.load_measurement(self.data_path, pixel_min=0)
            
            self.y = intensity_raw
            self.x = pixel_idx
            
            # Plot main measured data
            self.ax.clear()
            self.ax.plot(self.x, self.y, 'k-', alpha=0.5, label='Measured Data')
            self.ax.legend(loc='upper right')
            
            # Activate Range Selector (Semi-transparent yellow box)
            self.span = SpanSelector(
                self.ax, self.on_select, 'horizontal', useblit=True, 
                props=dict(alpha=0.3, facecolor='yellow')
            )
            
            # Update initial reference overlay
            self.update_ref(self.combo.currentText())
            
        except Exception as e:
            print(f"Failed to load plot data: {e}")

    def update_ref(self, name):
        """Draws the selected reference gas spectrum on the secondary Y-axis."""
        self.ax2.clear()
        
        if name in self.engine.interpolators:
            # Fetch the interpolated data for the selected gas from the engine
            y_ref = self.engine.interpolators[name](self.x.astype(float))
            
            self.ax2.plot(self.x, y_ref, 'r--', alpha=0.8, label=f'Ref: {name}')
            
            # Secure margin for Y-axis scale
            ymin, ymax = np.min(y_ref), np.max(y_ref)
            if ymax - ymin > 1e-65: 
                margin = (ymax - ymin) * 0.1
                self.ax2.set_ylim(ymin - margin, ymax + margin)
                
            self.ax2.legend(loc='upper left')
            
        self.canvas.draw()

    def on_select(self, val_min, val_max):
        """Stores the min/max indices of the range dragged via SpanSelector."""
        self.min_sel = int(val_min)
        self.max_sel = int(val_max)

    def emit_apply(self):
        """Sends the selected range to the main program and closes the dialog."""
        self.apply_range.emit(self.min_sel, self.max_sel)
        self.accept()

class MaskDialog(QDialog):
    """
    Smart masking dialog to set unnecessary noise regions of reference spectra to zero,
    thereby improving the accuracy of the fitting process.
    """
    def __init__(self, gas_list):
        super().__init__()
        self.setWindowTitle("✂️ Smart Masking Tool")
        self.resize(400, 250)
        
        # List of gas names currently loaded in the main engine
        self.gas_list = gas_list 
        
        self.setup_ui()
        
    def setup_ui(self):
        # Main vertical layout
        main_layout = QVBoxLayout(self)
        
        # --- 1. Target Reference Selection ---
        layout_ref = QHBoxLayout()
        layout_ref.addWidget(QLabel("Select Reference:"))
        
        self.cb_ref = QComboBox()
        self.cb_ref.addItems(self.gas_list)
        layout_ref.addWidget(self.cb_ref)
        
        main_layout.addLayout(layout_ref)
        
        # --- 2. Masking Method Selection ---
        grp_masking = QGroupBox("Masking Method")
        layout_opt = QVBoxLayout()
        self.bg = QButtonGroup()
        
        # [Option A] Manual Range
        self.rb_manual = QRadioButton("Manual Range (Keep Only)")
        self.rb_manual.setChecked(True)
        self.bg.addButton(self.rb_manual)
        layout_opt.addWidget(self.rb_manual)
        
        layout_manual = QHBoxLayout()
        layout_manual.setContentsMargins(20, 0, 0, 0) # Indentation effect
        layout_manual.addWidget(QLabel("Pixel Range:"))
        
        self.txt_range = QLineEdit("441-450")
        self.txt_range.setPlaceholderText("min-max")
        layout_manual.addWidget(self.txt_range)
        layout_opt.addLayout(layout_manual)
        
        # [Option B] Auto-Cut
        self.rb_auto = QRadioButton("🪄 Auto-Cut (Remove Weak Signal)")
        self.bg.addButton(self.rb_auto)
        layout_opt.addWidget(self.rb_auto)
        
        layout_auto = QHBoxLayout()
        layout_auto.setContentsMargins(20, 0, 0, 0) # Indentation effect
        layout_auto.addWidget(QLabel("Threshold (of Max):"))
        
        self.spin_thresh = QDoubleSpinBox()
        self.spin_thresh.setRange(0.001, 99.0)
        self.spin_thresh.setValue(1.0)
        self.spin_thresh.setSuffix("%")
        layout_auto.addWidget(self.spin_thresh)
        layout_opt.addLayout(layout_auto)
        
        grp_masking.setLayout(layout_opt)
        main_layout.addWidget(grp_masking)
        
        # --- 3. Bottom Buttons (Apply/Cancel) ---
        layout_btns = QHBoxLayout()
        layout_btns.addStretch(1) # Push buttons to the right
        
        b_ok = QPushButton("Apply")
        b_ok.clicked.connect(self.accept)
        layout_btns.addWidget(b_ok)
        
        b_cancel = QPushButton("Cancel")
        b_cancel.clicked.connect(self.reject)
        layout_btns.addWidget(b_cancel)
        
        main_layout.addLayout(layout_btns)

    def get_data(self):
        """Returns the masking options set in the dialog as a dictionary."""
        mode = "manual" if self.rb_manual.isChecked() else "auto"
        return {
            "name": self.cb_ref.currentText(),
            "mode": mode,
            "range": self.txt_range.text(),
            "threshold": self.spin_thresh.value()
        }
       

# =============================================================================
# 5. Reference Management
# =============================================================================
class RefPropertiesDialog(QDialog):
    """
    Dialog to dynamically edit Shift and Squeeze fitting parameters 
    (Free, Limit, Fix, Link) for each loaded reference gas.
    """
    def __init__(self, parent, gas_list, current_props):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Edit Reference Properties")
        self.resize(800, 350)
        layout = QVBoxLayout(self)
        
        self.table = QTableWidget(len(gas_list), 5)
        self.table.setHorizontalHeaderLabels(["Gas Name", "Shift Mode", "Shift Params", "Squeeze Mode", "Squeeze Params"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        # Synchronized variable name with UniversalEngine
        self.gas_list = gas_list
        
        # Dictionary to store widgets for extracting values later
        self.param_widgets = {} 
        
        for i, gas in enumerate(self.gas_list):
            self.table.setItem(i, 0, QTableWidgetItem(gas))
            
            # Default DOASIS style properties if none exist
            props = current_props.get(gas, {"sh_mode": "Limit", "sh_val": "-0.5, 0.5", "sq_mode": "Fix", "sq_val": "1.0"})
            
            # 🌟 Dynamic UI Generator (Handles page switching based on selected mode)
            def create_dynamic_cell(mode, val):
                stack = QStackedWidget()
                
                # Page 0: Free Mode (Read-only, placeholder text)
                w_free = QLineEdit("No Limit (Free Exploration)")
                w_free.setReadOnly(True)
                w_free.setStyleSheet("background-color: #e0e0e0; color: #555;") # Grayed out effect
                stack.addWidget(w_free)
                
                # Page 1: Limit Mode (Text input for min, max bounds)
                w_limit = QLineEdit("-0.5, 0.5" if mode not in ["Limit", "Free"] else str(val))
                stack.addWidget(w_limit)
                
                # Page 2: Fix Mode (Text input for a fixed value)
                w_fix = QLineEdit("0.0" if mode != "Fix" else str(val))
                stack.addWidget(w_fix)
                
                # Page 3: Link Mode (Combobox to link to another gas)
                w_link = QComboBox()
                linkable_gases = [g for g in self.gas_list if g != gas] # Exclude self
                w_link.addItems(linkable_gases)
                if mode == "Link" and str(val) in linkable_gases:
                    w_link.setCurrentText(str(val))
                stack.addWidget(w_link)
                
                # Set initial visible page based on the current mode
                if mode == "Free": stack.setCurrentIndex(0)
                elif mode == "Limit": stack.setCurrentIndex(1)
                elif mode == "Fix": stack.setCurrentIndex(2)
                elif mode == "Link": stack.setCurrentIndex(3)
                else: stack.setCurrentIndex(1) # Default to Limit
                
                return stack, w_free, w_limit, w_fix, w_link

            # --- Shift Configuration ---
            cmb_sh = QComboBox()
            cmb_sh.addItems(["Free", "Limit", "Fix", "Link"]) 
            cmb_sh.setCurrentText(props.get("sh_mode", "Limit"))
            stack_sh, sh_fre, sh_lim, sh_fix, sh_lnk = create_dynamic_cell(props.get("sh_mode", "Limit"), props.get("sh_val", ""))
            
            # Automatically switch the stacked widget page when combo box changes
            cmb_sh.currentIndexChanged.connect(stack_sh.setCurrentIndex)
            
            self.table.setCellWidget(i, 1, cmb_sh)
            self.table.setCellWidget(i, 2, stack_sh)
            
            # --- Squeeze Configuration ---
            cmb_sq = QComboBox()
            cmb_sq.addItems(["Free", "Limit", "Fix", "Link"]) 
            cmb_sq.setCurrentText(props.get("sq_mode", "Fix"))
            stack_sq, sq_fre, sq_lim, sq_fix, sq_lnk = create_dynamic_cell(props.get("sq_mode", "Fix"), props.get("sq_val", ""))
            
            cmb_sq.currentIndexChanged.connect(stack_sq.setCurrentIndex)
            
            self.table.setCellWidget(i, 3, cmb_sq)
            self.table.setCellWidget(i, 4, stack_sq)
            
            # Save widget references for data extraction
            self.param_widgets[gas] = {
                "sh_cmb": cmb_sh, "sh_lim": sh_lim, "sh_fix": sh_fix, "sh_lnk": sh_lnk,
                "sq_cmb": cmb_sq, "sq_lim": sq_lim, "sq_fix": sq_fix, "sq_lnk": sq_lnk
            }
        
        layout.addWidget(self.table)
        
        # OK and Cancel buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
    def get_properties(self):
        """Extracts the configured properties from the table widgets into a dictionary."""
        props = {}
        for gas in self.gas_list:
            w = self.param_widgets[gas]
            
            # Extract Shift properties
            sh_mode = w["sh_cmb"].currentText()
            if sh_mode == "Free": sh_val = "Free" # Ignore text field if Free
            elif sh_mode == "Limit": sh_val = w["sh_lim"].text()
            elif sh_mode == "Fix": sh_val = w["sh_fix"].text()
            else: sh_val = w["sh_lnk"].currentText() 
            
            # Extract Squeeze properties
            sq_mode = w["sq_cmb"].currentText()
            if sq_mode == "Free": sq_val = "Free" 
            elif sq_mode == "Limit": sq_val = w["sq_lim"].text()
            elif sq_mode == "Fix": sq_val = w["sq_fix"].text()
            else: sq_val = w["sq_lnk"].currentText() 
            
            props[gas] = {
                "sh_mode": sh_mode, "sh_val": sh_val,
                "sq_mode": sq_mode, "sq_val": sq_val
            }
        return props
       
class ReferenceGeneratorDialog(QDialog):
    """
    Ultimate Reference Generator Dialog.
    Incorporates advanced deconvolution logic to accurately simulate
    Instrument Line Shape (ILS) based on literature FWHM values.
    """
    reference_saved = pyqtSignal(str, str)

    def __init__(self, parent=None, current_wavelengths=None):
        super().__init__(parent)
        self.setWindowTitle("✂️ Ultimate Reference Generator (with Advanced Deconvolution)")
        self.resize(1150, 800)
        
        self.raw_wave = None
        self.raw_data = None
        self.target_wavelengths = current_wavelengths
        self.lamp_intensity = None
        self.final_ready_data = None
        
        self.gas_name = "Unknown"
        self.gen_info = "Generated"
        self.suggested_filename = "Ref_Ultimate.dat"
        
        self.init_ui()

        if self.target_wavelengths is not None:
            self.lbl_wave_info.setText(f"✅ Status: Synced with Main ({len(self.target_wavelengths)} px)")
            self.lbl_wave_info.setStyleSheet("color: #2E7D32; font-weight: bold;")

    def init_ui(self):
        layout = QHBoxLayout(self)
        
        # [Left] Graph Area
        left_layout = QVBoxLayout()
        self.fig, self.ax = plt.subplots(2, 1, figsize=(6, 8))
        self.canvas = FigureCanvas(self.fig)
        left_layout.addWidget(self.canvas)
        layout.addLayout(left_layout, stretch=2)
        
        # [Right] Control Panel Area
        right_layout = QVBoxLayout()
        
        # --- 1. Load/Generate Raw High-Res Reference ---
        grp_raw = QGroupBox("1. Load/Generate Raw High-Res Reference")
        lay_raw = QVBoxLayout()
        
        self.btn_load_raw = QPushButton("📂 Load Raw File (.txt)")
        self.btn_load_raw.clicked.connect(self.load_raw_reference)
        lay_raw.addWidget(self.btn_load_raw)
        
        # Literature FWHM Input (LabVIEW logic equivalent)
        lay_lit_fwhm = QHBoxLayout()
        lay_lit_fwhm.addWidget(QLabel("📖 Literature FWHM (nm):"))
        self.spin_lit_fwhm = QDoubleSpinBox()
        self.spin_lit_fwhm.setRange(0.0, 5.0)
        self.spin_lit_fwhm.setDecimals(5)
        self.spin_lit_fwhm.setValue(0.0) # Default 0 (Assumes infinite resolution)
        self.spin_lit_fwhm.setToolTip("Enter the resolution of the original data from literature or DB (e.g., NO2 Vandaele = 0.01156)")
        lay_lit_fwhm.addWidget(self.spin_lit_fwhm)
        lay_raw.addLayout(lay_lit_fwhm)
        
        # HITRAN API Parameters
        lay_hitran = QHBoxLayout()
        lay_hitran.addWidget(QLabel("T(K):"))
        self.spin_temp = QDoubleSpinBox(); self.spin_temp.setRange(200.0, 400.0); self.spin_temp.setValue(293.0)
        lay_hitran.addWidget(self.spin_temp)
        lay_hitran.addWidget(QLabel("P(atm):"))
        self.spin_press = QDoubleSpinBox(); self.spin_press.setRange(0.1, 2.0); self.spin_press.setValue(1.0)
        lay_hitran.addWidget(self.spin_press)
        lay_raw.addLayout(lay_hitran)

        lay_hitran_action = QHBoxLayout()
        self.combo_hitran_gas = QComboBox()
        self.combo_hitran_gas.addItems([
            "1: H2O (Water)", "2: CO2 (Carbon Dioxide)", "3: O3 (Ozone)", 
            "4: N2O (Nitrous Oxide)", "6: CH4 (Methane)", "7: O2 (Oxygen)", 
            "10: NO2 (Nitrogen Dioxide)"
        ])
        lay_hitran_action.addWidget(self.combo_hitran_gas)
        
        self.btn_hitran = QPushButton("🌐 Generate from HITRAN")
        self.btn_hitran.setStyleSheet("background-color: #e3f2fd; font-weight: bold;")
        self.btn_hitran.clicked.connect(self.generate_hitran_gas)
        lay_hitran_action.addWidget(self.btn_hitran)
        lay_raw.addLayout(lay_hitran_action)
        
        self.lbl_raw_info = QLabel("Loaded: None")
        self.lbl_raw_info.setStyleSheet("color: blue;")
        lay_raw.addWidget(self.lbl_raw_info)
        grp_raw.setLayout(lay_raw)
        right_layout.addWidget(grp_raw)
        
        # --- 2. Target Instrument Wavelength ---
        grp_wave = QGroupBox("2. Target Instrument Wavelength")
        lay_wave = QVBoxLayout()
        self.btn_load_wave = QPushButton("📂 Load Wavelength Calibration (.txt)")
        self.btn_load_wave.clicked.connect(self.load_target_wavelength)
        status_text = 'Loaded from Main' if self.target_wavelengths is not None else 'Not Loaded'
        self.lbl_wave_info = QLabel(f"Status: {status_text}")
        lay_wave.addWidget(self.btn_load_wave)
        lay_wave.addWidget(self.lbl_wave_info)
        grp_wave.setLayout(lay_wave)
        right_layout.addWidget(grp_wave)
        
        # --- 3. Instrument Line Shape (ILS) ---
        # --- 3. Instrument Line Shape (ILS) Profile ---
        grp_conv = QGroupBox("3. Instrument Line Shape (ILS) Profile")
        lay_conv = QVBoxLayout()
        
        self.btn_load_fwhm = QPushButton("📂 Load FWHM Profile (.txt)")
        self.btn_load_fwhm.clicked.connect(self.load_fwhm_profile)
        self.lbl_fwhm_info = QLabel("Status: Not Loaded")
        self.lbl_fwhm_info.setStyleSheet("color: #d32f2f;")
        
        lay_conv.addWidget(self.btn_load_fwhm)
        lay_conv.addWidget(self.lbl_fwhm_info)
        grp_conv.setLayout(lay_conv)
        right_layout.addWidget(grp_conv)
        
        # 내부 데이터 저장을 위한 변수 초기화 (init 함수 쪽에 넣으셔도 됩니다)
        self.ils_pixels = None
        self.ils_sigmas = None
        
        # --- 4. Generate & Save ---
        self.btn_generate = QPushButton("🪄 Generate Ultimate Reference")
        self.btn_generate.setStyleSheet("background-color: #ff9800; color: white; font-weight: bold; font-size: 14px;")
        self.btn_generate.clicked.connect(self.apply_convolution)
        self.btn_generate.setMinimumHeight(50)
        right_layout.addWidget(self.btn_generate)
        
        self.btn_save = QPushButton("💾 Save & Auto-Register to Main")
        self.btn_save.clicked.connect(self.save_reference)
        self.btn_save.setEnabled(False)
        self.btn_save.setMinimumHeight(40)
        right_layout.addWidget(self.btn_save)
        
        right_layout.addStretch(1)
        layout.addLayout(right_layout, stretch=1)

    # ---------------------------------------------------------
    # Data Loading Methods
    # ---------------------------------------------------------
    def load_raw_reference(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open Raw Ref", "", "Data Files (*.txt *.csv *.dat)")
        if not filename: return
        try:
            wave_nm_ref, intensity_raw = DataIO.load_reference(filename)
            
            if wave_nm_ref is None:
                raise ValueError("No Wavelength data found in the reference file.")
                
            self.raw_wave = wave_nm_ref
            self.raw_data = intensity_raw
            
            base_name = os.path.basename(filename)
            
            self.gas_name = base_name.split('_')[ 0 ]
            
            self.lbl_raw_info.setText(f"Loaded: {base_name} (Gas: {self.gas_name})")
            
            self.ax[ 0 ].clear()
            self.ax[ 0 ].plot(self.raw_wave, self.raw_data, 'k-', alpha=0.5, label='Raw Data')
            self.ax[ 0 ].legend()
            self.canvas.draw()
            
        except Exception as e: 
            QMessageBox.critical(self, "Error", f"Failed to load Raw file:\n{e}")

    def generate_hitran_gas(self):
        try: 
            import hapi
        except ImportError: 
            QMessageBox.critical(self, "Dependency Error", "The 'hapi' library is not installed.")
            return
            
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            T, P = self.spin_temp.value(), self.spin_press.value()
            if self.target_wavelengths is not None:
                w_min, w_max = self.target_wavelengths.min() - 10.0, self.target_wavelengths.max() + 10.0
            else: 
                w_min, w_max = 390.0, 510.0
            
            selected_text = self.combo_hitran_gas.currentText()
            gas_id = int(selected_text.split(':')[0])
            gas_name = selected_text.split(':')[1].split('(')[0].strip()
            table_name = f"{gas_name}_Lines"
            
            hapi.db_begin('hitran_data')
            hapi.fetch(table_name, gas_id, 1, 1e7/w_max, 1e7/w_min)
            nu, coef = hapi.absorptionCoefficient_Voigt(
                SourceTables=table_name, Environment={'p': P, 'T': T}, 
                OmegaStep=0.02, HITRAN_units=False
            )
            
            wave_nm = 1e7 / nu
            sort_idx = np.argsort(wave_nm)
            self.raw_wave = wave_nm[sort_idx]
            self.raw_data = coef[sort_idx]
            
            self.gas_name = f"{gas_name}-HITRAN" 
            self.lbl_raw_info.setText(f"HITRAN {gas_name} Generated")
            
            self.ax[0].clear()
            self.ax[0].plot(self.raw_wave, self.raw_data, 'b-', label=f'HITRAN {gas_name}')
            self.ax[0].legend()
            self.canvas.draw()
        except Exception as e: 
            QMessageBox.critical(self, "Error", f"HITRAN Generation Failed:\n{e}")
        finally: 
            QApplication.restoreOverrideCursor()

    def load_target_wavelength(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open Wavelength", "", "Text Files (*.txt *.csv)")
        if not filename: return
        df = pd.read_csv(filename, header=None)
        self.target_wavelengths = pd.to_numeric(df.iloc[:, 0], errors='coerce').dropna().values
        self.lbl_wave_info.setText(f"Loaded: {os.path.basename(filename)}")

    def load_fwhm_profile(self):
        """Loads the FWHM & Sigma profile generated from the calibration tool."""
        filename, _ = QFileDialog.getOpenFileName(self, "Open FWHM Profile", "", "Text Files (*.txt *.csv)")
        if not filename: return
        
        try:
            # 1. 🌟 스마트 헤더 탐색: 파일 텍스트를 먼저 스캔해서 'Pixel'로 시작하는 줄의 위치를 찾습니다.
            header_row_idx = 0
            with open(filename, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f):
                    if line.strip().lower().startswith("pixel"):
                        header_row_idx = i
                        break
            
            # 2. 찾은 헤더 위치(skiprows)를 기준으로 불필요한 줄(--- 등)을 건너뛰고 데이터를 불러옵니다.
            df = pd.read_csv(filename, sep=r'\s+', skiprows=header_row_idx)
            
            # 3. 컬럼 이름 전처리 (대소문자 무시, 공백 및 언더바 제거)
            clean_cols = [str(col).strip().lower().replace("_", "") for col in df.columns]
            df.columns = clean_cols
            
            # 4. 데이터 추출
            if 'pixel' in clean_cols and 'abssigma(nm)' in clean_cols:
                self.ils_pixels = df['pixel'].values
                self.ils_sigmas = df['abssigma(nm)'].values
            elif len(df.columns) >= 4:
                # 혹시 헤더 이름이 살짝 달라도, 1열(픽셀)과 4열(Sigma nm)을 강제 추출하는 안전망
                self.ils_pixels = df.iloc[:, 0].values
                self.ils_sigmas = df.iloc[:, 3].values
            else:
                raise ValueError("Invalid FWHM file format. Cannot find Pixel and abs_Sigma(nm) columns.")
            
            self.lbl_fwhm_info.setText(f"✅ Loaded: {len(self.ils_pixels)} Sigma points")
            self.lbl_fwhm_info.setStyleSheet("color: #2E7D32; font-weight: bold;")
            QMessageBox.information(self, "Success", "FWHM Profile loaded successfully.")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load FWHM profile:\n{e}")

    def auto_load_lamp_data(self, intensity_array):
        """Automatically imports lamp data if available from the main application."""
        if intensity_array is not None:
            self.lamp_intensity = intensity_array
            self.radio_measured.setChecked(True)
            peak_idx = int(np.argmax(intensity_array))
            self.spin_peak_px.setValue(peak_idx)
            
            if hasattr(self, 'btn_load_lamp'):
                self.btn_load_lamp.setText("✅ Lamp Synced from Calibration")
                self.btn_load_lamp.setStyleSheet("background-color: #E8F5E9; color: #2E7D32; font-weight: bold;")

    # ---------------------------------------------------------
    # 🌟 Core Feature: Advanced Deconvolution Algorithm
    # ---------------------------------------------------------
    def apply_convolution(self):
        """
        Applies a Wavelength-Dependent Gaussian Convolution.
        This creates a unique Gaussian kernel for EACH pixel based on its specific Sigma.
        """
        if self.raw_wave is None or self.target_wavelengths is None or self.ils_sigmas is None:
            QMessageBox.warning(self, "Warning", "Raw Data, Target Wavelength, and FWHM Profile are all required!")
            return
            
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # 1. 고해상도 그리드 생성 (정확한 수치 적분을 위함)
            hr_step = 0.002  
            hr_wave = np.arange(self.target_wavelengths.min() - 5.0, self.target_wavelengths.max() + 5.0, hr_step)
            
            # 원본 데이터를 고해상도 그리드에 매핑
            f_raw = interp1d(self.raw_wave, self.raw_data, kind='linear', bounds_error=False, fill_value=0.0)
            hr_data = f_raw(hr_wave)
            
            lit_fwhm = self.spin_lit_fwhm.value()
            lit_sigma = lit_fwhm / 2.35482
            
            # 2. 결과물을 담을 빈 배열 준비 
            degraded_data = np.zeros(len(self.target_wavelengths))
            
            # 3. FWHM 프로파일(몇 개의 점)을 전체 픽셀 영역에 부드럽게 보간
            f_sigma = interp1d(self.ils_pixels.astype(float), self.ils_sigmas.astype(float), 
                               kind='linear', fill_value="extrapolate")
            pixel_indices = np.arange(len(self.target_wavelengths))
            target_sigmas = f_sigma(pixel_indices)
            
            # 4. Wavelength-Dependent Convolution (다중 가우시안 커널)
            for i, target_w in enumerate(self.target_wavelengths):
                inst_sigma = target_sigmas[i]
                
                if inst_sigma <= lit_sigma:
                    added_var = 1e-10 
                else:
                    added_var = (inst_sigma**2) - (lit_sigma**2)
                
                kernel = (1.0 / np.sqrt(2 * np.pi * added_var)) * \
                         np.exp(-0.5 * ((hr_wave - target_w)**2) / added_var)
                
                degraded_data[i] = np.sum(hr_data * kernel) * hr_step
            
            self.final_ready_data = degraded_data
            self.gen_info = "Dynamic-ILS-Applied"
            
            # =========================================================
            # 🌟 5. 결과 시각화 (에러 원천 차단 로직 적용)
            # =========================================================
            ax_top = self.fig.axes[0]     # 무조건 위쪽 그래프
            ax_bottom = self.fig.axes[1]  # 무조건 아래쪽 그래프
            
            # 위쪽 그래프 지우고 그리기
            ax_top.clear()
            ax_top.plot(self.target_wavelengths, self.final_ready_data, 'r-', label="Ready Ref (Dynamic ILS)")
            ax_top.set_xlabel("Wavelength (nm)")
            ax_top.set_ylabel("Cross Section")
            ax_top.legend()
            
            
            # 아래쪽 그래프 지우고 그리기
            ax_bottom.clear()
            ax_bottom.plot(self.target_wavelengths, target_sigmas, 'g-', lw=2)
            ax_bottom.set_title("Wavelength-Dependent Sigma Profile")
            ax_bottom.set_xlabel("Wavelength (nm)")
            ax_bottom.set_ylabel("Sigma (nm)")
            
            self.canvas.draw()
            
            self.suggested_filename = f"Ref_{self.gas_name}_{self.gen_info}.dat"
            self.btn_save.setEnabled(True)
            self.btn_save.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
            
            QMessageBox.information(self, "Success", "Dynamic ILS Convolution applied successfully!")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Dynamic Convolution Failed:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()

    def save_reference(self):
        """Saves the fully processed reference spectrum with metadata header."""
        filters = "Data Files (*.dat);;Text Files (*.txt);;CSV Files (*.csv)"
        filename, _ = QFileDialog.getSaveFileName(self, "Save Reference", self.suggested_filename, filters)
        
        if filename:
            # 🌟 Append mathematical metadata as a header string
            header_info = f"Generated by CAESAR Pro Ultimate\nGas: {self.gas_name}\nMath: {self.gen_info}"
            
            if filename.endswith('.csv'):
                np.savetxt(filename, self.final_ready_data, fmt='%.8e', delimiter=',', header=header_info)
            else:
                np.savetxt(filename, self.final_ready_data, fmt='%.8e', header=header_info)
            
            # Emit signal to automatically register in the main engine
            self.reference_saved.emit(self.gas_name, filename)
            QMessageBox.information(self, "Saved", f"Reference saved and synced to Main Engine:\n{os.path.basename(filename)}")


# =============================================================================
# 6. Visualization Components
# =============================================================================
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
        
        # 🌟 그래프 객체 저장용 딕셔너리 (깜빡임 방지의 핵심)
        self.plot_items = {} 
        self.curve_items = {}
        
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        self.init_tab_components_pg()
        self.init_tab_fit_view_pg()
        self.init_tab_trend_pg()
        self.init_tab_viewer_pg()
        self.init_tab_hq_mpl()

    # 🌟 공통 툴바 생성 도구
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
        """GraphicsLayoutWidget 안의 모든 그래프를 원래 비율로 복구"""
        for item in glw.ci.items:
            if isinstance(item, pg.PlotItem):
                item.enableAutoRange(axis='xy', enable=True)

    # =========================================================
    # [Tab 1] Components (깜빡임 방지 & 잔차 복구)
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
    # [Tab 3] Trend (전체 데이터 & 자유 줌/스크롤 지원)
    # =========================================================
    def init_tab_trend_pg(self):
        self.tab_trend = QWidget()
        layout = QVBoxLayout(self.tab_trend)
        
        self.glw_trend = pg.GraphicsLayoutWidget()
        layout.addLayout(self._create_reset_toolbar(target_glw=self.glw_trend))
        
        self.p_sh = self.glw_trend.addPlot(row=0, col=0, title="Shift Trend")
        self.p_sq = self.glw_trend.addPlot(row=1, col=0, title="Squeeze Trend")
        self.p_rms = self.glw_trend.addPlot(row=2, col=0, title="RMS Error Trend")
        self.p_rms.setLogMode(y=True)
        
        for p in [self.p_sh, self.p_sq, self.p_rms]:
            p.setClipToView(True) 
            p.showGrid(x=True, y=True)
            p.setLabel('bottom', 'File Index')
            
        self.curve_sh = self.p_sh.plot(pen='g', symbol='o', symbolSize=4)
        self.curve_sq = self.p_sq.plot(pen='b', symbol='o', symbolSize=4)
        self.curve_rms = self.p_rms.plot(pen='k', symbol='o', symbolSize=4)
        
        self.x_data, self.y_sh, self.y_sq, self.y_rms = [], [], [], []
        
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
        l_view.addLayout(self._create_reset_toolbar(target_pw=self.pw_view)) # 뷰어용 리셋 버튼
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
        
        self.tabs.addTab(self.tab_view, "📂 Viewer (Fast)")

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
        
        self.tabs.addTab(self.tab_hq, "📸 HQ Export (Pro)")

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
            
    def plot_viewer(self, x, y, title, color='b', style='-'):
        self.latest_raw_data = (x, y, title)
        x_plot, x_label = self.get_x_axis(x)
        self.pw_view.setLabel('bottom', x_label)
        self.pw_view.setTitle(title)
        
        pen = pg.mkPen(color, width=1.5) if style == '-' else None
        sym = 'o' if style != '-' else None
        
        self.curve_view.setData(x_plot, y, pen=pen, symbol=sym, symbolSize=3, symbolBrush=color)
        if self.chk_autofit.isChecked():
            self.pw_view.autoRange()
        self.update_stats(y)

    # ---------------------------------------------------------
    # Real-Time Rendering Methods
    # ---------------------------------------------------------
    def update_spectrum(self, pixel_idx, intensity_raw, intensity_fit, intensity_poly, fit_params, title):
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
        gas_list = self.engine.gas_list
        if not gas_list: return
        
        # 🌟 1. 최초 1회만 Plot 틀 생성 (Residual 포함)
        current_gas_count = len(gas_list)
        if "layout_ready" not in self.plot_items or self.plot_items["gas_count"] != current_gas_count:
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

        # 🌟 2. 데이터 알맹이만 부드럽게 업데이트
        x_plot, _ = self.get_x_axis(pixel_idx)
        residual = intensity_raw - intensity_fit 

        for i, name in enumerate(gas_list):
            gas_fit = self.engine.get_individual_gas_contribution(pixel_idx, fit_params['shifts'], fit_params['squeezes'], fit_params['gas_coeffs'], i)
            self.curve_items[f"{name}_data"].setData(x_plot, residual + gas_fit)
            self.curve_items[f"{name}_fit"].setData(x_plot, gas_fit)
            
        self.curve_items["poly_raw"].setData(x_plot, intensity_raw)
        self.curve_items["poly_fit"].setData(x_plot, intensity_poly)
        self.curve_items["residual"].setData(x_plot, residual)

    def update_trend(self, data: dict):
        idx = data.get('idx', 0)
        shift = data.get('shift', 0.0)
        squeeze = data.get('squeeze', 1.0)
        rms = data.get('rms', 0.0)
        self.x_data.append(idx)
        self.y_sh.append(shift)
        self.y_sq.append(squeeze)
        self.y_rms.append(rms)
        
        # 전체 데이터 유지 (자유로운 줌/팬 가능)
        self.curve_sh.setData(self.x_data, self.y_sh)
        self.curve_sq.setData(self.x_data, self.y_sq)
        
        rms_data = np.array(self.y_rms)
        rms_data[rms_data <= 0] = 1e-9
        self.curve_rms.setData(self.x_data, rms_data)
        
        # Shift 그래프가 자동 모드라면 업데이트
        if self.p_sh.getViewBox().autoRangeEnabled(): 
            self.p_sh.enableAutoRange(axis='x', enable=True)
            
        # Squeeze 그래프가 자동 모드라면 업데이트
        if self.p_sq.getViewBox().autoRangeEnabled(): 
            self.p_sq.enableAutoRange(axis='x', enable=True)
            
        # RMS 그래프가 자동 모드라면 업데이트
        if self.p_rms.getViewBox().autoRangeEnabled(): 
            self.p_rms.enableAutoRange(axis='x', enable=True)

    def clear_trend(self):
        self.x_data, self.y_sh, self.y_sq, self.y_rms = [], [], [], []
        self.curve_sh.setData([], [])
        self.curve_sq.setData([], [])
        self.curve_rms.setData([], [])

    # =========================================================
    # [HQ Export] 
    # =========================================================
    def render_hq_plot(self):
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

# =============================================================================
# 7. Post-Processing & Export (Final Output)
# =============================================================================
class R_GeneratorDialog(QDialog):
    """
    BBCEAS Universal R-Curve Generator
    Calculates the wavelength-dependent mirror reflectivity (R(λ)) 
    using the difference in Rayleigh scattering cross-sections of two known gases.
    """
    def __init__(self, parent, wavelengths):
        super().__init__(parent)
        self.setWindowTitle("🎡 BBCEAS Universal R-Curve Generator")
        self.resize(550, 650)
        self.wl = wavelengths
        self.data1 = None
        self.data2 = None
        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        
        # 1. Physical Parameters Section
        phys_group = QGroupBox("Physical Parameters")
        phys_form = QFormLayout()
        
        self.txt_d = QLineEdit("51.8")
        self.txt_temp = QLineEdit("25.0")
        self.txt_press = QLineEdit("1013.25")
        
        phys_form.addRow("Cavity Length (d, cm):", self.txt_d)
        phys_form.addRow("Temperature (°C):", self.txt_temp)
        phys_form.addRow("Pressure (mbar):", self.txt_press)
        
        phys_group.setLayout(phys_form)
        self.main_layout.addWidget(phys_group)

        # 2. Gas Slot Generator (Returns the constructed GroupBox and its widgets)
        def create_gas_slot(slot_num):
            box = QGroupBox(f"Gas Slot {slot_num} Settings")
            vbox = QVBoxLayout()
            
            combo = QComboBox()
            combo.addItems(["Zero-Air (ZA/Air)", "Nitrogen (N2)", "Helium (He)", "Custom Input"])
            
            # Custom input fields
            custom_widget = QWidget()
            custom_hbox = QHBoxLayout(custom_widget)
            txt_c = QLineEdit(); txt_c.setPlaceholderText("C (e.g., 1.1e-15)")
            txt_k = QLineEdit(); txt_k.setPlaceholderText("k (e.g., -4.1)")
            
            custom_hbox.addWidget(QLabel("C:"))
            custom_hbox.addWidget(txt_c)
            custom_hbox.addWidget(QLabel("k:"))
            custom_hbox.addWidget(txt_k)
            custom_widget.setVisible(False)
            
            # Toggle custom input visibility based on combobox selection
            combo.currentIndexChanged.connect(
                lambda idx: custom_widget.setVisible(combo.currentText() == "Custom Input")
            )
            
            btn_file = QPushButton(f"📂 Load Gas {slot_num} Spectrum")
            btn_file.clicked.connect(lambda: self.load_data(slot_num))
            
            lbl_file = QLabel(f"Gas {slot_num}: No file selected")
            lbl_file.setStyleSheet("color: gray; font-size: 11px;")
            
            vbox.addWidget(QLabel("<b>Select Gas Type:</b>"))
            vbox.addWidget(combo)
            vbox.addWidget(custom_widget)
            vbox.addWidget(btn_file)
            vbox.addWidget(lbl_file)
            box.setLayout(vbox)
            
            return box, combo, txt_c, txt_k, lbl_file

        # Instantiate Gas 1 and Gas 2 widgets
        self.slot1_box, self.combo1, self.c1, self.k1, self.lbl1 = create_gas_slot(1)
        self.slot2_box, self.combo2, self.c2, self.k2, self.lbl2 = create_gas_slot(2)
        
        self.main_layout.addWidget(self.slot1_box)
        self.main_layout.addWidget(self.slot2_box)

        # 3. Final Calculation Button
        self.btn_calc = QPushButton("📊 Calculate Reflectivity (R(λ))")
        self.btn_calc.setFixedHeight(60)
        self.btn_calc.setStyleSheet("""
            QPushButton {
                background-color: #0277BD; color: white; 
                font-weight: bold; font-size: 15px; border-radius: 5px;
            }
            QPushButton:hover { background-color: #01579B; }
        """)
        self.btn_calc.clicked.connect(self.calculate_r)
        self.main_layout.addWidget(self.btn_calc)

    def load_data(self, slot):
        """Loads spectrum data, filtering out specialized headers (e.g., Ocean Optics timestamps)."""
        filename, _ = QFileDialog.getOpenFileName(self, f"Select Spectrum {slot}", "", "Data Files (*.txt *.dat *.csv)")
        if not filename: return

        try:
            with open(filename, 'r', encoding='ISO-8859-1') as file:
                lines = file.readlines()
            
            start_idx = -1
            for i, line in enumerate(lines):
                if ">>>>>Begin Spectral Data<<<<<" in line:
                    start_idx = i + 1
                    break
            
            if start_idx != -1:
                # Process specialized format
                data_line = lines[start_idx + 1].strip().split('\t')
                try:
                    float(data_line[0])
                    numeric_values = [float(x) for x in data_line if x.strip()]
                except ValueError:
                    # Skip the first column if it's a non-numeric timestamp
                    numeric_values = [float(x) for x in data_line[1:] if x.strip()]
                intensity = np.array(numeric_values)
            else:
                # Standard pandas parsing for regular CSV/DAT files
                df = pd.read_csv(filename, sep=None, engine='python', header=None)
                df_numeric = df.apply(pd.to_numeric, errors='coerce').dropna(axis=1, how='all')
                intensity = df_numeric.iloc[:, 0].values

            # Assign to the correct slot and update UI
            if slot == 1:
                self.data1 = intensity.astype(float)
                self.lbl1.setText(f"✅ Loaded: {os.path.basename(filename)}")
                self.lbl1.setStyleSheet("color: blue; font-weight: bold;")
            else:
                self.data2 = intensity.astype(float)
                self.lbl2.setText(f"✅ Loaded: {os.path.basename(filename)}")
                self.lbl2.setStyleSheet("color: blue; font-weight: bold;")

        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Error loading file:\n{e}")

    def get_rayleigh(self, combo, txt_c, txt_k):
        r"""Returns the Rayleigh scattering cross-section $\sigma(\lambda)$ based on the empirical formula $C \cdot \lambda^k$."""
        mode = combo.currentText()
        if mode == "Helium (He)": 
            return 1.336e-17 * (self.wl ** -4.1287)
        elif mode == "Nitrogen (N2)": 
            return 1.2577e-15 * (self.wl ** -4.1814)
        elif mode == "Zero-Air (ZA/Air)": 
            return 1.100065e-15 * (self.wl ** -4.1656)
        else:
            try:
                c_val = float(txt_c.text())
                k_val = float(txt_k.text())
                return c_val * (self.wl ** k_val)
            except ValueError:
                raise ValueError("Invalid Custom C or k values. Please enter valid numbers.")

    def calculate_r(self):
        """Calculates the mirror reflectivity R(λ) and prompts the user to save it as a CSV."""
        if self.data1 is None or self.data2 is None:
            QMessageBox.warning(self, "Missing Data", "Please load spectra for both Gas 1 and Gas 2.")
            return
        
        try:
            # Helper to align data lengths if resolutions mismatch
            def match_length(data, target_len):
                if len(data) == target_len: 
                    return data
                return np.interp(np.linspace(0, 1, target_len), np.linspace(0, 1, len(data)), data)

            d1 = match_length(self.data1, len(self.wl))
            d2 = match_length(self.data2, len(self.wl))
            
            # Calculate molecular number density (rho) using Ideal Gas Law
            # $P(Pa) / (k_B \cdot T(K)) \times 10^{-6}$ (conversion to molecules/cm^3)
            pressure_pa = float(self.txt_press.text()) * 100
            temp_k = float(self.txt_temp.text()) + 273.15
            k_b = 1.380649e-23
            
            rho = (pressure_pa / (k_b * temp_k)) * 1e-6 
            
            # Calculate total extinction coefficients
            alpha1 = self.get_rayleigh(self.combo1, self.c1, self.k1) * rho
            alpha2 = self.get_rayleigh(self.combo2, self.c2, self.k2) * rho

            # Calculate Reflectivity R
            ratio = d2 / d1
            cavity_len = float(self.txt_d.text())
            
            r_curve = 1 - cavity_len * ((ratio * alpha2 - alpha1) / (1 - ratio))

            gas1 = self.combo1.currentText().split(' ')[ 0 ]
            gas2 = self.combo2.currentText().split(' ')[ 0 ]
            import datetime
            date_str = datetime.datetime.now().strftime("%Y%m%d")
            
            default_fname = f"RCurve_{gas1}_vs_{gas2}_d{cavity_len}cm_{date_str}.csv"

            # Save the result
            save_path, _ = QFileDialog.getSaveFileName(self, "Save R-Curve", default_fname, "CSV (*.csv)")
            
            if save_path:
                pd.DataFrame({'Wavelength': self.wl, 'Reflectivity': r_curve}).to_csv(save_path, index=False)
                QMessageBox.information(self, "Success", "Reflectivity curve saved successfully!")
                self.accept()
                
        except Exception as e:
            QMessageBox.critical(self, "Calculation Error", f"Failed to calculate R(λ):\n{e}")

# PostProcessDialog removed — functionality covered by save() in app_window.py
class PostProcessDialog(QDialog):
    """Deprecated — kept as stub to avoid import errors if referenced externally."""
    def __init__(self, parent, analysis_results, wavelengths):
        super().__init__(parent)
        self.setWindowTitle("📊 BBCEAS Precision Concentration & Multi-Format Export")
        self.resize(500, 600)
        
        self.results = analysis_results # Current analysis results (list of dicts or DataFrame)
        self.wavelengths = wavelengths
        self.r_interp = None
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # 1. Physical Parameters Input
        self.input_cavity_len = QLineEdit()
        self.input_cavity_len.setPlaceholderText("in cm (e.g., 51.8)")
        
        self.input_temp = QLineEdit()
        self.input_temp.setPlaceholderText("in °C (e.g., 25.0)")
        
        self.input_press = QLineEdit()
        self.input_press.setPlaceholderText("in mbar (e.g., 1013.25)")
        
        self.input_conv_factor = QLineEdit()
        self.input_conv_factor.setReadOnly(True) 
        
        self.input_temp.textChanged.connect(self.calculate_factor_auto)
        self.input_press.textChanged.connect(self.calculate_factor_auto)

        form.addRow("Cavity Length (d, cm):", self.input_cavity_len)
        form.addRow("Temperature (°C):", self.input_temp)
        form.addRow("Pressure (mbar):", self.input_press)
        form.addRow("Calc Factor (1 ppb):", self.input_conv_factor)
        layout.addLayout(form)

        # 2. Reflectivity Curve Load
        self.btn_load_r = QPushButton("📁 Step 1: Load Reflectivity (R) Curve")
        self.btn_load_r.clicked.connect(self.load_reflectivity)
        layout.addWidget(self.btn_load_r)
        
        self.lbl_r_status = QLabel("❌ Reflectivity Curve Not Loaded")
        layout.addWidget(self.lbl_r_status)

        # 3. Export Format Selection
        layout.addWidget(QLabel("<b>Step 2: Select Export Format</b>"))
        self.combo_format = QComboBox()
        self.combo_format.addItems([
            "CSV (*.csv) - Standard Text", 
            "Parquet (*.parquet) - Big Data / High Performance", 
            "Feather (*.feather) - Ultra-Fast Read/Write",
            "DAT (*.dat) - Tab Separated Text"
        ])
        layout.addWidget(self.combo_format)

        # 4. Execute and Save Button
        self.btn_run = QPushButton("🚀 Convert to ppb & Export Data")
        self.btn_run.setFixedHeight(60)
        self.btn_run.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold;")
        self.btn_run.clicked.connect(self.run_process_and_save)
        layout.addWidget(self.btn_run)

    def calculate_factor_auto(self):
        """Automatically calculates molecular density for 1 ppb based on environment variables."""
        try:
            temp_c = float(self.input_temp.text())
            press_mbar = float(self.input_press.text())
            
            # Ideal gas law calculation for number density of air (molecules/cm^3)
            k_b = 1.380649e-23
            n_air = ((press_mbar * 100) / (k_b * (temp_c + 273.15))) * 1e-6
            
            self.input_conv_factor.setText(f"{n_air * 1e-9:.4e}")
        except Exception: 
            self.input_conv_factor.setText("")

    def load_reflectivity(self):
        """Loads the mirror reflectivity curve data."""
        filename, _ = QFileDialog.getOpenFileName(self, "Load Reflectivity Curve", "", "Data Files (*.csv *.txt *.dat)")
        if filename:
            try:
                df = pd.read_csv(filename, sep=None, engine='python')
                self.r_interp = interp1d(df.iloc[:, 0], df.iloc[:, 1], bounds_error=False, fill_value="extrapolate")
                self.lbl_r_status.setText(f"✅ Loaded Successfully: {os.path.basename(filename)}")
            except Exception as e: 
                QMessageBox.critical(self, "Load Error", f"Failed to load Reflectivity Curve:\n{e}")

    def run_process_and_save(self):
        """Applies physical corrections to concentrations and exports the dataframe."""
        if not self.r_interp or not self.input_conv_factor.text():
            QMessageBox.warning(self, "Missing Parameters", "Please ensure all parameters are filled and the Reflectivity file is loaded.")
            return

        try:
            # 1. Finalize Physical Parameters
            d = float(self.input_cavity_len.text())
            mid_wl = np.mean(self.wavelengths)
            r_val = self.r_interp(mid_wl)
            l_eff = d / (1 - r_val)
            calc_factor = float(self.input_conv_factor.text())

            # 2. Update Data (Calibrate against existing engine defaults)
            df = pd.DataFrame(self.results)
            engine_default_factor = 2.46e10  # Base constant from CAESAR engine
            
            # Identify concentration-related columns dynamically
            target_cols = [col for col in df.columns if any(keyword in col for keyword in ['NO2', 'CHOCHO', 'H2O', 'Conc'])]
            
            for col in target_cols:
                # Formula: Corrected ppb = Measured Value * Correction Factor
                df[col] = df[col] * (engine_default_factor / (l_eff * calc_factor * 1e9)) 

            # 3. Multi-Format Export Logic
            selected_format = self.combo_format.currentText()
            
            # Extract extension intuitively, e.g., ".csv" from "CSV (*.csv) - Standard Text"
            ext = "." + selected_format.split(" (*.")[1].split(")")[0]
            
            import datetime
            date_str = datetime.datetime.now().strftime("%Y%m%d")
            d_val = self.input_cavity_len.text()
            
            default_fname = f"{date_str}_PPB_Result_d{d_val}cm_R_Applied{ext}"
            
            save_path, _ = QFileDialog.getSaveFileName(self, "Save Results", default_fname, selected_format)

            if save_path:
                if ext == ".csv": 
                    df.to_csv(save_path, index=False)
                elif ext == ".parquet": 
                    df.to_parquet(save_path, index=False)
                elif ext == ".feather": 
                    df.to_feather(save_path)
                elif ext == ".dat": 
                    df.to_csv(save_path, sep='\t', index=False)
                
                QMessageBox.information(self, "Success", f"Data successfully converted and exported in {ext} format.")
                self.accept()
                
        except Exception as e: 
            QMessageBox.critical(self, "Export Error", f"Failed to process and save data:\n{e}")