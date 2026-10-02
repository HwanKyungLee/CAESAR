# -*- coding: utf-8 -*-
"""tools/test_replay_poly_panel.py — replay hands the Monitor the same quantities as a live run.

Live (worker plot_update): Meas = signal − poly − etalon, Fit = model − poly − etalon, poly.
Replay used to pass α and the full model, so the Polynomial panel (dots = Meas + poly) showed
α + poly: the baseline added twice (audit 2026-10-02 s3 R5).

    python tools/test_replay_poly_panel.py
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np

import gui.app_window_save as save_mod
from gui.app_window_save import SaveExportMixin


def main():
    px = np.arange(100, 200, dtype=float)
    poly = 1e-7 + 1e-10 * px
    etalon = 2e-9 * np.sin(0.3 * px)
    absorb = 5e-9 * np.exp(-((px - 150) / 10) ** 2)
    alpha = poly + etalon + absorb + 1e-11          # measured = model + tiny residual

    class Engine:
        def get_model_components(self, pixel_idx, **_):
            return poly + absorb + etalon, absorb, poly, etalon, np.zeros_like(px)

    got = {}

    class Monitor:
        engine = None
        _view_channel = 1
        tabs = SimpleNamespace(setCurrentIndex=lambda i: None)

        def update_spectrum(self, pixel_idx, raw, fit, poly_, params, title):
            got.update(raw=raw, fit=fit, poly=poly_)

    class Status:
        def setText(self, t): got['status'] = t
        def setStyleSheet(self, s): pass

    w = SaveExportMixin.__new__(SaveExportMixin)
    w.__dict__.update(
        monitor=Monitor(), status=Status(), engine=Engine(), _active_channel=1,
        _channel_configs={}, file_list=['f'], _channel_files={},
        txt_min=SimpleNamespace(text=lambda: '100'), txt_max=SimpleNamespace(text=lambda: '199'),
        main_tabs=SimpleNamespace(setCurrentWidget=lambda x: None), _tab_pages={},
        _entry_from_display_name=lambda n, l: 'f', _entry_filepath=lambda e: 'f',
        _row_index_from_display_name=lambda n: 0)
    orig = save_mod.DataIO.load_measurement_with_hk
    save_mod.DataIO.load_measurement_with_hk = staticmethod(lambda *a, **k: (px, alpha, 0, 0, 0))
    try:
        w._replay_result({'File': 'f', 'Channel': 1, 'Params': {
            'channel': 1, 'shifts': [0], 'squeezes': [1], 'gas_coeffs': [1], 'poly_coeffs': [0]}})
    finally:
        save_mod.DataIO.load_measurement_with_hk = orig

    assert 'raw' in got, got.get('status')
    np.testing.assert_allclose(got['fit'], absorb, atol=1e-20)               # Fit = absorption
    np.testing.assert_allclose(got['raw'] - got['fit'], 1e-11, rtol=1e-6)     # residual unchanged
    np.testing.assert_allclose(got['raw'] + got['poly'], alpha - etalon, rtol=1e-9)  # panel dots
    print("test_replay_poly_panel: OK")


if __name__ == '__main__':
    main()
