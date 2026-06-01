"""Check ALL 5/27 Hot files (24 files) for any column that comes online mid-day.

Also include col 6180 and check raw values more carefully.
For each file: sample ~50 rows, list median for every HK col 6149-6180 that's
not pure sentinel.
"""
from __future__ import annotations
import os, glob
from datetime import datetime, timedelta
import numpy as np

HOT_DIR = r"D:\Yeosu_2026\CAESAR_Hot\2026-05"
HK_COLS = list(range(6149, 6181))
ROW_STRIDE = 20
SAMPLE_ROWS_PER_FILE = 100
ROW_DT = 0.97

# Check ALL 27일 files + last few 5/26 + first few 5/28 for context
target_dates = ["2026-05-26", "2026-05-27", "2026-05-28"]
files = []
for d in target_dates:
    files += sorted(glob.glob(os.path.join(HOT_DIR, f"{d}-*.dat")))
print(f"Inspecting {len(files)} files\n")

# per (file, col) → median
results = []  # (file, mtime, ncols, col, med, n_sentinel, n_total)
for path in files:
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    base = os.path.basename(path)
    vals_by_col = {c: [] for c in HK_COLS}
    n_total = 0
    ncols = None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i % ROW_STRIDE != 0:
                continue
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            toks = s.split("\t") if "\t" in s else s.split()
            if ncols is None:
                ncols = len(toks)
            if len(toks) < max(HK_COLS) + 1:
                continue
            for c in HK_COLS:
                try:
                    vals_by_col[c].append(float(toks[c]))
                except ValueError:
                    pass
            n_total += 1
            if n_total >= SAMPLE_ROWS_PER_FILE:
                break
    for c in HK_COLS:
        arr = np.asarray(vals_by_col[c])
        if arr.size == 0:
            continue
        ok = (arr != 0) & (arr != 65535)
        n_sent = int(np.sum(~ok))
        if ok.sum() == 0:
            results.append((base, mtime, ncols, c, np.nan, n_sent, len(arr)))
        else:
            results.append((base, mtime, ncols, c, float(np.median(arr[ok])),
                            n_sent, len(arr)))

# Now print a matrix: per-file (rows) × cols 6149-6180 (cols)
files_unique = sorted(set(r[0] for r in results))
cols_unique  = sorted(set(r[3] for r in results))

# Find which columns transition mid-period
print("="*150)
print("Per-file MEDIAN for each HK col (only showing cols with any non-sentinel)")
print("="*150)

# Filter cols that have any real value across our window
cols_active = []
for c in cols_unique:
    has_real = any(not np.isnan(r[4]) for r in results if r[3] == c)
    if has_real:
        cols_active.append(c)

header = f"{'file':<22} {'mtime':<17} " + "".join(f"{c:>7}" for c in cols_active)
print(header)
for f in files_unique:
    row = {r[3]: r for r in results if r[0] == f}
    mt = list(row.values())[0][1]
    line = f"{f:<22} {mt.strftime('%m-%d %H:%M:%S'):<17} "
    for c in cols_active:
        if c not in row or np.isnan(row[c][4]):
            line += f"{'   -':>7}"
        else:
            line += f"{row[c][4]:>7.0f}"
    print(line)

# Highlight: per col, find first file with non-sentinel data
print("\n" + "="*70)
print("ONSET file per column (first file where median is non-NaN)")
print("="*70)
for c in cols_unique:
    onsets = [(r[0], r[1]) for r in results if r[3] == c and not np.isnan(r[4])]
    if not onsets:
        continue
    onsets.sort(key=lambda x: x[1])
    first = onsets[0]
    last = onsets[-1]
    print(f"col {c}: first={first[0]} ({first[1].strftime('%m-%d %H:%M')}) "
          f"last={last[0]} ({last[1].strftime('%m-%d %H:%M')})  total_files={len(onsets)}")
