"""hot_ans_negshift.ASC (미러링 bound: Sh min=-0.024nm, Sh max=+0.483nm) vs Augur 비교.

compare_qdoas_augur.py와 동일한 방법론(K=1e7, 명목 n_air 역변환)을 그대로 적용하되,
이 파일은 Sh/St/Err store가 켜진 상태로 재실행된 것이라 컬럼 레이아웃이 다름
(hot_ans_errfactor.ASC와 동일한 확장 레이아웃).
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
K = 1e7
T_NOMINAL_C = 25.0
P_NOMINAL_MBAR = 1013.25
N_AIR_NOMINAL = 2.68678e19 * (P_NOMINAL_MBAR / 1013.25) * (273.15 / (T_NOMINAL_C + 273.15))
# ⚠ (2026-09-14) 위 리터럴은 2026-09-08 실행 당시의 값 그대로다 — 산출물(csv/png)과
#   짝이므로 **재현성을 위해 바꾸지 않는다**. 현재 Augur는 core.physics.N_LOSCHMIDT
#   (SI 정의 유도값 = CODATA 2018, 2.686780111e19)로 통일됐다. 차이는 상대 4.2e-8 —
#   이 대조의 결론에 영향 없음. **새 코드는 core.physics.air_number_density를 임포트할 것.**

QDOAS_PATH = _p("qdoas_output/hot_ans/hot_ans_negshift.ASC")
AUGUR_PATH = _p("augur_fit/ans_merge.dat")

# 이전(부호 반전 전) boundfix 비교 대상 (참조용)
BOUNDFIX_ORIG = _p("qdoas_output/hot_ans/hot_ans_boundfix.ASC")


def load_qdoas_negshift(path):
    df = pd.read_csv(path, sep='\t', skiprows=2, header=None, engine='python')
    df = df.dropna(axis=1, how='all')
    df.columns = ['dt_raw', 'spec_no', 'Chi', 'RMS', 'Ref2Ref1Shift',
                  'CHOCHO_SlCol', 'CHOCHO_SlErr', 'Shift_CHOCHO', 'ErrShift',
                  'Stretch1', 'Stretch2', 'ErrStretch1', 'ErrStretch2',
                  'H2O_SlCol', 'H2O_SlErr', 'NO2_SlCol', 'NO2_SlErr']
    df['dt'] = pd.to_datetime(df['dt_raw'].astype(str).str.strip(), format='%Y%m%d%H%M%S')
    for g in GASES:
        df[f'alpha_qdoas_{g}'] = pd.to_numeric(df[f'{g}_SlCol'], errors='coerce') / K
    df['Shift_CHOCHO'] = pd.to_numeric(df['Shift_CHOCHO'], errors='coerce')
    df['RMS'] = pd.to_numeric(df['RMS'], errors='coerce')
    return df


def load_augur(path):
    df = pd.read_csv(path, sep='\t', comment='#', engine='python')
    df['dt'] = pd.to_datetime(df['Time'])
    for g in GASES:
        ppb = pd.to_numeric(df[g], errors='coerce')
        df[f'ppb_augur_{g}'] = ppb
        df[f'realconc_augur_{g}'] = ppb * N_AIR_NOMINAL / 1e9
    return df


q = load_qdoas_negshift(QDOAS_PATH)
a = load_augur(AUGUR_PATH)
print(f'QDOAS(negshift) 행수={len(q)}  Augur 행수={len(a)}')

merged = pd.merge(
    q[['dt', 'Shift_CHOCHO', 'RMS'] + [f'alpha_qdoas_{g}' for g in GASES]],
    a[['dt', 'Status'] + [f'realconc_augur_{g}' for g in GASES] + [f'ppb_augur_{g}' for g in GASES]],
    on='dt', how='inner')
print(f'타임스탬프 매칭: {len(merged)}건 ({100*len(merged)/len(q):.1f}% of QDOAS, {100*len(merged)/len(a):.1f}% of Augur)')

results = []
for qc_label, sub in [('전체(QC 무관)', merged), ('Augur Status==OK만', merged[merged['Status'] == 'OK'])]:
    for g in GASES:
        qv = sub[f'alpha_qdoas_{g}'].to_numpy()
        av = sub[f'realconc_augur_{g}'].to_numpy()
        mask = np.isfinite(qv) & np.isfinite(av)
        qv, av = qv[mask], av[mask]
        r = np.corrcoef(qv, av)[0, 1]
        slope, intercept = np.polyfit(av, qv, 1)
        resid = qv - (slope * av + intercept)
        rms_resid = np.sqrt(np.mean(resid ** 2))
        aug_std = np.std(av)
        results.append(dict(channel='hot_ans_negshift', qc=qc_label, gas=g, n=len(qv), r=r, r2=r**2,
                             slope=slope, intercept=intercept,
                             rms_resid_over_std=rms_resid / aug_std if aug_std else np.nan))
        print(f'  [{qc_label:16s}] {g:6s} n={len(qv):6d}  r={r:+.4f}  r2={r**2:.4f}  slope={slope:.3f}')

ok = merged[merged['Status'] == 'OK']
sh = ok['Shift_CHOCHO'].dropna().to_numpy()
lo, hi = -0.024, 0.483
tol = 0.005
print(f'\nShift(nm) 통계 (Status==OK, n={len(sh)}): min={sh.min():.4f} max={sh.max():.4f} '
      f'mean={sh.mean():.4f} std={sh.std():.4f}')
print(f'하한({lo}) pin 비율: {np.mean(np.abs(sh-lo)<tol)*100:.2f}%   '
      f'상한({hi}) pin 비율: {np.mean(np.abs(sh-hi)<tol)*100:.2f}%')

# 산점도
fig, axes = plt.subplots(1, 3, figsize=(15, 5))
for ax, g in zip(axes, GASES):
    qv = ok[f'alpha_qdoas_{g}'].to_numpy()
    av = ok[f'realconc_augur_{g}'].to_numpy()
    mask = np.isfinite(qv) & np.isfinite(av)
    qv, av = qv[mask], av[mask]
    ax.scatter(av, qv, s=3, alpha=0.3)
    slope, intercept = np.polyfit(av, qv, 1)
    xs = np.linspace(av.min(), av.max(), 50)
    ax.plot(xs, slope * xs + intercept, 'r--', lw=1.2, label=f'fit: y={slope:.2f}x+{intercept:.1e}')
    lo2, hi2 = min(av.min(), qv.min()), max(av.max(), qv.max())
    ax.plot([lo2, hi2], [lo2, hi2], 'k:', lw=0.8, label='y=x')
    ax.legend(fontsize=7)
    ax.set_xlabel(f'Augur real_conc≈ppb×n_air/1e9 ({g}) [cm⁻³]')
    ax.set_ylabel(f'QDOAS SCD/K ({g}) [cm⁻³ 상당]')
    ax.set_title(f'hot_ans_negshift(부호정정) - {g}  r={np.corrcoef(av,qv)[0,1]:.3f}')
fig.tight_layout()
out_png = _p('compare_hot_ans_negshift.png')
fig.savefig(out_png, dpi=110)
plt.close(fig)
print(f'산점도 저장 -> {out_png}')

pd.DataFrame(results).to_csv(_p('compare_hot_ans_negshift_summary.csv'), index=False)
merged.to_csv(_p('compare_hot_ans_negshift_matched.csv'), index=False)
print('저장 완료 -> compare_hot_ans_negshift_summary.csv / _matched.csv')

# 이전 비교표와 나란히
print('\n' + '='*70)
print('비교: Hot ANs CHOCHO/H2O r² 변천사')
print('='*70)
print(f'{"조건":30s} {"CHOCHO r2":>10s} {"H2O r2":>10s} {"NO2 r2":>10s}')
print(f'{"최초(±2px 대칭, 부호모름)":30s} {0.529:>10.3f} {0.532:>10.3f} {0.998:>10.3f}')
print(f'{"boundfix(Augur부호 그대로)":30s} {0.481:>10.3f} {0.325:>10.3f} {0.996:>10.3f}')
r2ok = {r['gas']: r['r2'] for r in results if r['qc'] == 'Augur Status==OK만'}
print(f'{"negshift(부호 반전+swap) NEW":30s} {r2ok["CHOCHO"]:>10.3f} {r2ok["H2O"]:>10.3f} {r2ok["NO2"]:>10.3f}')
