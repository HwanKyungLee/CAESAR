"""Clicking a Conc-plot point must hand back that point's own result dict
(Step appends per row via update_conc, Fast rebuilds once via rebuild_conc)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Pt:
    def __init__(self, x, y):
        from PyQt6.QtCore import QPointF
        self._p = QPointF(x, y)

    def pos(self):
        return self._p


def test_conc_click_returns_clicked_result():
    from PyQt6.QtWidgets import QApplication
    from gui.monitor_widget import MonitorWidget
    from core.engine import UniversalEngine

    app = QApplication.instance() or QApplication([])
    m = MonitorWidget(UniversalEngine())
    m.setup_conc_plots(["NO2"])
    res = [{'File': f"a.dat [{i:04d}]", 'Channel': 1 + i % 2,
            'Time': f"2026-05-20 00:{i:02d}:00", 'NO2': float(i)} for i in range(6)]
    got = []
    m.conc_point_clicked.connect(got.append)

    m.rebuild_conc(res)                       # Fast path
    m._on_conc_click("NO2", 2, [_Pt(m._conc_data["NO2"][2]['x'][1], 3.0)])
    assert got[-1] is res[3]

    m.clear_conc()                            # Step path
    for i, r in enumerate(res):
        m.update_conc(r, i)
    m._on_conc_click("NO2", 1, [_Pt(m._conc_data["NO2"][1]['x'][2], 4.0)])
    assert got[-1] is res[4]
    app.processEvents()


if __name__ == "__main__":
    test_conc_click_returns_clicked_result()
    print("ok")
