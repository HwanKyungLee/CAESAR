#!/usr/bin/env python
"""§7.2 현장 성능 — hot 채널 NO₂ 의 **실측 정밀도**와 검출한계.

무엇을 재나
-----------
보고 불확도(`<gas>_Error` = 조건부 선형 `perr`)가 실제 산포와 얼마나 다른가.
이 저장소의 앞선 실측은 perr 이 3.4~4.4배 과소평가라고 했다 — 여기서는 같은
질문을 **산출물 시계열 위에서** 한 기저로 다시 낸다.

추정량
------
    σ̂ = 1.4826 · median|Δ| / √2      (연속 레코드 차의 robust scale)

`√2` 는 두 독립 측정의 차가 √2 배 넓어지기 때문이다. 이 값은 **정밀도의
상한**이다 — 60 s 레코드 사이에는 실제 대기 변동도 들어 있다. 그래서
  * 60 s 레코드 기준(대기 변동 포함 = 상한)
  * 1 시간 평균의 연속차 — 이건 **정밀도가 아니라 대기 변동**이다(실측 0.4 ppb
    대). 정밀도 칸과 나란히 두되 이름을 그렇게 붙인다.
  * **조용한 시간대만**(|Δ| 하위 사분위 시간) — 상한을 더 조인 값
셋을 같이 낸다. 검출한계는 관례대로 `MDL = 3σ̂` 다.

기저
----
`production_budget*.csv` 의 `n2_a`(ANs 채널 NO₂) · `n2_b`(PNs 채널) 와
`ok`(두 채널 수렴) 를 쓴다. Table 2 와 **같은 기저**다(`tools/table2.py`).

재현
----
    python tools/field_performance.py \
        --csv diagnostics/i0_interp_2026-09/production_budget_clockfixed.csv \
        --perr-ans 0.0356 --perr-pns 0.0433
"""
from __future__ import annotations

import argparse
import csv
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass


def sigma_from_pairs(v):
    """연속쌍 차의 robust scale → 단일 측정 σ̂."""
    d = np.diff(v)
    d = d[np.isfinite(d)]
    if d.size < 5:
        return np.nan
    return float(1.4826 * np.median(np.abs(d)) / np.sqrt(2.0))


def runs(sec, max_gap_s=180.0):
    """연속 구간으로 쪼갠다 — 갭을 넘어 차분하면 대기 변동을 잡음으로 센다."""
    out, cur = [], [0]
    for i in range(1, len(sec)):
        if sec[i] - sec[i - 1] <= max_gap_s:
            cur.append(i)
        else:
            out.append(cur)
            cur = [i]
    out.append(cur)
    return [r for r in out if len(r) > 2]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--perr-ans", type=float, required=True,
                    help="ANs 채널 보고 σ 중앙 (ppb)")
    ap.add_argument("--perr-pns", type=float, required=True)
    a = ap.parse_args()

    R = list(csv.DictReader(open(a.csv, encoding="utf-8")))
    g = lambda n: np.array([float(r[n]) for r in R])
    ok = g("ok") > 0.5
    sec = g("sec")[ok]
    o = np.argsort(sec)
    sec = sec[o]
    ser = {"ANs채널": g("n2_a")[ok][o], "PNs채널": g("n2_b")[ok][o]}
    rep = {"ANs채널": a.perr_ans, "PNs채널": a.perr_pns}

    print("§7.2 현장 성능 — 기저: %s · n = %d" % (a.csv.split("/")[-1], ok.sum()))
    print("  추정량 σ̂ = 1.4826·median|Δ|/√2 (연속쌍). 대기 변동 포함 = **상한**")
    print()
    print("%-9s %9s %11s %11s %11s %9s %9s"
          % ("채널", "중앙 NO₂", "σ̂ 60s", "1h차(대기)", "σ̂ 조용시간", "보고 σ", "60s/보고"))
    for nm, v in ser.items():
        rr = runs(sec)
        s60 = np.nanmedian([sigma_from_pairs(v[r]) for r in rr if len(r) > 5])
        hh = np.floor(sec / 3600.0).astype(np.int64)
        u, inv = np.unique(hh, return_inverse=True)
        cnt = np.bincount(inv)
        hm = np.bincount(inv, weights=v) / np.maximum(cnt, 1)
        keep = cnt >= 8
        uh, hv = u[keep], hm[keep]
        c = np.diff(uh) == 1
        s1h = (float(1.4826 * np.median(np.abs(np.diff(hv))[c]) / np.sqrt(2))
               if c.sum() > 5 else np.nan)
        # 조용한 시간: 시간별 σ̂ 의 하위 사분위
        per_h = []
        for i, h in enumerate(u):
            m = inv == i
            if m.sum() > 8:
                per_h.append(sigma_from_pairs(v[m]))
        per_h = np.asarray([x for x in per_h if np.isfinite(x)], float)
        sq = float(np.percentile(per_h, 25)) if per_h.size else np.nan
        print("%-9s %9.3f %11.4f %11.4f %11.4f %9.4f %9.2f배"
              % (nm, np.median(v), s60, s1h, sq, rep[nm], s60 / rep[nm]))

    print()
    print("[검출한계]  MDL = 3σ̂ — 보고 σ 기반과 실측 기반을 **나란히**")
    print("%-9s %14s %14s %9s" % ("채널", "3×보고σ", "3×σ̂(조용시간)", "비"))
    for nm, v in ser.items():
        per_h = []
        hh = np.floor(sec / 3600.0).astype(np.int64)
        u, inv = np.unique(hh, return_inverse=True)
        for i in range(len(u)):
            m = inv == i
            if m.sum() > 8:
                per_h.append(sigma_from_pairs(v[m]))
        per_h = np.asarray([x for x in per_h if np.isfinite(x)], float)
        sq = float(np.percentile(per_h, 25))
        print("%-9s %14.4f %14.4f %9.2f배"
              % (nm, 3 * rep[nm], 3 * sq, sq / rep[nm]))
    print()
    print("  ⚠ σ̂ 는 대기 변동을 포함하므로 **정밀도의 상한**이고 비도 상한이다.")
    print("     `1h차` 열은 정밀도가 아니라 **대기 변동**이다(0.4 ppb 대) — 시간")
    print("     평균의 연속차는 잡음이 아니라 실제 농도 변화를 잰다.")
    print("     이 저장소의 앞선 실측(perr 3.4~4.4배 과소평가)은 **다른 기저**다 —")
    print("     그쪽은 제로에어 기반이고 여기는 ambient lag-1 상한이다. 가장 깨끗한")
    print("     §7.2 수치는 raw 의 제로에어 행을 ambient 처럼 핏해야 나온다")
    print("     (알파 산물에는 제로에어 행이 없다).")


if __name__ == "__main__":
    main()
