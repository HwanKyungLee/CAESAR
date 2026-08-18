"""콜드 잔차 지배 PCA모드 vs 후보 단면(O4, NO2) 오버레이로 범인 지목. 토큰 절약 미니버전."""
import sys, os, json, glob
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d
from numpy.polynomial import chebyshev as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.residual_compare import load_alpha, build_engine, fit_one
from core.doas_fit import DoasFitter
from core.data_io import DataIO

scen = json.load(open(os.path.join(ROOT, "scenarios", "Doctor_Scenario_Cold_ROI1_ROI2.json"), encoding="utf-8"))
ch = scen["channels"]["1"]; rp = ch["ref_props"]
pmin, pmax, poly = int(ch["f_min"]), int(ch["f_max"]), int(ch["poly_deg"])

files = sorted(glob.glob(r"C:\Doasis_Work\Output\alpha\cold\*\*_cold_alpha_trace.dat"))
files = files[:: max(1, len(files)//18)][:18]

eng = fitter = wl0 = None; R = []
for fp in files:
    w, a, T, P = load_alpha(fp)
    # build_engine 시그니처가 (refdir, wave)로 바뀜(residual_compare 리팩토링) —
    # 구식 (ch_dict, wave) 호출은 TypeError. Cold 채널 refdir='cold' 고정.
    if eng is None: eng = build_engine("cold", w); fitter = DoasFitter(eng)
    wl, resid, *_ = fit_one(eng, fitter, rp, w, a, T, P, pmin, pmax, poly)
    if wl0 is None: wl0 = wl
    if len(resid) == len(wl0): R.append(resid)
R = np.array(R)

# 지배 모드(평균잔차 + 1st PCA) 합쳐 대표 모양
mean_r = R.mean(0)
U, s, Vt = np.linalg.svd(R - mean_r, full_matrices=False)
mode1 = Vt[0] * np.sign(np.dot(Vt[0], mean_r))   # 부호 정렬

def hp(y):  # 다항식 제거(differential) + 정규화
    x = np.linspace(-1, 1, len(y))
    yd = y - C.chebval(x, C.chebfit(x, y, poly))
    return yd / (np.max(np.abs(yd)) + 1e-30)

# 후보 단면을 핏 윈도우로 가져와 differential화
def candidate(path):
    wref, iref = DataIO.load_reference(path)
    f = interp1d(wref, iref, kind="cubic", bounds_error=False, fill_value="extrapolate")
    return hp(f(wl0))

O4 = candidate(r"C:\Doasis_Work\reference_raw\O4_ThalmanVolkamer(2013)_293K_335.749-600.802nm.txt")
NO2 = candidate(r"C:\Doasis_Work\reference_raw\NO2_Vandaele(2002)_294K_384-725nm(vis-dilut5).txt")
M = hp(mean_r); P1 = hp(mode1)

def corr(a, b): return float(np.corrcoef(a, b)[0, 1])
print(f"mean-resid vs O4 ={corr(M,O4):+.2f}  vs NO2={corr(M,NO2):+.2f}")
print(f"PCAmode1  vs O4 ={corr(P1,O4):+.2f}  vs NO2={corr(P1,NO2):+.2f}")

fig, ax = plt.subplots(2, 1, figsize=(10, 7))
ax[0].plot(wl0, M, "k", lw=2, label="mean residual (norm)")
ax[0].plot(wl0, O4, color="#2E7D32", lw=1.2, label=f"O4 (r={corr(M,O4):+.2f})")
ax[0].plot(wl0, NO2, color="#C62828", lw=1, alpha=.7, label=f"NO2 (r={corr(M,NO2):+.2f})")
ax[0].legend(fontsize=8); ax[0].grid(alpha=.3); ax[0].set_title("Cold mean residual vs candidate cross-sections")
ax[1].plot(wl0, P1, "b", lw=2, label="PCA mode1 (norm)")
ax[1].plot(wl0, O4, color="#2E7D32", lw=1.2, label=f"O4 (r={corr(P1,O4):+.2f})")
ax[1].plot(wl0, NO2, color="#C62828", lw=1, alpha=.7, label=f"NO2 (r={corr(P1,NO2):+.2f})")
ax[1].legend(fontsize=8); ax[1].grid(alpha=.3); ax[1].set_xlabel("nm")
fig.tight_layout(); out = os.path.join(ROOT, "tools", "identify_mode.png")
fig.savefig(out, dpi=120); print("saved:", out)
