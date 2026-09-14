"""gui/reference_generator_dialog.py
ReferenceGeneratorDialog — ui_dialogs_ref.py에서 분리(클래스 단위).
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
        self.setWindowTitle("Ultimate Reference Generator (with Advanced Deconvolution)")
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
            self.lbl_wave_info.setText(f"Status: Synced with Main ({len(self.target_wavelengths)} px)")
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
        
        self.btn_load_raw = QPushButton("Load Raw File (.txt)")
        self.btn_load_raw.clicked.connect(self.load_raw_reference)
        lay_raw.addWidget(self.btn_load_raw)
        
        # Literature FWHM Input (LabVIEW logic equivalent)
        lay_lit_fwhm = QHBoxLayout()
        lay_lit_fwhm.addWidget(QLabel("Literature FWHM (nm):"))
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
        self.spin_temp = QDoubleSpinBox(); self.spin_temp.setRange(100.0, 1500.0); self.spin_temp.setValue(293.0)
        self.spin_temp.setToolTip("HITRAN cross-section temperature in K.\n"
                                   "Auto-filled from main window's fallback T (°C + 273.15) when this dialog opens.\n"
                                   "TD channel: PNs 180°C=453K, ANs 300°C=573K (heated-cell gas temperature).")
        lay_hitran.addWidget(self.spin_temp)
        lay_hitran.addWidget(QLabel("P(atm):"))
        self.spin_press = QDoubleSpinBox(); self.spin_press.setRange(0.1, 2.0); self.spin_press.setValue(1.0)
        self.spin_press.setToolTip("HITRAN pressure in atm.\n"
                                    "Auto-filled from main window's fallback P (mbar / 1013.25) when this dialog opens.")
        lay_hitran.addWidget(self.spin_press)
        lay_raw.addLayout(lay_hitran)

        # Auto-sync HITRAN T/P from main window's fallback fields (one-shot at
        # dialog construction; user can override afterwards).
        _parent = self.parent()
        if _parent is not None:
            if hasattr(_parent, "spin_temp"):
                try:
                    self.spin_temp.setValue(float(_parent.spin_temp.value()) + 273.15)
                except Exception:
                    pass
            if hasattr(_parent, "spin_pres"):
                try:
                    self.spin_press.setValue(float(_parent.spin_pres.value()) / 1013.25)
                except Exception:
                    pass

        lay_hitran_action = QHBoxLayout()
        self.combo_hitran_gas = QComboBox()
        self.combo_hitran_gas.addItems([
            "1: H2O (Water)", "2: CO2 (Carbon Dioxide)", "3: O3 (Ozone)", 
            "4: N2O (Nitrous Oxide)", "6: CH4 (Methane)", "7: O2 (Oxygen)", 
            "10: NO2 (Nitrogen Dioxide)"
        ])
        lay_hitran_action.addWidget(self.combo_hitran_gas)
        
        self.btn_hitran = QPushButton("Generate from HITRAN")
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

        # One-shot auto-pickup: grabs Calib + FWHM from the same campaign
        # wv_cal folder (remembers it across sessions via QSettings).
        self.btn_auto_pickup = QPushButton("Auto-pickup Calib + FWHM from campaign wv_cal folder")
        self.btn_auto_pickup.setStyleSheet("background-color: #1565C0; color: white; font-weight: bold;")
        self.btn_auto_pickup.clicked.connect(self._auto_pickup_calib_fwhm)
        lay_wave.addWidget(self.btn_auto_pickup)

        self.btn_load_wave = QPushButton("Load Wavelength Calibration (.txt)")
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
        
        self.btn_load_fwhm = QPushButton("Load FWHM Profile (.txt)")
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
        self.btn_generate = QPushButton("Generate Ultimate Reference")
        self.btn_generate.setStyleSheet("background-color: #ff9800; color: white; font-weight: bold; font-size: 14px;")
        self.btn_generate.clicked.connect(self.apply_convolution)
        self.btn_generate.setMinimumHeight(int(50 * self._s))
        right_layout.addWidget(self.btn_generate)
        
        self.btn_save = QPushButton("Save & Auto-Register to Main")
        self.btn_save.clicked.connect(self.save_reference)
        self.btn_save.setEnabled(False)
        self.btn_save.setMinimumHeight(int(40 * self._s))
        right_layout.addWidget(self.btn_save)

        # --- 5. FWHM Sweep (uniform Gaussian) — generation only ---
        # Validation/auto-best moved to Setup tab → 🎯 FWHM Best-Match
        grp_sweep = QGroupBox("5. FWHM Sweep (uniform Gaussian) — generate references")
        lay_sweep = QVBoxLayout()

        lay_sweep_params = QHBoxLayout()
        lay_sweep_params.addWidget(QLabel("Center FWHM (nm):"))
        self.spin_sweep_center = QDoubleSpinBox()
        self.spin_sweep_center.setRange(0.01, 10.0)
        self.spin_sweep_center.setDecimals(3)
        self.spin_sweep_center.setSingleStep(0.01)
        self.spin_sweep_center.setValue(0.50)
        lay_sweep_params.addWidget(self.spin_sweep_center)

        lay_sweep_params.addWidget(QLabel("Step:"))
        self.spin_sweep_step = QDoubleSpinBox()
        self.spin_sweep_step.setRange(0.001, 1.0)
        self.spin_sweep_step.setDecimals(3)
        self.spin_sweep_step.setSingleStep(0.01)
        self.spin_sweep_step.setValue(0.02)
        lay_sweep_params.addWidget(self.spin_sweep_step)

        lay_sweep_params.addWidget(QLabel("± steps:"))
        self.spin_sweep_n = QSpinBox()
        self.spin_sweep_n.setRange(1, 30)
        self.spin_sweep_n.setValue(5)
        lay_sweep_params.addWidget(self.spin_sweep_n)
        lay_sweep.addLayout(lay_sweep_params)

        lay_sweep_out = QHBoxLayout()
        self.btn_sweep_outdir = QPushButton("Output Folder…")
        self.btn_sweep_outdir.clicked.connect(self._pick_sweep_outdir)
        lay_sweep_out.addWidget(self.btn_sweep_outdir)
        self.lbl_sweep_outdir = QLabel("Status: Not Selected")
        self.lbl_sweep_outdir.setStyleSheet("color: #d32f2f;")
        lay_sweep_out.addWidget(self.lbl_sweep_outdir, stretch=1)
        lay_sweep.addLayout(lay_sweep_out)

        self.btn_run_sweep = QPushButton("Run FWHM Sweep")
        self.btn_run_sweep.setStyleSheet("background-color: #6a1b9a; color: white; font-weight: bold;")
        self.btn_run_sweep.clicked.connect(self.run_fwhm_sweep)
        self.btn_run_sweep.setMinimumHeight(int(40 * self._s))
        lay_sweep.addWidget(self.btn_run_sweep)

        _hint = QLabel("After sweep finishes, validate in Setup tab →  FWHM Best-Match")
        _hint.setStyleSheet("color: #555; font-style: italic;")
        _hint.setWordWrap(True)
        lay_sweep.addWidget(_hint)

        grp_sweep.setLayout(lay_sweep)
        # FWHM Sweep(uniform) 섹션 비활성화(2026-06): dynamic ILS(apply_convolution)가
        # Hg 측정 픽셀별 프로파일을 쓰므로 uniform sweep + Best-Match는 불필요(+작동 안 함).
        # 코드·run_fwhm_sweep는 보존 — 재활성화는 아래 addWidget 주석만 해제.
        self._grp_fwhm_sweep = grp_sweep   # 미부착 보존
        # right_layout.addWidget(grp_sweep)

        self._sweep_outdir = None

        right_layout.addStretch(1)
        layout.addLayout(right_layout, stretch=1)

    # ---------------------------------------------------------
    # Data Loading Methods
    # ---------------------------------------------------------
    # Known literature FWHM values per (gas, author) for popular cross-section
    # files. Values are nm. Sources cited in comments.
    _KNOWN_LIT_FWHM = [
        # (gas substring, author/db substring, FWHM_nm, source)
        ("no2",    "vandaele",      0.01156, "Vandaele 2002 (FTS)"),
        ("chocho", "volkamer",      0.003,   "Volkamer 2005"),
        ("o4",     "thalman",       0.07,    "Thalman & Volkamer 2013"),
        ("o4",     "volkamer",      0.07,    "Thalman & Volkamer 2013"),
        ("o4",     "greenblatt",    0.5,     "Greenblatt 1990"),
        ("hcho",   "meller",        0.025,   "Meller & Moortgat 2000"),
        ("hono",   "stutz",         0.5,     "Stutz et al."),
        ("io",     "spietz",        0.5,     "Spietz 2005"),
        ("h2o",    "hitran",        0.0,     "HITRAN line list"),
        ("hitran", "",              0.0,     "HITRAN line list"),
    ]

    @classmethod
    def _guess_lit_fwhm(cls, filename: str):
        """Best-guess literature FWHM (nm) from a raw cross-section filename.

        Returns (fwhm_nm, source_label) or (None, reason)."""
        import re
        fname = os.path.basename(filename).lower()
        # 1. Known (gas, author) catalogue
        for gas_key, author_key, fwhm, src in cls._KNOWN_LIT_FWHM:
            if gas_key in fname and (author_key == "" or author_key in fname):
                return fwhm, src
        # 2. Wavelength grid embedded in filename, e.g. "(0.001nm)"
        m = re.search(r"\(\s*([0-9]*\.?[0-9]+)\s*nm\s*\)", fname)
        if m:
            grid = float(m.group(1))
            # lit FWHM ~ grid is a conservative starting point; user can tweak
            return grid, f"derived from filename grid {grid:g} nm"
        return None, "no match"

    def load_raw_reference(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open Raw Ref", dlg_dir("rawref"), "Data Files (*.txt *.csv *.dat)")
        dlg_dir("rawref", filename)
        if not filename: return
        try:
            wave_nm_ref, intensity_raw = DataIO.load_reference(filename)

            if wave_nm_ref is None:
                raise ValueError("No Wavelength data found in the reference file.")

            self.raw_wave = wave_nm_ref
            self.raw_data = intensity_raw

            base_name = os.path.basename(filename)

            self.gas_name = base_name.split('_')[ 0 ]

            # Auto-fill Lit FWHM from filename if we recognise the cross-section
            lit_msg = ""
            lit_fwhm, src = self._guess_lit_fwhm(filename)
            if lit_fwhm is not None:
                self.spin_lit_fwhm.setValue(round(lit_fwhm, 5))
                lit_msg = f"   |   Lit FWHM auto-set to {lit_fwhm:g} nm ({src})"

            self.lbl_raw_info.setText(
                f"Loaded: {base_name} (Gas: {self.gas_name}){lit_msg}"
            )

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

        # hitran.org가 HTTPS 전용으로 전환됨 → hapi 기본값 http:// 는 연결 거부됨.
        # 실제 fetch URL은 VARIABLES['GLOBAL_HOST']를 쓰는데, hapi/__init__.py 가
        # `from .hapi import *` 로 module-level GLOBAL_HOST 의 *copy* 를 패키지
        # namespace 에 만들어 두기 때문에, hapi.GLOBAL_HOST 만 바꿔서는 함수 안의
        # GLOBAL_HOST (URLError 에러 메시지에 박히는 그 변수) 가 그대로 http:// 로
        # 남는다. 안쪽 hapi.hapi 모듈까지 직접 패치해야 한다.
        try:
            hapi.VARIABLES['GLOBAL_HOST'] = "https://hitran.org"
            hapi.GLOBAL_HOST = "https://hitran.org"
            import hapi.hapi as _hapi_inner
            _hapi_inner.GLOBAL_HOST = "https://hitran.org"
            _hapi_inner.VARIABLES['GLOBAL_HOST'] = "https://hitran.org"
        except Exception:
            pass

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
            
            # hitran_data 폴더는 리포 루트 기준 절대경로로 고정 (CWD 무관하게 캐시 재사용)
            hitran_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'hitran_data'
            )
            os.makedirs(hitran_dir, exist_ok=True)
            hapi.db_begin(hitran_dir)

            # 이미 받아둔 라인리스트가 있으면 다운로드 생략 (오프라인 / hitran.org API 다운 시에도 동작)
            if table_name not in hapi.LOCAL_TABLE_CACHE:
                # hapi.fetch() 내부 urllib2.urlopen()에 timeout이 없어(hapi.py) 네트워크가
                # 아예 안 잡히는 환경(배 위 등)에서 GUI가 무한정 멈출 수 있다 — 소켓 기본
                # timeout을 걸어 15초 내 실패하게 만들고, 아래 except가 에러 메시지로 띄운다.
                import socket
                _prev_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(15)
                try:
                    hapi.fetch(table_name, gas_id, 1, 1e7/w_max, 1e7/w_min)
                finally:
                    socket.setdefaulttimeout(_prev_timeout)
            else:
                print(f"[HITRAN] '{table_name}' using local cache (skip download)")

            nu, coef = hapi.absorptionCoefficient_Voigt(
                SourceTables=table_name, Environment={'p': P, 'T': T}, 
                OmegaStep=0.02, HITRAN_units=False
            )
            
            wave_nm = 1e7 / nu
            sort_idx = np.argsort(wave_nm)
            self.raw_wave = wave_nm[sort_idx]
            self.raw_data = coef[sort_idx]
            
            self.gas_name = f"{gas_name}-HITRAN"
            # HITRAN cross-sections are computed from a line list ⇒ effectively
            # delta-function broadening; literature FWHM is 0.
            self.spin_lit_fwhm.setValue(0.0)
            self.lbl_raw_info.setText(
                f"HITRAN {gas_name} Generated   |   Lit FWHM auto-set to 0 (line list)"
            )
            
            self.ax[0].clear()
            self.ax[0].plot(self.raw_wave, self.raw_data, 'b-', label=f'HITRAN {gas_name}')
            self.ax[0].legend()
            self.canvas.draw()
        except Exception as e: 
            QMessageBox.critical(self, "Error", f"HITRAN Generation Failed:\n{e}")
        finally: 
            QApplication.restoreOverrideCursor()

    def load_target_wavelength(self, path: str = None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Open Wavelength", dlg_dir("wavecal"), "Text Files (*.txt *.csv)")
            dlg_dir("wavecal", path)
        if not path:
            return
        df = pd.read_csv(path, header=None)
        self.target_wavelengths = pd.to_numeric(df.iloc[:, 0], errors='coerce').dropna().values
        self.lbl_wave_info.setText(
            f"Loaded: {os.path.basename(path)} ({len(self.target_wavelengths)} px)"
        )
        self.lbl_wave_info.setStyleSheet("color: #2E7D32; font-weight: bold;")

    def _auto_pickup_calib_fwhm(self):
        """Pick one campaign wv_cal folder, then load Calib_*.txt and
        FWHM_Analysis_*.txt automatically. Remembers the folder per
        ROI across sessions via QSettings.

        Expected layout::

            <wv_cal_root>/
                roi1/  Calib_*.txt  FWHM_Analysis_*.txt
                roi2/  Calib_*.txt  FWHM_Analysis_*.txt

        Or a flat folder with both files directly inside.
        """
        import glob
        from PyQt6.QtCore import QSettings
        from PyQt6.QtWidgets import QInputDialog

        settings = QSettings("DoasisLab", "CAESARPro")
        last_root = settings.value("ref_gen/wv_cal_root", "", str)

        root = QFileDialog.getExistingDirectory(
            self,
            "Choose campaign wv_cal folder (e.g. ..\\CAESAR_Hot\\wv_cal)",
            last_root or "",
        )
        if not root:
            return
        settings.setValue("ref_gen/wv_cal_root", root)

        # Detect ROI subfolders (case-insensitive)
        try:
            entries = os.listdir(root)
        except Exception as exc:
            QMessageBox.critical(self, "Auto-pickup", f"Cannot read folder:\n{exc}")
            return
        rois = sorted([d for d in entries
                       if os.path.isdir(os.path.join(root, d))
                       and d.lower().startswith("roi")])

        if not rois:
            target_dir = root
            roi_label  = "(flat)"
        elif len(rois) == 1:
            target_dir = os.path.join(root, rois[0])
            roi_label  = rois[0]
        else:
            chosen, ok = QInputDialog.getItem(
                self, "Choose ROI",
                f"{len(rois)} ROI subfolders found:",
                rois, 0, False,
            )
            if not ok:
                return
            target_dir = os.path.join(root, chosen)
            roi_label  = chosen

        calib_hits = glob.glob(os.path.join(target_dir, "Calib_*.txt"))
        fwhm_hits  = glob.glob(os.path.join(target_dir, "FWHM_Analysis_*.txt"))

        messages = [f"ROI: {roi_label}", f"Folder: {target_dir}", ""]

        if calib_hits:
            # Pick the newest by mtime
            calib_path = max(calib_hits, key=os.path.getmtime)
            try:
                self.load_target_wavelength(path=calib_path)
                messages.append(f"Calib: {os.path.basename(calib_path)}")
            except Exception as exc:
                messages.append(f"Calib load failed: {exc}")
        else:
            messages.append(f"No Calib_*.txt found")

        if fwhm_hits:
            fwhm_path = max(fwhm_hits, key=os.path.getmtime)
            try:
                self.load_fwhm_profile(path=fwhm_path)
                messages.append(f"FWHM: {os.path.basename(fwhm_path)}")
            except Exception as exc:
                messages.append(f"FWHM load failed: {exc}")
        else:
            messages.append(f"No FWHM_Analysis_*.txt found")

        QMessageBox.information(self, "Auto-pickup result", "\n".join(messages))

    def load_fwhm_profile(self, path: str = None):
        """Loads the FWHM & Sigma profile generated from the calibration tool.

        When ``path`` is None, prompts the user via QFileDialog. When called
        programmatically (e.g. from ``_auto_pickup_calib_fwhm``) the caller
        passes the resolved path directly.
        """
        if path is None:
            filename, _ = QFileDialog.getOpenFileName(self, "Open FWHM Profile", dlg_dir("fwhm_profile"), "Text Files (*.txt *.csv)")
            dlg_dir("fwhm_profile", filename)
        else:
            filename = path
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
                px_raw = df['pixel'].values
                sg_raw = df['abssigma(nm)'].values
            elif len(df.columns) >= 4:
                # Fallback: force-extract column 1 (pixel) and column 4 (Sigma nm)
                px_raw = df.iloc[:, 0].values
                sg_raw = df.iloc[:, 3].values
            elif len(df.columns) >= 3:
                # 3-column layout: Pixel | FWHM(nm) | abs_Sigma(nm)
                px_raw = df.iloc[:, 0].values
                sg_raw = df.iloc[:, 2].values
            else:
                raise ValueError("Invalid FWHM file format. Cannot find Pixel and abs_Sigma(nm) columns.")

            # Coerce to numeric and drop non-data rows (e.g. a trailing 'AVERAGE'
            # summary line) so .astype(float) downstream never sees a string.
            px_num = pd.to_numeric(pd.Series(px_raw), errors='coerce')
            sg_num = pd.to_numeric(pd.Series(sg_raw), errors='coerce')
            valid = px_num.notna() & sg_num.notna()
            if valid.sum() == 0:
                raise ValueError("No numeric (Pixel, Sigma) rows found in FWHM file.")
            self.ils_pixels = px_num[valid].to_numpy()
            self.ils_sigmas = sg_num[valid].to_numpy()

            # Auto-fill Section 5 Center FWHM with mean FWHM derived from this profile
            mean_sigma_nm = float(np.nanmean(self.ils_sigmas))
            mean_fwhm_nm  = mean_sigma_nm * 2.35482
            auto_msg = ""
            if hasattr(self, 'spin_sweep_center') and 0.01 <= mean_fwhm_nm <= 10.0:
                self.spin_sweep_center.setValue(round(mean_fwhm_nm, 3))
                auto_msg = f"\nSection 5 Center FWHM auto-set to {mean_fwhm_nm:.3f} nm."

            self.lbl_fwhm_info.setText(
                f"Loaded: {len(self.ils_pixels)} Sigma points "
                f"(mean FWHM ≈ {mean_fwhm_nm:.3f} nm)"
            )
            self.lbl_fwhm_info.setStyleSheet("color: #2E7D32; font-weight: bold;")
            QMessageBox.information(self, "Success",
                                    f"FWHM Profile loaded successfully.{auto_msg}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load FWHM profile:\n{e}")

    def auto_load_lamp_data(self, intensity_array):
        """Automatically imports lamp data if available from the main application."""
        if intensity_array is not None:
            self.lamp_intensity = intensity_array
            # Guard widgets that only exist in older UI revisions
            if hasattr(self, 'radio_measured'):
                self.radio_measured.setChecked(True)
            if hasattr(self, 'spin_peak_px'):
                peak_idx = int(np.argmax(intensity_array))
                self.spin_peak_px.setValue(peak_idx)
            if hasattr(self, 'btn_load_lamp'):
                self.btn_load_lamp.setText("Lamp Synced from Calibration")
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
                added_var = (inst_sigma**2) - (lit_sigma**2)

                # Direct-sampling fallback (convolution with a delta = identity):
                #  - inst_sigma invalid (NaN / ≤0 from edge extrapolation), or
                #  - the extra-broadening kernel would be narrower than the
                #    integration grid, in which case the discrete Gaussian sum
                #    can miss the peak entirely and return ~0 instead of the
                #    true value.  Sampling the raw spectrum at target_w is the
                #    mathematically correct limit here.
                if (not np.isfinite(inst_sigma) or inst_sigma <= 0
                        or added_var <= (2.0 * hr_step)**2):
                    degraded_data[i] = float(f_raw(target_w))
                    continue

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

    # ---------------------------------------------------------
    # FWHM Sweep (uniform Gaussian) — Dr. Nam ILS tuning workflow
    # ---------------------------------------------------------
    @staticmethod
    def _convolve_uniform_gaussian(raw_wave, raw_data, target_wl, fwhm_nm, lit_fwhm_nm=0.0):
        """Uniform Gaussian ILS — single FWHM across the full wavelength axis.
        Mirrors calibration/ils_sigma_sweep.convolve_uniform_gaussian.
        """
        sigma_inst = fwhm_nm / 2.35482
        sigma_lit  = lit_fwhm_nm / 2.35482
        added_var  = max(1e-20, sigma_inst**2 - sigma_lit**2)
        sigma_eff  = np.sqrt(added_var)

        hr_step = 0.002
        hr_wave = np.arange(target_wl.min() - 5.0, target_wl.max() + 5.0, hr_step)
        f_raw   = interp1d(raw_wave, raw_data, kind="linear",
                           bounds_error=False, fill_value=0.0)
        hr_data = f_raw(hr_wave)

        result = np.zeros(len(target_wl))
        for i, w in enumerate(target_wl):
            kernel = (1.0 / (sigma_eff * np.sqrt(2 * np.pi))) * \
                     np.exp(-0.5 * ((hr_wave - w) / sigma_eff) ** 2)
            result[i] = float(np.dot(hr_data, kernel) * hr_step)
        return result

    def _pick_sweep_outdir(self):
        dirpath = QFileDialog.getExistingDirectory(self, "Choose FWHM Sweep Output Folder", dlg_dir("fwhm_sweep"))
        dlg_dir("fwhm_sweep", dirpath)
        if not dirpath:
            return
        self._sweep_outdir = dirpath
        self.lbl_sweep_outdir.setText(f"{dirpath}")
        self.lbl_sweep_outdir.setStyleSheet("color: #2E7D32; font-weight: bold;")

    def run_fwhm_sweep(self):
        """Generate references at FWHM = center ± n·step (uniform Gaussian).
        Saves N files Ref_{gas}_FWHM{fv:.3f}nm.dat to the output folder.
        Validation (RMS vs measured α → best FWHM) is performed in
        Setup tab → 🎯 FWHM Best-Match."""
        if self.raw_wave is None or self.target_wavelengths is None:
            QMessageBox.warning(self, "Warning",
                "Raw reference and target wavelength are required.")
            return
        if not self._sweep_outdir:
            QMessageBox.warning(self, "Warning", "Choose an output folder first.")
            return

        center = float(self.spin_sweep_center.value())
        step   = float(self.spin_sweep_step.value())
        n      = int(self.spin_sweep_n.value())
        lit_fw = float(self.spin_lit_fwhm.value())

        fwhm_list = sorted({round(center + step * k, 4)
                            for k in range(-n, n + 1)
                            if round(center + step * k, 4) > 0})
        if not fwhm_list:
            QMessageBox.warning(self, "Warning", "Empty FWHM list.")
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            os.makedirs(self._sweep_outdir, exist_ok=True)
            results = {}

            mask = (self.raw_wave >= self.target_wavelengths.min() - 10.0) & \
                   (self.raw_wave <= self.target_wavelengths.max() + 10.0)
            if not np.any(mask):
                raise ValueError("Raw reference does not overlap target wavelength range.")
            rw_m, rd_m = self.raw_wave[mask], self.raw_data[mask]

            for fv in fwhm_list:
                conv = self._convolve_uniform_gaussian(
                    rw_m, rd_m, self.target_wavelengths, fv, lit_fw
                )
                results[fv] = conv
                fname = f"Ref_{self.gas_name}_FWHM{fv:.3f}nm.dat"
                header = (f"Gas={self.gas_name}  FWHM={fv:.3f}nm  "
                          f"Lit_FWHM={lit_fw}nm  Generated by CAESAR Pro sweep\n"
                          f"col0=wavelength_nm  col1=cross_section")
                # 2-column: 파장축을 함께 저장해야 FWHM Best-Match가 α 그리드에
                # 파장 기준으로 정확히 보간 정렬할 수 있다(인덱스 정렬은 sub-window에서 깨짐).
                np.savetxt(os.path.join(self._sweep_outdir, fname),
                           np.column_stack([self.target_wavelengths, conv]),
                           fmt="%.8e", header=header)

            # Overlay all swept references on the top panel
            ax_top = self.fig.axes[0]
            ax_top.clear()
            cmap = plt.get_cmap('viridis')
            for i, fv in enumerate(fwhm_list):
                color = cmap(i / max(1, len(fwhm_list) - 1))
                ax_top.plot(self.target_wavelengths, results[fv],
                            color=color, lw=0.8, alpha=0.7,
                            label=f"FWHM={fv:.3f}nm")
            ax_top.set_xlabel("Wavelength (nm)")
            ax_top.set_ylabel("Cross Section")
            ax_top.set_title(f"FWHM Sweep — {self.gas_name} ({len(fwhm_list)} versions)")
            ax_top.legend(fontsize=7, ncol=2)

            # Clear bottom panel + hint that validation moved to Setup tab
            ax_bottom = self.fig.axes[1]
            ax_bottom.clear()
            ax_bottom.text(0.5, 0.5,
                           "Validation moved to:\nSetup tab →  FWHM Best-Match",
                           ha="center", va="center", transform=ax_bottom.transAxes,
                           fontsize=11, color="#555", style="italic")
            ax_bottom.set_xticks([]); ax_bottom.set_yticks([])

            self.canvas.draw()

            QMessageBox.information(
                self, "FWHM Sweep Complete",
                f"Saved {len(fwhm_list)} reference files to:\n"
                f"{self._sweep_outdir}\n\n"
                f"FWHM range: {fwhm_list[0]:.3f} ~ {fwhm_list[-1]:.3f} nm "
                f"(step {step})\n\n"
                f"Next: Setup tab →  FWHM Best-Match → point to this folder + α."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"FWHM sweep failed:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()

    def save_reference(self):
        """Saves the fully processed reference spectrum with metadata header."""
        filters = "Data Files (*.dat);;Text Files (*.txt);;CSV Files (*.csv)"
        _start = os.path.join(dlg_dir("ref_save"), self.suggested_filename) if dlg_dir("ref_save") else self.suggested_filename
        filename, _ = QFileDialog.getSaveFileName(self, "Save Reference", _start, filters)
        dlg_dir("ref_save", filename)
        
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
