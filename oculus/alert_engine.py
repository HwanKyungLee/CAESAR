"""oculus/alert_engine.py — 경보 등급 공통 어휘 (설계문서 §5, §6).

`liveness_monitor`·`monitors/hk_monitor`(그리고 앞으로 올 r_monitor·conc_monitor)가
전부 같은 심각도 어휘를 쓰게 한다 — 각자 OK/P0 같은 상수를 따로 정의하면 나중에
어긋난다(예: 어떤 모듈은 "PASS", 어떤 모듈은 "OK"). 단일 출처(CLAUDE.md 원칙3).

등급(§5): P0=측정 자체가 멈춤/무의미, P1=데이터는 오나 품질 위험, P2=주의·관찰.
"""
from __future__ import annotations

OK, P2, P1, P0, SKIP = "OK", "P2", "P1", "P0", "SKIP"

# SKIP(아직 판정 불가)이 가장 약하고, P0가 가장 심각.
_RANK = {SKIP: 0, OK: 1, P2: 2, P1: 3, P0: 4}


def worse(a: str, b: str) -> str:
    """둘 중 더 심각한 등급. SKIP은 항상 실제 판정에 진다(SKIP+OK=OK, SKIP+P1=P1)."""
    return a if _RANK[a] >= _RANK[b] else b


def aggregate(results):
    """[(name, status, msg, metrics), ...] → (전체등급, 요약문). health_checks.overall()과 같은 역할,
    Oculus 자체 등급 어휘(P0/P1/P2)로. 빈 리스트면 SKIP."""
    if not results:
        return SKIP, "판정 항목 없음"
    worst = SKIP
    for _name, status, _msg, _metrics in results:
        worst = worse(worst, status)
    counts = {lvl: sum(1 for _n, s, *_ in results if s == lvl) for lvl in (P0, P1, P2, OK, SKIP)}
    if worst == P0:
        return P0, f"P0 {counts[P0]}건 — 즉시 확인 필요 (P1 {counts[P1]}·P2 {counts[P2]})"
    if worst == P1:
        return P1, f"P1 {counts[P1]}건 — 품질 위험 (P2 {counts[P2]})"
    if worst == P2:
        return P2, f"P2 {counts[P2]}건 — 주의·관찰"
    if worst == OK:
        return OK, f"정상 — 전부 OK {counts[OK]}"
    return SKIP, "판정 대기 중"
