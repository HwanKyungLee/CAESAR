# -*- coding: utf-8 -*-
"""gui/pg_perf.py — 큰 시계열(수십만 점)을 화면(pyqtgraph)에서 빠르게 그리는 규칙 한 곳.

2026-10-01 실측(30일 26만 행): 선·마커를 매 페인트마다 26만 점 전부 그리고 있었다.
pyqtgraph 0.14는 `pw.plot(..., autoDownsample=True)`처럼 **생성 인자로 준 솎아내기 옵션을 조용히
무시**한다(`opts['autoDownsample']`가 False로 남음 — 실측). 만든 뒤 `setDownsampling()`을 직접
불러야 켜지고, 켜지면 범위가 바뀔 때마다 스스로 다시 계산한다(30일 전체 보기에서 ds≈46, 페인트 ~12배).

- `peak` = 구간마다 최솟값·최댓값을 남긴다 → 스파이크가 화면에서 사라지지 않는다.
- 확대하면 배율이 1로 돌아와 모든 점이 다시 보인다. Publish(matplotlib)·Export·통계는 원본 그대로.
- `clipToView`는 쓰지 않는다 — pyqtgraph 0.14에서 PlotWidget에 붙이면 AttributeError(autoRangeEnabled).
"""
from __future__ import annotations

BIG = 20000            # 이 점 수를 넘는 시리즈만 솎는다(작은 그림은 예전과 똑같이)


def make_fast(item, n=None, force=False):
    """PlotDataItem에 화면 솎아내기를 켠다(n > BIG 또는 force). item을 그대로 돌려준다."""
    if n is None:
        xd = getattr(item, "xData", None)
        n = 0 if xd is None else len(xd)
    if force or n > BIG:
        item.setDownsampling(auto=True, method="peak")
    return item
