"""병렬 워커 수 단일 출처 — 알파 Pass1/2·병렬 핏·R(t) 파싱이 전부 여기만 본다.

**기본은 전 논리코어다.** 2026-09 이전에는 호출부마다 `cpu_count()//2` 를 따로
하드코딩했다(근거: 풀가동이면 GUI 프로세스가 굶어 '응답없음'). 그 규칙을 코드에서
빼고 **사람 손잡이**(GUI `CPU cores` 스핀)로 옮겼다 — 코어를 다 쓰고 싶은 사람이
소스를 고쳐야 했던 게 문제였지, 절반이라는 값 자체가 물리적 진실은 아니다.

전달 수단이 환경변수인 이유: 병렬 계산 진입점이 세 군데(gui/worker.py 두 곳,
tools/r_trend_monitor.py)인데 마지막 것은 GUI 위젯을 모르는 CLI 도구이고,
GUI 안에서는 **인프로세스로** 불린다(gui/r_workers.py). 인자로 끌고 다니면 서명
세 개가 오염되고, 모듈 전역으로 두면 CLI 단독 실행에서 못 바꾼다. 환경변수는
둘 다 되고 spawn 자식에게도 그대로 상속된다.
"""
from __future__ import annotations

import os

ENV_VAR = 'AUGUR_MAX_WORKERS'


def max_workers() -> int:
    """병렬 프로세스 수. 미설정/이상값이면 전 논리코어. 항상 [1, cpu_count] 클램프."""
    cpu = os.cpu_count() or 4
    try:
        n = int(os.environ.get(ENV_VAR, '') or cpu)
    except ValueError:
        n = cpu
    return max(1, min(n, cpu))


def set_max_workers(n: int | None) -> None:
    """GUI 토글이 부른다. n<=0/None = 미설정(=전 코어)."""
    if n and int(n) > 0:
        os.environ[ENV_VAR] = str(int(n))
    else:
        os.environ.pop(ENV_VAR, None)
