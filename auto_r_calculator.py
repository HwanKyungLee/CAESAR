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
COLD_DIR = r"D:\CAESAR cold\2026-05"
HOT_DIR  = r"D:\CAESAR hot\2026-05"

CAVITY_LEN = 51.8
RL_FACTOR  = 1.0   # MATLAB Alpha.m 기준 RL=1; 퍼지 보정 시 채널별 값 사용 (CH1=0.9330)
PIXEL_MIN = 0
PIXEL_MAX = None

WAVE_CAL_COLD    = r"D:\CAESAR cold\Calib_20260507_Hg_399-494nm_Poly2.txt"
WAVE_CAL_HOT_ANS = r"D:\CAESAR hot\roi1\Calib_20260403_Hg_400-499nm(roi1).txt"
WAVE_CAL_HOT_PNS = r"D:\CAESAR hot\roi2\Calib_20260403_Hg_400-499nm(roi2).txt"

OUTPUT_DIR   = r"C:\Users\kh548\OneDrive\바탕 화면\여수 필드 준비"
FLAG_ZA      = 500   # ZA injecting (안정 측정 구간): 501=set flow, 502=wait before, 500=injecting, 503=wait after
FLAG_HE      = 510   # He injecting (안정 측정 구간): 511=set flow, 512=wait before, 510=injecting, 513=wait after
FILE_PATTERN = "*.dat"

# ── 스펙트럼 컬럼 범위 (2026-05-18/19 실측 검증) ─────────────────────────────
#  col 0-4: 메타데이터 (카운터/시각/적분시간/unknown/flag)
#  CH1 (cols  5-2052): 비활성 (Cold/Hot 모두 신호 없음)
#  CH2 (cols 2053-4100): Cold + Hot ANs(roi1) 스펙트럼
#  CH3 (cols 4101-6148): Hot PNs(roi2) 스펙트럼 전용
SPEC_START_DEFAULT = 2053   # CH2: Cold / Hot ANs
SPEC_END_DEFAULT   = 4101   # exclusive
SPEC_START_PNS     = 4101   # CH3: Hot PNs(roi2)
SPEC_END_PNS       = 6149   # exclusive

# ── HK 컬럼 인덱스 (2026-05-18/19 실측 샘플 검증) ──────────────────────────
#  Cold 채널 (노트북, 단일 캐비티, 비가열)
COL_PRESS_COLD = 6160   # 압력: ×0.6895 → ~1010 mbar
COL_TEMP_COLD  = 6173   # 캐비티 온도: ÷100 → ~24°C

#  Hot 채널 (데스크탑, 이중 캐비티, 캐비티 75°C)
#  ※ 압력: ANs(6162)/PNs(6164) 두 캐비티 각각의 센서로 추정, 정확한 매핑 확인 필요
COL_PRESS_HOT_ANS = 6162   # ANs 캐비티 압력: ×0.6895 → ~987 mbar
COL_PRESS_HOT_PNS = 6164   # PNs 캐비티 압력: ×0.6895 → ~971 mbar  ※ tentative
COL_TEMP_HOT      = 6155   # 캐비티 온도 (ANs/PNs 공통): ÷100 → ~75°C
# 하위 호환 별칭 — r_trend_monitor.py 등 구버전 코드가 COL_PRESS_HOT를 참조
COL_PRESS_HOT = COL_PRESS_HOT_ANS
#  참고: col6154=ANs 오븐(~180°C), col6151=PNs 오븐(~300°C)
# ════════════════════════════════════════════════════════════════


def _extract_spectrum_and_hk(tokens, col_press=COL_PRESS_COLD, col_temp=COL_TEMP_COLD,
                              spec_start=SPEC_START_DEFAULT, spec_end=SPEC_END_DEFAULT):
    """한 행(토큰 리스트)에서 스펙트럼과 압력·온도를 추출한다.

    spec_start / spec_end: 추출할 스펙트럼 컬럼 범위 (exclusive end)
      - CH2 기본값 (2053-4101): Cold + Hot ANs
      - CH3 PNs   (4101-6149): Hot PNs(roi2) 전용
    """
    t_c, p_mbar = 25.0, 1013.25
    n = len(tokens)
    if n >= 6175:
        raw = np.array([float(t) if t.strip() else np.nan for t in tokens])
        intensity_full = raw[spec_start:spec_end]
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


def read_all_scans(filepath, col_press=COL_PRESS_COLD, col_temp=COL_TEMP_COLD,
                   spec_start=SPEC_START_DEFAULT, spec_end=SPEC_END_DEFAULT,
                   return_ts=False):
    """파일에서 flag=FLAG_ZA / flag=FLAG_HE 스캔을 읽어 (za, he) 리스트로 반환.
    각 항목: (spectrum_array, temp_c, press_mbar)

    ★ col1(tokens[1]) 단위 주의 ★
    ─────────────────────────────────────────────────────────────────
    col1 값은 센티초(centiseconds, 1/100초) 단위이다. UTC 초(seconds)가 아님!
    - 행 간 증가량: 약 +97 centiseconds = 0.97 초/행
    - 값이 65444 → 5로 감소: 스캔 사이클 재시작 (자정(day crossing) 아님!)
      · 65444 centisec = 654 초 ≈ 10.9분 (1사이클 활성 구간)
      · 1파일에 약 7회 발생, 각 간격 ≈ 14.4분 (활성 10.9분 + 리셋 대기 3.5분)
    - 파일 1개 = 약 3,700행 × 0.97초 ≈ 1시간 분량

    타임스탬프가 필요하면 col1이 아닌 파일 mtime을 사용할 것.
    (r_trend_monitor.py 상단 docstring 및 _parse_timestamp 함수 참조)
    ─────────────────────────────────────────────────────────────────

    return_ts=True 로 호출하면 8-튜플을 반환한다:
      (za, he, min_val, first_za_val, first_he_val, first_val, last_val, n_resets)
      min_val      : 파일 내 col1 최솟값 (센티초 단위, UTC 초 아님)
      first_za_val : 첫 번째 ZA 스캔 행의 col1 (센티초)
      first_he_val : 첫 번째 He 스캔 행의 col1 (센티초, 없으면 None)
      first_val    : 파일 내 첫 번째 유효 col1 (센티초)
      last_val     : 파일 내 마지막 유효 col1 (센티초)
      n_resets     : col1 감소(스캔 사이클 재시작) 횟수 — 날짜 계산에 사용 금지
    """
    za, he = [], []
    min_secs: float | None = None
    first_za_secs: float | None = None
    first_he_secs: float | None = None
    first_secs: float | None = None   # 파일 내 첫 번째 유효 col1 (센티초)
    last_secs: float | None = None    # 파일 내 마지막 유효 col1 (센티초)
    n_crossings: int = 0              # col1 감소 횟수 (스캔 사이클 재시작 횟수, 자정 교차 아님)
    _prev_s: float | None = None      # 이전 행의 col1 (사이클 재시작 감지용)

    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            tokens = line.strip().split("\t")
            if len(tokens) < 6:
                continue
            try:
                # ── col1 추적 (return_ts 용) ──────────────────────────────
                # col1(tokens[1])은 센티초 단위. UTC 초로 오해하지 말 것.
                # 0 < s < 86400 조건은 "센티초 값이 양수인 유효 행"을 걸러냄
                # (86400 centisec = 864초 = 14.4분, 즉 1 사이클 최대치 이내)
                if return_ts and len(tokens) >= 6175:
                    s = float(tokens[1])
                    if 0.0 < s < 86400.0:
                        if min_secs is None or s < min_secs:
                            min_secs = s
                        if first_secs is None:
                            first_secs = s
                        # 스캔 사이클 재시작: 이전 값보다 3600 centisec(=36초) 이상 감소
                        # ※ 자정 교차가 아니라 스캔 사이클 wrap-around임
                        if _prev_s is not None and s < _prev_s - 3600:
                            n_crossings += 1
                        _prev_s = s
                        last_secs = s   # 항상 마지막 값으로 갱신

                # ── ZA / He 스캔 추출 ────────────────────────────────────────
                flag = int(tokens[4].strip())
                if flag == FLAG_ZA:
                    sp, t, p = _extract_spectrum_and_hk(tokens, col_press, col_temp,
                                                        spec_start, spec_end)
                    if len(sp) > 0:
                        za.append((sp, t, p))
                        # 첫 번째 ZA 스캔 타임스탬프 기록
                        if return_ts and first_za_secs is None and len(tokens) >= 6175:
                            s = float(tokens[1])
                            if 0.0 < s < 86400.0:
                                first_za_secs = s
                elif flag == FLAG_HE:
                    sp, t, p = _extract_spectrum_and_hk(tokens, col_press, col_temp,
                                                        spec_start, spec_end)
                    if len(sp) > 0:
                        he.append((sp, t, p))
                        # 첫 번째 He 스캔 타임스탬프 기록
                        if return_ts and first_he_secs is None and len(tokens) >= 6175:
                            s = float(tokens[1])
                            if 0.0 < s < 86400.0:
                                first_he_secs = s
            except:
                continue

    if return_ts:
        # n_crossings = 스캔 사이클 재시작 횟수 (자정 교차 횟수가 아님!)
        # 모든 값(min_secs 등)은 센티초 단위임. UTC 초로 쓰면 날짜 계산 크게 틀림.
        return za, he, min_secs, first_za_secs, first_he_secs, first_secs, last_secs, n_crossings
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
                    col_press=None, col_temp=None,
                    spec_start=SPEC_START_DEFAULT, spec_end=SPEC_END_DEFAULT):
    """채널별 HK 컬럼·스펙트럼 범위를 지정하여 R을 계산한다.

    Parameters
    ----------
    channel_name  : 출력 표시용 이름 (예: "Cold", "Hot_ANs", "Hot_PNs")
    directory     : .dat 파일이 있는 폴더
    wave_cal_path : 파장 교정 파일 경로 (None이면 픽셀 인덱스로 폴백)
    output_dir    : R 결과 저장 폴더
    col_press     : 압력 HK 컬럼 (None이면 channel_name으로 자동 선택)
    col_temp      : 온도 HK 컬럼 (None이면 channel_name으로 자동 선택)
    spec_start    : 스펙트럼 시작 컬럼 (기본 2053 = CH2)
    spec_end      : 스펙트럼 끝 컬럼 exclusive (기본 4101 = CH2)
    """
    # HK 컬럼 자동 선택 (channel_name 기반)
    if col_press is None:
        if "pns" in channel_name.lower():
            col_press = COL_PRESS_HOT_PNS
        elif "hot" in channel_name.lower():
            col_press = COL_PRESS_HOT_ANS
        else:
            col_press = COL_PRESS_COLD
    if col_temp is None:
        col_temp = COL_TEMP_HOT if "hot" in channel_name.lower() else COL_TEMP_COLD

    print(f"\n[시작] {channel_name} 처리"
          f"  P=col{col_press}  T=col{col_temp}"
          f"  스펙트럼=cols{spec_start}-{spec_end-1}")

    if wave_cal_path and os.path.exists(wave_cal_path):
        with open(wave_cal_path, "r", encoding="utf-8") as _f:
            wave_nm = np.loadtxt(_f)
    else:
        wave_nm = None
    if wave_cal_path and not os.path.exists(wave_cal_path):
        print(f"  ⚠️  파장 교정 파일 없음: {wave_cal_path}  → 픽셀 인덱스로 진행")

    files = sorted(glob.glob(os.path.join(directory, FILE_PATTERN)))

    last_he = []   # 가장 최근 파일의 He 스캔 (다음 파일들에서 재사용)
    saved = fail = skip = 0

    for fp in files:
        fname = os.path.basename(fp)
        za, he = read_all_scans(fp, col_press, col_temp, spec_start, spec_end)

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
            if he:               tag += "  [He update]"
            if not rc.quality_ok: tag += "  [WARN: quality]"
            print(f"  [OK] {fname}  R={np.mean(r_curve):.6f}  valid={rc.valid_fraction*100:.1f}%"
                  f"  ZA={len(za)}  He={len(last_he)}{tag}")
            saved += 1
        except Exception as e:
            print(f"  [ERR] {fname}  {e}")
            fail += 1

    print(f"[완료] {channel_name}  성공:{saved}  실패:{fail}  스킵:{skip}")


def main():
    # Cold 채널
    process_channel("Cold", COLD_DIR, WAVE_CAL_COLD,
                    os.path.join(OUTPUT_DIR, "R_Cold"))

    # Hot ANs(roi1): CH2 스펙트럼 (cols 2053-4100), ANs 압력(col6162)
    process_channel("Hot_ANs", HOT_DIR, WAVE_CAL_HOT_ANS,
                    os.path.join(OUTPUT_DIR, "R_Hot_ANs"),
                    col_press=COL_PRESS_HOT_ANS, col_temp=COL_TEMP_HOT,
                    spec_start=SPEC_START_DEFAULT, spec_end=SPEC_END_DEFAULT)

    # Hot PNs(roi2): CH3 스펙트럼 (cols 4101-6148), PNs 압력(col6164, tentative)
    process_channel("Hot_PNs", HOT_DIR, WAVE_CAL_HOT_PNS,
                    os.path.join(OUTPUT_DIR, "R_Hot_PNs"),
                    col_press=COL_PRESS_HOT_PNS, col_temp=COL_TEMP_HOT,
                    spec_start=SPEC_START_PNS, spec_end=SPEC_END_PNS)

    print("\n모든 작업이 완료되었습니다.")


if __name__ == "__main__":
    main()
