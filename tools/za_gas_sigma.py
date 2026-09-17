#!/usr/bin/env python
"""tools/za_gas_sigma.py — 제로에어 스캔을 실제로 핏해서 **기체별 노이즈 sigma** 를 낸다.

`tools/za_noise_floor.py` 는 노이즈를 상대세기(차분) 공간에서 냈다. 문턱을
`k * sigma` 로 세우려면 그게 **보고 단위(ppb)** 여야 한다. 그래서 여기서는 제로에어
스캔을 ambient 와 똑같이 핏한다 - 참값이 0 이므로 나온 농도의 산포가 곧 노이즈다.

절대 스케일을 어떻게 잡나 (R 을 다시 계산하지 않고):
    alpha = RL * [(1-R)/d + alpha_ZA_Ray] * (I_ZA/I - 1) - dRay
  ZA vs ZA 는 같은 기체·같은 T/P 라 Rayleigh 차가 0 이고 대괄호는 공통이다. 그 대괄호를
  유도하는 대신 **생산 알파 트레이스에서 실측**한다. 같은 raw 파일의 ambient 에 대해
    scale(lambda) = mean(alpha_production) / mean(I_ZA/I_amb - 1)
  분자는 파이프라인이 R·d·RL·Rayleigh 를 다 넣어 만든 값이고 분모는 raw 에서 바로
  나온다. 둘 다 같은 한 시간의 평균이라 비가 곧 대괄호다. 즉 **생산 경로를 단일
  출처로 삼아** 스케일을 빌린다(사본을 만들지 않는다).

주의 두 가지:
  · 한 ZA 블록의 평균을 I0 로 쓰므로 여기 sigma 는 **블록 내 단기 노이즈**다. ZA
    주기(1시간) 사이의 I0 드리프트는 안 들어간다 - 그건 za_noise_floor.py 가 따로 낸다.
    따라서 이 sigma 는 실제 ambient 오차의 **하한**이다.
  · 스케일은 파장에 따라 완만히 변하는데 스칼라(창 중앙값)로 쓴다. 완만한 성분은
    핏의 poly 항이 먹으므로 기체 계수에 주는 영향은 작지만 0 은 아니다.

**재현 상태 (2026-09-17) — 아직 쓰면 안 된다.**

sigma 를 믿으려면 같은 엔진이 **생산 농도를 재현**해야 한다. 생산 알파를 그대로
핏해서 2026-05-18 PNs 와 대조한 결과:

    설정                                   NO2      CHOCHO       H2O
    435-480nm / poly4 / Sh자유            48.9x     5300x       406x
    438.4-475.8nm / poly4 / Sh자유         1.8x       3.9x      0.79x
    444-471nm / poly3 / Sh[-0.5] Sq[0.0]  0.73x       2.2x      0.91x   <- 생산 설정
    (1.00x = 생산 재현)

창·차수·shift 를 헤더에서 읽어오자 49배가 0.73배까지 줄었다 — **설정을 짐작하면
자릿수로 틀린다**는 뜻이고, 그래서 `parse_settings()` 가 생산 결과 헤더를 단일
출처로 읽는다. 다만 아직 1.00x 가 아니다. 남은 차이는 CHOCHO 가 높고 NO2 가 낮은
**상쇄 패턴**이라 레퍼런스 판본/ILS 처리 차이로 보인다(생산은 시나리오의
`reference_data/raw/*` + mult 을 쓰고 여기서는 wv_cal 의 Dynamic-ILS-Applied 를 쓴다).

따라서 **이 도구가 내는 sigma 를 문턱 설정에 쓰지 말 것.** 재현이 1.00x 근처로
맞은 뒤에 쓰라. 자체검증(`tools/test_za_gas_sigma.py`)은 그래서 sigma 값이 아니라
설정 파서 같은 순수 함수만 건다 — 재현 안 된 숫자에 테스트를 걸면 틀린 값을
고정하는 셈이다.

사용:
    python tools/za_gas_sigma.py --raw <raw.dat> [...] --alpha-dir <알파트레이스 폴더>
                                 --refdir <wv_cal/roiN> --block PNs [--poly 3]
                                 [--nm 444,471] [--max-amb 40]
    설정은 손으로 넣지 말고 생산 결과 헤더에서 읽을 것:
        parse_settings("...augur_fit/pns_merge.dat", "(PNs)")
        -> {'nm': (444.0, 471.0), 'poly': 3, 'sh': -0.5, 'sq': 0.0}
"""
import argparse
import glob
import os
import sys

import re

import numpy as np
from scipy.interpolate import interp1d

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.raw_parser import RawParser, FLAG_ZA, FLAG_AMBIENT
from core.engine import UniversalEngine
from core.doas_fit import DoasFitter
from core.physics import air_number_density

REF_FILES = [("NO2", "Ref_NO2*"), ("CHOCHO", "Ref_CHOCHO*"), ("H2O", "Ref_H2O*")]

# scenarios/Doctor_Scenario_Cold_ROI1_ROI2.json 의 채널 ref_props 와 같은 정책
# (NO2 가 shift/squeeze 를 쥐고 나머지는 Link). 여기서 바꾸면 생산 핏과 달라진다.
REF_PROPS = {
    "NO2": {"sh_mode": "Limit", "sh_val": "-2.0, 2.0",
            "sq_mode": "Limit", "sq_val": "-0.02, 0.02", "t_ref": 25.0, "t_coeff": 0.0},
    "CHOCHO": {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2",
               "t_ref": 25.0, "t_coeff": 0.0},
    "H2O": {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2",
            "t_ref": 25.0, "t_coeff": 0.0},
}


def make_ref_props(sh, sq):
    """생산 헤더의 Sh/Sq 를 그대로 쓴다. None 이면 모듈 기본(자유 제한)."""
    if sh is None and sq is None:
        return dict(REF_PROPS)
    lead = {"sh_mode": "Fix", "sh_val": str(sh if sh is not None else 0.0),
            "sq_mode": "Fix", "sq_val": str(sq if sq is not None else 0.0),
            "t_ref": 25.0, "t_coeff": 0.0}
    link = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2",
            "t_ref": 25.0, "t_coeff": 0.0}
    return {"NO2": lead, "CHOCHO": dict(link), "H2O": dict(link)}


def _col(path):
    return np.array([float(l) for l in open(path, encoding="utf-8", errors="replace")
                     if l.strip() and not l.lstrip().startswith("#")])


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
            t = line.rstrip("\n").split("\t")
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


def build_engine(refdir, wave):
    """roi 의 Calib nm 격자에 있는 ILS 적용 단면을 알파 파장축으로 리샘플해 등록."""
    eng = UniversalEngine()
    eng.set_wavelength_axis(wave)
    calib = sorted(glob.glob(os.path.join(refdir, "Calib*.txt")))
    if not calib:
        raise FileNotFoundError(refdir + ": Calib*.txt 없음")
    calib_nm = _col(calib[0])
    for name, pat in REF_FILES:
        hits = sorted(glob.glob(os.path.join(refdir, pat)))
        if not hits:
            continue
        vals = _col(hits[0])
        n = min(len(vals), len(calib_nm))
        res = interp1d(calib_nm[:n], vals[:n], kind="cubic",
                       bounds_error=False, fill_value="extrapolate")(wave)
        eng.raw_references[name] = res
        eng.interpolators[name] = interp1d(np.arange(len(res)), res, kind="cubic",
                                           fill_value="extrapolate")
        eng.scaling_factors[name] = float(np.max(np.abs(res))) or 1.0
        eng.multipliers[name] = 1.0
        if name not in eng.gas_list:
            eng.gas_list.append(name)
    eng.apply_ils_convolution(0.0)          # 단면은 이미 ILS 적용됨
    return eng


def fit_alpha(eng, fitter, wave, alpha, sl, poly, T_C, P_mbar):
    """알파 하나 -> {gas: ppb}. tools/residual_compare.py 의 fit_one 과 같은 경로."""
    wl, a = wave[sl], alpha[sl]
    wax = np.asarray(eng._wave_axis, float).ravel()
    vp = np.asarray(interp1d(wax, np.arange(len(wax)), bounds_error=False,
                             fill_value="extrapolate")(wl), float)
    ef = fitter.detect_etalon_frequency(vp, a, poly, 0.02, 0.40)
    active, fixed, linked, t0, lb, ub = fitter.setup_fit_parameters(
        REF_PROPS, 0.0, [0.0, 1.0], 0.5)
    out = fitter.execute_varpro_fit(vp, a, np.ones(len(a)), active, fixed, linked,
                                    t0, lb, ub, poly, ef, vp[len(vp) // 2], 1.0,
                                    REF_PROPS, T_C, 0.0, False)
    gco = out[2]
    n_air = air_number_density(T_C, P_mbar)
    return {g: float(gco[i] * eng.multipliers.get(g, 1.0)
                     / eng.scaling_factors.get(g, 1.0) / n_air * 1e9)
            for i, g in enumerate(eng.gas_list)}


def parse_settings(result_dat, channel_label):
    """생산 결과 헤더에서 그 채널의 핏 설정을 읽는다 — **설정의 단일 출처**.

    `# Channel 2 (PNs) settings: 444-471nm_Poly3_ShLink` 와
    `# Reference Constraints: Sh[-0.5], Sq[0.0]` 를 그대로 쓴다. 이걸 손으로 짐작하면
    창·차수·shift 가 어긋나 농도가 자릿수로 틀린다(실측: 435-480nm/poly4 로 잘못 쓰면
    NO2 가 생산 대비 49배, CHOCHO 5300배).
    """
    out = {}
    with open(result_dat, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("#"):
                break
            if "settings:" in line and channel_label in line:
                tag = line.split("settings:")[1].split()[0]
                m = re.match(r"([\d.]+)-([\d.]+)nm_Poly(\d+)", tag)
                if m:
                    out["nm"] = (float(m.group(1)), float(m.group(2)))
                    out["poly"] = int(m.group(3))
            if "Reference Constraints:" in line:
                m = re.search(r"Sh\[([-\d.]+)\].*Sq\[([-\d.]+)\]", line)
                if m:
                    out["sh"], out["sq"] = float(m.group(1)), float(m.group(2))
    return out


def production_medians(result_dat, gases):
    """같은 결과 파일의 기체별 중앙값 — 검증 기준."""
    import csv
    cols, vals = None, {}
    with open(result_dat, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            t = line.rstrip(chr(10)).split(chr(9))
            if cols is None:
                cols = t
                vals = {g: [] for g in gases if g in cols}
                continue
            for g in vals:
                try:
                    v = float(t[cols.index(g)])
                except (ValueError, IndexError):
                    continue
                if np.isfinite(v):
                    vals[g].append(v)
    return {g: float(np.median(np.abs(v))) for g, v in vals.items() if v}


def run(raw_files, alpha_dir, refdir, block, nm, poly, max_amb,
        sh=None, sq=None, validate_against=None, tol=0.20):
    eng = fitter = sl = None
    per_file = []
    full_nm = _col(sorted(glob.glob(os.path.join(refdir, "Calib*.txt")))[0])

    for rf in raw_files:
        stem = os.path.basename(rf).replace(".dat", "")
        hits = sorted(glob.glob(os.path.join(alpha_dir, stem + "_*alpha_trace.dat")))
        if not hits:
            print("  skip " + stem + ": 알파 트레이스 없음")
            continue
        wave, ri, A, T_C, P_mbar = read_alpha_trace(hits[0])

        p = RawParser(rf)
        if block not in p.layout.spec_blocks:
            raise KeyError(stem + ": 블록 " + block + " 없음")
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
            print("  skip " + stem + ": ZA=%d amb=%d" % (len(za), len(amb)))
            continue
        za = np.asarray(za, float)
        amb = np.asarray(amb, float)

        # 알파 트레이스는 raw 의 일부 픽셀 창만 내보낸다 - 파장으로 창을 되찾는다.
        off = int(np.argmin(np.abs(full_nm - wave[0])))
        win = slice(off, off + len(wave))
        if za.shape[1] < win.stop:
            raise ValueError(stem + ": raw 픽셀이 알파 창보다 짧다 "
                             "(refdir 의 roi 가 이 블록과 다른 것 아닌가)")
        # refdir 의 roi 가 이 채널 것이 맞는지 **파장으로 확인**한다. 틀린 roi 를 쓰면
        # 단면이 통째로 어긋나는데 핏은 조용히 성공해서 엉뚱한 ppb 가 나온다
        # (교차검증 문서가 겪은 "조용히 엉뚱한 열을 집는다"와 같은 실패 모드).
        dnm = float(np.max(np.abs(full_nm[win] - wave)))
        if dnm > 0.05:
            raise ValueError("%s: refdir 의 파장축이 알파와 안 맞는다 (max %.4f nm). "
                             "다른 roi 를 지정할 것." % (stem, dnm))

        I0 = za[:, win].mean(axis=0)
        g = I0 > 0
        q_amb = np.where(g, I0 / np.maximum(amb[:, win], 1e-30) - 1.0, np.nan)
        inwin = (wave >= nm[0]) & (wave <= nm[1])

        # 스케일 앵커 — 비가 아니라 **회귀**여야 한다.
        #   alpha_prod = s(lambda)*q + c(lambda)
        # Rayleigh 차 항이 q 와 무관한 **덧셈** 상수라, 평균의 비로 잡으면 그 항이
        # s 에 섞여 파일마다 값이 튀고 부호까지 뒤집힌다(실제로 그랬다). 기울기만
        # 뽑으면 c 는 절편으로 빠진다. 알파 한 행 = raw 60초 빈이므로 같은 빈의 raw
        # q 를 평균해서 짝을 맞춘다(행 하나에 스캔 하나를 맞추면 노이즈가 섞인다).
        qbar = np.full((len(ri), int(win.stop - win.start)), np.nan)
        bounds = list(ri) + [amb_idx[-1] + 1 if amb_idx else 0]
        pos = {r: k for k, r in enumerate(amb_idx)}
        for k in range(len(ri)):
            sel = [pos[r] for r in range(bounds[k], bounds[k + 1]) if r in pos]
            if sel:
                qbar[k] = np.nanmean(q_amb[sel], axis=0)
        ok = np.isfinite(qbar).all(axis=1) & np.isfinite(A).all(axis=1)
        if ok.sum() < 8:
            print("  skip " + stem + ": 짝지은 빈 %d개 (부족)" % int(ok.sum()))
            continue
        Q, Y = qbar[ok], A[ok]
        Qc, Yc = Q - Q.mean(axis=0), Y - Y.mean(axis=0)
        s_lam = (Qc * Yc).sum(axis=0) / np.maximum((Qc * Qc).sum(axis=0), 1e-300)
        scale = float(np.nanmedian(s_lam[inwin]))
        if not np.isfinite(scale) or scale <= 0:
            print("  skip " + stem + ": 스케일 비정상 %r" % scale)
            continue

        if eng is None:
            eng = build_engine(refdir, wave)
            fitter = DoasFitter(eng)
            idx = np.where(inwin)[0]
            sl = slice(int(idx[0]), int(idx[-1]) + 1)
            print("engine gases=%s  window=%.1f-%.1fnm (%dpx)  poly=%d"
                  % (eng.gas_list, wave[sl][0], wave[sl][-1], sl.stop - sl.start, poly))

        q_za = np.where(g, I0 / np.maximum(za[:, win], 1e-30) - 1.0, np.nan)
        za_fits = [fit_alpha(eng, fitter, wave, q * scale, sl, poly, T_C, P_mbar)
                   for q in q_za]
        step = max(1, len(amb) // max_amb)
        amb_fits = [fit_alpha(eng, fitter, wave, q * scale, sl, poly, T_C, P_mbar)
                    for q in q_amb[::step][:max_amb]]
        per_file.append((stem[-3:], scale, za_fits, amb_fits))
        print("  %s: ZA %d fits, amb %d fits, scale=%.4g cm^-1"
              % (stem[-3:], len(za_fits), len(amb_fits), scale))

    if not per_file:
        print("분석할 파일이 없다.")
        return []

    gases = list(per_file[0][2][0].keys())
    print("\n%8s%16s%14s%14s%12s%12s"
          % ("gas", "ZA mean(bias)", "ZA sigma", "amb median", "sigma/amb", "MDL 3sig"))
    out = []
    for gname in gases:
        z = np.array([f[gname] for _, _, zf, _ in per_file for f in zf])
        a = np.array([f[gname] for _, _, _, af in per_file for f in af])
        z, a = z[np.isfinite(z)], a[np.isfinite(a)]
        if len(z) < 5:
            continue
        s = float(np.std(z, ddof=1))
        am = float(np.median(np.abs(a)))
        out.append((gname, float(np.mean(z)), s, am))
        print("%8s%16.4g%14.4g%14.4g%12.3f%12.4g"
              % (gname, float(np.mean(z)), s, am, (s / am) if am else float("nan"), 3 * s))
    print("\n(ZA 참값=0 이므로 mean 은 bias, sigma 가 단기 노이즈. 블록 내 산포라")
    print(" ZA 주기 사이 I0 드리프트는 빠져 있다 = 실제 ambient 오차의 하한)")
    return out


def main():
    ap = argparse.ArgumentParser(description="제로에어 핏 기반 기체별 노이즈 sigma")
    ap.add_argument('--raw', nargs='+', required=True)
    ap.add_argument('--alpha-dir', required=True)
    ap.add_argument('--refdir', required=True)
    ap.add_argument('--block', default='PNs')
    ap.add_argument('--nm', default='435,480')
    ap.add_argument('--poly', type=int, default=4)
    ap.add_argument('--max-amb', type=int, default=40)
    a = ap.parse_args()
    run(sorted(a.raw), a.alpha_dir, a.refdir, a.block,
        tuple(float(v) for v in a.nm.split(',')), a.poly, a.max_amb)


if __name__ == '__main__':
    main()
