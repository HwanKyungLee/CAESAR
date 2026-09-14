"""Actual VARPRO through frozen selection/holdout; synthetic thresholds only."""
import copy
import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import fit_explorer as FE
from core.fit_explorer_v2_runtime import run_recommendation, _assess, COEFFICIENT_UNIT


def fixture(root):
    wave = np.linspace(430., 460., 121)
    ref = 1e-19 * (2 + np.sin(np.arange(121) * .37))
    observations, bindings = [], {}
    rng = np.random.default_rng(318)
    for index, obs in enumerate(("discovery", "holdout")):
        alpha = 1e-7 + ref * (1e11 + index * 3e10) + rng.normal(0., 1e-12, len(ref))
        path = os.path.join(root, obs + ".dat")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# wavelength_nm: " + "\t".join(map(str, wave)) + "\n")
            f.write("row_idx\tT_C\tP_mbar\t" + "\t".join(f"px{i}" for i in range(121)) + "\n")
            f.write("0\t25\t1013.25\t" + "\t".join(map(str, alpha)) + "\n")
        observations.append({"observation_id": obs, "content_hash": FE.sha256_file(path),
                             "date": f"2099-01-0{index + 1}", "block_id": obs, "previously_used": False})
        bindings[obs] = {"path": path, "row_index": 0}
    mission = {"schema": "explorer-mission-v2", "mission_id": "synthetic-chain",
        "channels": [{"channel_id": "opaque", "alpha_inputs": observations,
            "wavelength": {"unit": "nm", "values": wave.tolist()},
            "references": [{"species_id": "Species_X", "wavelength_nm": wave.tolist(),
                "values": ref.tolist(), "cross_section_unit": "cm2/molecule", "ils_state": "ALREADY_CONVOLVED"}]}],
        "search_policy": {"windows_nm": [[432., 457.], [433., 457.]], "poly_degrees": [2, 3],
            "registration_policies": [{"driver_species": "Species_X", "shift": {"mode": "Limit", "lower": -.5, "upper": .5},
                                       "squeeze": {"mode": "Fix", "value": 1.}}],
            "split": {"discovery": ["discovery"], "validation": [], "holdout": ["holdout"]},
            "budget": {"max_fit_attempts": 24, "closure_max_attempts": 4}}}
    criteria = {"schema": "explorer-v2-criteria-v1", "scope": "SYNTHETIC_CONTRACT_TEST",
        "basis": "Synthetic known 1e-12 noise test only; not transferable to field missions",
        "registration_seed": {"shift_abs_px": .01, "squeeze_abs_factor": 1e-5,
                              "basis": "Synthetic fixed squeeze and known common shift only"},
        "max_abs_ac1": .9, "max_multiple_R": .95, "min_differential_fraction": .01,
        "species": {"Species_X": {"unit": COEFFICIENT_UNIT, "seed_abs": 1e-10, "seed_rel": .01,
            "model_abs": 1e-10, "model_rel": .01, "signal_floor": 1e-9,
            "signal_floor_basis": "Synthetic generator signal 2e-8; noise 1e-12 only"}}}
    return mission, bindings, criteria


def main():
    with tempfile.TemporaryDirectory() as root:
        mission, bindings, criteria = fixture(root)
        ledger = os.path.join(root, "history.sqlite3")
        result = run_recommendation(mission, bindings, root, criteria=criteria, history_path=ledger)
        assert result["status"] == "MISSION_RECOMMENDED", json.dumps(result, indent=2)
        assert result["scope"] == "SYNTHETIC_CONTRACT_TEST"
        assert result["holdout"]["independent"]
        assert result["consumed_fit_attempts"] == 16, result["consumed_fit_attempts"]
        frozen_path = os.path.join(root, result["execution_hash"], "selection.json")
        with open(frozen_path, encoding="utf-8") as f:
            frozen = json.load(f)
        assert frozen["channels"]["opaque"]["candidate_id"] == result["channels"]["opaque"]["candidate_id"]
        assert "checks" not in frozen["channels"]["opaque"]  # no held-out result existed at selection time
        assert result == run_recommendation(mission, bindings, root, criteria=criteria, history_path=ledger)
        changed = copy.deepcopy(mission)
        changed["search_policy"]["poly_degrees"] = [2, 3, 4]
        reused = run_recommendation(changed, bindings, os.path.join(root, "other-output"),
                                    criteria=criteria, history_path=ledger)
        assert not reused["holdout"]["independent"] and reused["status"] != "MISSION_RECOMMENDED"
        provisional = run_recommendation(mission, bindings, os.path.join(root, "without-criteria"), history_path=ledger)
        assert provisional["status"] == "PROVISIONAL"
        assert provisional["channels"]["opaque"]["candidate_id"]
        limited = copy.deepcopy(mission)
        limited["search_policy"]["budget"]["max_fit_attempts"] = 2
        limited["search_policy"]["budget"]["closure_max_attempts"] = 0
        budget = run_recommendation(limited, bindings, os.path.join(root, "budget"), history_path=ledger)
        assert budget["consumed_fit_attempts"] == 2 and budget["status"] != "MISSION_RECOMMENDED"
        missing_dates = copy.deepcopy(mission)
        del missing_dates["channels"][0]["alpha_inputs"][0]["date"]
        dates = run_recommendation(missing_dates, bindings, os.path.join(root, "dates"), criteria=criteria,
                                   history_path=os.path.join(root, "date-history.sqlite3"))
        assert not dates["holdout"]["independent"] and dates["status"] != "MISSION_RECOMMENDED"
        exposed = copy.deepcopy(mission)
        exposed["channels"][0]["alpha_inputs"][1]["previously_used"] = True
        exposure = run_recommendation(exposed, bindings, os.path.join(root, "exposure"), criteria=criteria,
                                      history_path=os.path.join(root, "exposure-history.sqlite3"))
        assert not exposure["holdout"]["independent"] and exposure["status"] != "MISSION_RECOMMENDED"
        # This same real evidence must not hide missing species, failed solver, or divergent roots.
        directory = os.path.join(root, result["execution_hash"])
        evidence_dir = os.path.join(directory, result["phase_evidence"]["discovery"])
        with open(os.path.join(evidence_dir, "result.json"), encoding="utf-8") as f:
            report = json.load(f)["reports"][0]
        alias = copy.deepcopy(report)
        alias["attempts"][1]["final_shift"] += 5
        assert _assess(alias, ["Species_X"], criteria)["state"] == "EVALUATED_FAIL"
        limited_support = copy.deepcopy(report)
        limited_support["attempts"][0]["reference_support_valid"]["Species_X"] = False
        assert _assess(limited_support, ["Species_X"], criteria)["state"] == "UNEVALUATED"
        boundary = copy.deepcopy(report)
        boundary["attempts"][0]["boundary_hits"] = [{"parameter": "shift"}]
        assert _assess(boundary, ["Species_X"], criteria)["state"] == "UNEVALUATED"
        report["attempts"][1]["coeffs"]["Species_X"] *= 1000
        assert _assess(report, ["Species_X"], criteria)["state"] == "EVALUATED_FAIL"
        report["attempts"][0]["solver_termination"]["success"] = False
        assert not _assess(report, ["Species_X"], criteria)["numeric_complete"]
        del report["attempts"][0]["coeffs"]["Species_X"]
        assert not _assess(report, ["Species_X"], criteria)["species"]["Species_X"]["finite_complete"]
        print("test_fit_explorer_v2_chain: PASS (actual fit, selection, holdout, resume, reused history, budget, divergent roots)")


if __name__ == "__main__":
    main()
