"""
plot_r_results.py
R 결과 파일 시각화 — 3채널(Cold / Hot_PNs / Hot_ANs) 시계열 + R 스펙트럼
"""

import os
import glob
import numpy as np
import matplotlib
matplotlib.use("Agg")          # GUI 없이 파일로 저장
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.gridspec import GridSpec

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
BASE_DIR = r"C:\Users\kh548\OneDrive\바탕 화면\여수 필드 준비"
CHANNELS = {
    "Cold":     os.path.join(BASE_DIR, "R_Cold"),
    "Hot PNs":  os.path.join(BASE_DIR, "R_Hot_PNs"),
    "Hot ANs":  os.path.join(BASE_DIR, "R_Hot_ANs"),
}
OUT_DIR = BASE_DIR

COLORS = {"Cold": "#1f77b4", "Hot PNs": "#d62728", "Hot ANs": "#ff7f0e"}

# ── 데이터 로더 ───────────────────────────────────────────────────────────────

def load_channel(channel_dir):
    """채널 폴더 아래 모든 *_R.dat 읽기 → 파일별 (label, wave, R) 리스트 반환"""
    records = []
    files = []
    for root, dirs, fnames in os.walk(channel_dir):
        for fn in fnames:
            if fn.endswith("_R.dat"):
                files.append(os.path.join(root, fn))
    files = sorted(files)
    for fp in files:
        try:
            rows = []
            with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    parts = s.split("\t")
                    try:
                        rows.append([float(x) for x in parts])
                    except ValueError:
                        continue  # 컬럼명 행 스킵
            if not rows:
                continue
            data = np.array(rows)
            if data.ndim < 2 or data.shape[1] < 2:
                continue
            wave = data[:, 0]
            r    = data[:, 1]
            label = os.path.basename(fp).replace("_R.dat", "")
            records.append((label, wave, r))
        except Exception as e:
            print(f"  [로드 실패] {os.path.basename(fp)}: {e}")
            continue
    return records


def core_mean_r(wave, r):
    """전체 파장 범위 평균 R (캘 파일 그대로, 자르지 않음)"""
    return np.mean(r)


# ── 1. 시계열 그래프 (파일별 평균 R) ──────────────────────────────────────────

def make_timeseries_figure(all_records):
    fig, axes = plt.subplots(3, 1, figsize=(15, 11), sharex=False)
    fig.suptitle("Mirror Reflectivity R — Time Series  (full wavelength range mean)",
                 fontsize=13, fontweight="bold")

    global_ymin, global_ymax = 100.0, 0.0

    ch_ys = {}
    ch_xs = {}
    for ch_name, records in all_records.items():
        if not records:
            continue
        ys = np.array([core_mean_r(w, r) * 100.0 for _, w, r in records])
        ch_ys[ch_name] = ys
        ch_xs[ch_name] = list(range(len(records)))
        global_ymin = min(global_ymin, ys.min())
        global_ymax = max(global_ymax, ys.max())

    # 공통 y축 범위
    span = global_ymax - global_ymin
    pad  = max(span * 0.20, 0.03)
    ylo  = global_ymin - pad
    yhi  = global_ymax + pad
    if yhi - ylo < 0.20:
        mid  = (ylo + yhi) / 2
        ylo, yhi = mid - 0.10, mid + 0.10

    # 눈금 간격: 범위에 맞게 자동 결정
    span_plot = yhi - ylo
    if   span_plot < 0.15:  step = 0.02
    elif span_plot < 0.40:  step = 0.05
    elif span_plot < 0.80:  step = 0.10
    else:                   step = 0.20

    for ax, (ch_name, records) in zip(axes, all_records.items()):
        color = COLORS[ch_name]
        if not records or ch_name not in ch_ys:
            ax.set_title(f"{ch_name}  (no data)")
            continue

        ys = ch_ys[ch_name]
        xs = ch_xs[ch_name]

        ax.plot(xs, ys, "o-", color=color, markersize=5,
                linewidth=1.3, alpha=0.88, zorder=3)

        # 파일별 값 표시 (개수 적을 때)
        if len(xs) <= 30:
            for x, y in zip(xs, ys):
                ax.annotate(f"{y:.3f}", (x, y), textcoords="offset points",
                            xytext=(0, 6), fontsize=6, ha="center", color="gray")

        ax.set_title(f"{ch_name}  (n={len(records)} files)", fontsize=10)
        ax.set_ylabel("R (%)", fontsize=10)
        ax.set_ylim(ylo, yhi)
        ax.yaxis.set_major_locator(ticker.MultipleLocator(step))
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.3f"))
        ax.yaxis.set_minor_locator(ticker.MultipleLocator(step / 2))
        ax.grid(True, which="major", linestyle="--", alpha=0.45)
        ax.grid(True, which="minor", linestyle=":", alpha=0.25)
        ax.tick_params(axis="y", labelsize=9)

        # x축: 날짜 변경 지점에만 라벨
        labels  = [r[0] for r in records]
        shown   = []
        prev_dt = ""
        for i, lbl in enumerate(labels):
            dt = "-".join(lbl.split("-")[:3])
            if dt != prev_dt:
                shown.append(i)
                prev_dt = dt
        ax.set_xticks(shown)
        ax.set_xticklabels([labels[i] for i in shown],
                           rotation=30, ha="right", fontsize=8)
        ax.set_xlim(-0.5, len(xs) - 0.5)

    axes[-1].set_xlabel("File", fontsize=10)
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    out_path = os.path.join(OUT_DIR, "R_timeseries.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"[저장] {out_path}")
    plt.close(fig)


# ── 2. R 스펙트럼 그래프 (채널별 전체 파일 오버레이) ──────────────────────────

def make_spectra_figure(all_records):
    """채널별로 subplot, 중앙 파장 대역 R 스펙트럼 오버레이 (edge noise 제외)"""
    fig, axes = plt.subplots(3, 1, figsize=(13, 11), sharex=True)
    fig.suptitle("Mirror Reflectivity R — Spectra overlay  (full wavelength range)",
                 fontsize=13, fontweight="bold")

    for ax, (ch_name, records) in zip(axes, all_records.items()):
        if not records:
            ax.set_title(f"{ch_name}  (no data)")
            continue

        color = COLORS[ch_name]
        r_all = []
        wave_ref = None
        for lbl, wave, r in records:
            alpha = max(0.12, 0.9 - 0.012 * len(records))
            ax.plot(wave, r * 100.0, color=color, alpha=alpha, linewidth=0.7)
            r_all.append(r)
            if wave_ref is None:
                wave_ref = wave

        if not r_all:
            continue

        # 중앙값 스펙트럼 (길이 맞추기)
        min_len   = min(len(x) for x in r_all)
        r_stack   = np.vstack([x[:min_len] for x in r_all])
        w_stack   = wave_ref[:min_len]
        r_med     = np.median(r_stack, axis=0)
        ax.plot(w_stack, r_med * 100.0, color="black", linewidth=1.8,
                label="Median", zorder=5)

        ax.set_title(f"{ch_name}  (n={len(r_all)} files)", fontsize=10)
        ax.set_ylabel("R (%)", fontsize=10)
        ax.legend(fontsize=9, loc="lower center")
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.tick_params(labelsize=9)

        # y축: 중앙 대역 데이터 기준으로 타이트하게
        r_flat = r_stack.flatten() * 100.0
        p01  = np.percentile(r_flat, 0.5)
        p999 = np.percentile(r_flat, 99.5)
        span = p999 - p01
        pad  = max(span * 0.12, 0.02)
        ylo  = max(p01  - pad, 98.0)
        yhi  = min(p999 + pad, 100.05)
        if yhi - ylo < 0.15:
            mid = (ylo + yhi) / 2
            ylo, yhi = mid - 0.075, mid + 0.075
        ax.set_ylim(ylo, yhi)

        span_plot = yhi - ylo
        if   span_plot < 0.15:  step = 0.02
        elif span_plot < 0.40:  step = 0.05
        elif span_plot < 0.80:  step = 0.10
        else:                   step = 0.20
        ax.yaxis.set_major_locator(ticker.MultipleLocator(step))
        ax.yaxis.set_minor_locator(ticker.MultipleLocator(step / 2))
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.3f"))

    axes[-1].set_xlabel("Wavelength (nm)", fontsize=10)
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    out_path = os.path.join(OUT_DIR, "R_spectra.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"[저장] {out_path}")
    plt.close(fig)


# ── 3. 채널 비교 그래프 (같은 날짜 파일: PNs vs ANs) ─────────────────────────

def make_comparison_figure(all_records):
    """Hot PNs / Hot ANs 중앙값 스펙트럼 비교 (날짜별)"""
    pns_recs = all_records.get("Hot PNs", [])
    ans_recs = all_records.get("Hot ANs", [])
    if not pns_recs or not ans_recs:
        return

    # 날짜별로 그룹핑
    def group_by_date(records):
        d = {}
        for lbl, wave, r in records:
            date = "-".join(lbl.split("-")[:3])
            d.setdefault(date, []).append((lbl, wave, r))
        return d

    pns_g = group_by_date(pns_recs)
    ans_g = group_by_date(ans_recs)
    dates = sorted(set(pns_g) & set(ans_g))

    n = len(dates)
    if n == 0:
        return

    cols = min(n, 2)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(13, 4.5 * rows), squeeze=False)
    fig.suptitle("Hot PNs vs Hot ANs — Median R Spectra by Date",
                 fontsize=13, fontweight="bold")

    for idx, date in enumerate(dates):
        ax = axes[idx // cols][idx % cols]

        yvals_all = []
        for ch_name, grp, color in [("Hot PNs", pns_g[date], COLORS["Hot PNs"]),
                                     ("Hot ANs", ans_g[date], COLORS["Hot ANs"])]:
            r_list = [r for _, _, r in grp]
            if not r_list:
                continue
            min_len = min(len(x) for x in r_list)
            r_stack = np.vstack([x[:min_len] for x in r_list])
            r_med   = np.median(r_stack, axis=0)
            wave    = grp[0][1][:min_len]
            ax.plot(wave, r_med * 100.0, color=color, linewidth=1.5, label=ch_name)
            yvals_all.extend(r_med * 100.0)

        ax.set_title(date, fontsize=10)
        ax.set_xlabel("Wavelength (nm)", fontsize=8)
        ax.set_ylabel("R (%)", fontsize=8)
        ax.legend(fontsize=8)
        ax.grid(True, linestyle="--", alpha=0.35)
        ax.tick_params(labelsize=8)

        if yvals_all:
            arr = np.array(yvals_all)
            ylo = max(np.percentile(arr, 1)  - 0.05, 95.0)
            yhi = min(np.percentile(arr, 99) + 0.05, 100.1)
            if yhi - ylo < 0.20:
                mid = (ylo + yhi) / 2
                ylo, yhi = mid - 0.10, mid + 0.10
            ax.set_ylim(ylo, yhi)
            span = yhi - ylo
            step = 0.05 if span < 0.40 else (0.10 if span < 1.0 else 0.50)
            ax.yaxis.set_major_locator(ticker.MultipleLocator(step))
            ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.2f"))

    # 빈 subplot 숨김
    for idx in range(n, rows * cols):
        axes[idx // cols][idx % cols].set_visible(False)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    out_path = os.path.join(OUT_DIR, "R_PNs_vs_ANs.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"[저장] {out_path}")
    plt.close(fig)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("R 결과 파일 읽는 중...")
    all_records = {}
    for ch_name, ch_dir in CHANNELS.items():
        recs = load_channel(ch_dir)
        all_records[ch_name] = recs
        print(f"  {ch_name}: {len(recs)}개 파일")

    print("\n그래프 생성 중...")
    make_timeseries_figure(all_records)
    make_spectra_figure(all_records)
    make_comparison_figure(all_records)
    print("\n완료. 저장 위치:", OUT_DIR)


if __name__ == "__main__":
    main()
