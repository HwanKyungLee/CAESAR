"""파일 중간의 짧은(잘린·깨진) 행이 tick 하나를 통째로 버리지 않는가 (2026-10-02 리뷰, 데이터 불필요).

프로파일은 파일마다 캐시되므로 짧은 행도 그 프로파일로 넘어갔고, HKField.value 가 IndexError →
tick() 전체가 예외(P1 'internal error'), 커서는 이미 전진해 그 tick 의 행(~80개)이 감시되지 않았다.
  1) Watcher: 짧은 행은 미배정(profile_id None), 앞뒤 정상 행은 배정
  2) VigilApp.tick: 짧은 행이 섞여도 internal 오류 없음, 정상 행은 전부 처리(커서 = 파일 끝)
"""
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_self_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PyQt6.QtCore import QCoreApplication

_n_pass = _n_fail = 0
NC = 6181


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def _row(t, ncols=NC):
    cs = int(t * 100)
    v = ["0"] * NC
    v[0], v[1], v[4] = str(cs >> 16), str(cs & 0xFFFF), "1"
    v[2053:6149] = ["9000"] * 4096
    return "\t".join(v[:ncols])


def main():
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    from vigil.ingest_cursor import IngestCursor
    from vigil.profile import DEFAULT_PROFILE_DIR, ProfileSet
    from vigil.run_vigil import VigilApp
    from vigil.watcher import Watcher

    d = tempfile.mkdtemp()
    try:
        raw, st = os.path.join(d, "raw"), os.path.join(d, "state")
        os.makedirs(raw)
        f = os.path.join(raw, "2026-06-20-001 Hot.dat")
        t0 = 13_000_000
        lines = [_row(t0 + k) for k in range(5)] + [_row(t0 + 5, ncols=3000)] \
            + [_row(t0 + 6 + k) for k in range(5)]
        with open(f, "w") as fh:
            fh.write("\n".join(lines) + "\n")

        w = Watcher(raw, ProfileSet.load_default(), IngestCursor(os.path.join(d, "c.json")))
        ev = w.poll()
        ids = [e.profile_id for e in ev]
        check("Watcher: 11행 모두 이벤트", len(ev) == 11, len(ev))
        check("Watcher: 짧은 행만 미배정", ids[5] is None and all(i is not None for i in ids[:5] + ids[6:]),
              ids)

        core = VigilApp(raw, DEFAULT_PROFILE_DIR, st)
        core.tick()
        kinds = [json.loads(x) for x in open(os.path.join(st, "status.jsonl"), encoding="utf-8")]
        internal = [k for k in kinds if k.get("kind") == "internal"]
        check("tick: internal 오류 없음", not internal, internal[:1])
        check("tick: 파일 끝까지 처리", core.cursor.get(f) == os.path.getsize(f))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\nshort row tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
