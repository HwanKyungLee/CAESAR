"""Regression: unverified V2 verdicts must never authorize recommendation/export."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import fit_explorer_v2 as V2


def main():
    plan = {"plan_hash": "not-verified", "requested_species": ["S"],
            "candidates": [{"candidate_id": "c"}],
            "split": {"discovery": ["d"], "validation": [], "holdout": ["h"]}}
    graph = {"schema": "explorer-v2-graph-closure-v1", "components": [
        {"state": "CLOSED_INTERNAL_COMPONENT", "representative_candidate_id": "c"}]}
    states = {"c": {"internal_state": "PASS", "numerical_state": "IDENTIFIED", "species": {"S": "PASS"}}}
    result = V2.build_recommendation(plan, graph, states,
        {"observation_ids": ["h"], "candidate_states": {"c": "PASS"}})
    assert result["status"] == "ABSTAIN" and result["exportable_candidate_ids"] == []
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "must-not-exist.json")
        forged = {"status": "MISSION_RECOMMENDED", "exportable_candidate_ids": ["c"]}
        try:
            V2.export_recommended_fitset({}, {"candidate_id": "c"}, forged, path)
        except ValueError:
            pass
        else:
            raise AssertionError("unverified export accepted")
        assert not os.path.exists(path)
    rows = [{"scan_id": "x", "start_id": "a", "status": "OK", "coeffs": {"S": 1.}}] * 2
    try:
        V2.compare_multispecies_attempts([{"candidate_id": "c", "planned_attempts": 2, "attempts": rows}], ["S"])
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate attempt accepted")
    print("test_fit_explorer_v2_recommendation: PASS (unverified path blocked)")


if __name__ == "__main__":
    main()
