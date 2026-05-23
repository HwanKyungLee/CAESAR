"""
mission_20260523.py  ─  2026-05-23 박사님 New Mission
======================================================

Task 1. Hot sigma sweep   FWHM 0.60 → 0.80 nm (step 0.02, 11값)
        NO2 / CHOCHO / H2O / O4   → D:\CAESAR hot\roi1\sigma_sweep\
Task 2. Cold 파장 교정   새 Hg CSV(2026-05-23) 사용 → 새 Calib 파일
Task 3. Cold sigma sweep  측정 FWHM ±범위 (0.02 step)
Task 4. Cold sigma sweep  3.0 → 4.0 nm (step 0.1, 11값)
        → D:\CAESAR cold\sigma_sweep\

Run:  python mission_20260523.py
"""

from __future__ import annotations
import os, datetime, warnings
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
from scipy.optimize import curve_fit
from scipy.signal import find_peaks

warnings.filterwarnings("ignore")

# ════════════════════════════════════════════════════════════════
#  공용 경로
# ════════════════════════════════════════════════════════════════
XS_DIR   = r"C:\LGH\Absorption cross-section by lgh\원본"
COLD_DIR = r"D:\CAESAR cold"
HOT_DIR      = r"D:\CAESAR hot\roi1"
HOT_DIR_ROI2 = r"D:\CAESAR hot\roi2"

HOT_WAVE_CAL      = os.path.join(HOT_DIR,      "Calib_20260403_Hg_400-499nm(roi1).txt")
HOT_WAVE_CAL_ROI2 = os.path.join(HOT_DIR_ROI2, "Calib_20260403_Hg_400-499nm(roi2).txt")
NEW_HG_CSV   = r"D:\CAESAR cold\2026 5월 23 07_55_37.csv"

RAW_XS_FILES = {
    "NO2":    os.path.join(XS_DIR, "NO2_Vandaele(2002)_294K_384-725nm(vis-dilut5).txt"),
    "CHOCHO": os.path.join(XS_DIR, "CHOCHO_Volkamer(2005)_296K_250.031-526.168nm(0.001nm).txt"),
    "O4":     os.path.join(XS_DIR, "O4_ThalmanVolkamer(2013)_293K_335.749-600.802nm.txt"),
}
LIT_FWHM = {"NO2": 0.01156, "CHOCHO": 0.01, "O4": 0.0, "H2O": 0.0}

HR_STEP  = 0.002   # nm, 고해상도 보간 간격

# ════════════════════════════════════════════════════════════════
#  공용 함수
# ════════════════════════════════════════════════════════════════
def load_wavelengths(path: str) -> np.ndarray:
    lines = [l.strip() for l in open(path, encoding="utf-8", errors="replace")
             if l.strip() and not l.strip().startswith("#")]
    return np.array([float(l) for l in lines])


def load_xs(path: str) -> tuple[np.ndarray, np.ndarray]:
    df = pd.read_csv(path, sep=r"\s+", header=None, comment="#")
    wave = pd.to_numeric(df.iloc[:, 0], errors="coerce").values
    data = pd.to_numeric(df.iloc[:, 1], errors="coerce").values
    ok   = np.isfinite(wave) & np.isfinite(data)
    return wave[ok], data[ok]


def convolve_uniform_gaussian(raw_wave, raw_data, target_wl, fwhm_nm, lit_fwhm_nm=0.0):
    """전체 파장 범위에 균일한 Gaussian ILS 적용 (fixed sigma)."""
    sigma_inst = fwhm_nm / 2.35482
    sigma_lit  = lit_fwhm_nm / 2.35482
    added_var  = max(1e-20, sigma_inst**2 - sigma_lit**2)
    sigma_eff  = np.sqrt(added_var)

    hr_wave = np.arange(target_wl.min() - 5.0, target_wl.max() + 5.0, HR_STEP)
    f_raw   = interp1d(raw_wave, raw_data, kind="linear",
                       bounds_error=False, fill_value=0.0)
    hr_data = f_raw(hr_wave)

    result = np.zeros(len(target_wl))
    for i, w in enumerate(target_wl):
        kernel = (1.0 / (sigma_eff * np.sqrt(2 * np.pi))) * \
                 np.exp(-0.5 * ((hr_wave - w) / sigma_eff) ** 2)
        result[i] = float(np.dot(hr_data, kernel) * HR_STEP)
    return result


def _gaussian_fn(x, a, mu, sigma, offset):
    return a * np.exp(-0.5 * ((x - mu) / sigma) ** 2) + offset


def _get_subpixel_peak(spec, peak_px):
    """GUI WavelengthCalibrationDialog.get_subpixel_peak 와 동일한 방식.
    ±5 px 좁은 윈도우: Centroid → Gaussian fit (sigma_guess=1.0 고정).
    날카로운 Hg 라인에 최적 — 넓은 윈도우 방식보다 정확.
    """
    try:
        window = 5
        pk = int(np.clip(peak_px, 0, len(spec) - 1))
        s  = max(0, pk - window)
        e  = min(len(spec), pk + window + 1)
        x_data = np.arange(s, e, dtype=float)
        y_data = np.asarray(spec[s:e], dtype=float)

        # Stage 1: Centroid (Center of Mass)
        y_bg     = y_data - np.min(y_data)
        mass_sum = float(np.sum(y_bg))
        if mass_sum == 0:
            return float(pk)
        centroid = float(np.sum(x_data * y_bg) / mass_sum)

        # Stage 2: Gaussian fit (centroid을 초기값으로)
        a_g  = float(np.max(y_data) - np.min(y_data))
        off_g = float(np.min(y_data))
        popt, _ = curve_fit(_gaussian_fn, x_data, y_data,
                            p0=[a_g, centroid, 1.0, off_g],
                            maxfev=2000)
        sub_px = float(popt[1])

        # 너무 멀리 수렴하면 centroid fallback
        if abs(sub_px - pk) > window:
            return centroid
        return sub_px

    except Exception:
        # Gaussian 실패 → centroid fallback
        try:
            window = 5
            pk = int(np.clip(peak_px, 0, len(spec) - 1))
            s  = max(0, pk - window)
            e  = min(len(spec), pk + window + 1)
            x_data = np.arange(s, e, dtype=float)
            y_bg   = np.asarray(spec[s:e], dtype=float)
            y_bg   = y_bg - y_bg.min()
            total  = float(y_bg.sum())
            return float(np.sum(x_data * y_bg) / total) if total > 0 else float(peak_px)
        except Exception:
            return float(peak_px)


def fit_peak(spec, peak_px, wl):
    """서브픽셀 피크 위치 (GUI 방식, ±5 px) + FWHM 측정 (반치폭 기반 넓은 윈도우).
    Returns: (fwhm_nm, sigma_nm, subpixel_center)
    """
    # ── 1. 서브픽셀 위치: GUI get_subpixel_peak 방식 ──────────────────
    mu = _get_subpixel_peak(spec, peak_px)
    pk = int(np.clip(round(mu), 0, len(spec) - 1))

    # ── 2. FWHM: GUI calculate_fwhm 방식 (반치폭 → 동적 윈도우) ────────
    ctx       = spec[max(0, pk - 200): min(len(spec), pk + 201)]
    baseline  = float(np.percentile(ctx, 10))
    amplitude = float(spec[pk]) - baseline
    if amplitude <= 0:
        return None, None, None

    half_level = baseline + amplitude * 0.5
    left_hm, right_hm = pk, pk
    while left_hm  > 0              and spec[left_hm]  > half_level: left_hm  -= 1
    while right_hm < len(spec) - 1  and spec[right_hm] > half_level: right_hm += 1

    half_width = max(right_hm - pk, pk - left_hm, 1)
    window     = max(15, min(300, int(half_width * 1.5)))
    s, e       = max(0, pk - window), min(len(spec), pk + window + 1)
    x_d, y_d   = np.arange(s, e, dtype=float), spec[s:e]
    sigma_g    = max(0.5, min(half_width / 2.3548, window * 0.8))

    try:
        popt, _ = curve_fit(_gaussian_fn, x_d, y_d,
                            p0=[amplitude, mu, sigma_g, baseline],
                            bounds=([0, s, 0.3, -np.inf],
                                    [np.inf, e, window, np.inf]),
                            maxfev=8000)
    except Exception as ex:
        print(f"    FWHM fit failed at px {pk}: {ex}")
        return None, None, None

    _, fit_mu, sigma_px, _ = popt
    fwhm_px  = 2.3548 * abs(sigma_px)
    mu_i     = int(np.clip(round(fit_mu), 1, len(wl) - 2))
    disp     = (wl[mu_i + 1] - wl[mu_i - 1]) / 2.0
    if disp <= 0:
        return None, None, None

    fwhm_nm  = fwhm_px * disp
    sigma_nm = fwhm_nm / 2.3548
    return fwhm_nm, sigma_nm, mu   # mu = 서브픽셀 위치 (파장 교정용)


def save_ref_dat(path, arr, header):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    np.savetxt(path, arr, fmt="%.8e", header=header)


def save_sweep_xlsx(out_path, wavelengths, gas_results: dict, fwhm_list):
    """
    gas_results[gas][fwhm] = convolved array
    출력: 각 gas마다 열 = [FWHM값, ...], 행 = 픽셀
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    gases = list(gas_results.keys())
    n_fwhm = len(fwhm_list)
    n_pix  = len(wavelengths)

    # Header row: [gas1_F0.60, gas1_F0.62, ..., None, gas2_F0.60, ...]
    sep = 1   # 빈 열 구분자 수
    cols = []
    for gas in gases:
        for fv in fwhm_list:
            cols.append(f"{gas}_FWHM={fv:.2f}nm")
        cols.extend([None] * sep)

    rows = [cols]
    for i in range(n_pix):
        row = []
        for gas in gases:
            for fv in fwhm_list:
                row.append(float(gas_results[gas][fv][i]))
            row.extend([None] * sep)
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_excel(out_path, index=False, header=False, engine="openpyxl")
    print(f"  [xlsx] {out_path}  ({n_pix} px × {len(gases)} gases × {n_fwhm} FWHM)")


# ════════════════════════════════════════════════════════════════
#  TASK 1  Hot sigma sweep  FWHM 0.60 ~ 0.80 nm (0.02 step)
# ════════════════════════════════════════════════════════════════
def _hot_sweep_one_roi(roi_label, wave_cal_path, out_base_dir, fwhm_list, xs_raw):
    """단일 ROI에 대해 Hot sigma sweep 수행. task1에서 roi1/roi2 공용."""
    hot_wl  = load_wavelengths(wave_cal_path)
    out_dir = os.path.join(out_base_dir, "sigma_sweep")
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n  [{roi_label}] Wavelength: {hot_wl[0]:.3f} ~ {hot_wl[-1]:.3f} nm  ({len(hot_wl)} px)")

    h2o_wave, h2o_data = _get_h2o(hot_wl)
    xs_data = dict(xs_raw)
    xs_data["H2O"] = (h2o_wave, h2o_data)

    gas_results = {g: {} for g in xs_data}

    for gas, (rw, rd) in xs_data.items():
        mask = (rw >= hot_wl.min() - 10.0) & (rw <= hot_wl.max() + 10.0)
        if not np.any(mask):
            print(f"  {gas}: no data in range → skip")
            continue
        rw_m, rd_m = rw[mask], rd[mask]
        lit_fw = LIT_FWHM.get(gas, 0.0)
        print(f"\n  [{roi_label}][{gas}] lit_FWHM={lit_fw} nm")
        for fv in fwhm_list:
            conv  = convolve_uniform_gaussian(rw_m, rd_m, hot_wl, fv, lit_fw)
            gas_results[gas][fv] = conv
            fname = f"Ref_{gas}_FWHM{fv:.2f}nm(hot,{roi_label}).dat"
            save_ref_dat(os.path.join(out_dir, fname), conv,
                         f"Gas={gas}  FWHM={fv:.2f}nm  Channel=Hot {roi_label}")
            print(f"    FWHM={fv:.2f} → max={conv.max():.3e}  [{fname}]")

    xlsx_path = os.path.join(out_dir, f"sigma_sweep_hot_{roi_label}.xlsx")
    save_sweep_xlsx(xlsx_path, hot_wl, gas_results, fwhm_list)
    print(f"  ✅ {roi_label} 완료 → {out_dir}")


def task1_hot_sigma_sweep():
    print("\n" + "═"*64)
    print("  TASK 1: Hot sigma sweep  FWHM 0.60→0.80 nm  (step 0.02)  roi1 + roi2")
    print("═"*64)

    fwhm_list = [round(0.60 + 0.02 * k, 2) for k in range(11)]  # 0.60…0.80
    print(f"  FWHM values: {fwhm_list}")

    # 공통 cross-section 미리 로드 (roi1/roi2 공유)
    xs_raw = {}
    for gas, path in RAW_XS_FILES.items():
        try:
            w, d = load_xs(path)
            xs_raw[gas] = (w, d)
            print(f"  Loaded {gas}: {len(w)} pts, {w.min():.1f}~{w.max():.1f} nm")
        except Exception as ex:
            print(f"  SKIP {gas}: {ex}")

    # roi1
    _hot_sweep_one_roi("roi1", HOT_WAVE_CAL,      HOT_DIR,      fwhm_list, xs_raw)
    # roi2
    _hot_sweep_one_roi("roi2", HOT_WAVE_CAL_ROI2, HOT_DIR_ROI2, fwhm_list, xs_raw)

    print(f"\n  ✅ Task 1 완료 (roi1 + roi2)")


# ════════════════════════════════════════════════════════════════
#  TASK 2  Cold 파장 교정  (새 Hg CSV 사용)
# ════════════════════════════════════════════════════════════════
def task2_cold_wave_cal() -> tuple[np.ndarray, float, float]:
    """새 Cold 파장 교정을 수행. (wavelengths, avg_fwhm_nm, avg_sigma_nm) 반환."""
    print("\n" + "═"*64)
    print("  TASK 2: Cold 파장 교정  (2026-05-23 Hg CSV)")
    print("═"*64)

    df = pd.read_csv(NEW_HG_CSV)
    frames = [
        df[(df["Frame"] == fr) & (df["Row"] == 0)]
        .sort_values("Column")["Intensity"].values
        for fr in sorted(df["Frame"].unique())
    ]
    avg_spec = np.mean(frames, axis=0)
    n_pix    = len(avg_spec)
    print(f"  Spectrum: {n_pix} pixels, {len(frames)} frames averaged")

    # ── 피크 탐색 ──────────────────────────────────────────────
    peaks_hi, _ = find_peaks(avg_spec, height=3000, distance=5)
    peaks_lo, _ = find_peaks(avg_spec, height=1000, distance=5)
    all_peaks   = np.unique(np.concatenate([peaks_lo, peaks_hi]))
    print(f"  Detected peaks: {all_peaks}  (intensities: {avg_spec[all_peaks].astype(int).tolist()})")

    # ── Hg 라인 할당 ────────────────────────────────────────────────────────────────
    # 이전 캘리브레이션(Poly2, 399-494 nm) 기반 추정:
    #   pixel 88  → 404.656 nm (Hg I, 강함)
    #   pixel 150 → 407.783 nm (Hg I, 중간)
    #   pixel 722 → 435.833 nm (Hg I, 최강)
    # 피크가 ±20 px 이내에 있으면 해당 파장 할당
    known_hg = [
        (88,  404.656),
        (150, 407.783),
        (722, 435.833),
    ]
    assignments = []
    for ref_px, ref_wl in known_hg:
        # 탐지된 피크 중 ref_px에 가장 가까운 정수 픽셀 선택
        dists = np.abs(all_peaks - ref_px)
        best_int = int(all_peaks[np.argmin(dists)])
        if dists.min() <= 25:
            # GUI와 동일: ±5 px Centroid→Gaussian 으로 서브픽셀 정밀도 확보
            sub_px = _get_subpixel_peak(avg_spec, best_int)
            assignments.append((sub_px, ref_wl))
            print(f"    Assigned: pixel {sub_px:.3f} → {ref_wl} nm  (integer={best_int}, expected={ref_px})")
        else:
            print(f"    WARNING: no peak near pixel {ref_px} (min dist {dists.min():.0f}) → skipped")

    if len(assignments) < 2:
        raise RuntimeError(f"Hg 피크 할당 2개 미만 ({len(assignments)}개) — 교정 불가")

    # ── 다항식 피팅 (서브픽셀 위치 사용 — GUI 방식과 동일) ────────────
    deg = min(2, len(assignments) - 1)
    px_arr = np.array([a[0] for a in assignments], dtype=float)
    wl_arr = np.array([a[1] for a in assignments], dtype=float)
    coeffs = np.polyfit(px_arr, wl_arr, deg)
    poly   = np.poly1d(coeffs)
    residuals = wl_arr - poly(px_arr)
    print(f"\n  Polynomial deg={deg}  coefficients: {coeffs}")
    print(f"  Residuals: {residuals}  (max |res|: {np.abs(residuals).max():.4f} nm)")

    wavelengths = poly(np.arange(n_pix))
    print(f"  Wavelength range: {wavelengths[0]:.3f} ~ {wavelengths[-1]:.3f} nm")

    # ── FWHM 측정 (가우시안 피팅) ─────────────────────────────
    fwhm_records = []
    for px, wl_ref in assignments:
        fnm, snm, mu = fit_peak(avg_spec, px, wavelengths)
        if fnm:
            fwhm_records.append(fnm)
            print(f"  Peak px≈{px} ({wl_ref:.3f} nm): FWHM={fnm:.4f} nm  sigma={snm:.4f} nm")

    avg_fwhm   = float(np.mean(fwhm_records)) if fwhm_records else 3.5
    avg_sigma  = avg_fwhm / 2.3548
    print(f"\n  Average FWHM = {avg_fwhm:.4f} nm  (sigma = {avg_sigma:.4f} nm)")

    # ── 파일 저장 ─────────────────────────────────────────────
    today    = datetime.datetime.now().strftime("%Y%m%d")
    wl_range = f"{int(wavelengths[0])}-{int(wavelengths[-1]+1)}nm"
    out_name = f"Calib_{today}_Hg_{wl_range}_Poly{deg}_cold.txt"
    out_path = os.path.join(COLD_DIR, out_name)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# BBCEAS Wavelength Calibration Result\n")
        f.write(f"# Generated: {today}\n")
        f.write(f"# Source: {os.path.basename(NEW_HG_CSV)}\n")
        f.write(f"# Poly{deg} coefficients: {coeffs.tolist()}\n")
        f.write(f"# Hg assignments: {assignments}\n")
        f.write(f"# Info: Average FWHM: {avg_fwhm:.3f} nm "
                f"(calculated from {len(fwhm_records)} peaks)\n")
        for w in wavelengths:
            f.write(f"{w:.6f}\n")
    print(f"  ✅ Saved: {out_name}")

    # FWHM 기록 파일
    fwhm_out = os.path.join(COLD_DIR, f"FWHM_Analysis_{today}_cold.txt")
    with open(fwhm_out, "w", encoding="utf-8") as f:
        f.write("# BBCEAS FWHM & Sigma Analysis Records\n")
        f.write(f"# Generated: {today}\n")
        f.write(f"# Source: {os.path.basename(NEW_HG_CSV)}\n")
        f.write("# Formula: Sigma = FWHM / 2.3548\n")
        f.write("-"*60 + "\n")
        f.write("Pixel\tFWHM(nm)\tabs_Sigma(nm)\n")
        for (px, wl_ref), fnm in zip(assignments, fwhm_records):
            f.write(f"{px}\t{fnm:.4f}\t{fnm/2.3548:.4f}\n")
        f.write(f"AVERAGE\t{avg_fwhm:.4f}\t{avg_sigma:.4f}\n")
    print(f"  ✅ Saved: {os.path.basename(fwhm_out)}")

    return wavelengths, avg_fwhm, avg_sigma


# ════════════════════════════════════════════════════════════════
#  TASK 3  Cold sigma sweep  측정 FWHM ± 범위 (0.02 step)
# ════════════════════════════════════════════════════════════════
def task3_cold_sigma_fine(cold_wl: np.ndarray, measured_fwhm: float):
    print("\n" + "═"*64)
    print(f"  TASK 3: Cold sigma sweep  center FWHM={measured_fwhm:.3f} nm ± 0.02 step")
    print("═"*64)

    # 측정 FWHM 기준으로 ±5 스텝 (0.1 nm) 범위 생성, 소수점 2자리 반올림
    center = round(measured_fwhm, 2)
    fwhm_list = sorted({round(center + 0.02 * k, 2) for k in range(-5, 6)
                        if round(center + 0.02 * k, 2) > 0})
    print(f"  FWHM values: {fwhm_list}")

    _run_cold_sweep(cold_wl, fwhm_list,
                    os.path.join(COLD_DIR, "sigma_sweep_fine"),
                    "sigma_sweep_cold_fine.xlsx")
    print(f"  ✅ Task 3 완료")


# ════════════════════════════════════════════════════════════════
#  TASK 4  Cold sigma sweep  3.0 ~ 4.0 nm (0.1 step)
# ════════════════════════════════════════════════════════════════
def task4_cold_sigma_coarse(cold_wl: np.ndarray):
    print("\n" + "═"*64)
    print("  TASK 4: Cold sigma sweep  FWHM 3.0→4.0 nm  (step 0.1)")
    print("═"*64)

    fwhm_list = [round(3.0 + 0.1 * k, 1) for k in range(11)]  # 3.0…4.0
    print(f"  FWHM values: {fwhm_list}")

    _run_cold_sweep(cold_wl, fwhm_list,
                    os.path.join(COLD_DIR, "sigma_sweep"),
                    "sigma_sweep_cold_3.0-4.0nm.xlsx")
    print(f"  ✅ Task 4 완료")


# ────────────────────────────────────────────────────────────────
#  Cold sweep 공용 실행부
# ────────────────────────────────────────────────────────────────
def _run_cold_sweep(cold_wl, fwhm_list, out_dir, xlsx_name):
    os.makedirs(out_dir, exist_ok=True)
    h2o_wave, h2o_data = _get_h2o(cold_wl)

    xs_data = {}
    for gas, path in RAW_XS_FILES.items():
        try:
            xs_data[gas] = load_xs(path)
        except Exception as ex:
            print(f"  SKIP {gas}: {ex}")
    xs_data["H2O"] = (h2o_wave, h2o_data)

    gas_results = {g: {} for g in xs_data}

    for gas, (rw, rd) in xs_data.items():
        margin = 10.0
        mask = (rw >= cold_wl.min() - margin) & (rw <= cold_wl.max() + margin)
        if not np.any(mask):
            continue
        rw, rd  = rw[mask], rd[mask]
        lit_fw  = LIT_FWHM.get(gas, 0.0)
        print(f"\n  [{gas}] {len(rw)} pts")
        for fv in fwhm_list:
            conv  = convolve_uniform_gaussian(rw, rd, cold_wl, fv, lit_fw)
            gas_results[gas][fv] = conv
            fname = f"Ref_{gas}_FWHM{fv:.2f}nm(cold).dat"
            save_ref_dat(os.path.join(out_dir, fname), conv,
                         f"Gas={gas}  FWHM={fv:.2f}nm  Channel=Cold")
            print(f"    FWHM={fv:.2f} → max={conv.max():.3e}")

    xlsx_path = os.path.join(out_dir, xlsx_name)
    save_sweep_xlsx(xlsx_path, cold_wl, gas_results, fwhm_list)


# ────────────────────────────────────────────────────────────────
#  H2O 보조 로더
# ────────────────────────────────────────────────────────────────
def _get_h2o(wl: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    try:
        import hapi
        hapi.db_begin(r"C:\LGH\hitran_data")
        nu_min = 1e7 / (wl.max() + 10)
        nu_max = 1e7 / (wl.min() - 10)
        nu_arr, coef = hapi.absorptionCoefficient_Voigt(
            SourceTables="H2O_Lines",
            Environment={"p": 1.0, "T": 293.0},
            OmegaStep=0.02,
            HITRAN_units=False,
        )
        wl_arr = 1e7 / nu_arr
        idx    = np.argsort(wl_arr)
        wl_arr, coef = wl_arr[idx], coef[idx]
        mask   = (wl_arr >= wl.min() - 10) & (wl_arr <= wl.max() + 10)
        print(f"  H2O from HITRAN: {np.sum(mask)} pts, max={coef[mask].max():.3e}")
        return wl_arr[mask], coef[mask]
    except Exception as ex:
        print(f"  H2O HITRAN unavailable ({ex}) → near-zero fallback")
        wl_fb  = np.linspace(wl.min() - 5, wl.max() + 5, 5000)
        data_fb = np.full(len(wl_fb), 1e-30)
        return wl_fb, data_fb


# ════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  CAESAR Pro — mission_20260523  (박사님 New Mission)      ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # Task 1: Hot sigma sweep
    task1_hot_sigma_sweep()

    # Task 2: Cold 파장 교정
    cold_wavelengths, cold_fwhm, cold_sigma = task2_cold_wave_cal()

    # Task 3: Cold fine sweep (측정 FWHM ± 0.02 step)
    task3_cold_sigma_fine(cold_wavelengths, cold_fwhm)

    # Task 4: Cold coarse sweep (3.0 ~ 4.0 nm, 0.1 step)
    task4_cold_sigma_coarse(cold_wavelengths)

    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║  모든 Task 완료                                           ║")
    print(f"║  Cold FWHM 측정값: {cold_fwhm:.4f} nm  (sigma={cold_sigma:.4f} nm)   ║")
    print(f"║  Hot  sweep 저장: {os.path.join(HOT_DIR,'sigma_sweep')}  ║")
    print(f"║  Cold sweep 저장: {os.path.join(COLD_DIR,'sigma_sweep')} ║")
    print("╚══════════════════════════════════════════════════════════╝")
