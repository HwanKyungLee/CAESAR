"""Hot-ANs NO2(78) 검증: artifact 부풀림인가 진짜 화학인가.
①시간매칭 PNs vs ANs NO2 관계: 초과분이 일정 오프셋(artifact) vs PNs비례(화학).
②ANs 잔차 모양 vs Cold 잔차 모양 상관: 공통 instrumental artifact인지.
"""
import sys, os, json, glob, re
import numpy as np
from numpy.polynomial import chebyshev as C
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.residual_compare import load_alpha, build_engine, fit_one, CHANNELS, N_SCANS
from core.doas_fit import DoasFitter

scen = json.load(open(os.path.join(ROOT, "scenarios", "Doctor_Scenario_Cold_ROI1_ROI2.json"), encoding="utf-8"))
link = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}


def setup(name):
    ck, globs, refdir = CHANNELS[name]
    ch = scen["channels"][ck]; rp = dict(ch["ref_props"]); rp.setdefault("H2O", link); rp.setdefault("O4", link)
    return globs, refdir, rp, int(ch["f_min"]), int(ch["f_max"]), int(ch["poly_deg"])


def key(fp):  # 'YYYY-MM-DD-NNN'
    m = re.search(r"(\d{4}-\d{2}-\d{2}-\d{3})", os.path.basename(fp))
    return m.group(1) if m else None


# ── ① 시간매칭 PNs vs ANs ──
gP, rdP, rpP, pmnP, pmxP, plP = setup("Hot-PNs")
gA, rdA, rpA, pmnA, pmxA, plA = setup("Hot-ANs")
fP = {key(f): f for f in sorted(sum([glob.glob(g) for g in gP], []))}
fA = {key(f): f for f in sorted(sum([glob.glob(g) for g in gA], []))}
common = sorted(set(fP) & set(fA))
pick = common[:: max(1, len(common)//30)][:30]

engP = build_engine(rdP, load_alpha(fP[pick[0]])[0]); ftP = DoasFitter(engP)
engA = build_engine(rdA, load_alpha(fA[pick[0]])[0]); ftA = DoasFitter(engA)

def no2_of(eng, ft, rp, fp, pmn, pmx, pl):
    w, a, T, P = load_alpha(fp)
    wl, resid, rms, sig, no2 = fit_one(eng, ft, rp, w, a, T, P, pmn, pmx, pl)
    return no2, resid

nP=[]; nA=[]; rA_list=[]
for k in pick:
    p,_ = no2_of(engP, ftP, rpP, fP[k], pmnP, pmxP, plP)
    a,rA = no2_of(engA, ftA, rpA, fA[k], pmnA, pmxA, plA)
    nP.append(p); nA.append(a); rA_list.append(rA)
nP=np.array(nP); nA=np.array(nA)
r = np.corrcoef(nP, nA)[0,1]
slope, intercept = np.polyfit(nP, nA, 1)
print(f"matched scans: {len(pick)}")
print(f"PNs NO2 mean={nP.mean():.1f}  ANs NO2 mean={nA.mean():.1f}  (ratio {nA.mean()/nP.mean():.1f}x)")
print(f"ANs = {slope:.2f}*PNs + {intercept:.1f}   corr={r:+.2f}")
print(f" -> 절편(오프셋)={intercept:.1f}ppb, 기울기={slope:.2f}")
print(f"    절편이 평균의 대부분이면 artifact 오프셋, 기울기~1+상관높으면 화학")

# ── ② ANs 잔차모양 vs Cold 잔차모양 ──
def mean_resid(name):
    globs, rd, rp, pmn, pmx, pl = setup(name)
    files = sorted(sum([glob.glob(g) for g in globs], []))
    pk = files[:: max(1, len(files)//N_SCANS)][:N_SCANS]
    eng = build_engine(rd, load_alpha(pk[0])[0]); ft = DoasFitter(eng)
    R=[]; L=None
    for fp in pk:
        w,a,T,P = load_alpha(fp)
        _,resid,*_ = fit_one(eng, ft, rp, w, a, T, P, pmn, pmx, pl)
        if L is None: L=len(resid)
        if len(resid)==L: R.append(resid)
    return np.mean(R,0), pl

def hp(y, pl):
    x=np.linspace(-1,1,len(y)); yd=y-C.chebval(x,C.chebfit(x,y,pl)); return yd/(np.std(yd)+1e-30)

mrA, plA2 = mean_resid("Hot-ANs"); mrC, plC = mean_resid("Cold")
L = min(len(mrA), len(mrC))
rshape = np.corrcoef(hp(mrA[:L],plA2), hp(mrC[:L],plC))[0,1]
print(f"\nANs 잔차모양 vs Cold 잔차모양 상관 = {rshape:+.2f}  (높으면 공통 instrumental artifact)")
