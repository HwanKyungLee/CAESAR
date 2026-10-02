"""tools/test_wheel_guard.py
Scrolling the Setup page must not change physical constants: a wheel tick over the unfocused
cavity-length spin box changed d 51.8 -> 50.8 cm with no warning (UX audit 2026-10-02).
Focused spin boxes still take the wheel.
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication


def _wheel(w):
    pos = QPointF(w.rect().center())
    ev = QWheelEvent(pos, QPointF(w.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, -120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(w, ev)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from gui.app_window import CAESARAnalyzer
    win = CAESARAnalyzer(); win.show()
    for _ in range(5): app.processEvents()
    sp = win.spin_d_len
    v0 = sp.value()
    win.b_run.setFocus(); app.processEvents()
    _wheel(sp); app.processEvents()
    assert sp.value() == v0, (v0, sp.value())
    print("  PASS  unfocused d spin ignores the wheel")
    sp.setFocus(); app.processEvents()
    if sp.hasFocus():                   # offscreen may refuse focus; only assert when it took it
        _wheel(sp); app.processEvents()
        assert sp.value() != v0
        print("  PASS  focused d spin still takes the wheel")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
