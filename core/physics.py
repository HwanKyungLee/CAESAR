"""
core/physics.py — 공용 물리 연산 모듈
======================================
CAESAR Pro 전체에서 공유하는 물리 계산 클래스.
GUI 워커(gui/worker.py)와 반사율 계산기(tools/reflectance_calc.py)
양쪽에서 동일하게 사용한다.

Classes
-------
RayleighPhysics  : Rayleigh 산란 소광 계수 α(λ) 계산 (Sellmeier 굴절률 기반)
KalmanTracker    : 농도 시계열 스무딩용 다변수 Kalman 필터
"""
from __future__ import annotations
import numpy as np


class RayleighPhysics:
    """
    Rayleigh scattering extinction α(λ) [cm⁻¹] — Sellmeier 굴절률 기반.

    Zero-Air (N₂ 79% + O₂ 21%):
      Peck & Reeder (1972) Sellmeier for N₂; Bates (1984) for O₂.
      σ(λ) = 0.79·σ_N₂ + 0.21·σ_O₂  [cm²/molecule]

    Helium:
      Cuthbertson & Cuthbertson (1936) Sellmeier.

    Number density: N = N_Loschmidt × (P/P₀) × (T₀/T)  [molecules cm⁻³]
    α(T,P,λ) = σ(λ) × N(T,P)  [cm⁻¹]

    Note: σ는 N²에 반비례하므로 α = σ × N ∝ N (pressure/temperature에 정상 비례).
    """
    @staticmethod
    def get_alpha_rayleigh(
        wave_nm: np.ndarray,
        temp_c: float,
        press_mbar: float,
        gas_type: str = "zero_air",
    ) -> np.ndarray:
        wave_nm = np.asarray(wave_nm, dtype=float)
        N = 2.68678e19 * (press_mbar / 1013.25) * (273.15 / (temp_c + 273.15))
        v = 1e7 / wave_nm   # 파수 [cm⁻¹], 단 λ는 nm 단위

        if gas_type in ("zero_air", "air"):
            # ── MATLAB 경험식 (주석 보존) ───────────────────────────────────────
            # 출처: Rs2_CAESAR_Cold_Yeosu_2026.m (optimize_ZA_Rayleigh.m 피팅)
            #   σ_ZA = 3.019852e-14 × λ_nm^-3.87465  [cm²/molecule]
            # ※ MATLAB fun_air의 N 단위 관례에 맞게 피팅된 상수이므로,
            #   Python의 표준 Loschmidt N (2.688e19 cm⁻³)과 함께 쓰면 α가 ~100배 커짐.
            #   Python에서는 아래 Sellmeier 공식을 사용한다.
            # sigma = 3.019852e-14 * wave_nm ** (-3.87465)
            # ────────────────────────────────────────────────────────────────────

            # N₂: Peck & Reeder (1972) Sellmeier
            A_n2, B_n2, C_n2 = 5677.465, 318.81874e12, 14.4e9
            n_n2 = 1.0 + (A_n2 + B_n2 / (C_n2 - v**2)) * 1e-8
            Fk_n2 = 1.034 + 3.17e-12 * v
            s_n2 = Fk_n2 * (24 * np.pi**3 * v**4 / N**2) * ((n_n2**2 - 1) / (n_n2**2 + 2))**2

            # O₂: Bates (1984) Sellmeier
            A_o2, B_o2, C_o2 = 20564.8, 2.480899e13, 4.09e9
            n_o2 = 1.0 + (A_o2 + B_o2 / (C_o2 - v**2)) * 1e-8
            Fk_o2 = 1.09 + 1.385e-11 * v**2 + 1.448e-20 * v**4
            s_o2 = Fk_o2 * (24 * np.pi**3 * v**4 / N**2) * ((n_o2**2 - 1) / (n_o2**2 + 2))**2

            sigma = 0.79 * s_n2 + 0.21 * s_o2

        else:  # helium — Cuthbertson & Cuthbertson (1936)
            # ── MATLAB 경험식 (주석 보존) ───────────────────────────────────────
            # 출처: Rs2_CAESAR_Cold_Yeosu_2026.m
            #   σ_He = 1.336e-17 × λ_nm^-4.1287  [cm²/molecule]
            # ※ 위 ZA 경험식과 동일한 이유로 Python에서는 Sellmeier 사용.
            # sigma = 1.336e-17 * wave_nm ** (-4.1287)
            # ────────────────────────────────────────────────────────────────────

            A_he, B_he, C_he = 2283.0, 1.8102e13, 1.5342e10
            n_he = 1.0 + (A_he + B_he / (C_he - v**2)) * 1e-8
            sigma = (24 * np.pi**3 * v**4 / N**2) * ((n_he**2 - 1) / (n_he**2 + 2))**2

        return sigma * N  # α = σ × N(T,P)  [cm⁻¹]


class KalmanTracker:
    """
    다변수 Kalman 필터 — 농도 시계열 스무딩용.

    두 정보원의 균형을 맞춘 스마트 이동평균:
      1. 이전 추정값(state)  — 모델 신뢰도(Q)로 가중
      2. 새 측정값           — 센서 신뢰도(R)로 가중

    Parameters
    ----------
    q_noise : 프로세스 노이즈 — 실제 농도가 프레임당 얼마나 변할 수 있는지.
              Q 클수록 빠르게 추적 (급격한 플룸에 유리, 노이즈 증가).
    r_noise : 측정 노이즈 — 개별 피팅 결과를 얼마나 불신하는지.
              R 클수록 강하게 스무딩 (안정적 배경 모니터링에 유리).
    """
    def __init__(self, num_variables: int, q_noise: float = 1e-4, r_noise: float = 1e-2):
        self.num_vars = num_variables
        self.state = np.zeros(num_variables)
        self.P = np.eye(num_variables)
        self.Q = np.eye(num_variables) * q_noise
        self.R = np.eye(num_variables) * r_noise
        self.is_initialized = False

    def process(self, measurement) -> np.ndarray:
        z = np.array(measurement, dtype=float)

        if not self.is_initialized:
            self.state = z.copy()
            self.is_initialized = True
            return self.state.copy()

        # Predict: 불확실도 전파 P_k|k-1 = P + Q
        p_predict = self.P + self.Q

        # Update: Kalman gain = P_pred / (P_pred + R)
        #   R 클수록(노이즈 센서) K→0, 예측값 신뢰
        #   R 작을수록(정밀 센서) K→1, 측정값 신뢰
        kalman_gain = p_predict @ np.linalg.inv(p_predict + self.R)

        self.state = self.state + kalman_gain @ (z - self.state)
        self.P = (np.eye(self.num_vars) - kalman_gain) @ p_predict
        return self.state.copy()
