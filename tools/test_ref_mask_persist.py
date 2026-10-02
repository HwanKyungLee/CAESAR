# -*- coding: utf-8 -*-
"""tools/test_ref_mask_persist.py — a reference mask is part of the ref entry (2026-10-03).

Before: the mask lived only in the live engine — not in the FitSet, not in meta, ignored by
multi-channel runs (config-built engines) and lost on Lock (audit 2026-10-02 F15/s6).
Now `refs[i]["mask"]` is applied by every config-built engine and recorded in meta;
an unmasked config keeps its runid.

    python tools/test_ref_mask_persist.py
"""
from __future__ import annotations

import copy
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np

from core import run_meta
from core.fitset_builder import build_engine


def main():
    d = tempfile.mkdtemp()
    wave = np.linspace(400, 480, 300)
    ref_path = os.path.join(d, "NO2.dat")
    np.savetxt(ref_path, np.column_stack([wave, 1e-19 * (1 + np.sin(wave))]))

    def eng_for(mask):
        r = {"name": "NO2", "path": ref_path, "mult": 19}
        if mask:
            r["mask"] = mask
        return build_engine("", [r], lambda p: wave)[0]

    full = eng_for(None).raw_references["NO2"]
    man = eng_for({"mode": "manual", "range": [50, 120]}).raw_references["NO2"]
    assert np.all(man[:50] == 0) and np.all(man[120:] == 0)
    np.testing.assert_array_equal(man[50:120], full[50:120])
    auto = eng_for({"mode": "auto", "threshold_pct": 50.0}).raw_references["NO2"]
    assert 0 < np.count_nonzero(auto) < np.count_nonzero(full)

    cfg = {"refs": [{"name": "NO2", "path": ref_path, "mult": 19}], "f_min": 1, "f_max": 2}
    kw = dict(channel=1, qc={}, calibration={}, created=None, code_version="x")
    m0 = run_meta.build_meta(copy.deepcopy(cfg), **kw)
    assert "mask" not in m0["species"][0]
    cfg_m = copy.deepcopy(cfg)
    cfg_m["refs"][0]["mask"] = {"mode": "manual", "range": [50, 120]}
    m1 = run_meta.build_meta(cfg_m, **kw)
    assert m1["species"][0]["mask"] == {"mode": "manual", "range": [50, 120]}
    assert m1["runid"] != m0["runid"]
    assert run_meta.build_meta(copy.deepcopy(cfg), **kw)["runid"] == m0["runid"]
    print("test_ref_mask_persist: OK")


if __name__ == "__main__":
    main()
