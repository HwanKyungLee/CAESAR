"""oculus/{ingest_cursor,watcher,liveness_monitor}.py 단위테스트 (데이터 비의존).

커버:
  1) IngestCursor: set/get 왕복, 재시작(새 인스턴스) 후에도 오프셋 복원
  2) IngestCursor.clamp_to_size: 파일이 잘리면 0으로 리셋
  3) Watcher: 완성된 줄만 소비 — 개행 없는 마지막 줄은 다음 tick까지 보류
  4) Watcher: 이미 처리한 줄은 재관측 안 함(커서 전진 확인)
  5) Watcher: 프로파일 라우팅 → flag role·bytepack 시각 복원
  6) liveness_monitor: SKIP/OK/P0 경계 + latest_arrival 폴딩

사용: python oculus/test_watcher.py → 전부 PASS면 exit 0
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from oculus.ingest_cursor import IngestCursor
from oculus.monitors.liveness_monitor import check_liveness, latest_arrival
from oculus.alert_engine import OK, P0, SKIP
from oculus.profile import ProfileSet
from oculus.watcher import Watcher

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


COLD_ID = "caesar_cold_2026yeosu"


def _cold_row(n_columns=6179, flag=1, dt=None):
    """cold 프로파일 열수에 맞는 합성 행. flag·bytepack 시각을 심는다."""
    row = [800.0] * n_columns
    dt = dt or datetime(2026, 5, 26, 12, 0, 0)
    year_start = datetime(dt.year, 1, 1)
    cs = int((dt - year_start).total_seconds() * 100)
    row[0] = (cs >> 16) & 0xFFFF   # hi_col
    row[1] = cs & 0xFFFF           # lo_col
    row[4] = flag                  # state_flag_col
    return row


def _line(row) -> str:
    return "\t".join(str(v) for v in row)


def test_cursor_roundtrip():
    print("[1] IngestCursor set/get 왕복 + 재시작 복원")
    with tempfile.TemporaryDirectory() as d:
        state = os.path.join(d, "cursors.json")
        f = os.path.join(d, "x.dat")
        open(f, "w").close()
        c1 = IngestCursor(state)
        check("초기 오프셋 0", c1.get(f) == 0)
        c1.set(f, 123)
        check("set 직후 get", c1.get(f) == 123)
        c2 = IngestCursor(state)   # 재시작 시뮬레이션 — 새 인스턴스, 같은 파일
        check("재시작 후 오프셋 복원", c2.get(f) == 123, f"got {c2.get(f)}")


def test_cursor_clamp():
    print("[2] IngestCursor.clamp_to_size — 파일이 잘리면 0으로")
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "x.dat")
        with open(f, "w") as fh:
            fh.write("0123456789")   # 10 bytes
        c = IngestCursor(os.path.join(d, "cursors.json"))
        c.set(f, 10)
        check("정상 크기는 안 잘림", c.clamp_to_size(f) == 10)
        with open(f, "w") as fh:
            fh.write("ab")           # 파일이 2바이트로 잘림(로테이션/재시작 등)
        check("잘린 파일은 0으로 리셋", c.clamp_to_size(f) == 0)


def test_watcher_partial_line():
    print("[3] Watcher — 개행 없는 마지막 줄은 보류")
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "2026-05-26-001 Cold.dat")
        with open(f, "w") as fh:
            fh.write(_line(_cold_row()))   # 개행 없음 — 아직 쓰는 중
        ps = ProfileSet.load_default()
        w = Watcher(d, ps, IngestCursor(os.path.join(d, "cursors.json")))
        events = w.poll()
        check("미완성 줄은 이벤트 없음", len(events) == 0, f"got {len(events)}")
        with open(f, "a") as fh:
            fh.write("\n")   # 완성
        events = w.poll()
        check("개행 붙으면 다음 tick에 관측", len(events) == 1, f"got {len(events)}")


def test_watcher_incremental_and_routing():
    print("[4]+[5] Watcher — 증분 읽기 + 프로파일 라우팅(flag role·시각)")
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "2026-05-26-001 Cold.dat")
        dt1 = datetime(2026, 5, 26, 12, 0, 0)
        with open(f, "w") as fh:
            fh.write(_line(_cold_row(flag=1, dt=dt1)) + "\n")
        ps = ProfileSet.load_default()
        cursor = IngestCursor(os.path.join(d, "cursors.json"))
        w = Watcher(d, ps, cursor)

        ev1 = w.poll()
        check("첫 poll에서 1행 관측", len(ev1) == 1, f"got {len(ev1)}")
        check("프로파일 라우팅 성공", ev1[0].profile_id == COLD_ID, f"got {ev1[0].profile_id}")
        check("flag role == sampling", ev1[0].role == "sampling", f"got {ev1[0].role}")
        check("bytepack 시각 복원", ev1[0].row_time == dt1, f"got {ev1[0].row_time}")

        ev_empty = w.poll()
        check("같은 줄 재관측 안 함", len(ev_empty) == 0, f"got {len(ev_empty)}")

        dt2 = dt1 + timedelta(seconds=1)
        with open(f, "a") as fh:
            fh.write(_line(_cold_row(flag=500, dt=dt2)) + "\n")   # ZA 주입
        ev2 = w.poll()
        check("새로 append된 행만 관측", len(ev2) == 1, f"got {len(ev2)}")
        check("두번째 flag role == za_inject", ev2[0].role == "za_inject", f"got {ev2[0].role}")

        # 재시작 시뮬레이션: 새 Watcher/IngestCursor, 같은 상태파일 → 중복 관측 없음
        w2 = Watcher(d, ps, IngestCursor(os.path.join(d, "cursors.json")))
        ev3 = w2.poll()
        check("재시작 후 이미 처리한 행 재관측 안 함", len(ev3) == 0, f"got {len(ev3)}")


def test_liveness():
    print("[6] liveness_monitor — SKIP/OK/P0 + latest_arrival")
    now = datetime(2026, 5, 26, 12, 0, 0)
    status, msg, m = check_liveness(None, now, grace_sec=10)
    check("행 없으면 SKIP", status == SKIP, f"got {status}")

    status, msg, m = check_liveness(now - timedelta(seconds=5), now, grace_sec=10)
    check("허용시간 안이면 OK", status == OK, f"got {status}")

    status, msg, m = check_liveness(now - timedelta(seconds=15), now, grace_sec=10)
    check("허용시간 초과면 P0", status == P0, f"got {status}")
    check("gap_sec metric", abs(m["gap_sec"] - 15.0) < 1e-6, f"got {m.get('gap_sec')}")

    class _Ev:
        def __init__(self, t): self.arrival_time = t
    check("빈 events면 prior 유지", latest_arrival([], now) == now)
    later = now + timedelta(seconds=3)
    check("events 있으면 최신값", latest_arrival([_Ev(later)], now) == later)


def main():
    for t in (test_cursor_roundtrip, test_cursor_clamp, test_watcher_partial_line,
              test_watcher_incremental_and_routing, test_liveness):
        t()
    print(f"\nwatcher/liveness tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
