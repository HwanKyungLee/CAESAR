"""tools/test_health_checks.py — core/health_checks.py 단위테스트.

fitset_builder.py에 사전검증을 연결하며 실측으로 잡은 회귀:
O4(충돌유도흡수, 피크~1e-46)가 절대 std 문턱(1e-30) 때문에 "평평(퇴화)"으로
오판되던 버그(std/peak 비율은 CHOCHO·H2O와 같은 급이었는데도). 이 테스트는 그
버그가 다시 들어오지 않는지 + 진짜 평평한(상수) 레퍼런스는 여전히 잡는지 본다.

사용: python tools/test_health_checks.py → 전부 PASS면 exit 0
"""
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.health_checks import FAIL, PASS, SKIP, WARN, check_references, check_wavecal, overall

_n_pass = 0
_n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def test_check_wavecal():
    print("[1] check_wavecal")
    good = np.linspace(400.0, 500.0, 2048)
    status, msg, m = check_wavecal(good)
    check("단조증가 → PASS", status == PASS, f"{status}: {msg}")

    bad = good.copy()
    bad[1000] = bad[999] - 1.0   # 역행
    status, msg, m = check_wavecal(bad)
    check("비단조 → FAIL", status == FAIL, f"{status}: {msg}")

    status, msg, m = check_wavecal(np.array([1.0]))
    check("너무 짧음 → FAIL", status == FAIL, f"{status}: {msg}")


def test_check_references_scale_independent_flatness():
    print("[2] check_references — 절대 스케일 무관 평평함 판정 (O4 회귀 방지)")
    wl = np.linspace(438.0, 466.0, 2048)
    rng = np.random.default_rng(0)
    structure = np.sin(np.linspace(0, 20 * np.pi, 2048)) + rng.normal(0, 0.05, 2048)

    normal_scale = structure * 1e-19    # 일반 기체 스케일
    o4_scale = structure * 1e-46        # O4 스케일(충돌유도흡수) — 절대값은 작지만 구조는 동일
    status, msg, m = check_references({"NO2": normal_scale, "O4": o4_scale}, wl=wl)
    check("O4처럼 절대값 작아도 구조 있으면 평평 아님", status != FAIL or "평평" not in msg,
          f"{status}: {msg}")

    truly_flat = np.full(2048, 1e-46)   # 진짜 상수(퇴화) — 스케일과 무관하게 여전히 잡아야 함
    status, msg, m = check_references({"NO2": normal_scale, "O4_flat": truly_flat}, wl=wl)
    check("진짜 평평(상수)한 건 여전히 FAIL", status == FAIL and "평평" in msg, f"{status}: {msg}")


def test_check_references_other_paths():
    print("[3] check_references — 빈값/격자불일치/공선성/정상")
    wl = np.linspace(438.0, 466.0, 100)
    rng = np.random.default_rng(1)
    a = rng.normal(0, 1, 100)

    status, msg, m = check_references({}, wl=wl)
    check("빈 dict → FAIL", status == FAIL, f"{status}: {msg}")

    status, msg, m = check_references({"X": np.array([])}, wl=wl)
    check("빈 배열 → FAIL", status == FAIL, f"{status}: {msg}")

    status, msg, m = check_references({"X": a, "Y": np.concatenate([a, a])}, wl=wl)
    check("격자길이 불일치 → FAIL", status == FAIL, f"{status}: {msg}")

    status, msg, m = check_references({"X": a, "Y": a * 2.0 + 0.01}, wl=wl)   # 거의 동일(높은 공선성)
    check("공선성 높음 → WARN 이상", status in (WARN, FAIL), f"{status}: {msg}")

    b = rng.normal(0, 1, 100)
    status, msg, m = check_references({"X": a, "Y": b}, wl=wl)
    check("서로 다른 정상 레퍼런스 → PASS", status == PASS, f"{status}: {msg}")


def test_overall():
    print("[4] overall — 집계")
    status, msg = overall([])
    check("빈 리스트 → SKIP", status == SKIP, f"{status}: {msg}")
    status, msg = overall([("a", PASS, "x", {}), ("b", WARN, "y", {})])
    check("PASS+WARN → WARN", status == WARN, f"{status}: {msg}")
    status, msg = overall([("a", PASS, "x", {}), ("b", FAIL, "y", {})])
    check("PASS+FAIL → FAIL", status == FAIL, f"{status}: {msg}")


def main():
    for t in (test_check_wavecal, test_check_references_scale_independent_flatness,
              test_check_references_other_paths, test_overall):
        t()
    print(f"\nhealth_checks tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
