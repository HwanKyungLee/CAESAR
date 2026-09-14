"""B2 회귀 검사 — Result Lab 세로 스택 · flag 색 · 클릭 → 아래 패널.

지키는 것:
  1. 종마다 레인이 하나씩 생기고 **x축이 공유**된다(+ shift/squeeze · RMS 레인).
  2. flag 분류가 Status 자유형식을 올바로 읽는다. **값은 지우지 않는다** — 색만 다르다.
  3. 점을 클릭하면 아래 패널에 그 스캔의 상세가 뜨고, **시계열 레인은 계속 보인다**.
  4. fit이 아닌 종류(R 커브 등)는 예전 2단 플롯으로 되돌아간다(스택은 fit 전용).
  5. `load_fit_table`이 shift/squeeze를 준다 — 없으면 레인이 통째로 빈다.

    python tools/test_result_lanes.py
"""
from __future__ import annotations

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QApplication

from gui.result_viewer_io import load_fit_table
from gui.ui_result_viewer import ResultViewerWidget

_HDR = (
    "# ==========================================================\n"
    "# Augur Analysis Report\n"
    "# Fit Range: Pixel 774-1550 (438.4-475.8nm)\n"
    "# ==========================================================\n"
)
# 실제 저장 포맷을 따른다 — detect()는 File/Status/Chi2가 다 있어야 fit으로 본다
_COLS = ("File\tTime\tChannel\tRMS\tChi2\tSNR\tStatus\tShift\tSqueeze\t"
         "NO2\tNO2_Error\tCHOCHO\tCHOCHO_Error\n")
_ROWS = [
    ("f1", "2026-09-04 10:00:00", 0.0012, "OK",       -0.51, 1.0001,  3.5, 0.06, 0.09, 0.02),
    ("f2", "2026-09-04 10:01:00", 0.0018, "Unstable", -0.48, 1.0002,  9.9, 0.90, 0.11, 0.03),
    ("f3", "2026-09-04 10:02:00", 0.0090, "QC-RMS",   -0.50, 1.0000, -1.2, 0.50, 0.05, 0.04),
    ("f4", "2026-09-04 10:03:00", 0.0011, "Zero-Air (Flag 500 - I0 Updated)",
                                                      -0.52, 1.0001,  0.1, 0.02, 0.01, 0.01),
    ("f5", "2026-09-04 10:04:00", 0.0013, "Settling",  -0.49, 1.0001,  3.4, 0.06, 0.08, 0.02),
]


def _write_fit(d):
    p = os.path.join(d, "260904_CH1_PNs_r3f8a1.dat")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(_HDR + _COLS)
        for r in _ROWS:
            # File Time Channel RMS Chi2 SNR Status Shift Squeeze <gases…>
            fh.write("\t".join(str(v) for v in
                               (r[0], r[1], 1, r[2], 1.05, 120.0, *r[3:])) + "\n")
    return p


def _write_alpha(d, stem):
    """형제 alpha_trace — 클릭 상세가 스펙트럼을 찾을 수 있어야 한다."""
    p = os.path.join(d, stem + "_alpha_trace.dat")
    wave = np.linspace(438.0, 476.0, 12)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("# wavelength_nm:\t" + "\t".join(f"{w:.3f}" for w in wave) + "\n")
        fh.write("row_idx\tT_C\tP_mbar\t" + "\t".join(f"px{700+i}" for i in range(12)) + "\n")
        for i in range(len(_ROWS)):
            vals = "\t".join(f"{1e-7 * (i + 1) * (j + 1):.6e}" for j in range(12))
            fh.write(f"{i}\t25.0\t1013.0\t{vals}\n")
    return p


def test_loader_exposes_shift_squeeze():
    d = tempfile.mkdtemp()
    t = load_fit_table(_write_fit(d))
    assert t["shift"] is not None and t["squeeze"] is not None, sorted(t)
    assert abs(t["shift"][0] - (-0.51)) < 1e-9, t["shift"]
    assert list(t["gases"]) == ["NO2", "CHOCHO"], list(t["gases"])


def test_flag_classification():
    """Status는 자유형식 — 부분일치로 읽되 엉뚱한 걸 ok로 뭉개지 않는다."""
    f = ResultViewerWidget._flag_of
    assert f("OK") == "ok"
    assert f("") == "ok"
    assert f("Unstable") == "unstable"
    assert f("QC-RMS") == "qc"
    assert f("Settling skip") == "settling"
    assert f("Zero-Air (Flag 500 - I0 Updated)") == "cal"
    assert f("Helium (Flag 510 - Updated)") == "cal"
    assert f("Skip: All-Zero") == "cal"


def test_lanes_and_click(w):
    d = tempfile.mkdtemp()
    fit = _write_fit(d)
    _write_alpha(d, "260904_CH1_PNs_r3f8a1")

    w._path = fit
    w._reload()
    assert w._current_kind == "fit", w._current_kind

    # 종 2개 + shift/squeeze + RMS = 4 레인, 전부 표시
    vis = [pw for pw in w._lanes if not pw.isHidden()]
    assert len(vis) == 4, [pw.isHidden() for pw in w._lanes]
    # x축 공유 — 아래 레인들이 첫 레인에 링크돼 있다
    for pw in vis[1:]:
        assert pw.getViewBox().linkedView(0) is vis[0].getViewBox(), "x축이 안 묶였다"
    # 예전 2단 플롯은 물러나고 상세 패널이 나온다
    assert w._pw_top.isHidden() and w._pw_bot.isHidden()
    assert not w._stack_host.isHidden() and not w._pw_detail.isHidden()

    # flag 색: 5스캔이 서로 다른 상태 → 산점도 브러시도 달라야 한다
    sc = w._scatters[0]
    brushes = [sp.brush().color().name() for sp in sc.points()]
    assert len(set(brushes)) >= 4, brushes
    # 값은 지우지 않는다 — Unstable/Settling 행도 y가 살아있다
    t = w._fit_cache
    assert np.isfinite(t["gases"]["NO2"][1]) and np.isfinite(t["gases"]["NO2"][4])

    # 클릭 → 아래 패널에 상세, 시계열 레인은 계속 보인다
    w._show_scan_detail(1)
    title = w._pw_detail.plotItem.titleLabel.text
    assert "row 1" in title and "Unstable" in title, title
    assert "NO2 9.9" in title, title
    assert len(w._pw_detail.plotItem.listDataItems()) == 1, "alpha 스펙트럼이 안 그려졌다"
    assert not w._stack_host.isHidden(), "상세를 띄우느라 시계열이 사라지면 안 된다"

    # alpha 형제 파일이 없어도 수치 요약은 뜨고 죽지 않는다
    os.remove(os.path.join(d, "260904_CH1_PNs_r3f8a1_alpha_trace.dat"))
    w._show_scan_detail(2)
    assert "row 2" in w._pw_detail.plotItem.titleLabel.text


def test_non_fit_restores_old_plots(w):
    """스택은 fit 전용 — R 커브 같은 건 예전 2단 플롯으로 돌아가야 한다."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "x_R.dat")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("wavelength_nm\tR_raw\tR_fitted\tomr_d\tLeff_km\n")
        for i in range(5):
            fh.write(f"{440 + i}\t0.9998\t0.9998\t2e-5\t50.0\n")
    w._path = p
    w._reload()
    assert not w._pw_top.isHidden(), "예전 상단 플롯이 안 돌아왔다"
    assert w._stack_host.isHidden(), "fit이 아닌데 스택이 남아있다"


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)   # 참조 유지 필수
    assert app is not None
    w = ResultViewerWidget()
    for fn, args in ((test_loader_exposes_shift_squeeze, ()),
                     (test_flag_classification, ()),
                     (test_lanes_and_click, (w,)),
                     (test_non_fit_restores_old_plots, (w,))):
        fn(*args)
        print(f"  PASS  {fn.__name__}")
    print("result lanes self-check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
