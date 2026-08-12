"""oculus/{alert_engine,monitors/hk_monitor}.py 단위테스트 (데이터 비의존, 합성 raw 행).

커버:
  1) alert_engine.worse/aggregate — 등급 랭킹, 집계 메시지
  2) hk_monitor: 전 필드 정상 → OK
  3) hk_monitor: WARN 밴드 이탈 → P2
  4) hk_monitor: ALARM 밴드 이탈 → P1
  5) hk_monitor: NaN 값(센서 결측) → P2
  6) hk_monitor: 신호채널 일부 포화 → P1, 전부 포화 → P0

사용: python oculus/monitors/test_hk_monitor.py → 전부 PASS면 exit 0
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from oculus.alert_engine import OK, P0, P1, P2, SKIP, aggregate, worse
from oculus.monitors.hk_monitor import evaluate_hk
from oculus.profile import ProfileSet

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


HOT_ID = "caesar_hot_2026yeosu"


def test_alert_engine():
    print("[1] alert_engine — worse/aggregate")
    check("P0이 가장 심각", worse(OK, P0) == P0)
    check("SKIP은 항상 짐", worse(SKIP, OK) == OK)
    check("동급이면 뒤쪽 유지", worse(P1, P1) == P1)
    status, msg = aggregate([])
    check("빈 리스트 → SKIP", status == SKIP)
    status, msg = aggregate([("a", OK, "fine", {}), ("b", P2, "warn", {})])
    check("OK+P2 → P2", status == P2, f"got {status}")
    status, msg = aggregate([("a", P1, "x", {}), ("b", P0, "y", {})])
    check("P1+P0 → P0", status == P0, f"got {status}")


def _safe_value(field):
    if field.nominal is not None:
        return field.nominal
    for band in (field.warn, field.alarm):
        if band is not None:
            lo, hi = band
            if lo is not None and hi is not None:
                return (lo + hi) / 2.0
            return lo if lo is not None else (hi if hi is not None else 0.0)
    return 0.0


def _hot_row(hot, overrides=None, flag=1, n_columns=6181):
    row = [0.0] * n_columns
    row[hot.header.state_flag_col] = flag
    for f in hot.hk.fields:
        row[hot.hk.start_col + f.rel] = _safe_value(f) / f.scale
    if overrides:
        for key, phys in overrides.items():
            f = hot.hk.field(key)
            row[hot.hk.start_col + f.rel] = phys / f.scale
    return row


def _hot():
    return ProfileSet.load_default().by_id(HOT_ID)


def test_hk_ok():
    print("[2] hk_monitor — 전 필드 정상 → OK")
    hot = _hot()
    row = _hot_row(hot)
    status, msg, metrics = evaluate_hk(hot, row, phase="sampling")
    check("OK", status == OK, f"got {status}: {msg}")


def test_hk_warn():
    print("[3] hk_monitor — WARN 밴드 이탈 → P2")
    hot = _hot()
    # oven_pns_setpoint: nominal 180, warn[175,185], alarm[165,195] → 186은 warn 밖·alarm 안
    row = _hot_row(hot, overrides={"oven_pns_setpoint": 186.0})
    status, msg, metrics = evaluate_hk(hot, row, phase="sampling")
    check("P2", status == P2, f"got {status}: {msg}")


def test_hk_alarm():
    print("[4] hk_monitor — ALARM 밴드 이탈 → P1")
    hot = _hot()
    row = _hot_row(hot, overrides={"oven_pns_setpoint": 200.0})   # alarm[165,195] 밖
    status, msg, metrics = evaluate_hk(hot, row, phase="sampling")
    check("P1", status == P1, f"got {status}: {msg}")


def test_hk_missing():
    print("[5] hk_monitor — NaN(센서 결측) → P2")
    hot = _hot()
    row = _hot_row(hot)
    row[hot.hk.start_col + hot.hk.field("tempcell1").rel] = float("nan")
    status, msg, metrics = evaluate_hk(hot, row, phase="sampling")
    check("P2", status == P2, f"got {status}: {msg}")
    check("메시지에 결측 언급", "결측" in msg, msg)


def test_hk_saturation():
    print("[6] hk_monitor — 부분 포화 P1 / 전 채널 포화 P0")
    hot = _hot()
    ch_pns = hot.channel("ch_pns")
    ch_ans = hot.channel("ch_ans")

    row = _hot_row(hot)
    for c in range(*[ch_pns.columns[0], ch_pns.columns[1] + 1]):
        row[c] = 70000.0   # PNs만 포화(adc_max=64000)
    status, msg, metrics = evaluate_hk(hot, row, phase="sampling")
    check("부분 포화 → P1", status == P1, f"got {status}: {msg}")
    check("포화 채널 목록에 PNs만", metrics["saturated_channels"] == ["PNs"],
          f"got {metrics['saturated_channels']}")

    for c in range(*[ch_ans.columns[0], ch_ans.columns[1] + 1]):
        row[c] = 70000.0   # ANs도 포화 → 전 채널
    status, msg, metrics = evaluate_hk(hot, row, phase="sampling")
    check("전 채널 포화 → P0", status == P0, f"got {status}: {msg}")


def main():
    for t in (test_alert_engine, test_hk_ok, test_hk_warn, test_hk_alarm,
              test_hk_missing, test_hk_saturation):
        t()
    print(f"\nhk_monitor tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
