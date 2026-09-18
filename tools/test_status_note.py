"""Status 노트 생성기 자체검증 — `AnalysisWorker._solver_status_note`.

Status 문자열은 **직교하는 축들을 ` · ` 로 이어 붙인** 자유형식이다:

    <품질라벨> [· SATURATED n] [· AT_BOUND(파라미터)] [· UNDERDETERMINED] …

여기서 지키는 계약은 셋이다.
  1. 품질 라벨(OK/Unstable/…)은 **맨 앞**에 그대로 남는다 — 하류가 전부
     `startswith` 로 읽으므로(QC 기준 ②, 주간플롯, settle_average) 노트를 더해도
     동작이 안 바뀌어야 한다.
  2. 경계 상태에는 **어느 파라미터**가 걸렸는지 붙는다. `AT_BOUND` 하나로는
     넓혀야 할 게 sh 인지 sq 인지 알 수 없다(실측 부록 A-1 이 그 조사를 따로 했다).
  3. 품질 라벨의 축은 **chi2** 다(2026-09-18). 옛 축 `rms < mean|신호| × 10%` 는
     분모가 신호 세기라 **알파가 작아지면 멀쩡한 핏이 Unstable** 로 찍혔다 —
     교차검증 19.2만 행에서 Unstable 행의 RMS 가 OK 행보다 *낮았고*(ANs 1.23e-9 vs
     1.33e-9) chi2 중앙값은 1.05 였다. cold 은 더 나빠서 OK 행의 31.8 %가 chi2>1.5
     였다(축이 품질과 거꾸로 정렬). 판정은 `core.result_io.quality_label` 한 곳.
     같은 축을 두 번 말하지 않으려고 예전 ` · MISFIT` 노트는 빠졌다.
  4. `_apply_qc` 는 **Unstable 을 배제 근거로 쓰지 않는다**(2026-09-18). 상대 RMS 는
     신호 세기 축이라 저농도 행(chi2~1 = 멀쩡한 핏)을 지우면서 평균을 위로 편향시킨다.
     또 사유는 Status 를 **덮어쓰지 않고 앞에 붙인다** — 포화·헤더행·경계 노트가
     정작 그게 가장 필요한 배제행에서 사라지고 있었다.

GUI 없이 돈다(QThread 인스턴스를 만들지 않고 메서드만 빌려 쓴다).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.result_io import MISFIT_CHI2, quality_label
from gui.worker import AnalysisWorker

ACTIVE_VARS = ["CHOCHO_sh", "H2O_sh", "NO2_sh", "NO2_sq"]


class _Stub:
    """`_solver_status_note` 가 읽는 속성만 가진 더미."""
    _bound_param_names = AnalysisWorker._bound_param_names
    _solver_status_note = AnalysisWorker._solver_status_note
    _low_signal_retry = AnalysisWorker._low_signal_retry
    _apply_qc = AnalysisWorker._apply_qc


def _note(status, hits=(), active_vars=ACTIVE_VARS):
    w = _Stub()
    w._last_solver_termination = {"status": status}
    w._last_bound_hits = list(hits)
    w._last_active_vars = list(active_vars)
    w._last_underdetermined = False
    return w._solver_status_note()


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


def test_label_axis_is_chi2_not_signal_strength():
    """〖〖 이 한 개가 번집의 이유 〗〗  핵심 회거.

    알파가 아무리 작아도(= RMS/신호 가 커지는 상황) chi2 가 정상이면 OK 여야 한다.
    이게 뒤집힐 수 있는 것이 보고된 증상(Unstable 이 24~34 % 뜨는 것) 의 원인이다."""
    assert quality_label(1.05) == "OK"                       # ANs Unstable 행 중앙값
    assert quality_label(1.01) == "OK"                       # PNs Unstable 행 중앙값
    assert quality_label(MISFIT_CHI2) == "OK"                # 경계 포함
    assert quality_label(MISFIT_CHI2 + 1e-9) == "Unstable"
    assert quality_label(12.8) == "Unstable"                 # cold 진짜 미스핏 p95
    assert quality_label(1.0, attempt=1) == "Recovered"
    assert quality_label(9.9, attempt=1) == "Unstable"       # 다시 해도 미스핏이면 Unstable


def test_missing_chi2_flags_instead_of_passing():
    """Chi2 를 못 구한 행이 조용히 OK 로 새면 안 된다 — 헌장: 지우지 말고 flag."""
    for bad in (None, "", "nan", float("nan"), "abc", {}):
        assert quality_label(bad) == "Unstable", bad


def test_note_never_raises_and_carries_no_chi2():
    """노트는 이제 chi2 를 안 본다 — 상태가 없으면 조용해야 한다."""
    w = _Stub()
    w._last_solver_termination = None
    w._last_bound_hits = []
    w._last_active_vars = []
    w._last_underdetermined = False
    assert w._solver_status_note() == ""
    assert "MISFIT" not in _note("CONVERGED")


def test_quality_label_stays_first():
    """하류가 전부 startswith 로 읽는다 — 노트가 라벨을 밀어내면 QC 가 깨진다."""
    for label in ("OK", "Unstable", "Recovered"):
        status = label + _note("AT_BOUND", [{"index": 3}])
        assert status.startswith(label), status


class _Engine:
    gas_list = ["NO2", "CHOCHO"]


def _qc(status, rms=1e-8, snr=5.0, rms_abs=0.0, snr_min=0.0, enabled=True):
    """`_apply_qc` 를 돌리고 (Status, NO2 값) 을 돌려준다."""
    w = _Stub()
    w.engine = _Engine()
    w.qc_enabled = enabled
    w.qc_rms_abs = rms_abs
    w.qc_snr_min = snr_min
    w.ok_rms_threshold = 0.10
    r = {"Status": status, "RMS": rms, "SNR": snr, "NO2": 2.5, "NO2_Smooth": 2.4, "CHOCHO": 0.1}
    w._apply_qc(r)
    return r["Status"], r["NO2"], r["NO2_Smooth"]


def test_unstable_is_not_a_qc_reason():
    """계약 4. 상대 RMS 라벨만으로는 아무것도 배제하지 않는다 — 이게 뒤집히면
    저농도 행 24~34% 가 다시 NaN 이 되고 평균이 위로 편향된다."""
    for label in ("Unstable", "Unstable · MISFIT", "Unstable · AT_BOUND(NO2_sq)"):
        st, v, _ = _qc(label)
        assert st == label, st
        assert v == 2.5, v


def test_absolute_rms_and_snr_still_exclude():
    st, v, sm = _qc("OK", rms=9e-8, rms_abs=5e-8)
    assert st.startswith("QC-Excluded (rms=9.0e-08>5.0e-08)"), st
    assert v != v and sm != sm, (v, sm)          # 둘 다 NaN
    st, v, _ = _qc("OK", snr=0.5, snr_min=3)
    assert st.startswith("QC-Excluded (snr<3)"), st
    assert v != v, v


def test_qc_reason_is_prepended_not_overwritten():
    """계약 4 후반. 포화·헤더행 노트가 배제행에서 살아남아야 한다."""
    orig = "Unstable · SATURATED 3 · AT_BOUND(NO2_sq) · header row (T/P borrowed from next scan)"
    st, _, _ = _qc(orig, rms=9e-8, rms_abs=5e-8)
    assert st.startswith("QC-Excluded ("), st       # 하류 startswith 계약
    assert st.endswith(orig), st                    # 아무것도 안 잃는다


def test_qc_disabled_touches_nothing():
    st, v, _ = _qc("OK", rms=9e-8, rms_abs=5e-8, enabled=False)
    assert (st, v) == ("OK", 2.5), (st, v)


def test_low_signal_retry_keeps_the_old_axis():
    """옛 상대 RMS 식은 **retry 트리거로만** 남았다. 여기를 바꾸면 저농도 행의
    농도 숫자가 (1차 핏 vs 2차 핏으로) 달라지므로 라벨 교체와 분리해 뒀다."""
    w = _Stub()
    w.ok_rms_threshold = 0.10
    assert w._low_signal_retry(0.005, 1.0) is False      # 신호 충분 → 재시도 없음
    assert w._low_signal_retry(0.5, 1.0) is True
    assert w._low_signal_retry(0.10, 1.0) is True        # 경계 = 재시도
    assert w._low_signal_retry(float("nan"), 1.0) is True
    assert w._low_signal_retry(None, 1.0) is True        # 판정 불가 → 방어적으로 재시도


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  OK  {name}")
    print("status note: 전부 통과")
