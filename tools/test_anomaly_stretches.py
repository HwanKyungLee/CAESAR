#!/usr/bin/env python
"""`tools/anomaly_stretches.py` 자체검증 (데이터 불필요).

국소 z 와 연속구간 묶기가 §7.3 의 숫자를 통째로 정한다. 둘 다 조용히 틀릴 수
있는 종류다 — 창이 자기 자신을 포함하면 z 가 눌리고, 연속 판정이 빈 번호가
아니라 배열 순서를 보면 공백 너머를 한 구간으로 붙인다.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from anomaly_stretches import local_z, stretches


def test_local_z_finds_spike():
    """평탄한 배경 + 잡음에 스파이크 하나 → 그 빈만 큰 z."""
    rng = np.random.default_rng(0)
    b = np.arange(200)
    v = 2.0 + 0.01 * rng.standard_normal(200)
    v[100] = 3.0
    z, med = local_z(b, v, 12)
    assert abs(z[100]) > 20, z[100]
    other = np.abs(z[np.isfinite(z)])
    assert np.median(other) < 2.0
    assert abs(med[100] - 2.0) < 0.02          # 국소 중앙은 스파이크에 안 끌린다


def test_local_z_excludes_self():
    """자기 자신을 창에 넣으면 스파이크가 제 기준을 들어올려 z 가 눌린다."""
    b = np.arange(60)
    v = np.ones(60)
    v[30] = 5.0
    v += 1e-3 * np.arange(60) % 7 * 1e-3       # 완전 상수면 MAD=0
    z, _ = local_z(b, v, 10)
    assert np.isfinite(z[30]) and abs(z[30]) > 50


def test_local_z_is_nan_not_zero_when_thin():
    """이웃이 모자라면 NaN 이다 — 모르는 값은 절대 0 이 아니다."""
    b = np.arange(4)
    z, _ = local_z(b, np.array([1.0, 2.0, 3.0, 4.0]), 10)
    assert np.all(np.isnan(z))


def test_local_z_flat_window_gives_nan():
    """MAD 가 0 이면 나눌 수 없다 — 0 이 아니라 NaN 이어야 한다."""
    b = np.arange(40)
    v = np.ones(40)
    v[20] = 9.0
    z, _ = local_z(b, v, 10)
    assert np.isnan(z[20])


def test_stretches_respect_bin_gaps():
    """배열 순서가 아니라 **빈 번호**가 1씩 늘어야 한 구간이다."""
    b = np.array([10, 11, 12, 50, 51, 52, 53])
    out = stretches(np.arange(7), b, 3)
    assert [len(g) for g in out] == [3, 4]
    assert [b[g[0]] for g in out] == [10, 50]


def test_stretches_min_len():
    b = np.array([1, 2, 5, 6, 7])
    assert [len(g) for g in stretches(np.arange(5), b, 3)] == [3]
    assert [len(g) for g in stretches(np.arange(5), b, 2)] == [2, 3]


def main():
    fails = 0
    for nm, fn in sorted(globals().items()):
        if not nm.startswith("test_"):
            continue
        try:
            fn()
            print("  PASS %s" % nm)
        except AssertionError as e:
            fails += 1
            print("  FAIL %s  %s" % (nm, e))
    print("%d 실패" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
