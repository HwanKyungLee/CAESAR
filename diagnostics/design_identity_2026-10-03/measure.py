import os, sys
sys.modules.setdefault("_wmi", None)
os.environ["QT_QPA_PLATFORM"]="windows"; os.environ["QT_SCALE_FACTOR"]=sys.argv[1] if len(sys.argv)>1 else "1.5"
sys.path.insert(0, r"C:\GHL\CAESAR")
from PyQt6.QtWidgets import QApplication, QWidget, QLayout
app = QApplication(sys.argv)
from gui.theme import apply_augur; apply_augur(app)
from gui.app_window import CAESARAnalyzer
from PyQt6.QtCore import Qt
w = CAESARAnalyzer(); w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True); w.resize(910, 512); w.show()
for _ in range(10): app.processEvents()
lay = w._left_inner.layout()
print("left min", w._left_inner.minimumSizeHint().width(), "hint", w._left_inner.sizeHint().width())
for i in range(lay.count()):
    it = lay.itemAt(i)
    obj = it.widget() or it.layout()
    name = type(obj).__name__ + (" "+obj.title() if hasattr(obj,'title') and callable(obj.title) else "")
    print(f"{i:2d} {name[:40]:40s} min={it.minimumSize().width()} hint={it.sizeHint().width()}")
st = w.setup_tab
print("setup_tab min", st.minimumSizeHint().width(), st.minimumSizeHint().height())
lay = st.layout()
def walk(l, d=0):
    for i in range(l.count()):
        it = l.itemAt(i); o = it.widget() or it.layout()
        if o is None: continue
        print("  "*d, type(o).__name__, getattr(o,'title',lambda:'')() if hasattr(o,'title') and callable(o.title) else '', it.minimumSize().width(), it.minimumSize().height())
        if d < 2:
            sub = o if isinstance(o, QLayout) else o.layout()
            if sub: walk(sub, d+1)
walk(lay)
for name in ('result_viewer','plot_maker'):
    o = getattr(w, name); print(name, o.minimumSizeHint().width(), o.minimumSizeHint().height())
dt = w._diag_tabs
for i in range(dt.count()):
    pg_ = dt.widget(i); print("diag tab", dt.tabText(i), pg_.minimumSizeHint().width())
    l = pg_.layout()
    if l:
        for j in range(l.count()):
            it=l.itemAt(j); o=it.widget() or it.layout(); print("    ", type(o).__name__, it.minimumSize().width())
print("direction", w._setup_main_layout.direction(), "page w", w._tab_pages[w.setup_tab].width(), "setup min", w.setup_tab.minimumSizeHint().width(), "s", w._s)
print("diag grp min", w._setup_grp_viewer.minimumSizeHint().width(), "left cont min", w._setup_left_container.minimumSizeHint().width())
print("window min", w.minimumSizeHint().width(), "size", w.width())
for i in range(w.main_tabs.count()):
    print(" tab", w.main_tabs.tabText(i), w.main_tabs.widget(i).minimumSizeHint().width())
print(" plot maker tabs min", w.plot_maker._tabs.minimumWidth(), "right", w.plot_maker.pw.minimumSizeHint().width())
band = w.centralWidget().layout().itemAt(0).widget()
print("band_width", getattr(w, "_band_width", None)); print("band min", band.minimumSizeHint().width())
bl = band.layout()
for i in range(bl.count()):
    it = bl.itemAt(i); o = it.widget()
    print("   ", type(o).__name__ if o else "spacer", (o.text()[:30] if o and hasattr(o,'text') else ''), it.minimumSize().width())
print("splitter min", w._splitter.minimumSizeHint().width())
