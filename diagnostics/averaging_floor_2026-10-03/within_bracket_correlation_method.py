# Reproduces within_bracket_correlation.csv from diagnostics/heldout_calib_2026-10-02/yeosu_i0_heldout.csv
import os, numpy as np, pandas as pd
P=r"C:\GHL\CAESAR\diagnostics\heldout_calib_2026-10-02"; G=0.9524
H0=pd.read_csv(os.path.join(P,"yeosu_i0_heldout.csv")); K0=H0[H0.kind=="knot_noise"]; HH=H0[H0.kind=="heldout"].copy()
HH["occ"]=HH.groupby(["ch","m","j"]).cumcount()
HH["off"]=HH.apply(lambda r:[o for o in range(r.m) if o!=r.j%r.m][r.occ],axis=1)   # row order of the producing loop: off ascending
HH["lo"]=HH.j-((HH.j-HH.off)%HH.m)                                                   # lower kept knot of the bracket
hp=HH.pivot_table(index=["m","off","lo","j"],columns="ch",values="dNO2").reset_index(); hp.columns=[str(c) for c in hp.columns]; hp["S"]=hp["1"]-G*hp["2"]
kp=K0.pivot_table(index="j",columns="ch",values="dNO2"); kp.columns=[str(c) for c in kp.columns]; kp["S"]=kp["1"]-G*kp["2"]
sk={q:kp[q].std() for q in ["1","2","S"]}   # truth (withheld block) noise, independent between blocks
# per series q and thinning m: s2p = var(measured) - sk^2; rho_sepK = cov(errors K blocks apart, same bracket)/s2p;
# avg_factor = (var(bracket mean) - sk^2/n)/s2p, n=m-1 (1 = no averaging gain, 1/n = white). Bootstrap over brackets, 2000x, seed 20261003.
