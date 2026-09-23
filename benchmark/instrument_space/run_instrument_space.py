#!/usr/bin/env python
"""작업 B-3 — 벤치마크를 **계기 파라미터 공간**으로 넓혀 실패 양상이 지속되는지 본다.

무엇을 묻나
----------
지금의 벤치마크는 **우리 계기 한 점**에서 만들어졌다. 그래서 "보고 σ 가 산포보다
작다"·"shift 가 비식별이다"·"창을 바꾸면 답이 바뀐다" 가 **우리 창의 성질인지
방법의 성질인지** 구분되지 않는다. 좌표를 옮겨 가며 같은 세 지표를 재서 답한다.

지표 (지시서 B-2 · 전부 `score.py` 가 이미 계산한다 — 새 정의를 만들지 않는다)
  b_scatter_ratio      B_noise  — 산포 / 보고 σ. 1.0 이면 보고가 맞다
  d_unbounded_frac     D_identifiability — 비식별을 비식별이라고 말한 비율
  e_window_agreement   E_window — 두 창 답의 최대 불일치(상대)

⚠ **D 지표는 아직 반쪽이다.** `score.py` 는 `shift_sigma > 1 px` 또는 상자 끝
도달로 '비식별' 을 판정한다. 지시서가 요구한 **프로파일 우도 구간**은 아직
구현되지 않았으므로, 이 열은 그 구현 전의 대리값이다. 좌표 간 비교에는 쓸 수
있으나 절대값을 논문에 싣지 말 것.

⚠ **모든 좌표를 `--rebuild-sigma` 로 만든다.** ILS 축은 원본 고해상 단면에서
다시 convolve 해야 하는데, 그렇게 만든 HITRAN H2O 는 배포본 단면보다 피크가
약 2.5 % 크다(NO2·CHOCHO 는 상관 1.00000 으로 일치). 재조립 좌표와 배포본
좌표를 섞으면 그 2.5 % 가 축에 섞여 들어간다 — 그래서 **기준 좌표도 재조립**한다.
그 대신 이 표의 기준 좌표는 배포본 261 케이스와 **같지 않다**(H2O 만 다르다).

재현
----
    python benchmark/instrument_space/run_instrument_space.py --only baseline   # 소요시간
    python benchmark/instrument_space/run_instrument_space.py
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_BENCH_DIR = os.path.join(os.path.dirname(_HERE), "doas_benchmark_v1")
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_GENERATE = os.path.join(_BENCH_DIR, "generate.py")
_RUNNER = os.path.join(_ROOT, "diagnostics", "doas_benchmark_2026-09",
                       "run_augur_benchmark.py")
sys.path.insert(0, _BENCH_DIR)

# OAT — 기준 좌표에서 한 번에 하나씩. 값은 지시서 B-1 의 범위 그대로다.
BASE = dict(ils_scale=1.0, window_scale=1.0, pixel_dispersion_scale=1.0,
            noise_levels=[1.0, 2.0], poly_orders=[3], fit_poly_order=0)
GRID = [("baseline", {})]
GRID += [(f"ils{v:g}", dict(ils_scale=v)) for v in (0.5, 2.0)]
GRID += [(f"win{v:g}", dict(window_scale=v)) for v in (0.7, 1.3)]
GRID += [(f"disp{v:g}", dict(pixel_dispersion_scale=v)) for v in (0.7, 1.4)]
GRID += [("snr6", dict(noise_levels=[0.25, 0.5, 1.0, 2.0, 4.0, 8.0]))]
# 다항 차수는 **두 축**이다. 생성된 기저 차수(`poly_orders`)를 낮춰도 핏이 채널
# 차수로 그걸 정확히 흡수하므로 지표가 한 자리도 안 움직인다(2026-09-23 실측:
# genpoly2 가 기준과 소수 6자리까지 같다). 움직이는 축은 **핏 차수**다.
GRID += [("genpoly2", dict(poly_orders=[2]))]
GRID += [(f"fitpoly{v}", dict(fit_poly_order=v)) for v in (2, 4, 5, 6)]

COLS = ["coordinate_id", "ils_scale", "window_scale", "pixel_dispersion_scale",
        "noise_levels", "poly_orders", "fit_poly_order", "n_cases", "n_pixels_hot", "n_pixels_cold",
        "b_scatter_ratio_min", "b_scatter_ratio_max", "b_scatter_ratio_detail",
        "d_unbounded_frac", "d_shift_spread_px",
        "e_window_agreement", "e_inside_combined_sigma",
        "gen_s", "fit_s", "note"]


def sh(cmd, log_path):
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(" ".join(cmd) + "\n\n" + (p.stdout or "") + "\n--- stderr ---\n"
                 + (p.stderr or ""))
    if p.returncode != 0:
        raise SystemExit(f"ABSTAIN: 실패 (rc={p.returncode}) — {log_path}\n"
                         + (p.stderr or "")[-2000:])
    return time.time() - t0


def metrics(bench_dir, sub_path):
    import score as S
    man = pd.read_csv(os.path.join(bench_dir, "cases", "manifest.csv"))
    sub = pd.read_csv(sub_path)
    rep = S.score(man, sub)
    out = {}
    b = rep[rep.group.str.startswith("B_noise")]
    vals = [float(v) for v in b.value if np.isfinite(float(v))]
    out["b_scatter_ratio_min"] = min(vals) if vals else np.nan
    out["b_scatter_ratio_max"] = max(vals) if vals else np.nan
    out["b_scatter_ratio_detail"] = "|".join(
        "%s=%.3f" % (r.group.split(":")[-1].strip(), float(r.value)) for r in b.itertuples())
    d = rep[rep.group == "D_identifiability"]
    if len(d):
        n, m = str(d.value.iloc[0]).split("/")
        out["d_unbounded_frac"] = float(n) / max(float(m), 1)
        out["d_shift_spread_px"] = str(d.extra.iloc[0])
    e = rep[rep.group == "E_window"]
    if len(e):
        out["e_window_agreement"] = float(e.value.iloc[0])
        out["e_inside_combined_sigma"] = str(e.extra.iloc[0])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default=os.path.join(_HERE, "work"),
                    help="좌표별 생성 패키지와 제출본이 쌓이는 곳(gitignore)")
    ap.add_argument("--hitran-dir", default=os.path.join(_ROOT, "hitran_data"))
    ap.add_argument("--sigma", choices=("lin", "joint"), default="joint")
    ap.add_argument("--only", help="이 coordinate_id 만 (쉼표 구분)")
    ap.add_argument("--out", default=os.path.join(_HERE, "metrics_by_coordinate.csv"))
    args = ap.parse_args()

    os.makedirs(args.work, exist_ok=True)
    want = set(args.only.split(",")) if args.only else None
    rows, grid_meta = [], {}
    for cid, over in GRID:
        if want and cid not in want:
            continue
        cfg = dict(BASE, **over)
        pkg = os.path.join(args.work, cid)
        cmd = [sys.executable, _GENERATE, "--out", pkg, "--coordinate-id", cid,
               "--rebuild-sigma", "--hitran-dir", args.hitran_dir,
               "--ils-scale", "%g" % cfg["ils_scale"],
               "--window-scale", "%g" % cfg["window_scale"],
               "--pixel-dispersion-scale", "%g" % cfg["pixel_dispersion_scale"],
               "--noise-levels"] + ["%g" % v for v in cfg["noise_levels"]] + [
               "--poly-orders"] + ["%d" % v for v in cfg["poly_orders"]]
        if cfg["fit_poly_order"]:
            cmd += ["--fit-poly-order", "%d" % cfg["fit_poly_order"]]
        print(f"[{cid}] 케이스 생성…", flush=True)
        gen_s = sh(cmd, os.path.join(args.work, f"{cid}_generate.log"))
        sub = os.path.join(args.work, f"{cid}_submission.csv")
        print(f"[{cid}] 핏…", flush=True)
        fit_s = sh([sys.executable, _RUNNER, "--bench", pkg, "--sigma", args.sigma,
                    "--out", sub], os.path.join(args.work, f"{cid}_fit.log"))
        meta = json.load(open(os.path.join(pkg, "manifest.json"), encoding="utf-8"))
        r = dict({k: "" for k in COLS}, coordinate_id=cid,
                 ils_scale=cfg["ils_scale"], window_scale=cfg["window_scale"],
                 pixel_dispersion_scale=cfg["pixel_dispersion_scale"],
                 noise_levels=" ".join("%g" % v for v in cfg["noise_levels"]),
                 poly_orders=" ".join("%d" % v for v in cfg["poly_orders"]),
                 fit_poly_order=(cfg["fit_poly_order"] or "channel"),
                 n_cases=meta["n_cases"],
                 n_pixels_hot=meta["channels"]["hot_PNs"]["n_pixels"],
                 n_pixels_cold=meta["channels"]["cold"]["n_pixels"],
                 gen_s="%.0f" % gen_s, fit_s="%.0f" % fit_s,
                 note="D 열은 프로파일 우도 구간 구현 전의 대리값")
        r.update(metrics(pkg, sub))
        rows.append(r)
        grid_meta[cid] = dict(cfg, n_cases=meta["n_cases"],
                              channels=meta["channels"])
        print("  [%s] B %.3f–%.3f · D %s · E %s · %.0f+%.0f s"
              % (cid, r["b_scatter_ratio_min"], r["b_scatter_ratio_max"],
                 r["d_unbounded_frac"], r["e_window_agreement"], gen_s, fit_s), flush=True)

    with open(os.path.join(_HERE, "manifest_grid.json"), "w", encoding="utf-8") as fh:
        json.dump(dict(base=BASE, coordinates=grid_meta), fh, indent=2, ensure_ascii=False)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"\n→ {args.out}  ({len(rows)} 좌표)")


if __name__ == "__main__":
    main()
