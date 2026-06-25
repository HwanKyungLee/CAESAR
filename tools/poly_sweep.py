"""콜드 광대역 잔차가 소프트웨어로 잡히나? 다항식 차수 스윕.
- rms/sig가 차수↑로 떨어지면 → under-fit baseline(소프트웨어 fixable).
- NO2가 차수↑로 핫 수준으로 내려가면 → 높게 찍힌 게 baseline 누설(후보정 불필요, 모델로 해결).
- 안 떨어지면 → 콜드 데이터/광학 artifact(후보정 대상).
"""
import sys, os, json, glob
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.residual_compare import load_alpha, build_engine, fit_one, CHANNELS, N_SCANS
from core.doas_fit import DoasFitter

scen = json.load(open(os.path.join(ROOT, "scenarios", "Doctor_Scenario_Cold_ROI1_ROI2.json"), encoding="utf-8"))
link = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}
POLYS = [4, 6, 8, 10, 12]

for name in CHANNELS:
    ch_key, globs, refdir = CHANNELS[name]
    ch = scen["channels"][ch_key]
    rp = dict(ch["ref_props"]); rp.setdefault("H2O", link); rp.setdefault("O4", link)
    pmin, pmax = int(ch["f_min"]), int(ch["f_max"])
    files = sorted(sum([glob.glob(g) for g in globs], []))
    pick = files[:: max(1, len(files) // N_SCANS)][:N_SCANS]
    # 엔진 1회 생성(첫 알파 wave)
    w0, a0, T0, P0 = load_alpha(pick[0])
    eng = build_engine(refdir, w0); fitter = DoasFitter(eng)
    print(f"\n[{name}]")
    for poly in POLYS:
        rmss = []; sigs = []; no2s = []; acs = []
        for fp in pick:
            try:
                w, a, T, P = load_alpha(fp)
                wl, resid, rms, sig, no2 = fit_one(eng, fitter, rp, w, a, T, P, pmin, pmax, poly)
                rmss.append(rms); sigs.append(sig); no2s.append(no2)
                rr = resid - resid.mean()
                acs.append(np.dot(rr[:-1], rr[1:]) / (np.dot(rr, rr) + 1e-30))
            except Exception as e:
                pass
        no2a = np.array([x for x in no2s if x is not None])
        print(f"  poly{poly:2d}: rms/sig={np.mean(rmss)/np.mean(sigs)*100:5.1f}%  "
              f"NO2 mean={np.mean(no2a):7.1f}ppb  autocorr1={np.mean(acs):4.2f}")
