"""
Hot FWHM + R analysis
- FWHM: roi2 Hg lamp CSV  (C:\LGH\Wave length callibration\raw\...)
- Wavelength: existing calibration txt (D:\CAESAR hot\roi1 & roi2)
- R: raw .mat scans, He/ZA flags 510-513 / 500-503
"""
import numpy as np, pandas as pd, scipy.io as sio, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.optimize import curve_fit
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
HG_CSV  = r"C:\LGH\Wave length callibration\raw\2026 2월 03 09_38_35_cw450_Hglamp-Roi-2.csv"
CAL_R1  = r"D:\CAESAR hot\roi1\Calib_20260403_Hg_400-499nm(roi1).txt"
CAL_R2  = r"D:\CAESAR hot\roi2\Calib_20260403_Hg_400-499nm(roi2).txt"
MAT_DIR = r"D:\CAESAR hot\2026-05"
OUT_PNG = r"D:\CAESAR hot\FWHM_and_R_summary_Hot.png"

# ── Wavelength calibration ─────────────────────────────────────────────────
def load_calib(path):
    """Load wavelength calibration txt (skip comment lines starting with #)"""
    wl = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    wl.append(float(line))
                except ValueError:
                    pass
    return np.array(wl[:2048])   # first 2048 values

wl_r1 = load_calib(CAL_R1)   # roi1 wavelengths
wl_r2 = load_calib(CAL_R2)   # roi2 wavelengths (Hg lamp is roi2)

# ── Load Hg lamp CSV (roi2) ────────────────────────────────────────────────
df_hg  = pd.read_csv(HG_CSV)
df_hg.columns = [c.strip() for c in df_hg.columns]
hg_wide = df_hg.pivot_table(index="Frame", columns="Column",
                              values="Intensity", aggfunc="mean")
hg = hg_wide.mean(axis=0).values.astype(float)   # mean over frames

# ── Gaussian fit ──────────────────────────────────────────────────────────
def gauss(x, A, mu, sig, bg):
    return A * np.exp(-0.5*((x-mu)/sig)**2) + bg

def fit_peak(spectrum, pk_px, wl_arr):
    ctx = spectrum[max(0,pk_px-200):min(len(spectrum),pk_px+201)]
    baseline  = float(np.percentile(ctx, 10))
    half_lvl  = baseline + (spectrum[pk_px] - baseline)*0.5
    l, r = pk_px, pk_px
    while l > 0 and spectrum[l] > half_lvl: l -= 1
    while r < len(spectrum)-1 and spectrum[r] > half_lvl: r += 1
    hw  = max(r - pk_px, pk_px - l, 1)
    win = max(15, min(300, int(hw * 1.5)))
    s, e = max(0, pk_px-win), min(len(spectrum), pk_px+win+1)
    xd  = np.arange(s, e, dtype=float)
    yd  = spectrum[s:e]
    A0  = spectrum[pk_px] - baseline
    sg0 = max(0.3, hw/2.3548)
    try:
        popt, _ = curve_fit(gauss, xd, yd,
                            p0=[A0, float(pk_px), sg0, baseline],
                            bounds=([0, float(s), 0.1, -np.inf],
                                    [np.inf, float(e), float(win), np.inf]),
                            maxfev=10000)
        A, mu, sig, bg = popt
        fwhm_px = 2.3548 * abs(sig)
        mu_i    = int(np.clip(round(mu), 1, len(wl_arr)-2))
        disp    = (wl_arr[mu_i+1] - wl_arr[mu_i-1]) / 2.0
        return dict(mu=mu, sig_px=abs(sig), sig_nm=abs(sig)*disp,
                    fwhm_px=fwhm_px, fwhm_nm=fwhm_px*disp,
                    A=A, bg=bg, wl_center=wl_arr[mu_i],
                    xd=xd, yd=yd, popt=popt)
    except Exception:
        return None

# roi2 Hg peaks (approx px from 0.049nm/px dispersion, 400nm at px~0)
# 404nm -> px~82,  436nm -> px~738,  maybe also 435nm
# Find peaks automatically
from scipy.signal import find_peaks
peaks_idx, props = find_peaks(hg, height=np.percentile(hg,95),
                               prominence=1000, distance=50)
print(f"Auto-detected peaks at pixels: {peaks_idx} (wl: {wl_r2[peaks_idx].round(2)} nm)")

fits = []
for pk in peaks_idx:
    r = fit_peak(hg, pk, wl_r2)
    if r is not None:
        fits.append(r)
        print(f"  px={pk}  wl={r['wl_center']:.3f}nm  "
              f"FWHM={r['fwhm_nm']:.4f}nm ({r['fwhm_px']:.2f}px)  "
              f"sigma={r['sig_nm']:.4f}nm")

if fits:
    fwhm_mean = np.mean([f["fwhm_nm"] for f in fits])
    sig_mean  = np.mean([f["sig_nm"]  for f in fits])
else:
    fwhm_mean, sig_mean = np.nan, np.nan

print()
print("="*60)
print("  FWHM / Sigma  (Hot roi2 Hg lamp)")
print("="*60)
print(f"  Mean FWHM  = {fwhm_mean:.4f} nm")
print(f"  Mean sigma = {sig_mean:.4f} nm")
print()

# ── R calculation from raw Hot .mat files ─────────────────────────────────
# Collect all .mat files
mat_files = sorted(Path(MAT_DIR).glob("*.mat"))
print(f"Found {len(mat_files)} .mat files in {MAT_DIR}")

# HE flags: 510-513,  ZA flags: 500-503
HE_FLAGS = {510, 511, 512, 513}
ZA_FLAGS = {500, 501, 502, 503}

he_spectra_ch1 = []   # roi1 (ch1)
za_spectra_ch1 = []
he_spectra_ch2 = []   # roi2 (ch2)
za_spectra_ch2 = []

for mf in mat_files:
    try:
        mat  = sio.loadmat(str(mf))
        ch1  = mat["ch1"]            # (N, 2048)
        flags= mat["flag"].flatten().astype(int)
        tc1  = mat.get("tempcell1",  np.full((len(flags),1), 25.0)).flatten()
        pc1  = mat.get("presscell1", np.full((len(flags),1), 1013.25)).flatten()

        # Conversion factors (verified from raw values in 2026-05-18-001.mat):
        #   presscell1: raw counts × 0.6895 → mbar  (raw ~1400 → ~965 mbar)
        #   tempcell1:  raw counts ÷ 100   → °C     (raw ~3000 → ~30°C)
        P_SCALE = 0.01 * 6894.73326 / 100.0   # 0.6895 mbar/count
        ch2 = mat["ch2"]
        pc2 = mat.get("presscell2", pc1).flatten()
        tc2 = mat.get("tempcell2",  tc1).flatten()

        for fv in HE_FLAGS:
            idx = np.where(flags == fv)[0]
            if len(idx):
                t1 = float(np.median(tc1[idx])) / 100.0
                p1 = float(np.median(pc1[idx])) * P_SCALE
                he_spectra_ch1.append((np.median(ch1[idx,:], axis=0).astype(float), t1, p1))
                # ch2: use ch2 signal; if presscell2 is all-zero fall back to ch1 HK
                p2_raw = float(np.median(pc2[idx]))
                t2_raw = float(np.median(tc2[idx]))
                p2 = (p2_raw * P_SCALE) if p2_raw > 10 else p1
                t2 = (t2_raw / 100.0)  if t2_raw > 10 else t1
                he_spectra_ch2.append((np.median(ch2[idx,:], axis=0).astype(float), t2, p2))

        for fv in ZA_FLAGS:
            idx = np.where(flags == fv)[0]
            if len(idx):
                t1 = float(np.median(tc1[idx])) / 100.0
                p1 = float(np.median(pc1[idx])) * P_SCALE
                za_spectra_ch1.append((np.median(ch1[idx,:], axis=0).astype(float), t1, p1))
                p2_raw = float(np.median(pc2[idx]))
                t2_raw = float(np.median(tc2[idx]))
                p2 = (p2_raw * P_SCALE) if p2_raw > 10 else p1
                t2 = (t2_raw / 100.0)  if t2_raw > 10 else t1
                za_spectra_ch2.append((np.median(ch2[idx,:], axis=0).astype(float), t2, p2))
    except Exception as ex:
        print(f"  Skip {mf.name}: {ex}")

print(f"ch1 He: {len(he_spectra_ch1)}  ZA: {len(za_spectra_ch1)}")
print(f"ch2 He: {len(he_spectra_ch2)}  ZA: {len(za_spectra_ch2)}")

if he_spectra_ch1:
    print(f"ch1 He: T={np.mean([x[1] for x in he_spectra_ch1]):.1f}C  "
          f"P={np.mean([x[2] for x in he_spectra_ch1]):.1f} mbar")
if za_spectra_ch1:
    print(f"ch1 ZA: T={np.mean([x[1] for x in za_spectra_ch1]):.1f}C  "
          f"P={np.mean([x[2] for x in za_spectra_ch1]):.1f} mbar")
if he_spectra_ch2:
    print(f"ch2 He: T={np.mean([x[1] for x in he_spectra_ch2]):.1f}C  "
          f"P={np.mean([x[2] for x in he_spectra_ch2]):.1f} mbar")
if za_spectra_ch2:
    print(f"ch2 ZA: T={np.mean([x[1] for x in za_spectra_ch2]):.1f}C  "
          f"P={np.mean([x[2] for x in za_spectra_ch2]):.1f} mbar")
print()

# ── Rayleigh physics (same as reflectance_calc.py) ─────────────────────────
def alpha_rayleigh(wave_nm, temp_c, press_mbar, gas="zero_air"):
    wave_nm = np.asarray(wave_nm, dtype=float)
    N = 2.68678e19 * (press_mbar / 1013.25) * (273.15 / (temp_c + 273.15))
    v = 1e7 / wave_nm
    if gas in ("zero_air","air"):
        A_n2,B_n2,C_n2 = 5677.465, 318.81874e12, 14.4e9
        n_n2 = 1.0 + (A_n2 + B_n2/(C_n2-v**2))*1e-8
        Fk_n2= 1.034 + 3.17e-12*v
        s_n2 = Fk_n2*(24*np.pi**3*v**4/N**2)*((n_n2**2-1)/(n_n2**2+2))**2
        A_o2,B_o2,C_o2 = 20564.8, 2.480899e13, 4.09e9
        n_o2 = 1.0 + (A_o2 + B_o2/(C_o2-v**2))*1e-8
        Fk_o2= 1.09+1.385e-11*v**2+1.448e-20*v**4
        s_o2 = Fk_o2*(24*np.pi**3*v**4/N**2)*((n_o2**2-1)/(n_o2**2+2))**2
        return (0.79*s_n2+0.21*s_o2)*N
    else:  # helium
        A_he,B_he,C_he = 2283.0, 1.8102e13, 1.5342e10
        n_he = 1.0 + (A_he + B_he/(C_he-v**2))*1e-8
        return (24*np.pi**3*v**4/N**2)*((n_he**2-1)/(n_he**2+2))**2 * N

# ── Compute R per (He, ZA) pair ────────────────────────────────────────────
d_cav = 51.8   # cm

def compute_R_series(he_list, za_list, wl_arr, gas_he="helium", gas_za="zero_air"):
    results = []
    n = min(len(he_list), len(za_list))
    for i in range(n):
        i_he, t_he_i, p_he_i = he_list[i]
        i_za, t_za_i, p_za_i = za_list[i]
        a_he = alpha_rayleigh(wl_arr, t_he_i, p_he_i, gas_he)
        a_za = alpha_rayleigh(wl_arr, t_za_i, p_za_i, gas_za)
        i_he_safe = np.where(np.abs(i_he) > 1.0, i_he, 1.0)
        ratio = i_za / i_he_safe
        with np.errstate(divide="ignore", invalid="ignore"):
            omr_d = (ratio * a_za - a_he) / (1.0 - ratio)
        R_curve = np.clip(1.0 - omr_d * d_cav, 0.0, 1.0)
        results.append(R_curve)
    return np.vstack(results) if results else np.full((1, len(wl_arr)), np.nan)

R_all_ch1 = compute_R_series(he_spectra_ch1, za_spectra_ch1, wl_r1)
R_all_ch2 = compute_R_series(he_spectra_ch2, za_spectra_ch2, wl_r2)
print(f"R curves: ch1={R_all_ch1.shape[0]}  ch2={R_all_ch2.shape[0]}")

def summarize_R(R_all, wl_arr, label, wl_lo=432, wl_hi=480):
    p_lo = int(np.argmin(np.abs(wl_arr - wl_lo)))
    p_hi = int(np.argmin(np.abs(wl_arr - wl_hi)))
    Rv = R_all[:, p_lo:p_hi].copy()
    Rv[(Rv < 0.95)|(Rv >= 1.0)] = np.nan
    R_ts  = np.nanmedian(Rv, axis=1)
    R_wl  = np.nanmedian(R_all, axis=0)
    valid = R_ts[np.isfinite(R_ts)]
    print(f"\n{'='*60}")
    print(f"  R {label}  ({wl_lo}-{wl_hi}nm median)")
    print(f"{'='*60}")
    if len(valid):
        Leff = 51.8e-5 / (1.0 - valid)
        print(f"  R  range  : {valid.min()*100:.4f}% ~ {valid.max()*100:.4f}%")
        print(f"  R  median : {np.median(valid)*100:.4f}%")
        print(f"  Leff med  : {np.median(Leff):.2f} km")
    return R_ts, R_wl, p_lo, p_hi

R_ts1, R_wl1, p_lo1, p_hi1 = summarize_R(R_all_ch1, wl_r1, "roi1 (ch1)")
R_ts2, R_wl2, p_lo2, p_hi2 = summarize_R(R_all_ch2, wl_r2, "roi2 (ch2)")
print()

# ── Figure (4 rows) ────────────────────────────────────────────────────────
COLORS = ["red","royalblue","green","darkorange","purple"]
fig = plt.figure(figsize=(16, 17))
gs  = gridspec.GridSpec(4, 2, hspace=0.52, wspace=0.35,
                        top=0.94, bottom=0.06)

# (A) Full Hg spectrum (roi2)
ax0 = fig.add_subplot(gs[0, :])
ax0.plot(wl_r2, hg, "k-", lw=0.7, alpha=0.65, label="Hg lamp roi2 (60fr avg)")
for res, clr in zip(fits, COLORS):
    xi = np.clip(res["xd"].astype(int), 0, len(wl_r2)-1)
    ax0.plot(wl_r2[xi], gauss(res["xd"], *res["popt"]), color=clr, lw=2.5,
             label=f"{res['wl_center']:.1f}nm: FWHM={res['fwhm_nm']:.3f}nm  sigma={res['sig_nm']:.3f}nm")
    ax0.axvline(res["wl_center"], color=clr, ls="--", alpha=0.3)
ax0.set_xlabel("Wavelength (nm)"); ax0.set_ylabel("Counts")
ax0.set_title("Hot Hg lamp (roi2)  -  FWHM and sigma measurement",
              fontweight="bold", fontsize=13)
ax0.legend(fontsize=9); ax0.set_xlim(wl_r2[0], wl_r2[-1])

# (B) Peak1 zoom
ax1 = fig.add_subplot(gs[1, 0])
if fits:
    res = fits[0]; xi = np.clip(res["xd"].astype(int), 0, len(wl_r2)-1)
    ax1.plot(wl_r2[xi], hg[xi], "ko-", ms=3, label="data")
    ax1.plot(wl_r2[xi], gauss(res["xd"], *res["popt"]), "r-", lw=2.2, label="Gaussian fit")
    ax1.axhline(res["bg"]+res["A"]/2, color="gray", ls=":", lw=1.2, label="half-max")
    ax1.set_title(f"Peak1 {res['wl_center']:.1f}nm  FWHM={res['fwhm_nm']:.3f}nm  sigma={res['sig_nm']:.3f}nm",
                  fontweight="bold")
    ax1.set_xlabel("Wavelength (nm)"); ax1.set_ylabel("Counts"); ax1.legend()

# (C) Peak2 zoom
ax2 = fig.add_subplot(gs[1, 1])
if len(fits) >= 2:
    res = fits[-1]; xi = np.clip(res["xd"].astype(int), 0, len(wl_r2)-1)
    ax2.plot(wl_r2[xi], hg[xi], "ko-", ms=3, label="data")
    ax2.plot(wl_r2[xi], gauss(res["xd"], *res["popt"]), "royalblue", lw=2.2, label="Gaussian fit")
    ax2.axhline(res["bg"]+res["A"]/2, color="gray", ls=":", lw=1.2, label="half-max")
    ax2.set_title(f"Peak2 {res['wl_center']:.1f}nm  FWHM={res['fwhm_nm']:.3f}nm  sigma={res['sig_nm']:.3f}nm",
                  fontweight="bold")
    ax2.set_xlabel("Wavelength (nm)"); ax2.set_ylabel("Counts"); ax2.legend()

# ── R curves ──────────────────────────────────────────────────────────────
def plot_R_wl(ax, R_all, wl_arr, p_lo, p_hi, label, color):
    Rc = np.nanmedian(R_all, axis=0).copy()
    Rc[(Rc < 0.95)|(Rc >= 1.0)|~np.isfinite(Rc)] = np.nan
    med_r = float(np.nanmedian(Rc[p_lo:p_hi]))
    ax.plot(wl_arr, Rc*100, color=color, lw=1.2)
    if np.isfinite(med_r) and med_r < 1.0:
        ax.axhline(med_r*100, color="crimson", ls="--", lw=1.8,
                   label=f"median {med_r*100:.4f}%  Leff={51.8e-5/(1-med_r):.2f} km")
    ax.set_xlabel("Wavelength (nm)"); ax.set_ylabel("R (%)")
    ax.set_title(f"Hot R curve  ({label})", fontweight="bold")
    ax.set_xlim(wl_arr[0], wl_arr[-1]); ax.set_ylim(99.0, 100.05); ax.legend()

def plot_R_ts(ax, R_ts, label, color):
    v = np.isfinite(R_ts)
    ax.plot(np.arange(np.sum(v)), R_ts[v]*100, "o-", color=color, ms=5, lw=1.5)
    ax.set_xlabel("He/ZA pair index"); ax.set_ylabel("R median (%)")
    ax.set_title(f"Hot R per He/ZA pair  ({label}, 432-480nm)", fontweight="bold")
    valid = R_ts[v]
    if len(valid):
        lo, hi = valid.min()*100, valid.max()*100
        m = max((hi-lo)*0.5, 0.005)
        ax.set_ylim(lo-m, hi+m)

# (D) roi1 R wavelength
ax3 = fig.add_subplot(gs[2, 0])
plot_R_wl(ax3, R_all_ch1, wl_r1, p_lo1, p_hi1, "roi1 ch1", "navy")

# (E) roi2 R wavelength
ax4 = fig.add_subplot(gs[2, 1])
plot_R_wl(ax4, R_all_ch2, wl_r2, p_lo2, p_hi2, "roi2 ch2", "darkgreen")

# (F) roi1 R time series
ax5 = fig.add_subplot(gs[3, 0])
plot_R_ts(ax5, R_ts1, "roi1 ch1", "navy")

# (G) roi2 R time series
ax6 = fig.add_subplot(gs[3, 1])
plot_R_ts(ax6, R_ts2, "roi2 ch2", "darkgreen")

fig.text(0.5, 0.015,
    "sigma (s) = FWHM / 2.3548  |  "
    "Reference cross-sections must be convolved with Gaussian(sigma) "
    "to match the Hot spectrometer line shape.",
    ha="center", fontsize=9.5, color="#222",
    bbox=dict(boxstyle="round,pad=0.4", fc="lightyellow", ec="gray", alpha=0.9))

plt.savefig(OUT_PNG, dpi=130, bbox_inches="tight")
print(f"Saved: {OUT_PNG}")
