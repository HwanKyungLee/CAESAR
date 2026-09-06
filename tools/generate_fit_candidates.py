"""Generate and preflight the explicit zero-base candidate grid (Stage 0 only)."""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import fit_explorer as FE
from tools import optimize_params as OP


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fitset")
    parser.add_argument("key", choices=sorted(OP.CHAN_ALPHA))
    parser.add_argument("--output", required=True)
    parser.add_argument("--overwrite", action="store_true")
    policy = parser.add_mutually_exclusive_group(required=True)
    policy.add_argument("--allow-negative-gas", action="store_true")
    policy.add_argument("--nonnegative-gas", action="store_true")
    args = parser.parse_args(argv)
    output = os.path.abspath(args.output)
    if os.path.exists(output) and not args.overwrite:
        raise SystemExit("ABSTAIN: output exists (pass --overwrite to replace it)")
    with open(args.fitset, encoding="utf-8") as fh:
        scenario = json.load(fh)
    cfg = OP.pick_channel(scenario, args.key)
    if type(cfg.get("allow_negative_gas")) is not bool:
        raise SystemExit("ABSTAIN: FitSet allow_negative_gas must be an exact bool")
    if cfg["allow_negative_gas"] != bool(args.allow_negative_gas):
        raise SystemExit("ABSTAIN: CLI gas-sign policy conflicts with FitSet policy")
    try:
        reference_policy = FE.validate_reference_policy(cfg)
        eng = OP.build_engine_from_config(cfg)
        candidates = FE.zero_base_policy_candidates(cfg, eng._wave_axis)
        report = FE.stage0_candidate_grid(eng, candidates)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit("ABSTAIN: " + type(exc).__name__) from None
    report["status"] = "STAGE0_COMPLETE"
    report["channel"] = args.key
    report["reference_policy"] = reference_policy
    report["refs"] = list(eng.gas_list)
    report["source"] = {"fitset": os.path.basename(args.fitset), "key": args.key}
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"status": report["status"], "counts": report["counts"],
                      "output": output}, sort_keys=True))


if __name__ == "__main__":
    main()
