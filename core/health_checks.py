"""core/health_checks.py — 산출물 fit-readiness 건강검진(재사용 함수).

각 체크는 순수 함수(경로/배열을 인자로) → (status, msg, metrics) 반환.
  status : "PASS" | "WARN" | "FAIL" | "SKIP"
  msg    : 사람이 읽는 한 줄 요약(원인·권고 포함)
  metrics: {키: 값} 세부수치(드릴다운/로그용)

GUI 🩺 Health 탭과 tools/validate_pipeline이 공유한다. "이 산출물로 긴 핏을
돌려도 되나?"를 사전 판정하는 게 목적 — 조용한 오염(웨이브칼 shift·ref 누락·
나쁜 R·King회귀)을 긴 런 전에 빨간불로 잡는다.
"""
import os
import numpy as np

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"


def check_wavecal(wl, anchors=None, tol_nm=0.25, expect_range=None):
    """파장 배열(nm) 건강: 단조증가·유한·범위·(옵션)Hg 앵커 위치.

    anchors=[(픽셀, 실제nm), ...] 주면 Hg 라인 정합까지. expect_range=(lo,hi)."""
    wl = np.asarray(wl, float)
    if wl.size < 2:
        return FAIL, "파장 배열이 비었거나 너무 짧음", {}
    if not np.isfinite(wl).all():
        return FAIL, "파장에 NaN/inf 있음", {"n_bad": int((~np.isfinite(wl)).sum())}
    if np.any(np.diff(wl) <= 0):
        return FAIL, "파장이 단조증가 아님 (웨이브칼 손상)", {}
    disp = float(np.median(np.diff(wl)))
    m = {"n": int(wl.size), "first_nm": float(wl[0]), "last_nm": float(wl[-1]),
         "disp_nm_px": disp}
    if expect_range and not (expect_range[0] <= wl[0] and wl[-1] <= expect_range[1]):
        return WARN, f"파장범위 {wl[0]:.1f}~{wl[-1]:.1f}nm (예상 {expect_range} 밖)", m
    if anchors:
        errs = [abs(float(wl[px]) - nm) for px, nm in anchors if 0 <= px < wl.size]
        if errs:
            worst = max(errs)
            m["hg_worst_nm"] = worst
            if worst > tol_nm:
                return FAIL, f"Hg 라인 최대 {worst:.2f}nm 어긋남 (>{tol_nm}, 웨이브칼 교체?)", m
            return PASS, f"단조·범위 OK · Hg 라인 ±{worst:.2f}nm 이내", m
    return PASS, f"단조증가 · {wl[0]:.0f}~{wl[-1]:.0f}nm · 분산 {disp:.3f}nm/px", m


def check_references(refs, wl=None, collin_warn=0.98):
    """refs: {name: 1d array}(ILS 적용된 레퍼런스). 존재·비퇴화·격자·공선성.

    공선성(쌍별 |상관|)이 높으면 핏에서 서로/etalon/poly와 뒤섞여 불안정."""
    if not refs:
        return FAIL, "레퍼런스가 하나도 없음 (핏 불가)", {}
    issues, mats = [], []
    for name, arr in refs.items():
        a = np.asarray(arr, float)
        if a.size == 0 or not np.isfinite(a).any():
            issues.append(f"{name}:빈/전부NaN"); continue
        # 절대 std가 아니라 **자기 피크 대비 상대** std로 평평함을 판정한다 — 종마다 원본 단위
        # 스케일이 완전히 다르다(일반 기체 ~1e-19cm², O4는 충돌유도흡수라 ~1e-46cm⁵).
        # 절대 문턱(예: 1e-30)은 O4처럼 피크 자체가 작은 종을 전부 "평평"으로 오판한다
        # (실측: O4 std=1.4e-49인데 std/peak=0.22로 CHOCHO(0.16)·H2O(0.24)와 같은 급 —
        # 진짜 구조가 있는데 절대문턱 때문에 FAIL로 잘못 걸렸었다).
        peak = float(np.nanmax(np.abs(a))) if np.isfinite(a).any() else 0.0
        if peak <= 0 or float(np.nanstd(a)) < 1e-6 * peak:
            issues.append(f"{name}:평평(퇴화)")
        if wl is not None and len(a) != len(np.asarray(wl)):
            issues.append(f"{name}:격자길이≠wavecal")
        mats.append((name, a))
    worst_corr, worst_pair = 0.0, None
    for i in range(len(mats)):
        for j in range(i + 1, len(mats)):
            a, b = mats[i][1], mats[j][1]
            L = min(len(a), len(b))
            aa = a[:L] - np.nanmean(a[:L]); bb = b[:L] - np.nanmean(b[:L])
            d = np.sqrt(np.nansum(aa * aa) * np.nansum(bb * bb))
            if d > 0:
                c = abs(float(np.nansum(aa * bb) / d))
                if c > worst_corr:
                    worst_corr, worst_pair = c, (mats[i][0], mats[j][0])
    m = {"n": len(refs), "worst_corr": worst_corr, "worst_pair": worst_pair}
    if issues:
        return FAIL, "레퍼런스 문제: " + ", ".join(issues), m
    if worst_corr > collin_warn:
        return WARN, (f"레퍼런스 {len(refs)}개, 공선성 높음 "
                      f"{worst_pair} r={worst_corr:.3f} — 핏 불안정 위험"), m
    return PASS, f"레퍼런스 {len(refs)}개 · 비퇴화 · 공선성 최대 r={worst_corr:.2f}", m


def check_rayleigh(wave_nm=447.0, golden=9.6997e-27, tol=0.001):
    """Rayleigh σ_ZA가 문헌 골든값과 맞나 (King factor 회귀 감지). 데이터 불필요."""
    try:
        from core.physics import RayleighPhysics
    except Exception as e:
        return SKIP, f"core.physics import 불가: {e}", {}
    # α를 σ로 되돌릴 땐 **같은** 밀도여야 한다 — 사본을 쓰면 이 검사가 상수값에 흔들린다.
    # (σ는 분자 고유값이라 밀도 상수와 무관해야 하는 게 맞다.)
    from core.physics import N_LOSCHMIDT as N0
    try:
        sig = RayleighPhysics.get_alpha_rayleigh(
            np.array([float(wave_nm)]), 0.0, 1013.25, "zero_air")[0] / N0
    except Exception as e:
        return FAIL, f"Rayleigh 계산 오류: {e}", {}
    rel = abs(sig - golden) / golden
    m = {"sigma": float(sig), "golden": golden, "rel": float(rel)}
    if rel < tol:
        return PASS, f"σ_ZA@{wave_nm:.0f}nm = {sig:.4e} (문헌 {rel*100:.3f}% 이내)", m
    return FAIL, f"σ_ZA {sig:.3e} vs 골든 {golden:.3e} ({rel*100:.2f}% 차 — King factor 회귀?)", m


def check_r(npz_path, band=(438.0, 476.0), d_cm=51.8):
    """R(t) npz 물리성: 대역내 R·Leff 범위 + 물리불가 knot 비율."""
    if not npz_path or not os.path.exists(npz_path):
        return SKIP, "R npz 없음(경로 미설정)", {}
    try:
        z = np.load(npz_path, allow_pickle=True)
        omr = np.asarray(z["omr_d"], float)
        wv = np.asarray(z["wave_nm"], float)
    except Exception as e:
        return FAIL, f"R npz 읽기 실패: {e}", {}
    if omr.size == 0 or wv.size == 0:
        return FAIL, "R npz가 비어있음", {}
    omr_m = np.nanmedian(omr, 0)
    m = (wv >= band[0]) & (wv <= band[1])
    if not m.any():
        return WARN, f"R 대역 {band} 밖 데이터", {"n_knot": int(omr.shape[0])}
    Rmed = float(np.nanmedian(1 - omr_m[m] * d_cm))
    leff = float(np.nanmean(1 / np.maximum(omr_m[m], 1e-12)) * 1e-5)
    leff_knot = np.nanmean(1 / np.maximum(omr[:, m], 1e-12), 1) * 1e-5
    n_bad = int(np.sum((leff_knot < 1) | (leff_knot > 50) | ~np.isfinite(leff_knot)))
    met = {"R": Rmed, "Leff_km": leff, "n_bad": n_bad, "n_knot": int(len(leff_knot))}
    if not (0.99 <= Rmed <= 0.999995 and 1 <= leff <= 50):
        return FAIL, f"R={Rmed:.5f} Leff={leff:.1f}km (물리범위 벗어남)", met
    if n_bad > 0.05 * max(len(leff_knot), 1):
        return WARN, f"R={Rmed:.5f} Leff={leff:.1f}km, 물리불가 knot {n_bad}/{len(leff_knot)}", met
    return PASS, f"R={Rmed:.5f} · Leff={leff:.1f}km · 물리불가 knot {n_bad}/{len(leff_knot)}", met


# 상태 우선순위(전체 판정 집계용): FAIL > WARN > PASS > SKIP
_RANK = {FAIL: 3, WARN: 2, PASS: 1, SKIP: 0}


def overall(results):
    """[(name, status, msg, metrics), ...] → (전체status, 요약문). 판정 로직 단일화."""
    if not results:
        return SKIP, "검사 항목 없음"
    n_fail = sum(1 for _n, s, *_ in results if s == FAIL)
    n_warn = sum(1 for _n, s, *_ in results if s == WARN)
    n_pass = sum(1 for _n, s, *_ in results if s == PASS)
    if n_fail:
        return FAIL, f"핏 금지 — 실패 {n_fail} (원인 수정 필요) · 경고 {n_warn} · 통과 {n_pass}"
    if n_warn:
        return WARN, f"진행 가능(주의) — 경고 {n_warn} · 통과 {n_pass}"
    return PASS, f"핏 준비 완료 — 전부 통과 {n_pass}"
