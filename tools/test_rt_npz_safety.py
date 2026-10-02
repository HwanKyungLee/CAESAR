"""R(t) npz must never be silently replaced when the existing one can't be read.

Before: _merge_knots_into_npz / append_rt printed "creating new" on a load error and
saved only this run's knots over the accumulated npz (667 -> 1 knot on a truncated
R_cold copy). Now: RuntimeError, file untouched; saves are atomic and keep a .bak.
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys
import tempfile

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import rt_precompute as RTP  # noqa: E402


def main():
    x = np.arange(5, dtype=float) * 3600.0
    od = np.full((5, 16), 1e-6)
    wv = np.linspace(430.0, 470.0, 16)
    cfg = RTP.RTConfig((430.0, 470.0), 1, 2, 10, 26, 9, "t")
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "R_test.npz")
        RTP.save_rt(p, x, od, wv, label="t", config=cfg, processed_files=["a.dat"])
        assert not os.path.exists(p + ".tmp") and not os.path.exists(p + ".bak")

        # second save keeps the previous version as .bak
        RTP._merge_knots_into_npz(p, x + 5 * 3600.0, od.copy(), wv, cfg, ["b.dat"])
        assert len(RTP.load_rt(p)["knot_sec"]) == 10
        assert len(RTP.load_rt(p + ".bak")["knot_sec"]) == 5

        # truncate the accumulated npz -> merge/append must refuse, not overwrite
        with open(p, "rb") as fh:
            blob = fh.read()
        with open(p, "wb") as fh:
            fh.write(blob[: len(blob) // 2])
        with open(p, "rb") as fh:
            truncated = fh.read()
        for call in (
            lambda: RTP._merge_knots_into_npz(p, x + 99 * 3600.0, od.copy(), wv, cfg, ["c.dat"]),
            lambda: RTP.append_rt(p, td, wv, cfg, file_list=[]),
        ):
            try:
                call()
            except RuntimeError as e:
                assert "not overwriting" in str(e), e
            else:
                raise AssertionError("unreadable npz was not refused")
            with open(p, "rb") as fh:
                assert fh.read() == truncated, "unreadable npz was modified"
        assert len(RTP.load_rt(p + ".bak")["knot_sec"]) == 5   # .bak untouched too
    print("rt npz safety: refuse-on-unreadable + atomic save + .bak OK")


if __name__ == "__main__":
    main()
