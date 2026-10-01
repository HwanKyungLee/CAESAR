"""core/error_budget.py — 농도 하나에 붙는 불확도를 **항목별로** 분해한다.

왜 필요한가
-----------
지금 결과 파일에는 `<gas>_Error`(핏 공분산)와 `<gas>_TotalError`(+T/P 전파)만 있다.
그런데 실제 불확도를 지배하는 것들 — 단면 문헌 불확도, σ(R)→경로길이, 캐비티 길이,
콜드 잔차 고정패턴 — 은 **한 번도 정량화된 적이 없다**. 정량화 안 된 항을 빼놓고
"오차 ±0.08 ppb"라고 적으면 그 숫자는 틀린 게 아니라 **불완전**하다.

그래서 이 모듈의 핵심 설계는 "계산되는 항만 보여주기"가 **아니라**:

    **모르는 항도 줄로 남기고 `UNQUANTIFIED`라고 적는다.**

빈칸이 보여야 뭘 모르는지 알고, 그게 채워지는 순서가 곧 우선순위다. 논문 Table의
"Uncertainty budget"이 그대로 이 표다(docs/Augur_소개_2026-07.md §10-2).

무작위 vs 계통
--------------
둘은 **다르게 합쳐진다**. 무작위는 제곱합(√Σσ²)으로 줄어들고 평균하면 작아지지만,
계통은 선형합으로 남고 아무리 평균해도 안 사라진다. 그래서 총합을 하나로 안 뭉갠다
(이 저장소가 King factor 오타·O₂ 상수 오타에서 배운 것 — §4.2).

자기검증: `python -m core.error_budget`
"""
from __future__ import annotations

from dataclasses import dataclass, field

try:                                   # 패키지 임포트(평소)
    from core.physics import air_number_density
except ImportError:                    # `python core/error_budget.py` 직접 실행
    from physics import air_number_density

RANDOM = "random"
SYSTEMATIC = "systematic"
UNQUANTIFIED = None          # rel=None → "아직 모른다"


# ── 실제 공기의 비이상성 ──────────────────────────────────────────────────────
# 2차 비리얼: Z = 1 + B(T)·p/(R·T).  B(T)[cm³/mol]는 건공기 문헌값에 맞춘 선형 근사
# (앵커: Z(0 °C, 1 atm) = 0.99941 — 널리 인용되는 값).  이 근사 자체의 오차가 20%여도
# 농도 항으로는 0.006% 수준이라 무해하다.
_R_GAS = 8.314462618            # J/(mol·K)
_B_ANCHOR = ((273.15, -13.2e-6), (313.15, -5.6e-6))    # (T[K], B[m³/mol])


def _b_air(T_K: float) -> float:
    (t0, b0), (t1, b1) = _B_ANCHOR
    return b0 + (b1 - b0) * (T_K - t0) / (t1 - t0)


def compressibility(T_C: float, P_mbar: float) -> float:
    """건공기 압축인자 Z (<1). 실제 분자밀도 = 이상기체밀도 / Z."""
    T_K = T_C + 273.15
    return 1.0 + _b_air(T_K) * (P_mbar * 100.0) / (_R_GAS * T_K)


def ideal_gas_bias(T_C: float, P_mbar: float) -> float:
    """이상기체 가정이 농도에 주는 **상대 계통편향**(양수 = 농도가 그만큼 과대).

    ppb = N_gas / N_air 인데 N_air를 이상기체로 계산하면 실제보다 작다(Z<1) →
    분모가 작아 농도가 크게 나온다. 크기: 0 °C +0.06%, 25 °C +0.03%, 35 °C +0.02%.
    """
    return 1.0 / compressibility(T_C, P_mbar) - 1.0


# ── 예산 항목 ────────────────────────────────────────────────────────────────
@dataclass
class Term:
    """예산 한 줄. `rel=None`이면 **아직 정량화 안 됨**(빈칸을 숨기지 않는다)."""
    name: str
    kind: str                   # RANDOM | SYSTEMATIC
    rel: float | None           # 농도 대비 상대 크기(1σ). None = UNQUANTIFIED
    source: str = ""            # 어디서 나온 값인지 — 없으면 그 줄은 신뢰 못 한다
    note: str = ""

    @property
    def quantified(self) -> bool:
        return self.rel is not None


def build(conc_ppb, *, fit_err_ppb=None, total_err_ppb=None, T_C=None, P_mbar=None,
          xs_rel=None, r_rel=None, cavity_rel=None, residual_rel=None,
          extra=()) -> list:
    """한 농도값의 예산 줄들을 만든다. **모르는 건 None으로 남긴다.**

    conc_ppb       : 보고 농도(ppb)
    fit_err_ppb    : 결과 파일의 `<gas>_Error` (핏 공분산, 무작위)
    total_err_ppb  : 결과 파일의 `<gas>_TotalError` (핏 + T/P 전파)
    T_C, P_mbar    : 그 행의 실측 온·압 — 이상기체 항 계산에 필요
    xs_rel         : 단면 문헌 불확도(상대). **논문에서 가져와 넣어야 하는 값**
    r_rel          : σ(R) → 경로길이 불확도(상대). R_*.npz의 knot 산포에서 유도 가능
    cavity_rel     : 캐비티 길이 d·R_L 불확도(상대)
    residual_rel   : 잔차 구조(콜드 고정패턴)가 농도에 주는 몫(상대)
    """
    c = abs(float(conc_ppb)) or float("nan")
    terms = []

    if fit_err_ppb is not None:
        terms.append(Term("Fit covariance (perr)", RANDOM, abs(fit_err_ppb) / c,
                          "result file <gas>_Error",
                          "Diagonal of the VarPro linear-solution covariance — already per row"))

    # T/P 전파는 TotalError에 이미 합성돼 있으므로 **빼서** 분리한다(이중계산 금지)
    if fit_err_ppb is not None and total_err_ppb is not None:
        d2 = float(total_err_ppb) ** 2 - float(fit_err_ppb) ** 2
        tp = (d2 ** 0.5 if d2 > 0 else 0.0)
        terms.append(Term("T·P propagation", RANDOM, tp / c,
                          "<gas>_TotalError ⊖ <gas>_Error",
                          "assumes ±1 °C·±1 mbar (worker.py) — replace with actual sensor specs"))

    if T_C is not None and P_mbar is not None:
        terms.append(Term("Ideal gas (Z uncorrected)", SYSTEMATIC,
                          ideal_gas_bias(T_C, P_mbar),
                          "core.error_budget.ideal_gas_bias",
                          "Concentration is **always high by this much**. Correct only on the ppb path (σ is ideal-gas by convention)"))

    terms.append(Term("Cross-section (lit.)", SYSTEMATIC, xs_rel,
                      "original papers (Vandaele 2002 / Volkamer 2005 / Thalman 2013)",
                      "typically 3–5%, likely the largest term — **fill this in**"))
    terms.append(Term("σ(R) → path length", SYSTEMATIC, r_rel,
                      "R_<ch>.npz knot scatter",
                      "α ∝ (1−R)/d, so R uncertainty maps directly onto concentration scale"))
    terms.append(Term("Cavity length d · R_L", SYSTEMATIC, cavity_rel,
                      "measured (ASIA-AQ) — uncertainty not recorded",
                      "d=51.8 cm, R_L per channel 0.9330/0.9950/0.9968"))
    terms.append(Term("Residual fixed pattern", SYSTEMATIC, residual_rel,
                      "docs/Augur_소개_2026-07.md §10-1",
                      "documented as dominating the cold-channel uncertainty, not noise"))

    terms.extend(extra)
    return terms


def totals(terms) -> dict:
    """무작위는 제곱합, 계통은 선형합. **뭉개지 않는다.**"""
    rnd = [t.rel for t in terms if t.kind == RANDOM and t.quantified]
    sysx = [t.rel for t in terms if t.kind == SYSTEMATIC and t.quantified]
    missing = [t.name for t in terms if not t.quantified]
    return {
        "random_rel": (sum(x * x for x in rnd) ** 0.5) if rnd else None,
        "systematic_rel": sum(abs(x) for x in sysx) if sysx else None,
        "systematic_signed_rel": sum(sysx) if sysx else None,
        "unquantified": missing,
    }


def format_budget(terms, conc_ppb, gas="", header=True) -> str:
    """사람이 읽는 표. 정량화된 줄은 크기순, 미정량은 아래에 모아 **드러낸다**."""
    c = abs(float(conc_ppb))
    out = []
    if header:
        out.append(f"Error budget — {gas or 'gas'} = {conc_ppb:.4g} ppb")
        out.append(f"{'Term':<26}{'Kind':<6}{'Rel.':>10}{'Abs.(ppb)':>13}  Source")
        out.append("-" * 92)
    q = sorted([t for t in terms if t.quantified], key=lambda t: -abs(t.rel))
    for t in q:
        out.append(f"{t.name:<26}{'random' if t.kind == RANDOM else 'syst.':<6}"
                   f"{t.rel * 100:>9.4f}%{t.rel * c:>13.5g}  {t.source}")
    for t in terms:
        if not t.quantified:
            out.append(f"{t.name:<26}{'syst.' if t.kind == SYSTEMATIC else 'random':<6}"
                       f"{'unquant.':>10}{'—':>13}  {t.source}")
    tt = totals(terms)
    out.append("-" * 92)
    if tt["random_rel"] is not None:
        out.append(f"{'Random sum (√Σσ²)':<26}{'':<6}{tt['random_rel'] * 100:>9.4f}%"
                   f"{tt['random_rel'] * c:>13.5g}")
    if tt["systematic_rel"] is not None:
        out.append(f"{'Systematic sum (linear)':<26}{'':<6}{tt['systematic_rel'] * 100:>9.4f}%"
                   f"{tt['systematic_rel'] * c:>13.5g}  ← does not average down")
    if tt["unquantified"]:
        out.append(f"⚠ {len(tt['unquantified'])} unquantified term(s): {', '.join(tt['unquantified'])}")
        out.append("  → This table is a **lower bound**. No total uncertainty can be stated until the terms above are filled in.")
    return "\n".join(out)


def from_result_file(path, gas=None, *, row=None, **known):
    """저장된 결과 파일의 한 행(기본: 중앙값 농도 행)으로 예산 표를 만든다.

    `<gas>`·`<gas>_Error`·`<gas>_TotalError`·`T_used_C`·`P_used_mbar` 컬럼을 읽는다.
    정량화 안 된 항(`xs_rel` 등)은 `known=`으로 직접 넣는다 — 없으면 미정량으로 남는다.

        python -m core.error_budget <결과.dat> [가스명]
    """
    try:
        from core.result_io import read_result
    except ImportError:
        from result_io import read_result

    comments, colhdr, rows = read_result(path)
    cols = colhdr.split("\t")
    idx = {c: i for i, c in enumerate(cols)}
    gases = [c for c in cols if (c + "_Error") in idx]
    if not gases:
        raise ValueError("No gas column (<gas>_Error) — is this a fit result file?")
    gas = gas or gases[0]
    if gas not in gases:
        raise ValueError(f"'{gas}' not found. Available gases: {gases}")

    def _f(r, name):
        i = idx.get(name)
        if i is None or i >= len(r):
            return None
        try:
            v = float(r[i])
        except ValueError:
            return None
        return v if v == v else None        # NaN 제외

    parsed = [(t, ln.split("\t")) for t, ln in rows]
    vals = [(t, r) for t, r in parsed if _f(r, gas) is not None]
    if not vals:
        raise ValueError(f"No valid values for {gas} (all QC/NaN?)")
    if row is None:                          # 대표행 = 농도 중앙값에 가장 가까운 행
        import statistics
        med = statistics.median(_f(r, gas) for _, r in vals)
        _, r = min(vals, key=lambda tr: abs(_f(tr[1], gas) - med))
    else:
        r = vals[int(row)][1]

    return gas, _f(r, gas), build(
        _f(r, gas), fit_err_ppb=_f(r, gas + "_Error"),
        total_err_ppb=_f(r, gas + "_TotalError"),
        T_C=_f(r, "T_used_C"), P_mbar=_f(r, "P_used_mbar"), **known)


def _demo():
    """자기검증: 이중계산 금지 · 무작위/계통 분리 · 미정량이 숨지 않는지."""
    # Z: 알려진 값과 맞나 (건공기 0 °C, 1 atm → Z ≈ 0.9994)
    z0 = compressibility(0.0, 1013.25)
    assert 0.9993 < z0 < 0.9995, z0
    assert 4e-4 < ideal_gas_bias(0.0, 1013.25) < 7e-4, ideal_gas_bias(0.0, 1013.25)
    # 따뜻할수록 작아진다(비이상성 완화)
    assert ideal_gas_bias(35.0, 1013.25) < ideal_gas_bias(0.0, 1013.25)
    # 진공 극한에서는 이상기체로 수렴
    assert abs(ideal_gas_bias(25.0, 1.0)) < 1e-6

    terms = build(0.64, fit_err_ppb=0.08, total_err_ppb=0.0803,
                  T_C=25.0, P_mbar=1013.25)
    tt = totals(terms)

    # T/P 항은 TotalError에서 **빼서** 얻는다 — 핏 오차를 두 번 세면 안 된다
    tp = next(t for t in terms if "T·P" in t.name)
    assert tp.rel * 0.64 < 0.08, "T/P term as large as the fit error = double counting"
    # 무작위 합은 제곱합이라 최대항보다 크되 선형합보다 작다
    rnd = [t.rel for t in terms if t.kind == RANDOM]
    assert max(rnd) <= tt["random_rel"] <= sum(rnd) + 1e-12
    # 계통은 선형합(상쇄 가정 금지)
    assert tt["systematic_rel"] >= abs(tt["systematic_signed_rel"])
    # ★ 미정량 항이 반드시 남아야 한다 — 숨으면 "다 안다"는 거짓말이 된다
    assert len(tt["unquantified"]) == 4, tt["unquantified"]
    txt = format_budget(terms, 0.64, "NO2")
    assert "unquantified" in txt and "lower bound" in txt

    # 실제 결과 파일 경로도 돈다(컬럼 이름 계약이 깨지면 여기서 걸린다)
    import os, tempfile
    d = tempfile.mkdtemp(prefix="budget-")
    fp = os.path.join(d, "demo_fit.dat")
    with open(fp, "w", encoding="utf-8") as fh:
        fh.write("# demo\n")
        fh.write("Time\tT_used_C\tP_used_mbar\tNO2\tNO2_Error\tNO2_TotalError\n")
        for i, c in enumerate((0.55, 0.64, 0.80)):
            fh.write("2026-09-04 10:0%d:00\t25.0\t1013.25\t%.3f\t0.080\t0.0803\n"
                     % (i, c))
    g, c, tf = from_result_file(fp, "NO2")
    assert g == "NO2" and abs(c - 0.64) < 1e-9, (g, c)      # 중앙값 행을 골랐나
    assert any("Ideal gas" in t.name for t in tf)
    assert len(totals(tf)["unquantified"]) == 4
    import shutil; shutil.rmtree(d, ignore_errors=True)

    # 값을 채우면 미정량이 줄고 계통 합이 커진다
    terms2 = build(0.64, fit_err_ppb=0.08, total_err_ppb=0.0803, T_C=25.0,
                   P_mbar=1013.25, xs_rel=0.03)
    assert len(totals(terms2)["unquantified"]) == 3
    assert totals(terms2)["systematic_rel"] > tt["systematic_rel"]

    print(txt)
    print()
    print("error_budget self-check OK (Z@0C=%.6f, %d unquantified terms)"
          % (z0, len(tt["unquantified"])))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:                    # 실제 결과 파일로
        _gas, _c, _terms = from_result_file(sys.argv[1],
                                            sys.argv[2] if len(sys.argv) > 2 else None)
        print(format_budget(_terms, _c, _gas))
    else:
        _demo()
