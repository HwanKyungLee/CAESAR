"""확장 합성 스펙트럼 검정 — tools/test_varpro_closure.py 가 안 보는 네 구멍.

기존 closure test(B절)가 덮는 것: 무잡음 회수 정확도, 편향 <= 보고오차,
산포/보고오차 비율, cond(A). 안 덮는 것이 이 파일의 대상이다.

G1  비선형 파라미터 회수 — closure test는 sh/sq를 **반환만 받고 판정하지 않는다.**
    VarPro 외부 루프의 존재 이유가 검증되지 않은 상태다. 부호 자기일관성 포함.
G2  poly 차수 스윕 — closure는 poly3 고정. Stage-1이 차수를 **고른다**(A-4에서
    추천이 p6/p8로 나왔다). 차수를 올릴 때 기체 신호가 배경으로 새는가.
G3  모델 불일치 편향 — closure는 합성과 핏이 **같은 보간기**를 쓴다(순수 T1
    자기일관성). ILS 폭 불일치 · 미모형 에탈론 · 레퍼런스 누락을 넣어 T2로 만든다.
G4  shift 인입영역 — A-4가 발견한 `_seed_shift` 누락을 정답을 아는 계에서 정량화.

합성용 단면을 따로 만들지 않는다. 실제 계기 레퍼런스
`tests/data/wv_cal_roi1/Ref_*_Dynamic-ILS-Applied.dat` + 그 Calib 파장축을 쓴다
(운영 PNs 창 444.1~470.6 nm, poly3 — closure test와 같은 조건).
"""
import os
import sys

import numpy as np
from numpy.polynomial import chebyshev

def _repo_root(start):
    """`core/` 를 품은 상위 디렉터리를 찾아 올라간다.

    `dirname(dirname(__file__))` 는 이 파일이 `tools/` 에 있을 때만 맞는다. 한때
    `diagnostics/<폴더>/` 두 단계 아래에 놓였다가 `ModuleNotFoundError: core` 로
    CI 를 깼다(2026-09-20). 어디에 두든 돌게 위로 찾아 올라간다.
    """
    d = os.path.dirname(os.path.abspath(start))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "core")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("repo root(core/ 를 품은 폴더)를 못 찾았다")


ROOT = _repo_root(__file__)
sys.path.insert(0, ROOT)

from core.doas_fit import DoasFitter          # noqa: E402
from core.engine import UniversalEngine       # noqa: E402
# closure test와 같은 탐색 순서. 첫 번째는 저장소 동봉 픽스처라 CI에서도 돈다.
REF_DIRS = [os.environ.get("AUGUR_WVCAL_DIR", ""),
            os.path.join(ROOT, "tests", "data", "wv_cal_roi1"),
            os.path.join(ROOT, "reference_data", "wv_cal", "roi1"),
            os.path.join(ROOT, "dist", "oculus_deps", "wv_cal", "roi1")]
REFDIR = None
REF_FILES = [("NO2", "Ref_NO2_Dynamic-ILS-Applied.dat"),
             ("CHOCHO", "Ref_CHOCHO_Dynamic-ILS-Applied.dat"),
             ("H2O", "Ref_H2O-HITRAN_Dynamic-ILS-Applied.dat")]

FIT_NM = (444.1, 470.6)      # 운영 PNs 핏창
POLY_ORDER = 3               # 운영 PNs 차수
ETALON_F = 0.12              # 운영 fixed_e_f (rad/px)
NOISE_MEASURED = 6.16e-9     # cm^-1, 2026-06-14 PNs 잔차 RMS 중앙값
SCD_MID = 1e12               # molec/cm^3 (알파는 수농도다 — SCD 아님)
COMPANION_FRAC = {"CHOCHO": 0.05, "H2O": 0.30}
FIELD_SHIFT = -1.96          # 실측 PNs shift 중앙값 (부록 A-1)


# ── 엔진·합성·핏 ───────────────────────────────────────────────────────────
def read_col(path):
    return np.array([float(l) for l in open(path, encoding="utf-8", errors="replace")
                     if l.strip() and not l.lstrip().startswith("#")])


def build_engine(gases, ils_extra_px=0.0):
    """운영 경로 그대로: add_reference + apply_ils_convolution.

    ils_extra_px > 0.1 이면 레퍼런스를 그만큼 **추가로** 흐린다 — 합성 진실을
    만드는 데만 쓴다(핏 엔진은 항상 0.0). engine 내부에서 scaling_factors도
    같이 갱신되므로 흐린 쪽의 피크 σ 감소가 그대로 반영된다.
    """
    calib = [f for f in os.listdir(REFDIR) if f.startswith("Calib")]
    wave = read_col(os.path.join(REFDIR, calib[0]))
    eng = UniversalEngine()
    eng.set_wavelength_axis(wave)
    for name, fn in REF_FILES:
        if name not in gases:
            continue
        ok, msg = eng.add_reference(name, os.path.join(REFDIR, fn), wave_nm=wave)
        if not ok:
            raise RuntimeError(f"{name}: {msg}")
    eng.apply_ils_convolution(ils_extra_px)
    return eng, wave


def window(wave):
    px = np.where((wave >= FIT_NM[0]) & (wave <= FIT_NM[1]))[0].astype(float)
    return px, px[len(px) // 2]


def props_for(gases, sh_val="-6.0, 6.0", sq_val="-0.02, 0.02"):
    """NO2 앵커(Limit), 동반종은 Link — 운영 FitSet과 같은 구조."""
    p = {"NO2": {"sh_mode": "Limit", "sh_val": sh_val,
                 "sq_mode": "Limit", "sq_val": sq_val,
                 "t_ref": 25.0, "t_coeff": 0.0}}
    for g in gases:
        if g != "NO2":
            p[g] = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link",
                    "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}
    return p


def companion_scds(eng, gases, no2):
    """동반 기체를 NO2 중간 수준의 알파 기여 대비 고정 비율로 — closure test와 동일."""
    out = {"NO2": no2}
    ref_amp = SCD_MID * float(np.max(np.abs(eng.raw_references["NO2"])))
    for g in gases:
        if g == "NO2":
            continue
        peak = float(np.max(np.abs(eng.raw_references[g]))) or 1.0
        out[g] = COMPANION_FRAC[g] * ref_amp / peak
    return out


def synthesize(eng, vp, center, scds, shift, squeeze, noise_rms=0.0, rng=None,
               etalon_amp=0.0, etalon_f=ETALON_F, etalon_phase=0.4):
    """알파 = Σ n_g·σ_g(shift/squeeze) + 체비셰프 배경 (+ 에탈론) (+ 잡음).

    배경은 closure test와 같은 계수(0.30, -0.10, 0.05)를 가스 신호 크기로 스케일.
    """
    px = (vp - center) * squeeze + center + shift
    alpha = np.zeros(len(vp))
    for g, n in scds.items():
        alpha = alpha + n * eng.interpolators[g](px)
    x = np.linspace(-1.0, 1.0, len(vp))
    bg = max(float(np.max(np.abs(alpha))), 1e-12)
    alpha = alpha + bg * (0.30 - 0.10 * x + 0.05 * (2 * x ** 2 - 1))
    if etalon_amp:
        alpha = alpha + etalon_amp * bg * np.sin(etalon_f * vp + etalon_phase)
    if noise_rms > 0:
        alpha = alpha + rng.normal(0.0, noise_rms, len(vp))
    return alpha


def recover(eng, fitter, props, vp, center, alpha, poly_order=POLY_ORDER,
            step_limit=20.0, etalon_f=ETALON_F, init_shift=0.0):
    """운영 worker와 같은 회수 경로. 알파 스케일링(1e7급)을 반드시 재현한다 —
    안 하면 least_squares의 절대 허용오차가 theta0에서 만족돼 nfev=1로 끝난다."""
    avg = float(np.mean(alpha))
    scale = (10.0 ** (-np.floor(np.log10(abs(avg))))
             if (abs(avg) < 1e-4 and avg != 0) else 1.0)
    act, fx, lk, t0, lb, ub, bm = fitter.setup_fit_parameters(
        props, init_shift, [init_shift, 1.0], step_limit=step_limit,
        return_bounds=True)
    out, diag = fitter.execute_varpro_fit(
        vp, alpha * scale, np.ones(len(vp)), act, fx, lk, t0, lb, ub, poly_order,
        etalon_f, center, 1.0, props, 25.0, 0.0, False,
        allow_negative_gas=True, return_diagnostics=True, bounds_meta=bm)
    opt_sh, opt_sq, c_gas, _, eamp, _, perr = out
    scd, err = {}, {}
    for i, name in enumerate(eng.gas_list):
        sf = eng.scaling_factors[name] * scale
        mult = eng.multipliers.get(name, 1.0)
        scd[name] = float(c_gas[i] / sf * mult)
        err[name] = float(perr[i] / sf * mult)
    return dict(scd=scd, err=err, shift=float(opt_sh[0]), squeeze=float(opt_sq[0]),
                etalon_amp=float(eamp) / scale, diag=diag)


def profiled_rss(eng, vp, center, alpha, shift, squeeze, poly_order=POLY_ORDER,
                 etalon_f=ETALON_F):
    """VarPro 프로파일 목적함수: 선형 계수를 소거한 뒤의 RSS(shift 고정).

    열 구성은 `execute_varpro_fit`과 동일(gas -> cheb -> sin -> cos). RSS는
    열 스케일링에 불변이라 정규화 없이 비교해도 같다.
    """
    px = (vp - center) * squeeze + center + shift
    cols = [eng.interpolators[g](px) / eng.scaling_factors[g] for g in eng.gas_list]
    x = (2.0 * (vp - vp[0]) / (vp[-1] - vp[0])) - 1.0
    V = chebyshev.chebvander(x, poly_order)
    cols += [V[:, j] for j in range(poly_order + 1)]
    cols += [np.sin(etalon_f * vp), np.cos(etalon_f * vp)]
    A = np.column_stack(cols)
    c, *_ = np.linalg.lstsq(A, alpha, rcond=None)
    r = alpha - A @ c
    return float(r @ r)


# ── G1. 비선형 파라미터 회수 ────────────────────────────────────────────────
def g1_nonlinear_recovery():
    gases = ("NO2", "CHOCHO", "H2O")
    eng, wave = build_engine(gases)
    vp, center = window(wave)
    fitter, props = DoasFitter(eng), props_for(gases)
    rows = []
    for sh in (-4.0, -2.0, -1.0, -0.37, 0.0, 0.37, 1.0, 2.0, 4.0):
        for sq in (0.998, 1.0, 1.002):
            scds = companion_scds(eng, gases, SCD_MID)
            a = synthesize(eng, vp, center, scds, sh, sq)
            r = recover(eng, fitter, props, vp, center, a)
            rows.append(dict(true_shift=sh, true_squeeze=sq,
                             fit_shift=r["shift"], fit_squeeze=r["squeeze"],
                             d_shift=r["shift"] - sh, d_squeeze=r["squeeze"] - sq,
                             no2_rel=(r["scd"]["NO2"] - SCD_MID) / SCD_MID))
    return rows


# ── G2. poly 차수 스윕 ─────────────────────────────────────────────────────
def g2_poly_sweep(n_real=30):
    gases = ("NO2", "CHOCHO", "H2O")
    eng, wave = build_engine(gases)
    vp, center = window(wave)
    fitter, props = DoasFitter(eng), props_for(gases)
    scds = companion_scds(eng, gases, SCD_MID)
    rows = []
    for order in range(0, 9):
        a0 = synthesize(eng, vp, center, scds, FIELD_SHIFT, 1.002)
        r0 = recover(eng, fitter, props, vp, center, a0, poly_order=order)
        rng = np.random.default_rng(20260918)
        got, rep = [], []
        for _ in range(n_real):
            a = synthesize(eng, vp, center, scds, FIELD_SHIFT, 1.002,
                           NOISE_MEASURED, rng)
            rr = recover(eng, fitter, props, vp, center, a, poly_order=order)
            got.append(rr["scd"]["NO2"]); rep.append(rr["err"]["NO2"])
        got, rep = np.array(got), np.array(rep)
        rows.append(dict(poly_order=order,
                         rel_err_noisefree=(r0["scd"]["NO2"] - SCD_MID) / SCD_MID,
                         d_shift_noisefree=r0["shift"] - FIELD_SHIFT,
                         cond_norm=r0["diag"]["cond_normalized"],
                         dof=r0["diag"]["dof"],
                         bias_rel=float(np.mean(got) - SCD_MID) / SCD_MID,
                         scatter_rel=float(np.std(got, ddof=1)) / SCD_MID,
                         reported_rel=float(np.mean(rep)) / SCD_MID,
                         ratio=float(np.std(got, ddof=1) / np.mean(rep))))
    return rows


# ── G3. 모델 불일치 편향 ───────────────────────────────────────────────────
def g3a_ils_mismatch():
    """진실은 더 흐린 ILS, 핏 레퍼런스는 원래 폭. 파장 분산으로 nm 환산도 같이."""
    gases = ("NO2", "CHOCHO", "H2O")
    eng_fit, wave = build_engine(gases)
    vp, center = window(wave)
    disp = float(np.median(np.diff(wave[vp.astype(int)])))   # nm/px
    fitter, props = DoasFitter(eng_fit), props_for(gases)
    rows = []
    for dpx in (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0):
        eng_t, _ = build_engine(gases, ils_extra_px=dpx)
        scds = companion_scds(eng_t, gases, SCD_MID)
        a = synthesize(eng_t, vp, center, scds, FIELD_SHIFT, 1.002)
        r = recover(eng_fit, fitter, props, vp, center, a)
        rows.append(dict(ils_extra_px=dpx, ils_extra_nm=dpx * disp,
                         no2_rel=(r["scd"]["NO2"] - SCD_MID) / SCD_MID,
                         reported_rel=r["err"]["NO2"] / SCD_MID,
                         d_shift=r["shift"] - FIELD_SHIFT,
                         d_squeeze=r["squeeze"] - 1.002))
    return rows, disp


def g3b_unmodeled_etalon():
    """진실에 에탈론을 넣는다. 핏은 f=0.12 고정 sin/cos 두 열만 갖는다."""
    gases = ("NO2", "CHOCHO", "H2O")
    eng, wave = build_engine(gases)
    vp, center = window(wave)
    fitter, props = DoasFitter(eng), props_for(gases)
    scds = companion_scds(eng, gases, SCD_MID)
    rows = []
    for f_true in (0.12, 0.08, 0.20, 0.35):
        for amp in (0.0, 0.01, 0.03, 0.10):
            a = synthesize(eng, vp, center, scds, FIELD_SHIFT, 1.002,
                           etalon_amp=amp, etalon_f=f_true)
            r = recover(eng, fitter, props, vp, center, a)
            rows.append(dict(f_true=f_true, matched=(f_true == ETALON_F),
                             amp_frac=amp,
                             no2_rel=(r["scd"]["NO2"] - SCD_MID) / SCD_MID,
                             reported_rel=r["err"]["NO2"] / SCD_MID,
                             d_shift=r["shift"] - FIELD_SHIFT))
    return rows


def g3c_missing_reference():
    """진실 3종, 핏 1종(NO2만) — 레퍼런스 누락 편향."""
    gases = ("NO2", "CHOCHO", "H2O")
    eng_t, wave = build_engine(gases)
    vp, center = window(wave)
    scds = companion_scds(eng_t, gases, SCD_MID)
    a = synthesize(eng_t, vp, center, scds, FIELD_SHIFT, 1.002)
    rows = []
    for fit_gases in (("NO2", "CHOCHO", "H2O"), ("NO2", "H2O"),
                      ("NO2", "CHOCHO"), ("NO2",)):
        eng_f, _ = build_engine(fit_gases)
        r = recover(eng_f, DoasFitter(eng_f), props_for(fit_gases), vp, center, a)
        rows.append(dict(fit_gases="+".join(fit_gases), n_fit=len(fit_gases),
                         no2_rel=(r["scd"]["NO2"] - SCD_MID) / SCD_MID,
                         reported_rel=r["err"]["NO2"] / SCD_MID,
                         d_shift=r["shift"] - FIELD_SHIFT))
    return rows


# ── G4. shift 인입영역 ─────────────────────────────────────────────────────
def g4_basin():
    """진실 shift = 실측 중앙값 -1.96 px. theta0 = 0 에서 출발(Stage-1과 동일).

    landscape: 선형 계수를 소거한 프로파일 목적함수를 shift 격자에서 직접 평가.
    """
    gases = ("NO2", "CHOCHO", "H2O")
    eng, wave = build_engine(gases)
    vp, center = window(wave)
    fitter, props = DoasFitter(eng), props_for(gases)
    scds = companion_scds(eng, gases, SCD_MID)
    a = synthesize(eng, vp, center, scds, FIELD_SHIFT, 1.002)
    rows = []
    for step in (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 20.0):
        r = recover(eng, fitter, props, vp, center, a, step_limit=step)
        rows.append(dict(step_limit=step, fit_shift=r["shift"],
                         d_shift=r["shift"] - FIELD_SHIFT,
                         no2_rel=(r["scd"]["NO2"] - SCD_MID) / SCD_MID,
                         termination=r["diag"]["solver_termination"],
                         bound_state=r["diag"]["theta_bound_state"]))
    grid = np.arange(-6.0, 6.001, 0.05)
    land = [profiled_rss(eng, vp, center, a, s, 1.002) for s in grid]
    return rows, grid, np.array(land)


# ── 게이트 ─────────────────────────────────────────────────────────────────
_n_pass = _n_fail = 0


def check(label, ok, detail=""):
    global _n_pass, _n_fail
    if ok:
        _n_pass += 1
        print(f"  PASS  {label}")
    else:
        _n_fail += 1
        print(f"  FAIL  {label}  {detail}")


def main():
    global REFDIR
    for d in REF_DIRS:
        if d and all(os.path.exists(os.path.join(d, fn)) for _, fn in REF_FILES):
            REFDIR = d
            break
    if REFDIR is None:
        print("SKIP  실제 레퍼런스(Ref_*_Dynamic-ILS-Applied.dat)를 못 찾았다.")
        return 0
    print(f"refdir: {REFDIR}")

    print("[C1] 비선형 파라미터 회수 (shift/squeeze) — closure test가 판정하지 않는 것")
    g1 = g1_nonlinear_recovery()
    dsh = max(abs(r["d_shift"]) for r in g1)
    dsq = max(abs(r["d_squeeze"]) for r in g1)
    sgn = all(np.sign(r["fit_shift"]) == np.sign(r["true_shift"])
              for r in g1 if r["true_shift"] != 0)
    check(f"max|d_shift| {dsh:.2e} px < 1e-6", dsh < 1e-6)
    check(f"max|d_squeeze| {dsq:.2e} < 1e-8", dsq < 1e-8)
    check("shift 부호 자기일관 (진실 != 0 전수)", sgn)

    print("[C2] poly 차수 스윕 — 과소적합만 위험하다")
    g2 = g2_poly_sweep()
    hi = [r for r in g2 if r["poly_order"] >= 2]
    worst = max(abs(r["rel_err_noisefree"]) for r in hi)
    check(f"차수 2~8 무잡음 상대오차 {worst:.2e} < 1e-6 (배경 과적합 누출 없음)", worst < 1e-6)
    for r in hi:
        check(f"차수 {r['poly_order']} 산포/보고 {r['ratio']:.2f} in 0.5~10",
              0.5 <= r["ratio"] <= 10.0)
    r0 = [r for r in g2 if r["poly_order"] == 0][0]
    check(f"차수 0 편향 {r0['bias_rel']:+.2e} > 보고 1sigma {r0['reported_rel']:.2e} "
          f"(과소적합은 보고오차가 덮지 못한다 — 알려진 위험)",
          abs(r0["bias_rel"]) > r0["reported_rel"])

    print("[C3a] ILS 폭 불일치 — 보고오차가 덮지 못하는 계통")
    g3a, disp = g3a_ils_mismatch()
    print(f"        분산 {disp:.4f} nm/px")
    big = [r for r in g3a if r["ils_extra_px"] >= 1.0]
    check("추가 FWHM >= 1px에서 편향이 항상 음수 (NO2 과소평가)",
          all(r["no2_rel"] < 0 for r in big))
    check("편향이 FWHM 오차와 함께 단조증가",
          all(abs(big[i]["no2_rel"]) < abs(big[i + 1]["no2_rel"]) for i in range(len(big) - 1)))
    for r in big:
        print(f"        +{r['ils_extra_px']:.1f}px ({r['ils_extra_nm']:.4f}nm): "
              f"NO2 {r['no2_rel']:+.3e}  보고 {r['reported_rel']:.3e}  "
              f"비 {abs(r['no2_rel']) / r['reported_rel']:.1f}")
    r025 = [r for r in g3a if r["ils_extra_px"] == 0.25][0]
    r000 = [r for r in g3a if r["ils_extra_px"] == 0.0][0]
    check("문서화된 한계: 추가 FWHM 0.25px는 무효 (커널이 정수 px 격자)",
          r025["no2_rel"] == r000["no2_rel"])

    print("[C3b] 미모형 에탈론 — 주파수가 맞으면 선형 sin/cos가 정확히 흡수한다")
    g3b = g3b_unmodeled_etalon()
    for r in g3b:
        if r["matched"]:
            check(f"f=0.12 (핏 가정) A={r['amp_frac']:.0%}: 상대오차 {r['no2_rel']:.1e} < 1e-6",
                  abs(r["no2_rel"]) < 1e-6)
    for r in g3b:
        if not r["matched"] and r["amp_frac"] == 0.01:
            print(f"        f={r['f_true']:.2f} A=1%: NO2 {r['no2_rel']:+.3e}  "
                  f"보고 {r['reported_rel']:.3e}  d_shift {r['d_shift']:+.3f}px")

    print("[C3c] 레퍼런스 누락 편향")
    g3c = g3c_missing_reference()
    full = [r for r in g3c if r["n_fit"] == 3][0]
    check(f"진실과 같은 3종 핏은 기계 정밀도 ({full['no2_rel']:.1e})", abs(full["no2_rel"]) < 1e-6)
    for r in g3c:
        if r["n_fit"] < 3:
            print(f"        {r['fit_gases']:>14}: NO2 {r['no2_rel']:+.3e}  "
                  f"보고 {r['reported_rel']:.3e}  비 {abs(r['no2_rel']) / r['reported_rel']:.1f}")

    print("[C4] shift 인입영역 — 단봉이므로 실패는 보폭 상자 탓이다")
    g4, grid, land = g4_basin()
    loc = [grid[i] for i in range(1, len(land) - 1)
           if land[i] < land[i - 1] and land[i] < land[i + 1]]
    check(f"프로파일 목적함수의 국소최소 {len(loc)}개 == 1 (단봉)", len(loc) == 1,
          str(loc))
    check(f"그 최소가 진실 -1.96px 근처 ({loc[0] if loc else float('nan'):+.2f})",
          bool(loc) and abs(loc[0] - FIELD_SHIFT) < 0.1)
    for r in g4:
        if r["step_limit"] >= 2.0:
            check(f"step_limit {r['step_limit']:.1f}: |d_shift| {abs(r['d_shift']):.1e} < 1e-6",
                  abs(r["d_shift"]) < 1e-6)
        else:
            check(f"step_limit {r['step_limit']:.2f}: 진실 미달을 CONVERGED로 보고하지 않는다 "
                  f"({r['bound_state']}, NO2 {r['no2_rel']:+.2e})",
                  r["bound_state"] != "CONVERGED")

    print(f"\nvarpro synthetic-ext tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
