"""gui/app_window_fitsetup.py
CAESARAnalyzer §7~§9 — 다이얼로그 런처(ref/R/wavecal) · Test Fit · 핏 범위와 레퍼런스 관리 (gui/app_window.py에서 분리).

**순수 이동이다.** 메서드 본문은 한 글자도 안 고쳤다 — 호출부가 전부 self.xxx()라
믹스인으로 옮기는 것만으로 동작이 같다. 로직 개선은 다음 PR로.
가드는 tools/test_app_window_smoke.py (표면 골든 + 믹스인 이름 충돌 검사).

한 파일로 묶은 이유: 세 섹션 모두 '핏을 돌리기 전 세팅'이다.
"""
import math
import os
import numpy as np
import pandas as pd

from PyQt6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
                             QWidget)
from core.data_io import DataIO
from .test_fit_dialog import TestFitDialog
from .ui_dialogs import (MaskDialog, RCalibratorDialog, RefPropertiesDialog, ReferenceGeneratorDialog,
                         WavelengthCalibrationDialog)


class FitSetupMixin:
    """§7~§9 — 다이얼로그 런처(ref/R/wavecal) · Test Fit · 핏 범위와 레퍼런스 관리. CAESARAnalyzer에 믹스인된다."""

    # ══════════════════════════════════════════════════════════════════════
    # §7  다이얼로그 런처: ref / R / wavecal
    # ══════════════════════════════════════════════════════════════════════
    def open_ref_properties(self):
        """Opens the RefPropertiesDialog to configure Shift/Squeeze bounds."""
        if not hasattr(self, 'engine') or len(self.engine.gas_list) == 0:
            QMessageBox.warning(self, "Warning", "Please load and lock references first!")
            return
            
        dialog = RefPropertiesDialog(self, self.engine.gas_list, getattr(self, 'ref_props', {}))
        if dialog.exec():
            self.ref_props = dialog.get_properties()
            print("⚙️ Reference properties successfully saved:", self.ref_props)
            self._refresh_shsq_summary()   # L7: 그리드 요약 갱신

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

    # open_r_generator / R_GeneratorDialog 제거됨(2026-06): R Calibrator가 R(λ)·R(t)
    # 계산을 흡수했고 이 다이얼로그는 UI 버튼이 없는 죽은 경로였음.

    def open_r_trend_monitor(self):
        """R Calibrator: 채널별 반사율 교정 및 R(t) 계산."""
        from .ui_dialogs_r import RCalibratorDialog
        dialog = RCalibratorDialog(self)
        if hasattr(dialog, 'data_ready'):
            dialog.data_ready.connect(self._update_daily_rt_chart)
            dialog.data_ready.connect(self._update_setup_rt_charts)
        dialog.exec()

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

            # 4. Smart UI Update for FWHM Label + auto-fill nm spinbox
            fwhm_text = "Wavelength Updated"
            if hasattr(dialog, 'fwhm_records') and dialog.fwhm_records:
                valid_fwhms = [v['fwhm_nm'] for v in dialog.fwhm_records.values()
                               if v.get('fwhm_nm') is not None]
                if valid_fwhms:
                    avg_fwhm  = float(np.mean(valid_fwhms))
                    avg_sigma = avg_fwhm / 2.3548
                    fwhm_text = (f"FWHM={avg_fwhm:.3f} nm  "
                                 f"σ={avg_sigma:.3f} nm  "
                                 f"({len(valid_fwhms)} peaks)")
                    # Auto-populate the nm spinbox (triggers px conversion)
                    if hasattr(self, 'spin_fwhm_nm'):
                        self.spin_fwhm_nm.blockSignals(True)
                        self.spin_fwhm_nm.setValue(avg_fwhm)
                        self.spin_fwhm_nm.blockSignals(False)
                        # Now compute px using the just-loaded wavelength axis
                        self._update_fwhm_px_from_nm(avg_fwhm)

            target_label = getattr(self, 'lbl_fwhm_display', getattr(self, 'fwhm_label', None))
            if target_label:
                target_label.setText(fwhm_text)
                target_label.setStyleSheet("color: #2E7D32; font-weight: bold;")

            self._refresh_setup_status()

        dialog.calibration_finished.connect(on_calib_done)
        dialog.exec()

    def apply_new_wavelength(self, wl_array):
        """Immediately applies newly calibrated wavelengths to the UI monitor."""
        try:
            self.monitor.set_wavelengths(wl_array)
            self.monitor.refresh_current_plot()
            
            msg = f"Wavelength Updated: {wl_array.min():.2f} ~ {wl_array.max():.2f} nm"
            self.status.setText(msg)
            self.status.setStyleSheet("color: blue; font-weight: bold;")
            
            QMessageBox.information(self, "Applied", "New wavelength calibration applied to the system instantly.")
        except Exception as e:
            QMessageBox.critical(self, "Application Failed", f"Error during auto-apply: {e}")

    # ---------------------------------------------------------
    # Utility and Data Loading Functions
    # ---------------------------------------------------------
    def guess_gas_name(self, filename):
        """
        Attempts to identify the gas species from common substrings in the filename.

        Checks for known species names (NO2, O3, H2O, etc.) in the uppercased filename.
        Falls back to the filename prefix before the first underscore if nothing matches.
        Example: 'NO2_Vandaele_1998.txt' → 'NO2', 'ref_data.dat' → 'ref'.
        """
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
            filepath, _ = QFileDialog.getOpenFileName(self, "Load Wavelengths (nm)", self._dlg_dir('wavecal'), "Text/CSV (*.txt *.csv *.dat)")
            self._dlg_dir('wavecal', filepath)
            if not filepath: return
            self.loaded_wl_path = filepath # 🌟 Remember path for saving scenarios
            
        try:
            # 파장축 파서 단일 출처 — DataIO.load_wavecal_array
            wl_data = DataIO.load_wavecal_array(filepath)

            if wl_data is not None:
                self.wavelengths = wl_data
                self.engine.set_wavelength_axis(wl_data)  # register immediately so pixel_to_wavelength works before lock_ref
                self.monitor.set_wavelengths(wl_data)
                # 파일명은 lbl_wavecal(생략표시)에만 — 여기(FWHM 라벨)는 짧게 상태만
                self.lbl_fwhm_display.setText("WL ")
                if hasattr(self, 'lbl_wavecal'):
                    from PyQt6.QtGui import QFontMetrics
                    from PyQt6.QtCore import Qt as _Qt
                    _fm = QFontMetrics(self.lbl_wavecal.font())
                    _el = _fm.elidedText(f"{os.path.basename(filepath)}",
                                         _Qt.TextElideMode.ElideMiddle, int(180 * self._s))
                    self.lbl_wavecal.setText(_el)
                    self.lbl_wavecal.setStyleSheet("color: #1565C0; font-weight: bold; padding: 2px;")
                    self.lbl_wavecal.setToolTip(f"Wavecal for this channel:\n{filepath}")
                # X3: Calib 헤더에 ILS FWHM이 있으면 채운다. 예전엔 웨이브캘
                # **다이얼로그를 그 세션에 직접 돌린 경우에만** 채워져, 파일을
                # 불러오기만 한 런은 run_meta에 `ils_fwhm_nm: 0.0`이 박혔다.
                # 0.0은 "모른다"가 아니라 "폭이 0"으로 읽힌다.
                # 사용자가 이미 값을 넣었으면 덮지 않는다.
                if hasattr(self, 'spin_fwhm_nm') and self.spin_fwhm_nm.value() <= 0:
                    _fw = DataIO.wavecal_fwhm_nm(filepath)
                    if _fw:
                        self.spin_fwhm_nm.blockSignals(True)
                        self.spin_fwhm_nm.setValue(_fw)
                        self.spin_fwhm_nm.blockSignals(False)
                # Recompute px from nm spinbox with the new dispersion
                if hasattr(self, 'spin_fwhm_nm') and self.spin_fwhm_nm.value() > 0:
                    self._update_fwhm_px_from_nm(self.spin_fwhm_nm.value())
                self._refresh_setup_status()
                # Show popup only if loaded manually
                if not auto_path:
                    QMessageBox.information(self, "Loaded", f"X-Axis Calibration Loaded.\nRange: {wl_data.min():.2f} ~ {wl_data.max():.2f} nm")
            else:
                QMessageBox.warning(self, "Error", "No valid numeric data found in the file.")
                
        except Exception as e: 
            QMessageBox.critical(self, "Error", f"Failed to load wavelength file:\n{str(e)}")

    # ══════════════════════════════════════════════════════════════════════
    # §8  Test Fit (탭1 자동 최적화+Apply / 탭2 1-scan 미리보기 — gui/test_fit_dialog.py)
    # ══════════════════════════════════════════════════════════════════════
    def _open_test_fit_dialog(self):
        """🧪 Test Fit 버튼 핸들러 — 탭1(자동 파라미터 최적화)+탭2(1스캔 미리보기) 다이얼로그.
        옛 _test_fit의 사전 가드만 여기 유지하고, 실제 계산은 각 탭이 필요할 때 수행한다."""
        from PyQt6.QtWidgets import QMessageBox
        if not self.engine.is_engine_ready():
            QMessageBox.warning(self, "Test Fit", "Lock references first.")
            return
        files = self._channel_files.get(self._active_channel) or self.file_list
        if not files:
            QMessageBox.warning(self, "Test Fit", "Load data first.")
            return
        TestFitDialog(self).show()

    def _current_fit_px_window(self):
        """현재 활성 채널의 핏 윈도우 설정을 단위 무관 원시값으로 반환.

        반환: (unit, lo, hi). unit='px'면 lo/hi=검출기 픽셀 번호(int, 정수 텍스트박스 값
        그대로), unit='nm'이면 lo/hi=파장(nm, float). 실제 배열 인덱스로의 변환은 호출부가
        각자의 wave 축(파일마다 px_start가 다를 수 있음) 기준으로 한다 — 여기서 미리
        인덱스화하면 그 축을 모르는 채로 계산하게 돼 틀릴 수 있다."""
        unit = self.cb_fit_unit.currentText() if hasattr(self, 'cb_fit_unit') else 'nm'
        if unit == 'px':
            return unit, int(self.txt_min.text()), int(self.txt_max.text())
        return unit, self.spin_fit_start_nm.value(), self.spin_fit_end_nm.value()

    def _compute_1scan_preview(self):
        """S-B/S-C: 첫 알파 스캔 1개만 핏 → (fp, wl, a, full_model, resid, gas_models, ppb,
        opt_shifts, opt_squeezes, rms, T_C, P_mbar, collin) 튜플 반환(TestFitDialog 탭2용).
        실제 핏 경로(DoasFitter + get_model_components)를 그대로 써서 RUN과 동일하게 검증.
        실패 시 None(호출부가 사유 표시)."""
        from PyQt6.QtWidgets import QMessageBox
        files = self._channel_files.get(self._active_channel) or self.file_list
        if not files:
            return None
        fp = self._entry_filepath(files[0])
        # ── 알파 첫 데이터행 + 파장헤더 읽기 ──
        wave_nm_file = None
        alpha_start = None
        px_start = 0
        T_C, P_mbar = 25.0, 1013.25
        row = None
        with open(fp, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if line.startswith('# wavelength_nm'):
                    wave_nm_file = np.array([float(x) for x in line.split(':')[1].split()])
                if line.startswith('#'):
                    continue
                cols = line.rstrip('\n').split('\t')
                if cols and cols[0] == 'row_idx':
                    idx = {c: i for i, c in enumerate(cols)}
                    alpha_start = next(i for i, c in enumerate(cols) if c.startswith('px'))
                    try:   # 알파의 첫 픽셀 번호(예: 'px700' → 700) — px 핏단위 슬라이스 보정용
                        px_start = int(cols[alpha_start][2:])
                    except ValueError:
                        px_start = 0
                    _iT, _iP = idx.get('T_C'), idx.get('P_mbar')
                    continue
                if alpha_start is not None:
                    row = cols
                    break
        if wave_nm_file is None or row is None:
            QMessageBox.warning(self, "Test Fit",
                                "Not an alpha file (no wavelength header).\n"
                                "Test Fit currently supports alpha (*_alpha_trace.dat) input.")
            return None
        if _iT is not None and _iT < len(row):
            T_C = float(row[_iT])
        if _iP is not None and _iP < len(row):
            P_mbar = float(row[_iP])
        n_pix = len(wave_nm_file)
        alpha = np.array([float(v) for v in row[alpha_start:alpha_start + n_pix]], dtype=float)

        # ── 핏 윈도우 슬라이스(px/nm — 활성 채널 설정) ──
        unit, lo, hi = self._current_fit_px_window()
        if unit == 'px':
            pmin, pmax = int(lo), int(hi)
            # px 값은 '검출기 픽셀 번호' — 알파가 px_start부터 저장돼 있으므로
            # 배열 인덱스로는 px_start를 빼서 슬라이스(워커 _alpha_fit_slice와 동일 의미).
            sl = slice(max(0, pmin - px_start), max(1, min(n_pix, pmax - px_start + 1)))
        else:
            i0 = int(np.abs(wave_nm_file - lo).argmin())
            i1 = int(np.abs(wave_nm_file - hi).argmin())
            sl = slice(min(i0, i1), max(i0, i1) + 1)
        wl = wave_nm_file[sl]
        a = alpha[sl]

        # ── DoasFitter (RUN과 동일) ──
        from core.doas_fit import DoasFitter
        from scipy.interpolate import interp1d as _i1d
        eng = self.engine
        fitter = DoasFitter(eng)
        wax = np.asarray(eng._wave_axis, dtype=float).flatten()
        vp_pixel = np.asarray(_i1d(wax, np.arange(len(wax)), bounds_error=False,
                                   fill_value='extrapolate')(wl), dtype=float)
        vp_center = vp_pixel[len(vp_pixel) // 2]
        rp = getattr(self, 'ref_props', {})
        active, fixed, linked, t0, lb, ub = fitter.setup_fit_parameters(
            rp, 0.0, [0.0, 1.0], self.spin_step_limit.value())
        # (구식 etalon 위상 append 제거 — doas_fit가 etalon을 sin·cos 선형열로
        #  처리한 뒤로는 위상이 비선형 파라미터가 아니다. 워커와 동일하게 theta는
        #  shift/squeeze만. 전부 Fix면 theta=[]여도 doas_fit가 선형해 1회로 처리.)
        out = fitter.execute_varpro_fit(
            vp_pixel, a, np.ones(len(a)), active, fixed, linked, t0, lb, ub,
            self.spin_poly_deg.value(), 0.0, vp_center, 1.0, rp, T_C,
            self.spin_lambda.value(), self.chk_robust.isChecked(),
            allow_negative_gas=self.chk_allow_neg.isChecked())
        opt_shifts, opt_squeezes, gas_coeffs, poly_c, etal_amp, best_ep, perr = out
        full_model, *_ = eng.get_model_components(
            vp_pixel, opt_shifts, opt_squeezes, gas_coeffs, poly_c,
            etalon_amp=etal_amp, etalon_freq=0.0, etalon_phase=best_ep)
        resid = a - full_model
        # 가스별 기여(진짜 레퍼런스 오버레이, S-C): 핏이 내부에서 쓰는 것과 동일식
        gas_models = []
        for gi, nm in enumerate(eng.gas_list):
            px_sh = (vp_pixel - vp_center) * opt_squeezes[gi] + vp_center + opt_shifts[gi]
            try:
                refv = eng.interpolators[nm](px_sh) / eng.scaling_factors.get(nm, 1.0)
                gas_models.append(gas_coeffs[gi] * refv)
            except Exception:
                gas_models.append(None)
        rms = float(np.sqrt(np.mean(resid ** 2)))
        from core.physics import air_number_density
        n_air = air_number_density(T_C, P_mbar)   # ppb 환산 단일 출처
        ppb = {}
        for gi, nm in enumerate(eng.gas_list):
            sc = eng.scaling_factors.get(nm, 1.0); mu = eng.multipliers.get(nm, 1.0)
            ppb[nm] = (gas_coeffs[gi] * mu / sc) / n_air * 1e9

        # etalon–기체 공선성 진단(보고 전용, 핏 불변) — RUN과 동일한 FFT 검출
        # 주파수(워커 기본 밴드 0.02~0.40 rad/px)에서 평가. 실패해도 팝업은 뜬다.
        try:
            e_f_diag = fitter.detect_etalon_frequency(
                vp_pixel, a, self.spin_poly_deg.value(), 0.02, 0.40)
            collin = fitter.etalon_collinearity(
                vp_pixel, e_f_diag, self.spin_poly_deg.value(), rp,
                temperature=T_C, fit_sign=1.0,
                opt_shifts=opt_shifts, opt_squeezes=opt_squeezes,
                absolute_center=vp_center)
        except Exception:
            collin = None

        return (fp, wl, a, full_model, resid, gas_models, ppb, opt_shifts, opt_squeezes,
                rms, T_C, P_mbar, collin)

    def _apply_test_fit_recommendations(self, result):
        """TestFitDialog 탭1의 [Apply] 콜백 — 추천된 ref_props/poly/step_limit을 라이브
        상태에 반영한다. worker가 이미 t_ref/t_coeff/active_bands_nm(사용자 몫)을 보존해
        조립했으므로 여기서는 그대로 덮어쓰기만 하면 된다. 사람이 버튼을 눌러야만 호출됨
        (자동 적용 금지, docs/fit_optimizer_handoff.md §15-E 불변식4)."""
        for gas, props in result["proposed_ref_props"].items():
            self.ref_props[gas] = dict(props)
        self.spin_poly_deg.setValue(result["proposed_poly_deg"])
        if result.get("proposed_step_limit") is not None:
            self.spin_step_limit.setValue(result["proposed_step_limit"])
        self._refresh_shsq_summary()

    # ══════════════════════════════════════════════════════════════════════
    # §9  핏 범위 + 레퍼런스 관리
    # ══════════════════════════════════════════════════════════════════════
    def _auto_apply_nm(self):
        """nm 스핀 수정 완료 시 px 자동 동기화(웨이브칼 없으면 조용히 패스 — 팝업 금지).
        init 중에는 monitor가 아직 없을 수 있음 — hasattr 가드 필수."""
        if not hasattr(self, 'monitor'):
            return
        if getattr(self.monitor, 'wavelengths', None) is None:
            return
        self.set_range_from_nm()

    def set_range_from_nm(self):
        """Converts user-input nm range into pixel indices based on loaded wavelength data."""
        if self.monitor.wavelengths is None:
            QMessageBox.warning(self, "Error", "Please load the X-Axis (nm) wavelength file first!")
            return
            
        min_nm = self.spin_fit_start_nm.value()
        max_nm = self.spin_fit_end_nm.value()
        if min_nm > max_nm:
            min_nm, max_nm = max_nm, min_nm

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
        files, _ = QFileDialog.getOpenFileNames(self, "Select References", self._dlg_dir('refs'), "All Files (*.*)")
        if files:
            self._dlg_dir('refs', files[0])
        if files: 
            for f in sorted(files): 
                self.add_ref_row(self.guess_gas_name(f), f)
            
    def get_auto_scale_exponent(self, filepath):
        """
        Calculates the integer power-of-10 multiplier needed to bring a reference
        cross-section into the ~1e-19 cm² range expected by the engine.

        Example: if the file peak is 1e-38 (very small), exponent = -19 - (-38) = 19,
        so the spinner shows 19 and the engine multiplies by 10^19.
        """
        try:
            _, intensity_raw = DataIO.load_reference(filepath)
            
            if intensity_raw is None or len(intensity_raw) == 0: 
                return 0
                
            max_val = np.max(np.abs(intensity_raw))
            if max_val == 0: 
                return 0
                
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
        spin_mult.setFixedWidth(int(50 * self._s))

        if path:
            spin_mult.setValue(self.get_auto_scale_exponent(path))
        else:
            spin_mult.setValue(0)

        txt_name = QLineEdit()
        txt_name.setFixedWidth(int(80 * self._s))
        lbl_path = QLabel("...")

        btn_select = QPushButton("S")
        btn_delete = QPushButton("X")
        btn_delete.setFixedWidth(int(30 * self._s))
        
        def select_file_wrapper():
            f, _ = QFileDialog.getOpenFileName(self, "Select Reference", self._dlg_dir('refs'), "All Files (*.*)")
            self._dlg_dir('refs', f)
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
        self._mark_refs_dirty()
        print(f"✅ Slot Added: {name if name else 'Empty'}")

    def _mark_refs_dirty(self):
        """L5: 레퍼런스 변경 후 Lock 안 된 상태 표시 — Lock 버튼 빨강 + RUN 시 경고."""
        self._refs_dirty = True
        if hasattr(self, '_btn_lock_ref'):
            self._btn_lock_ref.setStyleSheet(
                "font-weight: bold; padding: 5px; background-color: #FFCDD2; color: #B71C1C;")

    def del_ref(self, widget):
        """Removes a reference row from the UI."""
        widget.deleteLater()
        self.ref_widgets = [x for x in self.ref_widgets if x['w'] != widget]
        self._mark_refs_dirty()

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

    def lock_ref(self, silent=False):
        """
        Commits all configured references from the UI into the UniversalEngine.

        silent=True: 채널 탭 전환 등 자동 재락 경로 — 모달 팝업 없이 상태라벨만.
        (사용자가 직접 Lock 버튼을 눌렀을 때만 팝업.)

        'Locking' means:
          1. The engine is cleared of any previous references.
          2. Each reference file is loaded, resampled to the instrument wavelength
             axis, scaled by its 10^exponent multiplier, and stored.
          3. A zero-FWHM convolution pass is run to initialize the interpolators.

        After locking, the engine is ready to call get_basis_matrix() for fitting.
        """
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
                    
        # Register wavelength axis in the engine (required for pixel_to_wavelength)
        if current_wave is not None:
            self.engine.set_wavelength_axis(current_wave)

        # Apply zero convolution initially (refreshes internal interpolators)
        self.engine.apply_ils_convolution(0.0)
        
        if success_count > 0:
            self._refs_dirty = False     # L5: 잠금 완료 → dirty 해제
            if hasattr(self, '_btn_lock_ref'):
                self._btn_lock_ref.setStyleSheet("font-weight: bold; padding: 5px;")
            if silent:
                self.status.setText(f"{success_count} references locked (auto, channel switch)")
            else:
                QMessageBox.information(self, "Locked", f"{success_count} references have been successfully locked into the Engine.")

            # Dynamically update the Result Table headers
            if hasattr(self, 'table'):
                cols = ["File", "Time", "RMS", "Chi2", "SNR", "Status"] + self.engine.gas_list + ["Shift", "Squeeze"]
                self.table.setColumnCount(len(cols))
                self.table.setHorizontalHeaderLabels(cols)
                self._compact_table_columns(cols)
                
            # Update Monitor dropdown list
            if hasattr(self, 'monitor') and hasattr(self.monitor, 'cb_view'):
                self.monitor.cb_view.clear()
                self.monitor.cb_view.addItem("Measurement")
                for name in self.engine.gas_list:
                    self.monitor.cb_view.addItem(f"Ref: {name}")
            # ILS was applied to the old interpolators — mark dirty so user re-applies
            self._ils_applied = False
            if hasattr(self, 'btn_apply_ils'):
                self.btn_apply_ils.setStyleSheet(
                    "font-weight: bold;")
            self._refresh_setup_status()
            self._refresh_shsq_summary()
        else:
            if silent:
                self.status.setText("no references to lock (channel switch)")
            else:
                QMessageBox.warning(self, "Error", "No valid references found to lock, or an error occurred.")


    # ---------------------------------------------------------
    # Measurement Data Loading & UI State Logic
    # ---------------------------------------------------------
