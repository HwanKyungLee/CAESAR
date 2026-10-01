"""vigil/watcher.py 파일 목록(폴더 나열) 자체검증 — 2026-10-01 '응답 없음' 사고(데이터 불필요).

감시 폴더에 .dat 13.6만 개가 있자 파일마다 os.stat 을 불러 tick 하나가 25 s 였다.
  1) poll 이 파일마다 os.stat/getsize 를 부르지 않는다(나열 결과의 크기를 쓴다)
  2) 전체 나열이 비싸 드물게만 하는 동안에도, 최근 폴더의 새 줄은 매 poll 잡는다
  3) 파일이 잘리면(커서 > 크기) 처음부터 다시 읽는다
  4) 큰 트리는 한 번 경고하고 전체 나열 간격을 늘린다
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

    print(f"\nwatcher scan tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
