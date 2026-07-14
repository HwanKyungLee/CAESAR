"""Output/fitting 레거시(날짜범위 폴더) → 날짜별(하루=폴더) 구조 일회성 마이그레이션.

배경: 예전 저장 규칙은 {로드범위}/{neg}/{QC}/ 라서 같은 기간을 재핏할 때마다
겹치는 범위 폴더가 늘었다(260517-260618, 260517-260629, …). 핏은 스캔 단위
독립이므로 결과를 날짜별로 잘라도 무손실 — 이 스크립트가 레거시 파일을
{base}/{YYMMDD}/{neg}/{QC}/{YYMMDD}_{이름}.dat 로 재슬라이스한다.

원칙(비파괴 — 아무것도 지우지 않음):
  - Time/datetime 열이 있는 .dat  → 날짜별 분할 저장. 같은 타깃에 여러 소스가
    겹치면 mtime 오래된 것부터 처리 → 최신이 남고 이전 버전은 _archive/로 이동.
  - 그 외 파일(.csv 계산 산출물 등) → _derived/legacy/{원상대경로} 로 이동(내용 불변).
  - 처리한 원본 .dat                → _archive/legacy/{원상대경로} 로 이동.
  - 범위 폴더명이 아닌 최상위 폴더('sh fix' 등) → 통째로 _archive/legacy/ 로 이동.
  - '_autosave', '_archive', '_derived' 는 건드리지 않음.

기본은 dry-run(계획만 출력). 실제 실행은 --apply.

사용:
  python tools/migrate_fitting_daily.py "C:/Doasis_Work/Output/fitting"          # 계획만
  python tools/migrate_fitting_daily.py "C:/Doasis_Work/Output/fitting" --apply  # 실행
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.result_io import (read_result, write_result, split_rows_by_day,
                            archive_existing, clean_stem, neg_qc_from_comments)

DATE_DIR = re.compile(r'^\d{6}(-\d{6})?$')
SKIP_DIRS = {'_autosave', '_archive', '_derived'}


def _neg_qc_from_path(rel_parts, comments):
    """원본 경로 조각(범위폴더 아래)에서 neg/QC 버킷 추출, 없으면 # 헤더에서."""
    neg = qc = None
    for p in rel_parts:
        if p in ('neg_o', 'neg_x'):
            neg = p
        elif p.startswith('QC'):
            qc = p
    if neg is None or qc is None:
        n2, q2 = neg_qc_from_comments(comments)
        neg, qc = neg or n2, qc or q2
    return neg or 'neg_x', qc or 'QCoff'


def _move(src, dst, apply):
    print(f"  MOVE  {src}\n     →  {dst}")
    if apply:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):   # 이름 충돌 시 __N 붙여 보존
            stem, ext = os.path.splitext(dst)
            i = 1
            while os.path.exists(f"{stem}__{i}{ext}"):
                i += 1
            dst = f"{stem}__{i}{ext}"
        shutil.move(src, dst)


def migrate(base: str, apply: bool):
    base = os.path.abspath(base)
    legacy_dat, other_files, stray_dirs = [], [], []

    for name in sorted(os.listdir(base)):
        top = os.path.join(base, name)
        if not os.path.isdir(top) or name in SKIP_DIRS:
            continue
        if not DATE_DIR.match(name):
            stray_dirs.append(top)
            continue
        if '-' not in name:        # 이미 하루짜리 폴더(신규 규칙) — 그대로 둠
            continue
        for dirpath, _dirs, files in os.walk(top):
            for f in files:
                fp = os.path.join(dirpath, f)
                (legacy_dat if f.lower().endswith('.dat') else other_files).append(fp)

    # 최신이 이기도록 mtime 오래된 것부터(나중에 쓴 파일이 기존 타깃을 _archive로 밀어냄)
    legacy_dat.sort(key=os.path.getmtime)

    n_split = n_moved = n_arch = n_err = 0
    for fp in legacy_dat:
        rel = os.path.relpath(fp, base)
        try:
            comments, colhdr, rows = read_result(fp)
        except (ValueError, OSError) as e:
            print(f"  SKIP  {rel}  (파싱불가: {e})")
            other_files.append(fp)
            n_err += 1
            continue
        neg, qc = _neg_qc_from_path(rel.split(os.sep)[1:-1], comments)
        stem = clean_stem(fp)
        by_day = split_rows_by_day(rows)
        print(f"SPLIT  {rel}  →  {len(by_day)} day(s)  [{neg}/{qc}]  stem={stem}")
        for day, drows in sorted(by_day.items()):
            out = os.path.join(base, day, neg, qc, f"{day}_{stem}.dat")
            exists = os.path.exists(out)
            print(f"   →  {os.path.relpath(out, base)}  ({len(drows)} rows)"
                  + ("  [기존→_archive]" if exists else ""))
            if apply:
                if archive_existing(out, base):
                    n_arch += 1
                os.makedirs(os.path.dirname(out), exist_ok=True)
                write_result(out, comments, colhdr, drows, note=f"migrated from {rel}")
            elif exists:
                n_arch += 1
            n_split += 1
        _move(fp, os.path.join(base, '_archive', 'legacy', rel), apply)
        n_moved += 1

    for fp in sorted(set(other_files)):
        rel = os.path.relpath(fp, base)
        _move(fp, os.path.join(base, '_derived', 'legacy', rel), apply)
        n_moved += 1

    for d in stray_dirs:
        rel = os.path.relpath(d, base)
        _move(d, os.path.join(base, '_archive', 'legacy', rel), apply)

    if apply:   # 비워진 레거시 범위 폴더 정리(빈 폴더만 — 내용물은 위에서 전부 이동됨)
        for name in sorted(os.listdir(base)):
            top = os.path.join(base, name)
            if os.path.isdir(top) and DATE_DIR.match(name) and '-' in name:
                for dirpath, _dirs, _files in os.walk(top, topdown=False):
                    if not os.listdir(dirpath):   # walk 스냅샷 말고 실시간 확인(자식 rmdir 반영)
                        os.rmdir(dirpath)

    mode = 'APPLIED' if apply else 'DRY-RUN (실행하려면 --apply)'
    print(f"\n{mode}: 일별파일 {n_split}개 생성, 원본/기타 {n_moved}개 이동, "
          f"기존버전 {n_arch}개 _archive, 파싱불가 {n_err}개, 통째이동 폴더 {len(stray_dirs)}개")


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('base', help='fitting 출력 최상위 폴더 (예: C:/Doasis_Work/Output/fitting)')
    ap.add_argument('--apply', action='store_true', help='실제 이동/쓰기 실행(기본은 dry-run)')
    a = ap.parse_args()
    migrate(a.base, a.apply)
