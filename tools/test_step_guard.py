"""계단 가드 단위테스트 (개선작업지시_2026-07 §A 검증 1항).

합성 knot 시계열로:
  1) 완만 drift만 → 후보 0 + SegmentedPchip 출력이 기존 PCHIP과 **완전 동일**(무회귀)
  2) drift + 계단 삽입 → 후보 감지 + 분절(계단 knot 간격 밖 출력은 기존과 동일)
  3) 복귀형 노이즈 스파이크 → 지속 조건에서 탈락(후보 0)
  4) 노이즈 큰 채널(콜드형) → 적응 문턱이 자동분절 억제
  5) 수동 분절 → 감지 없이도 강제 분절
  6) 벡터 knot(N,npix) 지원
  7) rt_precompute save/load/merge가 manual_breaks_sec 보존
  8) parse_break_datetimes 왕복

사용: python tools/test_step_guard.py  → 전부 PASS면 exit 0
"""
import os
import sys
import tempfile

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from scipy.interpolate import PchipInterpolator

from core.step_guard import (SegmentedPchip, detect_step_candidates,
                             knot_scalar_metric, step_threshold, REL_FLOOR)

_n_pass = 0
_n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def _dense(x):
    return np.linspace(x[0], x[-1], 4001)


def test_smooth_drift_no_regression():
    print("[1] smooth drift → no candidates, byte-identical to plain PCHIP")
    rng = np.random.default_rng(42)
    x = np.arange(100, dtype=float) * 3600.0
    m = 1e-6 * (1.0 + 0.001 * np.arange(100) + 0.01 * rng.standard_normal(100))
    cands, thr = detect_step_candidates(x, m)
    check("no candidates on smooth drift", len(cands) == 0,
          f"got {len(cands)} (thr={thr:.3f})")
    seg = SegmentedPchip(x, m)
    ref = PchipInterpolator(x, m, extrapolate=False)
    xs = _dense(x)
    a = np.array([seg(v) for v in xs])
    b = np.asarray(ref(xs), dtype=float)
    check("output identical to plain PCHIP (interior)", np.array_equal(a, b),
          f"max diff {np.nanmax(np.abs(a - b)):.3e}")
    check("outside range → nearest-constant",
          seg(x[0] - 999.0) == m[0] and seg(x[-1] + 999.0) == m[-1])
    check("single segment", seg.n_segments == 1)


def test_step_detected_and_segmented():
    print("[2] drift + inserted step → detected, segmented, local-only effect")
    x = np.arange(100, dtype=float) * 3600.0
    m = np.full(100, 1e-6)
    m[50:] *= 1.5          # +50% 지속 계단 (거울 급오염 급)
    cands, thr = detect_step_candidates(x, m)
    check("exactly 1 candidate", len(cands) == 1, f"got {len(cands)}")
    if not cands:
        return
    c = cands[0]
    check("candidate at the right pair", c["i"] == 49, f"i={c['i']}")
    seg = SegmentedPchip(x, m, break_x=[c["x_break"]])
    check("2 segments", seg.n_segments == 2)
    # 계단 구간(49~50번 knot 사이): 좌측은 좌측 레벨, 우측은 우측 레벨 상수 —
    # PCHIP 램프처럼 중간값이 생기지 않아야 한다.
    tl = x[49] + 600.0            # 경계 왼쪽
    tr = x[50] - 600.0            # 경계 오른쪽
    check("left of break holds left level", np.isclose(seg(tl), m[49]),
          f"{seg(tl):.3e} vs {m[49]:.3e}")
    check("right of break holds right level", np.isclose(seg(tr), m[50]),
          f"{seg(tr):.3e} vs {m[50]:.3e}")
    # 계단 knot 간격 밖에서는 기존 PCHIP과 동일해야 한다(국소성).
    ref = PchipInterpolator(x, m, extrapolate=False)
    far = np.concatenate([np.linspace(x[0], x[45], 500),
                          np.linspace(x[55], x[-1], 500)])
    a = np.array([seg(v) for v in far])
    b = np.asarray(ref(far), dtype=float)
    check("far from step: identical to plain PCHIP",
          np.allclose(a, b, rtol=0, atol=0),
          f"max diff {np.nanmax(np.abs(a - b)):.3e}")


def test_spike_not_detected():
    print("[3] return-to-level spike (bad injection) → NOT a step")
    x = np.arange(100, dtype=float) * 3600.0
    m = np.full(100, 1e-6)
    m[50] *= 1.8           # 한 knot만 튀고 복귀
    cands, thr = detect_step_candidates(x, m)
    check("spike rejected by persistence", len(cands) == 0,
          f"got {len(cands)} (thr={thr:.3f})")


def test_noisy_channel_suppressed():
    print("[4] cold-like noisy channel → adaptive threshold suppresses auto-seg")
    rng = np.random.default_rng(7)
    x = np.arange(300, dtype=float) * 3600.0
    m = 1e-6 * (1.0 + 0.4 * rng.standard_normal(300))   # p95 pair_rel >> floor
    m = np.abs(m) + 1e-8
    thr = step_threshold(m)
    check("threshold rises above floor", thr > REL_FLOOR, f"thr={thr:.3f}")
    cands, _ = detect_step_candidates(x, m)
    check("few/no auto candidates on pure noise", len(cands) <= 1,
          f"got {len(cands)}")


def test_manual_break():
    print("[5] manual break forces segmentation without detection")
    x = np.arange(10, dtype=float) * 3600.0
    m = np.linspace(1.0, 1.09, 10) * 1e-6   # 완만 — 감지 없음
    bt = 0.5 * (x[4] + x[5])
    seg = SegmentedPchip(x, m, break_x=[bt])
    check("2 segments from manual break", seg.n_segments == 2)
    check("left side constant near break", np.isclose(seg(bt - 60.0), m[4]))
    check("right side constant near break", np.isclose(seg(bt + 60.0), m[5]))


def test_vector_knots():
    print("[6] vector knots (N,npix)")
    x = np.arange(20, dtype=float) * 3600.0
    y = np.tile(np.linspace(1.0, 1.05, 20)[:, None], (1, 8)) * 1e-6
    y[10:, :] *= 1.4
    metr = knot_scalar_metric(y)
    cands, _ = detect_step_candidates(x, metr)
    check("step detected on vector metric", len(cands) == 1, f"got {len(cands)}")
    seg = SegmentedPchip(x, y, break_x=[c["x_break"] for c in cands])
    v = seg(x[3] + 1800.0)
    check("vector query returns npix array", getattr(v, "shape", None) == (8,))
    ref = PchipInterpolator(x, y, extrapolate=False)
    far = x[2] + 900.0
    check("vector far-from-step identical",
          np.allclose(seg(far), np.asarray(ref(far), dtype=float)))


def test_npz_manual_breaks_roundtrip():
    print("[7] rt_precompute: manual_breaks_sec survive save/load/merge")
    import rt_precompute as RTP
    x = np.arange(5, dtype=float) * 3600.0
    od = np.full((5, 16), 1e-6)
    wv = np.linspace(430.0, 470.0, 16)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "R_test.npz")
        RTP.save_rt(p, x, od, wv, label="t", config=None,
                    processed_files=["f_2026-05-01.dat"],
                    manual_breaks_sec=[7200.0, 9000.0])
        z = RTP.load_rt(p)
        check("breaks saved+loaded",
              list(z["manual_breaks_sec"]) == [7200.0, 9000.0],
              str(z.get("manual_breaks_sec")))
        # 증분 머지 후에도 보존되는가
        cfg = RTP.RTConfig((430.0, 470.0), 1, 2, 10, 26, 9, "t")
        RTP._merge_knots_into_npz(
            p, x + 5 * 3600.0, od.copy(), wv, cfg, ["f_2026-05-02.dat"])
        z2 = RTP.load_rt(p)
        check("breaks survive merge",
              list(z2["manual_breaks_sec"]) == [7200.0, 9000.0],
              str(z2.get("manual_breaks_sec")))
        check("merge added knots", len(z2["knot_sec"]) == 10)
        # set_manual_breaks 교체 + step_report가 manual을 보고하는가
        RTP.set_manual_breaks(p, [3600.0])
        z3 = RTP.load_rt(p)
        check("set_manual_breaks replaces", list(z3["manual_breaks_sec"]) == [3600.0])
        rep = RTP.step_report(p)
        check("step_report lists manual break",
              any("manual" in ln for ln in rep["lines"]), str(rep["lines"]))
        # 구버전 npz(manual_breaks_sec 없음) 호환
        np.savez_compressed(os.path.join(td, "old.npz"),
                            label="o", config="{}", processed_files_json="[]",
                            knot_sec=x, omr_d=od, wave_nm=wv)
        zo = RTP.load_rt(os.path.join(td, "old.npz"))
        check("legacy npz → empty breaks", len(zo["manual_breaks_sec"]) == 0)


def test_parse_datetimes():
    print("[8] parse_break_datetimes")
    import rt_precompute as RTP
    secs = RTP.parse_break_datetimes(
        ["2026-06-14 09:00", "2026-01-01 00:00:00", ""], 2026)
    check("parses to year-start seconds",
          np.isclose(secs[1], 0.0) and np.isclose(
              secs[0], (31 + 28 + 31 + 30 + 31 + 13) * 86400 + 9 * 3600),
          str(secs))
    try:
        RTP.parse_break_datetimes(["not-a-date"], 2026)
        check("invalid input raises", False)
    except ValueError:
        check("invalid input raises", True)


if __name__ == "__main__":
    for t in (test_smooth_drift_no_regression, test_step_detected_and_segmented,
              test_spike_not_detected, test_noisy_channel_suppressed,
              test_manual_break, test_vector_knots,
              test_npz_manual_breaks_roundtrip, test_parse_datetimes):
        t()
    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    sys.exit(1 if _n_fail else 0)
