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

from engine import UniversalEngine
from worker import AnalysisWorker
from ui_dialogs import *

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
        
        # Calibration State Variables
        self.calib_shift = 0.0
        self.calib_squeeze = 1.0
        
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('CAESAR Pro v1.0')
        self.resize(1400, 850)
        
        # Create horizontal splitter (Left: Control Panel / Right: Monitor Tabs)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)
        
        # =========================================================
        # [Left] Main Control Panel
        # =========================================================
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # --- Save/Load Fit Scenario ---
        grp_scenario = QGroupBox("💾 Fit Scenario")
        grp_scenario.setStyleSheet("QGroupBox { font-weight: bold; color: #2E7D32; }")
        lay_scenario = QHBoxLayout()
        
        btn_save_scen = QPushButton("📥 Save Settings")
        btn_load_scen = QPushButton("📂 Load Settings")
        
        btn_save_scen.clicked.connect(self.save_scenario)
        btn_load_scen.clicked.connect(self.load_scenario)
        
        lay_scenario.addWidget(btn_save_scen)
        lay_scenario.addWidget(btn_load_scen)
        grp_scenario.setLayout(lay_scenario)
        
        left_layout.addWidget(grp_scenario)
        
        # --- 0. Independent Tool Buttons ---
        layout_tools = QHBoxLayout()
        
        btn_calib_tool = QPushButton("🔍 Wavelength Calibration Tool")
        btn_calib_tool.clicked.connect(self.open_wavelength_calibration)
        
        btn_ref_gen = QPushButton("✂️ Reference Generator")
        btn_ref_gen.clicked.connect(self.open_reference_generator)
        btn_ref_gen.setStyleSheet("background-color: #fff3e0; font-weight: bold;")
        
        layout_tools.addWidget(btn_calib_tool)
        layout_tools.addWidget(btn_ref_gen)
        left_layout.addLayout(layout_tools)

        # --- 1. Reference Management Section ---
        grp_ref = QGroupBox("1. Reference")
        grp_ref.setMinimumHeight(250)
        lay_ref = QVBoxLayout()
        
        # Reference List Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(100) 
        self.ref_in = QWidget()
        self.ref_lay = QVBoxLayout()
        self.ref_in.setLayout(self.ref_lay)
        self.scroll.setWidget(self.ref_in)
        lay_ref.addWidget(self.scroll)
        
        # Batch Multiplier Scale
        layout_mult = QHBoxLayout()
        layout_mult.addWidget(QLabel("Ref Multiplier (1eX): 10^"))
        self.spin_mult_pow = QSpinBox()
        self.spin_mult_pow.setRange(-100, 100)
        self.spin_mult_pow.setValue(0)
        layout_mult.addWidget(self.spin_mult_pow)
        layout_mult.addWidget(QLabel("(e.g., 40 -> x1e40)"))
        layout_mult.addStretch(1)
        lay_ref.addLayout(layout_mult)
        
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
        
        # Lock References Button
        btn_lock = QPushButton("🔒 Lock References (Commit)")
        btn_lock.clicked.connect(self.lock_ref)
        btn_lock.setStyleSheet("background-color: #e1f5fe; color: #0277bd; font-weight: bold; padding: 5px;")
        lay_ref.addWidget(btn_lock)
        
        # ILS Convolution Blur
        layout_conv = QHBoxLayout()
        layout_conv.addWidget(QLabel("FWHM:"))
        self.spin_fwhm = QDoubleSpinBox()
        self.spin_fwhm.setRange(0, 50)
        layout_conv.addWidget(self.spin_fwhm)
        btn_conv = QPushButton("Blur")
        btn_conv.clicked.connect(self.apply_convolution)
        layout_conv.addWidget(btn_conv)
        lay_ref.addLayout(layout_conv)
        
        grp_ref.setLayout(lay_ref)
        left_layout.addWidget(grp_ref)
        
        # --- 2. Fit Range & Calibration Section ---
        grp_set = QGroupBox("2. Fit Range & Calibration")
        lay_set = QVBoxLayout()
        
        # Pixel-based Selection
        layout_px = QHBoxLayout()
        btn_load_wl = QPushButton("Load X-Axis (nm)")
        btn_load_wl.clicked.connect(self.load_wavelength_cal)
        layout_px.addWidget(btn_load_wl)
        
        self.lbl_fwhm_display = QLabel("💡 FWHM: Pending")
        self.lbl_fwhm_display.setStyleSheet("color: #757575; font-weight: bold; padding: 3px;")
        layout_px.addWidget(self.lbl_fwhm_display)
        layout_px.addStretch(1)
        
        layout_px.addWidget(QLabel("Pixel Min:"))
        self.txt_min = QLineEdit("0")
        self.txt_min.setFixedWidth(50)
        layout_px.addWidget(self.txt_min)
        layout_px.addWidget(QLabel("Max:"))
        self.txt_max = QLineEdit("950")
        self.txt_max.setFixedWidth(50)
        layout_px.addWidget(self.txt_max)
        
        btn_sel = QPushButton("Vis. Select")
        btn_sel.clicked.connect(self.open_selector)
        layout_px.addWidget(btn_sel)
        lay_set.addLayout(layout_px)
        
        # Wavelength-based Selection
        layout_nm = QHBoxLayout()
        layout_nm.addWidget(QLabel("Target nm:"))
        self.spin_target_nm = QDoubleSpinBox()
        self.spin_target_nm.setRange(200, 1000)
        self.spin_target_nm.setValue(455.0)
        layout_nm.addWidget(self.spin_target_nm)
        
        layout_nm.addWidget(QLabel("Window (±nm):"))
        self.spin_window_nm = QDoubleSpinBox()
        self.spin_window_nm.setRange(1, 200)
        self.spin_window_nm.setValue(20.0)
        layout_nm.addWidget(self.spin_window_nm)
        
        btn_apply_nm = QPushButton("Set Range by nm")
        btn_apply_nm.clicked.connect(self.set_range_from_nm)
        layout_nm.addWidget(btn_apply_nm)
        lay_set.addLayout(layout_nm)
        
        grp_set.setLayout(lay_set)
        left_layout.addWidget(grp_set)
        
        # --- Detailed Parameters Section (Poly, Shift Center, Precision Control) ---
        grp_calib = QGroupBox("Parameters")
        lay_calib = QHBoxLayout()
        
        lay_calib.addWidget(QLabel("Step Limit (px):"))
        self.spin_step_limit = QDoubleSpinBox()
        self.spin_step_limit.setRange(0.01, 10.0)
        self.spin_step_limit.setSingleStep(0.1)
        self.spin_step_limit.setDecimals(2)
        self.spin_step_limit.setValue(0.5) 
        self.spin_step_limit.setToolTip("Maximum pixels that can be moved per frame (inertia limit)")
        lay_calib.addWidget(self.spin_step_limit)

        lay_calib.addWidget(QLabel("Poly Degree:"))
        self.spin_poly_deg = QSpinBox()
        self.spin_poly_deg.setRange(0, 10)
        self.spin_poly_deg.setValue(3)
        lay_calib.addWidget(self.spin_poly_deg)
        
        #티호노프 람다(λ) 다이얼 추가
        lay_calib.addWidget(QLabel("Tikhonov λ:"))
        self.spin_lambda = QDoubleSpinBox()
        self.spin_lambda.setRange(0.0, 10.0)
        self.spin_lambda.setSingleStep(0.01)
        self.spin_lambda.setDecimals(4)
        self.spin_lambda.setValue(0.0000) # 기본값 0 (꺼짐)
        self.spin_lambda.setToolTip("Ridge Penalty: 0 = Off, 0.01~0.1 = Strong stabilization")
        lay_calib.addWidget(self.spin_lambda)

        self.chk_robust = QCheckBox("🛡️ Robust (IRLS)")
        self.chk_robust.setToolTip("Auto-ignore spike noise and cosmic rays")
        self.chk_robust.setChecked(False) # 기본값 꺼짐
        lay_calib.addWidget(self.chk_robust)

        self.ref_props = {} # Internal dictionary to store property settings
        
        btn_props = QPushButton("⚙️ Edit Reference Properties")
        btn_props.setStyleSheet("background-color: #1565C0; color: white; font-weight: bold;")
        btn_props.clicked.connect(self.open_ref_properties)
        lay_calib.addWidget(btn_props)
        
        grp_calib.setLayout(lay_calib)
        left_layout.addWidget(grp_calib)

        # --- 3. Analysis Control Section ---
        grp_ctl = QGroupBox("3. Analysis")
        lay_ctl = QVBoxLayout()
        
        layout_row1 = QHBoxLayout()
        btn_load = QPushButton("Load Data")
        btn_load.clicked.connect(self.load_data)
        layout_row1.addWidget(btn_load)
        
        layout_row2 = QHBoxLayout()
        self.b_run = QPushButton("RUN")
        self.b_run.clicked.connect(self.start_analysis)
        self.b_stop = QPushButton("STOP")
        self.b_stop.clicked.connect(self.stop_analysis)
        self.b_stop.setEnabled(False)
        self.b_save = QPushButton("Save")
        self.b_save.clicked.connect(self.save)
        
        layout_row2.addWidget(self.b_run)
        layout_row2.addWidget(self.b_stop)
        layout_row2.addWidget(self.b_save)
        
        layout_perf = QHBoxLayout()
        layout_perf.addWidget(QLabel("Update Graph Every:"))
        self.spin_update = QSpinBox()
        self.spin_update.setRange(1, 1000)
        self.spin_update.setValue(10)
        layout_perf.addWidget(self.spin_update)
        layout_perf.addWidget(QLabel("files"))
        
        self.chk_observe = QCheckBox("Observe (Slow Mode)")
        self.chk_observe.setStyleSheet("font-weight: bold; color: #1565C0;")
        layout_perf.addWidget(self.chk_observe)
        
        self.chk_turbo = QCheckBox("Turbo")
        layout_perf.addWidget(self.chk_turbo)
        
        lay_ctl.addLayout(layout_row1)
        lay_ctl.addLayout(layout_perf)
        lay_ctl.addLayout(layout_row2)
        grp_ctl.setLayout(lay_ctl)
        left_layout.addWidget(grp_ctl)
        
        # Status Bar, Progress Bar, and Result Table
        self.status = QLabel("Ready")
        self.pbar = QProgressBar()
        self.table = QTableWidget()
        self.table.cellDoubleClicked.connect(self.on_table_double_click)
        self.table.cellClicked.connect(self.on_table_single_click)
        
        left_layout.addWidget(self.status)
        left_layout.addWidget(self.pbar)
        left_layout.addWidget(self.table)
        splitter.addWidget(left_widget)
        
        # =========================================================
        # [Right] Monitor Tab Area
        # =========================================================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # 1. Main Tab Widget
        self.main_tabs = QTabWidget()
        
        # 2. [Tab 1] Existing Graph Monitor (High-Speed Analysis Monitor)
        self.monitor = MonitorWidget(self.engine)
        self.main_tabs.addTab(self.monitor, "📈 Analysis Monitor")
        
        # 3. [Tab 2] Post-Processing Screen
        self.post_tab = QWidget()
        self.setup_post_tab() # Fills the contents of the post-processing tab
        self.main_tabs.addTab(self.post_tab, "📊 Post-Analysis")
        
        right_layout.addWidget(self.main_tabs)
        
        # Keep Existing Signal Connections
        self.monitor.cb_view.currentIndexChanged.connect(self.refresh_viewer)
        self.monitor.roi_selected.connect(self.apply_roi_from_graph)
        
        splitter.addWidget(right_widget)

    def setup_post_tab(self):
        """Configure the layout and buttons for the Post-Analysis tab."""
        layout = QVBoxLayout(self.post_tab)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 1. Mirror Reflectivity Section
        group_r = QGroupBox("STEP 1: Mirror Reflectivity (R) Generation")
        r_layout = QVBoxLayout()
        btn_gen_r = QPushButton("🎡 Generate R-Curve") 
        btn_gen_r.setFixedSize(300, 50)
        btn_gen_r.clicked.connect(self.open_r_generator)
        r_layout.addWidget(btn_gen_r, alignment=Qt.AlignmentFlag.AlignCenter)
        group_r.setLayout(r_layout)
        layout.addWidget(group_r)

        # 2. Concentration (ppb) Conversion Section
        group_ppb = QGroupBox("STEP 2: Concentration (ppb) Conversion")
        ppb_layout = QVBoxLayout()
        btn_open_ppb = QPushButton("🚀 Open ppb Converter")
        btn_open_ppb.setFixedSize(300, 50)
        btn_open_ppb.clicked.connect(self.open_post_process)
        ppb_layout.addWidget(btn_open_ppb, alignment=Qt.AlignmentFlag.AlignCenter)
        group_ppb.setLayout(ppb_layout)
        layout.addWidget(group_ppb)

    def open_post_process(self):
        """Search deep within the engine and monitor to locate the wavelength array before opening."""
        if not hasattr(self, 'results') or not self.results:
            QMessageBox.warning(self, "No Data", "No analysis results found. Please run the analysis (RUN) first.")
            return

        wl_data = None

        # 🔍 Search Priority 1: Main class attributes
        wl_data = getattr(self, 'wavelengths', getattr(self, 'wave_data', None))

        # 🔍 Search Priority 2: Dive into the engine's raw references
        if wl_data is None and hasattr(self.engine, 'raw_references') and self.engine.raw_references:
            try:
                first_gas = self.engine.gas_list[0]
                ref_obj = self.engine.raw_references[first_gas]
                
                if isinstance(ref_obj, dict):
                    wl_data = ref_obj.get('wl')
                else:
                    wl_data = getattr(ref_obj, 'index', None)
            except Exception as e:
                print(f"DEBUG: Error searching raw_references - {e}")

        # 🔍 Search Priority 3: Extract from Monitor Widget
        if wl_data is None and hasattr(self, 'monitor'):
            wl_data = getattr(self.monitor, 'wavelengths', getattr(self.monitor, 'wave_data', None))

        # 🚨 Final check before execution
        if wl_data is None:
            QMessageBox.critical(self, "Missing Data", 
                                 "Wavelength data could not be found.\n"
                                 "Make sure you have fully loaded the data or completed an analysis run.")
            return
            
        # Convert to numpy array safely
        wl_final = np.array(wl_data)
        
        dialog = PostProcessDialog(self, self.results, wl_final)
        dialog.exec()

    def open_r_generator(self):
        """Locates wavelength data and opens the Reflectivity (R-Curve) Generator."""
        if not hasattr(self, 'results') or not self.results:
            QMessageBox.warning(self, "No Data", "No analysis results found. Please run the analysis (RUN) first.")
            return

        wl_data = None

        # 🔍 Search 1: Engine's raw references
        if hasattr(self.engine, 'raw_references') and self.engine.raw_references:
            try:
                first_gas = self.engine.gas_list[0]
                ref_obj = self.engine.raw_references[first_gas]
                
                if isinstance(ref_obj, dict):
                    wl_data = ref_obj.get('wl')
                elif isinstance(ref_obj, pd.DataFrame):
                    wl_data = ref_obj.index.values
            except Exception as e:
                print(f"DEBUG: Error searching raw_references - {e}")

        # 🔍 Search 2: Engine's scaling factors properties
        if wl_data is None and hasattr(self.engine, 'scaling_factors'):
            if isinstance(self.engine.scaling_factors, dict):
                wl_data = self.engine.scaling_factors.get('wl', self.engine.scaling_factors.get('x'))

        # 🔍 Search 3: Retrieve directly from the active Monitor widget
        if wl_data is None and hasattr(self, 'monitor'):
            wl_data = getattr(self.monitor, 'wavelengths', 
                      getattr(self.monitor, 'wave_data', 
                      getattr(self.monitor, 'wl', None)))

        if wl_data is None:
            print("--- [FINAL DEBUG: Engine Attributes] ---")
            print(f"Engine Gas List: {getattr(self.engine, 'gas_list', 'None')}")
            QMessageBox.critical(self, "Search Failed", "Wavelength data not found. Please check the engine configuration.")
            return

        dialog = R_GeneratorDialog(self, np.array(wl_data))
        dialog.exec()

    def open_ref_properties(self):
        """Opens the RefPropertiesDialog to configure Shift/Squeeze bounds."""
        if not hasattr(self, 'engine') or len(self.engine.gas_list) == 0:
            QMessageBox.warning(self, "Warning", "Please load and lock references first!")
            return
            
        dialog = RefPropertiesDialog(self, self.engine.gas_list, getattr(self, 'ref_props', {}))
        if dialog.exec():
            self.ref_props = dialog.get_properties()
            print("⚙️ Reference properties successfully saved:", self.ref_props)

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

    def auto_register_reference(self, gas_name, filepath):
        """Automatically places newly generated references into an empty UI slot."""
        for widget in getattr(self, 'ref_widgets', []):
            if widget['n'].text() == "" and widget['fp'] == "":
                widget['n'].setText(gas_name)
                widget['fp'] = filepath
                widget['btn'].setText(f"Load ({os.path.basename(filepath)})")
                widget['btn'].setStyleSheet("background-color: #e8f5e9; color: #2e7d32; font-weight: bold;")
                
                self.status.setText(f"✅ New reference auto-registered: {gas_name}")
                return
                
        QMessageBox.warning(self, "Slot Full", "Reference slots are full. Please load manually.")

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

            # 4. Smart UI Update for FWHM Label
            fwhm_text = "✅ Wavelength Updated"
            if hasattr(dialog, 'help_label') and "FWHM" in dialog.help_label.text():
                fwhm_text = f"💡 {dialog.help_label.text().split('|')[-1].strip()}"

            target_label = getattr(self, 'lbl_fwhm_display', getattr(self, 'fwhm_label', None))
            if target_label:
                target_label.setText(fwhm_text)
                target_label.setStyleSheet("color: #2E7D32; font-weight: bold;")

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
        """Intelligently guesses the gas name based on the filename."""
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
            filepath, _ = QFileDialog.getOpenFileName(self, "Load Wavelengths (nm)", "", "Text/CSV (*.txt *.csv *.dat)")
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
                self.monitor.set_wavelengths(wl_data)
                self.lbl_fwhm_display.setText(f"💡 WL Loaded: {os.path.basename(filepath)}")
                
                # Show popup only if loaded manually
                if not auto_path: 
                    QMessageBox.information(self, "Loaded", f"X-Axis Calibration Loaded.\nRange: {wl_data.min():.2f} ~ {wl_data.max():.2f} nm")
            else: 
                QMessageBox.warning(self, "Error", "No valid numeric data found in the file.")
                
        except Exception as e: 
            QMessageBox.critical(self, "Error", f"Failed to load wavelength file:\n{str(e)}")

    def set_range_from_nm(self):
        """Converts user-input nm range into pixel indices based on loaded wavelength data."""
        if self.monitor.wavelengths is None:
            QMessageBox.warning(self, "Error", "Please load the X-Axis (nm) wavelength file first!")
            return
            
        target = self.spin_target_nm.value()
        window = self.spin_window_nm.value()
        min_nm = target - window
        max_nm = target + window
        
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
        files, _ = QFileDialog.getOpenFileNames(self, "Select References", "", "All Files (*.*)")
        if files: 
            for f in sorted(files): 
                self.add_ref_row(self.guess_gas_name(f), f)
            
    def get_auto_scale_exponent(self, filepath):
        """Automatically calculates the exponent multiplier to normalize data scale to ~1e-19."""
        try:
            from data_io import DataIO
            _, intensity_raw = DataIO.load_reference(filepath)
            
            if intensity_raw is None or len(intensity_raw) == 0: 
                return 0
                
            max_val = np.max(np.abs(intensity_raw))
            if max_val == 0: 
                return 0
                
            import math
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
        spin_mult.setFixedWidth(50)
        
        if path: 
            spin_mult.setValue(self.get_auto_scale_exponent(path))
        else: 
            spin_mult.setValue(0)
            
        txt_name = QLineEdit()
        txt_name.setFixedWidth(80)
        lbl_path = QLabel("...")
        
        btn_select = QPushButton("S")
        btn_delete = QPushButton("X")
        btn_delete.setFixedWidth(30)
        
        def select_file_wrapper():
            f, _ = QFileDialog.getOpenFileName(self, "Select Reference", "", "All Files (*.*)")
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
        print(f"✅ Slot Added: {name if name else 'Empty'}")
        
    def del_ref(self, widget): 
        """Removes a reference row from the UI."""
        widget.deleteLater()
        self.ref_widgets = [x for x in self.ref_widgets if x['w'] != widget]

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

    def lock_ref(self):
        """Locks the UI references and commits them to the UniversalEngine for analysis."""
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
                    
        # Apply zero convolution initially (refreshes internal interpolators)
        self.engine.apply_ils_convolution(0.0)
        
        if success_count > 0:
            QMessageBox.information(self, "Locked", f"{success_count} references have been successfully locked into the Engine.")

            # Dynamically update the Result Table headers
            if hasattr(self, 'table'):
                cols = ["File", "RMS", "Status"] + self.engine.gas_list + ["Shift", "Squeeze"]
                self.table.setColumnCount(len(cols))
                self.table.setHorizontalHeaderLabels(cols)
                
            # Update Monitor dropdown list
            if hasattr(self, 'monitor') and hasattr(self.monitor, 'cb_view'):
                self.monitor.cb_view.clear()
                self.monitor.cb_view.addItem("Measurement")
                for name in self.engine.gas_list: 
                    self.monitor.cb_view.addItem(f"Ref: {name}")
        else:
            QMessageBox.warning(self, "Error", "No valid references found to lock, or an error occurred.")

    # ---------------------------------------------------------
    # Legacy Support for Wavelength/Lamp Loading
    # ---------------------------------------------------------
    def load_x_axis(self):
        """Loads a pre-calibrated text file as the X-axis."""
        filepath, _ = QFileDialog.getOpenFileName(self, "Load Calibration", "", "Text Files (*.txt)")
        if not filepath: 
            return
        
        self.wavelengths = np.loadtxt(filepath)
        
        # Read the first line to check for FWHM metadata
        with open(filepath, 'r') as f:
            first_line = f.readline()
            if "FWHM" in first_line:
                fwhm_info = first_line.strip().replace('#', '').strip()
                self.lbl_fwhm_display.setText(f"💡 {fwhm_info}")
                self.lbl_fwhm_display.setStyleSheet("color: #2E7D32; font-weight: bold;")
            else:
                self.lbl_fwhm_display.setText("⚠️ No FWHM Metadata")
                self.lbl_fwhm_display.setStyleSheet("color: #C62828; font-weight: bold;")

    def calculate_fwhm_from_old_lamp(self):
        """Calculates FWHM using an older format Hg Lamp CSV file."""
        if not hasattr(self, 'wavelengths') or self.wavelengths is None:
            QMessageBox.warning(self, "Warning", "Please load the X-axis (Wavelength Calibration) file first!")
            return
            
        filepath, _ = QFileDialog.getOpenFileName(self, "Load Old Hg Lamp", "", "CSV Files (*.csv)")
        if not filepath: 
            return
        
        try:
            df = pd.read_csv(filepath)
            lamp_y = df.groupby('Column')['Intensity'].mean().values if 'Column' in df.columns else df.iloc[:, -1].values
            
            # Default pixel approximation for legacy Hg lamps
            peak_pixel_guess = 727 
            
            fwhm_px, fwhm_nm = self.calculate_fwhm(peak_pixel_guess, lamp_y, self.wavelengths)
            
            if fwhm_nm is not None:
                self.lbl_fwhm_display.setText(f"💡 Calculated FWHM: {fwhm_nm:.3f} nm")
                self.lbl_fwhm_display.setStyleSheet("color: #1565C0; font-weight: bold;")
                
        except Exception as e:
            QMessageBox.critical(self, "Calculation Failed", f"Error calculating FWHM:\n{e}")

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
        btn_cancel = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        
        msg_box.exec()
        
        # Route to the appropriate function based on user selection
        if msg_box.clickedButton() == btn_files:
            self._load_files()
        elif msg_box.clickedButton() == btn_folder:
            self._load_folder()

    def _load_files(self):
        """Loads specific measurement files selected by the user."""
        files, _ = QFileDialog.getOpenFileNames(self, "Select Measurement Files", "", "Data Files (*.dat *.txt *.csv)")
        if files:
            self._update_file_table(sorted(files))

    def _load_folder(self):
        """Scans a selected folder and loads all valid measurement files."""
        folder_path = QFileDialog.getExistingDirectory(self, "Select Measurement Folder")
        
        if folder_path:
            # Filter files by valid extensions (.dat, .txt, .csv)
            valid_extensions = ('.dat', '.txt', '.csv')
            files = [
                os.path.join(folder_path, f) 
                for f in os.listdir(folder_path) 
                if f.lower().endswith(valid_extensions)
            ]
            
            if files:
                self._update_file_table(sorted(files))
            else:
                QMessageBox.warning(self
                                    , "No Data", "No analyzable files (.dat, .txt, .csv) found in the selected folder.")

    def _update_file_table(self, file_list):
        """Internal helper to update the UI table with the loaded file list."""
        self.file_list = file_list
        self.table.setRowCount(len(self.file_list))
        
        for i, filepath in enumerate(self.file_list): 
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(filepath)))
            
        self.status.setText(f"📁 {len(self.file_list)} Measurement files loaded.")

    def apply_convolution(self):
        """Applies Instrument Line Shape blur based on the entered FWHM."""
        if not self.engine.is_engine_ready(): 
            QMessageBox.warning(self, "Warning", "Please load references first.")
            return
            
        fwhm_val = self.spin_fwhm.value()
        self.engine.apply_ils_convolution(fwhm_val)
        self.refresh_viewer()
        QMessageBox.information(self, "Applied", f"ILS Blur (FWHM={fwhm_val} nm) successfully applied.")
        
    def open_selector(self):
        """Opens the visual RangeSelectorDialog."""
        if not self.file_list: 
            return
        try: 
            mn, mx = int(self.txt_min.text()), int(self.txt_max.text())
        except Exception: 
            mn, mx = 0, 950
            
        # Passes the middle file in the list for a representative preview
        mid_file = self.file_list[len(self.file_list) // 2]
        self.sel_dlg = RangeSelectorDialog(mid_file, mn, mx, self.engine)
        self.sel_dlg.apply_range.connect(self.update_range)
        self.sel_dlg.exec()
        
    def update_range(self, min_idx, max_idx):
        """Updates the text boxes with the visual selection."""
        self.txt_min.setText(str(min_idx))
        self.txt_max.setText(str(max_idx))
        
    def open_scanner(self):
        """Opens the CalibrationScanner to auto-find the best initial shift."""
        if not self.file_list: 
            return
        if not self.engine.is_engine_ready(): 
            QMessageBox.warning(self, "Warning", "Please load references first.")
            return
        try: 
            pixel_min, pixel_max = int(self.txt_min.text()), int(self.txt_max.text())
        except Exception: 
            return
            
        mid_file = self.file_list[len(self.file_list) // 2]
        try:
            from data_io import DataIO
            _, y_data = DataIO.load_measurement(mid_file, pixel_min=0)
        except Exception: 
            QMessageBox.critical(self, "Read Error", "Cannot parse the selected data file.")
            return
            
        current_poly_order = self.spin_poly_deg.value()
        # scanner = CalibrationScanner(...) 코드는 ui_dialogs.py 쪽에서 담당하므로 생략 없이 기존 호출부 유지
        self.scanner = CalibrationScanner(self.engine, y_data, pixel_min, pixel_max, current_poly_order)
        self.scanner.apply_result.connect(self.apply_scan_result)
        self.scanner.exec()
        
    def apply_scan_result(self, optimal_shift):
        """Updates the main UI shift value based on the scanner's result."""
        self.calib_shift = optimal_shift
        self.spin_manual_shift.setValue(optimal_shift)
        QMessageBox.information(self, "Success", f"Optimal Shift set to {optimal_shift:.2f}")
        
    def apply_roi_from_graph(self, min_val, max_val):
        """Updates the fitting range directly from the fast monitor ROI selection."""
        self.txt_min.setText(str(min_val))
        self.txt_max.setText(str(max_val))
        self.status.setText(f"Range Selected: {min_val} ~ {max_val}")

    # ---------------------------------------------------------
    # Multithreading Analysis Execution (Worker)
    # ---------------------------------------------------------
    def start_analysis(self):
        """Prepares UI, configs, and fires up the AnalysisWorker thread."""
        if not self.file_list: 
            return
        if not self.engine.is_engine_ready(): 
            QMessageBox.warning(self, "Warning", "Please lock references into the Engine first.")
            return
            
        try: 
            pixel_min, pixel_max = int(self.txt_min.text()), int(self.txt_max.text())
        except Exception: 
            QMessageBox.warning(self, "Input Error", "Please enter valid integers for Pixel Min/Max.")
            return
        
        self.results = []
        
        # 🌟 UI Table Reset: Disable sorting, clear, and reconstruct precisely
        self.table.setSortingEnabled(False) 
        self.table.clearContents()
        self.table.setRowCount(len(self.file_list)) 
        
        # Lock in column headers dynamically based on loaded gases
        cols = ["File", "RMS", "Status"] + self.engine.gas_list + ["Shift", "Squeeze"]
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        
        # Reset progress bar explicitly
        self.pbar.setMinimum(0)
        self.pbar.setMaximum(len(self.file_list))
        self.pbar.setValue(0)
        
        self.monitor.clear_trend()
        
        # Configure Initial Parameters and Bounds
        num_gases = len(self.engine.gas_list)
        
        start_shift = 0.0  
        step_limit_val = self.spin_step_limit.value()
        
        poly_deg = self.spin_poly_deg.value()
        num_poly_params = poly_deg + 1
        
        # p0 배열의 첫 번째 값은 0.0(start_shift)으로 고정되어 넘어감
        p0 = [start_shift, self.calib_squeeze] + [0.1] * num_gases + [0] * num_poly_params
        bounds_low = [-np.inf, 0.95] + [0.0] * num_gases + [-np.inf] * num_poly_params
        bounds_high = [np.inf, 1.05] + [np.inf] * num_gases + [np.inf] * num_poly_params
        
        interval = self.spin_update.value()
        
        # Dynamic delay control based on UI Checkboxes
        delay_ms = 200 if self.chk_observe.isChecked() else 0
        if self.chk_turbo.isChecked(): 
            interval = -1
            delay_ms = 0
            
        # Initialize and fire the Worker Thread
        self.worker = AnalysisWorker(
            self.engine, self.file_list, pixel_min, pixel_max, 
            p0, (bounds_low, bounds_high), interval, delay_ms,
            ref_properties=getattr(self, 'ref_props', {})
        )
        
        self.worker.step_limit = step_limit_val

        self.worker.tikhonov_lambda = self.spin_lambda.value()

        self.worker.use_robust_fitting = self.chk_robust.isChecked()

        # ===============================================================
        # Connect Thread Signals to UI functions
        self.worker.progress.connect(self.pbar.setValue)
        self.worker.result_ready.connect(self.update_table)
        self.worker.plot_update.connect(self.monitor.update_spectrum)
        self.worker.trend_update.connect(self.monitor.update_trend)
        self.worker.finished.connect(self.analysis_finished)
        
        # Lock UI controls to prevent interference
        self.b_run.setEnabled(False)
        self.b_stop.setEnabled(True)
        self.status.setText("🏃 Analysis in progress...")
        self.worker.start()
        
    def stop_analysis(self): 
        """Safely stops the worker thread and re-enables UI controls."""
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            self.status.setText("🛑 Halting analysis... please wait.")
            self.status.setStyleSheet("color: red; font-weight: bold;")
            self.b_stop.setEnabled(False) 
            self.worker.wait() 
            self.analysis_finished()
            
    def update_table(self, result_dict, row_index):
        """Triggered by the worker thread to update the table row-by-row."""
        
        self.results.append(result_dict)
        
        self.table.setItem(row_index, 0, QTableWidgetItem(str(result_dict['File'])))
        self.table.setItem(row_index, 1, QTableWidgetItem(f"{result_dict['RMS']:.2e}"))
        
        # Set status cell with conditional background color formatting
        item_status = QTableWidgetItem(str(result_dict['Status']))
        try:
            if result_dict['Status'] != "OK": 
                item_status.setBackground(QColor(255, 100, 100)) # Light Red for errors
        except Exception:
            pass
            
        self.table.setItem(row_index, 2, item_status)
        
        # Populate gas concentrations dynamically
        for i, gas_name in enumerate(self.engine.gas_list): 
            self.table.setItem(row_index, 3 + i, QTableWidgetItem(f"{result_dict.get(gas_name, 0):.2e}"))
            
        gas_offset = len(self.engine.gas_list)
        self.table.setItem(row_index, 3 + gas_offset, QTableWidgetItem(f"{result_dict.get('Shift', 0):.2f}"))
        self.table.setItem(row_index, 4 + gas_offset, QTableWidgetItem(f"{result_dict.get('Squeeze', 1):.4f}"))

        # Force UI scroll to follow the latest row
        item = self.table.item(row_index, 0)
        if item:
            self.table.scrollToItem(item)
            
        # Explicitly enforce progress bar value increment
        self.pbar.setValue(row_index + 1)
        
    def analysis_finished(self): 
        """Re-enables UI and displays completion message when the worker finishes."""
        self.b_run.setEnabled(True)
        self.b_stop.setEnabled(False)
        self.status.setText("✅ Analysis Completed!")
        self.status.setStyleSheet("color: green; font-weight: bold;")
        QMessageBox.information(self, "Done", "All files analyzed successfully.")

    def save(self):
        """Saves the current analysis results with an intelligently generated filename (in nm)."""
        if not hasattr(self, 'results') or not self.results:
            QMessageBox.warning(self, "Warning", "No analysis results to save. Please RUN the analysis first.")
            return
            
        import datetime
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

        # 🌟 4. Ultimate Filename Combiner
        default_fname = f"{now_str}_Result_{gas_list_str}_{wl_str}_Poly{poly_deg}_Step[{step_val}]_{sh_str}_{sq_str}.dat"
        
        path, _ = QFileDialog.getSaveFileName(self, "Save Data", default_fname, "Data Files (*.dat);;CSV Files (*.csv)")
        if path:
            try:
                import pandas as pd
                df = pd.DataFrame(self.results)
                
                if 'Params' in df.columns:
                    df = df.drop(columns=['Params'])
                    
                if path.endswith('.csv'):
                    df.to_csv(path, index=False)
                else:
                    df.to_csv(path, sep='\t', index=False)
                    
                QMessageBox.information(self, "Success", f"🎉 Analysis results saved successfully!\nFile: {os.path.basename(path)}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"An error occurred while saving:\n{e}")

    # ---------------------------------------------------------
    # Viewer Events (Table Click Sync)
    # ---------------------------------------------------------
    def on_table_double_click(self, row, col):
        """Reloads the exact mathematical fit of a specific row into the components view."""
        if row >= len(self.file_list): 
            return
            
        fname = self.table.item(row, 0).text()
        filepath = next((f for f in self.file_list if os.path.basename(f) == fname), None)
        if not filepath: 
            return
        
        if row < len(self.results) and self.results[row]['File'] == fname:
            params = self.results[row].get('Params')
            if params is None: 
                return 
                
            try:
                f_min, f_max = int(self.txt_min.text()), int(self.txt_max.text())
                
                from data_io import DataIO  
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
        if self.monitor.tabs.currentIndex() == 3 and self.monitor.cb_view.currentIndex() == 0: 
            self.refresh_viewer()
            
    def refresh_viewer(self):
        """Updates the fast viewer tab with raw measurement or reference data."""
        idx = self.monitor.cb_view.currentIndex()
        if idx == 0: # Measurement Data
            row = self.table.currentRow()
            if row < 0 or row >= len(self.file_list): 
                return
            
            fname = self.table.item(row, 0).text()
            filepath = next((f for f in self.file_list if os.path.basename(f) == fname), None)
            if filepath:
                try:
                    from data_io import DataIO
                    pixel_idx, intensity_raw = DataIO.load_measurement(filepath, pixel_min=0)
                    self.monitor.plot_viewer(pixel_idx, intensity_raw, f"Meas: {fname}", 'b')
                except Exception as e: 
                    print(f"Viewer load failed: {e}")
        else: # Reference Data
            ref_name = self.monitor.cb_view.currentText().replace("Ref: ", "")
            is_raw = self.monitor.chk_raw.isChecked() 
            
            if is_raw and ref_name in self.engine.raw_references:
                y = self.engine.raw_references[ref_name]
                self.monitor.plot_viewer(np.arange(len(y)), y, f"Ref (RAW): {ref_name}", 'r', style='.')
            elif ref_name in self.engine.interpolators:
                y = self.engine.interpolators[ref_name](np.arange(len(self.engine.raw_references[ref_name])))
                self.monitor.plot_viewer(np.arange(len(y)), y, f"Ref (Conv): {ref_name}", 'r', style='-')

    def auto_calculate_and_display_fwhm(self, lamp_spectrum, wavelengths):
        """Automatically calculates FWHM from the passed lamp spectrum upon calibration completion."""
        try:
            # 1. Find the highest peak (usually the 435.83nm Hg line)
            peak_px = int(np.argmax(lamp_spectrum))
            
            # 2. Extract ±15 pixels around the peak
            window = 15
            start = max(0, peak_px - window)
            end = min(len(lamp_spectrum), peak_px + window + 1)
            
            x_data = np.arange(start, end)
            y_data = lamp_spectrum[start:end]
            
            # 3. Gaussian Fitting
            offset_guess = np.min(y_data)
            a_guess = np.max(y_data) - offset_guess
            
            def gauss(x, a, mu, sigma, offset):
                return a * np.exp(-((x - mu)**2) / (2 * sigma**2)) + offset
                
            popt, _ = curve_fit(gauss, x_data, y_data, p0=[a_guess, peak_px, 2.0, offset_guess])
            sigma = abs(popt[2])
            fwhm_px = 2.3548 * sigma
            
            # 4. Convert pixel FWHM to nanometers (nm)
            dispersion = (wavelengths[end-1] - wavelengths[start]) / (end - 1 - start)
            fwhm_nm = abs(fwhm_px * dispersion)
            
            # 5. Display prominently on the Main UI
            self.lbl_fwhm_display.setText(f"ILS FWHM: {fwhm_nm:.4f} nm")
            self.lbl_fwhm_display.setStyleSheet("color: #E65100; font-weight: bold; background-color: #FFF3E0; border-radius: 4px; padding: 4px;")
            
            return fwhm_nm
            
        except Exception as e:
            print(f"Auto FWHM calculation failed: {e}")
            self.lbl_fwhm_display.setText("⚠️ Auto FWHM Failed")
            self.lbl_fwhm_display.setStyleSheet("color: #D32F2F; font-weight: bold;")
            return None

    # =========================================================
    # 🌟 [V11.0] Scenario Auto-Save & Load System
    # =========================================================
    def save_scenario(self):
        """Serializes current UI state, parameters, and reference paths into a JSON scenario file."""
        # 1. Gather reference information (name, path, multiplier)
        refs_data = []
        if hasattr(self, 'ref_widgets'):
            for rw in self.ref_widgets:
                if rw['n'].text() and rw['fp']:
                    refs_data.append({
                        "name": rw['n'].text(),
                        "path": rw['fp'],
                        "mult": rw['mult'].value()
                    })

        # 2. Collect all critical configuration settings
        scenario_data = {
            "wl_path": getattr(self, 'loaded_wl_path', ""), 
            "refs": refs_data,                              
            "f_min": self.txt_min.text(),
            "f_max": self.txt_max.text(),
            "poly_deg": self.spin_poly_deg.value(),
            "step_limit": getattr(self, 'spin_step_limit', None).value() if hasattr(self, 'spin_step_limit') else 0.5, # Start Shift 대신 Step Limit 저장!
            "ref_props": getattr(self, 'ref_props', {}) 
        }
        
        # 3. Generate smart filename
        gas_str = "_".join(self.engine.gas_list) if hasattr(self, 'engine') and self.engine.gas_list else "NoRefs"
        f_min = self.txt_min.text()
        f_max = self.txt_max.text()
        poly = self.spin_poly_deg.value()
        
        default_fname = f"FitSet_{gas_str}_{f_min}-{f_max}px_Poly{poly}.json"
        
        path, _ = QFileDialog.getSaveFileName(self, "Save Fit Scenario", default_fname, "JSON Files (*.json)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(scenario_data, f, indent=4)
                QMessageBox.information(self, "Success", f"Scenario saved successfully!\nFile: {os.path.basename(path)}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Save Failed:\n{e}")

    def load_scenario(self):
        """Deserializes a JSON scenario file, populates UI, and auto-locks references."""
        path, _ = QFileDialog.getOpenFileName(self, "Load Fit Scenario", "", "JSON Files (*.json)")
        if not path: return
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                scenario = json.load(f)
                
            # 1. Restore UI parameters
            self.txt_min.setText(str(scenario.get("f_min", "")))
            self.txt_max.setText(str(scenario.get("f_max", "")))
            self.spin_poly_deg.setValue(scenario.get("poly_deg", 3))
            if hasattr(self, 'spin_step_limit'):
                self.spin_step_limit.setValue(scenario.get("step_limit", 0.5))
            self.ref_props = scenario.get("ref_props", {})
            
            # 🌟 2. Auto-load wavelength file
            wl_path = scenario.get("wl_path", "")
            if wl_path and os.path.exists(wl_path):
                self.load_wavelength_cal(auto_path=wl_path) 
                
            # 🌟 3. Auto-load references
            refs = scenario.get("refs", [])
            if refs:
                # Clear existing reference UI
                if hasattr(self, 'ref_widgets'):
                    for rw in self.ref_widgets:
                        rw['w'].deleteLater()
                    self.ref_widgets.clear()
                self.engine.clear_engine()
                
                # Add gases one by one from scenario
                for ref in refs:
                    if os.path.exists(ref['path']):
                        self.add_ref_row(name=ref['name'], path=ref['path'])
                        self.ref_widgets[-1]['mult'].setValue(ref.get('mult', 0))
                        
                # 🌟 4. Auto-click 'Lock' to finalize engine setup!
                self.lock_ref()
                
                QMessageBox.information(self, "Auto-Load Success", 
                                        "🚀 [Full-Auto Mode Activated]\n"
                                        "Wavelengths, References, Locks, and Parameters have all been automatically configured!\n"
                                        "You can now simply [Load Data] and hit RUN!")
            else:
                QMessageBox.information(self, "Success", "📂 Scenario parameters loaded successfully!")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load scenario:\n{e}")
 