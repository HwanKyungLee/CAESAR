"""Reproduce the hash-pinned cold/O4 Tier-2 checkpoint (optional data)."""
from __future__ import annotations

import argparse, copy, glob, hashlib, json, math, os, platform, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
import scipy

from core.doas_fit import DoasFitter
from core import fit_explorer as FE
from core import fit_physics as FP
from core import param_optimizer as PO
from tools.optimize_params import build_engine_from_config, load_alpha, nm_to_px


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def evaluate_t2(eng, scans, props_without, props_with, px_min, px_max, poly, step_limit,
                allow_negative_gas, expected_n=None):
    """Map missing physical-anchor inputs to UNAVAILABLE before running the T2 judge."""
    if not scans or any(not (math.isfinite(float(scan[2])) and math.isfinite(float(scan[3])))
                        for scan in scans):
        return {"state": "UNAVAILABLE", "reason": "selected scan is missing finite temperature/pressure"}
    if eng is None or not all(hasattr(eng, name) for name in
                              ("gas_list", "raw_references", "scaling_factors", "multipliers")):
        return {"state": "UNAVAILABLE", "reason": "T2 engine prerequisites are unavailable"}
    if "O4" not in eng.gas_list or "NO2" not in eng.gas_list or "O4" not in eng.raw_references:
        return {"state": "UNAVAILABLE", "reason": "O4/NO2 reference prerequisites are unavailable"}
    try:
        scale = float(eng.scaling_factors["O4"])
        multiplier = float(eng.multipliers["O4"])
        reference = np.asarray(eng.raw_references["O4"], float)
    except (KeyError, TypeError, ValueError):
        return {"state": "UNAVAILABLE", "reason": "O4 amount conversion prerequisites are unavailable"}
    if (not math.isfinite(scale) or scale == 0 or not math.isfinite(multiplier)
            or reference.ndim != 1 or not np.all(np.isfinite(reference))):
        return {"state": "UNAVAILABLE", "reason": "O4 amount conversion prerequisites are unavailable"}
    if not isinstance(props_with, dict) or "O4" not in props_with:
        return {"state": "UNAVAILABLE", "reason": "O4 fit policy is unavailable"}
    anchors = [FP.theoretical_amount("O4", float(scan[2]), float(scan[3])) for scan in scans]
    if any(value is None or not math.isfinite(float(value)) or float(value) <= 0 for value in anchors):
        return {"state": "UNAVAILABLE", "reason": "O4 theoretical anchor is unavailable"}
    verdict = FP.judge_reference(
        eng, DoasFitter(eng), scans, props_without, props_with, px_min, px_max,
        poly, step_limit, candidate="O4", target="NO2", collin_hi=FP.COLLIN_HI_DEFAULT,
        abs_max_ratio=3.0, allow_negative_gas=allow_negative_gas)
    expected_n = len(scans) if expected_n is None else expected_n
    required = ("abs_ratio", "candidate_cv", "target_cv", "pair_collinearity",
                "multiple_R", "corr_with_target")
    if verdict.get("n") != expected_n:
        return {"state": "UNAVAILABLE", "reason": "T2 judge did not evaluate every selected scan",
                "observed": verdict}
    if any(not math.isfinite(float(verdict.get(key, float("nan")))) for key in required):
        return {"state": "UNAVAILABLE", "reason": "T2 judge returned incomplete/non-finite required outputs",
                "observed": verdict}
    if type(verdict.get("exclude")) is not bool:
        return {"state": "UNAVAILABLE", "reason": "T2 judge returned incomplete verdict state",
                "observed": verdict}
    return {"state": "FAIL" if verdict["exclude"] else "PASS", "observed": verdict}


def gate_audit(observed):
    """Expose the existing judge rules without inventing a combined score or tolerance."""
    constant_floor = 0.15
    return {
        "magnitude": {"state": "FAIL" if observed["impossible"] else "PASS",
                      "input": observed["abs_ratio"], "operator": ">",
                      "tolerance": 3.0,
                      "source": "core.fit_physics.judge_reference abs_max_ratio default"},
        "constant_species": {
            "state": "FAIL" if observed["candidate_cv"] > max(observed["target_cv"], constant_floor) else "PASS",
            "input": observed["candidate_cv"], "operator": ">",
            "tolerance": max(observed["target_cv"], constant_floor),
            "tolerance_components": {"target_cv": observed["target_cv"], "floor": constant_floor},
            "source": "core.fit_physics.fitted_amount_health constant_flag rule"},
        "collinearity": {"state": "FAIL" if observed["pair_collinearity"] > FP.COLLIN_HI_DEFAULT else "PASS",
                          "input": observed["pair_collinearity"], "operator": ">",
                          "tolerance": FP.COLLIN_HI_DEFAULT,
                          "source": "core.fit_physics.COLLIN_HI_DEFAULT"},
        "trade_off": {"state": "FAIL" if observed["corr_with_target"] < -0.5 else "PASS",
                       "input": observed["corr_with_target"], "operator": "<",
                       "tolerance": -0.5,
                       "source": "core.fit_physics.judge_reference trade_off rule"},
    }


def alpha_identity(path, expected):
    """Validate the raw export contract and identify load_alpha()'s first row."""
    columns = None
    header = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("# I0_mode="):
                tokens = dict(item.split("=", 1) for item in line[2:].split() if "=" in item)
                header.update(I0_mode=tokens.get("I0_mode"), ZA_count=int(tokens["ZA_count"]))
            elif line.startswith("# ambient_avg_sec="):
                header["ambient_avg_sec"] = int(line.split("=", 1)[1].split()[0])
            elif line.startswith("# RL_factor="):
                tokens = line[2:].split()
                header["RL_factor"] = float(tokens[0].split("=", 1)[1])
                header["d_cm"] = float(tokens[1].split("=", 1)[1])
            elif line.startswith("# channel="):
                tokens = dict(item.split("=", 1) for item in line[2:].split() if "=" in item)
                header.update(channel=tokens.get("channel"), label=tokens.get("label"))
            if line.startswith("#"):
                continue
            values = line.rstrip("\n").split("\t")
            if values and values[0] == "row_idx":
                columns = {name: i for i, name in enumerate(values)}
                required = {"row_idx", "datetime", "T_C", "P_mbar"}
                if not required.issubset(columns):
                    raise AssertionError(f"alpha header lacks required columns: {os.path.basename(path)}")
            elif columns is not None:
                if any(header.get(key) != value for key, value in expected.items()):
                    raise AssertionError(f"alpha export provenance changed: {os.path.basename(path)}")
                T_C, P_mbar = float(values[columns["T_C"]]), float(values[columns["P_mbar"]])
                if not (math.isfinite(T_C) and math.isfinite(P_mbar)):
                    raise AssertionError(f"alpha T/P is non-finite: {os.path.basename(path)}")
                return {"row_idx": values[columns["row_idx"]],
                        "datetime": values[columns["datetime"]], "state": "ambient_60s_average",
                        "T_C": T_C, "P_mbar": P_mbar,
                        **header}
    raise AssertionError(f"alpha has no data row: {os.path.basename(path)}")


def verify_population(root, manifest, deps):
    pattern = os.path.join(root, *manifest["population_glob"].split("/"))
    lo, hi = manifest["date_range"]
    population = [os.path.realpath(path) for path in glob.glob(pattern)
                  if lo <= os.path.basename(os.path.dirname(path)) <= hi]
    population.sort(key=lambda path: os.path.relpath(path, root).replace("\\", "/"))
    if len(population) != manifest["source_population_n"]:
        raise AssertionError("cold alpha source population count changed")
    indices = manifest["selected_zero_based_indices"]
    if len(indices) != len(manifest["sample_ids"]) or any(
            type(index) is not int or index < 0 or index >= len(population) for index in indices):
        raise AssertionError("cold alpha selected indices are invalid")
    selected = [population[index] for index in indices]
    expected = [os.path.realpath(deps[dep_id]) for dep_id in manifest["sample_ids"]]
    if selected != expected:
        raise AssertionError("cold alpha selected indices no longer map to sample_ids")


def audit_fits(eng, scans, sample_rows, props, px_min, px_max, poly, step_limit,
               allow_negative_gas):
    rows = []
    for scan, identity in zip(scans, sample_rows):
        try:
            result = PO.fit_scan(eng, DoasFitter(eng), props, *scan, px_min, px_max, poly,
                                 step_limit, allow_negative_gas=allow_negative_gas)
            coeff = float(result["coeffs"]["O4"])
            theoretical = FP.theoretical_amount("O4", scan[2], scan[3])
            retrieved = FP.retrieved_amount(eng, coeff, "O4")
            init = result["nonlinear_initialization"]
            sh_i, sq_i = init["active"].index("NO2_sh"), init["active"].index("NO2_sq")
            rows.append({"id": identity["id"], "fit_success": True,
                         "deterministic_seed": result["deterministic_seed"],
                         "effective_target": {
                             "theta0": {"shift": init["theta0"][sh_i], "squeeze": init["theta0"][sq_i]},
                             "lower": {"shift": init["lower"][sh_i], "squeeze": init["lower"][sq_i]},
                             "upper": {"shift": init["upper"][sh_i], "squeeze": init["upper"][sq_i]},
                             "final": {"shift": result["shifts"]["NO2"],
                                       "squeeze": result["squeezes"]["NO2"]}},
                         "NO2_coefficient": float(result["coeffs"]["NO2"]),
                         "O4": {"coefficient": coeff, "retrieved_amount": retrieved,
                                "theoretical_amount": theoretical,
                                "abs_ratio": abs(retrieved / theoretical)},
                         "etalon_frequency_rad_per_px": result["etalon_frequency"]})
        except Exception as exc:
            rows.append({"id": identity["id"], "fit_success": False,
                         "error": f"{type(exc).__name__}: {exc}"})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest")
    parser.add_argument("--data-root", default=os.environ.get("CAESAR_GOLDEN_DATA_ROOT"))
    parser.add_argument("--result")
    parser.add_argument("--provenance-exclude", action="append", default=[])
    args = parser.parse_args(argv)
    if not args.manifest:
        print("SKIP: no --manifest")
        return 0
    if not args.data_root:
        parser.error("--data-root or CAESAR_GOLDEN_DATA_ROOT is required")
    root = os.path.realpath(args.data_root)
    manifest_path = os.path.abspath(args.manifest)
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("claim_scope") != (
            "current-code cold/O4 T2 checkpoint only; not concentration truth, T3, plateau, or recommendation"):
        raise AssertionError("cold/O4 manifest contract changed")
    deps = {}
    for dep in manifest["dependencies"]:
        path = os.path.realpath(os.path.join(root, dep["path"]))
        if os.path.commonpath((root, path)) != root or not os.path.isfile(path):
            raise AssertionError(f"missing/escaping dependency: {dep['id']}")
        if sha256(path) != dep["sha256"]:
            raise AssertionError(f"hash mismatch: {dep['id']}")
        deps[dep["id"]] = path
    verify_population(root, manifest, deps)

    cfg = copy.deepcopy(json.load(open(deps["fitset"], encoding="utf-8"))["channels"]["3"])
    cfg["wl_path"] = deps["wavecal"]
    expected = [("CHOCHO", "ref_chocho"), ("H2O", "ref_h2o"), ("NO2", "ref_no2")]
    if [r["name"] for r in cfg["refs"]] != [name for name, _ in expected]:
        raise AssertionError("base reference order changed")
    cfg["refs"] = [{**ref, "path": deps[dep_id]}
                   for ref, (_, dep_id) in zip(cfg["refs"], expected)]
    eng = build_engine_from_config(cfg)
    eng.add_reference("O4", deps["ref_o4"], wave_nm=np.asarray(eng._wave_axis).flatten(), multiplier=1.0)
    eng.apply_ils_convolution(0.0)
    props = copy.deepcopy(cfg["ref_props"])
    props["O4"] = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link",
                   "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}
    expected_header = manifest["expected_alpha_header"]
    if (float(expected_header["RL_factor"]) != float(cfg.get("rl_factor")) or
            float(expected_header["d_cm"]) != float(cfg.get("cavity_d"))):
        raise AssertionError("manifest alpha header expectation disagrees with FitSet")
    sample_rows = [{"id": dep_id, **alpha_identity(deps[dep_id], expected_header)}
                   for dep_id in manifest["sample_ids"]]
    scans = [load_alpha(deps[dep_id]) for dep_id in manifest["sample_ids"]]
    for scan, identity in zip(scans, sample_rows):
        if scan[2] != identity["T_C"] or scan[3] != identity["P_mbar"]:
            raise AssertionError(f"{identity['id']}: load_alpha did not preserve raw T/P")
    px_min = nm_to_px(scans[0][0], float(cfg["fit_start_nm"]))
    px_max = nm_to_px(scans[0][0], float(cfg["fit_end_nm"]))
    t2_by_policy = {}
    started = time.perf_counter()
    for policy_name, allow_negative in (("nonnegative", False), ("signed", True)):
        audit_rows = audit_fits(eng, scans, sample_rows, props, px_min, px_max,
                                int(cfg["poly_deg"]), float(cfg["step_limit"]), allow_negative)
        outcome = evaluate_t2(eng, scans, cfg["ref_props"], props, px_min, px_max,
                              int(cfg["poly_deg"]), float(cfg["step_limit"]), allow_negative,
                              expected_n=len(scans))
        if outcome["state"] != manifest["expected_t2_states"][policy_name]:
            raise AssertionError(f"{policy_name}: expected T2 FAIL, got {outcome['state']}")
        if not all(row["fit_success"] for row in audit_rows):
            raise AssertionError(f"{policy_name}: per-scan audit fit failed")
        ratios = [row["O4"]["abs_ratio"] for row in audit_rows]
        if not math.isclose(float(np.median(ratios)), outcome["observed"]["abs_ratio"], rel_tol=1e-12):
            raise AssertionError(f"{policy_name}: audit/judge O4 ratio mismatch")
        o4 = np.asarray([row["O4"]["coefficient"] for row in audit_rows])
        no2 = np.asarray([row["NO2_coefficient"] for row in audit_rows])
        def cv(values):
            return float(np.std(values) / (abs(np.mean(values)) + 1e-30))
        checks = ((cv(o4), outcome["observed"]["candidate_cv"], "O4 CV"),
                  (cv(no2), outcome["observed"]["target_cv"], "NO2 CV"),
                  (float(np.corrcoef(o4, no2)[0, 1]),
                   outcome["observed"]["corr_with_target"], "O4/NO2 correlation"))
        if any(not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-15)
               for actual, expected, _ in checks):
            raise AssertionError(f"{policy_name}: per-scan audit does not reproduce judge aggregates")
        t2_by_policy[policy_name] = {"allow_negative_gas": allow_negative,
                                     "per_scan_audit": audit_rows, **outcome,
                                     "gates": gate_audit(outcome["observed"])}
    elapsed_seconds = time.perf_counter() - started
    shift_lo, shift_hi = map(float, str(cfg["ref_props"]["NO2"]["sh_val"]).split(","))
    report = {
        "schema_version": 1, "manifest_sha256": sha256(manifest_path),
        "claim_scope": manifest["claim_scope"],
        "dependencies": [{"id": d["id"], "sha256": d["sha256"], "name": os.path.basename(deps[d["id"]])}
                         for d in manifest["dependencies"]],
        "sampling": {"method": "sorted relative path, zero-based indices 0:450:30", "n": len(scans),
                     "source_population_n": manifest["source_population_n"],
                     "date_range": manifest["date_range"], "population_glob": manifest["population_glob"],
                     "population_filter": manifest["population_filter"],
                     "population_order": manifest["population_order"],
                     "selected_zero_based_indices": manifest["selected_zero_based_indices"],
                     "samples": sample_rows},
        "fit": {"gas_order": list(eng.gas_list),
                "multipliers": {g: float(eng.multipliers[g]) for g in eng.gas_list},
                "scaling_factors": {g: float(eng.scaling_factors[g]) for g in eng.gas_list},
                "gas_policies_evaluated": [False, True],
                "fit_sign": 1.0, "W": "identity", "poly": int(cfg["poly_deg"]),
                "window_nm_inclusive": [float(cfg["fit_start_nm"]), float(cfg["fit_end_nm"])],
                "local_px_inclusive": [px_min, px_max], "step_limit": float(cfg["step_limit"]),
                "coordinate_provenance": "nm endpoints mapped independently on first selected alpha wave axis by nearest pixel",
                "target_shift": {"mode": cfg["ref_props"]["NO2"]["sh_mode"],
                                 "value": cfg["ref_props"]["NO2"]["sh_val"],
                                 "configured_seed_range": [-15.0, 15.0],
                                 "effective_seed_range": [max(-15.0, shift_lo), min(15.0, shift_hi)],
                                 "seed_step": 0.25},
                "target_squeeze": {"mode": cfg["ref_props"]["NO2"]["sq_mode"],
                                   "value": cfg["ref_props"]["NO2"]["sq_val"],
                                   "effective_seed_range": [0.99, 1.01], "seed_step": 0.001},
                "ref_props": props,
                "linked_species": ["CHOCHO", "H2O", "O4"],
                "gas_temperature_override_C": float(cfg.get("gas_temp", 0.0)),
                "cavity_d_cm": float(cfg.get("cavity_d", 51.8)),
                "rl_factor": float(cfg.get("rl_factor", 1.0)),
                "tikhonov_lambda": float(cfg.get("tikhonov_lambda", 0.0)),
                "robust_fit": bool(cfg.get("use_robust", False)),
                "etalon": {"enabled": True, "frequency_search_cycles_per_px": [0.02, 0.40],
                            "frequency_search_rad_per_px": [float(2*np.pi*0.02), float(2*np.pi*0.40)],
                            "detected_frequency_rad_per_px_by_policy": {
                                name: [row["etalon_frequency_rad_per_px"]
                                       for row in value["per_scan_audit"]]
                                for name, value in t2_by_policy.items()}}},
        "physical_anchor": {"species": "O4", "formula": "(0.2095 * n_air)^2",
                            "oxygen_mole_fraction": 0.2095,
                            "air_number_density_formula": "N_LOSCHMIDT * (P_mbar / 1013.25) * (273.15 / (T_C + 273.15)); N_LOSCHMIDT = 101325/(1.380649e-23*273.15)*1e-6 = 2.686780111e19 (CODATA 2018)",
                            "source": "core.fit_physics.air_number_density/theoretical_amount",
                            "temperature_pressure_source": "each selected alpha export row",
                            "temperature_C": [float(scan[2]) for scan in scans],
                            "pressure_mbar": [float(scan[3]) for scan in scans],
                            "za_provenance": manifest["za_provenance"]},
        "t2": {"states": t2_by_policy, "threshold_sources": {
                    "collinearity": "core.fit_physics.COLLIN_HI_DEFAULT",
                    "absolute_ratio": "core.fit_physics.judge_reference default abs_max_ratio=3.0",
                    "constant_species": "core.fit_physics.fitted_amount_health CV rule"}},
        "selection": {"pruning": {"state": "N/A", "reason": "checkpoint evaluates every selected scan"},
                      "closure": {"state": "N/A", "reason": "not a plateau/selection checkpoint"}},
        "execution": {"elapsed_seconds": elapsed_seconds, "timing_source": "time.perf_counter"},
        "git": FE.git_provenance(ROOT, [p for p in (
            args.result, os.path.join(ROOT, "diagnostics", "fit_explorer", "cold_o4_result_v1.json"),
            *args.provenance_exclude) if p]),
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "numpy": np.__version__, "scipy": scipy.__version__},
    }
    if any(not math.isfinite(row["observed"]["abs_ratio"]) for row in t2_by_policy.values()):
        raise AssertionError("O4 anchor was not evaluated for both policies")
    if args.result:
        FE.ensure_output_safe(args.result, [manifest_path, *deps.values()])
        FE.write_report(args.result, report)
    print("PASS: cold/O4 " + ", ".join(
        f"{name}=T2 {row['state']} abs_ratio={row['observed']['abs_ratio']:.6g}"
        for name, row in t2_by_policy.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
