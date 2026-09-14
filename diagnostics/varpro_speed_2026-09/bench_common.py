"""Shared code for the VarPro-vs-fully-joint-nonlinear speed/accuracy test.

Run these scripts FROM THE REPO (see README.md in this folder) — they import
the real, live `core.doas_fit.DoasFitter` and `core.engine.UniversalEngine`
via the normal package path (no staged/stubbed copies), so results reflect
whatever is currently checked out, on your own hardware.

This module only builds synthetic test data and the two fit runners; it does
NOT modify anything in core/. The "baseline" solver (run_baseline) is not
part of AUGUR — it represents the class of algorithm VarPro's design note
(docs/Augur_소개_2026-07.md §5.2) says was rejected (putting concentrations,
background, etalon, shift and squeeze all into one non-linear vector instead
of projecting the linear part out), implemented here with the exact same
model equation and bounds for an apples-to-apples, one-variable-changed
comparison.
"""
from __future__ import annotations
import os, sys, time
import numpy as np
from scipy.interpolate import interp1d
from scipy.optimize import least_squares
from numpy.polynomial import chebyshev

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))   # diagnostics/<name>/ -> repo root
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.engine import UniversalEngine          # real, unmodified
from core.doas_fit import DoasFitter             # real, unmodified
from core.paths import WV_CAL_DIR                # real, unmodified


def build_engine(subdir: str, species: dict):
    """species: {name: (ref_filename_stub, multiplier)}. Bypasses add_reference()/
    DataIO on purpose (these files are already on the instrument's pixel grid,
    no wavelength resampling needed) — same technique validated in the cloud
    sandbox run. Populates only the documented UniversalEngine attributes
    (raw_references, interpolators, gas_list, scaling_factors)."""
    eng = UniversalEngine()
    ref_dir = os.path.join(WV_CAL_DIR, subdir)
    for name, (stub, mult) in species.items():
        arr = np.loadtxt(os.path.join(ref_dir, f"Ref_{stub}_Dynamic-ILS-Applied.dat")) * mult
        eng.raw_references[name] = arr
        pidx_full = np.arange(len(arr))
        eng._set_interpolator(name, arr)   # interpolators + ref_derivatives 동시 생성(해석적 자코비안용)
        eng.gas_list.append(name)
        mx = np.max(np.abs(arr))
        eng.scaling_factors[name] = mx if mx else 1.0
    return eng


def make_synthetic_scans(eng, pixel_idx, true_c, true_poly, true_et_amp, true_et_phase,
                          fixed_e_f, n_scans, jump_at, noise_sigma, seed=20260905):
    """Slow random-walk shift/squeeze drift + one instantaneous 'mirror cleaning'
    jump at `jump_at`. Returns (scans[n_scans, len(pixel_idx)], true_shift, true_squeeze)."""
    rng = np.random.default_rng(seed)
    abs_center = pixel_idx[len(pixel_idx)//2]
    true_shift = np.zeros(n_scans)
    true_squeeze = np.ones(n_scans)
    for t in range(1, n_scans):
        true_shift[t] = np.clip(true_shift[t-1] + rng.normal(0, 0.01), -1.8, 1.8)
        true_squeeze[t] = np.clip(true_squeeze[t-1] + rng.normal(0, 0.0003), 0.985, 1.015)
    true_shift[jump_at:] += 1.3
    true_squeeze[jump_at:] += 0.008

    x_min, x_max = pixel_idx[0], pixel_idx[-1]
    x_mapped = (2.0 * (pixel_idx - x_min) / (x_max - x_min)) - 1.0

    def model(shift, squeeze):
        gas_sum = 0.0
        for name in eng.gas_list:
            px_sh = (pixel_idx - abs_center) * squeeze + abs_center + shift
            gas_sum = gas_sum + true_c[name] * eng.interpolators[name](px_sh) / eng.scaling_factors[name]
        baseline = chebyshev.chebval(x_mapped, true_poly)
        etalon = true_et_amp * np.sin(fixed_e_f * pixel_idx + true_et_phase)
        return gas_sum + baseline + etalon

    scans = np.stack([model(true_shift[t], true_squeeze[t]) +
                       rng.normal(0, noise_sigma, size=len(pixel_idx)) for t in range(n_scans)])
    return scans, true_shift, true_squeeze


def load_real_alpha_scans(files, pixel_idx):
    """Parses real AUGUR '*_alpha_trace.dat' files (same format bench.py /
    validate_chunk.py already use — one row per scan, tab-separated, a
    'row_idx ... px0000 px0001 ...' header naming the pixel columns) into a
    [n_scans, len(pixel_idx)] array of real optical-depth spectra, sliced down
    to `pixel_idx`. No wavelength axis needed here: `pixel_idx` are raw
    instrument pixel indices (e.g. np.arange(775, 1550) for Cold), and the
    file's pixel columns already sit on that same 0..N-1 grid — the same grid
    build_engine() uses when it loads Ref_*_Dynamic-ILS-Applied.dat as a plain
    array indexed by np.arange(len(arr))."""
    rows = []
    for fp in files:
        lines = open(fp, encoding='utf-8', errors='replace').readlines()
        hdr = [l for l in lines if l.startswith('row_idx')][0].rstrip('\n').split('\t')
        ipx = next(i for i, c in enumerate(hdr) if c.startswith('px'))
        n_full = len(hdr) - ipx
        for l in lines:
            if not l.strip() or l.startswith('#') or l.startswith('row_idx'):
                continue
            p = l.rstrip('\n').split('\t')
            if len(p) < ipx + n_full:
                continue
            full_row = np.array(p[ipx:ipx + n_full], dtype=float)
            rows.append(full_row[pixel_idx])
    if not rows:
        raise ValueError(f"no data rows parsed from {len(files)} file(s)")
    return np.stack(rows)


def compare_real(name_a, out_a, name_b, out_b, gases):
    """No ground truth exists for real campaign data, unlike make_synthetic_scans'
    known true_shift/true_c — so instead of RMSE-vs-truth (summarize()'s job),
    this compares method A directly against method B on the SAME real spectra,
    the same way bench.py/validate_chunk.py compare shift-policies against each
    other. Also prints each method's own timing."""
    n = len(out_a)
    assert n == len(out_b)
    sh_a = np.array([o["shift"] for o in out_a]); sh_b = np.array([o["shift"] for o in out_b])
    sh_d = sh_a - sh_b
    sh_corr = np.corrcoef(sh_a, sh_b)[0, 1] if np.std(sh_a) > 0 and np.std(sh_b) > 0 else float('nan')
    print(f"\n=== {name_a} vs {name_b} (REAL data, n={n} scans, no ground truth — direct A-vs-B) ===")
    print(f"  shift: rms_diff={np.sqrt(np.mean(sh_d**2)):.4f}px max_diff={np.max(np.abs(sh_d)):.4f}px "
          f"corr={sh_corr:.6f}  ({name_a} range=[{sh_a.min():+.3f},{sh_a.max():+.3f}] "
          f"{name_b} range=[{sh_b.min():+.3f},{sh_b.max():+.3f}])")
    for g in gases:
        a = np.array([o["c"][g] for o in out_a]); b = np.array([o["c"][g] for o in out_b])
        d = a - b
        corr = np.corrcoef(a, b)[0, 1] if np.std(a) > 0 and np.std(b) > 0 else float('nan')
        rel = np.abs(d) / (np.abs(a) + 1e-12)
        print(f"  {g:6s} coeff: rms_diff={np.sqrt(np.mean(d**2)):.3e} max_diff={np.max(np.abs(d)):.3e} "
              f"corr={corr:.6f} max_rel={np.nanmax(rel):.2e}  (mean|{name_a}|={np.mean(np.abs(a)):.4f})")
    for name, out in ((name_a, out_a), (name_b, out_b)):
        dts = np.array([o["dt"] for o in out])
        print(f"  {name}: total={dts.sum():.3f}s  mean={1000*dts.mean():.3f} ms/scan  "
              f"median={1000*np.median(dts):.3f} ms/scan  max={1000*dts.max():.3f} ms/scan"
              + (f"  success_rate={np.mean([o['success'] for o in out]):.1%}" if "success" in out[0] else ""))


def _underflow_scale(y):
    """Reproduces gui/worker.py _fit_alpha_range's underflow guard EXACTLY
    (avg_raw = np.mean(y); scale_factor = 10**(-floor(log10(|avg_raw|))) only
    when |avg_raw| < 1e-4, else 1.0). Synthetic scans in this file are all
    amplitude ~1e-3 to ~0.3 (well above 1e-4), so scale_factor was always 1.0
    there and this was invisible. Real alpha data (run_cold_real.py) turned
    out to be far smaller in magnitude than that — 2026-09-06: without this,
    run_varpro's shift came back EXACTLY 0.000 for every single one of 1402
    real scans (verified: reproduced the identical freeze with synthetic data
    scaled down to the same ~1e-6 magnitude, confirmed it's the missing
    scale_factor and not a VarPro-specific defect — scipy's default relative
    finite-difference step size effectively sees zero gradient when both the
    data and the residual are this many orders of magnitude below 1)."""
    avg_raw = np.mean(y)
    if avg_raw != 0 and abs(avg_raw) < 1e-4:
        return 10.0 ** (-np.floor(np.log10(abs(avg_raw))))
    return 1.0


def run_varpro(eng, pixel_idx, scans, ref_props, poly_order, step_limit, fixed_e_f, warm,
               fitter_cls=None, W0=None):
    """Calls the real DoasFitter.execute_varpro_fit unmodified, per scan.

    `fitter_cls`/`W0` exist only for validate_dense_w_removal.py, which runs the
    pre-fix (dense n x n W) and post-fix (weight vector) DoasFitter through this
    exact same harness. Defaults reproduce the historical behaviour byte for byte.
    """
    fitter = (fitter_cls or DoasFitter)(eng)
    W0 = np.eye(len(pixel_idx)) if W0 is None else W0
    abs_center = pixel_idx[len(pixel_idx)//2]
    last = {g: {"sh": 0.0, "sq": 1.0} for g in eng.gas_list}
    out = []
    for t in range(len(scans)):
        scale_factor = _underflow_scale(scans[t])
        y = scans[t] * scale_factor
        anchor = last[eng.gas_list[0]]["sh"] if warm else 0.0
        init_vals = {}
        if warm:
            for g in eng.gas_list:
                init_vals[f"{g}_sh"] = last[g]["sh"]
                init_vals[f"{g}_sq"] = last[g]["sq"]
        active_vars, fixed_vars, linked_vars, theta0, lb, ub = fitter.setup_fit_parameters(
            ref_props, anchor, current_params=[last[eng.gas_list[0]]["sh"]],
            step_limit=step_limit, initial_values=init_vals)
        t0 = time.perf_counter()
        opt_shifts, opt_sqs, c_gas, poly_c, et_amp, et_ph, c_perr = fitter.execute_varpro_fit(
            pixel_idx, y, W0, active_vars, fixed_vars, linked_vars,
            theta0, lb, ub, poly_order, fixed_e_f, abs_center, 1.0,
            ref_props, 25.0, tikhonov_lambda=0.0, use_robust=False, allow_negative_gas=True)
        dt = time.perf_counter() - t0
        c_gas_orig = np.asarray(c_gas) / scale_factor
        for i, g in enumerate(eng.gas_list):
            last[g]["sh"], last[g]["sq"] = opt_shifts[i], opt_sqs[i]
        out.append(dict(t=t, dt=dt, shift=opt_shifts[0], squeeze=opt_sqs[0],
                         c=dict(zip(eng.gas_list, c_gas_orig.tolist()))))
    return out


def run_baseline(eng, pixel_idx, scans, poly_order, step_limit, fixed_e_f, warm, link_map=None):
    """Fully-joint nonlinear baseline: NOT part of AUGUR. `link_map` mirrors
    REF_PROPS' Link semantics: {gas: None} means that gas gets its own
    shift+squeeze unknown; {gas: "OtherGas"} means it reuses OtherGas's value
    (no separate unknown). Default: every gas independent. All unknowns
    (concentrations, background, etalon, and every independent shift/squeeze)
    go into ONE least_squares call — the alternative VarPro's projection
    avoids."""
    gases = list(eng.gas_list)
    n_gas = len(gases)
    link_map = link_map if link_map is not None else {g: None for g in gases}
    independent = [g for g in gases if link_map.get(g) is None]
    n_free_shift = len(independent)
    abs_center = pixel_idx[len(pixel_idx)//2]
    x_min, x_max = pixel_idx[0], pixel_idx[-1]
    x_mapped = (2.0 * (pixel_idx - x_min) / (x_max - x_min)) - 1.0
    ndim = n_gas + (poly_order + 1) + 2 + 2 * n_free_shift

    def residual(p, y):
        c = p[0:n_gas]
        poly = p[n_gas:n_gas+poly_order+1]
        a, b = p[n_gas+poly_order+1], p[n_gas+poly_order+2]
        off = n_gas + poly_order + 3
        shifts = {g: p[off+i] for i, g in enumerate(independent)}
        sqs = {g: p[off+n_free_shift+i] for i, g in enumerate(independent)}
        for g in gases:
            target = link_map.get(g)
            if target is not None:
                shifts[g] = shifts[target]
                sqs[g] = sqs[target]
        model = chebyshev.chebval(x_mapped, poly) + a*np.sin(fixed_e_f*pixel_idx) + b*np.cos(fixed_e_f*pixel_idx)
        for i, name in enumerate(gases):
            sh, sq = shifts[name], sqs[name]
            px_sh = (pixel_idx - abs_center) * sq + abs_center + sh
            model = model + c[i] * eng.interpolators[name](px_sh) / eng.scaling_factors[name]
        return model - y

    off = n_gas + poly_order + 3
    last_p = None
    last_sh = {g: 0.0 for g in independent}
    last_sq = {g: 1.0 for g in independent}
    out = []
    for t in range(len(scans)):
        lb = np.full(ndim, -np.inf); ub = np.full(ndim, np.inf)
        p0 = np.zeros(ndim); p0[off+n_free_shift:off+2*n_free_shift] = 1.0
        for i, g in enumerate(independent):
            anchor = last_sh[g] if warm else 0.0
            sh_lb, sh_ub = max(-2.0, anchor-step_limit), min(2.0, anchor+step_limit)
            if sh_lb >= sh_ub: sh_lb, sh_ub = anchor-1e-3, anchor+1e-3
            lb[off+i], ub[off+i] = sh_lb, sh_ub
            lb[off+n_free_shift+i], ub[off+n_free_shift+i] = 0.98, 1.02
            p0[off+i] = min(max(anchor, sh_lb+1e-6), sh_ub-1e-6)
            if warm: p0[off+n_free_shift+i] = min(max(last_sq[g], 0.98+1e-6), 1.02-1e-6)
        if warm and last_p is not None:
            p0[0:off] = last_p[0:off]
        scale_factor = _underflow_scale(scans[t])
        y = scans[t] * scale_factor
        t0 = time.perf_counter()
        res = least_squares(residual, x0=p0, bounds=(lb, ub), args=(y,), max_nfev=8000)
        dt = time.perf_counter() - t0
        last_p = res.x.copy()
        for i, g in enumerate(independent):
            last_sh[g], last_sq[g] = res.x[off+i], res.x[off+n_free_shift+i]
        out.append(dict(t=t, dt=dt, shift=res.x[off] if independent else 0.0,
                         squeeze=res.x[off+n_free_shift] if independent else 1.0,
                         c=dict(zip(gases, (res.x[0:n_gas] / scale_factor).tolist())),
                         nfev=res.nfev, success=bool(res.success)))
    return out


def _pool_init(eng, ref_props, poly_order, step_limit, fixed_e_f):
    """ProcessPoolExecutor initializer — one AnalysisWorker-equivalent context per
    worker process, mirroring gui/worker.py's _chunk_init (same BLAS-cap-per-worker
    reasoning: without this, each of the N processes spawns its own BLAS threads
    and N x threads >> cores -> oversubscription)."""
    global _G_ENG, _G_FITTER, _G_REF_PROPS, _G_POLY, _G_STEP, _G_EF
    _G_ENG, _G_REF_PROPS, _G_POLY, _G_STEP, _G_EF = eng, ref_props, poly_order, step_limit, fixed_e_f
    _G_FITTER = DoasFitter(eng)
    try:
        from threadpoolctl import threadpool_limits
        threadpool_limits(1)
    except ImportError:
        pass


def _pool_fit_chunk(task):
    """Runs in a worker process: replays `warmup_scans` (discarded) to re-settle
    last_valid_shift, then fits `body_scans` and returns (global_index, result)
    pairs for the body only — mirrors gui/worker.py's _chunk_entry/_run_parallel
    chunk+warmup design (real per-scan math: core/doas_fit.py, unmodified)."""
    warmup_scans, body_scans, pixel_idx, body_start = task
    eng, fitter = _G_ENG, _G_FITTER
    W0 = np.eye(len(pixel_idx))
    abs_center = pixel_idx[len(pixel_idx)//2]
    last = {g: {"sh": 0.0, "sq": 1.0} for g in eng.gas_list}
    all_scans = list(warmup_scans) + list(body_scans)
    n_warm = len(warmup_scans)
    results = []
    for i, spec in enumerate(all_scans):
        anchor = last[eng.gas_list[0]]["sh"]
        init_vals = {f"{g}_sh": last[g]["sh"] for g in eng.gas_list}
        init_vals.update({f"{g}_sq": last[g]["sq"] for g in eng.gas_list})
        active_vars, fixed_vars, linked_vars, theta0, lb, ub = fitter.setup_fit_parameters(
            _G_REF_PROPS, anchor, current_params=[last[eng.gas_list[0]]["sh"]],
            step_limit=_G_STEP, initial_values=init_vals)
        opt_shifts, opt_sqs, c_gas, poly_c, et_amp, et_ph, c_perr = fitter.execute_varpro_fit(
            pixel_idx, spec, W0, active_vars, fixed_vars, linked_vars,
            theta0, lb, ub, _G_POLY, _G_EF, abs_center, 1.0,
            _G_REF_PROPS, 25.0, tikhonov_lambda=0.0, use_robust=False, allow_negative_gas=True)
        for j, g in enumerate(eng.gas_list):
            last[g]["sh"], last[g]["sq"] = opt_shifts[j], opt_sqs[j]
        if i >= n_warm:
            results.append((body_start + (i - n_warm),
                             dict(shift=float(opt_shifts[0]), squeeze=float(opt_sqs[0]),
                                  c={g: float(v) for g, v in zip(eng.gas_list, c_gas.tolist())})))
    return results


def run_chunked_parallel(eng, pixel_idx, scans, ref_props, poly_order, step_limit, fixed_e_f,
                          nproc=None, warmup=40):
    """Reproduces gui/worker.py AnalysisWorker._run_parallel's chunk+warmup dispatch
    (same nproc formula, same warmup=40, same chunk_size formula) using a plain
    ProcessPoolExecutor. NOT copied from worker.py verbatim (that class is tightly
    coupled to Qt signals/GUI state) — this is a reproduction of the documented
    design, calling AUGUR's real, unmodified per-scan fit function."""
    import concurrent.futures as cf
    n = len(scans)
    cpu = os.cpu_count() or 4
    nproc = nproc if nproc is not None else max(2, min(8, cpu // 2))
    nproc = max(1, min(nproc, cpu))
    chunk_size = max(150, min(400, -(-n // (nproc * 6))))
    tasks = []
    bs = 0
    while bs < n:
        be = min(bs + chunk_size, n)
        ws = max(0, bs - warmup)
        tasks.append((scans[ws:bs], scans[bs:be], pixel_idx, bs))
        bs = be
    t0 = time.perf_counter()
    all_results = {}
    with cf.ProcessPoolExecutor(max_workers=nproc, initializer=_pool_init,
                                 initargs=(eng, ref_props, poly_order, step_limit, fixed_e_f)) as ex:
        for chunk_res in ex.map(_pool_fit_chunk, tasks):
            for idx, r in chunk_res:
                all_results[idx] = r
    dt = time.perf_counter() - t0
    ordered = [all_results[i] for i in range(n)]
    return ordered, dt, nproc, chunk_size, len(tasks)


def summarize(name, out, true_shift, true_squeeze, true_c, gases, jump_at):
    dts = np.array([o["dt"] for o in out])
    sh_err = np.array([o["shift"] - true_shift[o["t"]] for o in out])
    c_err = {g: np.array([o["c"][g] - true_c[g] for o in out]) for g in gases}
    steady, postjump, recovered = slice(10, 90), slice(jump_at, jump_at+10), slice(jump_at+15, jump_at+40)
    rmse = lambda a: float(np.sqrt(np.mean(a**2)))
    print(f"\n=== {name} ===")
    print(f"  total wall time: {dts.sum():.4f}s / {len(out)} scans "
          f"({1000*dts.mean():.3f} ms/scan mean, {1000*np.median(dts):.3f} ms/scan median, "
          f"{1000*dts.max():.3f} ms/scan max)")
    print(f"  shift RMSE steady={rmse(sh_err[steady]):.4f}px postjump={rmse(sh_err[postjump]):.4f}px "
          f"recovered={rmse(sh_err[recovered]):.4f}px")
    for g in gases:
        print(f"  {g:6s} conc RMSE steady={rmse(c_err[g][steady]):.5f} postjump={rmse(c_err[g][postjump]):.5f} "
              f"recovered={rmse(c_err[g][recovered]):.5f}")
    if "nfev" in out[0]:
        nfevs = np.array([o["nfev"] for o in out]); succ = np.mean([o["success"] for o in out])
        print(f"  nfev mean={nfevs.mean():.0f} max={nfevs.max()} success_rate={succ:.1%}")
    return dict(name=name, mean_ms=1000*dts.mean(), median_ms=1000*float(np.median(dts)), total_s=float(dts.sum()))
