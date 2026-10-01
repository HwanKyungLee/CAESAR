"""etalon OFF 경로 불변식 — 합성, 캠페인 데이터 불필요.

`tools/test_etalon_toggle.py`(물리: 복원·잔차·공선성 해소)를 보완한다. 여기서 지키는 것:

1. OFF 반환 — amp·phase 0.0, dof 가 ON 보다 정확히 2 큼, poly 계수 길이는 ON 과 같음
   (열 순서 gas→poly→custom→[sin,cos] 인덱싱), etalon 없는 합성에서 기체 계수 ON~OFF.
2. OFF 해석적 자코비안 == 유한차분.
3. OFF 결합 공분산 — 결합 ≥ 조건부, theta 오차 키가 active_vars.
4. 진단 — etalon_collinearity(None) 예외 없음, format 은 n/a.
5. 배관 — fit_scan(use_etalon=False)·워커(use_etalon=False)는 detect_etalon_frequency 를
   **부르지 않고** None 을 넘긴다. 켜면 부른다. 병렬 자식 cfg 에 use_etalon 이 실린다.
6. 정답 재현(축소판) — etalon 없는 합성, 좁은 창 450–462 nm·poly3·잡음×3 에서
   ON/OFF NO₂ 산포비 > 1.5. 전체판(300 실현)은 ON 0.0827 / OFF 0.0409, SD(z) 1.09 / 0.97.

출처: 브랜치 claude/etalon-switch-implementation-635a05(0798b15)의 테스트를 main 의
`use_etalon` 구현(87028c4)에 맞춰 옮김. 그 브랜치의 입력 계약 검사(fixed_e_f=0·NaN·음수
거부, check_etalon_freq/etalon_enabled)는 main 에 대응 API 가 없어 뺐다.
"""
import os
import sys
import io
import contextlib

import numpy as np
from scipy.optimize._numdiff import approx_derivative

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.doas_fit as df
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


def fit(eng, y, e_f, props=None):
    fitter = DoasFitter(eng)
    props = props or ref_props(eng.gas_list)
    act, fx, lk, t0, lb, ub = fitter.setup_fit_parameters(props, 0.0, [0.0], 0.5)
    c0 = PIXEL_IDX[len(PIXEL_IDX) // 2]
    return fitter.execute_varpro_fit(
        PIXEL_IDX, y, np.ones(len(y)), act, fx, lk, t0, lb, ub, POLY_ORDER, e_f,
        c0, 1.0, props, 25.0, 0.0, False, allow_negative_gas=True,
        return_diagnostics=True), act


def test_off_outputs():
    print("[1] OFF 반환값·인덱싱")
    eng = make_engine()
    y = synth_scan(eng)
    (on, d_on), _ = fit(eng, y, FIXED_E_F)
    (off, d_off), _ = fit(eng, y, None)
    check("amp·phase == 0.0", off[4] == 0.0 and off[5] == 0.0, f"{off[4]}, {off[5]}")
    check("dof OFF = ON + 2", d_off["dof"] == d_on["dof"] + 2, f"{d_on['dof']} {d_off['dof']}")
    check("poly 계수 길이 = poly_order+1 (양쪽)",
          len(on[3]) == len(off[3]) == POLY_ORDER + 1, f"{len(on[3])} {len(off[3])}")
    check("gas perr 유한", np.all(np.isfinite(off[6])), str(off[6]))
    # 합성엔 etalon 이 없다 → 두 핏의 기체 계수가 가깝다(끄는 게 해를 망치지 않는다)
    rel = np.max(np.abs(np.asarray(off[2]) - on[2]) / np.maximum(np.abs(on[2]), 1e-30))
    check("etalon 없는 합성에서 기체 계수 ON~OFF (<5 %)", rel < 0.05, f"max rel={rel:.3g}")


def test_off_jacobian():
    print("[2] OFF 해석적 자코비안 == 유한차분")
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
        fit(eng, y, None)
    finally:
        df.least_squares = orig
    check("해석적 자코비안이 쓰였다", worst["n"] > 0, f"호출 {worst['n']}회")
    check("유한차분과 일치", worst["rel"] < 1e-4, f"max rel={worst['rel']:.2e}")


def test_off_joint_covariance():
    print("[3] OFF 결합 공분산")
    eng = make_engine()
    y = synth_scan(eng) + np.random.default_rng(11).normal(0, 2e-4, len(PIXEL_IDX))
    (off, d), act = fit(eng, y, None)
    joint = np.asarray(d["perr_joint"], float)
    cond = np.asarray(off[6], float)
    check("결합 유한", np.all(np.isfinite(joint)), str(joint))
    check("결합 >= 조건부", np.all(joint >= cond * (1 - 1e-9)), f"{cond} {joint}")
    check("theta 오차 키 = active_vars", sorted(d["theta_err_joint"]) == sorted(act),
          f"{sorted(d['theta_err_joint'])} vs {sorted(act)}")


def test_diagnostics():
    print("[4] 공선성 진단 OFF → n/a")
    eng = make_engine()
    f = DoasFitter(eng)
    try:
        diag = f.etalon_collinearity(PIXEL_IDX.astype(float), None, POLY_ORDER, ref_props(eng.gas_list))
        line = DoasFitter.format_etalon_collinearity(diag)
        check("예외 없이 n/a", "n/a" in line and diag["per_gas"] == {}, line)
    except Exception as e:
        check("예외 없이 n/a", False, f"{type(e).__name__}: {e}")
    on = DoasFitter.format_etalon_collinearity(
        f.etalon_collinearity(PIXEL_IDX.astype(float), FIXED_E_F, POLY_ORDER, ref_props(eng.gas_list)))
    check("ON 은 종전 형식", on.startswith("etalon-gas collinearity (f="), on)


def test_plumbing_fit_scan():
    print("[5a] fit_scan(use_etalon=False)는 검출을 안 부르고 None 을 넘긴다")
    from core import param_optimizer as PO
    seen = {}

    class Eng:
        gas_list = []
        _wave_axis = np.array([0.0, 1.0])
        scaling_factors = multipliers = {}

        def get_model_components(self, *a, **k):
            seen["model_ef"] = k["etalon_freq"]
            return np.zeros(2), np.zeros(2), np.zeros(2), np.zeros(2), None

    class Fitter:
        def detect_etalon_frequency(self, *a):
            seen["detect"] = seen.get("detect", 0) + 1
            return 0.1

        def setup_fit_parameters(self, *a, **k):
            return [], {}, {}, [], [], []

        def execute_varpro_fit(self, *args, **kwargs):
            seen["ef"] = args[10]
            return [], [], np.array([]), np.array([]), 0.0, 0.0, np.array([])

    old = PO._seed_shift
    PO._seed_shift = lambda *a, **k: (0.0, 1.0)
    try:
        r = PO.fit_scan(Eng(), Fitter(), {}, [0, 1], [1e-6, 1e-6], 25, 1013, 0, 1, 0, .5,
                        allow_negative_gas=True, use_etalon=False)
        check("OFF: detect 0회, ef=None", seen.get("detect", 0) == 0 and seen["ef"] is None, str(seen))
        check("OFF: etalon_frequency NaN 기록", np.isnan(r["etalon_frequency"]), str(r.get("etalon_frequency")))
        seen.clear()
        r = PO.fit_scan(Eng(), Fitter(), {}, [0, 1], [1e-6, 1e-6], 25, 1013, 0, 1, 0, .5,
                        allow_negative_gas=True)
        check("기본(ON): detect 1회, ef=0.1", seen.get("detect") == 1 and seen["ef"] == 0.1, str(seen))
        check("ON: etalon_frequency 기록", r["etalon_frequency"] == 0.1, str(r.get("etalon_frequency")))
    finally:
        PO._seed_shift = old


def test_plumbing_worker():
    print("[5b] 워커 use_etalon=False → detect 안 부름")
    from gui import worker as W
    eng = make_engine()
    y = synth_scan(eng) * 1e-6                       # 알파 크기(워커가 1e6 로 스케일)
    wave = np.arange(len(y), dtype=float)
    old = (W.DataIO.parse_alpha_row_time, W.DataIO.load_alpha_trace_row_full)
    W.DataIO.parse_alpha_row_time = staticmethod(lambda *a: None)
    W.DataIO.load_alpha_trace_row_full = staticmethod(lambda *a: (wave, y.copy(), 25.0, 1013.0))
    try:
        for enabled in (False, True):
            p0 = [0.0, 1.0] + [0.1] * len(eng.gas_list) + [0.0] * (POLY_ORDER + 1)
            w = W.AnalysisWorker(eng, [], 0, len(y) - 1, p0, None, -1,
                                 ref_properties=ref_props(eng.gas_list))
            w.allow_negative_gas = True
            w.use_etalon = enabled
            calls = []
            fitter = w._doasfitter()
            orig = fitter.detect_etalon_frequency
            fitter.detect_etalon_frequency = lambda *a: (calls.append(1), orig(*a))[1]
            with contextlib.redirect_stdout(io.StringIO()):
                res, _, ef = w._fit_alpha_range([(0, "synthetic.dat", 0), (1, "synthetic.dat", 1)], 0)
            params = res[0][1].get("Params") or {}
            tag = "ON" if enabled else "OFF"
            check(f"{tag}: 핏 성공", bool(params), res[0][1].get("Status"))
            check(f"{tag}: detect 호출 {'1' if enabled else '0'}회", len(calls) == (1 if enabled else 0),
                  f"{len(calls)}")
            check(f"{tag}: 반환 주파수", (ef is None) if not enabled else (ef is not None and ef > 0), str(ef))
        check("병렬 자식 cfg 에 실린다", w._chunk_cfg().get("use_etalon") is True)
    finally:
        W.DataIO.parse_alpha_row_time, W.DataIO.load_alpha_trace_row_full = (
            staticmethod(old[0]), staticmethod(old[1]))


def test_narrow_window_scatter():
    print("[6] 정답 재현(축소판) — etalon 없는 합성, 좁은 창: ON/OFF 산포비 > 1.5")
    import tools.test_varpro_synthetic_ext as T
    T.REFDIR = T.REFDIR or next((d for d in T.REF_DIRS if d and os.path.isdir(d)), None)
    if not T.REFDIR:
        check("레퍼런스 픽스처 있음", False, "tests/data/wv_cal_roi1 없음")
        return
    old_nm = T.FIT_NM
    T.FIT_NM = (450.0, 462.0)
    try:
        gases = ("NO2", "CHOCHO", "H2O")
        with contextlib.redirect_stdout(io.StringIO()):
            eng, wave = T.build_engine(gases)
        vp, center = T.window(wave)
        fitter = DoasFitter(eng)
        props = T.props_for(gases, sh_val="-8.0, 8.0")
        scds = T.companion_scds(eng, gases, T.SCD_MID)
        rng = np.random.default_rng(20260953)
        res = {True: [], False: []}
        for _ in range(60):
            a = T.synthesize(eng, vp, center, scds, T.FIELD_SHIFT, 1.002, 3 * T.NOISE_MEASURED, rng)
            for on in (True, False):
                r = T.recover(eng, fitter, props, vp, center, a, etalon_f=(T.ETALON_F if on else None))
                res[on].append(r["scd"]["NO2"] / T.SCD_MID)
        s_on, s_off = (float(np.std(res[k], ddof=1)) for k in (True, False))
        print(f"        n={len(vp)} px, 60 실현: 산포 ON {s_on:.4f} / OFF {s_off:.4f} (비 {s_on / s_off:.2f})")
        check("ON/OFF 산포비 > 1.5", s_on / s_off > 1.5, f"{s_on:.4f}/{s_off:.4f}")
        check("OFF 산포 0.03~0.05 (전체판 0.0409)", 0.03 < s_off < 0.05, f"{s_off:.4f}")
    finally:
        T.FIT_NM = old_nm


def main():
    for t in (test_off_outputs, test_off_jacobian, test_off_joint_covariance, test_diagnostics,
              test_plumbing_fit_scan, test_plumbing_worker, test_narrow_window_scatter):
        try:
            t()
        except Exception as e:                      # 한 묶음이 터져도 나머지는 돈다
            check(f"{t.__name__} 실행", False, f"{type(e).__name__}: {e}")
    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    sys.exit(1 if _n_fail else 0)


if __name__ == "__main__":
    main()
