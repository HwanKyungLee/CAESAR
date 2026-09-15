"""oculus/state_log.py — append-only 상태 로그 (설계문서 §2 원칙2·6, §6).

경보/상태 전이를 한 줄씩 JSONL로 남긴다. 나중에 Augur 확정분석과 대조하기
위한 기록이라 append-only(수정·삭제 없음) — Oculus는 자기 상태만 여기 쓰고
raw나 Augur output/은 절대 건드리지 않는다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

from core.provenance import code_version


class StateLog:
    """append(status, msg, **fields) 한 줄 = 시각+상태 JSON 한 개.

        log = StateLog(r"oculus_state\\status.jsonl")
        log.append("P0", "측정 정지 의심", gap_sec=42.3, file=r"...\\2026-05-26-003.dat")
    """

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def append(self, status: str, msg: str, **fields) -> None:
        # 매 줄에 코드 해시를 박는다 — Augur 확정분석과 사후 대조할 때 "이 숫자가 어느
        # 코드에서 나왔나"가 줄 단위로 확정돼야 한다(현장 PC의 Oculus가 랩 Augur보다
        # 뒤처질 수 있다: tools/bundle_oculus_deps.py USB 배포). code_version()은
        # lru_cache라 프로세스당 git 호출 1회.
        rec = {"ts": datetime.now().isoformat(timespec="seconds"),
               "status": status, "msg": msg, "code": code_version(), **fields}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def tail(self, n: int = 20) -> list:
        """마지막 n개 레코드(대시보드 초기 로그 패널 채우기용). 파일 없으면 빈 리스트."""
        try:
            with open(self.path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except FileNotFoundError:
            return []
        out = []
        for ln in lines[-n:]:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out
