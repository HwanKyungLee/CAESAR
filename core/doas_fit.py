"""core/doas_fit.py — 공유 VarPro DOAS 피터(DoasFitter)
====================================================

CAESAR의 비선형 DOAS 핏(Variable Projection + NNLS + Tikhonov + IRLS)을
worker.AnalysisWorker에서 **그대로 추출**한 단일 구현.

- AnalysisWorker는 기존 메서드명을 유지하되 이 클래스로 위임한다(동작 보존,
  raw 경로 회귀 바이트동일 게이트로 검증).
- AlphaFitWorker(배치 alpha)는 이 클래스를 직접 사용해 동일한 VarPro로 피팅한다
  → raw↔alpha 일치.

설계 원칙
---------
* DoasFitter는 engine만 보유하고 **나머지는 호출마다 인자로 받는다**(상태 없음).
  Kalman/etalon-한번검출/사전캘리브 캐리오버 등 스캔간 상태는 워커가 소유.
* interpolators는 **픽셀-인덱스**(engine.add_reference가 interp1d(arange,…)로 생성).
  따라서 항상 픽셀 공간에서 평가한다.
"""
import numpy as np
from scipy.linalg import lstsq as scipy_lstsq
from scipy.optimize import least_squares, lsq_linear
from numpy.polynomial import chebyshev


class DoasFitter:
    def __init__(self, engine):
        self.engine = engine

    # ──────────────────────────────────────────────────────────────────
    def gas_active_in_window(self, ref_properties, gas_name, pixel_idx):
        """현재 핏 윈도우에서 gas_name을 포함할지. 'active_bands_nm'이 비면 항상 활성."""
        props = ref_properties.get(gas_name, {})
        bands_str = props.get("active_bands_nm", "").strip()
        if not bands_str:
            return True

        wave_nm = self.engine.pixel_to_wavelength(pixel_idx)
        win_lo, win_hi = float(wave_nm.min()), float(wave_nm.max())

        for seg in bands_str.split("|"):
            parts = seg.strip().split(",")
            if len(parts) == 2:
                try:
                    b_lo, b_hi = float(parts[0]), float(parts[1])
                    if win_hi >= b_lo and win_lo <= b_hi:
                        return True
                except ValueError:
                    pass
        return False

    # ──────────────────────────────────────────────────────────────────
    def pre_calibrate(self, pixel_idx, optical_depth, poly_order, init_shift):
        """격자탐색으로 초기 shift/squeeze 추정. init_shift = 기존 self.params[0]."""
        best_rms = np.inf
        best_shift = float(init_shift)
        best_squeeze = 1.0

        shifts = np.arange(best_shift - 0.5, best_shift + 0.51, 0.1)
        squeezes = np.arange(0.999, 1.002, 0.001)

        for sh in shifts:
            for sq in squeezes:
                try:
                    A = self.engine.get_basis_matrix(pixel_idx, sh, sq, poly_order)
                    coeffs, _, _, _ = scipy_lstsq(A, optical_depth, lapack_driver='gelsy')
                    y_fit = A @ coeffs
                    rms = np.sqrt(np.mean((optical_depth - y_fit) ** 2))
                    if rms < best_rms:
                        best_rms = rms
                        best_shift = sh
                        best_squeeze = sq
                except Exception:
                    pass
        return best_shift, best_squeeze

    # ──────────────────────────────────────────────────────────────────
    def detect_etalon_frequency(self, pixel_idx, optical_depth, poly_order,
                                freq_min, freq_max):
        """FFT로 지배적 etalon fringe 각주파수(rad/pixel) 검출."""
        x_mapped_temp = np.linspace(-1, 1, len(pixel_idx))
        p_coeffs = np.polyfit(x_mapped_temp, optical_depth, poly_order)
        poly_bg = np.polyval(p_coeffs, x_mapped_temp)

        rough_residual = optical_depth - poly_bg
        fft_vals = np.fft.rfft(rough_residual)
        fft_freqs = np.fft.rfftfreq(len(rough_residual), d=1.0)

        valid_mask = (fft_freqs > freq_min) & (fft_freqs < freq_max)
        if np.any(valid_mask):
            peak_f = fft_freqs[valid_mask][np.argmax(np.abs(fft_vals[valid_mask]))]
            return 2.0 * np.pi * peak_f
        return 0.50

    # ──────────────────────────────────────────────────────────────────
    def setup_fit_parameters(self, ref_properties, initial_shift_center,
                             current_params, step_limit):
        """least_squares용 비선형 파라미터 리스트(shift/squeeze 모드별) 구성."""
        active_vars, fixed_vars, linked_vars = [], {}, {}
        theta0, theta_lb, theta_ub = [], [], []

        for gas in self.engine.gas_list:
            props = ref_properties.get(gas, {"sh_mode": "Limit", "sh_val": "-0.5, 0.5",
                                             "sq_mode": "Fix", "sq_val": "1.0"})

            sh_name = f"{gas}_sh"
            if props["sh_mode"] == "Limit":
                active_vars.append(sh_name)
                try:
                    global_lb, global_ub = map(float, props["sh_val"].split(','))
                except Exception:
                    global_lb, global_ub = -3.0, 3.0
                window_lb, window_ub = initial_shift_center - step_limit, initial_shift_center + step_limit
                sh_lb, sh_ub = max(global_lb, window_lb), min(global_ub, window_ub)
                theta_lb.append(sh_lb); theta_ub.append(sh_ub)
                theta0.append(max(sh_lb + 1e-5, min(sh_ub - 1e-5, current_params[0])))
            elif props["sh_mode"] == "Free":
                active_vars.append(sh_name)
                theta_lb.append(-np.inf); theta_ub.append(np.inf); theta0.append(initial_shift_center)
            elif props["sh_mode"] == "Fix":
                try:
                    val = float(props["sh_val"])
                except Exception:
                    val = 0.0
                fixed_vars[sh_name] = initial_shift_center + val if abs(val) < 100 else val
            elif props["sh_mode"] == "Link":
                linked_vars[sh_name] = f"{props['sh_val'].strip()}_sh"

            sq_name = f"{gas}_sq"
            if props["sq_mode"] == "Limit":
                active_vars.append(sq_name)
                try:
                    v_min, v_max = map(float, props["sq_val"].split(','))
                except Exception:
                    v_min, v_max = -0.01, 0.01
                sq_lb = 1.0 + v_min if abs(v_min) < 0.5 else v_min
                sq_ub = 1.0 + v_max if abs(v_max) < 0.5 else v_max
                theta_lb.append(sq_lb); theta_ub.append(sq_ub)
                theta0.append(max(sq_lb + 1e-5, min(sq_ub - 1e-5, 1.0)))
            elif props["sq_mode"] == "Free":
                active_vars.append(sq_name)
                theta_lb.append(0.1); theta_ub.append(10.0); theta0.append(1.0)
            elif props["sq_mode"] == "Fix":
                try:
                    val = float(props["sq_val"])
                except Exception:
                    val = 1.0
                fixed_vars[sq_name] = 1.0 + val if abs(val) < 0.5 else val
            elif props["sq_mode"] == "Link":
                linked_vars[sq_name] = f"{props['sq_val'].strip()}_sq"

        return active_vars, fixed_vars, linked_vars, theta0, theta_lb, theta_ub

    # ──────────────────────────────────────────────────────────────────
    def execute_varpro_fit(self, pixel_idx, optical_depth, W_initial,
                           active_vars, fixed_vars, linked_vars,
                           theta0, theta_lb, theta_ub, poly_order, fixed_e_f,
                           absolute_center, fit_sign, ref_properties, temperature,
                           tikhonov_lambda, use_robust,
                           override_lam=None, override_robust=None, allow_negative_gas=False):
        """VarPro + NNLS + Tikhonov + Robust(IRLS) 엔진. AnalysisWorker에서 verbatim 이식.
        allow_negative_gas=True면 가스 계수 하한을 0→−∞로 풀어 음수 농도 허용(0근처 비편향)."""
        gas_lb = -np.inf if allow_negative_gas else 0.0
        x_min, x_max = pixel_idx[0], pixel_idx[-1]
        x_mapped = (2.0 * (pixel_idx - x_min) / (x_max - x_min)) - 1.0
        T = chebyshev.chebvander(x_mapped, poly_order) if poly_order >= 0 else np.zeros((len(pixel_idx), 0))

        lam = override_lam if override_lam is not None else tikhonov_lambda
        use_robust = override_robust if override_robust is not None else use_robust

        # 가스별 온도보정: σ_eff(T) = σ_ref × (1 + t_coeff·(T-T_ref)/100)
        t_corr = {}
        for name in self.engine.gas_list:
            props = ref_properties.get(name, {})
            t_ref = float(props.get("t_ref", 25.0))
            t_coeff = float(props.get("t_coeff", 0.0))
            t_corr[name] = 1.0 + t_coeff * (temperature - t_ref) / 100.0

        gas_active = {
            name: self.gas_active_in_window(ref_properties, name, pixel_idx)
            for name in self.engine.gas_list
        }

        W_current = W_initial.copy()
        max_iters = 10 if use_robust else 1
        prev_weights = np.diag(W_current).copy()
        num_gases = len(self.engine.gas_list)

        for iteration in range(max_iters):
            def objective_varpro(theta):
                val_dict = {v: theta[i] for i, v in enumerate(active_vars)}
                val_dict.update(fixed_vars)
                for v, t in linked_vars.items():
                    val_dict[v] = val_dict.get(t, 0.0)

                e_p = theta[-1]
                cols = []
                for name in self.engine.gas_list:
                    sh_i, sq_i = val_dict[f"{name}_sh"], val_dict[f"{name}_sq"]
                    pixel_shifted = (pixel_idx - absolute_center) * sq_i + absolute_center + sh_i
                    raw_ref = fit_sign * self.engine.interpolators[name](pixel_shifted) / self.engine.scaling_factors[name]
                    raw_ref = raw_ref * t_corr[name]
                    if not gas_active[name]:
                        raw_ref = np.zeros_like(raw_ref)
                    cols.append(raw_ref)

                for j in range(poly_order + 1):
                    cols.append(T[:, j])
                cols.append(np.sin(fixed_e_f * pixel_idx + e_p))

                A_weighted = W_current @ np.column_stack(cols)
                y_weighted = W_current @ optical_depth

                num_cols = A_weighted.shape[1]

                if lam > 0:
                    A_aug = np.vstack((A_weighted, np.eye(num_cols) * lam))
                    y_aug = np.concatenate((y_weighted, np.zeros(num_cols)))
                else:
                    A_aug, y_aug = A_weighted, y_weighted

                lb_inner = [gas_lb] * num_gases + [-np.inf] * (num_cols - num_gases)
                ub_inner = [np.inf] * num_cols

                res_temp = lsq_linear(A_aug, y_aug, bounds=(lb_inner, ub_inner))
                return y_aug - A_aug @ res_temp.x

            res_nonlin = least_squares(objective_varpro, x0=theta0, bounds=(theta_lb, theta_ub), max_nfev=1500)
            theta_opt = res_nonlin.x

            val_dict_opt = {v: theta_opt[i] for i, v in enumerate(active_vars)}
            val_dict_opt.update(fixed_vars)
            for v, t in linked_vars.items():
                val_dict_opt[v] = val_dict_opt.get(t, 0.0)

            opt_shifts = [val_dict_opt[f"{g}_sh"] for g in self.engine.gas_list]
            opt_squeezes = [val_dict_opt[f"{g}_sq"] for g in self.engine.gas_list]
            best_ep = theta_opt[-1]

            cols = []
            for i, name in enumerate(self.engine.gas_list):
                pixel_shifted = (pixel_idx - absolute_center) * opt_squeezes[i] + absolute_center + opt_shifts[i]
                raw_ref = fit_sign * self.engine.interpolators[name](pixel_shifted) / self.engine.scaling_factors[name]
                col = raw_ref * t_corr[name]
                if not gas_active[name]:
                    col = np.zeros_like(col)
                cols.append(col)
            for j in range(poly_order + 1):
                cols.append(T[:, j])
            cols.append(np.sin(fixed_e_f * pixel_idx + best_ep))

            A_final = np.column_stack(cols)
            A_f_w = W_current @ A_final
            y_w = W_current @ optical_depth

            num_cols_final = A_f_w.shape[1]

            if lam > 0:
                A_aug = np.vstack((A_f_w, np.eye(num_cols_final) * lam))
                y_aug = np.concatenate((y_w, np.zeros(num_cols_final)))
            else:
                A_aug, y_aug = A_f_w, y_w

            lb_final = [gas_lb] * num_gases + [-np.inf] * (num_cols_final - num_gases)
            res_lin_final = lsq_linear(A_aug, y_aug, bounds=(lb_final, [np.inf] * num_cols_final))
            c_opt = res_lin_final.x

            if use_robust and iteration < max_iters - 1:
                residuals = np.abs(optical_depth - A_final @ c_opt)
                raw_mad = np.median(residuals)
                mad = raw_mad if raw_mad > 0 else np.mean(residuals)
                sigma_hat = mad / 0.6745
                k = 4.685 * (sigma_hat + 1e-9)
                new_weights = np.where(residuals < k, (1 - (residuals / k) ** 2) ** 2, 0.0) * np.diag(W_initial)
                if iteration > 0 and np.max(np.abs(new_weights - prev_weights)) < 1e-6:
                    break
                prev_weights = new_weights.copy()
                W_current = np.diag(new_weights)
            else:
                break

        resid_w = y_w - A_f_w @ c_opt
        mse = np.mean(resid_w ** 2)
        try:
            lam = tikhonov_lambda   # 공분산은 override가 아니라 base lambda 사용(원본 동작 보존)
            AtWA = A_f_w.T @ A_f_w
            n_cols = AtWA.shape[0]
            M = AtWA + lam * np.eye(n_cols)
            M_inv = np.linalg.pinv(M)
            if lam > 1e-9:
                cov = M_inv @ AtWA @ M_inv * mse
            else:
                cov = M_inv * mse
            perr_lin = np.sqrt(np.maximum(np.diag(cov), 0.0))
        except Exception:
            perr_lin = np.zeros_like(c_opt)

        c_gas = c_opt[0:num_gases].copy()
        c_perr = perr_lin[0:num_gases].copy()
        for i, name in enumerate(self.engine.gas_list):
            if not gas_active[name]:
                c_gas[i] = 0.0
                c_perr[i] = 0.0

        return opt_shifts, opt_squeezes, c_gas, c_opt[num_gases:-1], c_opt[-1], best_ep, c_perr
