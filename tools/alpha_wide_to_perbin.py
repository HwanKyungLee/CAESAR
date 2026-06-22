"""wide 알파(*_alpha_trace.dat) → 박사님 per-bin 형식 변환기.

raw에서 다시 만들지 않고(느림), 이미 생성된 wide 알파의 행들을 박사님 std_t
그리드 bin에 매핑해 per-bin .dat로 쪼개 쓴다(빠름, 초 단위).

출력(생성 경로의 per-bin 출력과 동일 규격):
  {out}/{ch}_{YYYYMMDD}_000000/{ch}_{YYYYMMDD}_{bin:06d}.dat
  - 2048줄 single-column %20.6e, 헤더 없음, 빈 bin = NaN
  - bin 경계 = 박사님 _avg_60s.mat 의 std_t_st/std_t_end (doy, 연초=1)

사용:
  python tools/alpha_wide_to_perbin.py <wide.dat 또는 날짜폴더> --mat <..._avg_60s.mat>
        [--out DIR] [--ch ch1] [--date YYYYMMDD]

주의:
  - wide가 전체 2048px가 아니면(예: px774~1549) 바깥 픽셀은 NaN으로 채워진다.
  - wide 행은 이미 60초 평균이므로, std_t 경계와 위상이 어긋난 행은 가장 가까운
    bin 하나에 들어간다(직접 생성 대비 ≤1 bin 차이 가능).
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

N_PIX = 2048


def read_std_t(mat_path: str) -> np.ndarray:
    """_avg_60s.mat → (N,2) [start_sec, end_sec] (연초기준 초). app_window._read_drnam_std_t와 동일식."""
    import scipy.io as sio
    m = sio.loadmat(mat_path)
    st = np.asarray(m['std_t_st'], dtype=float).flatten()
    en = np.asarray(m['std_t_end'], dtype=float).flatten()
    n = min(len(st), len(en))
    return np.column_stack([(st[:n] - 1.0) * 86400.0, (en[:n] - 1.0) * 86400.0])


def read_wide(path: str):
    """wide 알파 1파일 → (doy_sec 배열, alpha2048 행렬, channel, px_offset)."""
    px_off = None
    channel = None
    idx_doy = None
    alpha_start = None
    n_pix_file = None
    rows_t, rows_a = [], []
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if line.startswith('#'):
                m = re.search(r'#\s*channel=(\d+)', line)
                if m:
                    channel = int(m.group(1))
                continue
            cols = line.rstrip('\n').split('\t')
            if cols and cols[0] == 'row_idx':
                # 컬럼 헤더: row_idx, doy, datetime, T_C, P_mbar, px{N}...
                idx_doy = cols.index('doy')
                for j, c in enumerate(cols):
                    if c.startswith('px'):
                        alpha_start = j
                        px_off = int(c[2:])
                        break
                n_pix_file = len(cols) - alpha_start
                continue
            if alpha_start is None or len(cols) < alpha_start + n_pix_file:
                continue
            try:
                doy = float(cols[idx_doy])
                a = np.array(cols[alpha_start:alpha_start + n_pix_file], dtype=float)
            except ValueError:
                continue
            rows_t.append((doy - 1.0) * 86400.0)   # 박사님 doy(연초=1) → 초
            rows_a.append(a)
    if not rows_a:
        return np.array([]), np.zeros((0, N_PIX)), channel, px_off
    A = np.full((len(rows_a), N_PIX), np.nan)
    A[:, px_off:px_off + n_pix_file] = np.array(rows_a)
    return np.array(rows_t), A, channel, px_off


def convert(files: list[str], mat: str, out_dir: str, chlabel: str | None, date: str | None):
    st = read_std_t(mat)
    nbin = len(st)
    secs_all, alpha_all, channel = [], [], None
    for fp in files:
        t, A, ch, off = read_wide(fp)
        if len(t) == 0:
            print(f'  SKIP {os.path.basename(fp)}: no data rows')
            continue
        channel = channel or ch
        secs_all.append(t)
        alpha_all.append(A)
        print(f'  {os.path.basename(fp)}: {len(t)} rows (px offset {off})')
    if not secs_all:
        raise SystemExit('No rows to convert.')
    secs = np.concatenate(secs_all)
    A = np.vstack(alpha_all)

    if date is None:
        m = re.search(r'(\d{4})-?(\d{2})-?(\d{2})', os.path.basename(files[0]))
        date = (m.group(1) + m.group(2) + m.group(3)) if m else 'unknown'
    ch = chlabel or (f'ch{channel}' if channel else 'ch1')

    # 행 → bin 매핑 후 bin별 nanmean (wide 행은 이미 60s 평균이라 보통 1:1)
    bins = np.searchsorted(st[:, 0], secs, side='right') - 1
    valid = (bins >= 0) & (bins < nbin) & (secs < st[np.clip(bins, 0, nbin - 1), 1])

    folder = os.path.join(out_dir, f'{ch}_{date}_000000')
    os.makedirs(folder, exist_ok=True)
    n_written = 0
    for b in range(nbin):
        sel = valid & (bins == b)
        if np.any(sel):
            alpha = np.nanmean(A[sel], axis=0)
            n_written += 1
        else:
            alpha = np.full(N_PIX, np.nan)
        np.savetxt(os.path.join(folder, f'{ch}_{date}_{b + 1:06d}.dat'),
                   alpha.reshape(-1, 1), fmt='%20.6e')
    print(f'Done: filled {n_written}/{nbin} bins → {folder}')
    return folder


def main():
    p = argparse.ArgumentParser(description='wide alpha → per-bin conversion')
    p.add_argument('inputs', nargs='+', help='wide *_alpha_trace.dat file(s) or date folder')
    p.add_argument('--mat', required=True, help='_avg_60s.mat (std_t grid)')
    p.add_argument('--out', default=None, help='output folder (default: input folder)')
    p.add_argument('--ch', default=None, help="channel label (default: header channel -> 'ch{N}')")
    p.add_argument('--date', default=None, help='YYYYMMDD (default: from filename)')
    args = p.parse_args()

    files = []
    for inp in args.inputs:
        if os.path.isdir(inp):
            files += sorted(glob.glob(os.path.join(inp, '*_alpha_trace.dat')))
        else:
            files.append(inp)
    if not files:
        raise SystemExit('No *_alpha_trace.dat found in inputs.')
    out = args.out or os.path.dirname(os.path.abspath(files[0]))
    convert(files, args.mat, out, args.ch, args.date)


if __name__ == '__main__':
    main()
