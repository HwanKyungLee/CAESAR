"""계단 가드 실데이터 영향 리포트 (개선작업지시_2026-07 §A 검증 2항).

캠페인 R_<ch>.npz에 대해 기존(plain PCHIP) vs 가드(SegmentedPchip, 자동감지
+수동분절) R(t) 보간을 1분 간격 전체 시간축에서 비교해 **바뀌는 %를 숫자로**
보고한다(헌장 ②). α는 (omr_d + RL·α_ray)에 선형이므로 omr_d 상대차는 해당
시각 α 스케일 변화의 상한이다.

사용: python tools/step_guard_impact.py [npz ...]
      (인자 없으면 C:\\Doasis_Work\\Output\\R\\R_*.npz 전부)
"""
import glob
import os
import sys
from datetime import datetime, timedelta

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from scipy.interpolate import PchipInterpolator

from rt_precompute import load_rt, npz_year
from core.step_guard import (SegmentedPchip, detect_step_candidates,
                             knot_scalar_metric)


def report(npz_path):
    z = load_rt(npz_path)
    ks = np.asarray(z["knot_sec"], dtype=float)
    od = np.asarray(z["omr_d"], dtype=float)
    wv = np.asarray(z["wave_nm"], dtype=float)
    print(f"\n=== {os.path.basename(npz_path)} ===")
    if ks.size < 2:
        print("  <2 knots — nothing to compare")
        return
    m = knot_scalar_metric(od, wave_nm=wv,
                           fit_window_nm=(z.get("config") or {}).get("fit_window_nm"))
    cands, thr = detect_step_candidates(ks, m)
    manual = list(np.asarray(z.get("manual_breaks_sec", []), dtype=float))
    breaks = sorted([c["x_break"] for c in cands] + manual)
    print(f"  knots={len(ks)}  auto candidates={len(cands)} (thr={thr:.3f})  "
          f"manual breaks={len(manual)}")

    plain = PchipInterpolator(ks, od, extrapolate=False)
    seg = SegmentedPchip(ks, od, break_x=breaks)
    if seg.n_segments == 1:
        print("  → no segmentation: guarded output is IDENTICAL to current "
              "pipeline (0.000% change everywhere)")
        return

    t = np.arange(ks[0], ks[-1], 60.0)          # 1-min grid, interior only
    a = np.asarray(plain(t), dtype=float)        # (T, npix)
    b = np.stack([np.asarray(seg(v), dtype=float) for v in t])
    with np.errstate(invalid="ignore", divide="ignore"):
        rel = np.abs(b - a) / np.where(np.abs(a) > 0, np.abs(a), np.nan)
    rel_t = np.nanmean(rel, axis=1)              # 시각별 평균 상대차
    changed = rel_t > 1e-12
    frac = changed.mean() * 100.0
    print(f"  guarded vs current omr_d on 1-min grid ({len(t)} pts):")
    print(f"    changed time fraction: {frac:.3f}%  "
          f"({changed.sum()} min of {len(t)} min)")
    if changed.any():
        print(f"    where changed: mean {np.nanmean(rel_t[changed]) * 100:.2f}%, "
              f"max {np.nanmax(rel_t) * 100:.2f}% (omr_d relative)")
        yr = npz_year(z)
        if yr:
            base = datetime(yr, 1, 1)
            idx = np.flatnonzero(changed)
            t0 = base + timedelta(seconds=float(t[idx[0]]))
            t1 = base + timedelta(seconds=float(t[idx[-1]]))
            print(f"    affected window(s) within: {t0:%Y-%m-%d %H:%M} ~ "
                  f"{t1:%Y-%m-%d %H:%M}")
    print("    (α scale change upper bound = omr_d relative change; "
          "everywhere else 0.000%)")


def main(paths):
    if not paths:
        paths = sorted(glob.glob(r"C:\Doasis_Work\Output\R\R_*.npz"))
    if not paths:
        print("no npz found")
        return 1
    for p in paths:
        report(p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
