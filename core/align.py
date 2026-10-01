# -*- coding: utf-8 -*-
"""core/align.py — 시각이 다른 두 시계열 맞추기(결손 가드 포함). Qt 비의존.

Plot Maker(Scatter 다른 데이터셋 짝짓기·Join 데이터셋)와 Result Lab 데이터 계산기가
같은 함수를 쓴다(단일 출처). 결손 판정 배수는 core/day_audit.GAP_FACTOR_FAIL.
"""
from __future__ import annotations

import numpy as np


def auto_max_gap(t):
    """정렬에서 '이 간격을 넘으면 결손'으로 볼 기본값(초) = 표본 간격 중앙값 × GAP_FACTOR_FAIL.
    결손 판정 배수는 core/day_audit 한 곳(단일 출처) — 거기서 2.8 = 연속 결손. 못 정하면 inf."""
    from core.day_audit import GAP_FACTOR_FAIL
    t = np.asarray(t, float)
    t = np.sort(t[np.isfinite(t)])
    if len(t) < 2:
        return np.inf
    d = np.diff(t)
    d = d[d > 0]
    return float(np.median(d) * GAP_FACTOR_FAIL) if d.size else np.inf


def align_to(t_ref, t_src, v_src, max_gap=None, method="linear"):
    """v_src(t_src)를 t_ref 시각으로 옮긴다 — 결손을 가로질러 잇지 않는다.

    linear  : t_ref를 감싸는 두 원본 점이 모두 유효하고 그 간격이 max_gap 이하일 때만 보간.
    nearest : 가장 가까운 유효 원본 점이 max_gap/2 안에 있을 때만 그 값.
    정확히 같은 시각은 언제나 그 값. 범위 밖·결손 구간은 NaN.

    max_gap=None → `auto_max_gap(t_src)`. 예전엔 `np.interp`를 그대로 써서 몇 시간 떨어진
    두 점 사이도 직선으로 메워 짝지었다(09-21 설계 부록 ④) — 그 점들이 상관·회귀에 섞였다.
    반환: (값 ndarray, 정보 dict{"max_gap","n_ok","n_gap"}) — n_gap = 가드가 버린 점 수."""
    t_ref = np.asarray(t_ref, float)
    t_src = np.asarray(t_src, float)
    v_src = np.asarray(v_src, float)
    m = np.isfinite(t_src) & np.isfinite(v_src)
    ts, vs = t_src[m], v_src[m]
    o = np.argsort(ts, kind="stable")
    ts, vs = ts[o], vs[o]
    out = np.full(t_ref.shape, np.nan)
    gap = auto_max_gap(t_src) if max_gap is None else float(max_gap)
    info = {"max_gap": gap, "n_ok": 0, "n_gap": 0}
    if ts.size == 0:
        return out, info
    fin = np.isfinite(t_ref)
    tr = t_ref[fin]
    hi = np.searchsorted(ts, tr, side="left")          # ts[hi-1] < tr <= ts[hi]
    hi_c = np.clip(hi, 0, ts.size - 1)
    lo_c = np.clip(hi - 1, 0, ts.size - 1)
    exact = ts[hi_c] == tr
    inside = (hi > 0) & (hi < ts.size)
    res = np.full(tr.shape, np.nan)
    if method == "nearest":
        d_lo = np.where(hi > 0, tr - ts[lo_c], np.inf)
        d_hi = np.where(hi < ts.size, ts[hi_c] - tr, np.inf)
        pick_hi = d_hi < d_lo          # 동점(정확히 가운데)은 앞 점 — 결정론
        idx = np.where(pick_hi, hi_c, lo_c)
        dist = np.minimum(d_lo, d_hi)
        ok = exact | (dist <= gap / 2.0)
        res[ok] = vs[idx[ok]]
        guarded = ~ok & np.isfinite(dist)
    else:
        span = ts[hi_c] - ts[lo_c]
        ok_lin = inside & (span <= gap) & (span > 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            w = np.where(ok_lin, (tr - ts[lo_c]) / np.where(span > 0, span, 1.0), 0.0)
        res[ok_lin] = (vs[lo_c] + w * (vs[hi_c] - vs[lo_c]))[ok_lin]
        res[exact] = vs[hi_c][exact]
        guarded = inside & ~ok_lin & ~exact
    out[fin] = res
    info["n_ok"] = int(np.isfinite(out).sum())
    info["n_gap"] = int(guarded.sum())
    return out, info
