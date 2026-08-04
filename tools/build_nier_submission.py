"""NIER 제출 세트 생성 — cold NO2 + ANs 를 동일 헤더 규격으로.

NIER 공유 규격(2026-07-23 회의록):
  5분 평균 / 파일명 언더바(빈칸 금지) / KST(bin start) / 헤더에 PI+측정정보 / 음수 유지
  ※ NIER 엑셀 양식 배포 예정 → 오면 컬럼 매핑만 하면 됨.

컬럼은 두 화학종을 동일 구조로 맞춘다(사용자 결정 2026-08-02):
  datetime_KST, <species>_ppb, <불확도>, N_valid, QC_flag
진단 컬럼(양채널 NO2, epoch, raw)은 제출본에서 뺀다 — 내부용은 Output/figure/ANs/ 에 그대로 있음.
"""
from __future__ import annotations
import os, shutil
import pandas as pd

FIG = r'C:\Doasis_Work\Output\figure'
OUT = os.path.join(FIG, 'NIER_submit')
SRC_ANS = os.path.join(FIG, 'ANs', 'GIST_CAESAR_ANs_5min_KST_20260518_20260710_ch1minusch2.csv')
SRC_COLD_CSV = os.path.join(FIG, 'cold_NO2', 'GIST_CAESAR_cold_NO2_5min_KST_20260517_20260617.csv')

# ── 시계 정정 (2026-08-03) ────────────────────────────────────────────────
# 원본 CSV 의 datetime_KST 는 `기록시각 + 8 h` 로 만들어졌다. 그런데 NIER 순천
# 상시측정과의 상호상관에서 계기 PC 시계가 **UTC** 임이 확인됐다(52일 내내 최적
# 지연 61~64분, cold·hot 두 PC 독립, r 최대 0.99). 즉 KST = 기록 + 9 h 이고
# 기존 라벨은 **정확히 1시간 이르다**.
#
# 값은 건드리지 않는다 — 틀린 것은 시각 라벨뿐이다. 1 h 는 5 min 의 정수배라
# 빈 경계가 그대로여서 라벨만 더하는 것으로 정확히 교정된다(재빈닝 불필요).
# ✅ 2026-08-03: 원본 CSV(`figure/ANs/`, `figure/cold_NO2/`)는
#    `tools/migrate_kst_plus9.py` 로 이미 +9 h 축으로 옮겼다 → 여기서 더 밀 것이 없다.
#    (+8 h 축의 옛 원본을 넣을 때만 1 로 올린다.)
TIME_FIX_H = 0


def _shift_kst(s: pd.Series) -> pd.Series:
    """datetime_KST 문자열 컬럼을 TIME_FIX_H 만큼 밀어 같은 포맷으로 되돌린다."""
    t = pd.to_datetime(s) + pd.Timedelta(hours=TIME_FIX_H)
    return t.dt.strftime('%Y-%m-%d %H:%M:%S')


def _period_line(s: pd.Series) -> str:
    t = pd.to_datetime(s)
    return f'# Period: {t.min():%Y-%m-%d} ~ {t.max():%Y-%m-%d} (KST)'


def _stem(species: str, s: pd.Series) -> str:
    """파일명의 기간을 실제 자료 범위에서 만든다(하드코딩 금지 — 시프트로 바뀐다)."""
    t = pd.to_datetime(s)
    return f'GIST_CAESAR_{species}_5min_KST_{t.min():%Y%m%d}_{t.max():%Y%m%d}'


TIME_FIX_NOTE = (
    '# Time_correction: +1 h applied 2026-08-03. The instrument PC clock runs on UTC,\n'
    '#   so KST = recorded + 9 h. Earlier files used +8 h and were therefore labelled\n'
    '#   one hour early. Concentrations are unchanged; only the timestamps moved.\n'
)

ANS_HDR = """\
# Institution: GIST
# PI: 이경환 (Lee, Kyung-Hwan)
# Contact: gh548080@gist.ac.kr
# Instrument: CAESAR (BBCEAS, thermal-dissociation dual hot cavity)
# Species: ANs (alkyl nitrates)
# Definition: NO2(300 degC cell) - g x NO2(180 degC cell)
#   g = inter-channel gain, determined per optical epoch by Theil-Sen regression.
#   Epochs bounded by instrument events: 2026-06-05 filter refit, 06-14 LED2 adjust, 06-23.
# Unit: ppb
# Time_zone: KST (UTC+9)
# Time_label: bin start (5-min average)
# Averaging: 5-minute mean
# Period: 2026-05-18 ~ 2026-07-10 (KST)
# QC: Chi2<10 both channels. Status flag NOT used (it removes low-SNR good fits & biases high).
# QC_flag: OK / low_light (cloudy, reduced signal) / few_scans (fewer than 3 scans in bin)
# Negative values retained (low-conc noise, not clipped).
# Uncertainty: ANs_unc_ppb = 1-sigma systematic from inter-channel gain variability,
#   day-to-day component only (0.04 x NO2).
#   *** This is NOT the full systematic budget. *** Channel gain also varies with time of day
#   and with NO2 level; including those, the total is ~0.30 ppb at typical NO2 - about 4x the
#   tabulated value, and larger than the reported ANs itself.
#   => Do NOT use this column alone to assess detection significance.
#   Random within-bin scatter (~0.019 ppb at 5 min) is small against either and is not tabulated.
# CAUTION: the retrieved signal lies within the inter-channel calibration uncertainty.
#   Report as an UPPER LIMIT (ANs < ~0.1-0.2 ppb), NOT as a quantitative time series.
#   Absolute quantification requires NO2 cylinder injection on a common inlet.
# Columns: datetime_KST, ANs_ppb, ANs_unc_ppb, N_valid, QC_flag
# Generated: 2026-08-02
"""


def build_ans():
    df = pd.read_csv(SRC_ANS, comment='#')
    out = pd.DataFrame({
        'datetime_KST': _shift_kst(df['datetime_KST']),
        'ANs_ppb': pd.to_numeric(df['ANs_ppb'], errors='coerce').round(4),
        'ANs_unc_ppb': pd.to_numeric(df['sys_unc_ppb'], errors='coerce').round(4),
        'N_valid': df['n_scans'],
        'QC_flag': df['QC_flag'],
    })
    hdr = '\n'.join(_period_line(out.datetime_KST) if l.startswith('# Period:') else l
                    for l in ANS_HDR.splitlines()) + '\n' + TIME_FIX_NOTE
    p = os.path.join(OUT, _stem('ANs', out.datetime_KST) + '.csv')
    with open(p, 'w', encoding='utf-8-sig', newline='') as f:   # BOM: Excel 한글 호환
        f.write(hdr)
        out.to_csv(f, index=False)
    print(f'  ANs  : {len(out):,} bins  median {out.ANs_ppb.median():+.4f} ppb  -> {os.path.basename(p)}')
    return out


UNPHYS_THR = -10.0        # ppb. 이보다 낮은 NO2 는 물리적으로 불가능


def build_cold():
    """cold NO2 를 원본 그대로 옮기되, 물리적으로 불가능한 값에 QC_flag 를 단다.

    값은 지우지 않는다 — 마지막 컬럼 QC_flag 만 OK -> unphysical 로 바꾼다.
    이 27개(0.33%)는 Chi2<10 을 통과했는데도 NO2 가 -226 ppb 까지 내려간다.
    대부분 N_valid<=3 이거나 stdev 가 |값| 보다 크다(저광량·단일스캔).
    그래프엔 영향이 없지만(이미 y축 밖) CSV 로 평균/표준편차를 내면
    표준편차가 21% 부풀려진다. 받는 쪽이 QC_flag 로 거를 수 있게 표시만 한다.
    """
    with open(SRC_COLD_CSV, encoding='utf-8-sig') as f:
        lines = f.read().splitlines()
    hdr = [l for l in lines if l.startswith('#')]
    df = pd.read_csv(SRC_COLD_CSV, comment='#')
    df['datetime_KST'] = _shift_kst(df['datetime_KST'])
    v = pd.to_numeric(df.NO2_ppb, errors='coerce')
    bad = v < UNPHYS_THR
    df.loc[bad, 'QC_flag'] = 'unphysical'

    hdr = [('# QC_flag: OK / low_quality (2026-06-17: cloudy/low-light, elevated RMS)'
            f' / unphysical (NO2 < {UNPHYS_THR:.0f} ppb;'
            ' fit converged but value physically impossible,'
            ' mostly N_valid<=3 or stdev > |value|)')
           if l.startswith('# QC_flag:') else l for l in hdr]
    hdr = [_period_line(df.datetime_KST) if l.startswith('# Period:') else l for l in hdr]

    p = os.path.join(OUT, _stem('cold_NO2', df.datetime_KST) + '.csv')
    with open(p, 'w', encoding='utf-8-sig', newline='') as f:
        f.write('\n'.join(hdr) + '\n' + TIME_FIX_NOTE)
        df.to_csv(f, index=False)
    print(f'  cold : {len(df):,} bins  median {v.median():+.4f} ppb'
          f'   unphysical 표시 {int(bad.sum())}개 ({100*bad.mean():.2f}%, 값은 보존)')


def main():
    os.makedirs(OUT, exist_ok=True)
    print('NIER 제출 세트 생성')
    build_ans()
    build_cold()

    # 그림은 plot_nier_figs 가 단독 소유한다. 예전엔 여기서 내부 그림을 PNG 로 복사했는데,
    # 그게 방금 만든 제출용 PNG 를 덮어써서 PNG 와 PDF 가 서로 다른 버전이 되는 버그가 있었다.
    # CSV 를 먼저 쓰고 곧바로 그림을 다시 그리므로 둘은 항상 같은 자료에서 나온다.
    import plot_nier_figs
    plot_nier_figs.main()

    # 규격 자체점검
    print('\n규격 점검')
    ok = True
    for fn in sorted(os.listdir(OUT)):
        if ' ' in fn:
            print(f'  [FAIL] 파일명에 빈칸: {fn}'); ok = False
    for fn in sorted(os.listdir(OUT)):
        if not fn.endswith('.csv'):
            continue
        txt = open(os.path.join(OUT, fn), encoding='utf-8-sig').read()
        need = ['# Institution:', '# PI:', '# Contact:', '# Instrument:', '# Species:',
                '# Unit:', '# Time_zone:', '# Averaging:', '# Period:', '# QC:', '# Columns:']
        miss = [k for k in need if k not in txt]
        first = txt.split('\n')[len([l for l in txt.split('\n') if l.startswith('#')])]
        print(f'  {fn}')
        print(f'     헤더 필수항목 : {"전부 있음" if not miss else "누락 " + str(miss)}')
        print(f'     컬럼          : {first}')
        if miss:
            ok = False
    print('\n' + ('  => 규격 통과' if ok else '  => 확인 필요'))


if __name__ == '__main__':
    main()
