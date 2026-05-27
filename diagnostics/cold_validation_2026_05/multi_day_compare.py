"""
05-17 / 05-18 / 05-19 cold setup 멀티데이 비교.
각 일자별 알파(omr_d, Leff) + DOAS v1/v2 (NO2/CHOCHO ppb, RMS) 통계 모아서
일자간 cavity 안정성 + DOAS 일관성 평가.
"""
import os, numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# day -> (alpha_dir, doas_v1_tsv, doas_v2_tsv)
SOURCES = {
    '05-17': (r'D:\GHL\CAESAR_Pro_validation_2026_05',
              r'D:\GHL\CAESAR_Pro_validation_2026_05\doas_fit.tsv',
              r'D:\GHL\CAESAR_Pro_validation_2026_05\doas_fit_v2_17.tsv'),
    '05-18': (r'D:\GHL\multi_2026_05_18',
              r'D:\GHL\multi_2026_05_18\doas_fit.tsv',
              r'D:\GHL\CAESAR_Pro_validation_2026_05\doas_fit_v2_18.tsv'),
    '05-19': (r'D:\GHL\multi_2026_05_19',
              r'D:\GHL\multi_2026_05_19\doas_fit.tsv',
              r'D:\GHL\CAESAR_Pro_validation_2026_05\doas_fit_v2_19.tsv'),
}

OUT_DIR = r'D:\GHL\CAESAR_Pro_validation_2026_05'
PLOT_DIR = os.path.join(OUT_DIR, 'plots')
os.makedirs(PLOT_DIR, exist_ok=True)

# ─── Load ────────────────────────────────────────────────────────────────────
def load_tsv(fp):
    if not os.path.exists(fp):
        return None
    with open(fp) as f:
        header = f.readline().strip().split('\t')
    data = np.loadtxt(fp, skiprows=1, delimiter='\t')
    return header, data

stats = {}
for day, (alpha_dir, v1_fp, v2_fp) in SOURCES.items():
    s = {}
    # alpha + calib
    calib = np.load(os.path.join(alpha_dir, 'calib.npz'))
    A     = np.load(os.path.join(alpha_dir, 'alpha_caesar.npz'))
    s['omr_d_mean'] = float(calib['best_omr'].mean())
    s['leff_km']    = 1.0 / s['omr_d_mean'] * 1e-5
    s['n_za']       = int(len(calib['za_blocks']))
    s['n_he']       = int(len(calib['he_blocks']))
    s['n_bins']     = int((A['counts'] > 0).sum())
    s['alpha_mean_abs'] = float(np.abs(A['alpha'][A['counts']>0]).mean())

    # v1
    h, d = load_tsv(v1_fp)
    if d is not None:
        cols = {n: i for i, n in enumerate(h)}
        s['v1_no2_med']    = float(np.median(d[:, cols['NO2_ppb']]))
        s['v1_no2_mean']   = float(np.mean(  d[:, cols['NO2_ppb']]))
        s['v1_chocho_med'] = float(np.median(d[:, cols['CHOCHO_ppb']]))
        s['v1_rms_med']    = float(np.median(d[:, cols['rms_cm-1']]))
        s['v1_n']          = len(d)
    # v2
    h, d = load_tsv(v2_fp)
    if d is not None:
        cols = {n: i for i, n in enumerate(h)}
        s['v2_no2_med']    = float(np.median(d[:, cols['NO2_ppb']]))
        s['v2_no2_mean']   = float(np.mean(  d[:, cols['NO2_ppb']]))
        s['v2_chocho_med'] = float(np.median(d[:, cols['CHOCHO_ppb']]))
        s['v2_rms_med']    = float(np.median(d[:, cols['rms']]))
        s['v2_shift_med']  = float(np.median(d[:, cols['shift_px']]))
        s['v2_sq_med']     = float(np.median(d[:, cols['squeeze']]))
        s['v2_n']          = len(d)
    stats[day] = s

# ─── Report ──────────────────────────────────────────────────────────────────
lines = []
lines.append('=' * 90)
lines.append('Multi-day comparison: 2026-05-17 / 05-18 / 05-19 cold setup')
lines.append('=' * 90)
lines.append('')
lines.append(f'{"":>20}{"05-17":>15}{"05-18":>15}{"05-19":>15}')
def row(label, key, fmt):
    parts = [f'{label:>20}']
    for d in ['05-17','05-18','05-19']:
        v = stats[d].get(key, float('nan'))
        parts.append(format(v, fmt).rjust(15))
    return ''.join(parts)
lines.append(row('ZA blocks',         'n_za',           'd'))
lines.append(row('He blocks',         'n_he',           'd'))
lines.append(row('R-cal omr_d',       'omr_d_mean',     '.3e'))
lines.append(row('Leff (km)',         'leff_km',        '.2f'))
lines.append(row('Alpha bins',        'n_bins',         'd'))
lines.append(row('mean|alpha| (cm-1)','alpha_mean_abs', '.3e'))
lines.append('')
lines.append('-- DOAS v1 (simple lstsq, no shift/sq) ---')
lines.append(row('NO2 median (ppb)',  'v1_no2_med',     '+.3f'))
lines.append(row('NO2 mean (ppb)',    'v1_no2_mean',    '+.3f'))
lines.append(row('CHOCHO median',     'v1_chocho_med',  '+.3f'))
lines.append(row('RMS median',        'v1_rms_med',     '.3e'))
lines.append('')
lines.append('-- DOAS v2 (NO2 shift/sq, others LINKED, narrow win 430-480) ---')
lines.append(row('NO2 median (ppb)',  'v2_no2_med',     '+.3f'))
lines.append(row('NO2 mean (ppb)',    'v2_no2_mean',    '+.3f'))
lines.append(row('CHOCHO median',     'v2_chocho_med',  '+.3f'))
lines.append(row('RMS median',        'v2_rms_med',     '.3e'))
lines.append(row('shift med (px)',    'v2_shift_med',   '+.3f'))
lines.append(row('squeeze med',       'v2_sq_med',      '.6f'))
lines.append('')
lines.append('-- v2 vs v1 RMS improvement ---')
for d in ['05-17', '05-18', '05-19']:
    v1 = stats[d].get('v1_rms_med'); v2 = stats[d].get('v2_rms_med')
    if v1 and v2:
        lines.append(f'  {d}: v1={v1:.2e}  v2={v2:.2e}  ratio v1/v2 = {v1/v2:.2f}x')

report = '\n'.join(lines)
print(report)
with open(os.path.join(OUT_DIR, 'multi_day_report.txt'), 'w', encoding='utf-8') as f:
    f.write(report)
print(f'\nwrote multi_day_report.txt')

# ─── Plot: NO2 ts overlay 3 days × 2 versions ────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=False)
colors = {'05-17': 'C0', '05-18': 'C1', '05-19': 'C2'}
for ax, ver, vtsv_key in zip(axes, ['v1', 'v2'], ['v1_no2', 'v2_no2']):
    for day, (alpha_dir, v1_fp, v2_fp) in SOURCES.items():
        fp = v1_fp if ver == 'v1' else v2_fp
        if not os.path.exists(fp):
            continue
        h, d = load_tsv(fp)
        cols = {n: i for i, n in enumerate(h)}
        bins = d[:, cols['bin_idx']] if 'bin_idx' in cols else d[:, cols.get('bin', 0)]
        no2  = d[:, cols['NO2_ppb']]
        ax.plot(bins, no2, '.', ms=2, alpha=0.5, color=colors[day], label=day)
    ax.axhline(0, color='k', ls='--', lw=0.5)
    ax.set_ylabel(f'NO2 ppb ({ver})')
    ax.set_ylim(-3, 10)
    ax.grid(alpha=0.3); ax.legend()
axes[0].set_title('NO2 multi-day overlay  (v1=top, v2=bottom)')
axes[-1].set_xlabel('bin (60s)')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '14_multi_day_no2.png'), dpi=120)
plt.close(fig)
print('wrote 14_multi_day_no2.png')

# ─── Plot: omr_d (R-cal) shape across days ───────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 5))
for day, (alpha_dir, _, _) in SOURCES.items():
    calib = np.load(os.path.join(alpha_dir, 'calib.npz'))
    A = np.load(os.path.join(alpha_dir, 'alpha_caesar.npz'))
    wave = A['wave_nm']
    ax.plot(wave, calib['best_omr'], '-', lw=1, color=colors[day],
            label=f'{day} Leff={stats[day]["leff_km"]:.2f}km')
ax.set_xlabel('Wavelength (nm)')
ax.set_ylabel('omr_d (cm-1)')
ax.set_title('R-cal omr_d shape per day')
ax.set_yscale('symlog', linthresh=1e-7)
ax.legend()
ax.grid(alpha=0.3, which='both')
fig.tight_layout()
fig.savefig(os.path.join(PLOT_DIR, '15_multi_day_omr_d.png'), dpi=120)
plt.close(fig)
print('wrote 15_multi_day_omr_d.png')
