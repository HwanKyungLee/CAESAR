#!/usr/bin/env python
"""`[TBD-7D]` 산출물 ΣANs 보고 불확도(0.0806 ppb)의 **출처**를 잰다.

왜 이게 최우선인가
------------------
§4 헤드라인 `√(보고² + 구조²)/보고` 의 **분모**이고 초록의 머리 숫자다. 그런데
제품 보고 열이 채널 핏 σ 의 제곱합보다 1.48배 크다(2026-09-22 실측). 그 1.48
배가 무엇인지 모르면 헤드라인이 무엇 대비 몇 배인지도 모르는 것이다.

무엇을 대조하나
--------------
* 산출물 `ANs_unc_ppb` (NIER 제출본 / 병합 v4)
* 같은 시각 두 채널 핏의 **레코드별** 전파 σ — `√(σ₁²/N₁ + g²·σ₂²/N₂)`
  (5분 평균이므로 스캔 수로 나눈다. 안 나누면 평균의 σ 가 아니다)
* 산출물 헤더가 주장하는 식 — `0.04 × NO2`

중앙값끼리 비교하면 치우친 분포에서 인공물이 난다. **레코드별로 짝지어** 비를
분포로 낸다.

재현
----
    python tools/reported_sigma_provenance.py \
        --ans "<...ANs_...merge54....dat>" --pns "<...PNs_...merge54....dat>" \
        --product "<...GIST_CAESAR_ANs_5min_KST_....csv>"
"""
from __future__ import annotations

import argparse
import calendar
import csv
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

BIN_S = 300.0                      # 산출물은 5분 평균이다


def load_fit(path, cols=("Time", "NO2", "NO2_Error", "Chi2")):
    """핏 산물 .dat → dict of arrays. 헤더행은 `File\\tChannel\\tTime…` 로 시작한다."""
    idx = None
    out = {c: [] for c in cols}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            if idx is None:
                if "Time" not in f:
                    continue
                idx = {c: f.index(c) for c in cols}
                continue
            try:
                for c in cols:
                    v = f[idx[c]]
                    out[c].append(v if c == "Time" else float(v))
            except (IndexError, ValueError):
                for c in cols:                       # 길이를 다시 맞춘다
                    if len(out[c]) > len(out["Time"]) - 1:
                        pass
                continue
    t = np.array([_sec(s) for s in out["Time"]], float)
    d = {c: np.asarray(out[c], float) for c in cols if c != "Time"}
    d["sec"] = t
    return d


def _sec(s):
    """`YYYY-MM-DD HH:MM:SS` (UTC) → Unix 초."""
    try:
        d, tm = s.split(" ")
        y, mo, da = (int(x) for x in d.split("-"))
        h, mi, se = (int(float(x)) for x in tm.split(":"))
        return float(calendar.timegm((y, mo, da, h, mi, se)))
    except Exception:
        return np.nan


def bin5(d, chi2_max=10.0):
    """5분 격자로 묶는다 — 산출물과 같은 해상도.

    평균의 σ 는 `mean(σ)/√N` 이다. 스캔별 σ 를 그대로 쓰면 N 배 과대평가한다.
    QC 는 산출물과 같게 `Chi2 < 10`.
    """
    m = np.isfinite(d["sec"]) & np.isfinite(d["NO2"]) & np.isfinite(d["NO2_Error"])
    m &= d["Chi2"] < chi2_max
    b = np.floor(d["sec"][m] / BIN_S).astype(np.int64)
    u, inv = np.unique(b, return_inverse=True)
    n = np.bincount(inv).astype(float)
    no2 = np.bincount(inv, weights=d["NO2"][m]) / n
    sig = np.bincount(inv, weights=d["NO2_Error"][m]) / n / np.sqrt(n)
    sd = np.sqrt(np.maximum(
        np.bincount(inv, weights=d["NO2"][m] ** 2) / n - no2 ** 2, 0.0)) / np.sqrt(n)
    return dict(bin=u, n=n, no2=no2, sig=sig, sem=sd)


def load_product(path, kst_h=9.0):
    rows = [l for l in open(path, encoding="utf-8-sig") if not l.startswith("#")]
    R = list(csv.DictReader(rows))
    key = "ANs_unc_ppb" if "ANs_unc_ppb" in R[0] else "ans_unc_ppb"
    ak = "ANs_ppb" if "ANs_ppb" in R[0] else "ans_ppb"
    tk = "datetime_KST" if "datetime_KST" in R[0] else "time"
    sec, unc, ans = [], [], []
    for r in R:
        s = _sec(r[tk])
        if not np.isfinite(s):
            continue
        try:
            unc.append(float(r[key]))
            ans.append(float(r[ak]))
        except (TypeError, ValueError):
            continue
        sec.append(s - kst_h * 3600.0)               # KST → UTC
    return (np.asarray(sec, float), np.asarray(ans, float), np.asarray(unc, float))


def q(v, lab):
    v = v[np.isfinite(v)]
    if not v.size:
        return "%-22s (없음)" % lab
    return ("%-22s 중앙 %8.4f · p05 %8.4f · p25 %8.4f · p75 %8.4f · p95 %8.4f"
            % (lab, np.median(v), *np.percentile(v, (5, 25, 75, 95))))


def tbd4d(a, prod_bin, sig_scan, prod_unc):
    """`[TBD-4D]` 레코드별 구조항 ÷ **그 레코드의** 보고 σ.

    지금 §4 의 "42 %" 와 "1.03–2.65" 는 구조항을 **상수로 놓은** 지시값이다.
    둘 다 레코드마다 다르므로 짝지어 재야 분포가 나온다.

    구조항은 60 s 예산 빈, 보고 σ 는 5 분빈에서 온 **스캔 단위** 값이다 —
    5 분빈 하나가 60 s 빈 다섯을 덮으므로 그 빈의 값을 그대로 쓴다.
    """
    R = list(csv.DictReader(open(a.budget, encoding="utf-8")))
    g = lambda n: np.array([float(r[n]) for r in R])
    ok = g("ok") > 0.5
    e0 = calendar.timegm((a.epoch_year, 1, 1, 0, 0, 0))
    bsec = g("sec")[ok] + e0
    tri = g("s_tri")[ok]
    bb = np.floor(bsec / BIN_S).astype(np.int64)
    look = {int(b): i for i, b in enumerate(prod_bin)}
    j = np.array([look.get(int(x), -1) for x in bb])
    m = j >= 0
    if m.sum() < 100:
        print()
        print("  [TBD-4D] 예산 창과 산출물이 %d 빈밖에 안 겹친다 — 생략" % m.sum())
        return
    s_fit, s_prod = sig_scan[j[m]], prod_unc[j[m]]
    t = np.abs(tri[m])
    print()
    print("  [TBD-4D] 레코드별 짝지은 비 — 예산 빈 %d 중 산출물과 짝 **%d**"
          % (len(tri), int(m.sum())))
    print("  %-30s %9s %9s %9s %9s %9s"
          % ("비", "중앙", "p05", "p25", "p75", "p95"))
    for lab, d in (("|구조 3중| / 핏 σ(스캔)", s_fit),
                   ("|구조 3중| / 산출물 unc", s_prod)):
        r = t / d
        print("  %-30s %9.3f %9.3f %9.3f %9.3f %9.3f"
              % (lab, np.median(r), *np.percentile(r, (5, 25, 75, 95))))
        print("     구조 > 보고 인 레코드 **%.1f %%**" % (100 * np.mean(r > 1)))
    print("  ⚠ 상수로 놓고 낸 지시값(42 % · 1.03–2.65)과 **다른 양**이다 —")
    print("     그쪽은 집계 구조항 ÷ 집계 보고, 이쪽은 레코드별 비의 분포다.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ans", required=True)
    ap.add_argument("--pns", required=True)
    ap.add_argument("--product", required=True)
    ap.add_argument("--gain", type=float, default=0.82)
    ap.add_argument("--chi2-max", type=float, default=10.0)
    ap.add_argument("--budget", help="`[TBD-4D]` — 빈별 구조항 CSV "
                    "(production_budget_clockfixed.csv). 주면 레코드별 짝지은 비를 낸다")
    ap.add_argument("--epoch-year", type=int, default=2026,
                    help="예산 sec 의 원점 연도 (day = sec/86400, 0-based)")
    ap.add_argument("--tri-rsd", type=float, default=0.0701)
    ap.add_argument("--tri-sd", type=float, default=0.1245)
    ap.add_argument("--csv", help="레코드별 대조표를 여기에 쓴다")
    a = ap.parse_args()

    A = bin5(load_fit(a.ans), a.chi2_max)
    B = bin5(load_fit(a.pns), a.chi2_max)
    psec, pans, punc = load_product(a.product)
    pbin = np.floor(psec / BIN_S).astype(np.int64)

    cab, ia, ib = np.intersect1d(A["bin"], B["bin"], return_indices=True)
    prop = np.sqrt(A["sig"][ia] ** 2 + (a.gain * B["sig"][ib]) ** 2)
    ans_fit = A["no2"][ia] - a.gain * B["no2"][ib]
    cc, ic, ip = np.intersect1d(cab, pbin, return_indices=True)

    print("[TBD-7D] 산출물 보고 불확도의 출처 — **레코드별**")
    print("  핏 5분빈 ANs %d · PNs %d · 두 채널 공통 %d · 산출물과 짝 **%d**"
          % (len(A["bin"]), len(B["bin"]), len(cab), len(cc)))
    if len(cc) < 100:
        print("  ⚠ 짝이 너무 적다 — 시각축(KST/UTC)이나 기간을 확인하라")
        return

    P, U, Afit = prop[ic], punc[ip], ans_fit[ic]
    hot = A["no2"][ia][ic]
    print()
    print("  " + q(U, "산출물 ANs_unc_ppb"))
    print("  " + q(P, "핏 전파 √(σ₁²+g²σ₂²)"))
    print("  " + q(U / P, "산출물 / 핏전파"))
    print("  → 상관 r(산출물, 핏전파) = %+.4f" % np.corrcoef(U, P)[0, 1])
    print()
    print("  [헤더 주장 검증]  `ANs_unc_ppb = 0.04 × NO2`")
    print("  " + q(U / np.abs(hot), "산출물 / |ANs채널 NO2|"))
    print("  → 상관 r(산출물, ANs채널 NO2) = %+.4f" % np.corrcoef(U, hot)[0, 1])
    sl = np.polyfit(hot, U, 1)
    print("  → 회귀 unc = %.6f·NO2 + %.6f" % (sl[0], sl[1]))
    print()
    print("  [산출물 ANs 값 자체는 재현되나]")
    print("  " + q(U * 0 + np.abs(Afit - pans[ip]), "|핏 ΣANs − 산출물 ΣANs|"))
    print("  → 상관 r = %+.4f" % np.corrcoef(Afit, pans[ip])[0, 1])


    # --- 해상도를 밝힌 분모 후보들 -------------------------------------------
    nsc = A["n"][ia][ic]
    ps = np.sqrt((A["sig"][ia][ic] * np.sqrt(nsc)) ** 2
                 + (a.gain * B["sig"][ib][ic] * np.sqrt(B["n"][ib][ic])) ** 2)
    print()
    print("  [분모 후보 — **해상도를 반드시 같이 쓴다**]")
    print("  5분빈 스캔 수 중앙 %.0f → 60 s 예산 빈은 스캔 **1개**에 해당한다"
          % np.median(nsc))
    print("  %-34s %10s %12s" % ("분모", "ppb", "해상도"))
    cands = (("산출물 ANs_unc (이득 계통)", float(np.median(U)), "5 분 · 계통"),
             ("핏 전파 σ — 스캔", float(np.median(ps)), "1 스캔 ≈ 60 s"),
             ("핏 전파 σ — 5 분빈", float(np.median(P)), "5 분"))
    for lab, v, res in cands:
        print("  %-34s %10.4f %12s" % (lab, v, res))
    print()
    print("  [헤드라인 √(보고²+구조²)/보고 · 구조 rSD %.4f · SD %.4f]"
          % (a.tri_rsd, a.tri_sd))
    for lab, v, res in cands:
        print("  %-34s **%.2f–%.2f배**  (%s)"
              % (lab, np.sqrt(v ** 2 + a.tri_rsd ** 2) / v,
                 np.sqrt(v ** 2 + a.tri_sd ** 2) / v, res))
    print("  ⚠ 구조항은 **60 s 예산 빈**에서 쟀다. 5 분 분모와 섞으면 안 된다.")

    if a.budget:
        tbd4d(a, cc, ps, U)

    if a.csv:
        with open(a.csv, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["bin", "sec", "n_ans", "n_pns", "no2_ans", "no2_pns",
                        "sig_ans", "sig_pns", "prop_sigma", "product_unc",
                        "ans_fit", "ans_product"])
            for k in range(len(cc)):
                j = ic[k]
                w.writerow(["%d" % cc[k], "%.0f" % (cc[k] * BIN_S),
                            "%.0f" % A["n"][ia][j], "%.0f" % B["n"][ib][j],
                            "%.6g" % A["no2"][ia][j], "%.6g" % B["no2"][ib][j],
                            "%.6g" % A["sig"][ia][j], "%.6g" % B["sig"][ib][j],
                            "%.6g" % P[k], "%.6g" % U[k],
                            "%.6g" % Afit[k], "%.6g" % pans[ip][k]])
        print("\n→ %s  (%d rows)" % (a.csv, len(cc)))


if __name__ == "__main__":
    main()
