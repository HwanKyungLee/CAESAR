"""
read_raw.py  —  CAESAR 로우파일 리더 (기초 확인용)

사용법:
    python read_raw.py "H:\Yeosu_2026\CAESAR_Cold\2026-05"
"""

import os
import sys
import glob
import numpy as np

# ── 설정 ──────────────────────────────────────────────────────────
FLAG_ZA    = (500, 501, 502, 503)
FLAG_HE    = (510, 511, 512, 513)
ROI2_START = 2053   # 스펙트럼 픽셀 시작 인덱스 (0-based)
ROI2_END   = 4101   # 스펙트럼 픽셀 끝 인덱스 (exclusive)
PRESS_IDX  = 6156
TEMP_IDX   = 6157
# ──────────────────────────────────────────────────────────────────


def read_file(filepath):
    """
    .dat 파일 한 개를 읽어 ZA/He 스캔 목록을 반환한다.

    반환값: (za_scans, he_scans)
        각 항목은 dict:
            {
              'spectrum':   np.ndarray (2048,),
              'temp_c':     float,
              'press_mbar': float,
              'flag':       int,
              'line_no':    int,
            }
    """
    za_scans, he_scans = [], []

    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            tokens = line.rstrip("\n").split("\t")

            if len(tokens) < ROI2_END:
                continue

            try:
                flag = int(tokens[4])
            except (ValueError, IndexError):
                continue

            if flag not in FLAG_ZA and flag not in FLAG_HE:
                continue

            try:
                spectrum = np.array(tokens[ROI2_START:ROI2_END], dtype=float)
            except ValueError:
                continue

            try:
                p_raw = float(tokens[PRESS_IDX])
                t_raw = float(tokens[TEMP_IDX])
                press_mbar = p_raw * (0.01 * 6894.73326 / 100.0) if p_raw not in (0.0, 65535.0) else 1013.25
                temp_c     = t_raw / 100.0                        if t_raw not in (0.0, 65535.0) else 25.0
            except (ValueError, IndexError):
                press_mbar, temp_c = 1013.25, 25.0

            scan = {
                "spectrum":   spectrum,
                "temp_c":     temp_c,
                "press_mbar": press_mbar,
                "flag":       flag,
                "line_no":    line_no,
            }

            if flag in FLAG_ZA:
                za_scans.append(scan)
            else:
                he_scans.append(scan)

    return za_scans, he_scans


def summarize_directory(directory):
    files = sorted(glob.glob(os.path.join(directory, "*.dat")))
    if not files:
        print(f"[오류] .dat 파일 없음: {directory}")
        return

    print(f"\n디렉토리: {directory}")
    print(f"파일 수 : {len(files)}개\n")

    for fp in files:
        za, he = read_file(fp)
        fname  = os.path.basename(fp)

        first  = za + he
        n_pix  = len(first[0]["spectrum"]) if first else 0
        t_str  = f"{first[0]['temp_c']:.1f}"    if first else "-"
        p_str  = f"{first[0]['press_mbar']:.1f}" if first else "-"

        za_flags = {}
        for s in za:
            za_flags[s["flag"]] = za_flags.get(s["flag"], 0) + 1
        he_flags = {}
        for s in he:
            he_flags[s["flag"]] = he_flags.get(s["flag"], 0) + 1

        za_detail = " ".join(f"{k}:{v}" for k, v in sorted(za_flags.items()))
        he_detail = " ".join(f"{k}:{v}" for k, v in sorted(he_flags.items()))

        print(f"  {fname}  ZA {len(za):3d} [{za_detail}]  He {len(he):3d} [{he_detail}]  {n_pix}px  {t_str}°C  {p_str}mbar")


if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else "."
    summarize_directory(directory)
