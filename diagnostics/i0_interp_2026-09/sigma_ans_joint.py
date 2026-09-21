#!/usr/bin/env python
"""ΣANs **레벨**에서 직접 전파한다 — 채널별로 재서 제곱합하면 안 된다.

왜
--
채널별 예산을 제곱합한 값(0.1281 ppb)은 **두 채널이 독립**이라는 가정이다. 그런데
hot ANs·PNs 는 **같은 raw 행(flag 500)** 에서 ZA 블록을 가져간다 — 알파 헤더의
`ZA_count=1313` 이 두 채널에 똑같이 찍히는 게 그 증거다. 같은 블록을 빼면 두 채널이
같이 움직이고, ΣANs = ch2 − ch1 에서 공통 성분은 **상쇄된다.**

게이트(0.083 ppb)는 **관측된 ΣANs 차분 변동**이라 상쇄가 이미 들어가 있다. 예산에만
안 들어가 있으면 분자와 분모의 구조가 달라 비교 자체가 성립하지 않는다.

그래서: **ZA 블록 하나를 빼고 → 두 채널에 동시 전파 → ΣANs 시계열을 만들고 → 그
시계열의 robust SD** 를 낸다. 이것만이 게이트와 같은 물리량이다.

⚠ 두 채널의 ZA 스펙트럼은 **검출기 다른 영역**(2053:4101 vs 4101:6149)이라 광자잡음은
독립이고 램프 드리프트만 공통이다. 상쇄가 얼마나 될지는 선험적으로 알 수 없다 — 그래서 잰다.

부호 주의: ΣANs 의 채널 순서(ch2−ch1 vs ch1−ch2)는 미해결(H2)이지만 **robust SD 는
부호에 불변**이라 이 진단의 결론은 그 논쟁과 무관하다.

재현
----
    python diagnostics/i0_interp_2026-09/sigma_ans_joint.py \
        --fitset "<운영 09-17 fitset>" --ceiling-ppb 0.083
"""
from __future__ import annotations

import argparse
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
for p in (_ROOT, os.path.join(_ROOT, "tools"), _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.physics import RayleighPhysics
from core.step_guard import SegmentedPchip
from gui.worker import _alpha_za_plain
from measure_i0_loo import ScanFitter, build_interpolators

OPERATIONAL_EF = 0.12      # gui/worker 가 런 첫 스캔에서 뽑아 고정하던 값

# 규칙 하나: **robust scale 을 제곱합하지 않는다.** 스캔별로 전파해 더한 뒤 마지막에
# scale 을 취한다. heavy-tailed 분포(|응답| max/median 13~78배)에서는 독립이어도
# rSD(a+b) 가 √(rSD(a)²+rSD(b)²) 를 25~39 % 넘는다(2026-09-20 확인: 스캔별 가법성은
# 잔차 0.8~2.2 % 로 성립하는데 Pearson/Spearman/Kendall/윈저화 상관은 전부 ≈0 이었다).
# 게이트도 관측량의 median 기반 scale 이라 이렇게 해야 분자·분모가 같은 연산이 된다.


class Chan:
    """한 채널의 캐시·보간기·핏기. α 조립식은 `measure_i0_loo._alpha_at` 와 같다
    (gui/worker.py Pass 2 단일 출처를 따른 것)."""

    def __init__(self, cache, rt_path, cfg, e_f, step_limit, target="NO2"):
        z = np.load(cache)
        self.d = {k: z[k] for k in z.files}
        self.za_x, self.is_sec, self.breaks = build_interpolators(self.d)
        self.fit = ScanFitter(cfg, None, target=target, e_f=e_f, step_limit=step_limit)
        self.wave = self.fit.wave
        self.rl = float(cfg.get("rl_factor", 1.0))
        self.za_ref = RayleighPhysics.get_alpha_rayleigh(self.wave, 0.0, 1013.25, "zero_air")
        self.pi0 = SegmentedPchip(self.za_x, self.d["za_arr"], break_x=self.breaks)
        self.pt = SegmentedPchip(self.za_x, self.d["za_t"], break_x=self.breaks)
        self.pp = SegmentedPchip(self.za_x, self.d["za_p"], break_x=self.breaks)
        from rt_precompute import load_rt
        rt = load_rt(rt_path)
        o = np.argsort(np.asarray(rt["knot_sec"], float))
        self.rks = np.asarray(rt["knot_sec"], float)[o]
        self.rod = np.asarray(rt["omr_d"], float)[o]
        self.rwave = np.asarray(rt["wave_nm"], float)
        self.rbrk = list(np.asarray(rt.get("manual_breaks_sec", []), float))
        self.ax = self.d["amb_sec"] if self.is_sec else self.d["amb_g"]

    def omr(self, sec, keep=None):
        x = self.rks if keep is None else self.rks[keep]
        y = self.rod if keep is None else self.rod[keep]
        v = np.asarray(SegmentedPchip(x, y, break_x=self.rbrk)(float(sec)), float)
        return v if v.shape == self.wave.shape else np.interp(self.wave, self.rwave[:v.shape[0]], v)

    def alpha(self, j, i0, omr):
        I = self.d["amb_I"][j]
        xq = float(self.ax[j])
        with np.errstate(divide="ignore", invalid="ignore"):
            q = np.where((I > 0) & (i0 > 0), (i0 - I) / I, np.nan)
        a_ref = _alpha_za_plain(float(self.pt(xq)), float(self.pp(xq)), self.za_ref)
        a_s = _alpha_za_plain(float(self.d["amb_T"][j]), float(self.d["amb_P"][j]), self.za_ref)
        return (omr + self.rl * a_ref) * np.nan_to_num(q) - (a_s - a_ref)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fitset", required=True)
    ap.add_argument("--cache-a", default=os.path.join(_HERE, "_cache_hot_ANs_op.npz"))
    ap.add_argument("--cache-b", default=os.path.join(_HERE, "_cache_hot_PNs_op.npz"))
    ap.add_argument("--rt-a", default="C:/Doasis_Work/Output/R/R_CH1.npz")
    ap.add_argument("--rt-b", default="C:/Doasis_Work/Output/R/R_CH2.npz")
    ap.add_argument("--key-a", default="1")
    ap.add_argument("--key-b", default="2")
    ap.add_argument("--ef-a", type=float, default=0.1594)
    ap.add_argument("--ef-b", type=float, default=0.1368)
    ap.add_argument("--step-limit", type=float, default=3.0)
    ap.add_argument("--channel-no2-ppb", type=float, default=2.2895)
    ap.add_argument("--i0-basis", choices=("loo", "knotnoise"), default="loo",
                    help="i0 섭동 기저. loo=ZA knot 제거(상한, 구간 곡률 포함) / "
                         "knotnoise=그 knot 의 반블록차 (A-B)/2 (하한, 곡률 제외). "
                         "rt 는 두 경우 모두 LOO 기저다 — 혼합이면 라벨에 명시할 것")
    ap.add_argument("--ceiling-ppb", type=float, default=0.083)
    ap.add_argument("--out")
    args = ap.parse_args()

    ch = json.load(open(args.fitset, encoding="utf-8"))["channels"]
    A = Chan(args.cache_a, args.rt_a, ch[args.key_a], args.ef_a, args.step_limit)
    B = Chan(args.cache_b, args.rt_b, ch[args.key_b], args.ef_b, args.step_limit)
    tgt = A.fit.target

    # 두 채널이 같은 ZA 블록을 쓰는지 **확인**하고 간다 (전제가 아니라 검사)
    na, nb = len(A.za_x), len(B.za_x)
    dt = np.abs(A.d["za_sec"][:min(na, nb)] - B.d["za_sec"][:min(na, nb)])
    print(f"[확인] ZA 블록 {na} vs {nb}개, 같은 순번끼리 시각차 최대 {np.nanmax(dt):.1f} s "
          + ("→ **공통 스케줄**" if na == nb and np.nanmax(dt) < 60 else "→ ⚠ 다르다"))
    if na != nb or np.nanmax(dt) >= 60:
        raise SystemExit("ABSTAIN: 두 채널의 ZA 블록이 1:1이 아니다 — 짝짓기 규칙을 정해야 한다")

    rows = []
    for k in range(1, na - 1):
        sec_k = float(A.d["za_sec"][k])
        out = {}
        ok = True
        for nm, C in (("a", A), ("b", B)):
            j = int(np.argmin(np.abs(C.d["amb_sec"] - sec_k)))
            if abs(C.d["amb_sec"][j] - sec_k) > 1800:
                ok = False; break
            kr = int(np.argmin(np.abs(C.rks - sec_k)))
            if not (0 < kr < len(C.rks) - 1) or abs(C.rks[kr] - sec_k) > 3600:
                ok = False; break
            keep = np.ones(len(C.rks), dtype=bool); keep[kr] = False
            kz = np.ones(len(C.za_x), dtype=bool); kz[k] = False
            i0l = SegmentedPchip(C.za_x[kz], C.d["za_arr"][kz], break_x=C.breaks)(float(C.ax[j]))
            if i0l is None:
                ok = False; break
            sec_j = float(C.d["amb_sec"][j])
            i0_full = np.asarray(C.pi0(float(C.ax[j])), float)
            if args.i0_basis == "knotnoise":
                # knot 제거 대신 **그 knot 자신의 잡음 실현**을 얹는다.
                # (A−B)/2 는 반블록 평균의 차라 분산이 정확히 블록평균 잡음과 같다
                #   var[(A−B)/2] = (2σ²/n + 2σ²/n)/4 = σ²/n = var[블록평균]
                # → 배율 보정 없는 실측 하한. 간격(구간 곡률) 성분은 여기 안 들어간다.
                za2 = C.d["za_arr"].copy()
                za2[k] = za2[k] + (C.d["za_half_a"][k] - C.d["za_half_b"][k]) / 2.0
                i0l = SegmentedPchip(C.za_x, za2, break_x=C.breaks)(float(C.ax[j]))
            omr_full, omr_loo = C.omr(sec_j), C.omr(sec_j, keep)
            a_full = C.alpha(j, i0_full, omr_full)
            T, P = float(C.d["amb_T"][j]), float(C.d["amb_P"][j])
            sh, sq, _ = C.fit.seed(a_full, T, P)
            # ef 섭동은 α 가 아니라 **핏 모델**을 바꾼다: 운영 고정값 → 그 스캔 검출값
            a_i0 = C.alpha(j, np.asarray(i0l, float), omr_full)
            a_rt = C.alpha(j, i0_full, omr_loo)
            a_tri = C.alpha(j, np.asarray(i0l, float), omr_loo)
            fits = {}
            for nm2, aa, ee in (("base", a_full, OPERATIONAL_EF),
                                ("i0", a_i0, OPERATIONAL_EF),
                                ("rt", a_rt, OPERATIONAL_EF),
                                ("ef", a_full, C.fit.ch.detect(a_full)),
                                ("tri", a_tri, C.fit.ch.detect(a_tri))):
                f = C.fit.fit(aa, T, P, (sh, sq), ee)
                if f["_at_bound"]:
                    ok = False
                    break
                fits[nm2] = f[tgt]
            if not ok:
                break
            out[nm] = fits
        if not ok:
            continue
        if not np.isfinite([v for f in out.values() for v in f.values()]).all():
            continue
        r = dict(k=k, sec=sec_k)
        for nm in ("a", "b"):
            for c in ("i0", "rt", "ef", "tri"):
                r[f"d_{nm}_{c}"] = out[nm][c] - out[nm]["base"]
        for c in ("i0", "rt", "ef", "tri"):
            r[f"d_sigma_{c}"] = ((out["b"][c] - out["a"][c])
                                 - (out["b"]["base"] - out["a"]["base"]))
        r["sigma_base"] = out["b"]["base"] - out["a"]["base"]
        rows.append(r)
    if len(rows) < 5:
        raise SystemExit("ABSTAIN: 짝지어진 케이스가 모자란다")

    def rsd(v):
        v = np.asarray(v, float)
        return float(1.4826 * np.median(np.abs(v - np.median(v))))

    def col(key):
        return np.array([r[key] for r in rows], float)

    _b = ("ZA knot 제거(LOO=상한)" if args.i0_basis == "loo"
          else "반블록차 (A-B)/2 = 실측 knot 잡음(하한)")
    print(f"[3중 joint] n={len(rows)}   i0={_b} · rt=같은시각 R knot 제거(LOO) "
          f"· ef=고정 {OPERATIONAL_EF} → 스캔별 검출값")
    print()
    print("%-9s %8s %8s %8s %11s %9s %9s" % ("", "i0", "rt", "ef", "스캔별합", "3중", "제곱합"))
    for nm, lab in (("a", "ANs채널"), ("b", "PNs채널")):
        v = {c: col(f"d_{nm}_{c}") for c in ("i0", "rt", "ef", "tri")}
        ssum = v["i0"] + v["rt"] + v["ef"]
        print("%-9s %8.4f %8.4f %8.4f %11.4f %9.4f %9.4f" % (
            lab, rsd(v["i0"]), rsd(v["rt"]), rsd(v["ef"]), rsd(ssum), rsd(v["tri"]),
            float(np.sqrt(rsd(v["i0"]) ** 2 + rsd(v["rt"]) ** 2 + rsd(v["ef"]) ** 2))))
        res = v["tri"] - ssum
        print("          가법성 잔차 |중앙| %.5f = 3중 신호의 %.1f%%" % (
            np.median(np.abs(res)),
            100 * np.median(np.abs(res)) / max(np.median(np.abs(v["tri"])), 1e-12)))
    vs = {c: col(f"d_sigma_{c}") for c in ("i0", "rt", "ef", "tri")}
    ss = vs["i0"] + vs["rt"] + vs["ef"]
    print("%-9s %8.4f %8.4f %8.4f %11.4f %9.4f %9.4f" % (
        "ΣANs", rsd(vs["i0"]), rsd(vs["rt"]), rsd(vs["ef"]), rsd(ss), rsd(vs["tri"]),
        float(np.sqrt(rsd(vs["i0"]) ** 2 + rsd(vs["rt"]) ** 2 + rsd(vs["ef"]) ** 2))))
    tri = rsd(vs["tri"])
    ca, cb = col("d_a_tri"), col("d_b_tri")
    print()
    print(f"  두 채널 3중응답 상관 r={np.corrcoef(ca, cb)[0, 1]:+.3f}  "
          f"→ ΣANs 상쇄 {1 - tri / float(np.hypot(rsd(ca), rsd(cb))):+.0%}")
    msg = f"  **ΣANs 3중 joint = {tri:.4f} ppb**"
    if args.ceiling_ppb:
        msg += (f"  · 게이트 {args.ceiling_ppb:.4f} 대비 {tri / args.ceiling_ppb:.2f}배 "
                + ("PASS" if tri <= args.ceiling_ppb else "**FAIL**"))
    print(msg)

    out = args.out or os.path.join(_HERE, "sigma_ans_triple.csv")
    keys = list(rows[0])
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(",".join(keys) + "\n")
        for r in rows:
            fh.write(",".join(f"{r[x]:.6g}" if isinstance(r[x], float) else str(r[x])
                              for x in keys) + "\n")
    print(f"→ {out}  ({len(rows)} rows)")


if __name__ == "__main__":
    main()
