"""Pure mission-to-plan contract for Fit Setting Explorer V2.

No FitSet, fit, ranking, or hidden species/channel policy is required here.
The caller supplies an explicit finite search policy; this module freezes it
against validated mission inputs for later execution.
"""
from __future__ import annotations

import hashlib
import json
import os
import copy

import numpy as np


MISSION_SCHEMA = "explorer-mission-v2"
PLAN_SCHEMA = "explorer-plan-v2"
_ILS_STATES = {"ALREADY_CONVOLVED", "NEEDS_RUNTIME_CONVOLUTION"}


def _canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _array(value, label):
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a finite numeric vector") from None
    if array.ndim != 1 or array.size < 2 or not np.isfinite(array).all():
        raise ValueError(f"{label} must be a finite numeric vector")
    return array


def _hash_hex(value, label):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} must be a lowercase SHA256 hex digest")
    return value


def _policy_axis(value, name, *, positive=False):
    if not isinstance(value, dict) or value.get("mode") not in {"Fix", "Limit"}:
        raise ValueError(f"registration {name} policy is invalid")
    mode = value["mode"]
    keys = {"mode", "value"} if mode == "Fix" else {"mode", "lower", "upper"}
    if set(value) != keys:
        raise ValueError(f"registration {name} policy schema is invalid")
    axis_keys = ("value",) if mode == "Fix" else ("lower", "upper")
    numbers = [value[key] for key in axis_keys]
    if any(isinstance(number, bool) or not isinstance(number, (int, float))
           or not np.isfinite(number) or (positive and number <= 0) for number in numbers):
        raise ValueError(f"registration {name} values are invalid")
    if mode == "Limit" and numbers[1] <= numbers[0]:
        raise ValueError(f"registration {name} limits are invalid")
    return {key: float(value[key]) if key != "mode" else value[key] for key in keys}


def _normalize_mission(mission):
    if not isinstance(mission, dict) or mission.get("schema") != MISSION_SCHEMA:
        raise ValueError("unsupported mission schema")
    required = {"schema", "mission_id", "channels", "search_policy"}
    if not required.issubset(mission) or set(mission) - {
            "schema", "mission_id", "channels", "requested_species", "legacy_fitset",
            "instrument_metadata", "search_policy"}:
        raise ValueError("mission fields do not match the v2 contract")
    if not isinstance(mission["mission_id"], str) or not mission["mission_id"].strip():
        raise ValueError("mission_id must be a non-empty opaque label")
    channels = mission["channels"]
    if not isinstance(channels, list) or not channels:
        raise ValueError("mission requires one or more channels")
    normalized = []
    channel_ids = set()
    for channel in channels:
        if not isinstance(channel, dict) or set(channel) != {
                "channel_id", "alpha_inputs", "wavelength", "references"}:
            raise ValueError("channel fields do not match the v2 contract")
        channel_id = channel["channel_id"]
        if not isinstance(channel_id, str) or not channel_id or channel_id in channel_ids:
            raise ValueError("channel_id must be a unique opaque label")
        channel_ids.add(channel_id)
        wave_spec = channel["wavelength"]
        if not isinstance(wave_spec, dict) or set(wave_spec) != {"unit", "values"} or wave_spec["unit"] != "nm":
            raise ValueError("wavelength must be an explicit nm vector")
        wave = _array(wave_spec["values"], "wavelength")
        if not np.all(np.diff(wave) > 0):
            raise ValueError("wavelength must be strictly increasing")
        alpha = channel["alpha_inputs"]
        if not isinstance(alpha, list) or not alpha:
            raise ValueError("alpha_inputs must be a non-empty list")
        alpha_ids = []
        for row in alpha:
            if not isinstance(row, dict) or not {"observation_id", "content_hash"}.issubset(row) or set(row) - {
                    "observation_id", "content_hash", "date", "block_id", "previously_used"}:
                raise ValueError("alpha input identity is invalid")
            if any(key in row and (not isinstance(row[key], str) or not row[key]) for key in ("date", "block_id")):
                raise ValueError("alpha block metadata is invalid")
            if "previously_used" in row and type(row["previously_used"]) is not bool:
                raise ValueError("alpha previously_used must be boolean")
            if not isinstance(row["observation_id"], str) or not row["observation_id"]:
                raise ValueError("observation_id must be a non-empty opaque label")
            _hash_hex(row["content_hash"], "alpha content_hash")
            alpha_ids.append(row["observation_id"])
        if len(alpha_ids) != len(set(alpha_ids)):
            raise ValueError("observation_id values must be unique per channel")
        refs = channel["references"]
        if not isinstance(refs, list) or not refs:
            raise ValueError("references must be a non-empty ordered list")
        ref_ids, normalized_refs = set(), []
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {
                    "species_id", "wavelength_nm", "values", "cross_section_unit", "ils_state"}:
                raise ValueError("reference fields do not match the v2 contract")
            species = ref["species_id"]
            if not isinstance(species, str) or not species or species in ref_ids:
                raise ValueError("species_id must be unique and non-empty")
            if ref["cross_section_unit"] not in {"cm2/molecule", "cm5/molecule2", "arb"}:
                raise ValueError("unsupported reference unit; arb is diagnostic only")
            if ref["ils_state"] not in _ILS_STATES:
                raise ValueError("reference ILS state is unknown")
            ref_wave, values = (_array(ref["wavelength_nm"], "reference wavelength"),
                                _array(ref["values"], "reference values"))
            if ref_wave.size != values.size or not np.all(np.diff(ref_wave) > 0):
                raise ValueError("reference wavelength/value coordinates are invalid")
            ref_ids.add(species)
            normalized_refs.append({"species_id": species, "coverage_nm": [float(ref_wave[0]), float(ref_wave[-1])],
                                    "content_hash": _canonical_hash({"wavelength_nm": ref_wave.tolist(),
                                                                     "values": values.tolist(),
                                                                     "unit": ref["cross_section_unit"],
                                                                     "ils_state": ref["ils_state"]}),
                                    "ils_state": ref["ils_state"]})
        normalized.append({"channel_id": channel_id, "wave_nm": wave, "alpha_ids": alpha_ids,
                           "alpha_hashes": [row["content_hash"] for row in alpha], "alpha_inputs": copy.deepcopy(alpha),
                           "references": normalized_refs})
    requested = mission.get("requested_species")
    all_species = {ref["species_id"] for channel in normalized for ref in channel["references"]}
    if requested is None:
        requested = sorted(all_species)
    if (not isinstance(requested, list) or not requested or any(not isinstance(name, str) for name in requested)
            or len(requested) != len(set(requested)) or not set(requested).issubset(all_species)):
        raise ValueError("requested_species must be registered unique species")
    return {"mission_id": mission["mission_id"], "channels": normalized,
            "requested_species": list(requested), "search_policy": mission["search_policy"]}


def _normalize_policy(policy, species):
    if not isinstance(policy, dict) or not {"windows_nm", "poly_degrees", "registration_policies", "split", "budget"}.issubset(policy) or set(policy) - {
            "windows_nm", "poly_degrees", "registration_policies", "registration_edges", "split", "budget"}:
        raise ValueError("search_policy fields do not match the v2 contract")
    windows = policy["windows_nm"]
    if not isinstance(windows, list) or not windows:
        raise ValueError("windows_nm must be a non-empty finite list")
    normalized_windows = []
    for row in windows:
        if not isinstance(row, (list, tuple)) or len(row) != 2 or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value)
                for value in row) or row[1] <= row[0]:
            raise ValueError("window bounds are invalid")
        normalized_windows.append([float(row[0]), float(row[1])])
    if len({tuple(row) for row in normalized_windows}) != len(normalized_windows):
        raise ValueError("window bounds must be unique")
    polys = policy["poly_degrees"]
    if (not isinstance(polys, list) or not polys or any(isinstance(value, bool) or not isinstance(value, int)
                                                        or value < 0 for value in polys)
            or len(polys) != len(set(polys))):
        raise ValueError("poly_degrees must be unique nonnegative integers")
    registrations = policy["registration_policies"]
    if not isinstance(registrations, list) or not registrations:
        raise ValueError("registration_policies must be non-empty")
    normalized_registrations = []
    for row in registrations:
        if not isinstance(row, dict) or set(row) != {"driver_species", "shift", "squeeze"}:
            raise ValueError("registration policy fields are invalid")
        if row["driver_species"] not in species:
            raise ValueError("registration driver is not a registered species")
        normalized_registrations.append({"driver_species": row["driver_species"],
                                         "shift": _policy_axis(row["shift"], "shift"),
                                         "squeeze": _policy_axis(row["squeeze"], "squeeze", positive=True)})
    if len({_canonical_hash(row) for row in normalized_registrations}) != len(normalized_registrations):
        raise ValueError("registration policies must be unique")
    split = policy["split"]
    if not isinstance(split, dict) or set(split) != {"discovery", "validation", "holdout"}:
        raise ValueError("split fields are invalid")
    values = []
    for name in ("discovery", "validation", "holdout"):
        rows = split[name]
        if not isinstance(rows, list) or any(not isinstance(value, str) or not value for value in rows):
            raise ValueError("split observation identities are invalid")
        values.extend(rows)
    if len(values) != len(set(values)):
        raise ValueError("discovery/validation/holdout identities overlap")
    budget = policy["budget"]
    if not isinstance(budget, dict) or set(budget) != {"max_fit_attempts", "closure_max_attempts"}:
        raise ValueError("budget fields are invalid")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in budget.values()):
        raise ValueError("budget values must be nonnegative integers")
    registration_edges = policy.get("registration_edges", [])
    if not isinstance(registration_edges, list):
        raise ValueError("registration_edges must be a list")
    seen_edges = set()
    for edge in registration_edges:
        if (not isinstance(edge, list) or len(edge) != 2 or any(type(i) is not int or i < 0 or i >= len(registrations) for i in edge)
                or edge[0] == edge[1] or tuple(sorted(edge)) in seen_edges):
            raise ValueError("registration_edges must be unique explicit policy-index pairs")
        seen_edges.add(tuple(sorted(edge)))
    return {"windows_nm": normalized_windows, "poly_degrees": list(polys), "registration_edges": sorted(seen_edges),
            "registration_policies": normalized_registrations, "split": split, "budget": budget}


def build_mission_plan(mission):
    """Validate a mission and freeze its finite, FitSet-free candidate plan."""
    normalized = _normalize_mission(mission)
    policy = _normalize_policy(normalized["search_policy"],
                               {ref["species_id"] for ch in normalized["channels"] for ref in ch["references"]})
    observation_ids = [value for ch in normalized["channels"] for value in ch["alpha_ids"]]
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError("observation_id must be unique across mission channels")
    known_observations = set(observation_ids)
    if set(sum((policy["split"][name] for name in policy["split"]), [])) - known_observations:
        raise ValueError("split contains an observation absent from the mission")
    input_hash = _canonical_hash({"mission_id": normalized["mission_id"],
                                  "channels": [{"channel_id": ch["channel_id"],
                                                "wave_nm": ch["wave_nm"].tolist(),
                                                "alpha_inputs": ch["alpha_inputs"],
                                                "references": ch["references"]}
                                               for ch in normalized["channels"]],
                                  "requested_species": normalized["requested_species"]})
    channels, candidates = [], []
    for channel in normalized["channels"]:
        common_lo = max([float(channel["wave_nm"][0])] + [ref["coverage_nm"][0] for ref in channel["references"]])
        common_hi = min([float(channel["wave_nm"][-1])] + [ref["coverage_nm"][1] for ref in channel["references"]])
        channel_candidates = []
        seen_candidate_ids = set()
        species = {ref["species_id"] for ref in channel["references"]}
        for window in policy["windows_nm"]:
            if window[0] < common_lo or window[1] > common_hi:
                continue
            lo = int(np.searchsorted(channel["wave_nm"], window[0], side="left"))
            hi = int(np.searchsorted(channel["wave_nm"], window[1], side="right")) - 1
            for poly in policy["poly_degrees"]:
                if hi - lo + 1 <= poly + len(channel["references"]):
                    continue
                for registration in policy["registration_policies"]:
                    if registration["driver_species"] not in species:
                        continue
                    identity = {"input_hash": input_hash, "channel_id": channel["channel_id"],
                                "px": [lo, hi], "poly": poly,
                                "references": channel["references"], "registration": registration}
                    candidate = {"candidate_id": "v2_" + _canonical_hash(identity)[:20],
                                 "requested_species": [name for name in normalized["requested_species"] if name in species],
                                 "planned_fit_attempts": len(set(channel["alpha_ids"]).intersection(policy["split"]["discovery"])) *
                                     (2 if any(registration[key]["mode"] == "Limit" for key in ("shift", "squeeze")) else 1),
                                 "channel_id": channel["channel_id"], "px_min": lo, "px_max": hi,
                                 "window_nm": [float(channel["wave_nm"][lo]), float(channel["wave_nm"][hi])],
                                 "poly": poly, "references": channel["references"],
                                 "registration": registration, "identity": identity,
                                 "runtime_spec": {"f_min": lo, "f_max": hi, "poly_deg": poly,
                                                  "reference_order": [ref["species_id"] for ref in channel["references"]],
                                                  "wavecal_hash": _canonical_hash(channel["wave_nm"].tolist())}}
                    if candidate["candidate_id"] in seen_candidate_ids:
                        continue
                    seen_candidate_ids.add(candidate["candidate_id"])
                    channel_candidates.append(candidate)
                    candidates.append(candidate)
        channels.append({"channel_id": channel["channel_id"], "wavecal_hash": _canonical_hash(channel["wave_nm"].tolist()),
                         "common_reference_coverage_nm": [common_lo, common_hi],
                         "candidate_count": len(channel_candidates)})
    plan = {"schema": PLAN_SCHEMA, "mission_id": normalized["mission_id"], "input_hash": input_hash,
            "policy_version": "explicit-mission-policy-v1", "requested_species": normalized["requested_species"],
            "domain": {"channels": channels, "windows_nm": policy["windows_nm"],
                       "poly_degrees": policy["poly_degrees"],
                       "registration_policies": policy["registration_policies"]},
            "status": "READY_FOR_STAGE0" if candidates else "ABSTAIN_NO_CANDIDATES",
            "candidates": candidates, "edges": _geometric_edges(candidates, policy), "split": policy["split"], "budget": policy["budget"],
            "criteria": {"state": "UNSET", "reason": "SPECIES_SENSITIVITY_CRITERIA_NOT_DECLARED"},
            "assumptions": ["FINITE_EXPLICIT_SEARCH_POLICY", "NO_FIT_EXECUTED", "NO_APPLY",
                            "EXPLICIT_FINITE_GEOMETRIC_NEIGHBORS"]}
    plan["plan_hash"] = _canonical_hash(plan)
    return plan


def _geometric_edges(candidates, policy):
    """Immediate numeric-axis neighbors; categorical adjacency is explicit only."""
    edges = []
    registrations = [_canonical_hash(row) for row in policy["registration_policies"]]
    categorical = {tuple(sorted((registrations[i], registrations[j]))) for i, j in policy["registration_edges"]}
    for index, left in enumerate(candidates):
        for right in candidates[index + 1:]:
            if left["channel_id"] != right["channel_id"]:
                continue
            same_registration = left["registration"] == right["registration"]
            kind = None
            differing = [key for key in ("px_min", "px_max", "poly") if left[key] != right[key]]
            if same_registration and len(differing) == 1:
                key = differing[0]
                lo, hi = sorted((left[key], right[key]))
                if not any(row["channel_id"] == left["channel_id"] and row["registration"] == left["registration"]
                           and all(row[other] == left[other] for other in ("px_min", "px_max", "poly") if other != key)
                           and lo < row[key] < hi for row in candidates):
                    kind = "poly" if key == "poly" else "window_" + key
            elif not differing and tuple(sorted((_canonical_hash(left["registration"]), _canonical_hash(right["registration"])))) in categorical:
                kind = "registration_explicit"
            if kind:
                a, b = sorted((left["candidate_id"], right["candidate_id"]))
                edges.append({"left_candidate_id": a, "right_candidate_id": b, "kind": kind})
    return sorted(edges, key=lambda row: (row["left_candidate_id"], row["right_candidate_id"]))


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _attempt_values(report, species):
    """Return finite coefficients keyed by the exact observation/start identity."""
    values, missing, seen = {}, [], set()
    for row in report["attempts"]:
        if not isinstance(row, dict) or not isinstance(row.get("scan_id"), str) or not isinstance(row.get("start_id"), str):
            raise ValueError("attempt identity is invalid")
        key = (row["scan_id"], row["start_id"])
        if not all(key) or key in seen:
            raise ValueError("duplicate or empty observation/start identity")
        seen.add(key)
        if row.get("status") != "OK":
            missing.append({"observation_id": key[0], "start_id": key[1], "reason": "FIT_NOT_SUCCESSFUL"})
            continue
        coeffs = row.get("coeffs")
        value = _finite(coeffs.get(species)) if isinstance(coeffs, dict) else None
        if value is None:
            missing.append({"observation_id": key[0], "start_id": key[1], "reason": "COEFFICIENT_UNAVAILABLE"})
        else:
            values[key] = value
    return values, missing


def compare_multispecies_attempts(candidate_reports, requested_species):
    """Compute fit evidence for every requested species, without a pass threshold.

    Reports are outputs of one controlled-start fit run per candidate.  Deltas
    are paired only on identical observation/start identities, so ordinary
    temporal concentration changes never become an instability penalty.
    """
    if not isinstance(candidate_reports, list) or len(candidate_reports) < 1:
        raise ValueError("candidate_reports must be a non-empty list")
    if (not isinstance(requested_species, list) or not requested_species
            or any(not isinstance(name, str) or not name for name in requested_species)
            or len(requested_species) != len(set(requested_species))):
        raise ValueError("requested_species must be unique non-empty labels")
    reports = []
    ids = set()
    for report in candidate_reports:
        if not isinstance(report, dict) or not isinstance(report.get("candidate_id"), str):
            raise ValueError("candidate report identity is invalid")
        if report["candidate_id"] in ids or not isinstance(report.get("attempts"), list):
            raise ValueError("candidate reports must have unique identities and attempt lists")
        planned = report.get("planned_attempts")
        if isinstance(planned, bool) or not isinstance(planned, int) or planned < 0:
            raise ValueError("candidate report planned_attempts is invalid")
        ids.add(report["candidate_id"])
        reports.append(report)
    per_candidate, raw = [], {}
    for report in reports:
        successful = sum(isinstance(row, dict) and row.get("status") == "OK" for row in report["attempts"])
        complete = len(report["attempts"]) == report["planned_attempts"] == successful
        species_rows = {}
        for species in requested_species:
            values, missing = _attempt_values(report, species)
            grouped = {}
            for (observation, start), value in values.items():
                grouped.setdefault(observation, []).append({"start_id": start, "coefficient": value})
            starts = []
            for observation in sorted(grouped):
                entries = sorted(grouped[observation], key=lambda item: item["start_id"])
                numbers = [item["coefficient"] for item in entries]
                starts.append({"observation_id": observation, "values": entries,
                               "range": float(max(numbers) - min(numbers)) if len(numbers) > 1 else None,
                               "state": "COMPUTED" if len(numbers) > 1 else "UNAVAILABLE"})
            species_rows[species] = {
                "state": "COMPUTED" if complete and not missing and values else "UNAVAILABLE",
                "attempts": {"planned": report["planned_attempts"], "executed": len(report["attempts"]),
                             "successful_fit": successful, "finite_coefficient": len(values),
                             "coefficient_unavailable": len(missing),
                             "complete": complete},
                "missing": missing, "multi_start": starts,
                "detection": {"state": "UNKNOWN", "reason": "NO_DECLARED_DETECTION_THRESHOLD"},
            }
            raw[(report["candidate_id"], species)] = values
        per_candidate.append({"candidate_id": report["candidate_id"], "species": species_rows})
    comparisons = []
    for left_index, left in enumerate(reports):
        for right in reports[left_index + 1:]:
            species_rows = {}
            for species in requested_species:
                left_values = raw[(left["candidate_id"], species)]
                right_values = raw[(right["candidate_id"], species)]
                common = sorted(set(left_values).intersection(right_values))
                deltas = [{"observation_id": key[0], "start_id": key[1],
                           "delta": float(right_values[key] - left_values[key])} for key in common]
                values = [row["delta"] for row in deltas]
                species_rows[species] = {
                    "state": "COMPUTED" if values else "UNAVAILABLE",
                    "paired_attempts": len(deltas),
                    "unpaired_attempts": len(set(left_values).symmetric_difference(right_values)),
                    "median_delta": float(np.median(values)) if values else None,
                    "range_delta": float(max(values) - min(values)) if values else None,
                    "deltas": deltas,
                    "criterion": {"state": "UNSET", "reason": "NO_SPECIES_SENSITIVITY_CRITERION"},
                }
            comparisons.append({"left_candidate_id": left["candidate_id"],
                                "right_candidate_id": right["candidate_id"],
                                "species": species_rows,
                                "residual_comparison": {"state": "NOT_APPLICABLE",
                                   "reason": "NO_COMMON_EVALUATION_BAND_OR_NOISE_NORMALIZATION"}})
    return {"schema": "explorer-v2-multispecies-evidence-v1", "state": "COMPUTED",
            "requested_species": list(requested_species), "candidates": per_candidate,
            "comparisons": comparisons,
            "limitations": ["No species sensitivity threshold", "No residual ranking across windows", "No Apply"]}


_NODE_STATES = {"EVALUATED_PASS", "EVALUATED_FAIL", "PRUNED", "UNEVALUATED"}
_EDGE_STATES = {"PASS", "FAIL", "UNAVAILABLE"}


def _candidate_complexity(candidate):
    """Deterministic tie-break only; it is never a scientific score."""
    poly = candidate.get("poly")
    width = candidate.get("px_max", 0) - candidate.get("px_min", 0)
    return (poly if isinstance(poly, int) and not isinstance(poly, bool) else 10 ** 9,
            width if isinstance(width, int) else 10 ** 9, candidate["candidate_id"])


def _edge_state(row, requested_species):
    if not isinstance(row, dict):
        raise ValueError("edge evidence must be an object")
    species = row.get("species")
    if species is None:
        state = row.get("state")
        if state not in _EDGE_STATES:
            raise ValueError("edge evidence state is invalid")
        return state
    if not isinstance(species, dict) or set(species) != set(requested_species):
        raise ValueError("edge evidence must cover exactly requested_species")
    states = []
    for name in requested_species:
        state = species[name].get("state") if isinstance(species[name], dict) else None
        if state not in _EDGE_STATES:
            raise ValueError("species edge evidence state is invalid")
        states.append(state)
    return "FAIL" if "FAIL" in states else "PASS" if all(state == "PASS" for state in states) else "UNAVAILABLE"


def evaluate_candidate_graph(plan, candidate_states, edge_evidence, *, used_fit_attempts=0, pair_evidence=None):
    """Evaluate only declared candidate edges and schedule finite closure work.

    ``edge_evidence`` contains upstream science judgments; this function does
    not convert coefficient deltas into PASS/FAIL.  Unknown frontier nodes are
    queued within the declared budget, never treated as failed boundaries.
    """
    if not isinstance(plan, dict) or not isinstance(plan.get("candidates"), list):
        raise ValueError("plan candidates are required")
    requested = plan.get("requested_species")
    if not isinstance(requested, list) or not requested or len(requested) != len(set(requested)):
        raise ValueError("plan requested_species is invalid")
    candidates = {row.get("candidate_id"): row for row in plan["candidates"]
                  if isinstance(row, dict) and isinstance(row.get("candidate_id"), str)}
    if len(candidates) != len(plan["candidates"]):
        raise ValueError("plan candidate identity is invalid")
    if not isinstance(candidate_states, dict) or set(candidate_states) != set(candidates):
        raise ValueError("candidate_states must cover exactly plan candidates")
    if any(state not in _NODE_STATES for state in candidate_states.values()):
        raise ValueError("candidate state is invalid")
    if isinstance(used_fit_attempts, bool) or not isinstance(used_fit_attempts, int) or used_fit_attempts < 0:
        raise ValueError("used_fit_attempts is invalid")
    budget = plan.get("budget")
    if not isinstance(budget, dict) or not isinstance(budget.get("max_fit_attempts"), int) \
            or not isinstance(budget.get("closure_max_attempts"), int):
        raise ValueError("plan budget is invalid")
    edges, edge_keys = [], set()
    for edge in plan.get("edges", []):
        if not isinstance(edge, dict) or set(edge) != {"left_candidate_id", "right_candidate_id", "kind"} \
                or not isinstance(edge["kind"], str) or not edge["kind"]:
            raise ValueError("plan edge is invalid")
        left, right = edge["left_candidate_id"], edge["right_candidate_id"]
        if left not in candidates or right not in candidates or left == right:
            raise ValueError("plan edge endpoints are invalid")
        key = tuple(sorted((left, right)))
        if key in edge_keys:
            raise ValueError("plan edges must be unique")
        edge_keys.add(key); edges.append((key, edge["kind"]))
    evidence = {}
    if not isinstance(edge_evidence, list):
        raise ValueError("edge_evidence must be a list")
    for row in edge_evidence:
        if not isinstance(row, dict):
            raise ValueError("edge evidence is invalid")
        left, right = row.get("left_candidate_id"), row.get("right_candidate_id")
        key = tuple(sorted((left, right))) if isinstance(left, str) and isinstance(right, str) else None
        if key not in edge_keys or key in evidence:
            raise ValueError("edge evidence must match one declared edge")
        evidence[key] = _edge_state(row, requested)
    pair_states_by_key = dict(evidence)
    if pair_evidence is not None:
        if not isinstance(pair_evidence, list):
            raise ValueError("pair_evidence must be a list")
        seen_pairs = set()
        for row in pair_evidence:
            if not isinstance(row, dict):
                raise ValueError("pair evidence must be an object")
            left, right = row.get("left_candidate_id"), row.get("right_candidate_id")
            if left not in candidates or right not in candidates or left == right:
                raise ValueError("pair evidence endpoints are invalid")
            key = tuple(sorted((left, right)))
            state = _edge_state(row, requested)
            if key in seen_pairs or (key in evidence and evidence[key] != state):
                raise ValueError("duplicate or conflicting pair evidence")
            seen_pairs.add(key)
            pair_states_by_key[key] = state
    adjacency = {candidate_id: [] for candidate_id in candidates}
    for (left, right), kind in edges:
        state = evidence.get((left, right), "UNAVAILABLE")
        adjacency[left].append((right, state, kind)); adjacency[right].append((left, state, kind))
    components, unseen = [], {candidate_id for candidate_id, state in candidate_states.items()
                               if state == "EVALUATED_PASS"}
    while unseen:
        start, stack, members = min(unseen), [min(unseen)], set()
        while stack:
            node = stack.pop()
            if node in members:
                continue
            members.add(node); unseen.discard(node)
            stack.extend(neighbor for neighbor, state, _kind in adjacency[node]
                         if state == "PASS" and candidate_states[neighbor] == "EVALUATED_PASS")
        components.append(sorted(members))
    remaining = max(0, budget["max_fit_attempts"] - used_fit_attempts)
    closure_cap = min(budget["closure_max_attempts"], remaining)
    component_rows, scheduled, scheduled_cost = [], [], 0
    for members in components:
        member_set = set(members)
        unknown = sorted({neighbor for node in members for neighbor, _state, _kind in adjacency[node]
                          if neighbor not in member_set and candidate_states[neighbor] == "UNEVALUATED"})
        unresolved_edges = any((state == "UNAVAILABLE" and candidate_states[neighbor] == "EVALUATED_PASS")
                               or candidate_states[neighbor] == "PRUNED"
                               for node in members for neighbor, state, _kind in adjacency[node])
        boundary = {node for node in members for neighbor, state, _kind in adjacency[node]
                    if neighbor not in member_set and (candidate_states[neighbor] == "EVALUATED_FAIL" or state == "FAIL")}
        distances = {}
        if boundary:
            for node in members:
                frontier, visited, hops = [(node, 0)], {node}, None
                while frontier:
                    current, distance = frontier.pop(0)
                    if current in boundary:
                        hops = distance; break
                    for neighbor, state, _kind in adjacency[current]:
                        if neighbor in member_set and state == "PASS" and neighbor not in visited:
                            visited.add(neighbor); frontier.append((neighbor, distance + 1))
                distances[node] = hops
        else:
            distances = {node: None for node in members}
        best_distance = max((value for value in distances.values() if value is not None), default=None)
        interior = members if best_distance is None else [node for node in members if distances[node] == best_distance]
        representative = min(interior, key=lambda node: _candidate_complexity(candidates[node]))
        direct_states = []
        for node in members:
            if node == representative:
                continue
            direct_states.append(pair_states_by_key.get(tuple(sorted((representative, node))), "UNAVAILABLE"))
        representative_check = "FAIL" if "FAIL" in direct_states else (
            "PASS" if all(state == "PASS" for state in direct_states) else "UNAVAILABLE")
        pair_states = [pair_states_by_key.get(tuple(sorted((left, right))), "UNAVAILABLE")
                       for index, left in enumerate(members) for right in members[index + 1:]]
        component_check = "FAIL" if "FAIL" in pair_states else (
            "PASS" if all(state == "PASS" for state in pair_states) else "UNAVAILABLE")
        local_schedule = []
        for node in unknown:
            cost = candidates[node].get("planned_fit_attempts")
            if cost is not None and (type(cost) is not int or cost <= 0):
                raise ValueError("planned_fit_attempts must be a positive integer")
            if node not in scheduled and cost is not None and scheduled_cost + cost <= closure_cap:
                local_schedule.append(node)
                scheduled_cost += cost
        scheduled.extend(local_schedule)
        state = ("ISOLATED_NO_ROBUSTNESS_EVIDENCE" if len(members) == 1 else
                 "INCONSISTENT_COMPONENT" if component_check == "FAIL" else
                 "OPEN_FRONTIER" if unknown or unresolved_edges else
                 "INSUFFICIENT_COMPONENT_EVIDENCE" if component_check == "UNAVAILABLE" else
                 "CLOSED_INTERNAL_COMPONENT")
        component_rows.append({"members": members, "state": state, "representative_candidate_id": representative,
                               "representative_boundary_hops": distances[representative],
                               "representative_component_check": representative_check,
                               "component_pair_check": component_check,
                               "unknown_frontier": unknown, "closure_scheduled": local_schedule})
    all_frontier = {node for row in component_rows for node in row["unknown_frontier"]}
    return {"schema": "explorer-v2-graph-closure-v1", "state": "COMPUTED",
            "components": component_rows,
            "node_states": dict(candidate_states),
            "edge_states": [{"left_candidate_id": left, "right_candidate_id": right,
                             "kind": kind, "state": evidence.get((left, right), "UNAVAILABLE")}
                            for (left, right), kind in edges],
            "closure": {"requested_candidate_ids": scheduled, "remaining_fit_budget": remaining,
                        "scheduled_fit_attempts": scheduled_cost,
                        "closure_capacity": closure_cap,
                        "unscheduled_frontier_count": len(all_frontier.difference(scheduled))},
            "limitations": ["No recommendation", "No automatic domain expansion", "No Apply"]}


def _assessment(value, requested_species):
    if not isinstance(value, dict) or set(value) != {"internal_state", "numerical_state", "species"}:
        raise ValueError("candidate assessment fields are invalid")
    if value["internal_state"] not in _EDGE_STATES or value["numerical_state"] not in {
            "IDENTIFIED", "MULTIPLE_SOLUTIONS", "UNAVAILABLE"}:
        raise ValueError("candidate assessment state is invalid")
    if not isinstance(value["species"], dict) or set(value["species"]) != set(requested_species) \
            or any(state not in _EDGE_STATES for state in value["species"].values()):
        raise ValueError("candidate assessment species states are invalid")
    return value


def build_recommendation(plan, graph, candidate_assessments, holdout=None, external_validation=None):
    """Turn frozen internal/holdout evidence into an explicit V2 status.

    This accepts upstream assessment states; it deliberately contains no hidden
    numerical tolerance.  Missing holdout evidence can produce PROVISIONAL but
    never MISSION_RECOMMENDED.
    """
    # The current API receives caller-supplied verdicts, not bound execution
    # evidence.  Keep it diagnostic until the runtime validates observations,
    # criteria, frozen candidate identity and holdout use history end to end.
    if not isinstance(plan, dict) or not isinstance(plan.get("plan_hash"), str):
        raise ValueError("frozen plan_hash is required")
    requested, split = plan.get("requested_species"), plan.get("split")
    candidate_ids = {row.get("candidate_id") for row in plan.get("candidates", []) if isinstance(row, dict)}
    if not requested or not isinstance(split, dict) or not candidate_ids:
        raise ValueError("plan recommendation inputs are invalid")
    if not isinstance(candidate_assessments, dict) or set(candidate_assessments) != candidate_ids:
        raise ValueError("candidate assessments must cover exactly plan candidates")
    assessments = {key: _assessment(value, requested) for key, value in candidate_assessments.items()}
    if not isinstance(graph, dict) or graph.get("schema") != "explorer-v2-graph-closure-v1":
        raise ValueError("graph closure evidence is invalid")
    closed = [row for row in graph.get("components", []) if isinstance(row, dict)
              and row.get("state") == "CLOSED_INTERNAL_COMPONENT"
              and row.get("representative_candidate_id") in candidate_ids]
    declared_holdout = set(split.get("holdout", []))
    discovery = set(split.get("discovery", [])).union(split.get("validation", []))
    if declared_holdout.intersection(discovery):
        raise ValueError("plan holdout overlaps discovery/validation")
    holdout_states = {}
    holdout_state = "UNAVAILABLE"
    if holdout is not None:
        if not isinstance(holdout, dict) or set(holdout) != {"observation_ids", "candidate_states"}:
            raise ValueError("holdout fields are invalid")
        observed = set(holdout["observation_ids"])
        if (not isinstance(holdout["observation_ids"], list) or observed != declared_holdout
                or observed.intersection(discovery) or not isinstance(holdout["candidate_states"], dict)):
            raise ValueError("holdout observations are not independent of discovery")
        holdout_states = holdout["candidate_states"]
        if any(key not in candidate_ids or state not in _EDGE_STATES for key, state in holdout_states.items()):
            raise ValueError("holdout candidate state is invalid")
        holdout_state = "AVAILABLE" if declared_holdout else "UNAVAILABLE"
    if external_validation is not None and not isinstance(external_validation, dict):
        raise ValueError("external_validation must be an object when supplied")
    eligible, alternatives, reasons = [], [], []
    for component in closed:
        candidate_id = component["representative_candidate_id"]
        assessment = assessments[candidate_id]
        internal_ok = (assessment["internal_state"] == "PASS"
                       and assessment["numerical_state"] == "IDENTIFIED"
                       and all(state == "PASS" for state in assessment["species"].values()))
        if not internal_ok:
            alternatives.append(candidate_id); reasons.append({"candidate_id": candidate_id,
                "reason": "INTERNAL_OR_SPECIES_EVIDENCE_NOT_PASSED"})
            continue
        if holdout_state == "AVAILABLE" and holdout_states.get(candidate_id) == "PASS":
            eligible.append((candidate_id, "MISSION_RECOMMENDED"))
        elif holdout_state == "UNAVAILABLE":
            eligible.append((candidate_id, "PROVISIONAL"))
        else:
            alternatives.append(candidate_id); reasons.append({"candidate_id": candidate_id,
                "reason": "HOLDOUT_NOT_PASSED_OR_UNAVAILABLE"})
    if eligible:
        candidate_id, status = sorted(eligible)[0]
    else:
        candidate_id, status = None, "ABSTAIN"
    diagnostic_status = status
    candidate_id, status = None, "ABSTAIN"
    reasons.append({"reason": "V2_EXECUTION_EVIDENCE_NOT_VERIFIED"})
    species_results = (assessments[candidate_id]["species"] if candidate_id else
                       {name: "UNAVAILABLE" for name in requested})
    return {"schema": "explorer-recommendation-v2", "plan_hash": plan["plan_hash"],
            "input_hash": plan.get("input_hash"), "status": status,
            "diagnostic_status_from_supplied_verdicts": diagnostic_status,
            "scope": "MISSION_LOCAL_FROZEN_PLAN_ONLY", "requested_species": list(requested),
            "candidate_id": candidate_id, "exportable_candidate_ids": [candidate_id] if candidate_id else [],
            "candidate_refs": sorted(candidate_ids), "species_results": species_results,
            "checks": {"internal_graph": "AVAILABLE", "holdout": holdout_state,
                       "external_validation": "AVAILABLE" if external_validation is not None else "UNAVAILABLE"},
            "frontier": graph.get("closure"), "holdout": holdout, "external_validation": external_validation,
            "code_provenance": {"state": "UNAVAILABLE", "reason": "CALLER_MUST_ATTACH_EXECUTION_PROVENANCE"},
            "alternatives": alternatives, "reasons": reasons,
            "limitations": ["External validation does not change status", "Manual export only", "No Apply"]}


def export_recommended_fitset(base_config, candidate, recommendation, output_path):
    """Reject export until V2 execution evidence is bound to the actual config.

    The former implementation checked names only and could export a changed
    candidate, missing references and an unspecified gas-sign policy.
    """
    raise ValueError("V2 export unavailable: execution/config binding is not implemented")
