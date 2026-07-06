# -*- coding: utf-8 -*-
"""tools/qc_false_removal.py — QC 오제거율(false-removal) 측정 [규칙 R8]
==========================================================================
"필터를 믿기 전에, 깨끗한 데이터를 몇 % 잘못 빼는지 먼저 재라."

방법
----
QCoff 핏출력(모든 값 보존)에 실제 QC식(core.result_io.robust_rms_thresholds)을
그대로 적용해 '제거될 스캔'을 구한다. 그리고 **시간적으로 안정한(=확실히 좋은)**
스캔을 독립 기준으로 정의해, 그중 QC가 몇 %를 제거하는지 측정한다.

왜 '시간 안정'이 독립 기준인가: 대기 미량기체는 분 단위로 부드럽게 변한다. 한
스캔의 NO2가 좌우 이웃들과 일치하면 그건 신뢰할 수 있는 측정이다(핏 RMS와 무관한
독립 신호). 이런 스캔을 QC가 빼면 = false removal. 빠르게 변하는 구간(플룸 경계)은
'확실히 좋다'고 못 하므로 기준집합에서 빠진다(보수적).

핵심 출력
---------
* QC가 제거하는 비율
* 그중 '이웃과 일치(=괜찮아 보임)'였던 비율  → 잠재적 false removal
* 확실히-좋은 집합 대비 false-removal 율 (이게 R8 핵심 숫자)
여러 K(4/6/8)에서 트레이드오프를 보여준다.
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

# 측정할 QCoff 핏출력 (모든 값 보존된 버전)
QCOFF = r"C:\Doasis_Work\Output\fitting\260517-260618\neg_o\QCoff\260517-260618_cold_438-476nm_Poly4_ShLink.dat"
SPECIES = "NO2"
WIN = 10           # 이웃 창 (±WIN 스캔). 60s 평균이라 ±10분쯤.
CONSIST_K = 2.0    # 이웃 robust 산포의 몇 배 안이면 '일치(좋음)'로 볼지


def load(path, sp):
    lines = [l.rstrip("\n") for l in open(path, encoding="utf-8", errors="replace")]
    hi = next(i for i, l in enumerate(lines) if l.strip() and not l.startswith("#"))
    hdr = lines[hi].split("\t")
    iV, iR = hdr.index(sp), hdr.index("RMS")
    iE = hdr.index(sp + "_Error") if sp + "_Error" in hdr else None
    val, rms, err = [], [], []
    for l in lines[hi + 1:]:
        if not l.strip() or l.startswith("#"):
            continue
        p = l.split("\t")
        def f(i):
            try:
                return float(p[i])
            except Exception:
                return np.nan
        val.append(f(iV)); rms.append(f(iR)); err.append(f(iE) if iE is not None else np.nan)
    return np.array(val), np.array(rms), np.array(err)


def local_consistent(val, win, k):
    """각 스캔이 이웃(±win)의 robust 밴드 안인가 → '시간적으로 안정(좋음)' 마스크.
    이웃 중앙값/MAD는 자기 자신 제외하고 계산(자기참조 방지)."""
    n = len(val)
    ok = np.zeros(n, dtype=bool)
    finite = np.isfinite(val)
    for i in range(n):
        if not finite[i]:
            continue
        s, e = max(0, i - win), min(n, i + win + 1)
        nb = val[s:e].copy()
        nb = np.delete(nb, min(i - s, len(nb) - 1))   # 자기 제외
        nb = nb[np.isfinite(nb)]
        if len(nb) < max(4, win):
            continue
        med = np.median(nb)
        mad = np.median(np.abs(nb - med)) * 1.4826 + 1e-9
        ok[i] = abs(val[i] - med) <= k * mad
    return ok


def main():
    if not os.path.exists(QCOFF):
        print(f"QCoff 파일 없음: {QCOFF}"); return
    val, rms, err = load(QCOFF, SPECIES)
    n = len(val)
    print("=" * 66)
    print(f" QC 오제거율 측정 (R8)  —  {SPECIES}, {n} 스캔")
    print("=" * 66)

    # 독립 기준: 시간적으로 안정 AND 물리적으로 말 되는 값 = 확실히 좋은 스캔.
    # (물리 게이트 없으면 흐린날 '불량 군집'이 자기들끼리 일치해 '좋음'으로 새 들어온다.)
    PHYS = np.abs(val) < 50.0    # NO2 |값|<50ppb (해양; 노이즈성 약음수는 허용)
    good = local_consistent(val, WIN, CONSIST_K) & PHYS
    print(f" 확실히-좋은(이웃과 일치 AND |NO2|<50ppb) 스캔: {good.sum()} / {n}  ({good.mean()*100:.0f}%)")
    print(f"   (나머지는 빠른변동/결측/물리불가 — '확실히 좋다'고 못 해 제외)\n")

    print(f" {'K':>4} | {'QC제거':>8} | {'제거중 일치(괜찮아보임)':>22} | {'확실히좋은것의 오제거율':>22}")
    print(" " + "-" * 64)
    for K in (4.0, 6.0, 8.0, 10.0):
        thr = robust_rms_thresholds(rms, channels=None, K=K)
        # channels=None 이면 함수가 키 0 으로 한 그룹 반환 — 값 하나를 꺼낸다.
        t = next(iter(thr.values()), np.inf) if thr else np.inf
        removed = np.isfinite(rms) & (rms > t)          # QC가 빼는 스캔
        n_rem = int(removed.sum())
        # 제거된 것 중 '이웃과 일치'였던 비율 = 잠재 false removal
        rem_good = int((removed & good).sum())
        frac_rem_good = rem_good / n_rem * 100 if n_rem else 0.0
        # 확실히-좋은 집합 대비 오제거율 (R8 핵심)
        fr_rate = (removed & good).sum() / max(good.sum(), 1) * 100
        print(f" {K:>4.0f} | {n_rem:>5} ({n_rem/n*100:4.1f}%) | "
              f"{rem_good:>5} ({frac_rem_good:4.1f}%){'':>9} | {fr_rate:>6.2f}%")

    # ── 핵심: 오제거가 '무작위'냐 '편향'이냐 (운용 K=6 기준) ──────────────────
    # 무작위면 N만 줄지만, 편향(예: 고농도 이벤트를 골라 뺌)이면 결과가 틀어진다.
    K = 6.0
    thr = robust_rms_thresholds(rms, channels=None, K=K)
    t = next(iter(thr.values()), np.inf)
    removed = np.isfinite(rms) & (rms > t)
    gr = good & removed     # 확실히 좋은데 제거됨
    gk = good & ~removed    # 확실히 좋고 유지됨
    print()
    print(f" ── K=6 오제거의 편향 검사 (가장 중요) ──")
    print(f"   확실히-좋은데 제거된 {gr.sum()}개  vs  유지된 {gk.sum()}개의 NO2 분포:")
    print(f"     제거된 것 : 중앙 {np.median(val[gr]):.2f}  평균 {np.mean(val[gr]):.2f} ppb")
    print(f"     유지된 것 : 중앙 {np.median(val[gk]):.2f}  평균 {np.mean(val[gk]):.2f} ppb")
    d_mean = np.mean(val[gr]) - np.mean(val[gk])
    # 전체(제거전) 평균 vs QC후 평균 — QC가 보고농도를 얼마나 옮기나
    all_good_mean = np.mean(val[good])
    kept_mean = np.mean(val[gk])
    print(f"   → 제거-유지 평균차 = {d_mean:+.2f} ppb "
          f"({'고농도를 골라 뺌=편향!' if abs(d_mean)>0.3 else '거의 무작위=편향 작음'})")
    print(f"   → QC가 평균 NO2를 {all_good_mean:.3f} → {kept_mean:.3f} ppb 로 "
          f"{(kept_mean-all_good_mean)/all_good_mean*100:+.1f}% 이동")
    print()
    print(" 해석:")
    print("  · 오제거율 11%여도, 그게 '무작위'면 N만 줄고 평균은 안 변함(편향 작음).")
    print("  · 평균차/이동%가 크면 → QC가 특정 농도대를 골라 빼는 것 = 진짜 문제(편향).")
    print("  · 이 숫자를 보고 K(또는 RMS기반 QC 자체)를 유지/완화/교체 결정.")


if __name__ == "__main__":
    main()
