"""CAESAR 주간회의 그림 — 내 fit 농도를 박사님 포맷으로 (standalone, GUI 아님)
================================================================================
레퍼런스: 주간회의 week3~4 의 CAESAR 그림 + week5 ToF 그림.
종(species)마다 [시계열 | diurnal] 한 쌍을 그린다.

  · 시계열 : 야간 회색음영(19:40~익일05:30) + x=KST 날짜
  · diurnal: 시(hour)별  Median(빨강 점선+마커) + Mean(선) + IQR 25–75% 음영
             x = Hour of day (KST)

대상 종(요청): NO2 · PNs · ANs · CHOCHO  (Cold NO2/CHOCHO + Hot PNs/ANs)
  NO2 패널은 누적 트레이스: NO2 / NO2+PNs / NO2+PNs+ANs  (총질산 누적)
  (NO2=Cold, PNs=PNsCh−Cold, ANs=ANsCh−PNsCh — 결과뷰어 _derive_no2_pns_ans 와 동일)

────────────────────────────────────────────────────────────────────────────────
■ 두 출력 모드 (같은 draw_* 함수를 ax 에 꽂아 재사용)
    기본      : 종별 파일 분리      caesar_<gas>.png   (한 장 = [시계열|diurnal])
    --composite: 박사님 복합형 한 장 caesar_composite.png (종을 세로로 N행 ×2열)
────────────────────────────────────────────────────────────────────────────────
■ 실데이터 연결 (지금은 더미)
    load_data() 한 곳만 교체. 필요 형태:
      df: index=KST 시각, columns ⊇ {NO2, PNs, ANs, CHOCHO} (ppb)
    실제로는 채널별 fit 리포트(Cold/PNs/ANs)를 읽어 시간정렬·차분해야 함
    → read_fit_report() / derive_no2_family() 골격을 아래 넣어둠(파일 생기면 활성화).
"""
from __future__ import annotations

import os
import sys
import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# QC 문턱식은 core/result_io.py 가 단일 출처 — 여기서 다시 구현하지 않는다(원칙 3).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from core.result_io import robust_rms_thresholds  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# 실 fit 리포트 폴더 (채널 3개). cold 은 스펙트로미터 고장으로 6/15~6/18 만 존재.
# QCk6  = 핏 단계 Auto QC K=6 적용본(QC-제외 행 NaN). Unstable 은 살아있음.
# QCoff = QC 미적용 핏본(진짜 raw). --qc-off 일 때 이걸 읽어야 정확.
DATA_DIR_QCON  = r"C:\Doasis_Work\Output\fitting\260615-260622\neg_o\QCk6"
DATA_DIR_QCOFF = r"C:\Doasis_Work\Output\fitting\260615-260622\neg_o\QCoff"
DATA_DIR = DATA_DIR_QCON   # 기본(QC on). main 에서 모드별로 교체
CHANNELS = {            # 라벨 → 파일명 일부(glob)
    "cold": "*cold*.dat",
    "CH1":  "*CH1*.dat",
    "CH2":  "*CH2*.dat",
}
TARGET_GASES = ["NO2", "CHOCHO"]   # 채널별로 그릴 가스

# 야간 음영(박사님 MATLAB 과 동일): 매일 19:40 ~ 익일 05:30
NIGHT_START, NIGHT_END = (19, 40), (5, 30)
NIGHT_COLOR, NIGHT_ALPHA = (0.85, 0.85, 0.85), 0.4

# diurnal 공통 스타일
MED_COLOR, MEAN_COLOR = "#d62728", "k"     # Median 빨강, Mean 검정

# 폰트/레이아웃 (박사님 피드백: ylabel 키우기·여백 줄이기)
LABEL_FS, TICK_FS, LEG_FS = 14, 11, 8      # y/x라벨 · 눈금 · 범례
FIG_W = 10.5                                # 한 행 가로(인치)
ROW_H_SINGLE, ROW_H_COMPO = 3.2, 2.7        # 단독 / 복합 행높이
WIDTH_RATIOS = [2.4, 1]                      # [시계열 : diurnal]
SAVE_FORMATS = ["png"]                       # main 에서 --vector 시 pdf·svg 추가


@dataclass
class Gas:
    key: str
    label: str            # 축 라벨(mathtext)
    color: str            # 시계열·IQR 색
    cumulative: bool = False   # NO2 처럼 누적 트레이스로 그릴지


GASES = {
    "NO2":    Gas("NO2",    r"NO$_2$ [ppbv]",    "#1f77b4", cumulative=True),
    "PNs":    Gas("PNs",    r"PNs [ppbv]",       "0.45"),
    "ANs":    Gas("ANs",    r"ANs [ppbv]",       "#d62728"),
    "CHOCHO": Gas("CHOCHO", r"CHOCHO [ppbv]",    "#2ca02c"),
}
ORDER = ["NO2", "PNs", "ANs", "CHOCHO"]


# ── 데이터 로딩 ──────────────────────────────────────────────────────────────
def load_data() -> pd.DataFrame:
    """▶▶ 실데이터 들어오면 여기만 교체 ◀◀  (지금은 더미)"""
    return make_dummy_data()


def read_fit_report(path: str, ok_only: bool = True, qc_k: float = 6.0) -> pd.DataFrame:
    """CAESAR fit 리포트(Time + 가스컬럼 + RMS + Status) → DataFrame(index=Time).
    결과뷰어 _load_fit_table 포맷과 동일. 사후 QC(핏 재실행 X):
      · 항상 Skip/QC-* 행 제외
      · ok_only=True  → Status!=OK(예: Unstable) 행 제외
      · qc_k>0        → RMS robust 임계 초과 행 제외  thr=10^(median(log10 RMS)+K·MAD)
                        (core.result_io.robust_rms_thresholds 호출 = GUI _apply_auto_qc와 **같은 함수**.
                         cold 은 K=4 쓰지 말 것 — 과제거)"""
    df = pd.read_csv(path, sep="\t", comment="#", engine="python")
    df.columns = [c.strip() for c in df.columns]
    df.index = pd.to_datetime(df["Time"], errors="coerce")
    df = df[~df.index.isna()].sort_index()
    if "Status" in df.columns:
        st = df["Status"].astype(str)
        drop = st.str.startswith("QC") | st.str.startswith("Skip")
        if ok_only:
            # Status 는 자유형식이다 — 품질 라벨 뒤에 직교하는 노트가 붙는다
            # (`OK · AT_BOUND`, `OK · MISFIT` …). 정확 일치로 비교하면 노트가
            # 붙었다는 이유만으로 멀쩡한 행을 버린다(실측 autosave 23,583 행 중
            # 2,135 행 = 9.1 %). 라벨만 본다.
            drop |= ~st.str.startswith("OK")
        df = df.loc[~drop]
    for g in ("NO2", "CHOCHO", "H2O"):
        if g in df.columns:
            df[g] = pd.to_numeric(df[g], errors="coerce")
    if qc_k > 0 and "RMS" in df.columns:
        rms = pd.to_numeric(df["RMS"], errors="coerce").to_numpy(float)
        # core 단일 출처. channels=None = 이 리포트 전체를 한 그룹으로(파일이 이미 채널별).
        # 표본부족(<5)이나 MAD=0이면 core가 +inf 를 줘서 아무도 안 걸러진다 —
        # 사본 시절의 "그냥 건너뜀"과 동일(무작위 21,000건 대조로 동치 확인).
        thr = robust_rms_thresholds(rms, K=qc_k).get(0, float("inf"))
        df = df.loc[~(np.isfinite(rms) & (rms > thr))]
    return df


def load_channels(ok_only: bool = True, qc_k: float = 6.0) -> dict[str, pd.DataFrame]:
    """DATA_DIR 의 채널 3개(cold/CH1/CH2) 리포트를 읽어 {라벨: df}."""
    import glob
    out = {}
    for label, pat in CHANNELS.items():
        hits = glob.glob(os.path.join(DATA_DIR, pat))
        if hits:
            out[label] = read_fit_report(hits[0], ok_only=ok_only, qc_k=qc_k)
    return out


def derive_no2_family(cold, pns_ch, ans_ch) -> pd.DataFrame:
    """채널 NO2 3개(Cold/PNs/ANs 리포트)를 Cold 시각격자에 정렬·차분.
    반환 columns: NO2, PNs, ANs  (결과뷰어 _derive_no2_pns_ans 와 동일 정의)."""
    t = cold.index
    c = cold["NO2"].to_numpy(float)
    p = np.interp(t.view("int64"), pns_ch.index.view("int64"),
                  pns_ch["NO2"].to_numpy(float), left=np.nan, right=np.nan)
    a = np.interp(t.view("int64"), ans_ch.index.view("int64"),
                  ans_ch["NO2"].to_numpy(float), left=np.nan, right=np.nan)
    return pd.DataFrame({"NO2": c, "PNs": p - c, "ANs": a - p}, index=t)


def make_dummy_data(days: int = 22, freq: str = "60s", seed: int = 0) -> pd.DataFrame:
    """week3~4 와 비슷한 일주기를 갖는 가짜 CAESAR 농도(모양 확인용)."""
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-05-31", periods=int(days * 24 * 3600 / 60), freq=freq)
    h = t.hour + t.minute / 60.0
    rush = (np.exp(-((h - 8) ** 2) / 4) + np.exp(-((h - 19) ** 2) / 5))   # 출퇴근 NO2
    noon = np.exp(-((h - 13) ** 2) / 8)                                   # 광화학 낮봉
    n = len(t)

    def noisy(base, lo=0.0):
        return np.clip(base * (1 + 0.3 * rng.standard_normal(n)), lo, None)

    df = pd.DataFrame(index=t)
    df["NO2"]    = noisy(3 + 8 * rush)
    df["PNs"]    = noisy(0.3 + 1.2 * noon)
    df["ANs"]    = noisy(0.2 + 0.8 * noon)
    df["CHOCHO"] = noisy(0.1 + 0.6 * noon)
    df.index.name = "time_kst"
    return df


# ── 그리기 프리미티브 (ax 받음 → 분리/복합 양쪽 재사용) ───────────────────────
def _shade_nights(ax, t0, t1):
    # 첫날 새벽(전날밤 19:40~익일05:30의 끝부분)도 칠해지게 하루 앞에서 시작.
    d = pd.Timestamp(t0.date()) - pd.Timedelta(days=1)
    while d <= t1:
        ns = d + pd.Timedelta(hours=NIGHT_START[0], minutes=NIGHT_START[1])
        ne = d + pd.Timedelta(days=1, hours=NIGHT_END[0], minutes=NIGHT_END[1])
        a, b = max(ns, t0), min(ne, t1)
        if a < b:   # 범위 밖/0폭 구간은 건너뜀(마지막날 끝 등)
            ax.axvspan(a, b, color=NIGHT_COLOR, alpha=NIGHT_ALPHA, lw=0, zorder=0)
        d += pd.Timedelta(days=1)


def _daily_xaxis(ax, t0, t1):
    """매일 00:00 major tick + 6/12/18시 minor tick (박사님 요청)."""
    ax.set_xlim(t0, t1)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=[6, 12, 18]))
    ax.tick_params(axis="x", which="major", length=6)
    ax.tick_params(axis="x", which="minor", length=3)
    ax.tick_params(axis="x", labelsize=TICK_FS)
    ax.set_xlabel("Time [KST]", fontsize=LABEL_FS - 1)


def draw_timeseries(ax, df, gas: Gas, xlim=None):
    """시계열 + 야간음영. NO2 면 누적 트레이스(NO2 / +PNs / +ANs)."""
    if xlim is None:
        xlim = (df.index[0], df.index[-1])
    t0, t1 = pd.Timestamp(xlim[0]), pd.Timestamp(xlim[1])
    _shade_nights(ax, t0, t1)
    if gas.cumulative and {"PNs", "ANs"} <= set(df.columns):
        no2 = df["NO2"]
        ax.plot(df.index, no2, ".", ms=1.5, color="#1f77b4", label="NO$_2$")
        ax.plot(df.index, no2 + df["PNs"], ".", ms=1.5, color="#ff7f0e",
                label="NO$_2$+PNs")
        ax.plot(df.index, no2 + df["PNs"] + df["ANs"], ".", ms=1.5, color="#d62728",
                label="NO$_2$+PNs+ANs")
        ax.legend(fontsize=LEG_FS, loc="upper right", framealpha=0.6, markerscale=4)
    else:
        ax.plot(df.index, df[gas.key], ".", ms=1.5, color=gas.color)
    ax.set_ylabel(gas.label, fontsize=LABEL_FS)
    ax.tick_params(axis="y", labelsize=TICK_FS)
    _daily_xaxis(ax, t0, t1)


# ── 이중축(twinx) 버전: 한 그래프에 좌=종A / 우=종B (박사님 ToF 사진 방식) ──
def _diurnal_arrays(s):
    g = s.groupby(s.index.hour); h = np.arange(24)
    return (g.median().reindex(h).to_numpy(), g.quantile(0.25).reindex(h).to_numpy(),
            g.quantile(0.75).reindex(h).to_numpy())


def draw_timeseries_dual(ax, left, right, xlim=None):
    """좌축=left=(df,Gas) / 우축=right=(df,Gas), 색은 각 Gas.color. 야간음영 1회."""
    (dfL, gL), (dfR, gR) = left, right
    if xlim is None:
        xlim = (dfL.index[0], dfL.index[-1])
    t0, t1 = pd.Timestamp(xlim[0]), pd.Timestamp(xlim[1])
    _shade_nights(ax, t0, t1)
    ax.plot(dfL.index, dfL[gL.key], ".", ms=1.5, color=gL.color)
    ax.set_ylabel(gL.label, color=gL.color, fontsize=LABEL_FS)
    ax.tick_params(axis="y", colors=gL.color, labelsize=TICK_FS)
    axr = ax.twinx()
    axr.plot(dfR.index, dfR[gR.key], ".", ms=1.5, color=gR.color)
    axr.set_ylabel(gR.label, color=gR.color, fontsize=LABEL_FS)
    axr.tick_params(axis="y", colors=gR.color, labelsize=TICK_FS)
    _daily_xaxis(ax, t0, t1)


def draw_diurnal_dual(ax, left, right):
    """좌/우축 종별 Median(점선+마커)+IQR 음영, 각 Gas.color (ToF diurnal 방식)."""
    for a, (df, g) in ((ax, left), (ax.twinx(), right)):
        med, q25, q75 = _diurnal_arrays(df[g.key])
        h = np.arange(24)
        a.fill_between(h, q25, q75, color=g.color, alpha=0.18, lw=0)
        a.plot(h, med, "--o", color=g.color, ms=4, lw=1.2)
        a.set_ylabel(g.label, color=g.color, fontsize=LABEL_FS)
        a.tick_params(axis="y", colors=g.color, labelsize=TICK_FS)
    ax.set_xlabel("Hour of day (KST)", fontsize=LABEL_FS - 1)
    ax.set_xlim(0, 23); ax.set_xticks([0, 6, 12, 18])
    ax.tick_params(axis="x", labelsize=TICK_FS)


def make_pair_dual(left, right, xlim=None, out="caesar_pair_dual.png"):
    """이중축 한 행: [시계열(좌A/우B) | diurnal(좌A/우B)]."""
    fig, (axt, axd) = plt.subplots(1, 2, figsize=(FIG_W, ROW_H_SINGLE),
                                   gridspec_kw={"width_ratios": WIDTH_RATIOS},
                                   layout="constrained")
    fig.patch.set_facecolor("w")
    subL = (left[0] if xlim is None else left[0].loc[xlim[0]:xlim[1]], left[1])
    subR = (right[0] if xlim is None else right[0].loc[xlim[0]:xlim[1]], right[1])
    draw_timeseries_dual(axt, subL, subR, xlim)
    draw_diurnal_dual(axd, subL, subR)
    _save(fig, out)


def draw_diurnal(ax, df, gas: Gas):
    """시별 Median(빨강 점선+마커) + Mean(검정 선) + IQR 25–75% 음영."""
    s = df[gas.key]
    g = s.groupby(s.index.hour)
    h = np.arange(24)
    med = g.median().reindex(h).to_numpy()
    mean = g.mean().reindex(h).to_numpy()
    q25 = g.quantile(0.25).reindex(h).to_numpy()
    q75 = g.quantile(0.75).reindex(h).to_numpy()
    ax.fill_between(h, q25, q75, color=gas.color, alpha=0.20, lw=0,
                    label="IQR (25–75%)")
    ax.plot(h, med, "--o", color=MED_COLOR, ms=4, lw=1.2, label="Median")
    ax.plot(h, mean, "-", color=MEAN_COLOR, lw=1.0, label="Mean")
    ax.set_ylabel(gas.label, fontsize=LABEL_FS)
    ax.set_xlabel("Hour of day (KST)", fontsize=LABEL_FS - 1)
    ax.set_xlim(0, 23)
    ax.set_xticks([0, 6, 12, 18])
    ax.tick_params(labelsize=TICK_FS)
    ax.legend(fontsize=LEG_FS, loc="best", framealpha=0.6)


# ── 출력 모드 ────────────────────────────────────────────────────────────────
def make_species_files(df, gases, xlim=None):
    """종별 파일 분리: 한 장 = [시계열 | diurnal]."""
    for key in gases:
        gas = GASES[key]
        fig, (axt, axd) = plt.subplots(1, 2, figsize=(11, 3.2),
                                       gridspec_kw={"width_ratios": [2.2, 1]})
        fig.patch.set_facecolor("w")
        draw_timeseries(axt, df, gas, xlim)
        draw_diurnal(axd, df, gas)
        fig.suptitle(f"CAESAR — {key}", fontsize=11)
        fig.tight_layout()
        _save(fig, f"caesar_{key}.png")


def make_composite_rows(rows, xlim=None, out="caesar_composite.png"):
    """박사님 복합형: rows=[(df, Gas), ...] 를 세로로 쌓아 N행 × 2열(시계열|diurnal).
    각 행의 y라벨은 Gas.label 그대로(채널명 안 붙음)."""
    n = len(rows)
    fig, axes = plt.subplots(n, 2, figsize=(FIG_W, ROW_H_COMPO * n),
                             gridspec_kw={"width_ratios": WIDTH_RATIOS},
                             squeeze=False, layout="constrained")
    fig.patch.set_facecolor("w")
    for i, (df, gas) in enumerate(rows):
        sub = df if xlim is None else df.loc[xlim[0]:xlim[1]]
        draw_timeseries(axes[i][0], sub, gas, xlim)
        draw_diurnal(axes[i][1], sub, gas)
    _save(fig, out)


# 채널별/유도 가스 설정 (PNs 회색·ANs 빨강 = week3~4 박사님 색)
GAS_CFG = {
    "NO2":    Gas("NO2",    r"NO$_2$ [ppbv]",    "#1f77b4"),
    "PNs":    Gas("PNs",    r"PNs [ppbv]",       "0.45"),
    "ANs":    Gas("ANs",    r"ANs [ppbv]",       "#d62728"),
    "CHOCHO": Gas("CHOCHO", r"CHOCHO [ppbv]",    "#2ca02c"),
}


def _align_no2(df, grid):
    """df 의 NO2 를 grid(DatetimeIndex)에 보간(범위 밖 NaN)."""
    s = pd.to_numeric(df["NO2"], errors="coerce")
    return np.interp(grid.view("int64"), df.index.view("int64"), s.to_numpy(float),
                     left=np.nan, right=np.nan)


def derive_td(channels: dict) -> dict:
    """TD-CEAS 차분 유도. 채널 매핑 가정: CH1=PNs(180°C), CH2=ANs(300°C).
      NO2 = Cold                       (콜드 의존 → 6/15~6/18)
      PNs = PNs채널(CH1) − Cold        (콜드 의존 → 6/15~6/18)
      ANs = ANs채널(CH2) − PNs채널(CH1) (✅ 콜드 무관 → 풀주간)
    각 결과를 단일 컬럼 DataFrame 으로 반환(draw_* 재사용용)."""
    out = {}
    if "cold" in channels:
        c = channels["cold"]
        out["NO2"] = pd.DataFrame({"NO2": pd.to_numeric(c["NO2"], errors="coerce").values},
                                  index=c.index)
        if "CH1" in channels:
            ch1i = _align_no2(channels["CH1"], c.index)
            out["PNs"] = pd.DataFrame({"PNs": ch1i - pd.to_numeric(c["NO2"], errors="coerce").values},
                                      index=c.index)
    if "CH1" in channels and "CH2" in channels:
        g = channels["CH2"].index
        ch1i = _align_no2(channels["CH1"], g)
        out["ANs"] = pd.DataFrame({"ANs": pd.to_numeric(channels["CH2"]["NO2"], errors="coerce").values - ch1i},
                                  index=g)
    return out


def make_td_files(derived: dict, xlim=None):
    """유도 NO2/PNs/ANs 각각 [시계열 | diurnal] 한 장씩 분리 저장."""
    for key, df in derived.items():
        gas = GAS_CFG[key]
        sub = df if xlim is None else df.loc[xlim[0]:xlim[1]]
        if sub[key].notna().sum() < 5:
            continue
        fig, (axt, axd) = plt.subplots(1, 2, figsize=(FIG_W, ROW_H_SINGLE),
                                       gridspec_kw={"width_ratios": WIDTH_RATIOS},
                                       layout="constrained")
        fig.patch.set_facecolor("w")
        draw_timeseries(axt, sub, gas, xlim)
        draw_diurnal(axd, sub, gas)
        span = f"{sub.index.min():%m/%d}~{sub.index.max():%m/%d}"
        fig.suptitle(f"CAESAR {key} (derived) — ({span}, n={sub[key].notna().sum()})",
                     fontsize=12)
        _save(fig, f"caesar_TD_{key}.png")


def make_channel_files(channels: dict, gases=TARGET_GASES, xlim=None):
    """채널 × 가스 마다 [시계열 | diurnal] 한 장씩 분리 저장."""
    for ch, df in channels.items():
        for gkey in gases:
            if gkey not in df.columns:
                continue
            gas = GAS_CFG[gkey]
            sub = df if xlim is None else df.loc[xlim[0]:xlim[1]]
            if sub[gkey].notna().sum() < 5:
                continue
            fig, (axt, axd) = plt.subplots(1, 2, figsize=(FIG_W, ROW_H_SINGLE),
                                           gridspec_kw={"width_ratios": WIDTH_RATIOS},
                                           layout="constrained")
            fig.patch.set_facecolor("w")
            # 시계열 x축은 전체 주간창으로 고정(cold 결손이 보이게)
            draw_timeseries(axt, sub, gas, xlim)
            draw_diurnal(axd, sub, gas)
            span = f"{sub.index.min():%m/%d}~{sub.index.max():%m/%d}"
            fig.suptitle(f"CAESAR {ch} — {gkey}   ({span}, n={sub[gkey].notna().sum()})",
                         fontsize=12)
            _save(fig, f"caesar_{ch}_{gkey}.png")


# 현재 실행의 출력 폴더 (main 에서 QC 모드별로 out/qcon · out/qcoff 로 설정)
RUN_OUT = OUT_DIR


def _save(fig, name):
    """SAVE_FORMATS(png 기본, --vector 시 pdf·svg)로 저장.
    constrained_layout 사용 중이라 bbox_inches='tight' 는 빼서 충돌 방지."""
    os.makedirs(RUN_OUT, exist_ok=True)
    stem = os.path.splitext(name)[0]
    for ext in SAVE_FORMATS:
        path = os.path.join(RUN_OUT, f"{stem}.{ext}")
        fig.savefig(path, dpi=200)
        print(f"saved: {path}")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dummy", action="store_true",
                    help="실데이터 대신 더미로(엔진 점검용)")
    ap.add_argument("--start", default="2026-06-15",
                    help="시계열 시작 (기본: 주간회의 범위 6/15 00:00)")
    ap.add_argument("--end", default="2026-06-22",
                    help="시계열 끝 (기본: 6/22 00:00)")
    ap.add_argument("--qc-k", type=float, default=6.0,
                    help="사후 RMS QC 민감도(0=끔, 기본 6). cold엔 4 쓰지 말 것")
    ap.add_argument("--no-ok-only", action="store_true",
                    help="Status=OK 필터 끄기(Unstable 도 포함)")
    ap.add_argument("--qc-off", action="store_true",
                    help="QC 전부 끄기(Status OK필터·RMS QC 모두 off, 비교용)")
    ap.add_argument("--composite", action="store_true",
                    help="NO2(CH2)+ANs 위아래 스택 복합형 추가 출력")
    ap.add_argument("--dual", action="store_true",
                    help="NO2(좌)+ANs(우) 이중축 한 그래프(박사님 ToF 사진 방식)")
    ap.add_argument("--vector", action="store_true",
                    help="PNG 외에 PDF·SVG 벡터도 저장(슬라이드/편집용)")
    ap.add_argument("--mat", action="store_true",
                    help="농도 데이터를 .mat 로 export(박사님 MATLAB 취합용)")
    args = ap.parse_args()
    xlim = (args.start, args.end)

    if args.vector:
        global SAVE_FORMATS
        SAVE_FORMATS = ["png", "pdf", "svg"]

    if args.dummy:
        df = make_dummy_data().loc[args.start:args.end]
        make_species_files(df, ORDER, xlim)
        return

    ok_only = not (args.no_ok_only or args.qc_off)
    qc_k = 0.0 if args.qc_off else args.qc_k

    # QC 모드별로 데이터 폴더 + 출력 폴더 둘 다 분리(양쪽 보존)
    global DATA_DIR, RUN_OUT
    DATA_DIR = DATA_DIR_QCOFF if args.qc_off else DATA_DIR_QCON
    RUN_OUT = os.path.join(OUT_DIR, "qcoff" if args.qc_off else "qcon")

    # 실데이터: 채널 3개(cold/CH1/CH2) × 가스(NO2/CHOCHO) 따로 그림
    channels = load_channels(ok_only=ok_only, qc_k=qc_k)
    if not channels:
        print(f"no fit files in {DATA_DIR}")
        return
    print(f"QC: ok_only={ok_only} qc_k={qc_k} | loaded:",
          {k: len(v) for k, v in channels.items()})
    # 채널별 raw (cold/CH1/CH2 × NO2/CHOCHO)
    make_channel_files(channels, TARGET_GASES, xlim)
    # TD 차분 유도 (NO2=Cold / PNs=CH1−Cold / ANs=CH2−CH1)
    derived = derive_td(channels)
    print("derived:", {k: int(v[k].notna().sum()) for k, v in derived.items()})
    make_td_files(derived, xlim)

    # NO2(CH2, 라벨은 그냥 NO2) + ANs 복합형
    if args.composite and "CH2" in channels and "ANs" in derived:
        rows = [(channels["CH2"], GAS_CFG["NO2"]),
                (derived["ANs"], GAS_CFG["ANs"])]
        make_composite_rows(rows, xlim, out="caesar_NO2_ANs.png")

    # NO2(좌)+ANs(우) 이중축 한 그래프
    if args.dual and "CH2" in channels and "ANs" in derived:
        make_pair_dual((channels["CH2"], GAS_CFG["NO2"]),
                       (derived["ANs"], GAS_CFG["ANs"]),
                       xlim, out="caesar_NO2_ANs_dual.png")

    if args.mat:
        export_mat(channels, derived, xlim)


def export_mat(channels: dict, derived: dict, xlim=None):
    """채널 raw + TD 유도 농도를 .mat 로 저장(박사님 MATLAB 취합/.fig 작성용).
    각 계열 = struct(t_datenum, t_str, value). MATLAB: datestr(t_datenum) 로 시각 복원."""
    from scipy.io import savemat
    EPOCH_DATENUM = 719529.0   # MATLAB datenum of 1970-01-01 (Unix epoch)

    def ser(idx, vals):
        ep = idx.asi8 / 1e9                              # epoch seconds (asi8 = int64 ns)
        return {"t_datenum": EPOCH_DATENUM + ep / 86400.0,
                "t_str": np.array([t.strftime("%Y-%m-%d %H:%M:%S") for t in idx], dtype=object),
                "value": np.asarray(vals, float)}

    out = {}
    for ch, df in channels.items():
        sub = df if xlim is None else df.loc[xlim[0]:xlim[1]]
        for g in ("NO2", "CHOCHO"):
            if g in sub.columns:
                out[f"{ch}_{g}"] = ser(sub.index, sub[g].to_numpy(float))
    for key, df in derived.items():                       # NO2/PNs/ANs
        sub = df if xlim is None else df.loc[xlim[0]:xlim[1]]
        out[f"TD_{key}"] = ser(sub.index, sub[key].to_numpy(float))
    out["README"] = ("CAESAR weekly conc (ppb). fields: <name>.t_datenum(MATLAB datenum), "
                     ".t_str, .value. TD_NO2=Cold, TD_PNs=CH1-Cold, TD_ANs=CH2-CH1. KST.")
    os.makedirs(RUN_OUT, exist_ok=True)
    path = os.path.join(RUN_OUT, "caesar_weekly_data.mat")
    savemat(path, out, do_compression=True)
    print(f"saved: {path}  ({len(out)-1} series)")


if __name__ == "__main__":
    main()
