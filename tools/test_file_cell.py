"""tools/test_file_cell.py
Results table File cell shows 'scan [row]' but every row lookup (replay, raw viewer, Set as I0)
must still get the full file name back (2026-10-03).
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QTableWidgetItem


def main():
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841 — items need an app
    from gui.app_window_results import ResultsQCMixin as M
    bad = 0
    for full, shown in (("2026-05-20-002_ANs_alpha_trace.dat [0042]", "002 [0042]"),
                        ("2026-05-20-002_ANs_alpha_trace.dat", "002"),
                        ("odd_name.dat", "odd_name.dat")):
        it = M._file_item(full)
        ok = it.text() == shown and M._file_cell_text(it) == full
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {full!r} → {it.text()!r}")
    plain = QTableWidgetItem("2026-05-20-001.dat")          # loaded-file row before a run
    ok = M._file_cell_text(plain) == "2026-05-20-001.dat"
    bad += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  plain cell falls back to its text")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
