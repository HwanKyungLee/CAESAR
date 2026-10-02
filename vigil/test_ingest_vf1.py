"""Vigil ingest/liveness/alert fixes VF1 (UX audit 2026-10-02, no data needed).

  1) liveness counts only rows routed to a profile — a growing analysis .dat must not mask a raw stop
  2) "no rows seen yet" is SKIP only for a while after start / folder change / Start, then P0
"""
import os
import shutil
import sys
import tempfile
from datetime import timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_self_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_n_pass = _n_fail = 0
NC = 6181


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def _row(t, ncols=NC):
    cs = int(t * 100)
    v = ["0"] * NC
    v[0], v[1], v[4] = str(cs >> 16), str(cs & 0xFFFF), "1"
    v[2053:6149] = ["9000"] * 4096
    return "\t".join(v[:ncols])


def _append(path, lines):
    with open(path, "a") as fh:
        fh.write("\n".join(lines) + "\n")


def _live(core):
    """Current liveness level (open alarm on the 'liveness' source, else OK)."""
    a = core._open_alarms.get("liveness")
    return a["level"] if a else "OK"


def _app(raw, st):
    from vigil.profile import DEFAULT_PROFILE_DIR
    from vigil.run_vigil import VigilApp
    return VigilApp(raw, DEFAULT_PROFILE_DIR, st)


def test_liveness_routed_only(d):
    print("[1] liveness ignores unrouted rows")
    raw, st = os.path.join(d, "raw1"), os.path.join(d, "st1")
    os.makedirs(os.path.join(raw, "alpha"))
    f = os.path.join(raw, "2026-06-20-001 Hot.dat")
    out = os.path.join(raw, "alpha", "alpha_out.dat")
    _append(f, [_row(13_000_000 + k) for k in range(3)])
    _append(out, ["1\t2\t3\t4"])
    core = _app(raw, st)
    core.tick()
    check("raw rows -> liveness OK", _live(core) == "OK", _live(core))
    core._last_arrival -= timedelta(seconds=30)          # raw stopped 30 s ago
    _append(out, ["1\t2\t3\t4"])                          # ... but the analysis output keeps growing
    core.tick()
    check("growing analysis .dat does not keep liveness alive -> P0", _live(core) == "P0", _live(core))


def test_no_rows_escalates(d):
    print("[2] no rows since start -> P0 after the limit")
    from datetime import datetime
    from vigil.monitors.liveness_monitor import NO_ROWS_MIN_SEC, check_liveness
    now = datetime(2026, 6, 20, 12, 0, 0)
    s, _m, _mt = check_liveness(None, now, 10, now - timedelta(seconds=NO_ROWS_MIN_SEC - 1))
    check("before the limit: SKIP", s == "SKIP", s)
    s, m, _mt = check_liveness(None, now, 10, now - timedelta(seconds=NO_ROWS_MIN_SEC + 1), "X:/raw")
    check("after the limit: P0 naming the folder", s == "P0" and "X:/raw" in m, (s, m))
    s, _m, _mt = check_liveness(None, now, 30, now - timedelta(seconds=120))
    check("limit is at least 6 x grace", s == "SKIP", s)
    check("no waiting_since: SKIP as before", check_liveness(None, now, 10)[0] == "SKIP")

    raw, st = os.path.join(d, "raw2"), os.path.join(d, "st2")
    os.makedirs(raw)
    core = _app(raw, st)                                  # empty folder = DAQ dead at restart
    core.tick()
    check("just started: liveness SKIP (not an alarm)", "liveness" not in core._open_alarms)
    core._waiting_since -= timedelta(seconds=NO_ROWS_MIN_SEC + 5)
    core.tick()
    check("no raw for longer than the limit: P0", _live(core) == "P0", _live(core))
    core.pause()
    core.resume()                                         # paused time does not count
    core.tick()
    check("after Start the wait restarts", "liveness" not in core._open_alarms)


def main():
    from PyQt6.QtCore import QCoreApplication
    _app_qt = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])  # noqa: F841
    d = tempfile.mkdtemp()
    try:
        test_liveness_routed_only(d)
        test_no_rows_escalates(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(f"\nVF1 ingest tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
