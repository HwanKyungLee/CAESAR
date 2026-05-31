"""Characterize col 6175 (the formerly-missing T sensor) on the days it works.

For 5/28 + 5/29 Hot data:
  - read row by row (stride 20)
  - record col 6155 (current "cavity T common", ÷100), col 6175 (÷100),
    col 6162 (P_PNs, ×0.6895), col 6164 (P_ANs, ×0.6895),
    col 6151 (ANs oven ÷100), col 6154 (PNs oven ÷100)
  - print time-aligned trend + simple correlations
"""
from __future__ import annotations
import os, glob
from datetime import datetime, timedelta
import numpy as np

DATA_DIR = r"D:\Yeosu_2026\CAESAR_Hot\2026-05"
ROW_STRIDE = 20
ROW_DT = 0.97

DATES = ("2026-05-28", "2026-05-29")

files = []
for d in DATES:
    files += sorted(glob.glob(os.path.join(DATA_DIR, f"{d}-*.dat")))
print(f"Found {len(files)} files for {DATES}\n")

records = []  # (ts, c6155, c6175, c6162, c6164, c6151, c6154)
for path in files:
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i % ROW_STRIDE != 0:
                continue
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            toks = s.split("\t") if "\t" in s else s.split()
            if len(toks) < 6180:
                continue
            try:
                c6155 = float(toks[6155]) / 100.0
                c6175 = float(toks[6175]) / 100.0
                c6162 = float(toks[6162]) * 0.6894733
                c6164 = float(toks[6164]) * 0.6894733
                c6151 = float(toks[6151]) / 100.0
                c6154 = float(toks[6154]) / 100.0
            except (ValueError, IndexError):
                continue
            ts = mtime + timedelta(seconds=i * ROW_DT)
            records.append((ts, c6155, c6175, c6162, c6164, c6151, c6154))

print(f"Got {len(records)} sample rows")
arr = np.array([r[1:] for r in records])
ts_arr = [r[0] for r in records]

cols = ["col6155 T_cav_common", "col6175 T_NEW",
        "col6162 P_PNs", "col6164 P_ANs",
        "col6151 T_ANs_oven", "col6154 T_PNs_oven"]
print("\nPer-column stats over 5/28-5/29:")
print(f"{'col':<25} {'n':>6} {'min':>10} {'max':>10} {'med':>10} {'std':>8}")
for i, name in enumerate(cols):
    v = arr[:, i]
    ok = np.isfinite(v) & (v > -1e6) & (v < 1e6) & (v != 0)
    if ok.sum() == 0:
        continue
    vo = v[ok]
    print(f"{name:<25} {ok.sum():>6} {vo.min():>10.2f} {vo.max():>10.2f} "
          f"{np.median(vo):>10.2f} {vo.std():>8.2f}")

# Show a few sample rows from start, middle, end
print("\nSample rows (first 5, middle 5, last 5):")
print(f"{'time':<20} {'c6155 T_cav':>11} {'c6175 NEW':>10} "
      f"{'c6162 P_PNs':>11} {'c6164 P_ANs':>11} "
      f"{'c6151 ANs_ov':>12} {'c6154 PNs_ov':>12}")
idxs = list(range(min(5, len(records)))) + \
       list(range(len(records)//2, min(len(records)//2+5, len(records)))) + \
       list(range(max(0, len(records)-5), len(records)))
for i in idxs:
    ts = ts_arr[i]
    c1,c2,c3,c4,c5,c6 = arr[i]
    print(f"{ts.strftime('%m-%d %H:%M:%S'):<20} {c1:>11.2f} {c2:>10.2f} "
          f"{c3:>11.2f} {c4:>11.2f} {c5:>12.2f} {c6:>12.2f}")

# Correlations of NEW col 6175 with everyone else
print("\nCorrelations of col 6175 (new) with others:")
v_new = arr[:, 1]
ok = np.isfinite(v_new) & (v_new > -1e6) & (v_new < 1e6) & (v_new != 0)
v_new_ok = v_new[ok]
for i, name in enumerate(cols):
    if i == 1:
        continue
    other = arr[:, i][ok]
    valid = np.isfinite(other) & (other != 0)
    if valid.sum() < 50:
        continue
    r = np.corrcoef(v_new_ok[valid], other[valid])[0,1]
    print(f"  col6175 vs {name:<25}  r = {r:+.3f}  n={valid.sum()}")
