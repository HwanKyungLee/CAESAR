"""core/fit_physics.py — Tier-2 물리 건전성 심판(순수·Qt없음)
================================================================

핏의 **자기일관성(Tier-1: 안정·perr·백색)** 은 과적합으로 만족시킬 수 있어 심판이 못 된다.
이 모듈은 외부데이터 없이 **핏된 양이 물리적으로 말이 되는지**로 과적합 크러치를 잡는다.

두 축
-----
1. `differential_collinearity` — 창 안에서 레퍼런스들의 **차등단면**(poly 제거)이 서로
   얼마나 분리되나. 타깃과 어떤 종의 공선성이 높으면 둘의 분해가 임의적 → 그 종을 넣든
   빼든 둘 다 못 믿음(degeneracy 능선). **데이터 불필요, 레퍼런스 기하만.**
2. `fitted_amount_health` — 스캔들에 걸쳐 각 ref의 핏 계수가 물리적으로 타당한가.
   O4처럼 **거의 상수여야 하는 종이 출렁이면 = 설명 안 되는 구조를 빨아들이는 과적합**.
   타깃과 어떤 종의 계수가 강하게 **반상관**이면 트레이드오프(서로 훔침)의 증거.
"""
from __future__ import annotations

import numpy as np
from numpy.polynomial import chebyshev

from core.param_optimizer import fit_scan, _require_bool

# judge_reference와 param_optimizer의 차등공선성 게이트가 공유하는 문턱(단일 출처 원칙).
COLLIN_HI_DEFAULT = 0.7


# ──────────────────────────────────────────────────────────────────────────
def _diff_unit(vec, poly_deg):
    """poly(체비셰프) 사영 제거 → 차등성분 → 단위노름. poly에 다 흡수되면 0벡터."""
    v = np.asarray(vec, float)
    x = np.linspace(-1, 1, len(v))
    T = chebyshev.chebvander(x, poly_deg)
    c, *_ = np.linalg.lstsq(T, v, rcond=None)
    d = v - T @ c
    n = np.linalg.norm(d)
    return (d / n) if n > 1e-300 else np.zeros_like(d)


def differential_collinearity(eng, refs, px_min, px_max, poly_deg):
    """창 안 레퍼런스 차등단면의 쌍별 |r| + 각 ref의 다중상관(나머지 전체 대비).

    반환: {"pairwise": {(a,b): |r|}, "multiple_R": {ref: R (0~1)}}
    다중상관 R = ref_unit을 나머지 ref들로 회귀했을 때 설명력 √(R²). 1에 가까우면
    그 ref는 다른 종들의 조합으로 흉내 가능 → 분해 불가(그 종은 창에서 판별 안 됨)."""
    sl = slice(px_min, px_max + 1)
    names = [n for n in refs if n in eng.raw_references]
    units = {n: _diff_unit(np.asarray(eng.raw_references[n], float)[sl], poly_deg)
             for n in names}

    pairwise = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pairwise[(a, b)] = float(abs(np.dot(units[a], units[b])))

    multiple_R = {}
    for tgt in names:
        others = [units[n] for n in names if n != tgt]
        if not others or np.linalg.norm(units[tgt]) == 0:
            multiple_R[tgt] = float("nan")
            continue
        A = np.column_stack(others)
        beta, *_ = np.linalg.lstsq(A, units[tgt], rcond=None)
        resid = units[tgt] - A @ beta
        r2 = min(max(1.0 - float(resid @ resid), 0.0), 1.0)
        multiple_R[tgt] = float(np.sqrt(r2))
    return {"pairwise": pairwise, "multiple_R": multiple_R}


# ──────────────────────────────────────────────────────────────────────────
def _cv(xs):
    xs = np.asarray([x for x in xs if np.isfinite(x)], float)
    if len(xs) < 2:
        return float("nan")
    m = np.mean(xs)
    return float(np.std(xs) / (abs(m) + 1e-30))


# ──────────────────────────────────────────────────────────────────────────
def air_number_density(T_C, P_mbar):
    return 2.68678e19 * (P_mbar / 1013.25) * (273.15 / (T_C + 273.15))


def theoretical_amount(species, T_C, P_mbar):
    """retrieved N과 **같은 규약**(N = coeff·mult/scale, 수밀도式)의 이론 기대량. 모르면 None.

    이게 T2의 결정타 — 자기일관성 지표들이 전부 속아도 이건 안 속는다.

    O4: [O2]² = (0.2095·n_air)². 이 값은 **물리적 상한**이다:
      알파의 I0가 ZA(=O2를 포함한 공기)면 O4 흡수는 ambient·ZA 양쪽에 동일하게 있어
      α에서 상쇄되므로 실제 기대값은 ~0에 가깝다. 즉 "대기 전체가 다 기여한다"고 최대로
      쳐줘도 이 값이 천장이다. **이 상한을 넘으면 어떤 가정에서도 물리적으로 불가능**
      → O4 아닌 구조(콜드 고정패턴 등)를 흡수 중 = 과적합 확정.
    """
    if str(species).upper() == "O4":
        n_air = air_number_density(T_C, P_mbar)
        return float((0.2095 * n_air) ** 2)
    return None


def retrieved_amount(eng, coeff, species):
    """핏 계수 → retrieved N (수밀도式). 설계열이 정규화단면(ref/scale)이라
    α = coeff·(σ/peakσ) = σ·N  →  N = coeff·mult/scale. (mult는 scale에 이미 포함돼 상쇄)"""
    sc = eng.scaling_factors.get(species, 1.0)
    mu = eng.multipliers.get(species, 1.0)
    return float(coeff * mu / sc) if sc else float("nan")


def fitted_amount_health(scans, eng, fitter, ref_props, px_min, px_max, poly_deg,
                         step_limit, target="NO2", constant_species=("O4",), *,
                         allow_negative_gas):
    """스캔들에 걸쳐 각 ref 핏 계수를 모아 물리 타당성 평가.

    반환 dict:
      cv[ref]              : 계수 변동계수(상수여야 할 종이 크면 과적합 신호)
      corr_with_target[ref]: 타깃 계수와의 스캔간 상관(강한 음수=트레이드오프)
      target_cv            : 타깃 계수 CV
      constant_flag[ref]   : constant_species 중 CV가 타깃보다 큰가(=상수여야 하는데 더 출렁)
    """
    allow_negative_gas = _require_bool(allow_negative_gas)
    series = {g: [] for g in eng.gas_list}
    abs_ratio_s = {g: [] for g in eng.gas_list}   # fitted N / 이론 상한(아는 종만)
    tgt = []
    for (wave, alpha, T_C, P_mbar) in scans:
        try:
            r = fit_scan(eng, fitter, ref_props, wave, alpha, T_C, P_mbar,
                         px_min, px_max, poly_deg, step_limit, target,
                         allow_negative_gas=allow_negative_gas)
        except Exception:                 # noqa: BLE001
            continue
        for g in eng.gas_list:
            c = r["coeffs"].get(g, np.nan)
            series[g].append(c)
            theo = theoretical_amount(g, T_C, P_mbar)
            if theo:
                abs_ratio_s[g].append(abs(retrieved_amount(eng, c, g) / theo))
        tgt.append(r["coeffs"].get(target, np.nan))

    tgt = np.asarray(tgt, float)
    target_cv = _cv(tgt)
    cv, corr = {}, {}
    for g in eng.gas_list:
        arr = np.asarray(series[g], float)
        cv[g] = _cv(arr)
        m = min(len(arr), len(tgt))
        if m >= 3 and g != target:
            aa, tt = arr[:m], tgt[:m]
            ok = np.isfinite(aa) & np.isfinite(tt)
            corr[g] = float(np.corrcoef(aa[ok], tt[ok])[0, 1]) if ok.sum() >= 3 else float("nan")
        else:
            corr[g] = float("nan")

    constant_flag = {}
    for g in constant_species:
        if g in cv and np.isfinite(cv[g]) and np.isfinite(target_cv):
            # 상수여야 할 종이 타깃보다 더 출렁이면 = 쓰레기 청소부(과적합) 강한 신호
            constant_flag[g] = bool(cv[g] > max(target_cv, 0.15))

    # 절대량 비율(이론 상한 대비) — 아는 종만. >1이면 물리적으로 불가능한 양.
    abs_ratio = {g: float(np.median(v)) for g, v in abs_ratio_s.items() if v}
    return dict(cv=cv, corr_with_target=corr, target_cv=target_cv,
                constant_flag=constant_flag, abs_ratio=abs_ratio, n=int(len(tgt)))


# ──────────────────────────────────────────────────────────────────────────
def judge_reference(eng, fitter, scans, ref_props_without, ref_props_with,
                    px_min, px_max, poly_deg, step_limit,
                    candidate="O4", target="NO2", collin_hi=COLLIN_HI_DEFAULT,
                    abs_max_ratio=3.0, *, allow_negative_gas):
    """후보 레퍼런스(예: O4)를 넣을지 뺄지 **물리로** 판정(Tier-1 안정성 아님).

    ref_props_with는 candidate가 gas_list에 있는 엔진에 대응해야 한다(엔진은 호출부가 구성).
    판정 규칙:
      * 창에서 target↔candidate 공선성(다중상관 포함)이 높다 → 분해 임의적 → 넣어도 못 믿음.
      * candidate 계수가 (상수여야 하는데) 출렁이거나 target과 강한 반상관 → 과적합 크러치.
      둘 중 하나라도 참이면 '제외 권고'(빼는 게 물리적으로 옳음)."""
    allow_negative_gas = _require_bool(allow_negative_gas)
    diag = differential_collinearity(eng, list(eng.gas_list), px_min, px_max, poly_deg)
    pair = diag["pairwise"].get((target, candidate),
                                diag["pairwise"].get((candidate, target), float("nan")))
    multR = diag["multiple_R"].get(candidate, float("nan"))

    health = fitted_amount_health(scans, eng, fitter, ref_props_with,
                                  px_min, px_max, poly_deg, step_limit, target,
                                  constant_species=(candidate,),
                                  allow_negative_gas=allow_negative_gas)
    cand_cv = health["cv"].get(candidate, float("nan"))
    corr = health["corr_with_target"].get(candidate, float("nan"))
    abs_ratio = health.get("abs_ratio", {}).get(candidate, float("nan"))

    collinear = np.isfinite(pair) and pair > collin_hi
    unstable = health["constant_flag"].get(candidate, False)
    trade_off = np.isfinite(corr) and corr < -0.5
    # ★결정타: 이론 상한을 넘는 양을 흡수하면 어떤 가정에서도 물리적으로 불가능 = 과적합.
    # (공선성·상수성은 상수 아티팩트에 속을 수 있음 — O4 사례에서 실증. 이 기준만 안 속았다.)
    impossible = np.isfinite(abs_ratio) and abs_ratio > abs_max_ratio

    exclude = collinear or unstable or trade_off or impossible
    reasons = []
    if impossible:
        reasons.append(f"★절대량 {abs_ratio:.0f}배(이론 상한의 {abs_max_ratio:g}배 초과) "
                       f"— 물리적으로 불가능한 양 흡수=과적합")
    if collinear:
        reasons.append(f"NO2↔{candidate} 공선성 {pair:.2f}>{collin_hi}(분해 임의적)")
    if unstable:
        reasons.append(f"{candidate} 계수 CV {cand_cv*100:.0f}%>타깃 {health['target_cv']*100:.0f}%(상수여야 하는데 출렁=과적합)")
    if trade_off:
        reasons.append(f"NO2↔{candidate} 계수 반상관 {corr:.2f}(서로 훔침)")
    return dict(candidate=candidate, exclude=exclude,
                pair_collinearity=pair, multiple_R=multR,
                candidate_cv=cand_cv, corr_with_target=corr, abs_ratio=abs_ratio,
                impossible=impossible,
                target_cv=health["target_cv"], n=health["n"],
                verdict=("제외 권고(물리)" if exclude else "포함 타당(물리)"),
                reasons=reasons)
