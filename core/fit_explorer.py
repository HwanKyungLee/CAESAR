"""Minimal Fit Setting Explorer contracts (no ranking, plateau, or Apply)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time

import numpy as np

from core import fit_physics as FP
from core import param_optimizer as PO


SCHEMA_VERSION = 1


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


def controlled_starts(ref_props, target, step_limit):
    """Two starts from the common effective target bounds used by final VarPro."""
    props = ref_props.get(target, {})
    mode = props.get("sh_mode")
    if mode == "Center":
        center, half = map(float, str(props.get("sh_val", "")).split(","))
        global_lo, global_hi, anchor = center - abs(half), center + abs(half), center
    elif mode == "Limit":
        global_lo, global_hi = map(float, str(props.get("sh_val", "")).split(","))
        anchor = 0.0
    else:
        raise ValueError(f"target shift mode {mode!r} cannot provide controlled starts")
    if global_hi < global_lo:
        global_lo, global_hi = global_hi, global_lo
    step_limit = float(step_limit)
    lo, hi = max(global_lo, anchor - step_limit), min(global_hi, anchor + step_limit)
    if not np.isfinite([lo, hi, step_limit]).all() or hi <= lo:
        raise ValueError("invalid target shift bounds")
    sq = props.get("sq_val", "1.0")
    if props.get("sq_mode") == "Limit":
        slo, shi = map(float, str(sq).split(","))
        if abs(slo) < .5 and abs(shi) < .5:
            slo, shi = 1 + slo, 1 + shi
        sqs = (slo + .25 * (shi - slo), slo + .75 * (shi - slo))
    else:
        v = float(sq)
        sqs = (1 + v if abs(v) < .5 else v,) * 2
    margin = max(1e-5, np.finfo(float).eps * max(abs(lo), abs(hi), 1.0) * 16)
    usable_lo, usable_hi = lo + margin, hi - margin
    if usable_hi <= usable_lo or np.nextafter(usable_lo, np.inf) >= usable_hi:
        raise ValueError("effective target interval cannot support two distinct starts")
    shifts = (usable_lo + .25 * (usable_hi - usable_lo),
              usable_lo + .75 * (usable_hi - usable_lo))
    starts = [dict(id=f"seed{i}", shift=float(shifts[i]), squeeze=float(sqs[i]),
                   provenance="interior quartile of common effective target bounds") for i in range(2)]
    if starts[0]["shift"] == starts[1]["shift"] and starts[0]["squeeze"] == starts[1]["squeeze"]:
        raise ValueError("controlled starts are not distinct")
    return starts


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


def t2_tri_state(eng, candidate, successful_runs, target="NO2", expected_count=None):
    """Conservative adapter: a negative exclusion decision is never a PASS."""
    try:
        diag = FP.differential_collinearity(
            eng, list(eng.gas_list), candidate["px_min"], candidate["px_max"], candidate["poly"])
        multiple_r = finite_or_none(diag["multiple_R"].get(target))
    except Exception as exc:  # diagnostic failure is unavailable, not pass
        return {"state": "UNAVAILABLE", "reason": f"collinearity unavailable: {exc}"}
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


def evaluate_candidate(eng, fitter, ref_props, scans, candidate, starts,
                       step_limit, allow_negative_gas, target="NO2"):
    preflight = stage0_preflight(eng, candidate, target)
    if preflight["state"] != "PASS":
        return {**candidate,
                "evaluation_state": "UNEVALUATED",
                "stage0_preflight": preflight,
                "execution_gate": {"state": "NOT_RUN", "n_ok": 0, "n_fail": 0},
                "t2_gate": {"state": "UNAVAILABLE", "reason": "fit not run after Stage 0"},
                "metrics": {key: summary([]) for key in
                            ("conc", "rms_sig", "perr_rel", "autocorr1")},
                "runs": [], "failures": [], "seconds": 0.0}
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
                    controlled_start=(seed["shift"], seed["squeeze"]))
                rows.append({"scan_id": scan["id"], "seed_id": seed["id"], "T_C": scan["T_C"],
                             "P_mbar": scan["P_mbar"], "seconds": time.perf_counter() - t0,
                             "result": result})
            except Exception as exc:
                failures.append({"scan_id": scan["id"], "seed_id": seed["id"],
                                 "seconds": time.perf_counter() - t0,
                                 "error": f"{type(exc).__name__}: {exc}"})
    gate = ("PASS" if rows and not failures else "FAIL" if not rows else "UNAVAILABLE")
    vals = lambda key: [r["result"][key] for r in rows if np.isfinite(r["result"][key])]
    metrics = {key: summary(vals(key)) for key in ("conc", "rms_sig", "perr_rel", "autocorr1")}
    t2 = t2_tri_state(eng, candidate, rows, target, len(scans) * len(starts))
    state = ("EVALUATED_FAIL" if gate == "FAIL" or t2["state"] == "FAIL" else
             "INCOMPLETE" if gate == "UNAVAILABLE" else
             "EVALUATED_PASS" if t2["state"] == "PASS" else "EVALUATED_WITH_T2_UNAVAILABLE")
    out = {**candidate, "evaluation_state": state, "stage0_preflight": preflight,
           "execution_gate": {"state": gate, "n_ok": len(rows), "n_fail": len(failures)},
           "t2_gate": t2, "metrics": metrics,
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
    untracked = sorted(run("ls-files", "--others", "--exclude-standard").splitlines())
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
    if any(s == "INCOMPLETE" for s in states):
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
