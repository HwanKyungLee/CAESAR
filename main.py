import sys
import time

from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from app_window import CAESARAnalyzer  # The main application window class

# ─── Entry point ────────────────────────────────────────────────────────────
# Everything starts here when you run  python main.py
if __name__ == '__main__':
    # Qt requires one QApplication instance per process before any widgets exist
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Fusion style: clean, modern look on all platforms

    # Scale font size relative to screen height (reference: 1080p → 9pt)
    from data_io import ui_scale
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
