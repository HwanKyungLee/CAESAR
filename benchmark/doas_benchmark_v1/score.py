
"""
Score a submission against the DOAS benchmark truth.

A submission is a CSV with columns
    case_id, NO2, NO2_sigma, shift_px, shift_sigma
and optionally at_grid_edge / termination.

The benchmark does not only ask whether the answer is right. Groups B and C
ask whether the *reported uncertainty* is right, which is the harder test.
"""
import numpy as np, pandas as pd


def rsd(x):
    x = np.asarray(x, float)
    return 1.4826 * np.median(np.abs(x - np.median(x)))


def score(man, sub):
    d = man.merge(sub, on="case_id", suffixes=("_true", ""))
    rep = []

    a = d[d.group == "A_exact"]
    e = np.abs(a.NO2 - a.NO2_molec_cm3) / a.NO2_molec_cm3
    rep.append(dict(group="A_exact", metric="max relative error", value=float(e.max()),
                    target="< 1e-6", pass_=bool(e.max() < 1e-6)))

    # Tags are discovered from the case ids rather than hard-coded, so a package
    # generated with --noise-levels beyond the default two is scored in full.
    # For the shipped package this yields exactly n1, n2, ar, in that order.
    seen = [c.split("_")[1] for c in d[d.group == "B_noise"].case_id]
    tags = sorted({t for t in seen if t != "ar"},
                  key=lambda t: float(t[1:]) if t[1:] else 0.0)
    tags += ["ar"] if "ar" in seen else []
    for tag, lab in ((f"B_{t}_", f"noise x{t[1:]}" if t != "ar" else "AR(1) 0.5")
                     for t in tags):
        b = d[d.case_id.str.startswith(tag)]
        if not len(b):
            continue
        t = b.NO2_molec_cm3.iloc[0]
        bias = (np.median(b.NO2) - t) / t
        sc = rsd(b.NO2) / t
        rp = np.median(b.NO2_sigma) / t
        rep.append(dict(group="B_noise:" + lab, metric="scatter / reported sigma",
                        value=float(sc / rp) if rp else np.inf, target="1.0 +- 0.2",
                        pass_=bool(rp and 0.8 <= sc / rp <= 1.2),
                        extra=f"bias {100*bias:+.2f} %, scatter {100*sc:.2f} %, reported {100*rp:.2f} %"))

    c = d[d.group == "C_mismatch"].copy()
    if len(c):
        # absolute bias in extinction units, in multiples of the single-scan noise.
        # relative bias is not used as the headline: the weakest case has a truth
        # of 0.3 x noise, where a relative figure says nothing about the retrieval.
        nz = float(c.noise_rms.replace(0, np.nan).dropna().median()) if c.noise_rms.any() else 6.16e-9
        c["bias_alpha"] = (c.NO2 - c.NO2_molec_cm3) / c.NO2_molec_cm3 * c.NO2_peak_alpha_cm1
        c["snr"] = c.NO2_peak_alpha_cm1 / nz
        # a submission that declares a case unconstrained has behaved correctly and
        # is not scored on its value there; those cases are counted separately.
        flag = c.at_grid_edge.fillna(False).astype(bool) if "at_grid_edge" in c else pd.Series(False, index=c.index)
        k = c[~flag]
        det = k[k.snr >= 3.0]
        # over-flagging guard: a case declared unconstrained whose truth was
        # detectable and whose returned value was in fact within 20 % is a
        # false alarm, and is reported so that flagging everything wins nothing.
        fa = c[flag & (c.snr >= 3.0) &
               (((c.NO2 - c.NO2_molec_cm3) / c.NO2_molec_cm3).abs() < 0.20)]
        worst = k.iloc[int(np.argmax(np.abs(k.bias_alpha)))] if len(k) else None
        rep.append(dict(group="C_mismatch", metric="max |bias| in units of the noise RMS",
                        value=float(np.max(np.abs(k.bias_alpha)) / nz) if len(k) else np.nan,
                        target="reported sigma is not expected to cover it",
                        pass_=None,
                        extra="scored on %d of %d cases (%d declared unconstrained, %d of those "
                              "false alarms); worst %s; max relative bias among detectable cases "
                              "(truth > 3x noise) %.1f %%; max |bias|/reported sigma %.1f"
                              % (len(k), len(c), int(flag.sum()), len(fa),
                                 worst.case_id if worst is not None else "-",
                                 100 * ((det.NO2 - det.NO2_molec_cm3) / det.NO2_molec_cm3).abs().max()
                                 if len(det) else np.nan,
                                 float(np.max(np.abs(k.NO2 - k.NO2_molec_cm3) / k.NO2_sigma)) if len(k) else np.nan)))

    dd = d[d.group == "D_identifiability"]
    if len(dd):
        flagged = int(((dd.shift_sigma > 1.0) | (~np.isfinite(dd.shift_sigma))
                       | dd.get("at_grid_edge", pd.Series(False, index=dd.index))).sum())
        rep.append(dict(group="D_identifiability", metric="cases declared unconstrained",
                        value=f"{flagged}/{len(dd)}", target=f"{len(dd)}/{len(dd)}",
                        pass_=bool(flagged == len(dd)),
                        extra="returned shift spread %.2f px" % (dd.shift_px.max() - dd.shift_px.min())))
    f = d[d.group == "F_subpixel"]
    if len(f):
        rel = np.abs(f.NO2 - f.NO2_molec_cm3) / f.NO2_molec_cm3
        rep.append(dict(group="F_subpixel", metric="median |error| from sub-pixel model",
                        value=float(np.median(rel)), target="report, do not pass/fail",
                        pass_=None,
                        extra="max %.2e; truth is band-limited, so this is the cost of "
                              "the interpolator chosen" % rel.max()))

    e = d[d.group == "E_window"]
    if len(e):
        w = e.pivot_table(index="pair_id", columns="channel",
                          values=["NO2", "NO2_molec_cm3", "NO2_sigma", "shift_sigma", "NO2_peak_alpha_cm1", "at_grid_edge"])
        chs = sorted(e.channel.unique())
        if len(chs) == 2:
            a, b_ = chs
            rel = ((w[("NO2", a)] / w[("NO2_molec_cm3", a)]) -
                   (w[("NO2", b_)] / w[("NO2_molec_cm3", b_)])).abs()
            comb = np.hypot(w[("NO2_sigma", a)] / w[("NO2_molec_cm3", a)],
                            w[("NO2_sigma", b_)] / w[("NO2_molec_cm3", b_)])
            snr = w[("NO2_peak_alpha_cm1", a)] / 6.16e-9
            det = snr >= 10.0
            if ("at_grid_edge", a) in w.columns and ("at_grid_edge", b_) in w.columns:
                ok = ~(w[("at_grid_edge", a)].fillna(0).astype(bool)
                       | w[("at_grid_edge", b_)].fillna(0).astype(bool))
                det = det & ok
            rep.append(dict(group="E_window",
                            metric="max window-to-window disagreement (truth > 10x noise)",
                            value=float(rel[det].max()) if det.any() else np.nan,
                            target="within the combined reported sigma",
                            pass_=bool((rel[det] <= comb[det]).all()) if det.any() else None,
                            extra="all pairs: max %.3f; %d/%d inside the combined reported sigma; "
                                  "median shift sigma %s %.2f px vs %s %.2f px"
                                  % (float(rel.max()), int((rel <= comb).sum()), len(rel), a,
                                     float(np.nanmedian(w[("shift_sigma", a)])), b_,
                                     float(np.nanmedian(w[("shift_sigma", b_)])))))
    return pd.DataFrame(rep)
