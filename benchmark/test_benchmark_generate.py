#!/usr/bin/env python
"""벤치마크 생성기가 **배포된 261 케이스를 재현**하는지. (데이터 불필요 — 전부 저장소 안)

`generate.py` 를 2026-09-23 에 파라미터화했다(작업 B-1). 기본값으로 돌리면 배포본과
같아야 하고, 안 그러면 계기 좌표 스윕의 기준점이 사라진다. 재현은 **비트 단위가
아니라 ~2 ULP** 다 — numpy matmul 의 합산 순서가 고정이 아니기 때문이고, 입력
파일은 바이트 동일함을 확인했다.

    python benchmark/test_benchmark_generate.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "doas_benchmark_v1"))

import generate                                             # noqa: E402


def main():
    generate.selftest()
    # 지시서 B-4: README 첫 줄이 249 라고 쓰여 있었다. manifest 와 군 합계는 261 이다.
    txt = open(os.path.join(_HERE, "doas_benchmark_v1", "README.md"),
               encoding="utf-8").read()
    assert "249 synthetic" not in txt, "README 가 아직 249 라고 쓰고 있다"
    assert "261 synthetic" in txt, "README 에 케이스 수가 없다"
    print("OK")


if __name__ == "__main__":
    main()
