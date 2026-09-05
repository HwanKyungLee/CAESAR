"""Synthetic policy tests for the minimal Fit Setting Explorer."""
import json
import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import fit_explorer as FE
from core.doas_fit import DoasFitter


def test_candidates_and_starts():
    candidates = FE.neighboring_candidates(100, 200, 3, 5)
    assert len(candidates) == 9
    assert len({(c["px_min"], c["px_max"]) for c in candidates}) == 3
    assert {c["poly"] for c in candidates} == {2, 3, 4}
    starts = FE.controlled_starts(
        {"NO2": {"sh_mode": "Limit", "sh_val": "-8, 0", "sq_mode": "Fix", "sq_val": "1"}},
        "NO2", .5)
    assert len(starts) == 2
    assert (starts[0]["shift"], starts[0]["squeeze"]) != (starts[1]["shift"], starts[1]["squeeze"])
    assert -.5 < starts[0]["shift"] < starts[1]["shift"] < 0
    asymmetric = FE.controlled_starts(
        {"NO2": {"sh_mode": "Center", "sh_val": "-5,2", "sq_mode": "Fix", "sq_val": "1"}},
        "NO2", .5)
    assert -5.5 < asymmetric[0]["shift"] < asymmetric[1]["shift"] < -4.5


def test_t2_tri_state_never_turns_no_anchor_into_pass():
    class Engine:
        gas_list = ["NO2"]
        raw_references = {"NO2": np.sin(np.linspace(0, 20, 101))}

    state = FE.t2_tri_state(Engine(), {"px_min": 0, "px_max": 100, "poly": 2}, [])
    assert state["state"] == "UNAVAILABLE"


def test_evaluator_injects_two_distinct_final_starts():
    class Engine:
        _wave_axis = np.arange(101.)
        gas_list = ["NO2", "H2O"]
        raw_references = {"NO2": np.sin(np.linspace(0, 20, 101)),
                          "H2O": np.cos(np.linspace(0, 20, 101))}
    seen = []
    original = FE.PO.fit_scan
    FE.PO.fit_scan = lambda *args, **kwargs: (seen.append(kwargs["controlled_start"]) or
        {"conc": 1., "rms_sig": .1, "perr_rel": .2, "autocorr1": 0., "coeffs": {}})
    FE.t2_tri_state, old_t2 = (lambda *args, **kwargs: {"state": "UNAVAILABLE"}), FE.t2_tri_state
    FE.FP.differential_collinearity, old_diag = (lambda *args, **kwargs: {
        "multiple_R": {"NO2": .2}}), FE.FP.differential_collinearity
    try:
        starts = [{"id": "a", "shift": -2., "squeeze": 1., "provenance": "test"},
                  {"id": "b", "shift": 2., "squeeze": 1., "provenance": "test"}]
        scans = [{"id": "s", "wave": np.arange(101), "alpha": np.zeros(101),
                  "T_C": 25., "P_mbar": 1013.}]
        FE.evaluate_candidate(Engine(), None, {}, scans, {"id": "c", "px_min": 0, "px_max": 100,
                                                     "poly": 2}, starts, .5, True)
    finally:
        FE.PO.fit_scan, FE.t2_tri_state = original, old_t2
        FE.FP.differential_collinearity = old_diag
    assert seen == [(-2., 1.), (2., 1.)]


def test_multistart_changes_target_theta_only_not_bounds():
    class Engine:
        gas_list = ["NO2", "H2O"]
    fitter = DoasFitter(Engine())
    props = {"NO2": {"sh_mode": "Limit", "sh_val": "-1,1", "sq_mode": "Fix", "sq_val": "1"},
             "H2O": {"sh_mode": "Limit", "sh_val": "-1,1", "sq_mode": "Fix", "sq_val": "1"}}
    a = fitter.setup_fit_parameters(props, 0., [0., 1.], .5,
                                    initial_values={"NO2_sh": -.4})
    b = fitter.setup_fit_parameters(props, 0., [0., 1.], .5,
                                    initial_values={"NO2_sh": .4})
    assert a[4:] == b[4:]
    assert a[3][a[0].index("NO2_sh")] != b[3][b[0].index("NO2_sh")]
    assert a[3][a[0].index("H2O_sh")] == b[3][b[0].index("H2O_sh")]


def test_t2_nan_and_partial_are_unavailable():
    class Engine:
        gas_list = ["NO2", "O4"]
        raw_references = {"NO2": np.sin(np.linspace(0, 20, 101)),
                          "O4": np.cos(np.linspace(0, 20, 101))}
        multipliers = {"NO2": 1., "O4": 1.}
        scaling_factors = {"NO2": 1., "O4": 1.}
    candidate = {"px_min": 0, "px_max": 100, "poly": 2}
    nan_row = {"T_C": float("nan"), "P_mbar": 1013., "result": {"coeffs": {"O4": 1.}}}
    assert FE.t2_tri_state(Engine(), candidate, [nan_row], expected_count=1)["state"] == "UNAVAILABLE"
    good = {"T_C": 25., "P_mbar": 1013., "result": {"coeffs": {"O4": 1e-30}}}
    assert FE.t2_tri_state(Engine(), candidate, [good], expected_count=2)["state"] == "UNAVAILABLE"
    bad_types = {"T_C": None, "P_mbar": "bad", "result": {"coeffs": {"O4": "nan"}}}
    assert FE.t2_tri_state(Engine(), candidate, [bad_types], expected_count=1)["state"] == "UNAVAILABLE"
    assert FE.finite_or_none(None) is None and FE.finite_or_none("bad") is None
    assert FE.finite_or_none(float("inf")) is None


def test_t2_nonnumeric_collinearity_is_unavailable():
    class Engine:
        gas_list = ["NO2"]
    original = FE.FP.differential_collinearity
    try:
        for bad in (None, "bad"):
            FE.FP.differential_collinearity = lambda *args, value=bad, **kwargs: {
                "multiple_R": {"NO2": value}}
            verdict = FE.t2_tri_state(Engine(), {"px_min": 0, "px_max": 10, "poly": 2}, [])
            assert verdict["state"] == "UNAVAILABLE"
            assert verdict["details"]["target_multiple_R"] is None
    finally:
        FE.FP.differential_collinearity = original


def test_status_and_coordinate_contracts():
    assert FE.overall_status([{"evaluation_state": "EVALUATED_FAIL"}]) == "ABSTAIN"
    assert FE.overall_status([{"evaluation_state": "INCOMPLETE"}]) == "ABSTAIN_INCOMPLETE"
    scan = {"id": "x", "wave": np.arange(101.), "alpha": np.zeros(101), "px_start": 10}
    assert FE.validate_coordinates(np.arange(200.), [scan],
                                   [{"px_min": 9, "px_max": 100, "poly": 2}])
    assert FE.validate_coordinates(np.arange(200.), [scan],
                                   [{"px_min": 10, "px_max": 111, "poly": 2}])


def test_stage0_preflight_is_conservative_and_fit_free():
    class Engine:
        _wave_axis = np.arange(8.)
        gas_list = ["NO2", "H2O"]
        raw_references = {"NO2": np.arange(8.), "H2O": np.arange(8.)[::-1]}
    eng = Engine()
    candidate = {"id": "c", "px_min": 0, "px_max": 7, "poly": 2}
    original_diag, original_fit = FE.FP.differential_collinearity, FE.PO.fit_scan
    calls = []
    try:
        FE.FP.differential_collinearity = lambda *a, **k: {"multiple_R": {"NO2": .2}}
        assert FE.stage0_preflight(eng, candidate)["state"] == "PASS"
        for bad, code in [
            ({**candidate, "px_min": 0.0}, "CANDIDATE_FIELDS_INVALID"),
            ({**candidate, "px_min": -1}, "CANDIDATE_BOUNDS_INVALID"),
            ({**candidate, "px_max": 8}, "CANDIDATE_OUTSIDE_ENGINE_DOMAIN"),
            ({**candidate, "poly": 7}, "POLY_UNDERDETERMINED")]:
            verdict = FE.stage0_preflight(eng, bad)
            assert verdict["state"] == "FAIL" and code in verdict["reason_codes"]
        saved = eng.raw_references.pop("H2O")
        assert FE.stage0_preflight(eng, candidate)["state"] == "FAIL"
        eng.raw_references["H2O"] = saved
        eng.raw_references["H2O"] = np.arange(7.)
        assert FE.stage0_preflight(eng, candidate)["state"] == "FAIL"
        eng.raw_references["H2O"] = saved
        outside_nan = saved.copy()
        outside_nan[0] = np.nan
        eng.raw_references["H2O"] = outside_nan
        inner = {**candidate, "px_min": 1}
        assert FE.stage0_preflight(eng, inner)["state"] == "PASS"
        eng.raw_references["H2O"][1] = np.nan
        assert FE.stage0_preflight(eng, inner)["state"] == "FAIL"
        eng.raw_references["H2O"] = saved
        assert FE.stage0_preflight(eng, candidate, "O4")["state"] == "FAIL"
        FE.FP.differential_collinearity = lambda *a, **k: {
            "multiple_R": {"NO2": FE.FP.COLLIN_HI_DEFAULT}}
        assert FE.stage0_preflight(eng, candidate)["state"] == "PASS"
        FE.FP.differential_collinearity = lambda *a, **k: {
            "multiple_R": {"NO2": np.nextafter(FE.FP.COLLIN_HI_DEFAULT, np.inf)}}
        assert FE.stage0_preflight(eng, candidate)["state"] == "FAIL"
        FE.FP.differential_collinearity = lambda *a, **k: {"multiple_R": {"NO2": np.nan}}
        assert FE.stage0_preflight(eng, candidate)["state"] == "UNAVAILABLE"
        FE.PO.fit_scan = lambda *a, **k: calls.append(1)
        rows = FE.evaluate_candidate(eng, None, {}, [], candidate, [], .5, True)
        assert rows["evaluation_state"] == "UNEVALUATED" and not calls
        failed = FE.evaluate_candidate(eng, None, {}, [], {**candidate, "px_max": 8}, [], .5, True)
        assert failed["evaluation_state"] == "UNEVALUATED" and not calls
        secret = r"C:\Users\secret\reference.txt"
        FE.FP.differential_collinearity = lambda *a, **k: (_ for _ in ()).throw(RuntimeError(secret))
        unavailable = FE.stage0_preflight(eng, candidate)
        assert unavailable["state"] == "UNAVAILABLE"
        assert secret not in json.dumps(unavailable)
    finally:
        FE.FP.differential_collinearity, FE.PO.fit_scan = original_diag, original_fit
    assert candidate == {"id": "c", "px_min": 0, "px_max": 7, "poly": 2}
    assert eng.gas_list == ["NO2", "H2O"]

    class BadWave(Engine):
        _wave_axis = np.array([0., 1., 1.])
        raw_references = {"NO2": np.ones(3), "H2O": np.ones(3)}
    assert FE.stage0_preflight(BadWave(), {**candidate, "px_max": 2})["state"] == "FAIL"
    eng.gas_list = ["NO2", "NO2"]
    assert FE.stage0_preflight(eng, candidate)["state"] == "FAIL"

    assert FE.overall_status([{"evaluation_state": "UNEVALUATED",
                               "stage0_preflight": {"state": "FAIL"}}]) == "ABSTAIN"
    assert FE.overall_status([{"evaluation_state": "UNEVALUATED",
                               "stage0_preflight": {"state": "UNAVAILABLE"}}]) == "ABSTAIN_INCOMPLETE"


def test_early_policy_abstain_cannot_overwrite_alpha_input():
    with tempfile.TemporaryDirectory() as td:
        alpha = os.path.join(td, "alpha.dat")
        with open(alpha, "wb") as fh:
            fh.write(b"immutable-alpha")
        before = FE.sha256_file(alpha)
        try:
            FE.ensure_output_safe(alpha, [alpha])  # guard runs before policy ABSTAIN writes
        except ValueError:
            pass
        else:
            raise AssertionError("alpha/report collision was not rejected")
        assert FE.sha256_file(alpha) == before


def test_json_schema_and_no_apply():
    report = {"schema_version": FE.SCHEMA_VERSION, "status": "EVALUATED_NO_PLATEAU_CLAIM",
              "provenance": {"git": {"head": "abc", "dirty": True}},
              "candidates": [], "value": float("nan"),
              "limitations": ["No Apply"]}
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "report.json")
        FE.write_report(path, report)
        loaded = json.load(open(path, encoding="utf-8"))
    assert loaded["schema_version"] == 1
    assert loaded["value"] is None
    assert "apply" not in loaded
    assert "No Apply" in loaded["limitations"]


def main():
    test_candidates_and_starts()
    test_t2_tri_state_never_turns_no_anchor_into_pass()
    test_evaluator_injects_two_distinct_final_starts()
    test_multistart_changes_target_theta_only_not_bounds()
    test_t2_nan_and_partial_are_unavailable()
    test_t2_nonnumeric_collinearity_is_unavailable()
    test_status_and_coordinate_contracts()
    test_stage0_preflight_is_conservative_and_fit_free()
    test_early_policy_abstain_cannot_overwrite_alpha_input()
    test_json_schema_and_no_apply()
    print("test_fit_explorer: PASS")


if __name__ == "__main__":
    main()
