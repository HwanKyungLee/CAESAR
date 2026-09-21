#!/usr/bin/env python
"""raw 에서 **교정 블록 시각만** 뽑는다 (ZA·He knot). 스펙트럼은 안 읽는다.

왜 따로 만드나
--------------
`alpha_context_sidecar.py` 가 I₀ 커버리지를 재려면 캠페인 전체의 ZA knot 시각이
있어야 하는데, 지금 있는 출처는 7일치 진단 캐시뿐이다. 그걸로 전 캠페인을 재면
'범위밖 88 %' 가 나오는데 커버리지가 아니라 **입력 불일치**를 재는 값이다.

전 파싱(`measure_i0_loo.collect`)은 스펙트럼까지 읽어 7일치가 4.7 GB 다. knot
시각만 필요하면 **탭 앞 5칸**이면 된다 — col0·col1 이 bytepack 시각, col4 가
상태 플래그다(`core/raw_parser.py:21`). 한 줄에서 6천 칸을 float 로 바꾸지 않는
것만으로 수십 배 싸다.

시각 규약은 `core.data_io.DataIO` 를 그대로 쓴다 — 단일 출처:
    sec = ((col0<<16) | col1) / 100  +  clock_epoch_offset_sec(파일)
그리고 `doy = sec/86400 + 1` 이므로 사이드카의 `sec=(doy-1)*86400` 와 같은 축이다.

블록 분할은 production 과 같은 규칙이다: **전역 스캔 인덱스 간격 > 10**.
(`gui/worker.py` `_block_average`, `measure_i0_loo._block_average` 와 동일)

검증
----
`--verify <cache.npz>` 를 주면 그 캐시의 `za_sec` 과 대조한다. 7일치
`_cache_hot_PNs_op.npz` 로 확인했다(2026-09-21).

재현
----
    python tools/extract_cal_knots.py \
        --raw "E:/Yeosu_2026/CAESAR_Hot/2026-*/*.dat" \
        --out diagnostics/i0_interp_2026-09/_knots_hot.npz
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.data_io import DataIO
from core.parallel import max_workers

FLAG_ZA, FLAG_HE = 500, 510
GAP = 10          # 전역 스캔 인덱스 간격. production `_block_average` 와 같은 값


def scan_file(path):
    """(n_rows, [(row_idx, flag, sec)…]) — 교정 행만. 스펙트럼은 건드리지 않는다."""
    out, n, off, head = [], 0, None, []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            # ⚠ `clock_epoch_offset_sec(path)` 를 ncols 없이 부르면 **파일을 통째로
            #   로드해서** 폭을 센다(data_io.py:1127). 가벼운 파싱이 무의미해진다.
            #   앞 10줄의 탭 개수로 폭을 직접 세서 넘긴다 — 그쪽 판정식과 같은
            #   `max(len(r) for r in rows[:10])` 이다.
            if off is None:
                head.append(line.count("	") + 1)
                if len(head) >= 10:
                    off = DataIO.clock_epoch_offset_sec(path, ncols=max(head))
            # split(maxsplit=5) — 뒤의 수천 칸은 문자열 하나로 남기고 버린다
            t = line.split("\t", 5)
            if len(t) < 5:
                continue
            i = n
            n += 1
            try:
                f = int(t[4])
            except ValueError:
                continue
            if f not in (FLAG_ZA, FLAG_HE):
                continue
            try:
                sec = (((int(t[0]) << 16) | (int(t[1]) & 0xFFFF)) / 100.0)
            except ValueError:
                continue
            out.append((i, f, sec))
    if off is None:           # 10줄 미만 파일
        off = DataIO.clock_epoch_offset_sec(path, ncols=max(head) if head else 0)
    return n, [(i, f, sec + off) for i, f, sec in out]


def blocks(idx, sec):
    """전역 인덱스로 끊어 (평균시각, 스캔수, span[s])."""
    if not len(idx):
        return [], [], []
    o = np.argsort(idx)
    g, s = np.asarray(idx)[o], np.asarray(sec, float)[o]
    cut = np.where(np.diff(g) > GAP)[0] + 1
    bs = np.split(s, cut)
    return ([float(np.nanmean(b)) for b in bs],
            [float(len(b)) for b in bs],
            [float(np.nanmax(b) - np.nanmin(b)) if len(b) > 1 else 0.0 for b in bs])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", nargs="+", required=True, help="raw .dat glob(들)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--verify", help="이 npz 의 za_sec 과 대조(교집합 구간에서)")
    ap.add_argument("--jobs", type=int, default=0)
    a = ap.parse_args()

    files = sorted({p for g in a.raw for p in glob.glob(g)})
    if not files:
        raise SystemExit(f"ABSTAIN: {a.raw} 에 맞는 파일이 없다")
    print(f"[knots] raw {len(files)} 파일 스캔 중…", flush=True)

    za_i, za_s, he_i, he_s = [], [], [], []
    base = 0
    nw = max(1, min(a.jobs or max_workers(), len(files)))
    # ex.map 은 입력 순서를 보존한다 — 전역 인덱스 배정이 순차와 같다(무회귀)
    with cf.ProcessPoolExecutor(max_workers=nw) as ex:
        for n, rows in ex.map(scan_file, files, chunksize=4):
            for i, f, sec in rows:
                (za_i if f == FLAG_ZA else he_i).append(base + i)
                (za_s if f == FLAG_ZA else he_s).append(sec)
            base += n

    zs, zn, zp = blocks(za_i, za_s)
    hs, hn, hp = blocks(he_i, he_s)
    np.savez_compressed(a.out,
                        za_sec=np.asarray(zs, float), za_nscan=np.asarray(zn, float),
                        za_span_s=np.asarray(zp, float),
                        he_sec=np.asarray(hs, float), he_nscan=np.asarray(hn, float),
                        he_span_s=np.asarray(hp, float))
    d = lambda v: (np.min(v) / 86400.0, np.max(v) / 86400.0) if len(v) else (np.nan,) * 2
    print(f"→ {a.out}")
    for tag, s_, n_ in (("ZA", zs, zn), ("He", hs, hn)):
        lo, hi = d(s_)
        per = np.median(np.diff(np.sort(s_))) / 3600.0 if len(s_) > 1 else np.nan
        print("  %s 블록 %5d · %.2f~%.2f day · 스캔/블록 중앙 %.0f · 주기 중앙 %.2f h"
              % (tag, len(s_), lo, hi, np.median(n_) if len(n_) else np.nan, per))

    if a.verify:
        ref = np.sort(np.asarray(np.load(a.verify)["za_sec"], float))
        got = np.sort(np.asarray(zs, float))
        m = (got >= ref.min() - 1) & (got <= ref.max() + 1)
        sub = got[m]
        print("[검증] %s" % os.path.basename(a.verify))
        print("  캐시 %d knot · 이 추출 %d knot(교집합 구간)" % (len(ref), len(sub)))
        if len(sub) == len(ref):
            print("  최대 시각차 **%.6f s** %s"
                  % (np.max(np.abs(sub - ref)),
                     "— 일치" if np.max(np.abs(sub - ref)) < 1e-6 else "⚠ 불일치"))
        else:
            print("  ⚠ 개수가 다르다 — 블록 분할 규칙이나 파일 목록을 확인하라")


if __name__ == "__main__":
    main()
