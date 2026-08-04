"""ANs 시계열 — 발표/제출용 간결판 (ch1 - g'*ch2 규약).

진단용 3패널(plot_ans_ch1minusch2.py)에서 다음을 덜어낸 버전:
  · raw(회색) 오버레이 제거      → 보정본만
  · off-scale 텍스트·epoch 패널 제거
  · 5분 점은 옅은 배경, 일 median 을 주역으로
raw·진단 정보는 _diagnostic 파일에 그대로 남아 있다(가공본만 내지 않는다 원칙).
"""
from __future__ import annotations
import os
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

SRC = r'C:\Doasis_Work\Output\figure\ANs\GIST_CAESAR_ANs_5min_KST_20260518_20260710_ch1minusch2.csv'
OUT = r'C:\Doasis_Work\Output\figure\ANs\GIST_CAESAR_ANs_5min_KST_20260518_20260710_ch1minusch2.png'

ANS = "#d62728"
NIGHT = (0.85, 0.85, 0.85)
LABEL_FS, TICK_FS, LEG_FS = 14, 11, 9
EVENTS = [("2026-06-06 01:00", "06-05\nfilter"), ("2026-06-14 01:00", "06-14\nLED2"), ("2026-06-23 01:00", "06-23\n(TBD)")]

df = pd.read_csv(SRC, comment='#')
df.index = pd.to_datetime(df['datetime_KST']); df = df.sort_index()
for c in ('ANs_ppb', 'sys_unc_ppb'):
    df[c] = pd.to_numeric(df[c], errors='coerce')

fig, (ax, axd) = plt.subplots(1, 2, figsize=(13.2, 4.3),
                              gridspec_kw={'width_ratios': [2.7, 1]}, layout='constrained')
fig.patch.set_facecolor('w')
YLO, YHI = -0.35, 0.55

# ── 시계열 ──────────────────────────────────────────────────────────────────
ax.fill_between(df.index, -df.sys_unc_ppb, df.sys_unc_ppb, color='0.55',
                alpha=0.16, lw=0, zorder=1)
ax.axhline(0, color='k', lw=0.9, zorder=2)
ax.plot(df.index, df.ANs_ppb, '.', ms=1.1, color=ANS, alpha=0.16, zorder=3, rasterized=True)

dm = df.ANs_ppb.resample('1D').median()
dm = dm.where(df.ANs_ppb.resample('1D').count() >= 50)
ax.plot(dm.index + pd.Timedelta(hours=12), dm, '-o', color=ANS, ms=4.5, lw=1.8,
        mec='w', mew=0.7, zorder=6)

for ts, lab in EVENTS:
    x = pd.Timestamp(ts)
    ax.axvline(x, color='0.55', ls='--', lw=0.9, zorder=4)
    ax.text(x + pd.Timedelta(hours=6), YHI * 0.97, lab, fontsize=8, color='0.45',
            va='top', ha='left', linespacing=1.15)

ax.set_ylim(YLO, YHI)
ax.set_ylabel('ANs [ppbv]', fontsize=LABEL_FS)
ax.set_xlim(df.index[0], df.index[-1])
ax.xaxis.set_major_locator(mdates.DayLocator(interval=7))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
ax.xaxis.set_minor_locator(mdates.DayLocator(interval=1))
ax.tick_params(axis='x', which='major', length=6, labelsize=TICK_FS)
ax.tick_params(axis='x', which='minor', length=3)
ax.tick_params(axis='y', labelsize=TICK_FS)
ax.set_xlabel('Time [KST]', fontsize=LABEL_FS - 1)
ax.legend(handles=[
    Line2D([], [], ls='-', marker='o', ms=4.5, lw=1.8, color=ANS, label='daily median'),
    Line2D([], [], ls='none', marker='.', ms=7, color=ANS, alpha=0.4, label='5-min'),
    Patch(facecolor='0.55', alpha=0.16, label=r'systematic 1$\sigma$'),
], fontsize=LEG_FS, loc='lower left', ncol=3, framealpha=0.85,
    handletextpad=0.4, columnspacing=1.2)

# ── diurnal ────────────────────────────────────────────────────────────────
axd.axvspan(0, 5.5, color=NIGHT, alpha=0.4, lw=0, zorder=0)
axd.axvspan(19 + 40 / 60, 24, color=NIGHT, alpha=0.4, lw=0, zorder=0)
s = df.ANs_ppb.dropna(); g = s.groupby(s.index.hour); h = np.arange(24)
su = df.sys_unc_ppb.groupby(df.index.hour).median().reindex(h).to_numpy()
axd.fill_between(h, -su, su, color='0.55', alpha=0.20, lw=0, zorder=1,
                 label=r'systematic 1$\sigma$')
axd.axhline(0, color='k', lw=0.9, zorder=2)
axd.fill_between(h, g.quantile(.25).reindex(h), g.quantile(.75).reindex(h),
                 color=ANS, alpha=0.20, lw=0, zorder=3, label='IQR')
axd.plot(h, g.median().reindex(h), '--o', color=ANS, ms=4.5, lw=1.5, zorder=5, label='Median')
axd.set_xlim(0, 23); axd.set_xticks([0, 6, 12, 18]); axd.set_ylim(-0.22, 0.28)
axd.set_xlabel('Hour of day (KST)', fontsize=LABEL_FS - 1)
axd.set_ylabel('ANs [ppbv]', fontsize=LABEL_FS)
axd.tick_params(labelsize=TICK_FS)
axd.legend(fontsize=LEG_FS - 1, loc='upper left', framealpha=0.85, handletextpad=0.5)

ax.set_title("CAESAR Yeosu 2026 — alkyl nitrates (ANs), 5-min means, KST\n"
             r"upper limit only: signal $<$ inter-channel calibration uncertainty"
             "  ·  sign convention (ch1$-$ch2) unverified",
             fontsize=11.5, loc='left', linespacing=1.35)

fig.savefig(OUT, dpi=200)
fig.savefig(OUT.replace('.png', '.pdf'))
print('saved:', OUT)
print(f"daily median 범위 {dm.min():+.3f} ~ {dm.max():+.3f} ppb, 전체 median {df.ANs_ppb.median():+.3f}")
