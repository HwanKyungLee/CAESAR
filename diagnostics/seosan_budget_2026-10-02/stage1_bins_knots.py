"""Seosan 2020 (21-25 Nov) raw -> 60-s ambient bins + zero-air / helium knots, both blocks (2026-10-02).
Calibration files are those containing flags != 1. Inside a calibration file the rows after the first flag 513 are
the stable part; of each consecutive pair the file with the higher stable intensity is helium, the other zero air
(Seosan 2020 cycles 511/512/510/513 as valve sequencing; old MATLAB code treats 510-513 as calibration).
Ambient = flag-1 rows of non-calibration files, excluding 300 s after a calibration file.
Output: seosan_bins.npz (t, I1, I2, n), seosan_knots.npz (za_t, za1, za2, he_t, he1, he2)."""
import os, glob, numpy as np
RAW=r"C:\GHL\old_missions\Seosan2020\raw"; OUT=os.path.dirname(os.path.abspath(__file__))
def read(f):
    t=[];fl=[];a=[];b=[]
    with open(f,"rb") as fh:
        for line in fh:
            v=line.rstrip(b"\r\n").split(b"\t")
            if len(v)<4129: continue
            t.append(((int(float(v[0]))<<16)|int(float(v[1])))/100.0); fl.append(int(float(v[4])))
            a.append(np.array(v[5:2053],dtype=np.float32)); b.append(np.array(v[2053:4101],dtype=np.float32))
    return np.array(t),np.array(fl),np.array(a),np.array(b)
def main():
    files=sorted(glob.glob(os.path.join(RAW,"2020-11-2[1-5]-*.dat")))
    cal=[];acc={};last_cal_end=-1e18
    for f in files:
        t,fl,a,b=read(f)
        if len(t)==0: continue
        if np.any((fl!=1)&(fl!=0)):
            k=np.flatnonzero(fl==513)
            s=slice(k[0]+1 if len(k) else len(t)//2, None)
            cal.append(dict(f=os.path.basename(f),t=float(np.mean(t[s])),I1=a[s].mean(0),I2=b[s].mean(0),lev=float(np.median(a[s][:,800:1300])),n=int(len(t[s]))))
            last_cal_end=t.max(); continue
        m=(fl==1)&(t>last_cal_end+300)
        for tb,i1,i2 in zip((t[m]//60)*60+30,a[m],b[m]):
            if tb not in acc: acc[tb]=[np.zeros(2048),np.zeros(2048),0]
            acc[tb][0]+=i1; acc[tb][1]+=i2; acc[tb][2]+=1
    tb=np.array(sorted(acc)); n=np.array([acc[x][2] for x in tb]); keep=n>=3; tb=tb[keep]
    I1=np.array([acc[x][0]/acc[x][2] for x in tb]); I2=np.array([acc[x][1]/acc[x][2] for x in tb])
    np.savez(os.path.join(OUT,"seosan_bins.npz"),t=tb,I1=I1,I2=I2,n=n[keep])
    za=[];he=[]
    i=0
    while i<len(cal)-1:
        c0,c1=cal[i],cal[i+1]
        if c1["t"]-c0["t"]<1800:
            (he if c1["lev"]>c0["lev"] else za).append(c1); (za if c1["lev"]>c0["lev"] else he).append(c0); i+=2
        else: i+=1
    za=sorted(za,key=lambda c:c["t"]); he=sorted(he,key=lambda c:c["t"])
    np.savez(os.path.join(OUT,"seosan_knots.npz"),za_t=np.array([c["t"] for c in za]),za1=np.array([c["I1"] for c in za]),za2=np.array([c["I2"] for c in za]),
             he_t=np.array([c["t"] for c in he]),he1=np.array([c["I1"] for c in he]),he2=np.array([c["I2"] for c in he]),
             za_files=np.array([c["f"] for c in za]),he_files=np.array([c["f"] for c in he]),
             za_lev=np.array([c["lev"] for c in za]),he_lev=np.array([c["lev"] for c in he]))
    print("bins",len(tb),"cal files",len(cal),"ZA",len(za),"He",len(he))
if __name__=="__main__": main()
