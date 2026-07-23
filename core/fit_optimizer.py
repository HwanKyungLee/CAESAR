"""core/fit_optimizer.py — 핏레인지+poly 자동탐색 코어(순수·Qt없음)
================================================================

CAESAR Pro "핏세팅 자동 최적화"의 **Stage 1**(핏레인지 + 다항식 차수) 헤드리스 엔진.

설계 헌장(데이터 무결성)
------------------------
* **목표는 잔차 RMS 최소화가 아니다.** RMS만 낮추면 옵티마이저는 poly↑·창 잘라먹기·
  shift 다 풀기로 수렴 → 잔차는 예쁜데 농도는 물리적으로 틀림(배경누설). 헌장 ①③④⑥ 위반.
* 1순위 축 = **검색 불확실도 `perr_rel`**(농도 오차/농도). 자유도를 늘리면 공분산이 커져
  perr가 스스로 부풀므로 과적합을 자연히 벌준다.
* **농도 안정성**이 1급 물리 가드: 창/차수를 조금 바꿔도 NO2가 안 흔들리면 진짜,
  흔들리면 배경누설. poly는 "RMS 최소"가 아니라 "농도가 안정되는 최소 차수"로 고른다.
* 자동 적용 없음. 후보 랭킹 + **현재 대비 Δ%농도**를 숫자로 찍고(헌장 ②) 사람이 승인.

이 모듈은 **순수**하다: I/O·엔진빌드·알파로더는 호출부(tools/optimize_fitrange.py 또는
GUI 워커)가 담당하고, 여기엔 이미 만들어진 engine/fitter와 알파 배열만 넘어온다.
그래야 core가 tools/Qt에 의존하지 않는다(패키징 이식성 유지).
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import interp1d


# ──────────────────────────────────────────────────────────────────────────
def air_number_density(T_C: float, P_mbar: float) -> float:
    """이상기체 수밀도 [molec/cm^3] — fit_one과 동일 식(ppb 환산용)."""
    return 2.68678e19 * (P_mbar / 1013.25) * (273.15 / (T_C + 273.15))


# ──────────────────────────────────────────────────────────────────────────
def fit_window(eng, fitter, ref_props, wave, alpha, T_C, P_mbar,
               px_min, px_max, poly_deg, step_limit=0.5, target="NO2"):
    """한 스캔을 한 (창, 차수)로 핏 → 스코어링 지표 dict.

    residual_compare.fit_one의 확장판: `perr`(검색 불확실도)와 shift-경계 여부,
    잔차 자기상관까지 뽑는다. 반환값은 전부 스칼라(호출부가 스캔들에 걸쳐 집계).
    실패 시 ValueError 없이 dict(ok=False, reason=...) 반환은 하지 않고 예외를 던진다
    — 호출부에서 스캔 단위로 try/except(‌‌오제거율 추적을 위해 skip 사유를 남길 것)."""
    sl = slice(px_min, px_max + 1)
    wl = np.asarray(wave, float)[sl]
    a = np.asarray(alpha, float)[sl]

    # 알파 nm격자 → 엔진 픽셀좌표(레퍼런스는 픽셀-인덱스 인터폴레이터)
    wax = np.asarray(eng._wave_axis, float).flatten()
    vp = np.asarray(interp1d(wax, np.arange(len(wax)), bounds_error=False,
                             fill_value="extrapolate")(wl), float)
    center = vp[len(vp) // 2]

    ef = fitter.detect_etalon_frequency(vp, a, poly_deg, 0.02, 0.40)
    active, fixed, linked, t0, lb, ub = fitter.setup_fit_parameters(
        ref_props, 0.0, [0.0, 1.0], step_limit)

    out = fitter.execute_varpro_fit(vp, a, np.eye(len(a)), active, fixed, linked,
                                    t0, lb, ub, poly_deg, ef, center, 1.0,
                                    ref_props, T_C, 0.0, False)
    opt_sh, opt_sq, gco, poly_c, eamp, ep, perr = out

    full, tot, base, etal, _ = eng.get_model_components(
        vp, opt_sh, opt_sq, gco, poly_c, etalon_amp=eamp, etalon_freq=ef,
        etalon_phase=ep)
    resid = a - full
    rms = float(np.sqrt(np.mean(resid ** 2)))
    sig = float(np.sqrt(np.mean(tot ** 2)))          # 가스흡수 신호 크기

    # lag-1 자기상관: 0=백색(노이즈한계), →1=구조 남음(underfit)
    rr = resid - resid.mean()
    autocorr1 = float(np.dot(rr[:-1], rr[1:]) / (np.dot(rr, rr) + 1e-30))

    # 타깃 농도(ppb) + 상대 검색 불확실도(mu/sc/n_air가 상쇄돼 perr/|coeff|만 남음)
    n_air = air_number_density(T_C, P_mbar)
    conc = perr_rel = float("nan")
    if target in eng.gas_list:
        gi = eng.gas_list.index(target)
        sc = eng.scaling_factors.get(target, 1.0)
        mu = eng.multipliers.get(target, 1.0)
        conc = float((gco[gi] * mu / sc) / n_air * 1e9)
        denom = abs(gco[gi])
        perr_rel = float(perr[gi] / denom) if denom > 0 else float("inf")

    # shift가 경계에 박혔나 — 박히면 창/스텝이 부적합(하드 게이트 신호)
    shift_at_bound = False
    for name, val in zip(list(eng.gas_list), opt_sh):
        props = ref_props.get(name, {})
        if props.get("sh_mode") != "Limit":
            continue
        try:
            g_lb, g_ub = map(float, props["sh_val"].split(","))
        except Exception:
            g_lb, g_ub = -3.0, 3.0
        w_lb, w_ub = -step_limit, step_limit
        b_lo, b_hi = max(g_lb, w_lb), min(g_ub, w_ub)
        span = (b_hi - b_lo) or 1.0
        if (val - b_lo) < 0.02 * span or (b_hi - val) < 0.02 * span:
            shift_at_bound = True

    return dict(conc=conc, perr_rel=perr_rel, rms=rms, sig=sig,
                rms_sig=float(rms / (sig + 1e-30)), autocorr1=autocorr1,
                shift_at_bound=shift_at_bound, n_pix=int(len(a)))


# ──────────────────────────────────────────────────────────────────────────
def _median(xs):
    xs = [x for x in xs if x is not None and np.isfinite(x)]
    return float(np.median(xs)) if xs else float("nan")


def aggregate_cell(scans, eng, fitter, ref_props, px_min, px_max, poly_deg,
                   step_limit=0.5, target="NO2"):
    """여러 스캔을 한 (창, 차수)로 핏 → 집계 지표 1행.

    scans: [(wave, alpha, T_C, P_mbar), ...]  (이미 로드된 알파 샘플)
    반환 dict: median 지표 + n_ok/n_fail(오제거율 추적) + skip 사유."""
    per = []
    fails = []
    for i, (wave, alpha, T_C, P_mbar) in enumerate(scans):
        try:
            per.append(fit_window(eng, fitter, ref_props, wave, alpha, T_C, P_mbar,
                                  px_min, px_max, poly_deg, step_limit, target))
        except Exception as e:            # noqa: BLE001 — 스캔 단위 격리
            fails.append((i, repr(e)))

    n_ok = len(per)
    row = dict(px_min=px_min, px_max=px_max, poly=poly_deg,
               n_ok=n_ok, n_fail=len(fails), fails=fails)
    if n_ok == 0:
        row.update(conc=float("nan"), perr_rel=float("nan"), rms_sig=float("nan"),
                   autocorr1=float("nan"), conc_cv=float("nan"),
                   at_bound_frac=1.0, width_px=px_max - px_min + 1)
        return row

    concs = [p["conc"] for p in per]
    row.update(
        conc=_median(concs),
        conc_cv=float(np.std([c for c in concs if np.isfinite(c)]) /
                      (abs(_median(concs)) + 1e-30)) if n_ok > 1 else 0.0,
        perr_rel=_median([p["perr_rel"] for p in per]),
        rms_sig=_median([p["rms_sig"] for p in per]),
        autocorr1=_median([p["autocorr1"] for p in per]),
        at_bound_frac=float(np.mean([p["shift_at_bound"] for p in per])),
        width_px=px_max - px_min + 1,
    )
    return row


# ──────────────────────────────────────────────────────────────────────────
def search_fit_range(scans, eng, fitter, ref_props, windows, polys,
                     step_limit=0.5, target="NO2", baseline=None):
    """Stage 1 그리드 탐색 → 스코어카드 랭킹.

    windows: [(px_min, px_max), ...]   polys: [int, ...]
    baseline: (px_min, px_max, poly) 현재 시나리오 값 → Δ%농도 기준(None이면 생략).

    2-pass: (1) 모든 (창×차수) 셀 집계 → (2) 이웃에서 안정성 가드 유도 후 점수화.
    점수는 낮을수록 좋음. **모든 컬럼을 그대로 담아 반환**(사람이 판단; 헌장=근거를 보여라)."""
    # ── pass 1: 그리드 집계 ────────────────────────────────────────────────
    grid = {}
    for (pmn, pmx) in windows:
        for p in polys:
            grid[(pmn, pmx, p)] = aggregate_cell(
                scans, eng, fitter, ref_props, pmn, pmx, p, step_limit, target)

    base_conc = None
    if baseline is not None and tuple(baseline) in grid:
        base_conc = grid[tuple(baseline)]["conc"]

    # ── 컨센서스 앵커: 창×차수 다수결의 "1x" 농도 ─────────────────────────
    # 퇴화(2x 뻥튀기·0x 붕괴)는 창 선택에 따라 계통적으로 생기지만, 진짜 농도는
    # 창·차수에 무관해야 한다. 대부분의 셀이 합의하는 값이 진짜에 가깝다는 가정.
    # 반복 median: (1) 전체 median으로 1x 밴드[0.5·,1.5·]를 잡고 (2) 그 안에서 다시
    # median → 뻥튀기 클러스터가 정상보다 많아도(ANs 25>22) 앵커가 1x에 고정된다.
    all_conc = [g["conc"] for g in grid.values() if np.isfinite(g.get("conc", np.nan))]
    consensus = float("nan")
    if all_conc:
        m0 = float(np.median(all_conc))
        band = [c for c in all_conc if 0.5 * abs(m0) <= abs(c) <= 1.5 * abs(m0)] or all_conc
        consensus = float(np.median(band))

    def _rel_spread(vals):
        vals = [v for v in vals if v is not None and np.isfinite(v)]
        if len(vals) < 2:
            return 0.0
        return float((max(vals) - min(vals)) / (abs(np.median(vals)) + 1e-30))

    # ── pass 2: 안정성 가드 + 점수 ────────────────────────────────────────
    win_sorted = sorted(set(windows))
    rows = []
    for (pmn, pmx, p) in grid:
        cell = grid[(pmn, pmx, p)]
        # 차수 안정성: 같은 창에서 **전체 poly** 농도 상대폭(p±1 이웃만 보면 POLYS=[3,4,6,8]
        # 간격상 poly6·8은 이웃이 그리드에 없어 항상 0으로 계산되는 반쪽 지표였음).
        poly_stab = _rel_spread([grid.get((pmn, pmx, q), {}).get("conc") for q in polys])
        # 창 안정성: 같은 차수에서 인접 창(정렬순 ±1) 농도 상대폭
        wi = win_sorted.index((pmn, pmx))
        neigh = [win_sorted[wi]]
        if wi > 0:
            neigh.append(win_sorted[wi - 1])
        if wi < len(win_sorted) - 1:
            neigh.append(win_sorted[wi + 1])
        win_stab = _rel_spread([grid.get((w[0], w[1], p), {}).get("conc")
                                for w in neigh])
        # 컨센서스 편차: 이 셀 농도가 1x 앵커에서 얼마나 벗어났나(뻥튀기/붕괴 탐지).
        # 국소 이웃차(win_stab)는 이웃이 퇴화면 같이 망가지므로, 전역 앵커가 더 견고.
        if np.isfinite(consensus) and abs(consensus) > 0 and np.isfinite(cell["conc"]):
            consensus_dev = abs(cell["conc"] - consensus) / abs(consensus)
        else:
            consensus_dev = float("nan")
        # perr-폭 편향 보정: perr_rel이 창폭에 따라 ~1/폭로 감소(잔차 자기상관 |ac1|~1로
        # perr가 독립가정하에 불확실도를 과소평가, 넓을수록 심함). √폭(=백색노이즈 통계 floor)로
        # 정규화해 '픽셀 수만으로 얻은 정밀도'를 제거 → 그 이상의 진짜 leverage만 순위에 반영.
        pw = cell.get("perr_rel", float("nan"))
        cell["perr_wn"] = float(pw * np.sqrt(cell["width_px"])) if np.isfinite(pw) else float("nan")
        cell = dict(cell, poly_stab=poly_stab, win_stab=win_stab,
                    consensus=consensus, consensus_dev=consensus_dev)
        if base_conc is not None and np.isfinite(cell["conc"]) and abs(base_conc) > 0:
            cell["d_conc_pct"] = float((cell["conc"] - base_conc) / abs(base_conc) * 100)
        else:
            cell["d_conc_pct"] = float("nan")
        rows.append(cell)

    # ── 점수(낮을수록 좋음). 하드 게이트는 gated=True로 표시하고 뒤로 보냄 ──
    def _z(key, invert=False):
        vals = np.array([r[key] for r in rows], float)
        good = np.isfinite(vals)
        if good.sum() < 2:
            return {id(r): 0.0 for r in rows}
        mu, sd = np.nanmedian(vals[good]), np.nanstd(vals[good]) or 1.0
        return {id(r): float((r[key] - mu) / sd) * (-1 if invert else 1)
                if np.isfinite(r[key]) else np.inf for r in rows}

    z_perr = _z("perr_wn")        # 1순위 축(폭 정규화된 perr — 폭 편향 제거)
    z_ac = _z("autocorr1")        # |ac|이지만 부호 무시 위해 아래서 abs
    z_ps = _z("poly_stab")
    z_rs = _z("rms_sig")
    # 컨센서스에서 이만큼 벗어나면 퇴화로 보고 하드 게이트(2x·0x 제거). 진짜 농도를
    # 창 선택으로 50% 넘게 바꾸는 세팅은 '최적화'가 아니라 degeneracy — 헌장 ④(물리>통계).
    OFF_CONSENSUS = 0.5

    # poly-나이프엣지 게이트: 한 창의 poly 형제 다수가 off_consensus면, 우연히 컨센서스에
    # 착지한 나머지 poly도 신뢰 불가(어느 poly가 '진짜'인지 외부정보 없이 못 정함) → 창째 게이트.
    # 예: PNs 675-1120은 poly3/6/8이 194ppb(2x)인데 poly4만 90.5 → poly4도 나이프엣지라 배제.
    win_polys = {}
    for r in rows:
        win_polys.setdefault((r["px_min"], r["px_max"]), []).append(r)
    poly_degenerate = set()
    for win, cells in win_polys.items():
        offc = [c for c in cells
                if np.isfinite(c.get("consensus_dev", np.nan)) and c["consensus_dev"] > OFF_CONSENSUS]
        if len(cells) >= 2 and len(offc) >= len(cells) / 2:
            poly_degenerate.add(win)

    for r in rows:
        off_cons = (np.isfinite(r.get("consensus_dev", np.nan))
                    and r["consensus_dev"] > OFF_CONSENSUS)
        poly_deg = (r["px_min"], r["px_max"]) in poly_degenerate and not off_cons
        gated = (r["n_ok"] == 0) or (r["at_bound_frac"] > 0.25) or \
                not np.isfinite(r["perr_rel"]) or off_cons or poly_deg
        r["gated"] = bool(gated)
        r["gate_reason"] = ("no_fit" if r["n_ok"] == 0 else
                            "shift_at_bound" if r["at_bound_frac"] > 0.25 else
                            "perr_nan" if not np.isfinite(r["perr_rel"]) else
                            "off_consensus" if off_cons else
                            "poly_knife_edge" if poly_deg else "")
        # 가중합(낮을수록 좋음): perr(1순위) 2.0, 컨센서스편차(전역 앵커) 3.0,
        # 차수안정 0.7, 잔차구조 0.5, 절약 0.3. win_stab는 표시용으로만 남기고 점수 제외.
        cdev = r["consensus_dev"] if np.isfinite(r.get("consensus_dev", np.nan)) else 1.0
        score = (2.0 * z_perr[id(r)] + 3.0 * cdev
                 + 0.7 * z_ps[id(r)]
                 + 0.5 * abs(z_ac[id(r)]) + 0.3 * z_rs[id(r)]
                 + 0.3 * (r["poly"] / 4.0) + 0.1 * (r["width_px"] / 500.0))
        r["score"] = float(score if not gated else score + 1e6)

    rows.sort(key=lambda r: r["score"])
    return rows
