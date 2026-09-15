"""core/fitset_builder.py — 맨바닥 FitSet 자동 생성(오케스트레이터).
==================================================================

**입력: 웨이브칼 + 레퍼런스 폴더 + 알파 표본. 그 외 아무 세팅도 받지 않는다.**
출력: 앱이 그대로 읽는 FitSet 채널 config(dict).

기존 모듈을 조립한다(중복 구현 금지):
  * `window_designer` — 핏창·poly (핏 없이 c-optimality + 편향지표)
  * `fit_physics`     — 레퍼런스 취사 물리심판(공선성·상수성·절대량)
  * `param_optimizer` — shift/squeeze/step_limit/Link (넓게 풀어 실측 분포→bounds)

자동 결정 vs 사용자 몫
----------------------
자동: refs 취사, ref `mult`(10^지수), 핏창(px·nm), `poly_deg`, ref별 sh/sq 정책+크기,
      `step_limit`, 2차 ref Link 여부.
사용자: `t_ref`·`t_coeff`(dσ/dT)·`active_bands_nm` — 물리/화학 판단(사용자 지정 2026-07-22).
원칙 고정(최적화 안 함): Tikhonov·Robust·Kalman = OFF/기본, Neg·QC = 정책.

닭-달걀 처리: 창을 정하려면 ref 세트가 필요하고 ref 취사에는 창이 필요하다 →
**2패스**(전체 후보로 임시 창 → ref 취사 → 최종 창 재설계).
"""
from __future__ import annotations

import glob
import os
import re

import numpy as np

from core import window_designer as WD
from core import fit_physics as FP
from core import health_checks as HC
from core import param_optimizer as PO
from core.doas_fit import DoasFitter
from core.engine import UniversalEngine

# 종별 기대 단면 크기(피크). 파일 단위가 제각각이라 `mult`(10^지수)로 맞춘다.
# 일반 기체는 cm²(~1e-19), O4는 collision-induced라 cm⁵/molec²(~1e-46).
EXPECTED_PEAK = {"O4": 1e-46, "_default": 1e-19}


def derive_mult(name, peak):
    """레퍼런스 파일 피크 → `mult`(10^지수) 자동 도출.

    파일이 이미 물리단위면 0. HITRAN H2O처럼 스케일이 다르면 지수를 되돌린다
    (실측: H2O 피크 7.9e-07 → mult −12 → 7.9e-19. 사용자 수동값 −12와 일치)."""
    if not np.isfinite(peak) or peak <= 0:
        return 0
    target = EXPECTED_PEAK.get(name, EXPECTED_PEAK["_default"])
    # ★ratio의 round가 아니라 **decade(floor) 정렬**이어야 한다. 6.99e-19는 이미 옳은
    # 자릿수인데 round(log10(1e-19/6.99e-19))=-1이 되어 한 자릿수 틀린다.
    # floor 정렬: NO2 0 / CHOCHO 0 / H2O -12 / O4 0 — 사용자 수동값과 4/4 일치 검증됨.
    return int(-np.floor(np.log10(peak)) + np.floor(np.log10(target)))


def _species_from_filename(path):
    """Ref_<종>_....dat → 종 이름. 'H2O-HITRAN' 같은 접미는 앞부분만."""
    b = os.path.basename(path)
    m = re.match(r"Ref_(.+?)_(Dynamic|Conv|ILS|.*Applied)", b)
    raw = m.group(1) if m else os.path.splitext(b)[0].replace("Ref_", "")
    return raw.split("-")[0]


def discover_references(ref_dir):
    """폴더에서 레퍼런스 후보를 발견 → [(종, 경로, mult)]. 사용자 입력 없음."""
    out = []
    for p in sorted(glob.glob(os.path.join(ref_dir, "Ref_*.dat"))):
        try:
            v = np.array([float(l) for l in open(p, encoding="utf-8", errors="replace")
                          if l.strip() and not l.lstrip().startswith("#")])
        except Exception:                 # noqa: BLE001
            continue
        if v.size < 100:
            continue
        name = _species_from_filename(p)
        out.append(dict(name=name, path=p, mult=derive_mult(name, float(np.max(np.abs(v)))),
                        peak=float(np.max(np.abs(v)))))
    return out


def build_engine(wl_path, refs, load_wavecal):
    """app_window._build_engine_from_config와 동일 규약으로 엔진 구성."""
    eng = UniversalEngine()
    wave = load_wavecal(wl_path)
    if wave is not None:
        eng.set_wavelength_axis(wave)
    for r in refs:
        if os.path.exists(r["path"]):
            try:
                eng.add_reference(name=r["name"], filepath=r["path"], wave_nm=wave,
                                  multiplier=10.0 ** r["mult"])
            except Exception:             # noqa: BLE001
                pass
    try:
        eng.apply_ils_convolution(0.0)
    except Exception:
        pass
    return eng, wave


# ──────────────────────────────────────────────────────────────────────────
def select_references(eng, alphas, candidates, wave, T_C, P_mbar,
                      px_min, px_max, poly_deg, target="NO2",
                      mdl_worsen_max=1.02, f_crit=10.0):
    """후보 레퍼런스 취사 — **핏 없이**. 기준은 "실제로 흡수하는가"(신호)이지
    "타깃 정밀도에 이득인가"가 아니다.

    ⚠️타깃 MDL만 보면 **실재하는 흡수체까지 빼버린다**(실측: CHOCHO 제외됨). 실재 흡수체를
    빼면 그 구조가 타깃으로 새어 **편향**이 된다 — 빼는 쪽이 입증책임(헌장③).
    규칙:
      1) 넣었을 때 잔차 구조가 의미있게 줄면(chi 개선) → **실재 흡수체, 포함**
      2) 신호가 없고(개선 없음) 타깃 MDL만 갉아먹으면 → 제외(순수 간섭·퇴화)
      3) 절대량 이론값을 아는 종(O4)은 물리 심판이 우선(과적합 스펀지 차단)"""
    keep = [target]
    log = []
    sig_px, _ = WD.estimate_noise(alphas)
    noise_sl = sig_px[px_min:px_max + 1]
    ys = [np.asarray(a, float)[px_min:px_max + 1] for a in np.asarray(alphas, float)]

    rho = WD.residual_rho(eng, alphas, [target], px_min, px_max, poly_deg)
    n_pix = px_max - px_min + 1
    # AR(1) 유효표본수 — 잔차가 상관되어 있으면 실제 정보량은 픽셀 수보다 적다.
    n_eff = max(n_pix * (1.0 - rho) / (1.0 + rho), 10.0)

    def _rss(species):
        sh = WD.estimate_shift(eng, alphas, species, px_min, px_max, poly_deg)
        A, _ = WD.design_matrix(eng, species, px_min, px_max, poly_deg, 0.30, shift=sh)
        out = []
        for y in ys:
            c_, *_ = np.linalg.lstsq(A, y, rcond=None)
            r = y - A @ c_
            out.append(float(r @ r))
        return float(np.median(out)), A.shape[1]

    for c in candidates:
        n = c["name"]
        if n == target:
            continue
        rss_wo, p_wo = _rss(keep)
        rss_w, p_w = _rss(keep + [n])
        # ★F-검정: 열 하나를 더하면 RSS는 항상 줄지만, **우연 이상으로** 줄었는지 본다.
        # 고정 퍼센트 문턱은 매직넘버라 실측에서 1.7% vs 2%처럼 간발로 결정이 뒤집혔다.
        # 자유도는 유효표본수(n_eff)로 — 자기상관을 무시하면 유의성을 과대평가한다.
        dof = max(n_eff - p_w, 1.0)
        F = ((rss_wo - rss_w) / max(p_w - p_wo, 1)) / (rss_w / dof) if rss_w > 0 else 0.0
        gain = (rss_wo - rss_w) / max(rss_wo, 1e-300)
        cmp = WD.compare_species(eng, alphas, keep, n, wave, T_C, P_mbar,
                                 px_min, px_max, poly_deg, target)
        has_signal = F > f_crit
        harmful = cmp["ratio"] > mdl_worsen_max
        ok = has_signal or not harmful
        if ok:
            keep.append(n)
        log.append(dict(name=n, ratio=cmp["ratio"], chi_gain=float(gain), F=float(F),
                        decision=("include(신호)" if has_signal else
                                  "include(무해)" if ok else "exclude(신호없음·간섭)"),
                        multR_with=cmp["with"]["multiple_R"],
                        multR_without=cmp["without"]["multiple_R"]))
    return keep, log


def build_fitset(wl_path, ref_dir, scans, load_wavecal, consecutive_scans=None,
                 target="NO2", label="auto", cavity_d=51.8,
                 starts_nm=None, ends_nm=None, n_design_alphas=8, progress=None,
                 use_center_mode=True, *, allow_negative_gas):
    """맨바닥 → FitSet 채널 config. 세팅 입력 없음.

    scans: [(wave, alpha, T_C, P_mbar), ...]   consecutive_scans: step_limit 추정용(연속)."""
    allow_negative_gas = PO._require_bool(allow_negative_gas)
    def _say(m):
        if progress:
            progress(m)

    # 0) 레퍼런스 발견 + mult 자동
    cands = discover_references(ref_dir)
    _say(f"레퍼런스 발견: {[(c['name'], c['mult']) for c in cands]}")
    eng, wave = build_engine(wl_path, cands, load_wavecal)
    if wave is None:
        raise ValueError("wavecal 로드 실패")

    # ── 사전검증(health_checks) — 후보 refs셋 평가 *전* 게이트(fit_optimizer_handoff.md §7·§10-C).
    # 웨이브칼 손상(비단조·범위이상)이나 레퍼런스 결함(빈값·평평·격자불일치)을 여기서 못 잡으면
    # 이후 창설계·ref취사·파라미터 추정 전부가 조용히 오염된 입력 위에서 돈다.
    _say("사전검증(웨이브칼·레퍼런스)…")
    wc_status, wc_msg, wc_metrics = HC.check_wavecal(wave)
    refs_for_check = {}
    for c in cands:
        interp = eng.interpolators.get(c["name"])
        if interp is not None:
            try:
                refs_for_check[c["name"]] = np.asarray(interp(wave), dtype=float)
            except Exception:                 # noqa: BLE001
                pass
    rf_status, rf_msg, rf_metrics = HC.check_references(refs_for_check, wl=wave)
    preflight = [("wavecal", wc_status, wc_msg, wc_metrics),
                ("references", rf_status, rf_msg, rf_metrics)]
    pf_status, pf_msg = HC.overall(preflight)
    _say(f"사전검증 결과: {pf_status} — {pf_msg}")
    if pf_status == HC.FAIL:
        raise ValueError(f"사전검증 실패 — FitSet 생성 중단 (wavecal: {wc_msg} / references: {rf_msg})")

    alphas_all = np.array([s[1] for s in scans if len(s[1]) == len(wave)])
    alphas = alphas_all[:: max(1, len(alphas_all) // n_design_alphas)][:n_design_alphas]
    T_C = float(np.median([s[2] for s in scans]))
    P_mbar = float(np.median([s[3] for s in scans]))

    if starts_nm is None:
        lo0 = float(np.percentile(wave, 25))
        starts_nm = np.arange(round(lo0), round(lo0) + 28.1, 2.0)
    if ends_nm is None:
        hi0 = float(np.percentile(wave, 62))
        ends_nm = np.arange(round(hi0), round(hi0) + 28.1, 2.0)

    # 1) 1패스 창(전체 후보로) — ref 취사를 위한 임시 창
    _say("1패스: 임시 창 설계…")
    rows, meta = WD.scan_windows(eng, alphas, [c["name"] for c in cands], wave,
                                 T_C, P_mbar, starts_nm, ends_nm, target=target)
    ok = [r for r in rows if not r["gated"]] or rows
    tmp = ok[0]

    # 2) 레퍼런스 취사(핏 없이) + 절대량 물리심판
    _say("레퍼런스 취사…")
    keep, sel_log = select_references(eng, alphas, cands, wave, T_C, P_mbar,
                                      tmp["px_min"], tmp["px_max"], tmp["poly"], target)
    # 절대량을 아는 종은 물리로 재확인(포함으로 기울었어도 물리가 아니면 제외)
    fitter = DoasFitter(eng)
    rp_tmp = _default_ref_props([c["name"] for c in cands], target, wide=12.0)
    for c in cands:
        if c["name"] in keep and c["name"] != target and \
                FP.theoretical_amount(c["name"], T_C, P_mbar):
            v = FP.judge_reference(eng, fitter, scans[:8], rp_tmp, rp_tmp,
                                   tmp["px_min"], tmp["px_max"], tmp["poly"], 0.5,
                                   candidate=c["name"], target=target,
                                   allow_negative_gas=allow_negative_gas)
            if v["exclude"]:
                keep.remove(c["name"])
                for L in sel_log:
                    if L["name"] == c["name"]:
                        L["decision"] = "exclude(물리)"
                        L["physics"] = v["reasons"]
    _say(f"채택 refs: {keep}")

    # 3) 최종 창·poly 재설계(확정 ref 세트로)
    _say("2패스: 최종 창 설계…")
    eng2, _ = build_engine(wl_path, [c for c in cands if c["name"] in keep], load_wavecal)
    fitter2 = DoasFitter(eng2)
    rows2, meta2 = WD.scan_windows(eng2, alphas, keep, wave, T_C, P_mbar,
                                   starts_nm, ends_nm, target=target)
    ok2 = [r for r in rows2 if not r["gated"]] or rows2
    best = _parsimonious(ok2)
    px_min, px_max, poly = best["px_min"], best["px_max"], best["poly"]

    # 4) 파라미터: shift/squeeze(넓게 풀어 실측 분포로), step_limit, Link
    _say("파라미터 추정…")
    rp = _default_ref_props(keep, target, wide=12.0)
    sh = PO.recommend_shift(scans, eng2, fitter2, rp, px_min, px_max, poly,
                            target, wide=12.0, allow_negative_gas=allow_negative_gas)
    sq = PO.recommend_squeeze(scans, eng2, fitter2, rp, px_min, px_max, poly,
                              target,
                              step_limit=max(abs(sh.get("lb", 1.0)), abs(sh.get("ub", 1.0)), 1.0),
                              allow_negative_gas=allow_negative_gas)
    step = dict(value=None, reason="연속 스캔 없음")
    if consecutive_scans:
        step = PO.recommend_step_limit(consecutive_scans, eng2, fitter2, rp,
                                       px_min, px_max, poly, target,
                                       allow_negative_gas=allow_negative_gas)
    links = []
    for s in keep:
        if s != target:
            links.append(PO.recommend_secondary_link(scans, eng2, fitter2, rp, px_min, px_max,
                                                     poly, s, target,
                                                     step_limit=step.get("value") or 1.0,
                                                     allow_negative_gas=allow_negative_gas))

    # 5) 조립
    ref_props = {}
    for s in keep:
        if s == target:
            if sh["policy"] == "Limit":
                _lo, _hi = float(sh["lb"]), float(sh["ub"])
                if use_center_mode:
                    # ★Center 모드: 허용창을 **실측 중심**에 앵커 → 0을 품을 필요가 없어
                    # 측정된 만큼 좁게 줄 수 있고, 0에서 걸어 들어오느라 초반 스캔을 버리지도 않는다.
                    c_val = float(sh.get("median", 0.0))
                    half = max(abs(_hi - c_val), abs(c_val - _lo))
                    sh["runnable"] = (c_val - half, c_val + half)
                    sh["widened_for_engine"] = False
                    sh["center_mode"] = (c_val, half)
                    sh_mode, sh_val = "Center", f"{round(c_val, 2)}, {round(half, 2)}"
                else:
                    _lo, _hi, _w = runnable_shift_bounds(_lo, _hi,
                                                        float(step.get("value") or 0.5))
                    sh["runnable"] = (_lo, _hi)
                    sh["widened_for_engine"] = _w
                    sh_mode, sh_val = "Limit", f"{_lo}, {_hi}"
            else:
                sh_mode, sh_val = "Fix", str(sh.get("value", 0.0))
            if sq["policy"] == "Limit":
                sq_mode, sq_val = "Limit", f"{sq['lo']}, {sq['hi']}"
            else:
                sq_mode, sq_val = "Fix", str(sq.get("value", 1.0))
        else:
            d = next((l for l in links if l["secondary"] == s), None)
            if d and d["decision"] == "Independent":
                sh_mode, sh_val = "Limit", f"{d['lb']}, {d['ub']}"
                sq_mode, sq_val = "Link", target
            else:
                sh_mode, sh_val, sq_mode, sq_val = "Link", target, "Link", target
        ref_props[s] = {"sh_mode": sh_mode, "sh_val": sh_val,
                        "sq_mode": sq_mode, "sq_val": sq_val,
                        # ↓ 사용자 몫(자동화 대상 아님) — 중립 기본값으로 두고 보고서에 명시
                        "t_ref": 25.0, "t_coeff": 0.0, "active_bands_nm": ""}

    cfg = {
        "wl_path": wl_path,
        "refs": [{"name": c["name"], "path": c["path"], "mult": c["mult"]}
                 for c in cands if c["name"] in keep],
        "data_label": label,
        "time_shift_h": 0.0, "gas_temp": 0.0,
        "f_min": str(px_min), "f_max": str(px_max),
        "fit_start_nm": round(float(wave[px_min]), 2),
        "fit_end_nm": round(float(wave[px_max]), 2),
        "fit_unit": "px",
        "poly_deg": int(poly),
        "step_limit": float(step["value"]) if step.get("value") else 0.5,
        "ref_props": ref_props,
        # 원칙 고정(최적화 대상 아님)
        "tikhonov_lambda": 0.0, "use_robust": False,
        "allow_negative_gas": bool(allow_negative_gas),
        "kalman_q": 0.0005, "kalman_r": 0.05,
        "cavity_d": cavity_d, "rl_factor": 1.0,
    }
    problems = validate_fitset(cfg, target)
    report = dict(problems=problems, preflight=preflight,
                  policy_provenance={"allow_negative_gas": "explicit build_fitset argument"},
                  candidates=cands, selection=sel_log, keep=keep, window=best,
                  shift=sh, squeeze=sq, step=step, links=links, meta=meta2,
                  design_rank=[r for r in rows2[:5]])
    return cfg, report


def runnable_shift_bounds(lb, ub, step_limit):
    """★불변식: 생성된 shift 범위는 **현재 엔진에서 실행 가능해야** 한다.

    `setup_fit_parameters`는 bounds = [전역범위] ∩ [center ± step_limit]로 잡고,
    워커는 `last_valid_shift = 0`에서 시작해 step_limit씩 걸어간다(worker.py:300,338).
    따라서 **0을 포함하지 않는 범위는 첫 스캔부터 교집합이 비어 least_squares가 죽는다**
    (실측: [-9,-1.5] + step 0.5 → bounds [-0.5,-1.5] → ValueError).
    → 측정된 최적 범위가 0을 벗어나면 **0까지 확장**해 걸어 들어갈 수 있게 한다.
    (근본 해결은 '측정 shift를 시작 중심으로 쓰는 Center 모드' — 엔진 수정 필요.)"""
    lo, hi = float(min(lb, ub)), float(max(lb, ub))
    widened = False
    if lo > 0.0:
        lo, widened = 0.0, True
    if hi < 0.0:
        hi, widened = 0.0, True
    return lo, hi, widened


def validate_fitset(cfg, target="NO2"):
    """생성된 FitSet이 **실제 엔진에서 돌아가는지** 불변식 검사 → [문제 문자열].

    옵티마이저가 '통계적으로 좋은' 세팅을 내도 엔진이 못 돌리면 무의미하다.
    출력 전 반드시 통과시킬 것."""
    problems = []
    step = float(cfg.get("step_limit", 0.5) or 0.5)
    for g, pr in cfg.get("ref_props", {}).items():
        if pr.get("sh_mode") == "Center":
            try:
                c_, h_ = map(float, str(pr["sh_val"]).split(","))
                if abs(h_) <= 0:
                    problems.append(f"{g}: Center 반폭이 0 이하")
            except Exception:
                problems.append(f"{g}: sh_val(Center) 파싱 불가 '{pr.get('sh_val')}'")
        elif pr.get("sh_mode") == "Limit":
            try:
                lo, hi = map(float, str(pr["sh_val"]).split(","))
            except Exception:
                problems.append(f"{g}: sh_val 파싱 불가 '{pr.get('sh_val')}'")
                continue
            if hi <= lo:
                problems.append(f"{g}: sh_val 상하한 역전 ({lo}, {hi})")
            # 첫 스캔(center=0)에서 교집합이 비면 핏이 죽는다
            if not (lo <= step and hi >= -step):
                problems.append(f"{g}: sh_val [{lo},{hi}]이 시작점 0±{step}과 교집합 없음 → 핏 불가")
        elif pr.get("sh_mode") == "Fix":
            # 2026-09-15 추가: Fix는 검사에서 빠져 있었다. doas_fit이 예전에는
            # 파싱 실패를 0.0으로 조용히 갈아탔으므로(지금은 예외) 여기서도 잡는다.
            try:
                float(str(pr["sh_val"]))
            except Exception:
                problems.append(f"{g}: sh_val(Fix) 파싱 불가 '{pr.get('sh_val')}'")
        if pr.get("sq_mode") == "Limit":
            try:
                lo, hi = map(float, str(pr["sq_val"]).split(","))
                if hi <= lo:
                    problems.append(f"{g}: sq_val 상하한 역전")
            except Exception:
                problems.append(f"{g}: sq_val 파싱 불가")
        elif pr.get("sq_mode") == "Fix":
            try:
                float(str(pr["sq_val"]))
            except Exception:
                problems.append(f"{g}: sq_val(Fix) 파싱 불가 '{pr.get('sq_val')}'")
    try:
        if int(cfg["f_max"]) - int(cfg["f_min"]) < 50:
            problems.append("핏창이 너무 좁음(<50px)")
    except Exception:
        problems.append("f_min/f_max 파싱 불가")
    if target not in cfg.get("ref_props", {}):
        problems.append(f"타깃 {target}가 ref_props에 없음")
    return problems


def _parsimonious(rows, tol=0.08):
    """**창을 먼저 고르고, 그 창 안에서** 가장 단순한 poly를 고른다.

    ⚠️창을 가로질러 절약선택을 하면 안 된다: 창마다 MDL 스케일이 달라 비교가 뒤섞이고,
    실제로 엉뚱한 高poly가 뽑혔다(실측 PNs poly8 — 같은 창 안에선 poly2가 더 좋았음).
    高poly는 광대역과 함께 타깃 구조까지 먹을 위험이 크므로 동등하면 단순한 쪽
    (헌장③ 입증책임은 자유도 더하는 쪽 = optimize_poly 무릎점과 같은 철학)."""
    if not rows:
        return None
    def eff(r):
        return r["mdl_ppb"] * max(r["robust_ratio"], 1.0) * max(r["chi"], 1.0)
    # ① 창 선택: 각 창의 '최선 poly' 성적으로 창들을 비교
    by_win = {}
    for r in rows:
        k = (r["px_min"], r["px_max"])
        if k not in by_win or eff(r) < eff(by_win[k]):
            by_win[k] = r
    win = min(by_win.values(), key=eff)
    # ② 그 창 안에서 poly 절약선택
    same = [r for r in rows if (r["px_min"], r["px_max"]) == (win["px_min"], win["px_max"])]
    b = min(eff(r) for r in same)
    near = [r for r in same if eff(r) <= b * (1.0 + tol)]
    return sorted(near, key=lambda r: r["poly"])[0]


def _default_ref_props(species, target, wide=12.0):
    """세팅이 전혀 없을 때의 출발 규약: 타깃만 넓게 풀고 나머지는 Link(절약)."""
    rp = {}
    for s in species:
        if s == target:
            rp[s] = {"sh_mode": "Limit", "sh_val": f"-{wide}, {wide}",
                     "sq_mode": "Limit", "sq_val": "-0.01, 0.01",
                     "t_ref": 25.0, "t_coeff": 0.0, "active_bands_nm": ""}
        else:
            rp[s] = {"sh_mode": "Link", "sh_val": target, "sq_mode": "Link",
                     "sq_val": target, "t_ref": 25.0, "t_coeff": 0.0,
                     "active_bands_nm": ""}
    return rp
