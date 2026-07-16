"""계단 가드 문턱 산정 근거 — 캠페인 R(t) knot 시계열의 변화율 분포 조사.

작업지시(개선작업지시_2026-07 §A-5): 매직넘버 금지 — 문턱은 실데이터 분포에서
정한다. 이 스크립트는 R_<ch>.npz 들에 대해
  1) 인접 knot 상대 변화 pair_rel = |Δm|/m̄ 분포 (m = R-fit 창 내 omr_d 평균)
  2) 지속 변화 persist_rel (앞뒤 5-knot 중앙값 레벨 차)
  3) 계단 점수 score = min(pair, persist) 분포와 적응 문턱, 감지 이벤트
를 보고한다. 결과·판단 근거는 docs/step_guard_threshold_2026-07.md 에 기록.

사용: python tools/step_threshold_survey.py [npz ...]
      (인자 없으면 C:\\Doasis_Work\\Output\\R\\R_*.npz 전부)
"""
import glob
import os
import re
import sys
from datetime import datetime, timedelta

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from rt_precompute import load_rt
from core.step_guard import (knot_scalar_metric, relative_changes,
                             persistent_changes, detect_step_candidates,
                             step_threshold)


def _npz_year(z, default=2026):
    for bn in z.get("processed_files", []):
        m = re.search(r"(\d{4})-\d{2}-\d{2}", str(bn))
        if m:
            return int(m.group(1))
    return default


def survey(npz_path):
    z = load_rt(npz_path)
    ks = np.asarray(z["knot_sec"], dtype=float)
    od = np.asarray(z["omr_d"], dtype=float)
    wv = np.asarray(z["wave_nm"], dtype=float)
    cfg = z.get("config") or {}
    win = cfg.get("fit_window_nm")
    m = knot_scalar_metric(od, wave_nm=wv, fit_window_nm=win)
    pair = relative_changes(m)
    pers = persistent_changes(m)
    score = np.minimum(pair, pers) if pair.size else pair
    dt_h = np.diff(ks) / 3600.0

    print(f"\n=== {os.path.basename(npz_path)} ===")
    print(f"  knots={len(ks)}  window={win}  "
          f"span={(ks[-1] - ks[0]) / 86400.0:.1f} d  median Δt={np.median(dt_h):.2f} h")
    if pair.size == 0:
        print("  (knot < 2 — no pairs)")
        return None
    q = lambda a, p: float(np.percentile(a, p))
    print(f"  pair_rel   : p50={q(pair,50):.4f}  p90={q(pair,90):.4f}  "
          f"p95={q(pair,95):.4f}  p99={q(pair,99):.4f}  p99.5={q(pair,99.5):.4f}  max={pair.max():.4f}")
    print(f"  persist_rel: p50={q(pers,50):.4f}  p90={q(pers,90):.4f}  "
          f"p99={q(pers,99):.4f}  p99.5={q(pers,99.5):.4f}  max={pers.max():.4f}")
    print(f"  score      : p99={q(score,99):.4f}  p99.5={q(score,99.5):.4f}  max={score.max():.4f}")

    thr = step_threshold(m)
    cands, _ = detect_step_candidates(ks, m)
    base = datetime(_npz_year(z), 1, 1)
    fmt = lambda s: (base + timedelta(seconds=float(s))).strftime("%m-%d %H:%M")
    print(f"  adaptive threshold = max(0.15, 2×p95) = {thr:.3f} → {len(cands)} event(s)")
    for c in cands:
        print(f"    • {fmt(c['x_left'])} → {fmt(c['x_right'])}  "
              f"jump {c['pair_rel']:.3f}, persists {c['persist_rel']:.3f}")
    return pair, pers, score


def main(paths):
    if not paths:
        paths = sorted(glob.glob(r"C:\Doasis_Work\Output\R\R_*.npz"))
    if not paths:
        print("no npz found")
        return 1
    pooled = []
    for p in paths:
        r = survey(p)
        if r is not None:
            pooled.append(r)
    if pooled:
        for name, k in (("pair_rel", 0), ("persist_rel", 1), ("score", 2)):
            allv = np.concatenate([t[k] for t in pooled])
            print(f"\n=== pooled {name} ({allv.size} pairs) ===")
            print(f"  p50={np.percentile(allv,50):.4f}  p90={np.percentile(allv,90):.4f}  "
                  f"p95={np.percentile(allv,95):.4f}  p99={np.percentile(allv,99):.4f}  "
                  f"p99.5={np.percentile(allv,99.5):.4f}  max={allv.max():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
