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
import warnings

import numpy as np

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gui.test_fit_dialog import (_TestFitOptimizerWorker, _resolve_px_bounds,
                                 _assemble_ref_props, _format_explorer_review)
from gui.app_window import CAESARAnalyzer, _scenario_gas_policy, _channel_worker_gas_policy

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


def test_allow_negative_gas_roundtrip_policy():
    print("[6] allow_negative_gas 저장/복원 정책")
    for saved in (False, True):
        restored, source = _scenario_gas_policy({"allow_negative_gas": saved}, not saved)
        check(f"명시값 {saved} 복원", restored is saved and source == "scenario")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        restored, source = _scenario_gas_policy({}, True)
    check("구 시나리오는 현재값 유지 + 경고", restored is True and bool(caught) and source.startswith("legacy"))

    class Box:
        def __init__(self, value): self.v = value
        def value(self): return self.v
        def setValue(self, value): self.v = value
        def text(self): return str(self.v)
        def setText(self, value): self.v = value
        def currentText(self): return str(self.v)
        def setCurrentText(self, value): self.v = value
        def isChecked(self): return self.v
        def setChecked(self, value): self.v = value

    class Fake:
        _capture_config = CAESARAnalyzer._capture_config
        _apply_config = CAESARAnalyzer._apply_config
        _time_shift_hours = staticmethod(lambda value: float(value))
        _refresh_shsq_summary = lambda self: None

    f = Fake()
    f.ref_widgets = []; f.ref_props = {}; f.loaded_wl_path = ""
    f.txt_min = Box("0"); f.txt_max = Box("1"); f.spin_fit_start_nm = Box(430.0)
    f.spin_fit_end_nm = Box(431.0); f.cb_fit_unit = Box("px"); f.spin_poly_deg = Box(3)
    f.spin_step_limit = Box(0.5); f.spin_lambda = Box(0.0); f.chk_robust = Box(False)
    f.chk_allow_neg = Box(False); f.spin_kalman_q = Box(0.1); f.spin_kalman_r = Box(0.2)
    f.spin_d_len = Box(51.8); f.spin_rl_factor = Box(1.0); f.spin_time_shift = Box(0.0)
    f.spin_gas_temp = Box(0.0)
    cfg = f._capture_config()
    f.chk_allow_neg.setChecked(True)
    f._apply_config(cfg, load_refs=False)
    check("실제 capture→apply False roundtrip", f.chk_allow_neg.isChecked() is False)
    policies = [_channel_worker_gas_policy(True, {"allow_negative_gas": value}, True)
                for value in (False, True)]
    check("두 채널 worker 정책이 각 저장값 유지", policies == [False, True])
    try:
        _TestFitOptimizerWorker([], None, {}, "px", 0, 1, 3, 0.5, "NO2", "false")
        check("Test Fit non-bool 정책 거부", False)
    except TypeError:
        check("Test Fit non-bool 정책 거부", True)


def test_explorer_review_is_read_only_contract():
    print("[7] Explorer Review 읽기 전용 계약")
    review = {
        "schema": "fit-explorer-human-review-v1",
        "verdict": "MISSION_LOCAL_ONLY",
        "reason": "mission-specific evidence",
        "stage2": {"candidate_id": "pns-mid", "attempts": 24,
                   "boundary_attempts": 2, "median_ppb": 1.65,
                   "seed_max_delta_ppb": 1e-7},
        "holdout": {"candidate_id": "pns-mid", "attempts": 24,
                    "boundary_attempts": 0, "median_ppb": 1.64,
                    "seed_max_delta_ppb": 2e-7},
        "apply": "FORBIDDEN_REQUIRES_EXPLICIT_HUMAN_ACTION",
    }
    html = _format_explorer_review(review)
    check("조건부 verdict와 Apply 금지 표시", "MISSION_LOCAL_ONLY" in html and "자동 변경하지 않습니다" in html)
    review["apply"] = "ALLOWED"
    try:
        _format_explorer_review(review)
        check("자동 Apply 허용 보고서 거부", False)
    except ValueError:
        check("자동 Apply 허용 보고서 거부", True)


if __name__ == "__main__":
    for t in (test_resolve_px_bounds, test_assemble_ref_props_target_limit_to_center,
              test_assemble_ref_props_target_fix,
              test_assemble_ref_props_secondary_independent_vs_link,
              test_assemble_ref_props_preserves_user_fields,
              test_allow_negative_gas_roundtrip_policy,
              test_explorer_review_is_read_only_contract):
        t()
    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    sys.exit(1 if _n_fail else 0)
