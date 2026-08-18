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
import numpy as np
import pandas as pd

FIG = r'C:\Doasis_Work\Output\figure'
OUT = os.path.join(FIG, 'NIER_submit')
# 2026-08-12: R0 피벗 -- 8/11 인젝션(g=0.82) 폐기, AQMS(NIER 순천) 앵커 방식으로 대체
# (tools/build_hot_no2_correction.py 가 생성). 인젝션은 3조건(안정화시간/믹싱/리트리벌안정성)
# 재확인 후 차기 제출에 반영 예정 -- docs/NO2_인젝션_실험_핸드오프_2026-08.md 참고.
SRC_ANS = os.path.join(FIG, 'ANs', 'GIST_CAESAR_ANs_5min_KST_aqms_corrected_source.csv')
SRC_PNS = os.path.join(FIG, 'ANs', 'GIST_CAESAR_PNs_5min_KST_aqms_corrected_source.csv')
SRC_COLD_CSV = os.path.join(FIG, 'cold_NO2', 'GIST_CAESAR_cold_NO2_5min_KST_aqms_corrected_source.csv')

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

METHOD_NOTE = """\
# Method (R0, 2026-08-12): the 2026-08-11 NO2 cylinder injection (g=0.82) is NOT used in this
#   submission -- PI review found the injection's own QA (dilution stabilization time, mixing
#   adequacy, retrieval-timeseries plateau stability) unverified, so it cannot yet support a
#   government submission. Deferred to a future revision pending re-validation of those 3 items.
# Method (R0, 2026-08-12): cold NO2 is instead scale-calibrated against NIER Suncheon AQMS
#   (Teledyne NO2 monitor, co-located site): cold_corrected = cold_raw / 0.922 (pooled regression
#   slope, clean-period only; intercept NOT removed -- it reflects AQMS's molybdenum-converter
#   NO2+NOz bias, not a cold error, confirmed by chemical closure). This AQMS-anchored
#   cold_corrected (or AQMS directly where cold is unavailable -- their equivalence is verified,
#   post-correction slope=1.0000) then serves as the absolute reference for the hot channels: a
#   continuous 24h-moving-average ratio of each hot channel's raw NO2 retrieval to this reference
#   gives a smoothly time-varying scale-correction curve (no discrete campaign periods -- the
#   curve already captures the one confirmed real optical step, ~06-21 filter test, without
#   needing hard-coded boundaries). ANs = NO2(300 degC cell, corrected) - NO2(180 degC cell,
#   corrected); PNs = NO2(180 degC cell, corrected) - reference NO2.
"""

ANS_HDR = """\
# Institution: GIST
# PI: 이경환 (Lee, Kyung-Hwan)
# Contact: gh548080@gist.ac.kr
# Instrument: CAESAR (BBCEAS, thermal-dissociation dual hot cavity)
# Species: ANs (alkyl nitrates)
# Definition: NO2(300 degC cell, AQMS-scale-corrected) - NO2(180 degC cell, AQMS-scale-corrected).
#   See Method note below for the correction methodology (2026-08-12 pivot from NO2-injection g).
# Unit: ppb
# Time_zone: KST (UTC+9)
# Time_label: bin start (5-min average)
# Averaging: 5-minute mean
# Period: 2026-05-18 ~ 2026-07-10 (KST)
# QC: n_scans>=3 per 5-min bin required for QC_flag=OK.
# QC_flag: OK / few_scans (fewer than 3 scans in bin)
# Negative values retained (low-conc noise, not clipped).
# Uncertainty: ANs_unc_ppb = sqrt(unc_ch1^2 + unc_ch2^2), each unc_ch = 24h rolling std of the
#   raw (unsmoothed) hot/reference ratio around its smoothed value, x reference NO2 -- a rough
#   measure of how much the instantaneous scale-correction factor jitters, NOT a full error
#   propagation. Median ANs_unc_ppb (~0.58 ppb) exceeds the ANs signal's own IQR -- i.e. this
#   R0 ANs series is dominated by correction-curve uncertainty; treat as best-current-estimate,
#   not a closed-out quantitative time series.
""" + METHOD_NOTE + """\
# Columns: datetime_KST, ANs_ppb, ANs_unc_ppb, N_valid, QC_flag
# Generated: 2026-08-12 (R0, AQMS-anchored correction; supersedes 2026-08-11 g=0.82 version)
"""

PNS_HDR = """\
# Institution: GIST
# PI: 이경환 (Lee, Kyung-Hwan)
# Contact: gh548080@gist.ac.kr
# Instrument: CAESAR (BBCEAS, thermal-dissociation dual hot cavity)
# Species: PNs (peroxy nitrates)
# Definition: NO2(180 degC cell, AQMS-scale-corrected) - reference NO2 (AQMS-anchored cold NO2,
#   or AQMS directly where cold unavailable). See Method note below.
# Unit: ppb
# Time_zone: KST (UTC+9)
# Time_label: bin start (5-min average)
# Averaging: 5-minute mean
# Period: 2026-05-18 ~ 2026-07-10 (KST)
# QC: n_scans>=3 per 5-min bin required for QC_flag=OK.
# QC_flag: OK / few_scans (fewer than 3 scans in bin)
# Negative values retained (low-conc noise, not clipped).
# Uncertainty: PNs_unc_ppb = 24h rolling std of the raw (unsmoothed) ch2/reference ratio around
#   its smoothed value, x reference NO2 -- a rough jitter estimate, not a full error propagation.
""" + METHOD_NOTE + """\
# Columns: datetime_KST, PNs_ppb, PNs_unc_ppb, N_valid, QC_flag
# Generated: 2026-08-12 (R0, AQMS-anchored correction; new for this submission)
"""


def _build_species(src_csv, hdr, species, value_col):
    df = pd.read_csv(src_csv, comment='#')
    out = pd.DataFrame({
        'datetime_KST': _shift_kst(df['datetime_KST']),
        f'{species}_ppb': pd.to_numeric(df[value_col], errors='coerce').round(4),
        f'{species}_unc_ppb': pd.to_numeric(df['sys_unc_ppb'], errors='coerce').round(4),
        'N_valid': df['n_scans'],
        'QC_flag': df['QC_flag'],
    })
    out_hdr = '\n'.join(_period_line(out.datetime_KST) if l.startswith('# Period:') else l
                        for l in hdr.splitlines()) + '\n' + TIME_FIX_NOTE
    p = os.path.join(OUT, _stem(species, out.datetime_KST) + '.csv')
    with open(p, 'w', encoding='utf-8-sig', newline='') as f:   # BOM: Excel 한글 호환
        f.write(out_hdr)
        out.to_csv(f, index=False)
    col = f'{species}_ppb'
    print(f'  {species}  : {len(out):,} bins  median {out[col].median():+.4f} ppb  -> {os.path.basename(p)}')
    return out


def build_ans():
    return _build_species(SRC_ANS, ANS_HDR, 'ANs', 'ANs_ppb')


def build_pns():
    return _build_species(SRC_PNS, PNS_HDR, 'PNs', 'PNs_ppb')


UNPHYS_THR = -10.0        # ppb. 이보다 낮은 NO2 는 물리적으로 불가능

# 값을 NaN 처리할 구간 (2026-08-06, 지도교수 지시: 콜드는 이 캠페인의 주 타깃이 아니라
# ANs 의 지원 채널이라, 원칙(지우지 말고 flag)의 예외로 이상구간은 값을 비우고 제출한다.
# 내부 진단본(figure/cold_NO2/*.csv)은 원본값을 그대로 보존 — 여기 제출본만 비운다.
NAN_WINDOWS = [
    # (start_KST, end_KST, QC_flag 라벨, 사유)
    # 2026-08-12: NIER 순천 Teledyne NO2 실측(AQMSdata/2026_Yeosu_AQMS_teledyne_NOx.xlsx)과
    # 직접 대조해 일별/구간별 회귀 기울기·r로 재확정. 원래 5/20~5/28 12:00을 통으로 뺐었는데,
    # 5/24~27 18:00은 기울기 0.94~1.0·r 0.68~0.99로 멀쩡해서 복원함(아래 표는 세션 로그 참고).
    ('2026-05-20 00:00:00', '2026-05-24 00:00:00', 'excluded_low_sensitivity',
     'NIER 순천 대비 회귀기울기 0.06~0.41 (실측 확인, 정상 1.0 대비)'),
    ('2026-05-27 18:00:00', '2026-05-28 12:00:00', 'excluded_instrument_glitch',
     'NIER 순천 대비 회귀기울기가 18:00 기점 0.94→0.01로 급락, r도 0.84→0.00 (실측 확인)'),
    ('2026-06-05 00:00:00', '2026-06-05 23:59:59', 'excluded_R_artifact',
     'R(거울반사율)이 하루 종일 평시 1.4배로 튀어 NO2가 약 +67% 과대'),
    # 2026-08-12: 필드로그 "0602.008~ 로우파일 NO2 인젝션" 대조로 발견 -- raw 파일번호
    # 007->012로 건너뜀, 정확히 이 시간대 N_valid가 5->1로 급락(실측 확인). 앰비언트 아님.
    ('2026-06-02 16:10:00', '2026-06-02 16:55:00', 'excluded_injection_test',
     '필드로그 기록 raw파일 NO2 인젝션 테스트, N_valid 5->1 급락으로 실측 확인'),
]


COLD_HDR = """\
# Institution: GIST
# PI: 이경환 (Lee, Kyung-Hwan)
# Contact: gh548080@gist.ac.kr
# Instrument: CAESAR (BBCEAS, cold cavity)
# Species: NO2
# Definition: NO2_raw / 0.922 (AQMS scale correction, see Method note below). Intercept of the
#   underlying regression is NOT applied -- it reflects AQMS's own molybdenum-converter NO2+NOz
#   bias, not a cold measurement error (confirmed by chemical closure: expected intercept < 0
#   sized like -NOz, observed -1.03 ppb, consistent).
# Unit: ppb
# Time_zone: KST (UTC+9)
# Time_label: bin start (5-min average)
# Averaging: 5-minute mean
# Period: 2026-05-17 ~ 2026-06-18 (KST)
# QC: Chi2<10 (fit quality, applied upstream). Status flag NOT used (removes low-SNR good fits).
""" + METHOD_NOTE + """\
# Columns: datetime_KST, NO2_ppb, NO2_stdev_ppb, N_valid, QC_flag
# Generated: 2026-08-12 (R0, AQMS-anchored /0.922 scale correction; supersedes uncorrected version)
"""


def build_cold():
    """cold NO2 를 옮기되, 이상 구간의 값은 NaN 처리하고 QC_flag 로 사유를 남긴다.

    2026-08-06 이전: 값은 안 지우고 QC_flag(unphysical 등)만 달았다.
    2026-08-06 이후: 지도교수 지시로 이상구간은 값 자체를 NaN 처리한다(콜드=지원채널,
    ANs 가 이 캠페인의 주 타깃이라 원칙의 예외로 적용). 행/시각은 유지 — 결측이 시간축에서
    구멍으로 바로 보이게. QC_flag 는 지우지 않고 사유를 그대로 남겨 무슨 값이 왜 빠졌는지
    항상 복원 가능하게 한다(값 자체는 내부 진단본 figure/cold_NO2/ 에 그대로 있다).

    2026-08-12: SRC_COLD_CSV가 이제 build_hot_no2_correction.py의 /0.922 보정 소스라 자체
    헤더 주석이 없다 -- COLD_HDR 템플릿에서 새로 만든다(ANS_HDR/PNS_HDR과 동일 패턴).
    """
    hdr = COLD_HDR.splitlines()
    df = pd.read_csv(SRC_COLD_CSV, comment='#')
    df['datetime_KST'] = _shift_kst(df['datetime_KST'])
    t = pd.to_datetime(df['datetime_KST'])

    v = pd.to_numeric(df.NO2_ppb, errors='coerce')
    unphys = v < UNPHYS_THR
    df.loc[unphys, 'QC_flag'] = 'unphysical'

    nan_mask = unphys | (df.QC_flag == 'low_quality')
    for start, end, label, _reason in NAN_WINDOWS:
        m = (t >= pd.Timestamp(start)) & (t <= pd.Timestamp(end))
        df.loc[m, 'QC_flag'] = label
        nan_mask |= m
    df.loc[nan_mask, ['NO2_ppb', 'NO2_stdev_ppb']] = np.nan

    win_lines = '\n'.join(f'#   {lab}: {start[:10]} ~ {end[:10]} — {reason}'
                          for start, end, lab, reason in NAN_WINDOWS)
    hdr = [('# QC_flag: OK / low_quality (2026-06-17: cloudy/low-light, elevated RMS)'
            f' / unphysical (NO2 < {UNPHYS_THR:.0f} ppb; fit converged but value'
            ' physically impossible, mostly N_valid<=3 or stdev > |value|)'
            ' / excluded_low_sensitivity / excluded_instrument_glitch / excluded_R_artifact'
            ' / excluded_injection_test'
            ' (NO2_ppb set to NaN for all excluded_* categories; PI decision 2026-08-06 — cold'
            ' is a support channel for this campaign, ANs is the primary target)\n' + win_lines)
           if l.startswith('# QC_flag:') else l for l in hdr]
    hdr = [_period_line(df.datetime_KST) if l.startswith('# Period:') else l for l in hdr]

    p = os.path.join(OUT, _stem('cold_NO2', df.datetime_KST) + '.csv')
    with open(p, 'w', encoding='utf-8-sig', newline='') as f:
        f.write('\n'.join(hdr) + '\n' + TIME_FIX_NOTE)
        df.to_csv(f, index=False)
    print(f'  cold : {len(df):,} bins  median(NaN 처리 후) {df.NO2_ppb.median():+.4f} ppb'
          f'   NaN 처리 {int(nan_mask.sum())}개 ({100*nan_mask.mean():.2f}%)'
          f'   [unphysical {int(unphys.sum())}, {", ".join(f"{lab} {int((df.QC_flag==lab).sum())}" for _,_,lab,_ in NAN_WINDOWS)}]')


def main():
    os.makedirs(OUT, exist_ok=True)
    print('NIER 제출 세트 생성')
    build_ans()
    build_pns()
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
