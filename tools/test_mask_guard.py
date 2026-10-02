"""tools/test_mask_guard.py
Reference mask guards (UX audit 2026-10-02): the old default "441-450" looked like nm but is
detector pixels — applying it kept 9 px and the fit returned NO2 -1.3e88 ppb with "Success";
a reversed range zeroed the whole reference, also "Success".
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
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox


class _Txt:
    def __init__(self, t): self.t = t
    def text(self): return self.t


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    import gui.app_window_fitsetup as fs
    from gui.ref_mask_dialog import MaskDialog as RealMask
    from core.engine import UniversalEngine

    _dlg = RealMask(["NO2"])                         # keep a reference: Qt deletes children otherwise
    assert _dlg.txt_range.text() == "", "mask range must start empty"
    print("  PASS  no pixel-range default")

    said = []
    QMessageBox.warning = staticmethod(lambda *a, **k: said.append(("warn", a[1], a[2])))
    QMessageBox.information = staticmethod(lambda *a, **k: said.append(("info", a[1], a[2])))
    answer = [QMessageBox.StandardButton.No]
    QMessageBox.question = staticmethod(lambda *a, **k: (said.append(("ask", a[1], a[2])), answer[0])[1])

    data = {}

    class _FakeDlg:
        def __init__(self, gases): pass
        def exec(self): return QDialog.DialogCode.Accepted
        def get_data(self): return dict(data)
    fs.MaskDialog = _FakeDlg

    class _Host(fs.FitSetupMixin):
        def __init__(self):
            self.engine = UniversalEngine()
            self.engine.raw_references["NO2"] = np.sin(np.linspace(0, 20, 2048)) + 2.0
            self.engine.gas_list = ["NO2"]
            self.engine.is_engine_ready = lambda: True
            self.txt_min, self.txt_max = _Txt("600"), _Txt("1270")
            self.ref_widgets = [{'n': _Txt("NO2")}]
        def refresh_viewer(self): pass
        def lock_ref(self, silent=False):            # real Lock reloads the file, then masks
            self.engine.raw_references["NO2"] = before.copy()
            m = self.ref_widgets[0].get('mask')
            if m:
                self.engine.apply_mask_spec("NO2", m)

    h = _Host()
    before = h.engine.raw_references["NO2"].copy()

    data.update(name="NO2", mode="manual", range="900-600")
    h.open_mask_dialog()
    assert said[-1][0] == "warn" and "reversed" in said[-1][2]
    assert np.array_equal(h.engine.raw_references["NO2"], before)
    print("  PASS  reversed range refused, reference untouched")

    data.update(range="441-450")                     # 0 px inside the 600-1270 fit window
    h.open_mask_dialog()
    assert said[-1][0] == "ask" and "Only 0 px" in said[-1][2]
    assert np.array_equal(h.engine.raw_references["NO2"], before)
    print("  PASS  mask leaving <10 px in the fit window asks, No keeps the reference")

    data.update(range="700-1200")
    h.open_mask_dialog()
    assert said[-1][0] == "info" and "Saved with the reference" in said[-1][2] and "500 non-zero px" in said[-1][2]
    assert h.ref_widgets[0]['mask'] == {'mode': 'manual', 'range': [700, 1200]}
    print("  PASS  normal mask applies and is stored on the reference row")

    data.update(range="800-1000")                    # replaces, does not stack on 700-1200
    h.open_mask_dialog()
    assert np.count_nonzero(h.engine.raw_references["NO2"]) == 200
    data.update(mode="clear")
    h.open_mask_dialog()
    assert h.ref_widgets[0]['mask'] is None
    assert np.array_equal(h.engine.raw_references["NO2"], before)
    print("  PASS  a new mask replaces the old one; 'Remove mask' restores the full reference")
    return 0


if __name__ == "__main__":
    sys.exit(main())
