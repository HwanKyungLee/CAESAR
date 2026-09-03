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

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.doas_fit import DoasFitter
from core.data_io import DataIO
from core import fit_explorer as FE
from tools import optimize_params as OP


def selected_scan_files(key, n=4):
    OP.require_key(key)
    pattern, day_filter = OP.CHAN_ALPHA[key]
    files = sorted(glob.glob(pattern))
    if day_filter:
        files = [p for p in files if os.path.basename(os.path.dirname(p)) in day_filter]
    if len(files) < n:
        raise SystemExit(f"ABSTAIN: representative alpha files {len(files)} < {n}: {pattern}")
    return files[::max(1, len(files) // n)][:n]


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
    def abstain(reason):
        FE.write_report(output, {"schema_version": FE.SCHEMA_VERSION, "status": "ABSTAIN",
                                 "reason": reason, "candidates": [],
                                 "limitations": ["Preflight did not permit evaluation", "No Apply"]})
        raise SystemExit("ABSTAIN: " + reason)
    with open(args.fitset, encoding="utf-8") as fh:
        scenario = json.load(fh)
    cfg = OP.pick_channel(scenario, args.key)
    pool_pattern, pool_dates = OP.CHAN_ALPHA[args.key]
    pool = sorted(glob.glob(pool_pattern))
    if pool_dates:
        pool = [p for p in pool if os.path.basename(os.path.dirname(p)) in pool_dates]
    protected_inputs = [args.fitset, cfg.get("wl_path", ""),
                        *[r.get("path", "") for r in cfg.get("refs", [])], *pool]
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
        paths = selected_scan_files(args.key)
    except SystemExit as exc:
        abstain(str(exc).removeprefix("ABSTAIN: "))
    file_paths = [args.fitset, cfg["wl_path"], *[r["path"] for r in cfg.get("refs", [])], *paths]
    try:
        FE.ensure_output_safe(output, file_paths)
    except ValueError as exc:
        raise SystemExit("ABSTAIN: " + str(exc)) from None
    scans = []
    for path in paths:
        w, alpha, temp, pressure, px_start = DataIO.load_alpha_trace_row_mapped(path, 0)
        if len(w) != len(alpha):
            raise SystemExit(f"ABSTAIN: alpha coordinate mismatch: {path}")
        scans.append({"id": os.path.relpath(path, ROOT).replace("\\", "/"), "path": path,
                      "wave": w, "alpha": alpha, "T_C": float(temp), "P_mbar": float(pressure),
                      "px_start": px_start,
                      "date": os.path.basename(os.path.dirname(path)), "state": "unknown"})
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
            "sample_selection": {"method": "sorted evenly spaced", "pool_size": len(pool),
                                 "indices": [pool.index(p) for p in paths],
                                 "dates": [s["date"] for s in scans],
                                 "states": [s["state"] for s in scans]},
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
        "scans": [{"id": s["id"], "T_C": s["T_C"], "P_mbar": s["P_mbar"],
                   "px_start": s["px_start"], "date": s["date"], "state": s["state"]} for s in scans],
        "candidates": evaluated,
        "seconds": time.perf_counter() - started,
        "limitations": ["No candidate ranking", "No robustness plateau claim", "No Apply"],
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
