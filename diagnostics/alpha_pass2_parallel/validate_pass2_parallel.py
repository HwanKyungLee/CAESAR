"""
Pass 2 병렬화 검증 (헤드리스, 실데이터 필요) — 2026-08
====================================================
AlphaExportWorker._run_inner()를 use_parallel=False/True 두 번 돌려(같은 raw
파일 셋, 다른 output_dir), 결과 *_alpha_trace.dat 를 파일별로 바이트 단위 비교한다.

Pass 2는 파일 단위 재계산(청크 워밍업·reduction 순서 개념이 없음)이라 병렬·순차가
byte-identical이어야 정상 — 이 스크립트는 그걸 1차 게이트(filecmp)로 확인하고,
혹시 안 맞으면 np.allclose(rtol=1e-12)로 최악 불일치 지점을 보여준다.

이 저장소에는 raw 데이터 fixture가 없어 dev 환경에서는 실행 불가 — 아래
RAW_DIR/RAW_GLOB/WV_FILE/FLAG_* 를 실측 데이터로 바꿔 사용자 PC에서 돌릴 것.

사용:
    python diagnostics/alpha_pass2_parallel/validate_pass2_parallel.py
"""
import os
import sys
import glob
import filecmp
import shutil
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'C:\Doasis_Work\CAESAR\CAESAR'
sys.path.insert(0, ROOT)

from PyQt6.QtCore import QCoreApplication
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

from gui.worker import AlphaExportWorker

# ─── 사용자가 실측 데이터로 채울 것 ────────────────────────────────────────────
RAW_DIR   = r'D:\Yeosu_2026\CAESAR_Cold\2026-05'
RAW_GLOB  = '2026-05-17-00[1-3].dat'   # 빠른 확인용 3파일. 전체 검증은 '2026-05-17-*.dat'
WV_FILE   = r'C:\Doasis_Work\Output\wv_cal\cold\Calib_20260523_Hg_4line_400-497nm_Poly2.txt'
OUT_ROOT  = r'C:\Users\holle\AppData\Local\Temp\claude\C--Doasis-Work\08dd617d-464e-4568-9de9-854af7062504\scratchpad\pass2_parallel_validation'

CHANNEL   = 1
PIXEL_MIN = 0
PIXEL_MAX = 2048
RL_FACTOR = 0.9764
CAVITY_LEN = 100.0
FLAG_ZA   = {500}
FLAG_HE   = {510}
FLAG_AMB  = {1}
AVG_SEC   = 60.0


def run_once(file_list, wave_nm, output_dir, use_parallel):
    if os.path.isdir(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    w = AlphaExportWorker(
        file_list=file_list, pixel_min=PIXEL_MIN, pixel_max=PIXEL_MAX,
        wave_nm=wave_nm, flag_za=FLAG_ZA, flag_he=FLAG_HE, flag_amb=FLAG_AMB,
        rl_factor=RL_FACTOR, cavity_len=CAVITY_LEN, output_dir=output_dir,
        channel=CHANNEL, avg_sec=AVG_SEC, channel_label='validate')
    w.use_parallel = use_parallel
    msgs = []
    w.status_msg.connect(lambda s: msgs.append(s))
    w._run_inner()   # QThread 자체를 안 띄우고 워커 로직만 동기 실행
    for m in msgs[-3:]:
        print(f'    {m}')
    return output_dir


def main():
    files = sorted(glob.glob(os.path.join(RAW_DIR, RAW_GLOB)))
    print(f'files={len(files)}')
    if not files:
        print(f'RAW_DIR/RAW_GLOB에 파일이 없음 — 상단 상수를 실측 경로로 바꿀 것: {RAW_DIR}\\{RAW_GLOB}')
        return
    wave_nm = np.loadtxt(WV_FILE, comments='#')
    if wave_nm.ndim == 2:
        wave_nm = wave_nm[:, -1]

    print('=== sequential (use_parallel=False) ===')
    seq_dir = run_once(files, wave_nm, os.path.join(OUT_ROOT, 'seq'), use_parallel=False)
    print('=== parallel (use_parallel=True) ===')
    par_dir = run_once(files, wave_nm, os.path.join(OUT_ROOT, 'par'), use_parallel=True)

    seq_files = sorted(glob.glob(os.path.join(seq_dir, '**', '*_alpha_trace.dat'), recursive=True))
    par_files = sorted(glob.glob(os.path.join(par_dir, '**', '*_alpha_trace.dat'), recursive=True))
    seq_names = {os.path.basename(f) for f in seq_files}
    par_names = {os.path.basename(f) for f in par_files}
    print(f'\nseq files={len(seq_files)}  par files={len(par_files)}')
    if seq_names != par_names:
        print(f'FAIL: 파일 집합이 다름. seq-only={seq_names - par_names}  par-only={par_names - seq_names}')
        return

    n_byte_ok = n_byte_bad = 0
    for name in sorted(seq_names):
        sf = next(f for f in seq_files if os.path.basename(f) == name)
        pf = next(f for f in par_files if os.path.basename(f) == name)
        if filecmp.cmp(sf, pf, shallow=False):
            n_byte_ok += 1
            continue
        n_byte_bad += 1
        # 바이트 불일치 시 헤더(가변 code-version 라인 등) 제외 후 수치 비교
        sa = np.loadtxt(sf, comments='#')
        pa = np.loadtxt(pf, comments='#')
        if sa.shape != pa.shape:
            print(f'  FAIL {name}: shape 다름 seq={sa.shape} par={pa.shape}')
            continue
        d = np.abs(sa - pa)
        ok = np.allclose(sa, pa, rtol=1e-12, atol=0, equal_nan=True)
        print(f'  {"OK(numeric)" if ok else "FAIL"} {name}: byte 불일치, Δmax={np.nanmax(d):.3e}')

    print(f'\n=== 결과: byte-identical {n_byte_ok}/{len(seq_names)}, 불일치 {n_byte_bad} ===')
    if n_byte_bad == 0:
        print('PASS: 병렬 == 순차 (byte-exact)')


if __name__ == '__main__':
    main()
