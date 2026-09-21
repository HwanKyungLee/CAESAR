#!/usr/bin/env python
"""[TBD-G] 9시간 묵은 R(t) 가 산출물을 얼마나 움직이나 — **실측**.

무엇을 재나
-----------
운영 `R_CH*.npz` 는 2026-07-10 산물이라 5/29 시계 보정(`f897ce8`, 2026-09-19)
보다 앞선다. 2026-05-18~05-29 의 knot 이 **보정 전 raw 시각**에 있고 알파는
**보정된** 시각에 있으므로, 그 구간 알파는 **9시간 묵은 R** 로 만들어졌다.

오차예산 창(05-18~05-24)이 전부 그 안이다. 그래서 예산 창 **전 빈**을 두 번
검색한다 — 운영 knot 과 시계정렬 knot(`tools/rt_clockfix.py`). R(t) 곡선을
민 차이가 아니라 **산출물의 차이**를 본다.

왜 섭동이 아니라 실측인가
------------------------
LOO 섭동은 knot 하나를 빼고 **보간의 뻣뻣함**을 잰다. 여기서는 축 전체가 밀려
있다 — 핏 잔차도 안 커지고 보고 σ 도 안 커지는 **기준 오차**다. 그래서 잔차
RMS 와 보고 σ 가 **움직이는지도 같이** 낸다. 안 움직이면 그게 claim ① 의 증례다.

I₀ 는 영향 없다(생산 캐시 ZA knot 이 보정 후 축과 0.000000 s 일치, 2026-09-22).

재현
----
    python diagnostics/i0_interp_2026-09/clock_impact.py \
        --fitset "<운영 09-17>"
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_ROOT, os.path.join(_ROOT, "tools"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.parallel import max_workers
from production_budget import Chan, rsd

_W = {}


def _init(spec):
    C = Chan(spec["cache"], spec["rt_op"], spec["cfg"], spec["e_f"], spec["step"])
    Cx = Chan(spec["cache"], spec["rt_fx"], spec["cfg"], spec["e_f"], spec["step"])
    _W["C"], _W["Cx"] = C, Cx


def _chunk(js):
    """빈 묶음 하나 → [(sec, no2_op, no2_fx, dshift, dalpha,
                       resid_op, resid_fx, perr_op, perr_fx)…]."""
    C, Cx = _W["C"], _W["Cx"]
    tgt = C.fit.target
    out = []
    seed = {}
    nk = len(C.za_x)
    knot_of = np.clip(np.searchsorted(C.za_x, C.ax), 1, nk - 1)
    left = np.abs(C.ax - C.za_x[knot_of - 1]) < np.abs(C.ax - C.za_x[np.minimum(knot_of, nk - 1)])
    knot_of = np.where(left, knot_of - 1, knot_of)
    for j in js:
        xq, sec_j = float(C.ax[j]), float(C.d["amb_sec"][j])
        i0 = np.asarray(C.pi0(xq), float)
        a_op = C.alpha(j, i0, C.omr(sec_j))
        a_fx = Cx.alpha(j, i0, Cx.omr(sec_j))
        T, P = float(C.d["amb_T"][j]), float(C.d["amb_P"][j])
        k = int(knot_of[j])
        if k not in seed:
            seed[k] = C.fit.seed(a_op, T, P)[:2]
        sh, sq = seed[k]
        f_op = C.fit.fit(a_op, T, P, (sh, sq), 0.12, want_diag=True)
        f_fx = C.fit.fit(a_fx, T, P, (sh, sq), 0.12, want_diag=True)
        if f_op["_at_bound"] or f_fx["_at_bound"]:
            continue
        if not (np.isfinite(f_op[tgt]) and np.isfinite(f_fx[tgt])):
            continue
        out.append((sec_j, f_op[tgt], f_fx[tgt],
                    f_fx["_shift"] - f_op["_shift"],
                    float(np.sqrt(np.nanmean((a_op - a_fx) ** 2))),
                    f_op.get("_resid_rms", np.nan), f_fx.get("_resid_rms", np.nan),
                    f_op["_perr"][tgt], f_fx["_perr"][tgt]))
    return out


def run_channel(cache, rt_op, rt_fx, cfg, e_f, step, jobs, limit):
    C = Chan(cache, rt_op, cfg, e_f, step)
    n = len(C.ax)
    stride = max(1, n // limit) if limit else 1
    js = list(range(0, n, stride))
    nw = max(1, min(jobs or max_workers(), len(js)))
    spec = dict(cache=cache, rt_op=rt_op, rt_fx=rt_fx, cfg=cfg, e_f=e_f, step=step)
    parts = []
    with cf.ProcessPoolExecutor(max_workers=nw, initializer=_init,
                                initargs=(spec,)) as ex:
        for r in ex.map(_chunk, [js[i::nw] for i in range(nw)]):
            parts += r
    parts.sort(key=lambda t: t[0])
    M = np.asarray(parts, float) if parts else np.zeros((0, 9))
    return dict(sec=M[:, 0], op=M[:, 1], fx=M[:, 2], dsh=M[:, 3], da=M[:, 4],
                r_op=M[:, 5], r_fx=M[:, 6], s_op=M[:, 7], s_fx=M[:, 8], nw=nw)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fitset", required=True)
    ap.add_argument("--ratio", type=float, default=0.82,
                    help="ΣANs = ch1 − r·ch2 의 r (캠페인 단일값)")
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--suffix", default="op",
                    help="캐시 접미사. `op`=예산 창(05-18~24), `b`=경계 창(05-25~06-01)")
    ap.add_argument("--label", default="예산 창 05-18~24")
    a = ap.parse_args()

    ch = json.load(open(a.fitset, encoding="utf-8"))["channels"]
    print("[TBD-G] 9시간 묵은 R(t) 의 산출물 영향 — %s" % a.label)
    res = {}
    for lab, key, cache, ef in (("ANs", "1", f"_cache_hot_ANs_{a.suffix}.npz", 0.1594),
                                ("PNs", "2", f"_cache_hot_PNs_{a.suffix}.npz", 0.1368)):
        r = run_channel(os.path.join(_HERE, cache),
                        f"C:/Doasis_Work/Output/R/R_CH{key}.npz",
                        os.path.join(_HERE, f"R_CH{key}_clockfixed.npz"),
                        ch[key], ef, 3.0, a.jobs, a.limit)
        res[lab] = r
        print(f"  [{lab}] 워커 {r['nw']} · 빈 {len(r['sec'])} · "
              f"base NO2 중앙 {np.median(r['op']):.3f} ppb")

    A, B = res["ANs"], res["PNs"]
    common, ia, ib = np.intersect1d(np.round(A["sec"], 3), np.round(B["sec"], 3),
                                    return_indices=True)
    print(f"  두 채널 공통 빈 {len(common)}")

    print()
    print("%-10s %11s %11s %9s %9s %9s"
          % ("계열", "Δ rSD(ppb)", "Δ SD(ppb)", "중앙Δ", "상대중앙", "rt항 대비"))
    RT_RSD = {"ANs": 0.0326, "PNs": 0.0123, "ΣANs": 0.0253}     # §2 표
    series = {"ANs채널": (A["fx"] - A["op"], A["op"]),
              "PNs채널": (B["fx"] - B["op"], B["op"])}
    ds = ((A["fx"][ia] - a.ratio * B["fx"][ib])
          - (A["op"][ia] - a.ratio * B["op"][ib]))
    series["ΣANs"] = (ds, A["op"][ia] - a.ratio * B["op"][ib])
    for nm, (d, base) in series.items():
        key = nm.replace("채널", "")
        ref = RT_RSD.get(key, np.nan)
        print("%-10s %11.4f %11.4f %+9.4f %8.2f%% %9.2f"
              % (nm, rsd(d), np.std(d, ddof=1), np.median(d),
                 100 * np.median(np.abs(d)) / max(abs(np.median(base)), 1e-12),
                 rsd(d) / ref if ref == ref else np.nan))

    print()
    print("[두 채널이 같은 방향인가]  ΣANs = ch1 − %.2f·ch2 이므로 같은 방향이면 상쇄된다"
          % a.ratio)
    da, db = A["fx"][ia] - A["op"][ia], B["fx"][ib] - B["op"][ib]
    print("  상관 r = %+.3f · 중앙 Δ ANs %+.4f · PNs %+.4f ppb"
          % (np.corrcoef(da, db)[0, 1], np.median(da), np.median(db)))
    print("  |ΣANs Δ| 중앙 %.4f 대 |ANs Δ| + %.2f·|PNs Δ| 중앙 %.4f  → %s"
          % (np.median(np.abs(ds)), a.ratio,
             np.median(np.abs(da)) + a.ratio * np.median(np.abs(db)),
             "상쇄" if np.median(np.abs(ds)) <
             np.median(np.abs(da)) + a.ratio * np.median(np.abs(db)) else "증폭"))

    print()
    print("[핏이 이걸 보는가]  α 는 바뀌는데 잔차·보고σ·shift 가 안 움직이면 기준 오차다")
    print("  %-4s %11s %11s %11s %9s %11s %11s %8s"
          % ("", "α RMS 차", "잔차 운영", "잔차 정렬", "잔차 비", "보고σ 운영",
             "보고σ 정렬", "σ 비"))
    for nm, r in (("ANs", A), ("PNs", B)):
        ro, rf = np.median(r["r_op"]), np.median(r["r_fx"])
        so, sf = np.median(r["s_op"]), np.median(r["s_fx"])
        print("  %-4s %11.3e %11.3e %11.3e %9.4f %11.5f %11.5f %8.4f"
              % (nm, np.median(r["da"]), ro, rf, rf / ro if ro else np.nan,
                 so, sf, sf / so if so else np.nan))
        print("       |Δshift| 중앙 %.4f px · p99 %.4f px · |Δ농도|/보고σ 중앙 %.2f"
              % (np.median(np.abs(r["dsh"])), np.percentile(np.abs(r["dsh"]), 99),
                 np.median(np.abs(r["fx"] - r["op"])) / max(so, 1e-30)))

    out = os.path.join(_HERE, f"clock_impact_{a.suffix}.csv")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("sec,ans_op,ans_fx,pns_op,pns_fx,sigma_ans_delta\n")
        for n in range(len(common)):
            fh.write("%.6g,%.6g,%.6g,%.6g,%.6g,%.6g\n"
                     % (common[n], A["op"][ia[n]], A["fx"][ia[n]],
                        B["op"][ib[n]], B["fx"][ib[n]], ds[n]))
    print(f"\n→ {out}  ({len(common)} rows)")


if __name__ == "__main__":
    main()
