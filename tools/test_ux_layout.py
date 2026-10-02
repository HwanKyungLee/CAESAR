# -*- coding: utf-8 -*-
"""tools/test_ux_layout.py — stage-3 UX behaviour that is logic, not looks (2026-10-03).

  1) empty_hint: the note shows on an empty plot / table and hides once data arrives
  2) Setup page stacks its two columns below SETUP_STACK_BELOW and goes back side by side above it
  3) the main window's minimum width fits a 1366×768 @150 % screen (910 logical px)

    python tools/test_ux_layout.py
"""
from __future__ import annotations

import os
import sys

sys.modules.setdefault("_wmi", None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from PyQt6.QtWidgets import QApplication, QBoxLayout, QTableWidget
    app = QApplication.instance() or QApplication(sys.argv)
    from gui.theme import apply_augur
    apply_augur(app)
    import pyqtgraph as pg
    from gui.empty_hint import attach

    pw = pg.PlotWidget(); pw.resize(400, 300); pw.show()
    h = attach(pw, "nothing yet")
    app.processEvents()
    assert not h.label.isHidden()
    pw.plot([1, 2, 3], [1, 2, 3]); h.refresh()
    assert h.label.isHidden(), "hint must hide once the plot has points"
    tb = QTableWidget(0, 2); tb.show()
    ht = attach(tb, "no rows")
    assert not ht.label.isHidden()
    tb.setRowCount(1); ht.refresh()
    assert ht.label.isHidden()
    print("  PASS  empty hint shows on empty plot/table, hides with data")

    from gui.app_window import CAESARAnalyzer
    w = CAESARAnalyzer(); w.resize(1400, 900); w.show()
    for _ in range(5):
        app.processEvents()
    w._setup_reflow(400)
    assert w._setup_main_layout.direction() == QBoxLayout.Direction.TopToBottom
    w._setup_reflow(2000)
    assert w._setup_main_layout.direction() == QBoxLayout.Direction.LeftToRight
    print("  PASS  Setup page stacks when narrow, side by side when wide")

    mw = w.minimumSizeHint().width()
    assert mw <= 910, f"main window needs {mw} px — wider than 1366x768 @150 %"
    print(f"  PASS  main window minimum width {mw} px <= 910")
    print("test_ux_layout: OK")


if __name__ == "__main__":
    main()
    # pyqtgraph scenes left to interpreter-exit GC sometimes die with 0xC0000005 after the checks
    # passed (same as tools/test_conc_click_replay.py, 9bd36a4) — close windows and leave at once.
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance()
    if _app is not None:
        for _w in _app.topLevelWidgets():
            _w.close()
            _w.deleteLater()
        _app.processEvents()
    sys.stdout.flush()
    os._exit(0)
