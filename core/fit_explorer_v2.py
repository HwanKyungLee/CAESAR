"""Pure mission-to-plan contract for Fit Setting Explorer V2.

No FitSet, fit, ranking, or hidden species/channel policy is required here.
The caller supplies an explicit finite search policy; this module freezes it
against validated mission inputs for later execution.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np


MISSION_SCHEMA = "explorer-mission-v2"
PLAN_SCHEMA = "explorer-plan-v2"
_ILS_STATES = {"ALREADY_CONVOLVED", "NEEDS_RUNTIME_CONVOLUTION"}


def _canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _array(value, label):
    try:
        array = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a finite numeric vector") from None
    if array.size < 2 or not np.isfinite(array).all():
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
            if not isinstance(row, dict) or set(row) != {"observation_id", "content_hash"}:
                raise ValueError("alpha input identity is invalid")
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
            if not isinstance(ref["cross_section_unit"], str) or not ref["cross_section_unit"].strip():
                raise ValueError("reference cross_section_unit is required")
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
                           "alpha_hashes": [row["content_hash"] for row in alpha],
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
    if not isinstance(policy, dict) or set(policy) != {
            "windows_nm", "poly_degrees", "registration_policies", "split", "budget"}:
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
    return {"windows_nm": normalized_windows, "poly_degrees": list(polys),
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
    drivers = {row["driver_species"] for row in policy["registration_policies"]}
    if any(not drivers.issubset({ref["species_id"] for ref in channel["references"]})
           for channel in normalized["channels"]):
        raise ValueError("registration driver is absent from a mission channel")
    input_hash = _canonical_hash({"mission_id": normalized["mission_id"],
                                  "channels": [{"channel_id": ch["channel_id"],
                                                "wave_nm": ch["wave_nm"].tolist(),
                                                "alpha_hashes": ch["alpha_hashes"],
                                                "references": ch["references"]}
                                               for ch in normalized["channels"]],
                                  "requested_species": normalized["requested_species"]})
    channels, candidates = [], []
    for channel in normalized["channels"]:
        common_lo = max([float(channel["wave_nm"][0])] + [ref["coverage_nm"][0] for ref in channel["references"]])
        common_hi = min([float(channel["wave_nm"][-1])] + [ref["coverage_nm"][1] for ref in channel["references"]])
        channel_candidates = []
        for window in policy["windows_nm"]:
            if window[0] < common_lo or window[1] > common_hi:
                continue
            lo = int(np.searchsorted(channel["wave_nm"], window[0], side="left"))
            hi = int(np.searchsorted(channel["wave_nm"], window[1], side="right")) - 1
            for poly in policy["poly_degrees"]:
                if hi - lo + 1 <= poly + len(channel["references"]):
                    continue
                for registration in policy["registration_policies"]:
                    identity = {"input_hash": input_hash, "channel_id": channel["channel_id"],
                                "px": [lo, hi], "poly": poly,
                                "references": channel["references"], "registration": registration}
                    candidate = {"candidate_id": "v2_" + _canonical_hash(identity)[:20],
                                 "channel_id": channel["channel_id"], "px_min": lo, "px_max": hi,
                                 "window_nm": [float(channel["wave_nm"][lo]), float(channel["wave_nm"][hi])],
                                 "poly": poly, "references": channel["references"],
                                 "registration": registration, "identity": identity,
                                 "runtime_spec": {"f_min": lo, "f_max": hi, "poly_deg": poly,
                                                  "reference_order": [ref["species_id"] for ref in channel["references"]],
                                                  "wavecal_hash": _canonical_hash(channel["wave_nm"].tolist())}}
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
            "candidates": candidates, "edges": [], "split": policy["split"], "budget": policy["budget"],
            "criteria": {"state": "UNSET", "reason": "SPECIES_SENSITIVITY_CRITERIA_NOT_DECLARED"},
            "assumptions": ["FINITE_EXPLICIT_SEARCH_POLICY", "NO_FIT_EXECUTED", "NO_APPLY",
                            "GRAPH_EDGES_DEFERRED_TO_CARD4"]}
    plan["plan_hash"] = _canonical_hash(plan)
    return plan


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _attempt_values(report, species):
    """Return finite coefficients keyed by the exact observation/start identity."""
    values, missing = {}, []
    for row in report["attempts"]:
        if not isinstance(row, dict) or not isinstance(row.get("scan_id"), str) or not isinstance(row.get("start_id"), str):
            raise ValueError("attempt identity is invalid")
        key = (row["scan_id"], row["start_id"])
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
                               "range": float(max(numbers) - min(numbers)),
                               "state": "COMPUTED"})
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
