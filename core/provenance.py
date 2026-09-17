"""코드 출처(provenance) 스탬프.

알파/핏 결과 파일 헤더에 "어떤 코드 버전으로 이 결과가 생성됐나"를 한 줄 박아,
0608 wavecal 오염처럼 나중에 발견되는 사고를 사후 추적할 수 있게 한다.

반환값 규약 (2026-09-17 개정)
-----------------------------
    'g3cf20b3'          커밋 확정 + 작업트리 clean 확인   → 재현 가능
    'g3cf20b3-dirty'    커밋 확정 + 미커밋 변경 있음      → 재현 불가(정직)
    'g3cf20b3-unknown'  커밋은 확정, **clean 여부 판정 실패** → 재현 불가(정직)
    'nogit'             커밋 자체를 못 읽음               → 재현 불가(정직)

`-unknown`을 새로 만든 이유. 예전 코드는

    dirty = _git("status", "--porcelain")
    return f"g{short}-dirty" if dirty else f"g{short}"

였는데 `_git`은 **실패해도 None**을 돌려준다. None은 falsy라 `git status`가
타임아웃/실패한 경우가 "clean"과 같은 취급을 받았다. 즉 작업트리가 더티인데도
결과 파일에 `g<hash>`(=이 커밋 그대로였다)가 박힐 수 있었다.

    nogit          → "버전을 모른다"     → 쓸모없지만 정직
    g<hash> (거짓) → "이 커밋 그대로였다" → **틀린 주장을 확신 있게 함**

후자가 훨씬 나쁘다. 나중에 그 해시로 checkout해 재현을 시도하면 결과가 다른데
이유를 알 수 없고, 재현 실패가 알고리즘 문제인지 기록 오류인지 구별되지 않는다.

frozen(exe) 실행
----------------
PyInstaller 번들에는 `.git`이 없다(`__file__`이 _MEIPASS 임시폴더를 가리킨다).
그러면 `git rev-parse`가 실패해 그 exe로 돌린 **모든** 결과가 `nogit`이 된다.
빌드 시점에 `core/_build_version.py`를 생성해 심으면 frozen에서도 실제 커밋이
남는다 — `tools/stamp_build_version.py` 참고. 있으면 그걸 우선한다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 재현 주장을 할 수 있는 값의 집합. 여기 없으면 "그 결과는 어느 코드로 만들었는지
# 확정할 수 없다"는 뜻이다.
_UNREPRODUCIBLE_SUFFIXES = ("-dirty", "-unknown")


@lru_cache(maxsize=1)
def code_version() -> str:
    """예: 'g3cf20b3' / 'g3cf20b3-dirty' / 'g3cf20b3-unknown' / 'nogit'.

    프로세스 1회만 계산해 캐시한다."""
    stamped = _stamped_version()
    if stamped:
        return stamped

    def _git(*args: str) -> str | None:
        """성공하면 stdout(빈 문자열 포함), 실패하면 **None**. 둘을 섞지 말 것."""
        try:
            out = subprocess.run(
                ["git", *args], cwd=_REPO_DIR,
                capture_output=True, text=True, timeout=10,
                # pythonw(GUI)에서 git.exe가 자기 콘솔창을 띄운다. 알파 저장은
                # 워커 프로세스마다 이걸 부르므로 검은 창이 수십 번 깜빡인다.
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except Exception:
            return None

    short = _git("rev-parse", "--short", "HEAD")
    if not short:
        return "nogit"
    dirty = _git("status", "--porcelain")
    if dirty is None:
        # 판정 실패. clean으로 뭉개면 '이 커밋 그대로였다'는 **거짓 주장**이 된다.
        return f"g{short}-unknown"
    return f"g{short}-dirty" if dirty else f"g{short}"


def _stamped_version() -> str | None:
    """빌드 시점에 심어둔 버전. frozen(exe)에는 `.git`이 없어 git이 안 돈다."""
    try:
        from core import _build_version                      # type: ignore
    except Exception:
        return None
    v = str(getattr(_build_version, "CODE_VERSION", "") or "").strip()
    return v or None


def is_reproducible(version: str | None = None) -> bool:
    """이 버전 문자열로 `git checkout` 해서 결과를 재현할 수 있다고 주장 가능한가."""
    v = code_version() if version is None else version
    if not v or v == "nogit":
        return False
    return not v.endswith(_UNREPRODUCIBLE_SUFFIXES)


def require_reproducible(context: str = "") -> str:
    """재현 불가한 버전이면 **거부**한다. 논문·제출용 산출물을 만드는 경로에서 쓸 것.

    조용한 폴백은 재현성 주장을 무너뜨린다 — 그 결과 파일과 정상 파일이 섞이면
    나중에 어느 쪽이 재현 가능한지 구별되지 않는다."""
    v = code_version()
    if not is_reproducible(v):
        raise RuntimeError(
            f"코드 버전을 확정할 수 없다: {v!r}"
            + (f" ({context})" if context else "")
            + ". 논문/제출용 산출물은 커밋된 clean 작업트리에서 만들 것 "
              "— 결과 파일 헤더의 해시로 checkout해 재현할 수 있어야 한다."
        )
    return v


if __name__ == "__main__":       # 자체검증 — 재현 판정 규약이 뒤집히면 걸린다
    assert is_reproducible("gdeadbee")
    assert not is_reproducible("gdeadbee-dirty")
    assert not is_reproducible("gdeadbee-unknown")
    assert not is_reproducible("nogit")
    assert not is_reproducible("")
    print(f"code_version() = {code_version()!r}  reproducible={is_reproducible()}")
