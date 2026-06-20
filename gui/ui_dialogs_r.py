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
                             QSplashScreen, QDialogButtonBox, QStackedWidget, QFormLayout,
                             QTextEdit, QFrame)
from PyQt6.QtCore import Qt, QThread, QTimer, QSettings, pyqtSignal
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


class _RTExportWorker(QThread):
    """α용 R(t) npz 저장 워커 — 채널별 compute_rt_knots(병렬) → save_rt.
    tasks: list of (label, raw_dir, wave_nm, RTConfig, file_list, out_path)."""
    log      = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)   # (done, total, channel label)
    finished = pyqtSignal(str)   # 요약 문자열

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks

    def run(self):
        import sys as _sys, os as _os, traceback
        _td = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
        if _td not in _sys.path:
            _sys.path.insert(0, _td)
        try:
            import rt_precompute as RTP
        except Exception as e:
            self.finished.emit(f"ERROR: rt_precompute 임포트 실패: {e}")
            return
        done = []
        for label, rdir, wave, cfg, flist, outp in self.tasks:
            try:
                self.log.emit(f"[{label}] R(t) 병렬 계산 중…")
                all_files = RTP._RT._resolve_files(rdir, flist)
                ks, od, wv = RTP.compute_rt_knots(
                    rdir, wave, cfg, file_list=flist, parallel=True,
                    progress_cb=lambda d, t, _l=label: self.progress.emit(d, t, _l))
                if len(ks) == 0:
                    self.log.emit(f"[{label}] ⚠️ knot 0개 — 저장 안 함")
                    continue
                processed = [_os.path.basename(f) for f in all_files]
                RTP.save_rt(outp, ks, od, wv, label=label, config=cfg,
                            processed_files=processed)
                self.log.emit(f"[{label}] ✅ {len(ks)} knots ({len(processed)}파일) → {_os.path.basename(outp)}")
                done.append(f"{label}({len(ks)})")
            except Exception as e:
                self.log.emit(f"[{label}] ❌ 실패: {e}\n{traceback.format_exc()}")
        self.finished.emit("  |  ".join(done) if done else "저장된 R(t) 없음")


class _RTAppendWorker(QThread):
    """α용 R(t) 증분 추가 워커 — 채널별 append_rt(병렬) → 기존 npz에 머지.
    tasks: list of (label, raw_dir, wave_nm, RTConfig, file_list, out_path)"""
    log      = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str)

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks

    def run(self):
        import sys as _sys, os as _os, traceback
        _td = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
        if _td not in _sys.path:
            _sys.path.insert(0, _td)
        try:
            import rt_precompute as RTP
        except Exception as e:
            self.finished.emit(f"ERROR: rt_precompute 임포트 실패: {e}")
            return
        done = []
        for label, rdir, wave, cfg, flist, outp in self.tasks:
            try:
                self.log.emit(f"[{label}] 증분 추가 중…")
                n_new, added = RTP.append_rt(
                    outp, rdir, wave, cfg, file_list=flist, parallel=True,
                    progress_cb=lambda d, t, _l=label: self.progress.emit(d, t, _l))
                if n_new == 0 and added:
                    self.log.emit(f"[{label}] ⚠️ {len(added)}개 파일 처리했으나 유효 knot 0개 (He/ZA 없음?)")
                elif n_new == 0:
                    self.log.emit(f"[{label}] 새 파일 없음 — 건너뜀")
                else:
                    self.log.emit(f"[{label}] ✅ +{n_new} knots ({len(added)}개 파일) → {_os.path.basename(outp)}")
                    done.append(f"{label}(+{n_new})")
            except Exception as e:
                self.log.emit(f"[{label}] ❌ 실패: {e}\n{traceback.format_exc()}")
        self.finished.emit("  |  ".join(done) if done else "추가된 knot 없음")


# ── 채널 색상 팔레트 ─────────────────────────────────────────────────────────
_CH_COLORS = [
    '#2196F3',  # blue
    '#FF6F00',  # orange
    '#D32F2F',  # red
    '#388E3C',  # green
    '#7B1FA2',  # purple
    '#0097A7',  # teal
    '#795548',  # brown
]


class _ChannelRWorker(QThread):
    """채널별 scan_directory() 호출 — 계산 시작 버튼용.
    channel_cfgs: list of {label, raw_dir, wave_nm, rtcfg, file_list, color}"""
    log        = pyqtSignal(str)
    finished   = pyqtSignal(str)
    data_ready = pyqtSignal(object, object, object, object)

    def __init__(self, channel_cfgs, out_dir, cavity_len, rl_factor):
        super().__init__()
        self.channel_cfgs = channel_cfgs
        self.out_dir      = out_dir
        self.cavity_len   = cavity_len
        self.rl_factor    = rl_factor

    def run(self):
        import sys as _sys, os as _os, traceback, io, contextlib
        _td = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
        if _td not in _sys.path:
            _sys.path.insert(0, _td)
        try:
            import r_trend_monitor as rtm
        except Exception as e:
            self.finished.emit(f"ERROR: {e}")
            return

        rtm.CAVITY_LEN = self.cavity_len
        rtm.RL_FACTOR  = self.rl_factor
        _os.makedirs(self.out_dir, exist_ok=True)
        all_results = []

        for ch_cfg in self.channel_cfgs:
            label   = ch_cfg["label"]
            raw_dir = ch_cfg["raw_dir"]
            wave_nm = ch_cfg["wave_nm"]
            rtcfg   = ch_cfg["rtcfg"]
            flist   = ch_cfg.get("file_list")
            color   = ch_cfg["color"]

            self.log.emit(f"[{label}] scan_directory 시작…")
            try:
                from datetime import timezone, timedelta
                ts_tz  = timezone(timedelta(hours=rtcfg.ts_tz_hours))
                _buf   = io.StringIO()
                with contextlib.redirect_stdout(_buf):
                    results = rtm.scan_directory(
                        raw_dir, wave_nm, file_list=flist,
                        col_press=rtcfg.col_press, col_temp=rtcfg.col_temp,
                        ts_tz=ts_tz,
                        spec_start=rtcfg.spec_start, spec_end=rtcfg.spec_end,
                        fit_window_nm=rtcfg.fit_window_nm,
                        parallel=True)
                for line in _buf.getvalue().splitlines():
                    if line.strip():
                        self.log.emit(line)

                if results:
                    rtm.save_dat(results,
                                 _os.path.join(self.out_dir, f"{label}_R_trend.dat"))
                    rtm.save_r_curves_per_file(results, f"R_{label}", self.out_dir)
                    self.log.emit(f"[{label}] ✅ {len(results)} 사이클")
                else:
                    self.log.emit(f"[{label}] ⚠️ 결과 없음")

                all_results.append({"label": label, "results": results or [], "color": color})

            except Exception as e:
                self.log.emit(f"[{label}] ❌ {e}\n{traceback.format_exc()}")
                all_results.append({"label": label, "results": [], "color": color})

        # arg0 = new-format [{label, results, color}]; arg1/arg2 = [] (unused)
        self.data_ready.emit(all_results, [], [], self.out_dir)
        self.finished.emit(self.out_dir)


class _HeCheckWorker(QThread):
    """증분 추가 전 He 플래그 사전 스캔 — 메인 스레드 얼음 방지.
    tasks: list of (label, raw_dir, wave_nm, RTConfig, file_list, out_path)"""
    finished = pyqtSignal(object)   # list of (label, raw_dir, wave, rtcfg, flist, out_path, new_files, he_map)
    progress = pyqtSignal(str)      # 채널 이름

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks

    def run(self):
        import sys as _sys, os as _os
        _td = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
        if _td not in _sys.path:
            _sys.path.insert(0, _td)
        try:
            import rt_precompute as RTP
        except Exception as e:
            self.finished.emit([])
            return

        results = []
        for label, raw_dir, wave, rtcfg, flist, out_path in self.tasks:
            self.progress.emit(label)
            try:
                new_files, he_map = RTP.check_new_files(out_path, raw_dir, flist)
            except Exception:
                new_files, he_map = [], {}
            results.append((label, raw_dir, wave, rtcfg, flist, out_path, new_files, he_map))
        self.finished.emit(results)


class RCalibratorDialog(QDialog):
    """R Calibrator — 채널별 반사율 교정 & R(t) 계산."""

    data_ready = pyqtSignal(object, object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("R Calibrator — 채널별 반사율 교정")
        self.resize(1100, 760)
        self._worker   = None
        self._t_start  = None
        self._timer    = QTimer(self)
        self._timer.timeout.connect(self._tick_elapsed)
        self._all_results = []
        self._ch_rows     = []   # list of QFrame per-channel row widgets

        self._init_ui()

        if parent is not None:
            if hasattr(parent, 'spin_d_len'):
                self._spin_cavity_len.setValue(parent.spin_d_len.value())
            if hasattr(parent, 'spin_rl_factor'):
                self._spin_rl.setValue(parent.spin_rl_factor.value())

        self._load_from_left_panel()

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
        main.setSpacing(5)

        # ── 채널 목록 ────────────────────────────────────────────────────────
        grp_ch = QGroupBox("채널 목록")
        grp_ch_lay = QVBoxLayout(grp_ch)
        grp_ch_lay.setSpacing(3)
        grp_ch_lay.setContentsMargins(6, 6, 6, 4)

        hdr = QHBoxLayout()
        btn_load_panel = QPushButton("🔄  왼쪽 패널에서 채널 로드")
        btn_load_panel.setStyleSheet(
            "background-color:#1565C0;color:white;font-weight:bold;")
        btn_load_panel.setToolTip(
            "왼쪽 패널의 채널 설정(파장보정·R창·TZ)을 읽어 채널 행을 채웁니다.\n"
            "채널을 변경하거나 추가했다면 클릭해 동기화하세요.")
        btn_load_panel.clicked.connect(self._load_from_left_panel)
        hdr.addWidget(btn_load_panel)
        btn_add_ch = QPushButton("＋  채널 추가")
        btn_add_ch.setFixedWidth(100)
        btn_add_ch.clicked.connect(
            lambda: self._add_ch_row(
                self._make_ch_row_widget(len(self._ch_rows) + 1)))
        hdr.addWidget(btn_add_ch)
        hdr.addStretch(1)
        grp_ch_lay.addLayout(hdr)

        self._ch_scroll = QScrollArea()
        self._ch_scroll.setWidgetResizable(True)
        self._ch_scroll.setMinimumHeight(70)
        self._ch_scroll.setMaximumHeight(230)
        self._ch_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._ch_container = QWidget()
        self._ch_vlay = QVBoxLayout(self._ch_container)
        self._ch_vlay.setContentsMargins(0, 0, 0, 0)
        self._ch_vlay.setSpacing(2)
        self._ch_vlay.addStretch(1)
        self._ch_scroll.setWidget(self._ch_container)
        grp_ch_lay.addWidget(self._ch_scroll)
        main.addWidget(grp_ch)

        # ── 공통 설정 ─────────────────────────────────────────────────────────
        grp_common = QGroupBox("공통 설정")
        gl = QGridLayout(grp_common)
        gl.setSpacing(4)
        gl.setColumnStretch(1, 1)

        gl.addWidget(QLabel("결과 저장 폴더:"), 0, 0, Qt.AlignmentFlag.AlignRight)
        self._le_out_dir = QLineEdit(".")
        btn_out = QPushButton("📂"); btn_out.setFixedWidth(28)
        btn_out.clicked.connect(lambda: self._pick_dir(self._le_out_dir))
        _od = QHBoxLayout(); _od.addWidget(self._le_out_dir, stretch=1); _od.addWidget(btn_out)
        _od_w = QWidget(); _od_w.setLayout(_od)
        gl.addWidget(_od_w, 0, 1)

        gl.addWidget(QLabel("날짜 범위(선택):"), 1, 0, Qt.AlignmentFlag.AlignRight)
        self._le_date_start = QLineEdit()
        self._le_date_start.setPlaceholderText("YYYYMMDD 시작 (예: 20260531)")
        self._le_date_end = QLineEdit()
        self._le_date_end.setPlaceholderText("YYYYMMDD 끝 (예: 20260601)")
        _dr = QHBoxLayout()
        _dr.addWidget(self._le_date_start); _dr.addWidget(QLabel("~")); _dr.addWidget(self._le_date_end)
        _drw = QWidget(); _drw.setLayout(_dr)
        gl.addWidget(_drw, 1, 1)

        gl.addWidget(QLabel("Cavity 설정:"), 2, 0, Qt.AlignmentFlag.AlignRight)
        from PyQt6.QtWidgets import QDoubleSpinBox as _DSB
        _cav = QHBoxLayout()
        _cav.addWidget(QLabel("길이 (cm):"))
        self._spin_cavity_len = _DSB()
        self._spin_cavity_len.setRange(1.0, 10000.0); self._spin_cavity_len.setDecimals(2)
        self._spin_cavity_len.setValue(51.8); self._spin_cavity_len.setFixedWidth(90)
        _cav.addWidget(self._spin_cavity_len); _cav.addSpacing(16)
        _cav.addWidget(QLabel("RL Factor:"))
        self._spin_rl = _DSB()
        self._spin_rl.setRange(0.001, 1.0); self._spin_rl.setDecimals(4)
        self._spin_rl.setSingleStep(0.001); self._spin_rl.setValue(1.0); self._spin_rl.setFixedWidth(80)
        _cav.addWidget(self._spin_rl); _cav.addStretch()
        _cav_w = QWidget(); _cav_w.setLayout(_cav)
        gl.addWidget(_cav_w, 2, 1)
        main.addWidget(grp_common)

        # ── 실행 버튼들 ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_run = QPushButton("▶  계산 시작")
        btn_run.setStyleSheet(
            "background-color:#4CAF50;color:white;font-weight:bold;height:36px;")
        btn_run.clicked.connect(self._run)
        self._btn_run = btn_run
        btn_row.addWidget(btn_run)

        btn_rt = QPushButton("💾  α용 R(t) 저장 (병렬)")
        btn_rt.setStyleSheet(
            "background-color:#1976D2;color:white;font-weight:bold;height:36px;")
        btn_rt.setToolTip(
            "현재 채널 설정으로 채널별 R(t)를 6코어 병렬 계산해\n"
            "결과 저장 폴더에 R_<채널>.npz 로 저장합니다.\n"
            "Alpha Generator에서 이 파일을 R(t)로 지정하면 알파에 적용됩니다.\n"
            "(R 계산은 계산 시작과 동일한 scan_directory 코어 사용)")
        btn_rt.clicked.connect(self._export_rt_for_alpha)
        self._btn_rt_export = btn_rt
        btn_row.addWidget(btn_rt)

        btn_rt_append = QPushButton("📥  증분 추가")
        btn_rt_append.setStyleSheet(
            "background-color:#00796B;color:white;font-weight:bold;height:36px;")
        btn_rt_append.setToolTip(
            "기존 R_<채널>.npz 에 새 파일만 추가 계산합니다.\n"
            "이미 처리된 파일은 건너뛰고 신규 파일만 계산 → 머지 저장.\n"
            "계산 전 각 파일의 He 플래그 유무를 미리 확인하고 진행 여부를 묻습니다.")
        btn_rt_append.clicked.connect(self._append_rt_for_alpha)
        self._btn_rt_append = btn_rt_append
        btn_row.addWidget(btn_rt_append)
        main.addLayout(btn_row)

        # ── 진행 표시줄 ────────────────────────────────────────────────────────
        prog_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setRange(0, 0); self._progress.setFixedHeight(16)
        self._progress.setVisible(False)
        self._lbl_elapsed = QLabel("")
        self._lbl_elapsed.setStyleSheet("color:#555;font-size:11px;min-width:80px;")
        prog_row.addWidget(self._progress, stretch=1); prog_row.addWidget(self._lbl_elapsed)
        main.addLayout(prog_row)

        # ── 스플리터: 로그/테이블 · 시계열/스펙트럼 ──────────────────────────
        main_splitter = QSplitter(Qt.Orientation.Vertical)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._log = QTextEdit()
        self._log.setReadOnly(True); self._log.setFontFamily("Consolas"); self._log.setFontPointSize(9)
        top_splitter.addWidget(self._log)

        self.tableWidget = QTableWidget(0, 4)
        self.tableWidget.setHorizontalHeaderLabels(["시간", "파일명", "채널", "R_mean (%)"])
        self.tableWidget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tableWidget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tableWidget.itemSelectionChanged.connect(self._on_table_row_selected)
        top_splitter.addWidget(self.tableWidget)
        top_splitter.setSizes([400, 600])

        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        _date_axis = pg.DateAxisItem(orientation='bottom')
        self._pw = pg.PlotWidget(axisItems={'bottom': _date_axis}, title="R 시계열")
        self._pw.setBackground('w'); self._pw.showGrid(x=True, y=True, alpha=0.3)
        self._pw.setLabel('left', 'R mean (%)'); self._pw.setLabel('bottom', 'Time')
        bottom_splitter.addWidget(self._pw)

        self._spectrum_pw = pg.PlotWidget(title="파장별 R(λ) 곡선")
        self._spectrum_pw.setBackground('w'); self._spectrum_pw.showGrid(x=True, y=True, alpha=0.3)
        self._spectrum_pw.setLabel('left', 'Reflectance R')
        self._spectrum_pw.setLabel('bottom', 'Wavelength (nm)')
        self._spectrum_pw.addLegend()
        bottom_splitter.addWidget(self._spectrum_pw)
        bottom_splitter.setSizes([600, 400])

        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(bottom_splitter)
        main_splitter.setSizes([280, 500])
        main.addWidget(main_splitter, stretch=1)

    # ── 채널 행 관리 ──────────────────────────────────────────────────────────
    def _make_ch_row_widget(self, ch_num, label="", raw_dir="", raw_ch=1,
                             wv_ok=False, r_start=435.0, r_end=480.0, tz_str="UTC"):
        """채널 한 행 QFrame 위젯 생성."""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet(
            "QFrame{background:#FAFAFA;border:1px solid #CCC;border-radius:3px;}")
        row = QHBoxLayout(frame)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(5)

        lbl_num = QLabel(f"CH{ch_num}")
        lbl_num.setStyleSheet("font-weight:bold;color:#1565C0;")
        lbl_num.setFixedWidth(34)
        row.addWidget(lbl_num)

        le_label = QLineEdit(label)
        le_label.setPlaceholderText("라벨")
        le_label.setFixedWidth(80)
        row.addWidget(le_label)

        le_raw_dir = QLineEdit(raw_dir)
        le_raw_dir.setPlaceholderText("Raw 데이터 폴더")
        row.addWidget(le_raw_dir, stretch=1)

        btn_dir = QPushButton("📂")
        btn_dir.setFixedWidth(28)
        btn_dir.clicked.connect(
            lambda _ch=ch_num, _le=le_raw_dir: self._pick_raw_dir(_le, _ch))
        row.addWidget(btn_dir)

        cb_raw_ch = QComboBox()
        cb_raw_ch.addItems(["ch 1", "ch 2", "ch 3"])
        cb_raw_ch.setCurrentIndex(raw_ch - 1)
        cb_raw_ch.setFixedWidth(62)
        cb_raw_ch.setToolTip(
            "로우 파일 내 몇 번째 ROI를 읽을지 (dio_channel)\n"
            "ch1: spec 0–2048 (Cold / Hot PNs)\n"
            "ch2: spec 2048–4096 (Hot ANs)\n"
            "핫 2채널: 같은 raw_dir, ch1·ch2 각각 지정")
        row.addWidget(cb_raw_ch)

        lbl_wv = QLabel("✅ wavecal" if wv_ok else "❌ 파장보정 없음")
        lbl_wv.setStyleSheet(
            "color:#2E7D32;font-weight:bold;" if wv_ok else "color:#C62828;")
        lbl_wv.setFixedWidth(104)
        lbl_wv.setToolTip("왼쪽 패널에서 로드된 파장보정 상태")
        row.addWidget(lbl_wv)

        # R창: 편집 가능 스핀박스 (기본값 = 핏범위에서 자동 채움)
        row.addWidget(QLabel("R창:"))
        sp_r_start = QDoubleSpinBox()
        sp_r_start.setRange(300.0, 1000.0); sp_r_start.setDecimals(1)
        sp_r_start.setValue(r_start); sp_r_start.setFixedWidth(58)
        sp_r_start.setToolTip("R 계산 파장창 시작 (nm)")
        row.addWidget(sp_r_start)
        row.addWidget(QLabel("–"))
        sp_r_end = QDoubleSpinBox()
        sp_r_end.setRange(300.0, 1000.0); sp_r_end.setDecimals(1)
        sp_r_end.setValue(r_end); sp_r_end.setFixedWidth(58)
        sp_r_end.setToolTip("R 계산 파장창 끝 (nm)")
        row.addWidget(sp_r_end)

        lbl_tz = QLabel(tz_str)
        lbl_tz.setStyleSheet("color:#555;font-size:11px;")
        lbl_tz.setFixedWidth(36)
        lbl_tz.setToolTip("TZ — 왼쪽 패널 설정")
        row.addWidget(lbl_tz)

        btn_del = QPushButton("✕")
        btn_del.setFixedWidth(22)
        btn_del.setStyleSheet("color:#AAA;")
        btn_del.setToolTip("이 채널 행 삭제")
        btn_del.clicked.connect(lambda _f=frame: self._del_ch_row(_f))
        row.addWidget(btn_del)

        frame.le_label    = le_label
        frame.le_raw_dir  = le_raw_dir
        frame.cb_raw_ch   = cb_raw_ch
        frame.lbl_wv      = lbl_wv
        frame.sp_r_start  = sp_r_start
        frame.sp_r_end    = sp_r_end
        frame.lbl_tz      = lbl_tz
        frame._ch_num     = ch_num
        frame._panel_data = {}   # filled by _load_from_left_panel
        return frame

    def _pick_raw_dir(self, line_edit, ch_num):
        d = QFileDialog.getExistingDirectory(self, "Raw 폴더 선택", dlg_dir("r_raw_dir"))
        if d:
            dlg_dir("r_raw_dir", d)
            line_edit.setText(d)
            QSettings("CAESAR", "app").setValue(f"r_calib/ch{ch_num}/raw_dir", d)

    def _add_ch_row(self, frame):
        idx = self._ch_vlay.count() - 1  # insert before trailing stretch
        self._ch_vlay.insertWidget(idx, frame)
        self._ch_rows.append(frame)

    def _del_ch_row(self, frame):
        if frame in self._ch_rows:
            self._ch_rows.remove(frame)
        self._ch_vlay.removeWidget(frame)
        frame.setParent(None)
        frame.deleteLater()

    def _clear_ch_rows(self):
        for frame in list(self._ch_rows):
            self._ch_vlay.removeWidget(frame)
            frame.setParent(None)
            frame.deleteLater()
        self._ch_rows.clear()

    def _load_from_left_panel(self):
        """왼쪽 패널 채널 설정 → 채널 행 동기화."""
        parent = self.parent()
        if parent is None or not hasattr(parent, '_channel_configs'):
            self._log.append("[채널 로드] 왼쪽 패널 채널 없음 (채널을 추가하세요).")
            return
        try:
            if hasattr(parent, '_capture_config') and hasattr(parent, '_active_channel'):
                parent._channel_configs[parent._active_channel] = parent._capture_config()
        except Exception:
            pass
        chcfgs = {k: v for k, v in (parent._channel_configs or {}).items() if v}
        if not chcfgs:
            self._log.append("[채널 로드] 왼쪽 패널에 설정된 채널이 없습니다.")
            return

        self._clear_ch_rows()
        qs = QSettings("CAESAR", "app")

        for ch in sorted(chcfgs):
            cfg     = chcfgs[ch]
            wl_path = cfg.get('wl_path', '')
            wave_ok = bool(wl_path) and os.path.isfile(wl_path)
            label   = (cfg.get('data_label') or f'CH{ch}').strip() or f'CH{ch}'

            # R창 기본값: QSettings 저장값 우선, 없으면 핏범위
            fit_s = float(cfg.get('fit_start_nm') or 435.0)
            fit_e = float(cfg.get('fit_end_nm') or 480.0)
            r_start = float(qs.value(f"r_calib/ch{ch}/r_start", fit_s))
            r_end   = float(qs.value(f"r_calib/ch{ch}/r_end",   fit_e))

            tz_h   = 9 if str(cfg.get('input_tz', '')).startswith('KST') else 0
            tz_str = "KST" if tz_h == 9 else "UTC"

            raw_dir = qs.value(f"r_calib/ch{ch}/raw_dir", "")
            raw_ch  = int(qs.value(f"r_calib/ch{ch}/raw_ch", 1))

            frame = self._make_ch_row_widget(
                ch, label, raw_dir, raw_ch, wave_ok, r_start, r_end, tz_str)

            frame._panel_data['ts_tz_hours'] = tz_h
            frame._panel_data['wl_path']        = wl_path

            if wave_ok:
                try:
                    wv = np.loadtxt(wl_path)
                    frame._panel_data['wave_nm'] = (
                        wv.ravel() if wv.ndim == 1 else wv[:, 0])
                except Exception as e:
                    frame._panel_data['wave_nm'] = None
                    self._log.append(f"  [CH{ch}] 파장보정 로드 실패: {e}")
            else:
                frame._panel_data['wave_nm'] = None

            self._add_ch_row(frame)

        self._log.append(f"[채널 로드] {len(chcfgs)}개 채널 동기화 완료")

    def _collect_channel_cfgs(self, RTP):
        """채널 행 → (label, raw_dir, wave_nm, RTConfig, file_list, out_path) 목록."""
        import os as _os
        try:
            import sys as _s
            _td = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
            if _td not in _s.path:
                _s.path.insert(0, _td)
            from r_batch_calculator import (
                SPEC_START_DEFAULT, SPEC_END_DEFAULT, SPEC_START_ANS, SPEC_END_ANS,
                COL_PRESS_COLD, COL_TEMP_COLD, COL_PRESS_HOT_ANS, COL_TEMP_HOT)
        except ImportError:
            SPEC_START_DEFAULT = 2053; SPEC_END_DEFAULT = 4101
            SPEC_START_ANS = 4101;     SPEC_END_ANS = 6149
            COL_PRESS_COLD = 6160;     COL_TEMP_COLD = 6173
            COL_PRESS_HOT_ANS = 6164;  COL_TEMP_HOT = 6155

        out_dir = self._le_out_dir.text().strip() or "."
        ds = self._le_date_start.text().strip()
        de = self._le_date_end.text().strip()

        def _flist(d):
            if not d:
                return None
            if ds or de:
                lo = self._norm_date(ds, "0000-00-00")
                hi = self._norm_date(de, "9999-99-99")
                return self._files_in_range(d, lo, hi) or None
            return None

        tasks = []
        for frame in self._ch_rows:
            label   = frame.le_label.text().strip() or f"ch{frame._ch_num}"
            raw_dir = frame.le_raw_dir.text().strip()
            if not raw_dir:
                self._log.append(f"  [{label}] raw_dir 없음 → 건너뜀")
                continue
            wave_nm = frame._panel_data.get('wave_nm')
            if wave_nm is None:
                self._log.append(
                    f"  [{label}] 파장보정 없음 → 건너뜀 (왼쪽 패널 로드 후 재시도)")
                continue

            dio_ch  = frame.cb_raw_ch.currentIndex() + 1  # 1-based
            fit_win = (frame.sp_r_start.value(), frame.sp_r_end.value())
            tz_h    = frame._panel_data.get('ts_tz_hours', 0)

            if dio_ch >= 2:  # ch2, ch3 → ANs 영역
                spec_s, spec_e = SPEC_START_ANS,     SPEC_END_ANS
                col_p,  col_t  = COL_PRESS_HOT_ANS,  COL_TEMP_HOT
            else:            # ch1 default
                spec_s, spec_e = SPEC_START_DEFAULT,  SPEC_END_DEFAULT
                col_p,  col_t  = COL_PRESS_COLD,      COL_TEMP_COLD

            rtcfg = RTP.RTConfig(
                fit_window_nm=fit_win, col_press=col_p, col_temp=col_t,
                spec_start=spec_s, spec_end=spec_e,
                ts_tz_hours=tz_h, label=label, dio_channel=dio_ch)

            tasks.append((label, raw_dir, wave_nm, rtcfg,
                          _flist(raw_dir), _os.path.join(out_dir, f"R_{label}.npz")))
        return tasks

    # ── 계산 시작 ─────────────────────────────────────────────────────────────
    def _run(self):
        """채널별 scan_directory → 시계열 + 스펙트럼 플롯."""
        if not self._ch_rows:
            QMessageBox.warning(self, "채널 없음",
                "채널을 먼저 로드하세요.\n'🔄 왼쪽 패널에서 채널 로드' 버튼을 클릭하세요.")
            return

        RTP = self._rt_import()
        if RTP is None:
            return

        qs = QSettings("CAESAR", "app")
        for frame in self._ch_rows:
            ch = frame._ch_num
            qs.setValue(f"r_calib/ch{ch}/raw_dir", frame.le_raw_dir.text().strip())
            qs.setValue(f"r_calib/ch{ch}/raw_ch",  frame.cb_raw_ch.currentIndex() + 1)
            qs.setValue(f"r_calib/ch{ch}/r_start", frame.sp_r_start.value())
            qs.setValue(f"r_calib/ch{ch}/r_end",   frame.sp_r_end.value())

        tasks = self._collect_channel_cfgs(RTP)
        if not tasks:
            QMessageBox.warning(self, "설정 오류",
                "실행 가능한 채널이 없습니다:\n"
                "• 각 채널의 Raw Dir를 지정하세요\n"
                "• 파장보정은 왼쪽 패널에서 로드해야 합니다")
            return

        out_dir = self._le_out_dir.text().strip() or "."
        channel_cfgs = [
            {"label":     label, "raw_dir": raw_dir, "wave_nm": wave,
             "rtcfg":     cfg,   "file_list": flist,
             "color":     _CH_COLORS[i % len(_CH_COLORS)]}
            for i, (label, raw_dir, wave, cfg, flist, _) in enumerate(tasks)
        ]

        self._log.clear(); self._pw.clear(); self._spectrum_pw.clear()
        self.tableWidget.setRowCount(0); self._all_results.clear()
        self._btn_run.setEnabled(False)
        self._progress.setVisible(True)
        self._t_start = time.time(); self._timer.start(1000)
        self._lbl_elapsed.setText("경과: 00:00")

        self._worker = _ChannelRWorker(
            channel_cfgs, out_dir,
            self._spin_cavity_len.value(), self._spin_rl.value())
        self._worker.log.connect(self._log.append)
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    # ── R(t) 공통 태스크 빌더 ──────────────────────────────────────────────
    def _build_rt_tasks(self, RTP):
        """채널 행에서 태스크 목록 반환 (_collect_channel_cfgs로 위임)."""
        return self._collect_channel_cfgs(RTP)

    def _rt_import(self):
        """rt_precompute 임포트 + 경로 보장. 실패 시 None 반환."""
        import sys as _sys, os as _os
        _td = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
        if _td not in _sys.path:
            _sys.path.insert(0, _td)
        try:
            import rt_precompute as RTP
            return RTP
        except Exception as e:
            QMessageBox.critical(self, "오류", f"rt_precompute 임포트 실패:\n{e}")
            return None

    def _lock_rt_buttons(self, locked):
        self._btn_rt_export.setEnabled(not locked)
        self._btn_rt_append.setEnabled(not locked)

    # ── 전체 재계산 저장 ────────────────────────────────────────────────────
    def _export_rt_for_alpha(self):
        """현재 설정으로 채널별 R(t)를 병렬 계산해 R_<채널>.npz 저장(Alpha Generator용)."""
        RTP = self._rt_import()
        if RTP is None:
            return

        out_dir = self._le_out_dir.text().strip() or "."
        tasks = self._build_rt_tasks(RTP)
        if not tasks:
            QMessageBox.warning(self, "입력 오류",
                                "왼쪽 패널 채널(파장보정 포함) + raw 폴더(Cold 또는 Hot)를 지정하거나,\n"
                                "Cold/Hot 폴더 + 파장보정 파일을 지정하세요.")
            return

        self._log.append(f"[R(t) export] {len(tasks)}채널 병렬 계산 시작 → {out_dir}")
        self._lock_rt_buttons(True)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("R(t) 계산 준비…")
        self._rt_export_worker = _RTExportWorker(tasks)
        self._rt_export_worker.log.connect(self._log.append)

        def _on_prog(done, total, label):
            self._progress.setRange(0, max(total, 1))
            self._progress.setValue(done)
            self._progress.setFormat(f"R(t) [{label}] {done}/{total} 파일 파싱  %p%")
        self._rt_export_worker.progress.connect(_on_prog)

        def _done(summary):
            self._log.append(f"[R(t) export 완료] {summary}")
            self._progress.setVisible(False)
            self._progress.setFormat("")
            self._lock_rt_buttons(False)
            QMessageBox.information(
                self, "R(t) 저장 완료",
                f"{summary}\n\n위치: {out_dir}\n파일: R_<채널>.npz\n\n"
                "Alpha Generator에서 이 파일을 'R(t) 파일'로 지정하면\n"
                "알파 생성 시 채널창 기반 R이 적용됩니다.")

        self._rt_export_worker.finished.connect(_done)
        self._rt_export_worker.start()

    # ── 증분 추가 ───────────────────────────────────────────────────────────
    def _append_rt_for_alpha(self):
        """기존 npz에 새 파일만 추가 — He 플래그 검사를 백그라운드로 실행 후 확인 다이얼로그."""
        RTP = self._rt_import()
        if RTP is None:
            return

        out_dir = self._le_out_dir.text().strip() or "."
        tasks = self._build_rt_tasks(RTP)
        if not tasks:
            QMessageBox.warning(self, "입력 오류",
                                "왼쪽 패널 채널(파장보정 포함) + raw 폴더를 지정하세요.")
            return

        # Phase 1 — He 플래그 검사를 백그라운드 스레드에서 실행
        self._append_out_dir = out_dir
        self._lock_rt_buttons(True)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)   # indeterminate
        self._progress.setTextVisible(True)
        self._progress.setFormat("He 플래그 스캔 중…")

        self._he_check_worker = _HeCheckWorker(tasks)
        self._he_check_worker.progress.connect(
            lambda lbl: self._progress.setFormat(f"He 스캔: [{lbl}]…"))
        self._he_check_worker.finished.connect(self._on_he_check_done)
        self._he_check_worker.start()

    def _on_he_check_done(self, results):
        """_HeCheckWorker 완료 콜백 — 확인 다이얼로그 표시 후 append worker 시작."""
        import os as _os

        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        self._progress.setFormat("")
        out_dir = self._append_out_dir

        summary_lines = []
        warn_lines    = []
        valid_tasks   = []

        for label, raw_dir, wave, rtcfg, flist, out_path, new_files, he_map in results:
            if not new_files:
                summary_lines.append(f"[{label}]  새 파일 없음 (건너뜀)")
                continue

            skip_count = 0
            for f in new_files:
                if he_map.get(_os.path.basename(f), False):
                    break
                skip_count += 1

            summary_lines.append(
                f"[{label}]  새 파일 {len(new_files)}개"
                + (f"  ⚠️ 앞 {skip_count}개 He없음(스킵)" if skip_count > 0
                   else "  ✅ 첫 파일부터 He 있음"))

            for i, f in enumerate(new_files[:20]):
                bn = _os.path.basename(f)
                has_he = he_map.get(bn, False)
                tag = ("✅ He" if has_he
                       else "⚠️ 스킵(He없음)" if i < skip_count
                       else "  ○ He승계")
                summary_lines.append(f"    {bn}  {tag}")
            if len(new_files) > 20:
                summary_lines.append(f"    … ({len(new_files) - 20}개 더)")

            if skip_count == len(new_files):
                warn_lines.append(
                    f"[{label}] 새 파일 {len(new_files)}개 모두 He 없음 → 전부 스킵될 수 있습니다.")

            valid_tasks.append((label, raw_dir, wave, rtcfg, flist, out_path))

        if not valid_tasks:
            self._lock_rt_buttons(False)
            QMessageBox.information(self, "증분 추가",
                                    "추가할 새 파일이 없습니다.\n\n" + "\n".join(summary_lines))
            return

        header = f"증분 추가 대상 채널 {len(valid_tasks)}개:\n\n"
        if warn_lines:
            header += "⚠️  경고:\n" + "\n".join(warn_lines) + "\n\n"

        msg = QMessageBox(self)
        msg.setWindowTitle("증분 추가 — He 플래그 확인")
        msg.setText(header + "계속 진행하시겠습니까?")
        msg.setDetailedText("\n".join(summary_lines))
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)
        msg.setIcon(QMessageBox.Icon.Warning if warn_lines else QMessageBox.Icon.Question)

        if msg.exec() != QMessageBox.StandardButton.Yes:
            self._lock_rt_buttons(False)
            return

        # Phase 2 — 실제 append
        self._log.append(f"[R(t) 증분] {len(valid_tasks)}채널 추가 시작 → {out_dir}")
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("R(t) 증분 준비…")

        self._rt_append_worker = _RTAppendWorker(valid_tasks)
        self._rt_append_worker.log.connect(self._log.append)

        def _on_prog(done, total, label):
            self._progress.setRange(0, max(total, 1))
            self._progress.setValue(done)
            self._progress.setFormat(f"R(t) 증분 [{label}] {done}/{total}  %p%")
        self._rt_append_worker.progress.connect(_on_prog)

        def _done(summary):
            self._log.append(f"[R(t) 증분 완료] {summary}")
            self._progress.setVisible(False)
            self._progress.setFormat("")
            self._lock_rt_buttons(False)
            QMessageBox.information(
                self, "증분 추가 완료",
                f"{summary}\n\n위치: {out_dir}\n\n기존 npz에 새 knot이 머지되었습니다.")

        self._rt_append_worker.finished.connect(_done)
        self._rt_append_worker.start()

    def _on_data_ready(self, arg0, arg1, arg2, out_dir):
        """arg0 = new [{label,results,color},...] 또는 legacy cold_results list."""
        self._pw.clear()
        self._pw.addLegend(offset=(10, 10))
        self._all_results.clear()
        self.tableWidget.setRowCount(0)

        # Format detection
        if (isinstance(arg0, list) and arg0 and
                isinstance(arg0[0], dict) and 'results' in arg0[0]):
            channels = arg0   # new channel-driven format
        else:
            # Legacy format: map fixed 3 channels
            channels = []
            for res, color, name in [
                (arg0, '#2196F3', 'Cold'),
                (arg1, '#FF6F00', 'Hot PNs'),
                (arg2, '#D32F2F', 'Hot ANs'),
            ]:
                if res:
                    channels.append({"label": name, "results": res, "color": color})

        def _plot_fill(results, color_hex, name):
            if not results:
                return
            times = np.array([r["timestamp"].replace(tzinfo=None).timestamp()
                              for r in results], dtype=float)
            r_pct = np.array([r["r_mean"] * 100.0 for r in results], dtype=float)
            r_std = np.array([r["r_std"]  * 100.0 for r in results], dtype=float)
            pen  = pg.mkPen(color=color_hex, width=2)
            brsh = pg.mkBrush(color_hex)
            self._pw.plot(times, r_pct, pen=pen, symbol='o', symbolSize=7,
                         symbolBrush=brsh, name=name)
            err = pg.ErrorBarItem(
                x=times, y=r_pct, top=r_std, bottom=r_std, beam=0,
                pen=pg.mkPen(color_hex, width=1, style=Qt.PenStyle.DotLine))
            self._pw.addItem(err)
            for r in results:
                ri = self.tableWidget.rowCount()
                self.tableWidget.insertRow(ri)
                self.tableWidget.setItem(ri, 0, QTableWidgetItem(
                    r["timestamp"].strftime('%Y-%m-%d %H:%M')))
                self.tableWidget.setItem(ri, 1, QTableWidgetItem(r["filename"]))
                self.tableWidget.setItem(ri, 2, QTableWidgetItem(name))
                self.tableWidget.setItem(ri, 3, QTableWidgetItem(
                    f"{r['r_mean'] * 100:.4f}"))
                file_date  = "-".join(r["filename"].split("-")[:3])
                base_fname = os.path.splitext(r["filename"])[0]
                # 새 형식: R_{name}; 레거시 호환 매핑
                _legacy = {"cold": "R_Cold", "hot_pns": "R_Hot_PNs",
                           "hot_ans": "R_Hot_ANs"}
                ch_subdir = _legacy.get(name.lower().replace(" ", "_"), f"R_{name}")
                dat_path  = os.path.join(
                    out_dir, ch_subdir, file_date, f"{base_fname}_R.dat")
                if not os.path.exists(dat_path):
                    dat_path = os.path.join(out_dir, file_date, f"{base_fname}_R.dat")
                self._all_results.append({
                    "channel": name, "color": color_hex,
                    "dat_path": dat_path, "roi": r.get("fit_window_nm", (400, 500))})

        for ch in channels:
            _plot_fill(ch["results"], ch["color"], ch["label"])

        all_r = [r["r_mean"] * 100 for ch in channels for r in ch["results"]]
        if all_r:
            arr = np.array(all_r, dtype=float)
            med = float(np.median(arr)); sd = float(np.std(arr))
            margin = max(sd * 4.0, 0.0015)
            self._pw.setYRange(med - margin, min(med + margin, 100.0 + 5e-4), padding=0)

        # 부모 윈도우(app_window)의 슬롯으로 전달
        self.data_ready.emit(channels, [], [], out_dir)

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


# 이전 이름으로 import하는 코드와의 하위 호환
RTrendMonitorDialog = RCalibratorDialog