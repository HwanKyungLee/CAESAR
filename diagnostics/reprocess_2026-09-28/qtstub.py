
import sys, types
def install_qt_stub():
    if "PyQt6.QtCore" in sys.modules and getattr(sys.modules["PyQt6.QtCore"],"_is_stub",False): return
    class _Sig:
        def __init__(self,*a): self.cbs=[]
        def connect(self,f): self.cbs.append(f)
        def emit(self,*a):
            for f in self.cbs: f(*a)
    class pyqtSignal:
        def __init__(self,*a): self.name=None
        def __set_name__(self,owner,name): self.name="_sig_"+name
        def __get__(self,obj,owner):
            if obj is None: return self
            s=obj.__dict__.get(self.name)
            if s is None: s=obj.__dict__[self.name]=_Sig()
            return s
    class QThread:
        def __init__(self,*a,**k): pass
        def start(self): self.run()
        def wait(self,*a): return True
        def isRunning(self): return False
    class _Any:
        def __getattr__(self,n): return _Any()
        def __call__(self,*a,**k): return _Any()
    qc=types.ModuleType("PyQt6.QtCore"); qc._is_stub=True
    qc.QThread=QThread; qc.pyqtSignal=pyqtSignal; qc.Qt=_Any(); qc.QTimer=_Any; qc.QObject=object
    qw=types.ModuleType("PyQt6.QtWidgets"); qw.__all__=[]
    qg=types.ModuleType("PyQt6.QtGui"); qg.__all__=[]
    pk=types.ModuleType("PyQt6"); pk.QtCore=qc; pk.QtWidgets=qw; pk.QtGui=qg
    sys.modules.update({"PyQt6":pk,"PyQt6.QtCore":qc,"PyQt6.QtWidgets":qw,"PyQt6.QtGui":qg})
