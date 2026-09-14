"""Hot ROI1 channel, REAL preset (Link preserved, same as Doctor_Scenario CH2):
600-1270px, poly4, NO2 Limit +-2px/+-0.02, CHOCHO/H2O Link->NO2 — i.e. the
SAME nonlinear dimensionality as Cold (2), just a different window/references.
This isolates: does the channel/window itself change VarPro-vs-baseline speed,
holding the fit's dimensionality fixed?

Run from this folder: python run_hot_reallink.py
"""
import json, os
import numpy as np
from bench_common import build_engine, make_synthetic_scans, run_varpro, run_baseline, summarize

PIXEL_IDX = np.arange(600, 1270)   # Doctor_Scenario Hot ROI1 window (f_min=600, f_max=1270)
POLY_ORDER = 4
STEP_LIMIT = 0.5
FIXED_E_F = 0.12
N_SCANS = 220
JUMP_AT = 100

REF_PROPS = {
    "NO2":    {"sh_mode": "Limit", "sh_val": "-2.0, 2.0", "sq_mode": "Limit", "sq_val": "-0.02, 0.02",
               "t_ref": 25.0, "t_coeff": 0.0},
    "CHOCHO": {"sh_mode": "Link",  "sh_val": "NO2",       "sq_mode": "Link",  "sq_val": "NO2",
               "t_ref": 25.0, "t_coeff": 0.0},
    "H2O":    {"sh_mode": "Link",  "sh_val": "NO2",       "sq_mode": "Link",  "sq_val": "NO2",
               "t_ref": 25.0, "t_coeff": 0.0},
}
TRUE_C = {"NO2": 0.15, "CHOCHO": 0.03, "H2O": 0.08}
TRUE_POLY = np.array([0.0, 0.002, -0.001, 0.0005, -0.0002])

if __name__ == "__main__":
    eng = build_engine("roi1", {"NO2": ("NO2", 1.0), "CHOCHO": ("CHOCHO", -1.0), "H2O": ("H2O-HITRAN", 1.0)})
    scans, true_shift, true_squeeze = make_synthetic_scans(
        eng, PIXEL_IDX, TRUE_C, TRUE_POLY, 0.01, 0.3, FIXED_E_F, N_SCANS, JUMP_AT, 0.003)

    print(f"HOT ROI1 (Link preserved): {len(PIXEL_IDX)}px window, gases={eng.gas_list}, "
          f"{N_SCANS} scans, jump at {JUMP_AT}")
    results = {}
    for warm in (True, False):
        tag = "warm-start" if warm else "cold-start"
        vout = run_varpro(eng, PIXEL_IDX, scans, REF_PROPS, POLY_ORDER, STEP_LIMIT, FIXED_E_F, warm)
        bout = run_baseline(eng, PIXEL_IDX, scans, POLY_ORDER, STEP_LIMIT, FIXED_E_F, warm,
                             link_map={"NO2": None, "CHOCHO": "NO2", "H2O": "NO2"})
        results[f"varpro_{tag}"] = summarize(f"VarPro - {tag}", vout, true_shift, true_squeeze, TRUE_C, eng.gas_list, JUMP_AT)
        results[f"baseline_{tag}"] = summarize(f"Fully-joint baseline - {tag}", bout, true_shift, true_squeeze, TRUE_C, eng.gas_list, JUMP_AT)

    print("\n=== SUMMARY (HOT ROI1, Link preserved) ===")
    for k, v in results.items():
        print(f"  {k:24s} mean={v['mean_ms']:8.3f} ms/scan  median={v['median_ms']:8.3f} ms/scan  total={v['total_s']:7.3f}s")
    with open(os.path.join(os.path.dirname(__file__), "results_hot_reallink.json"), "w") as f:
        json.dump(results, f, indent=2)
    print("Saved results_hot_reallink.json")
    print("\nCompare mean ms/scan against results_cold.json to check: does the channel/window")
    print("itself change VarPro-vs-baseline speed, or only the (un)linked dimensionality does?")
