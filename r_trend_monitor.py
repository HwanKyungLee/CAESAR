"""
r_trend_monitor.py — CAESAR Pro 거울 반사율 시계열 모니터
==========================================================
raw .dat 파일들을 스캔하여 파일 하나당 R_mean 값을 계산하고,
시간 순으로 정렬한 뒤 반사율이 유지되고 있는지 그래프로 확인합니다.
"""

import os
import re
import sys
import glob
from datetime import datetime, timedelta, timezone
import numpy as np

# 모듈 경로 문제 해결을 위한 강제 패스 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
HAS_MPL = True

try:
    from reflectance_calc import ReflectanceCalculator
    from auto_r_calculator import (
        read_all_scans, FLAG_ZA, FLAG_HE,
        CAVITY_LEN, RL_FACTOR, PIXEL_MIN, PIXEL_MAX,
        COL_PRESS_COLD, COL_TEMP_COLD, COL_PRESS_HOT, COL_TEMP_HOT,
    )
except ImportError as e:
    print(f"[오류] 필수 모듈을 찾을 수 없습니다: {e}")
    sys.exit(1)

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
COLD_DIR = r"H:\Yeosu_2026\CAESAR_Cold\2026-05"
HOT_DIR  = r"H:\Yeosu_2026\CAESAR_Hot\2026-05"

# 파장 보정 파일 경로 (정확한 파일명 적용 완료)
WAVE_CAL_COLD = r"C:\CAESAR_pro_package\reference\wavelength_cal\CAESAR cold\Calib_20260507_Hg_399-494nm_Poly2.txt"
WAVE_CAL_HOT  = r"C:\CAESAR_pro_package\reference\wavelength_cal\CAESAR hot\roi1\Calib_20260403_Hg_400-499nm(roi1).txt"

OUTPUT_DIR  = r"."
FILE_PATTERN = "*.dat"
R_EXPECTED_COLD = 0.9990
R_EXPECTED_HOT  = 0.9990
R_WARN_DELTA = 0.0005

# [방법 1] 전체 처리 시 None 사용
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
_UTC      = timezone.utc
_KST_TZ   = timezone(timedelta(hours=9))

def _parse_timestamp(filepath: str) -> datetime:
    """
    Araon Mega-Matrix 파일에서 첫 번째 스캔 시각을 읽어 KST로 반환.
      col 1  = 자정 기준 UTC 경과 초  (예: 44207 = 12:16:47 UTC)
      파일명 = UTC 날짜  (예: "2026-05-18-023.dat")
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                tokens = line.split("\t")
                if len(tokens) >= 6175:
                    secs = float(tokens[1])
                    if 0.0 <= secs < 86400.0:
                        fname = os.path.basename(filepath)
                        m = _DATE_RE.search(fname)
                        if m:
                            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                            base_utc = datetime(y, mo, d, tzinfo=_UTC)
                            return (base_utc + timedelta(seconds=secs)).astimezone(_KST_TZ)
                break   # 첫 번째 유효 행만 읽음
    except Exception:
        pass

    # fallback 1: 파일 mtime → KST
    try:
        return datetime.fromtimestamp(os.path.getmtime(filepath), tz=_KST_TZ)
    except OSError:
        pass

    # fallback 2: 현재 시각
    return datetime.now(tz=_KST_TZ)

def scan_directory(directory: str, wave_nm, file_list=None,
                   col_press=COL_PRESS_COLD, col_temp=COL_TEMP_COLD) -> list[dict]:
    """파일마다 R을 계산해 결과 목록을 반환한다.
    He가 있는 파일: He 갱신 후 해당 파일 ZA + 새 He로 계산.
    He가 없는 파일: 직전 He + 해당 파일 ZA로 계산.
    col_press/col_temp: 채널별 HK 컬럼 인덱스 (Cold/Hot 다름).
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
    last_he = []   # 가장 최근 He 스캔 (파일 간 유지)

    for fp in files:
        fname = os.path.basename(fp)
        za, he = read_all_scans(fp, col_press, col_temp)

        if he:
            last_he = he   # 새 He 캘리브레이션 갱신

        if not za or not last_he:
            print(f"  [{fname}] ⏳ 스킵 (ZA:{len(za)} He누적:{len(last_he)})")
            continue

        try:
            rc = ReflectanceCalculator(cavity_len=CAVITY_LEN, rl_factor=RL_FACTOR)
            for sp, t, p in za:      rc.add_za_spectrum(sp, t, p)
            for sp, t, p in last_he: rc.add_he_spectrum(sp, t, p)
            wave_out, r_curve, omr_d = rc.calculate(wave_nm)

            res = {
                "timestamp":  _parse_timestamp(fp),
                "filename":   fname,
                "r_mean":     float(np.mean(r_curve)),
                "r_std":      float(np.std(r_curve)),
                "r_min":      float(np.min(r_curve)),
                "r_max":      float(np.max(r_curve)),
                "leff_mean":  float(np.nanmean(np.where(omr_d > 1e-10, 1.0 / omr_d * 1e-5, np.nan))),
                "valid_frac": rc.valid_fraction,
                "n_za":       len(za),
                "n_he":       len(last_he),
            }
            results.append(res)
            tag = ("  [He갱신]" if he else "") + ("  ⚠️ 이상값" if not rc.quality_ok else "")
            print(f"  [{fname}] ✅ R_mean={res['r_mean']:.6f}  valid={res['valid_frac']*100:.1f}%{tag}")
        except Exception as e:
            print(f"  [{fname}] ❌ {e}")

    print(f"\n  총 파일: {len(files)}  성공: {len(results)}  실패/스킵: {len(files)-len(results)}")
    return results

def _stem_digits(filename: str) -> str:
    return re.sub(r"[^0-9]", "", os.path.splitext(os.path.basename(filename))[0])

def make_range_name(results: list[dict]) -> str:
    if not results: return "nodata"
    first = _stem_digits(results[0]["filename"])
    last  = _stem_digits(results[-1]["filename"])
    if first == last: return first
    return f"{first}_{last}"

def save_dat(results: list[dict], out_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(f"# CAESAR Pro — Mirror Reflectivity Trend\n")
        fh.write(f"# cavity={CAVITY_LEN} cm  RL={RL_FACTOR}  ZA_flag={FLAG_ZA}  He_flag={FLAG_HE}\n")
        fh.write("timestamp\tfilename\tR_mean\tR_std\tR_min\tR_max\tLeff_mean_km\tvalid_frac_pct\tn_ZA\tn_He\n")
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

    times  = [r["timestamp"] for r in results]
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

def plot_single_channel(results, channel_name, r_expected, out_path, color="steelblue"):
    n_panels = 2 if SHOW_LEFF else 1
    fig, axes = plt.subplots(n_panels, 1, figsize=(12, 4 * n_panels), sharex=True, squeeze=False)
    fig.suptitle(f"CAESAR Pro — {channel_name} Channel Mirror Reflectivity Trend\n(cavity={CAVITY_LEN} cm  RL={RL_FACTOR}  ZA flag={FLAG_ZA}  He flag={FLAG_HE})", fontsize=11)
    ax_r = axes[0, 0]
    ax_l = axes[1, 0] if SHOW_LEFF else None
    _plot_channel(ax_r, ax_l, results, channel_name, r_expected, color)
    if ax_l: ax_l.set_xlabel("Date / Time")
    else: ax_r.set_xlabel("Date / Time")
    plt.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=PLOT_DPI, bbox_inches="tight")
    print(f"  [PNG] {out_path}")
    if SHOW_PLOT: plt.show()
    plt.close(fig)

def plot_combined(results_cold, results_hot, out_path):
    n_rows = 4 if SHOW_LEFF else 2
    fig, axes = plt.subplots(n_rows, 1, figsize=(14, 3.5 * n_rows), sharex=False, squeeze=False)
    fig.suptitle("CAESAR Pro — Cold / Hot Channel Mirror Reflectivity Trend", fontsize=12)
    _plot_channel(axes[0, 0], axes[1, 0] if SHOW_LEFF else None, results_cold, "Cold", R_EXPECTED_COLD, "steelblue")
    _plot_channel(axes[2, 0], axes[3, 0] if SHOW_LEFF else None, results_hot, "Hot", R_EXPECTED_HOT, "darkorange")
    for i in range(n_rows): axes[i, 0].set_xlabel("Date / Time")
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

    # ── 파장 보정 파일 로드 (Cold / Hot 분리) ──
    wave_nm_cold, wave_nm_hot = None, None

    if os.path.isfile(WAVE_CAL_COLD):
        try: wave_nm_cold = np.loadtxt(WAVE_CAL_COLD)
        except Exception as exc: print(f"[경고] Cold 파장 로드 실패: {exc}")
    else: print(f"[경고] 파일 없음: {WAVE_CAL_COLD}")

    if os.path.isfile(WAVE_CAL_HOT):
        try: wave_nm_hot = np.loadtxt(WAVE_CAL_HOT)
        except Exception as exc: print(f"[경고] Hot 파장 로드 실패: {exc}")
    else: print(f"[경고] 파일 없음: {WAVE_CAL_HOT}")

    # ── Cold 채널 ─────────────────────────────────────────────────
    bar = "=" * 64
    print(f"\n{bar}\n  Cold 채널 처리\n{bar}")
    results_cold = scan_directory(COLD_DIR, wave_nm_cold, COLD_FILES,
                                  col_press=COL_PRESS_COLD, col_temp=COL_TEMP_COLD) \
                   if (COLD_FILES is not None or os.path.isdir(COLD_DIR)) else []

    # ── Hot 채널 ──────────────────────────────────────────────────
    print(f"\n{bar}\n  Hot 채널 처리\n{bar}")
    results_hot = scan_directory(HOT_DIR, wave_nm_hot, HOT_FILES,
                                 col_press=COL_PRESS_HOT, col_temp=COL_TEMP_HOT) \
                  if (HOT_FILES is not None or os.path.isdir(HOT_DIR)) else []

    # ── 출력 폴더 이름 결정 및 저장 ──────────────────────────────────
    range_cold = make_range_name(results_cold)
    range_hot  = make_range_name(results_hot)
    all_results = results_cold + results_hot
    folder_name = make_range_name(sorted(all_results, key=lambda x: x["timestamp"])) if all_results else "nodata"
    out_folder = os.path.join(OUTPUT_DIR, folder_name)
    os.makedirs(out_folder, exist_ok=True)

    print(f"\n{bar}\n  결과 저장  →  {out_folder}\n{bar}")
    if results_cold: save_dat(results_cold, os.path.join(out_folder, f"Cold_{range_cold}.dat"))
    if results_hot:  save_dat(results_hot, os.path.join(out_folder, f"Hot_{range_hot}.dat"))

    if HAS_MPL:
        if results_cold: plot_single_channel(results_cold, "Cold", R_EXPECTED_COLD, os.path.join(out_folder, "R_trend_Cold.png"), "steelblue")
        if results_hot:  plot_single_channel(results_hot, "Hot", R_EXPECTED_HOT, os.path.join(out_folder, "R_trend_Hot.png"), "darkorange")
        if results_cold or results_hot: plot_combined(results_cold, results_hot, os.path.join(out_folder, "R_trend_combined.png"))

    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║  완료 — 반사율 요약                                            ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    for ch, res, r_exp in [("Cold", results_cold, R_EXPECTED_COLD), ("Hot ", results_hot, R_EXPECTED_HOT)]:
        if not res:
            print(f"║  {ch}: 데이터 없음")
            continue
        r_vals = np.array([r["r_mean"] for r in res])
        print(f"║  {ch}: 사이클 {len(res)}개  R_mean={np.mean(r_vals):.6f}  경고={int(np.sum(r_vals < r_exp - R_WARN_DELTA))}건")
    print("╚══════════════════════════════════════════════════════════════╝\n")

if __name__ == "__main__":
    main()
