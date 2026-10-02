"""vigil/monitors/clock_monitor.py — 행 시각 vs PC 시계(둘 다 UTC) 감시 (설계 §1.4, VF4).

raw 의 행 시각(bytepack, 연초 기준 센티초)은 **UTC 가 규약**이다. Vigil 은 그 행을 받은 순간의 PC 시계
(epoch = UTC — Windows 시간대 설정과 무관)를 안다. 그 차이 `도착 − 행 시각` 을 계기마다 본다:

  · 거의 정확히 몇 시간(±TZ_TOL) → P2 시간대 변환 실수 의심. 실사건: 2026-05-18~05-29 핫 PC 가 bytepack 을
    UTC 로 안 바꿔 **9 h** 어긋났고, 몇 달 뒤 분석에서야 발견됐다(Augur clock_epoch_offset_sec 가 사후 보정).
  · LAG_WARN 초과 → P2 행이 자기 시각보다 한참 늦게 도착(LabVIEW 멈춤·몰아쓰기)
  · AHEAD_WARN 초과로 미래 → P2 행 시각이 PC 시계보다 앞섬
  · 그 밖 → OK(보통 수 초 — 쓰기·읽기 지연)

판정은 최근 WINDOW 개 표본의 **중앙값**(튀는 한 행으로 경보하지 않는다). 표본은 호출측이 "그 파일을 끝까지
읽은 시점의 마지막 행"만 넣는다 — 시작·일시정지 뒤 밀린 행은 원래 오래된 행이라 '늦게 도착'이 아니다.

한계: Vigil 이 LabVIEW 와 **같은 PC** 에서 돌면 둘이 같은 시계를 쓰므로 PC 시계 자체의 오차(수 분 틀림)는
상쇄돼 안 보인다. 잡는 것은 변환 실수와 지연이다(절대 시각은 외부 기준 — NTP·GPS — 이 있어야 한다).
오경보 위험이 있어 P2 로 시작한다(실측으로 문턱이 확인되면 시간대 실수는 P1 로 올릴 것).
"""
from __future__ import annotations

from collections import deque
from statistics import median
from typing import Optional

from vigil.alert_engine import OK, P2

WINDOW = 15            # 표본 수(≈ 한 계기 15 행)
MIN_SAMPLES = 3
LAG_WARN = 300.0       # s — 행이 자기 시각보다 5분 넘게 늦게 옴
AHEAD_WARN = 60.0      # s — 행 시각이 PC 보다 1분 넘게 미래
TZ_TOL = 600.0         # s — '몇 시간 + 10분 이내' 면 시간대 변환으로 본다


class ClockMonitor:
    """계기 하나의 시각 차이. observe(offset_s) → (status, msg, metrics) | None(표본 부족)."""

    def __init__(self, window: int = WINDOW):
        self.offsets: deque = deque(maxlen=window)

    def observe(self, offset_s: float):
        self.offsets.append(float(offset_s))
        if len(self.offsets) < MIN_SAMPLES:
            return None
        m = median(self.offsets)
        metrics = {"offset_s": m, "n": len(self.offsets)}
        hours = round(m / 3600.0)
        if hours != 0 and abs(m - hours * 3600.0) <= TZ_TOL:
            ahead = "ahead of" if hours < 0 else "behind"
            return P2, (f"row timestamps are ~{abs(hours)} h {ahead} the PC clock — time-zone conversion on the "
                        f"DAQ? (raw time should be UTC; 2026-05 hot PC was 9 h off)"), metrics
        if m > LAG_WARN:
            return P2, (f"rows arrive ~{m / 60:.0f} min after their own timestamp — DAQ stalled or "
                        f"writing in bursts?"), metrics
        if m < -AHEAD_WARN:
            return P2, f"row timestamps are {-m:.0f} s ahead of the PC clock", metrics
        return OK, f"row time vs PC clock {m:+.0f} s", metrics


def offset_seconds(row_time_utc, arrival_local) -> Optional[float]:
    """도착(PC 로컬 naive datetime) − 행 시각(UTC naive datetime) [s]. 하나라도 없으면 None."""
    if row_time_utc is None or arrival_local is None:
        return None
    from datetime import timezone
    arr_utc = arrival_local.astimezone(timezone.utc).replace(tzinfo=None)
    return (arr_utc - row_time_utc).total_seconds()


# ── Row-to-row time sequence (§1.4: backward, jump, rollover gap/overdue) ─────────────────
# Yeosu 2026-06 hot/cold raw: rows 0.8–1.9 s apart inside a file, ~1 s across a rollover,
# span ≤ 3600 s. Real events seen: DAQ restart gaps of 33 s and ~42 min between files.
BACK_TOL = 2.0         # s — row time may wobble this much backwards (bytepack rounding)
JUMP_WARN = 60.0       # s — longer gap between consecutive rows = rows missing / DAQ paused
ROLLOVER_GRACE = 120.0  # s — file longer than cadence.file_rollover_sec + this = rollover overdue
EVENT_HOLD = 600.0     # s (wall) — a backward/jump event stays P2 this long, then clears
_KEEP_FILES = 4


class RowTimeMonitor:
    """One instrument's row-time sequence. observe() per row; status(now) → (status, msg, metrics).

    Inside a file: backward > BACK_TOL or gap > JUMP_WARN. Across files: first row of a newer file
    (by name — catch-up may interleave older files, those get only the in-file check) against the
    last row of the previous one. Rollover overdue from row times alone (no wall clock), so a
    stopped instrument does not trigger it — liveness covers that. All P2: events, not states."""

    def __init__(self, rollover_sec=None, hold_sec: float = EVENT_HOLD):
        self.rollover_sec = rollover_sec
        self.hold_sec = hold_sec
        self.first: dict = {}      # {path: first row time}
        self.last: dict = {}       # {path: last row time}
        self.cur: Optional[str] = None
        self.event = None          # (wall datetime, msg, metrics)

    def _flag(self, now, msg, **metrics):
        self.event = (now, msg, metrics)

    def observe(self, path: str, row_time, now, files_between=None) -> None:
        """files_between(a, b) → True if other raw files sit between a and b (skipped as stale
        backlog, not read yet) — then a gap across them is not a gap in the data."""
        import os
        name = os.path.basename(path)
        prev = self.last.get(path)
        if prev is None:
            self.first[path] = row_time
            if (self.cur is not None and path > self.cur and self.cur in self.last
                    and not (files_between and files_between(self.cur, path))):
                gap = (row_time - self.last[self.cur]).total_seconds()
                if gap > JUMP_WARN:
                    self._flag(now, f"{gap / 60:.0f} min of rows missing between "
                                    f"{os.path.basename(self.cur)} and {name} (DAQ restart or skipped file?)",
                               gap_s=gap)
                elif gap < -BACK_TOL:
                    self._flag(now, f"{name} starts {-gap:.0f} s before {os.path.basename(self.cur)} ended "
                                    f"— row clock went backwards at the rollover", gap_s=gap)
            if self.cur is None or path > self.cur:
                self.cur = path
            for old in sorted(self.last)[:-_KEEP_FILES]:
                self.first.pop(old, None)
                self.last.pop(old, None)
        else:
            dt = (row_time - prev).total_seconds()
            if dt < -BACK_TOL:
                self._flag(now, f"row time went backwards by {-dt:.0f} s inside {name}", gap_s=dt)
            elif dt > JUMP_WARN:
                self._flag(now, f"row time jumped {dt / 60:.1f} min inside {name} (rows missing?)", gap_s=dt)
        self.last[path] = row_time

    def status(self, now):
        import os
        metrics = {}
        if self.cur in self.first and self.rollover_sec:
            span = (self.last[self.cur] - self.first[self.cur]).total_seconds()
            metrics["file_span_s"] = span
            if span > self.rollover_sec + ROLLOVER_GRACE:
                return P2, (f"{os.path.basename(self.cur)} has run {span / 60:.0f} min without a new file "
                            f"(expected every {self.rollover_sec / 60:.0f} min) — rollover stuck?"), metrics
        if self.event is not None and (now - self.event[0]).total_seconds() < self.hold_sec:
            return P2, self.event[1], {**metrics, **self.event[2]}
        if not self.first:
            return None
        return OK, "row times in sequence", metrics
