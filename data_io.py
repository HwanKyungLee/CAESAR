import os
import numpy as np
import pandas as pd

class DataIO:
    """
    CAESAR Pro Data Input/Output Manager
    모든 파일 로딩과 데이터 정제를 전담하여 엔진과 UI를 가볍게 만듭니다.
    Araon 2025 Mega-Matrix 포맷 및 일반 1D DOAS 포맷을 모두 지원합니다.
    """

    @staticmethod
    def enforce_1d_array(data):
        if data is None: return np.array([0.0])
        if isinstance(data, tuple): data = data[ 0 ]
        return np.atleast_1d(data).flatten().astype(float)

    @staticmethod
    def load_reference(filepath):
        try:
            try:
                df = pd.read_csv(filepath, sep=r'\s+', header=None, comment='#')
            except Exception:
                df = pd.read_csv(filepath, sep=',', header=None, comment='#')

            if len(df.columns) >= 2:
                wave_nm = pd.to_numeric(df.iloc[:, 0 ], errors='coerce').values
                intensity_raw = pd.to_numeric(df.iloc[:, 1 ], errors='coerce').values
            else:
                wave_nm = None
                intensity_raw = pd.to_numeric(df.iloc[:, -1 ], errors='coerce').values

            return wave_nm, intensity_raw
        except Exception as e:
            raise RuntimeError(f"Reference load failed: {str(e)}")

    @staticmethod
    def load_measurement(filepath, pixel_min=0, pixel_max=None):
        """기존의 단순 스펙트럼 읽기용 호환성 함수"""
        try:
            df = pd.read_csv(filepath, sep=r'\s+', header=None, dtype=str)
            intensity_full = pd.to_numeric(df.iloc[:, 0 ], errors='coerce').values
            
            valid_mask = ~np.isnan(intensity_full) & np.isfinite(intensity_full)
            intensity_clean = intensity_full[ valid_mask ]
            
            p_min = int(pixel_min)
            if len(intensity_clean) < p_min + 10:
                raise ValueError("데이터의 길이가 픽셀 최소 범위보다 짧습니다.")

            if pixel_max is None or int(pixel_max) > len(intensity_clean):
                p_max = len(intensity_clean)
            else:
                p_max = int(pixel_max)

            intensity_raw = intensity_clean[ p_min : p_max ]
            pixel_idx = np.arange(p_min, p_max)

            if np.max(np.abs(intensity_raw)) < 1e-10:
                raise ValueError("Garbage data detected (값이 너무 작음)")

            return pixel_idx, intensity_raw

        except Exception as e:
            raise RuntimeError(f"측정 파일 읽기 실패 ({os.path.basename(filepath)}): {str(e)}")

    @staticmethod
    def load_measurement_with_hk(filepath, pixel_min=0, pixel_max=None):
        """
        Extracts Spectrum, Flag, Temp, and Press from Araon Raw .dat files.
        Mapping based on LabVIEW Mega-Matrix format.
        """
        try:
            # Read all columns for the first row (Horizontal format)
            df = pd.read_csv(filepath, sep=r'\s+', header=None, dtype=str, nrows=1)
            
            # Flatten to 1D array to handle horizontal format correctly
            raw_data = pd.to_numeric(df.values.flatten(), errors='coerce')
            
            # Default fallback values
            state_flag = 0  
            env_t = 25.0
            env_p = 1013.25
            
            # Check if it is the Araon Mega-Matrix format (6175+ columns)
            if len(raw_data) >= 6175:
                # Ch1 NO2 Spectrum (Index 2053 to 4100 -> Length 2048)
                intensity_full = raw_data[ 2053 : 4101 ]
                
                # Housekeeping Data (Index based on MATLAB 1-based mapping)
                state_flag = int(raw_data[ 4 ])  # 5th value
                env_p = raw_data[ 6162 ]         # presscell1 (4115+2048-1)
                env_t = raw_data[ 6174 ]         # tempcell1 (4127+2048-1)
            else:
                intensity_full = raw_data

            valid_mask = ~np.isnan(intensity_full) & np.isfinite(intensity_full)
            intensity_clean = intensity_full[ valid_mask ]
            
            p_min = int(pixel_min)
            p_max = len(intensity_clean) if (pixel_max is None or int(pixel_max) > len(intensity_clean)) else int(pixel_max)

            intensity_raw = intensity_clean[ p_min : p_max ]
            pixel_idx = np.arange(p_min, p_max)

            return pixel_idx, intensity_raw, state_flag, env_t, env_p

        except Exception as e:
            raise RuntimeError(f"HK Data Load Failed ({os.path.basename(filepath)}): {str(e)}")

    @staticmethod
    def extract_gas_name(filepath):
        base = os.path.basename(filepath)
        return os.path.splitext(base)[ 0 ]