"""tools/build_fitset.py — 맨바닥 FitSet 자동 생성 CLI + 사용자 설정 대조.

세팅 입력 없이 (웨이브칼 + 레퍼런스폴더 + 알파)만으로 FitSet을 만들고,
사용자가 손으로 만든 FitSet과 나란히 비교해 **성능을 정직하게 보고**한다.

사용:  python tools/build_fitset.py [키]   (키 목록은 tools/channel_map.json 참조)
"""
import os
import sys
import json
import glob

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import fitset_builder as FB
from tools import optimize_params as OP


def _latest_wavecal(wl_dir):
    """폴더 안 가장 최근 Calib_*.txt(날짜 찍힌 파일명을 코드에 안 박음 —
    app_window._channel_wave_cal과 같은 관례)."""
    cands = sorted(glob.glob(os.path.join(wl_dir, "Calib_*.txt")))
    if not cands:
        raise SystemExit(f"웨이브칼 없음: {wl_dir}\\Calib_*.txt")
    return cands[-1]


def main():
    key = (sys.argv[1] if len(sys.argv) > 1 else "cold").lower()
    OP.require_key(key)
    label = OP.KEY2LABEL.get(key, key)
    ref_dir = os.path.join(OP.WAVECAL_ROOT, OP.KEY2WLDIR[key])
    wl_path = _latest_wavecal(ref_dir)

    scans, n_total = OP.gather_scans(key, 12)
    consec = OP.gather_consecutive(key, 20)

    print("#" * 92)
    print(f"# 맨바닥 FitSet 생성 — {label}   입력: 웨이브칼 + {OP.KEY2WLDIR[key]}/Ref_*.dat + 알파 {len(scans)}개")
    print(f"#   (세팅 입력 없음. 사용자 FitSet 참조 안 함)")
    print("#" * 92)

    cfg, rep = FB.build_fitset(wl_path, ref_dir, scans, OP.load_wavecal,
                               consecutive_scans=consec, target="NO2",
                               label=label, progress=lambda m: print("  ·", m))

    print("\n[레퍼런스 취사]")
    for cd in rep["candidates"]:
        mark = "✓채택" if cd["name"] in rep["keep"] else "✗제외"
        L = next((l for l in rep["selection"] if l["name"] == cd["name"]), None)
        extra = ""
        if L:
            extra = (f"  {L['decision']:<20} F={L.get('F',0):8.1f}  "
                     f"RSS감소 {L.get('chi_gain',0)*100:+5.1f}%  MDL비 {L['ratio']:.3f}")
            if L.get("physics"):
                extra += f"   물리: {L['physics'][0][:60]}"
        print(f"  {mark} {cd['name']:8s} mult={cd['mult']:+3d} (peak {cd['peak']:.2e}){extra}")

    w = rep["window"]
    print(f"\n[핏창·poly]  {w['lo_nm']:.1f}-{w['hi_nm']:.1f}nm (px {w['px_min']}-{w['px_max']}) "
          f"poly{w['poly']}   MDL={w['mdl_ppb']:.4f}ppb  multR={w['multiple_R']:.3f}  chi={w['chi']:.2f}")
    sh = rep["shift"]
    print(f"[shift]   {sh['reason']}")
    if sh.get("center_mode"):
        print(f"          Center 모드: 중심 {sh['center_mode'][0]:+.2f} ± {sh['center_mode'][1]:.2f}px "
              f"(0을 품을 필요 없어 실측만큼 좁게)")
    if sh.get("widened_for_engine"):
        print(f"          ⚠엔진 제약: 워커가 shift 0에서 시작해 step씩 걸어가므로 범위에 0이 필요 → "
              f"[{sh['runnable'][0]}, {sh['runnable'][1]}]로 확장 (측정 최적은 [{sh['lb']}, {sh['ub']}])")
    print(f"[squeeze] {rep['squeeze']['reason']}")
    print(f"[step]    {rep['step']['reason']}")
    for l in rep["links"]:
        print(f"[link]    {l['secondary']:8s} {l['reason']}")

    out = os.path.join(ROOT, "scenarios", f"AutoFitSet_{label}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(cfg, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\n저장: {out}")

    # ── 사용자 설정과 대조(성능 측정) ──
    try:
        scen = json.load(open(OP.FITSET, encoding="utf-8"))
        # ⚠️라벨(data_label)은 핫 채널 정체성 이슈로 뒤바뀔 수 있다(ch1=ANs vs ch2=ANs 미해결).
        # 알파 폴더와 확실히 짝이 맞는 **wavecal 경로(roi1/roi2/cold)**로 매칭한다.
        u = next((v for v in scen["channels"].values()
                  if OP.KEY2WLDIR[key] in str(v.get("wl_path", "")).replace("\\", "/")), None)
        if u is None:
            u = OP.pick_channel(scen, key)
    except Exception:
        return
    wave = scans[0][0]
    print("\n" + "=" * 92)
    # 표시 라벨은 label(CLI key로 결정)을 쓴다 — u['data_label']은 json 안에서 뒤바뀌어 있을 수 있음(위 주석).
    print(f"{'항목':<16}{'자동 생성':<34}{'사용자 수동('+label+')':<34}")
    print("-" * 92)
    ur = ",".join(sorted(r["name"] for r in u["refs"]))
    ar = ",".join(sorted(r["name"] for r in cfg["refs"]))
    print(f"{'refs':<16}{ar:<34}{ur:<34}")
    am = ",".join(f"{r['name']}:{r['mult']}" for r in sorted(cfg["refs"], key=lambda x: x["name"]))
    um = ",".join(f"{r['name']}:{r['mult']}" for r in sorted(u["refs"], key=lambda x: x["name"]))
    print(f"{'mult':<16}{am:<34}{um:<34}")
    aw = f"{cfg['fit_start_nm']:.1f}-{cfg['fit_end_nm']:.1f}nm"
    uw = f"{wave[int(u['f_min'])]:.1f}-{wave[int(u['f_max'])]:.1f}nm"
    print(f"{'핏창':<16}{aw:<34}{uw:<34}")
    print(f"{'poly':<16}{str(cfg['poly_deg']):<34}{str(u['poly_deg']):<34}")
    print(f"{'step_limit':<16}{str(cfg['step_limit']):<34}{str(u['step_limit']):<34}")
    for g in sorted(set(list(cfg["ref_props"]) + list(u["ref_props"]))):
        a = cfg["ref_props"].get(g, {})
        b = u["ref_props"].get(g, {})
        astr = f"{a.get('sh_mode','-')} {a.get('sh_val','-')}"
        bstr = f"{b.get('sh_mode','-')} {b.get('sh_val','-')}"
        print(f"{'sh:'+g:<16}{astr:<34}{bstr:<34}")
    print("=" * 92)


if __name__ == "__main__":
    main()
