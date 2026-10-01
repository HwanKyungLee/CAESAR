"""tools/test_ref_policy_panel.py
The main-window Reference policy table is the only ref_props editor (the Properties
popup button was removed 2026-10-01). Check that what a user edits there is what
the fitter actually receives:

  1. table starts collapsed, toggle opens it
  2. untouched table (ref_props == {}) fits with the same bounds the table displays
  3. edits via real widget signals land in win.ref_props
  4. AnalysisWorker(ref_properties=win.ref_props) builds the edited fixed/linked/bounds,
     T correction and active bands
  5. channel scenario save/restore and Test Fit apply both round-trip into the table
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

GASES = ["NO2", "O4", "H2O", "CHOCHO"]


def _type(line_edit, text):
    """Type like a user: select all, type, Enter -> editingFinished."""
    line_edit.setFocus()
    line_edit.selectAll()
    QTest.keyClicks(line_edit, text)
    QTest.keyClick(line_edit, Qt.Key.Key_Return)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from gui.app_window import CAESARAnalyzer
    from gui.worker import AnalysisWorker

    win = CAESARAnalyzer()
    win.engine.gas_list = list(GASES)
    win._refresh_shsq_summary()
    tbl = win.tbl_shsq

    # 1. collapsed by default
    assert win._shsq_table_visible is False and tbl.isHidden()
    assert win._btn_shsq_tbl.text().startswith("▶")
    win._toggle_shsq_table()
    assert win._shsq_table_visible is True and not tbl.isHidden()
    print("  PASS  collapsed by default, toggle opens")

    # 2. untouched: worker defaults == what the table shows
    assert win.ref_props == {}
    def setup(rp):
        w = AnalysisWorker(win.engine, [], 0, 10, [0.0, 1.0], ([-1, 0], [1, 2]), 1,
                           ref_properties=rp)
        w.step_limit = 5.0
        return w._setup_fit_parameters(0.0, [0.0, 1.0])
    assert setup({}) == setup(tbl.get_properties()), "table defaults != fitter defaults"
    print("  PASS  untouched table == fitter defaults")

    # 3. edit through real widget signals
    pw = tbl.param_widgets
    _type(pw["NO2"]["sh_lim"], "-1.2, 0.8")
    pw["O4"]["sh_cmb"].setCurrentText("Link");  pw["O4"]["sh_lnk"].setCurrentText("NO2")
    pw["H2O"]["sh_cmb"].setCurrentText("Fix");  _type(pw["H2O"]["sh_fix"], "0.25")
    pw["CHOCHO"]["sq_cmb"].setCurrentText("Limit"); _type(pw["CHOCHO"]["sq_lim"], "-0.02, 0.03")
    pw["O4"]["t_ref_spin"].setValue(20.0)
    pw["O4"]["t_coeff_spin"].setValue(0.5)
    _type(pw["O4"]["bands_edit"], "460,495")

    rp = win.ref_props
    assert rp["NO2"]["sh_mode"] == "Limit" and rp["NO2"]["sh_val"] == "-1.2, 0.8", rp["NO2"]
    assert rp["O4"]["sh_mode"] == "Link" and rp["O4"]["sh_val"] == "NO2", rp["O4"]
    assert rp["H2O"]["sh_mode"] == "Fix" and rp["H2O"]["sh_val"] == "0.25", rp["H2O"]
    assert rp["CHOCHO"]["sq_mode"] == "Limit" and rp["CHOCHO"]["sq_val"] == "-0.02, 0.03"
    assert rp["O4"]["t_ref"] == 20.0 and rp["O4"]["t_coeff"] == 0.5
    assert rp["O4"]["active_bands_nm"] == "460,495"
    assert "NO2 Sh[-1.2,0.8]" in win.lbl_shsq.text(), win.lbl_shsq.text()
    print("  PASS  widget edits -> win.ref_props + summary line")

    # 4. what the fitter builds from it
    active, fixed, linked, th0, lb, ub = setup(rp)
    i = active.index("NO2_sh")
    assert (lb[i], ub[i]) == (-1.2, 0.8), (lb[i], ub[i])
    assert linked["O4_sh"] == "NO2_sh"
    assert fixed["H2O_sh"] == 0.25
    j = active.index("CHOCHO_sq")
    assert np.allclose((lb[j], ub[j]), (0.98, 1.03)), (lb[j], ub[j])
    assert "H2O_sh" not in active and "O4_sh" not in active
    w = AnalysisWorker(win.engine, [], 0, 10, [0.0, 1.0], ([-1, 0], [1, 2]), 1,
                       ref_properties=rp)
    win.engine.pixel_to_wavelength = lambda px: np.linspace(400, 500, len(px))
    assert w._gas_active_in_window("O4", np.arange(11)) is True
    win.engine.pixel_to_wavelength = lambda px: np.linspace(400, 450, len(px))
    assert w._gas_active_in_window("O4", np.arange(11)) is False
    assert w._gas_active_in_window("NO2", np.arange(11)) is True     # no bands = always on
    print("  PASS  active bands honoured by worker")
    print("  PASS  fitter receives edited Limit/Link/Fix/squeeze")

    # 5a. scenario save/restore round-trip
    snap = win._capture_config() if hasattr(win, "_capture_config") else None
    if snap and "ref_props" in snap:
        win.ref_props = {}
        win._refresh_shsq_summary()
        assert tbl.get_properties()["H2O"]["sh_mode"] == "Limit"
        win.ref_props = dict(snap["ref_props"])
        win._refresh_shsq_summary()
        assert tbl.get_properties() == rp, "table not rebuilt from restored ref_props"
        print("  PASS  scenario ref_props -> table rebuild")

    # 5b. Test Fit [Apply] -> table
    new = dict(rp["NO2"]); new.update(sh_mode="Center", sh_val="-5.25, 0.3")
    win._apply_test_fit_recommendations({"proposed_ref_props": {"NO2": new},
                                         "proposed_poly_deg": win.spin_poly_deg.value()})
    got = tbl.get_properties()["NO2"]
    assert got["sh_mode"] == "Center" and got["sh_val"] == "-5.25, 0.3", got
    assert win.ref_props["NO2"]["sh_mode"] == "Center"
    print("  PASS  Test Fit apply -> table + ref_props")

    win.close()
    print("ref policy panel self-check OK")


if __name__ == "__main__":
    main()
