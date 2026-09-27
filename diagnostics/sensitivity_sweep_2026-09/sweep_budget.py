#!/usr/bin/env python
"""작업 A1 — 예산 배수(총 불확도 / 핏 전파 σ)의 **상수 민감도**.  (읽기 전용)

무엇을 재는가
------------
헤드라인 `1.72–2.68배`(= √(σ² + 구조²)/σ, σ = 핏 전파 0.0501 ppb, 정렬 기준
n=8,847)가 **우리가 고른 상수의 함수인지**를 OAT(one-at-a-time)로 잰다.
"더 좋은 설정을 찾는 것이 아니다" — 값을 바꾸지 않고 범위만 기록한다.

축 (기준에서 한 번에 하나씩)
---------------------------
  shift 상자 반폭   4 / 6 / 8 px      (기준 = 운영: ANs `-10,0.5` · PNs `-5,5`)
  스텝 리밋         on(기준 3.0) / off(1e6 = 전역 상자만 남음)
  시드 개수         5 / 13            (기준 = 운영 격자 0.25 px → ANs 43 · PNs 41점)
  다항 차수         poly−1 / poly+1   (기준 = 운영: ANs 4 · PNs 3)

⚠ 상자는 운영 상자의 **중심을 유지한 채 반폭만** 바꾼다(2026-09-23 사용자 결정).
ANs 운영 상자는 `-10, 0.5` 로 비대칭이고 실측 shift 가 −5.2 px 라, 0 중심으로
대칭화하면 '상자 폭' 이 아니라 '해를 잘라냈는가' 를 재게 된다.

⚠ 기준 step_limit 이 3.0 인 것은 **A1 헤드라인을 만든 런이 그랬기 때문**이다
(`production_budget.py --step-limit` 기본값). 운영 fitset 의 0.5 가 아니다.
A2(종료상태)는 운영 0.5 가 기준이다 — 두 숫자의 기준선이 서로 다르다.

비용 설계
--------
전 표본(8,847 빈)은 조합당 ~8분이라 9조합이면 비싸다. **고정 무작위 부분표본
n=1,000** 으로 돌리고, 기준 설정에서 부분표본이 전표본을 재현하는지 먼저 확인한다
(`--validate-only`). 표본은 시드 고정이라 모든 조합이 **같은 빈**을 본다.

재현
----
    python diagnostics/sensitivity_sweep_2026-09/sweep_budget.py --validate-only
    python diagnostics/sensitivity_sweep_2026-09/sweep_budget.py
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_BUDGET = os.path.join(_ROOT, "diagnostics", "i0_interp_2026-09", "production_budget.py")

# 기준 런의 산물. 이 폴더는 gitignore 대상(중간산물)이라 메인 체크아웃 경로를 쓴다.
_OPDIR = r"C:/GHL/CAESAR/diagnostics/i0_interp_2026-09"
FULL_CSV = os.path.join(_OPDIR, "production_budget_clockfixed.csv")
FITSET = (r"C:/Doasis_Work/Output/fit setting/"
          r"FitSet_ANs[430-462nm_P4]_PNs[444-471nm_P3]_cold[438-476nm_P4]_Std.json")

# §9-D 의 분모: 핏 전파 σ — 스캔 해상도. 구조항과 같은 해상도라 이 조합만 쓸 수 있다.
# ⚠ 조합마다 다시 재지 **않는다** — 분자(구조항)의 설정 의존성만 분리해 보기 위함이다.
DENOM_SIGMA = 0.0501

SUBSAMPLE_N = 1000
SUBSAMPLE_SEED = 20260923

# (config_id, box_half, step_limit, n_seeds, poly_delta) — None = 운영 기준값
CONFIGS = [
    ("base",          None, 3.0,  None, 0),
    ("box4",           4.0, 3.0,  None, 0),
    ("box6",           6.0, 3.0,  None, 0),
    ("box8",           8.0, 3.0,  None, 0),
    ("steplimit_off", None, 1e6,  None, 0),
    ("seeds5",        None, 3.0,     5, 0),
    ("seeds13",       None, 3.0,    13, 0),
    ("poly_minus1",   None, 3.0,  None, -1),
    ("poly_plus1",    None, 3.0,  None, +1),
]

COLS = ["config_id", "box_half_px", "step_limit", "n_seeds", "poly_delta",
        "n_subsample", "n_used", "structural_rSD", "structural_SD",
        "denom_sigma", "ratio_lo", "ratio_hi", "elapsed_s"]


def rsd(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) if v.size else np.nan


def read_budget(path):
    """production_budget CSV → (n_ok, rSD, SD). 본문 규칙대로 상자고착은 뺀다(§5)."""
    d = np.genfromtxt(path, delimiter=",", names=True)
    ok = np.asarray(d["ok"], float) > 0.5
    v = np.asarray(d["s_tri"], float)[ok]
    return int(ok.sum()), rsd(v), float(np.std(v, ddof=1))


def ratios(v_rsd, v_sd, denom=DENOM_SIGMA):
    f = lambda x: float(np.sqrt(denom ** 2 + x ** 2) / denom)
    return f(v_rsd), f(v_sd)


def make_subsample(out_path):
    """두 채널 **공통** ambient 빈에서 고정 시드로 n=1,000 을 뽑아 초 목록으로 저장.

    ⚠ 기준 CSV 의 `sec` 열은 `%.6g` 로 적혀 있어 초 단위 정밀도가 없다(1.18483e+07).
    그래서 표본은 캐시의 `amb_sec` 원본에서 뽑는다.
    """
    sa = np.round(np.load(os.path.join(_OPDIR, "_cache_hot_ANs_op.npz"))["amb_sec"], 3)
    sb = np.round(np.load(os.path.join(_OPDIR, "_cache_hot_PNs_op.npz"))["amb_sec"], 3)
    sec = np.intersect1d(sa, sb)
    rng = np.random.default_rng(SUBSAMPLE_SEED)
    pick = np.sort(rng.choice(len(sec), size=min(SUBSAMPLE_N, len(sec)), replace=False))
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join("%.3f" % s for s in sec[pick]) + "\n")
    return len(sec), len(pick)


def run_config(cfg_id, box, step, seeds, poly_d, sec_file, jobs, log_dir):
    out = os.path.join(log_dir, f"pb_{cfg_id}.csv")
    cmd = [sys.executable, _BUDGET, "--fitset", FITSET,
           "--rt-a", os.path.join(_OPDIR, "R_CH1_clockfixed.npz"),
           "--rt-b", os.path.join(_OPDIR, "R_CH2_clockfixed.npz"),
           "--cache-a", os.path.join(_OPDIR, "_cache_hot_ANs_op.npz"),
           "--cache-b", os.path.join(_OPDIR, "_cache_hot_PNs_op.npz"),
           "--step-limit", "%g" % step, "--out", out]
    if sec_file:
        cmd += ["--sec-file", sec_file]
    if box:
        cmd += ["--box-half", "%g" % box]
    if seeds:
        cmd += ["--n-seeds", "%d" % seeds]
    if poly_d:
        cmd += ["--poly-delta", "%d" % poly_d]
    if jobs:
        cmd += ["--jobs", "%d" % jobs]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    el = time.time() - t0
    with open(os.path.join(log_dir, f"pb_{cfg_id}.log"), "w", encoding="utf-8") as fh:
        fh.write(" ".join(cmd) + "\n\n" + (p.stdout or "") + "\n--- stderr ---\n"
                 + (p.stderr or ""))
    if p.returncode != 0 or not os.path.exists(out):
        raise SystemExit(f"ABSTAIN: {cfg_id} 실패 (rc={p.returncode}) — 로그를 볼 것\n"
                         + (p.stderr or "")[-2000:])
    return out, el


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--validate-only", action="store_true",
                    help="기준 설정에서 부분표본 대 전표본만 대조하고 멈춘다")
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--only", help="이 config_id 하나만 (쉼표 구분)")
    args = ap.parse_args()

    raw = os.path.join(_HERE, "raw")
    os.makedirs(raw, exist_ok=True)
    sec_file = os.path.join(raw, "subsample_secs.txt")
    n_full_rows, n_pick = make_subsample(sec_file)
    n_full, r_full, s_full = read_budget(FULL_CSV)
    print(f"[전표본] {FULL_CSV}")
    print(f"  캐시 공통 빈 {n_full_rows} · CSV 고착 제외 n={n_full} · rSD {r_full:.4f} · SD {s_full:.4f}"
          f" · 배수 {ratios(r_full, s_full)[0]:.3f}–{ratios(r_full, s_full)[1]:.3f}")
    print(f"[부분표본] n={n_pick} (seed {SUBSAMPLE_SEED}) → {sec_file}")

    # ── 1단계: 기준 설정에서 부분표본이 전표본을 재현하나 ──
    out, el = run_config("base", None, 3.0, None, 0, sec_file, args.jobs, raw)
    n_sub, r_sub, s_sub = read_budget(out)
    lo_f, hi_f = ratios(r_full, s_full)
    lo_s, hi_s = ratios(r_sub, s_sub)
    print(f"\n[검증] 기준 설정 · 부분표본 {n_sub} 빈 · {el:.0f} s")
    print("%-18s %10s %10s %10s %10s" % ("", "n", "rSD", "SD", "배수"))
    print("%-18s %10d %10.4f %10.4f %6.3f–%.3f" % ("전표본", n_full, r_full, s_full, lo_f, hi_f))
    print("%-18s %10d %10.4f %10.4f %6.3f–%.3f" % ("부분표본", n_sub, r_sub, s_sub, lo_s, hi_s))
    dv = lambda a, b: 100.0 * (a / b - 1.0)
    print("%-18s %10s %+9.1f%% %+9.1f%% %+5.1f%%/%+.1f%%"
          % ("편차", "", dv(r_sub, r_full), dv(s_sub, s_full), dv(lo_s, lo_f), dv(hi_s, hi_f)))

    with open(os.path.join(_HERE, "subsample_validation.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sample", "n_bins", "structural_rSD", "structural_SD",
                    "denom_sigma", "ratio_lo", "ratio_hi"])
        w.writerow(["full_8847", n_full, "%.6g" % r_full, "%.6g" % s_full,
                    DENOM_SIGMA, "%.6g" % lo_f, "%.6g" % hi_f])
        w.writerow(["subsample_%d" % n_pick, n_sub, "%.6g" % r_sub, "%.6g" % s_sub,
                    DENOM_SIGMA, "%.6g" % lo_s, "%.6g" % hi_s])
        w.writerow(["deviation_pct", "", "%.3f" % dv(r_sub, r_full),
                    "%.3f" % dv(s_sub, s_full), "", "%.3f" % dv(lo_s, lo_f),
                    "%.3f" % dv(hi_s, hi_f)])
    print("→ subsample_validation.csv")

    if args.validate_only:
        print("\n--validate-only — 여기서 멈춘다. 편차를 보고 계속할지 결정할 것.")
        return

    # ── 2단계: 나머지 조합 ──
    rows = []
    want = set(args.only.split(",")) if args.only else None
    for cfg_id, box, step, seeds, poly_d in CONFIGS:
        if want and cfg_id not in want:
            continue
        if cfg_id == "base":
            path, e = out, el
        else:
            print(f"\n[{cfg_id}] 실행 중…", flush=True)
            path, e = run_config(cfg_id, box, step, seeds, poly_d, sec_file, args.jobs, raw)
        n, r, s = read_budget(path)
        lo, hi = ratios(r, s)
        rows.append(dict(config_id=cfg_id, box_half_px=("op" if box is None else box),
                         step_limit=step, n_seeds=("op" if seeds is None else seeds),
                         poly_delta=poly_d, n_subsample=n_pick, n_used=n,
                         structural_rSD="%.6g" % r, structural_SD="%.6g" % s,
                         denom_sigma=DENOM_SIGMA, ratio_lo="%.6g" % lo,
                         ratio_hi="%.6g" % hi, elapsed_s="%.0f" % e))
        print(f"  [{cfg_id}] n={n} · rSD {r:.4f} · SD {s:.4f} · 배수 {lo:.3f}–{hi:.3f} · {e:.0f} s")

    dst = os.path.join(_HERE, "budget_ratio_by_config.csv")
    with open(dst, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"\n→ {dst}  ({len(rows)} 조합)")
    los = [float(r["ratio_lo"]) for r in rows]
    his = [float(r["ratio_hi"]) for r in rows]
    print("  배수 하한 %.3f–%.3f · 상한 %.3f–%.3f  (판정은 하지 않는다)"
          % (min(los), max(los), min(his), max(his)))


if __name__ == "__main__":
    main()
