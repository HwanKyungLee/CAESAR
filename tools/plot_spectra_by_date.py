"""Plot raw spectra trend across dates, grouped by flag (ZA / He / Sampling).

Usage
-----
python tools/plot_spectra_by_date.py --date 20260521 20260601 --raw_dir D:\\path\\to\\CAESAR_Cold
    [--system hot|cold]
    [--channel PNs|ANs|NO2]          # default: primary channel for system
    [--wave_csv path\\to\\wave.csv]    # optional: 2048-row file, one nm per line
    [--out_dir .]                    # where to write the PNG
    [--flags ZA He sampling]         # which flags to include (default: all three)
    [--max_per_flag 200]             # max spectra averaged per date+flag (0 = all)

Notes
-----
* --raw_dir is searched RECURSIVELY, so you can point it at a parent folder
  containing month subfolders (e.g. 2026-05, 2026-06) and pass dates from
  either month.
* Output is a SINGLE PNG with three panels (ZA / He / Sampling). In each panel,
  the MEAN spectrum of each date is overlaid in a time-ordered colour
  (early=blue → late=red) so you can see the day-to-day trend. Peaks are marked
  on the overall mean.
"""
from __future__ import annotations
import argparse, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.colors import Normalize
from scipy.signal import find_peaks

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from core.raw_parser import (
    RawParser,
    FLAG_ZA, FLAG_HE, FLAG_AMBIENT,
    SPEC_PRIMARY, SPEC_SECONDARY,
)


def load_wave(csv_path: str | None, n_pixels: int = 2048) -> np.ndarray:
    """Return wavelength array (nm). Falls back to pixel indices 0..n_pixels-1."""
    if csv_path and os.path.isfile(csv_path):
        data = np.loadtxt(csv_path, delimiter=",", comments="#")
        if data.ndim == 2:
            wl = data[:, 1] if data.shape[1] >= 2 else data[:, 0]
        else:
            wl = data
        if len(wl) != n_pixels:
            print(f"⚠  Wave CSV has {len(wl)} rows, expected {n_pixels}. Using pixel indices.")
            return np.arange(n_pixels, dtype=float)
        return wl.astype(float)
    if csv_path:
        print(f"⚠  Wave CSV not found: {csv_path}. Using pixel indices.")
    return np.arange(n_pixels, dtype=float)


def find_files(raw_dir: str, prefix: str) -> list[str]:
    """Recursively find *.dat files whose basename starts with *prefix*."""
    hits = []
    for root, _dirs, names in os.walk(raw_dir):
        for n in names:
            if n.startswith(prefix) and n.endswith(".dat"):
                hits.append(os.path.join(root, n))
    return sorted(hits)


def detect_peaks(mean_sp: np.ndarray) -> np.ndarray:
    height_thr = np.percentile(mean_sp, 70)
    pks, _ = find_peaks(mean_sp, height=height_thr,
                        prominence=np.ptp(mean_sp) * 0.02,
                        distance=10)
    return pks


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot raw-spectra trend across dates by flag")
    ap.add_argument("--date", required=True, nargs="+",
                    help="YYYYMMDD (여러 날짜 가능) e.g. 20260521 20260601")
    ap.add_argument("--raw_dir",      required=True, help="Folder (searched recursively) with *.dat files")
    ap.add_argument("--system",       default="hot", choices=["hot", "cold"])
    ap.add_argument("--channel",      default=None,  help="PNs | ANs | NO2  (auto if omitted)")
    ap.add_argument("--wave_csv",     default=None,  help="CSV with 2048 wavelengths in nm")
    ap.add_argument("--out_dir",      default=".",   help="Output directory for PNG")
    ap.add_argument("--flags",        nargs="+",
                    default=["ZA", "He", "sampling"],
                    help="Flags to include: ZA He sampling")
    ap.add_argument("--max_per_flag", type=int, default=200,
                    help="Max spectra averaged per date+flag (0=all)")
    args = ap.parse_args()

    flag_map     = {"ZA": FLAG_ZA, "He": FLAG_HE, "sampling": FLAG_AMBIENT}
    target_flags = {flag_map[f] for f in args.flags if f in flag_map}
    flag_labels  = {FLAG_ZA: "ZA (500)", FLAG_HE: "He (510)", FLAG_AMBIENT: "Sampling (1)"}

    CH_PIXELS = 2048
    if args.system == "hot":
        default_ch = "PNs"
        ch_options = {"PNs": SPEC_PRIMARY, "ANs": SPEC_SECONDARY}
    else:
        default_ch = "NO2"
        ch_options = {"NO2": SPEC_PRIMARY}

    ch_name    = args.channel or default_ch
    spec_slice = ch_options.get(ch_name, SPEC_PRIMARY)
    wave       = load_wave(args.wave_csv, CH_PIXELS)
    x_label    = "Wavelength (nm)" if args.wave_csv else "Pixel index"

    dates = sorted(args.date)
    print(f"System : {args.system}  Channel: {ch_name}  Spectrum cols: {spec_slice}")
    print(f"Flags  : {[flag_labels[f] for f in sorted(target_flags)]}")
    print(f"Wave   : {'from CSV' if args.wave_csv else 'pixel index'}")
    print(f"Dates  : {dates}  (raw_dir searched recursively)")

    date_means: dict[int, dict[str, np.ndarray]] = {f: {} for f in target_flags}
    date_counts: dict[int, dict[str, int]] = {f: {} for f in target_flags}

    for date_str in dates:
        y, m, d = date_str[:4], date_str[4:6], date_str[6:8]
        prefix  = f"{y}-{m}-{d}"
        files   = find_files(args.raw_dir, prefix)
        if not files:
            print(f"  {prefix}: no .dat files — skip")
            continue

        buckets: dict[int, list[np.ndarray]] = {f: [] for f in target_flags}
        for path in files:
            parser = RawParser(path)
            ch_key = next(
                (c for c, b in parser.layout.spec_blocks.items() if b == spec_slice), None
            )
            if ch_key is None:
                continue
            for row, specs in parser.iter_rows_with_spectra(channels=(ch_key,)):
                if row.flag not in target_flags:
                    continue
                sp = specs.get(ch_key)
                if sp is None:
                    continue
                b = buckets[row.flag]
                if args.max_per_flag == 0 or len(b) < args.max_per_flag:
                    b.append(sp.copy())

        for flag in target_flags:
            n = len(buckets[flag])
            date_counts[flag][date_str] = n
            if n:
                date_means[flag][date_str] = np.stack(buckets[flag]).mean(axis=0)
        counts = {flag_labels[f]: date_counts[f][date_str] for f in sorted(target_flags)}
        print(f"  {prefix}: {len(files)} file(s)  {counts}")

    ordered  = [f for f in [FLAG_ZA, FLAG_HE, FLAG_AMBIENT] if f in target_flags]
    n_panels = len(ordered)
    fig, axes = plt.subplots(n_panels, 1, figsize=(15, 4.8 * n_panels), squeeze=False)

    norm = Normalize(vmin=0, vmax=max(1, len(dates) - 1))
    cmap = cm.get_cmap("turbo")

    for ax, flag in zip(axes[:, 0], ordered):
        means = date_means[flag]
        if not means:
            ax.text(0.5, 0.5, f"No {flag_labels[flag]} data",
                    ha="center", va="center", transform=ax.transAxes, fontsize=11)
            ax.set_title(flag_labels[flag])
            continue

        for di, date_str in enumerate(dates):
            sp = means.get(date_str)
            if sp is None:
                continue
            ax.plot(wave, sp, color=cmap(norm(di)), lw=1.1, alpha=0.85,
                    label=f"{date_str} (n={date_counts[flag][date_str]})")

        overall = np.stack(list(means.values())).mean(axis=0)
        pks = detect_peaks(overall)
        if pks.size:
            for pk in pks:
                ax.axvline(wave[pk], color="gray", lw=0.6, ls=":", alpha=0.5)
                ax.annotate(f"{wave[pk]:.1f}", xy=(wave[pk], overall[pk]),
                            xytext=(0, 6), textcoords="offset points",
                            ha="center", fontsize=6.5, color="dimgray")

        ax.set_xlabel(x_label)
        ax.set_ylabel("Counts")
        ax.set_title(f"{flag_labels[flag]} — mean spectrum per date "
                     f"({len([1 for v in means.values()])} dates)")
        ax.legend(fontsize=7, ncol=2, loc="best")
        ax.grid(True, alpha=0.25)

    fig.suptitle(
        f"Spectra trend by flag — {args.system.upper()} / {ch_name} / "
        f"{dates[0]}–{dates[-1]}  ({x_label})",
        fontsize=13,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    os.makedirs(args.out_dir, exist_ok=True)
    tag = f"{dates[0]}_{dates[-1]}" if len(dates) > 1 else dates[0]
    out_path = os.path.join(args.out_dir, f"spectra_trend_{args.system}_{ch_name}_{tag}.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
