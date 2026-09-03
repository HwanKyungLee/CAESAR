"""Regression checks for the explicit gas-coefficient policy boundary."""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import fit_physics as FP
from core import param_optimizer as PO
from gui.worker import AnalysisWorker


class _SeedEngine:
    gas_list = ["NO2"]

    def get_basis_matrix(self, pixel_idx, shift, squeeze, poly_deg):
        # Gas column first, polynomial column second. A negative polynomial
        # coefficient is required even when the gas itself is constrained.
        return np.array([[1.0, 1.0], [1.0, -1.0]])


class _SeedFitter:
    engine = _SeedEngine()


def test_seed_bounds():
    fitter = _SeedFitter()
    props = {"NO2": {"sh_mode": "Limit", "sh_val": "-1,1"}}
    y = np.array([-1.0, 1.0])
    original = PO.lsq_linear
    seen_negative_poly = []
    seen_gas_lower = []

    def checked(A, b, bounds):
        result = original(A, b, bounds=bounds)
        assert bounds[0][0] == 0.0
        assert np.isneginf(bounds[0][1])
        seen_gas_lower.append(bounds[0][0])
        seen_negative_poly.append(result.x[1] < 0)
        return result

    PO.lsq_linear = checked
    try:
        assert PO._seed_shift(fitter, np.arange(2), y, 0, props, "NO2", 1, 1,
                              False) == (-1.0, 1.0)
    finally:
        PO.lsq_linear = original
    assert any(seen_negative_poly)
    # Both policies are accepted and the non-gas (polynomial) column remains unbounded.
    true_bounds = []

    def checked_true(A, b, bounds):
        true_bounds.append(bounds[0].copy())
        return original(A, b, bounds=bounds)

    PO.lsq_linear = checked_true
    try:
        assert PO._seed_shift(fitter, np.arange(2), y, 0, props, "NO2", 1, 1,
                              True) == (-1.0, 1.0)
    finally:
        PO.lsq_linear = original
    assert all(np.isneginf(b[0]) and np.isneginf(b[1]) for b in true_bounds)


def test_policy_is_required():
    try:
        PO.fit_scan(None, None, {}, [], [], 25, 1013, 0, 1, 0, 0.5)
    except TypeError:
        pass
    else:
        raise AssertionError("fit_scan silently selected a gas-sign policy")
    try:
        FP.fitted_amount_health([], None, None, {}, 0, 1, 0, 0.5)
    except TypeError:
        pass
    else:
        raise AssertionError("fit_physics silently selected a gas-sign policy")
    try:
        PO.fit_scan(None, None, {}, [], [], 25, 1013, 0, 1, 0, 0.5,
                    allow_negative_gas="NO2")
    except TypeError:
        pass
    else:
        raise AssertionError("non-bool policy accepted")
    for fake in (type("Missing", (), {})(),
                 type("Wrong", (), {"allow_negative_gas": "false"})()):
        try:
            AnalysisWorker._chunk_cfg(fake)
        except TypeError:
            pass
        else:
            raise AssertionError("parallel worker accepted missing/non-bool policy")


def test_ac1_uses_magnitude():
    old = PO.evaluate
    PO.evaluate = lambda *a, **k: {
        "shift_dist": {"NO2": (1.0, 0.1)}, "autocorr1": -0.9
    }
    try:
        out = PO.recommend_shift([], None, None, {}, 0, 1, 0,
                                 allow_negative_gas=False)
        assert out["degenerate"] is True
    finally:
        PO.evaluate = old


def test_abs_ratio_is_median_of_per_scan_magnitudes():
    class Eng:
        gas_list = ["O4"]
        scaling_factors = {"O4": 2.0}
        multipliers = {"O4": 5.0}

    old = FP.fit_scan
    scans = [(None, None, 25.0, 1013.25)] * 4
    try:
        for values in ((4.0,) * 4, (-4.0,) * 4, (4.0, -4.0, 4.0, -4.0)):
            ratios = iter(values)

            def fake_fit(*args, **kwargs):
                theo = FP.theoretical_amount("O4", 25.0, 1013.25)
                return {"coeffs": {"O4": next(ratios) * theo * 2.0 / 5.0}}

            FP.fit_scan = fake_fit
            health = FP.fitted_amount_health(scans, Eng(), None, {}, 0, 1, 0, 0.5,
                                             target="O4", constant_species=("O4",),
                                             allow_negative_gas=True)
            assert health["abs_ratio"]["O4"] == 4.0
    finally:
        FP.fit_scan = old


def test_mixed_ac1_aggregate():
    old = PO.fit_scan
    values = iter((0.9, -0.9, 0.9, -0.9))
    PO.fit_scan = lambda *a, **k: {
        "conc": 1.0, "perr_rel": 0.1, "autocorr1": next(values), "rms_sig": 0.1,
        "n_free": 1, "shifts": {}, "squeezes": {}
    }
    try:
        row = PO.evaluate([(None, None, 25, 1013)] * 4, type("E", (), {"gas_list": []})(),
                          None, {}, 0, 1, 0, 0.5, allow_negative_gas=False)
        assert row["autocorr1"] == 0.9
    finally:
        PO.fit_scan = old


def test_policy_reaches_seed_and_final():
    class Eng:
        gas_list = ["NO2"]
        _wave_axis = np.array([0.0, 1.0])
        scaling_factors = {"NO2": 1.0}
        multipliers = {"NO2": 1.0}

        def get_model_components(self, *args, **kwargs):
            z = np.zeros(2)
            return z, z, z, z, None

    seen = []

    class Fitter:
        engine = Eng()
        detect_etalon_frequency = lambda *a: 0.1
        setup_fit_parameters = lambda *a: ([], {}, {}, np.array([]), np.array([]), np.array([]))

        def execute_varpro_fit(self, *args, **kwargs):
            seen.append(("final", kwargs["allow_negative_gas"]))
            return np.array([0.0]), np.array([1.0]), np.array([1.0]), np.array([]), 0, 0, np.array([0.1])

    old = PO._seed_shift
    PO._seed_shift = lambda *a, **k: (seen.append(("seed", a[8])) or (0.0, 1.0))
    try:
        PO.fit_scan(Eng(), Fitter(), {}, [0, 1], [0, 0], 25, 1013, 0, 1, 0, 0.5,
                    allow_negative_gas=True)
        assert seen == [("seed", True), ("final", True)]
    finally:
        PO._seed_shift = old


def test_impossible_reference_excluded():
    old_diag, old_health = FP.differential_collinearity, FP.fitted_amount_health
    FP.differential_collinearity = lambda *a, **k: {"pairwise": {}, "multiple_R": {}}
    FP.fitted_amount_health = lambda *a, **k: {
        "cv": {"O4": 0.0}, "corr_with_target": {"O4": 0.0}, "target_cv": 0.0,
        "constant_flag": {"O4": False}, "abs_ratio": {"O4": 4.0}, "n": 4
    }
    try:
        eng = type("E", (), {"gas_list": ["NO2", "O4"]})()
        verdict = FP.judge_reference(eng, None, [], {}, {}, 0, 1, 0, 0.5,
                                     allow_negative_gas=False)
        assert verdict["impossible"] if "impossible" in verdict else verdict["exclude"]
        assert verdict["exclude"]
    finally:
        FP.differential_collinearity, FP.fitted_amount_health = old_diag, old_health


if __name__ == "__main__":
    test_seed_bounds()
    test_policy_is_required()
    test_ac1_uses_magnitude()
    test_abs_ratio_is_median_of_per_scan_magnitudes()
    test_mixed_ac1_aggregate()
    test_policy_reaches_seed_and_final()
    test_impossible_reference_excluded()
    print("7 PASS")
