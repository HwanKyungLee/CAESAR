# -*- coding: utf-8 -*-
"""tools/qc_false_removal_xch.py — QC 오제거율 [R8] 정밀판: 채널교차 진실기준
=============================================================================
qc_false_removal.py 는 '시간일치'를 '좋음' 기준으로 썼는데, 흐린날 불량군집이
자기들끼리 일치해 속을 수 있다. 여기서는 **독립 분광기 둘의 일치**를 기준으로 쓴다:
핫 CH1(PNs)·CH2(ANs)는 같은 장비라 행이 정렬돼 있고 NO2가 r=0.99로 일치한다.
두 독립 채널이 *우연히 같은 틀린 값*을 낼 확률은 0 → 가장 견고한 '좋음' 정의.

한 핫 스캔이 '확실히 좋음' = CH1·CH2 NO2가 (그 둘의 정상 차이 부근에서) 일치.
이 집합을 QC(RMS, K=6)가 몇 % 빼는지, 그리고 그 제거가 농도를 편향시키는지 잰다.
"""
from __future__ import annotations
import os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from core.result_io import robust_rms_thresholds

D = r"C:\Doasis_Work\Output\fitting\260517-260618\neg_o\QCoff"
F1 = os.path.join(D, "260517-260618_CH1_430-462nm_Poly4_ShLink.dat")
F2 = os.path.join(D, "260517-260618_CH2_444-471nm_Poly3_ShLink.dat")


def load(fn):
    lines = [l.rstrip("\n") for l in open(fn, encoding="utf-8", errors="replace")]
    hi = next(i for i, l in enumerate(lines) if l.strip() and not l.startswith("#"))
    hdr = lines[hi].split("\t")
    iN, iR = hdr.index("NO2"), hdr.index("RMS")
    no2, rms = [], []
    for l in lines[hi + 1:]:
        if not l.strip() or l.startswith("#"):
            continue
        p = l.split("\t")
        def f(i):
            try:
                return float(p[i])
            except Exception:
                return np.nan
        no2.append(f(iN)); rms.append(f(iR))
    return np.array(no2), np.array(rms)


def removed_mask(rms, K):
    thr = robust_rms_thresholds(rms, channels=None, K=K)
    t = next(iter(thr.values()), np.inf) if thr else np.inf
    return np.isfinite(rms) & (rms > t), t


def main():
    n1, r1 = load(F1)
    n2, r2 = load(F2)
    n = min(len(n1), len(n2))
    n1, r1, n2, r2 = n1[:n], r1[:n], n2[:n], r2[:n]

    # 두 채널 일치 기준: 차이가 '정상 차이(중앙값)' 부근인가 (CH1·CH2는 측정대상이
    # 조금 달라 일정 offset 있음 → 0이 아니라 median 중심으로 본다).
    diff = n1 - n2
    fin = np.isfinite(diff)
    md = np.median(diff[fin]); mad = np.median(np.abs(diff[fin] - md)) * 1.4826 + 1e-9
    agree = fin & (np.abs(diff - md) < 2.0 * mad)
    phys = (np.abs(n1) < 50) & (np.abs(n2) < 50)
    good = agree & phys     # 두 독립채널이 일치 + 물리적 = 확실히 좋음

    print("=" * 66)
    print(" QC 오제거율 [R8] — 채널교차(CH1↔CH2) 진실기준")
    print("=" * 66)
    r = np.corrcoef(n1[good], n2[good])[0, 1]
    print(f" 행 {n}개, CH1·CH2 정상차이 median={md:+.2f} 산포(MAD)={mad:.2f} ppb")
    print(f" 확실히-좋은(두 채널 일치 AND |NO2|<50) 스캔: {good.sum()} ({good.mean()*100:.0f}%), 그 구간 r={r:.3f}\n")

    print(f" {'K':>4} | {'CH1 좋은것 오제거율':>16} | {'CH2 좋은것 오제거율':>16}")
    print(" " + "-" * 44)
    for K in (4.0, 6.0, 8.0, 10.0):
        rm1, _ = removed_mask(r1, K)
        rm2, _ = removed_mask(r2, K)
        fr1 = (good & rm1).sum() / max(good.sum(), 1) * 100
        fr2 = (good & rm2).sum() / max(good.sum(), 1) * 100
        print(f" {K:>4.0f} | {fr1:>14.2f}% | {fr2:>14.2f}%")

    # K=6 편향검사
    print(f"\n ── K=6 편향검사 (확실히-좋은 집합에서) ──")
    for tag, no2, rms in [("CH1", n1, r1), ("CH2", n2, r2)]:
        rm, _ = removed_mask(rms, 6.0)
        gr = good & rm; gk = good & ~rm
        if gr.sum() == 0:
            print(f"  {tag}: 제거 0"); continue
        print(f"  {tag}: 제거된 좋은것 {gr.sum()}개 중앙 {np.median(no2[gr]):.2f}/평균 {np.mean(no2[gr]):.2f}  "
              f"vs 유지 중앙 {np.median(no2[gk]):.2f}/평균 {np.mean(no2[gk]):.2f} ppb")
        shift = (np.mean(no2[gk]) - np.mean(no2[good])) / abs(np.mean(no2[good]) + 1e-9) * 100
        print(f"        → QC가 평균을 {np.mean(no2[good]):.3f}→{np.mean(no2[gk]):.3f} ({shift:+.1f}%) 이동")
    print("\n 이게 가장 견고한 R8 숫자다 (두 독립 분광기가 보증한 '좋음' 기준).")


if __name__ == "__main__":
    main()
