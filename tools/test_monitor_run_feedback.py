"""Analysis Monitor / run-completion regressions (UX audit 2026-10-02, sector 3).

Offscreen Qt; no data needed."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


_APP = []      # keep the QApplication referenced — a collected one crashes Qt


def _app():
    from PyQt6.QtWidgets import QApplication
    if not _APP:
        _APP.append(QApplication.instance() or QApplication([]))
    return _APP[0]


def _monitor():
    from gui.monitor_widget import MonitorWidget
    from core.engine import UniversalEngine
    _app()
    return MonitorWidget(UniversalEngine())


def _row(i, ch=1, **kw):
    r = {'File': f"a.dat [{i:04d}]", 'Channel': ch, 'Time': f"2026-05-20 00:{i:02d}:00",
         'NO2': 1.0, 'Shift': 0.0, 'Squeeze': 1.0, 'RMS': 1e-4, 'Chi2': 1.0, 'SNR': 10.0,
         'Status': 'OK'}
    r.update(kw)
    return r


def test_user_x_zoom_survives_live_redraw():
    """R1: autoRangeEnabled() is [x, y] (always truthy) — a user's x zoom was reset."""
    m = _monitor()
    m.setup_conc_plots(["NO2"])
    for i in range(5):
        m.update_trend({'idx': i, 'shift': 0.0, 'squeeze': 1.0, 'rms': 1e-4,
                        'channel': 1, 'Time': f"2026-05-20 00:{i:02d}:00"})
    plots = [m.p_sh, m.p_sq, m.p_rms, m._conc_plots["NO2"]]
    for p in plots:
        p.setXRange(0, 1)                       # user zoom → x auto-range off
    m._redraw_trend(1)
    m._last_conc_draw = 0.0
    m.update_conc(_row(6), 6)
    for p in plots:
        assert not p.getViewBox().autoRangeEnabled()[0], p


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_"):
            _f()
            print("ok", _n)
