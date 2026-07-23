"""gui/ui_dialogs_calib.py
교정 다이얼로그: NavigationHelper, WavelengthCalibrationDialog, RangeSelectorDialog
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
        """Extract data around the peak, apply Gaussian fit, and calculate FWHM.

        Window is auto-detected from the half-max crossing points so that broad
        ILS peaks (Cold, FWHM ~3-4 nm = ~76 px) and narrow ILS peaks (Hot,
        FWHM ~0.7 nm = ~15 px) are both handled correctly.
        """
        try:
            full = np.asarray(intensities, dtype=float)
            pk   = int(np.clip(round(peak_pixel), 0, len(full) - 1))

            # ── Step 1: rough baseline & half-max scan ────────────────────────
            # Use a wide context (±200 px) just to estimate the local baseline.
            ctx_start = max(0, pk - 200)
            ctx_end   = min(len(full), pk + 201)
            ctx       = full[ctx_start:ctx_end]
            baseline  = float(np.percentile(ctx, 10))
            peak_val  = float(full[pk])
            amplitude = peak_val - baseline
            if amplitude <= 0:
                return None, None

            half_level = baseline + amplitude * 0.5

            # Walk outward from peak to find half-max crossing points
            left_hm = pk
            while left_hm > 0 and full[left_hm] > half_level:
                left_hm -= 1

            right_hm = pk
            while right_hm < len(full) - 1 and full[right_hm] > half_level:
                right_hm += 1

            # Window = 1.5 × half-width on each side (to include peak tails for
            # Gaussian fit), but at least 15 px and at most 300 px.
            half_width = max(right_hm - pk, pk - left_hm, 1)
            window = max(15, min(300, int(half_width * 1.5)))

            # ── Step 2: extract fit region ────────────────────────────────────
            start = max(0, pk - window)
            end   = min(len(full), pk + window + 1)
            x_data = np.arange(start, end, dtype=float)
            y_data = full[start:end]

            # ── Step 3: initial estimates ─────────────────────────────────────
            offset_guess = baseline
            a_guess      = amplitude
            mu_guess     = float(pk)
            # sigma from half-max walk (in pixels)
            sigma_guess  = max(0.5, half_width / 2.3548)
            sigma_guess  = min(sigma_guess, window * 0.8)

            p0_guess  = [a_guess, mu_guess, sigma_guess, offset_guess]
            bounds_lo = [0.0,  float(start), 0.3,            -np.inf]
            bounds_hi = [np.inf, float(end), float(window),   np.inf]

            # ── Step 4: Gaussian fit ──────────────────────────────────────────
            popt, _ = curve_fit(
                self._gaussian_model, x_data, y_data,
                p0=p0_guess,
                bounds=(bounds_lo, bounds_hi),
                maxfev=8000,
            )
            a, mu, sigma, offset = popt

            # ── Step 5: convert sigma → FWHM ─────────────────────────────────
            # FWHM = 2.3548 × σ  (standard Gaussian relation)
            fwhm_pixels = 2.3548 * abs(sigma)

            # ── Step 6: FWHM in nm using local polynomial dispersion ──────────
            fwhm_nm = None
            if current_wavelengths is not None:
                wl    = np.asarray(current_wavelengths)
                mu_i  = int(np.clip(round(mu), 1, len(wl) - 2))
                dispersion = (wl[mu_i + 1] - wl[mu_i - 1]) / 2.0  # nm/px (local)
                if dispersion > 0:
                    fwhm_nm = fwhm_pixels * dispersion

            return fwhm_pixels, fwhm_nm

        except Exception as e:
            print(f"FWHM calculation failed (noisy data or non-peak): {e}")
            return None, None

    def load_spectrum(self):
        """Load calibration spectrum dynamically using a robust header mapping for LightField."""
        filename, _ = QFileDialog.getOpenFileName(self, "Open Lamp Spectrum", dlg_dir("lamp"), "Data Files (*.dat *.txt *.csv)")
        dlg_dir("lamp", filename)
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
        _start = os.path.join(dlg_dir("calib_save"), suggested_name) if dlg_dir("calib_save") else suggested_name
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save & Apply Calibration", _start, filters
        )
        dlg_dir("calib_save", save_path)

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

        _start = os.path.join(dlg_dir("calib_save"), suggested_name) if dlg_dir("calib_save") else suggested_name
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save FWHM & Sigma Data", _start, "Text Files (*.txt);;CSV Files (*.csv)"
        )
        dlg_dir("calib_save", save_path)

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
    apply_channel = pyqtSignal(int, float, float, bool)   # (channel, lo, hi, is_nm)

    def __init__(self, data_path, pixel_min, pixel_max, engine, channels=None,
                 channel_paths=None, active_channel=None, channel_files=None,
                 chosen_files=None, channel_ranges=None):
        super().__init__()
        self.setWindowTitle("🔍 Fit Range Selector")
        _s = _ui_scale()
        self.resize(int(900 * _s), int(600 * _s))

        # --- Initialize Analysis Data & State ---
        self.engine = engine
        self.data_path = data_path
        self.min_sel = int(pixel_min)
        self.max_sel = int(pixel_max)
        self._channels = channels or []   # [(ch, label), ...] — 채널별 적용 시
        self._channel_paths = channel_paths or {}   # {ch: 대표 스펙트럼 경로}
        self._channel_files = channel_files or {}   # {ch: 전체 파일 리스트} — File콤보/★Score용
        # {ch: 고정 파일} — ★Score/수동 선택이 채널전환·재실행에도 유지되게(app_window 소유 dict).
        self._chosen_files = chosen_files if chosen_files is not None else {}
        # {ch: (lo, hi, is_nm)} — 채널별 핏레인지. 채널 전환 시 그 채널 범위를 표시하고,
        # 드래그하면 '현재 채널'것만 갱신(예전엔 min_sel/max_sel가 전역이라 전 채널이
        # 마지막으로 만진 범위를 공유했다).
        self._channel_ranges = dict(channel_ranges) if channel_ranges else {}
        self._active_channel = active_channel
        self._ref_line = None
        self._sel_lo = self._sel_hi = None
        self._sel_is_nm = False

        # 활성 채널에 고정된 파일이 있으면 그걸로 시작(대표파일 대신)
        pinned = self._pick_file_for_channel(active_channel)
        if pinned and os.path.isfile(pinned):
            self.data_path = pinned

        self.x = None
        self.y = None
        self.span = None

        self.setup_ui()
        self.load_plot()

    def _sync_range_from_channel(self):
        """현재 채널의 저장된 핏레인지 → min_sel/max_sel(이 파일 파장축 기준 픽셀).
        nm로 보관하므로 채널별 wavecal 차이가 자동 반영된다. 없으면 그대로 둔다."""
        try:
            chi = int(self._current_channel())
        except (TypeError, ValueError):
            return
        rng = self._channel_ranges.get(chi)
        if not rng:
            return
        lo_v, hi_v, is_nm = rng
        if is_nm and getattr(self, '_wave_mode', False):
            w = np.asarray(self.x, dtype=float)
            if w.size:
                a = int(np.argmin(np.abs(w - float(lo_v))))
                b = int(np.argmin(np.abs(w - float(hi_v))))
                self.min_sel, self.max_sel = (a, b) if a <= b else (b, a)
        elif not is_nm:
            self.min_sel = int(min(lo_v, hi_v))
            self.max_sel = int(max(lo_v, hi_v))

    def _pick_file_for_channel(self, ch):
        """채널의 표시 파일 선택: 고정(★Score/수동)이 있으면 우선, 없으면 대표(중간) 파일."""
        try:
            chi = int(ch)
        except (TypeError, ValueError):
            return None
        chosen = self._chosen_files.get(chi)
        files = self._channel_files.get(chi, [])
        if chosen and chosen in files:
            return chosen
        return self._channel_paths.get(chi)

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

        # Δα: 전 파장 고역통과(가우시안 베이스라인 제거)로 차등구조만 표시 — NO2
        # 레퍼런스와 피크 위치를 1:1로 대조하며 범위를 고를 수 있게. 표시 전용.
        # CH3처럼 광대역이 구조의 수백 배인 α도 이걸 켜면 구조가 드러난다.
        self.chk_diff = QCheckBox("Δα (detrend)")
        self.chk_diff.setToolTip(
            "Alpha display only: remove the broadband baseline (Gaussian high-pass, ~4nm)\n"
            "over the FULL spectrum and show the differential structure — same idea as the\n"
            "DOAS fit's polynomial. Defined at all wavelengths, so wheel zoom-out shows\n"
            "structure beyond the fit range too. Lets you match peaks 1:1 against the\n"
            "reference overlay. Display-only; the actual fit is unaffected.")
        self.chk_diff.setChecked(True)   # 알파 열면 바로 구조가 보이게 기본 ON (raw α는 체크 해제)
        self.chk_diff.toggled.connect(lambda _c: self.load_plot())
        top_layout.addWidget(self.chk_diff)

        # 적용 채널 — 선택한 범위를 이 채널의 nm 범위로 설정(멀티채널 시)
        self.combo_ch = None
        if self._channels:
            top_layout.addSpacing(12)
            top_layout.addWidget(QLabel("Channel:"))
            self.combo_ch = QComboBox()
            for ch, lbl in self._channels:
                self.combo_ch.addItem(lbl, ch)
            # 기본값 = 활성 채널
            if self._active_channel is not None:
                for i in range(self.combo_ch.count()):
                    if self.combo_ch.itemData(i) == self._active_channel:
                        self.combo_ch.setCurrentIndex(i); break
            # 채널 바꾸면 그 채널 대표 스펙트럼으로 그래프 갱신
            self.combo_ch.currentIndexChanged.connect(self._on_channel_combo)
            top_layout.addWidget(self.combo_ch)

        # 파일 선택 + ★Score: 대표파일(기본=중간)을 바꿔볼 수 있고, ★Score가 이 채널의
        # 파일들을 NO2 정렬 상관으로 채점해 최적 파일을 추천·자동선택한다.
        # 날짜 하드코딩 flag 없이, 06-17(+85px) 같은 밀린 날이 낮은 점수로 드러남.
        self.combo_file = None
        self.btn_score = None
        if self._channel_files:
            top_layout.addSpacing(12)
            top_layout.addWidget(QLabel("File:"))
            self.combo_file = QComboBox()
            self.combo_file.setMinimumWidth(230)
            self.combo_file.setToolTip("Representative file to display (default: middle of the list)")
            self.combo_file.currentIndexChanged.connect(self._on_file_combo)
            top_layout.addWidget(self.combo_file)
            self.btn_score = QPushButton("★ Score")
            self.btn_score.setToolTip(
                "Score every alpha file of this channel: correlation r of its median Δα\n"
                "against the NO2 reference within the current pixel band.\n"
                "High r = NO2 structure present & wavelength-aligned. Low r = shifted day\n"
                "(e.g. cold 06-17 +85px), contaminated, or no NO2. Best file is auto-selected.\n"
                "Data-driven recommendation — nothing is deleted or flagged.")
            self.btn_score.clicked.connect(self._score_files)
            top_layout.addWidget(self.btn_score)
            self._populate_file_combo()

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
        # Apply는 범위만 반영하고 창은 열어둔다(여러 채널·범위를 이어서 조정 가능).
        # 실제 닫기는 Close 버튼으로만.
        self.b_apply.clicked.connect(self.emit_apply)
        # 적용 피드백(창이 안 닫히므로 반영됐는지 알 수 있게)
        self.lbl_applied = QLabel("")
        self.lbl_applied.setStyleSheet("color:#2E7D32; font-weight:bold; padding:0 8px;")

        self.b_close = QPushButton("Close")
        self.b_close.clicked.connect(self.reject)

        btns_layout.addWidget(self.b_apply)
        btns_layout.addWidget(self.lbl_applied, 1)
        btns_layout.addWidget(self.b_close)
        self.main_layout.addLayout(btns_layout)

    def _load_araon_spectrum_for_display(self):
        """Read the brightest spectrum from an Araon mega-matrix file for display.

        Scans the first 500 rows and returns the row whose CH1 channel has the
        highest peak intensity. This is flag-agnostic so the display works
        regardless of whether ambient scans are flagged 0, 1, or any other value.
        Returns (pixel_idx, intensity).
        """
        _META  = DataIO._META_COLS   # 2053
        _NPIX  = DataIO._CH_PIXELS   # 2048
        col_start, col_end = _META, _META + _NPIX

        best_spectrum = None
        best_max      = -np.inf

        try:
            with open(self.data_path, 'r', encoding='utf-8', errors='replace') as fh:
                for i, line in enumerate(fh):
                    if i > 500:
                        break
                    tokens = line.strip().split('\t')
                    if len(tokens) < col_end:
                        continue
                    try:
                        raw = np.array([float(t) if t.strip() else np.nan
                                        for t in tokens[col_start:col_end]])
                    except Exception:
                        continue

                    fin = np.isfinite(raw)
                    if fin.sum() < 500:
                        continue

                    row_max = float(np.nanmax(raw))
                    if row_max > best_max:
                        best_max      = row_max
                        best_spectrum = raw.copy()
        except Exception as e:
            raise RuntimeError(f"Cannot read Araon file for vis.select: {e}")

        if best_spectrum is None:
            raise RuntimeError("No usable scan found in Araon file")

        best_spectrum = np.where(np.isfinite(best_spectrum), best_spectrum, 0.0)
        return np.arange(len(best_spectrum)), best_spectrum

    @staticmethod
    def _is_alpha_trace(path):
        """alpha_trace.dat 인지(헤더 '# wavelength_nm:' 존재)."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for _ in range(40):
                    l = f.readline()
                    if not l:
                        break
                    if l.startswith("# wavelength_nm:"):
                        return True
        except Exception:
            pass
        return False

    def _load_alpha_trace_for_display(self):
        """alpha_trace.dat 전체 스캔의 '중앙값 α 스펙트럼'을 표시용으로 로드.

        (기존엔 첫 데이터행 1개만 그렸는데, 첫 스캔은 정착스캔(빈 전환 직후 캐비티
        미충전)인 경우가 잦아 파일 내 최악의 노이즈 스캔이 그대로 표시되곤 했다 —
        실측 hot/ch2 8파일 중 4파일에서 row0가 최악/차악. 중앙값은 정착스캔을
        자동으로 무시하고 노이즈가 ~√N배 줄어 NO2 흡수구조가 보인다.
        파서는 Result Lab과 공용(gui.result_viewer_io.read_alpha_trace).)

        반환 (pixel_idx_for_ref, alpha, file_wave_nm):
          · file_wave_nm : 파일 자체 헤더 파장(표시 x축)
          · pixel_idx_for_ref : 파일 파장 → engine 픽셀 매핑(레퍼런스 overlay 정렬용).
            engine 파장축이 없으면 0..n-1.
        """
        from gui.result_viewer_io import read_alpha_trace
        wave, _ids, a = read_alpha_trace(self.data_path)
        if a.size == 0:
            raise RuntimeError("No alpha_trace data rows found")
        alpha = np.nanmedian(a, axis=0)
        self._alpha_nscans = int(a.shape[0])   # load_plot 레전드 라벨용
        wax = getattr(self.engine, "_wave_axis", None)
        if wax is not None and len(wave):
            wax = np.asarray(wax, dtype=float).flatten()
            from scipy.interpolate import interp1d
            px_of = interp1d(wax, np.arange(len(wax)), bounds_error=False, fill_value="extrapolate")
            eng_px = np.asarray(px_of(wave), dtype=float)
        else:
            eng_px = np.arange(len(alpha), dtype=float)
        return eng_px, alpha, wave

    def _current_channel(self):
        if getattr(self, 'combo_ch', None):
            return self.combo_ch.currentData()
        return self._active_channel

    def _populate_file_combo(self):
        """File 콤보를 현재 채널의 파일 리스트로 채우고 현재 파일을 선택 표시."""
        if getattr(self, 'combo_file', None) is None:
            return
        ch = self._current_channel()
        try:
            files = self._channel_files.get(int(ch), []) if ch is not None else []
        except (TypeError, ValueError):
            files = []
        self.combo_file.blockSignals(True)
        self.combo_file.clear()
        for f in files:
            self.combo_file.addItem(os.path.basename(f), f)
        if self.data_path in files:
            self.combo_file.setCurrentIndex(files.index(self.data_path))
        self.combo_file.blockSignals(False)

    def _on_file_combo(self, _idx):
        """File 콤보에서 다른 파일 선택 → 그 파일로 그래프 갱신 + 이 채널의 고정 파일로 기록."""
        if getattr(self, 'combo_file', None) is None:
            return
        p = self.combo_file.currentData()
        if not p:
            return
        ch = self._current_channel()
        try:
            self._chosen_files[int(ch)] = p   # 채널별 고정(재실행에도 유지)
        except (TypeError, ValueError):
            pass
        if p != self.data_path:
            self.data_path = p
            self.load_plot()

    def _score_files(self):
        """현재 채널의 알파 파일들을 채점: 현재 픽셀밴드에서 median Δα vs NO2 레퍼런스
        상관 r. 콤보 라벨에 점수를 달고 최고점 파일을 자동 선택한다.
        r 낮음 = 파장 밀림(예: 콜드 06-17 +85px)·오염·NO2 부재 — 날짜 하드코딩 없이
        데이터로 걸러진다. 원본은 건드리지 않음(추천만)."""
        from gui.result_viewer_io import read_alpha_trace
        ch = self._current_channel()
        try:
            files = self._channel_files.get(int(ch), []) if ch is not None else []
        except (TypeError, ValueError):
            files = []
        if not files or self.btn_score is None:
            return
        ref_name = 'NO2' if 'NO2' in self.engine.interpolators else \
                   (next(iter(self.engine.interpolators), None))
        if ref_name is None:
            self.btn_score.setText("★ no ref")
            return
        ref = np.asarray(self.engine.interpolators[ref_name](np.arange(2048, dtype=float)),
                         dtype=float)

        def _dt_idx(v, band):
            x = np.arange(len(band), dtype=float)
            vv = np.asarray(v, dtype=float)[band]
            fin = np.isfinite(vv)
            if int(fin.sum()) < 20:
                return None
            c = np.polyfit(x[fin], vv[fin], 5)
            out = np.full_like(vv, np.nan)
            out[fin] = vv[fin] - np.polyval(c, x[fin])
            return out

        scores = []
        for i, f in enumerate(files):
            self.btn_score.setText(f"★ {i + 1}/{len(files)}")
            QApplication.processEvents()
            s = None
            try:
                if "alpha_trace" in os.path.basename(f).lower() or self._is_alpha_trace(f):
                    _w, _ids, a = read_alpha_trace(f)
                    if a.size:
                        y = np.nanmedian(a, axis=0)
                        n = min(len(y), len(ref))
                        lo, hi = sorted((min(self.min_sel, n - 1), min(self.max_sel, n - 1)))
                        band = np.arange(lo, hi + 1)
                        dy = _dt_idx(y[:n], band)
                        dr = _dt_idx(ref[:n], band)
                        if dy is not None and dr is not None:
                            fin = np.isfinite(dy) & np.isfinite(dr)
                            if int(fin.sum()) > 20:
                                s = float(np.corrcoef(dy[fin], dr[fin])[0, 1])
            except Exception:
                s = None
            scores.append(s)
        self.btn_score.setText("★ Score")

        best_i, best_s = None, None
        self.combo_file.blockSignals(True)
        for k, (f, s) in enumerate(zip(files, scores)):
            base = os.path.basename(f)
            self.combo_file.setItemText(k, f"r={s:+.2f}  {base}" if s is not None else f"—  {base}")
            if s is not None and (best_s is None or s > best_s):
                best_i, best_s = k, s
        self.combo_file.blockSignals(False)
        if best_i is not None:
            # 최고점 파일을 이 채널의 고정 파일로 기록(재실행·채널전환에도 유지)
            try:
                self._chosen_files[int(ch)] = files[best_i]
            except (TypeError, ValueError):
                pass
            if best_i != self.combo_file.currentIndex():
                self.combo_file.setCurrentIndex(best_i)   # → _on_file_combo가 로드
            else:
                self.data_path = files[best_i]
                self.load_plot()

    def _on_channel_combo(self, _idx):
        """'적용 채널' 변경 → 그 채널의 대표 스펙트럼으로 그래프 재로딩."""
        if not self.combo_ch:
            return
        ch = self.combo_ch.currentData()
        p = self._pick_file_for_channel(ch)   # 고정(★Score/수동) 우선, 없으면 대표
        if p and p != self.data_path:
            self.data_path = p
        self._populate_file_combo()
        self.load_plot()

    def load_plot(self):
        """Loads selected data, plots it on a nm axis (if calibration available), and activates SpanSelector."""
        try:
            file_wave = None
            plot_label = 'Measured Spectrum'
            is_alpha = False
            self._diff_active = False   # update_ref가 참조: Δα 모드면 레퍼런스를 같은 축에 스케일 오버레이
            if "alpha_trace" in os.path.basename(self.data_path).lower() or self._is_alpha_trace(self.data_path):
                is_alpha = True
                pixel_idx, intensity_raw, file_wave = self._load_alpha_trace_for_display()
                plot_label = f'α median ({getattr(self, "_alpha_nscans", 0)} scans)'
                if getattr(self, 'chk_diff', None) and self.chk_diff.isChecked():
                    xd = file_wave if file_wave is not None else np.asarray(pixel_idx, float)
                    intensity_raw = self._detrend_band(xd, intensity_raw)
                    plot_label = f'Δα detrend ({getattr(self, "_alpha_nscans", 0)} scans)'
                    self._diff_active = True
            elif DataIO.is_araon_mega_matrix(self.data_path):
                pixel_idx, intensity_raw = self._load_araon_spectrum_for_display()
            else:
                pixel_idx, intensity_raw = DataIO.load_measurement(self.data_path, pixel_min=0)

            self.y = intensity_raw
            self._pixel_idx = pixel_idx   # 레퍼런스 평가용 픽셀(alpha면 engine 픽셀 매핑)

            # 파장축: alpha는 파일 자체 헤더 파장, 그 외 engine._wave_axis
            wave = file_wave
            if wave is None:
                wave = getattr(self.engine, '_wave_axis', None)
                if wave is not None:
                    wave = np.asarray(wave, dtype=float).flatten()
            if wave is not None and len(wave) == len(intensity_raw):
                self.x = wave
                self._wave_mode = True
                xlabel = "Wavelength (nm)"
            else:
                self.x = pixel_idx
                self._wave_mode = False
                xlabel = "Pixel Index"

            # 현재 채널의 핏레인지를 '이 채널의 파장축'에 매핑 → min_sel/max_sel 갱신.
            # 채널마다 wavecal이 달라 같은 nm도 픽셀이 다르므로 nm 기준으로 보관·환산한다.
            self._sync_range_from_channel()

            if self._wave_mode:
                n = len(self.x)
                x0 = self.x[min(self.min_sel, n - 1)]
                x1 = self.x[min(self.max_sel, n - 1)]
            else:
                x0, x1 = self.min_sel, self.max_sel

            self.ax.clear()
            self.ax.plot(self.x, self.y, 'k-', alpha=0.6, label=plot_label)
            # 파란 'Current Range' 스팬 — 드래그(on_select)로 갱신되게 참조 보관
            self._range_span = self.ax.axvspan(x0, x1, alpha=0.15, color='steelblue',
                                               label='Current Range')
            self.ax.set_xlabel(xlabel)
            self.ax.legend(loc='upper right', fontsize=8)

            # Activate Range Selector (Semi-transparent yellow box)
            self.span = SpanSelector(
                self.ax, self.on_select, 'horizontal', useblit=True,
                props=dict(alpha=0.3, facecolor='yellow')
            )

            # Update initial reference overlay (also calls canvas.draw())
            self.update_ref(self.combo.currentText())

            # 데이터가 실제로 있는 파장대로 줌(패딩/외삽으로 생긴 0 구간 제외)
            # → 0~500 전체가 아니라 400~500처럼 신호 있는 밴드에 맞춤
            self._zoom_x_to_data()
            # α/Δα 표시면 현재 핏레인지 밴드로 x·y 추가 줌 — 무광 가장자리 노이즈가
            # NO2 흡수구조(~1e-8)의 수십~수백 배라 풀스케일에선 구조가 납작해짐.
            # (Δα는 전 파장에 정의되므로 여기서 줌아웃하면 밴드 밖 구조도 보인다)
            if is_alpha:
                self._zoom_alpha_to_band(x0, x1)

        except Exception as e:
            # Surface the failure ON the canvas instead of silently leaving it blank
            # (the "창은 뜨는데 그래프가 안 뜸" symptom was a swallowed load error).
            import traceback
            traceback.print_exc()
            try:
                self.ax.clear()
                self.ax.text(0.5, 0.5, f"Data load failed:\n{e}",
                             ha='center', va='center', transform=self.ax.transAxes,
                             color='red', fontsize=10, wrap=True)
                self.canvas.draw()
            except Exception:
                pass

    def _zoom_x_to_data(self):
        """x축을 실제 데이터(유한·비0 y)가 있는 구간으로 줌. alpha 패딩/외삽 0 구간 제외.
        SpanSelector/overlay 보존(ax 메인 x만 조정)."""
        try:
            xv = np.asarray(self.x, dtype=float)
            yv = np.asarray(self.y, dtype=float)
            valid = np.isfinite(xv) & np.isfinite(yv) & (np.abs(yv) > 0)
            if int(valid.sum()) >= 2:
                xlo = float(np.min(xv[valid])); xhi = float(np.max(xv[valid]))
                if xhi > xlo:
                    m = (xhi - xlo) * 0.02
                    self.ax.set_xlim(xlo - m, xhi + m)
                    self.canvas.draw_idle()
        except Exception:
            pass

    def _detrend_band(self, xdisp, y):
        """'전 파장' 고역통과로 광대역 베이스라인을 빼 차등구조(Δα)만 남긴다.

        가우시안 σ=90px(≈4.3nm) 저역 베이스라인을 빼는 방식 — 광대역(수십 nm,
        CH3급 hump 포함)은 제거되고 NO2 차등굴곡(2~4nm)은 보존된다(골든 콜드 실측
        r=0.90, 밴드한정 poly5의 0.95와 등가 수준). 전 파장에 정의되므로 휠 줌아웃
        하면 핏레인지 밖 구조도 그대로 보인다(이전 밴드한정 방식은 밖이 NaN이라
        줌아웃해도 빈 화면이었음). NaN은 nan-aware 정규화로 처리. 표시 전용.
        표본 부족/실패 시 원본 그대로 반환."""
        try:
            yv = np.asarray(y, dtype=float)
            fin = np.isfinite(yv)
            if int(fin.sum()) < 50:
                return y
            sigma = 90.0
            y0 = np.where(fin, yv, 0.0)
            m = fin.astype(float)
            base = gaussian_filter1d(y0, sigma) / np.maximum(gaussian_filter1d(m, sigma), 1e-12)
            return np.where(fin, yv - base, np.nan)
        except Exception:
            return y

    def _zoom_alpha_to_band(self, x0, x1):
        """α 표시 시 현재 핏레인지 ±35% 패딩 창으로 x·y 줌.

        y는 창 안 데이터의 0.5~99.5 퍼센타일(핫픽셀 스파이크 1~2개가 다시 스케일을
        먹지 않게 robust)로 잡는다. 전체 스펙트럼은 휠줌아웃/우클릭 팬으로 언제든
        볼 수 있음 — 초기 화면만 'NO2 피크가 보이는' 밴드 뷰로."""
        try:
            xv = np.asarray(self.x, dtype=float)
            yv = np.asarray(self.y, dtype=float)
            lo, hi = (x0, x1) if x0 <= x1 else (x1, x0)
            pad = (hi - lo) * 0.35
            if pad <= 0:
                return
            xa, xb = lo - pad, hi + pad
            sel = np.isfinite(xv) & np.isfinite(yv) & (xv >= xa) & (xv <= xb)
            if int(sel.sum()) < 10:
                return
            ylo, yhi = np.percentile(yv[sel], [0.5, 99.5])
            m = (yhi - ylo) * 0.2
            if m <= 0:
                return
            self.ax.set_xlim(xa, xb)
            self.ax.set_ylim(ylo - m, yhi + m)
            self.canvas.draw_idle()
        except Exception:
            pass

    def update_ref(self, name):
        """Draws the selected reference gas spectrum on the secondary Y-axis.

        engine.interpolators are indexed by PIXEL number (engine.py builds them as
        interp1d(arange(len), intensity)). So we must evaluate them at the measured
        spectrum's own pixel indices and plot the result against self.x — whether
        self.x is in nm or pixels. (The previous code fed nm straight into a
        pixel-domain interpolator, so the overlay was sampled at the wrong place.)
        """
        # Δα 모드에서 같은 축(ax)에 그렸던 레퍼런스 라인 제거(콤보 변경 시 누적 방지)
        if getattr(self, '_ref_line', None) is not None:
            try:
                self._ref_line.remove()
            except Exception:
                pass
            self._ref_line = None
        self.ax2.clear()
        show_ax2 = False   # Δα 모드/레퍼런스 없음이면 우측 트윈축을 숨긴다(의미 없는 0~1 축 잔상 제거)

        px = getattr(self, '_pixel_idx', None)
        if name in self.engine.interpolators and px is not None:
            y_ref = self.engine.interpolators[name](np.asarray(px, dtype=float))
            if getattr(self, '_diff_active', False):
                # Δα 모드 '고도화 오버레이': 레퍼런스도 같은 밴드 poly5로 디트렌드한 뒤
                # 측정 Δα에 최소제곱 스케일해 '같은 축'에 겹친다 → 피크 1:1 대조
                # (미니 핏 프리뷰). 트윈축 대신 동일 스케일이라 진폭까지 비교 가능.
                ref_d = self._detrend_band(np.asarray(self.x, dtype=float),
                                           np.asarray(y_ref, dtype=float))
                ym = np.asarray(self.y, dtype=float)
                # 스케일은 '핏레인지 안'에서만 최소제곱 — 무광 가장자리 노이즈가
                # 스케일을 오염하지 않게. 그린 곡선은 전 파장(줌아웃 대조용).
                n_ = len(ym)
                lo_, hi_ = sorted((min(self.min_sel, n_ - 1), min(self.max_sel, n_ - 1)))
                bm = np.zeros(n_, dtype=bool)
                bm[lo_:hi_ + 1] = True
                fin = np.isfinite(ref_d) & np.isfinite(ym) & bm
                denom = float(np.dot(ref_d[fin], ref_d[fin])) if fin.any() else 0.0
                if denom > 0:
                    s = float(np.dot(ref_d[fin], ym[fin])) / denom
                    (self._ref_line,) = self.ax.plot(
                        self.x, ref_d * s, 'r--', alpha=0.85, lw=1.2,
                        label=f'Ref {name} (scaled)')
            else:
                self.ax2.plot(self.x, y_ref, 'r--', alpha=0.8, label=f'Ref: {name}')

                yfin = y_ref[np.isfinite(y_ref)]
                if yfin.size and (yfin.max() - yfin.min()) > 1e-65:
                    margin = (yfin.max() - yfin.min()) * 0.1
                    self.ax2.set_ylim(yfin.min() - margin, yfin.max() + margin)

                # 우측 축의 절대값(단면적 ~1e-19)은 범위선택에 무의미하고, 그 지수
                # 오프셋(1e-19)이 좌축 오프셋(1e-8)과 좌상단에서 겹쳐 '1e-89'로 뭉쳤다.
                # → 눈금·오프셋 숨기고 빨간 곡선(피크 위치)만 남긴다. 좌축=α 스케일 유지.
                self.ax2.tick_params(axis='y', which='both',
                                     left=False, right=False, labelright=False)
                self.ax2.yaxis.get_offset_text().set_visible(False)
                self.ax2.legend(loc='upper left', fontsize=8)
                show_ax2 = True   # 원시(raw) α + 레퍼런스일 때만 우측 곡선을 그림

        # Δα 모드거나 레퍼런스가 없으면 우측 트윈축을 통째로 숨김 → 좌측(1e-8)만 남아
        # y스케일이 실제 표시값과 일치하고, '0~1 잔상 축'·오프셋 겹침이 사라진다.
        self.ax2.set_visible(show_ax2)

        if getattr(self, '_diff_active', False):
            # 같은 축 오버레이 추가/제거를 레전드에 반영
            self.ax.legend(loc='upper right', fontsize=8)

        self.canvas.draw()

    def on_select(self, val_min, val_max):
        """Stores pixel indices(+원래 드래그 값) of the dragged range,
        그리고 파란 'Current Range' 스팬을 드래그한 범위로 즉시 갱신."""
        lo, hi = (val_min, val_max) if val_min <= val_max else (val_max, val_min)
        self._sel_is_nm = bool(getattr(self, '_wave_mode', False))
        self._sel_lo, self._sel_hi = float(lo), float(hi)
        if self._sel_is_nm:
            wave = self.x
            self.min_sel = int(np.argmin(np.abs(wave - val_min)))
            self.max_sel = int(np.argmin(np.abs(wave - val_max)))
            if self.min_sel > self.max_sel:
                self.min_sel, self.max_sel = self.max_sel, self.min_sel
        else:
            self.min_sel = int(lo)
            self.max_sel = int(hi)
        # 드래그한 범위는 '현재 채널'에만 기록 → 다른 채널은 자기 범위를 유지
        try:
            self._channel_ranges[int(self._current_channel())] = (
                float(lo), float(hi), bool(self._sel_is_nm))
        except (TypeError, ValueError):
            pass
        self._redraw_range_span(lo, hi)

    def _redraw_range_span(self, lo, hi):
        """파란 'Current Range' 음영을 (lo,hi) 표시좌표로 다시 그린다(드래그 반영).
        y줌은 건드리지 않고 스팬만 교체."""
        try:
            if getattr(self, '_range_span', None) is not None:
                self._range_span.remove()
            self._range_span = self.ax.axvspan(lo, hi, alpha=0.15, color='steelblue')
            self.canvas.draw_idle()
        except Exception:
            pass

    def emit_apply(self):
        """선택 범위를 메인에 전달한다(창은 닫지 않음 — 닫기는 Close 버튼).
        채널콤보가 있으면 그 채널의 nm 범위로 적용."""
        rng = None
        if self.combo_ch is not None:
            try:
                rng = self._channel_ranges.get(int(self.combo_ch.currentData()))
            except (TypeError, ValueError):
                rng = None
        if rng is not None:
            # 항상 '현재 채널'의 현재 범위를 적용 — 이전 채널 드래그값(_sel_lo)이
            # 엉뚱한 채널에 적용되던 문제 방지.
            ch = self.combo_ch.currentData()
            lo_v, hi_v, is_nm = rng
            self.apply_channel.emit(int(ch), float(lo_v), float(hi_v), bool(is_nm))
            unit = "nm" if is_nm else "px"
            self.lbl_applied.setText(
                f"✓ Applied CH{ch}: {float(lo_v):.1f}–{float(hi_v):.1f} {unit}")
        else:
            self.apply_range.emit(self.min_sel, self.max_sel)
            self.lbl_applied.setText(f"✓ Applied: px {self.min_sel}–{self.max_sel}")

