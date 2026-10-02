"""vigil/run_vigil.py — Vigil 진입점 (M0 유입 감시 + M1 HK + M2 R + M3 농도 + 대시보드).

사용:
    python vigil/run_vigil.py --dir "D:\\CAESAR raw\\2026-yeosu"
    python -m vigil.run_vigil --dir ... --poll-sec 1.0

DAQ PC에서 LabVIEW와 나란히 돌리는 걸 전제로 한다(설계문서 §0-A.1) — raw를
읽기만 하고 절대 쓰지 않으며(§2 원칙2), 자기 상태(커서·로그)는 `--state-dir`
(기본 레포의 `vigil_state/`)에만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

# WMI 우회 — main.py 와 같은 이유(Python 3.13 platform.machine() 이 멈춘 WMI 에 묶인다).
# platform 이 임포트되기 전이어야 한다.
sys.modules.setdefault("_wmi", None)

from collections import deque
from datetime import datetime

# LabVIEW 와 같은 PC — BLAS 가 코어를 다 잡지 않게 1 스레드로(설계문서 §8 CPU 예산).
# numpy/scipy 가 임포트되기 **전**이어야 먹는다(아래 vigil.monitors 가 numpy 를 끌어온다).
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from vigil.alert_engine import OK, P0, P1, P2, SKIP, aggregate, worse
from vigil.ingest_cursor import IngestCursor
from vigil.monitors.hk_monitor import evaluate_hk
from vigil.monitors.liveness_monitor import DEFAULT_GRACE_SEC, check_liveness, latest_arrival
from vigil.monitors.clock_monitor import ClockMonitor, RowTimeMonitor, offset_seconds

HEADER_ONLY_SEC = 60.0      # newest file holds only its header row this long after the last write -> P2
CLOCK_FRESH_SEC = 120.0    # 시각 차이 표본: 이 안에 쓰인 파일의 끝 행만(vigil/monitors/clock_monitor.py)
from vigil.monitors.lamp_monitor import LampMonitor
from vigil.monitors.r_monitor import RMonitor
from vigil.profile import DEFAULT_PROFILE_DIR, ProfileSet
from vigil.state_log import StateLog
from vigil.watcher import DEFAULT_BACKLOG_AGE_SEC, DEFAULT_MAX_BYTES_PER_TICK, Watcher
from vigil.datapaths import rebase, rebase_fitset_channel
from vigil.record import STATUS_CODE, MinuteRecorder

log = logging.getLogger("vigil")

TREND_MAXLEN = 720   # 그래프 표시용 최근 N점 — HK·농도 10 s 간격이면 2 h, R 은 교정 720회
# HK 는 매 행(1 s) 오는데 그래프는 열화 추세를 보는 용도라 10 s 에 한 점이면 충분하다. 예전엔 매 행을
# 넣어 300점 = 5분만 보였다(몇 시간에 걸친 온도 드리프트가 안 보였다). 판정은 매 행 그대로.
HK_TREND_EVERY_SEC = 10.0
ALARM_HISTORY_MAX = 500
# 이만큼 새 행이 없는 파일은 파일별 상태(표·HK 판정)에서 뺀다. 1 h 파일 rollover 뒤 지난 파일의
# P1 이 종합 상태를 영원히 붙잡고, 표가 캠페인 내내 늘어나던 것(2026-10-01). 측정 정지 자체는
# liveness(전체 최신 행 기준)가 따로 잡으므로 여기서 빼도 숨겨지지 않는다.
RETIRE_AFTER_SEC = 600.0
CURSOR_SAVE_INTERVAL_SEC = 5.0
# A file whose rows no profile accepts is reported once it has this many (its header row alone is
# unrouted too, and the first data row may come a tick later).
UNKNOWN_LAYOUT_MIN_ROWS = 3


def _grace_sec_for(profiles: ProfileSet, routed_ids: set) -> float:
    """지금까지 라우팅된 프로파일들의 liveness_grace_sec 중 최솟값(가장 민감한 쪽).
    아직 아무 프로파일도 안 붙었으면 DEFAULT_GRACE_SEC."""
    vals = [p.cadence.liveness_grace_sec for p in profiles.profiles
            if p.profile_id in routed_ids and p.cadence.liveness_grace_sec is not None]
    return min(vals) if vals else DEFAULT_GRACE_SEC


def _hk_value(prof, row, keys):
    """keys(채널 cavity 우선순위 목록)에서 처음으로 유효한 물리값. 없으면 NaN(R·농도 계산이 실패 처리).
    고르는 규칙은 Augur 와 같은 core.profile.HK.first_valid — 채널 정의 단일 출처(2026-10-02)."""
    return prof.hk.first_valid(row, keys) if keys else float("nan")


class VigilApp:
    """감시 루프 상태 컨테이너. QTimer가 매 tick `.tick()`을 부른다."""

    def __init__(self, watch_dir, profile_dir: str, state_dir: str,
                 dashboard=None, max_bytes_per_tick: int = DEFAULT_MAX_BYTES_PER_TICK,
                 backlog_age_sec=DEFAULT_BACKLOG_AGE_SEC, retire_after_sec: float = RETIRE_AFTER_SEC,
                 cursor_save_interval_sec: float = CURSOR_SAVE_INTERVAL_SEC):
        """watch_dir 은 None 이어도 된다 — 대시보드의 폴더 버튼으로 나중에 정한다(set_watch_dir)."""
        self.profile_dir = profile_dir
        # 이 PC 에 불러온 미션 패키지 — 상태 폴더 아래(프로그램 폴더는 쓰기 금지일 수 있다)
        self.missions_dir = os.path.join(state_dir, "missions")
        self.cursor = IngestCursor(os.path.join(state_dir, "cursors.json"))
        self.state_log = StateLog(os.path.join(state_dir, "status.jsonl"))
        self.profiles = None
        self._load_profiles()
        self._watcher_kw = dict(max_bytes_per_tick=max_bytes_per_tick, backlog_age_sec=backlog_age_sec,
                                cursor_save_interval_sec=cursor_save_interval_sec)
        self.retire_after_sec = retire_after_sec
        self.paused = False                # 대시보드 Stop — 정지 중엔 tick 이 아무것도 읽지 않는다
        self._tick_errors = 0              # 연속 tick 예외 수(성공하면 0)
        self._dropped_rows = 0             # rows lost to those failures (cursor already past them)
        self._tick_rows = (0, 0)           # (rows processed, rows polled) in the current tick
        self.dashboard = dashboard
        self._wavecal_cache: dict = {}     # {wavecal_path: np.ndarray|None} — 파일당 1회만 로드
        self._fitset_cache: dict = {}      # {fitset_path: dict} — FitSet json 1회만 로드
        # 다른 PC 의 Augur 출력 폴더 — 프로파일·FitSet 의 절대경로가 없을 때 그 아래에서 찾는다(vigil/datapaths.py)
        self.data_root = None
        # 1분 요약 기록(vigil/record.py) — 감시기가 이미 낸 최신값만 복사, 새 계산 없음
        self.recorder = MinuteRecorder(state_dir)
        self.watch_dir = None
        self.watcher = None
        self._reset_state()
        if watch_dir:
            self.set_watch_dir(watch_dir)

    def _load_profiles(self) -> None:
        """기본 + 프로그램 폴더의 미션 + 이 PC 에 불러온 미션 패키지. 어느 채널 정의로 감시하나 — 측정 PC 는
        USB 로 받아 git 으로 확인할 수 없으니 파일·판·내용 해시를 남긴다(Augur 알파 헤더 raw_layout 의
        profile= 와 같은 문자열 — 둘을 대조하면 된다)."""
        from core.mission_package import installed_mission_files
        from core.profile import load_profiles
        self.profiles = ProfileSet(load_profiles(self.profile_dir,
                                                 extra_paths=installed_mission_files(self.missions_dir)))
        _profs = [p.provenance for p in self.profiles.profiles]
        log.info("profiles: %s", ", ".join(_profs))
        self.state_log.append("CONTROL", f"profiles loaded: {', '.join(_profs)}",
                              kind="profiles", profiles=_profs)
        # Loader-time warnings (shown in the dashboard Log at startup, kept in status.jsonl).
        import importlib.util
        self.profile_warnings = []
        if importlib.util.find_spec("jsonschema") is None:
            self.profile_warnings.append(
                "jsonschema not installed — profiles get only the required-key and meaning checks; "
                "a misspelled optional key (e.g. 'alrt') is ignored")
        for g in self.profiles.ambiguous_groups():
            self.profile_warnings.append(
                f"profiles {', '.join(g)} match the same files (same column count, overlapping dates, "
                f"no filename_glob) — '{g[0]}' wins silently; give them date_range or filename_glob")
        for w in self.profile_warnings:
            log.warning(w)
            self.state_log.append(P2, w, kind="profiles")

    def load_mission(self, pkg_dir: str) -> list:
        """미션 패키지(Augur 'Export mission for Vigil')를 검사·설치하고 프로파일을 다시 읽는다 → 새로 들어온
        미션 출처 문자열들. 검사 실패(파일 누락·내용 변경)·날짜 겹침이면 ValueError — 아무것도 안 바꾼다."""
        from core.mission_package import install_package, overlap_problems, read_manifest
        man = read_manifest(pkg_dir)
        probs = overlap_problems(pkg_dir, self.profile_dir, self.missions_dir)
        if probs:
            raise ValueError("; ".join(probs))
        dst = install_package(pkg_dir, self.missions_dir)
        self._load_profiles()
        if self.watcher is not None:
            self.watcher.profiles = self.profiles
            self.watcher._profile_cache.clear()
            self.watcher.date_excluded.clear()
            self._reset_state()
        got = [p.provenance for p in self.profiles.profiles
               if p.source_path and os.path.dirname(os.path.abspath(p.source_path)) == os.path.abspath(dst)]
        msg = f"Mission loaded: {man['name']} → {', '.join(got)}"
        log.info(msg)
        self.state_log.append("CONTROL", msg, kind="mission", mission=man["name"], profiles=got)
        if self.dashboard is not None:
            self.dashboard.log_line(msg)
        return got

    def set_watch_dir(self, watch_dir: str) -> None:
        """감시 폴더를 정하거나 바꾼다(대시보드 폴더 버튼). 커서는 파일 절대경로 키라 그대로 이어지고,
        이전 폴더의 파일별 상태·감시기 기준선·추세는 비운다 — 다른 계기·캠페인의 데이터와 섞이지 않게."""
        if self.watcher is not None:
            self.cursor.flush()
        self.watch_dir = watch_dir
        self.watcher = Watcher(watch_dir, self.profiles, self.cursor, **self._watcher_kw)
        self._reset_state()
        msg = f"Watch folder: {watch_dir}"
        log.info(msg)
        self.state_log.append("CONTROL", msg, kind="watch_dir", watch_dir=watch_dir)

    def _reset_state(self) -> None:
        """폴더별 상태 — 처음 만들 때와 폴더를 바꿀 때."""
        self._tick_errors = 0
        self._backlog_logged = False
        self._date_excluded_logged: set = set()
        self._unknown_logged: set = set()
        self._auto_lit: dict = {}          # {(file, profile_id, channel_id): 빛이 들어오는 auto 블록인가}
        self._was_catching_up = False
        self._last_arrival = None
        self._waiting_since = datetime.now()   # liveness: no row since this -> P0 after a limit
        self._hk_latest: dict = {}         # {(profile_id, field_key): (value, severity, datetime)} — 현재 값 카드
        self._hk_latch: dict = {}          # {profile_id: {field_key: severity}} — HK band hysteresis
        self._hk_trend_t: dict = {}        # {(profile_id, field_key): 마지막으로 그래프에 넣은 시각}
        self.alarms: list = []             # 경보 이력 [{start, end, source, level, msg}] — 최근 것이 끝
        self._open_alarms: dict = {}       # {source: 위 dict} — 진행 중          # 전체 최신 관측 벽시계 시각
        self._files_seen: dict = {}        # {path: arrival_time}
        self._routed_ids: set = set()
        self._hk_status: dict = {}         # {path: (status, msg, metrics)} — 최신 HK 판정
        self._hk_last_status: dict = {}    # {path: status} — 로그 중복 방지용
        self._r_monitors: dict = {}        # {(profile_id, channel_id): RMonitor}
        self._r_by_channel: dict = {}      # {(profile_id, channel_id): (status, msg, metrics)}
        self._r_status: dict = {}          # {path: (status, msg, metrics)} — 파일의 채널들 중 worst
        self._r_last_status: dict = {}     # {path: status} — 로그 중복 방지용
        self._lamp_monitors: dict = {}     # {(profile_id, channel_id): LampMonitor}
        self._lamp_by_channel: dict = {}
        # 행 시각 vs PC 시계 — 계기(기본 프로파일)마다. 핫·콜드는 다른 DAQ PC 일 수 있다(2026-05 핫만 9 h).
        self._clock_monitors: dict = {}    # {instrument: ClockMonitor}
        self._rowtime_monitors: dict = {}  # {instrument: RowTimeMonitor} — backward/jump/rollover
        self._rowtime_last: dict = {}      # {instrument: status} — log on change only
        self._clock_by_inst: dict = {}     # {instrument: (status, msg, metrics)}
        self._lamp_status: dict = {}       # {path: (status, msg, metrics)} — 파일의 채널들 중 worst
        self._lamp_last_status: dict = {}
        self._conc_monitors: dict = {}     # {(profile_id, channel_id): ConcMonitor}
        self._conc_by_channel: dict = {}   # {(profile_id, channel_id): (status, msg, metrics)}
        self._conc_status: dict = {}       # {path: (status, msg, metrics)} — 파일의 채널들 중 worst
        self._conc_last_status: dict = {}  # {path: status} — 로그 중복 방지용
        self._last_status = None           # 종합(overall) 상태 — 로그 중복 방지용
        self._conc_trend: dict = {}   # {(profile_id,ch_id): deque[(datetime, {gas: ppb})]}
        self._r_trend: dict = {}      # {(profile_id,ch_id): deque[(datetime, float, baseline)]}
        self._hk_trend: dict = {}     # {(profile_id,field_key): deque[(datetime,float)]}
        self._trend_meta: dict = {}   # 채널/필드 메타(label, unit, min/max, warn/alarm) — 1회만 채움

    def set_data_root(self, path) -> None:
        """Augur 데이터 폴더(대시보드 버튼). 바꾸면 농도·R 감시기를 새 경로로 다시 만든다."""
        self.data_root = path or None
        self._wavecal_cache.clear()
        self._fitset_cache.clear()
        for d in (self._r_monitors, self._r_by_channel, self._r_status, self._r_last_status,
                  self._conc_monitors, self._conc_by_channel, self._conc_status, self._conc_last_status):
            d.clear()
        msg = f"Augur data folder: {path or '(not set)'} — concentration/R monitors re-initialise"
        log.info(msg)
        self.state_log.append("CONTROL", msg, kind="data_root", data_root=path)
        if self.dashboard is not None:
            self.dashboard.log_line(msg)

    def _get_wavecal(self, path):
        path = rebase(path, self.data_root)
        if path not in self._wavecal_cache:
            from tools.optimize_params import load_wavecal   # 기존 로더 재사용(3번째 사본 안 만듦)
            self._wavecal_cache[path] = load_wavecal(path)
        return self._wavecal_cache[path]

    def _get_fitset_channel(self, cfg):
        fp = rebase(cfg.fitset_path, self.data_root)
        scen = self._fitset_cache.get(fp)
        if scen is None:
            if not os.path.exists(fp):
                raise FileNotFoundError(f"FitSet not found: {cfg.fitset_path} — set the Augur data folder")
            from core.mission_package import absolutize_fitset
            # 미션 패키지의 FitSet 은 패키지 상대경로 — 그 FitSet 폴더 기준으로 푼다
            scen = absolutize_fitset(json.load(open(fp, encoding="utf-8")), os.path.dirname(os.path.abspath(fp)))
            self._fitset_cache[fp] = scen
        from vigil.monitors.conc_monitor import pick_fitset_channel
        return rebase_fitset_channel(pick_fitset_channel(scen, cfg.wl_dir, getattr(cfg, "fitset_channel", None)),
                                     self.data_root)

    def _observe_reflectance(self, prof, ev, now) -> None:
        """이 행의 프로파일에 reflectance 설정이 있는 signal 채널마다 RMonitor.observe.
        새 R이 나온 채널이 있으면 그 파일의 combined 상태를 재계산·로그(변경시만)."""
        touched = False
        for ch in prof.signal_channels():
            if ch.reflectance is None:
                continue
            key = (prof.profile_id, ch.id)
            rm = self._r_monitors.get(key)
            if rm is None:
                rc = ch.reflectance
                rm = RMonitor(wave_nm=self._get_wavecal(rc.wavecal_path),
                              cavity_len_cm=rc.cavity_len_cm, rl_factor=rc.rl_factor,
                              roi_nm=rc.roi_nm, warn_drop=rc.warn_drop, alarm_drop=rc.alarm_drop)
                self._r_monitors[key] = rm
                self._trend_meta[key] = {"label": ch.label or ch.id,
                                         "warn_drop": rc.warn_drop, "alarm_drop": rc.alarm_drop}
            spectrum = ch.slice(ev.row)
            temp_c = _hk_value(prof, ev.row, ch.temp_keys(ch.reflectance))
            press_mbar = _hk_value(prof, ev.row, ch.pressure_keys(ch.reflectance))
            result = rm.observe(ev.role, spectrum, temp_c, press_mbar)
            if result is not None:
                status, msg, metrics = result
                self._r_by_channel[key] = (status, f"[{ch.label or ch.id}] {msg}", metrics)
                self._r_trend.setdefault(key, deque(maxlen=TREND_MAXLEN)).append(
                    (now, metrics.get("R"), metrics.get("baseline")))
                touched = True
        if touched:
            self._combine_channels(prof, ev, self._r_by_channel, self._r_status,
                                   self._r_last_status, kind="r", label="R")

    def _combine_channels(self, prof, ev, by_channel, status, last_status, kind, label) -> None:
        """채널별 최신 판정 → 그 파일의 worst 로 합치고, 상태가 바뀔 때만 로그."""
        entries = [by_channel[(prof.profile_id, ch.id)]
                  for ch in prof.channels
                  if (prof.profile_id, ch.id) in by_channel]
        combined_status = SKIP
        for s, _m, _mt in entries:
            combined_status = worse(combined_status, s)
        combined_msg = "; ".join(m for _s, m, _mt in entries)
        status[ev.file] = (combined_status, combined_msg, {})
        if last_status.get(ev.file) != combined_status:
            self.state_log.append(combined_status, combined_msg, file=ev.file, kind=kind)
            if self.dashboard is not None:
                self.dashboard.log_line(f"[{os.path.basename(ev.file)}] {label} {combined_status}: {combined_msg}")
        last_status[ev.file] = combined_status

    def _active_channels(self, prof, ev) -> list:
        """감시할 스펙트럼 블록 — signal + **빛이 들어오는** auto 블록(기본 프로파일). auto 는 파일마다
        첫 행의 블록 최대값으로 한 번 판정한다(≥ autodetect.signal_min_max, 없으면 data_io 와 같은 5000) —
        어두운 블록의 바닥 잡음으로 램프 경보를 내지 않게."""
        out = []
        thr = prof.autodetect.signal_min_max if prof.autodetect is not None else 5000.0
        for ch in prof.channels:
            if ch.is_signal:
                out.append(ch)
            elif ch.is_auto and ch.columns is not None:
                key = (ev.file, prof.profile_id, ch.id)
                lit = self._auto_lit.get(key)
                if lit is None:
                    try:
                        lit = max(float(v) for v in ch.slice(ev.row)) >= thr
                    except (ValueError, TypeError):
                        lit = False
                    self._auto_lit[key] = lit
                if lit:
                    out.append(ch)
        return out

    def _observe_lamp(self, prof, ev) -> None:
        """모든 signal 채널의 ZA 블록 세기(램프 헬스). 설정 없이 기본 문턱으로 돈다."""
        # ponytail: 문턱은 모듈 상수(2026 여수 실측). 캠페인별로 달라지면 프로파일 키로 뺄 것.
        touched = False
        for ch in self._active_channels(prof, ev):
            key = (prof.profile_id, ch.id)
            lm = self._lamp_monitors.setdefault(key, LampMonitor())
            result = lm.observe(ev.role, ch.slice(ev.row))
            if result is not None:
                status, msg, metrics = result
                self._lamp_by_channel[key] = (status, f"[{ch.label or ch.id}] {msg}", metrics)
                touched = True
        if touched:
            self._combine_channels(prof, ev, self._lamp_by_channel, self._lamp_status,
                                   self._lamp_last_status, kind="lamp", label="lamp")

    def _observe_concentration(self, prof, ev, now) -> None:
        """이 행의 프로파일에 concentration 설정이 있는 signal 채널마다 ConcMonitor.observe.
        새 농도가 나온 채널이 있으면 그 파일의 combined 상태를 재계산·로그(변경시만)."""
        touched = False
        for ch in prof.signal_channels():
            if ch.concentration is None:
                continue
            key = (prof.profile_id, ch.id)
            cm = self._conc_monitors.get(key)
            if cm is None:
                # 여기서 처음 임포트한다 — scipy·피팅 엔진을 끌어와 ~1 s. 모듈 최상단에 두면
                # 스플래시가 뜨기도 전에 그만큼 멈춘다(main 이 스레드로 미리 데운다).
                from vigil.monitors.conc_monitor import ConcMonitor
                try:
                    fit_ch = self._get_fitset_channel(ch.concentration)
                    cm = ConcMonitor(fit_ch, ch.concentration)
                except Exception as e:                # noqa: BLE001
                    self._conc_by_channel[key] = (
                        P1, f"[{ch.label or ch.id}] init failed: {e}", {})
                    touched = True
                    continue
                self._conc_monitors[key] = cm
                self._trend_meta[key] = {"label": ch.label or ch.id, "target": ch.concentration.target,
                                         "conc_min_ppb": ch.concentration.conc_min_ppb,
                                         "conc_max_ppb": ch.concentration.conc_max_ppb}
            spectrum = ch.slice(ev.row)
            temp_c = _hk_value(prof, ev.row, ch.temp_keys(ch.concentration))
            press_mbar = _hk_value(prof, ev.row, ch.pressure_keys(ch.concentration))
            # (1-R)/d from the same channel's RMonitor (it ran first in this tick, so this
            # row's calibration is already in). No reflectance config -> None -> SKIP.
            rm = self._r_monitors.get(key)
            omr_d = rm.omr_d if rm is not None else None
            rl = ch.reflectance.rl_factor if ch.reflectance is not None else 1.0
            result = cm.observe(ev.role, spectrum, temp_c, press_mbar, omr_d=omr_d, rl=rl,
                                row_time=ev.row_time)
            if result is not None:
                status, msg, metrics = result
                self._conc_by_channel[key] = (status, f"[{ch.label or ch.id}] {msg}", metrics)
                self._conc_trend.setdefault(key, deque(maxlen=TREND_MAXLEN)).append(
                    (now, metrics.get("conc_all_ppb", {})))
                touched = True
        if not touched:
            return
        entries = [self._conc_by_channel[(prof.profile_id, ch.id)]
                  for ch in prof.signal_channels()
                  if (prof.profile_id, ch.id) in self._conc_by_channel]
        combined_status = SKIP
        for s, _m, _mt in entries:
            combined_status = worse(combined_status, s)
        combined_msg = "; ".join(m for _s, m, _mt in entries)
        self._conc_status[ev.file] = (combined_status, combined_msg, {})
        if self._conc_last_status.get(ev.file) != combined_status:
            self.state_log.append(combined_status, combined_msg, file=ev.file, kind="conc")
            if self.dashboard is not None:
                self.dashboard.log_line(
                    f"[{os.path.basename(ev.file)}] Conc {combined_status}: {combined_msg}")
        self._conc_last_status[ev.file] = combined_status

    def _log_ingest_state(self) -> None:
        """백로그 건너뜀(시작 1회)과 따라잡기 시작/끝을 로그에 남긴다 — 조용히 버리지 않는다."""
        w = self.watcher
        for path, ids in list(w.date_excluded.items()):
            if path in self._date_excluded_logged:
                continue
            self._date_excluded_logged.add(path)
            base = w._profile_cache.get(path)
            if base is not None and not base.is_mission:
                msg = (f"No mission for {os.path.basename(path)}: its date is outside {', '.join(ids)} "
                       f"(different fibre/channel layout) — monitoring with base profile "
                       f"{base.profile_id}: HK, block brightness and data flow only, NO concentration/R. "
                       f"Load the mission for this layout")
            else:
                msg = (f"NOT monitored: {os.path.basename(path)} has the column count of {', '.join(ids)}, "
                       f"but its file date is outside that profile's date_range (different fibre/channel "
                       f"layout) — add a profile for this layout")
            log.warning(msg)
            self.state_log.append(P2, msg, kind="ingest", file=path, profiles=ids)
            if self.dashboard is not None:
                self.dashboard.log_line(msg)
        new = sorted(p for p, (n, _nc) in w.unknown_layout.items()
                     if n >= UNKNOWN_LAYOUT_MIN_ROWS and p not in self._unknown_logged)
        if new:
            self._unknown_logged.update(new)
            ncols = sorted({w.unknown_layout[p][1] for p in new})
            names = ", ".join(os.path.basename(p) for p in new[:5]) + (" …" if len(new) > 5 else "")
            msg = (f"NOT monitored: {len(new)} file(s) with an unknown layout "
                   f"({', '.join(map(str, ncols))} columns — no profile matches): {names}")
            log.warning(msg)
            self.state_log.append(P2, msg, kind="ingest", files=new[:50], n_columns=ncols)
            if self.dashboard is not None:
                self.dashboard.log_line(msg)
        if not self._backlog_logged:
            self._backlog_logged = True
            n, nbytes = w.skipped_backlog
            if n:
                msg = (f"On start, skipped {n} old raw files ({nbytes / 1e6:.0f} MB) and began at their end "
                       f"(no cursor, unchanged for over {w.backlog_age_sec / 60:.0f} min — past data is Augur's job)")
                self.state_log.append(OK, msg, kind="ingest", skipped_files=n, skipped_bytes=nbytes)
                if self.dashboard is not None:
                    self.dashboard.log_line(msg)
        if w.catching_up != self._was_catching_up:
            self._was_catching_up = w.catching_up
            msg = (f"Catching up on backlog raw ({w.max_bytes_per_tick / 2**20:.0f} MB per tick)"
                   if w.catching_up else "Caught up — live")
            self.state_log.append(OK, msg, kind="ingest")
            if self.dashboard is not None:
                self.dashboard.log_line(msg)

    def pause(self, reason: str = "Monitoring paused (user Stop)") -> None:
        """대시보드 Stop. raw 는 계속 쌓이고 커서는 그 자리에 멈춘다 — resume 하면 밀린 줄부터
        (읽기 상한대로 나눠) 이어 읽는다. 정지 즉시 커서를 저장한다(정지한 채 창을 닫아도 안전)."""
        if self.paused:
            return
        self.paused = True
        self.cursor.flush()
        self._note_control(reason)

    def resume(self) -> None:
        if not self.paused:
            return
        self.paused = False
        self._waiting_since = datetime.now()   # paused time is not "no raw arriving"
        self._note_control("Monitoring resumed (user Start) — reading from the backlog onward")

    def _note_control(self, msg: str) -> None:
        log.info(msg)
        self.state_log.append("CONTROL", msg, kind="control")
        if self.dashboard is not None:
            self.dashboard.log_line(msg)

    def tick(self) -> None:
        """QTimer 슬롯. PyQt6 는 슬롯에서 새어 나간 예외에 프로세스를 abort 하므로, 여기서 다
        받아 로그에 남기고 배지에 띄운 뒤 다음 tick 을 계속 돈다 — 감시기가 조용히 사라지는
        것이 가장 나쁜 실패다. 정지(pause) 중이거나 아직 폴더가 없으면 아무것도 하지 않는다."""
        if self.paused or self.watcher is None:
            return
        self._tick_rows = (0, 0)
        try:
            self._tick()
        except Exception as e:                # noqa: BLE001
            self._tick_errors += 1
            # The watcher's cursor is already past this tick's rows: the ones after the failing row are
            # never re-read. Say how many (not re-reading them is deliberate — a row that always fails
            # would wedge ingest).
            done, total = self._tick_rows
            dropped = total - done
            self._dropped_rows += dropped
            log.exception("tick failed (%d in a row) — %d of %d rows of this tick not monitored",
                          self._tick_errors, dropped, total)
            msg = f"Vigil internal error, {self._tick_errors} in a row: {type(e).__name__}: {e}"
            if dropped:
                msg += f" — {self._dropped_rows} raw row(s) skipped by monitoring so far"
            if self._tick_errors == 1:        # 연속 실패의 첫 번만 상태 로그에(매초 쌓이지 않게)
                self.state_log.append(P1, msg, kind="internal")
            if self.dashboard is not None:
                try:
                    self.dashboard.set_status(P1, msg)
                    if self._tick_errors == 1:
                        self.dashboard.log_line(msg)
                except Exception:             # noqa: BLE001
                    log.exception("failed to report the error as well")
        else:
            if self._tick_errors:
                log.info("tick recovered (after %d consecutive failures, %d rows not monitored)",
                         self._tick_errors, self._dropped_rows)
                self.state_log.append(OK, f"Vigil internal error recovered (after {self._tick_errors}; "
                                          f"{self._dropped_rows} raw row(s) were not monitored)",
                                      kind="internal", dropped_rows=self._dropped_rows)
            self._tick_errors = 0
            self._dropped_rows = 0

    def shutdown(self) -> None:
        """종료 시 미저장 커서를 쓴다(저장 간격 때문에 마지막 몇 초가 메모리에만 있을 수 있다)."""
        self.cursor.flush()

    def _observe_clock(self, events) -> None:
        """행 시각 vs PC 시계(vigil/monitors/clock_monitor.py). 표본은 이번 poll 에서 **끝까지 읽은 파일의
        마지막 행**만 — 시작·일시정지 뒤 밀린 행(원래 오래된 행)을 '늦게 도착'으로 보지 않는다. 계기가 멈춰
        있으면 그 끝 행도 오래돼 지연으로 잡힌다."""
        last = {}
        for ev in events:
            if ev.profile_id and ev.row_time is not None:
                last[ev.file] = ev
        for path, ev in last.items():
            # 끝까지 읽었고 **계기가 방금도 쓰고 있는** 파일만 — 시작 때 끝까지 읽은 지난 시간 파일(이미
            # 닫힌 파일)의 끝 행은 원래 오래됐다. 계기가 완전히 멈춘 경우는 liveness 가 잡는다.
            age = self.watcher.write_age(path)
            if not self.watcher.at_end(path) or age is None or age > CLOCK_FRESH_SEC:
                continue
            prof = self.profiles.by_id(ev.profile_id)
            inst = (prof.base_id or prof.profile_id) if prof is not None else ev.profile_id
            off = offset_seconds(ev.row_time, ev.arrival_time)
            if off is None:
                continue
            res = self._clock_monitors.setdefault(inst, ClockMonitor()).observe(off)
            if res is None:
                continue
            prev = self._clock_by_inst.get(inst)
            self._clock_by_inst[inst] = res
            if prev is None or prev[0] != res[0]:
                self.state_log.append(res[0], f"[{inst}] {res[1]}", kind="clock", instrument=inst,
                                      offset_s=res[2].get("offset_s"))
                if self.dashboard is not None:
                    self.dashboard.log_line(f"[clock {inst}] {res[0]}: {res[1]}")

    def _files_between(self, a: str, b: str) -> bool:
        """Any watched file sorting strictly between a and b (same order as the watcher's list)."""
        import bisect
        paths = self.watcher._paths
        return bisect.bisect_right(paths, a) < bisect.bisect_left(paths, b)

    def _rowtime_results(self, now) -> list:
        """Row-time sequence per instrument (RowTimeMonitor) + a newest file that holds only its header
        row (DAQ wrote the header at rollover, then nothing) — logged when the status changes."""
        out = []
        for inst, mon in self._rowtime_monitors.items():
            res = mon.status(now)
            if res is not None:
                out.append((f"rowtime:{inst}", *res))
        w = self.watcher
        if w is not None and w._files:
            newest = max(w._files, key=lambda p: w._files[p][1])
            n = w.unknown_layout.get(newest, (0,))[0]
            age = w.write_age(newest)
            if 0 < n < UNKNOWN_LAYOUT_MIN_ROWS and w.at_end(newest) and age is not None and age > HEADER_ONLY_SEC:
                out.append(("ingest:header_only", P2,
                            f"{os.path.basename(newest)} holds only its header row ({age:.0f} s since the last "
                            f"write) — DAQ stuck right after the rollover?", {"file": newest}))
        for name, st, msg, mt in out:
            if self._rowtime_last.get(name) != st:
                self.state_log.append(st, msg, kind="rowtime", source=name, **{k: v for k, v in mt.items()
                                                                                 if k != "file"})
                if self.dashboard is not None and st != OK:
                    self.dashboard.log_line(f"[{name}] {st}: {msg}")
            self._rowtime_last[name] = st
        return out

    def _retire_stale_files(self, now: datetime) -> None:
        stale = [p for p, t in self._files_seen.items()
                 if (now - t).total_seconds() > self.retire_after_sec]
        for p in stale:
            for d in (self._files_seen, self._hk_status, self._hk_last_status,
                      self._r_status, self._r_last_status, self._lamp_status,
                      self._lamp_last_status, self._conc_status, self._conc_last_status,
                      self.watcher._profile_cache):
                d.pop(p, None)
            log.info("retired file (no new rows for %.0f min): %s", self.retire_after_sec / 60, p)

    # ── 경보 이력·현재 값·1분 기록 — 감시기가 이미 낸 판정·값을 모을 뿐, 새 계산 없음 ──────────
    def _update_alarms(self, results, now) -> None:
        """판정 항목(source)별로 P2/P1/P0 이 시작·해소된 시각을 이력으로 남긴다(같은 경보는 한 줄)."""
        alarming = {}
        for name, status, msg, _mt in results:
            if status in (P0, P1, P2):
                alarming[name] = (status, msg)
        for name, (status, msg) in alarming.items():
            a = self._open_alarms.get(name)
            if a is None:
                a = {"start": now, "end": None, "source": name, "level": status, "msg": msg}
                self._open_alarms[name] = a
                self.alarms.append(a)
                del self.alarms[:-ALARM_HISTORY_MAX]
            else:
                if worse(a["level"], status) == status:
                    a["level"] = status            # 진행 중 가장 심했던 등급
                a["msg"] = msg
        for name in [n for n in self._open_alarms if n not in alarming]:
            self._open_alarms.pop(name)["end"] = now

    def _cards(self) -> list:
        """현재 값 카드 — 채널별 농도(대표 기체)·R·램프, 밴드 있는 HK 필드."""
        cards = []
        for key, (s, m, mt) in sorted(self._conc_by_channel.items()):
            meta = self._trend_meta.get(key, {})
            v = mt.get("conc_ppb")
            cards.append({"key": ("conc", key), "title": f"{meta.get('label', key[1])} {meta.get('target', '')}",
                          "value": f"{v:.2f} ppb" if isinstance(v, (int, float)) and v == v else "—",
                          "sub": "concentration" if mt else "not running", "status": s, "tip": m})
        for key, (s, m, mt) in sorted(self._r_by_channel.items()):
            meta = self._trend_meta.get(key, {})
            r = mt.get("R")
            drop = mt.get("drop")
            cards.append({"key": ("r", key), "title": f"R {meta.get('label', key[1])}",
                          "value": f"{r:.6f}" if isinstance(r, float) else "—",
                          "sub": f"drop {drop:.1e}" if isinstance(drop, float) else "building baseline",
                          "status": s, "tip": m})
        for key, (s, m, mt) in sorted(self._lamp_by_channel.items()):
            lvl, rel = mt.get("I"), mt.get("rel")
            cards.append({"key": ("lamp", key), "title": f"Lamp {key[1]}",
                          "value": f"{lvl:.0f}" if isinstance(lvl, float) else "—",
                          "sub": f"{rel:+.1%} vs baseline" if isinstance(rel, float) and rel == rel else "building baseline",
                          "status": s, "tip": m})
        for inst, (s, m, mt) in sorted(self._clock_by_inst.items()):
            off = mt.get("offset_s")
            cards.append({"key": ("clock", inst), "title": f"Clock {inst.replace('caesar_', '').replace('_base', '')}",
                          "value": f"{off:+.0f} s" if isinstance(off, float) else "—",
                          "sub": "row time vs PC (UTC)", "status": s, "tip": m})
        sev_status = {None: OK, "warn": P2, "alarm": P1}
        for mkey, (val, sev, _t) in sorted(self._hk_latest.items()):
            meta = self._trend_meta.get(mkey, {})
            unit = meta.get("unit") or ""
            ok = isinstance(val, float) and val == val
            cards.append({"key": ("hk", mkey), "title": meta.get("label", mkey[1]),
                          "value": f"{val:.1f} {unit}".strip() if ok else "missing",
                          "sub": _band_text(meta.get("alarm") or meta.get("warn")),
                          "status": sev_status.get(sev, P2) if ok else P2})
        return cards

    def _record_values(self, overall_status, now) -> dict:
        """1분 기록 한 줄 — 열 이름은 안정적인 순서(정렬)로."""
        v = {"overall": STATUS_CODE.get(overall_status),
             "last_row_age_s": (now - self._last_arrival).total_seconds() if self._last_arrival else None}
        for key, dq in sorted(self._conc_trend.items()):
            if dq:
                for gas, ppb in sorted(dq[-1][1].items()):
                    v[f"conc:{self._trend_meta.get(key, {}).get('label', key[1])}:{gas}_ppb"] = ppb
        for key, (_s, _m, mt) in sorted(self._r_by_channel.items()):
            v[f"R:{self._trend_meta.get(key, {}).get('label', key[1])}"] = mt.get("R")
        for key, (_s, _m, mt) in sorted(self._lamp_by_channel.items()):
            v[f"lamp:{key[1]}_I"] = mt.get("I")
        for mkey, (val, _sev, _t) in sorted(self._hk_latest.items()):
            v[f"hk:{mkey[1]}"] = val
        for inst, (_s, _m, mt) in sorted(self._clock_by_inst.items()):
            v[f"clock:{inst}_offset_s"] = mt.get("offset_s")
        return v

    def _tick(self) -> None:
        events = self.watcher.poll()
        now = datetime.now()
        self._log_ingest_state()
        for i, ev in enumerate(events):
            self._tick_rows = (i, len(events))
            self._files_seen[ev.file] = now
            if not ev.profile_id:
                continue
            self._routed_ids.add(ev.profile_id)
            prof = self.profiles.by_id(ev.profile_id)
            if prof is None:
                continue
            hk_status, hk_msg, hk_metrics = evaluate_hk(prof, ev.row, phase=ev.role,
                                                        channels=self._active_channels(prof, ev),
                                                        latch=self._hk_latch.setdefault(ev.profile_id, {}))
            self._hk_status[ev.file] = (hk_status, hk_msg, hk_metrics)
            if self._hk_last_status.get(ev.file) != hk_status:
                self.state_log.append(hk_status, hk_msg, file=ev.file, **hk_metrics)
                if self.dashboard is not None:
                    self.dashboard.log_line(f"[{os.path.basename(ev.file)}] {hk_status}: {hk_msg}")
            self._hk_last_status[ev.file] = hk_status
            for fkey, (val, sev) in hk_metrics.get("readings", {}).items():
                field = prof.hk.field(fkey)
                if field is None or (field.warn is None and field.alarm is None):
                    continue   # 밴드 없는 필드는 그래프에 임계선을 못 그리므로 노이즈만 늘어남
                mkey = (ev.profile_id, fkey)
                if mkey not in self._trend_meta:
                    self._trend_meta[mkey] = {"label": field.label or fkey, "unit": field.unit,
                                              "warn": field.warn, "alarm": field.alarm}
                self._hk_latest[mkey] = (val, sev, now)
                _last = self._hk_trend_t.get(mkey)
                if _last is None or (now - _last).total_seconds() >= HK_TREND_EVERY_SEC:
                    self._hk_trend.setdefault(mkey, deque(maxlen=TREND_MAXLEN)).append((now, val))
                    self._hk_trend_t[mkey] = now
            if ev.row_time is not None and ev.role != "header":
                inst = prof.base_id or prof.profile_id
                self._rowtime_monitors.setdefault(
                    inst, RowTimeMonitor(prof.cadence.file_rollover_sec)).observe(
                        ev.file, ev.row_time, now, files_between=self._files_between)
            self._observe_reflectance(prof, ev, now)
            self._observe_lamp(prof, ev)
            self._observe_concentration(prof, ev, now)
        self._tick_rows = (len(events), len(events))
        self._observe_clock(events)
        self._last_arrival = latest_arrival(events, self._last_arrival)
        self._retire_stale_files(now)

        grace_sec = _grace_sec_for(self.profiles, self._routed_ids)
        live_status, live_msg, live_metrics = check_liveness(self._last_arrival, now, grace_sec,
                                                                   self._waiting_since, self.watch_dir)
        if live_status == P0 and self._last_arrival is None:
            n_unmon = len(self._unknown_logged) + len(self._date_excluded_logged)
            if n_unmon:
                live_msg += f" — {n_unmon} file(s) here have rows that no profile monitors (see the log)"

        # HK 는 매 행 판정이라 (퇴역 안 한) 파일별로, R·램프·농도는 교정 주기마다 한 번 나오는
        # 판정이라 **채널별 최신값**으로 모은다 — 파일 기준이면 rollover 직후 새 파일에 아직
        # 판정이 없어 진행 중인 R 경보가 종합에서 빠지거나, 지난 파일의 경보가 남는다.
        results = [("liveness", live_status, live_msg, live_metrics)]
        results += [(f"hk:{os.path.basename(p)}", s, m, mt)
                    for p, (s, m, mt) in self._hk_status.items()]
        for kind, by_channel in (("r", self._r_by_channel), ("conc", self._conc_by_channel),
                                 ("lamp", self._lamp_by_channel)):
            results += [(f"{kind}:{key[1]}", s, m, mt) for key, (s, m, mt) in by_channel.items()]
        results += [(f"clock:{inst}", s, m, mt) for inst, (s, m, mt) in self._clock_by_inst.items()]
        results += self._rowtime_results(now)
        overall_status, overall_msg = aggregate(results)

        if overall_status != self._last_status:
            self.state_log.append(overall_status, overall_msg, kind="overall")
            if self.dashboard is not None:
                self.dashboard.log_line(f"overall: {overall_status} — {overall_msg}")
        self._last_status = overall_status

        self._update_alarms(results, now)
        self.recorder.maybe_write(now.timestamp(), self._record_values(overall_status, now))

        if self.dashboard is not None:
            self.dashboard.set_results(results)        # badge names the worst cause + an action
            self.dashboard.set_status(overall_status, overall_msg)
            self.dashboard.set_freshness(self._last_arrival, now, grace_sec)
            self.dashboard.update_cards(self._cards())
            self.dashboard.update_alarms(self.alarms)
            rows = {}
            for p, t in self._files_seen.items():
                hk = self._hk_status.get(p)
                r = self._r_status.get(p)
                lamp = self._lamp_status.get(p)
                conc = self._conc_status.get(p)
                rows[p] = {
                    "last_row": t, "lag": (now - t).total_seconds(),
                    "hk_status": hk[0] if hk else None, "hk_msg": hk[1] if hk else None,
                    "r_status": r[0] if r else None, "r_msg": r[1] if r else None,
                    "lamp_status": lamp[0] if lamp else None, "lamp_msg": lamp[1] if lamp else None,
                    "conc_status": conc[0] if conc else None, "conc_msg": conc[1] if conc else None,
                }
            self.dashboard.update_files(rows)
            self.dashboard.update_conc_trend(self._conc_trend, self._trend_meta)
            self.dashboard.update_r_trend(self._r_trend, self._trend_meta)
            self.dashboard.update_hk_trend(self._hk_trend, self._trend_meta)


def _band_text(band) -> str:
    if not band:
        return ""
    lo, hi = band
    if lo is not None and hi is not None:
        return f"band {lo:g}–{hi:g}"
    return f"≥ {lo:g}" if lo is not None else f"≤ {hi:g}"


def _default_state_dir() -> str:
    """소스 실행은 `<repo>/vigil_state`(옛 `oculus_state` 만 있으면 그것), exe 는
    `%LOCALAPPDATA%\\Vigil`(재배포해도 커서 유지, 옛 위치에서 복사) — vigil/runtime.py."""
    from vigil.runtime import default_state_dir
    return default_state_dir(_ROOT)


def pick_watch_dir(parent=None, qs=None):
    """대시보드 폴더 버튼 — 폴더 선택 창. 고정 감시 폴더는 두지 않고 사람이 고른다(2026-10-01).
    지난번 고른 폴더에서 **열기만** 한다(자동으로 쓰지 않는다). 고르면 기억하고 경로를, 취소하면 None.
    `qs` 는 테스트용 설정 저장소(기본 QSettings("CAESAR", "vigil")). QApplication 이 있어야 한다."""
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QFileDialog
    qs = qs if qs is not None else QSettings("CAESAR", "vigil")
    last = qs.value("watch_dir", "", type=str)
    start = last if last and os.path.isdir(last) else os.path.expanduser("~")
    chosen = QFileDialog.getExistingDirectory(parent, "Vigil — choose the raw .dat folder to monitor", start)
    if not chosen:
        return None
    qs.setValue("watch_dir", chosen)
    return chosen


def pick_data_root(parent=None, qs=None):
    """'Augur data…' 버튼 — 이 PC 에서 Augur 산출물(FitSet·파장보정·레퍼런스)이 있는 폴더.
    프로파일의 절대경로가 다른 PC 것일 때만 필요하다(vigil/datapaths.py). 취소하면 None."""
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QFileDialog
    qs = qs if qs is not None else QSettings("CAESAR", "vigil")
    last = qs.value("data_root", "", type=str)
    start = last if last and os.path.isdir(last) else os.path.expanduser("~")
    chosen = QFileDialog.getExistingDirectory(
        parent, "Vigil — choose the Augur data folder (the one holding 'fit setting', wavelength calibrations …)", start)
    if not chosen:
        return None
    qs.setValue("data_root", chosen)
    return chosen


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Vigil M0+M1+M2+M3 — real-time monitoring of raw inflow + HK + R + concentration")
    ap.add_argument("--dir", default=None,
                    help="raw .dat folder to monitor (recursive). If omitted or missing, a folder picker "
                         "opens (the last chosen folder is remembered)")
    ap.add_argument("--profiles", default=DEFAULT_PROFILE_DIR,
                    help=f"instrument profile folder (default {DEFAULT_PROFILE_DIR})")
    ap.add_argument("--state-dir", default=None,
                    help="folder for cursors and logs (default: <repo>/vigil_state when run from source, %%LOCALAPPDATA%%\\Vigil for the exe)")
    ap.add_argument("--poll-sec", type=float, default=1.0, help="poll interval (s, default 1.0)")
    ap.add_argument("--autostart", action="store_true",
                    help="start monitoring immediately (unattended use, auto-run after reboot). By default it opens paused and waits for Start")
    ap.add_argument("--max-mb-per-tick", type=float, default=DEFAULT_MAX_BYTES_PER_TICK / 2**20,
                    help="max raw read per tick (MB, default %(default).0f) — backlog is caught up in chunks")
    ap.add_argument("--backlog-age-min", type=float, default=DEFAULT_BACKLOG_AGE_SEC / 60,
                    help="on start, skip cursorless files unchanged for longer than this (min, default %(default).0f). "
                         "Negative: skip nothing, read from the beginning")
    return ap


def main(argv=None) -> int:
    # 측정 PC 콘솔은 보통 cp949다. 한글은 cp949에 있어서 잘 나오지만 '≈' 같은 기호가
    # 섞이면 UnicodeEncodeError로 메시지 대신 트레이스백이 뜬다 — 콘솔 인코딩은 그대로
    # 두고(한글 정상 출력) 표현 못 하는 글자만 '?'로 떨어뜨린다.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except (AttributeError, OSError):   # 리다이렉트/파이프 등 reconfigure 불가
            pass

    args = build_arg_parser().parse_args(argv)
    if args.state_dir is None:
        args.state_dir = _default_state_dir()

    from vigil import runtime
    log_path = runtime.setup_logging(args.state_dir)
    _crash_fh = runtime.install_crash_handlers(args.state_dir)   # noqa: F841 — 끝까지 열어 둔다
    log.info("Vigil started — dir=%s state=%s log=%s", args.dir, args.state_dir, log_path)
    if runtime.lower_priority():
        log.info("process priority: below normal (LabVIEW first)")
    runtime.disable_quickedit()

    from PyQt6.QtCore import QLockFile, QTimer
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv[:1])
    from gui.theme import apply_vigil
    apply_vigil(app)   # 밤·등불 팔레트를 어둡게 고정 + pyqtgraph 기본값(gui/theme.py)

    # 무거운 임포트를 **앱 생성 직후** 스레드로 시작한다. 창에 필요한 것(프로파일 스키마 검증
    # jsonschema 1.9 s · 대시보드 pyqtgraph)이 끝나면 `_ui_ready` 를 켜고, 농도 감시기(scipy·피팅
    # 엔진)는 창이 뜬 뒤에도 계속 불러온다 — 첫 감시 tick 에서야 쓰이고, 기본은 정지 상태로 켜므로
    # 사람이 Start 를 누르기 전에 끝난다. 2026-10-01 전엔 농도 감시기까지 다 불러와야 창을 띄웠고
    # 그것도 프로파일 로드 뒤(5.6 s 시점)에 시작해서 창까지 ~10 s 였다.
    import importlib, threading
    _ui_ready = threading.Event()

    def _prewarm():
        for _m in ("jsonschema", "pyqtgraph", "vigil.dashboard.dashboard_window"):
            try:
                importlib.import_module(_m)
            except Exception:   # noqa: BLE001 — 실제 임포트 자리가 보고한다
                pass
        _ui_ready.set()
        try:
            importlib.import_module("vigil.monitors.conc_monitor")
        except Exception:       # noqa: BLE001
            pass
    _pre = threading.Thread(target=_prewarm, daemon=True)
    _pre.start()

    # 감시 폴더: 시작할 때 묻지 않는다 — 대시보드의 'Choose folder…' 버튼으로 고른다(2026-10-01).
    # --dir 은 무인 실행용으로만(없거나 사라진 폴더면 무시하고 버튼으로 고르게 한다).
    if args.dir and not os.path.isdir(args.dir):
        log.warning("watch folder not found: %s — choose one with the folder button", args.dir)
        args.dir = None

    # 한 PC 에 Vigil 두 개 금지 — 같은 cursors.json·status.jsonl 에 두 프로세스가 쓰고 CPU 도 두 배.
    lock = QLockFile(os.path.join(args.state_dir, "vigil.lock"))
    if not lock.tryLock(100):
        log.error("another Vigil is already running (%s) — exiting", args.state_dir)
        QMessageBox.warning(None, "Vigil", "Vigil is already running.\n"
                            f"(state folder: {args.state_dir})")
        return 2

    # 스플래시 먼저 — 로그 줄은 실제로 끝난 부팅 단계만(gui/splash.py).
    from gui.splash import VigilSplash, set_app_icon
    set_app_icon(app, "vigil")
    from vigil import __version__
    splash = VigilSplash(__version__, "Vital-signs Inspector for Gas Instruments, Live", n_steps=6)
    splash.show()
    splash.pump()
    splash.step("engine", f"Vigil v{__version__}")

    splash.step("watch", args.dir or "not set — choose with the folder button", "ok" if args.dir else "skip")
    _cursors = os.path.join(args.state_dir, "cursors.json")
    _resume = os.path.isfile(_cursors)
    splash.step("state", f"{os.path.basename(args.state_dir)} · "
                         f"{'resume' if _resume else 'fresh (skips raw older than %.0f min)' % args.backlog_age_min}",
                "ok" if _resume else "skip")
    from core.provenance import code_version
    _ver = code_version()
    splash.step("build", _ver, "ok" if not _ver.endswith(("-dirty", "-unknown")) and _ver != "nogit" else "skip")

    from PyQt6.QtCore import QSettings
    from vigil.dashboard.dashboard_window import DashboardWindow
    qs = QSettings("CAESAR", "vigil")
    win = DashboardWindow(title="Vigil", tz=qs.value("tz", "KST", type=str))
    win.tz_changed.connect(lambda tz: qs.setValue("tz", tz))
    # before VigilApp: its 'Watch folder' line would otherwise hide whether the last run wrote an exit line
    StateLog(os.path.join(args.state_dir, "status.jsonl")).lifecycle(
        "start", f"Vigil started (v{__version__}, autostart={bool(args.autostart and args.dir)})",
        pid=os.getpid(), watch_dir=args.dir, autostart=bool(args.autostart and args.dir))
    core = VigilApp(args.dir, args.profiles, args.state_dir, dashboard=win,
                    max_bytes_per_tick=int(args.max_mb_per_tick * 2**20),
                    backlog_age_sec=(args.backlog_age_min * 60 if args.backlog_age_min >= 0 else None))
    _data_root = qs.value("data_root", "", type=str)
    if _data_root and os.path.isdir(_data_root):
        core.data_root = _data_root          # 시작 시엔 감시기가 아직 없으니 경로만
        win.set_data_root(_data_root)
    splash.step("profiles", f"{len(core.profiles)} loaded", "ok" if len(core.profiles) else "fail")
    win.log_line(f"poll {args.poll_sec:.1f}s, {len(core.profiles)} profile(s) loaded")
    for w in core.profile_warnings:
        win.log_line(f"WARNING: {w}")
    win.set_watch_dir(args.dir)

    # 모션은 여기서부터 — 위의 준비(git·대시보드 생성)는 메인 스레드를 막으므로 첫 장면에서
    # 끝낸다(실측 0.2–0.4 s 정지가 세 번). 농도 감시기(scipy·피팅 엔진 ≈ 1 s)는 Qt 를 안
    # 건드리므로 스레드로 미리 데우며 1.3 s 모션을 끊김 없이 재생한다.
    splash.restart()
    splash.wait_while(lambda: not _ui_ready.is_set())   # 창에 필요한 임포트까지만(농도 감시기는 계속 뒤에서)
    splash.wait_settled()
    splash.step("dashboard", "ready")

    timer = QTimer()
    timer.timeout.connect(core.tick)
    timer.start(int(args.poll_sec * 1000))
    app.aboutToQuit.connect(core.shutdown)
    win.run_toggled.connect(lambda running: core.resume() if running else core.pause())

    def _on_folder_chosen(path):
        # 폴더를 바꾸면 정지 상태로 — 새 폴더를 확인하고 사람이 Start 를 누를 때 읽기 시작.
        core.pause("Watch folder changed — press Start to begin monitoring")
        win.set_running(False)
        core.set_watch_dir(path)
        win.reset_views()
        win.set_watch_dir(path)
        win.log_line(f"watching {path}")
    win.folder_requested.connect(lambda: (lambda p: p and _on_folder_chosen(p))(pick_watch_dir(win)))

    def _on_data_root(path):
        core.set_data_root(path)
        win.set_data_root(path)
    win.data_root_requested.connect(lambda: (lambda p: p and _on_data_root(p))(pick_data_root(win, qs)))

    def _on_mission():
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        d = QFileDialog.getExistingDirectory(win, "Load mission package (folder from Augur 'Export mission for Vigil')",
                                             qs.value("mission_dir", "", type=str))
        if not d:
            return
        qs.setValue("mission_dir", d)
        try:
            got = core.load_mission(d)
        except Exception as e:                    # noqa: BLE001 — 사람에게 보여 주고 아무것도 안 바꾼다
            QMessageBox.warning(win, "Mission not loaded", f"{type(e).__name__}: {e}")
            return
        win.reset_views()
        QMessageBox.information(win, "Mission loaded",
                                "Concentration and R are on for files in the mission's dates:\n\n" + "\n".join(got))
    win.mission_requested.connect(_on_mission)

    if not args.autostart or not args.dir:
        # 기본은 정지 상태로 켠다 — 폴더를 고르고(또는 확인하고) 사람이 Start 를 누를 때 읽기 시작.
        core.pause("Started paused — choose a folder and press Start (use --dir and --autostart for unattended runs)")
        win.set_running(False)
    if args.dir:
        win.log_line(f"watching {args.dir}")

    win.log_line(f"log: {log_path}")
    win.show()
    splash.finish(win)
    rc = app.exec()
    log.info("Vigil exited (rc=%s)", rc)
    reason = win.close_reason or "application quit"
    core.state_log.lifecycle("exit", f"Vigil exited (rc={rc}, {reason})", rc=rc, reason=reason)
    lock.unlock()
    return rc


if __name__ == "__main__":
    # `python vigil/run_vigil.py`로 직접 실행하면 인터프리터가 스크립트 디렉터리(vigil/)를
    # sys.path 맨 앞에 넣는다 — vigil/profile.py가 표준라이브러리 profile 모듈을 가려버려
    # (pyqtgraph.debug가 cProfile을 통해 그걸 import) 대시보드 임포트가 죽는다. 패키지 임포트는
    # 이미 위에서 _ROOT로 되므로, 이 항목만 지워도 안전.
    _self_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
    sys.exit(main())
