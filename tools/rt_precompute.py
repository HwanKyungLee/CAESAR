"""R(t) 프리컴퓨트 — R_trend_monitor의 검증된 scan_directory로 채널별 R(t) knot을
계산해 파일로 저장/로드한다. 알파 생성은 이 결과를 읽어 시간보간·적용한다.

설계 원칙 (캠페인 무관)
----------------------
채널 설정(R-fit 창·압력/온도 컬럼·스펙 컬럼·tz)을 **이름으로 하드코딩하지 않고
명시적 파라미터(RTConfig)로 받는다.** 그래야 다른 캠페인/다른 채널명이 와도
GUI(R-trend 좌측 패널) 세팅값만 넘겨주면 그대로 동작한다. `PRESETS`는 현재
2026 여수 캠페인 편의용 기본값일 뿐, 보편 상수가 아니다.

왜 scan_directory 재사용?
------------------------
알파 워커가 자체 페어링으로 R(t)를 만들면 ROI/페어링을 틀리기 쉽다(전체범위 ROI →
핫 98% 게이트 탈락, Leff ~2배 오차 관측). scan_directory는 박사님 Rs2.m대로 채널별
R-fit 창·ZA/He 그룹핑·게이팅을 제대로 하므로 그 결과를 '단일 진실원천'으로 재사용한다.

시간축
------
knot 시각은 알파 ambient의 rep_sec와 동일한 raw bytepack 연초기준 초(instrument
clock, tz 변환 없음). 채널별로 같은 raw 파일을 쓰므로 cold(UTC)/hot(KST) 간 tz
차이는 신경 쓸 필요 없다 — 각 채널 안에서 knot·bin이 같은 시계를 공유한다.
"""
import os
import sys
import json
from dataclasses import dataclass, asdict, field
import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import r_trend_monitor as _RT
from core.data_io import DataIO
# R 계산은 scan_directory(data_io 단일파스+병렬) 한 곳으로 통일 — reflectance_calc·
# read_all_scans 등은 더 이상 여기서 직접 안 씀(_campaign_presets만 inline import).


@dataclass
class RTConfig:
    """한 채널의 R(t) 계산 설정 — 캠페인/채널명 무관. GUI 좌측 패널 세팅에서 채워서
    넘기면 된다. label은 출처 표시용(ch1/ch2/사용자라벨 등) — 계산엔 안 쓰임."""
    fit_window_nm: tuple          # R-fit 파장창 (nm, 미러 흡수 깨끗한 구간)
    col_press: int                # 압력 HK 컬럼
    col_temp: int                 # 온도 HK 컬럼
    spec_start: int               # 스펙트럼 시작 컬럼
    spec_end: int                 # 스펙트럼 끝 컬럼
    ts_tz_hours: int = 9          # 타임스탬프 해석 tz(시간). Cold raw=UTC(0)? Hot=KST(9)
    label: str = ""               # 출처/채널 라벨 (자유 문자열)
    dio_channel: int = 1          # data_io 채널(1/2) — 트렁케이트 T/P를 hk_shift로 보정해 읽기용


def _tz(hours):
    from datetime import timezone, timedelta
    return timezone(timedelta(hours=hours))


# ── 현재 2026 여수 캠페인 프리셋 (편의용 — 보편 상수 아님) ──────────────────────
# 값 출처: r_batch_calculator 컬럼 상수 + 박사님 Rs2.m 채널 창. 새 캠페인이면
# GUI 세팅으로 RTConfig를 직접 만들어 넘기면 된다.
def _campaign_presets():
    from r_batch_calculator import (
        COL_PRESS_COLD, COL_TEMP_COLD, COL_PRESS_HOT_PNS, COL_PRESS_HOT_ANS,
        COL_TEMP_HOT, SPEC_START_DEFAULT, SPEC_END_DEFAULT, SPEC_START_ANS, SPEC_END_ANS,
    )
    cold_tz = int(getattr(_RT.COLD_TS_TZ, 'utcoffset')(None).total_seconds() // 3600)
    hot_tz  = int(getattr(_RT.HOT_TS_TZ,  'utcoffset')(None).total_seconds() // 3600)
    return {
        "cold":    RTConfig((435.0, 480.0), COL_PRESS_COLD,    COL_TEMP_COLD, SPEC_START_DEFAULT, SPEC_END_DEFAULT, cold_tz, "cold",    dio_channel=1),
        "hot_pns": RTConfig((430.0, 465.0), COL_PRESS_HOT_PNS, COL_TEMP_HOT,  SPEC_START_DEFAULT, SPEC_END_DEFAULT, hot_tz,  "hot_pns", dio_channel=1),
        "hot_ans": RTConfig((435.0, 470.0), COL_PRESS_HOT_ANS, COL_TEMP_HOT,  SPEC_START_ANS,     SPEC_END_ANS,     hot_tz,  "hot_ans", dio_channel=2),
    }


def preset(name):
    """현 캠페인 프리셋 RTConfig 반환 (cold/hot_pns/hot_ans). 새 캠페인은 RTConfig 직접 생성."""
    p = _campaign_presets()
    if name not in p:
        raise ValueError(f"unknown preset '{name}' — build an RTConfig directly. (available: {list(p)})")
    return p[name]


def _file_first_sec(path):
    """파일 첫 행의 raw bytepack 연초기준 초(알파 rep_sec와 동일 시계). 실패 시 NaN."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip():
                    p = line.split("\t", 3)
                    return float(DataIO._bytepack_year_seconds(float(p[0]), float(p[1])))
    except Exception:
        pass
    return float("nan")


def _results_to_knots(results, base2path, npix):
    """scan_directory results → (knot_sec[list], omr_rows[list]). 재스캔 없이 omr_d 재사용.
    knot 시각은 raw bytepack 연초기준 초(알파 rep_sec와 같은 시계, tz 변환 없음)."""
    knot_sec, omr_rows = [], []
    for r in results:
        path = base2path.get(r["filename"])
        if path is None:
            continue
        sec = _file_first_sec(path)
        od = np.asarray(r["omr_d"], dtype=float)
        if not np.isfinite(sec) or od.shape[0] != npix:
            continue
        knot_sec.append(sec)
        omr_rows.append(np.maximum(od, 1e-12))
    return knot_sec, omr_rows


def _compute_via_scandir(raw_dir, wave_nm, config, file_list, npix, parallel, progress_cb, verbose):
    """scan_directory(이제 data_io 단일파스+병렬)를 호출 → (knot_sec, omr_d) 추출.
    알파-R·R Trend 플롯이 같은 scan_directory 코어를 공유(단일 진실원천)."""
    files = _RT._resolve_files(raw_dir, file_list)
    base2path = {os.path.basename(f): f for f in files}
    import io
    import contextlib
    _ctx = contextlib.nullcontext() if verbose else contextlib.redirect_stdout(io.StringIO())
    with _ctx:
        results = _RT.scan_directory(
            raw_dir, wave_nm, file_list=file_list,
            col_press=config.col_press, col_temp=config.col_temp, ts_tz=_tz(config.ts_tz_hours),
            spec_start=config.spec_start, spec_end=config.spec_end,
            fit_window_nm=config.fit_window_nm, parallel=parallel, progress_cb=progress_cb)
    return _results_to_knots(results, base2path, npix)


def compute_rt_knots(raw_dir, wave_nm, config: RTConfig, file_list=None,
                     parallel=True, verbose=False, progress_cb=None):
    """채널 R(t) knot 계산. 반환: (knot_sec[N], omr_d[N,npix], wave_nm).

    scan_directory(data_io 단일파스+병렬)를 호출해 omr_d 추출 — 알파·R Trend 단일코어 공유.
    config:   RTConfig — 캠페인/채널명 무관. preset('cold') 등.
    parallel: scan_directory 병렬 파싱(6코어). progress_cb(done,total): 파싱 진행.
    knot_sec: raw bytepack 연초기준 초(시간 오름차순). omr_d: (1-R)/d(채널창 내 신뢰)."""
    wave_nm = np.asarray(wave_nm, dtype=float)
    npix = len(wave_nm)
    files = _RT._resolve_files(raw_dir, file_list)
    if not files:
        return np.array([]), np.zeros((0, npix)), wave_nm

    knot_sec, omr_rows = _compute_via_scandir(
        raw_dir, wave_nm, config, file_list, npix, parallel, progress_cb, verbose)

    if not knot_sec:
        return np.array([]), np.zeros((0, npix)), wave_nm
    order = np.argsort(knot_sec)
    knot_sec = np.asarray(knot_sec, dtype=np.float64)[order]
    omr_d = np.asarray(omr_rows, dtype=np.float64)[order]
    uniq = np.concatenate(([True], np.diff(knot_sec) > 0))   # 보간 단조 x
    return knot_sec[uniq], omr_d[uniq], wave_nm


def save_rt(path, knot_sec, omr_d, wave_nm, label="", config: RTConfig = None,
            processed_files=None):
    """R(t) knot을 npz로 저장. label/config는 출처 추적용(알파는 안 읽음).
    processed_files: 이미 처리된 파일명 목록 — 증분 추가 시 재처리 방지."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    cfg_json = json.dumps(asdict(config)) if config is not None else "{}"
    pf_json  = json.dumps(sorted(processed_files) if processed_files else [])
    np.savez_compressed(path, label=str(label), config=cfg_json,
                        processed_files_json=pf_json,
                        knot_sec=knot_sec, omr_d=omr_d, wave_nm=wave_nm)


def load_rt(path):
    """저장된 R(t) 로드. 반환 dict: knot_sec, omr_d, wave_nm (+ label, config 메타).
    알파 워커는 knot_sec/omr_d/wave_nm 만 사용한다."""
    z = np.load(path, allow_pickle=False)
    out = {"knot_sec": z["knot_sec"], "omr_d": z["omr_d"], "wave_nm": z["wave_nm"]}
    out["label"] = str(z["label"]) if "label" in z else ""
    try:
        out["config"] = json.loads(str(z["config"])) if "config" in z else {}
    except Exception:
        out["config"] = {}
    try:
        out["processed_files"] = (
            json.loads(str(z["processed_files_json"])) if "processed_files_json" in z else [])
    except Exception:
        out["processed_files"] = []
    return out


# ── 날짜 갭 탐지 ────────────────────────────────────────────────────────────

def find_date_gaps(npz_path):
    """npz의 knot_sec를 달력 날짜로 변환해 [first, last] 사이에서 **knot이 0개인 날**을
    찾는다(중간 빈 날 = R 보간으로만 채워지는 구간).

    sec→날짜는 data_io와 동일하게 datetime(year,1,1)+timedelta(seconds=sec).
    연도는 processed_files 파일명(YYYY-MM-DD)에서 취한다(bytepack은 연초기준).

    반환 dict {'missing':['YYYY-MM-DD',...], 'first':..., 'last':..., 'n_days':int}
    또는 None(판단 불가 / 갭 없음). 캠페인이 연말연시를 넘으면 부정확할 수 있음."""
    import re as _re
    from datetime import datetime as _dtm, timedelta as _tdl
    if not os.path.exists(npz_path):
        return None
    try:
        z = load_rt(npz_path)
    except Exception:
        return None
    ks = np.asarray(z.get("knot_sec", []), dtype=float)
    ks = ks[np.isfinite(ks)]
    if ks.size < 2:
        return None
    year = None
    for bn in z.get("processed_files", []):
        m = _re.search(r"(\d{4})-\d{2}-\d{2}", str(bn))
        if m:
            year = int(m.group(1)); break
    if year is None:
        return None
    base = _dtm(year, 1, 1)
    covered = sorted({(base + _tdl(seconds=float(s))).date() for s in ks})
    if len(covered) < 2:
        return None
    first, last = covered[0], covered[-1]
    cov_set = set(covered)
    missing, d = [], first
    while d <= last:
        if d not in cov_set:
            missing.append(d.strftime("%Y-%m-%d"))
        d += _tdl(days=1)
    if not missing:
        return None
    return {"missing": missing, "first": first.strftime("%Y-%m-%d"),
            "last": last.strftime("%Y-%m-%d"), "n_days": len(missing)}


def _knot_date_info(z):
    """knot_sec(연초기준 초) → npz가 실제로 담고 있는 날짜/시각 커버리지.

    반환 dict 또는 None(연도 판단 불가/빈 npz):
      first/last       : 커버된 첫·끝 날짜 'YYYY-MM-DD'
      first_dt/last_dt : 첫·끝 knot 시각 'YYYY-MM-DD HH:MM'
      n_days           : knot이 1개 이상 있는 distinct 날 수
      n_missing        : first~last 사이 knot 0개인 중간 빈 날 수
    sec→날짜는 data_io와 동일: datetime(year,1,1)+timedelta(seconds=sec).
    연도는 processed_files 파일명(YYYY-MM-DD)에서 취함(bytepack은 연초기준)."""
    import re as _re
    from datetime import datetime as _dtm, timedelta as _tdl
    ks = np.asarray(z.get("knot_sec", []), dtype=float)
    ks = ks[np.isfinite(ks)]
    if ks.size == 0:
        return None
    year = None
    for bn in z.get("processed_files", []):
        m = _re.search(r"(\d{4})-\d{2}-\d{2}", str(bn))
        if m:
            year = int(m.group(1)); break
    if year is None:
        return None
    base = _dtm(year, 1, 1)
    first_dt = base + _tdl(seconds=float(ks.min()))
    last_dt  = base + _tdl(seconds=float(ks.max()))
    covered  = sorted({(base + _tdl(seconds=float(s))).date() for s in ks})
    cov_set, miss, d = set(covered), 0, covered[0]
    while d <= covered[-1]:
        if d not in cov_set:
            miss += 1
        d += _tdl(days=1)
    return {"first": covered[0].strftime("%Y-%m-%d"),
            "last":  covered[-1].strftime("%Y-%m-%d"),
            "first_dt": first_dt.strftime("%Y-%m-%d %H:%M"),
            "last_dt":  last_dt.strftime("%Y-%m-%d %H:%M"),
            "n_days": len(covered), "n_missing": miss}


def verify_npz(npz_path, raw_dir, file_list=None):
    """npz 무결성 점검(읽기 전용·스캔 없음). raw 폴더 파일목록 + npz processed_files를
    비교해 '빈 날'과 '계산 안 된 파일'을 보고한다.

    반환 dict:
      exists       : npz 존재 여부
      n_knots      : 저장된 knot 수
      first/last   : knot 날짜 범위(YYYY-MM-DD) 또는 None
      gaps         : find_date_gaps 결과(빈 날) 또는 None
      n_raw        : raw 폴더의 .dat 수
      n_processed  : processed_files 수
      uncomputed   : raw엔 있으나 processed_files엔 없는 basename 목록(이름순)
    """
    report = {"exists": False, "n_knots": 0, "first": None, "last": None,
              "first_dt": None, "last_dt": None, "n_days": 0,
              "gaps": None, "n_raw": 0, "n_processed": 0, "uncomputed": []}

    all_files = _RT._resolve_files(raw_dir, file_list)
    report["n_raw"] = len(all_files)

    if not os.path.exists(npz_path):
        # npz 없으면 raw 전부가 '미계산'
        report["uncomputed"] = sorted(os.path.basename(f) for f in all_files)
        return report

    report["exists"] = True
    try:
        z = load_rt(npz_path)
    except Exception:
        return report

    ks = np.asarray(z.get("knot_sec", []), dtype=float)
    report["n_knots"] = int(np.isfinite(ks).sum())
    done = set(z.get("processed_files", []))
    report["n_processed"] = len(done)
    report["uncomputed"] = sorted(
        os.path.basename(f) for f in all_files if os.path.basename(f) not in done)

    # 날짜/시각 커버리지 — 갭 유무와 무관하게 항상 보고(깨끗한 npz도 범위 표시)
    info = _knot_date_info(z)
    if info:
        report.update({k: info[k] for k in
                       ("first", "last", "first_dt", "last_dt", "n_days")})

    g = find_date_gaps(npz_path)
    if g:
        report["gaps"] = g
    return report


# ── 증분 추가 유틸리티 ──────────────────────────────────────────────────────

def _file_has_he(path):
    """파일에 He 스캔(flag=510)이 있는지 빠르게 확인.
    전체 파싱 없이 flag 열만 검사하므로 파일당 수십 ms 수준."""
    from core.raw_parser import COL_FLAG, FLAG_HE
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                toks = line.split("\t", COL_FLAG + 2)
                if len(toks) <= COL_FLAG:
                    continue
                try:
                    if int(float(toks[COL_FLAG])) == FLAG_HE:
                        return True
                except ValueError:
                    continue
    except Exception:
        pass
    return False


def check_new_files(npz_path, raw_dir, file_list=None):
    """증분 추가 전 사전 검사: 새 파일 목록 + 각 파일의 He 플래그 존재 여부.

    반환: (new_files, he_map)
      new_files : 아직 처리되지 않은 파일 경로 목록 (이름순)
      he_map    : {basename: bool} — True=He 있음, False=없음
    processed 목록은 npz의 processed_files_json에서 읽는다. npz가 없으면 전체가 신규."""
    done_set = set()
    if os.path.exists(npz_path):
        try:
            z = np.load(npz_path, allow_pickle=False)
            if "processed_files_json" in z:
                done_set = set(json.loads(str(z["processed_files_json"])))
        except Exception:
            pass

    all_files = _RT._resolve_files(raw_dir, file_list)
    new_files = [f for f in all_files if os.path.basename(f) not in done_set]

    he_map = {os.path.basename(f): _file_has_he(f) for f in new_files}
    return new_files, he_map


def append_rt(npz_path, raw_dir, wave_nm, config: RTConfig, file_list=None,
              parallel=True, verbose=False, progress_cb=None):
    """기존 npz에 새 파일만 추가 계산해 머지 저장.

    이미 처리된 파일(processed_files_json)은 건너뛰고 신규 파일만 compute_rt_knots로
    처리한 뒤 기존 knot 배열과 시간순 머지해 재저장한다.

    반환: (n_new_knots, added_basenames)
      n_new_knots    : 이번에 새로 추가된 knot 수 (0이면 새 파일에서 유효 R 없음)
      added_basenames: 이번에 처리한 파일명 목록 (knot 생성 여부 무관)
    """
    wave_nm = np.asarray(wave_nm, dtype=float)
    npix    = len(wave_nm)

    # 기존 npz 로드
    ex_ks   = np.array([], dtype=np.float64)
    ex_od   = np.zeros((0, npix), dtype=np.float64)
    done_set = set()
    ex_label = config.label

    if os.path.exists(npz_path):
        try:
            ex = load_rt(npz_path)
            ex_ks    = ex["knot_sec"]
            ex_od    = ex["omr_d"]
            done_set = set(ex.get("processed_files", []))
            ex_label = ex.get("label") or ex_label
        except Exception as e:
            print(f"  [append_rt] failed to load existing npz -> creating new: {e}")

    all_files   = _RT._resolve_files(raw_dir, file_list)
    new_files   = [f for f in all_files if os.path.basename(f) not in done_set]
    new_basenames = [os.path.basename(f) for f in new_files]

    if not new_files:
        return 0, []

    # 새 파일만 compute
    new_ks, new_od, _ = compute_rt_knots(
        raw_dir, wave_nm, config, file_list=new_files,
        parallel=parallel, verbose=verbose, progress_cb=progress_cb)

    # 기존 npz와 시간순 머지+dedup (덮어쓰기 아님). processed_files는 시도한 전체 갱신.
    n_new, _ = _merge_knots_into_npz(
        npz_path, new_ks, new_od, wave_nm, config, new_basenames, ex_label=ex_label)
    return n_new, new_basenames


def _merge_knots_into_npz(npz_path, new_ks, new_od, wave_nm, config,
                          new_basenames, ex_label=None):
    """신규 (knot_sec, omr_d)를 기존 npz와 **시간순 머지 + 단조 dedup** 저장한다.
    기존 npz가 있으면 누적에 합치고, 없으면 새로 만든다 — **절대 덮어쓰지 않는다**.
    append_rt(신규파일 재계산)와 merge_results_into_npz(Start results 재사용)가 공유.
    반환: (n_new_knots, n_total_knots)."""
    wave_nm = np.asarray(wave_nm, dtype=float)
    npix    = len(wave_nm)

    ex_ks = np.array([], dtype=np.float64)
    ex_od = np.zeros((0, npix), dtype=np.float64)
    done_set = set()
    label = ex_label if ex_label is not None else config.label
    if os.path.exists(npz_path):
        try:
            ex = load_rt(npz_path)
            ex_ks    = ex["knot_sec"]
            ex_od    = ex["omr_d"]
            done_set = set(ex.get("processed_files", []))
            label    = ex.get("label") or label
        except Exception as e:
            print(f"  [merge] failed to load existing npz -> creating new: {e}")

    all_processed = sorted(done_set | set(new_basenames or []))
    new_ks = np.asarray(new_ks, dtype=np.float64)

    if len(new_ks) == 0:
        # 유효 R 없었어도 processed_files 갱신(재처리 방지)
        if len(ex_ks) > 0:
            save_rt(npz_path, ex_ks, ex_od, wave_nm,
                    label=label, config=config, processed_files=all_processed)
        return 0, len(ex_ks)

    new_od = np.asarray(new_od, dtype=np.float64)
    if len(ex_ks) > 0:
        merged_ks = np.concatenate([ex_ks, new_ks])
        merged_od = np.vstack([ex_od, new_od])
    else:
        merged_ks = new_ks
        merged_od = new_od

    order = np.argsort(merged_ks)
    merged_ks = merged_ks[order]
    merged_od = merged_od[order]
    uniq = np.concatenate(([True], np.diff(merged_ks) > 0))
    merged_ks = merged_ks[uniq]
    merged_od = merged_od[uniq]

    save_rt(npz_path, merged_ks, merged_od, wave_nm,
            label=label, config=config, processed_files=all_processed)
    return len(new_ks), len(merged_ks)


def merge_results_into_npz(npz_path, results, raw_dir, wave_nm, config, file_list=None):
    """Start가 이미 돌린 scan_directory **results를 재사용**해 npz에 증분 머지한다.
    핵심: scan_directory를 다시 부르지 않는다 — results 안의 omr_d를 그대로 쓴다(재스캔 0).
    기존 npz가 있으면 시간순 머지+dedup, 없으면 새로 생성. 절대 덮어쓰지 않는다.
    반환: (n_new_knots, n_total_knots)."""
    wave_nm = np.asarray(wave_nm, dtype=float)
    npix    = len(wave_nm)
    if not results:
        return 0, 0

    files = _RT._resolve_files(raw_dir, file_list)
    base2path = {os.path.basename(f): f for f in files}
    ks, od_rows = _results_to_knots(results, base2path, npix)
    new_basenames = [r["filename"] for r in results if r.get("filename")]

    if not ks:
        return _merge_knots_into_npz(npz_path, np.array([]), None, wave_nm,
                                     config, new_basenames)

    order  = np.argsort(ks)
    new_ks = np.asarray(ks, dtype=np.float64)[order]
    new_od = np.asarray(od_rows, dtype=np.float64)[order]
    uniq   = np.concatenate(([True], np.diff(new_ks) > 0))
    return _merge_knots_into_npz(npz_path, new_ks[uniq], new_od[uniq], wave_nm,
                                 config, new_basenames)
