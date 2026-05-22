import os
import time
import numpy as np

# DataIO gatekeeper call
from data_io import DataIO

# Core engine imports
from scipy.linalg import lstsq as scipy_lstsq
from scipy.optimize import least_squares, lsq_linear
from numpy.polynomial import chebyshev

from PyQt6.QtWidgets import *
from PyQt6.QtCore import Qt, QThread, pyqtSignal


# [ Rayleigh Physics Logic for worker.py ]

class RayleighPhysics:
    """
    Calculates Rayleigh scattering extinction coefficients α(λ) [cm⁻¹].

    Clausius-Mossotti 형태 + Sellmeier 분산식을 사용하는 물리 기반 모델.
    σ = Fk × (24π³v⁴/N²) × ((n²-1)/(n²+2))²,  α = σ × N

    Zero-Air: N₂ (79%) + O₂ (21%) 혼합
      N₂ — Peck & Khanna (1966) Sellmeier, King factor: Fk_N2 = 1.034 + 3.17e-12·v
      O₂ — Peck & Reeder (1972) Sellmeier, King factor: Fk_O2 = 1.09 + 1.385e-11·v² + 1.448e-20·v⁴
    Helium: Cuthbertson & Cuthbertson (1936) Sellmeier, Fk = 1 (noble gas)

    Number density: N = N_Loschmidt × (P/P₀) × (T₀/T)  [molecules cm⁻³]
    α(T,P,λ) = σ(λ) × N(T,P)  [cm⁻¹]
    """
    @staticmethod
    def get_alpha_rayleigh(wave_nm, temp_c, press_mbar, gas_type='zero_air'):
        wave_nm = np.asarray(wave_nm, dtype=float)
        # Loschmidt 수 → T, P 보정된 수밀도 [molecules/cm³]
        N = 2.68678e19 * (press_mbar / 1013.25) * (273.15 / (temp_c + 273.15))
        v = 1e7 / wave_nm  # 파수 [cm⁻¹]

        gas = gas_type.lower()
        if gas in ('zero_air', 'air'):
            # N₂ — Peck & Khanna (1966)
            A_n2, B_n2, C_n2 = 5677.465, 318.81874e12, 14.4e9
            n_n2 = 1.0 + (A_n2 + B_n2 / (C_n2 - v**2)) * 1e-8
            Fk_n2 = 1.034 + 3.17e-12 * v
            s_n2 = Fk_n2 * (24 * np.pi**3 * v**4 / N**2) * ((n_n2**2 - 1) / (n_n2**2 + 2))**2

            # O₂ — Peck & Reeder (1972)
            A_o2, B_o2, C_o2 = 20564.8, 2.480899e13, 4.09e9
            n_o2 = 1.0 + (A_o2 + B_o2 / (C_o2 - v**2)) * 1e-8
            Fk_o2 = 1.09 + 1.385e-11 * v**2 + 1.448e-20 * v**4
            s_o2 = Fk_o2 * (24 * np.pi**3 * v**4 / N**2) * ((n_o2**2 - 1) / (n_o2**2 + 2))**2

            sigma = 0.79 * s_n2 + 0.21 * s_o2

        else:  # helium — Cuthbertson & Cuthbertson (1936)
            A_he, B_he, C_he = 2283.0, 1.8102e13, 1.5342e10
            n_he = 1.0 + (A_he + B_he / (C_he - v**2)) * 1e-8
            sigma = (24 * np.pi**3 * v**4 / N**2) * ((n_he**2 - 1) / (n_he**2 + 2))**2

        return sigma * N  # α = σ × N(T,P)  [cm⁻¹]

class KalmanTracker:
    """
    A simple multi-variable Kalman filter for smoothing concentration time series.

    What is a Kalman filter?
    ------------------------
    Think of it as a smart moving average that balances two sources of information:
      1. The previous estimate (state)  — weighted by how much we trust our model (Q)
      2. The new measurement            — weighted by how much we trust the sensor (R)

    The result is a smoothed value that tracks real changes quickly while
    suppressing random measurement noise.

    Parameters
    ----------
    q_noise : Process noise — how fast the TRUE concentration can change per frame.
              Larger Q → filter tracks faster (good for rapid plumes, noisy).
    r_noise : Measurement noise — how much we distrust each individual fit result.
              Larger R → stronger smoothing (good for stable background monitoring).
    """
    def __init__(self, num_variables, q_noise=1e-4, r_noise=1e-2):
        self.num_vars = num_variables
        self.state = np.zeros(num_variables)
        self.P = np.eye(num_variables)
        self.Q = np.eye(num_variables) * q_noise
        self.R = np.eye(num_variables) * r_noise
        self.is_initialized = False

    def process(self, measurement):
        z = np.array(measurement, dtype=float)

        # On the very first frame, seed the state directly from the measurement
        if not self.is_initialized:
            self.state = z.copy()
            self.is_initialized = True
            return self.state.copy()

        # ── Predict step ─────────────────────────────────────────────────────
        # Propagate the uncertainty forward: P_k|k-1 = P + Q
        # Q says 'the true value might have drifted, so our confidence decreases'
        p_predict = self.P + self.Q

        # ── Update step ──────────────────────────────────────────────────────
        # Kalman gain K balances trust in prediction vs. measurement:
        #   K = P_pred / (P_pred + R)
        # When R is large (noisy sensor), K → 0 and we trust the prediction more.
        # When R is small (precise sensor), K → 1 and we trust the measurement more.
        kalman_gain = p_predict @ np.linalg.inv(p_predict + self.R)

        # Blend old state with new measurement, weighted by Kalman gain
        self.state = self.state + kalman_gain @ (z - self.state)

        # Update covariance: reduced uncertainty after incorporating measurement
        self.P = (np.eye(self.num_vars) - kalman_gain) @ p_predict
        return self.state.copy()


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

    def __init__(self, engine, file_list, pixel_min, pixel_max, p0, bounds, update_interval, delay_ms=0, ref_properties=None, i0_array=None, r_array=None, cavity_len=100.0, temperature=25.0, pressure=1013.25, flag_za=None, flag_he=None, flag_amb=None, dark_array=None, dark_scale_factor=1.0, offset_array=None, offset_scale_factor=1.0, stray_light_fraction=0.0, use_temporal_i0=False, save_alpha=False, alpha_save_dir='', rl_factor=1.0):
        super().__init__()
        self.engine = engine
        self.file_list = file_list
        self.pixel_min = pixel_min
        self.pixel_max = pixel_max
        self.update_interval = update_interval
        self.delay_ms = delay_ms
        self.ref_properties = ref_properties if ref_properties is not None else {}

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

    def auto_pre_calibrate(self, pixel_idx, optical_depth, poly_order):
        best_rms = np.inf
        best_shift = float(np.atleast_1d(self.params[ 0 ])[ 0 ])
        best_squeeze = 1.0
        
        shifts = np.arange(best_shift - 0.5, best_shift + 0.6, 0.5)
        squeezes = np.arange(0.999, 1.002, 0.001)
        
        for sh in shifts:
            for sq in squeezes:
                try:
                    A = self.engine.get_basis_matrix(pixel_idx, sh, sq, poly_order)
                    coeffs, _, _, _ = scipy_lstsq(A, optical_depth, lapack_driver='gelsy')
                    y_fit = A @ coeffs
                    rms = np.sqrt(np.mean((optical_depth - y_fit)**2))
                    if rms < best_rms:
                        best_rms = rms
                        best_shift = sh
                        best_squeeze = sq
                except Exception:
                    pass
        return best_shift, best_squeeze

    # ==========================================
    # 🌟 Helper Functions (Refactored)
    # ==========================================
    
    def _detect_etalon_frequency(self, pixel_idx, optical_depth, poly_order):
        """
        [Helper] Auto-detects the dominant etalon fringe frequency via FFT.

        Etalon fringes are sinusoidal ripples in the spectrum caused by partial
        reflections between optical surfaces (e.g., mirror faces, beam-splitters).
        Their frequency in pixel-space is related to the optical path difference.

        Strategy:
          1. Fit a low-order polynomial to remove the broad baseline.
          2. FFT the residual — etalon fringes appear as a sharp spike.
          3. Return the angular frequency (rad/pixel) of the strongest spike
             within the physically plausible range [etalon_freq_min, etalon_freq_max].
        """
        x_mapped_temp = np.linspace(-1, 1, len(pixel_idx))
        p_coeffs = np.polyfit(x_mapped_temp, optical_depth, poly_order)
        poly_bg = np.polyval(p_coeffs, x_mapped_temp)
        
        rough_residual = optical_depth - poly_bg
        fft_vals = np.fft.rfft(rough_residual)
        fft_freqs = np.fft.rfftfreq(len(rough_residual), d=1.0) 
        
        valid_mask = (fft_freqs > self.etalon_freq_min) & (fft_freqs < self.etalon_freq_max)
        if np.any(valid_mask):
            peak_f = fft_freqs[valid_mask][np.argmax(np.abs(fft_vals[valid_mask]))]
            return 2.0 * np.pi * peak_f
        return 0.50

    def _setup_fit_parameters(self, initial_shift_center, current_params):
        """
        [Helper] Builds the non-linear parameter lists for least_squares().

        Each gas has two non-linear parameters: Shift and Squeeze.
        The user can configure each as one of four modes:

          Free   → fully unconstrained (−∞ … +∞)
          Limit  → constrained to a user-defined range, further clipped to a
                   rolling window of ±step_limit around the previous shift
          Fix    → held constant at a fixed value (removed from optimization)
          Link   → forced to equal the shift/squeeze of another gas

        Returns:
          active_vars  — names of the parameters that the optimizer will tune
          fixed_vars   — {name: value} for parameters held constant
          linked_vars  — {name: target_name} for parameters locked to another
          theta0       — initial guess vector for active_vars
          theta_lb/ub  — lower/upper bound vectors for active_vars
        """
        active_vars, fixed_vars, linked_vars = [], {}, {}
        theta0, theta_lb, theta_ub = [], [], []
        
        for gas in self.engine.gas_list:
            props = self.ref_properties.get(gas, {"sh_mode": "Limit", "sh_val": "-0.5, 0.5", "sq_mode": "Fix", "sq_val": "1.0"})
            
            # Shift setup
            sh_name = f"{gas}_sh"
            if props["sh_mode"] == "Limit":
                active_vars.append(sh_name)
                try: global_lb, global_ub = map(float, props["sh_val"].split(','))
                except Exception: global_lb, global_ub = -3.0, 3.0
                step_limit = getattr(self, 'step_limit', 0.5)
                window_lb, window_ub = initial_shift_center - step_limit, initial_shift_center + step_limit
                sh_lb, sh_ub = max(global_lb, window_lb), min(global_ub, window_ub)
                theta_lb.append(sh_lb); theta_ub.append(sh_ub)
                theta0.append(max(sh_lb + 1e-5, min(sh_ub - 1e-5, current_params[ 0 ])))
            elif props["sh_mode"] == "Free":
                active_vars.append(sh_name)
                theta_lb.append(-np.inf); theta_ub.append(np.inf); theta0.append(initial_shift_center)
            elif props["sh_mode"] == "Fix":
                try: val = float(props["sh_val"])
                except: val = 0.0
                fixed_vars[sh_name] = initial_shift_center + val if abs(val) < 100 else val
            elif props["sh_mode"] == "Link":
                linked_vars[sh_name] = f"{props['sh_val'].strip()}_sh"
                
            # Squeeze setup
            sq_name = f"{gas}_sq"
            if props["sq_mode"] == "Limit":
                active_vars.append(sq_name)
                try: v_min, v_max = map(float, props["sq_val"].split(','))
                except: v_min, v_max = -0.01, 0.01
                sq_lb = 1.0 + v_min if abs(v_min) < 0.5 else v_min
                sq_ub = 1.0 + v_max if abs(v_max) < 0.5 else v_max
                theta_lb.append(sq_lb); theta_ub.append(sq_ub)
                theta0.append(max(sq_lb + 1e-5, min(sq_ub - 1e-5, 1.0)))
            elif props["sq_mode"] == "Free":
                active_vars.append(sq_name)
                theta_lb.append(0.1); theta_ub.append(10.0); theta0.append(1.0)
            elif props["sq_mode"] == "Fix":
                try: val = float(props["sq_val"])
                except: val = 1.0
                fixed_vars[sq_name] = 1.0 + val if abs(val) < 0.5 else val
            elif props["sq_mode"] == "Link":
                linked_vars[sq_name] = f"{props['sq_val'].strip()}_sq"

        return active_vars, fixed_vars, linked_vars, theta0, theta_lb, theta_ub

    def _execute_varpro_fit(self, pixel_idx, optical_depth, W_initial, active_vars, fixed_vars, linked_vars, theta0, theta_lb, theta_ub, poly_order, fixed_e_f, absolute_center, fit_sign, override_lam=None, override_robust=None):
        """
        [CAESAR Pro Final Form] VarPro + NNLS + Tikhonov + Robust (IRLS) engine.

        Algorithm overview (Variable Projection = VarPro)
        --------------------------------------------------
        The spectral model is:  y = A(θ) · c + noise
          - θ = non-linear params (Shift, Squeeze, Etalon phase) — few unknowns
          - c = linear params   (gas concentrations, poly coeffs, etalon amplitude)

        VarPro separates the problem:
          1. Non-linear loop  (least_squares): for each candidate θ, the optimal c
             is found analytically by NNLS (ensuring concentrations ≥ 0), so the
             optimizer only sees a residual, not the full c vector.
          2. Linear solve (lsq_linear): once θ is fixed, derive the final c.

        Extra regularizations
        ---------------------
        Tikhonov (Ridge): adds λ·‖c‖² to the cost → penalizes large coefficients,
            stabilizes fits when references are correlated (e.g., H2O and O4).
        IRLS (Iterative Reweighted Least Squares): down-weights pixels with large
            residuals (outliers, cosmic rays) so they don't distort the fit.
            Uses a Tukey bisquare weight function with k = 4.685σ.
        NNLS: gas concentrations are constrained to be ≥ 0 (physically required).
        """
        # Fix 1: Explicitly index 0 of pixel_idx
        x_min, x_max = pixel_idx[ 0 ], pixel_idx[ -1 ]
        x_mapped = (2.0 * (pixel_idx - x_min) / (x_max - x_min)) - 1.0
        T = chebyshev.chebvander(x_mapped, poly_order) if poly_order >= 0 else np.zeros((len(pixel_idx), 0))

        lam = override_lam if override_lam is not None else getattr(self, 'tikhonov_lambda', 0.0)
        use_robust = override_robust if override_robust is not None else getattr(self, 'use_robust_fitting', False)

        # Pre-compute temperature correction factors per gas.
        # σ_eff(T) = σ_ref(T_ref) × (1 + t_coeff × (T_meas - T_ref) / 100)
        # t_coeff in %/°C; T_meas (self.temperature) and T_ref both in °C.
        t_corr = {}
        for name in self.engine.gas_list:
            props = self.ref_properties.get(name, {})
            t_ref   = float(props.get("t_ref",   25.0))
            t_coeff = float(props.get("t_coeff",  0.0))
            t_corr[name] = 1.0 + t_coeff * (self.temperature - t_ref) / 100.0

        W_current = W_initial.copy()
        max_iters = 10 if use_robust else 1  # Up to 10 IRLS iterations; break early on convergence
        prev_weights = np.diag(W_current).copy()
        num_gases = len(self.engine.gas_list)

        for iteration in range(max_iters):
            def objective_varpro(theta):
                val_dict = {v: theta[ i ] for i, v in enumerate(active_vars)}
                val_dict.update(fixed_vars)
                for v, t in linked_vars.items(): val_dict[ v ] = val_dict.get(t, 0.0)
                
                e_p = theta[ -1 ]           
                cols = []
                for name in self.engine.gas_list:
                    sh_i, sq_i = val_dict[ f"{name}_sh" ], val_dict[ f"{name}_sq" ]
                    pixel_shifted = (pixel_idx - absolute_center) * sq_i + absolute_center + sh_i
                    raw_ref = fit_sign * self.engine.interpolators[ name ](pixel_shifted) / self.engine.scaling_factors[ name ]
                    raw_ref = raw_ref * t_corr[name]
                    cols.append(raw_ref)

                for j in range(poly_order + 1): cols.append(T[ :, j ])
                cols.append(np.sin(fixed_e_f * pixel_idx + e_p))
                
                A_weighted = W_current @ np.column_stack(cols)
                y_weighted = W_current @ optical_depth
                
                # Fix 2: Explicitly index 1 of shape (column count)
                num_cols = A_weighted.shape[ 1 ]
                
                if lam > 0:
                    A_aug = np.vstack((A_weighted, np.eye(num_cols) * lam))
                    y_aug = np.concatenate((y_weighted, np.zeros(num_cols)))
                else:
                    A_aug, y_aug = A_weighted, y_weighted

                # Force gas concentrations to be non-negative (NNLS constraint)
                lb_inner = [ 0.0 ] * num_gases + [ -np.inf ] * (num_cols - num_gases)
                ub_inner = [ np.inf ] * num_cols
                
                res_temp = lsq_linear(A_aug, y_aug, bounds=(lb_inner, ub_inner))
                return y_aug - A_aug @ res_temp.x

            # 1. Nonlinear optimization (Shift, Squeeze)
            res_nonlin = least_squares(objective_varpro, x0=theta0, bounds=(theta_lb, theta_ub), max_nfev=1500)
            theta_opt = res_nonlin.x
            
            # 2. Linear optimization (derive final results)
            val_dict_opt = {v: theta_opt[ i ] for i, v in enumerate(active_vars)}
            val_dict_opt.update(fixed_vars)
            for v, t in linked_vars.items(): val_dict_opt[ v ] = val_dict_opt.get(t, 0.0)
            
            opt_shifts = [ val_dict_opt[ f"{g}_sh" ] for g in self.engine.gas_list ]
            opt_squeezes = [ val_dict_opt[ f"{g}_sq" ] for g in self.engine.gas_list ]
            best_ep = theta_opt[ -1 ]
            
            cols = []
            for i, name in enumerate(self.engine.gas_list):
                pixel_shifted = (pixel_idx - absolute_center) * opt_squeezes[ i ] + absolute_center + opt_shifts[ i ]
                raw_ref = fit_sign * self.engine.interpolators[ name ](pixel_shifted) / self.engine.scaling_factors[ name ]
                cols.append(raw_ref * t_corr[name])
            for j in range(poly_order + 1): cols.append(T[ :, j ])
            cols.append(np.sin(fixed_e_f * pixel_idx + best_ep))
            
            A_final = np.column_stack(cols)
            A_f_w = W_current @ A_final
            y_w = W_current @ optical_depth
            
            # Fix 3: Explicitly index 1 of shape (column count)
            num_cols_final = A_f_w.shape[ 1 ]

            if lam > 0:
                A_aug = np.vstack((A_f_w, np.eye(num_cols_final) * lam))
                y_aug = np.concatenate((y_w, np.zeros(num_cols_final)))
            else:
                A_aug, y_aug = A_f_w, y_w

            lb_final = [ 0.0 ] * num_gases + [ -np.inf ] * (num_cols_final - num_gases)
            res_lin_final = lsq_linear(A_aug, y_aug, bounds=(lb_final, [ np.inf ] * num_cols_final))
            c_opt = res_lin_final.x

            # ── IRLS weight update ──────────────────────────────────────────────
            # Compute per-pixel residuals; large outliers get a lower weight next iter.
            # Tukey bisquare: w = (1-(r/k)²)² if |r| < k, else 0
            # MAD = Median Absolute Deviation ≈ robust estimate of σ
            if use_robust and iteration < max_iters - 1:
                residuals = np.abs(optical_depth - A_final @ c_opt)
                raw_mad = np.median(residuals)
                mad = raw_mad if raw_mad > 0 else np.mean(residuals)
                # MAD is a biased estimator of σ for Gaussian data: σ̂ = MAD / 0.6745
                sigma_hat = mad / 0.6745
                k = 4.685 * (sigma_hat + 1e-9)
                new_weights = np.where(residuals < k, (1 - (residuals/k)**2)**2, 0.0) * np.diag(W_initial)
                if iteration > 0 and np.max(np.abs(new_weights - prev_weights)) < 1e-6:
                    break
                prev_weights = new_weights.copy()
                W_current = np.diag(new_weights)
            else:
                break

        # Final return processing
        resid_w = y_w - A_f_w @ c_opt
        mse = np.mean(resid_w**2)
        try:
            lam = getattr(self, 'tikhonov_lambda', 0.0)
            AtWA = A_f_w.T @ A_f_w
            n_cols = AtWA.shape[0]
            M = AtWA + lam * np.eye(n_cols)
            M_inv = np.linalg.pinv(M)
            if lam > 1e-9:
                # Sandwich estimator: (M⁻¹ AtWA M⁻¹) σ²
                # Corrects for the bias introduced by Tikhonov regularization
                cov = M_inv @ AtWA @ M_inv * mse
            else:
                cov = M_inv * mse
            perr_lin = np.sqrt(np.maximum(np.diag(cov), 0.0))
        except Exception:
            perr_lin = np.zeros_like(c_opt)
            
        return opt_shifts, opt_squeezes, c_opt[ 0 : num_gases ], c_opt[ num_gases : -1 ], c_opt[ -1 ], best_ep, perr_lin[ 0 : num_gases ]
    
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
                _, raw, flag, _, _ = DataIO.load_measurement_with_hk(fp, self.pixel_min, self.pixel_max, row_index=row_idx)
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
            result = {'File': f"{os.path.basename(file_path)} [{row_idx:04d}]", 'Params': {}}
            # Try to read the measurement timestamp from column 0 of the Araon row.
            # Falls back to file mtime → KST if column 0 is not a recognisable timestamp.
            _ts = DataIO.parse_row_timestamp(file_path, row_index=row_idx)
            result['Time'] = _ts.strftime('%Y-%m-%d %H:%M:%S') if _ts else f"row {row_idx:04d}"

            try:
                # 1. Load Spectrum and Housekeeping (including Flag)
                pixel_idx, intensity_raw, state_flag, env_t, env_p = DataIO.load_measurement_with_hk(file_path, self.pixel_min, self.pixel_max, row_index=row_idx)
                
                # Update current environment for PPB calculation
                self.temperature = env_t
                self.pressure = env_p

                # Convert pixels to wavelength (nm) for Rayleigh calculation.
                # Guard: if _wave_axis is None, pixel_to_wavelength returns pixel indices
                # (~1453) which would be fed to Rayleigh(λ⁻⁴) as 1453 nm instead of ~455 nm,
                # giving ~100× too-small Rayleigh coefficients and corrupted optical depths.
                if self.engine._wave_axis is None:
                    print("⚠️  WARNING: No wavelength calibration loaded in engine. "
                          "pixel_to_wavelength() returns pixel indices as nm — "
                          "Rayleigh calculation will be incorrect. Load a wavelength cal file first.")
                wave_nm = self.engine.pixel_to_wavelength(pixel_idx)

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
                            optical_depth = (self.rl_factor * (self.one_minus_r_over_d + alpha_ref) * ((I_0 - I_meas) / I_meas)
                                            - (alpha_ray_sample - alpha_ref))
                            fit_sign = 1.0
                            # [DEBUG] 처음 ambient 스캔에서만 파일에 저장
                            if not getattr(self, '_debug_alpha_printed', False):
                                self._debug_alpha_printed = True
                                _dbg_path = os.path.join(os.path.dirname(__file__), 'debug_fit.txt')
                                with open(_dbg_path, 'w', encoding='utf-8') as _dbf:
                                    _dbf.write(f"[DEBUG-ALPHA] row={row_idx}  omr_d_mean={np.mean(self.one_minus_r_over_d):.4e}  "
                                               f"I0_mean={np.mean(I_0):.1f}  Imeas_mean={np.mean(I_meas):.1f}  "
                                               f"ratio=(I0-Im)/Im_mean={np.mean((I_0-I_meas)/I_meas):.6f}  "
                                               f"OD_mean={np.mean(optical_depth):.4e}  OD_std={np.std(optical_depth):.4e}\n")
                                    _dbf.write(f"[DEBUG-ALPHA] scale_factor={scale_factor}\n")
                                    _dbf.write(f"[DEBUG-ALPHA] engine refs: {[(n, self.engine.scaling_factors[n]) for n in self.engine.gas_list]}\n")

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
                            'etalon_phase': float(best_ep), 'etalon_freq': float(fixed_e_f)
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

                        # [DEBUG] 처음 ambient 스캔에서만 파일에 저장
                        if not getattr(self, '_debug_fit_printed', False):
                            self._debug_fit_printed = True
                            _dbg_path = os.path.join(os.path.dirname(__file__), 'debug_fit.txt')
                            with open(_dbg_path, 'a', encoding='utf-8') as _dbf:
                                _dbf.write(f"[DEBUG-FIT] gas_coeffs_scaled={gas_coeffs_scaled.tolist()}\n")
                                _dbf.write(f"[DEBUG-FIT] scaling_factors={[(n, self.engine.scaling_factors[n]) for n in self.engine.gas_list]}\n")
                                _dbf.write(f"[DEBUG-FIT] scale_factor={scale_factor}  n_air={n_air:.4e}\n")
                                for gi2, nm2 in enumerate(self.engine.gas_list):
                                    _dbf.write(f"[DEBUG-FIT] {nm2}: coeff={gas_coeffs_scaled[gi2]:.4e}  "
                                               f"scale_div={self.engine.scaling_factors[nm2]:.4e}  "
                                               f"real_conc={raw_concentrations[gi2]:.4e} cm-3  "
                                               f"ppb={result[nm2]:.4f}\n")

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

                        # [Bug Fix 2]: If fitting succeeds, register this Shift as the center for the next file (last_valid_shift)!
                        # Completely removed the < 0.5 condition to free the Step Limit constraint.
                        if status in ["OK", "Recovered"] and len(opt_shifts) > 0:
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
                    self.plot_update.emit(pixel_idx, diff_data, diff_fit, np.zeros_like(pixel_idx), final_params_dict, os.path.basename(file_path))
                    sh_val, sq_val = opt_shifts[ 0 ] if len(opt_shifts) > 0 else 0, opt_squeezes[ 0 ] if len(opt_squeezes) > 0 else 1
                    self.trend_update.emit({'idx': i, 'shift': sh_val, 'squeeze': sq_val, 'rms': rms})
                    
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
                 dark_spectrum=None):   # 1-D float array (full 2048 px), or None
        super().__init__()
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
                    fp, self.pixel_min, self.pixel_max, row_index=row_idx)
            except Exception as e:
                self.status_msg.emit(f"SKIP {os.path.basename(fp)}[{row_idx}]: {e}")
                continue

            is_za  = state_flag in self.flag_za
            is_he  = state_flag in self.flag_he
            is_amb = (state_flag == 0 or
                      (self.flag_amb and state_flag in self.flag_amb) or
                      (not self.flag_amb and not is_za and not is_he))

            if is_he:
                if 510 not in self.flag_he or state_flag == 510:
                    # 다크 보정 후 He 스펙트럼 저장 (injecting=510만 사용)
                    i_he_raw = intensity_raw.copy()
                    i_he_last   = (i_he_raw - dark) if has_dark else i_he_raw
                    t_he_last   = env_t
                    p_he_last   = env_p

            elif is_za:
                if 500 not in self.flag_za or state_flag == 500:
                    # 500=injecting만 PCHIP I₀ 및 R-cal에 사용
                    # 501=setflow, 502=wait before, 503=wait after 는 스킵
                    i_za_dc = (intensity_raw - dark) if has_dark else intensity_raw.copy()
                    za_gidx.append(global_idx)
                    za_spectra.append(i_za_dc)
                    za_t_list.append(env_t)
                    za_p_list.append(env_p)
                else:
                    i_za_dc = None

                if i_za_dc is not None and i_he_last is not None:
                    # R-calibration: dark-corrected ZA / dark-corrected He
                    # Sellmeier 기반 물리 모델 + rl_factor 퍼지 보정 적용
                    alpha_ray_za = RayleighPhysics.get_alpha_rayleigh(wave_nm, env_t, env_p, 'zero_air')
                    alpha_ray_he = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_he_last, p_he_last, 'helium')
                    i_he_s = np.where(np.abs(i_he_last) > 1.0, i_he_last, 1.0)
                    ratio  = i_za_dc / i_he_s
                    with np.errstate(divide='ignore', invalid='ignore'):
                        omr_d = self.rl_factor * ((ratio * alpha_ray_za) - alpha_ray_he) / (1.0 - ratio)
                    valid = np.isfinite(omr_d) & (omr_d > 0)
                    if valid.mean() >= 0.90 and np.nanmean(omr_d[valid]) < 1e-5:
                        x = np.arange(n_pix)
                        omr_d_clean = np.interp(x, x[valid], omr_d[valid])
                        calib_candidates.append(omr_d_clean)
                        if fp not in calib_info_per_file:
                            leff  = np.mean(1.0 / omr_d_clean) * 1e-5
                            rmean = 1.0 - np.mean(omr_d_clean) * self.cavity_len
                            calib_info_per_file[fp] = (
                                f"omr_d={np.mean(omr_d_clean):.3e} cm-1  "
                                f"Leff={leff:.2f} km  R={rmean:.6f}")
                            self.status_msg.emit(
                                f"[R-CAL] {os.path.basename(fp)} row{row_idx}: "
                                f"Leff={leff:.2f} km  R={rmean:.6f}")

            elif is_amb:
                amb_buffer.append((fp, row_idx, global_idx, env_t, env_p,
                                   intensity_raw.copy()))   # raw 저장, Pass 2에서 보정
                done_scans += 1
                self.progress.emit(done_scans)

        if not self.is_running:
            self.finished.emit("ERROR: 중단됨")
            return

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

        # ── Pass 2: compute alpha for each ambient row ────────────────────────
        self.status_msg.emit(f"Pass 2: {len(amb_buffer)}개 ambient 행 alpha 계산 중…")

        alpha_buffer = {}   # fp → list of (row_idx, T, P, alpha_array)

        for fp, row_idx, gidx, t_am, p_am, i_am in amb_buffer:
            if not self.is_running:
                break

            if use_pchip:
                g = float(gidx)
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

            # i0_interp: PCHIP I₀ (이미 dark-corrected, Pass 1에서 저장)
            # i_am: raw ambient → Pass 2에서 dark 보정
            i_am_dc = (i_am - dark) if has_dark else i_am
            i0_s   = np.where(i0_interp > 0, i0_interp, 1e-9).astype(float)
            i_am_s = np.where(i_am_dc   > 0, i_am_dc,   1e-9).astype(float)

            alpha_ref    = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_i0, p_i0, 'zero_air')
            alpha_sample = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_am, p_am, 'zero_air')

            alpha = (self.rl_factor * (best_omr_d + alpha_ref)
                     * ((i0_s - i_am_s) / i_am_s)
                     - (alpha_sample - alpha_ref))

            alpha_buffer.setdefault(fp, []).append((row_idx, t_am, p_am, alpha))

        # ── Write one alpha_trace file per source file ─────────────────────────
        n_saved  = 0
        pix_min  = self.pixel_min
        i0_mode  = "PCHIP" if use_pchip else "static"
        n_za     = len(za_gidx)

        for fp, rows in alpha_buffer.items():
            stem     = os.path.splitext(os.path.basename(fp))[0]
            out_path = os.path.join(self.output_dir, f"{stem}_alpha_trace.dat")
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(f"# CAESAR Pro Alpha Export — {os.path.basename(fp)}\n")
                f.write(f"# RL_factor={self.rl_factor}  d={self.cavity_len} cm\n")
                f.write(f"# I0_mode={i0_mode}  ZA_count={n_za}\n")
                dark_note = f"mean={dark.mean():.1f}" if has_dark else "None"
                f.write(f"# dark_correction={dark_note}\n")
                f.write(f"# Calibration: {calib_info_per_file.get(fp, 'unknown')}\n")
                wv_str = '\t'.join(f"{w:.4f}" for w in wave_nm)
                f.write(f"# wavelength_nm:\t{wv_str}\n")
                f.write("row_idx\tT_C\tP_mbar\t" +
                        '\t'.join(f"px{pix_min+j}" for j in range(n_pix)) + "\n")
                for rid, T, P, alpha in rows:
                    vals = '\t'.join(f"{v:.6e}" for v in alpha)
                    f.write(f"{rid}\t{T:.2f}\t{P:.2f}\t{vals}\n")
            n_saved += 1
            self.status_msg.emit(f"저장: {out_path}  ({len(rows)} ambient 스캔, {i0_mode} I₀)")

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

    def __init__(self, alpha_files, engine, poly_deg, output_dir, pixel_min=0):
        """
        alpha_files : list of str — alpha_trace.dat 경로 목록
        engine      : UniversalEngine 인스턴스 (레퍼런스 & 파장 포함)
        poly_deg    : int — Chebyshev 다항식 차수 (baseline)
        output_dir  : str — 결과 저장 디렉터리
        pixel_min   : int — 피팅 윈도우 시작 픽셀 (레퍼런스 슬라이싱에 사용)
        """
        super().__init__()
        self.alpha_files = alpha_files
        self.engine      = engine
        self.poly_deg    = poly_deg
        self.output_dir  = output_dir
        self.pixel_min   = pixel_min
        self.is_running  = True

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
        if engine._wave_axis is None:
            self.finished.emit("ERROR: 엔진에 파장 보정(X-축)이 로드되지 않았습니다. "
                               "먼저 Load X-Axis (nm)를 실행하세요.")
            return
        wave_nm  = np.asarray(engine._wave_axis, dtype=float)
        n_pix    = len(wave_nm)
        gas_list = engine.gas_list
        n_gas    = len(gas_list)

        # ── Chebyshev 기저 (baseline polynomial) ─────────────────────────────
        x_norm   = 2.0 * (np.arange(n_pix) / max(n_pix - 1, 1)) - 1.0
        poly_basis = np.column_stack([
            np.polynomial.chebyshev.chebval(x_norm, np.eye(self.poly_deg + 1)[k])
            for k in range(self.poly_deg + 1)
        ])                                          # (n_pix, poly_deg+1)

        # ── 레퍼런스 행렬 구성 ────────────────────────────────────────────────
        ref_cols = []
        for name in gas_list:
            ref_raw = np.asarray(engine.raw_references[name], dtype=float)
            scale   = engine.scaling_factors[name]
            if len(ref_raw) > n_pix:
                # 전체 스펙트럼(2048 px)이면 self.pixel_min 기준으로 fit window 자름
                ref_raw = ref_raw[self.pixel_min: self.pixel_min + n_pix]
            ref_cols.append(ref_raw / scale)

        A_ref = np.column_stack(ref_cols)           # (n_pix, n_gas)
        A     = np.column_stack([A_ref, poly_basis]) # (n_pix, n_gas + poly_deg+1)

        # 전체 행 수 추정 (progress bar용)
        total_est = sum(
            max(0, sum(1 for l in open(f, encoding='utf-8')
                       if l.strip() and not l.startswith('#') and not l.startswith('row_idx')))
            for f in self.alpha_files
        )
        self.total_ready.emit(max(total_est, 1))

        done = 0

        for fpath in self.alpha_files:
            if not self.is_running:
                break

            fname = os.path.basename(fpath)
            stem  = fname.replace('_alpha_trace.dat', '')
            out_path = os.path.join(self.output_dir, f"{stem}_fit.tsv")

            # ── alpha_trace.dat 파싱 ─────────────────────────────────────────
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except Exception as e:
                self.status_msg.emit(f"SKIP {fname}: {e}")
                continue

            data_lines = [l for l in lines
                          if l.strip() and not l.startswith('#')
                          and not l.startswith('row_idx')]

            if not data_lines:
                self.status_msg.emit(f"SKIP {fname}: 데이터 없음")
                continue

            result_rows = []

            for line in data_lines:
                if not self.is_running:
                    break

                parts = line.split('\t')
                if len(parts) < 3 + n_pix:
                    done += 1
                    self.progress.emit(done)
                    continue

                try:
                    row_idx = int(parts[0])
                    T_C     = float(parts[1])
                    P_mbar  = float(parts[2])
                    alpha   = np.array([float(v) for v in parts[3:3 + n_pix]], dtype=float)
                except (ValueError, IndexError):
                    done += 1
                    self.progress.emit(done)
                    continue

                # ── DOAS 피팅 (least-squares) ─────────────────────────────
                coeffs, _, _, _ = scipy_lstsq(A, alpha)
                gas_coeffs = coeffs[:n_gas]

                # ── ppb 변환 ─────────────────────────────────────────────
                n_air = 2.68678e19 * (P_mbar / 1013.25) * (273.15 / (T_C + 273.15))
                ppb_vals = {}
                for gi, name in enumerate(gas_list):
                    scale = engine.scaling_factors[name]
                    mult  = engine.multipliers[name]
                    N_cm3 = gas_coeffs[gi] * mult / scale
                    ppb_vals[name] = (N_cm3 / n_air) * 1e9

                # ── Residual RMS ──────────────────────────────────────────
                fitted = A @ coeffs
                rms = np.sqrt(np.mean((alpha - fitted) ** 2))

                result_rows.append((row_idx, T_C, P_mbar, ppb_vals, rms))

                done += 1
                self.progress.emit(done)

            # ── 결과 저장 ─────────────────────────────────────────────────
            if not result_rows:
                self.status_msg.emit(f"SKIP {fname}: 피팅 결과 없음")
                continue

            header = 'row_idx\tT_C\tP_mbar\t' + '\t'.join(gas_list) + '\trms_cm-1\n'
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(header)
                for row_idx, T, P, ppb_vals, rms in result_rows:
                    vals = '\t'.join(f"{ppb_vals.get(g, 0):.4f}" for g in gas_list)
                    f.write(f"{row_idx}\t{T:.2f}\t{P:.2f}\t{vals}\t{rms:.4e}\n")

            n_rows = len(result_rows)
            self.status_msg.emit(f"저장: {out_path}  ({n_rows}행, {n_gas}가스)")

        self.finished.emit(self.output_dir)