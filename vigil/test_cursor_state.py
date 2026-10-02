"""vigil/ingest_cursor.py 상태 파일 크기·손상 자체검증 (2026-10-02 리뷰, 데이터 불필요).

13.6만 파일 폴더를 감시하면 '오래된 백로그 → 파일 끝' 커서가 파일마다 cursors.json 에 쓰였고,
지워지지도 않았다. ~20 MB·indent=2 저장 한 번이 1.26 s, 5초마다 GUI 스레드에서 돌았다.
  1) 백로그 건너뜀 커서는 디스크에 안 쓴다 — cursors.json 에는 실제로 읽은 파일만
  2) 재시작해도 오래된 파일은 다시 건너뛴다(같은 규칙이 같은 값을 만든다), 새 줄은 이어 읽는다
  3) 옛 버전이 써 둔 백로그 항목(다 읽은 오래된 파일)은 첫 poll 뒤 디스크에서 빠진다
  4) 오래된 파일이 나중에 자라면 그때부터는 디스크에 남는다
  5) 깨진·모양이 틀린 cursors.json 은 .bad 로 옆에 두고 빈 커서로 시작(예외로 죽지 않음)
"""
import json
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


def _on_disk(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    d = tempfile.mkdtemp()
    try:
        old_dir = os.path.join(d, "old")
        live_dir = os.path.join(d, "live")
        os.makedirs(old_dir); os.makedirs(live_dir)
        t_old = time.time() - 7200
        olds = []
        for i in range(200):
            p = os.path.join(old_dir, f"a{i:03d}.dat"); _write(p, [i]); os.utime(p, (t_old, t_old))
            olds.append(p)
        live = os.path.join(live_dir, "2026-10-02-001.dat")
        _write(live, range(3))
        st = os.path.join(d, "s", "cursors.json")

        w = W.Watcher(d, ProfileSet([]), IngestCursor(st))
        ev = w.poll()
        w.cursor.flush()
        disk = _on_disk(st)
        check("첫 poll: 최근 파일만 읽고 오래된 200개 건너뜀",
              [int(e.row[0]) for e in ev] == [0, 1, 2] and w.skipped_backlog[0] == 200, w.skipped_backlog)
        check("cursors.json 에 백로그 항목이 없다(읽은 파일 1개만)",
              list(disk) == [os.path.abspath(live)], f"{len(disk)} entries")
        check("indent 없이 저장", "\n" not in open(st, encoding="utf-8").read().strip())

        # 2) 재시작 — 오래된 파일은 다시 건너뛰고, 살아 있는 파일은 이어 읽는다
        _write(live, [3])
        w2 = W.Watcher(d, ProfileSet([]), IngestCursor(st))
        ev2 = w2.poll()
        check("재시작: 오래된 파일은 다시 건너뛰고 새 줄만", [int(e.row[0]) for e in ev2] == [3],
              [int(e.row[0]) for e in ev2][:10])

        # 3) 옛 버전 상태 파일(백로그 항목 200개가 디스크에 있음) → 첫 poll 뒤 줄어든다
        legacy = {os.path.abspath(p): {"offset": os.path.getsize(p), "mtime": t_old} for p in olds}
        legacy[os.path.abspath(live)] = {"offset": os.path.getsize(live), "mtime": time.time()}
        with open(st, "w", encoding="utf-8") as fh:
            json.dump(legacy, fh, indent=2)
        w3 = W.Watcher(d, ProfileSet([]), IngestCursor(st))
        ev3 = w3.poll()
        w3.cursor.flush()
        disk3 = _on_disk(st)
        check("옛 상태 파일: 새 줄 없음(중복 읽기 없음)", ev3 == [], len(ev3))
        check("옛 상태 파일: 첫 poll 뒤 디스크 항목이 1개로 줄어든다", len(disk3) == 1, len(disk3))

        # 4) 오래된 파일이 나중에 자라면 디스크에 남는다(재시작해도 이어 읽게)
        _write(olds[0], [999])
        w3._next_full = 0                       # 다음 poll 에 전체 나열
        ev4 = w3.poll()
        w3.cursor.flush()
        check("자란 오래된 파일의 새 줄을 읽음", [int(e.row[0]) for e in ev4] == [999],
              [int(e.row[0]) for e in ev4])
        check("자란 파일은 디스크에 남는다", os.path.abspath(olds[0]) in _on_disk(st))

        # 5) 깨진 / 모양이 틀린 상태 파일
        with open(st, "w", encoding="utf-8") as fh:
            fh.write('{"a": {"offset": 1')
        c = IngestCursor(st)
        check("깨진 cursors.json → 빈 커서, .bad 로 보존",
              c.known_files() == [] and os.path.isfile(st + ".bad"))
        os.remove(st + ".bad")
        with open(st, "w", encoding="utf-8") as fh:
            json.dump(["not", "a", "dict"], fh)
        c = IngestCursor(st)
        check("모양이 틀린 cursors.json → 빈 커서, .bad 로 보존",
              c.known_files() == [] and os.path.isfile(st + ".bad"))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\ncursor state tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
