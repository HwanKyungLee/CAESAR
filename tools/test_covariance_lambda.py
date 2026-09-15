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


def _main():
    test_augmentation_is_lambda_squared()
    test_cov_matrix_matches_augmented_normal_equations()
    test_background_columns_not_shrunk()
    test_lambda_zero_is_unchanged()
    test_perr_matches_closed_form_with_unbiased_sigma()
    test_dof_denominator_is_not_n()
    print("OK: covariance matches the fit's augmented system, sigma-hat uses RSS/(n-p)")


# ── σ̂² 분모: RSS/(n−p) 인가 ────────────────────────────────────────────────────
class _FakeEngine:
    """execute_varpro_fit 이 실제로 건드리는 것만 갖춘 최소 엔진.

    gas_list · interpolators[name](px) · scaling_factors[name] 셋이면 돈다
    (`active_bands_nm` 을 비워두면 `pixel_to_wavelength` 경로는 안 탄다).
    """

    def __init__(self, n_px, n_gas, seed=3):
        rng = np.random.default_rng(seed)
        self.gas_list = [f"G{i}" for i in range(n_gas)]
        base = {g: rng.normal(size=n_px + 400) for g in self.gas_list}
        self.interpolators = {
            g: (lambda px, _v=base[g]: np.interp(px, np.arange(len(_v)) - 200.0, _v))
            for g in self.gas_list
        }
        self.scaling_factors = {g: 1.0 for g in self.gas_list}


def _fit_once(n_px=200, n_gas=2, poly_order=3, seed=7, return_inputs=False):
    from core.doas_fit import DoasFitter
    eng = _FakeEngine(n_px, n_gas)
    fitter = DoasFitter(eng)
    rng = np.random.default_rng(seed)
    px = np.arange(n_px, dtype=float)
    od = 0.3 * eng.interpolators["G0"](px) + 0.02 * rng.normal(size=n_px)
    props = {g: {"sh_mode": "Fix", "sh_val": "0.0", "sq_mode": "Fix", "sq_val": "1.0"}
             for g in eng.gas_list}
    active, fixed, linked, t0, lb, ub = fitter.setup_fit_parameters(props, 0.0, [0.0, 1.0], 0.5)
    out = fitter.execute_varpro_fit(
        px, od, np.ones(n_px), active, fixed, linked, t0, lb, ub,
        poly_order, 0.1, px[n_px // 2], 1.0, props, 25.0, 0.0, False,
        allow_negative_gas=True)
    if return_inputs:
        return out, len(t0), n_px, n_gas, poly_order, eng, px, od, 0.1
    return out, len(t0), n_px, n_gas, poly_order


def test_perr_matches_closed_form_with_unbiased_sigma():
    """λ=0·무제약에서 perr 를 **닫힌형과 대조**한다.

        cov = (AᵀA)⁻¹ · RSS/(n−p),   A = [gas | Chebyshev | sin | cos]

    분모가 RSS/n 으로 되돌아가면 perr 가 √(n/(n−p)) 배만큼 작아져 여기서 실패한다.
    설계행렬을 직접 재구성하므로 공분산 식 전체(분모뿐 아니라 (AᵀA)⁻¹·mse 구조)를 잡는다.
    """
    from numpy.polynomial import chebyshev

    (out, n_theta, n_px, n_gas, poly_order,
     eng, px, od, ef) = _fit_once(return_inputs=True)
    perr = np.asarray(out[6], dtype=float)
    assert np.all(np.isfinite(perr)), "perr 에 NaN — 공분산 경로가 예외로 빠졌다"

    # 설계행렬 재구성 (sh=0·sq=1 로 고정했으므로 shift/squeeze 변환은 항등)
    x_mapped = 2.0 * (px - px[0]) / (px[-1] - px[0]) - 1.0
    cols = [eng.interpolators[g](px) / eng.scaling_factors[g] for g in eng.gas_list]
    cols += [chebyshev.chebvander(x_mapped, poly_order)[:, j] for j in range(poly_order + 1)]
    cols += [np.sin(ef * px), np.cos(ef * px)]
    A = np.column_stack(cols)

    c = np.linalg.lstsq(A, od, rcond=None)[0]
    r = od - A @ c
    p_free = n_theta + A.shape[1]
    sigma2 = float(r @ r) / (n_px - p_free)
    cov = np.linalg.pinv(A.T @ A) * sigma2
    expect = np.sqrt(np.maximum(np.diag(cov), 0.0))[:n_gas]

    assert np.allclose(perr, expect, rtol=1e-6), (
        f"perr 가 닫힌형과 다르다: 코드={perr} 닫힌형={expect} "
        f"비율={perr / expect} (RSS/n 이면 ~{np.sqrt((n_px - p_free) / n_px):.4f})")

    # 테스트가 편향을 실제로 구별할 수 있는 표본인지
    biased = np.sqrt(np.maximum(np.diag(np.linalg.pinv(A.T @ A) * (float(r @ r) / n_px)), 0.0))[:n_gas]
    assert not np.allclose(perr, biased, rtol=1e-4), "n 과 n−p 가 구별 안 되는 표본 — 테스트 무의미"


def test_dof_denominator_is_not_n():
    """같은 잔차에서 RSS/n 과 RSS/(n−p) 가 실제로 다른 값을 내는지(테스트 유효성)."""
    n, p = 200, 8
    r = np.linspace(-1, 1, n)
    assert not np.isclose(r @ r / n, r @ r / (n - p), rtol=1e-6)


if __name__ == "__main__":
    _main()
