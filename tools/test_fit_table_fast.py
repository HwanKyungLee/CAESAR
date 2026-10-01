# -*- coding: utf-8 -*-
"""tools/test_fit_table_fast.py — load_fit_table 빠른 경로가 행별(예전) 구현과 같은 배열을 내는가.

2026-10-02: 26만 행 파일 읽기를 줄이려고 ① 칸 꺼내기를 2차원 object 배열 한 번으로 ② 숫자는
astype(float)(원소마다 파이썬 float — 같은 변환) ③ 시각은 형식이 맞는 값만 pandas로 한꺼번에 +
로컬 오프셋 시 단위로 바꿨다. 여기서 행별 기준 구현을 두고 리포트·옛 alpha-fit 형식과 이상값
(빈 칸·글자·nan·inf·1_000·짧은/긴 행·분수 초·24시·한 자리 월·공백)을 대조한다.

    python tools/test_fit_table_fast.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np

import gui.result_viewer_io as rvio
from core.result_io import parse_row_time


def _ref_col_float(rows, j):
    out = np.full(len(rows), np.nan)
    if j is None:
        return out
    for k, r in enumerate(rows):
        if j < len(r):
            try:
                out[k] = float(r[j])
            except ValueError:
                pass
    return out


def _ref_col_time(rows, j, cut=True):
    ts = np.full(len(rows), np.nan)
    if j is None:
        return ts
    for k, r in enumerate(rows):
        if j < len(r):
            s = r[j].strip()
            if s and (cut or len(s) <= 26):
                d = parse_row_time(s)
                if d is not None:
                    ts[k] = d.timestamp()
    return ts


def _write(d, name, header, rows):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# test\n" + "\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    return p


def main():
    d = tempfile.mkdtemp()
    try:
        vals = ["1.5", "", "abc", "nan", "inf", "-inf", " 2.5 ", "1e-3", "1_000", "0x10", "+3",
                "−1", "1.000000000000000000001", "0.1", "-0", "5"]
        times = ["2026-05-01 00:00:00", "2026-05-01 00:00:20.5", "", "garbage", "2026-5-1 1:2:3",
                 "2026-05-01 24:00:00", "2026-05-01 00:00:00.1234567", "  2026-05-01 00:01:00  ",
                 "2026-03-08 02:30:00", "2026-11-01 01:30:00", "1999-12-31 23:59:59",
                 "2026-05-01T00:00:00", "2026-05-01 00:00"]
        H = ["File", "Channel", "Time", "RMS", "Chi2", "Status", "NO2", "NO2_Error", "Shift", "Squeeze"]
        rows = []
        for i in range(500):
            v, t = vals[i % len(vals)], times[i % len(times)]
            r = [f"s{i}", str(1 + i % 2), t, v, "1", "QC" if i % 7 == 0 else "", v, "0.2", v, "1.0"]
            if i % 11 == 0:
                r = r[:6]
            if i % 13 == 0:
                r = r + ["tail", "x"]
            rows.append(r)
        files = [_write(d, "report.dat", H, rows)]
        H2 = ["row_idx", "doy", "datetime", "T_C", "P_mbar", "NO2", "CHOCHO", "rms_cm-1"]
        rows2 = [[str(i), "121.0", times[i % len(times)], "25.0", vals[i % len(vals)], "5.0",
                  vals[(i + 3) % len(vals)], "1e-3"] for i in range(300)]
        files.append(_write(d, "alpha_fit.tsv", H2, rows2))
        big = os.path.join(tempfile.gettempdir(), "perf_big_30", "merged.dat")
        if os.path.exists(big):
            files.append(big)

        # 기준: 같은 load_fit_table을 행별 구현으로 갈아 끼워서 돌린다
        fast = (rvio._col_float, rvio._col_time, rvio._Grid)

        class _RowsGrid:
            def __init__(self, rows, width):
                self.rows = rows
        def ref_float(g, j):
            return _ref_col_float(g.rows, j)
        def ref_time(g, j, cut=True):
            return _ref_col_time(g.rows, j, cut)

        for fp in files:
            A = rvio._load_fit_table_uncached(fp)
            rvio._col_float, rvio._col_time, rvio._Grid = ref_float, ref_time, _RowsGrid
            try:
                B = rvio._load_fit_table_uncached(fp)
            finally:
                rvio._col_float, rvio._col_time, rvio._Grid = fast
            for k in A:
                a, b = A[k], B[k]
                if isinstance(a, dict):
                    assert a.keys() == b.keys(), k
                    for g in a:
                        assert (a[g] is None) == (b[g] is None), (k, g)
                        if a[g] is not None:
                            assert np.array_equal(a[g], b[g], equal_nan=True), (fp, k, g)
                elif isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
                    assert (a is None) == (b is None), (fp, k)
                    if a is not None:
                        assert np.array_equal(a, b, equal_nan=True), (fp, k)
                else:
                    assert a == b, (fp, k)
        # 캐시: 두 번째 읽기는 같은 값의 **복사본**(고쳐 써도 캐시 오염 없음), 파일이 바뀌면 다시 읽는다
        p0 = files[0]
        a1 = rvio.load_fit_table(p0)
        a1["gases"]["NO2"][:] = -999.0
        a1["status"][0] = "MUTATED"
        a2 = rvio.load_fit_table(p0)
        assert not np.any(a2["gases"]["NO2"] == -999.0) and a2["status"][0] != "MUTATED", "캐시 오염"
        import time as _time
        _time.sleep(0.02)
        with open(p0, "a", encoding="utf-8") as f:
            f.write("sX\t1\t2026-05-02 00:00:00\t1\t1\t\t9\t0.2\t9\t1.0\n")
        a3 = rvio.load_fit_table(p0)
        assert len(a3["row_idx"]) == len(a2["row_idx"]) + 1, "파일이 바뀌었는데 묵은 캐시를 돌려줌"
        print(f"test_fit_table_fast: {len(files)} file(s) identical to the per-row implementation"
              " · cache returns copies · reloads on change")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
