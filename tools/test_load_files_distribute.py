"""tools/test_load_files_distribute.py
Load Data → Select Files with alphas of two labels (hot + cold picked together) must split them
over the channel tabs, like Load Entire Folder does. It used to put every file into the current
tab, so the cold alphas were fitted with CH1's settings and the Conc plot joined both series
(2026-10-03 — the 03:40 → 00:40 diagonal).
"""
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from gui.app_window import CAESARAnalyzer
    win = CAESARAnalyzer()
    win._add_channel_tab()                       # CH1 + CH2, labels empty → 'ch1' / 'ch2'
    tmp = tempfile.mkdtemp()
    files = []
    for ch in (1, 2):
        for scan in (1, 2):
            fp = os.path.join(tmp, f"2026-05-20-00{scan}_ch{ch}_alpha_trace.dat")
            with open(fp, "w", encoding="utf-8") as fh:
                fh.write(f"# channel={ch}  label=ch{ch}\n")
            files.append(fp)
    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: (files, ""))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    win._load_files()
    app.processEvents()
    got = {ch: sorted(os.path.basename(f) for f in win._channel_files.get(ch, [])) for ch in (1, 2)}
    want = {ch: sorted(os.path.basename(f) for f in files if f"_ch{ch}_" in f) for ch in (1, 2)}
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  Select Files splits labels over channel tabs  {got}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
