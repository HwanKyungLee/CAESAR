"""vigil/watcher.py 파일 목록(폴더 나열) 자체검증 — 2026-10-01 '응답 없음' 사고(데이터 불필요).

감시 폴더에 .dat 13.6만 개가 있자 파일마다 os.stat 을 불러 tick 하나가 25 s 였다.
  1) poll 이 파일마다 os.stat/getsize 를 부르지 않는다(나열 결과의 크기를 쓴다)
  2) 전체 나열이 비싸 드물게만 하는 동안에도, 최근 폴더의 새 줄은 매 poll 잡는다
  3) 파일이 잘리면(커서 > 크기) 처음부터 다시 읽는다
  4) 큰 트리는 한 번 경고하고 전체 나열 간격을 늘린다
  5) 전체 나열 사이(rescan_sec)에는 끝난 파일을 stat·열기·나열하지 않고 활성 파일만 본다,
     활성 파일의 새 줄은 매 poll, 같은 폴더의 새 파일(rollover)은 전체 나열을 안 기다리고 잡는다
     (폴더 mtime 이 안 바뀌는 파일시스템이어도), 전체 나열 경계를 넘어도 빠지는 행이 없다
"""
import os
import shutil
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_self_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import vigil.watcher as W
from vigil.ingest_cursor import IngestCursor
from vigil.profile import ProfileSet

_n_pass = _n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def _write(path, rows):
    with open(path, "a", encoding="utf-8") as fh:
        for k in rows:
            fh.write(f"{k}\t1.0\t2.0\n")


def _old_files(folder, n, prefix):
    t = time.time() - 7200
    for i in range(n):
        p = os.path.join(folder, f"{prefix}{i:03d}.dat"); _write(p, [i])
        os.utime(p, (t, t))


class _Spy:
    """os.stat · os.scandir · open(watcher 모듈 안) 호출 경로를 센다."""
    def __init__(self):
        self.paths = []

    def __enter__(self):
        self.real = (os.stat, os.scandir)
        real_stat, real_scandir = self.real
        def stat(p, *a, **k):
            self.paths.append(("stat", os.fspath(p)))
            return real_stat(p, *a, **k)
        def scandir(p="."):
            self.paths.append(("scandir", os.fspath(p)))
            return real_scandir(p)
        def opener(p, *a, **k):
            self.paths.append(("open", os.fspath(p)))
            return open(p, *a, **k)
        os.stat, os.scandir = stat, scandir
        W.open = opener                                   # watcher 모듈 안의 open 만 가로챈다
        return self

    def __exit__(self, *exc):
        os.stat, os.scandir = self.real
        del W.open

    def touched(self, folder):
        return [(k, p) for k, p in self.paths if os.path.dirname(p) == folder or p == folder]


def test_active_files():
    d = tempfile.mkdtemp()
    try:
        live = os.path.join(d, "2026-07"); cold = os.path.join(d, "2026-06")
        os.makedirs(live); os.makedirs(cold)
        _old_files(cold, 200, "c")                        # 지난달 폴더 — 끝난 파일만
        _old_files(live, 200, "b")                        # 이번달 폴더 — 끝난 파일 + 자라는 파일 하나
        f = os.path.join(live, "2026-07-01-001.dat"); _write(f, [0])
        w = W.Watcher(d, ProfileSet([]), IngestCursor(os.path.join(d, "s", "c.json")), rescan_sec=3600)
        w.poll()                                          # 첫 poll 은 항상 전체 나열
        w.poll()                                          # (상위 폴더 항목의 mtime 이 늦게 갱신되면 한 번 다시 나열)

        got = []
        with _Spy() as spy:
            for k in range(1, 6):
                _write(f, [k])
                got.append([int(e.row[0]) for e in w.poll()])
        check("(b) 활성 파일에 붙은 줄은 매 poll 관측", got == [[1], [2], [3], [4], [5]], got)
        finished = [x for x in spy.paths if os.path.basename(x[1]).startswith(("b", "c"))]
        check("(a) 전체 나열 사이엔 끝난 파일을 stat·열기 안 함", not finished, finished[:5])
        check("(a) 끝난 파일만 있는 폴더는 나열·stat 안 함", not spy.touched(cold), spy.touched(cold)[:5])
        check("(a) 활성 폴더도 자라는 동안엔 다시 나열 안 함",
              not [x for x in spy.paths if x == ("scandir", live)], spy.paths[:8])

        g = os.path.join(live, "2026-07-01-002.dat")      # 자라는 중에 같은 폴더에 새 파일(폴더 mtime 바뀜)
        _write(f, [6]); _write(g, [100, 101])
        ev = w.poll()
        check("(c) 같은 폴더 새 파일을 전체 나열 없이 잡음(폴더 mtime)",
              sorted((os.path.basename(e.file), int(e.row[0])) for e in ev)
              == [("2026-07-01-001.dat", 6), ("2026-07-01-002.dat", 100), ("2026-07-01-002.dat", 101)],
              [(os.path.basename(e.file), int(e.row[0])) for e in ev])

        # rollover — 폴더 mtime 이 안 바뀌는 파일시스템(FAT/exFAT·일부 공유)을 흉내: 기록값을 지금 값으로 덮는다
        _write(f, [7]); _write(g, [102]); w.poll()        # 둘 다 자람 → 폴더가 '살아 있음'
        h = os.path.join(live, "2026-07-01-003.dat"); _write(h, [200])
        w._dir_mtime[live] = os.stat(live).st_mtime
        ev = w.poll()                                     # f·g 가 안 자랐다 → rollover 의심 → 그 폴더만 나열
        check("(c) 폴더 mtime 없이도 rollover 새 파일을 다음 poll 에 잡음",
              [(os.path.basename(e.file), int(e.row[0])) for e in ev] == [("2026-07-01-003.dat", 200)],
              [(os.path.basename(e.file), int(e.row[0])) for e in ev])
        check("전체 나열은 첫 poll 뿐", w._next_full - time.monotonic() > 3000)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_rescan_boundary():
    d = tempfile.mkdtemp()
    try:
        live = os.path.join(d, "Hot"); other = os.path.join(d, "Cold")
        os.makedirs(live); os.makedirs(other)
        _old_files(live, 50, "b")
        w = W.Watcher(d, ProfileSet([]), IngestCursor(os.path.join(d, "s", "c.json")), rescan_sec=3600)
        want, got, k = [], [], 0
        for step in range(40):
            if step % 7 == 0:                             # rollover — 새 파일
                cur = os.path.join(live, f"2026-07-01-{step:03d}.dat")
            if step == 20:                                # 활성 폴더가 아닌 곳에 새 파일 → 전체 나열이 잡는다
                _write(os.path.join(other, "late.dat"), [9000]); want.append(9000)
            _write(cur, [k, k + 1]); want += [k, k + 1]; k += 2
            if step % 5 == 4:
                w._next_full = 0.0                        # 전체 나열 경계
            got += [int(e.row[0]) for e in w.poll()]
        w._next_full = 0.0
        got += [int(e.row[0]) for e in w.poll()]
        check("(d) 전체 나열 경계·rollover 를 넘어도 행이 빠지거나 중복되지 않음",
              sorted(got) == sorted(want) and len(got) == len(want), (len(got), len(want)))
        rows = [x for x in got if x != 9000]
        check("(d) 순서 유지", rows == sorted(rows))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    d = tempfile.mkdtemp()
    try:
        live = os.path.join(d, "2026-07")
        old = os.path.join(d, "alpha", "x")
        os.makedirs(live); os.makedirs(old)
        for i in range(300):                               # 오래된 산출물 300개
            p = os.path.join(old, f"a{i}.dat"); _write(p, [i])
            t = time.time() - 7200; os.utime(p, (t, t))
        f = os.path.join(live, "2026-07-01-001.dat")
        _write(f, range(3))
        w = W.Watcher(d, ProfileSet([]), IngestCursor(os.path.join(d, "s", "c.json")))

        calls = {"n": 0}
        real_stat, real_getsize = os.stat, os.path.getsize
        def spy_stat(*a, **k):
            calls["n"] += 1
            return real_stat(*a, **k)
        def spy_getsize(p):
            calls["n"] += 1
            return real_getsize(p)
        os.stat, os.path.getsize = spy_stat, spy_getsize
        try:
            ev = w.poll()
            n_first = calls["n"]; calls["n"] = 0
            w.poll()
            n_second = calls["n"]
        finally:
            os.stat, os.path.getsize = real_stat, real_getsize
        check("첫 poll: 최근 파일 3행만, 오래된 300개는 건너뜀",
              [int(e.row[0]) for e in ev] == [0, 1, 2] and w.skipped_backlog[0] == 300, w.skipped_backlog)
        check(f"poll 이 파일마다 stat 하지 않음 (첫 {n_first}회, 다음 {n_second}회 < 10)",
              n_first < 10 and n_second < 10)

        w._next_full = time.monotonic() + 3600            # 전체 나열이 드문 큰 트리처럼
        _write(f, [7, 8])
        ev = w.poll()
        check("전체 나열 사이에도 최근 폴더의 새 줄을 잡음", [int(e.row[0]) for e in ev] == [7, 8])

        with open(f, "w", encoding="utf-8") as fh:        # 잘림(교체)
            fh.write("100\t1.0\t2.0\n")
        ev = w.poll()
        check("잘린 파일은 처음부터 다시 읽음", [int(e.row[0]) for e in ev] == [100])

        big = W.Watcher(d, ProfileSet([]), IngestCursor(os.path.join(d, "s2", "c.json")))
        old_huge, old_cheap = W.HUGE_TREE_FILES, W.FULL_SCAN_CHEAP_SEC
        W.HUGE_TREE_FILES, W.FULL_SCAN_CHEAP_SEC = 100, 0.0
        try:
            big.poll()
        finally:
            W.HUGE_TREE_FILES, W.FULL_SCAN_CHEAP_SEC = old_huge, old_cheap
        check("큰 트리는 한 번 경고하고 전체 나열 간격을 늘림",
              big.huge_tree == 301 and big._next_full - time.monotonic() > W.FULL_SCAN_MIN_INTERVAL_SEC - 1,
              (big.huge_tree, round(big._next_full - time.monotonic(), 1)))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    test_active_files()
    test_rescan_boundary()

    print(f"\nwatcher scan tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
