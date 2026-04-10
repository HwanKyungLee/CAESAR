import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import convolve
from scipy.stats import norm
from numpy.polynomial import chebyshev
from data_io import DataIO 

class UniversalEngine:
    """
    CAESAR Pro Core Analysis Engine (Phase 2.6 Refactored)
    - 에탈론(Etalon) 성분까지 엔진 내부에서 통합 처리.
    - Basis Matrix 생성기를 고급형(배열 파라미터 지원)으로 업그레이드.
    """
    def __init__(self):
        self.raw_references = {}      
        self.interpolators = {}       
        self.gas_list = []            
        self.scaling_factors = {}     

    def clear_engine(self):
        self.raw_references = {}
        self.interpolators = {}
        self.gas_list = []
        self.scaling_factors = {}

    def is_engine_ready(self) -> bool:
        return len(self.gas_list) > 0

    # ---------------------------------------------------------
    # Reference Loading & Pre-processing
    # ---------------------------------------------------------
    def add_reference(self, name, filepath, wave_nm=None, multiplier=1.0):
        try:
            wave_nm_clean = DataIO.enforce_1d_array(wave_nm)
            wave_nm_ref, intensity_raw = DataIO.load_reference(filepath)

            if wave_nm_ref is not None and wave_nm_clean is not None:
                f_interp = interp1d(wave_nm_ref, intensity_raw, kind='cubic', bounds_error=False, fill_value="extrapolate")
                intensity_processed = f_interp(wave_nm_clean)
                print(f"-> {name}: Interpolated to instrument wavelength.")
            else:
                intensity_processed = intensity_raw
                print(f"-> {name}: No wavelength info. Loaded as 1D array.")

            intensity_processed = intensity_processed * multiplier
            max_abs_val = np.max(np.abs(intensity_processed))
            if max_abs_val == 0: max_abs_val = 1.0

            self.raw_references[name] = intensity_processed
            pixel_idx = np.arange(len(intensity_processed))
            self.interpolators[name] = interp1d(pixel_idx, intensity_processed, kind='cubic', bounds_error=False, fill_value="extrapolate")

            if name not in self.gas_list: self.gas_list.append(name)
            self.scaling_factors[name] = max_abs_val
            return True, f"{name} Loaded Successfully"
        except Exception as e:
            return False, f"Error loading {name}: {str(e)}"

    def apply_ils_convolution(self, fwhm_pixels):
        if not self.is_engine_ready(): return

        if fwhm_pixels <= 0.1:
            for name in self.gas_list:
                pixel_idx = np.arange(len(self.raw_references[name]))
                self.interpolators[name] = interp1d(pixel_idx, self.raw_references[name], kind='cubic', fill_value="extrapolate")
            return

        sigma = fwhm_pixels / 2.355
        radius = int(4 * sigma) + 1
        x_kernel = np.arange(-radius, radius + 1)
        kernel = norm.pdf(x_kernel, 0, sigma)
        kernel /= kernel.sum() 

        for name in self.gas_list:
            convolved_y = convolve(self.raw_references[name], kernel, mode='same')
            pixel_idx = np.arange(len(self.raw_references[name]))
            self.interpolators[name] = interp1d(pixel_idx, convolved_y, kind='cubic', fill_value="extrapolate")
            max_abs_val = np.max(np.abs(convolved_y))
            self.scaling_factors[name] = max_abs_val if max_abs_val != 0 else 1.0

    def apply_manual_mask(self, name, min_idx, max_idx):
        if name not in self.raw_references: return False
        data = self.raw_references[name].copy()
        start, end = max(0, int(min_idx)), min(len(data), int(max_idx))
        data[:start], data[end:] = 0.0, 0.0
        self._sync_reference_update(name, data)
        return True

    def apply_auto_mask(self, name, threshold_percent):
        if name not in self.raw_references: return False
        data = self.raw_references[name].copy()
        max_val = np.max(np.abs(data))
        if max_val == 0: return False
        data[np.abs(data) < max_val * (threshold_percent / 100.0)] = 0.0
        self._sync_reference_update(name, data)
        return True

    def _sync_reference_update(self, name, data):
        self.raw_references[name] = data
        pixel_idx = np.arange(len(data))
        self.interpolators[name] = interp1d(pixel_idx, data, kind='cubic', fill_value="extrapolate")
        max_abs_val = np.max(np.abs(data))
        self.scaling_factors[name] = max_abs_val if max_abs_val != 0 else 1.0

    # ---------------------------------------------------------
    # Mathematical Fitting Models (Upgraded)
    # ---------------------------------------------------------
    
    #Custom Basis (Ring 스펙트럼, PCA 배경광 등) 주입 통로 개설
    def get_model_components(self, pixel_idx, shifts, squeezes, gas_coeffs, poly_coeffs, etalon_amp=0.0, etalon_freq=0.0, etalon_phase=0.0, custom_basis=None, custom_coeffs=None):
        """Returns: (Full Model, Total Absorption, Polynomial Baseline, Etalon Wave, Custom Optical Effects)"""
        center_idx = pixel_idx[ len(pixel_idx)//2 ]
        
        total_absorption = 0
        for i, name in enumerate(self.gas_list):
            sh = shifts[ i ] if hasattr(shifts, '__iter__') else shifts
            sq = squeezes[ i ] if hasattr(squeezes, '__iter__') else squeezes
            
            pixel_shifted = (pixel_idx - center_idx) * sq + center_idx + sh
            normalized_ref = self.interpolators[name](pixel_shifted) / self.scaling_factors[name]
            total_absorption += (gas_coeffs[ i ] * normalized_ref)
            
        baseline = 0
        if len(poly_coeffs) > 0:
            x_min, x_max = pixel_idx[ 0 ], pixel_idx[ -1 ]
            x_mapped = (2.0 * (pixel_idx - x_min) / (x_max - x_min)) - 1.0
            baseline = chebyshev.chebval(x_mapped, poly_coeffs)
            
        etalon_wave = etalon_amp * np.sin(etalon_freq * pixel_idx + etalon_phase)
        
        # 광학 보정 항 (Ring Effect 등) 추가
        custom_effect = 0
        if custom_basis is not None and custom_coeffs is not None:
            # custom_basis는 (픽셀 수, 기저 개수) 형태의 2D 배열이라고 가정합니다.
            for i in range(custom_basis.shape):
                custom_effect += custom_coeffs[i] * custom_basis[:, i]
        
        full_model = baseline + total_absorption + etalon_wave + custom_effect
        return full_model, total_absorption, baseline, etalon_wave, custom_effect
    
    def get_individual_gas_contribution(self, pixel_idx, shifts, squeezes, gas_coeffs, gas_index):
        center_idx = pixel_idx[ len(pixel_idx)//2 ]
        sh = shifts[ gas_index ] if hasattr(shifts, '__iter__') else shifts
        sq = squeezes[ gas_index ] if hasattr(squeezes, '__iter__') else squeezes
        
        pixel_shifted = (pixel_idx - center_idx) * sq + center_idx + sh
        gas_name = self.gas_list[ gas_index ]
        coefficient = gas_coeffs[ gas_index ]
        
        return coefficient * self.interpolators[gas_name](pixel_shifted) / self.scaling_factors[gas_name]
        
    def get_absolute_concentration(self, name, fit_coefficient):
        return fit_coefficient / self.scaling_factors[name]
    
    # Basis Matrix에 Custom Basis 행렬 병합 기능 추가
    def get_basis_matrix(self, pixel_idx, shifts, squeezes, poly_order=-1, etalon_freq=None, etalon_phase=0.0, custom_basis=None):
        center_idx = pixel_idx[ len(pixel_idx)//2 ]
        column_vectors = []
        
        # 1. 미량 가스 (Trace Gases)
        for i, name in enumerate(self.gas_list):
            sh = shifts[ i ] if hasattr(shifts, '__iter__') else shifts
            sq = squeezes[ i ] if hasattr(squeezes, '__iter__') else squeezes
            
            pixel_shifted = (pixel_idx - center_idx) * sq + center_idx + sh
            column_vectors.append(self.interpolators[name](pixel_shifted) / self.scaling_factors[name])
            
        # 2. 다항식 베이스라인 (Polynomial)
        if poly_order >= 0:
            x_min, x_max = pixel_idx[ 0 ], pixel_idx[ -1 ]
            x_mapped = (2.0 * (pixel_idx - x_min) / (x_max - x_min)) - 1.0
            vander_matrix = chebyshev.chebvander(x_mapped, poly_order)
            for i in range(poly_order + 1):
                column_vectors.append(vander_matrix[:, i ])
                
        # 3. 에탈론 (Etalon Interference)
        if etalon_freq is not None:
            column_vectors.append(np.sin(etalon_freq * pixel_idx + etalon_phase))

        # 4.  특수 광학 보정 항 (Ring Effect, PCA Background 등)
        if custom_basis is not None:
            # custom_basis가 1D 배열이면 2D 열 벡터로 변환
            if custom_basis.ndim == 1:
                custom_basis = custom_basis.reshape(-1, 1)
            for i in range(custom_basis.shape):
                column_vectors.append(custom_basis[:, i])
                
        return np.column_stack(column_vectors)