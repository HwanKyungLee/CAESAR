"""Residual-correlation (sandwich) uncertainty vs white-noise sigma on benchmark group B (2026-09-30).
For each B_noise case: Augur operational fit path (run_augur_benchmark.fit_case), then
 sigma_white = sqrt(s2 * diag(pinv(M) pinv(M)^T)),  sigma_corr = sqrt(diag(pinv(M) Sigma pinv(M)^T)),
Sigma = Toeplitz(s2 * acf_r(k)) from the fit residual; M = linear design A (conditional) or [A, d model/d shift] (joint).
ACF variants: 'trunc' = lags until the first non-positive value; 'bart20' = Bartlett-tapered lags 1..20.
Run: python diagnostics/residual_corr_2026-09-30/bench_residual_corr.py  -> bench_cases.csv, bench_summary.csv
"""
import os, sys, csv, numpy as np, pandas as pd
from scipy.linalg import toeplitz
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, os.path.join(ROOT,"tools"), os.path.join(ROOT,"diagnostics","doas_benchmark_2026-09")):
    if p not in sys.path: sys.path.insert(0,p)
import run_augur_benchmark as RB
BENCH=r"C:\GHL\benchmark\doas_benchmark_v1"
def design(eng,px,sh,sq,order,ef):
    A=eng.get_basis_matrix(px,sh,sq,poly_order=order,etalon_freq=ef)
    return np.column_stack([A,np.cos(ef*px)])
def acf_of(r,kind,n):
    rc=r-r.mean(); g0=rc@rc/n; a=[1.0]
    if kind=="trunc":
        for k in range(1,80):
            v=(rc[:-k]@rc[k:])/n/g0
            if v<=0: break
            a.append(v)
    else:
        L=int(kind[4:])
        for k in range(1,L+1): a.append((rc[:-k]@rc[k:])/n/g0*(1-k/(L+1)))
    return np.array(a)
def sigmas(eng,px,ys,sh,sq,order,ef,ngas):
    A=design(eng,px,sh,sq,order,ef); n,p=A.shape
    c,*_=np.linalg.lstsq(A,ys,rcond=None); r=ys-A@c
    h=1e-3; d=((design(eng,px,[x+h for x in sh],sq,order,ef)-design(eng,px,[x-h for x in sh],sq,order,ef))/(2*h))[:,:ngas]@c[:ngas]
    s2=r@r/(n-p-1); res={"acf1":float((r[:-1]-r.mean())@(r[1:]-r.mean())/((r-r.mean())@(r-r.mean())))}
    for nm,M in (("lin",A),("joint",np.column_stack([A,d]))):
        G=np.linalg.pinv(M)[0]          # NO2 row (gas 0)
        res[nm+"_white"]=np.sqrt(s2*G@G)
        for kind in ("trunc","bart20"):
            a=acf_of(r,kind,n); g=np.zeros(n); g[:len(a)]=a*s2
            res[f"{nm}_{kind}"]=np.sqrt(max(G@toeplitz(g)@G,0.0))
    return c[0],res
def main():
    man=pd.read_csv(os.path.join(BENCH,"cases","manifest.csv")); man=man[man.group=="B_noise"]
    Z=np.load(os.path.join(BENCH,"cases","spectra.npz")); rows=[]; cache={}
    seed=np.arange(-(RB.SHIFT_LIMIT-2.0),RB.SHIFT_LIMIT-1.999,1.0)
    for _,r in man.iterrows():
        ch=r.channel; gases=tuple(r.gases_to_fit.split(","))
        if (ch,gases) not in cache:
            wave,sig=RB.load_channel(BENCH,ch); eng=RB.build_engine(wave,sig,"cubic",gases)
            cache[(ch,gases)]=(eng,RB.DoasFitter(eng),np.asarray(Z[f"pixel__{ch}"],float))
        eng,fitter,px=cache[(ch,gases)]
        y=np.asarray(Z[r.case_id],float)
        for mode,fix in (("free",None),("fixshift",float(r.shift_px))):
            best=RB.fit_case(eng,fitter,y,px,float(r.centre_pixel),gases,float(r.squeeze_factor),int(r.fit_poly_order),float(r.fit_etalon_f),seed,None,fix)
            if best is None: continue
            _,out,diag,act,lb,ub=best
            s=RB.alpha_fit_scale(y); conv=1.0/s/eng.scaling_factors["NO2"]*eng.multipliers["NO2"]
            c0,res=sigmas(eng,px,y*s,out[0],out[1],int(r.fit_poly_order),float(r.fit_etalon_f),len(gases))
            row=dict(case_id=r.case_id,mode=mode,noise_rms=r.noise_rms,ar1=r.ar1,truth=r.NO2_molec_cm3,
                     NO2=float(out[2][0])*conv,NO2_recon=c0*conv,sigma_lin_augur=abs(float(out[6][0]))*conv,
                     sigma_joint_augur=abs(float((diag.get("perr_joint") or [np.nan])[0]))*conv,shift=float(out[0][0]),acf1=res["acf1"])
            for k,v in res.items():
                if k!="acf1": row["sigma_"+k]=v*conv
            rows.append(row)
    df=pd.DataFrame(rows); df.to_csv(os.path.join(HERE,"bench_cases.csv"),index=False)
    df["cond"]=np.where(df.ar1>0,"AR(1) 0.5",np.where(df.noise_rms>df.noise_rms.min()*1.5,"white x2","white x1"))
    cols=[c for c in df.columns if c.startswith("sigma_")]
    summ=[]
    for (cond,mode),g in df.groupby(["cond","mode"]):
        err=g.NO2-g.truth; sd=err.std(ddof=1)
        d=dict(cond=cond,mode=mode,n=len(g),scatter=sd,median_acf1=g.acf1.median())
        for c in cols: d["ratio_"+c[6:]]=sd/np.sqrt(np.mean(g[c]**2))
        summ.append(d)
    S=pd.DataFrame(summ); S.to_csv(os.path.join(HERE,"bench_summary.csv"),index=False)
    pd.set_option("display.width",250); print(S.round(3).to_string())
if __name__=="__main__": main()
