import os, sys, shutil, tempfile, time


def main():
    sys.modules.setdefault("_wmi", None)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    W, H, SCALE, TAG = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
    os.environ["QT_SCALE_FACTOR"] = SCALE
    sys.path.insert(0, r"C:\GHL\CAESAR")
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    app = QApplication(sys.argv[:1])
    from gui.theme import apply_vigil; apply_vigil(app)
    from vigil.dashboard.dashboard_window import DashboardWindow
    from vigil.run_vigil import VigilApp
    from vigil.profile import DEFAULT_PROFILE_DIR
    base = os.path.join(tempfile.gettempdir(), "ux3_vigil"); raw = os.path.join(base, "raw"); st = os.path.join(base, "st")
    shutil.rmtree(base, ignore_errors=True); os.makedirs(raw); os.makedirs(st)
    if len(sys.argv) > 5:
        for src in sys.argv[5:]:
            shutil.copy(src, raw)
    win = DashboardWindow()
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.resize(int(W / float(SCALE)), int(H / float(SCALE))); win.show()
    core = VigilApp(raw if len(sys.argv) > 5 else None, DEFAULT_PROFILE_DIR, st, dashboard=win)
    for w_ in core.profile_warnings: win.log_line(f"WARNING: {w_}")
    win.set_watch_dir(None)
    if len(sys.argv) > 5:
        win.set_watch_dir(raw)
        for _ in range(60):
            core.tick(); app.processEvents()
    if os.environ.get("ALARM"):
        win.set_results([("hk:2026-06-01-003.dat", "P1", "ANs cavity P=1012.0 mbar out of band", {})])
        win.set_status("P1", "P1 x1 - quality at risk")
    for _ in range(30): app.processEvents()
    out = os.path.join(os.path.dirname(__file__), "shots"); os.makedirs(out, exist_ok=True)
    win.grab().save(os.path.join(out, f"vigil_{TAG}{'_alarm' if os.environ.get('ALARM') else ''}.png")); print("ok")


if __name__ == "__main__":
    main()
