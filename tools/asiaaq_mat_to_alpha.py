"""Export selected ASIA-AQ MATLAB alpha rows to CAESAR alpha_trace format.

This is an ingestion bridge only: it preserves the source alpha values and
housekeeping fields, and never invents temperature/pressure values.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy.io import loadmat


def _date_from_doy(year: int, doy: float) -> str:
    return (datetime(year, 1, 1) + timedelta(days=float(doy) - 1)).isoformat(sep=" ")


def convert(mat_path: Path, wave_mat: Path, output: Path, channel: int,
            rows: list[int], year: int = 2024) -> Path:
    data = loadmat(mat_path, squeeze_me=True)
    wave_data = loadmat(wave_mat, squeeze_me=True)
    alpha_key = f"alpha_abs{channel}"
    temp_key = f"tempcell{channel}{channel}"
    press_key = f"presscell{channel}{channel}"
    wave_key = f"wv_455_{channel}"
    required = (alpha_key, "std_t", temp_key, press_key)
    missing = [key for key in required if key not in data]
    if wave_key not in wave_data:
        missing.append(wave_key)
    if missing:
        raise ValueError("missing fields: " + ", ".join(missing))
    alpha = np.asarray(data[alpha_key], dtype=float)
    times = np.asarray(data["std_t"], dtype=float).reshape(-1)
    temp = np.asarray(data[temp_key], dtype=float).reshape(-1)
    pressure = np.asarray(data[press_key], dtype=float).reshape(-1)
    wave = np.asarray(wave_data[wave_key], dtype=float).reshape(-1)
    if alpha.ndim != 2 or alpha.shape[1] != len(wave):
        raise ValueError("alpha/wavelength dimensions are incompatible")
    if not (len(times) == len(temp) == len(pressure) == alpha.shape[0]):
        raise ValueError("row-level time/T/P dimensions are incompatible")
    selected = sorted(set(int(row) for row in rows))
    if not selected or selected[0] < 0 or selected[-1] >= alpha.shape[0]:
        raise ValueError("row index outside MAT alpha range")
    for row in selected:
        if not (np.isfinite(times[row]) and np.isfinite(temp[row]) and np.isfinite(pressure[row])):
            raise ValueError(f"row {row} has unavailable time/T/P")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("# format: CAESAR alpha_trace v1\n")
        fh.write(f"# source_mat: {mat_path.name}\n")
        fh.write(f"# channel={channel} label=ASIA_AQ_CH{channel}\n")
        fh.write("# T_P_PROVENANCE: measured_raw_housekeeping\n")
        fh.write("# wavelength_nm: " + "\t".join(f"{x:.12g}" for x in wave) + "\n")
        fh.write("row_idx\tdatetime\tT_C\tP_mbar\t" +
                 "\t".join(f"px{i}" for i in range(len(wave))) + "\n")
        for row in selected:
            fh.write(f"{row}\t{_date_from_doy(year, times[row])}\t"
                     f"{temp[row]:.12g}\t{pressure[row]:.12g}\t")
            fh.write("\t".join(f"{value:.17g}" for value in alpha[row]))
            fh.write("\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mat", type=Path, required=True)
    parser.add_argument("--wave-mat", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--channel", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--rows", type=int, nargs="+", required=True)
    args = parser.parse_args()
    print(convert(args.mat, args.wave_mat, args.output, args.channel, args.rows))


if __name__ == "__main__":
    main()
