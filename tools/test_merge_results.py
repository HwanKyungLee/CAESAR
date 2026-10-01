# -*- coding: utf-8 -*-
"""tools/test_merge_results.py — core.result_io.merge_results가 예전(제곱 시간) 구현과 같은 결과인가.

2026-10-01: 파일을 더할 때마다 쌓인 행을 전부 다시 맞추던 구현을 '열 목록 먼저 → 행마다 한 번'으로
바꿨다(30일 26만 행 39 s). 여기서 예전 구현을 기준으로 두고 같은 열 구성·새 열·열 순서 바뀜·
중복 열 이름·짧은/긴 행·시간 겹침(dedup)을 대조한다.

    python tools/test_merge_results.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.result_io import merge_results, read_result


def reference(files, dedup=True):
    """2026-10-01 이전 구현 그대로(기준)."""
    comments, colhdr, rows = read_result(files[0])
    columns = colhdr.split('\t')
    for fp in files[1:]:
        _, ch2, r2 = read_result(fp)
        other = ch2.split('\t')
        for c in other:
            if c not in columns:
                columns.append(c)

        def align(line, src):
            vals = line.split('\t')
            by_name = dict(zip(src, vals))
            return '\t'.join(by_name.get(c, '') for c in columns)
        rows = [(t, align(line, columns[:len(colhdr.split('\t'))])) for t, line in rows]
        rows += [(t, align(line, other)) for t, line in r2]
        colhdr = '\t'.join(columns)
    if colhdr != '\t'.join(columns):
        colhdr = '\t'.join(columns)
    if rows:
        rows = [(t, line if len(line.split('\t')) == len(columns)
                 else '\t'.join(line.split('\t') + [''] * (len(columns) - len(line.split('\t')))))
                for t, line in rows]
    n_dup = 0
    if dedup:
        cols = columns
        ci = cols.index('Channel') if 'Channel' in cols else None
        seen = {}
        for i, (t, line) in enumerate(rows):
            ch = line.split('\t')[ci] if (ci is not None and ci < len(line.split('\t'))) else ''
            seen[(t, ch)] = i
        keep_idx = set(seen.values())
        n_dup = len(rows) - len(keep_idx)
        rows = [r for i, r in enumerate(rows) if i in keep_idx]
    rows.sort(key=lambda x: x[0])
    return comments, colhdr, rows, n_dup


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
        H = ["File", "Channel", "Time", "RMS", "NO2"]
        def rows(day, n, extra=0, short=False, long_=False):
            out = []
            for i in range(n):
                r = [f"s{i}", str(1 + i % 2), f"2026-05-{day:02d} 00:{i // 60:02d}:{i % 60:02d}",
                     f"{i * 1e-4:.4g}", f"{5 + i * 0.01:.3f}"] + [f"x{i}"] * extra
                if short and i % 5 == 0:
                    r = r[:3]
                if long_ and i % 7 == 0:
                    r = r + ["tail"]
                out.append(r)
            return out
        a = _write(d, "a.dat", H, rows(1, 120, short=True))
        b = _write(d, "b.dat", H, rows(2, 120, long_=True))
        c = _write(d, "c.dat", H + ["CHOCHO"], rows(3, 120, extra=1))            # 새 열
        e = _write(d, "e.dat", ["Time", "Channel", "NO2", "File", "RMS"],          # 열 순서 바뀜
                   [[r[2], r[1], r[4], r[0], r[3]] for r in rows(4, 60)])
        f_ = _write(d, "f.dat", H, rows(1, 80))                                     # a와 시간 겹침
        g = _write(d, "g.dat", H + ["NO2"], rows(5, 50, extra=1))                   # 중복 열 이름
        h = _write(d, "h.dat", ["Time", "NO2"], [[f"2026-05-06 00:00:{i:02d}", "1"] for i in range(30)])
        cases = [[a], [a, b], [a, b, c], [c, a], [a, e], [a, f_], [a, b, c, e, f_],
                 [g, a], [a, g], [a, h], [h, a, c], [b, b]]
        for files in cases:
            for dedup in (True, False):
                got, want = merge_results(files, dedup=dedup), reference(files, dedup=dedup)
                names = [os.path.basename(x) for x in files]
                assert got == want, f"mismatch for {names} dedup={dedup}"
        print(f"test_merge_results: {len(cases) * 2} cases identical to the old implementation")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
