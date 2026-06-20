"""
gui/dr_nam_alpha_worker.py — Dr. Nam-compatible α(λ) export
============================================================

1:1 port of 박사님 MATLAB alpha pipeline so the output is bit-equivalent
(within floating-point tolerance) to::

    D:\\Yeosu_2026\\CAESAR_Hot\\alpha\\avg_60s\\
        ch1_YYYYMMDD_000000/ch1_YYYYMMDD_000NNN.dat   (1440 files / day)
        ch2_YYYYMMDD_000000/ch2_YYYYMMDD_000NNN.dat
        YYYY-MM-DD_avg_60s.mat                        (daily roll-up)

Source MATLAB scripts (D:\\Yeosu_2026\\CAESAR_Hot\\*.m):

  Step1_CAESAR_Hot_Yeosu_2026.m         raw .dat → daily .mat + CCD time-delay
  Step2_CAESAR_Hot_Yeosu_2026.m         orchestrator (Wv, Dark, Rs, Zs, Alpha)
  Rs_CAESAR_Hot_Yeosu_2026.m            R fit per He/ZA injection block
  Rs2_CAESAR_Hot_Yeosu_2026.m           R = 1 - d·(...) per-pixel + 5th-poly smooth
  Zs_CAESAR_Hot_Yeosu_2026.m            ZA injection block extraction (oneZ=1)
  Alpha_CAESAR_Hot_Yeosu_2026.m         60s avg → α = RL·(R+α_ref)·(I0/I-1) - (αs-αr)
  optimize_ZA_Rayleigh_Hot.m            optional: fit ZA Rayleigh A,B via fminsearch

Two modes
---------
mode = "drnam_mat":
    Phase 1.5 / Tier 1 — read 박사님 Rs_*.mat + Zs_*.mat as inputs and
    only recompute the Alpha.m step. Output is directly comparable
    pixel-by-pixel to 박사님 alpha_abs1/2 because the time grid (std_t),
    the R fit (alpha_cavity1/2_fit), and the ZA scans (Z1, Z2) are
    taken verbatim from 박사님 .mat files.

mode = "raw_full":  (Phase 2, not implemented yet)
    Full pipeline from raw .dat: implement Rs2.m + Zs.m ourselves.

Tracking: GitHub issue #23, PR #24.
"""
from __future__ import annotations

import os
import re
import glob
import datetime as _dt
from typing import Optional

import numpy as np
import pandas as pd
import scipy.io as sio
from scipy.interpolate import PchipInterpolator

from PyQt6.QtCore import QThread, pyqtSignal


# ── 박사님 constants extracted from .m files ─────────────────────────

# Dr. Nam HJ-measured ZA Rayleigh fit (Alpha.m:136, 138 — both channels)
HJ_ZA_RAYLEIGH_A = 1.100065008184610e-15   # cm² / molecule
HJ_ZA_RAYLEIGH_B = 4.165598772133079       # exponent (positive value; σ = A·λ^(-B))

# Per-channel RL (Step2 / Alpha.m:127 comment: ch1=0.9330 ch2=0.9950 ch3=0.9968)
# Hot CAESAR uses RL = 1 (line 127); Cold channels may differ.
DR_NAM_RL_DEFAULT_NON_HOT = {1: 0.9330, 2: 0.9950, 3: 0.9968}
DR_NAM_RL_DEFAULT_HOT     = {1: 1.0,    2: 1.0,    3: 1.0}

# Zeroing reference (Step2.m:95-96)
ZEROING_REF_PRESS_MBAR = 700.0
ZEROING_REF_TEMP_C     = 30.0

# Pressure raw-count → Pa conversion (Zs.m:64, Alpha.m:94)
PSI_TO_PA = 6894.73326
PRESS_COUNT_TO_PA_FACTOR = 0.01 * PSI_TO_PA   # raw_count → Pa  (~68.9473)

# Same factor expressed for mbar (matches r_batch_calculator's _P_SCALE)
PRESS_COUNT_TO_MBAR_FACTOR = PRESS_COUNT_TO_PA_FACTOR / 100.0

# Flags (Zs.m:17-18). Newer flag set first, legacy second.
FLAG_ZA_VALUES = (503, 500)
FLAG_HE_VALUES = (513, 510)

# Polyfit smoothing for R(λ) (Rs2.m:139-140)
R_POLYFIT_ORDER = 5

# Channel R-fit windows in nm (Hot Rs2.m:123-138)
CH_FIT_WINDOWS_NM_HOT = {
    1: (430.0, 465.0),   # PNs
    2: (435.0, 470.0),   # ANs
    3: (437.0, 472.0),
}

# ── Hot raw .dat column mapping ──────────────────────────────────────
# 박사님's read_data_CAESAR_Araon_2025_3ch.m (verified via screenshot
# 2026-05-29) defines the channel slices as:
#
#     ch1 = mm(:, 2048+6 : 2048+2048+5)         % MATLAB cols 2054..4101
#     ch2 = mm(:, 2048+2048+6 : 2048+2048+2048+5)
#     ch3 = mm(:, 6 : 2048+5)
#
# In 0-based Python:
#     ch1 → cols 2053..4100   (== r_batch_calculator's SPEC_START_DEFAULT)
#     ch2 → cols 4101..6148   (== SPEC_START_ANS .. SPEC_END_ANS)
#     ch3 → cols 5..2052
#
# Earlier (commit d544a72, 2026-05-28) we briefly used (1302, 3350) under
# the wrong assumption that 박사님's variable `ch1_1700` referred to pixel
# index 1700 of ch1. Alpha_CAESAR_Hot_Yeosu_2026.m line 212 is actually:
#     ch1_1700 = [ch1_1700; ch1(:, 950)];
# — the name "1700" is a legacy label and the data is pixel 950
# (1-based MATLAB) = pixel 949 (0-based Python). With ch1 base = col 2053
# and pixel 949, the brute-force hit at raw col 3002 still lines up:
# 2053 + 949 = 3002. So r_batch_calculator's original mapping was right
# all along and this commit restores it.
#
# Channel-to-cavity mapping on the Hot system:
#     ch1 (cols 2053..4100) → PNs cavity (NO2 absorption band 430-465 nm)
#     ch2 (cols 4101..6148) → ANs cavity (435-470 nm)
#     ch3 (cols 5..2052)    → unused on Hot
# The "NO2 / UV / PNs" comments in 박사님's read_data describe the
# Cold-system meaning of the same columns and must not be applied here.
HOT_CH_SPEC_COLS = {                 # (start, end_exclusive) in raw .dat columns
    1: (2053, 4101),                 # 박사님 ch1 = PNs cavity on Hot
    2: (4101, 6149),                 # 박사님 ch2 = ANs cavity on Hot
}
HOT_CH_PRESS_COL = {1: 6162, 2: 6164}
HOT_TEMP_COL     = 6155              # cell temperature, /100 → °C
HOT_FLAG_COL     = 4

# DOY conversion helpers (1 Jan = day 1.0)
def _datetime_to_doy(dt: _dt.datetime) -> float:
    """Convert a datetime to fractional day-of-year (1 Jan 00:00 = 1.0)."""
    start_of_year = _dt.datetime(dt.year, 1, 1)
    return (dt - start_of_year).total_seconds() / 86400.0 + 1.0


def _yyyymmdd_to_date(yyyymmdd: str) -> _dt.date:
    return _dt.date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))


class DrNamAlphaWorker(QThread):
    """
    Dr. Nam-compatible α export. Runs in a QThread so the GUI stays
    responsive during multi-day batches.

    Tier-1 entry point: ``mode="drnam_mat"`` reads 박사님 Rs_*.mat and
    Zs_*.mat from ``drnam_rszs_dir`` and re-computes the Alpha.m step
    using our raw .dat files. Output goes to ``output_dir`` in the
    same ch{N}_YYYYMMDD_000000/ structure 박사님 produces.

    Parameters
    ----------
    raw_dir : str
        Folder of raw .dat files for the campaign date.
    output_dir : str
        Where to write ch{N}_YYYYMMDD_000000/ folders and the daily .mat.
    wave_nm : np.ndarray, shape (n_pix,) per channel — pass a dict keyed
        by channel index, e.g. {1: wv_1, 2: wv_2}, or a single array
        which is reused for every channel.
    dark : dict[int, np.ndarray]
        Per-channel dark spectrum, keyed by channel index.
    drnam_rszs_dir : str
        Folder containing 박사님 Rs_YYYY-MM-DD.mat and Zs_YYYY-MM-DD.mat.
    date_yyyymmdd : str
        Target date (e.g. "20260520"). Used to locate Rs/Zs .mat and
        to filter raw files.
    avgsec : int, default 60
        Averaging window in seconds (박사님 default 60).
    channels : tuple[int, ...], default (1, 2)
        Which channels to export.
    system : "hot" | "cold", default "hot"
        Selects RL defaults and column mapping (Cold mapping in Phase 2).
    use_hj_za_rayleigh : bool, default True
        Use HJ-measured σ_ZA (Alpha.m:136,138). Set False to fall back
        to RayleighPhysics Sellmeier (slight physical difference).
    rl_per_channel : dict | None
        Override RL per channel. Defaults from `system`.
    use_260526_quirks : bool, default False
        Apply Alpha_Hot.m 260526 hot-fixes (tempcell2 := temppreh,
        presscell2 := presscell3). Hot data after 2026-05-26 needs this.
    std_t_from_drnam : bool, default True
        Use 박사님 ``std_t`` from the daily _avg_60s.mat (if available) as
        the canonical bin grid for 1:1 pixel comparison. If False, build
        the grid ourselves from raw .dat min/max DOY.
    max_files : int | None, default None
        Limit how many raw .dat files are read (set 1 for a fast
        single-file sanity test).  None = read all files for the date.

    Signals
    -------
    progress(int)         emitted 0..100 over the batch
    status_msg(str)       human-readable progress line
    finished(str)         output_dir on success, "ERROR: ..." on failure
    """

    progress    = pyqtSignal(int)
    status_msg  = pyqtSignal(str)
    finished    = pyqtSignal(str)

    # ── Construction ────────────────────────────────────────────────
    def __init__(
        self,
        raw_dir: str,
        output_dir: str,
        wave_nm,
        dark,
        *,
        drnam_rszs_dir: str = "",
        date_yyyymmdd: str = "",
        avgsec: int = 60,
        channels: tuple = (1, 2),
        system: str = "hot",
        mode: str = "drnam_mat",
        use_hj_za_rayleigh: bool = True,
        rl_per_channel: Optional[dict] = None,
        use_260526_quirks: bool = False,
        std_t_from_drnam: bool = True,
        max_files: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.raw_dir         = raw_dir
        self.output_dir      = output_dir
        self.drnam_rszs_dir  = drnam_rszs_dir
        self.date_yyyymmdd   = date_yyyymmdd
        self.avgsec          = int(avgsec)
        self.channels        = tuple(channels)
        self.system          = system.lower()
        self.mode            = mode
        self.use_hj_za_rayleigh = bool(use_hj_za_rayleigh)
        self.use_260526_quirks  = bool(use_260526_quirks)
        self.std_t_from_drnam   = bool(std_t_from_drnam)
        self.max_files          = max_files

        # Wave / dark normalised to per-channel dicts
        if isinstance(wave_nm, dict):
            self.wave_nm = {int(k): np.asarray(v, dtype=float) for k, v in wave_nm.items()}
        else:
            arr = np.asarray(wave_nm, dtype=float)
            self.wave_nm = {c: arr for c in self.channels}
        if isinstance(dark, dict):
            self.dark = {int(k): np.asarray(v, dtype=float) for k, v in dark.items()}
        else:
            arr = np.asarray(dark, dtype=float)
            self.dark = {c: arr for c in self.channels}

        if rl_per_channel is not None:
            self.rl_per_channel = dict(rl_per_channel)
        elif self.system == "hot":
            self.rl_per_channel = dict(DR_NAM_RL_DEFAULT_HOT)
        else:
            self.rl_per_channel = dict(DR_NAM_RL_DEFAULT_NON_HOT)

        self.is_running = True

    # ── Public API ──────────────────────────────────────────────────
    def stop(self) -> None:
        self.is_running = False

    def run(self) -> None:
        """Orchestrate the full pipeline. Currently supports mode='drnam_mat'."""
        try:
            if self.mode != "drnam_mat":
                self.finished.emit(
                    f"ERROR: mode={self.mode!r} not implemented yet "
                    f"(only 'drnam_mat' is wired up — see issue #23 Phase 2)."
                )
                return
            self._run_drnam_mat_mode()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.finished.emit(f"ERROR: {exc!r}")

    def _run_drnam_mat_mode(self) -> None:
        date = self.date_yyyymmdd
        if not date:
            raise ValueError("date_yyyymmdd is required in drnam_mat mode.")
        date_dashed = f"{date[:4]}-{date[4:6]}-{date[6:8]}"

        # 1. Load 박사님 Rs and Zs
        self._emit_status(f"Loading reference Rs/Zs .mat for {date_dashed}…")
        rs = self._load_dr_nam_rs_mat(
            os.path.join(self.drnam_rszs_dir, f"Rs_{date_dashed}.mat")
        )
        zs = self._load_dr_nam_zs_mat(
            os.path.join(self.drnam_rszs_dir, f"Zs_{date_dashed}.mat")
        )

        # 2. Build the std_t bin grid
        if self.std_t_from_drnam:
            ref_alpha_path = self._find_drnam_alpha_mat(date_dashed)
            if ref_alpha_path:
                ref = self._load_dr_nam_alpha_mat(ref_alpha_path)
                std_t = ref["std_t"]
                self._emit_status(
                    f"Using reference std_t bin grid: {len(std_t)} bins "
                    f"(DOY {std_t[0]:.4f} ~ {std_t[-1]:.4f})"
                )
            else:
                std_t = self._build_std_t_from_rs_zs(rs["doy_R"], zs["doy_z"])
                self._emit_status(
                    f"reference _avg_60s.mat not found, built std_t locally: "
                    f"{len(std_t)} bins"
                )
        else:
            std_t = self._build_std_t_from_rs_zs(rs["doy_R"], zs["doy_z"])

        # 3. Load raw .dat data for the date
        if self.max_files is not None:
            self._emit_status(
                f"Reading raw .dat scans (LIMITED to first {self.max_files} files)…"
            )
        else:
            self._emit_status("Reading raw .dat scans (ch1, ch2, HK, doy_per_row)…")
        raw = self._load_raw_dat_full(date_dashed, max_files=self.max_files)

        # 4. For each channel, time-interpolate R / Z / ρ_za onto std_t, bin
        #    raw I per std_t, and apply the Alpha.m formula.
        all_alpha = {}
        all_meta  = {"std_t": std_t}
        n_pix = len(self.wave_nm[self.channels[0]])

        for ch in self.channels:
            self._emit_status(f"Computing α for channel {ch}…")
            alpha_2d, meta = self._compute_alpha_per_bin(
                ch=ch,
                std_t=std_t,
                rs=rs,
                zs=zs,
                raw=raw,
            )
            all_alpha[ch] = alpha_2d
            all_meta[f"rho_avg{ch}"]     = meta["rho_avg"]
            all_meta[f"flag_avg"]        = meta.get("flag_avg", all_meta.get("flag_avg"))
            all_meta[f"tempcell{ch}{ch}"] = meta["tempcell_avg"]
            all_meta[f"presscell{ch}{ch}"] = meta["presscell_avg_mbar"]

        # 5. Write per-bin .dat files in ch{N}_YYYYMMDD_000000/
        n_files = 0
        for ch in self.channels:
            n_files += self._save_dr_nam_folder(all_alpha[ch], ch, date)
        self._emit_status(f"Wrote {n_files} per-bin .dat files.")

        # 6. Write the daily _avg_60s.mat roll-up
        all_meta["doy"]   = raw["doy_per_row"]
        all_meta["doy_z"] = zs["doy_z"]
        all_meta["doy_R"] = rs["doy_R"]
        for ch in self.channels:
            all_meta[f"alpha_abs{ch}"] = all_alpha[ch]
        # ch1_1700 is the raw pixel-1700 (~445 nm) time series for ch=1
        if 1 in self.channels and "ch1_full" in raw:
            all_meta["ch1_1700"] = raw["ch1_full"][:, 1700].astype(np.uint16)

        mat_path = self._save_daily_mat(all_meta, date_dashed)
        self._emit_status(f"Saved daily roll-up: {mat_path}")

        self.finished.emit(self.output_dir)

    # ── 박사님 .mat loaders ─────────────────────────────────────────
    def _load_dr_nam_rs_mat(self, path: str) -> dict:
        """Returns dict with doy_R (n_inj,), alpha_cavity1_fit (2048, n_inj),
        alpha_cavity2_fit (2048, n_inj). Mirrors what Alpha.m line 32/40 read."""
        m = sio.loadmat(path, squeeze_me=True)
        return {
            "doy_R":             np.asarray(m["doy_R"],             dtype=float),
            "alpha_cavity1_fit": np.asarray(m["alpha_cavity1_fit"], dtype=float),
            "alpha_cavity2_fit": np.asarray(m["alpha_cavity2_fit"], dtype=float),
        }

    def _load_dr_nam_zs_mat(self, path: str) -> dict:
        """Returns Z1, Z2 (n_za, 2048), rho_z1, rho_z2 (n_za,), doy_z (n_za,).
        Mirrors what Alpha.m line 44-46 reads from Zs.mat."""
        m = sio.loadmat(path, squeeze_me=True)
        return {
            "doy_z":  np.asarray(m["doy_z"],  dtype=float),
            "Z1":     np.asarray(m["Z1"],     dtype=float),
            "Z2":     np.asarray(m["Z2"],     dtype=float),
            "rho_z1": np.asarray(m["rho_z1"], dtype=float),
            "rho_z2": np.asarray(m["rho_z2"], dtype=float),
        }

    def _find_drnam_alpha_mat(self, date_dashed: str) -> Optional[str]:
        """Locate 박사님 daily roll-up .mat to import std_t (for 1:1 comparison)."""
        # Common locations 박사님 uses
        candidates = [
            os.path.join(os.path.dirname(self.drnam_rszs_dir), "alpha",
                         f"avg_{self.avgsec}s", f"{date_dashed}_avg_{self.avgsec}s.mat"),
            os.path.join(os.path.dirname(os.path.dirname(self.drnam_rszs_dir)),
                         "alpha", f"avg_{self.avgsec}s",
                         f"{date_dashed}_avg_{self.avgsec}s.mat"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return None

    def _load_dr_nam_alpha_mat(self, path: str) -> dict:
        m = sio.loadmat(path, squeeze_me=True)
        return {
            "std_t":      np.asarray(m["std_t"],      dtype=float),
            "alpha_abs1": np.asarray(m["alpha_abs1"], dtype=float),
            "alpha_abs2": np.asarray(m["alpha_abs2"], dtype=float),
            "rho_avg1":   np.asarray(m["rho_avg1"],   dtype=float),
            "rho_avg2":   np.asarray(m["rho_avg2"],   dtype=float),
        }

    # ── std_t builder ────────────────────────────────────────────────
    def _build_std_t_from_rs_zs(self, doy_R: np.ndarray, doy_z: np.ndarray) -> np.ndarray:
        """Alpha.m:25 — std_t_temp = min(doy):avgsec/86400:max(doy).
        We use the overlap of doy_R and doy_z to bound the grid."""
        lo = max(float(np.nanmin(doy_R)), float(np.nanmin(doy_z)))
        hi = min(float(np.nanmax(doy_R)), float(np.nanmax(doy_z)))
        return np.arange(lo, hi, self.avgsec / 86400.0)

    # ── Raw .dat loader (ch1, ch2 spectra + HK + per-row DOY) ────────
    def _load_raw_dat_full(self, date_dashed: str,
                           max_files: Optional[int] = None) -> dict:
        """Read raw .dat for the date and stack ch1/ch2 spectra and HK.
        Uses pandas C-engine + usecols for ~20-30× speedup vs line-by-line.

        Returns:
            doy_per_row     (N,)         fractional day-of-year per scan
            flag            (N,)         scan flag (col 4)
            ch1_full        (N, 2048)    raw ch1 spectrum (intensity counts)
            ch2_full        (N, 2048)    raw ch2 spectrum
            tempcell{1,2}   (N,)         raw temp count
            presscell{1,2,3}(N,)         raw press counts (3 needed for 260526)

        DOY conversion: file mtime → date + (col1 centiseconds offset).
        col1 wraps every ~10.9 min so we monotonise by detecting drops > 3600
        centisec and adding one cycle (~14.4 min) per wrap.
        """
        if self.system != "hot":
            raise NotImplementedError("Only Hot column mapping wired up (Phase 2 for Cold).")

        files = sorted(glob.glob(os.path.join(self.raw_dir, f"{date_dashed}-*.dat")))
        if max_files is not None:
            files = files[: int(max_files)]
        if not files:
            raise FileNotFoundError(
                f"No raw .dat matching {date_dashed}-*.dat in {self.raw_dir}"
            )

        s1, e1 = HOT_CH_SPEC_COLS[1]
        s2, e2 = HOT_CH_SPEC_COLS[2]
        c_p1   = HOT_CH_PRESS_COL[1]
        c_p2   = HOT_CH_PRESS_COL[2]
        c_p3   = HOT_CH_PRESS_COL.get(3, 6166)
        c_t    = HOT_TEMP_COL
        c_flag = HOT_FLAG_COL

        spec1_cols = list(range(s1, e1))   # 2048 cols
        spec2_cols = list(range(s2, e2))
        hk_cols    = [0, 1, c_flag, c_t, c_p1, c_p2, c_p3]   # 0,1 = bytepack 시각 상·하위워드
        usecols    = sorted(set(hk_cols + spec1_cols + spec2_cols))

        chunks = []
        for fp in files:
            self._emit_status(f"  read {os.path.basename(fp)} (pandas C-engine)…")
            try:
                df = pd.read_csv(
                    fp,
                    sep="\t", header=None, engine="c",
                    usecols=usecols,
                    dtype=np.float64,
                    on_bad_lines="skip",
                    na_values=["", "nan", "NaN"],
                    low_memory=False,
                )
            except Exception as exc:
                self._emit_status(f"    skip ({exc!r})")
                continue
            if df.empty:
                continue

            # Filter rows: 유효 col1(0 < centi < 86400) and finite
            centi = df[1].to_numpy()
            mask = np.isfinite(centi) & (centi > 0.0) & (centi < 86400.0)
            if not mask.any():
                continue
            df = df.loc[mask].reset_index(drop=True)

            # DOY = bytepack((col0<<16)|col1)/100/86400 + 1  (박사님 doy/std_t와 동일).
            # col0(상위워드)가 wrap을 담당하므로 수동 wrap 보정·mtime 앵커 불필요.
            c0 = df[0].to_numpy()
            c1 = df[1].to_numpy()
            bp = (c0.astype(np.int64) << 16) | (c1.astype(np.int64) & 0xFFFF)
            secs = bp.astype(np.float64) / 100.0
            doy = secs / 86400.0 + 1.0

            # Slice spectra (pandas keeps column labels = original col indices)
            ch1 = df.loc[:, spec1_cols].to_numpy(dtype=np.float64)
            ch2 = df.loc[:, spec2_cols].to_numpy(dtype=np.float64)
            flag_arr = df[c_flag].to_numpy(dtype=np.int32)
            t1_arr = df[c_t].to_numpy()
            t2_arr = df[c_t].to_numpy()   # Hot uses one temp probe
            p1_arr = df[c_p1].to_numpy()
            p2_arr = df[c_p2].to_numpy()
            p3_arr = df[c_p3].to_numpy()

            chunks.append({
                "doy": doy,   "flag": flag_arr,
                "ch1": ch1,   "ch2": ch2,
                "t1": t1_arr, "t2": t2_arr,
                "p1": p1_arr, "p2": p2_arr, "p3": p3_arr,
            })

        if not chunks:
            raise RuntimeError(f"No usable scans for {date_dashed}.")

        return {
            "doy_per_row": np.concatenate([c["doy"]  for c in chunks]),
            "flag":        np.concatenate([c["flag"] for c in chunks]),
            "ch1_full":    np.vstack([c["ch1"] for c in chunks]),
            "ch2_full":    np.vstack([c["ch2"] for c in chunks]),
            "tempcell1":   np.concatenate([c["t1"] for c in chunks]),
            "tempcell2":   np.concatenate([c["t2"] for c in chunks]),
            "presscell1":  np.concatenate([c["p1"] for c in chunks]),
            "presscell2":  np.concatenate([c["p2"] for c in chunks]),
            "presscell3":  np.concatenate([c["p3"] for c in chunks]),
        }

    # ── ZA Rayleigh σ (Alpha.m:136,138) ──────────────────────────────
    def _za_sigma_rayleigh(self, wave_nm: np.ndarray) -> np.ndarray:
        """σ_ZA(λ) [cm²/molecule]. HJ measurement (Alpha.m:136,138) by default.

        Both channels use the same HJ Ch1 expression because that's what
        Alpha.m line 136 and 138 actually write — Ch2's separate fit is
        commented out (line 141)."""
        if self.use_hj_za_rayleigh:
            return HJ_ZA_RAYLEIGH_A * wave_nm ** (-HJ_ZA_RAYLEIGH_B)
        # Sellmeier fallback via RayleighPhysics (slight physical difference)
        from core.physics import RayleighPhysics
        # get_alpha_rayleigh returns α [cm⁻¹] given T/P. We want σ alone so
        # divide by N at the same (T, P) — but caller multiplies by ρ again,
        # so canceling is fine. Use STP and divide by N₀.
        alpha_stp = RayleighPhysics.get_alpha_rayleigh(
            np.asarray(wave_nm, dtype=float), 0.0, 1013.25, "zero_air"
        )
        N0 = 2.6867811e19
        return alpha_stp / N0

    # ── PCHIP helper (per-pixel time interpolation) ──────────────────
    def _pchip_along_time(self, t_known: np.ndarray, y_known: np.ndarray,
                          t_target: np.ndarray) -> np.ndarray:
        """Interpolate y_known(t_known) onto t_target with PCHIP.

        If y_known is 2-D shaped (n_pix, n_time), interpolate each pixel
        column independently and return (n_target, n_pix) — matching
        Alpha.m's R*_interp shape."""
        t_known = np.asarray(t_known, dtype=float)
        order   = np.argsort(t_known)
        t_known = t_known[order]
        y       = np.asarray(y_known, dtype=float)

        if y.ndim == 1:
            y = y[order]
            mask = np.isfinite(t_known) & np.isfinite(y)
            if mask.sum() < 2:
                return np.full_like(t_target, np.nan)
            return PchipInterpolator(t_known[mask], y[mask], extrapolate=True)(t_target)

        # 2-D: assume shape (n_pix, n_time). Sort along time axis (columns).
        if y.shape[1] != t_known.size:
            # Try the other convention (n_time, n_pix) and transpose.
            if y.shape[0] == t_known.size:
                y = y.T
            else:
                raise ValueError(
                    f"y_known shape {y.shape} does not match t_known size {t_known.size}"
                )
        y = y[:, order]
        n_pix = y.shape[0]
        out = np.empty((t_target.size, n_pix), dtype=float)
        for ip in range(n_pix):
            col = y[ip, :]
            mask = np.isfinite(col)
            if mask.sum() < 2:
                out[:, ip] = np.nan
                continue
            out[:, ip] = PchipInterpolator(
                t_known[mask], col[mask], extrapolate=True
            )(t_target)
        return out

    # ── Core: Alpha.m per-bin calculation ────────────────────────────
    def _compute_alpha_per_bin(self, *, ch: int, std_t: np.ndarray,
                                rs: dict, zs: dict, raw: dict) -> tuple:
        """Compute α(bin, pixel) per channel — 1:1 port of Alpha.m:72-163."""
        wv = self.wave_nm[ch]
        dark = self.dark[ch]
        RL = float(self.rl_per_channel.get(ch, 1.0))
        n_bins = std_t.size
        n_pix  = wv.size

        # ── Interpolate R / Z / ρ_za onto std_t bins (Alpha.m:32-46) ──
        alpha_cav_fit = rs[f"alpha_cavity{ch}_fit"]   # shape may be (2048, n_inj) or (n_inj, 2048)
        if alpha_cav_fit.shape[0] != n_pix and alpha_cav_fit.shape[1] == n_pix:
            alpha_cav_fit = alpha_cav_fit.T
        R_interp = self._pchip_along_time(rs["doy_R"], alpha_cav_fit, std_t)   # (n_bins, n_pix)

        Z_known = zs[f"Z{ch}"]                      # (n_za, 2048)
        if Z_known.shape[0] != n_pix and Z_known.shape[1] == n_pix:
            Z_t = Z_known.T                         # → (n_pix, n_za)
        else:
            Z_t = Z_known                           # already (n_pix, n_za)
        Z_interp = self._pchip_along_time(zs["doy_z"], Z_t, std_t)             # (n_bins, n_pix)

        rho_za = self._pchip_along_time(zs["doy_z"], zs[f"rho_z{ch}"], std_t)  # (n_bins,)

        # ── Bin raw I and HK per std_t (Alpha.m:74-114) ──────────────
        doy_row = raw["doy_per_row"]
        ch_full = raw[f"ch{ch}_full"]              # (N_row, n_pix)

        # If raw spectra width != n_pix, slice/expand to match wv
        if ch_full.shape[1] != n_pix:
            m = min(ch_full.shape[1], n_pix)
            if ch_full.shape[1] > n_pix:
                ch_full = ch_full[:, :n_pix]
            else:
                pad = np.full((ch_full.shape[0], n_pix - ch_full.shape[1]), np.nan)
                ch_full = np.concatenate([ch_full, pad], axis=1)

        # Pressure raw → Pa (NaN-aware). 260526 quirk: ch2 → ch3 pressure.
        if ch == 2 and self.use_260526_quirks:
            press_raw = raw["presscell3"]
        else:
            press_raw = raw[f"presscell{ch}"]
        press_pa = self._press_count_to_pa(press_raw)

        # Default to 1 atm where all NaN (Alpha.m:100-104)
        if np.all(np.isnan(press_pa)):
            press_pa = np.full_like(press_pa, 101325.0)

        temp_raw = raw[f"tempcell{ch}"]
        # T_C = raw / 100  (Alpha.m:112)
        temp_c = temp_raw / 100.0

        I_avg          = np.full((n_bins, n_pix), np.nan)
        rho_avg        = np.full(n_bins, np.nan)
        tempcell_avg   = np.full(n_bins, np.nan)
        presscell_mbar = np.full(n_bins, np.nan)
        flag_avg       = np.full(n_bins, np.nan)

        flag = raw["flag"].astype(float)
        bin_width = self.avgsec / 86400.0
        last_valid_dt_st = None

        for i, t0 in enumerate(std_t):
            t1 = t0 + bin_width
            sel = (doy_row >= t0) & (doy_row < t1)
            j_idx = np.where(sel)[0]
            if j_idx.size < 3:
                # Alpha.m:76-79 — skip bin, only timestamp propagates
                continue
            I_avg[i, :]          = np.nanmean(ch_full[j_idx, :], axis=0) - dark
            t_k_mean             = np.nanmean(temp_c[j_idx] + 273.15)
            p_pa_mean            = np.nanmean(press_pa[j_idx])
            rho_avg[i]           = self._air_number_density(t_k_mean, p_pa_mean)
            tempcell_avg[i]      = np.nanmean(temp_c[j_idx])
            presscell_mbar[i]    = np.nanmean(press_raw[j_idx]) * PRESS_COUNT_TO_MBAR_FACTOR
            flag_avg[i]          = np.nanmean(flag[j_idx])

        # ── Apply Alpha.m formula (line 152) ─────────────────────────
        sigma_za = self._za_sigma_rayleigh(wv)                              # (n_pix,)
        alpha_ref     = sigma_za[None, :] * rho_za[:, None]                  # (n_bins, n_pix)
        alpha_sample  = sigma_za[None, :] * rho_avg[:, None]                 # (n_bins, n_pix)

        # Guard divide-by-zero: I_avg ≤ 0 → NaN → α = NaN → cleaned to 0 below
        safe_I = np.where(I_avg > 0, I_avg, np.nan)
        ratio  = Z_interp / safe_I - 1.0

        alpha_abs = RL * (R_interp + alpha_ref) * ratio - (alpha_sample - alpha_ref)

        # Alpha.m:161-163 — Inf / NaN → 0
        alpha_abs = np.where(np.isfinite(alpha_abs), alpha_abs, 0.0)

        meta = {
            "rho_avg":            rho_avg,
            "tempcell_avg":       tempcell_avg,
            "presscell_avg_mbar": presscell_mbar,
            "flag_avg":           flag_avg,
        }
        return alpha_abs, meta

    # ── Output: per-bin .dat files (Alpha.m:170-202 + write_alpha) ───
    def _save_dr_nam_folder(self, alpha_2d: np.ndarray, ch: int,
                            date_yyyymmdd: str) -> int:
        fld = os.path.join(self.output_dir, f"ch{ch}_{date_yyyymmdd}_000000")
        os.makedirs(fld, exist_ok=True)
        n_bins = alpha_2d.shape[0]
        for i in range(n_bins):
            scan = i + 1
            fname = f"ch{ch}_{date_yyyymmdd}_{scan:06d}.dat"
            path = os.path.join(fld, fname)
            # 박사님 write_alpha: one α per line, scientific notation
            # Reverse-engineered from sample file: leading 7-space indent,
            # %.6e, blank line between values.
            with open(path, "w", encoding="ascii") as fh:
                for v in alpha_2d[i, :]:
                    fh.write(f"       {v:.6e}\n\n")
        return n_bins

    def _save_daily_mat(self, all_meta: dict, date_dashed: str) -> str:
        path = os.path.join(self.output_dir, f"{date_dashed}_avg_{self.avgsec}s.mat")
        sio.savemat(path, all_meta, do_compression=True)
        return path

    # ── Comparison helper (validation aid) ───────────────────────────
    def _compare_to_dr_nam(self, our_alpha_2d: np.ndarray, ch: int,
                           date_dashed: str) -> Optional[dict]:
        """Pixel-wise RMS / max-abs diff against 박사님 alpha_abs{ch}.
        Returns None if 박사님 .mat is not found."""
        ref_path = self._find_drnam_alpha_mat(date_dashed)
        if not ref_path:
            return None
        ref = self._load_dr_nam_alpha_mat(ref_path)
        their = ref[f"alpha_abs{ch}"]
        n = min(our_alpha_2d.shape[0], their.shape[0])
        diff = our_alpha_2d[:n, :] - their[:n, :]
        return {
            "n_bins":     n,
            "rms":        float(np.sqrt(np.nanmean(diff ** 2))),
            "max_abs":    float(np.nanmax(np.abs(diff))),
            "ref_rms":    float(np.sqrt(np.nanmean(their[:n, :] ** 2))),
            "rel_rms":    float(
                np.sqrt(np.nanmean(diff ** 2)) /
                max(1e-30, np.sqrt(np.nanmean(their[:n, :] ** 2)))
            ),
        }

    # ── Internals (already wired up for both modes) ──────────────────
    @staticmethod
    def _press_count_to_pa(raw_count) -> np.ndarray:
        """Zs.m:64 — psi count → Pa. 65535 / 0 → NaN."""
        arr = np.asarray(raw_count, dtype=float)
        invalid = (arr == 65535) | (arr == 0)
        arr = np.where(invalid, np.nan, arr)
        return arr * PRESS_COUNT_TO_PA_FACTOR

    @staticmethod
    def _air_number_density(temp_k, press_pa) -> float:
        """fun_air equivalent — N(T, P) in molecules/cm³.

        박사님 fun_air confirmed (RayleighPhysics docstring) to use
        Loschmidt N₀ = 2.6867811e19, identical to our convention.
        """
        N0      = 2.6867811e19
        T0_K    = 273.15
        P0_MBAR = 1013.25
        P0_PA   = P0_MBAR * 100.0
        return N0 * (np.asarray(press_pa) / P0_PA) * (T0_K / np.asarray(temp_k))

    def _emit_status(self, msg: str) -> None:
        try:
            self.status_msg.emit(msg)
        except Exception:
            print(msg)

    # ── Phase 2 stubs (raw-only mode) ────────────────────────────────
    def _extract_za_blocks(self, *args, **kwargs):
        raise NotImplementedError("Phase 2 — Zs.m port")

    def _extract_he_blocks(self, *args, **kwargs):
        raise NotImplementedError("Phase 2 — Rs.m port")

    def _compute_r_per_injection(self, *args, **kwargs):
        raise NotImplementedError("Phase 2 — Rs2.m port")

    def _smooth_r_polyfit5(self, *args, **kwargs):
        raise NotImplementedError("Phase 2 — Rs2.m polyfit5")

    def _optimize_za_rayleigh(self, *args, **kwargs):
        raise NotImplementedError("Phase 2 — optimize_ZA_Rayleigh.m (fminsearch)")


__all__ = ["DrNamAlphaWorker"]
