"""`n_eff` 바닥이 걸리면 조용하지 않은지 — 그리고 실측 범위에선 안 걸리는지.

배경(2026-09-16 실측): `fitset_builder.select_references` 의
`n_eff = max(n_pix*(1-rho)/(1+rho), 10.0)` 바닥은 **한 번도 걸린 적이 없다.**
여수 3채널 × 창·poly 549조합에서 n_eff 최소 161, rho 최대 0.65.
저장된 optimizer 로그 764건의 실제 핏 잔차 ac1 도 max 0.814 (|ac1|>0.9 는 0%).

그래서 바닥은 손대지 않았다. 대신 걸리면 경고가 나오게 했다 — 걸린다는 건
F검정 자유도가 **관대한 쪽으로** 부풀어 레퍼런스가 과채택된다는 뜻이라
조용히 지나가면 원칙 2의 과적합 함정을 그대로 밟는다.

`python tools/test_n_eff_floor.py` 로 단독 실행 가능.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _n_eff_raw(n_pix, rho):
    return n_pix * (1.0 - rho) / (1.0 + rho)


def test_measured_rho_range_never_hits_floor():
    """실측 rho·n_pix 범위에서는 바닥(10)에 닿지 않는다."""
    # 실측 최악 조합: 가장 좁은 창 × 가장 높은 rho
    worst = _n_eff_raw(n_pix=331, rho=0.6519)
    assert worst > 10.0, f"실측 최악에서도 바닥 위여야 한다 (n_eff={worst:.1f})"
    assert worst > 60.0, f"여유가 생각보다 없다 — 실측 재확인 필요 (n_eff={worst:.1f})"


def test_floor_needs_extreme_rho():
    """바닥에 닿는 rho 경계 — 창 폭에 따라 0.941(좁음)~0.985(넓음).

    실측 rho 최대는 0.652(PNs)이고 실제 핏 잔차 ac1 최대는 0.814 이므로 둘 다 멀다.
    """
    for n_pix, rho_cross in ((331, 0.9413), (1352, 0.9853)):
        assert abs((n_pix - 10) / (n_pix + 10) - rho_cross) < 1e-3
        assert _n_eff_raw(n_pix, rho_cross - 0.01) > 10.0   # 경계 바로 아래 = 안 걸림
        assert _n_eff_raw(n_pix, rho_cross + 0.01) < 10.0   # 바로 위 = 걸림
    assert _n_eff_raw(331, 0.652) > 10.0, "실측 최대 rho 에서 걸리면 안 된다"


def test_floor_warns_when_it_binds():
    """바닥이 걸리면 RuntimeWarning 이 난다 — 조용히 관대해지면 안 된다."""
    import warnings

    import numpy as np

    from core import fitset_builder as FB
    from core import window_designer as WD

    # residual_rho 만 극단값으로 바꿔치기해 바닥을 강제로 밟게 한다.
    real = WD.residual_rho
    WD.residual_rho = lambda *a, **k: 0.995
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                FB.select_references(_StubEngine(), np.zeros((2, 400)), [],
                                     np.linspace(430, 462, 400), 25.0, 1013.25,
                                     0, 299, 4, "NO2")
            except Exception:
                pass          # 스텁이라 뒤에서 죽어도 된다 — 경고가 났는지만 본다
            msgs = [str(x.message) for x in w if issubclass(x.category, RuntimeWarning)]
        assert any("n_eff 바닥 발동" in m for m in msgs), \
            f"바닥이 걸렸는데 경고가 없다: {msgs}"
    finally:
        WD.residual_rho = real


class _StubEngine:
    gas_list: list = []
    interpolators: dict = {}
    scaling_factors: dict = {}


if __name__ == "__main__":
    test_measured_rho_range_never_hits_floor()
    test_floor_needs_extreme_rho()
    test_floor_warns_when_it_binds()
    print("OK: n_eff floor is unreachable in measured range, and loud if it ever binds")
