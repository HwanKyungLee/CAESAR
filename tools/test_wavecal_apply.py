"""tools/test_wavecal_apply.py
Wavelength Calibration "Save & Apply" must go through the single wavecal loader: it used to set
only self.wavelengths / engine.wavelengths, leaving engine._wave_axis, loaded_wl_path and the
channel's wl_path on the old file while saying "applied instantly" (UX audit 2026-10-02).
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

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    import gui.app_window_fitsetup as fs
    from gui.app_window import CAESARAnalyzer
    win = CAESARAnalyzer()

    tmp = tempfile.mkdtemp()
    new_path = os.path.join(tmp, "Calib_test_Hg_400-499nm_Poly2.txt")
    new_wl = np.linspace(401.0, 500.0, 2048)
    np.savetxt(new_path, new_wl, fmt="%.6f")

    class _FakeCalib(QObject):
        calibration_finished = pyqtSignal(np.ndarray)
        def __init__(self, parent):
            super().__init__()
            self.saved_path, self.spectrum, self.fwhm_records = new_path, None, {}
        def exec(self):
            self.calibration_finished.emit(new_wl)
    fs.WavelengthCalibrationDialog = _FakeCalib

    win.open_wavelength_calibration()
    assert win.loaded_wl_path == new_path, win.loaded_wl_path
    assert np.allclose(np.asarray(win.engine._wave_axis, float)[:3], new_wl[:3])
    assert np.allclose(np.asarray(win.wavelengths, float)[:3], new_wl[:3])
    assert win._capture_config()["wl_path"] == new_path
    assert getattr(win, "_refs_dirty", False) is True
    print("  PASS  Save & Apply updates engine axis, loaded path, channel wl_path; refs marked for re-Lock")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
