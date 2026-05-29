"""
알파 비교 분석 + 플롯 — compare_alpha.py 산출물을 받아 통계·시각화.

산출
----
plots/01_alpha_overlay_midday.png    중간시간대 알파 스펙트럼 오버레이 (CAESAR variants vs MATLAB)
plots/02_alpha_overlay_lambda_lines.png   3개 대표 λ에서 알파 시계열 비교
plots/03_residual_heatmap.png        잔차(CAESAR_A - MATLAB) (bins × pixels)
plots/04_rms_per_pixel.png           픽셀별 RMS 잔차 비교 4 variants
plots/05_correlation_scatter.png     CAESAR vs MATLAB 픽셀-픽셀 산점도
stats.txt                            픽셀 평균/최대 잔차, 상관계수, bias
"""
from __future__ import annotations
import os, numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
PLOT_DIR = os.path.join(HERE, 'plots')
os.makedirs(PLOT_DIR, exist_ok=True)

VARIANTS = [
    ('A_dark_none_sellmeier',         'A: dark=None, σ=Sellmeier'),
    ('B_dark_1500_sellmeier',         'B: dark=1500, σ=Sellmeier'),
    ('C_dark_none_matlab',            'C: dark=None, σ=MATLAB'),
    ('D_dark_1500_matlab',            'D: dark=1500, σ=MATLAB'),
    ('E_flagswap_dark_none_sellmeier','E: ★FLAG SWAP, dark=None'),
    ('F_flagswap_dark_500_sellmeier', 'F: ★FLAG SWAP, dark=500'),
]

wave_nm   = np.load(os.path.join(HERE, 'wave_nm.npy'))             # (2048,)
alpha_mat = np.load(os.path.join(HERE, 'alpha_matlab.npy'))        # (1399, 2048)

caesar = {}
for tag, _ in VARIANTS:
    z = np.load(os.path.join(HERE, f'alpha_caesar_{tag}.npz'))
    caesar[tag] = dict(alpha=z['alpha'], counts=z['counts'], t=z['t_centers'])

# ─── Time alignment ──────────────────────────────────────────────────────────
# MATLAB: 1399 bins, each ~60s, sequential.
# CAESAR: 1437 bins (1379 non-empty), built from raw timestamp grid.
# For first-pass align: skip CAESAR bins with count==0, then linear match to
# MATLAB by ordinal index (both should cover same UTC day in same order).
def aligned_pair(alpha_c, counts_c, alpha_m):
    """Drop empty CAESAR bins, then truncate both to common length."""
    nonempty = counts_c > 0
    a_c = alpha_c[nonempty]
    n = min(len(a_c), len(alpha_m))
    return a_c[:n], alpha_m[:n]


# ─── Stats ───────────────────────────────────────────────────────────────────
stats_lines = []
def banner(s):
    stats_lines.append(''); stats_lines.append('=' * 70)
    stats_lines.append(s); stats_lines.append('=' * 70)

banner('Per-pixel alpha statistics — MATLAB (reference)')
mat_mean = alpha_mat.mean(axis=0)
mat_std  = alpha_mat.std(axis=0)
for px in [200, 500, 1000, 1500, 1800]:
    stats_lines.append(f'  px {px:4d}  λ={wave_nm[px]:7.2f} nm   '
                       f'mean={mat_mean[px]:+.3e}  std={mat_std[px]:.3e}')

banner('CAESAR variant summary  (all bins, all pixels)')
for tag, label in VARIANTS:
    a = caesar[tag]['alpha']
    counts = caesar[tag]['counts']
    valid = counts > 0
    stats_lines.append(f'\n{label}')
    stats_lines.append(f'  n_bins={valid.sum()} / {len(counts)}   '
                       f'mean(|α|)={np.abs(a[valid]).mean():.3e}   '
                       f'median|α|={np.median(np.abs(a[valid])):.3e}')

banner('Residual: CAESAR − MATLAB (after time alignment)')
for tag, label in VARIANTS:
    a_c, a_m = aligned_pair(caesar[tag]['alpha'], caesar[tag]['counts'], alpha_mat)
    diff = a_c - a_m
    rms_per_pix = np.sqrt(np.nanmean(diff**2, axis=0))
    bias_per_pix = np.nanmean(diff, axis=0)
    # robust correlation (mask outliers > 5σ on |MATLAB|)
    mask = (np.abs(a_m) < 5 * np.nanstd(a_m, axis=0))
    a_cm = np.where(mask, a_c, np.nan)
    a_mm = np.where(mask, a_m, np.nan)
    # global pixel-pixel correlation
    flat_c = a_cm.flatten()
    flat_m = a_mm.flatten()
    good = np.isfinite(flat_c) & np.isfinite(flat_m)
    if good.sum() > 100:
        r = np.corrcoef(flat_c[good], flat_m[good])[0, 1]
    else:
        r = np.nan
    stats_lines.append(f'\n{label}')
    stats_lines.append(f'  aligned bins={len(a_c)}   '
                       f'global pixel correlation r={r:+.4f}')
    stats_lines.append(f'  RMS residual per-pixel (sample):')
    for px in [200, 500, 1000, 1500, 1800]:
        stats_lines.append(f'    px{px:4d} λ={wave_nm[px]:6.1f}  '
                           f'bias={bias_per_pix[px]:+.3e}  RMS={rms_per_pix[px]:.3e}  '
                           f'MATLAB std={mat_std[px]:.3e}')

stats_path = os.path.join(HERE, 'stats.txt')
with open(stats_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(stats_lines))
print(f'wrote {stats_path}')

# ─── Plot 1: alpha spectrum overlay at midday (bin ~700) ─────────────────────
fig, ax = plt.subplots(figsize=(12, 5))
mid_m = 700
ax.plot(wave_nm, alpha_mat[mid_m], 'k-', lw=1.5, label=f'MATLAB bin {mid_m}', alpha=0.85)
colors = ['C0', 'C1', 'C2', 'C3', 'magenta', 'darkviolet']
for (tag, label), c in zip(VARIANTS, colors):
    a_c, _ = aligned_pair(caesar[tag]['alpha'], caesar[tag]['counts'], alpha_mat)
    if mid_m < len(a_c):
        ax.plot(wave_nm, a_c[mid_m], '-', lw=0.9, color=c, alpha=0.8, label=label)
ax.set_xlabel('Wavelength (nm)')
ax.set_ylabel('α (cm⁻¹)')
ax.set_title(f'Alpha spectrum overlay — bin {mid_m} (~midday)  2025-06-11 ch1')
ax.set_xlim(300, 510)
ax.set_ylim(-1e-4, 2e-4)
ax.legend(fontsize=9)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '01_alpha_overlay_midday.png'), dpi=120)
plt.close(fig)
print('wrote plots/01_alpha_overlay_midday.png')

# ─── Plot 2: time series of alpha at 3 representative λ ──────────────────────
target_lambdas = [350, 425, 480]
target_pxs = [int(np.argmin(np.abs(wave_nm - λ))) for λ in target_lambdas]

fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
for ax, px, λ in zip(axes, target_pxs, target_lambdas):
    ax.plot(np.arange(len(alpha_mat)), alpha_mat[:, px], 'k-', lw=0.6,
            label='MATLAB', alpha=0.85)
    for (tag, label), c in zip(VARIANTS, colors):
        a_c, a_m = aligned_pair(caesar[tag]['alpha'], caesar[tag]['counts'], alpha_mat)
        ax.plot(np.arange(len(a_c)), a_c[:, px], '-', lw=0.5, color=c,
                alpha=0.7, label=label)
    ax.set_ylabel(f'α @ λ={wave_nm[px]:.1f} nm  (cm⁻¹)')
    ax.grid(alpha=0.3)
    ax.set_ylim(-5e-4, 5e-4)
axes[0].legend(fontsize=8, ncol=5, loc='upper right')
axes[-1].set_xlabel('bin index (~60s each)')
fig.suptitle('Alpha time series at 3 wavelengths')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '02_alpha_overlay_lambda_lines.png'), dpi=120)
plt.close(fig)
print('wrote plots/02_alpha_overlay_lambda_lines.png')

# ─── Plot 3: residual heatmap CAESAR_A − MATLAB ──────────────────────────────
tag_A = VARIANTS[0][0]
a_c, a_m = aligned_pair(caesar[tag_A]['alpha'], caesar[tag_A]['counts'], alpha_mat)
diff = a_c - a_m
fig, ax = plt.subplots(figsize=(12, 6))
vmax = np.nanquantile(np.abs(diff), 0.99)
im = ax.imshow(diff, aspect='auto', cmap='RdBu_r', vmin=-vmax, vmax=vmax,
               extent=[wave_nm[0], wave_nm[-1], len(diff), 0])
ax.set_xlabel('Wavelength (nm)')
ax.set_ylabel('bin index')
ax.set_title(f'Residual: CAESAR (A: dark=None, Sellmeier) − MATLAB     vmax=±{vmax:.2e}')
plt.colorbar(im, ax=ax, label='Δα (cm⁻¹)')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '03_residual_heatmap.png'), dpi=120)
plt.close(fig)
print('wrote plots/03_residual_heatmap.png')

# ─── Plot 4: RMS per pixel for all variants ──────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 5))
for (tag, label), c in zip(VARIANTS, colors):
    a_c, a_m = aligned_pair(caesar[tag]['alpha'], caesar[tag]['counts'], alpha_mat)
    diff = a_c - a_m
    rms = np.sqrt(np.nanmean(diff**2, axis=0))
    ax.semilogy(wave_nm, rms, color=c, lw=1, label=label)
# overlay MATLAB std for reference
ax.semilogy(wave_nm, mat_std, 'k--', lw=1, label='MATLAB std (reference scale)')
ax.set_xlabel('Wavelength (nm)')
ax.set_ylabel('RMS(α_CAESAR − α_MATLAB)  (cm⁻¹)')
ax.set_title('Per-pixel residual RMS across day (log scale)')
ax.set_xlim(300, 510)
ax.legend(fontsize=9)
ax.grid(alpha=0.3, which='both')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '04_rms_per_pixel.png'), dpi=120)
plt.close(fig)
print('wrote plots/04_rms_per_pixel.png')

# ─── Plot 5: correlation scatter — variant A at 3 wavelengths ────────────────
fig, axes = plt.subplots(1, 3, figsize=(15, 5))
a_c, a_m = aligned_pair(caesar[tag_A]['alpha'], caesar[tag_A]['counts'], alpha_mat)
for ax, px in zip(axes, target_pxs):
    ax.scatter(a_m[:, px], a_c[:, px], s=2, alpha=0.4)
    mn = min(a_m[:, px].min(), a_c[:, px].min())
    mx = max(a_m[:, px].max(), a_c[:, px].max())
    ax.plot([mn, mx], [mn, mx], 'r-', lw=0.5, label='y=x')
    ax.set_xlabel('MATLAB α (cm⁻¹)')
    ax.set_ylabel('CAESAR α (cm⁻¹)')
    ax.set_title(f'λ = {wave_nm[px]:.1f} nm')
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
fig.suptitle('CAESAR (A) vs MATLAB scatter, by wavelength')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '05_correlation_scatter.png'), dpi=120)
plt.close(fig)
print('wrote plots/05_correlation_scatter.png')

print('\nDone. See plots/ and stats.txt')
