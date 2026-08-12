"""oculus/monitors/r_monitor.py 단위테스트 (합성 ZA/He 스펙트럼, 실제 Rayleigh 물리 사용).

합성 스펙트럼은 core.physics.RayleighPhysics로 정확한 alpha_za/alpha_he를 구한 뒤
그 식을 대수적으로 역산해 "목표 R"이 나오도록 I_za/I_he 비율을 만든다 — 그래서
tools.reflectance_calc.ReflectanceCalculator의 실제 품질게이트(contrast band)와
물리식을 통과하는 진짜 같은 입력이 된다.

커버:
  1) 윈도우 완결 감지 — za_inject/he_inject 버퍼링, role이 바뀌어야 계산 트리거
  2) 베이스라인 축적 중(history<3)엔 OK만
  3) 급락(alarm_drop 초과) → P1, 완만한 하락(warn_drop 초과) → P2
  4) wavecal 없음 → 실패 1회는 P1, 연속 3회면 P0
  5) contrast 붕괴(ZA≈He) → ReflectanceCalculator 품질게이트가 실제로 막고 P1/P0로 이어짐

사용: python oculus/monitors/test_r_monitor.py → 전부 PASS면 exit 0
"""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.physics import RayleighPhysics
from oculus.alert_engine import OK, P0, P1, P2
from oculus.monitors.r_monitor import RMonitor

_n_pass = 0
_n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


WAVE = np.linspace(430.0, 470.0, 400)
ROI = (438.0, 466.0)
CAVITY_LEN = 51.8
RL_FACTOR = 0.933


def _synthetic_za_he(target_R, T=25.0, P=1013.25, he_counts=40000.0):
    """R=target_R이 나오도록 역산된 I_za/I_he (ReflectanceCalculator 공식의 역함수)."""
    alpha_za = RayleighPhysics.get_alpha_rayleigh(WAVE, T, P, "zero_air")
    alpha_he = RayleighPhysics.get_alpha_rayleigh(WAVE, T, P, "helium")
    k = (1.0 - target_R) / (RL_FACTOR * CAVITY_LEN)
    ratio = (k + alpha_he) / (alpha_za + k)
    i_he = np.full_like(WAVE, he_counts)
    i_za = ratio * i_he
    return i_za, i_he


def _feed_cycle(rm, target_R):
    """za_inject 3행 → he_inject 3행 → 윈도우 종료(role 전이) 1행. 마지막 호출의 반환값을 낸다."""
    i_za, i_he = _synthetic_za_he(target_R)
    for _ in range(3):
        rm.observe("za_inject", i_za, 25.0, 1013.25)
    for _ in range(3):
        rm.observe("he_inject", i_he, 25.0, 1013.25)
    return rm.observe("sampling", i_he, 25.0, 1013.25)   # 윈도우 종료 트리거


def test_window_completion():
    print("[1] 윈도우 완결 감지 — za만으론 계산 안 함")
    rm = RMonitor(wave_nm=WAVE, cavity_len_cm=CAVITY_LEN, rl_factor=RL_FACTOR, roi_nm=ROI)
    i_za, _ = _synthetic_za_he(0.9999)
    r1 = rm.observe("za_inject", i_za, 25.0, 1013.25)
    check("za만 관측되면 None", r1 is None, f"got {r1}")
    r2 = rm.observe("sampling", i_za, 25.0, 1013.25)   # za 윈도우 종료, he 없어서 계산 안 됨
    check("he 없이 za만 끝나면 여전히 None", r2 is None, f"got {r2}")


def test_baseline_accumulation_and_ok():
    print("[2]+[3] 베이스라인 축적 + 안정 시 OK")
    rm = RMonitor(wave_nm=WAVE, cavity_len_cm=CAVITY_LEN, rl_factor=RL_FACTOR, roi_nm=ROI,
                  warn_drop=5e-4, alarm_drop=2e-3)
    r1 = _feed_cycle(rm, 0.9999)
    check("1번째: 계산됨", r1 is not None)
    check("1번째: OK(축적중)", r1[0] == OK, f"got {r1[0]}: {r1[1]}")

    r2 = _feed_cycle(rm, 0.9999)
    check("2번째: OK(축적중)", r2[0] == OK, f"got {r2[0]}: {r2[1]}")

    r3 = _feed_cycle(rm, 0.9999)
    check("3번째(기준선 확보, 변화없음): OK", r3[0] == OK, f"got {r3[0]}: {r3[1]}")
    check("R값이 목표에 근접", abs(r3[2]["R"] - 0.9999) < 1e-4, f"got {r3[2]['R']}")
    return rm


def test_drop_alarms():
    print("[3] 급락→P1 / 완만한 하락→P2")
    # ⚠️ R은 0.9999 근방에서 극도로 비선형(L_eff=d/(1-R))이라, "작은" 절대 하락도
    # He/ZA contrast를 빠르게 무너뜨린다(예: 0.9999→0.9989 은 contrast 0.10→0.01로
    # 붕괴해 품질게이트에 걸림 — 처음엔 이걸로 실패해서 잡았다). 그래서 여기 쓰는
    # 하락폭은 유효 contrast band([0.05,0.35]) 안에 머무르는 실제 있을 법한 크기로 골랐다.
    rm = RMonitor(wave_nm=WAVE, cavity_len_cm=CAVITY_LEN, rl_factor=RL_FACTOR, roi_nm=ROI,
                  warn_drop=3e-5, alarm_drop=1e-4)
    for _ in range(3):
        _feed_cycle(rm, 0.9999)   # 안정 기준선 확보
    r_alarm = _feed_cycle(rm, 0.9997)   # drop=2e-4 (contrast 여전히 유효밴드 안, 0.036)
    check("급락 → P1", r_alarm[0] == P1, f"got {r_alarm[0]}: {r_alarm[1]}")

    r_warn = _feed_cycle(rm, 0.99985)   # drop=5e-5 from 최초기준선(급락 이후도 median이라 안 흔들림)
    check("완만한 하락 → P2", r_warn[0] == P2, f"got {r_warn[0]}: {r_warn[1]}")


def test_failure_streak_to_p0():
    print("[4] wavecal 없음 → 1회 P1, 3회 연속 P0")
    rm = RMonitor(wave_nm=None, roi_nm=ROI)   # wavecal 미설정 시뮬레이션
    r1 = _feed_cycle(rm, 0.9999)
    check("1회 실패 → P1", r1[0] == P1, f"got {r1[0]}: {r1[1]}")
    r2 = _feed_cycle(rm, 0.9999)
    check("2회 연속 실패 → 아직 P1", r2[0] == P1, f"got {r2[0]}: {r2[1]}")
    r3 = _feed_cycle(rm, 0.9999)
    check("3회 연속 실패 → P0", r3[0] == P0, f"got {r3[0]}: {r3[1]}")


def test_quality_gate_blocks_bad_contrast():
    print("[5] ZA≈He(contrast 붕괴) → ReflectanceCalculator 품질게이트가 막음")
    rm = RMonitor(wave_nm=WAVE, cavity_len_cm=CAVITY_LEN, rl_factor=RL_FACTOR, roi_nm=ROI)
    bad = np.full_like(WAVE, 40000.0)   # I_za == I_he → contrast 0 (< MIN_HE_ZA_CONTRAST)
    for _ in range(3):
        rm.observe("za_inject", bad, 25.0, 1013.25)
    for _ in range(3):
        rm.observe("he_inject", bad, 25.0, 1013.25)
    r = rm.observe("sampling", bad, 25.0, 1013.25)
    check("품질게이트 실패 → P1(실패 1회)", r[0] == P1, f"got {r[0]}: {r[1]}")
    check("메시지에 실패 언급", "실패" in r[1], r[1])


def main():
    for t in (test_window_completion, test_baseline_accumulation_and_ok, test_drop_alarms,
              test_failure_streak_to_p0, test_quality_gate_blocks_bad_contrast):
        t()
    print(f"\nr_monitor tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
