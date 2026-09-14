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

# ── 공기 수밀도 — **이 저장소의 단일 출처** ────────────────────────────────────
# Loschmidt 상수: STP(0 °C, 101.325 kPa)의 분자 밀도 [molec/cm³].
# Rayleigh σ의 기준 밀도이자 ppb 환산(n_air)의 기준이다 — **같은 물리량이므로 상수도
# 하나여야 한다.**
#
# 매직넘버로 적지 않고 **2019 SI 정의 상수에서 유도**한다. 2019년 SI 재정의 이후
# k_B·표준대기압·0 °C가 모두 정확값이므로 n₀ = p/(k_B·T)는 **정확히 계산되는 값**이고,
# 이렇게 두면 CODATA 판이 바뀌어도 낡지 않는다.
#
# ⚠ 이력(2026-09-14): 이 저장소엔 두 값이 돌아다니고 있었다 —
#   · ppb 환산:  2.68678e19        (정답을 6자리로 자른 값, 오차 −4.2e-8)
#   · Rayleigh:  2.6867811e19      (**CODATA 2014 구값**, 오차 +3.7e-7 — 9배 나쁨)
# "소수점이 많은 쪽"이 정확한 쪽이 아니었다. 아래 유도값이 정답(= CODATA 2018,
# 2.686 780 111 × 10²⁵ m⁻³)이며, 둘 다 여기로 통일했다.
_K_BOLTZMANN = 1.380649e-23    # J/K   — 2019 SI 정의(정확)
_P_STD_PA    = 101325.0        # Pa    — 표준대기압(정확)
_T_STD_K     = 273.15          # K     — 0 °C(정확)
N_LOSCHMIDT  = _P_STD_PA / (_K_BOLTZMANN * _T_STD_K) * 1e-6   # molec/cm³ ≈ 2.686780111e19


def air_number_density(T_C: float, P_mbar: float) -> float:
    """이상기체 공기 수밀도 N(T,P) [molec/cm³]. **ppb 환산의 단일 출처.**

        ppb = (핏 계수 / N(T,P)) × 1e9

    과거 이 식이 코어 4곳·GUI 3곳·도구 3곳에 복사돼 있었다(전부 같은 값이라 무해했지만,
    Rayleigh 사본이 한쪽만 고쳐져 R이 틀어졌던 사고와 같은 패턴). 새 코드는 여기만 쓴다.

    ⚠ 알려진 한계 — **이상기체 가정**(오차 예산에 넣을 항목, 2026-09-14 정량화)
    ------------------------------------------------------------------------
    이 함수는 PV=nRT다. 실제 공기는 분자간 인력 때문에 **같은 T·P에서 이상기체보다
    분자가 조금 더 들어간다**(압축인자 Z<1, 실제밀도 = 이상밀도/Z):

        T = 0 °C   Z=0.99953  →  실제가 +0.047% 많음
        T = 25 °C  Z=0.99971  →  +0.029%
        T = 35 °C  Z=0.99977  →  +0.023%   (핫 셀 실측 온도대)

    ppb = N_gas / N_air 이므로 **분모를 그만큼 작게 잡는 셈** → 보고되는 농도가
    **항상 같은 방향으로 0.02~0.05% 크게** 나온다(100 ppb면 +20~30 ppt, 0.64 ppb면
    +0.2 ppt). 무작위 오차와 달리 평균해도 안 사라진다.

    **그런데 이건 버그가 아니라 관례다.** 두 군데서 쓰이는데 요구가 서로 다르다:
      · Rayleigh σ 정규화(위 N_LOSCHMIDT) — 문헌(Bodhaine 1999 등)이 σ를 **이상기체**
        밀도 기준으로 정의한다(N_s=2.546899e19 = p/(k·288.15), 실제로 이상값). 여기선
        이상기체가 **맞다**. 안 그러면 문헌 σ와 어긋난다.
      · ppb 환산 — 캐비티 속 **실제** 분자 수를 원하므로 엄밀히는 Z 보정이 옳다.

    지금은 둘이 같은 식을 써서 σ 쪽 관례에 맞춰져 있다. 고치려면 ppb 경로에만
    `/Z(T,P)`를 넣으면 되지만(2차 비리얼 B(T)로 충분), **단면 문헌 불확도(~3%)보다
    100배 작아 우선순위는 낮다.** docs 오차 예산(§10-2)에 한 줄로 기록할 것:
    "n_air: 이상기체 가정, +0.02~0.05% 계통(미보정)".
    """
    return N_LOSCHMIDT * (P_mbar / 1013.25) * (273.15 / (T_C + 273.15))


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

    Note: σ는 STP 분자 밀도 N₀ (Loschmidt 상수) 기준으로 정의되는 분자 고유값.
          α = σ × N(T,P) 이므로 압력·온도가 증가하면 α도 정비례 증가한다.
    """
    @staticmethod
    def get_alpha_rayleigh(
        wave_nm: np.ndarray,
        temp_c: float,
        press_mbar: float,
        gas_type: str = "zero_air",
    ) -> np.ndarray:
        wave_nm = np.asarray(wave_nm, dtype=float)
        # Loschmidt 상수 — STP 분자 밀도. σ 공식 분모에 사용(모듈 상수 = ppb 환산과 공유).
        N0 = N_LOSCHMIDT
        # 현재 조건(P,T)에서의 실제 분자 밀도. α = σ × N(T,P) 변환에 사용.
        N  = air_number_density(temp_c, press_mbar)
        v = 1e7 / wave_nm   # 파수 [cm⁻¹], 단 λ는 nm 단위

        if gas_type in ("zero_air", "air"):
            # ── MATLAB 경험식 (주석 보존) ───────────────────────────────────────
            # 출처: Rs2_CAESAR_Cold_Yeosu_2026.m (optimize_ZA_Rayleigh.m 피팅)
            #   σ_ZA = 3.019852e-14 × λ_nm^-3.87465  [cm²/molecule]
            # ※ 박사님 fun_air 코드 확인 결과 MATLAB N도 Loschmidt 2.6867811e19 cm⁻³
            #   기반이며 **N 컨벤션까지는** Python과 동일. 다만 σ 공식이 다르다
            #   (MATLAB = 경험식, Python = Sellmeier 물리식) → α 결과가 차이날 수 있음
            #   (경험식 대비 −3.2%로 정량화됨 — docs/Augur_소개_2026-07.md).
            #
            # ★ 2026-09-14 — **N 상수를 MATLAB에 맞출 이유가 없다(맞춰도 정렬 안 됨)**:
            #   두 구현에서 α의 N₀ **지수가 반대**다.
            #     · MATLAB : σ = 3.019852e-14·λ^-3.87465 → σ에 N₀ 없음
            #                α = σ·N = σ·N₀·f(T,P)          ⇒ α ∝ N₀^(+1)
            #     · Augur  : σ = Fk·(24π³ν⁴/N₀²)·(…)²  (아래 s_n2/s_o2/sigma)
            #                α = σ·N ∝ f(T,P)/N₀           ⇒ α ∝ N₀^(−1)
            #   같은 N₀를 넣어도 α는 서로 **반대 방향**으로 움직인다. 그래서 위 "N 컨벤션
            #   동일"은 N에 대해서만 참이고 α로 가면 깨진다 — MATLAB의 값(2.6867811e19 =
            #   CODATA 2014 구값, 정답 대비 +3.7e-7)에 맞추면 알려진 오차만 영구히 떠안는다.
            #   그래서 N_LOSCHMIDT는 SI 정의 유도값으로 두고, MATLAB과의 이 미세 이탈
            #   (α 상대 +3.7e-7)은 **의도된 것**으로 기록한다. 3.2% 식 차이 옆에서 무의미한
            #   크기이기도 하다. 과거 대조 스크립트
            #   (diagnostics/alpha_vs_matlab_2025_06_11/compare_alpha.py)는 그때 값을
            #   그대로 둔다 — 그 시점 계산의 증거라서.
            #
            #   ⚠ 그러니 **N₀를 MATLAB 값(2.6867811e19)에 맞추려 하지 말 것** (2026-09-14 검토).
            #   두 코드에서 N₀의 **지수가 반대**다:
            #     · MATLAB : σ가 경험식이라 N₀를 안 씀   → α = σ·N ∝ N₀^(+1)
            #     · Augur  : σ = …/N₀²  (아래 Sellmeier) → α = σ·N ∝ N₀^(−1)
            #   같은 상수를 넣어도 α는 서로 **반대 방향**으로 움직인다. 즉 상수를 맞춰도
            #   정렬되는 것이 없고, 알려진 +3.7e-7 오차(CODATA 2014 구값)만 떠안게 된다.
            #   N₀는 모듈 상수 N_LOSCHMIDT(SI 정의 유도값)를 쓴다.
            # sigma = 3.019852e-14 * wave_nm ** (-3.87465)
            # ────────────────────────────────────────────────────────────────────

            # N₂: Peck & Reeder (1972) Sellmeier — Sellmeier 굴절률이 STP 기준이므로
            # σ 공식의 분모도 STP 분자 밀도 N₀를 써야 σ가 P/T에 무관한 분자 고유값이 된다.
            A_n2, B_n2, C_n2 = 5677.465, 318.81874e12, 14.4e9
            n_n2 = 1.0 + (A_n2 + B_n2 / (C_n2 - v**2)) * 1e-8
            # King 보정계수 F_k(N₂) = 1.034 + 3.17e-12·ν²  (Bates 1984; Bodhaine 1999).
            # ν 는 파수[cm⁻¹]. 과거 코드는 ν² 가 아니라 ν(1차항)이라 파장의존이 죽어
            # F_k≈1.034 상수로 고정됐었다(σ_N₂ ~0.15% 과소 → σ_ZA·R 계통편향). v**2 로 교정.
            Fk_n2 = 1.034 + 3.17e-12 * v**2
            s_n2 = Fk_n2 * (24 * np.pi**3 * v**4 / N0**2) * ((n_n2**2 - 1) / (n_n2**2 + 2))**2

            # O₂: Bates (1984) Sellmeier
            A_o2, B_o2, C_o2 = 20564.8, 2.480899e13, 4.09e9
            n_o2 = 1.0 + (A_o2 + B_o2 / (C_o2 - v**2)) * 1e-8
            # King 보정계수 F_k(O₂) = 1.096 + 1.385e-11·ν² + 1.448e-20·ν⁴  (Bates 1984;
            # Bodhaine 1999). 상수항은 1.09 가 아니라 1.096 이 정설(과거 1.09 → ~0.5% 과소).
            Fk_o2 = 1.096 + 1.385e-11 * v**2 + 1.448e-20 * v**4
            s_o2 = Fk_o2 * (24 * np.pi**3 * v**4 / N0**2) * ((n_o2**2 - 1) / (n_o2**2 + 2))**2

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
            sigma = (24 * np.pi**3 * v**4 / N0**2) * ((n_he**2 - 1) / (n_he**2 + 2))**2

        return sigma * N  # α = σ × N(T,P)  [cm⁻¹] — α는 압력·온도에 정비례


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


def _demo():
    """자기검증: ppb 환산과 Rayleigh가 **같은 상수**를 쓰는지 + 위임이 끊기지 않았는지."""
    # 유도값이 CODATA 2018 Loschmidt(2.686 780 111e19 cm^-3)와 맞나 — 매직넘버 방지
    assert abs(N_LOSCHMIDT - 2.686780111e19) / 2.686780111e19 < 1e-9, N_LOSCHMIDT
    assert abs(air_number_density(0.0, 1013.25) - N_LOSCHMIDT) < 1e6, "STP에서 N0가 아님"
    n1 = air_number_density(25.0, 1013.25)
    assert abs(n1 - N_LOSCHMIDT * (273.15 / 298.15)) / n1 < 1e-12
    # 온도·압력 의존이 물리대로인지(밀도 ∝ P, ∝ 1/T)
    assert abs(air_number_density(0.0, 2026.5) - 2 * N_LOSCHMIDT) / N_LOSCHMIDT < 1e-12

    # Rayleigh가 같은 밀도를 쓰는지 — σ는 상수이므로 α는 N에 정비례해야 한다
    a1 = RayleighPhysics.get_alpha_rayleigh(np.array([440.0]), 0.0, 1013.25, "zero_air")
    a2 = RayleighPhysics.get_alpha_rayleigh(np.array([440.0]), 0.0, 2026.5, "zero_air")
    ratio = float(np.asarray(a2 / a1).ravel()[0])
    assert abs(ratio - 2.0) < 1e-9, ratio

    # 코어 모듈들이 사본이 아니라 이 함수를 재사용하는지(같은 객체여야 한다)
    # `python -m core.physics`로 돌리면 이 파일이 __main__과 core.physics 두 번 로드된다
    # → 위임 모듈이 쓰는 건 후자다. 기준을 후자로 잡아야 착시가 안 생긴다.
    from core import physics as _cp
    from core import fit_optimizer, fit_physics, param_optimizer, window_designer
    for m in (fit_optimizer, fit_physics, param_optimizer, window_designer):
        assert m.air_number_density is _cp.air_number_density, m.__name__ + " 가 사본을 쓴다"

    print("physics self-check OK: N(25C,1013.25) = %.6e molec/cm3" % n1)


if __name__ == "__main__":
    _demo()
