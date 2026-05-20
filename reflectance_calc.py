from __future__ import annotations

import argparse
import os
import sys
import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# Rayleigh Scattering Physics
# ─────────────────────────────────────────────────────────────────────────────

class RayleighPhysics:
    """
    Rayleigh scattering extinction α(λ) [cm⁻¹].
    Ref: Thalman et al. (2014) Applied Optics.
    """
    @staticmethod
    def get_alpha_rayleigh(
        wave_nm: np.ndarray,
        temp_c: float,
        press_mbar: float,
        gas_type: str = "zero_air", 
    ) -> np.ndarray:
        wave_nm = np.asarray(wave_nm, dtype=float)
        n_density = 2.68678e19 * (press_mbar / 1013.25) * (273.15 / (temp_c + 273.15))
        lambda_um = wave_nm / 1000.0
        
        if gas_type == "zero_air":
            # Thalman 2014 공식 (Zero-Air: N2 80% + O2 20% 혼합비 고려)
            n_minus_1 = (0.80 * (1e-8 * (2726.7 + 15.286 / lambda_um**2 + 0.131 / lambda_um**4))) + \
                        (0.20 * (1e-8 * (2366.1 + 10.97 / lambda_um**2 + 0.08 / lambda_um**4)))
            king_factor = 1.034 
            
        elif gas_type == "helium":
            n_minus_1 = 1e-8 * (2283.0 + 1.8102e5 / (153.42 - (1.0/lambda_um)**2))
            king_factor = 1.0
            
        else: # air
            n_minus_1 = 1e-8 * (5792105.0 / (238.0185 - (1.0/lambda_um)**2) + 167917.0 / (57.362 - (1.0/lambda_um)**2))
            king_factor = 1.061
        
        wave_cm = wave_nm * 1e-7
        sigma = (8.0 * np.pi**3 * (n_minus_1 * 2.0)**2 * king_factor) / (3.0 * n_density**2 * wave_cm**4)
        return sigma * n_density

# ─────────────────────────────────────────────────────────────────────────────
# Internal file loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_spectrum_from_file(
    filepath: str,
    pixel_min: int = 0,
    pixel_max: int | None = None,
) -> tuple[np.ndarray, int, float, float]:
    flag, t_c, p_mbar = 0, 25.0, 1013.25
    try:
        first_line = ""
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    first_line = stripped
                    break
    except OSError as exc:
        raise RuntimeError(f"Cannot open {os.path.basename(filepath)}: {exc}") from exc

    tokens = first_line.split("\t")
    if len(tokens) < 3: tokens = first_line.split()

    try:
        raw = np.array([float(t) for t in tokens if t.strip()], dtype=float)
    except ValueError as exc:
        raise RuntimeError(f"Non-numeric data in {os.path.basename(filepath)}") from exc

    if len(raw) >= 6175:
        intensity_full = raw[2053:4101]
        flag = int(raw[4])
        raw_p, raw_t = raw[6156], raw[6157]
        if not (np.isnan(raw_p) or raw_p in (0, 65535)): p_mbar = raw_p * (0.01 * 6894.73326 / 100.0)
        if not (np.isnan(raw_t) or raw_t in (0, 65535)): t_c = raw_t / 100.0
    elif len(raw) > 10:
        possible_flag = raw[4] if len(raw) > 5 else None
        col5_mean = float(np.mean(raw[5 : min(55, len(raw))])) if len(raw) > 5 else 0.0
        if possible_flag is not None and 0 <= possible_flag <= 999 and possible_flag == int(possible_flag) and col5_mean > 100.0:
            flag = int(possible_flag)
            intensity_full = raw[5:]
        else:
            intensity_full = raw
    else:
        intensity_full = raw

    valid_mask = np.isfinite(intensity_full)
    intensity_clean = intensity_full[valid_mask]
    p_min = max(0, int(pixel_min))
    p_max = len(intensity_clean) if (pixel_max is None or int(pixel_max) > len(intensity_clean)) else int(pixel_max)
    return intensity_clean[p_min:p_max], flag, t_c, p_mbar

# ─────────────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────────────

class ReflectanceCalculator:
    def __init__(self, cavity_len: float = 51.8, rl_factor: float = 0.933) -> None:
        self.cavity_len = float(cavity_len)
        self.rl_factor = float(rl_factor)
        self._za_spectra = []
        self._he_spectra = []
        self.omr_d = None
        self.r_curve = None
        self.valid_fraction = 0.0
        self._wave_nm = None

    def add_za_spectrum(self, source, t_c=25.0, p_mbar=1013.25, pixel_min=0, pixel_max=None) -> None:
        sp, flag, t_f, p_f = self._ingest(source, pixel_min, pixel_max)
        t_use = t_c if t_c != 25.0 else t_f
        p_use = p_mbar if p_mbar != 1013.25 else p_f
        self._za_spectra.append((sp, t_use, p_use))

    def add_he_spectrum(self, source, t_c=25.0, p_mbar=1013.25, pixel_min=0, pixel_max=None) -> None:
        sp, flag, t_f, p_f = self._ingest(source, pixel_min, pixel_max)
        t_use = t_c if t_c != 25.0 else t_f
        p_use = p_mbar if p_mbar != 1013.25 else p_f
        self._he_spectra.append((sp, t_use, p_use))

    def calculate(self, wave_nm=None, min_valid_fraction=0.50):
        if not self._za_spectra or not self._he_spectra:
            raise RuntimeError("ZA/He spectra missing.")

        n_pix = min(min(len(s) for s, _, _ in self._za_spectra), min(len(s) for s, _, _ in self._he_spectra))
        za_arr = np.vstack([s[:n_pix] for s, _, _ in self._za_spectra])
        he_arr = np.vstack([s[:n_pix] for s, _, _ in self._he_spectra])

        i_za = np.median(za_arr, axis=0)
        i_he = np.median(he_arr, axis=0)

        t_za = float(np.mean([t for _, t, _ in self._za_spectra]))
        p_za = float(np.mean([p for _, _, p in self._za_spectra]))
        t_he = float(np.mean([t for _, t, _ in self._he_spectra]))
        p_he = float(np.mean([p for _, _, p in self._he_spectra]))

        if wave_nm is not None:
            wave_nm = np.asarray(wave_nm, dtype=float)
            if len(wave_nm) != n_pix:
                x_old = np.linspace(0.0, 1.0, len(wave_nm))
                x_new = np.linspace(0.0, 1.0, n_pix)
                wave_nm = np.interp(x_new, x_old, wave_nm)
        else:
            wave_nm = np.linspace(400.0, 500.0, n_pix)

        alpha_za = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_za, p_za, "zero_air")
        alpha_he = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_he, p_he, "helium")

        i_he_safe = np.where(np.abs(i_he) > 1.0, i_he, 1.0)
        ratio = i_za / i_he_safe

        with np.errstate(divide="ignore", invalid="ignore"):
            omr_d = self.rl_factor * (ratio * alpha_za - alpha_he) / (1.0 - ratio)

        valid = np.isfinite(omr_d) & (omr_d > 0.0) & (omr_d < 1e-4)
        self.valid_fraction = float(np.sum(valid)) / n_pix

        if self.valid_fraction < min_valid_fraction:
            raise RuntimeError(f"R-curve quality check failed. Valid: {self.valid_fraction * 100:.0f}%")

        if np.any(~valid):
            x = np.arange(n_pix)
            omr_d = np.interp(x, x[valid], omr_d[valid])

        r_curve = np.clip(1.0 - omr_d * self.cavity_len, 0.0, 1.0)
        self.omr_d = omr_d
        self.r_curve = r_curve
        self._wave_nm = wave_nm
        return wave_nm, r_curve, omr_d

    def _ingest(self, source, pixel_min, pixel_max):
        if isinstance(source, (str, os.PathLike)):
            return _load_spectrum_from_file(str(source), pixel_min, pixel_max)
        arr = np.asarray(source, dtype=float).flatten()
        p_min = max(0, int(pixel_min))
        p_max = len(arr) if (pixel_max is None or int(pixel_max) > len(arr)) else int(pixel_max)
        return arr[p_min:p_max], 0, 25.0, 1013.25