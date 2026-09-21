"""I0 블록 선두 과도구간 트리밍 — gui.worker.settle_start 의 자체검증.

가장 중요한 게이트는 **운영 알파 무변경**이다: 정상 주기의 ZA/He 블록은
앞에 wait-before 가 27초 돌고 시작해 첫 행부터 평평하므로 한 행도 잘리면 안 된다.
"""
import os
import sys

import numpy as np


def _repo_root(start):
    d = os.path.dirname(os.path.abspath(start))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "core")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("repo root(core/ 를 품은 폴더)를 못 찾았다")


sys.path.insert(0, _repo_root(__file__))

from gui.worker import SETTLE_MIN_ROWS, SETTLE_TOL, settle_start  # noqa: E402

RNG = np.random.default_rng(20260921)
NPIX = 64


def _flat(n, level=14780.0, jitter=0.003):
    """정착 구간: 실측 산포 ~0.3 %."""
    s = level * (1.0 + RNG.normal(0.0, jitter, n))
    return np.repeat(s[:, None], NPIX, axis=1)


_n_pass = _n_fail = 0


def check(label, ok, detail=""):
    global _n_pass, _n_fail
    if ok:
        _n_pass += 1
        print(f"  PASS  {label}")
    else:
        _n_fail += 1
        print(f"  FAIL  {label}  {detail}")


def main():
    # ── G1. 운영 무변경 — 이게 깨지면 기존 알파가 전부 바뀐다 ────────────
    for n in (34, 35, 64):
        blk = _flat(n)
        k = settle_start(blk)
        check(f"정착 블록 {n}행: 트리밍 없음 (k={k})", k == 0)
        if k == 0:
            same = np.array_equal(np.nanmean(blk[k:], axis=0), np.nanmean(blk, axis=0))
            check(f"정착 블록 {n}행: 평균 비트 동일", same)

    # ── G2. 실측 모양 — 2026-08-10-005 의 502 블록 ───────────────────────
    # PNs 17190 -> 14780 (-14 %) 을 14행에 걸쳐, 이후 50행 평평.
    ramp = np.linspace(17190.0, 14850.0, 14)
    blk = np.vstack([np.repeat(ramp[:, None], NPIX, axis=1), _flat(50)])
    k = settle_start(blk)
    check(f"실측형 64행(과도 14 + 정착 50): k={k} in 12~15", 12 <= k <= 15)

    # ANs 는 더 깊다 (-21 %).
    ramp = np.linspace(17131.0, 13560.0, 14)
    blk = np.vstack([np.repeat(ramp[:, None], NPIX, axis=1), _flat(50, level=13520.0)])
    check(f"ANs 형: k={settle_start(blk)} in 12~15", 12 <= settle_start(blk) <= 15)

    # 과도구간은 단조롭지 않다 — 기준 안으로 한 번 들어왔다가 다시 나간다.
    # 실측(2026-08-10-005 PNs): ... 14492(-2.0%) 14593(-1.3%) 15159(+2.5%) ...
    # '처음 들어오는 행'에서 멈추면 7행만 버리고 과도구간 절반을 I0 에 남긴다.
    lvl = np.array([17190, 17209, 17295, 17160, 16810, 15735, 14492, 14593,
                    15159, 15481, 15397, 15162, 14986, 14878], dtype=float)
    blk = np.vstack([np.repeat(lvl[:, None], NPIX, axis=1), _flat(50)])
    k = settle_start(blk)
    check(f"비단조 과도구간: 마지막 이탈 다음까지 버린다 (k={k}, 7 이면 조기중단)",
          k == 12, "처음 들어오는 행에서 멈추는 버그")

    # ── G3. 안전장치 ────────────────────────────────────────────────────
    check(f"{SETTLE_MIN_ROWS}행 미만은 기준을 못 세운다 → 0",
          settle_start(_flat(SETTLE_MIN_ROWS - 1)) == 0)

    # 절반 넘게 버려야 하는 블록 = 전체가 의심 → 통째로 쓰고 0 을 돌려준다.
    blk = np.vstack([np.repeat(np.linspace(20000.0, 15000.0, 40)[:, None], NPIX, axis=1),
                     _flat(20)])
    check(f"절반 초과 트리밍 요구 시 0 (k={settle_start(blk)})", settle_start(blk) == 0)

    # 끝까지 단조 상승 = 정착한 적 없음 → 0.
    blk = np.repeat(np.linspace(14000.0, 18000.0, 40)[:, None], NPIX, axis=1)
    check(f"끝까지 드리프트하면 0 (k={settle_start(blk)})", settle_start(blk) == 0)

    blk = _flat(30)
    blk[3, :] = np.nan
    check("NaN 행이 있으면 판정하지 않는다 → 0", settle_start(blk) == 0)

    check("1차원 입력은 0", settle_start(np.ones(30)) == 0)
    check("빈 입력은 0", settle_start(np.zeros((0, NPIX))) == 0)

    # ── G4. 문턱 양쪽 ───────────────────────────────────────────────────
    # 문턱의 절반만 벗어난 선두는 남기고, 두 배 벗어난 선두는 버린다.
    for mult, want in ((0.5, 0), (2.0, 3)):
        blk = _flat(40, jitter=0.0)
        blk[:3, :] *= (1.0 + SETTLE_TOL * mult)
        check(f"선두 3행이 문턱의 {mult}배 → k={settle_start(blk)} (기대 {want})",
              settle_start(blk) == want)

    print(f"\ni0 settle trim tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
