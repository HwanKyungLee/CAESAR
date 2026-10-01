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

from vigil.alert_engine import OK, P1, SKIP, aggregate, worse
from vigil.ingest_cursor import IngestCursor
from vigil.monitors.hk_monitor import evaluate_hk
from vigil.monitors.liveness_monitor import DEFAULT_GRACE_SEC, check_liveness, latest_arrival
from vigil.monitors.lamp_monitor import LampMonitor
from vigil.monitors.r_monitor import RMonitor
from vigil.profile import DEFAULT_PROFILE_DIR, ProfileSet
from vigil.state_log import StateLog
from vigil.watcher import DEFAULT_BACKLOG_AGE_SEC, DEFAULT_MAX_BYTES_PER_TICK, Watcher

log = logging.getLogger("vigil")

TREND_MAXLEN = 300   # ponytail: 그래프 표시용 최근 N개 — 부족하면 늘릴 것
# 이만큼 새 행이 없는 파일은 파일별 상태(표·HK 판정)에서 뺀다. 1 h 파일 rollover 뒤 지난 파일의
# P1 이 종합 상태를 영원히 붙잡고, 표가 캠페인 내내 늘어나던 것(2026-10-01). 측정 정지 자체는
# liveness(전체 최신 행 기준)가 따로 잡으므로 여기서 빼도 숨겨지지 않는다.
RETIRE_AFTER_SEC = 600.0
CURSOR_SAVE_INTERVAL_SEC = 5.0


def _grace_sec_for(profiles: ProfileSet, routed_ids: set) -> float:
    """지금까지 라우팅된 프로파일들의 liveness_grace_sec 중 최솟값(가장 민감한 쪽).
    아직 아무 프로파일도 안 붙었으면 DEFAULT_GRACE_SEC."""
    vals = [p.cadence.liveness_grace_sec for p in profiles.profiles
            if p.profile_id in routed_ids and p.cadence.liveness_grace_sec is not None]
    return min(vals) if vals else DEFAULT_GRACE_SEC


def _hk_value(prof, row, key):
    """key(hk.fields[].key)로 그 행의 물리값 하나만 뽑는다. key/필드 없으면 NaN(R 계산이 알아서 실패 처리)."""
    if not key:
        return float("nan")
    field = prof.hk.field(key)
    if field is None:
        return float("nan")
    try:
        return field.value(row, prof.hk.start_col)
    except (IndexError, ValueError):
        return float("nan")


class VigilApp:
    """감시 루프 상태 컨테이너. QTimer가 매 tick `.tick()`을 부른다."""

    def __init__(self, watch_dir: str, profile_dir: str, state_dir: str,
                 dashboard=None, max_bytes_per_tick: int = DEFAULT_MAX_BYTES_PER_TICK,
                 backlog_age_sec=DEFAULT_BACKLOG_AGE_SEC, retire_after_sec: float = RETIRE_AFTER_SEC,
                 cursor_save_interval_sec: float = CURSOR_SAVE_INTERVAL_SEC):
        self.watch_dir = watch_dir
        self.profiles = ProfileSet.load(profile_dir)
        self.cursor = IngestCursor(os.path.join(state_dir, "cursors.json"))
        self.state_log = StateLog(os.path.join(state_dir, "status.jsonl"))
        self.watcher = Watcher(watch_dir, self.profiles, self.cursor,
                               max_bytes_per_tick=max_bytes_per_tick, backlog_age_sec=backlog_age_sec,
                               cursor_save_interval_sec=cursor_save_interval_sec)
        self.retire_after_sec = retire_after_sec
        self.paused = False                # 대시보드 Stop — 정지 중엔 tick 이 아무것도 읽지 않는다
        self._tick_errors = 0              # 연속 tick 예외 수(성공하면 0)
        self._backlog_logged = False
        self._was_catching_up = False
        self.dashboard = dashboard

        self._last_arrival = None          # 전체 최신 관측 벽시계 시각
        self._files_seen: dict = {}        # {path: arrival_time}
        self._routed_ids: set = set()
        self._hk_status: dict = {}         # {path: (status, msg, metrics)} — 최신 HK 판정
        self._hk_last_status: dict = {}    # {path: status} — 로그 중복 방지용
        self._r_monitors: dict = {}        # {(profile_id, channel_id): RMonitor}
        self._wavecal_cache: dict = {}     # {wavecal_path: np.ndarray|None} — 파일당 1회만 로드
        self._r_by_channel: dict = {}      # {(profile_id, channel_id): (status, msg, metrics)}
        self._r_status: dict = {}          # {path: (status, msg, metrics)} — 파일의 채널들 중 worst
        self._r_last_status: dict = {}     # {path: status} — 로그 중복 방지용
        self._lamp_monitors: dict = {}     # {(profile_id, channel_id): LampMonitor}
        self._lamp_by_channel: dict = {}
        self._lamp_status: dict = {}       # {path: (status, msg, metrics)} — 파일의 채널들 중 worst
        self._lamp_last_status: dict = {}
        self._conc_monitors: dict = {}     # {(profile_id, channel_id): ConcMonitor}
        self._fitset_cache: dict = {}      # {fitset_path: dict} — FitSet json 1회만 로드
        self._conc_by_channel: dict = {}   # {(profile_id, channel_id): (status, msg, metrics)}
        self._conc_status: dict = {}       # {path: (status, msg, metrics)} — 파일의 채널들 중 worst
        self._conc_last_status: dict = {}  # {path: status} — 로그 중복 방지용
        self._last_status = None           # 종합(overall) 상태 — 로그 중복 방지용
        self._conc_trend: dict = {}   # {(profile_id,ch_id): deque[(datetime, {gas: ppb})]}
        self._r_trend: dict = {}      # {(profile_id,ch_id): deque[(datetime, float, baseline)]}
        self._hk_trend: dict = {}     # {(profile_id,field_key): deque[(datetime,float)]}
        self._trend_meta: dict = {}   # 채널/필드 메타(label, unit, min/max, warn/alarm) — 1회만 채움

    def _get_wavecal(self, path):
        if path not in self._wavecal_cache:
            from tools.optimize_params import load_wavecal   # 기존 로더 재사용(3번째 사본 안 만듦)
            self._wavecal_cache[path] = load_wavecal(path)
        return self._wavecal_cache[path]

    def _get_fitset_channel(self, cfg):
        scen = self._fitset_cache.get(cfg.fitset_path)
        if scen is None:
            scen = json.load(open(cfg.fitset_path, encoding="utf-8"))
            self._fitset_cache[cfg.fitset_path] = scen
        from vigil.monitors.conc_monitor import pick_fitset_channel
        return pick_fitset_channel(scen, cfg.wl_dir)

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
            temp_c = _hk_value(prof, ev.row, ch.reflectance.cavity_temp_hk)
            press_mbar = _hk_value(prof, ev.row, ch.reflectance.cavity_pressure_hk)
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
                  for ch in prof.signal_channels()
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

    def _observe_lamp(self, prof, ev) -> None:
        """모든 signal 채널의 ZA 블록 세기(램프 헬스). 설정 없이 기본 문턱으로 돈다."""
        # ponytail: 문턱은 모듈 상수(2026 여수 실측). 캠페인별로 달라지면 프로파일 키로 뺄 것.
        touched = False
        for ch in prof.signal_channels():
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
            temp_c = _hk_value(prof, ev.row, ch.concentration.cavity_temp_hk)
            press_mbar = _hk_value(prof, ev.row, ch.concentration.cavity_pressure_hk)
            result = cm.observe(ev.role, spectrum, temp_c, press_mbar)
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
        self._note_control("Monitoring resumed (user Start) — reading from the backlog onward")

    def _note_control(self, msg: str) -> None:
        log.info(msg)
        self.state_log.append("CONTROL", msg, kind="control")
        if self.dashboard is not None:
            self.dashboard.log_line(msg)

    def tick(self) -> None:
        """QTimer 슬롯. PyQt6 는 슬롯에서 새어 나간 예외에 프로세스를 abort 하므로, 여기서 다
        받아 로그에 남기고 배지에 띄운 뒤 다음 tick 을 계속 돈다 — 감시기가 조용히 사라지는
        것이 가장 나쁜 실패다. 정지(pause) 중엔 아무것도 하지 않는다."""
        if self.paused:
            return
        try:
            self._tick()
        except Exception as e:                # noqa: BLE001
            self._tick_errors += 1
            log.exception("tick failed (%d in a row)", self._tick_errors)
            msg = f"Vigil internal error, {self._tick_errors} in a row: {type(e).__name__}: {e}"
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
                log.info("tick recovered (after %d consecutive failures)", self._tick_errors)
                self.state_log.append(OK, f"Vigil internal error recovered (after {self._tick_errors})",
                                      kind="internal")
            self._tick_errors = 0

    def shutdown(self) -> None:
        """종료 시 미저장 커서를 쓴다(저장 간격 때문에 마지막 몇 초가 메모리에만 있을 수 있다)."""
        self.cursor.flush()

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

    def _tick(self) -> None:
        events = self.watcher.poll()
        now = datetime.now()
        self._log_ingest_state()
        for ev in events:
            self._files_seen[ev.file] = now
            if not ev.profile_id:
                continue
            self._routed_ids.add(ev.profile_id)
            prof = self.profiles.by_id(ev.profile_id)
            if prof is None:
                continue
            hk_status, hk_msg, hk_metrics = evaluate_hk(prof, ev.row, phase=ev.role)
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
                self._hk_trend.setdefault(mkey, deque(maxlen=TREND_MAXLEN)).append((now, val))
            self._observe_reflectance(prof, ev, now)
            self._observe_lamp(prof, ev)
            self._observe_concentration(prof, ev, now)
        self._last_arrival = latest_arrival(events, self._last_arrival)
        self._retire_stale_files(now)

        grace_sec = _grace_sec_for(self.profiles, self._routed_ids)
        live_status, live_msg, live_metrics = check_liveness(self._last_arrival, now, grace_sec)

        # HK 는 매 행 판정이라 (퇴역 안 한) 파일별로, R·램프·농도는 교정 주기마다 한 번 나오는
        # 판정이라 **채널별 최신값**으로 모은다 — 파일 기준이면 rollover 직후 새 파일에 아직
        # 판정이 없어 진행 중인 R 경보가 종합에서 빠지거나, 지난 파일의 경보가 남는다.
        results = [("liveness", live_status, live_msg, live_metrics)]
        results += [(f"hk:{os.path.basename(p)}", s, m, mt)
                    for p, (s, m, mt) in self._hk_status.items()]
        for kind, by_channel in (("r", self._r_by_channel), ("conc", self._conc_by_channel),
                                 ("lamp", self._lamp_by_channel)):
            results += [(f"{kind}:{key[1]}", s, m, mt) for key, (s, m, mt) in by_channel.items()]
        overall_status, overall_msg = aggregate(results)

        if overall_status != self._last_status:
            self.state_log.append(overall_status, overall_msg, kind="overall")
            if self.dashboard is not None:
                self.dashboard.log_line(f"overall: {overall_status} — {overall_msg}")
        self._last_status = overall_status

        if self.dashboard is not None:
            self.dashboard.set_status(overall_status, overall_msg)
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


def _default_state_dir() -> str:
    """소스 실행은 `<repo>/vigil_state`(옛 `oculus_state` 만 있으면 그것), exe 는
    `%LOCALAPPDATA%\\Vigil`(재배포해도 커서 유지, 옛 위치에서 복사) — vigil/runtime.py."""
    from vigil.runtime import default_state_dir
    return default_state_dir(_ROOT)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Vigil M0+M1+M2+M3 — real-time monitoring of raw inflow + HK + R + concentration")
    ap.add_argument("--dir", required=True, help="raw .dat folder to monitor (recursive)")
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
    if not os.path.isdir(args.dir):
        print(f"Watch folder not found: {args.dir}", file=sys.stderr)
        return 1

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

    splash.step("watch", args.dir)
    _cursors = os.path.join(args.state_dir, "cursors.json")
    _resume = os.path.isfile(_cursors)
    splash.step("state", f"{os.path.basename(args.state_dir)} · "
                         f"{'resume' if _resume else 'fresh (skips raw older than %.0f min)' % args.backlog_age_min}",
                "ok" if _resume else "skip")
    from core.provenance import code_version
    _ver = code_version()
    splash.step("build", _ver, "ok" if not _ver.endswith(("-dirty", "-unknown")) and _ver != "nogit" else "skip")

    from vigil.dashboard.dashboard_window import DashboardWindow
    win = DashboardWindow(title=f"Vigil — {args.dir}")
    core = VigilApp(args.dir, args.profiles, args.state_dir, dashboard=win,
                    max_bytes_per_tick=int(args.max_mb_per_tick * 2**20),
                    backlog_age_sec=(args.backlog_age_min * 60 if args.backlog_age_min >= 0 else None))
    splash.step("profiles", f"{len(core.profiles)} loaded", "ok" if len(core.profiles) else "fail")
    win.log_line(f"watching {args.dir} (poll {args.poll_sec:.1f}s, "
                f"{len(core.profiles)} profile(s) loaded)")

    # 모션은 여기서부터 — 위의 준비(git·대시보드 생성)는 메인 스레드를 막으므로 첫 장면에서
    # 끝낸다(실측 0.2–0.4 s 정지가 세 번). 농도 감시기(scipy·피팅 엔진 ≈ 1 s)는 Qt 를 안
    # 건드리므로 스레드로 미리 데우며 1.3 s 모션을 끊김 없이 재생한다.
    import importlib, threading
    _pre = threading.Thread(target=lambda: importlib.import_module("vigil.monitors.conc_monitor"),
                            daemon=True)
    splash.restart()
    _pre.start()
    splash.wait_while(_pre.is_alive)
    splash.wait_settled()
    splash.step("dashboard", "ready")

    timer = QTimer()
    timer.timeout.connect(core.tick)
    timer.start(int(args.poll_sec * 1000))
    app.aboutToQuit.connect(core.shutdown)
    win.run_toggled.connect(lambda running: core.resume() if running else core.pause())
    if not args.autostart:
        # 기본은 정지 상태로 켠다 — 폴더·설정을 확인하고 사람이 Start 를 누를 때 읽기 시작.
        core.pause("Started paused — press Start to begin monitoring (use --autostart to start immediately)")
        win.set_running(False)

    win.log_line(f"log: {log_path}")
    win.show()
    splash.finish(win)
    rc = app.exec()
    log.info("Vigil exited (rc=%s)", rc)
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
