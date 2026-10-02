# -*- coding: utf-8 -*-
"""DateLoadDialog list/label text (offscreen Qt, temp tree only — never a real fit folder)."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])


def _tree(base):
    for day in ("260520", "260521"):
        d = os.path.join(base, day, "neg_o", "QC_on")
        os.makedirs(d)
        with open(os.path.join(d, f"{day}_CH1.dat"), "w", encoding="utf-8") as f:
            f.write("Time\tNO2\n")


def test_list_text_and_write_location():
    from gui.dlg_date_load import DateLoadDialog
    with tempfile.TemporaryDirectory() as base:
        _tree(base)
        dlg = DateLoadDialog()
        dlg._ed_base.setText(base)
        dlg._rescan()
        txt = dlg._list.item(0).text()
        # R14: day count and save time were glued together ("2d10-02 04:42")
        assert " · 2d · saved " in txt, txt
        # R10: the merge is written into the chosen tree — the dialog must say where,
        # and scanning/opening must not write anything.
        assert os.path.join(base, "_derived") in dlg._lbl.text(), dlg._lbl.text()
        assert not os.path.exists(os.path.join(base, "_derived"))


if __name__ == "__main__":
    test_list_text_and_write_location()
    print("ok")
