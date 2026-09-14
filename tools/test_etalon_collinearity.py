"""Etalon–기체 공선성 진단 단위테스트 (개선작업지시_2026-07 §B 검증 1항).

합성 기체 지문으로:
  1) 지문 = 사인파(고의 공선, etalon 주파수와 동일) → |r|≈1, VIF ≫ vif_no_etalon
  2) 지문 = 좁은 가우시안 피크(무관) → r 낮음, VIF ≈ vif_no_etalon
  3) 지문 = 완만한 다항(전부 poly에 흡수) → 잔차 0 → r=NaN 처리
  4) 경고 목록·포매터 동작
  5) 진단이 핏 결과를 바꾸지 않음(호출 전후 fit 출력 동일 — 검증≠필터)

사용: python tools/test_etalon_collinearity.py  → 전부 PASS면 exit 0
"""
import os
import sys

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # cp949 콘솔 대비

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scipy.interpolate import interp1d

from core.doas_fit import DoasFitter, ETALON_CORR_WARN

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


class _FakeEngine:
    """DoasFitter가 쓰는 최소 인터페이스(gas_list/interpolators/scaling_factors)."""

    def __init__(self, refs):
        self.gas_list = list(refs)
        n = len(next(iter(refs.values())))
        x = np.arange(n, dtype=float)
        self.interpolators = {
            k: interp1d(x, v, bounds_error=False, fill_value=0.0)
            for k, v in refs.items()}
        self.scaling_factors = {k: float(np.max(np.abs(v)) or 1.0)
                                for k, v in refs.items()}
        self.multipliers = {k: 1.0 for k in refs}


def main():
    n = 800
    px = np.arange(n, dtype=float)
    e_f = 0.18                                     # rad/px (캠페인급)
    rng = np.random.default_rng(3)

    sine_gas  = np.sin(e_f * px + 0.7)             # 고의 공선(위상 달라도 부분공간 동일)
    peak_gas  = np.exp(-0.5 * ((px - 400.0) / 8.0) ** 2)   # 무관한 좁은 지문
    smooth_gas = 1e-3 * (px / n) ** 3 + 0.5        # poly가 전부 흡수

    eng = _FakeEngine({"SINE": sine_gas, "PEAK": peak_gas, "SMOOTH": smooth_gas})
    fitter = DoasFitter(eng)
    diag = fitter.etalon_collinearity(px, e_f, poly_order=4, ref_properties={})
    pg = diag["per_gas"]

    print("[1] deliberate collinear fingerprint (= sine at etalon f)")
    check("|r|≈1", pg["SINE"]["r"] > 0.99, f"r={pg['SINE']['r']:.4f}")
    check("VIF explodes vs no-etalon",
          pg["SINE"]["vif"] > 50 * max(pg["SINE"]["vif_no_etalon"], 1.0),
          f"vif={pg['SINE']['vif']:.1f} vs {pg['SINE']['vif_no_etalon']:.1f}")
    check("flagged in warn list", "SINE" in diag["warn"])

    print("[2] unrelated narrow fingerprint")
    check("r low", pg["PEAK"]["r"] < 0.3, f"r={pg['PEAK']['r']:.4f}")
    check("VIF ≈ no-etalon VIF",
          pg["PEAK"]["vif"] < 1.5 * pg["PEAK"]["vif_no_etalon"] + 0.5,
          f"vif={pg['PEAK']['vif']:.2f} vs {pg['PEAK']['vif_no_etalon']:.2f}")
    check("not flagged", "PEAK" not in diag["warn"])

    print("[3] smooth fingerprint fully absorbed by poly")
    check("r is NaN (zero differential norm)", not np.isfinite(pg["SMOOTH"]["r"]),
          f"r={pg['SMOOTH']['r']}")

    print("[4] formatter")
    line = DoasFitter.format_etalon_collinearity(diag)
    check("one line, mentions warn + f", ("⚠" in line) and ("rad/px" in line), line)
    check("threshold constant exported", ETALON_CORR_WARN == 0.5)

    print("[5] diagnostic does not alter the fit (검증≠필터)")
    # noisy 측정 = 0.3×PEAK + etalon fringe + noise → 진단 호출 전/후 핏 동일해야
    y = (0.3 * peak_gas / eng.scaling_factors["PEAK"]
         + 0.02 * np.sin(e_f * px + 1.1) + 0.001 * rng.standard_normal(n))
    fixed = {}
    for g in eng.gas_list:
        fixed[f"{g}_sh"] = 0.0
        fixed[f"{g}_sq"] = 1.0
    args = (px, y, np.ones(n), [], fixed, {}, [], [], [], 4, e_f,
            px[n // 2], 1.0, {}, 25.0, 0.0, False)
    out1 = fitter.execute_varpro_fit(*args)
    _ = fitter.etalon_collinearity(px, e_f, 4, {})
    out2 = fitter.execute_varpro_fit(*args)
    same = all(np.array_equal(np.asarray(a, dtype=float), np.asarray(b, dtype=float))
               for a, b in zip(out1[2:6], out2[2:6]))
    check("fit outputs byte-identical around diagnostic call", same)

    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
