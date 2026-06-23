"""gui/ref_mask_dialog.py
MaskDialog — ui_dialogs_ref.py에서 분리(클래스 단위).
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
