"""
기존 _R.dat 파일 읽어서
- np.mean (전체 평균) vs trimmed mean (엣지 5% 제거) 비교
- Leff 계산 확인
"""
import os, sys, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
base = r'C:\Users\kh548\OneDrive\바탕 화면\여수 필드 준비'
D_CM = 51.8

def trim_mean(r, trim=0.05):
    n = len(r)
    lo, hi = int(n*trim), n - int(n*trim)
    return float(np.mean(r[lo:hi])) if lo < hi else float(np.mean(r))

def leff_km(r):
    omr = 1.0 - trim_mean(r)
    return D_CM / omr * 1e-5 if omr > 0 else float('nan')

channels = {'Cold': 'R_Cold', 'Hot ANs': 'R_Hot_ANs', 'Hot PNs': 'R_Hot_PNs'}

for ch, sub in channels.items():
    ch_dir = os.path.join(base, sub)
    means_raw, means_trim, leffs = [], [], []
    for root, _, fnames in os.walk(ch_dir):
        for fn in sorted(fnames):
            if not fn.endswith('_R.dat'): continue
            rows = []
            with open(os.path.join(root,fn),'r',encoding='utf-8',errors='replace') as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith('#'): continue
                    parts = s.split('\t')
                    try: rows.append([float(x) for x in parts])
                    except ValueError: continue
            if not rows: continue
            d = np.array(rows)
            r = d[:,1]
            means_raw.append(float(np.mean(r))*100)
            means_trim.append(trim_mean(r)*100)
            leffs.append(leff_km(r))

    if not means_raw: print(f'{ch}: NO DATA'); continue
    mr, mt, ml = np.array(means_raw), np.array(means_trim), np.array(leffs)
    print(f'\n{ch}  ({len(mr)} files)')
    print(f'  mean(R) 전체평균:    {mr.min():.4f} ~ {mr.max():.4f}%  (범위 {mr.max()-mr.min():.4f}%)')
    print(f'  mean(R) trimmed:    {mt.min():.4f} ~ {mt.max():.4f}%  (범위 {mt.max()-mt.min():.4f}%)')
    print(f'  Leff (trimmed):     {ml.min():.3f} ~ {ml.max():.3f} km')
