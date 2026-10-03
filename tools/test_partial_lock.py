"""tools/test_partial_lock.py
Lock with one reference row that fails to load must not read as locked: the window stays dirty,
says which reference failed, and Setup Status shows it (UI audit 2026-10-04 — it used to say
"N references locked" and fit without that gas).
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox


def main():
    app = QApplication.instance() or QApplication(sys.argv)   # noqa: F841
    boxes = []
    for n in ("information", "warning", "critical"):
        setattr(QMessageBox, n, staticmethod(lambda *a, _n=n, **k: boxes.append((_n, str(a[1]), str(a[2])))))
    from gui.app_window import CAESARAnalyzer
    w = CAESARAnalyzer()
    wl = np.linspace(400.0, 500.0, 2048)
    w.wavelengths = wl
    w.engine.wavelengths = wl
    d = tempfile.mkdtemp()
    good = os.path.join(d, "Ref_GOOD.dat")
    np.savetxt(good, np.column_stack([wl, 1e-19 * (1 + np.sin(wl / 3))]))
    bad = os.path.join(d, "Ref_BAD.dat")
    with open(bad, "w") as fh:
        print("not a reference", file=fh)
    w.add_ref_row("GOOD", good)
    w.add_ref_row("BAD", bad)
    bad_n = 0

    def check(name, ok, detail=""):
        nonlocal bad_n
        bad_n += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")

    w.lock_ref(silent=False)
    check("one good + one broken: engine has the good one", list(w.engine.gas_list) == ["GOOD"], w.engine.gas_list)
    check("but it is not reported as locked (stays dirty)", w._refs_dirty is True)
    check("the failure is named", w._refs_failed == ["BAD"] and any("BAD" in b[2] for b in boxes if b[0] == "warning"),
          boxes[-1:])
    w._refresh_setup_status()
    check("Setup Status says it failed", "BAD" in w.lbl_st_refs.text(), w.lbl_st_refs.text())
    w.del_ref(next(r for r in w.ref_widgets if r["n"].text() == "BAD")["w"])
    w.lock_ref(silent=True)
    check("after removing it, a full lock clears the state", w._refs_dirty is False and w._refs_failed == [])
    return 1 if bad_n else 0


if __name__ == "__main__":
    sys.exit(main())
