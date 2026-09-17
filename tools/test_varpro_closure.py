"""합성 스펙트럼 closure test — 알려진 SCD를 넣고 되찾는가 (사양 B).

왜 이게 필요한가
----------------
실측 데이터로는 **정답을 모른다.** 잔차가 작다·오차가 작다는 건 자기일관성(T1)일
뿐이고, 자기일관성만으로 핏을 심판하면 과적합에 상을 준다(CLAUDE.md 원칙 2).
정답을 아는 유일한 방법은 정답을 **우리가 넣는** 것이다. 이 파일이 Augur VarPro의
유일한 **정확도** 검증이고, A9(열 정규화)의 진짜 게이트다.

무엇을 쓰는가
-------------
합성용 단면을 따로 만들지 않는다 — 실제 계기의 `Ref_*_Dynamic-ILS-Applied.dat`와
그 파장 캘리브를 그대로 쓴다(`tests/data/wv_cal_roi1/`, 2026 여수 PNs/roi1 사본).
합성도 핏도 같은 보간기를 통과하므로 잡음 0이면 회수는 **수치 정확도 문제**만 남는다.

격자
----
  NO2 수농도 : 1e10 ~ 1e13 molec/cm³ (4단계, 3자리 — 검출한계 훨씬 아래~400ppb)
  shift      : 0, ±2, ±4 px      (squeeze는 1.002 고정으로 같이 검증)
  잡음       : 0 / 실측 수준 / 실측 2배 / 실측 수준의 **AR(1) 상관 잡음**
  기체수     : 1종(NO2) · 3종(NO2+CHOCHO+H2O)

판정
----
1. 잡음 0 → 모든 격자점 상대오차 < 1e-6  (수치 정확도)
2. 잡음 有 → 편향(bias)이 보고된 오차 이내
3. `측정 산포 / 보고 오차` 비율을 **보고**한다. 이 값은 논문에 싣는 **측정값**이지
   통과 조건이 아니라, 게이트는 0.5~10으로 느슨하게 건다.
   측정 결과(2026-09-17): 백색 잡음 0.91~0.92, AR(1) ρ=0.9 상관 잡음 3.41.
   → 공분산 식 자체는 맞다. Stutz & Platt(1996)이 보고한 2~3배 과소평가는
     **잔차의 상관** 때문이지 오차 계산식 때문이 아니다.

실측 잡음 수준
--------------
2026-06-14 PNs 알파(444.1~470.6nm, 551px, poly3) 20스캔 잔차 RMS 중앙값
6.16e-9 cm⁻¹ (min 2.73e-9 / max 6.63e-9). 이 값을 NOISE_MEASURED로 쓴다.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.doas_fit import DoasFitter
from core.engine import UniversalEngine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 순서대로 찾는다. 첫 번째는 저장소 동봉 픽스처라 CI에서도 돈다.
REF_DIRS = [
    os.environ.get("AUGUR_WVCAL_DIR", ""),
    os.path.join(ROOT, "tests", "data", "wv_cal_roi1"),
    os.path.join(ROOT, "dist", "oculus_deps", "wv_cal", "roi1"),
    r"C:\GHL\2026 yeosu\Output\wv_cal\roi1",
    r"C:\Doasis_Work\Output\wv_cal\roi1",
]
REF_FILES = [("NO2", "Ref_NO2_Dynamic-ILS-Applied.dat"),
             ("CHOCHO", "Ref_CHOCHO_Dynamic-ILS-Applied.dat"),
             ("H2O", "Ref_H2O-HITRAN_Dynamic-ILS-Applied.dat")]

FIT_NM = (444.1, 470.6)          # 운영 PNs 핏창
POLY_ORDER = 3                   # 운영 PNs poly 차수
TRUE_SQUEEZE = 1.002
NOISE_MEASURED = 6.16e-9         # cm⁻¹ — 위 주석의 실측 잔차 RMS 중앙값
# NO2 수농도(molec/cm^3). BBCEAS 알파는 α=Σ n_i·σ_i 이므로 **수농도**다(주길이 SCD 아님).
# 2.5e19 = 대기 수농도라 1e10 ≈ 0.4 ppt(검출한계 훨씬 아래) ~ 1e13 ≈ 400 ppb(포화 근처).
# 3자리 범위.
SCD_GRID = (1e10, 1e11, 1e12, 1e13)
SHIFT_GRID = (0.0, -2.0, 2.0, -4.0, 4.0)
# 동반 기체는 **NO2 중간 수준의 α 기여 대비 비율**로 준다. 수농도로 직접 주면
# 레퍼런스 파일마다 다른 단위 스케일(H2O-HITRAN은 max 8.6e-7, NO2는 7.1e-19)에
# 발이 걸린다 — 검증 대상은 단위 환산이 아니라 회수 정확도다.
COMPANION_FRAC = {"CHOCHO": 0.05, "H2O": 0.30}
SCD_MID = 1e12
N_NOISE_REALIZATIONS = 60

_n_pass = _n_fail = 0


def check(label, ok, detail=""):
    global _n_pass, _n_fail
    if ok:
        _n_pass += 1
        print(f"  PASS  {label}")
    else:
        _n_fail += 1
        print(f"  FAIL  {label}  {detail}")


def find_refdir():
    for d in REF_DIRS:
        if d and all(os.path.exists(os.path.join(d, fn)) for _, fn in REF_FILES):
            return d
    return None


def read_col(path):
    return np.array([float(l) for l in open(path, encoding="utf-8", errors="replace")
                     if l.strip() and not l.lstrip().startswith("#")])


def build_engine(refdir, gases):
    """엔진 구성은 **운영 경로 그대로** — add_reference + apply_ils_convolution(0.0).
    (레퍼런스는 이미 ILS가 적용된 파일이라 추가 컨볼루션 없음.)"""
    calib = [f for f in os.listdir(refdir) if f.startswith("Calib")]
    if not calib:
        raise FileNotFoundError(f"Calib*.txt not found in {refdir}")
    wave = read_col(os.path.join(refdir, calib[0]))
    eng = UniversalEngine()
    eng.set_wavelength_axis(wave)
    for name, fn in REF_FILES:
        if name not in gases:
            continue
        ok, msg = eng.add_reference(name, os.path.join(refdir, fn), wave_nm=wave)
        if not ok:
            raise RuntimeError(f"{name}: {msg}")
    eng.apply_ils_convolution(0.0)
    return eng, wave


def props_for(gases):
    """NO2가 앵커(Limit ±6px), 나머지는 Link — 운영 FitSet과 같은 구조.
    step_limit은 크게 준다: 이 테스트는 회수 정확도를 보는 것이지 보폭 제한이
    아니다(그건 tools/test_step_limited.py 몫)."""
    p = {"NO2": {"sh_mode": "Limit", "sh_val": "-6.0, 6.0",
                 "sq_mode": "Limit", "sq_val": "-0.02, 0.02",
                 "t_ref": 25.0, "t_coeff": 0.0}}
    for g in gases:
        if g == "NO2":
            continue
        p[g] = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link",
                "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}
    return p


def make_noise(rng, n, rms, ar1=0.0):
    """백색(ar1=0) 또는 AR(1) 상관 잡음. 둘 다 RMS가 `rms`가 되게 정규화한다.

    왜 상관 잡음이 필요한가 — 실측 DOAS 잔차는 백색이 아니다(에탈론 잔재·구조
    누락·파장축 미세오차). 백색 잡음만 넣으면 `산포/보고오차`가 1 근처로 나와
    "오차 보고가 정확하다"는 결론이 나오는데, 그건 잡음 모델이 낙관적이어서다.
    Stutz & Platt(1996)이 2~3배를 보고한 것이 바로 이 상관 성분 때문이다."""
    w = rng.normal(0.0, 1.0, n)
    if ar1 <= 0:
        return w * rms
    x = np.empty(n)
    x[0] = w[0]
    for i in range(1, n):
        x[i] = ar1 * x[i - 1] + w[i]
    return x / np.std(x) * rms


def companion_scds(eng, gases, base):
    """동반 기체 계수를 NO2 중간 수준의 α 기여 대비 고정 비율로 환산한다."""
    out = dict(base)
    ref_amp = SCD_MID * float(np.max(np.abs(eng.raw_references["NO2"])))
    for g in gases:
        if g == "NO2":
            continue
        peak = float(np.max(np.abs(eng.raw_references[g]))) or 1.0
        out[g] = COMPANION_FRAC[g] * ref_amp / peak
    return out


def synthesize(eng, vp, center, scds, shift, squeeze, noise_rms, rng, ar1=0.0):
    """알파 = Σ SCD_g·σ_g(shift/squeeze 적용) + 다항식 배경 (+ 잡음).

    핏이 쓰는 것과 **같은 보간기**로 만든다. 그래야 잡음 0에서 남는 오차가
    순수하게 선형대수의 수치 오차다."""
    px = (vp - center) * squeeze + center + shift
    alpha = np.zeros(len(vp))
    for g, scd in scds.items():
        alpha = alpha + scd * eng.interpolators[g](px)
    # 알려진 다항식 배경 — 가스 신호와 같은 자릿수로(배경이 압도하면 회수가 쉬워져
    # 검증이 무의미해진다).
    x = np.linspace(-1.0, 1.0, len(vp))
    bg_scale = max(float(np.max(np.abs(alpha))), 1e-12)
    alpha = alpha + bg_scale * (0.30 - 0.10 * x + 0.05 * (2 * x ** 2 - 1))
    if noise_rms > 0:
        alpha = alpha + make_noise(rng, len(vp), noise_rms, ar1)
    return alpha


def recover(eng, fitter, props, vp, center, alpha, etalon_f=0.12):
    """핏 → (회수 SCD dict, 보고 오차 dict, shift, squeeze, 진단).

    회수식은 운영 worker와 같다: SCD = c_g / scaling_factor × multiplier.

    ⚠ **운영 정규화(alpha × scale_factor)를 반드시 재현해야 한다.** 알파는 ~1e-7이라
    그대로 넣으면 `least_squares`의 **절대** 허용오차(gtol=1e-8)가 θ0에서 이미 만족돼
    nfev=1로 끝난다 — shift/squeeze가 한 발짝도 안 움직인 채 CONVERGED가 나온다.
    `gui/worker.py`와 `core/param_optimizer.py`가 하는 것과 같은 스케일이다."""
    avg = float(np.mean(alpha))
    scale = (10.0 ** (-np.floor(np.log10(abs(avg))))
             if (abs(avg) < 1e-4 and avg != 0) else 1.0)
    act, fx, lk, t0, lb, ub, bm = fitter.setup_fit_parameters(
        props, 0.0, [0.0, 1.0], step_limit=20.0, return_bounds=True)
    out, diag = fitter.execute_varpro_fit(
        vp, alpha * scale, np.ones(len(vp)), act, fx, lk, t0, lb, ub, POLY_ORDER,
        etalon_f, center, 1.0, props, 25.0, 0.0, False,
        allow_negative_gas=True, return_diagnostics=True, bounds_meta=bm)
    opt_sh, opt_sq, c_gas, _, _, _, perr = out
    scd, err = {}, {}
    for i, name in enumerate(eng.gas_list):
        sf = eng.scaling_factors[name] * scale
        mult = eng.multipliers.get(name, 1.0)
        scd[name] = float(c_gas[i] / sf * mult)
        err[name] = float(perr[i] / sf * mult)
    return scd, err, float(opt_sh[0]), float(opt_sq[0]), diag


# ──────────────────────────────────────────────────────────────────────────
def test_noise_free_recovery(ctx):
    print("[1] 잡음 0 — 모든 격자점 상대오차 < 1e-6")
    worst = 0.0
    worst_at = None
    conds = []
    for gases in (("NO2",), ("NO2", "CHOCHO", "H2O")):
        eng, wave = build_engine(ctx["refdir"], gases)
        px = np.where((wave >= FIT_NM[0]) & (wave <= FIT_NM[1]))[0]
        vp = px.astype(float)
        center = vp[len(vp) // 2]
        fitter = DoasFitter(eng)
        props = props_for(gases)
        for scd_true in SCD_GRID:
            for shift in SHIFT_GRID:
                scds = companion_scds(eng, gases, {"NO2": scd_true})
                alpha = synthesize(eng, vp, center, scds, shift, TRUE_SQUEEZE,
                                   0.0, None)
                got, _, sh, sq, diag = recover(eng, fitter, props, vp, center, alpha)
                rel = abs(got["NO2"] - scd_true) / scd_true
                conds.append((diag["cond_raw"], diag["cond_normalized"]))
                if rel > worst:
                    worst, worst_at = rel, (len(gases), scd_true, shift, sh, sq)
    check(f"최악 상대오차 {worst:.3e} < 1e-6", worst < 1e-6, str(worst_at))
    cr = float(np.median([c[0] for c in conds]))
    cn = float(np.median([c[1] for c in conds]))
    print(f"        cond(A) 중앙값: 정규화 전 {cr:.3e} -> 후 {cn:.3e}")
    check(f"정규화 후 cond < 1e6 ({cn:.3e})", cn < 1e6)
    ctx["cond"] = (cr, cn)
    ctx["worst_rel"] = worst


def test_noisy_bias_and_scatter(ctx):
    print("[2] 잡음 有 — 편향 <= 보고 오차, 그리고 산포/보고오차 비율")
    gases = ("NO2", "CHOCHO", "H2O")
    eng, wave = build_engine(ctx["refdir"], gases)
    px = np.where((wave >= FIT_NM[0]) & (wave <= FIT_NM[1]))[0]
    vp = px.astype(float)
    center = vp[len(vp) // 2]
    fitter = DoasFitter(eng)
    props = props_for(gases)
    rows = []
    for scd_true in (1e11, 1e12):
        for noise, ar1 in ((NOISE_MEASURED, 0.0), (2 * NOISE_MEASURED, 0.0),
                           (NOISE_MEASURED, 0.9)):
            rng = np.random.default_rng(20260917)
            got, rep = [], []
            for _ in range(N_NOISE_REALIZATIONS):
                scds = companion_scds(eng, gases, {"NO2": scd_true})
                alpha = synthesize(eng, vp, center, scds, 0.0, TRUE_SQUEEZE,
                                   noise, rng, ar1)
                s, e, _, _, _ = recover(eng, fitter, props, vp, center, alpha)
                got.append(s["NO2"]); rep.append(e["NO2"])
            got = np.array(got); rep = np.array(rep)
            bias = float(np.mean(got) - scd_true)
            scatter = float(np.std(got, ddof=1))
            reported = float(np.mean(rep))
            ratio = scatter / reported if reported > 0 else float("nan")
            rows.append((scd_true, noise, ar1, bias, scatter, reported, ratio))
            print(f"        SCD={scd_true:.0e} noise={noise:.2e} ar1={ar1:.1f}: "
                  f"bias={bias:+.3e} scatter={scatter:.3e} reported={reported:.3e} "
                  f"ratio={ratio:.2f}")
            check(f"편향 <= 보고오차 (SCD={scd_true:.0e}, noise={noise:.1e}, ar1={ar1})",
                  abs(bias) <= reported, f"bias={bias:.3e} rep={reported:.3e}")
            # 게이트는 느슨하다 — 이 비율은 논문에 싣는 **측정값**이다.
            # 1 근처로 내려오면 오차 과소보고, 10을 넘으면 뭔가 깨진 것.
            check(f"산포/보고오차가 0.5~10 안 (ar1={ar1}: {ratio:.2f})",
                  0.5 <= ratio <= 10.0)
    ctx["noisy"] = rows


def main():
    refdir = find_refdir()
    if refdir is None:
        print("SKIP  실제 레퍼런스(Ref_*_Dynamic-ILS-Applied.dat)를 못 찾았다.")
        print("      AUGUR_WVCAL_DIR 로 지정하거나 tests/data/wv_cal_roi1/ 을 채울 것.")
        return 0
    print(f"refdir: {refdir}")
    ctx = {"refdir": refdir}
    test_noise_free_recovery(ctx)
    test_noisy_bias_and_scatter(ctx)
    print(f"\nvarpro closure tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
