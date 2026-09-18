"""알파 Pass 1 병렬 스케일링 실측 — 코어를 더 줘서 실제로 빨라지는가.

2026-09-18에 호출부의 `cpu_count()//2` 하드코딩을 걷어내고 GUI 스핀(core.parallel)으로
바꿨다. 그럼 '전 코어'가 실제로 이득인가? 병목이 파싱 CPU 가 아니라 **디스크**나
**메인스레드 직렬부**(분류·스풀)면 코어를 늘려도 그대로다. 그걸 가른다.

세 측정:
  A-cold  워커수마다 **서로 다른** 파일 묶음(매번 캐시 미적중) → 디스크 스케일링.
  A-warm  같은 묶음을 페이지캐시에 올려놓고 반복 → 순수 파싱 CPU 스케일링.
  B       실제 AlphaExportWorker._run_inner 의 Pass 1 풀 블록(파싱 + 메인스레드
          _process_scan 소비까지 포함) → A-warm 과의 차이가 직렬부 비용.

B 는 ProcessPoolExecutor 를 타이밍 래퍼로 바꿔 재는데, worker.py 가 함수 안에서
`import concurrent.futures` 하므로 모듈 속성 교체가 그대로 먹는다. 출력은 안 건드린다.

사용: python diagnostics/parallel_scaling_2026-09/measure_pass1.py [--n 20] [--full]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import numpy as np   # noqa: E402

from core.data_io import extract_raw_file_for_parallel as _xtr   # noqa: E402

RAW_DIR = r"E:\Yeosu_2026\CAESAR_Cold\2026-06"
WAVECAL = os.path.join(ROOT, "reference_data", "wv_cal", "cold",
                       "Calib_20260523_Hg_4line_400-497nm_Poly2.txt")
PX_MIN, PX_MAX, CHANNEL = 0, 2048, 1
WORKER_GRID = (1, 2, 5, 10, 20)


def _pool_parse(files, nproc):
    """Pass 1 의 파싱 부분만 — 제출 윈도우(2×nproc)까지 동일하게 흉내낸다."""
    from collections import deque
    tasks = [(fp, PX_MIN, PX_MAX, CHANNEL) for fp in files]
    win = max(2, nproc * 2)
    t0 = time.perf_counter()
    with cf.ProcessPoolExecutor(max_workers=nproc) as ex:
        futs, ti = deque(), 0
        while ti < len(tasks) and len(futs) < win:
            futs.append(ex.submit(_xtr, tasks[ti])); ti += 1
        while futs:
            futs.popleft().result()
            if ti < len(tasks):
                futs.append(ex.submit(_xtr, tasks[ti])); ti += 1
    return time.perf_counter() - t0


def _warm(files):
    """페이지캐시에 올린다. 반환은 실제 디스크 읽기 시간(= 콜드 I/O 바닥)."""
    t0 = time.perf_counter()
    nbytes = 0
    for fp in files:
        with open(fp, 'rb') as fh:
            while True:
                b = fh.read(1 << 24)
                if not b:
                    break
                nbytes += len(b)
    dt = time.perf_counter() - t0
    return dt, nbytes


def part_a_cold(all_files, n, offset=0):
    print("\n== A-cold: 워커수마다 다른 파일 묶음(캐시 미적중) — 디스크 스케일링 ==")
    # offset: A-warm 이 이미 캐시에 올려둔 앞쪽 묶음을 건너뛴다(안 그러면 첫 설정만
    # 캐시 적중으로 부당하게 빠르다).
    all_files = all_files[offset:]
    need = n * len(WORKER_GRID)
    if len(all_files) < need:
        print(f"   SKIP: 파일 {len(all_files)}개 < 필요 {need}개")
        return {}
    out = {}
    for k, w in enumerate(WORKER_GRID):
        chunk = all_files[k * n:(k + 1) * n]
        dt = _pool_parse(chunk, w)
        mb = sum(os.path.getsize(f) for f in chunk) / 1e6
        out[w] = dt
        print(f"   workers={w:>2}  {dt:7.1f}s   {mb/dt:6.1f} MB/s   ({n} files, {mb/1000:.1f} GB)")
    return out


def part_a_warm(files):
    print("\n== A-warm: 같은 묶음, 페이지캐시 적중 — 파싱 CPU 스케일링 ==")
    dt, nbytes = _warm(files)
    print(f"   [warm-up 읽기] {dt:.1f}s  {nbytes/1e6/dt:.1f} MB/s  ← 콜드 I/O 바닥")
    out = {}
    for w in WORKER_GRID:
        dt = _pool_parse(files, w)
        out[w] = dt
        print(f"   workers={w:>2}  {dt:7.1f}s   speedup×{out[WORKER_GRID[0]]/dt:5.2f}")
    return out


class _TimedPool(cf.ProcessPoolExecutor):
    spans: list = []

    def __enter__(self):
        self._t0 = time.perf_counter()
        return super().__enter__()

    def __exit__(self, *a):
        r = super().__exit__(*a)
        _TimedPool.spans.append((self._max_workers, time.perf_counter() - self._t0))
        return r


def part_b(files, out_root):
    """실제 _run_inner 로 Pass 1(풀 블록 = 파싱 + 메인스레드 소비) · Pass 2 를 잰다."""
    print("\n== B: 실제 AlphaExportWorker — Pass 1 풀 블록(메인스레드 소비 포함) ==")
    from core.parallel import set_max_workers
    wave = np.loadtxt(WAVECAL, dtype=float).reshape(-1)
    real = cf.ProcessPoolExecutor
    cf.ProcessPoolExecutor = _TimedPool
    try:
        for w in WORKER_GRID:
            set_max_workers(w)
            _TimedPool.spans = []
            from gui.worker import AlphaExportWorker
            wk = AlphaExportWorker(
                list(files), PX_MIN, PX_MAX, wave[PX_MIN:PX_MAX],
                flag_za=[500], flag_he=[510], flag_amb=[1],
                rl_factor=1.0, cavity_len=51.8,
                output_dir=os.path.join(out_root, f"w{w}"), channel=CHANNEL,
                avg_sec=60.0, purge_settle_sec=60.0, channel_label="cold_scaling",
                campaign="parallel_scaling")
            wk.status_msg.connect(lambda m: None)
            wk.finished.connect(lambda m: None)
            t0 = time.perf_counter()
            wk._run_inner()
            tot = time.perf_counter() - t0
            p1 = _TimedPool.spans[0][1] if _TimedPool.spans else float('nan')
            p2 = _TimedPool.spans[1][1] if len(_TimedPool.spans) > 1 else float('nan')
            print(f"   workers={w:>2}  total {tot:7.1f}s | Pass1 pool {p1:7.1f}s | Pass2 pool {p2:7.1f}s")
    finally:
        cf.ProcessPoolExecutor = real
        set_max_workers(None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=20, help='묶음당 파일 수')
    ap.add_argument('--skip-cold', action='store_true')
    ap.add_argument('--full', action='store_true', help='B(실제 알파 생성)까지')
    ap.add_argument('--out', default=os.path.join(
        os.environ.get('TEMP', '/tmp'), 'alpha_scaling'))
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(RAW_DIR, '*.dat')))
    if not files:
        raise SystemExit(f"raw 없음: {RAW_DIR}")
    print(f"cores={os.cpu_count()}  raw={len(files)} files in {RAW_DIR}")

    if not a.skip_cold:
        part_a_cold(files, a.n, offset=a.n)
    part_a_warm(files[:a.n])
    if a.full:
        part_b(files[:a.n], a.out)


if __name__ == '__main__':
    main()
