"""STEP_LIMITED 종료 판정 불변식 — 합성 레퍼런스, 캠페인 데이터 불필요, ~2초.

무엇을 지키는가 (사양 A7)
--------------------------
`setup_fit_parameters`는 허용범위 `[global_lb, global_ub]`와 보폭 창
`anchor ± step_limit`의 **교집합**을 solver 상자로 준다. `least_squares`는 그 상자
안에서 수렴하므로, 최적점이 상자 밖이면 경계에 붙은 채 성공 코드를 돌려주고
`_aggregate_solver_termination`은 그걸 CONVERGED로 분류했다 — **보폭 제한 때문에
못 움직인 핏이 수렴으로 보고됐다.**

여기서 거는 것:
1. 보폭이 충분히 크면(창이 허용범위를 감싸면) STEP_LIMITED가 나오지 않는다.
2. 보폭이 참 shift보다 훨씬 작으면 STEP_LIMITED가 나온다.
3. 허용범위 자체가 참 shift를 못 담으면 STEP_LIMITED가 아니라 AT_BOUND다
   (보폭을 풀어도 해결되지 않는 상황이므로 원인이 다르다).
4. 우선순위 FAILED > MAX_NFEV > STEP_LIMITED > AT_BOUND > CONVERGED.
5. 허용오차는 **상대값**이다 — 스케일만 다른 같은 문제는 같은 판정을 받는다.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.doas_fit import (DoasFitter, _aggregate_solver_termination,
                           classify_theta_bounds)
from tools.test_varpro_jacobian import (FIXED_E_F, PIXEL_IDX, POLY_ORDER,
                                        make_engine, synth_scan)

_n_pass = _n_fail = 0
TRUE_SHIFT = 3.0          # 참 shift. 보폭 0.5로는 한 스캔에 도달 못 한다.


def check(label, ok, detail=""):
    global _n_pass, _n_fail
    if ok:
        _n_pass += 1
        print(f"  PASS  {label}")
    else:
        _n_fail += 1
        print(f"  FAIL  {label}  {detail}")


def props_for(sh_val="-6.0, 6.0"):
    """NO2만 shift 자유(Limit), 나머지는 Link. squeeze는 고정 — 이 테스트의 대상이 아니다."""
    gases = ["NO2", "CHOCHO", "H2O"]
    p = {gases[0]: {"sh_mode": "Limit", "sh_val": sh_val,
                    "sq_mode": "Fix", "sq_val": "1.0",
                    "t_ref": 25.0, "t_coeff": 0.0}}
    for g in gases[1:]:
        p[g] = {"sh_mode": "Link", "sh_val": gases[0], "sq_mode": "Link",
                "sq_val": gases[0], "t_ref": 25.0, "t_coeff": 0.0}
    return p


def fit_with(step_limit, sh_val="-6.0, 6.0"):
    """참 shift 3.0px인 합성 스캔을 주어진 보폭/허용범위로 핏 → 진단 dict."""
    eng = make_engine()
    fitter = DoasFitter(eng)
    y = synth_scan(eng, shift=TRUE_SHIFT, squeeze=1.0)
    props = props_for(sh_val)
    active, fixed, linked, t0, lb, ub, bmeta = fitter.setup_fit_parameters(
        props, 0.0, current_params=[0.0], step_limit=step_limit, return_bounds=True)
    c0 = PIXEL_IDX[len(PIXEL_IDX) // 2]
    _, diag = fitter.execute_varpro_fit(
        PIXEL_IDX, y, np.ones(len(y)), active, fixed, linked, t0, lb, ub,
        POLY_ORDER, FIXED_E_F, c0, 1.0, props, 25.0,
        tikhonov_lambda=0.0, use_robust=False, allow_negative_gas=True,
        return_diagnostics=True, bounds_meta=bmeta)
    return diag


def test_large_step_limit_is_not_step_limited():
    print("[1] 보폭이 허용범위를 감싸면 STEP_LIMITED가 안 나온다")
    d = fit_with(step_limit=100.0)
    st = d["solver_termination"]["status"]
    check("step_limit=100 → STEP_LIMITED 아님", st != "STEP_LIMITED", f"status={st}")
    check("경계 판정이 window를 지목하지 않음",
          all(h["source"] != "window" for h in d["theta_bound_hits"]),
          str(d["theta_bound_hits"]))


def test_small_step_limit_is_step_limited():
    print("[2] 보폭이 참 shift보다 작으면 STEP_LIMITED")
    for sl in (0.01, 0.5):
        d = fit_with(step_limit=sl)
        st = d["solver_termination"]["status"]
        check(f"step_limit={sl} → STEP_LIMITED", st == "STEP_LIMITED",
              f"status={st} hits={d['theta_bound_hits']}")


def test_global_bound_wins_over_window():
    print("[3] 허용범위가 참 shift를 못 담으면 AT_BOUND (보폭 문제가 아니다)")
    # 허용범위 [-6, 0.4]: 참 shift 3.0이 밖이라 상한 0.4에 붙는다. 보폭도 크게 줘서
    # 창이 허용범위를 감싸게 하면 남는 원인은 허용범위뿐이다.
    d = fit_with(step_limit=100.0, sh_val="-6.0, 0.4")
    st = d["solver_termination"]["status"]
    check("AT_BOUND", st == "AT_BOUND", f"status={st} hits={d['theta_bound_hits']}")
    check("source=global", all(h["source"] == "global" for h in d["theta_bound_hits"]),
          str(d["theta_bound_hits"]))


def test_priority_order():
    print("[4] 우선순위 FAILED > MAX_NFEV > STEP_LIMITED > AT_BOUND > CONVERGED")
    ok = [{"status": 2, "success": True, "nfev": 5}]
    fail = [{"status": -1, "success": False, "nfev": 5}]
    maxn = [{"status": 0, "success": False, "nfev": 1500}]
    check("성공코드 + STEP_LIMITED → STEP_LIMITED",
          _aggregate_solver_termination(ok, "STEP_LIMITED")["status"] == "STEP_LIMITED")
    check("성공코드 + AT_BOUND → AT_BOUND",
          _aggregate_solver_termination(ok, "AT_BOUND")["status"] == "AT_BOUND")
    check("FAILED가 STEP_LIMITED를 이긴다",
          _aggregate_solver_termination(fail, "STEP_LIMITED")["status"] == "FAILED")
    check("MAX_NFEV가 STEP_LIMITED를 이긴다",
          _aggregate_solver_termination(maxn, "STEP_LIMITED")["status"] == "MAX_NFEV")
    check("bound_state 없으면 종전과 동일",
          _aggregate_solver_termination(ok)["status"] == "CONVERGED")
    check("nfev/success 집계는 불변",
          _aggregate_solver_termination(ok, "AT_BOUND")["nfev"] == 5)


def test_tolerance_is_relative():
    print("[5] 허용오차는 상대값 — 스케일만 다른 같은 문제는 같은 판정")
    # shift 스케일(폭 1.0)과 squeeze 스케일(폭 0.02)로 같은 상대 위치에 놓인 해.
    # 절대 허용오차였다면 둘 중 하나만 걸린다.
    for span, glob in ((1.0, (-5.0, 5.0)), (0.02, (-0.1, 0.1))):
        lb, ub = 0.0, span
        bm = {"global_lb": [glob[0]], "global_ub": [glob[1]],
              "window_lb": [lb], "window_ub": [ub]}
        state, hits = classify_theta_bounds([ub - 1e-4 * span], [lb], [ub], bm)
        check(f"span={span} 상대 0.01% 안쪽 → STEP_LIMITED",
              state == "STEP_LIMITED", f"{state} {hits}")
        state2, _ = classify_theta_bounds([lb + 0.5 * span], [lb], [ub], bm)
        check(f"span={span} 한가운데 → CONVERGED", state2 == "CONVERGED", state2)
    check("bounds_meta=None이면 판정 없음",
          classify_theta_bounds([0.0], [-1.0], [1.0], None) == ("CONVERGED", []))


def test_degenerate_box_is_not_converged():
    print("[6] 교집합이 빈 경우(폭 2e-4 상자)는 CONVERGED가 아니다")
    # sh_val "-9,-1.5" + anchor 0 + step 0.5 → 창 [-0.5,0.5]와 허용범위가 안 겹친다.
    # setup_fit_parameters가 near=-1.5 둘레에 ±1e-4 상자를 준다. 해는 그 한가운데
    # 앉지만 최적화가 일어난 게 아니라 사실상 고정이다.
    d = fit_with(step_limit=0.5, sh_val="-9.0, -1.5")
    st = d["solver_termination"]["status"]
    hits = d["theta_bound_hits"]
    check("CONVERGED 아님", st != "CONVERGED", f"status={st} hits={hits}")
    check("degenerate 표시", any(h.get("degenerate") for h in hits), str(hits))


def main():
    for t in (test_large_step_limit_is_not_step_limited,
              test_small_step_limit_is_step_limited,
              test_global_bound_wins_over_window,
              test_priority_order,
              test_tolerance_is_relative,
              test_degenerate_box_is_not_converged):
        t()
    print(f"\nstep-limited termination tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
