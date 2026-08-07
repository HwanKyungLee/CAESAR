"""
CAESAR Pro 알파 검증 — 2026-05-17 cold setup (high contrast He/ZA)
====================================================================
이 데이터는 He I_peak ≈ 60k, ZA I_peak ≈ 47k (28% contrast)로 R-cal이 안정적.
**Strict flag {500} ZA / {510} He** 적용 (사용자 지정: 501/502/503은 setflow/wait
상태라 cavity가 아직 ZA로 안 찬 transition → I0 오염 원인).

산출
----
alpha_caesar.npz       (N_bins, N_pix) 60s 빈 평균 알파, t_centers, counts
calib.npz              best_omr_d, ZA/He block 통계
mean_spectra.npz       he_mean, za_mean, amb_mean, amb_min
plots/                 진단 플롯
report.txt             텍스트 요약
"""
from __future__ import annotations
import os, sys, glob, numpy as np
from scipy.interpolate import PchipInterpolator
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

CAESAR_REPO = r'C:\Doasis_Work\CAESAR\CAESAR'
sys.path.insert(0, CAESAR_REPO)
from core.data_io import DataIO
from core.physics import RayleighPhysics
# alpha 공식 자체(강도보정 + Rayleigh 스케일링 + BBCEAS 조합)는 gui/worker.py의
# AlphaExportWorker(Pass 2)와 물리적으로 동일해야 하므로, 손으로 다시 짜지 않고
# 거기서 뽑아둔 순수함수를 그대로 가져다 쓴다(단일 출처 — 두 벌로 갈라질 위험 제거).
from gui.worker import _correct_intensity_plain, _alpha_za_plain

# ─── User-specified paths ────────────────────────────────────────────────────
RAW_DIR    = r'F:\CAESAR cold\2026-05'
RAW_GLOB   = '2026-05-17-*.dat'       # 1 day; expand to 2026-05-*.dat for full week
WV_FILE    = r'F:\CAESAR cold\Calib_20260523_Hg_400-497nm_Poly2_new.txt'
OUT_DIR    = r'D:\GHL\CAESAR_Pro_validation_2026_05'
PLOT_DIR   = os.path.join(OUT_DIR, 'plots')
os.makedirs(PLOT_DIR, exist_ok=True)

CHANNEL    = 1
PIXEL_MIN  = 0
PIXEL_MAX  = 2048
RL_FACTOR  = 0.9764               # cold setup mirror R (HANDOFF.md note)
# ★ STRICT flags per user correction: 500/510만 pure injecting; 501-503/511-513은 transition
FLAG_ZA    = {500}
FLAG_HE    = {510}
FLAG_AMB   = {1}
BIN_SEC    = 60.0

# ─── Load wavelength (skip header lines starting with #) ─────────────────────
wave_nm = np.loadtxt(WV_FILE, comments='#')
assert wave_nm.shape == (2048,), f'wave_nm shape {wave_nm.shape}'
print(f'wavelength range: {wave_nm[0]:.2f} ~ {wave_nm[-1]:.2f} nm  ({len(wave_nm)} pix)')

# ─── Pass 1: collect ZA / He / ambient ───────────────────────────────────────
def block_average(gidx_list, spec_list, t_list, p_list, gap=10):
    if len(gidx_list) == 0:
        return np.array([]), np.zeros((0, 2048)), np.array([]), np.array([])
    g = np.asarray(gidx_list, dtype=float)
    order = np.argsort(g)
    g = g[order]
    S = np.array(spec_list, dtype=np.float64)[order]
    T = np.array(t_list, dtype=float)[order]
    P = np.array(p_list, dtype=float)[order]
    splits = np.where(np.diff(g) > gap)[0] + 1
    bg = np.array([float(b.mean()) for b in np.split(g, splits)])
    bs = np.array([np.nanmean(b, axis=0) for b in np.split(S, splits)])
    bt = np.array([float(np.nanmean(b)) for b in np.split(T, splits)])
    bp = np.array([float(np.nanmean(b)) for b in np.split(P, splits)])
    return bg, bs, bt, bp


def collect(file_list):
    za = dict(g=[], s=[], T=[], P=[])
    he = dict(g=[], s=[], T=[], P=[])
    amb = dict(g=[], T=[], P=[], t_sec=[], spec=[])
    global_idx = 0
    for fi, fp in enumerate(file_list):
        entries = DataIO.expand_to_scan_list(fp)
        n_rows = len(entries)
        try:
            mtime = os.path.getmtime(fp)
        except Exception:
            mtime = float(fi) * 3600.0
        n_za = n_he = n_amb = 0
        # Also count rejected sub-flags for visibility
        n_rejected = 0
        for _, row_idx in entries:
            global_idx += 1
            try:
                _, intensity, sf, t, p = DataIO.load_measurement_with_hk(
                    fp, PIXEL_MIN, PIXEL_MAX, row_index=row_idx, channel=CHANNEL)
            except Exception:
                continue
            scan_time = mtime - (n_rows - row_idx) * (3600.0 / max(n_rows, 1))
            if sf in FLAG_ZA:
                za['g'].append(global_idx); za['s'].append(intensity.astype(np.float32))
                za['T'].append(t); za['P'].append(p); n_za += 1
            elif sf in FLAG_HE:
                he['g'].append(global_idx); he['s'].append(intensity.astype(np.float32))
                he['T'].append(t); he['P'].append(p); n_he += 1
            elif sf in FLAG_AMB:
                amb['g'].append(global_idx); amb['T'].append(t); amb['P'].append(p)
                amb['t_sec'].append(scan_time); amb['spec'].append(intensity.astype(np.float32))
                n_amb += 1
            elif sf in {501, 502, 503, 511, 512, 513}:
                n_rejected += 1
        print(f'  [{fi+1:02d}/{len(file_list)}] {os.path.basename(fp)}: '
              f'rows={n_rows}  amb={n_amb}  ZA(500)={n_za}  He(510)={n_he}  rejected_sub={n_rejected}')
    for d in (za, he):
        d['g'] = np.array(d['g'], dtype=np.int64)
        d['s'] = np.array(d['s'], dtype=np.float32)
        d['T'] = np.array(d['T'], dtype=np.float32)
        d['P'] = np.array(d['P'], dtype=np.float32)
    amb['g']     = np.array(amb['g'], dtype=np.int64)
    amb['T']     = np.array(amb['T'], dtype=np.float32)
    amb['P']     = np.array(amb['P'], dtype=np.float32)
    amb['t_sec'] = np.array(amb['t_sec'], dtype=np.float64)
    amb['spec']  = np.array(amb['spec'], dtype=np.float32)
    return za, he, amb


# ─── R-calibration (mirror AlphaExportWorker, relaxed threshold) ─────────────
def build_calib(za, he, wave_nm):
    za_g, za_s, za_t, za_p = block_average(za['g'], za['s'], za['T'], za['P'])
    he_g, he_s, he_t, he_p = block_average(he['g'], he['s'], he['T'], he['P'])
    print(f'  ZA: {len(za["g"])}→{len(za_g)} blocks   He: {len(he["g"])}→{len(he_g)} blocks')
    i_he_mean = np.nanmean(he_s, axis=0)
    t_he_mean = float(np.nanmean(he_t)); p_he_mean = float(np.nanmean(he_p))
    i_he_s = np.where(np.abs(i_he_mean) > 1.0, i_he_mean, 1.0)
    alpha_ray_he = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_he_mean, p_he_mean, 'helium')
    n_pix = len(wave_nm)
    cands = []
    cand_info = []
    for i_za_b, t_b, p_b, g_b in zip(za_s, za_t, za_p, za_g):
        a_ray_za = RayleighPhysics.get_alpha_rayleigh(wave_nm, float(t_b), float(p_b), 'zero_air')
        ratio = i_za_b / i_he_s
        with np.errstate(divide='ignore', invalid='ignore'):
            omr = RL_FACTOR * ((ratio * a_ray_za) - alpha_ray_he) / (1.0 - ratio)
        valid = np.isfinite(omr) & (omr > 0)
        # relaxed threshold (R~0.97 setup, so omr_d~(1-R)/d up to 3e-4 with d=100cm)
        if valid.mean() >= 0.50 and np.nanmean(omr[valid]) < 1e-3:
            x = np.arange(n_pix)
            omr_clean = np.interp(x, x[valid], omr[valid])
            cands.append(omr_clean)
            cand_info.append((float(g_b), float(valid.mean()), float(np.nanmean(omr[valid]))))
    if not cands:
        raise RuntimeError('No valid R-cal candidates')
    best_omr = np.median(np.array(cands), axis=0)
    print(f'  [R-CAL] {len(cands)} candidates  best_omr mean={best_omr.mean():.3e}  '
          f'Leff~{1/best_omr.mean()*1e-5:.2f} km')
    # interpolators for PCHIP I0
    pi0 = PchipInterpolator(za_g, za_s, extrapolate=False) if len(za_g) >= 2 else None
    pt  = PchipInterpolator(za_g, za_t, extrapolate=False) if len(za_g) >= 2 else None
    pp  = PchipInterpolator(za_g, za_p, extrapolate=False) if len(za_g) >= 2 else None
    bounds = (za_g[0], za_g[-1], za_s[0], za_s[-1],
              float(za_t[0]), float(za_t[-1]), float(za_p[0]), float(za_p[-1]))
    return best_omr, pi0, pt, pp, bounds, dict(
        za_blocks=za_g, za_specs=za_s, za_t=za_t, za_p=za_p,
        he_blocks=he_g, he_specs=he_s, he_t=he_t, he_p=he_p,
        cands=np.array(cands), cand_info=cand_info)


# ─── Alpha computation + 60s binning ─────────────────────────────────────────
def compute_binned_alpha(amb, best_omr, pi0, pt, pp, bounds, wave_nm, dark=None):
    g_min, g_max, i0_first, i0_last, t_first, t_last, p_first, p_last = bounds
    t0 = amb['t_sec'].min(); t1 = amb['t_sec'].max()
    n_bins = int(np.ceil((t1 - t0) / BIN_SEC)) + 1
    n_pix = len(wave_nm)
    sum_a = np.zeros((n_bins, n_pix), dtype=np.float64)
    cnt   = np.zeros(n_bins, dtype=np.int32)
    t_c   = t0 + (np.arange(n_bins) + 0.5) * BIN_SEC
    bin_idx = np.clip(((amb['t_sec'] - t0) / BIN_SEC).astype(np.int64), 0, n_bins - 1)
    n_amb = len(amb['g'])
    # STP(0℃,1013.25mbar) 기준 σ(λ)·N0 를 1회만 계산해두고, 스캔마다는 T/P 스칼라
    # 배율만 곱한다(AlphaExportWorker._run_inner의 _ZA_REF 최적화와 동일 — 매 스캔
    # get_alpha_rayleigh를 다시 부르는 것과 수학적으로 완전히 동일, 결과는 안 바뀜).
    za_ref = RayleighPhysics.get_alpha_rayleigh(wave_nm, 0.0, 1013.25, 'zero_air')
    for ai in range(n_amb):
        i_am = amb['spec'][ai]
        g    = float(amb['g'][ai])
        t_am = float(amb['T'][ai]); p_am = float(amb['P'][ai])
        if g < g_min:
            i0, t_i0, p_i0 = i0_first, t_first, p_first
        elif g > g_max:
            i0, t_i0, p_i0 = i0_last, t_last, p_last
        else:
            i0 = pi0(g); t_i0 = float(pt(g)); p_i0 = float(pp(g))
        i_am_dc = _correct_intensity_plain(i_am, dark, 1.0, None, 1.0, 0.0)
        i0_s   = np.where(i0      > 0, i0,      1e-9).astype(float)
        i_am_s = np.where(i_am_dc > 0, i_am_dc, 1e-9).astype(float)
        a_ref  = _alpha_za_plain(t_i0, p_i0, za_ref)
        a_smp  = _alpha_za_plain(t_am, p_am, za_ref)
        alpha = ((best_omr / RL_FACTOR + a_ref) * ((i0_s - i_am_s) / i_am_s)
                 - (a_smp - a_ref))
        bi = int(bin_idx[ai])
        sum_a[bi] += alpha; cnt[bi] += 1
        if (ai + 1) % 10000 == 0:
            print(f'    {ai+1}/{n_amb}')
    avg = np.divide(sum_a, np.maximum(cnt, 1)[:, None],
                    out=np.zeros_like(sum_a), where=cnt[:,None] > 0)
    return avg, t_c, cnt


# ─── Main ────────────────────────────────────────────────────────────────────
files = sorted(glob.glob(os.path.join(RAW_DIR, RAW_GLOB)))
print(f'Files: {len(files)}')

print('\n=== Pass 1 ===')
za, he, amb = collect(files)
print(f'Totals: ZA={len(za["g"])}  He={len(he["g"])}  amb={len(amb["g"])}')

print('\n=== R-calibration ===')
best_omr, pi0, pt, pp, bounds, calib_info = build_calib(za, he, wave_nm)

print('\n=== Compute alpha + 60s bins ===')
alpha_bins, t_centers, counts = compute_binned_alpha(amb, best_omr, pi0, pt, pp, bounds, wave_nm)
print(f'alpha_bins shape: {alpha_bins.shape}  nonempty: {(counts>0).sum()}')

# Save core arrays
np.savez(os.path.join(OUT_DIR, 'alpha_caesar.npz'),
         alpha=alpha_bins, t_centers=t_centers, counts=counts, wave_nm=wave_nm)
np.savez(os.path.join(OUT_DIR, 'calib.npz'),
         best_omr=best_omr, **{k: v for k, v in calib_info.items() if k != 'cand_info'})
he_mean = np.nanmean(calib_info['he_specs'], axis=0)
za_mean = np.nanmean(calib_info['za_specs'], axis=0)
amb_mean = np.nanmean(amb['spec'], axis=0)
amb_min  = np.nanmin(amb['spec'], axis=0)
np.savez(os.path.join(OUT_DIR, 'mean_spectra.npz'),
         he=he_mean, za=za_mean, amb_mean=amb_mean, amb_min=amb_min, wave_nm=wave_nm)
print(f'\nSaved arrays to {OUT_DIR}')
