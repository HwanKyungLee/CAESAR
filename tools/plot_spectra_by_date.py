"""Plot the PEAK-value trend per flag (ZA / He / Sampling) across dates.

Aggregation (built for spotting outliers)
-----------------------------------------
Plotting every raw row is unreadable (a He/ZA cycle holds hundreds of rows;
sampling has hundreds of thousands). Instead each panel is aggregated into
groups, and for every group we draw:

  * average  → dot
  * min/max  → faint lines (so a single out-of-range value in a group makes
               the max line spike up or the min line dip down — easy to spot)

Grouping per flag:
  * ZA   (flag 500) — per measurement cycle (consecutive rows; ≈1/hour)
  * He   (flag 510) — per measurement cycle (≈1/3 hours)
  * Sampling (flag 1) — per time bin (default 1 minute)

Usage
-----
python tools/plot_spectra_by_date.py --date 20260529 20260530 20260601 \\
       --raw_dir D:\\Yeosu_2026\\CAESAR_Cold
    [--channel PNs|ANs|NO2]      # spectrum block (default: primary)
    [--out_dir .]
    [--flags ZA He sampling]
    [--event_gap_min 5]          # gap (min) that starts a new ZA/He cycle
    [--sampling_bin_min 1]       # time-bin width (min) for sampling
    [--peak_pixel_lo 0 --peak_pixel_hi 2048]

Notes
-----
* --raw_dir is searched RECURSIVELY (month subfolders 2026-05, 2026-06 OK).
* Timestamp = encoded bytepack relative timing anchored to the file mtime
  (last row = mtime; others placed by their true bytepack spacing).
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
    hits = []
    for root, _dirs, names in os.walk(raw_dir):
        for n in names:
            if n.startswith(prefix) and n.endswith(".dat"):
                hits.append(os.path.join(root, n))
    return sorted(hits)


def row_timestamp(mtime: datetime, bp_sec: float, bp_last: float) -> datetime:
    """Timestamp = bytepack relative timing anchored to the file's mtime.

    The encoded bytepack ((col0<<16)|col1)/100 gives reliable *relative*
    row spacing (true per-row timing, including exposure differences between
    ZA/He/sampling), but its absolute offset is unreliable. So we anchor the
    last row to mtime (file-close time) and place every other row by its
    bytepack distance from the last:
        t(row) = mtime - (bp_last - bp_sec)
    Each file is anchored independently, so pauses between files don't smear.
    Falls back to mtime if the bytepack value is missing.
    """
    if np.isnan(bp_sec) or np.isnan(bp_last):
        return mtime
    return mtime - timedelta(seconds=(bp_last - bp_sec))


def _stats(seg: np.ndarray):
    return float(np.nanmean(seg)), float(np.nanmin(seg)), float(np.nanmax(seg))


def group_events(ts: np.ndarray, pk: np.ndarray, gap_min: float):
    """Group time-sorted points into cycles split by gaps > gap_min minutes.
    Returns (times, mean, vmin, vmax) — one entry per cycle."""
    if len(ts) == 0:
        return (np.array([]),) * 4
    order = np.argsort(ts); ts, pk = ts[order], pk[order]
    gap = timedelta(minutes=gap_min)
    T, A, LO, HI = [], [], [], []
    start = 0
    for i in range(1, len(ts)):
        if ts[i] - ts[i - 1] > gap:
            a, lo, hi = _stats(pk[start:i])
            T.append(ts[start] + (ts[i - 1] - ts[start]) / 2)
            A.append(a); LO.append(lo); HI.append(hi)
            start = i
    a, lo, hi = _stats(pk[start:])
    T.append(ts[start] + (ts[-1] - ts[start]) / 2)
    A.append(a); LO.append(lo); HI.append(hi)
    return np.array(T), np.array(A), np.array(LO), np.array(HI)


def bin_series(ts: np.ndarray, pk: np.ndarray, bin_min: float):
    """Time-bin continuous data. Returns (times, mean, vmin, vmax) per bin."""
    if len(ts) == 0:
        return (np.array([]),) * 4
    order = np.argsort(ts); ts, pk = ts[order], pk[order]
    t0 = ts[0]; width = timedelta(minutes=bin_min)
    keys = np.array([int((t - t0) / width) for t in ts])
    T, A, LO, HI = [], [], [], []
    for k in np.unique(keys):
        seg = pk[keys == k]
        a, lo, hi = _stats(seg)
        T.append(t0 + width * (int(k) + 0.5))
        A.append(a); LO.append(lo); HI.append(hi)
    return np.array(T), np.array(A), np.array(LO), np.array(HI)


def main() -> None:
    ap = argparse.ArgumentParser(description="Peak-value trend per flag (avg dot + min/max lines)")
    ap.add_argument("--date", required=True, nargs="+",
                    help="YYYYMMDD (여러 날짜 가능) e.g. 20260529 20260601")
    ap.add_argument("--raw_dir",  required=True, help="Folder (searched recursively) with *.dat files")
    ap.add_argument("--channel",  default=None,  help="PNs | ANs | NO2  (auto if omitted)")
    ap.add_argument("--out_dir",  default=".",   help="Output directory for PNG")
    ap.add_argument("--flags",    nargs="+", default=["ZA", "He", "sampling"],
                    help="Flags to include: ZA He sampling")
    ap.add_argument("--event_gap_min", type=float, default=5.0,
                    help="Gap in minutes that starts a new ZA/He cycle")
    ap.add_argument("--sampling_bin_min", type=float, default=1.0,
                    help="Time-bin width (minutes) for the sampling trend")
    ap.add_argument("--peak_pixel_lo", type=int, default=0)
    ap.add_argument("--peak_pixel_hi", type=int, default=2048)
    args = ap.parse_args()

    flag_map     = {"ZA": FLAG_ZA, "He": FLAG_HE, "sampling": FLAG_AMBIENT}
    target_flags = {flag_map[f] for f in args.flags if f in flag_map}
    flag_labels  = {FLAG_ZA: "ZA (500)", FLAG_HE: "He (510)", FLAG_AMBIENT: "Sampling (1)"}
    flag_colors  = {FLAG_ZA: "steelblue", FLAG_HE: "darkorange", FLAG_AMBIENT: "seagreen"}

    ch_block = SPEC_SECONDARY if (args.channel or "").upper() == "ANS" else SPEC_PRIMARY
    ch_label = (args.channel or "primary")
    p_lo, p_hi = max(0, args.peak_pixel_lo), min(2048, args.peak_pixel_hi)

    dates = sorted(args.date)
    print(f"Channel block: {ch_block} ({ch_label})   peak window px {p_lo}..{p_hi}")
    print(f"Flags  : {[flag_labels[f] for f in sorted(target_flags)]}")
    print(f"Dates  : {dates}  (recursive)")

    raw_ts: dict[int, list] = {f: [] for f in target_flags}
    raw_pk: dict[int, list] = {f: [] for f in target_flags}

    for date_str in dates:
        y, m, d = date_str[:4], date_str[4:6], date_str[6:8]
        prefix  = f"{y}-{m}-{d}"
        files   = find_files(args.raw_dir, prefix)
        if not files:
            print(f"  {prefix}: no .dat files — skip")
            continue
        n0 = {f: len(raw_ts[f]) for f in target_flags}
        for path in files:
            parser = RawParser(path)
            ch_key = next(
                (c for c, b in parser.layout.spec_blocks.items() if b == ch_block), None
            )
            if ch_key is None:
                continue
            mtime = parser.layout.mtime
            # Collect all rows first so the LAST bytepack value anchors the file
            file_rows = list(parser.iter_rows_with_spectra(channels=(ch_key,)))
            bp_last = next(
                (r.bytepack_sec for r, _ in reversed(file_rows)
                 if not np.isnan(r.bytepack_sec)), float("nan"))
            for row, specs in file_rows:
                if row.flag not in target_flags:
                    continue
                sp = specs.get(ch_key)
                if sp is None or sp.size == 0:
                    continue
                raw_pk[row.flag].append(float(np.nanmax(sp[p_lo:p_hi])))
                raw_ts[row.flag].append(row_timestamp(mtime, row.bytepack_sec, bp_last))
        added = {flag_labels[f]: len(raw_ts[f]) - n0[f] for f in sorted(target_flags)}
        print(f"  {prefix}: {len(files)} file(s)  rows {added}")

    ordered = [f for f in [FLAG_ZA, FLAG_HE, FLAG_AMBIENT] if f in target_flags]
    fig, ax = plt.subplots(figsize=(15, 6))

    legend_entries = []
    for flag in ordered:
        ts = np.array(raw_ts[flag]); pk = np.array(raw_pk[flag])
        if ts.size == 0:
            print(f"  (no data for {flag_labels[flag]})")
            continue

        if flag == FLAG_AMBIENT:
            T, A, LO, HI = bin_series(ts, pk, args.sampling_bin_min)
            sub = f"{len(T)} bins/{args.sampling_bin_min:g}min"
        else:
            T, A, LO, HI = group_events(ts, pk, args.event_gap_min)
            sub = f"{len(T)} cycles"

        c = flag_colors[flag]
        ax.plot(T, HI, "-", color=c, lw=0.8, alpha=0.30)
        ax.plot(T, LO, "-", color=c, lw=0.8, alpha=0.30)
        ax.plot(T, A,  "-", color=c, lw=0.5, alpha=0.50)
        line, = ax.plot(T, A, ".", color=c, ms=4, alpha=0.95)
        legend_entries.append((line, f"{flag_labels[flag]}  avg·min/max  ({sub}, {ts.size} rows)"))

    if legend_entries:
        ax.legend([e[0] for e in legend_entries],
                  [e[1] for e in legend_entries],
                  fontsize=9, loc="best")
    ax.set_ylabel("Peak counts")
    ax.set_xlabel("Time (KST)")
    ax.grid(True, alpha=0.25)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    fig.suptitle(f"Peak-value trend — {ch_label} / {dates[0]}–{dates[-1]}", fontsize=13)
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
