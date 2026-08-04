"""NIER 제출 그림 — cold NO2 와 ANs 를 **동일 형식**으로 생성.

한 함수(draw)로 두 종을 그리므로 스타일이 어긋날 수 없다.
박사님 그림 규약(plot-conventions-doctor-2026-06):
  · 좌 시계열 + 우 일주기, x=KST 날짜 major + 일별 minor, 양끝 tight
  · 데이터 공백이 보이게 마커만(선 연결 금지). 파생값은 그리지 않는다
  · 종색 통일: NO2=파랑 #1f77b4 / ANs=빨강 #d62728 (시계열↔일주기 동일)
  · 일주기 = Median + IQR(25–75%) + 야간 음영 19:40~05:30
  · ylabel 크게, 여백 최소

종별 차이는 데이터 성격에서 오는 것만 둔다:
  · 계통 1σ 밴드는 그리지 않는다 — 현행 sys_unc(0.04xNO2)는 g 변동 4개 원인 중
    '일별 표준편차' 하나만 담아 총 계통예산(0.300ppb)의 1/4에 불과하다. 틀린 오차막대는
    없느니만 못하므로 제목 문구(UPPER LIMIT)와 CSV 의 ANs_unc_ppb 컬럼으로만 전달한다.
  · ANs 만 장비 사건 표시(6/5 필터·6/14 LED2·6/23) — cold 는 단일 채널이라 무관
  · cold 만 6/17 저품질 표시
"""
from __future__ import annotations
import os
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates
from matplotlib.lines import Line2D

SUB = r'C:\Doasis_Work\Output\figure\NIER_submit'
NIGHT, NIGHT_A = (0.85, 0.85, 0.85), 0.4
LABEL_FS, TICK_FS, LEG_FS = 14, 11, 9
FIGSIZE, WRATIO = (13.2, 4.3), [2.7, 1]
DPI = 300          # 제출/발표용. 200 이면 5분 점이 뭉개진다

ANS_EVENTS = [("2026-06-06", "06-05\nfilter"), ("2026-06-14", "06-14\nLED2"),
              ("2026-06-23", "06-23\n(TBD)")]


def draw(csv, col, color, ylabel, title, sub, out,
         ylim, dylim, events=(), flagname=None, day_tick=7):
    df = pd.read_csv(csv, comment='#')
    df.index = pd.to_datetime(df['datetime_KST']); df = df.sort_index()
    df[col] = pd.to_numeric(df[col], errors='coerce')
    # unphysical 로 표시한 행은 그리지 않는다(CSV 엔 그대로 있다). 산점도엔 어차피
    # y축 밖이라 안 보이지만, 빼지 않으면 일주기 median 이 최대 0.11 ppb 끌려간다.
    n_unphys = int((df['QC_flag'].astype(str) == 'unphysical').sum())
    if n_unphys:
        df = df[df['QC_flag'].astype(str) != 'unphysical']

    fig, (ax, axd) = plt.subplots(1, 2, figsize=FIGSIZE,
                                  gridspec_kw={'width_ratios': WRATIO}, layout='constrained')
    fig.patch.set_facecolor('w')
    lo, hi = ylim

    ax.axhline(0, color='k', lw=0.9, zorder=2)
    # 제출 자료(5분 평균)만 그린다. 일 median 등 파생값은 넣지 않는다 — 그림에 있는 숫자는
    # 전부 CSV 에 있는 숫자여야 한다.
    ax.plot(df.index, df[col], '.', ms=2.0, color=color, alpha=0.38, zorder=3,
            rasterized=True)
    fig.set_dpi(DPI)   # rasterized 요소가 DPI 를 따라가게

    for ts, lab in events:
        x = pd.Timestamp(ts)
        ax.axvline(x, color='0.55', ls='--', lw=0.9, zorder=4)
        # 레전드(상단)와 겹치지 않게 하단에 배치
        ax.text(x + pd.Timedelta(hours=6), lo + 0.06 * (hi - lo), lab, fontsize=8,
                color='0.45', va='bottom', ha='left', linespacing=1.15)

    if flagname and flagname in set(df['QC_flag'].astype(str)):
        bad = df.index[df['QC_flag'].astype(str) == flagname]
        ax.axvspan(bad.min(), bad.max(), color='#d62728', alpha=0.10, lw=0, zorder=1)
        ax.text(bad.min(), hi * 0.97, ' low quality\n (flagged, kept)', fontsize=8,
                color='#a01216', va='top', ha='left', linespacing=1.15)

    off = int((df[col] < lo).sum() + (df[col] > hi).sum())
    note = f'off-scale (kept in data): {off:,} of {len(df) + n_unphys:,}'
    if n_unphys:
        note += f'   ·   {n_unphys} flagged unphysical (in CSV, not plotted)'
    if off or n_unphys:
        ax.text(0.995, 0.02, note, transform=ax.transAxes, ha='right', va='bottom',
                fontsize=8, color='0.45')

    ax.set_ylim(lo, hi)
    ax.set_ylabel(ylabel, fontsize=LABEL_FS)
    ax.set_xlim(df.index[0], df.index[-1])
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=day_tick))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    ax.xaxis.set_minor_locator(mdates.DayLocator(interval=1))
    ax.tick_params(axis='x', which='major', length=6, labelsize=TICK_FS)
    ax.tick_params(axis='x', which='minor', length=3)
    ax.tick_params(axis='y', labelsize=TICK_FS)
    ax.set_xlabel('Time [KST]', fontsize=LABEL_FS - 1)

    h = [Line2D([], [], ls='none', marker='.', ms=9, color=color, label='5-min mean')]
    ax.legend(handles=h, fontsize=LEG_FS, loc='upper left', ncol=len(h),
              framealpha=0.85, handletextpad=0.4, columnspacing=1.2)

    # ── 일주기 ─────────────────────────────────────────────────────────────
    axd.axvspan(0, 5.5, color=NIGHT, alpha=NIGHT_A, lw=0, zorder=0)
    axd.axvspan(19 + 40 / 60, 24, color=NIGHT, alpha=NIGHT_A, lw=0, zorder=0)
    s = df[col].dropna(); g = s.groupby(s.index.hour); hh = np.arange(24)
    axd.axhline(0, color='k', lw=0.9, zorder=2)
    axd.fill_between(hh, g.quantile(.25).reindex(hh), g.quantile(.75).reindex(hh),
                     color=color, alpha=0.22, lw=0, zorder=3, label='IQR (25–75%)')
    axd.plot(hh, g.median().reindex(hh), '--o', color=color, ms=4.5, lw=1.5,
             zorder=5, label='Median')
    axd.set_xlim(0, 23); axd.set_xticks([0, 6, 12, 18]); axd.set_ylim(*dylim)
    axd.set_xlabel('Hour of day (KST)', fontsize=LABEL_FS - 1)
    axd.set_ylabel(ylabel, fontsize=LABEL_FS)
    axd.tick_params(labelsize=TICK_FS)
    axd.legend(fontsize=LEG_FS - 1, loc='upper right', framealpha=0.85, handletextpad=0.5)

    ax.set_title(f"{title}\n{sub}", fontsize=11.5, loc='left', linespacing=1.35)
    fig.savefig(out, dpi=DPI)                      # 3960 x 1290 px
    fig.savefig(out.replace('.png', '.pdf'))       # 벡터(점만 래스터)
    print(f'  saved: {os.path.basename(out)}   n={len(df):,}  median={df[col].median():+.3f}'
          f'  off-scale={off}')
    plt.close(fig)


def _find(species):
    """제출 CSV 를 종별 prefix 로 찾는다. 파일명의 기간은 build_nier_submission 이
    실제 자료 범위에서 만들므로(시계 정정 등으로 바뀐다) 하드코딩하지 않는다."""
    import glob
    hits = sorted(glob.glob(os.path.join(SUB, f'GIST_CAESAR_{species}_5min_KST_*.csv')))
    if not hits:
        raise FileNotFoundError(f'{species} 제출 CSV 가 없다: {SUB}')
    if len(hits) > 1:
        raise RuntimeError(f'{species} CSV 가 여러 개다 — 옛 파일을 치워라:\n  '
                           + '\n  '.join(os.path.basename(h) for h in hits))
    return hits[0]


def main():
    print('NIER 제출 그림 (동일 형식)')
    cold_csv = _find('cold_NO2')
    draw(csv=cold_csv,
         col='NO2_ppb', color='#1f77b4', ylabel=r'NO$_2$ [ppbv]',
         title='CAESAR Yeosu 2026 — NO$_2$ (cold cavity), 5-min means, KST',
         sub='QC: Chi2 < 10  ·  negatives retained  ·  2026-06-17 flagged low quality (kept)',
         out=cold_csv.replace('.csv', '.png'),
         ylim=(-3, 22), dylim=(0, 9), flagname='low_quality', day_tick=5)

    # 장비 사건선(6/5·6/14·6/23)은 제출본에서 뺀다 — 외부 독자에겐 의미가 없고,
    # 6/14 는 |Δg|/σ = 0.8 로 통계적으로 약해 세로선이 근거 이상을 주장하게 된다.
    # epoch 경계 정보는 CSV 헤더 '# Definition:' 에 그대로 남아 있다(정보 소실 없음).
    # 내부 진단용 그림(Output/figure/ANs/*_diagnostic.png)에는 사건선이 그대로 있다.
    ans_csv = _find('ANs')
    draw(csv=ans_csv,
         col='ANs_ppb', color='#d62728', ylabel='ANs [ppbv]',
         title='CAESAR Yeosu 2026 — ANs (alkyl nitrates), 5-min means, KST',
         sub='UPPER LIMIT only: signal lies within the channel calibration uncertainty',
         out=ans_csv.replace('.csv', '.png'),
         ylim=(-0.35, 0.55), dylim=(-0.22, 0.28), day_tick=7)


if __name__ == '__main__':
    main()
