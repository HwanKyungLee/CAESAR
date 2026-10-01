"""Residual-correlation (sandwich) sigma on the field budget window (2026-09-30).
Same records as production_budget_clockfixed.csv (9034 bins, 18-24 May, clock-fixed R), base fit only
(operational e_f 0.12, seeds once per zero-air knot as in production_budget.py). For each record and heated channel:
 sigma_white (lin / joint incl. shift+squeeze) and sigma_corr with the residual ACF (trunc / bart20), in ppb.
Run (headless stub): python diagnostics/runtime_2026-09-30/qtstub_run.py diagnostics/residual_corr_2026-09-30/field_residual_corr.py
"""
import os, sys, json, numpy as np, pandas as pd
from scipy.linalg import toeplitz
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE)); D=os.path.join(ROOT,"diagnostics","i0_interp_2026-09")
for p in (ROOT, os.path.join(ROOT,"tools"), D):
    if p not in sys.path: sys.path.insert(0,p)
from production_budget import Chan
from core.doas_fit import alpha_fit_scale
FITSET=r"C:\GHL\2026 yeosu\Output\fit setting\FitSet_ANs[430-462nm_P4]_PNs[444-471nm_P3]_cold[438-476nm_P4]_Std.json"
EF=0.12; GP=0.9524
def acf_of(r,kind):
    n=len(r); rc=r-r.mean(); g0=rc@rc/n; a=[1.0]
    if kind=="trunc":
        for k in range(1,120):
            v=(rc[:-k]@rc[k:])/n/g0
            if v<=0: break
            a.append(v)
    else:
        L=int(kind[4:])
        for k in range(1,L+1): a.append((rc[:-k]@rc[k:])/n/g0*(1-k/(L+1)))
    return np.array(a)
def run(tag,key,cache,rt,secs):
    cfg=json.load(open(FITSET,encoding="utf-8"))["channels"][key]
    C=Chan(cache,rt,cfg,EF,3.0); ch=C.fit.ch; eng=ch.eng; gl=list(eng.gas_list); gi=gl.index("NO2"); order=int(cfg["poly_deg"])
    nk=len(C.za_x); amb=np.round(C.d["amb_sec"].astype(float),3); pos={v:i for i,v in enumerate(amb)}
    knot_of=np.clip(np.searchsorted(C.za_x,C.ax),1,nk-1)
    left=np.abs(C.ax-C.za_x[knot_of-1])<np.abs(C.ax-C.za_x[np.minimum(knot_of,nk-1)]); knot_of=np.where(left,knot_of-1,knot_of)
    lo,hi=min(secs)-100.0,max(secs)+100.0
    js=[]; by={}
    for j in range(len(C.ax)):
        sj=float(C.d["amb_sec"][j])
        if not (lo<=sj<=hi): continue
        k=int(knot_of[j])
        if k<=0 or k>=nk-1: continue
        sec_k=float(C.d["za_sec"][k]); kr=int(np.argmin(np.abs(C.rks-sec_k)))
        if not (0<kr<len(C.rks)-1) or abs(C.rks[kr]-sec_k)>3600: continue
        js.append(j)
    for j in js: by.setdefault(int(knot_of[j]),[]).append(j)
    print(tag,"records",len(js),flush=True)
    rows=[]; vp=ch.vp; n=len(vp)
    def design(sh,sq):
        A=eng.get_basis_matrix(vp,[sh]*len(gl),[sq]*len(gl),poly_order=order,etalon_freq=EF)
        return np.column_stack([A,np.cos(EF*vp)])
    for k,jl in sorted(by.items()):
        seed=None
        for j in jl:
            xq=float(C.ax[j]); sec=float(C.d["amb_sec"][j]); T=float(C.d["amb_T"][j]); P=float(C.d["amb_P"][j])
            a_full=C.alpha(j,np.asarray(C.pi0(xq),float),C.omr(sec))
            if seed is None: seed=C.fit.seed(a_full,T,P)[:2]
            f=C.fit.fit(a_full,T,P,seed,EF,want_diag=True)
            if not np.isfinite(f["NO2"]): continue
            a=np.asarray(a_full,float)[ch.sl]; s=alpha_fit_scale(a); y=a*s
            sh,sq=f["_shift"],f["_squeeze"]; A=design(sh,sq); p=A.shape[1]
            c,*_=np.linalg.lstsq(A,y,rcond=None); r=y-A@c
            conv=eng.multipliers.get("NO2",1.0)/eng.scaling_factors.get("NO2",1.0)/s/(f["NO2"]/(c[gi]*eng.multipliers.get("NO2",1.0)/eng.scaling_factors.get("NO2",1.0)/s)) if False else None
            # ppb conversion via the fitter's own NO2 value
            k_ppb=f["NO2"]/c[gi] if c[gi]!=0 else np.nan
            h=1e-3
            dsh=((design(sh+h,sq)-design(sh-h,sq))/(2*h))[:,:len(gl)]@c[:len(gl)]
            hq=1e-5
            dsq=((design(sh,sq+hq)-design(sh,sq-hq))/(2*hq))[:,:len(gl)]@c[:len(gl)]
            s2=r@r/(n-p-2); row=dict(sec=sec,NO2=f["NO2"],NO2_recon=c[gi]*k_ppb,perr_augur=f["_perr"]["NO2"],at_bound=f["_at_bound"],shift=sh,
                                     acf1=float(((r[:-1]-r.mean())@(r[1:]-r.mean()))/((r-r.mean())@(r-r.mean()))))
            for nm,M in (("lin",A),("joint",np.column_stack([A,dsh,dsq]))):
                G=np.linalg.pinv(M)[gi]
                row[f"{nm}_white"]=abs(k_ppb)*np.sqrt(s2*G@G)
                for kind in ("trunc","bart20"):
                    av=acf_of(r,kind); g=np.zeros(n); g[:len(av)]=av*s2
                    row[f"{nm}_{kind}"]=abs(k_ppb)*np.sqrt(max(G@toeplitz(g)@G,0.0))
                    if nm=="lin" and kind=="trunc": row["nlag"]=len(av)-1
            rows.append(row)
    df=pd.DataFrame(rows); df.to_csv(os.path.join(HERE,f"field_{tag}.csv"),index=False); print(tag,len(df),flush=True); return df
def main():
    secs=[round(float(v),3) for v in pd.read_csv(os.path.join(D,"production_budget_clockfixed.csv")).sec]
    A=run("ANs","1",os.path.join(D,"_cache_hot_ANs_op.npz"),os.path.join(D,"R_CH1_clockfixed.npz"),secs)
    B=run("PNs","2",os.path.join(D,"_cache_hot_PNs_op.npz"),os.path.join(D,"R_CH2_clockfixed.npz"),secs)
if __name__=="__main__": main()
