"""oculus/watcher.py — Ingest Watcher (설계문서 §1.4, §2, §4).

raw 폴더를 폴링해 새로 append된 완성된 줄만 읽어 RowEvent로 흘려보낸다.

폴링 vs watchdog: 설계문서는 "watchdog 또는 폴링"이라 적었지만, 케이던스가
초당 1행(§0-A.2)이라 1초 폴링으로 충분하고, `watchdog`는 이 저장소의 의존성이
아니다(`requirements.txt`에 없음) — 새 의존성을 넣을 만큼 폴링이 부족하지 않아
폴링으로 구현한다. 필요해지면 watchdog로 교체 가능(폴링 결과와 같은
`RowEvent`를 내면 됨).

읽기 전용·무간섭(§2 원칙2): raw 파일은 열어서 읽기만 한다. DAQ가 파일을 쓰는
중에도 안전해야 하므로, **완성된 줄만** 소비한다 — 마지막 줄이 개행으로 안
끝나면(DAQ가 그 줄을 쓰는 중) 커서를 그 줄 시작까지만 전진시키고 다음 폴링에
다시 읽는다.
"""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from oculus.ingest_cursor import IngestCursor
from oculus.profile import Profile, ProfileSet


@dataclass
class RowEvent:
    """새로 관측된 raw 한 행. 감시 계층(liveness/HK/R/농도)의 공통 입력."""
    file: str
    profile_id: Optional[str]
    flag: Optional[int]
    role: Optional[str]          # profile.flag_role(flag) — 'sampling'|'za_inject'|... or None
    row_time: Optional[datetime]  # bytepack에서 복원한 행 내부 시각 (프로파일 매치 실패시 None)
    arrival_time: datetime        # Oculus가 이 행을 관측한 벽시계 시각(now()) — liveness 기준
    row: list                    # 파싱된 float 행 전체(HK/채널 판독용)


_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _year_from_filename(path: str, default: Optional[int] = None) -> int:
    m = _DATE_RE.search(os.path.basename(path))
    if m:
        return int(m.group(1))
    return default if default is not None else datetime.now().year


def _parse_row(line: str) -> Optional[list]:
    """한 줄 → float 리스트. 헤더/주석/빈줄/파싱실패는 None(raw_parser와 같은 관례)."""
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    toks = s.split("\t") if "\t" in s else s.split()
    try:
        return [float(t) for t in toks]
    except ValueError:
        return None


class Watcher:
    """raw 폴더를 폴링해 새 행을 RowEvent로 낸다. 파일당 커서는 IngestCursor에 위임.

        w = Watcher(watch_dir, ProfileSet.load_default(), IngestCursor(state_path))
        events = w.poll()   # 매 tick 호출. 새 행이 없으면 빈 리스트.
    """

    def __init__(self, watch_dir: str, profiles: ProfileSet, cursor: IngestCursor,
                 file_glob: str = "*.dat"):
        self.watch_dir = watch_dir
        self.profiles = profiles
        self.cursor = cursor
        self.file_glob = file_glob
        self._profile_cache: dict = {}   # {path: Profile|False(=매치실패, 재시도 방지)}

    def _route(self, path: str, n_columns: int) -> Optional[Profile]:
        """성공만 캐시한다. LabVIEW가 파일 첫 행에 쓰는 flag=0 헤더행은 데이터행보다
        열이 몇 개 적어(핫 실측: 헤더 6177 vs 데이터 6181) 어느 프로파일과도 열수가
        안 맞는다. 실패를 캐시하면 그 한 행 때문에 파일 전체가 영구 스킵된다 —
        실제로 2026-08-10-001.dat 304행이 통째로 미배정됐다.
        # ponytail: 어느 프로파일과도 안 맞는 파일은 매 행 route()를 다시 탄다.
        # route()가 짧아 지금은 무시할 만하다. 감시 폴더에 남의 포맷 파일이 많이
        # 섞이면 '연속 N행 실패 시 캐시' 같은 걸 넣을 것."""
        cached = self._profile_cache.get(path)
        if cached is not None:
            return cached
        prof = self.profiles.route(filename=os.path.basename(path), n_columns=n_columns)
        if prof is not None:
            self._profile_cache[path] = prof
        return prof

    def _read_new_lines(self, path: str) -> list:
        """오프셋 이후 **완성된** 줄만 읽고 커서를 그만큼만 전진시킨다."""
        offset = self.cursor.clamp_to_size(path)
        try:
            with open(path, "rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
        except OSError:
            return []
        if not chunk:
            return []
        # 마지막 조각이 개행으로 안 끝나면 그 줄은 아직 쓰는 중 — 버리고 오프셋도 그만큼 뺀다.
        complete_len = len(chunk)
        if not chunk.endswith(b"\n"):
            last_nl = chunk.rfind(b"\n")
            complete_len = last_nl + 1  # last_nl==-1이면 0(완성된 줄 없음)
            chunk = chunk[:complete_len]
        if complete_len == 0:
            return []
        self.cursor.set(path, offset + complete_len, mtime=os.path.getmtime(path))
        text = chunk.decode("utf-8", errors="replace")
        return text.split("\n")[:-1]   # split 끝의 빈 문자열(마지막 \n 뒤) 제거

    def poll(self) -> list:
        """한 tick: 감시폴더의 모든 파일에서 새 행을 모아 RowEvent 리스트로 반환."""
        events: list = []
        pattern = os.path.join(self.watch_dir, "**", self.file_glob)
        for path in sorted(glob.glob(pattern, recursive=True)):
            for line in self._read_new_lines(path):
                row = _parse_row(line)
                if row is None:
                    continue
                prof = self._route(path, len(row))
                flag = role = row_time = None
                if prof is not None:
                    try:
                        flag = int(row[prof.header.state_flag_col])
                        role = prof.flag_role(flag)
                        year = _year_from_filename(path)
                        row_time = prof.header.time_bytepack.to_datetime(row, year)
                    except (IndexError, ValueError):
                        pass
                events.append(RowEvent(
                    file=path,
                    profile_id=(prof.profile_id if prof is not None else None),
                    flag=flag, role=role, row_time=row_time,
                    arrival_time=datetime.now(), row=row,
                ))
        return events
