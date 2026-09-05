"""Run the minimal 3-window x 3-poly Fit Setting Explorer.

No ranking, plateau claim, GUI mutation, or Apply is performed.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timedelta

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.doas_fit import DoasFitter
from core.data_io import DataIO
from core import fit_explorer as FE
from tools import optimize_params as OP


def eligible_scan_rows(key):
    OP.require_key(key)
    pattern, day_filter = OP.CHAN_ALPHA[key]
    files = sorted(glob.glob(pattern))
    if day_filter:
        files = [p for p in files if os.path.basename(os.path.dirname(p)) in day_filter]
    return [row for path in files for row in DataIO.expand_to_scan_list(path)]


def selected_scan_rows(key, n=4, rows=None):
    rows = eligible_scan_rows(key) if rows is None else rows
    selected, indices = FE.select_representative_rows(rows, n)
    return selected, rows, indices


def alpha_row_metadata(path, row_index):
    """Read only identity metadata; never infer an acquisition state."""
    header, parts, comments = None, None, []
    data_index = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith("#"):
                comments.append(stripped[1:].strip())
            elif stripped.startswith("row_idx"):
                header = stripped.split("\t")
            elif stripped:
                if data_index == row_index:
                    parts = stripped.split("\t")
                    break
                data_index += 1
    if parts is None:
        raise ValueError("selected alpha row metadata is unavailable")
    dt, datetime_source = None, "unavailable"
    if header and parts and "datetime" in header:
        value = parts[header.index("datetime")].strip()
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt).isoformat(sep=" ")
                datetime_source = "alpha_header.datetime"
                break
            except ValueError:
                pass
    if dt is None:
        year = DataIO._file_year(path)
        if header and parts and "doy" in header and year is not None:
            try:
                parsed = datetime(year, 1, 1) + timedelta(
                    days=float(parts[header.index("doy")]) - 1.0)
                dt, datetime_source = parsed.isoformat(sep=" "), "alpha_header.doy+filename_year"
            except (ValueError, IndexError):
                pass
    state, state_source = "unknown", "unavailable"
    if any(c.lower() in {"state=ambient_average", "state: ambient_average"} for c in comments):
        state, state_source = "ambient_average", "alpha_comment.explicit_state"
    date, date_source = (dt[:10], datetime_source) if dt else (None, "unavailable")
    parent = os.path.basename(os.path.dirname(path))
    if date is None:
        try:
            date = datetime.strptime(parent, "%Y-%m-%d").date().isoformat()
            date_source = "parent_directory_iso_date"
        except ValueError:
            pass
    filename, digest = os.path.basename(path), FE.sha256_file(path)
    return {"id": f"{filename}#sha256={digest[:12]}#row={row_index}",
            "file": filename, "sha256": digest,
            "row_index": int(row_index), "datetime": dt,
            "date": date, "datetime_source": datetime_source, "date_source": date_source,
            "state": state, "state_source": state_source}


def sample_public_id(identity, population_index):
    return (f"pool={population_index}#file={identity['file']}#"
            f"sha256={identity['sha256']}#row={identity['row_index']}")


def sample_metadata_summary(scans, identities):
    known_states = {s["state"] for s in scans if s["state"] != "unknown"}
    any_unknown = any(s["state"] == "unknown" for s in scans)
    return {
        "date_counts": {d: sum(s["date"] == d for s in scans)
                        for d in sorted({s["date"] for s in scans if s["date"]})},
        "date_completeness": "COMPLETE" if all(s["date"] for s in scans) else "INCOMPLETE",
        "datetime_completeness": ("COMPLETE" if all(row["datetime"] for row in identities)
                                  else "INCOMPLETE"),
        "state_counts": {state: sum(s["state"] == state for s in scans)
                         for state in sorted({s["state"] for s in scans})},
        "state_completeness": "INCOMPLETE" if any_unknown else "COMPLETE",
        "distinct_state_count": len(known_states),
        "state_diversity": ("UNAVAILABLE" if any_unknown else
                            "DIVERSE" if len(known_states) > 1 else "NOT_DIVERSE"),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fitset")
    parser.add_argument("key", choices=sorted(OP.CHAN_ALPHA))
    parser.add_argument("--output", required=True)
    parser.add_argument("--window-step-nm", type=float, default=1.0)
    parser.add_argument("--overwrite", action="store_true")
    policy = parser.add_mutually_exclusive_group(required=True)
    policy.add_argument("--allow-negative-gas", action="store_true")
    policy.add_argument("--nonnegative-gas", action="store_true")
    args = parser.parse_args(argv)

    output = os.path.abspath(args.output)
    if os.path.exists(output) and not args.overwrite:
        raise SystemExit("ABSTAIN: output exists (pass --overwrite to replace it)")
    def abstain(reason, status="ABSTAIN"):
        FE.write_report(output, {"schema_version": FE.SCHEMA_VERSION, "status": status,
                                 "reason": reason, "candidates": [],
                                 "limitations": ["Preflight did not permit evaluation", "No Apply"]})
        raise SystemExit("ABSTAIN: " + reason)
    with open(args.fitset, encoding="utf-8") as fh:
        scenario = json.load(fh)
    cfg = OP.pick_channel(scenario, args.key)
    try:
        pool = eligible_scan_rows(args.key)
    except (OSError, RuntimeError, TypeError, ValueError):
        abstain("eligible alpha rows could not be discovered", "ABSTAIN_INCOMPLETE")
    protected_inputs = [args.fitset, cfg.get("wl_path", ""),
                        *[r.get("path", "") for r in cfg.get("refs", [])],
                        *[p for p, _ in pool]]
    try:
        FE.ensure_output_safe(output, protected_inputs)
    except ValueError as exc:
        raise SystemExit("ABSTAIN: " + str(exc)) from None
    stored_policy = cfg.get("allow_negative_gas")
    requested_policy = bool(args.allow_negative_gas)
    if type(stored_policy) is not bool:
        abstain("FitSet allow_negative_gas must be an exact bool")
    if stored_policy != requested_policy:
        abstain("CLI gas-sign policy conflicts with FitSet policy")

    eng = OP.build_engine_from_config(cfg)
    wave = np.asarray(eng._wave_axis, float).flatten()
    px_min, px_max, poly = int(cfg["f_min"]), int(cfg["f_max"]), int(cfg["poly_deg"])
    spacing = float(np.median(np.abs(np.diff(wave[px_min:px_max + 1]))))
    if not np.isfinite(spacing) or spacing <= 0:
        abstain("wavelength spacing unavailable")
    pixel_step = max(1, int(round(args.window_step_nm / spacing)))
    try:
        candidates = FE.neighboring_candidates(px_min, px_max, poly, pixel_step)
    except ValueError as exc:
        abstain(str(exc))
    if min(c["px_min"] for c in candidates) < 0 or max(c["px_max"] for c in candidates) >= len(wave):
        abstain("neighboring window leaves wavecal domain")

    ref_props = cfg.get("ref_props", {})
    try:
        starts = FE.controlled_starts(ref_props, "NO2", float(cfg.get("step_limit", .5)))
    except (ValueError, KeyError) as exc:
        abstain(str(exc))
    try:
        selected_rows, pool, selected_indices = selected_scan_rows(args.key, rows=pool)
    except (ValueError, OSError) as exc:
        abstain(str(exc), "ABSTAIN_INCOMPLETE")
    paths = [p for p, _ in selected_rows]
    file_paths = [args.fitset, cfg["wl_path"], *[r["path"] for r in cfg.get("refs", [])], *paths]
    try:
        FE.ensure_output_safe(output, file_paths)
    except ValueError as exc:
        raise SystemExit("ABSTAIN: " + str(exc)) from None
    scans = []
    sample_rows = []
    try:
        for population_index, (path, row_index) in zip(selected_indices, selected_rows):
            identity = alpha_row_metadata(path, row_index)
            identity["population_index"] = population_index
            identity["id"] = sample_public_id(identity, population_index)
            w, alpha, temp, pressure, px_start = DataIO.load_alpha_trace_row_mapped(path, row_index)
            if len(w) != len(alpha):
                raise ValueError("selected alpha coordinate lengths differ")
            scans.append({"id": identity["id"], "path": path,
                          "wave": w, "alpha": alpha, "T_C": float(temp),
                          "P_mbar": float(pressure), "px_start": px_start,
                          "date": identity["date"], "state": identity["state"]})
            sample_rows.append(identity)
    except (OSError, RuntimeError, TypeError, ValueError, IndexError):
        abstain("selected alpha row could not be read or validated", "ABSTAIN_INCOMPLETE")
    offsets = {s["px_start"] for s in scans}
    if len(offsets) != 1:
        abstain("representative scans have ambiguous detector pixel offsets")
    px_start = offsets.pop()
    for c in candidates:
        c["fit_px_min"], c["fit_px_max"] = c["px_min"] - px_start, c["px_max"] - px_start
    coordinate_problems = FE.validate_coordinates(wave, scans, candidates)
    if coordinate_problems:
        abstain("; ".join(coordinate_problems))
    for c in candidates:
        c["start_nm"] = float(scans[0]["wave"][c["fit_px_min"]])
        c["end_nm"] = float(scans[0]["wave"][c["fit_px_max"]])

    started = time.perf_counter()
    fitter = DoasFitter(eng)
    evaluated = [FE.evaluate_candidate(eng, fitter, ref_props, scans, c, starts,
                                       float(cfg.get("step_limit", .5)), requested_policy)
                 for c in candidates]
    report = {
        "schema_version": FE.SCHEMA_VERSION,
        "status": "EVALUATED_NO_PLATEAU_CLAIM",
        "provenance": {
            "git": FE.git_provenance(ROOT),
            "files": [{"path": os.path.abspath(p), "sha256": FE.sha256_file(p)} for p in file_paths],
            "channel_key": args.key, "wavecal_identity": cfg.get("wl_path"),
            "reference_order": [r["name"] for r in cfg.get("refs", [])],
            "sample_selection": {
                "contract": FE.STAGE1_SAMPLE_CONTRACT,
                "method": "sort canonical (realpath,row_index); floor(i*(N-1)/(k-1)), endpoints included",
                "requested": 4, "selected": len(selected_rows),
                "pool_files": len({os.path.realpath(p) for p, _ in pool}),
                "eligible_rows": len(pool), "selected_zero_based_indices": selected_indices,
                **sample_metadata_summary(scans, sample_rows),
                "samples": sample_rows},
            "executed_engine": {"gas_order": list(eng.gas_list),
                                "multipliers": {g: float(eng.multipliers[g]) for g in eng.gas_list},
                                "scaling_factors": {g: float(eng.scaling_factors[g]) for g in eng.gas_list}},
        },
        "policy": {"allow_negative_gas": requested_policy, "fit_sign": 1.0,
                   "window_bounds": "inclusive", "W": "identity",
                   "temperature_override_C": None, "temperature_source": "per alpha scan",
                   "etalon": {"detection_band_cycles_per_pixel": [0.02, 0.40],
                               "frequency": "detected per scan/candidate"},
                   "gate_tolerances": {"collinearity": {"value": 0.7,
                       "source": "core.fit_physics.COLLIN_HI_DEFAULT"},
                       "absolute_amount_ratio": {"value": 3.0,
                       "source": "core.fit_physics.judge_reference default"}}},
        "baseline": {"px_min": px_min, "px_max": px_max, "poly": poly,
                     "window_step_nm": args.window_step_nm, "pixel_step": pixel_step,
                     "step_limit": float(cfg.get("step_limit", .5)),
                     "ref_props": ref_props, "refs": cfg.get("refs", [])},
        "controlled_starts": starts,
        "budget": FE.stage1_budget(evaluated, len(scans), len(starts)),
        "scans": [{"id": s["id"], "T_C": s["T_C"], "P_mbar": s["P_mbar"],
                   "px_start": s["px_start"], "date": s["date"], "state": s["state"]} for s in scans],
        "candidates": evaluated,
        "seconds": time.perf_counter() - started,
        "limitations": ["Stage 0 PASS is preflight evidence only, even when fitting follows",
                        "Stage 0 pruning is an execution decision, not a scientific fit failure",
                        "This checkpoint fixes sampling and budget provenance; halving is not implemented",
                        "Original spectroscopy-file coverage is unavailable after engine interpolation",
                        "No candidate ranking", "No robustness plateau claim", "No Apply"],
    }
    report["status"] = FE.overall_status(evaluated)
    FE.write_report(output, report)
    print("candidate  window(px)     poly  exec         T2           conc median     rms/sig median")
    for row in evaluated:
        conc = row["metrics"]["conc"]["median"]
        rms = row["metrics"]["rms_sig"]["median"]
        print(f"{row['id']:9} {row['px_min']:4}-{row['px_max']:<4} {row['poly']:5}  "
              f"{row['execution_gate']['state']:12} {row['t2_gate']['state']:12} "
              f"{conc if conc is not None else 'n/a':>12} {rms if rms is not None else 'n/a':>16}")
    print(f"\nJSON: {os.path.abspath(args.output)}")
    return report


if __name__ == "__main__":
    main()
