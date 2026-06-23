"""gui/ref_properties_dialog.py
RefPropertiesDialog — ui_dialogs_ref.py에서 분리(클래스 단위).
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


class RefPropertiesDialog(QDialog):
    """
    Dialog to dynamically edit Shift and Squeeze fitting parameters 
    (Free, Limit, Fix, Link) for each loaded reference gas.
    """
    def __init__(self, parent, gas_list, current_props):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Edit Reference Properties")
        _s = _ui_scale()
        self.resize(int(1200 * _s), int(350 * _s))
        layout = QVBoxLayout(self)

        self.table = QTableWidget(len(gas_list), 8)
        self.table.setHorizontalHeaderLabels([
            "Gas Name", "Shift Mode", "Shift Params",
            "Squeeze Mode", "Squeeze Params",
            "T_ref (°C)", "dσ/dT (%/°C)",
            "Active Bands (nm)",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # Fixed-width columns: T_ref, dσ/dT, Active Bands
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 110)
        self.table.setColumnWidth(7, 160)
        
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

            # --- Active absorption bands ---
            bands_edit = QLineEdit(props.get("active_bands_nm", ""))
            bands_edit.setPlaceholderText("e.g. 460,495 or 360,380|460,495")
            bands_edit.setToolTip(
                "Wavelength bands (nm) where this gas has real absorption.\n"
                "Format: 'lo,hi' or 'lo1,hi1|lo2,hi2' for multiple bands.\n"
                "Leave empty → always included in the fit.\n"
                "Example (O4): '460,495'  — disables O4 outside that range."
            )
            self.table.setCellWidget(i, 7, bands_edit)

            # Save widget references for data extraction
            self.param_widgets[gas] = {
                "sh_cmb": cmb_sh, "sh_lim": sh_lim, "sh_fix": sh_fix, "sh_lnk": sh_lnk,
                "sq_cmb": cmb_sq, "sq_lim": sq_lim, "sq_fix": sq_fix, "sq_lnk": sq_lnk,
                "t_ref_spin": t_ref_spin, "t_coeff_spin": t_coeff_spin,
                "bands_edit": bands_edit,
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
                "t_coeff": w["t_coeff_spin"].value(),
                "active_bands_nm": w["bands_edit"].text().strip(),
            }
        return props
