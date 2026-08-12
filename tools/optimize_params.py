"""tools/optimize_params.py — 파라미터 자동 최적화 CLI(헤드리스 검증용).

사용자 FitSet json(레퍼런스·핏레인지 고정)을 baseline으로, core/param_optimizer로
poly 차수 + ref별 shift/squeeze 정책·크기를 자동 판정한다.

사용:  python tools/optimize_params.py [cold|ans|pns]   (기본 cold)

엔진 빌드는 app_window._build_engine_from_config를 **그대로 복제**(wavecal이 축,
add_reference(wave_nm=wave, multiplier=10^mult), ILS 0) — 헤드리스=GUI 보장.
"""
import os
import sys
import json
import glob

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.engine import UniversalEngine
from core.doas_fit import DoasFitter
from core import param_optimizer as PO
from tools.residual_compare import load_alpha

FITSET = r"C:\Doasis_Work\Output\fit setting\FitSet_ANs[430-466nm_P4]_PNs[444-471nm_P3]_cold[438-466nm_P4]_Std.json"

# data_label → (알파 glob, 골든/표본일 필터)
GOLDEN_COLD = {f"2026-{m:02d}-{d:02d}"
               for (m, d) in [(5, x) for x in range(26, 32)] + [(6, x) for x in range(1, 14)]}
ALPHA = r"C:\Doasis_Work\Output\alpha"
ALPHA_BIN = "60s"   # Alpha Generator의 avg_sec=60 기본값과 일치(gui/worker.py). "10s" 폴더도 있으나 비표준.
CHAN_ALPHA = {
    "cold": (os.path.join(ALPHA, ALPHA_BIN, "cold", "*", "*_cold_alpha_trace.dat"), GOLDEN_COLD),
    "ans":  (os.path.join(ALPHA, ALPHA_BIN, "hot", "ch1", "*", "*_ANs_alpha_trace.dat"), None),
    "pns":  (os.path.join(ALPHA, ALPHA_BIN, "hot", "ch2", "*", "*_PNs_alpha_trace.dat"), None),
}
LABEL2KEY = {"cold": "cold", "ans": "ans", "pns": "pns"}
# key → wavecal 폴더명. FitSet json의 data_label은 뒤바뀔 수 있어(§14-D, 실측 확인) 신뢰 불가 —
# 반드시 wl_path(roi1/roi2/cold)로 채널을 매칭한다. roi1=ANs, roi2=PNs.
KEY2WLDIR = {"cold": "cold", "ans": "roi1", "pns": "roi2"}
N_SCANS = 12
POLYS = [2, 3, 4, 5, 6, 8]


def load_wavecal(path):
    """app_window._load_wavecal_array 복제."""
    try:
        try:
            df = pd.read_csv(path, sep=r"\s+", header=None)
        except Exception:
            df = pd.read_csv(path, sep=",", header=None)
        for i in range(df.shape[1]):
            col = pd.to_numeric(df.iloc[:, i], errors="coerce").dropna()
            if len(col) > 10:
                return col.values.flatten()
    except Exception:
        pass
    return None


def build_engine_from_config(cfg):
    """app_window._build_engine_from_config 복제(순수)."""
    eng = UniversalEngine()
    wave = load_wavecal(cfg.get("wl_path", ""))
    if wave is not None:
        eng.set_wavelength_axis(wave)
    for ref in cfg.get("refs", []):
        p = ref.get("path", "")
        if os.path.exists(p):
            try:
                eng.add_reference(name=ref["name"], filepath=p, wave_nm=wave,
                                  multiplier=10.0 ** ref.get("mult", 0))
            except Exception as e:            # noqa: BLE001
                print(f"[engine] ref 실패 {ref.get('name')}: {e}")
    try:
        eng.apply_ils_convolution(0.0)
    except Exception:
        pass
    return eng


def pick_channel(scen, key):
    """wl_path(roi1/roi2/cold)로 채널 매칭. data_label은 쓰지 않는다 — FitSet json에서
    라벨이 실제 채널과 뒤바뀌어 저장된 사례가 있다(§14-D, roi1이 'PNs'로 잘못 저장됨)."""
    wldir = KEY2WLDIR[key]
    for ch in scen["channels"].values():
        if wldir in str(ch.get("wl_path", "")).replace("\\", "/").split("/"):
            return ch
    raise SystemExit(f"wl_path에 '{wldir}' 폴더를 쓰는 채널 없음 (key='{key}')")


def gather_scans(key, n):
    pattern, day_filter = CHAN_ALPHA[key]
    files = sorted(glob.glob(pattern))
    if day_filter is not None:
        files = [f for f in files
                 if os.path.basename(os.path.dirname(f)) in day_filter]
    if not files:
        raise SystemExit(f"알파 없음: {pattern}")
    pick = files[:: max(1, len(files) // n)][:n]
    return [load_alpha(fp) for fp in pick], len(files)


def gather_consecutive(key, n):
    """시간상 인접한 스캔 블록(한 폴더 내 연번) — step_limit 추정 전용.
    날짜별로 흩뿌린 표본으로 Δshift를 재면 과대추정되므로 반드시 연속으로."""
    pattern, day_filter = CHAN_ALPHA[key]
    files = sorted(glob.glob(pattern))
    if day_filter is not None:
        files = [f for f in files
                 if os.path.basename(os.path.dirname(f)) in day_filter]
    if not files:
        return []
    # 파일이 가장 많은 날(연속성 최대) 선택
    from collections import Counter
    day = Counter(os.path.dirname(f) for f in files).most_common(1)[0][0]
    block = sorted(f for f in files if os.path.dirname(f) == day)[:n]
    out = []
    for fp in block:
        try:
            out.append(load_alpha(fp))
        except Exception:                 # noqa: BLE001
            pass
    return out


def nm_to_px(wave, nm):
    return int(np.argmin(np.abs(np.asarray(wave, float) - nm)))


def main():
    key = (sys.argv[1] if len(sys.argv) > 1 else "cold").lower()
    scen = json.load(open(FITSET, encoding="utf-8"))
    ch = pick_channel(scen, key)
    rp = ch["ref_props"]
    step_limit = float(ch.get("step_limit", 0.5))
    poly0 = int(ch["poly_deg"])

    scans, n_total = gather_scans(key, N_SCANS)
    eng = build_engine_from_config(ch)
    fitter = DoasFitter(eng)
    wave0 = scans[0][0]
    # ⚠️ FitSet json은 f_min/f_max(px)와 fit_start_nm/fit_end_nm이 **불일치**한다.
    # 앱의 실제 저장 결과 헤더("Fit Range: Pixel 774-1550")로 확인한 결과 **px 필드가 진짜**다.
    # (cold: px 774-1550 = 438.4-475.8nm ≠ nm필드 438.0-465.8. nm필드는 스테일.)
    px_min, px_max = int(ch["f_min"]), int(ch["f_max"])
    target = "NO2"

    print("#" * 100)
    # 헤더는 CLI key로 표기(ch['data_label']은 json 안에서 뒤바뀌어 있을 수 있어 안 씀 — pick_channel 주석 참조).
    print(f"# {key}  refs={list(eng.gas_list)}  창 {ch['fit_start_nm']}-{ch['fit_end_nm']}nm "
          f"(px {px_min}-{px_max})  baseline poly{poly0}  스캔 {len(scans)}/{n_total}")
    print("#" * 100)

    # ── baseline 평가 ──
    base = PO.evaluate(scans, eng, fitter, rp, px_min, px_max, poly0, step_limit, target)
    print(f"[baseline] poly{poly0}: NO2={base['conc']:.1f}ppb  perr_rel={base['perr_rel']:.3f}  "
          f"rms/sig={base['rms_sig']*100:.1f}%  |ac1|={abs(base['autocorr1']):.2f}  n_free={base['n_free']}")
    for g in eng.gas_list:
        m, s = base["shift_dist"][g]
        print(f"           {g:8s} 핏shift {m:+.2f}±{s:.2f}px")

    # ── A-1: poly 차수 무릎점 ──
    rec_poly, ladder = PO.optimize_poly(scans, eng, fitter, rp, px_min, px_max,
                                        POLYS, step_limit, target)
    print(f"\n[poly 사다리]  (무릎점 추천 = poly{rec_poly})")
    print(f"  {'poly':>4} {'NO2ppb':>8} {'rms/sig':>8} {'|ac1|':>6} {'conc_cv':>8}")
    for r in ladder:
        mark = " ←추천" if r["poly"] == rec_poly else ""
        print(f"  {r['poly']:>4} {r['conc']:>8.1f} {r['rms_sig']*100:>7.1f}% "
              f"{abs(r['autocorr1']):>6.2f} {r['conc_cv']*100:>7.1f}%{mark}")

    # ── A-2: target shift 크기(넓게 풀어 분포로 결정) ──
    print(f"\n[NO2 shift 크기 자동결정]  (현재 설정 {rp[target]['sh_mode']} {rp[target]['sh_val']})")
    sh = PO.recommend_shift(scans, eng, fitter, rp, px_min, px_max, rec_poly, target)
    print(f"  → {sh['reason']}")

    # ── A-3: squeeze 크기 ──
    print(f"\n[NO2 squeeze 크기 자동결정]  (현재 {rp[target]['sq_mode']} {rp[target]['sq_val']})")
    sq = PO.recommend_squeeze(scans, eng, fitter, rp, px_min, px_max, rec_poly,
                              target, step_limit=step_limit)
    print(f"  → {sq['reason']}")

    # ── A-4: step_limit (연속 스캔 블록 필요) ──
    print(f"\n[step_limit 자동결정]  (현재 {step_limit})  ※연속 스캔으로 측정")
    consec = gather_consecutive(key, 20)
    if consec:
        st = PO.recommend_step_limit(consec, eng, fitter, rp, px_min, px_max, rec_poly, target)
        print(f"  → {st['reason']}")
    else:
        print("  → 연속 스캔 확보 실패")

    # ── A-5: 2차 ref Link vs 독립 ──
    print(f"\n[2차 레퍼런스 shift 정책]")
    for sec in eng.gas_list:
        if sec == target:
            continue
        dec = PO.recommend_secondary_link(scans, eng, fitter, rp, px_min, px_max,
                                          rec_poly, sec, target, step_limit)
        print(f"  {sec:8s}: {dec['reason']}")


if __name__ == "__main__":
    main()
