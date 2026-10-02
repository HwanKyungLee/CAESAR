# -*- coding: utf-8 -*-
"""tools/test_qc_backup_columns.py — saved .dat keeps pre-QC values as plain columns (2026-10-03).

Before: `_qc_orig*` dicts went to the file as `{'NO2': np.float64(...)}` repr strings, so an
excluded row's original concentration could not be read back (charter ①).

    python tools/test_qc_backup_columns.py
"""
from __future__ import annotations

import io
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from core.result_io import flatten_qc_backup


def main():
    nan = float('nan')
    rows = [
        {'File': 'a', 'NO2': 1.5, 'Status': 'OK',
         '_qc_orig': {'NO2': np.float64(1.5)}, '_qc_orig_sm': {'NO2': 1.4}, '_qc_orig_status': 'OK'},
        {'File': 'b', 'NO2': nan, 'Status': 'QC-Auto (rms=2e-8>1e-8)',
         '_qc_orig': {'NO2': np.float64(7.25)}, '_qc_orig_sm': {'NO2': 7.0}, '_qc_orig_status': 'Unstable'},
        {'File': 'c', 'NO2': 3.0, 'Status': 'OK'},            # row without backup
    ]
    out = flatten_qc_backup(pd.DataFrame(rows))
    assert not any(c.startswith('_qc_orig') for c in out.columns), out.columns
    buf = io.StringIO()
    out.to_csv(buf, sep='\t', index=False)
    back = pd.read_csv(io.StringIO(buf.getvalue()), sep='\t')
    assert back['NO2_preQC'].tolist() == [1.5, 7.25, 3.0], back['NO2_preQC'].tolist()
    assert math.isnan(back['NO2'][1])                          # exclusion itself unchanged
    assert back['Status_preQC'].tolist() == ['OK', 'Unstable', 'OK']
    assert 'np.float64' not in buf.getvalue()
    # no QC ran -> nothing added
    plain = flatten_qc_backup(pd.DataFrame([{'NO2': 1.0, 'Status': 'OK'}]))
    assert list(plain.columns) == ['NO2', 'Status']
    print("test_qc_backup_columns: OK")


if __name__ == '__main__':
    main()
