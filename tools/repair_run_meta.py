"""옛 `.meta.json` 의 캘리브 기록 복원 — 채널별 wavecal 을 **역추적**해서 고친다.

왜 필요한가
-----------
2026-09-19 이전 `gui/app_window_channels._calibration_state()` 는 채널을 안 봤다.
창에 '지금 로드된' wavecal 하나를 **모든 채널 메타**에 똑같이 적었다. 핏 자체는
`_build_engine_from_config(cfg)` 가 채널별 wavecal·레퍼런스로 정상 수행했으므로
**결과 숫자는 멀쩡하고 기록만 틀렸다.** 실제로 여수 2026 런에서 cold/roi1/roi2 로
각각 옳게 핏된 결과의 메타가 셋 다 roi 것을 가리켰고, 그 기록을 믿고 "콜드 ILS 가
17 % 틀렸다"는 오진이 나왔다. 기록이 침묵하는 게 아니라 **자신 있게 틀린** 경우다.

어떻게 역추적하나 (추정이지 기록이 아니다 — 그래서 결과에 그렇게 적는다)
------------------------------------------------------------------------
메타의 `window.px` 와 `window.nm` 은 **그 채널이 실제로 쓴 축**으로 환산된 값이다.
후보 wavecal 마다 `axis[px_lo], axis[px_hi]` 를 계산해 `window.nm` 과 대조하면
어느 파일을 썼는지 지문처럼 드러난다. 여수 실측에서 정답 후보는 0.01~0.07 nm,
오답은 0.81~0.88 nm 로 **10배 이상** 벌어졌다.

원칙
----
* **기본은 dry-run.** `--apply` 를 줘야 쓴다(헌장 ④: 자동 처리는 사람 승인 없이 금지).
* 원본 meta 는 `_archive/` 로 옮기고 새로 쓴다(헌장 ①: 지우지 않는다).
* 고친 값은 `calibration` 에 넣되, **무엇을 근거로 바꿨는지**를 `calibration_repair`
  블록에 남긴다 — 원래 기록·방법·후보별 잔차·모호하면 왜 포기했는지.
* **`runid` 는 안 바꾼다.** 파일명에 박혀 있어 바꾸면 `.dat` 과의 연결이 끊긴다.
  `calibration` 이 runid 해시에 들어가므로 "고친 설정으로 계산하면 이 값"을
  `runid_if_recomputed` 로 따로 적는다(정보용).
* 후보가 애매하면(2등과 2배 미만 차이) **건드리지 않고 ABSTAIN** 으로 보고한다.

사용:
  python tools/repair_run_meta.py --meta-root "<fitting 폴더>" --wv-root "<wv_cal 폴더>"
  python tools/repair_run_meta.py --meta-root ... --wv-root ... --apply
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from core.data_io import DataIO            # noqa: E402
from core.result_io import archive_existing  # noqa: E402
from core.run_meta import compute_runid     # noqa: E402

MARGIN = 2.0        # 1등이 2등보다 이 배수 이상 좋아야 채택
MAX_RESID_NM = 0.3  # 1등이라도 이보다 나쁘면 포기(축이 아예 다른 것)
# ★절대 분리 조건. `window.nm` 은 GUI 가 입력한 nm 를 **소수 1자리**로 저장한다
# (`run_meta.build_meta` → cfg['fit_start_nm']). 끝점마다 최대 0.05 nm 반올림 오차가
# 있으니 두 끝점 합은 0.1 nm 까지 흔들린다. 비율만 보면 0.011 대 0.069 같은
# **잡음 이하 차이로 승자를 뽑게 된다** — 실제로 여수 PNs 가 그랬다(6.3배지만 절대
# 차이는 0.058 nm). 축이 서로 0.03 nm 밖에 안 다른 roi1/roi2 는 이 해상도로는
# 원리상 구분 불가다. 못 고르면 고르지 않는 게 맞다.
MIN_SEP_NM = 0.15


def load_candidates(wv_root):
    """{'roi2/Calib_x.txt': ndarray} — wv_cal 하위 모든 Calib_*.txt."""
    out = {}
    for p in sorted(glob.glob(os.path.join(wv_root, '*', 'Calib_*.txt'))):
        try:
            a = np.asarray(DataIO.load_wavecal_array(p), float).ravel()
        except Exception as e:                 # noqa: BLE001
            print(f"  [skip] {p}: {e}")
            continue
        if a.size >= 2:
            out[f"{os.path.basename(os.path.dirname(p))}/{os.path.basename(p)}"] = a
    return out


def identify(meta, cands):
    """(선택된 tag, 후보별 잔차 dict, 사유) — 못 고르면 tag=None."""
    win = meta.get('window') or {}
    px, nm = win.get('px'), win.get('nm')
    if not (isinstance(px, (list, tuple)) and isinstance(nm, (list, tuple))
            and len(px) == 2 and len(nm) == 2):
        return None, {}, "window.px/nm 없음"
    lo, hi = int(px[0]), int(px[1])
    resid = {}
    for tag, ax in cands.items():
        if not (0 <= lo < ax.size and 0 <= hi < ax.size):
            continue
        resid[tag] = round(float(abs(ax[lo] - nm[0]) + abs(ax[hi] - nm[1])), 4)
    if not resid:
        return None, {}, "픽셀 범위를 담는 후보 없음"
    order = sorted(resid.items(), key=lambda kv: kv[1])
    best, bv = order[0]
    if bv > MAX_RESID_NM:
        return None, resid, f"최선 후보도 {bv:.3f} nm 어긋남(>{MAX_RESID_NM})"
    if len(order) > 1:
        second, sv = order[1]
        if sv < bv * MARGIN or (sv - bv) < MIN_SEP_NM:
            return None, resid, (
                f"1등 {best} {bv:.3f} · 2등 {second} {sv:.3f} — "
                f"{'배수' if sv < bv * MARGIN else '절대차'} 부족"
                f"(필요: {MARGIN}배 그리고 {MIN_SEP_NM} nm 이상; "
                f"window.nm 이 소수 1자리라 그 아래는 반올림 잡음)")
    return best, resid, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--meta-root', required=True, help='.meta.json 이 있는 폴더(재귀)')
    ap.add_argument('--wv-root', required=True, help='wv_cal 폴더(하위에 채널 폴더들)')
    ap.add_argument('--apply', action='store_true', help='실제로 쓴다(기본은 dry-run)')
    a = ap.parse_args()

    cands = load_candidates(a.wv_root)
    if not cands:
        raise SystemExit(f"후보 wavecal 없음: {a.wv_root}/*/Calib_*.txt")
    print(f"후보 wavecal {len(cands)}개: {', '.join(sorted(cands))}")

    metas = sorted(glob.glob(os.path.join(a.meta_root, '**', '*.meta.json'), recursive=True))
    print(f"meta {len(metas)}개  ({'APPLY' if a.apply else 'DRY-RUN — 아무것도 안 쓴다'})\n")

    n_fix = n_same = n_abstain = 0
    summary = {}
    for mp in metas:
        try:
            meta = json.load(open(mp, encoding='utf-8'))
        except Exception as e:                  # noqa: BLE001
            print(f"  [skip] {os.path.basename(mp)}: {e}")
            continue
        tag, resid, why = identify(meta, cands)
        key = f"CH{meta.get('channel')} {meta.get('label')}"
        cal = meta.get('calibration') or {}
        recorded = cal.get('wavecal', '')
        if tag is None:
            n_abstain += 1
            summary.setdefault(key, {}).setdefault('ABSTAIN: ' + why, 0)
            summary[key]['ABSTAIN: ' + why] += 1
            continue
        if recorded == tag:
            n_same += 1
            summary.setdefault(key, {}).setdefault(f'이미 맞음 ({tag})', 0)
            summary[key][f'이미 맞음 ({tag})'] += 1
            continue

        n_fix += 1
        summary.setdefault(key, {}).setdefault(f'{recorded} → {tag}', 0)
        summary[key][f'{recorded} → {tag}'] += 1
        if not a.apply:
            continue

        new_cal = dict(cal)
        new_cal['wavecal'] = tag
        # 전역 위젯에서 온 ILS 는 그 채널 것이라는 보장이 없다 → 기록에서 내린다.
        for k in ('ils_fwhm_nm', 'ils_fwhm_px'):
            if k in new_cal:
                new_cal[k] = None
        probe = dict(meta)
        probe['calibration'] = new_cal
        meta['calibration'] = new_cal
        meta['calibration_repair'] = {
            "tool": "tools/repair_run_meta.py",
            "method": "window.px→window.nm 지문 대조(추정이며 기록이 아니다)",
            "original": {k: cal.get(k) for k in ('wavecal', 'ils_fwhm_nm', 'ils_fwhm_px')},
            "residual_nm_by_candidate": resid,
            "note": ("옛 _calibration_state() 가 채널을 안 보고 창에 로드된 wavecal 을 "
                     "모든 채널에 적었다. 핏 자체는 채널 config 로 수행됐으므로 "
                     "결과 숫자는 영향 없다. ils_fwhm 은 전역 위젯 값이라 내렸다."),
            "runid_unchanged": meta.get('runid'),
            "runid_if_recomputed": compute_runid(probe),
        }
        archive_existing(mp, a.meta_root)
        with open(mp, 'w', encoding='utf-8') as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)

    for key in sorted(summary):
        print(f"{key}:")
        for what, n in sorted(summary[key].items(), key=lambda kv: -kv[1]):
            print(f"    {n:4d}  {what}")
    print(f"\n고칠 것 {n_fix} · 이미 맞음 {n_same} · 포기 {n_abstain}")
    if n_fix and not a.apply:
        print("→ 적용하려면 --apply. 원본 meta 는 _archive/ 로 옮겨진다(삭제 없음).")


if __name__ == '__main__':
    main()
