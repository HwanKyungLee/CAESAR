# -*- coding: utf-8 -*-
"""Plot Maker — 공통 가공 헬퍼(모드 횡단): 시간 리샘플·rolling 평활·회귀·Allan 편차."""
from __future__ import annotations

import numpy as np


def resample_mean(t, y, sec):
    """시간 t(epoch초)를 sec 간격 버킷으로 묶어 평균. t 없으면 그대로."""
    if not sec or t is None:
        return t, y
    m = np.isfinite(t) & np.isfinite(y)
    if m.sum() == 0:
        return t, y
    tt, yy = t[m], y[m]
    o = np.argsort(tt)
    tt, yy = tt[o], yy[o]
    bins = np.floor(tt / sec).astype(np.int64)
    ub, inv = np.unique(bins, return_inverse=True)
    cnt = np.bincount(inv)
    xs = np.bincount(inv, weights=tt) / cnt
    ys = np.bincount(inv, weights=yy) / cnt
    return xs, ys


def smooth(y, n):
    """rolling 평균(center, NaN 무시). n<=1이면 그대로."""
    if n <= 1:
        return y
    import pandas as pd
    return pd.Series(y).rolling(n, min_periods=1, center=True).mean().to_numpy()


def step_xy(x, y):
    """계단(steps-post) 좌표로 확장 — 구간마다 수평선+수직선 두 점으로 편다.

    pg와 mpl의 계단 옵션 의미가 서로 미묘하게 다르다(pyqtgraph는
    stepMode='center'/'left'/'right', matplotlib은 drawstyle='steps-pre/post/mid').
    그래서 **양쪽 다 '그냥 선'으로 그리게** 좌표를 여기서 편다 — 두 렌더러가
    반드시 같은 그림을 낸다(화면·Publish 드리프트 방지 규약).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 2 or len(y) < 2:
        return x, y
    return np.repeat(x, 2)[1:], np.repeat(y, 2)[:-1]


def bar_width(x, frac=0.8):
    """막대 폭(x 단위) = 인접 간격 중앙값 × frac. 못 정하면 None."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return None
    d = float(np.median(np.diff(np.sort(x))))
    return d * frac if d > 0 else None


def regress(x, y):
    """최소제곱 직선 적합 → (slope, intercept, r2, n) 또는 None."""
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 2:
        return None
    x, y = x[m], y[m]
    slope, inter = np.polyfit(x, y, 1)
    yhat = slope * x + inter
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return slope, inter, r2, int(m.sum())


def allan_deviation(t, y):
    """비중첩 Allan 편차. 시각으로 균일 격자에 보간 후 2의 거듭제곱 구간평균.
    반환 (taus[s], adev) 또는 None."""
    if t is None:
        return None
    m = np.isfinite(t) & np.isfinite(y)
    if m.sum() < 16:
        return None
    tt, yy = t[m], y[m]
    o = np.argsort(tt)
    tt, yy = tt[o], yy[o]
    dt = float(np.median(np.diff(tt)))
    if dt <= 0:
        return None
    grid = np.arange(tt[0], tt[-1], dt)
    yi = np.interp(grid, tt, yy)
    n = len(yi)
    taus, ad = [], []
    mm = 1
    while mm <= n // 2:
        k = n // mm
        ym = yi[:k * mm].reshape(k, mm).mean(axis=1)
        d = np.diff(ym)
        ad.append(float(np.sqrt(0.5 * np.mean(d ** 2))))
        taus.append(mm * dt)
        mm *= 2
    return np.array(taus), np.array(ad)
