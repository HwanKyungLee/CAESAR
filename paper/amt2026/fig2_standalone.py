"""fig2_standalone.py — AMT Fig 2 from ./data (no session state).

    python paper/amt2026/fig2_standalone.py
"""
import os, json
import numpy as np, pandas as pd
import matplotlib as mpl; mpl.use("Agg")
import matplotlib.pyplot as plt
HERE=os.path.dirname(os.path.abspath(__file__)); D=lambda f: os.path.join(HERE,"data",f)
OUT=os.path.join(HERE,"out"); os.makedirs(OUT,exist_ok=True)
import sys; sys.path.insert(0,HERE)
from make_figs_345 import style as _style, letter as _letter
def apply_figure_style(sizes=(8,7,6)): _style(sizes)
f2=pd.read_csv(D("amt_fig2_data.csv")); NZP=pd.read_csv(D("amt_fig2_noise_profiles.csv"))
day=pd.read_csv(D("fig2_day_20260601.csv"),parse_dates=["t"])
t0=json.load(open(D("fig2_records.json")))
R={k:g.reset_index(drop=True) for k,g in day.groupby("config")}
OPS={k:R[k].set_index("t").loc[pd.Timestamp(t0[k])] for k in R}
DAYN={}

import numpy as np, pandas as pd, matplotlib as mpl, matplotlib.pyplot as plt
from matplotlib.lines import Line2D
apply_figure_style(sizes=(8,7,6))
C_NO2="#1f4e9c"; C_H2O="#7b4ea3"; C_GLY="#2f9a8c"; C_MEAS="#9a9a9a"; C_WIN="#e9eef7"
cfg=[("ANs","a","hot ANs","300 °C · 430–462 nm · 4th-order baseline",(428.1,456.1)),
     ("PNs","b","hot PNs","180 °C · 444–471 nm · 3rd-order baseline",(451.3,470.8)),
     ("cold","c","cold","ambient · 438–476 nm · 4th-order baseline",(451.7,473.4))]
fig=plt.figure(figsize=(7.2,10.0))
go=fig.add_gridspec(3,3,height_ratios=[0.8,3.9,0.95],hspace=0.22,wspace=0.30,left=0.1,right=0.955,top=0.95,bottom=0.05)
SUB=[go[1,j].subgridspec(4,1,height_ratios=[1,1,0.85,0.8],hspace=0.10) for j in range(3)]
AX={}
sc=1e9
for j,(k,let,name,sub,ledhm) in enumerate(cfg):
    g=f2[(f2.config==k)&(f2.alpha!=0)]; wl=g.wavelength_nm.values
    lo,hi=wl.min(),wl.max()
    # ---- row 0: noise profile
    ax=fig.add_subplot(go[0,j]); AX[(0,j)]=ax
    nz=NZP[NZP.config==k]; wlf=nz.wavelength_nm.values; s=nz["alpha_noise_60s_cm-1"].values.copy()
    m=(wlf>412)&(wlf<492)
    ax.axvspan(lo,hi,color=C_WIN,zorder=0)
    ax.semilogy(wlf[m],s[m],color="0.25",lw=0.8)
    ax.set_xlim(412,492); ax.set_ylim(2e-10,1.5e-7)
    if ledhm:
        y=1.0e-7; ax.plot(ledhm,[y,y],color="#2a7fb8",lw=2.2,solid_capstyle="butt")
        ax.text(np.mean(ledhm),y*1.25,"LED half-max (ZA)",ha="center",va="bottom",fontsize=6,color="#2a7fb8")
    ax.text((lo+hi)/2,3.2e-10,"fit window",ha="center",va="bottom",fontsize=6,color="#4a5f86")
    ax.set_xlabel("wavelength (nm)",labelpad=1)
    ax.text(0,1.30,let,transform=ax.transAxes,fontsize=10,fontweight="bold",va="bottom")
    ax.text(0.07,1.30,name,transform=ax.transAxes,fontsize=8,fontweight="bold",va="bottom")
    ax.text(0,1.13,sub,transform=ax.transAxes,fontsize=6.5,color="0.35",va="bottom")
    if j==0: ax.set_ylabel("α noise, 60 s\n(cm$^{-1}$ pixel$^{-1}$)")
    # ---- row 1: extinction
    ax=fig.add_subplot(SUB[j][0]); AX[(1,j)]=ax
    ax.plot(wl,g.alpha*1e8,color=C_MEAS,lw=0.9,label="measured")
    ax.plot(wl,g.model*1e8,color="k",lw=1.0,label="model")
    ax.plot(wl,g.baseline_etalon*1e8,color="k",lw=0.8,ls="--",label="baseline + etalon")
    ax.fill_between(wl,g.baseline_etalon*1e8,g.model*1e8,color=C_NO2,alpha=0.12,lw=0,label="trace-gas terms")
    if j==0: ax.set_ylabel("extinction α\n(10$^{-8}$ cm$^{-1}$)")
    if j==2: ax.legend(loc="upper right",frameon=False,handlelength=1.6,borderaxespad=0.2)
    # ---- row 2: NO2
    ax=fig.add_subplot(SUB[j][1]); AX[(2,j)]=ax
    ax.plot(wl,g.no2_signature*sc,color=C_MEAS,lw=0.8)
    ax.plot(wl,g.no2_fit*sc,color=C_NO2,lw=1.5)
    r=OPS[k]
    ax.text(0.97,0.95,f"NO$_2$ {r['NO2']:.2f} ± {r['NO2_Error']:.2f} ppb",transform=ax.transAxes,ha="right",va="top",color=C_NO2,fontsize=7)
    p2p=np.ptp(g.no2_fit*sc); rms=np.sqrt(np.mean(g.residual**2))*sc
    ax.text(0.97,0.80,f"band depth / RMS ≈ {p2p/rms:.0f}",transform=ax.transAxes,ha="right",va="top",color="0.3",fontsize=6)
    ax.set_ylim(5,65)
    if j==0:
        ax.set_ylabel("NO$_2$\n(10$^{-9}$ cm$^{-1}$)")
        ax.text(0.03,0.05,"measured − all other terms",transform=ax.transAxes,fontsize=6,color="0.45")
    # ---- row 3: minor absorbers
    ax=fig.add_subplot(SUB[j][2]); AX[(3,j)]=ax
    ax.plot(wl,g.h2o_signature*sc,color=C_MEAS,lw=0.6,alpha=0.8)
    ax.plot(wl,g.h2o_fit*sc,color=C_H2O,lw=1.3)
    ax.plot(wl,g.chocho_fit*sc,color=C_GLY,lw=1.1)
    ax.set_ylim(-14,26)
    ax.text(0.97,0.93,"H$_2$O",transform=ax.transAxes,ha="right",va="top",fontsize=6,color=C_H2O)
    ax.text(0.97,0.79,"CHOCHO",transform=ax.transAxes,ha="right",va="top",fontsize=6,color=C_GLY)
    if j==0:
        ax.set_ylabel("H$_2$O, CHOCHO\n(10$^{-9}$ cm$^{-1}$)")
        ax.annotate("443 nm band",xy=(443.2,8.0),xytext=(446.5,13),fontsize=6,color=C_H2O,
                    arrowprops=dict(arrowstyle="-",lw=0.5,color=C_H2O))
    # ---- row 4: residual + marginal histogram
    ax=fig.add_subplot(SUB[j][3]); AX[(4,j)]=ax
    res=g.residual.values*sc
    ax.axhspan(-rms,rms,color="0.88",lw=0,zorder=0); ax.axhline(0,color="k",lw=0.5)
    ax.plot(wl,res,color="0.45",lw=0.6)
    ax.set_ylim(-17,17)
    ax.text(0.97,0.95,f"RMS {rms:.1f}   χ$^2_\\nu$ {r['Chi2']:.2f}",transform=ax.transAxes,ha="right",va="top",fontsize=6.5)
    ih=ax.inset_axes([1.0,0,0.10,1],sharey=ax)
    bins=np.linspace(-17,17,35); ih.hist(res,bins=bins,orientation="horizontal",color="0.6",density=True)
    yy=np.linspace(-17,17,200); ih.plot(np.exp(-yy**2/(2*rms**2))/(rms*np.sqrt(2*np.pi)),yy,color="k",lw=0.7)
    ih.axis("off")
    if j==0:
        ax.set_ylabel("residual\n(10$^{-9}$ cm$^{-1}$)")
        ax.text(0.03,0.05,"shaded: ±RMS; side: histogram vs Gaussian",transform=ax.transAxes,fontsize=6,color="0.45")
    ax.set_xlabel("wavelength (nm)",labelpad=1)
    for rr_ in (1,2,3,4):
        AX[(rr_,j)].set_xlim(lo,hi)
        if rr_<4: AX[(rr_,j)].tick_params(labelbottom=False)
    for rr_ in (2,3,4):
        if j>0: AX[(rr_,j)].tick_params(labelleft=False)
    # ---- row 5: the day
    ax=fig.add_subplot(go[2,j]); AX[(5,j)]=ax
    d=R[k]; d=d[d.Chi2<=1.5]; tk=d.t+pd.Timedelta(hours=9)  # 2026-09-28: chi2 rule (old Status label is signal-relative RMS, not fit quality)
    ax.scatter(tk,d.NO2,s=1.2,color=C_NO2,alpha=0.45,lw=0)
    tr=pd.Timestamp(t0[k])+pd.Timedelta(hours=9)
    ax.scatter([tr],[r["NO2"]],marker="*",s=70,color="#e8a020",edgecolor="k",lw=0.5,zorder=5)
    ax.set_yscale("log"); ax.set_ylim(0.8,40)
    ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda v,_: f"{v:g}"))
    ax.set_xlim(pd.Timestamp("2026-06-01 09:00"),pd.Timestamp("2026-06-02 09:00"))
    ax.xaxis.set_major_locator(mpl.dates.HourLocator(byhour=[9,15,21,3]))
    ax.xaxis.set_major_formatter(mpl.dates.DateFormatter("%H"))
    ax.set_xlabel("KST hour, 1–2 June",labelpad=1)
    if j==0: ax.set_ylabel("retrieved NO$_2$\n(ppb, status OK)")
    else: ax.tick_params(labelleft=False)
    iv=ax.inset_axes([0.36,0.60,0.30,0.26])
    lr=np.log10(d.RMS.values*sc); iv.hist(lr,bins=30,color="0.75")
    iv.axvline(np.log10(r["RMS"]*sc),color="#e8a020",lw=1.4)
    pct=(d.RMS<r["RMS"]).mean()*100
    iv.set_yticks([]); iv.tick_params(labelsize=5,pad=1,length=2)
    tv=[1,2,5] if k!="cold" else [2,5,10]; iv.set_xticks(np.log10(tv)); iv.set_xticklabels([str(v) for v in tv])
    iv.set_title(f"residual RMS (10$^{{-9}}$ cm$^{{-1}}$)\nthis record: {pct:.0f}th percentile",fontsize=5.5,pad=1.5)
    for s_ in ("top","right","left"): iv.spines[s_].set_visible(False)
    iv.patch.set_alpha(0.85)
    DAYN[k]=(len(d),pct)
fig.align_ylabels([AX[(i,0)] for i in range(6)])

fig.savefig(os.path.join(OUT,"amt_fig2_representative_fits.png"),dpi=300); fig.savefig(os.path.join(OUT,"amt_fig2_representative_fits.pdf"))
print(DAYN)
