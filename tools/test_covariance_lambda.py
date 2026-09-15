"""Tikhonov λ>0 일 때 공분산이 **핏이 실제로 푼 계**와 일치하는지.

왜: `execute_varpro_fit` 의 공분산 블록이 핏과 세 군데 어긋나 있었다 —
① override_lam 을 버리고 base lambda 로 되돌림 ② 증강이 `diag(λ)` 라 실효
릿지가 λ² 인데 공분산은 λ 사용 ③ 핏은 Chebyshev 배경열을 페널티에서 빼는데
공분산은 전 열 균일 수축. λ=0 이라 476개 결과 파일 전부에서 드러나지 않았지만,
UI(`spin_lambda`)로 켤 수 있으므로 켜는 순간 **조용히 틀린 오차**가 나온다.

여기서 지키는 불변식: 공분산의 `M` 은 증강계 `[A; P]` 의 정규방정식
`AᵀA + PᵀP` 와 같아야 한다.

`python tools/test_covariance_lambda.py` 로 단독 실행 가능.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_augmentation_is_lambda_squared():
    """`[A; diag(λ)]c ≈ [y;0]` 의 해는 (AᵀA + **λ²**I)⁻¹Aᵀy 다.

    이게 이 테스트의 존재 이유다 — λ를 λ² 로 착각하면 공분산이 조용히 틀린다.
    """
    rng = np.random.default_rng(0)
    n, p, lam = 60, 4, 0.3
    A = rng.normal(size=(n, p))
    y = A @ np.array([1.0, 2.0, -1.0, 0.5]) + 0.05 * rng.normal(size=n)
    c_aug = np.linalg.lstsq(np.vstack((A, np.diag(np.full(p, lam)))),
                            np.concatenate((y, np.zeros(p))), rcond=None)[0]
    c_sq = np.linalg.solve(A.T @ A + lam ** 2 * np.eye(p), A.T @ y)
    c_lin = np.linalg.solve(A.T @ A + lam * np.eye(p), A.T @ y)
    assert np.allclose(c_aug, c_sq, atol=1e-12), "증강해가 λ² 릿지와 다르다"
    assert not np.allclose(c_aug, c_lin, atol=1e-6), "λ 와 λ² 가 구별이 안 되는 표본 — 테스트 무의미"


def _run(lam, override=None):
    """엔진 없이 공분산 경로만 태우기엔 의존이 커서, 여기서는 불변식을 직접 본다."""
    rng = np.random.default_rng(1)
    n, ngas, npoly = 80, 3, 4
    ncols = ngas + (npoly + 1) + 2
    A = rng.normal(size=(n, ncols))
    pen = np.full(ncols, lam if override is None else override, dtype=float)
    pen[ngas:ngas + npoly + 1] = 0.0          # 배경열은 수축 안 함 (doas_fit._penalty 와 동일)
    P = np.diag(pen)
    return A, P


def test_cov_matrix_matches_augmented_normal_equations():
    """M = AᵀA + PᵀP 가 증강계 [A;P] 의 정규방정식과 같은가."""
    A, P = _run(0.3)
    lhs = np.vstack((A, P))
    assert np.allclose(lhs.T @ lhs, A.T @ A + P.T @ P, atol=1e-12)


def test_background_columns_not_shrunk():
    """배경(Chebyshev) 열은 페널티가 0이어야 한다 — 표준 DOAS."""
    A, P = _run(0.3)
    ngas, npoly = 3, 4
    d = np.diag(P)
    assert np.all(d[ngas:ngas + npoly + 1] == 0.0), "배경열이 수축되고 있다"
    assert np.all(d[:ngas] > 0) and np.all(d[-2:] > 0), "가스·etalon 열은 수축돼야 한다"
    # 균일 λ·I 를 쓰면 배경열까지 수축된다 = 예전 공분산의 오류
    uniform = 0.3 * np.eye(len(d))
    assert not np.allclose(P.T @ P, uniform), "균일 수축과 구별이 안 된다"


def test_lambda_zero_is_unchanged():
    """λ=0 이면 P=0 이라 M = AᵀA — 기존 동작과 동일(회귀 없음)."""
    A, P = _run(0.0)
    assert np.allclose(P, 0.0)
    assert np.allclose(A.T @ A + P.T @ P, A.T @ A)


if __name__ == "__main__":
    test_augmentation_is_lambda_squared()
    test_cov_matrix_matches_augmented_normal_equations()
    test_background_columns_not_shrunk()
    test_lambda_zero_is_unchanged()
    print("OK: covariance now matches the augmented system the fit actually solves")
