"""Mission-agnostic batch/checkpoint contract for Fit Setting Explorer.

This module deliberately knows nothing about DOAS engines.  Callers validate and
prepare every channel first, then inject one candidate executor.  It does not
score, rank, recommend, apply, or interpret T2/plateau state.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets



SCHEMA = "fit-explorer-batch-v1"
SUPPORTED_STAGES = {1, 2}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}
_RESULT_FIELDS = {"schema", "candidate_id", "status", "policy", "budget",
    "translation", "policy_bounds", "planned_attempts", "executed_attempts",
    "successful_attempts", "objective_change_convention", "attempts",
    "limitations", "sampling", "source", "quality_gate", "t2_gate", "t2_diagnostics"}
_PUBLIC_KEYS = _RESULT_FIELDS | {
    "active_bands_nm", "allow_negative_gas", "attempts_per_scan", "bound",
    "boundary_hits", "channel", "channel_source", "coeffs", "contract", "date", "quality_state", "quality_gate",
    "date_range", "derived_target_ref_props", "details", "eligible_per_date",
    "eligible_rows", "executed_attempts", "expected_channel", "file",
    "final_shift", "final_squeeze", "fit_executed", "fitset", "gas_order",
    "id", "independence_note", "initial_shift", "initial_squeeze", "lower",
    "manifest_reuse", "minimum_distinct_dates", "mode", "name", "nfev", "objective_change",
    "objective_final", "objective_initial", "observation_key", "parameter",
    "planned_attempts", "reason", "references", "requested_scans", "row_index",
    "sample_order", "samples", "scan_id", "scope", "seed_stability", "selected_alpha", "selected_per_date",
    "selected_zero_based_indices", "sh_mode", "sh_val", "sha256", "shift",
    "side", "solver_termination", "source_policy", "source_policy_stage",
    "sq_mode", "sq_val", "squeeze", "start_id", "starts", "state_stratification",
    "success", "successful_attempts", "t_coeff", "t_ref", "target", "exception_class",
    "time_source", "timestamp", "target_concentration", "upper", "value", "wavecal", "rms", "rms_sig", "T_C", "P_mbar", "temperature_pressure_source", "t2_gate", "t2_diagnostics", "state", "reason", "details", "anchors", "abs_ratio", "limit", "target_multiple_R", "threshold", "incomplete", "n", "outlier_count", "median", "mad_scaled", "successful_attempts", "coefficient_health", "collinearity", "absolute_anchor"}
_FORBIDDEN_PUBLIC_KEYS = {"path", "message", "traceback", "exception_message"}


def canonical_json_hash(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def atomic_write_json(path, document, *, immutable=False):
    """Fsync then replace; immutable evidence may only be replayed identically."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    encoded = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True,
                          allow_nan=False) + "\n").encode("utf-8")
    if immutable and os.path.exists(path):
        with open(path, "rb") as fh:
            if fh.read() == encoded:
                return
        raise FileExistsError("immutable batch evidence already exists")
    tmp = path + ".tmp." + secrets.token_hex(8)
    try:
        with open(tmp, "xb") as fh:
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _safe_id_key(value):
    trimmed = value.rstrip(" .")
    stem = trimmed.split(".", 1)[0].upper()
    if not trimmed or stem in _RESERVED:
        raise ValueError("candidate id is not a Windows-safe path component")
    return os.path.normcase(trimmed).casefold()


def _validate_public_value(value, key=""):
    """Reject private paths/messages without trying to scrub scientific output."""
    if key.casefold() in _FORBIDDEN_PUBLIC_KEYS:
        raise ValueError("public result contains a forbidden field")
    if isinstance(value, dict):
        if key in {"t2_gate", "t2_diagnostics"}:
            # T2 details contain dynamic gas names; retain safety checks while
            # allowing domain-specific nested diagnostic keys.
            def walk_t2(child):
                if isinstance(child, dict):
                    for name, item in child.items():
                        if not isinstance(name, str) or name.casefold() in _FORBIDDEN_PUBLIC_KEYS:
                            raise ValueError("T2 diagnostic contains a forbidden field")
                        walk_t2(item)
                elif isinstance(child, list):
                    for item in child:
                        walk_t2(item)
                elif isinstance(child, str) and re.search(r"(?:^[A-Za-z]:[\\/]|^\\\\|^/)", child):
                    raise ValueError("T2 diagnostic contains a path-like string")
            walk_t2(value)
            return
        if key in {"selected_per_date", "eligible_per_date"}:
            from datetime import date
            for date_key, count in value.items():
                if not isinstance(date_key, str):
                    raise ValueError("per-date sampling keys must be ISO dates")
                try:
                    date.fromisoformat(date_key)
                except ValueError as exc:
                    raise ValueError("per-date sampling keys must be ISO dates") from exc
                if (isinstance(count, bool) or not isinstance(count, int)
                        or count < 0):
                    raise ValueError("per-date sampling counts must be nonnegative integers")
            return
        if key == "coeffs":
            if any(not isinstance(name, str) or not isinstance(value, (int, float))
                   or isinstance(value, bool) for name, value in value.items()):
                raise ValueError("coefficient summary is invalid")
            return
        for child_key, child in value.items():
            if not isinstance(child_key, str) or child_key not in _PUBLIC_KEYS:
                raise ValueError("public result contains a non-allowlisted field")
            _validate_public_value(child, child_key)
    elif isinstance(value, list):
        for child in value:
            _validate_public_value(child, key)
    elif isinstance(value, str):
        # Reject absolute/local paths, but allow ordinary prose containing
        # words such as "file/date" in scientific limitations.
        if re.search(r"(?:^[A-Za-z]:[\\/]|^\\\\|^/)", value):
            raise ValueError("public result contains a path-like string")


def validate_public_result(payload, *, stage, candidate_id):
    """Accept only the established vertical-slice public report envelope."""
    if not isinstance(payload, dict) or set(payload) != _RESULT_FIELDS:
        raise ValueError("executor result does not match the public report schema")
    expected_schema = f"stage{stage}-one-candidate-v1"
    if payload.get("schema") != expected_schema or payload.get("candidate_id") != candidate_id:
        raise ValueError("executor result identity does not match the batch candidate")
    _validate_public_value(payload)
    # Also proves the complete result is finite JSON, not merely its outer envelope.
    canonical_json_hash(payload)
    return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))


def _integrity(document):
    return canonical_json_hash({key: value for key, value in document.items()
                                if key != "integrity_sha256"})


def validate_config(document):
    """Validate the complete public configuration without opening data files."""
    if not isinstance(document, dict) or set(document) != {
            "schema", "mission", "stage", "allow_negative_gas", "output_root",
            "date_range", "channels"}:
        raise ValueError("batch config fields do not match the v1 schema")
    if document["schema"] != SCHEMA:
        raise ValueError("unsupported batch config schema")
    if not isinstance(document["mission"], str) or not document["mission"].strip():
        raise ValueError("mission must be a non-empty opaque label")
    _validate_public_value(document["mission"], "mission")
    if document["stage"] not in SUPPORTED_STAGES or isinstance(document["stage"], bool):
        raise ValueError("stage must be 1 or 2")
    if document["allow_negative_gas"] is not True:
        raise ValueError("allow_negative_gas must be explicitly true")
    if not isinstance(document["output_root"], str) or not document["output_root"]:
        raise ValueError("output_root is required")
    dates = document["date_range"]
    if not isinstance(dates, list) or len(dates) != 2 \
            or not all(isinstance(value, str) for value in dates):
        raise ValueError("date_range must contain two ISO dates")
    from datetime import date
    try:
        lo, hi = map(date.fromisoformat, dates)
    except ValueError as exc:
        raise ValueError("date_range contains an invalid ISO date") from exc
    if hi < lo:
        raise ValueError("date_range is reversed")
    channels = document["channels"]
    if not isinstance(channels, list) or not channels:
        raise ValueError("channels must be a non-empty list")
    labels, alpha_globs = set(), set()
    for channel in channels:
        allowed = {"label", "fitset", "alpha_glob", "candidates", "sample_manifest", "target_species", "fitset_channel_key", "channel_header_key", "exclude_alpha_basenames"}
        if not isinstance(channel, dict) or not set(channel).issubset(allowed) \
                or not {"label", "fitset", "alpha_glob", "candidates"}.issubset(channel):
            raise ValueError("channel config is incomplete")
        label = channel["label"]
        if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", label) or label in labels:
            raise ValueError("channel labels must be unique opaque IDs")
        labels.add(label)
        if "target_species" in channel:
            target = channel["target_species"]
            if (not isinstance(target, str) or
                    not re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", target)):
                raise ValueError("target_species must be a safe opaque species ID")
        if "fitset_channel_key" in channel and not isinstance(channel["fitset_channel_key"], str):
            raise ValueError("fitset_channel_key must be a string")
        if "channel_header_key" in channel and not isinstance(channel["channel_header_key"], str):
            raise ValueError("channel_header_key must be a string")
        if "exclude_alpha_basenames" in channel:
            excluded = channel["exclude_alpha_basenames"]
            if (not isinstance(excluded, list) or
                    any(not isinstance(name, str) or not name or
                        os.path.basename(name) != name for name in excluded) or
                    len(set(excluded)) != len(excluded)):
                raise ValueError("exclude_alpha_basenames must be unique basenames")
        for field in ("fitset", "alpha_glob"):
            if not isinstance(channel[field], str) or not channel[field]:
                raise ValueError(f"channel {field} is required")
        normalized_glob = os.path.normcase(os.path.abspath(channel["alpha_glob"]))
        if normalized_glob in alpha_globs:
            raise ValueError("alpha_glob is duplicated across channels")
        alpha_globs.add(normalized_glob)
        if document["stage"] == 2 and "sample_manifest" not in channel:
            raise ValueError("Stage 2 requires an explicit sample_manifest per channel")
        if "sample_manifest" in channel and (not isinstance(channel["sample_manifest"], str)
                                              or not channel["sample_manifest"]):
            raise ValueError("sample_manifest must be a non-empty path")
        candidates = channel["candidates"]
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("each channel requires declared candidates")
        ids = set()
        for item in candidates:
            if not isinstance(item, dict) or set(item) != {"id", "policy"} \
                    or not isinstance(item["id"], str) or not _ID.fullmatch(item["id"]):
                raise ValueError("candidate requires a safe exact id and policy")
            safe_key = _safe_id_key(item["id"])
            if safe_key in ids:
                raise ValueError("candidate id is duplicated within a channel")
            ids.add(safe_key)
            if not isinstance(item["policy"], dict) or set(item["policy"]) != {"shift", "squeeze"}:
                raise ValueError("candidate policy must declare shift and squeeze")
    return document


def _complete_report(path, expected):
    try:
        with open(path, encoding="utf-8") as fh:
            report = json.load(fh)
        if set(report) != {"schema", "mission", "stage", "channel",
                "candidate_id", "policy", "input_hash", "config_hash", "code_hash",
                "result", "batch_checkpoint", "scientific_scope", "integrity_sha256"}:
            return None
        if report.get("integrity_sha256") != _integrity(report):
            return None
        fingerprint = expected["fingerprint"]
        checks = {key: report.get(key) for key in expected if key != "fingerprint"}
        checkpoint = report.get("batch_checkpoint")
        wanted = {key: value for key, value in expected.items() if key != "fingerprint"}
        if checks != wanted or checkpoint != {"state": "COMPLETE", "fingerprint": fingerprint}:
            return None
        validate_public_result(report["result"], stage=report["stage"],
                               candidate_id=report["candidate_id"])
        return report
    except (OSError, ValueError, TypeError):
        return None


def run_prepared_batch(config, prepared, executor, *, code_hash, dry_run=False):
    """Run all prevalidated candidates sequentially with resumable evidence."""
    validate_config(config)
    if not isinstance(code_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", code_hash):
        raise ValueError("code_hash must be a SHA-256 digest")
    expected = [channel["label"] for channel in config["channels"]]
    if not isinstance(prepared, dict) or set(prepared) != set(expected):
        raise ValueError("all configured channels must be prepared before execution")
    for label in expected:
        item = prepared[label]
        if set(item) != {"input_hash", "candidates", "context"} \
                or not re.fullmatch(r"[0-9a-f]{64}", item["input_hash"]):
            raise ValueError("prepared channel contract is invalid")
        declared = config["channels"][expected.index(label)]["candidates"]
        if set(item["candidates"]) != {entry["id"] for entry in declared}:
            raise ValueError("prepared candidates do not match declared ids")
        for entry in declared:
            candidate = item["candidates"][entry["id"]]
            if candidate.get("id") != entry["id"] or candidate.get("policy") != entry["policy"]:
                raise ValueError("declared candidate id/policy does not match generated grid")

    public_config = {key: config[key] for key in
                     ("schema", "mission", "stage", "allow_negative_gas", "date_range")}
    config_hash = canonical_json_hash({**public_config,
        "channels": [{"label": channel["label"], "candidates": channel["candidates"]}
                     for channel in config["channels"]]})
    batch_dir = os.path.join(config["output_root"], "batch-" + config_hash[:16])
    results = []
    for channel in config["channels"]:
        label, material = channel["label"], prepared[channel["label"]]
        for declaration in channel["candidates"]:
            candidate_id = declaration["id"]
            fingerprint = canonical_json_hash({"config_hash": config_hash,
                "code_hash": code_hash, "input_hash": material["input_hash"],
                "channel": label, "candidate_id": candidate_id,
                "policy": declaration["policy"]})
            candidate_root = os.path.join(batch_dir, label, candidate_id)
            evidence_dir = os.path.join(candidate_root, fingerprint)
            report_path = os.path.join(evidence_dir, "report.json")
            existing = _complete_report(report_path, {
                "fingerprint": fingerprint, "channel": label,
                "candidate_id": candidate_id, "input_hash": material["input_hash"],
                "config_hash": config_hash, "code_hash": code_hash,
                "policy": declaration["policy"]})
            if existing is not None:
                repaired = {"schema": SCHEMA, "channel": label,
                    "candidate_id": candidate_id, "fingerprint": fingerprint,
                    "config_hash": config_hash, "code_hash": code_hash,
                    "input_hash": material["input_hash"], "state": "COMPLETE",
                    "report_sha256": existing["integrity_sha256"]}
                checkpoint_path = os.path.join(candidate_root, "checkpoint.json")
                try:
                    with open(checkpoint_path, encoding="utf-8") as fh:
                        current_checkpoint = json.load(fh)
                except (OSError, ValueError, TypeError):
                    current_checkpoint = None
                if current_checkpoint != repaired:
                    atomic_write_json(checkpoint_path, repaired)
                results.append({"channel": label, "candidate_id": candidate_id,
                                "state": "COMPLETE", "action": "SKIPPED_VALID"})
                continue
            if os.path.exists(report_path):
                # Immutable evidence is never overwritten or deleted. A repeated run
                # deterministically reports the same collision without fitting again.
                checkpoint = {"schema": SCHEMA, "channel": label,
                    "candidate_id": candidate_id, "fingerprint": fingerprint,
                    "config_hash": config_hash, "code_hash": code_hash,
                    "input_hash": material["input_hash"], "state": "INCOMPLETE",
                    "error_type": "InvalidExistingReport"}
                atomic_write_json(os.path.join(candidate_root, "checkpoint.json"), checkpoint)
                results.append({"channel": label, "candidate_id": candidate_id,
                                "state": "INCOMPLETE", "action": "COLLISION_PRESERVED"})
                continue
            if dry_run:
                results.append({"channel": label, "candidate_id": candidate_id,
                                "state": "PLANNED", "action": "DRY_RUN"})
                continue
            checkpoint = {"schema": SCHEMA, "channel": label,
                "candidate_id": candidate_id, "fingerprint": fingerprint,
                "config_hash": config_hash, "code_hash": code_hash,
                "input_hash": material["input_hash"], "state": "RUNNING"}
            atomic_write_json(os.path.join(candidate_root, "checkpoint.json"), checkpoint)
            try:
                payload = validate_public_result(
                    executor(label, material["candidates"][candidate_id],
                             material["context"]),
                    stage=config["stage"], candidate_id=candidate_id)
                report = {"schema": SCHEMA, "mission": config["mission"],
                    "stage": config["stage"], "channel": label,
                    "candidate_id": candidate_id, "policy": declaration["policy"],
                    "input_hash": material["input_hash"], "config_hash": config_hash,
                    "code_hash": code_hash,
                    "result": payload,
                    "batch_checkpoint": {"state": "COMPLETE", "fingerprint": fingerprint},
                    "scientific_scope": "NO_T2_NO_RANKING_NO_PLATEAU_NO_RECOMMENDATION_NO_APPLY"}
                report["integrity_sha256"] = _integrity(report)
                atomic_write_json(report_path, report, immutable=True)
                checkpoint["state"] = "COMPLETE"
                checkpoint["report_sha256"] = report["integrity_sha256"]
                state, action = "COMPLETE", "EXECUTED"
            except Exception as exc:  # isolate one candidate; do not leak paths/messages
                checkpoint["state"] = "INCOMPLETE"
                checkpoint["error_type"] = type(exc).__name__
                state, action = "INCOMPLETE", "FAILED_ISOLATED"
            atomic_write_json(os.path.join(candidate_root, "checkpoint.json"), checkpoint)
            results.append({"channel": label, "candidate_id": candidate_id,
                            "state": state, "action": action})
    counts = {state: sum(row["state"] == state for row in results)
              for state in ("COMPLETE", "INCOMPLETE", "PLANNED")}
    summary = {"schema": SCHEMA, "mission": config["mission"], "stage": config["stage"],
        "config_hash": config_hash, "code_hash": code_hash, "dry_run": bool(dry_run),
        "counts": counts, "candidates": results,
        "scientific_scope": "NO_T2_NO_RANKING_NO_PLATEAU_NO_RECOMMENDATION_NO_APPLY"}
    if not dry_run:
        summary_hash = canonical_json_hash(summary)
        summary["summary_sha256"] = summary_hash
        atomic_write_json(os.path.join(batch_dir, "summaries",
            f"summary-{summary_hash}.json"), summary, immutable=True)
    return summary
