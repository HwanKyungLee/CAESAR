"""퍼지 세틀링 회귀 — 교정(ZA/He) 직후 ambient 가 알파에서 빠지는지.

배경(2026-09-17): raw 는 파일(=1시간)마다 `ambient → He → ZA → ambient` 구조인데,
밸브가 돌아가 flag 이 1 로 바뀌어도 캐비티엔 퍼지가스가 남아 있다. 여수 콜드 실측
플러시(ZA-end 기준 상대농도 중앙값): 0–10s 0.21 · 20–30s 0.52 · 40–50s 0.79 · 60s~ 평탄.
그대로 60s 평균하면 시간당 딱 한 점이 H2O 24 % · NO2 32 % 로 찍혔다.
→ `AlphaExportWorker(purge_settle_sec=...)` 로 그 구간을 알파 평균에서 뺀다.

fixture 는 test_pass2_parallel.py 와 같은 콜드 raw 2파일(150행씩):
  001: flag=0 헤더행 + 교정 131행 + ambient 17행
       → settle 60s 면 교정 뒤 17행이 다 빠지고 **교정 前 헤더행 하나만** 남는다
         (교정보다 앞선 행은 오염될 수 없다 — 규칙이 '직전 교정 이후'인 이유)
  002: ambient 18행 + 교정 67행 + ambient 65행
       → settle 60s 면 앞 18행 + 뒤쪽 ~60초 지난 행만 남는다

사용: python tools/test_purge_settle.py  → 전부 PASS면 exit 0
"""
import glob
import os
import shutil
import sys
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


def run(files, wave_nm, out_dir, settle):
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    w = AlphaExportWorker(
        file_list=files, pixel_min=0, pixel_max=2048, wave_nm=wave_nm,
        flag_za={500}, flag_he={510}, flag_amb={1},
        rl_factor=0.9764, cavity_len=100.0, output_dir=out_dir,
        channel=1, avg_sec=60.0, channel_label='ci',
        purge_settle_sec=settle)
    w.use_parallel = False
    w._run_inner()
    out = {}
    for path in glob.glob(os.path.join(out_dir, '**', '*_alpha_trace.dat'), recursive=True):
        with open(path, encoding='utf-8') as f:
            lines = [ln for ln in f if not ln.startswith('#')]
        out[os.path.basename(path)] = (lines[0], lines[1:])   # (header row, data rows)
    return out


def expected_bins(fp, settle, avg_sec=60.0):
    """스킵 규칙을 테스트 쪽에서 독립 재구현 → 알파 파일의 rep row_idx 를 예측.
    Pass 1 과 같은 행 인덱싱을 쓰려고 같은 추출기를 부른다(헤더행 포함 150행)."""
    from core.data_io import extract_raw_file_for_parallel as xtr
    _, flags, _Ts, _Ps, _specs, secs = xtr((fp, 0, 2048, 1))
    AMB = {1, 0}          # flag_amb={1} + FLAG_HEADER(0)
    last_cal, kept = None, []
    for i, fl in enumerate(flags):
        if int(fl) not in AMB:
            last_cal = secs[i]
            continue
        if last_cal is not None and secs[i] - last_cal < settle:
            continue
        kept.append(i)
    if not kept:
        return []
    s0 = secs[kept[0]]
    bins = {}
    for i in kept:
        bins.setdefault(int((secs[i] - s0) / avg_sec), []).append(i)
    return [str(bins[b][0]) for b in sorted(bins)]


def test_purge_settle():
    files = sorted(glob.glob(os.path.join(_FIX, 'cold_sample-*.dat')))
    check("fixture files found", len(files) == 2, str(files))
    wave_nm = np.loadtxt(WV_FILE, comments='#')

    with tempfile.TemporaryDirectory() as tmp:
        off = run(files, wave_nm, os.path.join(tmp, 'off'), 0.0)
        on = run(files, wave_nm, os.path.join(tmp, 'on'), 60.0)

        check("settle=0 keeps both files", len(off) == 2, sorted(off))
        for fp in files:
            base = os.path.basename(fp).replace('.dat', '_ci_alpha_trace.dat')
            for settle, got in ((0.0, off), (60.0, on)):
                want = expected_bins(fp, settle)
                have = [r.split('	')[0] for r in got.get(base, ('', []))[1]]
                check(f"{base} settle={settle:.0f}: bins {want}", have == want,
                      f"got {have}")
        # 실제로 무언가 빠졌는지 — 안 빠지면 위 비교가 통과해도 의미가 없다.
        n_off = sum(len(v[1]) for v in off.values())
        n_on = sum(len(v[1]) for v in on.values())
        check("settle=60 actually removed rows", n_on < n_off, f"off={n_off} on={n_on}")
        # 교정 직후 구간은 001 의 ambient 전부 — 남는 건 교정 前 헤더행 하나뿐이어야.
        f1 = next(n for n in off if '001' in n)
        check("001: only the pre-calibration header row survives",
              len(on.get(f1, ('', []))[1]) == 1, str(on.get(f1, ('', []))[1]))


if __name__ == "__main__":
    test_purge_settle()
    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    sys.exit(1 if _n_fail else 0)
