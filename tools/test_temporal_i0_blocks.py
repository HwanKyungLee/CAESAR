"""ZA 블록 평균(`AnalysisWorker._group_za_blocks`) 자체검증.

계약 — 연속된 ZA 스캔은 **한 점**이 되고 그 점은 블록 평균이어야 한다.
스캔 하나를 그대로 I0 로 쓰면 그 스캔의 노이즈(실측 7.1e-3)가 알파에 통째로
실리는데, 이건 시간 보간이 고치려는 I0 드리프트(3.8e-3)보다 크다 — 즉 이 평균이
빠지면 Temporal I0 를 켜는 게 끄는 것보다 나빠진다(`tools/za_noise_floor.py` 실측).

GUI 없이 돈다(QThread 인스턴스를 만들지 않고 staticmethod 만 빌려 쓴다).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gui.worker import AnalysisWorker

group = AnalysisWorker._group_za_blocks


def test_one_contiguous_run_becomes_one_averaged_point():
    za = [(10 + i, np.full(4, float(i))) for i in range(5)]      # 값 0..4
    out = group(za)
    assert len(out) == 1, out
    idx, i0 = out[0]
    assert idx == 12, idx                                        # 가운데 index
    assert np.allclose(i0, 2.0), i0                              # 평균


def test_gap_splits_blocks():
    za = ([(0 + i, np.full(3, 1.0)) for i in range(4)] +
          [(100 + i, np.full(3, 5.0)) for i in range(6)])
    out = group(za)
    assert [len(out)] == [2], out
    assert np.allclose(out[0][1], 1.0) and np.allclose(out[1][1], 5.0)
    assert out[0][0] == 2 and out[1][0] == 103, (out[0][0], out[1][0])


def test_averaging_actually_reduces_noise():
    """블록평균의 산포가 단일 스캔의 1/sqrt(n) 로 줄어야 한다 — 이게 전체 요지다."""
    rng = np.random.default_rng(0)
    n, sigma = 35, 7.1e-3
    got = np.std([group([(i, rng.normal(1.0, sigma, 256)) for i in range(n)])[0][1].mean()
                  for _ in range(300)], ddof=1)
    expect = sigma / np.sqrt(n * 256)
    assert 0.7 < got / expect < 1.4, (got, expect)


def test_single_scan_and_empty_are_safe():
    assert group([]) == []
    out = group([(7, np.array([2.0, 4.0]))])
    assert len(out) == 1 and out[0][0] == 7 and np.allclose(out[0][1], [2.0, 4.0])


def test_input_order_is_preserved_as_given():
    """호출부가 index 오름차순으로 준다는 전제 — 블록 순서가 뒤집히면 보간이 깨진다."""
    za = [(0, np.zeros(2)), (1, np.zeros(2)), (50, np.ones(2)), (51, np.ones(2))]
    out = group(za)
    assert [i for i, _ in out] == [1, 51], out


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print(f"  OK  {name}")
    print("za block averaging: all passed")
