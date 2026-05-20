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

    # 전체 파일에서 토큰[0~10] 값 분포 집계
    print(f"\n=== 전체 {len(files)}개 파일 토큰[2] 값 분포 ===")
    counter = Counter()
    flag_files = Counter()
    for fp in files:
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                tokens = line.strip().split("\t")
                if len(tokens) < 3:
                    continue
                val = tokens[2].strip()
                counter[val] += 1
                if val in TARGET_FLAGS:
                    flag_files[val] += 1

    print("  tokens[2] 값 → 라인 수 (상위 15개):")
    for val, cnt in counter.most_common(15):
        mark = " ← 플래그!" if val in TARGET_FLAGS else ""
        print(f"    '{val}': {cnt}행{mark}")

    # 다른 위치도 확인 (앞 10개 토큰 전체 스캔)
    print(f"\n=== 전체 파일에서 502/512가 등장하는 토큰 인덱스 분포 ===")
    idx_counter = Counter()
    checked = 0
    for fp in files[:min(10, len(files))]:
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                tokens = line.strip().split("\t")
                for i, t in enumerate(tokens[:30]):
                    if t.strip() in TARGET_FLAGS:
                        idx_counter[i] += 1
        checked += 1

    if idx_counter:
        print(f"  (파일 {checked}개 기준)")
        for idx, cnt in sorted(idx_counter.items()):
            print(f"    tokens[{idx}]: {cnt}번 등장")
    else:
        print(f"  앞 30개 토큰 내에 502/512 없음 (파일 {checked}개 확인)")
        print("\n  >> 502/512가 파일 어느 위치에도 없을 수 있습니다.")
        print("  >> 실제 ZA/He를 구분하는 기준 값이 다를 수 있습니다.")
        print("  >> tokens[2]의 실제 값 목록을 위 분포에서 확인하세요.")

if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else "."
    diagnose(directory)
