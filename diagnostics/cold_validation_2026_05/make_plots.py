"""
2026-05-17 cold CAESAR Pro 알파 결과 시각화.
"""
import os, numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT_DIR  = r'D:\GHL\CAESAR_Pro_validation_2026_05'
PLOT_DIR = os.path.join(OUT_DIR, 'plots')
os.makedirs(PLOT_DIR, exist_ok=True)

# Load arrays
A     = np.load(os.path.join(OUT_DIR, 'alpha_caesar.npz'))
C     = np.load(os.path.join(OUT_DIR, 'calib.npz'))
M     = np.load(os.path.join(OUT_DIR, 'mean_spectra.npz'))
alpha = A['alpha']
counts = A['counts']
wave_nm = A['wave_nm']

# ─── Plot 1: Mean spectra — verify He > ZA, LED profile ──────────────────────
fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(wave_nm, M['he'], 'b-', lw=1.2, label=f'He mean (flag 510)  peak={M["he"].max():.0f}')
ax.plot(wave_nm, M['za'], 'g-', lw=1.2, label=f'ZA mean (flag 500)  peak={M["za"].max():.0f}')
ax.plot(wave_nm, M['amb_mean'], 'k-', lw=0.6, alpha=0.7,
        label=f'Ambient mean (flag 1) peak={M["amb_mean"].max():.0f}')
ax.plot(wave_nm, M['amb_min'], 'r--', lw=0.6, alpha=0.7,
        label=f'Ambient min (dark proxy) min={M["amb_min"].min():.0f}')
ax.set_xlabel('Wavelength (nm)')
ax.set_ylabel('Intensity (counts)')
ax.set_title('Mean spectra 2026-05-17 cold — He vs ZA contrast check')
ax.legend(fontsize=9)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '01_mean_spectra.png'), dpi=120)
plt.close(fig)
print('wrote 01_mean_spectra.png')

# ─── Plot 2: I_ZA / I_He ratio — should be <1 across LED active range ────────
fig, ax = plt.subplots(figsize=(12, 4))
ratio = M['za'] / np.where(np.abs(M['he']) > 1, M['he'], 1)
ax.plot(wave_nm, ratio, 'k-', lw=0.8)
ax.axhline(1, color='r', ls='--', label='ratio=1 (boundary)')
ax.set_xlabel('Wavelength (nm)')
ax.set_ylabel('I_ZA / I_He')
ax.set_title('R-cal input ratio — Washenfelder needs <1 (cavity dimmer in ZA)')
ax.set_ylim(0.6, 1.1)
ax.legend(fontsize=9)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '02_iza_ihe_ratio.png'), dpi=120)
plt.close(fig)
print('wrote 02_iza_ihe_ratio.png')

# ─── Plot 3: omr_d (R-cal) per block + median ────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 5))
for omr in C['cands']:
    ax.plot(wave_nm, omr, '-', lw=0.4, alpha=0.4)
ax.plot(wave_nm, C['best_omr'], 'k-', lw=1.5, label='median best_omr_d')
ax.axhline(0, color='r', ls='--', lw=0.5)
ax.set_xlabel('Wavelength (nm)')
ax.set_ylabel('omr_d (cm⁻¹)')
ax.set_title(f'R calibration omr_d — {len(C["cands"])} ZA blocks')
ax.legend(fontsize=9)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '03_omr_d.png'), dpi=120)
plt.close(fig)
print('wrote 03_omr_d.png')

# ─── Plot 4: sample alpha spectra at 3 times ─────────────────────────────────
nonempty = np.where(counts > 0)[0]
n3 = [nonempty[len(nonempty)//5], nonempty[len(nonempty)//2], nonempty[len(nonempty)*4//5]]

fig, ax = plt.subplots(figsize=(12, 5))
for bi, c in zip(n3, ['C0', 'C1', 'C2']):
    ax.plot(wave_nm, alpha[bi], '-', lw=0.8, color=c, label=f'bin {bi}')
ax.axhline(0, color='k', ls='--', lw=0.5)
ax.set_xlabel('Wavelength (nm)')
ax.set_ylabel('α (cm⁻¹)')
ax.set_title('Sample alpha spectra — 3 representative time bins')
ax.legend(fontsize=9)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '04_alpha_samples.png'), dpi=120)
plt.close(fig)
print('wrote 04_alpha_samples.png')

# ─── Plot 5: alpha time series at 3 representative λ ─────────────────────────
target_lambdas = [430, 450, 470]
target_pxs = [int(np.argmin(np.abs(wave_nm - L))) for L in target_lambdas]
fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
x_bins = np.arange(len(alpha))
for ax, px, L in zip(axes, target_pxs, target_lambdas):
    y = alpha[:, px].copy(); y[counts == 0] = np.nan
    ax.plot(x_bins, y, '-', lw=0.5, color='C0')
    ax.set_ylabel(f'α @ λ={wave_nm[px]:.1f} nm  (cm⁻¹)')
    ax.grid(alpha=0.3)
    ax.set_ylim(-1e-5, 1e-5)
axes[-1].set_xlabel('bin index (60s each)')
axes[0].set_title('Alpha time series — 2026-05-17 cold')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '05_alpha_timeseries.png'), dpi=120)
plt.close(fig)
print('wrote 05_alpha_timeseries.png')

# ─── Plot 6: alpha heatmap (bins × pixels) ───────────────────────────────────
nz = alpha[counts > 0]
fig, ax = plt.subplots(figsize=(12, 6))
vmax = np.nanquantile(np.abs(nz), 0.95)
im = ax.imshow(nz, aspect='auto', cmap='RdBu_r', vmin=-vmax, vmax=vmax,
               extent=[wave_nm[0], wave_nm[-1], len(nz), 0])
ax.set_xlabel('Wavelength (nm)')
ax.set_ylabel('bin index (60s each, nonempty only)')
ax.set_title(f'Alpha heatmap — vmax=±{vmax:.2e}')
plt.colorbar(im, ax=ax, label='α (cm⁻¹)')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '06_alpha_heatmap.png'), dpi=120)
plt.close(fig)
print('wrote 06_alpha_heatmap.png')

# ─── Text report ─────────────────────────────────────────────────────────────
lines = []
lines.append('=' * 70)
lines.append('CAESAR Pro Alpha Validation — 2026-05-17 cold setup')
lines.append('=' * 70)
lines.append(f'Wavelength range: {wave_nm[0]:.2f} ~ {wave_nm[-1]:.2f} nm  ({len(wave_nm)} px)')
lines.append('')
lines.append('-- Mean spectra ---------------------------------------------')
lines.append(f'  He  (flag 510, strict): peak {M["he"].max():.0f}  '
             f'@ λ={wave_nm[np.argmax(M["he"])]:.1f} nm')
lines.append(f'  ZA  (flag 500, strict): peak {M["za"].max():.0f}  '
             f'@ λ={wave_nm[np.argmax(M["za"])]:.1f} nm')
lines.append(f'  contrast (He-ZA)/He: {(M["he"].max()-M["za"].max())/M["he"].max()*100:.1f} %')
lines.append(f'  Ambient mean peak: {M["amb_mean"].max():.0f}')
lines.append(f'  Ambient min (dark proxy): {M["amb_min"].min():.0f}')
lines.append('')
lines.append('-- R calibration --------------------------------------------')
lines.append(f'  ZA blocks: {len(C["za_blocks"])}')
lines.append(f'  He blocks: {len(C["he_blocks"])}')
lines.append(f'  R-cal candidates passed threshold: {len(C["cands"])}')
lines.append(f'  best_omr_d mean: {C["best_omr"].mean():.3e} cm⁻¹')
lines.append(f'  → Leff ≈ {1.0/C["best_omr"].mean()*1e-5:.2f} km')
lines.append(f'  → if d=100cm: (1-R) ≈ {C["best_omr"].mean()*100:.4f}  → R ≈ {1 - C["best_omr"].mean()*100:.4f}')
lines.append('')
lines.append('-- Alpha statistics -----------------------------------------')
lines.append(f'  total bins: {len(counts)}    nonempty: {(counts>0).sum()}')
nz_alpha = alpha[counts > 0]
lines.append(f'  mean(|α|) across all bins×pixels: {np.abs(nz_alpha).mean():.3e} cm⁻¹')
lines.append(f'  median|α|:                       {np.median(np.abs(nz_alpha)):.3e}')
lines.append('')
lines.append('  Per-pixel mean α (sample λ):')
for L in [410, 430, 450, 470, 490]:
    px = int(np.argmin(np.abs(wave_nm - L)))
    a = nz_alpha[:, px]
    lines.append(f'    λ={wave_nm[px]:6.1f} nm  '
                 f'mean={np.nanmean(a):+.3e}  std={np.nanstd(a):.3e}')

report = '\n'.join(lines)
with open(os.path.join(OUT_DIR, 'report.txt'), 'w', encoding='utf-8') as f:
    f.write(report)
print('wrote report.txt')
