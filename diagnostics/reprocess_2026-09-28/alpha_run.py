
import os, sys, json, time, glob, types, io, contextlib
import numpy as np
ROOT=r"C:\GHL\CAESAR"; HERE=os.path.dirname(os.path.abspath(__file__))
sys.path[:0]=[HERE, ROOT, os.path.join(ROOT,"tools")]
from qtstub import install_qt_stub; install_qt_stub()
sys.modules.setdefault("core.window_designer", types.ModuleType("core.window_designer"))
from core.data_io import DataIO
from gui.worker import AlphaExportWorker
BASE=r"C:\GHL\2026 yeosu"
def run(ch, mode, rt, files, outdir, label, purge):
    if mode=="oldpair":
        DataIO._slot_identity=staticmethod(lambda lay, c, fp: None)
    rt=None if rt in ("none","None","") else rt
    wave=np.asarray(np.load(rt,allow_pickle=True)["wave_nm"] if rt else np.loadtxt(os.environ["WAVECAL"]).reshape(-1),float)
    logs=[]
    p0=int(os.environ.get('PXMIN',0)); p1=int(os.environ.get('PXMAX',2048))
    wk=AlphaExportWorker(files,p0,p1,wave[p0:p1],flag_za=[500],flag_he=[510],flag_amb=[1],rl_factor=1.0,cavity_len=51.8,
                         output_dir=outdir,channel=ch,avg_sec=60.0,purge_settle_sec=purge,channel_label=label,rt_path=rt)
    wk.use_parallel=False
    res={}
    wk.status_msg.connect(lambda s: logs.append(s)); wk.finished.connect(lambda s: res.setdefault("out",s))
    t0=time.time(); wk.run()
    open(os.path.join(outdir,f"_log_ch{ch}.txt"),"a",encoding="utf-8").write("\n".join(logs)+"\n")
    print("ch",ch,mode,len(files),"files ->",res.get("out"),"%.0fs"%(time.time()-t0),flush=True)
if __name__=="__main__":
    ch=int(sys.argv[1]); mode=sys.argv[2]; rt=sys.argv[3]; outdir=sys.argv[4]; purge=float(sys.argv[5]); pats=sys.argv[6:]
    files=sorted(sum([glob.glob(p) for p in pats],[]))
    os.makedirs(outdir,exist_ok=True)
    run(ch,mode,rt,files,outdir,os.environ.get("LABEL","ANs" if ch==1 else "PNs"),purge)
