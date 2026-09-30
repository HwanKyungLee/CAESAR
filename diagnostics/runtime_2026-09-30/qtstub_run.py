
import sys, types, runpy, time, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),'shim'))
from unittest import mock
for name in ["PyQt6","PyQt6.QtWidgets","PyQt6.QtCore","PyQt6.QtGui","pyqtgraph","pyqtgraph.Qt"]:
    m=mock.MagicMock(); m.__path__=[]; m.__all__=[]; sys.modules[name]=m
class _QObj: 
    def __init__(self,*a,**k): pass
sys.modules["PyQt6.QtCore"].QThread=_QObj; sys.modules["PyQt6.QtCore"].QObject=_QObj
sys.modules["PyQt6.QtCore"].pyqtSignal=lambda *a,**k: None
sys.path.insert(1, r'C:\GHL\CAESAR\tools'); sys.path.insert(2, r'C:\GHL\CAESAR')
import r_trend_monitor
script=sys.argv[1]; sys.argv=sys.argv[1:]
t0=time.perf_counter()
try:
    runpy.run_path(script, run_name="__main__")
finally:
    print(f"__WALL__ {time.perf_counter()-t0:.2f}", flush=True)
