# -*- coding: utf-8 -*-
"""gui/pg_perf.py — 큰 시계열(수십만 점)을 화면(pyqtgraph)에서 빠르게 그리는 규칙 한 곳.

2026-10-01 실측(30일 26만 행): 선·마커를 매 페인트마다 26만 점 전부 그리고 있었다.
pyqtgraph 0.14의 `PlotItem.addItem`은 붙이는 아이템에 **자기(그래프 메뉴)의 솎아내기 설정 — 기본
꺼짐 — 을 덮어쓴다**(`item.setDownsampling(*self.downsampleMode())`, PlotItem.py 643행). 그래서
`pw.plot(..., autoDownsample=True)`도, 붙이기 전에 켠 것도 꺼진다. **붙인 다음에** `setDownsampling()`을
불러야 켜지고, 켜지면 범위가 바뀔 때마다 스스로 다시 계산한다(30일 전체 보기에서 ds≈46, 페인트 ~12배).
그래프 전체(PlotItem.setDownsampling)로 켜지 않는 이유: x가 정렬되지 않은 산점도(Plot Maker Scatter)
까지 보폭 솎아내기가 걸려 점이 임의로 빠진다.

- `peak` = 구간마다 최솟값·최댓값을 남긴다 → 스파이크가 화면에서 사라지지 않는다.
- 확대하면 배율이 1로 돌아와 모든 점이 다시 보인다. Publish(matplotlib)·Export·통계는 원본 그대로.
- `clipToView`는 쓰지 않는다 — pyqtgraph 0.14에서 PlotWidget에 붙이면 AttributeError(autoRangeEnabled).
"""
from __future__ import annotations

BIG = 20000            # 이 점 수를 넘는 시리즈만 솎는다(작은 그림은 예전과 똑같이)


def add_fast_curve(target, x, y, **style):
    """곡선을 붙인다. 큰 시리즈(>BIG)는 **빈 아이템 → 뷰에 붙이기 → 솎아내기 켜기 → 데이터** 순서.
    데이터와 함께 만들면 붙기도 전에 전체 점으로 마커를 한 번 만들고, 붙이기 전에 켜면 addItem이
    꺼 버린다(모듈 설명). target: PlotWidget/PlotItem/ViewBox. 작은 시리즈는 예전처럼 한 번에."""
    import pyqtgraph as pg
    n = 0 if x is None else len(x)
    if n > BIG:
        item = pg.PlotDataItem(**style)
        target.addItem(item)
        make_fast(item, force=True)
        item.setData(x, y)
    else:
        item = pg.PlotDataItem(x, y, **style)
        target.addItem(item)
    return item


def thin_indices(x, y, xr, yr, w_px, h_px, cell_px=2.0, keep="first"):
    """산점도 화면용 솎아내기 — 보이는 범위를 cell_px 픽셀 칸으로 나눠 **칸마다 점 하나**의 인덱스.
    점이 하나라도 있는 칸은 반드시 남으므로 동떨어진 이상점이 사라지지 않는다(시간 순서가 없는
    산점도에는 선용 peak 솎아내기를 쓸 수 없다). 보이는 범위 밖 점은 뺀다(줌하면 다시 계산).
    keep="last"면 칸마다 **마지막** 점 — 전부 그렸을 때 위에 남는(나중에 그린) 점이라, 점마다 색이
    다른 그림(flag 색)에서 색 비율이 전부 그린 그림과 같게 보인다."""
    import numpy as np
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    (x0, x1), (y0, y1) = xr, yr
    if not (x1 > x0 and y1 > y0 and w_px > 0 and h_px > 0):
        return np.flatnonzero(np.isfinite(x) & np.isfinite(y))
    m = np.isfinite(x) & np.isfinite(y) & (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
    idx = np.flatnonzero(m)
    nx = max(1, int(w_px / cell_px))
    ny = max(1, int(h_px / cell_px))
    ix = np.minimum(((x[idx] - x0) / (x1 - x0) * nx).astype(np.int64), nx - 1)
    iy = np.minimum(((y[idx] - y0) / (y1 - y0) * ny).astype(np.int64), ny - 1)
    key = ix * ny + iy
    if keep == "last":
        _, rev = np.unique(key[::-1], return_index=True)
        return idx[np.sort(len(key) - 1 - rev)]
    _, first = np.unique(key, return_index=True)
    return idx[np.sort(first)]


def nearest_index(x, y, order, px, py, sx, sy, radius_px=8.0):
    """클릭 판정 — 데이터 좌표 (px, py)에서 화면상 radius_px 안의 **실제 데이터 점** 중 가장 가까운
    인덱스(없으면 None). order = x의 argsort(미리 계산해 재사용). sx·sy = 1픽셀당 데이터 단위.
    솎아서 안 그려진 점도 집힌다(판정은 원본 전부로)."""
    import numpy as np
    if sx <= 0 or sy <= 0 or len(order) == 0:
        return None
    xs = x[order]
    lo = np.searchsorted(xs, px - radius_px * sx, side="left")
    hi = np.searchsorted(xs, px + radius_px * sx, side="right")
    cand = order[lo:hi]
    if cand.size == 0:
        return None
    cy = y[cand]
    ok = np.isfinite(cy)
    cand, cy = cand[ok], cy[ok]
    if cand.size == 0:
        return None
    d2 = ((x[cand] - px) / sx) ** 2 + ((cy - py) / sy) ** 2
    k = int(np.argmin(d2))
    return int(cand[k]) if d2[k] <= radius_px ** 2 else None


def make_fast(item, n=None, force=False):
    """PlotDataItem에 화면 솎아내기를 켠다(n > BIG 또는 force). item을 그대로 돌려준다."""
    if n is None:
        xd = getattr(item, "xData", None)
        n = 0 if xd is None else len(xd)
    if force or n > BIG:
        item.setDownsampling(auto=True, method="peak")
    return item
