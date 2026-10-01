"""vigil/watcher.py — Ingest Watcher (설계문서 §1.4, §2, §4).

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

메모리 상한(2026-10-01, 현장 PC 다운 사고): 예전엔 커서 없는 파일을 처음부터 끝까지
**한 tick 에 전부** 읽어 행마다 float 리스트로 만들었다. 핫 행 6181열 ≈ 200 KB/행이라
한 시간치 백로그가 ~0.7 GB, 캠페인 폴더 전체면 수십 GB — 켜자마자 GUI 가 멈추고 메모리가
바닥나 LabVIEW 와 함께 PC 가 죽었다. 지금은 두 겹으로 막는다:
  1. tick 당 읽는 바이트에 상한(`max_bytes_per_tick`) — 밀린 분량은 여러 tick 에 나눠
     따라잡는다(커서는 실제로 소비한 완성된 줄까지만 전진하므로 빠지는 행은 없다).
  2. 시작 시점에 커서가 없고 `backlog_age_sec` 넘게 안 바뀐 파일은 끝에서 시작한다.
     실시간 감시기라 지난 데이터는 볼 이유가 없다(사후 분석은 Augur 몫). 건너뛴 건
     `skipped_backlog` 로 남겨 진입점이 로그에 적는다 — 조용히 버리지 않는다.
"""
from __future__ import annotations

import glob
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from vigil.ingest_cursor import IngestCursor
from vigil.profile import Profile, ProfileSet


@dataclass
class RowEvent:
    """새로 관측된 raw 한 행. 감시 계층(liveness/HK/R/농도)의 공통 입력."""
    file: str
    profile_id: Optional[str]
    flag: Optional[int]
    role: Optional[str]          # profile.flag_role(flag) — 'sampling'|'za_inject'|... or None
    row_time: Optional[datetime]  # bytepack에서 복원한 행 내부 시각 (프로파일 매치 실패시 None)
    arrival_time: datetime        # Vigil이 이 행을 관측한 벽시계 시각(now()) — liveness 기준
    row: list                    # 파싱된 float 행 전체(HK/채널 판독용)


_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

# 핫 행 텍스트 ≈ 45–60 KB → 4 MB ≈ 70–90 행/tick(파싱 후 ~15 MB). 1 h 파일(~160 MB)을
# ~40 s 에 따라잡는다. 정상 유입은 ~50 KB/s 라 상한에 닿지 않는다.
DEFAULT_MAX_BYTES_PER_TICK = 4 * 1024 * 1024
# 시작 시 커서 없는 파일 중 이보다 오래 안 바뀐 건 끝에서 시작(1 h 파일 rollover 주기).
DEFAULT_BACKLOG_AGE_SEC = 3600.0
_EXTEND_BYTES = 1024 * 1024   # 상한 안에 개행이 하나도 없을 때(행 하나가 상한보다 김) 더 읽는 단위


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
                 file_glob: str = "*.dat",
                 max_bytes_per_tick: int = DEFAULT_MAX_BYTES_PER_TICK,
                 backlog_age_sec: Optional[float] = DEFAULT_BACKLOG_AGE_SEC):
        self.watch_dir = watch_dir
        self.profiles = profiles
        self.cursor = cursor
        self.file_glob = file_glob
        self.max_bytes_per_tick = int(max_bytes_per_tick)
        self.backlog_age_sec = backlog_age_sec   # None 이면 건너뛰지 않음(처음부터 다 읽음)
        self._profile_cache: dict = {}   # {path: Profile|False(=매치실패, 재시도 방지)}
        self._warned_dupes: set = set()  # 중복 파일명 경고를 한 번만(폴링 1초 주기)
        self._started = False
        self._truncated = False
        self.skipped_backlog: tuple = (0, 0)   # (파일 수, 바이트) — 시작 시 건너뛴 백로그
        self.catching_up = False               # 직전 poll 이 상한에 닿았다 = 밀린 분량을 따라잡는 중

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

    def _skip_stale_backlog(self, paths: list) -> None:
        """첫 poll 한 번만: 커서 없고 오래된 파일은 커서를 파일 끝으로 둔다(모듈 docstring 2)."""
        if self.backlog_age_sec is None:
            return
        cutoff = time.time() - self.backlog_age_sec
        n = nbytes = 0
        for path in paths:
            if self.cursor.has(path):
                continue
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_mtime < cutoff:
                self.cursor.set(path, st.st_size, mtime=st.st_mtime, save=False)
                n += 1
                nbytes += st.st_size
        if n:
            self.cursor.save()
        self.skipped_backlog = (n, nbytes)

    def _read_new_lines(self, path: str, max_bytes: Optional[int] = None) -> list:
        """오프셋 이후 **완성된** 줄만 읽고 커서를 그만큼만 전진시킨다.
        max_bytes 가 있으면 그만큼만 읽는다(단, 완성된 줄이 하나는 나오도록 필요하면 더 읽음)."""
        self._truncated = False
        offset, size = self.cursor.offset_and_size(path)
        if size is not None and offset >= size:
            return []   # 새로 붙은 게 없으면 열지도 않는다(폴링 1초 × 파일 수)
        try:
            with open(path, "rb") as fh:
                fh.seek(offset)
                if max_bytes is None or (size is not None and size - offset <= max_bytes):
                    chunk = fh.read()
                else:
                    chunk = fh.read(max_bytes)
                    while len(chunk) >= max_bytes and b"\n" not in chunk:
                        more = fh.read(_EXTEND_BYTES)
                        if not more:
                            break
                        chunk += more
                    self._truncated = bool(fh.read(1))   # 상한 때문에 남긴 게 있다
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

    def _warn_duplicate_basenames(self, paths: list) -> None:
        """같은 파일명이 감시 트리에 두 번 이상 있으면 **한 번만** 경고한다.

        `**` 재귀 glob이라 감시폴더 밑에 사본 폴더가 있으면 같은 스캔을 두 번
        수집한다 — 실측: `CAESAR_Cold/2026-06/KRISS_10ppm - 복사본/` 이
        `KRISS_10ppm/` 의 사본이라 2026-06-02-009/010/011 이 두 번 들어온다
        (liveness·추세 지표가 그만큼 부풀고, 파일 간 시각 연속성에 가짜 역행이 생긴다).

        **지우거나 건너뛰지 않는다**(무결성 헌장: 지우지 말고 flag). 어느 쪽이
        진짜인지는 코드가 알 수 없고, 과필터링이 부족한 필터링보다 위험하다.
        운용자가 사본 폴더를 치우거나 watch_dir 을 좁히면 경고가 사라진다.
        폴링이 1초 주기라 **경고한 파일명은 기억해 두고 다시 찍지 않는다.**"""
        seen: dict = {}
        for p in paths:
            seen.setdefault(os.path.basename(p), []).append(p)
        for name, group in seen.items():
            if len(group) > 1 and name not in self._warned_dupes:
                self._warned_dupes.add(name)
                print(f"[vigil][WARN] 같은 파일명이 {len(group)}곳에 있다 — "
                      f"같은 스캔을 중복 수집한다: {name}")
                for p in group:
                    print(f"[vigil][WARN]     {p}")


    def poll(self) -> list:
        """한 tick: 감시폴더의 파일들에서 새 행을 모아 RowEvent 리스트로 반환.
        이번 tick 에 읽는 총량은 max_bytes_per_tick 까지 — 남은 건 다음 tick 에."""
        events: list = []
        pattern = os.path.join(self.watch_dir, "**", self.file_glob)
        paths = sorted(glob.glob(pattern, recursive=True))
        self._warn_duplicate_basenames(paths)
        if not self._started:
            self._skip_stale_backlog(paths)
            self._started = True
        budget = self.max_bytes_per_tick
        pending = False
        for path in paths:
            if budget <= 0:
                pending = True
                break
            before = self.cursor.get(path)
            lines = self._read_new_lines(path, max_bytes=budget)
            budget -= max(0, self.cursor.get(path) - before)
            pending = pending or self._truncated
            for line in lines:
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
        self.catching_up = pending
        return events
