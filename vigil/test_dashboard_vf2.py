"""Vigil dashboard / operator fixes (VF2, 2026-10-02) — no data needed, Qt offscreen.

  1) UI strings use only glyphs that render (★ and ⏸ showed as □)
"""
import ast
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_self_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_n_pass = _n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def test_glyphs():
    print("[1] UI glyphs")
    from vigil.dashboard import dashboard_window as dw
    tree = ast.parse(open(dw.__file__, encoding="utf-8").read())
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    used = {c for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docs for c in n.value if ord(c) > 127}
    check("only known-good glyphs in UI strings", used <= dw.UI_GLYPHS, "".join(sorted(used - dw.UI_GLYPHS)))


def test_paused_freshness():
    print("[2] freshness while paused")
    from datetime import datetime, timedelta
    from vigil.dashboard.dashboard_window import DashboardWindow
    win = DashboardWindow(title="t", tz="UTC")
    win.set_watch_dir("C:/raw")
    now = datetime.now()
    win.set_freshness(now - timedelta(seconds=7), now, 10)
    check("running: age shown", "7 s ago" in win.fresh.text(), win.fresh.text())
    win.set_running(False)
    check("paused: no frozen age", "paused" in win.fresh.text() and "ago" not in win.fresh.text(), win.fresh.text())
    win.set_running(True)
    win.set_freshness(now - timedelta(seconds=3), now, 10)
    check("resumed: age again", "3 s ago" in win.fresh.text(), win.fresh.text())


def test_tz_labels():
    print("[3] time-zone labels")
    import tempfile
    from vigil.dashboard.dashboard_window import DashboardWindow
    from vigil.state_log import StateLog
    win = DashboardWindow(title="t", tz="KST")
    hdr = lambda t, c: t.horizontalHeaderItem(c).text()
    check("files header", hdr(win.table, 1) == "Last row (KST)", hdr(win.table, 1))
    check("alarm headers", (hdr(win.alarm_table, 0), hdr(win.alarm_table, 1)) == ("Start (KST)", "End (KST)"))
    win.log_line("x")
    check("log line names zone", " KST] x" in win.log.toPlainText(), win.log.toPlainText())
    win.cb_tz.setCurrentText("UTC")
    check("headers follow switch", hdr(win.table, 1) == "Last row (UTC)" and hdr(win.alarm_table, 1) == "End (UTC)")
    with tempfile.TemporaryDirectory() as d:
        sl = StateLog(os.path.join(d, "s.jsonl"))
        sl.append("OK", "m")
        ts = sl.tail(1)[0]["ts"]
    check("status.jsonl ts has offset", ts[-6] in "+-" and ts[-3] == ":", ts)


def test_record_one_file_per_day():
    print("[4] .vrec: one file per local day, columns grow in place")
    import math
    import shutil
    import tempfile
    from datetime import datetime
    from vigil.record import MinuteRecorder, _finish_grow, read_records
    d = tempfile.mkdtemp()
    try:
        t0 = datetime(2026, 10, 2, 0, 30).timestamp()      # local 00:30 — the UTC date is the day before in KST
        rec = MinuteRecorder(d)
        rec.maybe_write(t0, {"overall": 0.0, "hk:a": 1.0})
        rec.maybe_write(t0 + 60, {"overall": 0.0, "hk:a": 2.0, "R:x": 0.99})
        rec.maybe_write(t0 + 120, {"overall": 1.0, "hk:a": 3.0, "R:x": 0.98, "conc:x:NO2_ppb": 5.0})
        files = sorted(f for f in os.listdir(os.path.join(d, "records")) if f.endswith(".vrec"))
        check("one file, named by local date", files == ["2026-10-02.vrec"], files)
        cols, t, v = read_records(rec._path)
        check("columns are the union", cols == ["overall", "hk:a", "R:x", "conc:x:NO2_ppb"], cols)
        check("old rows kept, new columns NaN", list(v[:, 1]) == [1, 2, 3] and math.isnan(v[0, 2])
              and math.isnan(v[1, 3]) and v[2, 3] == 5.0, v)
        rec2 = MinuteRecorder(d)                             # restart with fewer columns (monitors not up yet)
        rec2.maybe_write(t0 + 180, {"overall": 0.0, "hk:a": 4.0})
        cols, t, v = read_records(rec2._path)
        check("restart appends with NaN for missing", rec2._path == rec._path and len(t) == 4
              and math.isnan(v[3, 2]) and v[3, 1] == 4.0, (len(t), v[-1]))

        # interrupted rewrite: each crash point leaves one complete version
        path = rec._path
        good = open(path, "rb").read(), open(path + ".json", "rb").read()

        def restore():
            open(path, "wb").write(good[0]); open(path + ".json", "wb").write(good[1])
        open(path + ".grow", "wb").write(b"partial")             # crashed while writing new data
        _finish_grow(path)
        check("half-written .grow dropped", not os.path.exists(path + ".grow") and len(read_records(path)[1]) == 4)
        rec3 = MinuteRecorder(d)
        rec3._open("2026-10-02", ["overall"])
        rec3._grow(path, rec3._columns + ["new"])                 # complete grow, then simulate crash points
        grown = open(path, "rb").read(), open(path + ".json", "rb").read()
        restore()
        open(path + ".grow", "wb").write(grown[0]); open(path + ".grow.json", "wb").write(grown[1])
        os.replace(path + ".grow", path)                          # crashed between the two replaces
        cols, t, _v = read_records(path)
        check("reader uses .grow.json mid-commit", cols[-1] == "new" and len(t) == 4, cols)
        _finish_grow(path)
        cols, t, _v = read_records(path)
        check("restart finishes the commit", cols[-1] == "new" and len(t) == 4
              and not os.path.exists(path + ".grow.json"), cols)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_trend_skip():
    print("[5] trends: no redraw when nothing changed, cheap pens")
    from collections import deque
    from datetime import datetime, timedelta
    from vigil.dashboard.dashboard_window import DashboardWindow
    win = DashboardWindow(title="t", tz="UTC")
    now = datetime.now()
    hk = {("p", "f"): deque([(now + timedelta(seconds=10 * k), 1.0) for k in range(5)], maxlen=5)}
    meta = {("p", "f"): {"label": "f", "warn": [0, 2]}}
    win.update_hk_trend(hk, meta)
    item = win._curve_items[("hk", ("p", "f"))]
    calls = []
    real = item.setData
    item.setData = lambda *a, **k: (calls.append(1), real(*a, **k))
    win.update_hk_trend(hk, meta)
    check("unchanged deque: no setData", not calls, len(calls))
    hk[("p", "f")].append((now + timedelta(seconds=60), 1.5))           # full deque: same length, new point
    win.update_hk_trend(hk, meta)
    check("full deque gets a point: redrawn", len(calls) == 1, len(calls))
    check("live curve: width 1, no antialias", item.opts["pen"].widthF() <= 1 and item.opts["antialias"] is False,
          (item.opts["pen"].widthF(), item.opts["antialias"]))


def test_hk_view():
    print("[6] HK graph: % of band by default, one field in real units with only its lines")
    from datetime import datetime, timedelta
    from vigil.dashboard.dashboard_window import DashboardWindow
    win = DashboardWindow(title="t", tz="UTC")
    now = datetime.now()
    trend = {("p", "press"): [(now + timedelta(seconds=10 * k), 915.0) for k in range(5)],
             ("p", "oven"): [(now + timedelta(seconds=10 * k), 300.0) for k in range(5)],
             ("p", "led"): [(now + timedelta(seconds=10 * k), 30.0) for k in range(5)]}
    meta = {("p", "press"): {"label": "ANs cavity P", "unit": "mbar", "warn": [880, 950], "alarm": [830, 1000]},
            ("p", "oven"): {"label": "ANs oven SP", "unit": "degC", "warn": [295, 305], "alarm": [285, 315]},
            ("p", "led"): {"label": "LED1 temp", "unit": "degC", "warn": [15, 45]}}
    win.update_hk_trend(trend, meta)
    ys = {k[1]: list(win._curve_items[("hk", k)].getData()[1]) for k in trend}
    check("normalised to % of warn band", ys["press"][0] == 50.0 and ys["oven"][0] == 50.0 and ys["led"][0] == 50.0, ys)
    check("all view: two shared lines (0, 100)", sorted(ln.value() for ln, _c in win._hk_lines) == [0.0, 100.0])
    check("combo lists every field", win.cb_hk.count() == 4, win.cb_hk.count())
    win.cb_hk.setCurrentIndex([win.cb_hk.itemData(i) for i in range(win.cb_hk.count())].index(("p", "press")))
    item = win._curve_items[("hk", ("p", "press"))]
    check("one field: real units", list(item.getData()[1])[0] == 915.0)
    check("one field: others hidden", not win._curve_items[("hk", ("p", "oven"))].isVisible())
    check("one field: only its warn+alarm lines", sorted(ln.value() for ln, _c in win._hk_lines) == [830, 880, 950, 1000],
          [ln.value() for ln, _c in win._hk_lines])
    check("axis names the field and unit", "ANs cavity P (mbar)" in win.p_hk.getAxis("left").labelText)
    win.reset_views()
    check("reset clears the field list", win.cb_hk.count() == 1 and win._hk_sel is None and not win._hk_lines)


def test_realert():
    print("[7] P0 re-alert")
    from vigil.alert_engine import OK, P0
    from vigil.dashboard import dashboard_window as dw
    win = dw.DashboardWindow(title="t", tz="UTC")
    clock = [1000.0]
    alerts = []
    real_mono, real_alert = dw.time.monotonic, dw.QApplication.alert
    dw.time.monotonic = lambda: clock[0]
    dw.QApplication.alert = staticmethod(lambda *a, **k: alerts.append(clock[0]))
    try:
        win.set_status(P0, "stopped")
        clock[0] += 60; win.set_status(P0, "stopped")
        check("one alert on entering P0", alerts == [1000.0], alerts)
        clock[0] += dw.REALERT_SEC; win.set_status(P0, "stopped")
        check("again after REALERT_SEC while P0 persists", len(alerts) == 2, alerts)
        clock[0] += 10; win.set_status(OK, "ok"); win.set_status(P0, "stopped")
        check("new P0 episode alerts at once", len(alerts) == 3, alerts)
    finally:
        dw.time.monotonic, dw.QApplication.alert = real_mono, real_alert


def test_badge_cause():
    print("[8] badge names the worst cause and an action")
    from vigil.alert_engine import OK, P0, P1, aggregate
    from vigil.dashboard.dashboard_window import DashboardWindow
    win = DashboardWindow(title="t", tz="UTC")
    results = [("liveness", P0, "measurement stopped? — last row 49s ago (limit 10s)", {}),
               ("hk:2026-06-03-006.dat", P1, "ANs cavity P=689.50 mbar out of band", {}),
               ("conc:ch_ans", P1, "x" * 300, {})]
    win.set_results(results)
    win.set_status(*aggregate(results))
    txt = win.badge.text()
    check("P0: cause + action", txt.startswith("■  P0  Measurement stopped — measurement stopped? — last row 49s ago")
          and "Check LabVIEW acquisition" in txt and "+2 more" in txt, txt)
    win.set_results([r for r in results if r[1] != P0] + [("liveness", OK, "ok", {})])
    win.set_status(P1, "P1 ×2 — quality at risk (P2 0)")
    txt = win.badge.text()
    check("P1: first worst (HK) named", "Housekeeping out of band — ANs cavity P=689.50" in txt
          and "cavity pressure" in txt, txt)
    win.set_results([("conc:ch_ans", P1, "x" * 300, {})])
    win.set_status(P1, "P1 ×1")
    check("long message clipped, full text in tooltip", len(win.badge.text().splitlines()[0]) < 160
          and "x" * 300 in win.badge.toolTip())
    win.set_status(P1, "Vigil internal error, 1 in a row: X")      # no fresh results → no stale cause
    check("no results: message as is", "Vigil internal error" in win.badge.text(), win.badge.text())
    check("badge never sets the minimum width", win.badge.minimumSizeHint().width() < 400 or
          win.badge.sizePolicy().horizontalPolicy().name == "Ignored")


def main():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841
    test_glyphs()
    test_paused_freshness()
    test_tz_labels()
    test_record_one_file_per_day()
    test_trend_skip()
    test_hk_view()
    test_realert()
    test_badge_cause()
    print(f"\ndashboard VF2: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
