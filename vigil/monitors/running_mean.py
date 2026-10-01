"""ZA/He 구간 평균용 누적기 — 스펙트럼을 쌓지 않고 합과 개수만 든다.

예전엔 구간 동안 스펙트럼 전체를 리스트에 쌓았다가 끝날 때 평균냈다. 구간이 정상이면
수 분이라 문제없지만, flag 가 'ZA' 로 고착되거나 프로파일 flag 매핑이 틀리면 채널당
~65 KB/행씩 끝없이 자란다(2026-10-01 현장 PC 다운 사고 조사에서 확인). 평균만 필요하므로
메모리를 행 수와 무관하게 만든다.
"""
from __future__ import annotations

import numpy as np


class RunningMean:
    """add(x) 를 반복한 뒤 mean() — x 는 같은 모양의 배열(또는 스칼라)."""

    def __init__(self):
        self._sum = None
        self.n = 0

    def __bool__(self) -> bool:
        return self.n > 0

    def __len__(self) -> int:
        return self.n

    def add(self, x) -> None:
        a = np.asarray(x, dtype=float)
        if self._sum is None:
            self._sum = a.copy()
        else:
            self._sum += a
        self.n += 1

    def mean(self):
        return self._sum / self.n
