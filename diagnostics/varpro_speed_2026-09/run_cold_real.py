"""Cold channel, REAL campaign alpha data (default day: 2026-05-17 — the same
day validate_chunk.py already found to be the most unstable one seen so far,
shift bouncing between both +-2px hard walls, per the user's own confirmation
that Cold does this generally but 5/17 was an especially bad case).

Every other script in this folder (run_cold.py, run_hot_reallink.py,
run_hot_unlinked_stress.py) only compares VarPro (real core/doas_fit.py)
against the fully-joint-nonlinear baseline on SYNTHETIC data — a smooth,
slow random-walk shift/squeeze drift. That comparison has never been run on
real, messy data where the fit is visibly struggling (wall-to-wall shift
bouncing). This script closes that gap: same two methods, same model
equation, same bounds, run head-to-head on the SAME real spectra. There is no
ground truth for real data, so unlike run_cold.py this compares the two
methods directly against each other (see bench_common.compare_real) rather
than against a known true_shift/true_c — the same way bench.py and
validate_chunk.py already compare shift-policies against each other.

Needs the campaign folder connected. Default paths assume:
    C:\\GHL\\2026 yeosu\\Output\\alpha\\10s\\cold\\<day>\\*_cold_alpha_trace.dat
    C:\\GHL\\2026 yeosu\\Output\\wv_cal\\cold\\Ref_*_Dynamic-ILS-Applied.dat  (via core.paths.WV_CAL_DIR — see build_engine)
Override with --alpha-dir/--day/--nfiles if your layout differs.

Run from this folder (or the repo root, per README.md):
    python run_cold_real.py                          # day=2026-05-17, 4 files (~1400 scans)
    python run_cold_real.py --day 2026-06-05          # a calmer comparison day
    python run_cold_real.py --nfiles 8                # more scans, same day

2026-09-06 note: the first real run of this script showed VarPro's shift
frozen at exactly 0.000 for every single scan (both warm- and cold-start) --
that was a bug in bench_common.py (a missing underflow-guard scale_factor
that gui/worker.py's real _fit_alpha_range applies but this diagnostic
harness didn't), not a real VarPro defect -- see README.md's "미완 작업" for
the full story and the fix. Confirmed fixed and regression-checked against
run_cold.py's normal-amplitude synthetic case before this note was added.
"""
import argparse, glob, json, os
import numpy as np
from bench_common import build_engine, run_varpro, run_baseline, load_real_alpha_scans, compare_real

PIXEL_IDX = np.arange(775, 1550)   # same Cold window as run_cold.py
POLY_ORDER = 4
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

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument('--alpha-dir', default=r'C:\GHL\2026 yeosu\Output\alpha\10s\cold')
    ap.add_argument('--day', default='2026-05-17')
    ap.add_argument('--nfiles', type=int, default=4)
    args = ap.parse_args()

    eng = build_engine("cold", {"NO2": ("NO2", 1.0), "CHOCHO": ("CHOCHO", -1.0), "H2O": ("H2O-HITRAN", 1.0)})

    files = sorted(glob.glob(os.path.join(args.alpha_dir, args.day, '*_alpha_trace.dat')))[:args.nfiles]
    if not files:
        raise SystemExit(f"no *_alpha_trace.dat found under {args.alpha_dir}\\{args.day} "
                          f"-- check --alpha-dir/--day")
    scans = load_real_alpha_scans(files, PIXEL_IDX)
    print(f"REAL COLD data: day={args.day}  files={len(files)}  scans={len(scans)}  "
          f"{len(PIXEL_IDX)}px window  gases={eng.gas_list}")

    results = {}
    for warm in (True, False):
        tag = "warm-start" if warm else "cold-start"
        print(f"\n--- {tag} ---", flush=True)
        vout = run_varpro(eng, PIXEL_IDX, scans, REF_PROPS, POLY_ORDER, STEP_LIMIT, FIXED_E_F, warm)
        print(f"  VarPro done ({len(vout)} scans)", flush=True)
        bout = run_baseline(eng, PIXEL_IDX, scans, POLY_ORDER, STEP_LIMIT, FIXED_E_F, warm,
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

    print(f"\n=== SUMMARY (REAL COLD, day={args.day}) ===")
    for k in ("varpro_warm-start", "baseline_warm-start", "varpro_cold-start", "baseline_cold-start"):
        v = results[k]
        print(f"  {k:24s} mean={v['mean_ms']:8.3f} ms/scan  total={v['total_s']:7.3f}s")

    out_path = os.path.join(os.path.dirname(__file__), f"results_cold_real_{args.day}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved {out_path}")
