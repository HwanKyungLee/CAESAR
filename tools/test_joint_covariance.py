"""결합 공분산(θ 불확도 포함) 불변식 — 사양 A8-2. 합성 + 실측 레퍼런스, ~10초.

무엇을 지키는가
---------------
반환 튜플의 `c_perr`는 shift/squeeze를 최적값에 **고정한** 설계행렬에서 나온
조건부 Cov(c | θ=θ̂)다. VarPro는 θ와 c를 분리해 풀지만 불확도는 분리되지
않는다 — shift가 흔들리면 농도도 흔들린다.

1. 결합 ≥ 조건부. Schur 보수라 **수학적으로 보장**되어야 한다. 이게 깨지면
   결합 야코비안을 잘못 세운 것이다(예: GP 야코비안을 써서 c를 두 번 세는 경우).
2. 비선형 파라미터가 하나도 없으면(모두 Fix) 결합 == 조건부.
3. 못 구하면 0이 아니라 NaN.
4. 실측 레퍼런스에서 증가율(결합/조건부)을 **보고**한다 — 논문에 쓸 숫자다.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.doas_fit import DoasFitter
from tools.test_varpro_jacobian import (FIXED_E_F, PIXEL_IDX, POLY_ORDER,
                                        make_engine, ref_props, synth_scan)

_n_pass = _n_fail = 0


def check(label, ok, detail=""):
    global _n_pass, _n_fail
    if ok:
        _n_pass += 1
        print(f"  PASS  {label}")
    else:
        _n_fail += 1
        print(f"  FAIL  {label}  {detail}")


def run(props=None, noise=2e-4):
    eng = make_engine()
    fitter = DoasFitter(eng)
    y = synth_scan(eng, shift=0.4, squeeze=1.003)
    y = y + np.random.default_rng(11).normal(0, noise, len(y))
    props = props or ref_props(eng.gas_list)
    act, fx, lk, t0, lb, ub = fitter.setup_fit_parameters(props, 0.0, [0.0], 0.5)
    c0 = PIXEL_IDX[len(PIXEL_IDX) // 2]
    out, diag = fitter.execute_varpro_fit(
        PIXEL_IDX, y, np.ones(len(y)), act, fx, lk, t0, lb, ub, POLY_ORDER,
        FIXED_E_F, c0, 1.0, props, 25.0, 0.0, False, allow_negative_gas=True,
        return_diagnostics=True)
    return eng, out[6], np.asarray(diag["perr_joint"], dtype=float)


def all_fixed_props(gases):
    return {g: {"sh_mode": "Fix", "sh_val": "0.0", "sq_mode": "Fix",
                "sq_val": "1.0", "t_ref": 25.0, "t_coeff": 0.0} for g in gases}


def test_joint_at_least_conditional():
    print("[1] 결합 >= 조건부 (Schur 보수 — 수학적으로 보장)")
    eng, cond, joint = run()
    ratios = []
    for i, name in enumerate(eng.gas_list):
        check(f"{name}: joint >= cond",
              joint[i] >= cond[i] * (1 - 1e-9),
              f"cond={cond[i]:.6e} joint={joint[i]:.6e}")
        if cond[i] > 0:
            ratios.append(joint[i] / cond[i])
    print(f"        증가율 joint/cond = "
          f"{', '.join(f'{g}:{r:.3f}' for g, r in zip(eng.gas_list, ratios))}")


def test_no_nonlinear_params_means_equal():
    print("[2] 비선형 파라미터가 없으면 결합 == 조건부")
    eng, cond, joint = run(props=all_fixed_props(("NO2", "CHOCHO", "H2O")))
    check("active_vars 없음 → perr_joint NaN (계산 대상 아님)",
          np.all(np.isnan(joint)), str(joint))
    check("조건부는 여전히 유한", np.all(np.isfinite(cond)), str(cond))


def test_missing_derivatives_gives_nan():
    print("[3] 도함수가 없으면 0이 아니라 NaN")
    eng = make_engine()
    eng.ref_derivatives = {}          # 해석 도함수 제거
    fitter = DoasFitter(eng)
    y = synth_scan(eng)
    props = ref_props(eng.gas_list)
    act, fx, lk, t0, lb, ub = fitter.setup_fit_parameters(props, 0.0, [0.0], 0.5)
    c0 = PIXEL_IDX[len(PIXEL_IDX) // 2]
    _, diag = fitter.execute_varpro_fit(
        PIXEL_IDX, y, np.ones(len(y)), act, fx, lk, t0, lb, ub, POLY_ORDER,
        FIXED_E_F, c0, 1.0, props, 25.0, 0.0, False, allow_negative_gas=True,
        return_diagnostics=True)
    check("perr_joint 전부 NaN",
          np.all(np.isnan(np.asarray(diag["perr_joint"], dtype=float))),
          str(diag["perr_joint"]))


def test_on_real_references():
    """실측 레퍼런스로 증가율을 보고한다. 픽스처가 없으면 건너뛴다."""
    print("[4] 실측 레퍼런스 — 증가율 보고")
    import tools.test_varpro_closure as CL
    refdir = CL.find_refdir()
    if refdir is None:
        print("        SKIP (레퍼런스 픽스처 없음)")
        return
    gases = ("NO2", "CHOCHO", "H2O")
    eng, wave = CL.build_engine(refdir, gases)
    px = np.where((wave >= CL.FIT_NM[0]) & (wave <= CL.FIT_NM[1]))[0]
    vp = px.astype(float)
    center = vp[len(vp) // 2]
    fitter = DoasFitter(eng)
    props = CL.props_for(gases)
    rng = np.random.default_rng(20260917)
    scds = CL.companion_scds(eng, gases, {"NO2": 1e12})
    alpha = CL.synthesize(eng, vp, center, scds, -1.5, CL.TRUE_SQUEEZE,
                          CL.NOISE_MEASURED, rng)
    # 운영 정규화 재현 — 없으면 least_squares가 θ0에서 끝난다(closure test 주석 참고)
    avg = float(np.mean(alpha))
    scale = 10.0 ** (-np.floor(np.log10(abs(avg)))) if abs(avg) < 1e-4 else 1.0
    act, fx, lk, t0, lb, ub = fitter.setup_fit_parameters(
        props, 0.0, [0.0, 1.0], step_limit=20.0)
    out, diag = fitter.execute_varpro_fit(
        vp, alpha * scale, np.ones(len(vp)), act, fx, lk, t0, lb, ub,
        CL.POLY_ORDER, 0.12, center, 1.0, props, 25.0, 0.0, False,
        allow_negative_gas=True, return_diagnostics=True)
    cond = np.asarray(out[6], float)
    joint = np.asarray(diag["perr_joint"], float)
    for i, name in enumerate(eng.gas_list):
        check(f"{name}: joint >= cond", joint[i] >= cond[i] * (1 - 1e-9),
              f"cond={cond[i]:.6e} joint={joint[i]:.6e}")
    print("        증가율 joint/cond = " + ", ".join(
        f"{g}:{joint[i] / cond[i]:.3f}" for i, g in enumerate(eng.gas_list)
        if cond[i] > 0))


def main():
    for t in (test_joint_at_least_conditional,
              test_no_nonlinear_params_means_equal,
              test_missing_derivatives_gives_nan,
              test_on_real_references):
        t()
    print(f"\njoint covariance tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
