#!/usr/bin/env python
"""`[TBD-3.2]` 해석적 Golub–Pereyra 자코비안 대 유한차분 — **스텝 크기와 함께**.

왜 필요한가
-----------
§2 가 "해석적 2항 GP 자코비안" 을 주장한다. Kaufman 근사(1항만)와 완전 GP(2항)는
**둘 다 수렴하지만** 자코비안이 다르다 — 1항만 쓰면 유한차분과 안 맞는다.
그러니 "2항을 쓴다" 는 주장은 **유한차분 일치로만** 증명된다.

스텝 크기를 같이 내는 이유: 단일 h 의 일치도는 h 를 잘 고른 결과일 수 있다.
h 를 쓸면 **절단오차(∝h²)와 반올림오차(∝1/h)의 V 자**가 나와야 하고, 바닥이
√ε ≈ 1.5e-8 근처여야 한다. V 자가 안 나오면 자코비안이 틀린 것이다.

어떻게 잡나
-----------
`objective_varpro` · `jacobian_varpro` 는 `execute_varpro_fit` 안의 클로저라
밖에서 못 부른다. 그래서 **`least_squares` 를 감싸** 운영 경로가 만든 그 함수를
그대로 받아온다 — 테스트용 우회로를 core 에 뚫지 않는다.

데이터 불필요: 저장소 동봉 레퍼런스(`tests/data/wv_cal_roi1`)로 합성한다.
"""
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import core.doas_fit as DF
from core.doas_fit import DoasFitter, alpha_fit_scale
import test_varpro_synthetic_ext as SYN
from test_varpro_synthetic_ext import (POLY_ORDER, build_engine, companion_scds,
                                       props_for, synthesize, window)

# 그쪽은 REFDIR 를 `main()` 안에서 정한다(전역은 None). 같은 탐색 순서를 여기서 돈다.
if SYN.REFDIR is None:
    for _d in SYN.REF_DIRS:
        if _d and os.path.isdir(_d):
            SYN.REFDIR = _d
            break
    if SYN.REFDIR is None:
        print("SKIP  레퍼런스 픽스처를 못 찾았다: %s" % (SYN.REF_DIRS,))
        raise SystemExit(0)

_p = _f = 0


def check(name, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  PASS  %s %s" % (name, extra))
    else:
        _f += 1
        print("  FAIL  %s %s" % (name, extra))


def capture(eng, alpha, vp, center, rp, T=25.0):
    """운영 경로를 한 번 돌리면서 objective/jacobian 클로저를 가로챈다."""
    grabbed = {}
    real = DF.least_squares

    def spy(fun, x0=None, jac=None, bounds=None, **kw):
        if "fun" not in grabbed and callable(jac):
            grabbed.update(fun=fun, jac=jac, x0=np.asarray(x0, float), bounds=bounds)
        return real(fun, x0=x0, jac=jac, bounds=bounds, **kw)

    f = DoasFitter(eng)
    s = alpha_fit_scale(alpha)
    act, fx, lk, t0, lb, ub = f.setup_fit_parameters(rp, 0.0, [0.0, 1.0], 6.0)
    DF.least_squares = spy
    try:
        f.execute_varpro_fit(vp, alpha * s, np.ones(len(vp)), act, fx, lk,
                             t0, lb, ub, POLY_ORDER, 0.12, center, 1.0, rp,
                             T, 0.0, False, allow_negative_gas=True)
    finally:
        DF.least_squares = real
    grabbed["active"] = act
    return grabbed


def main():
    gases = ["NO2", "CHOCHO", "H2O"]
    eng, wave = build_engine(gases)
    vp, center = window(wave)
    rp = props_for(gases)
    scds = companion_scds(eng, gases, 1e12)
    rng = np.random.default_rng(20260922)
    alpha = synthesize(eng, vp, center, scds, shift=-1.96, squeeze=1.0,
                       noise_rms=6.16e-9, rng=rng, etalon_amp=0.01)

    g = capture(eng, alpha, vp, center, rp)
    check("운영 경로가 **해석적** 자코비안을 쓴다(jac 이 콜러블)",
          callable(g.get("jac")), "· active_vars=%s" % g.get("active"))
    if not callable(g.get("jac")):
        print("\nvarpro jacobian tests: %d PASS · %d FAIL" % (_p, _f + 1))
        return 1

    fun, jac, x0 = g["fun"], g["jac"], g["x0"]
    lo, hi = (np.asarray(b, float) for b in g["bounds"])
    # 상자 안쪽 점에서 잰다 — 경계에서는 중앙차분이 상자를 넘는다
    th = np.clip(x0, lo + 1e-3, hi - 1e-3)
    J = np.asarray(jac(th), float)
    check("자코비안 형상이 (잔차, θ) 다", J.ndim == 2 and J.shape[1] == len(th),
          "· %s" % (J.shape,))

    # ⚠ **파라미터별로** 낸다. shift 는 px 단위(O(1))인데 squeeze 는 1 근처의
    #   배율이라 상자가 ±0.02 급이다 — 같은 절대 h 가 두 축에서 전혀 다른 크기다.
    #   합쳐서 최대만 보면 어느 축이 튀는지 못 본다(실측: h=1e-2 에서 3.7e-2).
    names = g["active"]
    print("")
    print("  스텝 크기 쓸기 — 절단과 반올림의 V 자가 축마다 나와야 한다")
    print("  %-10s %s" % ("h", "".join("%16s" % n for n in names)))
    HS = (1e-1, 1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8, 1e-9)
    E = np.full((len(HS), len(th)), np.nan)
    for i, h in enumerate(HS):
        for k in range(len(th)):
            if th[k] + h > hi[k] or th[k] - h < lo[k]:
                continue
            e = np.zeros(len(th))
            e[k] = h
            fd = (np.asarray(fun(th + e), float) - np.asarray(fun(th - e), float)) / (2 * h)
            den = np.linalg.norm(J[:, k])
            E[i, k] = np.linalg.norm(fd - J[:, k]) / den if den else np.nan
        print("  %-10.0e %s" % (h, "".join(
            ("%16.3e" % E[i, k]) if np.isfinite(E[i, k]) else "%16s" % "상자밖"
            for k in range(len(th)))))
    best = (float(np.nanmin(E[:, 0])), HS[int(np.nanargmin(E[:, 0]))])

    print()
    check("%s 축이 유한차분과 **1e-5 이내** 일치" % names[0],
          best[0] < 1e-5, "· 최적 h=%.0e 에서 %.2e" % (best[1], best[0]))
    for k in range(1, len(th)):
        check("%s 축도 1e-5 이내" % names[k], np.nanmin(E[:, k]) < 1e-5,
              "· 최적 h=%.0e 에서 %.2e"
              % (HS[int(np.nanargmin(E[:, k]))], np.nanmin(E[:, k])))
    check("최적 h 가 √ε(1.5e-8) 의 1e-4~1e4 배 안 — V 자 바닥이 제자리",
          best[1] is not None and 1.5e-12 <= best[1] <= 1.5e-4,
          "· h=%.0e" % best[1])
    # 큰 h 에서는 절단오차가 지배해야 한다 = 오차가 h 와 같이 커진다
    e1 = None
    for h in (1e-1, 1e-2):
        k = 0
        if th[k] + h <= hi[k] and th[k] - h >= lo[k]:
            ee = np.zeros(len(th))
            ee[k] = h
            fd = (np.asarray(fun(th + ee), float) - np.asarray(fun(th - ee), float)) / (2 * h)
            v = np.linalg.norm(fd - J[:, k]) / np.linalg.norm(J[:, k])
            e1 = v if e1 is None else e1
            last = v
    check("큰 h 에서 오차가 h 와 같이 준다(절단오차 지배)",
          e1 is not None and last < e1, "· 1e-1 %.2e → 1e-2 %.2e" % (e1, last))

    print("\nvarpro jacobian tests: %d PASS · %d FAIL" % (_p, _f))
    return 1 if _f else 0


if __name__ == "__main__":
    raise SystemExit(main())
