
import os, sys, json, contextlib, io
import numpy as np, pandas as pd
from scipy.interpolate import PchipInterpolator
ROOT=r"C:\GHL\CAESAR"; DD=os.path.join(ROOT,"diagnostics","i0_interp_2026-09"); OD=os.path.join(ROOT,"diagnostics","heldout_calib_2026-10-02")
for p in [ROOT, DD, os.path.join(ROOT,"diagnostics","etalon_freq_2026-09")]:
    if p not in sys.path: sys.path.insert(0,p)
import measure_i0_loo as MI
from core.physics import RayleighPhysics
FS=json.load(open(r"C:\GHL\2026 yeosu\Output\fit setting\FitSet_ANs[430-462nm_P4]_PNs[444-471nm_P3]_cold[438-476nm_P4]_Std.json",encoding="utf-8"))["channels"]
spec={"1":dict(cache="_cache_hot_ANs_op.npz",R="R_CH1_clockfixed.npz",ef=0.1594),"2":dict(cache="_cache_hot_PNs_op.npz",R="R_CH2_clockfixed.npz",ef=0.1368)}
def rsd(x): x=np.asarray(x); x=x[np.isfinite(x)]; return 1.4826*np.median(np.abs(x-np.median(x)))
out=[]; summ={}
for k,s in spec.items():
    d=np.load(os.path.join(DD,s["cache"])); R=np.load(os.path.join(DD,s["R"]))
    za_t=d["za_sec"]; Z=d["za_arr"]; Ha,Hb=d["za_half_a"],d["za_half_b"]; T=d["za_t"]; P=d["za_p"]
    rk=R["knot_sec"]; xo=R["omr_d"]
    # ensure same time base: report offsets
    xf=PchipInterpolator(rk,xo,axis=0,extrapolate=False)
    with contextlib.redirect_stdout(io.StringIO()):
        F0=MI.ScanFitter(FS[k],None,target="NO2",e_f=s["ef"],step_limit=3.0)
    wave=F0.wave
    aza=RayleighPhysics.get_alpha_rayleigh(wave,32.0,float(np.nanmedian(P)),"zero_air")
    # typical shift from ambient alphas (simple assembly) for 25 bins
    amb_t=d["amb_sec"]; I=d["amb_I"]; I0f=PchipInterpolator(za_t,Z,axis=0,extrapolate=False)
    sel=np.linspace(0,len(amb_t)-1,25).astype(int); shs=[]
    for j in sel:
        I0=I0f(amb_t[j]); x=xf(amb_t[j])
        if not (np.all(np.isfinite(I0)) and np.all(np.isfinite(x))): continue
        a=(x+aza)*(I0-I[j])/I[j]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                sh,sq,ef=F0.seed(a,float(d["amb_T"][j]),float(d["amb_P"][j])); r=F0.fit(a,float(d["amb_T"][j]),float(d["amb_P"][j]),(sh,sq),want_diag=True)
            shs.append(r["_shift"])
        except Exception as e: pass
    sh_fix=float(np.median(shs))
    with contextlib.redirect_stdout(io.StringIO()):
        F=MI.ScanFitter(FS[k],None,target="NO2",e_f=s["ef"],step_limit=3.0,sh_fix=sh_fix)
    def no2_of(alpha,Tj,Pj):
        with contextlib.redirect_stdout(io.StringIO()):
            r=F.fit(alpha,Tj,Pj,(sh_fix,1.0),want_diag=True)
        return r["NO2"]
    # knot noise propagated: block mean noise spectrum = (half_a-half_b)/2 relative
    for j in range(len(za_t)):
        x=xf(za_t[j])
        if not np.all(np.isfinite(x)): continue
        eps=((Ha[j]-Hb[j])/2)/Z[j]
        out.append(dict(ch=k,kind="knot_noise",m=0,j=j,sec=za_t[j],bracket_h=0.0,dNO2=no2_of((x+aza)*eps,float(T[j]),float(P[j]))))
    # held-out prediction with thinning
    for m in (2,3,4,6):
        for off in range(m):
            keep=np.zeros(len(za_t),bool); keep[off::m]=True
            tk,Zk=za_t[keep],Z[keep]; f=PchipInterpolator(tk,Zk,axis=0,extrapolate=False); pos=np.searchsorted(tk,za_t)
            for j in np.flatnonzero(~keep):
                p=pos[j]
                if p==0 or p>=len(tk): continue
                lo,hi=tk[p-1],tk[p]
                seg=(za_t>=lo)&(za_t<=hi)
                if np.any(np.diff(za_t[seg])>3*3600): continue
                x=xf(za_t[j])
                if not np.all(np.isfinite(x)): continue
                eps=f(za_t[j])/Z[j]-1
                out.append(dict(ch=k,kind="heldout",m=m,j=j,sec=za_t[j],bracket_h=(hi-lo)/3600,dist_h=min(za_t[j]-lo,hi-za_t[j])/3600,
                                dNO2=no2_of((x+aza)*eps,float(T[j]),float(P[j]))))
    summ[k]=dict(sh_fix=sh_fix,n_shift_seeds=len(shs),za_knots=int(len(za_t)),R_overlap_frac=float(np.mean(np.isfinite(xf(za_t)[:,0]))))
df=pd.DataFrame(out); df.to_csv(os.path.join(OD,"yeosu_i0_heldout.csv"),index=False)
json.dump(summ,open(os.path.join(OD,"yeosu_i0_heldout_meta.json"),"w"),indent=1)
for (k,kind,m),g in df.groupby(["ch","kind","m"]):
    print(k,kind,m,len(g),"robust %.4f SD %.4f p95 %.4f mean %.4f"%(rsd(g.dNO2),np.std(g.dNO2),np.percentile(np.abs(g.dNO2),95),np.mean(g.dNO2)))
print(summ)
