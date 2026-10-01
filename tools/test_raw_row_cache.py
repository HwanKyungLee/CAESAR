# -*- coding: utf-8 -*-
"""tools/test_raw_row_cache.py — raw 행 캐시(DataIO._load_file_to_cache)의 스레드 동작 (2026-10-02).

전역 LRU-1 은 두 채널 QThread 가 서로 다른 raw 를 번갈아 읽으면 서로의 캐시를 지워
매 행 파일 전체를 재파싱했다. 이제 스레드별 LRU-1 + 같은 파일은 공유.

- 두 스레드가 서로 다른 파일을 한 행씩 번갈아 읽어도 파싱은 파일당 한 번
- 두 스레드가 같은 파일을 동시에 처음 읽어도 파싱 한 번, 같은 객체
- 단일 스레드는 종전과 같다: 파일을 바꾸면 옛 파일은 메모리에서 빠진다(LRU-1)
- 스레드가 끝나면 그 스레드만 쥐던 파일도 빠진다
- 파일이 바뀌면(mtime) 다시 읽는다, 내용은 직접 파싱과 같다

    python tools/test_raw_row_cache.py
"""
from __future__ import annotations

import gc
import os
import shutil
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np

from core.data_io import DataIO

N_ROWS = 30


def _write(d, name, seed):
    rng = np.random.default_rng(seed)
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        for _ in range(N_ROWS):
            f.write("\t".join(f"{v:.3f}" for v in rng.random(12)) + "\n")
    return p


class _Counter:
    def __init__(self):
        self.n = {}
        self.lock = threading.Lock()
        self.orig = DataIO._parse_file_rows

    def __enter__(self):
        orig = self.orig

        def counted(fp):
            with self.lock:
                self.n[fp] = self.n.get(fp, 0) + 1
            return orig(fp)
        DataIO._parse_file_rows = staticmethod(counted)
        return self

    def __exit__(self, *a):
        DataIO._parse_file_rows = staticmethod(self.orig)


def _reset():
    DataIO.clear_row_cache()
    gc.collect()


def _cached_paths():
    return sorted(k[0] for k in DataIO._row_cache.keys())


def main():
    d = tempfile.mkdtemp()
    checks = 0
    try:
        a, b = _write(d, "a.dat", 1), _write(d, "b.dat", 2)
        ref = {p: [DataIO._parse_line_to_array(ln) for ln in open(p, encoding="utf-8") if ln.strip()]
               for p in (a, b)}

        # 1) 두 스레드가 서로 다른 파일을 한 행씩 번갈아 읽는다
        _reset()
        bar = threading.Barrier(2)
        errs = []

        def walk(fp):
            try:
                for r in range(N_ROWS):
                    bar.wait()
                    assert np.array_equal(DataIO._read_row_raw(fp, r), ref[fp][r])
            except Exception as e:      # noqa: BLE001
                errs.append(e)
                bar.abort()
        with _Counter() as c:
            ts = [threading.Thread(target=walk, args=(p,)) for p in (a, b)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        assert not errs, errs
        assert c.n == {a: 1, b: 1}, c.n
        checks += 1

        # 2) 두 스레드가 같은 파일을 동시에 처음 읽는다
        _reset()
        got = []
        start = threading.Barrier(4)

        def first(fp):
            start.wait()
            got.append(DataIO._load_file_to_cache(fp))
        with _Counter() as c:
            ts = [threading.Thread(target=first, args=(a,)) for _ in range(4)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        assert c.n == {a: 1}, c.n
        assert all(g is got[0] for g in got)
        checks += 1

        # 3) 스레드가 끝나면 그 스레드만 쥐던 파일은 빠진다
        del got
        gc.collect()
        assert _cached_paths() == [], _cached_paths()
        checks += 1

        # 4) 단일 스레드: 같은 파일 반복은 공짜, 파일을 바꾸면 옛 파일은 빠진다(LRU-1)
        _reset()
        with _Counter() as c:
            for r in range(N_ROWS):
                DataIO._read_row_raw(a, r)
            assert _cached_paths() == [a]
            DataIO._read_row_raw(b, 0)
            gc.collect()
            assert _cached_paths() == [b], _cached_paths()
            DataIO._read_row_raw(a, 0)
        assert c.n == {a: 2, b: 1}, c.n
        checks += 1

        # 5) 다른 스레드가 쥔 파일은 이 스레드가 읽어도 다시 파싱하지 않는다
        _reset()
        held, go, done = [], threading.Event(), threading.Event()

        def holder():
            held.append(DataIO._load_file_to_cache(b))
            go.set()
            done.wait()
        with _Counter() as c:
            t = threading.Thread(target=holder)
            t.start()
            go.wait()
            assert DataIO._load_file_to_cache(b) is held[0]
            done.set()
            t.join()
        assert c.n == {b: 1}, c.n
        checks += 1
        del held

        # 6) mtime 이 바뀌면 다시 읽고, 내용은 직접 파싱과 같다
        _reset()
        with _Counter() as c:
            DataIO._read_row_raw(a, 0)
            st = os.stat(a)
            os.utime(a, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
            rows = DataIO._load_file_to_cache(a)
        assert c.n == {a: 2}, c.n
        assert len(rows) == N_ROWS and all(np.array_equal(x, y) for x, y in zip(rows, ref[a]))
        checks += 1
        _reset()

        print(f"test_raw_row_cache: {checks} checks passed")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
