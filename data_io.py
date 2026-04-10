import os
import numpy as np
import pandas as pd

class DataIO:
    """
    CAESAR Pro Data Input/Output Manager
    모든 파일 로딩과 데이터 정제를 전담하여 엔진과 UI를 가볍게 만듭니다.
    """

    @staticmethod
    def enforce_1d_array(data):
        if data is None:
            return None
        
        # 튜플로 감싸져 있다면 첫 번째 요소를 꺼냄
        if isinstance(data, tuple):
            data = data[ 0 ]
            
        return np.atleast_1d(data).flatten().astype(float)

    @staticmethod
    def load_reference(filepath):
        try:
            try:
                df = pd.read_csv(filepath, sep=r'\s+', header=None, comment='#')
            except Exception:
                df = pd.read_csv(filepath, sep=',', header=None, comment='#')

            # 🌟 [버그 원천 차단]: df.shape 대신 len(df.columns)를 사용하여 인덱스 증발 버그 방지
            if len(df.columns) >= 2:
                wave_nm = pd.to_numeric(df.iloc[:, 0 ], errors='coerce').values
                intensity_raw = pd.to_numeric(df.iloc[:, 1 ], errors='coerce').values
            else:
                wave_nm = None
                intensity_raw = pd.to_numeric(df.iloc[:, -1 ], errors='coerce').values

            if wave_nm is not None:
                valid_mask = ~np.isnan(wave_nm) & ~np.isnan(intensity_raw) & np.isfinite(intensity_raw)
                wave_nm = wave_nm[ valid_mask ]
                intensity_raw = intensity_raw[ valid_mask ]
            else:
                valid_mask = ~np.isnan(intensity_raw) & np.isfinite(intensity_raw)
                intensity_raw = intensity_raw[ valid_mask ]

            return wave_nm, intensity_raw

        except Exception as e:
            raise RuntimeError(f"레퍼런스 파일 읽기 실패 ({os.path.basename(filepath)}): {str(e)}")

    @staticmethod
    def load_measurement(filepath, pixel_min=0, pixel_max=None):
        try:
            df = pd.read_csv(filepath, sep=r'\s+', header=None, dtype=str)
            intensity_full = pd.to_numeric(df.iloc[:, 0 ], errors='coerce').values
            
            valid_mask = ~np.isnan(intensity_full) & np.isfinite(intensity_full)
            intensity_clean = intensity_full[ valid_mask ]
            
            # 안전한 타입 변환
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
    def extract_gas_name(filepath):
        base = os.path.basename(filepath)
        return os.path.splitext(base)[ 0 ]