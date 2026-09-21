#!/usr/bin/env python
"""참조 커버리지 표 — **한 번의 실행에서 하나의 표**로 낸다.

왜 한 실행인가
--------------
이 작업에서 "같은 이름, 다른 런, 다른 값" 으로 여섯 번 틀렸다. 커버리지 숫자도
문서마다 기저가 달랐다(옛 본문 "hot 4.1 % · cold 5.0 %, 최악 10.6 h" 는 어떤
양인지 라벨이 확정되지 않았다). 그래서 `범위밖 / 간격>2h / 최악 간격` 을
**같은 정의·같은 실행**으로 계기·창마다 낸다.

정의
----
  범위밖   : 스캔이 knot 시각 범위 **밖** (SegmentedPchip 최근접 상수 = 외삽)
  간격>2h  : 스캔을 감싼 두 knot 의 간격이 2 h 초과 (운용 ZA·R 주기는 1 h)
  최악 간격: 그 창에서 감싼 간격의 최대값

그리고 **범위밖이 왜 생겼는지**를 두 원인으로 가른다.
  파일목록 잘림 : R 생성이 처리한 파일 목록 밖 → 운용/기록 문제, 물리 아님
  품질 기각     : 목록 안인데 R knot 이 없다 → 세 관문이 페어를 떨어뜨렸다
                  (`reflectance_calc` min_valid_fraction · Leff 밴드 ·
                   `AlphaExportWorker` r_cal_valid_min · r_cal_omr_max)

재현
----
    python tools/coverage_table.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(_ROOT, "diagnostics", "i0_interp_2026-09")
SP = os.environ.get("CTX_DIR", os.path.join(
    os.path.expanduser("~"), "AppData", "Local", "Temp", "claude"))
EPOCH = datetime(2026, 1, 1)
DAY = 86400.0

# (라벨, 사이드카 csv, R npz, knot npz, 예산창 [day0, day1] 또는 None)
SETS = [
    ("hot ch1", "ctx_ch1_full.csv", "C:/Doasis_Work/Output/R/R_CH1.npz",
     "_knots_hot.npz", (137.11, 143.60), "예산 창 05-18~24"),
    ("hot ch2", "ctx_ch2_full.csv", "C:/Doasis_Work/Output/R/R_CH2.npz",
     "_knots_hot.npz", (137.11, 143.60), "예산 창 05-18~24"),
    ("cold", "ctx_cold_full.csv", "C:/Doasis_Work/Output/R/R_cold.npz",
     "_knots_cold.npz", (163.0, 168.0), "cold 창 06-10~16"),
]


def fmt(d):
    return (EPOCH + timedelta(days=float(d))).strftime("%m-%d %H:%M")


def load_ctx(path):
    import csv
    R = list(csv.DictReader(open(path, encoding="utf-8")))
    g = lambda n: np.array([float(r[n]) if r[n] not in ("", "nan") else np.nan
                            for r in R])
    return g("sec") / DAY, {t: (g(t + "_edge"), g(t + "_gap_h"), g(t + "_dt_s"))
                            for t in ("I0", "R")}


def row(lab, win, day, cols, mask):
    out = [lab, win, int(mask.sum())]
    for t in ("I0", "R"):
        e, gp, _ = cols[t]
        out += ["%.2f %%" % (100 * e[mask].mean()),
                "%.2f %%" % (100 * np.nanmean(gp[mask] > 2.0)),
                ("%.1f h" % np.nanmax(gp[mask])) if np.isfinite(gp[mask]).any() else "—"]
    return out


def main():
    ctx_dir = sys.argv[1] if len(sys.argv) > 1 else SP
    hdr = ["계기", "창", "n",
           "I0 범위밖", "I0 간격>2h", "I0 최악간격",
           "R 범위밖", "R 간격>2h", "R 최악간격"]
    rows = []
    causes = []
    for lab, csvname, rpath, kname, win, winlab in SETS:
        p = os.path.join(ctx_dir, csvname)
        if not os.path.exists(p):
            print(f"  [{lab}] 사이드카 없음: {p}")
            continue
        day, cols = load_ctx(p)
        rows.append(row(lab, "전 캠페인", day, cols, np.ones(len(day), bool)))
        m = (day >= win[0]) & (day <= win[1])
        if m.sum():
            rows.append(row(lab, winlab, day, cols, m))

        # 범위밖의 원인 분해 — 계기당 한 번이면 된다(ch1·ch2 는 같은 ZA/He)
        if lab == "hot ch2" or lab == "cold":
            r = np.load(rpath, allow_pickle=True)
            k = np.load(os.path.join(DIAG, kname))
            rk = np.sort(np.asarray(r["knot_sec"], float))
            za = np.sort(np.asarray(k["za_sec"], float))
            L = sorted(json.loads(str(r["processed_files_json"])))
            t0 = (datetime.strptime(L[0][:10], "%Y-%m-%d") - EPOCH).total_seconds()
            t1 = (datetime.strptime(L[-1][:10], "%Y-%m-%d") - EPOCH).total_seconds() + DAY
            inw = (za >= t0) & (za < t1)
            miss = np.array([z for z in za[inw]
                             if not len(rk) or np.min(np.abs(rk - z)) > 1800])
            causes.append((lab, len(L), L[0][:10], L[-1][:10], len(za),
                           int((~inw).sum()), len(miss),
                           100 * len(miss) / max(int(inw.sum()), 1), miss))

    w = [max(len(str(r[i])) for r in [hdr] + rows) for i in range(len(hdr))]
    line = lambda r: "| " + " | ".join(str(c).rjust(w[i]) for i, c in enumerate(r)) + " |"
    print("[참조 커버리지] 한 실행 · 같은 정의")
    print(line(hdr))
    print("|" + "|".join("-" * (x + 2) for x in w) + "|")
    for r in rows:
        print(line(r))

    print()
    print("[범위밖의 원인 분해]")
    for lab, nf, d0, d1, nza, ntrunc, nrej, prej, miss in causes:
        print("  %s: 처리 파일 %d (%s ~ %s) · ZA 블록 %d" % (lab, nf, d0, d1, nza))
        print("     파일목록 밖 **%d개**(R 생성이 안 돌았다) · "
              "목록 안 품질기각 **%d개 (%.1f %%)**" % (ntrunc, nrej, prej))
        if len(miss):
            d = np.floor(miss / DAY).astype(int)
            u, c = np.unique(d, return_counts=True)
            o = np.argsort(c)[::-1][:5]
            print("     기각이 몰린 날: " + " · ".join(
                "%s %d" % (fmt(u[i]), c[i]) for i in o))


if __name__ == "__main__":
    main()
