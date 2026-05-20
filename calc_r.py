"""
calc_r.py  —  CAESAR 거울 반사율 계산

flag=500 (ZA 안정 측정) + flag=510 (He 안정 측정) 이 모두 있는 파일에서
파일당 R 값 하나를 계산해 저장한다.

사용법:
    python calc_r.py "H:\Yeosu_2026\CAESAR_Cold\2026-05" Cold
    python calc_r.py "H:\Yeosu_2026\CAESAR_Hot\2026-05"  Hot
"""

import os
import sys
import glob
import numpy as np

# ════════════════════════════════════════════════════════════════
#  사용자 설정
# ════════════════════════════════════════════════════════════════
CAVITY_LEN = 51.8      # cm
RL_FACTOR  = 0.933

FLAG_ZA = 500          # ZA 안정 측정 스캔
FLAG_HE = 510          # He 안정 측정 스캔

ROI2_START = 2053
ROI2_END   = 4101
PRESS_IDX  = 6156
TEMP_IDX   = 6157

OUTPUT_DIR = r"."
# ════════════════════════════════════════════════════════════════


# ── Rayleigh 산란 계수 ────────────────────────────────────────────

def rayleigh_alpha(wave_nm, temp_c, press_mbar, gas):
    wave_nm = np.asarray(wave_nm, dtype=float)
    lum = wave_nm / 1000.0                          # μm
    N = 2.68678e19 * (press_mbar / 1013.25) * (273.15 / (temp_c + 273.15))

    if gas == "zero_air":
        n1 = (0.80 * 1e-8 * (2726.7 + 15.286 / lum**2 + 0.131 / lum**4) +
              0.20 * 1e-8 * (2366.1 + 10.97  / lum**2 + 0.08  / lum**4))
        Fk = 1.034
    else:  # helium
        n1 = 1e-8 * (2283.0 + 1.8102e5 / (153.42 - (1.0 / lum)**2))
        Fk = 1.0

    wave_cm = wave_nm * 1e-7
    sigma = (8.0 * np.pi**3 * (2.0 * n1)**2 * Fk) / (3.0 * N**2 * wave_cm**4)
    return sigma * N


# ── 파일 읽기 ─────────────────────────────────────────────────────

def read_file(filepath):
    """flag=500 / flag=510 스캔만 읽어 반환."""
    za, he = [], []
    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            tokens = line.rstrip("\n").split("\t")
            if len(tokens) < ROI2_END:
                continue
            try:
                flag = int(tokens[4])
            except (ValueError, IndexError):
                continue
            if flag not in (FLAG_ZA, FLAG_HE):
                continue
            try:
                sp = np.array(tokens[ROI2_START:ROI2_END], dtype=float)
            except ValueError:
                continue
            try:
                p_raw = float(tokens[PRESS_IDX])
                t_raw = float(tokens[TEMP_IDX])
                press = p_raw * (0.01 * 6894.73326 / 100.0) if p_raw not in (0.0, 65535.0) else 1013.25
                temp  = t_raw / 100.0                        if t_raw not in (0.0, 65535.0) else 25.0
            except (ValueError, IndexError):
                press, temp = 1013.25, 25.0

            scan = {"sp": sp, "temp": temp, "press": press}
            (za if flag == FLAG_ZA else he).append(scan)
    return za, he


# ── R 계산 ────────────────────────────────────────────────────────

def calc_r(za_scans, he_scans, wave_nm):
    """ZA / He 스캔 목록으로 R 커브를 계산한다."""
    n_pix = min(len(za_scans[0]["sp"]), len(he_scans[0]["sp"]))

    i_za = np.median([s["sp"][:n_pix] for s in za_scans], axis=0)
    i_he = np.median([s["sp"][:n_pix] for s in he_scans], axis=0)

    t_za = np.mean([s["temp"]  for s in za_scans])
    p_za = np.mean([s["press"] for s in za_scans])
    t_he = np.mean([s["temp"]  for s in he_scans])
    p_he = np.mean([s["press"] for s in he_scans])

    if wave_nm is None:
        wave_nm = np.linspace(400.0, 500.0, n_pix)
    elif len(wave_nm) != n_pix:
        x = np.linspace(0, 1, len(wave_nm))
        wave_nm = np.interp(np.linspace(0, 1, n_pix), x, wave_nm)

    alpha_za = rayleigh_alpha(wave_nm, t_za, p_za, "zero_air")
    alpha_he = rayleigh_alpha(wave_nm, t_he, p_he, "helium")

    i_he_safe = np.where(np.abs(i_he) > 1.0, i_he, 1.0)
    ratio = i_za / i_he_safe

    with np.errstate(divide="ignore", invalid="ignore"):
        omr_d = RL_FACTOR * (ratio * alpha_za - alpha_he) / (1.0 - ratio)

    valid = np.isfinite(omr_d) & (omr_d > 0) & (omr_d < 1e-4)
    valid_frac = float(np.sum(valid)) / n_pix

    if np.any(~valid):
        x = np.arange(n_pix)
        omr_d = np.interp(x, x[valid], omr_d[valid])

    r_curve = np.clip(1.0 - omr_d * CAVITY_LEN, 0.0, 1.0)
    return wave_nm, r_curve, omr_d, valid_frac


# ── 저장 ─────────────────────────────────────────────────────────

def save_result(out_path, wave, r, omr_d, src_name, n_za, n_he, valid_frac):
    leff = 1.0 / (omr_d + 1e-30) * 1e-5
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(f"# Source : {src_name}\n")
        fh.write(f"# cavity={CAVITY_LEN}cm  RL={RL_FACTOR}"
                 f"  ZA스캔={n_za}  He스캔={n_he}  valid={valid_frac*100:.1f}%\n")
        fh.write("wavelength_nm\tR\tomr_d_cm-1\tLeff_km\n")
        for i in range(len(r)):
            fh.write(f"{wave[i]:.4f}\t{r[i]:.8f}\t{omr_d[i]:.6e}\t{leff[i]:.4f}\n")


# ── 메인 처리 ─────────────────────────────────────────────────────

def process(directory, channel, wave_cal_path=None):
    files = sorted(glob.glob(os.path.join(directory, "*.dat")))
    if not files:
        print(f"[오류] 파일 없음: {directory}")
        return

    wave_nm = None
    if wave_cal_path and os.path.isfile(wave_cal_path):
        wave_nm = np.loadtxt(wave_cal_path)
        print(f"파장 보정 로드: {os.path.basename(wave_cal_path)}")

    out_dir = os.path.join(OUTPUT_DIR, f"R_{channel}")
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n[{channel}] {len(files)}개 파일 처리 중...\n")
    ok = fail = skip = 0

    for fp in files:
        fname = os.path.basename(fp)
        za, he = read_file(fp)

        if not za or not he:
            skip += 1
            continue  # He 없는 파일은 건너뜀

        try:
            wave, r, omr_d, vf = calc_r(za, he, wave_nm)
            stem = os.path.splitext(fname)[0]
            out_path = os.path.join(out_dir, f"{stem}_R.dat")
            save_result(out_path, wave, r, omr_d, fname, len(za), len(he), vf)
            print(f"  ✅ {fname}  R_mean={np.mean(r):.6f}  valid={vf*100:.1f}%"
                  f"  ZA={len(za)}  He={len(he)}")
            ok += 1
        except Exception as e:
            print(f"  ❌ {fname}  {e}")
            fail += 1

    print(f"\n[{channel}] 완료 — 성공:{ok}  실패:{fail}  He없어서 스킵:{skip}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python calc_r.py <디렉토리> <채널명> [파장보정파일]")
        sys.exit(1)
    directory     = sys.argv[1]
    channel       = sys.argv[2]
    wave_cal_path = sys.argv[3] if len(sys.argv) > 3 else None
    process(directory, channel, wave_cal_path)
