
import os, sys, json, contextlib, io, time
import numpy as np, pandas as pd
from scipy.interpolate import PchipInterpolator
from numpy.polynomial import chebyshev as C
ROOT=r"C:\GHL\CAESAR"; DD=os.path.join(ROOT,"diagnostics","i0_interp_2026-09"); OD=os.path.join(ROOT,"diagnostics","lowrank_i0_2026-10-03")
for p in [ROOT, DD, os.path.join(ROOT,"diagnostics","etalon_freq_2026-09")]:
    if p not in sys.path: sys.path.insert(0,p)
import measure_i0_loo as MI
from core.physics import RayleighPhysics
FS=json.load(open(r"C:\GHL\2026 yeosu\Output\fit setting\FitSet_ANs[430-462nm_P4]_PNs[444-471nm_P3]_cold[438-476nm_P4]_Std.json",encoding="utf-8"))["channels"]
META=json.load(open(os.path.join(ROOT,"diagnostics","heldout_calib_2026-10-02","yeosu_i0_heldout_meta.json")))
spec={"1":dict(cache="_cache_hot_ANs_op.npz",R="R_CH1_clockfixed.npz",ef=0.1594),"2":dict(cache="_cache_hot_PNs_op.npz",R="R_CH2_clockfixed.npz",ef=0.1368)}
PROBE = len(sys.argv)>1 and sys.argv[1]=="probe"
KS=(1,2,3,5)          # number of principal modes in the low-rank I0 model
LR_POLY=3             # Chebyshev degree (log domain) allowed in the low-rank reconstruction (broadband freedom)
MARGIN_NM=3.0
def rsd(x): x=np.asarray(x); x=x[np.isfinite(x)]; return 1.4826*np.median(np.abs(x-np.median(x)))

class LowRank:
    """ln I0 (inside the fit window +- margin) = c0*mu + sum_k c_k*PC_k + Chebyshev(LR_POLY); basis from training blocks only."""
    def __init__(self, Ztrain, mask, k):
        self.mask=mask; L=np.log(Ztrain[:,mask]); L=L-L.mean(1,keepdims=True)
        self.mu=L.mean(0); U,S,Vt=np.linalg.svd(L-self.mu,full_matrices=False)
        x=np.linspace(-1,1,mask.sum()); V=C.chebvander(x,LR_POLY)
        self.B=np.column_stack([self.mu]+[Vt[i] for i in range(k)]+[V])
        self.Q,_=np.linalg.qr(self.B)
    def __call__(self, y):
        out=np.array(y,float).copy(); ly=np.log(y[self.mask])
        out[self.mask]=np.exp(self.Q@(self.Q.T@ly)); return out

rows=[]; info={}
t0=time.time()
for ch,s in spec.items():
    d=np.load(os.path.join(DD,s["cache"])); R=np.load(os.path.join(DD,s["R"]))
    za_t=d["za_sec"]; Z=d["za_arr"]; Ha,Hb=d["za_half_a"],d["za_half_b"]; T=d["za_t"]; P=d["za_p"]
    xf=PchipInterpolator(R["knot_sec"],R["omr_d"],axis=0,extrapolate=False)
    sh_fix=META[ch]["sh_fix"]
    with contextlib.redirect_stdout(io.StringIO()):
        F=MI.ScanFitter(FS[ch],None,target="NO2",e_f=s["ef"],step_limit=3.0,sh_fix=sh_fix)
    wave=np.asarray(F.wave)
    lo,hi=float(FS[ch]["fit_start_nm"]),float(FS[ch]["fit_end_nm"])
    mask=(wave>=lo-MARGIN_NM)&(wave<=hi+MARGIN_NM)
    aza=RayleighPhysics.get_alpha_rayleigh(wave,32.0,float(np.nanmedian(P)),"zero_air")
    info[ch]=dict(npix=int(len(wave)), nmask=int(mask.sum()), za_shape=list(Z.shape), sh_fix=sh_fix)
    if PROBE:
        print(ch, info[ch]); continue
    def no2(eps,j):
        x=xf(za_t[j]); 
        with contextlib.redirect_stdout(io.StringIO()):
            r=F.fit((x+aza)*eps,float(T[j]),float(P[j]),(sh_fix,1.0),want_diag=True)
        return r["NO2"]
    N=len(za_t)
    # ---- T1: knot noise. raw: half_a vs half_b ; low-rank: LR(half_a) vs half_b, basis from all other full blocks
    for j in range(N):
        if not np.all(np.isfinite(xf(za_t[j]))): continue
        rows.append(dict(ch=ch,test="knot",method="raw_half_vs_half",k=0,m=0,j=j,sec=za_t[j],dNO2=no2(Ha[j]/Hb[j]-1,j)))
        rows.append(dict(ch=ch,test="knot",method="raw_mean_noise",k=0,m=0,j=j,sec=za_t[j],dNO2=no2(((Ha[j]-Hb[j])/2)/Z[j],j)))
        oth=np.delete(np.arange(N),j)
        for k in KS:
            lr=LowRank(Z[oth],mask,k)
            rows.append(dict(ch=ch,test="knot",method="lowrank_half_vs_half",k=k,m=0,j=j,sec=za_t[j],dNO2=no2(lr(Ha[j])/Hb[j]-1,j)))
    print("ch",ch,"knot done",round(time.time()-t0),flush=True)
    # ---- T2: held-out prediction with thinning m (truth = measured withheld block)
    for m in (2,3,6):
        for off in range(m):
            keep=np.zeros(N,bool); keep[off::m]=True
            tk=za_t[keep]; Zk=Z[keep]; pos=np.searchsorted(tk,za_t)
            f_raw=PchipInterpolator(tk,Zk,axis=0,extrapolate=False)
            lr=LowRank(Zk,mask,3)
            Zk_lr=np.array([lr(z) for z in Zk]); f_lr=PchipInterpolator(tk,Zk_lr,axis=0,extrapolate=False)
            for j in np.flatnonzero(~keep):
                p=pos[j]
                if p==0 or p>=len(tk): continue
                seg=(za_t>=tk[p-1])&(za_t<=tk[p])
                if np.any(np.diff(za_t[seg])>3*3600): continue
                if not np.all(np.isfinite(xf(za_t[j]))): continue
                rows.append(dict(ch=ch,test="heldout",method="raw_pchip",k=0,m=m,j=j,sec=za_t[j],dNO2=no2(f_raw(za_t[j])/Z[j]-1,j)))
                rows.append(dict(ch=ch,test="heldout",method="lowrank3_pchip",k=3,m=m,j=j,sec=za_t[j],dNO2=no2(f_lr(za_t[j])/Z[j]-1,j)))
    print("ch",ch,"heldout done",round(time.time()-t0),flush=True)
json.dump(info,open(os.path.join(OD,"lowrank_meta.json"),"w"),indent=1)
if not PROBE:
    pd.DataFrame(rows).to_csv(os.path.join(OD,"lowrank_i0_rows.csv"),index=False)
    print("rows",len(rows))
