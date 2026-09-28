"""fig1_standalone.py -- AMT Fig 1 (thesis figure) redrawn from files, no session state.

    python paper/amt2026/fig1_standalone.py            # writes both variants to out/
    python paper/amt2026/fig1_standalone.py --variant file
    python paper/amt2026/fig1_standalone.py --variant legacy

Inputs
  panel a, points  benchmark/instrument_space/metrics_by_coordinate.csv (synthetic; copied to data/)
                   column b_scatter_ratio_detail -> every 'noise x*' entry is a white-noise point
                   (30 over 13 coordinates), every 'AR(1) 0.5' entry a correlated-noise point (13).
  panel a, bar     diagnostics/sensitivity_sweep_2026-09/subsample_validation.csv, row full_8847
                   (field-derived: read in place, not copied)
  panel b          diagnostics/sensitivity_sweep_2026-09/termination_by_config.csv, rows base, steplimit_off
                   (field-derived: read in place)
  panel c          data/cold_shift_landscape.csv (field-derived, private data/ folder; identical to artifact
                   2bb6642f). Optional cross-check against shift_profile_likelihood_intervals.csv
                   (artifact 8ba88527, field-derived) if FIG1_SPL_CSV points to it.

Variants
  file    panel a points read from metrics_by_coordinate.csv                 -> out/amt_fig1_thesis_file.{png,pdf}
  legacy  panel a points = the 26 values hand-typed in the recorded v2 code   -> out/amt_fig1_thesis_legacy.{png,pdf}
          (kept only to document the discrepancy; the legacy series are interpolated between the
          file's min and max and do not match the file -- see manuscript/README.md)
"""
import os, sys, argparse
import numpy as np, pandas as pd
import matplotlib as mpl; mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from scipy.stats import f as fdist

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
D = lambda f: os.path.join(HERE, "data", f)
OUT = os.path.join(HERE, "out"); os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, HERE)
from make_figs_345 import style as _style          # house style used for Figs 2-6

F_METRICS = D("instrument_space_metrics_by_coordinate.csv")
F_METRICS_SRC = os.path.join(REPO, "benchmark", "instrument_space", "metrics_by_coordinate.csv")
F_SUBSAMPLE = os.path.join(REPO, "diagnostics", "sensitivity_sweep_2026-09", "subsample_validation.csv")
F_TERM = os.path.join(REPO, "diagnostics", "sensitivity_sweep_2026-09", "termination_by_config.csv")
F_LAND = D("cold_shift_landscape.csv")
F_SPL = os.environ.get("FIG1_SPL_CSV", "")

# the 26 values hand-typed in the recorded Fig 1 v2 code (legacy variant only)
LEGACY_WHITE = [0.911, 0.934, 0.952, 0.978, 1.002, 1.024, 1.048, 1.072, 1.098, 1.134, 1.190, 1.253, 1.323]
LEGACY_AR1 = [1.420, 1.458, 1.492, 1.531, 1.568, 1.612, 1.654, 1.702, 1.751, 1.812, 1.879, 1.963, 2.049]


def instrument_space_points(path):
    m = pd.read_csv(path)
    rows = []
    for cid, det in zip(m.coordinate_id, m.b_scatter_ratio_detail):
        for part in str(det).split("|"):
            k, v = part.rsplit("=", 1)
            rows.append((cid, k.strip(), float(v)))
    t = pd.DataFrame(rows, columns=["coordinate", "condition", "ratio"])
    white = t[t.condition.str.startswith("noise")].ratio.values
    ar1 = t[t.condition.str.startswith("AR(1)")].ratio.values
    return white, ar1, len(m)


def load_inputs():
    if not os.path.exists(F_METRICS):
        raise SystemExit(f"missing {F_METRICS}; copy it from {F_METRICS_SRC}")
    white, ar1, n_coord = instrument_space_points(F_METRICS)
    sv = pd.read_csv(F_SUBSAMPLE).set_index("sample")
    field_lo, field_hi = float(sv.loc["full_8847", "ratio_lo"]), float(sv.loc["full_8847", "ratio_hi"])
    tb = pd.read_csv(F_TERM).set_index("config_id")
    on, off = tb.loc["base"], tb.loc["steplimit_off"]
    ls = pd.read_csv(F_LAND)
    return dict(white=white, ar1=ar1, n_coord=n_coord, field_lo=field_lo, field_hi=field_hi,
                on=on, off=off, ls=ls)


def profile_intervals(ls, nmp=766):
    xs = ls.shift_px.values
    thr = 1 + fdist.ppf(0.95, 1, nmp) / nmp
    iv = []
    for s_ in [c for c in ls.columns if c != "shift_px"]:
        y = ls[s_].values / ls[s_].values.min()
        ins = y <= thr
        iv.append(dict(spec=s_, lo=xs[ins].min(), hi=xs[ins].max(), best=xs[np.argmin(y)],
                       lo_open=bool(ins[0]), hi_open=bool(ins[-1])))
    iv = pd.DataFrame(iv)
    iv["open"] = iv.lo_open | iv.hi_open
    iv["width"] = iv.hi - iv.lo
    return iv.sort_values("width").reset_index(drop=True), xs, thr


def draw(inp, white, ar1, out_stem):
    mpl.rcParams.update(mpl.rcParamsDefault)
    _style((8, 7, 6))
    C_REP, C_BAD, C_GREY, C_LIGHT = "#1f4e9c", "#c0582b", "#6b6b6b", "#a9bddf"
    segs = [("converged", "pct_converged", C_LIGHT),
            ("step-limited", "pct_step_limited", C_BAD),
            ("at a bound", "pct_at_bound", C_GREY)]
    on, off, ls = inp["on"], inp["off"], inp["ls"]
    field_lo, field_hi = inp["field_lo"], inp["field_hi"]
    ivs, xs, _ = profile_intervals(ls)

    def panel_letter(ax, letter):
        ax.text(-0.13, 1.04, letter, transform=ax.transAxes, fontsize=9,
                fontweight="bold", va="bottom", ha="left")

    fig = plt.figure(figsize=(6.9, 2.8))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.2, 0.95, 1.05], wspace=0.62)
    axA, axB, axC = [fig.add_subplot(gs[0, i]) for i in range(3)]
    rng = np.random.default_rng(3)

    # (a) scatter / reported sigma
    for y, v, c in [(2, np.asarray(white), C_GREY), (1, np.asarray(ar1), C_BAD)]:
        axA.scatter(v, y + rng.uniform(-0.12, 0.12, len(v)), s=10, color=c, alpha=0.85, lw=0, zorder=3)
    axA.plot([field_lo, field_hi], [0, 0], color=C_BAD, lw=5, solid_capstyle="butt", zorder=3)
    for xv in (field_lo, field_hi):
        axA.text(xv, -0.3, f"{xv:.2f}", ha="center", va="top", fontsize=6, color=C_BAD)
    axA.axvline(1, color="#222222", lw=0.8, ls=(0, (3, 2)), zorder=1)
    axA.text(1.04, 2.6, "reported σ", ha="left", va="center", fontsize=6.5, color="#222222")
    n = inp["n_coord"]
    axA.set_yticks([2, 1, 0])
    axA.set_yticklabels([f"white noise\n{n} synthetic instruments",
                         f"correlated noise\n{n} synthetic instruments",
                         "field record\ncalibration budget"], fontsize=6.5)
    axA.set_ylim(-0.75, 2.85)
    axA.set_xlim(0.7, 2.9)
    axA.set_xlabel("actual spread ÷ reported σ")
    axA.set_title("Reported σ holds only where\nthe fit's model is complete", loc="left", fontsize=8)

    # (b) termination state, step limit on / off
    for y, row in [(1, on), (0, off)]:
        left = 0
        for name, col, c in segs:
            w = float(row[col])
            axB.barh(y, w, left=left, color=c, height=0.5, lw=0)
            if w >= 30:
                axB.text(left + w / 2, y, f"{w:.0f} %", ha="center", va="center", fontsize=6.5, color="#1a2f55")
            elif w > 0:
                if name == "at a bound":
                    axB.text(101.5, y, f"{w:.0f} %", ha="left", va="center", fontsize=6, color=c, clip_on=False)
                else:
                    axB.text(left + w / 2, y + 0.31, f"{w:.0f} %", ha="center", va="bottom", fontsize=6, color=c)
            left += w
    axB.set_yticks([1, 0])
    axB.set_yticklabels(["step limit\non", "step limit\noff"], fontsize=6.5)
    axB.set_xlim(0, 100)
    axB.set_ylim(-0.8, 2.05)
    axB.set_xlabel("scans (%)")
    axB.legend([Patch(color=c) for _, _, c in segs], [nm for nm, _, _ in segs],
               ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.02),
               frameon=False, fontsize=6.5, handlelength=0.9, columnspacing=0.8, handletextpad=0.4)
    axB.text(50, -0.55, f"median NO$_2$\n{float(on.no2_median_ppb):.4f} → {float(off.no2_median_ppb):.4f} ppb",
             ha="center", va="center", fontsize=6.5, color=C_REP)
    axB.set_title("A guard reclassifies 21 % of\nscans; NO$_2$ moves 0.4 % of σ", loc="left", fontsize=8)

    # (c) 95 % profile-likelihood intervals of the cold shift
    axC.axvspan(xs.min(), xs.max(), color="#f0f0f0", lw=0, zorder=0)
    for k, r0 in ivs.iterrows():
        c = C_BAD if r0.open else C_REP
        axC.plot([r0.lo, r0.hi], [k, k], color=c, lw=1.8, solid_capstyle="butt", zorder=2)
        axC.plot(r0.best, k, "o", ms=2.8, color=c, zorder=3)
        if r0.lo_open:
            axC.plot(r0.lo, k, marker="<", ms=4, color=c, zorder=3)
        if r0.hi_open:
            axC.plot(r0.hi, k, marker=">", ms=4, color=c, zorder=3)
    axC.axvline(-0.5, color="#222222", lw=0.8, ls=(0, (3, 2)))
    axC.text(-0.25, len(ivs) - 0.1, "operational\nfixed value", ha="left", va="bottom", fontsize=6.5)
    axC.set_yticks([])
    axC.set_ylim(-0.8, len(ivs) + 1.7)
    axC.set_xlim(-6.6, 6.6)
    axC.set_xlabel("wavelength shift (px)")
    axC.set_ylabel(f"95 % profile interval\n{len(ivs)} cold-configuration spectra", fontsize=6.5)
    axC.set_title(f"The data do not fix the shift:\n{int(ivs.open.sum())} of {len(ivs)} reach the scan edge",
                  loc="left", fontsize=8)
    for ax in (axA, axB, axC):
        ax.xaxis.labelpad = 5
    for ax, l in zip([axA, axB, axC], "abc"):
        panel_letter(ax, l)
    fig.savefig(out_stem + ".png", dpi=300, bbox_inches="tight")
    fig.savefig(out_stem + ".pdf", bbox_inches="tight")
    plt.close(fig)
    return out_stem + ".png"


def checks(inp):
    ivs, xs, thr = profile_intervals(inp["ls"])
    print(f"panel a: {len(inp['white'])} white points, {len(inp['ar1'])} AR(1) points over {inp['n_coord']} coordinates")
    print(f"panel a bar: {inp['field_lo']:.5f}-{inp['field_hi']:.5f}; panel b: "
          f"{float(inp['on'].pct_converged)}/{float(inp['on'].pct_step_limited)}/{float(inp['on'].pct_at_bound)} vs "
          f"{float(inp['off'].pct_converged)}/{float(inp['off'].pct_step_limited)}/{float(inp['off'].pct_at_bound)}")
    print(f"panel c: threshold {thr:.5f}, {int(ivs.open.sum())}/{len(ivs)} open, median width {ivs.width.median():.2f} px")
    if F_SPL and os.path.exists(F_SPL):
        spl = pd.read_csv(F_SPL)
        spl = spl[spl.n_minus_P == 766].set_index("spec")
        j = ivs.set_index("spec").join(spl[["lo", "hi"]], rsuffix="_csv")
        print("cross-check vs shift_profile_likelihood_intervals.csv: max |lo| diff "
              f"{(j.lo - j.lo_csv).abs().max():.3g}, max |hi| diff {(j.hi - j.hi_csv).abs().max():.3g}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["file", "legacy", "both"], default="both")
    a = ap.parse_args()
    inp = load_inputs()
    checks(inp)
    if a.variant in ("file", "both"):
        print(draw(inp, inp["white"], inp["ar1"], os.path.join(OUT, "amt_fig1_thesis_file")))
    if a.variant in ("legacy", "both"):
        print(draw(inp, LEGACY_WHITE, LEGACY_AR1, os.path.join(OUT, "amt_fig1_thesis_legacy")))
