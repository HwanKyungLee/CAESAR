"""콜드 느린 fringe를 etalon 항으로 잡히나? etalon 탐색 하한(freq_min) 스윕.
freq_min을 낮추면(0.02→0.005) 느린 fringe(~0.008cyc/px)를 etalon이 포착 → rms/NO2 감소하면 모델로 해결됨.
"""
import sys, os, json, glob
import numpy as np

from core.physics import air_number_density   # ppb 환산 단일 출처
from scipy.interpolate import interp1d
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.residual_compare import load_alpha, build_engine, CHANNELS, N_SCANS
from core.doas_fit import DoasFitter

scen = json.load(open(os.path.join(ROOT, "scenarios", "Doctor_Scenario_Cold_ROI1_ROI2.json"), encoding="utf-8"))
link = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}
FLOORS = [0.02, 0.012, 0.008, 0.005, 0.003]   # etalon freq_min 후보 (cyc/px)


def fit_floor(eng, fitter, rp, wave, alpha, T, P, pmin, pmax, poly, fmin):
    sl = slice(pmin, pmax + 1)
    wl = wave[sl]; a = alpha[sl]
    wax = np.asarray(eng._wave_axis, float).flatten()
    vp = np.asarray(interp1d(wax, np.arange(len(wax)), bounds_error=False, fill_value="extrapolate")(wl), float)
    c = vp[len(vp) // 2]
    ef = fitter.detect_etalon_frequency(vp, a, poly, fmin, 0.40)
    active, fixed, linked, t0, lb, ub = fitter.setup_fit_parameters(rp, 0.0, [0.0, 1.0], 0.5)
    # (구식 etalon 위상 append 제거 — doas_fit가 sin·cos 선형열로 처리, theta는 shift/squeeze만)
    out = fitter.execute_varpro_fit(vp, a, np.eye(len(a)), active, fixed, linked,
                                    t0, lb, ub, poly, ef, c, 1.0, rp, T, 0.0, False)
    opt_sh, opt_sq, gco, poly_c, eamp, ep, perr = out
    full, tot, base, etal, _ = eng.get_model_components(
        vp, opt_sh, opt_sq, gco, poly_c, etalon_amp=eamp, etalon_freq=ef, etalon_phase=ep)
    resid = a - full
    rms = float(np.sqrt(np.mean(resid ** 2))); sig = float(np.sqrt(np.mean(tot ** 2)))
    n_air = air_number_density(T, P)
    gi = eng.gas_list.index("NO2")
    no2 = (gco[gi] * eng.multipliers["NO2"] / eng.scaling_factors["NO2"]) / n_air * 1e9
    rr = resid - resid.mean()
    ac = np.dot(rr[:-1], rr[1:]) / (np.dot(rr, rr) + 1e-30)
    period = 2 * np.pi / ef if ef > 0 else 0
    return rms, sig, no2, ac, period


for name in ["Cold", "Hot-ANs"]:   # 콜드 + 비교용 Hot-ANs(둘 다 구조 남았던 채널)
    ch_key, globs, refdir = CHANNELS[name]
    ch = scen["channels"][ch_key]
    rp = dict(ch["ref_props"]); rp.setdefault("H2O", link); rp.setdefault("O4", link)
    pmin, pmax, poly = int(ch["f_min"]), int(ch["f_max"]), int(ch["poly_deg"])
    files = sorted(sum([glob.glob(g) for g in globs], []))
    pick = files[:: max(1, len(files) // N_SCANS)][:N_SCANS]
    w0, *_ = load_alpha(pick[0]); eng = build_engine(refdir, w0); fitter = DoasFitter(eng)
    print(f"\n[{name}]  poly{poly}")
    for fmin in FLOORS:
        R = []; S = []; N = []; A = []; PER = []
        for fp in pick:
            try:
                w, a, T, P = load_alpha(fp)
                rms, sig, no2, ac, per = fit_floor(eng, fitter, rp, w, a, T, P, pmin, pmax, poly, fmin)
                R.append(rms); S.append(sig); N.append(no2); A.append(ac); PER.append(per)
            except Exception:
                pass
        print(f"  freq_min={fmin:.3f}: rms/sig={np.mean(R)/np.mean(S)*100:5.1f}%  "
              f"NO2={np.mean(N):7.1f}ppb  autocorr1={np.mean(A):4.2f}  "
              f"etalon_period~{np.median(PER):5.1f}px")
