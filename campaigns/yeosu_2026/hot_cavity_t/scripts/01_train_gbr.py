"""Maximize R^2 for T_cav_left prediction.

Try multiple feature sets + (optional) gradient boosting if available.
Output the BEST model and back-cast pre-5/27 with it.

Live & variable HK candidates (verified across 5/18~5/26 to ensure predictors
are available during the missing period):
  - col 6149 (raw, ÷100 ≈ 23-28)
  - col 6153 (raw, ÷100 ≈ 33-46)
  - col 6162  P_PNs   (×0.6895 = mbar)
  - col 6164  P_ANs   (×0.6895 = mbar)
  - col 6174  T_spt   (÷100 = °C)
Target: col 6175  T_cav_left (÷100 = °C)  [alive 5/27 10:56 KST+]
"""
from __future__ import annotations
import os, glob, time
from datetime import datetime, timedelta
import numpy as np

# ── Paths ────────────────────────────────────────────────────────────────
# HOT_DIR: where the Yeosu 2026 Hot Mega-Matrix .dat files live. Override
# with an explicit absolute path if your local layout differs.
# OUT_DIR: where the trained model (.pkl) lands. By default we write into
# ../model so the artefact stays alongside the script in the campaign tree.
import sys
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
ROW_STRIDE = 5

CANDIDATES = {
    "c6149": 6149,   # ÷100 raw temperature-like
    "c6153": 6153,   # ÷100 raw
    "P_PNs": 6162,
    "P_ANs": 6164,
    "T_spt": 6174,
}
TARGET = 6175

# Raw scalings (we'll apply when reading)
SCALE = {
    6149: ("÷100",  lambda x: x/100.0),
    6153: ("÷100",  lambda x: x/100.0),
    6162: ("×0.69", lambda x: x*0.6894733),
    6164: ("×0.69", lambda x: x*0.6894733),
    6174: ("÷100",  lambda x: x/100.0),
    6175: ("÷100",  lambda x: x/100.0),
}

# --- Train data: 5/27 ~ 5/29 (col 6175 alive period) ---
TRAIN_DATES = [f"2026-05-{d:02d}" for d in range(27, 30)]
train_files = []
for d in TRAIN_DATES:
    train_files += sorted(glob.glob(os.path.join(HOT_DIR, f"{d}-*.dat")))
print(f"Training scan: {len(train_files)} files")

t0 = time.time()
rows = []  # (ts, target, [features...])
for fi, path in enumerate(train_files, 1):
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
                tgt_raw = float(toks[TARGET])
                if tgt_raw in (0, 65535):
                    continue
                feats = {}
                ok = True
                for name, c in CANDIDATES.items():
                    v = float(toks[c])
                    if v in (0, 65535):
                        ok = False
                        break
                    feats[name] = SCALE[c][1](v)
                if not ok:
                    continue
                target = SCALE[TARGET][1](tgt_raw)
            except (ValueError, IndexError):
                continue
            ts = mtime + timedelta(seconds=i*0.97)
            rows.append((ts, target, *[feats[k] for k in CANDIDATES]))
    if fi % 30 == 0 or fi == len(train_files):
        print(f"  [{fi}/{len(train_files)}]  rows={len(rows)}  elapsed={time.time()-t0:.1f}s")

ts_arr = np.array([r[0] for r in rows])
y      = np.array([r[1] for r in rows])
feat_keys = list(CANDIDATES.keys())
X_base = np.array([r[2:] for r in rows])  # shape (n, 5)

print(f"\nTotal rows: {len(rows)}")
print(f"Base feature matrix: shape {X_base.shape}, keys = {feat_keys}")
print(f"Target T_cav_left: mean={y.mean():.3f}°C, std={y.std():.3f}, range=[{y.min():.2f}, {y.max():.2f}]")

# Helper
def eval_model(name, X, coef=None):
    if coef is None:
        Xa = np.column_stack([X, np.ones(len(X))])
        coef, *_ = np.linalg.lstsq(Xa, y, rcond=None)
        pred = Xa @ coef
    else:
        pred = X @ coef
    r2 = 1 - ((y-pred)**2).sum() / ((y-y.mean())**2).sum()
    rmse = float(np.sqrt(((y-pred)**2).mean()))
    print(f"  {name:<45}  R² = {r2:.5f}   RMSE = {rmse:.3f} °C")
    return coef, r2, rmse

print("\n=== Linear models (LSQ) ===")
results = []
results.append(("T_spt only",                eval_model("T_spt only",
    X_base[:, [feat_keys.index("T_spt")]])))
results.append(("P_PNs only",                eval_model("P_PNs only",
    X_base[:, [feat_keys.index("P_PNs")]])))
results.append(("T_spt + P_PNs",             eval_model("T_spt + P_PNs",
    X_base[:, [feat_keys.index("T_spt"), feat_keys.index("P_PNs")]])))
results.append(("All 5 features",            eval_model("All 5 features", X_base)))

# Polynomial: include squares + pairwise products
def expand_poly(X):
    n, d = X.shape
    cols = [X]
    for i in range(d):
        cols.append((X[:, i]**2).reshape(-1, 1))
    for i in range(d):
        for j in range(i+1, d):
            cols.append((X[:, i] * X[:, j]).reshape(-1, 1))
    return np.column_stack(cols)

X_poly = expand_poly(X_base)
print(f"\nPolynomial expansion: {X_base.shape[1]} → {X_poly.shape[1]} features")
results.append(("All 5 + squares + pairwise", eval_model("All 5 + squares + pairwise", X_poly)))

# Even higher order: cubics of T_spt
X_poly2 = np.column_stack([X_poly, (X_base[:, feat_keys.index("T_spt")]**3).reshape(-1,1)])
results.append(("Polynomial + T_spt cubic", eval_model("Poly + T_spt^3", X_poly2)))

# Add time-of-day cyclic features
hours_of_day = np.array([t.hour + t.minute/60.0 + t.second/3600.0 for t in ts_arr])
sin_h = np.sin(2*np.pi*hours_of_day/24)
cos_h = np.cos(2*np.pi*hours_of_day/24)
X_time = np.column_stack([X_poly, sin_h, cos_h])
results.append(("Poly + sin/cos(hour)", eval_model("Poly + sin/cos(hour)", X_time)))

# Try gradient boosting if sklearn available
try:
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.model_selection import train_test_split
    Xtr, Xte, ytr, yte = train_test_split(X_base, y, test_size=0.2, random_state=42)
    gbr = GradientBoostingRegressor(n_estimators=200, max_depth=5,
                                     learning_rate=0.05, random_state=42)
    gbr.fit(Xtr, ytr)
    pred_te = gbr.predict(Xte)
    r2_te = 1 - ((yte-pred_te)**2).sum() / ((yte-yte.mean())**2).sum()
    rmse_te = float(np.sqrt(((yte-pred_te)**2).mean()))
    pred_full = gbr.predict(X_base)
    r2_full = 1 - ((y-pred_full)**2).sum() / ((y-y.mean())**2).sum()
    rmse_full = float(np.sqrt(((y-pred_full)**2).mean()))
    print(f"\n=== GradientBoosting (sklearn) ===")
    print(f"  Test (20%)  : R² = {r2_te:.5f}  RMSE = {rmse_te:.3f}°C")
    print(f"  Full train  : R² = {r2_full:.5f}  RMSE = {rmse_full:.3f}°C")
    # Feature importances
    print(f"  Feature importances:")
    for name, imp in zip(feat_keys, gbr.feature_importances_):
        print(f"    {name:<8}  {imp:.4f}")
    results.append(("GradientBoosting", (None, r2_full, rmse_full)))
    HAS_SKLEARN = True
    BEST_GBR = gbr
except ImportError as exc:
    print(f"\nsklearn not available ({exc}), skipping GB")
    HAS_SKLEARN = False
    BEST_GBR = None

# Pick the best linear+poly model
print("\n=== Summary ===")
print(f"{'Model':<45} {'R²':>10} {'RMSE (°C)':>10}")
for name, (_, r2, rmse) in results:
    print(f"{name:<45} {r2:>10.5f} {rmse:>10.3f}")

# Save best linear model coefficients (Poly+sin/cos) for the back-cast step
best_idx = max(range(len(results)), key=lambda i: results[i][1][1])
print(f"\nBest model: {results[best_idx][0]}")

# Save model + feature spec for back-cast script
import pickle
model_pkl = os.path.join(OUT_DIR, "hot_t_best_model.pkl")
state = {
    "feat_keys": feat_keys,
    "linear_models": {
        name: {"coef": r[0]} for name, r in results if isinstance(r[0], np.ndarray)
    },
    "best_linear_name": results[best_idx][0],
    "use_gb": HAS_SKLEARN,
}
if HAS_SKLEARN:
    state["gbr"] = BEST_GBR
with open(model_pkl, "wb") as f:
    pickle.dump(state, f)
print(f"\nModel saved -> {model_pkl}")
