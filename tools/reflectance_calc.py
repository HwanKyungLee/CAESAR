from __future__ import annotations

import os
import sys

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# Rayleigh Scattering Physics  →  단일 출처(single source of truth) = core/physics.py
# ─────────────────────────────────────────────────────────────────────────────
# 이 파일에는 원래 RayleighPhysics 사본이 따로 들어 있었고, 그 사본은 박사님
# MATLAB *경험식*(fminsearch 피팅)을 그대로 이식한 것이었다:
#     σ_ZA = 3.019852e-14 · λ_nm^-3.87465                         [cm²/molec]
#     σ_He = 자작식  1e-8·(348.933 + 4.02/λ_um²) → n-1 기반
#
# ── 왜 원래(경험식)는 안 됐나 ────────────────────────────────────────────────
# 그 계수들을 Python에서 λ[nm]로 그대로 평가하면 스케일/단위가 맞지 않아
#     α_ZA 가 물리값(Sellmeier) 대비 ~168배 과대,
#     α_He 가 ~35배 과소        (게다가 ZA는 nm, He는 µm를 섞어 씀 → air/He 비가
#                                 실제 ~68 대신 ~400,000 으로 깨짐)
# 로 나온다. omr_d = (1−R)/d 는 ZA 항에 지배되므로 α_ZA 가 168배 커지면
# (1−R) 도 ~100배 부풀어 → R≈0.990 (정상 0.9999), Leff≈50 m (정상 ~9 km) 로
# 완전히 틀어진다. (2026-05-20 실측 파일로 재현·검증 완료: 정본으로 바꾸면
#  R 0.990→0.99994, Leff 0.05→~9 km.)
#
# ── 왜 이식(Sellmeier 정본)을 쓰나 ───────────────────────────────────────────
# core/physics.py 는 이미 위 경험식을 버리고 분산식(Sellmeier)으로 교체돼 있다:
#     N₂ = Peck & Reeder(1972), O₂ = Bates(1984), He = Cuthbertson(1936),
#     King 보정 포함, σ 는 STP Loschmidt N₀ 기준으로 정의 → α = σ·N(T,P).
# GUI(gui/worker.py)·진단 코드는 전부 core/physics 를 import 해 이미 정상이었고,
# 오직 이 tools 사본만 동기화가 안 돼 r_batch_calculator·r_trend_monitor 경로가
# 틀렸다. 사본을 삭제하고 정본을 import 해 *중복 자체*(드리프트의 원인)를 없앤다.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from core.physics import RayleighPhysics  # noqa: E402,F401  (re-export for callers)

# ─────────────────────────────────────────────────────────────────────────────
# Reflectance Calculator (Engine)
# ─────────────────────────────────────────────────────────────────────────────

class ReflectanceCalculator:
    def __init__(self, cavity_len: float = 51.8, rl_factor: float = 0.933):
        self.cavity_len = cavity_len
        self.rl_factor = rl_factor
        self.za_spectra = []
        self.he_spectra = []
        self.quality_ok = True
        self.valid_fraction = 0.0

    def add_za_spectrum(self, counts: np.ndarray, temp_c: float, press_mbar: float):
        self.za_spectra.append((counts, temp_c, press_mbar))

    def add_he_spectrum(self, counts: np.ndarray, temp_c: float, press_mbar: float):
        self.he_spectra.append((counts, temp_c, press_mbar))

    def _average_spectra(self, spectra: list):
        if not spectra:
            return None, 25.0, 1013.25
        arr = np.array([s[0] for s in spectra])
        mean_cnt = np.mean(arr, axis=0)
        mean_t = float(np.mean([s[1] for s in spectra]))
        mean_p = float(np.mean([s[2] for s in spectra]))
        return mean_cnt, mean_t, mean_p

    def calculate(self, wave_nm: np.ndarray = None, min_valid_fraction: float = 0.3, roi_min: float = 430.0, roi_max: float = 470.0):
        """
        [반환값] 
        wave_nm: 파장 배열
        r_curve_raw: 원본 R 배열 (노이즈 포함 점 데이터용)
        r_curve_fitted: 5차 다항식 피팅된 매끄러운 R 배열 (최종 계산용)
        omr_d_fitted: 피팅된 R 기반 (1-R)/d 결과
        """
        i_za, t_za, p_za = self._average_spectra(self.za_spectra)
        i_he, t_he, p_he = self._average_spectra(self.he_spectra)

        if i_za is None or i_he is None:
            raise RuntimeError("Missing ZA or He spectra.")

        n_pix = len(i_za)
        if wave_nm is None:
            wave_nm = np.linspace(400.0, 500.0, n_pix)

        # 1. 기체 산란 계수 계산
        alpha_za = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_za, p_za, "zero_air")
        alpha_he = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_he, p_he, "helium")

        # 0으로 나누기 방지
        i_he_safe = np.where(np.abs(i_he) > 1.0, i_he, 1.0)
        
        # 2. 광량비(Ratio) 계산 및 이동 평균(Moving Average) 적용
        ratio_raw = i_za / i_he_safe
        # 🌟 [MATLAB 로직 이식] runmean 10포인트로 고주파 노이즈 사전 제거
        box_pts = 10
        box = np.ones(box_pts) / box_pts
        ratio_smooth = np.convolve(ratio_raw, box, mode='same')

        # 3. 원본(Raw) OMR_d 및 R 값 계산
        with np.errstate(divide="ignore", invalid="ignore"):
            omr_d_raw = self.rl_factor * (ratio_smooth * alpha_za - alpha_he) / (1.0 - ratio_smooth)
        
        r_curve_raw = np.clip(1.0 - omr_d_raw * self.cavity_len, 0.0, 1.0)

        # 4. 🌟 [MATLAB 로직 이식] 채널별 동적 ROI 설정 및 품질 체크
        # 지정된 파장(roi_min ~ roi_max) 구간만 평가 및 피팅에 사용
        roi_mask = (wave_nm >= roi_min) & (wave_nm <= roi_max)
        
        # R값이 물리적으로 정상인(0.9 이상) 픽셀만 골라냄
        valid_mask = roi_mask & np.isfinite(r_curve_raw) & (r_curve_raw > 0.90)
        
        n_roi_pixels = np.sum(roi_mask)
        if n_roi_pixels > 0:
            self.valid_fraction = float(np.sum(valid_mask)) / n_roi_pixels
        else:
            self.valid_fraction = 0.0

        if self.valid_fraction < min_valid_fraction:
            self.quality_ok = False
            # 에러 메시지에 현재 ROI 대역을 표시
            raise RuntimeError(f"R-curve quality check failed. Valid inside ROI ({roi_min}-{roi_max}nm): {self.valid_fraction * 100:.0f}%")
        else:
            self.quality_ok = True

        # 5. 🌟 [MATLAB 로직 이식] 5차 다항식 피팅 (5th-order Polynomial)
        r_curve_fitted = r_curve_raw.copy()
        
        # 피팅할 유효 데이터가 충분할 경우에만 피팅 수행
        if np.sum(valid_mask) > 6:
            # ROI 내의 유효한 데이터만 가지고 5차 함수 계수(coeffs) 산출
            coeffs = np.polyfit(wave_nm[valid_mask], r_curve_raw[valid_mask], 5)
            # 산출된 5차 함수를 이용해 전체 파장에 대한 매끄러운 곡선 생성
            r_curve_fitted = np.polyval(coeffs, wave_nm)
            # 물리적 한계 초과 방지
            r_curve_fitted = np.clip(r_curve_fitted, 0.0, 1.0)

        # 6. 최종적으로 가스 흡수 계산에 쓸 피팅된 OMR_d 도출
        omr_d_fitted = (1.0 - r_curve_fitted) / self.cavity_len

        return wave_nm, r_curve_raw, r_curve_fitted, omr_d_fitted