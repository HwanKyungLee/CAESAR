import os
import time
import numpy as np

# DataIO gatekeeper call
from core.data_io import DataIO

# Core engine imports
from scipy.linalg import lstsq as scipy_lstsq
from scipy.optimize import least_squares, lsq_linear
from numpy.polynomial import chebyshev

from PyQt6.QtWidgets import *
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# RayleighPhysics / KalmanTracker → core/physics.py 에서 공유
from core.physics import RayleighPhysics, KalmanTracker


class AnalysisWorker(QThread):
    """
    Background thread that iterates over all measurement files and fits each one.

    Runs in a separate QThread so the UI never freezes during long batch analyses.
    Results are sent back to the main thread via Qt signals:

      progress(int)           → current file index for the progress bar
      result_ready(dict, int) → per-file result dict and its row index in the table
      plot_update(...)        → pixel arrays + fit parameters for the monitor graph
      trend_update(dict)      → shift/squeeze/RMS for the trend plots
      finished()              → emitted once all files are processed
    """
    progress = pyqtSignal(int)
    result_ready = pyqtSignal(dict, int)
    plot_update = pyqtSignal(np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict, str)
    trend_update = pyqtSignal(dict)
    finished = pyqtSignal()
    r_curve_update = pyqtSignal(object, object)
    scan_count_ready = pyqtSignal(int)   # emitted once after all files are expanded

    def __init__(self, engine, file_list, pixel_min, pixel_max, p0, bounds, update_interval, delay_ms=0, ref_properties=None, i0_array=None, r_array=None, cavity_len=100.0, temperature=25.0, pressure=1013.25, flag_za=None, flag_he=None, flag_amb=None, dark_array=None, dark_scale_factor=1.0, offset_array=None, offset_scale_factor=1.0, stray_light_fraction=0.0, use_temporal_i0=False, save_alpha=False, alpha_save_dir='', rl_factor=1.0, channel=1):
        super().__init__()
        self.engine = engine
        self.file_list = file_list
        self.pixel_min = pixel_min
        self.pixel_max = pixel_max
        self.update_interval = update_interval
        self.delay_ms = delay_ms
        self.ref_properties = ref_properties if ref_properties is not None else {}

        # Spectrum channel: 1=CH1/ROI1/PNs (180°C), 2=CH2/ROI2/ANs (300°C), 3=CH3
        self.channel = int(channel) if channel in (1, 2, 3) else 1

        # [ BBCEAS Physics Parameters ]
        self.i0_array = i0_array
        self.r_array = r_array
        self.cavity_len = cavity_len

        # [ Dark Current, Detector Offset, Stray Light & Temporal I0 ]
        self.dark_array            = dark_array            # Dark: thermal electrons, scales with integration time
        self.dark_scale_factor     = dark_scale_factor     # t_meas / t_dark  (1.0 if same integration time)
        self.offset_array          = offset_array          # Offset: ADC pedestal, independent of integration time
        self.offset_scale_factor   = offset_scale_factor   # n_meas / n_offset  (scan count ratio)
        self.stray_light_fraction  = stray_light_fraction  # ε: scattered light fraction; I_corr=(I-ε·mean(I))/(1-ε)
        self.use_temporal_i0       = use_temporal_i0       # If True, interpolate I0 from bracketing ZA scans

        # [ Environment Variables ]
        self.temperature = temperature
        self.pressure = pressure

        self.i_za_last = None        
        self.i_he_last = None        
        self.one_minus_r_over_d = None 
        
        # Flag lists: ZA=500~503 / He=510~513 / Amb=1  (CAESAR Araon 2025 convention)
        # 500=ZA injecting(실측), 501=setflow, 502=wait before, 503=wait after
        # 510=He injecting(실측), 511=setflow, 512=wait before, 513=wait after
        self.flag_za  = flag_za  if flag_za  is not None else [500, 501, 502, 503]
        self.flag_he  = flag_he  if flag_he  is not None else [510, 511, 512, 513]
        self.flag_amb = flag_amb if flag_amb is not None else [1]
        self.save_alpha = save_alpha
        self.alpha_save_dir = alpha_save_dir
        self.rl_factor = rl_factor

        # ZA scan T&P — updated each time a ZA scan is seen; used in Rayleigh correction
        self.t_za_last = temperature
        self.p_za_last = pressure
        # He scan T&P — updated each time a He (flag 510) scan is seen
        self.t_he_last = temperature
        self.p_he_last = pressure

        # Explicit initialization (directly accessed in run())
        self.params = list(p0) if p0 is not None else [0.0, 1.0]
        self.is_running = True
        self.tikhonov_lambda = 0.0
        self.use_robust_fitting = False
        self.needs_pre_calibration = False
        self.etalon_freq = None
        self.step_limit = 0.5
        self.kalman_q = 0.0005
        self.kalman_r = 0.050
        self.etalon_freq_min = 0.02
        self.etalon_freq_max = 0.40

    # ==========================================
    # 알파 입력 처리 — 채널별(파일별) 파장축 사용
    # ==========================================
    def _is_alpha_input(self, fp):
        c = getattr(self, '_alpha_input_cache', None)
        if c is None:
            c = self._alpha_input_cache = {}
        if fp not in c:
            try:
                c[fp] = DataIO._is_alpha_trace_format(fp)
            except Exception:
                c[fp] = False
        return c[fp]

    def _alpha_pixels(self, wave_nm):
        """알파 파장(nm) → engine 마스터축 픽셀. 레퍼런스(픽셀-인덱스)를 알파의 실제
        파장 위치에서 평가하게 해, 마스터 wavecal이 채널과 달라도 정확히 정렬."""
        wax = getattr(self.engine, '_wave_axis', None)
        if wax is None:
            return np.arange(len(wave_nm), dtype=float)
        f = getattr(self, '_alpha_px_of', None)
        if f is None:
            from scipy.interpolate import interp1d
            wax = np.asarray(wax, dtype=float).flatten()
            f = self._alpha_px_of = interp1d(wax, np.arange(len(wax)),
                                             bounds_error=False, fill_value='extrapolate')
        return np.asarray(f(np.asarray(wave_nm, dtype=float)), dtype=float)

    def _alpha_fit_slice(self, wave_nm):
        """알파 행을 핏범위로 슬라이스할 인덱스(slice) 또는 None(전체).
        fit_unit=='px': [pixel_min:pixel_max] 픽셀구간(박사님 시나리오 775-1550 등 재현).
        fit_unit=='nm': fit_lo_nm~fit_hi_nm 안의 파장만. 둘 다 None/full이면 전체 핏(기존 동작)."""
        unit = getattr(self, 'fit_unit', 'nm')
        n = len(wave_nm)
        if unit == 'px':
            a = max(0, int(self.pixel_min))
            b = min(n, int(self.pixel_max)) if self.pixel_max else n
            if b - a >= 2 and (a > 0 or b < n):
                return slice(a, b)
            return None
        lo = getattr(self, 'fit_lo_nm', None)
        hi = getattr(self, 'fit_hi_nm', None)
        if lo is None or hi is None:
            return None
        lo, hi = (lo, hi) if lo <= hi else (hi, lo)
        w = np.asarray(wave_nm, dtype=float)
        # 알파 전체 파장범위를 (거의) 덮으면 슬라이스 안 함(기존 동작 보존)
        if lo <= float(np.nanmin(w)) + 1e-6 and hi >= float(np.nanmax(w)) - 1e-6:
            return None
        idx = np.where((w >= lo) & (w <= hi))[0]
        if len(idx) >= 2:
            return slice(int(idx[0]), int(idx[-1]) + 1)
        return None

    # ==========================================
    # VarPro 핏 — core.doas_fit.DoasFitter 로 위임(단일 구현 공유)
    # AnalysisWorker는 스캔 루프/상태(Kalman, etalon 한번검출, R-cal 등)만 소유.
    # ==========================================
    def _doasfitter(self):
        f = getattr(self, '_dfit', None)
        if f is None or getattr(f, 'engine', None) is not self.engine:
            from core.doas_fit import DoasFitter
            f = DoasFitter(self.engine)
            self._dfit = f
        return f

    def _gas_active_in_window(self, gas_name, pixel_idx):
        return self._doasfitter().gas_active_in_window(self.ref_properties, gas_name, pixel_idx)

    def auto_pre_calibrate(self, pixel_idx, optical_depth, poly_order):
        init_shift = float(np.atleast_1d(self.params[0])[0])
        return self._doasfitter().pre_calibrate(pixel_idx, optical_depth, poly_order, init_shift)

    def _detect_etalon_frequency(self, pixel_idx, optical_depth, poly_order):
        return self._doasfitter().detect_etalon_frequency(
            pixel_idx, optical_depth, poly_order,
            self.etalon_freq_min, self.etalon_freq_max)

    def _setup_fit_parameters(self, initial_shift_center, current_params):
        return self._doasfitter().setup_fit_parameters(
            self.ref_properties, initial_shift_center, current_params,
            getattr(self, 'step_limit', 0.5))

    def _execute_varpro_fit(self, pixel_idx, optical_depth, W_initial, active_vars, fixed_vars,
                            linked_vars, theta0, theta_lb, theta_ub, poly_order, fixed_e_f,
                            absolute_center, fit_sign, override_lam=None, override_robust=None):
        return self._doasfitter().execute_varpro_fit(
            pixel_idx, optical_depth, W_initial, active_vars, fixed_vars, linked_vars,
            theta0, theta_lb, theta_ub, poly_order, fixed_e_f, absolute_center, fit_sign,
            self.ref_properties, self.temperature,
            getattr(self, 'tikhonov_lambda', 0.0),
            getattr(self, 'use_robust_fitting', False),
            override_lam, override_robust)
    
    # ==========================================
    # 🌟 Main Orchestrator
    # ==========================================

    def _prescan_za_scans(self):
        """
        Phase-0 pre-scan: reads every file quickly to collect ZA calibration scans.
        Returns a list of (file_index, i0_spectrum) sorted by index, used for
        temporal I0 interpolation during the main fitting loop.
        """
        za_list = []
        for idx, entry in enumerate(self.file_list):
            fp, row_idx = (entry[0], entry[1]) if isinstance(entry, tuple) else (entry, 0)
            try:
                _, raw, flag, _, _ = DataIO.load_measurement_with_hk(fp, self.pixel_min, self.pixel_max, row_index=row_idx, channel=self.channel)
                if flag in self.flag_za and len(raw) > 0:
                    i0 = raw.astype(float)
                    za_list.append((idx, i0))
            except Exception:
                pass
        print(f"[Temporal I0] Pre-scan complete: {len(za_list)} ZA scans found.")
        return za_list

    def _interpolate_i0(self, za_list, current_idx):
        """
        Returns an I0 array for the file at current_idx by linearly interpolating
        between the nearest preceding and following ZA calibration scans.

        Fallback order: bracketed interpolation → nearest single ZA scan → fixed i0_array.
        """
        if not za_list:
            return self.i0_array

        before = [(idx, i0) for idx, i0 in za_list if idx < current_idx]
        after  = [(idx, i0) for idx, i0 in za_list if idx >= current_idx]

        if before and after:
            idx_b, i0_b = before[-1]
            idx_a, i0_a = after[0]
            t = (current_idx - idx_b) / max(idx_a - idx_b, 1)
            return (1.0 - t) * i0_b + t * i0_a
        elif before:
            return before[-1][1]
        else:
            return after[0][1]

    def run(self):
        try: current_params = [ float(np.atleast_1d(p)[ 0 ]) for p in self.params ]
        except Exception: current_params = [ 0.0, 1.0 ] + [ 0.1 ] * len(self.engine.gas_list) + [ 0.0 ] * 10

        total_files = len(self.file_list)
        last_valid_shift = float(np.atleast_1d(current_params[ 0 ])[ 0 ])

        current_kalman_q = getattr(self, 'kalman_q', 0.0005)
        current_kalman_r = getattr(self, 'kalman_r', 0.050)
        kalman_filter = KalmanTracker(num_variables=len(self.engine.gas_list), q_noise=current_kalman_q, r_noise=current_kalman_r)

        # Phase 0: expand all file_list entries into individual (filepath, row_idx) scan tuples.
        # This runs in the worker thread so the UI never freezes during expansion.
        # For plain 1D files expand_to_scan_list returns [(path, 0)] — no overhead.
        expanded_scans = []
        for entry in self.file_list:
            if isinstance(entry, tuple):
                expanded_scans.append(entry)           # already a (path, row) tuple
            else:
                expanded_scans.extend(DataIO.expand_to_scan_list(entry))

        self.scan_count_ready.emit(len(expanded_scans))   # tell UI how many rows to allocate

        total_files = len(self.file_list)

        # Phase 0b: pre-scan ZA scans when temporal I0 mode is active
        za_scan_list = self._prescan_za_scans() if self.use_temporal_i0 else []

        # Track which source file we're on so the progress bar advances per file.
        _last_fp = None
        _file_counter = 0

        for i, entry in enumerate(expanded_scans):
            if not self.is_running: break

            file_path, row_idx = entry

            # Progress bar: advance by one when we move to a new source file
            if file_path != _last_fp:
                _last_fp = file_path
                _file_counter += 1
                self.progress.emit(_file_counter)

            initial_shift_center = last_valid_shift
            # Always display as "filename [NNNN]" so results are unambiguous
            result = {'File': f"{os.path.basename(file_path)} [{row_idx:04d}]", 'Channel': self.channel, 'Params': {}}
            # Try to read the measurement timestamp from column 0 of the Araon row.
            # Falls back to file mtime → KST if column 0 is not a recognisable timestamp.
            _ts = DataIO.parse_row_timestamp(file_path, row_index=row_idx)
            result['Time'] = _ts.strftime('%Y-%m-%d %H:%M:%S') if _ts else f"row {row_idx:04d}"

            try:
                # 1. Load Spectrum and Housekeeping (including Flag)
                if self._is_alpha_input(file_path):
                    # 알파 입력: 그 파일(채널)에 박힌 파장축으로 피팅(마스터 wavecal 아님).
                    # 레퍼런스는 알파의 실제 파장에 평가되도록 engine 마스터축 픽셀로 매핑
                    # → Hot CH2/CH3도 roi2/roi3 파장으로 정확히 정렬(채널별 wavecal 자동 반영).
                    wave_nm, intensity_raw, env_t, env_p = DataIO.load_alpha_trace_row_full(file_path, row_idx)
                    sl = self._alpha_fit_slice(wave_nm)
                    if sl is not None:
                        wave_nm = wave_nm[sl]; intensity_raw = intensity_raw[sl]
                    pixel_idx = self._alpha_pixels(wave_nm)
                    state_flag = 1   # 알파는 ambient
                else:
                    pixel_idx, intensity_raw, state_flag, env_t, env_p = DataIO.load_measurement_with_hk(file_path, self.pixel_min, self.pixel_max, row_index=row_idx, channel=self.channel)
                    # Guard: if _wave_axis is None, pixel_to_wavelength returns pixel indices
                    # (~1453) → Rayleigh(λ⁻⁴) corrupted. Load a wavelength cal first.
                    if self.engine._wave_axis is None:
                        print("⚠️  WARNING: No wavelength calibration loaded in engine. "
                              "pixel_to_wavelength() returns pixel indices as nm — "
                              "Rayleigh calculation will be incorrect. Load a wavelength cal file first.")
                    wave_nm = self.engine.pixel_to_wavelength(pixel_idx)

                # Update current environment for PPB calculation
                self.temperature = env_t
                self.pressure = env_p

                # [ State Switching & R-Calibration ]
                # Flag lists from UI: ZA=[500~503], He=[510~513], Amb=[1]
                # If flag_amb is set, only those values count as ambient.
                # Otherwise, anything not in ZA or He is treated as ambient.
                is_za  = state_flag in self.flag_za
                is_he  = state_flag in self.flag_he
                # flag 0 = no flag column in file (plain 1D / alpha files) → always ambient
                if state_flag == 0:
                    is_amb = True
                elif self.flag_amb:
                    is_amb = state_flag in self.flag_amb
                else:
                    is_amb = not is_za and not is_he

                if is_za:
                    self.i_za_last = intensity_raw.copy()
                    # Only injecting ZA (flag 500) updates I₀ and T/P reference.
                    # Other ZA flags (501=setflow, 502=wait before, 503=wait after) keep last good I₀.
                    # If 500 is not configured (legacy data), all ZA flags act as I₀.
                    if 500 not in self.flag_za or state_flag == 500:
                        self.i0_array = intensity_raw.copy()
                        self.t_za_last = env_t
                        self.p_za_last = env_p
                        result['Status'] = f"Zero-Air (Flag {state_flag} - I0 Updated)"
                    else:
                        result['Status'] = f"Zero-Air (Flag {state_flag} - i_za Updated, I0 Kept)"
                    if getattr(self, 'i_he_last', None) is not None:
                        self.update_mirror_reflectivity(wave_nm, env_t, env_p)
                        result['Status'] += " & R-Calibrated"
                    self.result_ready.emit(result, i)
                    continue

                elif is_he:
                    # Only injecting He (flag 510) updates i_he_last used for R-calibration.
                    # Other He flags (511=setflow, 512=wait before, 513=wait after) preserve last good reference.
                    # If 510 is not configured (legacy data), all He flags update i_he_last.
                    if 510 not in self.flag_he or state_flag == 510:
                        self.i_he_last = intensity_raw.copy()
                        self.t_he_last = env_t
                        self.p_he_last = env_p
                    result['Status'] = f"Helium (Flag {state_flag} - {'Updated' if (510 not in self.flag_he or state_flag == 510) else 'i_he Kept'})"
                    if getattr(self, 'i_za_last', None) is not None:
                        self.update_mirror_reflectivity(wave_nm, env_t, env_p)
                        result['Status'] += " & R-Calibrated"
                    self.result_ready.emit(result, i)
                    continue

                elif not is_amb:
                    # Unknown flag — skip silently
                    result['Status'] = f"Skip: Unknown flag {state_flag}"
                    self.result_ready.emit(result, i)
                    continue

                # [ AMBIENT Normal Measurement Mode ]
                else:

                    # 2. Pre-processing
                    # Detect the input type FIRST — before any R-curve check.
                    # linear_mode = True  → data is already optical depth / alpha (|mean| < 1)
                    #                       R-curve is NOT needed, fit directly.
                    # linear_mode = False → data is raw photon counts (|mean| >> 1)
                    #                       R-curve IS needed to convert to optical depth.
                    # Reject files where every pixel is zero — nothing to fit.
                    if np.max(np.abs(intensity_raw)) == 0:
                        print(f"⚠️  [Skip] {os.path.basename(file_path)} All-zero data — skipping.")
                        result['Status'] = "Skip: All-Zero"
                        self.result_ready.emit(result, i)
                        self.progress.emit(i + 1)
                        continue

                    avg_raw = np.mean(intensity_raw)
                    is_linear_mode = (abs(avg_raw) < 1.0)

                    # If the raw counts are very small (e.g., 1e-6), multiply up to ~1
                    # to avoid numerical underflow in the optimizer
                    scale_factor = (
                        10 ** (-np.floor(np.log10(abs(avg_raw))))
                        if (abs(avg_raw) < 1e-4 and avg_raw != 0)
                        else 1.0
                    )
                    intensity_processed = intensity_raw * scale_factor

                    # R-curve check: only required when converting raw counts → optical depth
                    if not is_linear_mode:
                        if getattr(self, 'one_minus_r_over_d', None) is None:
                            if self.r_array is not None:
                                self.one_minus_r_over_d = (1.0 - self.r_array) / self.cavity_len
                            else:
                                result['Status'] = "Skip: No R-curve"
                                self.result_ready.emit(result, i)
                                self.progress.emit(i+1)
                                continue
                    
                    if is_linear_mode:
                        optical_depth = intensity_processed
                        fit_sign = 1.0
                    else:
                        # [ BBCEAS Native Physics Engine ]
                        # Dark current subtraction: remove thermally-generated CCD counts
                        # that are present in every frame regardless of light level.
                        # Formula: α = [(1-R)/d] · [(I₀ - dark) - (I - dark)] / (I - dark)
                        #            = [(1-R)/d] · [(I₀ - I) / (I - dark)]
                        I_meas = intensity_processed.copy()
                        if self.dark_array is not None:
                            I_meas -= self.dark_scale_factor * self.dark_array * scale_factor
                        if self.offset_array is not None:
                            I_meas -= self.offset_scale_factor * self.offset_array * scale_factor
                        if self.stray_light_fraction > 1e-9:
                            eps = self.stray_light_fraction
                            I_meas = (I_meas - eps * np.mean(I_meas)) / (1.0 - eps)

                        I_meas[I_meas <= 0] = 1e-9

                        # Temporal I0: pick the interpolated I0 for this file index,
                        # otherwise fall back to the fixed i0_array.
                        if self.use_temporal_i0 and za_scan_list:
                            I_0 = self._interpolate_i0(za_scan_list, i)
                        else:
                            I_0 = self.i0_array

                        if I_0 is not None:
                            I_0 = I_0.astype(float) * scale_factor
                            if self.dark_array is not None:
                                I_0 -= self.dark_scale_factor * self.dark_array * scale_factor
                            if self.offset_array is not None:
                                I_0 -= self.offset_scale_factor * self.offset_array * scale_factor
                            if self.stray_light_fraction > 1e-9:
                                eps = self.stray_light_fraction
                                I_0 = (I_0 - eps * np.mean(I_0)) / (1.0 - eps)
                            I_0[I_0 <= 0] = 1e-9

                            # BBCEAS optical depth formula (CAESAR Araon 2025 / MATLAB-equivalent):
                            #   α = RL · [(1-R)/d + α_ZA_Ray] · (I_ZA/I - 1) − (α_sample_Ray − α_ZA_Ray)
                            # The α_ZA_Ray bracket term accounts for Rayleigh scattering present
                            # during the ZA reference scan — it is NOT zero in Zero-Air.
                            # The differential Rayleigh term removes the T/P-dependent background
                            # between the ZA and ambient scans.
                            # RL (Purge Length Ratio): CH1=0.9330, CH2=0.9950, CH3=0.9968
                            alpha_ref = RayleighPhysics.get_alpha_rayleigh(wave_nm, self.t_za_last, self.p_za_last, 'zero_air')
                            alpha_ray_sample = RayleighPhysics.get_alpha_rayleigh(wave_nm, self.temperature, self.pressure, 'zero_air')
                            optical_depth = ((self.one_minus_r_over_d / self.rl_factor + alpha_ref) * ((I_0 - I_meas) / I_meas)
                                            - (alpha_ray_sample - alpha_ref))
                            fit_sign = 1.0

                            # Save alpha spectrum as intermediate product (per박사님 request)
                            if self.save_alpha and self.alpha_save_dir:
                                try:
                                    stem = os.path.splitext(os.path.basename(file_path))[0]
                                    alpha_fname = os.path.join(self.alpha_save_dir, stem + '_alpha.dat')
                                    np.savetxt(alpha_fname, optical_depth, fmt='%.8e')
                                except Exception:
                                    pass
                        else:
                            # Fallback for traditional DOAS
                            optical_depth = np.log(I_meas) 
                            fit_sign = -1.0

                poly_start_idx = 2 + len(self.engine.gas_list)
                poly_order = len(current_params) - poly_start_idx - 1
                absolute_center = (self.pixel_min + self.pixel_max) / 2.0 if self.pixel_max else len(intensity_raw)/2.0

                # 2. Etalon detection
                if getattr(self, 'etalon_freq', None) is None:
                    self.etalon_freq = self._detect_etalon_frequency(pixel_idx, optical_depth, poly_order)

                # 3. Fitting loop
                max_retries = 2
                for attempt in range(max_retries):
                    current_lam = self.tikhonov_lambda
                    current_robust = self.use_robust_fitting

                    if self.needs_pre_calibration:
                        best_sh, best_sq = self.auto_pre_calibrate(pixel_idx, optical_depth, poly_order)
                        current_params[ 0 ] = best_sh; current_params[ 1 ] = best_sq
                        self.needs_pre_calibration = False

                    if len(current_params) > poly_start_idx:
                        current_params[poly_start_idx] = np.mean(optical_depth) 
                        current_params[poly_start_idx+1 : poly_start_idx+1+poly_order] = [0.0] * poly_order
                    
                    # 4. Parameter setup
                    active_vars, fixed_vars, linked_vars, theta0, theta_lb, theta_ub = self._setup_fit_parameters(initial_shift_center, current_params)
                    fixed_e_f = self.etalon_freq  
                    theta0.append(0.0); theta_lb.append(-np.pi); theta_ub.append(np.pi)
                    
                    try:
                        weights = np.ones_like(intensity_processed) if is_linear_mode else np.sqrt(np.abs(I_meas))
                        weights = weights / np.mean(weights)
                        W = np.diag(weights)

                        # 5. Core engine call
                        opt_shifts, opt_squeezes, gas_coeffs_scaled, poly_coeffs_scaled, etalon_amp_scaled, best_ep, gas_errs = self._execute_varpro_fit(
                            pixel_idx, optical_depth, W, active_vars, fixed_vars, linked_vars, theta0, theta_lb, theta_ub,
                            poly_order, fixed_e_f, absolute_center, fit_sign,
                            override_lam=current_lam, override_robust=current_robust
                        )

                        # 6. Combine and store results (keep 5 unpacked values)
                        _, abs_val_scaled, poly_val_scaled, _, _ = self.engine.get_model_components(
                            pixel_idx, opt_shifts, opt_squeezes, gas_coeffs_scaled, poly_coeffs_scaled
                        )
                        
                        abs_val_orig, poly_val_orig = abs_val_scaled / scale_factor, poly_val_scaled / scale_factor
                        etalon_part_orig = (etalon_amp_scaled * np.sin(fixed_e_f * pixel_idx + best_ep)) / scale_factor

                        y_fit_model_orig = poly_val_orig + (fit_sign * abs_val_orig) + etalon_part_orig
                        # residual must be in the same units as the fitted signal (optical_depth)
                        if is_linear_mode:
                            residual = intensity_raw - y_fit_model_orig
                        else:
                            residual = optical_depth - y_fit_model_orig
                        rms = np.sqrt(np.mean(residual**2))
                        
                        result['RMS'] = rms
                        result['Shift'] = opt_shifts[ 0 ] if len(opt_shifts) > 0 else 0
                        result['Squeeze'] = opt_squeezes[ 0 ] if len(opt_squeezes) > 0 else 1
                        
                        final_params_dict = {
                            'shifts': opt_shifts, 'squeezes': opt_squeezes,
                            'gas_coeffs': (gas_coeffs_scaled / scale_factor).tolist(),
                            'poly_coeffs': (poly_coeffs_scaled / scale_factor).tolist(),
                            'etalon_amp': etalon_amp_scaled / scale_factor,
                            'etalon_phase': float(best_ep), 'etalon_freq': float(fixed_e_f),
                            'channel': self.channel
                        }
                        result['Params'] = final_params_dict 
                        
                        raw_concentrations, real_errors = [], []
                        for gi, nm in enumerate(self.engine.gas_list):
                            scale_div = self.engine.scaling_factors[nm]
                            # The normalised reference column = ref_raw / max(ref_raw),
                            # so the multiplier cancels in the column but must be
                            # reapplied here to recover physical units [cm-3]:
                            #   N = (coeff / scale_factor) * mult / scale_div
                            mult_i = self.engine.multipliers.get(nm, 1.0)
                            if is_linear_mode:
                                real_conc = (gas_coeffs_scaled[gi] / scale_factor) / scale_div * mult_i
                                real_err  = (gas_errs[gi]           / scale_factor) / scale_div * mult_i
                            else:
                                real_conc = gas_coeffs_scaled[gi] / scale_div * mult_i
                                real_err  = gas_errs[gi]           / scale_div * mult_i
                            raw_concentrations.append(real_conc); real_errors.append(real_err)

                        smooth_concentrations = kalman_filter.process(raw_concentrations)
                        
                        # ── Real-time PPB conversion ─────────────────────────────────────
                        # Cross-section fitting gives concentrations in [cm²/molecule × molecules/cm³]
                        # i.e., the raw coefficient has units cm⁻³.
                        # Dividing by air number density N_air converts to a dimensionless mixing ratio.
                        # Multiplying by 1e9 converts to parts-per-billion (ppb).
                        # N_air from the ideal gas law at measured T and P:
                        n_air = 2.68678e19 * (self.pressure / 1013.25) * (273.15 / (self.temperature + 273.15))
                        
                        # n_air uncertainty propagation (assuming T: ±1°C, P: ±1 mbar, Washenfelder 2008)
                        dn_air_dT = -n_air / (self.temperature + 273.15)
                        dn_air_dP = n_air / self.pressure
                        rel_err_n = np.sqrt((dn_air_dT * 1.0)**2 + (dn_air_dP * 1.0)**2) / n_air

                        for gi, nm in enumerate(self.engine.gas_list):
                            ppb_raw    = (raw_concentrations[gi]    / n_air) * 1e9
                            ppb_smooth = (smooth_concentrations[gi] / n_air) * 1e9
                            ppb_err    = (real_errors[gi]           / n_air) * 1e9
                            ppb_total_err = abs(ppb_raw) * np.sqrt((ppb_err / max(abs(ppb_raw), 1e-30))**2 + rel_err_n**2)

                            # Primary column = raw fit result (not Kalman-filtered).
                            # _Smooth column = Kalman-filtered value for trend monitoring only.
                            result[nm]                  = ppb_raw
                            result[f"{nm}_Smooth"]      = ppb_smooth
                            result[f"{nm}_Error"]       = ppb_err
                            result[f"{nm}_TotalError"]  = float(np.mean(ppb_total_err)) if hasattr(ppb_total_err, '__len__') else float(ppb_total_err)
                            result[f"{nm}_MDL"]         = 3.0 * ppb_err
                            result[f"{nm}_Shift"]       = opt_shifts[gi]
                            result[f"{nm}_Squeeze"]     = opt_squeezes[gi]



                        # ── Spectral quality metrics ─────────────────────────────────────
                        # DOF = n_pixels − n_free_params (Shift, Squeeze, gases, poly, etalon)
                        # Chi2 (reduced): uses Neumann estimator for independent pixel noise:
                        #   sigma_pix ≈ std(diff(spectrum)) / sqrt(2)
                        #   This captures instrument noise without being biased by spectral features.
                        #   chi2 > 1 means systematic structure remains in residual.
                        # SNR: signal / noise, both in the same (scaled) units.
                        n_pts = len(pixel_idx)
                        n_gases = len(self.engine.gas_list)
                        n_params = len(theta0) + n_gases + (poly_order + 1) + 1
                        dof = max(n_pts - n_params, 1)
                        # Neumann estimator σ on the fitted signal (optical_depth units for both modes)
                        signal_for_stats = intensity_raw if is_linear_mode else optical_depth
                        sigma_pix = np.std(np.diff(signal_for_stats)) / np.sqrt(2)
                        if sigma_pix < 1e-30:
                            sigma_pix = rms if rms > 1e-30 else 1.0
                        chi2 = float(np.sum(residual**2 / sigma_pix**2) / dof)
                        snr = float(np.mean(np.abs(optical_depth)) / (rms + 1e-30))
                        result['Chi2'] = chi2
                        result['DOF'] = dof
                        result['SNR'] = snr

                        ok_thresh = getattr(self, 'ok_rms_threshold', 0.10)
                        # threshold is a fraction of the mean signal amplitude, in the same units as rms
                        threshold = np.mean(abs(signal_for_stats)) * ok_thresh

                        if rms < threshold:
                            status = "OK"
                            if attempt == 1: status = "Recovered" 
                        else:
                            status = "Unstable"

                        result['Status'] = status

                        # Always update last_valid_shift so the step-limit window can
                        # drift even during Unstable periods.  Without this the optimizer
                        # stays locked at the same center and perpetually hits the wall.
                        # The per-scan step_limit in _setup_fit_parameters already
                        # guarantees the shift cannot jump more than step_limit px/scan.
                        if len(opt_shifts) > 0:
                            last_valid_shift = opt_shifts[ 0 ]

                        # If OK or already retrying, exit the loop
                        if status in ["OK", "Recovered"] or attempt == max_retries - 1:
                            break
                        else:
                            # If status is bad, trigger defensive mode in the next loop
                            self.needs_pre_calibration = True
                            
                    except Exception as e:
                        if attempt == max_retries - 1: raise e
                        self.needs_pre_calibration = True

                # 7. Send to UI
                should_update = (self.update_interval > 0) and (i % self.update_interval == 0)
                if should_update or i == total_files - 1:
                    plot_signal = intensity_raw if is_linear_mode else optical_depth
                    diff_data = plot_signal - poly_val_orig - etalon_part_orig
                    diff_fit = fit_sign * abs_val_orig
                    ch_label = f"[CH{self.channel}] " if self.channel > 1 else ""
                    self.plot_update.emit(pixel_idx, diff_data, diff_fit, np.zeros_like(pixel_idx), final_params_dict, ch_label + os.path.basename(file_path))
                    sh_val, sq_val = opt_shifts[ 0 ] if len(opt_shifts) > 0 else 0, opt_squeezes[ 0 ] if len(opt_squeezes) > 0 else 1
                    self.trend_update.emit({'idx': i, 'shift': sh_val, 'squeeze': sq_val, 'rms': rms, 'channel': self.channel})
                    
            except Exception as e: 
                result['Status'] = f"Skip: {str(e)}"
                result['RMS'] = 0
                result['Params'] = {}
                self.needs_pre_calibration = True 
                
            self.result_ready.emit(result, i)
            time.sleep(self.delay_ms / 1000.0 if self.delay_ms > 0 else 0.001)

        self.scan_count_ready.emit(i + 1)   # final actual count (in case estimate differed)
        self.finished.emit()

    def update_mirror_reflectivity(self, wave_nm, t, p):
        """
        Derives (1-R(λ))/d from the ratio of Zero-Air and Helium intensities.

        Physics (Washenfelder et al. 2008)
        -----------------------------------
        BBCEAS measures intensity I under continuous-wave excitation:
            I = I₀ · (1-R) / [(1-R) + α·d]

        For two gases with known Rayleigh scattering (ZA and He):
            I_ZA / I_He = (α_He + (1-R)/d) / (α_ZA + (1-R)/d)

        Rearranging for (1-R)/d:
            (1-R)/d = (ratio·α_ZA − α_He) / (1 − ratio)

        This quantity is stored and reused for every subsequent ambient measurement
        to convert raw intensity ratios into absolute optical depth.
        """
        # ZA Rayleigh uses ZA scan's T/P; He Rayleigh uses He scan's T/P.
        # Using the same T/P for both would bias (1-R)/d when ZA and He scans differ in T/P.
        alpha_ray_za = RayleighPhysics.get_alpha_rayleigh(wave_nm, self.t_za_last, self.p_za_last, 'zero_air')
        alpha_ray_he = RayleighPhysics.get_alpha_rayleigh(wave_nm, self.t_he_last, self.p_he_last, 'helium')

        # Apply the Ratio Formula
        # Guard: pixels where I_ZA == I_He (saturated or dead pixels) give ratio=1.0,
        # making the denominator (1-ratio) = 0 → inf/nan that propagates into optical_depth.
        i_he_safe = np.where(np.abs(self.i_he_last) > 1e-9, self.i_he_last, 1e-9)
        ratio = self.i_za_last / i_he_safe

        print(f"[R-CAL] wave={wave_nm[len(wave_nm)//2]:.2f}nm  "
              f"T_ZA={self.t_za_last:.1f}C P_ZA={self.p_za_last:.1f}mbar  "
              f"T_He={self.t_he_last:.1f}C P_He={self.p_he_last:.1f}mbar  "
              f"I_ZA_mean={np.mean(self.i_za_last):.0f}  I_He_mean={np.mean(self.i_he_last):.0f}  "
              f"ratio_mean={np.mean(ratio):.4f}  "
              f"a_za={alpha_ray_za[len(alpha_ray_za)//2]:.3e}  a_he={alpha_ray_he[len(alpha_ray_he)//2]:.3e}  "
              f"rl_factor={self.rl_factor:.4f}")

        # rl_factor: ZA/He가 채우는 유효 공동 길이 비율 (퍼지 보정)
        with np.errstate(divide='ignore', invalid='ignore'):
            omr_d = self.rl_factor * ((ratio * alpha_ray_za) - alpha_ray_he) / (1.0 - ratio)

        # Replace non-finite values by interpolating from valid neighbours.
        # If ALL pixels are invalid (e.g. ratio≈1 when He/ZA signals are indistinct),
        # keep the previous valid one_minus_r_over_d rather than overwriting with garbage.
        valid_mask = np.isfinite(omr_d) & (omr_d > 0)
        valid_frac = np.sum(valid_mask) / len(omr_d)
        omr_d_mean_valid = np.mean(omr_d[valid_mask]) if valid_mask.any() else np.inf
        # Require ≥95% valid pixels AND Leff > 1 km (omr_d < 1e-5 cm⁻¹).
        # Transition scans (ratio ≈ 1) give valid_frac ~50% and omr_d ≈ 1e-4 — both filters catch them.
        is_good_cal = valid_frac >= 0.95 and omr_d_mean_valid < 1e-5
        if is_good_cal:
            x = np.arange(len(omr_d))
            omr_d = np.interp(x, x[valid_mask], omr_d[valid_mask])
            self.one_minus_r_over_d = omr_d
            print(f"[R-CAL] OK  valid={valid_frac*100:.0f}%  "
                  f"omr_d_mean={np.mean(omr_d):.3e} cm-1  "
                  f"Leff_mean={np.mean(1.0/omr_d)*1e-5:.2f} km  "
                  f"R_mean={1.0 - np.mean(omr_d)*self.cavity_len:.6f}")
        else:
            print(f"[R-CAL] SKIP — valid={valid_frac*100:.0f}%  "
                  f"omr_d_mean={omr_d_mean_valid:.3e} cm-1  "
                  f"(ratio≈{np.nanmean(ratio):.4f}, transition scan?). "
                  f"Keeping previous one_minus_r_over_d.")
            # Do NOT overwrite one_minus_r_over_d — keep the last good value

        if self.one_minus_r_over_d is not None:
            current_r_curve = 1.0 - (self.one_minus_r_over_d * self.cavity_len)
            self.r_curve_update.emit(wave_nm, current_r_curve)

    def stop(self):
        self.is_running = False


class AlphaExportWorker(QThread):
    """
    Alpha-only export: He/ZA 캘리브레이션 → ambient 행마다 alpha(cm-1) 계산 → 파일 저장.
    DOAS 피팅은 수행하지 않으므로 alpha 계산 단계만 독립적으로 확인할 수 있다.
    """
    progress     = pyqtSignal(int)          # (scans_done)
    total_ready  = pyqtSignal(int)          # (total_ambient_expected)
    status_msg   = pyqtSignal(str)          # 한 줄 로그
    finished     = pyqtSignal(str)          # (output_dir_or_error)

    def __init__(self, file_list, pixel_min, pixel_max,
                 wave_nm,               # 1-D array, length = pixel_max - pixel_min
                 flag_za, flag_he, flag_amb,
                 rl_factor, cavity_len,
                 output_dir,
                 dark_spectrum=None,    # 1-D float array (full 2048 px), or None
                 channel=1,             # spectrometer channel (1=CH1/ROI1)
                 r_cal_valid_min=0.90,  # ZA block omr_d 유효 픽셀 최소 비율
                 r_cal_omr_max=1e-5,    # block-mean omr_d 상한 — 이보다 크면 reject
                 avg_sec=60.0,          # ambient 시간평균 창(초). 박사님 avgsec=60. 0이면 스캔별(평균 안 함)
                 channel_label="",      # 채널 라벨(PNs/ANs/Cold 등) — 출력 파일명·헤더에 사용
                 std_t_bins=None,       # 박사님 형식: (N,2) [st_sec, end_sec] 연초기준 초 — 주면 이 그리드에 binning
                 drnam_date="",         # 박사님 형식 폴더/파일명용 YYYYMMDD
                 drnam_chlabel=""):     # 박사님 형식 채널 접두(ch1/ch2/ch3)
        """
        r_cal_valid_min, r_cal_omr_max : ZA block 별 R-cal 후보 채택 기준.
          기본값(0.90 / 1e-5)은 high-finesse cavity (R>0.999, omr_d ~ 1e-6) 가정.
          low/mid-finesse cavity (R~0.93-0.99, omr_d ~ 1e-5 ~ 1e-4)에선 둘 다 완화 필요:
            - r_cal_valid_min=0.50, r_cal_omr_max=1e-3 정도.
          이 값들이 너무 빡빡하면 R-cal candidate 없어 "no valid R-cal" 에러 나거나
          가장자리 노이즈만 채택되어 alpha 결과가 망가짐.
        """
        super().__init__()
        self.channel     = channel
        self.file_list   = file_list
        self.pixel_min   = pixel_min
        self.pixel_max   = pixel_max
        self.wave_nm     = np.asarray(wave_nm, dtype=float)
        self.flag_za     = flag_za
        self.flag_he     = flag_he
        self.flag_amb    = flag_amb
        self.rl_factor   = rl_factor
        self.cavity_len  = cavity_len
        self.output_dir  = output_dir
        self.r_cal_valid_min = float(r_cal_valid_min)
        self.r_cal_omr_max   = float(r_cal_omr_max)
        self.avg_sec         = float(avg_sec)
        self.channel_label   = str(channel_label)
        self.std_t_bins      = np.asarray(std_t_bins, dtype=float) if std_t_bins is not None else None
        self.drnam_date      = str(drnam_date)
        self.drnam_chlabel   = str(drnam_chlabel)
        self.is_running  = True
        # dark_spectrum: fit-window slice (pixel_min..pixel_max) already extracted
        if dark_spectrum is not None:
            self.dark = np.asarray(dark_spectrum, dtype=float)
            if len(self.dark) > (pixel_max - pixel_min):
                self.dark = self.dark[pixel_min:pixel_max]
        else:
            self.dark = None

    def stop(self):
        self.is_running = False

    def run(self):
        try:
            self._run_inner()
        except Exception as e:
            self.finished.emit(f"ERROR: {e}")

    def _run_inner(self):
        from scipy.interpolate import PchipInterpolator

        os.makedirs(self.output_dir, exist_ok=True)
        wave_nm = self.wave_nm
        n_pix   = len(wave_nm)

        # expand to (filepath, row_idx) tuples
        expanded = []
        for entry in self.file_list:
            if isinstance(entry, tuple):
                expanded.append(entry)
            else:
                expanded.extend(DataIO.expand_to_scan_list(entry))

        self.total_ready.emit(len(expanded))

        # ── Pass 1: collect all ZA spectra, He spectra, ambient rows ─────────
        # ZA measurements — used to build PCHIP I₀ interpolator
        za_gidx    = []   # global scan index of each ZA row
        za_spectra = []   # (N_pix,) intensity array per ZA
        za_t_list  = []   # ZA temperature
        za_p_list  = []   # ZA pressure

        # He measurements — collected for clean (block-averaged) R-calibration
        he_gidx    = []
        he_spectra = []
        he_t_list  = []
        he_p_list  = []

        # R-calibration candidates (He/ZA pairs)
        calib_candidates = []   # list of (1-R)/d arrays — take median later

        # Ambient rows buffered for Pass 2
        # (fp, row_idx, global_idx, t_amb, p_amb, intensity array)
        amb_buffer = []

        # Per-file calibration header info
        calib_info_per_file = {}   # fp → string describing first good R-cal in file

        i_he_last   = None
        t_he_last   = 25.0
        p_he_last   = 1013.25
        done_scans  = 0
        global_idx  = 0

        # 행별 실제 시각(연초기준 초) — 박사님 doy와 동일한 bytepack 시각.
        # row_idx×0.97 합성 대신 실측값으로 60s 평균 binning/출력 시간축에 사용.
        _sec_cache = {}
        def _row_sec(fp, ridx):
            arr = _sec_cache.get(fp)
            if arr is None:
                arr = DataIO.all_row_seconds(fp)
                _sec_cache[fp] = arr if arr is not None else np.array([])
                arr = _sec_cache[fp]
            return float(arr[ridx]) if (arr.size and ridx < arr.size) else np.nan

        dark = self.dark   # None or 1-D array (n_pix,)
        has_dark = dark is not None
        if has_dark:
            self.status_msg.emit(f"[다크보정] dark spectrum 적용  mean={dark.mean():.1f} counts")
        else:
            self.status_msg.emit("Pass 1: 전체 스캔 읽기 중 (ZA 수집)…")

        for entry in expanded:
            if not self.is_running:
                break
            fp, row_idx = entry
            global_idx += 1

            try:
                _, intensity_raw, state_flag, env_t, env_p = DataIO.load_measurement_with_hk(
                    fp, self.pixel_min, self.pixel_max, row_index=row_idx, channel=self.channel)
            except Exception as e:
                self.status_msg.emit(f"SKIP {os.path.basename(fp)}[{row_idx}]: {e}")
                continue

            is_za  = state_flag in self.flag_za
            is_he  = state_flag in self.flag_he
            is_amb = (state_flag == 0 or
                      (self.flag_amb and state_flag in self.flag_amb) or
                      (not self.flag_amb and not is_za and not is_he))

            # ── 단순 수집만 (R/I0는 Pass 1 종료 후 injection 블록평균으로 계산) ──
            # 개별 단일 스캔은 noise(~1%)가 커서 I0에 그대로 실리면 alpha가 망가진다.
            # 한 injection의 모든 ZA/He 스캔을 모아 두었다가 블록평균한다.
            if is_he:
                he_gidx.append(global_idx)
                he_spectra.append(intensity_raw.copy())
                he_t_list.append(env_t)
                he_p_list.append(env_p)

            elif is_za:
                za_gidx.append(global_idx)
                za_spectra.append(intensity_raw.copy())
                za_t_list.append(env_t)
                za_p_list.append(env_p)

            elif is_amb:
                amb_buffer.append((fp, row_idx, global_idx, _row_sec(fp, row_idx),
                                   env_t, env_p,
                                   intensity_raw.copy()))   # raw 저장, Pass 2에서 보정
                done_scans += 1
                self.progress.emit(done_scans)

        if not self.is_running:
            self.finished.emit("ERROR: 중단됨")
            return

        # ── Block-average each ZA / He injection into one clean spectrum ──────
        # 핵심 수정: 개별 단일 스캔(noise ~1%)을 그대로 I0로 쓰면 alpha가 망가진다.
        # 한 injection(연속 global idx)의 모든 스캔을 평균해 깨끗한 I0/R을 만든다.
        # (박사님 MATLAB Zs/Alpha 의 blockfinder 평균과 동일 접근)
        def _block_average(gidx_list, spec_list, t_list, p_list, gap=10):
            if not gidx_list:
                return [], [], [], []
            g = np.array(gidx_list, dtype=float)
            order = np.argsort(g)
            g = g[order]
            S = np.array(spec_list, dtype=float)[order]
            T = np.array(t_list, dtype=float)[order]
            P = np.array(p_list, dtype=float)[order]
            splits = np.where(np.diff(g) > gap)[0] + 1
            bg = [float(np.mean(b))     for b in np.split(g, splits)]
            bs = [np.nanmean(b, axis=0) for b in np.split(S, splits)]
            bt = [float(np.nanmean(b))  for b in np.split(T, splits)]
            bp = [float(np.nanmean(b))  for b in np.split(P, splits)]
            return bg, bs, bt, bp

        n_za_raw, n_he_raw = len(za_gidx), len(he_gidx)
        za_gidx, za_spectra, za_t_list, za_p_list = _block_average(
            za_gidx, za_spectra, za_t_list, za_p_list)
        he_gidx, he_spectra, he_t_list, he_p_list = _block_average(
            he_gidx, he_spectra, he_t_list, he_p_list)
        self.status_msg.emit(
            f"[I0] ZA {n_za_raw}스캔→{len(za_gidx)}블록, He {n_he_raw}스캔→{len(he_gidx)}블록 평균")

        # dark 보정 (블록평균 후 한 번만)
        if has_dark:
            za_spectra = [s - dark for s in za_spectra]
            he_spectra = [s - dark for s in he_spectra]

        # ── R-calibration: R Trend Monitor와 동일한 reflectance_calc 로 통일 ──
        # α 가 쓰는 (1-R)/d 를 R Trend 파이프라인과 같은 코드로 만든다. near-0
        # 필터·He/ZA contrast band·5차 다항식 피팅·비물리 제외가 그대로 적용된
        # omr_d_fitted 를 calib 으로 사용한다. 품질 미달/오류 시에는 기존
        # per-block median 방식으로 폴백해 robustness 유지.
        if za_spectra and he_spectra:
            calib_str = "unknown"
            try:
                import sys as _sys
                _tools = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
                if _tools not in _sys.path:
                    _sys.path.insert(0, _tools)
                from reflectance_calc import ReflectanceCalculator
                rc = ReflectanceCalculator(cavity_len=self.cavity_len, rl_factor=self.rl_factor)
                for s, t, p in zip(za_spectra, za_t_list, za_p_list):
                    rc.add_za_spectrum(s, t, p)
                for s, t, p in zip(he_spectra, he_t_list, he_p_list):
                    rc.add_he_spectrum(s, t, p)
                roi_lo, roi_hi = float(np.nanmin(wave_nm)), float(np.nanmax(wave_nm))
                _w, _rraw, r_fit, omr_d_fit = rc.calculate(
                    wave_nm, min_valid_fraction=0.30, roi_min=roi_lo, roi_max=roi_hi)
                omr_d_fit = np.maximum(np.asarray(omr_d_fit, dtype=float), 1e-12)
                calib_candidates.append(omr_d_fit)   # 단일 통일 곡선 (하류 median=자기자신)
                leff  = float(np.mean(1.0 / omr_d_fit) * 1e-5)
                rmean = float(np.mean(r_fit))
                calib_str = (f"Leff={leff:.2f} km  R={rmean:.6f}  "
                             f"contrast={getattr(rc, 'he_za_contrast', float('nan')):.3f}")
                self.status_msg.emit(
                    f"[R-CAL 통일/reflectance_calc] {calib_str}  "
                    f"(ZA {len(za_spectra)}블록, He {len(he_spectra)}블록)")
            except Exception as e:
                # 폴백: 기존 per-block median 방식 (전환플래그 오염 등은 위 필터가
                # 없으므로 R Trend 와 다를 수 있음 — 어디까지나 비상용)
                self.status_msg.emit(f"[R-CAL] reflectance_calc 실패 → 기존 방식 폴백: {e}")
                i_he_clean   = np.nanmean(np.array(he_spectra), axis=0)
                t_he_clean   = float(np.nanmean(he_t_list))
                p_he_clean   = float(np.nanmean(he_p_list))
                i_he_s       = np.where(np.abs(i_he_clean) > 1.0, i_he_clean, 1.0)
                alpha_ray_he = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_he_clean, p_he_clean, 'helium')
                for i_za_b, t_za_b, p_za_b, g_za_b in zip(za_spectra, za_t_list, za_p_list, za_gidx):
                    alpha_ray_za = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_za_b, p_za_b, 'zero_air')
                    ratio = i_za_b / i_he_s
                    with np.errstate(divide='ignore', invalid='ignore'):
                        omr_d = self.rl_factor * ((ratio * alpha_ray_za) - alpha_ray_he) / (1.0 - ratio)
                    valid = np.isfinite(omr_d) & (omr_d > 0)
                    if (valid.mean() >= self.r_cal_valid_min
                            and np.nanmean(omr_d[valid]) < self.r_cal_omr_max):
                        x = np.arange(n_pix)
                        calib_candidates.append(np.interp(x, x[valid], omr_d[valid]))
                if calib_candidates:
                    calib_str = (f"Leff={np.mean(1.0/np.median(np.array(calib_candidates),axis=0))*1e-5:.2f}"
                                 f" km (fallback)")
            for fp_amb in {e[0] for e in amb_buffer}:
                calib_info_per_file[fp_amb] = calib_str

        # ── Build PCHIP I₀ interpolator ───────────────────────────────────────
        if len(za_gidx) < 2:
            # Fallback: single static ZA (original behaviour)
            self.status_msg.emit(f"[경고] ZA 측정 {len(za_gidx)}개 → 정적 I₀ 사용")
            use_pchip = False
            i_za_static = za_spectra[0] if za_spectra else None
            t_za_static = za_t_list[0]  if za_t_list  else 25.0
            p_za_static = za_p_list[0]  if za_p_list  else 1013.25
        else:
            use_pchip = True
            za_x   = np.array(za_gidx,    dtype=float)
            za_arr = np.array(za_spectra,  dtype=float)   # (N_za, N_pix)
            za_t   = np.array(za_t_list,   dtype=float)
            za_p   = np.array(za_p_list,   dtype=float)
            pchip_i0 = PchipInterpolator(za_x, za_arr, extrapolate=False)
            pchip_t  = PchipInterpolator(za_x, za_t,   extrapolate=False)
            pchip_p  = PchipInterpolator(za_x, za_p,   extrapolate=False)
            # 경계 밖 외삽은 최근접 ZA를 상수로 사용
            za_x_min, za_x_max = za_x[0], za_x[-1]
            i0_first, i0_last  = za_arr[0],  za_arr[-1]
            t_first,  t_last   = float(za_t[0]),  float(za_t[-1])
            p_first,  p_last   = float(za_p[0]),  float(za_p[-1])
            self.status_msg.emit(
                f"[PCHIP] ZA 측정 {len(za_gidx)}개로 I₀ 보간기 구성  "
                f"(global idx {za_gidx[0]}~{za_gidx[-1]})")

        # ── Best R-calibration: median across all valid candidates ─────────────
        if calib_candidates:
            best_omr_d = np.median(np.array(calib_candidates), axis=0)
            leff_med   = np.mean(1.0 / best_omr_d) * 1e-5
            r_med      = 1.0 - np.mean(best_omr_d) * self.cavity_len
            self.status_msg.emit(
                f"[R-CAL 확정] {len(calib_candidates)}개 평균  "
                f"Leff={leff_med:.2f} km  R={r_med:.6f}")
        else:
            best_omr_d = None
            self.status_msg.emit("[경고] 유효 R-calibration 없음 → alpha 계산 불가")

        if best_omr_d is None or (not use_pchip and i_za_static is None):
            self.finished.emit("ERROR: R-calibration 또는 ZA 스펙트럼 없음")
            return

        # ── Pass 2: ambient 를 avg_sec(기본 60초) 시간평균 후 alpha 계산 ────────
        # 박사님 Alpha 파이프라인(Step2 avgsec=60)과 동일. 단일 스캔(~1초)은
        # noise가 커 DOAS 피팅이 불안정해진다 → gidx-시간(약 0.97초/행) 기준으로
        # avg_sec 창마다 ambient intensity 를 평균해 SNR 을 √N 배 높인다.
        # (gidx 는 ZA/He 주입 행까지 포함한 전역 카운터라, 주입으로 생기는
        #  시간 공백도 자동 반영되어 공백을 넘어 평균되지 않는다.)
        SEC_PER_ROW = 0.97   # (폴백) 실측 시각이 없을 때만 사용
        avg_sec = getattr(self, 'avg_sec', 60.0)

        def _avg_ambient(entries):
            """한 파일 ambient entries 를 avg_sec 시간창으로 묶어 평균.
            binning은 **실측 시각(sec, 박사님 doy 기준)** 차분 기준 — row×0.97 합성이
            아니라 실제 시간 갭을 반영(주입/공백을 넘어 평균되지 않음).
            반환: [(rep_row_idx, mean_gidx, rep_sec, T, P, I_avg, n_in_bin), ...]"""
            if not entries:
                return []
            entries = sorted(entries, key=lambda e: e[2])   # by gidx
            g0 = entries[0][2]
            # 실측 sec 가 유효하면 그걸로, 아니면 gidx×0.97 폴백
            secs = np.array([e[3] for e in entries], dtype=float)
            use_real = np.isfinite(secs).all()
            s0 = secs[0] if use_real else None
            bins = {}
            for (_fp, rid, g, sec, t, p, i) in entries:
                if avg_sec <= 0:
                    b = len(bins)
                elif use_real:
                    b = int((sec - s0) / avg_sec)
                else:
                    b = int((g - g0) * SEC_PER_ROW / avg_sec)
                bins.setdefault(b, []).append((rid, g, sec, t, p, i))
            out = []
            for b in sorted(bins):
                grp = bins[b]
                I = np.nanmean(np.array([x[5] for x in grp], dtype=float), axis=0)
                T = float(np.nanmean([x[3] for x in grp]))
                P = float(np.nanmean([x[4] for x in grp]))
                gmean = float(np.mean([x[1] for x in grp]))
                rep_sec = float(np.nanmean([x[2] for x in grp]))
                out.append((grp[0][0], gmean, rep_sec, T, P, I, len(grp)))
            return out

        # ── 박사님 형식: 전 파일 ambient를 std_t 그리드에 binning → per-bin .dat (full 2048px) ──
        # ch{N}_{YYYYMMDD}_000000/ch{N}_{YYYYMMDD}_{bin:06d}.dat, 2048줄 single-column %20.6e, 헤더없음.
        if self.std_t_bins is not None and len(self.std_t_bins):
            st = self.std_t_bins  # (N,2) [st_sec, end_sec] 연초기준 초
            nbin = len(st)
            bin_groups = {}
            for (_fp, rid, g, sec, t, p, i) in amb_buffer:
                if not np.isfinite(sec):
                    continue
                b = int(np.searchsorted(st[:, 0], sec, side='right') - 1)
                if 0 <= b < nbin and sec < st[b, 1]:
                    bin_groups.setdefault(b, []).append((g, t, p, i))
            chp = self.drnam_chlabel or f"ch{self.channel}"
            folder = os.path.join(self.output_dir, f"{chp}_{self.drnam_date}_000000")
            os.makedirs(folder, exist_ok=True)
            n_written = 0
            for b in range(nbin):
                grp = bin_groups.get(b)
                if grp:
                    I = np.nanmean(np.array([x[3] for x in grp], dtype=float), axis=0)
                    t_am = float(np.nanmean([x[1] for x in grp]))
                    p_am = float(np.nanmean([x[2] for x in grp]))
                    gmean = float(np.mean([x[0] for x in grp]))
                    if use_pchip:
                        if gmean < za_x_min:
                            i0_interp, t_i0, p_i0 = i0_first, t_first, p_first
                        elif gmean > za_x_max:
                            i0_interp, t_i0, p_i0 = i0_last, t_last, p_last
                        else:
                            i0_interp, t_i0, p_i0 = pchip_i0(gmean), float(pchip_t(gmean)), float(pchip_p(gmean))
                    else:
                        i0_interp, t_i0, p_i0 = i_za_static, t_za_static, p_za_static
                    i_am_dc = (I - dark) if has_dark else I
                    i0_s = np.where(i0_interp > 0, i0_interp, 1e-9).astype(float)
                    i_am_s = np.where(i_am_dc > 0, i_am_dc, 1e-9).astype(float)
                    alpha_ref = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_i0, p_i0, 'zero_air')
                    alpha_sample = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_am, p_am, 'zero_air')
                    alpha = ((best_omr_d / self.rl_factor + alpha_ref)
                             * ((i0_s - i_am_s) / i_am_s) - (alpha_sample - alpha_ref))
                    n_written += 1
                else:
                    alpha = np.full(len(wave_nm), np.nan)   # 빈 bin
                fn = os.path.join(folder, f"{chp}_{self.drnam_date}_{b+1:06d}.dat")
                np.savetxt(fn, np.asarray(alpha, dtype=float).reshape(-1, 1), fmt='%20.6e')
                if b % 200 == 0:
                    self.progress.emit(b)
            self.status_msg.emit(f"박사님 형식: {n_written}/{nbin} bin 채움 → {folder}")
            self.finished.emit(folder)
            return

        amb_by_fp = {}
        for e in amb_buffer:
            amb_by_fp.setdefault(e[0], []).append(e)

        alpha_buffer = {}   # fp → list of (row_idx, T, P, alpha_array, n_avg)
        n_bins_total = 0
        for fp, entries in amb_by_fp.items():
            if not self.is_running:
                break
            for (row_idx, gmean, rep_sec, t_am, p_am, i_am, n_avg) in _avg_ambient(entries):
                if use_pchip:
                    g = float(gmean)
                    if g < za_x_min:
                        i0_interp, t_i0, p_i0 = i0_first, t_first, p_first
                    elif g > za_x_max:
                        i0_interp, t_i0, p_i0 = i0_last,  t_last,  p_last
                    else:
                        i0_interp = pchip_i0(g)
                        t_i0      = float(pchip_t(g))
                        p_i0      = float(pchip_p(g))
                else:
                    i0_interp = i_za_static
                    t_i0      = t_za_static
                    p_i0      = p_za_static

                # i0_interp: PCHIP I₀ (이미 dark-corrected). i_am: 평균 ambient.
                i_am_dc = (i_am - dark) if has_dark else i_am
                i0_s   = np.where(i0_interp > 0, i0_interp, 1e-9).astype(float)
                i_am_s = np.where(i_am_dc   > 0, i_am_dc,   1e-9).astype(float)

                alpha_ref    = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_i0, p_i0, 'zero_air')
                alpha_sample = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_am, p_am, 'zero_air')

                alpha = ((best_omr_d / self.rl_factor + alpha_ref)
                         * ((i0_s - i_am_s) / i_am_s)
                         - (alpha_sample - alpha_ref))

                alpha_buffer.setdefault(fp, []).append((row_idx, rep_sec, t_am, p_am, alpha, n_avg))
                n_bins_total += 1
        self.status_msg.emit(
            f"Pass 2: ambient {len(amb_buffer)}행 → {avg_sec:.0f}초 평균 {n_bins_total}개 bin 으로 alpha 계산")

        # ── Write one alpha_trace file per source file ─────────────────────────
        n_saved  = 0
        pix_min  = self.pixel_min
        i0_mode  = "PCHIP" if use_pchip else "static"
        n_za     = len(za_gidx)

        from datetime import datetime as _dt, timedelta as _td
        lbl_tag = f"_{self.channel_label}" if self.channel_label else ""
        for fp, rows in alpha_buffer.items():
            stem     = os.path.splitext(os.path.basename(fp))[0]
            out_path = os.path.join(self.output_dir, f"{stem}{lbl_tag}_alpha_trace.dat")
            _yr = DataIO._file_year(fp) or 2026
            def _doy_iso(sec):
                if not np.isfinite(sec):
                    return float('nan'), ''
                doy = sec / 86400.0 + 1.0
                iso = (_dt(_yr, 1, 1) + _td(seconds=float(sec))).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                return doy, iso
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(f"# CAESAR Pro Alpha Export — {os.path.basename(fp)}\n")
                f.write(f"# channel={self.channel}  label={self.channel_label or 'single'}\n")
                f.write(f"# RL_factor={self.rl_factor}  d={self.cavity_len} cm\n")
                f.write(f"# I0_mode={i0_mode}  ZA_count={n_za}\n")
                f.write(f"# ambient_avg_sec={self.avg_sec:.0f}  (ambient {self.avg_sec:.0f}초 시간평균 후 alpha)\n")
                dark_note = f"mean={dark.mean():.1f}" if has_dark else "None"
                f.write(f"# dark_correction={dark_note}\n")
                f.write(f"# Calibration: {calib_info_per_file.get(fp, 'unknown')}\n")
                wv_str = '\t'.join(f"{w:.4f}" for w in wave_nm)
                f.write(f"# wavelength_nm:\t{wv_str}\n")
                f.write("# time = bytepack(col0,col1)/100 (박사님 doy와 동일, 타임존 변환 없음)\n")
                f.write("row_idx\tdoy\tdatetime\tT_C\tP_mbar\t" +
                        '\t'.join(f"px{pix_min+j}" for j in range(n_pix)) + "\n")
                for rid, rep_sec, T, P, alpha, n_avg in rows:
                    doy, iso = _doy_iso(rep_sec)
                    vals = '\t'.join(f"{v:.6e}" for v in alpha)
                    f.write(f"{rid}\t{doy:.6f}\t{iso}\t{T:.2f}\t{P:.2f}\t{vals}\n")
            n_saved += 1
            self.status_msg.emit(
                f"저장: {out_path}  ({len(rows)}개 bin = {self.avg_sec:.0f}초 평균, {i0_mode} I₀)")

        self.finished.emit(self.output_dir if n_saved > 0 else "ERROR: 저장된 파일 없음")


# ─────────────────────────────────────────────────────────────────────────────
class AlphaFitWorker(QThread):
    """
    Stage 2: 저장된 alpha_trace.dat 파일을 읽어 DOAS 피팅 후 ppb 결과 저장.
    AlphaExportWorker로 생성한 파일을 입력으로 받는다.

    출력 포맷 (TSV):
        row_idx  T_C  P_mbar  CHOCHO_ppb  H2O_ppb  NO2_ppb  rms  ...
    """
    progress    = pyqtSignal(int)
    total_ready = pyqtSignal(int)
    status_msg  = pyqtSignal(str)
    finished    = pyqtSignal(str)

    def __init__(self, alpha_files, engine, poly_deg, output_dir,
                 pixel_min=0, pixel_max=None,
                 ref_properties=None, step_limit=0.5,
                 etalon_freq_min=0.02, etalon_freq_max=0.40,
                 tikhonov_lambda=0.0, use_robust=False,
                 use_varpro=True, fit_etalon=True):
        """
        alpha_files : list of str — alpha_trace.dat 경로 목록
        engine      : UniversalEngine 인스턴스 (레퍼런스 & 파장 포함)
        poly_deg    : int — Chebyshev 다항식 차수 (baseline)
        output_dir  : str — 결과 저장 디렉터리
        pixel_min   : int — 피팅 윈도우 시작 픽셀
        pixel_max   : int — 피팅 윈도우 끝 픽셀 (None이면 전체 파장 축 사용)

        VarPro 통일(raw↔alpha 일치):
        ref_properties : 가스별 shift/squeeze 모드(없으면 shift Limit±0.5 / squeeze Fix).
        step_limit, etalon_freq_min/max, tikhonov_lambda, use_robust : raw 핏과 동일한 설정.
        use_varpro : True면 raw와 동일한 VarPro, False면 구형 선형 lstsq(빠른 폴백).
        fit_etalon : etalon fringe 항 포함 여부(첫 행에서 1회 검출 후 재사용).
        """
        super().__init__()
        self.alpha_files = alpha_files
        self.engine      = engine
        self.poly_deg    = poly_deg
        self.output_dir  = output_dir
        self.pixel_min   = pixel_min
        self.pixel_max   = pixel_max
        self.ref_properties  = ref_properties
        self.step_limit      = step_limit
        self.etalon_freq_min = etalon_freq_min
        self.etalon_freq_max = etalon_freq_max
        self.tikhonov_lambda = tikhonov_lambda
        self.use_robust      = use_robust
        self.use_varpro      = use_varpro
        self.fit_etalon      = fit_etalon
        self.is_running  = True

    def _default_ref_properties(self):
        """ref_properties 미지정 시 합리적 기본값: shift Limit±0.5, squeeze Fix 1.0."""
        if self.ref_properties:
            return self.ref_properties
        return {g: {"sh_mode": "Limit", "sh_val": "-0.5, 0.5",
                    "sq_mode": "Fix", "sq_val": "1.0",
                    "t_ref": 25.0, "t_coeff": 0.0, "active_bands_nm": ""}
                for g in self.engine.gas_list}

    def stop(self):
        self.is_running = False

    def run(self):
        try:
            self._run_inner()
        except Exception as e:
            import traceback
            self.finished.emit(f"ERROR: {e}\n{traceback.format_exc()}")

    def _run_inner(self):
        os.makedirs(self.output_dir, exist_ok=True)

        engine   = self.engine
        gas_list = engine.gas_list
        n_gas    = len(gas_list)

        # 전체 행 수 추정 (progress bar용)
        total_est = sum(
            max(0, sum(1 for l in open(f, encoding='utf-8', errors='replace')
                       if l.strip() and not l.startswith('#') and not l.startswith('row_idx')))
            for f in self.alpha_files
        )
        self.total_ready.emit(max(total_est, 1))

        done = 0

        for fpath in self.alpha_files:
            if not self.is_running:
                break

            fname = os.path.basename(fpath)
            stem  = os.path.splitext(fname)[0].replace('_alpha_trace', '')
            out_path = os.path.join(self.output_dir, f"{stem}_fit.tsv")

            # ── 파일 읽기 ────────────────────────────────────────────────────
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()
            except Exception as e:
                self.status_msg.emit(f"SKIP {fname}: {e}")
                continue

            # ── 헤더에서 파장축 추출 (# wavelength_nm: 라인) ────────────────
            wave_nm_file = None
            for l in lines:
                if l.startswith('# wavelength_nm:'):
                    try:
                        vals = l.split(':', 1)[1].strip().split('\t')
                        wave_nm_file = np.array([float(v) for v in vals if v.strip()],
                                                dtype=float)
                    except Exception:
                        pass
                    break

            # ── 데이터 행 추출 ────────────────────────────────────────────────
            data_lines = [l for l in lines
                          if l.strip() and not l.startswith('#')
                          and not l.startswith('row_idx')]

            if not data_lines:
                self.status_msg.emit(f"SKIP {fname}: 데이터 없음")
                continue

            # ── 컬럼 헤더(row_idx …) 파싱 → 메타/alpha 위치(구·신 포맷 모두 지원) ──
            # 구: row_idx, T_C, P_mbar, px…   신: row_idx, doy, datetime, T_C, P_mbar, px…
            hdr_cols = next((l.rstrip('\n').split('\t')
                             for l in lines if l.startswith('row_idx')), None)
            def _mi(name, default=None):
                return hdr_cols.index(name) if (hdr_cols and name in hdr_cols) else default
            first_px = None
            if hdr_cols:
                first_px = next((i for i, c in enumerate(hdr_cols) if c.startswith('px')), None)
            idx_doy = _mi('doy')
            idx_dt  = _mi('datetime')
            idx_T   = _mi('T_C', 1)
            idx_P   = _mi('P_mbar', 2)
            alpha_start = first_px if first_px is not None else 3

            # ── n_pix: 헤더 파장 수 우선, 없으면 컬럼 수로 감지 ────────────────
            first_parts = data_lines[0].strip().split('\t')
            n_cols = len(first_parts)

            if wave_nm_file is not None:
                n_pix = len(wave_nm_file)
            elif n_cols > alpha_start:
                n_pix = n_cols - alpha_start
                if engine._wave_axis is not None:
                    full_wave = np.asarray(engine._wave_axis, dtype=float)
                    px_min = self.pixel_min
                    wave_nm_file = full_wave[px_min: px_min + n_pix]
                else:
                    wave_nm_file = np.arange(n_pix, dtype=float)
            else:
                self.status_msg.emit(f"SKIP {fname}: 형식 인식 불가 (컬럼 수={n_cols})")
                continue

            if n_pix == 0:
                self.status_msg.emit(f"SKIP {fname}: n_pix=0")
                continue

            self.status_msg.emit(
                f"[{fname}] n_pix={n_pix}  wave={wave_nm_file[0]:.2f}–{wave_nm_file[-1]:.2f} nm")

            # ── 레퍼런스 행렬 구성 (파일 파장축으로 interpolation) ────────────
            ref_cols = []
            for name in gas_list:
                if name in engine.interpolators:
                    ref_interp = engine.interpolators[name](wave_nm_file)
                else:
                    # interpolator 없으면 raw_references 픽셀 슬라이스 폴백
                    ref_raw = np.asarray(engine.raw_references[name], dtype=float)
                    if len(ref_raw) >= n_pix:
                        ref_interp = ref_raw[:n_pix]
                    else:
                        ref_interp = np.pad(ref_raw, (0, n_pix - len(ref_raw)))
                scale = engine.scaling_factors.get(name, 1.0)
                ref_cols.append(ref_interp / scale)

            x_norm = 2.0 * (np.arange(n_pix) / max(n_pix - 1, 1)) - 1.0
            poly_basis = np.column_stack([
                np.polynomial.chebyshev.chebval(x_norm, np.eye(self.poly_deg + 1)[k])
                for k in range(self.poly_deg + 1)
            ])
            A_ref = np.column_stack(ref_cols)
            A     = np.column_stack([A_ref, poly_basis])

            # ── VarPro 셋업(raw와 동일한 핏) ─────────────────────────────────
            # interpolators는 픽셀-인덱스 → alpha 파일 헤더 파장(nm)을 engine 픽셀로
            # 매핑해 raw와 동일한 픽셀 공간에서 평가한다(nm-into-pixel 버그 제거).
            varpro = bool(self.use_varpro)
            fitter = None
            vp_pixel = None
            vp_setup = None
            vp_center = None
            vp_efreq = 0.0
            if varpro:
                from core.doas_fit import DoasFitter
                fitter = DoasFitter(engine)
                if engine._wave_axis is not None:
                    wax = np.asarray(engine._wave_axis, dtype=float).flatten()
                    from scipy.interpolate import interp1d as _i1d
                    _px_of = _i1d(wax, np.arange(len(wax)), bounds_error=False,
                                 fill_value='extrapolate')
                    vp_pixel = np.asarray(_px_of(wave_nm_file), dtype=float)
                else:
                    vp_pixel = np.arange(n_pix, dtype=float) + self.pixel_min
                vp_center = vp_pixel[len(vp_pixel) // 2]
                refprops = self._default_ref_properties()
                vp_setup = fitter.setup_fit_parameters(refprops, 0.0, [0.0, 1.0],
                                                       self.step_limit)

            # ── 행별 파싱 & 피팅 ─────────────────────────────────────────────
            result_rows = []
            _W = np.eye(n_pix)

            for line in data_lines:
                if not self.is_running:
                    break

                parts = line.strip().split('\t')
                if len(parts) < alpha_start + n_pix:
                    self.status_msg.emit(
                        f"  행 스킵: 컬럼 {len(parts)} < 필요 {alpha_start+n_pix} "
                        f"(파일 n_pix={n_pix}와 행 컬럼 수 불일치)")
                    done += 1
                    self.progress.emit(done)
                    continue

                try:
                    row_idx = int(float(parts[0]))
                    T_C     = float(parts[idx_T])
                    P_mbar  = float(parts[idx_P])
                    row_doy = float(parts[idx_doy]) if idx_doy is not None else float('nan')
                    row_dt  = parts[idx_dt] if idx_dt is not None else ''
                    alpha   = np.array([float(v) for v in parts[alpha_start:alpha_start + n_pix]], dtype=float)
                except (ValueError, IndexError) as e:
                    self.status_msg.emit(f"  행 파싱 오류: {e}")
                    done += 1
                    self.progress.emit(done)
                    continue

                if varpro:
                    # raw와 동일한 VarPro(shift/squeeze/etalon/robust/Tikhonov).
                    # etalon 주파수는 첫 유효행에서 1회 검출 후 파일 내 재사용.
                    if self.fit_etalon and vp_efreq == 0.0:
                        vp_efreq = fitter.detect_etalon_frequency(
                            vp_pixel, alpha, self.poly_deg,
                            self.etalon_freq_min, self.etalon_freq_max)
                    active, fixed, linked, t0, lb, ub = vp_setup
                    out = fitter.execute_varpro_fit(
                        vp_pixel, alpha, _W, active, fixed, linked, t0, lb, ub,
                        self.poly_deg, vp_efreq, vp_center, 1.0,
                        self._default_ref_properties(), T_C,
                        self.tikhonov_lambda, self.use_robust)
                    opt_shifts, opt_squeezes, gas_coeffs, poly_c, etal_amp, best_ep, _perr = out
                    # 모델 재구성(rms in α 단위)
                    full_model, *_ = engine.get_model_components(
                        vp_pixel, opt_shifts, opt_squeezes, gas_coeffs, poly_c,
                        etalon_amp=etal_amp, etalon_freq=vp_efreq, etalon_phase=best_ep)
                    rms = float(np.sqrt(np.mean((alpha - full_model) ** 2)))
                else:
                    coeffs, _, _, _ = scipy_lstsq(A, alpha)
                    gas_coeffs = coeffs[:n_gas]
                    fitted = A @ coeffs
                    rms = float(np.sqrt(np.mean((alpha - fitted) ** 2)))

                n_air = 2.68678e19 * (P_mbar / 1013.25) * (273.15 / (T_C + 273.15))
                ppb_vals = {}
                for gi, name in enumerate(gas_list):
                    scale = engine.scaling_factors.get(name, 1.0)
                    mult  = engine.multipliers.get(name, 1.0)
                    N_cm3 = gas_coeffs[gi] * mult / scale
                    ppb_vals[name] = (N_cm3 / n_air) * 1e9

                result_rows.append((row_idx, row_doy, row_dt, T_C, P_mbar, ppb_vals, rms))
                done += 1
                self.progress.emit(done)

            # ── 결과 저장 ─────────────────────────────────────────────────────
            if not result_rows:
                self.status_msg.emit(f"SKIP {fname}: 피팅된 행 없음")
                continue

            # 출처/단위 명시 헤더 — raw→alpha→fit 전체 사슬을 추적 가능하게.
            from datetime import datetime as _dt
            src_chan = next((l.strip().lstrip('#').strip()
                             for l in lines if l.startswith('# channel=')), '')
            # alpha 헤더의 '# CAESAR Pro Alpha Export — {raw}' 에서 원본 raw 파일명 추출
            raw_src = next((l.split('—', 1)[1].strip()
                            for l in lines if l.startswith('# CAESAR Pro Alpha Export')
                            and '—' in l), '')
            header_lines = [
                "# CAESAR Pro Fit Result",
                f"# raw_source={raw_src}" if raw_src else "# raw_source=unknown",
                f"# source_alpha={fname}",
                f"# fit_range_nm={wave_nm_file[0]:.1f}-{wave_nm_file[-1]:.1f}",
            ]
            if src_chan:
                header_lines.append(f"# {src_chan}")
            # alpha 에 시각 컬럼이 있었으면 fit 결과에도 그대로 통과(실시간 시계열용).
            has_time = any(np.isfinite(r[1]) or r[2] for r in result_rows)
            time_hdr = "doy\tdatetime\t" if has_time else ""
            header_lines += [
                f"# conc_unit=ppb  rms_unit=cm-1  poly_deg={self.poly_deg}",
                f"# generated={_dt.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "row_idx\t" + time_hdr + "T_C\tP_mbar\t" + '\t'.join(gas_list) + '\trms_cm-1',
            ]
            header = '\n'.join(header_lines) + '\n'
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(header)
                for row_idx, row_doy, row_dt, T, P, ppb_vals, rms in result_rows:
                    vals = '\t'.join(f"{ppb_vals.get(g, 0):.4f}" for g in gas_list)
                    tcol = (f"{row_doy:.6f}\t{row_dt}\t" if has_time else "")
                    f.write(f"{row_idx}\t{tcol}{T:.2f}\t{P:.2f}\t{vals}\t{rms:.4e}\n")

            self.status_msg.emit(f"저장: {out_path}  ({len(result_rows)}행, {n_gas}가스)")

        self.finished.emit(self.output_dir)