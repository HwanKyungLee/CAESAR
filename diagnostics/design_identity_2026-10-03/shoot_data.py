import os, sys, glob, time
sys.modules.setdefault("_wmi", None)
os.environ["QT_QPA_PLATFORM"] = "windows"
def main():
    W, H, SCALE, TAG = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
    RUN = len(sys.argv) > 5 and sys.argv[5] == "run"
    os.environ["QT_SCALE_FACTOR"] = SCALE
    sys.path.insert(0, r"C:\GHL\CAESAR")
    from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
    from PyQt6.QtCore import Qt
    app = QApplication(sys.argv)
    from gui.theme import apply_augur; apply_augur(app)
    FS = r"C:\Doasis_Work\Output\fit setting\FitSet_ANs[430-462nm_P4]_PNs[444-471nm_P3]_cold[438-476nm_P4]_Std.json"
    A = r"C:\Doasis_Work\Output\alpha\60s"
    files = sorted(glob.glob(A + r"\hot\ch*\2026-05-20\*alpha_trace.dat"))[:6] + sorted(glob.glob(A + r"\cold\2026-05-20\*alpha_trace.dat"))[:3]
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (FS, ""))
    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: (files, ""))
    OUT = os.path.join(os.path.dirname(__file__), "scratch_out"); os.makedirs(OUT, exist_ok=True)
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(OUT, "x.dat"), ""))
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: OUT)
    for n in ("information", "warning", "critical"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.exec = lambda self: QMessageBox.StandardButton.Yes
    from PyQt6.QtWidgets import QDialog
    QDialog.exec = lambda self: 1
    from gui.app_window import CAESARAnalyzer
    w = CAESARAnalyzer()
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.resize(int(W / float(SCALE)), int(H / float(SCALE))); w.show()
    def pump(n=20):
        for _ in range(n): app.processEvents()
    pump()
    w.load_scenario(); pump()
    w._load_files(); pump()   # hot + cold picked together → auto-distributed to CH1 / CH3 (question → Yes)
    if RUN:
        w.chk_auto_save.setChecked(False)
        w.start_analysis(); t0 = time.time()
        while time.time() - t0 < 180:
            pump(5); time.sleep(0.05)
            if w.b_run.isEnabled() and w.results: break
        print("results", len(w.results), "in", round(time.time() - t0, 1), "s")
        pump(40)
    shots = os.path.join(os.path.dirname(__file__), "shots"); os.makedirs(shots, exist_ok=True)
    for i in range(w.main_tabs.count()):
        w.main_tabs.setCurrentIndex(i); pump(30)
        w.grab().save(os.path.join(shots, f"data_{TAG}_{i}_{w.main_tabs.tabText(i).replace(' ', '_')}.png"))
    if RUN:
        w.main_tabs.setCurrentIndex(1)
        for j in range(w.monitor.tabs.count()):
            w.monitor.tabs.setCurrentIndex(j); pump(30)
            w.grab().save(os.path.join(shots, f"data_{TAG}_mon{j}.png"))
    if os.environ.get("POLICY"):
        w.main_tabs.setCurrentIndex(0); w._toggle_shsq_table(); pump(30)
        w._left_scroll.widget().grab().save(os.path.join(shots, f"data_{TAG}_policy.png"))
    print("ok")


if __name__ == "__main__":
    main()
