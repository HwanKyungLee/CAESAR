"""AUGUR alpha(*_alpha_trace.dat) -> QDOAS ASCII "line format" 스펙트럼 변환기.

목적: build_qdoas_xs.py(레퍼런스 단면적 변환)와 짝을 이루는 스크립트. Augur의 alpha는
이미 R(t)/Rayleigh/경로보정이 끝난 값이라 QDOAS(공개강품을 모르는 범용 DOAS 도구)에
raw 강도로 못 넣는다 -- 대신 가상 스펙트럼 I(lambda)=exp(-K*alpha(lambda)),
I0(lambda)=1(평탄)을 만들면 QDOAS가 계산하는 광학밀도 -ln(I/I0) = K*alpha가 되어,
K로 나누기만 하면 Augur의 alpha와 정확히 같아진다. (자세한 배경은
README.md "비교 방법론" 참조.)

K(스케일 인자)를 두는 이유: alpha가 워낙 작으면(~1e-7 수준, 콜드 채널 실측 기준)
I=exp(-alpha)~1-alpha가 1.0에 극히 가까워, QDOAS 내부가 만약 spectra를 float32로
저장한다면(float32의 1.0 부근 분해능은 ~1.19e-7) 신호가 반올림 잡음에 거의 묻힐 위험이
있다. bench_common.py의 _underflow_scale과 정확히 같은 문제/해법 -- alpha를 10의
거듭제곱 K로 미리 키워서 exp(-K*alpha)가 1.0에서 충분히(수 %) 벗어나게 만든 뒤,
QDOAS가 내놓는 농도(SCD)를 K로 나눠 원래 스케일로 되돌린다.

QDOAS 프로젝트 Instrumental 페이지 설정(Project_InstrumentalAscii.jpg 확인 완료,
2026-09-07):
  Instr. Format = ASCII, Format = line, Detector Size = <픽셀수>
  Read from file: DD/MM/YYYY 체크, Decimal Time 체크, 나머지(태양천정각/방위각/
    고도각/Lambda)는 전부 체크 해제
  Calibration File = build_qdoas_xs.py에도 쓴 Calib_*.txt (픽셀->파장, 단일컬럼)
Analysis Window의 Ref. Selection = File, Reference 1 = 이 스크립트가 만드는
  reference_flat.asc, Reference 2 = 비움. Calibration 페이지의 보정 방법은 "None"
  (가상 스펙트럼엔 태양 프라운호퍼선이 없어 QDOAS의 자체 파장보정이 무의미/실패할 수
  있음 -- Analysis.html: "If the wavelength calibration ... is assumed to be accurate
  enough, the option None can be used").

두 가지 모드:
  1) 단일 폴더(테스트용, 기존 방식): --alpha-dir <하루 폴더>
  2) 배치(실전용, 2026-09-07 신규): --alpha-root <채널 루트 폴더, 그 아래 YYYY-MM-DD
     날짜별 하위폴더가 있는 구조> --date-start --date-end
     -> 날짜별로 각각 <out-dir>/<날짜>.asc 하나씩 생성(라인 수가 너무 커지는 것을
     피하고, QDOAS "Files" 탭에서 폴더째로 추가해 한 번에 배치 실행할 수 있게 함).
     레퍼런스 파일(I0=1, 평탄)은 전체 배치에 1개만 생성(픽셀창이 모든 날짜에
     동일하므로). 스케일 인자 K는 배치의 첫 날 데이터로 한 번만 정하고 이후
     모든 날짜에 동일하게 적용(날짜 간 비교 가능성을 위해 -- 날짜마다 K가
     바뀌면 QDOAS 결과를 원래 스케일로 되돌릴 때 날짜별로 다른 K를 추적해야
     해서 번거롭고 실수 위험 있음).

사용 예 (콜드, 실제 캠페인 창 774-1550px, 확정됨, 60s 알파):
  python build_qdoas_spectrum.py --alpha-root "C:\\GHL\\2026 yeosu\\Output\\alpha\\60s\\cold" \\
      --date-start 2026-05-17 --date-end 2026-06-17 \\
      --px-lo 774 --px-hi 1550 \\
      --calib "C:\\GHL\\2026 yeosu\\Output\\wv_cal\\cold\\Calib_20260523_Hg_4line_400-497nm_Poly2.txt" \\
      --out-dir qdoas_input\\cold

  (핫 채널 ANs=600-1270px/poly4(wv_cal\\roi1), PNs=900-1450px/poly3(wv_cal\\roi2) --
  2026-09-07 확정, README.md/DOASIS_변환_로직.md의 "미해결 발견" 참조.)

--calib는 2026-09-07부터 필수: QDOAS의 Reference1/2 로더(engine/analyse.c의
AnalyseLoadVector, GitHub UVVIS-BIRA-IASB/qdoas에서 직접 확인)가 reference_flat
파일을 "파장(nm) 값" 2컬럼 x N줄 포맷으로 기대한다는 게 밝혀져서, 실제 파장값이
필요해짐(이전 버전은 line 포맷 + 더미 값이라 QDOAS Fatal Error 남).

단일 폴더 테스트 예:
  python build_qdoas_spectrum.py --alpha-dir <alpha\\60s\\cold\\2026-06-05 폴더>
      --px-lo 774 --px-hi 1550 --calib <위 Calib 파일> --out qdoas_cold_2026-06-05.asc
"""
import argparse, glob, os, re
from datetime import date, timedelta
import numpy as np


def read_alpha_file(path, px_lo, px_hi):
    """AUGUR *_alpha_trace.dat 1개 파일 -> (datetime 문자열 리스트, alpha 배열 [n,px_hi-px_lo])."""
    lines = open(path, encoding='utf-8', errors='replace').readlines()
    hdr_i = next(i for i, l in enumerate(lines) if l.startswith('row_idx'))
    cols = lines[hdr_i].rstrip('\n').split('\t')
    idx_dt = cols.index('datetime')
    ipx = next(i for i, c in enumerate(cols) if c.startswith('px'))
    times, rows = [], []
    for l in lines[hdr_i + 1:]:
        if not l.strip() or l.startswith('#'):
            continue
        p = l.rstrip('\n').split('\t')
        if len(p) < ipx + px_hi:
            continue
        try:
            a = np.array(p[ipx + px_lo:ipx + px_hi], dtype=float)
        except ValueError:
            continue
        times.append(p[idx_dt])
        rows.append(a)
    return times, np.array(rows)


def read_day_folder(day_dir, px_lo, px_hi, nfiles=None):
    """하루 폴더의 *_alpha_trace.dat 전부를 읽어 (times, alpha[n,px]) 하나로 합친다."""
    files = sorted(glob.glob(os.path.join(day_dir, '*_alpha_trace.dat')))
    if nfiles:
        files = files[:nfiles]
    if not files:
        return [], np.zeros((0, px_hi - px_lo))
    all_times, all_alpha = [], []
    for fp in files:
        t, a = read_alpha_file(fp, px_lo, px_hi)
        if len(t) == 0:
            continue
        all_times += t
        all_alpha.append(a)
    if not all_alpha:
        return [], np.zeros((0, px_hi - px_lo))
    return all_times, np.vstack(all_alpha)


def pick_scale_factor(alpha: np.ndarray, target=0.05) -> float:
    """bench_common._underflow_scale과 같은 발상: |alpha|의 대표값(중앙값 절대값,
    0이면 최댓값)을 target(기본 0.05, 광학밀도로 적당히 '작지만 0.0데드존은 아닌'
    크기) 근방으로 올리는 10의 거듭제곱 K를 고른다."""
    ref = np.median(np.abs(alpha))
    if ref == 0:
        ref = np.max(np.abs(alpha))
    if ref == 0:
        return 1.0
    return float(10 ** np.round(np.log10(target / ref)))


def write_line_format(path, dts, intensities, digits=7):
    """QDOAS ASCII line format: 한 줄 = DD/MM/YYYY<space>decimal_time<space>I_1 I_2 ... I_N

    digits=7: 원본 alpha 자체가 유효숫자 ~7자리로 기록돼 있어(예: 7.378100e-08)
    그 이상 정밀도는 의미 없음 -- 배치 변환 시 파일 크기를 아낀다(하루~5-10만
    스캔 단위라 소수점 자리 하나하나가 전체 용량에 직접 영향)."""
    with open(path, 'w') as f:
        for dt_str, row in zip(dts, intensities):
            # dt_str: "2026-06-05 00:51:31.166"
            date_part, time_part = dt_str.split(' ')
            y, m, d = date_part.split('-')
            hh, mm, ss = time_part.split(':')
            decimal_time = float(hh) + float(mm) / 60.0 + float(ss) / 3600.0
            vals = ' '.join(f'{v:.{digits}e}' for v in row)
            f.write(f'{d}/{m}/{y} {decimal_time:.8f} {vals}\n')


def write_flat_reference(path, wavelengths_nm):
    """I0=1(평탄) 레퍼런스.

    2026-09-07 정정(중요): 처음엔 이것도 line 포맷(날짜+시각+전체 픽셀값 한 줄)으로
    썼었는데, 그건 틀렸다 -- QDOAS 소스코드(engine/analyse.c의 AnalyseLoadVector(),
    Reference 1/2 파일 전용 로더, GitHub UVVIS-BIRA-IASB/qdoas에서 직접 확인)는
    Reference 파일을 "한 줄 = 파장(nm) 하나 + 값 하나"인 2컬럼 x N줄(N=Detector Size)
    포맷으로 기대한다 -- Instrumental 탭의 line/column 설정과 무관한 별도 로더다.
    line 포맷으로 주면 "AnalyseLoadVector records of file ... do not have the
    expected size" Fatal Error가 난다. build_qdoas_xs.py가 만드는 .xs 파일과 같은
    구조라고 생각하면 된다.

    wavelengths_nm: 이 레퍼런스가 커버하는 픽셀 구간의 실제 파장값 배열(캘리브레이션
    파일에서 같은 px_lo:px_hi로 슬라이스한 것) -- QDOAS가 cross-section을 이 그리드에
    맞춰 보간하므로 대충 넣으면 안 되고 실제 값을 써야 한다."""
    with open(path, 'w') as f:
        for w in wavelengths_nm:
            f.write(f'{w:.6f}\t{1.0:.7e}\n')


def load_calib_wavelengths(calib_path, px_lo, px_hi):
    """Calib_*.txt(픽셀->파장, 단일컬럼, 줄번호=픽셀 0-based로 alpha의 px0..px2047과
    정렬됨 -- build_qdoas_xs.py/run_hot_real.py와 동일 규약)에서 [px_lo:px_hi) 슬라이스."""
    wl = np.loadtxt(calib_path)
    return wl[px_lo:px_hi]


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def run_single(args):
    """기존 단일 폴더 모드(테스트용)."""
    all_times, alpha = read_day_folder(args.alpha_dir, args.px_lo, args.px_hi, args.nfiles)
    if len(all_times) == 0:
        raise SystemExit(f'no *_alpha_trace.dat under {args.alpha_dir}')
    n_px = alpha.shape[1]

    K = pick_scale_factor(alpha, args.target_od)
    intensity = np.exp(-K * alpha)
    print(f'scans={len(all_times)}  px={n_px}  alpha median|.|={np.median(np.abs(alpha)):.3e}  '
          f'scale K={K:.1e}  -> K*alpha median|.|={np.median(np.abs(K*alpha)):.3e}  '
          f'I range=[{intensity.min():.6f}, {intensity.max():.6f}]')

    write_line_format(args.out, all_times, intensity)
    ref_path = os.path.join(os.path.dirname(args.out) or '.', f'reference_flat_{n_px}px.asc')
    write_flat_reference(ref_path, load_calib_wavelengths(args.calib, args.px_lo, args.px_hi))

    meta_path = args.out + '.meta.txt'
    with open(meta_path, 'w') as f:
        f.write(f'scale_factor_K={K!r}\n')
        f.write(f'px_lo={args.px_lo}\npx_hi={args.px_hi}\n')
        f.write(f'n_scans={len(all_times)}\n')
        f.write('IMPORTANT: QDOAS가 내놓는 SCD(농도)는 이 파일의 alpha보다 K배 큽니다.\n')
        f.write('Augur 결과와 비교할 때 QDOAS SCD를 K로 나누세요.\n')

    print(f'Saved spectra -> {args.out}')
    print(f'Saved flat I0=1 reference -> {ref_path}  (QDOAS Analysis Window Reference 1로 지정)')
    print(f'Saved scale-factor note -> {meta_path}  (비교 시 QDOAS 출력 농도를 K={K:.1e}로 나눌 것)')


def run_batch(args):
    """신규 배치 모드: 날짜 범위 전체를 하루 1파일씩 변환."""
    start = date.fromisoformat(args.date_start)
    end = date.fromisoformat(args.date_end)
    os.makedirs(args.out_dir, exist_ok=True)

    K = None
    n_px = args.px_hi - args.px_lo
    day_summaries = []
    missing_days = []
    for d in daterange(start, end):
        dstr = d.isoformat()
        day_dir = os.path.join(args.alpha_root, dstr)
        if not os.path.isdir(day_dir):
            missing_days.append(dstr)
            continue
        times, alpha = read_day_folder(day_dir, args.px_lo, args.px_hi, args.nfiles)
        if len(times) == 0:
            print(f'  {dstr}: SKIP (파일 없음/빈 폴더)')
            missing_days.append(dstr)
            continue
        if K is None:
            K = pick_scale_factor(alpha, args.target_od)
            print(f'  스케일 인자 K={K:.1e}  (첫 날 {dstr} 데이터로 결정, 이후 전 날짜 동일 적용)')
        intensity = np.exp(-K * alpha)
        out_path = os.path.join(args.out_dir, f'{dstr}.asc')
        write_line_format(out_path, times, intensity)
        med_od = float(np.median(np.abs(K * alpha)))
        print(f'  {dstr}: {len(times)} scans  ->  {out_path}  '
              f'(K*alpha median|.|={med_od:.3e}, I range=[{intensity.min():.4f}, {intensity.max():.4f}])')
        day_summaries.append((dstr, len(times), med_od))

    if K is None:
        raise SystemExit('날짜 범위 안에 유효한 데이터가 하나도 없습니다 -- 경로/날짜를 확인하세요.')

    ref_path = os.path.join(args.out_dir, f'reference_flat_{n_px}px.asc')
    write_flat_reference(ref_path, load_calib_wavelengths(args.calib, args.px_lo, args.px_hi))

    # 2026-09-07 정정(Cold 실행 중 발견): 이 메타 파일을 예전엔 out_dir 안에
    # ('_batch_meta.txt') 썼는데, QDOAS Raw Spectra "Insert Directory"가 폴더 안 파일을
    # 전부 스펙트럼으로 집어넣어서 "_batch_meta.txt"까지 읽으려다 FATAL(ASCII_Read,
    # format unknown)을 낸다. 알파벳/아스키 순서상 "_"(0x5F)가 숫자로 시작하는
    # 날짜 파일명(2026-...)보다 뒤에 오므로, 정상 날짜 파일을 전부(우리 경우 32일치
    # 43259스캔) 처리한 "다음"에야 이 파일에 걸려 죽는다 -- 겉보기엔 배치가 끝까지
    # 잘 도는 것처럼 보이다 마지막에 에러가 나서 헷갈리기 쉽다. 그래서 out_dir의
    # 부모 폴더에 채널명을 붙여 저장(= QDOAS가 Insert Directory할 폴더 밖).
    out_dir_norm = os.path.normpath(args.out_dir)
    meta_path = os.path.join(os.path.dirname(out_dir_norm) or '.',
                              f'_batch_meta_{os.path.basename(out_dir_norm)}.txt')
    total_scans = sum(s[1] for s in day_summaries)
    with open(meta_path, 'w', encoding='utf-8') as f:
        f.write(f'scale_factor_K={K!r}\n')
        f.write(f'px_lo={args.px_lo}\npx_hi={args.px_hi}\n')
        f.write(f'date_range={args.date_start}~{args.date_end}\n')
        f.write(f'days_converted={len(day_summaries)}\n')
        f.write(f'total_scans={total_scans}\n')
        if missing_days:
            f.write(f'missing_or_empty_days({len(missing_days)})={",".join(missing_days)}\n')
        f.write('per_day: date, n_scans, K*alpha median|.|\n')
        for dstr, n, med_od in day_summaries:
            f.write(f'  {dstr}\t{n}\t{med_od:.3e}\n')
        f.write('\nIMPORTANT: QDOAS가 내놓는 SCD(농도)는 이 파일들의 alpha보다 K배 큽니다.\n')
        f.write('Augur 결과와 비교할 때 QDOAS SCD를 K로 나누세요.\n')

    print(f'\n총 {len(day_summaries)}일 변환 완료 (스캔 합계 {total_scans})'
          + (f', 데이터 없는 날짜 {len(missing_days)}개(스킵)' if missing_days else ''))
    print(f'출력 폴더 -> {args.out_dir}  (QDOAS Files 탭에서 이 폴더를 통째로 추가하면 됨)')
    print(f'평탄 I0=1 레퍼런스 -> {ref_path}')
    print(f'배치 요약(K, 날짜별 스캔수/광학밀도) -> {meta_path}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--alpha-dir', help='[단일 폴더 모드] alpha\\10s\\<채널>\\<날짜> 폴더')
    ap.add_argument('--alpha-root', help='[배치 모드] alpha\\10s\\<채널> 폴더(그 아래 YYYY-MM-DD 하위폴더)')
    ap.add_argument('--date-start', help='[배치 모드] YYYY-MM-DD')
    ap.add_argument('--date-end', help='[배치 모드] YYYY-MM-DD (포함)')
    ap.add_argument('--px-lo', type=int, required=True)
    ap.add_argument('--px-hi', type=int, required=True, help='exclusive (numpy 슬라이스와 동일)')
    ap.add_argument('--calib', required=True,
                     help='Calib_*.txt (픽셀->파장, 단일컬럼, build_qdoas_xs.py의 --calib와 같은 파일). '
                          'reference_flat_*.asc의 파장 컬럼을 채우는 데 필요(2026-09-07: QDOAS가 '
                          'Reference1/2를 2컬럼[파장,값]xN줄 포맷으로 읽는다는 게 밝혀져서 필수가 됨).')
    ap.add_argument('--nfiles', type=int, default=None, help='하루당 파일 개수 제한(기본: 전부, 테스트용)')
    ap.add_argument('--out', help='[단일 폴더 모드] 출력 스펙트럼 파일 경로')
    ap.add_argument('--out-dir', help='[배치 모드] 출력 폴더(날짜별 <YYYY-MM-DD>.asc 생성)')
    ap.add_argument('--target-od', type=float, default=0.05, help='스케일링 후 목표 광학밀도 크기(기본 0.05)')
    args = ap.parse_args()

    if args.alpha_root:
        if not (args.date_start and args.date_end and args.out_dir):
            raise SystemExit('배치 모드는 --date-start --date-end --out-dir가 모두 필요합니다.')
        run_batch(args)
    elif args.alpha_dir:
        if not args.out:
            raise SystemExit('단일 폴더 모드는 --out이 필요합니다.')
        run_single(args)
    else:
        raise SystemExit('--alpha-dir(단일 폴더) 또는 --alpha-root(배치) 중 하나를 지정하세요.')


if __name__ == '__main__':
    main()
