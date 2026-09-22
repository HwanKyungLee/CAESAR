#!/usr/bin/env python
"""`§7.3` **농도는 이상한데 잔차·보고 σ 는 정상인 구간** — 그리고 플래그가 뭘 놓치나.

왜 이게 §7.3 인가
-----------------
claim ① 의 실물 증례다. 핏이 스스로 "이상하다" 고 말할 수단은 잔차와 보고 σ
둘뿐인데, 기준(baseline) 쪽이 틀리면 **둘 다 안 움직인다** — 핏은 틀린 기준에
완벽히 맞을 수 있다. 그런 구간이 실제로 있는지, 몇 개나 되는지, 운용 플래그가
그중 얼마를 잡는지를 센다.

이상 구간의 정의
----------------
* **농도가 이상하다** — 그 레코드의 NO₂ 가 **국소 기준**(±`--win-h` 시간의
  중앙값, 자기 자신 제외)에서 robust 하게 `--z` σ 이상 벗어난다. 국소로 잡는
  이유는 일주기·계절 변동을 이상으로 세지 않기 위해서다.
* **잔차·보고 σ 는 정상이다** — `RMS` 와 `NO2_Error` 가 둘 다 캠페인 분포의
  `--normal-pct` 백분위 **아래**다. 즉 핏은 아무 불평도 하지 않는다.

플래그 셋 (산출물이 실제로 쓰는 것)
----------------------------------
| | 정의 | 산출물에서의 이름 |
|---|---|---|
| F1 | `Chi2 ≥ 10` | QC 기각 |
| F2 | 신호 평균 < 캠페인 중앙의 `--low-light` 배 | `low_light` |
| F3 | 5 분빈 스캔 수 < 3 | `few_scans` |

`Status` 는 산출물이 **안 쓴다**(헤더: "removes low-SNR good fits & biases
high"). 그래도 참고로 같이 센다.

재현
----
    python tools/anomaly_stretches.py \\
        --fit "<...ANs_...merge54....dat>" --label ANs채널
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reported_sigma_provenance import BIN_S, load_fit

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

COLS = ("Time", "NO2", "NO2_Error", "Chi2", "RMS", "_signal_mean", "Status")


def rsd(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) if v.size else np.nan


def bin_all(d):
    """5 분빈. 플래그 판정에 필요한 양을 전부 빈 단위로 올린다."""
    m = np.isfinite(d["sec"]) & np.isfinite(d["NO2"])
    b = np.floor(d["sec"][m] / BIN_S).astype(np.int64)
    u, inv = np.unique(b, return_inverse=True)
    n = np.bincount(inv).astype(float)
    avg = lambda k: np.bincount(inv, weights=np.nan_to_num(d[k][m])) / n
    # `Status` 는 문자열이다 — 빈 안에 정상이 아닌 스캔이 **하나라도** 있으면 센다.
    st = d.get("Status")
    bad = (np.array([str(x).strip().lower() not in ("good", "ok", "", "nan")
                     for x in st[m]], bool) if st is not None
           else np.zeros(int(m.sum()), bool))
    return dict(bin=u, n=n, no2=avg("NO2"), sig=avg("NO2_Error"),
                chi2=avg("Chi2"), rms=avg("RMS"), sig_mean=avg("_signal_mean"),
                status=np.bincount(inv, weights=bad.astype(float)) > 0)


def local_z(bin_id, v, win_bins):
    """±`win_bins` 안의 **자기 제외** 중앙값에서 몇 robust σ 떨어졌나.

    전역 중앙값을 쓰면 일주기가 통째로 이상으로 잡힌다. 창 안에 이웃이
    `--min-neighbours` 개 미만이면 판정하지 않는다(NaN) — 0 이 아니다.
    """
    z = np.full(len(v), np.nan)
    med = np.full(len(v), np.nan)
    lo = np.searchsorted(bin_id, bin_id - win_bins, "left")
    hi = np.searchsorted(bin_id, bin_id + win_bins, "right")
    for i in range(len(v)):
        sl = np.r_[v[lo[i]:i], v[i + 1:hi[i]]]
        sl = sl[np.isfinite(sl)]
        if sl.size < 8:
            continue
        med[i] = np.median(sl)
        s = 1.4826 * np.median(np.abs(sl - med[i]))
        if s > 0:
            z[i] = (v[i] - med[i]) / s
    return z, med


def stretches(idx, bin_id, min_len):
    """연속(빈 번호가 1씩 증가) 구간으로 묶는다."""
    out, cur = [], []
    for k in idx:
        if cur and bin_id[k] == bin_id[cur[-1]] + 1:
            cur.append(k)
        else:
            if len(cur) >= min_len:
                out.append(cur)
            cur = [k]
    if len(cur) >= min_len:
        out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fit", required=True)
    ap.add_argument("--label", default="hot 채널")
    ap.add_argument("--z", type=float, default=5.0, help="국소 robust σ 문턱")
    ap.add_argument("--win-h", type=float, default=1.0, help="국소 기준 창 ±시간")
    ap.add_argument("--normal-pct", type=float, default=75.0,
                    help="잔차·보고 σ 가 '정상' 인 백분위 상한")
    ap.add_argument("--low-light", type=float, default=0.5,
                    help="신호 평균이 캠페인 중앙의 이 배 미만이면 저광량")
    ap.add_argument("--min-len", type=int, default=3, help="구간 최소 길이(빈)")
    ap.add_argument("--show", type=int, default=6)
    a = ap.parse_args()

    D = bin_all(load_fit(a.fit, COLS))
    nb = len(D["bin"])
    z, lmed = local_z(D["bin"], D["no2"], int(round(a.win_h * 3600.0 / BIN_S)))
    r_hi = float(np.nanpercentile(D["rms"], a.normal_pct))
    s_hi = float(np.nanpercentile(D["sig"], a.normal_pct))
    quiet = (D["rms"] <= r_hi) & (D["sig"] <= s_hi)
    odd = np.isfinite(z) & (np.abs(z) >= a.z)
    silent = odd & quiet

    F = {"F1 Chi2 ≥ 10": D["chi2"] >= 10.0,
         "F2 저광량": D["sig_mean"] < a.low_light * np.nanmedian(D["sig_mean"]),
         "F3 스캔 < 3": D["n"] < 3}
    any_f = np.zeros(nb, bool)
    for v in F.values():
        any_f |= v

    print("[§7.3] %s — 농도는 이상한데 핏은 조용한 구간" % a.label)
    print("  5 분빈 %d · 국소 창 ±%.1f h · 문턱 %.1f robust σ" % (nb, a.win_h, a.z))
    print("  '정상' 기준: RMS ≤ p%g (%.3e) · 보고 σ ≤ p%g (%.4f ppb)"
          % (a.normal_pct, r_hi, a.normal_pct, s_hi))
    print("  판정 가능 %d · 농도 이상 **%d (%.2f %%)** · 그중 핏이 조용한 것 "
          "**%d (%.1f %%)**"
          % (int(np.isfinite(z).sum()), int(odd.sum()), 100 * odd.mean(),
             int(silent.sum()), 100 * silent.sum() / max(odd.sum(), 1)))

    # 플래그를 세기 전에, 그 플래그가 **작동 범위 안에 있는지** 부터 본다.
    print()
    print("  [플래그가 애초에 발동 가능한가]")
    print("    Chi2  min %.3f · p50 %.3f · p95 %.3f · **max %.3f** → 문턱 10 은 %s"
          % (np.nanmin(D["chi2"]), np.nanmedian(D["chi2"]),
             np.nanpercentile(D["chi2"], 95), np.nanmax(D["chi2"]),
             "**한 번도 안 걸린다**" if np.nanmax(D["chi2"]) < 10 else "걸린다"))
    mm = np.isfinite(D["rms"]) & np.isfinite(D["sig"])
    rr = float(np.corrcoef(D["rms"][mm], D["sig"][mm])[0, 1])
    ratio = D["sig"][mm] / D["rms"][mm]
    print("    corr(RMS, 보고 σ) = **%+.4f** · σ/RMS 가 p05~p95 로 %.1f %% 만 움직인다"
          % (rr, 100 * (np.percentile(ratio, 95) / np.percentile(ratio, 5) - 1)))
    if rr > 0.99:
        print("    → 보고 σ 는 잔차의 **상수배**다. 자기검증 통로가 둘이 아니라 **하나**다.")

    print()
    print("  [플래그가 무엇을 잡나]  분모는 **농도가 이상한 빈 %d 개**" % odd.sum())
    print("  %-16s %10s %12s %14s" % ("플래그", "전체 발동", "이상 중 적중", "적중률"))
    for nm, v in F.items():
        hit = int((v & odd).sum())
        print("  %-16s %10d %12d %13.1f %%"
              % (nm, int(v.sum()), hit, 100 * hit / max(odd.sum(), 1)))
    hit = int((any_f & odd).sum())
    print("  %-16s %10d %12d %13.1f %%"
          % ("셋 중 하나라도", int(any_f.sum()), hit, 100 * hit / max(odd.sum(), 1)))
    miss = odd & ~any_f
    print("  %-16s %10s %12d %13.1f %%   ← **놓치는 것**"
          % ("아무것도 안 걸림", "—", int(miss.sum()),
             100 * miss.sum() / max(odd.sum(), 1)))
    st = np.asarray(D["status"], bool)
    print("  (참고) `Status` 는 산출물이 안 쓴다 — 발동 %d · 이상 중 적중 %.1f %%"
          % (int(st.sum()), 100 * (st & odd).sum() / max(odd.sum(), 1)))

    sil_miss = silent & ~any_f
    print()
    print("  **핏도 조용하고 플래그도 안 걸리는 빈: %d 개 (%.2f %% of 전체)**"
          % (int(sil_miss.sum()), 100 * sil_miss.mean()))

    idx = np.where(sil_miss)[0]
    S = stretches(idx, D["bin"], a.min_len)
    print("  연속 %d 빈 이상인 구간 **%d 개**" % (a.min_len, len(S)))
    if S:
        print()
        print("  %-21s %5s %9s %9s %9s %11s %9s"
              % ("시작 (UTC)", "빈", "NO₂", "국소중앙", "최대|z|", "RMS/p50", "σ/p50"))
        r50, s50 = np.nanmedian(D["rms"]), np.nanmedian(D["sig"])
        S.sort(key=lambda g: -max(abs(z[k]) for k in g))
        for g in S[:a.show]:
            sub = np.asarray(g)
            print("  %-21s %5d %9.3f %9.3f %9.1f %11.2f %9.2f"
                  % (_utc(D["bin"][g[0]] * BIN_S), len(g),
                     float(np.median(D["no2"][sub])), float(np.median(lmed[sub])),
                     float(np.max(np.abs(z[sub]))),
                     float(np.median(D["rms"][sub])) / r50,
                     float(np.median(D["sig"][sub])) / s50))
    print()
    print("  ⚠ 이 구간들은 **핏이 옳다고 말하는데 값이 틀린** 후보다. 잔차와 보고")
    print("     σ 가 정상 범위 안이므로 self-consistency(T1)로는 절대 못 걸른다 —")
    print("     `docs/CLAUDE.md` 의 원칙 2(T1 단독 심판 금지)의 실물 증례다.")


def _utc(sec):
    import time
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(sec))


if __name__ == "__main__":
    main()
