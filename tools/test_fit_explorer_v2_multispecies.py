"""Contract checks for V2 same-observation multi-species evidence."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import fit_explorer_v2 as V2


def _report(candidate_id, attempts):
    return {"candidate_id": candidate_id, "planned_attempts": 3, "attempts": attempts}


def test_multispecies_comparison_preserves_missing_denominators_and_pairs_rows():
    left = _report("left", [
        {"scan_id": "morning", "start_id": "a", "status": "OK", "coeffs": {"Species_A": 1., "Species_B": .01}},
        {"scan_id": "morning", "start_id": "b", "status": "OK", "coeffs": {"Species_A": 1., "Species_B": .02}},
        {"scan_id": "afternoon", "start_id": "a", "status": "OK", "coeffs": {"Species_A": 10., "Species_B": .03}}])
    right = _report("right", [
        {"scan_id": "morning", "start_id": "a", "status": "OK", "coeffs": {"Species_A": 2., "Species_B": .04}},
        {"scan_id": "morning", "start_id": "b", "status": "OK", "coeffs": {"Species_A": 2.}},
        {"scan_id": "night", "start_id": "a", "status": "UNAVAILABLE"}])
    evidence = V2.compare_multispecies_attempts([left, right], ["Species_A", "Species_B"])
    left_a = evidence["candidates"][0]["species"]["Species_A"]
    right_b = evidence["candidates"][1]["species"]["Species_B"]
    assert left_a["multi_start"][0]["range"] == 0.0  # repeat seeds, not time-series stability
    assert right_b["state"] == "UNAVAILABLE" and right_b["attempts"]["coefficient_unavailable"] == 2
    assert right_b["attempts"]["complete"] is False
    a_delta = evidence["comparisons"][0]["species"]["Species_A"]
    assert a_delta["paired_attempts"] == 2 and a_delta["median_delta"] == 1.0
    assert evidence["comparisons"][0]["residual_comparison"]["state"] == "NOT_APPLICABLE"


def main():
    test_multispecies_comparison_preserves_missing_denominators_and_pairs_rows()
    print("test_fit_explorer_v2_multispecies: PASS")


if __name__ == "__main__":
    main()
