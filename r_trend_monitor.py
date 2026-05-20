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
from datetime import datetime, timedelta
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
        CalibrationBuffer
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

FLAGS_ZA = [502]
FLAGS_HE = [512]

SHOW_LEFF  = True
SHOW_PLOT  = False
PLOT_DPI   = 150
# ════════════════════════════════════════════════════════════════

_TS_PATTERN = re.compile(r"(\d{4})[_\-](\d{2})[_\-](\d{2})[_\-](\d+)", re.IGNORECASE)

def _parse_timestamp(filepath: str) -> datetime:
    name = os.path.basename(filepath)
    m = _TS_PATTERN.search(name)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        seq  = int(m.group(4))
        try:
            return datetime(year, month, day) + timedelta(minutes=seq * 10)
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(os.path.getmtime(filepath))
    except OSError:
        return datetime.now()

def scan_directory(directory: str, wave_nm, file_list=None) -> list[dict]:
    """진행 상황과 에러 메시지를 상세히 출력하는 연속 계산 루프"""
    if file_list is not None:
        files = sorted(str(f) for f in file_list if os.path.isfile(str(f)))
    else:
        files = sorted(glob.glob(os.path.join(directory, FILE_PATTERN)))
        if not files:
            files = sorted(glob.glob(os.path.join(directory, "**", FILE_PATTERN), recursive=True))
            
    if not files:
        print(f"  .dat 파일 없음: {directory}")
        return []

    buffer = CalibrationBuffer()
    results = []

    print(f"  {len(files)}개 파일 연속 처리 시작...\n")
    
    for fp in files:
        fname = os.path.basename(fp)
        
        # 파일이 실제로 존재하는지 확인 (file_range 사용 시 없는 파일 지정 방지)
        if not os.path.isfile(fp):
            print(f"  [{fname}] ⚠️ 파일이 존재하지 않아 스킵합니다.")
            continue
            
        za_spectra, he_spectra = read_all_scans(fp)
        
        # 1. 캘리브레이션 데이터 업데이트
        if za_spectra or he_spectra:
            buffer.update(za_spectra, he_spectra)
            print(f"  [{fname}] 🔄 캘리브레이션 갱신 (ZA: {len(za_spectra)}행, He: {len(he_spectra)}행) | 준비상태: {buffer.is_ready}")
        
        # 2. 버퍼 준비 여부에 따른 처리
        if not buffer.is_ready:
            print(f"  [{fname}] ⏳ 대기 중 (아직 ZA와 He가 모두 확보되지 않음)")
            continue

        try:
            rc = ReflectanceCalculator(cavity_len=CAVITY_LEN, rl_factor=RL_FACTOR)
            for s, t, p in buffer.za_spectra: rc.add_za_spectrum(s, t, p)
            for s, t, p in buffer.he_spectra: rc.add_he_spectrum(s, t, p)
            
            wave_out, r_curve, omr_d = rc.calculate(wave_nm)
            
            res = {
                "timestamp": _parse_timestamp(fp),
                "filename": fname,
                "r_mean": float(np.mean(r_curve)),
                "r_std": float(np.std(r_curve)),
                "r_min": float(np.min(r_curve)),
                "r_max": float(np.max(r_curve)),
                "leff_mean": float(np.mean(1.0 / (omr_d + 1e-30) * 1e-5)),
                "valid_frac": rc.valid_fraction,
                "n_za": len(buffer.za_spectra),
                "n_he": len(buffer.he_spectra)
            }
            results.append(res)
            print(f"  [{fname}] ✅ 계산 성공 (R_mean: {res['r_mean']:.6f})")
            
        except Exception as e:
            print(f"  [{fname}] ❌ 계산 실패: {e}")

    return results

def _stem_digits(filename: str) -> str:
    return re.sub(r"[^0-9]", "", os.path.splitext(os.path.basename(filename)))

def make_range_name(results: list[dict]) -> str:
    if not results: return "nodata"
    first = _stem_digits(results["filename"])
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
                f"{r['filename']}\t{r['r_mean']:.8f}\t{r['r_std']:.8f}\t"
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

    y_lo = min(float(np.min(r_mean - r_std)), r_expected - R_WARN_DELTA - 0.0005)
    y_hi = max(float(np.max(r_mean + r_std)), r_expected + 0.0005)
    ax_r.set_ylim(y_lo - 0.0005, y_hi + 0.0005)

    if ax_l is not None:
        ax_l.plot(times, leff, "s-", color=color, markersize=4, linewidth=1.0, alpha=0.8)
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
    ax_r = axes
    ax_l = axes if SHOW_LEFF else None
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
    _plot_channel(axes, axes if SHOW_LEFF else None, results_cold, "Cold", R_EXPECTED_COLD, "steelblue")
    _plot_channel(axes, axes if SHOW_LEFF else None, results_hot, "Hot", R_EXPECTED_HOT, "darkorange")
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
    results_cold = scan_directory(COLD_DIR, wave_nm_cold, COLD_FILES) if (COLD_FILES is not None or os.path.isdir(COLD_DIR)) else []

    # ── Hot 채널 ──────────────────────────────────────────────────
    print(f"\n{bar}\n  Hot 채널 처리\n{bar}")
    results_hot = scan_directory(HOT_DIR, wave_nm_hot, HOT_FILES) if (HOT_FILES is not None or os.path.isdir(HOT_DIR)) else []

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
        print(f"║  {ch}: 파일 {len(res)}개  R_mean={np.mean(r_vals):.6f}  경고={int(np.sum(r_vals < r_exp - R_WARN_DELTA))}건")
    print("╚══════════════════════════════════════════════════════════════╝\n")

if __name__ == "__main__":
    main()