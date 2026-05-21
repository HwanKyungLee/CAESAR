"""
Alpha Export — MATLAB-style cycle detection (He stable → ZA at He_end+25..55)
I0+omr_d 방식: 순차 per-cycle (각 bin은 직전 유효 R-cal 사이클의 ZA/omr_d 사용)
LEFF_MIN_KM=8 → anomalous R-cal(Leff<8km) 자동 제외
"""
import sys, os, glob
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

from worker import RayleighPhysics

RAW_DIR   = r"c:\Doasis_Work\CAESAR_Pro\raw(ex)\2025-06"
WV_FILE   = r"c:\Doasis_Work\CAESAR_Pro\아라온호 데이터분석\wavelength\wv_2025_Araon.txt"
OUT_DIR   = r"c:\Doasis_Work\CAESAR_Pro\raw(ex)"
PIXEL_MIN = 1453
PIXEL_MAX = 1646   # exclusive → px1453..1645

COL_FLAG  = 4
COL_PRESS = 6162   # raw × 0.01 psi → × 6894.73326/100 → mbar
COL_TEMP  = 6174   # raw / 100 → °C
COL_SPEC  = 2053   # CH1 스펙트럼 시작
SPEC_S    = COL_SPEC + PIXEL_MIN   # 3506
SPEC_E    = COL_SPEC + PIXEL_MAX   # 3699

FLAG_ZA_ALL     = {500, 501, 502, 503}
FLAG_HE_ALL     = {510, 511, 512, 513}
FLAG_HE_INJECT  = {510}   # 실제 He 주입(측정) 기간만 — block 검출 & 평균에 사용

RL       = 1.0000   # TEST: RL=1.0 (derived formula shows RL cancels in I0/Iamb ratio)
D        = 51.8     # cm
BIN_SIZE = 60
DARK     = 0.0      # 다크 보정 없음 (박사님과 동일 조건)
LEFF_MIN_KM = 8.0  # R-cal 유효 최소 Leff (km) → anomalous candidates(003,007) 자동 제외

# MATLAB-style 사이클 검출 파라미터
# MATLAB pix1=1600 (1-indexed) → 0-indexed 1599 → spec array index: 1599 - PIXEL_MIN(1453) = 146
REF_PIX          = 146    # spec 배열 내 참조 픽셀 (He/ZA 강도 기반 안정성 판단)
HE_STABLE_THRESH = 500.0  # 이동평균 최대값에서 500 counts 이내 → He stable
HE_MOVMEAN_WIN   = 5      # 이동평균 윈도우 (MATLAB: movmean 5)
ZA_OFF_START     = 25     # He stable 끝 이후 ZA 시작 오프셋
ZA_OFF_END       = 55     # ZA 끝 오프셋 (inclusive, 총 31 스캔: 25..55)

wv_all  = pd.read_csv(WV_FILE, sep=r'\s+', header=None, comment='#').iloc[:,0].values
wave_nm = wv_all[PIXEL_MIN:PIXEL_MAX]
n_pix   = len(wave_nm)
print(f"[파장] {wave_nm[0]:.2f}~{wave_nm[-1]:.2f} nm  n={n_pix}")


def read_file_fast(fp):
    rows = []
    with open(fp, 'r') as f:
        for line in f:
            parts = line.split()
            if len(parts) < 6175:
                continue
            try:
                flag  = int(float(parts[COL_FLAG]))
                raw_p = float(parts[COL_PRESS])
                raw_t = float(parts[COL_TEMP])
                p = raw_p * (0.01 * 6894.73326 / 100.0)
                t = raw_t / 100.0
                if raw_p in (65535, 0) or not np.isfinite(p): p = 1013.25
                if raw_t in (65535, 0) or not np.isfinite(t): t = 25.0
                spec = np.array(parts[SPEC_S:SPEC_E], dtype=float)
                if len(spec) != (PIXEL_MAX - PIXEL_MIN):
                    continue
            except (ValueError, IndexError):
                continue
            rows.append((flag, t, p, spec))
    return rows


def moving_mean_1d(arr, window):
    return pd.Series(arr.astype(float)).rolling(window, center=True, min_periods=1).mean().values


def detect_cycles(rows, file_global_start):
    """
    MATLAB Rs2_CAESAR 방식 사이클 검출:
      - He block(FLAG_HE_ALL) 검출 → 끝에서 +600 스캔 확장
      - 확장 범위에서 ref pixel 이동평균 → max에서 500 counts 이내 = stable He
      - ZA = He stable 마지막 스캔 + ZA_OFF_START .. ZA_OFF_END (31 스캔)
    Returns: list of (global_za_mid, he_avg_t, he_avg_p, he_avg_spec,
                                     za_avg_t, za_avg_p, za_avg_spec)
    """
    n = len(rows)
    if n == 0:
        return []

    flags        = np.array([r[0] for r in rows], dtype=int)
    ref_ints     = np.array([r[3][REF_PIX] for r in rows], dtype=float)
    in_he_all    = np.isin(flags, list(FLAG_HE_ALL))     # 512/510/513 전체
    in_he_inject = np.isin(flags, list(FLAG_HE_INJECT))  # flag=510만

    cycles = []
    i = 0
    while i < n:
        if not in_he_all[i]:
            i += 1
            continue

        # FLAG_HE_ALL 블록 시작 (512→510→513 전체 포함, MATLAB ihe_st 기준)
        he_start = i
        while i < n and in_he_all[i]:
            i += 1
        he_end = i - 1  # FLAG_HE_ALL 마지막 스캔 (inclusive)

        # 확장 범위: he_start ~ he_end+600
        ext_end = min(he_end + 600, n - 1)
        ext_idx = np.arange(he_start, ext_end + 1)
        ref_ext = ref_ints[ext_idx]

        mm = moving_mean_1d(ref_ext, HE_MOVMEAN_WIN)
        # He block 범위에서만 max 계산 (ZA > He 파일에서 ZA 피크에 끌리지 않도록)
        he_block_len = he_end - he_start + 1
        max_mm = float(np.max(mm[:he_block_len]))

        # He block 내 stable 검출
        stable_mask_all  = (max_mm - mm[:he_block_len]) < HE_STABLE_THRESH
        stable_local_all = np.where(stable_mask_all)[0]

        if len(stable_local_all) == 0:
            print(f"    [경고] He block (local {he_start}..{he_end}): stable 없음 → 스킵")
            i = ext_end + 1
            continue

        # he_stable_end: He block 끝에서 출발해 ZA fill 초입까지 점진적 확장
        # MATLAB은 He 이후 ZA fill 초기에 강도가 He와 비슷하면 stable 연장
        # mm ≤ max_mm 조건으로 ZA > He 파일(ZA fill이 He보다 밝음)은 자동 차단
        he_block_last_file = int(ext_idx[he_block_len - 1])
        he_stable_end = he_block_last_file
        for k in range(1, 11):  # 최대 10스캔 확장
            probe_mm_idx = he_block_len - 1 + k
            probe_file   = he_block_last_file + k
            if probe_mm_idx >= len(mm) or probe_file >= n:
                break
            probe_mm = float(mm[probe_mm_idx])
            if (max_mm - probe_mm) < HE_STABLE_THRESH and probe_mm <= max_mm + 0.5:
                he_stable_end = probe_file
            else:
                break

        # He 평균: stable 범위 중 flag=510 스캔만 (오염 없는 He 주입 기간)
        he_stable_file_idx_all = ext_idx[:he_block_len][stable_local_all]
        inject_mask = in_he_inject[he_stable_file_idx_all]
        he_stable_file_idx = he_stable_file_idx_all[inject_mask]
        if len(he_stable_file_idx) == 0:
            # flag=510이 없으면 stable 전체로 fallback
            he_stable_file_idx = he_stable_file_idx_all

        he_specs = np.array([rows[j][3] for j in he_stable_file_idx], dtype=float)
        he_ts    = np.array([rows[j][1] for j in he_stable_file_idx])
        he_ps    = np.array([rows[j][2] for j in he_stable_file_idx])
        he_avg_spec = np.mean(he_specs, axis=0)
        he_avg_t    = float(np.mean(he_ts))
        he_avg_p    = float(np.mean(he_ps))

        # ZA 범위: he_stable_end + ZA_OFF_START .. ZA_OFF_END
        za_s = he_stable_end + ZA_OFF_START
        za_e = min(he_stable_end + ZA_OFF_END, n - 1)

        if za_s >= n:
            print(f"    [경고] ZA 범위 ({za_s}..{za_e}) 파일 밖 → 스킵")
            i = ext_end + 1
            continue

        za_idx   = np.arange(za_s, za_e + 1)
        za_specs = np.array([rows[j][3] for j in za_idx], dtype=float)
        za_ts    = np.array([rows[j][1] for j in za_idx])
        za_ps    = np.array([rows[j][2] for j in za_idx])
        za_flags = flags[za_idx]

        za_avg_spec  = np.mean(za_specs, axis=0)
        za_avg_t     = float(np.mean(za_ts))
        za_avg_p     = float(np.mean(za_ps))
        za_local_mid = float(np.median(za_idx))
        global_za_mid = file_global_start + za_local_mid

        flag_counts = {f: int(np.sum(za_flags == f)) for f in np.unique(za_flags)}
        print(f"    He stable: {len(he_stable_file_idx)} scans (local {int(he_stable_file_idx[0])}..{he_stable_end})"
              f"  ZA: local {za_s}..{za_e} ({len(za_idx)} scans) flags={flag_counts}")

        cycles.append((global_za_mid, he_avg_t, he_avg_p, he_avg_spec,
                       za_avg_t, za_avg_p, za_avg_spec))

        i = ext_end + 1

    return cycles


raw_files = sorted(glob.glob(os.path.join(RAW_DIR, "2025-06-10-*.dat")))
print(f"[입력] {len(raw_files)}개 파일")

# ─── Pass 1: 파일별 읽기 & MATLAB-style 사이클 검출 ──────────────────────────
print("\n[Pass 1] 파일 읽기 및 사이클 검출...")

calib_cycles = []   # (gza_mid, omr_d_arr) — 유효 R-cal만, 시간순
za_cycles    = []   # (gza_mid, za_spec, za_t, za_p) — 모든 ZA 주입 (R-cal 실패 포함)
amb_buffer   = []   # (fp, global_idx, t, p, spec)

global_idx = 0

for fp in raw_files:
    rows = read_file_fast(fp)
    file_global_start = global_idx
    n_rows = len(rows)
    fname  = os.path.basename(fp)
    print(f"\n  {fname}: {n_rows} scans")

    flags_arr = np.array([r[0] for r in rows], dtype=int)
    in_za = np.isin(flags_arr, list(FLAG_ZA_ALL))
    in_he = np.isin(flags_arr, list(FLAG_HE_ALL))

    for local_i, (flag, t, p, spec) in enumerate(rows):
        if not in_za[local_i] and not in_he[local_i]:
            amb_buffer.append((fp, file_global_start + local_i, t, p, spec))

    global_idx += n_rows

    cycles = detect_cycles(rows, file_global_start)
    if not cycles:
        print(f"    → 사이클 없음")
        continue

    for (gza_mid, he_t, he_p, he_spec, za_t, za_p, za_spec) in cycles:
        # ZA는 R-cal 성공 여부와 무관하게 항상 기록
        za_cycles.append((gza_mid, za_spec, za_t, za_p))

        # R-cal 계산
        alpha_ray_za = RayleighPhysics.get_alpha_rayleigh(wave_nm, za_t, za_p, 'air')
        alpha_ray_he = RayleighPhysics.get_alpha_rayleigh(wave_nm, he_t, he_p, 'helium')
        za_dc  = za_spec  - DARK
        he_dc  = he_spec  - DARK
        i_he_s = np.where(np.abs(he_dc) > 1.0, he_dc, 1.0)
        ratio  = za_dc / i_he_s
        with np.errstate(divide='ignore', invalid='ignore'):
            omr_d = ((ratio * alpha_ray_za) - alpha_ray_he) / (1.0 - ratio)
        valid = np.isfinite(omr_d) & (omr_d > 0)
        omrd_max = 1e-5 / LEFF_MIN_KM  # Leff_min → omr_d 상한 (8km → 1.25e-6)
        if valid.mean() >= 0.90 and np.nanmean(omr_d[valid]) < omrd_max:
            x = np.arange(n_pix)
            omr_d_clean = np.interp(x, x[valid], omr_d[valid])
            leff_c = np.mean(1.0 / omr_d_clean) * 1e-5
            r_c    = 1.0 - np.mean(omr_d_clean) * D
            calib_cycles.append((gza_mid, omr_d_clean))
            print(f"    → R-cal OK: Leff={leff_c:.2f} km  R={r_c:.6f}"
                  f"  He T={he_t:.1f}°C P={he_p:.1f}mbar"
                  f"  ZA T={za_t:.1f}°C P={za_p:.1f}mbar")
        else:
            print(f"    → R-cal FAIL (valid={valid.mean()*100:.0f}%"
                  f"  omr_mean={np.nanmean(omr_d[valid]) if valid.any() else float('nan'):.2e})")

leff_list = [np.mean(1.0 / c[1]) * 1e-5 for c in calib_cycles]
print(f"\n  Ambient 총 {len(amb_buffer)}행")
print(f"  ZA 사이클 {len(za_cycles)}개 (R-cal 성공/실패 포함)")
print(f"  유효 R-cal {len(calib_cycles)}개  Leff={[f'{v:.2f}' for v in leff_list]} km")

# ─── R-cal: 순차 per-cycle ───────────────────────────────────────────────────
if not calib_cycles:
    raise RuntimeError("유효한 R-cal 사이클이 없습니다. LEFF_MIN_KM 또는 데이터 확인 필요.")
print(f"[R-CAL] 순차 per-cycle: {len(calib_cycles)}개 유효 사이클 (시간순)")
for gzm, omrd in calib_cycles:
    leff_c = np.mean(1.0 / omrd) * 1e-5
    r_c    = 1.0 - np.mean(omrd) * D
    print(f"  gza_mid={gzm:.0f}  Leff={leff_c:.2f} km  R={r_c:.6f}")
print(f"[ZA]    총 {len(za_cycles)}개 ZA 사이클 → I0으로 순차 사용")

# ─── Pass 2: bin별 강도 평균 → alpha 계산 (파일별 고정 I0 + 상수 omr_d) ─────
print(f"\n[Pass 2] {len(amb_buffer)}개 ambient — {BIN_SIZE}스캔 bin 강도평균 후 alpha 계산...")
print(f"         I0+omr_d: 순차 per-cycle (직전 유효 R-cal 사이클 적용)")

n_bins     = len(amb_buffer) // BIN_SIZE
alpha_bins = []

for bn in range(n_bins):
    chunk = amb_buffer[bn * BIN_SIZE:(bn + 1) * BIN_SIZE]

    i_stack    = np.array([row[4] for row in chunk], dtype=float)
    i_amb_mean = np.mean(i_stack, axis=0)
    T_avg = float(np.mean([row[2] for row in chunk]))
    P_avg = float(np.mean([row[3] for row in chunk]))

    fp_first = chunk[0][0]

    bin_global_mid = chunk[BIN_SIZE // 2][1]   # (fp, global_idx, t, p, spec)[1]

    # I0: 직전 ZA 주입 (R-cal 실패 포함, 모든 ZA 사이클에서 조회)
    current_za = za_cycles[0]                   # forward fallback
    for za in za_cycles:
        if za[0] <= bin_global_mid:
            current_za = za
        else:
            break
    _, i0_interp, t_i0, p_i0 = current_za

    # omr_d: 직전 유효 R-cal (실패 파일은 마지막 성공 R-cal 이어받음)
    current_rcal = calib_cycles[0]              # forward fallback
    for rcal in calib_cycles:
        if rcal[0] <= bin_global_mid:
            current_rcal = rcal
        else:
            break
    _, omr_d_bin = current_rcal

    i0_dc   = i0_interp  - DARK
    i_am_dc = i_amb_mean - DARK
    i0_s    = np.where(i0_dc   > 0, i0_dc,   1e-9).astype(float)
    i_am_s  = np.where(i_am_dc > 0, i_am_dc, 1e-9).astype(float)

    alpha_ref    = RayleighPhysics.get_alpha_rayleigh(wave_nm, t_i0, p_i0, 'air')
    alpha_sample = RayleighPhysics.get_alpha_rayleigh(wave_nm, T_avg, P_avg, 'air')

    alpha = (RL * (omr_d_bin + alpha_ref) * ((i0_s - i_am_s) / i_am_s)
             - (alpha_sample - alpha_ref))

    alpha_bins.append((bn, fp_first, T_avg, P_avg, alpha))

alpha_buffer = {}
for bn, fp, T_avg, P_avg, alpha in alpha_bins:
    alpha_buffer.setdefault(fp, []).append((bn, T_avg, P_avg, alpha))

# ─── 저장 ─────────────────────────────────────────────────────────────────────
pix_min = PIXEL_MIN
for fp, rows in alpha_buffer.items():
    stem     = os.path.splitext(os.path.basename(fp))[0]
    out_path = os.path.join(OUT_DIR, f"{stem}_alpha_trace.dat")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"# CAESAR Pro Alpha Export (MATLAB-style cycle, per-file step I0) — {os.path.basename(fp)}\n")
        f.write(f"# RL_factor={RL}  d={D} cm  BIN_SIZE={BIN_SIZE}\n")
        f.write(f"# I0+R_mode=per-cycle-sequential  LEFF_MIN_KM={LEFF_MIN_KM}  ZA_offset={ZA_OFF_START}..{ZA_OFF_END}\n")
        f.write(f"# dark_correction=scalar:{DARK:.0f} counts\n")
        f.write(f"# Calibration: I0=per-ZA-cycle({len(za_cycles)}) omr_d=per-valid-Rcal({len(calib_cycles)})"
                f"  Leff={min(leff_list):.2f}~{max(leff_list):.2f} km\n")
        f.write(f"# averaging: intensity-first (MATLAB-compatible)\n")
        wv_str = '\t'.join(f"{w:.4f}" for w in wave_nm)
        f.write(f"# wavelength_nm:\t{wv_str}\n")
        f.write("bin_idx\tT_C\tP_mbar\t" +
                '\t'.join(f"px{pix_min+j}" for j in range(n_pix)) + "\n")
        for bn, T, P, alpha in rows:
            vals = '\t'.join(f"{v:.6e}" for v in alpha)
            f.write(f"{bn}\t{T:.2f}\t{P:.2f}\t{vals}\n")
    print(f"  저장: {out_path}  ({len(rows)} bins)")

# ─── 요약 ──────────────────────────────────────────────────────────────────────
print("\n[파일별 alpha 요약]")
print(f"  {'파일':>4}  {'n_bins':>6}  {'mean(m-1)':>12}  {'std':>12}")
for fp in raw_files:
    rows = alpha_buffer.get(fp, [])
    if not rows:
        print(f"  {os.path.basename(fp).split('-')[-1].replace('.dat',''):>4}  {'없음':>6}")
        continue
    means = [np.nanmean(r[3]) for r in rows]
    fnum  = os.path.basename(fp).split('-')[-1].replace('.dat','')
    print(f"  {fnum:>4}  {len(rows):6d}  {np.nanmean(means):12.4e}  {np.nanstd(means):12.4e}")

print(f"\n  전체 bin: {n_bins}  (ambient {len(amb_buffer)}행 중 {n_bins*BIN_SIZE}행 사용)")
print("\n[완료]")
