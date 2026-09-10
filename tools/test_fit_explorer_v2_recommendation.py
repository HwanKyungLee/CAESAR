"""V2 recommendation/explicit export contract checks."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import fit_explorer_v2 as V2


def _plan():
    return {"plan_hash": "p" * 64, "input_hash": "i" * 64, "requested_species": ["Species_A"],
            "candidates": [{"candidate_id": "c", "px_min": 10, "px_max": 80, "poly": 2,
                            "runtime_spec": {"f_min": 10, "f_max": 80, "poly_deg": 2,
                                             "reference_order": ["Species_A"]},
                            "registration": {"driver_species": "Species_A",
                                "shift": {"mode": "Limit", "lower": -1., "upper": 1.},
                                "squeeze": {"mode": "Limit", "lower": .9999, "upper": 1.0001}}}],
            "split": {"discovery": ["d"], "validation": [], "holdout": ["h"]}}


def _graph():
    return {"schema": "explorer-v2-graph-closure-v1", "components": [
        {"state": "CLOSED_INTERNAL_COMPONENT", "representative_candidate_id": "c"}]}


def _assessments(state="IDENTIFIED"):
    return {"c": {"internal_state": "PASS", "numerical_state": state,
                  "species": {"Species_A": "PASS"}}}


def _base():
    return {"refs": [{"name": "Species_A", "path": "reference.dat", "mult": 0}],
            "ref_props": {"Species_A": {"sh_mode": "Limit", "sh_val": "-2, 2",
                                           "sq_mode": "Limit", "sq_val": "-0.001, 0.001",
                                           "t_ref": 25., "t_coeff": 0., "active_bands_nm": ""}},
            "f_min": 0, "f_max": 100, "poly_deg": 2, "step_limit": .5}


def test_recommendation_requires_independent_holdout_but_not_external_anchor():
    plan = _plan()
    recommended = V2.build_recommendation(plan, _graph(), _assessments(),
        {"observation_ids": ["h"], "candidate_states": {"c": "PASS"}})
    assert recommended["status"] == "MISSION_RECOMMENDED"
    provisional = V2.build_recommendation(plan, _graph(), _assessments())
    assert provisional["status"] == "PROVISIONAL"
    assert V2.build_recommendation(plan, _graph(), _assessments("MULTIPLE_SOLUTIONS"),
        {"observation_ids": ["h"], "candidate_states": {"c": "PASS"}})["status"] == "ABSTAIN"
    try:
        V2.build_recommendation(plan, _graph(), _assessments(),
            {"observation_ids": ["d"], "candidate_states": {"c": "PASS"}})
    except ValueError:
        pass
    else:
        raise AssertionError("reused discovery row was accepted as holdout")


def test_export_is_explicit_roundtripped_and_never_overwrites():
    plan = _plan(); candidate = plan["candidates"][0]
    recommendation = V2.build_recommendation(plan, _graph(), _assessments())
    original = _base()
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "export.json")
        result = V2.export_recommended_fitset(original, candidate, recommendation, path)
        assert result["active_fitset_changed"] is False
        exported = json.load(open(path, encoding="utf-8"))
        assert exported["f_min"] == 10 and exported["ref_props"]["Species_A"]["sh_val"] == "-1.0, 1.0"
        try:
            V2.export_recommended_fitset(original, candidate, recommendation, path)
        except FileExistsError:
            pass
        else:
            raise AssertionError("existing export was overwritten")
        bad = copy.deepcopy(candidate); bad["registration"].pop("shift")
        try:
            V2.export_recommended_fitset(original, bad, recommendation, os.path.join(root, "bad.json"))
        except ValueError:
            pass
        else:
            raise AssertionError("candidate without registration policy was exported")
    assert original == _base()


def main():
    test_recommendation_requires_independent_holdout_but_not_external_anchor()
    test_export_is_explicit_roundtripped_and_never_overwrites()
    print("test_fit_explorer_v2_recommendation: PASS")


if __name__ == "__main__":
    main()
