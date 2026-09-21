#!/usr/bin/env python
"""T2 — 채널별 에탈론 주파수 확정.  (읽기 전용 진단)

왜
--
운영 `fixed_e_f = 0.12 rad/px` 는 **PNs 창의 값**이다. cold·ANs 채널의 실제 주파수는
확인된 적이 없다. 에탈론 항은 ΣANs 오차예산의 76 % 를 차지하는데, 그 크기가 **채널 간
차등인지 상쇄인지**가 f 의 채널별 값에 달려 있다. 주파수가 맞으면 선형 sin·cos 쌍이
진폭 10 % 도 흡수하지만, f 가 틀리면 그 진폭이 기체로 샌다.

운영 경로의 사실 두 가지 (`gui/worker.py:839`, `:1153`)
  * f 는 **런의 첫 스캔에서 한 번** 검출돼 그 런 내내 고정된다. 즉 f 는 채널 상수가
    아니라 **그 런 첫 스캔의 제비뽑기**다.
  * 검출은 FFT argmax 라 f 가 **k/N 으로 양자화**된다. 핏창 N≈530 px 면 이웃 bin 과
    0.0119 rad/px 떨어져 있다 — 0.12 는 k=10 에 해당한다.

무엇을 재는가
------------
1. 채널 창마다 production 알파 수백 장에 `DoasFitter.detect_etalon_frequency` 를
   그대로 돌려 f 분포(중앙값·IQR·최빈 bin 점유율)를 낸다.
2. 분포 중앙값이 0.12 와 다르면, 그 차이를 **섭동으로 넣어** 기체별 상대편향을
   T1 과 같은 열 구조로 낸다.

재현
----
    python diagnostics/etalon_freq_2026-09/etalon_freq.py \
        --alpha-dir "C:/Doasis_Work/Output/alpha_purge60/26yeosu/2026-05-18/alpha/ch2" \
        --fitset "<FitSet_*.bak_20260722_labelswap>" --ch-key 2 --label hot_PNs
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_TOOLS = os.path.join(_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import scipy.interpolate as _si

from core import param_optimizer as PO
from core.data_io import DataIO
from core.doas_fit import DoasFitter, alpha_fit_scale
from core.physics import air_number_density
from za_gas_sigma import build_engine, read_alpha_trace

REPORTED_1SIG = 0.0055
OPERATIONAL_EF = 0.12          # gui/worker 가 PNs 첫 스캔에서 뽑아 쓰던 값
FREQ_MIN, FREQ_MAX = 0.02, 0.40    # gui/worker.py:120 과 동일 (cyc/px)

CSV_COLS = ["case", "eps_mean", "eps_shape_rms", "no2_rel", "chocho_rel",
            "h2o_rel", "dshift", "reported"]


class Channel:
    """한 채널의 창·엔진·핏. `param_optimizer.fit_scan` 과 같은 경로를 쓰되,
    **etalon 각주파수만 밖에서 지정**할 수 있게 열어 둔 판이다.

    `fit_scan` 은 스캔마다 f 를 재검출하므로 "f 를 X 로 두면 어떻게 되나" 를 물을 수
    없다. 그래서 그 함수의 스케일링(`alpha_fit_scale` — 없으면 least_squares 가
    θ₀에서 멈춘다)과 파라미터 구성을 그대로 따라 한 `fit()` 을 둔다. 같은 값을 주면
    `fit_scan` 과 일치하는지 `--selftest` 가 매번 확인한다.
    """

    def __init__(self, cfg, target="NO2"):
        self.cfg, self.target = cfg, target
        self.wave = np.asarray(DataIO.load_wavecal_array(cfg["wl_path"]), float).ravel()
        self.eng = build_engine(cfg, self.wave)
        self.fitter = DoasFitter(self.eng)
        idx = np.where((self.wave >= cfg["fit_start_nm"]) & (self.wave <= cfg["fit_end_nm"]))[0]
        if len(idx) < 50:
            raise SystemExit("ABSTAIN: 핏 창이 알파 파장축과 거의 안 겹친다")
        self.px_min, self.px_max = int(idx[0]), int(idx[-1])
        self.sl = slice(self.px_min, self.px_max + 1)
        wax = np.asarray(self.eng._wave_axis, float).ravel()
        self.vp = np.asarray(_si.interp1d(wax, np.arange(len(wax)), bounds_error=False,
                                          fill_value="extrapolate")(self.wave[self.sl]), float)
        self.n = len(self.vp)

    def detect(self, alpha):
        a = np.asarray(alpha, float)[self.sl]
        return float(self.fitter.detect_etalon_frequency(
            self.vp, a * alpha_fit_scale(a), int(self.cfg["poly_deg"]), FREQ_MIN, FREQ_MAX))

    def fit(self, alpha, T_C, P_mbar, e_f, start, want_diag=False):
        """want_diag=True 면 잔차 RMS·보고 σ 를 같이 낸다.

        `return_diagnostics=True` 는 반환 튜플 `o` 를 **바꾸지 않는다** — 진단은
        핏이 끝난 뒤 따로 계산된다. 그래서 농도·shift 는 바이트 동일하고,
        기존 호출부(want_diag 기본 False)는 한 글자도 영향받지 않는다.
        `_perr` 는 반환 튜플의 `c_perr`(조건부 선형 오차, 운영 `<gas>_Error` 와
        같은 양)를 ppb 로 환산한 것이다.
        """
        c = self.cfg
        a = np.asarray(alpha, float)[self.sl]
        s = alpha_fit_scale(a)
        sh, sq = float(start[0]), float(start[1])
        step = float(c["step_limit"])
        # `param_optimizer.fit_scan` 의 controlled_start=None 경로를 **그대로** 따라 한다
        # (anchor=시드, 상자=시드±step, squeeze t0 만 시드로 클립). 한 줄이라도 달리
        # 쓰면 cold 처럼 shift 가 구속 안 되는 채널에서 다른 국소해로 간다.
        act, fx, lk, t0, lb, ub = self.fitter.setup_fit_parameters(
            c["ref_props"], sh, [sh, 1.0], step)
        sq_key = f"{self.target}_sq"
        if sq_key in act:
            k = act.index(sq_key)
            t0[k] = float(min(max(sq, lb[k] + 1e-9), ub[k] - 1e-9))
        o = self.fitter.execute_varpro_fit(
            self.vp, a * s, np.ones(self.n), act, fx, lk, t0, lb, ub,
            int(c["poly_deg"]), float(e_f), self.vp[self.n // 2], 1.0,
            c["ref_props"], T_C, 0.0, False, allow_negative_gas=True,
            return_diagnostics=want_diag)
        diag = None
        if want_diag:
            o, diag = o
        gco = np.asarray(o[2], float) / s
        na = air_number_density(T_C, P_mbar)
        out = {g: float(gco[i] * self.eng.multipliers.get(g, 1.0)
                        / self.eng.scaling_factors.get(g, 1.0) / na * 1e9)
               for i, g in enumerate(self.eng.gas_list)}
        out["_shift"] = float(o[0][self.eng.gas_list.index(self.target)])
        out["_squeeze"] = float(o[1][self.eng.gas_list.index(self.target)])
        out["_e_f"] = float(e_f)
        if diag is not None:
            # 잔차는 스케일된 α 위에서 최소화됐다 — s 로 나눠 물리 단위로 되돌린다
            obj = float(diag.get("objective_final", np.nan))
            out["_resid_rms"] = (float(np.sqrt(max(obj, 0.0) / self.n)) / s
                                 if np.isfinite(obj) else np.nan)
            pe = np.asarray(o[6], float) / s
            out["_perr"] = {g: float(pe[i] * self.eng.multipliers.get(g, 1.0)
                                     / self.eng.scaling_factors.get(g, 1.0) / na * 1e9)
                            for i, g in enumerate(self.eng.gas_list)}
            out["_status"] = str((diag.get("solver_termination") or {}).get("status", ""))
        # shift 가 상자 끝에 붙었나. 붙은 핏의 농도차를 "섭동 효과"로 읽으면 안 된다
        # (그건 step_limit 이 만든 값이다) — T7 이 다루는 바로 그 상태.
        sh_key = f"{self.target}_sh"
        if sh_key in act:
            k = act.index(sh_key)
            tol = 1e-6 * max(1.0, abs(lb[k]), abs(ub[k]))
            out["_at_bound"] = bool(min(abs(out["_shift"] - lb[k]),
                                        abs(out["_shift"] - ub[k])) <= tol)
        else:
            out["_at_bound"] = False
        return out

    def seed(self, alpha, T_C, P_mbar):
        """격자 시딩은 production 과 같은 `fit_scan` 에 맡긴다."""
        r = PO.fit_scan(self.eng, self.fitter, self.cfg["ref_props"], self.wave,
                        np.asarray(alpha, float), T_C, P_mbar,
                        self.px_min, self.px_max, int(self.cfg["poly_deg"]),
                        float(self.cfg["step_limit"]), target=self.target,
                        allow_negative_gas=True)
        # **수렴한 shift 가 아니라 격자 시드**를 돌려준다. fit_scan 은 상자를 시드에
        # 앵커하므로(anchor = seed), 재핏도 같은 상자를 써야 같은 계를 푸는 것이 된다.
        # 수렴값에 앵커했더니 cold 처럼 shift 가 경계에 붙는 채널에서 31/31 이
        # fit_scan 과 어긋났다(최대 11 %).
        sd = r["deterministic_seed"]
        return (float(sd["shift"]), float(sd["squeeze"]),
                float(r["etalon_frequency"]), r["conc_all"])


def _gas_key(gases, want):
    for g in gases:
        if want.lower() in g.lower().replace("-", ""):
            return g
    return None


def load_rows(alpha_dir, limit):
    paths = sorted(glob.glob(os.path.join(alpha_dir, "*alpha_trace.dat")))
    if not paths:
        raise SystemExit(f"ABSTAIN: {alpha_dir} 에 *alpha_trace.dat 이 없다")
    out = []
    for p in paths:
        w, ri, A, T, P = read_alpha_trace(p)
        for i in range(len(A)):
            a = np.asarray(A[i], float)
            if np.all(np.isfinite(a)) and np.any(a != 0):
                out.append((a, T, P))
            if len(out) >= limit:
                return out, w
    return out, w


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alpha-dir", required=True)
    ap.add_argument("--fitset", required=True)
    ap.add_argument("--ch-key", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--target", default="NO2")
    ap.add_argument("--limit", type=int, default=400, help="쓸 스캔 수 (최소 수백)")
    ap.add_argument("--sens", type=int, default=40, help="민감도 핏에 쓸 스캔 수")
    ap.add_argument("--vs-detected", action="store_true",
                    help="운영 고정 f 핏 vs 스캔별 검출 f 핏의 차 분포까지 낸다 "
                         "(주파수 항의 하한이 아닌 값)")
    ap.add_argument("--fixed-f", type=float,
                    help="--vs-detected 의 고정 f. 기본은 채널 최빈값")
    ap.add_argument("--channel-no2-ppb", type=float, default=2.2895)
    ap.add_argument("--ceiling-ppb", type=float, default=0.083)
    ap.add_argument("--selftest", action="store_true", default=True)
    ap.add_argument("--no-selftest", dest="selftest", action="store_false")
    ap.add_argument("--out")
    args = ap.parse_args()

    cfg = json.load(open(args.fitset, encoding="utf-8"))["channels"][str(args.ch_key)]
    ch = Channel(cfg, target=args.target)
    rows, wave_hdr = load_rows(args.alpha_dir, args.limit)
    if len(rows) < 100:
        print(f"[warn] 스캔 {len(rows)}개뿐 — 지시서가 요구한 '최소 수백' 미달")
    dw = float(np.max(np.abs(np.asarray(wave_hdr, float)[:len(ch.wave)] - ch.wave[:len(wave_hdr)])))
    print(f"[{args.label}] 창 {cfg['fit_start_nm']}-{cfg['fit_end_nm']} nm "
          f"N={ch.n} px poly{cfg['poly_deg']}  스캔 {len(rows)}개")
    print(f"[axis] 알파 헤더축 vs fitset wl_path 최대차 {dw:.4f} nm "
          f"({dw / 0.0483:.2f} px) — 0 이 아니면 T3 의 배선 문제다")

    fs = np.array([ch.detect(a) for a, _, _ in rows], float)
    bin_rad = 2.0 * np.pi / ch.n           # FFT 격자 간격 (rad/px)
    q1, med, q3 = np.percentile(fs, [25, 50, 75])
    # 분포가 넓어 중앙값은 대표값이 못 된다 — **최빈 bin** 을 쓴다.
    _ks = np.round(fs / bin_rad).astype(int)
    mode_k = int(np.bincount(_ks - _ks.min()).argmax() + _ks.min())
    frac = float(np.mean(_ks == mode_k))
    print(f"[f] 중앙 {med:.4f} rad/px  IQR {q1:.4f}–{q3:.4f}  "
          f"FFT bin 간격 {bin_rad:.4f}  최빈 bin k={mode_k} ({mode_k * bin_rad:.4f}) "
          f"점유 {frac * 100:.0f}%")
    print(f"[f] 운영값 {OPERATIONAL_EF:.4f} 대비 중앙값 차 {med - OPERATIONAL_EF:+.4f} rad/px "
          f"= {(med - OPERATIONAL_EF) / bin_rad:+.2f} bin")

    # ── 민감도: 같은 스캔을 f=운영값 / f=채널중앙값 두 벌로 핏 ──
    gases = list(ch.eng.gas_list)
    kNO2, kCHO, kH2O = (_gas_key(gases, g) for g in ("no2", "chocho", "h2o"))
    # 최빈 bin 점유율이 낮으면 "채널 고유 주파수"라는 전제 자체가 없는 것이다.
    ks = np.round(fs / bin_rad).astype(int)
    top = np.argsort(np.bincount(ks - ks.min()))[::-1][:5] + ks.min()
    print("[f] 상위 bin (k, rad/px, 점유율): "
          + "  ".join(f"k={k} {k * bin_rad:.4f} {np.mean(ks == k) * 100:.0f}%" for k in top))

    out_rows, rels, self_d = [], [], []
    step = max(1, len(rows) // max(args.sens, 1))
    for i in range(0, len(rows), step):
        a, T, P = rows[i]
        sh, sq, ef_auto, conc_fs = ch.seed(a, T, P)
        if args.selftest:
            # 같은 f·같은 시작점이면 fit_scan 과 같은 답이 나와야 한다.
            chk = ch.fit(a, T, P, ef_auto, (sh, sq))
            self_d.append(max(abs(chk[g] - conc_fs[g]) / max(abs(conc_fs[g]), 1e-30)
                              for g in gases))
        base = ch.fit(a, T, P, OPERATIONAL_EF, (sh, sq))
        alt = ch.fit(a, T, P, mode_k * bin_rad, (sh, sq))
        r = {"case": f"etalon_f_{args.label}_s{i:04d}",
             "eps_mean": float(mode_k * bin_rad - OPERATIONAL_EF),
             "eps_shape_rms": 0.0,
             "no2_rel": _rel(base, alt, kNO2), "chocho_rel": _rel(base, alt, kCHO),
             "h2o_rel": _rel(base, alt, kH2O),
             "dshift": float(alt["_shift"] - base["_shift"]),
             "reported": REPORTED_1SIG}
        out_rows.append(r)
        rels.append(r["no2_rel"])
    for stat, fn in (("median", np.nanmedian), ("p95", lambda v: np.nanpercentile(v, 95))):
        agg = {"case": f"etalon_f_{args.label}_{stat}|abs|", "reported": REPORTED_1SIG}
        for c in CSV_COLS[1:-1]:
            agg[c] = float(fn([abs(r[c]) for r in out_rows if np.isfinite(r[c])] or [np.nan]))
        out_rows.append(agg)
    if self_d:
        sd = np.asarray(self_d, float)
        print(f"[selftest] fit_scan 재현 {len(sd)}회: 최대 상대차 중앙 {np.median(sd):.1e}, "
              f"1e-6 초과 {int((sd > 1e-6).sum())}회 (초과분은 shift 가 상자 경계에 붙어 "
              f"국소해가 갈린 경우 — 최대 {sd.max():.1e})")
    print(f"[sens] f {OPERATIONAL_EF:.4f} → {mode_k * bin_rad:.4f} rad/px 로 바꾸면 "
          f"NO2 중앙 |Δ| {np.nanmedian(np.abs(rels)) * 100:.3f} % "
          f"(보고 1σ 0.55 % 의 {np.nanmedian(np.abs(rels)) / REPORTED_1SIG:.1f}배)")

    if args.vs_detected:
        _vs_detected(ch, rows, fs, bin_rad, mode_k, args, (kNO2, kCHO, kH2O))

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   f"etalon_f_{args.label}.csv")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(",".join(CSV_COLS) + "\n")
        for r in out_rows:
            fh.write(",".join(f"{r[c]:.6g}" if isinstance(r[c], float) else str(r[c])
                              for c in CSV_COLS) + "\n")
    np.savetxt(out.replace(".csv", "_freqs.txt"), fs, fmt="%.6f",
               header="detected etalon angular frequency (rad/px), one per scan")
    print(f"→ {out}  ({len(out_rows)} rows)")


def _vs_detected(ch, rows, fs, bin_rad, mode_k, args, gkeys):
    """운영 **고정 f** 핏 vs **스캔별 검출 f** 핏 — 주파수 항의 하한이 아닌 값.

    T2 본편이 잰 것은 두 고정값의 차(0.12 vs 채널 최빈값)라 **하한**이다. 진짜 f 가
    스캔마다 흩어져 있으면(최빈 점유 18~32 %) 어떤 고정값을 써도 대부분 스캔에 잔여
    불일치가 남는다. 그 잔여분까지 포함한 값이 이것이다.

    ⚠ 검출 f 자체도 잡음에 흔들리므로 이건 **상한** 성격이다 — 진짜 f 가 정말 스캔마다
    변한다면 하한과 상한 사이가 참값이고, 진짜 f 가 고정인데 검출만 흔들린다면 이 값은
    'f 검출 잡음이 농도에 주는 영향'이다. 둘은 T2 본편의 최빈 점유율로 구분한다.
    """
    kNO2, kCHO, kH2O = gkeys
    step = max(1, len(rows) // max(args.sens, 1))
    fixed = mode_k * bin_rad if args.fixed_f is None else float(args.fixed_f)
    rel, dfs = [], []
    for i in range(0, len(rows), step):
        a, T, P = rows[i]
        sh, sq, _ef, _c = ch.seed(a, T, P)
        ef_scan = float(fs[i])
        b = ch.fit(a, T, P, fixed, (sh, sq))
        d = ch.fit(a, T, P, ef_scan, (sh, sq))
        r = _rel(b, d, kNO2)
        if np.isfinite(r):
            rel.append(r); dfs.append(ef_scan - fixed)
    if len(rel) < 5:
        print("[vs-det] 유효 핏이 모자라 규모를 못 낸다(ABSTAIN)")
        return
    v = np.asarray(rel, float); df = np.asarray(dfs, float)
    rsd = float(1.4826 * np.median(np.abs(v - np.median(v))))
    ppb = rsd * float(args.channel_no2_ppb)
    print(f"[vs-det] 고정 f {fixed:.4f} vs 스캔별 검출 f — n={len(v)}  "
          f"|Δf| 중앙 {np.median(np.abs(df)):.4f} rad/px (p95 {np.percentile(np.abs(df), 95):.4f})")
    print(f"[vs-det] NO2 signed mean {v.mean():+.4f}  median|.| {np.median(np.abs(v)):.4f}  "
          f"**robust SD {rsd:.4f}** = {ppb:.4f} ppb  ({rsd / REPORTED_1SIG:.1f}×1σ)")
    if args.ceiling_ppb:
        print(f"[vs-det] 관측 상한 {args.ceiling_ppb:.4f} ppb 대비 {ppb / args.ceiling_ppb:.2f}배 "
              + ("PASS" if ppb <= args.ceiling_ppb else "**FAIL**"))


def _rel(base, alt, g):
    if g is None or g not in base:
        return float("nan")
    b = base[g]
    return float("nan") if not np.isfinite(b) or abs(b) < 1e-30 else float((alt[g] - b) / b)


if __name__ == "__main__":
    main()
