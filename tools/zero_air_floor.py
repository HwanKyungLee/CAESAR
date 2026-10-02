#!/usr/bin/env python
"""Measured noise floor and MDL from the zero-air LOO alpha (manuscript §7.2, product tool, 2026-10-03).

Alpha generation writes `{campaign}/_zeroair/zeroair_loo_<label>_…_alpha_trace.dat`: every inner
zero-air block as a measurement whose truth is 0, I₀ interpolated from the *other* blocks — the
same assembly as an ambient row. Fitting those rows with the production FitSet gives the floor the
product actually has, I₀ interpolation included:

    σ_ZA (robust and SD) · median at a true zero (bias) · MDL = 3σ · ratio to the reported <gas>_Error

For a channel-difference product (ΣANs = ch1 − g′·ch2) give both channels: blocks are paired by time
and the floor is measured on the difference (the channels share light source, cavity and clock, so
a quadrature sum assumes an independence nothing guarantees — the correlation is reported).

Shift is held fixed (default) at the operational centre: zero air has nothing to align, and a free
shift sticks to the box edge in most blocks, which selects the quieter ones and biases σ low
(diagnostics/i0_interp_2026-09/zero_air_floor.py). The etalon frequency is fixed too.

A zero-air block averages fewer scans than an ambient bin (34 vs 60 s). The σ is reported as
measured (upper bound for an ambient bin) and photon-noise scaled by √(N_za/N_amb) (lower bound —
I₀ interpolation error does not scale with N).

    python tools/zero_air_floor.py --fitset FitSet.json \
        --za <campaign>/_zeroair/zeroair_loo_ANs_….dat --channel 1 --shift -6.12 \
        [--za-b <…PNs….dat> --channel-b 2 --shift-b -0.51 --ratio 0.9524]

Writes <za file>.floor.json next to the first input.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OPERATIONAL_EF = 0.12      # manuscript operational etalon frequency (fixed per run)


def rsd(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) if v.size else float("nan")


def fixed_shift_props(ref_props, shift):
    """Limit-mode shifts → Fix at `shift`; Link/Fix/Free untouched (links follow the fixed gas)."""
    rp = copy.deepcopy(ref_props)
    for pr in rp.values():
        if pr.get("sh_mode") in ("Limit", "Center"):
            pr["sh_mode"], pr["sh_val"] = "Fix", "%.6g" % shift
    return rp


def read_rows(path):
    """[(sec, wave, alpha, T, P)] from an alpha trace (any px start)."""
    from core.data_io import DataIO
    first_px, t_idx, p_idx, px_start, wave = DataIO._alpha_layout(path)
    hdr, _w, data = DataIO._alpha_file(path)
    di = hdr.index("doy")
    out = []
    for line in data:
        t = line.split("\t")
        out.append(((float(t[di]) - 1.0) * 86400.0, np.asarray(wave, float),
                    np.array([float(v) for v in t[first_px:]], float),
                    float(t[t_idx]), float(t[p_idx])))
    return out, int(px_start)


def fit_channel(path, cfg, shift, ef, target="NO2"):
    """Fit every zero-air row → dict of arrays (sec, value, error, error_corr) in ppb."""
    from core import param_optimizer as PO
    from core.doas_fit import DoasFitter
    from optimize_params import build_engine_from_config
    eng = build_engine_from_config(cfg)
    fitter = DoasFitter(eng)
    rp = cfg.get("ref_props") or {}
    if shift is not None:
        rp = fixed_shift_props(rp, shift)
    rows, px0 = read_rows(path)
    lo, hi = int(cfg["f_min"]) - px0, int(cfg["f_max"]) - px0
    neg = bool(cfg.get("allow_negative_gas", True))
    res = {"sec": [], "value": [], "error": [], "error_corr": [], "n_bound": 0, "n_fail": 0}
    for sec, wave, alpha, T, P in rows:
        try:
            r = PO.fit_scan(eng, fitter, rp, wave, alpha, T, P, lo, hi, int(cfg["poly_deg"]),
                            float(cfg.get("step_limit", 0.5)), target=target, allow_negative_gas=neg,
                            return_solver_diagnostics=True, use_etalon=bool(cfg.get("use_etalon", True)),
                            etalon_freq=ef)
        except Exception:      # noqa: BLE001 — count it, keep going
            res["n_fail"] += 1
            continue
        d = r.get("solver_diagnostics") or {}
        if d.get("theta_bound_hits") or not np.isfinite(r["conc"]):
            res["n_bound"] += 1
            continue
        err = abs(r["perr_rel"] * r["conc"])
        gi = eng.gas_list.index(target)
        pc = None
        try:
            pc = float(d["perr_corr"][gi])
        except (KeyError, IndexError, TypeError):
            pass
        res["sec"].append(sec); res["value"].append(r["conc"]); res["error"].append(err)
        # sandwich/white ratio on the coefficient errors; perr_corr is in the scaled (×normalization)
        # coefficient space, perr_rel·|coeff| in the unscaled one
        coeff_err = abs(r["perr_rel"] * r["coeffs"][target]) * r["normalization_factor"]
        res["error_corr"].append(err * pc / coeff_err if (pc is not None and coeff_err) else np.nan)
    return {k: (np.asarray(v, float) if isinstance(v, list) else v) for k, v in res.items()}


def summary(v, reported):
    m_r, m_s = rsd(v), float(np.std(v, ddof=1)) if len(v) > 1 else float("nan")
    return {"n": int(len(v)), "median_at_zero": float(np.median(v)) if len(v) else float("nan"),
            "sigma_rsd": m_r, "sigma_sd": m_s, "mdl_3rsd": 3 * m_r, "mdl_3sd": 3 * m_s,
            "reported_error_median": reported,
            "ratio_rsd_to_reported": m_r / reported if reported else float("nan"),
            "ratio_sd_to_reported": m_s / reported if reported else float("nan")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fitset", required=True)
    ap.add_argument("--za", required=True, help="zero-air LOO alpha of channel A")
    ap.add_argument("--channel", required=True, help="FitSet channel key of A (e.g. 1)")
    ap.add_argument("--shift", type=float, help="fixed shift for A (px, operational centre)")
    ap.add_argument("--za-b", help="zero-air LOO alpha of channel B (difference product)")
    ap.add_argument("--channel-b")
    ap.add_argument("--shift-b", type=float)
    ap.add_argument("--ratio", type=float, default=0.9524, help="g′ in ΣANs = A − g′·B")
    ap.add_argument("--free-shift", action="store_true",
                    help="leave shift free (box-edge selection biases σ low — for comparison only)")
    ap.add_argument("--etalon-f", type=float, default=OPERATIONAL_EF)
    ap.add_argument("--target", default="NO2")
    ap.add_argument("--za-scans", type=float, default=34.0, help="scans per zero-air block")
    ap.add_argument("--amb-scans", type=float, default=60.0, help="scans per ambient bin")
    a = ap.parse_args(argv)
    if not a.free_shift and a.shift is None:
        ap.error("--shift is required (operational shift centre), or pass --free-shift")
    chans = json.load(open(a.fitset, encoding="utf-8"))["channels"]
    scale = float(np.sqrt(a.za_scans / a.amb_scans))

    out = {"fitset": os.path.basename(a.fitset), "target": a.target, "etalon_f": a.etalon_f,
           "shift_fixed": not a.free_shift, "za_scans": a.za_scans, "amb_scans": a.amb_scans}
    fits = {}
    for tag, path, key, sh in (("A", a.za, a.channel, a.shift), ("B", a.za_b, a.channel_b, a.shift_b)):
        if not path:
            continue
        f = fit_channel(path, chans[str(key)], None if a.free_shift else sh, a.etalon_f, a.target)
        fits[tag] = f
        s = summary(f["value"], float(np.median(f["error"])) if len(f["error"]) else float("nan"))
        s.update(file=os.path.basename(path), channel=str(key), n_bound=f["n_bound"], n_fail=f["n_fail"],
                 error_corr_median=float(np.nanmedian(f["error_corr"])) if len(f["error_corr"]) else float("nan"),
                 sigma_rsd_scaled_to_ambient=s["sigma_rsd"] * scale)
        out[f"channel_{tag}"] = s
        print(f"[{tag}] CH{key} n={s['n']} (bound {f['n_bound']}, failed {f['n_fail']})  "
              f"median {s['median_at_zero']:+.4f}  σ rSD {s['sigma_rsd']:.4f} / SD {s['sigma_sd']:.4f} ppb  "
              f"MDL 3σ {s['mdl_3rsd']:.3f}–{s['mdl_3sd']:.3f}  reported {s['reported_error_median']:.4f} "
              f"({s['ratio_rsd_to_reported']:.2f}×; scaled to {a.amb_scans:g} scans "
              f"{s['sigma_rsd_scaled_to_ambient'] / s['reported_error_median']:.2f}×)")
    if "A" in fits and "B" in fits:
        A, B = fits["A"], fits["B"]
        ka, kb = np.round(A["sec"], 0), np.round(B["sec"], 0)
        common, ia, ib = np.intersect1d(ka, kb, return_indices=True)
        if len(common) >= 10:
            d = A["value"][ia] - a.ratio * B["value"][ib]
            rep = float(np.median(np.hypot(A["error"][ia], a.ratio * B["error"][ib])))
            s = summary(d, rep)
            r = float(np.corrcoef(A["value"][ia], B["value"][ib])[0, 1])
            quad = float(np.hypot(rsd(A["value"][ia]), a.ratio * rsd(B["value"][ib])))
            s.update(ratio_g=a.ratio, paired_blocks=int(len(common)), inter_channel_r=r,
                     quadrature_rsd=quad, reported_is="median quadrature of the channel _Error")
            out["difference"] = s
            print(f"[A − {a.ratio:g}·B] paired {len(common)} blocks  r={r:+.3f}  median {s['median_at_zero']:+.4f}  "
                  f"σ rSD {s['sigma_rsd']:.4f} / SD {s['sigma_sd']:.4f}  MDL 3σ {s['mdl_3rsd']:.3f}–{s['mdl_3sd']:.3f}  "
                  f"(quadrature would say {quad:.4f})")
        else:
            print(f"[A − g′·B] only {len(common)} blocks pair by time — not computed")
    from core.provenance import code_version
    out["code"] = code_version()
    dst = a.za + ".floor.json"
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(f"→ {dst}")
    return out


if __name__ == "__main__":
    main()
