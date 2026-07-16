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
            override_lam, override_robust,
            allow_negative_gas=getattr(self, 'allow_negative_gas', False))
    
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

    def _prescan_injection_indices(self, expanded_scans):
        """청크+워밍업 병렬화용(터보 모드). 스펙트럼 처리·핏 없이 **플래그만** 빠르게
        읽어, 펼친 스캔(expanded_scans) 기준 주입 스캔의 index를 수집한다.

        반환: dict(za=[index...], he=[index...], amb=[index...])
          za = I0/R 기준이 갱신되는 ZA-injecting(flag 500; 500 미설정이면 모든 ZA),
          he = R 기준 He-injecting(flag 510; 510 미설정이면 모든 He),
          amb = ambient 스캔 index(핏 대상).
        각 청크는 본체 앞 '마지막 za·he index'까지 워밍업으로 replay해 I0/R/shift를
        복원한다(ZA/He는 핏 없이 상태만 갱신 → 워밍업 비용 작음). [[EXISTING_FIT_LOGIC]]
        """
        za_i, he_i, amb_i = [], [], []
        za_inj = 500 if 500 in self.flag_za else None
        he_inj = 510 if 510 in self.flag_he else None
        for idx, entry in enumerate(expanded_scans):
            fp, row_idx = (entry[0], entry[1]) if isinstance(entry, tuple) else (entry, 0)
            # 알파 입력은 플래그가 없어 항상 ambient.
            if self._is_alpha_input(fp):
                amb_i.append(idx); continue
            try:
                _, _raw, flag, _, _ = DataIO.load_measurement_with_hk(
                    fp, self.pixel_min, self.pixel_max, row_index=row_idx, channel=self.channel)
            except Exception:
                amb_i.append(idx); continue   # 못 읽으면 본체에서 동일하게 skip 처리됨
            is_za = flag in self.flag_za
            is_he = flag in self.flag_he
            if is_za:
                if za_inj is None or flag == za_inj:
                    za_i.append(idx)
            elif is_he:
                if he_inj is None or flag == he_inj:
                    he_i.append(idx)
            elif flag == 0 or (self.flag_amb and flag in self.flag_amb) or \
                 (not self.flag_amb and not is_za and not is_he):
                amb_i.append(idx)
            # 그 외(미지 플래그)는 본체에서 skip continue 되므로 어디에도 안 넣음
        print(f"[Chunk prescan] za_inj={len(za_i)} he_inj={len(he_i)} ambient={len(amb_i)}")
        return {'za': za_i, 'he': he_i, 'amb': amb_i}

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
        # Fast mode: dispatch alpha scans to a process pool (see _run_parallel).
        # Falls back to nothing on failure (no double-processing) — user re-runs.
        if getattr(self, 'parallel', False):
            try:
                self._run_parallel()
            except Exception as e:
                import traceback
                print(f"[ParallelFit] failed: {e}\n{traceback.format_exc()}")
                self.finished.emit()
            return
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
            if self._is_alpha_input(file_path):
                _ts = DataIO.parse_alpha_row_time(file_path, row_idx)   # 알파: doy/datetime 컬럼
            else:
                _ts = DataIO.parse_row_timestamp(file_path, row_index=row_idx)
            # 채널 시각 시프트(초). 순수 시간이동 — 계기시각을 출력 시각으로만 보정.
            _off = getattr(self, 'tz_offset_sec', 0)
            if _ts is not None and _off:
                from datetime import timedelta as _td_tz
                _ts = _ts + _td_tz(seconds=_off)
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
                # TD 채널 가스온도 오버라이드: ppb 밀도(n_air) 보정에 실제 가스온도(오븐
                # 180/300°C)를 사용. HK는 셀히터(75°C, 과냉 방지)라 밀도 기준이 아님.
                _gt = getattr(self, 'gas_temp_override', None)
                if _gt is not None:
                    self.temperature = float(_gt)

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
                            # ── RL 적용 수정 (2026-06) ──────────────────────────────────
                            # one_minus_r_over_d = RL·(1-R)/d (R-cal에서 ×RL 됨). 과거 식은
                            # `omr/RL + alpha_ref` 라 RL이 (1-R)/d 항에서 소거돼 RL이 알파에
                            # 무효였다(검증: RL 0.933 vs 1.0 → α 0.00% 변화). HANDOFF 공식
                            # α=RL·[(1-R)/d + α_ZA]·(I_ZA/I−1)−Δα 대로 RL이 괄호 전체를 곱하게
                            # `omr + RL·alpha_ref` 로 교정(= RL·[(1-R)/d + alpha_ref]).
                            alpha_ref = RayleighPhysics.get_alpha_rayleigh(wave_nm, self.t_za_last, self.p_za_last, 'zero_air')
                            alpha_ray_sample = RayleighPhysics.get_alpha_rayleigh(wave_nm, self.temperature, self.pressure, 'zero_air')
                            optical_depth = ((self.one_minus_r_over_d + self.rl_factor * alpha_ref) * ((I_0 - I_meas) / I_meas)
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
                    # (etalon 위상은 더 이상 비선형 파라미터 아님 — doas_fit가 sin·cos
                    #  두 선형열로 처리. 위상 append 제거.)
                    
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
                        n_params = len(theta0) + n_gases + (poly_order + 1) + 2  # etalon=sin+cos 2열
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
                        _sig_mean = float(np.mean(abs(signal_for_stats)))
                        threshold = _sig_mean * ok_thresh
                        result['_signal_mean'] = _sig_mean

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

                # 6.5 ── 자동 품질필터(QC): 불량 핏 행의 가스 농도를 NaN으로 제외 ──
                # 구름/저광량 등으로 핏이 실패하면(RMS가 신호의 임계% 초과 → Status=Unstable),
                # NNLS/음수허용 하에서 NO2가 −로 폭주하고 CHOCHO·H2O가 상쇄상승하는 가짜값이
                # 출력된다. 이 행들의 가스값을 NaN으로 빼서 시계열·통계·내보내기에서 제외한다.
                # (Status·RMS·SNR 컬럼은 사유 추적용으로 유지.) 표준 DOAS QA/QC.
                if getattr(self, 'qc_enabled', True):
                    _qc_reason = ''
                    _rms = float(result.get('RMS', 0.0) or 0.0)
                    # (1) 절대 RMS 상한 — 핵심 기준. 구름/저광량 때 알파 신호가 부풀어
                    #     상대 RMS(Unstable)는 통과하지만 절대 RMS는 정상의 ~100배로 튄다.
                    _rms_abs = float(getattr(self, 'qc_rms_abs', 0.0) or 0.0)
                    if _rms_abs > 0 and _rms > _rms_abs:
                        _qc_reason = f"rms={_rms:.1e}>{_rms_abs:.1e}"
                    # (2) 상대 RMS(Unstable) — 보조
                    _st = result.get('Status', '')
                    if (not _qc_reason) and isinstance(_st, str) and _st.startswith('Unstable'):
                        _qc_reason = f"rms>{getattr(self,'ok_rms_threshold',0.10)*100:.0f}%"
                    # (3) SNR 하한 — 보조
                    _snr_min = float(getattr(self, 'qc_snr_min', 0.0) or 0.0)
                    if (not _qc_reason) and _snr_min > 0 and float(result.get('SNR', np.inf)) < _snr_min:
                        _qc_reason = f"snr<{_snr_min:.0f}"
                    if _qc_reason:
                        for _nm in self.engine.gas_list:
                            result[_nm] = float('nan')
                            if f"{_nm}_Smooth" in result:
                                result[f"{_nm}_Smooth"] = float('nan')
                        result['Status'] = f"QC-Excluded ({_qc_reason})"

                # 7. Send to UI
                should_update = (self.update_interval > 0) and (i % self.update_interval == 0)
                if should_update or i == total_files - 1:
                    plot_signal = intensity_raw if is_linear_mode else optical_depth
                    diff_data = plot_signal - poly_val_orig - etalon_part_orig
                    diff_fit = fit_sign * abs_val_orig
                    ch_label = f"[CH{self.channel}] " if self.channel > 1 else ""
                    # 4번째 인자 = 폴리 베이스라인(모니터 'Polynomial Baseline' 파란선). 예전엔
                    # zeros를 넘겨 화면에 0 직선으로 떴다(폴리는 실제 핏·적용됨 — diff_data에서
                    # poly_val_orig를 빼는 중). 실제 폴리 곡선을 넘겨 보이게 한다.
                    self.plot_update.emit(pixel_idx, diff_data, diff_fit, poly_val_orig, final_params_dict, ch_label + os.path.basename(file_path))
                    sh_val, sq_val = opt_shifts[ 0 ] if len(opt_shifts) > 0 else 0, opt_squeezes[ 0 ] if len(opt_squeezes) > 0 else 1
                    self.trend_update.emit({'idx': i, 'shift': sh_val, 'squeeze': sq_val, 'rms': rms, 'channel': self.channel, 'Time': result.get('Time')})
                    
            except Exception as e: 
                result['Status'] = f"Skip: {str(e)}"
                result['RMS'] = 0
                result['Params'] = {}
                self.needs_pre_calibration = True 
                
            self.result_ready.emit(result, i)
            time.sleep(self.delay_ms / 1000.0 if self.delay_ms > 0 else 0.001)

        self.scan_count_ready.emit(i + 1)   # final actual count (in case estimate differed)
        self.finished.emit()

    # ──────────────────────────────────────────────────────────────────────────
    # 청크+워밍업 병렬화용 알파 핏 (터보 모드). run()의 ambient/linear 경로를
    # emit 없이 [범위] 로 도는 순수 함수. 알파-only라 I0/R/ZA·He 캐리오버 없음 —
    # 스캔간 캐리오버는 last_valid_shift(+current_params·needs_pre_calibration)뿐.
    # run()의 라이브 경로는 건드리지 않는다(무회귀). 검증=run() 순차결과와 per-scan 대조.
    # ──────────────────────────────────────────────────────────────────────────
    def _fit_alpha_range(self, scans, body_start, init_shift=0.0, etalon_freq=None):
        """scans = [(global_i, file_path, row_idx), …] (워밍업+본체, 시간순).
        body_start = scans 내에서 본체가 시작하는 위치(앞쪽 [0:body_start]=워밍업, shift만
        정착시키고 결과 버림). init_shift = 워밍업 시작 last_valid_shift.
        반환: (results[(global_i, result_dict)…] 본체만, shift_traj[전체], etalon_freq)."""
        try:
            current_params = [float(np.atleast_1d(p)[0]) for p in self.params]
        except Exception:
            current_params = [0.0, 1.0] + [0.1] * len(self.engine.gas_list) + [0.0] * 10
        last_valid_shift = float(init_shift)
        self.etalon_freq = etalon_freq            # None이면 첫 스캔에서 1회 검출
        self.needs_pre_calibration = False

        results = []
        shift_traj = []
        for pos, (gi_scan, file_path, row_idx) in enumerate(scans):
            is_body = pos >= body_start
            initial_shift_center = last_valid_shift
            result = {'File': f"{os.path.basename(file_path)} [{row_idx:04d}]",
                      'Channel': self.channel, 'Params': {}}
            try:
                _ts = DataIO.parse_alpha_row_time(file_path, row_idx)
                _off = getattr(self, 'tz_offset_sec', 0)
                if _ts is not None and _off:
                    from datetime import timedelta as _td_tz
                    _ts = _ts + _td_tz(seconds=_off)
                result['Time'] = _ts.strftime('%Y-%m-%d %H:%M:%S') if _ts else f"row {row_idx:04d}"

                # 알파 로드(채널 자체 파장축) + 핏범위 슬라이스
                wave_nm, intensity_raw, env_t, env_p = DataIO.load_alpha_trace_row_full(file_path, row_idx)
                sl = self._alpha_fit_slice(wave_nm)
                if sl is not None:
                    wave_nm = wave_nm[sl]; intensity_raw = intensity_raw[sl]
                pixel_idx = self._alpha_pixels(wave_nm)
                self.temperature = env_t; self.pressure = env_p
                _gt = getattr(self, 'gas_temp_override', None)
                if _gt is not None:
                    self.temperature = float(_gt)

                if np.max(np.abs(intensity_raw)) == 0:
                    result['Status'] = "Skip: All-Zero"
                    if is_body:
                        results.append((gi_scan, result))
                    shift_traj.append(last_valid_shift)
                    continue

                # 알파 = linear mode (optical depth 그대로). raw 경로 없음.
                avg_raw = np.mean(intensity_raw)
                scale_factor = (10 ** (-np.floor(np.log10(abs(avg_raw))))
                                if (abs(avg_raw) < 1e-4 and avg_raw != 0) else 1.0)
                intensity_processed = intensity_raw * scale_factor
                optical_depth = intensity_processed
                fit_sign = 1.0

                poly_start_idx = 2 + len(self.engine.gas_list)
                poly_order = len(current_params) - poly_start_idx - 1
                absolute_center = (self.pixel_min + self.pixel_max) / 2.0 if self.pixel_max else len(intensity_raw) / 2.0

                if self.etalon_freq is None:
                    self.etalon_freq = self._detect_etalon_frequency(pixel_idx, optical_depth, poly_order)

                max_retries = 2
                for attempt in range(max_retries):
                    current_lam = self.tikhonov_lambda
                    current_robust = self.use_robust_fitting
                    if self.needs_pre_calibration:
                        best_sh, best_sq = self.auto_pre_calibrate(pixel_idx, optical_depth, poly_order)
                        current_params[0] = best_sh; current_params[1] = best_sq
                        self.needs_pre_calibration = False
                    if len(current_params) > poly_start_idx:
                        current_params[poly_start_idx] = np.mean(optical_depth)
                        current_params[poly_start_idx + 1: poly_start_idx + 1 + poly_order] = [0.0] * poly_order

                    active_vars, fixed_vars, linked_vars, theta0, theta_lb, theta_ub = \
                        self._setup_fit_parameters(initial_shift_center, current_params)
                    fixed_e_f = self.etalon_freq
                    # (etalon 위상은 더 이상 비선형 파라미터 아님 — doas_fit가 sin·cos
                    #  두 선형열로 처리. 위상 append 제거.)
                    try:
                        weights = np.ones_like(intensity_processed)
                        weights = weights / np.mean(weights)
                        W = np.diag(weights)
                        opt_shifts, opt_squeezes, gas_coeffs_scaled, poly_coeffs_scaled, etalon_amp_scaled, best_ep, gas_errs = \
                            self._execute_varpro_fit(
                                pixel_idx, optical_depth, W, active_vars, fixed_vars, linked_vars,
                                theta0, theta_lb, theta_ub, poly_order, fixed_e_f, absolute_center, fit_sign,
                                override_lam=current_lam, override_robust=current_robust)
                        _, abs_val_scaled, poly_val_scaled, _, _ = self.engine.get_model_components(
                            pixel_idx, opt_shifts, opt_squeezes, gas_coeffs_scaled, poly_coeffs_scaled)
                        abs_val_orig, poly_val_orig = abs_val_scaled / scale_factor, poly_val_scaled / scale_factor
                        etalon_part_orig = (etalon_amp_scaled * np.sin(fixed_e_f * pixel_idx + best_ep)) / scale_factor
                        y_fit_model_orig = poly_val_orig + (fit_sign * abs_val_orig) + etalon_part_orig
                        residual = intensity_raw - y_fit_model_orig
                        rms = np.sqrt(np.mean(residual ** 2))

                        result['RMS'] = rms
                        result['Shift'] = opt_shifts[0] if len(opt_shifts) > 0 else 0
                        result['Squeeze'] = opt_squeezes[0] if len(opt_squeezes) > 0 else 1
                        result['Params'] = {
                            'shifts': opt_shifts, 'squeezes': opt_squeezes,
                            'gas_coeffs': (gas_coeffs_scaled / scale_factor).tolist(),
                            'poly_coeffs': (poly_coeffs_scaled / scale_factor).tolist(),
                            'etalon_amp': etalon_amp_scaled / scale_factor,
                            'etalon_phase': float(best_ep), 'etalon_freq': float(fixed_e_f),
                            'channel': self.channel}

                        raw_concentrations, real_errors = [], []
                        for gj, nm in enumerate(self.engine.gas_list):
                            scale_div = self.engine.scaling_factors[nm]
                            mult_i = self.engine.multipliers.get(nm, 1.0)
                            real_conc = (gas_coeffs_scaled[gj] / scale_factor) / scale_div * mult_i
                            real_err = (gas_errs[gj] / scale_factor) / scale_div * mult_i
                            raw_concentrations.append(real_conc); real_errors.append(real_err)

                        n_air = 2.68678e19 * (self.pressure / 1013.25) * (273.15 / (self.temperature + 273.15))
                        dn_air_dT = -n_air / (self.temperature + 273.15)
                        dn_air_dP = n_air / self.pressure
                        rel_err_n = np.sqrt((dn_air_dT * 1.0) ** 2 + (dn_air_dP * 1.0) ** 2) / n_air
                        for gj, nm in enumerate(self.engine.gas_list):
                            ppb_raw = (raw_concentrations[gj] / n_air) * 1e9
                            ppb_err = (real_errors[gj] / n_air) * 1e9
                            ppb_total_err = abs(ppb_raw) * np.sqrt(
                                (ppb_err / max(abs(ppb_raw), 1e-30)) ** 2 + rel_err_n ** 2)
                            result[nm] = ppb_raw
                            result[f"{nm}_Error"] = ppb_err
                            result[f"{nm}_TotalError"] = float(np.mean(ppb_total_err)) if hasattr(ppb_total_err, '__len__') else float(ppb_total_err)
                            result[f"{nm}_MDL"] = 3.0 * ppb_err
                            result[f"{nm}_Shift"] = opt_shifts[gj]
                            result[f"{nm}_Squeeze"] = opt_squeezes[gj]

                        n_pts = len(pixel_idx); n_gases = len(self.engine.gas_list)
                        n_params = len(theta0) + n_gases + (poly_order + 1) + 2  # etalon=sin+cos 2열
                        dof = max(n_pts - n_params, 1)
                        sigma_pix = np.std(np.diff(intensity_raw)) / np.sqrt(2)
                        if sigma_pix < 1e-30:
                            sigma_pix = rms if rms > 1e-30 else 1.0
                        result['Chi2'] = float(np.sum(residual ** 2 / sigma_pix ** 2) / dof)
                        result['DOF'] = dof
                        result['SNR'] = float(np.mean(np.abs(optical_depth)) / (rms + 1e-30))

                        ok_thresh = getattr(self, 'ok_rms_threshold', 0.10)
                        _sig_mean = float(np.mean(abs(intensity_raw)))
                        threshold = _sig_mean * ok_thresh
                        result['_signal_mean'] = _sig_mean
                        if rms < threshold:
                            status = "OK"
                            if attempt == 1: status = "Recovered"
                        else:
                            status = "Unstable"
                        result['Status'] = status
                        if len(opt_shifts) > 0:
                            last_valid_shift = opt_shifts[0]
                        if status in ["OK", "Recovered"] or attempt == max_retries - 1:
                            break
                        else:
                            self.needs_pre_calibration = True
                    except Exception as e:
                        if attempt == max_retries - 1: raise e
                        self.needs_pre_calibration = True

                # QC (run()과 동일)
                if getattr(self, 'qc_enabled', True):
                    _qc_reason = ''
                    _rms = float(result.get('RMS', 0.0) or 0.0)
                    _rms_abs = float(getattr(self, 'qc_rms_abs', 0.0) or 0.0)
                    if _rms_abs > 0 and _rms > _rms_abs:
                        _qc_reason = f"rms={_rms:.1e}>{_rms_abs:.1e}"
                    _st = result.get('Status', '')
                    if (not _qc_reason) and isinstance(_st, str) and _st.startswith('Unstable'):
                        _qc_reason = f"rms>{getattr(self,'ok_rms_threshold',0.10)*100:.0f}%"
                    _snr_min = float(getattr(self, 'qc_snr_min', 0.0) or 0.0)
                    if (not _qc_reason) and _snr_min > 0 and float(result.get('SNR', np.inf)) < _snr_min:
                        _qc_reason = f"snr<{_snr_min:.0f}"
                    if _qc_reason:
                        for _nm in self.engine.gas_list:
                            result[_nm] = float('nan')
                        result['Status'] = f"QC-Excluded ({_qc_reason})"

            except Exception as e:
                result['Status'] = f"Skip: {str(e)}"
                result['RMS'] = 0
                result['Params'] = {}
                self.needs_pre_calibration = True

            shift_traj.append(last_valid_shift)
            if is_body:
                results.append((gi_scan, result))

        return results, shift_traj, self.etalon_freq

    def _chunk_cfg(self):
        """Picklable config sent to each pool worker (see _chunk_init)."""
        nparam = len(self.params)
        return {
            'pixel_min': self.pixel_min, 'pixel_max': self.pixel_max,
            'params': list(self.params),
            'bounds': ([-np.inf] * nparam, [np.inf] * nparam),  # unused by _fit_alpha_range
            'channel': self.channel,
            'ref_properties': self.ref_properties,
            'step_limit': getattr(self, 'step_limit', 0.5),
            'tikhonov_lambda': getattr(self, 'tikhonov_lambda', 0.0),
            'use_robust_fitting': getattr(self, 'use_robust_fitting', False),
            'allow_negative_gas': getattr(self, 'allow_negative_gas', False),
            'fit_unit': getattr(self, 'fit_unit', 'nm'),
            'fit_lo_nm': getattr(self, 'fit_lo_nm', None),
            'fit_hi_nm': getattr(self, 'fit_hi_nm', None),
            'qc_enabled': getattr(self, 'qc_enabled', True),
            'qc_rms_abs': getattr(self, 'qc_rms_abs', 0.0),
            'qc_snr_min': getattr(self, 'qc_snr_min', 0.0),
            'ok_rms_threshold': getattr(self, 'ok_rms_threshold', 0.10),
            'gas_temp_override': getattr(self, 'gas_temp_override', None),
            'tz_offset_sec': getattr(self, 'tz_offset_sec', 0),
            'etalon_freq_min': getattr(self, 'etalon_freq_min', 0.02),
            'etalon_freq_max': getattr(self, 'etalon_freq_max', 0.40),
        }

    def _run_parallel(self):
        """Fast mode: fit alpha scans across a process pool, chunk + warmup.

        Each chunk re-settles last_valid_shift over a short warmup, then fits its
        body — validated to reproduce the sequential fit to ~1e-6 ppb. Results are
        emitted in scan order (buffered) as chunks complete, so the table/plots fill
        in progressively. Alpha-only, so there is no I0/R/ZA/He carryover.

        NOTE (v1): the Kalman _Smooth columns are not produced here (they are a
        trend-monitor-only secondary). Primary ppb is identical to sequential.
        """
        import concurrent.futures as cf

        # Expand to individual scans (alpha rows). Same expansion as the sequential run.
        expanded = []
        for entry in self.file_list:
            if isinstance(entry, tuple):
                expanded.append(entry)
            else:
                expanded.extend(DataIO.expand_to_scan_list(entry))
        scans = [(i, fp, r) for i, (fp, r) in enumerate(expanded)]
        n = len(scans)
        self.scan_count_ready.emit(max(n, 1))
        if n == 0:
            self.finished.emit()
            return

        # Detect the etalon frequency once (on the first scan) and share it with all
        # chunks, exactly as the sequential run detects it once and reuses it.
        _, _, etalon = self._fit_alpha_range(scans[:1], body_start=0,
                                             init_shift=0.0, etalon_freq=None)

        # Use about half the logical cores by default: full saturation pins the CPU
        # at ~100% and starves the GUI process (lag / 'Not Responding'), even with
        # BLAS threads capped. Half keeps the machine usable while still ~Nx faster.
        # Override via self.fit_nproc (set from the UI) if the user wants more/less.
        _cpu = os.cpu_count() or 4
        nproc = int(getattr(self, 'fit_nproc', 0) or max(2, min(8, _cpu // 2)))
        nproc = max(1, min(nproc, _cpu))
        warmup = 40
        # Cap chunk size so each chunk finishes in a bounded time even for a whole
        # campaign (tens of thousands of scans). Big chunks (e.g. 1600 scans ≈ 7 min)
        # mean no results/graphs appear for minutes AND the dispatch loop blocks
        # between completions so Stop can't interrupt and the pool isn't torn down on
        # close (orphan processes). Small-ish chunks → first results in ~1 min,
        # frequent completions → responsive Stop. Floor keeps warmup overhead modest.
        chunk_size = max(150, min(400, -(-n // (nproc * 6))))     # ceil, clamped
        cfg = self._chunk_cfg()

        tasks = []   # [(task_tuple, body_scans), …] — body_scans는 청크 실패 시 Skip 백필용
        bs = 0
        while bs < n:
            be = min(bs + chunk_size, n)
            ws = max(0, bs - warmup)
            tasks.append(((scans[ws:be], bs - ws, 0.0, etalon), scans[bs:be]))
            bs = be

        # Cap BLAS threads to 1 PER worker process BEFORE the pool is spawned, so the
        # children inherit it at import time (setting it inside the worker is too late —
        # numpy/scipy have already initialised their thread pools). Without this, each
        # of the N processes spawns its own BLAS threads → N×threads ≫ cores →
        # oversubscription, ~100% CPU thrash, and a starved/unresponsive GUI.
        for _ev in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                    'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
            os.environ[_ev] = '1'

        done = {}
        nxt = 0
        self.progress.emit(0)
        try:
            with cf.ProcessPoolExecutor(max_workers=nproc, initializer=_chunk_init,
                                        initargs=(self.engine, cfg)) as ex:
                # future → 그 청크의 body 스캔들. 청크가 통째로 죽었을 때(워커 크래시·
                # 피클 실패·OOM 등) 해당 전역 인덱스를 Skip 결과로 백필해 순서-emit 루프
                # (`while nxt in done`)가 그 지점에서 영구 정지하지 않게 하는 보험.
                fut_body = {ex.submit(_chunk_entry, t): body for t, body in tasks}
                pending = set(fut_body)
                while pending:
                    if not self.is_running:
                        for _f in pending:
                            _f.cancel()
                        ex.shutdown(wait=False, cancel_futures=True)
                        break
                    # Wait briefly so Stop (is_running) is checked ~2×/s even while a
                    # chunk is still running — otherwise the loop blocks until a chunk
                    # completes (minutes on big runs) and Stop/close can't interrupt.
                    finished_set, pending = cf.wait(pending, timeout=0.5,
                                                    return_when=cf.FIRST_COMPLETED)
                    for fut in finished_set:
                        try:
                            for gi, r in fut.result():
                                done[gi] = r
                        except Exception as e:
                            print(f"[ParallelFit] chunk error: {e}")
                            # 빠진 인덱스를 Skip으로 메워 emit이 막히지 않게(데이터 유실
                            # 대신 명시적 Skip 표시). 결과 dict 모양은 기존 Skip과 동일.
                            for (gi, _fp, _ridx) in fut_body.get(fut, ()):
                                done.setdefault(gi, {
                                    'File': f"{os.path.basename(_fp)} [{_ridx:04d}]",
                                    'Channel': self.channel, 'Params': {},
                                    'Status': 'Skip: chunk failed', 'RMS': 0})
                    # Emit results in scan order. Fast mode collects them (table/plots
                    # are rendered once at the end), so we only emit result_ready +
                    # progress here — NO per-scan trend/plot signals (those don't keep
                    # up at scale). Pace emission (msleep every ~25) so a large unblocked
                    # prefix doesn't flood the GUI event queue.
                    _since_yield = 0
                    while nxt in done:
                        r = done.pop(nxt)
                        self.result_ready.emit(r, nxt)
                        self.progress.emit(nxt + 1)
                        nxt += 1
                        _since_yield += 1
                        if _since_yield >= 25:
                            _since_yield = 0
                            self.msleep(3)   # yield so the GUI can process queued updates
        finally:
            self.scan_count_ready.emit(max(nxt, 1))
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


# ─── Parallel chunk fitting (Fast mode) ───────────────────────────────────────
# A ProcessPoolExecutor runs AnalysisWorker._fit_alpha_range over contiguous scan
# chunks. Each chunk replays a short warmup to re-settle last_valid_shift, then
# fits its body. Validated to reproduce the sequential fit to ~1e-6 ppb on real
# cold alpha (see diagnostics/parallel_shift_bench/validate_chunk.py).
# Fit is alpha-only, so the only cross-scan state is last_valid_shift — no I0/R/
# ZA/He carryover — which makes chunking safe.
_CHUNK_WORKER = None


def _chunk_init(engine, cfg):
    """Pool initializer: build one AnalysisWorker fit-context per worker process.

    The engine is sent once per process via initargs (picklable). A throwaway
    AnalysisWorker is constructed so _fit_alpha_range can reuse all existing fit
    methods; the per-run config overrides the relevant attributes.
    """
    global _CHUNK_WORKER
    # Cap BLAS to 1 thread PER worker process. scipy bundles its own OpenBLAS
    # (libscipy_openblas) that ignores OPENBLAS_NUM_THREADS, so the env var alone
    # leaves it at 12 threads → 6 procs × 12 = oversubscription → ~100% CPU + GUI
    # freeze. threadpoolctl sets it at runtime on the already-loaded library.
    try:
        from threadpoolctl import threadpool_limits
        globals()['_CHUNK_TPL'] = threadpool_limits(1)   # keep ref so limit isn't reverted
    except Exception:
        os.environ.setdefault('OMP_NUM_THREADS', '1')   # fallback
    from PyQt6.QtCore import QCoreApplication
    import sys as _sys
    if QCoreApplication.instance() is None:
        QCoreApplication(_sys.argv)                 # QThread needs an app object
    w = AnalysisWorker(engine, [], cfg['pixel_min'], cfg['pixel_max'],
                       cfg['params'], cfg['bounds'], -1, channel=cfg['channel'])
    for k in ('ref_properties', 'step_limit', 'tikhonov_lambda', 'use_robust_fitting',
              'allow_negative_gas', 'fit_unit', 'fit_lo_nm', 'fit_hi_nm',
              'qc_enabled', 'qc_rms_abs', 'qc_snr_min', 'ok_rms_threshold',
              'gas_temp_override', 'tz_offset_sec', 'etalon_freq_min', 'etalon_freq_max'):
        if k in cfg:
            setattr(w, k, cfg[k])
    _CHUNK_WORKER = w


def _chunk_entry(task):
    """Fit one chunk in a worker process.

    task = (scans, body_start, init_shift, etalon_freq)
    Returns the body results as a list of (global_scan_index, result_dict).

    The fit is wrapped in threadpool_limits(1) so BLAS stays single-threaded DURING
    the matrix ops regardless of init-time state — N processes × 1 thread, not ×12.
    """
    scans, body_start, init_shift, etalon = task
    try:
        from threadpoolctl import threadpool_limits
        with threadpool_limits(limits=1):
            results, _shift_traj, _etal = _CHUNK_WORKER._fit_alpha_range(
                scans, body_start, init_shift, etalon)
    except Exception:
        results, _shift_traj, _etal = _CHUNK_WORKER._fit_alpha_range(
            scans, body_start, init_shift, etalon)
    return results


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
                 dark_scale_factor=1.0,     # t_meas/t_dark — RUN(AnalysisWorker)과 동일
                 offset_spectrum=None,      # detector offset (full px), or None
                 offset_scale_factor=1.0,   # n_meas/n_offset
                 stray_light_fraction=0.0,  # ε: I_corr=(I−ε·mean(I))/(1−ε)
                 channel=1,             # spectrometer channel (1=CH1/ROI1)
                 r_cal_valid_min=0.90,  # ZA block omr_d 유효 픽셀 최소 비율
                 r_cal_omr_max=1e-5,    # block-mean omr_d 상한 — 이보다 크면 reject
                 avg_sec=60.0,          # ambient 시간평균 창(초). 박사님 avgsec=60. 0이면 스캔별(평균 안 함)
                 channel_label="",      # 채널 라벨(PNs/ANs/Cold 등) — 출력 파일명·헤더에 사용
                 std_t_bins=None,       # 박사님 형식: (N,2) [st_sec, end_sec] 연초기준 초 — 주면 이 그리드에 binning
                 drnam_date="",         # 박사님 형식 폴더/파일명용 YYYYMMDD
                 drnam_chlabel="",      # 박사님 형식 채널 접두(ch1/ch2/ch3)
                 channel_subdir="",     # wide 형식: 멀티채널 시 출력 하위폴더(ch1/ch2/…), 단일이면 ""
                 rt_path=None):         # R(t) npz 경로(rt_precompute). 주면 자체 R 대신 이걸 시간보간해 사용
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
        self.channel_subdir  = str(channel_subdir)
        self.rt_path         = rt_path
        self.is_running  = True
        # dark_spectrum: fit-window slice (pixel_min..pixel_max) already extracted
        if dark_spectrum is not None:
            self.dark = np.asarray(dark_spectrum, dtype=float)
            if len(self.dark) > (pixel_max - pixel_min):
                self.dark = self.dark[pixel_min:pixel_max]
        else:
            self.dark = None
        # detector offset / dark-scale / stray light — RUN 경로(AnalysisWorker)와 물리 일치.
        # 기본값(scale=1, offset=None, ε=0)에선 기존 'I−dark'와 완전 동일(무회귀).
        self.dark_scale_factor    = float(dark_scale_factor)
        self.offset_scale_factor  = float(offset_scale_factor)
        self.stray_light_fraction = float(stray_light_fraction)
        if offset_spectrum is not None:
            self.offset = np.asarray(offset_spectrum, dtype=float)
            if len(self.offset) > (pixel_max - pixel_min):
                self.offset = self.offset[pixel_min:pixel_max]
        else:
            self.offset = None

    def _correct_intensity(self, I):
        """강도 보정(dark·offset·stray) — RUN(AnalysisWorker L488-494)과 동일 물리식.
        보정값이 모두 기본이면 원본을 그대로 반환해 byte-동일(무회귀)을 보장한다."""
        I = np.asarray(I, dtype=float)
        if (self.dark is None and self.offset is None
                and self.stray_light_fraction <= 1e-9):
            return I
        out = I.copy()
        if self.dark is not None:
            out = out - self.dark_scale_factor * self.dark
        if self.offset is not None:
            out = out - self.offset_scale_factor * self.offset
        if self.stray_light_fraction > 1e-9:
            eps = self.stray_light_fraction
            out = (out - eps * np.mean(out)) / (1.0 - eps)
        return out

    def stop(self):
        self.is_running = False

    def run(self):
        try:
            self._run_inner()
        except Exception as e:
            self.finished.emit(f"ERROR: {e}")

    def _run_inner(self):
        os.makedirs(self.output_dir, exist_ok=True)
        wave_nm = self.wave_nm
        n_pix   = len(wave_nm)

        # expand to (filepath, row_idx) tuples — 인덱싱(파일별 스캔수 세기) 진행 표시
        _nf = len(self.file_list)
        self.total_ready.emit(max(1, _nf))
        self.status_msg.emit(f"Indexing {_nf} file(s)…")
        expanded = []
        for _k, entry in enumerate(self.file_list, 1):
            if isinstance(entry, tuple):
                expanded.append(entry)
            else:
                expanded.extend(DataIO.expand_to_scan_list(entry))
            self.progress.emit(_k)
            if _k % 10 == 0 or _k == _nf:
                self.status_msg.emit(f"Indexing {_k}/{_nf} files… ({len(expanded)} scans)")

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

        # Ambient rows — LIGHT index + 임시 바이너리 스풀.
        # RAM 버퍼링(수 GB)도, Pass 2 텍스트 재파싱(2배 느림)도 피하려고:
        #  Pass 1에서 ambient 스펙트럼을 임시 .bin(float32, raw 카운트=정수라 무손실)에
        #  순차로 흘려쓰고, Pass 2는 memmap으로 바로 읽는다 → 저메모리 + 빠름.
        # amb_index[fp] = [(row_idx, global_idx, sec, env_t, env_p, spool_idx), ...]
        amb_index = {}
        amb_count = 0
        import tempfile as _tf
        _amb_spool = _tf.NamedTemporaryFile(prefix='caesar_amb_', suffix='.bin', delete=False)
        _amb_spool_path = _amb_spool.name
        _amb_spool_n = 0   # 기록된 스펙트럼 수
        _amb_mm = None     # Pass 2에서 memmap 할당
        def _cleanup_spool():
            """임시 ambient 스풀(.bin, 최대 GB급) 정리 — 어느 종료 경로에서도 호출."""
            nonlocal _amb_mm
            _amb_mm = None
            import gc as _g; _g.collect()
            try:
                if not _amb_spool.closed:
                    _amb_spool.close()
            except Exception:
                pass
            try:
                os.remove(_amb_spool_path)
            except OSError:
                pass

        # Per-file calibration header info
        calib_info_per_file = {}   # fp → string describing first good R-cal in file

        # (R/I0는 Pass 1 종료 후 블록평균으로 계산 — 옛 'last He' 러닝값은 알파생성에서
        #  쓰지 않는다. self.i_he_last 등은 라이브-R 핏 워커 전용이라 여기선 없음.)
        done_scans  = 0
        global_idx  = 0
        n_default_tp = 0   # HK 읽기 실패로 T/P가 기본값(25.0/1013.25)으로 떨어진 스캔 수

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
            self.status_msg.emit(f"[dark] dark spectrum applied  mean={dark.mean():.1f} counts")
        else:
            self.status_msg.emit("Pass 1: reading all scans (collecting ZA)…")

        # ── 스캔 처리 본체 (순차·병렬 공통) — 분류/스풀/수집 로직은 여기 한 곳만 ──
        # 병렬 경로는 '파싱'만 워커로 돌리고, 데이터는 이 함수로 메인에서 처리한다.
        # 따라서 분류/스풀/R수집 로직은 한 글자도 이동하지 않는다(무회귀 보장).
        def _process_scan(fp, row_idx, intensity_raw, state_flag, env_t, env_p, gidx):
            nonlocal n_default_tp, _amb_spool_n, amb_count, done_scans
            # HK 미복구 폴백 감지: 실측 P는 raw_count×0.6895라 정확히 1013.25가 될 수
            # 없으므로 env_p==1013.25는 'HK 읽기 실패→기본값' 신호. 가시화용 카운트.
            if env_p == 1013.25:
                n_default_tp += 1
            is_za  = state_flag in self.flag_za
            is_he  = state_flag in self.flag_he
            is_amb = (state_flag == 0 or
                      (self.flag_amb and state_flag in self.flag_amb) or
                      (not self.flag_amb and not is_za and not is_he))
            # 단순 수집만(R/I0는 Pass1 후 블록평균). 단일스캔 noise 커서 그대로 안 씀.
            if is_he:
                he_gidx.append(gidx); he_spectra.append(intensity_raw.copy())
                he_t_list.append(env_t); he_p_list.append(env_p)
            elif is_za:
                za_gidx.append(gidx); za_spectra.append(intensity_raw.copy())
                za_t_list.append(env_t); za_p_list.append(env_p)
            elif is_amb:
                _amb_spool.write(np.ascontiguousarray(intensity_raw, dtype=np.float32).tobytes())
                amb_index.setdefault(fp, []).append(
                    (row_idx, gidx, _row_sec(fp, row_idx), env_t, env_p, _amb_spool_n))
                _amb_spool_n += 1; amb_count += 1; done_scans += 1

        if getattr(self, 'use_parallel', True) and len(expanded) > 1:
            # ── 병렬 Pass 1: 파싱(CPU 병목)만 프로세스풀로. gidx는 파일·행 순서 그대로
            #    라 순차와 동일 결과(extract 등가성 바이트검증 완료). 분류/스풀은 메인. ──
            from collections import OrderedDict, deque
            import concurrent.futures as _cf
            from core.data_io import (extract_raw_file_for_parallel as _xtr,
                                      RAW_LOAD_FAIL as _LF)
            _files = []
            _rpf = OrderedDict()
            for _fp, _ri in expanded:
                if _fp not in _rpf:
                    _rpf[_fp] = []; _files.append(_fp)
                _rpf[_fp].append(_ri)
            _tasks = [(fp, self.pixel_min, self.pixel_max, self.channel) for fp in _files]
            # 전체 코어의 절반만(과부하 방지). R calc 병렬파싱과 동일 정책.
            _nproc = max(1, (os.cpu_count() or 4) // 2)
            _win = max(2, _nproc * 2)
            self.status_msg.emit(
                f"Pass 1 (parallel {_nproc} cores): parsing {len(_files)} files…")
            try:
                with _cf.ProcessPoolExecutor(max_workers=_nproc) as _ex:
                    _futs = deque(); _ti = 0
                    while _ti < len(_tasks) and len(_futs) < _win:
                        _futs.append((_files[_ti], _ex.submit(_xtr, _tasks[_ti]))); _ti += 1
                    while _futs:
                        if not self.is_running:
                            break
                        _fp, _fut = _futs.popleft()
                        try:
                            _, _flags, _Ts, _Ps, _specs, _secs = _fut.result()
                        except Exception as e:
                            self.status_msg.emit(f"SKIP(parse) {os.path.basename(_fp)}: {e}")
                            _flags = None
                        if _ti < len(_tasks):
                            _futs.append((_files[_ti], _ex.submit(_xtr, _tasks[_ti]))); _ti += 1
                        if _flags is None:
                            for _ri in _rpf[_fp]:
                                global_idx += 1; self.progress.emit(global_idx)
                            continue
                        _sec_cache[_fp] = _secs
                        for _ri in _rpf[_fp]:
                            global_idx += 1
                            self.progress.emit(global_idx)
                            if _ri >= len(_flags) or _flags[_ri] == _LF:
                                continue
                            _process_scan(_fp, _ri,
                                          np.asarray(_specs[_ri], dtype=float),
                                          int(_flags[_ri]), float(_Ts[_ri]), float(_Ps[_ri]),
                                          global_idx)
            except Exception as e:
                # 병렬 인프라 자체가 죽은 경우: 부분 스풀로 순차 폴백하면 이중기록되어
                # 위험 → 깨끗이 중단(알파 미작성). 사용자가 재실행(또는 use_parallel=False).
                _cleanup_spool()
                self.finished.emit(f"ERROR: parallel parsing failed (please rerun): {e}")
                return
        else:
            # ── 순차 Pass 1 (폴백/검증용; 기존 로직 보존) ──
            for entry in expanded:
                if not self.is_running:
                    break
                fp, row_idx = entry
                global_idx += 1
                self.progress.emit(global_idx)
                try:
                    _, intensity_raw, state_flag, env_t, env_p = DataIO.load_measurement_with_hk(
                        fp, self.pixel_min, self.pixel_max, row_index=row_idx, channel=self.channel)
                except Exception as e:
                    self.status_msg.emit(f"SKIP {os.path.basename(fp)}[{row_idx}]: {e}")
                    continue
                _process_scan(fp, row_idx, intensity_raw, state_flag, env_t, env_p, global_idx)

        if not self.is_running:
            _cleanup_spool()
            self.finished.emit("ERROR: aborted")
            return

        if n_default_tp:
            self.status_msg.emit(
                f"[WARN] HK not recovered → default T/P (25.0℃/1013.25mbar) used for "
                f"{n_default_tp}/{global_idx} scans — their alpha may have inaccurate "
                f"Rayleigh correction (usually bin warmup rows).")

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
            f"[I0] ZA {n_za_raw} scans→{len(za_gidx)} blocks, He {n_he_raw} scans→{len(he_gidx)} blocks averaged")

        # 강도 보정(dark·offset·stray) — 블록평균 후 한 번만. RUN 경로와 동일 물리.
        # 기본값(scale=1·offset=None·ε=0)에선 기존 'I−dark'와 byte-동일(무회귀).
        za_spectra = [self._correct_intensity(s) for s in za_spectra]
        he_spectra = [self._correct_intensity(s) for s in he_spectra]

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
                    f"[R-CAL unified/reflectance_calc] {calib_str}  "
                    f"(ZA {len(za_spectra)} blocks, He {len(he_spectra)} blocks)")
            except Exception as e:
                # 폴백: 기존 per-block median 방식 (전환플래그 오염 등은 위 필터가
                # 없으므로 R Trend 와 다를 수 있음 — 어디까지나 비상용)
                self.status_msg.emit(f"[R-CAL] reflectance_calc failed → fallback to legacy method: {e}")
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
            for fp_amb in amb_index:
                calib_info_per_file[fp_amb] = calib_str

        # ── R(t): ZA마다 최근접 He 페어 → 인젝션별 (1-R)/d → gidx 시간보간 ──────────
        # I0(PCHIP)와 대칭. He(3h)·ZA(1h) 인젝션의 R 시간변화를 보존한다. 기존엔 전
        # 인젝션을 풀링해 런당 단일 R로 뭉갰고(런 경계마다 Leff 점프, 시간정보 소실).
        # 여기서는 각 ZA 블록을 gidx 최근접 He 블록과 페어해 reflectance_calc(동일
        # 품질필터·5차피팅)로 omr_d를 구하고 za_gidx 위에서 보간한다. 유효 knot<2면
        # omr_interp=None → 기존 단일 best_omr_d 로 폴백(무회귀).
        omr_interp = None
        # rt_path(R calibrator 프리컴퓨트 npz)가 있으면 아래 _omr_d_at이 그걸(rt_omr_interp)
        # 우선 쓰므로, 여기서 ZA 블록마다 reflectance_calc(5차 polyfit)로 자체 R(t)를 만드는
        # 건 헛수고다 → 스킵. (rt 로드 실패 시엔 best_omr_d 단일 R로 폴백.)
        if (not getattr(self, 'rt_path', None)) and za_spectra and he_spectra and len(za_gidx) >= 2:
            try:
                from reflectance_calc import ReflectanceCalculator as _RC
            except Exception:
                _RC = None
            if _RC is not None:
                _he_g = np.asarray(he_gidx, dtype=float)
                _roi_lo, _roi_hi = float(np.nanmin(wave_nm)), float(np.nanmax(wave_nm))
                _knots = []
                for _i, _gz in enumerate(za_gidx):
                    _j = int(np.argmin(np.abs(_he_g - _gz)))   # 최근접 He 블록
                    _rc1 = _RC(cavity_len=self.cavity_len, rl_factor=self.rl_factor)
                    _rc1.add_za_spectrum(za_spectra[_i], za_t_list[_i], za_p_list[_i])
                    _rc1.add_he_spectrum(he_spectra[_j], he_t_list[_j], he_p_list[_j])
                    try:
                        _, _, _, _od = _rc1.calculate(
                            wave_nm, min_valid_fraction=0.30,
                            roi_min=_roi_lo, roi_max=_roi_hi)
                    except Exception:
                        continue   # 품질 미달 페어 skip (전환스캔·dropout 등)
                    _od = np.maximum(np.asarray(_od, dtype=float), 1e-12)
                    _knots.append((float(_gz), _od))
                if len(_knots) >= 2:
                    _knots.sort(key=lambda k: k[0])
                    _kg = np.array([k[0] for k in _knots], dtype=float)
                    _kd = np.array([k[1] for k in _knots], dtype=float)   # (N, n_pix)
                    _uniq = np.concatenate(([True], np.diff(_kg) > 0))     # PCHIP: 단조 x
                    _kg, _kd = _kg[_uniq], _kd[_uniq]
                    # 인젝션별 robust 이상치 제거 — pooled median이 자동으로 누르던
                    # 비물리 knot(전환오염·near-0/음수→floor 클램프로 R≈1, Leff→∞, 또는
                    # 과소 Leff)을 per-injection에선 직접 걸러야 PCHIP 보간이 폭주하지
                    # 않는다. knot 평균 Leff가 중앙값의 [0.5×,2×] 밖이면 제외(R 드리프트는
                    # 작아 이 밴드 안. 4e6 km 같은 floor-clamp knot가 여기서 잘린다).
                    _n_rej = 0
                    if len(_kg) >= 2:
                        _leff_k = np.array([float(np.mean(1.0 / d) * 1e-5) for d in _kd])
                        _med = float(np.median(_leff_k))
                        _ok = (np.isfinite(_leff_k)
                               & (_leff_k >= 0.5 * _med) & (_leff_k <= 2.0 * _med))
                        _n_rej = int((~_ok).sum())
                        _kg, _kd, _leff_k = _kg[_ok], _kd[_ok], _leff_k[_ok]
                    if len(_kg) >= 2:
                        # 계단 가드: 자체 R(t)도 계단 후보에서 PCHIP 분절(경계 밖
                        # 최근접 상수 정책은 SegmentedPchip에 내장 — 기존과 동일).
                        # 축이 gidx(스캔 인덱스)라 수동 분절(초 단위)은 rt_path
                        # 경로 전용 — 여기선 자동 감지만.
                        from core.step_guard import (
                            knot_scalar_metric as _sg_metric2,
                            detect_step_candidates as _sg_detect2,
                            SegmentedPchip as _SegPchip2,
                            format_step_report as _sg_fmt2)
                        _sg_c2, _sg_t2 = _sg_detect2(_kg, _sg_metric2(_kd))
                        _pchip_omr = _SegPchip2(
                            _kg, _kd, break_x=[c['x_break'] for c in _sg_c2])
                        def omr_interp(g, _p=_pchip_omr):
                            return _p(float(g))
                        for _ln in _sg_fmt2(_sg_c2, threshold=_sg_t2,
                                            x_to_str=lambda v: f"scan#{v:.0f}",
                                            kind="self R(t)"):
                            self.status_msg.emit(_ln)
                        _seg2 = (f", {_pchip_omr.n_segments} seg"
                                 if _pchip_omr.n_segments > 1 else "")
                        _rt_str = (f"R(t) {len(_kg)} knots{_seg2}  "
                                   f"Leff={_leff_k.min():.2f}~{_leff_k.max():.2f} km "
                                   f"(median {np.median(_leff_k):.2f}, {_n_rej} rej)")
                        for _fp in amb_index:
                            calib_info_per_file[_fp] = _rt_str
                        self.status_msg.emit(f"[R-CAL time-interp] {_rt_str}")

        # Pass 1 스풀(임시 바이너리) 닫기. Pass 2는 파일별 '연속 블록'만 seek+read.
        # (한 파일의 ambient 스캔은 Pass 1에서 연속 기록되므로 한 블록으로 읽힌다.)
        _amb_spool.flush(); _amb_spool.close()
        _row_bytes = n_pix * 4   # float32

        def _reread_amb(fp):
            """파일의 ambient 스펙트럼을 임시 스풀에서 '한 블록'만 읽어 반환.
            한 파일분(~수MB)만 RAM에 → 저메모리 + 텍스트 재파싱 없음(빠름).
            float32 raw 카운트(정수)라 무손실 = 버퍼 방식과 바이트 동일."""
            ents = amb_index.get(fp, [])
            if not ents:
                return []
            seqs = [e[5] for e in ents]
            s0, s1 = min(seqs), max(seqs)
            cnt = s1 - s0 + 1
            try:
                with open(_amb_spool_path, 'rb') as fh:
                    fh.seek(s0 * _row_bytes)
                    block = np.frombuffer(fh.read(cnt * _row_bytes),
                                          dtype=np.float32).reshape(cnt, n_pix)
            except Exception:
                return []
            out = []
            for e in ents:
                inten = np.asarray(block[e[5] - s0], dtype=float)
                out.append((fp, e[0], e[1], e[2], e[3], e[4], inten))
            return out

        # ── Build PCHIP I₀ interpolator ───────────────────────────────────────
        if len(za_gidx) < 2:
            # Fallback: single static ZA (original behaviour)
            self.status_msg.emit(f"[WARN] {len(za_gidx)} ZA measurements → using static I₀")
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
            # 계단 가드: I₀도 LED 조절/재정렬 같은 계단이 knot 사이에 오면 PCHIP이
            # 램프로 뭉갠다 → ZA 블록 평균강도로 계단 후보를 감지해 분절.
            # T/P는 계단지표가 아니지만 I₀와 같은 경계로 분절해 일관성 유지
            # (break 없으면 기존 PCHIP과 동일 출력 = 무회귀).
            from core.step_guard import (
                detect_step_candidates as _sg_detect_i0,
                SegmentedPchip as _SegPchip_i0,
                format_step_report as _sg_fmt_i0)
            _i0_metric = np.nanmean(za_arr, axis=1)
            _i0_cands, _i0_thr = _sg_detect_i0(za_x, _i0_metric)
            _i0_breaks = [c['x_break'] for c in _i0_cands]
            pchip_i0 = _SegPchip_i0(za_x, za_arr, break_x=_i0_breaks)
            pchip_t  = _SegPchip_i0(za_x, za_t,   break_x=_i0_breaks)
            pchip_p  = _SegPchip_i0(za_x, za_p,   break_x=_i0_breaks)
            # 경계 밖 외삽은 최근접 ZA를 상수로 사용
            za_x_min, za_x_max = za_x[0], za_x[-1]
            i0_first, i0_last  = za_arr[0],  za_arr[-1]
            t_first,  t_last   = float(za_t[0]),  float(za_t[-1])
            p_first,  p_last   = float(za_p[0]),  float(za_p[-1])
            _i0_seg = (f", {pchip_i0.n_segments} segments"
                       if pchip_i0.n_segments > 1 else "")
            self.status_msg.emit(
                f"[PCHIP] built I₀ interpolator from {len(za_gidx)} ZA measurements  "
                f"(global idx {za_gidx[0]}~{za_gidx[-1]}{_i0_seg})")
            for _ln in _sg_fmt_i0(_i0_cands, threshold=_i0_thr,
                                  x_to_str=lambda v: f"scan#{v:.0f}", kind="I0(t)"):
                self.status_msg.emit(_ln)

        # ── Best R-calibration: median across all valid candidates ─────────────
        if calib_candidates:
            best_omr_d = np.median(np.array(calib_candidates), axis=0)
            leff_med   = np.mean(1.0 / best_omr_d) * 1e-5
            r_med      = 1.0 - np.mean(best_omr_d) * self.cavity_len
            self.status_msg.emit(
                f"[R-CAL final] averaged {len(calib_candidates)}  "
                f"Leff={leff_med:.2f} km  R={r_med:.6f}")
        else:
            best_omr_d = None
            self.status_msg.emit("[WARN] no valid R-calibration → cannot compute alpha")

        # ── R(t) 외부 로드(rt_path): R_trend(scan_directory)로 미리 뽑은 채널 R(t)를
        #    읽어 '시각(rep_sec)'으로 시간보간. 있으면 워커 자체 R보다 우선(단일 진실원천).
        #    채널창 기반이라 핫도 정상(자체 전체범위 R은 핫 98% 탈락·Leff 2배 오차). ──
        rt_omr_interp = None
        rt_calib_note = None   # rt_path 적용 시 헤더에 박을 출처(없으면 자체 R)
        if getattr(self, 'rt_path', None):
            try:
                import sys as _sys
                _tdir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools')
                if _tdir not in _sys.path:
                    _sys.path.insert(0, _tdir)
                from rt_precompute import load_rt as _load_rt
                _rt = _load_rt(self.rt_path)
                _ks = np.asarray(_rt['knot_sec'], dtype=float)
                _od = np.asarray(_rt['omr_d'], dtype=float)
                _rw = np.asarray(_rt['wave_nm'], dtype=float)
                # 계단 가드 감지는 픽셀축 슬라이스 **전에** — R-fit 신뢰창(config)
                # 기준 스칼라로 봐야 하고, 창이 알파 핏창과 다를 수 있다.
                from core.step_guard import (
                    knot_scalar_metric as _sg_metric,
                    detect_step_candidates as _sg_detect,
                    SegmentedPchip as _SegPchip,
                    format_step_report as _sg_fmt)
                _sg_m = _sg_metric(_od, wave_nm=_rw,
                                   fit_window_nm=(_rt.get('config') or {}).get('fit_window_nm'))
                _sg_cands, _sg_thr = _sg_detect(_ks, _sg_m)
                _sg_manual = list(np.asarray(_rt.get('manual_breaks_sec', []), dtype=float))
                _sg_breaks = sorted([c['x_break'] for c in _sg_cands] + _sg_manual)
                # 픽셀축 정합: 저장 omr_d(보통 full 2048) → 현재 wave_nm.
                if _od.shape[1] == n_pix and np.allclose(_rw[:n_pix], wave_nm, atol=1e-3):
                    pass
                elif _od.shape[1] >= self.pixel_max and np.allclose(
                        _rw[self.pixel_min:self.pixel_max], wave_nm, atol=1e-3):
                    _od = _od[:, self.pixel_min:self.pixel_max]
                else:
                    _od = np.array([np.interp(wave_nm, _rw, row) for row in _od])
                _od = np.maximum(_od, 1e-12)
                if len(_ks) >= 2:
                    # 계단 경계에서 분절된 PCHIP — break 없으면 기존과 동일 출력.
                    _prt = _SegPchip(_ks, _od, break_x=_sg_breaks)
                    def rt_omr_interp(sec, _p=_prt):
                        if not np.isfinite(sec):
                            return None
                        return _p(sec)
                    _seg_note = (f", {_prt.n_segments} segments"
                                 if _prt.n_segments > 1 else "")
                    rt_calib_note = (f"external R(t) — {os.path.basename(self.rt_path)} "
                                     f"({len(_ks)} knots{_seg_note})")
                    self.status_msg.emit(
                        f"[R(t) load] {len(_ks)} knots{_seg_note} "
                        f"({os.path.basename(self.rt_path)})")
                    _fp0 = self.file_list[0] if self.file_list else None
                    if isinstance(_fp0, tuple):
                        _fp0 = _fp0[0]
                    _yr0 = DataIO._file_year(_fp0) if _fp0 else None
                    if _yr0:
                        from datetime import datetime as _sgdt, timedelta as _sgtd
                        _b0 = _sgdt(int(_yr0), 1, 1)
                        _x2s = lambda s: (_b0 + _sgtd(seconds=float(s))).strftime('%m-%d %H:%M')
                    else:
                        _x2s = lambda s: f"doy {s / 86400.0 + 1.0:.3f}"
                    for _ln in _sg_fmt(_sg_cands, threshold=_sg_thr, x_to_str=_x2s,
                                       kind="R(t)"):
                        self.status_msg.emit(_ln)
                    if _sg_manual:
                        self.status_msg.emit(
                            "[STEP GUARD] manual breaks applied: "
                            + ", ".join(_x2s(b) for b in sorted(_sg_manual)))
                elif len(_ks) == 1:
                    _only = _od[0]
                    def rt_omr_interp(sec, _o=_only):
                        return _o
                    rt_calib_note = (f"external R(t) — {os.path.basename(self.rt_path)} (1 knot)")
            except Exception as e:
                self.status_msg.emit(f"[R(t) load failed → using self R] {e}")
                rt_omr_interp = None

        if ((best_omr_d is None and omr_interp is None and rt_omr_interp is None)
                or (not use_pchip and i_za_static is None)):
            _cleanup_spool()
            self.finished.emit("ERROR: no R-calibration or ZA spectrum")
            return

        # bin의 (1-R)/d: rt_path 로드면 시각(sec) 시간보간 우선, 아니면 gidx 보간/단일값.
        def _omr_d_at(g, sec=None):
            if rt_omr_interp is not None and sec is not None:
                _v = rt_omr_interp(sec)
                if _v is not None:
                    return _v
            if omr_interp is not None:
                return omr_interp(float(g))
            return best_omr_d

        # ── zero_air Rayleigh σ는 파장만의 함수(T/P 무관) → 1회만 계산 ──────────
        # α_ray(λ,T,P) = σ(λ)·N(T,P). σ(λ)(Sellmeier, 2048픽셀)는 모든 bin에서 동일하고
        # bin마다 바뀌는 건 스칼라 N(T,P)뿐. STP(0℃,1013.25mbar)에선 N=N0라
        # get_alpha_rayleigh(…,0,1013.25,…)=σ·N0. 이후 bin마다 N/N0 스칼라만 곱한다.
        # bin마다 get_alpha_rayleigh를 재호출하던 것과 수학적으로 동일(무회귀), Sellmeier
        # 재계산만 루프 밖으로 뺀다.
        _ZA_REF = RayleighPhysics.get_alpha_rayleigh(wave_nm, 0.0, 1013.25, 'zero_air')
        def _alpha_za(T, P):
            return _ZA_REF * (float(P) / 1013.25) * (273.15 / (float(T) + 273.15))

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
            # 파일별로 재읽기(스트리밍) — 박사님 형식은 보통 하루 단위라 부담 적음
            for _fp in amb_index:
                if not self.is_running:
                    break
                for (_fp2, rid, g, sec, t, p, i) in _reread_amb(_fp):
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
                    i_am_dc = self._correct_intensity(I)
                    i0_s = np.where(i0_interp > 0, i0_interp, 1e-9).astype(float)
                    i_am_s = np.where(i_am_dc > 0, i_am_dc, 1e-9).astype(float)
                    alpha_ref    = _alpha_za(t_i0, p_i0)
                    alpha_sample = _alpha_za(t_am, p_am)
                    # RL은 괄호 전체를 곱한다(omr=RL·(1-R)/d → omr + RL·alpha_ref = RL·[(1-R)/d+α_ZA]).
                    alpha = ((_omr_d_at(gmean, float((st[b, 0] + st[b, 1]) / 2.0)) + self.rl_factor * alpha_ref)
                             * ((i0_s - i_am_s) / i_am_s) - (alpha_sample - alpha_ref))
                    n_written += 1
                else:
                    alpha = np.full(len(wave_nm), np.nan)   # 빈 bin
                fn = os.path.join(folder, f"{chp}_{self.drnam_date}_{b+1:06d}.dat")
                np.savetxt(fn, np.asarray(alpha, dtype=float).reshape(-1, 1), fmt='%20.6e')
                if b % 200 == 0:
                    self.progress.emit(b)
            self.status_msg.emit(f"Per-bin format: filled {n_written}/{nbin} bins → {folder}")
            _cleanup_spool()
            self.finished.emit(folder)
            return

        # ── 스트리밍 Pass 2: 파일 1개씩 재읽기 → alpha 계산 → 즉시 저장 → 메모리 해제 ──
        n_bins_total = 0
        n_saved  = 0
        pix_min  = self.pixel_min
        i0_mode  = "PCHIP" if use_pchip else "static"
        n_za     = len(za_gidx)

        from datetime import datetime as _dt, timedelta as _td
        lbl_tag = f"_{self.channel_label}" if self.channel_label else ""
        base_dir = os.path.join(self.output_dir, self.channel_subdir) if self.channel_subdir else self.output_dir
        os.makedirs(base_dir, exist_ok=True)
        import re as _re_date

        for fp in amb_index:
            if not self.is_running:
                break
            # 이 파일의 ambient를 재읽기 → 60s 평균 → alpha 계산(파일 1개분만 RAM에)
            rows = []
            for (row_idx, gmean, rep_sec, t_am, p_am, i_am, n_avg) in _avg_ambient(_reread_amb(fp)):
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

                i_am_dc = self._correct_intensity(i_am)
                i0_s   = np.where(i0_interp > 0, i0_interp, 1e-9).astype(float)
                i_am_s = np.where(i_am_dc   > 0, i_am_dc,   1e-9).astype(float)

                alpha_ref    = _alpha_za(t_i0, p_i0)
                alpha_sample = _alpha_za(t_am, p_am)

                # RL은 괄호 전체를 곱한다(omr=RL·(1-R)/d → omr + RL·alpha_ref = RL·[(1-R)/d+α_ZA]).
                alpha = ((_omr_d_at(gmean, rep_sec) + self.rl_factor * alpha_ref)
                         * ((i0_s - i_am_s) / i_am_s)
                         - (alpha_sample - alpha_ref))

                rows.append((row_idx, rep_sec, t_am, p_am, alpha, n_avg))
                n_bins_total += 1

            if not rows:
                continue
            stem     = os.path.splitext(os.path.basename(fp))[0]
            # 파일명에서 날짜(YYYY-MM-DD) 추출 → 날짜별 하위폴더에 저장(없으면 base_dir)
            _md = _re_date.search(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})', stem)
            _file_dir = os.path.join(base_dir, f"{_md.group(1)}-{_md.group(2)}-{_md.group(3)}") if _md else base_dir
            os.makedirs(_file_dir, exist_ok=True)
            out_path = os.path.join(_file_dir, f"{stem}{lbl_tag}_alpha_trace.dat")
            _yr = DataIO._file_year(fp) or 2026
            def _doy_iso(sec):
                if not np.isfinite(sec):
                    return float('nan'), ''
                doy = sec / 86400.0 + 1.0
                iso = (_dt(_yr, 1, 1) + _td(seconds=float(sec))).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                return doy, iso
            with open(out_path, 'w', encoding='utf-8') as f:
                from core.provenance import code_version as _codever
                f.write(f"# CAESAR Pro Alpha Export — {os.path.basename(fp)}\n")
                f.write(f"# code={_codever()}\n")
                f.write(f"# channel={self.channel}  label={self.channel_label or 'single'}\n")
                f.write(f"# RL_factor={self.rl_factor}  d={self.cavity_len} cm\n")
                f.write(f"# I0_mode={i0_mode}  ZA_count={n_za}\n")
                f.write(f"# ambient_avg_sec={self.avg_sec:.0f}  (alpha after {self.avg_sec:.0f}s time-average of ambient)\n")
                dark_note = f"mean={dark.mean():.1f}×{self.dark_scale_factor:g}" if has_dark else "None"
                f.write(f"# dark_correction={dark_note}\n")
                f.write(f"# offset_correction={'applied×%g' % self.offset_scale_factor if self.offset is not None else 'None'}"
                        f"  stray_light_eps={self.stray_light_fraction:g}\n")
                f.write(f"# Calibration: {rt_calib_note or calib_info_per_file.get(fp, 'unknown')}\n")
                wv_str = '\t'.join(f"{w:.4f}" for w in wave_nm)
                f.write(f"# wavelength_nm:\t{wv_str}\n")
                f.write("# time = bytepack(col0,col1)/100 (matches reference doy, no timezone conversion)\n")
                f.write("row_idx\tdoy\tdatetime\tT_C\tP_mbar\t" +
                        '\t'.join(f"px{pix_min+j}" for j in range(n_pix)) + "\n")
                for rid, rep_sec, T, P, alpha, n_avg in rows:
                    doy, iso = _doy_iso(rep_sec)
                    vals = '\t'.join(f"{v:.6e}" for v in alpha)
                    f.write(f"{rid}\t{doy:.6f}\t{iso}\t{T:.2f}\t{P:.2f}\t{vals}\n")
            n_saved += 1
            # 파일별 진행상황 emit — UI가 주기적으로 숨 쉬어 '응답없음' 완화
            self.progress.emit(global_idx)
            self.status_msg.emit(
                f"[{n_saved}/{len(amb_index)}] saved: {os.path.basename(out_path)}  "
                f"({len(rows)} bin, {i0_mode} I₀)")

        _cleanup_spool()
        self.status_msg.emit(
            f"Done: ambient {amb_count} rows → {n_bins_total} bins → {n_saved} files (streaming, low-memory)")
        self.finished.emit(self.output_dir if n_saved > 0 else "ERROR: no files saved")

