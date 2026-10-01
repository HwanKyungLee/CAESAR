# -*- coding: utf-8 -*-
"""tools/test_alpha_row_readers.py — 알파 행 읽기 두 함수가 예전 구현과 같은 결과인가 (2026-10-02).

- `DataIO.parse_alpha_row_time`: 행마다 strptime 두 번 → core.result_io.parse_row_time(26자 이하만).
- `DataIO._load_alpha_trace_row`: 행 하나 꺼낼 때마다 파일 전체를 다시 읽던 것 → 캐시(_alpha_file).
기준 구현을 여기 그대로 두고, 신·구 포맷 + 이상한 시각 문자열(분수 초·7자리·24시·공백·doy만)을 대조한다.

    python tools/test_alpha_row_readers.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np

from core.data_io import DataIO


def ref_time(filepath, row_index=0):
    """2026-10-02 이전 parse_alpha_row_time 그대로."""
    try:
        hdr, _wave, data_rows = DataIO._alpha_file(filepath)
    except Exception:
        return None
    if not hdr:
        return None
    dt_idx = hdr.index('datetime') if 'datetime' in hdr else None
    doy_idx = hdr.index('doy') if 'doy' in hdr else None
    if dt_idx is None and doy_idx is None:
        return None
    parts = data_rows[row_index].split('\t') if 0 <= row_index < len(data_rows) else None
    if not parts:
        return None
    if dt_idx is not None and dt_idx < len(parts):
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(parts[dt_idx], fmt)
            except (ValueError, IndexError):
                pass
    if doy_idx is not None and doy_idx < len(parts):
        try:
            yr = DataIO._file_year(filepath) or 2026
            return datetime(yr, 1, 1) + timedelta(days=float(parts[doy_idx]) - 1.0)
        except (ValueError, IndexError):
            pass
    return None


def ref_row(filepath, row_index, pixel_min=0, pixel_max=None):
    """2026-10-02 이전 _load_alpha_trace_row의 파일 읽기 그대로(이후 처리는 같은 코드)."""
    first_px, t_idx, p_idx, px_start, _wave = DataIO._alpha_layout(filepath)
    data_rows = []
    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith('#') or s.startswith('row_idx'):
                continue
            data_rows.append(s)
    if row_index >= len(data_rows):
        raise RuntimeError("row not found")
    parts = data_rows[row_index].split('\t')
    env_t = float(parts[t_idx]); env_p = float(parts[p_idx])
    alpha_vals = np.array([float(v) for v in parts[first_px:]], dtype=float)
    full_alpha = np.zeros(2048, dtype=float)
    end_px = min(px_start + len(alpha_vals), 2048)
    full_alpha[px_start:end_px] = alpha_vals[:end_px - px_start]
    p_min = int(pixel_min)
    p_max = end_px if pixel_max is None or int(pixel_max) > 2048 else int(pixel_max)
    return np.arange(p_min, p_max), full_alpha[p_min:p_max], env_t, env_p


def _write(d, name, with_dt=True, with_doy=True):
    p = os.path.join(d, name)
    times = ["2026-05-20 00:00:00", "2026-05-20 00:00:20.5", "2026-05-20 00:00:40.1234567",
             "2026-05-20 24:00:00", " 2026-05-20 00:01:00", "garbage", "", "2026-5-20 1:2:3"]
    wave = np.linspace(430, 470, 64)
    cols = ["row_idx"] + (["doy"] if with_doy else []) + (["datetime"] if with_dt else []) + ["T_C", "P_mbar"]
    with open(p, "w", encoding="utf-8") as f:
        f.write("# wavelength_nm:\t" + "\t".join(f"{w:.3f}" for w in wave) + "\n")
        f.write("\t".join(cols + [f"px{900 + i}" for i in range(64)]) + "\n")
        for i in range(40):
            row = [str(i)] + ([f"{140.0 + i / 1000:.6f}"] if with_doy else []) + \
                  ([times[i % len(times)]] if with_dt else []) + ["25.0", "1013.2"]
            row += [repr(float(np.sin(i + k) * 1e-7)) for k in range(64)]
            f.write("\t".join(row) + "\n")
            if i % 9 == 0:
                f.write("# comment line\n\n")
    return p


def main():
    d = tempfile.mkdtemp()
    try:
        files = [_write(d, "260520_a_alpha_trace.dat"), _write(d, "260520_b_alpha_trace.dat", with_doy=False),
                 _write(d, "260520_c_alpha_trace.dat", with_dt=False)]
        n_cmp = 0
        for fp in files:
            for r in range(-1, 42):
                assert DataIO.parse_alpha_row_time(fp, r) == ref_time(fp, r), (os.path.basename(fp), r)
                n_cmp += 1
            for r in range(40):
                for pm in ((0, None), (900, 940), (0, 5000)):
                    a = DataIO._load_alpha_trace_row(fp, r, *pm)
                    b = ref_row(fp, r, *pm)
                    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]), (fp, r, pm)
                    assert a[3] == b[2] and a[4] == b[3], (fp, r, pm)
                    n_cmp += 1
        print(f"test_alpha_row_readers: {n_cmp} comparisons identical to the old implementation")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
