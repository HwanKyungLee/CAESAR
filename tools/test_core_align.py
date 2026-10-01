# -*- coding: utf-8 -*-
"""tools/test_core_align.py — core/align.py(결손 가드 정렬) 자체검증. Qt·데이터 불필요.

지키는 것:
  1. linear: 감싸는 두 점 간격이 max_gap 이하일 때만 보간, 넘으면 NaN(결손을 잇지 않음)
  2. nearest: 가장 가까운 점이 max_gap/2 안일 때만
  3. 정확히 같은 시각은 언제나 그 값 · 범위 밖은 NaN · NaN 원본 점은 없는 점으로
  4. auto_max_gap = 간격 중앙값 × core.day_audit.GAP_FACTOR_FAIL (단일 출처)
  5. n_gap = 가드가 버린 점 수

    python tools/test_core_align.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np

from core.align import align_to, auto_max_gap
from core.day_audit import GAP_FACTOR_FAIL


def main():
    ts = np.array([0.0, 60, 120, 180, 600, 660])      # 180→600 = 결손
    vs = np.array([0.0, 1, 2, 3, 10, 11])
    tr = np.array([-10, 30, 120, 150, 300, 630, 700])

    assert auto_max_gap(ts) == 60 * GAP_FACTOR_FAIL
    v, info = align_to(tr, ts, vs)
    exp = [np.nan, 0.5, 2.0, 2.5, np.nan, 10.5, np.nan]
    assert np.allclose(v, exp, equal_nan=True), v
    assert info["n_gap"] == 1 and info["n_ok"] == 4, info      # 300 하나만 가드에 걸림

    v, info = align_to(tr, ts, vs, method="nearest", max_gap=120)
    exp = [0.0, 0.0, 2.0, 2.0, np.nan, 10.0, 11.0]               # -10·700: 60 s 안이라 채움
    assert np.allclose(v, exp, equal_nan=True), v
    assert info["n_gap"] == 1

    # 결손이어도 정확히 같은 시각은 그 값
    v, _ = align_to(np.array([180.0, 600.0]), ts, vs, max_gap=1)
    assert np.allclose(v, [3, 10])

    # NaN 원본 점은 없는 점 → 그 양옆 간격으로 판단
    vs2 = vs.copy(); vs2[1] = np.nan
    v, _ = align_to(np.array([60.0, 90.0]), ts, vs2, max_gap=100)
    assert np.isnan(v).all(), v                                   # 0→120 간격 120 > 100
    v, _ = align_to(np.array([60.0]), ts, vs2, max_gap=150)
    assert np.allclose(v, [1.0])                                  # 0↔2 사이 보간

    # 원본이 비어도 죽지 않는다
    v, info = align_to(tr, np.array([]), np.array([]))
    assert np.isnan(v).all() and info["n_ok"] == 0
    print("test_core_align: all OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
