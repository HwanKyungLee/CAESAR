"""NIER 제출용 ANs 농도 시계열 (CAESAR Yeosu 2026)
=====================================================
입력 : Output/figure/ANs/alt_ch2minusch1/GIST_CAESAR_ANs_5min_KST_20260518_20260710_ch2minusch1.csv
       (대칭 재핏 444.1-461.9nm/P4 기반, 5분평균, KST, 음수 유지)

박사님 그림 규약 (plot-conventions-doctor-2026-06):
  · x = KST, 날짜 major(%m/%d) + 6/12/18시 minor, 양끝 tight
  · 데이터 공백 = 마커만 (선 연결 금지)
  · 종색 통일: ANs = #d62728 (시계열 ↔ diurnal 동일)
  · ylabel 크게, 여백 최소, 레전드 크기조절
  · 야간 음영 19:40~05:30 (54일 시계열엔 시각적 노이즈 → diurnal 패널에만)

핸드오프 §5 / filtering-philosophy ①:
  · raw(ch2-ch1)와 보정(ch2-g*ch1) 둘 다 표시 — 가공본만 내지 않는다
  · low_light 는 flag 로 표시만, 제거하지 않는다 (rug)
  · 정량값이 아니라 상한값임을 그림 위에 명시
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

SRC = r"C:\Doasis_Work\Output\figure\ANs\alt_ch2minusch1\GIST_CAESAR_ANs_5min_KST_20260518_20260710_ch2minusch1.csv"
OUT_DIR = r"C:\Doasis_Work\Output\figure\ANs\alt_ch2minusch1"
STEM = "GIST_CAESAR_ANs_5min_KST_20260518_20260710_ch2minusch1"

# ── 스타일 (weekly_figs/plot_caesar_weekly.py 와 동일) ────────────────────────
ANS_COLOR = "#d62728"      # 종색: ANs = 빨강
RAW_COLOR = "0.62"         # raw(미보정) 회색
MEAN_COLOR = "k"
NIGHT_COLOR, NIGHT_ALPHA = (0.85, 0.85, 0.85), 0.4
LABEL_FS, TICK_FS, LEG_FS = 14, 11, 9

# 실제 광학/장비 사건만 표시. A0/A1 경계(5/27)는 HK 온도 인공물이라 뺀다(핸드오프 §1-7).
EVENTS = [
    ("2026-06-06 01:00", "06-05 filter\nrefit (ch2)"),
    ("2026-06-14 01:00", "06-14 LED2\nadjust"),
    ("2026-06-23 01:00", "06-23\n(cause TBD)"),
]
# epoch 경계 (핸드오프 §2-5) — epoch median 패널용
EPOCHS = [
    ("A0", None, "2026-05-27 01:00"),
    ("A1", "2026-05-27 01:00", "2026-06-06 01:00"),
    ("B", "2026-06-06 01:00", "2026-06-14 01:00"),
    ("C1", "2026-06-14 01:00", "2026-06-23 01:00"),
    ("C2", "2026-06-23 01:00", None),
]


def load() -> pd.DataFrame:
    df = pd.read_csv(SRC, comment="#")
    df.index = pd.to_datetime(df["datetime_KST"])
    df = df.sort_index()
    for c in ("ANs_ppb", "ANs_raw_ppb", "sys_unc_ppb", "NO2_PNs_cell", "NO2_ANs_cell"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _daily_xaxis(ax, t0, t1, label=True):
    """날짜 major + 6/12/18시 minor. x 양끝 tight."""
    ax.set_xlim(t0, t1)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_minor_locator(mdates.DayLocator(interval=1))
    ax.tick_params(axis="x", which="major", length=6, labelsize=TICK_FS)
    ax.tick_params(axis="x", which="minor", length=3)
    if label:
        ax.set_xlabel("Time [KST]", fontsize=LABEL_FS - 1)


def _shade_night_hours(ax):
    """diurnal 패널용 야간 음영 (19:40~05:30 KST)."""
    ax.axvspan(0, 5.5, color=NIGHT_COLOR, alpha=NIGHT_ALPHA, lw=0, zorder=0)
    ax.axvspan(19 + 40 / 60, 24, color=NIGHT_COLOR, alpha=NIGHT_ALPHA, lw=0, zorder=0)


def draw_timeseries(ax, df):
    t0, t1 = df.index[0], df.index[-1]
    low = df["QC_flag"].eq("low_light").to_numpy()

    # 계통불확도 밴드 (채널 이득 변동에서 온 겉보기 ANs)
    ax.fill_between(df.index, -df["sys_unc_ppb"], df["sys_unc_ppb"],
                    color=ANS_COLOR, alpha=0.13, lw=0, zorder=1)
    ax.axhline(0, color="k", lw=0.8, zorder=2)

    # 데이터 공백이 보이게 마커만 (선 연결 금지)
    ax.plot(df.index, df["ANs_raw_ppb"], ".", ms=1.6, color=RAW_COLOR,
            alpha=0.65, zorder=3, rasterized=True)
    ax.plot(df.index, df["ANs_ppb"], ".", ms=1.8, color=ANS_COLOR,
            alpha=0.75, zorder=4, rasterized=True)

    # 일 median (읽기 보조) — 결측일은 자동으로 NaN → 마커만
    dmed = df["ANs_ppb"].resample("1D").median()
    dcnt = df["ANs_ppb"].resample("1D").count()
    dmed = dmed.where(dcnt >= 50)
    ax.plot(dmed.index + pd.Timedelta(hours=12), dmed, "-o", color="#7f1214",
            ms=4, lw=1.4, zorder=6, mec="w", mew=0.6)

    # 사건 경계
    ymin, ymax = -0.9, 0.9
    for ts, lab in EVENTS:
        x = pd.Timestamp(ts)
        ax.axvline(x, color="0.35", ls="--", lw=1.0, zorder=5)
        ax.text(x + pd.Timedelta(hours=10), ymax * 0.60, lab, fontsize=8.5,
                color="0.25", va="top", ha="left", linespacing=1.15)

    # low_light rug (제거 안 함, 표시만)
    if low.any():
        ax.plot(df.index[low], np.full(low.sum(), ymin * 0.965), "|",
                color="#1f77b4", ms=4, mew=0.7, alpha=0.5, zorder=3,
                rasterized=True)

    # 축 밖으로 나간 점은 숨기지 말고 개수를 밝힌다 (filtering-philosophy ①/②)
    off_raw = int((df["ANs_raw_ppb"] < ymin).sum() + (df["ANs_raw_ppb"] > ymax).sum())
    off_cor = int((df["ANs_ppb"] < ymin).sum() + (df["ANs_ppb"] > ymax).sum())
    n = len(df)
    ax.text(0.995, 0.975,
            f"off-scale (not removed):  raw {off_raw:,} ({off_raw/n:.1%})"
            f"   ·   corrected {off_cor:,} ({off_cor/n:.1%})",
            transform=ax.transAxes, ha="right", va="top", fontsize=8.5,
            color="0.35")

    ax.set_ylim(ymin, ymax)
    ax.set_ylabel(r"ANs [ppbv]", fontsize=LABEL_FS)
    ax.tick_params(axis="y", labelsize=TICK_FS)
    _daily_xaxis(ax, t0, t1)

    n_low = int(low.sum())
    handles = [
        Line2D([], [], ls="none", marker=".", ms=9, color=RAW_COLOR,
               label=r"raw  ch2 $-$ ch1"),
        Line2D([], [], ls="none", marker=".", ms=9, color=ANS_COLOR,
               label=r"gain-corrected  ch2 $-$ g$\cdot$ch1"),
        Line2D([], [], ls="-", marker="o", ms=4, lw=1.4, color="#7f1214",
               label="daily median"),
        Patch(facecolor=ANS_COLOR, alpha=0.13,
              label=r"systematic 1$\sigma$ (channel gain)"),
        Line2D([], [], ls="none", marker="|", ms=8, color="#1f77b4",
               label=f"low-light flag (n={n_low:,}, retained)"),
    ]
    # 데이터가 없는 위쪽 좌측에 배치(raw 저농도 꼬리를 가리지 않게)
    ax.legend(handles=handles, fontsize=LEG_FS, loc="upper left", ncol=2,
              framealpha=0.9, handletextpad=0.4, columnspacing=1.1,
              borderpad=0.4)


def draw_diurnal(ax, df):
    """시별 Median(빨강 점선+마커) + Mean(검정 선) + IQR 음영. 야간 음영."""
    _shade_night_hours(ax)
    s = df["ANs_ppb"].dropna()
    g = s.groupby(s.index.hour)
    h = np.arange(24)
    med = g.median().reindex(h).to_numpy()
    mean = g.mean().reindex(h).to_numpy()
    q25 = g.quantile(0.25).reindex(h).to_numpy()
    q75 = g.quantile(0.75).reindex(h).to_numpy()

    # 계통 1σ (시간대별 g 변동 → NO2 일주기를 타고 들어옴)
    sysu = df["sys_unc_ppb"].groupby(df.index.hour).median().reindex(h).to_numpy()
    ax.fill_between(h, -sysu, sysu, color="0.5", alpha=0.22, lw=0,
                    label=r"systematic 1$\sigma$", zorder=1)

    ax.axhline(0, color="k", lw=0.8, zorder=2)
    ax.fill_between(h, q25, q75, color=ANS_COLOR, alpha=0.20, lw=0,
                    label="IQR (25–75%)", zorder=3)
    ax.plot(h, med, "--o", color=ANS_COLOR, ms=4, lw=1.2, label="Median", zorder=5)
    ax.plot(h, mean, "-", color=MEAN_COLOR, lw=1.0, label="Mean", zorder=4)

    ax.set_ylabel(r"ANs [ppbv]", fontsize=LABEL_FS)
    ax.set_xlabel("Hour of day (KST)", fontsize=LABEL_FS - 1)
    ax.set_xlim(0, 23)
    ax.set_xticks([0, 6, 12, 18])
    ax.set_ylim(-0.42, 0.42)
    ax.tick_params(labelsize=TICK_FS)
    ax.legend(fontsize=LEG_FS - 1, loc="upper right", framealpha=0.8,
              handletextpad=0.5)


def draw_epochs(ax, df):
    """구간별 median ± 계통. 절대 스케일이 미정임을 밴드로."""
    xs, meds, errs, labs = [], [], [], []
    for i, (name, a, b) in enumerate(EPOCHS):
        sub = df.loc[slice(a, b)]
        if len(sub) < 100:
            continue
        xs.append(i)
        meds.append(sub["ANs_ppb"].median())
        errs.append(sub["sys_unc_ppb"].median())
        labs.append(f"{name}\nn={len(sub):,}")

    band = float(np.nanmedian(df["NO2_PNs_cell"])) * 0.15
    ax.axhspan(-band, band, color="0.5", alpha=0.18, lw=0, zorder=0)
    ax.axhline(0, color="k", lw=0.8, zorder=1)
    ax.errorbar(xs, meds, yerr=errs, fmt="o", color=ANS_COLOR, ms=7,
                capsize=4, lw=1.4, zorder=3)
    ax.set_xticks(xs)
    ax.set_xticklabels(labs, fontsize=TICK_FS - 2)
    ax.set_xlim(-0.6, len(xs) - 0.4)
    ax.set_ylim(-0.42, 0.42)
    ax.set_ylabel(r"ANs [ppbv]", fontsize=LABEL_FS)
    ax.tick_params(axis="y", labelsize=TICK_FS)
    ax.text(0.97, 0.95,
            f"absolute scale unknown\nto $\\pm$0.15$\\times$NO$_2$ ($\\pm${band:.2f} ppb)",
            transform=ax.transAxes, ha="right", va="top", fontsize=LEG_FS - 1,
            color="0.35")


def main():
    df = load()
    print(f"loaded {len(df):,} bins  {df.index[0]} -> {df.index[-1]}")

    fig = plt.figure(figsize=(13.5, 8.0), layout="constrained")
    fig.patch.set_facecolor("w")
    gs = fig.add_gridspec(2, 3, height_ratios=[1.45, 1.0], hspace=0.06)

    ax_ts = fig.add_subplot(gs[0, :])
    ax_di = fig.add_subplot(gs[1, :2])
    ax_ep = fig.add_subplot(gs[1, 2])

    draw_timeseries(ax_ts, df)
    draw_diurnal(ax_di, df)
    draw_epochs(ax_ep, df)

    ax_ts.set_title(
        "CAESAR Yeosu 2026 — alkyl nitrates (ANs) = NO$_2$(300 °C cell) $-$ NO$_2$(180 °C cell)\n"
        "5-min means, KST · negatives retained · "
        "signal lies within the inter-channel calibration uncertainty → "
        "report as UPPER LIMIT (ANs < ~0.1–0.2 ppb)",
        fontsize=12.5, loc="left", linespacing=1.35)

    os.makedirs(OUT_DIR, exist_ok=True)
    for ext in ("png", "pdf"):
        p = os.path.join(OUT_DIR, f"{STEM}.{ext}")
        fig.savefig(p, dpi=200)
        print("saved:", p)
    plt.close(fig)

    # 요약 통계 (보고용)
    print("\n--- summary ---")
    for name, a, b in EPOCHS:
        sub = df.loc[slice(a, b)]
        if len(sub) < 100:
            continue
        print(f"{name:3s} n={len(sub):6,}  raw med={sub['ANs_raw_ppb'].median():+.3f}"
              f"  corr med={sub['ANs_ppb'].median():+.3f}"
              f"  sysunc med={sub['sys_unc_ppb'].median():.3f}")
    print(f"ALL n={len(df):,}  raw med={df['ANs_raw_ppb'].median():+.3f}"
          f"  corr med={df['ANs_ppb'].median():+.3f}")
    print("QC:", df["QC_flag"].value_counts().to_dict())


if __name__ == "__main__":
    main()
