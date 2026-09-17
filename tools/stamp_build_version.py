"""빌드 직전에 커밋 해시를 `core/_build_version.py`로 심는다.

왜 필요한가 — PyInstaller 번들에는 `.git`이 없다. `core/provenance.code_version()`
이 `git rev-parse`를 못 돌려 그 exe로 만든 **모든** 결과가 `nogit`으로 찍히고,
"결과 파일 헤더의 해시로 checkout해서 재현한다"는 장치가 통째로 무력해진다.

사용:
    python tools/stamp_build_version.py && pyinstaller Oculus.spec

생성 파일은 `.gitignore` 대상이다(빌드 산출물). 심을 값이 재현 불가
(`-dirty`/`-unknown`/`nogit`)면 **거부**한다 — 그런 빌드로 만든 결과는 어차피
재현할 수 없고, 그 사실을 빌드 시점에 아는 게 결과가 쌓인 뒤보다 낫다.
`--allow-dirty`로 개발 빌드는 통과시킬 수 있다(그 값 그대로 심는다).
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.provenance import code_version, is_reproducible   # noqa: E402

OUT = os.path.join(ROOT, "core", "_build_version.py")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-dirty", action="store_true",
                    help="재현 불가한 버전도 그대로 심는다(개발 빌드용)")
    args = ap.parse_args()

    v = code_version()
    if not is_reproducible(v) and not args.allow_dirty:
        print(f"[stamp] 거부: 코드 버전이 재현 불가다 ({v!r}). "
              f"커밋하고 다시 빌드하거나 --allow-dirty 를 줄 것.", file=sys.stderr)
        return 1
    with open(OUT, "w", encoding="utf-8") as f:
        f.write('"""빌드 시점에 자동 생성됨 — 손으로 고치지 말 것 '
                '(tools/stamp_build_version.py)."""\n')
        f.write(f'CODE_VERSION = "{v}"\n')
    print(f"[stamp] {OUT} <- {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
