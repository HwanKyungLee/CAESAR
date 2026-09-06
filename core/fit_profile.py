"""Diagnostic-only multi-start and fixed-grid profile utilities.

This module deliberately has no ranking, T2 verdict, or Apply path.  The
numeric fitting callback is injected by callers so the diagnostic can be
tested without real instrument files.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from typing import Callable, Iterable

import numpy as np

SCHEMA_VERSION = "fit-explorer-profile-v1"


def finite_grid(values, name):
    values = [float(v) for v in values]
    if not values or not np.all(np.isfinite(values)):
        raise ValueError(f"{name} grid must be finite and non-empty")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} grid must not contain duplicates")
    return sorted(values)


def grid_cells(shift_grid, squeeze_grid):
    """Return deterministic Cartesian cells, row-major by squeeze then shift."""
    shifts = finite_grid(shift_grid, "shift")
    squeezes = finite_grid(squeeze_grid, "squeeze")
    return [{"cell_id": f"s{si}_q{qi}", "shift": sh, "squeeze": sq,
             "grid_index": [si, qi]}
            for qi, sq in enumerate(squeezes) for si, sh in enumerate(shifts)]


def boundary_hits(result, bounds, *, tol=1e-8):
    """Report parameter boundary contacts without turning them into a verdict."""
    out = []
    for name in ("shift", "squeeze"):
        if name not in result or name not in bounds:
            continue
        value = float(result[name])
        lo, hi = map(float, bounds[name])
        if not np.isfinite(value) or not np.isfinite([lo, hi]).all() or hi <= lo:
            raise ValueError(f"invalid {name} result or bounds")
        span = hi - lo
        if abs(value - lo) <= max(tol, span * tol):
            out.append({"parameter": name, "side": "lower", "value": value,
                        "bound": lo})
        elif abs(value - hi) <= max(tol, span * tol):
            out.append({"parameter": name, "side": "upper", "value": value,
                        "bound": hi})
    return out


def source_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git_provenance(root):
    try:
        commit = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"],
                                         text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {"root": os.path.abspath(root), "commit": commit}


def run_profile(*, scan_identity, starts, shift_grid, squeeze_grid, bounds,
                fit_callback: Callable, fixed_fit_callback: Callable | None = None,
                allow_negative_gas: bool,
                source_files: Iterable[str] = (), provenance_root=None):
    """Run injected fits and return a path-safe diagnostic report.

    ``fit_callback(shift, squeeze, mode)`` must return finite metric values;
    it is called once per multi-start and once per fixed-grid cell.  No result
    is used to select or apply a setting.
    """
    if type(allow_negative_gas) is not bool:
        raise TypeError("allow_negative_gas must be an exact bool")
    if not scan_identity or "file" not in scan_identity or "row_index" not in scan_identity:
        raise ValueError("scan identity must include file and row_index")
    starts = [tuple(map(float, s)) for s in starts]
    if not starts or any(len(s) != 2 or not np.isfinite(s).all() for s in starts):
        raise ValueError("starts must be finite (shift, squeeze) pairs")
    cells = grid_cells(shift_grid, squeeze_grid)
    if fixed_fit_callback is None:
        raise ValueError("fixed_fit_callback is required for true fixed profiles")
    def checked(result, expected=None):
        result = dict(result)
        for key in ("rms_sig", "conc"):
            if key in result and result[key] is not None and not np.isfinite(float(result[key])):
                raise ValueError(f"nonfinite diagnostic metric: {key}")
        if expected is not None:
            for key, value in expected.items():
                if key in result and not np.isclose(float(result[key]), value, rtol=0, atol=1e-12):
                    raise ValueError(f"fixed profile changed {key}")
        return result
    multi = []
    for i, (shift, squeeze) in enumerate(starts):
        result = checked(fit_callback(shift, squeeze, "multi_start"))
        multi.append({"start_id": f"start_{i}", "initial": {"shift": shift, "squeeze": squeeze},
                      "result": result, "boundary_hits": boundary_hits(result, bounds)})
    fixed = []
    for cell in cells:
        result = checked(fixed_fit_callback(cell["shift"], cell["squeeze"], "fixed_grid"),
                         {"shift": cell["shift"], "squeeze": cell["squeeze"]})
        fixed.append({**cell, "result": result,
                      "boundary_hits": boundary_hits(result, bounds)})
    files = []
    for path in source_files:
        if not os.path.isfile(path):
            raise ValueError("source file is unavailable")
        files.append({"name": os.path.basename(path), "sha256": source_sha256(path)})
    return {"schema_version": SCHEMA_VERSION, "status": "DIAGNOSTIC_ONLY",
            "scan": dict(scan_identity),
            "policy": {"allow_negative_gas": allow_negative_gas},
            "bounds": {k: list(map(float, v)) for k, v in bounds.items()},
            "multi_start": multi, "fixed_grid": fixed,
            "provenance": {"files": files,
                           "git": git_provenance(provenance_root) if provenance_root else None},
            "limitations": ["No T2 verdict", "No ranking", "No plateau claim", "No Apply"]}
