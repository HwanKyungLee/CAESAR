"""코드 출처(provenance) 스탬프.

알파/핏 결과 파일 헤더에 "어떤 코드 버전으로 이 결과가 생성됐나"를 한 줄 박아,
0608 wavecal 오염처럼 나중에 발견되는 사고를 사후 추적할 수 있게 한다.

git 짧은 해시 + 작업트리 변경 여부(-dirty)를 반환한다. git 저장소가 아니거나
git이 없으면 'nogit'으로 안전하게 폴백한다. 프로세스 1회만 계산해 캐시한다.
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@lru_cache(maxsize=1)
def code_version() -> str:
    """예: 'g3cf20b3' 또는 'g3cf20b3-dirty' / 'nogit'. 캐시되어 반복 호출 비용 0."""
    def _git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], cwd=_REPO_DIR,
                capture_output=True, text=True, timeout=3,
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except Exception:
            return None

    short = _git("rev-parse", "--short", "HEAD")
    if not short:
        return "nogit"
    dirty = _git("status", "--porcelain")
    return f"g{short}-dirty" if dirty else f"g{short}"
