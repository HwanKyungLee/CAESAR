"""Pass 2(alpha 계산) 병렬 vs 순차 byte-exact 회귀 테스트 — CI 전용, 작은 실데이터 fixture.

diagnostics/alpha_pass2_parallel/fixtures/ 의 콜드 raw 2파일(150행씩 잘라낸
것)로 AlphaExportWorker._run_inner()를 use_parallel=False/True 두 번 실행해
결과 *_alpha_trace.dat 를 파일별로 바이트 단위 비교한다. 파일이 반드시 2개
이상 있어야 병렬 분기(len(amb_index)>1)가 실제로 실행되므로 fixture는 2파일.

diagnostics/alpha_pass2_parallel/validate_pass2_parallel.py(사용자가 실제
캠페인 하루치 전체로 수동 실행하는 버전)의 축소판 — 이건 커밋된 fixture만
써서 CI에서 매 push마다 자동으로 돈다.

사용: python tools/test_pass2_parallel.py  → 전부 PASS면 exit 0
"""
import os
import sys
import glob
import filecmp
import shutil
import tempfile

import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PyQt6.QtCore import QCoreApplication
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

from gui.worker import AlphaExportWorker

_FIX = os.path.join(_ROOT, 'diagnostics', 'alpha_pass2_parallel', 'fixtures')
WV_FILE = os.path.join(_FIX, 'wavecal_cold_sample.txt')

_n_pass = 0
_n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def run_once(files, wave_nm, output_dir, use_parallel):
    if os.path.isdir(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    w = AlphaExportWorker(
        file_list=files, pixel_min=0, pixel_max=2048, wave_nm=wave_nm,
        flag_za={500}, flag_he={510}, flag_amb={1},
        rl_factor=0.9764, cavity_len=100.0, output_dir=output_dir,
        channel=1, avg_sec=60.0, channel_label='ci',
        # 이 테스트는 '순차 vs 병렬 동일성'만 본다. 기본 purge_settle_sec=60 이면
        # fixture 001(교정 뒤 ambient 17행뿐)이 통째로 제외돼 출력 파일이 1개가 되고,
        # 그러면 병렬 분기(len(amb_index)>1) 자체가 안 돈다 → 여기선 0으로 끈다.
        # 퍼지 세틀링 자체의 회귀는 tools/test_purge_settle.py 가 본다.
        purge_settle_sec=0.0)
    w.use_parallel = use_parallel
    w._run_inner()
    return output_dir


def test_pass2_parallel_matches_sequential():
    print("[1] Pass2 순차 vs 병렬 — 실데이터 fixture(2파일, 150행씩) byte-exact")
    files = sorted(glob.glob(os.path.join(_FIX, 'cold_sample-*.dat')))
    check("fixture files found (need >=2 for parallel branch)", len(files) >= 2, str(files))
    wave_nm = np.loadtxt(WV_FILE, comments='#')

    with tempfile.TemporaryDirectory() as tmp:
        seq_dir = run_once(files, wave_nm, os.path.join(tmp, 'seq'), use_parallel=False)
        par_dir = run_once(files, wave_nm, os.path.join(tmp, 'par'), use_parallel=True)

        seq_files = sorted(glob.glob(os.path.join(seq_dir, '**', '*_alpha_trace.dat'), recursive=True))
        par_files = sorted(glob.glob(os.path.join(par_dir, '**', '*_alpha_trace.dat'), recursive=True))
        check("both runs produced output files", len(seq_files) > 0 and len(par_files) > 0,
              f"seq={len(seq_files)} par={len(par_files)}")
        seq_names = {os.path.basename(f) for f in seq_files}
        par_names = {os.path.basename(f) for f in par_files}
        check("same output filenames", seq_names == par_names,
              f"seq-only={seq_names - par_names} par-only={par_names - seq_names}")

        for name in sorted(seq_names & par_names):
            sf = next(f for f in seq_files if os.path.basename(f) == name)
            pf = next(f for f in par_files if os.path.basename(f) == name)
            check(f"byte-exact: {name}", filecmp.cmp(sf, pf, shallow=False))


if __name__ == "__main__":
    test_pass2_parallel_matches_sequential()
    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    sys.exit(1 if _n_fail else 0)
