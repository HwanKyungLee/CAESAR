#!/usr/bin/env python
"""`tools/extract_cal_knots.py` 블록 분할 자체검증 — 데이터 불필요.

분할 규칙이 production(`gui/worker.py` `_block_average`)과 같아야 한다:
**전역 스캔 인덱스 간격 > 10 이면 새 블록.** 시각 간격이 아니라 인덱스다 —
시각으로 끊으면 계기가 멈췄다 재개한 구간에서 한 블록이 둘로 갈린다.
"""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.extract_cal_knots import GAP, blocks

_p = _f = 0


def check(name, cond):
    global _p, _f
    if cond:
        _p += 1
        print("  PASS  " + name)
    else:
        _f += 1
        print("  FAIL  " + name)


def main():
    check("빈 입력은 빈 결과", blocks([], []) == ([], [], []))

    # 한 블록: 인덱스 연속 34개, 1초 간격
    idx = list(range(34))
    sec = [1000.0 + i for i in idx]
    s, n, sp = blocks(idx, sec)
    check("연속 34스캔 → 블록 1개", len(s) == 1)
    check("  스캔수 34", n == [34.0])
    check("  span 33 s", abs(sp[0] - 33.0) < 1e-9)
    check("  평균시각", abs(s[0] - np.mean(sec)) < 1e-9)

    # 두 블록: 인덱스가 GAP 보다 크게 벌어짐
    idx2 = list(range(34)) + list(range(3600, 3634))
    sec2 = [1000.0 + i for i in range(34)] + [4600.0 + i for i in range(34)]
    s2, n2, _ = blocks(idx2, sec2)
    check("인덱스가 벌어지면 블록 2개", len(s2) == 2 and n2 == [34.0, 34.0])

    # 경계: 간격이 정확히 GAP 이면 **같은 블록**(> 이지 >= 가 아니다)
    s3, n3, _ = blocks([0, GAP], [0.0, 10.0])
    check("간격 == GAP 이면 같은 블록", len(s3) == 1 and n3 == [2.0])
    s4, n4, _ = blocks([0, GAP + 1], [0.0, 11.0])
    check("간격 == GAP+1 이면 두 블록", len(s4) == 2)

    # 시각이 크게 벌어져도 인덱스가 붙어 있으면 한 블록
    s5, n5, _ = blocks([0, 1, 2], [0.0, 1.0, 9999.0])
    check("시각이 벌어져도 인덱스가 붙으면 한 블록(계기 정지 구간)",
          len(s5) == 1 and n5 == [3.0])

    # 입력 순서가 뒤섞여도 결과가 같다
    s6, n6, _ = blocks(idx2[::-1], sec2[::-1])
    check("입력 순서에 무관", len(s6) == 2 and n6 == [34.0, 34.0]
          and all(abs(a - b) < 1e-9 for a, b in zip(s6, s2)))

    # 단일 스캔 블록은 span 0
    s7, n7, sp7 = blocks([0], [5.0])
    check("단일 스캔 블록 span 0", sp7 == [0.0] and n7 == [1.0])

    print(f"\nextract_cal_knots tests: {_p} PASS · {_f} FAIL")
    return 1 if _f else 0


if __name__ == "__main__":
    raise SystemExit(main())
