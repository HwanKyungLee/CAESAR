"""vigil/monitors/liveness_monitor.py — raw 유입 정지 판정 (설계문서 §1.4, §5).

다른 셋(농도·R·HK)의 전제 조건 — raw가 안 들어오면 볼 데이터가 없으므로
ingest 경보가 최우선순위(P0)다(§1.4). 순수함수로 만들어 Vigil 대시보드와
향후 CLI/테스트가 공유한다(core/health_checks.py와 같은 패턴).

임계값은 코드 상수가 아니라 프로파일의 `cadence.liveness_grace_sec`에서
온다(§5) — 캠페인·장비 구성별로 다르므로.

등급 어휘(OK/P0/SKIP)는 여기서 정의하지 않고 `vigil.alert_engine`에서 가져온다 —
hk_monitor 등 다른 모니터와 같은 어휘를 써야 대시보드/aggregate가 일관된다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from vigil.alert_engine import OK, P0, SKIP

DEFAULT_GRACE_SEC = 10.0   # 프로파일에 liveness_grace_sec이 없을 때의 폴백


def check_liveness(last_arrival: Optional[datetime], now: Optional[datetime] = None,
                    grace_sec: float = DEFAULT_GRACE_SEC):
    """마지막으로 새 행을 관측한 벽시계 시각 vs 지금 — (status, msg, metrics).

    status: SKIP(아직 아무 행도 못 봄) | OK | P0(측정 정지 의심, grace_sec 초과)."""
    if last_arrival is None:
        return SKIP, "no rows seen yet (initializing, or no raw in watch folder)", {}
    now = now or datetime.now()
    gap = (now - last_arrival).total_seconds()
    metrics = {"gap_sec": gap, "grace_sec": grace_sec,
              "last_arrival": last_arrival.isoformat()}
    if gap > grace_sec:
        return P0, f"measurement stopped? — last row {gap:.0f}s ago (limit {grace_sec:.0f}s)", metrics
    return OK, f"normal — last row {gap:.1f}s ago", metrics


def latest_arrival(events: Sequence, prior: Optional[datetime]) -> Optional[datetime]:
    """이번 poll의 RowEvent들 + 이전 최신시각 → 갱신된 최신 관측시각.
    Only rows routed to a profile count: analysis .dat files growing in the watch folder, header-only
    files and unknown layouts used to keep liveness OK for as long as they grew, masking a real stop
    (audit 2026-10-02: raw stopped, P0 came 80 s later). No routed row -> prior unchanged."""
    times = [ev.arrival_time for ev in events if ev.profile_id]
    if not times:
        return prior
    newest = max(times)
    return newest if prior is None else max(prior, newest)
