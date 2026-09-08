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
    raise ValueError(f"Unrecognized time format: {s!r}  (e.g. 2026-05-20 or '2026-05-20 06:00')")


def parse_row_time(ts: str):
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(ts[:26], fmt)
        except ValueError:
            continue
    return None


def robust_rms_thresholds(rms, channels=None, K=8.0, min_n=5):
    """채널별 robust RMS 이상치 임계값을 계산해 {채널: 임계} dict로 반환.

    각 채널에서 유한하고 >0 인 RMS만 모아 log 공간에서
        thr = 10 ^ (median(log10 r) + K · MAD(log10 r))
    로 임계를 잡는다(분포 기반 — 매직넘버 불필요). RMS가 이 임계를 넘는 행이
    이상치(핏 실패/구름·저광)다.

    DOAS 자동 QC의 '단일 진실원': 핏 종료 후 자동 QC(app_window._apply_auto_qc)와
    결과뷰어의 표시/통계·내보내기 QC가 모두 이 함수를 호출한다. 식을 한 곳에서만
    관리해 세 경로가 어긋나지 않게 한다.

    Args:
        rms: RMS 값 시퀀스(array-like, NaN 허용).
        channels: 각 RMS의 채널 라벨 시퀀스(rms와 같은 길이·순서). None이면 전체를
            한 그룹으로 본다. 라벨 타입(int/str)은 호출부 내에서 일관되기만 하면 된다.
        K: 민감도. 클수록 느슨(이상치 적게 검출). 0 이하면 빈 dict 반환(=QC 끔).
        min_n: 임계를 계산할 최소 유한표본 수. 미만인 채널은 임계 +inf(=아무도 제외 안 함).

    Returns:
        {channel_label: threshold(float)} dict. K<=0이면 {}.
        표본부족이거나 MAD<=0(분포가 거의 단일값)인 채널의 임계는 +inf.
    """
    import numpy as np
    if K is None or K <= 0:
        return {}
    rms = list(rms)
    if channels is None:
        channels = [0] * len(rms)
    else:
        channels = list(channels)
    groups: dict = {}
    for r, ch in zip(rms, channels):
        groups.setdefault(ch, []).append(r)
    thr: dict = {}
    for ch, vals in groups.items():
        a = np.asarray(vals, dtype=float)
        fin = np.isfinite(a) & (a > 0)
        if int(fin.sum()) < min_n:
            thr[ch] = float('inf')
            continue
        la = np.log10(a[fin])
        med = float(np.median(la))
        mad = float(np.median(np.abs(la - med)))
        thr[ch] = float(10 ** (med + K * mad)) if mad > 0 else float('inf')
    return thr


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
                    raise ValueError(f"{os.path.basename(fp)}: Time/datetime column not found.")
                colhdr = line
                continue
            r = line.split('\t')
            t = parse_row_time(r[ti]) if len(r) > ti else None
            if t is not None:
                rows.append((t, line))
    if colhdr is None:
        raise ValueError(f"{os.path.basename(fp)}: no data header.")
    return comments, colhdr, rows


def merge_results(files: list[str], dedup: bool = True):
    """여러 결과 파일을 시간순 병합. 새 컬럼은 구형 행에 빈 값으로 채운다.

    dedup=True(기본): 같은 (timestamp, Channel) 행이 여러 파일에 있으면
    **뒤에 온 파일(인자 순서상 나중)** 행만 남긴다 — 시간대가 겹쳐도 안전.
    반환: (comments, colhdr, rows 시간순, n_dup 제거수).
    """
    comments, colhdr, rows = read_result(files[0])
    columns = colhdr.split('\t')
    for fp in files[1:]:
        _, ch2, r2 = read_result(fp)
        other = ch2.split('\t')
        for c in other:
            if c not in columns:
                columns.append(c)
        def align(line, src):
            vals = line.split('\t')
            by_name = dict(zip(src, vals))
            return '\t'.join(by_name.get(c, '') for c in columns)
        rows = [(t, align(line, columns[:len(colhdr.split('\t'))])) for t, line in rows]
        rows += [(t, align(line, other)) for t, line in r2]
        colhdr = '\t'.join(columns)

    # First-file rows may need padding even when no later file introduced columns.
    if colhdr != '\t'.join(columns):
        colhdr = '\t'.join(columns)
    if rows:
        # rows already aligned above; pad initial rows for a single-file/new schema case.
        rows = [(t, line if len(line.split('\t')) == len(columns)
                 else '\t'.join(line.split('\t') + [''] * (len(columns) - len(line.split('\t')))))
                for t, line in rows]

    n_dup = 0
    if dedup:
        cols = columns
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


def split_rows_by_day(rows) -> dict:
    """rows → {'YYMMDD': [rows...]} 날짜별 분할. 핏은 스캔 단위 독립이라 무손실.
    날짜 경계는 행 타임스탬프 그대로(TZ 변환 없음 — Cold=UTC/Hot=KST 각자 기준)."""
    out: dict[str, list] = {}
    for t, line in rows:
        out.setdefault(f"{t:%y%m%d}", []).append((t, line))
    return out


def archive_existing(path: str, base: str) -> str | None:
    """path에 파일이 이미 있으면 {base}/_archive/ 아래로 이동(비파괴 — 삭제 없음).

    상대경로를 보존하고 파일 수정시각을 이름에 붙여 몇 번을 재핏해도 이전 버전이
    전부 남는다: {base}/_archive/{상대경로stem}__{mtime YYMMDD_HHMMSS}{ext}.
    path가 없으면 None, 이동했으면 이동된 경로를 반환."""
    if not os.path.exists(path):
        return None
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base))
    if rel.startswith('..'):        # base 밖 파일은 상대경로 대신 이름만
        rel = os.path.basename(path)
    stem, ext = os.path.splitext(rel)
    mt = datetime.fromtimestamp(os.path.getmtime(path))
    dst = os.path.join(base, '_archive', f"{stem}__{mt:%y%m%d_%H%M%S}{ext}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.replace(path, dst)
    return dst


def write_result(out: str, comments, colhdr, rows, note: str = ''):
    """주석헤더 + 이력주석 + 컬럼헤더 + 행 저장."""
    with open(out, 'w', encoding='utf-8') as fh:
        for c in comments:
            fh.write(c + '\n')
        info = f"# [result_io] {len(rows)} rows"
        if rows:
            info += f" | range {rows[0][0]:%Y-%m-%d %H:%M} ~ {rows[-1][0]:%Y-%m-%d %H:%M}"
        info += f" | generated {datetime.now():%Y-%m-%d %H:%M}"
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
    앞쪽 날짜 프리픽스(YYMMDD_ 또는 YYMMDD-YYMMDD_)·뒤쪽 _slice…/_merge…/_merged 태그 제거.
    예: '…/260517-260606_cold_438-476nm_Poly4_ShLink_slice2605..' → 'cold_438-476nm_Poly4_ShLink'."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = _re.sub(r'^\d{6}(-\d{6})?_', '', stem)                    # 앞 날짜(범위)
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
    아니면 파일이 있는 폴더를 반환(버킷 못 찾음 → 제자리 저장).
    _derived/ 안의 파일이면 한 단계 더 올라가 진짜 base를 반환(중첩 방지)."""
    ap = os.path.abspath(path)
    qc_dir = os.path.dirname(ap)
    neg_dir = os.path.dirname(qc_dir)
    date_dir = os.path.dirname(neg_dir)
    if (os.path.basename(neg_dir) in ('neg_o', 'neg_x')
            and os.path.basename(qc_dir).startswith('QC')):
        base = os.path.dirname(date_dir)
        if os.path.basename(base) == '_derived':
            base = os.path.dirname(base)
        return base
    return qc_dir


def bucketed_out_name(first_input: str, rows, comments, kind: str = 'slice',
                      nfiles: int = 1, ext: str = '.dat',
                      qc_override: str | None = None) -> str:
    """머지/슬라이스 결과의 자동 저장경로: {base}/_derived/{날짜}/{neg}/{QC}/{이름}.
    neg·QC는 입력파일 # 헤더에서 상속(qc_override 있으면 그게 우선 — 뷰어 사후 QC 재적용),
    날짜는 출력 rows의 실제 범위. base는 입력이 버킷 안이면 그 최상위, 아니면 입력 폴더.
    _derived 아래로 두는 이유: 정식 결과는 날짜별(하루=폴더) 트리로 저장되므로,
    기간 머지 같은 파생물이 최상위에 범위 폴더를 다시 만들지 않게 분리."""
    base = detect_fitting_base(first_input)
    neg, qc = neg_qc_from_comments(comments)
    if qc_override:
        qc = qc_override
    folder = os.path.join(base, '_derived', _date_bucket(rows), neg or 'neg_x', qc or 'QCoff')
    stem = clean_stem(first_input)
    if kind == 'merge':
        name = f'{stem}_merge{nfiles}_{_span_tag(rows)}{ext}'
    else:
        name = f'{stem}_slice_{_span_tag(rows)}{ext}'
    return os.path.join(folder, name)
