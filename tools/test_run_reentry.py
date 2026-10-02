"""tools/test_run_reentry.py
RUN re-entry and the run-input lock (UX audit 2026-10-02, sector 1):

  1. RUN/F5 while workers are running is refused — it used to replace `_workers` and orphan
     the first set (still fitting after STOP, progress "70 / 14 scans").
  2. An early return from the RUN body (no data) leaves no stale running flag / locked inputs.
  3. While locked, the inputs that define a run (QC/K live in the params container) are
     disabled, so "settings frozen for this run" is true; unlocking re-enables them.
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication


class _FakeRunning:
    def isRunning(self):
        return True


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from gui.app_window import CAESARAnalyzer

    win = CAESARAnalyzer()
    called = []
    win._start_analysis_body = lambda: called.append(1)

    # 1. re-entry refused while a worker runs
    win._workers = [_FakeRunning()]
    win.start_analysis()
    assert called == [], "RUN body must not run while workers are running"
    assert "already running" in win.status.text()
    print("  PASS  re-entry refused while running")

    # 2. body returns early (nothing started) -> flag reset, inputs unlocked
    win._workers = []
    win._analysis_running = True
    win._set_run_inputs_locked(True)
    win.start_analysis()
    assert called == [1]
    assert win._analysis_running is False
    assert win._params_container.isEnabled() and win.spin_d_len.isEnabled()
    print("  PASS  early return clears running flag and unlocks")

    # 3. lock covers QC/K (inside the params container) and the physical constants
    win._set_run_inputs_locked(True)
    assert not win._params_container.isEnabled()
    assert not win.spin_qc_k.isEnabled() and not win.spin_rl_factor.isEnabled()
    assert win.b_stop is not None and win.b_stop not in win._run_lock_widgets
    win.b_run.setEnabled(True)          # analysis_finished re-enables RUN when all channels are done
    win._unlock_inputs_if_done()
    assert win._params_container.isEnabled() and win.spin_qc_k.isEnabled()
    print("  PASS  lock/unlock covers run-defining inputs")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
