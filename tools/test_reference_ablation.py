"""Contract tests for diagnostic-only reference ablation aggregation."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import reference_ablation as RA


def main():
    variants = RA.variant_declarations(["NO2", "H2O", "CHOCHO", "O4"], "NO2")
    assert [row["id"] for row in variants] == ["baseline", "without_H2O", "without_CHOCHO", "without_O4"]
    attempts = [{"status": "OK", "scan_id": "a", "start_id": "lo", "target_concentration": 2.,
                 "rms_sig": 1., "final_shift": -2., "final_squeeze": 1.},
                {"status": "OK", "scan_id": "a", "start_id": "hi", "target_concentration": 4.,
                 "rms_sig": 3., "final_shift": -1., "final_squeeze": 1.0001},
                {"status": "UNAVAILABLE", "scan_id": "b", "start_id": "lo"}]
    summary = RA.summarize_attempts(attempts)
    assert summary["attempts"] == {"planned": 3, "successful": 2, "failed": 1}
    assert summary["median"]["target_concentration"] == 3.
    assert summary["seed_target_span_median"] == 2.
    compared = RA.compare_to_baseline([
        {"id": "baseline", "summary": summary},
        {"id": "without_H2O", "summary": {"median": {**summary["median"],
            "target_concentration": 5.}}},
    ])
    assert compared[1]["delta_from_baseline"]["target_concentration"] == 2.
    print("test_reference_ablation: PASS")


if __name__ == "__main__":
    main()
