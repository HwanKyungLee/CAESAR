"""core/window_designer.py — 핏창 사전설계(a-priori). 핏 결과 없이 최적 창을 고른다.
=====================================================================================

**완전 처음 피팅하는 상황**(기존 핏 결과 0개)을 전제로 한다. 필요한 입력은
레퍼런스 단면 + 웨이브칼 + 알파 표본뿐. **핏을 한 번도 하지 않는다.**

원리 — 사전 오차전파(c-optimality)
-----------------------------------
선형 최소제곱의 검색 공분산은 데이터가 아니라 **설계행렬과 노이즈**만으로 정해진다:

    Cov = (Aᵀ Σ⁻¹ A)⁻¹ ,   A = [차등단면들 | Chebyshev(p) | etalon sin·cos]
    σ_target = √Cov[t,t]  →  ppb 환산 = **그 창의 검출한계**

이 한 식이 따로 세던 기준을 전부 품는다:
  * 타깃 차등구조 세기        → 열 노름↑ → Cov↓
  * 간섭종과의 공선성(퇴화)   → AᵀA 특이화 → Cov↑ (자동 페널티)
  * poly가 신호를 먹는 정도   → poly가 **설계행렬 안에** 있어 경쟁이 그대로 반영
  * 빛 약한 구간(저SNR)       → Σ의 픽셀별 노이즈
  * "넓으면 무조건 좋다" 편향 → **신호 없는 픽셀을 더해도 Cov가 안 줄어든다**

★마지막 항목이 중요하다. 예전 시도에서 `perr ∝ 1/폭` 스프롤 편향이 났던 건 *핏된* 잔차를
독립가정으로 썼기 때문(실제 잔차는 |ac1|~1로 강한 자기상관). 여기서는 Σ에 **AR(1) 자기상관**을
넣어 유효 자유도를 깎으므로 그 편향이 원천적으로 없다.

편향/분산 분리
--------------
분산만 보면 poly=0이 항상 최고(경쟁 열이 없으니까). 그래서 **poly 하한은 편향이 정한다**:
알파의 실제 광대역을 평평하게 만드는 최소 차수를 `min_poly_for_broadband`로 구해 하한으로 쓰고,
그 이상에서 σ_target을 최소화한다.
"""
from __future__ import annotations

import sys
import numpy as np
from numpy.polynomial import chebyshev
from scipy.ndimage import uniform_filter1d


# ppb 환산(n_air)은 core/physics.py가 단일 출처 — 여기서 재정의하지 않는다.
from core.physics import air_number_density   # ppb 환산 단일 출처(이 모듈이 직접 호출)


# ──────────────────────────────────────────────────────────────────────────
def residual_rho(eng, alphas, species, px_min, px_max, poly_deg, etalon_freq=0.30):
    """**설계행렬이 설명하지 못한 잔차**의 lag-1 자기상관 ρ.

    ⚠️고역통과한 알파의 상관을 쓰면 정의상 백색(ρ≈0)이라 유효자유도 보정이 무력화되고
    '넓을수록 좋다' 편향이 되살아난다. 그래서 선형 사영(비선형 최적화 없음 — 여전히
    사전계산)으로 얻은 잔차에서 ρ를 재야 한다.

    ⚠️ **실측(2026-09-16)** — 예전 주석은 "실제 핏 잔차는 강하게 상관(|ac1|~1)"이라고
    적고 있었으나 **그 근거가 없고 측정과 다르다.** 두 갈래로 독립 확인했다:

      · 이 함수 자체 (여수 알파 8스캔 × 창·poly 183조합, 채널별)
          cold  ρ median 0.075 (max 0.456)
          ANs   ρ median 0.441 (max 0.640)
          PNs   ρ median 0.392 (max 0.652)
      · 저장된 optimizer 로그 764건의 **실제 핏 잔차** ac1
          median 0.093 · max 0.814 · |ac1|>0.9 인 것 **0 %**

    즉 보정은 여전히 의미 있지만(핫 ρ≈0.44 → n_eff ≈ 0.39n) "|ac1|~1" 은 과장이다.
    이 숫자를 전제로 뭔가를 재설계하지 말 것."""
    sh = estimate_shift(eng, alphas, species, px_min, px_max, poly_deg, etalon_freq)
    A, _ = design_matrix(eng, species, px_min, px_max, poly_deg, etalon_freq, shift=sh)
    sl = slice(px_min, px_max + 1)
    rs = []
    n_fail = 0
    for a in np.asarray(alphas, float):
        y = a[sl]
        try:
            c, *_ = np.linalg.lstsq(A, y, rcond=None)
        except Exception:
            n_fail += 1
            continue
        r = y - A @ c
        rc = r - r.mean()
        rs.append(float(np.dot(rc[:-1], rc[1:]) / (np.dot(rc, rc) + 1e-30)))
    if not rs:
        # 예전엔 0.0을 돌려줬다. 0.0은 이 함수의 docstring이 바로 위에서 경고하는
        # 값이다 — "ρ≈0이면 유효자유도 보정이 무력화되고 '넓을수록 좋다' 편향이
        # 되살아난다". 즉 측정 실패의 기본값이 하필 **가장 관대한 값**이었다.
        # 하류에서 n_eff = n_pix*(1-ρ)/(1+ρ) = n_pix 가 되어 F검정 자유도가
        # 부풀고, 후보 종이 우연한 개선만으로 채택된다.
        # 옆의 model_adequacy()는 같은 상황에서 inf(=모델 불충분)를 돌려준다.
        # 보수적으로 실패하는 게 이 모듈의 규칙이므로 여기서는 멈춘다.
        raise RuntimeError(
            f"residual_rho: {n_fail}개 스캔 전부 lstsq 실패 — 자기상관을 잴 수 없다. "
            f"설계행렬/알파가 성립하는지 확인할 것(0.0으로 계속하면 유효자유도 "
            f"보정이 조용히 꺼진다)")
    if n_fail:
        print(f"[window_designer] residual_rho: {n_fail}/{n_fail + len(rs)} 스캔 "
              f"lstsq 실패 — 남은 {len(rs)}개로 ρ 추정", file=sys.stderr)
    return float(np.clip(np.median(rs), 0.0, 0.98))


def estimate_noise(alphas, smooth_px=15, local_px=25):
    """알파 표본 → 픽셀별 노이즈 σ(λ)와 잔차 lag-1 자기상관 ρ.

    고역통과(알파 − 이동평균)로 흡수·광대역을 걷어내고 남는 고주파를 노이즈로 본다.
    빛이 약한 구간은 여기서 자동으로 σ가 커진다(= 빛세기 정보가 데이터에서 나온다).
    ρ는 유효 자유도 보정에 쓴다(자기상관을 무시하면 넓은 창을 과대평가하게 된다)."""
    A = np.asarray(alphas, float)
    if A.ndim == 1:
        A = A[None, :]
    hp = A - uniform_filter1d(A, smooth_px, axis=1)
    # 픽셀별 노이즈: 각 스캔의 국소 표준편차 → 스캔 중앙값(이상 스캔에 강건)
    sig = np.median(np.array([np.sqrt(uniform_filter1d(h ** 2, local_px)) for h in hp]), axis=0)
    sig = np.maximum(sig, np.median(sig) * 1e-3)      # 0 방지
    # lag-1 자기상관(전 스캔 평균)
    rs = []
    for h in hp:
        hc = h - h.mean()
        d = float(np.dot(hc[:-1], hc[1:]) / (np.dot(hc, hc) + 1e-30))
        rs.append(d)
    rho = float(np.clip(np.median(rs), 0.0, 0.95))
    return sig, rho


def min_poly_for_broadband(alphas, px_min, px_max, max_deg=8, noise=None, k=1.0):
    """알파의 실제 광대역을 평평하게 만드는 **최소 Chebyshev 차수**(편향 하한).

    편향을 노이즈에 묶는다: **설명 못한 광대역 성분이 노이즈 수준 아래로 떨어지는 최소 차수**.
    (상대개선 문턱은 헐거워서 poly0을 뱉었다 — 물리적 기준인 노이즈로 바꿈.)
    이 값 미만의 poly는 광대역을 못 걷어 편향을 남기므로 창 탐색의 하한으로 쓴다."""
    A = np.asarray(alphas, float)
    if A.ndim == 1:
        A = A[None, :]
    sl = slice(px_min, px_max + 1)
    n = sl.stop - sl.start
    x = np.linspace(-1, 1, n)
    # 흡수선(고주파)을 뺀 '평활 성분'만 대상으로 판단
    smooth = uniform_filter1d(A[:, sl], 25, axis=1)
    thr = k * float(np.median(noise[sl])) if noise is not None else 0.0
    for deg in range(0, max_deg + 1):
        T = chebyshev.chebvander(x, deg)
        res = []
        for row in smooth:
            c, *_ = np.linalg.lstsq(T, row, rcond=None)
            res.append(float(np.sqrt(np.mean((row - T @ c) ** 2))))
        if float(np.median(res)) <= thr:
            return deg
    return max_deg


# ──────────────────────────────────────────────────────────────────────────
def _ar1_whiten(M, rho):
    """AR(1) 상관구조 Σ=σ²R 하에서 Σ⁻¹ 가중을 주기 위한 화이트닝 변환.
    R의 Cholesky 역변환은 해석적이다: 첫 행 √(1-ρ²), 이후 x_i - ρ·x_{i-1}.
    화이트닝 후에는 보통 최소제곱을 쓰면 (Aᵀ R⁻¹ A)와 동치가 된다."""
    if rho <= 0:
        return M
    W = M.copy()
    W[1:] = M[1:] - rho * M[:-1]
    W[0] = M[0] * np.sqrt(max(1.0 - rho ** 2, 1e-12))
    return W / np.sqrt(max(1.0 - rho ** 2, 1e-12))


def design_matrix(eng, species, px_min, px_max, poly_deg, etalon_freq=0.0,
                  shift=0.0, squeeze=1.0):
    """설계행렬 A = [차등단면들 | Chebyshev(poly) | etalon sin·cos].
    가스 열은 실제 핏과 동일하게 **정규화 단면**(ref/scale)을 쓴다 → 계수공간이 핏과 일치."""
    sl = slice(px_min, px_max + 1)
    n = sl.stop - sl.start
    px = np.arange(px_min, px_max + 1, dtype=float)
    center = px[n // 2]
    cols, names = [], []
    for name in species:
        if name not in eng.raw_references:
            continue
        ref = np.asarray(eng.raw_references[name], float)
        if shift or squeeze != 1.0:
            pxs = (px - center) * squeeze + center + shift
            v = eng.interpolators[name](pxs)
        else:
            v = ref[sl]
        cols.append(np.asarray(v, float) / (eng.scaling_factors.get(name, 1.0) or 1.0))
        names.append(name)
    x = np.linspace(-1, 1, n)
    T = chebyshev.chebvander(x, poly_deg)
    for j in range(T.shape[1]):
        cols.append(T[:, j]); names.append(f"poly{j}")
    if etalon_freq:
        cols.append(np.sin(etalon_freq * px)); names.append("etalon_sin")
        cols.append(np.cos(etalon_freq * px)); names.append("etalon_cos")
    return np.column_stack(cols), names


def estimate_shift(eng, alphas, species, px_min, px_max, poly_deg,
                   etalon_freq=0.30, lo=-12.0, hi=12.0, step=0.25):
    """창의 **레퍼런스 정렬(shift)**을 사전 추정 — 격자 + 선형사영만(비선형 최적화 없음).

    ⚠️필수. 설계행렬을 shift=0으로 세우면 실제 정렬이 어긋난 채널에서 잔차가 부풀어
    `chi`가 '미모델 구조'로 **오진**된다(실측: ANs 실제 shift −5.4px → chi 1.63 오진).
    창·poly 선택은 정렬이 맞은 상태에서 평가해야 의미가 있다."""
    ys = [np.asarray(a, float)[px_min:px_max + 1] for a in np.asarray(alphas, float)]
    best_r, best_sh = np.inf, 0.0
    for sh in np.arange(lo, hi + 1e-9, step):
        A, _ = design_matrix(eng, species, px_min, px_max, poly_deg, etalon_freq, shift=float(sh))
        rs = []
        for y in ys:
            try:
                c, *_ = np.linalg.lstsq(A, y, rcond=None)
            except Exception:             # noqa: BLE001
                continue
            rs.append(float(np.sqrt(np.mean((y - A @ c) ** 2))))
        if rs:
            m = float(np.median(rs))
            if m < best_r:
                best_r, best_sh = m, float(sh)
    return best_sh


def model_adequacy(A, y_list, noise_sl):
    """**모델이 데이터를 설명하는가** — 편향 위험 지표. 핏 없이 선형 사영만으로 계산.

    σ_target(c-optimality)은 **정밀도만** 재고 정확도는 못 본다. 창을 넓혀 ILS 불일치·
    웨이브칼 외삽·미모델 흡수체가 있는 구간까지 들어가면 분산은 줄지만 **편향이 커진다**.
    그래서 "잔차가 노이즈 수준인가"를 같이 봐야 최적화가 폭주하지 않는다.
    반환 chi = RMS(잔차)/median(노이즈). 1 근처면 모델 충분, 크면 미모델 구조 존재."""
    chis = []
    for y in y_list:
        try:
            c, *_ = np.linalg.lstsq(A, y, rcond=None)
        except Exception:                 # noqa: BLE001
            continue
        r = y - A @ c
        chis.append(float(np.sqrt(np.mean(r ** 2)) / (np.median(noise_sl) + 1e-300)))
    return float(np.median(chis)) if chis else float("inf")


def predicted_sigma(A, names, noise_sl, rho, target):
    """사전 검색 오차 σ_target(계수공간) + 진단(조건수, 타깃의 다중상관 R).

    Σ⁻¹ 가중 = (1) 픽셀별 노이즈로 행 스케일 (2) AR(1) 화이트닝(자기상관 보정)."""
    if target not in names:
        return dict(sigma=float("inf"), cond=float("inf"), multiple_R=float("nan"))
    Aw = A / noise_sl[:, None]
    Aw = _ar1_whiten(Aw, rho)
    try:
        AtA = Aw.T @ Aw
        C = np.linalg.pinv(AtA)
        ti = names.index(target)
        sig = float(np.sqrt(max(C[ti, ti], 0.0)))
        cond = float(np.linalg.cond(AtA))
    except Exception:                     # noqa: BLE001
        return dict(sigma=float("inf"), cond=float("inf"), multiple_R=float("nan"))
    # 타깃이 **다른 가스들**로 재현되나(=퇴화). ⚠️poly·etalon 열을 넣고 재면 NO2 단면의
    # 매끄러운 성분이 poly로 재현돼 항상 ~0.99가 나온다 → poly/etalon은 **사영 제거**하고
    # 가스 열끼리만 비교해야 의미가 있다(fit_physics.differential_collinearity와 동일 철학).
    gas_idx = [i for i, n in enumerate(names)
               if not (n.startswith("poly") or n.startswith("etalon"))]
    bg_idx = [i for i, n in enumerate(names)
              if n.startswith("poly") or n.startswith("etalon")]
    try:
        B = Aw[:, bg_idx] if bg_idx else None
        def _depoly(v):
            if B is None or B.shape[1] == 0:
                return v
            c, *_ = np.linalg.lstsq(B, v, rcond=None)
            return v - B @ c
        t = _depoly(Aw[:, ti])
        oth = [_depoly(Aw[:, i]) for i in gas_idx if i != ti]
        if not oth or np.linalg.norm(t) == 0:
            mR = float("nan")
        else:
            O = np.column_stack(oth)
            beta, *_ = np.linalg.lstsq(O, t, rcond=None)
            r = t - O @ beta
            r2 = 1.0 - float(r @ r) / (float(t @ t) + 1e-300)
            mR = float(np.sqrt(max(min(r2, 1.0), 0.0)))
    except Exception:                     # noqa: BLE001
        mR = float("nan")
    return dict(sigma=sig, cond=cond, multiple_R=mR)


# ──────────────────────────────────────────────────────────────────────────
def scan_windows(eng, alphas, species, wave, T_C, P_mbar,
                 starts_nm, ends_nm, polys=None, target="NO2",
                 min_width_nm=10.0, etalon_freq=0.30, robust_shift_px=1.0,
                 degeneracy_max=0.98, chi_max=1.30):
    """창×poly 사전설계 스캔 → 검출한계(ppb) 랭킹. **핏 전혀 안 함.**

    반환 rows: dict(lo_nm, hi_nm, px_min, px_max, poly, mdl_ppb, cond, multiple_R,
                    robust_ratio, gated, gate_reason). mdl_ppb 낮을수록 좋음."""
    wave = np.asarray(wave, float)
    sig_px, _ = estimate_noise(alphas)
    n_air = air_number_density(T_C, P_mbar)
    # ρ는 대표 창(전 범위 중앙부)에서 잔차 기반으로 1회 추정 → 유효자유도 보정에 사용
    _p0, _p1 = int(len(wave) * 0.35), int(len(wave) * 0.75)
    # ★정렬 먼저: shift=0으로 평가하면 정렬이 어긋난 채널에서 chi가 오진된다.
    shift0 = estimate_shift(eng, alphas, species, _p0, _p1, 4, etalon_freq)
    rho = residual_rho(eng, alphas, species, _p0, _p1, 4, etalon_freq)
    sc = eng.scaling_factors.get(target, 1.0) or 1.0
    mu = eng.multipliers.get(target, 1.0)

    def nm2px(v):
        return int(np.argmin(np.abs(wave - v)))

    rows = []
    for lo in starts_nm:
        for hi in ends_nm:
            if hi - lo < min_width_nm:
                continue
            pmn, pmx = nm2px(lo), nm2px(hi)
            if pmx - pmn < 30:
                continue
            # poly 하한 = 광대역을 걷는 최소 차수(편향), 그 이상만 후보
            # poly 후보는 고정 범위. (예전엔 min_poly_for_broadband로 하한을 뒀는데 문턱이
            # 과해 poly4~8만 후보가 되었다 — 같은 창에서 실제론 poly2~3이 더 좋았다.
            # 편향은 chi가 직접 재므로 하한 휴리스틱 없이 chi+절약선택에 맡긴다.)
            pmin_deg = min_poly_for_broadband(alphas, pmn, pmx, noise=sig_px)
            cand = polys if polys is not None else range(2, 10)
            noise_sl = sig_px[pmn:pmx + 1]
            for p in cand:
                A, names = design_matrix(eng, species, pmn, pmx, p, etalon_freq, shift=shift0)
                d = predicted_sigma(A, names, noise_sl, rho, target)
                chi = model_adequacy(A, [np.asarray(a, float)[pmn:pmx + 1]
                                         for a in np.asarray(alphas, float)], noise_sl)
                # 계수공간 σ → 수밀도 → ppb (핏의 환산과 동일 규약)
                mdl = d["sigma"] * mu / sc / n_air * 1e9
                # 강건성: 레퍼런스를 ±1px 흔들었을 때 σ가 얼마나 나빠지나(웨이브칼 오차 내성)
                A2, n2 = design_matrix(eng, species, pmn, pmx, p, etalon_freq,
                                       shift=shift0 + robust_shift_px)
                d2 = predicted_sigma(A2, n2, noise_sl, rho, target)
                rr = (d2["sigma"] / d["sigma"]) if d["sigma"] > 0 else float("inf")
                gated = ((not np.isfinite(mdl)) or (d["multiple_R"] > degeneracy_max)
                         or (chi > chi_max))
                rows.append(dict(
                    lo_nm=float(wave[pmn]), hi_nm=float(wave[pmx]),
                    px_min=pmn, px_max=pmx, poly=int(p), poly_min=int(pmin_deg),
                    mdl_ppb=float(mdl), cond=d["cond"], multiple_R=d["multiple_R"], chi=float(chi),
                    robust_ratio=float(rr), width_nm=float(wave[pmx] - wave[pmn]),
                    gated=bool(gated),
                    gate_reason=("degenerate" if d["multiple_R"] > degeneracy_max else
                                 "unmodeled(편향위험)" if chi > chi_max else
                                 "bad" if not np.isfinite(mdl) else ""),
                ))
    rows.sort(key=lambda r: (r["gated"], r["mdl_ppb"] * max(r["robust_ratio"], 1.0)
                             * max(r["chi"], 1.0)))
    return rows, dict(rho=rho, noise_median=float(np.median(sig_px)), shift=shift0)


def compare_species(eng, alphas, base_species, candidate, wave, T_C, P_mbar,
                    px_min, px_max, poly_deg, target="NO2", etalon_freq=0.30):
    """후보 레퍼런스를 **넣었을 때 vs 뺐을 때** 타깃 검출한계 비교. 핏 없이 ref 취사선택 판단.
    (넣어서 σ_target이 나빠지면 그 종은 공선성으로 타깃을 갉아먹는다는 뜻.)"""
    sig_px, _ = estimate_noise(alphas)
    rho = residual_rho(eng, alphas, base_species, px_min, px_max, poly_deg, etalon_freq)
    noise_sl = sig_px[px_min:px_max + 1]
    n_air = air_number_density(T_C, P_mbar)
    sc = eng.scaling_factors.get(target, 1.0) or 1.0
    mu = eng.multipliers.get(target, 1.0)
    out = {}
    for tag, sp in (("without", [s for s in base_species if s != candidate]),
                    ("with", list(base_species) + ([candidate] if candidate not in base_species else []))):
        A, names = design_matrix(eng, sp, px_min, px_max, poly_deg, etalon_freq)
        d = predicted_sigma(A, names, noise_sl, rho, target)
        out[tag] = dict(mdl_ppb=d["sigma"] * mu / sc / n_air * 1e9,
                        multiple_R=d["multiple_R"], cond=d["cond"])
    w, wo = out["with"]["mdl_ppb"], out["without"]["mdl_ppb"]
    out["ratio"] = float(w / wo) if wo > 0 else float("inf")
    out["verdict"] = ("포함 이득" if out["ratio"] < 0.95 else
                      "무의미/해로움" if out["ratio"] > 1.05 else "중립")
    return out
