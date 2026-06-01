"""Plot the PEAK-value time series per flag (ZA / He / Sampling) across dates.

What it does
------------
For every measurement row in the selected dates it records the spectrum's
peak intensity (max counts) and the row timestamp, then plots peak-vs-time
so you can see how each cavity readout drifts over the campaign:

  * ZA   (flag 500) — one point per zero-air measurement row
  * He   (flag 510) — one point per helium measurement row
  * Sampling (flag 1) — every ambient row, plotted as it was logged

This is a TREND view (x = time), not an averaged-spectrum overlay.

Usage
-----
python tools/plot_spectra_by_date.py --date 20260529 20260530 20260601 \\
       --raw_dir D:\\Yeosu_2026\\CAESAR_Cold
    [--channel PNs|ANs|NO2]   # which spectrum block (default: primary)
    [--out_dir .]             # where to write the PNG
    [--flags ZA He sampling]  # which flags to include (default: all three)
    [--stride 1]              # subsample rows (e.g. 10 = every 10th) for speed
    [--peak_pixel_lo 0 --peak_pixel_hi 2048]  # restrict peak search window

Notes
-----
* --raw_dir is searched RECURSIVELY, so a parent folder with month subfolders
  (2026-05, 2026-06) works with dates from either month.
* Timestamp = filename date (UTC) + col1 seconds-since-midnight → KST,
  matching DataIO.parse_row_timestamp. Falls back to file mtime if col1 is
  out of range.
"""
from __future__ import annotations
import argparse, os, re, sys
from datetime import datetime, timedelta, timezone
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from core.raw_parser import (
    RawParser,
    FLAG_ZA, FLAG_HE, FLAG_AMBIENT,
    SPEC_PRIMARY, SPEC_SECONDARY,
)

UTC = timezone.utc
KST = timezone(timedelta(hours=9))
_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def find_files(raw_dir: str, prefix: str) -> list[str]:
    """Recursively find *.dat files whose basename starts with *prefix*."""
    hits = []
    for root, _dirs, names in os.walk(raw_dir):
        for n in names:
            if n.startswith(prefix) and n.endswith(".dat"):
                hits.append(os.path.join(root, n))
    return sorted(hits)


def row_timestamp(fname: str, col1_sec: float, mtime: datetime,
                  row_idx: int) -> datetime:
    """filename date (UTC) + col1 seconds → KST. Falls back to mtime estimate."""
    m = _DATE_RE.search(os.path.basename(fname))
    if m and np.isfinite(col1_sec) and 0.0 <= col1_sec < 86400.0:
        base = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
        return (base + timedelta(seconds=col1_sec)).astimezone(KST)
    # fallback: file mtime + row spacing (~0.97 s/row)
    return mtime + timedelta(seconds=row_idx * 0.97)


def main() -> None:
    ap = argparse.ArgumentParser(description="Peak-value time series per flag across dates")
    ap.add_argument("--date", required=True, nargs="+",
                    help="YYYYMMDD (여러 날짜 가능) e.g. 20260529 20260601")
    ap.add_argument("--raw_dir",  required=True, help="Folder (searched recursively) with *.dat files")
    ap.add_argument("--channel",  default=None,  help="PNs | ANs | NO2  (auto if omitted)")
    ap.add_argument("--out_dir",  default=".",   help="Output directory for PNG")
    ap.add_argument("--flags",    nargs="+", default=["ZA", "He", "sampling"],
                    help="Flags to include: ZA He sampling")
    ap.add_argument("--stride",   type=int, default=1,
                    help="Subsample rows: plot every Nth matching row (default 1 = all)")
    ap.add_argument("--peak_pixel_lo", type=int, default=0,
                    help="Lower pixel bound for the peak search window")
    ap.add_argument("--peak_pixel_hi", type=int, default=2048,
                    help="Upper pixel bound for the peak search window")
    args = ap.parse_args()

    flag_map     = {"ZA": FLAG_ZA, "He": FLAG_HE, "sampling": FLAG_AMBIENT}
    target_flags = {flag_map[f] for f in args.flags if f in flag_map}
    flag_labels  = {FLAG_ZA: "ZA (500)", FLAG_HE: "He (510)", FLAG_AMBIENT: "Sampling (1)"}
    flag_colors  = {FLAG_ZA: "steelblue", FLAG_HE: "darkorange", FLAG_AMBIENT: "seagreen"}

    # spectrum block — primary by default; ANs only meaningful on hot files
    ch_block = SPEC_SECONDARY if (args.channel or "").upper() == "ANS" else SPEC_PRIMARY
    ch_label = (args.channel or "primary")
    p_lo, p_hi = max(0, args.peak_pixel_lo), min(2048, args.peak_pixel_hi)

    dates = sorted(args.date)
    print(f"Channel block: {ch_block} ({ch_label})")
    print(f"Flags  : {[flag_labels[f] for f in sorted(target_flags)]}")
    print(f"Peak window: pixels {p_lo}..{p_hi}   stride={args.stride}")
    print(f"Dates  : {dates}  (raw_dir searched recursively)")

    # series[flag] = (list[datetime], list[float peak])
    series: dict[int, tuple[list, list]] = {f: ([], []) for f in target_flags}

    for date_str in dates:
        y, m, d = date_str[:4], date_str[4:6], date_str[6:8]
        prefix  = f"{y}-{m}-{d}"
        files   = find_files(args.raw_dir, prefix)
        if not files:
            print(f"  {prefix}: no .dat files — skip")
            continue

        n_added = {f: 0 for f in target_flags}
        seen    = {f: 0 for f in target_flags}
        for path in files:
            parser = RawParser(path)
            ch_key = next(
                (c for c, b in parser.layout.spec_blocks.items() if b == ch_block), None
            )
            if ch_key is None:
                continue
            mtime = parser.layout.mtime
            for row, specs in parser.iter_rows_with_spectra(channels=(ch_key,)):
                if row.flag not in target_flags:
                    continue
                s = seen[row.flag]
                seen[row.flag] = s + 1
                if args.stride > 1 and (s % args.stride != 0):
                    continue
                sp = specs.get(ch_key)
                if sp is None or sp.size == 0:
                    continue
                peak = float(np.nanmax(sp[p_lo:p_hi]))
                ts = row_timestamp(path, row.time_centisec, mtime, row.row_idx)
                series[row.flag][0].append(ts)
                series[row.flag][1].append(peak)
                n_added[row.flag] += 1
        counts = {flag_labels[f]: n_added[f] for f in sorted(target_flags)}
        print(f"  {prefix}: {len(files)} file(s)  added {counts}")

    # ── plot: one panel per flag, x = time, y = peak counts ──────────────────
    ordered  = [f for f in [FLAG_ZA, FLAG_HE, FLAG_AMBIENT] if f in target_flags]
    n_panels = len(ordered)
    fig, axes = plt.subplots(n_panels, 1, figsize=(15, 4.2 * n_panels),
                             squeeze=False, sharex=True)

    for ax, flag in zip(axes[:, 0], ordered):
        ts_list, pk_list = series[flag]
        if not ts_list:
            ax.text(0.5, 0.5, f"No {flag_labels[flag]} data",
                    ha="center", va="center", transform=ax.transAxes, fontsize=11)
            ax.set_title(flag_labels[flag])
            continue
        # sort by time
        order = np.argsort(ts_list)
        ts_arr = np.array(ts_list)[order]
        pk_arr = np.array(pk_list)[order]
        ax.plot(ts_arr, pk_arr, "-", color=flag_colors[flag], lw=0.6, alpha=0.5)
        ax.plot(ts_arr, pk_arr, ".", color=flag_colors[flag], ms=3, alpha=0.8)
        ax.set_ylabel("Peak counts")
        ax.set_title(f"{flag_labels[flag]} — peak value over time  (n={len(ts_arr)})")
        ax.grid(True, alpha=0.25)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))

    axes[-1, 0].set_xlabel("Time (KST)")
    fig.suptitle(
        f"Peak-value trend by flag — {ch_label} / {dates[0]}–{dates[-1]}",
        fontsize=13,
    )
    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    os.makedirs(args.out_dir, exist_ok=True)
    tag = f"{dates[0]}_{dates[-1]}" if len(dates) > 1 else dates[0]
    out_path = os.path.join(args.out_dir, f"peak_trend_{ch_label}_{tag}.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
