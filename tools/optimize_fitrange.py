"""tools/optimize_fitrange.py — Stage 1 핏레인지+poly 자동탐색 CLI(헤드리스 검증용).

core/fit_optimizer.search_fit_range를 실제 알파로 구동해 스코어카드 표를 찍는다.
GUI 얹기 전에 표가 물리적으로 말이 되는지 사람이 눈으로 확인하는 단계.

사용:
  python tools/optimize_fitrange.py cold      # Cold(골든 05-26~06-13)
  python tools/optimize_fitrange.py ans       # Hot ch1 = ANs
  python tools/optimize_fitrange.py pns       # Hot ch2 = PNs
  python tools/optimize_fitrange.py all

wavecal(refdir)은 **알파 실제 nm축을 각 Calib 범위와 겹쳐 자동 매칭**한다
(핫 채널 ch↔roi 꼬임을 추측 없이 우회 — 선택 결과를 표에 찍는다).
"""
import os
import sys
import glob

import numpy as np
from scipy.interpolate import interp1d

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.residual_compare import load_alpha, build_engine, WV, _read_col
from core.doas_fit import DoasFitter
from core.fit_optimizer import search_fit_range

ALPHA = r"C:\Doasis_Work\Output\alpha"

# 채널 정의: alpha glob, 파일패턴, baseline(px_min,px_max,poly), 표본일 필터(있으면)
GOLDEN_COLD = {f"2026-{m:02d}-{d:02d}"
               for (m, d) in [(5, x) for x in range(26, 32)] + [(6, x) for x in range(1, 14)]}
CHANNELS = {
    "cold": dict(pattern=os.path.join(ALPHA, "cold", "*", "*_cold_alpha_trace.dat"),
                 baseline=(775, 1550, 4), day_filter=GOLDEN_COLD, label="Cold"),
    "ans":  dict(pattern=os.path.join(ALPHA, "hot", "ch1", "*", "*_ANs_alpha_trace.dat"),
                 baseline=(900, 1450, 3), day_filter=None, label="Hot-ANs (ch1)"),
    "pns":  dict(pattern=os.path.join(ALPHA, "hot", "ch2", "*", "*_PNs_alpha_trace.dat"),
                 baseline=(600, 1270, 4), day_filter=None, label="Hot-PNs (ch2)"),
}
REFDIRS = ["cold", "roi1", "roi2"]
N_SCANS = 12
POLYS = [3, 4, 6, 8]

# Cold ref_props(시나리오 CH1) — 세 채널 공통 사용(H2O·O4는 NO2에 Link)
RP = {
    "NO2":    {"sh_mode": "Limit", "sh_val": "-2.0, 2.0", "sq_mode": "Limit",
               "sq_val": "-0.02, 0.02", "t_ref": 25.0, "t_coeff": 0.0},
    "CHOCHO": {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2",
               "t_ref": 25.0, "t_coeff": 0.0},
    "H2O":    {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2",
               "t_ref": 25.0, "t_coeff": 0.0},
    "O4":     {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2",
               "t_ref": 25.0, "t_coeff": 0.0},
}


def pick_refdir(wave):
    """알파 nm축과 겹침이 가장 큰 wv_cal 폴더 선택(추측 없이 데이터로 매칭)."""
    wlo, whi = float(np.min(wave)), float(np.max(wave))
    best, best_ov = None, -1.0
    for rd in REFDIRS:
        cs = glob.glob(os.path.join(WV, rd, "Calib*.txt"))
        if not cs:
            continue
        c = _read_col(cs[0])
        clo, chi = float(np.min(c)), float(np.max(c))
        ov = max(0.0, min(whi, chi) - max(wlo, clo))
        if ov > best_ov:
            best, best_ov = rd, ov
    return best, (wlo, whi)


def gather_scans(cfg, n):
    files = sorted(glob.glob(cfg["pattern"]))
    if cfg["day_filter"] is not None:
        files = [f for f in files
                 if os.path.basename(os.path.dirname(f)) in cfg["day_filter"]]
    if not files:
        raise SystemExit(f"알파 없음: {cfg['pattern']}")
    pick = files[:: max(1, len(files) // n)][:n]
    scans = []
    for fp in pick:
        try:
            scans.append(load_alpha(fp))
        except Exception as e:            # noqa: BLE001
            print(f"  skip {os.path.basename(fp)}: {e}")
    return scans, len(files)


def make_windows(baseline, n_pix):
    """baseline 중심 coarse 그리드(채널별 픽셀범위에 맞춰)."""
    bmn, bmx, _ = baseline
    mins = sorted({max(0, bmn + d) for d in (-150, -75, 0, 75)})
    maxs = sorted({min(n_pix - 1, bmx + d) for d in (-150, 0, 100, 200)})
    return [(mn, mx) for mn in mins for mx in maxs if mx - mn >= 300]


def run(key):
    cfg = CHANNELS[key]
    scans, n_total = gather_scans(cfg, N_SCANS)
    wave0 = scans[0][0]
    refdir, (wlo, whi) = pick_refdir(wave0)
    n_pix = len(wave0)
    baseline = cfg["baseline"]

    print("\n" + "#" * 108)
    print(f"# {cfg['label']}  |  스캔 {len(scans)}/{n_total}  |  픽셀 {n_pix}  "
          f"|  알파 nm [{wlo:.1f}, {whi:.1f}]  →  wavecal='{refdir}'  |  baseline={baseline}")
    print("#" * 108)

    eng = build_engine(refdir, wave0)
    fitter = DoasFitter(eng)
    rp = {g: RP[g] for g in RP if g in eng.gas_list}

    windows = make_windows(baseline, n_pix)
    rows = search_fit_range(scans, eng, fitter, rp, windows, POLYS,
                            step_limit=0.5, target="NO2", baseline=baseline)

    print(f"{'rank':>4} {'win_px':>11} {'poly':>4} {'NO2ppb':>8} {'Δ%':>6} "
          f"{'perr':>6} {'perrWN':>7} {'cDev':>6} {'|ac1|':>6} "
          f"{'rms/sig':>7} {'score':>8} {'gate':>14}")
    print("-" * 110)
    for i, r in enumerate(rows):
        win = f"{r['px_min']}-{r['px_max']}"
        d = r.get("d_conc_pct", float("nan"))
        sc = r["score"] if r["score"] < 1e5 else float("inf")
        print(f"{i+1:>4} {win:>11} {r['poly']:>4} "
              f"{r['conc']:>8.1f} {d:>6.1f} {r['perr_rel']:>6.3f} {r['perr_wn']:>7.2f} "
              f"{r['consensus_dev']:>6.2f} {abs(r['autocorr1']):>6.2f} "
              f"{r['rms_sig']*100:>6.1f}% {sc:>8.2f} {r['gate_reason']:>14}")

    b = next((r for r in rows if (r["px_min"], r["px_max"], r["poly"]) == baseline), None)
    if b:
        print(f"[baseline] {b['px_min']}-{b['px_max']} poly{b['poly']}: "
              f"NO2={b['conc']:.1f}ppb perr={b['perr_rel']:.3f} "
              f"rank {rows.index(b)+1}/{len(rows)}")
    # 퇴화 진단: 전체 창 농도 중앙값 대비 이상치(2배/붕괴) 몇 셀인가
    anchor = rows[0].get("consensus", float("nan"))
    concs = np.array([r["conc"] for r in rows if np.isfinite(r["conc"])])
    n_gate = sum(1 for r in rows if r["gate_reason"] == "off_consensus")
    survivors = [r for r in rows if not r["gated"]]
    if len(concs):
        hi = int(np.sum(concs > 1.5 * anchor))
        lo = int(np.sum(concs < 0.5 * anchor))
        print(f"[consensus] 앵커 NO2={anchor:.1f}ppb  |  >1.5x {hi}셀  <0.5x {lo}셀  "
              f"→ off_consensus 게이트 {n_gate}셀  |  생존 {len(survivors)}/{len(rows)}")
    print("[top-3 생존]")
    for r in survivors[:3]:
        print(f"  창 {r['px_min']}-{r['px_max']} poly{r['poly']}: NO2={r['conc']:.1f}ppb "
              f"(Δ{r.get('d_conc_pct', float('nan')):+.1f}% vs 현재, cDev {r['consensus_dev']:.2f}, "
              f"perr {r['perr_rel']:.3f})")


def main():
    keys = sys.argv[1:] or ["cold"]
    if keys == ["all"]:
        keys = list(CHANNELS)
    for k in keys:
        if k not in CHANNELS:
            print(f"unknown channel: {k} (choose from {list(CHANNELS)} or 'all')")
            continue
        run(k)


if __name__ == "__main__":
    main()
