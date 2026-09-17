#!/usr/bin/env python
"""tools/temporal_noise.py — 인접 스캔 차분으로 '진짜' 측정 노이즈를 잰다.

왜 필요한가 — RMS·chi2·Unstable 은 전부 **한 스캔 안에서** 핏이 스스로를 채점한
자기일관성(T1) 지표다. 같은 공기를 60초 뒤에 다시 잰 값과 비교하는 건 그보다 한
단계 위다(CLAUDE.md §2 의 T2 쪽) — 핏이 한 번 스스로를 속을 수는 있어도, 연속
두 스캔에서 같은 방향으로 똑같이 속기는 어렵다.

재는 것은 Allan 편차(비중첩):

    sigma_A(tau)^2 = 1/(2(M-1)) * sum_k (yb_{k+1} - yb_k)^2
    yb_k = 연속 tau 스캔의 블록평균

  · tau=1 이 **단일 스캔 반복성**. 보고 오차(perr)와 비교하면 perr 이 맞는지 나온다.
  · 백색잡음이면 sigma_A(tau) 는 1/sqrt(tau) 로 준다 — 평균낼수록 좋아진다.
  · 어느 tau 에서 그 기울기가 꺾이면 거기가 **드리프트/실제 대기변동 바닥**이다.
    그 아래로는 더 오래 평균내도 안 좋아진다 = 평균 구간을 그 이상 늘릴 이유가 없다.

**한계 (중요, 결론 낼 때 반드시 같이 읽을 것)** — 인접 스캔 차분에는 실제 대기
변동이 섞인다. 따라서 sigma_A 는 노이즈의 **상한**이다. 60초 안에 대기가 얼마나
변했는지는 이 도구가 알 수 없다. "노이즈 = sigma_A" 가 아니라 "노이즈 <= sigma_A"
로 읽어야 하고, 그래서 이걸로 레퍼런스나 세팅을 심판하면 안 된다(§2: 단독 심판 금지).

시간이 끊긴 자리(캘 사이클·파일 경계·결측)에서는 차분하지 않는다 — 간격이 벌어진
두 스캔의 차이는 노이즈가 아니라 그냥 시간이다. 값이 NaN 인 행(QC 배제 등)도
구간을 끊는다.

사용:
    python tools/temporal_noise.py <result.dat|autosave.tsv> [...]
                                   [--taus 1,2,5,10,30,60] [--by-status]
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.result_io import read_result          # 결과파일 파싱 단일 출처
from core.agreement import effective_n          # 자기상관 반영 유효 표본수


def contiguous_runs(t_sec, v, step, tol=0.5):
    """시간이 step 간격으로 이어지고 값이 유한한 **최대 구간**들의 리스트.

    끊는 조건 두 가지뿐이다: 간격이 step 에서 tol 비율 넘게 벗어나거나, 값이 NaN.
    길이 2 미만 구간은 차분을 못 만드니 버린다.
    """
    t_sec = np.asarray(t_sec, dtype=float)
    v = np.asarray(v, dtype=float)
    if len(v) < 2:
        return []
    ok = np.isfinite(v)
    cont = np.zeros(len(v), dtype=bool)
    cont[1:] = np.abs(np.diff(t_sec) - step) <= tol * step
    runs, cur = [], []
    for i in range(len(v)):
        if not ok[i]:
            if len(cur) >= 2:
                runs.append(np.asarray(cur, dtype=float))
            cur = []
            continue
        if cur and cont[i]:
            cur.append(v[i])
        else:
            if len(cur) >= 2:
                runs.append(np.asarray(cur, dtype=float))
            cur = [v[i]]
    if len(cur) >= 2:
        runs.append(np.asarray(cur, dtype=float))
    return runs


def allan_sigma(runs, tau):
    """여러 연속구간에 걸친 비중첩 Allan 편차 sigma_A(tau). 표본 없으면 nan.

    구간마다 따로 블록평균을 내고 **제곱합만** 모은다 — 구간을 이어붙이면
    경계에서 시간이 튄 차분이 하나 섞여 노이즈를 부풀린다.
    """
    ss, n = 0.0, 0
    for v in runs:
        m = len(v) // tau
        if m < 2:
            continue
        b = v[:m * tau].reshape(m, tau).mean(axis=1)
        d = np.diff(b)
        ss += float(d @ d)
        n += int(len(d))
    return float(np.sqrt(ss / (2.0 * n))) if n else float('nan')


def _cols(colhdr):
    return {c: i for i, c in enumerate(colhdr.split('\t'))}


def _f(row, i):
    if i is None or i >= len(row):
        return float('nan')
    try:
        return float(row[i])
    except ValueError:
        return float('nan')


def analyse(path, taus, by_status=False):
    comments, colhdr, rows = read_result(path)
    idx = _cols(colhdr)
    cols = colhdr.split('\t')
    gases = [c for c in cols if f"{c}_Error" in idx and not c.endswith('_Error')]
    if not gases:
        print(f"  (기체 컬럼 없음 — <gas>/<gas>_Error 쌍을 못 찾음)")
        return
    split = [r[1].split('\t') for r in rows]
    t_sec = np.array([r[0].timestamp() for r in rows], dtype=float)
    ch_i, st_i = idx.get('Channel'), idx.get('Status')
    chans = np.array([(_f(r, ch_i) if ch_i is not None else 0.0) for r in split])
    labels = np.array([(r[st_i].split(' ')[0] if st_i is not None and st_i < len(r) else '')
                       for r in split])

    print(f"\n{'=' * 78}\n{os.path.basename(path)}   {len(rows):,}행   기체 {','.join(gases)}")
    for ch in sorted(set(chans[np.isfinite(chans)])):
        m = chans == ch
        t, lab = t_sec[m], labels[m]
        order = np.argsort(t, kind='stable')
        t, lab = t[order], lab[order]
        dt = np.diff(t)
        dt = dt[dt > 0]
        if len(dt) == 0:
            continue
        step = float(np.median(dt))
        print(f"\n-- Channel {int(ch)}   n={int(m.sum()):,}   스캔간격 {step:.0f}s")
        for g in gases:
            v = np.array([_f(r, idx[g]) for r in split])[m][order]
            e = np.array([_f(r, idx[f'{g}_Error']) for r in split])[m][order]
            runs = contiguous_runs(t, v, step)
            if not runs:
                print(f"   {g:<8} 연속구간 없음 — 건너뜀")
                continue
            s1 = allan_sigma(runs, 1)
            tot = sum(len(r) for r in runs)
            print(f"   {g:<8} 연속구간 {len(runs):,}개 (총 {tot:,}스캔, 최장 {max(len(r) for r in runs):,})")
            head = "      tau(scans) " + "".join(f"{x:>10d}" for x in taus)
            sig = "      sigma_A    " + "".join(f"{allan_sigma(runs, x):>10.4g}" for x in taus)
            wht = "      백색예측    " + "".join(f"{s1 / np.sqrt(x):>10.4g}" for x in taus)
            rat = "      실측/예측   " + "".join(
                f"{allan_sigma(runs, x) / (s1 / np.sqrt(x)):>10.2f}" for x in taus)
            print(head); print(sig); print(wht); print(rat)
            perr = float(np.nanmedian(e))
            val = float(np.nanmedian(np.abs(v)))
            if np.isfinite(perr) and perr > 0:
                print(f"      보고 perr(중앙) {perr:.4g}   sigma_A(1)/perr = {s1 / perr:.2f}배"
                      f"   <- 1보다 크면 보고 오차가 과소평가")
            print(f"      |값|중앙 {val:.4g}   반복성 SNR = |값|/sigma_A(1) = {val / s1:.2f}"
                  f"   MDL(3sigma,1스캔) = {3 * s1:.4g}")
            vv = v[np.isfinite(v)]
            if len(vv) >= 3:
                print(f"      유효표본 n_eff = {effective_n(vv):,.0f} / {len(vv):,}"
                      f"  (자기상관 반영)")
            if by_status:
                parts = []
                for want in ('OK', 'Recovered', 'Unstable'):
                    sel = np.where(lab == want, v, np.nan)
                    r2 = contiguous_runs(t, sel, step)
                    s = allan_sigma(r2, 1)
                    if np.isfinite(s):
                        parts.append(f"{want} {s:.4g}")
                if parts:
                    print(f"      Status별 sigma_A(1):  " + "   ".join(parts))


def main():
    ap = argparse.ArgumentParser(description="인접 스캔 차분 기반 실측 노이즈(Allan 편차)")
    ap.add_argument('files', nargs='+')
    ap.add_argument('--taus', default='1,2,5,10,30,60',
                    help='블록 길이(스캔 수), 쉼표 구분')
    ap.add_argument('--by-status', action='store_true',
                    help='Status 라벨별로 sigma_A(1)을 따로 낸다')
    a = ap.parse_args()
    taus = [int(x) for x in a.taus.split(',') if x.strip()]
    for f in a.files:
        analyse(f, taus, by_status=a.by_status)


if __name__ == '__main__':
    main()
