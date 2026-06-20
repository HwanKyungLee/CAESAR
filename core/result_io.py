"""리트리벌 결과 파일 공통 IO — 읽기/자르기/병합.

CLI(tools/result_slice.py)와 GUI(결과뷰어 내보내기/병합)가 같은 코드를 쓴다.
지원 형식: CAESAR 핏 결과('File<TAB>...' 헤더), 유도농도('datetime<TAB>...'),
autosave TSV — 공통 조건은 'Time' 또는 'datetime' 컬럼이 있는 탭구분 텍스트.
"""
from __future__ import annotations

import os
from datetime import datetime


def parse_when(s: str | None, end: bool = False):
    """'YYYY-MM-DD[ HH:MM[:SS]]' → datetime. 날짜만 주고 end=True면 23:59:59."""
    if not s:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            d = datetime.strptime(s.strip(), fmt)
            if fmt == '%Y-%m-%d' and end:
                d = d.replace(hour=23, minute=59, second=59)
            return d
        except ValueError:
            continue
    raise ValueError(f"시간 형식 인식 불가: {s!r}  (예: 2026-05-20 또는 '2026-05-20 06:00')")


def parse_row_time(ts: str):
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(ts[:26], fmt)
        except ValueError:
            continue
    return None


def read_result(fp: str):
    """결과 파일 → (주석헤더 리스트, 컬럼헤더 문자열, [(datetime, 원본행 문자열)]).

    Time/datetime 컬럼이 없으면 ValueError.
    """
    comments, colhdr, rows = [], None, []
    ti = None
    with open(fp, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.rstrip('\n')
            if not line:
                continue
            if line.startswith('#'):
                if colhdr is None:
                    comments.append(line)
                continue
            if colhdr is None:
                cols = line.split('\t')
                for cand in ('Time', 'datetime'):
                    if cand in cols:
                        ti = cols.index(cand)
                        break
                if ti is None:
                    raise ValueError(f"{os.path.basename(fp)}: Time/datetime 컬럼을 찾을 수 없습니다.")
                colhdr = line
                continue
            r = line.split('\t')
            t = parse_row_time(r[ti]) if len(r) > ti else None
            if t is not None:
                rows.append((t, line))
    if colhdr is None:
        raise ValueError(f"{os.path.basename(fp)}: 데이터 헤더가 없습니다.")
    return comments, colhdr, rows


def merge_results(files: list[str], dedup: bool = True):
    """여러 결과 파일을 시간순 병합. 컬럼 불일치면 ValueError.

    dedup=True(기본): 같은 (timestamp, Channel) 행이 여러 파일에 있으면
    **뒤에 온 파일(인자 순서상 나중)** 행만 남긴다 — 시간대가 겹쳐도 안전.
    반환: (comments, colhdr, rows 시간순, n_dup 제거수).
    """
    comments, colhdr, rows = read_result(files[0])
    for fp in files[1:]:
        _, ch2, r2 = read_result(fp)
        if ch2 != colhdr:
            raise ValueError(
                f"Column mismatch — cannot merge:\n  {os.path.basename(files[0])}\n  {os.path.basename(fp)}\n"
                "(merge only same-channel / same-format results)")
        rows += r2

    n_dup = 0
    if dedup:
        cols = colhdr.split('\t')
        ci = cols.index('Channel') if 'Channel' in cols else None
        seen = {}   # (epoch, channel) → 마지막 등장 인덱스(나중 파일 우선)
        for i, (t, line) in enumerate(rows):
            ch = line.split('\t')[ci] if (ci is not None and ci < len(line.split('\t'))) else ''
            seen[(t, ch)] = i      # 같은 키면 뒤(나중 파일)가 덮어씀
        keep_idx = set(seen.values())
        n_dup = len(rows) - len(keep_idx)
        rows = [r for i, r in enumerate(rows) if i in keep_idx]

    rows.sort(key=lambda x: x[0])
    return comments, colhdr, rows, n_dup


def slice_rows(rows, t0: datetime | None = None, t1: datetime | None = None):
    if t0:
        rows = [r for r in rows if r[0] >= t0]
    if t1:
        rows = [r for r in rows if r[0] <= t1]
    return rows


def write_result(out: str, comments, colhdr, rows, note: str = ''):
    """주석헤더 + 이력주석 + 컬럼헤더 + 행 저장."""
    with open(out, 'w', encoding='utf-8') as fh:
        for c in comments:
            fh.write(c + '\n')
        info = f"# [result_io] {len(rows)}행"
        if rows:
            info += f" | 범위 {rows[0][0]:%Y-%m-%d %H:%M} ~ {rows[-1][0]:%Y-%m-%d %H:%M}"
        info += f" | 생성 {datetime.now():%Y-%m-%d %H:%M}"
        if note:
            info += f" | {note}"
        fh.write(info + '\n')
        fh.write(colhdr + '\n')
        for _, line in rows:
            fh.write(line + '\n')
    return out


import re as _re


def clean_stem(path: str) -> str:
    """파일경로 → 설명적 핵심 이름만. 디렉토리·확장자 제거 +
    앞쪽 날짜범위 프리픽스(YYMMDD-YYMMDD_)·뒤쪽 _slice…/_merge…/_merged 태그 제거.
    예: '…/260517-260606_cold_438-476nm_Poly4_ShLink_slice2605..' → 'cold_438-476nm_Poly4_ShLink'."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = _re.sub(r'^\d{6}-\d{6}_', '', stem)                       # 앞 날짜범위
    stem = _re.sub(r'_(slice|merge\d*|merged)[0-9_\-]*$', '', stem)   # 뒤 가공 태그
    stem = _re.sub(r'_\d{6}[-_]\d{4}-\d{6}[-_]\d{4}$', '', stem)      # 뒤 slice 시각태그
    return stem or 'result'


def _span_tag(rows) -> str:
    """rows 시간범위 → 'YYMMDD_HHMM-YYMMDD_HHMM' (같은 날이면 시각만)."""
    if not rows:
        return 'empty'
    a, b = rows[0][0], rows[-1][0]
    if a.date() == b.date():
        return f"{a:%y%m%d_%H%M}-{b:%H%M}"
    return f"{a:%y%m%d_%H%M}-{b:%y%m%d_%H%M}"


def auto_out_name(first_input: str, rows, ext: str = '.dat') -> str:
    """슬라이스 자동 파일명: {핵심이름}_slice_{실제시간범위}.dat (원본 폴더에)."""
    folder = os.path.dirname(os.path.abspath(first_input))
    return os.path.join(folder, f'{clean_stem(first_input)}_slice_{_span_tag(rows)}{ext}')


def merge_out_name(first_input: str, rows, nfiles: int, ext: str = '.dat') -> str:
    """병합 자동 파일명: {핵심이름}_merge{N}_{전체시간범위}.dat."""
    folder = os.path.dirname(os.path.abspath(first_input))
    return os.path.join(folder, f'{clean_stem(first_input)}_merge{nfiles}_{_span_tag(rows)}{ext}')


# ── 세팅 버킷 경로(날짜/neg/QC) — GUI save()와 동일 규칙을 머지/슬라이스에도 적용 ──

def _date_bucket(rows) -> str:
    """rows 시간범위 → 날짜 버킷 'YYMMDD' 또는 'YYMMDD-YYMMDD' (GUI _drange와 동일 형식)."""
    if not rows:
        return 'nodate'
    a, b = rows[0][0], rows[-1][0]
    return f"{a:%y%m%d}" if a.date() == b.date() else f"{a:%y%m%d}-{b:%y%m%d}"


def neg_qc_from_comments(comments) -> tuple[str | None, str | None]:
    """결과 # 헤더 주석에서 (neg_bucket, qc_bucket) 추출. 못 찾으면 (None, None).
    인식 줄: '# Allow Negative Gas (±Neg): ON/OFF', '# Auto QC: ON (... K=6 ...) / OFF'.
    (구버전 파일엔 이 줄이 없을 수 있음 → None 반환, 호출부에서 기본값 처리.)"""
    neg = qc = None
    for c in comments or []:
        cu = c.upper()
        if 'ALLOW NEGATIVE' in cu or '±NEG' in c:
            m = _re.search(r':\s*(ON|OFF)', cu)
            neg = 'neg_o' if (m and m.group(1) == 'ON') else 'neg_x'
        if 'AUTO QC' in cu:
            if _re.search(r':\s*OFF', cu):
                qc = 'QCoff'
            else:
                m = _re.search(r'K=\s*([\d.]+)', c)
                qc = f"QCk{float(m.group(1)):g}" if m else 'QCmanual'
    return neg, qc


def detect_fitting_base(path: str) -> str:
    """path가 .../{날짜}/{neg_o|neg_x}/{QC*}/파일 버킷 구조 안이면 그 최상위 base를,
    아니면 파일이 있는 폴더를 반환(버킷 못 찾음 → 제자리 저장)."""
    ap = os.path.abspath(path)
    qc_dir = os.path.dirname(ap)
    neg_dir = os.path.dirname(qc_dir)
    date_dir = os.path.dirname(neg_dir)
    if (os.path.basename(neg_dir) in ('neg_o', 'neg_x')
            and os.path.basename(qc_dir).startswith('QC')):
        return os.path.dirname(date_dir)
    return qc_dir


def bucketed_out_name(first_input: str, rows, comments, kind: str = 'slice',
                      nfiles: int = 1, ext: str = '.dat',
                      qc_override: str | None = None) -> str:
    """머지/슬라이스 결과의 자동 저장경로: {base}/{날짜}/{neg}/{QC}/{이름}.
    neg·QC는 입력파일 # 헤더에서 상속(qc_override 있으면 그게 우선 — 뷰어 사후 QC 재적용),
    날짜는 출력 rows의 실제 범위. base는 입력이 버킷 안이면 그 최상위, 아니면 입력 폴더."""
    base = detect_fitting_base(first_input)
    neg, qc = neg_qc_from_comments(comments)
    if qc_override:
        qc = qc_override
    folder = os.path.join(base, _date_bucket(rows), neg or 'neg_x', qc or 'QCoff')
    stem = clean_stem(first_input)
    if kind == 'merge':
        name = f'{stem}_merge{nfiles}_{_span_tag(rows)}{ext}'
    else:
        name = f'{stem}_slice_{_span_tag(rows)}{ext}'
    return os.path.join(folder, name)
