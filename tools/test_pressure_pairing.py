"""tools/test_pressure_pairing.py — 핫 채널 압력 센서가 **채널 정체로** 짝지어지는지 (2026-09-27).

여수 캠페인: P_ANs(6164) = 300 °C 경로 = primary(block 2053, 'ANs'),
             P_PNs(6162) = 180 °C 경로 = secondary(block 4101, 'PNs').
예전 data_io 는 슬롯 1 ← P_PNs, 슬롯 2 ← P_ANs 로 반대였다.
기간(date_range) 밖 파일(9/27 이후 실험실, block 4101 = 300 °C 셀)은 예전 슬롯 규칙을 유지한다.

    python tools/test_pressure_pairing.py
"""
from __future__ import annotations

import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.data_io import DataIO
from core.raw_parser import P_SCALE

_FAIL = []


def check(name, cond, extra=""):
    print(("  PASS  %s" % name) if cond else ("  FAIL  %s  %s" % (name, extra)))
    if not cond:
        _FAIL.append(name)


def _row(d, name, p_pns=965.0, p_ans=920.0):
    v = ["0"] * 6181
    v[0], v[1], v[2], v[3], v[4] = "18125", "43986", "900", "-1000", "1"
    for i in range(2053, 6149):
        v[i] = "50000"
    v[6162] = str(int(round(p_pns / P_SCALE)))
    v[6164] = str(int(round(p_ans / P_SCALE)))
    v[6174] = "3000"
    v[6155] = "7500"
    fp = os.path.join(d, name)
    with open(fp, "w", encoding="utf-8") as fh:
        fh.write("\t".join(v) + "\n")
    return fp


def main():
    with tempfile.TemporaryDirectory() as d:
        print("[1] 캠페인 파일: 슬롯 1(ANs) ← P_ANs, 슬롯 2(PNs) ← P_PNs")
        fp = _row(d, "2026-05-20-010.dat")
        p1 = DataIO.load_measurement_with_hk(fp, row_index=0, channel=1)[4]
        p2 = DataIO.load_measurement_with_hk(fp, row_index=0, channel=2)[4]
        check("block 2053 = ANs → 6164 (920)", abs(p1 - 920.0) < 1.0, p1)
        check("block 4101 = PNs → 6162 (965)", abs(p2 - 965.0) < 1.0, p2)
        print("[2] 8/11 실험실(같은 배치)도 캠페인 규칙")
        fp = _row(d, "2026-08-11-003.dat")
        check("8/11 슬롯 1 → 6164", abs(DataIO.load_measurement_with_hk(fp, row_index=0, channel=1)[4] - 920.0) < 1.0)
        print("[3] 기간 밖(9/27 실험실): 예전 슬롯 규칙 — 슬롯 2(300 °C 셀) ← P_ANs")
        fp = _row(d, "2026-09-27-001.dat")
        q1 = DataIO.load_measurement_with_hk(fp, row_index=0, channel=1)[4]
        q2 = DataIO.load_measurement_with_hk(fp, row_index=0, channel=2)[4]
        check("9/27 슬롯 1 → 6162", abs(q1 - 965.0) < 1.0, q1)
        check("9/27 슬롯 2 → 6164", abs(q2 - 920.0) < 1.0, q2)
        print("[4] 이름 없는 파일명(날짜 없음)은 제한 없이 캠페인 이름 적용")
        fp = _row(d, "synthetic.dat")
        check("날짜 없음 슬롯 1 → 6164", abs(DataIO.load_measurement_with_hk(fp, row_index=0, channel=1)[4] - 920.0) < 1.0)
    print("\npressure pairing tests: %s" % ("OK" if not _FAIL else "FAIL %s" % _FAIL))
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
