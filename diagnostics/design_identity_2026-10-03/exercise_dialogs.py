"""Drive each popup's main action on real inputs (not just open it) and grab the result.
    PYTHONIOENCODING=utf-8 python exercise_dialogs.py <scratch_out_dir>
Outputs (alphas, references) go to <scratch_out_dir>; screenshots to shots/ex_<name>.png.
"""
import glob
import os
import sys
import time
import traceback


def main():
    sys.modules.setdefault("_wmi", None)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    OUT = sys.argv[1]
    os.makedirs(OUT, exist_ok=True)
    sys.path.insert(0, r"C:\GHL\CAESAR")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QTableWidgetItem
    app = QApplication(sys.argv)
    from gui.theme import apply_augur
    apply_augur(app)
    REF = r"C:\GHL\CAESAR\reference_data"
    FS = r"C:\Doasis_Work\Output\fit setting\FitSet_ANs[430-462nm_P4]_PNs[444-471nm_P3]_cold[438-476nm_P4]_Std.json"
    A = r"C:\Doasis_Work\Output\alpha\60s"
    RAW = r"E:\Yeosu_2026\CAESAR_Hot\2026-06\2026-06-01-003.dat"
    FIT = r"C:\Doasis_Work\Output\fitting\new\26yeosu\2026-05-18\fitting\260518_CH1_ANs_r96b76.dat"
    alphas = (sorted(glob.glob(A + r"\hot\ch*\2026-05-20\*alpha_trace.dat"))[:6]
              + sorted(glob.glob(A + r"\cold\2026-05-20\*alpha_trace.dat"))[:3])
    nxt = {"open": FS}
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (nxt["open"], ""))
    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: (alphas, ""))
    msgs = []
    for _n in ("information", "warning", "critical"):
        setattr(QMessageBox, _n, staticmethod(
            lambda *a, _n=_n, **k: msgs.append((_n, str(a[1]) if len(a) > 1 else "", str(a[2])[:160] if len(a) > 2 else ""))
            or QMessageBox.StandardButton.Ok))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.exec = lambda self: msgs.append(("box", self.windowTitle(), self.text()[:160])) or 0
    QDialog.exec = lambda self: 0                 # dialogs are shown non-modally below
    shots = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")

    def pump(n=40):
        for _ in range(n):
            app.processEvents()

    def wait(cond, sec):
        t0 = time.time()
        while time.time() - t0 < sec and not cond():
            pump(5)
            time.sleep(0.05)
        return cond()

    def show(dlg, name):
        dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        dlg.show()
        pump(60)
        dlg.grab().save(os.path.join(shots, f"ex_{name}.png"))

    def report(name, ok, detail):
        new = msgs[:]
        msgs.clear()
        out = sys.__stdout__           # the app tees/replaces sys.stdout while some dialogs run
        print(f"[{'OK ' if ok else 'BAD'}] {name}: {detail}", file=out)
        for m in new:
            print(f"      box: {m}", file=out)
        out.flush()

    from gui.app_window import CAESARAnalyzer
    w = CAESARAnalyzer()
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.resize(1920, 1080)
    w.show()
    pump()
    w.load_scenario(); pump()
    w._load_files(); pump()
    msgs.clear()

    def step(name, fn):
        try:
            fn()
        except Exception as e:      # noqa: BLE001
            report(name, False, f"{type(e).__name__}: {e}")
            traceback.print_exc(limit=3)

    # 1 Calculator
    def calc():
        from gui.dlg_calculator import CalculatorDialog
        d = CalculatorDialog(w, datasets=[FIT])
        d._var_rows[1][2].setCurrentText("NO2")
        d._expr.setText("B - A")
        d._compute(); pump()
        show(d, "calculator")
        r = getattr(d, "_result", None)
        report("Calculator B-A", r is not None and len(r[1]) > 0,
               f"{len(r[1]) if r else 0} values, msg='{d._msg.text()[:80]}'")
    step("calculator", calc)

    # 2 Test Fit: preview (built in __init__) + optimizer
    def testfit():
        from gui.test_fit_dialog import TestFitDialog
        d = TestFitDialog(w)
        d.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        d.show(); pump(60)
        tabs = d.findChild(type(w.main_tabs))
        if tabs is not None:
            tabs.setCurrentIndex(1); pump(40)
        d.grab().save(os.path.join(shots, "ex_testfit_preview.png"))
        d._run_optimizer()
        ok = wait(lambda: getattr(d, "_last_result", None) is not None, 300)
        if tabs is not None:
            tabs.setCurrentIndex(0); pump(40)
        d.grab().save(os.path.join(shots, "ex_testfit_optimizer.png"))
        res = getattr(d, "_last_result", None)
        report("Test Fit optimizer", ok and isinstance(res, dict) and "error" not in res,
               (str(res.get("error"))[:120] if isinstance(res, dict) and "error" in res
                else f"keys={list(res)[:6] if isinstance(res, dict) else res}"))
    step("testfit", testfit)

    # 3 Wavelength calibration: load lamp + auto peaks
    def wavecal():
        from gui.ui_dialogs_calib import WavelengthCalibrationDialog
        d = WavelengthCalibrationDialog(w)
        nxt["open"] = REF + r"\wv_cal\roi2\2026 April 03 13_20_24-Roi-2.csv"
        d.load_spectrum(); pump()
        d.find_peaks_auto(); pump()
        show(d, "wavecal")
        n = d.table.rowCount()
        report("Wavecal load + auto peaks", getattr(d, "spectrum", None) is not None and n > 0,
               f"spectrum={None if getattr(d, 'spectrum', None) is None else len(d.spectrum)} px, {n} peaks")
    step("wavecal", wavecal)

    # 4 Reference generator: NO2 raw → convolve to main wavecal with the roi FWHM profile
    def refgen():
        from gui.reference_generator_dialog import ReferenceGeneratorDialog
        from core.data_io import DataIO
        d = ReferenceGeneratorDialog(w, current_wavelengths=getattr(w, "wavelengths", None))
        rw, rd = DataIO.load_reference(REF + r"\raw\NO2_Vandaele(2002)_294K_384-725nm(vis-dilut5).txt")[:2]
        d.raw_wave, d.raw_data, d.gas_name = rw, rd, "NO2"
        d.load_fwhm_profile(REF + r"\wv_cal\roi2\FWHM_Analysis_20260619.txt"); pump()
        d.apply_convolution(); pump()
        show(d, "refgen")
        conv = [k for k in vars(d) if "conv" in k.lower() or "result" in k.lower() or "final" in k.lower()]
        report("Reference generator convolve", not any(m[0] in ("warning", "critical") for m in msgs),
               f"attrs={conv[:5]}")
    step("refgen", refgen)

    # 5 R Calibrator: channels from the left panel + Verify npz
    def rcal():
        from gui.ui_dialogs_r import RCalibratorDialog
        d = RCalibratorDialog(w)
        d._load_from_left_panel(); pump()
        d._verify_npz(); pump()
        show(d, "rcal")
        report("R Calibrator verify", True, f"{len(d._ch_rows)} rows, log tail='{d._log.toPlainText()[-160:]}'")
    step("rcal", rcal)

    # 6 Mission export: check blocks against a raw file, then collect()
    def mission():
        from gui.dlg_mission_export import MissionExportDialog
        d = MissionExportDialog(w, fitset_path=FS)
        d._check_raw(p=RAW); pump()
        show(d, "mission")
        try:
            d.collect()
            res = "collect() ok with defaults"
        except Exception as e:      # noqa: BLE001
            res = f"collect() refused defaults: {e}"
        # 2026-10-03: no default block — Check draws the unassigned blocks, collect() must refuse
        report("Mission check with raw", "choose the raw block" in res, res)
    step("mission", mission)

    # 7 Alpha generator on one raw file
    def alpha():
        from gui.ui_alpha_gen import AlphaGeneratorDialog
        d = AlphaGeneratorDialog(w)
        d._add([RAW]); pump()
        # operational R(t) — this raw hour has no He block, so alpha needs the campaign npz
        R = "C:/GHL/2026 yeosu/Output/R"
        d._ch_rt.update({1: R + "/R_CH1.npz", 2: R + "/R_CH2.npz"})
        d._out_dir = os.path.join(OUT, "alpha")
        done = {}
        orig = d._on_done
        d._on_done = lambda *a, **k: (done.setdefault("args", a), orig(*a, **k))
        show(d, "alpha_loaded")
        d._generate()
        ok = wait(lambda: "args" in done, 900)
        pump(40)
        d.grab().save(os.path.join(shots, "ex_alpha_done.png"))
        made = glob.glob(os.path.join(OUT, "alpha", "**", "*alpha_trace.dat"), recursive=True)
        report("Alpha generator", ok and bool(made), f"done={ok}, {len(made)} alpha file(s)")
    step("alpha", alpha)
    print("ok")


if __name__ == "__main__":
    main()
