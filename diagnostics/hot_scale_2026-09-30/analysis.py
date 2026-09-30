"""Hot-channel scale diagnostics (2026-09-30) for AMT Sect. 3.3 / 3.6.
(1) hot-channel NO2 gain vs AQMS: clock lag test, daily origin slopes, cal-state, night O3 terciles.
(2) QDOAS/Augur NO2 scale ratio vs fitted shift and stretch (hot ANs negshift run; hot PNs boundfix).
Run: python diagnostics/hot_scale_2026-09-30/analysis.py  -> results.json
"""
import os, json, numpy as np, pandas as pd
MERGED=r"C:\GHL\2026 yeosu\data analysis\00_데이터\CAESAR_O3_ANs_merged_data_20260928_final_v3.xlsx"
Q=r"C:\GHL\CAESAR\diagnostics\qdoas_crossval_2026-09"
HERE=os.path.dirname(os.path.abspath(__file__)); out={}
D=pd.read_excel(MERGED,sheet_name="Data"); D["t"]=pd.to_datetime(D.time)
S=D.set_index("t").sort_index(); S=S[~S.index.duplicated()]
def lag(sub,col,h):
    s=sub[col].copy(); s.index=s.index+pd.Timedelta(hours=h)
    j=pd.concat([s,sub.no2_tel_ppb],axis=1,join="inner").dropna()
    return dict(r=float(j.corr().iloc[0,1]), slope0=float((j.iloc[:,0]*j.no2_tel_ppb).sum()/(j.no2_tel_ppb**2).sum()), n=len(j))
out["clock"]={f"{lab}_{c}_{h}":lag(sub,c,h) for lab,sub in [("pre0529",S[:"2026-05-28"]),("post",S["2026-05-29":])]
              for c in ["no2_hot300_ppb","no2_hot180_ppb"] for h in (-9,0,9)}
E=D[D.no2_tel_ppb>3].copy(); E["d"]=E.t.dt.date
def o0(g,y): g=g[[y,"no2_tel_ppb"]].dropna(); return float((g[y]*g.no2_tel_ppb).sum()/(g.no2_tel_ppb**2).sum()) if len(g)>=30 else None
out["daily_slope"]={str(d):dict(h300=o0(g,"no2_hot300_ppb"),h180=o0(g,"no2_hot180_ppb")) for d,g in E.groupby("d")}
for c in ["no2_hot300_ppb","no2_hot180_ppb","no2_caesar_ppb"]: E["r_"+c]=E[c]/E.no2_tel_ppb
out["cal_state_median_ratio"]=E.groupby("ans_cal_state")[["r_no2_hot300_ppb","r_no2_hot180_ppb"]].median().to_dict()
N=E[E.hour.isin(range(6))].copy(); N["hc300"]=N.no2_hot300_ppb/N.no2_caesar_ppb
out["night_hot300_over_cold_by_O3_tercile"]=N.groupby(pd.qcut(N.o3_ppb,3),observed=True).hc300.median().tolist()
def asc(p):
    rows=[];hdr=None
    for l in open(p,encoding="utf-8",errors="replace"):
        if l.startswith("# Date"): hdr=[c.strip() for c in l[2:].rstrip("\n").split("\t")]; continue
        if l.startswith("#"): continue
        rows.append(l.rstrip("\n").split("\t"))
    df=pd.DataFrame(rows,columns=hdr); df["dt"]=pd.to_datetime(df.iloc[:,0].str.strip(),format="%Y%m%d%H%M%S")
    for c in df.columns[2:-1]: df[c]=pd.to_numeric(df[c],errors="coerce")
    return df
def merge_dat(p):
    m=pd.read_csv(p,sep="\t",comment="#",engine="python"); m["dt"]=pd.to_datetime(m.Time,errors="coerce"); return m
def within_day(x,slope_ref):
    x=x.assign(day=x.dt.dt.date); res=[]
    for d,g in x.groupby("day"):
        if len(g)>200: res.append((g.r.corr(g.Shift,method="spearman"),np.polyfit(g.Shift,g.r,1)[0]))
    res=np.array(res); return dict(days=len(res),pos=int((res[:,0]>0).sum()),median_rho=float(np.median(res[:,0])),median_slope_per_px=float(np.median(res[:,1])))
for name,mf,af,deming,asc_p in [("ANs","compare_hot_ans_negshift_matched.csv","ans_merge.dat",1.043,"qdoas_output/hot_ans/hot_ans_negshift.ASC"),
                                ("PNs","compare_hot_pns_boundfix_matched.csv","pns_merge.dat",1.063,None)]:
    m=pd.read_csv(os.path.join(Q,mf),parse_dates=["dt"]).merge(merge_dat(os.path.join(Q,"augur_fit",af))[["dt","Shift","Squeeze"]],on="dt")
    m["r"]=m.alpha_qdoas_NO2/m.realconc_augur_NO2
    m=m[(m.realconc_augur_NO2>m.realconc_augur_NO2.quantile(.5))&np.isfinite(m.r)].copy()
    m["r"]=m.r*deming/m.r.median()   # nominal-T/P ratio rescaled to the exact-T/P Deming slope
    o=dict(n=len(m),shift_median_px=float(m.Shift.median()),rho_shift=float(m.r.corr(m.Shift,method="spearman")),
           rho_squeeze=float(m.r.corr(m.Squeeze,method="spearman")),within_day=within_day(m,deming))
    if asc_p:
        q=asc(os.path.join(Q,asc_p)); mm=m.merge(q[["dt","NO2.Stretch(CHOCHO)1","NO2.Shift(CHOCHO)"]],on="dt")
        o["rho_qdoas_stretch"]=float(mm.r.corr(mm["NO2.Stretch(CHOCHO)1"],method="spearman"))
        o["rho_shift_disagreement"]=float(mm.r.corr(mm["NO2.Shift(CHOCHO)"]+0.0482*mm.Shift,method="spearman"))
    out["qdoas_"+name]=o
json.dump(out,open(os.path.join(HERE,"results.json"),"w"),indent=1,default=str)
print(json.dumps({k:v for k,v in out.items() if k!="daily_slope"},indent=1,default=str)[:3000])
