"""oculus/monitors/conc_monitor.py 단위테스트.

실데이터 재구성: `Output/alpha/60s/cold`의 실제(이미 검증된) alpha 배열을
`spectrum = I0 * exp(-alpha)`로 raw 광량 도메인으로 역변환해서 넣는다 —
그러면 ConcMonitor 내부의 `-log(spectrum/I0)`가 그 alpha를 정확히 복원하고,
이 세션 내내 검증해 온 진짜 FitSet(cold)로 실제 core.param_optimizer.fit_scan이
돈다(합성 물리 아님, 진짜 파이프라인 배관만 새 코드).

커버:
  1) I0 버퍼링(za_inject 윈도우 완결) + throttle
  2) 첫 핏 후 seed narrowing(Center 모드로 전환)
  3) 경보 판정(_classify) — OK/물리불가(P1)/rms낮음(P1)/스파이크(P2)/평탄선(P2)
  4) 연속 실패 → P0 격상
  5) pick_fitset_channel — wl_dir 매칭

사용: python oculus/monitors/test_conc_monitor.py → 전부 PASS면 exit 0
"""
import glob
import json
import os
import sys
import warnings

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from oculus.alert_engine import OK, P0, P1, P2
from oculus.monitors.conc_monitor import ConcMonitor, pick_fitset_channel
from oculus.profile import ConcentrationConfig
from tools import optimize_params as OP
from tools.residual_compare import load_alpha

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


def _real_cold_alpha():
    files = sorted(glob.glob(
        r"C:\Doasis_Work\Output\alpha\60s\cold\2026-05-26\*_cold_alpha_trace.dat"))
    if not files:
        return None
    return load_alpha(files[0])   # (wave, alpha, T, P)


def _make_monitor(**cfg_overrides):
    scen = json.load(open(OP.FITSET, encoding="utf-8"))
    fit_ch = pick_fitset_channel(scen, "cold")
    cfg_kwargs = dict(fitset_path=OP.FITSET, wl_dir="cold", target="NO2",
                      allow_negative_gas=False,
                      throttle_sec=0.0, seed_narrow_px=2.0,
                      conc_min_ppb=-20, conc_max_ppb=50, spike_ppb=20,
                      rms_sig_alarm=0.15, flatline_n=5)
    cfg_kwargs.update(cfg_overrides)
    cfg = ConcentrationConfig(**cfg_kwargs)
    return ConcMonitor(fit_ch, cfg)


def test_pick_fitset_channel():
    print("[5] pick_fitset_channel — wl_dir 매칭")
    scen = json.load(open(OP.FITSET, encoding="utf-8"))
    for wl_dir in ("cold", "roi1", "roi2"):
        ch = pick_fitset_channel(scen, wl_dir)
        check(f"'{wl_dir}' 매칭됨", wl_dir in str(ch.get("wl_path", "")).replace("\\", "/"))
    try:
        pick_fitset_channel(scen, "roi99")
        check("없는 wl_dir는 예외", False, "예외 안 남")
    except ValueError:
        check("없는 wl_dir는 예외", True)


def test_gas_policy_source_and_legacy_migration():
    print("[6] gas policy source + legacy migration")
    scen = json.load(open(OP.FITSET, encoding="utf-8"))
    legacy = dict(pick_fitset_channel(scen, "cold"))
    legacy.pop("allow_negative_gas", None)
    cfg = ConcentrationConfig(fitset_path=OP.FITSET, wl_dir="cold",
                              allow_negative_gas=False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cm = ConcMonitor(legacy, cfg)
    check("legacy FitSet은 profile fallback을 경고", bool(caught))
    check("legacy provenance 기록", cm.gas_policy_provenance.startswith("legacy"))

    current = dict(legacy, allow_negative_gas=False)
    cm = ConcMonitor(current, cfg)
    check("현재 FitSet이 정책 단일 출처", cm.gas_policy_provenance == "FitSet")
    try:
        ConcMonitor(dict(current, allow_negative_gas=True), cfg)
        check("FitSet/profile 불일치 거부", False)
    except ValueError:
        check("FitSet/profile 불일치 거부", True)


def test_i0_buffer_and_fit_and_throttle():
    print("[1]+[2] I0 버퍼링 + throttle + seed narrowing")
    real = _real_cold_alpha()
    if real is None:
        print("  SKIP  실측 알파 없음(로컬 데이터 없음) — 이 블록 건너뜀")
        return
    wave, alpha_real, T, P = real
    i0 = np.full_like(wave, 40000.0)
    spectrum = i0 * np.exp(-alpha_real)   # -log(spectrum/i0) == alpha_real로 복원됨

    cm = _make_monitor(throttle_sec=0.0)
    r_za = cm.observe("za_inject", i0, T, P)
    check("za_inject 중엔 결과 없음", r_za is None)
    check("I0 아직 없음(za 윈도우 안 끝남)", cm._i0 is None)

    r0 = cm.observe("sampling", spectrum, T, P)
    check("za 윈도우 종료 후 I0 채워짐", cm._i0 is not None)
    check("첫 sampling 행에서 핏 실행됨", r0 is not None)
    status, msg, metrics = r0
    check("농도값이 유한", np.isfinite(metrics["conc_ppb"]), metrics)
    check("cold 콘텍스트에서 그럴듯한 농도(-20~50ppb)",
          -20 <= metrics["conc_ppb"] <= 50, metrics["conc_ppb"])
    check("첫 핏 후 seed(_last_shift) 저장됨", cm._last_shift is not None)
    rp2 = cm._seeded_ref_props()
    check("두번째부턴 Center 모드로 좁힘", rp2["NO2"]["sh_mode"] == "Center", rp2["NO2"])

    # throttle=0이라 즉시 재핏 가능 — 되는지만 확인(느려도 됨, 값 검증은 위에서 끝)
    r1 = cm.observe("sampling", spectrum, T, P)
    check("throttle=0이면 바로 재핏", r1 is not None)


def test_throttle_blocks_immediate_refit():
    print("[1] throttle_sec 큰 값이면 바로 다음 행은 스킵")
    real = _real_cold_alpha()
    if real is None:
        print("  SKIP  실측 알파 없음")
        return
    wave, alpha_real, T, P = real
    i0 = np.full_like(wave, 40000.0)
    spectrum = i0 * np.exp(-alpha_real)
    cm = _make_monitor(throttle_sec=9999.0)
    cm.observe("za_inject", i0, T, P)
    r0 = cm.observe("sampling", spectrum, T, P)
    check("첫 핏은 즉시 실행", r0 is not None)
    r1 = cm.observe("sampling", spectrum, T, P)
    check("throttle 안 지났으면 None", r1 is None)


def test_classify():
    print("[3] _classify — 경보 등급")
    cm = _make_monitor(conc_min_ppb=-20, conc_max_ppb=50, spike_ppb=20,
                       rms_sig_alarm=0.15, flatline_n=3)

    def _res(conc, rms_sig=0.05, perr_rel=0.05, rms=3e-9):
        return dict(conc=conc, rms_sig=rms_sig, perr_rel=perr_rel, rms=rms,
                    conc_all={"NO2": conc})

    status, msg, m = cm._classify(_res(3.5))
    check("정상 범위 → OK", status == OK, f"{status}: {msg}")

    status, msg, m = cm._classify(_res(80.0))
    check("너무 높음 → P1", status == P1, f"{status}: {msg}")

    cm2 = _make_monitor(conc_min_ppb=-20, conc_max_ppb=50, rms_sig_alarm=0.15)
    status, msg, m = cm2._classify(_res(-30.0))
    check("너무 낮음 → P1", status == P1, f"{status}: {msg}")

    cm3 = _make_monitor(rms_sig_alarm=0.15)
    status, msg, m = cm3._classify(_res(3.0, rms_sig=0.30))
    check("rms/sig 높음 → P1", status == P1, f"{status}: {msg}")

    cm4 = _make_monitor(spike_ppb=5.0)
    cm4._classify(_res(3.0))            # 이력에 3.0 심음
    status, msg, m = cm4._classify(_res(30.0))
    check("직전 대비 급변 → P2", status == P2, f"{status}: {msg}")

    cm5 = _make_monitor(flatline_n=3)
    cm5._classify(_res(4.0))
    cm5._classify(_res(4.0))
    status, msg, m = cm5._classify(_res(4.0))
    check("N회 연속 동일값 → 평탄선 P2", status == P2, f"{status}: {msg}")

    # rms_alarm — 저농도 채널용 절대 잔차 문턱(rms_sig는 신호가 작으면 폭발해서 못 씀).
    cm6 = _make_monitor(rms_sig_alarm=None, rms_alarm=5e-8)
    check("rms 정상(3e-9) → OK", cm6._classify(_res(1.0, rms=3e-9))[0] == OK)
    st6, msg6, _ = cm6._classify(_res(1.0, rms=2e-7))
    check("rms 큼(2e-7) → P1", st6 == P1, f"{st6}: {msg6}")
    # 실측 근거: cold 748스캔에서 rms_sig>0.15가 56%에 걸렸고 그 대부분이 저농도(중앙
    # 1.1ppb)였다 — 같은 스캔들이 rms 기준으론 정상으로 남아야 한다.
    cm7 = _make_monitor(rms_sig_alarm=None, rms_alarm=5e-8)
    check("저농도+높은 rms_sig라도 rms 정상이면 OK",
          cm7._classify(_res(0.5, rms_sig=0.67, rms=3.5e-9))[0] == OK)

    status, msg, m = cm5._classify(dict(conc=float("nan"), rms_sig=0.05, perr_rel=0.05,
                                        rms=3e-9, conc_all={}))
    check("농도 NaN → P1", status == P1, f"{status}: {msg}")


def test_fail_streak_to_p0():
    print("[4] 연속 실패 → P0")
    cm = _make_monitor(throttle_sec=0.0)
    bad_i0 = np.zeros(2048)          # 0으로 나누기 → alpha가 전부 inf/NaN
    bad_spec = np.full(2048, 1.0)
    r_za = cm.observe("za_inject", bad_i0, 25.0, 1013.25)
    r1 = cm.observe("sampling", bad_spec, 25.0, 1013.25)
    check("1회 실패 → P1", r1[0] == P1, f"got {r1[0]}: {r1[1]}")
    r2 = cm.observe("sampling", bad_spec, 25.0, 1013.25)
    check("2회 연속 실패 → 아직 P1", r2[0] == P1, f"got {r2[0]}: {r2[1]}")
    r3 = cm.observe("sampling", bad_spec, 25.0, 1013.25)
    check("3회 연속 실패 → P0", r3[0] == P0, f"got {r3[0]}: {r3[1]}")


def main():
    for t in (test_pick_fitset_channel, test_gas_policy_source_and_legacy_migration,
              test_i0_buffer_and_fit_and_throttle,
              test_throttle_blocks_immediate_refit, test_classify, test_fail_streak_to_p0):
        t()
    print(f"\nconc_monitor tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
