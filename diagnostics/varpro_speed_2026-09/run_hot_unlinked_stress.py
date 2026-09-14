"""Hot ROI1, DELIBERATE STRESS CASE (not the real preset): NO2/CHOCHO/H2O/O4
all UNLINKED (each own Limit-mode shift/squeeze) -> VarPro outer dim=8,
fully-joint dim=19. This is the test that showed VarPro slower than the
fully-joint baseline in the cloud-sandbox run; it exists to probe how the
speed gap scales with independent nonlinear dimensionality, NOT to represent
how Hot is actually fit today (the real Doctor_Scenario preset keeps
CHOCHO/H2O Linked -> see run_hot_reallink.py for the realistic comparison).

Physically shift/squeeze is one shared spectrometer property, so the ground
truth here still uses ONE shared trajectory — only the FIT is given the
(here, deliberately excessive) freedom to solve each gas independently.

Run from this folder: python run_hot_unlinked_stress.py
"""
import json, os
import numpy as np
from bench_common import build_engine, make_synthetic_scans, run_varpro, run_baseline, summarize

PIXEL_IDX = np.arange(600, 1270)
POLY_ORDER = 4
STEP_LIMIT = 0.5
FIXED_E_F = 0.12
N_SCANS = 220
JUMP_AT = 100

if __name__ == "__main__":
    eng = build_engine("roi1", {"NO2": ("NO2", 1.0), "CHOCHO": ("CHOCHO", -1.0),
                                  "H2O": ("H2O-HITRAN", 1.0), "O4": ("O4", 1.0)})
    REF_PROPS = {g: {"sh_mode": "Limit", "sh_val": "-2.0, 2.0", "sq_mode": "Limit", "sq_val": "-0.02, 0.02",
                     "t_ref": 25.0, "t_coeff": 0.0} for g in eng.gas_list}
    TRUE_C = {"NO2": 0.15, "CHOCHO": 0.03, "H2O": 0.08, "O4": 0.05}
    TRUE_POLY = np.array([0.0, 0.002, -0.001, 0.0005, -0.0002])

    scans, true_shift, true_squeeze = make_synthetic_scans(
        eng, PIXEL_IDX, TRUE_C, TRUE_POLY, 0.01, 0.3, FIXED_E_F, N_SCANS, JUMP_AT, 0.003)

    print(f"HOT ROI1 (UNLINKED stress case): {len(PIXEL_IDX)}px window, gases={eng.gas_list} (all independent), "
          f"VarPro outer dim={2*len(eng.gas_list)}, {N_SCANS} scans, jump at {JUMP_AT}")
    results = {}
    for warm in (True, False):
        tag = "warm-start" if warm else "cold-start"
        vout = run_varpro(eng, PIXEL_IDX, scans, REF_PROPS, POLY_ORDER, STEP_LIMIT, FIXED_E_F, warm)
        bout = run_baseline(eng, PIXEL_IDX, scans, POLY_ORDER, STEP_LIMIT, FIXED_E_F, warm,
                             link_map=None)  # every gas independent
        results[f"varpro_{tag}"] = summarize(f"VarPro - {tag}", vout, true_shift, true_squeeze, TRUE_C, eng.gas_list, JUMP_AT)
        results[f"baseline_{tag}"] = summarize(f"Fully-joint baseline - {tag}", bout, true_shift, true_squeeze, TRUE_C, eng.gas_list, JUMP_AT)

    print("\n=== SUMMARY (HOT ROI1, unlinked stress case) ===")
    for k, v in results.items():
        print(f"  {k:24s} mean={v['mean_ms']:8.3f} ms/scan  median={v['median_ms']:8.3f} ms/scan  total={v['total_s']:7.3f}s")
    with open(os.path.join(os.path.dirname(__file__), "results_hot_unlinked_stress.json"), "w") as f:
        json.dump(results, f, indent=2)
    print("Saved results_hot_unlinked_stress.json")
