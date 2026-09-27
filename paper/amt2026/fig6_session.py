
import numpy as np, pandas as pd, matplotlib as mpl, matplotlib.pyplot as plt, matplotlib.dates as mdates
apply_figure_style(sizes=(8,7,6))
cA="#1b6ca8"; cP="#6a51a3"; cC="#5a5a5a"; cX="#c62828"; cK="#2e7d6b"
T0,T1=pd.Timestamp("2026-05-17"),pd.Timestamp("2026-07-12")
fig=plt.figure(figsize=(7.2,10.3))
go=fig.add_gridspec(3,1,height_ratios=[4.4,2.1,2.3],hspace=0.26,left=0.105,right=0.975,top=0.967,bottom=0.05)
gA=go[0].subgridspec(6,1,height_ratios=[1.35,1.0,0.75,0.75,0.28,0.28],hspace=0.10)
A=[fig.add_subplot(gA[i]) for i in range(6)]
for a in A[1:]: a.sharex(A[0])
hA,hP,hC=H.loc["ANs"],H.loc["PNs"],H.loc["cold"]
# A1 NO2
a=A[0]
a.plot(hC.index,hC.NO2,color=cC,lw=0.6,label="cold")
a.plot(hA.index,hA.NO2,color=cA,lw=0.6,label="hot ANs (300 °C)")
a.plot(hP.index,hP.NO2,color=cP,lw=0.5,label="hot PNs (180 °C)")
xh=XHK; a.scatter(xh.index,xh.NO2,s=9,color=cX,zorder=5,lw=0)
a.set_yscale("symlog",linthresh=5,linscale=1.2); a.set_ylim(-600,60)
a.set_yticks([-100,-10,0,10,50]); a.set_yticklabels(["−100","−10","0","10","50"])
a.axhline(-5,color=cX,lw=0.5,ls=":")
a.set_ylabel("NO$_2$ (ppb)")
a.legend(loc="lower right",ncol=3,frameon=False,handlelength=1.2,columnspacing=1.0,borderaxespad=0.1)
a.text(0.0,1.02,"a",transform=a.transAxes,fontsize=10,fontweight="bold",va="bottom")
a.text(0.035,1.02,"Deployment: what each field sees (18 May – 11 July 2026, KST)",transform=a.transAxes,fontsize=8,va="bottom")
# episode badges
trb=mpl.transforms.blended_transform_factory(a.transData,a.transAxes)
for n,(t,y) in EPS_BADGE.items():
    a.text(t,y,n,transform=trb,ha="center",va="center",fontsize=5.5,color="white",fontweight="bold",zorder=6,
           bbox=dict(boxstyle="circle,pad=0.15",fc=cX if n!="1" else "#8a6d00",ec="none"))
# A2 chi2
a=A[1]
for h_,c_ in [(hC,cC),(hP,cP),(hA,cA)]: a.plot(h_.index,h_.Chi2,color=c_,lw=0.6)
a.scatter(xh.index,xh.chi2,s=9,color=cX,zorder=5,lw=0)
a.axhline(1.5,color="k",lw=0.5,ls="--"); a.text(T1,1.6,"misfit threshold 1.5 ",ha="right",va="bottom",fontsize=6)
a.set_yscale("log"); a.set_ylim(0.6,200); a.set_ylabel("reduced χ$^2$")
a.text(0.005,0.95,"fit report",transform=a.transAxes,fontsize=6,va="top",color="0.3")
a.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda v,_: f"{v:g}"))
# A3 cold reference context
a=A[2]
a.fill_between(hK.index,1,hK.gap,step="mid",color=cK,alpha=0.35,lw=0)
a.plot(hK.index,hK.gap,color=cK,lw=0.6,drawstyle="steps-mid")
kd=hK[hK.kdev>0.5]; a.scatter(kd.index,np.full(len(kd),11.5),marker="v",s=10,color=cK,lw=0)
a.set_ylim(0,13.5); a.set_yticks([1,5,9]); a.set_ylabel("knot gap (h)")
a.text(0.995,0.55,"cold reference context\n▼ knot departs > 50 % from running median",transform=a.transAxes,ha="right",va="top",fontsize=6,color=cK)
# A3b light level
a=A[3]
a.plot(LA.index,LA.values,color=cC,lw=0.6,label="ambient")
a.plot(LZ.index,LZ.values,color="#b07a2a",lw=0.6,label="zero air")
a.axhline(460,color="k",lw=0.5,ls=":"); a.text(pd.Timestamp("2026-06-25"),520,"detector dark",ha="center",va="bottom",fontsize=6)
a.set_yscale("log"); a.set_ylim(250,8e4); a.set_ylabel("counts")
a.text(0.995,0.45,"cold raw light at 460 nm",transform=a.transAxes,ha="right",fontsize=6,va="center",color="0.3")
a.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda v,_: f"{v/1000:g}k" if v>=1000 else f"{v:g}"))
a.legend(loc="upper right",ncol=2,frameon=False,handlelength=1.2,borderaxespad=0.1)
# A4 provenance
a=A[4]
a.axvspan(pd.Timestamp("2026-05-18"),DISP_END,color="#e0b400",alpha=0.9,lw=0)
a.text(pd.Timestamp("2026-05-18")+(DISP_END-pd.Timestamp("2026-05-18"))/2,0.5,"hot R(t) 9 h displaced",ha="center",va="center",fontsize=6)
a.text(DISP_END+pd.Timedelta("1D"),0.5,"hot R(t) clock-aligned",ha="left",va="center",fontsize=6,color="0.4")
a.set_yticks([]); a.set_ylabel("provenance",rotation=0,ha="right",va="center",labelpad=4)
# A5 termination
a=A[5]
for t in BOUND_T: a.axvline(t,color=cP,lw=1.2)
a.text(BOUND_T[0]+pd.Timedelta("1D"),0.5,"hot PNs at +5 px shift bound (11 records, 21 June)",fontsize=6,va="center",color=cP)
a.set_yticks([]); a.set_ylabel("termination",rotation=0,ha="right",va="center",labelpad=4)
for a in A:
    a.set_xlim(T0,T1)
    if a is not A[-1]: a.tick_params(labelbottom=False)
for a in A[4:]:
    for s in ("left",): a.spines[s].set_visible(False)
    a.set_ylim(0,1)
A[-1].xaxis.set_major_locator(mdates.DayLocator(bymonthday=[1,11,21])); A[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
fig.align_ylabels(A)

# ---------- B zooms
gB=go[1].subgridspec(1,3,wspace=0.32)
def two(gs):
    s=gs.subgridspec(2,1,hspace=0.08,height_ratios=[1.2,1]); a1=fig.add_subplot(s[0]); a2=fig.add_subplot(s[1],sharex=a1); a1.tick_params(labelbottom=False); return a1,a2
# B1 displacement
s_=gB[0].subgridspec(2,1,hspace=0.55,height_ratios=[1.2,1]); b1=fig.add_subplot(s_[0]); b2=fig.add_subplot(s_[1])
b1.scatter(CI.t,CI.dS,s=0.6,color="#8a6d00",alpha=0.35,lw=0)
b1.plot(DS6.index,DS6.values,color="#8a6d00",lw=1.0)
b1.axhline(0,color="k",lw=0.5); b1.set_ylim(-0.6,0.6)
b1.set_ylabel("Δ ΣANs (ppb)\naligned − displaced")
b1.text(0,1.04,"b",transform=b1.transAxes,fontsize=10,fontweight="bold",va="bottom")
b1.text(0.09,1.04,"① product moves, fit report does not",transform=b1.transAxes,fontsize=7,va="bottom")
rows_=[("concentration |Δc| / σ",199,55),("residual RMS change",0.20,0.16),("reported σ change",0.22,0.16)]
for i,(lab,va,vp) in enumerate(rows_):
    y=2-i
    b2.plot([0.05,max(va,vp)],[y,y],color="0.85",lw=0.8,zorder=1)
    b2.scatter([va],[y+0.12],s=18,color=cA,zorder=3); b2.scatter([vp],[y-0.12],s=18,color=cP,zorder=3)
    b2.text(0.06,y+0.30,lab,fontsize=6,va="bottom")
b2.set_xscale("log"); b2.set_xlim(0.05,600); b2.set_ylim(-0.5,2.75); b2.set_yticks([])
b2.xaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda v,_: f"{v:g} %"))
b2.set_xlabel("change caused by the displacement",labelpad=1)
b2.text(0.80,0.06,"● ANs",transform=b2.transAxes,ha="right",fontsize=6,color=cA); b2.text(0.98,0.06,"● PNs",transform=b2.transAxes,ha="right",fontsize=6,color=cP)
b2.spines["left"].set_visible(False)
b1.set_xlim(pd.Timestamp("2026-05-18"),pd.Timestamp("2026-06-02")); b1.axvline(DISP_END,color="0.4",lw=0.6,ls="--")
b1.xaxis.set_major_locator(mdates.DayLocator(bymonthday=[18,25,1])); b1.xaxis.set_major_formatter(mdates.DateFormatter("%d %b")); b1.tick_params(labelbottom=True)
b1.text(0.03,0.05,"ΣANs rSD 0.10 ppb (18–24 May)",transform=b1.transAxes,fontsize=6,color="#8a6d00")
b1.text(DISP_END,-0.55," aligned",fontsize=6,color="0.4",va="bottom")
# cold zooms
def coldzoom(gs,t0,t1,letter,title,labels):
    c1,c2=two(gs)
    w=C0[(C0.tk>=t0)&(C0.tk<=t1)]
    c1.scatter(w.tk,w.NO2,s=1.5,color=cC,lw=0)
    bad=w[w.NO2<-5]; c1.scatter(bad.tk,bad.NO2,s=2,color=cX,lw=0)
    c1.set_yscale("symlog",linthresh=5); c1.set_ylim(-800,50); c1.set_yticks([-100,-10,0,10]); c1.set_yticklabels(["−100","−10","0","10"])
    c2.scatter(w.tk,w.Chi2,s=1.5,color=cC,lw=0); c2.set_yscale("log"); c2.set_ylim(0.5,1000); c2.axhline(1.5,color="k",lw=0.5,ls="--")
    c2.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda v,_: f"{v:g}"))
    kk=KC[(KC>=t0)&(KC<=t1)]
    for k in kk: c1.axvline(k,color=cK,lw=0.5,alpha=0.8,ymin=0.93,ymax=1.0)
    c1.text(0,1.04,letter,transform=c1.transAxes,fontsize=10,fontweight="bold",va="bottom")
    c1.text(0.09,1.04,title,transform=c1.transAxes,fontsize=7,va="bottom")
    for (tt,lab) in labels: c1.annotate(lab,xy=(tt,-600),fontsize=6,ha="center",color=cX)
    c2.set_xlim(t0,t1); c2.xaxis.set_major_locator(mdates.HourLocator(byhour=[0,12])); c2.xaxis.set_major_formatter(mdates.DateFormatter("%d %Hh"))
    return c1,c2
c1,c2=coldzoom(gB[1],pd.Timestamp("2026-05-22 20:00"),pd.Timestamp("2026-05-24 16:00"),"c","④⑤ gaps between reference knots (|)",[])
c1.set_ylabel("cold NO$_2$ (ppb)"); c2.set_ylabel("reduced χ$^2$")
d1,d2=coldzoom(gB[2],pd.Timestamp("2026-06-02 00:00"),pd.Timestamp("2026-06-02 20:00"),"d","⑦ knots regular (|): residual only",[])

# ---------- C
gC=go[2].subgridspec(1,2,width_ratios=[0.78,1.9],wspace=0.22)
e1=fig.add_subplot(gC[0])
hb=e1.hexbin(SX*1e9,SY*1e2,gridsize=45,bins="log",cmap="Blues",mincnt=1,lw=0)
e1.set_xlabel("ANs residual RMS (10$^{-9}$ cm$^{-1}$)"); e1.set_ylabel("ANs reported σ (10$^{-2}$ ppb)")
e1.text(0.04,0.93,f"r = {SR:.3f}, n = {len(SX)/1000:.1f}k\nσ/RMS spread 2.8 % (p5–p95)",transform=e1.transAxes,va="top",fontsize=6.5)
e1.text(0,1.04,"e",transform=e1.transAxes,fontsize=10,fontweight="bold",va="bottom")
e1.text(0.12,1.04,"residual and σ: one witness",transform=e1.transAxes,fontsize=7,va="bottom")
e1.margins(0.03)
# matrix
m=fig.add_subplot(gC[1])
cols=["residual\n/ χ²","termination\nstate","distance to\nreference","reference\nprovenance","raw light\nlevel"]
DX=1.3
for i,(lab,mag,vals) in enumerate(MAT):
    y=len(MAT)-1-i
    m.text(-0.35,y,lab,ha="right",va="center",fontsize=6)
    m.text((len(cols)-1)*DX+0.55,y,mag,ha="left",va="center",fontsize=6,color="0.3")
    for j,v in enumerate(vals):
        if v==1: m.scatter(j*DX,y,s=55,color=cX if i>0 else "#8a6d00",zorder=3)
        elif v==0: m.scatter(j*DX,y,s=55,facecolor="white",edgecolor="0.55",lw=0.8,zorder=3)
        elif v==-2: m.text(j*DX,y,"–",ha="center",va="center",fontsize=7,color="0.55")
        else: m.text(j*DX,y,"n/a",ha="center",va="center",fontsize=6,color="0.55")
for j,c in enumerate(cols): m.text(j*DX,len(MAT)-0.3,c,ha="center",va="bottom",fontsize=6)
m.set_xlim(-3.1,(len(cols)-1)*DX+1.75); m.set_ylim(-0.6,len(MAT)+0.9)
m.axis("off")
m.text(-3.1,len(MAT)+0.9,"f",fontsize=10,fontweight="bold",va="bottom",ha="left")
m.text(-2.8,len(MAT)+0.9,"which field flags which episode   ● flags   ○ silent   – not assessed",fontsize=7,va="bottom")
