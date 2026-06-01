"""Apply best GradientBoosting model to back-cast Hot left cavity T for
the entire 5/18 ~ 5/29 period.

For each row:
  - Read features (c6149, c6153, P_PNs, P_ANs, T_spt)
  - GBR.predict → T_predicted
  - Read col 6175 raw; if non-sentinel, T_measured = col 6175 / 100
  - Unified output column: T_final = T_measured if available else T_predicted
  (Model trained directly on col 6175, 5/27~5/29 — no bias correction needed)
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
# Default: keep outputs (CSV + plot) alongside the trained model under
# campaigns/yeosu_2026/hot_cavity_t/model/.
OUT_DIR = os.environ.get(
    "CAESAR_TPRED_OUT",
    os.path.normpath(os.path.join(_HERE, "..", "model")),
)
os.makedirs(OUT_DIR, exist_ok=True)
ROW_STRIDE = 1

# Feature columns (must match training)
FEAT_COLS = [6149, 6153, 6162, 6164, 6174]
SCALE = {
    6149: lambda x: x/100.0,
    6153: lambda x: x/100.0,
    6162: lambda x: x*0.6894733,
    6164: lambda x: x*0.6894733,
    6174: lambda x: x/100.0,
    6175: lambda x: x/100.0,
}
TARGET = 6175

print("Loading saved model...")
with open(os.path.join(OUT_DIR, "hot_t_best_model.pkl"), "rb") as f:
    state = pickle.load(f)
gbr = state["gbr"]
print(f"  Features: {state['feat_keys']}")

# Scan ALL files 5/18 ~ 5/29
files = sorted(glob.glob(os.path.join(HOT_DIR, "*.dat")))
print(f"\nScanning {len(files)} Hot files...")

rows_out = []  # (ts, T_spt, feats, T_measured_6175 (or nan), file, row)
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
            if len(toks) <= TARGET:
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
                v_target = float(toks[TARGET])
                t_meas = SCALE[TARGET](v_target) if v_target not in (0, 65535) else float("nan")
            except (ValueError, IndexError):
                continue
            t_spt = feats[FEAT_COLS.index(6174)]
            ts = mtime + timedelta(seconds=i*0.97)
            rows_out.append((ts, t_spt, feats, t_meas, base, i))
    if fi % 30 == 0 or fi == len(files):
        print(f"  [{fi}/{len(files)}]  rows={len(rows_out)}  elapsed={time.time()-t0:.1f}s")

print(f"\nTotal rows: {len(rows_out)}")

# Vectorized prediction
X = np.array([r[2] for r in rows_out])
print("Predicting with GBR...")
t1 = time.time()
preds = gbr.predict(X)
print(f"  predict: {time.time()-t1:.1f}s for {len(X)} rows")

# Build unified column: measured (col 6175) if available, else predicted
t_meas_arr = np.array([r[3] for r in rows_out])
has_meas = ~np.isnan(t_meas_arr)
T_final = np.where(has_meas, t_meas_arr, preds)

# Save CSV
csv_path = os.path.join(OUT_DIR, "hot_T_left_cavity_unified.csv")
with open(csv_path, "w", encoding="utf-8") as f:
    f.write("# Hot left-cavity T unified series (Yeosu 2026 campaign)\n")
    f.write("# Model: sklearn GradientBoostingRegressor (n_est=200, max_depth=5, lr=0.05)\n")
    f.write("# Features: c6149/100, c6153/100, P_PNs(=c6162*0.6895), P_ANs(=c6164*0.6895), T_spt(=c6174/100)\n")
    f.write("# Trained on 5/27~5/29 (col 6175 alive period). No bias correction needed.\n")
    f.write("# T_final = T_measured (col 6175/100) if available else T_predicted (GBR)\n")
    f.write("ts,T_spt_C,T_predicted_C,T_measured_c6175_C,T_final_C,source,file,row_idx\n")
    for i, r in enumerate(rows_out):
        ts, tspt, _, tmeas, fname, ridx = r
        src = "measured" if has_meas[i] else "predicted"
        tmeas_str = "" if np.isnan(tmeas) else f"{tmeas:.3f}"
        f.write(f"{ts.isoformat(timespec='seconds')},{tspt:.3f},{preds[i]:.3f},"
                f"{tmeas_str},{T_final[i]:.3f},{src},{fname},{ridx}\n")
print(f"\nUnified CSV -> {csv_path}")
print(f"  Total rows: {len(rows_out)}")
print(f"  Measured rows (col 6175, 5/27 10:56~): {has_meas.sum()}  ({100*has_meas.mean():.1f}%)")
print(f"  Predicted rows (5/18~5/27 10:56): {(~has_meas).sum()}")

# Per-day summary
ts_arr = np.array([r[0] for r in rows_out])
print("\n=== Per-day T_left_cav summary ===")
print(f"{'date':<12} {'n':>7} {'src':<10} {'med':>7} {'p10':>7} {'p90':>7}")
days = sorted(set(t.date() for t in ts_arr))
for d in days:
    m = np.array([t.date() == d for t in ts_arr])
    tf = T_final[m]
    src = "measured" if has_meas[m].all() else ("predicted" if (~has_meas[m]).all() else "mixed")
    print(f"{d.strftime('%Y-%m-%d'):<12} {m.sum():>7} {src:<10} "
          f"{np.median(tf):>7.2f} {np.percentile(tf,10):>7.2f} {np.percentile(tf,90):>7.2f}")

# Plot
fig, ax = plt.subplots(figsize=(15, 6))
m_pred = ~has_meas
m_meas = has_meas
ax.plot(ts_arr[m_pred], T_final[m_pred], "b.", ms=2, alpha=0.5,
        label=f"역추정 (5/18~5/27 오전, GBR n={m_pred.sum()})")
ax.plot(ts_arr[m_meas], T_final[m_meas], "r.", ms=2, alpha=0.4,
        label=f"실측 col 6175 (5/27 10:56~, n={m_meas.sum()})")

recovery = datetime(2026, 5, 27, 10, 56)
ax.axvline(recovery, color="darkgreen", lw=1.2, ls="--", alpha=0.7,
           label="5/27 10:56 — col 6175 onset (수리 시점)")

ax.set_title("Hot 좌측 캐비티 T 통합 시계열 (역추정 + 실측)  "
             "[GBR trained on col 6175, 5/27~5/29]")
ax.set_xlabel("시간 (KST)")
ax.set_ylabel("좌측 캐비티 T (°C)")
ax.legend(loc="best")
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(mdates.DayLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
fig.autofmt_xdate()
png = os.path.join(OUT_DIR, "hot_T_left_cavity_unified.png")
fig.savefig(png, dpi=140, bbox_inches="tight")
print(f"\nPlot -> {png}")
