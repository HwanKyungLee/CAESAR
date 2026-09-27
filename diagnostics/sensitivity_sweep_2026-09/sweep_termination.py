#!/usr/bin/env python
"""작업 A2 — 종료상태 분해(`CONVERGED/STEP_LIMITED/AT_BOUND`)의 **상수 민감도**. (읽기 전용)

무엇을 재는가
------------
헤드라인 `34.3 % = STEP_LIMITED 21.4 % + AT_BOUND 12.8 %` (2026-06-14 CH2/PNs,
8,446 스캔, `docs/AMT_코드검정_2026-09-17.md` §6)가 설정에 얼마나 의존하는지
OAT 로 잰다. **더 나은 설정을 찾지 않는다** — 재분배만 기록한다.

경로
----
`gui/worker.AnalysisWorker._fit_alpha_range` 를 **그대로** 부른다. 이게 운영
경로다: 스캔마다 격자 시딩을 하지 않고 **직전 스캔의 shift 를 다음 창의 앵커**로
쓰고 상자는 `앵커 ± step_limit ∩ 전역 sh_val` 이다. §6 의 실측이 재현한 것도 이
경로다(문서 부록 A-6: "스캔간 연속성까지 워커와 동일하게 재현").

⚠ **`시드 개수` 축은 이 숫자에 존재하지 않는다.** 격자 시딩(`_seed_shift`,
5/13/41점)은 `param_optimizer.fit_scan` 의 오프라인 경로에만 있고 운영 워커에는
없다. A1(예산 배수)에는 있다. 그래서 그 두 행은 값 없이 사유만 기록한다.

축 (기준 = 09-17 운영 fitset ch2)
  shift 상자 반폭   4 / 6 / 8 px   (기준 = 운영 `-5, 5` → 반폭 5, 중심 0)
  스텝 리밋         on(기준 0.5) / off(1e6 = 전역 상자만)
  다항 차수         poly−1(2) / poly+1(4)   (기준 3)

재현
----
    python diagnostics/sensitivity_sweep_2026-09/sweep_termination.py --limit 300   # 소요시간 확인
    python diagnostics/sensitivity_sweep_2026-09/sweep_termination.py
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import time
from collections import Counter

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_ROOT, os.path.join(_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PyQt6.QtCore import QCoreApplication                       # noqa: E402

_APP = QCoreApplication.instance() or QCoreApplication(sys.argv)

from core.data_io import DataIO                                 # noqa: E402
from core.fitset_builder import build_engine                    # noqa: E402
from gui.worker import AnalysisWorker                           # noqa: E402

FITSET = (r"C:/Doasis_Work/Output/fit setting/"
          r"FitSet_ANs[430-462nm_P4]_PNs[444-471nm_P3]_cold[438-476nm_P4]_Std.json")
ALPHA_DIR = r"C:/Doasis_Work/Output/alpha/10s/hot/ch2/2026-06-14"
CH_KEY = "2"

STATUSES = ("CONVERGED", "STEP_LIMITED", "AT_BOUND", "MAX_NFEV", "FAILED", "")

# (config_id, box_half, step_limit, poly_delta) — None = 운영 기준값
CONFIGS = [
    ("base",          None, None, 0),
    ("box4",           4.0, None, 0),
    ("box6",           6.0, None, 0),
    ("box8",           8.0, None, 0),
    ("steplimit_off", None,  1e6, 0),
    ("poly_minus1",   None, None, -1),
    ("poly_plus1",    None, None, +1),
]
# 값 없이 사유만 남기는 행 (위 docstring 참고)
NA_CONFIGS = [("seeds5", 5), ("seeds13", 13)]

COLS = ["config_id", "box_px", "step_limit", "n_seeds", "poly", "n_scans",
        "converged", "step_limited", "at_bound", "max_nfev", "failed", "other",
        "pct_converged", "pct_step_limited", "pct_at_bound", "pct_nonoptimal",
        "bound_params_top", "shift_p01", "shift_p50", "shift_p99",
        "no2_median_ppb", "elapsed_s", "note"]


def load_wavecal(path):
    arr = np.loadtxt(path, comments="#")
    return arr[:, -1] if arr.ndim == 2 else arr


def make_cfg(base_cfg, box_half, step_limit, poly_delta, target="NO2"):
    """운영 cfg → 이 조합의 cfg. 상자는 **중심 유지 · 반폭만** 바꾼다."""
    cfg = dict(base_cfg)
    cfg["ref_props"] = {g: dict(v) for g, v in base_cfg["ref_props"].items()}
    lo, hi = (float(v) for v in str(cfg["ref_props"][target]["sh_val"]).split(","))
    if box_half:
        c = 0.5 * (lo + hi)
        cfg["ref_props"][target]["sh_val"] = "%g, %g" % (c - box_half, c + box_half)
    if step_limit is not None:
        cfg["step_limit"] = float(step_limit)
    cfg["poly_deg"] = int(cfg["poly_deg"]) + int(poly_delta)
    return cfg


def build_worker(cfg):
    eng, wave = build_engine(cfg["wl_path"], cfg["refs"], load_wavecal)
    if not eng.is_engine_ready():
        raise SystemExit("ABSTAIN: 엔진이 준비되지 않았다 — 레퍼런스 경로를 볼 것")
    ng = len(eng.gas_list)
    pd = int(cfg["poly_deg"])
    p0 = [0.0, 1.0] + [0.1] * ng + [0.0] * (pd + 1)
    inf = [np.inf] * (2 + ng + pd + 1)
    w = AnalysisWorker(eng, [], int(cfg["f_min"]), int(cfg["f_max"]), p0,
                       ([-v for v in inf], inf), update_interval=-1, channel=2)
    w.ref_properties = cfg["ref_props"]
    w.step_limit = float(cfg["step_limit"])
    w.tikhonov_lambda = float(cfg.get("tikhonov_lambda", 0.0))
    w.use_robust_fitting = bool(cfg.get("use_robust", False))
    w.allow_negative_gas = bool(cfg.get("allow_negative_gas", True))
    w.fit_unit = "nm"
    w.fit_lo_nm = float(cfg["fit_start_nm"])
    w.fit_hi_nm = float(cfg["fit_end_nm"])
    w.qc_enabled = False          # QC 는 종료상태에 영향 없음 — NaN 회피용
    w.ok_rms_threshold = 0.10
    w.gas_temp_override = None
    w.tz_offset_sec = 0
    return w


def build_scans(alpha_dir, limit=0):
    scans, gi = [], 0
    for fp in sorted(glob.glob(os.path.join(alpha_dir, "*alpha_trace.dat"))):
        n = DataIO.count_alpha_rows(fp) if hasattr(DataIO, "count_alpha_rows") else None
        if n is None:
            with open(fp, encoding="utf-8", errors="replace") as fh:
                n = sum(1 for l in fh
                        if l.strip() and not l.startswith("#") and not l.startswith("row_idx"))
        for r in range(n):
            scans.append((gi, fp, r))
            gi += 1
            if limit and gi >= limit:
                return scans
    return scans


def tally(results):
    c = Counter()
    bp = Counter()          # AT_BOUND 행만 — 부록 A-1 의 "1085건 전부 squeeze" 가 이 열이다
    sh, no2 = [], []
    for _gi, r in results:
        st = str(r.get("Fit_Status") or "")
        c[st if st in STATUSES else "other"] += 1
        if st == "AT_BOUND" and r.get("Bound_Params"):
            bp[r["Bound_Params"]] += 1
        if "Shift" in r:
            sh.append(float(r["Shift"]))
        if r.get("NO2") is not None:
            no2.append(float(r["NO2"]))
    return c, bp, np.asarray(sh, float), np.asarray(no2, float)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fitset", default=FITSET)
    ap.add_argument("--alpha-dir", default=ALPHA_DIR)
    ap.add_argument("--ch-key", default=CH_KEY)
    ap.add_argument("--limit", type=int, default=0, help="스캔 수 상한(소요시간 확인용)")
    ap.add_argument("--only", help="이 config_id 만 (쉼표 구분)")
    ap.add_argument("--out", default=os.path.join(_HERE, "termination_by_config.csv"))
    args = ap.parse_args()

    base_cfg = json.load(open(args.fitset, encoding="utf-8"))["channels"][args.ch_key]
    scans = build_scans(args.alpha_dir, args.limit)
    print(f"[A2] {args.alpha_dir}")
    print(f"  스캔 {len(scans)} · 기준 sh_val {base_cfg['ref_props']['NO2']['sh_val']}"
          f" · poly {base_cfg['poly_deg']} · step_limit {base_cfg['step_limit']}")

    want = set(args.only.split(",")) if args.only else None
    rows = []
    for cfg_id, box, step, poly_d in CONFIGS:
        if want and cfg_id not in want:
            continue
        cfg = make_cfg(base_cfg, box, step, poly_d)
        w = build_worker(cfg)
        t0 = time.time()
        res, _traj, _ef = w._fit_alpha_range(scans, body_start=0, init_shift=0.0,
                                             etalon_freq=None)
        el = time.time() - t0
        c, bp, sh, no2 = tally(res)
        n = sum(c.values())
        pct = lambda k: 100.0 * c[k] / max(n, 1)
        nonopt = pct("STEP_LIMITED") + pct("AT_BOUND")
        rows.append(dict(
            config_id=cfg_id, box_px=("op" if box is None else box),
            step_limit=cfg["step_limit"], n_seeds="n/a", poly=cfg["poly_deg"],
            n_scans=n, converged=c["CONVERGED"], step_limited=c["STEP_LIMITED"],
            at_bound=c["AT_BOUND"], max_nfev=c["MAX_NFEV"], failed=c["FAILED"],
            other=c[""] + c["other"],
            pct_converged="%.2f" % pct("CONVERGED"),
            pct_step_limited="%.2f" % pct("STEP_LIMITED"),
            pct_at_bound="%.2f" % pct("AT_BOUND"),
            pct_nonoptimal="%.2f" % nonopt,
            bound_params_top=("|".join("%s:%d" % kv for kv in bp.most_common(3)) if bp else ""),
            shift_p01="%.4g" % (np.percentile(sh, 1) if sh.size else np.nan),
            shift_p50="%.4g" % (np.median(sh) if sh.size else np.nan),
            shift_p99="%.4g" % (np.percentile(sh, 99) if sh.size else np.nan),
            no2_median_ppb="%.6g" % (np.median(no2) if no2.size else np.nan),
            elapsed_s="%.0f" % el, note=""))
        print("  [%-14s] n=%d · CONV %.2f%% · STEP %.2f%% · BOUND %.2f%% "
              "(비최적 %.2f%%) · %s · %.0f s"
              % (cfg_id, n, pct("CONVERGED"), pct("STEP_LIMITED"), pct("AT_BOUND"),
                 nonopt, ("AT_BOUND=" + "|".join("%s:%d" % kv for kv in bp.most_common(3))
                          if bp else "-"), el), flush=True)

    if not want:
        for cfg_id, ns in NA_CONFIGS:
            rows.append(dict({k: "" for k in COLS}, config_id=cfg_id, box_px="op",
                             step_limit=base_cfg["step_limit"], n_seeds=ns,
                             poly=base_cfg["poly_deg"],
                             note="해당 없음 — 운영 워커 경로는 격자 시딩을 안 쓴다"
                                  "(직전 스캔 shift 가 앵커). 시드 축은 A1 에만 있다."))

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=COLS)
        wr.writeheader()
        wr.writerows(rows)
    print(f"\n→ {args.out}  ({len(rows)} 행)")


if __name__ == "__main__":
    main()
