"""Etalon ON/OFF 토글 단위테스트 (2026-09-26).

execute_varpro_fit(fixed_e_f=None) → etalon sin·cos 열 없이 핏.
  1) fringe 없는 합성 스펙트럼: OFF가 기체를 정확히 복원, etalon_amp=0, poly 계수 = poly_order+1개
  2) fringe 없는 스펙트럼: ON/OFF 기체값이 잡음 수준 안에서 일치
  3) fringe 있는 스펙트럼: ON이 OFF보다 잔차가 작다(토글이 실제로 기저를 바꾼다)
  4) 기체 지문이 fringe와 공선일 때: OFF의 기체 σ가 ON보다 작다(공선성 해소 — 옵션의 목적)

사용: python tools/test_etalon_toggle.py  → 전부 PASS면 exit 0
"""
import os
import sys

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scipy.interpolate import interp1d

from core.doas_fit import DoasFitter

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
    def __init__(self, refs):
        self.gas_list = list(refs)
        n = len(next(iter(refs.values())))
        x = np.arange(n, dtype=float)
        self.interpolators = {k: interp1d(x, v, bounds_error=False, fill_value=0.0)
                              for k, v in refs.items()}
        self.scaling_factors = {k: float(np.max(np.abs(v)) or 1.0) for k, v in refs.items()}
        self.multipliers = {k: 1.0 for k in refs}


def _fit(fitter, eng, px, y, e_f, poly=3):
    fixed = {}
    for g in eng.gas_list:
        fixed[f"{g}_sh"] = 0.0
        fixed[f"{g}_sq"] = 1.0
    n = len(px)
    return fitter.execute_varpro_fit(px, y, np.ones(n), [], fixed, {}, [], [], [],
                                     poly, e_f, px[n // 2], 1.0, {}, 25.0, 0.0, False)


def main():
    n = 600
    px = np.arange(n, dtype=float)
    e_f = 0.15
    rng = np.random.default_rng(7)
    # 좁은 선 여러 개(H2O 유사) + 넓은 띠(NO2 유사)
    lines = sum(np.exp(-0.5 * ((px - c) / 2.5) ** 2) for c in (90, 170, 260, 330, 410, 505))
    band = np.sin(px / 40.0) * np.exp(-((px - 300) / 250.0) ** 2) + 1.0
    eng = _FakeEngine({"LINES": lines, "BAND": band})
    fitter = DoasFitter(eng)
    sL, sB = eng.scaling_factors["LINES"], eng.scaling_factors["BAND"]
    tL, tB = 0.8, 2.0                                  # 참값(스케일된 계수)
    base = 0.01 * ((px - 300) / 300) ** 2 + 0.003
    clean = tL * lines / sL + tB * band / sB + base

    print("[1] no fringe, noise-free: OFF recovers exactly")
    sh, sq, gc, pc, ea, ep, perr = _fit(fitter, eng, px, clean, None)
    check("gas exact", np.allclose(gc, [tL, tB], rtol=1e-8, atol=1e-10), f"gc={gc}")
    check("etalon_amp == 0 and phase == 0", ea == 0.0 and ep == 0.0, f"{ea},{ep}")
    check("poly coeffs = poly_order+1", len(pc) == 4, f"len={len(pc)}")

    print("[2] no fringe, noisy: ON ~ OFF")
    y = clean + 2e-4 * rng.standard_normal(n)
    on = _fit(fitter, eng, px, y, e_f)
    off = _fit(fitter, eng, px, y, None)
    d = np.abs(np.asarray(on[2]) - np.asarray(off[2]))
    sig = np.asarray(on[6][:2]) if on[6] is not None and len(on[6]) >= 2 else np.array([np.inf, np.inf])
    check("|ON-OFF| < 3 sigma", np.all(d < 3 * np.maximum(sig, 1e-12)), f"d={d}, sig={sig}")

    print("[3] with fringe: ON residual < OFF residual")
    yf = y + 3e-3 * np.sin(e_f * px + 0.4)
    def rms(out):
        _sh, _sq, g, p, a, ph, _pe = out
        X = np.column_stack([lines / sL, band / sB])
        r = yf - X @ np.asarray(g)
        # poly+etalon 성분은 선형이므로 잔차를 (poly[+etalon]) 공간에 재투영해 비교
        xn = (px - px[n // 2]) / (0.5 * (px[-1] - px[0]))
        cols = [np.polynomial.chebyshev.chebvander(xn, 3)]
        if a != 0.0:
            cols.append(np.column_stack([np.sin(e_f * px), np.cos(e_f * px)]))
        B = np.hstack(cols)
        c, *_ = np.linalg.lstsq(B, r, rcond=None)
        return float(np.sqrt(np.mean((r - B @ c) ** 2)))
    r_on, r_off = rms(_fit(fitter, eng, px, yf, e_f)), rms(_fit(fitter, eng, px, yf, None))
    check("rms_on < 0.5*rms_off", r_on < 0.5 * r_off, f"on={r_on:.2e} off={r_off:.2e}")

    print("[4] gas collinear with fringe: OFF sigma < ON sigma")
    col = np.sin(e_f * px + 0.3) * np.exp(-((px - 300) / 200.0) ** 2) + 1.2
    eng2 = _FakeEngine({"COL": col})
    f2 = DoasFitter(eng2)
    y2 = 0.5 * col / eng2.scaling_factors["COL"] + base + 2e-4 * rng.standard_normal(n)
    s_on = _fit(f2, eng2, px, y2, e_f)[6]
    s_off = _fit(f2, eng2, px, y2, None)[6]
    ok = s_on is not None and s_off is not None and np.isfinite(s_off[0]) and s_off[0] < s_on[0]
    check("sigma_off < sigma_on", ok, f"on={None if s_on is None else s_on[0]}, off={None if s_off is None else s_off[0]}")

    print(f"etalon toggle tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 0 if _n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
