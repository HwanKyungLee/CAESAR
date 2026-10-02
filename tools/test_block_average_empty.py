"""gui.worker.block_average — empty-input path must return the same 6-tuple as the normal path.

Hot Yeosu raw has no flag-510 He blocks, so the He call always hits the empty branch.
f700cb1 added a 6th return value (n_settle_dropped) but left the empty branch at 5,
which crashed every hot alpha generation with "expected 6, got 5".
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.worker import block_average  # noqa: E402


def main():
    # empty path: what the AlphaExportWorker caller does, verbatim unpack
    g, sec, spec, t, p, n_drop = block_average([], [], [], [], [])
    assert (g, sec, spec, t, p, n_drop) == ([], [], [], [], [], 0)

    # normal path: two blocks (gap > 10) → two averaged spectra, same tuple length
    gidx = [1, 2, 3, 50, 51]
    out = block_average(gidx, [10., 11., 12., 60., 61.],
                        [np.full(4, v) for v in (1., 2., 3., 5., 7.)],
                        [25.] * 5, [1000.] * 5)
    assert len(out) == 6
    g, sec, spec, t, p, n_drop = out
    assert g == [2.0, 50.5] and sec == [11.0, 60.5]
    assert np.allclose(spec[0], 2.0) and np.allclose(spec[1], 6.0)
    assert n_drop == 0
    print("block_average: empty + normal paths OK")


if __name__ == "__main__":
    main()
