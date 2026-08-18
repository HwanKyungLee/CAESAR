"""ANs = ch1 - g'*ch2 (뒤집기 규약) 산출물 생성 — CSV + 시계열 그림.

⚠️ 규약 주의
  현행 문서(핸드오프 §1-2)는 ch1=PNs(180C) / ch2=ANs(300C) → ANs = ch2 - ch1 이다.
  이 스크립트는 그 반대(ch1=300C 가정)로 계산한다. 사용자 요청(2026-08-01).
  두 결과는 corr(flip, -cur) = 0.9964 로 부호만 다른 같은 시계열이므로,
  어느 쪽이 맞는지는 데이터가 아니라 현장 배관이 정한다.
"""
import os
import numpy as np, pandas as pd
from scipy.stats import theilslopes
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

SRC = r'C:\Doasis_Work\Output\figure\ANs\alt_ch2minusch1\GIST_CAESAR_ANs_5min_KST_20260518_20260710_ch2minusch1.csv'
OUT_DIR = r'C:\Doasis_Work\Output\figure\ANs'
STEM = 'GIST_CAESAR_ANs_5min_KST_20260518_20260710_ch1minusch2'

ANS_COLOR, RAW_COLOR, MEAN_COLOR = "#d62728", "0.62", "k"
NIGHT_COLOR, NIGHT_ALPHA = (0.85, 0.85, 0.85), 0.4
LABEL_FS, TICK_FS, LEG_FS = 14, 11, 9
EVENTS = [("2026-06-06 01:00", "06-05 filter\nrefit (ch2)"),
          ("2026-06-14 01:00", "06-14 LED2\nadjust"),
          ("2026-06-21 22:00", "06-21 Short Pass\nFilter test")]
EP = [('A0', None, '2026-05-27 19:00'), ('A1', '2026-05-27 19:00', '2026-06-06 01:00'),
      ('B', '2026-06-06 01:00', '2026-06-14 01:00'), ('C1', '2026-06-14 01:00', '2026-06-21 22:00'),
      ('C2', '2026-06-21 22:00', None)]


def build():
    df = pd.read_csv(SRC, comment='#')
    df.index = pd.to_datetime(df['datetime_KST']); df = df.sort_index()
    for c in ('NO2_PNs_cell', 'NO2_ANs_cell', 'sys_unc_ppb'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    d = df.dropna(subset=['NO2_PNs_cell', 'NO2_ANs_cell']).copy()
    # 뒤집기 규약: ch1 을 300C(ANs) 셀로 본다
    d['ch1'] = d.NO2_PNs_cell
    d['ch2'] = d.NO2_ANs_cell
    d['ANs_raw_ppb'] = d.ch1 - d.ch2

    rng = np.random.default_rng(0)
    d['ANs_ppb'] = np.nan; d['epoch'] = ''
    gains = {}
    for name, a, b in EP:
        m = (d.index >= (pd.Timestamp(a) if a else d.index[0])) & \
            (d.index < (pd.Timestamp(b) if b else d.index[-1] + pd.Timedelta('1s')))
        s = d.loc[m]
        idx = rng.choice(len(s), min(4000, len(s)), replace=False)
        g, a0, *_ = theilslopes(s.ch1.to_numpy()[idx], s.ch2.to_numpy()[idx])
        d.loc[m, 'ANs_ppb'] = s.ch1 - g * s.ch2
        d.loc[m, 'epoch'] = name
        gains[name] = (g, a0)
    return d, gains


def write_csv(d, gains, path):
    gtxt = '  '.join(f'{k}={v[0]:.4f}' for k, v in gains.items())
    hdr = [
        "# CAESAR Yeosu 2026 - alkyl nitrates (ANs), thermal-dissociation channel difference",
        "# PI: Kyunghwan Lee   gh548080@gist.ac.kr   Institution: GIST",
        "# Time: KST (= recorded + 9 h).  Averaging: 5 min.  Negatives retained (not clipped).",
        "# Retrieval: common window 444.1-461.9 nm, poly 4, NO2 shift Limit[-10,+5], +Neg ON (both channels).",
        "#",
        "# *** CHANNEL CONVENTION - ch1 MINUS ch2 ***",
        "# This file assumes ch1 = 300 degC (ANs) cell and ch2 = 180 degC (PNs) cell.",
        "# NOTE: this is the OPPOSITE of the assignment documented in the handoff note",
        "#   (wiring log 'PNs roi1 / ANs roi2', code column map, measured cell pressures",
        "#    ch1 952 mbar vs PNs annotation ~965 / ch2 910 vs ANs annotation ~915).",
        "# The two conventions give the SAME series with opposite sign:",
        "#   corr(ch1-g*ch2, -(ch2-g*ch1)) = 0.9964.  The data cannot decide the sign;",
        "#   only physical inspection of the cell plumbing can.  UNRESOLVED as of 2026-08-01.",
        "#",
        "# ANs_raw_ppb = ch1 - ch2                    (no channel-gain correction)",
        f"# ANs_ppb     = ch1 - g*ch2   epoch Theil-Sen g:  {gtxt}",
        "# sys_unc_ppb = 1-sigma systematic from inter-channel gain variability (0.04 x NO2).",
        "#",
        "# *** CAUTION ***",
        "# Inter-channel gain is known only to ~15% epoch-to-epoch = ~0.30 ppb apparent ANs",
        "# at typical NO2, which exceeds the retrieved signal (median +0.076 ppb).",
        "# Diurnal amplitude (0.060 ppb) is smaller than the systematic (0.081 ppb), and peaks",
        "# at 09h rather than the 13-16h expected for photochemical alkyl nitrates.",
        "# Random detection limit (0.019 ppb at 5 min) is NOT the limiting factor; calibration is.",
        "# => UPPER LIMIT (ANs < ~0.1-0.2 ppb), not a quantitative time series.",
        "# Absolute quantification requires NO2 cylinder injection on a common inlet.",
        "#",
    ]
    out = d[['ANs_ppb', 'ANs_raw_ppb', 'sys_unc_ppb', 'ch1', 'ch2', 'epoch', 'n_scans', 'QC_flag']].copy()
    out.columns = ['ANs_ppb', 'ANs_raw_ppb', 'sys_unc_ppb', 'NO2_ch1_300C', 'NO2_ch2_180C',
                   'epoch', 'n_scans', 'QC_flag']
    out.insert(0, 'datetime_KST', d.index.strftime('%Y-%m-%d %H:%M:%S'))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(hdr) + '\n')
        out.to_csv(f, index=False, float_format='%.5f')
    print('saved:', path, f'({len(out):,} rows)')


def _xaxis(ax, t0, t1):
    ax.set_xlim(t0, t1)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_minor_locator(mdates.DayLocator(interval=1))
    ax.tick_params(axis="x", which="major", length=6, labelsize=TICK_FS)
    ax.tick_params(axis="x", which="minor", length=3)
    ax.set_xlabel("Time [KST]", fontsize=LABEL_FS - 1)


def figure(d, path_stem):
    fig = plt.figure(figsize=(13.5, 8.0), layout="constrained")
    fig.patch.set_facecolor("w")
    gs = fig.add_gridspec(2, 3, height_ratios=[1.45, 1.0])
    ax, axd, axe = fig.add_subplot(gs[0, :]), fig.add_subplot(gs[1, :2]), fig.add_subplot(gs[1, 2])
    ymin, ymax = -0.5, 0.9
    low = d.QC_flag.eq('low_light').to_numpy()

    ax.fill_between(d.index, -d.sys_unc_ppb, d.sys_unc_ppb, color=ANS_COLOR,
                    alpha=0.13, lw=0, zorder=1)
    ax.axhline(0, color='k', lw=0.8, zorder=2)
    ax.plot(d.index, d.ANs_raw_ppb, '.', ms=1.6, color=RAW_COLOR, alpha=0.65,
            zorder=3, rasterized=True)
    ax.plot(d.index, d.ANs_ppb, '.', ms=1.8, color=ANS_COLOR, alpha=0.75,
            zorder=4, rasterized=True)
    dm = d.ANs_ppb.resample('1D').median().where(d.ANs_ppb.resample('1D').count() >= 50)
    ax.plot(dm.index + pd.Timedelta(hours=12), dm, '-o', color='#7f1214', ms=4,
            lw=1.4, mec='w', mew=0.6, zorder=6)
    for ts, lab in EVENTS:
        x = pd.Timestamp(ts)
        ax.axvline(x, color='0.35', ls='--', lw=1.0, zorder=5)
        ax.text(x + pd.Timedelta(hours=10), ymax * 0.60, lab, fontsize=8.5,
                color='0.25', va='top', ha='left', linespacing=1.15)
    if low.any():
        ax.plot(d.index[low], np.full(low.sum(), ymin * 0.94), '|', color='#1f77b4',
                ms=4, mew=0.7, alpha=0.5, zorder=3, rasterized=True)
    n = len(d)
    o_r = int((d.ANs_raw_ppb < ymin).sum() + (d.ANs_raw_ppb > ymax).sum())
    o_c = int((d.ANs_ppb < ymin).sum() + (d.ANs_ppb > ymax).sum())
    ax.text(0.995, 0.975, f"off-scale (not removed):  raw {o_r:,} ({o_r/n:.1%})"
            f"   ·   corrected {o_c:,} ({o_c/n:.1%})", transform=ax.transAxes,
            ha='right', va='top', fontsize=8.5, color='0.35')
    ax.set_ylim(ymin, ymax)
    ax.set_ylabel(r"ANs [ppbv]", fontsize=LABEL_FS)
    ax.tick_params(axis='y', labelsize=TICK_FS)
    _xaxis(ax, d.index[0], d.index[-1])
    ax.legend(handles=[
        Line2D([], [], ls='none', marker='.', ms=9, color=RAW_COLOR, label=r"raw  ch1 $-$ ch2"),
        Line2D([], [], ls='none', marker='.', ms=9, color=ANS_COLOR,
               label=r"gain-corrected  ch1 $-$ g$'\cdot$ch2"),
        Line2D([], [], ls='-', marker='o', ms=4, lw=1.4, color='#7f1214', label="daily median"),
        Patch(facecolor=ANS_COLOR, alpha=0.13, label=r"systematic 1$\sigma$ (channel gain)"),
        Line2D([], [], ls='none', marker='|', ms=8, color='#1f77b4',
               label=f"low-light flag (n={int(low.sum()):,}, retained)"),
    ], fontsize=LEG_FS, loc='upper left', ncol=2, framealpha=0.9,
        handletextpad=0.4, columnspacing=1.1, borderpad=0.4)

    # diurnal
    axd.axvspan(0, 5.5, color=NIGHT_COLOR, alpha=NIGHT_ALPHA, lw=0, zorder=0)
    axd.axvspan(19 + 40 / 60, 24, color=NIGHT_COLOR, alpha=NIGHT_ALPHA, lw=0, zorder=0)
    s = d.ANs_ppb.dropna(); g = s.groupby(s.index.hour); h = np.arange(24)
    med, mean = g.median().reindex(h).to_numpy(), g.mean().reindex(h).to_numpy()
    q25, q75 = g.quantile(.25).reindex(h).to_numpy(), g.quantile(.75).reindex(h).to_numpy()
    su = d.sys_unc_ppb.groupby(d.index.hour).median().reindex(h).to_numpy()
    axd.fill_between(h, -su, su, color='0.5', alpha=0.22, lw=0, label=r"systematic 1$\sigma$", zorder=1)
    axd.axhline(0, color='k', lw=0.8, zorder=2)
    axd.fill_between(h, q25, q75, color=ANS_COLOR, alpha=0.20, lw=0, label="IQR (25–75%)", zorder=3)
    axd.plot(h, med, '--o', color=ANS_COLOR, ms=4, lw=1.2, label="Median", zorder=5)
    axd.plot(h, mean, '-', color=MEAN_COLOR, lw=1.0, label="Mean", zorder=4)
    axd.axvspan(13, 16, color='#2ca02c', alpha=0.10, lw=0, zorder=0)
    axd.text(14.5, -0.28, "expected\nphotochem.\nmaximum", fontsize=7.5, color='#2ca02c',
             ha='center', va='bottom', linespacing=1.15)
    axd.set_ylabel(r"ANs [ppbv]", fontsize=LABEL_FS)
    axd.set_xlabel("Hour of day (KST)", fontsize=LABEL_FS - 1)
    axd.set_xlim(0, 23); axd.set_xticks([0, 6, 12, 18]); axd.set_ylim(-0.32, 0.32)
    axd.tick_params(labelsize=TICK_FS)
    axd.legend(fontsize=LEG_FS - 1, loc='upper right', framealpha=0.8, handletextpad=0.5)

    # epoch medians
    xs, ms_, es, labs = [], [], [], []
    for i, (name, a, b) in enumerate(EP):
        sub = d.loc[slice(a, b)]
        if len(sub) < 100:
            continue
        xs.append(i); ms_.append(sub.ANs_ppb.median()); es.append(sub.sys_unc_ppb.median())
        labs.append(f"{name}\nn={len(sub):,}")
    band = float(np.nanmedian(d.ch1)) * 0.15
    axe.axhspan(-band, band, color='0.5', alpha=0.18, lw=0, zorder=0)
    axe.axhline(0, color='k', lw=0.8, zorder=1)
    axe.errorbar(xs, ms_, yerr=es, fmt='o', color=ANS_COLOR, ms=7, capsize=4, lw=1.4, zorder=3)
    axe.set_xticks(xs); axe.set_xticklabels(labs, fontsize=TICK_FS - 2)
    axe.set_xlim(-0.6, len(xs) - 0.4); axe.set_ylim(-0.32, 0.32)
    axe.set_ylabel(r"ANs [ppbv]", fontsize=LABEL_FS)
    axe.tick_params(axis='y', labelsize=TICK_FS)
    axe.text(0.97, 0.95, f"absolute scale unknown\nto $\\pm$0.15$\\times$NO$_2$ ($\\pm${band:.2f} ppb)",
             transform=axe.transAxes, ha='right', va='top', fontsize=LEG_FS - 1, color='0.35')

    ax.set_title(
        "CAESAR Yeosu 2026 — alkyl nitrates (ANs), convention  ch1 $-$ ch2   "
        "(5-min means, KST · negatives retained)\n"
        r"⚠ sign convention UNVERIFIED — exact mirror of ch2$-$ch1 (corr 0.996); "
        "signal lies within the calibration uncertainty → UPPER LIMIT",
        fontsize=12, loc='left', linespacing=1.4)

    os.makedirs(os.path.dirname(path_stem), exist_ok=True)
    for ext in ('png', 'pdf'):
        fig.savefig(f"{path_stem}.{ext}", dpi=200)
        print('saved:', f"{path_stem}.{ext}")
    plt.close(fig)


if __name__ == '__main__':
    d, gains = build()
    os.makedirs(OUT_DIR, exist_ok=True)
    write_csv(d, gains, os.path.join(OUT_DIR, STEM + '.csv'))
    figure(d, os.path.join(OUT_DIR, STEM))
    print('\nmedian ANs = {:+.4f} ppb   positive {:.1%}'.format(d.ANs_ppb.median(), (d.ANs_ppb > 0).mean()))
