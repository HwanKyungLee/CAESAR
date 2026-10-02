"""tools/test_test_fit_apply_channel.py
Test Fit is modeless. Recommendations computed on CH1 used to be applied to whatever tab was
active when Apply was pressed (UX audit 2026-10-02: ANs' shift Center -6.07 landed on PNs).
Apply must refuse on another channel, and must ask before changing settings on the right one.
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QMessageBox


class _Spin:
    def __init__(self, v): self.v = v
    def value(self): return self.v


class _Btn:
    def setText(self, t): self.text = t
    def setEnabled(self, b): self.enabled = b


class _App:
    def __init__(self, active):
        self._active_channel = active
        self.spin_poly_deg, self.spin_step_limit = _Spin(4), _Spin(0.5)
        self.ref_props = {"NO2": {"sh_mode": "Limit", "sh_val": "-10, 0.5"}}
        self.applied = []
    def _apply_test_fit_recommendations(self, r): self.applied.append(r)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from gui.test_fit_dialog import TestFitDialog
    asked = []
    QMessageBox.warning = staticmethod(lambda *a, **k: asked.append(("warn", a[2])))
    answer = [QMessageBox.StandardButton.No]
    QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(("ask", a[2])), answer[0])[1])
    result = {"proposed_poly_deg": 3, "proposed_step_limit": 0.5,
              "proposed_ref_props": {"NO2": {"sh_mode": "Center", "sh_val": "-6.07, 2.07"}}}

    class _D:
        pass
    d = _D(); d._last_result = result; d._rec_channel = 1; d._btn_apply = _Btn()

    d._app = _App(active=2)
    TestFitDialog._on_apply(d)
    assert d._app.applied == [] and asked[-1][0] == "warn" and "CH1" in asked[-1][1]
    print("  PASS  Apply on another channel tab is refused")

    d._app = _App(active=1)
    TestFitDialog._on_apply(d)                       # user answers No
    assert d._app.applied == [] and asked[-1][0] == "ask"
    assert "Poly degree: 4 -> 3" in asked[-1][1] and "NO2" in asked[-1][1]
    answer[0] = QMessageBox.StandardButton.Yes
    TestFitDialog._on_apply(d)
    assert d._app.applied == [result]
    print("  PASS  same channel: shows the changes, applies only on Yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
