#!/usr/bin/env python
"""tools/settle_average.py — 정착(settling) 스캔 제외 + 시간평균.

CAESAR Pro 핏 결과(.dat)에서
  ① 각 빈(bin)의 첫 N개 '정착 스캔'을 제외하고  (캘 사이클 복귀 직후 캐비티 미충전 →
     농도가 체계적으로 낮게 치우침. 노이즈가 아니라 bias라 평균으로 안 사라짐)
  ② 시계(clock)에 정렬된 M분 구간으로 평균
한 시계열 CSV를 만든다.

데이터 무결성 원칙(filtering-philosophy):
  - 무엇을 왜 얼마나 뺐는지 CSV 헤더에 숫자로 남긴다(과제거율 명시).
  - 평균값만이 아니라 median·std·n을 같이 적어 산점도를 숨기지 않는다.
  - 정착 스캔은 '지우는' 게 아니라 '집계에서 제외'(원본 .dat은 그대로).

사용:
  python tools/settle_average.py <result.dat> [...] [--settle 3] [--avg 60]
                                 [--drop-unstable] [--out DIR]
기본값: --settle 3  --avg 60(분).  빈/스캔#은 'File' 컬럼의 'name [NNNN]'에서 읽는다.
"""
import argparse
import os
import re
import sys
from datetime import datetime, timedelta

import numpy as np


def _read_result(fp):
    """핏 결과 .dat 읽기 → (meta, header[list], rows[list[list[str]]])."""
    meta = {"refs": [], "comments": []}
    header = None
    rows = []
    with open(fp, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if ln.startswith("#"):
                meta["comments"].append(ln.rstrip("\n"))
                m = re.search(r"refs=([A-Za-z0-9_,]+)", ln)
                if m:
                    meta["refs"] = [g for g in m.group(1).split(",") if g]
                continue
            t = ln.rstrip("\n").split("\t")
            if header is None:
                header = t
                continue
            rows.append(t)
    return meta, header, rows


def _gas_list(meta, idx):
    """레퍼런스 가스 목록. 헤더 주석의 refs= 우선, 없으면 {gas}_Error 짝으로 추정."""
    if meta["refs"]:
        return [g for g in meta["refs"] if g in idx]
    return [c[:-6] for c in idx if c.endswith("_Error") and c[:-6] in idx]


def settle_average(fp, settle=3, avg_min=60, drop_unstable=False, out_dir=None):
    meta, header, rows = _read_result(fp)
    idx = {n: i for i, n in enumerate(header)}
    for need in ("File", "Time"):
        if need not in idx:
            raise ValueError(f"{os.path.basename(fp)}: '{need}' 컬럼이 없습니다.")
    gases = _gas_list(meta, idx)
    if not gases:
        raise ValueError(f"{os.path.basename(fp)}: 가스 컬럼을 찾지 못했습니다.")

    n_total = len(rows)
    n_settle = n_unstable = n_badtime = 0
    # 시계 정렬 구간 → {gas: [values]}
    buckets = {}
    win = timedelta(minutes=avg_min)
    epoch = datetime(2000, 1, 1)

    for r in rows:
        # 빈 내 스캔# (정착 판정)
        m = re.search(r"\[(\d+)\]", r[idx["File"]])
        scan_i = int(m.group(1)) if m else -1
        if 0 <= scan_i < settle:
            n_settle += 1
            continue
        if drop_unstable and "Status" in idx and str(r[idx["Status"]]).startswith("Unstable"):
            n_unstable += 1
            continue
        try:
            t = datetime.strptime(r[idx["Time"]], "%Y-%m-%d %H:%M:%S")
        except (ValueError, IndexError):
            n_badtime += 1
            continue
        # 시계 정렬: epoch 기준 win의 정수배로 내림
        k = int((t - epoch) // win)
        wstart = epoch + k * win
        b = buckets.setdefault(wstart, {g: [] for g in gases})
        for g in gases:
            try:
                v = float(r[idx[g]])
            except (ValueError, IndexError):
                continue
            if np.isfinite(v):
                b[g].append(v)

    n_used = n_total - n_settle - n_unstable - n_badtime
    # 출력 경로
    out_dir = out_dir or os.path.dirname(os.path.abspath(fp))
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(fp))[0]
    tag = f"_settle{settle}_avg{avg_min}m" + ("_qc" if drop_unstable else "")
    out_path = os.path.join(out_dir, stem + tag + ".csv")

    cols = ["window_start", "n_used"]
    for g in gases:
        cols += [f"{g}_mean", f"{g}_median", f"{g}_std", f"{g}_n"]

    with open(out_path, "w", encoding="utf-8") as fo:
        fo.write(f"# source: {os.path.basename(fp)}\n")
        fo.write(f"# settle_skip={settle} scans/bin   avg_window={avg_min} min"
                 f"   drop_unstable={drop_unstable}\n")
        fo.write(f"# gases: {','.join(gases)}\n")
        rem = n_total - n_used
        fo.write(f"# scans: total={n_total}  used={n_used}  "
                 f"settling_excluded={n_settle} ({n_settle/max(n_total,1)*100:.1f}%)  "
                 f"unstable_excluded={n_unstable}  bad_time={n_badtime}  "
                 f"=> over-removal {rem/max(n_total,1)*100:.1f}%\n")
        fo.write(f"# windows={len(buckets)}\n")
        fo.write(",".join(cols) + "\n")
        for wstart in sorted(buckets):
            b = buckets[wstart]
            nn = max((len(b[g]) for g in gases), default=0)
            line = [wstart.strftime("%Y-%m-%d %H:%M"), str(nn)]
            for g in gases:
                v = np.array(b[g], dtype=float)
                if v.size:
                    line += [f"{np.mean(v):.6g}", f"{np.median(v):.6g}",
                             f"{np.std(v):.6g}", str(v.size)]
                else:
                    line += ["", "", "", "0"]
            fo.write(",".join(line) + "\n")

    return dict(out=out_path, n_total=n_total, n_used=n_used, n_settle=n_settle,
                n_unstable=n_unstable, n_windows=len(buckets), gases=gases)


def main(argv=None):
    ap = argparse.ArgumentParser(description="정착 스캔 제외 + 시간평균(.dat → .csv)")
    ap.add_argument("files", nargs="+", help="핏 결과 .dat (여러 개 가능)")
    ap.add_argument("--settle", type=int, default=3, help="빈마다 제외할 첫 스캔 수 (기본 3)")
    ap.add_argument("--avg", type=int, default=60, help="평균 구간(분) (기본 60)")
    ap.add_argument("--drop-unstable", action="store_true",
                    help="Status=Unstable 스캔도 제외(보조 QC)")
    ap.add_argument("--out", default=None, help="출력 폴더 (기본: 원본 옆)")
    a = ap.parse_args(argv)

    for fp in a.files:
        if not os.path.isfile(fp):
            print(f"  [skip] not found: {fp}")
            continue
        try:
            r = settle_average(fp, settle=a.settle, avg_min=a.avg,
                               drop_unstable=a.drop_unstable, out_dir=a.out)
        except Exception as e:
            print(f"  [fail] {os.path.basename(fp)}: {e}")
            continue
        rem = r["n_total"] - r["n_used"]
        print(f"  [ok] {os.path.basename(r['out'])}")
        print(f"     total={r['n_total']}  used={r['n_used']}  "
              f"settling-excl={r['n_settle']} ({r['n_settle']/max(r['n_total'],1)*100:.1f}%)"
              + (f"  unstable-excl={r['n_unstable']}" if a.drop_unstable else "")
              + f"  -> over-removal {rem/max(r['n_total'],1)*100:.1f}%")
        print(f"     windows={r['n_windows']}  gases={','.join(r['gases'])}")


if __name__ == "__main__":
    main()
