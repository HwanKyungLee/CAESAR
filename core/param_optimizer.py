"""core/param_optimizer.py — 핏 파라미터 자동 최적화(순수·Qt없음)
=================================================================

**레퍼런스와 핏레인지는 고정**(사용자 FitSet json)이라고 보고, 그 위에서 최적의
파라미터(poly 차수, ref별 shift/squeeze 정책+크기, t_coeff)를 찾는다.

설계 헌장(데이터 무결성)
------------------------
* 목표는 잔차 RMS 최소화가 **아니다**. → "농도가 안 움직이고 shift가 물리적으로 안정한 채
  잔차를 희게 만드는 **가장 단순한** 세팅"(Occam + 헌장③ 입증책임은 자유도 더하는 쪽).
* shift/squeeze **크기(bounds)는 blind 그리드서치가 아니라** 넓게 풀어 실제 핏된 값의 분포를
  측정해 거기에 맞춘다 → 데이터가 bounds를 정한다(ANs 비대칭 -10,0.5도 데이터가 그러면 재현).
* 정규화(Tikhonov/Robust/Kalman)·Neg·QC는 여기서 **최적화하지 않는다**(구조를 가리는 화장·
  정책 결정 — 원칙 default). 이 모듈은 A(진짜 탐색대상)만 다룬다.

순수 모듈: engine/fitter/알파배열만 받는다(엔진빌드·I/O는 호출부).
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import interp1d
from numpy.polynomial import chebyshev


def air_number_density(T_C, P_mbar):
    return 2.68678e19 * (P_mbar / 1013.25) * (273.15 / (T_C + 273.15))


# ──────────────────────────────────────────────────────────────────────────
def _seed_shift(fitter, pixel_idx, optical_depth, poly_deg, ref_props, target,
                seed_range, seed_step, sq_range=0.01, sq_step=0.001):
    """전역 격자탐색으로 초기 (shift, squeeze) 추정 — 비볼록 지형 대응. 실패시 (0.0, 1.0)."""
    props = ref_props.get(target, {})
    if props.get("sh_mode") not in ("Limit", "Free"):
        return 0.0, 1.0
    lo, hi = -abs(seed_range), abs(seed_range)
    if props.get("sh_mode") == "Limit":
        try:
            g_lo, g_hi = map(float, str(props.get("sh_val", "")).split(","))
            lo, hi = max(lo, g_lo), min(hi, g_hi)
        except Exception:
            pass
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return 0.0, 1.0
    def _rms(sh, sq):
        try:
            A = fitter.engine.get_basis_matrix(pixel_idx, float(sh), float(sq), poly_deg)
            coef, *_ = np.linalg.lstsq(A, optical_depth, rcond=None)
            return float(np.sqrt(np.mean((optical_depth - A @ coef) ** 2)))
        except Exception:                 # noqa: BLE001
            return np.inf

    # 2단 시딩(전체 2D격자는 과비용): ①squeeze=1에서 shift 훑기 ②그 shift에서 squeeze 훑기.
    # squeeze도 shift와 똑같이 x0에 주저앉는 문제가 있어 반드시 시딩해야 한다
    # (앱 실측: 핫 squeeze가 0.995~1.005로 실제 움직임 — Fix 추천은 시딩 누락의 오진이었음).
    best_rms, best_sh = np.inf, 0.0
    for sh in np.arange(lo, hi + 1e-9, seed_step):
        r = _rms(sh, 1.0)
        if r < best_rms:
            best_rms, best_sh = r, float(sh)
    best_sq = 1.0
    for sq in np.arange(1.0 - sq_range, 1.0 + sq_range + 1e-12, sq_step):
        r = _rms(best_sh, sq)
        if r < best_rms:
            best_rms, best_sq = r, float(sq)
    return best_sh, best_sq


def fit_scan(eng, fitter, ref_props, wave, alpha, T_C, P_mbar,
             px_min, px_max, poly_deg, step_limit, target="NO2",
             seed_range=15.0, seed_step=0.25):
    """한 스캔 핏 → 지표 + **핏된 shift/squeeze 값**(ref별). bounds를 데이터에서 정하려면
    이 값들의 분포가 필요하다. fit_optimizer.fit_window의 확장(shift/squeeze 반환 추가)."""
    sl = slice(px_min, px_max + 1)
    wl = np.asarray(wave, float)[sl]
    a = np.asarray(alpha, float)[sl]
    wax = np.asarray(eng._wave_axis, float).flatten()
    vp = np.asarray(interp1d(wax, np.arange(len(wax)), bounds_error=False,
                             fill_value="extrapolate")(wl), float)
    center = vp[len(vp) // 2]

    ef = fitter.detect_etalon_frequency(vp, a, poly_deg, 0.02, 0.40)

    # ★초기 shift 시딩(필수): DOAS의 shift 지형은 레퍼런스가 진동해 **비볼록**이라
    # x0=0에서 least_squares만 돌리면 멀리 있는 진짜 최소(예: 핫 -4.95px)를 못 찾고
    # 0에 주저앉는다. 앱은 스캔간 last_valid_shift를 이어받아 step_limit씩 걸어가지만,
    # 표본 스캔은 시간연속이 아니므로 **스캔마다 넓은 격자탐색**으로 시드를 잡는다.
    # (DoasFitter.pre_calibrate는 ±0.5 국소 격자라 여기선 부족 → 전역 격자를 직접 돈다.)
    seed, seed_sq = _seed_shift(fitter, vp, a, poly_deg, ref_props, target, seed_range, seed_step)
    active, fixed, linked, t0, lb, ub = fitter.setup_fit_parameters(
        ref_props, seed, [seed, 1.0], step_limit)
    # setup_fit_parameters는 squeeze theta0를 항상 1.0으로 놓으므로 시드를 직접 주입한다.
    sq_key = f"{target}_sq"
    if sq_key in active:
        k = active.index(sq_key)
        t0[k] = float(min(max(seed_sq, lb[k] + 1e-9), ub[k] - 1e-9))
    out = fitter.execute_varpro_fit(vp, a, np.eye(len(a)), active, fixed, linked,
                                    t0, lb, ub, poly_deg, ef, center, 1.0,
                                    ref_props, T_C, 0.0, False)
    opt_sh, opt_sq, gco, poly_c, eamp, ep, perr = out

    full, tot, base, etal, _ = eng.get_model_components(
        vp, opt_sh, opt_sq, gco, poly_c, etalon_amp=eamp, etalon_freq=ef,
        etalon_phase=ep)
    resid = a - full
    rms = float(np.sqrt(np.mean(resid ** 2)))
    sig = float(np.sqrt(np.mean(tot ** 2)))
    rr = resid - resid.mean()
    autocorr1 = float(np.dot(rr[:-1], rr[1:]) / (np.dot(rr, rr) + 1e-30))

    n_air = air_number_density(T_C, P_mbar)
    conc = perr_rel = float("nan")
    if target in eng.gas_list:
        gi = eng.gas_list.index(target)
        sc = eng.scaling_factors.get(target, 1.0)
        mu = eng.multipliers.get(target, 1.0)
        conc = float((gco[gi] * mu / sc) / n_air * 1e9)
        conc *= 1.0   # perr_rel은 단위 무관(계수/계수)
        perr_rel = float(perr[gi] / abs(gco[gi])) if abs(gco[gi]) > 0 else float("inf")

    shifts = {g: float(s) for g, s in zip(eng.gas_list, opt_sh)}
    squeezes = {g: float(s) for g, s in zip(eng.gas_list, opt_sq)}
    coeffs = {g: float(c) for g, c in zip(eng.gas_list, gco)}   # ref별 핏 계수(정규화공간)
    return dict(conc=conc, perr_rel=perr_rel, rms=rms, sig=sig,
                rms_sig=float(rms / (sig + 1e-30)), autocorr1=autocorr1,
                shifts=shifts, squeezes=squeezes, coeffs=coeffs, n_free=len(active))


def _med_mad(xs):
    xs = np.array([x for x in xs if np.isfinite(x)], float)
    if len(xs) == 0:
        return float("nan"), float("nan")
    med = float(np.median(xs))
    mad = float(np.median(np.abs(xs - med))) * 1.4826  # →σ 환산
    return med, mad


def evaluate(scans, eng, fitter, ref_props, px_min, px_max, poly_deg,
             step_limit, target="NO2"):
    """스캔 샘플을 한 파라미터 세트로 핏 → 집계 지표(median 중심) + ref별 shift/squeeze 분포."""
    per, fails = [], 0
    for (wave, alpha, T_C, P_mbar) in scans:
        try:
            per.append(fit_scan(eng, fitter, ref_props, wave, alpha, T_C, P_mbar,
                                px_min, px_max, poly_deg, step_limit, target))
        except Exception:                 # noqa: BLE001
            fails += 1
    if not per:
        return dict(n_ok=0, n_fail=fails)

    concs = [p["conc"] for p in per]
    conc_med, _ = _med_mad(concs)
    finite_c = [c for c in concs if np.isfinite(c)]
    row = dict(
        n_ok=len(per), n_fail=fails, poly=poly_deg,
        conc=conc_med,
        conc_cv=float(np.std(finite_c) / (abs(conc_med) + 1e-30)) if len(finite_c) > 1 else 0.0,
        perr_rel=_med_mad([p["perr_rel"] for p in per])[0],
        autocorr1=_med_mad([p["autocorr1"] for p in per])[0],
        rms_sig=_med_mad([p["rms_sig"] for p in per])[0],
        n_free=per[0]["n_free"],
    )
    # ref별 shift/squeeze 분포(median, σ)
    shift_dist, sq_dist = {}, {}
    for g in eng.gas_list:
        shift_dist[g] = _med_mad([p["shifts"].get(g, np.nan) for p in per])
        sq_dist[g] = _med_mad([p["squeezes"].get(g, np.nan) for p in per])
    row["shift_dist"] = shift_dist    # {ref: (median, sigma)}
    row["sq_dist"] = sq_dist
    return row


# ──────────────────────────────────────────────────────────────────────────
def optimize_poly(scans, eng, fitter, ref_props, px_min, px_max, polys,
                  step_limit, target="NO2", plateau=0.05, conc_tol=0.03):
    """poly 차수 사다리 → 최소 무릎점 추천(RMS 최소 아님).

    기준: rms/sig가 더 낮은 차수 대비 `plateau`(5%) 미만으로만 개선되고, 농도가 다음 차수와
    `conc_tol`(3%) 안에서 안정되면 그 최소 차수 채택(광대역만 걷고 NO2 구조는 안 먹는 지점).
    자유도(=차수)를 더 올릴 입증책임은 올리는 쪽 — 헌장③."""
    ladder = [evaluate(scans, eng, fitter, ref_props, px_min, px_max, p, step_limit, target)
              for p in polys]
    ladder = [r for r in ladder if r.get("n_ok")]
    if not ladder:
        return None, []

    rec = ladder[-1]["poly"]
    for i, r in enumerate(ladder):
        rs = r["rms_sig"]
        rs_next = ladder[i + 1]["rms_sig"] if i + 1 < len(ladder) else rs
        conc_next = ladder[i + 1]["conc"] if i + 1 < len(ladder) else r["conc"]
        improve = (rs - rs_next) / (abs(rs) + 1e-30)          # 다음 차수로 갈 때 개선폭
        conc_move = abs(conc_next - r["conc"]) / (abs(r["conc"]) + 1e-30)
        if improve < plateau and conc_move < conc_tol:
            rec = r["poly"]
            break
    return rec, ladder


# ──────────────────────────────────────────────────────────────────────────
def _round_bound(x, up):
    """shift bound을 사람이 읽기 좋은 값으로 여유 반올림."""
    if not np.isfinite(x):
        return 0.0
    step = 0.5 if abs(x) < 3 else 1.0
    return float(np.ceil(x / step) * step) if up else float(np.floor(x / step) * step)


def recommend_shift(scans, eng, fitter, ref_props, px_min, px_max, poly_deg,
                    target="NO2", wide=15.0, margin_sigma=4.0):
    """TARGET shift 크기 자동 결정: **넓게 풀어 실제 핏된 shift 분포를 측정** → bounds가
    데이터에서 나온다(blind 그리드 아님). 분포가 안정하면 [median±kσ] Limit, 심하게
    흔들리면 shift가 안 정해지는 것 → Fix(median) 권고."""
    rp_wide = {g: dict(p) for g, p in ref_props.items()}
    rp_wide[target] = dict(rp_wide.get(target, {}),
                           sh_mode="Limit", sh_val=f"-{wide}, {wide}")
    row = evaluate(scans, eng, fitter, rp_wide, px_min, px_max, poly_deg,
                   step_limit=wide, target=target)
    med, sig = row["shift_dist"].get(target, (float("nan"), float("nan")))
    at_edge = np.isfinite(med) and (wide - abs(med)) < 2 * (sig + 0.1)
    # 흔들림 지표: σ가 크면(>2px) shift가 스캔마다 튐 → 잘 안 정해짐
    jittery = np.isfinite(sig) and sig > 2.0
    if not np.isfinite(med):
        return dict(policy="Link", reason="측정불가", median=med, sigma=sig)
    # ★미결정 감지: bounds를 활짝 열었는데도 핏이 x0(0.0)에서 한 발도 안 움직임 →
    # 데이터가 shift를 제약하지 못한다는 뜻(타깃 신호가 약하면 발생). 이때 좁은 Limit을
    # 추천하면 "측정된 값"인 척하는 거짓말이 된다 → 자유도를 빼고 Fix + 사유를 보고.
    if abs(med) < 1e-9 and (not np.isfinite(sig) or sig < 1e-9):
        return dict(policy="Fix", value=0.0, median=med, sigma=sig, undetermined=True,
                    reason=("데이터가 shift를 결정 못 함(bounds ±%g로 열었는데 핏이 0에서 불변) "
                            "→ 자유도 주지 말고 **Fix**. 타깃 신호가 약할 때 나타남." % wide))
    if jittery:
        return dict(policy="Fix", value=round(med, 2), median=med, sigma=sig,
                    reason=f"shift 흔들림 σ={sig:.2f}px→고정 권고")
    lb = _round_bound(med - margin_sigma * sig, up=False)
    ub = _round_bound(med + margin_sigma * sig, up=True)
    return dict(policy="Limit", lb=lb, ub=ub, median=med, sigma=sig,
                at_wide_edge=bool(at_edge),
                reason=(f"핏 shift {med:.2f}±{sig:.2f}px → Limit [{lb}, {ub}]"
                        + ("  ⚠넓힌 경계에도 닿음(더 넓혀야 할 수도)" if at_edge else "")))


def recommend_squeeze(scans, eng, fitter, ref_props, px_min, px_max, poly_deg,
                      target="NO2", wide=0.05, margin_sigma=4.0, step_limit=1.0):
    """TARGET squeeze 크기 자동 결정 — shift와 동일 철학(넓게 풀어 실제 분포로 bounds).

    squeeze는 1.0 근방의 배율. 분포가 1.0에 붙어 폭이 무의미하게 좁으면 **Fix 1.0 권고**
    (자유도를 더할 근거 없음 — 헌장③). sq_val은 setup_fit_parameters 규약대로 1.0 기준 편차."""
    rp = {g: dict(p) for g, p in ref_props.items()}
    rp[target] = dict(rp.get(target, {}), sq_mode="Limit", sq_val=f"-{wide}, {wide}")
    row = evaluate(scans, eng, fitter, rp, px_min, px_max, poly_deg, step_limit, target)
    med, sig = row["sq_dist"].get(target, (float("nan"), float("nan")))
    if not np.isfinite(med):
        return dict(policy="Fix", value=1.0, reason="측정불가 → Fix 1.0")
    dev = med - 1.0
    # 편차도 산포도 무시할 만하면 자유도를 줄 이유가 없다
    if abs(dev) < 1e-4 and (not np.isfinite(sig) or sig < 1e-4):
        return dict(policy="Fix", value=1.0, median=med, sigma=sig,
                    reason=f"핏 squeeze {med:.5f}±{sig:.5f} → 1.0에서 사실상 안 움직임 → Fix 1.0(절약)")
    lo = dev - margin_sigma * sig
    hi = dev + margin_sigma * sig
    return dict(policy="Limit", lo=round(lo, 4), hi=round(hi, 4), median=med, sigma=sig,
                reason=f"핏 squeeze {med:.5f}±{sig:.5f} → Limit [{lo:+.4f}, {hi:+.4f}] (1.0 기준 편차)")


def recommend_step_limit(consecutive_scans, eng, fitter, ref_props, px_min, px_max,
                         poly_deg, target="NO2", wide=15.0, quantile=0.95, floor=0.05):
    """`step_limit`(스캔당 최대 shift 변화) 자동 결정.

    ⚠️ sh_val(절대범위)과 다른 물건 — **연속 스캔 간 Δshift**에서 나와야 하므로
    시간상 인접한 스캔 블록을 넘겨야 한다(날짜별로 흩뿌린 표본이면 과대추정된다).
    실제 |Δshift|의 `quantile`을 여유 있게 올림 → 정상 변화는 통과, 튐은 막는다."""
    rp = {g: dict(p) for g, p in ref_props.items()}
    rp[target] = dict(rp.get(target, {}), sh_mode="Limit", sh_val=f"-{wide}, {wide}")
    shifts = []
    for (wave, alpha, T_C, P_mbar) in consecutive_scans:
        try:
            r = fit_scan(eng, fitter, rp, wave, alpha, T_C, P_mbar,
                         px_min, px_max, poly_deg, wide, target)
            shifts.append(r["shifts"].get(target, np.nan))
        except Exception:                 # noqa: BLE001
            shifts.append(np.nan)
    s = np.asarray(shifts, float)
    d = np.abs(np.diff(s))
    d = d[np.isfinite(d)]
    if len(d) < 3:
        return dict(value=None, reason="연속 스캔 부족 → 추천 불가")
    if float(np.max(d)) < 1e-9:
        # shift 자체가 미결정(핏이 안 움직임)이면 '스캔당 변화량'은 정의되지 않는다.
        return dict(value=None, undetermined=True,
                    reason="shift가 미결정(Δ가 전부 0) → step_limit은 의미 없음. shift Fix 권고와 함께 판단할 것")
    q = float(np.quantile(d, quantile))
    rec = max(floor, float(np.ceil(q * 1.5 * 20) / 20))   # 1.5배 여유, 0.05 단위 올림
    return dict(value=rec, q=q, median_step=float(np.median(d)), n=len(d),
                reason=(f"연속 |Δshift| median {np.median(d):.3f}px, {int(quantile*100)}% {q:.3f}px "
                        f"→ step_limit {rec:.2f}"))


def recommend_secondary_link(scans, eng, fitter, ref_props, px_min, px_max, poly_deg,
                             secondary, target="NO2", step_limit=1.0,
                             wide=15.0, improve_min=0.05):
    """2차 레퍼런스를 target에 **Link vs 독립** 판정. 기본=Link(절약). 독립이 잔차를
    의미있게(≥improve_min) 개선하고 AND 그 shift가 물리적으로 안정할 때만 독립 권고."""
    # (a) Link 기준선
    rp_link = {g: dict(p) for g, p in ref_props.items()}
    rp_link[secondary] = dict(rp_link.get(secondary, {}),
                              sh_mode="Link", sh_val=target,
                              sq_mode="Link", sq_val=target)
    base = evaluate(scans, eng, fitter, rp_link, px_min, px_max, poly_deg,
                    step_limit, target)
    # (b) 독립(넓게)
    rp_free = {g: dict(p) for g, p in ref_props.items()}
    rp_free[secondary] = dict(rp_free.get(secondary, {}),
                              sh_mode="Limit", sh_val=f"-{wide}, {wide}")
    free = evaluate(scans, eng, fitter, rp_free, px_min, px_max, poly_deg,
                    step_limit=wide, target=target)
    if not base.get("n_ok") or not free.get("n_ok"):
        return dict(secondary=secondary, decision="Link", reason="평가불가")

    improve = (base["rms_sig"] - free["rms_sig"]) / (abs(base["rms_sig"]) + 1e-30)
    med, sig = free["shift_dist"].get(secondary, (float("nan"), float("nan")))
    stable = np.isfinite(sig) and sig < 2.0
    conc_move = abs(free["conc"] - base["conc"]) / (abs(base["conc"]) + 1e-30)

    if improve >= improve_min and stable:
        lb = _round_bound(med - 4 * sig, up=False)
        ub = _round_bound(med + 4 * sig, up=True)
        return dict(secondary=secondary, decision="Independent",
                    lb=lb, ub=ub, improve=improve, shift=(med, sig), conc_move=conc_move,
                    reason=(f"독립시 잔차 {improve*100:.0f}%↓ & shift {med:.2f}±{sig:.2f}px 안정"
                            f" → 독립 [{lb}, {ub}] (Δ농도 {conc_move*100:.1f}%)"))
    return dict(secondary=secondary, decision="Link", improve=improve,
                shift=(med, sig), conc_move=conc_move,
                reason=(f"독립 이득 {improve*100:.0f}%(<{improve_min*100:.0f}%)"
                        + ("" if stable else f"·shift 불안정 σ={sig:.2f}") + " → Link 유지"))
