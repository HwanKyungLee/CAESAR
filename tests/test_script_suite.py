"""tests/test_script_suite.py — 저장소의 자체검증 스크립트를 **전부** 돌린다.

왜 이게 필요했나 (2026-09-15)
------------------------------
저장소에 `test_*.py`가 42개 있는데 CI는 그중 10개만 돌리고 있었다. 나머지 32개는
"있지만 아무도 안 돌리는" 상태라, 깨져도 아무도 모른다. 실제로 그랬다 —
`tools/test_fit_explorer_cold_o4_evidence.py`는 b7a107e(n_air 단일 출처 통일)
이후로 계속 실패하고 있었고, `*_portable_evidence.py`는 Windows 체크아웃에서만
CRLF 변환 때문에 sha256이 어긋나 실패하고 있었다(.gitattributes로 해결).

왜 파일을 `tests/`로 옮기지 않았나
----------------------------------
그 스크립트들은 전부 `python tools/test_x.py`로 **단독 실행되는 자체검증기**이고
(pytest 함수가 아니라 `main()` + assert), 문서 50여 곳이 경로로 참조한다. 옮기면
참조가 전부 깨지는데 얻는 건 폴더 이름뿐이다. 대신 여기서 한 곳으로 모아 돌린다:

    pytest                     # 전부
    pytest -k raw_parser       # 하나만
    python tools/test_x.py     # 예전처럼 단독 실행도 그대로 된다

새 자체검증 스크립트를 `tools/`나 `oculus/`에 `test_*.py`로 추가하면 **자동으로**
이 스위트에 포함된다. CI에 줄을 추가할 필요가 없다 — 그게 원래 문제였다.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ("core", "gui", "oculus", "tools", "diagnostics", "calibration")

# 제외 — {상대경로: 사유}. 늘리기 전에 "정말 테스트가 아닌가"를 먼저 의심할 것.
EXCLUDE = {
    "gui/test_fit_dialog.py":
        "테스트가 아니라 **Test Fit 다이얼로그** GUI 모듈 — 이름만 test_로 시작한다",
    "tools/test_fit_explorer_cold_o4_rerun.py":
        "CLI — --data-root 필수 인자(외부 골든 데이터 필요)",
}

# test_* 이름은 아니지만 __main__에 assert 자체검증을 가진 모듈.
SELF_CHECKS = (
    "core/agreement.py",
    "core/error_budget.py",
)

# 개별 스크립트 상한. 전체 43개가 로컬에서 32초, 제일 느린 하나가 2.6초다
# (tools/test_fit_explorer_batch.py). 상한을 크게 잡은 건 CI 러너가 느릴 때를
# 위한 여유일 뿐 — 한 스크립트가 이걸 넘기면 무한루프를 의심할 것.
TIMEOUT_S = 600


def _discover():
    found = []
    for top in SCAN_DIRS:
        base = os.path.join(ROOT, top)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in sorted(filenames):
                if fn.startswith("test_") and fn.endswith(".py"):
                    rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
                    found.append(rel.replace("\\", "/"))
    return sorted(found) + list(SELF_CHECKS)


SCRIPTS = [s for s in _discover() if s not in EXCLUDE]


def test_nothing_silently_dropped():
    """제외 목록이 실재하는 파일만 가리키는지. 파일을 지우거나 옮기면 여기서 걸린다."""
    missing = [rel for rel in list(EXCLUDE) + list(SELF_CHECKS)
               if not os.path.isfile(os.path.join(ROOT, rel))]
    assert not missing, f"목록에 있는데 파일이 없다: {missing}"
    assert len(SCRIPTS) >= 40, f"수집된 스크립트가 너무 적다({len(SCRIPTS)}개) — 탐색이 깨졌나?"


@pytest.mark.parametrize("rel", SCRIPTS)
def test_script(rel):
    env = dict(os.environ,
               QT_QPA_PLATFORM="offscreen",   # GUI 위젯 계약 테스트용
               MPLBACKEND="Agg",
               PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, rel], cwd=ROOT, env=env,
                          capture_output=True, text=True, errors="replace",
                          timeout=TIMEOUT_S)
    if proc.returncode != 0:
        pytest.fail(f"{rel} 실패 (exit {proc.returncode})\n"
                    f"--- stdout ---\n{proc.stdout[-4000:]}\n"
                    f"--- stderr ---\n{proc.stderr[-4000:]}")
