"""oculus/ingest_cursor.py — 파일별 처리 오프셋 저장/복원 (재시작 견고성).

설계문서 §2 원칙1(증분): 파일 전체를 매번 다시 읽지 않고, 마지막으로 처리한
바이트 오프셋을 기억해 새로 붙은 부분만 읽는다. Oculus가 재시작해도(크래시·
업데이트) 처음부터 다시 읽지 않도록 이 오프셋을 디스크에 영속화한다.

Oculus는 raw를 절대 쓰지 않는다(§2 원칙2) — 커서는 별도 상태 폴더에만 저장한다.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Optional


class IngestCursor:
    """{파일 절대경로: {"offset": int, "mtime": float}} — JSON 파일에 영속화.

        cur = IngestCursor(r"oculus_state\\cursors.json")
        off = cur.get(path)              # 미기록이면 0
        cur.set(path, new_offset, mtime) # 즉시 디스크에 저장(원자적 교체)
    """

    def __init__(self, state_path: str):
        self.state_path = state_path
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                self._data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def _save(self) -> None:
        """원자적 저장(임시파일 → os.replace) — 쓰는 도중 프로세스가 죽어도
        cursors.json이 반쪽짜리로 깨지지 않게."""
        d = os.path.dirname(self.state_path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".cursors_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
            os.replace(tmp, self.state_path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def get(self, path: str) -> int:
        """이 파일의 마지막 처리 오프셋(바이트). 미기록이면 0(처음부터)."""
        entry = self._data.get(os.path.abspath(path))
        return int(entry["offset"]) if entry else 0

    def set(self, path: str, offset: int, mtime: Optional[float] = None) -> None:
        """오프셋 갱신 + 즉시 저장. mtime은 참고용(파일 교체 감지에 쓸 수 있음)."""
        key = os.path.abspath(path)
        self._data[key] = {"offset": int(offset), "mtime": float(mtime or 0.0)}
        self._save()

    def clamp_to_size(self, path: str) -> int:
        """저장된 오프셋이 실제 파일 크기보다 크면(파일이 잘렸다/교체됐다) 0으로
        되돌리고 그 값을 반환. 정상이면 저장된 오프셋을 그대로 반환."""
        off = self.get(path)
        try:
            size = os.path.getsize(path)
        except OSError:
            return off
        if off > size:
            self.set(path, 0)
            return 0
        return off

    def known_files(self) -> list:
        return list(self._data.keys())
