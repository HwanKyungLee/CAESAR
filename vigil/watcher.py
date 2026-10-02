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

import fnmatch
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from vigil.ingest_cursor import IngestCursor
from vigil.profile import Profile, ProfileSet

log = logging.getLogger("vigil")


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

# 파일 목록(2026-10-01, 응답없음 사고): 감시 폴더 아래 .dat 가 13.6만 개(raw 1.3천 + 분석
# 산출물 alpha/·doasis/)인 곳을 가리키자, 파일마다 os.stat 을 따로 불러 tick 하나가 25 s —
# 1초 타이머라 창이 영영 '응답 없음'이었다. 지금은 폴더 나열(os.scandir) 한 번에 크기·수정시각을
# 같이 받는다(Windows 는 나열 결과에 들어 있어 추가 디스크 조회가 없다). 나열 자체가 비싼
# 큰 트리는 전체 나열을 드물게 하고, 사이에는 최근에 바뀌는 파일이 있는 폴더만 다시 본다.
FULL_SCAN_CHEAP_SEC = 0.05       # 전체 나열이 이보다 느리면 '비싼 트리' — 간격을 더 늘린다
FULL_SCAN_MIN_INTERVAL_SEC = 10  # 비싸면 최소 이 간격, 또는 나열 시간의 20배 중 큰 쪽
HUGE_TREE_FILES = 20000          # 이보다 많으면 'raw 폴더만 가리키라'고 한 번 경고
# 활성 파일(2026-10-01, 정상 상태 비용): 전체 나열이 싸도(raw 전용 폴더 ~2천 개 ≈ 50 ms) 매초
# 하면 한 달치 끝난 파일을 매번 다시 본다. LabVIEW 는 채널 폴더마다 1 h 파일 하나만 키우고 새 파일은
# rollover 로 같은 폴더에 생긴다. 그래서 전체 나열은 rescan_sec 마다만 하고, 사이에는
#   - '활성' 파일(최근에 바뀌었거나 아직 덜 읽은 것)만 stat 해서 크기를 보고,
#   - 그 파일들이 있는 폴더는 폴더 mtime(항목이 생기면 바뀜)이 바뀌었거나, 방금까지 자라던 파일이
#     이번 poll 에 안 자랐으면(= rollover 직후일 수 있다) 그 폴더 하나만 다시 나열한다.
# 폴더 mtime 을 믿지 않는 파일시스템(FAT/exFAT·일부 네트워크 공유)이어도 rollover 는 두 번째 규칙이
# 잡고, 그 밖의 놓친 변화는 다음 전체 나열(≤ rescan_sec)이 잡는다 — 늦을 수는 있어도 행이 빠지진 않는다
# (커서는 실제로 읽은 바이트까지만 전진한다).
DEFAULT_RESCAN_SEC = 30.0
ACTIVE_WINDOW_MIN_SEC = 300.0    # 전체 나열 때 mtime 이 이 안(또는 전체 나열 간격 안)에 바뀌었으면 활성
ROLLOVER_WATCH_SEC = 60.0        # 이 안에 자란 적 있는 폴더는 '안 자란 poll' 마다 다시 나열


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


def _first_line(path: str) -> Optional[bytes]:
    """First line (up to 64 KB) — read-only; None if unreadable."""
    try:
        with open(path, "rb") as fh:
            return fh.readline(65536)
    except OSError:
        return None


class Watcher:
    """raw 폴더를 폴링해 새 행을 RowEvent로 낸다. 파일당 커서는 IngestCursor에 위임.

        w = Watcher(watch_dir, ProfileSet.load_default(), IngestCursor(state_path))
        events = w.poll()   # 매 tick 호출. 새 행이 없으면 빈 리스트.
    """

    def __init__(self, watch_dir: str, profiles: ProfileSet, cursor: IngestCursor,
                 file_glob: str = "*.dat",
                 max_bytes_per_tick: int = DEFAULT_MAX_BYTES_PER_TICK,
                 backlog_age_sec: Optional[float] = DEFAULT_BACKLOG_AGE_SEC,
                 cursor_save_interval_sec: float = 0.0,
                 rescan_sec: float = DEFAULT_RESCAN_SEC):
        self.watch_dir = watch_dir
        self.profiles = profiles
        self.cursor = cursor
        self.file_glob = file_glob
        self.max_bytes_per_tick = int(max_bytes_per_tick)
        self.backlog_age_sec = backlog_age_sec   # None 이면 건너뛰지 않음(처음부터 다 읽음)
        # 커서를 디스크에 쓰는 최소 간격. 0 이면 새 행이 있는 poll 마다(파일마다가 아니라 poll 당 1회).
        # 진입점은 몇 초로 둔다 — 매초 원자적 교체는 백신 잠금 경합과 디스크 소모만 늘린다.
        self.cursor_save_interval_sec = cursor_save_interval_sec
        self._last_cursor_save = 0.0
        self._profile_cache: dict = {}   # {path: Profile|False(=매치실패, 재시도 방지)}
        self._warned_dupes: set = set()  # 중복 파일명 경고를 한 번만(폴링 1초 주기)
        self._started = False
        self._truncated = False
        self.skipped_backlog: tuple = (0, 0)   # (파일 수, 바이트) — 시작 시 건너뛴 백로그
        # {path: [profile_id …]} — 열 수는 맞는데 파일명 날짜가 프로파일 date_range 밖이라 감시하지 않는
        # 파일. 진입점이 한 번씩 경고한다(감시하지 않는 상태는 보여야 한다 — 설계 §2).
        self.date_excluded: dict = {}
        # {path: (unrouted rows, last column count)} — rows no profile accepts at all (unknown layout:
        # analysis outputs, another instrument). Dropped once a row of the file routes (a header row
        # is unrouted too). The entry point reports files past a few rows (not monitored — §2).
        self.unknown_layout: dict = {}
        self.catching_up = False               # 직전 poll 이 상한에 닿았다 = 밀린 분량을 따라잡는 중
        self._files: dict = {}                 # {path: (size, mtime)} — 마지막 나열 결과
        self._paths: list = []                 # sorted(self._files) — 목록이 바뀔 때만 다시 정렬
        self._done: dict = {}                  # {path: size} 끝까지 읽은 크기 — 같으면 커서도 안 본다
        # 전체 나열 간격. 0 이면 매 poll 전체 나열(예전 동작). 나열이 비싸면 더 늘린다.
        self.rescan_sec = max(0.0, float(rescan_sec))
        self._interval = self.rescan_sec
        self._next_full = 0.0                  # 다음 전체 나열 시각(monotonic) — 첫 poll 은 항상 전체
        self._active: set = set()              # 전체 나열 사이에 stat 하는 파일(모듈 상단 '활성 파일')
        self._active_sorted: list = []
        self._keep: set = set()                # 활성에서 빼지 않는 파일(살아 있던 폴더의 최신 파일)
        self._dir_mtime: dict = {}             # {폴더: 마지막 나열 직전에 본 폴더 mtime}
        self._dir_grew: dict = {}              # {폴더: 그 폴더 파일이 마지막으로 자란 시각(monotonic)}
        self.huge_tree = 0                     # 경고한 파일 수(0 = 경고 안 함)

    def _scan_dir(self, d: str, recursive: bool, out: dict) -> None:
        """폴더 나열로 (크기, 수정시각)을 같이 받는다 — 파일마다 stat 하지 않는다.
        재귀일 때는 하위 폴더 mtime 도 그 폴더를 나열하기 **전에** 적어 둔다(나열 중 생긴 파일은
        다음 poll 의 폴더 mtime 비교가 잡는다)."""
        try:
            it = os.scandir(d)
        except OSError:
            return
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if recursive:
                            self._dir_mtime[e.path] = e.stat().st_mtime
                            self._scan_dir(e.path, True, out)
                    elif fnmatch.fnmatch(e.name, self.file_glob):
                        st = e.stat()
                        out[e.path] = (st.st_size, st.st_mtime)
                except OSError:
                    continue

    def _set_active(self, paths) -> None:
        self._active = set(paths)
        self._active_sorted = sorted(self._active)

    def _full_scan(self, now: float) -> None:
        t0 = time.perf_counter()
        files: dict = {}
        self._dir_mtime = {}
        try:
            self._dir_mtime[self.watch_dir] = os.stat(self.watch_dir).st_mtime
        except OSError:
            pass
        self._scan_dir(self.watch_dir, True, files)
        dur = time.perf_counter() - t0
        for p, (size, _mt) in files.items():          # 지난 나열보다 자란 파일의 폴더 = 살아 있는 폴더
            old = self._files.get(p)
            if old is not None and size > old[0]:
                self._dir_grew[os.path.dirname(p)] = now
        self._files = files
        self._paths = sorted(files)
        interval = self.rescan_sec
        if dur >= FULL_SCAN_CHEAP_SEC:
            interval = max(interval, FULL_SCAN_MIN_INTERVAL_SEC, 20 * dur)
        self._interval = interval
        self._next_full = now + interval
        self._warn_duplicate_basenames(list(files))
        if len(files) > HUGE_TREE_FILES and not self.huge_tree:
            self.huge_tree = len(files)
            log.warning("watch folder has %s %d files — analysis outputs (not raw) seem mixed in. "
                        "Full listing took %.1f s → now only every %.0f s. Point it at the raw folder only: %s",
                        self.file_glob, len(files), dur, interval, self.watch_dir)

    def _rebuild_active(self) -> None:
        """전체 나열 poll 의 읽기가 끝난 뒤: 최근에 바뀐 파일 + 아직 끝까지 못 읽은 파일만 활성.
        (읽기 뒤라 끝까지 읽은 파일은 _done 에 있다 — 커서를 다시 조회하지 않는다.)"""
        recent = time.time() - max(ACTIVE_WINDOW_MIN_SEC, self._interval)
        # 이번 세션에 자란 적 있는 폴더(= LabVIEW 가 쓰던 채널 폴더)는 측정이 오래 멈춰도 가장 최근
        # 파일 하나를 계속 활성으로 둔다 — 재개해 새 파일이 생기면 전체 나열을 안 기다리고 잡는다.
        newest: dict = {}
        for p, (_size, mtime) in self._files.items():
            d = os.path.dirname(p)
            if d in self._dir_grew and mtime >= newest.get(d, ("", -1e18))[1]:
                newest[d] = (p, mtime)
        self._keep = {p for p, _mt in newest.values()}
        self._set_active([p for p, (size, mtime) in self._files.items()
                          if mtime >= recent or self._done.get(p) != size] + list(self._keep))

    def _quick_refresh(self, now: float) -> None:
        """전체 나열 사이: 활성 파일만 stat, 그 폴더들은 필요할 때만 다시 나열."""
        grew: set = set()
        gone = []
        for p in self._active_sorted:
            try:
                st = os.stat(p)
            except OSError:
                gone.append(p)                        # 지워졌거나 이름이 바뀜 — 다음 전체 나열이 확인
                continue
            old = self._files.get(p)
            if old is None or st.st_size != old[0]:
                d = os.path.dirname(p)
                grew.add(d)
                self._dir_grew[d] = now
            self._files[p] = (st.st_size, st.st_mtime)
        changed = bool(gone)
        for p in gone:
            self._active.discard(p)
            self._files.pop(p, None)
        new_active = []
        for d in {os.path.dirname(p) for p in self._active}:
            try:
                dmt = os.stat(d).st_mtime
            except OSError:
                continue
            rolled = d not in grew and now - self._dir_grew.get(d, -1e18) <= ROLLOVER_WATCH_SEC
            if dmt == self._dir_mtime.get(d) and not rolled:
                continue
            self._dir_mtime[d] = dmt                  # 나열 **전** 값 — 나열 중 생긴 파일은 다음 poll 이 잡는다
            fresh: dict = {}
            self._scan_dir(d, False, fresh)
            for p, (size, mtime) in fresh.items():
                old = self._files.get(p)
                if old is None or old[0] != size:     # 새 파일(rollover)·크기 바뀐 파일 → 활성
                    new_active.append(p)
                    if old is None:
                        changed = True
                self._files[p] = (size, mtime)
        if new_active:
            self._active.update(new_active)
        if changed or new_active:
            self._active_sorted = sorted(self._active)
        if changed:
            self._paths = sorted(self._files)

    def _dirs_changed(self) -> bool:
        """No active file (empty folder, or DAQ stopped before this session saw anything grow): the
        quick refresh had nothing to look at, so the first new file waited for the next full listing —
        12–29 s (audit 2026-10-02). Instead stat the folders of the last listing (a new entry changes its
        folder's mtime) and list again as soon as one changed.
        # ponytail: one stat per folder per poll; only while nothing is active. If a huge idle tree has
        # thousands of folders, stat just the root and the newest few."""
        for d, mt in self._dir_mtime.items():
            try:
                if os.stat(d).st_mtime != mt:
                    return True
            except OSError:
                return True                           # folder gone — re-list
        return False

    def _refresh_files(self) -> bool:
        """True = 이번이 전체 나열."""
        now = time.monotonic()
        # (cheap trees only: on a tree whose listing is slow, a churning folder would re-list every poll)
        if now >= self._next_full or (not self._active and self._interval <= self.rescan_sec
                                      and self._dirs_changed()):
            self._full_scan(now)
            return True
        self._quick_refresh(now)
        return False

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
            # 파일 중간의 짧은(잘린·깨진) 행 — 캐시된 프로파일로 넘기면 HK 평가가 IndexError 를 내
            # 그 tick 의 행(~80개)이 통째로 버려졌다(2026-10-02 리뷰). 그 행만 미배정으로.
            # raw_parser 의 `len(toks) < ncols` 가드와 같은 뜻.
            return cached if cached.match.col_compatible(n_columns) else None
        prof = self.profiles.route(filename=os.path.basename(path), n_columns=n_columns)
        if prof is not None:
            self._profile_cache[path] = prof
            self.unknown_layout.pop(path, None)
        if (prof is None or not prof.is_mission) and path not in self.date_excluded:
            # 이 열 수의 미션(셀 정체)이 이 날짜를 안 덮는다 — 기본(구조) 프로파일로 감시되거나(농도·R 없음)
            # 기본도 없으면 미배정. 진입점이 파일마다 한 번 알린다.
            ids = self.profiles.date_excluded(os.path.basename(path), n_columns)
            if ids:
                self.date_excluded[path] = ids
            elif prof is None:
                # No profile of any layer accepts this column count: unknown layout (a base-profile
                # route is monitored, so it is not counted here).
                self.unknown_layout[path] = (self.unknown_layout.get(path, (0,))[0] + 1, n_columns)
        return prof

    def _skip_stale_backlog(self, paths: list) -> None:
        """첫 poll 한 번만: 커서 없고 오래된 파일은 커서를 파일 끝으로 둔다(모듈 docstring 2)."""
        if self.backlog_age_sec is None:
            return
        cutoff = time.time() - self.backlog_age_sec
        n = nbytes = n_shrunk = 0
        for path in paths:
            if path not in self._files:
                continue
            size, mtime = self._files[path]          # 나열 결과 — 파일마다 stat 하지 않는다
            if mtime >= cutoff:
                continue
            if self.cursor.has(path):
                # 다 읽은 오래된 파일 — 재시작해도 이 규칙이 같은 값(파일 끝)을 다시 만든다.
                # 옛 버전이 써 둔 백로그 항목도 여기서 디스크에서 빠진다(cursors.json 축소).
                if self.cursor.get(path) == size:
                    self.cursor.mark_ephemeral(path)
                    n_shrunk += 1
                continue
            # 디스크에는 안 쓴다 — 13.6만 파일 폴더에서 cursors.json 이 20 MB·저장 1.26 s 가 됐다
            self.cursor.set(path, size, mtime=mtime, save=False, persist=False)
            n += 1
            nbytes += size
        if n or n_shrunk:
            self.cursor.save()
        self.skipped_backlog = (n, nbytes)

    def write_age(self, path: str) -> Optional[float]:
        """마지막 나열 때 본 파일 mtime 이 지금부터 몇 초 전인가(모르면 None)."""
        ent = self._files.get(path)
        return None if ent is None else time.time() - float(ent[1])

    def at_end(self, path: str) -> bool:
        """이 파일을 (마지막 poll 시점 크기까지) 끝까지 읽었나 — 그때 마지막 행이 계기가 쓴 최신 행이다."""
        ent = self._files.get(path)
        return ent is not None and self.cursor.get(path) >= ent[0]

    def _read_new_lines(self, path: str, max_bytes: Optional[int] = None,
                        size: Optional[int] = None) -> list:
        """오프셋 이후 **완성된** 줄만 읽고 커서를 그만큼만 전진시킨다.
        max_bytes 가 있으면 그만큼만 읽는다(단, 완성된 줄이 하나는 나오도록 필요하면 더 읽음).
        size 를 주면(폴더 나열 결과) 크기를 다시 묻지 않는다."""
        self._truncated = False
        if size is None:
            offset, size = self.cursor.offset_and_size(path)
        else:
            offset = self.cursor.get(path)
            if offset > size:                         # 잘렸거나 교체됨 — 처음부터
                self.cursor.set(path, 0)
                offset = 0
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
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        self.cursor.set(path, offset + complete_len, mtime=mtime, save=False)
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
        폴링이 1초 주기라 **경고한 파일명은 기억해 두고 다시 찍지 않는다.**

        A copy = same name, same size and same first line. Hot/ and cold/ trees name their hourly files
        alike (2026-06-01-001.dat in both) — that is the normal setup, not a copy (audit 2026-10-02:
        false warning). Sizes are compared first; only equal non-empty sizes open the files."""
        seen: dict = {}
        for p in paths:
            seen.setdefault(os.path.basename(p), []).append(p)
        shown = hidden = 0
        for name, group in seen.items():
            if len(group) < 2 or name in self._warned_dupes:
                continue
            by_key: dict = {}
            for p in group:
                size = self._files[p][0]
                if size:                              # two fresh empty files (rollover) are not copies
                    by_key.setdefault(size, []).append(p)
            copies = []
            for same in by_key.values():
                if len(same) > 1:
                    heads: dict = {}
                    for p in same:
                        heads.setdefault(_first_line(p), []).append(p)
                    copies += [g for k, g in heads.items() if k is not None and len(g) > 1]
            if not copies:
                continue
            self._warned_dupes.add(name)
            if shown < 20:                            # 산출물 폴더가 섞이면 수천 건 — 로그를 덮지 않게
                shown += 1
                group = [p for g in copies for p in g]
                log.warning("same file name in %d places — the same scan is collected twice: %s | %s",
                            len(group), name, " | ".join(group))
            else:
                hidden += 1
        if hidden:
            log.warning("%d more duplicate file names (omitted) — narrow the watch folder to the raw folder", hidden)


    def poll(self) -> list:
        """한 tick: 감시폴더의 파일들에서 새 행을 모아 RowEvent 리스트로 반환.
        이번 tick 에 읽는 총량은 max_bytes_per_tick 까지 — 남은 건 다음 tick 에."""
        events: list = []
        full = self._refresh_files()
        if not self._started:
            self._skip_stale_backlog(self._paths)
            self._started = True
        # 전체 나열 poll 은 모든 파일, 사이에는 활성 파일만(둘 다 정렬 순서 — 상한 배분이 같다)
        paths = self._paths if full else self._active_sorted
        budget = self.max_bytes_per_tick
        pending = False
        for path in paths:
            if budget <= 0:
                pending = True
                break
            size = self._files[path][0]
            if self._done.get(path) == size:
                continue                              # 지난번 끝까지 읽었고 크기 그대로 — 커서 조회도 생략
            before = self.cursor.get(path)            # (13.6만 파일에 매 tick 조회하면 200 ms)
            if before == size:
                self._done[path] = size               # 새로 붙은 게 없다 — 열지 않는다
                continue                              # (커서 > 크기 = 잘린 파일은 읽기에서 0 으로)
            lines = self._read_new_lines(path, max_bytes=budget, size=size)
            after = self.cursor.get(path)
            budget -= max(0, after - before)
            if after == size:
                self._done[path] = size
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
        if full:
            self._rebuild_active()
        elif self._active_sorted:
            # 끝까지 읽었고 오래된 파일은 활성에서 뺀다(첫 poll 의 큰 백로그가 끝난 뒤 비용이 줄어든다)
            recent = time.time() - max(ACTIVE_WINDOW_MIN_SEC, self._interval)
            idle = [p for p in self._active_sorted if p not in self._keep
                    and self._done.get(p) == self._files[p][0] and self._files[p][1] < recent]
            if idle:
                self._active.difference_update(idle)
                self._active_sorted = sorted(self._active)
        now = time.monotonic()
        if now - self._last_cursor_save >= self.cursor_save_interval_sec:
            if self.cursor.flush():
                self._last_cursor_save = now
        return events
