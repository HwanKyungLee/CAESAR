
"""
Generate the DOAS extinction-domain retrieval benchmark (v2).

Self-contained: reads only wavelength calibrations and ILS-convolved cross
sections, and writes spectra, truth and a manifest. No retrieval code is
imported, so the benchmark does not depend on the implementation it tests.

Two fitting windows are included. They differ in width, polynomial order and
instrument line shape, and the same truth is presented in both (group E), so a
code can be asked whether its answer depends on the window.

Forward model, per pixel p of a window:

    alpha(p) = sum_g c_g * sigma_g(p')      gases, c_g in molec/cm3
             + sum_k a_k * T_k(x(p))        Chebyshev baseline, x in [-1, 1]
             + A * sin(2*pi*f*p + phi)      etalon, where present
             + eps(p)                       noise, where present

    p' = centre + (p - centre) * squeeze + shift_px

Units: sigma cm2/molec, alpha cm-1.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.ndimage import gaussian_filter1d

OUT = Path("bench/doas_benchmark_v1")
MULT = {"NO2": 0, "CHOCHO": 0, "H2O": -12}
NOISE_RMS = 6.16e-9
SEED = 20260921

CHANNELS = {
    "hot_PNs": dict(
        src=Path(r"C:\GHL\CAESAR\tests\data\wv_cal_roi1"),
        calib="Calib_20260619_Hg_400-499nm_Poly2.txt",
        refs={"NO2": "Ref_NO2_Dynamic-ILS-Applied.dat",
              "CHOCHO": "Ref_CHOCHO_Dynamic-ILS-Applied.dat",
              "H2O": "Ref_H2O-HITRAN_Dynamic-ILS-Applied.dat"},
        window_nm=(444.146, 470.685), poly=3),
    "cold": dict(
        src=Path(r"C:/GHL/2026 yeosu/Output/wv_cal/cold"),
        calib="Calib_20260523_Hg_4line_400-497nm_Poly2.txt",
        refs={"NO2": "Ref_NO2_Dynamic-ILS-Applied.dat",
              "CHOCHO": "Ref_CHOCHO_Dynamic-ILS-Applied.dat",
              "H2O": "Ref_H2O-HITRAN_Dynamic-ILS-Applied.dat"},
        window_nm=(438.420, 475.741), poly=4),
}
BASE = [1.85e-7, -4.0e-9, 1.2e-9, -3.0e-10]


def read_col(p, mult=0):
    v = np.asarray([float(l) for l in p.read_text().splitlines()
                    if l.strip() and not l.startswith("#")], float)
    return v * 10.0 ** mult


def resample(sigma, px, centre, shift, squeeze):
    """Linear sub-pixel resampling (the convention groups B-E are generated with)."""
    src = np.arange(len(sigma), dtype=float)
    return np.interp(centre + (px - centre) * squeeze + shift, src, sigma)


def resample_bandlimited(sigma, px, centre, shift, squeeze, a=4):
    """Windowed-sinc (Lanczos) resampling.

    A detector samples a spectrum already band-limited by the slit function, so
    band-limited interpolation is the physically motivated sub-pixel model. It
    coincides with neither linear nor cubic interpolation, which is why group F
    can compare them without favouring either.
    """
    pp = centre + (px - centre) * squeeze + shift
    n = len(sigma)
    base = np.floor(pp).astype(int)
    out = np.zeros(len(pp))
    wsum = np.zeros(len(pp))
    for k in range(-a + 1, a + 1):
        idx = np.clip(base + k, 0, n - 1)
        x = pp - (base + k)
        w = np.sinc(x) * np.sinc(x / a)
        out += w * sigma[idx]
        wsum += w
    return out / np.where(np.abs(wsum) < 1e-12, 1.0, wsum)


def cheb(x, order):
    T = [np.ones_like(x), x]
    for k in range(2, order + 1):
        T.append(2 * x * T[-1] - T[-2])
    return np.array(T[:order + 1])


def load(ch):
    cfg = CHANNELS[ch]
    wl = read_col(cfg["src"] / cfg["calib"])
    sig = {g: read_col(cfg["src"] / f, MULT[g]) for g, f in cfg["refs"].items()}
    assert all(len(v) == len(wl) for v in sig.values()), f"{ch}: grid mismatch"
    m = (wl >= cfg["window_nm"][0]) & (wl <= cfg["window_nm"][1])
    px = np.where(m)[0].astype(float)
    return wl, sig, m, px, float(px.mean()), cfg


def build(sig, px, centre, conc, shift, squeeze, poly, etalon=None,
          ils_extra_px=0.0, noise=0.0, ar1=0.0, rng=None, bandlimited=False):
    rs = resample_bandlimited if bandlimited else resample
    a = np.zeros(len(px))
    for g, c in conc.items():
        if not c:
            continue
        s = sig[g]
        if ils_extra_px > 0:
            s = gaussian_filter1d(s, ils_extra_px, mode="nearest")
        a += c * rs(s, px, centre, shift, squeeze)
    a += np.asarray(poly) @ cheb(np.linspace(-1.0, 1.0, len(px)), len(poly) - 1)
    if etalon is not None:
        amp, f, phi = etalon
        a += amp * np.sin(2 * np.pi * f * px + phi)
    if noise > 0:
        e = rng.normal(0.0, 1.0, len(px))
        if ar1 > 0:
            o = np.empty_like(e); o[0] = e[0]
            for i in range(1, len(e)):
                o[i] = ar1 * o[i - 1] + np.sqrt(1 - ar1 ** 2) * e[i]
            e = o
        a += noise * e
    return a


def main():
    rng = np.random.default_rng(SEED)
    L = {ch: load(ch) for ch in CHANNELS}
    peak = {ch: {g: float(np.max(np.abs(L[ch][1][g][L[ch][2]]))) for g in CHANNELS[ch]["refs"]}
            for ch in CHANNELS}
    rows, spectra = [], {}

    def add(cid, ch, group, purpose, conc, shift, squeeze, poly, pair_id="", **kw):
        wl, sig, m, px, centre, cfg = L[ch]
        spectra[cid] = build(sig, px, centre, conc, shift, squeeze, poly, rng=rng, **kw)
        kw.pop("bandlimited", None)
        et = kw.get("etalon")
        rows.append(dict(case_id=cid, channel=ch, group=group, purpose=purpose,
                         pair_id=pair_id,
                         window_start_nm=cfg["window_nm"][0], window_end_nm=cfg["window_nm"][1],
                         n_pixels=int(len(px)), centre_pixel=centre,
                         NO2_molec_cm3=conc.get("NO2", 0.0),
                         CHOCHO_molec_cm3=conc.get("CHOCHO", 0.0),
                         H2O_molec_cm3=conc.get("H2O", 0.0),
                         NO2_peak_alpha_cm1=conc.get("NO2", 0.0) * peak[ch]["NO2"],
                         CHOCHO_peak_alpha_cm1=conc.get("CHOCHO", 0.0) * peak[ch]["CHOCHO"],
                         H2O_peak_alpha_cm1=conc.get("H2O", 0.0) * peak[ch]["H2O"],
                         shift_px=shift, squeeze_factor=squeeze, poly_order=len(poly) - 1,
                         noise_rms=kw.get("noise", 0.0), ar1=kw.get("ar1", 0.0),
                         etalon_amp=(et[0] if et else 0.0),
                         etalon_f=(et[1] if et else np.nan),
                         ils_extra_px=kw.get("ils_extra_px", 0.0),
                         gases_to_fit=("NO2" if conc.get("CHOCHO", 0) == 0 else "NO2,CHOCHO,H2O"),
                         fit_poly_order=cfg["poly"], fit_etalon_f=0.12))

    def amt(ch, g, target):
        return target / peak[ch][g]

    def three(ch):
        return dict(CHOCHO=amt(ch, "CHOCHO", 2.0e-9), H2O=amt(ch, "H2O", 3.0e-8))

    H = "hot_PNs"
    # A - exact recovery, noise free
    for tgt in (2e-9, 2e-8, 1e-7, 4e-7):
        for d in (0.0, -2.0, 2.0, -4.0):
            t = f"a{tgt:.0e}_s{d:+.0f}".replace("+", "p").replace("-", "m")
            add("A_1gas_" + t, H, "A_exact",
                "numerical recovery; integer shift and unit squeeze, so no "
                "sub-pixel resampling is involved for any implementation",
                {"NO2": amt(H, "NO2", tgt)}, d, 1.000, BASE)
            add("A_3gas_" + t, H, "A_exact",
                "numerical recovery, three absorbers; integer shift, unit squeeze",
                dict(NO2=amt(H, "NO2", tgt), **three(H)), d, 1.000, BASE)

    # B - noise replicates: does the reported uncertainty equal the scatter
    for tag, nz, ar in (("n1", NOISE_RMS, 0.0), ("n2", 2 * NOISE_RMS, 0.0),
                        ("ar", NOISE_RMS, 0.5)):
        for k in range(60):
            add(f"B_{tag}_{k:03d}", H, "B_noise",
                "uncertainty calibration: 60 replicates of one truth",
                dict(NO2=amt(H, "NO2", 2e-8), **three(H)), -2.0, 1.002, BASE,
                noise=nz, ar1=ar)

    # C - model mismatch, noise free so the bias is unambiguous
    for ex in (0.25, 0.5, 1.0, 3.0):
        add(f"C_ils_{ex:g}px", H, "C_mismatch", "reference convolved with extra ILS width",
            dict(NO2=amt(H, "NO2", 2e-8), **three(H)), -2.0, 1.002, BASE, ils_extra_px=ex)
    for fr in (0.005, 0.01, 0.02):
        for f in (0.12, 0.16, 0.35):
            add(f"C_etalon_a{fr:g}_f{f:g}", H, "C_mismatch",
                "etalon present at f; fit uses the fixed operational f = 0.12",
                dict(NO2=amt(H, "NO2", 2e-8), **three(H)), -2.0, 1.002, BASE,
                etalon=(fr * 1.85e-7, f, 0.7))
    for tgt in (2e-9, 2e-8, 1e-7):
        add(f"C_missing_a{tgt:.0e}", H, "C_mismatch",
            "CHOCHO and H2O present; submitter is told to fit NO2 only",
            dict(NO2=amt(H, "NO2", tgt), **three(H)), -2.0, 1.002, BASE)
        rows[-1]["gases_to_fit"] = "NO2"

    # D - identifiability: a high-order baseline absorbs the shift
    for d in (-4.0, -2.0, 0.0, 2.0, 4.0):
        add("D_flat_s" + f"{d:+.0f}".replace("+", "p").replace("-", "m"), H,
            "D_identifiability",
            "shift is not constrained; a code should report that, not a value",
            dict(NO2=amt(H, "NO2", 6e-9), **three(H)), d, 1.002,
            BASE + [8e-11, -2e-11], noise=NOISE_RMS)
        rows[-1]["fit_poly_order"] = 5

    # E - the same truth in two windows
    for k, (tgt, d) in enumerate([(2e-8, 0.0), (2e-8, -2.0), (2e-8, 2.0),
                                  (1e-7, 0.0), (1e-7, -2.0),
                                  (4e-7, 0.0), (4e-7, -2.0), (4e-7, 2.0)]):
        pid = f"E{k:02d}"
        for ch in ("hot_PNs", "cold"):
            add(f"E_{ch}_{pid}", ch, "E_window",
                "same truth in two windows; the answer should not depend on the window",
                dict(NO2=amt(ch, "NO2", tgt), **three(ch)), d, 1.002, BASE,
                pair_id=pid, noise=NOISE_RMS)

    # F - sub-pixel resampling. Generated band-limited, so neither a linear nor a
    # cubic interpolator reproduces it; the spread between them is the quantity.
    for tgt in (2e-8, 1e-7, 4e-7):
        for d in (-1.96, -0.37, 0.41, 2.63):
            t = f"a{tgt:.0e}_s{d:+.2f}".replace("+", "p").replace("-", "m").replace(".", "")
            add("F_subpix_" + t, H, "F_subpixel",
                "non-integer shift with squeeze; truth uses band-limited sub-pixel "
                "resampling, so the result depends on the interpolator chosen",
                dict(NO2=amt(H, "NO2", tgt), **three(H)), d, 1.002, BASE,
                bandlimited=True)

    man = pd.DataFrame(rows)
    (OUT / "reference").mkdir(parents=True, exist_ok=True)
    (OUT / "cases").mkdir(parents=True, exist_ok=True)
    for ch in CHANNELS:
        wl, sig, m, px, centre, cfg = L[ch]
        pd.DataFrame({"pixel": np.arange(len(wl)), "wavelength_nm": wl,
                      **{f"sigma_{g}_cm2": sig[g] for g in cfg["refs"]}}).to_csv(
            OUT / "reference" / f"cross_sections_{ch}.csv", index=False)
    man.to_csv(OUT / "cases" / "manifest.csv", index=False)
    grids = {}
    for ch in CHANNELS:
        wl, sig, m, px, centre, cfg = L[ch]
        grids[f"pixel__{ch}"] = px.astype(int)
        grids[f"wavelength_nm__{ch}"] = wl[m]
    np.savez_compressed(OUT / "cases" / "spectra.npz", **grids, **spectra)
    meta = dict(name="DOAS extinction-domain retrieval benchmark", version=2, seed=SEED,
                n_cases=int(len(man)), alpha_units="cm-1", sigma_units="cm2 molec-1",
                noise_rms_cm1=NOISE_RMS, reference_multiplier_applied=MULT,
                shift_convention="p_prime = centre + (p - centre) * squeeze + shift_px",
                channels={ch: dict(window_nm=list(CHANNELS[ch]["window_nm"]),
                                   poly_order=CHANNELS[ch]["poly"],
                                   window_pixels=[int(L[ch][3][0]), int(L[ch][3][-1])],
                                   n_pixels=int(len(L[ch][3])),
                                   centre_pixel=L[ch][4]) for ch in CHANNELS},
                cross_section_provenance=(
                    "instrument-convolved references from a two-channel thermal-dissociation "
                    "BBCEAS; NO2 after Vandaele et al., CHOCHO after Volkamer et al., H2O from "
                    "HITRAN. Cite the original cross-section papers, not this package."),
                groups={g: int(n) for g, n in man.group.value_counts().items()})
    (OUT / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return man, meta


if __name__ == "__main__":
    man, meta = main()
    print(json.dumps(meta["channels"], indent=1))
    print("n_cases", meta["n_cases"])
    print(man.group.value_counts().to_string())
