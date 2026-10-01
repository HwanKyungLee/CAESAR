"""Clicking near a Conc (or Shift/Squeeze/RMS) point must hand back that point's
own result dict (Step appends per row via update_conc, Fast rebuilds once via
rebuild_conc) — and a click farther than _CLICK_PX from every point picks nothing."""
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Ev:
    def __init__(self, pos):
        self._p = pos

    def scenePos(self):
        return self._p

    def button(self):
        from PyQt6.QtCore import Qt
        return Qt.MouseButton.LeftButton


def _settle(app, w):
    for _ in range(10):
        app.processEvents()
    w.grab()                      # forces layout so view→scene transforms are current
    for _ in range(10):
        app.processEvents()


def test_click_near_point_returns_its_result():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QPointF
    from gui.monitor_widget import MonitorWidget
    from core.engine import UniversalEngine

    app = QApplication.instance() or QApplication([])
    m = MonitorWidget(UniversalEngine())
    m.resize(1200, 900)
    m.show()
    m.setup_conc_plots(["NO2", "H2O"])
    res = [{'File': f"a.dat [{i:04d}]", 'Channel': 1 + i % 2,
            'Time': f"2026-05-20 00:{i:02d}:00", 'NO2': float(i % 7), 'H2O': 1e6 + i,
            'Shift': 0.1 * (i % 5), 'Squeeze': 1.0, 'RMS': 1e-4 * (1 + i % 3)} for i in range(40)]
    got = []
    m.conc_point_clicked.connect(got.append)

    def click(widget, plot, x, y, dx):
        got.clear()
        sp = plot.getViewBox().mapViewToScene(QPointF(x, y)) + QPointF(dx, 0)
        handler = m._on_conc_scene_click if widget is m.glw_conc else m._on_trend_scene_click
        handler(_Ev(sp))
        return got[-1] if got else None

    # Fast path (bulk) and Step path (per row) fill Conc the same way.
    for fill in ("fast", "step"):
        m.clear_conc()
        if fill == "fast":
            m.rebuild_conc(res)
        else:
            for i, r in enumerate(res):
                m.update_conc(r, i)
        m.flush_plots()
        m.tabs.setCurrentWidget(m.tab_conc)
        _settle(app, m)
        x = m._conc_data["H2O"][2]['x'][3]               # res[7] (CH2 = odd rows)
        assert click(m.glw_conc, m._conc_plots["H2O"], x, res[7]['H2O'], 5) is res[7], fill
        assert click(m.glw_conc, m._conc_plots["H2O"], x, res[7]['H2O'], 40) is None, fill

    m.rebuild_trend(res)
    m.tabs.setCurrentWidget(m.tab_trend)
    _settle(app, m)
    td = m._trend_data[1]
    x = td['x'][4]                                       # res[8] (CH1 = even rows)
    assert click(m.glw_trend, m.p_sh, x, td['sh'][4], 5) is res[8]
    assert click(m.glw_trend, m.p_rms, x, math.log10(res[8]['RMS']), 5) is res[8]
    assert click(m.glw_trend, m.p_sq, x, 1.0, 40) is None


if __name__ == "__main__":
    test_click_near_point_returns_its_result()
    print("ok")
