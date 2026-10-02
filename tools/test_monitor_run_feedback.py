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


def test_trend_throttle_is_per_channel():
    """R8: a shared throttle timestamp starved the second channel's redraw."""
    m = _monitor()
    for i in range(4):
        for ch in (1, 2):
            m.update_trend({'idx': i, 'shift': 0.0, 'squeeze': 1.0, 'rms': 1e-4,
                            'channel': ch, 'Time': f"2026-05-20 00:{i:02d}:00"})
    for ch in (1, 2):
        assert m._trend_curves[ch]['sh'].xData is not None, ch


class _Eng:
    def __init__(self, gas, level):
        self.gas_list, self.level = [gas], level

    def get_individual_gas_contribution(self, px, sh, sq, coeffs, i):
        import numpy as np
        return np.full(len(px), self.level)


def _emit_scan(m, eng, ch):
    """Emit one scan the way a channel worker does (signal from a QThread)."""
    import numpy as np
    from PyQt6.QtCore import QThread, pyqtSignal

    class W(QThread):
        plot_update = pyqtSignal(np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict, str)
    w = W()
    w.engine = eng
    w.plot_update.connect(m.update_spectrum)
    px = np.arange(10.0)
    w.plot_update.emit(px, np.zeros(10), np.zeros(10), np.zeros(10),
                       {'channel': ch, 'shifts': [0], 'squeezes': [1], 'gas_coeffs': [1]}, "s")
    return w


def test_components_use_the_scans_own_engine():
    """R2/R4: another channel's scan was drawn with the active-tab engine, also after
    a tab round trip."""
    m = _monitor()
    m.engine = _Eng("A", 1.0)                   # active-tab engine
    m.set_available_channels([1, 2])
    m.cb_fit_channel.setCurrentIndex(1)          # view CH2
    m.tabs.setCurrentIndex(0)
    _w = _emit_scan(m, _Eng("B", 7.0), 2)
    assert "B_fit" in m.curve_items and m.curve_items["B_fit"].yData[0] == 7.0
    m.tabs.setCurrentIndex(1)
    m.tabs.setCurrentIndex(0)
    assert "B_fit" in m.curve_items and m.curve_items["B_fit"].yData[0] == 7.0


def test_new_run_drops_previous_scans():
    """R9: Fit View / Components kept the previous run's scan after a new RUN."""
    m = _monitor()
    m.engine = _Eng("A", 1.0)
    m.set_available_channels([1])
    m.tabs.setCurrentIndex(1)
    _w = _emit_scan(m, m.engine, 1)
    assert m.latest_fit_data and m.curve_meas.xData is not None
    m.set_available_channels([1])               # next RUN start (same channels)
    assert m.latest_fit_data is None and not m._latest_by_channel
    assert m.curve_meas.xData is None or len(m.curve_meas.xData) == 0
    assert not m.curve_items
    m.tabs.setCurrentIndex(0)                    # tab hop must not redraw old data
    assert not m.curve_items


def test_status_colour_reads_the_head_label():
    """R7: 'OK · AT_BOUND' was painted with the failure colour."""
    from gui.app_window_results import ResultsQCMixin
    from gui.theme import AUGUR
    from PyQt6.QtGui import QColor
    _app()
    bg = lambda st: ResultsQCMixin._status_item(st).background().color().name()
    fail, warn = QColor(AUGUR.fail_bg).name(), QColor(AUGUR.warn_bg).name()
    assert bg("OK · AT_BOUND") not in (fail, warn)
    assert bg("OK") not in (fail, warn)
    assert bg("Recovered · STEP_LIMITED") == warn
    assert bg("Unstable") == fail
    assert bg("QC-Auto (rms=1e-3>1e-4)") == fail
    assert bg("Settling") == fail


def _host(results, channels, fast=False, cap=5000):
    """Smallest ResultsQCMixin host that can run analysis_finished; QMessageBox
    calls are captured in host.popups instead of shown."""
    from types import SimpleNamespace
    from PyQt6.QtWidgets import QLabel, QProgressBar, QPushButton, QTableWidget, QWidget
    from gui.app_window_results import ResultsQCMixin
    import gui.app_window_results as mod
    _app()

    class Host(ResultsQCMixin, QWidget):
        def _autosave_close(self):
            pass

    h = Host()
    h.popups = []
    mod.QMessageBox = SimpleNamespace(
        information=lambda _w, t, m: h.popups.append(("info", t, m)),
        warning=lambda _w, t, m: h.popups.append(("warn", t, m)))
    h.table, h.status, h.pbar = QTableWidget(), QLabel(), QProgressBar()
    h.b_run, h.b_stop = QPushButton(), QPushButton()
    h.engine = SimpleNamespace(gas_list=['NO2'])
    h.monitor = SimpleNamespace()
    h.table.setColumnCount(9)
    h.results = list(results)
    h._alpha_groups = {c: ['x'] for c in channels}
    h._workers_total = len(channels)
    h._workers_done = 0
    h._multi_channel_mode = len(channels) > 1
    h._fast_mode_active = fast
    h._fast_table_cap = cap
    return h


def _finish_all(h):
    for _ in range(h._workers_total):
        h.analysis_finished()


def test_parallel_failure_is_not_reported_as_success():
    """Pattern A: worker ERROR + finished → green 'Completed' / 'successfully'."""
    h = _host([], [1], fast=True)
    h._on_analysis_status(1, "ERROR: parallel fit failed — X: boom (no results)")
    _finish_all(h)
    assert "FAILED" in h.status.text() and "Completed" not in h.status.text()
    kind, title, msg = h.popups[-1]
    assert kind == "warn" and "successfully" not in msg and "boom" in msg
    # Errors do not leak into the next run.
    h2 = _host([_row(0)], [1])
    h2._run_errors = []
    _finish_all(h2)
    assert "Completed" in h2.status.text() and h2.popups[-1][0] == "info"


def test_channel_without_rows_is_a_failure():
    """Pattern A: one of two channels returned nothing (no ERROR line seen)."""
    h = _host([_row(i, ch=1) for i in range(3)], [1, 2])
    _finish_all(h)
    assert "FAILED" in h.status.text() and "CH2: no results" in h.status.text()
    assert h.popups[-1][0] == "warn"


def test_table_cap_note_survives_completion():
    """R3: the 5,000-row cap note was overwritten by 'Analysis Completed!'."""
    h = _host([_row(i % 50) for i in range(12)], [1], fast=True, cap=5)
    _finish_all(h)
    assert "5 of 12 rows" in h.status.text() and "Completed" in h.status.text()
    assert "5 of 12 rows" in h.popups[-1][2]


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_"):
            _f()
            print("ok", _n)
