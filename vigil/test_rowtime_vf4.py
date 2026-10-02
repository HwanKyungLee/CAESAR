# -*- coding: utf-8 -*-
"""vigil/test_rowtime_vf4.py — §1.4 row-time sequence checks (VF4, 2026-10-03, no data needed).

Before: row_time was decoded and never used — a +3600 s jump, a −7200 s backward step, a skipped
rollover and a file holding only its header row raised nothing (audit 2026-10-02 V1 §6, e9/e3).

  1) RowTimeMonitor: backward / jump inside a file, gap or backwards step across a rollover,
     no gap across files that were skipped as backlog, rollover overdue, event hold expiry
  2) VigilApp: a missing hour between files and a header-only newest file reach the results
  3) Dec-31 file: rows after midnight decode to Jan 1 of the next year, not a year back

    python vigil/test_rowtime_vf4.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_self_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from vigil.alert_engine import OK, P2
from vigil.monitors.clock_monitor import RowTimeMonitor

NC = 6181
T0 = datetime(2026, 6, 20)


def _row(sec_of_year, ncols=NC):
    cs = int(sec_of_year * 100)
    v = ["0"] * NC
    v[0], v[1], v[4] = str(cs >> 16), str(cs & 0xFFFF), "1"
    v[2053:6149] = ["9000"] * 4096
    return "\t".join(v[:ncols])


def _append(path, lines):
    with open(path, "a") as fh:
        fh.write("\n".join(lines) + "\n")


def test_monitor():
    now = datetime.now()
    t = lambda s: T0 + timedelta(seconds=s)
    m = RowTimeMonitor(rollover_sec=3600)
    for s in range(5):
        m.observe("a/001.dat", t(s), now)
    assert m.status(now)[0] == OK
    m.observe("a/001.dat", t(4 - 10), now)                       # 10 s back inside the file
    st = m.status(now)
    assert st[0] == P2 and "backwards" in st[1], st
    assert m.status(now + timedelta(seconds=601))[0] == OK        # event clears after the hold

    m = RowTimeMonitor(rollover_sec=3600)
    m.observe("a/001.dat", t(0), now); m.observe("a/001.dat", t(1), now)
    m.observe("a/001.dat", t(400), now)                          # 6.6 min jump inside
    assert "jumped" in m.status(now)[1]

    m = RowTimeMonitor(rollover_sec=3600)
    m.observe("a/001.dat", t(3599), now)
    m.observe("a/002.dat", t(3600 + 3600), now)                  # an hour of rows missing
    assert "missing between" in m.status(now)[1], m.status(now)
    m = RowTimeMonitor(rollover_sec=3600)
    m.observe("a/001.dat", t(3599), now)
    m.observe("a/003.dat", t(7200), now, files_between=lambda a, b: True)   # 002 skipped as backlog
    assert m.status(now)[0] == OK
    m = RowTimeMonitor(rollover_sec=3600)
    m.observe("a/002.dat", t(3600), now)
    m.observe("a/001.dat", t(0), now)                            # catch-up revisits an older file
    assert m.status(now)[0] == OK
    m.observe("a/003.dat", t(3600 - 7200), now)                  # next file starts 2 h earlier
    assert "backwards at the rollover" in m.status(now)[1]

    m = RowTimeMonitor(rollover_sec=3600)
    for s in range(0, 3600 + 200, 50):                           # 63 min without a new file
        m.observe("a/001.dat", t(s), now)
    assert "without a new file" in m.status(now)[1]
    print("  PASS  RowTimeMonitor")


def test_app(d):
    from vigil.profile import DEFAULT_PROFILE_DIR
    from vigil.run_vigil import VigilApp
    raw, st = os.path.join(d, "raw"), os.path.join(d, "st")
    os.makedirs(raw)
    base = (T0 - datetime(2026, 1, 1)).total_seconds()
    f1 = os.path.join(raw, "2026-06-20-001 Hot.dat")
    f2 = os.path.join(raw, "2026-06-20-003 Hot.dat")
    _append(f1, [_row(base + k) for k in range(5)])
    _append(f2, [_row(base + 7200 + k) for k in range(5)])        # 002 never written: 2 h gap
    core = VigilApp(raw, DEFAULT_PROFILE_DIR, st)
    core.tick()
    res = {n: (s, m) for n, s, m, _ in core._rowtime_results(datetime.now())}
    rt = [v for k, v in res.items() if k.startswith("rowtime:")]
    assert rt and rt[0][0] == P2 and "missing between" in rt[0][1], res

    f3 = os.path.join(raw, "2026-06-20-004 Hot.dat")
    _append(f3, [_row(0, ncols=6177)])                           # header row only
    for p, age in ((f1, 140), (f2, 130), (f3, 120)):
        os.utime(p, (time.time() - age,) * 2)
    core.watcher._files.clear()
    core.tick()
    res = {n: (s, m) for n, s, m, _ in core._rowtime_results(datetime.now())}
    assert res.get("ingest:header_only", (None,))[0] == P2, res
    print("  PASS  VigilApp: hour missing between files, header-only newest file")


def test_year_end(d):
    from vigil.profile import DEFAULT_PROFILE_DIR
    from vigil.run_vigil import VigilApp
    raw, st = os.path.join(d, "raw_ye"), os.path.join(d, "st_ye")
    os.makedirs(raw)
    f = os.path.join(raw, "2025-12-31-024 Hot.dat")
    last_dec = (datetime(2025, 12, 31, 23, 59, 59) - datetime(2025, 1, 1)).total_seconds()
    _append(f, [_row(last_dec), _row(1)])                          # 23:59:59, then 00:00:01
    core = VigilApp(raw, DEFAULT_PROFILE_DIR, st)
    times = [ev.row_time for ev in core.watcher.poll() if ev.row_time is not None]
    assert times == [datetime(2025, 12, 31, 23, 59, 59), datetime(2026, 1, 1, 0, 0, 1)], times
    print("  PASS  Dec-31 file: after-midnight rows decode to the next year")


def main():
    test_monitor()
    d = tempfile.mkdtemp()
    try:
        test_app(d)
        test_year_end(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("test_rowtime_vf4: OK")


if __name__ == "__main__":
    main()
