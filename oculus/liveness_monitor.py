"""oculus/liveness_monitor.py — raw 유입 정지 판정 (설계문서 §1.4, §5).

다른 셋(농도·R·HK)의 전제 조건 — raw가 안 들어오면 볼 데이터가 없으므로
ingest 경보가 최우선순위(P0)다(§1.4). 순수함수로 만들어 Oculus 대시보드와
향후 CLI/테스트가 공유한다(core/health_checks.py와 같은 패턴).

임계값은 코드 상수가 아니라 프로파일의 `cadence.liveness_grace_sec`에서
온다(§5) — 캠페인·장비 구성별로 다르므로.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

OK, P0, SKIP = "OK", "P0", "SKIP"

DEFAULT_GRACE_SEC = 10.0   # 프로파일에 liveness_grace_sec이 없을 때의 폴백


def check_liveness(last_arrival: Optional[datetime], now: Optional[datetime] = None,
                    grace_sec: float = DEFAULT_GRACE_SEC):
    """마지막으로 새 행을 관측한 벽시계 시각 vs 지금 — (status, msg, metrics).

    status: SKIP(아직 아무 행도 못 봄) | OK | P0(측정 정지 의심, grace_sec 초과)."""
    if last_arrival is None:
        return SKIP, "아직 관측된 행 없음 (초기화 중이거나 감시폴더에 raw 없음)", {}
    now = now or datetime.now()
    gap = (now - last_arrival).total_seconds()
    metrics = {"gap_sec": gap, "grace_sec": grace_sec,
              "last_arrival": last_arrival.isoformat()}
    if gap > grace_sec:
        return P0, f"측정 정지 의심 — 마지막 행 {gap:.0f}s 전 (허용 {grace_sec:.0f}s)", metrics
    return OK, f"정상 — 마지막 행 {gap:.1f}s 전", metrics


def latest_arrival(events: Sequence, prior: Optional[datetime]) -> Optional[datetime]:
    """이번 poll의 RowEvent들 + 이전 최신시각 → 갱신된 최신 관측시각.
    events가 비었으면 prior 그대로(새 행이 없었다는 뜻)."""
    if not events:
        return prior
    newest = max(ev.arrival_time for ev in events)
    return newest if prior is None else max(prior, newest)
