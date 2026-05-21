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
    Clausius-Mossotti form, ported from MATLAB CAESAR processing code.
    σ = Fk × (24π³v⁴/N²) × ((n²-1)/(n²+2))²,  α = σ × N
    where v = 1/λ_cm (wavenumber), N = number density [cm⁻³].
    """
    @staticmethod
    def get_alpha_rayleigh(
        wave_nm: np.ndarray,
        temp_c: float,
        press_mbar: float,
        gas_type: str = "zero_air",
    ) -> np.ndarray:
        wave_nm = np.asarray(wave_nm, dtype=float)
        N = 2.68678e19 * (press_mbar / 1013.25) * (273.15 / (temp_c + 273.15))
        v = 1e7 / wave_nm  # wavenumber [cm⁻¹]

        if gas_type == "zero_air":
            # N2 — Sellmeier dispersion
            A_n2, B_n2, C_n2 = 5677.465, 318.81874e12, 14.4e9
            n_n2 = 1.0 + (A_n2 + B_n2 / (C_n2 - v**2)) * 1e-8
            Fk_n2 = 1.034 + 3.17e-12 * v
            s_n2 = Fk_n2 * (24 * np.pi**3 * v**4 / N**2) * ((n_n2**2 - 1) / (n_n2**2 + 2))**2

            # O2 — Sellmeier dispersion
            A_o2, B_o2, C_o2 = 20564.8, 2.480899e13, 4.09e9
            n_o2 = 1.0 + (A_o2 + B_o2 / (C_o2 - v**2)) * 1e-8
            Fk_o2 = 1.09 + 1.385e-11 * v**2 + 1.448e-20 * v**4
            s_o2 = Fk_o2 * (24 * np.pi**3 * v**4 / N**2) * ((n_o2**2 - 1) / (n_o2**2 + 2))**2

            sigma = 0.79 * s_n2 + 0.21 * s_o2

        elif gas_type == "helium":
            # He — Sellmeier dispersion, Fk = 1
            A_he, B_he, C_he = 2283.0, 1.8102e13, 1.5342e10
            n_he = 1.0 + (A_he + B_he / (C_he - v**2)) * 1e-8
            sigma = (24 * np.pi**3 * v**4 / N**2) * ((n_he**2 - 1) / (n_he**2 + 2))**2

        else:  # standard air
            lambda_um = wave_nm / 1000.0
            n_minus_1 = 1e-8 * (5792105.0 / (238.0185 - (1.0/lambda_um)**2)
                                 + 167917.0 / (57.362 - (1.0/lambda_um)**2))
            wave_cm = wave_nm * 1e-7
            sigma = (8.0 * np.pi**3 * (n_minus_1 * 2.0)**2 * 1.061) / (3.0 * N**2 * wave_cm**4)

        return sigma * N

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
        self.quality_ok = self.valid_fraction >= min_valid_fraction

        if np.any(valid):
            x = np.arange(n_pix)
            omr_d = np.interp(x, x[valid], omr_d[valid])
        else:
            omr_d = np.zeros(n_pix)

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