"""tools/test_lock_ref_keep.py
Lock must not destroy the previously locked references when every row fails to load
(UX audit 2026-10-02: lock_ref cleared the engine first, so a bad file left it empty).
An intentionally empty reference list still empties the engine.
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox


class _Txt:
    def __init__(self, t): self.t = t
    def text(self): return self.t
    def setText(self, t): self.t = t


class _Spin:
    def value(self): return 0


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    import gui.app_window_fitsetup as fs
    from core.engine import UniversalEngine
    said = []
    QMessageBox.warning = staticmethod(lambda *a, **k: said.append(a[2]))

    class _Host(fs.FitSetupMixin):
        def __init__(self):
            self.engine = UniversalEngine()
            self.engine.raw_references["NO2"] = np.ones(2048)
            self.engine.gas_list = ["NO2"]
            self.status = _Txt("")
            self.ref_widgets = []
    h = _Host()
    eng = h.engine

    h.ref_widgets = [{'n': _Txt("NO2"), 'fp': "C:/__no_such__/Ref_NO2.dat", 'mult': _Spin()}]
    h.lock_ref()
    assert h.engine is eng and h.engine.gas_list == ["NO2"] and "NO2" in h.engine.raw_references
    assert "kept" in said[-1]
    print("  PASS  all rows failing to load keeps the previously locked set (same engine object)")

    h.ref_widgets = []
    h.lock_ref()
    assert h.engine.gas_list == [] and "empty" in said[-1]
    print("  PASS  an empty reference list still empties the engine, and says so")
    return 0


if __name__ == "__main__":
    sys.exit(main())
