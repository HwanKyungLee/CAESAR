"""Render a human-review summary from completed Fit Explorer evidence.

This tool never ranks candidates or changes a FitSet.  The verdict is supplied
by the scientific review that produced the evidence, then rendered with the
same boundary and seed diagnostics a user needs before manual approval.
"""
from __future__ import annotations
import argparse, json, os
from collections import defaultdict
import numpy as np

VERDICTS = ("RECOMMENDABLE_INTERNAL", "MISSION_LOCAL_ONLY",
            "NON_IDENTIFIABLE_OR_ABSTAIN")

def summarize(path):
    with open(path, encoding="utf-8") as fh: data = json.load(fh)
    attempts = data.get("attempts", [])
    if not attempts or any("target_concentration" not in row for row in attempts):
        raise ValueError("report has no completed concentration attempts")
    groups = defaultdict(list)
    for row in attempts: groups[row["scan_id"]].append(row["target_concentration"])
    return {"file": os.path.basename(path), "candidate_id": data.get("candidate_id"),
            "attempts": len(attempts),
            "boundary_attempts": sum(bool(row.get("boundary_hits")) for row in attempts),
            "median_ppb": float(np.median([row["target_concentration"] for row in attempts])),
            "seed_max_delta_ppb": float(max(abs(max(v)-min(v)) for v in groups.values()))}


def summarize_session_relative(path):
    """Accept injection evidence only as session-relative, non-calibration context."""
    with open(path, encoding="utf-8") as fh: data = json.load(fh)
    if data.get("schema") != "CAESAR.InjectionPlateauEvidence.v1":
        raise ValueError("not an InjectionPlateauEvidence.v1 report")
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("injection evidence has no stable plateau candidates")
    return {"file": os.path.basename(path), "candidate_count": len(candidates),
            "scope": "SESSION_RELATIVE_ONLY_NO_ABSOLUTE_CORRECTION",
            "criterion": data.get("criterion"),
            "limitations": data.get("limitations", [])}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage2", required=True); p.add_argument("--holdout")
    p.add_argument("--verdict", choices=VERDICTS, required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--session-relative-evidence", action="append", default=[],
                   help="optional InjectionPlateauEvidence.v1; display-only, never calibration")
    p.add_argument("--output", help="optional JSON file for the Test Fit Explorer Review tab")
    a = p.parse_args(argv)
    result = {"schema": "fit-explorer-human-review-v1", "verdict": a.verdict,
              "reason": a.reason, "stage2": summarize(a.stage2),
              "holdout": summarize(a.holdout) if a.holdout else None,
              "session_relative_validation": [summarize_session_relative(path)
                                              for path in a.session_relative_evidence],
              "apply": "FORBIDDEN_REQUIRES_EXPLICIT_HUMAN_ACTION"}
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if a.output:
        # The report is evidence for human review, never a FitSet mutation.
        with open(a.output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    print(text)
    return 0

if __name__ == "__main__": raise SystemExit(main())
