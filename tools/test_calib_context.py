# -*- coding: utf-8 -*-
"""tools/test_calib_context.py — per-record calibration context columns (manuscript §6.1, 2026-10-03).

  1) core.calib_context.context: nearest distance, bracketing interval, outside-range flag, NaN rules
  2) alpha generation (committed cold raw fixture) writes the I0 knots it used into the header,
     on the same time axis as the doy column
  3) the fit side reads them back (header first, else the folder's _calknots.json); unknown → NaN

    python tools/test_calib_context.py
"""
import glob
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core.calib_context import SIDECAR, context, knots_for, row_context

_FIX = os.path.join(_ROOT, 'diagnostics', 'alpha_pass2_parallel', 'fixtures')


def test_context():
    dt, gap, edge = context([50, 3650, 9000, 99999, float('nan')], [7200, 0, 3600, 14400])
    assert np.allclose(dt[:3], [50, 50, 1800]) and np.allclose(gap[:3], [1, 1, 2])
    assert edge.tolist() == [False, False, False, True, False]
    assert math.isnan(gap[3]) and math.isnan(dt[4])
    assert math.isnan(context([1.0], [5.0])[0][0])          # one knot: no interval → unknown
    print("  PASS  context(): distance, interval, outside-range, NaN rules")


def test_alpha_header_and_fit_side():
    from PyQt6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication(sys.argv)
    from gui.worker import AlphaExportWorker, AnalysisWorker
    tmp = tempfile.mkdtemp()
    os.environ['AUGUR_ALPHA_CACHE'] = '0'
    try:
        src = sorted(glob.glob(os.path.join(_FIX, 'cold_sample-*.dat')))
        assert len(src) == 2, src
        out = os.path.join(tmp, 'out')
        os.makedirs(out)
        w = AlphaExportWorker(
            file_list=src, pixel_min=0, pixel_max=2048,
            wave_nm=np.loadtxt(os.path.join(_FIX, 'wavecal_cold_sample.txt'), comments='#'),
            flag_za={500}, flag_he={510}, flag_amb={1}, rl_factor=0.9764, cavity_len=100.0,
            output_dir=out, channel=1, avg_sec=60.0, channel_label='ci')
        w.use_parallel = False
        w._run_inner()
        alphas = sorted(glob.glob(os.path.join(out, '**', '*_alpha_trace.dat'), recursive=True))
        assert alphas, "alpha generation produced nothing"
        head = [l for l in open(alphas[0], encoding='utf-8') if l.startswith('#')]
        za_line = [l for l in head if l.startswith('# I0_knot_sec=')]
        assert za_line, "alpha header lacks the I0 knot line"
        k = knots_for(alphas[0])['I0']
        assert len(k) >= 2 and np.all(np.diff(k) > 0)
        # same axis as the doy column: the first record sits between/near the knots, not days away
        from core.data_io import DataIO
        ts = DataIO.parse_alpha_row_time(alphas[0], 0)
        res = {}
        AnalysisWorker._calib_context_cols(res, alphas[0], ts)
        assert 0 <= res['I0_dt_s'] < 6 * 3600, res
        assert math.isnan(res['R_dt_s']) and math.isnan(res['R_edge']), "no R(t) npz → R unknown"
        print(f"  PASS  alpha header carries {len(k)} I0 knots; record 0: I0_dt_s={res['I0_dt_s']:.0f}")

        # an alpha without header knots falls back to the folder sidecar
        bare = os.path.join(tmp, 'bare'); os.makedirs(bare)
        b = os.path.join(bare, os.path.basename(alphas[0]))
        with open(alphas[0], encoding='utf-8') as fi, open(b, 'w', encoding='utf-8') as fo:
            for line in fi:
                if not line.startswith(('# I0_knot_sec=', '# R_knot_sec=')):
                    fo.write(line)
        assert knots_for(b) == {}
        res = {}
        AnalysisWorker._calib_context_cols(res, b, ts)
        assert math.isnan(res['I0_dt_s'])
        with open(os.path.join(bare, SIDECAR), 'w', encoding='utf-8') as fh:
            json.dump({"I0_knot_sec": k.tolist(), "R_knot_sec": [float(k[0]), float(k[-1])]}, fh)
        os.utime(b)                                   # new mtime → fresh cache entry
        res = {}
        AnalysisWorker._calib_context_cols(res, b, ts)
        assert res['I0_dt_s'] == row_context(alphas[0], (ts - datetime(ts.year, 1, 1)).total_seconds())['I0_dt_s']
        assert np.isfinite(res['R_dt_s'])
        print("  PASS  no header knots → NaN; _calknots.json sidecar fills them")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    test_context()
    test_alpha_header_and_fit_side()
    print("test_calib_context: OK")
