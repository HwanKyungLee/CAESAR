#!/usr/bin/env python
"""tools/za_noise_floor.py — 제로에어(ZA) 스캔으로 기기 노이즈 바닥을 잰다.

`tools/temporal_noise.py` 가 남긴 숙제를 푼다. 저쪽은 ambient 인접스캔 차분이라
실제 대기 변동이 섞여 노이즈의 **상한**밖에 못 냈다. 제로에어는 같은 기체를
반복 측정하므로 대기 변동이 정확히 0이다 - 여기서 나온 산포가 순수 기기 노이즈다.

재는 것 (전부 DOAS 가 실제로 쓰는 **차분** 공간에서):

  다항식(baseline)이 흡수하고 남는 성분만 본다. 브로드밴드 드리프트는 핏의 poly
  항이 먹으므로 그대로 세면 노이즈를 몇 배 과대평가한다.

  1. per-scan 노이즈  std_i( hipass(I_i / Ibar - 1) )      = 한 스캔의 기기 노이즈
  2. ambient 차분신호 std( hipass(I0 / I_amb - 1) )        = 실제로 재려는 것의 크기
  3. I0 시간간 드리프트 std( hipass(I0_next / I0_prev - 1) ) = 낡은 I0 가 남기는 오차
     - 블록평균 자체의 노이즈(= per-scan / sqrt(n))를 **제곱차로 뺀다**. 안 빼면
       드리프트가 없어도 0 이 안 나온다.

물리상수가 필요 없다 - ZA 산포도 ambient 흡수도 같은 (1-R)/d 를 지나므로 비를
취하면 소거된다. 그래서 R(lambda)/캐비티길이 없이도 노이즈/신호가 정확히 나온다.

**per-pixel 숫자다.** DOAS 는 수백 픽셀에 구조를 걸쳐 핏하므로 농도의 SNR 은 이보다
sqrt(유효 독립픽셀수) 배 좋다. 픽셀당 노이즈/신호 > 1 이라고 "측정이 불가능"으로
읽으면 안 된다. 농도 단위로 환산하려면 실제 핏이 필요하다(아직 미구현).

사용:
    python tools/za_noise_floor.py <raw.dat> [...] --wavecal <calib.txt>
                                   [--channel PNs] [--nm 435,480] [--poly 4]
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.raw_parser import RawParser, FLAG_ZA, FLAG_AMBIENT


def differential(y, x, deg):
    """다항식 성분을 뺀 나머지. DOAS 의 baseline 항이 먹고 남는 것과 같다."""
    y = np.atleast_2d(np.asarray(y, dtype=float))
    V = np.vander(np.asarray(x, dtype=float) - np.mean(x), deg + 1)
    coef, *_ = np.linalg.lstsq(V, y.T, rcond=None)
    return y - (V @ coef).T


def deconvolve(total, known):
    """제곱차. total 이 known 보다 작으면(표본 요동) 0 으로 접는다."""
    return float(np.sqrt(max(total * total - known * known, 0.0)))


def load_block(path, channel):
    """raw 한 파일에서 (ZA 스펙트럼 행렬, ambient 평균 스펙트럼, ambient 행수)."""
    p = RawParser(path)
    if channel not in p.layout.spec_blocks:
        raise KeyError(f"{os.path.basename(path)}: 채널 {channel} 없음 "
                       f"(가능: {list(p.layout.spec_blocks)})")
    za, amb, n = [], None, 0
    for row, sp in p.iter_rows_with_spectra((channel,)):
        s = sp.get(channel)
        if s is None:
            continue
        if row.flag == FLAG_ZA:
            za.append(s)
        elif row.flag == FLAG_AMBIENT:
            amb = s.copy() if amb is None else amb + s
            n += 1
    return (np.asarray(za, dtype=float), (amb / n) if n else None, n)


def analyse(files, wavecal, channel, nm, poly, min_za=10):
    wave = np.loadtxt(wavecal, comments='#')
    wave = wave.reshape(-1) if wave.ndim == 1 else wave[:, -1].reshape(-1)
    w = (wave >= nm[0]) & (wave <= nm[1])
    x = wave[w]
    print(f"wavecal {len(wave)}px   window {nm[0]}-{nm[1]}nm -> {int(w.sum())}px   "
          f"poly_deg={poly}   channel={channel}")

    blocks = []
    for f in files:
        Z, Iamb, n = load_block(f, channel)
        tag = os.path.basename(f)
        if len(Z) < min_za or Iamb is None:
            print(f"  skip {tag}: ZA={len(Z)} amb={n}")
            continue
        blocks.append((tag, Z[:, w], Iamb[w]))
        print(f"  {tag}: ZA={len(Z)} amb={n}")
    if not blocks:
        print("분석할 ZA 블록이 없다.")
        return []

    print(f"\n{'block':>10}{'n':>4}{'ZA noise/scan':>16}{'ambient signal':>16}"
          f"{'noise/signal':>14}{'per-px SNR':>12}")
    rows, ratios = [], []
    for tag, Z, Iamb in blocks:
        I0 = Z.mean(axis=0)
        g = I0 > 0
        dz = differential(Z[:, g] / I0[g] - 1.0, x[g], poly)
        s_noise = float(np.median(np.std(dz, axis=0, ddof=1)))
        da = differential((I0[g] / np.maximum(Iamb[g], 1e-30) - 1.0)[None, :], x[g], poly)[0]
        s_sig = float(np.std(da))
        ratios.append(s_noise / s_sig)
        rows.append((tag, Z, I0, s_noise))
        print(f"{tag[-7:]:>10}{len(Z):>4}{s_noise:>16.3e}{s_sig:>16.3e}"
              f"{s_noise / s_sig:>14.3f}{s_sig / s_noise:>12.2f}")
    print(f"{'median':>10}{'':>4}{'':>16}{'':>16}"
          f"{float(np.median(ratios)):>14.3f}{1.0 / float(np.median(ratios)):>12.2f}")

    print("\nI0 drift between ZA cycles (block-mean noise removed in quadrature):")
    for a, b in zip(rows, rows[1:]):
        (ta, Za, I0a, na), (tb, Zb, I0b, nb) = a, b
        g = (I0a > 0) & (I0b > 0)
        dd = differential((I0b[g] / I0a[g] - 1.0)[None, :], x[g], poly)[0]
        raw_drift = float(np.std(dd))
        mean_noise = float(np.hypot(na / np.sqrt(len(Za)), nb / np.sqrt(len(Zb))))
        print(f"  {ta[-7:]} -> {tb[-7:]}   raw {raw_drift:.3e}"
              f"   block-mean noise {mean_noise:.3e}"
              f"   -> real drift {deconvolve(raw_drift, mean_noise):.3e}")
    return rows


def main():
    ap = argparse.ArgumentParser(description="제로에어 스캔 기반 기기 노이즈 바닥")
    ap.add_argument('files', nargs='+')
    ap.add_argument('--wavecal', required=True)
    ap.add_argument('--channel', default='PNs')
    ap.add_argument('--nm', default='435,480')
    ap.add_argument('--poly', type=int, default=4)
    a = ap.parse_args()
    nm = tuple(float(v) for v in a.nm.split(','))
    analyse(sorted(a.files), a.wavecal, a.channel, nm, a.poly)


if __name__ == '__main__':
    main()
