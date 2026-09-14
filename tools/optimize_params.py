"""tools/optimize_params.py — 파라미터 자동 최적화 CLI(헤드리스 검증용).

사용자 FitSet json(레퍼런스·핏레인지 고정)을 baseline으로, core/param_optimizer로
poly 차수 + ref별 shift/squeeze 정책·크기를 자동 판정한다.

사용:  python tools/optimize_params.py [키] (--allow-negative-gas | --nonnegative-gas)

엔진 빌드는 app_window._build_engine_from_config를 **그대로 복제**(wavecal이 축,
add_reference(wave_nm=wave, multiplier=10^mult), ILS 0) — 헤드리스=GUI 보장.

채널 키(cold/ans/pns 등)는 코드에 박지 않고 `tools/channel_map.json`에서 읽는다 —
CAESAR 한 대가 나중에 캐비티를 늘리면(예: 3채널) 그 json에 항목만 추가하면 되고
이 파일이나 build_fitset.py/design_window.py/t2_reference_check.py(전부 이 모듈을
재사용)를 고칠 필요가 없다.
"""
import os
import sys
import json
import glob
import argparse
from datetime import date, timedelta

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.engine import UniversalEngine
from core.doas_fit import DoasFitter
from core import param_optimizer as PO
from tools.residual_compare import load_alpha

FITSET = r"C:\Doasis_Work\Output\fit setting\FitSet_ANs[430-466nm_P4]_PNs[444-471nm_P3]_cold[438-466nm_P4]_Std.json"
CHANNEL_MAP_PATH = os.path.join(ROOT, "tools", "channel_map.json")


def _golden_date_set(date_range):
    """[시작,끝] ISO 날짜 → 그 사이 모든 날짜의 {'YYYY-MM-DD',...} 집합. 없으면 None(필터 없음)."""
    if not date_range:
        return None
    lo, hi = date.fromisoformat(date_range[0]), date.fromisoformat(date_range[1])
    return {(lo + timedelta(d)).isoformat() for d in range((hi - lo).days + 1)}


def _load_channel_map(path=CHANNEL_MAP_PATH):
    """채널 키 → (알파 glob, 표본일 필터)/wavecal 폴더/표시라벨. 새 채널은 이 json에
    항목만 추가하면 된다(코드 수정 불필요) — 2026-08 CAESAR 재구성 대비 정리."""
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    alpha_root, alpha_bin = cfg["alpha_root"], cfg.get("alpha_bin", "60s")
    chan_alpha, key2wldir, key2label = {}, {}, {}
    for key, c in cfg["channels"].items():
        pattern = os.path.join(alpha_root, alpha_bin, *c["alpha_glob"].split("/"))
        chan_alpha[key] = (pattern, _golden_date_set(c.get("golden_date_range")))
        key2wldir[key] = c["wavecal_dir"]
        key2label[key] = c.get("label", key)
    return chan_alpha, key2wldir, key2label, cfg["wavecal_root"]


def verify_channel_map_against_profiles(key2wldir=None, key2label=None, profiles_dir=None):
    """channel_map의 채널→wavecal 폴더가 **캠페인 프로파일과 같은지** 대조.

    같은 매핑이 두 파일에 있으면 언젠가 어긋난다 — 실제로 2026-09-14에 ch 번호와 roi
    번호를 같은 번호끼리 짝지어 `tools/channel_map.json`과 Oculus 프로파일 **둘 다**
    반대로 들어가 있었다(2026 여수는 roi1=PNs, roi2=ANs로 ch와 번호가 반대).

    기준은 **캠페인 프로파일**이다(계측기 진실). channel_map은 기계별 경로를 담는 파일이라
    지우지 않고 남기되, 매핑이 어긋나면 여기서 드러난다. **차단하지 않고 보고만 한다**
    (헌장: 검증 ≠ 필터). 회귀 검사는 `tools/test_raw_layout.py`.

    반환: 불일치 목록 [(채널키, channel_map값, 프로파일값)]
    """
    key2wldir = KEY2WLDIR if key2wldir is None else key2wldir
    key2label = KEY2LABEL if key2label is None else key2label
    try:
        from core.profile import ProfileSet
        ps = (ProfileSet.load_default() if profiles_dir is None
              else ProfileSet.load(profiles_dir))
    except Exception as e:                       # noqa: BLE001 — 프로파일이 없어도 도구는 돈다
        return [("(프로파일 로드 실패)", "", str(e))]

    prof_wldir = {}
    for prof in ps.profiles:
        for ch in prof.channels:
            wl = getattr(ch.concentration, "wl_dir", None) if ch.concentration else None
            if ch.role == "signal" and wl:
                for name in (ch.label, ch.id):
                    if name:
                        prof_wldir[str(name).casefold()] = wl

    bad = []
    for key, wldir in key2wldir.items():
        want = prof_wldir.get(str(key).casefold()) or             prof_wldir.get(str(key2label.get(key, key)).casefold())
        if want and want != wldir:
            bad.append((key, wldir, want))
    return bad


CHAN_ALPHA, KEY2WLDIR, KEY2LABEL, WAVECAL_ROOT = _load_channel_map()

for _k, _have, _want in verify_channel_map_against_profiles():
    print(f"[channel_map] ⚠ 채널 '{_k}'의 wavecal 폴더가 캠페인 프로파일과 다르다: "
          f"channel_map='{_have}' vs 프로파일='{_want}'. "
          f"어느 쪽이 이 캠페인의 실제 구성인지 확인할 것 — 틀리면 **다른 채널의 "
          f"파장보정으로 핏**하게 된다.")
N_SCANS = 12
POLYS = [2, 3, 4, 5, 6, 8]


def canonical_channel_key(value):
    """Accept case variants of configured keys/labels, returning the map key."""
    if not isinstance(value, str):
        return value
    folded = value.strip().casefold()
    for key, label in KEY2LABEL.items():
        if folded in {key.casefold(), str(label).casefold()}:
            return key
    return value


def require_key(key):
    """알 수 없는 채널 키에 바로 KeyError 대신 사용 가능한 키 목록 + 어디를 고칠지 알려준다."""
    if key not in CHAN_ALPHA:
        raise SystemExit(f"알 수 없는 채널 키 '{key}'. 사용 가능: {sorted(CHAN_ALPHA)} "
                         f"(새 채널은 {CHANNEL_MAP_PATH}에 추가)")


def ref_path(key, filename):
    """이 채널의 wavecal 폴더 안 파일 경로(예: O4 후보 레퍼런스)."""
    require_key(key)
    return os.path.join(WAVECAL_ROOT, KEY2WLDIR[key], filename)


def load_wavecal(path):
    """app_window._load_wavecal_array 복제."""
    try:
        try:
            df = pd.read_csv(path, sep=r"\s+", header=None)
        except Exception:
            df = pd.read_csv(path, sep=",", header=None)
        for i in range(df.shape[1]):
            col = pd.to_numeric(df.iloc[:, i], errors="coerce").dropna()
            if len(col) > 10:
                return col.values.flatten()
    except Exception:
        pass
    return None


def build_engine_from_config(cfg):
    """app_window._build_engine_from_config 복제(순수)."""
    eng = UniversalEngine()
    wave = load_wavecal(cfg.get("wl_path", ""))
    if wave is not None:
        eng.set_wavelength_axis(wave)
    for ref in cfg.get("refs", []):
        p = ref.get("path", "")
        if os.path.exists(p):
            try:
                eng.add_reference(name=ref["name"], filepath=p, wave_nm=wave,
                                  multiplier=10.0 ** ref.get("mult", 0))
            except Exception as e:            # noqa: BLE001
                print(f"[engine] ref 실패 {ref.get('name')}: {e}")
    try:
        eng.apply_ils_convolution(0.0)
    except Exception:
        pass
    return eng


def pick_channel(scen, key):
    """wl_path(roi1/roi2/cold)로 채널 매칭. data_label은 쓰지 않는다 — FitSet json에서
    라벨이 실제 채널과 뒤바뀌어 저장된 사례가 있다(§14-D, roi1이 'PNs'로 잘못 저장됨)."""
    key = canonical_channel_key(key)
    require_key(key)
    wldir = KEY2WLDIR[key]
    for ch in scen["channels"].values():
        if wldir in str(ch.get("wl_path", "")).replace("\\", "/").split("/"):
            return ch
    raise SystemExit(f"wl_path에 '{wldir}' 폴더를 쓰는 채널 없음 (key='{key}') — "
                     f"FitSet json에 이 채널이 아직 없을 수 있음")


def gather_scans(key, n):
    require_key(key)
    pattern, day_filter = CHAN_ALPHA[key]
    files = sorted(glob.glob(pattern))
    if day_filter is not None:
        files = [f for f in files
                 if os.path.basename(os.path.dirname(f)) in day_filter]
    if not files:
        raise SystemExit(f"알파 없음: {pattern}")
    pick = files[:: max(1, len(files) // n)][:n]
    return [load_alpha(fp) for fp in pick], len(files)


def gather_consecutive(key, n):
    """시간상 인접한 스캔 블록(한 폴더 내 연번) — step_limit 추정 전용.
    날짜별로 흩뿌린 표본으로 Δshift를 재면 과대추정되므로 반드시 연속으로."""
    require_key(key)
    pattern, day_filter = CHAN_ALPHA[key]
    files = sorted(glob.glob(pattern))
    if day_filter is not None:
        files = [f for f in files
                 if os.path.basename(os.path.dirname(f)) in day_filter]
    if not files:
        return []
    # 파일이 가장 많은 날(연속성 최대) 선택
    from collections import Counter
    day = Counter(os.path.dirname(f) for f in files).most_common(1)[0][0]
    block = sorted(f for f in files if os.path.dirname(f) == day)[:n]
    out = []
    for fp in block:
        try:
            out.append(load_alpha(fp))
        except Exception:                 # noqa: BLE001
            pass
    return out


def nm_to_px(wave, nm):
    return int(np.argmin(np.abs(np.asarray(wave, float) - nm)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("key", nargs="?", default="cold")
    policy = parser.add_mutually_exclusive_group(required=True)
    policy.add_argument("--allow-negative-gas", action="store_true")
    policy.add_argument("--nonnegative-gas", action="store_true")
    parser.add_argument("--override-fitset-policy", action="store_true",
                        help="intentionally override a conflicting policy stored in the FitSet")
    args = parser.parse_args()
    key = args.key.lower()
    allow_negative_gas = args.allow_negative_gas
    require_key(key)
    scen = json.load(open(FITSET, encoding="utf-8"))
    ch = pick_channel(scen, key)
    stored_policy = ch.get("allow_negative_gas")
    if stored_policy is not None and not isinstance(stored_policy, bool):
        parser.error("FitSet allow_negative_gas must be boolean")
    if stored_policy is not None and stored_policy != allow_negative_gas \
            and not args.override_fitset_policy:
        parser.error("CLI gas policy conflicts with FitSet; use --override-fitset-policy intentionally")
    policy_source = ("explicit CLI override of FitSet" if stored_policy is not None
                     and stored_policy != allow_negative_gas else
                     "FitSet confirmed by CLI" if stored_policy is not None else "explicit CLI (legacy FitSet)")
    rp = ch["ref_props"]
    step_limit = float(ch.get("step_limit", 0.5))
    poly0 = int(ch["poly_deg"])

    scans, n_total = gather_scans(key, N_SCANS)
    eng = build_engine_from_config(ch)
    fitter = DoasFitter(eng)
    wave0 = scans[0][0]
    # ⚠️ FitSet json은 f_min/f_max(px)와 fit_start_nm/fit_end_nm이 **불일치**한다.
    # 앱의 실제 저장 결과 헤더("Fit Range: Pixel 774-1550")로 확인한 결과 **px 필드가 진짜**다.
    # (cold: px 774-1550 = 438.4-475.8nm ≠ nm필드 438.0-465.8. nm필드는 스테일.)
    px_min, px_max = int(ch["f_min"]), int(ch["f_max"])
    target = "NO2"

    print("#" * 100)
    # 헤더는 CLI key/channel_map 라벨로 표기(ch['data_label']은 json 안에서 뒤바뀌어 있을 수
    # 있어 안 씀 — pick_channel 주석 참조).
    print(f"# {key}({KEY2LABEL.get(key, key)})  refs={list(eng.gas_list)}  "
          f"창 {ch['fit_start_nm']}-{ch['fit_end_nm']}nm "
          f"(px {px_min}-{px_max})  baseline poly{poly0}  스캔 {len(scans)}/{n_total}")
    print("#" * 100)

    # ── baseline 평가 ──
    print(f"# gas coefficient policy: allow_negative_gas={allow_negative_gas} ({policy_source})")
    base = PO.evaluate(scans, eng, fitter, rp, px_min, px_max, poly0, step_limit,
                       target, allow_negative_gas=allow_negative_gas)
    print(f"[baseline] poly{poly0}: NO2={base['conc']:.1f}ppb  perr_rel={base['perr_rel']:.3f}  "
          f"rms/sig={base['rms_sig']*100:.1f}%  |ac1|={abs(base['autocorr1']):.2f}  n_free={base['n_free']}")
    for g in eng.gas_list:
        m, s = base["shift_dist"][g]
        print(f"           {g:8s} 핏shift {m:+.2f}±{s:.2f}px")

    # ── A-1: poly 차수 무릎점 ──
    rec_poly, ladder = PO.optimize_poly(scans, eng, fitter, rp, px_min, px_max,
                                        POLYS, step_limit, target,
                                        allow_negative_gas=allow_negative_gas)
    print(f"\n[poly 사다리]  (무릎점 추천 = poly{rec_poly})")
    print(f"  {'poly':>4} {'NO2ppb':>8} {'rms/sig':>8} {'|ac1|':>6} {'conc_cv':>8}")
    for r in ladder:
        mark = " ←추천" if r["poly"] == rec_poly else ""
        print(f"  {r['poly']:>4} {r['conc']:>8.1f} {r['rms_sig']*100:>7.1f}% "
              f"{abs(r['autocorr1']):>6.2f} {r['conc_cv']*100:>7.1f}%{mark}")

    # ── A-2: target shift 크기(넓게 풀어 분포로 결정) ──
    print(f"\n[NO2 shift 크기 자동결정]  (현재 설정 {rp[target]['sh_mode']} {rp[target]['sh_val']})")
    sh = PO.recommend_shift(scans, eng, fitter, rp, px_min, px_max, rec_poly,
                            target, allow_negative_gas=allow_negative_gas)
    print(f"  → {sh['reason']}")

    # ── A-3: squeeze 크기 ──
    print(f"\n[NO2 squeeze 크기 자동결정]  (현재 {rp[target]['sq_mode']} {rp[target]['sq_val']})")
    sq = PO.recommend_squeeze(scans, eng, fitter, rp, px_min, px_max, rec_poly,
                              target, step_limit=step_limit,
                              allow_negative_gas=allow_negative_gas)
    print(f"  → {sq['reason']}")

    # ── A-4: step_limit (연속 스캔 블록 필요) ──
    print(f"\n[step_limit 자동결정]  (현재 {step_limit})  ※연속 스캔으로 측정")
    consec = gather_consecutive(key, 20)
    if consec:
        st = PO.recommend_step_limit(consec, eng, fitter, rp, px_min, px_max, rec_poly,
                                     target, allow_negative_gas=allow_negative_gas)
        print(f"  → {st['reason']}")
    else:
        print("  → 연속 스캔 확보 실패")

    # ── A-5: 2차 ref Link vs 독립 ──
    print(f"\n[2차 레퍼런스 shift 정책]")
    for sec in eng.gas_list:
        if sec == target:
            continue
        dec = PO.recommend_secondary_link(scans, eng, fitter, rp, px_min, px_max,
                                          rec_poly, sec, target, step_limit,
                                          allow_negative_gas=allow_negative_gas)
        print(f"  {sec:8s}: {dec['reason']}")


if __name__ == "__main__":
    main()
