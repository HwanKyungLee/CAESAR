"""Etalon–기체 공선성 실측 프로브 (개선작업지시_2026-07 §B-3).

현재 캠페인 시나리오(콜드 NO₂·CHOCHO·H₂O, 775–1550 px, 4차 poly)에서 etalon
sin/cos 열과 기체 지문의 differential-공간 상관 r·VIF를 실제로 잰다 —
리뷰 방어용 실측 기록. GUI 없이 RUN과 동일 요소(웨이브칼·ILS 적용 레퍼런스·
FFT etalon 검출)로 구성한다.

사용: python tools/etalon_collinearity_probe.py [alpha_trace.dat]
      (인자 없으면 기본 콜드 알파 1개)
결과는 docs/etalon_collinearity_2026-07.md 에 기록.
"""
import os
import sys

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.engine import UniversalEngine
from core.doas_fit import DoasFitter

OUT = r"C:\Doasis_Work\Output"
WAVECAL = os.path.join(OUT, r"wv_cal\cold\Calib_20260523_Hg_4line_400-497nm_Poly2.txt")
REFS = {   # 2026 여수 콜드 시나리오 (ILS 적용본)
    "NO2":    os.path.join(OUT, r"wv_cal\cold\Ref_NO2_Dynamic-ILS-Applied.dat"),
    "CHOCHO": os.path.join(OUT, r"wv_cal\cold\Ref_CHOCHO_Dynamic-ILS-Applied.dat"),
    "H2O":    os.path.join(OUT, r"wv_cal\cold\Ref_H2O-HITRAN_Dynamic-ILS-Applied.dat"),
}
ALPHA_DEFAULT = os.path.join(OUT, r"alpha\cold\2026-05-17\2026-05-17-001_cold_alpha_trace.dat")
PX_MIN, PX_MAX = 775, 1550      # 시나리오 핏창
POLY_ORDER = 4


def load_alpha_scan(path):
    """알파 트레이스 파일에서 첫 데이터 행(2048px)과 파장 헤더를 읽는다."""
    wave = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("# wavelength_nm"):
                wave = np.array([float(x) for x in line.split(":")[1].split()])
                continue
            if line.startswith("#"):
                continue
            cols = line.rstrip("\n").split("\t")
            if cols and cols[0] == "row_idx":
                start = next(i for i, c in enumerate(cols) if c.startswith("px"))
                continue
            if wave is not None and cols and not cols[0].startswith("row"):
                vals = np.array([float(v) for v in cols[start:start + len(wave)]])
                return wave, vals
    raise RuntimeError(f"no data row in {path}")


def main(argv):
    alpha_path = argv[0] if argv else ALPHA_DEFAULT
    for p in [WAVECAL, alpha_path] + list(REFS.values()):
        if not os.path.exists(p):
            print(f"SKIP — file not found: {p}")
            return 1

    wl = np.array([float(l) for l in open(WAVECAL, encoding="utf-8", errors="replace")
                   if l.strip() and not l.strip().startswith("#")])
    eng = UniversalEngine()
    eng.set_wavelength_axis(wl)
    for name, path in REFS.items():
        ok, msg = eng.add_reference(name, path, wave_nm=wl, multiplier=1.0)
        if not ok:
            print(f"ref load failed [{name}]: {msg}")
            return 1

    wave_f, alpha = load_alpha_scan(alpha_path)
    px = np.arange(PX_MIN, PX_MAX + 1, dtype=float)
    a = alpha[PX_MIN:PX_MAX + 1]

    fitter = DoasFitter(eng)
    e_f = fitter.detect_etalon_frequency(px, a, POLY_ORDER, 0.02, 0.40)
    diag = fitter.etalon_collinearity(px, e_f, POLY_ORDER, ref_properties={})

    print(f"scenario: cold {'+'.join(REFS)}  window {PX_MIN}-{PX_MAX}px "
          f"({wl[PX_MIN]:.1f}-{wl[PX_MAX]:.1f}nm)  poly={POLY_ORDER}")
    print(f"alpha scan: {os.path.basename(alpha_path)}")
    print(f"detected etalon f = {e_f:.4f} rad/px "
          f"(period {2 * np.pi / e_f:.1f} px)")
    print(DoasFitter.format_etalon_collinearity(diag))
    for g, d in diag["per_gas"].items():
        print(f"  {g:8s} r={d['r']:.3f}  VIF={d['vif']:.2f}  "
              f"VIF(no etalon)={d['vif_no_etalon']:.2f}  "
              f"etalon-induced inflation ×{d['vif'] / d['vif_no_etalon']:.2f}")
    # 주파수 스윕: FFT 검출 밴드(0.02–0.40 cycles/px = 0.126–2.513 rad/px) 전체에서
    # 최악의 r — 캠페인 중 etalon 주파수가 어디로 가더라도 안전한지 확인.
    fs = 2.0 * np.pi * np.linspace(0.02, 0.40, 153)
    worst = {g: (0.0, 0.0) for g in REFS}
    for f in fs:
        d2 = fitter.etalon_collinearity(px, f, POLY_ORDER, ref_properties={})
        for g in REFS:
            r = d2["per_gas"][g]["r"]
            if np.isfinite(r) and r > worst[g][0]:
                worst[g] = (r, f)
    print("worst-case r over detection band 0.02–0.40 cycles/px "
          "(0.126–2.513 rad/px):")
    for g, (r, f) in worst.items():
        print(f"  {g:8s} max r={r:.3f} at f={f:.3f} rad/px "
              f"(period {2 * np.pi / f:.1f} px)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
