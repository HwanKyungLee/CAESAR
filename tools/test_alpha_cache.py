"""alpha_trace 파일 캐시(DataIO._alpha_file, 2026-10-01) 불변식 — 합성, 데이터 비의존.

핏 루프가 스캔마다 알파 파일을 통째로 다시 읽던 것(행당 ~77 ms)을 파일당 1회로 줄였다.
실데이터 4파일 819행 전 출력이 바꾸기 전과 바이트동일함은 도입 때 따로 확인했다. 여기서 지키는 것:

1. 같은 파일 반복 호출은 디스크를 다시 읽지 않는다(캐시 적중).
2. 파일이 바뀌면(append — DAQ/재생성) 다시 읽어 새 행이 보인다. 낡은 캐시 금지.
3. 반환된 파장축을 호출부가 고쳐도 캐시 원본은 그대로다.
4. 경계: 범위 밖·음수 행의 시각은 None(종전 규칙), 범위 밖 행 로드는 RuntimeError.
5. 헤더 없는 구포맷도 종전 기본 레이아웃(3, 1, 2, 0).
"""
import os
import sys
import tempfile
from datetime import datetime

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data_io import DataIO

_n_pass = _n_fail = 0


def check(label, ok, detail=""):
    global _n_pass, _n_fail
    if ok:
        _n_pass += 1
        print(f"  PASS  {label}")
    else:
        _n_fail += 1
        print(f"  FAIL  {label}  {detail}")


def _write(path, n_rows, start=0, header=True, mode="w"):
    with open(path, mode, encoding="utf-8") as fh:
        if header and mode == "w":
            fh.write("# test alpha\n")
            fh.write("# wavelength_nm:\t" + "\t".join(f"{400 + 0.05 * i:.4f}" for i in range(5)) + "\n")
            fh.write("row_idx\tdoy\tdatetime\tT_C\tP_mbar\t" + "\t".join(f"px{10 + i}" for i in range(5)) + "\n")
        for r in range(start, start + n_rows):
            vals = "\t".join(f"{(r + 1) * 1e-7 + i * 1e-9:.6e}" for i in range(5))
            fh.write(f"{r}\t140.5\t2026-05-20 12:00:{r:02d}\t{25 + r * 0.1:.1f}\t1013.0\t{vals}\n")


def main():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "2026-05-20-001_cold_alpha_trace.dat")
        _write(f, 3)

        print("[1] 캐시 적중")
        w, a, T, P = DataIO.load_alpha_trace_row_full(f, 1)
        check("행 1 값", np.isclose(a[0], 2e-7) and T == 25.1 and P == 1013.0, f"{a[0]} {T} {P}")
        check("파장축 = 헤더", np.allclose(w, 400 + 0.05 * np.arange(5)), str(w))
        check("레이아웃(px 시작 10)", DataIO._alpha_layout(f)[:4] == (5, 3, 4, 10), str(DataIO._alpha_layout(f)[:4]))
        reads = {"n": 0}
        real_open = open

        def counting_open(*args, **kw):
            if args and os.path.abspath(str(args[0])) == os.path.abspath(f):
                reads["n"] += 1
            return real_open(*args, **kw)
        import builtins
        builtins.open = counting_open
        try:
            for i in range(3):
                DataIO.load_alpha_trace_row_full(f, i)
                DataIO.parse_alpha_row_time(f, i)
        finally:
            builtins.open = real_open
        check("반복 호출은 파일을 다시 열지 않는다", reads["n"] == 0, f"{reads['n']}회 열림")

        print("[2] 파일이 바뀌면 다시 읽는다")
        _write(f, 2, start=3, mode="a")
        st = os.stat(f)
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))   # 같은 틱 안의 append 대비
        check("행 수 3 → 5", DataIO._count_alpha_trace_data_rows(f) == 5 and len(DataIO._alpha_file(f)[2]) == 5)
        check("새 행(4) 로드", np.isclose(DataIO.load_alpha_trace_row_full(f, 4)[1][0], 5e-7))
        check("새 행(4) 시각", DataIO.parse_alpha_row_time(f, 4) == datetime(2026, 5, 20, 12, 0, 4))

        print("[3] 반환 파장축을 고쳐도 캐시는 그대로")
        w = DataIO.load_alpha_trace_row_full(f, 0)[0]
        w[:] = -1
        check("다음 호출의 파장축 정상", DataIO.load_alpha_trace_row_full(f, 0)[0][0] == 400.0)

        print("[4] 경계")
        check("음수 행 시각 None", DataIO.parse_alpha_row_time(f, -1) is None)
        check("범위 밖 행 시각 None", DataIO.parse_alpha_row_time(f, 99) is None)
        try:
            DataIO.load_alpha_trace_row_full(f, 99)
            check("범위 밖 행 로드는 RuntimeError", False)
        except RuntimeError:
            check("범위 밖 행 로드는 RuntimeError", True)

        print("[5] 헤더 없는 구포맷")
        g = os.path.join(d, "old_alpha_trace.dat")
        with open(g, "w") as fh:
            fh.write("0\t25.0\t1013.0\t1e-7\t2e-7\n")
        check("기본 레이아웃", DataIO._alpha_layout(g) == (3, 1, 2, 0, None))
        check("시각 None", DataIO.parse_alpha_row_time(g, 0) is None)
        check("행 로드", np.allclose(DataIO.load_alpha_trace_row_full(g, 0)[1], [1e-7, 2e-7]))

    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    sys.exit(1 if _n_fail else 0)


if __name__ == "__main__":
    main()
