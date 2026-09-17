"""tools/za_gas_sigma.py 자체검증 — **순수 함수만** 건다.

의도적으로 sigma 값 자체는 테스트하지 않는다. 그 값은 아직 생산 핏을 재현하지
못한다(za_gas_sigma.py 상단 "재현 상태" 참고). 재현 안 된 숫자에 테스트를 걸면
틀린 값을 고정하는 셈이라 더 나쁘다.

여기서 거는 것은 **설정을 손으로 짐작하지 않는다**는 계약이다. 실측으로, 창·차수를
잘못 짚으면 NO2 가 생산 대비 49배, CHOCHO 5300배까지 틀렸다. 그래서 설정은 반드시
생산 결과 헤더에서 읽어야 하고, 그 파서가 깨지면 즉시 알아야 한다.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.za_gas_sigma import parse_settings, production_medians, make_ref_props

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PNS = os.path.join(ROOT, "diagnostics", "qdoas_crossval_2026-09", "augur_fit", "pns_merge.dat")


def _hdr(tmp, lines):
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("".join(l + "\n" for l in lines))
    return tmp


def test_parses_window_poly_shift_squeeze(tmp_path=None):
    import tempfile
    p = os.path.join(tempfile.mkdtemp(), "r.dat")
    _hdr(p, ["# Channel 2 (PNs) settings: 444-471nm_Poly3_ShLink  gas_temp=0.0C",
             "# Reference Constraints: Sh[-0.5], Sq[0.0]",
             "Time\tNO2", "2026-05-18 00:00:00\t1.0"])
    s = parse_settings(p, "(PNs)")
    assert s["nm"] == (444.0, 471.0), s
    assert s["poly"] == 3, s
    assert s["sh"] == -0.5 and s["sq"] == 0.0, s


def test_picks_the_right_channel_block():
    """헤더에 여러 채널이 있으면 지정한 채널 것만 집어야 한다."""
    import tempfile
    p = os.path.join(tempfile.mkdtemp(), "r.dat")
    _hdr(p, ["# Channel 1 (ANs) settings: 430-460nm_Poly2_ShLink",
             "# Channel 2 (PNs) settings: 444-471nm_Poly3_ShLink",
             "Time\tNO2", "2026-05-18 00:00:00\t1.0"])
    assert parse_settings(p, "(ANs)")["nm"] == (430.0, 460.0)
    assert parse_settings(p, "(PNs)")["poly"] == 3


def test_missing_settings_returns_empty_not_guess():
    """못 찾으면 **빈 dict**여야 한다 — 기본값을 지어내면 조용히 틀린 창으로 핏한다."""
    import tempfile
    p = os.path.join(tempfile.mkdtemp(), "r.dat")
    _hdr(p, ["# nothing useful here", "Time\tNO2", "2026-05-18 00:00:00\t1.0"])
    assert parse_settings(p, "(PNs)") == {}


def test_real_production_header_is_readable():
    """저장소에 있는 실제 생산 결과로도 돌아야 한다(형식이 바뀌면 여기서 잡힌다)."""
    if not os.path.exists(PNS):
        return
    s = parse_settings(PNS, "(PNs)")
    assert s.get("nm") == (444.0, 471.0), s
    assert s.get("poly") == 3 and s.get("sh") == -0.5, s
    med = production_medians(PNS, ["NO2", "CHOCHO"])
    assert 0.1 < med["NO2"] < 100.0, med
    assert med["CHOCHO"] > 0.0, med


def test_ref_props_fixes_shift_and_links_the_rest():
    rp = make_ref_props(-0.5, 0.0)
    assert rp["NO2"]["sh_mode"] == "Fix" and float(rp["NO2"]["sh_val"]) == -0.5
    assert rp["NO2"]["sq_mode"] == "Fix" and float(rp["NO2"]["sq_val"]) == 0.0
    for g in ("CHOCHO", "H2O"):
        assert rp[g]["sh_mode"] == "Link" and rp[g]["sh_val"] == "NO2"
    # 인자가 없으면 모듈 기본으로 돌아가되, 링크 구조는 유지된다.
    assert make_ref_props(None, None)["CHOCHO"]["sh_mode"] == "Link"


def test_ref_props_are_independent_objects():
    """한 기체의 props 를 바꿔도 다른 기체가 따라 바뀌면 안 된다(dict 공유 사고)."""
    rp = make_ref_props(-0.5, 0.0)
    rp["CHOCHO"]["t_coeff"] = 1.234
    assert rp["H2O"]["t_coeff"] == 0.0, rp["H2O"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("  OK  " + name)
    print("za_gas_sigma helpers: all passed")
