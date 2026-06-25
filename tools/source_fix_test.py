"""소스 차분 테스트 — 시간-국소(같은 날) 레퍼런스(sequential DOAS).
고정 artifact는 며칠 단위로 드리프트하나 같은 날엔 거의 동일 →
같은 날 중앙값 알파를 빼면 그 시점 artifact 상쇄. 잔차가 백색(autocorr→0)으로
깨끗해지면 '시간-국소 차분으로 소스 제거 가능' 확정. 단 NO2는 차분(상대)값.
campaign-wide 단일 레퍼런스는 드리프트 때문에 실패함이 이미 확인됨 → 일별 국소로 비교.
"""
import sys, os, json, glob
import numpy as np
from scipy.interpolate import interp1d
from scipy.optimize import lsq_linear
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.residual_compare import load_alpha, build_engine, CHANNELS, N_SCANS

scen = json.load(open(os.path.join(ROOT, "scenarios", "Doctor_Scenario_Cold_ROI1_ROI2.json"), encoding="utf-8"))
link = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}


def fit(eng, vp, od, poly):
    A = eng.get_basis_matrix(vp, 0.0, 1.0, poly_order=poly)
    ng = len(eng.gas_list)
    res = lsq_linear(A, od, bounds=([0]*ng + [-np.inf]*(A.shape[1]-ng), [np.inf]*A.shape[1]))
    resid = od - A @ res.x
    rms = float(np.sqrt(np.mean(resid**2)))
    rr = resid - resid.mean()
    ac = float(np.dot(rr[:-1], rr[1:]) / (np.dot(rr, rr) + 1e-30))
    return res.x[eng.gas_list.index("NO2")], rms, ac


def day_of(fp):
    return os.path.basename(fp)[:10]   # 'YYYY-MM-DD'


for name in ["Cold", "Hot-PNs", "Hot-ANs"]:
    ch_key, globs, refdir = CHANNELS[name]
    ch = scen["channels"][ch_key]
    pmin, pmax, poly = int(ch["f_min"]), int(ch["f_max"]), int(ch["poly_deg"])
    files = sorted(sum([glob.glob(g) for g in globs], []))
    # 스캔 많은 처음 3일만(같은 날 국소 레퍼런스용)
    days = {}
    for fp in files:
        days.setdefault(day_of(fp), []).append(fp)
    use_days = [d for d in sorted(days) if len(days[d]) >= 8][:3]
    eng = build_engine(refdir, load_alpha(days[use_days[0]][0])[0])
    wax = np.asarray(eng._wave_axis, float).flatten()
    sc, mu = eng.scaling_factors["NO2"], eng.multipliers["NO2"]

    raw_ac=[]; raw_rms=[]; raw_no2=[]; cor_ac=[]; cor_rms=[]; cor_no2=[]
    for d in use_days:
        A=[]; meta=[]
        for fp in days[d]:
            w,a,T,P = load_alpha(fp)
            vp = interp1d(wax, np.arange(len(wax)), bounds_error=False, fill_value="extrapolate")(w[pmin:pmax+1])
            A.append(a[pmin:pmax+1]); meta.append((vp,T,P))
        L=min(len(x) for x in A); A=np.array([x[:L] for x in A]); vp=meta[0][0][:L]
        R0=np.median(A,0)   # ★같은 날 중앙값 = 시간-국소 레퍼런스
        for i,(_,T,P) in enumerate(meta):
            n_air=2.68678e19*(P/1013.25)*(273.15/(T+273.15))
            c0,r0,a0=fit(eng,vp,A[i],poly)
            c1,r1,a1=fit(eng,vp,A[i]-R0,poly)
            raw_rms.append(r0); raw_ac.append(a0); raw_no2.append(c0*mu/sc/n_air*1e9)
            cor_rms.append(r1); cor_ac.append(a1); cor_no2.append(c1*mu/sc/n_air*1e9)
    print(f"[{name:8s}] days={use_days}")
    print(f"   raw      : rms {np.mean(raw_rms):.2e}  autocorr {np.mean(raw_ac):4.2f}  NO2 {np.mean(raw_no2):6.1f}+-{np.std(raw_no2):5.1f}")
    print(f"   day-local: rms {np.mean(cor_rms):.2e}  autocorr {np.mean(cor_ac):4.2f}  dNO2 std {np.std(cor_no2):5.1f}  (autocorr->0 = 구조제거)")
