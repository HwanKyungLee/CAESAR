"""Synthetic graph/closure checks for V2; science edge states are injected."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import fit_explorer_v2 as V2


def _plan():
    ids = ["a", "b", "c", "d", "e"]
    return {"requested_species": ["Species_A", "Species_B"],
            "candidates": [{"candidate_id": name, "poly": 2 if name != "b" else 3,
                            "px_min": 10, "px_max": 30} for name in ids],
            "edges": [{"left_candidate_id": "a", "right_candidate_id": "b", "kind": "poly"},
                      {"left_candidate_id": "b", "right_candidate_id": "c", "kind": "poly"},
                      {"left_candidate_id": "a", "right_candidate_id": "c", "kind": "reference-choice"},
                      {"left_candidate_id": "b", "right_candidate_id": "e", "kind": "reference-choice"}],
            "budget": {"max_fit_attempts": 10, "closure_max_attempts": 1}}


def _evidence(left, right, a, b):
    return {"left_candidate_id": left, "right_candidate_id": right,
            "species": {"Species_A": {"state": a}, "Species_B": {"state": b}}}


def test_graph_requires_full_component_evidence_and_preserves_unknown_frontier():
    states = {"a": "EVALUATED_PASS", "b": "EVALUATED_PASS", "c": "EVALUATED_PASS",
              "d": "EVALUATED_PASS", "e": "UNEVALUATED"}
    graph = V2.evaluate_candidate_graph(_plan(), states, [
        _evidence("a", "b", "PASS", "PASS"), _evidence("b", "c", "PASS", "PASS"),
        _evidence("a", "c", "PASS", "FAIL")])
    abc = next(row for row in graph["components"] if row["members"] == ["a", "b", "c"])
    assert abc["state"] == "INCONSISTENT_COMPONENT" and abc["component_pair_check"] == "FAIL"
    assert graph["closure"]["requested_candidate_ids"] == ["e"]
    isolated = next(row for row in graph["components"] if row["members"] == ["d"])
    assert isolated["representative_candidate_id"] == "d"
    assert isolated["state"] == "ISOLATED_NO_ROBUSTNESS_EVIDENCE"


def test_graph_keeps_species_conflict_and_budget_exhaustion_out_of_plateau():
    states = {"a": "EVALUATED_PASS", "b": "EVALUATED_PASS", "c": "EVALUATED_FAIL",
              "d": "PRUNED", "e": "UNEVALUATED"}
    graph = V2.evaluate_candidate_graph(_plan(), states, [
        _evidence("a", "b", "PASS", "FAIL")], used_fit_attempts=10)
    assert len(graph["components"]) == 2  # conflict prevents a/b connection
    assert graph["edge_states"][0]["state"] == "FAIL"
    assert graph["closure"]["requested_candidate_ids"] == []


def main():
    test_graph_requires_full_component_evidence_and_preserves_unknown_frontier()
    test_graph_keeps_species_conflict_and_budget_exhaustion_out_of_plateau()
    print("test_fit_explorer_v2_graph: PASS")


if __name__ == "__main__":
    main()
