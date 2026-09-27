import os
import sys
import io
import contextlib
import re
import numpy as np
import pandas as pd
import xml.etree.ElementTree as ET
import copy
import subprocess
import matplotlib as mpl
import matplotlib.pyplot as plt

REPO = r"C:\GHL\CAESAR"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

os.environ["AUGUR_WVCAL_DIR"] = os.path.join(REPO, "tests", "data", "wv_cal_roi1")

from core.doas_fit import DoasFitter
from core.engine import UniversalEngine

REFDIR = os.path.join(REPO, "tests", "data", "wv_cal_roi1")
REF_FILES = [("NO2", "Ref_NO2_Dynamic-ILS-Applied.dat"),
             ("CHOCHO", "Ref_CHOCHO_Dynamic-ILS-Applied.dat"),
             ("H2O", "Ref_H2O-HITRAN_Dynamic-ILS-Applied.dat")]

FIT_NM = (444.1, 470.6)
POLY_ORDER = 3
ETALON_F = 0.12
NOISE_MEASURED = 6.16e-9
SCD_MID = 1e12
COMPANION_FRAC = {"CHOCHO": 0.05, "H2O": 0.30}
FIELD_SHIFT = -1.96


def read_col(path):
    return np.array([float(l) for l in open(path, encoding="utf-8", errors="replace")
                     if l.strip() and not l.lstrip().startswith("#")])


def build_engine(gases, ils_extra_px=0.0):
    calib = [f for f in os.listdir(REFDIR) if f.startswith("Calib")]
    wave = read_col(os.path.join(REFDIR, calib[0]))
    eng = UniversalEngine()
    eng.set_wavelength_axis(wave)
    for name, fn in REF_FILES:
        if name not in gases:
            continue
        ok, msg = eng.add_reference(name, os.path.join(REFDIR, fn), wave_nm=wave)
        if not ok:
            raise RuntimeError(f"{name}: {msg}")
    eng.apply_ils_convolution(ils_extra_px)
    return eng, wave


def window(wave):
    px = np.where((wave >= FIT_NM[0]) & (wave <= FIT_NM[1]))[0].astype(float)
    return px, px[len(px) // 2]


def props_for(gases, sh_val="-6.0, 6.0", sq_val="-0.02, 0.02"):
    p = {"NO2": {"sh_mode": "Limit", "sh_val": sh_val,
                 "sq_mode": "Limit", "sq_val": sq_val,
                 "t_ref": 25.0, "t_coeff": 0.0}}
    for g in gases:
        if g != "NO2":
            p[g] = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link",
                    "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}
    return p


def companion_scds(eng, gases, no2):
    out = {"NO2": no2}
    ref_amp = SCD_MID * float(np.max(np.abs(eng.raw_references["NO2"])))
    for g in gases:
        if g == "NO2":
            continue
        peak = float(np.max(np.abs(eng.raw_references[g]))) or 1.0
        out[g] = COMPANION_FRAC[g] * ref_amp / peak
    return out


def synthesize(eng, vp, center, scds, shift, squeeze, noise_rms=0.0, rng=None,
               etalon_amp=0.0, etalon_f=ETALON_F, etalon_phase=0.4):
    px = (vp - center) * squeeze + center + shift
    alpha = np.zeros(len(vp))
    for g, n in scds.items():
        alpha = alpha + n * eng.interpolators[g](px)
    x = np.linspace(-1.0, 1.0, len(vp))
    bg = max(float(np.max(np.abs(alpha))), 1e-12)
    alpha = alpha + bg * (0.30 - 0.10 * x + 0.05 * (2 * x ** 2 - 1))
    if etalon_amp:
        alpha = alpha + etalon_amp * bg * np.sin(etalon_f * vp + etalon_phase)
    if noise_rms > 0:
        alpha = alpha + rng.normal(0.0, noise_rms, len(vp))
    return alpha


def recover(eng, fitter, props, vp, center, alpha, poly_order=POLY_ORDER,
            step_limit=20.0, etalon_f=ETALON_F, init_shift=0.0):
    avg = float(np.mean(alpha))
    scale = (10.0 ** (-np.floor(np.log10(abs(avg))))
             if (abs(avg) < 1e-4 and avg != 0) else 1.0)
    act, fx, lk, t0, lb, ub, bm = fitter.setup_fit_parameters(
        props, init_shift, [init_shift, 1.0], step_limit=step_limit,
        return_bounds=True)
    out, diag = fitter.execute_varpro_fit(
        vp, alpha * scale, np.ones(len(vp)), act, fx, lk, t0, lb, ub, poly_order,
        etalon_f, center, 1.0, props, 25.0, 0.0, False,
        allow_negative_gas=True, return_diagnostics=True, bounds_meta=bm)
    opt_sh, opt_sq, c_gas, _, eamp, _, perr = out
    scd, err = {}, {}
    for i, name in enumerate(eng.gas_list):
        sf = eng.scaling_factors[name] * scale
        mult = eng.multipliers.get(name, 1.0)
        scd[name] = float(c_gas[i] / sf * mult)
        err[name] = float(perr[i] / sf * mult)
    return dict(scd=scd, err=err, shift=float(opt_sh[0]), squeeze=float(opt_sq[0]),
                etalon_amp=float(eamp) / scale, diag=diag)


# figure style helpers (replicate apply_figure_style and panel_letter and META_GREY)
META_GREY = "#6d6d6d"

def apply_figure_style(sizes=(8, 7, 6)):
    mpl.rcParams.update({
        "font.size": sizes[2],
        "axes.titlesize": sizes[1],
        "axes.labelsize": sizes[2],
        "xtick.labelsize": sizes[2],
        "ytick.labelsize": sizes[2],
        "legend.fontsize": sizes[2],
        "figure.dpi": 100,
    })

def panel_letter(ax, letter, x=-0.13, y=1.03):
    ax.text(x, y, f"({letter})", transform=ax.transAxes,
            fontsize=8, fontweight="bold", va="top", ha="left")


apply_figure_style(sizes=(8, 7, 6))
FOCAL, C2, C3 = "#1f4e9c", "#c0561f", "#1a7f6b"

# Build engine and setup
gases = ("NO2", "CHOCHO", "H2O")
with contextlib.redirect_stdout(io.StringIO()):
    eng, wave = build_engine(gases)

vp, center = window(wave)
px = vp.astype(int)
wl = wave[px]
K = 1e7
DISP = float(np.median(np.diff(wl)))

# Setup output directory
OUT = os.path.join(os.getcwd(), "h1_synth")
os.makedirs(OUT, exist_ok=True)
for sub in ("spec", "xs", "out"):
    os.makedirs(os.path.join(OUT, sub), exist_ok=True)

# Save Calib and flat reference
np.savetxt(os.path.join(OUT, f"Calib_synth_{px[0]}-{px[-1]}px.txt"), wl, fmt="%.6f")
with open(os.path.join(OUT, "reference_flat.asc"), "w") as f:
    for w in wl:
        f.write(f"{w:.6f}\t{1.0:.7e}\n")

# Save cross sections
xs_paths = {}
for name, fn in REF_FILES:
    arr = np.loadtxt(os.path.join(REFDIR, fn), comments="#")
    p = os.path.join(OUT, "xs", f"{name}_augur-conv.xs")
    np.savetxt(p, np.column_stack([wave, arr]), fmt="%.6f\t%.6e")
    xs_paths[name] = p.replace("\\", "/")

# Generate synthetic spectra
cases, rows = [], []
scds_true = companion_scds(eng, gases, SCD_MID)
rng = np.random.default_rng(20260919)
for sh in (0.0, -1.96, 2.0, -4.0):
    a_ = synthesize(eng, vp, center, scds_true, sh, 1.002)
    cases.append(("noisefree", sh, 0, a_))
for i in range(30):
    a_ = synthesize(eng, vp, center, scds_true, FIELD_SHIFT, 1.002, NOISE_MEASURED, rng)
    cases.append(("noisy", FIELD_SHIFT, i, a_))

specfile = os.path.join(OUT, "spec", "synth.asc")
with open(specfile, "w") as f:
    for k, (kind, sh, idx, alpha) in enumerate(cases):
        I = np.exp(-K * alpha)
        dt = 1.0 + k / 3600.0
        f.write(f"01/06/2026 {dt:.8f} " + " ".join(f"{v:.7e}" for v in I) + "\n")
        rows.append(dict(record=k + 1, kind=kind, true_shift_px=sh, real=idx))
meta = pd.DataFrame(rows)
meta.to_csv(os.path.join(OUT, "cases.csv"), index=False)

# Build QDOAS XML project
XV = r"C:\GHL\CAESAR\diagnostics\qdoas_crossval_2026-09"
COLD = os.path.join(XV, "qdoas_input", "cold", "Cold.xml")
tree_xml = ET.parse(COLD)
root = tree_xml.getroot()

pns = [p for p in root.findall("project") if p.get("name") == "PNs"][0]
SH_NM = 6.0 * DISP

new = ET.Element("qdoas")
ET.SubElement(new, "paths")
sym = ET.SubElement(new, "symbols")
for g in gases:
    ET.SubElement(sym, "symbol", {"name": g, "descr": ""})

proj = copy.deepcopy(pns)
proj.set("name", "SynthPNs")
asc = proj.find("instrumental").find("ascii")
asc.set("size", str(len(px)))
asc.set("calib", os.path.join(OUT, f"Calib_synth_{px[0]}-{px[-1]}px.txt").replace("\\", "/"))
o = proj.find("output")
o.set("path", os.path.join(OUT, "out", "synth_").replace("\\", "/"))
o.set("fileFormat", ".ASC")

w = proj.find("analysis_window")
w.set("min", f"{wl[0]:.3f}")
w.set("max", f"{wl[-1]:.3f}")
w.set("lambda0", f"{wl[len(wl)//2]:.3f}")
w.find("files").set("refone", os.path.join(OUT, "reference_flat.asc").replace("\\", "/"))
w.find("linear").set("xpoly", "3")
for cs in w.find("cross_sections"):
    cs.set("csfile", xs_paths[cs.get("sym")])
    cs.set("cstype", "interp")
ss = w.find("shift_stretches")[0]
ss.set("shmin", f"{-SH_NM:.3e}")
ss.set("shmax", f"{SH_NM:.3e}")
ss.set("shfit", "true")
ss.set("stfit", "1st")
ss.set("shstr", "true")
ss.set("ststr", "true")
ss.set("errstr", "true")
new.append(proj)
XMLP = os.path.join(OUT, "synth_project.xml")
ET.ElementTree(new).write(XMLP, encoding="utf-8", xml_declaration=True)

# Run QDOAS
exe = r"C:\Users\User\miniforge3\envs\qdoas\Library\bin\doas_cl.exe"
subprocess.run([exe, "-c", XMLP, "-a", "SynthPNs", "-f", specfile],
               capture_output=True)

# Load QDOAS output
ASC = os.path.join(OUT, "out", "synth_.ASC")
raw = open(ASC, encoding="utf-8", errors="replace").read().splitlines()
hdr_i = max(i for i, l in enumerate(raw) if l.startswith("#") or "SlntCol" in l)
q = pd.read_csv(ASC, sep="\t", skiprows=hdr_i, engine="python")
q.columns = [c.strip().lstrip("#").strip() for c in q.columns]

# Run Augur
fitter = DoasFitter(eng)
props = props_for(gases)
aug = []
for kind, sh, idx, alpha in cases:
    r = recover(eng, fitter, props, vp, center, alpha)
    aug.append(dict(no2=r["scd"]["NO2"], err=r["err"]["NO2"], shift=r["shift"], sq=r["squeeze"]))
A = pd.DataFrame(aug)

Q = pd.DataFrame({
    "no2": q["NO2.SlCol(NO2)"].values / K,
    "err": q["NO2.SlErr(NO2)"].values / K,
    "shift_px": -q["NO2.Shift(CHOCHO)"].values / DISP,
    "stretch": q["NO2.Stretch(CHOCHO)1"].values,
    "rms": q["NO2.RMS"].values})

C = pd.concat([meta.reset_index(drop=True), A.add_prefix("aug_"), Q.add_prefix("qd_")], axis=1)
C["aug_relerr"] = (C.aug_no2 - SCD_MID) / SCD_MID
C["qd_relerr"] = (C.qd_no2 - SCD_MID) / SCD_MID
C["aug_dshift"] = C.aug_shift - C.true_shift_px
C["qd_dshift"] = C.qd_shift_px - C.true_shift_px

nf = C[C.kind == "noisefree"]
ny = C[C.kind == "noisy"]
t = SCD_MID
lim = [0.988, 1.012]
RES = 1e-4

# Plot
plt.close("all")
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.1, 3.0))
s = nf.sort_values("true_shift_px")
qd_abs = np.abs(s.qd_relerr.values)
det = qd_abs >= RES
ax1.plot(s.true_shift_px, np.abs(s.aug_relerr) + 1e-17, "o-", color=FOCAL, ms=4.5, lw=1.4,
         label="Augur (VP, analytic Jacobian)")
ax1.plot(s.true_shift_px[det], qd_abs[det], "s", color=C2, ms=5, label="QDOAS (Marquardt–SVD)")
ax1.errorbar(s.true_shift_px[~det], np.full((~det).sum(), RES),
             yerr=[np.full((~det).sum(), RES*0.55), np.zeros((~det).sum())],
             fmt="v", mfc="none", mec=C2, ecolor=C2, ms=5, lw=1.0, capsize=0,
             label="QDOAS, below output resolution")
ax1.axhline(RES, color=META_GREY, lw=0.8, ls=":")
ax1.text(2.1, 1.25e-4, "QDOAS output resolution", ha="right", va="bottom", fontsize=6, color=META_GREY)
ax1.set_yscale("log")
ax1.set_ylim(3e-17, 3e-2)
ax1.set_yticks([1e-15, 1e-12, 1e-9, 1e-6, 1e-3])
ax1.set_xlabel("true reference shift (px)")
ax1.set_ylabel("|NO$_2$ error| vs known truth")
ax1.set_title("Noise-free: the codes diverge only where\nthe shift operator is applied")
ax1.annotate("truth built with Augur's\ninterpolator — favours Augur", xy=(-1.96, 7e-16), xytext=(-4.1, 2.5e-11),
             fontsize=6, color=META_GREY, arrowprops=dict(arrowstyle="-", lw=0.6, color=META_GREY))
ax1.legend(frameon=False, loc="lower center", fontsize=6, handlelength=1.5, labelspacing=0.22,
           bbox_to_anchor=(0.52, -0.02))
ax1.margins(0.05)

ax2.scatter(ny.aug_no2 / t, ny.qd_no2 / t, s=16, color=FOCAL, alpha=0.75, lw=0)
ax2.plot(lim, lim, "-", color=META_GREY, lw=0.9)
ax2.axhline(1.0, color=C3, lw=0.8, ls="--")
ax2.axvline(1.0, color=C3, lw=0.8, ls="--")
ax2.set_xlim(lim)
ax2.set_ylim(lim)
ax2.set_xlabel("Augur NO$_2$ / truth")
ax2.set_ylabel("QDOAS NO$_2$ / truth")
ax2.set_title("With measured noise, 30 realizations:\nequal precision, 0.16 % mean offset")
ax2.text(0.9885, 1.0105, f"r = {np.corrcoef(ny.aug_no2, ny.qd_no2)[0,1]:.3f}\n"
         f"scatter: {ny.aug_no2.std(ddof=1)/t*100:.2f} % / {ny.qd_no2.std(ddof=1)/t*100:.2f} %",
         fontsize=6, va="top")
ax2.text(1.0115, 1.0005, "truth", fontsize=6, color=C3, ha="right", va="bottom")
for ax, L in zip((ax1, ax2), "ab"):
    panel_letter(ax, L)
fig.tight_layout(pad=0.8, w_pad=1.6)
fig.savefig("h1_qdoas_synthetic.png", dpi=300, bbox_inches="tight")