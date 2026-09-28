"""make_figs_345.py — AMT Fig 3 (validation), Fig 4 (error budget), Fig 5 (identifiability).

Standalone: reads only ./data/*.csv next to this file and writes ./out/amt_fig{3,4,5}_*.{png,pdf}.
Values not stored in a CSV are taken from the manuscript text and marked TEXT below.
Fig 4 (2026-09-28): the Sigma-ANs responses are formed as a_* - g' b_* (300 C minus g' x 180 C, g' read from
data/amt_recompute_values.json, copy of artifact e27a3579); the fit-sigma line and panel (b) values are read from
the same JSON (denominator.window_matched_gprime, sec45.*). Previously s_* (unit gain) and TEXT values were used.

    python paper/amt2026/make_figs_345.py
"""
import os
import numpy as np
import pandas as pd
import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

HERE = os.path.dirname(os.path.abspath(__file__))
D = lambda f: os.path.join(HERE, "data", f)
OUT = os.path.join(HERE, "out"); os.makedirs(OUT, exist_ok=True)

def style(sizes=(8, 7, 6)):
    b, s, t = sizes
    mpl.rcParams.update({"font.family": "sans-serif", "font.size": b, "axes.labelsize": b, "axes.titlesize": b,
        "legend.fontsize": s, "xtick.labelsize": t, "ytick.labelsize": t, "axes.linewidth": 0.6,
        "xtick.direction": "out", "ytick.direction": "out", "xtick.major.size": 3, "ytick.major.size": 3,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6, "axes.spines.top": False, "axes.spines.right": False,
        "legend.frameon": False, "savefig.dpi": 300, "savefig.bbox": "tight", "axes.titlelocation": "left",
        "lines.linewidth": 1.2, "pdf.fonttype": 42, "ps.fonttype": 42})

def letter(ax, s, dx=-0.18, dy=1.02):
    ax.text(dx, dy, s, transform=ax.transAxes, fontweight="bold", fontsize=mpl.rcParams["font.size"] + 1, va="bottom", ha="left")

def rsd(x):
    x = np.asarray(x); return 1.4826 * np.median(np.abs(x - np.median(x)))

cAu, cQd, cOr, cG, cLab = "#1f5fa8", "#2a9d8f", "#d9822b", "0.55", "#6a3d9a"

def fig3():
    vs = pd.read_csv(D("varpro_synth_results.csv")); b2 = pd.read_csv(D("h2h_E2_basin.csv")); e1 = pd.read_csv(D("h2h_E1_coverage.csv"))
    g1 = vs[vs.test == "g1_nonlinear_recovery"]; g2 = vs[vs.test == "g2_poly_sweep"]
    JH = np.array([1e-1, 1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8, 1e-9])            # TEXT §3.2 table
    Jsh = np.array([4.31e-3, 4.29e-5, 4.29e-7, 4.51e-9, 2.60e-9, 7.28e-8, 5.79e-7, 6.95e-6, 1.09e-5])
    Jsq = np.array([np.nan, 1.02, 2.63e-2, 2.61e-4, 2.61e-6, 2.61e-8, 2.64e-9, 2.87e-8, 2.70e-7])
    fig = plt.figure(figsize=(7.2, 5.9))
    gs = fig.add_gridspec(2, 3, hspace=0.58, wspace=0.42, left=0.08, right=0.985, top=0.93, bottom=0.09)
    a = fig.add_subplot(gs[0, 0])
    a.scatter(g1.true_shift - 0.12, np.abs(g1.no2_rel).clip(1e-17), s=14, color=cAu, lw=0, label="NO$_2$ (relative)")
    a.scatter(g1.true_shift + 0.12, np.abs(g1.d_shift).clip(1e-17), s=14, facecolor="white", edgecolor=cAu, lw=0.8, label="shift (px)")
    a.set_yscale("log"); a.set_ylim(1e-17, 1e-6); a.set_xlabel("true shift (px)"); a.set_ylabel("recovery error")
    a.legend(loc="upper left", fontsize=6, handletextpad=0.2)
    a.text(0.97, 0.78, "× 3 squeezes each", transform=a.transAxes, ha="right", fontsize=6, color=cG)
    a.set_title("exact recovery, 27 cases", fontsize=7.5); letter(a, "a")
    b = fig.add_subplot(gs[0, 1])
    b.semilogy(g2.poly_order, np.abs(g2.rel_err_noisefree).clip(1e-16), "o-", color=cAu, ms=4, lw=1)
    b.set_xlabel("baseline polynomial order"); b.set_ylabel("NO$_2$ error, noise-free")
    b.axvline(4, color=cG, ls=":", lw=0.7); b.text(4.1, 3e-2, "truth: 4th order", fontsize=6, color=cG)
    b.set_ylim(1e-16, 3); b.set_xticks(range(0, 9))
    for o_, lab in [(0, "27 %"), (1, "0.75 %")]:
        v = abs(g2[g2.poly_order == o_].rel_err_noisefree.values[0]); b.annotate(lab, (o_, v), xytext=(6, 2), textcoords="offset points", fontsize=6)
    bi = b.inset_axes([0.42, 0.40, 0.55, 0.30])
    bi.plot(g2.poly_order, g2.ratio, "o", color=cAu, ms=2.5); bi.axhline(1, color="k", lw=0.5)
    bi.set_ylim(0, 1.2); bi.set_xticks([0, 4, 8]); bi.tick_params(labelsize=5, length=2, pad=1)
    bi.set_title("noisy: scatter / reported σ", fontsize=5.5, pad=1.5)
    b.set_title("baseline order is the one free choice", fontsize=7.5); letter(b, "b")
    c = fig.add_subplot(gs[0, 2])
    c.loglog(JH, Jsh, "o-", color=cAu, ms=3.5, lw=1, label="shift"); c.loglog(JH, Jsq, "s-", color=cQd, ms=3.2, lw=1, label="squeeze")
    hh = np.array([1e-4, 3e-2]); c.loglog(hh, 4.3e-3 * hh ** 2, color="k", lw=0.6, ls="--"); c.text(1.5e-3, 1.2e-9, "slope $h^2$", fontsize=6)
    c.set_xlabel("finite-difference step $h$"); c.set_ylabel("|analytic − FD| (rel.)"); c.set_ylim(1e-10, 3); c.invert_xaxis()
    c.legend(loc="upper right", bbox_to_anchor=(1.0, 0.80), handlelength=1.4)
    c.text(0.97, 0.97, "floor 2.6×10$^{-9}$ (round-off)", transform=c.transAxes, ha="right", va="top", fontsize=6, color=cG)
    c.set_title("analytic Jacobian reaches round-off", fontsize=7.5); letter(c, "c")
    d = fig.add_subplot(gs[1, 0]); jit = 0.12
    d.scatter(b2.true_shift - jit, b2.aug_shift - b2.true_shift, s=9, color=cAu, lw=0, label="Augur")
    d.scatter(b2.true_shift + jit, b2.qd_shift - b2.true_shift, s=9, color=cQd, lw=0, marker="D", label="QDOAS")
    d.axhline(0, color="k", lw=0.5); d.set_ylim(-0.4, 0.4)
    d.set_xlabel("true shift (px), start at 0"); d.set_ylabel("recovered − true shift (px)")
    d.legend(loc="upper left", ncol=2, handletextpad=0.2, columnspacing=0.8)
    miss = int(((b2.aug_shift - b2.true_shift).abs() > 1).sum()), int(((b2.qd_shift - b2.true_shift).abs() > 1).sum())
    d.text(0.97, 0.05, "misses > 1 px: %d / %d" % miss, transform=d.transAxes, ha="right", fontsize=6)
    d.set_title("same convergence range", fontsize=7.5); letter(d, "d")
    e = fig.add_subplot(gs[1, 1]); rows_e = ["C1", "C2", "C3"]; labs = ["C1 noise", "C2 noise×10", "C3 narrow, ×3"]; ypos = [2, 1, 0]
    for cd_, y in zip(rows_e, ypos):
        m1 = e1[(e1.cond == cd_) & (e1.prog == "Augur noEt(joint)")].iloc[0]; q = e1[(e1.cond == cd_) & (e1.prog == "QDOAS")].iloc[0]
        pr = e1[(e1.cond == cd_) & (e1.prog == "Augur(joint)")].iloc[0]
        e.scatter(m1.sd_z, y + 0.12, color=cAu, s=22, zorder=3, label="Augur, same model" if y == 2 else None)
        e.scatter(q.sd_z, y - 0.12, color=cQd, marker="D", s=18, zorder=3, label="QDOAS" if y == 2 else None)
        e.scatter(pr.sd_z, y + 0.12, facecolor="white", edgecolor=cOr, s=22, lw=0.9, zorder=3, label="Augur, etalon terms on" if y == 2 else None)
    e.axvline(1, color="k", lw=0.5); e.set_yticks(ypos); e.set_yticklabels(labs); e.set_xlim(0.9, 1.18); e.set_ylim(-0.6, 2.9)
    e.set_xlabel("SD of (retrieved − truth) / reported σ"); e.legend(loc="upper right", fontsize=5.5, handletextpad=0.2, borderaxespad=0.1)
    c3 = e1[(e1.cond == "C3") & (e1.prog == "Augur(joint)")].iloc[0]; q3 = e1[(e1.cond == "C3") & (e1.prog == "QDOAS")].iloc[0]
    e.annotate("scatter ×%.1f" % (c3.sd_rel / q3.sd_rel), (c3.sd_z, 0.12), xytext=(0, -11), textcoords="offset points", fontsize=5.5, color=cOr, ha="center")
    e.set_title("honest error bars, N = 300 each", fontsize=7.5); letter(e, "e")
    f_ = fig.add_subplot(gs[1, 2]); xa = np.arange(3)
    aug, ref, fix = [1.32, 1.09, 1.65], [1.19, 1.33, 1.57], [1.19, np.nan, 1.75]                     # TEXT §3.4
    f_.scatter(xa - 0.15, aug, color=cAu, s=22, zorder=3, label="Augur")
    f_.scatter(xa + 0.15, ref, color=cQd, marker="D", s=18, zorder=3, label="reference impl.")
    f_.scatter(xa - 0.15, fix, facecolor="white", edgecolor=cAu, s=22, lw=0.9, zorder=3, label="Augur, shift fixed")
    f_.axhline(1, color="k", lw=0.5); f_.axhline(np.sqrt(3), color=cOr, lw=0.8, ls="--")
    f_.text(0.55, np.sqrt(3) + 0.02, "√3 predicted by AR(1)", ha="center", fontsize=6, color=cOr, va="bottom")
    f_.set_xticks(xa); f_.set_xticklabels(["white", "doubled", "AR(1) ρ=0.5"]); f_.set_xlim(-0.5, 2.5); f_.set_ylim(0.9, 1.95)
    f_.set_ylabel("scatter / reported σ"); f_.legend(loc="upper left", bbox_to_anchor=(0.0, 0.80), fontsize=6, handletextpad=0.2)
    f_.set_title("benchmark group B: predictable shortfall", fontsize=7.5); letter(f_, "f")
    for ext in ("png", "pdf"): fig.savefig(os.path.join(OUT, "amt_fig3_validation." + ext))
    plt.close(fig)

def fig4():
    import json
    rv = json.load(open(D("amt_recompute_values.json"), encoding="utf-8"))
    g = float(rv["scale_budget_vs_product"]["g_prime_values"][0]); den = float(rv["denominator"]["window_matched_gprime"]); h = rv["sec45"]
    P = pd.read_csv(D("production_budget_clockfixed.csv")); P = P[P.ok.astype(bool)].copy()
    for k in ("i0", "rt", "ef", "tri"): P["g_" + k] = P["a_" + k] - g * P["b_" + k]          # Sigma-ANs response (300 C minus g' x 180 C)
    P["t"] = pd.Timestamp("2026-01-01") + pd.to_timedelta(P.sec, unit="s") + pd.Timedelta("9h")   # sec axis is UTC -> KST
    terms = [("g_i0", "zero-air ($I_0$) interpolation", cAu, "-"), ("g_rt", "reflectivity ($R$) interpolation", cOr, "-"),
             ("g_ef", "etalon frequency", cQd, "-"), ("g_tri", "joint", "k", "--")]
    fig = plt.figure(figsize=(7.2, 5.4))
    gs = fig.add_gridspec(2, 2, width_ratios=[1.6, 1], height_ratios=[1.15, 1], hspace=0.55, wspace=0.32, left=0.08, right=0.985, top=0.94, bottom=0.09)
    a = fig.add_subplot(gs[0, 0])
    for k, lab, c_, ls in terms:
        x = np.sort(P[k].abs().values); y = 1 - np.arange(1, len(x) + 1) / len(x)
        a.plot(x, y, color=c_, lw=1.3 if ls == "-" else 1.0, ls=ls, label="%s  (rSD %.3f, SD %.3f)" % (lab, rsd(P[k]), P[k].std()))
    a.set_xscale("log"); a.set_yscale("log"); a.set_xlim(1e-4, 1); a.set_ylim(1e-4, 1.05)
    a.axvline(den, color="0.3", lw=0.8, ls=":")                                                      # JSON denominator
    a.text(den * 0.92, 0.02, "σ the fit reports\nper scan, %.4f ppb →" % den, fontsize=6, color="0.3", ha="right", va="center")
    a.set_xlabel("|ΔΣANs| per 60 s record (ppb)"); a.set_ylabel("fraction of records exceeding")
    a.legend(loc="lower left", fontsize=5.8, handlelength=1.8, borderaxespad=0.2)
    fmt = mpl.ticker.FuncFormatter(lambda v, _: "%g" % v); a.xaxis.set_major_formatter(fmt); a.yaxis.set_major_formatter(fmt)
    a.set_title("reflectivity: smallest typical term, heaviest tail", fontsize=7.5); letter(a, "a")
    b = fig.add_subplot(gs[0, 1])
    items = [("observed, campaign\n(%d h)" % h["obs_campaign_hours"], h["obs_campaign"], "0.55"),
             ("observed, matched\nhours (%d h)" % h["obs_matched_hours"], h["obs_matched"], cQd),
             ("budget, jointly\npropagated", h["budget_gate"], cAu)]                                # JSON sec45
    for i, (lab, v, c_) in enumerate(items):
        b.plot([0, v], [i, i], color="0.85", lw=1.2, zorder=1); b.scatter(v, i, s=45, color=c_, zorder=3); b.text(v + 0.002, i + 0.18, ("%.4f" if i == 2 else "%.3f") % v, fontsize=6, va="bottom")
    b.set_yticks(range(3)); b.set_yticklabels([x[0] for x in items], fontsize=6); b.set_xlim(0, 0.1); b.set_ylim(-0.6, 2.7)
    b.text(0.02, 0.5, "budget = %.2f × matched" % h["ratio_hourly"], fontsize=6.5, color=cAu)
    b.set_xlabel("hour-to-hour variation of ΣANs (ppb)"); b.set_title("budget stays under what the data show", fontsize=7.5); letter(b, "b")
    c = fig.add_subplot(gs[1, :])
    c.scatter(P.t, P.g_rt, s=0.8, color=cOr, alpha=0.45, lw=0)
    hr = P.set_index("t").g_rt.pow(2).resample("1h").mean().pow(0.5)
    c.plot(hr.index, hr.values, color="k", lw=0.8, drawstyle="steps-mid", label="hourly RMS"); c.plot(hr.index, -hr.values, color="k", lw=0.8, drawstyle="steps-mid")
    hs = P.set_index("t").g_rt.pow(2).resample("1h").sum().sort_values(ascending=False)
    for t_ in hs.index[:5]: c.axvspan(t_, t_ + pd.Timedelta("1h"), color=cOr, alpha=0.18, lw=0)
    c.axhline(0, color="0.6", lw=0.4); c.set_ylim(-0.65, 0.65); c.set_ylabel("ΔΣANs from\nreflectivity (ppb)")
    c.text(0.995, 0.95, "5 of %d hours (shaded) carry %.0f %% of the reflectivity variance" % (hr.notna().sum(), hs.iloc[:5].sum() / hs.sum() * 100),
           transform=c.transAxes, ha="right", va="top", fontsize=6.5)
    c.xaxis.set_major_locator(mdates.DayLocator()); c.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    c.set_xlim(P.t.min() - pd.Timedelta("2h"), P.t.max() + pd.Timedelta("2h")); c.set_xlabel("KST, budget window 2026")
    c.legend(loc="lower right", fontsize=6); c.set_title("the tail is a few hours, not every record", fontsize=7.5); letter(c, "c")
    for ext in ("png", "pdf"): fig.savefig(os.path.join(OUT, "amt_fig4_error_budget." + ext))
    plt.close(fig)

def fig5():
    csl = pd.read_csv(D("cold_shift_landscape.csv")); kp = pd.read_csv(D("kriss_injection_0602_shift_profiles.csv"))
    G = kp.shift_px_augur.values
    fig = plt.figure(figsize=(7.2, 5.3))
    gs = fig.add_gridspec(2, 2, hspace=0.55, wspace=0.32, left=0.09, right=0.985, top=0.93, bottom=0.09)
    a = fig.add_subplot(gs[0, 0]); m_ = (csl.shift_px >= -4) & (csl.shift_px <= 4)
    for col in csl.columns[1:]:
        y = csl.loc[m_, col] / csl.loc[m_, col].min(); a.plot(csl.loc[m_, "shift_px"], y, color=cAu, lw=0.9, alpha=0.55)
    a.axvspan(-1, 1, color="0.93", lw=0, zorder=0); a.axvline(-0.5, color=cOr, lw=1, ls="--")
    a.text(-0.6, 1.052, "operational\nfixed value", fontsize=6, color=cOr, va="top", ha="right")
    a.text(0.98, 0.97, "12 ambient spectra, cold channel\nmedian spread 1.2 % over ±4 px", transform=a.transAxes, fontsize=6, color="0.3", ha="right", va="top")
    a.set_xlim(-4, 4); a.set_ylim(0.998, 1.072); a.set_xlabel("wavelength shift (px)"); a.set_ylabel("residual sum of squares / min")
    a.set_title("ambient air: the objective is flat", fontsize=7.5); letter(a, "a")
    b = fig.add_subplot(gs[0, 1])
    for col, c_, lab in [("9.3 ppb", cLab, "9.3 ppb NO$_2$ added"), ("3.6 ppb", "#a98bd0", "3.6 ppb NO$_2$ added"), ("0 ppb", "0.6", "0 ppb (zero air)")]:
        pr = kp[col].values; rr = (pr / pr.min()) ** 2; mG = (G >= -4) & (G <= 4)
        b.plot(G[mG], rr[mG], color=c_, lw=1.4, label=lab)
        if col != "0 ppb": b.scatter(G[np.argmin(pr)], 1.0, color=c_, s=16, zorder=4)
    b.axvspan(-1, 1, color="0.93", lw=0, zorder=0); b.axvline(-0.5, color=cOr, lw=1, ls="--")
    b.axhspan(0.998, 1.072, color=cAu, alpha=0.08, lw=0); b.text(1.95, 1.08, "range of (a)", fontsize=5.5, color=cAu, ha="right", va="bottom")
    b.set_xlim(-3.5, 2.0); b.set_ylim(0.95, 3.2); b.set_xlabel("wavelength shift (px)"); b.set_ylabel("residual sum of squares / min")
    b.legend(loc="upper left", fontsize=6, handlelength=1.4)
    b.text(0.97, 0.60, "minimum −0.10 px\n(−0.15 px at 3.6 ppb)", transform=b.transAxes, ha="right", fontsize=6, color=cLab)
    b.set_title("laboratory NO$_2$: the same channel locates it", fontsize=7.5); letter(b, "b")
    c = fig.add_subplot(gs[1, 0])
    pts = [("this work, shift free", -2.014, cAu, "85.5 % at a bound"), ("QDOAS, same spectra", -0.088, cQd, "4.5 % at a bound"),   # TEXT §5.1
           ("operational fixed value", -0.5, cOr, "not fitted"), ("laboratory NO$_2$, 9.3 ppb", G[np.argmin(kp["9.3 ppb"].values)], cLab, "profile minimum"),
           ("laboratory NO$_2$, 3.6 ppb", G[np.argmin(kp["3.6 ppb"].values)], "#a98bd0", "profile minimum")]
    for i, (lab, v, c_, note) in enumerate(pts):
        y = len(pts) - 1 - i; c.scatter(v, y, s=40, color=c_, zorder=3); c.text(v + 0.12, y, note, fontsize=6, va="center", color=c_)
    c.set_yticks(range(len(pts))[::-1]); c.set_yticklabels([p[0] for p in pts], fontsize=6.5)
    c.axvspan(-2, 2, color="0.95", lw=0, zorder=0); c.axvline(-2, color="0.6", lw=0.6); c.axvline(2, color="0.6", lw=0.6)
    c.text(-2, len(pts) - 0.4, "bound", fontsize=5.5, color="0.5", ha="center"); c.text(2, len(pts) - 0.4, "bound", fontsize=5.5, color="0.5", ha="center")
    c.set_xlim(-2.6, 2.6); c.set_ylim(-0.6, len(pts) - 0.1); c.set_xlabel("cold-channel shift (px)")
    c.set_title("five answers to one question", fontsize=7.5); letter(c, "c")
    d = fig.add_subplot(gs[1, 1]); xx = np.arange(3)
    fl, fx = [0.940, 0.858, 1.027], [1.019, 0.662, 1.178]                                             # TEXT §5.1
    for i in range(3): d.plot([xx[i] - 0.12, xx[i] + 0.12], [fl[i], fx[i]], color="0.8", lw=1, zorder=1)
    d.scatter(xx - 0.12, fl, color=cAu, s=36, zorder=3, label="shift fitted"); d.scatter(xx + 0.12, fx, color=cOr, s=36, zorder=3, label="shift fixed at −0.5 px")
    d.axhline(1, color="k", lw=0.5, ls="--"); d.text(1.42, 1.005, "agreement", fontsize=6, ha="center", va="bottom", color="0.4")
    d.annotate("−23 %", (1 + 0.12, 0.662), xytext=(8, 0), textcoords="offset points", fontsize=6, va="center", color=cOr)
    d.set_xticks(xx); d.set_xticklabels(["NO$_2$", "CHOCHO", "H$_2$O"]); d.set_xlim(-0.5, 2.5); d.set_ylim(0.55, 1.25)
    d.set_ylabel("slope against hot-channel reference"); d.legend(loc="lower left", fontsize=6)
    d.set_title("and the answer moves the amounts", fontsize=7.5); letter(d, "d")
    for ext in ("png", "pdf"): fig.savefig(os.path.join(OUT, "amt_fig5_identifiability." + ext))
    plt.close(fig)

if __name__ == "__main__":
    style(); fig3(); fig4(); fig5()
    print("wrote", sorted(os.listdir(OUT)))
