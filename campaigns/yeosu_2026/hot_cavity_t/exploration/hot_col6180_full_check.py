"""Verify col 6180 is alive across ALL days 5/18 ~ 5/29.
Also compare col 6180 vs col 6175 during the overlap period (5/27 10:56 ~ 5/29).
"""
from __future__ import annotations
import os, glob
from datetime import datetime, timedelta
import numpy as np

HOT_DIR = r"D:\Yeosu_2026\CAESAR_Hot\2026-05"

# Check first file of every day, full row scan
files = []
for d in range(18, 30):
    pat = sorted(glob.glob(os.path.join(HOT_DIR, f"2026-05-{d:02d}-*.dat")))
    if pat:
        files.append(pat[0])
        files.append(pat[-1])

per_file = []
for path in files:
    base = os.path.basename(path)
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    c6175_vals = []
    c6180_vals = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i > 200:
                break
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            toks = s.split("\t") if "\t" in s else s.split()
            if len(toks) < 6181:
                continue
            try:
                v75 = float(toks[6175])
                v80 = float(toks[6180])
            except ValueError:
                continue
            if v75 not in (0, 65535):
                c6175_vals.append(v75/100.0)
            if v80 not in (0, 65535):
                c6180_vals.append(v80/100.0)
    med_75 = np.median(c6175_vals) if c6175_vals else float("nan")
    med_80 = np.median(c6180_vals) if c6180_vals else float("nan")
    per_file.append((base, mtime, len(c6175_vals), med_75, len(c6180_vals), med_80))

print(f"{'file':<22} {'mtime':<17} {'n6175':>6} {'med6175':>8} {'n6180':>6} {'med6180':>8}")
for r in per_file:
    base, mt, n75, m75, n80, m80 = r
    s75 = f"{m75:.2f}" if not np.isnan(m75) else "SENT"
    s80 = f"{m80:.2f}" if not np.isnan(m80) else "SENT"
    print(f"{base:<22} {mt.strftime('%m-%d %H:%M:%S'):<17} {n75:>6} {s75:>8} {n80:>6} {s80:>8}")

# Now correlation 6180 vs 6175 in overlap period (5/27-010 onwards)
print("\n=== 5/28 ~ 5/29 overlap: col 6180 vs col 6175 correlation ===")
overlap_files = []
for d in ("2026-05-28", "2026-05-29"):
    overlap_files += sorted(glob.glob(os.path.join(HOT_DIR, f"{d}-*.dat")))

pairs = []
for path in overlap_files[:20]:  # sample 20 files enough
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i % 20 != 0:
                continue
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            toks = s.split("\t") if "\t" in s else s.split()
            if len(toks) < 6181:
                continue
            try:
                v75 = float(toks[6175]) / 100.0
                v80 = float(toks[6180]) / 100.0
            except ValueError:
                continue
            if 5 < v75 < 60 and 5 < v80 < 60:
                pairs.append((v75, v80))

if pairs:
    arr = np.array(pairs)
    r = np.corrcoef(arr[:,0], arr[:,1])[0,1]
    diff = arr[:,0] - arr[:,1]
    print(f"  n={len(pairs)}, correlation r = {r:+.4f}")
    print(f"  col 6175 median: {np.median(arr[:,0]):.2f} °C")
    print(f"  col 6180 median: {np.median(arr[:,1]):.2f} °C")
    print(f"  6175 - 6180  bias = {diff.mean():+.3f} ± {diff.std():.3f} °C")
