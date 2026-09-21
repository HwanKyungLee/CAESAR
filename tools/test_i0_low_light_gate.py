#!/usr/bin/env python
"""§6.3 저광량 I0 knot 게이트 자체검증 — 데이터 불필요.

가장 중요한 케이스는 **frac=0 이면 한 블록도 안 버린다**(운영 산출물 무변경)다.
나머지는 문턱이 절대값이 아니라 그 런의 블록 중앙값 대비 비율이라는 것,
그리고 판정을 핏창 안에서만 한다는 것.
"""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gui.worker import low_light_knots

_n_pass = _n_fail = 0


def check(name, cond):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print("  PASS  " + name)
    else:
        _n_fail += 1
        print("  FAIL  " + name)


def main():
    bright = [np.full(100, 10000.0) for _ in range(5)]
    dark = np.full(100, 1000.0)

    check("frac=0 이면 아무것도 안 버린다 (운영 기본값)",
          low_light_knots(bright + [dark], 0.0) == set())
    check("frac=None 도 동일", low_light_knots(bright + [dark], None) == set())
    check("frac<0 도 동일", low_light_knots(bright + [dark], -1.0) == set())

    check("중앙값의 0.5배 미만인 블록만 버린다",
          low_light_knots(bright + [dark], 0.5) == {5})
    check("문턱보다 밝으면 안 버린다 (0.05배 문턱)",
          low_light_knots(bright + [dark], 0.05) == set())

    # 절대값이 아니라 비율 — 전체가 10배 어두워도 같은 판정
    dim = [np.full(100, 1000.0) for _ in range(5)] + [np.full(100, 100.0)]
    check("전체 광량이 10배 달라도 같은 집합",
          low_light_knots(dim, 0.5) == {5})

    # 핏창 밖은 판정에 쓰지 않는다
    s = np.full(100, 10000.0)
    s[:20] = 1.0          # 창 밖만 어둡다
    check("창 밖이 어두운 블록은 창 안으로 판정해 안 버린다",
          low_light_knots(bright + [s], 0.5, pixel_min=20, pixel_max=100) == set())
    s2 = np.full(100, 10000.0)
    s2[20:] = 1.0         # 창 안이 어둡다
    check("창 안이 어두우면 버린다",
          low_light_knots(bright + [s2], 0.5, pixel_min=20, pixel_max=100) == {5})

    check("NaN 블록은 버린다(판정 불가 → flag 쪽)",
          low_light_knots(bright + [np.full(100, np.nan)], 0.5) == {5})
    check("기준(중앙값)을 못 세우면 아무것도 안 버린다",
          low_light_knots([np.full(10, np.nan)] * 3, 0.5) == set())
    check("전부 0 이면 기준이 0 이라 아무것도 안 버린다",
          low_light_knots([np.zeros(10)] * 3, 0.5) == set())
    check("빈 입력은 빈 집합", low_light_knots([], 0.5) == set())

    print(f"\ni0 low-light gate tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
