"""datetime_KST 를 +8h 축에서 **+9h 축**으로 옮기는 1회성 마이그레이션.

왜
--
계기 PC 시계가 UTC 라는 것이 2026-08-03 NIER 순천 상시측정과의 상호상관으로
확인됐다(52일 내내 최적 지연 61~64분, cold·hot 두 PC 독립, r 최대 0.99).
즉 KST = 기록시각 + 9 h 이고, 기존 산출물의 `datetime_KST` 는 정확히 1시간 이르다.
근거: memory `caesar-clock-plus9-nier-evidence-2026-08`.

무엇을
------
**시각 라벨만** 옮긴다. 농도 값은 한 글자도 건드리지 않는다.
1 h 는 5 min 의 정수배라 빈 경계가 그대로여서 재빈닝 없이 정확히 교정된다.

안전장치
--------
* 원본은 같은 폴더의 `_pre_plus9/` 로 **먼저 복사**한 뒤에만 덮어쓴다.
* 이미 `# Time_correction:` 마커가 있는 파일은 **건너뛴다**(두 번 밀림 방지).
* `--check` 로 무엇이 바뀔지 먼저 볼 수 있다(쓰기 없음).

사용
----
    python tools/migrate_kst_plus9.py --check
    python tools/migrate_kst_plus9.py
"""
from __future__ import annotations

import argparse
import os
import shutil

import pandas as pd

SHIFT_H = 1

FIG = r'C:\Doasis_Work\Output\figure'
TARGETS = [
    os.path.join(FIG, 'ANs', 'alt_ch2minusch1',
                 'GIST_CAESAR_ANs_5min_KST_20260518_20260710_ch2minusch1.csv'),
    os.path.join(FIG, 'ANs',
                 'GIST_CAESAR_ANs_5min_KST_20260518_20260710_ch1minusch2.csv'),
    os.path.join(FIG, 'cold_NO2',
                 'GIST_CAESAR_cold_NO2_5min_KST_20260517_20260617.csv'),
]

MARKER = '# Time_correction:'
NOTE = (f'{MARKER} +{SHIFT_H} h applied 2026-08-03 (tools/migrate_kst_plus9.py).\n'
        '#   The instrument PC clock runs on UTC, so KST = recorded + 9 h. Files written\n'
        '#   before this date used +8 h and were labelled one hour early.\n'
        '#   Concentrations are unchanged; only the timestamps moved.\n')


def _patch_header(lines: list[str], t: pd.Series) -> list[str]:
    out = []
    for l in lines:
        if 'recorded + 8 h' in l:
            l = l.replace('recorded + 8 h', 'recorded + 9 h')
        elif l.startswith('# Period:'):
            l = f'# Period: {t.min():%Y-%m-%d} ~ {t.max():%Y-%m-%d} (KST)'
        out.append(l)
    return out


def migrate(path: str, dry: bool) -> str:
    if not os.path.exists(path):
        return f'없음     {path}'
    with open(path, encoding='utf-8-sig') as f:
        lines = f.read().splitlines()
    if any(l.startswith(MARKER) for l in lines):
        return f'건너뜀   {os.path.basename(path)}  (이미 정정됨)'

    hdr = [l for l in lines if l.startswith('#')]
    df = pd.read_csv(path, comment='#')
    if 'datetime_KST' not in df.columns:
        return f'스킵     {os.path.basename(path)}  (datetime_KST 컬럼 없음)'

    t0 = pd.to_datetime(df['datetime_KST'])
    t1 = t0 + pd.Timedelta(hours=SHIFT_H)
    msg = (f'{os.path.basename(path)}\n'
           f'      {len(df):,} 행   {t0.min()} ~ {t0.max()}\n'
           f'          →           {t1.min()} ~ {t1.max()}')
    if dry:
        return '변경예정 ' + msg

    bak_dir = os.path.join(os.path.dirname(path), '_pre_plus9')
    os.makedirs(bak_dir, exist_ok=True)
    shutil.copy2(path, os.path.join(bak_dir, os.path.basename(path)))

    df['datetime_KST'] = t1.dt.strftime('%Y-%m-%d %H:%M:%S')
    hdr = _patch_header(hdr, t1)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write('\n'.join(hdr) + '\n' + NOTE)
        df.to_csv(f, index=False)
    return '완료     ' + msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='쓰지 않고 무엇이 바뀔지만 출력')
    a = ap.parse_args()
    print(f'datetime_KST  +{SHIFT_H} h 마이그레이션' + ('  [--check: 쓰기 없음]' if a.check else ''))
    for p in TARGETS:
        print('  ' + migrate(p, a.check))
    if not a.check:
        print('\n  원본은 각 폴더의 _pre_plus9/ 에 보존됨')


if __name__ == '__main__':
    main()
