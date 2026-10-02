import os, sys
sys.modules.setdefault("_wmi", None)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
W, H, SCALE, TAG = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
os.environ["QT_SCALE_FACTOR"] = SCALE
sys.path.insert(0, r"C:\GHL\CAESAR")
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from gui.theme import apply_augur
apply_augur(app)
from gui.app_window import CAESARAnalyzer
w = CAESARAnalyzer()
w.resize(int(W / float(SCALE)), int(H / float(SCALE)))
from PyQt6.QtCore import Qt
w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
w.show()
out = os.path.join(os.path.dirname(__file__), "shots")
os.makedirs(out, exist_ok=True)
for _ in range(20): app.processEvents()
for i in range(w.main_tabs.count()):
    w.main_tabs.setCurrentIndex(i)
    for _ in range(20): app.processEvents()
    name = w.main_tabs.tabText(i).replace(" ", "_")
    w.grab().save(os.path.join(out, f"augur_{TAG}_{i}_{name}.png"))
    print("saved", name)
