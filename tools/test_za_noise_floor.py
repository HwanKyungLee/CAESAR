"""tools/za_noise_floor.py 자체검증 — 합성 스펙트럼으로 계약을 건다.

지키는 계약 넷:
  1. `differential` 은 다항식 성분을 **정확히** 뺀다. 안 빠지면 브로드밴드 램프
     드리프트가 노이즈로 계산돼 바닥을 몇 배 부풀린다.
  2. 다항식보다 높은 주파수 성분은 **살려둔다**. 같이 지워버리면 정작 DOAS 가
     쓰는 흡수 구조까지 없애고 노이즈를 과소평가한다.
  3. 백색잡음의 per-scan 산포를 제대로 회수한다.
  4. `deconvolve` 는 제곱차이고, 표본 요동으로 음수가 될 자리에서 0 으로 접는다
     (sqrt 에서 nan 이 나면 표 전체가 조용히 비어버린다).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.za_noise_floor import differential, deconvolve

X = np.linspace(435.0, 480.0, 939)


def test_polynomial_is_removed_exactly():
    for deg in (2, 4):
        y = np.polyval(np.array([3.0, -2.0, 1.0, 0.5, 7.0])[-(deg + 1):], X - X.mean())
        out = differential(y[None, :], X, deg)[0]
        assert np.max(np.abs(out)) < 1e-9 * max(1.0, np.max(np.abs(y))), np.max(np.abs(out))


def test_high_frequency_structure_survives():
    """흡수 구조를 닮은 성분은 남아야 한다."""
    fine = 1e-3 * np.sin(2 * np.pi * (X - X[0]) / 1.5)
    y = fine + np.polyval([1.0, -3.0, 2.0, 5.0, 1.0], X - X.mean())
    out = differential(y[None, :], X, 4)[0]
    assert np.std(out) / np.std(fine) > 0.97, np.std(out) / np.std(fine)


def test_white_noise_level_is_recovered():
    rng = np.random.default_rng(0)
    sigma = 7e-3
    Z = rng.normal(0.0, sigma, (40, len(X)))
    d = differential(Z, X, 4)
    got = float(np.median(np.std(d, axis=0, ddof=1)))
    assert abs(got - sigma) / sigma < 0.08, got


def test_polynomial_removal_does_not_bias_a_flat_block():
    """모든 스캔이 동일하면 산포는 정확히 0 이어야 한다."""
    Z = np.tile(np.polyval([1.0, 2.0, 3.0], X - X.mean()), (12, 1))
    d = differential(Z, X, 4)
    assert float(np.max(np.std(d, axis=0, ddof=1))) < 1e-12


def test_deconvolve_is_quadrature_and_clamps():
    assert abs(deconvolve(5.0, 3.0) - 4.0) < 1e-12
    assert deconvolve(1.0, 2.0) == 0.0          # nan 이 아니라 0
    assert deconvolve(0.0, 0.0) == 0.0


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print(f"  OK  {name}")
    print("za noise floor: all passed")
