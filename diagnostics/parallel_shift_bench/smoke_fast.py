"""
Smoke test for AnalysisWorker Fast path (_run_parallel), headless.
Calls run() synchronously (parallel=True) and checks all results arrive in order
and match a sequential reference (_fit_alpha_range, body_start=0).
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

def build():
    eng = UniversalEngine()
    calib = glob.glob(os.path.join(WV, 'Calib_*Poly2.txt'))[0]
    arr = np.loadtxt(calib, comments='#'); wave = arr[:, -1] if arr.ndim == 2 else arr
    eng.set_wavelength_axis(wave)
    for nm, pat, mult in [('NO2', 'Ref_NO2*ILS-Applied.dat', 1.0), ('CHOCHO', 'Ref_CHOCHO*ILS-Applied.dat', 0.1), ('H2O', 'Ref_H2O*ILS-Applied.dat', 1.0)]:
        eng.add_reference(nm, glob.glob(os.path.join(WV, pat))[0], wave_nm=wave, multiplier=mult)
    ng = len(eng.gas_list); pd = 4
    p0 = [0.0, 1.0] + [0.1] * ng + [0.0] * (pd + 1)
    bd = ([-np.inf] * len(p0), [np.inf] * len(p0))
    w = AnalysisWorker(eng, [], 775, 1550, p0, bd, -1, channel=1)
    w.ref_properties = REF_PROPS
    w.step_limit = 0.5; w.tikhonov_lambda = 0.0; w.use_robust_fitting = False
    w.allow_negative_gas = False; w.fit_unit = 'px'; w.fit_lo_nm = None; w.fit_hi_nm = None
    w.qc_enabled = False; w.qc_rms_abs = 0.0; w.qc_snr_min = 0.0; w.ok_rms_threshold = 0.10
    w.gas_temp_override = None; w.tz_offset_sec = 0
    return eng, w

def main():
    eng, w = build()
    files = sorted(glob.glob(os.path.join(ALPHA, '*_alpha_trace.dat')))[:4]
    # sequential reference via _fit_alpha_range
    from gui.worker import AnalysisWorker as AW
    expanded = []
    for fp in files:
        lines = open(fp, encoding='utf-8', errors='replace').readlines()
        nrow = sum(1 for l in lines if l.strip() and not l.startswith('#') and not l.startswith('row_idx'))
        expanded += [(fp, r) for r in range(nrow)]
    scans = [(i, fp, r) for i, (fp, r) in enumerate(expanded)]
    seq_res, _, _ = w._fit_alpha_range(scans, 0, 0.0, None)
    seq = {i: r for i, r in seq_res}

    # Fast path via run() (synchronous)
    got = {}
    order = []
    w.result_ready.connect(lambda r, i: (got.__setitem__(i, r), order.append(i)))
    fin = {'done': False}
    w.finished.connect(lambda: fin.__setitem__('done', True))
    w.file_list = files
    w.is_running = True
    w.parallel = True
    w.run()   # synchronous

    n = len(scans)
    print(f'scans={n}  emitted={len(got)}  finished={fin["done"]}  in_order={order == sorted(order)}')
    # compare
    sh = np.array([abs(seq[i].get('Shift', 0) - got[i].get('Shift', 0)) for i in range(n) if i in got])
    no2 = np.array([abs(seq[i].get('NO2', np.nan) - got[i].get('NO2', np.nan)) for i in range(n) if i in got])
    print(f'shift dmax={sh.max():.5f}   NO2 dmax={np.nanmax(no2):.3e}  mean|NO2|={np.nanmean([abs(seq[i].get("NO2",np.nan)) for i in range(n)]):.3f}')

if __name__ == '__main__':
    main()
