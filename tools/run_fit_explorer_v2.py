"""File-based GUI/CLI bridge for the pure Fit Explorer V2 contracts."""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import fit_explorer_v2 as V2


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_plan(path, plan):
    path = os.path.abspath(path)
    encoded = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if os.path.exists(path):
        existing = _load(path)
        if existing.get("plan_hash") == plan.get("plan_hash"):
            return "REUSED"
        raise FileExistsError("plan path already exists with different content")
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise ValueError("plan output directory does not exist")
    with open(path, "x", encoding="utf-8", newline="\n") as fh:
        fh.write(encoded)
    return "CREATED"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fit Explorer V2 plan/export bridge")
    sub = parser.add_subparsers(dest="action", required=True)
    plan_cmd = sub.add_parser("plan", help="validate mission and write/reuse a frozen V2 plan")
    plan_cmd.add_argument("--mission", required=True)
    plan_cmd.add_argument("--output", required=True)
    export_cmd = sub.add_parser("export", help="explicitly export one V2 recommendation candidate")
    export_cmd.add_argument("--plan", required=True)
    export_cmd.add_argument("--recommendation", required=True)
    export_cmd.add_argument("--base-fitset", required=True)
    export_cmd.add_argument("--candidate-id", required=True)
    export_cmd.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            plan = V2.build_mission_plan(_load(args.mission))
            result = {"action": "plan", "state": _write_plan(args.output, plan),
                      "plan_hash": plan["plan_hash"], "candidate_count": len(plan["candidates"]),
                      "status": plan["status"]}
        else:
            plan, recommendation, base = _load(args.plan), _load(args.recommendation), _load(args.base_fitset)
            candidate = next((row for row in plan.get("candidates", [])
                              if row.get("candidate_id") == args.candidate_id), None)
            if candidate is None:
                raise ValueError("candidate_id is absent from plan")
            result = {"action": "export", **V2.export_recommended_fitset(
                base, candidate, recommendation, args.output)}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit("ABSTAIN: " + type(exc).__name__) from None


if __name__ == "__main__":
    raise SystemExit(main())
