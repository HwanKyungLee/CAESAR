"""core/agreement.py — 두 방법(예: Augur vs QDOAS/DOASIS)이 **얼마나 일치하는가**.

왜 필요한가
-----------
지금 교차검증 보고는 `r²`와 OLS `slope`로 돼 있다. 그런데 **상관은 일치가 아니다.**
실제 QDOAS 대조표에 그 증거가 있다:

    Cold CHOCHO   r² = 0.861   slope = 0.685   → 한쪽이 31% 크다
    Cold H2O      r² = 0.977   slope = 1.237   → 한쪽이 24% 크다

r²는 "같이 오르내리는가"를 재고, 일치는 "같은 값인가"다. 방법비교에서 이 둘을 섞는 건
고전적 오류다(Bland & Altman 1986). 그래서 이 모듈은 셋을 같이 낸다:

1. **Bland–Altman** — 차이 대 평균. 평균 편향 · 일치한계(±1.96 SD) · **농도에 따라
   편향이 변하는지**(비례 편향). slope 하나에 뭉개져 있던 걸 분리한다.
2. **Deming(직교) 회귀** — OLS는 **x에도 오차가 있으면 기울기를 0쪽으로 끌어내린다**
   (감쇠 편향). 두 방법 다 불확도가 있으므로 OLS slope는 구조적으로 1에서 멀어진다.
   즉 *slope 0.685가 진짜 차이인지 감쇠인지 OLS로는 구분 못 한다.*
3. **유효 표본수 / 블록 부트스트랩** — 60초 빈 연속 시계열은 **독립이 아니다**.
   n=50,000이어도 유효 표본은 수백~수천이다. CI·p값을 쓸 거면 이걸 반영해야 한다.

절편도 항상 낸다 — slope만 보면 **비례 편향과 덧셈 편향이 구분되지 않는다**(미량
기체에서는 검출한계 근처 offset이 결정적).

자기검증: `python -m core.agreement`
"""
from __future__ import annotations

import numpy as np


def _clean(x, y):
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    if x.shape != y.shape:
        raise ValueError(f"길이가 다르다: {x.shape} vs {y.shape}")
    m = np.isfinite(x) & np.isfinite(y)
    return x[m], y[m]


def pearson_r2(x, y) -> float:
    x, y = _clean(x, y)
    if len(x) < 3:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1] ** 2)


def ols(x, y) -> tuple:
    """최소제곱 y = a·x + b. **x에 오차가 있으면 a는 0쪽으로 감쇠한다.**"""
    x, y = _clean(x, y)
    if len(x) < 3:
        return float("nan"), float("nan")
    a, b = np.polyfit(x, y, 1)
    return float(a), float(b)


def deming(x, y, lambda_ratio: float = 1.0) -> tuple:
    """Deming 회귀 y = a·x + b. `lambda_ratio` = var(err_y)/var(err_x).

    λ=1이면 직교(orthogonal) 회귀. **두 축 모두 오차가 있을 때 쓰는 추정량**이라
    OLS의 감쇠 편향이 없다. 두 방법의 반복측정 분산을 알면 그 비를 넣고, 모르면
    λ=1(대등 가정)로 두되 **그 가정을 보고서에 적을 것**.
    """
    x, y = _clean(x, y)
    n = len(x)
    if n < 3:
        return float("nan"), float("nan")
    mx, my = x.mean(), y.mean()
    dx, dy = x - mx, y - my
    sxx = float(dx @ dx) / (n - 1)
    syy = float(dy @ dy) / (n - 1)
    sxy = float(dx @ dy) / (n - 1)
    if sxy == 0:
        return float("nan"), float("nan")
    lam = float(lambda_ratio)
    t = syy - lam * sxx
    a = (t + np.sqrt(t * t + 4.0 * lam * sxy * sxy)) / (2.0 * sxy)
    return float(a), float(my - a * mx)


def bland_altman(x, y, *, relative: bool = False) -> dict:
    """차이 대 평균. x·y 순서는 (기준, 비교) 관례 — diff = y − x.

    relative=True면 차이를 평균으로 나눠 **비율**로 본다(농도 범위가 넓을 때 적절).
    `prop_bias_slope`는 "차이가 농도에 따라 커지는가"(비례 편향) — 0에서 유의하게
    벗어나면 단일 편향값으로 요약하면 안 된다는 신호다.
    """
    x, y = _clean(x, y)
    if len(x) < 3:
        return {"n": len(x)}
    mean = (x + y) / 2.0
    diff = y - x
    if relative:
        with np.errstate(divide="ignore", invalid="ignore"):
            diff = np.where(mean != 0, diff / mean, np.nan)
        m = np.isfinite(diff)
        mean, diff = mean[m], diff[m]
    bias = float(np.mean(diff))
    sd = float(np.std(diff, ddof=1))
    slope, _ = ols(mean, diff)
    out = {
        "n": int(len(diff)),
        "bias": bias,                       # 평균 편향(계통 차이)
        "sd": sd,
        "loa_lo": bias - 1.96 * sd,         # 일치 한계 95%
        "loa_hi": bias + 1.96 * sd,
        "prop_bias_slope": slope,           # 0이 아니면 농도 의존 편향
        "relative": bool(relative),
    }
    if relative:
        # ⚠ 상대 BA는 차이를 **두 값의 평균**으로 나눈다(x가 아니라).
        #   y = k·x 이면 bias = 2(k−1)/(k+1) 이다 — 예: k=1.30 → bias=0.261.
        #   26%로 읽고 "26% 차이"라고 말하면 틀린다. 직관적인 비율을 같이 낸다.
        out["ratio_equiv"] = ((2.0 + bias) / (2.0 - bias)) if abs(bias) < 2 else float("nan")
    return out


def bias_vs_scale(x, y, ref=None) -> dict:
    """편향을 **안정적인 스케일**(기본: |기준값|의 중앙값)로 나눈 상대 크기.

    왜 상대 BA를 그냥 쓰면 안 되나: 이 저장소는 음수 허용이 기본이라 0 근처·음수 농도가
    정상적으로 나온다. 차이를 '두 값의 평균'으로 나누면 그 평균이 0을 스쳐 **폭발**한다
    (실측: Cold NO2에서 상대편향 +112%, 일치한계 ±3.6e4% — 전부 0 나눗셈 아티팩트이고
    실제 Deming slope는 1.088이다). 그래서 분모를 **행마다**가 아니라 **한 번** 정한다.
    """
    x, y = _clean(x, y)
    if len(x) < 3:
        return {"n": len(x)}
    scale = float(ref) if ref else float(np.median(np.abs(x)))
    d = y - x
    bias, sd = float(np.mean(d)), float(np.std(d, ddof=1))
    if not scale or not np.isfinite(scale):
        return {"n": len(x), "scale": scale}
    return {"n": int(len(x)), "scale": scale,
            "bias_rel": bias / scale, "sd_rel": sd / scale,
            "loa_lo_rel": (bias - 1.96 * sd) / scale,
            "loa_hi_rel": (bias + 1.96 * sd) / scale}


def effective_n(v) -> float:
    """자기상관을 반영한 유효 표본수: n·(1−r₁)/(1+r₁).

    연속 시계열에서 n을 그대로 쓰면 CI가 **터무니없이 좁아진다**. 1차 근사지만
    "n=50,000이 사실은 수백"이라는 자릿수를 드러내는 데는 충분하다.
    """
    v = np.asarray(v, dtype=float).ravel()
    v = v[np.isfinite(v)]
    n = len(v)
    if n < 3:
        return float(n)
    d = v - v.mean()
    denom = float(d @ d)
    if denom == 0:
        return float(n)
    r1 = float(d[:-1] @ d[1:]) / denom
    r1 = min(max(r1, -0.999), 0.999)
    return float(n * (1.0 - r1) / (1.0 + r1))


def block_bootstrap_slope_ci(x, y, *, block=None, n_boot=400, lam=1.0,
                             seed=0, alpha=0.05) -> tuple:
    """Deming slope의 신뢰구간 — **이동 블록 부트스트랩**(자기상관 보존).

    일반 부트스트랩은 표본을 독립으로 가정해 CI를 과도하게 좁힌다. 블록 단위로
    다시 뽑으면 시계열 구조가 살아남는다. block 기본값 = √n (경험칙).
    """
    x, y = _clean(x, y)
    n = len(x)
    if n < 20:
        return float("nan"), float("nan")
    b = int(block or max(2, round(np.sqrt(n))))
    n_blocks = int(np.ceil(n / b))
    rng = np.random.default_rng(seed)
    out = []
    starts_max = n - b
    for _ in range(int(n_boot)):
        st = rng.integers(0, starts_max + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + b) for s in st])[:n]
        a, _ = deming(x[idx], y[idx], lam)
        if np.isfinite(a):
            out.append(a)
    if not out:
        return float("nan"), float("nan")
    lo, hi = np.quantile(out, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


def compare(x, y, *, name="", lam=1.0, relative=False, boot=True) -> dict:
    """한 쌍에 대한 일치도 한 묶음. x=기준(예: Augur), y=비교(예: QDOAS)."""
    x, y = _clean(x, y)
    a_ols, b_ols = ols(x, y)
    a_dem, b_dem = deming(x, y, lam)
    res = {
        "name": name, "n": int(len(x)),
        "r2": pearson_r2(x, y),
        "ols_slope": a_ols, "ols_intercept": b_ols,
        "deming_slope": a_dem, "deming_intercept": b_dem,
        "lambda": float(lam),
        "n_eff": effective_n(x),
        "ba": bland_altman(x, y, relative=relative),
        # 0을 스치는 데이터에서도 읽을 수 있는 상대 편향(분모 = |기준값| 중앙값)
        "scaled": bias_vs_scale(x, y),
    }
    if boot:
        res["deming_ci"] = block_bootstrap_slope_ci(x, y, lam=lam)
    return res


def format_compare(r: dict, unit="ppb") -> str:
    ba = r.get("ba") or {}
    L = []
    L.append(f"[{r.get('name') or 'pair'}]  n={r['n']:,}  (유효 n≈{r['n_eff']:,.0f}"
             f" — 자기상관 반영)")
    L.append(f"  r²                 {r['r2']:.4f}      ← 연관성. **일치가 아니다**")
    L.append(f"  OLS     slope      {r['ols_slope']:.4f}   intercept {r['ols_intercept']:+.4g} {unit}"
             f"   (x 오차로 0쪽 감쇠)")
    ci = r.get("deming_ci")
    ci_s = (f"  [{ci[0]:.4f}, {ci[1]:.4f}] 95% 블록부트스트랩"
            if ci and np.isfinite(ci[0]) else "")
    L.append(f"  Deming  slope      {r['deming_slope']:.4f}   intercept "
             f"{r['deming_intercept']:+.4g} {unit}   (λ={r['lambda']:g}){ci_s}")
    if ba.get("n"):
        u = "" if ba.get("relative") else f" {unit}"
        sc = 100.0 if ba.get("relative") else 1.0
        tag = "%" if ba.get("relative") else u
        L.append(f"  Bland–Altman 편향  {ba['bias'] * sc:+.4g}{tag}"
                 f"   일치한계 [{ba['loa_lo'] * sc:+.4g}, {ba['loa_hi'] * sc:+.4g}]{tag}")
        if ba.get("ratio_equiv") is not None and np.isfinite(ba["ratio_equiv"]):
            L.append(f"     (= 비율 {ba['ratio_equiv']:.4f} 배. 상대 BA는 두 값의 평균으로"
                     f" 나누므로 편향%를 그대로 '몇 % 차이'로 읽지 말 것)")
        L.append(f"  비례 편향 기울기    {ba['prop_bias_slope']:+.4g}"
                 f"   ← 0에서 멀면 편향이 농도에 따라 변함(단일 값 요약 금지)")
    sc = r.get("scaled") or {}
    if sc.get("bias_rel") is not None:
        L.append(f"  편향/중앙값        {sc['bias_rel'] * 100:+.2f}%"
                 f"   일치한계 [{sc['loa_lo_rel'] * 100:+.1f}, {sc['loa_hi_rel'] * 100:+.1f}]%"
                 f"   (분모 = |기준값| 중앙값 {sc['scale']:.4g} — 0 나눗셈 회피)")
    return "\n".join(L)


def _demo():
    """자기검증 — 이 모듈의 **존재 이유**를 수치로 보인다."""
    rng = np.random.default_rng(0)
    n = 4000
    true = rng.lognormal(0.0, 0.6, n)          # 참값(양수, 넓은 동적범위)

    # ① 두 축 모두 오차 → OLS는 감쇠, Deming은 회복
    ex = rng.normal(0, 0.25, n)
    ey = rng.normal(0, 0.25, n)
    x, y = true + ex, true + ey                # 참 기울기 = 1.0
    a_ols, _ = ols(x, y)
    a_dem, _ = deming(x, y, 1.0)
    assert a_ols < 0.95, f"OLS 감쇠가 안 보인다: {a_ols}"
    assert abs(a_dem - 1.0) < 0.05, f"Deming이 참값을 못 찾음: {a_dem}"
    assert a_dem > a_ols

    # ② r²는 높은데 일치는 나쁜 경우 — 이 모듈의 핵심 주장
    y2 = 1.30 * true                            # 30% 비례 차이, 노이즈 없음
    assert pearson_r2(true, y2) > 0.999, "상관은 완벽한데"
    ba = bland_altman(true, y2, relative=True)
    # 상대 BA는 (두 값의 평균)으로 나누므로 비율 1.30 → 2(k−1)/(k+1) = 0.2609다.
    # 이 숫자를 "26% 차이"로 읽으면 틀리므로 ratio_equiv로 되돌릴 수 있어야 한다.
    assert abs(ba["bias"] - 2 * 0.30 / 2.30) < 1e-6, ba
    assert abs(ba["ratio_equiv"] - 1.30) < 1e-9, ba["ratio_equiv"]
    a_dem2, _ = deming(true, y2, 1.0)
    assert abs(a_dem2 - 1.30) < 0.01, a_dem2

    # ③ 절편(덧셈 편향)과 기울기(비례 편향)를 분리하는지
    y3 = true + 0.5
    a3, b3 = deming(true, y3, 1.0)
    assert abs(a3 - 1.0) < 1e-6 and abs(b3 - 0.5) < 1e-6, (a3, b3)

    # ③-b 0을 스치는 데이터: 상대 BA는 폭발하고, 스케일 기준은 멀쩡해야 한다
    z = rng.normal(0, 1.0, n)                   # 0을 자주 스침(음수 허용 상황)
    zy = z + 0.10                                # 알려진 덧셈 편향 0.10
    ba_bad = bland_altman(z, zy, relative=True)
    sc_ok = bias_vs_scale(z, zy)
    # 증상은 평균이 아니라 **산포**다: 일치한계가 ±2700%까지 벌어지고 부호까지 뒤집힌다
    # (실측 z~N(0,1), 참 편향 +0.10 → 상대BA bias=-0.30, sd=13.6).
    assert ba_bad["sd"] > 5.0, ba_bad
    assert ba_bad["bias"] * 0.10 < 0, ("상대BA 부호가 참값과 반대여야 한다(전제)", ba_bad)
    # 안정 스케일은 정확히 맞는다
    assert abs(sc_ok["bias_rel"] - 0.10 / float(np.median(np.abs(z)))) < 1e-12, sc_ok
    assert sc_ok["sd_rel"] < 1e-9, sc_ok      # 덧셈 편향만 있으므로 산포는 0

    # ④ 자기상관 → 유효 표본수가 크게 줄어드는지
    ar = np.empty(n)
    ar[0] = rng.normal()
    for i in range(1, n):
        ar[i] = 0.95 * ar[i - 1] + rng.normal(0, 0.3)
    assert effective_n(ar) < 0.1 * n, effective_n(ar)
    assert abs(effective_n(rng.normal(size=n)) - n) < 0.25 * n   # 백색잡음은 ≈n

    # ⑤ 블록 부트스트랩 CI가 참 기울기를 덮는지
    lo, hi = block_bootstrap_slope_ci(x, y, n_boot=200)
    assert lo < 1.0 < hi, (lo, hi)

    r = compare(x, y, name="demo(참 slope=1.0)", relative=False)
    print(format_compare(r))
    print()
    print("agreement self-check OK — OLS %.4f(감쇠) vs Deming %.4f(회복)"
          % (a_ols, a_dem))


if __name__ == "__main__":
    _demo()
