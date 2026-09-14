"""
청크+워밍업 검증 (헤드리스, 진짜 핏) — 2026-06-17
=================================================
AnalysisWorker._fit_alpha_range 를 실제 콜드 알파에 돌려:
  순차 기준 = _fit_alpha_range(전체, body_start=0)
  청크      = K분할, 각 청크 warmup M 후 body만 수집 → concat
per-scan NO2/CHOCHO ppb·shift 를 대조해 '청크==순차'인지 확인.

엔진=시나리오 CH1(cold): wavecal Calib_20260523 + ILS적용 ref(NO2/CHOCHO/H2O).
"""
import os, sys, glob, argparse, time
import numpy as np

# 2026-09-05: ROOT가 r'C:\Doasis_Work\CAESAR\CAESAR'로 하드코딩돼 있었는데, 이 경로는
# 이제 이 기기에 존재하지 않음(C:\Doasis_Work 최상위엔 "data analysis"/"filed log"/
# "Output"뿐 — CAESAR 서브폴더 없음). 즉 이 스크립트를 그대로 돌리면 import가
# 실패하거나(경로 없음), 있었다 해도 어느 시점의 스냅샷인지 알 수 없는 낡은 복사본을
# 쓸 위험이 있었음 — "실제 프로덕션 코드"를 검증한다는 이 스크립트의 목적과 어긋남.
# 그래서 ROOT를 이 파일 위치 기준 상대경로로 계산해 "지금 실행 중인 이 저장소"를
# 항상 쓰도록 고침(diagnostics/parallel_shift_bench/ 의 두 단계 위 = repo root).
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, ROOT)

from PyQt6.QtCore import QCoreApplication
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

from core.engine import UniversalEngine
from gui.worker import AnalysisWorker

# 하위호환 기본값(존재하지 않는 경로일 수 있음) — 실제로는 아래 --alpha-dir/--wv-dir로
# 덮어써서 사용. 2026-09-05 기준 실데이터 위치:
#   --alpha-dir "C:\GHL\2026 yeosu\Output\alpha\10s\cold"
#   --wv-dir    "C:\GHL\2026 yeosu\Output\wv_cal\cold"
ALPHA_DIR = r'C:\Doasis_Work\Output\alpha\cold'
WV = r'C:\Doasis_Work\Output\wv_cal\cold'
DAY = '2026-05-17'
NFILES = 4
NCHUNKS = 4
WARMUP = 30

# ── 엔진 ─────────────────────────────────────────────────────────────────────
def load_wavecal(path):
    arr = np.loadtxt(path, comments='#')
    return arr[:, -1] if arr.ndim == 2 else arr

def build_engine():
    eng = UniversalEngine()
    calib = glob.glob(os.path.join(WV, 'Calib_*Poly2.txt'))[0]
    wave = load_wavecal(calib)
    print(f'wavecal {os.path.basename(calib)}  n={len(wave)}  {wave[0]:.2f}-{wave[-1]:.2f}nm')
    eng.set_wavelength_axis(wave)
    refs = [('NO2', 'Ref_NO2*Dynamic-ILS-Applied.dat', 1.0),
            ('CHOCHO', 'Ref_CHOCHO*Dynamic-ILS-Applied.dat', 0.1),
            ('H2O', 'Ref_H2O*Dynamic-ILS-Applied.dat', 1.0)]
    for nm, pat, mult in refs:
        fp = glob.glob(os.path.join(WV, pat))[0]
        ok, msg = eng.add_reference(nm, fp, wave_nm=wave, multiplier=mult)
        print(f'  add_reference {nm}: {ok}  {msg}')
    return eng, wave

# ── 워커(핏 컨텍스트) ────────────────────────────────────────────────────────
def build_worker(eng):
    ng = len(eng.gas_list)
    poly_deg = 4
    p0 = [0.0, 1.0] + [0.1] * ng + [0.0] * (poly_deg + 1)
    lo = [-np.inf, 0.95] + [0.0] * ng + [-np.inf] * (poly_deg + 1)
    hi = [np.inf, 1.05] + [np.inf] * ng + [np.inf] * (poly_deg + 1)
    w = AnalysisWorker(eng, [], 775, 1550, p0, (lo, hi), update_interval=-1,
                       channel=1)
    w.ref_properties = {
        'NO2':    {'sh_mode': 'Limit', 'sh_val': '-2.0, 2.0',
                   'sq_mode': 'Limit', 'sq_val': '-0.02, 0.02', 't_ref': 25.0, 't_coeff': 0.0},
        'CHOCHO': {'sh_mode': 'Link', 'sh_val': 'NO2', 'sq_mode': 'Link', 'sq_val': 'NO2', 't_ref': 25.0, 't_coeff': 0.0},
        'H2O':    {'sh_mode': 'Link', 'sh_val': 'NO2', 'sq_mode': 'Link', 'sq_val': 'NO2', 't_ref': 25.0, 't_coeff': 0.0},
    }
    w.step_limit = 0.5
    w.tikhonov_lambda = 0.0
    w.use_robust_fitting = False
    w.allow_negative_gas = False
    w.fit_unit = 'px'
    w.qc_enabled = False     # 비교는 raw ppb로(QC NaN 회피; QC는 per-scan 결정적이라 무관)
    w.ok_rms_threshold = 0.10
    w.gas_temp_override = None
    w.tz_offset_sec = 0
    return w

def build_scans(files):
    scans = []
    gi = 0
    for fp in files:
        lines = open(fp, encoding='utf-8', errors='replace').readlines()
        nrow = sum(1 for l in lines if l.strip() and not l.startswith('#') and not l.startswith('row_idx'))
        for r in range(nrow):
            scans.append((gi, fp, r)); gi += 1
    return scans

def main():
    global ALPHA_DIR, WV, DAY, NFILES, NCHUNKS, WARMUP
    ap = argparse.ArgumentParser()
    ap.add_argument('--alpha-dir', default=ALPHA_DIR, help='dir containing <day>/*_alpha_trace.dat')
    ap.add_argument('--wv-dir', default=WV, help='dir containing Calib_*Poly2.txt + Ref_*Dynamic-ILS-Applied.dat')
    ap.add_argument('--day', default=DAY)
    ap.add_argument('--nfiles', type=int, default=NFILES)
    ap.add_argument('--nchunks', type=int, default=NCHUNKS)
    ap.add_argument('--warmup', type=int, default=WARMUP)
    args = ap.parse_args()
    ALPHA_DIR, WV, DAY = args.alpha_dir, args.wv_dir, args.day
    NFILES, NCHUNKS, WARMUP = args.nfiles, args.nchunks, args.warmup

    eng, wave = build_engine()
    if not eng.is_engine_ready():
        print('ENGINE NOT READY'); return
    w = build_worker(eng)
    files = sorted(glob.glob(os.path.join(ALPHA_DIR, DAY, '*_alpha_trace.dat')))[:NFILES]
    scans = build_scans(files)
    print(f'files={len(files)} scans={len(scans)}')

    # 순차 기준 — 진짜 프로덕션 VarPro를 스캔마다 호출하므로 여기서 몇십초 정도
    # 조용히 있을 수 있음(스캔당 진행률 출력이 없음). 멈춘 게 아니라 정상.
    print(f'sequential fit 시작 (real _fit_alpha_range, {len(scans)} scans, 진행률 출력 없음 — 정상적으로 조용함)...', flush=True)
    t0 = time.time()
    seq_res, seq_sh, etal = w._fit_alpha_range(scans, body_start=0, init_shift=0.0, etalon_freq=None)
    seq = {gi: r for gi, r in seq_res}
    print(f'seq done in {time.time()-t0:.1f}s. etalon_freq={etal:.4f}')

    # 청크 — 이것도 프로세스 병렬 아님(정확성만 검증하는 스크립트), 청크를 순서대로
    # 한 프로세스 안에서 도니까 seq만큼 또는 그보다 (워밍업 replay 때문에) 조금 더 걸림.
    n = len(scans)
    bounds = np.linspace(0, n, NCHUNKS + 1, dtype=int)
    chunk = {}
    t0 = time.time()
    for ci in range(NCHUNKS):
        bs, be = int(bounds[ci]), int(bounds[ci + 1])
        ws = max(0, bs - WARMUP)
        sub = scans[ws:be]
        body_start = bs - ws
        print(f'  chunk {ci+1}/{NCHUNKS}: scans[{ws}:{be}] (본체 {bs}:{be}, warmup {ws}:{bs})...', flush=True)
        res, sh, _ = w._fit_alpha_range(sub, body_start=body_start, init_shift=0.0, etalon_freq=etal)
        for gi, r in res:
            chunk[gi] = r
    print(f'chunk done in {time.time()-t0:.1f}s ({NCHUNKS} chunks, warmup={WARMUP})')

    # 대조
    gases = list(eng.gas_list)
    print(f'\n=== 순차 vs 청크 per-scan 대조 (n={n}) ===')
    sh_d = np.array([abs(seq[i].get('Shift', 0) - chunk[i].get('Shift', 0)) for i in range(n)])
    print(f'shift  Δmax={sh_d.max():.5f}  Δrms={np.sqrt(np.mean(sh_d**2)):.5f}')
    for g in [x for x in gases if x in ('NO2', 'CHOCHO')]:
        a = np.array([seq[i].get(g, np.nan) for i in range(n)])
        b = np.array([chunk[i].get(g, np.nan) for i in range(n)])
        d = np.abs(a - b)
        rel = d / (np.abs(a) + 1e-12)
        nbad = int(np.sum(d > 1e-6))
        print(f'{g:7} ppb: Δmax={np.nanmax(d):.4e}  Δrms={np.sqrt(np.nanmean(d**2)):.4e}  '
              f'평균|ppb|={np.nanmean(np.abs(a)):.3f}  >1e-6인스캔={nbad}/{n}  최대상대={np.nanmax(rel):.2e}')
    # 경계 부근 차이 위치
    worst = int(np.argmax(sh_d))
    print(f'shift Δ 최대 위치 i={worst} (청크경계={list(bounds)})  seqShift={seq[worst].get("Shift"):.4f} chunkShift={chunk[worst].get("Shift"):.4f}')
    # shift 거동(벽붙음 확인)
    sa = np.array([seq[i].get('Shift', np.nan) for i in range(n)])
    print(f'seq shift: min={np.nanmin(sa):+.3f} max={np.nanmax(sa):+.3f} std={np.nanstd(sa):.3f} mean={np.nanmean(sa):+.3f}')

if __name__ == '__main__':
    main()
