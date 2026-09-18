"""콜드 HDD 에서 '읽기'와 '파싱'을 겹칠 수 있는가 — 알파 Pass 1 구조 결정용.

배경(measure_pass1.py 결과): E: USB HDD 는 동시 읽기에 헤드가 긁혀 워커를 늘릴수록
느려진다(41.4→26.9 MB/s). 그래서 워커 1개가 제일 빠른데, 1개면 읽기와 파싱이 한
프로세스에서 순차로 일어나 디스크가 파싱하는 동안 논다.

그럼 **스레드 하나가 다음 파일을 미리 읽어 페이지캐시에 올려두면** 파싱과 읽기가
겹치는가? 겹친다면 파서 코드는 한 글자도 안 고치고(=무회귀) 절반을 먹는다.
파일 시스템 read 는 GIL 을 놓으므로 스레드로 충분하다.

네 설정을 **서로 다른 파일 묶음**(전부 캐시 미적중)으로 잰다:
  A 현행     — 워커 1개, 읽기+파싱 순차
  B 프리페치 — 백그라운드 스레드가 다음 파일을 통째로 read() → 본 파싱은 그대로
  C 읽기만   — 디스크 바닥(파싱 없음)
  D 2채널    — 한 번 읽고 CH1·CH2 둘 다 뽑기(두 번째 채널의 한계비용)

사용: python diagnostics/parallel_scaling_2026-09/measure_prefetch.py [--n 8]
"""
from __future__ import annotations

import argparse
import glob
import os
import queue
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from core.data_io import DataIO, extract_raw_file_for_parallel as _xtr   # noqa: E402

RAW_DIR = r"E:\Yeosu_2026\CAESAR_Hot\2026-07"
PX = (0, 2048)


def _mb(files):
    return sum(os.path.getsize(f) for f in files) / 1e6


def _slurp(fp):
    """파일을 통째로 읽어 페이지캐시에 올린다(내용은 버린다)."""
    with open(fp, 'rb') as fh:
        while fh.read(1 << 24):
            pass


def run_current(files, ch=1):
    t0 = time.perf_counter()
    for fp in files:
        _xtr((fp, PX[0], PX[1], ch))
        DataIO._row_cache.clear()          # 파일 간 행캐시는 원래도 LRU-1
    return time.perf_counter() - t0


def run_prefetch(files, ch=1, depth=2):
    """백그라운드 스레드가 depth 개 앞서 읽어둔다. 파싱 경로는 현행 그대로."""
    q = queue.Queue(maxsize=depth)

    def reader():
        for fp in files:
            _slurp(fp)
            q.put(fp)
        q.put(None)

    th = threading.Thread(target=reader, daemon=True)
    t0 = time.perf_counter()
    th.start()
    while True:
        fp = q.get()
        if fp is None:
            break
        _xtr((fp, PX[0], PX[1], ch))
        DataIO._row_cache.clear()
    th.join()
    return time.perf_counter() - t0


def run_readonly(files):
    t0 = time.perf_counter()
    for fp in files:
        _slurp(fp)
    return time.perf_counter() - t0


def run_two_channels(files):
    t0 = time.perf_counter()
    for fp in files:
        _xtr((fp, PX[0], PX[1], 1))
        _xtr((fp, PX[0], PX[1], 2))        # 같은 파일 — 행캐시가 살아 있어 재읽기 없음
        DataIO._row_cache.clear()
    return time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=8, help='설정당 파일 수')
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(RAW_DIR, '*.dat')))
    need = a.n * 4
    if len(files) < need:
        raise SystemExit(f"파일 {len(files)}개 < 필요 {need}개")
    print(f"raw={RAW_DIR}  파일 {len(files)}개 중 설정당 {a.n}개(서로 다른 묶음, 전부 콜드)")

    for k, (name, fn) in enumerate([
            ("A 현행(워커1, 읽기+파싱 순차)", run_current),
            ("B 프리페치 스레드 + 파싱", run_prefetch),
            ("C 읽기만(디스크 바닥)", run_readonly),
            ("D 한 번 읽고 2채널", run_two_channels)]):
        chunk = files[k * a.n:(k + 1) * a.n]
        dt = fn(chunk)
        mb = _mb(chunk)
        print(f"  {name:<28} {dt:7.1f}s  {mb/dt:6.1f} MB/s  ({dt/len(chunk):.2f} s/file)")


if __name__ == '__main__':
    main()
