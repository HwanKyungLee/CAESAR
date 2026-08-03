"""oculus/find_flags.py — raw .dat에서 flag 분포를 훑고 필요한 구간만 뽑아내는 도구.

왜 필요한가
-----------
raw 한 파일은 1시간 ≈ 3,700 스캔이고 한 줄이 25 KB라 **파일 전체가 ~90 MB**다.
그런데 ZA(500)/He(510) 교정 스캔은 그중 특정 구간에만 나온다. 앞부분 몇 줄을 잘라
올리면 거의 항상 `flag=1`(대기)만 담긴다 — 무작정 많이 긁는 대신 **flag가 바뀌는
지점을 찾아 그 주변만** 뽑아야 한다.

이 도구는 파일을 **스트리밍**하며 flag 열만 읽으므로(전체 행을 파싱하지 않음)
큰 파일도 메모리 부담 없이 훑는다.

사용
----
    # 1) 이 파일에 어떤 flag가 몇 번 나오는지 + 어디서 바뀌는지
    python oculus/find_flags.py "D:/data/2026-06-02-006.dat"

    # 2) 폴더 전체를 훑어 교정 스캔이 든 파일 찾기
    python oculus/find_flags.py "D:/data/CAESAR"

    # 3) flag 전환 지점 주변만 뽑아 작은 파일로 저장(업로드용)
    python oculus/find_flags.py "D:/data/2026-06-02-006.dat" --extract sample.dat

옵션
----
    --extract PATH   전환 지점 주변 행을 PATH에 저장
    --context N      전환 앞뒤로 N행씩 (기본 2)
    --flag-col N     flag 열 인덱스 (기본 4)
    --only 500,510   지정 flag 주변만 추출
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

DEFAULT_FLAG_COL = 4


def iter_flags(path: str, flag_col: int = DEFAULT_FLAG_COL):
    """(행번호, flag)를 스트리밍으로 산출. 행 전체를 파싱하지 않고 flag 열까지만 자른다."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if not line.strip():
                continue
            parts = line.split("\t", flag_col + 1)
            if len(parts) <= flag_col:
                continue
            try:
                yield i, int(parts[flag_col])
            except ValueError:
                continue


def scan_file(path: str, flag_col: int = DEFAULT_FLAG_COL) -> dict:
    """파일 하나의 flag 히스토그램 + 전환 지점."""
    hist: dict = {}
    transitions = []          # [(행번호, 이전flag, 새flag)]
    prev = None
    total = 0
    for i, f in iter_flags(path, flag_col):
        total += 1
        hist[f] = hist.get(f, 0) + 1
        if prev is not None and f != prev:
            transitions.append((i, prev, f))
        prev = f
    return {"path": path, "rows": total, "hist": hist, "transitions": transitions}


def extract_rows(path: str, wanted_rows: set, out_path: str) -> int:
    """지정한 행 번호들만 그대로(원문 그대로) out_path에 저장."""
    n = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh, \
            open(out_path, "w", encoding="utf-8", newline="") as out:
        for i, line in enumerate(fh):
            if i in wanted_rows:
                out.write(line if line.endswith("\n") else line + "\n")
                n += 1
    return n


def rows_around(transitions, context: int, only: set = None) -> set:
    """전환 지점 앞뒤 context행을 모은 행번호 집합."""
    rows = set()
    for i, prev, new in transitions:
        if only and not (prev in only or new in only):
            continue
        for r in range(max(0, i - context), i + context + 1):
            rows.add(r)
    return rows


def _fmt_hist(hist: dict) -> str:
    return "  ".join(f"flag={k}:{v}행" for k, v in sorted(hist.items()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="raw .dat flag 분포 조사 / 구간 추출")
    ap.add_argument("target", help="raw .dat 파일 또는 폴더")
    ap.add_argument("--extract", help="전환 지점 주변 행을 저장할 경로")
    ap.add_argument("--context", type=int, default=2, help="전환 앞뒤 행 수 (기본 2)")
    ap.add_argument("--flag-col", type=int, default=DEFAULT_FLAG_COL)
    ap.add_argument("--only", help="관심 flag 목록 (예: 500,510)")
    args = ap.parse_args(argv)

    only = {int(x) for x in args.only.split(",")} if args.only else None

    if os.path.isdir(args.target):
        files = sorted(glob.glob(os.path.join(args.target, "*.dat")))
        if not files:
            print(f"'{args.target}' 에 .dat 파일이 없습니다.")
            return 1
        print(f"{len(files)}개 파일 조사 중...\n")
        interesting = []
        for p in files:
            r = scan_file(p, args.flag_col)
            others = {k: v for k, v in r["hist"].items() if k != 1}
            mark = "  ★교정스캔 있음" if others else ""
            print(f"  {os.path.basename(p):<40} {r['rows']:>6}행  {_fmt_hist(r['hist'])}{mark}")
            if others:
                interesting.append(p)
        print()
        if interesting:
            print("★ 교정 스캔(ZA/He 등)이 든 파일:")
            for p in interesting:
                print(f"    {p}")
            print("\n이 중 하나를 골라 --extract 로 뽑으세요:")
            print(f'    python oculus/find_flags.py "{interesting[0]}" --extract sample.dat')
        else:
            print("대기 측정(flag=1)만 발견 — 이 폴더엔 교정 스캔이 없습니다.")
        return 0

    if not os.path.isfile(args.target):
        print(f"파일/폴더를 찾을 수 없습니다: {args.target}")
        return 1

    r = scan_file(args.target, args.flag_col)
    print(f"파일: {r['path']}")
    print(f"행 수: {r['rows']}")
    print(f"flag 분포: {_fmt_hist(r['hist']) or '(없음)'}")
    print(f"전환 지점: {len(r['transitions'])}개")
    for i, prev, new in r["transitions"][:20]:
        print(f"    행 {i:>6}: {prev} → {new}")
    if len(r["transitions"]) > 20:
        print(f"    ... 외 {len(r['transitions']) - 20}개")

    if args.extract:
        rows = rows_around(r["transitions"], args.context, only)
        if not rows:
            # 전환이 없으면 앞쪽 몇 행이라도 (구조 확인용)
            rows = set(range(0, min(5, r["rows"])))
            print("\n전환 지점이 없어 앞 5행만 추출합니다.")
        n = extract_rows(args.target, rows, args.extract)
        size = os.path.getsize(args.extract)
        print(f"\n추출 완료: {args.extract}  ({n}행, {size/1024/1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
