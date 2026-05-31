"""
r_trend_monitor.py — CAESAR Pro 거울 반사율 시계열 모니터
==========================================================
raw .dat 파일들을 스캔하여 파일 하나당 R_mean 값을 계산하고,
시간 순으로 정렬한 뒤 반사율이 유지되고 있는지 그래프로 확인합니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ★ RAW .DAT 파일 구조 & 타임스탬프 읽는 법 (중요!)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [1] col1 (첫 번째 열) 단위 = 센티초 (centiseconds, 1/100 초)
      - 절대로 "UTC 자정으로부터 경과한 초(seconds)"가 아니다.
      - 행 사이 증가량: 약 +97 centiseconds = 0.97 초/행
      - 값 범위 예시: 5 → 65444 → (리셋) → 5 → 65444 → ...
        · 65444 centiseconds = 654.44초 ≈ 10.9분 (스캔 1사이클 활성 구간)
        · 0→65444 구간이 끝나면 col1이 다시 ~5로 떨어짐 = 스캔 사이클 재시작
        · 사이클 재시작 ≠ 자정(day crossing). 날짜 계산에 절대 사용 금지!
      - 1파일당 약 7번 리셋 발생, 각 리셋 간 실제 경과 시간 ≈ 14.4분
        (활성 스캔 ~10.9분 + 장비 리셋 대기 ~3.5분)

  [2] 파일 하나의 실제 측정 시간
      - 행 수: 약 3,700~3,750행
      - 활성 스캔 시간: 3,700행 × 0.97초 ≈ 3,590초 ≈ 1시간
      - DAQ는 1시간 분량이 쌓이면 다음 파일로 넘어감

  [3] 타임스탬프를 얻는 올바른 방법 = 파일 mtime 사용
      - DAQ가 파일을 열 때(측정 시작 시각) mtime을 설정한다.
      - 파일들의 mtime은 정확히 1시간 간격으로 찍혀 있다.
        예) 2026-05-17-001.dat → 18:33 KST
            2026-05-17-002.dat → 19:33 KST
            2026-05-17-003.dat → 20:33 KST  ...
      - ctime(생성일)은 파일을 분석 PC로 복사한 날짜로 바뀌므로 사용 금지.
      - col1 값으로 시각을 추산하려 하면 날짜가 수백 일 틀린다 (검증 완료).

  [4] flag 열 의미
      - flag=0   : 파일 시작 마커(헤더 행)
      - flag=1   : 대기(Atmosphere) 측정
      - flag=500 : ZA (Zero Air) 주입 중  ← R 계산에 사용
      - flag=510 : He (Helium) 주입 중    ← R 계산에 사용
      - flag=502/503/512/513 : 전환 대기 상태 (사용 안 함)

  [5] 2026 여수 아라온 항해 데이터 세션 구성 (참고)
      - 2026-05-17: 파일 001~016 (16개, 18:33~09:33 KST)
      - 2026-05-18: 파일 001~025 (25개, 09:34~09:41 KST 다음날)
      - 2026-05-19: 파일 001~019 (19개, 10:41~04:41 KST 다음날)
      - Cold 합계: 60파일 / Hot 합계: 54파일 (Hot은 05-18부터 시작)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import re
import sys
import io
import glob
from datetime import datetime, timedelta, timezone
import numpy as np

# Windows CP949 콘솔에서 이모지/한글 깨짐 방지
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 모듈 경로 문제 해결을 위한 강제 패스 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
HAS_MPL = True

try:
    from reflectance_calc import ReflectanceCalculator
    from r_batch_calculator import (
        read_all_scans, FLAG_ZA, FLAG_HE,
        CAVITY_LEN, RL_FACTOR, PIXEL_MIN, PIXEL_MAX,
        COL_PRESS_COLD, COL_TEMP_COLD, COL_PRESS_HOT, COL_TEMP_HOT,
        COL_PRESS_HOT_PNS, COL_PRESS_HOT_ANS,
        SPEC_START_DEFAULT, SPEC_END_DEFAULT, SPEC_START_ANS, SPEC_END_ANS,
    )
except ImportError as e:
    # sys.exit()는 QThread 안에서 SystemExit를 던져 스레드를 비정상 종료시키므로 사용 금지.
    # ImportError를 그대로 re-raise하면 _RTrendWorker.run()의 except Exception이 잡아서
    # 로그에 표시하고 finished("")를 emit한다.
    raise ImportError(f"필수 모듈을 찾을 수 없습니다: {e}") from e

# ════════════════════════════════════════════════════════════════
#  유틸리티 함수 (반드시 설정보다 위에 있어야 합니다)
# ════════════════════════════════════════════════════════════════
def file_range(directory: str, date: str, start: int, end: int) -> list:
    """날짜와 번호 범위로 파일 목록을 생성한다.
    예: file_range(COLD_DIR, "2026-05-19", 1, 24)
    """
    return [
        os.path.join(directory, f"{date}-{i:03d}.dat")
        for i in range(start, end + 1)
    ]

# ════════════════════════════════════════════════════════════════
#  사용자 설정
# ════════════════════════════════════════════════════════════════
# Paths and wavelength calibration files are imported from
# r_batch_calculator, which auto-discovers them across the locations they've
# lived in throughout the campaign (D:\, C:\Doasis_Work\raw,alpha_by_nam\, ...).
# Override these module-level constants if you need a one-off run on
# different files.
from r_batch_calculator import (   # noqa: E402  (kept here for visibility)
    COLD_DIR  as _DEFAULT_COLD_DIR,
    HOT_DIR   as _DEFAULT_HOT_DIR,
    WAVE_CAL_COLD     as _DEFAULT_WAVE_CAL_COLD,
    WAVE_CAL_HOT_PNS  as _DEFAULT_WAVE_CAL_HOT_PNS,
    WAVE_CAL_HOT_ANS  as _DEFAULT_WAVE_CAL_HOT_ANS,
)

COLD_DIR = _DEFAULT_COLD_DIR
HOT_DIR  = _DEFAULT_HOT_DIR
WAVE_CAL_COLD    = _DEFAULT_WAVE_CAL_COLD
WAVE_CAL_HOT     = _DEFAULT_WAVE_CAL_HOT_PNS    # PNs(roi1)=CH2
WAVE_CAL_HOT_ANS = _DEFAULT_WAVE_CAL_HOT_ANS    # ANs(roi2)=CH3

OUTPUT_DIR  = r"."
FILE_PATTERN = "*.dat"
R_EXPECTED_COLD = 0.9990
R_EXPECTED_HOT  = 0.9990
R_WARN_DELTA = 0.0005

# ── Channel R-fit wavelength windows ─────────────────────────────────
# 박사님 Rs2_*.m line 123-138 — only the wavelength range where the
# mirror absorption is well-sampled is used for the R statistics. The
# rest of the CCD has too much edge noise / out-of-band signal.
#
#   Cold ch1 (NO2 cell)  : 435..480 nm   (Rs2_Cold.m line 124)
#   Hot  ch1 (PNs cell)  : 430..465 nm   (Rs2_Hot.m line 124)
#   Hot  ch2 (ANs cell)  : 435..470 nm   (Rs2_Hot.m line 129)
CH_FIT_WINDOW_NM = {
    "cold":    (435.0, 480.0),
    "hot_pns": (430.0, 465.0),
    "hot_ans": (435.0, 470.0),
}

# 타임존 상수 (설정에서 참조하므로 여기서 먼저 정의)
_UTC      = timezone.utc
_KST_TZ   = timezone(timedelta(hours=9))

# Cold DAQ는 파일 mtime을 UTC로 기록 → _UTC 사용 (KST로 읽으면 +9시간 오차 발생)
# Hot DAQ는 KST로 기록 → _KST_TZ 사용 (PNs/ANs 같은 raw 파일이라 동일 tz)
COLD_TS_TZ   = _UTC
HOT_TS_TZ    = _KST_TZ
HOT_ANS_TS_TZ = _KST_TZ

# [방법 1] 전체 처리 시 None 사용
# Hot PNs/ANs는 같은 raw 파일을 ROI 컬럼만 달리해서 읽으므로 HOT_FILES를 공유한다.
COLD_FILES = None
HOT_FILES  = None

# [방법 2] 특정 번호 범위만 처리 시 (주석 해제 후 사용)
#COLD_FILES = file_range(COLD_DIR, "2026-05-19", 1, 2)
#HOT_FILES  = file_range(HOT_DIR, "2026-05-19", 1, 2)

SHOW_LEFF  = True
SHOW_PLOT  = False
PLOT_DPI   = 150
# ════════════════════════════════════════════════════════════════

_DATE_RE  = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

def _parse_timestamp(filepath: str) -> datetime:
    """파일 mtime (DAQ가 파일을 연 시각)을 KST datetime으로 반환.

    ── 왜 col1을 쓰지 않는가 ──────────────────────────────────────
    col1 값은 "센티초(1/100초)" 단위이며, 자정으로부터 경과한 UTC 초가 아니다.
    예) 행 간격 +97 → 0.97초/행 (초가 아닌 센티초이므로 97초/행이 아님)
        값이 65444에서 5로 리셋 → 스캔 사이클 재시작 (자정 crossing 아님)
    col1을 날짜 계산에 쓰면 파일당 7번 × (65444 centisec / 86400 sec) ≈ 5.3일씩
    날짜가 밀려 60개 파일 처리 후 수백 일 미래 날짜가 찍힌다 (실제로 재현됨).

    ── 왜 mtime이 정확한가 ────────────────────────────────────────
    DAQ 소프트웨어가 새 파일을 열 때(= 측정 시작) mtime을 직접 기록한다.
    실제 파일들의 mtime 간격이 정확히 1시간임을 확인:
        001.dat → 18:33 KST
        002.dat → 19:33 KST
        003.dat → 20:33 KST  ...
    단, ctime(Windows 탐색기 '만든 날짜')은 파일을 PC로 복사한 날짜로
    덮어씌워지므로 절대 사용하지 말 것.
    """
    try:
        return datetime.fromtimestamp(os.path.getmtime(filepath), tz=_KST_TZ)
    except OSError:
        return datetime.now(tz=_KST_TZ)

def scan_directory(directory: str, wave_nm, file_list=None,
                   col_press=COL_PRESS_COLD, col_temp=COL_TEMP_COLD,
                   ts_tz=None,
                   spec_start=SPEC_START_DEFAULT, spec_end=SPEC_END_DEFAULT,
                   fit_window_nm: tuple | None = None) -> list[dict]:
    """파일마다 R을 계산해 결과 목록을 **타임스탬프 순**으로 반환한다.

    수정 내역
    ---------
    * 파일명 순서가 아닌 타임스탬프 순으로 정렬 후 반환 → 지그재그 선 해소.
    * valid_fraction = 0 (완전 보정 실패, R=1.0 dummy) 결과는 저장하지 않음.
    * 보정 실패 파일에서 He 스캔이 나와도 last_he를 오염시키지 않음.
    * quality_ok 기준을 실측 valid_fraction(~44 %)에 맞게 0.30으로 완화.
    """
    if file_list is not None:
        files = sorted(str(f) for f in file_list if os.path.isfile(str(f)))
    else:
        files = sorted(glob.glob(os.path.join(directory, FILE_PATTERN)))
        if not files:
            files = sorted(glob.glob(os.path.join(directory, "**", FILE_PATTERN), recursive=True))

    if not files:
        print(f"  .dat 파일 없음: {directory}")
        return []

    print(f"  {len(files)}개 파일 연속 처리 시작...\n")

    results = []
    last_he = []          # 가장 최근 양질의 He 스캔 (파일 간 유지)
    skip = fail = 0

    for fp in files:
        fname = os.path.basename(fp)
        za, he = read_all_scans(fp, col_press, col_temp,
                                spec_start, spec_end)

        # ── 타임스탬프: 파일 mtime만 사용 ────────────────────────────────────
        # ※ col1은 센티초(centiseconds) 단위 → UTC 초로 오해하면 날짜가 수백 일 틀림.
        #   col1의 0→65444 리셋은 스캔 사이클 재시작일 뿐, 자정 crossing이 아님.
        #   상세 설명은 파일 맨 위 docstring 참조.
        _tz = ts_tz if ts_tz is not None else _KST_TZ
        ts = datetime.fromtimestamp(os.path.getmtime(fp), tz=_tz)
        ts_str = ts.strftime("%m/%d %H:%M")

        # He 스캔을 만나도 보정 품질을 먼저 확인한 뒤에만 last_he 갱신
        # → 나쁜 파일의 He가 다음 파일로 오염되는 것 방지
        candidate_he = he if he else last_he

        if not za or not candidate_he:
            reason = []
            if not za:            reason.append(f"ZA스캔=0 (flag={FLAG_ZA} 행 없음)")
            if not candidate_he:  reason.append("He없음(last_he도 없음)")
            print(f"  [{fname}] ⏳ 스킵 @ {ts_str}  {', '.join(reason)}")
            skip += 1
            continue

        try:
            rc = ReflectanceCalculator(cavity_len=CAVITY_LEN, rl_factor=RL_FACTOR)
            for sp, t, p in za:            rc.add_za_spectrum(sp, t, p)
            for sp, t, p in candidate_he: rc.add_he_spectrum(sp, t, p)
            # ── Channel-specific R-fit ROI ────────────────────────────
            # Previously the channel-specific window (CH_FIT_WINDOW_NM)
            # was only used for *plotting* the statistics; the
            # ReflectanceCalculator itself was called without ROI so it
            # always used its 430-470 nm default. That biased the 5th-
            # order polynomial fit toward the Hot-PNs window even for
            # Cold and Hot ANs channels. Pass the channel window through
            # explicitly when fit_window_nm is supplied.
            calc_kwargs: dict = {"min_valid_fraction": 0.30}
            if fit_window_nm is not None:
                calc_kwargs["roi_min"] = float(fit_window_nm[0])
                calc_kwargs["roi_max"] = float(fit_window_nm[1])
            # reflectance_calc.calculate() returns 4-tuple as of this refactor
            wave_out, r_curve_raw, r_curve_fit, omr_d = rc.calculate(
                wave_nm, **calc_kwargs
            )
            r_curve = r_curve_fit   # downstream code expects a single curve

            # valid=0%는 ratio≈1 (He/ZA 신호 동일) → omr_d=0 → R=1.0 dummy
            # 이 파일은 결과에 포함하지 않고 last_he도 갱신하지 않는다
            if rc.valid_fraction == 0.0:
                print(f"  [{fname}] ⏭️  valid=0% (R=1.0 dummy) 스킵 — last_he 유지")
                skip += 1
                continue

            # 품질이 OK인 경우에만 last_he 갱신
            if he and rc.quality_ok:
                last_he = he

            leff_arr = np.where(omr_d > 1e-10, 1.0 / omr_d * 1e-5, np.nan)

            # ── R-fit wavelength window (박사님 Rs2.m line 123-138) ──
            # Restrict the R statistics to the channel-specific band
            # where the cavity transmission is well-characterised; CCD
            # edges and out-of-band pixels otherwise pull the mean up
            # toward 1.0 and inflate the noise.
            if fit_window_nm is not None:
                w_mask = (wave_out >= float(fit_window_nm[0])) & \
                         (wave_out <= float(fit_window_nm[1]))
                if w_mask.sum() < 50:
                    print(f"  [{fname}] ⚠️ fit_window 내 픽셀 부족 ({w_mask.sum()}), 전 픽셀 사용")
                    r_fit, leff_fit = r_curve, leff_arr
                else:
                    r_fit, leff_fit = r_curve[w_mask], leff_arr[w_mask]
            else:
                r_fit, leff_fit = r_curve, leff_arr

            # Store the (wave, R) curve actually used for the statistics
            # so plot_r_curves() can overlay every scan and draw the mean
            # spectrum per channel (박사님 Rs2.m line 144 style).
            if fit_window_nm is not None and w_mask.sum() >= 50:
                wave_in_window = np.asarray(wave_out)[w_mask]
            else:
                wave_in_window = np.asarray(wave_out)

            # Full-wavelength arrays kept alongside the ROI-clipped
            # statistics. The GUI plots the full curves and shades the
            # ROI as a band, so we need both.
            res = {
                "timestamp":  ts,   # 위에서 이미 파싱한 값 재사용
                "filename":   fname,
                "r_mean":     float(np.mean(r_fit)),
                "r_std":      float(np.std(r_fit)),
                "r_min":      float(np.min(r_fit)),
                "r_max":      float(np.max(r_fit)),
                "leff_mean":  float(np.nanmean(leff_fit)),
                "valid_frac": rc.valid_fraction,
                "n_za":       len(za),
                "n_he":       len(candidate_he),
                "fit_window_nm": fit_window_nm,
                # ROI-clipped (used for headline statistics + per-channel mean curve)
                "wave_nm":    wave_in_window,
                "r_curve":    np.asarray(r_fit, dtype=float),
                # Full-wavelength curves (raw + 5th-order poly fit), for per-file R(λ) plot
                "wave_nm_full":   np.asarray(wave_out,     dtype=float),
                "r_curve_raw":    np.asarray(r_curve_raw,  dtype=float),
                "r_curve_fit":    np.asarray(r_curve_fit,  dtype=float),
                "omr_d":          np.asarray(omr_d,        dtype=float),
            }
            results.append(res)
            tag = ("  [He갱신]" if (he and rc.quality_ok) else "") + \
                  ("  ⚠️ 이상값" if not rc.quality_ok else "")
            print(f"  [{fname}] ✅ @ {ts_str}  R_mean={res['r_mean']:.6f}  "
                  f"Leff={res['leff_mean']:.2f}km  valid={res['valid_frac']*100:.1f}%{tag}")
        except Exception as e:
            print(f"  [{fname}] ❌ {e}")
            fail += 1


    # ── 타임스탬프 순 정렬 ──────────────────────────────────────────────────────
    # 파일명 순서 ≠ 시간 순서인 경우(아라온 DAQ가 번호를 역순 또는 교차 할당할 때)
    # 정렬 없이 plot 하면 선이 아침↔저녁을 오가며 지그재그가 된다.
    results.sort(key=lambda x: x["timestamp"])

    saved = len(results)
    print(f"\n  총 파일: {len(files)}  저장: {saved}  스킵: {skip}  실패: {fail}")
    return results

def _stem_digits(filename: str) -> str:
    return re.sub(r"[^0-9]", "", os.path.splitext(os.path.basename(filename))[0])

def make_range_name(results: list[dict]) -> str:
    if not results: return "nodata"
    first = _stem_digits(results[0]["filename"])
    last  = _stem_digits(results[-1]["filename"])
    if first == last: return first
    return f"{first}_{last}"

def save_r_curves_per_file(results: list[dict], channel_subdir: str,
                            out_folder: str) -> int:
    """Persist per-file R(λ) curves so the GUI can plot any single scan.

    Writes to ``{out_folder}/{channel_subdir}/{YYYY-MM-DD}/{basename}_R.dat``
    matching the path layout expected by ``ui_dialogs_r.py``'s
    ``_on_table_row_selected``.

    Each file contains: ``wavelength_nm, R_raw, R_fitted, omr_d_cm-1, Leff_km``
    across the *full* CCD wavelength range — the ROI is recorded as a
    header comment so the GUI can shade it as a band.
    """
    from r_batch_calculator import save_r_dat   # local import to avoid cycles

    n_saved = 0
    for r in results:
        wave = r.get("wave_nm_full")
        r_raw = r.get("r_curve_raw")
        r_fit = r.get("r_curve_fit")
        omr_d = r.get("omr_d")
        if any(v is None for v in (wave, r_raw, r_fit, omr_d)):
            continue
        fname = r["filename"]
        # Date prefix from filename (e.g. 2026-05-19-007.dat → 2026-05-19)
        file_date = "-".join(os.path.splitext(fname)[0].split("-")[:3])
        base = os.path.splitext(fname)[0]
        out_path = os.path.join(out_folder, channel_subdir, file_date,
                                f"{base}_R.dat")
        save_r_dat(out_path, wave, r_raw, r_fit, omr_d,
                   fname=fname, n_za=r.get("n_za", 0), n_he=r.get("n_he", 0))
        n_saved += 1
    if n_saved:
        print(f"  [R(λ) curves] {channel_subdir}: {n_saved}개 파일 저장")
    return n_saved


def save_dat(results: list[dict], out_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(f"# CAESAR Pro — Mirror Reflectivity Trend\n")
        fh.write(f"# cavity={CAVITY_LEN} cm  RL={RL_FACTOR}  ZA_flag={FLAG_ZA}  He_flag={FLAG_HE}\n")
        # Record the R-fit wavelength window used for each row's statistics
        _winset = {r.get("fit_window_nm") for r in results}
        _winset.discard(None)
        if len(_winset) == 1:
            _w = _winset.pop()
            fh.write(f"# R_fit_window_nm={_w[0]:.1f}-{_w[1]:.1f}\n")
        elif _winset:
            fh.write(f"# R_fit_window_nm=mixed: {sorted(_winset)}\n")
        else:
            fh.write(f"# R_fit_window_nm=none (full CCD pixels)\n")
        fh.write("timestamp(KST)\tfilename\tR_mean\tR_std\tR_min\tR_max\tLeff_mean_km\tvalid_frac_pct\tn_ZA\tn_He\n")
        for r in results:
            fh.write(
                f"{r['timestamp'].strftime('%Y-%m-%d %H:%M')}\t"
                f"{r['filename']}\t"
                f"{r['r_mean']:.8f}\t{r['r_std']:.8f}\t"
                f"{r['r_min']:.8f}\t{r['r_max']:.8f}\t{r['leff_mean']:.4f}\t"
                f"{r['valid_frac']*100:.1f}\t{r['n_za']}\t{r['n_he']}\n"
            )
    print(f"  [DAT] {out_path}  ({len(results)}행)")

def _plot_channel(ax_r, ax_l, results, channel_name, r_expected, color):
    if not results:
        ax_r.text(0.5, 0.5, f"{channel_name}\nNo Data", ha="center", va="center", transform=ax_r.transAxes, fontsize=12, color="gray")
        return

    # 선택한 타임존(ts_tz)의 wall-clock을 그대로 사용 (로그/.dat 출력과 일치).
    # tzinfo만 제거해 naive로 만들면 matplotlib이 추가 변환 없이 그대로 표시한다.
    # astimezone()을 쓰면 tz 선택이 무효화되므로 사용하지 않는다.
    times  = [r["timestamp"].replace(tzinfo=None) for r in results]
    r_mean = np.array([r["r_mean"]  for r in results])
    r_std  = np.array([r["r_std"]   for r in results])
    leff   = np.array([r["leff_mean"] for r in results])

    warn_mask = r_mean < (r_expected - R_WARN_DELTA)

    ax_r.fill_between(times, r_mean - r_std, r_mean + r_std, alpha=0.2, color=color, label="±1σ")
    ax_r.plot(times, r_mean, "o-", color=color, markersize=4, linewidth=1.2, label="R_mean")

    if np.any(warn_mask):
        warn_times = [t for t, w in zip(times, warn_mask) if w]
        warn_r     = r_mean[warn_mask]
        ax_r.scatter(warn_times, warn_r, s=80, marker="x", color="red", zorder=5, label=f"Warning (<{r_expected-R_WARN_DELTA:.4f})")

    ax_r.axhline(r_expected, color="gray", linestyle="--", linewidth=0.8, label=f"Expected {r_expected:.4f}")
    ax_r.axhline(r_expected - R_WARN_DELTA, color="red", linestyle=":", linewidth=0.8, alpha=0.6, label=f"Warn.limit {r_expected-R_WARN_DELTA:.4f}")

    ax_r.set_ylabel(f"{channel_name}  R(λ) mean")
    ax_r.legend(fontsize=8, loc="lower left")
    ax_r.grid(True, alpha=0.3)

    # Zoom Y-axis so ±0.01 % changes near R≈99.99 % are clearly visible.
    # Window = ±5σ of the data, but never narrower than ±0.05 % (5e-4).
    r_mean_val = float(np.mean(r_mean))
    r_std_val  = float(np.std(r_mean))
    margin     = max(r_std_val * 5.0, 5e-4)
    # Also guarantee the expected-R and warn-limit lines stay inside the frame.
    y_lo = min(r_mean_val - margin, r_expected - R_WARN_DELTA - 1e-4)
    y_hi = max(r_mean_val + margin, r_expected + 1e-4)
    ax_r.set_ylim(y_lo, y_hi)

    if ax_l is not None:
        leff_plot = np.array(leff, dtype=float)
        leff_plot[~np.isfinite(leff_plot)] = np.nan
        ax_l.plot(times, leff_plot, "s-", color=color, markersize=4, linewidth=1.0, alpha=0.8)
        ax_l.set_ylabel("Leff mean (km)")
        ax_l.grid(True, alpha=0.3)

    for ax in ([ax_r, ax_l] if ax_l else [ax_r]):
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d\n%H:%M"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax.xaxis.get_majorticklabels(), fontsize=7)
    # X축 레이블에 KST 표기 (naive datetime이므로 명시적으로 기재)
    (ax_l if ax_l else ax_r).set_xlabel("Date / Time (KST)")

def plot_single_channel(results, channel_name, r_expected, out_path, color="steelblue"):
    n_panels = 2 if SHOW_LEFF else 1
    fig, axes = plt.subplots(n_panels, 1, figsize=(12, 4 * n_panels), sharex=True, squeeze=False)
    fig.suptitle(f"CAESAR Pro — {channel_name} Channel Mirror Reflectivity Trend\n(cavity={CAVITY_LEN} cm  RL={RL_FACTOR}  ZA flag={FLAG_ZA}  He flag={FLAG_HE})", fontsize=11)
    ax_r = axes[0, 0]
    ax_l = axes[1, 0] if SHOW_LEFF else None
    _plot_channel(ax_r, ax_l, results, channel_name, r_expected, color)
    plt.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=PLOT_DPI, bbox_inches="tight")
    print(f"  [PNG] {out_path}")
    if SHOW_PLOT: plt.show()
    plt.close(fig)

def plot_r_curves_per_channel(results, channel_name, color, out_path):
    """Plot every scan's R(λ) curve plus the mean spectrum for one channel.

    Mirrors 박사님 Rs2.m line 144 (``plot(wv, R1, '.', wv, Rr1, 'g')``):
    each scan's R(λ) is drawn at low opacity so day-to-day stability is
    visible, with the mean and ±1σ band overlaid.  When a fit window
    was active the corresponding wavelength range is shaded.
    """
    if not results:
        print(f"  [R(λ)] {channel_name}: no data")
        return

    waves = [r["wave_nm"] for r in results if "wave_nm" in r and r["wave_nm"] is not None]
    curves = [r["r_curve"] for r in results if "r_curve" in r and r["r_curve"] is not None]
    if not waves or not curves:
        print(f"  [R(λ)] {channel_name}: no r_curve data collected")
        return

    # Trim every scan to the shortest length so we can stack into a 2-D array
    n_min = min(len(w) for w in waves)
    waves   = [w[:n_min] for w in waves]
    curves  = [c[:n_min] for c in curves]
    wave_common = np.asarray(waves[0], dtype=float)
    r_stack     = np.asarray(curves, dtype=float)

    fig, ax = plt.subplots(figsize=(12, 5))

    # Per-scan overlay (alpha blending)
    for r in r_stack:
        ax.plot(wave_common, r, color=color, alpha=0.07, lw=0.6)

    # Mean + ±1σ
    r_mean = np.mean(r_stack, axis=0)
    r_std  = np.std(r_stack, axis=0)
    ax.fill_between(wave_common, r_mean - r_std, r_mean + r_std,
                    color=color, alpha=0.25, label="±1σ across scans")
    ax.plot(wave_common, r_mean, color=color, lw=1.8, label="mean R(λ)")

    # Highlight fit window when one was used consistently
    fws = {r.get("fit_window_nm") for r in results}
    fws.discard(None)
    if len(fws) == 1:
        fw = fws.pop()
        ax.axvspan(fw[0], fw[1], alpha=0.06, color="green",
                   label=f"fit window {fw[0]:.0f}-{fw[1]:.0f} nm")

    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Reflectivity R(λ)")
    ax.set_title(f"CAESAR Pro — {channel_name} R(λ) ({len(r_stack)} scans)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)

    plt.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=PLOT_DPI, bbox_inches="tight")
    print(f"  [PNG] {out_path}")
    if SHOW_PLOT: plt.show()
    plt.close(fig)



def plot_combined(results_cold, results_hot_pns, results_hot_ans, out_path):
    # 3채널(Cold / Hot PNs / Hot ANs) × (R + 선택적 Leff)
    per_ch = 2 if SHOW_LEFF else 1
    n_rows = 3 * per_ch
    fig, axes = plt.subplots(n_rows, 1, figsize=(14, 3.5 * n_rows), sharex=False, squeeze=False)
    fig.suptitle("CAESAR Pro — Cold / Hot PNs(roi1) / Hot ANs(roi2) Mirror Reflectivity Trend", fontsize=12)
    channels = [
        (results_cold,    "Cold",            R_EXPECTED_COLD, "steelblue"),
        (results_hot_pns, "Hot PNs(roi1)",   R_EXPECTED_HOT,  "darkorange"),
        (results_hot_ans, "Hot ANs(roi2)",   R_EXPECTED_HOT,  "crimson"),
    ]
    for i, (res, name, r_exp, color) in enumerate(channels):
        ax_r = axes[i * per_ch, 0]
        ax_l = axes[i * per_ch + 1, 0] if SHOW_LEFF else None
        _plot_channel(ax_r, ax_l, res, name, r_exp, color)
    plt.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=PLOT_DPI, bbox_inches="tight")
    print(f"  [PNG] {out_path}")
    if SHOW_PLOT: plt.show()
    plt.close(fig)

def main():
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   CAESAR Pro — r_trend_monitor.py  반사율 시계열 모니터        ║")
    print(f"║   ZA={FLAG_ZA}  He={FLAG_HE}  cavity={CAVITY_LEN}cm  RL={RL_FACTOR}             ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── 파장 보정 파일 로드 (Cold / Hot PNs / Hot ANs) ──
    # Hot은 한 raw 파일 안에 ROI 2개(PNs=CH2 / ANs=CH3)가 있어 파장보정이 각각 다르다.
    wave_nm_cold = wave_nm_hot_pns = wave_nm_hot_ans = None

    def _load_wave(path, label):
        if not os.path.isfile(path):
            print(f"[경고] 파일 없음: {path}")
            return None
        try:
            with open(path, "r", encoding="utf-8") as _f:
                return np.loadtxt(_f)
        except Exception as exc:
            print(f"[경고] {label} 파장 로드 실패: {exc}")
            return None

    wave_nm_cold    = _load_wave(WAVE_CAL_COLD,    "Cold")
    wave_nm_hot_pns = _load_wave(WAVE_CAL_HOT,     "Hot PNs(roi1)")
    wave_nm_hot_ans = _load_wave(WAVE_CAL_HOT_ANS, "Hot ANs(roi2)")

    has_hot = (HOT_FILES is not None or os.path.isdir(HOT_DIR))

    # ── Cold 채널 (CH2) ───────────────────────────────────────────
    bar = "=" * 64
    print(f"\n{bar}\n  Cold 채널 처리\n{bar}")
    results_cold = scan_directory(COLD_DIR, wave_nm_cold, COLD_FILES,
                                  col_press=COL_PRESS_COLD, col_temp=COL_TEMP_COLD,
                                  ts_tz=COLD_TS_TZ,
                                  spec_start=SPEC_START_DEFAULT, spec_end=SPEC_END_DEFAULT,
                                  fit_window_nm=CH_FIT_WINDOW_NM["cold"]) \
                   if (COLD_FILES is not None or os.path.isdir(COLD_DIR)) else []

    # ── Hot PNs(roi1) 채널 (CH2, 컬럼 2053-4100) ──────────────────
    print(f"\n{bar}\n  Hot PNs(roi1) 채널 처리  fit window: {CH_FIT_WINDOW_NM['hot_pns']} nm\n{bar}")
    results_hot_pns = scan_directory(HOT_DIR, wave_nm_hot_pns, HOT_FILES,
                                     col_press=COL_PRESS_HOT_PNS, col_temp=COL_TEMP_HOT,
                                     ts_tz=HOT_TS_TZ,
                                     spec_start=SPEC_START_DEFAULT, spec_end=SPEC_END_DEFAULT,
                                     fit_window_nm=CH_FIT_WINDOW_NM["hot_pns"]) \
                      if has_hot else []

    # ── Hot ANs(roi2) 채널 (CH3, 컬럼 4101-6148) ──────────────────
    print(f"\n{bar}\n  Hot ANs(roi2) 채널 처리  fit window: {CH_FIT_WINDOW_NM['hot_ans']} nm\n{bar}")
    results_hot_ans = scan_directory(HOT_DIR, wave_nm_hot_ans, HOT_FILES,
                                     col_press=COL_PRESS_HOT_ANS, col_temp=COL_TEMP_HOT,
                                     ts_tz=HOT_ANS_TS_TZ,
                                     spec_start=SPEC_START_ANS, spec_end=SPEC_END_ANS,
                                     fit_window_nm=CH_FIT_WINDOW_NM["hot_ans"]) \
                      if has_hot else []

    # ── 출력 폴더 이름 결정 및 저장 ──────────────────────────────────
    range_cold    = make_range_name(results_cold)
    range_hot_pns = make_range_name(results_hot_pns)
    range_hot_ans = make_range_name(results_hot_ans)
    all_results = results_cold + results_hot_pns + results_hot_ans
    folder_name = make_range_name(sorted(all_results, key=lambda x: x["timestamp"])) if all_results else "nodata"
    out_folder = os.path.join(OUTPUT_DIR, folder_name)
    os.makedirs(out_folder, exist_ok=True)

    print(f"\n{bar}\n  결과 저장  →  {out_folder}\n{bar}")
    if results_cold:    save_dat(results_cold,    os.path.join(out_folder, f"Cold_{range_cold}.dat"))
    if results_hot_pns: save_dat(results_hot_pns, os.path.join(out_folder, f"Hot_PNs_{range_hot_pns}.dat"))
    if results_hot_ans: save_dat(results_hot_ans, os.path.join(out_folder, f"Hot_ANs_{range_hot_ans}.dat"))

    # Per-file R(λ) curves (raw points + 5-th order poly fit) for the GUI's
    # per-scan plot. Path layout matches ui_dialogs_r.py expectations.
    if results_cold:    save_r_curves_per_file(results_cold,    "R_Cold",    out_folder)
    if results_hot_pns: save_r_curves_per_file(results_hot_pns, "R_Hot_PNs", out_folder)
    if results_hot_ans: save_r_curves_per_file(results_hot_ans, "R_Hot_ANs", out_folder)

    if HAS_MPL:
        if results_cold:    plot_single_channel(results_cold,    "Cold",        R_EXPECTED_COLD, os.path.join(out_folder, "R_trend_Cold.png"),    "steelblue")
        if results_hot_pns: plot_single_channel(results_hot_pns, "Hot PNs",     R_EXPECTED_HOT,  os.path.join(out_folder, "R_trend_Hot_PNs.png"), "darkorange")
        if results_hot_ans: plot_single_channel(results_hot_ans, "Hot ANs",     R_EXPECTED_HOT,  os.path.join(out_folder, "R_trend_Hot_ANs.png"), "crimson")
        if all_results: plot_combined(results_cold, results_hot_pns, results_hot_ans, os.path.join(out_folder, "R_trend_combined.png"))

        # R(λ) per-scan overlay + mean spectrum (박사님 Rs2.m line 144 style)
        if results_cold:    plot_r_curves_per_channel(results_cold,    "Cold",        "steelblue",  os.path.join(out_folder, "R_curve_Cold.png"))
        if results_hot_pns: plot_r_curves_per_channel(results_hot_pns, "Hot PNs(roi1)", "darkorange", os.path.join(out_folder, "R_curve_Hot_PNs.png"))
        if results_hot_ans: plot_r_curves_per_channel(results_hot_ans, "Hot ANs(roi2)", "crimson",    os.path.join(out_folder, "R_curve_Hot_ANs.png"))

    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║  완료 — 반사율 요약                                            ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    for ch, res, r_exp in [("Cold    ", results_cold, R_EXPECTED_COLD),
                           ("Hot PNs ", results_hot_pns, R_EXPECTED_HOT),
                           ("Hot ANs ", results_hot_ans, R_EXPECTED_HOT)]:
        if not res:
            print(f"║  {ch}: 데이터 없음")
            continue
        r_vals = np.array([r["r_mean"] for r in res])
        print(f"║  {ch}: 사이클 {len(res)}개  R_mean={np.mean(r_vals):.6f}  경고={int(np.sum(r_vals < r_exp - R_WARN_DELTA))}건")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    return results_cold, results_hot_pns, results_hot_ans, out_folder

if __name__ == "__main__":
    main()
