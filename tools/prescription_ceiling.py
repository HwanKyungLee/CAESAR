#!/usr/bin/env python
"""§6 처방 천장표 — **제곱합이 아니라 레코드 공간에서** 다시 낸다.

왜 다시 쓰나
------------
기존 천장표는 계열 SD 들을 **제곱합**해 만들었다. 그런데 §4.3 이 바로 그 연산을
금지한다 — 3중 응답은 세 항의 합이 아니고(가법성 잔차가 ΣANs 3중의 29.1 %),
실제로 joint SD 0.1245 대 제곱합 0.1162 로 **7.1 % 어긋난다**.

레코드 공간이면 그 문제가 없다. 빈마다 응답이 다 있으므로 처방을 **빈 단위로
적용한 뒤** SD 를 한 번만 잰다. 분산은 더해지지만 그건 레코드에서 일어나는 일이고,
집계된 robust scale 끼리 더하는 것과는 다르다.

    ×4 블록      : 빈마다 I₀ 항 응답을 1/2 로 (N^−0.5, §10-B 에서 **미검증**)
    R 구간 플래그 : 빈마다 R 항 응답을 rSD 규모로 winsorize (완벽한 플래거 가정)

두 가정 다 **최선의 경우**다. 표는 값이 아니라 **순서**를 위한 것이다.

재현
----
    python tools/prescription_ceiling.py \
        --op  diagnostics/i0_interp_2026-09/production_budget.csv \
        --fix diagnostics/i0_interp_2026-09/production_budget_clockfixed.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from table2 import load, rsd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass


def quad_table(D, pre="s_"):
    """옛 방식 재현 — 집계 SD 의 제곱합. **검증용으로만** 남긴다."""
    sd = {t: float(np.std(D["col"][pre + t], ddof=1)) for t in ("i0", "rt", "ef")}
    rs = rsd(D["col"][pre + "rt"])
    q = lambda i0, rt: float(np.sqrt(i0 ** 2 + rt ** 2 + sd["ef"] ** 2))
    return {"운용": q(sd["i0"], sd["rt"]),
            "블록 ×4": q(sd["i0"] / 2, sd["rt"]),
            "R 플래그": q(sd["i0"], rs),
            "둘 다": q(sd["i0"] / 2, rs)}


def winsorize(v, scale):
    """꼬리를 rSD 규모로 자른다 — '완벽한 플래거' 의 레코드 공간 표현."""
    m = np.median(v)
    return np.clip(v, m - scale, m + scale)


def rec_table(D, pre="s_"):
    """레코드 공간 — 처방을 빈마다 적용한 뒤 SD 를 **한 번** 잰다."""
    tri = D["col"][pre + "tri"]
    i0, rt = D["col"][pre + "i0"], D["col"][pre + "rt"]
    w = winsorize(rt, rsd(rt))
    sd = lambda v: float(np.std(v, ddof=1))
    return {"운용": sd(tri),
            "블록 ×4": sd(tri - 0.5 * i0),
            "R 플래그": sd(tri - rt + w),
            "둘 다": sd(tri - 0.5 * i0 - rt + w)}


def show(lab, D):
    Q, R = quad_table(D), rec_table(D)
    print()
    print("[%s]  n = %d" % (lab, D["ok_n"]))
    print("  joint 3중 SD %.4f 대 제곱합 %.4f — **%.1f %% 차이** (§4.3 이 금지하는 연산)"
          % (R["운용"], Q["운용"], 100 * (R["운용"] / Q["운용"] - 1)))
    print("  %-12s %12s %8s   %12s %8s" % ("", "제곱합(옛)", "배수", "레코드(정본)", "배수"))
    for k in ("운용", "블록 ×4", "R 플래그", "둘 다"):
        print("  %-12s %12.4f %8.2f   %12.4f %8.2f"
              % (k, Q[k], Q[k] / Q["운용"], R[k], R[k] / R["운용"]))
    win = "플래그" if R["R 플래그"] < R["블록 ×4"] else "×4 평균화"
    print("  → 순서: **%s 가 이긴다** (%.3f 대 %.3f)"
          % (win, min(R["R 플래그"], R["블록 ×4"]) / R["운용"],
             max(R["R 플래그"], R["블록 ×4"]) / R["운용"]))
    return R


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--op", required=True)
    ap.add_argument("--fix", required=True)
    a = ap.parse_args()
    for lab, p in (("보정 전 (운영 R)", a.op), ("보정 후 (시계정렬 R)", a.fix)):
        if os.path.exists(p):
            show(lab, load(p))
        else:
            print("  없음: %s" % p)
    print()
    print("  ⚠ 두 처방 다 **가정**이다 — ×4 의 N^−0.5 는 §10-B 가 검증 실패했고")
    print("     (ANs 지수 0.104 · PNs 0.416), 플래거의 재현율·오경보율은 잰 적 없다.")
    print("     그래서 값이 아니라 **순서**만 인용한다.")


if __name__ == "__main__":
    main()
