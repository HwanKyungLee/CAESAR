"""Convert a small, explicit subset of Seosan MATLAB alpha rows.

This is an ingestion bridge, not a scientific recalibration step.  The old
Seosan MAT alpha files do not contain row-level T/P, so generated rows carry
the loader-compatible fallback values and an explicit UNAVAILABLE provenance
comment.  They must not be used as absolute-anchor T2 evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy.io import loadmat
import h5py


def _date_from_doy(year: int, doy: float) -> str:
    return (datetime(year, 1, 1) + timedelta(days=float(doy) - 1)).isoformat(sep=" ")


def convert(mat_path: Path, output: Path, channel: int, rows: list[int],
            year: int = 2020, pixel_slope: float = 0.048844,
            pixel_intercept: float = 404.0361, raw_mat_paths: list[Path] | None = None) -> Path:
    data = loadmat(mat_path, squeeze_me=True)
    key = f"alpha_abs{channel}"
    if key not in data or "std_t" not in data:
        raise ValueError(f"missing {key}/std_t in {mat_path}")
    alpha = np.asarray(data[key], dtype=float)
    doy = np.asarray(data["std_t"], dtype=float).reshape(-1)
    if alpha.ndim != 2 or alpha.shape[1] != 2048 or len(doy) != alpha.shape[0]:
        raise ValueError("MAT alpha/time dimensions are incompatible")
    selected = sorted(set(int(r) for r in rows))
    if not selected or selected[0] < 0 or selected[-1] >= alpha.shape[0]:
        raise ValueError("row index outside MAT alpha range")
    wave = pixel_intercept + pixel_slope * np.arange(2048, dtype=float)
    raw_doy = raw_p = raw_t = None
    if raw_mat_paths:
        parts = []
        for raw_path in raw_mat_paths:
            with h5py.File(raw_path, "r") as raw:
                parts.append((np.asarray(raw["doy"]).reshape(-1),
                              np.asarray(raw[f"presscell{channel}"]).reshape(-1),
                              np.asarray(raw[f"tempcell{channel}"]).reshape(-1)))
        raw_doy = np.concatenate([x[0] for x in parts])
        raw_p = np.concatenate([x[1] for x in parts])
        raw_t = np.concatenate([x[2] for x in parts])
        order = np.argsort(raw_doy)
        raw_doy, raw_p, raw_t = raw_doy[order], raw_p[order], raw_t[order]
        if len(raw_doy) == 0 or np.any(np.diff(raw_doy) < 0):
            raise ValueError("raw T/P time axis is invalid")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("# format: CAESAR alpha_trace v1\n")
        fh.write(f"# source_mat: {mat_path.name}\n")
        fh.write(f"# channel: CH{channel}\n")
        if raw_doy is None:
            fh.write("# T_P_PROVENANCE: UNAVAILABLE (MAT alpha has no row-level T/P)\n")
        else:
            fh.write("# T_P_PROVENANCE: matched_nearest_raw_mat_row\n")
        fh.write("# wavelength_nm: " + "\t".join(f"{x:.9f}" for x in wave) + "\n")
        fh.write("row_idx\tdatetime\tT_C\tP_mbar\t" +
                 "\t".join(f"px{i}" for i in range(2048)) + "\n")
        for row in selected:
            if raw_doy is None:
                temp_c, pressure_mbar = 25.0, 1013.25
            else:
                idx = int(np.argmin(np.abs(raw_doy - doy[row])))
                # Seosan stores these housekeeping values in tenths of mbar/C.
                temp_c, pressure_mbar = raw_t[idx] / 100.0, raw_p[idx] / 10.0
            fh.write(f"{row}\t{_date_from_doy(year, doy[row])}\t{temp_c:.6g}\t{pressure_mbar:.6g}\t")
            fh.write("\t".join(f"{x:.17g}" for x in alpha[row]))
            fh.write("\n")
    return output


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mat", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--channel", type=int, choices=(1, 2), required=True)
    p.add_argument("--rows", type=int, nargs="+", required=True)
    p.add_argument("--raw-mat", type=Path, nargs="*", default=None,
                   help="raw v7.3 MAT files supplying nearest-row T/P")
    args = p.parse_args()
    print(convert(args.mat, args.output, args.channel, args.rows, raw_mat_paths=args.raw_mat))


if __name__ == "__main__":
    main()
