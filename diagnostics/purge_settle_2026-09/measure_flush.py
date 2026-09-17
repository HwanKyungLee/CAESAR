"""교정(ZA/He) 직후 캐비티 플러시 곡선 실측 — `purge_settle_sec` 의 근거.

무엇을 재나: raw 파일마다 교정 블록이 끝난 행(마지막 비-ambient 행) 이후
1스캔(~0.97초) 단위로 "대기 농도가 몇 %까지 돌아왔나"를 잰다. 피팅을 안 쓰고
재는 방법 —

    OD(row) = -ln(I_row / I_ZA)                      (ZA 블록평균을 I0로)
    고차 다항 제거(3차) 후, 충분히 플러시된 뒤의 OD_ref 에 사영:
    rel(row) = <OD_row, OD_ref> / <OD_ref, OD_ref>   → 1.0 이면 완전 회복

DOAS 피팅·레퍼런스·R 을 하나도 안 거치므로 알파 파이프라인과 독립된 증거다.

실측 결과(2026-09-17, 여수 콜드 `E:\\Yeosu_2026\\CAESAR_Cold\\2026-06\\2026-06-12-0{10..21}.dat`,
12파일 중앙값):

    t after cal(s) :  0-10   10-20   20-30   30-40   40-50   50-60   60+
    rel conc       :  0.21   0.25    0.52    0.71    0.79    0.83    0.85~0.89 (평탄)

→ `AlphaExportWorker(purge_settle_sec=60.0)` 의 근거. 플러시 시간은 유량·셀부피에
달렸으니 **계기·채널·캠페인이 바뀌면 다시 재고 값을 조정할 것**(핫은 미측정 —
결과 쪽 증상은 콜드보다 한 블록 뒤, 더 약하게(0.67) 나타났다).

사용:
    python diagnostics/purge_settle_2026-09/measure_flush.py "E:/Yeosu_2026/CAESAR_Cold/2026-06/2026-06-12-0*.dat"
"""
from __future__ import annotations

import glob
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.raw_parser import RawParser

N_ROWS = 180          # 교정 이후 몇 행까지 볼지 (~175초)
REF_OFFSET = 400      # 이만큼 뒤 60행을 '완전히 플러시된' 기준으로


def _hipass(y, deg=3):
    x = np.linspace(-1, 1, len(y))
    return y - np.polyval(np.polyfit(x, y, deg), x)


def flush_curve(path, px=(300, 1700)):
    """한 파일의 rel(row) 배열(길이 N_ROWS) 또는 None(교정 없음/길이 부족)."""
    p = RawParser(path)
    rows = list(p.iter_rows())
    flags = np.array([r.flag for r in rows])
    if not (flags != 1).any():
        return None
    block = 'NO2' if 'NO2' in p.layout.spec_blocks else next(iter(p.layout.spec_blocks))
    spec = lambda i: p.get_spectrum(i, block)[px[0]:px[1]].astype(float)
    last_cal = int(np.max(np.nonzero(flags != 1)))
    za = [i for i, f in enumerate(flags) if f == 500]
    if len(za) < 5 or last_cal + REF_OFFSET + 60 >= len(rows):
        return None
    i_za = np.mean([spec(i) for i in za], axis=0)
    i_ref = np.mean([spec(i) for i in
                     range(last_cal + REF_OFFSET, last_cal + REF_OFFSET + 60)], axis=0)
    od_ref = _hipass(-np.log(i_ref / i_za))
    out = []
    for k in range(N_ROWS):
        od = _hipass(-np.log(np.clip(spec(last_cal + 1 + k), 1, None) / i_za))
        out.append(float(od @ od_ref / (od_ref @ od_ref)))
    return out


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else None
    if not pattern:
        raise SystemExit(__doc__.splitlines()[-2].strip())
    curves = []
    for path in sorted(glob.glob(pattern)):
        try:
            c = flush_curve(path)
        except Exception as e:                     # 잘린 파일 등은 건너뛴다
            print(f"  skip {os.path.basename(path)}: {e}")
            continue
        if c is None:
            print(f"  skip {os.path.basename(path)}: no calibration block / too short")
            continue
        curves.append(c)
        print(f"  ok   {os.path.basename(path)}")
    if not curves:
        raise SystemExit("ABSTAIN: no usable file matched")
    c = np.array(curves)
    print(f"\n{len(c)} files — rel conc (1.0 = fully flushed), median over files")
    print("  t after cal (s)   rel")
    for b in range(N_ROWS // 10):
        print(f"   {b*10:3d} - {b*10+10:3d}      {np.median(c[:, b*10:(b+1)*10]):5.2f}")


if __name__ == "__main__":
    main()
