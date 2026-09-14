"""oculus/run_oculus.py — Oculus 진입점 (M0 유입 감시 + M1 HK + M2 R + M3 농도 + 대시보드).

사용:
    python oculus/run_oculus.py --dir "D:\\CAESAR raw\\2026-yeosu"
    python -m oculus.run_oculus --dir ... --poll-sec 1.0

DAQ PC에서 LabVIEW와 나란히 돌리는 걸 전제로 한다(설계문서 §0-A.1) — raw를
읽기만 하고 절대 쓰지 않으며(§2 원칙2), 자기 상태(커서·로그)는 `--state-dir`
(기본 레포의 `oculus_state/`)에만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import deque
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from oculus.alert_engine import P1, SKIP, aggregate, worse
from oculus.ingest_cursor import IngestCursor
from oculus.monitors.conc_monitor import ConcMonitor, pick_fitset_channel
from oculus.monitors.hk_monitor import evaluate_hk
from oculus.monitors.liveness_monitor import DEFAULT_GRACE_SEC, check_liveness, latest_arrival
from oculus.monitors.r_monitor import RMonitor
from oculus.profile import DEFAULT_PROFILE_DIR, ProfileSet
from oculus.state_log import StateLog
from oculus.watcher import Watcher

TREND_MAXLEN = 300   # ponytail: 그래프 표시용 최근 N개 — 부족하면 늘릴 것


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


class OculusApp:
    """감시 루프 상태 컨테이너. QTimer가 매 tick `.tick()`을 부른다."""

    def __init__(self, watch_dir: str, profile_dir: str, state_dir: str,
                 dashboard=None):
        self.watch_dir = watch_dir
        self.profiles = ProfileSet.load(profile_dir)
        self.cursor = IngestCursor(os.path.join(state_dir, "cursors.json"))
        self.state_log = StateLog(os.path.join(state_dir, "status.jsonl"))
        self.watcher = Watcher(watch_dir, self.profiles, self.cursor)
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
        if not touched:
            return
        entries = [self._r_by_channel[(prof.profile_id, ch.id)]
                  for ch in prof.signal_channels()
                  if (prof.profile_id, ch.id) in self._r_by_channel]
        combined_status = SKIP
        for s, _m, _mt in entries:
            combined_status = worse(combined_status, s)
        combined_msg = "; ".join(m for _s, m, _mt in entries)
        self._r_status[ev.file] = (combined_status, combined_msg, {})
        if self._r_last_status.get(ev.file) != combined_status:
            self.state_log.append(combined_status, combined_msg, file=ev.file, kind="r")
            if self.dashboard is not None:
                self.dashboard.log_line(f"[{os.path.basename(ev.file)}] R {combined_status}: {combined_msg}")
        self._r_last_status[ev.file] = combined_status

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
                try:
                    fit_ch = self._get_fitset_channel(ch.concentration)
                    cm = ConcMonitor(fit_ch, ch.concentration)
                except Exception as e:                # noqa: BLE001
                    self._conc_by_channel[key] = (
                        P1, f"[{ch.label or ch.id}] 초기화 실패: {e}", {})
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

    def tick(self) -> None:
        events = self.watcher.poll()
        now = datetime.now()
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
            self._observe_concentration(prof, ev, now)
        self._last_arrival = latest_arrival(events, self._last_arrival)

        grace_sec = _grace_sec_for(self.profiles, self._routed_ids)
        live_status, live_msg, live_metrics = check_liveness(self._last_arrival, now, grace_sec)

        results = [("liveness", live_status, live_msg, live_metrics)]
        results += [(f"hk:{os.path.basename(p)}", s, m, mt)
                    for p, (s, m, mt) in self._hk_status.items()]
        results += [(f"r:{os.path.basename(p)}", s, m, mt)
                    for p, (s, m, mt) in self._r_status.items()]
        results += [(f"conc:{os.path.basename(p)}", s, m, mt)
                    for p, (s, m, mt) in self._conc_status.items()]
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
                conc = self._conc_status.get(p)
                rows[p] = {
                    "last_row": t, "lag": (now - t).total_seconds(),
                    "hk_status": hk[0] if hk else None, "hk_msg": hk[1] if hk else None,
                    "r_status": r[0] if r else None, "r_msg": r[1] if r else None,
                    "conc_status": conc[0] if conc else None, "conc_msg": conc[1] if conc else None,
                }
            self.dashboard.update_files(rows)
            self.dashboard.update_conc_trend(self._conc_trend, self._trend_meta)
            self.dashboard.update_r_trend(self._r_trend, self._trend_meta)
            self.dashboard.update_hk_trend(self._hk_trend, self._trend_meta)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Oculus M0+M1+M2+M3 — raw 유입 + HK + R + 농도 실시간 감시")
    ap.add_argument("--dir", required=True, help="감시할 raw .dat 폴더(재귀)")
    ap.add_argument("--profiles", default=DEFAULT_PROFILE_DIR,
                    help=f"인스트루먼트 프로파일 폴더 (기본 {DEFAULT_PROFILE_DIR})")
    ap.add_argument("--state-dir", default=os.path.join(_ROOT, "oculus_state"),
                    help="커서·로그 저장 폴더 (기본 <repo>/oculus_state)")
    ap.add_argument("--poll-sec", type=float, default=1.0, help="폴링 주기(초, 기본 1.0)")
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
    if not os.path.isdir(args.dir):
        print(f"감시 폴더 없음: {args.dir}", file=sys.stderr)
        return 1

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from oculus.dashboard.dashboard_window import DashboardWindow

    app = QApplication(sys.argv[:1])
    win = DashboardWindow(title=f"Oculus — {args.dir}")
    core = OculusApp(args.dir, args.profiles, args.state_dir, dashboard=win)
    win.log_line(f"watching {args.dir} (poll {args.poll_sec:.1f}s, "
                f"{len(core.profiles)} profile(s) loaded)")

    timer = QTimer()
    timer.timeout.connect(core.tick)
    timer.start(int(args.poll_sec * 1000))

    win.show()
    return app.exec()


if __name__ == "__main__":
    # `python oculus/run_oculus.py`로 직접 실행하면 인터프리터가 스크립트 디렉터리(oculus/)를
    # sys.path 맨 앞에 넣는다 — oculus/profile.py가 표준라이브러리 profile 모듈을 가려버려
    # (pyqtgraph.debug가 cProfile을 통해 그걸 import) 대시보드 임포트가 죽는다. 패키지 임포트는
    # 이미 위에서 _ROOT로 되므로, 이 항목만 지워도 안전.
    _self_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
    sys.exit(main())
