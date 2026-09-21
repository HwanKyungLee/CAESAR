#!/usr/bin/env python
"""운영 R npz 의 knot 시각을 5/29 핫 시계 보정 축으로 옮긴 **새 파일**을 만든다.

왜 재생성이 아니라 라벨 이동인가
--------------------------------
`rt_precompute` 의 knot 시각은 `_file_first_sec(path)` — **파일 첫 스캔 시각**이고,
그 함수가 지금은 `DataIO.clock_epoch_offset_sec` 를 더한다. 반사도 값 `omr_d` 는
파일 내용에서 나오므로 **시계 보정과 무관**하다. 따라서 같은 파일 목록으로
재생성하면 바뀌는 것은 `knot_sec` 라벨뿐이고, 그 변화량은 정확히
`clock_epoch_offset_sec` 다. 라벨을 옮기는 것이 재생성과 **동일**하다.

(파일 목록을 넓히는 것 — 07-10~11 추가 — 은 별개 문제다. `rt_precompute.append_rt`.)

운영 파일은 **덮지 않는다.** 하류 알파와 모든 결과가 바뀐다.

재현
----
    python tools/rt_clockfix.py --in "C:/Doasis_Work/Output/R/R_CH2.npz" \
        --out diagnostics/i0_interp_2026-09/R_CH2_clockfixed.npz
"""
from __future__ import annotations

import argparse
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
for _p in (_ROOT, os.path.join(_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.data_io import DataIO

EPOCH = datetime(2026, 1, 1)


def _stem_window_secs():
    """보정 대상 스템 구간을 초로. `DataIO` 의 상수를 단일 출처로 쓴다."""
    a = DataIO.HOT_DEPLOY_STEM[:10]
    b = DataIO.HOT_UTC_TOGGLE_STEM[:10]
    t0 = (datetime.strptime(a, "%Y-%m-%d") - EPOCH).total_seconds()
    t1 = (datetime.strptime(b, "%Y-%m-%d") - EPOCH).total_seconds() + 86400
    return t0, t1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if os.path.abspath(a.src) == os.path.abspath(a.out):
        raise SystemExit("ABSTAIN: 운영 파일을 덮으려 한다 — 새 경로를 줘라")

    z = np.load(a.src, allow_pickle=True)
    d = {k: z[k] for k in z.files}
    ks = np.asarray(d["knot_sec"], float)
    t0, t1 = _stem_window_secs()
    off = DataIO.HOT_PRE_TOGGLE_SHIFT_SEC
    hit = (ks >= t0) & (ks < t1)
    if not hit.any():
        print("  보정창 안 knot 이 없다 — 그대로 복사한다(cold 등)")
    new = np.where(hit, ks + off, ks)

    o = np.argsort(new)
    new, od = new[o], np.asarray(d["omr_d"], float)[o]
    uniq = np.concatenate(([True], np.diff(new) > 0))   # PCHIP 단조 x
    d["knot_sec"], d["omr_d"] = new[uniq], od[uniq]
    # 무엇을 했는지 파일 안에 남긴다 — 나중에 "이게 뭐였지" 를 막는다
    d["clockfix_note"] = np.array(json.dumps({
        "source": os.path.basename(a.src), "shifted_knots": int(hit.sum()),
        "offset_sec": float(off), "window": [DataIO.HOT_DEPLOY_STEM,
                                             DataIO.HOT_UTC_TOGGLE_STEM],
        "why": "R npz predates f897ce8 (2026-09-19) hot 5/29 clock fix"}))
    np.savez_compressed(a.out, **d)

    f = lambda s: (EPOCH + timedelta(seconds=float(s))).strftime("%m-%d %H:%M")
    print(f"→ {a.out}")
    print("  knot %d개 중 **%d개**를 %+.0f h 이동 · 중복 제거 %d"
          % (len(ks), int(hit.sum()), off / 3600, len(new) - int(uniq.sum())))
    print("  첫 knot %s → %s · 마지막 %s → %s"
          % (f(np.sort(ks)[0]), f(d["knot_sec"][0]),
             f(np.sort(ks)[-1]), f(d["knot_sec"][-1])))


if __name__ == "__main__":
    main()
