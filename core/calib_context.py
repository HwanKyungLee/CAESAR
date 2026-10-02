"""core/calib_context.py — per-record calibration context (manuscript §6.1, 2026-10-03).

The fit uncertainty says nothing about how far a record sits from the zero-air (I₀) and
reflectivity (R) calibrations it was interpolated from. Per record:

    I0_dt_s, R_dt_s    seconds to the nearest knot
    I0_gap_h, R_gap_h  length of the bracketing knot interval (h); NaN outside the knot range
    I0_edge, R_edge    1 = outside the knot range (extrapolated: nearest knot held constant)

Unknown is NaN, never 0 (0 would claim "right on a knot").

Where the knot times come from, in order:
  1. the alpha file header — alpha generation writes the knots it actually used
     (`# I0_knot_sec=` / `# R_knot_sec=`, seconds from the start of the year, same axis as
     the doy column: sec = (doy − 1)·86400);
  2. `_calknots.json` in the alpha folder — for alphas made before 2026-10-03
     (tools/alpha_context_sidecar.py --write-knots builds it from raw + the R npz).

Self-check: python -m core.calib_context
"""
from __future__ import annotations

import json
import os

import numpy as np

SEC_PER_DAY = 86400.0
KNOT_TAGS = ("I0", "R")
SIDECAR = "_calknots.json"
COLUMNS = ("I0_dt_s", "I0_gap_h", "I0_edge", "R_dt_s", "R_gap_h", "R_edge")

_cache: dict = {}


def format_knot_line(tag: str, secs) -> str:
    """Header line for the alpha file (no trailing newline). Empty knots → '' (write nothing)."""
    if secs is None or len(secs) == 0:
        return ""
    return f"# {tag}_knot_sec=" + ",".join(f"{float(s):.3f}" for s in secs)


def context(sec, knots):
    """(nearest distance [s], bracketing interval [h], outside range?) for sorted-or-not knots."""
    sec = np.atleast_1d(np.asarray(sec, float))
    n = len(sec)
    if knots is None or len(knots) < 2:
        nan = np.full(n, np.nan)
        return nan, nan.copy(), np.zeros(n, bool)
    k = np.sort(np.asarray(knots, float))
    i = np.searchsorted(k, sec)
    lo = np.clip(i - 1, 0, len(k) - 1)
    hi = np.clip(i, 0, len(k) - 1)
    dt = np.minimum(np.abs(sec - k[lo]), np.abs(sec - k[hi]))
    edge = (sec < k[0]) | (sec > k[-1])
    gap = np.where(edge, np.nan, (k[hi] - k[lo]) / 3600.0)
    bad = ~np.isfinite(sec)
    dt[bad] = np.nan
    gap[bad] = np.nan
    return dt, gap, edge & ~bad


def _from_header(path):
    out = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("#"):
                break
            for tag in KNOT_TAGS:
                pre = f"# {tag}_knot_sec="
                if line.startswith(pre):
                    vals = [v for v in line[len(pre):].strip().split(",") if v]
                    out[tag] = np.array([float(v) for v in vals], float)
    return out


def _from_sidecar(path):
    sc = os.path.join(os.path.dirname(os.path.abspath(path)), SIDECAR)
    if not os.path.exists(sc):
        return {}
    with open(sc, encoding="utf-8") as fh:
        d = json.load(fh)
    return {tag: np.asarray(d[f"{tag}_knot_sec"], float)
            for tag in KNOT_TAGS if d.get(f"{tag}_knot_sec")}


def knots_for(path) -> dict:
    """{'I0': array, 'R': array} known for this alpha file (missing tags absent). Cached."""
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    hit = _cache.get(key)
    if hit is None:
        try:
            hit = _from_header(path)
            side = _from_sidecar(path)
            for tag in KNOT_TAGS:
                hit.setdefault(tag, side.get(tag))
            hit = {t: v for t, v in hit.items() if v is not None and len(v)}
        except Exception:      # noqa: BLE001 — context is advisory; never break a fit over it
            hit = {}
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = hit
    return hit


def row_context(path, sec) -> dict:
    """The six context columns for one record at `sec` (start-of-year seconds)."""
    k = knots_for(path)
    out = {}
    for tag in KNOT_TAGS:
        dt, gap, edge = context([sec], k.get(tag))
        out[f"{tag}_dt_s"] = float(dt[0])
        out[f"{tag}_gap_h"] = float(gap[0])
        out[f"{tag}_edge"] = int(edge[0]) if np.isfinite(dt[0]) else float("nan")
    return out


if __name__ == "__main__":
    dt, gap, edge = context([50, 3650, 9000, 99999], [0, 3600, 7200, 14400])
    assert np.allclose(dt[:3], [50, 50, 1800]) and np.allclose(gap[:3], [1, 1, 2])
    assert edge.tolist() == [False, False, False, True] and np.isnan(gap[3])
    assert np.isnan(context([1.0], None)[0][0])
    print("calib_context: OK")
