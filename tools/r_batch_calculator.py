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

# near-0 dropout 스캔 제외 임계값(peak counts). 램프 off/셔터/취득 실패 시
# 스펙트럼 peak가 ≈0으로 찍히는데, 이를 ZA/He 평균에 넣으면 ratio가 깨져
# R이 비물리값이 된다. 정상 신호 peak는 보통 3만+ 이므로 1000은 dropout만
# 안전하게 걸러낸다(실데이터는 안 건드림). 필요시 caller가 올려 잡을 수 있다.
MIN_PEAK_INTENSITY = 1000.0

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
# Scan reader — RETIRED 2026-06-17.
# read_all_scans()는 core.data_io.read_scans_via_dataio 로 대체됨(data_io 단일파스+
# hk_shift T/P, 트렁케이트 정확 + 핫 실측 tempcell 온도). scan_directory·rt_precompute
# 모두 그쪽을 씀. 스펙트럼·스캔선택(MIN_PEAK·플래그 500/510)은 동일(검증 완료).
# ─────────────────────────────────────────────────────────────────────────────


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
    "save_r_dat",
    "ReflectanceCalculator",
]
