"""화면 peak 솎아내기(gui/pg_perf.py)가 NaN 섞인 큰 시리즈의 선을 지우지 않는가.

2026-10-02 리뷰: pyqtgraph 0.14 `peak`는 구간마다 max/min(axis=1) 이라 구간에 NaN 이 하나만 있어도
그 구간 전체가 NaN → 안 그려진다. 26만 점·NaN 1 %(QC 숨김·필터·핏 실패)에서 화면 점의 ~50 %가
사라지고, 그 구간의 스파이크도 함께 사라졌다.

  1. add_fast_curve(NaN 1 %) — 화면(솎은) 점이 전부 유한, 원본 유한 비율만큼 그려진다
  2. 스파이크(NaN 과 같은 구간)가 화면 최댓값에 남는다
  3. NaN 이 있던 자리는 선이 끊긴다(connect=False) — 빈 구간을 잇지 않는다
  4. make_fast 를 이미 NaN 째 데이터가 든 아이템에 걸어도(ui_result_viewer Shift/RMS 경로) 같다
  5. 작은 시리즈(<=BIG)는 손대지 않는다(무회귀)

사용: python tools/test_pg_perf_nan.py  → 전부 PASS면 exit 0
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from gui import pg_perf

_n_pass = _n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def _display(pw, item):
    pw.resize(800, 400)
    pw.show()
    pw.getPlotItem().vb.autoRange()
    _app.processEvents()
    ds = item._getDisplayDataset()
    return np.asarray(ds.x), np.asarray(ds.y), ds.connect


def main():
    rng = np.random.default_rng(0)
    n = 260_000
    x = np.arange(n, dtype=float)
    y = rng.normal(10.0, 1.0, n)
    nan_idx = rng.choice(n, n // 100, replace=False)
    y[nan_idx] = np.nan
    spike_at = int(nan_idx[500]) + 1           # NaN 바로 옆 = 같은 솎기 구간
    y[spike_at] = 1000.0

    # 1~3. add_fast_curve
    pw = pg.PlotWidget()
    item = pg_perf.add_fast_curve(pw, x, y, pen='k')
    dx, dy, conn = _display(pw, item)
    check("솎아내기가 실제로 걸렸다(화면 점 < 원본)", len(dy) < n // 4, f"{len(dy)}")
    fin = np.isfinite(dy).mean() if len(dy) else 0.0
    check("화면 점이 전부 유한(NaN 구간이 통째로 안 사라짐)", fin == 1.0, f"finite {fin:.3f}")
    check("스파이크가 화면에 남는다", np.nanmax(dy) == 1000.0, f"max {np.nanmax(dy)}")
    ox, oy = item.getOriginalDataset()
    check("원본 데이터셋엔 NaN 없음 · 유한 점 수 그대로",
          np.isfinite(oy).all() and len(oy) == np.isfinite(y).sum(), f"{len(oy)}")
    c = item.opts['connect']
    k = int(np.searchsorted(ox, nan_idx[10]))   # NaN 바로 뒤 점의 위치
    check("NaN 자리에서 선이 끊긴다", isinstance(c, np.ndarray) and not c[k - 1], "")
    # 끊김 수 == NaN 이 만든 빈 구간 수(연속 NaN 은 한 구간) — 나머지는 전부 이어진다
    bad = np.zeros(n, bool); bad[nan_idx] = True
    n_gaps = int(np.sum(bad[1:-1] & ~bad[:-2]))   # 맨 앞이 아닌 NaN 구간의 시작 수
    check("끊김 수 == NaN 빈 구간 수(그 밖은 이어짐)",
          isinstance(c, np.ndarray) and int((~c[:-1]).sum()) == n_gaps,
          f"{None if not isinstance(c, np.ndarray) else int((~c[:-1]).sum())} vs {n_gaps}")

    # 4. make_fast 를 데이터가 든 아이템에(ui_result_viewer 의 _fast(pw.plot(...)))
    pw2 = pg.PlotWidget()
    item2 = pg_perf.make_fast(pw2.plot(x, y, pen='k'))
    dx2, dy2, _ = _display(pw2, item2)
    fin2 = np.isfinite(dy2).mean() if len(dy2) else 0.0
    check("make_fast(기존 데이터) — 화면 점 전부 유한", fin2 == 1.0, f"finite {fin2:.3f}")
    check("make_fast(기존 데이터) — 스파이크 남음", np.nanmax(dy2) == 1000.0)

    # 5. 작은 시리즈는 그대로
    pw3 = pg.PlotWidget()
    xs, ys = x[:1000], y[:1000].copy()
    item3 = pg_perf.add_fast_curve(pw3, xs, ys, pen='k')
    _, oy3 = item3.getOriginalDataset()
    check("작은 시리즈는 원본 그대로(NaN 포함)", len(oy3) == 1000)

    print(f"\n결과: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
