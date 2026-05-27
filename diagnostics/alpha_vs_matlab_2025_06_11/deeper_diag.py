"""
2차 진단: R-cal omr_d 모양, ZA/He/ambient 평균 스펙트럼, (I0-I)/I 분포.
1번 비교에서 CAESAR α @ 450nm ≈ +2.5e-5 cm⁻¹ LED-shaped bump이 보이는 원인 추적.
"""
import os, sys, glob, numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, HERE)
import compare_alpha as ca

wave_nm = np.load(os.path.join(HERE, 'wave_nm.npy'))

# Re-do Pass 1 quickly (it's cached in memory if recently run, but we'll rerun)
file_list = sorted(glob.glob(os.path.join(ca.RAW_DIR, ca.RAW_GLOB)))
print(f'Re-collecting {len(file_list)} files...')
za, he, amb = ca.collect_scans(file_list)
print(f'  ZA={len(za["gidx"])}  He={len(he["gidx"])}  amb={len(amb["gidx"])}')

# Block averages
za_g, za_s, za_t, za_p = ca.block_average(za['gidx'], za['spec'], za['T'], za['P'])
he_g, he_s, he_t, he_p = ca.block_average(he['gidx'], he['spec'], he['T'], he['P'])

# Mean spectra
he_mean = np.nanmean(he_s, axis=0)
za_mean = np.nanmean(za_s, axis=0)
amb_mean = np.nanmean(amb['spec'], axis=0)
amb_min = np.nanmin(amb['spec'], axis=0)

# Plot mean spectra to see LED profile
fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
ax = axes[0]
ax.plot(wave_nm, he_mean, 'b-', lw=1, label=f'He mean ({len(he_g)} blocks)')
ax.plot(wave_nm, za_mean, 'g-', lw=1, label=f'ZA mean ({len(za_g)} blocks)')
ax.plot(wave_nm, amb_mean, 'k-', lw=0.6, label=f'Ambient mean ({len(amb["gidx"])} scans)', alpha=0.7)
ax.plot(wave_nm, amb_min,  'r--', lw=0.6, label='Ambient min (dark candidate)', alpha=0.7)
ax.axhline(1500, color='orange', ls=':', label='dark=1500 (variant B,D)')
ax.set_ylabel('Intensity (counts)')
ax.set_title('Mean spectra — LED profile + dark baseline check')
ax.legend(fontsize=9)
ax.grid(alpha=0.3)

# Plot 2: ratio I_ZA/I_He (R calibration input)
ax = axes[1]
ratio = za_mean / np.where(np.abs(he_mean) > 1.0, he_mean, 1.0)
ax.plot(wave_nm, ratio, 'k-', lw=0.7)
ax.axhline(1.0, color='r', ls='--', label='ratio=1 (boundary; >1 breaks omr_d)')
ax.set_xlabel('Wavelength (nm)')
ax.set_ylabel('I_ZA / I_He')
ax.set_title('R-cal input ratio — should be <1 (cavity dimmer in ZA than He)')
ax.set_ylim(0.5, 1.5)
ax.legend(fontsize=9)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(HERE, 'plots', '06_mean_spectra.png'), dpi=120)
plt.close(fig)
print('wrote plots/06_mean_spectra.png')

# Compute omr_d per ZA block (no threshold), plot shape
alpha_ray_he = ca.get_alpha_rayleigh(wave_nm, float(np.nanmean(he_t)), float(np.nanmean(he_p)), 'helium', 'sellmeier')
i_he_s = np.where(np.abs(he_mean) > 1.0, he_mean, 1.0)
all_omr = []
for i_za, t_z, p_z in zip(za_s, za_t, za_p):
    alpha_ray_za = ca.get_alpha_rayleigh(wave_nm, float(t_z), float(p_z), 'zero_air', 'sellmeier')
    r = i_za / i_he_s
    with np.errstate(divide='ignore', invalid='ignore'):
        omr = ca.RL_FACTOR * ((r * alpha_ray_za) - alpha_ray_he) / (1.0 - r)
    all_omr.append(omr)
all_omr = np.array(all_omr)
omr_med = np.nanmedian(all_omr, axis=0)

fig, ax = plt.subplots(figsize=(12, 5))
for omr in all_omr:
    ax.plot(wave_nm, omr, '-', lw=0.3, alpha=0.3)
ax.plot(wave_nm, omr_med, 'k-', lw=1.5, label='median (used as best_omr_d)')
ax.axhline(0, color='r', ls='--', lw=0.5)
ax.set_xlabel('Wavelength (nm)')
ax.set_ylabel('omr_d  =  (1-R)/d  · RL  (cm⁻¹)')
ax.set_title(f'R calibration omr_d per ZA block — {len(all_omr)} blocks')
ax.set_ylim(-1e-4, 2e-4)
ax.legend(fontsize=9)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(HERE, 'plots', '07_omr_d_shape.png'), dpi=120)
plt.close(fig)
print('wrote plots/07_omr_d_shape.png')

# Distribution of (I0 - I_amb)/I_amb at λ=450 nm, dark=None
px_450 = int(np.argmin(np.abs(wave_nm - 450)))
# Use ZA mean as I0 (proxy — actual PCHIP gives similar values mid-day)
i0_proxy = za_mean[px_450]
ratios_450 = (i0_proxy - amb['spec'][:, px_450]) / amb['spec'][:, px_450]
fig, axes = plt.subplots(2, 1, figsize=(12, 7))
ax = axes[0]
ax.hist(ratios_450, bins=200, range=(-0.5, 0.5), color='C0', alpha=0.7)
ax.set_xlabel('(I_ZA_mean − I_amb) / I_amb  at λ=450 nm')
ax.set_ylabel('count')
ax.set_title(f'(I0 − I)/I distribution — direct contributor to alpha magnitude')
ax.grid(alpha=0.3)
ax = axes[1]
ax.plot(amb['t_sec'], ratios_450, '.', ms=1, alpha=0.4)
ax.set_xlabel('t (sec UTC)')
ax.set_ylabel('(I0−I)/I @ 450 nm')
ax.set_ylim(-0.5, 0.5)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(HERE, 'plots', '08_i0_ratio_450nm.png'), dpi=120)
plt.close(fig)
print('wrote plots/08_i0_ratio_450nm.png')

# Compute what alpha at 450nm SHOULD be from (I0-I)/I × omr_d
mean_ratio_450 = np.nanmean(ratios_450)
omr_450 = omr_med[px_450]
expected_alpha_dc = omr_450 / ca.RL_FACTOR * mean_ratio_450
print(f'\nAt λ=450 nm:')
print(f'  omr_d_median = {omr_450:.3e} cm⁻¹')
print(f'  omr_d/RL     = {omr_450/ca.RL_FACTOR:.3e} cm⁻¹')
print(f'  mean (I0-I)/I = {mean_ratio_450:+.3e}')
print(f'  expected DC alpha = omr_d/RL · ratio = {expected_alpha_dc:+.3e} cm⁻¹')
print(f'  Observed CAESAR α @ 450nm midday: ~2.5e-5 cm⁻¹ (from plot 01)')
