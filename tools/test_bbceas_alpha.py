"""Regression check for core.physics.bbceas_alpha / omr_d_from_ratio.

The alpha and (1-R)/d formulas used to be inline copies in gui/worker.py and
tools/reflectance_calc.py. They now call the core.physics functions; this check
pins that the functions are bit-identical to the former inline expressions, so
production alpha (path B) does not change by a single bit (CLAUDE.md rule 4).

No data needed. Collected by tests/test_script_suite.py.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.physics import RayleighPhysics, bbceas_alpha, omr_d_from_ratio


def _legacy_alpha(I, I0, omr_d, alpha_za, alpha_sample, rl):
    """Former inline expression of gui/worker.py (raw path, Pass 2, binned export). Baseline only."""
    return ((omr_d + rl * alpha_za) * ((I0 - I) / I) - (alpha_sample - alpha_za))


def _legacy_omr_d(ratio, alpha_za, alpha_he, rl):
    """Former inline expression of worker (R update, AlphaExportWorker) and reflectance_calc."""
    return rl * ((ratio * alpha_za) - alpha_he) / (1.0 - ratio)


def test_bit_identical_to_legacy():
    rng = np.random.default_rng(20260923)
    wave = np.linspace(400.0, 500.0, 2048)
    for rl in (1.0, 0.9330, 0.9950):
        for t_za, p_za, t_s, p_s in ((25.0, 1013.25, 28.8, 1010.0),
                                     (180.0, 965.0, 181.2, 964.3),
                                     (300.0, 915.0, 299.1, 916.8)):
            a_za = RayleighPhysics.get_alpha_rayleigh(wave, t_za, p_za, "zero_air")
            a_s = RayleighPhysics.get_alpha_rayleigh(wave, t_s, p_s, "zero_air")
            I0 = rng.uniform(1e3, 5e4, wave.size)
            I = I0 * rng.uniform(0.90, 1.02, wave.size)
            for omr_d in (np.full(wave.size, 9.79e-7) * rng.uniform(0.98, 1.02, wave.size),
                          9.79e-7):                       # array and scalar (best_omr_d) forms
                new = bbceas_alpha(I, I0, omr_d, a_za, a_s, rl)
                old = _legacy_alpha(I, I0, omr_d, a_za, a_s, rl)
                assert np.array_equal(new, old), f"rl={rl} T_za={t_za}: bit mismatch"


def test_omr_d_bit_identical_to_legacy():
    rng = np.random.default_rng(626)
    wave = np.linspace(400.0, 500.0, 2048)
    for rl in (1.0, 0.9330, 0.9950):
        for t, p in ((25.0, 1013.25), (28.8, 1010.0), (180.0, 965.0)):
            a_za = RayleighPhysics.get_alpha_rayleigh(wave, t, p, "zero_air")
            a_he = RayleighPhysics.get_alpha_rayleigh(wave, t, p, "helium")
            ratio = rng.uniform(0.79, 0.83, wave.size)
            ratio[::97] = 1.0                                 # denominator 0 -> inf/nan must match too
            with np.errstate(divide="ignore", invalid="ignore"):
                new = omr_d_from_ratio(ratio, a_za, a_he, rl)
                old = _legacy_omr_d(ratio, a_za, a_he, rl)
            assert np.array_equal(new, old, equal_nan=True), f"rl={rl} T={t}: bit mismatch"


def test_zero_absorber_gives_zero():
    wave = np.linspace(430.0, 470.0, 512)
    a_za = RayleighPhysics.get_alpha_rayleigh(wave, 25.0, 1013.25, "zero_air")
    I = np.full(wave.size, 12345.0)
    alpha = bbceas_alpha(I, I.copy(), np.full(wave.size, 1e-6), a_za, a_za, 0.933)
    assert np.all(alpha == 0.0)


def test_alpha_is_od_over_leff():
    """Weak absorber: alpha ~ OD*(1-R)/d, i.e. ~1e6 smaller than OD (the Vigil OD bug)."""
    wave = np.linspace(430.0, 470.0, 512)
    a_za = RayleighPhysics.get_alpha_rayleigh(wave, 25.0, 1013.25, "zero_air")
    omr_d = 9.79e-7
    I0 = np.full(wave.size, 20000.0)
    od = 0.05
    alpha = bbceas_alpha(I0 * np.exp(-od), I0, np.full(wave.size, omr_d), a_za, a_za, 1.0)
    assert np.allclose(alpha, (omr_d + a_za) * (np.exp(od) - 1.0), rtol=1e-12)
    assert np.median(alpha) < od * 1e-3


def test_omr_d_recovers_known_reflectivity():
    wave = np.linspace(430.0, 470.0, 400)
    t, p, d, rl = 25.0, 1013.25, 51.8, 0.933
    a_za = RayleighPhysics.get_alpha_rayleigh(wave, t, p, "zero_air")
    a_he = RayleighPhysics.get_alpha_rayleigh(wave, t, p, "helium")
    for target_r in (0.9999, 0.99995, 0.9995):
        k = (1.0 - target_r) / (rl * d)
        ratio = (k + a_he) / (a_za + k)
        omr_d = omr_d_from_ratio(ratio, a_za, a_he, rl)
        assert np.allclose(1.0 - omr_d * d, target_r, rtol=1e-10), target_r


if __name__ == "__main__":
    test_bit_identical_to_legacy()
    test_omr_d_bit_identical_to_legacy()
    test_zero_absorber_gives_zero()
    test_alpha_is_od_over_leff()
    test_omr_d_recovers_known_reflectivity()
    print("physics self-check OK: bbceas_alpha / omr_d_from_ratio bit-identical to legacy")
