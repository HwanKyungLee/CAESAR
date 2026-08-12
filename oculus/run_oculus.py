"""oculus/run_oculus.py — Oculus 진입점 (M0 유입 감시 + M1 HK 헬스 + 최소 대시보드).

사용:
    python oculus/run_oculus.py --dir "D:\\CAESAR raw\\2026-yeosu"
    python -m oculus.run_oculus --dir ... --poll-sec 1.0

DAQ PC에서 LabVIEW와 나란히 돌리는 걸 전제로 한다(설계문서 §0-A.1) — raw를
읽기만 하고 절대 쓰지 않으며(§2 원칙2), 자기 상태(커서·로그)는 `--state-dir`
(기본 레포의 `oculus_state/`)에만 쓴다.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from oculus.alert_engine import aggregate
from oculus.ingest_cursor import IngestCursor
from oculus.monitors.hk_monitor import evaluate_hk
from oculus.monitors.liveness_monitor import DEFAULT_GRACE_SEC, check_liveness, latest_arrival
from oculus.profile import DEFAULT_PROFILE_DIR, ProfileSet
from oculus.state_log import StateLog
from oculus.watcher import Watcher


def _grace_sec_for(profiles: ProfileSet, routed_ids: set) -> float:
    """지금까지 라우팅된 프로파일들의 liveness_grace_sec 중 최솟값(가장 민감한 쪽).
    아직 아무 프로파일도 안 붙었으면 DEFAULT_GRACE_SEC."""
    vals = [p.cadence.liveness_grace_sec for p in profiles.profiles
            if p.profile_id in routed_ids and p.cadence.liveness_grace_sec is not None]
    return min(vals) if vals else DEFAULT_GRACE_SEC


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
        self._last_status = None           # 종합(overall) 상태 — 로그 중복 방지용

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
        self._last_arrival = latest_arrival(events, self._last_arrival)

        grace_sec = _grace_sec_for(self.profiles, self._routed_ids)
        live_status, live_msg, live_metrics = check_liveness(self._last_arrival, now, grace_sec)

        results = [("liveness", live_status, live_msg, live_metrics)]
        results += [(f"hk:{os.path.basename(p)}", s, m, mt)
                    for p, (s, m, mt) in self._hk_status.items()]
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
                rows[p] = (t, (now - t).total_seconds(),
                          hk[0] if hk else None, hk[1] if hk else None)
            self.dashboard.update_files(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Oculus M0+M1 — raw 유입 + HK 실시간 감시")
    ap.add_argument("--dir", required=True, help="감시할 raw .dat 폴더(재귀)")
    ap.add_argument("--profiles", default=DEFAULT_PROFILE_DIR,
                    help=f"인스트루먼트 프로파일 폴더 (기본 {DEFAULT_PROFILE_DIR})")
    ap.add_argument("--state-dir", default=os.path.join(_ROOT, "oculus_state"),
                    help="커서·로그 저장 폴더 (기본 <repo>/oculus_state)")
    ap.add_argument("--poll-sec", type=float, default=1.0, help="폴링 주기(초, 기본 1.0)")
    return ap


def main(argv=None) -> int:
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
    sys.exit(main())
