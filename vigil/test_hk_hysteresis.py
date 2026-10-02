# -*- coding: utf-8 -*-
"""vigil/test_hk_hysteresis.py — an HK value sitting on a band limit does not flip every scan (2026-10-03).

Before: severity was judged per row with no memory, so a reading jittering around a limit
alternated P2/OK every scan and pushed real alerts out of the 500-entry history (audit V2 §2).

    python vigil/test_hk_hysteresis.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.profile import HKField, SEVERITY_ALARM, SEVERITY_NONE, SEVERITY_WARN


def _walk(f, values):
    prev, out = SEVERITY_NONE, []
    for v in values:
        prev = f.evaluate(v, None, prev)
        out.append(prev)
    return out


def main():
    f = HKField.from_dict({"key": "t", "rel": 0,
                           "alert": {"warn": [20.0, 30.0], "alarm": [10.0, 40.0]}})
    # default margin = 2 % of the warn width = 0.2
    jitter = [30.05, 29.95, 30.05, 29.95, 29.85, 29.7]
    assert _walk(f, jitter) == [SEVERITY_WARN] * 5 + [SEVERITY_NONE], _walk(f, jitter)
    # without memory the same series flips (the old behaviour)
    assert [f.evaluate(v) for v in jitter[:4]] == [SEVERITY_WARN, SEVERITY_NONE] * 2
    # alarm eases to warn only inside the alarm band by 0.6 (2 % of 30), then to OK inside warn by 0.2
    assert _walk(f, [41, 39.5, 39.3, 29.9, 29.7]) == [
        SEVERITY_ALARM, SEVERITY_ALARM, SEVERITY_WARN, SEVERITY_WARN, SEVERITY_NONE]
    # worsening is immediate
    assert f.evaluate(40.1, None, SEVERITY_NONE) == SEVERITY_ALARM
    # explicit margin and one-sided band
    g = HKField.from_dict({"key": "p", "rel": 0, "alert": {"warn": [None, 1000.0], "hysteresis": 5.0}})
    assert _walk(g, [1001, 997, 994]) == [SEVERITY_WARN, SEVERITY_WARN, SEVERITY_NONE]
    print("test_hk_hysteresis: OK")


if __name__ == "__main__":
    main()
