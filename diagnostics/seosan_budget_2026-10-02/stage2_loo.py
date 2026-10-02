"""Seosan 2020 stage 2: R(t) from He/ZA knots, ambient alpha, NO2 fit, leave-one-knot-out (LOO) budget.
Run after stage1_bins_knots.py (seosan_bins.npz, seosan_knots.npz). Reproduces results.json / loo_compare_yeosu_seosan.csv.
Choices (see README): knot pairs with He/ZA level ratio <= 1.1 dropped (11-21-034/035, ratio 1.007);
nominal 20 C / 1013.25 hPa for Rayleigh; ILS FWHM 14 px by residual minimisation (scan 4-18 px);
NO2 shift fixed (ch1 5.65 px, ch2 6.71 px = median free-fit values), squeeze limit +/-1e-4; PCHIP in time, no extrapolation.
"""
import os, io, copy, contextlib, numpy as np
from scipy.interpolate import PchipInterpolator
# --- Augur imports (repo C:\GHL\CAESAR) ---
# FB = fit backend (build_engine), EFm = field Channel wrapper, DataIO, RayleighPhysics: same modules as used in the session
D=os.path.dirname(os.path.abspath(__file__))
def omr(Iz,Ih,aZA,aHe): return (Iz*aZA-Ih*aHe)/(Ih-Iz)          # (1-R)/d
def interp(kt,K,t): return PchipInterpolator(kt,K,axis=0,extrapolate=False)(t)
def alpha(t,I,za_t,Z,r_t,X,aZA):                               # ambient extinction
    I0=interp(za_t,Z,t); x=interp(r_t,X,t); return (x+aZA)*(I0-I)/I
def make_channel(cfg,fwhm_px,FB,EFm,DataIO):
    def be(c,wave):
        with contextlib.redirect_stdout(io.StringIO()):
            e=FB.build_engine(c["wl_path"],c["refs"],DataIO.load_wavecal_array)[0]; e.apply_ils_convolution(float(fwhm_px))
        return e
    EFm.build_engine=be; return EFm.Channel(cfg)
def cfg_fix(cfg,shift):
    c=copy.deepcopy(cfg); c["ref_props"]["NO2"]["sh_mode"]="Fix"; c["ref_props"]["NO2"]["sh_val"]=str(shift); return c
def loo(ch,t,I,za_t,Z,tR,X,aZA,near,kind):
    """kind in i0/rt/tri: drop nearest knot from I0, R, or both; refit."""
    out=np.full((len(t),3),np.nan); nk=len(za_t)
    for k in range(nk):
        m=near==k
        if not m.any(): continue
        keep=np.arange(nk)!=k
        zt,Zk=(za_t[keep],Z[keep]) if kind in("i0","tri") else (za_t,Z)
        rt,Xk=(tR[keep],X[keep]) if kind in("rt","tri") else (tR,X)
        A=alpha(t[m],I[m],zt,Zk,rt,Xk,aZA)
        for j,a in zip(np.flatnonzero(m),A):
            if not np.all(np.isfinite(a[737:1044])): continue
            s=ch.seed(a,20.0,1013.25); f=ch.fit(a,20.0,1013.25,s[2],s[:2],want_diag=True)
            out[j]=(f["NO2"],f["_perr"]["NO2"],f["_resid_rms"]*1e9)
    return out
