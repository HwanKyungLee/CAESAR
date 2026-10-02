"""tools/test_shortcuts.py
Main-window shortcuts (UX audit 2026-10-02):
  1. Ctrl+S inside Plot Maker used to do nothing — the main window's and Plot Maker's Ctrl+S
     were ambiguous, so Qt fired neither. Now: focus in Plot Maker -> its config save,
     elsewhere -> results save.
  2. Esc asks before stopping a running analysis, and does nothing when idle.
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox


class _Running:
    def isRunning(self): return True


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from gui.app_window import CAESARAnalyzer
    win = CAESARAnalyzer(); win.resize(1400, 900); win.show(); win.activateWindow()
    for _ in range(10): app.processEvents()
    hits = []
    win.save = lambda *a, **k: hits.append("main")
    # The unambiguous path calls the bound save connected at init; with no results it warns.
    QMessageBox.warning = staticmethod(lambda *a, **k: hits.append("main") if "No analysis results" in str(a) else None)
    win.plot_maker._save_cfg = lambda *a, **k: hits.append("pm")

    win.main_tabs.setCurrentWidget(win._tab_pages[win.plot_maker]); win.plot_maker.setFocus()
    for _ in range(5): app.processEvents()
    QTest.keyClick(app.focusWidget() or win, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert hits == ["pm"], hits
    win.main_tabs.setCurrentIndex(0); win.b_run.setFocus()
    for _ in range(5): app.processEvents()
    QTest.keyClick(app.focusWidget() or win, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert hits == ["pm", "main"], hits
    print("  PASS  Ctrl+S goes to Plot Maker inside it, to results save elsewhere")

    asked, stopped = [], []
    win.stop_analysis = lambda: stopped.append(1)
    answer = [QMessageBox.StandardButton.No]
    QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(1), answer[0])[1])
    win._workers = []
    win._confirm_stop_analysis()
    assert not asked and not stopped
    win._workers = [_Running()]
    win._confirm_stop_analysis()
    assert asked and not stopped
    answer[0] = QMessageBox.StandardButton.Yes
    win._confirm_stop_analysis()
    assert stopped == [1]
    win._workers = []
    print("  PASS  Esc asks before stopping, no-op when idle")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
