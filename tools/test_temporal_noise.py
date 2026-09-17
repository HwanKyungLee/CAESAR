"""tools/temporal_noise.py 자체검증 — 합성 신호로 Allan 편차의 계약을 건다.

지키는 계약 넷:
  1. 백색잡음이면 sigma_A(1) = sigma 이고, sigma_A(tau) 는 1/sqrt(tau) 로 준다.
     (이게 깨지면 "평균내면 좋아진다"는 결론 자체를 못 믿는다.)
  2. 랜덤워크(드리프트)면 그 1/sqrt(tau) 법칙이 **깨진다** — 도구가 드리프트를
     드리프트로 보여야 쓸모가 있다.
  3. 시간이 끊긴 자리에서는 차분하지 않는다. 캘 사이클 앞뒤를 차분하면 그건
     노이즈가 아니라 그냥 시간인데, 그게 섞이면 노이즈를 몇 배로 부풀린다.
  4. NaN(QC 배제행 등)도 구간을 끊는다.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.temporal_noise import allan_sigma, contiguous_runs

TAUS = (1, 2, 5, 10, 30)


def test_white_noise_follows_root_tau():
    rng = np.random.default_rng(0)
    v = rng.normal(0.0, 2.5, 60_000)
    runs = [v]
    s1 = allan_sigma(runs, 1)
    assert abs(s1 - 2.5) / 2.5 < 0.03, s1
    for t in TAUS:
        got, pred = allan_sigma(runs, t), s1 / np.sqrt(t)
        assert abs(got - pred) / pred < 0.15, (t, got, pred)


def test_offset_does_not_change_sigma():
    """차분 통계라 일정한 오프셋(농도 수준)에 흔들리면 안 된다."""
    rng = np.random.default_rng(1)
    v = rng.normal(0.0, 1.0, 20_000)
    a, b = allan_sigma([v], 1), allan_sigma([v + 1e4], 1)
    assert abs(a - b) / a < 1e-6, (a, b)


def test_random_walk_breaks_the_root_tau_law():
    rng = np.random.default_rng(2)
    v = np.cumsum(rng.normal(0.0, 1.0, 60_000))
    s1 = allan_sigma([v], 1)
    got, pred = allan_sigma([v], 30), s1 / np.sqrt(30)
    assert got / pred > 5.0, (got, pred, got / pred)


def test_runs_break_at_time_gaps():
    """간격이 벌어진 두 스캔 사이의 큰 점프가 노이즈로 새면 안 된다."""
    step = 60.0
    t = np.concatenate([np.arange(50) * step, 50 * step + 9999 + np.arange(50) * step])
    v = np.concatenate([np.zeros(50), np.full(50, 1000.0)])   # 점프는 간격 자리에만
    runs = contiguous_runs(t, v, step)
    assert len(runs) == 2 and all(len(r) == 50 for r in runs), [len(r) for r in runs]
    assert allan_sigma(runs, 1) == 0.0          # 구간 안은 완전 평탄


def test_runs_break_at_nan():
    step = 60.0
    t = np.arange(30) * step
    v = np.zeros(30)
    v[10] = np.nan                               # QC 배제행 한 줄
    runs = contiguous_runs(t, v, step)
    assert [len(r) for r in runs] == [10, 19], [len(r) for r in runs]


def test_short_runs_are_dropped_not_crashed():
    step = 60.0
    t = np.array([0.0, step, 9e9, 9e9 + step * 5])
    v = np.array([1.0, 2.0, 3.0, 4.0])
    runs = contiguous_runs(t, v, step)
    assert [len(r) for r in runs] == [2], [len(r) for r in runs]
    assert np.isnan(allan_sigma(runs, 10))       # tau 가 구간보다 길면 nan


def test_empty_input_is_nan_not_exception():
    assert np.isnan(allan_sigma([], 1))
    assert contiguous_runs([], [], 60.0) == []
    assert contiguous_runs([0.0], [1.0], 60.0) == []


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print(f"  OK  {name}")
    print("temporal noise: all passed")
