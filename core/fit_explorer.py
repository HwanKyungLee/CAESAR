"""Minimal Fit Setting Explorer contracts (no ranking, plateau, or Apply)."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import time
from datetime import date, datetime, timedelta

import numpy as np

from core import fit_physics as FP
from core import param_optimizer as PO


SCHEMA_VERSION = 1
STAGE1_SAMPLE_CONTRACT = "stage1-representative-rows-v1"
STAGE1_EXPECTED_ATTEMPTS = 8
STAGE1_VERTICAL_SLICE_SCHEMA = "stage1-one-candidate-v1"
STAGE1_SOLVER_STATUSES = {"CONVERGED", "MAX_NFEV", "FAILED", "TERMINATED"}
STAGE2_SAMPLE_CONTRACT = "stage2-date-distributed-rows-v1"


def canonical_channel_label(value):
    """Normalize one of the three supported alpha channel labels.

    Unknown labels are rejected instead of being returned unchanged.  This
    keeps Stage 2 fail-closed even when an unknown value is supplied for both
    the expected and record channel (which would otherwise compare equal).
    """
    if not isinstance(value, str):
        raise ValueError("channel label must be a string")
    normalized = {"cold": "cold", "ans": "ANs", "pns": "PNs"}.get(
        value.strip().casefold())
    if normalized is None:
        raise ValueError("unsupported channel label")
    return normalized
STAGE2_VERTICAL_SLICE_SCHEMA = "stage2-one-candidate-v1"
ZERO_BASE_CANDIDATE_SCHEMA = "zero-base-candidates-v1"
SEED_STABILITY_TOLERANCES = {
    "conc_abs_ppb": 0.1, "conc_rel": 0.05, "shift_abs_px": 0.01,
    "squeeze_abs": 1e-5, "rms_sig_rel": 0.01,
}


def validate_reference_policy(cfg):
    """Validate optional window-specific reference policy without changing refs.

    The ordered ``cfg['refs']`` list remains authoritative.  A policy may
    document an intentional exclusion, but it must not silently add/remove a
    reference or contradict the actual FitSet.
    """
    policy = cfg.get("reference_policy")
    if policy is None:
        return None
    if not isinstance(policy, dict):
        raise ValueError("reference_policy must be an object")
    mode = policy.get("mode")
    excluded = policy.get("excluded_species", [])
    if mode != "EXPLICIT_FITSET_ORDER" or not isinstance(excluded, list):
        raise ValueError("reference_policy has unsupported mode or exclusions")
    if any(not isinstance(name, str) or not name for name in excluded):
        raise ValueError("reference_policy excluded_species must contain names")
    refs = cfg.get("refs", [])
    if not isinstance(refs, list) or any(not isinstance(ref, dict) for ref in refs):
        raise ValueError("FitSet refs must be a list of objects")
    names = [ref.get("name") for ref in refs]
    if len(names) != len(set(names)) or any(not isinstance(name, str) or not name for name in names):
        raise ValueError("FitSet refs must be an ordered list of unique names")
    contradiction = sorted(set(excluded).intersection(names))
    if contradiction:
        raise ValueError("reference_policy contradicts FitSet refs: " + ", ".join(contradiction))
    if not policy.get("reason"):
        raise ValueError("reference_policy reason is required")
    return {"mode": mode, "excluded_species": list(excluded),
            "reason": str(policy["reason"]),
            "evidence": policy.get("evidence"),
            "t2_o4_state": policy.get("t2_o4_state")}


def representative_indices(pool_size, requested=4):
    """Evenly spaced zero-based indices, including both endpoints."""
    if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer))
           for value in (pool_size, requested)):
        raise ValueError("representative sample sizes must be exact non-bool integers")
    pool_size, requested = int(pool_size), int(requested)
    if requested < 2 or pool_size < requested:
        raise ValueError(f"eligible alpha rows {pool_size} < requested {requested}")
    indices = [i * (pool_size - 1) // (requested - 1) for i in range(requested)]
    if len(set(indices)) != requested:
        raise ValueError("representative row selection produced duplicate indices")
    return indices


def select_representative_rows(rows, requested=4):
    """Sort row identities deterministically, then select even-spaced endpoints."""
    keyed, physical = [], set()
    for row in rows:
        path, row_idx = row
        if isinstance(row_idx, bool) or not isinstance(row_idx, (int, np.integer)) or row_idx < 0:
            raise ValueError("alpha row identity is invalid")
        canonical = os.path.normcase(os.path.realpath(path)).replace("\\", "/")
        try:
            stat = os.stat(path)
        except OSError as exc:
            raise ValueError("alpha row identity cannot be resolved") from exc
        file_identity = (("stat", int(stat.st_dev), int(stat.st_ino))
                         if stat.st_ino else ("realpath", canonical))
        physical_key = (file_identity, int(row_idx))
        if physical_key in physical:
            raise ValueError("alpha row identities alias the same physical file")
        physical.add(physical_key)
        key = (canonical, int(row_idx))
        keyed.append((key, (path, int(row_idx))))
    keyed.sort(key=lambda item: item[0])
    keys = [item[0] for item in keyed]
    if len(keys) != len(set(keys)):
        raise ValueError("alpha row identities are not unique")
    indices = representative_indices(len(keyed), requested)
    return [keyed[i][1] for i in indices], indices


def select_stage2_rows(records, date_from, date_to, expected_channel, requested=12):
    """Select an exact date-ordered Stage 2 sample with explicit provenance."""
    if requested != 12 or not isinstance(expected_channel, str) or not expected_channel:
        raise ValueError("Stage 2 requires exactly 12 scans and an explicit channel")
    try:
        first, last = date.fromisoformat(date_from), date.fromisoformat(date_to)
    except (TypeError, ValueError) as exc:
        raise ValueError("Stage 2 requires an explicit ISO date range") from exc
    if last < first:
        raise ValueError("Stage 2 date range is reversed")
    all_dates = [(first + timedelta(days=offset)).isoformat()
                 for offset in range((last - first).days + 1)]
    keyed, physical = [], set()
    observation_keys, timestamps = set(), set()
    for record in records:
        required = {"path", "row_index", "date", "timestamp", "observation_key",
                    "time_source", "channel", "channel_source"}
        if not isinstance(record, dict) or set(record) != required:
            raise ValueError("Stage 2 row metadata is incomplete or ambiguous")
        if (canonical_channel_label(record["channel"])
                != canonical_channel_label(expected_channel)
                or record["channel_source"] != "alpha_header_label"):
            raise ValueError("Stage 2 row channel does not match the requested channel")
        try:
            day = date.fromisoformat(record["date"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Stage 2 row date is missing or ambiguous") from exc
        if day < first or day > last:
            raise ValueError("Stage 2 row lies outside the explicit date range")
        if not isinstance(record["timestamp"], str) or not record["timestamp"] \
                or record["observation_key"] != record["timestamp"]:
            raise ValueError("Stage 2 observation identity is missing or ambiguous")
        try:
            timestamp = datetime.fromisoformat(record["timestamp"])
        except ValueError as exc:
            raise ValueError("Stage 2 timestamp is invalid") from exc
        if timestamp.date() != day:
            raise ValueError("Stage 2 timestamp and date disagree")
        if record["time_source"] not in {
                "alpha_header_datetime", "alpha_header_doy_with_filename_year"}:
            raise ValueError("Stage 2 timestamp source is unavailable")
        row_index = record["row_index"]
        if isinstance(row_index, bool) or not isinstance(row_index, (int, np.integer)) \
                or row_index < 0:
            raise ValueError("Stage 2 row identity is invalid")
        canonical = os.path.normcase(os.path.realpath(record["path"])).replace("\\", "/")
        try:
            stat = os.stat(record["path"])
        except OSError as exc:
            raise ValueError("Stage 2 row identity cannot be resolved") from exc
        file_identity = (("stat", int(stat.st_dev), int(stat.st_ino))
                         if stat.st_ino else ("realpath", canonical))
        physical_key = (file_identity, int(row_index))
        if physical_key in physical:
            raise ValueError("Stage 2 rows alias the same physical file")
        physical.add(physical_key)
        if record["observation_key"] in observation_keys \
                or record["timestamp"] in timestamps:
            raise ValueError("Stage 2 observation identity is duplicated")
        observation_keys.add(record["observation_key"])
        timestamps.add(record["timestamp"])
        keyed.append(((day, record["timestamp"], canonical, int(row_index)),
                      (record["path"], int(row_index)), record))
    keyed.sort(key=lambda item: item[0])
    if len(keyed) < requested:
        raise ValueError(f"eligible alpha rows {len(keyed)} < requested {requested}")
    buckets = {}
    for item in keyed:
        buckets.setdefault(item[2]["date"], []).append(item)
    if len(buckets) < 4:
        raise ValueError("Stage 2 requires at least four distinct dates")
    if sum(min(3, len(bucket)) for bucket in buckets.values()) < requested:
        raise ValueError("Stage 2 date cap leaves fewer than 12 eligible rows")
    allocated = {day: 0 for day in buckets}
    while sum(allocated.values()) < requested:
        available = [day for day in sorted(buckets)
                     if allocated[day] < min(3, len(buckets[day]))]
        remaining = requested - sum(allocated.values())
        chosen = (available if len(available) <= remaining else
                  [available[(len(available) - 1) // 2]] if remaining == 1 else
                  [available[index] for index in representative_indices(
                      len(available), remaining)])
        for day in chosen:
            allocated[day] += 1
    picked = []
    for day, count in allocated.items():
        if not count:
            continue
        bucket = buckets[day]
        local_indices = ([(len(bucket) - 1) // 2] if count == 1 else
                         representative_indices(len(bucket), count))
        picked.extend(bucket[index] for index in local_indices)
    picked.sort(key=lambda item: item[0])
    keyed_positions = {item[0]: index for index, item in enumerate(keyed)}
    indices = [keyed_positions[item[0]] for item in picked]
    selected = [item[1] for item in picked]
    hash_cache = {}
    for item in picked:
        if item[1][0] not in hash_cache:
            hash_cache[item[1][0]] = sha256_file(item[1][0])
    samples = [{"id": (os.path.basename(item[1][0]) + "#sha256="
                       + hash_cache[item[1][0]][:12] + f"#row={item[1][1]}"),
                "file": os.path.basename(item[1][0]),
                "sha256": hash_cache[item[1][0]], "row_index": item[1][1],
                "date": item[2]["date"], "timestamp": item[2]["timestamp"],
                "time_source": item[2]["time_source"],
                "observation_key": item[2]["observation_key"],
                "channel": canonical_channel_label(expected_channel),
                "channel_source": item[2]["channel_source"]} for item in picked]
    per_date = {day: sum(sample["date"] == day for sample in samples)
                for day in all_dates}
    eligible_per_date = {day: len(buckets.get(day, [])) for day in all_dates}
    return selected, {"contract": STAGE2_SAMPLE_CONTRACT,
                      "requested_scans": 12, "eligible_rows": len(keyed),
                      "selected_zero_based_indices": indices,
                      "date_range": [date_from, date_to],
                      "expected_channel": canonical_channel_label(expected_channel),
                      "channel_source": "alpha_header_label",
                      "minimum_distinct_dates": 4,
                      "eligible_per_date": eligible_per_date,
                      "selected_per_date": per_date,
                      "state_stratification": "NOT_AVAILABLE_NOT_STRATIFIED",
                      "independence_note": ("Rows within one file/date are repeated observations, "
                                            "not independent date replicates"),
                      "samples": samples}


def stage1_budget(candidates, selected_scans, starts):
    if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer))
           for value in (selected_scans, starts)):
        raise ValueError("Stage 1 sample budget requires exact non-bool integers")
    if selected_scans != 4 or starts != 2:
        raise ValueError("Stage 1 sample budget requires exactly 4 scans and 2 starts")
    counts = {state: sum(c["stage0_preflight"]["state"] == state for c in candidates)
              for state in ("PASS", "FAIL", "UNAVAILABLE")}
    attempts = int(selected_scans) * int(starts)
    return {"contract": STAGE1_SAMPLE_CONTRACT, "requested_scans": 4,
            "selected_scans": int(selected_scans), "starts_per_candidate": int(starts),
            "attempts_per_candidate": attempts, "stage0": counts,
            "planned_fit_attempts": counts["PASS"] * attempts,
            "executed_fit_attempts": sum(c["execution_gate"]["n_ok"] +
                                         c["execution_gate"]["n_fail"] for c in candidates)}


def neighboring_candidates(px_min, px_max, poly, pixel_step):
    """Exactly three translated windows x three adjacent polynomial orders."""
    px_min, px_max, poly, pixel_step = map(int, (px_min, px_max, poly, pixel_step))
    if px_max - px_min < 50 or pixel_step < 1:
        raise ValueError("baseline window must be >=50 px and pixel_step >=1")
    polys = [poly - 1, poly, poly + 1]
    if min(polys) < 0 or len(set(polys)) != 3:
        raise ValueError("baseline poly must have three distinct nonnegative neighbors")
    windows = [(px_min + d, px_max + d) for d in (-pixel_step, 0, pixel_step)]
    return [dict(id=f"w{wi}_p{p}", px_min=lo, px_max=hi, poly=p)
            for wi, (lo, hi) in enumerate(windows) for p in polys]


def zero_base_policy_candidates(cfg, wave_axis, target="NO2", window_offsets_nm=(-1.0, 0.0, 1.0)):
    """Generate the deliberately small, explicit zero-base Stage 0 grid.

    This describes policies; it does not run a fit and never changes ``refs``.
    The FitSet's existing window/poly are the baseline geometry.  Window offsets
    are converted to inclusive pixel offsets using the median wavelength spacing.
    """
    wave = np.asarray(wave_axis, dtype=float).reshape(-1)
    if wave.size < 2 or not np.isfinite(wave).all() or not np.all(np.diff(wave) > 0):
        raise ValueError("wave axis must be finite and strictly increasing")
    try:
        base_lo, base_hi = int(cfg["f_min"]), int(cfg["f_max"])
        base_poly = int(cfg["poly_deg"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("FitSet baseline window/poly is invalid") from None
    if any(isinstance(v, bool) for v in (base_lo, base_hi, base_poly)):
        raise ValueError("FitSet baseline window/poly is invalid")
    if base_lo < 0 or base_hi <= base_lo or base_hi >= wave.size or base_poly < 1:
        raise ValueError("FitSet baseline window/poly is invalid")
    spacing = float(np.median(np.diff(wave[base_lo:base_hi + 1])))
    if not np.isfinite(spacing) or spacing <= 0:
        raise ValueError("wavelength spacing unavailable")
    offsets = tuple(float(x) for x in window_offsets_nm)
    if len(offsets) != 3 or len(set(offsets)) != 3 or not all(np.isfinite(offsets)):
        raise ValueError("window offsets must be three finite unique values")
    deltas = tuple(int(round(x / spacing)) for x in offsets)
    if len(set(deltas)) != len(deltas):
        raise ValueError("window offsets collapse to duplicate pixel deltas")
    shift_policies = (
        {"mode": "Fix", "value": -5.0}, {"mode": "Fix", "value": -2.0},
        {"mode": "Fix", "value": -0.5}, {"mode": "Fix", "value": 0.0},
        {"mode": "Limit", "lower": -1.0, "upper": 1.0},
        {"mode": "Limit", "lower": -5.0, "upper": 5.0},
        {"mode": "Limit", "lower": -3.5, "upper": 1.5},
        {"mode": "Limit", "lower": -10.0, "upper": 0.5},
    )
    squeeze_policies = (
        {"mode": "Fix", "value": 1.0},
        {"mode": "Limit", "lower": 0.9999, "upper": 1.0001},
        {"mode": "Limit", "lower": 0.9995, "upper": 1.0005},
        {"mode": "Limit", "lower": 0.995, "upper": 1.005},
        {"mode": "Limit", "lower": 0.98, "upper": 1.02},
    )
    for policy in shift_policies:
        if policy["mode"] == "Fix" and not np.isfinite(policy["value"]):
            raise ValueError("invalid fixed shift policy")
        if policy["mode"] == "Limit":
            _worker_shift_interval(policy["lower"], policy["upper"], "candidate shift")
    for policy in squeeze_policies:
        if policy["mode"] == "Fix" and (not np.isfinite(policy["value"])
                                         or policy["value"] <= 0):
            raise ValueError("invalid fixed squeeze policy")
        if policy["mode"] == "Limit":
            _strict_interval(policy["lower"], policy["upper"], "candidate squeeze")
    rows = []
    for offset_nm, delta in zip(offsets, deltas):
        lo, hi = base_lo + delta, base_hi + delta
        for poly in (base_poly - 1, base_poly, base_poly + 1):
            if poly < 0 or hi < lo or hi >= wave.size or lo < 0:
                continue
            for shift in shift_policies:
                for squeeze in squeeze_policies:
                    policy = {"shift": shift, "squeeze": squeeze}
                    digest = hashlib.sha256(json.dumps(
                        {"window": [lo, hi], "poly": poly, "policy": policy,
                         "target": target}, sort_keys=True, separators=(",", ":")
                    ).encode()).hexdigest()[:16]
                    rows.append({"id": f"zb_{digest}", "px_min": lo, "px_max": hi,
                                 "poly": poly, "window_offset_nm": offset_nm,
                                 "window_offset_px": delta, "target": target,
                                 "policy": policy, "refs_source": "FitSet.cfg.refs",
                                 "policy_stage": "STAGE0_METADATA_ONLY"})
    rows.sort(key=lambda c: c["id"])
    if len({c["id"] for c in rows}) != len(rows):
        raise ValueError("zero-base candidate IDs are not unique")
    return rows


def translate_zero_base_policy(cfg, ref_props, candidate, target="NO2"):
    """Translate one Stage 0 policy into worker-compatible Stage 1 ref props.

    This is a pure translation contract: no fit is run and neither input is
    mutated.  The candidate still carries ``STAGE0_METADATA_ONLY`` because
    translation alone does not make it evaluated Stage 1 evidence.
    """
    if not isinstance(candidate, dict) or candidate.get("policy_stage") != "STAGE0_METADATA_ONLY":
        raise ValueError("candidate must be STAGE0_METADATA_ONLY")
    if not isinstance(candidate.get("id"), str) or not candidate["id"]:
        raise ValueError("candidate id is required")
    if not isinstance(cfg, dict) or not isinstance(ref_props, dict):
        raise ValueError("FitSet cfg/ref_props must be objects")
    refs = cfg.get("refs")
    if not isinstance(refs, list) or any(not isinstance(ref, dict) for ref in refs):
        raise ValueError("FitSet refs must be an ordered list of objects")
    gas_order = [ref.get("name") for ref in refs]
    if (any(not isinstance(name, str) or not name for name in gas_order)
            or len(gas_order) != len(set(gas_order))):
        raise ValueError("FitSet refs must contain unique species names")
    if target not in gas_order or target not in ref_props or not isinstance(ref_props[target], dict):
        raise ValueError("candidate target is absent from FitSet refs/ref_props")
    if candidate.get("target") != target:
        raise ValueError("candidate target does not match requested target")

    policy = candidate.get("policy")
    if not isinstance(policy, dict) or set(policy) != {"shift", "squeeze"}:
        raise ValueError("candidate policy must contain exactly shift and squeeze")

    def parse_axis(axis, *, positive=False):
        spec = policy[axis]
        if not isinstance(spec, dict) or spec.get("mode") not in ("Fix", "Limit"):
            raise ValueError(f"candidate {axis} policy is invalid")
        mode = spec["mode"]
        expected = {"mode", "value"} if mode == "Fix" else {"mode", "lower", "upper"}
        if set(spec) != expected:
            raise ValueError(f"candidate {axis} policy schema is invalid")
        keys = ("value",) if mode == "Fix" else ("lower", "upper")
        values = []
        for key in keys:
            value = spec[key]
            if (isinstance(value, (bool, np.bool_))
                    or not isinstance(value, (int, float, np.integer, np.floating))):
                raise ValueError(f"candidate {axis} values must be finite numbers")
            value = float(value)
            if not np.isfinite(value) or (positive and value <= 0):
                raise ValueError(f"candidate {axis} values must be finite positive numbers")
            values.append(value)
        if mode == "Limit" and values[1] <= values[0]:
            raise ValueError(f"candidate {axis} bounds must be strictly increasing")
        return mode, values

    sh_mode, sh_values = parse_axis("shift")
    sq_mode, sq_values = parse_axis("squeeze", positive=True)
    derived = copy.deepcopy(ref_props)
    target_props = derived[target]
    if sh_mode == "Fix":
        target_props["sh_mode"] = "Fix"
        target_props["sh_val"] = repr(sh_values[0])
    else:
        _strict_interval(*sh_values, "candidate shift")
        target_props["sh_mode"] = "Limit"
        target_props["sh_val"] = f"{repr(sh_values[0])}, {repr(sh_values[1])}"
    if sq_mode == "Fix":
        if sq_values[0] != 1.0:
            raise ValueError("candidate fixed squeeze must be the absolute factor 1.0")
        target_props["sq_mode"] = "Fix"
        target_props["sq_val"] = "0.0"
    else:
        _strict_interval(*sq_values, "candidate squeeze")
        target_props["sq_mode"] = "Limit"
        target_props["sq_val"] = (f"{repr(sq_values[0] - 1.0)}, "
                                  f"{repr(sq_values[1] - 1.0)}")

    # Fail closed if our serialization does not round-trip through the same
    # parser used to derive independent Stage 1 nonlinear bounds.
    parsed = independent_global_bounds(derived, gas_order)
    if sh_mode == "Limit" and not np.allclose(
            parsed.get(f"{target}_sh", ()), sh_values, rtol=0.0, atol=1e-15):
        raise ValueError("candidate shift policy failed worker round-trip")
    if sh_mode == "Fix" and float(target_props["sh_val"]) != sh_values[0]:
        raise ValueError("candidate fixed shift failed worker round-trip")
    if sq_mode == "Limit" and not np.allclose(
            parsed.get(f"{target}_sq", ()), sq_values, rtol=0.0, atol=1e-15):
        raise ValueError("candidate squeeze policy failed worker round-trip")
    if sq_mode == "Fix":
        raw = float(target_props["sq_val"])
        worker_value = 1.0 + raw if abs(raw) < 0.5 else raw
        if worker_value != sq_values[0]:
            raise ValueError("candidate fixed squeeze failed worker round-trip")

    provenance = {
        "schema": "zero-base-policy-translation-v1",
        "candidate_id": candidate.get("id"),
        "target": target,
        "gas_order": gas_order,
        "source_policy": copy.deepcopy(policy),
        "derived_target_ref_props": copy.deepcopy(target_props),
        "source_policy_stage": "STAGE0_METADATA_ONLY",
        "fit_executed": False,
    }
    return {"ref_props": derived, "provenance": provenance}


def stage1_policy_starts(candidate):
    """Return the exact Stage 1 starts implied by one zero-base policy."""
    policy = candidate.get("policy") if isinstance(candidate, dict) else None
    if not isinstance(policy, dict) or set(policy) != {"shift", "squeeze"}:
        raise ValueError("candidate policy must contain exactly shift and squeeze")

    def axis_values(name):
        spec = policy[name]
        if not isinstance(spec, dict) or spec.get("mode") not in ("Fix", "Limit"):
            raise ValueError(f"candidate {name} policy is invalid")
        if spec["mode"] == "Fix":
            if set(spec) != {"mode", "value"}:
                raise ValueError(f"candidate {name} policy schema is invalid")
            value = spec["value"]
            if isinstance(value, (bool, np.bool_)) or not np.isfinite(value):
                raise ValueError(f"candidate {name} fixed value is invalid")
            return [float(value)]
        if set(spec) != {"mode", "lower", "upper"}:
            raise ValueError(f"candidate {name} policy schema is invalid")
        lo, hi = _strict_interval(spec["lower"], spec["upper"], f"candidate {name}")
        return [lo + .25 * (hi - lo), lo + .75 * (hi - lo)]

    shifts, squeezes = axis_values("shift"), axis_values("squeeze")
    active = len(shifts) == 2 or len(squeezes) == 2
    count = 2 if active else 1
    starts = []
    for index in range(count):
        starts.append({"id": f"start{index}",
                       "shift": shifts[index if len(shifts) == 2 else 0],
                       "squeeze": squeezes[index if len(squeezes) == 2 else 0]})
    return {"starts": starts, "attempts_per_scan": count,
            "seed_stability": ("PENDING" if active else "NOT_APPLICABLE"),
            "reason": ("ACTIVE_LIMIT_DIMENSION" if active else "FIXED_POLICY")}


def _run_diagnostic_vertical_slice(cfg, ref_props, candidate, scans, fit_callback, *,
                                   allow_negative_gas, target, expected_scans,
                                   schema, stage):
    """Execute one candidate's budget through an injected worker-compatible adapter.

    The callback receives immutable copies of the translated worker ``ref_props``
    and policy bounds.  It must expose the exact diagnostics schema below; this
    contract does not infer or preserve arbitrary callback content.
    """
    if allow_negative_gas is not True:
        raise ValueError(f"{stage} vertical slice requires explicit allow_negative_gas=True")
    if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str) \
            or not candidate["id"]:
        raise ValueError(f"{stage} candidate id is required")
    if not callable(fit_callback) or not isinstance(scans, list) or len(scans) != expected_scans:
        raise ValueError(f"{stage} vertical slice requires a callback and exactly {expected_scans} scans")
    scan_ids = [scan.get("id") for scan in scans if isinstance(scan, dict)]
    if len(scan_ids) != expected_scans or any(not isinstance(x, str) or not x for x in scan_ids) \
            or len(set(scan_ids)) != expected_scans:
        raise ValueError(f"{stage} scan identities must be {expected_scans} unique strings")
    translated = translate_zero_base_policy(cfg, ref_props, candidate, target)
    plan = stage1_policy_starts(candidate)
    policy = candidate["policy"]
    policy_bounds = {
        axis: ({"mode": "FIXED", "value": float(spec["value"])}
               if spec["mode"] == "Fix" else
               {"mode": "INTERVAL", "lower": float(spec["lower"]),
                "upper": float(spec["upper"])})
        for axis, spec in policy.items()
    }
    required = {"initial_shift", "initial_squeeze", "final_shift", "final_squeeze",
                "objective_initial", "objective_final", "solver_termination",
                "boundary_hits"}
    attempts = []
    for scan in scans:
        for start in plan["starts"]:
            try:
                raw = fit_callback(copy.deepcopy(candidate), copy.deepcopy(scan),
                                   copy.deepcopy(start),
                                   ref_props=copy.deepcopy(translated["ref_props"]),
                                   policy_bounds=copy.deepcopy(policy_bounds),
                                   allow_negative_gas=True)
                optional = {"target_concentration", "rms", "rms_sig", "coeffs"}
                if not isinstance(raw, dict) or not required.issubset(raw):
                    raise ValueError("worker result must match the exact Stage 1 schema")
                numeric = [raw[key] for key in required - {"solver_termination", "boundary_hits"}]
                if any(isinstance(v, (bool, np.bool_)) or not np.isfinite(v) for v in numeric):
                    raise ValueError("worker result contains non-finite diagnostics")
                if (not np.isclose(raw["initial_shift"], start["shift"], rtol=0.0, atol=1e-12)
                        or not np.isclose(raw["initial_squeeze"], start["squeeze"],
                                          rtol=0.0, atol=1e-12)):
                    raise ValueError("worker did not use the prescribed Stage 1 start")
                termination = raw["solver_termination"]
                if (not isinstance(termination, dict)
                        or set(termination) != {"status", "success", "nfev"}
                        or termination["status"] not in STAGE1_SOLVER_STATUSES
                        or type(termination["success"]) is not bool
                        or isinstance(termination["nfev"], (bool, np.bool_))
                        or not isinstance(termination["nfev"], (int, np.integer))
                        or termination["nfev"] < 0):
                    raise ValueError("worker solver termination is unavailable")
                hits = raw["boundary_hits"]
                if not isinstance(hits, list) or any(
                        not isinstance(hit, dict)
                        or set(hit) != {"parameter", "side", "value", "bound"}
                        or hit["parameter"] not in ("shift", "squeeze")
                        or hit["side"] not in ("lower", "upper")
                        or not np.isfinite([hit["value"], hit["bound"]]).all()
                        for hit in hits):
                    raise ValueError("worker boundary diagnostics are invalid")
                for axis in ("shift", "squeeze"):
                    spec = policy_bounds[axis]
                    if spec["mode"] == "FIXED" and not np.isclose(
                            raw[f"final_{axis}"], spec["value"], rtol=0.0, atol=1e-12):
                        raise ValueError(f"worker changed fixed {axis}")
                extra = {key: copy.deepcopy(raw[key]) for key in optional if key in raw}
                attempts.append({"candidate_id": candidate.get("id"),
                                 "scan_id": scan["id"], "start_id": start["id"],
                                 "status": "OK",
                                 **{key: copy.deepcopy(raw[key]) for key in required}, **extra,
                                 "objective_change": (float(raw["objective_final"])
                                                      - float(raw["objective_initial"]))})
            except Exception as exc:
                attempts.append({"candidate_id": candidate.get("id"),
                                 "scan_id": scan["id"], "start_id": start["id"],
                                 "status": "UNAVAILABLE", "reason": "FIT_ATTEMPT_EXCEPTION",
                                 "exception_class": type(exc).__name__})
    n_ok = sum(row["status"] == "OK" for row in attempts)
    return {"schema": schema, "candidate_id": candidate.get("id"),
            "status": "COMPLETE" if n_ok == len(attempts) else "ABSTAIN_INCOMPLETE",
            "policy": {"allow_negative_gas": True}, "budget": plan,
            "translation": {"scope": "TRANSLATION_ONLY_NO_FIT_CLAIM",
                            "details": translated["provenance"]},
            "policy_bounds": policy_bounds,
            "planned_attempts": expected_scans * plan["attempts_per_scan"],
            "executed_attempts": len(attempts), "successful_attempts": n_ok,
            "objective_change_convention": "final_minus_initial",
            "attempts": attempts,
            "limitations": ["No T2 verdict", "No ranking", "No plateau claim", "No Apply"]}


def run_stage1_vertical_slice(cfg, ref_props, candidate, scans, fit_callback, *,
                              allow_negative_gas, target="NO2"):
    """Execute the unchanged exact-four-scan Stage 1 diagnostic contract."""
    return _run_diagnostic_vertical_slice(
        cfg, ref_props, candidate, scans, fit_callback,
        allow_negative_gas=allow_negative_gas, target=target, expected_scans=4,
        schema=STAGE1_VERTICAL_SLICE_SCHEMA, stage="Stage 1")


def run_stage2_vertical_slice(cfg, ref_props, candidate, scans, fit_callback, *,
                              allow_negative_gas, target="NO2"):
    """Execute one Stage 2 candidate on exactly 12 scans; diagnostics only."""
    return _run_diagnostic_vertical_slice(
        cfg, ref_props, candidate, scans, fit_callback,
        allow_negative_gas=allow_negative_gas, target=target, expected_scans=12,
        schema=STAGE2_VERTICAL_SLICE_SCHEMA, stage="Stage 2")


def production_stage1_callback(eng, fitter, cfg, target="NO2"):
    """Adapt ``param_optimizer.fit_scan`` to the exact Stage 1 result schema."""
    gas_order = list(eng.gas_list)
    step_limit = float(cfg.get("step_limit", .5))

    def fit(candidate, scan, start, *, ref_props, policy_bounds,
            allow_negative_gas):
        if allow_negative_gas is not True:
            raise ValueError("production Stage 1 requires signed gas coefficients")
        required = {"wave", "alpha", "temperature_C", "pressure_mbar", "px_start"}
        if not isinstance(scan, dict) or not required.issubset(scan):
            raise ValueError("scan payload is incomplete")
        all_bounds = independent_global_bounds(ref_props, gas_order)
        initial_values = independent_initial_values(all_bounds, target)
        result = PO.fit_scan(
            eng, fitter, ref_props, scan["wave"], scan["alpha"],
            float(scan["temperature_C"]), float(scan["pressure_mbar"]),
            int(candidate["px_min"]) - int(scan["px_start"]),
            int(candidate["px_max"]) - int(scan["px_start"]),
            int(candidate["poly"]), step_limit, target,
            allow_negative_gas=True,
            controlled_start=(start["shift"], start["squeeze"]),
            controlled_bounds=all_bounds,
            controlled_initial_values=initial_values,
            return_solver_diagnostics=True)
        diagnostics = result.get("solver_diagnostics")
        if not isinstance(diagnostics, dict):
            raise ValueError("solver diagnostics are unavailable")
        raw_hits = boundary_hits(result, policy_bounds, target)
        hits = [{"parameter": hit["parameter"].lower(),
                 "side": hit["side"].lower(), "value": hit["value"],
                 "bound": hit["bound"]} for hit in raw_hits]
        summary = {}
        for name in ("conc", "rms", "rms_sig"):
            value = float(result.get(name, float("nan")))
            if np.isfinite(value):
                summary[{"conc": "target_concentration", "rms": "rms",
                         "rms_sig": "rms_sig"}[name]] = value
        coeffs = {str(k): float(v) for k, v in result.get("coeffs", {}).items()
                  if np.isfinite(float(v))}
        if coeffs:
            summary["coeffs"] = coeffs
        return {"initial_shift": float(start["shift"]),
                "initial_squeeze": float(start["squeeze"]),
                "final_shift": float(result["shifts"][target]),
                "final_squeeze": float(result["squeezes"][target]),
                "objective_initial": diagnostics["objective_initial"],
                "objective_final": diagnostics["objective_final"],
                **summary,
                "solver_termination": diagnostics["solver_termination"],
                "boundary_hits": hits}
    return fit


def _strict_interval(lo, hi, label):
    lo, hi = float(lo), float(hi)
    if not np.isfinite([lo, hi]).all() or hi <= lo:
        raise ValueError(f"invalid {label} bounds")
    margin = 1e-5
    if hi - lo <= 2 * margin or np.nextafter(lo + margin, np.inf) >= hi - margin:
        raise ValueError(f"{label} interval is too narrow for fitter interior margin")
    return lo, hi


def _worker_shift_interval(lo, hi, label):
    """Match setup_fit_parameters Limit behavior before validating usable width."""
    lo, hi = float(lo), float(hi)
    return _strict_interval(min(lo, hi), max(lo, hi), label)


def _squeeze_interval(value, label):
    lo, hi = map(float, str(value).split(","))
    lo = 1 + lo if abs(lo) < .5 else lo
    hi = 1 + hi if abs(hi) < .5 else hi
    return _strict_interval(lo, hi, label)


def target_global_bounds(ref_props, target):
    """Return finite FitSet-declared target bounds; never infer an Explorer range."""
    props = ref_props.get(target, {})
    mode = props.get("sh_mode")
    if mode == "Center":
        center, half = map(float, str(props.get("sh_val", "")).split(","))
        half = abs(half)
        if not np.isfinite([center, half]).all() or half == 0:
            raise ValueError("invalid target global shift bounds")
        sh_lo, sh_hi = _strict_interval(center - half, center + half,
                                         "target global shift")
    elif mode == "Limit":
        sh_lo, sh_hi = map(float, str(props.get("sh_val", "")).split(","))
        sh_lo, sh_hi = _worker_shift_interval(sh_lo, sh_hi, "target global shift")
    else:
        raise ValueError(f"target shift mode {mode!r} has no finite declared interval")
    sq_mode = props.get("sq_mode")
    if sq_mode == "Limit":
        sq_lo, sq_hi = _squeeze_interval(props.get("sq_val", ""),
                                          "target global squeeze")
        squeeze = {"mode": "INTERVAL", "lower": sq_lo, "upper": sq_hi}
    elif sq_mode == "Fix":
        value = float(props.get("sq_val", "1"))
        value = 1 + value if abs(value) < .5 else value
        if not np.isfinite(value):
            raise ValueError("invalid fixed target squeeze")
        squeeze = {"mode": "FIXED", "value": value}
    else:
        raise ValueError(f"target squeeze mode {sq_mode!r} has no finite declared interval")
    return {"shift": {"mode": "INTERVAL", "lower": sh_lo, "upper": sh_hi},
            "squeeze": squeeze,
            "source": "FitSet ref_props; Stage 1 independent-scan global bounds"}


def independent_global_bounds(ref_props, gas_order):
    """Bounds for every independently active nonlinear variable in Stage 1."""
    bounds = {}
    for gas in gas_order:
        props = ref_props.get(gas, {})
        sh_mode = props.get("sh_mode")
        if sh_mode == "Limit":
            lo, hi = map(float, str(props.get("sh_val", "")).split(","))
            lo, hi = _worker_shift_interval(lo, hi, f"{gas} global shift")
        elif sh_mode == "Center":
            center, half = map(float, str(props.get("sh_val", "")).split(","))
            half = abs(half)
            if not np.isfinite([center, half]).all() or half == 0:
                raise ValueError(f"invalid {gas} global shift bounds")
            lo, hi = _strict_interval(center - half, center + half,
                                      f"{gas} global shift")
        elif sh_mode in ("Fix", "Link"):
            lo = hi = None
        else:
            raise ValueError(f"{gas} shift mode {sh_mode!r} has no finite declared interval")
        if lo is not None:
            bounds[f"{gas}_sh"] = (float(lo), float(hi))

        sq_mode = props.get("sq_mode")
        if sq_mode == "Limit":
            lo, hi = _squeeze_interval(props.get("sq_val", ""),
                                       f"{gas} global squeeze")
            bounds[f"{gas}_sq"] = (float(lo), float(hi))
        elif sq_mode not in ("Fix", "Link"):
            raise ValueError(f"{gas} squeeze mode {sq_mode!r} has no finite declared interval")
    return bounds


def independent_initial_values(bounds, target):
    """Use one deterministic midpoint for every non-target active variable."""
    prefix = f"{target}_"
    return {name: float((lo + hi) / 2)
            for name, (lo, hi) in bounds.items() if not name.startswith(prefix)}


def controlled_starts(ref_props, target):
    """Two starts inside the FitSet global interval, independent of step_limit."""
    bounds = target_global_bounds(ref_props, target)
    lo, hi = bounds["shift"]["lower"], bounds["shift"]["upper"]
    margin = max(1e-5, np.finfo(float).eps * max(abs(lo), abs(hi), 1.0) * 16)
    usable_lo, usable_hi = lo + margin, hi - margin
    if usable_hi <= usable_lo or np.nextafter(usable_lo, np.inf) >= usable_hi:
        raise ValueError("global target interval cannot support two distinct starts")
    shifts = (usable_lo + .25 * (usable_hi - usable_lo),
              usable_lo + .75 * (usable_hi - usable_lo))
    sq = bounds["squeeze"]
    if sq["mode"] == "INTERVAL":
        sqs = (sq["lower"] + .25 * (sq["upper"] - sq["lower"]),
               sq["lower"] + .75 * (sq["upper"] - sq["lower"]))
    else:
        sqs = (sq["value"], sq["value"])
    starts = [dict(id=f"seed{i}", shift=float(shifts[i]), squeeze=float(sqs[i]),
                   provenance="interior quartile of FitSet global target bounds") for i in range(2)]
    if starts[0]["shift"] == starts[1]["shift"] and starts[0]["squeeze"] == starts[1]["squeeze"]:
        raise ValueError("controlled starts are not distinct")
    return starts


def boundary_hits(result, bounds, target="NO2"):
    """Report proximity to declared interval edges; diagnostic only."""
    hits = []
    for parameter, result_key in (("shift", "shifts"), ("squeeze", "squeezes")):
        spec = bounds[parameter]
        if spec["mode"] != "INTERVAL":
            continue
        lo, hi = float(spec["lower"]), float(spec["upper"])
        value = finite_or_none(result.get(result_key, {}).get(target))
        if value is None:
            continue
        span = hi - lo
        tolerance = max(span * 1e-6,
                        np.finfo(float).eps * max(abs(lo), abs(hi), 1.0) * 64)
        if value - lo <= tolerance:
            hits.append({"parameter": parameter.upper(), "side": "LOWER", "value": value,
                         "bound": lo, "tolerance": float(tolerance)})
        if hi - value <= tolerance:
            hits.append({"parameter": parameter.upper(), "side": "UPPER", "value": value,
                         "bound": hi, "tolerance": float(tolerance)})
    return hits


def boundary_diagnostic(rows, bounds, target="NO2", expected=STAGE1_EXPECTED_ATTEMPTS):
    applicable = [(parameter, result_key) for parameter, result_key in
                  (("shift", "shifts"), ("squeeze", "squeezes"))
                  if bounds[parameter]["mode"] == "INTERVAL"]
    complete = len(rows) == expected and all(
        finite_or_none(row.get("result", {}).get(result_key, {}).get(target)) is not None
        for row in rows for _, result_key in applicable)
    if not complete:
        return {"state": "UNAVAILABLE", "reason": "BOUNDARY_INPUT_INCOMPLETE",
                "hit_count": None, "bounds": bounds, "effect": "diagnostic_only"}
    hit_count = sum(len(row["result"]["boundary_hits"]) for row in rows)
    return {"state": "BOUNDARY_HIT" if hit_count else "NO_BOUNDARY_HIT",
            "hit_count": hit_count, "bounds": bounds, "effect": "diagnostic_only"}


def validate_coordinates(engine_wave, scans, candidates):
    """Reject missing/non-monotonic/misaligned alpha coordinates before fitting."""
    ew = np.asarray(engine_wave, float)
    if ew.ndim != 1 or len(ew) < 2 or not np.isfinite(ew).all() or not np.all(np.diff(ew) > 0):
        return ["engine wavecal is missing, non-finite, or non-monotonic"]
    max_px = max(c["px_max"] for c in candidates)
    problems = []
    for scan in scans:
        wave, alpha = np.asarray(scan["wave"], float), np.asarray(scan["alpha"], float)
        start = scan.get("px_start")
        if not isinstance(start, int):
            problems.append(f"{scan['id']}: detector pixel origin is ambiguous")
            continue
        local_min = min(c["px_min"] for c in candidates) - start
        local_max = max_px - start
        if (len(wave) != len(alpha) or local_min < 0 or local_max < local_min
                or len(wave) <= local_max):
            problems.append(f"{scan['id']}: alpha/wavelength length or candidate coverage mismatch")
        elif not np.isfinite(wave).all() or not np.all(np.diff(wave) > 0):
            problems.append(f"{scan['id']}: wavelength axis is non-finite or non-monotonic")
        elif wave[0] < ew[0] or wave[-1] > ew[-1]:
            problems.append(f"{scan['id']}: alpha wavelength axis leaves engine reference domain")
    return problems


def stage0_preflight(eng, candidate, target="NO2"):
    """Fit-free, conservative candidate preflight; PASS is not fit evidence."""
    details = {
        "collinearity_threshold": FP.COLLIN_HI_DEFAULT,
        "tolerance_source": "core.fit_physics.COLLIN_HI_DEFAULT",
        "original_reference_coverage": "UNAVAILABLE",
        "coverage_limitation": "engine references are already interpolated/extrapolated",
    }

    def verdict(state, *reasons):
        return {"state": state, "reason_codes": list(reasons), "details": details}

    try:
        wave = np.asarray(getattr(eng, "_wave_axis", None), dtype=float)
    except (TypeError, ValueError):
        return verdict("FAIL", "ENGINE_WAVE_INVALID")
    if wave.ndim != 1 or len(wave) < 2 or not np.isfinite(wave).all() or not np.all(np.diff(wave) > 0):
        return verdict("FAIL", "ENGINE_WAVE_INVALID")
    try:
        lo, hi, poly = (candidate[k] for k in ("px_min", "px_max", "poly"))
    except (KeyError, TypeError):
        return verdict("FAIL", "CANDIDATE_FIELDS_INVALID")
    if any(isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, np.integer))
           for v in (lo, hi, poly)):
        return verdict("FAIL", "CANDIDATE_FIELDS_INVALID")
    if lo < 0 or hi < 0 or poly < 0 or lo > hi:
        return verdict("FAIL", "CANDIDATE_BOUNDS_INVALID")
    if hi >= len(wave):
        return verdict("FAIL", "CANDIDATE_OUTSIDE_ENGINE_DOMAIN")
    gases = getattr(eng, "gas_list", None)
    if (not isinstance(gases, (list, tuple)) or not gases
            or any(not isinstance(g, str) or not g for g in gases)
            or len(set(gases)) != len(gases)):
        return verdict("FAIL", "GAS_ORDER_INVALID")
    if target not in gases:
        return verdict("FAIL", "TARGET_MISSING")
    refs = getattr(eng, "raw_references", None)
    if not isinstance(refs, dict):
        return verdict("FAIL", "REFERENCE_SET_INVALID")
    for gas in gases:
        if gas not in refs:
            return verdict("FAIL", "REFERENCE_MISSING")
        try:
            ref = np.asarray(refs[gas], dtype=float)
        except (TypeError, ValueError):
            return verdict("FAIL", "REFERENCE_ENGINE_COVERAGE_INVALID")
        if ref.ndim != 1 or len(ref) != len(wave) or not np.isfinite(ref[lo:hi + 1]).all():
            return verdict("FAIL", "REFERENCE_ENGINE_COVERAGE_INVALID")
    if hi - lo + 1 <= poly + 1:
        return verdict("FAIL", "POLY_UNDERDETERMINED")
    try:
        diag = FP.differential_collinearity(eng, list(gases), lo, hi, poly)
        multiple_r = finite_or_none(diag["multiple_R"].get(target))
    except Exception as exc:
        details["diagnostic_error_class"] = type(exc).__name__
        return verdict("UNAVAILABLE", "COLLINEARITY_DIAGNOSTIC_UNAVAILABLE")
    details["target_multiple_R"] = multiple_r
    if multiple_r is None:
        return verdict("UNAVAILABLE", "COLLINEARITY_DIAGNOSTIC_UNAVAILABLE")
    if multiple_r > FP.COLLIN_HI_DEFAULT:
        return verdict("FAIL", "TARGET_DIFFERENTIAL_COLLINEARITY")
    return verdict("PASS", "AVAILABLE_STATIC_CHECKS_PASSED")


def stage0_candidate_grid(eng, candidates, target="NO2"):
    """Run only fit-free preflight over an explicit candidate grid."""
    if not isinstance(candidates, list):
        raise ValueError("candidate grid must be a list")
    out = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str):
            out.append({"id": None, "stage0_preflight": {
                "state": "FAIL", "reason_codes": ["CANDIDATE_FIELDS_INVALID"],
                "details": {}}})
            continue
        result = dict(candidate)
        result["stage0_preflight"] = stage0_preflight(eng, candidate, target)
        out.append(result)
    counts = {state: sum(x["stage0_preflight"]["state"] == state for x in out)
              for state in ("PASS", "FAIL", "UNAVAILABLE")}
    return {"schema": ZERO_BASE_CANDIDATE_SCHEMA, "target": target,
            "fit_executed": False, "counts": counts, "candidates": out,
            "limitations": ["Stage 0 is fit-free preflight only", "No ranking", "No Apply"]}


def t2_tri_state(eng, candidate, successful_runs, target="NO2", expected_count=None):
    """Conservative adapter: a negative exclusion decision is never a PASS."""
    try:
        diag = FP.differential_collinearity(
            eng, list(eng.gas_list), candidate["px_min"], candidate["px_max"], candidate["poly"])
        multiple_r = finite_or_none(diag["multiple_R"].get(target))
    except Exception as exc:  # diagnostic failure is unavailable, not pass
        return {"state": "UNAVAILABLE", "reason": "COLLINEARITY_UNAVAILABLE",
                "details": {"exception_class": type(exc).__name__}}
    details = {"target_multiple_R": multiple_r,
               "threshold": FP.COLLIN_HI_DEFAULT}
    if multiple_r is not None and multiple_r > FP.COLLIN_HI_DEFAULT:
        return {"state": "FAIL", "reason": "target differential collinearity", "details": details}
    anchored, incomplete = [], []
    for gas in eng.gas_list:
        ratios = []
        applicable = str(gas).upper() == "O4"
        for row in successful_runs:
            try:
                theo = FP.theoretical_amount(gas, row.get("T_C"), row.get("P_mbar"))
            except (TypeError, ValueError, OverflowError):
                theo = float("nan") if applicable else None
            coeff = row["result"].get("coeffs", {}).get(gas)
            if theo is not None:
                applicable = True
                try:
                    retrieved = FP.retrieved_amount(eng, coeff, gas)
                except (TypeError, ValueError, OverflowError):
                    retrieved = float("nan")
                theo_num, retrieved_num = finite_or_none(theo), finite_or_none(retrieved)
                if theo_num is not None and theo_num > 0 and retrieved_num is not None:
                    ratios.append(abs(retrieved_num / theo_num))
                else:
                    incomplete.append(f"{gas}: non-finite/non-positive theoretical or retrieved amount")
        if applicable and expected_count is not None and len(ratios) != expected_count:
            incomplete.append(f"{gas}: complete ratios {len(ratios)}/{expected_count}")
        if ratios:
            ratio = float(np.median(ratios))
            anchored.append({"gas": gas, "abs_ratio": ratio, "limit": 3.0})
            if ratio > 3.0:
                return {"state": "FAIL", "reason": f"{gas} absolute amount exceeds bound",
                        "details": {**details, "anchors": anchored}}
    details["anchors"] = anchored
    details["incomplete"] = sorted(set(incomplete))
    return ({"state": "PASS", "reason": "available T2 checks passed", "details": details}
            if anchored and multiple_r is not None and not incomplete else
            {"state": "UNAVAILABLE", "reason": "required T2 input or absolute-amount anchor unavailable",
             "details": details})


def stage1_gate(preflight_state, n_ok, n_fail, attempt_t2_states,
                expected=STAGE1_EXPECTED_ATTEMPTS):
    """Decide only whether conservative Stage 1 evidence may advance."""
    if preflight_state != "PASS":
        return {"state": "UNAVAILABLE", "reason": "STAGE0_NOT_PASSED",
                "expected": expected, "n_ok": 0, "n_fail": 0,
                "t2_counts": {s: 0 for s in ("PASS", "FAIL", "UNAVAILABLE")},
                "advance": False, "rerun_required": False}
    if n_ok + n_fail != expected or len(attempt_t2_states) != n_ok:
        raise ValueError("Stage 1 gate attempt accounting is inconsistent")
    counts = {state: attempt_t2_states.count(state)
              for state in ("PASS", "FAIL", "UNAVAILABLE")}
    if any(state not in counts for state in attempt_t2_states):
        raise ValueError("Stage 1 gate received a non-canonical T2 state")
    if n_ok == 0:
        state, reason, advance = "UNAVAILABLE", "ALL_ATTEMPTS_UNAVAILABLE", True
    elif n_ok < expected:
        state, reason, advance = "UNAVAILABLE", "EXECUTION_INCOMPLETE", True
    elif counts["FAIL"] == expected:
        state, reason, advance = "FAIL", "ALL_ATTEMPTS_T2_FAIL", False
    elif counts["PASS"] == expected:
        state, reason, advance = "PASS", "ALL_ATTEMPTS_T2_PASS", True
    elif counts["UNAVAILABLE"]:
        state, reason, advance = "UNAVAILABLE", "T2_UNAVAILABLE", True
    else:
        state, reason, advance = "UNAVAILABLE", "MIXED_T2_OUTCOMES", True
    return {"state": state, "reason": reason, "expected": expected,
            "n_ok": n_ok, "n_fail": n_fail, "t2_counts": counts,
            "advance": advance, "rerun_required": state == "UNAVAILABLE"}


def stage1_evaluation_state(gate):
    return ({"FAIL": "EVALUATED_FAIL", "PASS": "EVALUATED_PASS",
             "UNAVAILABLE": "UNEVALUATED"}[gate["state"]])


def paired_start_outputs(scans, starts, rows, failures):
    """Expose paired raw start results and arithmetic deltas without judging them."""
    ok = {(row["scan_id"], row["seed_id"]): row for row in rows}
    failed = {(row["scan_id"], row["seed_id"]): row for row in failures}
    numeric = ("conc", "rms_sig", "perr_rel", "autocorr1")
    pairs = []
    for scan in scans:
        entries = []
        for seed in starts:
            key = (scan["id"], seed["id"])
            if key in ok:
                entries.append({"seed_id": seed["id"], "status": "OK",
                                "result": ok[key]["result"]})
            else:
                entries.append({"seed_id": seed["id"], "status": "FAIL",
                                "error": failed.get(key, {}).get("error", "missing attempt")})
        deltas = {}
        if len(entries) == 2 and all(entry["status"] == "OK" for entry in entries):
            for key in numeric:
                a = finite_or_none(entries[0]["result"].get(key))
                b = finite_or_none(entries[1]["result"].get(key))
                deltas[key] = None if a is None or b is None else b - a
        pairs.append({"scan_id": scan["id"], "expected_starts": len(starts),
                      "n_ok": sum(e["status"] == "OK" for e in entries),
                      "n_fail": sum(e["status"] == "FAIL" for e in entries),
                      "completeness": ("COMPLETE" if all(e["status"] == "OK" for e in entries)
                                       else "INCOMPLETE"),
                      "starts": entries, "deltas": deltas})
    return pairs


def seed_stability(pairs, target="NO2"):
    """Classify paired-start convergence only; this is not a T2 physics gate."""
    tolerances = dict(SEED_STABILITY_TOLERANCES)
    checks = []
    unavailable = lambda reason: {"state": "UNAVAILABLE", "reason": reason,
                                  "target": target, "tolerances": tolerances,
                                  "checks": checks}
    if len(pairs) != 4:
        return unavailable("PAIRED_STARTS_INCOMPLETE")
    for pair in pairs:
        starts = pair.get("starts", [])
        if (pair.get("completeness") != "COMPLETE" or len(starts) != 2
                or any(start.get("status") != "OK" for start in starts)):
            return unavailable("PAIRED_STARTS_INCOMPLETE")
        a, b = (start.get("result", {}) for start in starts)
        values = [finite_or_none(a.get("conc")), finite_or_none(b.get("conc")),
                  finite_or_none(a.get("shifts", {}).get(target)),
                  finite_or_none(b.get("shifts", {}).get(target)),
                  finite_or_none(a.get("squeezes", {}).get(target)),
                  finite_or_none(b.get("squeezes", {}).get(target)),
                  finite_or_none(a.get("rms_sig")), finite_or_none(b.get("rms_sig"))]
        if any(value is None for value in values):
            return unavailable("PAIRED_START_VALUE_UNAVAILABLE")
        ca, cb, sha, shb, sqa, sqb, ra, rb = values
        conc_limit = max(tolerances["conc_abs_ppb"],
                         tolerances["conc_rel"] * max(abs(ca), abs(cb)))
        rms_scale = max(abs(ra), abs(rb))
        deltas = {"conc_abs_ppb": abs(cb - ca), "conc_limit_ppb": conc_limit,
                  "shift_abs_px": abs(shb - sha), "squeeze_abs": abs(sqb - sqa),
                  "rms_sig_rel": 0.0 if rms_scale == 0 else abs(rb - ra) / rms_scale}
        within = lambda value, limit: bool(value <= limit or
                                           np.isclose(value, limit, rtol=1e-12, atol=1e-15))
        passed = (within(deltas["conc_abs_ppb"], conc_limit)
                  and within(deltas["shift_abs_px"], tolerances["shift_abs_px"])
                  and within(deltas["squeeze_abs"], tolerances["squeeze_abs"])
                  and within(deltas["rms_sig_rel"], tolerances["rms_sig_rel"]))
        checks.append({"scan_id": pair.get("scan_id"), "passed": passed,
                       "deltas": deltas})
    stable = all(check["passed"] for check in checks)
    return {"state": "SEED_STABLE" if stable else "SEED_UNSTABLE",
            "reason": "ALL_PAIRS_WITHIN_TOLERANCE" if stable else "PAIR_THRESHOLD_EXCEEDED",
            "target": target, "tolerances": tolerances, "checks": checks}


def attempt_identity_check(scans, starts, rows, failures):
    """Require one outcome for every member of the exact 4x2 Cartesian budget."""
    scan_ids = [scan.get("id") for scan in scans]
    seed_ids = [seed.get("id") for seed in starts]
    if (len(scan_ids) != 4 or len(set(scan_ids)) != 4
            or len(seed_ids) != 2 or len(set(seed_ids)) != 2):
        return {"state": "UNAVAILABLE", "reason": "ATTEMPT_IDENTITY_INVALID"}
    expected = {(scan_id, seed_id) for scan_id in scan_ids for seed_id in seed_ids}
    outcomes = [(row.get("scan_id"), row.get("seed_id")) for row in [*rows, *failures]]
    if len(outcomes) != len(expected) or len(set(outcomes)) != len(outcomes):
        return {"state": "UNAVAILABLE", "reason": "ATTEMPT_IDENTITY_INVALID"}
    if set(outcomes) != expected:
        return {"state": "UNAVAILABLE", "reason": "ATTEMPT_IDENTITY_INVALID"}
    return {"state": "PASS", "reason": "ATTEMPT_IDENTITY_COMPLETE"}


def evaluate_candidate(eng, fitter, ref_props, scans, candidate, starts,
                       step_limit, allow_negative_gas, target="NO2", target_bounds=None,
                       nonlinear_bounds=None):
    preflight = stage0_preflight(eng, candidate, target)
    if preflight["state"] != "PASS":
        gate = stage1_gate(preflight["state"], 0, 0, [])
        return {**candidate,
                "evaluation_state": "UNEVALUATED",
                "stage0_preflight": preflight,
                "execution_gate": {"state": "NOT_RUN", "n_ok": 0, "n_fail": 0},
                "t2_gate": {"state": "UNAVAILABLE", "reason": "fit not run after Stage 0"},
                "stage1_gate": gate, "paired_starts": [],
                "seed_stability": {**seed_stability([], target), "reason": "FIT_NOT_RUN"},
                "boundary_diagnostic": {
                    "state": "UNAVAILABLE", "reason": "FIT_NOT_RUN",
                    "hit_count": None, "bounds": target_bounds,
                    "effect": "diagnostic_only"},
                "metrics": {key: summary([]) for key in
                            ("conc", "rms_sig", "perr_rel", "autocorr1")},
                "runs": [], "failures": [], "seconds": 0.0}
    target_bounds = target_bounds or target_global_bounds(ref_props, target)
    nonlinear_bounds = nonlinear_bounds or independent_global_bounds(ref_props, eng.gas_list)
    secondary_initials = independent_initial_values(nonlinear_bounds, target)
    rows, failures = [], []
    started = time.perf_counter()
    for scan in scans:
        for seed in starts:
            t0 = time.perf_counter()
            try:
                fit_lo = candidate.get("fit_px_min", candidate["px_min"])
                fit_hi = candidate.get("fit_px_max", candidate["px_max"])
                result = PO.fit_scan(
                    eng, fitter, ref_props, scan["wave"], scan["alpha"], scan["T_C"], scan["P_mbar"],
                    fit_lo, fit_hi, candidate["poly"], step_limit, target,
                    allow_negative_gas=allow_negative_gas,
                    controlled_start=(seed["shift"], seed["squeeze"]),
                    controlled_bounds=nonlinear_bounds,
                    controlled_initial_values=secondary_initials)
                result["boundary_hits"] = boundary_hits(result, target_bounds, target)
                rows.append({"scan_id": scan["id"], "seed_id": seed["id"], "T_C": scan["T_C"],
                             "P_mbar": scan["P_mbar"], "seconds": time.perf_counter() - t0,
                             "result": result})
            except Exception as exc:
                failures.append({"scan_id": scan["id"], "seed_id": seed["id"],
                                 "seconds": time.perf_counter() - t0,
                                 "error": "FIT_ATTEMPT_EXCEPTION",
                                 "exception_class": type(exc).__name__})
    gate = ("PASS" if rows and not failures else "FAIL" if not rows else "UNAVAILABLE")
    vals = lambda key: [r["result"][key] for r in rows if np.isfinite(r["result"][key])]
    metrics = {key: summary(vals(key)) for key in ("conc", "rms_sig", "perr_rel", "autocorr1")}
    expected = STAGE1_EXPECTED_ATTEMPTS
    if len(scans) != 4 or len(starts) != 2:
        raise ValueError("Stage 1 evaluation requires exactly 4 scans and 2 starts")
    identity = attempt_identity_check(scans, starts, rows, failures)
    if identity["state"] != "PASS":
        s1 = {"state": "UNAVAILABLE", "reason": identity["reason"],
              "expected": expected, "n_ok": len(rows), "n_fail": len(failures),
              "t2_counts": {s: 0 for s in ("PASS", "FAIL", "UNAVAILABLE")},
              "advance": True, "rerun_required": True}
        return {**candidate, "evaluation_state": "UNEVALUATED",
                "stage0_preflight": preflight,
                "execution_gate": {"state": gate, "n_ok": len(rows), "n_fail": len(failures)},
                "attempt_identity": identity, "stage1_gate": s1,
                "t2_gate": {"state": "UNAVAILABLE", "reason": "ATTEMPT_IDENTITY_INVALID"},
                "metrics": metrics, "paired_starts": [],
                "seed_stability": {**seed_stability([], target),
                                   "reason": "ATTEMPT_IDENTITY_INVALID"},
                "boundary_diagnostic": {
                    "state": "UNAVAILABLE", "reason": "ATTEMPT_IDENTITY_INVALID",
                    "hit_count": None, "bounds": target_bounds,
                    "effect": "diagnostic_only"},
                "runs": rows,
                "failures": failures, "seconds": time.perf_counter() - started}
    attempt_t2 = [t2_tri_state(eng, candidate, [row], target, expected_count=1)
                  for row in rows]
    for row, verdict in zip(rows, attempt_t2):
        row["t2"] = verdict
    t2 = t2_tri_state(eng, candidate, rows, target, expected)
    s1 = stage1_gate(preflight["state"], len(rows), len(failures),
                     [verdict["state"] for verdict in attempt_t2], expected)
    state = stage1_evaluation_state(s1)
    pairs = paired_start_outputs(scans, starts, rows, failures)
    out = {**candidate, "evaluation_state": state, "stage0_preflight": preflight,
           "attempt_identity": identity,
           "execution_gate": {"state": gate, "n_ok": len(rows), "n_fail": len(failures)},
           "t2_gate": t2, "stage1_gate": s1, "metrics": metrics,
           "paired_starts": pairs, "seed_stability": seed_stability(pairs, target),
           "boundary_diagnostic": boundary_diagnostic(rows, target_bounds, target),
           "runs": rows, "failures": failures, "seconds": time.perf_counter() - started}
    return out


def summary(values):
    return ({"n": 0, "median": None, "min": None, "max": None} if not values else
            {"n": len(values), "median": float(np.median(values)),
             "min": float(np.min(values)), "max": float(np.max(values))})


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git_provenance(root, excluded_paths=()):
    def run(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                              text=True, encoding="utf-8", errors="replace").stdout
    head = run("rev-parse", "HEAD").strip()
    root_real = os.path.realpath(root)
    excluded = sorted({os.path.relpath(os.path.abspath(p), root_real).replace("\\", "/")
                       for p in excluded_paths
                       if os.path.commonpath((root_real, os.path.realpath(p))) == root_real})
    pathspec = ["."] + [f":(exclude){p}" for p in excluded]
    diff = run("diff", "--binary", "HEAD", "--", *pathspec).replace("\r\n", "\n").encode()
    raw_untracked = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "--others",
         "--exclude-standard", "-z"],
        cwd=root, check=True, capture_output=True).stdout
    untracked = sorted(os.fsdecode(path) for path in raw_untracked.split(b"\0") if path)
    def is_excluded(path):
        path = path.replace("\\", "/")
        return any(path == item or path.startswith(item.rstrip("/") + "/")
                   for item in excluded)
    untracked = [p for p in untracked if not is_excluded(p)]
    return {"head": head, "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
            "untracked": [{"path": p.replace("\\", "/"), "sha256": sha256_file(os.path.join(root, p))}
                          for p in untracked], "dirty": bool(diff or untracked),
            "excluded_paths": excluded}


def finite_or_none(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def output_collides(output, inputs):
    out = os.path.normcase(os.path.realpath(output))
    return out in {os.path.normcase(os.path.realpath(p)) for p in inputs if p}


def ensure_output_safe(output, inputs):
    if output_collides(output, inputs):
        raise ValueError("report output collides with an input file")


def json_ready(value):
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def overall_status(candidates):
    states = [c.get("evaluation_state") for c in candidates]
    preflight_states = [c.get("stage0_preflight", {}).get("state") for c in candidates]
    if "UNAVAILABLE" in preflight_states:
        return "ABSTAIN_INCOMPLETE"
    if states and all(s == "EVALUATED_FAIL" or (s == "UNEVALUATED" and p == "FAIL")
                      for s, p in zip(states, preflight_states)):
        return "ABSTAIN"
    if any(s not in ("UNEVALUATED", "EVALUATED_PASS", "EVALUATED_FAIL") for s in states):
        return "ABSTAIN_INCOMPLETE"
    rerun_required = any(c.get("stage1_gate", {}).get("rerun_required", False)
                         for c in candidates)
    unresolved_nonadvancing = any(
        s == "UNEVALUATED" and not c.get("stage1_gate", {}).get("advance", False)
        and c.get("stage0_preflight", {}).get("state") != "FAIL"
        for s, c in zip(states, candidates))
    if rerun_required or unresolved_nonadvancing:
        return "ABSTAIN_INCOMPLETE"
    return "EVALUATED_NO_PLATEAU_CLAIM"


def write_report(path, report):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix=".fit-explorer-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(json_ready(report), fh, ensure_ascii=False, indent=2, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
