"""vigil/alert_engine.py — 경보 등급 공통 어휘 (설계문서 §5, §6).

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
    Vigil 자체 등급 어휘(P0/P1/P2)로. 빈 리스트면 SKIP.

    A SKIP (not evaluated) is not an OK: "normal — all OK" only when every source was evaluated,
    otherwise "OK k/n · not evaluated m" (audit 2026-10-02 — liveness OK + every monitor SKIP read
    "normal — all 1 OK"; same bug as Augur health_checks.overall, fixed in 0dc4be3). When raw inflow
    is the only thing judged OK and every monitor is SKIP, nothing about the data is being watched —
    P2, and the message says so."""
    if not results:
        return SKIP, "nothing to evaluate"
    worst = SKIP
    for _name, status, _msg, _metrics in results:
        worst = worse(worst, status)
    counts = {lvl: sum(1 for _n, s, *_ in results if s == lvl) for lvl in (P0, P1, P2, OK, SKIP)}
    n, n_skip = len(results), counts[SKIP]
    skipped = f" · not evaluated {n_skip}" if n_skip else ""
    if worst == P0:
        return P0, f"P0 ×{counts[P0]} — check now (P1 {counts[P1]} · P2 {counts[P2]}){skipped}"
    if worst == P1:
        return P1, f"P1 ×{counts[P1]} — quality at risk (P2 {counts[P2]}){skipped}"
    if worst == P2:
        return P2, f"P2 ×{counts[P2]} — watch{skipped}"
    if worst == OK:
        if [name for name, s, *_ in results if s == OK] == ["liveness"]:
            return P2, f"only raw inflow is checked — no monitor has evaluated yet ({n_skip} waiting)"
        if n_skip:
            return OK, f"normal — OK {counts[OK]}/{n}{skipped}"
        return OK, f"normal — all {n} OK"
    return SKIP, f"waiting for data — nothing evaluated yet ({n_skip} not evaluated)"
