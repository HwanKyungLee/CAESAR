"""`window_designer.estimate_shift` 가 "정렬 실패"를 "정렬이 0"과 구분해 알리는지.

설계행렬은 가짜로 바꿔 끼운다: 가우시안 흡수대 하나를 shift 만큼 옮긴 열 + 상수.
데이터 없이 돈다.
"""
import os
import sys
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.window_designer as WD

N = 200


def _fake_dm(eng, species, px_min, px_max, poly_deg, etalon_freq=0.0, shift=0.0, squeeze=1.0):
    px = np.arange(px_min, px_max + 1, dtype=float)
    band = np.exp(-0.5 * ((px - 100.0 - shift) / 4.0) ** 2)
    return np.column_stack([band, np.ones_like(px)]), None


def _run(alphas, **kw):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        sh = WD.estimate_shift(None, alphas, ["X"], 0, N - 1, 0, **kw)
    return sh, [str(x.message) for x in w if issubclass(x.category, RuntimeWarning)]


def main():
    orig = WD.design_matrix
    WD.design_matrix = _fake_dm
    try:
        px = np.arange(N, dtype=float)
        good = np.exp(-0.5 * ((px - 103.0) / 4.0) ** 2)[None, :] * np.ones((3, 1))

        sh, ws = _run(good)
        assert abs(sh - 3.0) < 1e-9 and not ws, (sh, ws)
        print("PASS 정상 정렬: 경고 없음")

        sh, ws = _run(np.full((3, N), np.nan))
        assert sh == 0.0 and any("정렬 실패" in m for m in ws), ws
        print("PASS 전 스캔 NaN: shift 0 + 실패 경고")

        mixed = np.vstack([good, np.full((1, N), np.nan)])
        sh, ws = _run(mixed)
        assert abs(sh - 3.0) < 1e-9 and not ws, (sh, ws)
        print("PASS NaN 스캔 하나 섞임: 나머지로 정렬")

        sh, ws = _run(good, lo=-2.0, hi=2.0)
        assert sh == 2.0 and any("경계" in m for m in ws), (sh, ws)
        print("PASS 경계에 붙음: 경고")
    finally:
        WD.design_matrix = orig
    print("\nOK")


if __name__ == "__main__":
    main()
