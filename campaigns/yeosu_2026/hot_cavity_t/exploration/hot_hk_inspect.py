"""Find live HK columns in Hot data and identify which T column came online at 27일.

Strategy:
  Scan one file from each day 5/18 ~ 5/29 (early row).
  For each HK candidate column (6149..6180), record min/max/median per day.
  Print a per-column per-day matrix so we can spot which column was sentinel
  (0 or 65535 or constant) before 27일 and "alive" after.
"""
from __future__ import annotations
import os, glob
from datetime import datetime
import numpy as np

DATA_DIR = r"D:\Yeosu_2026\CAESAR_Hot\2026-05"
HK_COLS  = list(range(6149, 6180))
SAMPLE_ROWS_PER_FILE = 200  # first N data rows
ROW_STRIDE = 5

# Pick one file per day (first file of each date)
dates = []
for d in range(18, 30):  # 5/18 ~ 5/29
    pat = os.path.join(DATA_DIR, f"2026-05-{d:02d}-001.dat")
    if os.path.exists(pat):
        dates.append((f"2026-05-{d:02d}", pat))

print(f"Sampling {len(dates)} files (1st of each day)\n")

# matrix[col][day] = (min, max, median, n_sentinel)
per_col_day = {}  # (col, day) -> dict
for day, path in dates:
    print(f"  Reading {os.path.basename(path)} ...")
    vals_by_col = {c: [] for c in HK_COLS}
    n = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i % ROW_STRIDE != 0:
                continue
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            toks = s.split("\t") if "\t" in s else s.split()
            if len(toks) < max(HK_COLS) + 1:
                continue
            for c in HK_COLS:
                try:
                    vals_by_col[c].append(float(toks[c]))
                except ValueError:
                    pass
            n += 1
            if n >= SAMPLE_ROWS_PER_FILE:
                break
    for c in HK_COLS:
        arr = np.asarray(vals_by_col[c])
        if arr.size == 0:
            per_col_day[(c, day)] = (np.nan, np.nan, np.nan, 0, 0)
        else:
            n_zero = int(np.sum(arr == 0))
            n_max  = int(np.sum(arr == 65535))
            ok = arr[(arr != 0) & (arr != 65535)]
            if ok.size > 0:
                per_col_day[(c, day)] = (float(ok.min()), float(ok.max()),
                                         float(np.median(ok)), n_zero, n_max)
            else:
                per_col_day[(c, day)] = (np.nan, np.nan, np.nan, n_zero, n_max)

# Print transposed table: rows=col, columns=day
print("\n" + "="*120)
print("HK col MEDIAN per day (skipping 0/65535 sentinels)")
print("="*120)
day_labels = [d for d,_ in dates]
header = f"{'col':>6}  " + "  ".join(f"{d[5:]:>6}" for d in day_labels)
print(header)
for c in HK_COLS:
    row = f"{c:>6}  "
    for d in day_labels:
        med = per_col_day[(c, d)][2]
        if np.isnan(med):
            row += f"  {'SENT':>5} "
        else:
            row += f"  {med:>6.0f}"
    print(row)

# Now flag cols where pre-27일 = sentinel and 27일+ = real values
print("\n" + "="*120)
print("CANDIDATE for broken-then-recovered:  sentinel/NaN before 5/27, real values from 5/27")
print("="*120)
for c in HK_COLS:
    pre  = [per_col_day[(c,d)][2] for d in day_labels if d < "2026-05-27"]
    post = [per_col_day[(c,d)][2] for d in day_labels if d >= "2026-05-27"]
    pre_all_nan  = all(np.isnan(x) for x in pre) if pre else False
    post_any_ok  = any(not np.isnan(x) for x in post) if post else False
    if pre_all_nan and post_any_ok:
        post_med = np.nanmedian(post)
        print(f"  col {c}: ALL SENTINEL before 5/27, real after (post median = {post_med:.0f})")
    elif post_any_ok and pre and not all(np.isnan(x) for x in pre):
        # Partial pattern
        n_pre_nan = sum(1 for x in pre if np.isnan(x))
        if n_pre_nan >= len(pre) * 0.7:  # mostly sentinel
            post_med = np.nanmedian(post)
            print(f"  col {c}: mostly sentinel before 5/27 ({n_pre_nan}/{len(pre)}), real after (post med = {post_med:.0f})")
