"""Vigil ingest/liveness/alert fixes VF1 (UX audit 2026-10-02, no data needed).

  1) liveness counts only rows routed to a profile — a growing analysis .dat must not mask a raw stop
  2) "no rows seen yet" is SKIP only for a while after start / folder change / Start, then P0
  3) aggregate never says "normal — all OK" while sources were not evaluated
  5) empty watch folder: the first file is seen on the next poll, not at the next full listing
  6) same file name in hot/ and cold/ is not a "collected twice" copy unless size and first line match
  7) a tick that fails mid-batch says how many rows went unmonitored
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


def test_aggregate_not_evaluated():
    print("[3] aggregate counts SKIP as not evaluated")
    from vigil.alert_engine import aggregate
    live = ("liveness", "OK", "", {})
    s, m = aggregate([live])
    check("liveness alone is not 'normal — all 1 OK'", s == "P2" and "only raw inflow" in m, (s, m))
    s, m = aggregate([live, ("conc:a", "SKIP", "", {}), ("conc:b", "SKIP", "", {})])
    check("liveness OK + every monitor SKIP -> P2, says so", s == "P2" and "only raw inflow" in m, (s, m))
    s, m = aggregate([live, ("hk:x", "OK", "", {}), ("conc:a", "SKIP", "", {}), ("conc:b", "SKIP", "", {})])
    check("OK k/n · not evaluated m", s == "OK" and "OK 2/4" in m and "not evaluated 2" in m, (s, m))
    s, m = aggregate([live, ("hk:x", "OK", "", {})])
    check("all evaluated -> normal — all 2 OK", s == "OK" and m == "normal — all 2 OK", (s, m))
    s, m = aggregate([("liveness", "SKIP", "", {}), ("conc:a", "SKIP", "", {})])
    check("nothing evaluated -> SKIP", s == "SKIP", (s, m))
    s, m = aggregate([live, ("hk:x", "P1", "", {}), ("conc:a", "SKIP", "", {})])
    check("P1 message also counts not evaluated", s == "P1" and "not evaluated 1" in m, (s, m))


def test_empty_folder_first_file(d):
    print("[5] empty folder -> first file on the next poll")
    import time
    from vigil.ingest_cursor import IngestCursor
    from vigil.profile import ProfileSet
    from vigil.watcher import Watcher
    raw = os.path.join(d, "raw5")
    os.makedirs(raw)
    w = Watcher(raw, ProfileSet.load_default(), IngestCursor(os.path.join(d, "c5.json")), rescan_sec=3600)
    w.poll()
    nxt = w._next_full
    w.poll()
    check("nothing changed: no extra full listing", w._next_full == nxt)
    time.sleep(0.05)                                      # coarse folder mtime clocks
    os.makedirs(os.path.join(raw, "2026-06"))
    f = os.path.join(raw, "2026-06", "2026-06-20-001 Hot.dat")
    _append(f, [_row(13_000_000 + k) for k in range(2)])
    ev = []
    for _ in range(2):                                    # (a new subfolder may need one more listing)
        ev += w.poll()
    check("rows of the first file seen within 2 polls (full listing is 3600 s away)",
          len(ev) == 2 and all(e.profile_id for e in ev), len(ev))


def test_duplicate_names(d):
    print("[6] duplicate-name warning only for real copies")
    import logging
    from vigil.ingest_cursor import IngestCursor
    from vigil.profile import ProfileSet
    from vigil.watcher import Watcher
    raw = os.path.join(d, "raw6")
    for sub in ("hot", "cold", "copy"):
        os.makedirs(os.path.join(raw, sub))
    _append(os.path.join(raw, "hot", "2026-06-01-001.dat"), ["1	2	3"] * 5)
    _append(os.path.join(raw, "cold", "2026-06-01-001.dat"), ["4	5	6	7"] * 5)   # other size
    _append(os.path.join(raw, "hot", "2026-06-01-002.dat"), ["1	2	3"] * 5)
    _append(os.path.join(raw, "cold", "2026-06-01-002.dat"), ["1	2	9"] * 5)      # same size, other line
    for sub in ("hot", "cold"):                                                      # fresh rollover files
        open(os.path.join(raw, sub, "2026-06-01-003.dat"), "w").close()
    _append(os.path.join(raw, "copy", "2026-06-01-001.dat"), ["1	2	3"] * 5)      # a real copy of hot/001
    msgs = []

    class _H(logging.Handler):
        def emit(self, r):
            msgs.append(r.getMessage())
    h = _H()
    logging.getLogger("vigil").addHandler(h)
    try:
        Watcher(raw, ProfileSet.load_default(), IngestCursor(os.path.join(d, "c6.json"))).poll()
    finally:
        logging.getLogger("vigil").removeHandler(h)
    dup = [m for m in msgs if "same file name" in m]
    check("one warning, for the real copy only", len(dup) == 1 and "2026-06-01-001.dat" in dup[0]
          and "cold" not in dup[0], dup)


def test_dropped_rows_logged(d):
    print("[7] failing tick reports the dropped rows")
    import json
    import vigil.run_vigil as rv
    raw, st = os.path.join(d, "raw7"), os.path.join(d, "st7")
    os.makedirs(raw)
    _append(os.path.join(raw, "2026-06-20-001 Hot.dat"), [_row(13_000_000 + k) for k in range(10)])
    core = _app(raw, st)
    real, calls = rv.evaluate_hk, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("boom")
        return real(*a, **k)
    rv.evaluate_hk = flaky
    try:
        core.tick()                                       # row index 3 fails -> rows 3..9 never monitored
    finally:
        rv.evaluate_hk = real
    lines = [json.loads(x) for x in open(os.path.join(st, "status.jsonl"), encoding="utf-8")]
    err = [x for x in lines if x.get("kind") == "internal"]
    check("internal error line says 7 rows were skipped", err and "7 raw row(s)" in err[0]["msg"],
          err[:1])
    core.tick()
    lines = [json.loads(x) for x in open(os.path.join(st, "status.jsonl"), encoding="utf-8")]
    rec = [x for x in lines if x.get("kind") == "internal" and x["status"] == "OK"]
    check("recovery line carries the total", rec and rec[0].get("dropped_rows") == 7, rec[:1])


def main():
    from PyQt6.QtCore import QCoreApplication
    _app_qt = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])  # noqa: F841
    d = tempfile.mkdtemp()
    try:
        test_liveness_routed_only(d)
        test_no_rows_escalates(d)
        test_aggregate_not_evaluated()
        test_empty_folder_first_file(d)
        test_duplicate_names(d)
        test_dropped_rows_logged(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(f"\nVF1 ingest tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
