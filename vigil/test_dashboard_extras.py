"""Vigil 2026-10-01 개편 자체검증 (데이터 불필요, Qt offscreen).

  1) 1분 기록(.vrec): interval 당 한 줄, 읽기 왕복, 잘린 꼬리 무시, 열 바뀌면 새 파일, 재시작 이어 쓰기
  2) 다른 PC 경로(datapaths.rebase): 있으면 그대로, 꼬리로 찾기, 파일 이름만으론 안 찾음
  3) 경보 이력: 시작·해소 한 줄, 진행 중 최악 등급 유지
  4) HK 추세 10 s 간격(판정·현재값은 매 행)
  5) 대시보드: 카드·경보표·신선도·KST/UTC·범위 밖 표시·바뀐 칸만 갱신·reset
"""
import os
import shutil
import struct
import sys
import tempfile
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_self_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np  # noqa: E402

_n_pass = _n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def test_record(d):
    print("[1] 1분 기록")
    from vigil.record import MinuteRecorder, read_records
    rec = MinuteRecorder(d)
    t0 = 1_790_000_040.0                      # 분 경계 안쪽
    check("첫 줄 씀", rec.maybe_write(t0, {"a": 1.0, "b": None}))
    check("같은 분엔 안 씀", not rec.maybe_write(t0 + 10, {"a": 2.0, "b": 3.0}))
    check("다음 분엔 씀", rec.maybe_write(t0 + 60, {"a": 2.0, "b": 3.0}))
    path = rec._path
    cols, t, v = read_records(path)
    check("왕복: 열·시각·값", cols == ["a", "b"] and list(t) == [t0, t0 + 60] and v[1, 1] == 3.0, (cols, t, v))
    check("None → NaN", np.isnan(v[0, 1]))
    check("CSV 대비 가벼움(레코드 16 B)", os.path.getsize(path) == 2 * (8 + 4 * 2))
    with open(path, "ab") as fh:
        fh.write(struct.pack("<d", t0 + 120))  # 정전으로 잘린 꼬리
    check("잘린 꼬리 무시", len(read_records(path)[1]) == 2)
    rec.maybe_write(t0 + 180, {"a": 1.0, "b": 2.0, "c": 3.0})
    check("열 바뀌면 새 파일(_2)", rec._path != path and rec._path.endswith("_2.vrec"), rec._path)
    rec2 = MinuteRecorder(d)
    rec2.maybe_write(t0 + 240, {"a": 1.0, "b": 2.0})
    check("재시작 — 같은 열이면 이어 씀", rec2._path == path and len(read_records(path)[1]) >= 3)


def test_datapaths(d):
    print("[2] 다른 PC 경로")
    from vigil.datapaths import rebase, rebase_fitset_channel
    root = os.path.join(d, "Output2")
    os.makedirs(os.path.join(root, "fit setting"))
    f = os.path.join(root, "fit setting", "X.json")
    open(f, "w").write("{}")
    check("있는 경로는 그대로", rebase(f, root) == f)
    check("꼬리로 찾음", os.path.samefile(rebase("C:/Nowhere/Output/fit setting/X.json", root), f))
    check("data_root 없으면 원래 경로", rebase("C:/Nowhere/a/X.json", None) == "C:/Nowhere/a/X.json")
    open(os.path.join(root, "X.json"), "w").write("{}")
    check("파일 이름만으론 안 찾음", rebase("C:/Nowhere/zzz/X.json", root) == "C:/Nowhere/zzz/X.json")
    ch = {"wl_path": "C:/Nowhere/Output/fit setting/X.json", "refs": [{"path": "D:/q/fit setting/X.json"}]}
    out = rebase_fitset_channel(ch, root)
    check("FitSet 채널 사본만 바뀜", os.path.samefile(out["refs"][0]["path"], f)
          and ch["refs"][0]["path"] == "D:/q/fit setting/X.json")


def test_alarms_and_hk(d):
    print("[3] 경보 이력 · [4] HK 10 s 간격")
    from vigil.alert_engine import OK, P1, P2
    from vigil.profile import DEFAULT_PROFILE_DIR
    from vigil.run_vigil import VigilApp
    app = VigilApp(None, DEFAULT_PROFILE_DIR, os.path.join(d, "st_a"))
    t = datetime(2026, 10, 1, 12, 0, 0)
    app._update_alarms([("hk", P2, "warm", {}), ("lamp", OK, "ok", {})], t)
    app._update_alarms([("hk", P1, "hot", {})], t + timedelta(seconds=5))
    app._update_alarms([("hk", P2, "warm", {})], t + timedelta(seconds=10))
    check("한 경보는 한 줄", len(app.alarms) == 1, app.alarms)
    check("진행 중 최악 등급 유지", app.alarms[0]["level"] == P1 and app.alarms[0]["end"] is None)
    app._update_alarms([("hk", OK, "ok", {})], t + timedelta(seconds=20))
    check("해소 시각 기록", app.alarms[0]["end"] == t + timedelta(seconds=20))
    app._update_alarms([("hk", P2, "again", {})], t + timedelta(seconds=30))
    check("재발은 새 줄", len(app.alarms) == 2)

    from vigil.test_pause import _rows
    raw = os.path.join(d, "raw")
    os.makedirs(raw)
    f = os.path.join(raw, "2026-06-20-001.dat")
    open(f, "w").write(_rows(5, 13_000_000))
    app2 = VigilApp(raw, DEFAULT_PROFILE_DIR, os.path.join(d, "st_b"))
    app2.tick()
    open(f, "a").write(_rows(5, 13_000_005))
    app2.tick()
    lens = {k: len(v) for k, v in app2._hk_trend.items()}
    check("HK 현재값은 매 행", bool(app2._hk_latest), "HK 필드 없음")
    check("HK 추세는 10 s 안에 한 점", lens and all(n == 1 for n in lens.values()), lens)
    cards = app2._cards()
    check("HK 카드 생성", any(c["key"][0] == "hk" for c in cards))
    vals = app2._record_values(OK, datetime.now())
    check("기록 열: overall·나이·hk", "overall" in vals and "last_row_age_s" in vals
          and any(k.startswith("hk:") for k in vals), list(vals)[:5])


def test_dashboard():
    print("[5] 대시보드")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841
    from vigil.alert_engine import OK, P1, P2
    from vigil.dashboard.dashboard_window import DashboardWindow, _robust_range
    win = DashboardWindow(title="t", tz="UTC")
    now = datetime.now()
    win.update_cards([{"key": "a", "title": "A", "value": "1", "sub": "", "status": OK},
                      {"key": "b", "title": "B", "value": "2", "sub": "", "status": P1}])
    check("카드 2개", len(win._cards) == 2)
    win.update_cards([{"key": "a", "title": "A", "value": "3", "sub": "", "status": OK}])
    check("사라진 카드 제거·값 갱신", list(win._cards) == ["a"] and win._cards["a"].v.text() == "3")
    win.update_alarms([{"start": now, "end": None, "source": "hk", "level": P2, "msg": "warm"},
                       {"start": now, "end": now, "source": "lamp", "level": P1, "msg": "x"}])
    check("경보표 최근 것이 위", win.alarm_table.rowCount() == 2 and win.alarm_table.item(0, 3).text() == "lamp")
    check("진행 중 개수 탭", win.tabs.tabText(1) == "Alarms (1)", win.tabs.tabText(1))
    win.set_freshness(now - timedelta(seconds=30), now, 10)
    check("신선도: 30 s, 한도 넘음 표시", "30 s ago" in win.fresh.text() and "UTC" in win.fresh.text())
    ax = win.p_hk.getAxis('bottom')
    check("UTC offset 0", ax.utcOffset == 0)
    win.cb_tz.setCurrentText("KST")
    check("KST offset −32400, 라벨", ax.utcOffset == -32400 and "KST" in ax.labelText)
    lo, hi = _robust_range([(range(100), [1.0] * 99 + [1e6])])
    check("스파이크 하나에 안 뭉개짐", hi < 10, (lo, hi))
    trend = {("p", "f"): [(now + timedelta(seconds=10 * k), 1.0 + 0.01 * k) for k in range(50)]
             + [(now + timedelta(seconds=500), 1e6)]}
    win.update_hk_trend(trend, {("p", "f"): {"label": "f"}})
    out = win._out_items["hk"]
    check("범위 밖 점은 가장자리 표시", len(out.data) == 1)
    rows = {"/x/a.dat": {"last_row": now, "lag": 1.0, "hk_status": OK}}
    win.update_files(rows)
    it = win.table.item(0, 0)
    win.update_files(rows)
    check("파일 표: 같은 행은 항목 재사용", win.table.item(0, 0) is it)
    win.reset_views()
    check("reset 이 카드·경보·표를 비움", not win._cards and win.alarm_table.rowCount() == 0
          and win.table.rowCount() == 0)


def main():
    d = tempfile.mkdtemp()
    try:
        test_record(d)
        test_datapaths(d)
        test_alarms_and_hk(d)
        test_dashboard()
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(f"\ndashboard extras: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
