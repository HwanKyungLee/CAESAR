"""
박사님 alpha (DOASIS) vs CAESAR alpha (500/510 플래그, 60-scan bin) 비교.
파일별 C/D, 파장별 C/D, 상세 진단 포함.
"""
import sys, os, glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.stdout.reconfigure(encoding='utf-8')

PIXEL_MIN = 1453
PIXEL_MAX = 1646   # exclusive

DOASIS_DIR  = r"c:\Doasis_Work\CAESAR_Pro\아라온호 데이터분석\alpha_trace\ch1_20250610_000000"
CAESAR_DIR  = r"c:\Doasis_Work\CAESAR_Pro\raw(ex)"
OUT_DIR     = r"c:\Doasis_Work\CAESAR_Pro\raw(ex)"
WV_FILE     = r"c:\Doasis_Work\CAESAR_Pro\아라온호 데이터분석\wavelength\wv_2025_Araon.txt"

# ── 파장 축 ─────────────────────────────────────────────────────────────────
wv_all  = pd.read_csv(WV_FILE, sep=r'\s+', header=None, comment='#').iloc[:,0].values
wave_nm = wv_all[PIXEL_MIN:PIXEL_MAX]
n_pix   = len(wave_nm)
print(f"파장: {wave_nm[0]:.2f}~{wave_nm[-1]:.2f} nm  ({n_pix} px)")

# ── 박사님 파일 로드 (fit window만) ─────────────────────────────────────────
doasis_files = sorted(glob.glob(os.path.join(DOASIS_DIR, "*.dat")))
doasis_alpha = []
for f in doasis_files:
    d = np.loadtxt(f)
    fw = d[PIXEL_MIN:PIXEL_MAX]
    if np.any(fw != 0):
        doasis_alpha.append(fw)
doasis_alpha = np.array(doasis_alpha)   # (N_doasis, 193)
n_doasis = len(doasis_alpha)
print(f"박사님 alpha: {n_doasis}개 (all-zero 제외)")

# ── CAESAR alpha 로드: 파일별 구분 ──────────────────────────────────────────
caesar_files = sorted(glob.glob(os.path.join(CAESAR_DIR, "2025-06-10-*_alpha_trace.dat")))
caesar_alpha  = []   # 전체 bins (순서대로)
caesar_file_of_bin = []  # 각 bin이 어느 raw 파일에서 왔는지

for f in caesar_files:
    raw_label = os.path.basename(f).replace('2025-06-10-', '').replace('_alpha_trace.dat', '')
    with open(f, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 4:
                continue
            try:
                int(parts[0])
            except ValueError:
                continue
            alpha = np.array([float(v) for v in parts[3:3+n_pix]])
            caesar_alpha.append(alpha)
            caesar_file_of_bin.append(raw_label)

caesar_alpha = np.array(caesar_alpha)   # (N_caesar, 193)
n_caesar = len(caesar_alpha)
print(f"CAESAR alpha:  {n_caesar}개 bins  (파일 {len(caesar_files)}개)")

# ── 파일 수 맞추기 (짧은 쪽 기준) ──────────────────────────────────────────
n_cmp = min(n_doasis, n_caesar)
doasis_cmp = doasis_alpha[:n_cmp]
caesar_cmp = caesar_alpha[:n_cmp]
file_labels = caesar_file_of_bin[:n_cmp]

# ── 픽셀 평균 타임시리즈 ─────────────────────────────────────────────────────
doasis_ts  = np.mean(doasis_cmp,  axis=1)
caesar_ts  = np.mean(caesar_cmp,  axis=1)

# ── 전체 통계 ────────────────────────────────────────────────────────────────
diff  = caesar_ts - doasis_ts
ratio = np.where(np.abs(doasis_ts) > 1e-9, caesar_ts / doasis_ts, np.nan)
print(f"\n[전체 비교] {n_cmp}개 bins, fit-window 평균")
print(f"  박사님  mean={np.mean(doasis_ts):.4e}  std={np.std(doasis_ts):.4e}")
print(f"  CAESAR  mean={np.mean(caesar_ts):.4e}  std={np.std(caesar_ts):.4e}")
print(f"  차이(C-D)  mean={np.mean(diff):.4e}  std={np.std(diff):.4e}")
print(f"  비율(C/D)  mean={np.nanmean(ratio):.4f}  median={np.nanmedian(ratio):.4f}"
      f"  std={np.nanstd(ratio):.4f}  (NaN={np.sum(np.isnan(ratio))}개)")

# ── 파일별 C/D ───────────────────────────────────────────────────────────────
unique_files = sorted(set(file_labels), key=lambda x: int(x) if x.isdigit() else 0)
print(f"\n[파일별 C/D]")
print(f"  {'file':>4}  {'n_bins':>6}  {'D mean':>10}  {'C mean':>10}  "
      f"{'C/D med':>8}  {'C/D std':>8}  {'diff mean':>10}")
file_cd_medians = {}
for fl in unique_files:
    mask = np.array([lb == fl for lb in file_labels])
    if not mask.any():
        continue
    d_sub  = doasis_ts[mask]
    c_sub  = caesar_ts[mask]
    r_sub  = ratio[mask]
    r_valid = r_sub[np.isfinite(r_sub)]
    cd_med = float(np.nanmedian(r_valid)) if len(r_valid) > 0 else np.nan
    file_cd_medians[fl] = cd_med
    print(f"  {fl:>4}  {mask.sum():6d}  {np.nanmean(d_sub):10.4e}  {np.nanmean(c_sub):10.4e}  "
          f"  {cd_med:7.4f}   {float(np.nanstd(r_valid)):7.4f}  {float(np.nanmean(c_sub-d_sub)):10.4e}")

# ── 파장 구간별 C/D ───────────────────────────────────────────────────────────
wv_bands = [(wave_nm[0], 450), (450, 470), (470, 490), (490, wave_nm[-1])]
print(f"\n[파장 구간별 C/D]  ({wave_nm[0]:.1f}~{wave_nm[-1]:.1f} nm)")
print(f"  {'band':>14}  {'D mean':>10}  {'C mean':>10}  {'C/D':>7}")
for (w0, w1) in wv_bands:
    px_mask = (wave_nm >= w0) & (wave_nm < w1)
    if not px_mask.any():
        continue
    d_band = np.mean(doasis_cmp[:, px_mask], axis=1)
    c_band = np.mean(caesar_cmp[:, px_mask], axis=1)
    r_band = np.where(np.abs(d_band) > 1e-9, c_band / d_band, np.nan)
    print(f"  {w0:.1f}–{w1:.1f} nm   {np.nanmean(d_band):10.4e}  "
          f"{np.nanmean(c_band):10.4e}  {np.nanmedian(r_band):7.4f}")

# ── 픽셀별 C/D 평균 (전체 bins) ──────────────────────────────────────────────
px_ratio_all = np.where(np.abs(doasis_cmp) > 1e-10, caesar_cmp / doasis_cmp, np.nan)
px_cd_mean   = np.nanmean(px_ratio_all, axis=0)
print(f"\n[픽셀별 C/D]  min={np.nanmin(px_cd_mean):.4f}  max={np.nanmax(px_cd_mean):.4f}"
      f"  mean={np.nanmean(px_cd_mean):.4f}")

# ── 분위수 진단 ─────────────────────────────────────────────────────────────
valid_r = ratio[np.isfinite(ratio)]
print(f"\n[C/D 분위수]  10%={np.percentile(valid_r,10):.4f}  25%={np.percentile(valid_r,25):.4f}"
      f"  50%={np.percentile(valid_r,50):.4f}  75%={np.percentile(valid_r,75):.4f}"
      f"  90%={np.percentile(valid_r,90):.4f}")

# ─── Figure 1: 타임시리즈 + C/D + 파일 경계 ─────────────────────────────────
fig, axes = plt.subplots(3, 1, figsize=(16, 11), sharex=True)

# 파일 경계 계산
file_boundaries = []
prev = file_labels[0]
for k, fl in enumerate(file_labels):
    if fl != prev:
        file_boundaries.append((k, fl))
        prev = fl

ax = axes[0]
ax.plot(doasis_ts,  'b-', lw=1.0, label='DOASIS')
ax.plot(caesar_ts,  'r-', lw=1.0, label='CAESAR')
for kb, fl in file_boundaries:
    ax.axvline(kb, color='gray', lw=0.6, ls='--', alpha=0.6)
ax.set_ylabel('alpha (cm⁻¹)')
ax.set_title('DOASIS vs CAESAR — fit-window mean (2025-06-10)')
ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

ax = axes[1]
ax.plot(diff, 'k-', lw=0.8)
ax.axhline(0, color='gray', lw=0.5)
for kb, fl in file_boundaries:
    ax.axvline(kb, color='gray', lw=0.6, ls='--', alpha=0.6)
ax.set_ylabel('C − D (cm⁻¹)')
ax.set_title('Difference')
ax.grid(True, alpha=0.3)

ax = axes[2]
ax.plot(ratio, 'g-', lw=0.8, label='C/D per bin')
ax.axhline(1, color='gray', lw=0.8, ls='--')
ax.axhline(float(np.nanmedian(ratio)), color='orange', lw=1.0, ls=':', label=f'median={np.nanmedian(ratio):.4f}')
for kb, fl in file_boundaries:
    ax.axvline(kb, color='gray', lw=0.6, ls='--', alpha=0.6)
    ax.text(kb, ax.get_ylim()[0] if ax.get_ylim()[0] > -5 else 0.5, fl, fontsize=6, rotation=90, va='bottom', color='gray')
ax.set_ylabel('C/D')
ax.set_xlabel('bin index')
ax.set_title('Ratio (CAESAR/DOASIS)')
ax.set_ylim(0, 2); ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)

plt.tight_layout()
out1 = os.path.join(OUT_DIR, 'compare_timeseries.png')
plt.savefig(out1, dpi=150)
plt.close()
print(f"\n저장: {out1}")

# ── Figure 2: 픽셀별 C/D 평균 스펙트럼 ──────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(14, 8))

ax = axes[0]
ax.plot(wave_nm, np.nanmean(doasis_cmp, axis=0), 'b-', lw=1.0, label='DOASIS mean')
ax.plot(wave_nm, np.nanmean(caesar_cmp, axis=0), 'r-', lw=1.0, label='CAESAR mean')
ax.set_ylabel('alpha (cm⁻¹)')
ax.set_title('Spectral mean — all bins')
ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

ax = axes[1]
ax.plot(wave_nm, px_cd_mean, 'g-', lw=1.0)
ax.axhline(1.0, color='k', lw=0.8, ls='--')
ax.axhline(float(np.nanmean(px_cd_mean)), color='orange', lw=1.0, ls=':', label=f'mean={np.nanmean(px_cd_mean):.4f}')
ax.set_xlabel('wavelength (nm)')
ax.set_ylabel('C/D')
ax.set_title('Per-pixel C/D mean (averaged over all bins)')
ax.set_ylim(0, 2); ax.legend(fontsize=9)
ax.grid(True, alpha=0.3)

plt.tight_layout()
out4 = os.path.join(OUT_DIR, 'compare_pixel_cd.png')
plt.savefig(out4, dpi=150)
plt.close()
print(f"저장: {out4}")

# ── Figure 3: 파일별 C/D bar chart ───────────────────────────────────────────
fl_names = list(file_cd_medians.keys())
fl_vals  = [file_cd_medians[k] for k in fl_names]
fig, ax = plt.subplots(figsize=(12, 5))
colors = ['tomato' if v < 0.95 or v > 1.05 else 'steelblue' for v in fl_vals]
ax.bar(fl_names, fl_vals, color=colors, alpha=0.85)
ax.axhline(1.0, color='k', lw=0.8, ls='--')
ax.axhline(float(np.nanmedian(ratio)), color='orange', lw=1.0, ls=':', label=f'global median={np.nanmedian(ratio):.4f}')
ax.set_xlabel('raw file')
ax.set_ylabel('C/D median')
ax.set_title('Per-file C/D ratio (CAESAR/DOASIS)')
ax.set_ylim(0, 2); ax.legend()
ax.grid(True, alpha=0.3, axis='y')
plt.tight_layout()
out5 = os.path.join(OUT_DIR, 'compare_per_file_cd.png')
plt.savefig(out5, dpi=150)
plt.close()
print(f"저장: {out5}")

# ── Figure 4: 스펙트럼 샘플 오버레이 ────────────────────────────────────────
pix_ax = np.arange(PIXEL_MIN, PIXEL_MAX)
sample_idxs = np.linspace(0, n_cmp-1, 10, dtype=int)
fig, axes_grid = plt.subplots(5, 2, figsize=(14, 14))
axes_grid = axes_grid.flatten()
for k, idx in enumerate(sample_idxs):
    ax = axes_grid[k]
    ax.plot(wave_nm, doasis_cmp[idx], 'b-', lw=1.0, label='DOASIS')
    ax.plot(wave_nm, caesar_cmp[idx], 'r-', lw=1.0, label='CAESAR')
    cd = float(np.nanmedian(caesar_cmp[idx] / np.where(np.abs(doasis_cmp[idx]) > 1e-10, doasis_cmp[idx], np.nan)))
    ax.set_title(f'bin {idx}  (file {file_labels[idx]})  C/D={cd:.3f}', fontsize=9)
    ax.set_xlabel('nm'); ax.set_ylabel('alpha')
    ax.legend(fontsize=7); ax.grid(True, alpha=0.3)
plt.suptitle('Spectral overlay — DOASIS vs CAESAR (sample bins)', fontsize=11)
plt.tight_layout()
out2 = os.path.join(OUT_DIR, 'compare_spectra.png')
plt.savefig(out2, dpi=150)
plt.close()
print(f"저장: {out2}")

# ── Figure 5: scatter ─────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(6, 6))
lim = max(np.nanmax(np.abs(doasis_ts)), np.nanmax(np.abs(caesar_ts))) * 1.1
sc  = ax.scatter(doasis_ts, caesar_ts, s=5, alpha=0.5,
                 c=np.arange(n_cmp), cmap='viridis')
ax.plot([-lim, lim], [-lim, lim], 'k--', lw=0.8, label='1:1')
ax.plot([-lim, lim], [-lim*np.nanmedian(ratio), lim*np.nanmedian(ratio)],
        'r--', lw=0.8, label=f'C/D={np.nanmedian(ratio):.4f}')
plt.colorbar(sc, ax=ax, label='bin index')
ax.set_xlabel('DOASIS alpha (cm⁻¹)')
ax.set_ylabel('CAESAR alpha (cm⁻¹)')
ax.set_title('DOASIS vs CAESAR scatter')
ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
ax.legend(); ax.grid(True, alpha=0.3)
plt.tight_layout()
out3 = os.path.join(OUT_DIR, 'compare_scatter.png')
plt.savefig(out3, dpi=150)
plt.close()
print(f"저장: {out3}")

print("\n[완료]")
