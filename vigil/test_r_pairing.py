# -*- coding: utf-8 -*-
"""vigil/test_r_pairing.py — R pairs each He window with its adjacent ZA, not last hour's (2026-10-03).

Yeosu raw order per calibration: he_wait_before(512) → he_inject(510) → he_wait_after(513) →
za_inject(500); ZA hourly, He every 3 h. The old "latest of each" pairing computed R the moment
He finished, with the ZA from an hour earlier (audit 2026-10-02 V2 §4).

    python vigil/test_r_pairing.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from vigil.alert_engine import OK
from vigil.monitors.r_monitor import RMonitor


def _run(order_he_first=True):
    rm = RMonitor(wave_nm=None)
    pairs = []
    rm._compute = lambda: (pairs.append((rm._last_he[0][0], rm._last_za[0][0])), (OK, "", {}))[1]

    def feed(role, n, val):
        for _ in range(n):
            rm.observe(role, np.full(4, float(val)), 25.0, 1013.0)

    for hour in range(9):
        feed("sampling", 3000, 0)
        he = hour % 3 == 0
        if he and order_he_first:
            feed("he_wait_before", 30, 0); feed("he_inject", 60, 1000 + hour); feed("he_wait_after", 30, 0)
        feed("za_inject", 60, hour)
        if he and not order_he_first:
            feed("he_wait_before", 30, 0); feed("he_inject", 60, 1000 + hour); feed("he_wait_after", 30, 0)
    feed("sampling", 10, 0)
    return pairs


def main():
    for he_first in (True, False):
        pairs = _run(he_first)
        assert pairs == [(1000.0 + h, float(h)) for h in (0, 3, 6)], (he_first, pairs)
    print("test_r_pairing: OK (He paired with its adjacent ZA, both orders)")


if __name__ == "__main__":
    main()
