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
    seen = []
    original = FE.PO.fit_scan
    FE.PO.fit_scan = lambda *args, **kwargs: (seen.append(kwargs["controlled_start"]) or
        {"conc": 1., "rms_sig": .1, "perr_rel": .2, "autocorr1": 0., "coeffs": {}})
    FE.t2_tri_state, old_t2 = (lambda *args, **kwargs: {"state": "UNAVAILABLE"}), FE.t2_tri_state
    try:
        starts = [{"id": "a", "shift": -2., "squeeze": 1., "provenance": "test"},
                  {"id": "b", "shift": 2., "squeeze": 1., "provenance": "test"}]
        scans = [{"id": "s", "wave": np.arange(101), "alpha": np.zeros(101),
                  "T_C": 25., "P_mbar": 1013.}]
        FE.evaluate_candidate(None, None, {}, scans, {"id": "c", "px_min": 0, "px_max": 100,
                                                     "poly": 2}, starts, .5, True)
    finally:
        FE.PO.fit_scan, FE.t2_tri_state = original, old_t2
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
    test_early_policy_abstain_cannot_overwrite_alpha_input()
    test_json_schema_and_no_apply()
    print("test_fit_explorer: PASS")


if __name__ == "__main__":
    main()
