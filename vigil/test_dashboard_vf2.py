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


def main():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841
    test_glyphs()
    test_paused_freshness()
    test_tz_labels()
    print(f"\ndashboard VF2: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
