"""
diagnostics/fwhm_r_check.py
============================
Cold / Hot 두 채널의 FWHM(ILS) 측정 + R 진단 스크립트.

cold_fwhm_r_check.py 와 hot_fwhm_r_check.py 를 하나로 병합.
공유 헬퍼(gauss, fit_peak)는 한 번만 정의.
Rayleigh 물리는 core.physics.RayleighPhysics 를 사용(중복 제거).

사용법:
    python diagnostics/fwhm_r_check.py --mode cold
    python diagnostics/fwhm_r_check.py --mode hot
"""
import argparse
import sys
import numpy as np
import pandas as pd
import scipy.io as sio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.optimize import curve_fit
from scipy.signal import find_peaks
from pathlib import Path

# Rayleigh physics → 공용 모듈에서 가져옴 (중복 제거)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.physics import RayleighPhysics


# =============================================================================
# 공유 헬퍼
# =============================================================================

def gauss(x, A, mu, sig, bg):
    return A * np.exp(-0.5 * ((x - mu) / sig) ** 2) + bg


def fit_peak(spectrum, pk_px, wl_arr, win_min=15, win_max=300):
    """스펙트럼에서 pk_px 픽셀 근방 Gaussian 피팅 → FWHM/sigma 반환."""
    ctx      = spectrum[max(0, pk_px - 200):min(len(spectrum), pk_px + 201)]
    baseline = float(np.percentile(ctx, 10))
    half_lvl = baseline + (spectrum[pk_px] - baseline) * 0.5
    l = r = pk_px
    while l > 0 and spectrum[l] > half_lvl:
        l -= 1
    while r < len(spectrum) - 1 and spectrum[r] > half_lvl:
        r += 1
    hw  = max(r - pk_px, pk_px - l, 1)
    win = max(win_min, min(win_max, int(hw * 1.5)))
    s, e = max(0, pk_px - win), min(len(spectrum), pk_px + win + 1)
    xd   = np.arange(s, e, dtype=float)
    yd   = spectrum[s:e]
    A0   = spectrum[pk_px] - baseline
    sg0  = max(0.3, hw / 2.3548)
    try:
        popt, _ = curve_fit(
            gauss, xd, yd,
            p0=[A0, float(pk_px), sg0, baseline],
            bounds=([0, float(s), 0.1, -np.inf],
                    [np.inf, float(e), float(win), np.inf]),
            maxfev=10000,
        )
        A, mu, sig_fit, bg = popt
        fwhm_px = 2.3548 * abs(sig_fit)
        mu_i    = int(np.clip(round(mu), 1, len(wl_arr) - 2))
        disp    = (wl_arr[mu_i + 1] - wl_arr[mu_i - 1]) / 2.0
        return dict(mu=mu, sig_px=abs(sig_fit), sig_nm=abs(sig_fit) * disp,
                    fwhm_px=fwhm_px, fwhm_nm=fwhm_px * disp,
                    A=A, bg=bg, wl_center=wl_arr[mu_i],
                    xd=xd, yd=yd, popt=popt)
    except Exception:
        return None


def load_calib_txt(path):
    """파장 교정 텍스트(# 주석 제외, 숫자 1열) → ndarray."""
    wl = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    wl.append(float(line))
                except ValueError:
                    pass
    return np.array(wl[:2048])


# =============================================================================
# Cold 분석
# =============================================================================

def run_cold():
    """Cold ILS 측정 + Cold R 진단."""
    # ── 경로 ──────────────────────────────────────────────────────────────────
    px    = np.arange(2048)
    wl    = 399.216 + 0.05139 * px - 2.54e-6 * px ** 2
    HG_CSV  = r"D:\CAESAR cold\2026 5월 06 10_46_46.csv"
    RS_MAT  = r"D:\CAESAR cold\2026-05\Rs\Rs_2026-05-18.mat"
    OUT_PNG = r"D:\CAESAR cold\FWHM_and_R_summary.png"

    df_hg  = pd.read_csv(HG_CSV)
    df_hg.columns = [c.strip() for c in df_hg.columns]
    hg_wide = df_hg.pivot_table(index="Frame", columns="Column",
                                 values="Intensity", aggfunc="mean")
    hg = hg_wide.mean(axis=0).values.astype(float)

    r1 = fit_peak(hg, 107, wl, win_min=20)
    r2 = fit_peak(hg, 741, wl, win_min=20)

    print("=" * 62)
    print("  FWHM / Sigma  (Cold Hg lamp, 2026-05-06)")
    print("=" * 62)
    for tag, res in [("Peak1 (404nm, px107)", r1), ("Peak2 (436nm, px741)", r2)]:
        if res:
            print(f"  {tag}")
            print(f"    Center wl : {res['wl_center']:.3f} nm  (px {res['mu']:.1f})")
            print(f"    FWHM      : {res['fwhm_nm']:.3f} nm  ({res['fwhm_px']:.1f} px)")
            print(f"    Sigma     : {res['sig_nm']:.3f} nm  ({res['sig_px']:.1f} px)")
            print()

    valid_res = [r for r in (r1, r2) if r is not None]
    if valid_res:
        fwhm_mean = np.mean([r["fwhm_nm"] for r in valid_res])
        sig_mean  = np.mean([r["sig_nm"]  for r in valid_res])
        print(f"  Mean FWHM = {fwhm_mean:.3f} nm,  Mean sigma = {sig_mean:.3f} nm\n")

    # ── R data ────────────────────────────────────────────────────────────────
    mat   = sio.loadmat(RS_MAT)
    R_all = mat["Rs_merged1"]        # (2048, N_scans)
    doy_R = mat["doy_R"].flatten()
    p_lo, p_hi = 650, 1720
    R_cen = np.nanmedian(R_all[p_lo:p_hi, :], axis=0)

    print("=" * 62)
    print("  R (Cold cavity, 2026-05-18, median 432-480nm)")
    print("=" * 62)
    for i, rv in enumerate(R_cen):
        if np.isfinite(rv):
            leff = 51.8e-5 / (1.0 - rv)
            print(f"  [{i:2d}] DOY={doy_R[i]:.4f}  R={rv*100:.4f}%  Leff={leff:.2f} km")
    print()
    R_valid    = R_cen[np.isfinite(R_cen)]
    leff_valid = 51.8e-5 / (1.0 - R_valid)
    print(f"  R    range  : {R_valid.min()*100:.4f}% ~ {R_valid.max()*100:.4f}%")
    print(f"  R    median : {np.median(R_valid)*100:.4f}%")
    print(f"  Leff median : {np.median(leff_valid):.2f} km\n")

    # ── Figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(16, 13))
    gs  = gridspec.GridSpec(3, 2, hspace=0.52, wspace=0.35, top=0.93, bottom=0.09)

    ax0 = fig.add_subplot(gs[0, :])
    ax0.plot(wl, hg, "k-", lw=0.7, alpha=0.65, label="Hg lamp (60 fr avg)")
    for res, clr, nm in [(r1, "red", "404"), (r2, "royalblue", "436")]:
        if res:
            xi = np.clip(res["xd"].astype(int), 0, 2047)
            ax0.plot(wl[xi], gauss(res["xd"], *res["popt"]), color=clr, lw=2.5,
                     label=f"{nm}nm:  FWHM={res['fwhm_nm']:.2f}nm  sigma={res['sig_nm']:.2f}nm")
            ax0.axvline(res["wl_center"], color=clr, ls="--", alpha=0.35)
    ax0.set_xlabel("Wavelength (nm)"); ax0.set_ylabel("Counts")
    ax0.set_title("Cold Hg lamp  -  FWHM and sigma measurement", fontweight="bold", fontsize=13)
    ax0.legend(fontsize=10); ax0.set_xlim(399, 494)

    for ax_sub, res, clr in [(fig.add_subplot(gs[1, 0]), r1, "red"),
                              (fig.add_subplot(gs[1, 1]), r2, "royalblue")]:
        if res:
            xi = np.clip(res["xd"].astype(int), 0, 2047)
            ax_sub.plot(wl[xi], hg[xi], "ko-", ms=3.5, label="data")
            ax_sub.plot(wl[xi], gauss(res["xd"], *res["popt"]), color=clr, lw=2.2, label="Gaussian fit")
            ax_sub.axhline(res["bg"] + res["A"] / 2, color="gray", ls=":", lw=1.2, label="half-max")
            ax_sub.set_title(f"FWHM={res['fwhm_nm']:.2f}nm  sigma={res['sig_nm']:.2f}nm", fontweight="bold")
            ax_sub.set_xlabel("Wavelength (nm)"); ax_sub.set_ylabel("Counts"); ax_sub.legend()

    ax3 = fig.add_subplot(gs[2, 0])
    t0  = int(np.where(np.isfinite(R_cen))[0][0])
    Rc  = R_all[:, t0].copy()
    Rc[(Rc < 0.95) | (Rc > 1.0) | ~np.isfinite(Rc)] = np.nan
    med_r = float(np.nanmedian(Rc[p_lo:p_hi]))
    ax3.plot(wl, Rc * 100, color="navy", lw=1.2)
    ax3.axhline(med_r * 100, color="crimson", ls="--", lw=1.8,
                label=f"median {med_r*100:.4f}%  Leff={51.8e-5/(1-med_r):.2f} km")
    ax3.set_xlabel("Wavelength (nm)"); ax3.set_ylabel("R (%)")
    ax3.set_title(f"Cold R curve  (DOY={doy_R[t0]:.4f})", fontweight="bold")
    ax3.set_xlim(399, 494); ax3.set_ylim(99.88, 100.05); ax3.legend()

    ax4 = fig.add_subplot(gs[2, 1])
    valid_t = np.isfinite(R_cen)
    t_hr = (doy_R[:len(R_cen)][valid_t] - np.floor(doy_R[0])) * 24
    ax4.plot(t_hr, R_cen[valid_t] * 100, "o-", color="navy", ms=6, lw=1.8)
    ax4.set_xlabel("UTC hours on DOY 138"); ax4.set_ylabel("R median (%)")
    ax4.set_title("Cold R time series  (2026-05-18, 432-480nm median)", fontweight="bold")
    ax4.set_ylim(99.98, 100.01)

    fig.text(0.5, 0.015,
             "sigma (s) = FWHM / 2.3548  |  "
             "Reference cross-sections must be convolved with Gaussian(sigma) "
             "to match the instrument line shape.",
             ha="center", fontsize=9.5, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="lightyellow", ec="gray", alpha=0.9))
    plt.savefig(OUT_PNG, dpi=130, bbox_inches="tight")
    print(f"Saved: {OUT_PNG}")


# =============================================================================
# Hot 분석
# =============================================================================

def run_hot():
    """Hot ILS 측정 + Hot R 진단 (roi1 ch1 & roi2 ch2)."""
    # ── 경로 ──────────────────────────────────────────────────────────────────
    HG_CSV  = r"C:\LGH\Wave length callibration\raw\2026 2월 03 09_38_35_cw450_Hglamp-Roi-2.csv"
    CAL_R1  = r"D:\CAESAR hot\roi1\Calib_20260403_Hg_400-499nm(roi1).txt"
    CAL_R2  = r"D:\CAESAR hot\roi2\Calib_20260403_Hg_400-499nm(roi2).txt"
    MAT_DIR = r"D:\CAESAR hot\2026-05"
    OUT_PNG = r"D:\CAESAR hot\FWHM_and_R_summary_Hot.png"

    wl_r1 = load_calib_txt(CAL_R1)
    wl_r2 = load_calib_txt(CAL_R2)

    df_hg  = pd.read_csv(HG_CSV)
    df_hg.columns = [c.strip() for c in df_hg.columns]
    hg_wide = df_hg.pivot_table(index="Frame", columns="Column",
                                 values="Intensity", aggfunc="mean")
    hg = hg_wide.mean(axis=0).values.astype(float)

    # 피크 자동 감지
    peaks_idx, _ = find_peaks(hg, height=np.percentile(hg, 95),
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

    fwhm_mean = np.mean([f["fwhm_nm"] for f in fits]) if fits else np.nan
    sig_mean  = np.mean([f["sig_nm"]  for f in fits]) if fits else np.nan
    print(f"\n{'='*60}\n  FWHM / Sigma  (Hot roi2 Hg lamp)\n{'='*60}")
    print(f"  Mean FWHM  = {fwhm_mean:.4f} nm\n  Mean sigma = {sig_mean:.4f} nm\n")

    # ── Raw .mat → R 계산 ─────────────────────────────────────────────────────
    HE_FLAGS = {510, 511, 512, 513}
    ZA_FLAGS = {500, 501, 502, 503}
    mat_files = sorted(Path(MAT_DIR).glob("*.mat"))
    print(f"Found {len(mat_files)} .mat files in {MAT_DIR}")

    he_ch1, za_ch1 = [], []
    he_ch2, za_ch2 = [], []
    P_SCALE = 0.01 * 6894.73326 / 100.0   # counts → mbar

    for mf in mat_files:
        try:
            mat  = sio.loadmat(str(mf))
            ch1  = mat["ch1"]
            ch2  = mat["ch2"]
            flags = mat["flag"].flatten().astype(int)
            tc1 = mat.get("tempcell1",  np.full((len(flags), 1), 25.0)).flatten()
            pc1 = mat.get("presscell1", np.full((len(flags), 1), 1013.25)).flatten()
            pc2 = mat.get("presscell2", pc1).flatten()
            tc2 = mat.get("tempcell2",  tc1).flatten()

            for fv, lists in [(HE_FLAGS, (he_ch1, he_ch2)),
                               (ZA_FLAGS, (za_ch1, za_ch2))]:
                for flag_val in fv:
                    idx = np.where(flags == flag_val)[0]
                    if not len(idx):
                        continue
                    t1 = float(np.median(tc1[idx])) / 100.0
                    p1 = float(np.median(pc1[idx])) * P_SCALE
                    lists[0].append((np.median(ch1[idx, :], axis=0).astype(float), t1, p1))
                    p2_raw = float(np.median(pc2[idx]))
                    t2_raw = float(np.median(tc2[idx]))
                    p2 = (p2_raw * P_SCALE) if p2_raw > 10 else p1
                    t2 = (t2_raw / 100.0)   if t2_raw > 10 else t1
                    lists[1].append((np.median(ch2[idx, :], axis=0).astype(float), t2, p2))
        except Exception as ex:
            print(f"  Skip {mf.name}: {ex}")

    print(f"ch1 He: {len(he_ch1)}  ZA: {len(za_ch1)}")
    print(f"ch2 He: {len(he_ch2)}  ZA: {len(za_ch2)}\n")

    # ── R 계산: core.physics.RayleighPhysics 사용 ─────────────────────────────
    d_cav = 51.8   # cm

    def compute_R_series(he_list, za_list, wl_arr, gas_he="helium", gas_za="zero_air"):
        results = []
        for (i_he, t_he, p_he), (i_za, t_za, p_za) in zip(he_list, za_list):
            a_he = RayleighPhysics.get_alpha_rayleigh(wl_arr, t_he, p_he, gas_he)
            a_za = RayleighPhysics.get_alpha_rayleigh(wl_arr, t_za, p_za, gas_za)
            i_he_safe = np.where(np.abs(i_he) > 1.0, i_he, 1.0)
            ratio = i_za / i_he_safe
            with np.errstate(divide="ignore", invalid="ignore"):
                omr_d = (ratio * a_za - a_he) / (1.0 - ratio)
            results.append(np.clip(1.0 - omr_d * d_cav, 0.0, 1.0))
        return np.vstack(results) if results else np.full((1, len(wl_arr)), np.nan)

    R_ch1 = compute_R_series(he_ch1, za_ch1, wl_r1)
    R_ch2 = compute_R_series(he_ch2, za_ch2, wl_r2)
    print(f"R curves: ch1={R_ch1.shape[0]}  ch2={R_ch2.shape[0]}")

    def summarize_R(R_all, wl_arr, label, wl_lo=432, wl_hi=480):
        p_lo = int(np.argmin(np.abs(wl_arr - wl_lo)))
        p_hi = int(np.argmin(np.abs(wl_arr - wl_hi)))
        Rv = R_all[:, p_lo:p_hi].copy()
        Rv[(Rv < 0.95) | (Rv >= 1.0)] = np.nan
        R_ts = np.nanmedian(Rv, axis=1)
        valid = R_ts[np.isfinite(R_ts)]
        print(f"\n{'='*60}\n  R {label}  ({wl_lo}-{wl_hi}nm median)\n{'='*60}")
        if len(valid):
            Leff = 51.8e-5 / (1.0 - valid)
            print(f"  R  range  : {valid.min()*100:.4f}% ~ {valid.max()*100:.4f}%")
            print(f"  R  median : {np.median(valid)*100:.4f}%")
            print(f"  Leff med  : {np.median(Leff):.2f} km")
        return R_ts, np.nanmedian(R_all, axis=0), p_lo, p_hi

    R_ts1, R_wl1, p_lo1, p_hi1 = summarize_R(R_ch1, wl_r1, "roi1 (ch1)")
    R_ts2, R_wl2, p_lo2, p_hi2 = summarize_R(R_ch2, wl_r2, "roi2 (ch2)")
    print()

    # ── Figure ────────────────────────────────────────────────────────────────
    COLORS = ["red", "royalblue", "green", "darkorange", "purple"]
    fig = plt.figure(figsize=(16, 17))
    gs  = gridspec.GridSpec(4, 2, hspace=0.52, wspace=0.35, top=0.94, bottom=0.06)

    ax0 = fig.add_subplot(gs[0, :])
    ax0.plot(wl_r2, hg, "k-", lw=0.7, alpha=0.65, label="Hg lamp roi2 (60fr avg)")
    for res, clr in zip(fits, COLORS):
        xi = np.clip(res["xd"].astype(int), 0, len(wl_r2) - 1)
        ax0.plot(wl_r2[xi], gauss(res["xd"], *res["popt"]), color=clr, lw=2.5,
                 label=f"{res['wl_center']:.1f}nm: FWHM={res['fwhm_nm']:.3f}nm  sigma={res['sig_nm']:.3f}nm")
        ax0.axvline(res["wl_center"], color=clr, ls="--", alpha=0.3)
    ax0.set_xlabel("Wavelength (nm)"); ax0.set_ylabel("Counts")
    ax0.set_title("Hot Hg lamp (roi2)  -  FWHM and sigma measurement",
                  fontweight="bold", fontsize=13)
    ax0.legend(fontsize=9); ax0.set_xlim(wl_r2[0], wl_r2[-1])

    for ax_sub, fit_res, clr in [(fig.add_subplot(gs[1, 0]), fits[0] if fits else None, "red"),
                                  (fig.add_subplot(gs[1, 1]), fits[-1] if len(fits) >= 2 else None, "royalblue")]:
        if fit_res:
            xi = np.clip(fit_res["xd"].astype(int), 0, len(wl_r2) - 1)
            ax_sub.plot(wl_r2[xi], hg[xi], "ko-", ms=3, label="data")
            ax_sub.plot(wl_r2[xi], gauss(fit_res["xd"], *fit_res["popt"]), color=clr, lw=2.2, label="Gaussian fit")
            ax_sub.axhline(fit_res["bg"] + fit_res["A"] / 2, color="gray", ls=":", lw=1.2, label="half-max")
            ax_sub.set_title(f"{fit_res['wl_center']:.1f}nm  FWHM={fit_res['fwhm_nm']:.3f}nm  sigma={fit_res['sig_nm']:.3f}nm",
                             fontweight="bold")
            ax_sub.set_xlabel("Wavelength (nm)"); ax_sub.set_ylabel("Counts"); ax_sub.legend()

    def plot_R_wl(ax, R_all, wl_arr, p_lo, p_hi, label, color):
        Rc = np.nanmedian(R_all, axis=0).copy()
        Rc[(Rc < 0.95) | (Rc >= 1.0) | ~np.isfinite(Rc)] = np.nan
        med_r = float(np.nanmedian(Rc[p_lo:p_hi]))
        ax.plot(wl_arr, Rc * 100, color=color, lw=1.2)
        if np.isfinite(med_r) and med_r < 1.0:
            ax.axhline(med_r * 100, color="crimson", ls="--", lw=1.8,
                       label=f"median {med_r*100:.4f}%  Leff={51.8e-5/(1-med_r):.2f} km")
        ax.set_xlabel("Wavelength (nm)"); ax.set_ylabel("R (%)")
        ax.set_title(f"Hot R curve  ({label})", fontweight="bold")
        ax.set_xlim(wl_arr[0], wl_arr[-1]); ax.set_ylim(99.0, 100.05); ax.legend()

    def plot_R_ts(ax, R_ts, label, color):
        v = np.isfinite(R_ts)
        ax.plot(np.arange(np.sum(v)), R_ts[v] * 100, "o-", color=color, ms=5, lw=1.5)
        ax.set_xlabel("He/ZA pair index"); ax.set_ylabel("R median (%)")
        ax.set_title(f"Hot R per He/ZA pair  ({label}, 432-480nm)", fontweight="bold")
        valid = R_ts[v]
        if len(valid):
            lo, hi = valid.min() * 100, valid.max() * 100
            m = max((hi - lo) * 0.5, 0.005)
            ax.set_ylim(lo - m, hi + m)

    plot_R_wl(fig.add_subplot(gs[2, 0]), R_ch1, wl_r1, p_lo1, p_hi1, "roi1 ch1", "navy")
    plot_R_wl(fig.add_subplot(gs[2, 1]), R_ch2, wl_r2, p_lo2, p_hi2, "roi2 ch2", "darkgreen")
    plot_R_ts(fig.add_subplot(gs[3, 0]), R_ts1, "roi1 ch1", "navy")
    plot_R_ts(fig.add_subplot(gs[3, 1]), R_ts2, "roi2 ch2", "darkgreen")

    fig.text(0.5, 0.015,
             "sigma (s) = FWHM / 2.3548  |  "
             "Reference cross-sections must be convolved with Gaussian(sigma) "
             "to match the Hot spectrometer line shape.",
             ha="center", fontsize=9.5, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="lightyellow", ec="gray", alpha=0.9))
    plt.savefig(OUT_PNG, dpi=130, bbox_inches="tight")
    print(f"Saved: {OUT_PNG}")


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FWHM + R 진단 (cold/hot)")
    parser.add_argument("--mode", choices=["cold", "hot"], required=True,
                        help="분석 대상: cold = Cold 채널,  hot = Hot 채널 (roi1+roi2)")
    args = parser.parse_args()

    if args.mode == "cold":
        run_cold()
    else:
        run_hot()
