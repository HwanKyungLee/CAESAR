import numpy as np, pandas as pd, scipy.io as sio, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.optimize import curve_fit

# 1. 파장 캘리브레이션
px = np.arange(2048)
wl = 399.216 + 0.05139*px - 2.54e-6*px**2

# 2. Hg lamp CSV
HG_CSV  = r"D:\CAESAR cold\2026 5월 06 10_46_46.csv"
RS_MAT  = r"D:\CAESAR cold\2026-05\Rs\Rs_2026-05-18.mat"
OUT_PNG = r"D:\CAESAR cold\FWHM_and_R_summary.png"

df_hg  = pd.read_csv(HG_CSV)
df_hg.columns = [c.strip() for c in df_hg.columns]
# Long-format: ROI, Frame, Row, Column, Intensity  →  pivot to (Frame x Column)
hg_wide = df_hg.pivot_table(index="Frame", columns="Column",
                             values="Intensity", aggfunc="mean")
hg = hg_wide.mean(axis=0).values.astype(float)   # mean over frames

# 3. Gaussian fit helper
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
    win = max(20, min(300, int(hw * 1.5)))
    s, e = max(0, pk_px-win), min(len(spectrum), pk_px+win+1)
    xd = np.arange(s, e, dtype=float)
    yd = spectrum[s:e]
    A0  = spectrum[pk_px] - baseline
    sg0 = max(0.5, hw/2.3548)
    try:
        popt, _ = curve_fit(gauss, xd, yd,
                            p0=[A0, float(pk_px), sg0, baseline],
                            bounds=([0, float(s), 0.2, -np.inf],
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

r1 = fit_peak(hg, 107, wl)
r2 = fit_peak(hg, 741, wl)

# ── 콘솔 출력 ─────────────────────────────────────────────────────────────────
print("="*62)
print("  FWHM / Sigma  (Cold Hg lamp, 2026-05-06)")
print("="*62)
for tag, res in [("Peak1 (404nm, px107)", r1), ("Peak2 (436nm, px741)", r2)]:
    if res:
        print(f"  {tag}")
        print(f"    Center wl : {res['wl_center']:.3f} nm  (px {res['mu']:.1f})")
        print(f"    FWHM      : {res['fwhm_nm']:.3f} nm  ({res['fwhm_px']:.1f} px)")
        print(f"    Sigma     : {res['sig_nm']:.3f} nm  ({res['sig_px']:.1f} px)")
        print()

fwhm_mean = np.mean([r1["fwhm_nm"], r2["fwhm_nm"]])
sig_mean  = np.mean([r1["sig_nm"],  r2["sig_nm"]])
print(f"  Mean FWHM = {fwhm_mean:.3f} nm,  Mean sigma = {sig_mean:.3f} nm")
print()

# 4. R data
mat    = sio.loadmat(RS_MAT)
R_all  = mat["Rs_merged1"]   # (2048, 18)
doy_R  = mat["doy_R"].flatten()
p_lo, p_hi = 650, 1720
R_cen  = np.nanmedian(R_all[p_lo:p_hi, :], axis=0)   # (18,)

print("="*62)
print("  R (Cold cavity, 2026-05-18, median 432-480nm)")
print("="*62)
for i, rv in enumerate(R_cen):
    if np.isfinite(rv):
        leff = 51.8e-5 / (1.0 - rv)
        print(f"  [{i:2d}] DOY={doy_R[i]:.4f}  R={rv*100:.4f}%  Leff={leff:.2f} km")
print()
R_valid    = R_cen[np.isfinite(R_cen)]
leff_valid = 51.8e-5 / (1.0 - R_valid)
print(f"  R    range  : {R_valid.min()*100:.4f}% ~ {R_valid.max()*100:.4f}%")
print(f"  R    median : {np.median(R_valid)*100:.4f}%")
print(f"  Leff median : {np.median(leff_valid):.2f} km")
print()

# 5. Figure -------------------------------------------------------------------
fig = plt.figure(figsize=(16, 13))
gs  = gridspec.GridSpec(3, 2, hspace=0.52, wspace=0.35,
                        top=0.93, bottom=0.09)

# (A) full Hg spectrum
ax0 = fig.add_subplot(gs[0, :])
ax0.plot(wl, hg, "k-", lw=0.7, alpha=0.65, label="Hg lamp (60 fr avg)")
for res, clr, nm in [(r1,"red","404"), (r2,"royalblue","436")]:
    if res:
        xi = np.clip(res["xd"].astype(int), 0, 2047)
        ax0.plot(wl[xi], gauss(res["xd"], *res["popt"]),
                 color=clr, lw=2.5,
                 label=f"{nm}nm:  FWHM={res['fwhm_nm']:.2f}nm  sigma={res['sig_nm']:.2f}nm")
        ax0.axvline(res["wl_center"], color=clr, ls="--", alpha=0.35)
ax0.set_xlabel("Wavelength (nm)"); ax0.set_ylabel("Counts")
ax0.set_title("Cold Hg lamp  -  FWHM and sigma measurement", fontweight="bold", fontsize=13)
ax0.legend(fontsize=10); ax0.set_xlim(399, 494)

# (B) Peak1 zoom
ax1 = fig.add_subplot(gs[1, 0])
if r1:
    xi = np.clip(r1["xd"].astype(int), 0, 2047)
    ax1.plot(wl[xi], hg[xi], "ko-", ms=3.5, label="data")
    ax1.plot(wl[xi], gauss(r1["xd"], *r1["popt"]),
             "r-", lw=2.2, label="Gaussian fit")
    ax1.axhline(r1["bg"]+r1["A"]/2, color="gray", ls=":", lw=1.2, label="half-max")
    ax1.set_title(f"Peak1 404nm  FWHM={r1['fwhm_nm']:.2f}nm  sigma={r1['sig_nm']:.2f}nm",
                  fontweight="bold")
    ax1.set_xlabel("Wavelength (nm)"); ax1.set_ylabel("Counts"); ax1.legend()

# (C) Peak2 zoom
ax2 = fig.add_subplot(gs[1, 1])
if r2:
    xi = np.clip(r2["xd"].astype(int), 0, 2047)
    ax2.plot(wl[xi], hg[xi], "ko-", ms=3.5, label="data")
    ax2.plot(wl[xi], gauss(r2["xd"], *r2["popt"]),
             "royalblue", lw=2.2, label="Gaussian fit")
    ax2.axhline(r2["bg"]+r2["A"]/2, color="gray", ls=":", lw=1.2, label="half-max")
    ax2.set_title(f"Peak2 436nm  FWHM={r2['fwhm_nm']:.2f}nm  sigma={r2['sig_nm']:.2f}nm",
                  fontweight="bold")
    ax2.set_xlabel("Wavelength (nm)"); ax2.set_ylabel("Counts"); ax2.legend()

# (D) R wavelength curve
ax3 = fig.add_subplot(gs[2, 0])
t0  = int(np.where(np.isfinite(R_cen))[0][0])
Rc  = R_all[:, t0].copy()
Rc[(Rc < 0.95)|(Rc > 1.0)|~np.isfinite(Rc)] = np.nan
med_r = float(np.nanmedian(Rc[p_lo:p_hi]))
ax3.plot(wl, Rc*100, color="navy", lw=1.2)
ax3.axhline(med_r*100, color="crimson", ls="--", lw=1.8,
            label=f"median {med_r*100:.4f}%  Leff={51.8e-5/(1-med_r):.2f} km")
ax3.set_xlabel("Wavelength (nm)"); ax3.set_ylabel("R (%)")
ax3.set_title(f"Cold R curve  (DOY={doy_R[t0]:.4f})", fontweight="bold")
ax3.set_xlim(399, 494); ax3.set_ylim(99.88, 100.05); ax3.legend()

# (E) R time series
ax4 = fig.add_subplot(gs[2, 1])
valid_t = np.isfinite(R_cen)
t_hr = (doy_R[:len(R_cen)][valid_t] - np.floor(doy_R[0])) * 24
ax4.plot(t_hr, R_cen[valid_t]*100, "o-", color="navy", ms=6, lw=1.8)
ax4.set_xlabel("UTC hours on DOY 138"); ax4.set_ylabel("R median (%)")
ax4.set_title("Cold R time series  (2026-05-18, 432-480nm median)", fontweight="bold")
ax4.set_ylim(99.98, 100.01)

# bottom annotation
fig.text(0.5, 0.015,
    "sigma (s) = FWHM / 2.3548  |  "
    "Reference cross-sections must be convolved with Gaussian(sigma) "
    "so they match the instrument line shape the spectrometer actually measures.",
    ha="center", fontsize=9.5, color="#222",
    bbox=dict(boxstyle="round,pad=0.4", fc="lightyellow", ec="gray", alpha=0.9))

plt.savefig(OUT_PNG, dpi=130, bbox_inches="tight")
print(f"Saved: {OUT_PNG}")
