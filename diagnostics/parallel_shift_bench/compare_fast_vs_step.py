"""
Fast vs Step(=original sequential run() loop) — headless direct comparison.
parallel=False runs the ORIGINAL run() sequential loop (what Step mode uses).
parallel=True runs the Fast (chunk) path. Compares primary ppb + shift per scan.
"""
import os, sys, glob
import numpy as np
ROOT = r'C:\Doasis_Work\CAESAR\CAESAR'
sys.path.insert(0, ROOT)
from PyQt6.QtCore import QCoreApplication
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)
from core.engine import UniversalEngine
from gui.worker import AnalysisWorker

WV = r'C:\Doasis_Work\Output\wv_cal\cold'
ALPHA = r'C:\Doasis_Work\Output\alpha\cold\2026-05-17'
REF_PROPS = {
    'NO2':    {'sh_mode': 'Limit', 'sh_val': '-2.0, 2.0', 'sq_mode': 'Limit', 'sq_val': '-0.02, 0.02', 't_ref': 25.0, 't_coeff': 0.0},
    'CHOCHO': {'sh_mode': 'Link', 'sh_val': 'NO2', 'sq_mode': 'Link', 'sq_val': 'NO2', 't_ref': 25.0, 't_coeff': 0.0},
    'H2O':    {'sh_mode': 'Link', 'sh_val': 'NO2', 'sq_mode': 'Link', 'sq_val': 'NO2', 't_ref': 25.0, 't_coeff': 0.0},
}

def build(files):
    eng = UniversalEngine()
    calib = glob.glob(os.path.join(WV, 'Calib_*Poly2.txt'))[0]
    arr = np.loadtxt(calib, comments='#'); wave = arr[:, -1] if arr.ndim == 2 else arr
    eng.set_wavelength_axis(wave)
    for nm, pat, mult in [('NO2', 'Ref_NO2*ILS-Applied.dat', 1.0), ('CHOCHO', 'Ref_CHOCHO*ILS-Applied.dat', 0.1), ('H2O', 'Ref_H2O*ILS-Applied.dat', 1.0)]:
        eng.add_reference(nm, glob.glob(os.path.join(WV, pat))[0], wave_nm=wave, multiplier=mult)
    ng = len(eng.gas_list); pd = 4
    p0 = [0.0, 1.0] + [0.1] * ng + [0.0] * (pd + 1)
    bd = ([-np.inf] * len(p0), [np.inf] * len(p0))
    w = AnalysisWorker(eng, list(files), 775, 1550, p0, bd, -1, channel=1)
    w.ref_properties = REF_PROPS
    w.step_limit = 0.5; w.tikhonov_lambda = 0.0; w.use_robust_fitting = False
    w.allow_negative_gas = False; w.fit_unit = 'px'; w.fit_lo_nm = None; w.fit_hi_nm = None
    w.qc_enabled = False; w.qc_rms_abs = 0.0; w.qc_snr_min = 0.0; w.ok_rms_threshold = 0.10
    w.gas_temp_override = None; w.tz_offset_sec = 0
    return eng, w

def run_capture(w, parallel):
    got = {}
    w.result_ready.connect(lambda r, i: got.__setitem__(i, dict(r)))
    w.is_running = True
    w.parallel = parallel
    w.run()
    return got

def main():
    files = sorted(glob.glob(os.path.join(ALPHA, '*_alpha_trace.dat')))[:4]
    # Step = original sequential run() loop (parallel=False)
    _, w1 = build(files)
    step = run_capture(w1, parallel=False)
    # Fast = parallel chunk path
    _, w2 = build(files)
    fast = run_capture(w2, parallel=True)

    n = max(max(step) if step else 0, max(fast) if fast else 0) + 1
    common = [i for i in range(n) if i in step and i in fast]
    print(f'step={len(step)}  fast={len(fast)}  common={len(common)}')
    sh = np.array([abs(step[i].get('Shift', 0) - fast[i].get('Shift', 0)) for i in common])
    print(f'shift  dmax={sh.max():.6f}  drms={np.sqrt(np.mean(sh**2)):.6f}')
    for g in ('NO2', 'CHOCHO'):
        a = np.array([step[i].get(g, np.nan) for i in common])
        b = np.array([fast[i].get(g, np.nan) for i in common])
        d = np.abs(a - b)
        print(f'{g:7} ppb: dmax={np.nanmax(d):.3e}  drms={np.sqrt(np.nanmean(d**2)):.3e}  '
              f'mean|ppb|={np.nanmean(np.abs(a)):.3f}  >1e-4={int(np.sum(d>1e-4))}/{len(common)}')

if __name__ == '__main__':
    main()
