"""⚠️ 2026-08-12 저녁: 이 방식은 R0 최종 제출에 미채택됨. 지도교수가 인젝션(g=0.82) 신뢰성을
낮게 판단해서 하루 동안 이 AQMS 앵커 방식으로 대체 진행했으나, 같은 날 저녁 다시 "인젝션 g=0.82
그대로 쓰고 콜드는 이상치만 제거"로 최종 결정이 바뀌었다. 최종 제출 로직은
tools/build_final_g082_submission.py 참고. 이 파일은 방법론 보존 + 향후 인젝션 재실험과의
교차검증용으로 repo에 남겨둔다. 산출물 위치는 Output/figure/*/‌_archive_aqms_anchor_not_used/.

AQMS 앵커 기반 콜드/핫 NO2 절대스케일 보정 -> ANs/PNs 산출 (탐색, 2026-08-12).

8/11 NO2 인젝션(g=0.82)은 교수님이 신뢰성 미흡 판정(희석 안정화/믹싱/리트리벌 안정성 3조건
미검증) -> 이번 R0 제출은 인젝션 없이 다음 방식으로 대체한다:

  1. 콜드 NO2를 NIER 순천 AQMS(Teledyne NO2)로 스케일 보정 (cold_corrected = cold_raw / 0.922).
     절편은 안 뺀다 -- AQMS가 몰리브덴 컨버터라 NO2+NOz를 재는 데서 오는 AQMS 쪽 양의 바이어스이지
     콜드 오차가 아니다(화학적 검산 완료, 세션 로그 참고).
  2. 콜드_corrected를 절대기준 ref(t)로 삼아 핫 두 채널(ch1=ANs 300도C, ch2=PNs 180도C)의
     raw NO2 리트리벌이 몇 배 낮게 나오는지 24h movmean 비율로 구해 연속 보정곡선을 만든다.
     콜드가 없는 구간(캠페인 극초반, 콜드 QC 제외구간, 6/18 이후 전체)은 AQMS를 콜드의 대역물로
     직접 쓴다 -- 겹침구간에서 cold_corrected ~= AQMS(slope=1.0000)가 이미 검증됐기 때문.
  3. ANs = ch1_corrected - ch2_corrected, PNs = ch2_corrected - ref(t).

계획 문서: C:\\Users\\holle\\.claude\\plans\\serene-humming-popcorn.md
"""
from __future__ import annotations
import glob
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

COLD_CSV = r"C:\Doasis_Work\Output\figure\cold_NO2\GIST_CAESAR_cold_NO2_5min_KST_20260517_20260617.csv"
AQMS_XLSX = r"C:\Users\holle\ATMOS Dropbox\GyungHwan Lee\ATMOS_all\(mission)2026_yeosu\AQMSdata\AQMS_Time_corrected_version_SJY.xlsx"
# 2026-08-12: Output/fitting/.../*_ANs_*.dat (2026-07-09 생성)는 hot PC의 5/29 10:05:52
# UTC-toggle 시계버그가 반영 안 된 상태였다(그 이후 데이터가 통째로 ~9h 밀려있었음 -- AQMS
# 대비 상관이 6월부터 붕괴하는 것으로 발견, TIMEZONE_LABELED 소스로 교체해서 해결 확인:
# r 0.96~0.99 전 캠페인 유지). 이후 핫(ch1/ch2) 소스는 이 정타임스탬프 10s 파일을 쓴다.
HOT_10S_CH1 = r"C:\Users\holle\ATMOS Dropbox\GyungHwan Lee\ATMOS_all\(mission)2026_yeosu\data_obs\CAESAR\10s\10s_ch1_ANs_time_concentration_TIMEZONE_LABELED.csv"
HOT_10S_CH2 = r"C:\Users\holle\ATMOS Dropbox\GyungHwan Lee\ATMOS_all\(mission)2026_yeosu\data_obs\CAESAR\10s\10s_ch2_PNs_time_concentration_TIMEZONE_LABELED.csv"
OUT_DIR = r"C:\Doasis_Work\Output\figure\ANs"
DIAG_DIR = r"C:\Doasis_Work\Output\figure\ANs\_aqms_correction_diag"

COLD_SLOPE = 0.922   # cold_raw vs AQMS pooled regression slope, clean-period only (2026-08-12)

# cold NIER-submit と 동일 QC 제외창 (build_nier_submission.NAN_WINDOWS 와 단일 출처 유지할 것)
COLD_BAD_WINDOWS = [
    ("2026-05-20 00:00:00", "2026-05-24 00:00:00"),
    ("2026-05-27 18:00:00", "2026-05-28 12:00:00"),
    ("2026-06-05 00:00:00", "2026-06-05 23:59:59"),
    # 2026-08-12: 필드로그 "0602.008~ 로우파일 NO2 인젝션" -- raw 파일번호 007->012로 건너뜀,
    # 정확히 이 시간대 N_valid가 5->1로 급락(실측 확인). 앰비언트 아님.
    ("2026-06-02 16:10:00", "2026-06-02 16:55:00"),
]

# 2026-08-12: 필드로그 "6/9 20:20-20:30 Sampling valve closed -> NO2 injection 시작(013번 파일)"
# -- 이 창의 10s raw 표준편차가 주변 대비 5~10배 튐(실측 확인). 앰비언트 아님, 핫 두 채널 공통.
HOT_BAD_WINDOWS = [
    ("2026-06-09 19:55:00", "2026-06-09 20:45:00"),
]

MOVMEAN_WINDOW = "24h"
EVENT_DATES = [
    ("2026-06-05", "6/5 filter swap"),
    ("2026-06-14", "6/14 LED2"),
    ("2026-06-18", "cold->AQMS handoff"),
    ("2026-06-21", "6/21 filter test"),
]


def load_hot_10s(path: str) -> tuple[pd.Series, pd.Series]:
    """정타임스탬프 10s time_concentration CSV -> (5분 평균 NO2, 5분당 스캔수)."""
    df = pd.read_csv(path, usecols=["Timestamp_KST_UTC+09:00", "NO2"])
    df["t"] = pd.to_datetime(df["Timestamp_KST_UTC+09:00"]).dt.tz_localize(None)
    df["NO2"] = pd.to_numeric(df["NO2"], errors="coerce")
    g = df.set_index("t")["NO2"].resample("5min")
    return g.mean(), g.count()


def build_ref_series() -> tuple[pd.Series, pd.Series, pd.Series]:
    """cold_corrected, AQMS(teledyne_NO2), 결합 ref(t) 를 반환."""
    cold_raw = pd.read_csv(COLD_CSV, comment="#")
    cold_raw["datetime_KST"] = pd.to_datetime(cold_raw["datetime_KST"])
    cold_raw = cold_raw.set_index("datetime_KST")
    cold_corrected = cold_raw["NO2_ppb"] / COLD_SLOPE
    for start, end in COLD_BAD_WINDOWS:
        m = (cold_corrected.index >= start) & (cold_corrected.index <= end)
        cold_corrected.loc[m] = np.nan
    # 2026-08-12: 6/17이 콜드 자체 QC_flag=low_quality(흐림/저조도, elevated RMS)로 이미 표시돼
    # 있던 날 -- 이 마지막 하루가 AQMS와 어긋나 6/18 콜드->AQMS 경계에서 인위적 튐을 만들었다.
    # ref(t) 구성에도 이 플래그를 반영해 제외한다(NIER_submit 콜드 산출물 QC와 동일 기준).
    low_q = cold_raw["QC_flag"] == "low_quality"
    cold_corrected.loc[low_q] = np.nan

    aqms = pd.read_excel(AQMS_XLSX, sheet_name="Sheet1")
    aqms = aqms.set_index("AQMS_time")["teledyne_NO2"].resample("5min").mean()

    idx = aqms.index.union(cold_corrected.index)
    cold_corrected = cold_corrected.reindex(idx)
    aqms_r = aqms.reindex(idx)
    ref = cold_corrected.combine_first(aqms_r)
    return cold_corrected, aqms_r, ref


def main():
    os.makedirs(DIAG_DIR, exist_ok=True)

    print("=== 1. ref(t) 구성 ===")
    cold_corrected, aqms, ref = build_ref_series()
    n_from_cold = cold_corrected.notna().sum()
    n_from_aqms = (ref.notna() & cold_corrected.isna()).sum()
    print(f"ref(t): cold_corrected 유효 {n_from_cold}, AQMS 대체 {n_from_aqms}, 전체 {ref.notna().sum()}")
    print(f"range: {ref.dropna().index.min()} ~ {ref.dropna().index.max()}")

    print("\n=== 2. 핫 채널 raw 로드 (정타임스탬프 10s 소스) ===")
    ans_raw, ans_n = load_hot_10s(HOT_10S_CH1)
    pns_raw, pns_n = load_hot_10s(HOT_10S_CH2)
    print(f"ANs_ch1: {ans_raw.notna().sum()} bins  {ans_raw.index.min()} ~ {ans_raw.index.max()}")
    print(f"PNs_ch2: {pns_raw.notna().sum()} bins  {pns_raw.index.min()} ~ {pns_raw.index.max()}")

    for start, end in HOT_BAD_WINDOWS:
        m = (ans_raw.index >= start) & (ans_raw.index <= end)
        ans_raw.loc[m] = np.nan
        m2 = (pns_raw.index >= start) & (pns_raw.index <= end)
        pns_raw.loc[m2] = np.nan
    print(f"HOT_BAD_WINDOWS 적용 (인젝션 오염 제거): {len(HOT_BAD_WINDOWS)}개 창")

    idx = ans_raw.index.union(pns_raw.index).union(ref.index)
    df = pd.DataFrame({
        "ref": ref.reindex(idx),
        "cold_corrected": cold_corrected.reindex(idx),
        "aqms": aqms.reindex(idx),
        "ANs_ch1_raw": ans_raw.reindex(idx),
        "PNs_ch2_raw": pns_raw.reindex(idx),
        "n_scans_ch1": ans_n.reindex(idx),
        "n_scans_ch2": pns_n.reindex(idx),
    })

    ref_safe = df["ref"].where(df["ref"].abs() > 1.0)
    df["ratio_ch1"] = df["ANs_ch1_raw"] / ref_safe
    df["ratio_ch2"] = df["PNs_ch2_raw"] / ref_safe
    df["ratio_ch1_smooth"] = df["ratio_ch1"].rolling(MOVMEAN_WINDOW, min_periods=50).mean()
    df["ratio_ch2_smooth"] = df["ratio_ch2"].rolling(MOVMEAN_WINDOW, min_periods=50).mean()
    # 앞/뒤 결측 구간(스무딩 워밍업 등)은 가장 가까운 유효 보정계수로 연장 -- 커버리지 공백 방지
    df["ratio_ch1_smooth"] = df["ratio_ch1_smooth"].ffill().bfill()
    df["ratio_ch2_smooth"] = df["ratio_ch2_smooth"].ffill().bfill()

    print("\n=== 3. 경계/이벤트 연속성 점검 ===")
    for ev, lbl in EVENT_DATES:
        t = pd.Timestamp(ev)
        window = df.loc[t - pd.Timedelta("36h"): t + pd.Timedelta("36h")]
        before = window.loc[:t, ["ratio_ch1_smooth", "ratio_ch2_smooth"]].iloc[-1] if len(window.loc[:t]) else None
        after = window.loc[t:, ["ratio_ch1_smooth", "ratio_ch2_smooth"]].iloc[0] if len(window.loc[t:]) else None
        if before is not None and after is not None:
            print(f"  {lbl:24s} before={before.values}  after={after.values}")

    print("\n=== 4. 보정 적용 + ANs/PNs 계산 ===")
    df["ANs_ch1_corrected"] = df["ANs_ch1_raw"] / df["ratio_ch1_smooth"]
    df["PNs_ch2_corrected"] = df["PNs_ch2_raw"] / df["ratio_ch2_smooth"]
    df["ANs_ppb"] = df["ANs_ch1_corrected"] - df["PNs_ch2_corrected"]
    df["PNs_ppb"] = df["PNs_ch2_corrected"] - df["ref"]

    valid = df.dropna(subset=["ANs_ppb"])
    print(f"ANs_ppb: n={len(valid)}  median={valid['ANs_ppb'].median():+.4f}"
          f"  positive%={100*(valid['ANs_ppb']>0).mean():.1f}")
    valid_pns = df.dropna(subset=["PNs_ppb"])
    print(f"PNs_ppb: n={len(valid_pns)}  median={valid_pns['PNs_ppb'].median():+.4f}"
          f"  negative%={100*(valid_pns['PNs_ppb']<0).mean():.1f}")

    out_csv = os.path.join(DIAG_DIR, "aqms_corrected_full.csv")
    df.to_csv(out_csv)
    print(f"\nsaved {out_csv}")

    print("\n=== 6. NIER 제출용 소스 CSV 작성 ===")
    # 보정계수(ratio_smooth)의 raw-vs-smooth 잔차를 그 시점 ref(t) 로 ppb 환산 -> 대략적 계통불확도.
    # (엄밀한 오차전파는 아님 -- 8/11 인젝션 재확인 전까지의 잠정치, ANS_HDR 에 그렇게 명시)
    resid_ch1 = (df["ratio_ch1"] - df["ratio_ch1_smooth"]).rolling(MOVMEAN_WINDOW, min_periods=50).std()
    resid_ch2 = (df["ratio_ch2"] - df["ratio_ch2_smooth"]).rolling(MOVMEAN_WINDOW, min_periods=50).std()
    unc_ch1_ppb = (resid_ch1.ffill().bfill() * df["ref"]).abs()
    unc_ch2_ppb = (resid_ch2.ffill().bfill() * df["ref"]).abs()
    df["ANs_unc_ppb"] = np.sqrt(unc_ch1_ppb**2 + unc_ch2_ppb**2)
    df["PNs_unc_ppb"] = unc_ch2_ppb

    def _write_species_csv(species: str, value_col: str, unc_col: str, n_col: str, path: str):
        out = pd.DataFrame({
            "datetime_KST": df.index.strftime("%Y-%m-%d %H:%M:%S"),
            f"{species}_ppb": df[value_col].round(4),
            "sys_unc_ppb": df[unc_col].round(4),
            "n_scans": df[n_col].fillna(0).astype(int),
            "QC_flag": np.where(df[n_col].fillna(0) >= 3, "OK", "few_scans"),
        })
        out = out.dropna(subset=[f"{species}_ppb"])
        out.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"  {species}: {len(out):,} bins -> {path}")

    ans_src = os.path.join(OUT_DIR, "GIST_CAESAR_ANs_5min_KST_aqms_corrected_source.csv")
    pns_src = os.path.join(OUT_DIR, "GIST_CAESAR_PNs_5min_KST_aqms_corrected_source.csv")
    _write_species_csv("ANs", "ANs_ppb", "ANs_unc_ppb", "n_scans_ch1", ans_src)
    _write_species_csv("PNs", "PNs_ppb", "PNs_unc_ppb", "n_scans_ch2", pns_src)

    # 콜드 소스도 같은 스케일 보정 반영해서 다시 씀 (NAN_WINDOWS 처리는 build_nier_submission 이 담당)
    cold_full = pd.read_csv(COLD_CSV, comment="#")
    cold_full["NO2_ppb"] = pd.to_numeric(cold_full["NO2_ppb"], errors="coerce") / COLD_SLOPE
    cold_full["NO2_stdev_ppb"] = pd.to_numeric(cold_full["NO2_stdev_ppb"], errors="coerce") / COLD_SLOPE
    cold_src = os.path.join(OUT_DIR.replace("ANs", "cold_NO2"), "GIST_CAESAR_cold_NO2_5min_KST_aqms_corrected_source.csv")
    os.makedirs(os.path.dirname(cold_src), exist_ok=True)
    cold_full.to_csv(cold_src, index=False, encoding="utf-8-sig")
    print(f"  cold: {len(cold_full):,} bins -> {cold_src}")

    print("\n=== 5. 진단 플롯 ===")
    fig, axes = plt.subplots(3, 1, figsize=(16, 11), sharex=True)
    axes[0].plot(df.index, df["ratio_ch1"], ".", ms=1, alpha=0.1, color="tab:red")
    axes[0].plot(df.index, df["ratio_ch1_smooth"], color="darkred", lw=1.3, label="ch1 24h movmean")
    axes[0].axhline(1.0, color="gray", ls="--", lw=0.8)
    axes[0].set_ylim(0, 2.5)
    axes[0].set_ylabel("ANs_ch1_raw / ref(t)")
    axes[0].legend(loc="upper right", fontsize=8)

    axes[1].plot(df.index, df["ratio_ch2"], ".", ms=1, alpha=0.1, color="tab:blue")
    axes[1].plot(df.index, df["ratio_ch2_smooth"], color="navy", lw=1.3, label="ch2 24h movmean")
    axes[1].axhline(1.0, color="gray", ls="--", lw=0.8)
    axes[1].set_ylim(0, 2.5)
    axes[1].set_ylabel("PNs_ch2_raw / ref(t)")
    axes[1].legend(loc="upper right", fontsize=8)

    axes[2].plot(df.index, df["ratio_ch1_smooth"], color="darkred", lw=1.1, label="ch1")
    axes[2].plot(df.index, df["ratio_ch2_smooth"], color="navy", lw=1.1, label="ch2")
    for ev, lbl in EVENT_DATES:
        axes[2].axvline(pd.Timestamp(ev), color="green", ls=":", lw=1)
        axes[2].text(pd.Timestamp(ev), 1.55, lbl, rotation=90, fontsize=7, va="top")
    axes[2].set_ylim(0.3, 1.6)
    axes[2].set_ylabel("24h movmean (both)")
    axes[2].legend(loc="upper right", fontsize=8)

    plt.tight_layout()
    fig_path = os.path.join(DIAG_DIR, "hot_ratio_full_campaign.png")
    plt.savefig(fig_path, dpi=130)
    print(f"saved {fig_path}")


if __name__ == "__main__":
    main()
