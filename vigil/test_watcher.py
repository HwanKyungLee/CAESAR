"""vigil/{ingest_cursor,watcher,liveness_monitor}.py 단위테스트 (데이터 비의존).

커버:
  1) IngestCursor: set/get 왕복, 재시작(새 인스턴스) 후에도 오프셋 복원
  2) IngestCursor.clamp_to_size: 파일이 잘리면 0으로 리셋
  3) Watcher: 완성된 줄만 소비 — 개행 없는 마지막 줄은 다음 tick까지 보류
  4) Watcher: 이미 처리한 줄은 재관측 안 함(커서 전진 확인)
  5) Watcher: 프로파일 라우팅 → flag role·bytepack 시각 복원
  6) liveness_monitor: SKIP/OK/P0 경계 + latest_arrival 폴딩
  7) 메모리 상한(2026-10-01 현장 PC 다운): tick 당 읽기 상한 → 여러 tick 에 나눠 빠짐없이
     따라잡기, 시작 시 오래된 커서 없는 파일 건너뜀(최근 파일·시작 후 생긴 파일은 처음부터),
     ZA/He 누적 평균이 행을 쌓지 않고 np.mean 과 같은 값

사용: python vigil/test_watcher.py → 전부 PASS면 exit 0
"""
# 한글 Windows 콘솔(cp949)에서 직접 실행해도 '—'·'✓' 등에서 죽지 않게(2026-10-01).
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from vigil.ingest_cursor import IngestCursor
from vigil.monitors.liveness_monitor import check_liveness, latest_arrival
from vigil.alert_engine import OK, P0, SKIP
from vigil.profile import ProfileSet
from vigil.watcher import Watcher

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


def _write_rows(path, n, flag=1, t0=None):
    t0 = t0 or datetime(2026, 5, 26, 12, 0, 0)
    with open(path, "a") as fh:
        for i in range(n):
            fh.write(_line(_cold_row(flag=flag, dt=t0 + timedelta(seconds=i))) + "\n")


def test_tick_budget():
    print("[7a] tick 당 읽기 상한 — 나눠 따라잡고 빠지는 행 없음")
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "2026-05-26-001 Cold.dat")
        _write_rows(f, 50)
        row_bytes = os.path.getsize(f) // 50
        w = Watcher(d, ProfileSet.load_default(), IngestCursor(os.path.join(d, "cursors.json")),
                    max_bytes_per_tick=row_bytes * 10 + row_bytes // 2)   # 10.5행분
        sizes, times = [], []
        for _ in range(10):
            ev = w.poll()
            sizes.append(len(ev))
            times += [e.row_time for e in ev]
            if not ev:
                break
        check("한 tick 에 상한(10행)까지만", max(sizes) == 10, f"{sizes}")
        check("다 따라잡으면 50행 전부, 순서·중복 없음",
              len(times) == 50 and times == sorted(set(times)), f"{len(times)}")
        check("따라잡은 뒤 catching_up False", w.catching_up is False)

        # 행 하나가 상한보다 길어도 멈추지 않는다(완성된 줄 하나는 반드시 소비)
        g = os.path.join(d, "sub", "2026-05-26-002 Cold.dat")
        os.makedirs(os.path.dirname(g))
        _write_rows(g, 3)
        w2 = Watcher(os.path.dirname(g), ProfileSet.load_default(),
                     IngestCursor(os.path.join(d, "c2.json")), max_bytes_per_tick=100)
        n = sum(len(w2.poll()) for _ in range(5))
        check("상한 < 행 길이여도 tick 마다 1행씩 진행", n == 3, f"got {n}")


def test_stale_backlog_skip():
    print("[7b] 시작 시 오래된 커서 없는 파일은 끝에서 시작, 최근·새 파일은 처음부터")
    with tempfile.TemporaryDirectory() as d:
        old = os.path.join(d, "2026-05-25-001 Cold.dat")
        recent = os.path.join(d, "2026-05-26-001 Cold.dat")
        _write_rows(old, 5)
        _write_rows(recent, 3)
        two_h_ago = time.time() - 7200
        os.utime(old, (two_h_ago, two_h_ago))
        cur = IngestCursor(os.path.join(d, "cursors.json"))
        w = Watcher(d, ProfileSet.load_default(), cur)
        ev = w.poll()
        check("최근 파일만 읽음(3행)", len(ev) == 3 and all(e.file == recent for e in ev),
              f"{[(os.path.basename(e.file)) for e in ev]}")
        check("건너뛴 백로그 기록", w.skipped_backlog == (1, os.path.getsize(old)), f"{w.skipped_backlog}")
        check("건너뛴 파일 커서 = 파일 끝", cur.get(old) == os.path.getsize(old))
        # 재시작해도 유지 — 디스크에 쓰지 않고(2026-10-02, cursors.json 20 MB 사고) 같은 규칙이 다시 건너뛴다
        cur.flush()
        w_re = Watcher(d, ProfileSet.load_default(), IngestCursor(os.path.join(d, "cursors.json")))
        check("재시작해도 건너뛴 파일을 다시 읽지 않음",
              all(e.file != old for e in w_re.poll()))
        _write_rows(old, 2, t0=datetime(2026, 5, 25, 13, 0, 0))
        check("건너뛴 파일에 새로 붙은 행은 읽음", len(w.poll()) == 2)

        late = os.path.join(d, "2026-05-26-002 Cold.dat")   # 시작 후 rollover 로 생긴 파일
        _write_rows(late, 4)
        os.utime(late, (two_h_ago, two_h_ago))
        check("시작 후 생긴 파일은 mtime 과 무관하게 처음부터", len(w.poll()) == 4)

        # 커서가 이미 있는 파일은 오래됐어도 이어서 읽는다(재시작 시 빠지는 행 없음)
        with open(recent, "a") as fh:
            fh.write(_line(_cold_row()) + "\n")
        os.utime(recent, (two_h_ago, two_h_ago))
        w2 = Watcher(d, ProfileSet.load_default(), IngestCursor(os.path.join(d, "cursors.json")))
        ev = w2.poll()
        check("커서 있는 오래된 파일은 이어서 읽음", len(ev) == 1 and ev[0].file == recent, f"{len(ev)}")
        check("이번엔 건너뛴 것 없음", w2.skipped_backlog == (0, 0), f"{w2.skipped_backlog}")

        w3 = Watcher(d, ProfileSet.load_default(), IngestCursor(os.path.join(d, "c3.json")),
                     backlog_age_sec=None)
        check("backlog_age_sec=None 이면 전부 처음부터", len(w3.poll()) == 5 + 2 + 3 + 1 + 4)


def test_running_mean():
    print("[7c] ZA/He 누적 평균 — 행을 쌓지 않고 np.mean 과 같다")
    import numpy as np
    from vigil.monitors.running_mean import RunningMean
    from vigil.monitors.r_monitor import RMonitor
    rng = np.random.default_rng(0)
    xs = rng.normal(30000, 50, (200, 2048))
    rm = RunningMean()
    check("빈 누적기는 False", not rm)
    for x in xs:
        rm.add(list(x))
    check("평균 일치", np.allclose(rm.mean(), xs.mean(axis=0), rtol=0, atol=1e-8))
    r = RMonitor(wave_nm=None, cavity_len_cm=100.0, rl_factor=1.0, roi_nm=(440, 460),
                 warn_drop=None, alarm_drop=None)
    for x in xs:
        r.observe("za_inject", x, 25.0, 1013.0)
    check("ZA 고착 200행에도 버퍼는 합 하나", r._za_buf[0].n == 200 and r._za_buf[0]._sum.shape == (2048,))


def main():
    for t in (test_cursor_roundtrip, test_cursor_clamp, test_watcher_partial_line,
              test_watcher_incremental_and_routing, test_liveness,
              test_tick_budget, test_stale_backlog_skip, test_running_mean):
        t()
    print(f"\nwatcher/liveness tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
