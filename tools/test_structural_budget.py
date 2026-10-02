# -*- coding: utf-8 -*-
"""tools/test_structural_budget.py — per-record structural terms end to end on synthetic data (2026-10-03).

Synthetic campaign: hourly zero-air knots with 0.3 % noise, R(t) knots, a known 5 ppb NO₂, ambient
intensities built so that the production alpha equation reproduces it exactly. Then:

  1) core.structural inversion: the perturbed alpha equals re-assembly from the true intensity
  2) tools/structural_budget.py: base NO₂ recovers the truth, i0/rt terms are non-zero (noisy knots),
     ef is 0 with the etalon term off, tri ≈ i0 + rt (additivity), records at edge knots skipped
  3) --result: the fit result copy gets NO2_Struct = |tri| on the matching rows

    python tools/test_structural_budget.py
"""
import json
import os
import shutil
import sys
import tempfile

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "tools")]

from core.physics import RayleighPhysics, air_number_density, bbceas_alpha
from core.step_guard import SegmentedPchip
from core.structural import CalibKnots

NPX, NK, PER = 2048, 6, 8          # pixels, zero-air knots (hourly), records per hour
T, P, PPB = 25.0, 1000.0, 5.0


def build(tmp):
    rng = np.random.default_rng(5)
    wave = np.linspace(400.0, 500.0, NPX)
    np.savetxt(os.path.join(tmp, "wavecal.txt"), wave)
    sig = 3e-19 * (1 + np.sin(wave / 0.9)) * np.exp(-((wave - 450) / 25) ** 2)
    sig_h2o = 1e-24 * (1 + np.cos(wave / 0.4)) * np.exp(-((wave - 470) / 10) ** 2)
    for nm, s in (("NO2", sig), ("H2O", sig_h2o)):
        np.savetxt(os.path.join(tmp, f"Ref_{nm}.dat"), np.column_stack([wave, s]))
    x = 140 * 86400.0 + np.arange(NK) * 3600.0
    za = 30000.0 * (1 + 0.003 * rng.normal(size=(NK, NPX)))
    rsec = x + 120.0
    omr = 2e-6 * (1 + 0.002 * rng.normal(size=(NK, NPX)))
    za_ref = RayleighPhysics.get_alpha_rayleigh(wave, 0.0, 1013.25, "zero_air")
    knots = dict(za_x=x, za_arr=za, za_t=np.full(NK, T), za_p=np.full(NK, P), i0_breaks=np.zeros(0),
                 wave_nm=wave, pix_min=0, rl_factor=1.0, za_ref=za_ref, r_sec=rsec, r_omr=omr,
                 r_breaks=np.zeros(0), rt_path="synthetic")
    np.savez_compressed(os.path.join(tmp, "calib_knots_ANs.npz"), **knots)
    pi0, por = SegmentedPchip(x, za), SegmentedPchip(rsec, omr)
    a_ref = za_ref * (P / 1013.25) * (273.15 / (T + 273.15))
    a_gas = sig * PPB * 1e-9 * air_number_density(T, P)
    lines, recs = [], []
    for h in range(NK - 1):
        for j in range(PER):
            sec = x[h] + (j + 0.5) * 3600.0 / PER
            I0, om = np.asarray(pi0(sec)), np.asarray(por(sec))
            q = (a_gas + a_ref - a_ref) / (om + a_ref)
            I = I0 / (1 + q)
            a = bbceas_alpha(I, I0, om, a_ref, a_ref, 1.0)
            recs.append((sec, I))
            lines.append(f"{len(lines)}\t{sec / 86400 + 1:.8f}\tx\t{T:.2f}\t{P:.2f}\t"
                         + "\t".join(f"{v:.9e}" for v in a))
    ap = os.path.join(tmp, "2026-05-20-001_ANs_alpha_trace.dat")
    with open(ap, "w", encoding="utf-8") as f:
        f.write("# synthetic\n# wavelength_nm:\t" + "\t".join(f"{w:.4f}" for w in wave) + "\n")
        f.write("row_idx\tdoy\tdatetime\tT_C\tP_mbar\t" + "\t".join(f"px{k}" for k in range(NPX)) + "\n")
        f.write("\n".join(lines) + "\n")
    cfg = {"wl_path": os.path.join(tmp, "wavecal.txt"),
           "refs": [{"name": "NO2", "path": os.path.join(tmp, "Ref_NO2.dat"), "mult": 19},
                    {"name": "H2O", "path": os.path.join(tmp, "Ref_H2O.dat"), "mult": 24}],
           "f_min": "800", "f_max": "1300", "poly_deg": 3, "allow_negative_gas": True, "use_etalon": False,
           "data_label": "ANs",
           "ref_props": {"NO2": {"sh_mode": "Limit", "sh_val": "-2, 2", "sq_mode": "Fix", "sq_val": "1.0"},
                         "H2O": {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Fix", "sq_val": "1.0"}}}
    fs = os.path.join(tmp, "FitSet.json")
    json.dump({"channels": {"1": cfg}}, open(fs, "w", encoding="utf-8"))
    return ap, fs, knots, recs, a_ref


def main():
    tmp = tempfile.mkdtemp()
    try:
        ap, fs, knots, recs, a_ref = build(tmp)
        K = CalibKnots(knots)
        sec, I = recs[10]
        from core.data_io import DataIO
        hdr, _w, data = DataIO._alpha_file(ap)
        a = np.array([float(v) for v in data[10].split("\t")[5:]])
        p = K.perturbed(a, sec, T, P)
        want = bbceas_alpha(I, np.asarray(K._i0_loo(p["k"])(sec)), np.asarray(K._por(sec)), a_ref, a_ref, 1.0)
        assert np.allclose(p["i0"], want, rtol=1e-6, atol=1e-16), "inverted alpha ≠ re-assembly from I"
        print("  PASS  inversion: perturbed alpha == re-assembly from the true intensity")

        res = os.path.join(tmp, "result.dat")
        with open(res, "w", encoding="utf-8") as f:
            f.write("# Augur Analysis Report\nFile\tChannel\tNO2\tNO2_Error\n")
            for i in range(len(recs)):
                f.write(f"2026-05-20-001_ANs_alpha_trace.dat [{i:04d}]\t1\t5.0\t0.1\n")
        from structural_budget import main as sb_main
        sb_main(["--fitset", fs, "--alpha", ap, "--knots", os.path.join(tmp, "calib_knots_ANs.npz"),
                 "--channel", "1", "--jobs", "1", "--result", res])
        import pandas as pd
        d = pd.read_csv(os.path.join(tmp, "structural_ANs.csv"))
        inner = sum(1 for s, _ in recs if 0 < K.nearest_za(s) < NK - 1)
        assert len(d) == inner, (len(d), inner)
        assert np.allclose(d.NO2, PPB, rtol=0.05), d.NO2.describe()
        assert d.NO2_d_i0.abs().median() > 1e-3 and d.NO2_d_rt.abs().median() > 1e-5
        assert np.allclose(d.NO2_d_ef, 0.0, atol=1e-9), "etalon off: ef term must be 0"
        add = d.NO2_d_tri - (d.NO2_d_i0 + d.NO2_d_rt)
        assert add.abs().max() < 0.05 * d.NO2_d_tri.abs().max() + 1e-6, "tri ≉ i0 + rt"
        print(f"  PASS  tool: {len(d)} records, base NO2 {d.NO2.median():.3f} ppb (truth {PPB}), "
              f"i0 rSD {d.NO2_d_i0.std():.4f}, ef 0, tri ≈ i0 + rt")
        m = pd.read_csv(os.path.join(tmp, "result_struct.dat"), sep="\t", comment="#")
        assert np.isfinite(m.NO2_Struct).sum() == inner and (m.NO2_Struct.dropna() >= 0).all()
        print("  PASS  --result: NO2_Struct on the matching rows, NaN elsewhere")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_structural_budget: OK")


if __name__ == "__main__":
    main()
