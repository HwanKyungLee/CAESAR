"""Run diagnostic leave-one-reference-out fits from an explicit Explorer config.

This uses the Stage 1 representative scans and controlled starts, but it is not
a batch ranking path: it writes one immutable diagnostic report and never edits
a FitSet, selects a winner, or applies a policy.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import fit_explorer as FE
from core import reference_ablation as RA
from core.doas_fit import DoasFitter
from core import param_optimizer as PO
from core.fit_explorer_batch import atomic_write_json
from tools import optimize_params as OP
from tools import run_fit_explorer_batch as RB


def _attempt(engine, fitter, cfg, candidate, ref_props, scan, start, target):
    bounds = FE.independent_global_bounds(ref_props, list(engine.gas_list))
    initial = FE.independent_initial_values(bounds, target)
    result = PO.fit_scan(
        engine, fitter, ref_props, scan["wave"], scan["alpha"],
        float(scan["temperature_C"]), float(scan["pressure_mbar"]),
        int(candidate["px_min"]) - int(scan["px_start"]),
        int(candidate["px_max"]) - int(scan["px_start"]), int(candidate["poly"]),
        float(cfg.get("step_limit", .5)), target, allow_negative_gas=True,
        controlled_start=(float(start["shift"]), float(start["squeeze"])),
        controlled_bounds=bounds, controlled_initial_values=initial,
        return_solver_diagnostics=True)
    diagnostics = result.get("solver_diagnostics", {})
    values = {"target_concentration": result.get("conc"), "rms_sig": result.get("rms_sig"),
              "final_shift": result.get("shifts", {}).get(target),
              "final_squeeze": result.get("squeezes", {}).get(target)}
    if any(value is None or not np.isfinite(float(value)) for value in values.values()):
        raise ValueError("fit result is incomplete")
    return {"status": "OK", "scan_id": str(scan["id"]), "start_id": str(start["id"]),
            **{key: float(value) for key, value in values.items()},
            "solver_status": str(diagnostics.get("solver_termination", {}).get("status", "UNAVAILABLE"))}


def run(document, channel_label, candidate_id):
    if document.get("stage") != 1:
        raise ValueError("reference ablation requires an explicit Stage 1 config")
    channel = next((item for item in document["channels"] if item["label"] == channel_label), None)
    if channel is None:
        raise ValueError("channel is not declared")
    prepared = RB.prepare_channel(channel, document)
    context = prepared["context"]
    candidate = prepared["candidates"].get(candidate_id)
    if candidate is None:
        raise ValueError("candidate is not declared")
    cfg, target = context["cfg"], context["target"]
    gas_order = [ref["name"] for ref in cfg["refs"]]
    declarations = RA.variant_declarations(gas_order, target)
    starts = FE.stage1_policy_starts(candidate)["starts"]
    variants = []
    for declaration in declarations:
        excluded = set(declaration["excluded"])
        variant_cfg = copy.deepcopy(cfg)
        variant_cfg["refs"] = [ref for ref in cfg["refs"] if ref["name"] not in excluded]
        raw_props = {name: copy.deepcopy(props) for name, props in cfg["ref_props"].items()
                     if name not in excluded}
        engine = OP.build_engine_from_config(variant_cfg)
        fitter = DoasFitter(engine)
        ref_props = FE.translate_zero_base_policy(
            variant_cfg, raw_props, candidate, target)["ref_props"]
        attempts = []
        for scan in context["scans"]:
            for start in starts:
                try:
                    attempts.append(_attempt(engine, fitter, variant_cfg, candidate,
                                             ref_props, scan, start, target))
                except Exception as exc:
                    attempts.append({"status": "UNAVAILABLE", "scan_id": str(scan["id"]),
                                     "start_id": str(start["id"]),
                                     "reason": "FIT_ATTEMPT_EXCEPTION",
                                     "exception_class": type(exc).__name__})
        variants.append({"id": declaration["id"], "excluded": declaration["excluded"],
                         "gas_order": list(engine.gas_list), "attempts": attempts,
                         "summary": RA.summarize_attempts(attempts),
                         "reference_observability": FE.reference_observability(
                             engine, candidate, context["reference_roles"])})
    return {"schema": RA.SCHEMA, "status": "DIAGNOSTIC_ONLY",
            "target": target, "candidate": {"id": candidate["id"], "policy": candidate["policy"],
                                                "px_min": candidate["px_min"], "px_max": candidate["px_max"],
                                                "poly": candidate["poly"]},
            "source": context["source"], "sampling": context["sampling"],
            "variants": variants, "comparisons": RA.compare_to_baseline(variants),
            "limitations": ["No T2 verdict", "No ranking", "No plateau claim", "No Apply",
                            "No fixed shift/squeeze grid profile"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if os.path.exists(args.output):
        raise SystemExit("ABSTAIN: output exists")
    try:
        with open(args.config, encoding="utf-8") as fh:
            document = RB._resolve_paths(json.load(fh), os.path.dirname(os.path.abspath(args.config)))
        report = run(document, args.channel, args.candidate_id)
        atomic_write_json(args.output, report, immutable=True)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit("ABSTAIN: " + type(exc).__name__) from None
    print(json.dumps({"status": report["status"], "variants": len(report["variants"]),
                      "output": os.path.basename(args.output)}))


if __name__ == "__main__":
    main()
