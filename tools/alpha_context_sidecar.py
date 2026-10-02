#!/usr/bin/env python
"""알파 트레이스 옆에 **보간 컨텍스트 사이드카**를 낸다 (§6.1 컨텍스트 플래그).

왜 사이드카인가
--------------
최근접 knot 거리·간격·결함은 Pass 1(알파 생성)에서만 아는 값이라, 산출물 열로
내려면 알파 트레이스에 열을 더해야 한다. 그러면 `_is_alpha_input` 판정과 기존
리더가 영향을 받는다 — 그 판정은 이미 감사 미해결 항목이다.

필요 없다. 알파 행의 **시각**과 knot 파일의 시각만 있으면 사후에 조인된다.
그래서 형식을 안 건드리고, **과거에 만든 알파에도 소급 적용**된다(형식을 바꾸면
재생성해야만 얻는다).

무엇을 내나 (행마다)
-------------------
    doy, sec, I0_dt_s, I0_gap_h, I0_edge, R_dt_s, R_gap_h, R_edge

  `*_dt_s`  : 그 스캔에서 **최근접 knot 까지의 시간**(초). 클수록 보간에 기댄다.
  `*_gap_h` : 그 스캔을 감싼 두 knot 의 **간격**(시간). 운용은 ZA 1 h · He 3 h 라
              이 값이 2 h 를 넘으면 knot 이 빠진 구간이다.
  `*_edge`  : 스캔이 knot 범위 **밖**이다(외삽 구간, SegmentedPchip 는 최근접 상수).

모르는 값은 **NaN** 이다 — 0 으로 채우면 "knot 바로 위" 라는 거짓 주장이 된다
(`perr_joint` 와 같은 규약).

재현
----
    python tools/alpha_context_sidecar.py \
        --alpha-dir "C:/Doasis_Work/Output/alpha_purge60/26yeosu/2026-05-18/alpha/ch2" \
        --rt "C:/Doasis_Work/Output/R/R_CH2.npz" \
        --za-npz diagnostics/i0_interp_2026-09/_cache_hot_PNs_op.npz \
        --out alpha_context_ch2.csv

`--za-npz` 를 안 주면 I0_* 열은 전부 NaN 이다(R 열은 그대로 나온다).
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

SEC_PER_DAY = 86400.0


def read_trace_times(path):
    """알파 트레이스에서 행별 doy 를 읽는다. 스펙트럼은 안 읽는다(빠르다)."""
    hdr, doy = None, []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            t = line.rstrip("\n").split("\t")
            if t and t[0] == "row_idx":
                hdr = t
                continue
            if hdr and len(t) > 1:
                try:
                    doy.append(float(t[hdr.index("doy")]))
                except (ValueError, IndexError):
                    doy.append(np.nan)
    return np.asarray(doy, float)


# single source: the fit writes the same columns per record (core.calib_context)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from core.calib_context import SIDECAR, context  # noqa: E402


def write_knot_sidecars(dirs, za, rk, sources):
    """`_calknots.json` in each alpha folder — the fit reads it for alphas whose header has no
    knot lines (made before 2026-10-03). ⚠ I0 knots from raw (extract_cal_knots) are *all* ZA
    blocks; alpha generation may have dropped a few (short or low-light blocks)."""
    import json
    from core.provenance import code_version
    for d in dirs:
        with open(os.path.join(d, SIDECAR), "w", encoding="utf-8") as fh:
            json.dump({"I0_knot_sec": [] if za is None else [float(v) for v in np.sort(za)],
                       "R_knot_sec": [] if rk is None else [float(v) for v in np.sort(rk)],
                       "source": sources, "code": code_version(),
                       "note": "axis: seconds from the start of the year (= (doy-1)*86400)"},
                      fh, indent=0)
        print(f"→ {os.path.join(d, SIDECAR)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alpha-dir", required=True, nargs="+",
                    help="알파 폴더(들). 여러 개 또는 glob 가능 — 캠페인 전체를 한 번에")
    ap.add_argument("--rt", help="R(t) npz (knot_sec)")
    ap.add_argument("--za-npz", help="ZA knot 시각을 가진 npz (za_sec). 없으면 I0_* 는 NaN")
    ap.add_argument("--year-start-doy", type=float, default=1.0,
                    help="doy 규약. 1.0 이면 sec=(doy-1)*86400 (연초 = doy 1)")
    ap.add_argument("--out", help="CSV of the context per row (optional with --write-knots)")
    ap.add_argument("--write-knots", action="store_true",
                    help="also write _calknots.json into every alpha folder (the fit then exports "
                         "the context columns for these older alphas)")
    a = ap.parse_args()

    paths = []
    for d in a.alpha_dir:
        for dd in (sorted(glob.glob(d)) or [d]):
            paths += glob.glob(os.path.join(dd, "*alpha_trace.dat"))
    paths = sorted(set(paths))
    if not paths:
        raise SystemExit(f"ABSTAIN: {a.alpha_dir} 에 *alpha_trace.dat 이 없다")

    if not a.out and not a.write_knots:
        raise SystemExit("give --out and/or --write-knots")
    za = None
    if a.za_npz:
        z = np.load(a.za_npz)
        if "za_sec" not in z.files:
            raise SystemExit(f"ABSTAIN: {a.za_npz} 에 za_sec 이 없다")
        za = np.asarray(z["za_sec"], float)
    rk = None
    if a.rt:
        r = np.load(a.rt, allow_pickle=True)
        rk = np.asarray(r["knot_sec"], float)

    if a.write_knots:
        write_knot_sidecars(sorted({os.path.dirname(p) for p in paths}), za, rk,
                            {"za_npz": a.za_npz, "rt": a.rt})
    if not a.out:
        return
    rows = 0
    _span = [np.inf, -np.inf]
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("file,row,doy,sec,I0_dt_s,I0_gap_h,I0_edge,R_dt_s,R_gap_h,R_edge\n")
        for p in paths:
            doy = read_trace_times(p)
            if not len(doy):
                continue
            sec = (doy - a.year_start_doy) * SEC_PER_DAY
            i_dt, i_gap, i_ed = context(sec, za)
            r_dt, r_gap, r_ed = context(sec, rk)
            b = os.path.basename(p)
            for j in range(len(sec)):
                fh.write("%s,%d,%.6f,%.3f,%.6g,%.6g,%d,%.6g,%.6g,%d\n"
                         % (b, j, doy[j], sec[j], i_dt[j], i_gap[j], int(i_ed[j]),
                            r_dt[j], r_gap[j], int(r_ed[j])))
            rows += len(sec)
            _span[0] = min(_span[0], float(np.nanmin(sec)))
            _span[1] = max(_span[1], float(np.nanmax(sec)))

    print(f"→ {a.out}  ({rows} rows, {len(paths)} files)")
    # ⚠ knot 출처가 알파 구간을 **안 덮으면** '범위밖' 이 그 사실만 재게 된다.
    #   실측으로 한 번 당했다(7일치 ZA 캐시로 전 캠페인 알파를 재서 I0 범위밖
    #   88.1 % — 커버리지 결함이 아니라 입력 불일치였다). 그래서 먼저 경고한다.
    lo, hi = _span[0], _span[1]
    for tag, k in (("I0", za), ("R", rk)):
        if k is None or not len(k):
            continue
        if k.min() > lo + 3600 or k.max() < hi - 3600:
            print("  ⚠ [%s] knot 구간(%.2f~%.2f day)이 알파 구간(%.2f~%.2f day)을 "
                  "안 덮는다 — '범위밖' 은 커버리지가 아니라 **입력 불일치**를 잰다."
                  % (tag, k.min() / SEC_PER_DAY, k.max() / SEC_PER_DAY,
                     lo / SEC_PER_DAY, hi / SEC_PER_DAY))
    # 한 줄 요약 — 커버리지 문제가 있으면 여기서 바로 보인다
    import csv as _csv
    R = list(_csv.DictReader(open(a.out, encoding="utf-8")))
    for tag in ("I0", "R"):
        g = np.array([float(x[tag + "_gap_h"]) if x[tag + "_gap_h"] not in ("", "nan")
                      else np.nan for x in R])
        d = np.array([float(x[tag + "_dt_s"]) if x[tag + "_dt_s"] not in ("", "nan")
                      else np.nan for x in R])
        e = np.array([int(x[tag + "_edge"]) for x in R])
        if not np.isfinite(g).any():
            print(f"  [{tag}] knot 시각이 없어 판정 안 함 (NaN)")
            continue
        print("  [%s] 최근접 knot 중앙 %.0f s · p99 %.0f s · 간격 중앙 %.2f h · "
              "간격>2h 인 행 %.1f %% · 범위밖 %.1f %%"
              % (tag, np.nanmedian(d), np.nanpercentile(d, 99), np.nanmedian(g),
                 100 * np.nanmean(g > 2.0), 100 * e.mean()))


if __name__ == "__main__":
    main()
