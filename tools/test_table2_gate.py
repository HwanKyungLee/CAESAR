#!/usr/bin/env python
"""`tools/table2.py` 게이트 추정량과 **시각축 정렬** 자체검증 (데이터 불필요).

왜 이게 필요한가
----------------
게이트 셋(예산 · 관측 전체 · 관측 짝)을 한 실행에서 내려면 두 축을 같은 원점으로
옮겨야 한다 — 병합자료는 엑셀 serial(Unix 기준), 예산 `sec` 은 **연초 기준**이다.
틀리면 예외가 아니라 **교집합 0** 으로 조용히 죽는다(실제로 한 번 그랬다).
그래서 원점 변환에 고정점 하나를 박아 둔다.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from table2 import hourly_gate, merged_sec, rsd


def test_epoch_fixed_point():
    """2026-05-20 12:00 KST → day 139.125 (= 03:00 UTC). 부호와 25569 를 잡는다."""
    assert merged_sec(46162.5, 9.0, 2026) == 12020400.0
    assert merged_sec(46162.5, 9.0, 2026) / 86400.0 == 139.125
    # KST 를 안 빼면 9 h 앞선다 — 부호가 뒤집히면 18 h 어긋난다.
    assert merged_sec(46162.5, 0.0, 2026) - merged_sec(46162.5, 9.0, 2026) == 32400.0


def test_gate_known_staircase():
    """시간평균이 d 씩 번갈아 움직이면 게이트는 1.4826·d/√2 다."""
    d = 0.4
    sec, val = [], []
    for h in range(40):
        for k in range(12):
            sec.append(h * 3600 + k * 300)
            val.append(d * (h % 2))
    G = hourly_gate(np.array(sec, float), np.array(val, float), 8)
    assert G["n"] == 40 and G["pairs"] == 39
    assert abs(G["gate"] - 1.4826 * d / np.sqrt(2.0)) < 1e-9


def test_gap_hours_not_differenced():
    """인접하지 않은 시간끼리 차분하면 공백을 잡음으로 센다 — 빼야 한다."""
    sec, val = [], []
    for h in list(range(20)) + list(range(60, 80)):       # 40 시간 공백
        for k in range(12):
            sec.append(h * 3600 + k * 300)
            val.append(0.1 if h < 20 else 9.9)            # 공백 너머는 9.8 점프
    G = hourly_gate(np.array(sec, float), np.array(val, float), 8)
    assert G["n"] == 40
    assert G["pairs"] == 38                               # 39 가 아니다 — 경계쌍 제외
    assert G["gate"] == 0.0                               # 각 덩이 안은 평탄


def test_min_per_hour_drops_thin_hours():
    """레코드가 모자란 시간은 세지 않는다. 그 때문에 짝이 146 → 107 로 준다."""
    sec, val = [], []
    for h in range(10):
        n = 12 if h != 5 else 3
        for k in range(n):
            sec.append(h * 3600 + k * 300)
            val.append(float(h))
    G = hourly_gate(np.array(sec, float), np.array(val, float), 8)
    assert G["n"] == 9 and 5 not in set(G["hours"].tolist())
    assert G["pairs"] == 7                                # 4–5, 5–6 둘 다 끊긴다


def test_gate_nan_when_too_few_pairs():
    """쌍이 모자라면 0 이 아니라 NaN 이다 (모르는 값은 NaN, 절대 0 이 아니다)."""
    sec = np.arange(0, 3 * 3600, 300.0)
    G = hourly_gate(sec, np.ones_like(sec), 8)
    assert G["pairs"] == 2 and np.isnan(G["gate"])


def test_rsd_matches_definition():
    v = np.array([1.0, 2.0, 3.0, 4.0, 100.0])
    assert abs(rsd(v) - 1.4826 * 1.0) < 1e-12            # median 3, MAD 1 — 꼬리에 안 끌린다


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
