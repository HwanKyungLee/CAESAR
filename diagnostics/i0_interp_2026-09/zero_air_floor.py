#!/usr/bin/env python
"""§7.2 정본 — **제로에어 잡음 바닥**. 참값이 0 인 측정으로 보고 σ 를 심판한다.

왜 이게 정본인가
----------------
ambient lag-1 은 실제 대기 변동을 포함하므로 **정밀도의 상한**만 준다. 제로에어
블록은 NO₂ 가 없으므로 핏 결과의 **참값이 0** 이다. 그래서 산포가 곧 잡음이다.

무엇을 조립하나
--------------
그 ZA 블록을 **측정으로**, I₀ 는 **그 knot 을 뺀 나머지로 보간**해서 쓴다
(leave-one-out). production 이 ambient 에 하는 일과 똑같은 구조다 —
I₀ 보간 오차까지 포함된, 제품이 실제로 겪는 잡음 바닥이다.

    α = (omr_d + RL·α_Ray(T_i0,P_i0))·(I₀−I)/I − (α_Ray(T,P) − α_Ray(T_i0,P_i0))

⚠ 스캔 수가 다르다. ZA 블록은 34 스캔, ambient 빈은 60 s 평균이다. 광자잡음은
√N 로 주므로 **비교 전에 스캔 수를 맞춰야** 한다 — 실측 스캔 수를 같이 낸다.

재현
----
    python diagnostics/i0_interp_2026-09/zero_air_floor.py --fitset "<운영 09-17>"
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
for _p in (_ROOT, os.path.join(_ROOT, "tools"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.step_guard import SegmentedPchip
from gui.worker import _alpha_za_plain
from production_budget import Chan, rsd

OPERATIONAL_EF = 0.12


def fix_shift(cfg, value):
    """shift 를 고정한 cfg 사본. 제로에어에는 정렬할 신호가 없다.

    자유 shift 로 재면 155 블록 중 102·120 개가 상자 끝에 붙어 빠진다(실측).
    그건 §5 의 식별성 결과이지 잡음 바닥이 아니다 — 남은 표본이 **덜 시끄러운
    쪽으로 선택**되므로 σ 가 아래로 편향된다. 그래서 운용 중앙 shift 에 고정하고
    **전 블록**을 쓴다.
    """
    import copy
    c = copy.deepcopy(cfg)
    rp = c["ref_props"]
    for g, pr in rp.items():
        if pr.get("sh_mode") == "Limit":
            pr["sh_mode"], pr["sh_val"] = "Fix", "%.6g" % value
    return c


def run(cache, rt, cfg, e_f, step, target="NO2", sh_fix=None):
    C = Chan(cache, rt, fix_shift(cfg, sh_fix) if sh_fix is not None else cfg,
             e_f, step)
    nk = len(C.za_x)
    no2, sig, resid, nsc, secs = [], [], [], [], []
    n_bad = 0
    for k in range(1, nk - 1):
        keep = np.ones(nk, bool)
        keep[k] = False
        loo = SegmentedPchip(C.za_x[keep], C.d["za_arr"][keep], break_x=C.breaks)
        xq = float(C.za_x[k])
        i0 = loo(xq)
        if i0 is None:
            continue
        i0 = np.asarray(i0, float)
        I = np.asarray(C.d["za_arr"][k], float)          # 이 블록이 '측정'
        with np.errstate(divide="ignore", invalid="ignore"):
            q = np.where((I > 0) & (i0 > 0), (i0 - I) / I, np.nan)
        T, P = float(C.d["za_t"][k]), float(C.d["za_p"][k])
        a_ref = _alpha_za_plain(float(C.pt(xq)), float(C.pp(xq)), C.za_ref)
        a_s = _alpha_za_plain(T, P, C.za_ref)
        omr = C.omr(float(C.d["za_sec"][k]))
        alpha = (omr + C.rl * a_ref) * np.nan_to_num(q) - (a_s - a_ref)
        sh, sq = C.fit.seed(alpha, T, P)[:2]
        f = C.fit.fit(alpha, T, P, (sh, sq), OPERATIONAL_EF, want_diag=True)
        if f["_at_bound"] or not np.isfinite(f[target]):
            n_bad += 1
            continue
        no2.append(f[target])
        sig.append(f["_perr"][target])
        resid.append(f.get("_resid_rms", np.nan))
        nsc.append(float(C.d["za_nscan"][k]))
        secs.append(float(C.d["za_sec"][k]))
    return (np.asarray(no2, float), np.asarray(sig, float),
            np.asarray(resid, float), np.asarray(nsc, float), n_bad, len(C.ax),
            np.asarray(secs, float))


def sigma_ans(blk, ratio, reported):
    """§7.2 정본 — **제품 레코드는 ΣANs 다.** 채널 둘을 짝지어 직접 잰다.

    채널별 σ 를 제곱합하면 **두 채널이 독립이라고 가정**하는 것이다. 같은 광원·
    같은 캐비티·같은 시각이라 그럴 이유가 없다 — 그래서 상관을 **재고**, 제곱합
    가정이 얼마나 틀리는지 같이 낸다(§4.3 과 같은 규율).

    참값이 0 이므로 MDL = 3σ 를 그대로 쓸 수 있다.
    """
    if len(blk) < 2:
        print()
        print("[ΣANs] 채널이 둘 다 있어야 낸다 — 생략")
        return
    (sa, va), (sb, vb) = blk["ANs채널"], blk["PNs채널"]
    key_a = np.round(sa, 3)
    key_b = np.round(sb, 3)
    common, ia, ib = np.intersect1d(key_a, key_b, return_indices=True)
    if len(common) < 10:
        print()
        print("[ΣANs] 두 채널의 ZA 블록 시각이 안 맞는다 (공통 %d) — 생략"
              % len(common))
        return
    x, y = va[ia], vb[ib]
    d = x - ratio * y
    r = float(np.corrcoef(x, y)[0, 1])
    m_r, m_s = rsd(d), float(np.std(d, ddof=1))
    quad_r = float(np.sqrt(rsd(x) ** 2 + (ratio * rsd(y)) ** 2))
    print()
    print("[ΣANs 잡음 바닥]  제품 레코드 기준 · 공통 ZA 블록 **%d** · ΣANs = ch1 − %.2f·ch2"
          % (len(common), ratio))
    print("  채널간 상관 r = %+.3f — 제곱합은 r=0 을 가정한다" % r)
    print("  %-14s %9s %9s %11s %11s" % ("", "rSD", "SD", "MDL=3·rSD", "MDL=3·SD"))
    print("  %-14s %9.4f %9.4f %11.4f %11.4f"
          % ("실측(짝지음)", m_r, m_s, 3 * m_r, 3 * m_s))
    print("  %-14s %9.4f %9s %11.4f %11s"
          % ("제곱합(가정)", quad_r, "—", 3 * quad_r, "—"))
    print("  → 제곱합이 실측보다 %+.1f %% (상관 %+.3f 의 몫)" % (100 * (quad_r / m_r - 1), r))
    print("  중앙 편향 %+.4f ppb (참값 0)" % float(np.median(d)))
    print("  보고 불확도 %.4f ppb 대비 — rSD %.2f배 · SD %.2f배"
          % (reported, m_r / reported, m_s / reported))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fitset", required=True)
    ap.add_argument("--rt-a", default=os.path.join(_HERE, "R_CH1_clockfixed.npz"))
    ap.add_argument("--rt-b", default=os.path.join(_HERE, "R_CH2_clockfixed.npz"))
    ap.add_argument("--sh-ans", type=float, default=-6.12,
                    help="ANs 채널 운용 shift 중앙 (px). 제로에어는 shift 를 고정해 잰다")
    ap.add_argument("--sh-pns", type=float, default=-0.51)
    ap.add_argument("--free-shift", action="store_true",
                    help="shift 를 자유로 두고 잰다 — 상자고착으로 표본이 선택편향된다")
    ap.add_argument("--amb-scans", type=float, default=60.0,
                    help="ambient 빈의 스캔 수(60 s 평균). 광자잡음 √N 환산용")
    ap.add_argument("--ratio", type=float, default=0.82,
                    help="ΣANs = ch1 − r·ch2 의 r (캠페인 단일값)")
    ap.add_argument("--reported-ans", type=float, default=0.0806,
                    help="산출물의 ΣANs 보고 불확도 중앙 (ppb) — 비교 분모")
    a = ap.parse_args()

    ch = json.load(open(a.fitset, encoding="utf-8"))["channels"]
    print("[제로에어 잡음 바닥]  참값 = 0 · I₀ 는 그 knot 을 뺀 LOO 보간 · shift %s"
          % ("자유(선택편향 주의)" if a.free_shift
             else "고정 ANs %.2f / PNs %.2f px" % (a.sh_ans, a.sh_pns)))
    print("%-9s %5s %10s %11s %11s %9s %11s"
          % ("채널", "n", "중앙(편향)", "실측 σ(rSD)", "실측 σ(SD)", "보고 σ", "실측/보고"))
    out, blk = {}, {}
    for lab, key, cache, ef, rt, shf in (
            ("ANs채널", "1", "_cache_hot_ANs_op.npz", 0.1594, a.rt_a, a.sh_ans),
            ("PNs채널", "2", "_cache_hot_PNs_op.npz", 0.1368, a.rt_b, a.sh_pns)):
        v, s, r, nsc, nb, namb, sec = run(os.path.join(_HERE, cache), rt, ch[key],
                                          ef, 3.0,
                                          sh_fix=None if a.free_shift else shf)
        if not len(v):
            print("  [%s] 케이스 없음" % lab)
            continue
        m_r, m_s = rsd(v), float(np.std(v, ddof=1))
        rep = float(np.median(s))
        out[lab] = (m_r, m_s, rep, float(np.median(nsc)))
        blk[lab] = (sec, v)
        print("%-9s %5d %10.4f %11.4f %11.4f %9.4f %9.2f배"
              % (lab, len(v), np.median(v), m_r, m_s, rep, m_r / rep))
        if nb:
            print("       상자고착/비수렴 %d개 제외" % nb)

    sigma_ans(blk, a.ratio, a.reported_ans)

    print()
    print("[스캔 수 환산]  ZA 블록 %g 스캔 대 ambient 빈 %g 스캔 — 광자잡음은 √N"
          % (out[next(iter(out))][3] if out else np.nan, a.amb_scans))
    print("%-9s %13s %13s %11s %11s"
          % ("채널", "σ(ZA, 실측)", "σ(ambient 환산)", "보고 σ", "환산/보고"))
    for lab, (m_r, m_s, rep, nz) in out.items():
        conv = m_r * np.sqrt(nz / a.amb_scans)
        print("%-9s %13.4f %13.4f %11.4f %9.2f배"
              % (lab, m_r, conv, rep, conv / rep))
    print()
    print("  ⚠ 환산은 **광자잡음만** √N 로 준다고 가정한다. 제로에어 바닥에는")
    print("     I₀ 보간 오차도 들어 있고 그건 스캔 수로 안 준다 — 환산값은")
    print("     **하한**이고, 실측 σ(ZA) 가 상한이다.")
    print("  ⚠ 참값이 0 이므로 `중앙(편향)` 열이 0 에서 멀면 그 자체가 결과다.")


if __name__ == "__main__":
    main()
