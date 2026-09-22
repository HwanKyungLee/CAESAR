#!/usr/bin/env python
"""Table 2 — **한 기저, 한 실행**. 보정 전/후를 같은 마스크로 낸다.

왜 다시 쓰나
------------
`production_budget.py` 의 화면 출력은 계열마다 마스크가 다르다 — ANs 행은
ANs 채널만 수렴한 빈(8505), ΣANs 행은 두 채널 공통(8382). 표 안에서 기저가
섞인다. 실제로 문서 §2(0.0658)와 실행 출력(0.0655)이 그래서 달랐다.

여기서는 **두 채널 공통 + 양쪽 수렴(`ok`)** 하나로 통일한다. ΣANs 가 차분이라
두 채널이 다 있어야 하고, 표가 한 기저여야 하기 때문이다.

기저 규약
---------
행 단위는 **ambient 60 s 빈** 이고 그것이 곧 산출물 레코드다(알파 한 행).
`n` 은 항상 명기한다.

재현
----
    python tools/table2.py \
        --op  diagnostics/i0_interp_2026-09/production_budget.csv \
        --fix diagnostics/i0_interp_2026-09/production_budget_clockfixed.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

TERMS = ("i0", "rt", "ef", "tri")
SERIES = (("ANs채널", "a_"), ("PNs채널", "b_"), ("ΣANs", "s_"))


def rsd(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) if v.size else np.nan


def load(path):
    R = list(csv.DictReader(open(path, encoding="utf-8")))
    g = lambda n: np.array([float(r[n]) for r in R])
    ok = g("ok") > 0.5
    return dict(sec=g("sec")[ok], ok_n=int(ok.sum()), tot=len(R),
                col={pre + t: g(pre + t)[ok] for _, pre in SERIES for t in TERMS},
                ds={t: g("ds_" + t)[ok] for t in TERMS})


def table(lab, D, gate_ppb):
    print()
    print("[%s]  기저: 두 채널 공통 + 양쪽 수렴 · **n = %d** (공통 %d 중)"
          % (lab, D["ok_n"], D["tot"]))
    print("%-9s %-5s %10s %10s %8s" % ("계열", "항", "rSD(ppb)", "SD(ppb)", "s=rSD/SD"))
    out = {}
    for nm, pre in SERIES:
        for t in TERMS:
            v = D["col"][pre + t]
            r, sd = rsd(v), float(np.std(v, ddof=1))
            out[(nm, t)] = (r, sd)
            print("%-9s %-5s %10.4f %10.4f %8.3f"
                  % (nm if t == "i0" else "", t, r, sd, r / sd if sd else np.nan))
        qr = np.sqrt(sum(out[(nm, t)][0] ** 2 for t in TERMS[:3]))
        qs = np.sqrt(sum(out[(nm, t)][1] ** 2 for t in TERMS[:3]))
        tr, ts = out[(nm, "tri")]
        print("%-9s %-5s %10.4f %10.4f   3중/제곱합  rSD %.3f · SD %.3f"
              % ("", "제곱합", qr, qs, tr / qr, ts / qs))
    s_r, s_s = out[("ΣANs", "tri")]
    print("  **ΣANs 3중 rSD %.4f · SD %.4f**" % (s_r, s_s))
    print("  [게이트] 추정량 이름을 명기한다")
    print("    ① 빈 해상도 rSD / 캠페인 게이트(%.4f) = **%.2f배**" % (gate_ppb, s_r / gate_ppb))
    hh = np.floor(D["sec"] / 3600.0).astype(np.int64)
    u, inv = np.unique(hh, return_inverse=True)
    cnt = np.bincount(inv)
    hm = np.bincount(inv, weights=D["col"]["s_tri"]) / np.maximum(cnt, 1)
    keep = cnt >= 8
    uh, hv = u[keep], hm[keep]
    cons = np.diff(uh) == 1
    ge = np.nan
    if cons.sum() > 10:
        ge = float(1.4826 * np.median(np.abs(np.diff(hv))[cons]) / np.sqrt(2))
        print("    ② 시간평균 게이트추정량 1.4826·median|Δ_1h|/√2 = %.4f ppb"
              " → 캠페인 게이트 대비 **%.2f배** (시간 %d · 연속쌍 %d)"
              % (ge, ge / gate_ppb, len(uh), int(cons.sum())))
    # §5 Δshift 층화 — 레코드 비율과 분산 비율 둘 다
    print("  [§5 Δshift 층화] 레코드 비율과 분산 비율을 **둘 다** 낸다")
    dt, vt = D["ds"]["tri"], D["col"]["s_tri"]
    tot = float(np.sum((vt - np.median(vt)) ** 2))
    for lo, hi, nm in ((0.0, 0.1, "<0.1 px"), (0.1, 1.0, "0.1–1 px"), (1.0, np.inf, "≥1 px")):
        m = (np.abs(dt) >= lo) & (np.abs(dt) < hi)
        cv = float(np.sum((vt[m] - np.median(vt)) ** 2)) if m.sum() else 0.0
        print("    %-9s 레코드 %6.2f %% · 분산 %6.2f %% · rSD %.4f"
              % (nm, 100 * m.mean(), 100 * cv / max(tot, 1e-30),
                 rsd(vt[m]) if m.sum() > 2 else np.nan))
    return dict(tri=(s_r, s_s), gate1=s_r / gate_ppb, ge=ge, uh=uh, hv=hv, n=D["ok_n"])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--op", required=True)
    ap.add_argument("--fix", required=True)
    ap.add_argument("--gate-ppb", type=float, default=0.0832,
                    help="캠페인 관측 게이트(1.4826·median|Δ_1h|/√2, 전 캠페인)")
    ap.add_argument("--reported", type=float, default=0.0806,
                    help="보고 불확도 — 헤드라인 √(보고²+구조²)/보고 의 분모")
    a = ap.parse_args()

    R = {}
    for lab, p in (("보정 전 (운영 R)", a.op), ("보정 후 (시계정렬 R)", a.fix)):
        if not os.path.exists(p):
            print("  없음: %s" % p)
            continue
        R[lab] = table(lab, load(p), a.gate_ppb)

    print()
    print("[헤드라인] √(보고² + 구조²) / 보고 · 보고 = %.4f ppb" % a.reported)
    print("%-22s %10s %10s %10s" % ("", "구조 rSD", "구조 SD", "배수 범위"))
    for lab, r in R.items():
        lo = np.sqrt(a.reported ** 2 + r["tri"][0] ** 2) / a.reported
        hi = np.sqrt(a.reported ** 2 + r["tri"][1] ** 2) / a.reported
        print("%-22s %10.4f %10.4f   **%.2f–%.2f배**" % (lab, r["tri"][0], r["tri"][1], lo, hi))


if __name__ == "__main__":
    main()
