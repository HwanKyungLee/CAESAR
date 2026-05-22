import sys, datetime as dt, numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from ui_dialogs import MonitorWidget
from engine import UniversalEngine

w = MonitorWidget(UniversalEngine())
w._r_dir_edit.setText(r'C:\Users\kh548\OneDrive\바탕 화면\여수 필드 준비')
w._r_load_all()

for ch in ["Cold", "Hot ANs", "Hot PNs"]:
    recs = w._r_data.get(ch, [])
    if not recs:
        print(f"{ch}: no data"); continue
    ts = [r[3] for r in recs]
    diffs = np.diff(ts) / 3600
    print(f"\n{ch}  ({len(recs)} files)")
    for r in recs[:2]:
        kst = dt.datetime.utcfromtimestamp(r[3]) + dt.timedelta(hours=9)
        print(f"  {r[0]}  -> {kst.strftime('%Y-%m-%d %H:%M KST')}")
    print("  ...")
    for r in recs[-1:]:
        kst = dt.datetime.utcfromtimestamp(r[3]) + dt.timedelta(hours=9)
        print(f"  {r[0]}  -> {kst.strftime('%Y-%m-%d %H:%M KST')}")
    print(f"  간격: 평균 {np.mean(diffs):.2f}h  최대 {np.max(diffs):.2f}h  최소 {np.min(diffs):.2f}h")
