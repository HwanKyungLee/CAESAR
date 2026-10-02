# -*- coding: utf-8 -*-
"""tools/test_zero_air_loo.py — zero-air LOO rows written by alpha generation (manuscript §7.2, 2026-10-03).

  1) inner blocks only (first/last would be extrapolation), none for < 3 blocks or an index axis
  2) a block identical to its neighbours (true zero, no noise) gives α ≈ 0
  3) a block with extra extinction gives the α the ambient assembly would give
  4) fixed_shift_props: Limit/Center → Fix, links untouched

The fit side is validated against the canonical diagnostics run (155 blocks per hot channel,
ΣANs rSD 0.0748 vs 0.0733 ppb) — that needs the campaign caches, so it is not in CI.

    python tools/test_zero_air_loo.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from core.physics import bbceas_alpha
from gui.worker import _alpha_za_plain, zero_air_loo_rows


def _ctx(npx, omr=1e-6):
    return {"i0_axis_is_sec": True, "ZA_REF": np.full(npx, 1e-8), "rt_omr_pchip": None,
            "rt_omr_const": None, "omr_pchip": None, "omr_axis_is_sec": True,
            "best_omr_d": np.full(npx, omr), "rl_factor": 1.0}


def main():
    npx, nk = 50, 6
    x = np.arange(nk) * 3600.0
    za = np.full((nk, npx), 30000.0)
    t = np.full(nk, 25.0); p = np.full(nk, 1000.0)
    rows = zero_air_loo_rows(_ctx(npx), x, za, t, p, np.arange(nk), x, [])
    assert [r[0] for r in rows] == [1, 2, 3, 4], [r[0] for r in rows]
    assert max(np.max(np.abs(r[4])) for r in rows) < 1e-15, "identical blocks must give alpha 0"
    assert zero_air_loo_rows(_ctx(npx), x[:2], za[:2], t[:2], p[:2], [0, 1], x[:2], []) == []
    ctx = _ctx(npx); ctx["i0_axis_is_sec"] = False
    assert zero_air_loo_rows(ctx, x, za, t, p, np.arange(nk), x, []) == []
    print("  PASS  inner blocks only; true zero → α 0; none for < 3 blocks or index axis")

    za2 = za.copy(); za2[3] *= 0.99                       # 1 % extra extinction in block 3
    rows = {r[0]: r[4] for r in zero_air_loo_rows(_ctx(npx), x, za2, t, p, np.arange(nk), x, [])}
    a_ref = _alpha_za_plain(25.0, 1000.0, np.full(npx, 1e-8))
    want = bbceas_alpha(za2[3], za[0], np.full(npx, 1e-6), a_ref, a_ref, 1.0)
    assert np.allclose(rows[3], want, rtol=1e-9), "same assembly as an ambient row"
    print("  PASS  LOO row = bbceas_alpha(block, I0 from the others, ...)")

    from zero_air_floor import fixed_shift_props
    rp = fixed_shift_props({"NO2": {"sh_mode": "Limit", "sh_val": "-5, 5"},
                            "H2O": {"sh_mode": "Link", "sh_val": "NO2"}}, -6.12)
    assert rp["NO2"] == {"sh_mode": "Fix", "sh_val": "-6.12"} and rp["H2O"]["sh_mode"] == "Link"
    print("  PASS  fixed_shift_props")
    print("test_zero_air_loo: OK")


if __name__ == "__main__":
    main()
