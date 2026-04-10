import sys
import os
import math
import datetime
import time
import numpy as np
import pandas as pd
import pyqtgraph as pg

# DataIO 수문장 호출
from data_io import DataIO 

# 장갑차 엔진 임포트
from scipy.linalg import lstsq as scipy_lstsq
from scipy.optimize import least_squares, lsq_linear
from numpy.polynomial import chebyshev

from PyQt6.QtWidgets import *
from PyQt6.QtCore import Qt, QThread, pyqtSignal

class KalmanTracker:
    def __init__(self, num_variables, q_noise=1e-4, r_noise=1e-2):
        self.num_vars = num_variables
        self.state = np.zeros(num_variables)
        self.P = np.eye(num_variables)
        self.Q = np.eye(num_variables) * q_noise
        self.R = np.eye(num_variables) * r_noise
        self.is_initialized = False

    def process(self, measurement):
        z = np.array(measurement, dtype=float)
        if not self.is_initialized:
            self.state = z.copy()
            self.is_initialized = True
            return self.state.copy()
            
        p_predict = self.P + self.Q
        kalman_gain = p_predict @ np.linalg.inv(p_predict + self.R)
        self.state = self.state + kalman_gain @ (z - self.state)
        self.P = (np.eye(self.num_vars) - kalman_gain) @ p_predict
        return self.state.copy()


class AnalysisWorker(QThread):
    progress = pyqtSignal(int)
    result_ready = pyqtSignal(dict, int) 
    plot_update = pyqtSignal(object, object, object, object, object, str) 
    trend_update = pyqtSignal(int, float, float, float)
    finished = pyqtSignal()
    
    def __init__(self, engine, file_list, pixel_min, pixel_max, initial_params, fit_bounds, update_interval=1, delay_ms=0, ref_properties=None):
        super().__init__()
        self.engine = engine
        self.file_list = file_list
        self.pixel_min = int(pixel_min)
        self.pixel_max = int(pixel_max)
        self.params = initial_params
        self.bounds = fit_bounds
        self.update_interval = update_interval
        self.delay_ms = delay_ms
        self.is_running = True
        self.needs_pre_calibration = True
        self.ref_properties = ref_properties if ref_properties is not None else {}

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
        """[Helper] FFT 기반 에탈론 초기 주파수 자동 감지"""
        x_mapped_temp = np.linspace(-1, 1, len(pixel_idx))
        p_coeffs = np.polyfit(x_mapped_temp, optical_depth, poly_order)
        poly_bg = np.polyval(p_coeffs, x_mapped_temp)
        
        rough_residual = optical_depth - poly_bg
        fft_vals = np.fft.rfft(rough_residual)
        fft_freqs = np.fft.rfftfreq(len(rough_residual), d=1.0) 
        
        valid_mask = (fft_freqs > 0.02) & (fft_freqs < 0.40)
        if np.any(valid_mask):
            peak_f = fft_freqs[valid_mask][np.argmax(np.abs(fft_vals[valid_mask]))]
            return 2.0 * np.pi * peak_f
        return 0.50

    def _setup_fit_parameters(self, initial_shift_center, current_params):
        """[Helper] UI 설정값을 바탕으로 최적화 파라미터 경계(Bounds) 세팅"""
        active_vars, fixed_vars, linked_vars = [], {}, {}
        theta0, theta_lb, theta_ub = [], [], []
        
        for gas in self.engine.gas_list:
            props = self.ref_properties.get(gas, {"sh_mode": "Limit", "sh_val": "-0.5, 0.5", "sq_mode": "Fix", "sq_val": "1.0"})
            
            # Shift 셋업
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
                
            # Squeeze 셋업
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
        """[Helper] 핵심 수학 엔진: 비선형(Shift/Sq) + 선형(가스농도) 분리 피팅 (Tikhonov + IRLS 융합형)"""
        x_min, x_max = pixel_idx[ 0 ], pixel_idx[-1]
        x_mapped = (2.0 * (pixel_idx - x_min) / (x_max - x_min)) - 1.0
        T = chebyshev.chebvander(x_mapped, poly_order) if poly_order >= 0 else np.zeros((len(pixel_idx), 0))

        lam = override_lam if override_lam is not None else getattr(self, 'tikhonov_lambda', 0.0)
        use_robust = override_robust if override_robust is not None else getattr(self, 'use_robust_fitting', False)
        
        # 가중치 행렬 초기화
        W_current = W_initial.copy()

        # IRLS 루프 (로버스트 피팅 사용 시 3회 반복, 미사용 시 1회)
        max_iters = 3 if use_robust else 1
        
        for iteration in range(max_iters):
            def objective_varpro(theta):
                val_dict = {}
                idx = 0
                for v_name in active_vars:
                    val_dict[v_name] = theta[idx]; idx += 1
                val_dict.update(fixed_vars)
                for v_name, target in linked_vars.items():
                    val_dict[v_name] = val_dict.get(target, 0.0)
                
                e_p = theta[-1]           
                cols = []
                for name in self.engine.gas_list:
                    sh_i, sq_i = val_dict[f"{name}_sh"], val_dict[f"{name}_sq"]
                    pixel_shifted = (pixel_idx - absolute_center) * sq_i + absolute_center + sh_i
                    raw_ref = fit_sign * self.engine.interpolators[name](pixel_shifted) / self.engine.scaling_factors[name]
                    cols.append(raw_ref)
                
                for j in range(poly_order + 1): cols.append(T[:, j])
                cols.append(np.sin(fixed_e_f * pixel_idx + e_p))
                
                A_weighted = W_current @ np.column_stack(cols)
                y_weighted = W_current @ optical_depth
                
                # 티호노프 정규화 적용 (Non-linear Step)
                if lam > 0:
                    Gamma = np.eye(A_weighted.shape[ 1 ]) * lam
                    A_aug = np.vstack((A_weighted, Gamma))
                    y_aug = np.concatenate((y_weighted, np.zeros(A_weighted.shape[ 1 ])))
                else:
                    A_aug, y_aug = A_weighted, y_weighted

                c_temp, _, _, _ = scipy_lstsq(A_aug, y_aug, lapack_driver='gelsy')
                return y_aug - A_aug @ c_temp

            # 1. 비선형 파라미터 최적화 (Shift, Squeeze)
            res_nonlin = least_squares(objective_varpro, x0=theta0, bounds=(theta_lb, theta_ub), max_nfev=1500)
            theta_opt = res_nonlin.x
            
            # 2. 선형 파라미터 최적화 (Concentrations)
            val_dict_opt = {}
            idx = 0
            for v_name in active_vars:
                val_dict_opt[v_name] = theta_opt[idx]; idx += 1
            val_dict_opt.update(fixed_vars)
            for v_name, target in linked_vars.items():
                val_dict_opt[v_name] = val_dict_opt.get(target, 0.0)
                
            opt_shifts = [val_dict_opt[f"{g}_sh"] for g in self.engine.gas_list]
            opt_squeezes = [val_dict_opt[f"{g}_sq"] for g in self.engine.gas_list]
            best_ep = theta_opt[-1]
            
            cols = []
            for gas_idx, name in enumerate(self.engine.gas_list):
                pixel_shifted = (pixel_idx - absolute_center) * opt_squeezes[gas_idx] + absolute_center + opt_shifts[gas_idx]
                raw_ref = fit_sign * self.engine.interpolators[name](pixel_shifted) / self.engine.scaling_factors[name]
                cols.append(raw_ref)
            
            for j in range(poly_order + 1): cols.append(T[:, j])
            cols.append(np.sin(fixed_e_f * pixel_idx + best_ep))
            A_final = np.column_stack(cols)
            
            A_final_weighted = W_current @ A_final
            y_weighted = W_current @ optical_depth
            
            if lam > 0:
                Gamma = np.eye(A_final_weighted.shape[ 1 ]) * lam
                A_aug = np.vstack((A_final_weighted, Gamma))
                y_aug = np.concatenate((y_weighted, np.zeros(A_final_weighted.shape[ 1 ])))
            else:
                A_aug, y_aug = A_final_weighted, y_weighted

            res_lin_final = lsq_linear(A_aug, y_aug)
            c_opt = res_lin_final.x

            # [IRLS 핵심]: 오차가 큰 픽셀의 가중치를 깎아 다음 루프로 전달
            if use_robust and iteration < max_iters - 1:
                residuals = np.abs(optical_depth - A_final @ c_opt)
                # MAD(Median Absolute Deviation) 기반 가중치 계산
                mad = np.median(residuals) if np.median(residuals) > 0 else np.mean(residuals)
                # 튜닝 계수 4.685 (Bisquare Weighting 표준값)
                k = 4.685 * (mad + 1e-9)
                new_w_diag = np.where(residuals < k, (1 - (residuals/k)**2)**2, 0.0)
                W_current = np.diag(new_w_diag * np.diag(W_initial))
            else:
                break # 루프 종료

        # 에러 계산 (Covariance)
        resid_final_weighted = y_weighted - A_final_weighted @ c_opt
        mse = np.mean(resid_final_weighted**2)
        try:
            cov_lin = np.linalg.pinv(A_aug.T @ A_aug) * mse
            perr_lin = np.sqrt(np.diag(cov_lin))
        except Exception:
            perr_lin = np.zeros_like(c_opt)
            
        num_gases = len(self.engine.gas_list)
        gas_coeffs_scaled = c_opt[ 0 : num_gases ]
        poly_coeffs_scaled = c_opt[ num_gases : -1 ]
        etalon_amp_scaled = c_opt[ -1 ]
        gas_errs = perr_lin[ 0 : num_gases ]

        return opt_shifts, opt_squeezes, gas_coeffs_scaled, poly_coeffs_scaled, etalon_amp_scaled, best_ep, gas_errs

    # ==========================================
    # 🌟 Main Orchestrator
    # ==========================================

    def run(self):
        try: current_params = [ float(np.atleast_1d(p)[ 0 ]) for p in self.params ]
        except Exception: current_params = [ 0.0, 1.0 ] + [ 0.1 ] * len(self.engine.gas_list) + [ 0.0 ] * 10
            
        total_files = len(self.file_list)
        last_valid_shift = float(np.atleast_1d(current_params[ 0 ])[ 0 ])
        kalman_filter = KalmanTracker(num_variables=len(self.engine.gas_list), q_noise=0.0005, r_noise=0.05)
        
        for i, file_path in enumerate(self.file_list):
            if not self.is_running: break

            # 🌟 [버그 수정 1]: 매 파일마다 항상 이전 파일에서 성공했던 Shift 값을 중심점으로 잡습니다.
            initial_shift_center = last_valid_shift
            result = {'File': os.path.basename(file_path), 'Params': {}}
            
            try:
                # 1. 파일 읽기 및 전처리
                pixel_idx, intensity_raw = DataIO.load_measurement(file_path, self.pixel_min, self.pixel_max)
                
                avg_raw = np.mean(intensity_raw)
                is_linear_mode = (abs(avg_raw) < 1.0) 
                scale_factor = 10 ** (-np.floor(np.log10(abs(avg_raw)))) if (abs(avg_raw) < 1e-4 and avg_raw != 0) else 1.0
                intensity_processed = intensity_raw * scale_factor
                
                if is_linear_mode:
                    optical_depth = intensity_processed
                    fit_sign = 1.0 
                else:
                    intensity_safe = intensity_processed.copy()
                    intensity_safe[intensity_safe <= 0] = 1e-9
                    optical_depth = np.log(intensity_safe)
                    fit_sign = -1.0 

                poly_start_idx = 2 + len(self.engine.gas_list)
                poly_order = len(current_params) - poly_start_idx - 1
                absolute_center = (self.pixel_min + self.pixel_max) / 2.0 if self.pixel_max else len(intensity_raw)/2.0

                # 2. 에탈론 감지
                if getattr(self, 'etalon_freq', None) is None:
                    self.etalon_freq = self._detect_etalon_frequency(pixel_idx, optical_depth, poly_order)

                # 3. 피팅 루프
                max_retries = 2
                for attempt in range(max_retries):
                    # --- [Auto-Pilot 전략] ---
                    current_lam = self.tikhonov_lambda
                    current_robust = self.use_robust_fitting
                    
                    if attempt == 1:
                        print(f"🚨 [Auto-Pilot] {os.path.basename(file_path)} 피팅 불안정 감지. 방어 모드로 재시도합니다.")
                        current_lam = max(current_lam, 0.01) 
                        current_robust = True               
                    
                    if self.needs_pre_calibration:
                        best_sh, best_sq = self.auto_pre_calibrate(pixel_idx, optical_depth, poly_order)
                        current_params[ 0 ] = best_sh; current_params[ 1 ] = best_sq
                        self.needs_pre_calibration = False

                    if len(current_params) > poly_start_idx:
                        current_params[poly_start_idx] = np.mean(optical_depth) 
                        current_params[poly_start_idx+1 : poly_start_idx+1+poly_order] = [0.0] * poly_order
                    
                    # 4. 파라미터 세팅
                    active_vars, fixed_vars, linked_vars, theta0, theta_lb, theta_ub = self._setup_fit_parameters(initial_shift_center, current_params)
                    fixed_e_f = self.etalon_freq  
                    theta0.append(0.0); theta_lb.append(-np.pi); theta_ub.append(np.pi)
                    
                    try:
                        weights = np.ones_like(intensity_processed) if is_linear_mode else np.sqrt(np.abs(intensity_safe))
                        weights = weights / np.mean(weights)
                        W = np.diag(weights)

                        # 5. 핵심 엔진 호출
                        opt_shifts, opt_squeezes, gas_coeffs_scaled, poly_coeffs_scaled, etalon_amp_scaled, best_ep, gas_errs = self._execute_varpro_fit(
                            pixel_idx, optical_depth, W, active_vars, fixed_vars, linked_vars, theta0, theta_lb, theta_ub, 
                            poly_order, fixed_e_f, absolute_center, fit_sign,
                            override_lam=current_lam, override_robust=current_robust
                        )

                        # 6. 결과 조합 및 저장 (언패킹 개수 5개로 유지)
                        _, abs_val_scaled, poly_val_scaled, _, _ = self.engine.get_model_components(
                            pixel_idx, opt_shifts, opt_squeezes, gas_coeffs_scaled, poly_coeffs_scaled
                        )
                        
                        abs_val_orig, poly_val_orig = abs_val_scaled / scale_factor, poly_val_scaled / scale_factor
                        etalon_part_orig = (etalon_amp_scaled * np.sin(fixed_e_f * pixel_idx + best_ep)) / scale_factor
                        
                        y_fit_model_orig = poly_val_orig + (fit_sign * abs_val_orig) + etalon_part_orig
                        residual = intensity_raw - y_fit_model_orig
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
                            real_conc = (gas_coeffs_scaled[gi] / scale_factor) / scale_div if is_linear_mode else gas_coeffs_scaled[gi] / scale_div
                            real_err = (gas_errs[gi] / scale_factor) / scale_div if is_linear_mode else gas_errs[gi] / scale_div
                            raw_concentrations.append(real_conc); real_errors.append(real_err)

                        smooth_concentrations = kalman_filter.process(raw_concentrations)
                        
                        for gi, nm in enumerate(self.engine.gas_list):
                            result[f"{nm}_Raw"], result[nm], result[f"{nm}_Error"] = raw_concentrations[gi], smooth_concentrations[gi], real_errors[gi]
                            result[f"{nm}_Shift"], result[f"{nm}_Squeeze"] = opt_shifts[gi], opt_squeezes[gi]

                        # 피팅 상태 판정
                        threshold = (np.mean(abs(optical_depth)) * 0.3) if is_linear_mode else 0.05
                        if rms < threshold:
                            status = "OK"
                            if attempt == 1: status = "Recovered" 
                        else:
                            status = "Unstable"

                        result['Status'] = status

                        # 🌟 [버그 수정 2]: 피팅이 성공했다면 이번 파일의 Shift를 다음 파일의 중심점(last_valid_shift)으로 등록!
                        # 0.5 미만이라는 조건을 완전히 없애버려서 Step Limit의 족쇄를 풀었습니다.
                        if status in ["OK", "Recovered"] and len(opt_shifts) > 0:
                            last_valid_shift = opt_shifts[ 0 ]

                        # 만약 OK이거나 이미 재시도 중이라면 루프 종료
                        if status in ["OK", "Recovered"] or attempt == max_retries - 1:
                            break
                        else:
                            # 상태가 안 좋으면 다음 루프에서 방어 모드 발동
                            self.needs_pre_calibration = True
                            
                    except Exception as e:
                        if attempt == max_retries - 1: raise e
                        self.needs_pre_calibration = True

                # 7. UI 전송
                should_update = (self.update_interval > 0) and (i % self.update_interval == 0)
                if should_update or i == total_files - 1:
                    diff_data = intensity_raw - poly_val_orig - etalon_part_orig
                    diff_fit = fit_sign * abs_val_orig
                    self.plot_update.emit(pixel_idx, diff_data, diff_fit, np.zeros_like(pixel_idx), final_params_dict, os.path.basename(file_path))
                    sh_val, sq_val = opt_shifts[ 0 ] if len(opt_shifts) > 0 else 0, opt_squeezes[ 0 ] if len(opt_squeezes) > 0 else 1
                    self.trend_update.emit(i, sh_val, sq_val, rms)
                    
            except Exception as e: 
                result['Status'] = f"Skip: {str(e)}"
                result['RMS'] = 0
                result['Params'] = {}
                self.needs_pre_calibration = True 
                
            self.result_ready.emit(result, i)
            self.progress.emit(i+1)
            time.sleep(self.delay_ms / 1000.0 if self.delay_ms > 0 else 0.001) 
            
        self.finished.emit()

    def stop(self):
        self.is_running = False