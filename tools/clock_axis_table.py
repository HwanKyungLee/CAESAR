#!/usr/bin/env python
"""[게이트 0] 알파 시각축 ↔ 제출 병합자료 시각축의 차를 **측정**한다.

왜
--
제출본 `CAESAR_O3_ANs_merged_data_20260831_v4.xlsx` 는 시계 보정 커밋 f897ce8
(2026-09-19) 이전(08-31)에 만들어졌는데도 시각이 옳다. 9 h 는 KST-UTC 와 같은
값이라 "시계 오차"와 "시간대 변환"이 구별되지 않는다. 둘을 가르는 유일한 방법은
알파 레코드 시각과 병합 시각을 **날짜별로 재는 것**이다.

어떻게
------
값이 아니라 **밀도 지문**으로 맞춘다. 5 분 빈마다 들어간 스캔 수는 판본/게인/부호
규약이 달라도 안 변한다(병합 `ans_n_valid` <-> CSV `n_scans` <-> 알파 레코드 수).
값 상관은 ch1-ch2 / ch2-ch1 부호 규약 때문에 음수로 나와 심판이 못 된다.

알파<->병합을 직접 스캔하면 흐릿하다 — 하루 288 빈 중 272 빈이 "꽉 찬 5" 평지라
정수 시간 지연끼리 구별이 안 된다. 그래서 `--bridge-csv` 로 **중간산물을 다리로
두 구간을 따로 잰다**: 알파->CSV 는 +-12 h 탐색(지문이 강해 289/289 급으로 떨어지고),
CSV->병합 은 물리적으로 가능한 두 값(0 h / -9 h)만 채점한다. 완전일치가 나오는 쪽을
채택하고, 결손 빈이 없어 둘 다 완전일치인 날은 '동률'로 표시한 뒤 캠페인 창 요약으로
채운다.

입력
----
* `--old-alpha` : 당시(08-31) 알파 트리  `<날짜>/<스템>_ANs_alpha_trace.dat`
* `--new-alpha` : 현재 알파 트리        `<날짜>/alpha/ch1/<스템>_ANs_alpha_trace.dat`
* `--merged`    : 제출 병합 xlsx (`Data` 시트의 `time` / `ans_n_valid`). **읽기 전용.**

xlsx 는 openpyxl 없이 stdlib zipfile+ElementTree 로 읽는다(저장소 의존성 추가 없음).

예
--
    python tools/clock_axis_table.py \
      --merged "C:/GHL/2026 yeosu/data analysis/CAESAR_O3_ANs_merged_data_20260831_v4.xlsx" \
      --old-alpha "C:/Doasis_Work/Output/alpha/60s/hot/ch1" \
      --new-alpha "C:/Doasis_Work/Output/alpha_purge60/26yeosu"
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import zipfile
from collections import Counter
from xml.etree import ElementTree as ET

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
XL_EPOCH = dt.datetime(1899, 12, 30)

DEFAULT_DATES = ["2026-05-20", "2026-05-23", "2026-05-26", "2026-05-29",
                 "2026-05-30", "2026-06-05", "2026-06-20", "2026-07-05"]


# -- 최소 xlsx 리더 ----------------------------------------------------------
def read_sheet(path, sheet_name="Data"):
    """(헤더 -> 열번호 dict, 행 dict 리스트). 날짜 서식 셀은 datetime 으로 돌려준다."""
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target")
                for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        part = None
        for s in wb.find(NS + "sheets"):
            if s.get("name") == sheet_name:
                t = rels[s.get(RNS + "id")]
                part = t.lstrip("/") if t.startswith("/") else "xl/" + t
        if part is None:
            raise SystemExit("시트 없음: " + sheet_name)
        try:
            sst = ["".join(t.text or "" for t in si.iter(NS + "t"))
                   for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
        except KeyError:
            sst = []
        datefmt = set()
        st = ET.fromstring(z.read("xl/styles.xml"))
        custom = {int(n.get("numFmtId")): n.get("formatCode") for n in st.iter(NS + "numFmt")}
        for i, xf in enumerate(st.find(NS + "cellXfs")):
            fid = int(xf.get("numFmtId", 0))
            code = custom.get(fid, "") or ""
            if 14 <= fid <= 22 or 45 <= fid <= 47 or re.search(r"[ymdhs]", code, re.I):
                datefmt.add(i)

        def colnum(ref):
            n = 0
            for c in re.match(r"([A-Z]+)", ref).group(1):
                n = n * 26 + ord(c) - 64
            return n - 1

        hdr, out = None, []
        with z.open(part) as f:
            for _, el in ET.iterparse(f, events=("end",)):
                if el.tag != NS + "row":
                    continue
                vals = {}
                for c in el.iter(NS + "c"):
                    t, v = c.get("t"), c.find(NS + "v")
                    if t == "inlineStr" or (v is None and c.find(NS + "is") is not None):
                        vals[colnum(c.get("r"))] = "".join(x.text or "" for x in c.iter(NS + "t"))
                        continue
                    if v is None or v.text is None:
                        continue
                    if t == "s":
                        val = sst[int(v.text)]
                    else:
                        val = float(v.text)
                        if int(c.get("s", -1)) in datefmt:
                            val = XL_EPOCH + dt.timedelta(days=val)
                    vals[colnum(c.get("r"))] = val
                el.clear()
                if hdr is None:
                    hdr = vals
                else:
                    out.append(vals)
    return {v: k for k, v in hdr.items()}, out


# -- 알파 시각 읽기 ----------------------------------------------------------
def alpha_times(path):
    """알파 trace 한 파일의 레코드 datetime 리스트(3번째 열)."""
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                continue
            c = line.split("\t", 3)
            if len(c) < 3 or c[0] == "row_idx":
                continue
            try:
                out.append(dt.datetime.strptime(c[2][:19], "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                pass
    return out


def alpha_header(path):
    """헤더에서 clock_epoch / ambient_avg_sec / code 를 뽑는다."""
    got = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith("#"):
                break
            for k in ("clock_epoch", "ambient_avg_sec", "code"):
                m = re.search(r"#\s*" + k + r"=(\S+)", line)
                if m:
                    got.setdefault(k, m.group(1))
    return got


def day_files(root, date, layout):
    """그날 스템(YYYY-MM-DD-NNN)의 알파 파일 경로 목록."""
    d = os.path.join(root, date) if layout == "flat" else os.path.join(root, date, "alpha", "ch1")
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, n) for n in os.listdir(d)
                  if n.endswith("_ANs_alpha_trace.dat"))


# -- 지연 측정 ---------------------------------------------------------------
def bin5(times):
    c = Counter()
    for t in times:
        c[t.replace(minute=t.minute // 5 * 5, second=0, microsecond=0)] += 1
    return c


MODE_N = 5   # 5분 빈에 60s 알파가 꽉 찼을 때의 스캔 수 — 이 평지는 지연을 못 가른다


def best_lag(left, right, span_min=720, step=5, informative=True):
    """`left` 의 5분 카운트를 `right` 에 맞추는 지연(분). (지연, 일치수, 비교수).

    `informative=True` 면 **양쪽 다 꽉 찬 빈(5/5)은 세지 않는다.** 그 평지가 하루의
    95 % 라서 같이 세면 어떤 지연이든 고득점이 되고, 매시 퍼지 주기 때문에 정수 시간
    지연끼리 구별이 안 된다. 결손/부분 빈만 남기면 지연이 하나로 떨어진다.
    커버리지 밖(둘 중 하나라도 관측 구간 밖)은 비교하지 않는다."""
    if not left or not right:
        return (None, -1, 0)
    rlo, rhi = min(right), max(right)
    llo, lhi = min(left), max(left)
    grid = [llo + dt.timedelta(minutes=5 * i)
            for i in range(int((lhi - llo).total_seconds() // 300) + 1)]
    best = (None, -1, 0, -10**9)
    for lag in range(-span_min, span_min + 1, step):
        d = dt.timedelta(minutes=lag)
        hit = tot = 0
        for t in grid:
            u = t + d
            if not (rlo <= u <= rhi):
                continue
            n, m = left.get(t, 0), right.get(u, 0)
            if informative and n == MODE_N and m == MODE_N:
                continue
            tot += 1
            hit += (n == m)
        # 점수 = 일치 − 불일치. 일치수만 보면 겹치는 구간이 넓은 (틀린) 지연이 이기고,
        # 일치율만 보면 20빈짜리 우연이 이긴다. 차이를 쓰면 둘 다 안 걸린다.
        if tot >= 10 and (2 * hit - tot) > best[3]:
            best = (lag, hit, tot, 2 * hit - tot)
    return best[:3]



CAND_LAGS = (0, -540)   # 병합−CSV 로 물리적으로 가능한 값: 그대로(0) / KST 라벨 되돌림(−9 h)


def score_candidates(left, right, lags=CAND_LAGS):
    """두 후보 지연에서 (일치, 비교) — 양쪽 다 값이 있는 빈만 센다."""
    out = {}
    for lag in lags:
        d = dt.timedelta(minutes=lag)
        hit = tot = 0
        for t, n in left.items():
            m = right.get(t + d)
            if m is None:
                continue
            tot += 1
            hit += (m == n)
        out[lag] = (hit, tot)
    return out


def pick(cand, min_tot=20):
    """완전일치(hit==tot)를 채택한다. 둘 다 완전일치면 결손 없는 날이라 못 가른다.

    스캔 수가 하루 내내 5 로 평평한 날은 9 h 를 밀어도 자기 자신과 맞는다 —
    그런 날은 '동률'로 표시하고 캠페인 창 요약에 맡긴다."""
    ok = [l for l, (h, t) in cand.items() if t >= min_tot and h == t]
    if len(ok) == 1:
        return ok[0], "%+.2f h" % (ok[0] / 60.0)
    if len(ok) > 1:
        return None, "동률(무결손일)"
    best = max(cand, key=lambda l: (2 * cand[l][0] - cand[l][1]))
    return best, "%+.2f h (부분)" % (best / 60.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merged", required=True, help="제출 병합 xlsx (읽기 전용)")
    ap.add_argument("--old-alpha", help="당시(08-31) 알파 트리 루트")
    ap.add_argument("--new-alpha", help="현재 알파 트리 루트")
    ap.add_argument("--dates", nargs="*", default=DEFAULT_DATES)
    ap.add_argument("--samples", type=int, default=5, help="날짜당 표에 찍을 레코드 수")
    ap.add_argument("--bridge-csv", help="중간산물 5분 CSV(datetime_KST,n_scans) — "
                                         "알파→CSV→병합 두 구간을 따로 재서 어느 단계가 "
                                         "시각을 옮겼는지 특정한다")
    a = ap.parse_args()

    idx, rows = read_sheet(a.merged)
    merged = {}
    for r in rows:
        t, n = r.get(idx["time"]), r.get(idx["ans_n_valid"])
        if isinstance(t, dt.datetime) and isinstance(n, float):
            merged[t] = int(n)
    print("병합자료: %s   ans_n_valid %d 행   %s ~ %s"
          % (os.path.basename(a.merged), len(merged), min(merged), max(merged)))
    print()

    # 1) 중간산물 다리 — 알파→CSV, CSV→병합 두 구간을 따로 잰다.
    #    직접 알파↔병합 스캔은 하루 95 %가 "꽉 찬 5" 평지라 지연이 흐릿하다.
    #    CSV 의 n_scans 는 알파 스캔 수 그대로라 알파↔CSV 가 289/289 수준으로 떨어지고,
    #    CSV↔병합은 ±1 일 창을 쓰면 캠페인 시작 경계(05-20 12:00)에서도 안 흔들린다.
    bridge, blag = {}, {}
    if a.bridge_csv:
        import csv as _csv
        with open(a.bridge_csv, encoding="utf-8-sig") as f:
            lines = [l for l in f if not l.startswith("#")]
        for r in _csv.DictReader(lines):
            bridge[dt.datetime.strptime(r["datetime_KST"], "%Y-%m-%d %H:%M:%S")] = int(r["n_scans"])
        print("### 중간산물 다리   %s" % os.path.basename(a.bridge_csv))
        print("| 날짜 | CSV − 당시알파 | 일치 | 병합−CSV = 0 h | 병합−CSV = −9 h | "
              "채택 | 합 = 병합 − 당시알파 |")
        print("|---|---|---|---|---|---|---|")
        for date in a.dates:
            fs = day_files(a.old_alpha, date, "flat") if a.old_alpha else []
            if not fs:
                print("| %s | (알파 없음) | - | - | - | - |" % date)
                continue
            l1, h1, t1 = best_lag(bin5(sorted(t for p in fs for t in alpha_times(p))),
                                  bridge, informative=False)
            d0 = dt.datetime.strptime(date, "%Y-%m-%d")
            win = {t: n for t, n in bridge.items()
                   if d0 <= t < d0 + dt.timedelta(days=1)}
            # 지연 탐색 대신 **두 후보를 직접 채점**한다. 이 단계에서 물리적으로 가능한
            # 값은 0 h(그대로 병합) 와 −9 h(KST 라벨을 되돌림) 둘뿐이고, 캠페인 시작
            # 경계(05-20)나 토글 경계(05-29/30) 때문에 창을 넓히거나 좁히면 탐색이
            # 흔들린다. 양쪽 다 값이 있는 빈만 센다(결손을 0으로 채우면 잡음이 된다).
            cand = score_candidates(win, merged)
            l2, note = pick(cand)
            if l1 is not None and l2 is not None:
                blag[date] = l1 + l2
            print("| %s | %s | %d/%d | %d/%d | %d/%d | %s | %s |"
                  % (date,
                     "-" if l1 is None else "%+.2f h" % (l1 / 60.0), h1, t1,
                     cand[0][0], cand[0][1], cand[-540][0], cand[-540][1], note,
                     "-" if date not in blag else "%+.2f h" % (blag[date] / 60.0)))
        print()
        print("에폭 창 요약 (병합 − CSV, 양쪽 다 값 있는 빈만):")
        for lab, lo, hi in (("pre_fix  (~05-29 09:29)", dt.datetime(2026, 1, 1),
                             dt.datetime(2026, 5, 29, 9, 29)),
                            ("post_fix (05-30~)", dt.datetime(2026, 5, 30),
                             dt.datetime(2027, 1, 1))):
            sub = {t: n for t, n in bridge.items() if lo <= t < hi}
            c = score_candidates(sub, merged)
            l, note = pick(c)
            print("  %-26s  0 h: %5d/%-5d   −9 h: %5d/%-5d   → %s"
                  % (lab, c[0][0], c[0][1], c[-540][0], c[-540][1], note))
            # 무결손일이라 하루로는 못 가른 날짜는 이 창의 결론으로 채운다.
            for date in a.dates:
                d0 = dt.datetime.strptime(date, "%Y-%m-%d")
                if date in blag or l is None or not (lo <= d0 + dt.timedelta(hours=12) < hi):
                    continue
                fs = day_files(a.old_alpha, date, "flat") if a.old_alpha else []
                if fs:
                    l1, _, _ = best_lag(bin5(sorted(t for pp in fs for t in alpha_times(pp))),
                                        bridge, informative=False)
                    if l1 is not None:
                        blag[date] = l1 + l
        print()

    # 2) 알파 트리별 표. `병합 time` 은 위에서 잰 지연으로 찍고, 직접 스캔은 교차확인용.
    for label, root, layout in (("당시(08-31) 알파", a.old_alpha, "flat"),
                                ("현재 알파", a.new_alpha, "nested")):
        if not root:
            continue
        print("### %s   %s" % (label, root))
        print("| 날짜 | 알파 datetime | 알파 헤더 clock_epoch | 병합 time | "
              "차 (병합-알파) | 일간 지연 | 직접스캔(교차확인) |")
        print("|---|---|---|---|---|---|---|")
        for date in a.dates:
            fs = day_files(root, date, layout)
            if not fs:
                print("| %s | (알파 없음) | - | - | - | - | - |" % date)
                continue
            epoch = alpha_header(fs[0]).get("clock_epoch", "(헤더에 줄 없음)")
            times = sorted(t for p in fs for t in alpha_times(p))
            dlag, dhit, dtot = best_lag(bin5(times), merged)
            # 당시알파 기준 지연 + (현재알파 − 당시알파) 보정. 트리가 같으면 후자는 0.
            lag = blag.get(date)
            if lag is not None and root != a.old_alpha and a.old_alpha:
                ofs = day_files(a.old_alpha, date, "flat")
                if ofs:
                    o0 = min(t for p in ofs for t in alpha_times(p))
                    shift = round((min(times) - o0).total_seconds() / 300.0) * 5
                    lag -= shift
            if lag is None:
                lag = dlag
            picks = [times[int(len(times) * (i + 0.5) / a.samples)]
                     for i in range(a.samples)] if times else []
            for k, t in enumerate(picks):
                d0 = date if k == 0 else ""
                e0 = epoch if k == 0 else ""
                if lag is None:
                    print("| %s | %s | %s | (지연 미측정) | - | - | - |" % (d0, t, e0))
                    continue
                b = (t.replace(minute=t.minute // 5 * 5, second=0, microsecond=0)
                     + dt.timedelta(minutes=lag))
                print("| %s | %s | %s | %s | %+.2f h | %+.2f h | %s (%d/%d) |"
                      % (d0, t, e0, b, (b - t).total_seconds() / 3600.0, lag / 60.0,
                         "-" if dlag is None else "%+.2f h" % (dlag / 60.0), dhit, dtot))
        print()


if __name__ == "__main__":
    main()
