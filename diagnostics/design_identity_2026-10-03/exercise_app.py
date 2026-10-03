"""Drive the rest of Augur/Vigil end to end on real inputs (UI audit 2026-10-04, items 2–7):
Plot Maker data + Publish, Result Lab kinds/folder/range/export/merge/stats, Setup small actions,
save flow, the popups' remaining steps, Vigil states. Every output goes to <tmp>.
    PYTHONIOENCODING=utf-8 python -u exercise_app.py <tmp>
Remembered folders (gui.dlg_dir) are redirected to <tmp>; restore HKCU\\Software\\CAESAR afterwards
if anything else wrote QSettings.
"""
import glob
import os
import shutil
import sys
import time
import traceback


def main():
    sys.modules.setdefault("_wmi", None)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    TMP = os.path.abspath(sys.argv[1])
    os.makedirs(TMP, exist_ok=True)
    sys.path.insert(0, r"C:\GHL\CAESAR")
    os.chdir(r"C:\GHL\CAESAR")
    errors = []
    sys.excepthook = lambda t, v, tb: errors.append("".join(traceback.format_exception(t, v, tb))[-500:])
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
    app = QApplication(sys.argv)
    from gui.theme import apply_augur
    apply_augur(app)
    out = sys.__stdout__
    shots = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")

    # ---- isolation: no dialogs, no remembered-folder writes ----
    import gui.dlg_dir as _dd
    _dd.dlg_dir = lambda key, save=None: TMP
    for modname in ("gui.ui_dialogs_calib", "gui.reference_generator_dialog", "gui.ui_result_viewer",
                    "gui.ui_alpha_gen", "gui.ui_plot_maker.widget"):
        try:
            mod = __import__(modname, fromlist=["x"])
            if hasattr(mod, "dlg_dir"):
                mod.dlg_dir = _dd.dlg_dir
        except Exception:      # noqa: BLE001
            pass
    nxt = {"open": None, "opens": None, "save": None, "dir": None}
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (nxt["open"] or "", ""))
    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: (nxt["opens"] or [], ""))
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (nxt["save"] or "", ""))
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: nxt["dir"] or "")
    msgs = []
    for _n in ("information", "warning", "critical"):
        setattr(QMessageBox, _n, staticmethod(
            lambda *a, _n=_n, **k: msgs.append((_n, str(a[1]) if len(a) > 1 else "", str(a[2])[:200] if len(a) > 2 else ""))
            or QMessageBox.StandardButton.Ok))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.exec = lambda self: msgs.append(("box", self.windowTitle(), self.text()[:200])) or 0
    QDialog.exec = lambda self: 1

    def pump(n=30):
        for _ in range(n):
            app.processEvents()

    def wait(cond, sec):
        t0 = time.time()
        while time.time() - t0 < sec and not cond():
            pump(5)
            time.sleep(0.05)
        return cond()

    results = []

    def report(name, ok, detail=""):
        new = msgs[:]
        msgs.clear()
        results.append((name, ok))
        print(f"[{'OK ' if ok else 'BAD'}] {name}: {detail}", file=out, flush=True)
        for m in new:
            print(f"      box: {m}", file=out, flush=True)

    def step(name, fn):
        only = os.environ.get("ONLY")      # e.g. ONLY=rcal,alpha — run a subset
        if only and name not in only.split(","):
            return
        try:
            fn()
        except Exception as e:      # noqa: BLE001
            report(name, False, f"{type(e).__name__}: {e}")
            print(traceback.format_exc(limit=4), file=out, flush=True)

    REF = r"C:\GHL\CAESAR\reference_data"
    FS = r"C:\Doasis_Work\Output\fit setting\FitSet_ANs[430-462nm_P4]_PNs[444-471nm_P3]_cold[438-476nm_P4]_Std.json"
    ALPHA = r"C:\Doasis_Work\Output\alpha\60s"
    FITDIR = r"C:\Doasis_Work\Output\fitting\new\26yeosu\2026-05-18\fitting"
    FIT = FITDIR + r"\260518_CH1_ANs_r96b76.dat"
    FIT2 = FITDIR + r"\260518_CH2_PNs_r03854.dat"
    RTREND = r"C:\Doasis_Work\Output\R\CH1_R_trend.dat"
    RCURVE = r"C:\Doasis_Work\Output\R\R_CH1\2026-05-18\2026-05-18-001_R.dat"
    CONC = r"C:\Doasis_Work\Output\ANs_chfix_20260927\SigmaANs_60s_chfix_20260927.csv"
    MERGED = r"C:\Doasis_Work\Output\fitting\_derived\260603-260608\neg_o\QCoff\ANs_430-466nm_Poly4_ShLink_merge6_260603-260608.dat"
    XSEC = REF + r"\raw\NO2_Vandaele(2002)_294K_384-725nm(vis-dilut5).txt"
    RAWS = [r"E:\Yeosu_2026\CAESAR_Hot\2026-06\2026-06-01-00%d.dat" % i for i in (1, 2)]
    alphas = (sorted(glob.glob(ALPHA + r"\hot\ch*\2026-05-20\*alpha_trace.dat"))[:4]
              + sorted(glob.glob(ALPHA + r"\cold\2026-05-20\*alpha_trace.dat"))[:2])

    from gui.app_window import CAESARAnalyzer
    w = CAESARAnalyzer()
    w._dlg_dir = lambda key, save=None: TMP
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.resize(1920, 1080)
    w.show()
    pump()
    nxt["open"] = FS
    w.load_scenario(); pump()
    nxt["opens"] = alphas
    w._load_files(); pump()
    msgs.clear()

    # ===== 2. Plot Maker =====
    def plotmaker():
        import matplotlib as mpl
        pm = w.plot_maker
        n = pm.add_specs([FIT, FIT2]); pump()
        ts = next(m for m in pm._modes if m.key == "timeseries")
        names = list(pm.shelf)
        ts.on_column_activated(f"{names[0]}:NO2")
        ts.on_column_activated(f"{names[1]}:NO2")
        pm._mode.render(); pump(60)
        w.main_tabs.setCurrentWidget(w._tab_pages[pm]); pump(40)
        w.grab().save(os.path.join(shots, "app_plotmaker.png"))
        fig = pm._build_publish_fig()
        png = os.path.join(TMP, "publish.png")
        fig.savefig(png, dpi=pm._dpi_spin.value(), bbox_inches="tight")
        fig.savefig(os.path.join(TMP, "publish.pdf"), bbox_inches="tight")
        shutil.copy(png, os.path.join(shots, "app_publish.png"))
        rc_ok = mpl.rcParams["figure.facecolor"] in ("white", "#ffffff", (1, 1, 1, 1)) and \
            mpl.rcParams["axes.facecolor"] in ("white", "#ffffff", (1, 1, 1, 1))
        report("Plot Maker add + series + Publish", n == 2 and os.path.getsize(png) > 10000 and rc_ok,
               f"added {n}, series={len(ts._series)}, png {os.path.getsize(png)//1024} KB, "
               f"rcParams untouched={rc_ok}, warnings={pm._publish_warnings[:2]}")
    step("plotmaker", plotmaker)

    # ===== 3. Result Lab =====
    rv = w.result_viewer

    def rl_kinds():
        w.main_tabs.setCurrentWidget(w._tab_pages[rv]); pump()
        bad = []
        for label, path, force in (("R trend", RTREND, None), ("R curve", RCURVE, None),
                                   ("alpha", alphas[0], None), ("reference", XSEC, "Reference"),
                                   ("concentration", CONC, None), ("merged fit", MERGED, None)):
            if not os.path.exists(path):
                bad.append(f"{label}: missing input")
                continue
            rv._combo.blockSignals(True)
            rv._combo.setCurrentText(force or "Auto")
            rv._combo.blockSignals(False)
            rv._path = path
            rv._reload(); pump(40)
            txt = rv._lbl.text()
            w.grab().save(os.path.join(shots, f"app_rl_{label.replace(' ', '_')}.png"))
            if txt.startswith("Failed"):
                bad.append(f"{label}: {txt[:100]}")
            print(f"      {label}: kind={getattr(rv, '_current_kind', '?')} '{txt[:90]}'", file=out)
        rv._combo.setCurrentText("Auto")
        report("Result Lab non-fit kinds", not bad, "; ".join(bad) or "all displayed")
    step("rl_kinds", rl_kinds)

    def rl_folder_range_export():
        rv._browse_dir(FITDIR); pump()
        items = [rv._list.item(i) for i in range(rv._list.count())]
        files = [it for it in items if isinstance(it.data(Qt.ItemDataRole.UserRole), tuple)
                 and it.data(Qt.ItemDataRole.UserRole)[0] == "file"]
        rv._on_list_item(files[0]); pump(40)
        # range: middle half of the day
        t = rv._fit_cache.get("time") if rv._fit_cache else None
        import numpy as np
        tt = np.asarray(t, float) if t is not None else None
        rv._btn_region.setChecked(True); pump()
        if tt is not None and len(tt):
            a, b = tt[len(tt) // 4], tt[3 * len(tt) // 4]
            rv._set_range_edits(a, b, block=False); rv._on_range_edited(); pump()
        nxt["save"] = os.path.join(TMP, "rl_export.dat")
        rv._export_region(); pump()
        exp_ok = os.path.exists(nxt["save"])
        stats = rv._stats_lines()
        for it in files[:2]:
            it.setSelected(True)
        nxt["save"] = os.path.join(TMP, "rl_merge.dat")
        rv._merge_files(); pump()
        merge_ok = os.path.exists(nxt["save"])
        npng = rv._save_png(os.path.join(TMP, "rl.png"))
        rv._to_plot_maker(); pump()
        w.grab().save(os.path.join(shots, "app_rl_range.png"))
        report("Result Lab folder/range/export/merge/stats/png/to-PlotMaker",
               len(files) >= 2 and exp_ok and merge_ok and bool(stats) and npng,
               f"{len(files)} files listed, export={exp_ok}, merge={merge_ok}, stats lines={len(stats or [])}, png plots={npng}")
    step("rl_folder", rl_folder_range_export)

    # ===== 4. Setup small actions =====
    def setup_actions():
        w.main_tabs.setCurrentIndex(0); pump()
        n0 = len(w.ref_widgets)
        bad = os.path.join(TMP, "broken_ref.dat")
        with open(bad, "w") as fh:
            print("not a reference", file=fh)
        w.add_ref_row("BAD", bad); pump()
        added = len(w.ref_widgets) == n0 + 1
        dirty = bool(getattr(w, "_refs_dirty", False))
        w.lock_ref(silent=False); pump()
        partial_dirty = bool(w._refs_dirty)
        gases = list(w.engine.gas_list)
        print(f"      partial lock: gases={gases} dirty_after={partial_dirty} boxes={msgs[-1:] }", file=out)
        w.del_ref(w.ref_widgets[-1]["w"]); pump()
        w.lock_ref(silent=True); pump()
        locked = w.engine.is_engine_ready() and not w._refs_dirty
        w._set_params_visible(True); pump()
        w._toggle_shsq_table(); pump()
        tbl = w.tbl_shsq.isVisible()
        w._toggle_shsq_table(); pump()
        nch = len(w._channel_configs)
        w._add_channel_tab(); pump()
        added_ch = len(w._channel_configs) == nch + 1
        w._del_channel_tab(); pump()
        back = len(w._channel_configs) == nch
        w._channel_tabbar.setCurrentIndex(0); pump()
        w.open_selector(); pump(40)
        sel = getattr(w, "sel_dlg", None)
        if sel is not None:
            sel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True); sel.show(); pump(40)
            sel.grab().save(os.path.join(shots, "app_vis.png"))
            sel.hide()
        w._refresh_setup_status(); pump()
        w.grab().save(os.path.join(shots, "app_setup_after.png"))
        report("Setup add-ref/lock/policy/channel tabs/Vis/status",
               added and dirty and locked and tbl and added_ch and back and sel is not None,
               f"add={added} dirty={dirty} locked={locked} policy-table={tbl} tab+={added_ch} tab-={back} vis={sel is not None}")
        report("Partial lock (1 of 4 refs broken) is not reported as locked", partial_dirty,
               f"after lock: dirty={partial_dirty}, engine gases={gases}")
    step("setup", setup_actions)

    # ===== 5. Run + save =====
    def run_save():
        w.chk_auto_save.setChecked(False)
        w.cb_display_mode.setCurrentIndex(0)
        w._skip_run_confirm = True
        w.start_analysis()
        ok = wait(lambda: w.b_run.isEnabled() and bool(w.results), 300)
        pump(40)
        w.save(auto=True); pump()
        files = glob.glob(os.path.join(TMP, "**", "fitting", "*.dat"), recursive=True)
        metas = glob.glob(os.path.join(TMP, "**", "fitting", "*.meta.json"), recursive=True)
        head = open(files[0], encoding="utf-8", errors="replace").read(600) if files else ""
        report("Fast run + Save", ok and files and metas and "Augur" in head,
               f"{len(w.results)} results, {len(files)} .dat, {len(metas)} .meta.json, header '{head.splitlines()[0][:60] if head else ''}'")
    step("save", run_save)

    # ===== 6. Popup remaining steps =====
    def wavecal_fit_save():
        import numpy as np
        from PyQt6.QtWidgets import QTableWidgetItem
        from gui.ui_dialogs_calib import WavelengthCalibrationDialog
        cal = np.loadtxt(REF + r"\wv_cal\roi2\Calib_20260619_Hg_400-499nm_Poly2.txt")
        d = WavelengthCalibrationDialog(w)
        d.show_fit_result_popup = lambda *a, **k: None
        nxt["open"] = REF + r"\wv_cal\roi2\2026 April 03 13_20_24-Roi-2.csv"
        d.load_spectrum(); d.find_peaks_auto(); pump()
        # the person adds the third peak by hand: local max around px 160
        sp = np.asarray(d.spectrum, float)
        p3 = 140 + int(np.argmax(sp[140:180]))
        r = d.table.rowCount(); d.table.insertRow(r); d.table.setItem(r, 0, QTableWidgetItem(str(p3)))
        for i in range(d.table.rowCount()):
            px = float(d.table.item(i, 0).text())
            d.table.setItem(i, 1, QTableWidgetItem(f"{float(np.interp(px, np.arange(len(cal)), cal)):.3f}"))
        d.fit_calibration(); pump()
        nxt["save"] = os.path.join(TMP, "Calib_test.txt")
        got = []
        d.calibration_finished.connect(lambda a: got.append(len(a)))
        d.save_and_apply(); pump()
        report("Wavecal 3 peaks → fit → save", os.path.exists(nxt["save"]) and bool(got),
               f"pairs={d.table.rowCount()}, help='{d.help_label.text()[:80]}', saved={os.path.exists(nxt['save'])}")
    step("wavecal", wavecal_fit_save)

    def refgen_save():
        from gui.reference_generator_dialog import ReferenceGeneratorDialog
        from core.data_io import DataIO
        d = ReferenceGeneratorDialog(w, current_wavelengths=w.wavelengths)
        rw, rd = DataIO.load_reference(XSEC)[:2]
        d.raw_wave, d.raw_data, d.gas_name = rw, rd, "NO2"
        d.load_fwhm_profile(REF + r"\wv_cal\roi2\FWHM_Analysis_20260619.txt")
        d.apply_convolution(); pump()
        got = []
        d.reference_saved.connect(lambda g, f: got.append((g, f)))
        nxt["save"] = os.path.join(TMP, "Ref_NO2_test.dat")
        d.save_reference(); pump()
        report("RefGen convolve → save → signal", os.path.exists(nxt["save"]) and bool(got), f"signal={got[:1]}")
    step("refgen", refgen_save)

    def mission_build():
        from gui.dlg_mission_export import MissionExportDialog
        d = MissionExportDialog(w, fitset_path=FS)
        t = d.table
        plan = {0: ("ch1", "ANs"), 1: ("ch2", "PNs")}
        for r in range(t.rowCount()):
            if r not in plan:
                t.cellWidget(r, 0).setChecked(False)
                continue
            blk, name = plan[r]
            t.cellWidget(r, 3).setCurrentIndex(t.cellWidget(r, 3).findData(blk))
            t.cellWidget(r, 4).setText(name)
            for c in (5, 6):
                cb = t.cellWidget(r, c)
                if cb.currentData() is None:
                    cb.setCurrentIndex(1)
        d._check_raw(p=RAWS[0]); pump()
        show_ok = True
        d.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True); d.show(); pump(40)
        d.grab().save(os.path.join(shots, "app_mission_filled.png"))
        ms = d.collect()
        man = d.build(os.path.join(TMP, "mission_pkg"))
        report("Mission fill → check → collect → build", bool(ms) and bool(man) and show_ok,
               f"{len(ms)} mission(s), checks='{t.cellWidget(0, 9).text()[:70]}'")
    step("mission", mission_build)

    def rcal_run():
        from gui.ui_dialogs_r import RCalibratorDialog
        rawdir = os.path.join(TMP, "raw_hot")
        os.makedirs(rawdir, exist_ok=True)
        for p in RAWS:
            if not os.path.exists(os.path.join(rawdir, os.path.basename(p))):
                shutil.copy(p, rawdir)
        d = RCalibratorDialog(w)
        d._load_from_left_panel(); pump()
        rows = list(d._ch_rows)
        for i, fr in enumerate(rows):
            fr.le_raw_dir.setText(rawdir if i < 2 else "")
        d._le_out_dir.setText(os.path.join(TMP, "rcal"))
        d._run(); pump()
        ok = wait(lambda: getattr(d, "_worker", None) is not None and not d._worker.isRunning(), 900)
        pump(60)
        d.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True); d.show(); pump(40)
        d.grab().save(os.path.join(shots, "app_rcal_done.png"))
        npz = glob.glob(os.path.join(TMP, "rcal", "**", "*.npz"), recursive=True)
        report("R Calibrator Start on 2 raw files", ok and bool(npz),
               f"npz={[os.path.basename(x) for x in npz]}, log tail='{d._log.toPlainText()[-120:]}'")
    step("rcal", rcal_run)

    def alpha_folder():
        from gui.ui_alpha_gen import AlphaGeneratorDialog
        d = AlphaGeneratorDialog(w)
        nxt["dir"] = os.path.join(TMP, "raw_hot")
        w._pick_dates = lambda ds: set(ds)
        d._pick_folder(); pump()
        R = "C:/GHL/2026 yeosu/Output/R"
        d._ch_rt.update({1: R + "/R_CH1.npz", 2: R + "/R_CH2.npz"})
        d._out_dir = os.path.join(TMP, "alpha_folder")
        done = {}
        orig = d._on_done
        d._on_done = lambda *a, **k: (done.setdefault("a", a), orig(*a, **k))
        if os.environ.get("CPU"):
            from core.parallel import set_max_workers
            set_max_workers(int(os.environ["CPU"]))
        _amsg = []
        _orig_st = w._alpha_status
        w._alpha_status = lambda m, _o=_orig_st: (_amsg.append(m), _o(m))
        d._generate()
        ok = wait(lambda: "a" in done, 1200)
        for m in _amsg:
            if any(k in m for k in ("Pass 2", "Done:", "failed", "fallback", "TEMP-DEBUG")):
                print("      alpha status:", m[:180], file=out, flush=True)
        made = glob.glob(os.path.join(TMP, "alpha_folder", "**", "*alpha_trace.dat"), recursive=True)
        report("Alpha from a folder (2 raw files)", ok and len(made) >= 2, f"{len(made)} alpha file(s)")
    step("alpha", alpha_folder)

    # ===== 7. Vigil =====
    def vigil():
        from datetime import datetime, timedelta
        from gui.theme import apply_vigil
        apply_vigil(app)       # last step: Vigil's own night theme, as run_vigil does (Augur's was on)
        from vigil.dashboard.dashboard_window import DashboardWindow
        from vigil.run_vigil import VigilApp, DEFAULT_PROFILE_DIR
        from vigil.alert_engine import P0
        raw = os.path.join(TMP, "vigil_raw")
        os.makedirs(raw, exist_ok=True)
        dst = os.path.join(raw, os.path.basename(RAWS[0]))
        shutil.copy(RAWS[0], dst)
        os.utime(dst, None)
        win = DashboardWindow()
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        win.resize(1920, 1080); win.show()
        core = VigilApp(raw, DEFAULT_PROFILE_DIR, os.path.join(TMP, "vigil_state"), dashboard=win)
        win.set_watch_dir(raw)
        win.run_toggled.connect(lambda r: core.resume() if r else core.pause())
        for _ in range(8):
            core.tick(); pump(20)
        win.grab().save(os.path.join(shots, "app_vigil_data.png"))
        live = win.badge.text()[:80]
        win._toggle_run(); pump(); core.tick(); pump()
        paused = "PAUSED" in win.badge.text()
        win.grab().save(os.path.join(shots, "app_vigil_paused.png"))
        win._toggle_run(); pump()
        win.set_results([("liveness", P0, "No new raw row for 65 min — measurement stopped?", {})])
        win.set_status(P0, "No new raw row for 65 min")
        pump(30)
        win.grab().save(os.path.join(shots, "app_vigil_p0.png"))
        p0 = "P0" in win.badge.text()
        pkg = os.path.join(TMP, "mission_pkg")
        mis = None
        if os.path.isdir(pkg):
            try:
                mis = core.load_mission(pkg)
            except Exception as e:      # noqa: BLE001
                mis = f"refused: {e}"
        core.set_data_root(r"C:\GHL\2026 yeosu\Output"); win.set_data_root(r"C:\GHL\2026 yeosu\Output")
        for _ in range(3):
            core.tick(); pump(20)
        win.grab().save(os.path.join(shots, "app_vigil_mission.png"))
        report("Vigil live/pause/P0/mission/data root", paused and p0,
               f"live badge='{live}', paused={paused}, p0={p0}, mission={str(mis)[:80]}")
    step("vigil", vigil)

    print("SUMMARY", sum(ok for _n, ok in results), "/", len(results), "OK", file=out)
    print("QT SLOT EXCEPTIONS", len(errors), file=out)
    for e in errors[:6]:
        print("----\n" + e, file=out)
    out.flush()
    os._exit(0)    # skip Qt teardown (worker threads) — results are printed


if __name__ == "__main__":
    main()
