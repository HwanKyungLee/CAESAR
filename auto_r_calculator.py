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

# 파장 보정 경로 매핑
WAVE_CAL_COLD = r"C:\CAESAR_pro_package\reference\wavelength_cal\CAESAR cold\Calib_20260507_Hg_399-494nm_Poly2.txt"
WAVE_CAL_HOT  = r"C:\CAESAR_pro_package\reference\wavelength_cal\CAESAR hot\roi1\Calib_20260403_Hg_400-499nm(roi1).txt"

OUTPUT_DIR = r"."
FLAG_ZA = 500
FLAG_HE = 510
FILE_PATTERN = "*.dat"


def _extract_spectrum_and_hk(tokens):
    t_c, p_mbar = 25.0, 1013.25
    n = len(tokens)
    if n >= 6175:
        raw = np.array([float(t) if t.strip() else np.nan for t in tokens])
        intensity_full = raw[2053:4101]
        raw_p = raw[6156]
        raw_t = raw[6157]
        if np.isfinite(raw_p) and raw_p not in (0.0, 65535.0):
            p_mbar = raw_p * (0.01 * 6894.73326 / 100.0)
        if np.isfinite(raw_t) and raw_t not in (0.0, 65535.0):
            t_c = raw_t / 100.0
    else:
        intensity_full = np.array(tokens[5:], dtype=float)

    intensity_full = intensity_full[np.isfinite(intensity_full)]
    return intensity_full[PIXEL_MIN:PIXEL_MAX], t_c, p_mbar


def iter_cal_scans(filepath):
    """파일에서 ZA/He 스캔을 시간 순서대로 yield: (scan_type, sp, t, p)"""
    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            tokens = line.strip().split("\t")
            if len(tokens) < 6:
                continue
            try:
                flag = tokens[4].strip()
                if flag == str(FLAG_ZA):
                    sp, t, p = _extract_spectrum_and_hk(tokens)
                    if len(sp) > 0:
                        yield ("za", sp, t, p)
                elif flag == str(FLAG_HE):
                    sp, t, p = _extract_spectrum_and_hk(tokens)
                    if len(sp) > 0:
                        yield ("he", sp, t, p)
            except:
                continue


def save_r_dat(out_path, wave, r, omr_d, src_label):
    leff = 1.0 / (omr_d + 1e-30) * 1e-5
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(f"# Source: {src_label}\n")
        fh.write(f"# cavity={CAVITY_LEN}cm  RL={RL_FACTOR}\n")
        fh.write("wavelength_nm\tR\tomr_d_cm-1\tLeff_km\n")
        for i in range(len(r)):
            fh.write(f"{wave[i]:.4f}\t{r[i]:.8f}\t{omr_d[i]:.6e}\t{leff[i]:.4f}\n")


def _try_calculate(za_group, he_group, wave_nm, output_dir, label):
    """ZA/He 그룹 한 쌍으로 R 계산 후 저장. 성공 여부 반환."""
    try:
        rc = ReflectanceCalculator(cavity_len=CAVITY_LEN, rl_factor=RL_FACTOR)
        for sp, t, p in za_group:
            rc.add_za_spectrum(sp, t, p)
        for sp, t, p in he_group:
            rc.add_he_spectrum(sp, t, p)
        wave_out, r_curve, omr_d = rc.calculate(wave_nm)
        out_path = os.path.join(output_dir, f"{label}_R.dat")
        save_r_dat(out_path, wave_out, r_curve, omr_d, label)
        return True
    except Exception as e:
        print(f"  [계산 실패] {label}: {e}")
        return False


def process_channel(channel_name, directory, wave_cal_path, output_dir):
    print(f"\n[시작] {channel_name} 연속 처리 (Cal: {os.path.basename(wave_cal_path)})")

    wave_nm = np.loadtxt(wave_cal_path) if wave_cal_path and os.path.exists(wave_cal_path) else None
    files = sorted(glob.glob(os.path.join(directory, FILE_PATTERN)))

    # 파일 경계를 넘어 유지되는 ZA/He 그룹 버퍼
    last_za_group = None   # 가장 최근 완성된 ZA 연속 그룹
    last_he_group = None   # 가장 최근 완성된 He 연속 그룹

    current_type = None    # 현재 축적 중인 타입 ('za' | 'he')
    current_group = []     # 현재 축적 중인 스캔 목록
    current_file = None    # 현재 그룹이 시작된 파일명 (출력 라벨용)

    cycle_count = 0
    saved = 0

    def flush_group():
        """current_group 을 last_za/he_group 으로 확정하고, ZA가 완성되면 R 계산."""
        nonlocal last_za_group, last_he_group, cycle_count, saved
        if not current_group:
            return
        if current_type == "za":
            last_za_group = list(current_group)
            # ZA 그룹 완성 → He 가 있으면 R 계산
            if last_he_group is not None:
                cycle_count += 1
                file_date = "-".join(os.path.basename(current_file).split("-")[:3])
                target_dir = os.path.join(output_dir, file_date)
                os.makedirs(target_dir, exist_ok=True)
                stem = os.path.splitext(os.path.basename(current_file))[0]
                label = f"{stem}_c{cycle_count:04d}"
                if _try_calculate(last_za_group, last_he_group, wave_nm,
                                   target_dir, label):
                    saved += 1
        elif current_type == "he":
            last_he_group = list(current_group)

    for fp in files:
        for scan_type, sp, t, p in iter_cal_scans(fp):
            if scan_type != current_type:
                flush_group()
                current_type = scan_type
                current_group = [(sp, t, p)]
                current_file = fp
            else:
                current_group.append((sp, t, p))

    # 마지막 그룹 처리
    flush_group()

    print(f"[완료] {channel_name}  사이클 수: {cycle_count}  저장: {saved}  실패: {cycle_count - saved}")


def main():
    process_channel("Cold", COLD_DIR, WAVE_CAL_COLD, os.path.join(OUTPUT_DIR, "R_Cold"))
    process_channel("Hot",  HOT_DIR,  WAVE_CAL_HOT,  os.path.join(OUTPUT_DIR, "R_Hot"))
    print("\n모든 작업이 완료되었습니다.")


if __name__ == "__main__":
    main()
