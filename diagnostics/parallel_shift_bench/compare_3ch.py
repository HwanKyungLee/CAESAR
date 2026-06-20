"""
3-channel Fast(chunk) vs Step(sequential) comparison on one stable day.
For each channel: Step = _fit_alpha_range(all, body_start=0); Fast = chunked with
warmup. Compares per-scan NO2/CHOCHO/shift. Answers: does chunking change results?
(ProcessPool path already proven == in-process, so this isolates the chunk logic.)
"""
import os, sys, glob
import numpy as np
ROOT = r'C:\Doasis_Work\CAESAR\CAESAR'
sys.path.insert(0, ROOT)
from PyQt6.QtCore import QCoreApplication
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)
from core.engine import UniversalEngine
from gui.worker import AnalysisWorker

DAY = '2026-06-10'
WARMUP = 40
NCHUNKS = 6

CHANS = [
    dict(name='cold', alpha=rf'C:\Doasis_Work\Output\alpha\cold\{DAY}',
         wv=r'C:\Doasis_Work\Output\wv_cal\cold', sh=(-2.0, 2.0), poly=4),
    dict(name='CH1_PNs', alpha=rf'C:\Doasis_Work\Output\alpha\hot\ch1\{DAY}',
         wv=r'C:\Doasis_Work\Output\wv_cal\roi1', sh=(-5.0, 5.0), poly=4),
    dict(name='CH2_ANs', alpha=rf'C:\Doasis_Work\Output\alpha\hot\ch2\{DAY}',
         wv=r'C:\Doasis_Work\Output\wv_cal\roi2', sh=(-5.0, 5.0), poly=3),
]
GASES = ['NO2', 'CHOCHO', 'H2O']


def build(cfg):
    eng = UniversalEngine()
    calib = glob.glob(os.path.join(cfg['wv'], 'Calib_*.txt'))[0]
    arr = np.loadtxt(calib, comments='#'); wave = arr[:, -1] if arr.ndim == 2 else arr
    eng.set_wavelength_axis(wave)
    for g in GASES:
        fs = glob.glob(os.path.join(cfg['wv'], f'Ref_{g}*.dat'))
        eng.add_reference(g, fs[0], wave_nm=wave, multiplier=1.0)
    ng = len(eng.gas_list); pd_ = cfg['poly']
    p0 = [0.0, 1.0] + [0.1] * ng + [0.0] * (pd_ + 1)
    bd = ([-np.inf] * len(p0), [np.inf] * len(p0))
    w = AnalysisWorker(eng, [], 774, 1550, p0, bd, -1, channel=1)
    lo, hi = cfg['sh']
    rp = {GASES[0]: {'sh_mode': 'Limit', 'sh_val': f'{lo}, {hi}',
                     'sq_mode': 'Fix', 'sq_val': '1.0', 't_ref': 25.0, 't_coeff': 0.0}}
    for g in GASES[1:]:
        rp[g] = {'sh_mode': 'Link', 'sh_val': GASES[0], 'sq_mode': 'Link', 'sq_val': GASES[0],
                 't_ref': 25.0, 't_coeff': 0.0}
    w.ref_properties = rp
    w.step_limit = 0.5; w.tikhonov_lambda = 0.0; w.use_robust_fitting = False
    w.allow_negative_gas = True; w.fit_unit = 'px'; w.fit_lo_nm = None; w.fit_hi_nm = None
    w.qc_enabled = False; w.qc_rms_abs = 0.0; w.qc_snr_min = 0.0; w.ok_rms_threshold = 0.10
    w.gas_temp_override = None; w.tz_offset_sec = 0
    return eng, w


def scans_of(adir):
    sc, gi = [], 0
    for fp in sorted(glob.glob(os.path.join(adir, '*_alpha_trace.dat')))[:8]:
        lines = open(fp, encoding='utf-8', errors='replace').readlines()
        nrow = sum(1 for l in lines if l.strip() and not l.startswith('#') and not l.startswith('row_idx'))
        for r in range(nrow):
            sc.append((gi, fp, r)); gi += 1
    return sc


def main():
    for cfg in CHANS:
        scans = scans_of(cfg['alpha'])
        if not scans:
            print(f"{cfg['name']}: no alpha for {DAY}"); continue
        eng, w = build(cfg)
        gl = eng.gas_list
        seq, _, etal = w._fit_alpha_range(scans, body_start=0, init_shift=0.0, etalon_freq=None)
        seqd = {i: r for i, r in seq}
        # chunked
        n = len(scans); bounds = np.linspace(0, n, NCHUNKS + 1, dtype=int)
        chunk = {}
        for ci in range(NCHUNKS):
            bs, be = int(bounds[ci]), int(bounds[ci + 1])
            ws = max(0, bs - WARMUP)
            res, _, _ = w._fit_alpha_range(scans[ws:be], bs - ws, 0.0, etal)
            for i, r in res:
                chunk[i] = r
        # compare
        sh = np.array([abs(seqd[i].get('Shift', 0) - chunk[i].get('Shift', 0)) for i in range(n)])
        print('=' * 64)
        print(f"{cfg['name']}  {DAY}  scans={n}  gases={gl}")
        print(f"  shift  dmax={sh.max():.6f}")
        for g in ('NO2', 'CHOCHO'):
            if g not in gl:
                continue
            a = np.array([seqd[i].get(g, np.nan) for i in range(n)])
            b = np.array([chunk[i].get(g, np.nan) for i in range(n)])
            d = np.abs(a - b)
            print(f"  {g:7} dmax={np.nanmax(d):.3e}  seq[neg%={100*(a<0).mean():.0f} med={np.nanmedian(a):+.3f}]  "
                  f"chunk[neg%={100*(b<0).mean():.0f} med={np.nanmedian(b):+.3f}]  >1e-3={int(np.sum(d>1e-3))}/{n}")


if __name__ == '__main__':
    main()
