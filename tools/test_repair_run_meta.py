"""`tools/repair_run_meta.identify` 자체검증 — **못 고르면 고르지 않는다**가 핵심.

이 도구는 기록이 아니라 **추정**을 쓴다(window.px→window.nm 지문). 추정이 틀리면
"이 결과는 cold 로 피팅됐다"는 거짓 기록이 남고, 그건 침묵보다 나쁘다. 그래서
경계 조건을 못박는다. 데이터 불필요(합성 축).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.repair_run_meta import MIN_SEP_NM, identify   # noqa: E402


def _axis(start, step=0.0483, n=2048):
    return start + step * np.arange(n)


COLD = _axis(400.3151)
ROI1 = _axis(400.0076)
ROI2 = _axis(400.0416)      # roi1 과 0.034 nm 차 — 실측 여수 구성


def _meta(px, nm):
    return {"window": {"px": list(px), "nm": list(nm), "unit": "nm"}}


def test_clear_winner_is_picked():
    """콜드 축으로 환산한 값이면 콜드가 뽑힌다(오답과 0.6 nm 이상 벌어진다)."""
    lo, hi = 774, 1550
    m = _meta((lo, hi), (round(COLD[lo], 1), round(COLD[hi], 1)))
    tag, resid, why = identify(m, {'cold/c.txt': COLD, 'roi1/c.txt': ROI1, 'roi2/c.txt': ROI2})
    assert tag == 'cold/c.txt', (tag, resid, why)
    assert resid['roi1/c.txt'] - resid['cold/c.txt'] > MIN_SEP_NM


def test_near_identical_axes_abstain():
    """★roi1/roi2 는 0.03 nm 차 — window.nm 이 소수 1자리라 원리상 구분 불가.
    비율로는 6배 차이가 나도 **절대차가 반올림 잡음 이하**면 포기해야 한다."""
    lo, hi = 899, 1450
    m = _meta((lo, hi), (round(ROI2[lo], 1), round(ROI2[hi], 1)))
    tag, resid, why = identify(m, {'roi1/c.txt': ROI1, 'roi2/c.txt': ROI2})
    assert tag is None, f"구분할 수 없는데 {tag} 을 골랐다 ({resid})"
    assert '절대차' in why or '배수' in why, why


def test_no_window_abstains():
    tag, _, why = identify({}, {'cold/c.txt': COLD})
    assert tag is None and 'window' in why


def test_all_candidates_far_abstains():
    """축이 통째로 다른 경우(예: 다른 분광기) — 1등이라도 채택하지 않는다."""
    m = _meta((100, 200), (900.0, 950.0))
    tag, _, why = identify(m, {'cold/c.txt': COLD, 'roi1/c.txt': ROI1})
    assert tag is None, tag
    assert '어긋남' in why, why


def test_px_outside_axis_is_skipped():
    """픽셀 범위를 담지 못하는 후보는 비교에서 빠진다(짧은 축을 억지로 인덱싱하지 않음)."""
    short = _axis(400.0, n=500)
    lo, hi = 774, 1550
    m = _meta((lo, hi), (round(COLD[lo], 1), round(COLD[hi], 1)))
    tag, resid, _ = identify(m, {'cold/c.txt': COLD, 'short/c.txt': short})
    assert 'short/c.txt' not in resid
    assert tag == 'cold/c.txt'


if __name__ == '__main__':
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn(); print(f"PASS {name}")
            except AssertionError as e:
                fails += 1; print(f"FAIL {name}: {e}")
    print('OK' if not fails else f'{fails} FAILED')
    sys.exit(1 if fails else 0)
