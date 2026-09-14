"""Chunk+warmup parallel fitting vs sequential, using AUGUR's real per-scan
VarPro fit (core/doas_fit.py, unmodified) and a dispatcher that reproduces
gui/worker.py's AnalysisWorker._run_parallel design (same nproc formula
max(2, min(8, cpu_count//2)), same warmup=40, same chunk_size formula) —
NOT copied from worker.py verbatim (that class is tightly coupled to Qt), but
same math, same per-scan fit function, real numbers from THIS machine's cores.

This directly answers the earlier "does the documented ~1e-6 ppb sequential
vs parallel match hold, and what's the actual speedup on real hardware"
question that the cloud sandbox (2 cores) could not test.

Run from this folder: python run_parallel_chunk.py [--nproc N] [--scans N]
"""
import argparse, json, os, time
import numpy as np
from bench_common import build_engine, make_synthetic_scans, run_varpro, run_chunked_parallel

PIXEL_IDX = np.arange(775, 1550)   # Cold window
POLY_ORDER = 4
STEP_LIMIT = 0.5
FIXED_E_F = 0.12
JUMP_AT = 400

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--nproc", type=int, default=None, help="default: production formula max(2,min(8,cpu//2))")
    ap.add_argument("--scans", type=int, default=1500)
    args = ap.parse_args()

    eng = build_engine("cold", {"NO2": ("NO2", 1.0), "CHOCHO": ("CHOCHO", -1.0), "H2O": ("H2O-HITRAN", 1.0)})
    scans, true_shift, true_squeeze = make_synthetic_scans(
        eng, PIXEL_IDX, TRUE_C, TRUE_POLY, 0.01, 0.3, FIXED_E_F, args.scans, JUMP_AT, 0.003)

    cpu = os.cpu_count() or 4
    print(f"this machine: os.cpu_count()={cpu}")
    print(f"COLD window={len(PIXEL_IDX)}px, {args.scans} synthetic scans, jump at {JUMP_AT}")

    print("\n=== Sequential (warm-start), real core/doas_fit.py ===")
    t0 = time.perf_counter()
    seq_out = run_varpro(eng, PIXEL_IDX, scans, REF_PROPS, POLY_ORDER, STEP_LIMIT, FIXED_E_F, warm=True)
    seq_dt = time.perf_counter() - t0
    print(f"  total: {seq_dt:.3f}s  ({1000*seq_dt/args.scans:.3f} ms/scan)")

    print("\n=== Chunk+warmup parallel (reproduces gui/worker.py AnalysisWorker._run_parallel design) ===")
    par_out, par_dt, nproc, chunk_size, n_chunks = run_chunked_parallel(
        eng, PIXEL_IDX, scans, REF_PROPS, POLY_ORDER, STEP_LIMIT, FIXED_E_F, nproc=args.nproc)
    print(f"  nproc={nproc}  chunk_size={chunk_size}  n_chunks={n_chunks}")
    print(f"  total: {par_dt:.3f}s  ({1000*par_dt/args.scans:.3f} ms/scan)  speedup={seq_dt/par_dt:.2f}x")

    # Agreement check — mirrors the real validation gate ("~1e-6 ppb" claim in
    # docs/Augur_소개_2026-07.md §5.7): does chunk+warmup reproduce sequential?
    shift_diff = np.array([abs(par_out[i]["shift"] - seq_out[i]["shift"]) for i in range(args.scans)])
    c_diff = {g: np.array([abs(par_out[i]["c"][g] - seq_out[i]["c"][g]) for i in range(args.scans)])
              for g in eng.gas_list}
    print(f"\n=== Sequential vs chunk+warmup agreement (per-scan abs diff) ===")
    print(f"  shift: max={shift_diff.max():.3e}px  mean={shift_diff.mean():.3e}px  "
          f"(large only expected right at each chunk boundary if warmup=40 is too short)")
    for g in eng.gas_list:
        print(f"  {g:6s} conc: max={c_diff[g].max():.3e}  mean={c_diff[g].mean():.3e}")

    with open(os.path.join(os.path.dirname(__file__), "results_parallel.json"), "w") as f:
        json.dump(dict(cpu_count=cpu, n_scans=args.scans, nproc=nproc, chunk_size=chunk_size,
                        n_chunks=n_chunks, seq_total_s=seq_dt, par_total_s=par_dt,
                        speedup=seq_dt/par_dt, shift_diff_max=float(shift_diff.max()),
                        shift_diff_mean=float(shift_diff.mean())), f, indent=2)
    print("\nSaved results_parallel.json")
