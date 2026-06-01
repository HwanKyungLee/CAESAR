"""Plot raw spectra for a given date, grouped by flag (ZA / He / Sampling).

Usage
-----
python tools/plot_spectra_by_date.py --date 20260521 --raw_dir D:\path\to\raw\2026-05
    [--system hot|cold]
    [--channel PNs|ANs|NO2]          # default: primary channel for system
    [--wave_csv path\to\wave.csv]    # optional: 2048-row file, one nm per line
    [--out_dir .]                    # where to write the PNG
    [--flags ZA He sampling]         # which flags to include (default: all three)
    [--max_per_flag 50]              # max spectra overlaid per flag (0 = all)

Output
------
One PNG with three panels (ZA / He / Sampling), each showing all raw spectra
for that flag overlaid in semi-transparent colour, plus the mean in solid.
Vertical lines mark detected peaks on the mean spectrum.
"""
from __future__ import annotations
import argparse, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import find_peaks

# ── make sure repo root is on the path ────────────────────────────────────────
REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from core.raw_parser import (
    RawParser,
    FLAG_ZA, FLAG_HE, FLAG_AMBIENT,
    SPEC_PRIMARY, SPEC_SECONDARY,
)


# ── helpers ───────────────────────────────────────────────────────────────────────

def load_wave(csv_path: str | None, n_pixels: int = 2048) -> np.ndarray:
    """Return wavelength array (nm).  Falls back to pixel indices 0..n_pixels-1."""
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


def detect_peaks(mean_sp: np.ndarray, wave: np.ndarray) -> np.ndarray:
    """Return indices of prominent peaks in mean_sp."""
    height_thr = np.percentile(mean_sp, 70)
    pks, _ = find_peaks(mean_sp, height=height_thr,
                         prominence=np.ptp(mean_sp) * 0.02,
                         distance=10)
    return pks


def plot_flag_panel(ax, spectra: list[np.ndarray], wave: np.ndarray,
                    flag_label: str, color: str) -> None:
    if not spectra:
        ax.text(0.5, 0.5, f"No {flag_label} rows found",
                ha="center", va="center", transform=ax.transAxes, fontsize=11)
        ax.set_title(flag_label)
        return

    arr = np.stack(spectra)
    mean_sp = arr.mean(axis=0)

    for sp in arr:
        ax.plot(wave, sp, color=color, lw=0.4, alpha=max(0.05, min(0.3, 5/len(arr))))

    ax.plot(wave, mean_sp, color="black", lw=1.6, label=f"mean (n={len(arr)})")

    pks = detect_peaks(mean_sp, wave)
    if pks.size:
        ax.vlines(wave[pks], mean_sp[pks] * 0.98, mean_sp[pks] * 1.02,
                  colors="red", lw=1.2, label=f"{len(pks)} peaks")
        for pk in pks:
            ax.annotate(f"{wave[pk]:.1f}", xy=(wave[pk], mean_sp[pk]),
                        xytext=(0, 6), textcoords="offset points",
                        ha="center", fontsize=7, color="red")

    x_label = "Wavelength (nm)" if wave[0] > 1 else "Pixel"
    ax.set_xlabel(x_label)
    ax.set_ylabel("Counts")
    ax.set_title(f"{flag_label}  (n={len(arr)})")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25)


# ── main ──────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Plot raw spectra by flag for one date")
    ap.add_argument("--date",        required=True,  help="YYYYMMDD e.g. 20260521")
    ap.add_argument("--raw_dir",     required=True,  help="Folder containing *.dat files")
    ap.add_argument("--system",      default="hot",  choices=["hot", "cold"])
    ap.add_argument("--channel",     default=None,   help="PNs | ANs | NO2  (auto if omitted)")
    ap.add_argument("--wave_csv",    default=None,   help="CSV with 2048 wavelengths in nm")
    ap.add_argument("--out_dir",     default=".",    help="Output directory for PNG")
    ap.add_argument("--flags",       nargs="+",
                    default=["ZA", "He", "sampling"],
                    help="Flags to include: ZA He sampling")
    ap.add_argument("--max_per_flag", type=int, default=200,
                    help="Max spectra per flag (0=all)")
    args = ap.parse_args()

    flag_map = {"ZA": FLAG_ZA, "He": FLAG_HE, "sampling": FLAG_AMBIENT}
    target_flags = {flag_map[f] for f in args.flags if f in flag_map}
    flag_labels  = {FLAG_ZA: "ZA (500)", FLAG_HE: "He (510)", FLAG_AMBIENT: "Sampling (1)"}
    flag_colors  = {FLAG_ZA: "steelblue", FLAG_HE: "darkorange", FLAG_AMBIENT: "seagreen"}

    CH_PIXELS = 2048
    if args.system == "hot":
        default_ch, default_slice = "PNs", SPEC_PRIMARY
        ch_options = {"PNs": SPEC_PRIMARY, "ANs": SPEC_SECONDARY}
    else:
        default_ch, default_slice = "NO2", SPEC_PRIMARY
        ch_options = {"NO2": SPEC_PRIMARY}

    ch_name = args.channel or default_ch
    spec_slice = ch_options.get(ch_name, default_slice)

    wave = load_wave(args.wave_csv, CH_PIXELS)
    x_label = "Wavelength (nm)" if args.wave_csv else "Pixel"

    print(f"System: {args.system}  Channel: {ch_name}  Spectrum cols: {spec_slice}")
    print(f"Flags  : {[flag_labels[f] for f in sorted(target_flags)]}")
    print(f"Wave   : {'from CSV' if args.wave_csv else 'pixel index'}")

    buckets: dict[int, list[np.ndarray]] = {f: [] for f in target_flags}
    y, m, d = args.date[:4], args.date[4:6], args.date[6:8]
    prefix = f"{y}-{m}-{d}"

    files = sorted(
        f for f in os.listdir(args.raw_dir)
        if f.startswith(prefix) and f.endswith(".dat")
    )
    if not files:
        print(f"No .dat files found for {prefix} in {args.raw_dir}")
        sys.exit(1)
    print(f"\nFound {len(files)} file(s) — reading...")

    for fi, fname in enumerate(files, 1):
        path = os.path.join(args.raw_dir, fname)
        parser = RawParser(path, system=args.system)
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
        if fi % 10 == 0 or fi == len(files):
            counts = {flag_labels[f]: len(buckets[f]) for f in sorted(target_flags)}
            print(f"  [{fi}/{len(files)}]  {counts}")

    ordered = [f for f in [FLAG_ZA, FLAG_HE, FLAG_AMBIENT] if f in target_flags]
    n_panels = len(ordered)
    fig, axes = plt.subplots(n_panels, 1, figsize=(14, 4.5 * n_panels), squeeze=False)
    fig.suptitle(
        f"Raw spectra by flag — {args.system.upper()} / {ch_name} / {prefix}\n"
        f"({x_label})",
        fontsize=13,
    )

    for ax, flag in zip(axes[:, 0], ordered):
        plot_flag_panel(ax, buckets[flag], wave, flag_labels[flag], flag_colors[flag])

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    os.makedirs(args.out_dir, exist_ok=True)
    out_name = f"spectra_{args.system}_{ch_name}_{args.date}.png"
    out_path = os.path.join(args.out_dir, out_name)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\nSaved → {out_path}")

    print("\n=== Peak summary (mean spectrum) ===")
    for flag in ordered:
        sp_list = buckets[flag]
        if not sp_list:
            print(f"  {flag_labels[flag]}: no data")
            continue
        mean_sp = np.stack(sp_list).mean(axis=0)
        pks = detect_peaks(mean_sp, wave)
        if pks.size:
            peak_info = "  ".join(
                f"{wave[p]:.1f}({'nm' if args.wave_csv else 'px'})={mean_sp[p]:.0f}"
                for p in pks
            )
            print(f"  {flag_labels[flag]} ({len(sp_list)} spectra): {peak_info}")
        else:
            print(f"  {flag_labels[flag]} ({len(sp_list)} spectra): no prominent peaks")


if __name__ == "__main__":
    main()
