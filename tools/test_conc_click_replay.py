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
    m._on_conc_scene_click(_Ev(scene))
    assert got[-1] is res[spike], ("스파이크 클릭이 다른 스캔을 열었다",
                                   got[-1]['File'], res[spike]['File'])


def test_trend_click_skip_and_per_channel_gas():
    """(2026-10-02 리뷰) 추세 클릭은 그 채널·그 시각의 **같은** 스캔만 재생한다.
    1) Skip 스캔(Fast 추세엔 RMS 점으로 그려지지만 농도 결과가 없음)을 누르면 이웃을 재생하지 않는다.
    2) 첫 기체가 그 채널에 없어도(채널마다 레퍼런스가 다름) 그 채널의 다른 기체로 찾아 재생한다."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QPointF
    from gui.monitor_widget import MonitorWidget
    from core.engine import UniversalEngine

    app = QApplication.instance() or QApplication([])
    m = MonitorWidget(UniversalEngine())
    m.resize(1200, 900); m.show()
    m.setup_conc_plots(["NO2", "H2O"])
    res = []
    for i in range(20):
        r = {'File': f"b.dat [{i:04d}]", 'Channel': 2, 'Time': f"2026-05-20 01:{i:02d}:00",
             'H2O': 1e6 + i, 'Shift': 0.1 * (i % 5), 'Squeeze': 1.0, 'RMS': 1e-4 * (1 + i % 3)}
        if i == 6:                                   # 건너뛴 스캔 — 기체 값 없음
            r = {'File': r['File'], 'Channel': 2, 'Time': r['Time'], 'Status': 'Skip: test',
                 'Shift': 0.0, 'Squeeze': 1.0, 'RMS': 0.0}
        res.append(r)
    got = []
    m.conc_point_clicked.connect(got.append)
    m.rebuild_conc(res)
    m.rebuild_trend(res)
    m.flush_plots()
    m.tabs.setCurrentWidget(m.tab_trend)
    _settle(app, m)
    td = m._trend_data[2]

    def click_sh(k):
        got.clear()
        sp = m.p_sh.getViewBox().mapViewToScene(QPointF(td['x'][k], td['sh'][k]))
        m._on_trend_scene_click(_Ev(sp))
        return got[-1] if got else None

    assert click_sh(9) is res[9], "CH2 에 NO2 가 없어도 H2O 로 찾아 재생해야 한다"
    assert click_sh(6) is None, "Skip 스캔 점은 이웃 스캔을 재생하면 안 된다"


if __name__ == "__main__":
    test_click_near_point_returns_its_result()
    test_conc_click_with_downsampling_hits_the_spike()
    test_trend_click_skip_and_per_channel_gas()
    # 검사는 여기서 끝 — MonitorWidget 3개(pyqtgraph 장면)를 인터프리터 종료 GC 에 맡기면 Qt 소멸 순서 때문에
    # 가끔 접근 위반(exit 0xC0000005)으로 죽었다(pytest 하위 프로세스에서 3~5번 중 1~4번, 'ok' 출력 뒤).
    # 창을 명시적으로 닫아 정리하고, 결과를 내보낸 뒤 바로 끝낸다.
    import os as _os
    from PyQt6.QtWidgets import QApplication as _QA
    _app = _QA.instance()
    if _app is not None:
        for _w in _app.topLevelWidgets():
            _w.close()
            _w.deleteLater()
        _app.processEvents()
    print("ok")
    sys.stdout.flush()
    _os._exit(0)
