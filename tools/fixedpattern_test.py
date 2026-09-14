"""고정패턴 기저 제거 시도. 평균잔차 P를 basis로 추가했을 때:
  ① rms가 줄어드나(구조 제거 효과)  ② NO2가 같이 변하나(누설/과적합 위험).
P가 NO2와 직교(corr~0)면 깨끗이 제거, 상관 크면 NO2 잠식 위험.
2-pass: pass1 잔차평균=P, pass2 선형핏 [gases,poly] vs [gases,poly,P] 비교.
"""
import sys, os, json, glob
import numpy as np

from core.physics import air_number_density   # ppb 환산 단일 출처
from scipy.interpolate import interp1d
from scipy.optimize import lsq_linear
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.residual_compare import load_alpha, build_engine, fit_one, CHANNELS, N_SCANS
from core.doas_fit import DoasFitter

scen = json.load(open(os.path.join(ROOT, "scenarios", "Doctor_Scenario_Cold_ROI1_ROI2.json"), encoding="utf-8"))
link = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}


def linfit(eng, vp, od, poly, custom=None):
    A = eng.get_basis_matrix(vp, 0.0, 1.0, poly_order=poly, custom_basis=custom)
    ng = len(eng.gas_list)
    lb = [0.0] * ng + [-np.inf] * (A.shape[1] - ng)   # 가스≥0 (실제 핏터와 동일 NNLS)
    ub = [np.inf] * A.shape[1]
    res = lsq_linear(A, od, bounds=(lb, ub))
    resid = od - A @ res.x
    return res.x, float(np.sqrt(np.mean(resid ** 2)))


def ppb(eng, coef0, T, P):
    n_air = air_number_density(T, P)
    return (coef0 * eng.multipliers["NO2"] / eng.scaling_factors["NO2"]) / n_air * 1e9


for name in ["Cold", "Hot-PNs", "Hot-ANs"]:
    ch_key, globs, refdir = CHANNELS[name]
    ch = scen["channels"][ch_key]; rp = dict(ch["ref_props"]); rp.setdefault("H2O", link); rp.setdefault("O4", link)
    pmin, pmax, poly = int(ch["f_min"]), int(ch["f_max"]), int(ch["poly_deg"])
    files = sorted(sum([glob.glob(g) for g in globs], []))
    pick = files[:: max(1, len(files)//N_SCANS)][:N_SCANS]

    eng = build_engine(refdir, load_alpha(pick[0])[0]); fitter = DoasFitter(eng)
    wax = np.asarray(eng._wave_axis, float).flatten()
    gi = eng.gas_list.index("NO2")

    # pass1: 평균잔차 P
    Rs = []; scans = []
    for fp in pick:
        w, a, T, P = load_alpha(fp)
        wl, resid, *_ = fit_one(eng, fitter, rp, w, a, T, P, pmin, pmax, poly)
        vp = interp1d(wax, np.arange(len(wax)), bounds_error=False, fill_value="extrapolate")(wl)
        Rs.append(resid); scans.append((vp, a[pmin:pmax+1], T, P))
    L = min(len(r) for r in Rs)
    Pn = np.mean([r[:L] for r in Rs], 0); Pn = Pn / (np.std(Pn) + 1e-30)

    # NO2 단면(윈도우)과 P 상관 = 누설 위험 지표
    no2col = eng.interpolators["NO2"](scans[0][0][:L]) / eng.scaling_factors["NO2"]
    leak = float(np.corrcoef(Pn, no2col - no2col.mean())[0, 1])

    # P를 모델기저(가스+poly)에 직교화 → 가스가 설명못하는 부분만 남김(NO2 보호)
    vp0 = scans[0][0][:L]
    A0 = eng.get_basis_matrix(vp0, 0.0, 1.0, poly_order=poly)
    coef, *_ = __import__("scipy.linalg", fromlist=["lstsq"]).lstsq(A0, Pn)
    P_orth = Pn - A0 @ coef
    P_orth = P_orth / (np.std(P_orth) + 1e-30)

    # pass2: 무직교 P  vs  직교화 P_orth
    rA = []; rB = []; rC = []; nA = []; nB = []; nC = []
    for vp, od, T, Pp in scans:
        vp = vp[:L]; od = od[:L]
        cA, rmsA = linfit(eng, vp, od, poly)
        cB, rmsB = linfit(eng, vp, od, poly, custom=Pn.reshape(-1, 1))
        cC, rmsC = linfit(eng, vp, od, poly, custom=P_orth.reshape(-1, 1))
        rA.append(rmsA); rB.append(rmsB); rC.append(rmsC)
        nA.append(ppb(eng, cA[gi], T, Pp)); nB.append(ppb(eng, cB[gi], T, Pp)); nC.append(ppb(eng, cC[gi], T, Pp))
    print(f"[{name:8s}] corr(P,NO2ref)={leak:+.2f}")
    print(f"    무처리   : rms {np.mean(rA):.2e}            NO2 {np.mean(nA):7.1f}ppb")
    print(f"    P 자유   : rms {np.mean(rB):.2e} ({(1-np.mean(rB)/np.mean(rA))*100:3.0f}%↓)  NO2 {np.mean(nB):7.1f}ppb  (불안정 위험)")
    print(f"    P 직교화 : rms {np.mean(rC):.2e} ({(1-np.mean(rC)/np.mean(rA))*100:3.0f}%↓)  NO2 {np.mean(nC):7.1f}ppb  (NO2 보호)")
