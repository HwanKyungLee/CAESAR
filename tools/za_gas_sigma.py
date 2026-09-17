#!/usr/bin/env python
"""tools/za_gas_sigma.py — 제로에어 스캔을 핏해서 **기체별 노이즈 sigma** 를 ppb 로 낸다.

`tools/temporal_noise.py` 는 ambient 인접스캔 차분이라 실제 대기 변동이 섞여 sigma 의
**상한**밖에 못 냈다. 제로에어는 같은 기체를 반복 측정하므로 참값이 0 이고, 핏 결과의
산포가 곧 기기+검색 노이즈다 = **하한**. 둘 사이가 진짜 값이다.

왜 문턱에 필요한가 — 파이프라인은 이미 `MDL = 3.0 * ppb_err`(gui/worker.py)를 내는데,
그 `ppb_err` 은 핏이 자기 공분산으로 낸 값이라 실측 반복성과 기체마다 다르게 어긋난다.
`k * sigma` 구조는 이미 있으니 **sigma 를 실측으로 갈아끼우는 것**이 할 일이다.

설정은 짐작하지 않는다 — **생산 fitset JSON 이 단일 출처**다:
`C:/Doasis_Work/Output/fit setting/FitSet_*.json` 의 `channels[<key>]` 에서 창·차수·
레퍼런스 경로·ref_props·step_limit 을 그대로 읽는다. 짐작하면 자릿수로 틀린다
(실측: 창을 435-480nm/poly4 로 잘못 잡으면 NO2 가 49배, CHOCHO 5300배).
`.bak_20260722_labelswap` 이 붙은 판본이 2026-07-22 채널 라벨 교체 **이전** 것이고,
2026-09 교차검증(2026-07-09 생성)은 그쪽 설정이다.

절대 스케일 (R 을 다시 계산하지 않고):
    alpha_prod = s(lambda) * q + c(lambda),   q = I_ZA/I - 1
  생산 알파와 raw 의 q 를 같은 60초 빈으로 짝지어 **회귀 기울기** s(lambda) 를 얻는다.
  Rayleigh 차는 q 와 무관한 덧셈 항이라 절편 c 로 빠진다 - 평균의 비로 잡으면 파일마다
  값이 튀고 부호까지 뒤집힌다(실측). ZA 는 같은 기체·같은 T/P 라 c 가 상쇄되므로
  alpha_za = s * q_za 로 충분하다.

**검증 (--validate)**: 생산 알파를 그대로 핏해 같은 파일·같은 행 번호의 생산 결과와
스캔별로 대조한다. 생산 `File` 열이 `<trace>.dat [0000]` 이라 정확히 짝지어진다.
**전체 기간 중앙값끼리 비교하면 안 된다** - 대기가 변하므로 다른 모집단을 견주는 꼴이고,
실제로 그렇게 비교했다가 "재현 실패(0.72배)"로 잘못 판단했다. 같은 스캔끼리 짝지으면
NO2 0.967배·상관 1.000 으로 재현된다.

**절대값 경고 (2026-09-17) — sigma 의 "배수"를 그대로 쓰지 말 것.**

방법 자체는 검증됐다. ZA 알파에 알려진 NO2 를 주입하면 99.7~100.3% 로 되찾히고
(편향 < 0.007 ppb), 회수 sigma 가 주입 농도와 무관하게 일정하다(0.1068 @ 0/0.2/0.6/
2/5 ppb). 즉 "락온할 신호가 없어서 sigma 가 부풀었다"는 의심은 반증됐고, 자유
파라미터를 맞춘 것이 아니므로 과적합도 아니다(참값 0 은 외부 진실이다).

**그런데 절대 스케일 앵커가 4배 폭으로 불안정하다.** 같은 날 13블록을 나눠 pooled
회귀하면 2.114e-07 / 2.627e-07 / 8.618e-07 (전체 5.588e-07) 이 나온다 - 모아도
수렴하지 않으니 노이즈가 아니라 시간대별 계통 차이다. sigma 는 스케일에 정비례하므로
**sigma 와 perr 대비 배수도 같은 4배 폭을 그대로 물려받는다.**

원인은 회귀 가정이다: alpha = s*q + c 에서 c(Rayleigh 차)를 빈 사이 상수로 뒀는데,
c 는 T/P 를 따라 일주기로 변하고 q 도 일주기로 변한다 - 둘이 상관되면 기울기가 c 를
일부 먹는다. **고치는 길은 빌리지 말고 물리로 계산하는 것**이다:
    s = RL * [(1-R)/d + alpha_ZA_Ray]
R 은 He 인젝션(flag 510, 3시간마다)에서, d=51.8cm·RL 은 fitset 에서, alpha_ZA_Ray 는
core/physics.py 에서 나온다. 전부 있고 전부 안정적이다. 그때까지 이 도구의 sigma 는
**상대 비교(기체 간·블록 간)에만** 쓰고 절대 문턱으로 쓰지 말 것.

사용:
    python tools/za_gas_sigma.py --raw <raw.dat> [...] --alpha-dir <알파 폴더>
        --fitset "<FitSet_*.json>" --ch-key 2 --block PNs
        [--validate <production_result.dat>] [--max-amb 40]
"""
import argparse
import glob
import json
import os
import re
import sys

import numpy as np
from scipy.interpolate import interp1d

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.raw_parser import RawParser, FLAG_ZA, FLAG_AMBIENT
from core.engine import UniversalEngine
from core.doas_fit import DoasFitter
from core.physics import air_number_density


def _col(path):
    return np.array([float(l) for l in open(path, encoding="utf-8", errors="replace")
                     if l.strip() and not l.lstrip().startswith("#")])


def load_fitset(path, ch_key):
    """생산 fitset 의 한 채널 설정. 없는 키면 바로 죽는다 - 기본값을 지어내지 않는다."""
    ch = json.load(open(path, encoding="utf-8"))["channels"]
    if str(ch_key) not in ch:
        raise KeyError("fitset 에 채널 %r 없음 (있는 키: %s)" % (ch_key, list(ch)))
    return ch[str(ch_key)]


def read_alpha_trace(path):
    """생산 알파 트레이스 -> (wavelength_nm, row_idx, alpha 행렬, T_C, P_mbar)."""
    wave, hdr, rows = None, None, []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("# wavelength_nm"):
                wave = np.array([float(v) for v in line.split(":", 1)[1].split()])
                continue
            if line.startswith("#"):
                continue
            t = line.rstrip(chr(10)).split(chr(9))
            if t and t[0] == "row_idx":
                hdr = t
                continue
            if hdr:
                rows.append(t)
    if wave is None or hdr is None or not rows:
        raise ValueError(os.path.basename(path) + ": 알파 트레이스 형식이 아니다")
    p0 = hdr.index("px0")
    ri = np.array([int(float(r[0])) for r in rows])
    A = np.array([[float(v) if v not in ("", "nan") else np.nan for v in r[p0:]]
                  for r in rows], dtype=float)
    iT, iP = hdr.index("T_C"), hdr.index("P_mbar")
    T = float(np.nanmedian([float(r[iT]) for r in rows]))
    P = float(np.nanmedian([float(r[iP]) for r in rows]))
    return wave, ri, A, T, P


def build_engine(cfg, wave):
    """fitset 의 refs 를 그 채널 wavecal 격자에서 알파 파장축으로 리샘플해 등록."""
    calib = _col(cfg["wl_path"])
    eng = UniversalEngine()
    eng.set_wavelength_axis(wave)
    for r in cfg["refs"]:
        if not r.get("path") or not os.path.exists(r["path"]):
            continue
        v = _col(r["path"])
        n = min(len(v), len(calib))
        res = interp1d(calib[:n], v[:n], kind="cubic",
                       bounds_error=False, fill_value="extrapolate")(wave)
        eng.raw_references[r["name"]] = res
        eng.interpolators[r["name"]] = interp1d(np.arange(len(res)), res, kind="cubic",
                                                fill_value="extrapolate")
        eng.scaling_factors[r["name"]] = float(np.max(np.abs(res))) or 1.0
        eng.multipliers[r["name"]] = 1.0
        if r["name"] not in eng.gas_list:
            eng.gas_list.append(r["name"])
    eng.apply_ils_convolution(0.0)          # fitset 단면은 이미 ILS 적용본
    return eng


class Fitter:
    """fitset 설정을 고정해 두고 알파 하나씩 핏하는 얇은 래퍼."""

    def __init__(self, cfg, wave):
        self.cfg, self.wave = cfg, wave
        self.eng = build_engine(cfg, wave)
        self.f = DoasFitter(self.eng)
        inw = (wave >= cfg["fit_start_nm"]) & (wave <= cfg["fit_end_nm"])
        idx = np.where(inw)[0]
        if len(idx) < 50:
            raise ValueError("핏 창이 알파 파장축과 거의 안 겹친다 - 채널/ roi 확인")
        self.sl = slice(int(idx[0]), int(idx[-1]) + 1)
        self.inw = inw
        wax = np.asarray(self.eng._wave_axis, float).ravel()
        self.vp = np.asarray(interp1d(wax, np.arange(len(wax)), bounds_error=False,
                                      fill_value="extrapolate")(wave[self.sl]), float)

    def fit(self, alpha, T_C, P_mbar):
        c, a = self.cfg, np.asarray(alpha, float)[self.sl]
        ef = self.f.detect_etalon_frequency(self.vp, a, c["poly_deg"], 0.02, 0.40)
        act, fx, lk, t0, lb, ub = self.f.setup_fit_parameters(
            c["ref_props"], 0.0, [0.0, 1.0], c["step_limit"])
        o = self.f.execute_varpro_fit(
            self.vp, a, np.ones(len(a)), act, fx, lk, t0, lb, ub, c["poly_deg"], ef,
            self.vp[len(self.vp) // 2], 1.0, c["ref_props"], T_C,
            c.get("tikhonov_lambda", 0.0), c.get("use_robust", False),
            allow_negative_gas=True)          # 생산 헤더: Allow Negative Gas ON
        full = self.eng.get_model_components(self.vp, o[0], o[1], o[2], o[3],
                                             etalon_amp=o[4], etalon_freq=ef,
                                             etalon_phase=o[5])[0]
        na = air_number_density(T_C, P_mbar)
        out = {g: float(o[2][i] / self.eng.scaling_factors[g] / na * 1e9)
               for i, g in enumerate(self.eng.gas_list)}
        out["_rms"] = float(np.sqrt(np.mean((a - full) ** 2)))
        return out


def load_production(result_dat, trace_stem):
    """생산 결과에서 `<trace_stem>...dat [NNNN]` 행만 행번호 순으로."""
    cols, rows = None, {}
    with open(result_dat, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            t = line.rstrip(chr(10)).split(chr(9))
            if cols is None:
                cols = t
                continue
            f = t[cols.index("File")] if "File" in cols else ""
            if not f.startswith(trace_stem):
                continue
            m = re.search(r"\[(\d+)\]", f)
            if m:
                rows[int(m.group(1))] = dict(zip(cols, t))
    return rows


def validate(fitter, A, T, P, result_dat, trace_stem, tol=0.25):
    """생산 알파를 그대로 핏해 **같은 파일·같은 행 번호**의 생산 값과 대조.

    전체 기간 중앙값끼리 비교하면 안 된다 - 대기가 변하므로 다른 모집단을 견주는 꼴이다.
    """
    prod = load_production(result_dat, trace_stem)
    if not prod:
        print("  [validate] 생산 결과에 %s 행이 없다 - 건너뜀" % trace_stem)
        return True
    ks = sorted(k for k in prod if k < len(A))
    mine = {k: fitter.fit(A[k], T, P) for k in ks}
    ok = True
    print("  [validate] %d 스캔 대조 (같은 파일·같은 행 번호)" % len(ks))
    for g in list(fitter.eng.gas_list) + ["RMS"]:
        key = "_rms" if g == "RMS" else g
        mv = np.array([mine[k][key] for k in ks], float)
        pv = np.array([float(prod[k].get(g, "nan") or "nan") for k in ks], float)
        m = np.isfinite(mv) & np.isfinite(pv)
        if m.sum() < 5:
            continue
        ratio = float(np.median(mv[m]) / np.median(pv[m])) if np.median(pv[m]) else float("nan")
        corr = float(np.corrcoef(mv[m], pv[m])[0, 1]) if np.std(pv[m]) > 0 else float("nan")
        bad = not (abs(ratio - 1.0) <= tol)
        ok = ok and not bad
        print("     %-8s ratio=%6.3f  corr=%6.3f %s" % (g, ratio, corr, "  <-- 벗어남" if bad else ""))
    return ok


def matched_bins(A, ri, q_amb, amb_idx):
    """생산 알파 행과 같은 60초 빈의 raw q 평균을 짝지어 (Q, Y) 로 낸다.

    회귀는 **하루치를 모아 한 번에** 한다. 한 블록(약 59빈)만으로는 q 의 분산이 작아
    기울기가 불안정하고(실측: 블록마다 2.4배 폭, 한 블록은 부호까지 음수), 그 흔들림이
    ZA 알파에 그대로 실려 sigma 를 부풀린다. s = RL*[(1-R)/d + alpha_Ray] 는 하루 안에
    거의 안 변하는 양이라 모아서 추정하는 편이 물리적으로도 맞다.
    """
    qbar = np.full((len(ri), q_amb.shape[1]), np.nan)
    bounds = list(ri) + [(amb_idx[-1] + 1) if amb_idx else 0]
    pos = {r: k for k, r in enumerate(amb_idx)}
    for k in range(len(ri)):
        sel = [pos[r] for r in range(bounds[k], bounds[k + 1]) if r in pos]
        if sel:
            qbar[k] = np.nanmean(q_amb[sel], axis=0)
    good = np.isfinite(qbar).all(axis=1) & np.isfinite(A).all(axis=1)
    if good.sum() < 8:
        return None
    return qbar[good], A[good]


def fit_scale(pairs):
    """모은 (Q, Y) 들로 픽셀별 기울기 s(lambda)."""
    Q = np.concatenate([q for q, _ in pairs], axis=0)
    Y = np.concatenate([y for _, y in pairs], axis=0)
    Qc, Yc = Q - Q.mean(axis=0), Y - Y.mean(axis=0)
    return (Qc * Yc).sum(axis=0) / np.maximum((Qc * Qc).sum(axis=0), 1e-300)


def run(raw_files, alpha_dir, fitset, ch_key, block, max_amb, validate_against=None):
    cfg = load_fitset(fitset, ch_key)
    print("fitset: %s  %.1f-%.1fnm  poly=%d  step=%.2f  refs=%s"
          % (cfg.get("data_label"), cfg["fit_start_nm"], cfg["fit_end_nm"],
             cfg["poly_deg"], cfg["step_limit"], [r["name"] for r in cfg["refs"]]))
    fitter = None
    pending = []
    za_all, amb_all = [], []
    for rf in raw_files:
        stem = os.path.basename(rf).replace(".dat", "")
        hits = sorted(glob.glob(os.path.join(alpha_dir, stem + "_*alpha_trace.dat")))
        if not hits:
            print("  skip %s: 알파 트레이스 없음" % stem)
            continue
        wave, ri, A, T, P = read_alpha_trace(hits[0])
        if fitter is None:
            fitter = Fitter(cfg, wave)
            print("  engine gases=%s  window=%dpx" % (fitter.eng.gas_list,
                                                      fitter.sl.stop - fitter.sl.start))
            if validate_against and not validate(fitter, A, T, P, validate_against,
                                                 os.path.basename(hits[0])):
                print("\n[중단] 생산 재현 실패 - sigma 를 내지 않는다.")
                return None
        p = RawParser(rf)
        if block not in p.layout.spec_blocks:
            raise KeyError("%s: 블록 %s 없음" % (stem, block))
        za, amb, amb_idx = [], [], []
        for row, sp in p.iter_rows_with_spectra((block,)):
            s = sp.get(block)
            if s is None:
                continue
            if row.flag == FLAG_ZA:
                za.append(s)
            elif row.flag == FLAG_AMBIENT:
                amb.append(s)
                amb_idx.append(int(row.row_idx))
        if len(za) < 10 or len(amb) < 50:
            print("  skip %s: ZA=%d amb=%d" % (stem, len(za), len(amb)))
            continue
        za, amb = np.asarray(za, float), np.asarray(amb, float)
        off = int(np.argmin(np.abs(_col(cfg["wl_path"]) - wave[0])))
        win = slice(off, off + len(wave))
        I0 = za[:, win].mean(axis=0)
        g = I0 > 0
        q_amb = np.where(g, I0 / np.maximum(amb[:, win], 1e-30) - 1.0, np.nan)
        mb = matched_bins(A, ri, q_amb, amb_idx)
        if mb is None:
            print("  skip %s: 짝지은 빈 부족" % stem)
            continue
        q_za = np.where(g, I0 / np.maximum(za[:, win], 1e-30) - 1.0, np.nan)
        step = max(1, len(amb) // max_amb)
        pending.append((stem[-3:], mb, q_za, q_amb[::step][:max_amb], T, P))
        print("  %s: ZA %d, amb %d, 짝지은 빈 %d"
              % (stem[-3:], len(q_za), min(max_amb, len(q_amb[::step])), len(mb[0])))

    # 하루치를 모아 스케일 한 번 추정 (이유는 matched_bins 참고).
    if pending:
        s_lam = fit_scale([mb for _, mb, _, _, _, _ in pending])
        sc = float(np.nanmedian(s_lam[fitter.inw]))
        print("  pooled scale med=%.4g cm^-1  (빈 %d개)"
              % (sc, sum(len(mb[0]) for _, mb, _, _, _, _ in pending)))
        if not np.isfinite(sc) or sc <= 0:
            print(chr(10) + "[중단] 스케일이 비정상 - sigma 를 내지 않는다.")
            return None
        for tag, _, q_za, q_amb_s, T, P in pending:
            za_all += [fitter.fit(q * s_lam, T, P) for q in q_za]
            amb_all += [fitter.fit(q * s_lam, T, P) for q in q_amb_s]

    if not za_all:
        print("분석할 ZA 가 없다.")
        return None
    print("\n%8s%14s%14s%14s%12s" % ("gas", "ZA bias", "ZA sigma", "amb median", "MDL 3sig"))
    out = []
    for g in fitter.eng.gas_list:
        z = np.array([x[g] for x in za_all], float)
        a = np.array([x[g] for x in amb_all], float)
        z, a = z[np.isfinite(z)], a[np.isfinite(a)]
        if len(z) < 5:
            continue
        s = float(np.std(z, ddof=1))
        out.append((g, float(np.mean(z)), s, float(np.median(np.abs(a)))))
        print("%8s%14.4g%14.4g%14.4g%12.4g" % (g, np.mean(z), s, np.median(np.abs(a)), 3 * s))
    print("\n(ZA 참값=0 이므로 bias 는 계통오차, sigma 가 노이즈. 한 ZA 블록 평균을 I0 로")
    print(" 쓰므로 블록 내 단기 노이즈다 - ZA 주기 사이 I0 드리프트는 빠져 있어 하한이다.)")
    return out


def main():
    ap = argparse.ArgumentParser(description="제로에어 핏 기반 기체별 노이즈 sigma")
    ap.add_argument('--raw', nargs='+', required=True)
    ap.add_argument('--alpha-dir', required=True)
    ap.add_argument('--fitset', required=True)
    ap.add_argument('--ch-key', default='2')
    ap.add_argument('--block', default='PNs')
    ap.add_argument('--max-amb', type=int, default=40)
    ap.add_argument('--validate', dest='validate_against')
    a = ap.parse_args()
    run(sorted(a.raw), a.alpha_dir, a.fitset, a.ch_key, a.block,
        a.max_amb, a.validate_against)


if __name__ == '__main__':
    main()
