import os
import glob
import sys
import numpy as np

try:
    from reflectance_calc import ReflectanceCalculator
except ImportError:
    print("[오류] reflectance_calc.py를 찾을 수 없습니다.")
    sys.exit(1)

# ════════════════════════════════════════════════════════════════
#  사용자 설정
# ════════════════════════════════════════════════════════════════
COLD_DIR = r"H:\Yeosu_2026\CAESAR_Cold\2026-05"
HOT_DIR  = r"H:\Yeosu_2026\CAESAR_Hot\2026-05"

CAVITY_LEN = 51.8
RL_FACTOR  = 0.933
PIXEL_MIN = 0
PIXEL_MAX = None

WAVE_CAL_COLD = r"C:\CAESAR_pro_package\reference\wavelength_cal\CAESAR cold\Calib_20260507_Hg_399-494nm_Poly2.txt"
WAVE_CAL_HOT  = r"C:\CAESAR_pro_package\reference\wavelength_cal\CAESAR hot\roi1\Calib_20260403_Hg_400-499nm(roi1).txt"

OUTPUT_DIR   = r"."
FLAG_ZA      = 500   # ZA 안정 측정 (Injecting)
FLAG_HE      = 510   # He 안정 측정 (Injecting)
FILE_PATTERN = "*.dat"

# ── HK 컬럼 인덱스 (2026-05-18/19 실측 샘플 검증) ──────────────────────────
#  Cold 채널 (노트북, 단일 캐비티, 비가열)
COL_PRESS_COLD = 6160   # 압력: ×0.6895 → ~1010 mbar
COL_TEMP_COLD  = 6173   # 캐비티 온도: ÷100 → ~24°C  ※ Cold 전용 컬럼, 확인 권장
#  Hot 채널 (데스크탑, 이중 캐비티: ANs 오븐180°C / PNs 오븐300°C, 캐비티 75°C)
COL_PRESS_HOT  = 6162   # 압력: ×0.6895 → ~971 mbar
COL_TEMP_HOT   = 6155   # 캐비티 온도: ÷100 → ~75°C  ✓ 오븐온도(6154=180°C, 6151=300°C)로 교차검증
# ════════════════════════════════════════════════════════════════


def _extract_spectrum_and_hk(tokens, col_press=COL_PRESS_COLD, col_temp=COL_TEMP_COLD):
    """한 행(토큰 리스트)에서 스펙트럼과 압력·온도를 추출한다."""
    t_c, p_mbar = 25.0, 1013.25
    n = len(tokens)
    if n >= 6175:
        raw = np.array([float(t) if t.strip() else np.nan for t in tokens])
        intensity_full = raw[2053:4101]
        raw_p = raw[col_press] if col_press < n else np.nan
        raw_t = raw[col_temp]  if col_temp  < n else np.nan
        if np.isfinite(raw_p) and raw_p not in (0.0, 65535.0):
            p_mbar = raw_p * (0.01 * 6894.73326 / 100.0)
        if np.isfinite(raw_t) and raw_t not in (0.0, 65535.0):
            t_c = raw_t / 100.0
    else:
        intensity_full = np.array(tokens[5:], dtype=float)

    intensity_full = intensity_full[np.isfinite(intensity_full)]
    return intensity_full[PIXEL_MIN:PIXEL_MAX], t_c, p_mbar


def read_all_scans(filepath, col_press=COL_PRESS_COLD, col_temp=COL_TEMP_COLD):
    """파일에서 flag=FLAG_ZA / flag=FLAG_HE 스캔을 읽어 (za, he) 리스트로 반환.
    각 항목: (spectrum_array, temp_c, press_mbar)
    """
    za, he = [], []
    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            tokens = line.strip().split("\t")
            if len(tokens) < 6:
                continue
            try:
                flag = int(tokens[4].strip())
                if flag == FLAG_ZA:
                    sp, t, p = _extract_spectrum_and_hk(tokens, col_press, col_temp)
                    if len(sp) > 0:
                        za.append((sp, t, p))
                elif flag == FLAG_HE:
                    sp, t, p = _extract_spectrum_and_hk(tokens, col_press, col_temp)
                    if len(sp) > 0:
                        he.append((sp, t, p))
            except:
                continue
    return za, he


def save_r_dat(out_path, wave, r, omr_d, src_label, n_za, n_he):
    leff = np.where(omr_d > 1e-10, 1.0 / omr_d * 1e-5, np.nan)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(f"# Source: {src_label}\n")
        fh.write(f"# cavity={CAVITY_LEN}cm  RL={RL_FACTOR}  ZA={n_za}스캔  He={n_he}스캔\n")
        fh.write("wavelength_nm\tR\tomr_d_cm-1\tLeff_km\n")
        for i in range(len(r)):
            fh.write(f"{wave[i]:.4f}\t{r[i]:.8f}\t{omr_d[i]:.6e}\t{leff[i]:.4f}\n")


def process_channel(channel_name, directory, wave_cal_path, output_dir,
                    col_press=None, col_temp=None):
    """채널별 압력·온도 컬럼을 자동 선택하거나 명시적으로 지정할 수 있다."""
    if col_press is None:
        col_press = COL_PRESS_HOT if channel_name.lower() == "hot" else COL_PRESS_COLD
    if col_temp is None:
        col_temp  = COL_TEMP_HOT  if channel_name.lower() == "hot" else COL_TEMP_COLD
    print(f"\n[시작] {channel_name} 처리  P=col{col_press}  T=col{col_temp}")

    wave_nm = np.loadtxt(wave_cal_path) if wave_cal_path and os.path.exists(wave_cal_path) else None
    files = sorted(glob.glob(os.path.join(directory, FILE_PATTERN)))

    last_he = []   # 가장 최근 파일의 He 스캔 (다음 파일들에서 재사용)
    saved = fail = skip = 0

    for fp in files:
        fname = os.path.basename(fp)
        za, he = read_all_scans(fp, col_press, col_temp)

        if he:
            last_he = he   # 새 He 캘리브레이션 갱신

        if not za or not last_he:
            skip += 1
            continue

        try:
            rc = ReflectanceCalculator(cavity_len=CAVITY_LEN, rl_factor=RL_FACTOR)
            for sp, t, p in za:      rc.add_za_spectrum(sp, t, p)
            for sp, t, p in last_he: rc.add_he_spectrum(sp, t, p)

            wave_out, r_curve, omr_d = rc.calculate(wave_nm)

            file_date = "-".join(fname.split("-")[:3])
            target_dir = os.path.join(output_dir, file_date)
            os.makedirs(target_dir, exist_ok=True)
            stem = os.path.splitext(fname)[0]
            save_r_dat(os.path.join(target_dir, f"{stem}_R.dat"),
                       wave_out, r_curve, omr_d, fname, len(za), len(last_he))

            tag = ""
            if he:              tag += "  [He갱신]"
            if not rc.quality_ok: tag += "  ⚠️ 이상값"
            print(f"  ✅ {fname}  R={np.mean(r_curve):.6f}  valid={rc.valid_fraction*100:.1f}%"
                  f"  ZA={len(za)}  He={len(last_he)}{tag}")
            saved += 1
        except Exception as e:
            print(f"  ❌ {fname}  {e}")
            fail += 1

    print(f"[완료] {channel_name}  성공:{saved}  실패:{fail}  스킵:{skip}")


def main():
    process_channel("Cold", COLD_DIR, WAVE_CAL_COLD, os.path.join(OUTPUT_DIR, "R_Cold"))
    process_channel("Hot",  HOT_DIR,  WAVE_CAL_HOT,  os.path.join(OUTPUT_DIR, "R_Hot"))
    print("\n모든 작업이 완료되었습니다.")


if __name__ == "__main__":
    main()
