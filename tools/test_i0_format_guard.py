"""Browse I0 / table "Set as I0" must refuse a raw Mega-Matrix (and length mismatches).

Before: set_i0_path read any file with the 1D loader, so a raw Mega-Matrix became
an "I0" made of column 0 (timestamps) of every row, shown green as loaded.
Offscreen, synthetic files only.
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

import gui.app_window_inputs as AWI  # noqa: E402

_warnings = []
AWI.QMessageBox.warning = staticmethod(lambda *a, **k: _warnings.append(a[1]))


class _App(AWI.InputsAlphaMixin):
    def __init__(self, n_wl):
        self.lbl_i0_path = QLabel("Auto from ZA scans")
        self.status = QLabel()
        self.wavelengths = np.linspace(400, 500, n_wl)
        self.i0_data = None

    def update_diagnostic_plot(self):
        pass

    def _refresh_setup_status(self):
        pass


def main():
    _qapp = QApplication.instance() or QApplication(sys.argv)  # noqa: F841 (keep alive)
    with tempfile.TemporaryDirectory() as td:
        raw = os.path.join(td, "2026-05-20-001.dat")
        with open(raw, "w") as fh:
            for t in range(3):
                fh.write("\t".join([str(1000.0 + t)] + ["5"] * 4200) + "\n")
        one_d = os.path.join(td, "i0.dat")
        np.savetxt(one_d, np.arange(10.0) + 100.0)

        app = _App(10)
        app.set_i0_path(raw)
        assert app.i0_data is None and _warnings[-1] == "Not an I0 spectrum", _warnings
        assert app.lbl_i0_path.text() == "Auto from ZA scans"

        app = _App(12)
        app.set_i0_path(one_d)
        assert app.i0_data is None and _warnings[-1] == "I0 length mismatch", _warnings

        app = _App(10)
        n_warn = len(_warnings)
        app.set_i0_path(one_d)
        assert len(_warnings) == n_warn and app.lbl_i0_path.text() == "i0.dat"
        assert np.allclose(app.i0_data, np.arange(10.0) + 100.0)
    print("I0 format guard: mega-matrix refused, length checked, 1D accepted OK")


if __name__ == "__main__":
    main()
