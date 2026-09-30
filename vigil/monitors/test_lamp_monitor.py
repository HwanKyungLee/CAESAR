"""vigil/monitors/lamp_monitor.py 단위테스트 (합성 ZA 블록, 데이터 불필요).

커버:
  1) ZA 구간이 끝난 행에서만 판정, 짧은 조각은 무시
  2) 기준선 축적 중엔 OK
  3) 평상시 흔들림(±1 %) OK · 5 % 넘으면 P2 · 15 % 넘으면 P1 (+20 % = 2026-05-26 실사건 크기)
  4) 기준선의 20 % 미만 → P0, 그 블록은 기준선에 안 들어가 복귀가 계단으로 안 보임
  5) 계단 뒤 기준선이 새 레벨에 적응

사용: python vigil/monitors/test_lamp_monitor.py → 전부 PASS면 exit 0
"""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from vigil.alert_engine import OK, P0, P1, P2
from vigil.monitors.lamp_monitor import LampMonitor

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


def _block(lm, level, n=8):
    """ZA 구간 n행 + 샘플링 1행. 마지막 행의 판정을 돌려준다."""
    spec = np.full(64, float(level))
    for _ in range(n):
        assert lm.observe("za_inject", spec) is None
    return lm.observe("sampling", spec * 0.9)


def _warm(lm, level=12000.0, n=6):
    for k in range(n):
        _block(lm, level * (1 + 0.005 * (-1) ** k))


def test_window_and_fragments():
    print("[1] ZA 구간 끝에서만 판정 · 짧은 조각 무시")
    lm = LampMonitor()
    check("샘플링 행은 None", lm.observe("sampling", np.ones(8)) is None)
    check("ZA 2행 조각은 판정 안 함", _block(lm, 12000, n=2) is None)
    r = _block(lm, 12000)
    check("완결 블록은 판정", r is not None and r[0] == OK, str(r))


def test_baseline_accumulation():
    print("[2] 기준선 축적 중")
    lm = LampMonitor()
    r = _block(lm, 5000)
    check("첫 블록 OK + 축적 문구", r[0] == OK and "축적" in r[1], r[1])


def test_levels():
    print("[3] 평상시 / 변화 / 계단")
    lm = LampMonitor(); _warm(lm)
    r = _block(lm, 12000 * 1.01)
    check("+1 % 는 OK", r[0] == OK, r[1])
    lm = LampMonitor(); _warm(lm)
    r = _block(lm, 12000 * 0.92)
    check("-8 % 는 P2", r[0] == P2, r[1])
    lm = LampMonitor(); _warm(lm)
    r = _block(lm, 12000 * 1.20)
    check("+20 % (05-26 실사건) 는 P1", r[0] == P1 and "+20" in r[1], r[1])


def test_dark_and_recovery():
    print("[4] 램프 꺼짐 → P0, 복귀는 계단 아님")
    lm = LampMonitor(); _warm(lm)
    r = _block(lm, 12000 * 0.04)
    check("4 % (06-15 콜드 실사건) 는 P0", r[0] == P0, r[1])
    r = _block(lm, 12000)
    check("복귀 블록은 OK (어두운 블록이 기준선 오염 안 함)", r[0] == OK, r[1])


def test_adapts_after_step():
    print("[5] 계단 뒤 기준선 적응")
    lm = LampMonitor(); _warm(lm, n=4)
    statuses = [_block(lm, 14400)[0] for _ in range(12)]
    check("처음엔 P1", statuses[0] == P1, str(statuses))
    check("새 레벨이 기준선이 되면 OK", statuses[-1] == OK, str(statuses))


def test_moderate_step_stays_visible():
    print("[6] +8 % 계단(06-05 필터 재장착 크기)이 곧바로 꺼지지 않는다")
    lm = LampMonitor(); _warm(lm, n=24)
    statuses = [_block(lm, 12000 * 1.08)[0] for _ in range(8)]
    check("8블록 내내 P2 유지", all(s == P2 for s in statuses), str(statuses))


def main():
    for t in (test_window_and_fragments, test_baseline_accumulation, test_levels,
              test_dark_and_recovery, test_adapts_after_step, test_moderate_step_stays_visible):
        t()
    print(f"\nlamp_monitor tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
