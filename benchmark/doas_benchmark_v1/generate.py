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

Instrument-coordinate parameters (2026-09-23, task B-1)
------------------------------------------------------
Every axis below defaults to the value the shipped v2 package was built with,
so running this file with no arguments reproduces the 261 shipped cases (see
`--selftest`; agreement is to ~2 ULP, not bitwise -- the residual is the order
of summation inside numpy's matmul, and the inputs are byte-identical).

    --ils-scale                 instrument line width, as a multiple of the
                                measured ILS sigma.  Values other than 1.0
                                REBUILD the cross sections from the raw
                                high-resolution sources (reference_data/raw
                                for NO2 and CHOCHO, HITRAN line list for H2O),
                                because an already-convolved section cannot be
                                narrowed and should not be broadened twice.
    --window-scale              window width, about its centre
    --pixel-dispersion-scale    nm per pixel, about the window centre; the ILS
                                width in nm is held fixed, so this changes the
                                line width measured in pixels
    --noise-levels              group B white-noise levels, as multiples of
                                NOISE_RMS (the AR(1) replicate set is always
                                added on top)
    --poly-orders               order of the baseline that is PUT INTO the
                                spectra; more than one value suffixes the
                                case ids.  Measured 2026-09-23: varying this
                                alone changes nothing a retrieval can see,
                                because a fit at the channel order absorbs a
                                lower-order true baseline exactly.
    --fit-poly-order            order the SUBMITTER is told to fit with
                                (manifest column `fit_poly_order`); default is
                                each channel's operational order.  This is the
                                axis that moves.

⚠ The random draws are one shared stream consumed in case order, so any change
that adds, removes or reorders cases changes every noisy case after it.  That
is intended: a different instrument coordinate is a different data set, not a
perturbation of this one.
"""
import argparse
import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.interpolate import interp1d
from scipy.ndimage import gaussian_filter1d

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
OUT = Path("bench/doas_benchmark_v1")
MULT = {"NO2": 0, "CHOCHO": 0, "H2O": -12}
NOISE_RMS = 6.16e-9
SEED = 20260921

CHANNELS = {
    "hot_PNs": dict(
        src=_REPO / "reference_data" / "wv_cal" / "roi1",
        calib="Calib_20260619_Hg_400-499nm_Poly2.txt",
        fwhm="FWHM_Analysis_20260619.txt",
        refs={"NO2": "Ref_NO2_Dynamic-ILS-Applied.dat",
              "CHOCHO": "Ref_CHOCHO_Dynamic-ILS-Applied.dat",
              "H2O": "Ref_H2O-HITRAN_Dynamic-ILS-Applied.dat"},
        window_nm=(444.146, 470.685), poly=3),
    "cold": dict(
        src=_REPO / "reference_data" / "wv_cal" / "cold",
        calib="Calib_20260523_Hg_4line_400-497nm_Poly2.txt",
        fwhm="FWHM_Analysis_20260610_4line.txt",
        refs={"NO2": "Ref_NO2_Dynamic-ILS-Applied.dat",
              "CHOCHO": "Ref_CHOCHO_Dynamic-ILS-Applied.dat",
              "H2O": "Ref_H2O-HITRAN_Dynamic-ILS-Applied.dat"},
        window_nm=(438.420, 475.741), poly=4),
}
BASE = [1.85e-7, -4.0e-9, 1.2e-9, -3.0e-10]
# Enough coefficients for --poly-orders up to 6.  The first four are BASE, so
# order 3 is unchanged.
BASE_EXT = BASE + [8e-11, -2e-11, 5e-12]

# High-resolution sources for --ils-scale, and the resolution they were
# published at (subtracted in variance; same numbers as calibration/build_cold_refs.py).
RAW_DIR = _REPO / "reference_data" / "raw"
RAW_XS = {"NO2": "NO2_Vandaele(2002)_294K_384-725nm(vis-dilut5).txt",
          "CHOCHO": "CHOCHO_Volkamer(2005)_296K_250.031-526.168nm(0.001nm).txt"}
LIT_FWHM = {"NO2": 0.01156, "CHOCHO": 0.01, "H2O": 0.0}
HITRAN_DIR = _REPO / "hitran_data"


def read_col(p, mult=0):
    v = np.asarray([float(l) for l in Path(p).read_text().splitlines()
                    if l.strip() and not l.startswith("#")], float)
    return v * 10.0 ** mult


def read_two_col(p):
    """Raw literature cross section: wavelength_nm <ws> sigma_cm2."""
    a = np.loadtxt(p)
    o = np.argsort(a[:, 0])
    return a[o, 0], a[o, 1]


def read_ils_sigma_nm(path, n_px):
    """FWHM_Analysis_*.txt -> per-pixel instrument sigma in nm (linear in pixel)."""
    px, sg = [], []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        t = line.split()
        if len(t) < 4 or line.startswith("#") or not t[0][0].isdigit():
            continue
        px.append(float(t[0]))
        sg.append(float(t[3]))
    if len(px) < 2:
        raise SystemExit(f"ABSTAIN: {path} has no usable FWHM rows")
    f = interp1d(np.asarray(px), np.asarray(sg), kind="linear", fill_value="extrapolate")
    return np.asarray(f(np.arange(n_px, dtype=float)), float)


def hitran_h2o(w_min, w_max):
    """H2O from the HITRAN line list, as calibration/build_cold_refs.py does it.

    Option B of the 2026-09-23 decision: the shipped H2O section is already
    ILS-applied, so an ILS axis has to start from the line list.
    """
    import hapi
    d = Path(HITRAN_DIR)
    if not (d / "H2O_Lines.data").exists():
        raise SystemExit(
            f"ABSTAIN: no HITRAN H2O line list at {d}. It is a per-machine cache "
            "(.gitignore: hitran_data/). Point --hitran-dir at it, or fetch it with "
            "hapi.fetch('H2O_Lines', 1, 1, nu_min, nu_max).")
    hapi.db_begin(str(d))
    nu, coef = hapi.absorptionCoefficient_Voigt(
        SourceTables="H2O_Lines", Environment={"p": 1.0, "T": 293.0},
        OmegaStep=0.02, HITRAN_units=False)
    wl = 1e7 / np.asarray(nu, float)
    o = np.argsort(wl)
    wl, coef = wl[o], np.asarray(coef, float)[o]
    m = (wl >= w_min - 10.0) & (wl <= w_max + 10.0)
    return wl[m], coef[m]


def convolve_dynamic_ils(raw_w, raw_v, target_wl, sigma_nm, lit_fwhm_nm,
                         hr_step=0.002, n_sigma=5.0):
    """Per-pixel Gaussian ILS, same convention as
    `gui/reference_generator_dialog.ReferenceGeneratorDialog.apply_convolution`
    (variance subtraction, 0.002 nm integration grid, direct sampling when the
    added kernel would be narrower than the grid).  The kernel is truncated at
    n_sigma, which the dialog does not do -- checked to 1e-12 relative.
    """
    lit_sigma = float(lit_fwhm_nm) / 2.35482
    hr_w = np.arange(target_wl.min() - 5.0, target_wl.max() + 5.0, hr_step)
    f_raw = interp1d(raw_w, raw_v, kind="linear", bounds_error=False, fill_value=0.0)
    hr_v = f_raw(hr_w)
    out = np.zeros(len(target_wl))
    for i, w in enumerate(target_wl):
        var = float(sigma_nm[i]) ** 2 - lit_sigma ** 2
        if not np.isfinite(sigma_nm[i]) or sigma_nm[i] <= 0 or var <= (2.0 * hr_step) ** 2:
            out[i] = float(f_raw(w))
            continue
        half = n_sigma * np.sqrt(var)
        lo = int(np.searchsorted(hr_w, w - half))
        hi = int(np.searchsorted(hr_w, w + half))
        x = hr_w[lo:hi]
        k = np.exp(-0.5 * (x - w) ** 2 / var) / np.sqrt(2 * np.pi * var)
        out[i] = float(np.dot(hr_v[lo:hi], k) * hr_step)
    return out


def rebuild_sigma(ch, target_wl, ils_scale):
    """Cross sections at `ils_scale` x the measured instrument ILS width."""
    cfg = CHANNELS[ch]
    sigma_nm = read_ils_sigma_nm(cfg["src"] / cfg["fwhm"], len(target_wl)) * float(ils_scale)
    out = {}
    for g in cfg["refs"]:
        if g == "H2O":
            rw, rv = hitran_h2o(float(target_wl.min()), float(target_wl.max()))
        else:
            rw, rv = read_two_col(RAW_DIR / RAW_XS[g])
        out[g] = convolve_dynamic_ils(rw, rv, target_wl, sigma_nm, LIT_FWHM[g]) * 10.0 ** MULT[g]
    return out


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


def load(ch, args):
    cfg = CHANNELS[ch]
    wl = read_col(cfg["src"] / cfg["calib"])

    if args.pixel_dispersion_scale != 1.0:
        # nm per pixel x s, about the window centre.  The pixel index grid is
        # unchanged, so the detector covers a wider (or narrower) band at a
        # coarser (finer) sampling; the ILS width in nm is untouched, which is
        # what a grating/slit change does.
        c = 0.5 * (cfg["window_nm"][0] + cfg["window_nm"][1])
        wl = c + (wl - c) * float(args.pixel_dispersion_scale)

    if args.ils_scale != 1.0 or getattr(args, "rebuild_sigma", False):
        sig = rebuild_sigma(ch, wl, args.ils_scale)
    else:
        sig = {g: read_col(cfg["src"] / f, MULT[g]) for g, f in cfg["refs"].items()}
        if args.pixel_dispersion_scale != 1.0:
            # sections live on the original calibration grid -> move them to the
            # new wavelength of each pixel, keeping their nm-domain shape
            wl0 = read_col(cfg["src"] / cfg["calib"])
            sig = {g: np.asarray(interp1d(wl0, v, kind="cubic", bounds_error=False,
                                          fill_value=0.0)(wl), float)
                   for g, v in sig.items()}
        assert all(len(v) == len(wl) for v in sig.values()), f"{ch}: grid mismatch"

    w0, w1 = cfg["window_nm"]
    if args.window_scale != 1.0:
        c, half = 0.5 * (w0 + w1), 0.5 * (w1 - w0) * float(args.window_scale)
        w0, w1 = c - half, c + half
    m = (wl >= w0) & (wl <= w1)
    px = np.where(m)[0].astype(float)
    if len(px) < 50:
        raise SystemExit(f"ABSTAIN: {ch} window holds only {len(px)} pixels")
    cfg = dict(cfg, window_nm=(w0, w1))
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


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(OUT), help="output package directory")
    ap.add_argument("--ils-scale", type=float, default=1.0)
    ap.add_argument("--rebuild-sigma", action="store_true",
                    help="rebuild the cross sections from the raw sources even at "
                         "--ils-scale 1.0. An ILS sweep should set this on every "
                         "coordinate including the baseline: the HITRAN H2O rebuilt "
                         "here is ~2.5 %% larger in peak than the shipped section, so "
                         "mixing rebuilt and shipped coordinates confounds the axis.")
    ap.add_argument("--window-scale", type=float, default=1.0)
    ap.add_argument("--pixel-dispersion-scale", type=float, default=1.0)
    ap.add_argument("--noise-levels", type=float, nargs="+", default=[1.0, 2.0],
                    help="group B white-noise levels as multiples of NOISE_RMS")
    ap.add_argument("--poly-orders", type=int, nargs="+", default=[3],
                    help="order of the baseline PUT INTO the spectra; >1 suffixes case ids")
    ap.add_argument("--fit-poly-order", type=int, default=None,
                    help="order the submitter is told to fit with (default: channel's)")
    ap.add_argument("--hitran-dir", default=str(HITRAN_DIR),
                    help="HITRAN H2O_Lines cache; only read when --ils-scale != 1")
    ap.add_argument("--coordinate-id", default="",
                    help="recorded in manifest.json; does not change the data")
    ap.add_argument("--selftest", action="store_true",
                    help="regenerate with defaults and compare with the shipped package")
    return ap.parse_args(argv)


def main(args=None):
    args = args or parse_args([])
    global HITRAN_DIR
    HITRAN_DIR = Path(getattr(args, "hitran_dir", HITRAN_DIR))
    out_dir = Path(args.out)
    rng = np.random.default_rng(SEED)
    L = {ch: load(ch, args) for ch in CHANNELS}
    peak = {ch: {g: float(np.max(np.abs(L[ch][1][g][L[ch][2]]))) for g in CHANNELS[ch]["refs"]}
            for ch in CHANNELS}
    rows, spectra = [], {}
    multi_poly = len(args.poly_orders) > 1

    def fit_order(ch):
        return (int(args.fit_poly_order) if args.fit_poly_order is not None
                else CHANNELS[ch]["poly"])

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
                         fit_poly_order=fit_order(ch), fit_etalon_f=0.12))

    def amt(ch, g, target):
        return target / peak[ch][g]

    def three(ch):
        return dict(CHOCHO=amt(ch, "CHOCHO", 2.0e-9), H2O=amt(ch, "H2O", 3.0e-8))

    H = "hot_PNs"
    for order in args.poly_orders:
        base = BASE_EXT[:order + 1]
        sfx = f"_p{order}" if multi_poly else ""
        # A - exact recovery, noise free
        for tgt in (2e-9, 2e-8, 1e-7, 4e-7):
            for d in (0.0, -2.0, 2.0, -4.0):
                t = f"a{tgt:.0e}_s{d:+.0f}".replace("+", "p").replace("-", "m")
                add("A_1gas_" + t + sfx, H, "A_exact",
                    "numerical recovery; integer shift and unit squeeze, so no "
                    "sub-pixel resampling is involved for any implementation",
                    {"NO2": amt(H, "NO2", tgt)}, d, 1.000, base)
                add("A_3gas_" + t + sfx, H, "A_exact",
                    "numerical recovery, three absorbers; integer shift, unit squeeze",
                    dict(NO2=amt(H, "NO2", tgt), **three(H)), d, 1.000, base)

        # B - noise replicates: does the reported uncertainty equal the scatter
        levels = ([(f"n{m:g}", m * NOISE_RMS, 0.0) for m in args.noise_levels]
                  + [("ar", NOISE_RMS, 0.5)])
        for tag, nz, ar in levels:
            for k in range(60):
                add(f"B_{tag}_{k:03d}" + sfx, H, "B_noise",
                    "uncertainty calibration: 60 replicates of one truth",
                    dict(NO2=amt(H, "NO2", 2e-8), **three(H)), -2.0, 1.002, base,
                    noise=nz, ar1=ar)

        # C - model mismatch, noise free so the bias is unambiguous
        for ex in (0.25, 0.5, 1.0, 3.0):
            add(f"C_ils_{ex:g}px" + sfx, H, "C_mismatch",
                "reference convolved with extra ILS width",
                dict(NO2=amt(H, "NO2", 2e-8), **three(H)), -2.0, 1.002, base, ils_extra_px=ex)
        for fr in (0.005, 0.01, 0.02):
            for f in (0.12, 0.16, 0.35):
                add(f"C_etalon_a{fr:g}_f{f:g}" + sfx, H, "C_mismatch",
                    "etalon present at f; fit uses the fixed operational f = 0.12",
                    dict(NO2=amt(H, "NO2", 2e-8), **three(H)), -2.0, 1.002, base,
                    etalon=(fr * 1.85e-7, f, 0.7))
        for tgt in (2e-9, 2e-8, 1e-7):
            add(f"C_missing_a{tgt:.0e}" + sfx, H, "C_mismatch",
                "CHOCHO and H2O present; submitter is told to fit NO2 only",
                dict(NO2=amt(H, "NO2", tgt), **three(H)), -2.0, 1.002, base)
            rows[-1]["gases_to_fit"] = "NO2"

        # D - identifiability: a high-order baseline absorbs the shift
        for d in (-4.0, -2.0, 0.0, 2.0, 4.0):
            add("D_flat_s" + f"{d:+.0f}".replace("+", "p").replace("-", "m") + sfx, H,
                "D_identifiability",
                "shift is not constrained; a code should report that, not a value",
                dict(NO2=amt(H, "NO2", 6e-9), **three(H)), d, 1.002,
                base + BASE_EXT[order + 1:order + 3], noise=NOISE_RMS)
            # D is generated with two extra baseline terms and fitted two
            # orders above the channel -- that gap is what makes shift
            # unidentifiable, so it follows the fit order.
            rows[-1]["fit_poly_order"] = fit_order(H) + 2

        # E - the same truth in two windows
        for k, (tgt, d) in enumerate([(2e-8, 0.0), (2e-8, -2.0), (2e-8, 2.0),
                                      (1e-7, 0.0), (1e-7, -2.0),
                                      (4e-7, 0.0), (4e-7, -2.0), (4e-7, 2.0)]):
            pid = f"E{k:02d}" + sfx
            for ch in ("hot_PNs", "cold"):
                add(f"E_{ch}_{pid}", ch, "E_window",
                    "same truth in two windows; the answer should not depend on the window",
                    dict(NO2=amt(ch, "NO2", tgt), **three(ch)), d, 1.002, base,
                    pair_id=pid, noise=NOISE_RMS)

        # F - sub-pixel resampling. Generated band-limited, so neither a linear nor a
        # cubic interpolator reproduces it; the spread between them is the quantity.
        for tgt in (2e-8, 1e-7, 4e-7):
            for d in (-1.96, -0.37, 0.41, 2.63):
                t = f"a{tgt:.0e}_s{d:+.2f}".replace("+", "p").replace("-", "m").replace(".", "")
                add("F_subpix_" + t + sfx, H, "F_subpixel",
                    "non-integer shift with squeeze; truth uses band-limited sub-pixel "
                    "resampling, so the result depends on the interpolator chosen",
                    dict(NO2=amt(H, "NO2", tgt), **three(H)), d, 1.002, base,
                    bandlimited=True)

    man = pd.DataFrame(rows)
    (out_dir / "reference").mkdir(parents=True, exist_ok=True)
    (out_dir / "cases").mkdir(parents=True, exist_ok=True)
    for ch in CHANNELS:
        wl, sig, m, px, centre, cfg = L[ch]
        pd.DataFrame({"pixel": np.arange(len(wl)), "wavelength_nm": wl,
                      **{f"sigma_{g}_cm2": sig[g] for g in cfg["refs"]}}).to_csv(
            out_dir / "reference" / f"cross_sections_{ch}.csv", index=False)
    man.to_csv(out_dir / "cases" / "manifest.csv", index=False)
    grids = {}
    for ch in CHANNELS:
        wl, sig, m, px, centre, cfg = L[ch]
        grids[f"pixel__{ch}"] = px.astype(int)
        grids[f"wavelength_nm__{ch}"] = wl[m]
    np.savez_compressed(out_dir / "cases" / "spectra.npz", **grids, **spectra)
    meta = dict(name="DOAS extinction-domain retrieval benchmark", version=2, seed=SEED,
                n_cases=int(len(man)), alpha_units="cm-1", sigma_units="cm2 molec-1",
                noise_rms_cm1=NOISE_RMS, reference_multiplier_applied=MULT,
                shift_convention="p_prime = centre + (p - centre) * squeeze + shift_px",
                channels={ch: dict(window_nm=list(L[ch][5]["window_nm"]),
                                   poly_order=CHANNELS[ch]["poly"],
                                   window_pixels=[int(L[ch][3][0]), int(L[ch][3][-1])],
                                   n_pixels=int(len(L[ch][3])),
                                   centre_pixel=L[ch][4]) for ch in CHANNELS},
                cross_section_provenance=(
                    "instrument-convolved references from a two-channel thermal-dissociation "
                    "BBCEAS; NO2 after Vandaele et al., CHOCHO after Volkamer et al., H2O from "
                    "HITRAN. Cite the original cross-section papers, not this package."),
                groups={g: int(n) for g, n in man.group.value_counts().items()})
    coord = dict(coordinate_id=args.coordinate_id, ils_scale=args.ils_scale,
                 rebuild_sigma=bool(getattr(args, "rebuild_sigma", False)),
                 window_scale=args.window_scale,
                 pixel_dispersion_scale=args.pixel_dispersion_scale,
                 noise_levels=list(args.noise_levels), poly_orders=list(args.poly_orders),
                 fit_poly_order=args.fit_poly_order)
    if coord != dict(coordinate_id="", ils_scale=1.0, rebuild_sigma=False,
                     window_scale=1.0, pixel_dispersion_scale=1.0,
                     noise_levels=[1.0, 2.0], poly_orders=[3], fit_poly_order=None):
        meta["instrument_coordinate"] = coord
    (out_dir / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return man, meta


def selftest():
    """Defaults must reproduce the shipped package (to a few ULP)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        a = parse_args([])
        a.out = td
        man, meta = main(a)
        # np.load keeps the zip open; Windows will not delete the temp dir otherwise
        with np.load(Path(td) / "cases" / "spectra.npz") as z:
            got = {k: np.asarray(z[k], float) for k in z.files}
        with np.load(_HERE / "cases" / "spectra.npz") as z:
            want = {k: np.asarray(z[k], float) for k in z.files}
        assert set(got) == set(want), "case set changed"
        worst, where = 0.0, ""
        for k in want:
            g, w = got[k], want[k]
            assert g.shape == w.shape, k
            r = np.max(np.abs(g - w)) / max(np.max(np.abs(w)), 1e-300)
            if r > worst:
                worst, where = r, k
        # compare the written CSVs, not the in-memory frame: a round trip through
        # CSV normalises dtypes, and it is the file that ships
        ref = pd.read_csv(_HERE / "cases" / "manifest.csv")
        new = pd.read_csv(Path(td) / "cases" / "manifest.csv")
        assert new.equals(ref), "manifest.csv changed"
        assert worst < 1e-13, f"spectra differ by {worst:.3e} at {where}"
        print(f"selftest OK: {len(want) - 4} cases, manifest identical, "
              f"worst relative spectrum difference {worst:.3e} at {where}")
        print("  (not bitwise: numpy's matmul summation order is not pinned; "
              "the input files are byte-identical)")


if __name__ == "__main__":
    _a = parse_args()
    if _a.selftest:
        selftest()
    else:
        man, meta = main(_a)
        print(json.dumps(meta["channels"], indent=1))
        print("n_cases", meta["n_cases"])
        print(man.group.value_counts().to_string())
