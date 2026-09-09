"""Diagnostic-only aggregation for Fit Explorer reference ablation runs."""
from __future__ import annotations

import numpy as np


SCHEMA = "reference-ablation-v1"


def variant_declarations(gas_order, target):
    """Baseline plus one leave-one-reference-out variant per non-target gas."""
    if (not isinstance(gas_order, list) or not gas_order or target not in gas_order
            or any(not isinstance(gas, str) or not gas for gas in gas_order)
            or len(set(gas_order)) != len(gas_order)):
        raise ValueError("gas order or target is invalid")
    return ([{"id": "baseline", "excluded": []}]
            + [{"id": "without_" + gas, "excluded": [gas]}
               for gas in gas_order if gas != target])


def _median(values):
    finite = [float(value) for value in values if np.isfinite(float(value))]
    return None if not finite else float(np.median(finite))


def summarize_attempts(attempts):
    """Summarize existing fit attempts; do not manufacture a verdict."""
    ok = [row for row in attempts if isinstance(row, dict) and row.get("status") == "OK"]
    summary = {key: _median([row.get(key, float("nan")) for row in ok])
               for key in ("target_concentration", "rms_sig", "final_shift", "final_squeeze")}
    starts = {}
    for row in ok:
        starts.setdefault(str(row.get("scan_id")), []).append(row)
    seed_deltas = []
    for rows in starts.values():
        concentrations = [float(row["target_concentration"]) for row in rows
                          if "target_concentration" in row and np.isfinite(float(row["target_concentration"]))]
        if len(concentrations) >= 2:
            seed_deltas.append(max(concentrations) - min(concentrations))
    return {"attempts": {"planned": len(attempts), "successful": len(ok),
                         "failed": len(attempts) - len(ok)},
            "median": summary,
            "seed_target_span_median": _median(seed_deltas),
            "scope": "DESCRIPTIVE_ONLY_NO_RANKING_NO_RECOMMENDATION"}


def compare_to_baseline(variants):
    """Attach signed median deltas without calling any variant better."""
    if not variants or variants[0].get("id") != "baseline":
        raise ValueError("baseline variant is required first")
    baseline = variants[0].get("summary", {}).get("median", {})
    out = []
    for variant in variants:
        current = variant.get("summary", {}).get("median", {})
        delta = {}
        for key in ("target_concentration", "rms_sig", "final_shift", "final_squeeze"):
            a, b = baseline.get(key), current.get(key)
            delta[key] = (None if a is None or b is None else float(b - a))
        out.append({"id": variant.get("id"), "delta_from_baseline": delta,
                    "scope": "SIGNED_DIAGNOSTIC_DELTA_NOT_A_SELECTION_SCORE"})
    return out
