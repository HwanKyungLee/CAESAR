"""Alpha Pass 1 파싱 캐시(core/alpha_cache.py) — 캐시를 거쳐도 알파 출력이 **바이트 동일**인가.

커밋된 콜드 raw fixture 2파일(150행씩)로 AlphaExportWorker를 돌려 *_alpha_trace.dat를 비교한다.
  1. 캐시 끔 = 기준
  2. 빈 캐시(미스 → 파싱·저장)           == 기준, 2파일 저장
  3. 찬 캐시(적중 → raw 안 읽음)          == 기준, 2파일 적중
  4. 찬 캐시 + purge_settle_sec 변경     == 캐시 끄고 같은 세팅으로 돌린 것
     (HANDOFF 09-17 §4 경고 — 세팅은 캐시 뒤에서 계산되니 키에 없어도 옛 캐시가 결과를 못 바꾼다)
  5. raw 하나가 바뀜(mtime)              → 그 파일만 다시 파싱, 결과 == 기준
  6. 캐시 파일 손상                      → 다시 파싱, 결과 == 기준
  7. 파서 지문이 바뀜(코드·프로파일 변경) → 전부 미스
  8. 상한 정리(prune)                    → 오래된 것부터 지운다

사용: python tools/test_alpha_pass1_cache.py  → 전부 PASS면 exit 0
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
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PyQt6.QtCore import QCoreApplication
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

from core import alpha_cache
from gui.worker import AlphaExportWorker

_FIX = os.path.join(_ROOT, 'diagnostics', 'alpha_pass2_parallel', 'fixtures')
WV_FILE = os.path.join(_FIX, 'wavecal_cold_sample.txt')
_n_pass = _n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def run(files, out, use_cache, purge=0.0):
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    w = AlphaExportWorker(
        file_list=files, pixel_min=0, pixel_max=2048, wave_nm=np.loadtxt(WV_FILE, comments='#'),
        flag_za={500}, flag_he={510}, flag_amb={1}, rl_factor=0.9764, cavity_len=100.0,
        output_dir=out, channel=1, avg_sec=60.0, channel_label='ci', purge_settle_sec=purge)
    w.use_parallel = True                 # 캐시는 병렬 Pass 1 경로에 붙어 있다
    w.use_pass1_cache = use_cache
    msgs = []
    w.status_msg.connect(msgs.append)
    w._run_inner()
    cache_line = next((m for m in msgs if m.startswith("[Pass 1 cache]")), "")
    return out, cache_line


def same(a, b):
    fa = sorted(glob.glob(os.path.join(a, '**', '*_alpha_trace.dat'), recursive=True))
    fb = sorted(glob.glob(os.path.join(b, '**', '*_alpha_trace.dat'), recursive=True))
    if not fa or [os.path.basename(x) for x in fa] != [os.path.basename(x) for x in fb]:
        return False, f"files {len(fa)} vs {len(fb)}"
    bad = [os.path.basename(x) for x, y in zip(fa, fb) if not filecmp.cmp(x, y, shallow=False)]
    return not bad, f"differs: {bad}"


def main():
    tmp = tempfile.mkdtemp()
    os.environ['AUGUR_ALPHA_CACHE_DIR'] = os.path.join(tmp, 'cache')
    try:
        src = sorted(glob.glob(os.path.join(_FIX, 'cold_sample-*.dat')))
        check("fixture files found", len(src) == 2, str(src))
        raw = os.path.join(tmp, 'raw')
        os.makedirs(raw)
        files = []
        for s in src:                              # 사본에서 — 원본 fixture의 mtime을 건드리지 않게
            d = os.path.join(raw, os.path.basename(s))
            shutil.copy2(s, d)
            files.append(d)

        ref, _ = run(files, os.path.join(tmp, 'ref'), use_cache=False)
        cold, msg = run(files, os.path.join(tmp, 'cold'), use_cache=True)
        ok, why = same(ref, cold)
        check("빈 캐시(미스) == 기준, byte-exact", ok, why)
        check("빈 캐시: 2파일 저장", "0 file(s) from cache" in msg and "2 saved" in msg, msg)

        warm, msg = run(files, os.path.join(tmp, 'warm'), use_cache=True)
        ok, why = same(ref, warm)
        check("찬 캐시(적중) == 기준, byte-exact", ok, why)
        check("찬 캐시: 2파일 적중(raw 안 읽음)", "2 file(s) from cache" in msg and "0 saved" in msg, msg)

        ref60, _ = run(files, os.path.join(tmp, 'ref60'), use_cache=False, purge=60.0)
        warm60, msg = run(files, os.path.join(tmp, 'warm60'), use_cache=True, purge=60.0)
        ok, why = same(ref60, warm60)
        check("세팅 변경(purge 0→60) + 찬 캐시 == 캐시 없이 같은 세팅, byte-exact", ok, why)
        check("세팅 변경에도 캐시 적중(세팅은 캐시 뒤에서 계산)", "2 file(s) from cache" in msg, msg)
        ok_diff, _ = same(ref, ref60)
        check("(대조) purge 0 과 60 은 실제로 결과가 다르다", not ok_diff)

        os.utime(files[0], None)                   # raw 하나 '바뀜'
        st = os.stat(files[0])
        os.utime(files[0], ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
        chg, msg = run(files, os.path.join(tmp, 'chg'), use_cache=True)
        ok, why = same(ref, chg)
        check("raw 변경 → 그 파일만 다시 파싱", "1 file(s) from cache" in msg and "1 saved" in msg, msg)
        check("raw 변경 후 결과 == 기준", ok, why)

        npzs = glob.glob(os.path.join(alpha_cache.cache_dir(), '*', '*.npz'))
        key0 = alpha_cache.cache_key(files[0], 1, 0, 2048)
        p0 = next(p for p in npzs if os.path.basename(p).startswith(key0))
        with open(p0, 'wb') as fh:
            fh.write(b'not an npz')
        bad, msg = run(files, os.path.join(tmp, 'bad'), use_cache=True)
        ok, why = same(ref, bad)
        check("손상된 캐시 → 다시 파싱, 결과 == 기준", ok, why)
        check("손상된 캐시는 다시 저장된다", alpha_cache.load(key0) is not None)

        old_fp = alpha_cache._FINGERPRINT
        alpha_cache._FINGERPRINT = "other-parser-version"
        try:
            k = alpha_cache.cache_key(files[0], 1, 0, 2048)
            check("파서 지문이 바뀌면 키가 달라져 미스", not alpha_cache.has(k))
        finally:
            alpha_cache._FINGERPRINT = old_fp
        check("채널·픽셀범위가 다르면 다른 키",
              len({alpha_cache.cache_key(files[0], 1, 0, 2048), alpha_cache.cache_key(files[0], 2, 0, 2048),
                   alpha_cache.cache_key(files[0], 1, 0, 1024)}) == 3)

        n_before, b_before = alpha_cache.usage()
        freed = alpha_cache.prune(limit=b_before // 2)
        n_after, b_after = alpha_cache.usage()
        check("상한 정리: 절반 상한이면 오래된 것부터 지운다", freed > 0 and b_after <= b_before // 2 + 1,
              f"{n_before}→{n_after} files, {b_before}→{b_after} B")
    finally:
        os.environ.pop('AUGUR_ALPHA_CACHE_DIR', None)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
