#!/usr/bin/env python
"""Table 2 — **한 기저, 한 실행**. 보정 전/후를 같은 마스크로 낸다.

왜 다시 쓰나
------------
`production_budget.py` 의 화면 출력은 계열마다 마스크가 다르다 — ANs 행은
ANs 채널만 수렴한 빈(8505), ΣANs 행은 두 채널 공통(8382). 표 안에서 기저가
섞인다. 실제로 문서 §2(0.0658)와 실행 출력(0.0655)이 그래서 달랐다.

여기서는 **두 채널 공통 + 양쪽 수렴(`ok`)** 하나로 통일한다. ΣANs 가 차분이라
두 채널이 다 있어야 하고, 표가 한 기저여야 하기 때문이다.

게이트 분모도 같은 실행에서 낸다 (`--merged`)
---------------------------------------------
§5 는 게이트를 **셋** 쓴다 — 예산 시계열 · 관측 전체 · 관측(예산과 짝). 이전
판본은 셋이 서로 다른 실행에서 왔고, 그래서 같은 값(예산 시계열)이 문서 안에서
0.0575 와 0.0555 로 두 번 나왔다. 여기서는 **하나의 추정량**

    G = 1.4826 · median|Δ_1h| / √2      (시간평균의 연속차, 인접 시간만)

을 예산 시계열과 관측 시계열에 **똑같이** 적용하고, 시간 수·연속쌍 수를 항상
같이 낸다. 한 시간은 레코드 `--min-per-hour` 개 이상일 때만 센다.

⚠ 병합자료 시각은 KST 다(`--kst-offset-h`, 기본 9). 예산 `sec` 은 알파 축 = UTC.

재현
----
    python tools/table2.py \
        --op  diagnostics/i0_interp_2026-09/production_budget.csv \
        --fix diagnostics/i0_interp_2026-09/production_budget_clockfixed.csv \
        --merged "C:/GHL/2026 yeosu/data analysis/CAESAR_O3_ANs_merged_data_20260831_v4.xlsx"
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

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TERMS = ("i0", "rt", "ef", "tri")
SERIES = (("ANs채널", "a_"), ("PNs채널", "b_"), ("ΣANs", "s_"))


def rsd(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) if v.size else np.nan


def hourly_gate(sec, v, min_n=8):
    """게이트 추정량 `1.4826·median|Δ_1h|/√2` — **한 정의, 모든 계열 공용**.

    반환 dict: gate · hours(시간 id 배열) · n(시간 수) · pairs(연속쌍 수).
    인접하지 않은 시간끼리 차분하면 잡음이 아니라 공백을 잰다 — `diff==1` 만 쓴다.
    """
    sec = np.asarray(sec, float)
    v = np.asarray(v, float)
    m = np.isfinite(sec) & np.isfinite(v)
    sec, v = sec[m], v[m]
    hh = np.floor(sec / 3600.0).astype(np.int64)
    u, inv = np.unique(hh, return_inverse=True)
    cnt = np.bincount(inv)
    hm = np.bincount(inv, weights=v) / np.maximum(cnt, 1)
    keep = cnt >= min_n
    uh, hv = u[keep], hm[keep]
    c = np.diff(uh) == 1 if len(uh) > 1 else np.zeros(0, bool)
    g = (float(1.4826 * np.median(np.abs(np.diff(hv))[c]) / np.sqrt(2.0))
         if c.sum() > 5 else np.nan)
    return dict(gate=g, hours=uh, n=len(uh), pairs=int(c.sum()))


def load(path):
    R = list(csv.DictReader(open(path, encoding="utf-8")))
    g = lambda n: np.array([float(r[n]) for r in R])
    ok = g("ok") > 0.5
    return dict(sec=g("sec")[ok], ok_n=int(ok.sum()), tot=len(R),
                col={pre + t: g(pre + t)[ok] for _, pre in SERIES for t in TERMS},
                ds={t: g("ds_" + t)[ok] for t in TERMS})


def merged_sec(serial, kst_h, epoch_year):
    """엑셀 serial(1899-12-30 기준, KST) → **예산 축** 초(연초 기준 UTC).

    25569 = 1970-01-01 의 엑셀 serial. 예: 46162.5 (2026-05-20 12:00 KST)
    → 12020400 s = day 139.125 = 2026-05-20 03:00 UTC.
    """
    import calendar
    e0 = calendar.timegm((epoch_year, 1, 1, 0, 0, 0))
    return (np.asarray(serial, float) - 25569.0) * 86400.0 - kst_h * 3600.0 - e0


def load_merged(path, kst_h, epoch_year):
    """병합자료 `ans_ppb` → (**예산과 같은 축의** 초, ppb). 관측 게이트의 원천.

    축이 둘 다르다 — 병합은 엑셀 serial(→ Unix epoch), 예산 `sec` 은 **연초
    기준**이다(`day = sec/86400`, 0-based · CLAUDE.md). 시간 id 로 짝짓기
    전에 같은 원점으로 옮긴다. 안 옮기면 교집합이 조용히 0 이 된다.
    """
    sys.path.insert(0, os.path.join(_ROOT, "diagnostics", "gate_ceilings_2026-09"))
    from build_gate_ceilings import _read_xlsx          # 단일 출처 — 사본 만들지 말 것
    rows = _read_xlsx(path)
    hdr = {rows[0][k]: k for k in rows[0]}
    for need in ("time", "ans_ppb"):
        if need not in hdr:
            raise SystemExit("  병합자료에 '%s' 열이 없다" % need)

    def col(n):
        k = hdr[n]
        out = []
        for r in rows[1:]:
            try:
                out.append(float(r.get(k)))
            except (TypeError, ValueError):
                out.append(np.nan)
        return np.asarray(out, float)

    sec = merged_sec(col("time"), kst_h, epoch_year)
    v = col("ans_ppb")
    m = np.isfinite(sec) & np.isfinite(v)
    o = np.argsort(sec[m])
    return sec[m][o], v[m][o]


def table(lab, D, min_n):
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
    G = hourly_gate(D["sec"], D["col"]["s_tri"], min_n)
    return dict(tri=(s_r, s_s), G=G, n=D["ok_n"])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--op", required=True)
    ap.add_argument("--fix", required=True)
    ap.add_argument("--merged", help="병합 xlsx — 관측 게이트 두 개를 여기서 만든다")
    ap.add_argument("--kst-offset-h", type=float, default=9.0,
                    help="병합자료 시각이 UTC 보다 앞선 시간. 예산 sec 은 UTC 다")
    ap.add_argument("--epoch-year", type=int, default=2026,
                    help="예산 sec 의 원점 연도 (day = sec/86400, 0-based)")
    ap.add_argument("--min-per-hour", type=int, default=8,
                    help="한 시간을 세는 최소 레코드 수 — 세 계열에 **같은 값**을 쓴다")
    ap.add_argument("--gate-ppb", type=float, default=0.0832,
                    help="`--merged` 가 없을 때 쓰는 캠페인 게이트 상수(구 판본 호환)")
    ap.add_argument("--reported", type=float, default=0.0806,
                    help="보고 불확도 — 헤드라인 √(보고²+구조²)/보고 의 분모")
    a = ap.parse_args()

    R = {}
    for lab, p in (("보정 전 (운영 R)", a.op), ("보정 후 (시계정렬 R)", a.fix)):
        if not os.path.exists(p):
            print("  없음: %s" % p)
            continue
        R[lab] = table(lab, load(p), a.min_per_hour)

    print()
    print("[게이트 — 분모 셋을 **한 실행에서**]  추정량 G = 1.4826·median|Δ_1h|/√2")
    print("  시간 최소 레코드 %d개 · 인접 시간쌍만 · 예산 축 UTC" % a.min_per_hour)
    print("%-26s %7s %8s %12s" % ("계열", "시간", "연속쌍", "G (ppb)"))
    for lab, r in R.items():
        print("%-26s %7d %8d %12.4f"
              % ("예산 시계열 — " + lab, r["G"]["n"], r["G"]["pairs"], r["G"]["gate"]))

    if a.merged:
        msec, mv = load_merged(a.merged, a.kst_offset_h, a.epoch_year)
        A = hourly_gate(msec, mv, a.min_per_hour)
        g_all = A["gate"]
        print("%-26s %7d %8d %12.4f" % ("관측 전체", A["n"], A["pairs"], g_all))
        hh = np.floor(msec / 3600.0).astype(np.int64)
        for lab, r in R.items():
            keep = np.isin(hh, r["G"]["hours"])       # 예산이 있는 시간만
            B = hourly_gate(msec[keep], mv[keep], a.min_per_hour)
            r["pair"] = B["gate"]
            print("%-26s %7d %8d %12.4f"
                  % ("관측(짝) — " + lab, B["n"], B["pairs"], B["gate"]))
        print("  ⚠ 짝이 예산 시간보다 적으면 그 시간에 관측 레코드가 %d개 미만이다."
              % a.min_per_hour)
    else:
        g_all = a.gate_ppb
        print("%-26s %7s %8s %12.4f   (상수 — `--merged` 를 주면 실측한다)"
              % ("관측 전체", "?", "?", g_all))

    print()
    print("[게이트 세 추정량]  분모를 **매번** 명기한다")
    for lab, r in R.items():
        print("  %s" % lab)
        print("    %-6s %-22s %-30s %8.2f배"
              % ("①", "빈 해상도", "rSD(ΣANs 3중) / 관측 전체", r["tri"][0] / g_all))
        print("    %-6s %-22s %-30s %8.2f배"
              % ("②", "시간평균", "G(예산) / 관측 전체", r["G"]["gate"] / g_all))
        gp = r.get("pair")
        if gp and np.isfinite(gp):
            print("    %-6s %-22s %-30s %8.2f배  ← like-for-like, 본값"
                  % ("③", "짝지은 관측", "G(예산) / G(관측 짝)", r["G"]["gate"] / gp))

    print()
    print("[헤드라인] √(보고² + 구조²) / 보고 · 보고 = %.4f ppb" % a.reported)
    print("%-22s %10s %10s %10s" % ("", "구조 rSD", "구조 SD", "배수 범위"))
    for lab, r in R.items():
        lo = np.sqrt(a.reported ** 2 + r["tri"][0] ** 2) / a.reported
        hi = np.sqrt(a.reported ** 2 + r["tri"][1] ** 2) / a.reported
        print("%-22s %10.4f %10.4f   **%.2f–%.2f배**" % (lab, r["tri"][0], r["tri"][1], lo, hi))


if __name__ == "__main__":
    main()
