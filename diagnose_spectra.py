"""
diagnose_spectra.py — 플래그별 스펙트럼 강도를 비교해 올바른 ZA/He 플래그를 판별합니다.

사용법:
    python diagnose_spectra.py "H:\Yeosu_2026\CAESAR_Cold\2026-05"
"""
import os, sys, glob
import numpy as np
from collections import defaultdict

SPECTRUM_SLICE = slice(2053, 4101)   # ROI 2 (현재 코드가 사용하는 구간)
ROI1_SLICE     = slice(5, 2053)      # ROI 1
ROI3_SLICE     = slice(4101, 6149)   # ROI 3
FLAGS_OF_INTEREST = {"500", "501", "502", "503", "510", "512", "513", "1", "0"}
MAX_SAMPLES = 50   # 플래그당 최대 샘플 수

def diagnose(directory):
    files = sorted(glob.glob(os.path.join(directory, "*.dat")))[:10]  # 앞 10개 파일만
    if not files:
        print(f"[오류] .dat 파일 없음: {directory}"); return

    buckets = defaultdict(list)   # flag → list of (roi1_mean, roi2_mean, roi3_mean)

    for fp in files:
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                tokens = line.strip().split("\t")
                if len(tokens) < 6175: continue
                flag = tokens[4].strip()
                if flag not in FLAGS_OF_INTEREST: continue
                if len(buckets[flag]) >= MAX_SAMPLES: continue
                try:
                    raw = np.array(tokens, dtype=float)
                    r1 = np.nanmean(raw[ROI1_SLICE])
                    r2 = np.nanmean(raw[SPECTRUM_SLICE])
                    r3 = np.nanmean(raw[ROI3_SLICE])
                    buckets[flag].append((r1, r2, r3))
                except:
                    pass

    print(f"\n파일 {len(files)}개 기준 플래그별 평균 스펙트럼 강도")
    print(f"{'플래그':>6}  {'샘플수':>5}  {'ROI1 평균':>12}  {'ROI2 평균(현재)':>14}  {'ROI3 평균':>12}  추정역할")
    print("-" * 80)

    order = sorted(buckets.keys(), key=lambda x: int(x) if x.isdigit() else 999)
    for flag in order:
        rows = buckets[flag]
        if not rows: continue
        r1 = np.mean([r[0] for r in rows])
        r2 = np.mean([r[1] for r in rows])
        r3 = np.mean([r[2] for r in rows])
        n  = len(rows)

        role = ""
        if flag == "1":   role = "일반 측정"
        elif flag == "0": role = "초기화/비정상"
        elif flag in ("500","502","503"): role = "ZA 계열"
        elif flag in ("510","512","513"): role = "He 계열"

        print(f"  {flag:>4}   {n:>5}   {r1:>12.1f}   {r2:>14.1f}   {r3:>12.1f}  {role}")

    print()
    print("▶ 강도가 가장 높은 ZA/He 플래그 = 광원 ON 상태의 실제 신호 스캔")
    print("▶ 강도가 낮은 플래그              = 다크(광원 OFF) 또는 대기 스캔")

    # ZA/He 각각 최고 강도 플래그 추천
    za_flags = {k: np.mean([r[1] for r in v]) for k, v in buckets.items()
                if k in ("500","501","502","503") and v}
    he_flags = {k: np.mean([r[1] for r in v]) for k, v in buckets.items()
                if k in ("510","512","513") and v}

    if za_flags:
        best_za = max(za_flags, key=za_flags.get)
        print(f"\n  추천 FLAG_ZA = {best_za}  (ROI2 평균강도: {za_flags[best_za]:.1f})")
        for k, v in sorted(za_flags.items()):
            print(f"    ZA {k}: {v:.1f}")
    if he_flags:
        best_he = max(he_flags, key=he_flags.get)
        print(f"  추천 FLAG_HE = {best_he}  (ROI2 평균강도: {he_flags[best_he]:.1f})")
        for k, v in sorted(he_flags.items()):
            print(f"    He {k}: {v:.1f}")

if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else "."
    diagnose(directory)
