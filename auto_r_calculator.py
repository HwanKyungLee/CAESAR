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

class CalibrationBuffer:
    def __init__(self):
        self.za_spectra = []
        self.he_spectra = []
        self.is_ready = False

    def update(self, za, he):
        if za: self.za_spectra = za
        if he: self.he_spectra = he
        if self.za_spectra and self.he_spectra:
            self.is_ready = True

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

def read_all_scans(filepath):
    za, he = [], []
    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            tokens = line.strip().split("\t")
            if len(tokens) < 6: continue
            
            try:
                flag = tokens[4].strip()
                if flag == str(FLAG_ZA):
                    sp, t, p = _extract_spectrum_and_hk(tokens)
                    if len(sp) > 0: za.append((sp, t, p))
                elif flag == str(FLAG_HE):
                    sp, t, p = _extract_spectrum_and_hk(tokens)
                    if len(sp) > 0: he.append((sp, t, p))
            except:
                continue
    return za, he

def save_r_dat(out_path, wave, r, omr_d, rc, src_file):
    leff = 1.0 / (omr_d + 1e-30) * 1e-5
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(f"# Source: {os.path.basename(src_file)}\n")
        fh.write(f"# cavity={CAVITY_LEN}cm  RL={RL_FACTOR}\n")
        fh.write("wavelength_nm\tR\tomr_d_cm-1\tLeff_km\n")
        for i in range(len(r)):
            fh.write(f"{wave[i]:.4f}\t{r[i]:.8f}\t{omr_d[i]:.6e}\t{leff[i]:.4f}\n")

def process_channel(channel_name, directory, wave_cal_path, output_dir):
    print(f"\n[시작] {channel_name} 연속 처리 (Cal: {os.path.basename(wave_cal_path)})")
    
    wave_nm = np.loadtxt(wave_cal_path) if wave_cal_path and os.path.exists(wave_cal_path) else None
    files = sorted(glob.glob(os.path.join(directory, FILE_PATTERN)))
    buffer = CalibrationBuffer()
    saved = 0

    for fp in files:
        file_date = "-".join(os.path.basename(fp).split("-")[:3])
        target_dir = os.path.join(output_dir, file_date)
        os.makedirs(target_dir, exist_ok=True)

        za, he = read_all_scans(fp)
        if za or he:
            buffer.update(za, he)
            print(f"  [{os.path.basename(fp)}] 캘리브레이션 업데이트")

        if buffer.is_ready:
            try:
                rc = ReflectanceCalculator(cavity_len=CAVITY_LEN, rl_factor=RL_FACTOR)
                for s, t, p in buffer.za_spectra: rc.add_za_spectrum(s, t, p)
                for s, t, p in buffer.he_spectra: rc.add_he_spectrum(s, t, p)
                
                wave_out, r_curve, omr_d = rc.calculate(wave_nm)
                
                filename = os.path.splitext(os.path.basename(fp))
                out_path = os.path.join(target_dir, f"{filename}_R.dat")
                save_r_dat(out_path, wave_out, r_curve, omr_d, rc, fp)
                saved += 1
            except Exception as e:
                print(f"  [계산 실패] {os.path.basename(fp)}: {e}") 
    print(f"[완료] {channel_name} 저장 파일 수: {saved}")

def main():
    process_channel("Cold", COLD_DIR, WAVE_CAL_COLD, os.path.join(OUTPUT_DIR, "R_Cold"))
    process_channel("Hot",  HOT_DIR,  WAVE_CAL_HOT,  os.path.join(OUTPUT_DIR, "R_Hot"))
    print("\n모든 작업이 완료되었습니다.")

if __name__ == "__main__":
    main()