"""
shift 안정화 방식 비교 하네스 (2026-06-17)
==========================================
AnalysisWorker 병렬화를 위해, '직전 스캔 shift(last_valid_shift) 캐리오버'를
대체할 후보들을 실콜드 alpha 시계열에 돌려 비교한다.

★핵심 설계: 4개 방식이 **완전히 동일한 inner fit**(build_A + 경계 L-BFGS + lstsq)을
쓰고 바깥 'shift 탐색창 중심/폭 정책'만 다르다. 따라서 결과 차이는 순수히
shift 정책 효과만 분리한다. (inner fit은 production VarPro의 단순화판 — 절대 ppb는
production과 다를 수 있으나, 방식 간 상대비교 결론은 그대로 전이된다.)

방식:
  seq      : 순차 step_limit (center=직전 최적 shift, 폭=±step). = 현재 GUI 방식. 병렬 불가.
  indep    : 독립 넓은창 (center=0 고정, 폭=±global). step_limit 그냥 제거. 완전 병렬.
  twopass  : 1패스 indep로 raw shift → robust 평활 → 2패스(center=평활, 폭=±step). 병렬.
  chunk    : 청크 분할, 각 청크 seq 재귀를 M스캔 워밍업 후 실행. 청크간 병렬.

비교 기준 = seq(현재 방식) 대비 NO2/CHOCHO ppb 차이 + shift 궤적.
"""
from __future__ import annotations
import os, sys, glob, time, argparse
import numpy as np
from scipy.linalg import lstsq
from scipy.optimize import minimize
from scipy.interpolate import interp1d

ALPHA_DIR = r'C:\Doasis_Work\Output\alpha\cold'
REF_DIR   = r'C:\Doasis_Work\Output\wv_cal\cold'
# 2026-09-05: C:\Doasis_Work\Output는 이 세션에서 접근이 막혀 있었음(폴더 권한
# 거부). 이후 사용자가 "C:\GHL\2026 yeosu\Output"를 연결 — 여기에 실제 여수
# 캠페인 alpha(10s/60s, cold/hot ch1/ch2, 2026-05-17~)와 wv_cal(cold/roi1/roi2)이
# 있음을 확인. 위 두 상수는 하위호환용 기본값으로 남겨두고, --alpha-dir/--ref-dir로
# 덮어쓸 수 있게 함. 실행 예:
#   python bench.py --alpha-dir "C:\GHL\2026 yeosu\Output\alpha\10s\cold" \
#                    --ref-dir   "C:\GHL\2026 yeosu\Output\wv_cal\cold"
OUT_DIR   = os.path.join(os.path.dirname(__file__), 'out')
os.makedirs(OUT_DIR, exist_ok=True)

GAS_LIST    = ['NO2', 'CHOCHO', 'H2O']     # 시나리오 cold refs (Link: CHOCHO/H2O→NO2)
WAVE_FIT    = (435.0, 480.0)
POLY_DEG    = 4
SHIFT_GLOB  = (-2.0, 2.0)                  # 시나리오 sh_val
SQUEEZE_LIM = (1 - 0.02, 1 + 0.02)         # 시나리오 sq_val ±0.02
STEP_LIMIT  = 0.5                          # 시나리오 step_limit (px/scan)


# ─── 데이터 로드 ──────────────────────────────────────────────────────────────
def load_refs(n_pix, ref_dir=REF_DIR):
    refs, scale = {}, {}
    for g in GAS_LIST:
        fs = glob.glob(os.path.join(ref_dir, f'Ref_{g}*Dynamic-ILS-Applied.dat'))
        arr = np.loadtxt(fs[0], comments='#')
        assert len(arr) == n_pix, f'{g}: {len(arr)} != {n_pix}'
        scale[g] = 10.0 ** np.floor(np.log10(np.max(np.abs(arr))))
        px = np.arange(n_pix, dtype=float)
        refs[g] = interp1d(px, arr / scale[g], kind='cubic',
                           bounds_error=False, fill_value=0.0)
    return refs, scale


def load_alpha_series(files):
    """여러 alpha 파일의 행을 시간순(파일순+행순)으로 이어붙여 시계열로."""
    wave = None
    rows, T, P, doy = [], [], [], []
    for fp in files:
        lines = open(fp, encoding='utf-8', errors='replace').readlines()
        if wave is None:
            wl = [l for l in lines if l.startswith('# wavelength_nm:')][0]
            wave = np.array([float(v) for v in wl.split(':', 1)[1].strip().split('\t') if v.strip()])
        hdr = [l for l in lines if l.startswith('row_idx')][0].rstrip('\n').split('\t')
        iT, iP, iD = hdr.index('T_C'), hdr.index('P_mbar'), hdr.index('doy')
        ipx = next(i for i, c in enumerate(hdr) if c.startswith('px'))
        for l in lines:
            if not l.strip() or l.startswith('#') or l.startswith('row_idx'):
                continue
            p = l.rstrip('\n').split('\t')
            if len(p) < ipx + len(wave):
                continue
            rows.append(np.array(p[ipx:ipx + len(wave)], dtype=float))
            T.append(float(p[iT])); P.append(float(p[iP])); doy.append(float(p[iD]))
    return wave, np.array(rows), np.array(T), np.array(P), np.array(doy)


# ─── inner fit (모든 방식 공통) ───────────────────────────────────────────────
class InnerFit:
    def __init__(self, wave, refs):
        self.fit_idx = np.where((wave >= WAVE_FIT[0]) & (wave <= WAVE_FIT[1]))[0]
        self.center_px = self.fit_idx[len(self.fit_idx) // 2]
        self.refs = refs
        n_fit = len(self.fit_idx)
        xn = 2.0 * (np.arange(n_fit) / max(n_fit - 1, 1)) - 1.0
        self.poly = np.column_stack([
            np.polynomial.chebyshev.chebval(xn, np.eye(POLY_DEG + 1)[k])
            for k in range(POLY_DEG + 1)])

    def build_A(self, shift, squeeze):
        pxs = (self.fit_idx - self.center_px) * squeeze + self.center_px + shift
        A_ref = np.column_stack([self.refs[g](pxs) for g in GAS_LIST])
        return np.column_stack([A_ref, self.poly])

    def fit(self, y, sh_lo, sh_hi, sq_lo=SQUEEZE_LIM[0], sq_hi=SQUEEZE_LIM[1], sh0=0.0):
        def cost(prm):
            A = self.build_A(prm[0], prm[1])
            c, _, _, _ = lstsq(A, y)
            r = y - A @ c
            return float(r @ r)
        sh0c = min(max(sh0, sh_lo + 1e-6), sh_hi - 1e-6)
        res = minimize(cost, [sh0c, 1.0], bounds=[(sh_lo, sh_hi), (sq_lo, sq_hi)],
                       method='L-BFGS-B', options={'maxiter': 40, 'ftol': 1e-12})
        sh, sq = float(res.x[0]), float(res.x[1])
        A = self.build_A(sh, sq)
        c, _, _, _ = lstsq(A, y)
        rms = float(np.sqrt(np.mean((y - A @ c) ** 2)))
        return sh, sq, c[:len(GAS_LIST)], rms

    def ppb_row(self, y, sh, sq, T_C, P_mbar, scale):
        A = self.build_A(sh, sq)
        c, _, _, _ = lstsq(A, y)
        gc = c[:len(GAS_LIST)]
        N_air = 2.68678e19 * (P_mbar / 1013.25) * (273.15 / (T_C + 273.15))
        out = {}
        for gi, g in enumerate(GAS_LIST):
            out[g] = (gc[gi] / scale[g]) / N_air * 1e9
        return out


# ─── shift 정책들 ─────────────────────────────────────────────────────────────
def run_seq(F, A, step=STEP_LIMIT, glob_=SHIFT_GLOB):
    """현재 GUI 방식: center=직전 최적 shift, 폭=±step ∩ global. 순차."""
    n = len(A); sh = np.zeros(n); sq = np.zeros(n)
    last = 0.0
    for i in range(n):
        lo, hi = max(glob_[0], last - step), min(glob_[1], last + step)
        s, q, _, _ = F.fit(A[i], lo, hi, sh0=last)
        sh[i], sq[i] = s, q; last = s
    return sh, sq


def run_indep(F, A, glob_=SHIFT_GLOB):
    """step_limit 제거: 모든 스캔 독립, center=0, 폭=±global."""
    n = len(A); sh = np.zeros(n); sq = np.zeros(n)
    for i in range(n):
        s, q, _, _ = F.fit(A[i], glob_[0], glob_[1], sh0=0.0)
        sh[i], sq[i] = s, q
    return sh, sq


def _hampel_smooth(x, win=15, nsig=3.0):
    """robust 평활: Hampel(이상치→이웃 median) 후 이동 median."""
    n = len(x); y = x.copy()
    k = win // 2
    for i in range(n):
        a, b = max(0, i - k), min(n, i + k + 1)
        seg = x[a:b]; med = np.median(seg)
        mad = 1.4826 * np.median(np.abs(seg - med)) + 1e-9
        if abs(x[i] - med) > nsig * mad:
            y[i] = med
    # 한번 더 가벼운 이동 median으로 매끈하게
    z = y.copy()
    for i in range(n):
        a, b = max(0, i - k), min(n, i + k + 1)
        z[i] = np.median(y[a:b])
    return z


def run_twopass(F, A, step=STEP_LIMIT, glob_=SHIFT_GLOB, smooth_win=15):
    """1패스 indep로 raw shift → robust 평활 → 2패스 center=평활, 폭=±step."""
    sh1, _ = run_indep(F, A, glob_)
    center = _hampel_smooth(sh1, win=smooth_win)
    n = len(A); sh = np.zeros(n); sq = np.zeros(n)
    for i in range(n):
        lo, hi = max(glob_[0], center[i] - step), min(glob_[1], center[i] + step)
        s, q, _, _ = F.fit(A[i], lo, hi, sh0=center[i])
        sh[i], sq[i] = s, q
    return sh, sq, sh1, center


def run_chunk(F, A, step=STEP_LIMIT, glob_=SHIFT_GLOB, nchunks=6, warmup=40):
    """청크 분할, 각 청크 seq 재귀를 M스캔 워밍업 lead-in 후 실행(워밍업 결과 버림)."""
    n = len(A); sh = np.zeros(n); sq = np.zeros(n)
    bounds = np.linspace(0, n, nchunks + 1, dtype=int)
    for ci in range(nchunks):
        cs, ce = bounds[ci], bounds[ci + 1]
        ws = max(0, cs - warmup)            # 워밍업 시작
        last = 0.0
        for i in range(ws, ce):
            lo, hi = max(glob_[0], last - step), min(glob_[1], last + step)
            s, q, _, _ = F.fit(A[i], lo, hi, sh0=last)
            last = s
            if i >= cs:                     # 본체만 기록(워밍업 버림)
                sh[i], sq[i] = s, q
    return sh, sq


# ─── 비교 실행 ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', default='2026-05-17')
    ap.add_argument('--nfiles', type=int, default=4)
    ap.add_argument('--warmup', type=int, default=40)
    ap.add_argument('--smooth', type=int, default=15)
    ap.add_argument('--alpha-dir', default=None, help=f'override ALPHA_DIR (default: {ALPHA_DIR})')
    ap.add_argument('--ref-dir', default=None, help=f'override REF_DIR (default: {REF_DIR})')
    args = ap.parse_args()

    alpha_dir = args.alpha_dir or ALPHA_DIR
    ref_dir = args.ref_dir or REF_DIR
    files = sorted(glob.glob(os.path.join(alpha_dir, args.day, '*_alpha_trace.dat')))[:args.nfiles]
    print(f'files: {len(files)}  ({args.day}, alpha_dir={alpha_dir})')
    wave, A, T, P, doy = load_alpha_series(files)
    print(f'scans: {len(A)}  n_pix: {A.shape[1]}')
    refs, scale = load_refs(A.shape[1], ref_dir)
    A = A[:, :]                       # 전체 px (fit_idx로 잘림)
    F = InnerFit(wave, refs)
    Af = A[:, :]                      # fit 안에서 fit_idx 슬라이스
    # InnerFit.fit 은 y 전체px 받아 build_A가 fit_idx로 평가하므로 y도 fit_idx로 잘라야 함
    Afit = A[:, F.fit_idx]

    methods = {}
    t0 = time.time(); methods['seq']     = run_seq(F, Afit);                         print(f'seq     {time.time()-t0:.1f}s')
    t0 = time.time(); methods['indep']   = run_indep(F, Afit);                       print(f'indep   {time.time()-t0:.1f}s')
    t0 = time.time(); tp = run_twopass(F, Afit, smooth_win=args.smooth); methods['twopass'] = tp[:2]; print(f'twopass {time.time()-t0:.1f}s')
    t0 = time.time(); methods['chunk']   = run_chunk(F, Afit, warmup=args.warmup);   print(f'chunk   {time.time()-t0:.1f}s')

    # ppb 계산(각 방식의 shift/squeeze로)
    ppb = {m: {g: np.zeros(len(Afit)) for g in GAS_LIST} for m in methods}
    for m, (sh, sq) in methods.items():
        for i in range(len(Afit)):
            r = F.ppb_row(Afit[i], sh[i], sq[i], T[i], P[i], scale)
            for g in GAS_LIST: ppb[m][g][i] = r[g]

    # seq 기준 차이 통계
    print('\n=== seq(현재방식) 대비 차이 ===')
    shseq = methods['seq'][0]
    hdr = f'{"method":<8} {"shiftΔrms":>10} {"shiftΔmax":>10}'
    for g in ['NO2', 'CHOCHO']:
        hdr += f' {g+"Δrms":>11} {g+"Δmax":>10} {g+"corr":>7}'
    print(hdr)
    for m in methods:
        sh = methods[m][0]
        line = f'{m:<8} {np.sqrt(np.mean((sh-shseq)**2)):>10.4f} {np.max(np.abs(sh-shseq)):>10.4f}'
        for g in ['NO2', 'CHOCHO']:
            a, b = ppb['seq'][g], ppb[m][g]
            d = b - a
            corr = np.corrcoef(a, b)[0, 1] if np.std(a) > 0 and np.std(b) > 0 else float('nan')
            line += f' {np.sqrt(np.mean(d**2)):>11.4f} {np.max(np.abs(d)):>10.4f} {corr:>7.4f}'
        print(line)

    # 저장
    np.savez(os.path.join(OUT_DIR, f'bench_{args.day}_{len(files)}f.npz'),
             doy=doy, T=T, P=P,
             **{f'sh_{m}': methods[m][0] for m in methods},
             **{f'sq_{m}': methods[m][1] for m in methods},
             **{f'ppb_{m}_{g}': ppb[m][g] for m in methods for g in GAS_LIST},
             sh1_twopass=tp[2], center_twopass=tp[3])
    print(f'\nsaved npz -> {OUT_DIR}')

    # 플롯
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        x = np.arange(len(Afit))
        fig, ax = plt.subplots(3, 1, figsize=(13, 10), sharex=True)
        for m in methods:
            ax[0].plot(x, methods[m][0], '.-', ms=2, lw=0.5, label=m)
        ax[0].plot(x, tp[2], 'x', ms=3, alpha=0.3, color='gray', label='twopass raw(P1)')
        ax[0].set_ylabel('shift (px)'); ax[0].legend(fontsize=8); ax[0].grid(alpha=0.3)
        ax[0].set_title(f'shift trajectory  {args.day}  {len(files)}files  {len(Afit)}scans')
        for gi, g in enumerate(['NO2', 'CHOCHO']):
            for m in methods:
                ax[gi+1].plot(x, ppb[m][g], '.-', ms=2, lw=0.5, label=m)
            ax[gi+1].set_ylabel(f'{g} (ppb)'); ax[gi+1].legend(fontsize=8); ax[gi+1].grid(alpha=0.3)
            ax[gi+1].axhline(0, color='k', ls='--', lw=0.5)
        ax[-1].set_xlabel('scan index (time)')
        fig.tight_layout()
        png = os.path.join(OUT_DIR, f'bench_{args.day}_{len(files)}f.png')
        fig.savefig(png, dpi=120); plt.close(fig)
        print(f'saved png -> {png}')
    except Exception as e:
        print(f'plot skip: {e}')


if __name__ == '__main__':
    main()
