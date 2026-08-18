"""tools/design_window.py — 핏창 사전설계 CLI (핏 결과 없이 최적 창 추천).

완전 처음 피팅하는 상황을 전제: 레퍼런스 + 웨이브칼 + 알파만으로 창·poly를 추천한다.

사용:  python tools/design_window.py [키]   (키 목록은 tools/channel_map.json 참조)
"""
import os
import sys
import json

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import window_designer as WD
from tools import optimize_params as OP

N_SCANS = 15


def main():
    key = (sys.argv[1] if len(sys.argv) > 1 else "cold").lower()
    scen = json.load(open(OP.FITSET, encoding="utf-8"))
    ch = OP.pick_channel(scen, key)
    scans, n_total = OP.gather_scans(key, N_SCANS)
    eng = OP.build_engine_from_config(ch)

    wave = scans[0][0]
    alphas = np.array([s[1] for s in scans if len(s[1]) == len(wave)])
    T_C = float(np.median([s[2] for s in scans]))
    P_mbar = float(np.median([s[3] for s in scans]))
    species = list(eng.gas_list)

    print("#" * 96)
    print(f"# {ch['data_label']}  refs={species}  스캔 {len(alphas)}/{n_total}  "
          f"T={T_C:.1f}°C P={P_mbar:.0f}mbar   ※핏 전혀 안 함(사전설계)")
    print("#" * 96)

    starts = np.arange(424.0, 452.1, 2.0)
    ends = np.arange(456.0, 484.1, 2.0)
    rows, meta = WD.scan_windows(eng, alphas, species, wave, T_C, P_mbar,
                                 starts, ends, polys=None, target="NO2")
    print(f"\n노이즈: median σ_α={meta['noise_median']:.3e}, 잔차 자기상관 ρ={meta['rho']:.2f} "
          f"(ρ가 크면 유효 자유도가 줄어 넓은 창 과대평가가 자동 억제됨)")

    print(f"\n[사전설계 랭킹]  MDL=예측 NO2 1σ 검출한계(낮을수록 좋음)")
    print(f"  {'창(nm)':>16} {'폭':>5} {'poly':>4} {'MDL(ppb)':>9} {'cond':>9} {'multR':>6} {'chi':>5}")
    print("  " + "-" * 66)
    for r in rows[:12]:
        print(f"  {r['lo_nm']:7.1f}-{r['hi_nm']:6.1f} {r['width_nm']:5.1f} {r['poly']:>4} "
              f"{r['mdl_ppb']:9.4f} {r['cond']:9.1e} {r['multiple_R']:6.3f} {r['chi']:5.2f}"
              + ("  ← " + r["gate_reason"] if r["gated"] else ""))

    # 현재 사용자 창은 이 랭킹에서 어디쯤인가
    pmn, pmx = int(ch["f_min"]), int(ch["f_max"])
    cur = [r for r in rows if abs(r["px_min"] - pmn) <= 12 and abs(r["px_max"] - pmx) <= 12]
    if cur:
        c = min(cur, key=lambda r: r["mdl_ppb"])
        print(f"\n[현재 사용자 창] {wave[pmn]:.1f}-{wave[pmx]:.1f}nm poly{ch['poly_deg']} "
              f"→ 근사 후보 {c['lo_nm']:.1f}-{c['hi_nm']:.1f} poly{c['poly']}: "
              f"MDL={c['mdl_ppb']:.4f}ppb, 순위 {rows.index(c)+1}/{len(rows)}")

    # 레퍼런스 취사(핏 없이): O4를 넣으면 이득인가?
    print(f"\n[레퍼런스 취사 — 핏 없이 판단]")
    o4p = OP.ref_path(key, "Ref_O4_Dynamic-ILS-Applied.dat")
    if os.path.exists(o4p) and "O4" not in eng.gas_list:
        eng.add_reference(name="O4", filepath=o4p,
                          wave_nm=np.asarray(eng._wave_axis).flatten(), multiplier=1.0)
        eng.apply_ils_convolution(0.0)
    best = rows[0]
    cmp = WD.compare_species(eng, alphas, species, "O4", wave, T_C, P_mbar,
                             best["px_min"], best["px_max"], best["poly"])
    print(f"  최적창 {best['lo_nm']:.1f}-{best['hi_nm']:.1f}nm poly{best['poly']} 기준:")
    print(f"    O4 없이: MDL={cmp['without']['mdl_ppb']:.4f}ppb (multR {cmp['without']['multiple_R']:.3f})")
    print(f"    O4 포함: MDL={cmp['with']['mdl_ppb']:.4f}ppb (multR {cmp['with']['multiple_R']:.3f})")
    print(f"    → 비율 {cmp['ratio']:.3f}  판정: **{cmp['verdict']}**")


if __name__ == "__main__":
    main()
