import os
import sys
import copy
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import fit_explorer as FE
from core.doas_fit import (DoasFitter, _aggregate_solver_termination,
                           _endpoint_objectives)


def test_zero_base_grid_is_explicit_and_deterministic():
    cfg = {"f_min": 100, "f_max": 200, "poly_deg": 4}
    wave = np.linspace(430.0, 480.0, 401)
    a = FE.zero_base_policy_candidates(cfg, wave)
    b = FE.zero_base_policy_candidates(cfg, wave)
    assert len(a) == 315
    assert [x["id"] for x in a] == [x["id"] for x in b]
    assert all(x["refs_source"] == "FitSet.cfg.refs" for x in a)
    assert all(x["policy_stage"] == "STAGE0_METADATA_ONLY" for x in a)
    assert {x["window_offset_nm"] for x in a} == {-1.0, 0.0, 1.0}
    assert {x["policy"]["shift"]["mode"] for x in a} == {"Fix", "Limit"}


def test_zero_base_rejects_collapsed_nm_offsets():
    cfg = {"f_min": 100, "f_max": 200, "poly_deg": 4}
    wave = np.linspace(430.0, 480.0, 401)
    try:
        FE.zero_base_policy_candidates(cfg, wave, window_offsets_nm=(-0.01, 0.0, 0.01))
    except ValueError as exc:
        assert "duplicate pixel deltas" in str(exc)
    else:
        raise AssertionError("collapsed offsets must fail closed")


def test_zero_base_stage0_is_fit_free_and_counts():
    class Engine:
        _wave_axis = np.arange(300.0)
        gas_list = ["NO2"]
        raw_references = {"NO2": np.ones(300)}

    candidates = [{"id": "pass", "px_min": 100, "px_max": 200, "poly": 2},
                  {"id": "bad", "px_min": 100, "px_max": 999, "poly": 2}]
    with patch.object(FE.FP, "differential_collinearity",
                      return_value={"multiple_R": {"NO2": 0.1}}):
        report = FE.stage0_candidate_grid(Engine(), candidates)
    assert report["fit_executed"] is False
    assert report["counts"] == {"PASS": 1, "FAIL": 1, "UNAVAILABLE": 0}
    assert report["candidates"][1]["stage0_preflight"]["state"] == "FAIL"


def _translation_fixture():
    cfg = {"f_min": 100, "f_max": 200, "poly_deg": 4,
           "refs": [{"name": "H2O"}, {"name": "NO2"}]}
    props = {
        "H2O": {"sh_mode": "Link", "sh_val": "NO2",
                "sq_mode": "Link", "sq_val": "NO2", "mult": -12},
        "NO2": {"sh_mode": "Center", "sh_val": "-2, 3",
                "sq_mode": "Fix", "sq_val": "1.0", "mult": 0},
    }
    wave = np.linspace(430.0, 480.0, 401)
    candidates = FE.zero_base_policy_candidates(cfg, wave)
    unique = {}
    for candidate in candidates:
        key = repr(candidate["policy"])
        unique.setdefault(key, candidate)
    assert len(unique) == 35
    return cfg, props, list(unique.values())


def test_policy_translation_all_35_round_trip_through_worker():
    cfg, props, candidates = _translation_fixture()
    original_cfg, original_props = copy.deepcopy(cfg), copy.deepcopy(props)
    fake = SimpleNamespace(engine=SimpleNamespace(gas_list=["H2O", "NO2"]))
    for candidate in candidates:
        original_candidate = copy.deepcopy(candidate)
        translated = FE.translate_zero_base_policy(cfg, props, candidate)
        derived = translated["ref_props"]
        assert derived["H2O"] == props["H2O"]
        active, fixed, linked, _, lower, upper = DoasFitter.setup_fit_parameters(
            fake, derived, 0.0, [0.0, 1.0], 1e6)
        policy = candidate["policy"]
        shift = policy["shift"]
        squeeze = policy["squeeze"]
        if shift["mode"] == "Fix":
            assert fixed["NO2_sh"] == shift["value"]
        else:
            index = active.index("NO2_sh")
            assert (lower[index], upper[index]) == (shift["lower"], shift["upper"])
        if squeeze["mode"] == "Fix":
            assert fixed["NO2_sq"] == squeeze["value"]
            assert derived["NO2"]["sq_val"] == "0.0"
        else:
            index = active.index("NO2_sq")
            assert np.allclose((lower[index], upper[index]),
                               (squeeze["lower"], squeeze["upper"]),
                               rtol=0.0, atol=1e-15)
        assert linked["H2O_sh"] == "NO2_sh"
        assert linked["H2O_sq"] == "NO2_sq"
        assert translated["provenance"]["fit_executed"] is False
        assert candidate == original_candidate
    assert cfg == original_cfg
    assert props == original_props


def test_policy_translation_malformed_fails_closed():
    cfg, props, candidates = _translation_fixture()
    base = candidates[0]
    malformed = []
    wrong_stage = copy.deepcopy(base)
    wrong_stage["policy_stage"] = "STAGE1"
    malformed.append(wrong_stage)
    extra = copy.deepcopy(base)
    extra["policy"]["shift"]["extra"] = 1
    malformed.append(extra)
    nan_value = copy.deepcopy(base)
    nan_value["policy"]["shift"] = {"mode": "Fix", "value": float("nan")}
    malformed.append(nan_value)
    reversed_bounds = copy.deepcopy(base)
    reversed_bounds["policy"]["squeeze"] = {"mode": "Limit", "lower": 1.1, "upper": 0.9}
    malformed.append(reversed_bounds)
    bad_fix = copy.deepcopy(base)
    bad_fix["policy"]["squeeze"] = {"mode": "Fix", "value": 1.1}
    malformed.append(bad_fix)
    string_value = copy.deepcopy(base)
    string_value["policy"]["shift"] = {"mode": "Fix", "value": "0.0"}
    malformed.append(string_value)
    missing_id = copy.deepcopy(base)
    del missing_id["id"]
    malformed.append(missing_id)
    for candidate in malformed:
        try:
            FE.translate_zero_base_policy(cfg, props, candidate)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed policy must fail closed")

    missing_target = copy.deepcopy(cfg)
    missing_target["refs"] = [{"name": "H2O"}]
    try:
        FE.translate_zero_base_policy(missing_target, props, base)
    except ValueError as exc:
        assert "target" in str(exc)
    else:
        raise AssertionError("missing target must fail closed")


def test_stage1_one_candidate_budget_and_worker_contract():
    cfg, props, candidates = _translation_fixture()
    original_cfg, original_props = copy.deepcopy(cfg), copy.deepcopy(props)
    scans = [{"id": f"scan{i}"} for i in range(4)]

    def worker(candidate, scan, start, *, ref_props, policy_bounds,
               allow_negative_gas):
        assert allow_negative_gas is True
        assert ref_props["H2O"] == props["H2O"]
        assert ref_props["NO2"]["sh_mode"] == candidate["policy"]["shift"]["mode"]
        assert set(policy_bounds) == {"shift", "squeeze"}
        return {"initial_shift": start["shift"],
                "initial_squeeze": start["squeeze"],
                "final_shift": start["shift"],
                "final_squeeze": start["squeeze"],
                "objective_initial": 10.0, "objective_final": 8.0,
                "solver_termination": {"status": "CONVERGED", "success": True,
                                       "nfev": 3},
                "boundary_hits": []}

    fixed = next(c for c in candidates
                 if c["policy"]["shift"]["mode"] == "Fix"
                 and c["policy"]["squeeze"]["mode"] == "Fix")
    fixed_report = FE.run_stage1_vertical_slice(
        cfg, props, fixed, scans, worker, allow_negative_gas=True)
    assert fixed_report["status"] == "COMPLETE"
    assert fixed_report["planned_attempts"] == 4
    assert fixed_report["budget"]["attempts_per_scan"] == 1
    assert fixed_report["budget"]["seed_stability"] == "NOT_APPLICABLE"
    assert fixed_report["translation"]["scope"] == "TRANSLATION_ONLY_NO_FIT_CLAIM"
    assert fixed_report["translation"]["details"]["fit_executed"] is False
    assert all(row["objective_change"] == -2.0 for row in fixed_report["attempts"])

    modes = (("Limit", "Fix"), ("Fix", "Limit"), ("Limit", "Limit"))
    for sh_mode, sq_mode in modes:
        active = next(c for c in candidates
                      if c["policy"]["shift"]["mode"] == sh_mode
                      and c["policy"]["squeeze"]["mode"] == sq_mode)
        active_report = FE.run_stage1_vertical_slice(
            cfg, props, active, scans, worker, allow_negative_gas=True)
        assert active_report["status"] == "COMPLETE"
        assert active_report["planned_attempts"] == 8
        assert active_report["budget"]["attempts_per_scan"] == 2
        assert active_report["budget"]["seed_stability"] == "PENDING"
        starts = active_report["budget"]["starts"]
        assert len({(s["shift"], s["squeeze"]) for s in starts}) == 2
        assert len({(r["scan_id"], r["start_id"])
                    for r in active_report["attempts"]}) == 8

    active = next(c for c in candidates
                  if c["policy"]["shift"]["mode"] == "Limit"
                  and c["policy"]["squeeze"]["mode"] == "Limit")

    incomplete = FE.run_stage1_vertical_slice(
        cfg, props, active, scans, lambda *a, **k: {}, allow_negative_gas=True)
    assert incomplete["status"] == "ABSTAIN_INCOMPLETE"
    assert incomplete["successful_attempts"] == 0
    assert all(row["exception_class"] == "ValueError" for row in incomplete["attempts"])
    try:
        FE.run_stage1_vertical_slice(cfg, props, active, scans, worker,
                                     allow_negative_gas=False)
    except ValueError as exc:
        assert "explicit" in str(exc)
    else:
        raise AssertionError("implicit/nonnegative Stage 1 policy was accepted")
    assert cfg == original_cfg and props == original_props


def test_stage1_worker_output_cannot_override_or_leak():
    cfg, props, candidates = _translation_fixture()
    scans = [{"id": f"scan{i}"} for i in range(4)]
    fixed = next(c for c in candidates
                 if c["policy"]["shift"]["mode"] == "Fix"
                 and c["policy"]["squeeze"]["mode"] == "Fix")

    def bad_extra(candidate, scan, start, **kwargs):
        return {"initial_shift": start["shift"], "initial_squeeze": start["squeeze"],
                "final_shift": start["shift"], "final_squeeze": start["squeeze"],
                "objective_initial": 2.0, "objective_final": 1.0,
                "solver_termination": {"status": "OK", "success": True, "nfev": 1},
                "boundary_hits": [], "status": "OK", "path": "C:\\secret\\raw.txt"}

    report = FE.run_stage1_vertical_slice(
        cfg, props, fixed, scans, bad_extra, allow_negative_gas=True)
    assert report["status"] == "ABSTAIN_INCOMPLETE"
    assert all("path" not in row and row["status"] == "UNAVAILABLE"
               for row in report["attempts"])

    def changed_fixed(candidate, scan, start, **kwargs):
        row = bad_extra(candidate, scan, start, **kwargs)
        row.pop("status"); row.pop("path")
        row["final_shift"] += 1e-6
        return row

    report = FE.run_stage1_vertical_slice(
        cfg, props, fixed, scans, changed_fixed, allow_negative_gas=True)
    assert report["status"] == "ABSTAIN_INCOMPLETE"
    assert all(row["exception_class"] == "ValueError" for row in report["attempts"])

    def sensitive_termination(candidate, scan, start, **kwargs):
        row = changed_fixed(candidate, scan, start, **kwargs)
        row["final_shift"] = start["shift"]
        row["solver_termination"] = {"status": "C:\\secret\\solver.log",
                                     "success": True, "nfev": 1}
        return row

    report = FE.run_stage1_vertical_slice(
        cfg, props, fixed, scans, sensitive_termination, allow_negative_gas=True)
    assert report["status"] == "ABSTAIN_INCOMPLETE"
    assert "secret" not in repr(report)


def test_production_adapter_maps_real_engine_contract():
    cfg, props, candidates = _translation_fixture()
    candidate = next(c for c in candidates
                     if c["policy"]["shift"]["mode"] == "Limit"
                     and c["policy"]["squeeze"]["mode"] == "Limit")
    scan = {"id": "s0", "wave": np.arange(300.), "alpha": np.ones(300),
            "temperature_C": 25., "pressure_mbar": 1013., "px_start": 0}
    class Fitter:
        pass
    engine = SimpleNamespace(gas_list=["H2O", "NO2"])
    translated = FE.translate_zero_base_policy(cfg, props, candidate)["ref_props"]
    with patch.object(FE.PO, "fit_scan") as mocked:
        mocked.return_value = {
            "shifts": {"NO2": candidate["policy"]["shift"]["lower"]},
            "squeezes": {"NO2": 1.0},
            "solver_diagnostics": {"objective_initial": 4.0,
                                   "objective_final": 1.0,
                                   "solver_termination": {
                                       "status": "CONVERGED", "success": True,
                                       "nfev": 7}}}
        callback = FE.production_stage1_callback(engine, Fitter(), cfg)
        start = FE.stage1_policy_starts(candidate)["starts"][0]
        bounds = {"shift": {"mode": "INTERVAL", **{
                      "lower": candidate["policy"]["shift"]["lower"],
                      "upper": candidate["policy"]["shift"]["upper"]}},
                  "squeeze": {"mode": "INTERVAL", **{
                      "lower": candidate["policy"]["squeeze"]["lower"],
                      "upper": candidate["policy"]["squeeze"]["upper"]}}}
        out = callback(candidate, scan, start, ref_props=translated,
                       policy_bounds=bounds, allow_negative_gas=True)
    assert out["solver_termination"]["nfev"] == 7
    assert out["boundary_hits"] == [{"parameter": "shift", "side": "lower",
                                     "value": bounds["shift"]["lower"],
                                     "bound": bounds["shift"]["lower"]}]
    assert mocked.call_args.kwargs["return_solver_diagnostics"] is True
    assert mocked.call_args.kwargs["allow_negative_gas"] is True


def test_solver_diagnostics_are_comparable_and_max_nfev_reachable():
    termination = _aggregate_solver_termination([
        {"status": 1, "success": True, "nfev": 3},
        {"status": 0, "success": False, "nfev": 9}])
    assert termination == {"status": "MAX_NFEV", "success": False, "nfev": 12}
    final_irls_weight = 3.0
    calls = []
    def final_objective(theta):
        calls.append(float(theta[0]))
        return np.array([final_irls_weight * (theta[0] - 2.0)])
    initial, final = _endpoint_objectives(final_objective, [0.0], [1.0])
    assert calls == [0.0, 1.0]
    assert initial == 36.0 and final == 9.0


if __name__ == "__main__":
    test_zero_base_grid_is_explicit_and_deterministic()
    test_zero_base_rejects_collapsed_nm_offsets()
    test_zero_base_stage0_is_fit_free_and_counts()
    test_policy_translation_all_35_round_trip_through_worker()
    test_policy_translation_malformed_fails_closed()
    test_stage1_one_candidate_budget_and_worker_contract()
    test_stage1_worker_output_cannot_override_or_leak()
    test_production_adapter_maps_real_engine_contract()
    test_solver_diagnostics_are_comparable_and_max_nfev_reachable()
    print("test_zero_base_candidates: PASS")
