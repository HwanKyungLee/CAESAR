import sys
import time
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
_crash_fh.write(f"\n===== 세션 시작 {_dt.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
_crash_fh.flush()
faulthandler.enable(file=_crash_fh, all_threads=True)

def _excepthook(etype, value, tb):
    try:
        _crash_fh.write(f"\n[미처리 예외 {_dt.datetime.now():%Y-%m-%d %H:%M:%S}]\n")
        traceback.print_exception(etype, value, tb, file=_crash_fh)
        _crash_fh.flush()
    except Exception:
        pass
    sys.__excepthook__(etype, value, tb)
sys.excepthook = _excepthook

# stdout/stderr를 logs/session_*.log 로도 남긴다(진단 print 사후 추적용).
from core.session_log import install as _install_session_log
_install_session_log()

from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from gui.app_window import CAESARAnalyzer  # The main application window class

# ─── Entry point ────────────────────────────────────────────────────────────
# Everything starts here when you run  python main.py
if __name__ == '__main__':
    # Qt requires one QApplication instance per process before any widgets exist
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Fusion style: clean, modern look on all platforms

    # Scale font size relative to screen height (reference: 1080p → 9pt)
    from core.data_io import ui_scale
    _s = ui_scale()
    _font = app.font()
    _font.setPointSize(max(7, round(9 * _s)))
    app.setFont(_font)

    # ── Splash screen ────────────────────────────────────────────────────────
    # Show a logo image while the heavy main window is initializing in the background
    splash_pixmap = QPixmap("Argos.png")
    splash = QSplashScreen(splash_pixmap, Qt.WindowType.WindowStaysOnTopHint)
    splash.show()

    # Print a loading message at the bottom-center of the splash image
    splash.showMessage(
        "Loading CAESAR Pro V1.0 Engine...",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
        Qt.GlobalColor.white
    )

    # Force the event loop to process pending events so the splash actually
    # renders on screen before the next line blocks the thread
    app.processEvents()


    # ── Main window initialization ───────────────────────────────────────────
    # CAESARAnalyzer.__init__ loads the engine, builds every widget, and
    # connects all signals — this is the slow part covered by the splash
    ex = CAESARAnalyzer()

    # Brief pause so the splash remains visible before the main window appears
    time.sleep(0.5)

    ex.showMaximized()

    # Dissolve the splash and bring the fully loaded main window to the front
    if 'splash' in locals():
        splash.finish(ex)

    # Hand control over to the Qt event loop.
    # This call blocks until the user closes the window, then returns an exit code.
    sys.exit(app.exec())
