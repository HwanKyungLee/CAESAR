"""리트리벌 결과 자르기/합치기 CLI — 로직은 core/result_io.py 공용(GUI 결과뷰어와 동일).

사용 예:
  # 1) 한 파일에서 기간만 추출
  python tools/result_slice.py 결과.dat --from "2026-05-20 06:00" --to "2026-05-22 18:00"

  # 2) 여러 파일 병합(시간순 정렬) 후 기간 추출
  python tools/result_slice.py 5월결과.dat 6월결과.dat --from "2026-05-30" --to "2026-06-03" --out 머지본.dat

  # 3) 기간 없이 병합만
  python tools/result_slice.py a.dat b.dat --out merged.dat
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.result_io import (auto_out_name, merge_results, parse_when,  # noqa: E402
                            slice_rows, write_result)


def main():
    p = argparse.ArgumentParser(description='slice/merge retrieval results')
    p.add_argument('inputs', nargs='+', help='one or more result files (.dat/.tsv)')
    p.add_argument('--from', dest='t0', default=None, help="start 'YYYY-MM-DD[ HH:MM[:SS]]'")
    p.add_argument('--to', dest='t1', default=None, help="end (date only = until 23:59:59 that day)")
    p.add_argument('--out', default=None, help='output path (default: auto name)')
    a = p.parse_args()

    try:
        t0 = parse_when(a.t0)
        t1 = parse_when(a.t1, end=True)
        comments, colhdr, rows, ndup = merge_results(a.inputs)
        n_in = len(rows)
        rows = slice_rows(rows, t0, t1)
        if not rows:
            raise SystemExit('No data in the selected range.')
        out = a.out or auto_out_name(a.inputs[0], rows)
        write_result(out, comments, colhdr, rows,
                     note=f'merged {len(a.inputs)} files, {ndup} dups removed, {n_in}→{len(rows)} rows')
    except ValueError as e:
        raise SystemExit(str(e))
    print(f'Done: {out}')
    print(f'  {len(rows)} rows ({rows[0][0]:%m-%d %H:%M} ~ {rows[-1][0]:%m-%d %H:%M})')


if __name__ == '__main__':
    main()
