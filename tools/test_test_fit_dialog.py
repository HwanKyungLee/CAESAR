"""gui/test_fit_dialog.py의 순수 로직(Qt 비의존) 단위테스트.

커버:
  1) _resolve_px_bounds: px 단위(px_start 오프셋 보정) / nm 단위(argmin, 보정 불필요)
  2) _assemble_ref_props: target shift Limit→Center 변환(core/fitset_builder.py의
     build_fitset 조립 규칙과 동일 산식인지), target Fix 통과, secondary Independent
     →Limit+squeeze Link, secondary Link→둘 다 Link, t_ref/t_coeff/active_bands_nm 보존

사용: python tools/test_test_fit_dialog.py  → 전부 PASS면 exit 0
"""
import io
import os
import sys

import numpy as np

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gui.test_fit_dialog import _resolve_px_bounds, _assemble_ref_props

_n_pass = 0
_n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def test_resolve_px_bounds():
    print("[1] _resolve_px_bounds")
    wave = np.linspace(430.0, 470.0, 2048)   # px_start=700 스타일 서브레인지 흉내(길이만 씀)

    # px 단위: 검출기 픽셀 번호(774) - px_start(700) = 배열 인덱스 74
    pmin, pmax = _resolve_px_bounds("px", 774, 1550, wave, px_start=700)
    check("px: px_start 보정됨", (pmin, pmax) == (74, 850), f"got {(pmin, pmax)}")

    # px 단위, px_start=0(전체범위 생성)이면 그대로
    pmin, pmax = _resolve_px_bounds("px", 774, 1550, wave, px_start=0)
    check("px: px_start=0이면 원값 그대로", (pmin, pmax) == (774, 1550), f"got {(pmin, pmax)}")

    # px 단위, 하한이 px_start보다 작으면 0으로 클램프
    pmin, pmax = _resolve_px_bounds("px", 100, 200, wave, px_start=700)
    check("px: 음수 인덱스는 0으로 클램프", pmin == 0, f"got pmin={pmin}")

    # nm 단위: wave 배열 자체에서 argmin — px_start 보정이 이미 필요 없음(이 파일의
    # 실제 wave 축이므로), 인덱스는 그대로 배열 인덱스
    pmin, pmax = _resolve_px_bounds("nm", 440.0, 450.0, wave, px_start=700)
    i0 = int(np.abs(wave - 440.0).argmin())
    i1 = int(np.abs(wave - 450.0).argmin())
    check("nm: argmin 결과가 그대로(추가 오프셋 없음)",
          (pmin, pmax) == (min(i0, i1), max(i0, i1)), f"got {(pmin, pmax)}")


def test_assemble_ref_props_target_limit_to_center():
    print("[2] target shift Limit → Center 변환 (core/fitset_builder.py 산식과 동일해야 함)")
    gas_list = ["NO2", "CHOCHO"]
    sh = dict(policy="Limit", lb=-9.0, ub=-1.5, median=-5.25, sigma=0.7)
    sq = dict(policy="Fix", value=1.0)
    out = _assemble_ref_props({}, gas_list, "NO2", sh, sq, links=[])
    # fitset_builder.build_fitset: c_val=median, half=max(|hi-c|,|c-lo|)
    c_val, half = -5.25, max(abs(-1.5 - (-5.25)), abs(-5.25 - (-9.0)))  # max(3.75, 3.75)=3.75
    check("sh_mode == Center", out["NO2"]["sh_mode"] == "Center", out["NO2"])
    check("sh_val == 'center, half' (fitset_builder와 동일 반올림)",
          out["NO2"]["sh_val"] == f"{round(c_val,2)}, {round(half,2)}", out["NO2"]["sh_val"])
    check("squeeze Fix 그대로 통과", out["NO2"]["sq_mode"] == "Fix" and out["NO2"]["sq_val"] == "1.0")


def test_assemble_ref_props_target_fix():
    print("[3] target shift 미결정 → Fix 그대로 통과 (raw Limit로 쓰지 않음)")
    gas_list = ["NO2"]
    sh = dict(policy="Fix", value=0.0, undetermined=True, reason="측정불가")
    sq = dict(policy="Fix", value=1.0)
    out = _assemble_ref_props({}, gas_list, "NO2", sh, sq, links=[])
    check("sh_mode == Fix (Center/Limit 아님)", out["NO2"]["sh_mode"] == "Fix", out["NO2"])
    check("sh_val == '0.0'", out["NO2"]["sh_val"] == "0.0", out["NO2"]["sh_val"])


def test_assemble_ref_props_secondary_independent_vs_link():
    print("[4] secondary Independent→Limit+sq Link / Link→둘 다 Link")
    gas_list = ["NO2", "CHOCHO", "H2O"]
    sh = dict(policy="Fix", value=0.0)
    sq = dict(policy="Fix", value=1.0)
    links = [
        dict(secondary="CHOCHO", decision="Independent", lb=-3.0, ub=3.0),
        dict(secondary="H2O", decision="Link"),
    ]
    out = _assemble_ref_props({}, gas_list, "NO2", sh, sq, links)
    check("CHOCHO: Independent → shift Limit(그 lb/ub)",
          out["CHOCHO"]["sh_mode"] == "Limit" and out["CHOCHO"]["sh_val"] == "-3.0, 3.0",
          out["CHOCHO"])
    check("CHOCHO: Independent여도 squeeze는 target에 Link",
          out["CHOCHO"]["sq_mode"] == "Link" and out["CHOCHO"]["sq_val"] == "NO2", out["CHOCHO"])
    check("H2O: Link → shift/squeeze 둘 다 target에 Link",
          out["H2O"]["sh_mode"] == "Link" and out["H2O"]["sh_val"] == "NO2"
          and out["H2O"]["sq_mode"] == "Link" and out["H2O"]["sq_val"] == "NO2", out["H2O"])


def test_assemble_ref_props_preserves_user_fields():
    print("[5] t_ref/t_coeff/active_bands_nm 보존 (§15-D 사용자 몫 — 자동화 대상 아님)")
    gas_list = ["NO2"]
    old = {"NO2": {"sh_mode": "Fix", "sh_val": "0.0", "sq_mode": "Fix", "sq_val": "1.0",
                   "t_ref": 30.0, "t_coeff": 0.5, "active_bands_nm": "460,495"}}
    sh = dict(policy="Fix", value=0.0)
    sq = dict(policy="Fix", value=1.0)
    out = _assemble_ref_props(old, gas_list, "NO2", sh, sq, links=[])
    check("t_ref 보존", out["NO2"]["t_ref"] == 30.0, out["NO2"])
    check("t_coeff 보존", out["NO2"]["t_coeff"] == 0.5, out["NO2"])
    check("active_bands_nm 보존", out["NO2"]["active_bands_nm"] == "460,495", out["NO2"])


if __name__ == "__main__":
    for t in (test_resolve_px_bounds, test_assemble_ref_props_target_limit_to_center,
              test_assemble_ref_props_target_fix,
              test_assemble_ref_props_secondary_independent_vs_link,
              test_assemble_ref_props_preserves_user_fields):
        t()
    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    sys.exit(1 if _n_fail else 0)
