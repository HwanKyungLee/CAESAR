# -*- coding: utf-8 -*-
"""tools/validate_pipeline.py — CAESAR 파이프라인 자동 검증 (계기판 경고등)
===========================================================================
코드를 고친 뒤 `python tools/validate_pipeline.py` 한 번 치면, 각 단계가
여전히 맞는지 자동으로 확인해 PASS/WARN/FAIL 로 보여준다.

왜? 1인 개발이라 뭔가 고치다 '맞던 게 조용히 깨지는' 게 가장 큰 리스크다
(이번에 King factor 오타·0608 웨이브칼 오염·RL 상쇄가 다 그렇게 숨어 있었다).
손으로 검증한 걸 여기 박제해 두면 회귀가 커밋 순간 빨간불로 뜬다.

확인 항목
---------
1. raw 파싱       : Python(.dat) 이 MATLAB(.mat) 과 같은 raw를 읽나 (오차 0이어야)
2. 웨이브칼       : Hg 라인이 알려진 파장에 맞나
3. 레퍼런스 ILS   : ref가 장비 ILS로 뭉개졌나 (raw sharp 아님)
4. Rayleigh 물리  : σ_ZA 가 문헌값과 맞나 (King factor 회귀 감지)
5. R 값          : R(λ)·Leff 가 물리적 범위인가
6. 핏 출력       : NO2 가 타당하고 세 채널이 서로 일치하나

경로는 아래 CONFIG 에서 네 환경에 맞게 고치면 된다. 파일이 없으면 그 항목만 SKIP.
"""
from __future__ import annotations
import os, sys, glob
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — 네 환경 경로 (없는 파일은 자동 SKIP)
# ─────────────────────────────────────────────────────────────────────────────
DROPBOX = r"C:\Users\holle\ATMOS Dropbox\HJ BC\ATMOS\(mission)2026_yeosu\CAESAR Raw"
OUT     = r"C:\Doasis_Work\Output"

RAW_DAT = os.path.join(DROPBOX, r"CAESAR_Hot\2026-05\2026-05-18-001.dat")
RAW_MAT = os.path.join(DROPBOX, r"CAESAR_Hot\2026-05\2026-05-18-001.mat")
WAVECAL = os.path.join(OUT, r"wv_cal\cold\Calib_20260523_Hg_4line_400-497nm_Poly2.txt")
ILS_REF = os.path.join(OUT, r"wv_cal\cold\Ref_NO2_Dynamic-ILS-Applied.dat")
RAW_XS  = r"C:\Doasis_Work\Reference raw\NO2_Vandaele(2002)_294K_384-725nm(vis-dilut5).txt"
R_NPZ   = os.path.join(OUT, r"R\R_cold.npz")
# 일별 버킷 구조({config}/{YYMMDD}/{neg}/{QC}) — 2* 패턴이라 _archive/_derived는 안 걸림.
# config 폴더명은 사용자 실측 콜드 핏창(438.4-475.8nm, §13-B)과 일치하는 걸 고정.
FIT_GLOB = os.path.join(OUT, "fitting", "ch1_429.5~461.9_ch2_444.1~470.6_ch3_438.4~475.8",
                         "2*", "neg_o", "QCoff")

# 웨이브칼 기준: (픽셀, 진짜 Hg 파장 nm). 0523 4-line 기준. 허용오차 0.2nm.
WAVECAL_ANCHORS = [(86, 404.66), (149, 407.78), (721, 435.83), (1883, 491.60)]
WAVECAL_TOL_NM  = 0.25

# ─────────────────────────────────────────────────────────────────────────────
# 체크 프레임워크
# ─────────────────────────────────────────────────────────────────────────────
CHECKS = []
def check(name, needs_data=True):
    """needs_data=False = 머신-로컬 데이터 파일 없이 도는 순수 코드 검증
    (CI가 `--no-data`로 이 항목만 분리 실행한다)."""
    def deco(fn):
        CHECKS.append((name, fn, needs_data)); return fn
    return deco

class Skip(Exception):
    pass

def _need(path):
    if not os.path.exists(path):
        raise Skip(f"파일 없음: {os.path.basename(path)}")
    return path


# ── 1. raw 파싱: Python(.dat) == MATLAB(.mat) ────────────────────────────────
@check("raw 파싱 (Python==MATLAB)")
def c_raw():
    import scipy.io as sio
    _need(RAW_DAT); _need(RAW_MAT)
    m = sio.loadmat(RAW_MAT)
    with open(RAW_DAT, encoding="utf-8", errors="replace") as f:
        lines = [s for s in (ln.strip() for ln in f) if s]
    nmat = m["ch1"].shape[0]
    if len(lines) != nmat:
        return "FAIL", f"행수 불일치 (.dat {len(lines)} vs .mat {nmat})"
    blocks = {"ch1": (2053, 4101), "ch2": (4101, 6149), "ch3": (5, 2053)}
    worst = 0
    for r in (10, 500, 2000):
        if r >= nmat:
            continue
        dat = np.array(lines[r].split("\t"), dtype=float)
        for mk, (s, e) in blocks.items():
            mv = m[mk][r].astype(float)
            if e <= len(dat):
                worst = max(worst, int(np.max(np.abs(dat[s:e] - mv))))
        if int(m["flag"][r, 0]) != int(dat[4]):
            return "FAIL", f"flag 불일치 row{r}"
    if worst == 0:
        return "PASS", "스펙트럼·flag 오차 0 (바이트 일치)"
    return "FAIL", f"스펙트럼 최대오차 {worst} (0이어야 함)"


# ── 2. 웨이브칼: Hg 라인이 맞나 ──────────────────────────────────────────────
@check("웨이브칼 (Hg 라인 위치)")
def c_wavecal():
    _need(WAVECAL)
    wl = np.array([float(l) for l in open(WAVECAL, encoding="utf-8", errors="replace")
                   if l.strip() and not l.strip().startswith("#")])
    if not (398 < wl[0] < 402 and 497 < wl[-1] < 501):
        return "FAIL", f"파장범위 이상 {wl[0]:.1f}~{wl[-1]:.1f}nm"
    if np.any(np.diff(wl) <= 0):
        return "FAIL", "파장이 단조증가 아님"
    errs = [abs(wl[px] - nm) for px, nm in WAVECAL_ANCHORS if px < len(wl)]
    worst = max(errs)
    if worst <= WAVECAL_TOL_NM:
        return "PASS", f"Hg 4라인 모두 ±{worst:.2f}nm 이내"
    return "FAIL", f"Hg 라인 최대 {worst:.2f}nm 어긋남 (>{WAVECAL_TOL_NM}, 웨이브칼 교체?)"


# ── 3. 레퍼런스 ILS: 뭉개졌나 (raw sharp 아님) ───────────────────────────────
@check("레퍼런스 ILS 적용")
def c_ref_ils():
    _need(ILS_REF); _need(RAW_XS); _need(WAVECAL)
    ils = np.array([float(l) for l in open(ILS_REF, encoding="utf-8", errors="replace")
                    if l.strip() and not l.strip().startswith("#")])
    rw, rs = np.loadtxt(RAW_XS, unpack=True)
    wl = np.array([float(l) for l in open(WAVECAL, encoding="utf-8", errors="replace")
                   if l.strip() and not l.strip().startswith("#")])
    if len(ils) != len(wl):
        return "WARN", f"ref({len(ils)})·wavecal({len(wl)}) 길이 다름"
    raw_on = np.interp(wl, rw, rs)
    m = (wl >= 438) & (wl <= 476)
    xm = np.linspace(-1, 1, int(m.sum()))
    def dstd(y):
        return np.std(y - np.polyval(np.polyfit(xm, y, 4), xm))
    ratio = dstd(ils[m]) / (dstd(raw_on[m]) + 1e-30)   # ILS면 <1, raw면 ≈1
    if ratio < 0.92:
        return "PASS", f"ref가 ILS로 뭉개짐 (차분비 {ratio:.2f})"
    return "FAIL", f"ref가 raw처럼 sharp (차분비 {ratio:.2f}≈1, ILS 미적용?)"


# ── 4. Rayleigh 물리: σ_ZA 가 문헌값과 맞나 (King factor 회귀 감지) ──────────
@check("Rayleigh 물리 (King factor)", needs_data=False)
def c_rayleigh():
    from core.physics import RayleighPhysics
    N0 = 2.6867811e19
    wave = np.array([447.0])
    sig = RayleighPhysics.get_alpha_rayleigh(wave, 0.0, 1013.25, "zero_air")[0] / N0
    # 골든값: King factor 수정(v→v²,1.09→1.096) 후 Bates/Bodhaine 문헌과 정합 검증된
    # @447.0nm σ_ZA. 허용 0.1% — King factor 회귀(σ 0.23% 변동)를 잡을 만큼 빡세다.
    GOLDEN = 9.6997e-27
    rel = abs(sig - GOLDEN) / GOLDEN
    if rel < 0.001:
        return "PASS", f"σ_ZA @447nm = {sig:.4e} (문헌 골든값 {rel*100:.3f}% 이내)"
    return "FAIL", f"σ_ZA {sig:.4e} vs 골든 {GOLDEN:.4e} ({rel*100:.2f}% 차 — King factor 회귀?)"


# ── 5. R 값: 물리적 범위인가 ─────────────────────────────────────────────────
@check("R 값 (R·Leff 물리성)")
def c_rvalue():
    _need(R_NPZ)
    z = np.load(R_NPZ, allow_pickle=True)
    omr = np.asarray(z["omr_d"], float); wv = np.asarray(z["wave_nm"], float)
    omr_m = np.nanmedian(omr, 0); d = 51.8
    m = (wv >= 438) & (wv <= 476)
    Rmed = float(np.nanmedian(1 - omr_m[m] * d))
    leff = float(np.nanmean(1 / omr_m[m]) * 1e-5)
    # 이상치 = 물리적으로 불가능한 Leff (1km 미만 or 50km 초과 or 비유한). 한 달
    # 캠페인의 정상 드리프트는 이 범위 안이라 안 잡힌다 — 진짜 깨진 knot만 센다.
    leff_knot = np.nanmean(1 / np.maximum(omr[:, m], 1e-12), 1) * 1e-5
    n_bad = int(np.sum((leff_knot < 1) | (leff_knot > 50) | ~np.isfinite(leff_knot)))
    if not (0.99 <= Rmed <= 0.999995 and 1 <= leff <= 50):
        return "FAIL", f"R={Rmed:.5f} Leff={leff:.1f}km (물리범위 벗어남)"
    if n_bad > 0.05 * len(leff_knot):
        return "WARN", f"R 정상(R={Rmed:.5f},Leff={leff:.1f}km)이나 물리불가 knot {n_bad}/{len(leff_knot)}"
    return "PASS", f"R={Rmed:.5f}  Leff={leff:.1f}km  물리불가 knot {n_bad}/{len(leff_knot)}"


# ── 6. 핏 출력: NO2 타당 + 채널 일치 ─────────────────────────────────────────
def _read_fit_no2(path):
    lines = [l.rstrip("\n") for l in open(path, encoding="utf-8", errors="replace")]
    hi = next(i for i, l in enumerate(lines) if l.strip() and not l.startswith("#"))
    hdr = lines[hi].split("\t"); ci = hdr.index("NO2")
    v = []
    for l in lines[hi + 1:]:
        if l.strip() and not l.startswith("#"):
            try:
                x = float(l.split("\t")[ci])
                if np.isfinite(x):
                    v.append(x)
            except Exception:
                pass
    return np.array(v)

@check("핏 출력 (NO2 타당·채널일치)")
def c_fit():
    if not glob.glob(FIT_GLOB):
        raise Skip(f"파일 없음: {FIT_GLOB}")
    meds = {}
    for tag in ("cold", "ANs", "PNs"):   # 실제 파일명 태그(ch1=ANs, ch2=PNs — §14-D)
        fs = sorted(glob.glob(os.path.join(FIT_GLOB, f"*{tag}*.dat")))
        fs = [f for f in fs if "NO2-PNs" not in os.path.basename(f)]
        if fs:
            no2 = _read_fit_no2(fs[0])
            if len(no2):
                meds[tag] = float(np.median(no2))
    if not meds:
        raise Skip("핏 결과 파일 없음")
    bad = {k: v for k, v in meds.items() if not (-2 <= v <= 30)}
    if bad:
        return "FAIL", f"NO2 중앙값 비현실적: {bad} ppb"
    vals = list(meds.values())
    if max(vals) > 3 * max(min(vals), 0.3):
        return "WARN", f"채널간 NO2 차 큼: {meds}"
    txt = "  ".join(f"{k}={v:.1f}" for k, v in meds.items())
    return "PASS", f"NO2 ppb {txt} (타당·채널일치)"


# ─────────────────────────────────────────────────────────────────────────────
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    no_data = "--no-data" in argv
    checks = [(n, f) for n, f, nd in CHECKS if not (no_data and nd)]
    print("=" * 64)
    print(" CAESAR 파이프라인 자동 검증"
          + ("  [--no-data: 데이터 비의존 항목만]" if no_data else ""))
    print("=" * 64)
    n_pass = n_warn = n_fail = n_skip = 0
    for name, fn in checks:
        try:
            status, msg = fn()
        except Skip as e:
            status, msg = "SKIP", str(e)
        except Exception as e:
            status, msg = "FAIL", f"오류: {e}"
        icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌", "SKIP": "⏭️ "}[status]
        print(f" [{status:4s}] {icon} {name}")
        print(f"          {msg}")
        n_pass += status == "PASS"; n_warn += status == "WARN"
        n_fail += status == "FAIL"; n_skip += status == "SKIP"
    print("-" * 64)
    print(f" 결과: {n_pass} PASS · {n_warn} WARN · {n_fail} FAIL · {n_skip} SKIP")
    if n_fail:
        print(" ❌ 실패 항목이 있다 — 최근 코드 변경이 뭔가 깨뜨렸을 수 있음.")
    elif n_warn:
        print(" ⚠️  치명적 실패는 없지만 주의 항목 있음.")
    else:
        print(" ✅ 전부 통과 — 파이프라인 건강함.")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
