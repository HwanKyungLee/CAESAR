"""Hot ROI1/ROI2 channel, REAL campaign alpha data -- same idea as
run_cold_real.py (Cold), but for the Hot channels. Closes the last remaining
gap in the VarPro-vs-fully-joint-nonlinear real-data comparison: Cold has now
been checked on both an extreme wall-hugging day (2026-05-17) and a "typical"
day (2026-06-05); Hot ROI1/ROI2 has so far only ever been compared on
SYNTHETIC data (run_hot_reallink.py, run_hot_unlinked_stress.py).

2026-09-06 CORRECTION (important -- read before trusting any earlier
results_hot_*.json from this script): the FIRST version of this script paired
folder `ch1` (files `*_ANs_alpha_trace.dat`) with the label "roi1" and
`ch2` (`*_PNs_alpha_trace.dat`) with "roi2", and ran BOTH through the same
600-1270px/poly4 window -- based only on the coincidence that `ch1` sorts
before `ch2` the same way `roi1` sorts before `roi2`. The user's own
recollection of the real shift magnitudes (ROI1 ~ -5px, ROI2 ~ -2px) didn't
match what that first run produced, which prompted a check against
`scenarios/Doctor_Scenario_Cold_ROI1_ROI2.json` and
`docs/매뉴얼_조작순서.md`. Those turned up the ACTUAL mapping:
  - manual: "CH1=ANs(300C), CH2=PNs(180C)" -- these are the physical/thermal
    channel numbers, i.e. device folder `ch1` IS the ANs (300C) channel and
    `ch2` IS the PNs (180C) channel (that part was right).
  - scenario json's `channels` dict uses a DIFFERENT numbering (its own fit-
    scenario slots, not the physical channel numbers) and its comment says:
    "CH2=Hot ROI1" with data_label "PNs", f_min/f_max 600/1270, poly_deg 4;
    "CH3=Hot ROI2" with data_label "ANs", f_min/f_max 900/1450, poly_deg 3.
So the fit-scenario names are the OPPOSITE of what the first version assumed:
  ROI1 (600-1270px, poly4)  <-> PNs data (device folder `ch2`)
  ROI2 (900-1450px, poly3)  <-> ANs data (device folder `ch1`)
...and ROI2 additionally used poly3, NOT poly4 -- the first run used
600-1270/poly4 for BOTH, which is simply the wrong window+order for
whichever channel is really "ROI2". The first run's results_hot_roi1_real_*
and results_hot_roi2_real_*.json (and the README/memory sections describing
them) are INVALID and were superseded once this correction was made -- see
README.md's "미완 작업" for the retraction note. wv_cal/roi1 vs wv_cal/roi2
are assumed to follow the same "ROI1"/"ROI2" fit-scenario naming as the
scenario json (their Ref_*_Dynamic-ILS-Applied.dat files are the same length
regardless, since they're built over the full instrument pixel grid, not the
fit window -- so file size can't independently confirm this; if further
campaign documentation contradicts this mapping, treat CHANNEL_INFO below as
the single place to fix it).

Run from this folder (or the repo root, per README.md):
    python run_hot_real.py --channel roi1                  # PNs/ch2, 600-1270px poly4, day=2026-06-05
    python run_hot_real.py --channel roi2                  # ANs/ch1, 900-1450px poly3, day=2026-06-05
    python run_hot_real.py --channel roi1 --day 2026-05-18  # earliest available hot day
    python run_hot_real.py --channel roi1 --nfiles 8
Override --alpha-root if your Output folder isn't at the default path.
"""
import argparse, glob, json, os
import numpy as np
from bench_common import build_engine, run_varpro, run_baseline, load_real_alpha_scans, compare_real

STEP_LIMIT = 0.5
FIXED_E_F = 0.12

REF_PROPS = {
    "NO2":    {"sh_mode": "Limit", "sh_val": "-2.0, 2.0", "sq_mode": "Limit", "sq_val": "-0.02, 0.02",
               "t_ref": 25.0, "t_coeff": 0.0},
    "CHOCHO": {"sh_mode": "Link",  "sh_val": "NO2",       "sq_mode": "Link",  "sq_val": "NO2",
               "t_ref": 25.0, "t_coeff": 0.0},
    "H2O":    {"sh_mode": "Link",  "sh_val": "NO2",       "sq_mode": "Link",  "sq_val": "NO2",
               "t_ref": 25.0, "t_coeff": 0.0},
}

# Per scenarios/Doctor_Scenario_Cold_ROI1_ROI2.json (channels "2" and "3") +
# docs/매뉴얼_조작순서.md's "CH1=ANs(300C), CH2=PNs(180C)":
#   subdir       -> passed to build_engine() -> reads wv_cal\<subdir>\Ref_*_Dynamic-ILS-Applied.dat
#   alpha_subpath -> real alpha data folder for this channel (device folder, NOT the same
#                    number as the fit-scenario name -- see correction note above)
#   pixel_idx / poly_order -> from the scenario json's f_min/f_max/poly_deg for that slot
CHANNEL_INFO = {
    "roi1": dict(subdir="roi1", alpha_subpath=r"alpha\10s\hot\ch2",   # PNs, 180C
                 pixel_idx=np.arange(600, 1270), poly_order=4, default_day="2026-06-05"),
    "roi2": dict(subdir="roi2", alpha_subpath=r"alpha\10s\hot\ch1",   # ANs, 300C
                 pixel_idx=np.arange(900, 1450), poly_order=3, default_day="2026-06-05"),
}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument('--channel', choices=["roi1", "roi2"], default="roi1")
    ap.add_argument('--alpha-root', default=r'C:\GHL\2026 yeosu\Output')
    ap.add_argument('--day', default=None, help="default: 2026-06-05 (same 'typical' day used for Cold)")
    ap.add_argument('--nfiles', type=int, default=4)
    args = ap.parse_args()

    info = CHANNEL_INFO[args.channel]
    day = args.day or info["default_day"]
    alpha_dir = os.path.join(args.alpha_root, info["alpha_subpath"])
    pixel_idx = info["pixel_idx"]
    poly_order = info["poly_order"]

    eng = build_engine(info["subdir"], {"NO2": ("NO2", 1.0), "CHOCHO": ("CHOCHO", -1.0), "H2O": ("H2O-HITRAN", 1.0)})

    files = sorted(glob.glob(os.path.join(alpha_dir, day, '*_alpha_trace.dat')))[:args.nfiles]
    if not files:
        raise SystemExit(f"no *_alpha_trace.dat found under {alpha_dir}\\{day} "
                          f"-- check --alpha-root/--day/--channel")
    scans = load_real_alpha_scans(files, pixel_idx)
    print(f"REAL HOT {args.channel.upper()} data (alpha_subpath={info['alpha_subpath']}): "
          f"day={day}  files={len(files)}  scans={len(scans)}  "
          f"{len(pixel_idx)}px window [{pixel_idx[0]}-{pixel_idx[-1]}]  poly_order={poly_order}  "
          f"gases={eng.gas_list}")

    results = {}
    for warm in (True, False):
        tag = "warm-start" if warm else "cold-start"
        print(f"\n--- {tag} ---", flush=True)
        vout = run_varpro(eng, pixel_idx, scans, REF_PROPS, poly_order, STEP_LIMIT, FIXED_E_F, warm)
        print(f"  VarPro done ({len(vout)} scans)", flush=True)
        bout = run_baseline(eng, pixel_idx, scans, poly_order, STEP_LIMIT, FIXED_E_F, warm,
                             link_map={"NO2": None, "CHOCHO": "NO2", "H2O": "NO2"})
        print(f"  baseline done ({len(bout)} scans)", flush=True)
        compare_real(f"VarPro-{tag}", vout, f"baseline-{tag}", bout, eng.gas_list)
        results[f"varpro_{tag}"] = dict(
            mean_ms=1000 * float(np.mean([o["dt"] for o in vout])),
            total_s=float(np.sum([o["dt"] for o in vout])),
            shift=[o["shift"] for o in vout],
            c={g: [o["c"][g] for o in vout] for g in eng.gas_list})
        results[f"baseline_{tag}"] = dict(
            mean_ms=1000 * float(np.mean([o["dt"] for o in bout])),
            total_s=float(np.sum([o["dt"] for o in bout])),
            shift=[o["shift"] for o in bout],
            c={g: [o["c"][g] for o in bout] for g in eng.gas_list})

    print(f"\n=== SUMMARY (REAL HOT {args.channel.upper()}, day={day}) ===")
    for k in ("varpro_warm-start", "baseline_warm-start", "varpro_cold-start", "baseline_cold-start"):
        v = results[k]
        print(f"  {k:24s} mean={v['mean_ms']:8.3f} ms/scan  total={v['total_s']:7.3f}s")

    out_path = os.path.join(os.path.dirname(__file__), f"results_hot_{args.channel}_real_{day}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved {out_path}")
