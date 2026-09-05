"""Hash-pinned optional real-data checks for Fit Explorer."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import sys
import time
from ntpath import basename as _path_leaf

import numpy as np
import scipy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import fit_explorer as FE
from core import param_optimizer as PO
from core.data_io import DataIO
from core.doas_fit import DoasFitter
from tools.migrate_fitset_policy import sha256
from tools.optimize_params import build_engine_from_config

SCHEMA_VERSION = 3
SUITE_VERSION = "1.2"
METRICS = ("conc", "rms_sig", "abs_ac1")
ROLES = {"legacy_fitset", "alpha", "wavecal", "reference"}
ASSERTION_SCOPE = ("qualitative behavioral ordering only; not cross-platform numeric equivalence, "
                   "scientific tolerance, concentration truth, T3, or plateau evidence")


def portable_basename(path):
    """Return only the leaf name for Windows or POSIX path text."""
    return _path_leaf(path)


def resolve(base, path, data_root=None):
    if data_root is None:
        return os.path.abspath(path if os.path.isabs(path) else os.path.join(base, path))
    if os.path.isabs(path):
        raise AssertionError("portable dependency paths must be relative")
    root = os.path.realpath(data_root)
    resolved = os.path.realpath(os.path.join(root, path))
    if os.path.commonpath((root, resolved)) != root:
        raise AssertionError("portable dependency path leaves data root")
    return resolved


def exact_bool(value, label):
    if type(value) is not bool:
        raise AssertionError(f"{label} must be an exact bool")
    return value


def canonical_sha256(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def validate_manifest(manifest, base, data_root=None):
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
        dep_by_id[dep["id"]] = {**dep, "resolved_path": resolve(base, dep["path"], data_root)}
    case_ids, used = set(), set()
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise AssertionError(f"duplicate or invalid case id: {case_id!r}")
        case_ids.add(case_id)
        exact_bool(case.get("allow_negative_gas"), f"{case_id}.allow_negative_gas")
        if case.get("evidence_role") not in ("high_residual_candidate", "low_residual_candidate"):
            raise AssertionError(f"{case_id}: invalid evidence_role")
        refs, expected_refs = case.get("reference_ids"), case.get("expected_references")
        if not isinstance(refs, list) or not refs or not isinstance(expected_refs, list):
            raise AssertionError(f"{case_id}: ordered references are required")
        if len(refs) != len(expected_refs):
            raise AssertionError(f"{case_id}: reference ids/specs length mismatch")
        links = (("source_fitset_id", "legacy_fitset"), ("alpha_id", "alpha"),
                 ("wavecal_id", "wavecal"))
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
    assertions = manifest.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        raise AssertionError("manifest requires relational assertions")
    if manifest.get("assertion_scope") != ASSERTION_SCOPE:
        raise AssertionError("manifest assertion_scope is missing or changed")
    for assertion in assertions:
        if set(assertion) != {"id", "type", "high_case_id", "low_case_id", "source",
                              "strictly_greater"}:
            raise AssertionError("paired assertion contains unsupported fields")
        if assertion.get("type") != "paired_branch_contrast":
            raise AssertionError("unsupported assertion type")
        if assertion.get("high_case_id") not in case_ids or assertion.get("low_case_id") not in case_ids:
            raise AssertionError("assertion references an unknown case")
        if assertion["high_case_id"] == assertion["low_case_id"]:
            raise AssertionError("paired assertion requires two distinct cases")
        if assertion.get("strictly_greater") != list(METRICS):
            raise AssertionError(f"paired assertion must order exactly {METRICS}")
        if "thresholds" in assertion:
            raise AssertionError("paired behavioral assertion must not define numeric thresholds")
        if not isinstance(assertion.get("source"), str) or not assertion["source"]:
            raise AssertionError("paired assertion requires a source")
    measurements = manifest.get("measurements", [])
    if not isinstance(measurements, list):
        raise AssertionError("measurements must be a list")
    measurement_ids = set()
    for measurement in measurements:
        measurement_id = measurement.get("id")
        if (not isinstance(measurement_id, str) or not measurement_id or
                measurement_id in measurement_ids):
            raise AssertionError(f"duplicate or invalid measurement id: {measurement_id!r}")
        measurement_ids.add(measurement_id)
        kind = measurement.get("type")
        if kind not in ("fixed_shift_grid", "shift_path"):
            raise AssertionError(f"{measurement_id}: unsupported measurement type")
        source_case_id = measurement.get("source_case_id")
        if source_case_id not in case_ids:
            raise AssertionError(f"{measurement_id}: source_case_id is unknown")
        if kind == "fixed_shift_grid":
            values = measurement.get("shift_values")
            if (not isinstance(values, list) or not values or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
                raise AssertionError(f"{measurement_id}: finite shift_values are required")
            if len(set(map(float, values))) != len(values) or any(a >= b for a, b in zip(values, values[1:])):
                raise AssertionError(f"{measurement_id}: shift_values must be unique and strictly increasing")
            fixed_squeeze = measurement.get("fixed_squeeze", 1.0)
            if type(fixed_squeeze) not in (int, float) or not math.isfinite(fixed_squeeze):
                raise AssertionError(f"{measurement_id}: fixed_squeeze must be finite")
        else:
            mode = measurement.get("shift_mode")
            if mode not in ("Limit", "Center") or not isinstance(measurement.get("shift_value"), str):
                raise AssertionError(f"{measurement_id}: Limit/Center shift policy is required")
            try:
                lo, hi = [float(part.strip()) for part in measurement["shift_value"].split(",")]
            except (TypeError, ValueError):
                raise AssertionError(f"{measurement_id}: shift_value must contain exactly two finite numbers") from None
            if not (math.isfinite(lo) and math.isfinite(hi)):
                raise AssertionError(f"{measurement_id}: shift_value must contain exactly two finite numbers")
            if mode == "Limit" and lo >= hi:
                raise AssertionError(f"{measurement_id}: Limit lower bound must be below upper bound")
            if mode == "Center" and hi <= 0:
                raise AssertionError(f"{measurement_id}: Center halfwidth must be positive")
            if mode == "Limit":
                for field in ("seed_range", "seed_step"):
                    value = measurement.get(field)
                    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                        raise AssertionError(f"{measurement_id}: {field} must be finite and positive")
                seed_range = float(measurement["seed_range"])
                if max(-seed_range, lo) >= min(seed_range, hi):
                    raise AssertionError(f"{measurement_id}: Limit and seed_range must overlap")
    if used != set(dep_by_id):
        raise AssertionError(f"unused/extra dependencies: {sorted(set(dep_by_id) - used)}")
    return dep_by_id


def verify_dependencies(dep_by_id):
    for dep in dep_by_id.values():
        path = dep["resolved_path"]
        if not os.path.isfile(path):
            raise AssertionError(f"required file missing: {dep['id']} ({portable_basename(path)})")
        actual = sha256(path)
        if actual.lower() != dep["sha256"].lower():
            raise AssertionError(f"hash mismatch: {dep['id']}: {actual}")


def public_dependency(dep):
    """Shareable identity without manifest or resolved directory paths."""
    return {"id": dep["id"], "role": dep["role"], "sha256": dep["sha256"].lower(),
            "name": portable_basename(dep["resolved_path"])}


def alpha_row_identity(path, row_index):
    with open(path, encoding="utf-8") as fh:
        rows = [line.rstrip("\r\n") for line in fh if line.strip() and not line.startswith("#")]
    headings, values = rows[0].split("\t"), rows[row_index + 1].split("\t")
    row = dict(zip(headings[:5], values[:5]))
    return {"selection_method": "exact alpha data-row index", "row_index": row_index,
            "exported_row_idx": int(row["row_idx"]), "doy": float(row["doy"]),
            "datetime": row["datetime"], "state": "ambient_60s_average",
            "state_source": "alpha export header ambient_avg_sec=60"}


def run_case(case, dependencies):
    started = time.perf_counter()
    with open(dependencies[case["source_fitset_id"]]["resolved_path"], encoding="utf-8") as fh:
        scenario = json.load(fh)
    channel_id = str(case["channel_id"])
    if channel_id not in scenario.get("channels", {}):
        raise AssertionError(f"{case['id']}: channel {channel_id} is absent")
    cfg = copy.deepcopy(scenario["channels"][channel_id])
    policy = exact_bool(case["allow_negative_gas"], f"{case['id']}.case policy")
    cfg["allow_negative_gas"] = policy
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
    initialization = result["nonlinear_initialization"]
    fit_identity = {"channel_id": channel_id, "fit_sign": 1.0, "W": "identity",
                    "detector_px_inclusive": [int(cfg["f_min"]), int(cfg["f_max"])],
                    "alpha_local_px_inclusive": [int(cfg["f_min"]) - px_start,
                                                   int(cfg["f_max"]) - px_start],
                    "wavelength_nm_inclusive": [float(wave[int(cfg["f_min"]) - px_start]),
                                                  float(wave[int(cfg["f_max"]) - px_start])],
                    "poly": int(cfg["poly_deg"]), "step_limit": float(cfg.get("step_limit", .5)),
                    "shift": {"mode": "Fix", "value": float(case["fixed_shift"])},
                    "squeeze": {"mode": "Fix", "value": float(case.get("fixed_squeeze", 1.0))},
                    "effective_nonlinear": initialization,
                    "seed_grid": {"state": "N/A", "reason": "fixed shift and squeeze"},
                    "etalon": {"enabled": True, "search_rad_per_px": [0.02, 0.40],
                                "detected_frequency": float(result["etalon_frequency"])},
                    "temperature_pressure": {"T_C": float(temp), "P_mbar": float(pressure),
                                               "source": "selected alpha row",
                                               "scenario_gas_temp_C": float(cfg.get("gas_temp", 0.0)),
                                               "reference_t_ref_C":
                                               [float(props[g].get("t_ref", 25.0))
                                                for g in engine.gas_list]}}
    public_config = {"fit": fit_identity, "reference_order": expected_identity,
                     "gas_order": list(engine.gas_list), "multipliers": engine_mults,
                     "scaling_factors": [float(engine.scaling_factors[g]) for g in engine.gas_list],
                     "allow_negative_gas": policy}
    return {"id": case["id"], "status": "PERFORMED", "evidence_role": case["evidence_role"],
            "row_index": int(case["row_index"]), "fixed_shift": float(case["fixed_shift"]),
            "allow_negative_gas": policy, "metrics": metrics,
            "sample_identity": alpha_row_identity(dependencies[case["alpha_id"]]["resolved_path"],
                                                   int(case["row_index"])),
            "config_identity": public_config, "config_sha256": canonical_sha256(public_config),
            "engine_identity": {"gas_order": list(engine.gas_list), "multipliers": engine_mults,
                                "scaling_factors": public_config["scaling_factors"]},
            "t2": {"state": "UNAVAILABLE", "reason": "behavioral policy comparison has no O4 absolute anchor"},
            "elapsed_s": time.perf_counter() - started}


def run_measurement(spec, case_by_id, dependencies):
    """Remeasure a single-row offline fit path; this is deliberately not worker E2E."""
    case = copy.deepcopy(case_by_id[spec["source_case_id"]])
    with open(dependencies[case["source_fitset_id"]]["resolved_path"], encoding="utf-8") as fh:
        cfg = copy.deepcopy(json.load(fh)["channels"][str(case["channel_id"])])
    policy = exact_bool(case["allow_negative_gas"], f"{spec['id']}.case policy")
    cfg["wl_path"] = dependencies[case["wavecal_id"]]["resolved_path"]
    cfg["refs"] = [{**cfg["refs"][i], "path": dependencies[r["dependency_id"]]["resolved_path"]}
                   for i, r in enumerate(case["expected_references"])]
    engine = build_engine_from_config(cfg)
    wave, alpha, temp, pressure, px_start = DataIO.load_alpha_trace_row_mapped(
        dependencies[case["alpha_id"]]["resolved_path"], int(case["row_index"]))
    px_min, px_max = int(cfg["f_min"]) - px_start, int(cfg["f_max"]) - px_start
    target = case.get("target", "NO2")

    def observe(mode, value, fixed_squeeze=None):
        props = copy.deepcopy(cfg["ref_props"])
        props[target]["sh_mode"], props[target]["sh_val"] = mode, str(value)
        if fixed_squeeze is not None:
            props[target].update(sq_mode="Fix", sq_val=str(fixed_squeeze))
        result = PO.fit_scan(
            engine, DoasFitter(engine), props, wave, alpha, temp, pressure,
            px_min, px_max, int(cfg["poly_deg"]), float(cfg.get("step_limit", .5)),
            target=target, seed_range=float(spec.get("seed_range", 15.0)),
            seed_step=float(spec.get("seed_step", .25)), allow_negative_gas=policy)
        init = result["nonlinear_initialization"]
        return {"declared_shift": {"mode": mode, "value": str(value)},
                "declared_squeeze": {"mode": props[target]["sq_mode"],
                                     "value": str(props[target]["sq_val"])},
                "initialization": init, "fitted_shift": result["shifts"][target],
                "fitted_squeeze": result["squeezes"][target],
                "metrics": {"conc": float(result["conc"]),
                            "rms_sig": float(result["rms_sig"]),
                            "abs_ac1": abs(float(result["autocorr1"]))}}

    if spec["type"] == "fixed_shift_grid":
        observations = [observe("Fix", value, spec.get("fixed_squeeze", 1.0))
                        for value in spec["shift_values"]]
        policy_detail = {"shift_values": list(map(float, spec["shift_values"])),
                         "fixed_squeeze": float(spec.get("fixed_squeeze", 1.0)),
                         "seed_grid": {"state": "N/A", "reason": "shift and squeeze are fixed"}}
    else:
        observations = [observe(spec["shift_mode"], spec["shift_value"])]
        declared_a, declared_b = map(float, spec["shift_value"].split(","))
        seed_range = float(spec.get("seed_range", 15.0))
        policy_detail = {"shift_mode": spec["shift_mode"], "shift_value": spec["shift_value"],
                         "seed_grid": ({"range": seed_range,
                                        "step": float(spec.get("seed_step", .25)),
                                        "effective_interval": [max(-seed_range, declared_a),
                                                               min(seed_range, declared_b)],
                                        "selection": "minimum linear-fit RMS before final VarPro"}
                                       if spec["shift_mode"] == "Limit" else
                                       {"state": "N/A", "reason": "Center bypasses grid seeding"})}
    return {"id": spec["id"], "type": spec["type"], "status": "OBSERVED",
            "execution_scope": "offline single-row param_optimizer.fit_scan; not worker end-to-end",
            "initialization_scope": ("Center-anchored bounds; fit_scan supplies current shift 0 and "
                                     "setup_fit_parameters clips theta0 into those bounds"
                                     if spec.get("shift_mode") == "Center" else
                                     "param_optimizer fit_scan initialization"),
            "source_case_id": spec["source_case_id"], "allow_negative_gas": policy,
            "fit_context": {"poly": int(cfg["poly_deg"]),
                            "step_limit": float(cfg.get("step_limit", .5)),
                            "detector_px_inclusive": [int(cfg["f_min"]), int(cfg["f_max"])],
                            "fit_sign": 1.0, "W": "identity",
                            "sample": alpha_row_identity(
                                dependencies[case["alpha_id"]]["resolved_path"],
                                int(case["row_index"]))},
            "policy": policy_detail, "observations": observations,
            "t2": {"state": "UNAVAILABLE", "reason": "ROI1 measurement has no absolute physical anchor"}}


def evaluate_assertions(specs, performed):
    rows, output = {row["id"]: row for row in performed}, []
    for spec in specs:
        high, low = rows[spec["high_case_id"]], rows[spec["low_case_id"]]
        observed = {metric: {"high": high["metrics"][metric], "low": low["metrics"][metric]}
                    for metric in spec["strictly_greater"]}
        passed = all(pair["high"] > pair["low"] for pair in observed.values())
        output.append({"id": spec["id"], "type": spec["type"], "source": spec["source"],
                       "contract": "qualitative ordering only; not cross-platform numeric equivalence or scientific tolerance",
                       "strictly_greater": spec["strictly_greater"], "observed": observed,
                       "status": "PASS" if passed else "FAIL"})
        if not passed:
            raise AssertionError(f"relational assertion failed: {spec['id']}")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=os.environ.get("CAESAR_GOLDEN_MANIFEST"))
    parser.add_argument("--data-root", default=os.environ.get("CAESAR_GOLDEN_DATA_ROOT"),
                        help="root for portable relative dependency paths")
    parser.add_argument("--result", help="optional structured local result JSON")
    args = parser.parse_args(argv)
    if not args.manifest:
        print("SKIP: no --manifest or CAESAR_GOLDEN_MANIFEST")
        return 0
    manifest_path = os.path.abspath(args.manifest)
    excluded = [os.path.abspath(args.result)] if args.result else []
    report = {"schema_version": SCHEMA_VERSION, "suite_version": SUITE_VERSION,
              "manifest_sha256": None, "git": FE.git_provenance(ROOT, excluded),
              "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                          "numpy": np.__version__, "scipy": scipy.__version__},
              "performed": [], "measurements": [], "failed": [], "skipped": []}
    dependencies = {}
    candidate_inputs = [manifest_path]
    try:
        if not os.path.isfile(manifest_path):
            raise AssertionError(f"manifest not found: {portable_basename(manifest_path)}")
        report["manifest_sha256"] = sha256(manifest_path)
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        candidate_inputs += [resolve(os.path.dirname(manifest_path), dep["path"], args.data_root)
                             for dep in manifest.get("dependencies", [])
                             if isinstance(dep, dict) and isinstance(dep.get("path"), str)]
        dependencies = validate_manifest(manifest, os.path.dirname(manifest_path), args.data_root)
        verify_dependencies(dependencies)
        report["dependencies"] = [public_dependency(dep) for dep in dependencies.values()]
        report["performed"] = [run_case(case, dependencies) for case in manifest["cases"]]
        case_by_id = {case["id"]: case for case in manifest["cases"]}
        report["measurements"] = [run_measurement(spec, case_by_id, dependencies)
                                  for spec in manifest.get("measurements", [])]
        report["assertions"] = evaluate_assertions(manifest["assertions"], report["performed"])
        report["assertion_scope"] = manifest["assertion_scope"]
        report["generation"] = {"base_commit": report["git"]["head"],
                                "artifact_self_excluded": bool(report["git"]["excluded_paths"]),
                                "artifact_name": portable_basename(args.result) if args.result else None}
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
