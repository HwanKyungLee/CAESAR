"""Execute a V2 plan against explicitly bound alpha files; diagnostics only."""
import json
import os
import tempfile
import copy
import sqlite3
from pathlib import Path
from contextlib import closing
from datetime import date

import numpy as np

from core import fit_explorer as FE
from core import fit_explorer_v2 as V2
from core import fit_explorer_batch as FB
from core.data_io import DataIO
from core.engine import UniversalEngine
from core.doas_fit import DoasFitter
from core import param_optimizer as PO


COEFFICIENT_UNIT = "normalized_reference_coefficient"


def _runtime_callback(engine, cfg, driver, reference_support):
    """Same production fit, retaining diagnostics needed by V2 (not ppb)."""
    fitter = DoasFitter(engine)
    def fit(candidate, scan, start, *, ref_props, policy_bounds, allow_negative_gas):
        bounds = FE.independent_global_bounds(ref_props, engine.gas_list)
        result = PO.fit_scan(engine, fitter, ref_props, scan["wave"], scan["alpha"],
            scan["temperature_C"], scan["pressure_mbar"],
            candidate["px_min"] - scan["px_start"], candidate["px_max"] - scan["px_start"],
            candidate["poly"], cfg["step_limit"], driver, allow_negative_gas=True,
            controlled_start=(start["shift"], start["squeeze"]), controlled_bounds=bounds,
            controlled_initial_values=FE.independent_initial_values(bounds, driver),
            return_solver_diagnostics=True)
        diagnostics = result["solver_diagnostics"]
        strengths, differential, support_ok = {}, {}, {}
        pixels = np.arange(candidate["px_min"], candidate["px_max"] + 1, dtype=float)
        center = pixels[len(pixels) // 2]  # same absolute_center as PO.fit_scan
        for gas in engine.gas_list:
            transformed = (pixels - center) * result["squeezes"][gas] + center + result["shifts"][gas]
            lo, hi = reference_support[gas]
            support_ok[gas] = bool(np.min(transformed) >= lo and np.max(transformed) <= hi)
            values = np.asarray(engine.interpolators[gas](transformed), dtype=float)
            basis = np.polynomial.legendre.legvander(np.linspace(-1., 1., len(values)), candidate["poly"])
            residual = values - basis @ np.linalg.lstsq(basis, values, rcond=None)[0]
            strengths[gas] = float(np.linalg.norm(residual) / max(np.linalg.norm(values), 1e-300))
            differential[gas] = residual / max(np.linalg.norm(residual), 1e-300)
        correlations = {}
        for gas, values in differential.items():
            others = [v for name, v in differential.items() if name != gas]
            if not others:
                correlations[gas] = 0. if strengths[gas] > 0 else None
            else:
                matrix = np.column_stack(others)
                residual = values - matrix @ np.linalg.lstsq(matrix, values, rcond=None)[0]
                correlations[gas] = float(np.sqrt(np.clip(1 - residual @ residual, 0, 1)))
        return {"coeffs": {str(k): float(v) for k, v in result["coeffs"].items()
                           if np.isfinite(float(v))},
                "coefficient_unit": COEFFICIENT_UNIT,
                "rms": float(result["rms"]),
                "autocorr1": float(result["autocorr1"]) if np.isfinite(result["autocorr1"]) else None,
                "final_shift": float(result["shifts"][driver]),
                "final_squeeze": float(result["squeezes"][driver]),
                "objective_initial": diagnostics["objective_initial"],
                "objective_final": diagnostics["objective_final"],
                "solver_termination": diagnostics["solver_termination"],
                "boundary_hits": FE.boundary_hits(result, policy_bounds, driver),
                "collinearity": correlations, "differential_fraction": strengths,
                "reference_support_valid": support_ok}
    return fit


def run_mission(mission, bindings, output_directory, *, candidate_ids=None, max_attempts=None):
    """Bind observation IDs to files, verify hashes, fit discovery rows and resume.

    Alpha hashes refer to whole source files; row_index selects an observation.
    Holdout is deliberately not opened by this discovery execution path.
    """
    plan = V2.build_mission_plan(mission)
    if candidate_ids is not None:
        if not set(candidate_ids).issubset({c["candidate_id"] for c in plan["candidates"]}):
            raise ValueError("runtime candidate selection is absent from plan")
    limit = plan["budget"]["max_fit_attempts"] if max_attempts is None else max_attempts
    if type(limit) is not int or not 0 <= limit <= plan["budget"]["max_fit_attempts"]:
        raise ValueError("runtime fit budget is invalid")
    if not isinstance(bindings, dict):
        raise ValueError("bindings must map observation_id to path and row_index")
    discovery = plan["split"]["discovery"]
    if not discovery or set(bindings) != set(discovery):
        raise ValueError("bindings must cover exactly discovery observations")
    channels = {row["channel_id"]: row for row in mission["channels"]}
    observations = {row["observation_id"]: (channel, row)
                    for channel in mission["channels"] for row in channel["alpha_inputs"]}
    scans, seen = {}, set()
    for observation in discovery:
        binding = bindings[observation]
        if not isinstance(binding, dict) or set(binding) != {"path", "row_index"}:
            raise ValueError("binding requires path and row_index")
        path, index = binding["path"], binding["row_index"]
        if type(index) is not int or index < 0:
            raise ValueError("row_index must be a nonnegative integer")
        channel, metadata = observations[observation]
        digest = FE.sha256_file(path)
        if digest != metadata["content_hash"]:
            raise ValueError("alpha file hash does not match mission")
        key = (channel["channel_id"], digest, index)
        if key in seen:
            raise ValueError("duplicate physical observation binding")
        seen.add(key)
        wave, alpha, temperature, pressure, start = DataIO.load_alpha_trace_row_mapped(path, index)
        if not np.isfinite([temperature, pressure]).all() or pressure <= 0 or temperature <= -273.15:
            raise ValueError("alpha T/P values unavailable for production fitter")
        scan = {"id": observation, "wave": wave, "alpha": alpha, "px_start": start,
                "temperature_C": temperature, "pressure_mbar": pressure}
        candidates = [row for row in plan["candidates"] if row["channel_id"] == channel["channel_id"]]
        if candidates and FE.validate_coordinates(channel["wavelength"]["values"], [scan], candidates):
            raise ValueError("alpha and mission pixel coordinates do not match")
        scans[observation] = scan
    # Include numerical implementation and bindings in the resume identity.
    from tools.run_fit_explorer_batch import code_hash
    execution_hash = FB.canonical_json_hash({"plan": plan["plan_hash"], "code": code_hash(),
                                             "bindings": bindings, "candidate_ids": candidate_ids,
                                             "limit": limit})
    directory = os.path.join(os.path.abspath(output_directory), execution_hash)
    FB.atomic_write_json(os.path.join(directory, "plan.json"), plan, immutable=True)
    reports, spent = [], 0
    with tempfile.TemporaryDirectory(prefix="caesar-v2-refs-") as temp:
        engines = {}
        for channel_id, channel in channels.items():
            engine = UniversalEngine()
            wave = np.asarray(channel["wavelength"]["values"], dtype=float)
            engine.set_wavelength_axis(wave)
            for i, ref in enumerate(channel["references"]):
                if ref["ils_state"] != "ALREADY_CONVOLVED":
                    raise ValueError("runtime needs explicitly convolved references")
                path = os.path.join(temp, f"ref-{i}.txt")
                np.savetxt(path, np.column_stack((ref["wavelength_nm"], ref["values"])))
                ok, _ = engine.add_reference(ref["species_id"], path, wave_nm=wave)
                if not ok:
                    raise ValueError("reference failed production engine loading")
            engines[channel_id] = engine
        for candidate in plan["candidates"]:
            if candidate_ids is not None and candidate["candidate_id"] not in candidate_ids:
                continue
            engine = engines[candidate["channel_id"]]
            driver = candidate["registration"]["driver_species"]
            props = {gas: {"sh_mode": "Link", "sh_val": driver, "sq_mode": "Link", "sq_val": driver,
                           "t_ref": 25., "t_coeff": 0., "active_bands_nm": ""} for gas in engine.gas_list}
            cfg = {"refs": [{"name": gas} for gas in engine.gas_list], "ref_props": props, "step_limit": .5}
            legacy = {"id": candidate["candidate_id"], "target": driver, "policy_stage": "STAGE0_METADATA_ONLY",
                      "px_min": candidate["px_min"], "px_max": candidate["px_max"], "poly": candidate["poly"],
                      "policy": {axis: candidate["registration"][axis] for axis in ("shift", "squeeze")}}
            translated = FE.translate_zero_base_policy(cfg, props, legacy, driver)["ref_props"]
            starts = FE.stage1_policy_starts(legacy)["starts"]
            selected = [obs for obs in discovery if observations[obs][0]["channel_id"] == candidate["channel_id"]]
            channel = channels[candidate["channel_id"]]
            wave = np.asarray(channel["wavelength"]["values"], dtype=float)
            support = {r["species_id"]: np.interp([r["wavelength_nm"][0], r["wavelength_nm"][-1]],
                                                 wave, np.arange(len(wave))).tolist()
                       for r in channel["references"]}
            callback = _runtime_callback(engine, cfg, driver, support)
            bounds = {axis: ({"mode": "FIXED", "value": spec["value"]} if spec["mode"] == "Fix"
                             else {"mode": "INTERVAL", "lower": spec["lower"], "upper": spec["upper"]})
                      for axis, spec in legacy["policy"].items()}
            attempts = []
            for observation in selected:
                for start in starts:
                    if spent >= limit:
                        break
                    key = FB.canonical_json_hash([candidate["candidate_id"], observation, start])
                    path = os.path.join(directory, key + ".json")
                    if os.path.exists(path):
                        with open(path, encoding="utf-8") as handle:
                            saved = json.load(handle)
                        row = saved.get("attempt", {})
                        if (saved.get("execution_hash") != execution_hash
                                or saved.get("integrity_hash") != FB.canonical_json_hash(row)
                                or row.get("candidate_id") != candidate["candidate_id"]
                                or row.get("scan_id") != observation
                                or row.get("start_id") != start["id"]):
                            raise ValueError("cached attempt integrity mismatch")
                    else:
                        row = {"candidate_id": candidate["candidate_id"], "scan_id": observation,
                               "start_id": start["id"]}
                        try:
                            result = callback(legacy, scans[observation], start, ref_props=translated,
                                              policy_bounds=bounds, allow_negative_gas=True)
                            row.update(result, status="OK")
                        except Exception as exc:
                            row.update(status="UNAVAILABLE", exception_class=type(exc).__name__)
                        FB.atomic_write_json(path, {"execution_hash": execution_hash,
                                                   "attempt": row,
                                                   "integrity_hash": FB.canonical_json_hash(row)}, immutable=True)
                    attempts.append(row)
                    spent += 1
            reports.append({"candidate_id": candidate["candidate_id"],
                            "planned_attempts": len(selected) * len(starts), "attempts": attempts})
    evidence = V2.compare_multispecies_attempts(reports, plan["requested_species"]) if reports else None
    result = {"schema": "explorer-v2-discovery-run-v1", "execution_hash": execution_hash,
              "plan_hash": plan["plan_hash"], "consumed_fit_attempts": spent, "reports": reports,
              "evidence": evidence, "status": "DIAGNOSTIC_ONLY",
              "limitations": ["No holdout executed", "No verified species sensitivity criteria", "No recommendation or export"]}
    FB.atomic_write_json(os.path.join(directory, "result.json"), result, immutable=True)
    return result


def _criteria(value, species):
    if value is None:
        return None
    required = {"schema", "scope", "basis", "species", "registration_seed", "max_abs_ac1", "max_multiple_R",
                "min_differential_fraction"}
    if (not isinstance(value, dict) or set(value) != required
            or value["schema"] != "explorer-v2-criteria-v1"
            or value["scope"] not in {"MISSION_INTERNAL", "SYNTHETIC_CONTRACT_TEST"}
            or not isinstance(value["basis"], str) or not value["basis"].strip()
            or set(value["species"]) != set(species)):
        raise ValueError("complete predeclared criteria and basis required")
    registration = value["registration_seed"]
    if (not isinstance(registration, dict) or set(registration) != {"shift_abs_px", "squeeze_abs_factor", "basis"}
            or not isinstance(registration["basis"], str) or not registration["basis"].strip()
            or any(V2._finite(registration[k]) is None or registration[k] < 0
                   for k in ("shift_abs_px", "squeeze_abs_factor"))):
        raise ValueError("registration seed criteria require explicit pixel/factor tolerance and basis")
    for name in ("max_abs_ac1", "max_multiple_R", "min_differential_fraction"):
        if V2._finite(value[name]) is None or not 0 <= value[name] <= 1:
            raise ValueError("invalid dimensionless criterion")
    if value["max_multiple_R"] >= 1 or value["min_differential_fraction"] <= 0:
        raise ValueError("criteria cannot accept exact degeneracy or absent differential structure")
    for spec in value["species"].values():
        if (not isinstance(spec, dict) or set(spec) != {"unit", "seed_abs", "seed_rel", "model_abs",
                                                     "model_rel", "signal_floor", "signal_floor_basis"}
                or spec["unit"] != COEFFICIENT_UNIT
                or not isinstance(spec["signal_floor_basis"], str) or not spec["signal_floor_basis"].strip()
                or any(V2._finite(spec[k]) is None or spec[k] < 0 for k in
                       ("seed_abs", "seed_rel", "model_abs", "model_rel", "signal_floor"))):
            raise ValueError("species criteria need finite coefficient-space bounds and signal basis")
    return copy.deepcopy(value)


def _within(a, b, spec, prefix):
    return abs(a - b) <= spec[prefix + "_abs"] + spec[prefix + "_rel"] * max(abs(a), abs(b))


def _assess(report, species, criteria):
    attempts = report["attempts"]
    keys = {(row["scan_id"], row["start_id"]) for row in attempts}
    complete = (report["planned_attempts"] > 0 and len(attempts) == report["planned_attempts"]
                and len(keys) == len(attempts))
    numerical = complete and all(row.get("status") == "OK"
              and row.get("solver_termination", {}).get("success") is True for row in attempts)
    states, diagnostics = {}, {}
    for gas in species:
        values = {key: row.get("coeffs", {}).get(gas) for key, row in zip(
                  [(r["scan_id"], r["start_id"]) for r in attempts], attempts)}
        healthy = numerical and all(V2._finite(v) is not None for v in values.values())
        supported = complete and all(r.get("reference_support_valid", {}).get(gas) is True for r in attempts)
        groups = {}
        for (scan, _start), value in values.items():
            groups.setdefault(scan, []).append(value)
        ranges = {scan: max(v) - min(v) if all(V2._finite(x) is not None for x in v)
                  and len(v) > 1 else None for scan, v in groups.items()}
        state = "UNAVAILABLE"
        reasons = [] if healthy else ["INCOMPLETE_OR_UNSUCCESSFUL_SPECIES_ATTEMPTS"]
        if not supported:
            reasons.append("TRANSFORMED_REFERENCE_OUTSIDE_SOURCE_SUPPORT")
        checks = {}
        if healthy and criteria:
            spec = criteria["species"][gas]
            # Fixed policies have one mathematical start; they do not claim multi-start evidence.
            seeded = all(_within(min(v), max(v), spec, "seed") for v in groups.values())
            for scan in groups:
                scan_attempts = [r for r in attempts if r["scan_id"] == scan]
                for field, tolerance in (("final_shift", "shift_abs_px"), ("final_squeeze", "squeeze_abs_factor")):
                    coordinates = [r.get(field) for r in scan_attempts]
                    seeded = seeded and all(V2._finite(v) is not None for v in coordinates)
                    if all(V2._finite(v) is not None for v in coordinates):
                        seeded = seeded and max(coordinates) - min(coordinates) <= criteria["registration_seed"][tolerance]
            signal = all(abs(v) >= spec["signal_floor"] for v in values.values())
            residual = all(V2._finite(r.get("autocorr1")) is not None
                           and abs(r["autocorr1"]) <= criteria["max_abs_ac1"] for r in attempts)
            structure = all(V2._finite(r.get("collinearity", {}).get(gas)) is not None
                            and r["collinearity"][gas] <= criteria["max_multiple_R"]
                            and r.get("differential_fraction", {}).get(gas, -1) >=
                            criteria["min_differential_fraction"] for r in attempts)
            hit_count = sum(bool(r.get("boundary_hits")) for r in attempts)
            checks = {"seed_reproducible": seeded, "above_declared_signal_floor": signal,
                      "residual_structure": residual, "reference_identifiability": structure,
                      "boundary_hit_attempts": hit_count, "reference_support_valid": supported}
            if not seeded:
                reasons.append("SEED_SOLUTIONS_DISAGREE")
            if not residual:
                reasons.append("RESIDUAL_CRITERION_NOT_MET")
            if not structure:
                reasons.append("REFERENCE_STRUCTURE_CRITERION_NOT_MET")
            if not signal:
                reasons.append("SIGNAL_BELOW_DECLARED_FLOOR_NOT_QUANTITATIVE")
            if hit_count:
                reasons.append("BOUNDARY_LIMITED_DIAGNOSTIC_NOT_PHYSICAL_FAILURE")
            state = "FAIL" if not (seeded and residual and structure) else (
                    "UNAVAILABLE" if not signal or hit_count or not supported else "PASS")
        elif healthy:
            reasons.append("COMPARISON_CRITERIA_NOT_DECLARED")
        states[gas] = state
        diagnostics[gas] = {"state": state, "finite_complete": healthy,
                            "supported_complete": supported,
                            "seed_ranges": ranges, "unit": COEFFICIENT_UNIT,
                            "checks": checks, "reasons": reasons}
    return {"numeric_complete": numerical, "species": diagnostics,
            "state": "EVALUATED_PASS" if states and all(s == "PASS" for s in states.values()) else
                     "EVALUATED_FAIL" if "FAIL" in states.values() else "UNEVALUATED"}


def _pairs(reports, species, criteria):
    pairs = []
    for index, left in enumerate(reports):
        for right in reports[index + 1:]:
            lv = {(r["scan_id"], r["start_id"]): r for r in left["attempts"] if r.get("status") == "OK"}
            rv = {(r["scan_id"], r["start_id"]): r for r in right["attempts"] if r.get("status") == "OK"}
            row = {"left_candidate_id": left["candidate_id"], "right_candidate_id": right["candidate_id"],
                   "species": {}}
            for gas in species:
                paired = [(key, lv[key].get("coeffs", {}).get(gas), rv[key].get("coeffs", {}).get(gas))
                          for key in sorted(set(lv) & set(rv))]
                paired = [(key, a, b) for key, a, b in paired if V2._finite(a) is not None and V2._finite(b) is not None]
                complete = len(paired) == left["planned_attempts"] == right["planned_attempts"] and bool(paired)
                state = "UNAVAILABLE" if not complete or not criteria else (
                    "PASS" if all(_within(a, b, criteria["species"][gas], "model") for _, a, b in paired) else "FAIL")
                row["species"][gas] = {"state": state, "unit": COEFFICIENT_UNIT,
                    "paired_attempts": len(paired), "complete": complete,
                    "deltas": [{"observation_id": key[0], "start_id": key[1], "delta": b-a}
                               for key, a, b in paired]}
            pairs.append(row)
    return pairs


def _history_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(str(Path.home()), ".local", "state")
    return os.path.join(base, "CAESAR", "explorer-v2", "observation_history.sqlite3")


def _record_history(path, token, observations, roles):
    """Atomic conservative reservation, before fitting any held-out values."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    independent, reasons = True, []
    with closing(sqlite3.connect(path, timeout=30)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS uses (identity TEXT, token TEXT, role TEXT, PRIMARY KEY(identity,token,role))")
        db.execute("BEGIN IMMEDIATE")
        for observation, role in roles.items():
            meta = observations[observation]
            # Date keys deliberately ignore channel/mission labels: renaming must not reset history.
            identities = ["file:" + meta["content_hash"]]
            if meta.get("date"):
                identities.append("date:" + meta["date"])
            if meta.get("block_id"):
                identities.append("block:" + meta["block_id"])
            for identity in identities:
                old = db.execute("SELECT token,role FROM uses WHERE identity=?", (identity,)).fetchall()
                if role == "holdout" and any(t != token or r != "holdout" for t, r in old):
                    independent = False
                    reasons.append("HOLDOUT_ALREADY_REGISTERED")
                db.execute("INSERT OR IGNORE INTO uses VALUES(?,?,?)", (identity, token, role))
    return independent, sorted(set(reasons))


def run_recommendation(mission, bindings, output_directory, *, criteria=None, history_path=None):
    """Actual fits determine every verdict. No caller-provided PASS is accepted.

    Coefficients are normalized-reference coefficients, never labelled ppb. The
    independent claim is restricted to supplied prior-exposure declarations and
    the persistent registered-run history, not an assertion of unknowable history.
    """
    plan = V2.build_mission_plan(mission)
    criteria = _criteria(criteria, plan["requested_species"])
    observations = {r["observation_id"]: r for c in mission["channels"] for r in c["alpha_inputs"]}
    roles = {obs: role for role, ids in plan["split"].items() for obs in ids}
    if set(bindings) != set(roles) or not plan["split"]["discovery"]:
        raise ValueError("bindings must cover every declared split observation")
    physical, split_dates = {}, {role: set() for role in plan["split"]}
    for obs, role in roles.items():
        binding, meta = bindings[obs], observations[obs]
        if (set(binding) != {"path", "row_index"} or type(binding["row_index"]) is not int
                or binding["row_index"] < 0 or FE.sha256_file(binding["path"]) != meta["content_hash"]):
            raise ValueError("invalid physical observation binding")
        identity = (meta["content_hash"], binding["row_index"])
        if identity in physical:
            raise ValueError("same physical row appears in multiple observation identities")
        physical[identity] = obs
        if meta.get("date"):
            if date.fromisoformat(meta["date"]).isoformat() != meta["date"]:
                raise ValueError("observation dates must use canonical ISO date")
            split_dates[role].add(meta["date"])
    from tools.run_fit_explorer_batch import code_hash
    token = FB.canonical_json_hash({"mission": mission, "bindings": bindings, "criteria": criteria,
                                    "code": code_hash(), "runtime_contract": "frozen-chain-v1"})
    directory = os.path.join(os.path.abspath(output_directory), token)
    frozen_path = os.path.join(directory, "selection.json")
    # Freeze policy before discovery. Do not accept a summary supplied as evidence.
    FB.atomic_write_json(os.path.join(directory, "policy.json"),
                         {"plan": plan, "criteria": criteria, "execution_hash": token,
                          "runtime_defaults": {"allow_negative_gas": True, "secondary_registration": "LINK_TO_DRIVER",
                            "reference_temperature_C": 25., "reference_temperature_coefficient": 0.,
                            "step_limit": .5, "etalon": "DISABLED",
                            "coefficient_unit": COEFFICIENT_UNIT}}, immutable=True)
    history_ok, history_reasons = _record_history(history_path or _history_path(), token, observations, roles)
    independent = (history_ok and bool(plan["split"]["holdout"])
        and all(observations[o].get("date") for o in roles)
        and all(observations[o].get("date") and observations[o].get("previously_used") is False
                for o in plan["split"]["holdout"])
        and not (split_dates["holdout"] & (split_dates["discovery"] | split_dates["validation"])))
    if not plan["split"]["holdout"]:
        history_reasons.append("HOLDOUT_NOT_DECLARED")
    if not all(observations[o].get("date") for o in roles):
        history_reasons.append("DATE_METADATA_UNAVAILABLE")
    if any(observations[o].get("previously_used") is True for o in plan["split"]["holdout"]):
        history_reasons.append("PREVIOUSLY_USED_HOLDOUT")
    if any("previously_used" not in observations[o] for o in plan["split"]["holdout"]):
        history_reasons.append("PRIOR_HOLDOUT_EXPOSURE_UNKNOWN")
    if split_dates["holdout"] & (split_dates["discovery"] | split_dates["validation"]):
        history_reasons.append("SAME_DATE_SPLIT")
    nonholdout = [observations[o] for o, role in roles.items() if role != "holdout"]
    if any(h.get("content_hash") == d.get("content_hash") or
           (h.get("block_id") and h.get("block_id") == d.get("block_id"))
           for h in (observations[o] for o in plan["split"]["holdout"]) for d in nonholdout):
        independent = False
        history_reasons.append("HOLDOUT_FILE_OR_BLOCK_OVERLAP")
    if history_path is not None and (not criteria or criteria["scope"] != "SYNTHETIC_CONTRACT_TEST"):
        independent = False
        history_reasons.append("CUSTOM_HISTORY_HAS_NO_GLOBAL_INDEPENDENCE_CLAIM")
    spent = 0
    phases = {}
    def phase(name, ids=None):
        nonlocal spent
        selected = plan["split"][name]
        if not selected:
            return None
        local = copy.deepcopy(mission)
        local["search_policy"]["split"] = {"discovery": selected, "validation": [], "holdout": []}
        report = run_mission(local, {o: bindings[o] for o in selected}, directory,
                             candidate_ids=ids, max_attempts=plan["budget"]["max_fit_attempts"] - spent)
        spent += report["consumed_fit_attempts"]
        phases[name] = report
        return report
    discovery = phase("discovery")
    by_id = {r["candidate_id"]: r for r in discovery["reports"]}
    channels, frozen_ids = {}, []
    for channel in plan["domain"]["channels"]:
        cid = channel["channel_id"]
        candidates = [c for c in plan["candidates"] if c["channel_id"] == cid]
        requested = candidates[0].get("requested_species", plan["requested_species"]) if candidates else []
        reports = [by_id[c["candidate_id"]] for c in candidates]
        assessments = {r["candidate_id"]: _assess(r, requested, criteria) for r in reports}
        pairs = _pairs(reports, requested, criteria)
        ids = set(assessments)
        local_plan = {**plan, "candidates": candidates, "requested_species": requested,
                      "edges": [e for e in plan["edges"] if e["left_candidate_id"] in ids]}
        edge_keys = {tuple(sorted((e["left_candidate_id"], e["right_candidate_id"]))) for e in local_plan["edges"]}
        graph = V2.evaluate_candidate_graph(local_plan, {i: a["state"] for i, a in assessments.items()},
            [p for p in pairs if tuple(sorted((p["left_candidate_id"], p["right_candidate_id"]))) in edge_keys],
            pair_evidence=pairs, used_fit_attempts=spent)
        closed = [c for c in graph["components"] if c["state"] == "CLOSED_INTERNAL_COMPONENT"]
        eligible = [c for c in candidates if assessments[c["candidate_id"]]["numeric_complete"]
                    and all(s["finite_complete"] for s in assessments[c["candidate_id"]]["species"].values())
                    and all(s["supported_complete"] for s in assessments[c["candidate_id"]]["species"].values())
                    and assessments[c["candidate_id"]]["state"] != "EVALUATED_FAIL"]
        closed_ids = {c["representative_candidate_id"] for c in closed}
        if closed_ids:
            eligible = [c for c in eligible if c["candidate_id"] in closed_ids]
        chosen = min(eligible, key=lambda c: (c["poly"], c["candidate_id"])) if eligible else None
        chosen_id = chosen["candidate_id"] if chosen else None
        cohort = sorted({chosen_id} | {endpoint for e in local_plan["edges"]
                       if chosen_id in (e["left_candidate_id"], e["right_candidate_id"])
                       for endpoint in (e["left_candidate_id"], e["right_candidate_id"])}) if chosen else []
        if chosen_id in closed_ids:
            cohort = next(c["members"] for c in closed if c["representative_candidate_id"] == chosen_id)
        frozen_ids.extend(cohort)
        channels[cid] = {"candidate_id": chosen_id, "holdout_cohort": cohort,
                         "selection_basis": "CLOSED_INTERNAL_COMPONENT" if chosen_id in closed_ids else
                                            "SIMPLE_EXECUTABLE_PROVISIONAL_NOT_ROBUSTNESS_PROVEN",
                         "assessments": assessments, "comparisons": pairs, "graph": graph,
                         "requested_species": requested}
    frozen = {"execution_hash": token, "discovery_hash": FB.canonical_json_hash(discovery),
              "criteria_hash": FB.canonical_json_hash(criteria), "channels": channels}
    FB.atomic_write_json(frozen_path, frozen, immutable=True)
    # Selection is immutable on disk before opening validation or holdout spectra.
    validation = phase("validation", frozen_ids) if frozen_ids else None
    holdout = phase("holdout", frozen_ids) if frozen_ids else None
    for channel in channels.values():
        selected = channel["candidate_id"]
        accepted = bool(selected) and channel["selection_basis"] == "CLOSED_INTERNAL_COMPONENT"
        checks = {}
        for name, result in (("validation", validation), ("holdout", holdout)):
            reports = [] if result is None else [r for r in result["reports"] if r["candidate_id"] in channel["holdout_cohort"]]
            states = [_assess(r, channel["requested_species"], criteria)["state"] for r in reports]
            pairs = _pairs(reports, channel["requested_species"], criteria)
            passed = (bool(reports) and len(reports) == len(channel["holdout_cohort"])
                      and all(s == "EVALUATED_PASS" for s in states)
                      and all(s["state"] == "PASS" for p in pairs for s in p["species"].values()))
            failed = "EVALUATED_FAIL" in states or any(s["state"] == "FAIL" for p in pairs for s in p["species"].values())
            checks[name] = {"state": "PASS" if passed else "FAIL" if failed else "UNAVAILABLE", "comparisons": pairs}
            if name == "holdout" or plan["split"][name]:
                accepted = accepted and passed
        channel["checks"] = checks
        channel["status"] = "ABSTAIN" if not selected else "MISSION_RECOMMENDED" if accepted and independent else "PROVISIONAL"
        if any(check["state"] == "FAIL" for check in checks.values()):
            channel["status"] = "ABSTAIN"
    statuses = [c["status"] for c in channels.values()]
    status = "MISSION_RECOMMENDED" if statuses and all(s == "MISSION_RECOMMENDED" for s in statuses) else (
             "PROVISIONAL" if any(s != "ABSTAIN" for s in statuses) else "ABSTAIN")
    result = {"schema": "explorer-v2-recommendation-run-v1", "status": status, "execution_hash": token,
              "plan_hash": plan["plan_hash"], "scope": criteria["scope"] if criteria else "MISSION_INTERNAL_DIAGNOSTIC",
              "consumed_fit_attempts": spent, "channels": channels,
              "holdout": {"independent": independent, "history_reasons": history_reasons,
                          "scope": "DECLARED_PRIOR_EXPOSURE_AND_REGISTERED_RUN_HISTORY_ONLY"},
              "phase_evidence": {k: v["execution_hash"] for k, v in phases.items()},
              "exportable_candidate_ids": [], "apply": "FORBIDDEN",
              "limitations": ["Coefficient sensitivity is not ppb accuracy or absolute calibration",
                              "No cross-window raw RMS ranking", "No automatic Apply or export",
                              "Missing criteria yields provisional evidence, not a robustness claim"]}
    FB.atomic_write_json(os.path.join(directory, "recommendation.json"), result, immutable=True)
    return result
