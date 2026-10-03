"""Step-mode run: grab the monitor tabs mid-run and after, collect any Python exception raised in a
Qt slot (sys.excepthook) — Fast mode was the only run exercised before.
    PYTHONIOENCODING=utf-8 python exercise_step.py
"""
import glob
import os
import sys
import time
import traceback


def main():
    sys.modules.setdefault("_wmi", None)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    sys.path.insert(0, r"C:\GHL\CAESAR")
    errors = []
    sys.excepthook = lambda t, v, tb: errors.append("".join(traceback.format_exception(t, v, tb))[-600:])
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
    app = QApplication(sys.argv)
    from gui.theme import apply_augur
    apply_augur(app)
    FS = r"C:\Doasis_Work\Output\fit setting\FitSet_ANs[430-462nm_P4]_PNs[444-471nm_P3]_cold[438-476nm_P4]_Std.json"
    A = r"C:\Doasis_Work\Output\alpha\60s"
    files = (sorted(glob.glob(A + r"\hot\ch*\2026-05-20\*alpha_trace.dat"))[:3]
             + sorted(glob.glob(A + r"\cold\2026-05-20\*alpha_trace.dat"))[:2])
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (FS, ""))
    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: (files, ""))
    for n in ("information", "warning", "critical"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    from PyQt6.QtWidgets import QDialog
    boxes = []
    shots = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
    QMessageBox.exec = lambda self: boxes.append((self.windowTitle(), self.text()[:120])) or 0
    def _accept(self):          # grab the dialog (e.g. 'Start with these settings?'), then accept
        from PyQt6.QtCore import Qt as _Qt
        self.setAttribute(_Qt.WidgetAttribute.WA_DontShowOnScreen, True); self.show()
        for _ in range(30): app.processEvents()
        self.grab().save(os.path.join(shots, f'step_dialog_{len(boxes)}.png'))
        boxes.append((self.windowTitle(), type(self).__name__)); self.hide()
        return 1
    QDialog.exec = _accept
    out = sys.__stdout__

    def pump(n=20):
        for _ in range(n):
            app.processEvents()
    from gui.app_window import CAESARAnalyzer
    w = CAESARAnalyzer()
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.resize(1920, 1080)
    w.show()
    pump()
    w.load_scenario(); pump()
    w._load_files(); pump()
    w.chk_auto_save.setChecked(False)
    w.cb_display_mode.setCurrentIndex(1)           # Step
    w.spin_step_delay.setValue(0)
    w.main_tabs.setCurrentIndex(1)
    m = w.monitor
    w.start_analysis()
    t0, mid = time.time(), False
    while time.time() - t0 < 300:
        pump(5)
        time.sleep(0.02)
        if not mid and len(w.results) >= 40:
            mid = True
            for j in range(m.tabs.count()):
                m.tabs.setCurrentIndex(j); pump(20)
                w.grab().save(os.path.join(shots, f"step_mid_{j}.png"))
            print("MID results", len(w.results), "legend conc",
                  [[l.text for _s, l in m._conc_plots[g].legend.items] for g in m._conc_gases][:1], file=out)
        if w.b_run.isEnabled() and w.results:
            break
    pump(60)
    print("DONE results", len(w.results), "in", round(time.time() - t0, 1), "s", file=out)
    for j in range(m.tabs.count()):
        m.tabs.setCurrentIndex(j); pump(30)
        w.grab().save(os.path.join(shots, f"step_end_{j}.png"))
    print("legend trend", [l.text for _s, l in m.p_sh.legend.items], file=out)
    print("MODALS", boxes[:8], file=out)
    print("EXCEPTIONS", len(errors), file=out)
    for e in errors[:5]:
        print("----\n" + e, file=out)
    print("ok", file=out)


if __name__ == "__main__":
    main()
