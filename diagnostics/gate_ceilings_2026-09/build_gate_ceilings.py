#!/usr/bin/env python
"""수용 게이트 상한을 **채널차 산출물마다** 만든다.  (읽기 전용 진단)

왜
--
"구조항 추정치는 그것과 같은 상쇄 구조를 갖는 관측량의 변동을 넘을 수 없다" 는
게이트가 지금까지 두 번의 과대추정을 잡았다. 그런데 그 게이트는 **ΣANs 에만** 있다 —
병합자료(`CAESAR_O3_ANs_merged_data_*.xlsx`)에 `ans_ppb` 는 있어도 **ΣPNs 열이 없다**
(137열 확인, PNs 관련 0개). cold 채널은 ΣPNs 의 기준선이므로, cold 에 걸린 항
(저광량 ZA 블록, 긴 R(t) 간격)은 **검정할 수단 자체가 없다.**

그래서 production 핏 결과에서 직접 만든다:

    ΣPNs = NO2(PNs 채널) − NO2(cold)
    ΣANs = NO2(ANs 채널) − NO2(PNs 채널)

**ΣANs 를 같은 방식으로 만들어 병합자료와 대조하는 것이 이 도구의 수용 게이트다.**
그게 맞아야 ΣPNs 도 믿을 수 있다.

상한의 정의(ΣANs 때와 동일)
---------------------------
시간평균 인접차 |Δ| 의 중앙값 → 인접 시각이 독립이라 보면
    sigma_ceiling = median|Δ| / (0.6745 · √2)
관측 인접차에는 **실제 대기 변동이 포함**돼 있으므로 이것은 상한이다.
채널 독립 항이 두 채널에서 같은 크기라면 채널당 상한은 sigma_ceiling/√2.

재현
----
    python diagnostics/gate_ceilings_2026-09/build_gate_ceilings.py \
        --fitdir "C:/Doasis_Work/Output/fitting/new/26yeosu" \
        --merged "C:/GHL/2026 yeosu/data analysis/CAESAR_O3_ANs_merged_data_20260831_v4.xlsx"
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from datetime import datetime

_EPOCH = datetime(1970, 1, 1)

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

BIN_MIN = 5.0          # 병합자료 격자와 같은 5분


def read_result(path, shift_h=0.0):
    """production 결과 .dat → (분 단위 시각 배열, NO2 ppb, NO2_Error, Status)."""
    hdr, t, v, e, st = None, [], [], [], []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            row = line.rstrip("\n").split("\t")
            if hdr is None:
                hdr = row
                try:
                    iT, iN = hdr.index("Time"), hdr.index("NO2")
                except ValueError:
                    return None
                iE = hdr.index("NO2_Error") if "NO2_Error" in hdr else None
                iS = hdr.index("Status") if "Status" in hdr else None
                continue
            try:
                ts = datetime.strptime(row[iT], "%Y-%m-%d %H:%M:%S")
            except (ValueError, IndexError):
                continue
            def _f(i):
                try:
                    return float(row[i])
                except (TypeError, ValueError, IndexError):
                    return np.nan
            # `.timestamp()` 는 naive datetime 을 **로컬시각(KST)** 으로 해석해
            # 엑셀 serial(무시간대) 과 9 h 어긋난다. 고정 기준으로 직접 뺀다.
            t.append((ts - _EPOCH).total_seconds() / 60.0 + shift_h * 60.0)
            v.append(_f(iN))
            e.append(_f(iE) if iE is not None else np.nan)
            st.append(row[iS] if iS is not None and iS < len(row) else "")
    if not t:
        return None
    return np.asarray(t), np.asarray(v), np.asarray(e), np.asarray(st, dtype=object)


def load_channel(fitdir, tag, shift_h=0.0):
    """`*_CH?_<tag>_*.dat` 전부를 이어 붙인다."""
    paths = sorted(glob.glob(os.path.join(fitdir, "*", "fitting", f"*_{tag}_*.dat")))
    T, V, E, S = [], [], [], []
    for p in paths:
        r = read_result(p, shift_h)
        if r is None:
            continue
        T.append(r[0]); V.append(r[1]); E.append(r[2]); S.append(r[3])
    if not T:
        raise SystemExit(f"ABSTAIN: {tag} 결과 .dat 을 못 찾았다 — {fitdir}")
    return (np.concatenate(T), np.concatenate(V), np.concatenate(E),
            np.concatenate(S), len(paths))


def bin5(t, v, e, bin_min=BIN_MIN):
    """5분 격자 평균. 오차는 독립가정 제곱합/n."""
    b = np.floor(t / bin_min).astype(np.int64)
    ok = np.isfinite(v)
    b, v, e = b[ok], v[ok], e[ok]
    ub, inv = np.unique(b, return_inverse=True)
    n = np.bincount(inv)
    m = np.bincount(inv, weights=v) / n
    with np.errstate(invalid="ignore"):
        ee = np.sqrt(np.bincount(inv, weights=np.nan_to_num(e) ** 2)) / n
    return ub * bin_min, m, ee, n


def ceiling(t_min, y, label):
    """시간평균 인접차 → sigma 상한. ΣANs 때와 같은 절차."""
    hh = np.floor(t_min / 60.0).astype(np.int64)
    uh, inv = np.unique(hh, return_inverse=True)
    cnt = np.bincount(inv)
    hm = np.bincount(inv, weights=y) / np.maximum(cnt, 1)
    keep = cnt >= 8
    uh, hm = uh[keep], hm[keep]
    cons = np.diff(uh) == 1
    if cons.sum() < 20:
        print(f"  [{label}] 연속 시간쌍 {int(cons.sum())}개뿐 — 상한을 못 낸다(ABSTAIN)")
        return None
    d = np.abs(np.diff(hm))[cons]
    dn = np.abs(np.diff(y))
    sig = float(np.median(d) / (0.6745 * np.sqrt(2)))
    print(f"  [{label}] n={len(y)} · 중앙 {np.median(y):+.4f} · robustSD "
          f"{1.4826 * np.median(np.abs(y - np.median(y))):.4f}")
    print(f"        {BIN_MIN:.0f}분 인접|Δ| 중앙 {np.median(dn):.4f} · "
          f"시간평균 인접|Δ| 중앙 {np.median(d):.4f} (쌍 {int(cons.sum())})")
    print(f"        → **sigma 상한 {sig:.4f} ppb**, 채널당(등가 기여) {sig / np.sqrt(2):.4f} ppb")
    return sig


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fitdir", required=True, help="production 핏 결과 캠페인 폴더")
    ap.add_argument("--merged", help="병합 xlsx (ΣANs 대조용 — 이게 수용 게이트다)")
    ap.add_argument("--ans-tag", default="ANs")
    ap.add_argument("--pns-tag", default="PNs")
    ap.add_argument("--cold-tag", default="cold")
    ap.add_argument("--time-shift-h", type=float, default=0.0,
                    help="핏 결과 시각에 더할 시간(h). production `.meta.json` 은 "
                         "time_shift_h=0 으로 UTC 인데 병합자료·AQMS 는 KST 라 +9 가 맞다 "
                         "(53일 전부 lag=+9 h 에서 AQMS NO2 와 상관 0.994)")
    ap.add_argument("--out")
    args = ap.parse_args()

    chans = {}
    for name, tag in (("ANs", args.ans_tag), ("PNs", args.pns_tag), ("cold", args.cold_tag)):
        t, v, e, s, npath = load_channel(args.fitdir, tag, args.time_shift_h)
        tb, vb, eb, nb = bin5(t, v, e)
        chans[name] = (tb, vb, eb)
        print(f"[{name}] 파일 {npath}개 · 행 {len(t)} → {BIN_MIN:.0f}분 빈 {len(tb)} · "
              f"NO2 중앙 {np.nanmedian(vb):.4f} ppb")

    def diff(a, b, label):
        ta, va, ea = chans[a]
        tb, vb, eb = chans[b]
        common, ia, ib = np.intersect1d(ta, tb, return_indices=True)
        y = va[ia] - vb[ib]
        u = np.hypot(ea[ia], eb[ib])
        good = np.isfinite(y)
        print(f"\n== {label} = NO2({a}) − NO2({b}) ==  공통 빈 {int(good.sum())}")
        print(f"  보고 불확도(제곱합) 중앙 {np.nanmedian(u[good]):.4f} ppb")
        sig = ceiling(common[good], y[good], label)
        return common[good], y[good], u[good], sig

    t_ans, y_ans, u_ans, sig_ans = diff("ANs", "PNs", "ΣANs")
    t_pns, y_pns, u_pns, sig_pns = diff("PNs", "cold", "ΣPNs")

    if args.merged:
        print("\n== 수용 게이트: 재구성 ΣANs vs 병합자료 ans_ppb ==")
        _compare_merged(args.merged, t_ans, y_ans)

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "gate_ceilings.csv")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("product,n,median_ppb,robustSD_ppb,reported_unc_ppb,"
                 "sigma_ceiling_ppb,per_channel_ceiling_ppb\n")
        for lab, y, u, sig in (("SigmaANs", y_ans, u_ans, sig_ans),
                               ("SigmaPNs", y_pns, u_pns, sig_pns)):
            if sig is None:
                continue
            fh.write(f"{lab},{len(y)},{np.median(y):.6g},"
                     f"{1.4826 * np.median(np.abs(y - np.median(y))):.6g},"
                     f"{np.nanmedian(u):.6g},{sig:.6g},{sig / np.sqrt(2):.6g}\n")
    print(f"\n→ {out}")


def _compare_merged(path, t_min, y):
    """재구성 ΣANs 와 병합 `ans_ppb` 를 같은 시각끼리 대조. 안 맞으면 ΣPNs 도 못 믿는다."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    rows = _read_xlsx(path)
    hdr = {rows[0][k]: k for k in rows[0]}
    for need in ("time", "ans_ppb"):
        if need not in hdr:
            print(f"  병합자료에 '{need}' 열이 없다 — 대조 생략")
            return
    def col(n):
        k = hdr[n]
        out = []
        for r in rows[1:]:
            try:
                out.append(float(r.get(k)))
            except (TypeError, ValueError):
                out.append(np.nan)
        return np.asarray(out)
    # 엑셀 serial(1899-12-30 기준) → 분
    tm = (col("time") - 25569.0) * 1440.0
    am = col("ans_ppb")
    ok = np.isfinite(tm) & np.isfinite(am)
    tm, am = tm[ok], am[ok]
    idx = np.argsort(tm)
    tm, am = tm[idx], am[idx]
    j = np.searchsorted(tm, t_min)
    j = np.clip(j, 0, len(tm) - 1)
    close = np.abs(tm[j] - t_min) <= BIN_MIN
    if close.sum() < 50:
        print(f"  시각이 겹치는 점 {int(close.sum())}개뿐 — 대조 불가"
              f" (재구성 {t_min.min():.0f}~{t_min.max():.0f}분, 병합 {tm.min():.0f}~{tm.max():.0f}분)")
        return
    x, z = am[j][close], y[close]
    print(f"  짝지은 점 {int(close.sum())} · 병합 중앙 {np.median(x):.4f} · "
          f"재구성 중앙 {np.median(z):.4f} · 상관 {np.corrcoef(x, z)[0, 1]:.4f}")
    print(f"  차이 중앙 {np.median(z - x):+.4f} ppb")
    # 상관이 낮으면 시각 정렬부터 의심한다 — ±12 h 를 5분 격자로 훑어 최적 지연을 찾는다.
    if np.corrcoef(x, z)[0, 1] < 0.5:
        best = (None, -2.0, 0)
        for lag in np.arange(-720, 721, BIN_MIN):
            jj = np.clip(np.searchsorted(tm, t_min + lag), 0, len(tm) - 1)
            cc = np.abs(tm[jj] - (t_min + lag)) <= BIN_MIN
            if cc.sum() < 200:
                continue
            r = float(np.corrcoef(am[jj][cc], y[cc])[0, 1])
            if r > best[1]:
                best = (lag, r, int(cc.sum()))
        print(f"  ⚠ 상관이 낮다. ±12 h 지연 스캔 최적: lag {best[0]:+.0f} 분, "
              f"상관 {best[1]:.4f} (n={best[2]})")


def _read_xlsx(path):
    import zipfile
    import xml.etree.ElementTree as ET
    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

    def cidx(ref):
        n = 0
        for ch in re.match(r"([A-Z]+)", ref).group(1):
            n = n * 26 + (ord(ch) - 64)
        return n - 1

    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid = {r.get("Id"): r.get("Target") for r in rels}
        target = None
        for sh in wb.iter(f"{NS}sheets"):
            for s in sh:
                if s.get("name") == "Data":
                    k = [v for a, v in s.attrib.items() if a.endswith("}id")][0]
                    target = rid[k]
        target = target.lstrip("/")
        if target not in z.namelist():
            target = "xl/" + target
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
                shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
        rows = []
        for r in ET.fromstring(z.read(target)).iter(f"{NS}row"):
            vals = {}
            for c in r:
                v = c.find(f"{NS}v")
                if v is None or v.text is None:
                    txt = "".join(x.text or "" for x in c.iter(f"{NS}t"))
                    if txt:
                        vals[cidx(c.get("r"))] = txt
                    continue
                vals[cidx(c.get("r"))] = (shared[int(v.text)] if c.get("t") == "s" else v.text)
            rows.append(vals)
    return rows


if __name__ == "__main__":
    main()
