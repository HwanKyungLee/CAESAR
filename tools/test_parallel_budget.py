"""core.parallel 단일 출처 회귀.

지키려는 것 두 가지:
  1. max_workers() 가 환경변수/클램프 규칙대로 동작한다.
  2. **아무도 코어 수를 따로 계산하지 않는다** — 옛 `cpu_count()//2` 가 한 군데라도
     되살아나면 GUI 스핀이 그 경로만 조용히 못 건드리게 된다.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.parallel import ENV_VAR, max_workers, set_max_workers   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_budget_rules():
    cpu = os.cpu_count() or 4
    old = os.environ.get(ENV_VAR)
    try:
        set_max_workers(None)
        assert max_workers() == cpu, "미설정이면 전 코어"
        set_max_workers(3)
        assert max_workers() == min(3, cpu)
        set_max_workers(cpu * 10)
        assert max_workers() == cpu, "코어 수 위로는 클램프"
        set_max_workers(0)
        assert max_workers() == cpu, "0 = 미설정"
        os.environ[ENV_VAR] = 'garbage'
        assert max_workers() == cpu, "이상값이면 전 코어로 폴백"
        os.environ[ENV_VAR] = '-5'
        assert max_workers() == 1, "아래로는 1 클램프"
    finally:
        os.environ.pop(ENV_VAR, None)
        if old is not None:
            os.environ[ENV_VAR] = old


def test_no_local_core_math():
    """`cpu_count() ... // 2` 류의 자체 계산이 소스에 없어야 한다."""
    pat = re.compile(r'cpu_count\(\)[^\n]*//\s*\d')
    bad = []
    for sub in ('core', 'gui', 'tools', 'oculus'):
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, sub)):
            dirnames[:] = [d for d in dirnames if d != '__pycache__']
            for fn in filenames:
                # 제외: 이 테스트 자신과 단일 출처 모듈(도큐스트링이 옛 규칙을 인용한다)
                if not fn.endswith('.py') or fn in (os.path.basename(__file__), 'parallel.py'):
                    continue
                fp = os.path.join(dirpath, fn)
                with open(fp, encoding='utf-8') as fh:
                    for i, line in enumerate(fh, 1):
                        if pat.search(line):
                            bad.append(f"{os.path.relpath(fp, ROOT)}:{i}: {line.strip()}")
    assert not bad, "코어 수 자체계산 발견 → core.parallel.max_workers() 를 쓸 것:\n" + "\n".join(bad)


if __name__ == '__main__':
    test_budget_rules()
    test_no_local_core_math()
    print("PASS: core.parallel 예산 규칙 + 자체계산 없음")
