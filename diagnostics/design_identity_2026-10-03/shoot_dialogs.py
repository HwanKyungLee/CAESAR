"""Open every Setup / Result Lab popup on a loaded FitSet + alphas and grab it.
    PYTHONIOENCODING=utf-8 python shoot_dialogs.py 1920 1080 1 fhd
Modal exec() is replaced by show + grab, so nothing blocks. Output: shots/dlg_<tag>_<name>.png
"""
import glob
import os
import sys


def main():
    sys.modules.setdefault("_wmi", None)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    W, H, SCALE, TAG = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
    os.environ["QT_SCALE_FACTOR"] = SCALE
    sys.path.insert(0, r"C:\GHL\CAESAR")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
    app = QApplication(sys.argv)
    from gui.theme import apply_augur
    apply_augur(app)
    FS = r"C:\Doasis_Work\Output\fit setting\FitSet_ANs[430-462nm_P4]_PNs[444-471nm_P3]_cold[438-476nm_P4]_Std.json"
    A = r"C:\Doasis_Work\Output\alpha\60s"
    files = (sorted(glob.glob(A + r"\hot\ch*\2026-05-20\*alpha_trace.dat"))[:6]
             + sorted(glob.glob(A + r"\cold\2026-05-20\*alpha_trace.dat"))[:3])
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (FS, ""))
    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: (files, ""))
    for n in ("information", "warning", "critical"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: print("MSG", n, a[1:3]) or QMessageBox.StandardButton.Ok))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    shots = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
    os.makedirs(shots, exist_ok=True)

    def pump(n=40):
        for _ in range(n):
            app.processEvents()

    def grab(dlg, name):
        dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        dlg.show()
        pump(60)
        # what the app does when the window gets focus (gui/theme.keep_windows_on_screen)
        if dlg.windowHandle() is not None:
            app.focusWindowChanged.emit(dlg.windowHandle())
            pump(30)
        fit = dlg.size()
        scr_w, scr_h = int(W / float(SCALE)), int(H / float(SCALE))
        over = fit.width() > scr_w or fit.height() > scr_h
        print(f"DLG {name}: {fit.width()}x{fit.height()} (screen {scr_w}x{scr_h})"
              + ("  ** LARGER THAN SCREEN **" if over else ""),
              "min", dlg.minimumSizeHint().width(), dlg.minimumSizeHint().height())
        dlg.grab().save(os.path.join(shots, f"dlg_{TAG}_{name}.png"))

    opened = []

    def fake_exec(self):
        grab(self, type(self).__name__)
        opened.append(self)
        return 0
    QDialog.exec = fake_exec

    from gui.app_window import CAESARAnalyzer
    w = CAESARAnalyzer()
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.resize(int(W / float(SCALE)), int(H / float(SCALE)))
    w.show()
    pump()
    w.load_scenario()
    pump()
    w._load_files()
    pump()
    for opener in (w.open_wavelength_calibration, w.open_reference_generator, w.open_r_trend_monitor,
                   w.open_alpha_generator):
        try:
            opener()
        except Exception as e:   # noqa: BLE001
            print("ERR", opener.__name__, type(e).__name__, e)
        pump()
    from gui.dlg_mission_export import open_mission_export
    try:
        open_mission_export(w)
    except Exception as e:       # noqa: BLE001
        print("ERR mission", type(e).__name__, e)
    before = set(QApplication.topLevelWidgets())
    w._open_test_fit_dialog()
    pump()
    for tw in set(QApplication.topLevelWidgets()) - before:
        if tw.isVisible() and isinstance(tw, QDialog):
            grab(tw, type(tw).__name__)
    rv = w.result_viewer
    rv._path = r"C:\Doasis_Work\Output\fitting\new\26yeosu\2026-05-18\fitting\260518_CH1_ANs_r96b76.dat"
    rv._reload()
    pump()
    try:
        rv._open_calculator()
    except Exception as e:       # noqa: BLE001
        print("ERR calculator", type(e).__name__, e)
    print("ok")


if __name__ == "__main__":
    main()
