"""Rebuild unified T_left_cavity CSV with col 6175 as the measured source.

Difference from previous version:
  - T_final = col 6175 (when available, 5/27 10:56 onwards) else GBR prediction
  - GBR was trained on col 6180. We apply a small bias correction (+0.1°C) so
    predictions land on the col 6175 scale. (col 6175 - col 6180 mean = +0.10°C
    in overlap period.)
  - col 6180 is kept in the CSV as an auxiliary cross-check column.

Output: temp_predict/output/hot_T_left_cavity_unified_c6175.csv (+ png)
"""
from __future__ import annotations
import os, glob, time, pickle
from datetime import datetime, timedelta
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager
for cand in ("Malgun Gothic", "NanumGothic", "Gulim"):
    try:
        font_manager.findfont(cand, fallback_to_default=False)
        plt.rcParams["font.family"] = cand
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

_HERE = os.path.dirname(os.path.abspath(__file__))
HOT_DIR = os.environ.get(
    "CAESAR_HOT_DIR",
    r"C:\Doasis_Work\raw,alpha_by_nam\CAESAR_Hot\2026-05",
)
OUT_DIR = os.environ.get(
    "CAESAR_TPRED_OUT",
    os.path.normpath(os.path.join(_HERE, "..", "model")),
)
os.makedirs(OUT_DIR, exist_ok=True)
MODEL_PKL = os.path.join(OUT_DIR, "hot_t_best_model.pkl")
ROW_STRIDE = 1

FEAT_COLS = [6149, 6153, 6162, 6164, 6174]
SCALE = {
    6149: lambda x: x/100.0,
    6153: lambda x: x/100.0,
    6162: lambda x: x*0.6894733,
    6164: lambda x: x*0.6894733,
    6174: lambda x: x/100.0,
    6180: lambda x: x/100.0,
    6175: lambda x: x/100.0,
}
TARGET_MEAS = 6175   # the column the supervisor knows about (broken until 5/27)
AUX = 6180           # the auxiliary column (came online 5/22, used for training)
BIAS_CORR = +0.10    # col 6175 - col 6180 average bias in overlap

print("Loading saved GBR model (trained on col 6180)...")
with open(MODEL_PKL, "rb") as f:
    state = pickle.load(f)
gbr = state["gbr"]
print(f"  Features: {state['feat_keys']}")

files = sorted(glob.glob(os.path.join(HOT_DIR, "*.dat")))
print(f"\nScanning {len(files)} Hot files (stride={ROW_STRIDE})...")

rows = []  # (ts, t_spt, feats, t_meas_6175, t_aux_6180, base, i)
t0 = time.time()
for fi, path in enumerate(files, 1):
    base = os.path.basename(path)
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i % ROW_STRIDE != 0:
                continue
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            toks = s.split("\t") if "\t" in s else s.split()
            if len(toks) <= max(TARGET_MEAS, AUX):
                continue
            try:
                feats = []
                bad = False
                for c in FEAT_COLS:
                    v = float(toks[c])
                    if v in (0, 65535):
                        bad = True
                        break
                    feats.append(SCALE[c](v))
                if bad:
                    continue
                v6175 = float(toks[TARGET_MEAS])
                t_meas = SCALE[TARGET_MEAS](v6175) if v6175 not in (0, 65535) else float("nan")
                v6180 = float(toks[AUX])
                t_aux  = SCALE[AUX](v6180) if v6180 not in (0, 65535) else float("nan")
            except (ValueError, IndexError):
                continue
            t_spt = feats[FEAT_COLS.index(6174)]
            ts = mtime + timedelta(seconds=i*0.97)
            rows.append((ts, t_spt, feats, t_meas, t_aux, base, i))
    if fi % 30 == 0 or fi == len(files):
        print(f"  [{fi}/{len(files)}]  rows={len(rows)}  elapsed={time.time()-t0:.1f}s")

print(f"\nTotal rows: {len(rows)}")

X = np.array([r[2] for r in rows])
print("Predicting with GBR (then applying +0.1°C bias to match col 6175 scale)...")
t1 = time.time()
preds_raw = gbr.predict(X)
preds = preds_raw + BIAS_CORR
print(f"  predict: {time.time()-t1:.1f}s")

t_meas_arr = np.array([r[3] for r in rows])   # col 6175 (target)
t_aux_arr  = np.array([r[4] for r in rows])   # col 6180 (auxiliary)
has_meas = ~np.isnan(t_meas_arr)
T_final = np.where(has_meas, t_meas_arr, preds)

# Save CSV
csv_path = os.path.join(OUT_DIR, "hot_T_left_cavity_unified_c6175.csv")
with open(csv_path, "w", encoding="utf-8") as f:
    f.write("# Hot left-cavity T unified series — col 6175 as measured source\n")
    f.write("# Model: sklearn GradientBoostingRegressor (n_est=200, max_depth=5, lr=0.05)\n")
    f.write(f"# Trained on col 6180 over 5/22~5/29 (Test R^2=0.981, RMSE=0.244 C).\n")
    f.write(f"# Predictions bias-corrected by {BIAS_CORR:+.2f} C to align with col 6175 scale\n")
    f.write("# (col 6175 - col 6180 mean = +0.10 C, std = 0.86 C in overlap).\n")
    f.write("# T_final = col 6175 (when available, 5/27 10:56 KST onwards) else GBR_predicted + bias\n")
    f.write("# T_aux_c6180 kept as cross-check (independent sensor that came online 5/22).\n")
    f.write("ts,T_spt_C,T_predicted_C,T_measured_c6175_C,T_aux_c6180_C,T_final_C,source,file,row_idx\n")
    for i, r in enumerate(rows):
        ts, tspt, _, tmeas, taux, fname, ridx = r
        src = "measured" if has_meas[i] else "predicted"
        tmeas_str = "" if np.isnan(tmeas) else f"{tmeas:.3f}"
        taux_str  = "" if np.isnan(taux)  else f"{taux:.3f}"
        f.write(f"{ts.isoformat(timespec='seconds')},{tspt:.3f},{preds[i]:.3f},"
                f"{tmeas_str},{taux_str},{T_final[i]:.3f},{src},{fname},{ridx}\n")
print(f"\nWrote CSV -> {csv_path}")
print(f"  Total rows: {len(rows)}")
print(f"  Measured (col 6175, 5/27 10:56 ~): {has_meas.sum()} ({100*has_meas.mean():.1f}%)")
print(f"  Predicted (GBR, 5/18 ~ 5/27 10:56): {(~has_meas).sum()} ({100*(~has_meas).mean():.1f}%)")

# Per-day summary
ts_arr = np.array([r[0] for r in rows])
print("\n=== Per-day T_left_cav summary ===")
print(f"{'date':<12} {'n':>7} {'source':<14} {'med':>7} {'p10':>7} {'p90':>7}")
days = sorted(set(t.date() for t in ts_arr))
for d in days:
    m = np.array([t.date() == d for t in ts_arr])
    tf = T_final[m]
    if has_meas[m].all():    src = "measured"
    elif (~has_meas[m]).all(): src = "predicted"
    else:                      src = "mixed"
    print(f"{d.strftime('%Y-%m-%d'):<12} {m.sum():>7} {src:<14} "
          f"{np.median(tf):>7.2f} {np.percentile(tf,10):>7.2f} {np.percentile(tf,90):>7.2f}")

# Plot
fig, ax = plt.subplots(figsize=(15, 6))
m_pred = ~has_meas
m_meas = has_meas
ax.plot(ts_arr[m_pred], T_final[m_pred], "b.", ms=2, alpha=0.5,
        label=f"역추정 (5/18~5/27 오전, GBR n={m_pred.sum()})")
ax.plot(ts_arr[m_meas], T_final[m_meas], "r.", ms=2, alpha=0.4,
        label=f"실측 col 6175 (5/27 10:56~, n={m_meas.sum()})")

# Overlay col 6180 (aux) for visual cross-check
has_aux = ~np.isnan(t_aux_arr)
ax.plot(ts_arr[has_aux & m_pred], t_aux_arr[has_aux & m_pred],
        "g.", ms=1, alpha=0.3, label=f"참고: col 6180 (5/22 onset, 별도 센서)")

recovery = datetime(2026, 5, 27, 10, 56)
ax.axvline(recovery, color="darkgreen", lw=1.2, ls="--", alpha=0.7,
           label="5/27 10:56 — col 6175 onset (수리 시점)")

ax.set_title("Hot 좌측 캐비티 T (col 6175 기준)  "
             "[5/18~5/27 GBR 역추정 + bias correction, 5/27 10:56~ 실측]")
ax.set_xlabel("시간 (KST)")
ax.set_ylabel("좌측 캐비티 T (°C)")
ax.legend(loc="best")
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(mdates.DayLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
fig.autofmt_xdate()
png = os.path.join(OUT_DIR, "hot_T_left_cavity_unified_c6175.png")
fig.savefig(png, dpi=140, bbox_inches="tight")
print(f"\nPlot -> {png}")
