# -*- coding: utf-8 -*-
"""tools/test_parse_row_time.py — core.result_io.parse_row_time 빠른 길이 예전 strptime과 같은가.

2026-10-01: 26만 행 파일에서 행마다 strptime을 두 번 시도하는 데 ~10 s가 들어
`fromisoformat` 빠른 길을 넣었다. 빠른 길은 두 형식과 **모양이 정확히 같은** 문자열만 탄다.
여기서는 정상·경계·이상 문자열 전부를 예전 구현과 대조한다(결과가 하나라도 다르면 실패).

    python tools/test_parse_row_time.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.result_io import parse_row_time


def reference(ts):
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(ts[:26], fmt)
        except ValueError:
            continue
    return None


CASES = [
    "2026-05-01 00:00:00", "2026-05-01 23:59:59", "2026-12-31 12:34:56.5",
    "2026-12-31 12:34:56.123", "2026-12-31 12:34:56.123456", "2026-12-31 12:34:56.1234567",
    "2026-02-29 00:00:00", "2026-13-01 00:00:00", "2026-05-01 24:00:00", "2026-05-01 00:60:00",
    "2026-5-1 1:2:3", "2026-05-01T00:00:00", "2026-05-01 00:00:00 extra", "2026-05-01 00:00:00.",
    "2026-05-01 00:00:00.abc", "2026-05-01", "", "   ", "garbage", "2026-05-01 00:00",
    "2026-05-01 00:00:00+09:00", "2026-05-01 00:00:00Z", "0001-01-01 00:00:00", "9999-12-31 23:59:59",
    "2026-05-01 00:00:00.000000123", "2026-05-01 7:00:00", "20260501 000000", "2026/05/01 00:00:00",
    "２０２６-05-01 00:00:00",
]


def main():
    bad = []
    for s in CASES:
        a, b = parse_row_time(s), reference(s)
        if a != b:
            bad.append((s, a, b))
    # 무작위 정상 시각 대량 대조
    import random
    rnd = random.Random(0)
    for _ in range(20000):
        d = datetime(2000 + rnd.randrange(60), 1 + rnd.randrange(12), 1 + rnd.randrange(28),
                     rnd.randrange(24), rnd.randrange(60), rnd.randrange(60), rnd.randrange(1_000_000))
        for s in (f"{d:%Y-%m-%d %H:%M:%S}", f"{d:%Y-%m-%d %H:%M:%S.%f}",
                  f"{d:%Y-%m-%d %H:%M:%S.%f}"[:23]):
            if parse_row_time(s) != reference(s):
                bad.append((s, parse_row_time(s), reference(s)))
    assert not bad, f"{len(bad)} mismatch(es), e.g. {bad[:5]}"
    print(f"test_parse_row_time: {len(CASES)} edge cases + 60000 random — identical to strptime")
    return 0


if __name__ == "__main__":
    sys.exit(main())
