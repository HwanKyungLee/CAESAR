"""Alpha generation failure must not be reported as success (and must not leak the spool).

Before: a channel whose AlphaExportWorker emitted "ERROR: ..." still ended in
100 % / "Done" / "Alpha generation complete", and an exception inside _run_inner
left the %TEMP%/caesar_amb_*.bin spool behind. Runs offscreen, no data needed.
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from gui.app_window_inputs import InputsAlphaMixin  # noqa: E402
from gui.worker import AlphaExportWorker  # noqa: E402


class _App(InputsAlphaMixin):
    """Just enough of CAESARAnalyzer for the queue-completion path."""
    def __init__(self):
        self.status = QLabel()
        self._alpha_queue = []
        self._alpha_out_dir = "OUT"
        self._alpha_done_msgs = []
        self._alpha_failed = []
        self._alpha_status_cb = None
        self._alpha_progress_cb = None
        self.qc_called = False
        self.cb_args = None
        self._alpha_user_done_cb = lambda *a: setattr(self, "cb_args", a)

    def _alpha_qc_after_export(self, out_dir):
        self.qc_called = True


def _check_reporting():
    app = _App()
    app._on_alpha_channel_done("ERROR: not enough values to unpack", "ANs")
    out_dir, msgs, failed = app.cb_args
    assert failed == [("ANs", "ERROR: not enough values to unpack")], failed
    assert "FAILED" in app.status.text() and "ANs" in app.status.text(), app.status.text()
    assert not app.qc_called, "Pipeline Health must not be pointed at a folder with no output"

    app = _App()
    app._on_alpha_channel_done("C:/out", "PNs")
    _, _, failed = app.cb_args
    assert failed == [] and "complete" in app.status.text()
    assert app.qc_called


def _check_spool_cleanup():
    w = AlphaExportWorker([], 0, 4, np.arange(4.0), [500], [510], [1], 0.9, 100.0,
                          tempfile.mkdtemp())
    fd, spool = tempfile.mkstemp(prefix="caesar_amb_test_", suffix=".bin")
    os.close(fd)
    errs = []
    w.finished.connect(errs.append)

    def _boom():
        w._cleanup_spool = lambda: os.remove(spool)
        raise ValueError("boom")
    w._run_inner = _boom
    w.run()                       # synchronous: exercise the except/finally path
    assert errs == ["ERROR: boom"], errs
    assert not os.path.exists(spool), "spool leaked on the exception path"


def main():
    _qapp = QApplication.instance() or QApplication(sys.argv)  # noqa: F841 (keep alive)
    _check_reporting()
    _check_spool_cleanup()
    print("alpha failure reporting + spool cleanup OK")


if __name__ == "__main__":
    main()
