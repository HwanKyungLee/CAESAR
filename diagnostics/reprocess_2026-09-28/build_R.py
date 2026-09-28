
import os, sys, json, time, io, contextlib, types
import numpy as np
ROOT=r"C:\GHL\CAESAR"; HERE=os.path.dirname(os.path.abspath(__file__))
sys.path[:0]=[HERE, ROOT, os.path.join(ROOT,"tools")]
sys.modules.setdefault("core.window_designer", types.ModuleType("core.window_designer"))
from core.data_io import DataIO
import rt_precompute as RP
RP._RT.RL_FACTOR=1.0   # operational R Calibrator setting (GUI rl_factor=1.0); headless default is 0.933
BASE=r"C:\GHL\2026 yeosu"
def main(ch, mode, out, nfiles=None):
    if mode=="oldpair":
        DataIO._slot_identity=staticmethod(lambda lay, c, fp: None)   # pre-2026-09-27 slot rule
    z=np.load(os.path.join(BASE,"Output","R",f"R_CH{ch}.npz"),allow_pickle=True)
    cfgd=json.loads(str(z["config"])); files=json.loads(str(z["processed_files_json"]))
    idx={os.path.basename(p):p for p in __import__("glob").glob(os.path.join(BASE,"RAW","hot","*","*.dat"))}
    fl=[idx[f] for f in files if f in idx]
    if nfiles: fl=fl[:nfiles]
    cfg=RP.RTConfig(tuple(cfgd["fit_window_nm"]),cfgd["col_press"],cfgd["col_temp"],cfgd["spec_start"],cfgd["spec_end"],
                    cfgd["ts_tz_hours"],cfgd["label"],dio_channel=cfgd["dio_channel"])
    wave=np.asarray(z["wave_nm"],float); t0=time.time()
    ks,od,_w=RP.compute_rt_knots(os.path.dirname(fl[0]), wave, cfg, file_list=fl, parallel=True)
    RP.save_rt(out, ks, od, wave, label=f"CH{ch}", config=cfg, processed_files=[os.path.basename(p) for p in fl])
    print("ch",ch,mode,"files",len(fl),"knots",len(ks),"%.0fs"%(time.time()-t0),flush=True)
if __name__=="__main__":
    ch=int(sys.argv[1]); mode=sys.argv[2]; out=sys.argv[3]; n=int(sys.argv[4]) if len(sys.argv)>4 else None
    main(ch,mode,out,n)
