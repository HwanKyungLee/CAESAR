"""Pass 1 파싱 캐시(core/alpha_cache.py) — **측정 중이라 자라는 raw 파일**이 캐시를 오염시키지 않는가.

2026-10-02 리뷰: 키(크기·mtime)를 파싱 **뒤에** 읽어서, LabVIEW 가 아직 행을 붙이는 오늘 파일의
짧은 파싱 결과가 다 자란 파일의 키로 저장됐다. 그 뒤 모든 알파·R 런이 그 캐시에 적중해 붙은 행을
말없이 빠뜨렸다(worker.py 의 `_ri >= len(_flags): continue`).

  1. 파싱 도중 파일이 자람 → store(stamp=파싱 전) 는 저장을 거부, lookup 은 미스
  2. extract_cached 도 같은 상황에서 저장하지 않는다(R 경로)
  3. 파일이 멈춘 뒤 다시 → 저장되고, 적중 결과의 행 수 == 다 자란 파일의 행 수
  4. 파일이 안 바뀌었으면 평소대로 저장·적중(무회귀)

사용: python tools/test_alpha_cache_growing.py  → 전부 PASS면 exit 0
"""
import glob
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import alpha_cache
import core.data_io as dio

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


def _split_fixture(dst):
    """fixture 를 앞 절반만 dst 에 쓰고 나머지 줄을 돌려준다(나중에 붙일 '측정 중' 행)."""
    src = sorted(glob.glob(os.path.join(_FIX, 'cold_sample-*.dat')))[0]
    with open(src, 'rb') as fh:
        lines = fh.read().splitlines(keepends=True)
    half = len(lines) // 2
    with open(dst, 'wb') as fh:
        fh.writelines(lines[:half])
    return lines[half:]


def _append(fp, tail):
    with open(fp, 'ab') as fh:
        fh.writelines(tail)
    st = os.stat(fp)                       # mtime 해상도가 거친 파일시스템 대비 — 크기도 바뀐다
    os.utime(fp, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


def main():
    tmp = tempfile.mkdtemp()
    os.environ['AUGUR_ALPHA_CACHE_DIR'] = os.path.join(tmp, 'cache')
    os.environ['AUGUR_ALPHA_CACHE'] = '1'
    try:
        fp = os.path.join(tmp, 'growing.dat')
        tail = _split_fixture(fp)
        task = (fp, 0, 2048, 1)

        # 1. 워커 경로: stamp 를 잡고 → 파싱 → (그 사이 행이 붙음) → store
        st = alpha_cache.file_stamp(fp)
        out_short = dio.extract_raw_file_for_parallel(task)
        n_short = len(out_short[1])
        _append(fp, tail)
        n_full = len(dio.DataIO.expand_to_scan_list(fp))
        check("fixture 가 실제로 자랐다", n_full > n_short, f"{n_short} → {n_full}")
        saved = alpha_cache.store(fp, 1, 0, 2048, *out_short[1:], stamp=st)
        check("파싱 중 파일이 자라면 store 가 거부", saved is False, str(saved))
        check("거부 뒤 lookup 은 미스(다시 파싱하게)", alpha_cache.lookup(fp, 1, 0, 2048) is None)

        # 2. R 경로(extract_cached): 파싱 도중에 행이 붙는 상황을 흉내
        fp2 = os.path.join(tmp, 'growing2.dat')
        tail2 = _split_fixture(fp2)
        real = dio.extract_raw_file_for_parallel

        def parse_then_grow(t):
            out = real(t)
            _append(t[0], tail2)                       # 파싱이 끝난 직후, 저장 전에 자람
            return out

        dio.extract_raw_file_for_parallel = parse_then_grow
        try:
            out2 = alpha_cache.extract_cached((fp2, 0, 2048, 1))
        finally:
            dio.extract_raw_file_for_parallel = real
        check("extract_cached: 결과는 그때 파싱한 그대로 돌려준다", len(out2[1]) > 0)
        check("extract_cached: 자란 파일 키로 짧은 결과를 저장하지 않음",
              alpha_cache.lookup(fp2, 1, 0, 2048) is None)

        # 3. 파일이 멈춘 뒤에는 정상 저장 → 적중 결과 행 수 == 다 자란 파일
        out3 = alpha_cache.extract_cached((fp2, 0, 2048, 1))
        hit = alpha_cache.lookup(fp2, 1, 0, 2048)
        n2_full = len(dio.DataIO.expand_to_scan_list(fp2))
        check("멈춘 파일은 저장된다", hit is not None)
        check("적중 행 수 == 다 자란 파일 행 수",
              hit is not None and len(hit[0]) == n2_full == len(out3[1]),
              f"{None if hit is None else len(hit[0])} vs {n2_full}")

        # 4. 무회귀: 안 바뀐 파일은 stamp 그대로 저장·적중
        st = alpha_cache.file_stamp(fp)
        out4 = dio.extract_raw_file_for_parallel(task)
        check("안 바뀐 파일은 저장", alpha_cache.store(fp, 1, 0, 2048, *out4[1:], stamp=st) is True)
        hit4 = alpha_cache.lookup(fp, 1, 0, 2048)
        check("안 바뀐 파일은 적중, 행 수 == 파일", hit4 is not None and len(hit4[0]) == n_full)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n결과: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
