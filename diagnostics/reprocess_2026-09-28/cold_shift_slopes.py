
import os, sys, types, json, glob, io, contextlib, copy, time
import numpy as np, pandas as pd
ROOT=r"C:\GHL\CAESAR"; sys.path.insert(0,ROOT)
sys.modules["core.window_designer"]=types.ModuleType("core.window_designer")
from core import param_optimizer as PO, fitset_builder as FB
from core.doas_fit import DoasFitter
from core.data_io import DataIO
from core.physics import air_number_density
XV=os.path.join(ROOT,"diagnostics","qdoas_crossval_2026-09"); Kc=1e6; STRIDE=8
FSP=r"C:\GHL\2026 yeosu\Output\fit setting\FitSet_ANs[430-462nm_P4]_PNs[444-471nm_P3]_cold[438-476nm_P4]_Std.json"
C=json.load(open(FSP,encoding="utf-8"))["channels"]["3"]
CONDS={"fix-0.5":("Fix","-0.5"),"fix-0.1":("Fix","-0.1"),"fix-0.15":("Fix","-0.15"),"fix0":("Fix","0.0"),"free2.01":("Limit","-2.01, 2.01"),"free5":("Limit","-5.0, 5.0")}
def props(mode,val):
    p=copy.deepcopy(C["ref_props"]); p["NO2"].update(sh_mode=mode,sh_val=val)
    if mode=="Limit": p["NO2"].update(sq_mode="Limit",sq_val="-0.005, 0.005")
    return p
def main(days,out):
    with contextlib.redirect_stdout(io.StringIO()): eng=FB.build_engine(C["wl_path"],C["refs"],DataIO.load_wavecal_array)[0]
    fit=DoasFitter(eng); wave=np.asarray(DataIO.load_wavecal_array(C["wl_path"]),float)
    nair=air_number_density(25.0,1013.25)
    rows=[]
    for p in days:
        d=os.path.basename(p)[:10]
        for l in open(p).read().splitlines()[::STRIDE]:
            f=l.split(); hh=float(f[1]); I=np.array(f[2:],dtype=float)
            a=np.zeros(2048); a[774:774+len(I)]=-np.log(np.clip(I,1e-300,None))/Kc
            rec={"day":d,"sec":hh*3600.0}
            for tag,(m,v) in CONDS.items():
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        o=PO.fit_scan(eng,fit,props(m,v),wave,a,25.0,1013.25,774,773+len(I),C["poly_deg"],20.0 if m=="Limit" else C["step_limit"],target="NO2",allow_negative_gas=True)
                    ca=o["conc_all"]
                    for g in ("NO2","CHOCHO","H2O"): rec[f"{g}_{tag}"]=ca.get(g,np.nan)*nair/1e9
                    rec[f"sh_{tag}"]=o["shifts"]["NO2"]; rec[f"rms_{tag}"]=o["rms"]
                except Exception as e: rec[f"err_{tag}"]=str(e)[:60]
            rows.append(rec)
    pd.DataFrame(rows).to_csv(out,index=False)
if __name__=="__main__":
    wi,nw,outdir=int(sys.argv[1]),int(sys.argv[2]),sys.argv[3]; os.makedirs(outdir,exist_ok=True)
    days=sorted(glob.glob(os.path.join(XV,"qdoas_input","cold","2026-*.asc")))[wi::nw]
    t0=time.time(); main(days,os.path.join(outdir,f"w{wi}.csv")); print("w",wi,len(days),"%.0fs"%(time.time()-t0))
