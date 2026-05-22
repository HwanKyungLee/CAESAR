import sys
import os
import math
import datetime
import time
import json
import numpy as np
import pandas as pd
import pyqtgraph as pg
from data_io import ui_scale as _ui_scale
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
    Attaches interactive navigation (zoom, pan, reset) to a Matplotlib Axes object.

    Controls
    --------
    Mouse wheel      → zoom in/out centered on the cursor position
    Left-click drag  → pan the graph (in 'pan_left' mode)
    Right-click drag → pan the graph (in 'pan_right' mode, used in RangeSelectorDialog)
    Double left-click→ reset zoom to show all data (autoscale)
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
            
        # Scroll up → zoom out (scale_factor > 1 expands the axis range)
        # Scroll down → zoom in (scale_factor < 1 shrinks the axis range)
        scale_factor = 1 / self.base_scale if event.button == 'up' else self.base_scale
            
        # Calculate new width and height
        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor
        
        # Calculate how far the cursor is from each edge (as a fraction of the range).
        # This anchors the zoom so the point under the cursor stays fixed on screen.
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
        _s = _ui_scale()
        self.resize(int(1100 * _s), int(700 * _s))
        
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
        Refines a coarse integer peak position to sub-pixel accuracy.

        Two-stage approach:
          Stage 1 — Centroid (Center of Mass):
            x_c = Σ(x · I) / Σ(I)   using a ±5-pixel window around the peak.
            Fast and always works, but slightly biased for asymmetric peaks.

          Stage 2 — Gaussian fitting (curve_fit):
            Fits a Gaussian + offset model  a·exp(-(x-μ)²/2σ²) + c  to the same
            window, using the centroid as the initial guess for μ.
            More accurate for symmetric emission lines (Hg lamp, etc.).

        If Gaussian fitting fails or diverges by more than the window size,
        the centroid value is returned as a safe fallback.
        Returns a float (sub-pixel) in all cases — never a rounded integer.
        """
        try:
            # 1. Narrow search to ±5 pixels to match sharp peaks (e.g., mercury lamp)
            window = 5  
            start = max(0, int(peak_pixel) - window)
            end = min(len(intensities), int(peak_pixel) + window + 1)
            
            x_data = np.arange(start, end)
            y_data = intensities[start:end]
            
            # 2. Remove baseline (background noise)
            y_bg_removed = y_data - np.min(y_data)
            mass_sum = np.sum(y_bg_removed)
            
            # 3. Step 1: Find sub-pixel center using Center-of-Mass (Centroid)
            if mass_sum == 0:
                return float(peak_pixel)
            centroid_x = np.sum(x_data * y_bg_removed) / mass_sum
            
            # 4. Step 2: Initial estimates for Gaussian fitting (using centroid result)
            offset_guess = np.min(y_data)
            a_guess = np.max(y_data) - offset_guess
            mu_guess = centroid_x  # Use centroid (not integer peak) as initial guess
            sigma_guess = 1.0      # Narrow sigma estimate for sharp peaks
            
            p0_guess = [a_guess, mu_guess, sigma_guess, offset_guess]
            
            # 5. Run optimization (curve_fit)
            popt, _ = curve_fit(self._gaussian_model, x_data, y_data, p0=p0_guess, maxfev=2000)
            sub_pixel_mu = popt[1]  # mu is the second parameter: [a, mu, sigma, offset]

            # 6. If fitting diverged too far, safely fall back to centroid
            if abs(sub_pixel_mu - peak_pixel) > window:
                return centroid_x

            return sub_pixel_mu
            
        except Exception as e:
            # On Gaussian fit failure, return centroid instead of rounding to integer
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

            x_data = np.arange(start, end, dtype=float)
            y_data = np.asarray(intensities[start:end], dtype=float)

            # 2. Initial estimates — 데이터에서 자동 추정
            offset_guess = float(np.percentile(y_data, 10))   # 하위 10% → 베이스라인
            a_guess      = float(np.max(y_data)) - offset_guess
            mu_guess     = float(x_data[np.argmax(y_data)])   # 실제 최대값 위치

            # sigma 초기값: 반치폭 픽셀 수에서 추정
            y_above_half = np.where((y_data - offset_guess) >= a_guess / 2.0)[0]
            sigma_guess  = (len(y_above_half) / 2.3548) if len(y_above_half) >= 2 else 2.0
            sigma_guess  = max(0.5, min(sigma_guess, window * 0.8))

            # 3. Curve Fitting — bounds로 발산 방지
            p0_guess = [a_guess, mu_guess, sigma_guess, offset_guess]
            bounds_lo = [0.0,   float(start),  0.3,      -np.inf]
            bounds_hi = [np.inf, float(end),   float(window), np.inf]

            popt, _ = curve_fit(
                self._gaussian_model, x_data, y_data,
                p0=p0_guess,
                bounds=(bounds_lo, bounds_hi),
                maxfev=8000,
            )
            a, mu, sigma, offset = popt

            # 4. Convert Gaussian sigma → FWHM
            # For a Gaussian: FWHM = 2 · √(2 · ln 2) · σ ≈ 2.3548 · σ
            fwhm_pixels = 2.3548 * abs(sigma)

            # 5. Convert to nm — 피팅된 peak center(mu) 근방 로컬 분산율 사용
            fwhm_nm = None
            if current_wavelengths is not None:
                wl = np.asarray(current_wavelengths)
                mu_i = int(np.clip(round(mu), 1, len(wl) - 2))
                dispersion = (wl[mu_i + 1] - wl[mu_i - 1]) / 2.0  # nm/px (로컬)
                if dispersion > 0:
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
            # 1. Load data based on file extension
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

            # 2. LightField and generic header alias dictionary
            header_aliases = {
                # Y-axis (Intensity)
                'i': 'intensity', 'intensity': 'intensity', 'counts': 'intensity',
                # X-axis (Wavelength or Pixel/Column)
                'w': 'wavelength', 'wavelength': 'wavelength',
                'x': 'column', 'column': 'column', 'pixel': 'column',
                # Metadata and grouping
                'f': 'frame', 'frame': 'frame',
                'y': 'row', 'row': 'row',
                'r': 'roi', 'roi': 'roi',
                'ests': 'ests', 'exposurestarttimestamp': 'ests',
                'eets': 'eets', 'exposureendtimestamp': 'eets',
                'ftn': 'ftn', 'frametrackingnumber': 'ftn',
                'gtw': 'gtw', 'gatetrackingdelay': 'gtw',
                'mtp': 'mtp', 'modulationtrackingphase': 'mtp'
            }

            # 3. Normalize DataFrame column headers (lowercase, strip spaces/underscores)
            original_cols = df.columns.tolist()
            clean_cols = []
            for col in original_cols:
                # e.g., "Exposure Start Time Stamp" -> "exposurestarttimestamp"
                raw_str = str(col).strip().lower().replace(" ", "").replace("_", "")
                # Use alias if mapped, otherwise keep the normalized name
                clean_cols.append(header_aliases.get(raw_str, raw_str))
            
            df.columns = clean_cols

            # 4. Extract X and Y data using normalized header names
            x_col = None
            if 'wavelength' in clean_cols:
                x_col = 'wavelength'
            elif 'column' in clean_cols:
                x_col = 'column'

            y_col = 'intensity' if 'intensity' in clean_cols else None

            # 5. Assign final data
            if x_col and y_col:
                # Average intensity per X value when multiple frames/rows are stored
                avg_spec = df.groupby(x_col)[y_col].mean()
                self.spectrum = avg_spec.values
                # Always use integer pixel indices so click events map to array positions
                # correctly in FWHM calculation (nm values must not be used as indices)
                self.pixels = np.arange(len(self.spectrum))
            elif y_col:
                # Intensity only (no X-axis info)
                self.spectrum = df[y_col].values
                self.pixels = np.arange(len(self.spectrum))
            else:
                # Fallback: unknown format — force-use the last column
                print(f"Warning: Expected headers not found. Found columns: {original_cols}. Using the last column.")
                self.spectrum = df.iloc[:, -1].values
                if x_col:
                    self.pixels = df[x_col].values
                else:
                    self.pixels = np.arange(len(self.spectrum))

            # 6. Update graph
            self.ax.clear()
            self.ax.plot(self.pixels, self.spectrum, 'k-', alpha=0.7, label='Lamp Spectrum')
            
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

        # 4. Calculate R² (Coefficient of Determination)
        # R² = 1 means the polynomial passes exactly through every data point.
        # R² > 0.9999 is typically required for a reliable wavelength calibration.
        # Formula: R² = 1 - SS_res / SS_tot
        #   SS_res = sum of squared residuals between the fit and measured wavelengths
        #   SS_tot = total variance of the measured wavelengths
        fitted_waves = np.polyval(self.poly_coeffs, pixel_list)
        y_mean    = np.mean(wavelength_list)
        ss_tot    = np.sum((wavelength_list - y_mean)**2)
        ss_res    = np.sum((wavelength_list - fitted_waves)**2)
        r_squared = 1 - (ss_res / ss_tot)
        
        # 5. Generate wavelengths for the full pixel range
        total_pixels = len(self.spectrum) if hasattr(self, 'spectrum') and self.spectrum is not None else 2048
        self.wavelengths = np.polyval(self.poly_coeffs, np.arange(total_pixels))
        
        if not hasattr(self, 'fwhm_records'):
            self.fwhm_records = {}
            
        self.fwhm_records.clear()  # Clear any leftover records from previous runs
        
        if hasattr(self, 'spectrum') and self.spectrum is not None:
            # pixel_list contains the peaks registered in the table by the user
            for px in pixel_list:  
                fwhm_px, fwhm_nm = self.calculate_fwhm(px, self.spectrum, self.wavelengths)
                if fwhm_px is not None:
                    # Store result in the dictionary
                    self.fwhm_records[round(px, 3)] = {"fwhm_nm": fwhm_nm, "fwhm_px": fwhm_px}

        # Calculate average FWHM for the status message
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

        # 8. Show fitting result popup
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
            
            # Proceed only if fwhm_records exist and are non-empty
            if hasattr(self, 'fwhm_records') and self.fwhm_records:
                # Collect only FWHM values successfully calculated in nm
                valid_fwhms = [data['fwhm_nm'] for data in self.fwhm_records.values() if data.get('fwhm_nm') is not None]
                
                # Compute average if at least one valid value exists
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
            QMessageBox.warning(self, "No Data", "No FWHM data to save.\nRight-click a peak on the graph to calculate FWHM first.")
            return

        # Auto-generate filename
        date_str = datetime.datetime.now().strftime("%Y%m%d")
        suggested_name = f"FWHM_Analysis_{date_str}.txt"

        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save FWHM & Sigma Data", suggested_name, "Text Files (*.txt);;CSV Files (*.csv)"
        )

        if save_path:
            try:
                with open(save_path, 'w', encoding='utf-8') as f:
                    # Write file header
                    f.write("# BBCEAS FWHM & Sigma Analysis Records\n")
                    f.write(f"# Generated: {date_str}\n")
                    f.write("# Formula: abs(Sigma) = FWHM / 2.3548\n")
                    f.write("-" * 60 + "\n")
                    
                    # Tab-separated for easy import into Excel / Origin
                    if save_path.endswith('.csv'):
                        f.write("Pixel,FWHM(nm),FWHM(px),abs_Sigma(nm),abs_Sigma(px)\n")
                    else:
                        f.write("Pixel\tFWHM(nm)\tFWHM(px)\tabs_Sigma(nm)\tabs_Sigma(px)\n")
                    
                    # Sort by pixel number (ascending)
                    for px in sorted(self.fwhm_records.keys()):
                        data = self.fwhm_records[px]
                        
                        # Retrieve FWHM values
                        f_nm = data['fwhm_nm']
                        f_px = data['fwhm_px']
                        
                        # Back-calculate Sigma (FWHM = 2.3548 * sigma)
                        s_nm = f_nm / 2.3548 if f_nm is not None else None
                        s_px = f_px / 2.3548 if f_px is not None else None

                        # Format: N/A if missing, 4 decimal places otherwise
                        str_f_nm = f"{f_nm:.4f}" if f_nm is not None else "N/A"
                        str_f_px = f"{f_px:.4f}" if f_px is not None else "N/A"
                        str_s_nm = f"{s_nm:.4f}" if s_nm is not None else "N/A"
                        str_s_px = f"{s_px:.4f}" if s_px is not None else "N/A"
                        
                        if save_path.endswith('.csv'):
                            f.write(f"{px},{str_f_nm},{str_f_px},{str_s_nm},{str_s_px}\n")
                        else:
                            f.write(f"{px}\t{str_f_nm}\t{str_f_px}\t{str_s_nm}\t{str_s_px}\n")

                QMessageBox.information(self, "Success", f"FWHM data saved successfully!\nFile: {os.path.basename(save_path)}")
            
            except Exception as e:
                QMessageBox.critical(self, "Error", f"An error occurred while saving:\n{e}")


class RangeSelectorDialog(QDialog):
    """
    Dialog for visually selecting the fitting range by dragging over the data.
    Supports overlaying reference spectra for precise visual alignment.
    """
    apply_range = pyqtSignal(int, int)

    def __init__(self, data_path, pixel_min, pixel_max, engine):
        super().__init__()
        self.setWindowTitle("🔍 Fit Range Selector")
        _s = _ui_scale()
        self.resize(int(900 * _s), int(600 * _s))
        
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
    Dialog for zeroing out unwanted spectral regions in a reference spectrum.

    Why masking?
    The fitting engine uses the full reference array.  If a reference has
    strong features outside the measurement window (detector edge noise, saturated
    lines, or features that overlap with another gas), those can corrupt the fit.
    Masking forces those pixels to zero so they contribute nothing.

    Two modes
    ---------
    Manual Range  → keep only pixels in [min, max]; zero everything outside.
    Auto-Cut      → zero any pixel whose absolute value is below X% of the peak.
    """
    def __init__(self, gas_list):
        super().__init__()
        self.setWindowTitle("✂️ Smart Masking Tool")
        _s = _ui_scale()
        self.resize(int(400 * _s), int(250 * _s))
        
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
        _s = _ui_scale()
        self.resize(int(1020 * _s), int(350 * _s))
        layout = QVBoxLayout(self)

        self.table = QTableWidget(len(gas_list), 7)
        self.table.setHorizontalHeaderLabels(["Gas Name", "Shift Mode", "Shift Params", "Squeeze Mode", "Squeeze Params", "T_ref (°C)", "dσ/dT (%/°C)"])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # Last two columns are numeric spinboxes — cap their width
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 110)
        
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

            # --- Temperature-dependent cross-section ---
            t_ref_spin = QDoubleSpinBox()
            t_ref_spin.setRange(-100.0, 100.0)
            t_ref_spin.setDecimals(1)
            t_ref_spin.setValue(float(props.get("t_ref", 25.0)))
            t_ref_spin.setToolTip("Temperature at which this reference was measured (°C)")
            self.table.setCellWidget(i, 5, t_ref_spin)

            t_coeff_spin = QDoubleSpinBox()
            t_coeff_spin.setRange(-10.0, 10.0)
            t_coeff_spin.setDecimals(3)
            t_coeff_spin.setSingleStep(0.01)
            t_coeff_spin.setValue(float(props.get("t_coeff", 0.0)))
            t_coeff_spin.setToolTip("Temperature coefficient: σ(T) = σ(T_ref)×(1 + coeff×ΔT/100)\n0.0 = no correction")
            self.table.setCellWidget(i, 6, t_coeff_spin)

            # Save widget references for data extraction
            self.param_widgets[gas] = {
                "sh_cmb": cmb_sh, "sh_lim": sh_lim, "sh_fix": sh_fix, "sh_lnk": sh_lnk,
                "sq_cmb": cmb_sq, "sq_lim": sq_lim, "sq_fix": sq_fix, "sq_lnk": sq_lnk,
                "t_ref_spin": t_ref_spin, "t_coeff_spin": t_coeff_spin
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
                "sq_mode": sq_mode, "sq_val": sq_val,
                "t_ref": w["t_ref_spin"].value(),
                "t_coeff": w["t_coeff_spin"].value()
            }
        return props
       
class ReferenceGeneratorDialog(QDialog):
    """
    Generates instrument-ready reference cross-sections by applying
    a wavelength-dependent Gaussian convolution (ILS degradation).

    Why is this needed?
    Literature cross-sections (e.g., from HITRAN or Vandaele) are measured
    at very high spectral resolution (σ < 0.01 nm).  Our instrument has a much
    coarser resolution (σ ≈ 0.2–0.5 nm).  If we feed the sharp reference directly
    into the fit, the mismatch causes large residuals and incorrect concentrations.

    This dialog convolves each wavelength point of the reference with a Gaussian
    whose sigma is taken from the measured FWHM profile — making the reference
    look exactly like what the spectrometer would record.

    Variance addition formula:
        σ_inst² = σ_lit² + σ_extra²   →   σ_extra = √(σ_inst² − σ_lit²)
    Only the 'extra' broadening is applied because the literature data already
    has σ_lit baked in.
    """
    reference_saved = pyqtSignal(str, str)

    def __init__(self, parent=None, current_wavelengths=None):
        super().__init__(parent)
        self.setWindowTitle("✂️ Ultimate Reference Generator (with Advanced Deconvolution)")
        self._s = _ui_scale()
        self.resize(int(1150 * self._s), int(800 * self._s))
        
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
        
        # Internal data storage variables
        self.ils_pixels = None
        self.ils_sigmas = None
        
        # --- 4. Generate & Save ---
        self.btn_generate = QPushButton("🪄 Generate Ultimate Reference")
        self.btn_generate.setStyleSheet("background-color: #ff9800; color: white; font-weight: bold; font-size: 14px;")
        self.btn_generate.clicked.connect(self.apply_convolution)
        self.btn_generate.setMinimumHeight(int(50 * self._s))
        right_layout.addWidget(self.btn_generate)
        
        self.btn_save = QPushButton("💾 Save & Auto-Register to Main")
        self.btn_save.clicked.connect(self.save_reference)
        self.btn_save.setEnabled(False)
        self.btn_save.setMinimumHeight(int(40 * self._s))
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
            # 1. Smart header search: scan file text to find the line starting with "Pixel"
            header_row_idx = 0
            with open(filename, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f):
                    if line.strip().lower().startswith("pixel"):
                        header_row_idx = i
                        break
            
            # 2. Load data, skipping rows above the detected header
            df = pd.read_csv(filename, sep=r'\s+', skiprows=header_row_idx)
            
            # 3. Normalize column names (lowercase, strip underscores)
            clean_cols = [str(col).strip().lower().replace("_", "") for col in df.columns]
            df.columns = clean_cols
            
            # 4. Extract data
            if 'pixel' in clean_cols and 'abssigma(nm)' in clean_cols:
                self.ils_pixels = df['pixel'].values
                self.ils_sigmas = df['abssigma(nm)'].values
            elif len(df.columns) >= 4:
                # Fallback: force-extract column 1 (pixel) and column 4 (Sigma nm)
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
            # 1. Create high-resolution grid for accurate numerical integration
            hr_step = 0.002  
            hr_wave = np.arange(self.target_wavelengths.min() - 5.0, self.target_wavelengths.max() + 5.0, hr_step)
            
            # Map raw data onto the high-resolution grid
            f_raw = interp1d(self.raw_wave, self.raw_data, kind='linear', bounds_error=False, fill_value=0.0)
            hr_data = f_raw(hr_wave)
            
            lit_fwhm = self.spin_lit_fwhm.value()
            lit_sigma = lit_fwhm / 2.35482
            
            # 2. Allocate output array
            degraded_data = np.zeros(len(self.target_wavelengths))
            
            # 3. Interpolate FWHM profile over the full pixel range
            f_sigma = interp1d(self.ils_pixels.astype(float), self.ils_sigmas.astype(float), 
                               kind='linear', fill_value="extrapolate")
            pixel_indices = np.arange(len(self.target_wavelengths))
            target_sigmas = f_sigma(pixel_indices)
            
            # 4. Wavelength-Dependent Convolution (per-pixel Gaussian kernel)
            for i, target_w in enumerate(self.target_wavelengths):
                inst_sigma = target_sigmas[i]
                
                # Variance addition: σ_applied² = σ_inst² − σ_lit²
                # If the literature resolution is already coarser than our instrument,
                # we set added_var to a tiny positive number (no de-sharpening possible).
                if inst_sigma <= lit_sigma:
                    added_var = 1e-10   # Effectively no extra broadening
                else:
                    added_var = (inst_sigma**2) - (lit_sigma**2)
                
                kernel = (1.0 / np.sqrt(2 * np.pi * added_var)) * \
                         np.exp(-0.5 * ((hr_wave - target_w)**2) / added_var)
                
                degraded_data[i] = np.sum(hr_data * kernel) * hr_step
            
            self.final_ready_data = degraded_data
            self.gen_info = "Dynamic-ILS-Applied"
            
            # =========================================================
            # 5. Visualize results
            # =========================================================
            ax_top = self.fig.axes[0]     # Top graph
            ax_bottom = self.fig.axes[1]  # Bottom graph
            
            # Redraw top graph
            ax_top.clear()
            ax_top.plot(self.target_wavelengths, self.final_ready_data, 'r-', label="Ready Ref (Dynamic ILS)")
            ax_top.set_xlabel("Wavelength (nm)")
            ax_top.set_ylabel("Cross Section")
            ax_top.legend()
            
            
            # Redraw bottom graph
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
        
        # Graph object cache (key to anti-flicker rendering)
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
        self.init_tab_r_viewer()

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


    # [Tab 6] R Viewer — 거울 반사율 시계열 + 스펙트럼 뷰어
    # =========================================================
    def init_tab_r_viewer(self):
        self.tab_r = QWidget()
        lay = QVBoxLayout(self.tab_r)

        from PyQt6.QtWidgets import QLineEdit, QComboBox

        # ── 행1: R 결과 폴더 ──────────────────────────────────
        row1 = QHBoxLayout()
        self._r_dir_edit = QLineEdit()
        self._r_dir_edit.setPlaceholderText("R 결과 폴더  (R_Cold / R_Hot_ANs / R_Hot_PNs 포함)")
        btn_r = QPushButton("📂"); btn_r.setFixedWidth(30)
        btn_r.clicked.connect(lambda: self._r_pick(self._r_dir_edit))
        row1.addWidget(QLabel("결과 폴더:")); row1.addWidget(self._r_dir_edit, 4); row1.addWidget(btn_r)
        lay.addLayout(row1)

        # ── 행2: 원본 Cold .dat 폴더 ──────────────────────────
        row2 = QHBoxLayout()
        self._r_cold_edit = QLineEdit()
        self._r_cold_edit.setPlaceholderText("Cold 원본 폴더  (타임스탬프용, 없으면 파일명 날짜로 추정)")
        btn_c = QPushButton("📂"); btn_c.setFixedWidth(30)
        btn_c.clicked.connect(lambda: self._r_pick(self._r_cold_edit))
        row2.addWidget(QLabel("Cold 원본:")); row2.addWidget(self._r_cold_edit, 4); row2.addWidget(btn_c)
        lay.addLayout(row2)

        # ── 행3: 원본 Hot .dat 폴더 ───────────────────────────
        row3 = QHBoxLayout()
        self._r_hot_edit = QLineEdit()
        self._r_hot_edit.setPlaceholderText("Hot 원본 폴더  (타임스탬프용, 없으면 파일명 날짜로 추정)")
        btn_h = QPushButton("📂"); btn_h.setFixedWidth(30)
        btn_h.clicked.connect(lambda: self._r_pick(self._r_hot_edit))
        row3.addWidget(QLabel("Hot 원본:")); row3.addWidget(self._r_hot_edit, 4); row3.addWidget(btn_h)
        lay.addLayout(row3)

        # ── 행4: 컨트롤 ───────────────────────────────────────
        row4 = QHBoxLayout()
        btn_load = QPushButton("▶ 불러오기")
        btn_load.setStyleSheet("background-color:#4CAF50;color:white;font-weight:bold;")
        btn_load.clicked.connect(self._r_load_all)
        # 채널 가시성 체크박스
        self._r_chk = {}
        for ch, col in [("Cold","#1f77b4"), ("Hot ANs","#d62728"), ("Hot PNs","#ff7f0e")]:
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
        self._r_mode_cb.setToolTip("시계열·스펙트럼을 반사율(R) 또는 유효경로(Leff)로 전환")
        self._r_mode_cb.currentIndexChanged.connect(self._r_on_display_change)
        row4.addWidget(btn_load)
        row4.addWidget(QLabel("  채널:"))
        for chk in self._r_chk.values(): row4.addWidget(chk)
        row4.addWidget(QLabel("  단위:"))
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
            title="R 시계열  |  휠: Y줌  Ctrl+휠: X줌  우클릭: 이동  점 클릭: 스펙트럼",
            axisItems={'bottom': _date_ax})
        self._r_p_ts.setLabel('left',   'R (%)')
        self._r_p_ts.setLabel('bottom', 'Time (KST)')
        self._r_p_ts.showGrid(x=True, y=True, alpha=0.4)
        self._r_p_ts.addLegend(offset=(10, 10))

        # 채널별 커브
        _CH = {"Cold":"#1f77b4", "Hot ANs":"#d62728", "Hot PNs":"#ff7f0e"}
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
                                             title="R 스펙트럼  (시계열 점 클릭 시 표시)")
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

    def _r_pick(self, line_edit):
        from PyQt6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "폴더 선택")
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
        """label(YYYY-MM-DD-NNN)에 해당하는 unix timestamp 반환."""
        day_epoch = self._r_date_epoch(label)
        if raw_dir:
            src = label + ".dat"
            for candidate in [
                os.path.join(raw_dir, src),
                os.path.join(raw_dir, "-".join(label.split("-")[:3]), src),
            ]:
                if os.path.exists(candidate):
                    col1 = self._r_read_col1(candidate)
                    if col1 is not None:
                        return day_epoch + col1   # UTC초 → 절대 시각
        # 원본 없을 때: 파일명 시퀀스로 1시간 간격 추정
        try:
            seq = int(label.split("-")[3]) - 1
        except Exception:
            seq = 0
        return day_epoch + seq * 3600.0

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
            QMessageBox.warning(self, "경고", "R 결과 폴더를 선택하세요."); return

        sub = {
            "Cold":    (os.path.join(base, "R_Cold"),    cold_raw),
            "Hot ANs": (os.path.join(base, "R_Hot_ANs"), hot_raw),
            "Hot PNs": (os.path.join(base, "R_Hot_PNs"), hot_raw),
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
            f"총 {total}개 파일  ({'실제 시각' if has_real else '추정 시각 — 원본 폴더 지정 시 정확해짐'})")
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
        for ch in ["Cold", "Hot ANs", "Hot PNs"]:
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
            f"R 시계열  |  커서 근처: [{ch}] {lbl}  "
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

        # 1. Create plot frames only once (including Residual)
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

        # 2. Update data smoothly without recreating frames
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
        """
        Appends one new data point to each trend graph (Shift, Squeeze, RMS).

        Trend graphs keep the entire history in memory so the user can freely
        zoom and scroll without data being thrown away.  Auto-range is only
        applied along the X-axis (file index) to follow new data, while Y-axis
        zoom is left under user control.
        """
        idx = data.get('idx', 0)
        shift = data.get('shift', 0.0)
        squeeze = data.get('squeeze', 1.0)
        rms = data.get('rms', 0.0)
        self.x_data.append(idx)
        self.y_sh.append(shift)
        self.y_sq.append(squeeze)
        self.y_rms.append(rms)
        
        # Keep full dataset for free zoom/pan
        self.curve_sh.setData(self.x_data, self.y_sh)
        self.curve_sq.setData(self.x_data, self.y_sq)
        
        rms_data = np.array(self.y_rms)
        rms_data[rms_data <= 0] = 1e-9
        self.curve_rms.setData(self.x_data, rms_data)
        
        # Update Shift graph if in auto-range mode
        if self.p_sh.getViewBox().autoRangeEnabled(): 
            self.p_sh.enableAutoRange(axis='x', enable=True)
            
        # Update Squeeze graph if in auto-range mode
        if self.p_sq.getViewBox().autoRangeEnabled(): 
            self.p_sq.enableAutoRange(axis='x', enable=True)
            
        # Update RMS graph if in auto-range mode
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

# =============================================================================
# 7. Post-Processing & Export (Final Output)
# =============================================================================
class R_GeneratorDialog(QDialog):
    """
    BBCEAS Universal R-Curve Generator.

    Calculates the wavelength-dependent mirror reflectivity R(λ) using the
    difference in Rayleigh scattering cross-sections of two well-characterised gases.

    Physical principle (Washenfelder et al. 2008)
    ---------------------------------------------
    When light bounces between two high-reflectivity mirrors separated by distance d,
    the effective path length is L_eff = d / (1 − R).  By measuring two gases whose
    scattering is well-known (e.g., Zero-Air and Helium), we can solve for R(λ):

        ratio = I_gas2 / I_gas1
        R(λ)  = 1 − d · (ratio·α₂ − α₁) / (1 − ratio)

    The resulting R-curve is saved as a CSV file and loaded into the main engine
    before analysis to enable accurate ppb-level concentration retrieval.
    """
    def __init__(self, parent, wavelengths):
        super().__init__(parent)
        self.setWindowTitle("🎡 BBCEAS Universal R-Curve Generator")
        _s = _ui_scale()
        self.resize(int(550 * _s), int(650 * _s))
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

        # Preset table: (C, k, reference)
        PRESETS = {
            "Zero-Air (ZA/Air)":    (1.100065e-15, -4.1656, "Bucholtz (1995) J. Atmos. Sci. 52, 1705"),
            "Nitrogen (N2)":        (1.2577e-15,   -4.1814, "Naus & Ubachs (2000) J. Mol. Spectrosc. 203, 106"),
            "Helium (He)":          (1.336e-17,    -4.1287, "Ityaksov et al. (2008) Chem. Phys. Lett. 462, 31"),
            "Argon (Ar)":           (4.50e-17,     -4.0564, "Ityaksov et al. (2008) Chem. Phys. Lett. 462, 31"),
            "Carbon Dioxide (CO2)": (6.50e-16,     -4.26,   "Sneep & Ubachs (2005) J. Quant. Spectrosc. 92, 293 (approx.)"),
            "Neon (Ne)":            (2.68e-18,     -4.12,   "Sneep & Ubachs (2005) J. Quant. Spectrosc. 92, 293 (approx.)"),
            "Krypton (Kr)":         (2.01e-16,     -4.02,   "Sneep & Ubachs (2005) J. Quant. Spectrosc. 92, 293 (approx.)"),
            "Custom Input":         (None,          None,    ""),
        }

        # 2. Gas Slot Generator (Returns the constructed GroupBox and its widgets)
        def create_gas_slot(slot_num):
            box = QGroupBox(f"Gas Slot {slot_num} Settings")
            vbox = QVBoxLayout()

            combo = QComboBox()
            combo.addItems(list(PRESETS.keys()))

            # C / k fields — always visible; pre-filled for presets, blank for Custom
            ck_widget = QWidget()
            ck_hbox = QHBoxLayout(ck_widget)
            ck_hbox.setContentsMargins(0, 0, 0, 0)
            txt_c = QLineEdit()
            txt_c.setPlaceholderText("C  (e.g. 1.1e-15)")
            txt_k = QLineEdit()
            txt_k.setPlaceholderText("k  (e.g. -4.17)")
            ck_hbox.addWidget(QLabel("C:"))
            ck_hbox.addWidget(txt_c)
            ck_hbox.addWidget(QLabel("k:"))
            ck_hbox.addWidget(txt_k)

            # Always-visible formula explanation
            lbl_ck_info = QLabel(
                "<b>σ(λ) = C · λᵏ</b> &nbsp;[cm²]<br>"
                "C : scattering coefficient — gas-specific constant; larger molecules / higher polarity → larger C<br>"
                "k : wavelength exponent — typically −4 ~ −4.3; pure Rayleigh gives exactly −4"
            )
            lbl_ck_info.setStyleSheet("color: #333; font-size: 10px; background: #f5f5f5; padding: 4px; border-radius: 3px;")
            lbl_ck_info.setWordWrap(True)

            # Reference label shown below C/k fields
            lbl_ref = QLabel("")
            lbl_ref.setStyleSheet("color: #555; font-size: 10px; font-style: italic;")
            lbl_ref.setWordWrap(True)

            def on_combo_changed():
                name = combo.currentText()
                c_val, k_val, ref = PRESETS[name]
                if c_val is not None:
                    txt_c.setText(f"{c_val:.6e}")
                    txt_k.setText(str(k_val))
                    txt_c.setStyleSheet("")
                    txt_k.setStyleSheet("")
                    lbl_ref.setText(f"Ref: {ref}")
                else:
                    txt_c.clear()
                    txt_k.clear()
                    lbl_ref.setText("Enter C and k manually.")

            combo.currentIndexChanged.connect(lambda _: on_combo_changed())
            on_combo_changed()  # Populate fields for the default selection

            btn_file = QPushButton(f"📂 Load Gas {slot_num} Spectrum")
            btn_file.clicked.connect(lambda: self.load_data(slot_num))

            lbl_file = QLabel(f"Gas {slot_num}: No file selected")
            lbl_file.setStyleSheet("color: gray; font-size: 11px;")

            vbox.addWidget(QLabel("<b>Select Gas Type:</b>"))
            vbox.addWidget(combo)
            vbox.addWidget(ck_widget)
            vbox.addWidget(lbl_ck_info)
            vbox.addWidget(lbl_ref)
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
        r"""
        Returns the Rayleigh scattering cross-section σ(λ) [cm²] using
        σ = C · λ^k  (λ in nm), where C and k are read directly from the UI
        fields so the user can override preset values at any time.
        """
        try:
            c_val = float(txt_c.text())
            k_val = float(txt_k.text())
        except ValueError:
            gas = combo.currentText()
            raise ValueError(
                f"C or k value for '{gas}' is not a valid number.\n"
                "Please check the input fields."
            )
        return c_val * (self.wl ** k_val)

    def calculate_r(self):
        """Calculates the mirror reflectivity R(λ) and prompts the user to save it as a CSV."""
        if self.data1 is None or self.data2 is None:
            QMessageBox.warning(self, "Missing Data", "Please load spectra for both Gas 1 and Gas 2.")
            return

        if self.wl is None:
            QMessageBox.warning(
                self, "No Wavelength Calibration",
                "Wavelength calibration has not been loaded.\n\n"
                "Please load or run the Wavelength Calibration Tool first,\n"
                "then re-open the R-Curve Generator."
            )
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

            # Validate R range: R must be in (0, 1) for a physically real mirror.
            # Values outside this range indicate noise, division-by-zero near ratio=1,
            # or a mis-matched gas pair. Clip and warn so downstream analysis is safe.
            n_bad = int(np.sum((r_curve < 0) | (r_curve > 1)))
            if n_bad > 0:
                r_curve = np.clip(r_curve, 0.0, 1.0)
                QMessageBox.warning(
                    self, "Out-of-Range Pixels",
                    f"{n_bad} pixel(s) had R < 0 or R > 1 and were clipped to [0, 1].\n\n"
                    "This typically occurs at spectral edges where I₂/I₁ ≈ 1 "
                    "(ratio denominator near zero) or where signal-to-noise is poor.\n"
                    "Check that the correct gases are assigned to each slot "
                    "and that the spectra cover the same wavelength range."
                )

            gas1 = self.combo1.currentText().split(' ')[0]
            gas2 = self.combo2.currentText().split(' ')[0]
            import datetime
            date_str = datetime.datetime.now().strftime("%Y%m%d")

            default_fname = f"RCurve_{gas1}_vs_{gas2}_d{cavity_len}cm_{date_str}.csv"

            # Save the result
            save_path, _ = QFileDialog.getSaveFileName(self, "Save R-Curve", default_fname, "CSV (*.csv)")

            if save_path:
                pd.DataFrame({'Wavelength': self.wl, 'Reflectivity': r_curve}).to_csv(save_path, index=False)
                self.r_curve_result = r_curve  # Expose result so caller can load it directly
                QMessageBox.information(self, "Success", "Reflectivity curve saved successfully!")
                self.accept()
                
        except Exception as e:
            QMessageBox.critical(self, "Calculation Error", f"Failed to calculate R(λ):\n{e}")

# PostProcessDialog: functionality superseded by save() in app_window.py.
# Retained here as a stub so that any external scripts importing this class
# do not break with an ImportError.
class _RTrendWorker(QThread):
    """백그라운드에서 r_trend_monitor.main()을 실행."""
    log      = pyqtSignal(str)
    finished = pyqtSignal(str)   # 결과 폴더 경로

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg

    def run(self):
        import io as _io
        try:
            import r_trend_monitor as rtm
            cfg = self.cfg

            # 사용자 설정 오버라이드
            rtm.COLD_DIR      = cfg.get("cold_dir", "")
            rtm.HOT_DIR       = cfg.get("hot_dir",  "")
            rtm.WAVE_CAL_COLD = cfg.get("wl_cold",  "")
            rtm.WAVE_CAL_HOT  = cfg.get("wl_hot",   "")
            rtm.OUTPUT_DIR    = cfg.get("out_dir",  ".")
            rtm.COLD_FILES    = None
            rtm.HOT_FILES     = None
            rtm.SHOW_PLOT     = False

            # stdout 캡처 → log 시그널
            import sys as _sys
            old_stdout = _sys.stdout
            _sys.stdout = buf = _io.StringIO()
            try:
                rtm.main()
            finally:
                _sys.stdout = old_stdout

            for line in buf.getvalue().splitlines():
                self.log.emit(line)

            self.finished.emit(rtm.OUTPUT_DIR)

        except Exception as e:
            import traceback
            self.log.emit(f"[오류] {e}\n{traceback.format_exc()}")
            self.finished.emit("")


class RTrendMonitorDialog(QDialog):
    """R Trend Monitor 설정 + 실행 + 로그 표시 다이얼로그."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("R Trend Monitor — 거울 반사율 시계열")
        self.resize(720, 560)
        self._worker = None
        self._init_ui()

    def _pick_dir(self, line_edit):
        d = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if d:
            line_edit.setText(d)

    def _pick_file(self, line_edit):
        f, _ = QFileDialog.getOpenFileName(
            self, "파일 선택", "", "텍스트 파일 (*.txt *.dat *.csv);;모든 파일 (*)")
        if f:
            line_edit.setText(f)

    def _init_ui(self):
        from PyQt6.QtWidgets import QTextEdit
        main = QVBoxLayout(self)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        def row_dir(label, attr):
            le = QLineEdit()
            btn = QPushButton("…"); btn.setFixedWidth(32)
            btn.clicked.connect(lambda: self._pick_dir(le))
            h = QHBoxLayout(); h.addWidget(le); h.addWidget(btn)
            w = QWidget(); w.setLayout(h)
            form.addRow(label, w)
            setattr(self, attr, le)

        def row_file(label, attr):
            le = QLineEdit()
            btn = QPushButton("…"); btn.setFixedWidth(32)
            btn.clicked.connect(lambda: self._pick_file(le))
            h = QHBoxLayout(); h.addWidget(le); h.addWidget(btn)
            w = QWidget(); w.setLayout(h)
            form.addRow(label, w)
            setattr(self, attr, le)

        row_dir("Cold 데이터 폴더:",      "_le_cold_dir")
        row_dir("Hot 데이터 폴더:",       "_le_hot_dir")
        row_file("Cold 파장 보정 파일:",  "_le_wl_cold")
        row_file("Hot 파장 보정 파일:",   "_le_wl_hot")
        row_dir("결과 저장 폴더:",        "_le_out_dir")
        self._le_out_dir.setText(".")
        main.addLayout(form)

        btn_run = QPushButton("▶  계산 시작")
        btn_run.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold; height: 36px;")
        btn_run.clicked.connect(self._run)
        main.addWidget(btn_run)
        self._btn_run = btn_run

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFontFamily("Consolas")
        self._log.setFontPointSize(9)
        main.addWidget(self._log)

    def _run(self):
        cfg = {
            "cold_dir": self._le_cold_dir.text().strip(),
            "hot_dir":  self._le_hot_dir.text().strip(),
            "wl_cold":  self._le_wl_cold.text().strip(),
            "wl_hot":   self._le_wl_hot.text().strip(),
            "out_dir":  self._le_out_dir.text().strip() or ".",
        }
        if not cfg["cold_dir"] and not cfg["hot_dir"]:
            QMessageBox.warning(self, "입력 오류", "Cold 또는 Hot 데이터 폴더를 지정해주세요.")
            return

        self._log.clear()
        self._btn_run.setEnabled(False)
        self._worker = _RTrendWorker(cfg)
        self._worker.log.connect(self._log.append)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_done(self, out_dir: str):
        self._btn_run.setEnabled(True)
        if out_dir:
            self._log.append(f"\n✅ 완료 → 결과 폴더: {out_dir}")
            QMessageBox.information(self, "완료", f"R Trend Monitor 완료!\n결과 폴더:\n{out_dir}")
        else:
            self._log.append("\n❌ 오류 발생 — 위 로그를 확인하세요.")
