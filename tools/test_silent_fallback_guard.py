"""tools/test_silent_fallback_guard.py — core가 **조용히 다른 값으로 갈아타지** 않는가.

2026-09-15 except 감사에서 나온 것들을 고정한다. 공통 실패 모드는 하나다:
예외를 삼키고 하드코딩 기본값을 넣으면, 결과 파일에는 **선언한 세팅**이 기록되는데
실제로 돈 건 다른 세팅이라 "기록 = 재현"이 깨진다. 숫자가 조용히 틀리는 쪽이
빨간불로 멈추는 쪽보다 훨씬 비싸다.

지키는 것
  1. shift/squeeze 정책 문자열이 깨지면 **셋업 단계에서 예외**로 멈춘다
     (Center/Limit/Fix × sh/sq 5경로 전부). 예전엔 각각 0±3px / ±3px / 0 /
     ±0.01 / 1.0 으로 조용히 갈아탔다.
  2. 멀쩡한 값은 예전 그대로 동작한다(회귀 방지).
  3. `validate_fitset()`이 Fix 모드 파싱 불가도 잡는다(감사 전에는 구멍이었다).
  4. 공분산 계산이 실패하면 perr는 0이 아니라 **NaN**이다.
     0이면 결과 파일에 Error=0 · MDL=0(=검출한계 0)이 박히고, fit_optimizer의
     1순위 순위축 perr_rel=0이 되어 **그 세팅이 최적으로 뽑힌다**.

    python tools/test_silent_fallback_guard.py
"""
from __future__ import annotations

import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import core.fit_physics as fp                            # noqa: E402
from core.data_io import (read_scans_via_dataio,          # noqa: E402
                          scans_worker_for_parallel)
from core.doas_fit import DoasFitter                      # noqa: E402
from core.fitset_builder import validate_fitset           # noqa: E402
from tools import test_varpro_jacobian as vj              # noqa: E402  (합성 엔진 재사용)

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


class _StubEngine:
    """setup_fit_parameters는 engine.gas_list만 본다."""
    def __init__(self, gases):
        self.gas_list = list(gases)


def _setup(props):
    fitter = DoasFitter(_StubEngine(list(props)))
    return fitter.setup_fit_parameters(props, 0.0, current_params=[0.0], step_limit=0.5)


def _raises(props, needle):
    try:
        _setup(props)
    except ValueError as e:
        return needle in str(e)
    except Exception:
        return False
    return False


def test_broken_policy_raises():
    """5개 경로 전부 — 예전에 조용히 갈아타던 기본값이 뭐였는지 함께 적는다."""
    cases = [
        ("sh Center", {"sh_mode": "Center", "sh_val": "쓰레기",
                       "sq_mode": "Fix", "sq_val": "1.0"}, "sh_val"),
        ("sh Limit",  {"sh_mode": "Limit", "sh_val": "-3.0",          # 값 1개 = 범위 아님
                       "sq_mode": "Fix", "sq_val": "1.0"}, "sh_val"),
        ("sh Fix",    {"sh_mode": "Fix", "sh_val": "",
                       "sq_mode": "Fix", "sq_val": "1.0"}, "sh_val"),
        ("sq Limit",  {"sh_mode": "Fix", "sh_val": "0.0",
                       "sq_mode": "Limit", "sq_val": "0.01"}, "sq_val"),
        ("sq Fix",    {"sh_mode": "Fix", "sh_val": "0.0",
                       "sq_mode": "Fix", "sq_val": None}, "sq_val"),
    ]
    for label, props, needle in cases:
        check(f"{label} 깨진 값 → 예외", _raises({"NO2": props}, needle))
        check(f"{label} 메시지에 가스 이름", _raises({"NO2": props}, "NO2"))


def test_valid_policy_unchanged():
    props = {"NO2": {"sh_mode": "Center", "sh_val": "-5.25, 1.0",
                     "sq_mode": "Limit", "sq_val": "-0.005, 0.005"}}
    active, fixed, linked, theta0, lb, ub = _setup(props)
    check("Center 유효값 활성화", active == ["NO2_sh", "NO2_sq"], active)
    # 창 = 선언 중심 ±반폭 ∩ 앵커±step_limit. 첫 스캔 앵커는 중심(-5.25).
    check("Center 하한", np.isclose(lb[0], -5.75), lb)
    check("Center 상한", np.isclose(ub[0], -4.75), ub)
    check("sq Limit 하한", np.isclose(lb[1], 0.995), lb)
    check("sq Limit 상한", np.isclose(ub[1], 1.005), ub)

    fx = {"NO2": {"sh_mode": "Fix", "sh_val": "-0.5", "sq_mode": "Fix", "sq_val": "1.0"}}
    _a, fixed, _l, _t, _lb, _ub = _setup(fx)
    check("sh Fix 절대값 보존", np.isclose(fixed["NO2_sh"], -0.5), fixed)
    check("sq Fix 값 보존", np.isclose(fixed["NO2_sq"], 1.0), fixed)


def test_validate_fitset_catches_fix():
    cfg = {"f_min": 400, "f_max": 900, "step_limit": 0.5,
           "ref_props": {"NO2": {"sh_mode": "Fix", "sh_val": "쓰레기",
                                 "sq_mode": "Fix", "sq_val": "또쓰레기"}}}
    probs = validate_fitset(cfg, target="NO2")
    check("validate_fitset: sh Fix 파싱불가 보고",
          any("sh_val(Fix)" in p for p in probs), probs)
    check("validate_fitset: sq Fix 파싱불가 보고",
          any("sq_val(Fix)" in p for p in probs), probs)

    ok = {"f_min": 400, "f_max": 900, "step_limit": 0.5,
          "ref_props": {"NO2": {"sh_mode": "Fix", "sh_val": "-0.5",
                                "sq_mode": "Fix", "sq_val": "1.0"}}}
    check("멀쩡한 Fix는 문제 없음", validate_fitset(ok, target="NO2") == [], 
          validate_fitset(ok, target="NO2"))


def test_covariance_failure_gives_nan_not_zero():
    """공분산이 터지면 perr=NaN. 0이면 Error=0·MDL=0·perr_rel=0(=최적)이 된다."""
    eng = vj.make_engine()
    y = vj.synth_scan(eng)
    W = np.ones(len(vj.PIXEL_IDX))

    good = vj.run_fit(eng, y, W)
    perr_good = np.asarray(good[6], dtype=float)
    check("정상 경로 perr는 유한", np.all(np.isfinite(perr_good)), perr_good)

    import core.doas_fit as df
    orig = np.linalg.pinv
    np.linalg.pinv = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("공분산 실패 주입"))
    try:
        bad = vj.run_fit(eng, y, W)
    finally:
        np.linalg.pinv = orig
    perr_bad = np.asarray(bad[6], dtype=float)
    check("공분산 실패 → perr 전부 NaN", np.all(np.isnan(perr_bad)), perr_bad)
    check("공분산 실패 → perr가 0이 아님", not np.any(perr_bad == 0.0), perr_bad)
    check("농도 자체는 그대로 나온다", np.all(np.isfinite(np.asarray(bad[2], dtype=float))))


MISSING = "C:/__augur_no_such_dir__/absent.dat"


def test_unreadable_file_is_not_no_scans():
    """'못 읽었다'와 'ZA/He 블록이 없다'는 다른 사건이다."""
    try:
        read_scans_via_dataio(MISSING, 1, 1000.0)
        ok = False
    except RuntimeError:
        ok = True
    except Exception:
        ok = False
    check("읽을 수 없는 파일 → RuntimeError", ok)

    _fp, za, he = scans_worker_for_parallel((MISSING, 1, 1000.0))
    check("병렬 워커는 (None, None)", za is None and he is None, (za, he))
    check("빈 리스트로 뭉개지 않는다", not (za == [] and he == []), (za, he))


def test_health_reports_dropped_scans():
    """핏이 터져 빠진 스캔 수를 반환 dict가 밝히는가."""
    eng = vj.make_engine()
    fitter = DoasFitter(eng)
    props = vj.ref_props(eng.gas_list)
    scans = [(None, None, 25.0, 1013.25) for _ in range(5)]

    calls = {"n": 0}
    real_coeffs = {g: 0.1 for g in eng.gas_list}

    def fake_fit_scan(*a, **k):
        calls["n"] += 1
        if calls["n"] % 2 == 0:               # 5개 중 2개(2번째·4번째) 실패
            raise RuntimeError("핏 실패 주입")
        return {"coeffs": dict(real_coeffs)}

    orig = fp.fit_scan
    fp.fit_scan = fake_fit_scan
    try:
        out = fp.fitted_amount_health(scans, eng, fitter, props, 0, 100, 3, 0.5,
                                      allow_negative_gas=True)
    finally:
        fp.fit_scan = orig

    check("n_requested = 넣어준 수", out.get("n_requested") == 5, out.get("n_requested"))
    check("n_failed = 터진 수", out.get("n_failed") == 2, out.get("n_failed"))
    check("n = 실제 쓰인 수", out.get("n") == 3, out.get("n"))
    check("표본 손실이 dict에 드러난다",
          out.get("n") + out.get("n_failed") == out.get("n_requested"), out)


def test_optimizer_shares_the_same_parser():
    """fit_optimizer도 같은 엄격 파서를 쓴다(±3.0 기본값 복귀 방지)."""
    import inspect
    import core.fit_optimizer as fo
    src = inspect.getsource(fo)
    check("fit_optimizer가 policy_floats를 쓴다", "policy_floats(" in src)
    check("±3.0 침묵 기본값이 남아있지 않다",
          "g_lb, g_ub = -3.0, 3.0" not in src)
    from core.doas_fit import policy_floats
    check("파서 단일 출처", fo.policy_floats is policy_floats)


def test_timestamp_has_no_mtime_fallback():
    """시각을 못 읽으면 None. mtime(=복사하면 조용히 틀리는 값)으로 때우지 않는다."""
    from core.data_io import DataIO
    import inspect
    src = inspect.getsource(DataIO.parse_row_timestamp)
    check("mtime 폴백 없음", "getmtime" not in src, src[-200:])

    # 날짜 없는 이름 + 읽을 수 없는 파일 → None (예외도, 가짜 시각도 아니다)
    ts = DataIO.parse_row_timestamp("C:/__augur_no_such_dir__/undated.dat", 0)
    check("읽을 수 없으면 None", ts is None, ts)


def test_residual_rho_does_not_default_to_zero():
    """ρ를 못 재면 멈춘다. 0.0은 '넓을수록 좋다' 편향을 되살리는 가장 관대한 값이다."""
    import core.window_designer as wd
    import inspect
    src = inspect.getsource(wd.residual_rho)
    check("0.0 기본값 없음", "else 0.0" not in src)

    eng = vj.make_engine()
    orig = np.linalg.lstsq
    np.linalg.lstsq = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("lstsq 실패 주입"))
    try:
        wd.residual_rho(eng, [np.zeros(vj.N_PIX)], [eng.gas_list[0]], 100, 300, 3)
        ok = False
    except RuntimeError as e:
        ok = "자기상관" in str(e)
    except Exception:
        ok = False
    finally:
        np.linalg.lstsq = orig
    check("전 스캔 실패 → RuntimeError", ok)


def main():
    for fn in (test_broken_policy_raises, test_valid_policy_unchanged,
               test_validate_fitset_catches_fix,
               test_covariance_failure_gives_nan_not_zero,
               test_unreadable_file_is_not_no_scans,
               test_health_reports_dropped_scans,
               test_optimizer_shares_the_same_parser,
               test_timestamp_has_no_mtime_fallback,
               test_residual_rho_does_not_default_to_zero):
        fn()
    print(f"silent fallback guard: {PASS} PASS · {FAIL} FAIL")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
