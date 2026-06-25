"""3채널 잔차 모양 vs (1-R(λ)) 구조 대조. R모양이 잔차 주범인지 채널별 확정.
omr_d = (1-R)/d, 알파에 곱해지는 factor. 그 파장구조가 잔차에 박혔으면 R이 범인.
"""
import sys, os, json, glob
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from numpy.polynomial import chebyshev as C
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.residual_compare import load_alpha, build_engine, fit_one, CHANNELS, N_SCANS
from core.doas_fit import DoasFitter

scen = json.load(open(os.path.join(ROOT, "scenarios", "Doctor_Scenario_Cold_ROI1_ROI2.json"), encoding="utf-8"))
link = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}
NPZ = {"Cold": "R_cold.npz", "Hot-PNs": "R_CH1.npz", "Hot-ANs": "R_CH2.npz"}


def cold_mean_resid(name):
    ch_key, globs, refdir = CHANNELS[name]
    ch = scen["channels"][ch_key]; rp = dict(ch["ref_props"]); rp.setdefault("H2O", link); rp.setdefault("O4", link)
    pmin, pmax, poly = int(ch["f_min"]), int(ch["f_max"]), int(ch["poly_deg"])
    files = sorted(sum([glob.glob(g) for g in globs], []))
    pick = files[:: max(1, len(files)//N_SCANS)][:N_SCANS]
    eng = fitter = wl0 = None; R = []
    for fp in pick:
        w, a, T, P = load_alpha(fp)
        if eng is None: eng = build_engine(refdir, w); fitter = DoasFitter(eng)
        wl, resid, *_ = fit_one(eng, fitter, rp, w, a, T, P, pmin, pmax, poly)
        if wl0 is None: wl0 = wl
        if len(resid) == len(wl0): R.append(resid)
    return wl0, np.mean(R, 0), pmin, pmax, poly


def hp(y, poly):
    x = np.linspace(-1, 1, len(y)); yd = y - C.chebval(x, C.chebfit(x, y, poly))
    return yd / (np.std(yd) + 1e-30)


fig, ax = plt.subplots(3, 1, figsize=(10, 9))
for j, name in enumerate(["Cold", "Hot-PNs", "Hot-ANs"]):
    wl, mean_r, pmin, pmax, poly = cold_mean_resid(name)
    z = np.load(os.path.join(r"C:\Doasis_Work\Output\R", NPZ[name]), allow_pickle=True)
    omr_w = z["omr_d"].mean(0)[pmin:pmax+1]
    M = hp(mean_r, poly); ONE_R = hp(omr_w, poly)
    r = float(np.corrcoef(M, ONE_R)[0, 1])
    print(f"[{name:8s}] corr(residual, (1-R) structure) = {r:+.2f}")
    ax[j].plot(wl, M, "k", lw=1.8, label="mean residual")
    ax[j].plot(wl, ONE_R, color="#00695C", lw=1.4, label=f"(1-R) structure  r={r:+.2f}")
    ax[j].set_title(name); ax[j].legend(fontsize=8); ax[j].grid(alpha=.3)
ax[-1].set_xlabel("nm")
fig.tight_layout(); out = os.path.join(ROOT, "tools", "rshape_test.png")
fig.savefig(out, dpi=120); print("saved:", out)
