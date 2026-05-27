"""
DOAS 피팅 v2 — shift/squeeze + NO2 link + 좁은 윈도우
======================================================
v1 대비 추가 사항 (CAESAR Pro engine.py 로직 모사):
  - 피팅 윈도우 430-480 nm로 축소 (사용자 지정)
  - NO2 shift, squeeze nonlinear 피팅 (±5 px, ±0.01 limit)
  - CHOCHO/H2O/O4 shift/squeeze는 NO2에 LINK (같은 값 사용)
  - VarPro: outer L-BFGS on (shift, squeeze), inner linear lstsq on coeffs+poly
  - Robust loss 옵션 (Huber, --robust)
  - 사후 Kalman smoothing 옵션 (--kalman)

사용:
  python doas_fit_v2.py --input alpha_caesar.npz
  python doas_fit_v2.py --robust --kalman   (옵션 추가)
"""
from __future__ import annotations
import os, sys, argparse, numpy as np
from scipy.linalg import lstsq
from scipy.optimize import minimize
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# CAESAR Pro repo for KalmanTracker
sys.path.insert(0, r'C:\Doasis_Work\CAESAR_Pro')
from core.physics import KalmanTracker

OUT_DIR  = r'D:\GHL\CAESAR_Pro_validation_2026_05'
PLOT_DIR = os.path.join(OUT_DIR, 'plots')
os.makedirs(PLOT_DIR, exist_ok=True)
REF_FILES = {
    'NO2'   : r'F:\CAESAR cold\Ref_NO2_Dynamic-ILS-Applied.dat',
    'CHOCHO': r'F:\CAESAR cold\Ref_CHOCHO_Dynamic-ILS-Applied.dat',
    'O4'    : r'F:\CAESAR cold\Ref_O4_Dynamic-ILS-Applied.dat',
    'H2O'   : r'F:\CAESAR cold\Ref_H2O-HITRAN_Dynamic-ILS-Applied.dat',
}
GAS_LIST = ['NO2', 'CHOCHO', 'O4', 'H2O']

WAVE_FIT_MIN = 430.0
WAVE_FIT_MAX = 480.0
POLY_DEG     = 5
SHIFT_LIM    = (-5.0, +5.0)     # px (CAESAR Pro 표준)
SQUEEZE_LIM  = (1 - 0.01, 1 + 0.01)  # ±1%

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default=os.path.join(OUT_DIR, 'alpha_caesar.npz'),
                    help='alpha .npz with arrays alpha, counts, wave_nm')
    ap.add_argument('--robust', action='store_true', help='Huber loss outer')
    ap.add_argument('--kalman', action='store_true', help='Kalman smooth ppb time series')
    ap.add_argument('--tag', default='v2', help='output tag (suffix on tsv/plots)')
    return ap.parse_args()

args = parse_args()
TAG = args.tag

# ─── Load alpha + refs ───────────────────────────────────────────────────────
A_npz = np.load(args.input)
alpha_all = A_npz['alpha']; counts = A_npz['counts']; wave_nm = A_npz['wave_nm']
n_bins, n_pix = alpha_all.shape
print(f'Loaded alpha {alpha_all.shape}  nonempty {(counts>0).sum()}')

fit_mask = (wave_nm >= WAVE_FIT_MIN) & (wave_nm <= WAVE_FIT_MAX)
fit_idx  = np.where(fit_mask)[0]
n_fit    = len(fit_idx)
wave_fit = wave_nm[fit_mask]
print(f'Fit window {wave_fit[0]:.1f}-{wave_fit[-1]:.1f} nm  ({n_fit} px)')

# load full-band ref + interpolators (we'll evaluate at shifted/squeezed pixels)
from scipy.interpolate import interp1d
ref_interps = {}
SIGMA_SCALE = {}
for g, fp in REF_FILES.items():
    arr = np.loadtxt(fp, comments='#')
    assert len(arr) == n_pix, f'{g}: ref length {len(arr)} != {n_pix}'
    SIGMA_SCALE[g] = 10.0 ** np.floor(np.log10(np.max(np.abs(arr))))
    # interpolator over PIXEL index (so shift in px works naturally)
    px_full = np.arange(n_pix, dtype=float)
    ref_interps[g] = interp1d(px_full, arr / SIGMA_SCALE[g],
                              kind='cubic', bounds_error=False, fill_value=0.0)
    print(f'  ref {g:>6}: SCALE={SIGMA_SCALE[g]:.0e}')

# Pre-build polynomial basis (no shift on baseline)
x_norm = 2.0 * (np.arange(n_fit) / max(n_fit - 1, 1)) - 1.0
poly_basis = np.column_stack([
    np.polynomial.chebyshev.chebval(x_norm, np.eye(POLY_DEG + 1)[k])
    for k in range(POLY_DEG + 1)
])

# Center pixel for shift/squeeze (use fit-window middle)
center_px = fit_idx[len(fit_idx) // 2]

# ─── Inner: build A matrix at given (shift, squeeze) ─────────────────────────
def build_A(shift, squeeze):
    """Return (A, refs_dict) — refs evaluated at shifted/squeezed pixels."""
    px_shifted = (fit_idx - center_px) * squeeze + center_px + shift
    refs_at = {g: ref_interps[g](px_shifted) for g in GAS_LIST}
    A_ref = np.column_stack([refs_at[g] for g in GAS_LIST])
    A = np.column_stack([A_ref, poly_basis])
    return A, refs_at

def fit_one_bin(y, robust=False):
    """Outer optimize shift/squeeze; inner linear lstsq for coeffs."""
    def cost(params):
        shift, squeeze = params
        A, _ = build_A(shift, squeeze)
        coef, _, _, _ = lstsq(A, y)
        resid = y - A @ coef
        if robust:
            # Huber loss with delta = 1.5·MAD
            mad = np.median(np.abs(resid - np.median(resid))) + 1e-30
            delta = 1.5 * mad
            r = np.abs(resid)
            inside = r <= delta
            return float(np.sum(0.5 * resid[inside]**2)
                         + np.sum(delta * (r[~inside] - 0.5*delta)))
        return float(np.sum(resid**2))

    # Outer: 2-D bounded optimize on (shift_px, squeeze)
    res = minimize(cost, x0=[0.0, 1.0],
                   bounds=[SHIFT_LIM, SQUEEZE_LIM], method='L-BFGS-B',
                   options={'maxiter': 30, 'ftol': 1e-12})
    shift_opt, squeeze_opt = float(res.x[0]), float(res.x[1])
    A, refs_at = build_A(shift_opt, squeeze_opt)
    coef, _, _, _ = lstsq(A, y)
    fitted = A @ coef
    resid = y - fitted
    rms = float(np.sqrt(np.mean(resid**2)))
    return shift_opt, squeeze_opt, coef, fitted, resid, rms

# ─── Fit each bin ────────────────────────────────────────────────────────────
T_C, P_mbar = 25.0, 1013.25
N_air = 2.68678e19 * (P_mbar/1013.25) * (273.15/(T_C+273.15))

results = []  # (bi, shift, sq, ppb_dict, rms, resid)
print(f'\nFitting {(counts>0).sum()} bins (robust={args.robust})...')
for bi in range(n_bins):
    if counts[bi] == 0:
        continue
    y = alpha_all[bi, fit_mask].astype(np.float64)
    shift_opt, sq_opt, coef, fitted, resid, rms = fit_one_bin(y, robust=args.robust)
    gas_coef = coef[:len(GAS_LIST)]
    ppb = {}
    for gi, g in enumerate(GAS_LIST):
        N = gas_coef[gi] / SIGMA_SCALE[g]   # molec/cm^3
        if g == 'O4':
            ppb[g] = N   # raw n^2 cm-5
        else:
            ppb[g] = N / N_air * 1e9
    results.append((bi, shift_opt, sq_opt, ppb, rms, resid))
    if len(results) % 100 == 0:
        print(f'  {len(results)} bins done')
print(f'Fit done - {len(results)} bins')

# Stack arrays
bins_arr  = np.array([r[0] for r in results])
shift_arr = np.array([r[1] for r in results])
sq_arr    = np.array([r[2] for r in results])
ppb_arr   = {g: np.array([r[3][g] for r in results]) for g in GAS_LIST}
rms_arr   = np.array([r[4] for r in results])
resid_mat = np.array([r[5] for r in results])

# Optional Kalman smoothing
if args.kalman:
    kal = KalmanTracker(num_variables=len(GAS_LIST), q_noise=1e-4, r_noise=1e-2)
    smoothed = {g: np.zeros_like(ppb_arr[g]) for g in GAS_LIST}
    for i in range(len(results)):
        z = np.array([ppb_arr[g][i] for g in GAS_LIST])
        s = kal.process(z)
        for gi, g in enumerate(GAS_LIST):
            smoothed[g][i] = s[gi]
else:
    smoothed = None

# ─── Save TSV ────────────────────────────────────────────────────────────────
tsv = os.path.join(OUT_DIR, f'doas_fit_{TAG}.tsv')
with open(tsv, 'w', encoding='utf-8') as f:
    cols = ['bin','shift_px','squeeze'] + [f'{g}_ppb' if g!='O4' else 'O4_n2_cm-5' for g in GAS_LIST] + ['rms']
    f.write('\t'.join(cols) + '\n')
    for r in results:
        bi, sh, sq, ppb, rms, _ = r
        row = [f'{bi}', f'{sh:+.4f}', f'{sq:.6f}']
        row += [f'{ppb[g]:+.4e}' for g in GAS_LIST]
        row.append(f'{rms:.4e}')
        f.write('\t'.join(row) + '\n')
print(f'wrote {tsv}')

# Stats
print('\n=== Stats ===')
for g in GAS_LIST:
    a = ppb_arr[g]
    u = 'ppb' if g != 'O4' else 'molec2/cm5'
    print(f'  {g:>6}: mean={np.mean(a):+.3e}  med={np.median(a):+.3e}  std={np.std(a):.3e}  ({u})')
print(f'  RMS:    mean={rms_arr.mean():.3e}  med={np.median(rms_arr):.3e}')
print(f'  shift:  median={np.median(shift_arr):+.3f} px  range [{shift_arr.min():+.2f}, {shift_arr.max():+.2f}]')
print(f'  squeeze:median={np.median(sq_arr):.6f}  range [{sq_arr.min():.4f}, {sq_arr.max():.4f}]')

# ─── Plots ───────────────────────────────────────────────────────────────────
# 11: NO2/CHOCHO time series (raw + Kalman if available)
fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
for ax, g, yl in zip(axes, ['NO2', 'CHOCHO'], [(-5, 20), (-3, 5)]):
    ax.plot(bins_arr, ppb_arr[g], '.', ms=2, alpha=0.4, label=f'{g} raw')
    if smoothed:
        ax.plot(bins_arr, smoothed[g], '-', lw=1, color='r', label=f'{g} Kalman')
    ax.axhline(0, color='k', ls='--', lw=0.5)
    ax.set_ylabel(f'{g} (ppb)')
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    if yl: ax.set_ylim(yl)
axes[0].set_title(f'DOAS v2 NO2/CHOCHO ts  win {WAVE_FIT_MIN}-{WAVE_FIT_MAX}nm  '
                  f'NO2 shift/squeeze fit  others LINKED  robust={args.robust}')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, f'11_doas_{TAG}_no2_chocho_ts.png'), dpi=120)
plt.close(fig)
print(f'wrote 11_doas_{TAG}_no2_chocho_ts.png')

# 12: shift/squeeze/rms time series
fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
axes[0].plot(bins_arr, shift_arr, '.', ms=2)
axes[0].set_ylabel('shift (px)'); axes[0].axhline(0, color='r', ls='--', lw=0.5)
axes[0].set_ylim(SHIFT_LIM); axes[0].grid(alpha=0.3)
axes[1].plot(bins_arr, sq_arr, '.', ms=2)
axes[1].set_ylabel('squeeze'); axes[1].axhline(1, color='r', ls='--', lw=0.5)
axes[1].set_ylim(SQUEEZE_LIM); axes[1].grid(alpha=0.3)
axes[2].semilogy(bins_arr, rms_arr, '.', ms=2)
axes[2].set_ylabel('RMS (cm-1)'); axes[2].grid(alpha=0.3, which='both')
axes[2].set_xlabel('bin index')
axes[0].set_title('DOAS v2 nuisance parameters')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, f'12_doas_{TAG}_nuisance.png'), dpi=120)
plt.close(fig)
print(f'wrote 12_doas_{TAG}_nuisance.png')

# 13: 3 example fits with shift/squeeze annotation
ex_idx = [len(results)//5, len(results)//2, len(results)*4//5]
fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
for ax, ei in zip(axes, ex_idx):
    bi, sh, sq, ppb, rms, resid = results[ei]
    y = alpha_all[bi, fit_mask]
    fitted = y - resid
    ax.plot(wave_fit, y, 'k-', lw=0.7, label='alpha')
    ax.plot(wave_fit, fitted, 'r-', lw=0.7, label='fit')
    ax2 = ax.twinx()
    ax2.plot(wave_fit, resid, 'b-', lw=0.4, alpha=0.5)
    ax2.set_ylabel('resid', color='b')
    ax.set_ylabel('alpha (cm-1)')
    ax.legend(loc='upper left', fontsize=8)
    ax.set_title(f'bin {bi}  shift={sh:+.2f}px  sq={sq:.5f}  '
                 f'NO2={ppb["NO2"]:+.2f}ppb  CHOCHO={ppb["CHOCHO"]:+.2f}ppb  RMS={rms:.2e}')
    ax.grid(alpha=0.3)
axes[-1].set_xlabel('Wavelength (nm)')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, f'13_doas_{TAG}_examples.png'), dpi=120)
plt.close(fig)
print(f'wrote 13_doas_{TAG}_examples.png')

# Report
with open(os.path.join(OUT_DIR, f'doas_report_{TAG}.txt'), 'w', encoding='utf-8') as f:
    f.write(f'DOAS v2 fit summary - 2026-05-17 cold\n')
    f.write(f'Fit window: {WAVE_FIT_MIN}-{WAVE_FIT_MAX} nm ({n_fit} px), poly={POLY_DEG}\n')
    f.write(f'Shift fit (NO2): bounds {SHIFT_LIM} px\n')
    f.write(f'Squeeze fit (NO2): bounds {SQUEEZE_LIM}\n')
    f.write(f'CHOCHO/O4/H2O: shift/squeeze LINKED to NO2\n')
    f.write(f'Robust: {args.robust}    Kalman: {args.kalman}\n')
    f.write(f'N bins fitted: {len(results)}\n\n')
    f.write('Per-gas:\n')
    for g in GAS_LIST:
        a = ppb_arr[g]; u = 'ppb' if g != 'O4' else 'molec2/cm5'
        f.write(f'  {g:>6}: mean={np.mean(a):+.4e}  med={np.median(a):+.4e}  std={np.std(a):.4e}  ({u})\n')
    f.write(f'\nRMS: mean={rms_arr.mean():.3e}  med={np.median(rms_arr):.3e}  cm-1\n')
    f.write(f'shift  px median {np.median(shift_arr):+.3f}  range [{shift_arr.min():+.2f}, {shift_arr.max():+.2f}]\n')
    f.write(f'squeeze median {np.median(sq_arr):.6f}  range [{sq_arr.min():.4f}, {sq_arr.max():.4f}]\n')
print(f'wrote doas_report_{TAG}.txt')
