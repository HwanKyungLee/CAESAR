# -*- coding: utf-8 -*-
"""tools/test_error_corr.py — residual-correlation (sandwich) error <gas>_ErrorCorr (2026-10-03).

The fit covariance assumes a white residual. Manuscript §3.4/§4.6: an AR(1) ρ=0.5 residual makes
it ~1.6× too small; the sandwich G·Toeplitz(ρ)·Gᵀ recovers that and leaves white noise alone.

  1) toeplitz_quadform_diag == explicit G·Toeplitz·Gᵀ
  2) residual_acf: truncated at the first non-positive lag, ρ_0 = 1
  3) end to end (Monte Carlo, synthetic references): white noise → ErrorCorr ≈ Error ≈ actual
     scatter; AR(1) 0.5 → Error too small, ErrorCorr close to the actual scatter
  4) the existing conditional error (c_perr → <gas>_Error) does not change

    python tools/test_error_corr.py
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys

import numpy as np
from scipy.linalg import toeplitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.doas_fit import DoasFitter, residual_acf, toeplitz_quadform_diag
from tools.test_varpro_jacobian import (FIXED_E_F, PIXEL_IDX, POLY_ORDER,
                                        make_engine, ref_props, synth_scan)


def test_quadform():
    rng = np.random.default_rng(3)
    G = rng.normal(size=(4, 50))
    rho = np.array([1.0, 0.6, 0.3, 0.1])
    full = np.zeros(50); full[:4] = rho
    want = np.diag(G @ toeplitz(full) @ G.T)
    assert np.allclose(toeplitz_quadform_diag(G, rho), want, rtol=1e-12)
    print("  PASS  toeplitz_quadform_diag == explicit Toeplitz sandwich")


def test_acf():
    rng = np.random.default_rng(4)
    e = rng.normal(size=4000)
    ar = np.empty_like(e); ar[0] = e[0]
    for i in range(1, len(e)):
        ar[i] = 0.5 * ar[i - 1] + e[i]
    a = residual_acf(ar)
    assert a[0] == 1.0 and abs(a[1] - 0.5) < 0.05 and np.all(a[1:] > 0)
    assert len(residual_acf(np.ones(10))) == 1          # constant residual → white
    print(f"  PASS  residual_acf AR(0.5): rho1={a[1]:.3f}, {len(a) - 1} positive lags")


def _mc(rho, n_rep=200, noise=2e-4):
    eng = make_engine()
    fitter = DoasFitter(eng)
    clean = synth_scan(eng, shift=0.4, squeeze=1.003)
    props = ref_props(eng.gas_list)
    act, fx, lk, t0, lb, ub = fitter.setup_fit_parameters(props, 0.0, [0.0], 0.5)
    c0 = PIXEL_IDX[len(PIXEL_IDX) // 2]
    rng = np.random.default_rng(7)
    est, perr, pcorr = [], [], []
    for _ in range(n_rep):
        e = rng.normal(0, noise, len(clean))
        if rho:
            for i in range(1, len(e)):
                e[i] = rho * e[i - 1] + np.sqrt(1 - rho ** 2) * e[i]
        out, diag = fitter.execute_varpro_fit(
            PIXEL_IDX, clean + e, np.ones(len(clean)), act, fx, lk, t0, lb, ub, POLY_ORDER,
            FIXED_E_F, c0, 1.0, props, 25.0, 0.0, False, allow_negative_gas=True,
            return_diagnostics=True)
        est.append(out[2][0]); perr.append(out[6][0]); pcorr.append(diag["perr_corr"][0])
    sd = np.std(est, ddof=1)
    return sd / np.median(perr), sd / np.median(pcorr), np.median(np.divide(pcorr, perr))


def test_monte_carlo():
    w_err, w_corr, w_infl = _mc(0.0)
    a_err, a_corr, a_infl = _mc(0.5)
    print(f"        white : SD/Error {w_err:.2f}  SD/ErrorCorr {w_corr:.2f}  inflation {w_infl:.2f}")
    print(f"        AR 0.5: SD/Error {a_err:.2f}  SD/ErrorCorr {a_corr:.2f}  inflation {a_infl:.2f}")
    assert 0.95 < w_infl < 1.15, "white noise must not be inflated much"
    assert a_err > 1.1, "AR(1) case should expose the white-noise deficit"
    assert a_infl > 1.15, "AR(1) residual must inflate the error"
    assert abs(a_corr - 1.0) < abs(a_err - 1.0) and 0.75 < a_corr < 1.3, \
        "sandwich error must be closer to the actual scatter than the white error"
    print("  PASS  Monte Carlo: sandwich recovers correlated-noise deficit, leaves white noise")


def test_conditional_error_unchanged():
    eng = make_engine()
    fitter = DoasFitter(eng)
    y = synth_scan(eng) + np.random.default_rng(11).normal(0, 2e-4, len(PIXEL_IDX))
    props = ref_props(eng.gas_list)
    act, fx, lk, t0, lb, ub = fitter.setup_fit_parameters(props, 0.0, [0.0], 0.5)
    args = (PIXEL_IDX, y, np.ones(len(y)), act, fx, lk, t0, lb, ub, POLY_ORDER,
            FIXED_E_F, PIXEL_IDX[len(PIXEL_IDX) // 2], 1.0, props, 25.0, 0.0, False)
    plain = fitter.execute_varpro_fit(*args, allow_negative_gas=True)
    with_diag, diag = fitter.execute_varpro_fit(*args, allow_negative_gas=True, return_diagnostics=True)
    assert np.array_equal(plain[6], with_diag[6]) and len(diag["perr_corr"]) == len(eng.gas_list)
    assert np.isfinite(diag["resid_acf1"])
    print("  PASS  conditional error (c_perr) unchanged; perr_corr per gas; resid_acf1 finite")


if __name__ == "__main__":
    test_quadform()
    test_acf()
    test_conditional_error_unchanged()
    test_monte_carlo()
    print("test_error_corr: OK")
