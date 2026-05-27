"""
2026-05-17 cold 알파 → DOAS 피팅 (CAESAR Pro AlphaFitWorker 로직 standalone)
=================================================================================
Linear LSTSQ:  α(λ) = Σ σ_gas(λ)·N_gas + Σ c_k·T_k(λ)
- gas: NO2, CHOCHO, O4, H2O (Dynamic-ILS-Applied refs)
- baseline: Chebyshev poly (deg=5, HANDOFF.md 박사님 셋팅 참조)
- fit window: 425-490 nm (LED 활성구간 안쪽)

Output:
  doas_fit.tsv         - bin별 ppb + rms
  plots/07*.png        - 시계열·잔차·예시
"""
from __future__ import annotations
import os, numpy as np
from scipy.linalg import lstsq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT_DIR  = r'D:\GHL\CAESAR_Pro_validation_2026_05'
PLOT_DIR = os.path.join(OUT_DIR, 'plots')
REF_FILES = {
    'NO2'   : r'F:\CAESAR cold\Ref_NO2_Dynamic-ILS-Applied.dat',
    'CHOCHO': r'F:\CAESAR cold\Ref_CHOCHO_Dynamic-ILS-Applied.dat',
    'O4'    : r'F:\CAESAR cold\Ref_O4_Dynamic-ILS-Applied.dat',
    'H2O'   : r'F:\CAESAR cold\Ref_H2O-HITRAN_Dynamic-ILS-Applied.dat',
}
# σ scaling - computed at runtime so each A column has comparable norm to poly
# (without this, cond num ~1e19 -> LSTSQ truncates gas columns to zero)
SIGMA_SCALE = {}     # filled below from each column's max|σ|
# unit multiplier: O4 cross-section is in cm⁵·molec⁻² (collision), so coefficient
# directly gives [N_O2]² → need square root and divide by N_air to get ppb O4 partner
# For DOAS practice O4 is reported as fit coefficient (10^46 molec²/cm⁵) not ppb;
# we'll keep coefficient + a "pseudo-ppb" = sqrt(coeff)/N_air
O4_AS_PPB = False

WAVE_FIT_MIN = 425.0   # nm
WAVE_FIT_MAX = 490.0   # nm
POLY_DEG = 5

# ─── Load ────────────────────────────────────────────────────────────────────
A_npz = np.load(os.path.join(OUT_DIR, 'alpha_caesar.npz'))
alpha_all = A_npz['alpha']         # (N_bins, 2048)
counts    = A_npz['counts']
wave_nm   = A_npz['wave_nm']
n_bins, n_pix = alpha_all.shape
print(f'Loaded alpha: {alpha_all.shape}, nonempty bins: {(counts>0).sum()}')

# fit window
fit_mask = (wave_nm >= WAVE_FIT_MIN) & (wave_nm <= WAVE_FIT_MAX)
fit_idx  = np.where(fit_mask)[0]
n_fit    = len(fit_idx)
wave_fit = wave_nm[fit_mask]
print(f'Fit window: λ {wave_fit[0]:.1f}-{wave_fit[-1]:.1f} nm  ({n_fit} px)')

# References + auto scaling so each column has max|σ_scaled| ~ 1
refs = {}
for gas, fp in REF_FILES.items():
    arr = np.loadtxt(fp, comments='#')
    assert len(arr) == n_pix, f'{gas}: ref length {len(arr)} != {n_pix}'
    refs[gas] = arr[fit_mask].astype(np.float64)
    # auto-scale: SCALE = 10^(round(log10(max|σ|)))
    s = float(np.max(np.abs(refs[gas])))
    SIGMA_SCALE[gas] = 10.0 ** np.floor(np.log10(s)) if s > 0 else 1.0
    print(f'  ref {gas:>6}: σ range [{refs[gas].min():+.3e}, {refs[gas].max():+.3e}]   '
          f'SCALE={SIGMA_SCALE[gas]:.0e}  ->  scaled max={s/SIGMA_SCALE[gas]:.2f}')

# ─── Build A matrix ──────────────────────────────────────────────────────────
gas_list = ['NO2', 'CHOCHO', 'O4', 'H2O']
A_ref_cols = []
for g in gas_list:
    A_ref_cols.append(refs[g] / SIGMA_SCALE[g])     # scaled σ
x_norm = 2.0 * (np.arange(n_fit) / max(n_fit - 1, 1)) - 1.0
poly_basis = np.column_stack([
    np.polynomial.chebyshev.chebval(x_norm, np.eye(POLY_DEG + 1)[k])
    for k in range(POLY_DEG + 1)
])
A_ref = np.column_stack(A_ref_cols)
A_full = np.column_stack([A_ref, poly_basis])
print(f'A shape: {A_full.shape}  (n_ref=4, n_poly={POLY_DEG+1})')

# ─── Fit each non-empty bin ──────────────────────────────────────────────────
T_C    = 25.0       # cell conditions assumed constant (HK env_p was default in 2026 data)
P_mbar = 1013.25
N_air  = 2.68678e19 * (P_mbar / 1013.25) * (273.15 / (T_C + 273.15))

results = []  # (bin_idx, ppb_dict, rms, residual_array)
print(f'\nFitting {(counts>0).sum()} bins...')
for bi in range(n_bins):
    if counts[bi] == 0:
        continue
    y = alpha_all[bi, fit_mask].astype(np.float64)
    coeffs, _, _, _ = lstsq(A_full, y)
    gas_coeffs = coeffs[:len(gas_list)]
    ppb = {}
    for gi, g in enumerate(gas_list):
        # gas_coeffs is N_gas in molec/cm³ (already accounting for /SIGMA_SCALE which
        # was divided into the σ - so coeff is in units of SIGMA_SCALE × molec/cm³;
        # multiplying back: N = coeff × (1/SIGMA_SCALE × SIGMA_SCALE) = coeff ... hmm
        # Let me redo: α = σ_scaled · X  where σ_scaled = σ/SIGMA_SCALE → X = N · SIGMA_SCALE
        # so N = X / SIGMA_SCALE. ppb = N/N_air × 1e9.
        if g == 'O4':
            # O4 σ is cm⁵·molec⁻² (collision); X = [O2]² · SIGMA_SCALE
            X = gas_coeffs[gi]
            n2 = X / SIGMA_SCALE[g]
            if n2 > 0 and O4_AS_PPB:
                ppb[g] = np.sqrt(n2) / N_air * 1e9
            else:
                ppb[g] = n2  # raw [molec²/cm⁵] for diagnostic
        else:
            N = gas_coeffs[gi] / SIGMA_SCALE[g]
            ppb[g] = N / N_air * 1e9
    fitted = A_full @ coeffs
    resid  = y - fitted
    rms = float(np.sqrt(np.mean(resid**2)))
    results.append((bi, ppb, rms, resid))

print(f'Fit done - {len(results)} bins')

# ─── Save TSV ────────────────────────────────────────────────────────────────
tsv = os.path.join(OUT_DIR, 'doas_fit.tsv')
with open(tsv, 'w', encoding='utf-8') as f:
    cols = ['bin_idx'] + [f'{g}_ppb' if g != 'O4' else 'O4_n2_cm-5' for g in gas_list] + ['rms_cm-1']
    f.write('\t'.join(cols) + '\n')
    for bi, ppb, rms, _ in results:
        vals = [f'{bi}']
        for g in gas_list:
            vals.append(f'{ppb[g]:.4e}')
        vals.append(f'{rms:.4e}')
        f.write('\t'.join(vals) + '\n')
print(f'wrote {tsv}')

# ─── Stats ───────────────────────────────────────────────────────────────────
bins_arr = np.array([r[0] for r in results])
ppb_arr  = {g: np.array([r[1][g] for r in results]) for g in gas_list}
rms_arr  = np.array([r[2] for r in results])
resid_mat = np.array([r[3] for r in results])  # (N_results, n_fit)

print('\n=== DOAS Fit Stats ===')
for g in gas_list:
    a = ppb_arr[g]
    label = 'ppb' if g != 'O4' else 'molec2/cm5'
    print(f'  {g:>6}: mean={np.mean(a):+.3e}  med={np.median(a):+.3e}  std={np.std(a):.3e}  ({label})')
print(f'  RMS:    mean={rms_arr.mean():.3e}  med={np.median(rms_arr):.3e}  ({rms_arr.min():.3e} ~ {rms_arr.max():.3e}) cm-1')

# ─── Plots ───────────────────────────────────────────────────────────────────
# 07: NO2 / CHOCHO / H2O / O4 time series
fig, axes = plt.subplots(4, 1, figsize=(12, 11), sharex=True)
units = ['ppb', 'ppb', 'molec²/cm⁵', 'ppb']
ylims = [(-5, 20), (-2, 5), None, (-100, 5000)]
for ax, g, u, yl in zip(axes, gas_list, units, ylims):
    ax.plot(bins_arr, ppb_arr[g], '.', ms=2, alpha=0.5)
    ax.axhline(0, color='r', ls='--', lw=0.5)
    ax.set_ylabel(f'{g} ({u})')
    ax.grid(alpha=0.3)
    if yl: ax.set_ylim(yl)
axes[0].set_title('DOAS fit time series - 2026-05-17 cold (1-min bins)')
axes[-1].set_xlabel('bin index (60s each)')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '07_doas_timeseries.png'), dpi=120)
plt.close(fig)
print('wrote 07_doas_timeseries.png')

# 08: RMS time series
fig, ax = plt.subplots(figsize=(12, 4))
ax.semilogy(bins_arr, rms_arr, '.', ms=2)
ax.set_xlabel('bin index')
ax.set_ylabel('RMS residual (cm⁻¹)')
ax.set_title(f'DOAS RMS - median {np.median(rms_arr):.2e}  (fit window {WAVE_FIT_MIN:.0f}-{WAVE_FIT_MAX:.0f} nm, poly={POLY_DEG})')
ax.grid(alpha=0.3, which='both')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '08_doas_rms.png'), dpi=120)
plt.close(fig)
print('wrote 08_doas_rms.png')

# 09: 3 example bins - alpha, fit, residual
ex_idx = [len(results)//5, len(results)//2, len(results)*4//5]
fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
for ax, ei in zip(axes, ex_idx):
    bi, ppb, rms, resid = results[ei]
    y = alpha_all[bi, fit_mask]
    fitted = y - resid
    ax.plot(wave_fit, y, 'k-', lw=0.7, label='α (measured)')
    ax.plot(wave_fit, fitted, 'r-', lw=0.7, label='α (fit)')
    ax2 = ax.twinx()
    ax2.plot(wave_fit, resid, 'b-', lw=0.5, alpha=0.6, label='residual')
    ax2.set_ylabel('residual (cm⁻¹)', color='b')
    ax.set_ylabel('α (cm⁻¹)')
    ax.legend(loc='upper left', fontsize=8)
    ax2.legend(loc='upper right', fontsize=8)
    ax.set_title(f'bin {bi}  NO2={ppb["NO2"]:+.2f} ppb  CHOCHO={ppb["CHOCHO"]:+.2f} ppb  '
                 f'H2O={ppb["H2O"]:+.2e} ppb  RMS={rms:.2e}')
    ax.grid(alpha=0.3)
axes[-1].set_xlabel('Wavelength (nm)')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '09_doas_examples.png'), dpi=120)
plt.close(fig)
print('wrote 09_doas_examples.png')

# 10: residual heatmap
fig, ax = plt.subplots(figsize=(12, 6))
vmax = np.nanquantile(np.abs(resid_mat), 0.99)
im = ax.imshow(resid_mat, aspect='auto', cmap='RdBu_r', vmin=-vmax, vmax=vmax,
               extent=[wave_fit[0], wave_fit[-1], len(resid_mat), 0])
ax.set_xlabel('Wavelength (nm)')
ax.set_ylabel('bin (chronological)')
ax.set_title(f'DOAS residual heatmap - vmax=±{vmax:.2e}')
plt.colorbar(im, ax=ax, label='residual (cm⁻¹)')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '10_doas_residual_heatmap.png'), dpi=120)
plt.close(fig)
print('wrote 10_doas_residual_heatmap.png')

# Report
with open(os.path.join(OUT_DIR, 'doas_report.txt'), 'w', encoding='utf-8') as f:
    f.write(f'DOAS fit - 2026-05-17 cold\n')
    f.write(f'Fit window: {WAVE_FIT_MIN}-{WAVE_FIT_MAX} nm  ({n_fit} px)\n')
    f.write(f'Polynomial degree: {POLY_DEG}\n')
    f.write(f'N bins fitted: {len(results)}\n\n')
    f.write('Per-gas stats:\n')
    for g in gas_list:
        a = ppb_arr[g]
        u = 'ppb' if g != 'O4' else 'molec²/cm⁵'
        f.write(f'  {g:>6}: mean={np.mean(a):+.4e}  med={np.median(a):+.4e}  std={np.std(a):.4e}  ({u})\n')
    f.write(f'\nRMS: mean={rms_arr.mean():.3e}  med={np.median(rms_arr):.3e} cm⁻¹\n')
print('wrote doas_report.txt')
