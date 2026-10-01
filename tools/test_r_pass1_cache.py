"""R 생성의 Pass 1 파싱 캐시 + 알파와의 공유 — 결과가 캐시 없이 돌린 것과 같은가 (2026-10-02).

R 생성(`tools/r_trend_monitor.scan_directory` → `read_scans_via_dataio`)은 알파와 같은 파서를 같은 키로
캐시한다(core/alpha_cache.py). 커밋된 콜드 raw fixture 2파일로:
  1. read_scans_via_dataio: 끔 == 빈 캐시 == 찬 캐시 (ZA/He 블록 배열 전부)
  2. 찬 캐시에선 raw 파서를 **아예 안 부른다**(파서를 예외 던지게 바꿔도 통과)
  3. scan_directory 전체 결과(R·omr_d 등): 끔 == 찬 캐시(병렬 경로 — 자식 프로세스가 캐시를 읽는다)
  4. R이 만든 **전체 폭** 캐시를 알파(픽셀 700~1700)가 잘라 써도 알파 출력 **바이트 동일**
  5. 잘라 쓰기가 안전하지 않은 전체 폭 캐시(읽기 실패 행 있음)는 다른 범위에 안 쓴다

    python tools/test_r_pass1_cache.py
"""
import filecmp
import glob
import os
import shutil
import sys
import tempfile

import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (_ROOT, os.path.join(_ROOT, 'tools')):
    if p not in sys.path:
        sys.path.insert(0, p)

from PyQt6.QtCore import QCoreApplication
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

import core.data_io as dio
from core import alpha_cache

_FIX = os.path.join(_ROOT, 'diagnostics', 'alpha_pass2_parallel', 'fixtures')
_n_pass = _n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def eq(a, b):
    """중첩 결과(리스트·튜플·dict·ndarray·datetime·숫자) 완전 일치."""
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        a, b = np.asarray(a), np.asarray(b)
        return a.dtype == b.dtype and a.shape == b.shape and np.array_equal(a, b, equal_nan=True)
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(eq(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return type(a) is type(b) and len(a) == len(b) and all(eq(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
        return True
    return a == b


def alpha_run(files, out, pmin, pmax, use_cache):
    from gui.worker import AlphaExportWorker
    wv = np.loadtxt(os.path.join(_FIX, 'wavecal_cold_sample.txt'), comments='#')
    os.makedirs(out, exist_ok=True)
    w = AlphaExportWorker(
        file_list=files, pixel_min=pmin, pixel_max=pmax, wave_nm=wv[pmin:pmax],
        flag_za={500}, flag_he={510}, flag_amb={1}, rl_factor=0.9764, cavity_len=100.0,
        output_dir=out, channel=1, avg_sec=60.0, channel_label='ci', purge_settle_sec=0.0)
    w.use_parallel = True
    w.use_pass1_cache = use_cache
    msgs = []
    w.status_msg.connect(msgs.append)
    w._run_inner()
    return next((m for m in msgs if m.startswith("[Pass 1 cache]")), "")


def same_alpha(a, b):
    fa = sorted(glob.glob(os.path.join(a, '**', '*_alpha_trace.dat'), recursive=True))
    fb = sorted(glob.glob(os.path.join(b, '**', '*_alpha_trace.dat'), recursive=True))
    return bool(fa) and len(fa) == len(fb) and all(filecmp.cmp(x, y, shallow=False) for x, y in zip(fa, fb))


def main():
    tmp = tempfile.mkdtemp()
    os.environ['AUGUR_ALPHA_CACHE_DIR'] = os.path.join(tmp, 'cache')
    try:
        raw = os.path.join(tmp, 'raw')
        os.makedirs(raw)
        files = []
        for s in sorted(glob.glob(os.path.join(_FIX, 'cold_sample-*.dat'))):
            d = os.path.join(raw, os.path.basename(s))
            shutil.copy2(s, d)
            files.append(d)
        check("fixture files found", len(files) == 2)

        # 1·2. read_scans_via_dataio
        os.environ['AUGUR_ALPHA_CACHE'] = '0'
        ref = [dio.read_scans_via_dataio(f, 1) for f in files]
        os.environ['AUGUR_ALPHA_CACHE'] = '1'
        cold = [dio.read_scans_via_dataio(f, 1) for f in files]
        check("R 읽기: 빈 캐시 == 끔", eq(ref, cold))
        check("R 읽기는 ZA/He 블록을 실제로 낸다", all(len(z) + len(h) > 0 for z, h in ref))
        real = dio.extract_raw_file_for_parallel

        def boom(task):
            raise AssertionError("raw parsed despite warm cache")
        dio.extract_raw_file_for_parallel = boom
        try:
            warm = [dio.read_scans_via_dataio(f, 1) for f in files]
            check("R 읽기: 찬 캐시 == 끔, raw 파서를 안 부름", eq(ref, warm))
        except AssertionError as e:
            check("R 읽기: 찬 캐시 == 끔, raw 파서를 안 부름", False, str(e))
        finally:
            dio.extract_raw_file_for_parallel = real

        # 3. scan_directory 전체(병렬 — 자식 프로세스가 캐시를 읽는다)
        import r_trend_monitor as rtm
        wv = np.loadtxt(os.path.join(_FIX, 'wavecal_cold_sample.txt'), comments='#')
        os.environ['AUGUR_ALPHA_CACHE'] = '0'
        r_off = rtm.scan_directory(raw, wv, files, parallel=True)
        os.environ['AUGUR_ALPHA_CACHE'] = '1'
        r_warm = rtm.scan_directory(raw, wv, files, parallel=True)
        check("scan_directory 결과: 찬 캐시 == 끔", eq(r_off, r_warm),
              f"{len(r_off)} vs {len(r_warm)} results")

        # 4. R이 만든 전체 폭 캐시를 알파(700~1700)가 잘라 쓴다
        os.environ['AUGUR_ALPHA_CACHE'] = '1'
        a_ref_msg = alpha_run(files, os.path.join(tmp, 'a_ref'), 700, 1700, use_cache=False)
        a_msg = alpha_run(files, os.path.join(tmp, 'a_shared'), 700, 1700, use_cache=True)
        check("알파(700~1700)가 R의 전체 폭 캐시를 잘라 씀", "2 file(s) from cache" in a_msg, a_msg)
        check("잘라 쓴 알파 == 캐시 없이 만든 알파, byte-exact",
              same_alpha(os.path.join(tmp, 'a_ref'), os.path.join(tmp, 'a_shared')))
        _ = a_ref_msg

        # 5. 잘라 쓰기 불안전(읽기 실패 행) 전체 폭 캐시는 다른 범위에 안 쓴다
        _, fl, Ts, Ps, sp, sc = real((files[0], 0, 2048, 1))
        fl = fl.copy()
        fl[3] = dio.RAW_LOAD_FAIL
        alpha_cache.store(files[0], 1, 0, 2048, fl, Ts, Ps, sp, sc)
        for k in (alpha_cache.cache_key(files[0], 1, 700, 1700),):
            p = os.path.join(alpha_cache.cache_dir(), k[:2], k + '.npz')
            if os.path.exists(p):
                os.remove(p)                       # 정확한 범위 캐시는 치우고
        check("불안전한 전체 폭 캐시는 잘라 쓰지 않음",
              alpha_cache.lookup(files[0], 1, 700, 1700) is None)
        check("같은 전체 폭 요청에는 그대로 씀(정확한 범위)",
              alpha_cache.lookup(files[0], 1, 0, 2048) is not None)
    finally:
        os.environ.pop('AUGUR_ALPHA_CACHE_DIR', None)
        os.environ.pop('AUGUR_ALPHA_CACHE', None)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
