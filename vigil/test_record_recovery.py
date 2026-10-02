"""1분 기록(vigil/record.py) 정전 복구 자체검증 (2026-10-02 리뷰, 데이터 불필요).

  1) 잘린 마지막 레코드가 있는 .vrec 에 재시작 후 이어 쓰면, 앞 기록 + 새 기록이 전부 바르게 읽힌다
     (예전: 경계가 어긋나 그날 나머지가 쓰레기)
  2) 깨진 .vrec.json(쓰다 죽음) → 예외 없이 새 번호 파일로 기록이 계속된다
     (예전: JSONDecodeError 가 OSError 가 아니라 매분 tick 이 실패)
"""
import json
import math
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_self_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from vigil.record import MinuteRecorder, read_records

_n_pass = _n_fail = 0
T0 = 1_790_000_000.0 - (1_790_000_000.0 % 86400) + 3600   # 어느 날 01:00 UTC


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def main():
    d = tempfile.mkdtemp()
    try:
        cols = {"a": 1.0, "b": 2.0, "c": None}
        r = MinuteRecorder(d)
        for k in range(3):
            r.maybe_write(T0 + 60 * k, {"a": float(k), "b": 10.0 + k, "c": None})
        path = r._path
        with open(path, "ab") as fh:                    # 정전: 반쯤 쓴 레코드
            fh.write(b"\x00" * 7)

        r2 = MinuteRecorder(d)                          # 재시작
        for k in range(3, 5):
            r2.maybe_write(T0 + 60 * k, {"a": float(k), "b": 10.0 + k, "c": None})
        check("같은 파일에 이어 씀", r2._path == path, (r2._path, path))
        c, t, v = read_records(path)
        check("레코드 5개", len(t) == 5, len(t))
        check("시각이 바르다", list(t) == [T0 + 60 * k for k in range(5)], list(t))
        check("값이 바르다(이어 쓴 것 포함)",
              [float(x) for x in v[:, 0]] == [0, 1, 2, 3, 4] and all(math.isnan(x) for x in v[:, 2]),
              v[:, 0])

        # 2) 깨진 메타
        d2 = tempfile.mkdtemp(dir=d)
        r3 = MinuteRecorder(d2)
        r3.maybe_write(T0, cols)
        with open(r3._path + ".json", "w", encoding="utf-8") as fh:
            fh.write('{"version": 1, "colu')
        r4 = MinuteRecorder(d2)
        ok = r4.maybe_write(T0 + 60, cols)
        check("깨진 메타: 예외 없이 기록", ok is True)
        check("깨진 메타: 새 번호 파일로", r4._path.endswith("_2.vrec"), r4._path)
        check("깨진 메타: 새 파일 읽힘", len(read_records(r4._path)[1]) == 1)
        check("메타 임시 파일이 남지 않음",
              not any(n.endswith(".tmp") for n in os.listdir(os.path.dirname(r4._path))))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\nrecord recovery tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
