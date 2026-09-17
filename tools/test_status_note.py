"""Status 노트 생성기 자체검증 — `AnalysisWorker._solver_status_note`.

Status 문자열은 **직교하는 축들을 ` · ` 로 이어 붙인** 자유형식이다:

    <품질라벨> [· SATURATED n] [· AT_BOUND(파라미터)] [· MISFIT] [· UNDERDETERMINED] …

여기서 지키는 계약은 셋이다.
  1. 품질 라벨(OK/Unstable/…)은 **맨 앞**에 그대로 남는다 — 하류가 전부
     `startswith` 로 읽으므로(QC 기준 ②, 주간플롯, settle_average) 노트를 더해도
     동작이 안 바뀌어야 한다.
  2. 경계 상태에는 **어느 파라미터**가 걸렸는지 붙는다. `AT_BOUND` 하나로는
     넓혀야 할 게 sh 인지 sq 인지 알 수 없다(실측 부록 A-1 이 그 조사를 따로 했다).
  3. `MISFIT`(chi2 > MISFIT_CHI2)은 품질 라벨과 **직교**한다. 상대잔차의 분모는
     mean|신호| 라 농도에 끌려가지만 chi2 의 분모는 그 스캔 자신의 픽셀간
     노이즈다 — `OK · MISFIT` 과 `Unstable`(노트 없음)이 둘 다 나와야 정상이다.

GUI 없이 돈다(QThread 인스턴스를 만들지 않고 메서드만 빌려 쓴다).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.worker import AnalysisWorker, MISFIT_CHI2

ACTIVE_VARS = ["CHOCHO_sh", "H2O_sh", "NO2_sh", "NO2_sq"]


class _Stub:
    """`_solver_status_note` 가 읽는 속성만 가진 더미."""
    _bound_param_names = AnalysisWorker._bound_param_names
    _solver_status_note = AnalysisWorker._solver_status_note


def _note(status, hits=(), chi2=1.0, active_vars=ACTIVE_VARS):
    w = _Stub()
    w._last_solver_termination = {"status": status}
    w._last_bound_hits = list(hits)
    w._last_active_vars = list(active_vars)
    return w._solver_status_note({"Chi2": chi2})


def test_converged_is_silent():
    assert _note("CONVERGED") == ""


def test_bound_names_the_parameter():
    assert _note("AT_BOUND", [{"index": 3}]) == " · AT_BOUND(NO2_sq)"
    assert _note("STEP_LIMITED", [{"index": 0}]) == " · STEP_LIMITED(CHOCHO_sh)"


def test_bound_lists_each_parameter_once():
    assert _note("AT_BOUND", [{"index": 3}, {"index": 2}]) == " · AT_BOUND(NO2_sq,NO2_sh)"
    assert _note("AT_BOUND", [{"index": 3}, {"index": 3}]) == " · AT_BOUND(NO2_sq)"


def test_bound_falls_back_when_name_unknown():
    """이름을 못 찾으면 옛 형식으로 — 괄호가 비거나 IndexError 가 나면 안 된다."""
    assert _note("AT_BOUND", []) == " · AT_BOUND"
    assert _note("AT_BOUND", [{"index": 99}]) == " · AT_BOUND"
    assert _note("AT_BOUND", [{"index": 0}], active_vars=[]) == " · AT_BOUND"


def test_failure_states_take_no_parameter_name():
    """MAX_NFEV/FAILED 는 경계 문제가 아니다 — 경계 이름을 붙이면 오해를 부른다."""
    assert _note("FAILED", [{"index": 3}]) == " · FAILED"
    assert _note("MAX_NFEV", [{"index": 3}]) == " · MAX_NFEV"


def test_misfit_is_orthogonal_to_the_bound_state():
    assert _note("CONVERGED", chi2=MISFIT_CHI2 + 0.1) == " · MISFIT"
    assert _note("AT_BOUND", [{"index": 3}], chi2=9.9) == " · AT_BOUND(NO2_sq) · MISFIT"


def test_misfit_threshold_is_exclusive():
    assert _note("CONVERGED", chi2=MISFIT_CHI2) == ""
    assert _note("CONVERGED", chi2=MISFIT_CHI2 - 1e-9) == ""


def test_missing_or_bad_chi2_never_raises():
    """Chi2 를 못 구한 스캔이 있어도 Status 생성이 터지면 그 행 전체를 잃는다."""
    w = _Stub()
    w._last_solver_termination = {"status": "CONVERGED"}
    w._last_bound_hits = []
    w._last_active_vars = []
    for bad in ({}, {"Chi2": ""}, {"Chi2": None}, {"Chi2": "nan"}, None):
        assert w._solver_status_note(bad) == ""


def test_quality_label_stays_first():
    """하류가 전부 startswith 로 읽는다 — 노트가 라벨을 밀어내면 QC 가 깨진다."""
    for label in ("OK", "Unstable", "Recovered"):
        status = label + _note("AT_BOUND", [{"index": 3}], chi2=9.9)
        assert status.startswith(label), status


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  OK  {name}")
    print("status note: 전부 통과")
