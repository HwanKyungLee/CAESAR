"""vigil/record.py — 1분 요약 기록(가벼운 바이너리, 2026-10-01).

Vigil 은 분석기가 아니라 감시기다. 그래도 창을 닫으면 그동안의 농도·R·램프·HK 추세가 다 사라져서,
며칠에 걸친 하드웨어 열화(램프 세기 감소, 거울 R 하락, 온도 드리프트)를 나중에 볼 수 없었다
(status.jsonl 은 상태가 **바뀔 때만** 남는다). 그래서 1분에 한 줄, 그 순간의 "최신값"만 남긴다 —
새 계산은 없다(감시기가 이미 낸 값을 복사할 뿐).

형식 — 문자열 변환 없는 고정 길이 레코드(쓰기가 가장 가볍고 CSV 의 절반 이하 크기):
    <state_dir>/records/YYYY-MM-DD[_N].vrec       레코드 = float64 epoch(UTC 초) + float32 × 열 수 (리틀엔디언)
    <state_dir>/records/YYYY-MM-DD[_N].vrec.json  {"version":1, "columns":[...], "interval_sec":60, ...}
  · 값이 없으면 NaN. 상태 열(overall)은 0=OK 1=P2 2=P1 3=P0, NaN=판정 없음.
  · 열 구성이 바뀌면(감시 폴더·프로파일 변경) 같은 날이라도 새 파일(_2, _3 …)로 시작한다.
  · 레코드 길이가 고정이라 마지막 줄이 정전으로 잘려도 앞 기록은 그대로 읽힌다(잘린 꼬리는 버림).
읽기: `read_records(path)` → (columns, times[epoch], values[n×cols]),
      CSV 로 뽑기: `python -m vigil.record <파일.vrec> [--csv out.csv] [--tz 9]`
"""
from __future__ import annotations

import json
import logging
import math
import os
import struct
from datetime import datetime, timezone

log = logging.getLogger("vigil")

VERSION = 1
STATUS_CODE = {"OK": 0.0, "P2": 1.0, "P1": 2.0, "P0": 3.0}


class MinuteRecorder:
    """`maybe_write(now_epoch, values)` 를 매 tick 불러도 된다 — interval 경계마다 한 줄만 쓴다."""

    def __init__(self, state_dir: str, interval_sec: float = 60.0):
        self.dir = os.path.join(state_dir, "records")
        self.interval = float(interval_sec)
        self._slot = None          # 마지막으로 쓴 interval 칸 번호
        self._path = None
        self._columns = None

    def maybe_write(self, now_epoch: float, values: dict) -> bool:
        """values: {열 이름: 값(float|None)} — 순서가 열 순서. 이번 interval 칸에 이미 썼으면 False."""
        slot = int(now_epoch // self.interval)
        if slot == self._slot or not values:
            return False
        self._slot = slot
        columns = list(values)
        day = datetime.fromtimestamp(now_epoch, tz=timezone.utc).strftime("%Y-%m-%d")
        try:
            if self._columns != columns or self._path is None or not os.path.basename(self._path).startswith(day):
                self._open(day, columns)
            row = [float(values[c]) if values[c] is not None else math.nan for c in columns]
            with open(self._path, "ab") as fh:
                fh.write(struct.pack(f"<d{len(row)}f", float(now_epoch), *row))
            return True
        except (OSError, ValueError) as e:       # 기록 실패가 감시를 멈추면 안 된다
            log.warning("minute record write failed: %s", e)
            return False

    def _open(self, day: str, columns: list) -> None:
        os.makedirs(self.dir, exist_ok=True)
        n = 1
        while True:
            stem = day if n == 1 else f"{day}_{n}"
            path = os.path.join(self.dir, stem + ".vrec")
            meta_path = path + ".json"
            if not os.path.exists(meta_path):
                break
            try:
                with open(meta_path, encoding="utf-8") as fh:
                    if json.load(fh).get("columns") == columns:
                        break               # 같은 열 구성이면 이어 쓴다(재시작)
            except ValueError:              # 깨진 메타(쓰다 죽음) — 그 파일은 두고 다음 번호로
                log.warning("minute record meta unreadable, starting a new file: %s", meta_path)
            n += 1
        if not os.path.exists(meta_path):
            meta = {"version": VERSION, "columns": columns, "interval_sec": self.interval,
                    "record": "float64 epoch_utc_s + float32 x len(columns), little-endian",
                    "status_codes": STATUS_CODE, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            tmp = meta_path + ".tmp"        # 원자적 — 쓰다 죽어도 깨진 메타가 남지 않게
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, meta_path)
        else:
            # 이어 쓰기 전에 잘린 꼬리(정전으로 반쯤 쓴 레코드)를 레코드 경계로 자른다. 안 그러면
            # 뒤에 붙는 레코드가 전부 어긋나 그날 나머지가 쓰레기로 읽힌다. 잘라내는 바이트는
            # 원래도 read_records 가 버리는, 값이 될 수 없는 조각이다.
            rec = 8 + 4 * len(columns)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            if size % rec:
                with open(path, "r+b") as fh:
                    fh.truncate(size - size % rec)
                log.warning("minute record had a torn last record (%d bytes) — trimmed before appending: %s",
                            size % rec, path)
        self._path, self._columns = path, columns


def read_records(path: str):
    """(columns, times, values) — times: float64 epoch(UTC), values: float32 (n, len(columns))."""
    import numpy as np
    with open(path + ".json", encoding="utf-8") as fh:
        columns = json.load(fh)["columns"]
    dt = np.dtype([("t", "<f8"), ("v", "<f4", (len(columns),))])
    raw = open(path, "rb").read()
    n = len(raw) // dt.itemsize            # 잘린 꼬리(정전 등)는 버린다
    rec = np.frombuffer(raw[:n * dt.itemsize], dtype=dt)
    return columns, rec["t"].copy(), rec["v"].copy()


def _main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Read a Vigil minute record (.vrec); print a summary or export CSV")
    ap.add_argument("path")
    ap.add_argument("--csv", help="write CSV here")
    ap.add_argument("--tz", type=float, default=9.0, help="hours to add to UTC for the time column (default 9 = KST)")
    a = ap.parse_args(argv)
    cols, t, v = read_records(a.path)
    if a.csv:
        import csv
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow([f"time (UTC{a.tz:+g})"] + cols)
            for ti, row in zip(t, v):
                ts = datetime.fromtimestamp(ti + a.tz * 3600, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                w.writerow([ts] + ["" if math.isnan(x) else f"{x:.6g}" for x in row])
        print(f"wrote {len(t)} rows → {a.csv}")
    else:
        print(f"{len(t)} records, {len(cols)} columns: {', '.join(cols)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
