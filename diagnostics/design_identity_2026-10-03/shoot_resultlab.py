"""Result Lab screenshots: empty, a fit result opened, one scan clicked (detail + residual).
    PYTHONIOENCODING=utf-8 python shoot_resultlab.py 1920 1080 1 fhd
"""
import os
import sys


def main():
    sys.modules.setdefault("_wmi", None)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    W, H, SCALE, TAG = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
    os.environ["QT_SCALE_FACTOR"] = SCALE
    sys.path.insert(0, r"C:\GHL\CAESAR")
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    app = QApplication(sys.argv)
    from gui.theme import apply_augur
    apply_augur(app)
    from gui.app_window import CAESARAnalyzer
    w = CAESARAnalyzer()
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.resize(int(W / float(SCALE)), int(H / float(SCALE)))
    w.show()

    def pump(n=30):
        for _ in range(n):
            app.processEvents()
    shots = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
    os.makedirs(shots, exist_ok=True)
    w.main_tabs.setCurrentWidget(w._tab_pages[w.result_viewer])
    pump()
    w.grab().save(os.path.join(shots, f"rl_{TAG}_0_empty.png"))
    rv = w.result_viewer
    rv._path = r"C:\Doasis_Work\Output\fitting\new\26yeosu\2026-05-18\fitting\260518_CH1_ANs_r96b76.dat"
    rv._reload()
    pump()
    w.grab().save(os.path.join(shots, f"rl_{TAG}_1_fit.png"))
    rv._show_scan_detail(100)
    pump(60)
    w.grab().save(os.path.join(shots, f"rl_{TAG}_2_detail.png"))
    print("ok")


if __name__ == "__main__":
    main()
