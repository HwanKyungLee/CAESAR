#!/usr/bin/env python
"""T1 — I₀(zero air)·T·P 시간보간 오차를 leave-one-out 으로 **측정**하고
기체 농도 편향까지 전파한다.  (읽기 전용 진단 — core/·gui/ 는 건드리지 않는다)

왜
--
`gui/worker.py:2656-2658` 이 I₀ 와 그 시점의 T·P 를 `_SegPchip_i0` 로 **시간 PCHIP
보간**한다. R(t) 보간 오차와 완전히 같은 실패 모드인데 한 번도 측정된 적이 없다.
α ∝ (I₀−I)/I 라 I₀ 의 상대오차 ε 는

    Δα/α = ε · I₀/(I₀−I)

로 증폭돼 들어간다. 증폭배수는 **추정하지 않고 실제 스펙트럼에서 잰다**(지시서 T1-3).

무엇을 재는가
------------
1. worker Pass 1 과 **같은 방식**으로 ZA knot 을 만든다
   (flag 수집 → gap=10 블록평균 → `_correct_intensity_plain` → `resolve_time_axis`
    → `detect_step_candidates` 분절 → `SegmentedPchip`).
2. 중간 knot 을 하나씩 빼고 남은 knot 으로 그 시각을 예측 → ε(λ).
3. 그 시각 근처 ambient 60 s 빈에서 q(λ) = (I₀−I)/I 를 **실측**한다.
4. α 를 production 과 같은 식으로 조립해 ε 없는 것/있는 것 두 벌을 핏하고
   기체별 상대편향을 낸다. ε 은 스케일 성분(파장평균)과 모양 성분으로 **분리**해서도
   따로 넣는다 — R(t) 에서 스케일 성분은 모든 핏 진단에 안 보였다.
5. T·P 보간 오차는 Rayleigh 항에 직접 들어가므로 별도 case 로 낸다.

분모 규약
--------
`reported` 열은 실측 잡음 조건의 **단일 스캔 보고 1σ = 0.55 %** 하나로 통일한다
(지시서 §0). 기존 문서의 24배/13배/47배는 항마다 분모가 달라 인용하지 않는다.

재현
----
    python diagnostics/i0_interp_2026-09/measure_i0_loo.py \
        --raw "E:/Yeosu_2026/CAESAR_Hot/2026-05/2026-05-18-*.dat" \
        --channel 2 --label hot_PNs --rt "C:/Doasis_Work/Output/R/R_CH2.npz" \
        --fitset "C:/Doasis_Work/Output/fit setting/FitSet_ANs[430-466nm_P4]_PNs[444-471nm_P3]_cold[438-466nm_P4]_Std.json.bak_20260722_labelswap" \
        --ch-key 2

캐시(`--cache`)에 raw 파싱 결과가 남으므로 2회차부터는 즉시 끝난다.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

try:                       # cp949 콘솔에서 '₀'·'√' 같은 글자가 print 를 죽인다
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_TOOLS = os.path.join(_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from core.data_io import DataIO, extract_raw_file_for_parallel
from core.parallel import max_workers
from core.physics import RayleighPhysics
from core.raw_parser import CH_PIXELS, FLAG_HEADER
from core.step_guard import (SegmentedPchip, detect_step_candidates,
                             resolve_time_axis)
from gui.worker import (_alpha_za_plain, _avg_ambient_plain,
                        _correct_intensity_plain)

FLAG_ZA_SET = {500}
FLAG_HE_SET = {510}
REPORTED_1SIG = 0.0055      # 단일 스캔 보고 1σ (지시서 §0 — 유일한 분모)

CSV_COLS = ["case", "eps_mean", "eps_shape_rms", "no2_rel", "chocho_rel",
            "h2o_rel", "dshift", "reported"]


# ── Pass 1 재현 ──────────────────────────────────────────────────────────────
def _time_blocks(gidx_list, sec_list, gap=10):
    """스펙트럼 없이 블록 경계만 — (블록 평균시각, 스캔수, span[s]).

    분할 규칙은 `_block_average` 와 같은 gidx 간격 gap 이다. He 는 §6.2 듀티사이클
    (ZA+He 합산)에만 쓰이므로 스펙트럼을 들고 있을 이유가 없다.
    """
    if not gidx_list:
        return [], [], []
    g = np.asarray(gidx_list, float)
    o = np.argsort(g)
    g, sec = g[o], np.asarray(sec_list, float)[o]
    splits = np.where(np.diff(g) > gap)[0] + 1
    bs = np.split(sec, splits)
    return ([float(np.nanmean(b)) for b in bs],
            [float(len(b)) for b in bs],
            [float(np.nanmax(b) - np.nanmin(b)) if len(b) > 1 else 0.0 for b in bs])


def _block_average(gidx_list, sec_list, spec_list, t_list, p_list, gap=10):
    """gui/worker.py `_run_inner._block_average` 와 동일(그쪽은 클로저라 임포트 불가).
    한 글자도 바꾸지 않는다 — 바꾸면 이 진단이 production knot 을 안 재는 게 된다."""
    if not gidx_list:
        return [], [], [], [], [], [], [], [], [], [[], [], [], []], []
    g = np.array(gidx_list, dtype=float)
    order = np.argsort(g)
    g = g[order]
    SEC = np.array(sec_list, dtype=float)[order]
    S = np.array(spec_list, dtype=float)[order]
    T = np.array(t_list, dtype=float)[order]
    P = np.array(p_list, dtype=float)[order]
    splits = np.where(np.diff(g) > gap)[0] + 1
    bg = [float(np.mean(b)) for b in np.split(g, splits)]
    bsec = [float(np.nanmean(b)) for b in np.split(SEC, splits)]
    bs = [np.nanmean(b, axis=0) for b in np.split(S, splits)]
    bt = [float(np.nanmean(b)) for b in np.split(T, splits)]
    bp = [float(np.nanmean(b)) for b in np.split(P, splits)]
    # 블록평균 I₀ 자체의 **광자잡음** — ε 의 바닥이 여기다. 보간 탓인지 측정 탓인지
    # 가르려면 이게 있어야 한다(없으면 "ZA 를 더 자주"라는 틀린 처방이 나온다).
    # 짝/홀 **반블록 평균** — knot 자체 잡음을 간격 외삽 없이 직접 재기 위한 것.
    # 앞반/뒤반이 아니라 짝/홀로 가르는 이유: 블록 내 드리프트가 있어도 두 반쪽이
    # 같은 시간분포를 가져 드리프트가 상쇄된다(35스캔 ≈ 35 s 라 작지만 공짜로 없앤다).
    bha = [np.nanmean(b[0::2], axis=0) for b in np.split(S, splits)]
    bhb = [np.nanmean(b[1::2], axis=0) for b in np.split(S, splits)]
    # **연속** 4분할 — 짝/홀은 드리프트가 두 쪽에 똑같이 들어가 차분에서 상쇄되므로
    # 드리프트를 보려면 시간순으로 잘라야 한다. 둘을 같이 저장해 대조하면
    # 잡음(짝/홀)과 잡음+드리프트(연속)가 분리된다.
    def _q(b, i):
        n = len(b) // 4
        return np.nanmean(b[i * n:(i + 1) * n], axis=0) if n >= 1 else np.full(S.shape[1], np.nan)
    bq = [[_q(b, i) for b in np.split(S, splits)] for i in range(4)]
    bspan = [float(np.ptp(t)) for t in np.split(SEC, splits)]   # 블록 시간폭 T (s)
    bnz = []
    for b in np.split(S, splits):
        m = np.nanmean(b, axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.where(m > 0, b / m, np.nan)
        bnz.append(np.nanstd(rel, axis=0, ddof=1) / np.sqrt(max(len(b), 1))
                   if len(b) > 1 else np.full(S.shape[1], np.nan))
    return (bg, bsec, bs, bt, bp, bnz, [len(b) for b in np.split(g, splits)],
            bha, bhb, bq, bspan)


def collect(files, channel, purge_settle_sec=60.0, avg_sec=60.0, parallel=True):
    """worker Pass 1 과 같은 분류·세틀링·블록평균으로 (ZA knot, ambient 60s bin) 수집."""
    za_g, za_sec, za_sp, za_t, za_p = [], [], [], [], []
    he_g, he_sec = [], []             # [TBD-A2] He 블록 듀티사이클용 — 스펙트럼은
                                      # 안 받는다(§6.2 는 N·span·주기만 쓴다)
    amb_bins = []                     # (fp, gmean, rep_sec, T, P, I, n)
    gidx = 0

    def _consume(fp, flags, Ts, Ps, specs, secs):
        """파일 하나분을 **받는 즉시** 처리하고 버린다.

        예전엔 전 파일 결과를 리스트에 모아 뒀다가 돌았는데, 한 파일이
        3702행 × 2048 px float32 ≈ 30 MB 라 157 파일이면 4.7 GB 다 — 실측으로
        `ex.map` 결과 언피클 중 MemoryError 로 죽었다(2026-09-20, hot ch1 7일치).
        `ex.map` 은 입력 순서를 보존하므로 스트리밍해도 gidx 배정이 같다(무회귀).
        """
        nonlocal gidx
        last_cal_sec = None
        entries = []
        for i in range(len(flags)):
            f = int(flags[i])
            g = gidx
            gidx += 1
            if f < 0:
                continue
            is_za, is_he = f in FLAG_ZA_SET, f in FLAG_HE_SET
            is_amb = (f == FLAG_HEADER or f == 1)
            if not is_amb:
                last_cal_sec = float(secs[i])
            if is_za:
                za_g.append(g); za_sec.append(float(secs[i]))
                za_sp.append(np.asarray(specs[i], dtype=float))
                za_t.append(float(Ts[i])); za_p.append(float(Ps[i]))
            elif is_he:
                he_g.append(g); he_sec.append(float(secs[i]))
            elif is_amb:
                if last_cal_sec is not None:
                    dt = float(secs[i]) - last_cal_sec
                    if np.isfinite(dt) and dt < purge_settle_sec:
                        continue
                entries.append((fp, i, g, float(secs[i]), float(Ts[i]),
                                float(Ps[i]), np.asarray(specs[i], dtype=float)))
        amb_bins.extend(_avg_ambient_plain(entries, avg_sec))

    if parallel and len(files) > 1:
        import concurrent.futures as cf
        with cf.ProcessPoolExecutor(max_workers=max_workers()) as ex:
            for out in ex.map(_extract_task, [(fp, channel) for fp in files]):
                _consume(*out)
                del out
    else:
        for fp in files:
            _consume(*extract_raw_file_for_parallel((fp, 0, CH_PIXELS, channel)))

    (za_g, za_sec, za_sp, za_t, za_p, za_nz, za_n,
     za_a, za_b, za_q, za_span) = _block_average(za_g, za_sec, za_sp, za_t, za_p)
    he_bsec, he_bn, he_bspan = _time_blocks(he_g, he_sec)
    _ci = lambda v: _correct_intensity_plain(v, None, 1.0, None, 1.0, 0.0)
    return dict(he_sec=np.asarray(he_bsec, float),
                he_nscan=np.asarray(he_bn, float),
                he_span_s=np.asarray(he_bspan, float),
                za_half_a=np.asarray([_ci(v) for v in za_a], dtype=float),
                za_half_b=np.asarray([_ci(v) for v in za_b], dtype=float),
                za_q0=np.asarray([_ci(v) for v in za_q[0]], dtype=float),
                za_q1=np.asarray([_ci(v) for v in za_q[1]], dtype=float),
                za_q2=np.asarray([_ci(v) for v in za_q[2]], dtype=float),
                za_q3=np.asarray([_ci(v) for v in za_q[3]], dtype=float),
                za_span_s=np.asarray(za_span, dtype=float),
                za_noise=np.asarray(za_nz, float),
                za_nscan=np.asarray(za_n, float),
                za_gidx=np.asarray(za_g, float), za_sec=np.asarray(za_sec, float),
                za_arr=np.asarray([_correct_intensity_plain(s, None, 1.0, None, 1.0, 0.0)
                                   for s in za_sp], dtype=float),
                za_t=np.asarray(za_t, float), za_p=np.asarray(za_p, float),
                amb_sec=np.asarray([b[2] for b in amb_bins], float),
                amb_g=np.asarray([b[1] for b in amb_bins], float),
                amb_T=np.asarray([b[3] for b in amb_bins], float),
                amb_P=np.asarray([b[4] for b in amb_bins], float),
                amb_I=np.asarray([_correct_intensity_plain(b[5], None, 1.0, None, 1.0, 0.0)
                                  for b in amb_bins], dtype=float))


def _extract_task(t):
    fp, channel = t
    return extract_raw_file_for_parallel((fp, 0, CH_PIXELS, channel))


# ── I₀ 보간기 (worker 2641-2652 과 동일 구성) ────────────────────────────────
def build_interpolators(d):
    za_x, is_sec = resolve_time_axis(d["za_gidx"], d["za_sec"])
    metric = np.nanmean(d["za_arr"], axis=1)
    cands, _thr = detect_step_candidates(za_x, metric)
    breaks = [c["x_break"] for c in cands]
    return za_x, is_sec, breaks


def loo_eps(za_x, za_arr, breaks, k, xq, leave=1):
    """knot k(부터 leave 개)를 빼고 남은 knot 으로 xq 를 예측 → ε(λ) = (pred − full)/full.

    분모는 **전체 knot 으로 보간한 값**이다. production 이 그 시각에 실제로 쓴 I₀ 가
    그것이고, 우리가 재는 건 "knot 이 없었다면 production 이 얼마나 틀렸겠나" 다.

    ⚠ leave=1 도 이미 **간격을 2배로 벌린다**(1 h 운용 → 2 h). 그래서 이 값은 운용
    간격의 오차가 아니라 그 **상한**이다. `--leave 2,3` 으로 간격-오차 곡선을 재서
    운용 간격으로 되돌려 읽는 것이 `--gap-scan` 이다.
    """
    keep = np.ones(len(za_x), dtype=bool)
    keep[k:k + leave] = False
    pred = SegmentedPchip(za_x[keep], za_arr[keep], break_x=breaks)(xq)
    full = SegmentedPchip(za_x, za_arr, break_x=breaks)(xq)
    if pred is None or full is None:
        return None
    full = np.asarray(full, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(full > 0, (np.asarray(pred, float) - full) / full, np.nan)


def loo_scalar(za_x, y, breaks, k, xq, leave=1):
    keep = np.ones(len(za_x), dtype=bool)
    keep[k:k + leave] = False
    v = SegmentedPchip(za_x[keep], y[keep], break_x=breaks)(xq)
    return None if v is None else float(v)


# ── 핏 하니스 ────────────────────────────────────────────────────────────────
class ScanFitter:
    """etalon 각주파수를 **고정**한 채 production 과 같은 경로로 한 스캔을 핏한다.

    구현은 T2 진단의 `Channel` 을 그대로 쓴다 — 그쪽이 `param_optimizer.fit_scan` 의
    `controlled_start=None` 경로를 한 글자도 안 바꾸고 따라 했고, 같은 입력에서
    `fit_scan` 과 **바이트 일치**함을 매 실행 자체검증한다(2026-09-20, 93/93).

    왜 f 를 고정하나 — 1차 실행(2026-09-20 오전)은 `fit_scan` 을 직접 불러 스캔마다
    f 가 재검출됐고, `full` 섭동 행의 **73~82 %** 에서 f 가 바뀌었다. 그 행의 농도차는
    I₀ 섭동 효과가 아니라 **모델이 바뀐 효과**라 편향이 부풀었다.

    step_limit 도 밖에서 키울 수 있게 뒀다. 1차 실행에서 hot PNs 는 11개 중 6개가
    섭동 후 shift 가 상자 끝(±0.5 px)에 붙었고, 그 농도차는 step_limit 이 만든 값이다.
    """

    def __init__(self, cfg, wave, target="NO2", e_f=None, step_limit=None,
                 sh_limit=None, sh_fix=None):
        sys.path.insert(0, os.path.join(_ROOT, "diagnostics", "etalon_freq_2026-09"))
        from etalon_freq import Channel
        cfg = dict(cfg)
        if step_limit is not None:
            cfg["step_limit"] = float(step_limit)
        if sh_limit is not None:
            # 전역 shift 한계도 넓힌다. hot ANs 는 base shift 가 −5.2 px 라 운영
            # 한계 ±5 에 이미 닿아 있어, 그 상태로 재면 "섭동이 못 움직인 만큼"이
            # 편향에서 빠진다. 넓혀서 재고, 운영이 경계에 붙어 있다는 사실은 T7 로 넘긴다.
            cfg["ref_props"] = {g: dict(v) for g, v in cfg["ref_props"].items()}
            cfg["ref_props"][target]["sh_val"] = sh_limit
        if sh_fix is not None:
            # cold 는 전역 한계가 ±1 px 이고 실측 base shift 가 정확히 −1.000 =
            # **이미 경계에 붙어 있다**(T6 의 비식별성). 그 상태로는 섭동 효과와
            # 경계 인공물이 안 갈린다. shift 를 아예 Fix 로 두면 경계가 없어져
            # I₀ 효과만 남는다 — 운영 cold 설정(Shift Fix)과도 가깝다.
            cfg["ref_props"] = {g: dict(v) for g, v in cfg["ref_props"].items()}
            cfg["ref_props"][target]["sh_mode"] = "Fix"
            cfg["ref_props"][target]["sh_val"] = str(sh_fix)
        self.cfg, self.target, self.e_f = cfg, target, e_f
        self.ch = Channel(cfg, target=target)
        self.wave = self.ch.wave
        self.px_min, self.px_max = self.ch.px_min, self.ch.px_max

    @property
    def gas_list(self):
        return list(self.ch.eng.gas_list)

    def seed(self, alpha, T_C, P_mbar):
        """격자 시딩 + 그 스캔의 자동 검출 f. 상자는 이 시드에 앵커된다."""
        sh, sq, ef_auto, _conc = self.ch.seed(alpha, T_C, P_mbar)
        return sh, sq, ef_auto

    def fit(self, alpha, T_C, P_mbar, start, e_f=None):
        r = self.ch.fit(alpha, T_C, P_mbar,
                        self.e_f if e_f is None else e_f, start)
        return r


def _split_half(args, d, wave, inwin, za_x, breaks, is_sec, alpha_at, fitter, gkeys):
    """knot 자체 잡음이 농도에 주는 효과 — **간격 외삽 없이** 직접 잰다.

    각 ZA 블록을 짝/홀로 갈라 두 반쪽으로 각각 I₀(t) 를 만들고, 같은 ambient 빈을
    두 번 핏해 NO₂ 차를 본다. 보간 간격이 개입하지 않으므로 LOO 의 ×0.5~0.7 외삽이
    필요 없다.

    스케일: 반블록은 스캔이 절반이라 잡음이 √2 크고, 두 반쪽의 **차**는 다시 √2 크다
    → 관측 차이는 전블록 knot 잡음 효과의 **2배**다. 그래서 2로 나눈다.
    두 보간항이 잡음 제한(멱지수 0.2)이라는 것이 이미 확인됐으므로, 이 값이 사실상
    운용 간격에서의 오차다.
    """
    kNO2, kCHO, kH2O = gkeys
    if "za_half_a" not in d:
        raise SystemExit("ABSTAIN: 캐시에 반블록이 없다 — --refresh 로 다시 만들 것")
    amb = d["amb_sec"] if is_sec else d["amb_g"]
    pa = SegmentedPchip(za_x, d["za_half_a"], break_x=breaks)
    pb = SegmentedPchip(za_x, d["za_half_b"], break_x=breaks)
    rows, rel = [], []
    for k in range(1, len(za_x) - 1):
        j = int(np.argmin(np.abs(amb - za_x[k])))
        xq = float(amb[j])
        ia, ib = np.asarray(pa(xq), float), np.asarray(pb(xq), float)
        if ia is None or ib is None or not np.isfinite(ia).all() or not np.isfinite(ib).all():
            continue
        T, P = float(d["amb_T"][j]), float(d["amb_P"][j])
        a_a = alpha_at(j, i0=ia)[0]
        sh0, sq0, ef_auto = fitter.seed(a_a, T, P)
        ef = fitter.e_f if fitter.e_f is not None else ef_auto
        fa = fitter.fit(a_a, T, P, (sh0, sq0), ef)
        fb = fitter.fit(alpha_at(j, i0=ib)[0], T, P, (sh0, sq0), ef)
        if fa["_at_bound"] or fb["_at_bound"]:
            continue
        r = _rel_of(fa, fb, kNO2)
        if np.isfinite(r):
            rel.append(r)
            rows.append(dict(k=k, sec=float(d["amb_sec"][j]), rel_halfdiff=r))
    if len(rel) < 5:
        raise SystemExit("ABSTAIN: split-half 케이스가 모자란다")
    v = np.asarray(rel, float)
    rsd_diff = float(1.4826 * np.median(np.abs(v - np.median(v))))
    rsd = rsd_diff / 2.0          # 위 docstring 의 2배 규칙
    ppb = rsd * float(args.channel_no2_ppb)
    print(f"[split] n={len(v)}  반쪽차 robust SD {rsd_diff * 100:.3f} %  "
          f"→ **knot 잡음 기여 {rsd * 100:.3f} %** = {ppb:.4f} ppb ({rsd / REPORTED_1SIG:.1f}×1σ)")
    if args.ceiling_ppb:
        print(f"[split] 게이트 {args.ceiling_ppb:.4f} 대비 {ppb / args.ceiling_ppb:.2f}배 "
              + ("PASS" if ppb <= args.ceiling_ppb else "**FAIL**"))
    print("[split] 이 값에는 **간격 외삽이 없다** — LOO 상한의 ×0.5~0.7 을 대체한다")
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   f"split_half_{args.label}.csv")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("k,sec,rel_halfdiff\n")
        for r in rows:
            fh.write(f"{r['k']},{r['sec']:.6g},{r['rel_halfdiff']:.6g}\n")
    print(f"→ {out}  ({len(rows)} rows)")
    return out


def _joint_loo(args, d, wave, inwin, rt, za_x, breaks, is_sec,
               pchip_i0, alpha_at, fitter, gkeys):
    """I₀ 와 R(t) 를 **한 번에** 뺀다 — 둘은 독립이 아니다.

    같은 ZA 블록이 두 경로로 들어간다:
      * I₀ = I_ZA            → α = (omr + RL·α_ray)·(I₀−I)/I
      * omr_d = RL·(r·α_ZA − α_He)/(1−r),  r = I_ZA/I_He   (`tools/reflectance_calc.py:115`)
    α_ZA ≫ α_He(σ비 68.9)라 ∂omr/∂r > 0 이고, I₀ 경로도 같은 부호다. **같은 방향으로
    움직이므로 제곱합은 과소계상**이다.

    그래서 같은 시각의 ZA knot 과 R knot 을 **동시에** 빼고 α 를 한 번 조립해 잰다.
    비교용으로 각각만 뺀 경우도 같은 시드로 돌려 제곱합과 직접 대조한다.
    """
    kNO2, kCHO, kH2O = gkeys
    amb = d["amb_sec"] if is_sec else d["amb_g"]
    rks = np.asarray(rt["knot_sec"], float); rod = np.asarray(rt["omr_d"], float)
    o = np.argsort(rks); rks, rod = rks[o], rod[o]
    rwave = np.asarray(rt["wave_nm"], float)
    rbrk = list(np.asarray(rt.get("manual_breaks_sec", []), float))

    def _omr(sec, keep=None):
        x = rks if keep is None else rks[keep]
        y = rod if keep is None else rod[keep]
        v = np.asarray(SegmentedPchip(x, y, break_x=rbrk)(float(sec)), float)
        return v if v.shape == wave.shape else np.interp(wave, rwave[:v.shape[0]], v)

    rows, det = [], []
    for k in range(1, len(za_x) - 1):
        j = int(np.argmin(np.abs(amb - za_x[k])))
        xq = float(amb[j])
        sec = float(d["amb_sec"][j])
        # 같은 시각의 R knot (없으면 건너뛴다)
        kr = int(np.argmin(np.abs(rks - d["za_sec"][k])))
        if not (0 < kr < len(rks) - 1) or abs(rks[kr] - d["za_sec"][k]) > 3600:
            continue
        keep = np.ones(len(rks), dtype=bool); keep[kr] = False
        i0_full = np.asarray(pchip_i0(xq), float)
        kz = np.ones(len(za_x), dtype=bool); kz[k] = False
        i0_loo = SegmentedPchip(za_x[kz], d["za_arr"][kz], break_x=breaks)(xq)
        if i0_loo is None:
            continue
        i0_loo = np.asarray(i0_loo, float)
        omr_full, omr_loo = _omr(sec), _omr(sec, keep)
        T, P = float(d["amb_T"][j]), float(d["amb_P"][j])

        a_base = alpha_at(j, i0=i0_full, omr_in=omr_full)[0]
        sh0, sq0, ef_auto = fitter.seed(a_base, T, P)
        ef = fitter.e_f if fitter.e_f is not None else ef_auto
        base = fitter.fit(a_base, T, P, (sh0, sq0), ef)
        out = {}
        for tag, i0v, omv in (("i0", i0_loo, omr_full), ("rt", i0_full, omr_loo),
                              ("joint", i0_loo, omr_loo)):
            ap = alpha_at(j, i0=i0v, omr_in=omv)[0]
            f = fitter.fit(ap, T, P, (sh0, sq0), ef)
            out[tag] = _rel_of(base, f, kNO2)
            if tag == "joint":
                rows.append(_row(f"joint_loo_k{k:03d}", 0.0, 0.0, base, f, kNO2, kCHO, kH2O))
        if not all(np.isfinite(v) for v in out.values()):
            continue
        det.append(dict(k=k, sec=sec, i0=out["i0"], rt=out["rt"], joint=out["joint"],
                        quad=float(np.hypot(out["i0"], out["rt"])),
                        at_bound=int(base["_at_bound"])))
    if len(det) < 5:
        raise SystemExit("ABSTAIN: joint 케이스가 모자란다")

    g = [r for r in det if not r["at_bound"]]
    def rsd(key):
        v = np.array([r[key] for r in g], float)
        return float(1.4826 * np.median(np.abs(v - np.median(v))))
    a_i0, a_rt, a_j = rsd("i0"), rsd("rt"), rsd("joint")
    quad = float(np.hypot(a_i0, a_rt))
    v_i0 = np.array([r["i0"] for r in g]); v_rt = np.array([r["rt"] for r in g])
    corr = float(np.corrcoef(v_i0, v_rt)[0, 1]) if len(g) > 3 else float("nan")
    print(f"[joint] n={len(g)} (상자고착 {len(det) - len(g)} 제외)")
    print(f"[joint] I0 단독 {a_i0 * 100:.3f} %  ·  R(t) 단독 {a_rt * 100:.3f} %  "
          f"·  두 항 상관 r={corr:+.3f}")
    print(f"[joint] **동시 {a_j * 100:.3f} %**  vs  제곱합 {quad * 100:.3f} %  "
          f"→ 제곱합이 {a_j / quad:.2f}배 {'과소' if a_j > quad else '과대'}계상")
    ppb = a_j * float(args.channel_no2_ppb)
    print(f"[joint] 채널 기여 {ppb:.4f} ppb" + (
        f"  · 게이트 {args.ceiling_ppb:.4f} 대비 {ppb / args.ceiling_ppb:.2f}배 "
        + ("PASS" if ppb <= args.ceiling_ppb else "**FAIL**") if args.ceiling_ppb else ""))

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   f"joint_loo_{args.label}.csv")
    keys = list(det[0])
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(",".join(keys) + "\n")
        for r in det:
            fh.write(",".join(f"{r[x]:.6g}" if isinstance(r[x], float) else str(r[x])
                              for x in keys) + "\n")
    print(f"→ {out}  ({len(det)} rows)  [열: i0, rt, joint, quad = NO2 상대편향]")
    return out


def _rel_of(base, pert, g):
    if g is None or g not in base:
        return float("nan")
    b = base[g]
    return float("nan") if not np.isfinite(b) or abs(b) < 1e-30 else float((pert[g] - b) / b)


def _gap_curve_report(per_gap, label, args):
    """간격-응답 곡선을 **두 지수로** 보고한다.

    전 구간 로그-로그 회귀값과 **끝점(첫↔마지막) 함축값**을 같이 낸다. 곡선이 깨끗한
    멱법칙이 아니면 둘이 갈리는데(2026-09-21 실측: R(t) PNs 회귀 0.20 vs 끝점 0.127),
    하나만 적으면 본문과 표가 어긋난다. 갈리면 **곡선이 멱법칙이 아니라는 사실**이
    결과이지, 둘 중 하나를 고를 문제가 아니다.
    """
    pts = []
    print("  유효간격   n      NO2 robust SD        ppb")
    for g in sorted(per_gap):
        v = np.asarray(per_gap[g], float)
        if v.size < 5:
            continue
        r = float(1.4826 * np.median(np.abs(v - np.median(v))))
        print(f"  {g:5d} h {v.size:5d}      {r:.5f}        {r * float(args.channel_no2_ppb):.4f}")
        pts.append((float(g), r))
    if len(pts) < 2:
        return None
    x = np.log([p[0] for p in pts]); y = np.log([p[1] for p in pts])
    fit = float(np.polyfit(x, y, 1)[0])
    end = float((y[-1] - y[0]) / (x[-1] - x[0]))
    print(f"  [{label}] 멱지수 — 전구간 회귀 **{fit:+.3f}** · 끝점({pts[0][0]:.0f}→"
          f"{pts[-1][0]:.0f} h) **{end:+.3f}**"
          + ("   ⚠ 둘이 갈린다 = 멱법칙이 아니다" if abs(fit - end) > 0.05 else "   (일치)"))
    return fit, end


def _i0_gap_fit(args, d, wave, inwin, za_x, breaks, is_sec, alpha_at, fitter, gkeys):
    """I₀ LOO 를 **NO₂ 응답 공간**에서 간격별로 잰다.

    `--gap-scan` 은 ε(I₀ 상대오차) 공간이라 R(t) 쪽(NO₂ 응답 공간)과 **양이 다르다**.
    두 지수를 한 표에 나란히 놓으려면 같은 양이어야 한다 — 그래서 여기서는 핏을 돌린다.
    """
    kNO2, kCHO, kH2O = gkeys
    ax = d["amb_sec"] if is_sec else d["amb_g"]
    h = float(np.median(np.diff(za_x))) / (3600.0 if is_sec else 1.0)
    per_gap, n_bad = {}, 0
    for leave in range(1, int(args.rt_leave_max) + 1):
        for k in range(1, len(za_x) - leave):
            mid = (za_x[k - 1] + za_x[min(k + leave, len(za_x) - 1)]) / 2.0
            j = int(np.argmin(np.abs(ax - mid)))
            if abs(ax[j] - mid) > (1800 if is_sec else 30):
                continue
            gap_h = float(za_x[k + leave] - za_x[k - 1]) / (3600.0 if is_sec else 1.0)
            keep = np.ones(len(za_x), dtype=bool)
            keep[k:k + leave] = False
            i0l = SegmentedPchip(za_x[keep], d["za_arr"][keep], break_x=breaks)(float(ax[j]))
            if i0l is None:
                continue
            a0 = alpha_at(j)[0]
            ap = alpha_at(j, i0=np.asarray(i0l, float))[0]
            T, P = float(d["amb_T"][j]), float(d["amb_P"][j])
            sh0, sq0, efa = fitter.seed(a0, T, P)
            ef = fitter.e_f if fitter.e_f is not None else efa
            b = fitter.fit(a0, T, P, (sh0, sq0), ef)
            p = fitter.fit(ap, T, P, (sh0, sq0), ef)
            if b["_at_bound"] or p["_at_bound"]:
                n_bad += 1
                continue
            r = _rel_of(b, p, kNO2)
            if np.isfinite(r):
                per_gap.setdefault(int(round(gap_h)), []).append(r)
    if not per_gap:
        raise SystemExit("ABSTAIN: I₀ 간격 케이스가 없다")
    print(f"[i0-gap] 운용 knot 간격 h={h:.2f} h · 상자고착 {n_bad}개 제외 · "
          f"**NO₂ 응답 공간**(R(t) 표와 같은 양)")
    _gap_curve_report(per_gap, "I0", args)
    return None


def _rt_loo(args, d, wave, inwin, rt, rt_ks, rt_od, rl, za_ref,
            pchip_t, pchip_p, alpha_at, fitter, gkeys):
    """T-R — 운영 R(t) 파일로 knot leave-N-out. I₀ LOO 와 **같은 기계**다.

    α = (omr(t) + RL·α_ray) · q − Δα_ray 이므로 omr 오차는 q 를 통해 곱셈으로 들어간다.
    R knot 을 빼고 남은 knot 으로 같은 시각을 예측해 그 차이를 α 에 실어 재핏한다.

    **스칼라 하나로 내지 않는다.** 운영 간격은 99 %가 1 h 인데 꼬리에 5~12 h 가 있다
    (R_cold 는 >2 h 가 4.2 %). leave=N 이 유효간격 (N+1)·h 를 만들므로, 그 곡선이 곧
    "간격별 불확도" 다 — 캠페인 평균 하나는 꼬리를 숨긴다.
    """
    kNO2, kCHO, kH2O = gkeys
    amb_sec = d["amb_sec"]
    lo, hi = float(np.nanmin(amb_sec)), float(np.nanmax(amb_sec))
    rt_breaks = list(np.asarray(rt.get("manual_breaks_sec", []), float))
    order = np.argsort(rt_ks)
    ks, od = rt_ks[order], rt_od[order]
    rwave = np.asarray(rt["wave_nm"], float)

    def _omr_at(sec, keep=None):
        y = od if keep is None else od[keep]
        x = ks if keep is None else ks[keep]
        v = np.asarray(SegmentedPchip(x, y, break_x=rt_breaks)(float(sec)), float)
        return v if v.shape == wave.shape else np.interp(wave, rwave[:v.shape[0]], v)

    rows, detail, n_at_bound = [], [], 0
    per_gap = {}
    for leave in range(1, int(args.rt_leave_max) + 1):
        for k in range(1, len(ks) - leave):
            mid = (ks[k - 1] + ks[k + leave]) / 2.0
            if not (lo <= mid <= hi):
                continue
            gap_h = float(ks[k + leave] - ks[k - 1]) / 3600.0
            j = int(np.argmin(np.abs(amb_sec - mid)))
            if abs(amb_sec[j] - mid) > 1800:          # 30분 넘게 떨어지면 그 구간은 자료가 없다
                continue
            keep = np.ones(len(ks), dtype=bool)
            keep[k:k + leave] = False
            alpha0, q, omr_full, a_ref, a_samp, _I, _I0 = alpha_at(j)
            omr_loo = _omr_at(amb_sec[j], keep)
            alpha_p = (omr_loo + rl * a_ref) * np.nan_to_num(q) - (a_samp - a_ref)
            t_am, p_am = float(d["amb_T"][j]), float(d["amb_P"][j])
            sh0, sq0, ef_auto = fitter.seed(alpha0, t_am, p_am)
            ef = fitter.e_f if fitter.e_f is not None else ef_auto
            base = fitter.fit(alpha0, t_am, p_am, (sh0, sq0), ef)
            pert = fitter.fit(alpha_p, t_am, p_am, (sh0, sq0), ef)
            bad = bool(base["_at_bound"] or pert["_at_bound"])
            n_at_bound += int(bad)
            d_omr = float(np.nanmedian(np.abs((omr_loo - omr_full)[inwin]
                                              / np.where(omr_full[inwin] != 0, omr_full[inwin], np.nan))))
            r = _row(f"rt_loo_L{leave}_k{k:05d}", d_omr, gap_h, base, pert, kNO2, kCHO, kH2O)
            r["at_bound"] = bad
            rows.append(r)
            if not bad and np.isfinite(r["no2_rel"]):
                per_gap.setdefault(round(gap_h), []).append(r["no2_rel"])
            detail.append(dict(case=r["case"], sec=float(amb_sec[j]), gap_h=gap_h,
                               d_omr_rel=d_omr, e_f=ef, at_bound=int(bad),
                               no2_base=base.get(kNO2, np.nan), no2_pert=pert.get(kNO2, np.nan)))
    if not rows:
        raise SystemExit("ABSTAIN: 캐시의 ambient 구간 안에 쓸 수 있는 R knot 이 없다")

    print(f"[rt] R knot {len(ks)}개 중 이 구간({_hh(lo)}~{_hh(hi)}) 안에서 "
          f"{len(rows)}개 케이스, 상자 고착 {n_at_bound}개 제외 · **NO₂ 응답 공간**")
    _gap_curve_report(per_gap, "R(t)", args)

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   f"rt_loo_{args.label}.csv")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(",".join(CSV_COLS) + "\n")
        for r in rows:
            fh.write(",".join(f"{r[c]:.6g}" if isinstance(r[c], float) else str(r[c])
                              for c in CSV_COLS) + "\n")
    det = out.replace(".csv", "_detail.csv")
    keys = list(detail[0])
    with open(det, "w", encoding="utf-8") as fh:
        fh.write(",".join(keys) + "\n")
        for r in detail:
            fh.write(",".join(f"{r[k]:.6g}" if isinstance(r[k], float) else str(r[k])
                              for k in keys) + "\n")
    print(f"→ {out}  ({len(rows)} rows)   [eps_mean=Δomr/omr, eps_shape_rms=유효간격 h]")
    print(f"→ {det}")
    return out


def _hh(sec):
    from datetime import datetime, timedelta
    return (datetime(2026, 1, 1) + timedelta(seconds=float(sec))).strftime("%m-%d %H:%M")


def _validate_alpha(args, d, wave, inwin, alpha_at):
    """**수용 게이트** — 이 진단이 조립한 α 가 production α 와 같은가.

    같은 60 s 빈을 `doy` 로 짝지어 핏창 안에서 회귀 기울기·상관을 낸다. 여기서
    어긋나면 아래 LOO 편향은 우리 조립식의 오차지 I₀ 보간의 오차가 아니다.
    """
    from za_gas_sigma import read_alpha_trace
    paths = sorted(glob.glob(os.path.join(args.validate_alpha, "*alpha_trace.dat")))
    if not paths:
        raise SystemExit(f"ABSTAIN: {args.validate_alpha} 에 *alpha_trace.dat 이 없다")
    prod_doy, prod_a = [], []
    for p in paths:
        w, ri, A, T, P = read_alpha_trace(p)
        doys = _trace_doys(p)
        if len(doys) != len(A):
            continue
        prod_doy.extend(doys); prod_a.extend(A)
    if not prod_doy:
        raise SystemExit("ABSTAIN: production 알파에서 doy 를 못 읽었다")
    prod_doy = np.asarray(prod_doy, float)
    ours, theirs = [], []
    for j in range(len(d["amb_sec"])):
        doy = float(d["amb_sec"][j]) / 86400.0 + 1.0
        i = int(np.argmin(np.abs(prod_doy - doy)))
        if abs(prod_doy[i] - doy) * 86400.0 > args.avg_sec:       # 같은 빈이 아니면 버린다
            continue
        a_ours = alpha_at(j)[0]
        ours.append(a_ours[inwin]); theirs.append(np.asarray(prod_a[i], float)[inwin])
    if not ours:
        raise SystemExit("ABSTAIN: production 알파와 시각으로 짝지어진 빈이 없다")
    x = np.concatenate(theirs); y = np.concatenate(ours)
    m = np.isfinite(x) & np.isfinite(y)
    slope = float(np.dot(x[m], y[m]) / np.dot(x[m], x[m]))
    corr = float(np.corrcoef(x[m], y[m])[0, 1])
    print(f"[validate] 짝지은 빈 {len(ours)}개 · 픽셀 {int(m.sum())}개  "
          f"기울기(ours/prod) {slope:.4f}  상관 {corr:.5f}")
    print(f"[validate] 중앙 α  ours {np.nanmedian(y):.4e}  prod {np.nanmedian(x):.4e}")
    return None


def _trace_doys(path):
    """알파 트레이스의 `doy` 열만 순서대로."""
    out, hdr = [], None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            t = line.rstrip("\n").split("\t")
            if hdr is None:
                hdr = t
                continue
            try:
                out.append(float(t[hdr.index("doy")]))
            except (ValueError, IndexError):
                out.append(np.nan)
    return out


def _limit_pair(props, kind, default):
    """ref_props 의 `sh_val`/`sq_val` ("-5, 5") → (lo, hi). 파싱 실패하면 default."""
    try:
        lo, hi = (float(v) for v in str(props.get(f"{kind}_val", "")).split(",")[:2])
        return (lo, hi) if lo <= hi else (hi, lo)
    except (ValueError, TypeError):
        return default


def _gas_key(gas_list, want):
    for g in gas_list:
        if want.lower() in g.lower().replace("-", ""):
            return g
    return None


# ── 본체 ─────────────────────────────────────────────────────────────────────
def run(args):
    files = sorted({p for pat in args.raw for p in glob.glob(pat)})
    files = [f for f in files if f.lower().endswith(".dat")]
    if not files:
        raise SystemExit("ABSTAIN: --raw 가 아무 파일도 안 가리킨다")

    cache = args.cache or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       f"_cache_{args.label}.npz")
    if os.path.exists(cache) and not args.refresh:
        z = np.load(cache)
        d = {k: z[k] for k in z.files}
        print(f"[cache] {os.path.basename(cache)} 재사용 "
              f"(ZA {len(d['za_sec'])} blocks, amb {len(d['amb_sec'])} bins)")
    else:
        print(f"[pass1] {len(files)} raw 파일 파싱 중…")
        d = collect(files, args.channel, args.purge_settle_sec, args.avg_sec,
                    parallel=not args.no_parallel)
        np.savez_compressed(cache, **d)
        print(f"[pass1] ZA {len(d['za_sec'])} blocks, ambient {len(d['amb_sec'])} bins "
              f"→ {os.path.basename(cache)}")

    za_x, is_sec, breaks = build_interpolators(d)
    n = len(za_x)
    if n < 4:
        raise SystemExit(f"ABSTAIN: ZA knot {n}개로는 leave-one-out 이 무의미하다")
    print(f"[I0] knot {n}개, 축={'real-time' if is_sec else 'scan-index'}, "
          f"분절 break {len(breaks)}개, knot 간격 중앙값 "
          f"{np.median(np.diff(za_x)) / (3600 if is_sec else 1):.2f}"
          f"{'h' if is_sec else ' idx'}")

    # ── 핏 설정 ──
    cfg = json.load(open(args.fitset, encoding="utf-8"))["channels"][str(args.ch_key)]
    wave = DataIO.load_wavecal_array(cfg["wl_path"])
    wave = np.asarray(wave, float).ravel()
    if len(wave) != d["za_arr"].shape[1]:
        raise SystemExit(f"ABSTAIN: wavecal {len(wave)}px vs 스펙트럼 "
                         f"{d['za_arr'].shape[1]}px — 채널이 안 맞는다")
    fitter = ScanFitter(cfg, wave, target=args.target, e_f=args.e_f,
                        step_limit=args.step_limit, sh_limit=args.sh_limit,
                        sh_fix=args.sh_fix)
    gases = fitter.gas_list
    kNO2 = _gas_key(gases, "no2")
    kCHO = _gas_key(gases, "chocho")
    kH2O = _gas_key(gases, "h2o")
    inwin = (wave >= cfg["fit_start_nm"]) & (wave <= cfg["fit_end_nm"])
    print(f"[fit] {cfg['fit_start_nm']}-{cfg['fit_end_nm']} nm poly{cfg['poly_deg']} "
          f"gases={gases} target={args.target}")
    if "za_noise" in d and d["za_noise"].size:
        nz = float(np.nanmedian(d["za_noise"][:, inwin]))
        print(f"[I0] ZA 블록당 스캔 {np.nanmedian(d['za_nscan']):.0f}개 → 블록평균 I₀ 의 "
              f"상대 광자잡음 중앙 {nz:.3e} (핏창). **ε 의 바닥이 여기다** — 예측에 이웃"
              f" knot 도 쓰이므로 드리프트가 0 이어도 ε ≈ √2·{nz:.1e} = {nz * np.sqrt(2):.1e}")

    # ── R(t) ──
    from rt_precompute import load_rt
    rt = load_rt(args.rt)
    rt_ks = np.asarray(rt["knot_sec"], float)
    rt_od = np.asarray(rt["omr_d"], float)
    rt_pchip = SegmentedPchip(rt_ks, rt_od,
                              break_x=list(np.asarray(rt.get("manual_breaks_sec", []), float)))
    za_ref = RayleighPhysics.get_alpha_rayleigh(wave, 0.0, 1013.25, "zero_air")
    rl = float(cfg.get("rl_factor", 1.0))

    pchip_i0 = SegmentedPchip(za_x, d["za_arr"], break_x=breaks)
    pchip_t = SegmentedPchip(za_x, d["za_t"], break_x=breaks)
    pchip_p = SegmentedPchip(za_x, d["za_p"], break_x=breaks)

    def _alpha_at(j, i0=None, t_i0=None, p_i0=None, omr_in=None):
        """ambient 빈 j 의 α — gui/worker.py Pass 2 의 조립식 그대로."""
        xq = float((d["amb_sec"] if is_sec else d["amb_g"])[j])
        I = d["amb_I"][j]
        I0 = np.asarray(pchip_i0(xq), float) if i0 is None else np.asarray(i0, float)
        t0_ = float(pchip_t(xq)) if t_i0 is None else float(t_i0)
        p0_ = float(pchip_p(xq)) if p_i0 is None else float(p_i0)
        with np.errstate(divide="ignore", invalid="ignore"):
            q = np.where((I > 0) & (I0 > 0), (I0 - I) / I, np.nan)
        if omr_in is None:
            omr = np.asarray(rt_pchip(float(d["amb_sec"][j])), float)
            if omr.shape != wave.shape:
                omr = np.interp(wave, np.asarray(rt["wave_nm"], float)[:omr.shape[0]], omr)
        else:
            omr = np.asarray(omr_in, float)
        a_ref = _alpha_za_plain(t0_, p0_, za_ref)
        a_samp = _alpha_za_plain(float(d["amb_T"][j]), float(d["amb_P"][j]), za_ref)
        return (omr + rl * a_ref) * np.nan_to_num(q) - (a_samp - a_ref), q, omr, a_ref, a_samp, I, I0

    if args.validate_alpha:
        return _validate_alpha(args, d, wave, inwin, _alpha_at)

    if args.split_half:
        return _split_half(args, d, wave, inwin, za_x, breaks, is_sec,
                           _alpha_at, fitter, (kNO2, kCHO, kH2O))

    if args.joint_loo:
        return _joint_loo(args, d, wave, inwin, rt, za_x, breaks, is_sec,
                          pchip_i0, _alpha_at, fitter, (kNO2, kCHO, kH2O))

    if args.i0_gap_fit:
        return _i0_gap_fit(args, d, wave, inwin, za_x, breaks, is_sec,
                           _alpha_at, fitter, (kNO2, kCHO, kH2O))

    if args.rt_loo:
        return _rt_loo(args, d, wave, inwin, rt, rt_ks, rt_od, rl, za_ref,
                       pchip_t, pchip_p, _alpha_at, fitter, (kNO2, kCHO, kH2O))

    ax = d["amb_sec"] if is_sec else d["amb_g"]
    h = float(np.median(np.diff(za_x))) / (3600.0 if is_sec else 1.0)

    def _eps_at(k, leave):
        """removed run 의 가운데에 가장 가까운 ambient 빈에서 ε → (bin, mean, shape_rms)."""
        # 뺀 구간의 **양옆 남은 knot** 사이 중간점 = 보간이 가장 멀리 외로운 자리.
        mid = (za_x[k - 1] + za_x[min(k + leave, len(za_x) - 1)]) / 2.0
        j = int(np.argmin(np.abs(ax - mid)))
        e = loo_eps(za_x, d["za_arr"], breaks, k, float(ax[j]), leave)
        if e is None or not np.isfinite(e[inwin]).any():
            return None
        em = float(np.nanmean(e[inwin]))
        return j, e, em, float(np.sqrt(np.nanmean((e - em)[inwin] ** 2)))

    if args.gap_scan:
        print(f"[gap-scan] 운용 knot 간격 h = {h:.2f} h. leave=N 은 간격을 (N+1)·h 로 벌린다.")
        print("  gap_h  n   |eps_mean| med   eps_shape_rms med")
        pts = []
        for leave in range(1, args.gap_scan + 1):
            res = [_eps_at(k, leave) for k in range(1, n - leave)]
            res = [r for r in res if r]
            if not res:
                continue
            gm = float(np.median([abs(r[2]) for r in res]))
            gs = float(np.median([r[3] for r in res]))
            pts.append(((leave + 1) * h, gm, gs))
            print(f"  {(leave + 1) * h:5.2f} {len(res):3d}   {gm:.4e}      {gs:.4e}")
        if len(pts) >= 2:
            g = np.log([p[0] for p in pts])
            for name, i in (("|eps_mean|", 1), ("eps_shape_rms", 2)):
                y = np.log([p[i] for p in pts])
                slope = float(np.polyfit(g, y, 1)[0])
                at_h = float(np.exp(np.polyval(np.polyfit(g, y, 1), np.log(h))))
                print(f"  {name}: 멱지수 {slope:+.2f} → 운용 간격 {h:.2f} h 로 외삽하면 {at_h:.3e}")
            print("  ⚠ 외삽은 2점~3점 회귀다. 운용 간격의 오차는 **직접 잴 수 없다**"
                  "(그 knot 을 빼면 간격이 벌어지므로). 상한은 leave=1 행이다.")
        return None

    rows = []
    detail = []
    eps_stats = []
    amp_stats = []
    n_at_bound = 0
    for k in range(1, n - 1):            # 중간 knot 만 (양끝은 외삽=상수 정책)
        # knot k 시각에 가장 가까운 ambient 60 s 빈. ε 도 q 도 **이 빈의 시각**에서
        # 잰다 — production 이 그 빈의 α 를 만들 때 실제로 쓴 질의점이 여기라
        # 그래야 ε 과 증폭이 같은 점의 값이 된다.
        j = int(np.argmin(np.abs(ax - za_x[k])))
        xq = float(ax[j])
        eps = loo_eps(za_x, d["za_arr"], breaks, k, xq)
        if eps is None or not np.isfinite(eps[inwin]).any():
            continue
        e_mean = float(np.nanmean(eps[inwin]))
        e_shape = eps - e_mean
        e_shape_rms = float(np.sqrt(np.nanmean(e_shape[inwin] ** 2)))
        eps_stats.append((e_mean, e_shape_rms))

        alpha0, q, omr, a_ref, a_samp, I, I0 = _alpha_at(j)
        with np.errstate(divide="ignore", invalid="ignore"):
            amp = np.where(np.abs(q) > 1e-12, (1.0 + q) / q, np.nan)
        amp_stats.append(float(np.nanmedian(np.abs(amp[inwin]))))
        t_i0, p_i0 = float(pchip_t(xq)), float(pchip_p(xq))
        t_am, p_am = float(d["amb_T"][j]), float(d["amb_P"][j])
        C = omr + rl * a_ref

        # 시드는 **한 번만** 격자로 잡고, base 와 섭동핏을 같은 시드·같은 상자에서
        # 출발시킨다 = production 웜스타트와 같은 조건이자 유일한 공정한 비교.
        sh0, sq0, ef_auto = fitter.seed(alpha0, t_am, p_am)
        start = (sh0, sq0)
        ef_used = fitter.e_f if fitter.e_f is not None else ef_auto
        base = fitter.fit(alpha0, t_am, p_am, start, ef_used)
        amp_full = np.nan_to_num(C * (I0 / np.where(I > 0, I, np.nan)))
        cases = [(f"i0_loo_k{k:02d}_full", eps, e_mean, e_shape_rms, alpha0 + amp_full * np.nan_to_num(eps)),
                 (f"i0_loo_k{k:02d}_scale", None, e_mean, 0.0, alpha0 + amp_full * e_mean),
                 (f"i0_loo_k{k:02d}_shape", None, 0.0, e_shape_rms,
                  alpha0 + amp_full * np.nan_to_num(e_shape))]

        # T·P 보간 오차 — Rayleigh 항에만 들어간다(α 조립식의 덧셈·곱셈 양쪽)
        t_loo, p_loo = loo_scalar(za_x, d["za_t"], breaks, k, xq), \
            loo_scalar(za_x, d["za_p"], breaks, k, xq)
        if t_loo is not None and p_loo is not None:
            a_ref2 = _alpha_za_plain(t_loo, p_loo, za_ref)
            cases.append((f"tp_loo_k{k:02d}", None, t_loo - t_i0, p_loo - p_i0,
                          (omr + rl * a_ref2) * np.nan_to_num(q) - (a_samp - a_ref2)))

        for case, _e, a_col, b_col, a_pert in cases:
            pert = fitter.fit(a_pert, t_am, p_am, start, ef_used)
            bad = bool(base["_at_bound"] or pert["_at_bound"])
            n_at_bound += int(bad)
            rows.append(_row(case, a_col, b_col, base, pert, kNO2, kCHO, kH2O))
            detail.append(dict(case=case, xq=xq, amp_med=amp_stats[-1],
                               e_f=ef_used, ef_auto_base=ef_auto,
                               at_bound=int(bad),
                               shift_base=base["_shift"], shift_pert=pert["_shift"],
                               **{f"{g}_base": base[g] for g in gases},
                               **{f"{g}_pert": pert[g] for g in gases}))

    if not rows:
        raise SystemExit("ABSTAIN: 유효한 LOO knot 이 없다")

    # 집계 행 — |값| 의 중앙값·p95 (부호가 섞여 상쇄되면 크기를 못 본다)
    for kind in ("i0_loo_full", "i0_loo_scale", "i0_loo_shape", "tp_loo"):
        sel = [r for r in rows if _matches(r["case"], kind)]
        if not sel:
            continue
        for stat, fn in (("median", lambda v: float(np.nanmedian(v))),
                         ("p95", lambda v: float(np.nanpercentile(v, 95)))):
            agg = {"case": f"{kind}_{stat}|abs|", "reported": REPORTED_1SIG}
            for c in CSV_COLS[1:-1]:
                agg[c] = fn([abs(r[c]) for r in sel if np.isfinite(r[c])] or [np.nan])
            rows.append(agg)

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   f"i0_loo_{args.label}.csv")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(",".join(CSV_COLS) + "\n")
        for r in rows:
            fh.write(",".join(f"{r[c]:.6g}" if isinstance(r[c], float) else str(r[c])
                              for c in CSV_COLS) + "\n")
    em = np.array([e[0] for e in eps_stats]); es = np.array([e[1] for e in eps_stats])
    print(f"[eps] scale |mean| 중앙 {np.nanmedian(np.abs(em)):.3e} "
          f"p95 {np.nanpercentile(np.abs(em), 95):.3e} | "
          f"shape rms 중앙 {np.nanmedian(es):.3e} p95 {np.nanpercentile(es, 95):.3e}")
    print(f"[amp] 실측 |I0/(I0−I)| 중앙 {np.nanmedian(amp_stats):.1f} "
          f"(min {np.nanmin(amp_stats):.1f} max {np.nanmax(amp_stats):.1f})")
    if n_at_bound:
        print(f"[warn] shift 가 상자 끝에 붙은 핏 {n_at_bound}/{len(rows)}개 — 그 행의"
              f" 농도차는 섭동이 아니라 step_limit({fitter.cfg['step_limit']:.2f} px)이"
              f" 만든 값이다. --step-limit 을 키워 다시 볼 것")
    det = out.replace(".csv", "_detail.csv")
    if detail:
        keys = list(detail[0])
        with open(det, "w", encoding="utf-8") as fh:
            fh.write(",".join(keys) + "\n")
            for r in detail:
                fh.write(",".join(f"{r[k]:.6g}" if isinstance(r[k], float) else str(r[k])
                                  for k in keys) + "\n")
    _report_scale(rows, args)
    print(f"→ {out}  ({len(rows)} rows)")
    print(f"→ {det}  (핏별 원자료: 절대농도·etalon f·shift·rms)")
    return out


def _report_scale(rows, args):
    """상자에 안 붙은 `full` 행만으로 **1σ 규모**를 내고 관측 상한과 대조한다.

    중앙값|.|은 규모가 아니다(정규분포면 0.674σ). 오차예산에 들어갈 것은 로버스트
    표준편차 1.4826·MAD 이고, n 이 작아 std 는 꼬리 하나에 끌려간다.
    """
    sel = [r for r in rows if r["case"].startswith("i0_loo_k")
           and r["case"].endswith("_full") and not r.get("at_bound")]
    v = np.array([r["no2_rel"] for r in sel if np.isfinite(r["no2_rel"])], float)
    if v.size < 3:
        print(f"[scale] 상자에 안 붙은 full 행이 {v.size}개 — 규모를 낼 수 없다(ABSTAIN)")
        return
    rsd = float(1.4826 * np.median(np.abs(v - np.median(v))))
    print(f"[scale] n={v.size}  signed mean {v.mean():+.4f}  median|.| "
          f"{np.median(np.abs(v)):.4f}  **robust SD {rsd:.4f}**  std {v.std(ddof=1):.4f}")
    ppb = rsd * float(args.channel_no2_ppb)
    print(f"[scale] 채널 NO2 {args.channel_no2_ppb} ppb 기준 이 채널 기여 {ppb:.4f} ppb "
          f"(LOO 상한; 운용조건은 ×0.5~0.7 — 간격 2배 + 두 실현의 차라 √2 과대)")
    if args.ceiling_ppb:
        # 한 채널만으로도 상한을 넘으면 그 시점에 끝이다(ΣANs 는 두 채널 제곱합이라 더 크다).
        ok = ppb <= args.ceiling_ppb
        print(f"[gate] 관측 상한 {args.ceiling_ppb:.4f} ppb 대비 {ppb / args.ceiling_ppb:.2f}배 "
              + ("PASS" if ok else "**FAIL — 구조항 추정치가 그 양의 관측 총변동을 넘었다**"))


def _matches(case, kind):
    if kind == "tp_loo":
        return case.startswith("tp_loo_k")
    return case.startswith("i0_loo_k") and case.endswith(kind.rsplit("_", 1)[-1])


def _row(case, a, b, base, pert, kNO2, kCHO, kH2O):
    def rel(g):
        if g is None:
            return np.nan
        b0 = base.get(g)
        if b0 is None or not np.isfinite(b0) or abs(b0) < 1e-30:
            return np.nan
        return (pert[g] - b0) / b0
    return {"at_bound": bool(base.get("_at_bound") or pert.get("_at_bound")),
            "case": case, "eps_mean": float(a), "eps_shape_rms": float(b),
            "no2_rel": rel(kNO2), "chocho_rel": rel(kCHO), "h2o_rel": rel(kH2O),
            "dshift": float(pert["_shift"] - base["_shift"]),
            "reported": REPORTED_1SIG}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", nargs="+", required=True, help="raw .dat glob(들)")
    ap.add_argument("--channel", type=int, required=True, help="data_io 채널(1/2)")
    ap.add_argument("--label", required=True, help="출력/캐시 이름 (cold, hot_PNs, …)")
    ap.add_argument("--rt", required=True, help="production R(t) npz")
    ap.add_argument("--fitset", required=True)
    ap.add_argument("--ch-key", required=True)
    ap.add_argument("--target", default="NO2",
                    help="shift/squeeze 를 주도하는 종 (fitset 의 Link 대상)")
    ap.add_argument("--e-f", type=float,
                    help="etalon 각주파수를 이 값(rad/px)으로 **고정**한다. 안 주면 "
                         "스캔마다 자동검출값을 쓰되 base·섭동은 같은 값을 쓴다. "
                         "채널 최빈값은 T2 참고 (PNs 0.1368 · ANs 0.1590 · cold 0.1639)")
    ap.add_argument("--step-limit", type=float,
                    help="fitset 의 step_limit 을 덮어쓴다. 섭동 핏이 상자 끝에 "
                         "붙으면 농도차가 섭동이 아니라 상자 크기의 함수가 된다")
    ap.add_argument("--sh-limit", metavar='"-10, 10"',
                    help="target 종의 전역 shift 한계를 덮어쓴다 (fitset 은 -5, 5)")
    ap.add_argument("--sh-fix", type=float,
                    help="target 종의 shift 를 이 값으로 Fix 한다 (cold 처럼 이미 전역 "
                         "경계에 붙어 있는 채널에서 경계 인공물을 없애고 잰다)")
    ap.add_argument("--ceiling-ppb", type=float,
                    help="수용 게이트: 전파된 ΣANs 기여가 이 값을 넘으면 FAIL. "
                         "관측 ΣANs 시간척도 상한 0.083 ppb (병합자료 실측)")
    ap.add_argument("--channel-no2-ppb", type=float, default=2.2895,
                    help="ΣANs 환산용 채널 NO2 중앙 농도")
    ap.add_argument("--avg-sec", type=float, default=60.0)
    ap.add_argument("--purge-settle-sec", type=float, default=60.0)
    ap.add_argument("--gap-scan", type=int, metavar="MAXLEAVE",
                    help="ε 을 knot 간격의 함수로만 재고 끝낸다 (leave=1..MAXLEAVE). "
                         "핏은 안 돈다 — 간격-오차 곡선과 운용 간격 외삽만 낸다")
    ap.add_argument("--split-half", action="store_true",
                    help="ZA 블록을 짝/홀로 갈라 knot 잡음 효과를 **외삽 없이** 직접 잰다")
    ap.add_argument("--joint-loo", action="store_true",
                    help="같은 시각의 ZA knot 과 R knot 을 **동시에** 빼서 잰다. "
                         "둘은 같은 ZA 블록에서 나오므로 제곱합이 과소계상이다")
    ap.add_argument("--i0-gap-fit", action="store_true",
                    help="I₀ LOO 를 **NO₂ 응답 공간**에서 간격별로 잰다 (R(t) 표와 같은 양). "
                         "--gap-scan 은 ε 공간이라 지수를 나란히 놓을 수 없다")
    ap.add_argument("--rt-loo", action="store_true",
                    help="I₀ 대신 **R(t) knot** 에 leave-N-out 을 돌린다 (운영 R npz 사용). "
                         "결과는 스칼라가 아니라 유효간격별 분포로 낸다")
    ap.add_argument("--rt-leave-max", type=int, default=5,
                    help="--rt-loo 에서 연속으로 빼는 knot 수의 최대값 (유효간격 (N+1)·h)")
    ap.add_argument("--validate-alpha", metavar="DIR",
                    help="수용 게이트: 이 폴더의 production *alpha_trace.dat 과 "
                         "우리가 조립한 α 를 같은 60 s 빈끼리 대조하고 끝낸다")
    ap.add_argument("--cache")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--no-parallel", action="store_true")
    ap.add_argument("--out")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
