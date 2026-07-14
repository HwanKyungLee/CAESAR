"""tools/residual_compare.py — Cold vs Hot(PNs) vs Hot(ANs) 잔차 진단 비교.

질문: 콜드의 큰 변동성/구조가 (a)데이터 문제인지 (b)소프트웨어(피팅)가 못 잡는 건지.
방법: 세 채널을 동일 절차(GUI Test Fit 복제)로 피팅하고,
  - fixed/random : 잔차가 매 스캔 똑같은 고정패턴이냐(>1=고정·소프트웨어로 제거가능) vs 랜덤이냐
  - NO2 CV       : 스캔간 농도 변동(콜드 불안정 / 핫 안정 가설 검증)
  - rms, rms/sig : 핏 품질
을 한 화면에 비교.
"""
import sys, os, json, glob
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.engine import UniversalEngine
from core.doas_fit import DoasFitter

SCEN = os.path.join(ROOT, "scenarios", "Doctor_Scenario_Cold_ROI1_ROI2.json")

# 채널 정의: (시나리오채널키, 알파glob, wv_cal 폴더(ILS단면))
WV = r"C:\Doasis_Work\Output\wv_cal"
CHANNELS = {
    "Cold":     ("1", [r"C:\Doasis_Work\Output\alpha\cold\*\*_cold_alpha_trace.dat"], "cold"),
    "Hot-PNs":  ("2", [r"C:\Doasis_Work\Output\alpha\hot\ch1\*\*_CH1_alpha_trace.dat"], "roi1"),
    "Hot-ANs":  ("3", [r"C:\Doasis_Work\Output\alpha\hot\ch2\*\*_CH2_alpha_trace.dat"], "roi2"),
}
REF_FILES = [("NO2", "Ref_NO2_Dynamic-ILS-Applied.dat"),
             ("CHOCHO", "Ref_CHOCHO_Dynamic-ILS-Applied.dat"),
             ("H2O", "Ref_H2O-HITRAN_Dynamic-ILS-Applied.dat"),
             ("O4", "Ref_O4_Dynamic-ILS-Applied.dat")]
N_SCANS = 18   # 채널당 표본 스캔 수(여러 날에 고르게)


def load_alpha(fp):
    wave = row = None; alpha_start = iT = iP = None
    with open(fp, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("# wavelength_nm"):
                wave = np.array([float(x) for x in line.split(":")[1].split()])
            if line.startswith("#"):
                continue
            cols = line.rstrip("\n").split("\t")
            if cols and cols[0] == "row_idx":
                idx = {c: i for i, c in enumerate(cols)}
                alpha_start = next(i for i, c in enumerate(cols) if c.startswith("px"))
                iT, iP = idx.get("T_C"), idx.get("P_mbar")
                continue
            if alpha_start is not None:
                row = cols; break
    n = len(wave)
    T_C = float(row[iT]) if iT is not None and iT < len(row) else 25.0
    P_mbar = float(row[iP]) if iP is not None and iP < len(row) else 1013.0
    alpha = np.array([float(v) for v in row[alpha_start:alpha_start + n]], dtype=float)
    return wave, alpha, T_C, P_mbar


def _read_col(p):
    return np.array([float(l) for l in open(p, encoding="utf-8", errors="replace")
                     if l.strip() and not l.lstrip().startswith("#")])


def build_engine(refdir, wave, align=True):
    """채널별 ILS단면을 등록. align=True면 단면을 자기 Calib nm격자→알파 wave격자로 리샘플
    (Hot은 알파 웨이브캘≠레퍼런스 Calib라 필수). align=False=구버전(픽셀 직접, Cold만 정확)."""
    eng = UniversalEngine()
    eng.set_wavelength_axis(wave)
    calib_files = glob.glob(os.path.join(WV, refdir, "Calib*.txt"))
    calib_nm = _read_col(calib_files[0]) if (align and calib_files) else None
    for name, fn in REF_FILES:
        p = os.path.join(WV, refdir, fn)
        if not os.path.exists(p):
            continue
        if calib_nm is not None:
            vals = _read_col(p)
            n = min(len(vals), len(calib_nm))
            f = interp1d(calib_nm[:n], vals[:n], kind="cubic",
                         bounds_error=False, fill_value="extrapolate")
            resampled = f(np.asarray(wave, float))   # 알파 nm격자로 정합
            eng.raw_references[name] = resampled
            eng.interpolators[name] = interp1d(np.arange(len(resampled)), resampled,
                                               kind="cubic", fill_value="extrapolate")
            mx = float(np.max(np.abs(resampled))) or 1.0
            eng.scaling_factors[name] = mx
            eng.multipliers[name] = 1.0
            if name not in eng.gas_list:
                eng.gas_list.append(name)
        else:
            eng.add_reference(name, p, wave_nm=None, multiplier=1.0)
    eng.apply_ils_convolution(0.0)   # 이미 ILS 적용됨 → skip
    return eng


def fit_one(eng, fitter, rp, wave, alpha, T_C, P_mbar, px_min, px_max, poly_deg):
    sl = slice(px_min, px_max + 1)
    wl = wave[sl]; a = alpha[sl]
    wax = np.asarray(eng._wave_axis, float).flatten()
    vp = np.asarray(interp1d(wax, np.arange(len(wax)), bounds_error=False,
                             fill_value="extrapolate")(wl), float)
    c = vp[len(vp) // 2]
    ef = fitter.detect_etalon_frequency(vp, a, poly_deg, 0.02, 0.40)
    active, fixed, linked, t0, lb, ub = fitter.setup_fit_parameters(rp, 0.0, [0.0, 1.0], 0.5)
    # (구식 etalon 위상 append 제거 — doas_fit가 sin·cos 선형열로 처리, theta는 shift/squeeze만)
    out = fitter.execute_varpro_fit(vp, a, np.eye(len(a)), active, fixed, linked,
                                    t0, lb, ub, poly_deg, ef, c, 1.0, rp, T_C, 0.0, False)
    opt_sh, opt_sq, gco, poly_c, eamp, ep, perr = out
    full, tot, base, etal, _ = eng.get_model_components(
        vp, opt_sh, opt_sq, gco, poly_c, etalon_amp=eamp, etalon_freq=ef, etalon_phase=ep)
    resid = a - full
    rms = float(np.sqrt(np.mean(resid ** 2)))
    sig = float(np.sqrt(np.mean((tot) ** 2)))  # 가스흡수 신호 크기
    n_air = 2.68678e19 * (P_mbar / 1013.25) * (273.15 / (T_C + 273.15))
    no2 = None
    if "NO2" in eng.gas_list:
        gi = eng.gas_list.index("NO2")
        sc = eng.scaling_factors.get("NO2", 1.0); mu = eng.multipliers.get("NO2", 1.0)
        no2 = (gco[gi] * mu / sc) / n_air * 1e9
    return wl, resid, rms, sig, no2


def run_channel(name, scen):
    ch_key, globs, refdir = CHANNELS[name]
    ch = scen["channels"][ch_key]
    rp = dict(ch["ref_props"])
    link = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}
    rp.setdefault("H2O", link); rp.setdefault("O4", link)   # ILS 단면에 맞춰 4종 모두
    px_min, px_max, poly = int(ch["f_min"]), int(ch["f_max"]), int(ch["poly_deg"])

    files = []
    for g in globs:
        files += glob.glob(g)
    files = sorted(files)
    if not files:
        print(f"[{name}] no files"); return None
    pick = files[:: max(1, len(files) // N_SCANS)][:N_SCANS]

    eng = None; fitter = None; wl0 = None
    resids = []; no2s = []; rmss = []; sigs = []
    for fp in pick:
        try:
            wave, alpha, T_C, P_mbar = load_alpha(fp)
            if eng is None:
                eng = build_engine(refdir, wave); fitter = DoasFitter(eng)
            wl, resid, rms, sig, no2 = fit_one(eng, fitter, rp, wave, alpha, T_C, P_mbar, px_min, px_max, poly)
            if wl0 is None: wl0 = wl
            if len(resid) == len(wl0):
                resids.append(resid); no2s.append(no2); rmss.append(rms); sigs.append(sig)
        except Exception as e:
            print(f"  [{name}] skip {os.path.basename(fp)}: {e}")
    R = np.array(resids)
    mean_r, std_r = R.mean(0), R.std(0)
    fixed_random = float(np.std(mean_r) / (np.mean(std_r) + 1e-30))

    # ── 데이터 vs 소프트웨어 판별 지표 ──
    # (1) lag-1 자기상관: 잔차가 이웃 픽셀과 얼마나 닮았나. 0=백색(노이즈한계), →1=매끄러운 구조.
    ac = []
    for row in R:
        rr = row - row.mean()
        d = np.dot(rr[:-1], rr[1:]) / (np.dot(rr, rr) + 1e-30)
        ac.append(d)
    autocorr1 = float(np.mean(ac))
    # (2) PCA 구조도: 잔차행렬 상위 3모드가 설명하는 분산 비율. 백색이면 ≈3/n.
    Rc = R - R.mean(0)
    sv = np.linalg.svd(Rc, compute_uv=False)
    ev = sv ** 2
    top1 = float(ev[0] / ev.sum())
    top3 = float(ev[:3].sum() / ev.sum())
    white_base = 3.0 / len(R)   # 백색 기대치

    no2arr = np.array([x for x in no2s if x is not None])
    no2_cv = float(np.std(no2arr) / (abs(np.mean(no2arr)) + 1e-30)) if len(no2arr) else float("nan")
    rms_sig = float(np.mean(rmss) / (np.mean(sigs) + 1e-30))
    print(f"[{name:8s}] n={len(resids):2d}  autocorr1={autocorr1:5.2f}(0=white)  "
          f"PCA top3={top3*100:4.0f}% (white~{white_base*100:.0f}%)  top1={top1*100:3.0f}%  "
          f"rms/sig={rms_sig*100:4.1f}%  fixed/random={fixed_random:.1f}")
    return dict(name=name, wl=wl0, mean_r=mean_r, std_r=std_r, R=R,
                fixed_random=fixed_random, no2=no2arr, no2_cv=no2_cv,
                rms=np.mean(rmss), rms_sig=rms_sig,
                autocorr1=autocorr1, top1=top1, top3=top3, white_base=white_base, ev=ev)


def main():
    scen = json.load(open(SCEN, encoding="utf-8"))
    results = [run_channel(n, scen) for n in CHANNELS]
    results = [r for r in results if r]

    fig, axes = plt.subplots(2, len(results), figsize=(5 * len(results), 8))
    if len(results) == 1:
        axes = axes.reshape(2, 1)
    for j, r in enumerate(results):
        ax = axes[0, j]
        for row in r["R"]:
            ax.plot(r["wl"], row, lw=.4, alpha=.4)
        ax.plot(r["wl"], r["mean_r"], "k", lw=1.8)
        ax.axhline(0, color="gray", lw=.5)
        ax.set_title(f"{r['name']}  autocorr1={r['autocorr1']:.2f}\n"
                     f"PCA top3={r['top3']*100:.0f}% (white≈{r['white_base']*100:.0f}%)  rms/sig={r['rms_sig']*100:.0f}%")
        ax.set_xlabel("nm"); ax.set_ylabel("residual"); ax.grid(alpha=.3)

        # 하단: PCA 누적분산 곡선 vs 백색기준 대각선 — 위로 휘면 구조적(소프트웨어로 제거가능)
        axc = axes[1, j]
        cum = np.cumsum(r["ev"]) / r["ev"].sum()
        k = np.arange(1, len(cum) + 1)
        axc.plot(k, cum, "o-", ms=3, color="#1565C0", label="residual PCA")
        axc.plot(k, k / len(cum), "--", color="gray", label="white-noise baseline")
        axc.set_xlim(1, min(12, len(cum))); axc.set_ylim(0, 1.02)
        axc.set_title("cumulative variance explained")
        axc.set_xlabel("# PCA modes"); axc.set_ylabel("frac variance"); axc.legend(fontsize=7); axc.grid(alpha=.3)
    fig.tight_layout()
    out = os.path.join(ROOT, "tools", "residual_compare.png")
    fig.savefig(out, dpi=120); print("saved:", out)


if __name__ == "__main__":
    main()
