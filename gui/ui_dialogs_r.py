"""gui/ui_dialogs_r.py
R 커브 & R 시계열: R_GeneratorDialog, _RTrendWorker, RTrendMonitorDialog
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
                             QSplashScreen, QDialogButtonBox, QStackedWidget, QFormLayout, QTextEdit)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPixmap


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
        filename, _ = QFileDialog.getOpenFileName(self, f"Select Spectrum {slot}", dlg_dir("spectrum"), "Data Files (*.txt *.dat *.csv)")
        dlg_dir("spectrum", filename)
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
            _start = os.path.join(dlg_dir("rcurve_save"), default_fname) if dlg_dir("rcurve_save") else default_fname
            save_path, _ = QFileDialog.getSaveFileName(self, "Save R-Curve", _start, "CSV (*.csv)")
            dlg_dir("rcurve_save", save_path)

            if save_path:
                pd.DataFrame({'Wavelength': self.wl, 'Reflectivity': r_curve}).to_csv(save_path, index=False)
                self.r_curve_result = r_curve  # Expose result so caller can load it directly
                QMessageBox.information(self, "Success", "Reflectivity curve saved successfully!")
                self.accept()
                
        except Exception as e:
            QMessageBox.critical(self, "Calculation Error", f"Failed to calculate R(λ):\n{e}")

# =============================================================================
# R Trend Monitor Components (UI + Worker)
# =============================================================================

class _LiveStream:
    """sys.stdout 대체 — write() 호출마다 log 시그널로 실시간 전달."""
    def __init__(self, emit_fn):
        self._emit = emit_fn
        self._buf  = ""

    def write(self, text):
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)

    def flush(self):
        if self._buf:
            self._emit(self._buf)
            self._buf = ""

    def isatty(self):
        return False


class _RTrendWorker(QThread):
    """백그라운드에서 r_trend_monitor.main()을 실행."""
    log        = pyqtSignal(str)
    finished   = pyqtSignal(str)    # 결과 폴더 경로
    # 시계열 데이터와 테이블 정보 전송용 시그널 확장
    data_ready = pyqtSignal(object, object, object, object)

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg

    def run(self):
        try:
            import sys as _sys, os as _os
            _tools_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
            if _tools_dir not in _sys.path:
                _sys.path.insert(0, _tools_dir)
            
            # 정적 분석기(Pylance) 가짜 경고 무시
            import r_trend_monitor as rtm # type: ignore
            cfg = self.cfg

            # 사용자 설정 오버라이드
            rtm.COLD_DIR         = cfg.get("cold_dir", "")
            rtm.HOT_DIR          = cfg.get("hot_dir",  "")
            rtm.WAVE_CAL_COLD    = cfg.get("wl_cold",  "")
            rtm.WAVE_CAL_HOT     = cfg.get("wl_hot",   "")      # PNs(roi1)=CH2
            rtm.WAVE_CAL_HOT_ANS = cfg.get("wl_hot_ans", "")    # ANs(roi2)=CH3
            rtm.OUTPUT_DIR       = cfg.get("out_dir",  ".")
            rtm.COLD_FILES       = cfg.get("cold_files", None)  
            rtm.HOT_FILES        = cfg.get("hot_files",  None)  
            rtm.SHOW_PLOT        = False
            rtm.CAVITY_LEN       = cfg.get("cavity_len", rtm.CAVITY_LEN)
            rtm.RL_FACTOR        = cfg.get("rl_factor",  rtm.RL_FACTOR)

            _tz_map = {"UTC": rtm._UTC, "KST": rtm._KST_TZ}
            rtm.COLD_TS_TZ    = _tz_map.get(cfg.get("cold_tz", "UTC"), rtm._UTC)
            rtm.HOT_TS_TZ     = _tz_map.get(cfg.get("hot_tz",  "KST"), rtm._KST_TZ)
            rtm.HOT_ANS_TS_TZ = rtm.HOT_TS_TZ   

            # stdout 리다이렉트
            _live = _LiveStream(self.log.emit)
            old_stdout = _sys.stdout
            _sys.stdout = _live
            _rtm_result = None
            try:
                _rtm_result = rtm.main()
            finally:
                _sys.stdout = old_stdout
                _live.flush()

            _out_dir = rtm.OUTPUT_DIR
            if _rtm_result and len(_rtm_result) >= 4:
                self.data_ready.emit(_rtm_result[0], _rtm_result[1], _rtm_result[2], _rtm_result[3])
                _out_dir = _rtm_result[3] or _out_dir

            self.finished.emit(_out_dir)

        except Exception as e:
            import traceback
            self.log.emit(f"[오류] {e}\n{traceback.format_exc()}")
            self.finished.emit("")


class RTrendMonitorDialog(QDialog):
    """R Trend Monitor 설정 + 실행 + 로그 표시 + 테이블/스펙트럼 플롯 다이얼로그."""

    data_ready = pyqtSignal(object, object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("R Trend Monitor — 거울 반사율 시계열 & 파장 분석")
        self.resize(1300, 850) # 해상도 약간 확장
        self._worker = None
        self._cold_files_list: list = []
        self._hot_files_list:  list = []
        self._t_start = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_elapsed)
        self._all_results = [] # 테이블 클릭용 데이터 저장소
        
        self._init_ui()
        if parent is not None:
            if hasattr(parent, 'spin_d_len'):
                self._spin_cavity_len.setValue(parent.spin_d_len.value())
            if hasattr(parent, 'spin_rl_factor'):
                self._spin_rl.setValue(parent.spin_rl_factor.value())

    def _pick_dir(self, line_edit):
        d = QFileDialog.getExistingDirectory(self, "폴더 선택", dlg_dir("r_folder"))
        dlg_dir("r_folder", d)
        if d: line_edit.setText(d)

    def _pick_file(self, line_edit):
        f, _ = QFileDialog.getOpenFileName(
            self, "파일 선택", dlg_dir("r_file"), "텍스트 파일 (*.txt *.dat *.csv);;모든 파일 (*)")
        dlg_dir("r_file", f)
        if f: line_edit.setText(f)

    @staticmethod
    def _norm_date(s, default):
        """'20260531' 또는 '2026-05-31' → '2026-05-31'. 빈 값이면 default."""
        s = (s or "").strip().replace("-", "")
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        return default

    @staticmethod
    def _files_in_range(directory, lo, hi):
        """directory(및 하위폴더)에서 파일명 날짜(YYYY-MM-DD)가 [lo,hi]인 .dat 정렬 반환.
        부모폴더를 주면 월별 하위폴더를 함께 스캔해 월 경계를 넘는다."""
        import glob, re
        pats = (glob.glob(os.path.join(directory, "*.dat")) +
                glob.glob(os.path.join(directory, "**", "*.dat"), recursive=True))
        out = []
        for f in set(pats):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(f))
            if m and lo <= m.group(1) <= hi:
                out.append(f)
        return sorted(out)

    def _init_ui(self):
        main = QVBoxLayout(self)

        # ── 1. 상단: 입력 폼 ──
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        def row_data(label, dir_attr, files_attr, hint_attr, tz_attr, tz_default):
            le = QLineEdit()
            le.setPlaceholderText("폴더 경로 또는 파일 N개 선택됨")
            btn_dir = QPushButton("📂 폴더")
            btn_dir.setFixedWidth(70)
            btn_fil = QPushButton("📄 파일")
            btn_fil.setFixedWidth(70)
            tz_combo = QComboBox()
            tz_combo.addItems(["KST", "UTC (−9h)"])
            tz_combo.setCurrentText(tz_default)
            tz_combo.setFixedWidth(96)
            setattr(self, tz_attr, tz_combo)
            hint = QLabel()
            hint.setStyleSheet("color: #777; font-size: 10px;")
            setattr(self, hint_attr, hint)

            def pick_dir():
                d = QFileDialog.getExistingDirectory(self, "폴더 선택", dlg_dir("r_folder"))
                dlg_dir("r_folder", d)
                if d:
                    le.setText(d)
                    setattr(self, files_attr, [])
                    hint.setText("")

            def pick_files():
                files, _ = QFileDialog.getOpenFileNames(self, "파일 선택 (복수 가능)", dlg_dir("r_files"), "DAT 파일 (*.dat);;모든 파일 (*)")
                if files:
                    dlg_dir("r_files", files[0])
                if files:
                    le.setText("")
                    setattr(self, files_attr, files)
                    hint.setText(f"  {len(files)}개 파일 선택됨: {', '.join(os.path.basename(f) for f in files[:3])}...")

            btn_dir.clicked.connect(pick_dir)
            btn_fil.clicked.connect(pick_files)

            h = QHBoxLayout()
            h.addWidget(le); h.addWidget(btn_dir); h.addWidget(btn_fil)
            h.addWidget(QLabel("TZ:")); h.addWidget(tz_combo)
            w = QWidget(); w.setLayout(h)
            v = QVBoxLayout(); v.setContentsMargins(0, 0, 0, 2)
            v.addWidget(w); v.addWidget(hint)
            wv = QWidget(); wv.setLayout(v)
            form.addRow(label, wv)
            setattr(self, dir_attr, le)

        def row_file(label, attr):
            le = QLineEdit()
            btn = QPushButton("…"); btn.setFixedWidth(32)
            btn.clicked.connect(lambda: self._pick_file(le))
            h = QHBoxLayout(); h.addWidget(le); h.addWidget(btn)
            w = QWidget(); w.setLayout(h)
            form.addRow(label, w)
            setattr(self, attr, le)

        def row_dir(label, attr):
            le = QLineEdit()
            btn = QPushButton("…"); btn.setFixedWidth(32)
            btn.clicked.connect(lambda: self._pick_dir(le))
            h = QHBoxLayout(); h.addWidget(le); h.addWidget(btn)
            w = QWidget(); w.setLayout(h)
            form.addRow(label, w)
            setattr(self, attr, le)

        row_data("Cold 데이터:",     "_le_cold_dir", "_cold_files_list", "_hint_cold", "_tz_cold", "UTC (−9h)")
        row_data("Hot 데이터:",      "_le_hot_dir",  "_hot_files_list",  "_hint_hot", "_tz_hot", "KST")

        # 날짜 범위 (월 경계 넘어 선택 — 비우면 폴더 전체). 부모폴더(예: CAESAR_Cold)를
        # 주고 날짜범위를 넣으면 2026-05 / 2026-06 하위폴더를 함께 스캔해 5/31↔6/1 연결.
        self._le_date_start = QLineEdit(); self._le_date_start.setPlaceholderText("YYYYMMDD 시작 (예: 20260531)")
        self._le_date_end   = QLineEdit(); self._le_date_end.setPlaceholderText("YYYYMMDD 끝 (예: 20260601)")
        _dr = QHBoxLayout()
        _dr.addWidget(self._le_date_start); _dr.addWidget(QLabel("~")); _dr.addWidget(self._le_date_end)
        _drw = QWidget(); _drw.setLayout(_dr)
        form.addRow("날짜 범위(선택):", _drw)

        row_file("Cold 파장 보정 파일:",        "_le_wl_cold")
        row_file("Hot PNs(roi1) 파장 보정:",   "_le_wl_hot")
        row_file("Hot ANs(roi2) 파장 보정:",   "_le_wl_hot_ans")
        row_dir("결과 저장 폴더:",             "_le_out_dir")
        self._le_out_dir.setText(".")

        # 캐비티 파라미터
        from PyQt6.QtWidgets import QDoubleSpinBox as _DSB
        cavity_row = QHBoxLayout()
        cavity_row.addWidget(QLabel("Cavity 길이 (cm):"))
        self._spin_cavity_len = _DSB(); self._spin_cavity_len.setRange(1.0, 10000.0); self._spin_cavity_len.setDecimals(2); self._spin_cavity_len.setValue(51.8); self._spin_cavity_len.setFixedWidth(90)
        cavity_row.addWidget(self._spin_cavity_len); cavity_row.addSpacing(20)
        cavity_row.addWidget(QLabel("RL Factor:"))
        self._spin_rl = _DSB(); self._spin_rl.setRange(0.001, 1.0); self._spin_rl.setDecimals(4); self._spin_rl.setSingleStep(0.001); self._spin_rl.setValue(1.0); self._spin_rl.setFixedWidth(80)
        cavity_row.addWidget(self._spin_rl); cavity_row.addStretch()
        cw = QWidget(); cw.setLayout(cavity_row)
        form.addRow("캐비티 설정:", cw)

        main.addLayout(form)

        btn_run = QPushButton("▶  계산 시작")
        btn_run.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; height: 36px;")
        btn_run.clicked.connect(self._run)
        main.addWidget(btn_run)
        self._btn_run = btn_run

        # 진행 표시줄
        prog_row = QHBoxLayout()
        self._progress = QProgressBar(); self._progress.setRange(0, 0); self._progress.setFixedHeight(16); self._progress.setVisible(False)
        self._lbl_elapsed = QLabel(""); self._lbl_elapsed.setStyleSheet("color: #555; font-size: 11px; min-width: 80px;")
        prog_row.addWidget(self._progress, stretch=1); prog_row.addWidget(self._lbl_elapsed)
        main.addLayout(prog_row)

        # ── 2. 중단 및 하단: 스플리터 레이아웃 ──
        # Top Splitter: [로그(좌)] | [테이블(우)]
        # Bottom Splitter: [시계열 플롯(좌)] | [스펙트럼 플롯(우)]
        # Main Splitter: Top / Bottom 분리
        
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 2-1. 상단 스플리터 (로그 & 테이블)
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._log = QTextEdit(); self._log.setReadOnly(True); self._log.setFontFamily("Consolas"); self._log.setFontPointSize(9)
        top_splitter.addWidget(self._log)
        
        self.tableWidget = QTableWidget(0, 4)
        self.tableWidget.setHorizontalHeaderLabels(["시간(KST)", "파일명", "채널", "R_mean (%)"])
        self.tableWidget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tableWidget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tableWidget.itemSelectionChanged.connect(self._on_table_row_selected)
        top_splitter.addWidget(self.tableWidget)
        top_splitter.setSizes([400, 600])

        # 2-2. 하단 스플리터 (시계열 & 스펙트럼 플롯)
        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 시계열
        _date_axis = pg.DateAxisItem(orientation='bottom')
        self._pw = pg.PlotWidget(axisItems={'bottom': _date_axis}, title="R 시계열 (Cold/Hot)")
        self._pw.setBackground('w'); self._pw.showGrid(x=True, y=True, alpha=0.3)
        self._pw.setLabel('left', 'R mean (%)'); self._pw.setLabel('bottom', 'Time (KST)')
        bottom_splitter.addWidget(self._pw)

        # 파장별 스펙트럼 (신규)
        self._spectrum_pw = pg.PlotWidget(title="파장별 R(λ) 곡선")
        self._spectrum_pw.setBackground('w'); self._spectrum_pw.showGrid(x=True, y=True, alpha=0.3)
        self._spectrum_pw.setLabel('left', 'Reflectance R'); self._spectrum_pw.setLabel('bottom', 'Wavelength (nm)')
        self._spectrum_pw.addLegend()
        bottom_splitter.addWidget(self._spectrum_pw)
        bottom_splitter.setSizes([600, 400])

        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(bottom_splitter)
        main_splitter.setSizes([300, 500])

        main.addWidget(main_splitter, stretch=1)

    def _run(self):
        cold_dir   = self._le_cold_dir.text().strip()
        hot_dir    = self._le_hot_dir.text().strip()
        cold_files = self._cold_files_list or None  
        hot_files  = self._hot_files_list  or None

        if not (cold_dir or cold_files) and not (hot_dir or hot_files):
            QMessageBox.warning(self, "입력 오류", "Cold 또는 Hot 데이터의 폴더나 파일을 지정해주세요.")
            return

        # 날짜 범위가 있으면 폴더를 재귀 스캔해 월 경계를 넘는 파일 목록을 구성한다.
        ds = self._le_date_start.text().strip()
        de = self._le_date_end.text().strip()
        if ds or de:
            lo = self._norm_date(ds, "0000-00-00")
            hi = self._norm_date(de, "9999-99-99")
            if cold_dir:
                sel = self._files_in_range(cold_dir, lo, hi)
                if sel:
                    cold_files = sel
            if hot_dir:
                sel = self._files_in_range(hot_dir, lo, hi)
                if sel:
                    hot_files = sel
            self._log.append(
                f"[날짜범위] {lo} ~ {hi}  →  Cold {len(cold_files or [])}개 / Hot {len(hot_files or [])}개")

        cfg = {
            "cold_dir":   cold_dir,
            "hot_dir":    hot_dir,
            "cold_files": cold_files,
            "hot_files":  hot_files,
            "wl_cold":    self._le_wl_cold.text().strip(),
            "wl_hot":     self._le_wl_hot.text().strip(),
            "wl_hot_ans": self._le_wl_hot_ans.text().strip(),
            "out_dir":    self._le_out_dir.text().strip() or ".",
            "cold_tz":    "UTC" if self._tz_cold.currentText().startswith("UTC") else "KST",
            "hot_tz":     "UTC" if self._tz_hot.currentText().startswith("UTC")  else "KST",
            "cavity_len": self._spin_cavity_len.value(),
            "rl_factor":  self._spin_rl.value(),
        }

        self._log.clear(); self._pw.clear(); self._spectrum_pw.clear()
        self.tableWidget.setRowCount(0); self._all_results.clear()
        self._btn_run.setEnabled(False)
        self._progress.setVisible(True)
        self._t_start = time.time(); self._timer.start(1000)
        self._lbl_elapsed.setText("경과: 00:00")
        
        self._worker = _RTrendWorker(cfg)
        self._worker.log.connect(self._log.append)
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_data_ready(self, cold_results, hot_pns_results, hot_ans_results, out_dir):
        """연산된 결과를 바탕으로 1) 시계열 그리기, 2) 테이블 채우기를 수행합니다."""
        self._pw.clear()
        self._pw.addLegend(offset=(10, 10))
        self._all_results.clear()
        self.tableWidget.setRowCount(0)

        def _plot_and_fill_table(results, color_hex, name, ch_key):
            if not results: return
            
            # 시계열 플롯
            times  = np.array([r["timestamp"].replace(tzinfo=None).timestamp() for r in results], dtype=float)
            r_pct  = np.array([r["r_mean"] * 100.0 for r in results], dtype=float)
            r_std  = np.array([r["r_std"]  * 100.0 for r in results], dtype=float)

            pen  = pg.mkPen(color=color_hex, width=2)
            brsh = pg.mkBrush(color_hex)
            self._pw.plot(times, r_pct, pen=pen, symbol='o', symbolSize=7, symbolBrush=brsh, name=name)
            err = pg.ErrorBarItem(x=times, y=r_pct, top=r_std, bottom=r_std, beam=0, pen=pg.mkPen(color_hex, width=1, style=Qt.PenStyle.DotLine))
            self._pw.addItem(err)

            # 테이블 채우기 및 로컬 데이터 저장 (dat 파일 경로 유추)
            for r in results:
                row_idx = self.tableWidget.rowCount()
                self.tableWidget.insertRow(row_idx)
                
                t_str = r["timestamp"].strftime('%Y-%m-%d %H:%M')
                fname = r["filename"]
                r_val = r["r_mean"] * 100.0
                
                self.tableWidget.setItem(row_idx, 0, QTableWidgetItem(t_str))
                self.tableWidget.setItem(row_idx, 1, QTableWidgetItem(fname))
                self.tableWidget.setItem(row_idx, 2, QTableWidgetItem(name))
                self.tableWidget.setItem(row_idx, 3, QTableWidgetItem(f"{r_val:.4f}"))
                
                # 원본 dat 파일 이름 추론 로직 (저장된 규칙)
                file_date = "-".join(fname.split("-")[:3])
                base_fname = os.path.splitext(fname)[0]
                # 채널별 저장 폴더 매핑
                ch_subdir = {
                    "cold":    "R_Cold",
                    "hot_pns": "R_Hot_PNs",
                    "hot_ans": "R_Hot_ANs",
                }.get(ch_key, "R_Cold")
                dat_path = os.path.join(out_dir, ch_subdir, file_date, f"{base_fname}_R.dat")

                # 만약 지정된 경로가 없으면 루트 폴더(out_dir/file_date)도 확인
                if not os.path.exists(dat_path):
                    dat_path = os.path.join(out_dir, file_date, f"{base_fname}_R.dat")

                self._all_results.append({
                    "channel": ch_key,
                    "color": color_hex,
                    "dat_path": dat_path,
                    "roi": r.get("fit_window_nm", (400, 500))
                })

        _plot_and_fill_table(cold_results,    '#2196F3', 'Cold', 'cold')
        _plot_and_fill_table(hot_pns_results, '#FF6F00', 'Hot PNs', 'hot_pns')
        _plot_and_fill_table(hot_ans_results, '#D32F2F', 'Hot ANs', 'hot_ans')

        # Y축 자동 조정
        all_r = ([r["r_mean"] * 100 for r in cold_results] +
                 [r["r_mean"] * 100 for r in hot_pns_results] +
                 [r["r_mean"] * 100 for r in hot_ans_results])
        if all_r:
            # 0.9999 근처 변동이 보이도록 타이트하게 확대. (예전 ±0.05%는 너무 넓어
            # 전부 평평하게 보였다.) 중앙값 ±max(4σ, 0.0015%)로 줌.
            arr = np.array(all_r, dtype=float)
            med = float(np.median(arr)); sd = float(np.std(arr))
            margin = max(sd * 4.0, 0.0015)   # percent 단위 (0.0015% = 1.5e-5)
            self._pw.setYRange(med - margin, min(med + margin, 100.0 + 5e-4), padding=0)

        # 부모 윈도우로 결과 전달 — 이게 없으면 워커 데이터가 이 다이얼로그
        # 내부 플롯에만 들어가고, app_window 가 연결한 Setup 탭 R/Leff 시계열
        # (_update_setup_rt_charts)·Daily Run 차트(_update_daily_rt_chart)는
        # 빈 채로 남는다. 다이얼로그의 data_ready 를 여기서 다시 emit 한다.
        self.data_ready.emit(cold_results, hot_pns_results, hot_ans_results, out_dir)

    def _on_table_row_selected(self):
        """테이블 행 클릭 시 해당 파일의 _R.dat를 읽어 스펙트럼 플롯에 렌더링"""
        sel = self.tableWidget.selectedItems()
        if not sel: return
        
        row = sel[0].row()
        if row >= len(self._all_results): return
        
        info = self._all_results[row]
        dat_path = info["dat_path"]
        
        self._spectrum_pw.clear()
        
        if not os.path.exists(dat_path):
            self._spectrum_pw.setTitle(f"데이터 파일 없음: {os.path.basename(dat_path)}")
            return
            
        try:
            # 3번째 줄부터 데이터 시작 (skiprows=2)
            data = np.loadtxt(dat_path, skiprows=2)
            wave = data[:, 0]
            r_raw = data[:, 1]
            r_fit = data[:, 2]
            
            roi_min, roi_max = info["roi"]
            color = info["color"]

            self._spectrum_pw.setTitle(f"R(λ) - {os.path.basename(dat_path)}")
            
            # 원본 데이터 (흐릿한 점)
            self._spectrum_pw.plot(wave, r_raw, pen=None, symbol='o', symbolSize=3, symbolBrush=(150,150,150,150), name="Raw Data")
            # 피팅 데이터 (선명한 선)
            self._spectrum_pw.plot(wave, r_fit, pen=pg.mkPen(color, width=2.5), name="5th Poly Fit")
            
            # ROI 영역 표시
            lr = pg.LinearRegionItem([roi_min, roi_max], movable=False, brush=(0,255,0,20))
            self._spectrum_pw.addItem(lr)
            
        except Exception as e:
            self._spectrum_pw.setTitle(f"플롯 실패: {e}")

    def _tick_elapsed(self):
        if self._t_start is not None:
            m, s = divmod(int(time.time() - self._t_start), 60)
            self._lbl_elapsed.setText(f"경과: {m:02d}:{s:02d}")

    def _on_done(self, out_dir: str):
        self._timer.stop(); self._progress.setVisible(False)
        m, s = divmod(int(time.time() - self._t_start) if self._t_start else 0, 60)
        self._lbl_elapsed.setText(f"완료 ({m:02d}:{s:02d})")
        self._t_start = None; self._btn_run.setEnabled(True)
        
        if out_dir:
            self._log.append(f"\n✅ 완료 → 결과 폴더: {out_dir}")
        else:
            self._log.append("\n❌ 오류 발생 — 위 로그를 확인하세요.")

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.quit()
            if not self._worker.wait(3000):
                self._worker.terminate(); self._worker.wait()
        super().closeEvent(event)