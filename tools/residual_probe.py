"""tools/residual_probe.py — 실제 콜드 알파 한 스캔을 박사님 시나리오로 피팅하고
잔차(residual)를 그림으로 뽑는다. GUI의 Test Fit 로직을 헤드리스로 복제.

목적: "지금 핏이 얼마나 잘 맞고 있나"를 잔차 한 장으로 눈으로 확인.
- 잔차가 평평한 잡음 → 이미 충분히 좋음(더 할 거 없음).
- 규칙적 물결/구조 → ISF·etalon·레퍼런스 손볼 여지 있음(FFT로 확인).
"""
import sys, os, json
import numpy as np

from core.physics import air_number_density   # ppb 환산 단일 출처
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.engine import UniversalEngine
from core.doas_fit import DoasFitter

SCEN = os.path.join(ROOT, "scenarios", "Doctor_Scenario_Cold_ROI1_ROI2.json")
ALPHA = r"C:\Doasis_Work\Output\alpha\cold\2026-05-17\2026-05-17-008_cold_alpha_trace.dat"
PX_MIN, PX_MAX = 775, 1550     # 박사님 콜드 핏 윈도우(px)
POLY_DEG, STEP_LIMIT, LAM, ROBUST = 4, 0.5, 0.0, False


def load_alpha(fp):
    wave = None; row = None; alpha_start = None; iT = iP = None
    with open(fp, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("# wavelength_nm"):
                wave = np.array([float(x) for x in line.split(":")[1].split()])
            if line.startswith("#"):
                continue
            cols = line.rstrip("\n").split("\t")
            if cols and cols[0] == "row_idx":
                idx = {c: i for i, c in enumerate(cols)}
                alpha_start = next(i for i, c in enumerate(cols) if c.startswith("px"))
                iT, iP = idx.get("T_C"), idx.get("P_mbar")
                continue
            if alpha_start is not None:
                row = cols
                break
    n = len(wave)
    T_C = float(row[iT]) if iT is not None and iT < len(row) else 25.0
    P_mbar = float(row[iP]) if iP is not None and iP < len(row) else 1013.0
    alpha = np.array([float(v) for v in row[alpha_start:alpha_start + n]], dtype=float)
    return wave, alpha, T_C, P_mbar


def build_engine(ch_cfg, wave):
    eng = UniversalEngine()
    eng.set_wavelength_axis(wave)
    for ref in ch_cfg["refs"]:
        p = ref.get("path", "")
        if p and os.path.exists(p):
            ok, msg = eng.add_reference(ref["name"], p, wave_nm=wave,
                                        multiplier=10.0 ** ref.get("mult", 0))
            print("  ref:", ref["name"], ok)
    eng.apply_ils_convolution(0.0)
    return eng


def fit_one(eng, fitter, rp, wave, alpha, T_C, P_mbar):
    sl = slice(PX_MIN, PX_MAX + 1)
    wl = wave[sl]; a = alpha[sl]
    wax = np.asarray(eng._wave_axis, float).flatten()
    vp_pixel = np.asarray(interp1d(wax, np.arange(len(wax)), bounds_error=False,
                                   fill_value="extrapolate")(wl), float)
    vp_center = vp_pixel[len(vp_pixel) // 2]
    ef = fitter.detect_etalon_frequency(vp_pixel, a, POLY_DEG, 0.02, 0.40)
    active, fixed, linked, t0, lb, ub = fitter.setup_fit_parameters(rp, 0.0, [0.0, 1.0], STEP_LIMIT)
    # (구식 etalon 위상 append 제거 — doas_fit가 sin·cos 선형열로 처리, theta는 shift/squeeze만)
    out = fitter.execute_varpro_fit(
        vp_pixel, a, np.eye(len(a)), active, fixed, linked, t0, lb, ub,
        POLY_DEG, ef, vp_center, 1.0, rp, T_C, LAM, ROBUST)
    opt_shifts, opt_squeezes, gas_coeffs, poly_c, etal_amp, best_ep, perr = out
    full_model, total_abs, baseline, etal, _ = eng.get_model_components(
        vp_pixel, opt_shifts, opt_squeezes, gas_coeffs, poly_c,
        etalon_amp=etal_amp, etalon_freq=ef, etalon_phase=best_ep)
    resid = a - full_model
    rms = float(np.sqrt(np.mean(resid ** 2)))
    n_air = air_number_density(T_C, P_mbar)
    ppb = {}
    for gi, nm in enumerate(eng.gas_list):
        sc = eng.scaling_factors.get(nm, 1.0); mu = eng.multipliers.get(nm, 1.0)
        ppb[nm] = (gas_coeffs[gi] * mu / sc) / n_air * 1e9
    return wl, a, baseline, etal, total_abs, resid, rms, ppb, opt_shifts[0], opt_squeezes[0]


def multi_overlay(eng, fitter, rp):
    """여러 스캔 잔차를 겹쳐 그려 구조의 재현성(고정 vs 랜덤)을 본다."""
    import glob
    days = [r"C:\Doasis_Work\Output\alpha\cold\2026-05-17",
            r"C:\Doasis_Work\Output\alpha\cold\2026-05-18"]
    files = []
    for d in days:
        files += sorted(glob.glob(os.path.join(d, "*_cold_alpha_trace.dat")))
    files = files[::3][:12]
    resids = []; wl0 = None
    fig, ax = plt.subplots(2, 1, figsize=(10, 8))
    for fp in files:
        try:
            wave, alpha, T_C, P_mbar = load_alpha(fp)
            wl, a, base, etal, tot, resid, rms, ppb, sh, sq = fit_one(eng, fitter, rp, wave, alpha, T_C, P_mbar)
            if wl0 is None: wl0 = wl
            if len(resid) == len(wl0):
                resids.append(resid)
                ax[0].plot(wl0, resid, lw=.6, alpha=.5)
            print(f"  {os.path.basename(fp)[:13]}  NO2={ppb.get('NO2',0):6.1f}  RMS={rms:.2e}")
        except Exception as e:
            print("  skip", os.path.basename(fp), e)
    R = np.array(resids)
    mean_r = R.mean(0); std_r = R.std(0)
    ax[0].plot(wl0, mean_r, "k", lw=2, label="mean residual")
    ax[0].axhline(0, color="gray", lw=.5)
    ax[0].set_title(f"Residuals of {len(resids)} cold scans overlaid")
    ax[0].set_ylabel("residual"); ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)
    # 재현성 지표: mean의 진폭 vs scan-to-scan 산포
    frac = np.std(mean_r) / (np.mean(std_r) + 1e-30)
    ax[1].plot(wl0, mean_r, "k", lw=1.5, label=f"mean (fixed structure)")
    ax[1].fill_between(wl0, mean_r - std_r, mean_r + std_r, color="#90CAF9", alpha=.4,
                       label="±1σ scan-to-scan")
    ax[1].axhline(0, color="gray", lw=.5)
    ax[1].set_title(f"Fixed structure vs random spread   (fixed/random = {frac:.2f};  >1 = systematic)")
    ax[1].set_xlabel("wavelength (nm)"); ax[1].set_ylabel("residual"); ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)
    fig.tight_layout()
    out_png = os.path.join(ROOT, "tools", "residual_overlay.png")
    fig.savefig(out_png, dpi=130); print("saved:", out_png)
    print(f"DIAG: fixed/random ratio = {frac:.2f}  (>1 → systematic, removable)")


def main():
    scen = json.load(open(SCEN, encoding="utf-8"))
    ch = scen["channels"]["1"]
    rp = ch["ref_props"]

    wave, alpha, T_C, P_mbar = load_alpha(ALPHA)
    print(f"alpha: n_pix={len(wave)}  T={T_C:.1f}C  P={P_mbar:.0f}mb")

    eng = build_engine(ch, wave)
    fitter = DoasFitter(eng)

    if len(sys.argv) > 1 and sys.argv[1] == "multi":
        multi_overlay(eng, fitter, rp)
        return

    sl = slice(PX_MIN, PX_MAX + 1)
    wl = wave[sl]; a = alpha[sl]

    wax = np.asarray(eng._wave_axis, float).flatten()
    vp_pixel = np.asarray(interp1d(wax, np.arange(len(wax)), bounds_error=False,
                                   fill_value="extrapolate")(wl), float)
    vp_center = vp_pixel[len(vp_pixel) // 2]

    # etalon 주파수 검출(worker와 동일: 0.02~0.40 cycles/px) → 각주파수(rad/px) 반환
    ef = fitter.detect_etalon_frequency(vp_pixel, a, POLY_DEG, 0.02, 0.40)
    print(f"etalon angular freq = {ef:.4f} rad/px  (period {2*np.pi/ef:.1f} px)")

    active, fixed, linked, t0, lb, ub = fitter.setup_fit_parameters(rp, 0.0, [0.0, 1.0], STEP_LIMIT)
    # (구식 etalon 위상 append 제거 — doas_fit가 sin·cos 선형열로 처리, theta는 shift/squeeze만)
    out = fitter.execute_varpro_fit(
        vp_pixel, a, np.eye(len(a)), active, fixed, linked, t0, lb, ub,
        POLY_DEG, ef, vp_center, 1.0, rp, T_C, LAM, ROBUST)
    opt_shifts, opt_squeezes, gas_coeffs, poly_c, etal_amp, best_ep, perr = out

    full_model, total_abs, baseline, etal, _ = eng.get_model_components(
        vp_pixel, opt_shifts, opt_squeezes, gas_coeffs, poly_c,
        etalon_amp=etal_amp, etalon_freq=ef, etalon_phase=best_ep)
    resid = a - full_model
    rms = float(np.sqrt(np.mean(resid ** 2)))

    n_air = air_number_density(T_C, P_mbar)
    ppb = {}
    for gi, nm in enumerate(eng.gas_list):
        sc = eng.scaling_factors.get(nm, 1.0); mu = eng.multipliers.get(nm, 1.0)
        ppb[nm] = (gas_coeffs[gi] * mu / sc) / n_air * 1e9
    gtxt = "  ".join(f"{g}={ppb[g]:.2f}ppb" for g in ppb)
    print(f"FIT: {gtxt}  shift={opt_shifts[0]:+.3f}px  sq={opt_squeezes[0]:.4f}  RMS={rms:.3e}")

    # baseline 제거 측정 vs 가스합
    diff_meas = a - baseline - etal
    sum_gas = total_abs

    # ── 그림: (1) 측정 vs 가스합  (2) 잔차  (3) 잔차 FFT ──
    fig, ax = plt.subplots(3, 1, figsize=(10, 10))
    ax[0].plot(wl, diff_meas, color="#1976D2", lw=1.4, label="measured (baseline removed)")
    ax[0].plot(wl, sum_gas, color="#D32F2F", lw=1.2, label="fitted gases (Σ)")
    ax[0].set_title(f"Cold {os.path.basename(ALPHA)}  |  {gtxt}  |  RMS={rms:.2e}")
    ax[0].set_ylabel("diff α"); ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)

    ax[1].axhline(0, color="k", lw=.6)
    ax[1].plot(wl, resid, color="#455A64", lw=.9)
    ax[1].fill_between(wl, -rms, rms, color="#90A4AE", alpha=.25, label=f"±RMS ({rms:.1e})")
    ax[1].set_title("Residual  (flat noise = good fit; wavy = structure left)")
    ax[1].set_ylabel("residual"); ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)

    r = resid - resid.mean()
    fft = np.abs(np.fft.rfft(r * np.hanning(len(r))))
    freq = np.fft.rfftfreq(len(r), d=1.0)  # cycles/pixel
    ax[2].plot(freq[1:], fft[1:], color="#6A1B9A", lw=1.0)
    ax[2].set_title("Residual FFT  (sharp peak = etalon/periodic structure)")
    ax[2].set_xlabel("frequency (cycles/pixel)"); ax[2].set_ylabel("|amplitude|"); ax[2].grid(alpha=.3)

    fig.tight_layout()
    out_png = os.path.join(ROOT, "tools", "residual_probe.png")
    fig.savefig(out_png, dpi=130)
    print("saved:", out_png)

    # 잔차 구조 정량 지표
    white = np.std(np.diff(resid)) / (np.std(resid) + 1e-30)  # 1=흰잡음, <1=구조있음(자기상관)
    peak_ratio = float(fft[1:].max() / (np.median(fft[1:]) + 1e-30))
    print(f"DIAG: resid_std={np.std(resid):.3e}  whiteness={white:.2f}(1=white)  fft_peak/median={peak_ratio:.1f}")


if __name__ == "__main__":
    main()
