"""B2 회귀 검사 — Result Lab 세로 스택 · flag 색 · 클릭 → 아래 패널.

지키는 것:
  1. 종마다 레인이 하나씩 생기고 **x축이 공유**된다(+ shift/squeeze · RMS 레인).
  2. flag 분류가 Status 자유형식을 올바로 읽는다. **값은 지우지 않는다** — 색만 다르다.
  3. 점을 클릭하면 아래 패널에 그 스캔의 상세가 뜨고, **시계열 레인은 계속 보인다**.
  4. fit이 아닌 종류(R 커브 등)는 예전 2단 플롯으로 되돌아간다(스택은 fit 전용).
  5. `load_fit_table`이 shift/squeeze를 준다 — 없으면 레인이 통째로 빈다.
  6. 잔차 패널은 **그때 설정을 복원 못 하면 안 그리고 사유를 적는다**(레거시 = meta 없음).

    python tools/test_result_lanes.py
"""
from __future__ import annotations
# 한글 Windows 콘솔(cp949)에서 직접 실행해도 '—'·'✓' 등에서 죽지 않게(2026-10-01).
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

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


_STEM = "260904_CH1_PNs_r3f8a1"
# alpha row_idx column values are NOT positions (real files: 0, 258, 310, …) — 2026-10-02 R3
_ALPHA_IDS = (0, 258, 310, 400, 512)


def _write_fit(d):
    p = os.path.join(d, _STEM + ".dat")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(_HDR + _COLS)
        for k, r in enumerate(_ROWS):
            # File Time Channel RMS Chi2 SNR Status Shift Squeeze <gases…>
            # File = "<alpha> [NNNN]" as the worker writes it: NNNN = alpha data-row position
            fh.write("\t".join(str(v) for v in
                               (f"{_STEM}_alpha_trace.dat [{k:04d}]", r[1], 1, r[2], 1.05, 120.0,
                                *r[3:])) + "\n")
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
            fh.write(f"{_ALPHA_IDS[i]}\t25.0\t1013.0\t{vals}\n")
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

    # 클릭 판정은 산점도가 아니라 원본 전부로 — 그 점 좌표면 그 행, 동떨어진 곳이면 없음
    from PyQt6.QtCore import QPointF
    lane = vis[0]
    xs, ys = t["time"], t["gases"]["NO2"]
    hidden = w._qc_mask(t)            # Hide QC로 숨긴 행은 화면에 없으니 클릭으로도 안 집힌다
    for j in range(len(xs)):
        want = None if hidden[j] else j
        assert w.lane_point_at(lane, QPointF(float(xs[j]), float(ys[j]))) == want, j
    (x0, x1), (y0, y1) = lane.getViewBox().viewRange()
    assert w.lane_point_at(lane, QPointF(x0 - (x1 - x0), y0 - (y1 - y0))) is None

    # 클릭 → 아래 패널에 상세, 시계열 레인은 계속 보인다
    w._show_scan_detail(1)
    title = w._pw_detail.plotItem.titleLabel.text
    assert "row 1" in title and "Unstable" in title, title
    assert "NO2 9.9" in title, title
    items = w._pw_detail.plotItem.listDataItems()
    assert len(items) == 1, "alpha 스펙트럼이 안 그려졌다"
    # the File cell's position picks the scan — data row 1 (row_idx 258), not row_idx 1
    assert abs(items[0].yData[0] - 2e-7) < 1e-12, items[0].yData[:3]
    assert not w._stack_host.isHidden(), "상세를 띄우느라 시계열이 사라지면 안 된다"

    # alpha 형제 파일이 없어도 수치 요약은 뜨고 죽지 않는다
    os.remove(os.path.join(d, "260904_CH1_PNs_r3f8a1_alpha_trace.dat"))
    w._show_scan_detail(2)
    title = w._pw_detail.plotItem.titleLabel.text
    assert "row 2" in title and "not found" in title, title
    assert not w._pw_detail.plotItem.listDataItems(), "drew a spectrum from the wrong file"
    assert ResultViewerWidget._sibling_alpha(fit) is None, "the fit .dat is not its own alpha"


def test_real_click_opens_detail(w):
    """A real mouse click on a plotted point must open Scan detail (2026-10-02 R1: the flag
    ScatterPlotItem accepted the click and `_on_lane_click` returned on `ev.isAccepted()`,
    so the panel never opened — the test above calls `_show_scan_detail` directly)."""
    from PyQt6.QtCore import QPointF, Qt as _Qt
    from PyQt6.QtTest import QTest
    d = tempfile.mkdtemp()
    fit = _write_fit(d)
    _write_alpha(d, "260904_CH1_PNs_r3f8a1")
    w.resize(1200, 900); w.show()
    w._path = fit
    w._reload()
    QApplication.processEvents()
    w._pw_detail.setTitle("untouched")
    lane = w._lanes[0]
    t = w._fit_cache
    j = 1                                   # Unstable row — not hidden by Hide QC
    sp = lane.getViewBox().mapViewToScene(QPointF(float(t["time"][j]), float(t["gases"]["NO2"][j])))
    vp = lane.mapFromScene(sp)
    QTest.mouseClick(lane.viewport(), _Qt.MouseButton.LeftButton, pos=vp)
    QApplication.processEvents()
    title = w._pw_detail.plotItem.titleLabel.text
    assert "row 1" in title and "Unstable" in title, title


def test_big_file_thinning_keeps_flag_share(w):
    """큰 파일(>2만 행)은 화면 칸마다 점 하나로 그린다 — 그래도 **flag 색 비율이 전부 그린 그림과
    같아야** 한다(2026-10-01: ok만 솎고 flag 점을 전부 덧그렸더니 2 %인 QC가 띠 전체를 덮어
    '대부분 QC'처럼 보였다). 클릭은 솎아서 안 그려진 점도 집는다."""
    from PyQt6.QtCore import QPointF
    from datetime import datetime, timedelta
    d = tempfile.mkdtemp()
    p = os.path.join(d, "260904_CH1_PNs_big.dat")
    rng = np.random.default_rng(0)
    n = 30000
    st = rng.choice(["OK", "QC-RMS", "Unstable"], size=n, p=[0.96, 0.03, 0.01])
    t0 = datetime(2026, 9, 4)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(_HDR + _COLS)
        for i in range(n):
            fh.write("\t".join(str(v) for v in (
                f"f{i}", f"{t0 + timedelta(seconds=20 * i):%Y-%m-%d %H:%M:%S}", 1, 0.0012, 1.05,
                120.0, st[i], 0.0, 1.0, 3.5 + rng.normal(), 0.06, 0.09, 0.02)) + "\n")
    w.resize(1200, 800); w.show()
    w._chk_hide_qc.setChecked(False)
    w._path = p
    w._reload()
    QApplication.processEvents()
    sc = w._scatters[0]
    shown = len(sc.points())
    assert 0 < shown < n, f"큰 파일인데 솎지 않음({shown})"
    qc_col = w._FLAG_COLOR["qc"]
    share = np.mean([sp.brush().color().name() == qc_col for sp in sc.points()])
    assert share < 0.10, f"화면의 QC 비율 {share:.0%} — 실제 3 %인데 덮어 보인다"
    # 솎아서 안 그려진 점도 클릭으로 집힌다
    t = w._fit_cache
    j = n // 2 + 7
    lane = w._lanes[0]
    got = w.lane_point_at(lane, QPointF(float(t["time"][j]), float(t["gases"]["NO2"][j])))
    assert got == j, (got, j)
    w._chk_hide_qc.setChecked(True)

    # the next (small) file must get x auto-range back — 2026-10-02 R5: after a >20k-row file
    # every later file was drawn inside the stale x window of the big one
    w._path = _write_fit(tempfile.mkdtemp())
    w._reload()
    QApplication.processEvents()
    vb = w._lanes[0].getViewBox()
    assert vb.autoRangeEnabled()[0], "x auto-range left off after a big file"
    (x0, x1), _ = vb.viewRange()
    tt = w._fit_cache["time"]
    assert x0 <= tt.min() and x1 >= tt.max() and (x1 - x0) < 3600, (x0, x1, tt.min(), tt.max())


def test_residual_refuses_without_meta(w):
    """레거시 결과(= `.meta.json` 없음)는 잔차를 **그리지 않고 사유를 적는다**.

    그때 설정을 복원 못 하면 지금 설정으로 계산한 잔차가 나오는데, 그건 화면의 그때
    농도와 대응하지 않는 조용히 틀린 그림이다 — 빈 패널이 아니라 이유가 떠야 한다.
    """
    d = tempfile.mkdtemp()
    fit = _write_fit(d)
    _write_alpha(d, "260904_CH1_PNs_r3f8a1")
    w._path = fit
    w._reload()
    w._show_scan_detail(1)

    assert not w._pw_resid.plotItem.listDataItems(), "복원 못 했는데 잔차를 그렸다"
    title = w._pw_resid.plotItem.titleLabel.text
    assert "unavailable" in title and "meta" in title, title
    # α는 그대로 보여야 한다 — 잔차가 없다고 상세가 통째로 사라지면 안 된다
    assert len(w._pw_detail.plotItem.listDataItems()) == 1, "alpha까지 사라졌다"


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


def _write_conc_csv(d, bom=False):
    p = os.path.join(d, "conc_KST.csv")
    with open(p, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as fh:
        fh.write("# NIER submission\n")
        fh.write("time_KST,time_UTC,NO2,n_used\n")
        for i in range(5):
            fh.write(f"2026-09-04 19:0{i}:00,2026-09-04 10:0{i}:00,{1.0 + i},10\n")
    return p


def test_view_toggles_leave_non_fit_alone(w):
    """2026-10-02 R4: Hide QC / K / Gas / Err after opening a CSV re-plotted it as a fit
    (ValueError on CSV, 2,048 'gas' lanes on an alpha trace)."""
    d = tempfile.mkdtemp()
    w._path = _write_fit(d)
    w._reload()
    w._path = _write_conc_csv(d)
    w._reload()
    assert w._current_kind == "concentration", w._current_kind
    errs, old_hook = [], sys.excepthook
    sys.excepthook = lambda *a: errs.append(a[1])      # Qt slot exceptions land here
    try:
        w._chk_hide_qc.toggle()
        w._spin_qc_k.setValue(3.0)
        w._chk_err.toggle()
    finally:
        sys.excepthook = old_hook
    assert not errs, f"view toggle re-plotted the CSV as a fit: {errs[0]!r}"
    assert not w._pw_top.isHidden() and w._stack_host.isHidden(), "CSV was re-plotted as a fit"
    w._chk_hide_qc.toggle(); w._spin_qc_k.setValue(0.0); w._chk_err.toggle()


def test_png_of_fit_is_the_lanes(w):
    """2026-10-02 R7: PNG of a fit result saved the hidden `_pw_top` (blank 2400x37)."""
    from PyQt6.QtGui import QImage
    d = tempfile.mkdtemp()
    w._path = _write_fit(d)
    w._reload()
    out = os.path.join(d, "x.png")
    n = w._save_png(out)
    assert n == 4, n                           # 2 gas lanes + shift/squeeze + RMS
    im = QImage(out)
    assert im.width() == 2400 and im.height() > 400, (im.width(), im.height())


def test_stats_follow_open_file(w):
    """2026-10-02 R8: Σ Stats showed the previous fit while a CSV was open; H2O-scale values
    (~1e-13) printed as 0.000."""
    d = tempfile.mkdtemp()
    w._path = _write_fit(d)
    w._reload()
    w._fit_cache["gases"]["CHOCHO"] = w._fit_cache["gases"]["CHOCHO"] * 1e-13
    line = next(s for s in w._stats_lines() if s.startswith("CHOCHO"))
    assert "0.000" not in line and "e-1" in line, line
    w._path = _write_conc_csv(d)
    w._reload()
    assert w._stats_lines() is None, "stats of the previous fit file while a CSV is open"


def test_bom_csv_opens(w):
    """2026-10-02 R11: the NIER KST CSV starts with a UTF-8 BOM, so '\\ufeff# …' was not a
    comment and became the header → "No numeric concentration columns"."""
    from gui.result_viewer_io import detect
    p = _write_conc_csv(tempfile.mkdtemp(), bom=True)
    assert detect(p) == "concentration", detect(p)
    w._path = p
    w._reload()
    assert "Failed" not in w._lbl.text(), w._lbl.text()
    assert "NO2" in [it.name() for it in w._pw_top.plotItem.listDataItems()]


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)   # 참조 유지 필수
    assert app is not None
    w = ResultViewerWidget()
    for fn, args in ((test_loader_exposes_shift_squeeze, ()),
                     (test_flag_classification, ()),
                     (test_lanes_and_click, (w,)),
                     (test_real_click_opens_detail, (w,)),
                     (test_big_file_thinning_keeps_flag_share, (w,)),
                     (test_residual_refuses_without_meta, (w,)),
                     (test_non_fit_restores_old_plots, (w,)),
                     (test_view_toggles_leave_non_fit_alone, (w,)),
                     (test_png_of_fit_is_the_lanes, (w,)),
                     (test_stats_follow_open_file, (w,)),
                     (test_bom_csv_opens, (w,))):
        fn(*args)
        print(f"  PASS  {fn.__name__}")
    print("result lanes self-check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
