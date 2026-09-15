"""QDOAS(외부 독립 DOAS 구현) vs Augur(VarPro) 비교 스크립트.

배경: build_qdoas_spectrum.py가 만든 가상 스펙트럼 I=exp(-K*alpha)를 QDOAS로 피팅하면
QDOAS가 내놓는 SCD(=NO2.SlCol(...))는 (raw cross-section 기준이라) Augur가 내부적으로
쓰는 "raw_conc"(피크정규화 기저의 계수를 mult/scale_div로 물리단위 cm⁻³로 되돌린 값,
core/fit_physics.retrieved_amount / gui/worker.py 확인)와 같은 물리량이다:
    real_conc_augur[gas] == SCD_qdoas[gas] / K   (cm⁻³, 이론상 정확히 성립)

★ 2026-09-07 핵심 정정: merge*.dat의 CHOCHO/H2O/NO2 컬럼은 alpha도 real_conc(cm⁻³)도
아니라 **ppb 혼합비**다 (gui/worker.py: ppb = real_conc/n_air*1e9, n_air는 이상기체
식으로 스캔별 T,P에서 계산). 그래서 앞선(2026-09-07 오전) "K로만 나누면 되는 줄 알았던"
비교는 raw SCD를 ppb와 그대로 비교해 ~14자리 스케일이 어긋난 것처럼 보였다 -- 실제로는
스케일이 안 맞는 게 아니라 **물리량 자체가 다른(SCD/n_air-변환 전 vs 후) 것을 비교**한
것. Augur merge 파일에는 스캔별 T/P가 없어(헤더의 gas_temp=0.0°C는 T_ref 표시일 뿐,
실측 T/P 로그가 아님) 정확한 역변환은 불가능하지만, 명목 T=25°C(=FitSet의 t_ref),
P=1013.25mbar로 가정한 n_air(≈2.4625e19 cm⁻³)를 쓰면
    real_conc_augur_approx[gas] = ppb_augur[gas] * n_air_nominal / 1e9
이 SCD_qdoas/K와 상관계수뿐 아니라 **절대 스케일(회귀기울기)까지** 잘 맞는 것을
경험적으로 확인함 (기울기 실측 1.7e10~3.0e10 vs 예측 n_air/1e9=2.46e10, 같은 자릿수
+ 물리적으로 타당한 범위 -- 스캔별 실제 T/P가 명목값 근방에서 흔들리는 정도의 잔차만
남을 것으로 예상). 이 스크립트는 두 가지 절대-스케일 지표를 함께 출력한다:
  (a) "n_air 예측" 방식: ppb_augur*n_air_nominal/1e9 를 SCD_qdoas/K와 직접 비교
      (slope가 1.0 근방이면 물리적 환산이 정확히 성립한다는 뜻)
  (b) "경험적 회귀" 방식(기존): av(ppb 그대로) vs qv=SCD/K 를 그냥 선형회귀
      (slope 자체는 의미 없지만 상관계수 r은 배율에 불변이라 여전히 유효한 지표)

Shift/Squeeze 세팅 caveat (FitSet_ANs430462nm_P4_PNs444471nm_P3_cold438476nm_P4_Std.json,
2026-09-07 확인 -- merge 헤더의 "Sh[-0.5], Sq[0.0]"는 core/result_io.merge_results()가
files[0](=cold)의 주석만 남기고 나머지 파일 주석을 버리는 버그라 ANs/PNs에도 잘못
찍힌 것일 뿐, 실제 세팅은 채널마다 다르다):
  - cold  : NO2 Shift Fix(-0.5), Squeeze Fix(0.0)             -- 완전 고정
  - ANs   : NO2 Shift Limit(-10, 0.5) px, Squeeze Limit(±0.005) -- 자유
  - PNs   : NO2 Shift Limit(-5, 5) px,   Squeeze Limit(±0.005) -- 자유
(CHOCHO/H2O는 3채널 모두 NO2에 Link) 이번 QDOAS 세팅은 Shift를 Nonlinear로 자유롭게
피팅했으므로, cold는 "고정 vs 자유"가 갈리지만 ANs/PNs는 오히려 둘 다 자유-- 다만
QDOAS 쪽 bounds(±2px 상당)가 Augur의 실제 bounds(비대칭, -10~+0.5 / -5~+5)와는 다르므로
완전한 apples-to-apples는 아님. 논문 §7/§10에 채널별로 정확히 명시할 것.

절차:
  1) QDOAS Output(ASC/HTML, 탭구분, 헤더 2줄) 을 읽어 SCD/K = alpha_qdoas(=real_conc 상당)로,
  2) Augur의 실제 VarPro 프로덕션 피팅 결과(merge*.dat, "# 주석" 헤더 + 탭구분 표, ppb 컬럼)를
     읽어 ppb -> real_conc_approx(명목 n_air) 로 변환한 뒤,
  3) 두 결과를 스캔 시각(YYYYMMDDHHMMSS, 초 단위)으로 매칭해 상관계수/회귀기울기/절대스케일
     일치도를 계산한다.

사용:
  python compare_qdoas_augur.py
  (하단 CHANNELS 리스트의 경로/K값을 환경에 맞게 수정)
"""
import os

# 경로는 **이 폴더 기준**이다. (2026-09-15) 원래는 이전 세션 샌드박스의 절대경로
# (/mnt/user-data/..., /root/.claude/uploads/...)가 박혀 있어 다른 PC에서는 임포트조차
# 터졌다 — 논문 대조표를 만든 코드가 남이 돌릴 수 없으면 재현성이 아니다.
# 입력 원자료(QDOAS 출력 .ASC/.html, Augur merge*.dat)는 비공개라 저장소에 없다;
# 무엇을 어디에 두면 되는지는 같은 폴더 README.md의 "재현 방법" 절 참조.
HERE = os.path.dirname(os.path.abspath(__file__))


def _p(rel):
    return os.path.join(HERE, rel)

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

GASES = ['CHOCHO', 'H2O', 'NO2']

# 명목(nominal) 대기 조건 -- 실제 스캔별 T/P가 merge 파일에 없어 근사로만 씀.
# T_ref=25°C, P=1013.25mbar (FitSet의 t_ref=25.0과 표준 기압 가정).
# n_air = 2.68678e19 * (P/1013.25) * (273.15/(T+273.15))  [cm^-3].
# (원 주석은 'core/worker.py와 동일 공식'이었으나, worker.py가 단일 출처로 옮겨가 더는 아니다.)
T_NOMINAL_C = 25.0
P_NOMINAL_MBAR = 1013.25
N_AIR_NOMINAL = 2.68678e19 * (P_NOMINAL_MBAR / 1013.25) * (273.15 / (T_NOMINAL_C + 273.15))
# ⚠ (2026-09-14) 위 리터럴은 2026-09-08 실행 당시의 값 그대로다 — 산출물(csv/png)과
#   짝이므로 **재현성을 위해 바꾸지 않는다**. 현재 Augur는 core.physics.N_LOSCHMIDT
#   (SI 정의 유도값 = CODATA 2018, 2.686780111e19)로 통일됐다. 차이는 상대 4.2e-8 —
#   이 대조의 결론에 영향 없음. **새 코드는 core.physics.air_number_density를 임포트할 것.**


def load_qdoas(path, K):
    """QDOAS ASCII 출력(# 주석 2줄 + 탭구분 표: Date&time, SpecNo, NO2.SlCol(GAS)x3, ...)."""
    df = pd.read_csv(path, sep='\t', skiprows=2, header=None, engine='python')
    df = df.dropna(axis=1, how='all')  # 줄 끝 탭으로 생기는 빈 컬럼 제거
    df = df.iloc[:, :8]
    df.columns = ['dt_raw', 'spec_no',
                  'CHOCHO_SlCol', 'CHOCHO_SlErr',
                  'H2O_SlCol', 'H2O_SlErr',
                  'NO2_SlCol', 'NO2_SlErr']
    df['dt'] = pd.to_datetime(df['dt_raw'].astype(str).str.strip(), format='%Y%m%d%H%M%S')
    for g in GASES:
        df[f'alpha_qdoas_{g}'] = pd.to_numeric(df[f'{g}_SlCol'], errors='coerce') / K
    return df


def load_augur(path):
    """Augur merge*.dat: '#' 주석 헤더 다수 + 탭구분 표(File/Channel/Time/.../CHOCHO/H2O/NO2/.../Status).

    CHOCHO/H2O/NO2 컬럼은 ppb(혼합비) -- gui/worker.py 확인. 스캔별 실제 T/P가 파일에
    없으므로 명목 n_air(N_AIR_NOMINAL, T=25°C/P=1013.25mbar 가정)로 근사 역변환해
    real_conc_approx[gas](cm^-3, QDOAS SCD/K와 같은 물리량)도 함께 만든다."""
    df = pd.read_csv(path, sep='\t', comment='#', engine='python')
    df['dt'] = pd.to_datetime(df['Time'])
    for g in GASES:
        ppb = pd.to_numeric(df[g], errors='coerce')
        df[f'ppb_augur_{g}'] = ppb
        df[f'realconc_augur_{g}'] = ppb * N_AIR_NOMINAL / 1e9
    return df


def compare_channel(name, qdoas_path, augur_path, K):
    print(f'\n{"="*70}\n{name}\n{"="*70}')
    q = load_qdoas(qdoas_path, K)
    a = load_augur(augur_path)
    print(f'  QDOAS 행수={len(q)}  Augur 행수={len(a)}  (K={K:.1e}, n_air_nominal={N_AIR_NOMINAL:.4e} cm^-3)')

    merged = pd.merge(q[['dt'] + [f'alpha_qdoas_{g}' for g in GASES]],
                       a[['dt', 'Status'] + [f'realconc_augur_{g}' for g in GASES] +
                         [f'ppb_augur_{g}' for g in GASES]],
                       on='dt', how='inner')
    print(f'  타임스탬프(초단위) 매칭: {len(merged)}건 '
          f'(QDOAS의 {100*len(merged)/max(len(q),1):.1f}%, Augur의 {100*len(merged)/max(len(a),1):.1f}%)')

    results = []
    for qc_label, sub in [('전체(QC 무관)', merged), ('Augur Status==OK만', merged[merged['Status'] == 'OK'])]:
        for g in GASES:
            qv = sub[f'alpha_qdoas_{g}'].to_numpy()          # = SCD_qdoas/K, 이론상 real_conc(cm^-3)와 동일
            av = sub[f'realconc_augur_{g}'].to_numpy()        # = ppb_augur * n_air_nominal/1e9 (cm^-3 근사)
            mask = np.isfinite(qv) & np.isfinite(av)
            qv, av = qv[mask], av[mask]
            if len(qv) < 2:
                continue
            r = np.corrcoef(qv, av)[0, 1]
            # (a) n_air 물리 예측: slope가 1.0에 가까우면 "ppb->cm^-3 명목환산 + K분리"만으로
            #     절대 스케일까지 맞는다는 뜻(스캔별 실제 T/P 흔들림만큼만 벗어나야 정상).
            slope_phys, intercept_phys = np.polyfit(av, qv, 1)
            resid = qv - (slope_phys * av + intercept_phys)
            rms_resid = np.sqrt(np.mean(resid ** 2))
            aug_std = np.std(av)
            results.append(dict(channel=name, qc=qc_label, gas=g, n=len(qv), r=r,
                                 slope_realconc_vs_scdK=slope_phys, intercept=intercept_phys,
                                 rms_resid_after_fit=rms_resid, augur_realconc_std=aug_std,
                                 rms_resid_over_std=rms_resid / aug_std if aug_std else np.nan))
            print(f'  [{qc_label:16s}] {g:6s} n={len(qv):6d}  r={r:+.4f}  '
                  f'slope(SCD/K ÷ realconc_approx)={slope_phys:.3f} (1.0=물리적으로 정확히 일치)  '
                  f'선형보정후 잔차rms/std={rms_resid/aug_std if aug_std else float("nan"):.3f}')

    # 산점도 (Status==OK 서브셋 기준). 이제 x/y 둘 다 같은 물리량(cm^-3, 명목 n_air 가정)이라
    # y=x 기준선이 의미를 가진다(회귀직선과 함께 표시).
    ok = merged[merged['Status'] == 'OK']
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for ax, g in zip(axes, GASES):
        qv = ok[f'alpha_qdoas_{g}'].to_numpy()          # SCD/K, cm^-3 상당
        av = ok[f'realconc_augur_{g}'].to_numpy()        # ppb*n_air_nominal/1e9, cm^-3 근사
        mask = np.isfinite(qv) & np.isfinite(av)
        qv, av = qv[mask], av[mask]
        ax.scatter(av, qv, s=3, alpha=0.3)
        slope, intercept = np.polyfit(av, qv, 1)
        xs = np.linspace(av.min(), av.max(), 50)
        ax.plot(xs, slope * xs + intercept, 'r--', lw=1.2,
                label=f'fit: y={slope:.2f}x+{intercept:.1e}')
        lo, hi = min(av.min(), qv.min()), max(av.max(), qv.max())
        ax.plot([lo, hi], [lo, hi], 'k:', lw=0.8, label='y=x (물리적 일치선)')
        ax.legend(fontsize=7)
        ax.set_xlabel(f'Augur real_conc≈ppb×n_air/1e9 ({g}) [cm⁻³]')
        ax.set_ylabel(f'QDOAS SCD/K ({g}) [cm⁻³ 상당]')
        ax.set_title(f'{name} - {g}  r={np.corrcoef(av,qv)[0,1]:.3f}')
    fig.tight_layout()
    out_png = _p(f'compare_{name}.png')
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    print(f'  산점도 저장 -> {out_png}')

    merged.to_csv(_p(f'compare_{name}_matched.csv'), index=False)
    return results


if __name__ == '__main__':
    CHANNELS = [
        dict(name='cold', K=1e6,
             qdoas_path=_p('qdoas_output/cold/Analysis_clean.html'),
             augur_path=_p('augur_fit/cold_merge.dat')),
        dict(name='hot_ans', K=1e7,
             qdoas_path=_p('qdoas_output/hot_ans/hot_ans.ASC'),
             augur_path=_p('augur_fit/ans_merge.dat')),
        dict(name='hot_pns', K=1e7,
             qdoas_path=_p('qdoas_output/hot_PNs/hot_PNs.ASC'),
             augur_path=_p('augur_fit/pns_merge.dat')),
        # 2026-09-07: Shift bound을 Augur 실제 production 값(ANs Limit(-10,0.5)px,
        # PNs Limit(-5,5)px)으로 재설정해 재실행한 버전 -- Hot ANs CHOCHO/H2O
        # r^2=0.53 미스터리의 결정적 검증.
        dict(name='hot_ans_boundfix', K=1e7,
             qdoas_path=_p('qdoas_output/hot_ans/hot_ans_boundfix.ASC'),
             augur_path=_p('augur_fit/ans_merge.dat')),
        dict(name='hot_pns_boundfix', K=1e7,
             qdoas_path=_p('qdoas_output/hot_PNs/hot_PNs_boundfix.ASC'),
             augur_path=_p('augur_fit/pns_merge.dat')),
    ]
    all_results = []
    for ch in CHANNELS:
        all_results += compare_channel(ch['name'], ch['qdoas_path'], ch['augur_path'], ch['K'])

    summary = pd.DataFrame(all_results)
    summary.to_csv(_p('compare_summary.csv'), index=False)
    print(f'\n전체 요약표 -> {_p("compare_summary.csv")}')
