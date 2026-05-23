from __future__ import annotations

import argparse
import os
import sys
import numpy as np

# RayleighPhysics → core/physics.py 에서 공유 (gui/worker.py 와 동일 구현 유지)
from core.physics import RayleighPhysics

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
        # HK column auto-detect (verified 2026-05-18/19 samples):
        #   Cold: P=col6160 (~1010 mbar),  T=col6173 (~24°C, cavity)  [tempcell1 in MATLAB]
        #   Hot:  P=col6162 (~971 mbar),   T=col6155 (~75°C, cavity)  [heated cavity]
        #   col 6174 = tempsptrm (spectrometer housing ~30°C) — NOT the cavity temperature
        #
        # Pressure: try Cold col first (6160), fall back to Hot col (6162)
        raw_p = np.nan
        for _pcol in (6160, 6162):
            _v = raw[_pcol] if _pcol < len(raw) else np.nan
            if np.isfinite(_v) and _v not in (0, 65535):
                raw_p = _v
                break
        # Temperature: try Hot cavity col first (6155 ~75°C), fall back to Cold cavity col (6173 ~24°C)
        raw_t = np.nan
        for _tcol in (6155, 6173):
            _v = raw[_tcol] if _tcol < len(raw) else np.nan
            if np.isfinite(_v) and _v not in (0, 65535):
                raw_t = _v
                break
        if np.isfinite(raw_p): p_mbar = float(raw_p) * (0.01 * 6894.73326 / 100.0)
        if np.isfinite(raw_t): t_c = float(raw_t) / 100.0
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
    def __init__(self, cavity_len: float = 51.8, rl_factor: float = 1.0) -> None:
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

    def calculate(self, wave_nm=None, min_valid_fraction=0.30):
        """R 커브를 계산한다.

        min_valid_fraction
            유효 픽셀 비율 하한.  기본값 0.30.
            실측 장비에서 CCD 엣지 저신호 픽셀로 인해 valid_fraction ≈ 0.44 가
            정상이므로, 과거 기본값 0.50 은 모든 파일을 quality_ok=False로 판정하는
            오류를 일으켰다.  0.30으로 완화하여 정상 파일을 올바르게 OK로 분류한다.
        """
        if not self._za_spectra or not self._he_spectra:
            raise RuntimeError("ZA/He spectra missing.")

        n_pix = min(min(len(s) for s, _, _ in self._za_spectra), min(len(s) for s, _, _ in self._he_spectra))
        za_arr = np.vstack([s[:n_pix] for s, _, _ in self._za_spectra])
        he_arr = np.vstack([s[:n_pix] for s, _, _ in self._he_spectra])

        i_za = np.median(za_arr, axis=0)
        i_he = np.median(he_arr, axis=0)

        # ── 신호 기반 엣지 마스크 ─────────────────────────────────────────────
        # CCD 양쪽 끝은 감도가 낮아 I_ZA, I_He 모두 노이즈 지배 → ratio 불안정
        # peak 대비 5% 미만 픽셀은 R 계산에서 제외하고 보간으로 대체
        _SIG_THRESH = 0.05
        _peak_za = float(np.nanmax(i_za)) if np.any(np.isfinite(i_za)) else 1.0
        _peak_he = float(np.nanmax(i_he)) if np.any(np.isfinite(i_he)) else 1.0
        _sig_ok = (i_za >= _SIG_THRESH * _peak_za) & (i_he >= _SIG_THRESH * _peak_he)

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

        # 유효 범위: 신호 OK + 0 < omr_d < 1e-3 cm^-1 (R > ~94.8% @ d=51.8cm)
        # _sig_ok: 엣지 노이즈 픽셀 배제 (peak 5% 미만)
        valid = _sig_ok & np.isfinite(omr_d) & (omr_d > 0.0) & (omr_d < 1e-3)
        self.valid_fraction = float(np.sum(valid)) / n_pix
        self.quality_ok = self.valid_fraction >= min_valid_fraction

        if np.any(valid):
            x = np.arange(n_pix)
            omr_d = np.interp(x, x[valid], omr_d[valid])
        else:
            # 유효 픽셀 0개 = ratio ≈ 1 전체 (He/ZA 신호 구별 불가).
            # zeros → R=1.0 dummy 를 내보내면 호출자가 이를 정상값으로 오인하므로
            # 예외를 던져 호출자가 이 파일을 명시적으로 스킵하게 한다.
            raise RuntimeError(
                "valid_fraction=0: 모든 픽셀에서 He/ZA ratio≈1 "
                "(퍼지 불완전 또는 전환 스캔). 이 파일의 R 계산 불가."
            )

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