"""tools/test_alpha_fit_slice.py
AnalysisWorker._alpha_fit_slice must never turn an unusable fit window into a whole-alpha fit
(UX audit 2026-10-02: a 300-350 nm window on a 400-499 nm alpha collapsed to px 0-0 and the
run fitted the full range — DOF 658 -> 2036 — and reported success).
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np


def _worker(**attrs):
    from gui.worker import AnalysisWorker
    w = AnalysisWorker.__new__(AnalysisWorker)     # slice logic only — no engine/thread needed
    for k, v in attrs.items():
        setattr(w, k, v)
    return w


def main():
    wave = np.linspace(400.0, 499.0, 2048)

    sl = _worker(fit_unit='nm', fit_lo_nm=430.0, fit_hi_nm=462.0)._alpha_fit_slice(wave)
    assert isinstance(sl, slice) and 430.0 <= wave[sl][0] and wave[sl][-1] <= 462.0
    print("  PASS  nm window inside the axis slices")

    assert _worker(fit_unit='nm', fit_lo_nm=399.0, fit_hi_nm=500.0)._alpha_fit_slice(wave) is None
    print("  PASS  window covering the whole axis = no slice (unchanged)")

    for lo, hi in ((300.0, 350.0), (440.0, 440.01)):
        try:
            _worker(fit_unit='nm', fit_lo_nm=lo, fit_hi_nm=hi)._alpha_fit_slice(wave)
        except ValueError as e:
            assert "outside" in str(e)
        else:
            raise AssertionError(f"{lo}-{hi} nm must raise, not fall back to the full range")
    print("  PASS  window outside / narrower than the axis raises")

    try:
        _worker(fit_unit='px', pixel_min=900, pixel_max=900)._alpha_fit_slice(wave)
    except ValueError:
        pass
    else:
        raise AssertionError("empty px window must raise")
    assert _worker(fit_unit='px', pixel_min=600, pixel_max=1270)._alpha_fit_slice(wave) == slice(600, 1270)
    print("  PASS  px windows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
