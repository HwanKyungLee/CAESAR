"""
gui/dr_nam_alpha_worker.py — Dr. Nam-compatible α(λ) export
============================================================

Goal
----
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

Pipeline (mirrors 박사님 Step2 + Alpha.m)
-----------------------------------------
  Raw .dat   (or daily .mat from Step1)
       │
       ▼
  Wv calibration (2048 × ch1/ch2)
  Dark spectrum  (per channel)
       │
       ▼
  ─── Rs ─────────────────────────────────────
  for each He/ZA injection (per file):
      block = blockfinder_3ch(flag 503/500 ZA, 513/510 He)
      R_per_inj = compute_r_per_injection(...)
      Rr_smooth = smooth_r_polyfit5(R, ch_window)
  → doy_R, alpha_cavity1_fit, alpha_cavity2_fit
       │
       ▼
  ─── Zs ─────────────────────────────────────
  for each ZA injection:
      Z = za - dark
  → doy_z, Z1, Z2, rho_z1, rho_z2
  (oneZ=1 → IQR-filtered nanmean → single Z1one/Z2one)
       │
       ▼
  ─── Alpha (60s) ────────────────────────────
  std_t_temp = arange(min(doy), max(doy), avgsec/86400)
  for each bin in std_t_temp:
      j = scans with doy in [bin, bin + 60s)
      if len(j) < 3: skip + propagate previous timestamp
      R_interp   = pchip(doy_R,  alpha_cavity_fit)(bin)
      Z_interp   = pchip(doy_z,  Z)(bin)
      ρ_za_interp= pchip(doy_z,  rho_z)(bin)
      I_avg      = nanmean(ch[j, :]) - dark
      α_ref      = σ_ZA(λ) · ρ_za_interp
      α_sample   = σ_ZA(λ) · ρ_air(T_amb, P_amb)
      α_abs(bin, :) = RL · (R_interp + α_ref) · (Z_interp/I_avg - 1)
                     - (α_sample - α_ref)
      α[Inf|NaN] = 0
      → write ch{N}_YYYYMMDD_000NNN.dat (one α per pixel, scientific)
  → save YYYY-MM-DD_avg_60s.mat (alpha_abs1, alpha_abs2, std_t, rho_avg1, ...)

Gaps vs current CAESAR Pro AlphaExportWorker
--------------------------------------------
Required (no Dr-Nam-match without these):
  · 60s bin averaging (raw I averaged, not α)
  · R PCHIP per bin (we use candidates-median)
  · Output folders ch{N}_YYYYMMDD_000000/ + 5-zero-pad scan numbers
  · bin skip when len(j) < 3
  · per-channel RL (ch1=0.9330 / ch2=0.9950 / ch3=0.9968 — Hot uses 1)
  · RL formula position:  RL·(R+α_ref)·(...)  vs ours (omr_d/RL + α_ref)·(...)
  · ref_press=700 mb, ref_temp=30 °C → ref_rho for Zeroing reference
  · R(λ) 5th-degree polyfit smoothing (Rr1)
  · HJ-measured ZA Rayleigh:  σ_ZA = 1.100065e-15 · λ^(-4.166)
    used for BOTH Ch1 and Ch2 (Alpha.m:136,138).
    Sellmeier (our current RayleighPhysics) is physics-correct but differs.

Optional (precision improvements):
  · CCD time delay correction (Step1)
  · optimize_ZA_Rayleigh: fminsearch (A,B) so R(λ) is smoothest under polyfit5
  · fitalpha1/2 (channel selects raw R vs fitted R)
  · oneZ=1 IQR average vs oneZ=0 per-pixel PCHIP
  · 260526 quirks: tempcell2 = temppreh; presscell2_Pa = presscell3_Pa

Tracking
--------
GitHub issue: https://github.com/HwanKyungLee/CEASER/issues/23
"""
from __future__ import annotations

import os
import numpy as np
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal


# Dr. Nam HJ-measured ZA Rayleigh fit (Alpha.m:136, 138 — both channels)
HJ_ZA_RAYLEIGH_A = 1.100065008184610e-15   # cm² / molecule
HJ_ZA_RAYLEIGH_B = 4.165598772133079       # exponent (positive value; σ = A·λ^(-B))

# Per-channel RL (Step2 / Alpha.m:127 comment: ch1=0.9330 ch2=0.9950 ch3=0.9968)
# Hot CAESAR uses RL = 1 (line 127); Cold channels may differ.
DR_NAM_RL_DEFAULT = {1: 0.9330, 2: 0.9950, 3: 0.9968}

# Zeroing reference (Step2.m:95-96)
ZEROING_REF_PRESS_MBAR = 700.0
ZEROING_REF_TEMP_C     = 30.0

# Pressure raw-count → Pa conversion (Zs.m:64, Alpha.m:94)
PSI_TO_PA = 6894.73326
PRESS_COUNT_TO_PA_FACTOR = 0.01 * PSI_TO_PA   # raw_count → Pa  (~68.9473)

# Flags (Zs.m:17-18)
FLAG_ZA_VALUES = (503, 500)
FLAG_HE_VALUES = (513, 510)

# Polyfit smoothing for R(λ) (Rs2.m:139-140)
R_POLYFIT_ORDER = 5

# Channel R-fit windows in nm (Rs2.m:123-138)
CH_FIT_WINDOWS_NM = {
    1: (430.0, 465.0),   # PNs in Rs2 comment ("PNs" on line 123 / 146)
    2: (435.0, 470.0),   # ANs
    3: (437.0, 472.0),   # N/A / PN
}


class DrNamAlphaWorker(QThread):
    """
    Dr. Nam-compatible α export.

    Runs in a QThread so the GUI stays responsive during multi-day batches.

    Parameters
    ----------
    raw_dir : str
        Folder of raw .dat (or daily .mat) files for the campaign date(s).
    output_dir : str
        Where to write ch{N}_YYYYMMDD_000000/ folders and the daily .mat.
    wave_nm : np.ndarray, shape (n_pix,) or (n_pix, n_ch)
        Wavelength calibration. Loaded from H:/.../wv_cal/wv_CAESAR_Hot_Calib_*.mat
        in 박사님 Step2.m — caller passes parsed array(s).
    dark : np.ndarray, shape (n_pix, n_ch)
        Dark spectrum per channel.
    avgsec : int, default 60
        Averaging window in seconds (박사님 default 60).
    channels : tuple[int, ...], default (1, 2)
        Which channels to export. Hot has ch1 and ch2 active.
    rl_per_channel : dict[int, float] or None
        Override RL per channel. If None, uses DR_NAM_RL_DEFAULT *but* Hot
        runs use RL = 1 per Alpha.m:127 — caller decides.
    use_hj_za_rayleigh : bool, default True
        If True, σ_ZA = HJ_ZA_RAYLEIGH_A · λ^(-HJ_ZA_RAYLEIGH_B) (박사님 동일).
        If False, fall back to RayleighPhysics Sellmeier (slight physical
        difference, not 1:1 with 박사님 output).
    one_z_mode : bool, default True
        Zs.m oneZ=1 path: IQR-filter ZA scans and use a single nanmean Z.
        If False, per-pixel PCHIP across all ZA scans (Zs.m else branch).
    fitalpha_per_channel : dict[int, bool] or None
        Per-channel choice between raw R (True) and polyfit5-smoothed Rr (False).
        Defaults to {1: True, 2: True} (Alpha.m:31-41 commented but both use fit).
    enable_ccd_time_delay_fix : bool, default False
        Apply Step1 time-correcting_matfiles_*_3ch behavior. Stub for now.
    enable_optimize_za_rayleigh : bool, default False
        Run fminsearch on (A, B) so polyfit5 residual of R(λ) is minimal
        (optimize_ZA_Rayleigh_Hot.m). When True, supersedes use_hj_za_rayleigh.

    Signals
    -------
    progress(int)         emitted 0..100 over the batch
    status_msg(str)       human-readable progress line
    finished(str)         output_dir on success, "ERROR: ..." on failure
    """

    progress    = pyqtSignal(int)
    status_msg  = pyqtSignal(str)
    finished    = pyqtSignal(str)

    def __init__(
        self,
        raw_dir: str,
        output_dir: str,
        wave_nm: np.ndarray,
        dark: np.ndarray,
        *,
        avgsec: int = 60,
        channels: tuple = (1, 2),
        rl_per_channel: Optional[dict] = None,
        use_hj_za_rayleigh: bool = True,
        one_z_mode: bool = True,
        fitalpha_per_channel: Optional[dict] = None,
        enable_ccd_time_delay_fix: bool = False,
        enable_optimize_za_rayleigh: bool = False,
    ) -> None:
        super().__init__()
        self.raw_dir    = raw_dir
        self.output_dir = output_dir
        self.wave_nm    = np.asarray(wave_nm, dtype=float)
        self.dark       = np.asarray(dark,    dtype=float)
        self.avgsec     = int(avgsec)
        self.channels   = tuple(channels)
        self.rl_per_channel = dict(rl_per_channel) if rl_per_channel else {c: 1.0 for c in self.channels}
        self.use_hj_za_rayleigh        = bool(use_hj_za_rayleigh)
        self.one_z_mode                = bool(one_z_mode)
        self.fitalpha_per_channel      = dict(fitalpha_per_channel) if fitalpha_per_channel else {c: True for c in self.channels}
        self.enable_ccd_time_delay_fix = bool(enable_ccd_time_delay_fix)
        self.enable_optimize_za_rayleigh = bool(enable_optimize_za_rayleigh)
        self.is_running = True

    # ── Public API ───────────────────────────────────────────────────────
    def stop(self) -> None:
        self.is_running = False

    def run(self) -> None:
        """Main thread entry — orchestrates the full pipeline."""
        try:
            self._emit_status("Phase 0 stub — DrNamAlphaWorker not yet implemented.")
            # TODO Phase 1: load raw files / daily .mat
            # TODO Phase 1: ZA & He block extraction (Zs.m, Rs.m)
            # TODO Phase 1: per-injection R computation (Rs2.m)
            # TODO Phase 1: 5th-order polyfit smoothing (Rs2.m:139)
            # TODO Phase 1: optional optimize_ZA_Rayleigh (fminsearch)
            # TODO Phase 2: build 60s time grid + PCHIP R/Z/ρ per bin
            # TODO Phase 2: nanmean(I[j, :]) - dark per bin
            # TODO Phase 2: α formula RL·(R+α_ref)·(Z/I-1) - (αs-αr)
            # TODO Phase 2: Inf/NaN → 0 cleanup
            # TODO Phase 3: write ch{N}_YYYYMMDD_000000/ folders + scan files
            # TODO Phase 3: write YYYY-MM-DD_avg_60s.mat (scipy.io.savemat)
            # TODO Phase 4: validate vs 박사님 results (pixel-wise RMS)
            self.finished.emit("ERROR: DrNamAlphaWorker not yet implemented (Phase 0 skeleton).")
        except Exception as exc:
            self.finished.emit(f"ERROR: {exc!r}")

    # ── Pipeline stages (Phase 1+) ──────────────────────────────────────
    # Each helper mirrors a piece of 박사님 MATLAB. Names intentionally
    # close to the .m filenames so future hand-port edits are obvious.

    def _load_raw_or_mat(self, fname: str) -> dict:
        """Load one day's worth of raw scans.
        Mirrors Step1 read_data_*_3ch.mat output:
          ch1, ch2, ch3, doy, flag, tempcell1/2/3, presscell1/2/3, ...
        """
        raise NotImplementedError("Phase 1")

    def _extract_za_blocks(self, ch: np.ndarray, flag: np.ndarray) -> list:
        """Zs.m: find flag-503/500 blocks, trim to stable region (movmean 5,
        end+25..end+55 pixel slice)."""
        raise NotImplementedError("Phase 1")

    def _extract_he_blocks(self, ch: np.ndarray, flag: np.ndarray) -> list:
        """Rs.m equivalent: flag-513/510 He injection blocks."""
        raise NotImplementedError("Phase 1")

    def _za_sigma_rayleigh(self, wave_nm: np.ndarray) -> np.ndarray:
        """σ_ZA(λ) [cm²/molecule]. HJ measurement (Alpha.m:136,138) by default,
        or RayleighPhysics Sellmeier when use_hj_za_rayleigh=False."""
        if self.use_hj_za_rayleigh:
            return HJ_ZA_RAYLEIGH_A * wave_nm ** (-HJ_ZA_RAYLEIGH_B)
        # else: defer to core.physics.RayleighPhysics (Sellmeier 0.79 N₂ + 0.21 O₂)
        raise NotImplementedError("Sellmeier fallback wiring in Phase 1")

    def _compute_r_per_injection(self, he, za, rho_he, rho_za, wave_nm,
                                  dark, ch: int, d_cav: float = 51.8) -> dict:
        """Rs2.m line 95: R = 1 - d_cav · ((I_ZA/I_He)·α_hi - α_lo) / (1 - I_ZA/I_He)
        Returns {R, Rr (polyfit5 smooth), α_hi, I_ZA_dark_corrected, leff}."""
        raise NotImplementedError("Phase 1")

    def _smooth_r_polyfit5(self, wave_nm: np.ndarray, R: np.ndarray, ch: int) -> np.ndarray:
        """Rs2.m:139-140 — fit R(λ) on the channel-specific window with a
        5th-degree polynomial and evaluate over the full λ axis."""
        raise NotImplementedError("Phase 1")

    def _optimize_za_rayleigh(self, he, za, rho_he, rho_za, wave_nm,
                               dark, ch: int, d_cav: float = 51.8) -> tuple:
        """optimize_ZA_Rayleigh_Hot.m — minimise sum((R - polyfit5(R))²)
        over (A, B) of σ_ZA = A·λ^(-B). Returns (A_best, B_best, R, σ_ZA)."""
        raise NotImplementedError("Phase 1")

    def _build_60s_time_grid(self, doy: np.ndarray) -> np.ndarray:
        """Alpha.m:25 — std_t_temp = min(doy) : avgsec/86400 : max(doy)."""
        return np.arange(np.nanmin(doy), np.nanmax(doy),
                         self.avgsec / 86400.0)

    def _pchip_along_time(self, t_known: np.ndarray, y_known: np.ndarray,
                           t_target: np.ndarray) -> np.ndarray:
        """Time-axis PCHIP, with per-pixel support when y_known is 2-D
        (Alpha.m line 32-46). NaN-aware."""
        raise NotImplementedError("Phase 1")

    def _compute_alpha_per_bin(self, std_t, doy, ch_data, dark, rho_air_fn,
                                rho_za_pchip, R_pchip, Z_pchip, RL, sigma_za,
                                ch: int) -> np.ndarray:
        """Alpha.m:74-156 — per-bin raw average + BBCEAS α formula.
        α[Inf|NaN] = 0 (Alpha.m:161-163)."""
        raise NotImplementedError("Phase 2")

    def _save_dr_nam_folder(self, alpha_2d: np.ndarray, ch: int,
                             date_yyyymmdd: str) -> int:
        """Write ch{N}_YYYYMMDD_000000/ch{N}_YYYYMMDD_000NNN.dat files.
        Returns number of files written."""
        raise NotImplementedError("Phase 3")

    def _save_daily_mat(self, all_alphas: dict, all_meta: dict,
                         date_yyyymmdd: str) -> str:
        """Alpha.m:251-262 roll-up: YYYY-MM-DD_avg_60s.mat with
        alpha_abs1/2, rho_avg1/2, std_t/std_t_st/std_t_end/std_t_mid,
        tempcell11/22, presscell11/22, doy/doy_z/doy_R."""
        raise NotImplementedError("Phase 3")

    # ── Internals ────────────────────────────────────────────────────────
    @staticmethod
    def _press_count_to_pa(raw_count) -> np.ndarray:
        """Zs.m:64 — psi count → Pa.
        65535 / 0 → NaN; if everything NaN → caller defaults to 101325 Pa."""
        arr = np.asarray(raw_count, dtype=float)
        invalid = (arr == 65535) | (arr == 0)
        arr = np.where(invalid, np.nan, arr)
        return arr * PRESS_COUNT_TO_PA_FACTOR

    @staticmethod
    def _air_number_density(temp_k: np.ndarray, press_pa: np.ndarray) -> np.ndarray:
        """fun_air equivalent — N(T, P) in molecules/cm³.

        박사님 fun_air confirmed (RayleighPhysics docstring) to use
        Loschmidt N₀ = 2.6867811e19, identical to our convention.
        """
        N0      = 2.6867811e19
        T0_K    = 273.15
        P0_MBAR = 1013.25
        P0_PA   = P0_MBAR * 100.0
        return N0 * (press_pa / P0_PA) * (T0_K / temp_k)

    def _emit_status(self, msg: str) -> None:
        try:
            self.status_msg.emit(msg)
        except Exception:
            print(msg)


__all__ = ["DrNamAlphaWorker"]
