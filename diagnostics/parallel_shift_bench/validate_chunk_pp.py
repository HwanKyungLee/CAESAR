"""
Parallel-pool chunk validation (headless, real fit) — 2026-06-17
================================================================
Proves the *actual* ProcessPoolExecutor path (engine pickling, parallel chunk
dispatch, ordered collection) reproduces the in-process sequential fit.

  sequential = AnalysisWorker._fit_alpha_range(all, body_start=0)   [in-process]
  parallel   = ProcessPoolExecutor(_chunk_init, _chunk_entry) over chunks+warmup

Engine = scenario CH1 (cold). Compares per-scan NO2/CHOCHO ppb + shift.
"""
import os, sys, glob, time
import numpy as np
import concurrent.futures as cf

ROOT = r'C:\Doasis_Work\CAESAR\CAESAR'
sys.path.insert(0, ROOT)

from PyQt6.QtCore import QCoreApplication
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

from core.engine import UniversalEngine
from gui.worker import AnalysisWorker, _chunk_init, _chunk_entry

ALPHA_DIR = r'C:\Doasis_Work\Output\alpha\cold'
WV = r'C:\Doasis_Work\Output\wv_cal\cold'
DAY = '2026-05-17'
NFILES = 4
NCHUNKS = 6
WARMUP = 40

REF_PROPS = {
    'NO2':    {'sh_mode': 'Limit', 'sh_val': '-2.0, 2.0',
               'sq_mode': 'Limit', 'sq_val': '-0.02, 0.02', 't_ref': 25.0, 't_coeff': 0.0},
    'CHOCHO': {'sh_mode': 'Link', 'sh_val': 'NO2', 'sq_mode': 'Link', 'sq_val': 'NO2', 't_ref': 25.0, 't_coeff': 0.0},
    'H2O':    {'sh_mode': 'Link', 'sh_val': 'NO2', 'sq_mode': 'Link', 'sq_val': 'NO2', 't_ref': 25.0, 't_coeff': 0.0},
}


def build_engine():
    eng = UniversalEngine()
    calib = glob.glob(os.path.join(WV, 'Calib_*Poly2.txt'))[0]
    arr = np.loadtxt(calib, comments='#')
    wave = arr[:, -1] if arr.ndim == 2 else arr
    eng.set_wavelength_axis(wave)
    for nm, pat, mult in [('NO2', 'Ref_NO2*Dynamic-ILS-Applied.dat', 1.0),
                          ('CHOCHO', 'Ref_CHOCHO*Dynamic-ILS-Applied.dat', 0.1),
                          ('H2O', 'Ref_H2O*Dynamic-ILS-Applied.dat', 1.0)]:
        eng.add_reference(nm, glob.glob(os.path.join(WV, pat))[0], wave_nm=wave, multiplier=mult)
    return eng


def make_cfg(eng):
    ng = len(eng.gas_list)
    poly_deg = 4
    p0 = [0.0, 1.0] + [0.1] * ng + [0.0] * (poly_deg + 1)
    lo = [-np.inf, 0.95] + [0.0] * ng + [-np.inf] * (poly_deg + 1)
    hi = [np.inf, 1.05] + [np.inf] * ng + [np.inf] * (poly_deg + 1)
    return {
        'pixel_min': 775, 'pixel_max': 1550, 'params': p0, 'bounds': (lo, hi), 'channel': 1,
        'ref_properties': REF_PROPS, 'step_limit': 0.5, 'tikhonov_lambda': 0.0,
        'use_robust_fitting': False, 'allow_negative_gas': False,
        'fit_unit': 'px', 'fit_lo_nm': None, 'fit_hi_nm': None,
        'qc_enabled': False, 'qc_rms_abs': 0.0, 'qc_snr_min': 0.0, 'ok_rms_threshold': 0.10,
        'gas_temp_override': None, 'tz_offset_sec': 0,
        'etalon_freq_min': 0.02, 'etalon_freq_max': 0.40,
    }


def build_worker(eng, cfg):
    w = AnalysisWorker(eng, [], cfg['pixel_min'], cfg['pixel_max'], cfg['params'], cfg['bounds'], -1, channel=1)
    for k in ('ref_properties', 'step_limit', 'tikhonov_lambda', 'use_robust_fitting',
              'allow_negative_gas', 'fit_unit', 'fit_lo_nm', 'fit_hi_nm',
              'qc_enabled', 'qc_rms_abs', 'qc_snr_min', 'ok_rms_threshold',
              'gas_temp_override', 'tz_offset_sec', 'etalon_freq_min', 'etalon_freq_max'):
        setattr(w, k, cfg[k])
    return w


def build_scans(files):
    scans, gi = [], 0
    for fp in files:
        lines = open(fp, encoding='utf-8', errors='replace').readlines()
        nrow = sum(1 for l in lines if l.strip() and not l.startswith('#') and not l.startswith('row_idx'))
        for r in range(nrow):
            scans.append((gi, fp, r)); gi += 1
    return scans


def main():
    eng = build_engine()
    cfg = make_cfg(eng)
    files = sorted(glob.glob(os.path.join(ALPHA_DIR, DAY, '*_alpha_trace.dat')))[:NFILES]
    scans = build_scans(files)
    print(f'files={len(files)} scans={len(scans)}  gases={eng.gas_list}')

    # ── sequential reference (in-process) ──
    w = build_worker(eng, cfg)
    t0 = time.time()
    seq_res, _, etal = w._fit_alpha_range(scans, body_start=0, init_shift=0.0, etalon_freq=None)
    t_seq = time.time() - t0
    seq = {gi: r for gi, r in seq_res}
    print(f'sequential: {t_seq:.1f}s  etalon={etal:.4f}')

    # ── parallel (ProcessPoolExecutor) ──
    n = len(scans)
    bounds = np.linspace(0, n, NCHUNKS + 1, dtype=int)
    tasks = []
    for ci in range(NCHUNKS):
        bs, be = int(bounds[ci]), int(bounds[ci + 1])
        ws = max(0, bs - WARMUP)
        tasks.append((scans[ws:be], bs - ws, 0.0, etal))
    par = {}
    t0 = time.time()
    nproc = min((os.cpu_count() or 4), 6)
    with cf.ProcessPoolExecutor(max_workers=nproc, initializer=_chunk_init, initargs=(eng, cfg)) as ex:
        for res in ex.map(_chunk_entry, tasks):
            for gi, r in res:
                par[gi] = r
    t_par = time.time() - t0
    print(f'parallel({nproc}p, {NCHUNKS}chunks, warmup{WARMUP}): {t_par:.1f}s  speedup={t_seq/max(t_par,1e-9):.2f}x')

    # ── compare ──
    print(f'\n=== sequential vs parallel-pool (n={n}) ===')
    sh_d = np.array([abs(seq[i].get('Shift', 0) - par[i].get('Shift', 0)) for i in range(n)])
    print(f'shift  dmax={sh_d.max():.6f}  drms={np.sqrt(np.mean(sh_d**2)):.6f}')
    for g in ('NO2', 'CHOCHO'):
        if g not in eng.gas_list:
            continue
        a = np.array([seq[i].get(g, np.nan) for i in range(n)])
        b = np.array([par[i].get(g, np.nan) for i in range(n)])
        d = np.abs(a - b)
        print(f'{g:7} ppb: dmax={np.nanmax(d):.3e}  drms={np.sqrt(np.nanmean(d**2)):.3e}  '
              f'mean|ppb|={np.nanmean(np.abs(a)):.3f}  >1e-6={int(np.sum(d>1e-6))}/{n}')


if __name__ == '__main__':
    main()
