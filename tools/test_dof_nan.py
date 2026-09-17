"""자유도 n−p ≤ 0 일 때 σ̂²·오차가 NaN인지 (사양 A8-1). 합성, ~1초.

왜: 예전 분모는 `max(n−p, 1)`이라 과소결정 상태에서도 **유한한 숫자**가 나왔다.
그건 "오차가 이만큼"이라는 주장이고, 읽는 쪽은 그걸 '작은 오차'로 받는다.
n−p ≤ 0 이면 σ̂²는 큰 게 아니라 **정의되지 않는다**.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.doas_fit import DoasFitter
from tools.test_varpro_jacobian import FIXED_E_F, make_engine, ref_props

_n_pass = _n_fail = 0


def check(label, ok, detail=""):
    global _n_pass, _n_fail
    if ok:
        _n_pass += 1
        print(f"  PASS  {label}")
    else:
        _n_fail += 1
        print(f"  FAIL  {label}  {detail}")


def fit_on(n_pix, poly_order):
    """픽셀 수를 줄여 n−p 를 원하는 부호로 만든다. p = 비선형 + 선형열 전부."""
    eng = make_engine()
    fitter = DoasFitter(eng)
    px = np.arange(900, 900 + n_pix, dtype=float)
    c0 = px[len(px) // 2]
    y = np.zeros(n_pix)
    for amp, name in zip((0.15, 0.04, 0.09), eng.gas_list):
        y = y + amp * eng.interpolators[name](px) / eng.scaling_factors[name]
    y = y + 0.01 + np.random.default_rng(3).normal(0, 2e-4, n_pix)
    props = ref_props(eng.gas_list)
    act, fx, lk, t0, lb, ub = fitter.setup_fit_parameters(props, 0.0, [0.0], 0.5)
    out, d = fitter.execute_varpro_fit(
        px, y, np.ones(n_pix), act, fx, lk, t0, lb, ub, poly_order, FIXED_E_F,
        c0, 1.0, props, 25.0, 0.0, False, allow_negative_gas=True,
        return_diagnostics=True)
    return out[6], d       # (기체별 perr, 진단)


def main():
    print("[1] n > p — 오차는 유한하고 underdetermined 아님")
    perr, d = fit_on(n_pix=400, poly_order=3)
    check("dof > 0", d["dof"] > 0, str(d["dof"]))
    check("underdetermined False", d["underdetermined"] is False)
    check("perr 유한", np.all(np.isfinite(perr)), str(perr))

    print("[2] n ≤ p — 오차 NaN, underdetermined True")
    # 선형열 = 기체3 + poly(deg+1) + etalon2, 비선형 = shift/squeeze 2개.
    # n_pix=9, poly_order=3 → p = 2 + 3 + 4 + 2 = 11 > 9.
    perr, d = fit_on(n_pix=9, poly_order=3)
    check("dof ≤ 0", d["dof"] <= 0, str(d["dof"]))
    check("underdetermined True", d["underdetermined"] is True)
    check("perr 전부 NaN (0이 아니다)", np.all(np.isnan(perr)), str(perr))

    print(f"\ndof/NaN tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
