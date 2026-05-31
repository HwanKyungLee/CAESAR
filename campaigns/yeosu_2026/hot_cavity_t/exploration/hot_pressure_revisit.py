"""Re-examine the P_PNs ↔ T_cavity relationship per user's suggestion.

User's intuition: pressure of the SAME cell whose T is missing should correlate
more strongly with its own T than the spectrometer T does. Our earlier finding
(P_PNs alone R²=0.54 vs T_spectro alone R²=0.975) may be misleading because:
  - All flags were mixed (ZA, He, sampling have different flow regimes)
  - Slow drift dominated the raw correlation

Strategy
--------
1. Use col 6180 as the target (alive from 5/22, covers more data than col 6175)
2. Restrict to sampling rows (flag=1) only -- consistent flow conditions
3. Compute both RAW and DETRENDED correlations:
   - Raw: instantaneous values
   - Detrended: subtract 1-hour rolling mean from each variable
4. Test multiple regression options
"""
from __future__ import annotations
import os, glob, time
from datetime import datetime, timedelta
import numpy as np

HOT_DIR = r"D:\Yeosu_2026\CAESAR_Hot\2026-05"
ROW_STRIDE = 5

C_TARGET_180 = 6180
C_TARGET_175 = 6175
C_P_PNS  = 6162
C_P_ANS  = 6164
C_T_SPT  = 6174
C_FLAG   = 4

DATES = [f"2026-05-{d:02d}" for d in range(22, 30)]  # 5/22 ~ 5/29

print(f"Scanning Hot files 5/22~5/29 (col 6180 working period)...")
files = []
for d in DATES:
    files += sorted(glob.glob(os.path.join(HOT_DIR, f"{d}-*.dat")))
print(f"  {len(files)} files\n")

rows = []
t0 = time.time()
for fi, path in enumerate(files, 1):
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i % ROW_STRIDE != 0:
                continue
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            toks = s.split("\t") if "\t" in s else s.split()
            if len(toks) < 6181:
                continue
            try:
                flag = int(float(toks[C_FLAG]))
                t180 = float(toks[C_TARGET_180])
                pp   = float(toks[C_P_PNS])
                pa   = float(toks[C_P_ANS])
                tsp  = float(toks[C_T_SPT])
            except (ValueError, IndexError):
                continue
            if t180 in (0, 65535) or pp in (0, 65535) or pa in (0, 65535) or tsp in (0, 65535):
                continue
            ts = mtime + timedelta(seconds=i * 0.97)
            rows.append((ts, flag, t180/100.0, pp*0.6894733, pa*0.6894733, tsp/100.0))
    if fi % 30 == 0 or fi == len(files):
        print(f"  [{fi}/{len(files)}]  elapsed={time.time()-t0:.1f}s  rows={len(rows)}")

ts_arr = np.array([r[0] for r in rows])
flag_arr = np.array([r[1] for r in rows])
t180_arr = np.array([r[2] for r in rows])
pp_arr   = np.array([r[3] for r in rows])
pa_arr   = np.array([r[4] for r in rows])
tsp_arr  = np.array([r[5] for r in rows])

print(f"\nTotal samples: {len(rows)}")
print(f"Per flag: 1(sampling)={np.sum(flag_arr==1)}, "
      f"500(ZA)={np.sum(flag_arr==500)}, 510(He)={np.sum(flag_arr==510)}, "
      f"502={np.sum(flag_arr==502)}, 512={np.sum(flag_arr==512)}")

# ----- 1. RAW correlations (all flags) -----
print("\n=== RAW correlations (all flags, n={}) ===".format(len(rows)))
def report(label, x, y):
    r = np.corrcoef(x, y)[0,1]
    print(f"  {label:<30}  r = {r:+.4f}")
report("col6180 vs P_PNs (col6162)", t180_arr, pp_arr)
report("col6180 vs P_ANs (col6164)", t180_arr, pa_arr)
report("col6180 vs T_spt (col6174)", t180_arr, tsp_arr)

# ----- 2. SAMPLING ONLY -----
m_samp = flag_arr == 1
print(f"\n=== Sampling rows only (n={m_samp.sum()}) ===")
report("col6180 vs P_PNs", t180_arr[m_samp], pp_arr[m_samp])
report("col6180 vs P_ANs", t180_arr[m_samp], pa_arr[m_samp])
report("col6180 vs T_spt", t180_arr[m_samp], tsp_arr[m_samp])

# ----- 3. DETRENDED (subtract rolling mean) ------
# Build a rolling 1-hour mean for each variable, subtract.
print("\n=== Detrended (subtract 1h rolling mean, sampling only) ===")
# Convert ts to seconds for rolling window
def detrend(times, vals, window_sec=3600):
    """Subtract centered rolling mean."""
    secs = np.array([(t - times[0]).total_seconds() for t in times])
    out = np.zeros_like(vals)
    j_lo = 0
    j_hi = 0
    for i in range(len(secs)):
        # Find window
        while j_lo < i and secs[j_lo] < secs[i] - window_sec/2:
            j_lo += 1
        while j_hi < len(secs) and secs[j_hi] < secs[i] + window_sec/2:
            j_hi += 1
        if j_hi - j_lo > 5:
            out[i] = vals[i] - vals[j_lo:j_hi].mean()
        else:
            out[i] = 0
    return out

ts_samp  = ts_arr[m_samp]
t180_s = t180_arr[m_samp]
pp_s   = pp_arr[m_samp]
pa_s   = pa_arr[m_samp]
tsp_s  = tsp_arr[m_samp]

# To avoid huge time complexity, subsample if too many
if len(ts_samp) > 5000:
    idx = np.linspace(0, len(ts_samp)-1, 5000).astype(int)
    ts_samp = ts_samp[idx]
    t180_s = t180_s[idx]; pp_s = pp_s[idx]; pa_s = pa_s[idx]; tsp_s = tsp_s[idx]

t180_d = detrend(ts_samp, t180_s)
pp_d   = detrend(ts_samp, pp_s)
pa_d   = detrend(ts_samp, pa_s)
tsp_d  = detrend(ts_samp, tsp_s)

report("col6180 vs P_PNs (detrended)", t180_d, pp_d)
report("col6180 vs P_ANs (detrended)", t180_d, pa_d)
report("col6180 vs T_spt (detrended)", t180_d, tsp_d)

# ----- 4. Linear regression: T = a*P_PNs + b (sampling only) ------
print("\n=== Regression: T_cav_left = a*P_PNs + b (sampling only) ===")
X = np.column_stack([pp_arr[m_samp], np.ones(m_samp.sum())])
y = t180_arr[m_samp]
coef, *_ = np.linalg.lstsq(X, y, rcond=None)
pred = X @ coef
resid = y - pred
ss_tot = ((y - y.mean())**2).sum()
r2 = 1 - (resid**2).sum() / ss_tot
print(f"  T = {coef[0]:+.5f} * P_PNs + {coef[1]:+.3f}")
print(f"  R² = {r2:.4f},  RMSE = {np.sqrt((resid**2).mean()):.3f} °C")

# Multiple predictors
print("\n=== Regression: T_cav_left = a*P_PNs + b*T_spt + c (sampling only) ===")
X = np.column_stack([pp_arr[m_samp], tsp_arr[m_samp], np.ones(m_samp.sum())])
coef, *_ = np.linalg.lstsq(X, y, rcond=None)
pred = X @ coef
r2 = 1 - ((y-pred)**2).sum() / ss_tot
print(f"  T = {coef[0]:+.5f}*P_PNs + {coef[1]:+.5f}*T_spt + {coef[2]:+.3f}")
print(f"  R² = {r2:.4f},  RMSE = {np.sqrt(((y-pred)**2).mean()):.3f} °C")

# T_spt only (sampling only)
print("\n=== Regression: T_cav_left = a*T_spt + b (sampling only) ===")
X = np.column_stack([tsp_arr[m_samp], np.ones(m_samp.sum())])
coef, *_ = np.linalg.lstsq(X, y, rcond=None)
pred = X @ coef
r2 = 1 - ((y-pred)**2).sum() / ss_tot
print(f"  T = {coef[0]:+.5f}*T_spt + {coef[1]:+.3f}")
print(f"  R² = {r2:.4f},  RMSE = {np.sqrt(((y-pred)**2).mean()):.3f} °C")

# Also check: col 6180 daily coverage to confirm always alive 5/22+
print("\n=== col 6180 daily coverage (rows with non-sentinel value) ===")
for d in DATES:
    m = np.array([t.strftime("%Y-%m-%d") == d for t in ts_arr])
    if m.sum() > 0:
        print(f"  {d}: {m.sum()} valid samples (median T={np.median(t180_arr[m]):.2f}°C)")
