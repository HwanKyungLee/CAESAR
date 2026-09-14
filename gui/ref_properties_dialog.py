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


class RefPropertiesTable(QWidget):
    """가스별 Shift/Squeeze 정책 8컬럼 테이블 (Free · Limit · Fix · Link · Center).

    원래 `RefPropertiesDialog` 안에만 있었다. link 정책은 피팅 결과를 좌우하는 1급
    결정인데 팝업 안에 숨어 있어 메인 화면엔 한 줄 요약뿐이었다 — 논문 방식
    ("NO2를 맞추고 나머지는 그 값에 link")이 화면에서 안 보였다.
    다이얼로그는 이 위젯을 감싸기만 하고, `get_properties()` 계약은 그대로다.

    `changed`는 사용자가 무언가 바꿀 때마다 뜬다 → 메인 패널이 OK 버튼 없이
    `ref_props`를 즉시 갱신할 수 있다(다이얼로그는 이 시그널을 안 듣고 OK에서만 읽는다 —
    Cancel이 취소로 남아야 하므로).
    """
    changed = pyqtSignal()

    def __init__(self, gas_list, current_props, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 8)
        layout.addWidget(self.table)
        self.set_gases(gas_list, current_props)

    def set_gases(self, gas_list, current_props):
        """가스 목록이 바뀌면(레퍼런스 재락) 테이블을 다시 만든다."""
        self.table.clearContents()
        self.table.setRowCount(len(gas_list))
        self._build(gas_list, current_props or {})

    def _build(self, gas_list, current_props):
        self.table.setColumnCount(8)
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

                # Page 4: Center Mode ("중심, 반폭") — 허용창을 0이 아니라 **선언된 중심**에
                # 앵커한다. Limit은 항상 0에서 출발해 step_limit씩 걸어 들어가므로, 0에서 먼
                # 실제 shift(예: 핫 -5.25px)를 쓰려면 범위가 0을 품어야 해 그만큼 느슨해졌다.
                w_center = QLineEdit("0.0, 1.0" if mode != "Center" else str(val))
                w_center.setPlaceholderText("중심, 반폭  (예: -5.25, 1.9)")
                stack.addWidget(w_center)

                # Set initial visible page based on the current mode
                if mode == "Free": stack.setCurrentIndex(0)
                elif mode == "Limit": stack.setCurrentIndex(1)
                elif mode == "Fix": stack.setCurrentIndex(2)
                elif mode == "Link": stack.setCurrentIndex(3)
                elif mode == "Center": stack.setCurrentIndex(4)
                else: stack.setCurrentIndex(1) # Default to Limit
                
                return stack, w_free, w_limit, w_fix, w_link, w_center

            # --- Shift Configuration ---
            cmb_sh = QComboBox()
            cmb_sh.addItems(["Free", "Limit", "Fix", "Link", "Center"])
            cmb_sh.setCurrentText(props.get("sh_mode", "Limit"))
            stack_sh, sh_fre, sh_lim, sh_fix, sh_lnk, sh_ctr = create_dynamic_cell(props.get("sh_mode", "Limit"), props.get("sh_val", ""))
            
            # Automatically switch the stacked widget page when combo box changes
            cmb_sh.currentIndexChanged.connect(stack_sh.setCurrentIndex)
            
            self.table.setCellWidget(i, 1, cmb_sh)
            self.table.setCellWidget(i, 2, stack_sh)
            
            # --- Squeeze Configuration ---
            cmb_sq = QComboBox()
            cmb_sq.addItems(["Free", "Limit", "Fix", "Link"])   # squeeze는 1.0 기준이라 Center 불필요
            cmb_sq.setCurrentText(props.get("sq_mode", "Fix"))
            stack_sq, sq_fre, sq_lim, sq_fix, sq_lnk, _sq_ctr = create_dynamic_cell(props.get("sq_mode", "Fix"), props.get("sq_val", ""))
            
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
                "sh_ctr": sh_ctr,
                "sq_cmb": cmb_sq, "sq_lim": sq_lim, "sq_fix": sq_fix, "sq_lnk": sq_lnk,
                "t_ref_spin": t_ref_spin, "t_coeff_spin": t_coeff_spin,
                "bands_edit": bands_edit,
            }
        
            # 편집 즉시 알린다 — 상시 노출 패널은 OK 버튼이 없다.
            for w in (cmb_sh, cmb_sq):
                w.currentIndexChanged.connect(self.changed)
            for w in (sh_lim, sh_fix, sh_ctr, sq_lim, sq_fix, bands_edit):
                w.editingFinished.connect(self.changed)
            for w in (sh_lnk, sq_lnk):
                w.currentIndexChanged.connect(self.changed)
            for w in (t_ref_spin, t_coeff_spin):
                w.valueChanged.connect(self.changed)

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
            elif sh_mode == "Center": sh_val = w["sh_ctr"].text()
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


class RefPropertiesDialog(QDialog):
    """`RefPropertiesTable`을 감싼 팝업. 기존 호출부와 계약이 같다.

    상시 노출 패널(C1)이 생겼어도 이 팝업은 남긴다 — 넓은 창에서 한 번에 훑고
    **Cancel로 되돌릴 수 있는** 편집 경로가 여전히 필요하다(패널은 즉시 반영이라
    취소가 없다).
    """

    def __init__(self, parent, gas_list, current_props):
        super().__init__(parent)
        self.setWindowTitle("Edit Reference Properties")
        _s = _ui_scale()
        self.resize(int(1200 * _s), int(350 * _s))
        layout = QVBoxLayout(self)

        self._w = RefPropertiesTable(gas_list, current_props, self)
        layout.addWidget(self._w)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # 하위호환 — 예전에 dialog.table / .gas_list / .param_widgets를 직접 보던 코드용
    @property
    def table(self):
        return self._w.table

    @property
    def gas_list(self):
        return self._w.gas_list

    @property
    def param_widgets(self):
        return self._w.param_widgets

    def get_properties(self):
        """계약 불변 — 호출부는 이 메서드만 안다."""
        return self._w.get_properties()
