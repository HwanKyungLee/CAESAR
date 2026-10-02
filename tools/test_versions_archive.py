# -*- coding: utf-8 -*-
"""tools/test_versions_archive.py — superseded results stay visible in Versions (2026-10-03).

Before: archive_existing renamed the sidecar to `x.meta__T.json` (split from `x__T.dat`) and
find_versions skipped `_archive`, so a same-settings re-fit made the previous run vanish from
Result Lab's Versions list.

    python tools/test_versions_archive.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import run_meta
from core.result_io import archive_existing


def main():
    base = tempfile.mkdtemp()
    try:
        camp = os.path.join(base, "yeosu")
        day = os.path.join(camp, "2026-05-20", "fitting")
        os.makedirs(day)
        dat = os.path.join(day, "260520_CH1_rABC.dat")

        def save(created):
            if archive_existing(dat, camp):
                pass
            open(dat, "w").write("x\n")
            run_meta.write_meta(dat, {"runid": "rABC", "channel": 1, "created": created,
                                      "data_days": ["2026-05-20"]})

        save("2026-10-01T10:00:00")
        os.utime(dat, (1_700_000_000, 1_700_000_000))   # distinct archive stamp
        save("2026-10-02T10:00:00")

        arch = os.path.join(camp, "_archive", "2026-05-20", "fitting")
        names = sorted(os.listdir(arch))
        assert len(names) == 2, names
        a_dat = next(n for n in names if n.endswith(".dat"))
        assert a_dat[:-4] + ".meta.json" in names, names          # pair keeps one name

        for probe in (dat, os.path.join(arch, a_dat)):           # from either side
            v = run_meta.find_versions(probe)
            assert [x["meta"]["created"][:10] for x in v] == ["2026-10-01", "2026-10-02"], v
            assert all(os.path.exists(x["path"]) for x in v), v

        # a bare .meta.json archive keeps the compound extension
        lone = os.path.join(day, "y.meta.json")
        open(lone, "w").write("{}")
        assert archive_existing(lone, camp).endswith(".meta.json")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("test_versions_archive: OK")


if __name__ == "__main__":
    main()
