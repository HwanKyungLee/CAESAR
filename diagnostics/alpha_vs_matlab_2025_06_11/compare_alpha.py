"""
CAESAR Pro 알파 vs 박사님 MATLAB 알파 비교 — 2025-06-11 (ch1)
==============================================================
목적
----
CAESAR Pro의 AlphaExportWorker 알파 추출 로직을 그대로 적용해
박사님 MATLAB(`Alpha_CAESAR_Araon_2025_3ch.m`) 결과와 픽셀·시간 비교한다.
코드는 수정하지 않는다 — 진단 전용.

비교 변형 (dark·σ 토글)
-----------------------
  ν A : dark=None,            σ=Sellmeier  (현재 CAESAR Pro 기본 동작)
  ν B : dark=const 1500,      σ=Sellmeier  (HANDOFF.md 추정값 검증)
  ν C : dark=None,            σ=MATLAB 경험식 (1.100065e-15 · λ^-4.166)
  ν D : dark=const 1500,      σ=MATLAB 경험식

산출
----
  alpha_caesar_<variant>.npy : (N_bins, 2048) 60s 빈평균 알파
  alpha_matlab.npy           : (N_bins, 2048) 박사님 알파
  wave_nm.npy                : (2048,) 공통 파장축
  stats.txt                  : 픽셀별 bias·RMS, 잔차 시계열 요약
  plots/                     : 대표 bin 알파 오버레이, residual heatmap 등
"""
from __future__ import annotations
import os, sys, glob
import numpy as np
from scipy.interpolate import PchipInterpolator

# CAESAR Pro repo import
HERE      = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, REPO_ROOT)
from core.data_io import DataIO
from core.physics import RayleighPhysics

# ─── Constants for this run ──────────────────────────────────────────────────
RAW_DIR   = r'C:\Doasis_Work\CAESAR_Pro\raw(ex)\2025-06'
RAW_GLOB  = '2025-06-11-*.dat'
MATLAB_DIR = r'C:\Doasis_Work\LGH\아라온호 데이터분석\alpha_trace\ch1_20250611_000000'
WV_FILE   = r'C:\Doasis_Work\LGH\아라온호 데이터분석\wavelength\wv_2025_Araon.txt'
OUT_DIR   = HERE
PLOT_DIR  = os.path.join(OUT_DIR, 'plots')

CHANNEL    = 1
PIXEL_MIN  = 0
PIXEL_MAX  = 2048
RL_FACTOR  = 0.9330        # MATLAB ch1
FLAG_ZA    = {500, 501, 502, 503}
FLAG_HE    = {510, 511, 512, 513}
FLAG_AMB   = {1}           # MATLAB uses flag==1 only
BIN_SECONDS = 60.0
DARK_CONST = 1500.0        # for ν B / ν D

# ─── Rayleigh σ 변형 ─────────────────────────────────────────────────────────
def rayleigh_matlab_ch1(wave_nm, temp_c, press_mbar, gas_type='zero_air'):
    """MATLAB 경험식 (HJ 240429 실측 피팅) — Alpha_CAESAR_Araon_2025_3ch.m line 155."""
    wave_nm = np.asarray(wave_nm, dtype=float)
    N0 = 2.6867811e19
    N  = N0 * (press_mbar / 1013.25) * (273.15 / (temp_c + 273.15))
    if gas_type in ('zero_air', 'air'):
        sigma = 1.100065008184610e-15 * wave_nm ** -4.165598772133079
    else:  # helium — MATLAB Rs2_CAESAR_Cold_Yeosu_2026.m
        sigma = 1.336e-17 * wave_nm ** -4.1287
    return sigma * N


def get_alpha_rayleigh(wave_nm, temp_c, press_mbar, gas_type, sigma_source):
    if sigma_source == 'sellmeier':
        return RayleighPhysics.get_alpha_rayleigh(wave_nm, temp_c, press_mbar, gas_type)
    elif sigma_source == 'matlab':
        return rayleigh_matlab_ch1(wave_nm, temp_c, press_mbar, gas_type)
    raise ValueError(sigma_source)


# ─── Pass 1: collect ZA / He / ambient metadata across all files ─────────────
def collect_scans(file_list):
    """One streaming pass. Returns dict with arrays for ZA, He, ambient.

    Ambient gets (gidx, t, p, scan_time_s, file_idx, row_idx) without intensity
    (we'll re-read in pass 2 to save memory).
    """
    za   = dict(gidx=[], spec=[], T=[], P=[])
    he   = dict(gidx=[], spec=[], T=[], P=[])
    # ambient: also cache intensity (float32) so Pass 2 doesn't re-read raw files
    # Cost: ~88k scans × 2048 × 4B ≈ 720 MB — acceptable
    amb  = dict(gidx=[], T=[], P=[], t_sec=[], file_idx=[], row=[], spec=[])

    global_idx = 0
    # baseline timestamp = mtime of last file in chronological order minus its scan count
    # but simpler: assign each scan a synthetic time using (file_idx, row) order.
    for fi, fp in enumerate(file_list):
        try:
            entries = DataIO.expand_to_scan_list(fp)
        except Exception as e:
            print(f'  [SKIP] {os.path.basename(fp)}: {e}')
            continue
        n_rows = len(entries)
        # use file_mtime - (n_rows - row)/3672 * 3600 as rough timestamp (1 scan ≈ 1s)
        # this matches MATLAB doy ordering
        try:
            file_mtime = os.path.getmtime(fp)
        except Exception:
            file_mtime = float(fi) * 3600.0
        n_za_f = n_he_f = n_amb_f = 0
        for _, row_idx in entries:
            global_idx += 1
            try:
                _, intensity, sf, t, p = DataIO.load_measurement_with_hk(
                    fp, PIXEL_MIN, PIXEL_MAX, row_index=row_idx, channel=CHANNEL)
            except Exception:
                continue
            scan_time = file_mtime - (n_rows - row_idx) * (3600.0 / max(n_rows, 1))
            if sf in FLAG_ZA:
                za['gidx'].append(global_idx); za['spec'].append(intensity.astype(np.float32))
                za['T'].append(t); za['P'].append(p)
                n_za_f += 1
            elif sf in FLAG_HE:
                he['gidx'].append(global_idx); he['spec'].append(intensity.astype(np.float32))
                he['T'].append(t); he['P'].append(p)
                n_he_f += 1
            elif sf in FLAG_AMB:
                amb['gidx'].append(global_idx)
                amb['T'].append(t); amb['P'].append(p); amb['t_sec'].append(scan_time)
                amb['file_idx'].append(fi); amb['row'].append(row_idx)
                amb['spec'].append(intensity.astype(np.float32))
                n_amb_f += 1
        print(f'  [{fi+1:02d}/{len(file_list)}] {os.path.basename(fp)}: '
              f'rows={n_rows}  amb={n_amb_f}  ZA={n_za_f}  He={n_he_f}')

    # convert lists to arrays
    for d in (za, he):
        d['gidx'] = np.array(d['gidx'], dtype=np.int64)
        d['spec'] = np.array(d['spec'], dtype=np.float32)
        d['T']    = np.array(d['T'], dtype=np.float32)
        d['P']    = np.array(d['P'], dtype=np.float32)
    for k in ('gidx', 'T', 'P', 't_sec', 'file_idx', 'row'):
        amb[k] = np.array(amb[k], dtype=np.float64 if k in ('t_sec',) else np.int64 if k in ('gidx','file_idx','row') else np.float32)
    amb['spec'] = np.array(amb['spec'], dtype=np.float32)  # (N_amb, N_pix)
    return za, he, amb


def block_average(gidx, spec, T, P, gap=10):
    """AlphaExportWorker._block_average — group consecutive scans (gap>10 in global idx)."""
    if len(gidx) == 0:
        return np.array([]), np.array([]).reshape(0, spec.shape[1] if spec.ndim==2 else 0), np.array([]), np.array([])
    order = np.argsort(gidx)
    g = gidx[order]; S = spec[order]; T = T[order]; P = P[order]
    splits = np.where(np.diff(g) > gap)[0] + 1
    bg = np.array([float(b.mean()) for b in np.split(g, splits)])
    bs = np.array([np.nanmean(b, axis=0) for b in np.split(S, splits)])
    bt = np.array([float(np.nanmean(b)) for b in np.split(T, splits)])
    bp = np.array([float(np.nanmean(b)) for b in np.split(P, splits)])
    return bg, bs, bt, bp


# ─── R calibration & I₀ builder — mirror AlphaExportWorker lines 1153-1216 ───
def build_calibration(za, he, wave_nm, sigma_source, dark):
    """Returns (best_omr_d[N_pix], pchip_i0, pchip_t, pchip_p, za_gidx_bounds)."""
    za_g, za_s, za_t, za_p = block_average(za['gidx'], za['spec'], za['T'], za['P'])
    he_g, he_s, he_t, he_p = block_average(he['gidx'], he['spec'], he['T'], he['P'])
    print(f'  [I0] ZA {len(za["gidx"])}→{len(za_g)} blocks, He {len(he["gidx"])}→{len(he_g)} blocks')

    # dark subtract once (after block average)
    if dark is not None:
        za_s = za_s - dark
        he_s = he_s - dark

    # R-calibration: clean He mean, per-ZA-block omr_d
    i_he_clean = np.nanmean(he_s, axis=0)
    t_he_clean = float(np.nanmean(he_t))
    p_he_clean = float(np.nanmean(he_p))
    i_he_s = np.where(np.abs(i_he_clean) > 1.0, i_he_clean, 1.0)
    alpha_ray_he = get_alpha_rayleigh(wave_nm, t_he_clean, p_he_clean, 'helium', sigma_source)
    n_pix = len(wave_nm)

    candidates = []
    for i_za_b, t_za_b, p_za_b, g_za_b in zip(za_s, za_t, za_p, za_g):
        alpha_ray_za = get_alpha_rayleigh(wave_nm, t_za_b, p_za_b, 'zero_air', sigma_source)
        ratio = i_za_b / i_he_s
        with np.errstate(divide='ignore', invalid='ignore'):
            omr_d = RL_FACTOR * ((ratio * alpha_ray_za) - alpha_ray_he) / (1.0 - ratio)
        valid = np.isfinite(omr_d) & (omr_d > 0)
        # 진단용 완화: CAESAR Pro 기본은 0.90/1e-5 (high-finesse). 이 데이터는 omr_d~5e-5
        # (lower-finesse cavity)라 임계값 1e-3로 완화. 부호 음수만 제외하면 충분.
        if valid.mean() >= 0.50 and np.nanmean(omr_d[valid]) < 1e-3:
            x = np.arange(n_pix)
            omr_clean = np.interp(x, x[valid], omr_d[valid])
            candidates.append(omr_clean)
            print(f'    [cand] g~{g_za_b:.0f}  valid={valid.mean():.2f}  '
                  f'omr_d_mean={np.nanmean(omr_d[valid]):.3e}')

    if not candidates:
        raise RuntimeError('No valid R calibration')

    best_omr_d = np.median(np.array(candidates), axis=0)
    print(f'  [R-CAL] {len(candidates)} candidates  '
          f'omr_d mean={best_omr_d.mean():.3e}  Leff~{1/best_omr_d.mean()*1e-5:.2f} km')

    # PCHIP I0 interpolators (over global idx, same as AlphaExportWorker)
    pchip_i0 = PchipInterpolator(za_g, za_s, extrapolate=False) if len(za_g) >= 2 else None
    pchip_t  = PchipInterpolator(za_g, za_t, extrapolate=False) if len(za_g) >= 2 else None
    pchip_p  = PchipInterpolator(za_g, za_p, extrapolate=False) if len(za_g) >= 2 else None
    bounds = (za_g[0], za_g[-1], za_s[0], za_s[-1], float(za_t[0]), float(za_t[-1]),
              float(za_p[0]), float(za_p[-1]))
    return best_omr_d, pchip_i0, pchip_t, pchip_p, bounds


# ─── Pass 2: compute alpha for each ambient + 60s bin ────────────────────────
def compute_binned_alpha(amb, best_omr_d, pchip_i0, pchip_t, pchip_p,
                        bounds, wave_nm, sigma_source, dark, bin_sec=BIN_SECONDS):
    """Compute alpha from cached ambient spectra, accumulate into 60s bins.

    Returns (alpha_bins[N_bins, N_pix], t_bin_centers[N_bins], counts[N_bins]).
    """
    n_pix = len(wave_nm)
    g_min, g_max, i0_first, i0_last, t_first, t_last, p_first, p_last = bounds

    # 60s bin grid based on ambient time range
    t0 = amb['t_sec'].min(); t1 = amb['t_sec'].max()
    n_bins = int(np.ceil((t1 - t0) / bin_sec)) + 1
    sum_alpha = np.zeros((n_bins, n_pix), dtype=np.float64)
    count     = np.zeros(n_bins, dtype=np.int32)
    t_centers = t0 + (np.arange(n_bins) + 0.5) * bin_sec

    # Vectorize per-bin assignment
    bin_idx_all = np.clip(((amb['t_sec'] - t0) / bin_sec).astype(np.int64), 0, n_bins - 1)

    n_amb = len(amb['gidx'])
    for ai in range(n_amb):
        i_am = amb['spec'][ai]
        g    = float(amb['gidx'][ai])
        t_am = float(amb['T'][ai]); p_am = float(amb['P'][ai])

        if g < g_min:
            i0, t_i0, p_i0 = i0_first, t_first, p_first
        elif g > g_max:
            i0, t_i0, p_i0 = i0_last, t_last, p_last
        else:
            i0 = pchip_i0(g); t_i0 = float(pchip_t(g)); p_i0 = float(pchip_p(g))

        i_am_dc = (i_am - dark) if dark is not None else i_am
        i0_s   = np.where(i0      > 0, i0,      1e-9).astype(float)
        i_am_s = np.where(i_am_dc > 0, i_am_dc, 1e-9).astype(float)

        alpha_ref    = get_alpha_rayleigh(wave_nm, t_i0, p_i0, 'zero_air', sigma_source)
        alpha_sample = get_alpha_rayleigh(wave_nm, t_am, p_am, 'zero_air', sigma_source)
        alpha = ((best_omr_d / RL_FACTOR + alpha_ref)
                 * ((i0_s - i_am_s) / i_am_s)
                 - (alpha_sample - alpha_ref))

        bi = int(bin_idx_all[ai])
        sum_alpha[bi] += alpha
        count[bi]     += 1
        if (ai + 1) % 20000 == 0:
            print(f'    ambient {ai+1}/{n_amb}')

    avg = np.divide(sum_alpha, np.maximum(count, 1)[:, None],
                    out=np.zeros_like(sum_alpha), where=count[:,None] > 0)
    return avg, t_centers, count


# ─── MATLAB alpha loader ─────────────────────────────────────────────────────
def load_matlab_alpha(matlab_dir):
    files = sorted(glob.glob(os.path.join(matlab_dir, 'ch1_*.dat')))
    n = len(files)
    arr = np.zeros((n, 2048), dtype=np.float64)
    for i, fp in enumerate(files):
        arr[i] = np.loadtxt(fp)
    return arr


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    os.makedirs(PLOT_DIR, exist_ok=True)
    wave_nm = np.loadtxt(WV_FILE)
    assert wave_nm.shape == (2048,), f'wave_nm shape {wave_nm.shape}'

    print('=== Loading MATLAB alpha ===')
    alpha_mat = load_matlab_alpha(MATLAB_DIR)
    print(f'  MATLAB alpha shape: {alpha_mat.shape}')
    np.save(os.path.join(OUT_DIR, 'alpha_matlab.npy'), alpha_mat)
    np.save(os.path.join(OUT_DIR, 'wave_nm.npy'), wave_nm)

    file_list = sorted(glob.glob(os.path.join(RAW_DIR, RAW_GLOB)))
    print(f'\n=== Raw files: {len(file_list)} ===')

    print('\n=== Pass 1: collecting ZA/He/ambient metadata ===')
    za, he, amb = collect_scans(file_list)
    print(f'  totals: ZA={len(za["gidx"])}  He={len(he["gidx"])}  amb={len(amb["gidx"])}')

    # Original variants + flag-swap experiment
    # E/F: swap FLAG_ZA ↔ FLAG_HE (hypothesis: 2025-06-11 data has reversed convention)
    variants = [
        ('A_dark_none_sellmeier',    None,        'sellmeier', False),
        ('B_dark_1500_sellmeier',    DARK_CONST,  'sellmeier', False),
        ('C_dark_none_matlab',       None,        'matlab',    False),
        ('D_dark_1500_matlab',       DARK_CONST,  'matlab',    False),
        ('E_flagswap_dark_none_sellmeier', None,  'sellmeier', True),
        ('F_flagswap_dark_500_sellmeier',  500.0, 'sellmeier', True),
    ]

    for spec in variants:
        tag, dark, sigma_source, swap_flags = spec
        out_path = os.path.join(OUT_DIR, f'alpha_caesar_{tag}.npz')
        if os.path.exists(out_path):
            print(f'\n=== Variant {tag}  [skip, file exists] ===')
            continue
        print(f'\n=== Variant {tag}  dark={dark}  σ={sigma_source}  swap={swap_flags} ===')
        # swap_flags: relabel collected ZA→He and He→ZA (data already classified by flag)
        za_use, he_use = (he, za) if swap_flags else (za, he)
        omr, pi0, pt, pp, bounds = build_calibration(za_use, he_use, wave_nm, sigma_source, dark)
        alpha_bins, t_centers, counts = compute_binned_alpha(
            amb, omr, pi0, pt, pp, bounds, wave_nm, sigma_source, dark)
        np.savez(os.path.join(OUT_DIR, f'alpha_caesar_{tag}.npz'),
                 alpha=alpha_bins, t_centers=t_centers, counts=counts,
                 dark=(dark if dark is not None else -1), sigma_source=sigma_source)
        print(f'  saved alpha_caesar_{tag}.npz  shape={alpha_bins.shape}  '
              f'nonempty_bins={(counts>0).sum()}')


if __name__ == '__main__':
    main()
