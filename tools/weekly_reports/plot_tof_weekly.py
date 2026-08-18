"""ToF 주간회의 그림 — MATLAB → Python 변환 (standalone, GUI 아님)
================================================================
박사님 week5_ToF.pptx 의 두 종류 그림을 재현한다.

  (A) 시계열 1장  : 3단 패널 × 패널당 종 2개(이중축) × 야간 회색음영, x=KST
                    → make_timeseries()  [박사님 MATLAB figure_time_series 변환]
  (B) Diurnal 6장 : 종쌍 3개 × 기간 2개. 이중축 + median 마커선 + 25–75 IQR 음영
                    → make_diurnal()     [pptx 그림에서 로직 역설계]

실데이터(ToF)가 아직 없어서 지금은 ▶ make_dummy_data() 의 가짜 데이터로 모양만
맞춰둔다. 실데이터 들어오면 load_data() 한 곳만 갈아끼우면 된다(아래 설명 참조).

────────────────────────────────────────────────────────────────────────────
■ MATLAB ↔ Python 대응
    time_tof_60s + time_diff      → df.index (tz 보정 끝난 KST DatetimeIndex)
    data_tof_norm_60s_amb(:,idx)  → df[species]  (종별 컬럼)
    yyaxis right                  → ax.twinx()
    patch(...FaceAlpha 0.4 회색)  → ax.axvspan(...)  (야간 음영)
    diurnal median / 25-75 IQR    → groupby(hour).median() + .quantile([.25,.75])
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")                 # GUI 없이 PNG로 저장
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# ── 종(species) 정의 ─────────────────────────────────────────────────────────
# scale = 축 표기를 ×10ⁿ 로 만들기 위한 곱. label 의 ×10ⁿ 표기와 짝을 맞춘다.
@dataclass
class Sp:
    key: str            # 데이터 컬럼명
    label: str          # 축 라벨(matplotlib mathtext)
    color: str
    scale: float = 1.0  # 표시값 = 원시값 * scale
    ylim: tuple | None = None

# 패널 = (왼축 종, 오른축 종).  pptx image1 / image2~7 의 배치와 단위를 따름.
PANELS = [
    (Sp("HNO3",  r"HNO$_3$ [ncps]",                 "k",       1.0,   (0, 0.03)),
     Sp("HCOOH", r"HCOOH [ncps]",                   "r",       1.0,   (0, 0.03))),
    (Sp("ClNO2", r"ClNO$_2$ $\times10^{-3}$ [ncps]","b",       1e3,   (0, 3.5)),
     Sp("N2O5",  r"N$_2$O$_5$ $\times10^{-4}$ [ncps]","m",     1e4,   (0, 2.0))),
    (Sp("Cl2",   r"Cl$_2$ [pptv]",                  "0.45",    1.0,   (0, 20)),
     Sp("Br2",   r"Br$_2$ [pptv]",                  "#ff7f0e", 1.0,   (0, 30))),
]

# Diurnal 은 ×10² 스케일(pptx 라벨 그대로). 종쌍은 PANELS 와 동일.
DIURNAL = [
    (Sp("HNO3",  r"HNO$_3$ $\times10^{2}$ [ncps]",  "k",       1e2,  None),
     Sp("HCOOH", r"HCOOH $\times10^{2}$ [ncps]",    "r",       1e2,  None)),
    (Sp("Cl2",   r"Cl$_2$ [pptv]",                  "0.45",    1.0,  None),
     Sp("Br2",   r"Br$_2$ [pptv]",                  "#ff7f0e", 1.0,  None)),
    (Sp("ClNO2", r"ClNO$_2$ $\times10^{3}$ [ncps]", "b",       1e3,  None),
     Sp("N2O5",  r"N$_2$O$_5$ $\times10^{4}$ [ncps]","m",      1e4,  None)),
]

# 야간 음영 구간(박사님 MATLAB 과 동일): 매일 19:40 ~ 익일 05:30, 회색 alpha 0.4
NIGHT_START = (19, 40)
NIGHT_END   = (5, 30)
NIGHT_COLOR = (0.85, 0.85, 0.85)
NIGHT_ALPHA = 0.4


# ── 데이터 로딩 ──────────────────────────────────────────────────────────────
def load_data() -> pd.DataFrame:
    """ToF 데이터를 KST DatetimeIndex + 종별 컬럼인 DataFrame 으로 반환.

    ▶▶ 실데이터 들어오면 여기만 교체 ◀◀
    필요 형태: index = tz 보정 끝난 시각(KST), columns ⊇
               {HNO3, HCOOH, ClNO2, N2O5, Cl2, Br2}.
    예) MATLAB 변수를 csv/mat 로 받으면:
        df = pd.read_csv(path, parse_dates=['time'], index_col='time')
        df = df.rename(columns={'idx_190':'HNO3', 'idx_173':'HCOOH', ...})
    지금은 더미 데이터로 대체.
    """
    return make_dummy_data()


def make_dummy_data(days: int = 22, freq: str = "60s", seed: int = 0) -> pd.DataFrame:
    """pptx 그림과 비슷한 일주기·야간피크를 갖는 가짜 ToF 데이터 생성(모양 확인용)."""
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-05-31", periods=int(days * 24 * 3600 / 60), freq=freq)
    hod = t.hour + t.minute / 60.0                  # 0~24 연속 시
    noon = np.exp(-((hod - 13) ** 2) / (2 * 3.0 ** 2))   # 낮(광화학) 봉우리
    night = np.maximum(np.exp(-((hod - 2) ** 2) / (2 * 2.5 ** 2)),
                       np.exp(-((hod - 23) ** 2) / (2 * 2.5 ** 2)))  # 밤 봉우리
    n = len(t)

    def noisy(base, lo=0.0):
        return np.clip(base * (1 + 0.25 * rng.standard_normal(n)) +
                       0.05 * base.max() * rng.standard_normal(n), lo, None)

    df = pd.DataFrame(index=t)
    df["HNO3"]  = noisy(0.006 + 0.010 * noon)              # 낮 높음
    df["HCOOH"] = noisy(0.002 + 0.012 * noon)              # 낮 높음(가파른 상승)
    df["ClNO2"] = noisy(0.0003 + 0.0022 * night, 0)        # 밤 높음
    df["N2O5"]  = noisy(0.00002 + 0.00012 * night, 0)      # 밤 높음
    df["Cl2"]   = noisy(2 + 8 * noon, 0)                   # 낮 높음(쌍봉 경향)
    df["Br2"]   = noisy(6 + 8 * noon, 0)                   # 낮 높음
    df.index.name = "time_kst"
    return df


# ── (A) 시계열 3단 패널 ──────────────────────────────────────────────────────
def _shade_nights(ax, t0: pd.Timestamp, t1: pd.Timestamp):
    """[t0, t1] 사이 매일 야간 구간을 회색으로 음영(MATLAB patch 루프 대응)."""
    d = pd.Timestamp(t0.date())
    while d <= t1:
        ns = d + pd.Timedelta(hours=NIGHT_START[0], minutes=NIGHT_START[1])
        ne = d + pd.Timedelta(days=1, hours=NIGHT_END[0], minutes=NIGHT_END[1])
        ax.axvspan(max(ns, t0), min(ne, t1), color=NIGHT_COLOR,
                   alpha=NIGHT_ALPHA, lw=0, zorder=0)
        d += pd.Timedelta(days=1)


def make_timeseries(df: pd.DataFrame, xlim=None, out=None):
    """3단(HNO3/HCOOH · ClNO2/N2O5 · Cl2/Br2) 이중축 시계열 + 야간 음영."""
    if xlim is None:
        xlim = (df.index[0], df.index[-1])
    t0, t1 = pd.Timestamp(xlim[0]), pd.Timestamp(xlim[1])

    fig, axes = plt.subplots(3, 1, figsize=(7, 7), sharex=True)
    fig.patch.set_facecolor("w")
    for ax, (spL, spR) in zip(axes, PANELS):
        _shade_nights(ax, t0, t1)
        # 왼축
        ax.plot(df.index, df[spL.key] * spL.scale, ".", color=spL.color, ms=2)
        ax.set_ylabel(spL.label, color=spL.color)
        ax.tick_params(axis="y", colors=spL.color, length=4)
        if spL.ylim: ax.set_ylim(spL.ylim)
        # 오른축
        axr = ax.twinx()
        axr.plot(df.index, df[spR.key] * spR.scale, ".", color=spR.color, ms=2)
        axr.set_ylabel(spR.label, color=spR.color)
        axr.tick_params(axis="y", colors=spR.color, length=4)
        if spR.ylim: axr.set_ylim(spR.ylim)
        for a in (ax, axr):
            a.set_xlim(t0, t1)

    axes[-1].set_xlabel("Time [KST]")
    axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=3))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.align_ylabels(axes)
    fig.tight_layout()
    _save(fig, out or "tof_timeseries.png")


# ── (B) Diurnal (median + 25–75 IQR), 종쌍별 이중축 ─────────────────────────
def _diurnal_stats(s: pd.Series):
    """시(hour)별 median 과 25/75 분위수. 반환: hours, med, q25, q75."""
    g = s.groupby(s.index.hour)
    med = g.median()
    q25 = g.quantile(0.25)
    q75 = g.quantile(0.75)
    h = med.index.to_numpy()
    return h, med.to_numpy(), q25.to_numpy(), q75.to_numpy()


def make_diurnal_pair(df: pd.DataFrame, spL: Sp, spR: Sp, title="", out=None):
    """한 종쌍의 diurnal 이중축 그림(median 선+마커, 25-75 IQR 음영)."""
    fig, ax = plt.subplots(figsize=(4.2, 4.0))
    fig.patch.set_facecolor("w")
    for ax_, sp, side in ((ax, spL, "left"), (ax.twinx(), spR, "right")):
        h, med, q25, q75 = _diurnal_stats(df[sp.key] * sp.scale)
        ax_.fill_between(h, q25, q75, color=sp.color, alpha=0.20, lw=0)
        ax_.plot(h, med, "-o", color=sp.color, ms=4, lw=1.2)
        ax_.set_ylabel(sp.label, color=sp.color)
        ax_.tick_params(axis="y", colors=sp.color)
        if sp.ylim: ax_.set_ylim(sp.ylim)
    ax.set_xlabel("Hour of day (KST)")
    ax.set_xlim(0, 23)
    ax.set_xticks([0, 6, 12, 18])
    if title:
        ax.set_title(title)
    fig.tight_layout()
    _save(fig, out or f"tof_diurnal_{spL.key}_{spR.key}.png")


def make_diurnal(df: pd.DataFrame, label: str):
    """주어진 (기간 슬라이스된) df 로 종쌍 3개 diurnal 을 모두 생성."""
    for spL, spR in DIURNAL:
        make_diurnal_pair(df, spL, spR, title=label,
                          out=f"tof_diurnal_{label}_{spL.key}_{spR.key}.png")


# ── 저장 유틸 ────────────────────────────────────────────────────────────────
def _save(fig, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"saved: {path}")


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    df = load_data()

    # (A) 시계열 — pptx 와 동일하게 5/31 ~ 6/22 12:00 범위
    make_timeseries(df, xlim=("2026-05-31", "2026-06-22 12:00"))

    # (B) Diurnal — 기간 2개: Entire period / 6/15–6/22(이번주)
    make_diurnal(df, "entire")
    make_diurnal(df.loc["2026-06-15":"2026-06-22"], "wk_0615-0622")


if __name__ == "__main__":
    main()
