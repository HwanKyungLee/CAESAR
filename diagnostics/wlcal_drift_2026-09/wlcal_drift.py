#!/usr/bin/env python
"""T3 — 캠페인 전체의 파장검정(픽셀→파장) 드리프트.  (읽기 전용 진단)

왜
--
지금까지 본 것은 **핏 내부의 shift** 뿐이다. Calib 자체가 캠페인 수 주에 걸쳐
움직였는지는 확인된 적이 없다. 움직였다면 모든 창에 공통으로 걸리는 계통항이고,
알려진 ch↔roi 매핑 불일치(0.62 px)와 합쳐질 수 있다.

무엇을 재는가
------------
1. **Hg 검정 시대 간 드리프트** — 같은 채널의 `Calib_*.txt` 들을 서로 빼고, 차이를
   **픽셀 단위**로 환산한다(Δpx = Δnm / 국소 분산 dλ/dpx). nm 으로 적으면 창마다
   분산이 달라 비교가 안 된다.
2. **production 산출물이 실제로 쓴 축과 fitset 축의 불일치** — 알파 트레이스 헤더의
   `wavelength_nm` 과 fitset `wl_path` 를 같은 방식으로 비교한다. 이건 드리프트가
   아니라 **배선 오류**지만, 최종 농도에는 드리프트와 똑같이 들어간다.

재현
----
    python diagnostics/wlcal_drift_2026-09/wlcal_drift.py \
        --group cold 438.0 465.8 \
            "C:/Doasis_Work/Output/wv_cal/cold/old/Calib_20260602_Hg_399-498nm_Poly2.txt" \
            "C:/Doasis_Work/Output/wv_cal/cold/Calib_20260523_Hg_4line_400-497nm_Poly2.txt" \
            "E:/Yeosu_2026/CAESAR_Cold/wv_cal/Calib_20260507_Hg_399-494nm_Poly2.txt" \
        --alpha <production alpha_trace.dat> --alpha-ref <fitset wl_path>
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from core.data_io import DataIO


def _load(path):
    w = DataIO.load_wavecal_array(path)
    if w is None:
        raise SystemExit(f"ABSTAIN: wavecal 을 못 읽었다 — {path}")
    return np.asarray(w, float).ravel()


def compare(ref_w, w, lo, hi):
    """두 파장축의 차이를 **픽셀 단위**로. (nm 차 / 국소 분산)"""
    n = min(len(ref_w), len(w))
    ref_w, w = ref_w[:n], w[:n]
    disp = np.gradient(ref_w)                       # nm/px
    d_px = (w - ref_w) / disp
    m = (ref_w >= lo) & (ref_w <= hi)
    if not m.any():
        raise SystemExit(f"ABSTAIN: 창 {lo}-{hi} nm 이 축 범위 밖")
    seg = d_px[m]
    return dict(n=int(m.sum()), med=float(np.median(seg)),
                p95=float(np.percentile(np.abs(seg), 95)),
                mx=float(np.max(np.abs(seg))),
                span=float(np.max(seg) - np.min(seg)),
                disp=float(np.median(disp[m])))


def hg_spectrum(path):
    """Hg 램프 CSV(`ROI,Frame,Row,Column,Intensity`) → 픽셀축 스펙트럼.

    Calib_*.txt 는 **누가 언제 피팅했느냐**가 섞인 산물이다(실측: 같은 04-03 Hg 를
    04-03 판과 06-19 판이 1.5 px 다르게 적는다). 램프 원자료에서 피크 자리를 직접
    재면 그 교란 없이 **계기가 움직였는지**만 볼 수 있다."""
    col, inten = [], []
    with open(path, encoding="utf-8", errors="replace") as fh:
        next(fh, None)
        for line in fh:
            t = line.split(",")
            if len(t) < 5:
                continue
            try:
                col.append(int(t[3])); inten.append(float(t[4]))
            except ValueError:
                continue
    col = np.asarray(col); inten = np.asarray(inten, float)
    if col.size == 0:
        raise SystemExit(f"ABSTAIN: Hg CSV 를 못 읽었다 — {path}")
    spec = np.bincount(col, weights=inten, minlength=col.max() + 1)
    return spec / max(np.bincount(col, minlength=col.max() + 1).max(), 1)


def peak_centroid(spec, px0, half=20):
    """px0 주변 ±half 에서 배경 뺀 무게중심. 배경은 창 가장자리 5 px 중앙값."""
    lo, hi = max(0, int(px0) - half), min(len(spec), int(px0) + half + 1)
    seg = spec[lo:hi].astype(float)
    if seg.size < 5:
        return float("nan")
    bg = np.median(np.concatenate([seg[:5], seg[-5:]]))
    w = np.clip(seg - bg, 0, None)
    if w.sum() <= 0:
        return float("nan")
    return float(np.dot(np.arange(lo, hi), w) / w.sum())


def _alpha_axis(path):
    """알파 트레이스 헤더의 `# wavelength_nm:` 한 줄."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("# wavelength_nm"):
                return np.array([float(v) for v in line.split(":", 1)[1].split()], float)
            if not line.startswith("#"):
                break
    raise SystemExit(f"ABSTAIN: {os.path.basename(path)} 헤더에 wavelength_nm 이 없다")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", nargs="+", action="append", required=True,
                    metavar="NAME LO HI FILE...",
                    help="채널 이름, 핏창 lo hi (nm), 그 채널의 Calib 파일들. "
                         "첫 파일이 기준(production 이 실제 쓴 것)")
    ap.add_argument("--hg", nargs="+", action="append", metavar="NAME PX... :: FILE...",
                    help="채널 이름, 기대 피크 픽셀들, '::', Hg 램프 CSV 들. "
                         "첫 CSV 가 기준 시대")
    ap.add_argument("--alpha", help="production alpha_trace.dat (헤더 축 비교용)")
    ap.add_argument("--alpha-ref", help="그 채널 fitset 의 wl_path")
    ap.add_argument("--out")
    args = ap.parse_args()

    rows = []
    for grp in args.group:
        name, lo, hi = grp[0], float(grp[1]), float(grp[2])
        files = grp[3:]
        if len(files) < 2:
            print(f"[{name}] Calib 파일이 {len(files)}개뿐 — 드리프트를 **잴 수 없다**. "
                  f"이건 '드리프트 없음'이 아니라 '측정 없음'이다.")
            continue
        ref = _load(files[0])
        print(f"[{name}] 기준 {os.path.basename(files[0])}  "
              f"분산 {np.median(np.gradient(ref)):.4f} nm/px  창 {lo}-{hi} nm")
        for f in files[1:]:
            r = compare(ref, _load(f), lo, hi)
            print(f"  vs {os.path.basename(f):50s} "
                  f"중앙 {r['med']:+.3f} px · p95|Δ| {r['p95']:.3f} px · "
                  f"최대|Δ| {r['mx']:.3f} px · 창내 기울기폭 {r['span']:.3f} px")
            rows.append(dict(group=name, kind="calib_epoch", ref=os.path.basename(files[0]),
                             other=os.path.basename(f), **r))

    for grp in (args.hg or []):
        name = grp[0]
        sep = grp.index("::")
        pxs = [float(v) for v in grp[1:sep]]
        files = grp[sep + 1:]
        cents = []
        for f in files:
            sp = hg_spectrum(f)
            c = [peak_centroid(sp, p) for p in pxs]
            cents.append(c)
            print(f"[Hg {name}] {os.path.basename(f):40s} 피크 px "
                  + " ".join(f"{v:8.3f}" for v in c))
        if len(cents) < 2:
            print(f"[Hg {name}] 램프 측정이 {len(cents)}회뿐 — 드리프트를 **잴 수 없다**"
                  f" ('드리프트 없음'이 아니다)")
            continue
        for f, c in zip(files[1:], cents[1:]):
            dv = np.asarray(c) - np.asarray(cents[0])
            print(f"[Hg {name}] vs {os.path.basename(f):36s} Δpx "
                  + " ".join(f"{v:+8.3f}" for v in dv)
                  + f"   |중앙 {np.nanmedian(dv):+.3f} px, 창내 기울기폭 "
                    f"{np.nanmax(dv) - np.nanmin(dv):.3f} px|")
            rows.append(dict(group=name, kind="hg_lamp", ref=os.path.basename(files[0]),
                             other=os.path.basename(f), n=len(pxs),
                             med=float(np.nanmedian(dv)),
                             p95=float(np.nanpercentile(np.abs(dv), 95)),
                             mx=float(np.nanmax(np.abs(dv))),
                             span=float(np.nanmax(dv) - np.nanmin(dv)), disp=float("nan")))

    if args.alpha and args.alpha_ref:
        a = _alpha_axis(args.alpha)
        b = _load(args.alpha_ref)
        # 알파 축은 pixel_min 부터 잘려 있을 수 있다 — 길이가 같을 때만 정직하게 비교한다.
        if len(a) != len(b):
            print(f"[alpha] 길이 불일치 {len(a)} vs {len(b)} — 앞에서부터 겹치는 만큼만 본다")
        lo, hi = float(a[0]), float(a[-1])
        r = compare(b[:len(a)], a, lo, hi)
        print(f"[alpha] {os.path.basename(args.alpha)} 헤더축 vs fitset "
              f"{os.path.basename(args.alpha_ref)}: 중앙 {r['med']:+.3f} px · "
              f"최대|Δ| {r['mx']:.3f} px")
        rows.append(dict(group="alpha_vs_fitset", kind="wiring",
                         ref=os.path.basename(args.alpha_ref),
                         other=os.path.basename(args.alpha), **r))

    if rows:
        out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "wlcal_drift.csv")
        keys = list(rows[0])
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(",".join(keys) + "\n")
            for r in rows:
                fh.write(",".join(f"{r[k]:.6g}" if isinstance(r[k], float) else str(r[k])
                                  for k in keys) + "\n")
        print(f"→ {out}  ({len(rows)} rows)")


if __name__ == "__main__":
    main()
