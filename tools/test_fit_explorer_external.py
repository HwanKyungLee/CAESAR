"""Hash-pinned optional real-data checks for Fit Explorer."""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import fit_explorer as FE
from core import param_optimizer as PO
from core.data_io import DataIO
from core.doas_fit import DoasFitter
from tools.migrate_fitset_policy import sha256
from tools.optimize_params import build_engine_from_config

SCHEMA_VERSION = 1
SUITE_VERSION = "1.0"
METRICS = ("conc", "rms_sig", "abs_ac1")
ROLES = {"legacy_fitset", "migrated_fitset", "alpha", "wavecal", "reference"}


def resolve(base, path):
    return os.path.abspath(path if os.path.isabs(path) else os.path.join(base, path))


def exact_bool(value, label):
    if type(value) is not bool:
        raise AssertionError(f"{label} must be an exact bool")
    return value


def validate_range(label, value):
    if not isinstance(value, list) or len(value) != 2:
        raise AssertionError(f"{label} must be an ordered [lo, hi] list")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise AssertionError(f"{label} bounds must be finite numbers")
    if value[0] > value[1]:
        raise AssertionError(f"{label} has lo > hi")


def validate_manifest(manifest, base):
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise AssertionError(f"schema_version must be {SCHEMA_VERSION}")
    if manifest.get("suite_version") != SUITE_VERSION:
        raise AssertionError(f"suite_version must be {SUITE_VERSION}")
    dependencies, cases = manifest.get("dependencies"), manifest.get("cases")
    if not isinstance(dependencies, list) or not dependencies or not isinstance(cases, list) or not cases:
        raise AssertionError("manifest requires non-empty dependencies and cases")
    dep_by_id = {}
    for dep in dependencies:
        if not isinstance(dep, dict) or not isinstance(dep.get("id"), str) or not dep["id"]:
            raise AssertionError("every dependency requires a non-empty string id")
        if dep["id"] in dep_by_id:
            raise AssertionError(f"duplicate dependency id: {dep['id']}")
        if dep.get("role") not in ROLES:
            raise AssertionError(f"{dep['id']}: invalid dependency role")
        digest = dep.get("sha256")
        if (not isinstance(dep.get("path"), str) or not dep["path"] or
                not isinstance(digest, str) or len(digest) != 64):
            raise AssertionError(f"{dep['id']}: invalid sha256")
        try:
            int(digest, 16)
        except ValueError:
            raise AssertionError(f"{dep['id']}: invalid sha256") from None
        dep_by_id[dep["id"]] = {**dep, "resolved_path": resolve(base, dep["path"])}
    case_ids, used = set(), set()
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise AssertionError(f"duplicate or invalid case id: {case_id!r}")
        case_ids.add(case_id)
        exact_bool(case.get("allow_negative_gas"), f"{case_id}.allow_negative_gas")
        if case.get("evidence_role") not in ("high_residual_candidate", "low_residual_candidate"):
            raise AssertionError(f"{case_id}: invalid evidence_role")
        ranges = case.get("expected_ranges")
        if not isinstance(ranges, dict) or set(ranges) != set(METRICS):
            raise AssertionError(f"{case_id}: expected_ranges must contain exactly {METRICS}")
        for metric in METRICS:
            validate_range(f"{case_id}.{metric}", ranges[metric])
        refs, expected_refs = case.get("reference_ids"), case.get("expected_references")
        if not isinstance(refs, list) or not refs or not isinstance(expected_refs, list):
            raise AssertionError(f"{case_id}: ordered references are required")
        if len(refs) != len(expected_refs):
            raise AssertionError(f"{case_id}: reference ids/specs length mismatch")
        links = (("source_fitset_id", "legacy_fitset"), ("fitset_id", "migrated_fitset"),
                 ("alpha_id", "alpha"), ("wavecal_id", "wavecal"))
        for key, role in links:
            dep_id = case.get(key)
            if dep_id not in dep_by_id or dep_by_id[dep_id]["role"] != role:
                raise AssertionError(f"{case_id}: {key} must reference role {role}")
            used.add(dep_id)
        for dep_id, spec in zip(refs, expected_refs):
            if dep_id not in dep_by_id or dep_by_id[dep_id]["role"] != "reference":
                raise AssertionError(f"{case_id}: reference {dep_id!r} is not pinned")
            if spec.get("dependency_id") != dep_id or not isinstance(spec.get("name"), str):
                raise AssertionError(f"{case_id}: reference identity/order mismatch")
            if type(spec.get("mult")) not in (int, float) or not math.isfinite(spec["mult"]):
                raise AssertionError(f"{case_id}: reference mult must be finite")
            used.add(dep_id)
        gases = case.get("expected_gas_order")
        if (not isinstance(gases, list) or not gases or len(set(gases)) != len(gases) or
                any(not isinstance(g, str) or not g for g in gases)):
            raise AssertionError(f"{case_id}: expected_gas_order is required")
        if type(case.get("row_index")) is not int or case["row_index"] < 0:
            raise AssertionError(f"{case_id}: row_index must be a nonnegative int")
        if type(case.get("fixed_shift")) not in (int, float) or not math.isfinite(case["fixed_shift"]):
            raise AssertionError(f"{case_id}: fixed_shift must be finite")
    if used != set(dep_by_id):
        raise AssertionError(f"unused/extra dependencies: {sorted(set(dep_by_id) - used)}")
    return dep_by_id


def verify_dependencies(dep_by_id):
    for dep in dep_by_id.values():
        path = dep["resolved_path"]
        if not os.path.isfile(path):
            raise AssertionError(f"required file missing: {dep['id']} ({os.path.basename(path)})")
        actual = sha256(path)
        if actual.lower() != dep["sha256"].lower():
            raise AssertionError(f"hash mismatch: {dep['id']}: {actual}")


def public_dependency(dep):
    """Shareable identity without manifest or resolved directory paths."""
    return {"id": dep["id"], "role": dep["role"], "sha256": dep["sha256"].lower(),
            "name": os.path.basename(dep["resolved_path"])}


def run_case(case, dependencies):
    started = time.perf_counter()
    with open(dependencies[case["fitset_id"]]["resolved_path"], encoding="utf-8") as fh:
        scenario = json.load(fh)
    history = scenario.get("policy_migrations")
    source_hash = dependencies[case["source_fitset_id"]]["sha256"].lower()
    if (not isinstance(history, list) or not history or
            history[-1].get("source_sha256", "").lower() != source_hash):
        raise AssertionError(f"{case['id']}: migrated FitSet provenance/source mismatch")
    channel_id = str(case["channel_id"])
    if channel_id not in scenario.get("channels", {}):
        raise AssertionError(f"{case['id']}: channel {channel_id} is absent")
    cfg = copy.deepcopy(scenario["channels"][channel_id])
    policy = exact_bool(cfg.get("allow_negative_gas"), f"{case['id']}.FitSet policy")
    if policy is not case["allow_negative_gas"]:
        raise AssertionError(f"{case['id']}: case/FitSet policy mismatch")
    cfg["wl_path"] = dependencies[case["wavecal_id"]]["resolved_path"]
    embedded, expected_refs = cfg.get("refs", []), case["expected_references"]
    embedded_identity = [(r.get("name"), r.get("mult", 0)) for r in embedded]
    expected_identity = [(r["name"], r["mult"]) for r in expected_refs]
    if embedded_identity != expected_identity:
        raise AssertionError(f"{case['id']}: FitSet reference order/mults changed")
    cfg["refs"] = [{**embedded[i], "path": dependencies[spec["dependency_id"]]["resolved_path"]}
                   for i, spec in enumerate(expected_refs)]
    engine = build_engine_from_config(cfg)
    if list(engine.gas_list) != case["expected_gas_order"]:
        raise AssertionError(f"{case['id']}: engine gas order changed: {engine.gas_list}")
    engine_mults = [engine.multipliers[g] for g in engine.gas_list]
    expected_mults = [10.0 ** r["mult"] for r in expected_refs]
    if engine_mults != expected_mults:
        raise AssertionError(f"{case['id']}: engine multipliers changed")
    wave, alpha, temp, pressure, px_start = DataIO.load_alpha_trace_row_mapped(
        dependencies[case["alpha_id"]]["resolved_path"], int(case["row_index"]))
    props = copy.deepcopy(cfg["ref_props"])
    target = case.get("target", "NO2")
    props[target].update(sh_mode="Fix", sh_val=str(case["fixed_shift"]),
                         sq_mode="Fix", sq_val=str(case.get("fixed_squeeze", 1.0)))
    result = PO.fit_scan(engine, DoasFitter(engine), props, wave, alpha, temp, pressure,
                         int(cfg["f_min"]) - px_start, int(cfg["f_max"]) - px_start,
                         int(cfg["poly_deg"]), float(cfg.get("step_limit", .5)), target=target,
                         allow_negative_gas=policy)
    metrics = {"conc": float(result["conc"]), "rms_sig": float(result["rms_sig"]),
               "abs_ac1": abs(float(result["autocorr1"]))}
    for metric in METRICS:
        lo, hi = case["expected_ranges"][metric]
        if not lo <= metrics[metric] <= hi:
            raise AssertionError(f"{case['id']}.{metric}={metrics[metric]:.12g} outside [{lo}, {hi}]")
    return {"id": case["id"], "status": "PERFORMED", "evidence_role": case["evidence_role"],
            "row_index": int(case["row_index"]), "fixed_shift": float(case["fixed_shift"]),
            "allow_negative_gas": policy, "metrics": metrics,
            "config_identity": {"channel_id": channel_id, "window_px_inclusive":
                                [int(cfg["f_min"]), int(cfg["f_max"])],
                                "poly": int(cfg["poly_deg"]), "reference_order": expected_identity},
            "engine_identity": {"gas_order": list(engine.gas_list), "multipliers": engine_mults},
            "elapsed_s": time.perf_counter() - started}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=os.environ.get("CAESAR_GOLDEN_MANIFEST"))
    parser.add_argument("--result", help="optional structured local result JSON")
    args = parser.parse_args(argv)
    if not args.manifest:
        print("SKIP: no --manifest or CAESAR_GOLDEN_MANIFEST")
        return 0
    manifest_path = os.path.abspath(args.manifest)
    report = {"schema_version": SCHEMA_VERSION, "suite_version": SUITE_VERSION,
              "manifest_sha256": None, "git": FE.git_provenance(ROOT),
              "performed": [], "failed": [], "skipped": []}
    dependencies = {}
    candidate_inputs = [manifest_path]
    try:
        if not os.path.isfile(manifest_path):
            raise AssertionError(f"manifest not found: {os.path.basename(manifest_path)}")
        report["manifest_sha256"] = sha256(manifest_path)
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        candidate_inputs += [resolve(os.path.dirname(manifest_path), dep["path"])
                             for dep in manifest.get("dependencies", [])
                             if isinstance(dep, dict) and isinstance(dep.get("path"), str)]
        dependencies = validate_manifest(manifest, os.path.dirname(manifest_path))
        verify_dependencies(dependencies)
        report["dependencies"] = [public_dependency(dep) for dep in dependencies.values()]
        report["performed"] = [run_case(case, dependencies) for case in manifest["cases"]]
    except (KeyError, OSError, TypeError, ValueError, AssertionError, json.JSONDecodeError) as exc:
        report["failed"].append({"id": "manifest_or_case", "reason": str(exc)})
        if args.result:
            FE.ensure_output_safe(args.result, candidate_inputs)
            FE.write_report(args.result, report)
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.result:
        FE.ensure_output_safe(args.result, candidate_inputs)
        FE.write_report(args.result, report)
    print(f"manifest_sha256={report['manifest_sha256']}")
    for row in report["performed"]:
        m = row["metrics"]
        print(f"PASS: {row['id']}: row={row['row_index']}, shift={row['fixed_shift']:g}, "
              f"allow_negative_gas={row['allow_negative_gas']}, conc={m['conc']:.6g}, "
              f"rms/sig={m['rms_sig']:.6g}, |ac1|={m['abs_ac1']:.6g}, "
              f"elapsed_s={row['elapsed_s']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
