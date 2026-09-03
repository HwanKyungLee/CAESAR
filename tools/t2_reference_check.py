"""tools/t2_reference_check.py — Tier-2 물리 심판을 O4 사례로 검증.

"O4를 넣을지 뺄지"를 안정성(Tier-1)이 아니라 물리(Tier-2: 공선성·계수상수성·트레이드오프)로
판정한다. 결과가 사용자 직관(O4=과적합)과 맞으면 로직이 물리로 옳은 결정을 내린다는 증거.

사용:  python tools/t2_reference_check.py [키] (--allow-negative-gas | --nonnegative-gas)
"""
import os
import sys
import json
import glob
import argparse

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.doas_fit import DoasFitter
from core import fit_physics as FP
from tools import optimize_params as OP   # build_engine_from_config, pick_channel, gather_scans, nm_to_px, ref_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("key", nargs="?", default="cold")
    policy = parser.add_mutually_exclusive_group(required=True)
    policy.add_argument("--allow-negative-gas", action="store_true")
    policy.add_argument("--nonnegative-gas", action="store_true")
    parser.add_argument("--override-fitset-policy", action="store_true",
                        help="intentionally override a conflicting policy stored in the FitSet")
    args = parser.parse_args()
    key = args.key.lower()
    allow_negative_gas = args.allow_negative_gas
    scen = json.load(open(OP.FITSET, encoding="utf-8"))
    ch = OP.pick_channel(scen, key)
    stored_policy = ch.get("allow_negative_gas")
    if stored_policy is not None and not isinstance(stored_policy, bool):
        parser.error("FitSet allow_negative_gas must be boolean")
    if stored_policy is not None and stored_policy != allow_negative_gas \
            and not args.override_fitset_policy:
        parser.error("CLI gas policy conflicts with FitSet; use --override-fitset-policy intentionally")
    policy_source = ("explicit CLI override of FitSet" if stored_policy is not None
                     and stored_policy != allow_negative_gas else
                     "FitSet confirmed by CLI" if stored_policy is not None else "explicit CLI (legacy FitSet)")
    rp = dict(ch["ref_props"])
    step_limit = float(ch.get("step_limit", 0.5))
    poly = int(ch["poly_deg"])

    scans, n_total = OP.gather_scans(key, 15)
    eng = OP.build_engine_from_config(ch)              # 사용자 3 refs (O4 없음)
    base_gas = list(eng.gas_list)

    # 후보 O4 추가(엔진에) — 각 채널 wv_cal 폴더의 O4 레퍼런스(사용자 FitSet엔 없음)
    o4p = OP.ref_path(key, "Ref_O4_Dynamic-ILS-Applied.dat")
    if os.path.exists(o4p):
        eng.add_reference(name="O4", filepath=o4p,
                          wave_nm=np.asarray(eng._wave_axis).flatten(), multiplier=1.0)
        eng.apply_ils_convolution(0.0)
    rp_with = dict(rp)
    rp_with["O4"] = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link",
                     "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}

    fitter = DoasFitter(eng)
    wave0 = scans[0][0]
    px_min = OP.nm_to_px(wave0, float(ch["fit_start_nm"]))
    px_max = OP.nm_to_px(wave0, float(ch["fit_end_nm"]))

    print("#" * 96)
    print(f"# gas coefficient policy: allow_negative_gas={allow_negative_gas} ({policy_source})")
    print(f"# {ch['data_label']}  창 {ch['fit_start_nm']}-{ch['fit_end_nm']}nm  poly{poly}  "
          f"사용자refs={base_gas}  +후보 O4  스캔 {len(scans)}/{n_total}")
    print("#" * 96)

    # ── 1) 차등단면 공선성(데이터 불필요) ──
    diag = FP.differential_collinearity(eng, list(eng.gas_list), px_min, px_max, poly)
    print("\n[1] 차등단면 공선성 (창 안 레퍼런스 기하)")
    print("  쌍별 |r|:")
    for (a, b), r in sorted(diag["pairwise"].items(), key=lambda kv: -kv[1]):
        star = "  ← NO2-O4" if {a, b} == {"NO2", "O4"} else ""
        print(f"    {a:7s}-{b:7s} |r|={r:.2f}{star}")
    print("  다중상관 R(나머지 전체로 흉내가능?):")
    for g, R in diag["multiple_R"].items():
        print(f"    {g:7s} R={R:.2f}" + ("  ← O4가 다른종 조합으로 재현됨" if g == "O4" and R > 0.9 else ""))

    # ── 2) 핏 계수 물리 건전성(O4 상수성·NO2 트레이드오프) ──
    health = FP.fitted_amount_health(scans, eng, fitter, rp_with, px_min, px_max,
                                     poly, step_limit, target="NO2",
                                     constant_species=("O4",),
                                     allow_negative_gas=allow_negative_gas)
    print("\n[2] 핏 계수 물리 건전성 (스캔 간)")
    print(f"    NO2  계수 CV = {health['target_cv']*100:.0f}%")
    for g in eng.gas_list:
        if g == "NO2":
            continue
        cvg = health["cv"].get(g, float("nan"))
        cc = health["corr_with_target"].get(g, float("nan"))
        note = ""
        if g == "O4":
            note = "  ← O4는 물리적으로 거의 상수여야 함"
        print(f"    {g:7s} 계수 CV = {cvg*100:5.0f}%   NO2와 상관 r={cc:+.2f}{note}")
    ar = health.get("abs_ratio", {})
    if ar:
        print("\n[2-B] ★절대량 앵커 (fitted N / 이론 상한) — 이론값을 아는 종만")
        for g, v in ar.items():
            flag = "  ← 물리적으로 불가능(과적합)" if v > 3.0 else "  ← 물리적으로 타당"
            print(f"    {g:7s} fitted/이론상한 = {v:.1f}배{flag}")

    # ── 3) 판정 ──
    verdict = FP.judge_reference(eng, fitter, scans, rp, rp_with,
                                 px_min, px_max, poly, step_limit,
                                 candidate="O4", target="NO2",
                                 allow_negative_gas=allow_negative_gas)
    print("\n[3] Tier-2 물리 판정 (안정성 아님)")
    print(f"    ▶ {verdict['verdict']}")
    for r in verdict["reasons"]:
        print(f"      · {r}")
    if not verdict["reasons"]:
        print("      · 공선성 낮고 계수 상수·트레이드오프 없음 → 물리적으로 포함 타당")


if __name__ == "__main__":
    main()
