"""보정 원리 설명용 그림 — ch2 vs ch1 산점도에서 g'가 무엇인지 보인다."""
import numpy as np, pandas as pd
from scipy.stats import theilslopes
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'Malgun Gothic'      # 한글 라벨
plt.rcParams['axes.unicode_minus'] = False          # 한글폰트 마이너스 깨짐 방지

SRC = r'C:\Doasis_Work\Output\figure\ANs\alt_ch2minusch1\GIST_CAESAR_ANs_5min_KST_20260518_20260710_ch2minusch1.csv'
OUT = r'C:\Doasis_Work\Output\figure\ANs\correction_explained_ch1minusch2.png'
EP = [('A0', None, '2026-05-27 01:00'), ('A1', '2026-05-27 01:00', '2026-06-06 01:00'),
      ('B', '2026-06-06 01:00', '2026-06-14 01:00'), ('C1', '2026-06-14 01:00', '2026-06-23 01:00'),
      ('C2', '2026-06-23 01:00', None)]

df = pd.read_csv(SRC, comment='#'); df.index = pd.to_datetime(df['datetime_KST']); df = df.sort_index()
for c in ('NO2_PNs_cell', 'NO2_ANs_cell'):
    df[c] = pd.to_numeric(df[c], errors='coerce')
d = df.dropna(subset=['NO2_PNs_cell', 'NO2_ANs_cell']).copy()
d['ch1'] = d.NO2_PNs_cell; d['ch2'] = d.NO2_ANs_cell

rng = np.random.default_rng(0)
fits = {}
for name, a, b in EP:
    # 프로덕션(ans_flip_build.py)과 동일한 반열린 구간 [a, b) 로 잘라야 g'가 일치한다.
    # pandas 라벨 슬라이싱은 끝점 포함이라 그대로 쓰면 경계 1 bin이 달라진다.
    m = (d.index >= (pd.Timestamp(a) if a else d.index[0])) & \
        (d.index < (pd.Timestamp(b) if b else d.index[-1] + pd.Timedelta('1s')))
    s = d.loc[m]
    idx = rng.choice(len(s), min(4000, len(s)), replace=False)
    g, a0, *_ = theilslopes(s.ch1.to_numpy()[idx], s.ch2.to_numpy()[idx])
    fits[name] = (g, a0, s)

fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), layout='constrained')
fig.patch.set_facecolor('w')

# (a) 산점도 + 1:1 vs g' 선  (A1: 가장 심한 구간)
ax = axes[0]
g, a0, s = fits['A1']
ax.plot(s.ch2, s.ch1, '.', ms=2, color='0.65', alpha=0.4, rasterized=True)
x = np.linspace(0, 12, 50)
ax.plot(x, x, 'k--', lw=1.6, label="1:1  (두 채널이 맞다면)")
ax.plot(x, g * x + a0, '-', color='#d62728', lw=2.0,
        label=f"Theil-Sen  ch1 = {g:.3f}·ch2 {a0:+.3f}")
ax.annotate('', xy=(8, g * 8 + a0), xytext=(8, 8),
            arrowprops=dict(arrowstyle='<->', color='#1f77b4', lw=2))
ax.text(8.3, (8 + g * 8 + a0) / 2, f"이 벌어짐이\n이득 불일치\n(+{(g-1)*100:.0f}%)",
        fontsize=9, color='#1f77b4', va='center')
ax.set_xlabel('ch2  NO$_2$ [ppb]', fontsize=12)
ax.set_ylabel('ch1  NO$_2$ [ppb]', fontsize=12)
ax.set_xlim(0, 12); ax.set_ylim(0, 12)
ax.set_title('(a) epoch A1 — 두 채널은 서로 안 맞는다', fontsize=11, loc='left')
ax.legend(fontsize=9, loc='lower right')

# (b) g' 의 epoch 변화
ax = axes[1]
names = [n for n, _, _ in EP]
gs = [fits[n][0] for n in names]
ax.axhline(1.0, color='k', ls='--', lw=1.2)
ax.plot(range(len(names)), gs, '-o', color='#d62728', ms=9, lw=1.8)
for i, (n, gv) in enumerate(zip(names, gs)):
    ax.annotate(f"{gv:.3f}", (i, gv), textcoords='offset points',
                xytext=(0, 11), ha='center', fontsize=9.5)
ax.set_xticks(range(len(names)))
ax.set_xticklabels(['A0\n~5/26', 'A1\n5/27~6/5', 'B\n6/6~6/13', 'C1\n6/14~6/22', 'C2\n6/23~'],
                   fontsize=9)
ax.set_ylabel("g'  (ch1 / ch2 기울기)", fontsize=12)
ax.set_ylim(0.96, 1.22)
ax.text(0.5, 1.005, 'g\'=1 이면 두 채널 일치', fontsize=9, color='0.4')
ax.set_title("(b) g'는 상수가 아니다 → 구간별로 따로 구한다", fontsize=11, loc='left')

# (c) 보정 전/후 분포
ax = axes[2]
raw = (d.ch1 - d.ch2)
cor = pd.concat([fits[n][2].ch1 - fits[n][0] * fits[n][2].ch2 for n in names])
bins = np.linspace(-0.6, 0.8, 90)
ax.hist(raw, bins=bins, color='0.6', alpha=0.75, label=f'보정 전  ch1$-$ch2\nmedian {raw.median():+.3f}')
ax.hist(cor, bins=bins, color='#d62728', alpha=0.6,
        label=f"보정 후  ch1$-$g'·ch2\nmedian {cor.median():+.3f}")
ax.axvline(0, color='k', lw=1.0)
ax.set_xlabel('ANs [ppb]', fontsize=12); ax.set_ylabel('bins', fontsize=12)
ax.set_title('(c) 보정은 NO$_2$에 비례하는 성분을 걷어낸다', fontsize=11, loc='left')
ax.legend(fontsize=9)

fig.suptitle("ANs 이득 보정 (epoch gain correction) — 무엇을 어떻게 뺐는가",
             fontsize=13.5, x=0.005, ha='left')
fig.savefig(OUT, dpi=190)
print('saved:', OUT)
for n in names:
    g, a0, s = fits[n]
    print(f"{n:3s} g'={g:.4f}  a'={a0:+.4f}  n={len(s):,}")
