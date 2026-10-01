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


class _Ev:
    def __init__(self, scene_pos):
        self._s = scene_pos

    def scenePos(self):
        return self._s


def test_conc_click_with_downsampling_hits_the_spike():
    """큰 런(화면 peak 솎아내기) — 화면 점은 구간 대표값이라, x부터 맞추면 스파이크를 눌러도
    그 구간의 첫 스캔이 열릴 수 있다. 마우스 위치에서 화면 픽셀로 가장 가까운 **원본 점**이어야 한다."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication
    from gui.monitor_widget import MonitorWidget
    from core.engine import UniversalEngine
    import numpy as np

    app = QApplication.instance() or QApplication([])
    m = MonitorWidget(UniversalEngine())
    m.resize(1200, 800); m.show()
    m.setup_conc_plots(["NO2"])
    n = 60000
    rng = np.random.default_rng(0)
    vals = 5 + 0.1 * rng.normal(size=n)
    spike = 41234
    vals[spike] = 50.0
    from datetime import datetime, timedelta
    t0 = datetime(2026, 5, 20)
    res = [{'File': f"a.dat [{i:05d}]", 'Channel': 1,
            'Time': f"{t0 + timedelta(seconds=20 * i):%Y-%m-%d %H:%M:%S}", 'NO2': float(vals[i])}
           for i in range(n)]
    got = []
    m.conc_point_clicked.connect(got.append)
    m.rebuild_conc(res)
    m.tabs.setCurrentWidget(m.tab_conc)
    p = m._conc_plots["NO2"]
    p.getViewBox().autoRange()
    app.processEvents()
    curve = m._conc_curves["NO2"][1]
    shown = len(curve.getData()[0]) if curve.getData()[0] is not None else 0
    assert 0 < shown < n, f"솎아내기가 안 걸림({shown} of {n})"
    d = m._conc_data["NO2"][1]
    vb = p.getViewBox()
    scene = vb.mapViewToScene(QPointF(d['x'][spike], d['y'][spike]))
    m._on_conc_click("NO2", 1, [_Pt(d['x'][spike - 3], 5.0)], _Ev(scene))
    assert got[-1] is res[spike], ("스파이크 클릭이 다른 스캔을 열었다",
                                   got[-1]['File'], res[spike]['File'])


if __name__ == "__main__":
    test_conc_click_returns_clicked_result()
    test_conc_click_with_downsampling_hits_the_spike()
    print("ok")
