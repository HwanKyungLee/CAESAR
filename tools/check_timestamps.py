"""Diagnostic: compare timestamp candidates for ONE raw .dat file.

Run this on the notebook (where the raw files live) against a real file:

    python tools/check_timestamps.py "D:\\Yeosu_2026\\CAESAR_Cold\\2026-05\\2026-05-21-009.dat"

It prints, for the first/middle/last data rows, the three candidate
timestamps so you can eyeball which one is sane:

  A) bytepack  = LABVIEW_EPOCH + (ref + (col0<<16|col1)/100) s   ← real encoded time
  B) mtime-anchored = mtime - (n_rows-1-row_idx)*0.97 s          ← current plot code
  C) filename  = date(filename, UTC) + col1 s  → KST             ← old (buggy) guess

Also prints col0/col1 raw values and the row-to-row delta of the bytepack
time, so you can see if 0.97 s/row is realistic and whether bytepack jumps.
"""
from __future__ import annotations
import os, sys
from datetime import datetime, timedelta, timezone

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from core.raw_parser import (
    RawParser, LABVIEW_EPOCH, LABVIEW_REF_SEC_2026,
    COL_TIME_LO, COL_TIME_HI, KST,
)

UTC = timezone.utc


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    path = sys.argv[1]
    base = os.path.basename(path)

    # read raw token rows (col0, col1) keeping row_idx
    rows = []  # (row_idx, col0, col1)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            toks = s.split("\t") if "\t" in s else s.split()
            if len(toks) <= COL_TIME_HI:
                continue
            try:
                c0 = int(float(toks[COL_TIME_LO]))
                c1 = int(float(toks[COL_TIME_HI]))
            except ValueError:
                continue
            rows.append((i, c0, c1))

    n = len(rows)
    parser = RawParser(path)
    mtime = parser.layout.mtime
    print(f"File   : {base}")
    print(f"Rows   : {n}")
    print(f"mtime  : {mtime}  (file close time, KST)")
    print(f"kind   : {parser.layout.kind}")
    print()

    # filename date
    import re
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", base)
    fdate = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC) if m else None

    def bytepack_ts(c0, c1):
        secs = ((c0 << 16) | c1) / 100.0
        return LABVIEW_EPOCH.replace(tzinfo=KST) + timedelta(seconds=LABVIEW_REF_SEC_2026 + secs)

    def mtime_ts(row_idx):
        return mtime - timedelta(seconds=(n - 1 - row_idx) * 0.97)

    def fname_ts(c1):
        if fdate is None:
            return None
        return (fdate + timedelta(seconds=c1)).astimezone(KST)

    picks = [0, n // 2, n - 1] if n > 2 else list(range(n))
    print(f"{'row':>6} {'col0':>7} {'col1':>7}  "
          f"{'A bytepack':>22} {'B mtime-anchor':>22} {'C filename':>22}")
    for idx in picks:
        ridx, c0, c1 = rows[idx]
        a = bytepack_ts(c0, c1)
        b = mtime_ts(ridx)
        c = fname_ts(c1)
        print(f"{ridx:>6} {c0:>7} {c1:>7}  "
              f"{a.strftime('%m-%d %H:%M:%S'):>22} "
              f"{b.strftime('%m-%d %H:%M:%S'):>22} "
              f"{(c.strftime('%m-%d %H:%M:%S') if c else '-'):>22}")

    # bytepack row-to-row deltas (median) → is 0.97 s/row right?
    if n > 1:
        deltas = []
        for k in range(1, min(n, 200)):
            t_prev = bytepack_ts(rows[k - 1][1], rows[k - 1][2])
            t_cur = bytepack_ts(rows[k][1], rows[k][2])
            deltas.append((t_cur - t_prev).total_seconds())
        deltas.sort()
        med = deltas[len(deltas) // 2]
        print(f"\nbytepack median row-to-row delta (first 200): {med:.3f} s/row")
        print(f"  (current plot assumes 0.97 s/row)")
        span_a = bytepack_ts(*rows[-1][1:]) - bytepack_ts(*rows[0][1:])
        print(f"  bytepack total span: {span_a}  ({n} rows)")
        print(f"  mtime-anchor span  : {timedelta(seconds=(n-1)*0.97)}")


if __name__ == "__main__":
    main()
