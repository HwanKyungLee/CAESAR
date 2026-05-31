"""tools/r_batch_calculator.py
==============================

System-wide constants and a flag-aware ZA/He scan reader for R-curve
computation.

This module used to hardcode column indices and the wrong flag values
(``FLAG_ZA=[502]`` instead of the stable ZA measurement flag ``500``).
It now delegates **all** raw-data layout knowledge to :mod:`core.raw_parser`,
which was verified against 2026-05 Yeosu campaign Cold + Hot files.

What changed (vs the pre-migration file)
----------------------------------------
* ``FLAG_ZA = [500]`` and ``FLAG_HE = [510]`` — the stable measurement
  windows, as documented in ``r_trend_monitor.py``'s docstring. Wait
  states (502/512) gave slightly different intensity (Cold: 42184 vs
  40068, ~5%) so using them inflated R noise.
* Cold pressure column corrected: was 6162 → now 6160.
* Cold cavity-T column corrected: was 6174 (spectrometer housing) →
  now 6173 (real cavity T).
* Hot ANs pressure separated from PNs: was both 6162 → now PNs=6162,
  ANs=6164.
* Hot temperature now points to the cell heater / gas T (col 6155,
  ~75 °C) which is what the Rayleigh extinction equation needs.
* Default paths moved off the missing ``D:\\`` to the current
  ``C:\\Doasis_Work\\raw,alpha_by_nam\\`` location, with a path-discovery
  helper so users on different machines aren't blocked.

The legacy module-level constants (``COL_PRESS_*``, ``SPEC_START_*`` etc.)
are kept so existing callers (``r_trend_monitor.py``, the GUI worker)
import-resolve without changes, but they are now thin aliases over
:mod:`core.raw_parser`.
"""
from __future__ import annotations

import os
import sys

import numpy as np

# Allow `python tools/r_batch_calculator.py` to find core/ from anywhere
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
if _root not in sys.path:
    sys.path.insert(0, _root)

from core.raw_parser import (  # noqa: E402
    FLAG_ZA   as _RP_FLAG_ZA,
    FLAG_HE   as _RP_FLAG_HE,
    SPEC_PRIMARY,
    SPEC_SECONDARY,
    P_SCALE,
)

try:
    from reflectance_calc import ReflectanceCalculator   # noqa: F401  (re-export for callers)
except ImportError:
    # The legacy fallback path. Don't sys.exit() — let the caller decide.
    ReflectanceCalculator = None   # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# Path discovery — find the campaign data wherever it lives this week
# ─────────────────────────────────────────────────────────────────────────────

def _first_existing(*paths: str) -> str:
    """Return the first path that exists on disk, else the last one."""
    for p in paths:
        if os.path.isdir(p) or os.path.isfile(p):
            return p
    return paths[-1]


COLD_DIR = _first_existing(
    r"C:\Doasis_Work\raw,alpha_by_nam\CAESAR_Cold\2026-05",
    r"D:\Yeosu_2026\CAESAR_Cold\2026-05",
    r"D:\CAESAR cold\2026-05",
)
HOT_DIR = _first_existing(
    r"C:\Doasis_Work\raw,alpha_by_nam\CAESAR_Hot\2026-05",
    r"D:\Yeosu_2026\CAESAR_Hot\2026-05",
    r"D:\CAESAR hot\2026-05",
)

# Wavelength calibration files — same fallback list pattern.
# Note: the most recent Cold calibration (2026-05-23) lives under the Hot
# folder tree, not under Cold/wv_cal, so we list it first.
WAVE_CAL_COLD = _first_existing(
    r"C:\Doasis_Work\raw,alpha_by_nam\CAESAR_Hot\CAESAR_calibration\CAESAR_cold\Calib_20260523_Hg_400-497nm_Poly2_cold.txt",
    r"C:\Doasis_Work\raw,alpha_by_nam\CAESAR_Cold\wv_cal\Calib_20260507_Hg_399-494nm_Poly2.txt",
    r"C:\Doasis_Work\test\1. Wavelength cal\Calib_20260523_Hg_400499nm_Poly2_cold.txt",
    r"D:\CAESAR cold\Calib_20260523_Hg_400-497nm_Poly2_cold.txt",
)
WAVE_CAL_HOT_PNS = _first_existing(
    r"C:\Doasis_Work\raw,alpha_by_nam\CAESAR_Hot\wv_cal\roi1\Calib_20260403_Hg_400-499nm(roi1).txt",
    r"C:\Doasis_Work\raw,alpha_by_nam\CAESAR_Hot\CAESAR_calibration\CAESAR_hot\roi1\Calib_20260403_Hg_400-499nm(roi1).txt",
    r"C:\Doasis_Work\test\1. Wavelength cal\Calib_20260403_Hg_400499nm_Poly2_roi1.txt",
    r"D:\CAESAR hot\roi1\Calib_20260403_Hg_400-499nm(roi1).txt",
)
WAVE_CAL_HOT_ANS = _first_existing(
    r"C:\Doasis_Work\raw,alpha_by_nam\CAESAR_Hot\wv_cal\roi2\Calib_20260403_Hg_400-499nm(roi2).txt",
    r"C:\Doasis_Work\raw,alpha_by_nam\CAESAR_Hot\CAESAR_calibration\CAESAR_hot\roi2\Calib_20260403_Hg_400-499nm(roi2).txt",
    r"C:\Doasis_Work\test\1. Wavelength cal\Calib_20260403_Hg_400499nm_Poly2_roi2.txt",
    r"D:\CAESAR hot\roi2\Calib_20260403_Hg_400-499nm(roi2).txt",
)


# ─────────────────────────────────────────────────────────────────────────────
# Physics constants (caller-tunable via r_trend_monitor)
# ─────────────────────────────────────────────────────────────────────────────

CAVITY_LEN = 51.8    # cm
RL_FACTOR  = 0.933

OUTPUT_DIR  = r"."
FILE_PATTERN = "*.dat"


# ─────────────────────────────────────────────────────────────────────────────
# Flag constants — use STABLE measurement windows, not transitional wait
# ─────────────────────────────────────────────────────────────────────────────

FLAG_ZA = [_RP_FLAG_ZA]    # = [500]
FLAG_HE = [_RP_FLAG_HE]    # = [510]


# ─────────────────────────────────────────────────────────────────────────────
# Legacy column-index aliases (kept for backward compatibility)
# ─────────────────────────────────────────────────────────────────────────────
# Cold layout: P at col 6160, T_cavity at col 6173.
# Hot  layout: P_PNs at 6162, P_ANs at 6164, gas T (heater setpoint) at 6155.

PIXEL_MIN = 0
PIXEL_MAX = None

# Cold
COL_PRESS_COLD = 6160
COL_TEMP_COLD  = 6173

# Hot — two cavities, separate pressures, shared gas temperature
COL_PRESS_HOT     = 6162   # default (= PNs)
COL_TEMP_HOT      = 6155   # cavity gas T setpoint, ~75 °C
COL_PRESS_HOT_PNS = 6162
COL_PRESS_HOT_ANS = 6164

# Spectrum slices (re-export from raw_parser for callers)
SPEC_START_DEFAULT = SPEC_PRIMARY[0]      # 2053
SPEC_END_DEFAULT   = SPEC_PRIMARY[1]      # 4101
SPEC_START_ANS     = SPEC_SECONDARY[0]    # 4101
SPEC_END_ANS       = SPEC_SECONDARY[1]    # 6149


# ─────────────────────────────────────────────────────────────────────────────
# File I/O
# ─────────────────────────────────────────────────────────────────────────────

def save_r_dat(out_path: str, wave, r_raw, r_fit, omr_d, fname, n_za, n_he) -> None:
    """Write per-file R(λ) curve (raw + 5-th order polynomial fit) to a .dat.

    Columns: wavelength_nm, R_raw, R_fitted, omr_d_cm-1, Leff_km.

    Header lines are all comment-prefixed so the file is round-trip safe
    with ``np.loadtxt(..., comments='#')`` and so the column-header row
    doesn't get parsed as data.
    """
    # Clip omr_d to a small positive value before inverting. Without this
    # the fitted polynomial can touch R=1 at the edges, sending omr_d→0
    # and Leff to 1e25 km, which then explodes any auto-scaled plot of
    # this column.  1e-9 cm^-1 corresponds to Leff ≈ 1000 km (well above
    # any real cavity), so clipping at that floor preserves the entire
    # physically interesting range and just caps the unphysical tail.
    omr_d_safe = np.maximum(np.asarray(omr_d, dtype=float), 1e-9)
    leff = 1.0 / omr_d_safe * 1e-5      # cm → km
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(f"# Source: {os.path.basename(fname)} (ZA:{n_za}, He:{n_he})\n")
        fh.write(f"# cavity={CAVITY_LEN}cm  RL={RL_FACTOR}\n")
        fh.write("# wavelength_nm\tR_raw\tR_fitted\tomr_d_cm-1\tLeff_km\n")
        for i in range(len(wave)):
            fh.write(
                f"{wave[i]:.4f}\t{r_raw[i]:.8f}\t{r_fit[i]:.8f}\t"
                f"{omr_d[i]:.6e}\t{leff[i]:.4f}\n"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Scan reader — flag-aware, channel-aware
# ─────────────────────────────────────────────────────────────────────────────

def read_all_scans(
    filepath: str,
    col_press: int = COL_PRESS_COLD,
    col_temp: int  = COL_TEMP_COLD,
    spec_start: int = SPEC_START_DEFAULT,
    spec_end: int   = SPEC_END_DEFAULT,
) -> tuple[list, list]:
    """Read every ZA (flag=500) and He (flag=510) row in one file.

    Returns ``(za_scans, he_scans)`` where each scan is the tuple
    ``(intensity_array, T_celsius, P_mbar)`` that
    :class:`ReflectanceCalculator` consumes.

    Parameters
    ----------
    filepath : str
        Path to a Mega-Matrix .dat file.
    col_press, col_temp : int
        Absolute column indices for the pressure and temperature
        sensors. Callers (Cold vs Hot, PNs vs ANs) pass the appropriate
        constants from above.
    spec_start, spec_end : int
        Spectrum slice (exclusive end). Defaults select the primary
        block (Cold NO2 / Hot PNs). Pass ``SPEC_START_ANS`` /
        ``SPEC_END_ANS`` for Hot ANs.

    Notes
    -----
    This function previously read flags **502 / 512** (transitional
    wait), which produced slightly biased ZA/He spectra. It now reads
    **500 / 510** — the stable measurement windows.
    """
    za: list = []
    he: list = []

    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            tokens = s.split("\t") if "\t" in s else s.split()
            if len(tokens) <= max(col_press, col_temp, spec_end - 1):
                continue
            try:
                flag = int(float(tokens[4]))
            except (ValueError, IndexError):
                continue
            if flag not in FLAG_ZA and flag not in FLAG_HE:
                continue

            # Spectrum
            try:
                intensity = np.fromiter(
                    (_safe_float(t) for t in tokens[spec_start:spec_end]),
                    dtype=float, count=spec_end - spec_start,
                )
            except ValueError:
                continue
            intensity = intensity[np.isfinite(intensity)]
            if intensity.size == 0:
                continue

            # T (°C) — fall back to 25.0 if sentinel
            t_raw = _safe_float(tokens[col_temp])
            t_c = t_raw / 100.0 if (np.isfinite(t_raw) and t_raw not in (0.0, 65535.0)) else 25.0

            # P (mbar) — fall back to 1013.25 if sentinel
            p_raw = _safe_float(tokens[col_press])
            p_mbar = (
                p_raw * P_SCALE
                if (np.isfinite(p_raw) and p_raw not in (0.0, 65535.0))
                else 1013.25
            )

            scan = (intensity, t_c, p_mbar)
            if flag in FLAG_ZA:
                za.append(scan)
            else:
                he.append(scan)

    return za, he


def _safe_float(s: str) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return float("nan")


__all__ = [
    # paths
    "COLD_DIR", "HOT_DIR",
    "WAVE_CAL_COLD", "WAVE_CAL_HOT_PNS", "WAVE_CAL_HOT_ANS",
    "OUTPUT_DIR", "FILE_PATTERN",
    # physics
    "CAVITY_LEN", "RL_FACTOR",
    # flags
    "FLAG_ZA", "FLAG_HE",
    # column constants (back-compat)
    "PIXEL_MIN", "PIXEL_MAX",
    "COL_PRESS_COLD", "COL_TEMP_COLD",
    "COL_PRESS_HOT",  "COL_TEMP_HOT",
    "COL_PRESS_HOT_PNS", "COL_PRESS_HOT_ANS",
    "SPEC_START_DEFAULT", "SPEC_END_DEFAULT",
    "SPEC_START_ANS",     "SPEC_END_ANS",
    # functions
    "save_r_dat", "read_all_scans",
    "ReflectanceCalculator",
]
