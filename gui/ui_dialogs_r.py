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
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, 
                             QProgressBar, QGroupBox, QLineEdit, QScrollArea, QDialog, 
                             QComboBox, QSplitter, QTabWidget, QDoubleSpinBox, QSpinBox, 
                             QCheckBox, QGridLayout, QInputDialog, QRadioButton, QButtonGroup,
                             QSplashScreen, QDialogButtonBox, QStackedWidget, QFormLayout)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
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
    log        = pyqtSignal(str)
    finished   = pyqtSignal(str)    # 결과 폴더 경로
    data_ready = pyqtSignal(object, object)  # (cold_results, hot_results) — inline plot용

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
            _rtm_result = None
            try:
                _rtm_result = rtm.main()
            finally:
                _sys.stdout = old_stdout

            for line in buf.getvalue().splitlines():
                self.log.emit(line)

            # main()이 (results_cold, results_hot, out_folder) 튜플을 반환하면
            # data_ready 시그널로 인라인 플롯에 전달한다
            _out_dir = rtm.OUTPUT_DIR
            if _rtm_result and len(_rtm_result) >= 3:
                self.data_ready.emit(_rtm_result[0], _rtm_result[1])
                _out_dir = _rtm_result[2] or _out_dir

            self.finished.emit(_out_dir)

        except Exception as e:
            import traceback
            self.log.emit(f"[오류] {e}\n{traceback.format_exc()}")
            self.finished.emit("")


class RTrendMonitorDialog(QDialog):
    """R Trend Monitor 설정 + 실행 + 로그 표시 + 인라인 시계열 그래프 다이얼로그."""

    # Forwarded from the worker so the parent main window can connect to it
    data_ready = pyqtSignal(object, object)   # (cold_results, hot_results)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("R Trend Monitor — 거울 반사율 시계열")
        self.resize(1150, 720)
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
        from PyQt6.QtWidgets import QTextEdit, QSplitter
        main = QVBoxLayout(self)

        # ── 상단: 입력 폼 ──────────────────────────────────────────
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

        # ── 하단: 로그(왼쪽) + 시계열 플롯(오른쪽) ────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFontFamily("Consolas")
        self._log.setFontPointSize(9)
        self._log.setMinimumWidth(340)
        splitter.addWidget(self._log)

        # pyqtgraph R 시계열 위젯 (DateAxisItem 으로 실제 시각 표시)
        _date_axis = pg.DateAxisItem(orientation='bottom')
        self._pw = pg.PlotWidget(axisItems={'bottom': _date_axis},
                                 title="R 시계열 (Cold / Hot)")
        self._pw.setBackground('w')
        self._pw.showGrid(x=True, y=True, alpha=0.3)
        self._pw.setLabel('left', 'R mean (%)')
        self._pw.setLabel('bottom', 'Time (KST)')
        self._pw.addLegend(offset=(10, 10))
        splitter.addWidget(self._pw)
        splitter.setSizes([380, 720])

        main.addWidget(splitter, stretch=1)

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
        self._pw.clear()
        self._btn_run.setEnabled(False)
        self._worker = _RTrendWorker(cfg)
        self._worker.log.connect(self._log.append)
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.data_ready.connect(self.data_ready)   # forward to dialog signal
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_data_ready(self, cold_results, hot_results):
        """워커가 계산 완료한 R 시계열을 인라인 플롯에 표시한다."""
        self._pw.clear()
        self._pw.addLegend(offset=(10, 10))

        def _plot_channel(results, color_hex, name):
            if not results:
                return
            import numpy as np
            times  = np.array([r["timestamp"].timestamp() for r in results], dtype=float)
            r_pct  = np.array([r["r_mean"] * 100.0         for r in results], dtype=float)
            r_std  = np.array([r["r_std"]  * 100.0         for r in results], dtype=float)

            pen  = pg.mkPen(color=color_hex, width=2)
            brsh = pg.mkBrush(color_hex)
            self._pw.plot(times, r_pct, pen=pen, symbol='o',
                          symbolSize=7, symbolBrush=brsh, name=name)

            # ±1σ 음영 (ErrorBarItem)
            err = pg.ErrorBarItem(x=times, y=r_pct,
                                  top=r_std, bottom=r_std,
                                  beam=0, pen=pg.mkPen(color_hex, width=1, style=Qt.PenStyle.DotLine))
            self._pw.addItem(err)

        _plot_channel(cold_results, '#2196F3', 'Cold R mean')
        _plot_channel(hot_results,  '#FF6F00', 'Hot R mean')

        # Y축 범위: 전체 데이터 기준 ±0.05 % 여백
        all_r = ([r["r_mean"] * 100 for r in cold_results] +
                 [r["r_mean"] * 100 for r in hot_results])
        if all_r:
            import numpy as np
            lo = min(all_r) - 0.05
            hi = max(all_r) + 0.05
            self._pw.setYRange(lo, hi, padding=0)

    def _on_done(self, out_dir: str):
        self._btn_run.setEnabled(True)
        if out_dir:
            self._log.append(f"\n✅ 완료 → 결과 폴더: {out_dir}")
            QMessageBox.information(self, "완료", f"R Trend Monitor 완료!\n결과 폴더:\n{out_dir}")
        else:
            self._log.append("\n❌ 오류 발생 — 위 로그를 확인하세요.")

    def closeEvent(self, event):
        """다이얼로그 닫힐 때 백그라운드 스레드가 살아있으면 안전하게 종료 대기."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.quit()   # event loop 종료 요청
            if not self._worker.wait(3000):   # 3초 대기 후 강제 terminate
                self._worker.terminate()
                self._worker.wait()
        super().closeEvent(event)
