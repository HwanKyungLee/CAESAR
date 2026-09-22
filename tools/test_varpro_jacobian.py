"""VarPro 선형/자코비안 경로 불변식 — 합성 레퍼런스, 캠페인 데이터 불필요, ~1초.

`diagnostics/varpro_speed_2026-09/validate_*.py`는 실캠페인 알파로 도는 **일회성
전/후 대조**다(기준 커밋을 `--before-ref`로 줘야 하고 캠페인 폴더가 있어야 한다).
이 파일은 그 스위트에서 **영속적인 불변식만** 뽑아 CI에서 매번 돌리는 축소판이다
(`diagnostics/alpha_pass2_parallel/` ↔ `tools/test_pass2_parallel.py`와 같은 짝).

무엇을 지키는가
---------------
1. `make_interp_spline(k=3)` == `interp1d(kind='cubic', fill_value="extrapolate")`
   **비트동일**(외삽 포함). `core/engine.py`가 이 동치를 전제로 도함수를 만든다 —
   scipy 업그레이드로 깨지면 도함수가 핏에 실제로 쓰이는 보간기와 달라져
   **자코비안이 조용히 틀린 값**을 낸다. 다른 어떤 테스트도 이걸 안 잡는다.
2. 해석적(Golub–Pereyra) 자코비안 == 유한차분. `_gas_dcolumns`·`jac_targets`·
   `keep_mask`·GP 식을 건드리면 걸린다.
3. W를 **벡터로** 주나 **밀집 대각행렬로** 주나 결과 비트동일(구 호출부 호환).
4. ±Neg OFF(기체 계수 하한 0)면 해석적 경로가 꺼지고 유한차분으로 떨어진다 —
   그 조건에선 투영이 미분 불가능이라 해석해가 성립하지 않는다.
5. 창 밖 기체(`gas_active=False`)의 계수는 정확히 0 (`keep_mask` 경로).
"""
import os
import sys

import numpy as np
from scipy.interpolate import interp1d, make_interp_spline
from scipy.optimize._numdiff import approx_derivative

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.doas_fit as df
from core.doas_fit import DoasFitter
from core.engine import UniversalEngine

_n_pass = _n_fail = 0
N_PIX = 2048
PIXEL_IDX = np.arange(700, 1300)
POLY_ORDER = 3
FIXED_E_F = 0.12


def check(label, ok, detail=""):
    global _n_pass, _n_fail
    if ok:
        _n_pass += 1
        print(f"  PASS  {label}")
    else:
        _n_fail += 1
        print(f"  FAIL  {label}  {detail}")


def make_engine(gases=("NO2", "CHOCHO", "H2O")):
    """서로 다른 합성 흡수단면 3종. 실제 파일이 없어도 되도록 add_reference를
    거치지 않고 _set_interpolator()만 쓴다 — 그 메서드가 바로 검증 대상이다."""
    rng = np.random.default_rng(20260915)
    eng = UniversalEngine()
    x = np.arange(N_PIX, dtype=float)
    for i, name in enumerate(gases):
        # 종마다 다른 모양(다른 스플라인) — Link여도 보간이 공유되지 않음을 반영
        arr = (np.sin(x / (37.0 + 11 * i)) * np.exp(-((x - 900 - 150 * i) / 400.0) ** 2)
               + 0.05 * rng.normal(0, 1, N_PIX))
        eng.raw_references[name] = arr
        eng._set_interpolator(name, arr)
        eng.gas_list.append(name)
        mx = float(np.max(np.abs(arr)))
        eng.scaling_factors[name] = mx if mx else 1.0
    return eng


def ref_props(gases, active_window=True):
    """NO2가 앵커(Limit), 나머지는 Link — 실제 Cold/Hot 프리셋과 같은 구조."""
    props = {gases[0]: {"sh_mode": "Limit", "sh_val": "-2.0, 2.0",
                        "sq_mode": "Limit", "sq_val": "-0.02, 0.02",
                        "t_ref": 25.0, "t_coeff": 0.0}}
    for g in gases[1:]:
        props[g] = {"sh_mode": "Link", "sh_val": gases[0], "sq_mode": "Link",
                    "sq_val": gases[0], "t_ref": 25.0, "t_coeff": 0.0}
    return props


def synth_scan(eng, shift=0.4, squeeze=1.003):
    c0 = PIXEL_IDX[len(PIXEL_IDX) // 2]
    px = (PIXEL_IDX - c0) * squeeze + c0 + shift
    y = 0.0
    for amp, name in zip((0.15, 0.04, 0.09), eng.gas_list):
        y = y + amp * eng.interpolators[name](px) / eng.scaling_factors[name]
    y = y + 0.01 + 3e-4 * (PIXEL_IDX - c0) / 100.0
    return y + np.random.default_rng(7).normal(0, 2e-4, len(PIXEL_IDX))


def run_fit(eng, y, W, allow_negative_gas=True, props=None):
    fitter = DoasFitter(eng)
    props = props or ref_props(eng.gas_list)
    active, fixed, linked, theta0, lb, ub = fitter.setup_fit_parameters(
        props, 0.0, current_params=[0.0], step_limit=0.5)
    c0 = PIXEL_IDX[len(PIXEL_IDX) // 2]
    return fitter.execute_varpro_fit(
        PIXEL_IDX, y, W, active, fixed, linked, theta0, lb, ub,
        POLY_ORDER, FIXED_E_F, c0, 1.0, props, 25.0,
        tikhonov_lambda=0.0, use_robust=False,
        allow_negative_gas=allow_negative_gas)


def test_spline_equivalence():
    print("[1] make_interp_spline(k=3) == interp1d(kind='cubic') — engine이 도함수를 만드는 근거")
    rng = np.random.default_rng(1)
    for trial in range(3):
        y = rng.normal(0, 1, N_PIX)
        x = np.arange(N_PIX, dtype=float)
        f = interp1d(x, y, kind="cubic", bounds_error=False, fill_value="extrapolate")
        s = make_interp_spline(x, y, k=3)
        xs = np.arange(700, 1300) + 0.317
        check(f"보간 비트동일 (trial {trial})", np.array_equal(f(xs), s(xs)),
              f"max|d|={np.max(np.abs(f(xs) - s(xs))):.3e}")
    xe = np.array([-4.5, -0.3, N_PIX - 0.4, N_PIX + 3.0])
    check("외삽 구간도 비트동일", np.array_equal(f(xe), s(xe)),
          f"max|d|={np.max(np.abs(f(xe) - s(xe))):.3e}")

    eng = make_engine()
    name = eng.gas_list[0]
    d = eng.ref_derivatives[name]
    fi = eng.interpolators[name]
    xs = np.arange(800, 1200) + 0.11
    h = 1e-5
    fd = (fi(xs + h) - fi(xs - h)) / (2 * h)
    rel = np.max(np.abs(d(xs).ravel() - fd)) / max(np.max(np.abs(fd)), 1e-300)
    check("engine.ref_derivatives가 그 보간기의 도함수", rel < 1e-6, f"rel={rel:.2e}")


def test_analytic_jacobian_matches_finite_difference():
    print("[2] 해석적 자코비안 == 유한차분 (핏 도중 실제로 불린 것 전수)")
    eng = make_engine()
    y = synth_scan(eng)
    worst = {"rel": 0.0, "n": 0}
    orig = df.least_squares

    def spy(fun, x0, **kw):
        jac = kw.get("jac")
        if callable(jac):
            x = np.asarray(x0, dtype=float)
            J = jac(x)
            Jfd = approx_derivative(fun, x, method="2-point",
                                    bounds=kw.get("bounds", (-np.inf, np.inf)))
            scale = max(float(np.abs(Jfd).max()), 1e-300)
            worst["rel"] = max(worst["rel"], float(np.abs(J - Jfd).max()) / scale)
            worst["n"] += 1
        return orig(fun, x0, **kw)

    df.least_squares = spy
    try:
        run_fit(eng, y, np.ones(len(PIXEL_IDX)))
    finally:
        df.least_squares = orig
    check("해석적 자코비안이 실제로 쓰였다", worst["n"] > 0, f"호출 {worst['n']}회")
    check("유한차분과 일치", worst["rel"] < 1e-4, f"max rel={worst['rel']:.2e}")


def test_jacobian_step_sweep():
    """[TBD-3.2] 스텝 크기를 쓸어 V 자를 확인한다 — **축마다 따로**.

    [2] 는 scipy 기본 스텝 하나로 본다. 단일 h 의 일치도는 h 를 잘 고른 결과일
    수도 있으므로, 절단오차(∝h²)와 반올림오차(∝1/h)의 **V 자**가 실제로 나오는지
    본다. V 자가 안 나오면 자코비안이 틀린 것이다.

    ⚠ **축마다 따로 내야 한다.** shift 는 px 단위(O(1))인데 squeeze 는 1 근처의
    배율이라 상자가 ±0.02 급이다 — 같은 절대 h 가 두 축에서 전혀 다른 크기다.
    합쳐서 최대만 보면 h=1e-2 에서 squeeze 쪽이 3.7e-2 로 튀어 "V 자가 깨졌다" 로
    읽힌다. 이상이 아니라 스케일 차이다.
    """
    print("[2b] 자코비안 유한차분 일치 — 스텝 크기 쓸기 (축마다)")
    eng = make_engine()
    y = synth_scan(eng)
    grab = {}
    orig = df.least_squares

    def spy(fun, x0, **kw):
        if "fun" not in grab and callable(kw.get("jac")):
            grab.update(fun=fun, jac=kw["jac"], x0=np.asarray(x0, float),
                        bounds=kw.get("bounds", (-np.inf, np.inf)),
                        names=kw.get("_names"))
        return orig(fun, x0, **kw)

    df.least_squares = spy
    try:
        run_fit(eng, y, np.ones(len(PIXEL_IDX)))
    finally:
        df.least_squares = orig
    if "fun" not in grab:
        check("해석적 자코비안을 잡았다", False)
        return

    fun, jac, x0 = grab["fun"], grab["jac"], grab["x0"]
    lo, hi = (np.asarray(b, dtype=float) * np.ones(len(x0)) for b in grab["bounds"])
    th = np.clip(x0, lo + 1e-3, hi - 1e-3)      # 상자 안쪽에서 — 중앙차분이 나가면 안 된다
    J = np.asarray(jac(th), dtype=float)
    HS = (1e-1, 1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8, 1e-9)
    E = np.full((len(HS), len(th)), np.nan)
    print("    %-10s %s" % ("h", "".join("%14s" % ("theta[%d]" % k)
                                         for k in range(len(th)))))
    for i, h in enumerate(HS):
        for k in range(len(th)):
            if th[k] + h > hi[k] or th[k] - h < lo[k]:
                continue
            e = np.zeros(len(th))
            e[k] = h
            fd = (np.asarray(fun(th + e), dtype=float)
                  - np.asarray(fun(th - e), dtype=float)) / (2 * h)
            den = float(np.linalg.norm(J[:, k]))
            E[i, k] = float(np.linalg.norm(fd - J[:, k])) / den if den else np.nan
        print("    %-10.0e %s" % (h, "".join(
            ("%14.3e" % E[i, k]) if np.isfinite(E[i, k]) else "%14s" % "box"
            for k in range(len(th)))))
    for k in range(len(th)):
        col = E[:, k]
        if not np.isfinite(col).any():
            continue
        j = int(np.nanargmin(col))
        check("theta[%d] 축 최소오차 < 1e-6" % k, np.nanmin(col) < 1e-6,
              "h=%.0e 에서 %.2e" % (HS[j], np.nanmin(col)))
        # V 자: 최소 양쪽이 최소보다 커야 한다(끝점이면 한쪽만)
        vshape = ((j == 0 or col[j - 1] > col[j])
                  and (j == len(HS) - 1 or col[j + 1] > col[j]))
        check("theta[%d] 축이 V 자" % k, bool(vshape),
              "최소 h=%.0e" % HS[j])


def test_weight_vector_equals_dense_diagonal():
    print("[3] W 벡터 == W 밀집 대각행렬 (구 호출부 호환 경로)")
    eng = make_engine()
    y = synth_scan(eng)
    n = len(PIXEL_IDX)
    w = np.linspace(0.7, 1.3, n)
    a = run_fit(eng, y, w)
    b = run_fit(eng, y, np.diag(w))
    for i, label in enumerate(("shift", "squeeze", "gas", "poly")):
        va, vb = np.asarray(a[i], dtype=float), np.asarray(b[i], dtype=float)
        check(f"{label} 비트동일", np.array_equal(va, vb),
              f"max|d|={np.max(np.abs(va - vb)) if va.size else 0:.3e}")


def test_negative_block_falls_back_to_finite_difference():
    print("[4] ±Neg OFF면 해석적 경로가 꺼진다 (경계에서 미분 불가능)")
    eng = make_engine()
    y = synth_scan(eng)
    seen = {"analytic": None}
    orig = df.least_squares

    def spy(fun, x0, **kw):
        seen["analytic"] = callable(kw.get("jac"))
        return orig(fun, x0, **kw)

    df.least_squares = spy
    try:
        run_fit(eng, y, np.ones(len(PIXEL_IDX)), allow_negative_gas=True)
        on = seen["analytic"]
        run_fit(eng, y, np.ones(len(PIXEL_IDX)), allow_negative_gas=False)
        off = seen["analytic"]
    finally:
        df.least_squares = orig
    check("±Neg ON → 해석적 자코비안", on is True, f"jac callable={on}")
    check("±Neg OFF → 유한차분 폴백", off is False, f"jac callable={off}")


def test_inactive_gas_coefficient_is_zero():
    print("[5] 창 밖 기체 계수는 정확히 0 (keep_mask 경로)")
    eng = make_engine()
    y = synth_scan(eng)
    props = ref_props(eng.gas_list)
    # 두 번째 기체의 흡수대를 핏 창 밖 파장으로 선언 → gas_active_in_window가 False
    # (파장축이 없으면 픽셀 번호가 그대로 nm로 쓰인다 — 여기선 창이 700~1299)
    target = eng.gas_list[1]
    props[target] = dict(props[target], active_bands_nm="1900, 2000")
    out = run_fit(eng, y, np.ones(len(PIXEL_IDX)), props=props)
    gas = np.asarray(out[2], dtype=float)
    idx = eng.gas_list.index(target)
    check(f"{target} 계수 == 0", gas[idx] == 0.0, f"c={gas[idx]:.3e}")
    check("다른 기체는 0이 아님", np.any(np.delete(gas, idx) != 0.0), f"c={gas}")


def main():
    for t in (test_spline_equivalence,
              test_analytic_jacobian_matches_finite_difference,
              test_jacobian_step_sweep,
              test_weight_vector_equals_dense_diagonal,
              test_negative_block_falls_back_to_finite_difference,
              test_inactive_gas_coefficient_is_zero):
        t()
    print(f"\nvarpro jacobian tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
