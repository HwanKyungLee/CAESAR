
import os, sys, types, json, glob, time, io, contextlib, copy
import numpy as np, pandas as pd
ROOT=r"C:\GHL\CAESAR"; sys.path.insert(0,ROOT)
sys.modules["core.window_designer"]=types.ModuleType("core.window_designer")
from core import param_optimizer as PO, fitset_builder as FB
from core.doas_fit import DoasFitter
from core.data_io import DataIO
FSP=r"C:\GHL\2026 yeosu\Output\fit setting\FitSet_ANs[430-462nm_P4]_PNs[444-471nm_P3]_cold[438-476nm_P4]_Std.json"
FS=json.load(open(FSP,encoding="utf-8"))
def run(abase, ch, day, outdir, step=1):
    chk=ch[-1]; out_fp=os.path.join(outdir,f"{ch}_{day}.csv")
    if os.path.exists(out_fp): return
    c=copy.deepcopy(FS["channels"][chk])
    with contextlib.redirect_stdout(io.StringIO()): eng=FB.build_engine(c["wl_path"],c["refs"],DataIO.load_wavecal_array)[0]
    fitter=DoasFitter(eng); rows=[]
    for f in sorted(glob.glob(os.path.join(abase,ch,day,"*_alpha_trace.dat"))):
        first_px,t_idx,p_idx,px_start,wave=DataIO._alpha_layout(f)
        d=pd.read_csv(f,sep="\t",comment="#"); pc=[k for k in d.columns if k.startswith("px")]
        A=d[pc].values.astype(float)
        i0=int(np.abs(wave-c["fit_start_nm"]).argmin()); i1=int(np.abs(wave-c["fit_end_nm"]).argmin())
        for k in range(0,len(d),step):
            r=d.iloc[k]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    o=PO.fit_scan(eng,fitter,c["ref_props"],wave,A[k],float(r.T_C),float(r.P_mbar),i0,i1,c["poly_deg"],c["step_limit"],target="NO2",allow_negative_gas=True)
                rows.append(dict(file=os.path.basename(f)[:14],row_idx=int(r.row_idx),datetime=r.datetime,T_C=r.T_C,P_mbar=r.P_mbar,
                    NO2=o.get("conc"),NO2_rel_err=o.get("perr_rel"),rms=o.get("rms"),rms_sig=o.get("rms_sig"),
                    shift=(o.get("shifts") or {}).get("NO2"),chi2=o.get("chi2",o.get("red_chi2")),
                    H2O=(o.get("conc_all") or {}).get("H2O"),CHOCHO=(o.get("conc_all") or {}).get("CHOCHO")))
            except Exception as e:
                rows.append(dict(file=os.path.basename(f)[:14],row_idx=int(r.row_idx),datetime=r.datetime,err=str(e)[:80]))
    pd.DataFrame(rows).to_csv(out_fp,index=False)
if __name__=="__main__":
    abase=sys.argv[1]; outdir=sys.argv[2]; wi=int(sys.argv[3]); nw=int(sys.argv[4]); step=int(sys.argv[5]) if len(sys.argv)>5 else 1
    os.makedirs(outdir,exist_ok=True)
    days=sorted(set(os.listdir(os.path.join(abase,"ch1")))&set(os.listdir(os.path.join(abase,"ch2"))))
    if len(sys.argv)>6: days=[d for d in days if d in sys.argv[6:]]
    jobs=[(ch,d) for d in days for ch in ("ch1","ch2")][wi::nw]; t0=time.time()
    for ch,d in jobs: run(abase,ch,d,outdir,step)
    print("worker",wi,"done",len(jobs),"%.0fs"%(time.time()-t0),flush=True)
