"""Regression checks for the explicit gas-coefficient policy boundary."""
import os
import sys

import numpy as np
from scipy.interpolate import interp1d

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import fit_physics as FP
from core import param_optimizer as PO
from core.doas_fit import DoasFitter
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
        setup_fit_parameters = lambda *a, **k: ([], {}, {}, np.array([]), np.array([]), np.array([]))

        def execute_varpro_fit(self, *args, **kwargs):
            seen.append(("final", kwargs["allow_negative_gas"]))
            return np.array([0.0]), np.array([1.0]), np.array([1.0]), np.array([]), 0, 0, np.array([0.1])

    old = PO._seed_shift
    PO._seed_shift = lambda *a, **k: (seen.append(("seed", a[8])) or (0.0, 1.0))
    try:
        result = PO.fit_scan(Eng(), Fitter(), {}, [0, 1], [1e-6, 1e-6], 25, 1013, 0, 1, 0, 0.5,
                             allow_negative_gas=True)
        assert seen == [("seed", True), ("final", True)]
        assert result["deterministic_seed"] == {
            "shift": 0.0, "squeeze": 1.0, "source": "deterministic_grid"}
        controlled = PO.fit_scan(Eng(), Fitter(), {}, [0, 1], [1e-6, 1e-6], 25, 1013,
                                 0, 1, 0, 0.5, allow_negative_gas=False,
                                 controlled_start=(0.2, 1.01))
        assert controlled["deterministic_seed"] == {
            "shift": 0.2, "squeeze": 1.01, "source": "controlled_start"}
    finally:
        PO._seed_shift = old


def test_fit_scan_matches_worker_small_alpha_scaling_and_unscales_outputs():
    class Eng:
        gas_list = ["NO2"]
        _wave_axis = np.array([0.0, 1.0])
        scaling_factors = {"NO2": 1.0}
        multipliers = {"NO2": 1.0}

        def get_model_components(self, px, shifts, squeezes, gas, poly, **kwargs):
            model = np.full(2, gas[0] + poly[0])
            return model, np.full(2, gas[0]), np.full(2, poly[0]), np.zeros(2), None

    seen = {}

    class Fitter:
        engine = Eng()

        def detect_etalon_frequency(self, px, alpha, *args):
            seen["detected"] = alpha.copy()
            return 0.1

        setup_fit_parameters = lambda *a, **k: ([], {}, {}, np.array([]), np.array([]), np.array([]))

        def execute_varpro_fit(self, px, alpha, *args, **kwargs):
            seen["fitted"] = alpha.copy()
            # alpha mean is 2e-6, hence the production decade factor is 1e6.
            return np.array([0.0]), np.array([1.0]), np.array([1.5]), np.array([0.5]), 0.25, 0.0, np.array([0.1])

    result = PO.fit_scan(Eng(), Fitter(), {}, [0, 1], [2e-6, 2e-6], 25, 1013,
                         0, 1, 0, 0.5, allow_negative_gas=True,
                         controlled_start=(0.0, 1.0))
    assert np.array_equal(seen["detected"], np.array([2.0, 2.0]))
    assert np.array_equal(seen["fitted"], np.array([2.0, 2.0]))
    assert result["coeffs"]["NO2"] == 1.5e-6
    assert result["perr_rel"] == 0.1 / 1.5
    assert result["rms"] == 0.0
    assert result["sig"] == 1.5e-6
    assert result["normalization_factor"] == 1e6


def test_fit_scan_rejects_invalid_alpha_before_solver():
    class Eng:
        gas_list = []
        _wave_axis = np.array([0.0, 1.0])

    for alpha, message in (([0.0, 0.0], "all zero"),
                           ([0.0, np.nan], "finite"),
                           ([0.0, np.inf], "finite"),
                           ([1e-320, 1e-320], "normalization factor")):
        try:
            PO.fit_scan(Eng(), object(), {}, [0, 1], alpha, 25, 1013, 0, 1, 0, 0.5,
                        allow_negative_gas=True)
            raise AssertionError("invalid alpha accepted")
        except ValueError as exc:
            assert message in str(exc)


def test_small_alpha_active_shift_moves_and_multistarts_converge():
    class Eng:
        def __init__(self):
            self.gas_list = ["NO2"]
            self._wave_axis = np.arange(201.0)
            rng = np.random.default_rng(2)
            ref = np.convolve(rng.normal(size=201), np.ones(5) / 5, mode="same")
            self.interpolators = {"NO2": interp1d(
                self._wave_axis, ref, bounds_error=False, fill_value="extrapolate")}
            self.scaling_factors = {"NO2": 1.0}
            self.multipliers = {"NO2": 1.0}

        def pixel_to_wavelength(self, px):
            return np.asarray(px)

        def get_model_components(self, px, shifts, squeezes, gas, poly,
                                 etalon_amp=0, etalon_freq=0, etalon_phase=0):
            center = px[len(px) // 2]
            absorption = gas[0] * self.interpolators["NO2"](
                (px - center) * squeezes[0] + center + shifts[0])
            baseline = np.polynomial.chebyshev.chebval(
                np.linspace(-1, 1, len(px)), poly)
            etalon = etalon_amp * np.sin(etalon_freq * px + etalon_phase)
            return absorption + baseline + etalon, absorption, baseline, etalon, None

    class Fitter(DoasFitter):
        def detect_etalon_frequency(self, *args):
            return 0.37

    eng = Eng()
    px = np.arange(201.0)
    true_shift = 1.7
    alpha = 2e-6 * eng.interpolators["NO2"](px + true_shift) + 3e-7
    props = {"NO2": {"sh_mode": "Limit", "sh_val": "-3,3",
                       "sq_mode": "Fix", "sq_val": "1"}}
    fitted = [PO.fit_scan(
        eng, Fitter(eng), props, px, alpha, 25, 1013, 0, 200, 0, 5,
        allow_negative_gas=True, controlled_start=(start, 1.0))
        for start in (-0.4, 0.4)]

    assert all(r["shifts"]["NO2"] != start for r, start in zip(fitted, (-0.4, 0.4)))
    np.testing.assert_allclose(
        [r["shifts"]["NO2"] for r in fitted], [true_shift, true_shift], rtol=0, atol=1e-10)
    np.testing.assert_allclose(
        [r["coeffs"]["NO2"] for r in fitted], [2e-6, 2e-6], rtol=0, atol=1e-18)


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
    test_fit_scan_matches_worker_small_alpha_scaling_and_unscales_outputs()
    test_fit_scan_rejects_invalid_alpha_before_solver()
    test_small_alpha_active_shift_moves_and_multistarts_converge()
    test_impossible_reference_excluded()
    print("10 PASS")
