import sys
import os

# ── 크래시 로그 ──────────────────────────────────────────────────────────────
# 밤샘 런 중 프로세스가 소리없이 죽으면(OOM/액세스 위반/미처리 예외) 원인을 알 수
# 없으므로, 하드크래시는 faulthandler가, 파이썬 예외는 excepthook이 logs/에 남긴다.
import faulthandler
import traceback
import datetime as _dt

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(_LOG_DIR, exist_ok=True)
_crash_fh = open(os.path.join(_LOG_DIR, 'crash.log'), 'a', encoding='utf-8')
_crash_fh.write(f"\n===== session start {_dt.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
_crash_fh.flush()
faulthandler.enable(file=_crash_fh, all_threads=True)

def _excepthook(etype, value, tb):
    try:
        _crash_fh.write(f"\n[uncaught exception {_dt.datetime.now():%Y-%m-%d %H:%M:%S}]\n")
        traceback.print_exception(etype, value, tb, file=_crash_fh)
        _crash_fh.flush()
    except Exception:
        pass
    sys.__excepthook__(etype, value, tb)
sys.excepthook = _excepthook

# stdout/stderr를 logs/session_*.log 로도 남긴다(진단 print 사후 추적용).
from core.session_log import install as _install_session_log
_install_session_log()

# NOTE: keep these top-level imports lightweight. The heavy import
# (`gui.app_window`, which pulls in matplotlib + scipy via the dialog
# modules) is deferred until *after* the splash is on screen — otherwise
# the logo can't appear until ~a second of import work finishes first.
from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from core.__version__ import __version__

# ─── Entry point ────────────────────────────────────────────────────────────
# Everything starts here when you run  python main.py
if __name__ == '__main__':
    # Qt requires one QApplication instance per process before any widgets exist
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Fusion style: clean, modern look on all platforms

    # ── Splash screen ────────────────────────────────────────────────────────
    # Show the logo FIRST, before any heavy module import or window build, so it
    # appears almost instantly. Everything slow below runs while it is visible.
    splash_pixmap = QPixmap("AUGUR.png").scaledToWidth(
        360, Qt.TransformationMode.SmoothTransformation
    )
    splash = QSplashScreen(splash_pixmap, Qt.WindowType.WindowStaysOnTopHint)
    splash.show()

    # Print a loading message at the bottom-center of the splash image
    splash.showMessage(
        f"Loading Augur v{__version__} Engine...",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
        Qt.GlobalColor.white
    )

    # Force the event loop to paint the splash before the blocking work below
    app.processEvents()

    # Scale font size relative to screen height (reference: 1080p → 9pt)
    from core.data_io import ui_scale
    _s = ui_scale()
    _font = app.font()
    _font.setPointSize(max(7, round(9 * _s)))
    app.setFont(_font)

    # ── Main window initialization ───────────────────────────────────────────
    # Importing app_window loads matplotlib/scipy (heaviest part of startup);
    # CAESARAnalyzer.__init__ then builds every widget and connects all signals.
    # Both run under the splash so the user sees the logo the whole time.
    from gui.app_window import CAESARAnalyzer  # The main application window class

    splash.showMessage(
        "Building interface...",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
        Qt.GlobalColor.white
    )
    app.processEvents()

    ex = CAESARAnalyzer()

    ex.showMaximized()

    # Dissolve the splash and bring the fully loaded main window to the front
    if 'splash' in locals():
        splash.finish(ex)

    # Hand control over to the Qt event loop.
    # This call blocks until the user closes the window, then returns an exit code.
    sys.exit(app.exec())
