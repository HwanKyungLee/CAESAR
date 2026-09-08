"""Find reproducible, two-channel stable windows in completed injection profiles.

This is evidence extraction, not a calibration tool.  It never changes a
FitSet or applies a concentration correction.  A reported window can only be
called an absolute validation point after a human links it to a logged,
known injection level.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict

import numpy as np


def _profile_means(path: str) -> dict[int, float]:
    with open(path, encoding="utf-8") as fh:
        report = json.load(fh)
    values: dict[int, list[float]] = defaultdict(list)
    for attempt in report.get("attempts", []):
        if "row_index" in attempt and "target_concentration" in attempt:
            values[int(attempt["row_index"])].append(float(attempt["target_concentration"]))
    if not values:
        raise ValueError(f"{path}: no row-level concentration attempts")
    return {row: float(np.mean(v)) for row, v in values.items()}


def _alpha_times(path: str) -> dict[int, str]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("#"):
                header = line.rstrip("\n").split("\t")
                break
        else:
            raise ValueError(f"{path}: no alpha header")
        indices = {name: i for i, name in enumerate(header)}
        if "row_idx" not in indices or "datetime" not in indices:
            raise ValueError(f"{path}: needs row_idx and datetime columns")
        # Explorer profiles use the ordinal alpha row (0..N-1), whereas the
        # trace's row_idx is the original raw-file row.  Preserve chronological
        # order here instead of silently comparing those two different IDs.
        result = {}
        for ordinal, row in enumerate(csv.reader(fh, delimiter="\t")):
            if row:
                result[ordinal] = row[indices["datetime"]]
    return result


def find_plateaus(ans: dict[int, float], pns: dict[int, float], times: dict[int, str],
                  *, window_rows: int = 6, max_relative_drift: float = 0.10) -> list[dict]:
    """Return every fixed-length jointly stable window, without choosing a winner."""
    rows = sorted(set(ans) & set(pns) & set(times))
    output = []
    for group in (rows[i:i + window_rows] for i in range(len(rows) - window_rows + 1)):
        if group[-1] - group[0] != window_rows - 1:
            continue
        a = np.array([ans[i] for i in group]); p = np.array([pns[i] for i in group])
        adrift = float((a[-1] - a[0]) / np.mean(a))
        pdrift = float((p[-1] - p[0]) / np.mean(p))
        arange = float((np.max(a) - np.min(a)) / np.mean(a))
        prange = float((np.max(p) - np.min(p)) / np.mean(p))
        # Endpoint drift alone can miss a ramp that returns to its starting
        # value inside one window.  Require the entire range to be small too.
        if max(abs(adrift), abs(pdrift), arange, prange) > max_relative_drift:
            continue
        ratio = a / p
        output.append({
            "row_start": group[0], "row_end": group[-1],
            "time_start": times[group[0]], "time_end": times[group[-1]],
            "ANs_median_ppb": float(np.median(a)), "PNs_median_ppb": float(np.median(p)),
            "ANs_relative_drift": adrift, "PNs_relative_drift": pdrift,
            "ANs_relative_range": arange, "PNs_relative_range": prange,
            "ANs_over_PNs_median": float(np.median(ratio)),
            "ANs_over_PNs_relative_drift": float((ratio[-1] - ratio[0]) / np.mean(ratio)),
        })
    # Sliding windows overlap heavily.  Keep the most stable representative of
    # each interval so one physical plateau is not reported four times.
    selected = []
    for candidate in sorted(output, key=lambda item: max(abs(item["ANs_relative_drift"]),
                                                          abs(item["PNs_relative_drift"]),
                                                          item["ANs_relative_range"],
                                                          item["PNs_relative_range"])):
        if any(not (candidate["row_end"] < prior["row_start"] or
                    prior["row_end"] < candidate["row_start"]) for prior in selected):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: item["row_start"])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ans-profile", required=True)
    p.add_argument("--pns-profile", required=True)
    p.add_argument("--ans-alpha", required=True)
    p.add_argument("--window-rows", type=int, default=6)
    p.add_argument("--max-relative-drift", type=float, default=0.10)
    p.add_argument("--output", required=True)
    a = p.parse_args(argv)
    if a.window_rows < 3 or not 0 < a.max_relative_drift < 1:
        p.error("window-rows must be >=3 and max-relative-drift must be in (0,1)")
    plateaus = find_plateaus(_profile_means(a.ans_profile), _profile_means(a.pns_profile),
                             _alpha_times(a.ans_alpha), window_rows=a.window_rows,
                             max_relative_drift=a.max_relative_drift)
    result = {"schema": "CAESAR.InjectionPlateauEvidence.v1",
              "status": "CANDIDATES_REQUIRE_LOGGED_LEVEL_REVIEW",
              "criterion": {"window_rows": a.window_rows,
                            "max_relative_drift": a.max_relative_drift,
                            "both_channels_required": True},
              "candidates": plateaus,
              "limitations": ["No automatic injection-level assignment",
                              "No absolute calibration or FitSet mutation"]}
    with open(a.output, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"candidate_count": len(plateaus), "output": a.output}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
