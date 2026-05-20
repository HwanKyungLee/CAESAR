"""
diagnose_flags.py — .dat 파일에서 플래그 위치 및 값을 진단합니다.

사용법:
    python diagnose_flags.py "H:\Yeosu_2026\CAESAR_Cold\2026-05"
    python diagnose_flags.py  (인수 없으면 현재 디렉토리의 *.dat 파일 사용)
"""

import os
import sys
import glob
from collections import Counter

TARGET_FLAGS = {"502", "512", "502.0", "512.0"}

def diagnose(directory):
    files = sorted(glob.glob(os.path.join(directory, "*.dat")))
    if not files:
        files = sorted(glob.glob(os.path.join(directory, "**", "*.dat"), recursive=True))
    if not files:
        print(f"[오류] .dat 파일 없음: {directory}")
        return

    print(f"\n총 {len(files)}개 파일 진단 중...\n")

    # 첫 번째 파일 상세 분석
    fp = files[0]
    print(f"=== 첫 번째 파일 상세 분석: {os.path.basename(fp)} ===")
    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            tokens = line.strip().split("\t")
            n = len(tokens)
            if n < 3:
                continue

            print(f"\n  [라인 {line_no}] 토큰 수: {n}")
            print(f"    tokens[0~5]: {tokens[:6]}")
            print(f"    tokens[-10~]: {tokens[-10:]}")

            # 502/512가 어디에 있는지 탐색
            hits = [(i, tokens[i]) for i in range(min(20, n))
                    if tokens[i].strip() in TARGET_FLAGS]
            if hits:
                print(f"    >>> 502/512 발견 위치: {hits}")
            else:
                print(f"    >>> 앞 20개 토큰에 502/512 없음")
                # 전체 탐색
                all_hits = [(i, tokens[i]) for i in range(n)
                            if tokens[i].strip() in TARGET_FLAGS]
                if all_hits:
                    print(f"    >>> 전체 탐색 결과: {all_hits[:10]}")
                else:
                    print(f"    >>> 파일 전체에 502/512 없음")

            if line_no >= 4:
                print("  (이하 생략)")
                break

    # 전체 파일에서 tokens[4] 기준 플래그 분포
    print(f"\n=== 전체 {len(files)}개 파일 tokens[4] 플래그 분포 ===")
    flag4_counter = Counter()
    for fp in files:
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                tokens = line.strip().split("\t")
                if len(tokens) < 5:
                    continue
                flag4_counter[tokens[4].strip()] += 1

    for val, cnt in flag4_counter.most_common(20):
        mark = " ← ZA(제로에어)" if val == "502" else (" ← He(헬륨)" if val == "512" else "")
        print(f"    tokens[4]='{val}': {cnt}행{mark}")

    # 파일별 ZA/He 포함 여부
    print(f"\n=== 파일별 502(ZA) / 512(He) 포함 현황 ===")
    for fp in files:
        za_cnt = he_cnt = 0
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                tokens = line.strip().split("\t")
                if len(tokens) < 5:
                    continue
                f = tokens[4].strip()
                if f == "502": za_cnt += 1
                elif f == "512": he_cnt += 1
        if za_cnt or he_cnt:
            print(f"  {os.path.basename(fp):30s}  ZA(502)={za_cnt}행  He(512)={he_cnt}행")

if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else "."
    diagnose(directory)
