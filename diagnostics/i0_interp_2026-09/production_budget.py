#!/usr/bin/env python
"""[TBD-B] 생산 런 — **전 ambient 빈**에 전파하고, scale 은 마지막에 한 번만 취한다.

왜 다시 만드나
-------------
이전 표는 knot 당 **대표 빈 하나**로 만들어졌다. 그런데 응답은 그 빈의 증폭
|I₀/(I₀−I)| 에 심하게 의존하고(실측 9.0~349.8), 같은 knot 안에서도 빈에 따라
24~1366 % 흔들린다. 대표 빈을 2.6분 옮기면 robust SD 가 25 % 달라진다
(2026-09-21 실측: 2.234 % vs 2.803 %). **대표 빈 설계 자체가 틀렸다.**

그리고 §4.3 이 선언한 규칙이 바로 이걸 요구한다:

    모든 항을 **최종 산출물 시계열**로 전파하고, scale 은 **맨 마지막에 한 번** 취한다.

그래서 빈마다 하나의 응답을 만들어 **진짜 시계열**을 구성한다. 빈이 곧 산출물의
표본 단위이므로 가중은 자동으로 스캔당이 된다(knot 균등 가중이 사라진다).

무엇을 섭동하나 (빈 j 의 최근접 ZA knot k 를 기준으로)
  i0  : knot k 제거 → I₀(t) 재보간
  rt  : 같은 시각의 R knot 제거 → omr(t) 재보간
  ef  : 운영 고정 f(0.12) → 그 스캔이 검출한 f
  tri : 셋 동시

α 조립은 `gui/worker.py` Pass 2 식 그대로. i0·rt 는 선형화와 재조립이 **비트 동일**임을
확인했으므로(α 최대차 2.6e-22, 응답 최대차 1.2e-15) 재조립으로 통일한다.

시드는 **knot 당 1회** 격자 탐색 후 그 knot 창의 모든 빈이 공유한다(상자는 시드±step).
빈마다 격자를 다시 돌면 60배 느려지는데 shift 는 그 사이 거의 안 변한다 —
`--seed-per-bin` 으로 표본 검증할 수 있다.

재현
----
    python diagnostics/i0_interp_2026-09/production_budget.py --fitset "<운영 09-17>"

병렬은 knot 단위다(LOO 보간자·격자 시딩이 knot 당 한 번이라 빈 단위로 흩으면
시딩을 워커마다 다시 한다). **워커 수가 결과를 바꾸지 않는다** — 2026-09-21 확인:

    for J in 1 4; do python ... --limit 300 --jobs $J --out p_j$J.csv; done
    diff p_j1.csv p_j4.csv        # 동일

데이터가 필요해 CI 에는 못 넣는다. 병렬부를 고치면 이 diff 를 직접 돌려라.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys

import numpy as np
from scipy import stats

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_ROOT, os.path.join(_ROOT, "tools"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.physics import RayleighPhysics
from core.step_guard import SegmentedPchip
from gui.worker import _alpha_za_plain
from core.parallel import max_workers
from measure_i0_loo import ScanFitter, build_interpolators

OPERATIONAL_EF = 0.12


class Chan:
    def __init__(self, cache, rt_path, cfg, e_f, step_limit, target="NO2"):
        # 워커가 자기 프로세스에서 똑같이 다시 지을 수 있도록 재료를 들고 있는다
        self.src_cache, self.src_rt, self.src_cfg = cache, rt_path, cfg
        self.src_ef, self.src_step = e_f, step_limit
        z = np.load(cache)
        self.d = {k: z[k] for k in z.files}
        self.za_x, self.is_sec, self.breaks = build_interpolators(self.d)
        self.fit = ScanFitter(cfg, None, target=target, e_f=e_f, step_limit=step_limit)
        self.wave = self.fit.wave
        self.rl = float(cfg.get("rl_factor", 1.0))
        self.za_ref = RayleighPhysics.get_alpha_rayleigh(self.wave, 0.0, 1013.25, "zero_air")
        self.pi0 = SegmentedPchip(self.za_x, self.d["za_arr"], break_x=self.breaks)
        self.pt = SegmentedPchip(self.za_x, self.d["za_t"], break_x=self.breaks)
        self.pp = SegmentedPchip(self.za_x, self.d["za_p"], break_x=self.breaks)
        from rt_precompute import load_rt
        rt = load_rt(rt_path)
        o = np.argsort(np.asarray(rt["knot_sec"], float))
        self.rks = np.asarray(rt["knot_sec"], float)[o]
        self.rod = np.asarray(rt["omr_d"], float)[o]
        self.rwave = np.asarray(rt["wave_nm"], float)
        self.rbrk = list(np.asarray(rt.get("manual_breaks_sec", []), float))
        self.ax = self.d["amb_sec"] if self.is_sec else self.d["amb_g"]

    def omr(self, sec, keep=None):
        x = self.rks if keep is None else self.rks[keep]
        y = self.rod if keep is None else self.rod[keep]
        v = np.asarray(SegmentedPchip(x, y, break_x=self.rbrk)(float(sec)), float)
        return v if v.shape == self.wave.shape else np.interp(self.wave, self.rwave[:v.shape[0]], v)

    def amp(self, j, i0, inwin):
        """그 빈의 증폭배수 |I0/(I0-I)| 중앙 — §6.1 대리변수의 설명변수."""
        I = self.d["amb_I"][j]
        with np.errstate(divide="ignore", invalid="ignore"):
            q = np.where((I > 0) & (i0 > 0), (i0 - I) / I, np.nan)
            a = np.where(np.abs(q) > 1e-12, (1.0 + q) / q, np.nan)
        return float(np.nanmedian(np.abs(a[inwin])))

    def alpha(self, j, i0, omr):
        I = self.d["amb_I"][j]
        xq = float(self.ax[j])
        with np.errstate(divide="ignore", invalid="ignore"):
            q = np.where((I > 0) & (i0 > 0), (i0 - I) / I, np.nan)
        a_ref = _alpha_za_plain(float(self.pt(xq)), float(self.pp(xq)), self.za_ref)
        a_s = _alpha_za_plain(float(self.d["amb_T"][j]), float(self.d["amb_P"][j]), self.za_ref)
        return (omr + self.rl * a_ref) * np.nan_to_num(q) - (a_s - a_ref)


def rsd(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) if v.size else np.nan


KEYS = ("i0", "rt", "ef", "tri")
_W = {}


def _init_worker(spec):
    """워커마다 Chan 을 한 번만 짓는다. npz 가 채널당 ~350 MB 라 워커 수를 올리면
    메모리가 선형으로 는다 — 8 워커면 ~3 GB. 모자라면 `--jobs` 로 줄여라."""
    _W["C"] = Chan(spec["cache"], spec["rt"], spec["cfg"], spec["e_f"], spec["step_limit"])
    _W["seed_per_bin"] = spec["seed_per_bin"]


def _scan_chunk(chunk):
    return _scan(_W["C"], _W["seed_per_bin"], chunk)


def _scan(C, seed_per_bin, chunk):
    """chunk = [(k, kr, [빈 인덱스…]), …] → (레코드들, 비수렴수, 고착수, 시드수).

    knot 단위로 자르는 이유: LOO 보간자와 격자 시딩이 **knot 당 한 번**이고 그
    knot 의 모든 빈이 공유한다. 빈 단위로 흩으면 워커마다 시딩을 다시 해서
    60배 손해다.
    """
    nk = len(C.za_x)
    tgt = C.fit.target
    inwin = slice(C.fit.px_min, C.fit.px_max + 1)
    recs, n_bad, n_seed = [], 0, 0
    n_bound = {k: 0 for k in ("base",) + KEYS}
    for k, kr, js in chunk:
        kz = np.ones(nk, bool)
        kz[k] = False
        loo = SegmentedPchip(C.za_x[kz], C.d["za_arr"][kz], break_x=C.breaks)
        keepR = np.ones(len(C.rks), bool)
        keepR[kr] = False
        seed = None
        for jj in js:
            xq = float(C.ax[jj])
            sec_j = float(C.d["amb_sec"][jj])
            i0f = np.asarray(C.pi0(xq), float)
            i0l = loo(xq)
            if i0l is None:
                continue
            i0l = np.asarray(i0l, float)
            omf, oml = C.omr(sec_j), C.omr(sec_j, keepR)
            a_full = C.alpha(jj, i0f, omf)
            T, P = float(C.d["amb_T"][jj]), float(C.d["amb_P"][jj])
            if seed is None or seed_per_bin:
                seed = C.fit.seed(a_full, T, P)[:2]
                n_seed += 1
            sh, sq = seed
            a_i0 = C.alpha(jj, i0l, omf)
            a_rt = C.alpha(jj, i0f, oml)
            a_tri = C.alpha(jj, i0l, oml)
            # 상자고착을 **버리지 않고 표시**한다. 버리면 "섭동이 핏을 상자 끝까지
            # 민 빈" 만 골라 빠지는데 그게 바로 응답이 가장 큰 빈이다 — 예산이 제
            # 배제규칙에 의해 위에서 잘린다. §5(경계고착은 수렴이 아니다)는 본문
            # 값에서 빼는 것으로 지키고, 뺀 전후를 같은 런에서 둘 다 낸다.
            fits, bnd = {}, {}
            for nm, aa, ee in (("base", a_full, OPERATIONAL_EF), ("i0", a_i0, OPERATIONAL_EF),
                               ("rt", a_rt, OPERATIONAL_EF),
                               ("ef", a_full, C.fit.ch.detect(a_full)),
                               ("tri", a_tri, C.fit.ch.detect(a_tri))):
                f = C.fit.fit(aa, T, P, (sh, sq), ee)
                if not np.isfinite(f[tgt]):
                    fits = None
                    break
                fits[nm] = f
                bnd[nm] = bool(f["_at_bound"])
            if fits is None:
                n_bad += 1
                continue
            for nm, hit in bnd.items():
                n_bound[nm] += int(hit)
            b = fits["base"]
            recs.append((sec_j, float(not any(bnd.values())), b[tgt], b["_shift"],
                         C.amp(jj, i0f, inwin))
                        + tuple(fits[c][tgt] - b[tgt] for c in KEYS)
                        + tuple(fits[c]["_shift"] - b["_shift"] for c in KEYS))
    return recs, n_bad, n_bound, n_seed


def run_channel(C, args, tag):
    """빈마다 하나의 응답 → 시계열. 반환 dict[key] = (sec, 값배열)."""
    nk = len(C.za_x)
    knot_of = np.clip(np.searchsorted(C.za_x, C.ax), 1, nk - 1)
    left = np.abs(C.ax - C.za_x[knot_of - 1]) < np.abs(C.ax - C.za_x[np.minimum(knot_of, nk - 1)])
    knot_of = np.where(left, knot_of - 1, knot_of)
    # --limit 은 **균등 간격 표본**이어야 한다. 앞에서 N개를 자르면 캠페인 앞
    # 몇 시간(knot 7개)만 보게 되고, 그 구간이 대표적이라는 보장이 전혀 없다
    # (실측: 앞 400빈은 ANs shift 중앙 −6.6 px 로 전체 −5.2 와 딴판이었다).
    stride = max(1, len(C.ax) // args.limit) if args.limit else 1
    by_knot = {}
    for jj in range(0, len(C.ax), stride):
        k = int(knot_of[jj])
        if k <= 0 or k >= nk - 1:
            continue
        sec_k = float(C.d["za_sec"][k])
        kr = int(np.argmin(np.abs(C.rks - sec_k)))
        if not (0 < kr < len(C.rks) - 1) or abs(C.rks[kr] - sec_k) > 3600:
            continue
        by_knot.setdefault((k, kr), []).append(jj)
    work = [(k, kr, js) for (k, kr), js in sorted(by_knot.items())]

    nw = max(1, min(args.jobs or max_workers(), len(work)))
    if nw > 1:
        # 워커가 각자 BLAS 스레드를 띄우면 코어를 서로 뺏는다(실측: 워커당
        # CPU 85% 중 절반이 스핀). 자식은 spawn 시점에 물려받으므로 여기서
        # 박아야 먹는다 — 부모는 이미 numpy 를 import 했으니 안 바뀐다.
        for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            os.environ.setdefault(_v, "1")
        # knot 을 라운드로빈으로 흩는다 — knot 마다 빈 수가 달라서 앞뒤로 자르면
        # 워커 하나가 꼬리를 혼자 뒤집어쓴다.
        chunks = [work[i::nw] for i in range(nw)]
        spec = dict(cache=C.src_cache, rt=C.src_rt, cfg=C.src_cfg, e_f=C.src_ef,
                    step_limit=C.src_step, seed_per_bin=bool(args.seed_per_bin))
        parts = []
        with cf.ProcessPoolExecutor(max_workers=nw, initializer=_init_worker,
                                    initargs=(spec,)) as ex:
            for r in ex.map(_scan_chunk, chunks):
                parts.append(r)
    else:
        parts = [_scan(C, bool(args.seed_per_bin), work)]

    recs, n_bad, n_seed = [], 0, 0
    n_bound = {k: 0 for k in ("base",) + KEYS}
    for r, nb, nbd, ns in parts:
        recs.extend(r)
        n_bad += nb
        n_seed += ns
        for k in n_bound:
            n_bound[k] += nbd[k]
    # 워커 순서에 결과가 달라지면 안 된다 — 시각으로 정렬해 확정한다.
    recs.sort(key=lambda t: t[0])
    M = np.asarray(recs, float) if recs else np.zeros((0, 13))
    secs = M[:, 0]
    oks = M[:, 1] > 0.5
    base_no2 = M[:, 2]
    shifts = M[:, 3]
    amps = M[:, 4]
    out = {c: M[:, 5 + i] for i, c in enumerate(KEYS)}
    ds = {c: M[:, 9 + i] for i, c in enumerate(KEYS)}
    print(f"  [{tag}] 워커 {nw} · knot {len(work)}")
    sec = np.asarray(secs, float)
    ok = np.asarray(oks, bool)
    dsa = {c: np.asarray(ds[c], float) for c in KEYS}
    dmax = max(float(np.max(np.abs(v))) for v in dsa.values()) if len(sec) else np.nan
    print(f"  [{tag}] 빈 {len(C.ax)} 중 사용 {len(sec)} · 비수렴(NaN) {n_bad} · "
          f"시드 {n_seed}회 · base NO2 중앙 {np.median(base_no2):.3f} ppb · "
          f"shift 중앙 {np.median(shifts):+.3f} px · 섭동이 shift 를 움직인 최대 "
          f"{dmax:.4f} px")
    print("       상자고착: 빈 %d/%d (%.1f%%) · 항별 %s"
          % ((~ok).sum(), len(ok), 100.0 * (~ok).sum() / max(len(ok), 1),
             " ".join("%s %d" % (k, n_bound[k]) for k in ("base",) + KEYS)))
    return dict(sec=sec, v={c: np.asarray(out[c], float) for c in KEYS},
                ds=dsa, ok=ok, amp=np.asarray(amps, float),
                n2=np.asarray(base_no2, float))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fitset", required=True)
    ap.add_argument("--cache-a", default=os.path.join(_HERE, "_cache_hot_ANs_op.npz"))
    ap.add_argument("--cache-b", default=os.path.join(_HERE, "_cache_hot_PNs_op.npz"))
    ap.add_argument("--rt-a", default="C:/Doasis_Work/Output/R/R_CH1.npz")
    ap.add_argument("--rt-b", default="C:/Doasis_Work/Output/R/R_CH2.npz")
    ap.add_argument("--key-a", default="1")
    ap.add_argument("--key-b", default="2")
    ap.add_argument("--ef-a", type=float, default=0.1594)
    ap.add_argument("--ef-b", type=float, default=0.1368)
    ap.add_argument("--step-limit", type=float, default=3.0)
    ap.add_argument("--ceiling-ppb", type=float, default=0.0832)
    ap.add_argument("--seed-per-bin", action="store_true",
                    help="빈마다 격자 시딩(60배 느림). 기본은 knot 당 1회 공유 — 표본 검증용")
    ap.add_argument("--limit", type=int, help="빈 수 상한(빠른 확인용)")
    ap.add_argument("--jobs", type=int, default=0,
                    help="병렬 워커 수(0=core/parallel.max_workers). 워커마다 npz "
                         "~350 MB 를 따로 든다 — 메모리 모자라면 줄여라")
    ap.add_argument("--out", default=os.path.join(_HERE, "production_budget.csv"))
    args = ap.parse_args()

    ch = json.load(open(args.fitset, encoding="utf-8"))["channels"]
    print("[생산 런] 전 빈 전파 · scale 은 마지막 한 번 · 가중=빈(=스캔) 단위")
    A = Chan(args.cache_a, args.rt_a, ch[args.key_a], args.ef_a, args.step_limit)
    B = Chan(args.cache_b, args.rt_b, ch[args.key_b], args.ef_b, args.step_limit)
    RA = run_channel(A, args, "ANs")
    RB = run_channel(B, args, "PNs")
    sa, va, ampa = RA["sec"], RA["v"], RA["amp"]
    sb, vb, ampb = RB["sec"], RB["v"], RB["amp"]

    common, ia, ib = np.intersect1d(np.round(sa, 3), np.round(sb, 3), return_indices=True)
    print(f"  두 채널 공통 빈 {len(common)}")
    vs = {c: vb[c][ib] - va[c][ia] for c in va}
    oka, okb = RA["ok"], RB["ok"]
    oks = oka[ia] & okb[ib]
    # ΣANs 의 Δshift 는 두 채널 중 큰 쪽 — 어느 채널이든 분지가 넘어가면 오염이다
    dss = {c: np.maximum(np.abs(RA["ds"][c][ia]), np.abs(RB["ds"][c][ib])) for c in vs}

    msd = lambda x: rsd(x) / max(np.std(np.asarray(x, float), ddof=1), 1e-30)

    def table(lbl, ma, mb, ms):
        print()
        print("[%s]  n: ANs %d · PNs %d · ΣANs %d" % (lbl, ma.sum(), mb.sum(), ms.sum()))
        print("%-9s %9s %9s %9s %11s %10s %10s %9s"
              % ("", "i0", "rt", "ef", "스캔별합", "3중", "제곱합", "SD(3중)"))
        got = {}
        for nm, v0, m in (("ANs채널", va, ma), ("PNs채널", vb, mb), ("ΣANs", vs, ms)):
            v = {c: v0[c][m] for c in v0}
            ssum = v["i0"] + v["rt"] + v["ef"]
            quad = float(np.sqrt(rsd(v["i0"]) ** 2 + rsd(v["rt"]) ** 2 + rsd(v["ef"]) ** 2))
            print("%-9s %9.4f %9.4f %9.4f %11.4f %10.4f %10.4f %9.4f" % (
                nm, rsd(v["i0"]), rsd(v["rt"]), rsd(v["ef"]), rsd(ssum), rsd(v["tri"]),
                quad, np.std(v["tri"], ddof=1)))
            res = v["tri"] - ssum
            print("          가법성 잔차 rSD %.5f = 3중의 %.1f%%  ·  **3중/제곱합 %.3f**" % (
                rsd(res), 100 * rsd(res) / max(rsd(v["tri"]), 1e-12),
                rsd(v["tri"]) / max(quad, 1e-12)))
            print("          정규화 MAD/SD (가우스=1.000):  i0 %.3f · rt %.3f · ef %.3f · 3중 %.3f"
                  % (msd(v["i0"]), msd(v["rt"]), msd(v["ef"]), msd(v["tri"])))
            got[nm] = rsd(v["tri"])
        print("  ΣANs 3중 %.4f ppb · 관측 게이트 %.4f 대비 **%.2f배** (rSD 대 rSD)"
              % (got["ΣANs"], args.ceiling_ppb, got["ΣANs"] / args.ceiling_ppb))
        return got["ΣANs"]

    all_a = np.ones(len(sa), bool)
    all_b = np.ones(len(sb), bool)
    all_s = np.ones(len(common), bool)
    tri_lax = table("각주: 상자고착 포함", all_a, all_b, all_s)
    tri = table("본문: 상자고착 제외 (§5 규칙)", oka, okb, oks)
    print()
    print("  고착 제외의 효과: ΣANs 3중 %.4f → %.4f ppb (%+.1f%%)"
          % (tri_lax, tri, 100.0 * (tri / max(tri_lax, 1e-12) - 1.0)))
    print("  두 채널 3중응답 상관 r=%+.3f"
          % np.corrcoef(va["tri"][ia][oks], vb["tri"][ib][oks])[0, 1])

    # ── Δshift 구간별 분해: 보간오차의 전파인가, 분지 전환인가 ──
    print()
    print("[Δshift 분해] ΣANs 3중 응답을 |Δshift| 로 층화 (고착 제외 후)")
    print("%-24s %7s %7s %10s %10s %11s" % ("구간", "n", "비율%", "rSD", "SD", "분산기여%"))
    dt, vt = dss["tri"][oks], vs["tri"][oks]
    tot = float(np.sum((vt - np.median(vt)) ** 2))
    for lo, hi, lbl in ((0.0, 0.1, "|dshift| < 0.1 px"),
                        (0.1, 1.0, "0.1 <= |dshift| < 1 px"),
                        (1.0, np.inf, "|dshift| >= 1 px")):
        m = (dt >= lo) & (dt < hi)
        if m.sum() < 2:
            print("%-24s %7d %7.1f %10s %10s %11s"
                  % (lbl, m.sum(), 100.0 * m.sum() / max(len(dt), 1), "-", "-", "-"))
            continue
        cv = float(np.sum((vt[m] - np.median(vt)) ** 2))
        print("%-24s %7d %7.1f %10.4f %10.4f %11.1f"
              % (lbl, m.sum(), 100.0 * m.sum() / len(dt), rsd(vt[m]),
                 np.std(vt[m], ddof=1), 100.0 * cv / max(tot, 1e-30)))
    print("  |dshift| 분위: p50 %.4f · p90 %.4f · p99 %.4f · max %.4f px"
          % tuple(np.percentile(dt, [50, 90, 99, 100])))

    # ── §6.1 대리변수: 증폭 vs |응답| ──
    print()
    print("[대리변수] |응답| ≈ c · |I0/(I0−I)| 의 c 와 잔차 (항별·채널별)")
    print("%-8s %-4s %8s %11s %8s %11s %9s %9s %8s"
          % ("채널", "항", "r", "기울기 c", "R²", "잔차/중앙", "Spearman", "logslope", "logR2"))
    for nm, v0, am0 in (("ANs", va, ampa), ("PNs", vb, ampb)):
        km = oka if nm == "ANs" else okb
        v = {c: v0[c][km] for c in v0}
        am = am0[km]
        for c in ("i0", "rt", "ef", "tri"):
            x, y = np.asarray(am, float), np.abs(v[c])
            m = np.isfinite(x) & np.isfinite(y) & (x > 0)
            if m.sum() < 20:
                continue
            r = float(np.corrcoef(x[m], y[m])[0, 1])
            sl = float(np.polyfit(x[m], y[m], 1)[0])
            res = y[m] - sl * x[m]
            # 증폭(9~350)도 응답(MAD/SD 0.27)도 꼬리가 무겁다 — Pearson 은 극단값
            # 몇 개가 정한다. Spearman 과 로그공간 멱함수로 같이 본다.
            mm = m & (y > 0)
            if mm.sum() >= 20:
                rs = float(stats.spearmanr(x[mm], y[mm]).statistic)
                lx, ly = np.log(x[mm]), np.log(y[mm])
                bslope = float(np.polyfit(lx, ly, 1)[0])
                r2l = float(np.corrcoef(lx, ly)[0, 1] ** 2)
            else:
                rs = bslope = r2l = np.nan
            print("%-8s %-4s %+8.3f %11.3e %8.3f %11.2f %+9.3f %9.3f %8.3f"
                  % (nm, c, r, sl, r * r, rsd(res) / max(np.median(y[m]), 1e-12),
                     rs, bslope, r2l))

    # ── §4.5: 전파 ΣANs 를 제품 해상도로, 그리고 게이트 연산자로 ──
    ct, vt45 = common[oks], vs["tri"][oks]
    hh = np.floor(ct / 3600.0).astype(np.int64)
    u, inv = np.unique(hh, return_inverse=True)
    cnt = np.bincount(inv)
    hm = np.bincount(inv, weights=vt45) / np.maximum(cnt, 1)
    keep = cnt >= 8
    uh, hv = u[keep], hm[keep]
    cons = np.diff(uh) == 1
    print()
    print("[§4.5] 전파 ΣANs")
    print("  제품 해상도(빈): n=%d · rSD %.4f · SD %.4f · 정규화 MAD/SD %.3f"
          % (len(vt45), rsd(vt45), np.std(vt45, ddof=1),
             rsd(vt45) / max(np.std(vt45, ddof=1), 1e-30)))
    if int(cons.sum()) > 10:
        dd = np.abs(np.diff(hv))[cons]
        ge = 1.4826 * np.median(dd) / np.sqrt(2)
        print("  시간평균: n=%d · 연속쌍 %d · median|Δ_1h| %.4f · 게이트추정량 %.4f ppb"
              % (len(hv), int(cons.sum()), np.median(dd), ge))
        print("  → 관측 게이트 %.4f 대비 **%.2f배**" % (args.ceiling_ppb, ge / args.ceiling_ppb))
        np.savetxt(args.out.replace(".csv", "_hourly.csv"),
                   np.column_stack([uh, hv]), delimiter=",", fmt="%.8g",
                   header="hour_year2026,SigmaANs_triple_response_ppb")
    else:
        print("  시간평균 연속쌍 %d개뿐 — 표본이 좁다(ABSTAIN)" % int(cons.sum()))

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("sec,ok,n2_a,n2_b,amp_a,amp_b,a_i0,a_rt,a_ef,a_tri,b_i0,b_rt,b_ef,b_tri,"
                 "s_i0,s_rt,s_ef,s_tri,ds_i0,ds_rt,ds_ef,ds_tri\n")
        for n in range(len(common)):
            fh.write(",".join("%.6g" % x for x in (
                common[n], int(oks[n]), RA["n2"][ia[n]], RB["n2"][ib[n]],
                ampa[ia[n]], ampb[ib[n]],
                va["i0"][ia[n]], va["rt"][ia[n]], va["ef"][ia[n]], va["tri"][ia[n]],
                vb["i0"][ib[n]], vb["rt"][ib[n]], vb["ef"][ib[n]], vb["tri"][ib[n]],
                vs["i0"][n], vs["rt"][n], vs["ef"][n], vs["tri"][n],
                dss["i0"][n], dss["rt"][n], dss["ef"][n], dss["tri"][n])) + "\n")
    print(f"→ {args.out}  ({len(common)} rows)  [빈별 증폭·응답 쌍 포함]")


if __name__ == "__main__":
    main()
