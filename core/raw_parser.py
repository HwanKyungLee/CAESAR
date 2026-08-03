"""core/raw_parser.py
====================

CAESAR Araon Mega-Matrix raw .dat parser.

This module is the **single source of truth** for column layout. Every other
module that reads raw data should go through here rather than hardcoding
column indices.

Layout (verified against 2026-05 Yeosu campaign data + 박사님
`read_data_CAESAR_Araon_2025_3ch.m`):

::

  col  0      : LabVIEW timestamp byte-pack HIGH 16 bits (uint16) — bytepack=(col0<<16)|col1
  col  1      : LabVIEW timestamp byte-pack LOW 16 bits (uint16)
                (필드/상수명 time_lo·COL_TIME_LO 등은 역사적 오명 — 수식이 정본이며
                 기준 .mat doy와 std=0.0000s 일치 검증됨. 이름만 보고 순서 바꾸지 말 것)
  col  2      : exposure (centiseconds? unit unclear, MATLAB calls it 'ms')
  col  3      : tempccd (CCD temp, ÷100 = °C)
  col  4      : state flag (1=Atmosphere, 500=ZA, 510=He, 502/512=wait, 503/513=end)
  col  5–2052 : ** EMPTY / NOISE in 2026 ** (was ch3 in 박사님 2025 3-channel build)
  col 2053–4100: PRIMARY spectrum  — Cold: NO2 cell.   Hot: PNs cell ("좌측")
  col 4101–6148: SECONDARY spectrum — Hot only: ANs cell ("우측"). Cold: noise.
  col 6149+   : HK block (housekeeping). Cold: 30 cols. Hot: 32 cols.

Verified by VALUE-INSPECTION (2026-05-25-001 Cold, 2026-05-26-001 Hot):
  * Cold block (5:2053): max ≈ 758  → noise (dark floor ~713)
  * Cold block (2053:4101): max ≈ 35839 → SIGNAL (Cold cavity NO2)
  * Cold block (4101:6149): max ≈ 839  → noise
  * Hot block (5:2053): max ≈ 981   → noise (dark floor ~922)
  * Hot block (2053:4101): max ≈ 50608 → SIGNAL (PNs cavity, 박사님 "좌측")
  * Hot block (4101:6149): max ≈ 38024 → SIGNAL (ANs cavity, 박사님 "우측")

HK relative offsets (within the 6149+ block; verified by VALUE-INSPECTION on
2026-05-26-001 Hot + 2026-05-25-001 Cold):

  Hot file (6181 cols total):
    rel  0 (col 6149) : templed1            ÷100 = °C
    rel  1 (col 6150) : templed2            ÷100
    rel  2 (col 6151) : ANs oven setpoint   ÷100 ≈ 300 °C  [MATLAB:'templed3']
    rel  4 (col 6153) : preheater temp      ÷100 ≈ 38 °C   [MATLAB:'temppreh']
    rel  5 (col 6154) : PNs oven setpoint   ÷100 ≈ 180 °C  [MATLAB:'tempcellh']
    rel  6 (col 6155) : cell heater (=cavity gas T setpoint) ÷100 ≈ 75 °C
                                                            [MATLAB:'tempoptbx']
    rel 13 (col 6162) : PNs cavity P        raw × 0.6895 ≈ 965 mbar
    rel 15 (col 6164) : ANs cavity P        raw × 0.6895 ≈ 915 mbar
    rel 25 (col 6174) : tempcell1           ÷100 = °C (always working)
    rel 26 (col 6175) : tempcell2           ÷100 = °C (broken until 5/27 10:56)
    rel 27 (col 6176) : tempcell3           ÷100 = °C
    rel 28 (col 6177) : tempsptrm (spectrometer housing) ÷100 = °C

  Cold file (6179 cols total):
    rel  6 (col 6155) : ??                  raw 15000-15500 (sentinel?)
    rel 11 (col 6160) : cavity pressure     raw × 0.6895 ≈ 1000 mbar
    rel 24 (col 6173) : cavity temperature  ÷100 ≈ 24 °C
    rel 25 (col 6174) : spectrometer T      ÷100

NOTE on MATLAB labels: 박사님 MATLAB variable names (e.g. ``tempcellh``,
``tempoptbx``) appear to drift from the physical role by one or two columns
compared to our 2026 Yeosu data values. The mapping here reflects what the
**data** actually shows, not necessarily the MATLAB label. Where the two
disagree the MATLAB label is recorded as a comment for reference.

State flag conventions
----------------------
::

Authoritative semantics (from the LabVIEW DAQ side). The calibration families
share one rule: **5xx = Zero Air, 51x = Helium**, and the last digit is the
step within that family.

::

  flag = 0     header / file-start marker
  flag = 1     sampling (atmosphere)
  flag = 100   shutdown

  ── x00 injecting · x01 setflow · x02 wait-before · x03 wait-after ──
  flag = 500   ZA injecting     ← measurement window (R uses this)
  flag = 501   ZA setflow
  flag = 502   ZA wait-before
  flag = 503   ZA wait-after
  flag = 510   He injecting     ← measurement window (R uses this)
  flag = 511   He setflow
  flag = 512   He wait-before
  flag = 513   He wait-after

Observed cycle (2026-06-02 Hot, one full calibration ≈ 2 min 15 s, ~30 s/step)::

  1 → 512 → 510 → 513 → 501 → 502 → 500 → 503 → 1

R calculation should use **500 / 510** (the injecting = measurement window),
NOT the setflow/wait steps. The legacy ``r_batch_calculator.py`` constant
``FLAG_ZA = [502]`` is wrong and should be migrated to ``[500]``.

.. note::
   ``501`` / ``511`` / ``100`` were absent from this file's earlier flag table and
   were added after ``501`` turned up in real 2026-06 data; the older
   "ZA-end (one-row marker)" reading of ``503`` was a guess — it is *wait-after*.

Time decoding
-------------
``col0`` (low 16 bits) and ``col1`` (high 16 bits) byte-pack to a LabVIEW
timestamp in centiseconds since the start of the year:

::

  bytepack = (col0 << 16) | col1
  this_year_sec = bytepack / 100
  date_local = datenum(1904, 1, 2) + (ref_sec + this_year_sec) / 86400

The 2026 ``ref_sec`` per 박사님 MATLAB code is **3 723 840 000**. For
practical use the file mtime is usually a good enough start-of-file
timestamp; we expose both. NOTE: the absolute ``ref_sec`` offset has been
seen to be wrong by hours on 2026 Yeosu files, but the *relative* row-to-row
bytepack spacing is reliable (~0.97 s/row) — see ``ParsedRow.bytepack_sec``.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator

import numpy as np

# ──────────────────────────────────────────────────────────────────────────────────
# Constants — single source of truth
# ──────────────────────────────────────────────────────────────────────────────────

META_COLS = 2053            # 0..2052 inclusive
CH_PIXELS = 2048            # 2048 pixels per spectral channel

# Absolute spectrum slices (start, end_exclusive)
SPEC_BLOCK_A = (5,         5 + CH_PIXELS)            # 5..2053  — empty / legacy 3-ch
SPEC_PRIMARY = (META_COLS, META_COLS + CH_PIXELS)    # 2053..4101 — Cold NO2 / Hot PNs
SPEC_SECONDARY = (META_COLS + CH_PIXELS,             # 4101..6149 — Hot ANs only
                  META_COLS + 2 * CH_PIXELS)
# Legacy aliases for code expecting the MATLAB nomenclature
SPEC_CH1_NO2 = SPEC_PRIMARY        # MATLAB "ch1"
SPEC_CH2_UV  = SPEC_SECONDARY      # MATLAB "ch2"

HK_START = META_COLS + 2 * CH_PIXELS                  # 6149

# Standard meta columns
COL_TIME_LO = 0
COL_TIME_HI = 1
COL_EXPOSURE = 2
COL_TEMP_CCD = 3
COL_FLAG = 4

# State flag categories.
# Family rule: 5xx = Zero Air, 51x = Helium;
#              x00 injecting · x01 setflow · x02 wait-before · x03 wait-after.
FLAG_HEADER   = 0
FLAG_AMBIENT  = 1        # LabVIEW calls this "sampling"
FLAG_SHUTDOWN = 100
FLAG_ZA      = 500       # ZA injecting = measurement window
FLAG_ZA_SETFLOW = 501
FLAG_ZA_WAIT = 502       # wait-before
FLAG_ZA_END  = 503       # wait-after (historical name kept for compatibility)
FLAG_HE      = 510       # He injecting = measurement window
FLAG_HE_SETFLOW = 511
FLAG_HE_WAIT = 512       # wait-before
FLAG_HE_END  = 513       # wait-after (historical name kept for compatibility)

# Accurate aliases (prefer these in new code; values are identical)
FLAG_ZA_WAIT_BEFORE = FLAG_ZA_WAIT
FLAG_ZA_WAIT_AFTER  = FLAG_ZA_END
FLAG_HE_WAIT_BEFORE = FLAG_HE_WAIT
FLAG_HE_WAIT_AFTER  = FLAG_HE_END

FLAG_STABLE = {FLAG_ZA, FLAG_HE}              # actual measurement windows
FLAG_TRANSITIONAL = {FLAG_ZA_SETFLOW, FLAG_ZA_WAIT, FLAG_ZA_END,
                     FLAG_HE_SETFLOW, FLAG_HE_WAIT, FLAG_HE_END}

FLAG_NAMES: dict[int, str] = {
    FLAG_HEADER:     "header",
    FLAG_AMBIENT:    "sampling",
    FLAG_SHUTDOWN:   "shutdown",
    FLAG_ZA:         "ZA-inject",
    FLAG_ZA_SETFLOW: "ZA-setflow",
    FLAG_ZA_WAIT:    "ZA-wait-before",
    FLAG_ZA_END:     "ZA-wait-after",
    FLAG_HE:         "He-inject",
    FLAG_HE_SETFLOW: "He-setflow",
    FLAG_HE_WAIT:    "He-wait-before",
    FLAG_HE_END:     "He-wait-after",
}

# Pressure raw → mbar (raw × 0.01 × 6894.73 Pa/PSI ÷ 100)
P_SCALE = 0.01 * 6894.73326 / 100.0   # ≈ 0.6894733
P_VALID_LO, P_VALID_HI = 800.0, 1200.0  # mbar plausibility window

# Time decoding (per 박사님 read_data_CAESAR_Araon_2025_3ch.m)
LABVIEW_REF_SEC_2026 = 3_723_840_000      # MATLAB line 49
LABVIEW_EPOCH = datetime(1904, 1, 2)      # MATLAB datenum(1904,1,2)
KST = timezone(timedelta(hours=9))

# Sentinel raw values that mean "no reading"
SENTINEL_RAW = (0.0, 65535.0)


def _is_sentinel(v: float) -> bool:
    return (not np.isfinite(v)) or (v in SENTINEL_RAW)


# ──────────────────────────────────────────────────────────────────────────────────
# HK column maps — explicit name → (absolute col, scale, units, kind)
# ──────────────────────────────────────────────────────────────────────────────────

# kind: "temp" → ÷100 = °C, "press" → ×0.6895 = mbar, "raw" → use as-is
HotHKMap: dict[str, tuple[int, float, str, str]] = {
    "templed1":       (6149, 0.01,      "C",    "temp"),   # MATLAB:templed1
    "templed2":       (6150, 0.01,      "C",    "temp"),   # MATLAB:templed2
    "ANs_oven":       (6151, 0.01,      "C",    "temp"),   # MATLAB:templed3 (actually ANs oven ~300C)
    "templed4":       (6152, 0.01,      "C",    "temp"),
    "temppreh":       (6153, 0.01,      "C",    "temp"),   # MATLAB:temppreh ~38C
    "PNs_oven":       (6154, 0.01,      "C",    "temp"),   # MATLAB:tempcellh (actually PNs oven ~180C)
    "cavity_gas_T":   (6155, 0.01,      "C",    "temp"),   # MATLAB:tempoptbx (actually cell heater ~75C — gas T setpoint)
    "P_PNs":          (6162, P_SCALE,   "mbar", "press"),  # PNs cavity inlet
    "P_ANs":          (6164, P_SCALE,   "mbar", "press"),  # ANs cavity inlet
    "tempcell1":      (6174, 0.01,      "C",    "temp"),   # cavity T sensor 1 (always working)
    "tempcell2":      (6175, 0.01,      "C",    "temp"),   # cavity T sensor 2 (broken until 5/27 10:56)
    "tempcell3":      (6176, 0.01,      "C",    "temp"),   # cavity T sensor 3
    "tempsptrm":      (6177, 0.01,      "C",    "temp"),   # spectrometer housing T
}

ColdHKMap: dict[str, tuple[int, float, str, str]] = {
    "cavity_P":       (6160, P_SCALE,   "mbar", "press"),  # Cold cavity pressure
    "cavity_T":       (6173, 0.01,      "C",    "temp"),   # Cold cavity wall T
    "tempsptrm":      (6174, 0.01,      "C",    "temp"),   # spectrometer T
}


# ──────────────────────────────────────────────────────────────────────────────────
# Public dataclasses
# ──────────────────────────────────────────────────────────────────────────────────

@dataclass
class ParsedRow:
    """One parsed row from a raw .dat file."""
    row_idx: int
    time_centisec: float          # raw col1 (high 16 bits of the LabVIEW bytepack)
    time_lo: float                # raw col0 (low 16 bits of the LabVIEW bytepack)
    exposure: float
    temp_ccd_C: float
    flag: int
    hk: dict[str, float]          # name → value in physical units (°C, mbar, ...)
    # Spectrum slices are not stored on the row by default to save memory.
    # Call .spectrum(...) on the parser to get them on demand.

    @property
    def bytepack_sec(self) -> float:
        """LabVIEW bytepack ((col0<<16)|col1)/100 → seconds (this-year scale).

        Returns NaN if either half is missing. The *absolute* offset depends
        on LABVIEW_REF_SEC_2026 (which can be wrong), but the *relative*
        spacing between rows is reliable (~0.97 s/row), so this is ideal for
        anchoring a file's rows to its mtime:
            t(row) = mtime - (bytepack_sec[last] - bytepack_sec[row])
        """
        import math
        if math.isnan(self.time_lo) or math.isnan(self.time_centisec):
            return float("nan")
        return ((int(self.time_lo) << 16) | int(self.time_centisec)) / 100.0


@dataclass
class FileLayout:
    """Detected file layout (Cold vs Hot)."""
    path: str
    ncols: int                    # actual ncols of first non-empty row
    kind: str                     # "cold" | "hot" | "unknown"
    hk_map: dict[str, tuple[int, float, str, str]]
    spec_blocks: dict[str, tuple[int, int]]   # name → (start, end) slice
    mtime: datetime               # file mtime in KST


# ──────────────────────────────────────────────────────────────────────────────────
# Parser
# ──────────────────────────────────────────────────────────────────────────────────

class RawParser:
    """Streaming parser for CAESAR Araon Mega-Matrix .dat files.

    Examples
    --------
    >>> p = RawParser("D:/.../2026-05-25-001.dat")
    >>> p.layout.kind                 # 'cold' or 'hot'
    'cold'
    >>> for row in p.iter_rows():     # streamed, low memory
    ...     if row.flag == FLAG_ZA:
    ...         spec = p.get_spectrum(row.row_idx, 'ch1')  # NO2/Cold spectrum
    ...         T = row.hk['cavity_T']; P = row.hk['cavity_P']
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.layout = self._detect_layout(path)

    # ── Layout detection ────────────────────────────────────────────────────────
    @staticmethod
    def _detect_layout(path: str) -> FileLayout:
        """Read first non-empty data row to determine ncols, then classify."""
        ncols = 0
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                toks = s.split("\t") if "\t" in s else s.split()
                ncols = len(toks)
                break
        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=KST)

        if ncols == 6179:
            return FileLayout(
                path=path, ncols=ncols, kind="cold",
                hk_map=ColdHKMap,
                spec_blocks={"NO2": SPEC_PRIMARY},   # Cold's only real channel
                mtime=mtime,
            )
        if ncols == 6181:
            return FileLayout(
                path=path, ncols=ncols, kind="hot",
                hk_map=HotHKMap,
                spec_blocks={
                    "PNs": SPEC_PRIMARY,             # Hot "좌측" cavity (was 박사님 "ch1")
                    "ANs": SPEC_SECONDARY,           # Hot "우측" cavity (was 박사님 "ch2")
                },
                mtime=mtime,
            )
        return FileLayout(
            path=path, ncols=ncols, kind="unknown",
            hk_map={},
            spec_blocks={},
            mtime=mtime,
        )

    # ── Row-by-row streaming ─────────────────────────────────────────────────
    def iter_rows(self) -> Iterator[ParsedRow]:
        """Stream-parse the file. Skips header / malformed rows silently."""
        for i, line in enumerate(self._iter_data_lines()):
            toks = line.split("\t") if "\t" in line else line.split()
            if len(toks) < self.layout.ncols:
                continue
            try:
                flag = int(float(toks[COL_FLAG]))
            except ValueError:
                continue
            row = ParsedRow(
                row_idx=i,
                time_centisec=self._safe_float(toks[COL_TIME_HI]),
                time_lo=self._safe_float(toks[COL_TIME_LO]),
                exposure=self._safe_float(toks[COL_EXPOSURE]),
                temp_ccd_C=self._safe_float(toks[COL_TEMP_CCD]) / 100.0,
                flag=flag,
                hk=self._extract_hk(toks),
            )
            yield row

    def _iter_data_lines(self) -> Iterator[str]:
        with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                yield s

    def _extract_hk(self, toks: list[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for name, (col, scale, unit, kind) in self.layout.hk_map.items():
            if col >= len(toks):
                out[name] = float("nan")
                continue
            try:
                raw = float(toks[col])
            except ValueError:
                out[name] = float("nan")
                continue
            if _is_sentinel(raw):
                out[name] = float("nan")
                continue
            out[name] = raw * scale
        return out

    # ── Spectrum extraction (random access) ──────────────────────────────────
    def get_spectrum(self, row_idx: int, channel: str) -> np.ndarray:
        """Return the spectrum array for a single row & channel.

        Slower than ``iter_rows`` because it scans the file again. Use
        ``iter_rows_with_spectra`` for bulk extraction.
        """
        if channel not in self.layout.spec_blocks:
            raise KeyError(
                f"Channel '{channel}' not in layout. Available: "
                f"{list(self.layout.spec_blocks)}"
            )
        start, end = self.layout.spec_blocks[channel]
        for i, line in enumerate(self._iter_data_lines()):
            if i != row_idx:
                continue
            toks = line.split("\t") if "\t" in line else line.split()
            return np.array([self._safe_float(t) for t in toks[start:end]], dtype=np.float64)
        raise IndexError(f"row {row_idx} not found in {self.path}")

    def iter_rows_with_spectra(
        self, channels: tuple[str, ...] = ("ch1_NO2",)
    ) -> Iterator[tuple[ParsedRow, dict[str, np.ndarray]]]:
        """Stream rows together with selected spectra. Memory-efficient."""
        blocks = {ch: self.layout.spec_blocks[ch] for ch in channels
                  if ch in self.layout.spec_blocks}
        for i, line in enumerate(self._iter_data_lines()):
            toks = line.split("\t") if "\t" in line else line.split()
            if len(toks) < self.layout.ncols:
                continue
            try:
                flag = int(float(toks[COL_FLAG]))
            except ValueError:
                continue
            row = ParsedRow(
                row_idx=i,
                time_centisec=self._safe_float(toks[COL_TIME_HI]),
                time_lo=self._safe_float(toks[COL_TIME_LO]),
                exposure=self._safe_float(toks[COL_EXPOSURE]),
                temp_ccd_C=self._safe_float(toks[COL_TEMP_CCD]) / 100.0,
                flag=flag,
                hk=self._extract_hk(toks),
            )
            specs = {
                name: np.array(
                    [self._safe_float(t) for t in toks[start:end]],
                    dtype=np.float64,
                )
                for name, (start, end) in blocks.items()
            }
            yield row, specs

    # ── Grouping helpers ──────────────────────────────────────────────────────
    def collect_spectra_by_flag(
        self,
        flags: set[int],
        channel: str,
    ) -> list[tuple[ParsedRow, np.ndarray]]:
        """Read the file once and return all (row, spectrum) pairs whose flag
        is in ``flags``. Convenient for R calculation (flags={500, 510}).
        """
        out: list[tuple[ParsedRow, np.ndarray]] = []
        for row, specs in self.iter_rows_with_spectra(channels=(channel,)):
            if row.flag in flags:
                out.append((row, specs[channel]))
        return out

    # ── Time decoding ────────────────────────────────────────────────────────
    def decode_time(self, row: ParsedRow,
                    ref_sec: int = LABVIEW_REF_SEC_2026) -> datetime | None:
        """Decode the LabVIEW timestamp from cols 0-1 into a KST datetime.

        Returns ``None`` if the bytepack value is not plausible (e.g. file
        uses a different time encoding). NOTE: the *absolute* result can be
        off by hours on 2026 Yeosu files (ref_sec mismatch). For plotting,
        prefer anchoring ``ParsedRow.bytepack_sec`` to the file mtime.
        """
        # We need col0 (low 16 bits) and col1 (high 16 bits) — but
        # iter_rows() didn't keep col0. Re-read just that row's first two
        # values. Slow path; intended for occasional use, not every row.
        for i, line in enumerate(self._iter_data_lines()):
            if i != row.row_idx:
                continue
            toks = line.split("\t") if "\t" in line else line.split()
            try:
                c0 = int(float(toks[COL_TIME_LO]))
                c1 = int(float(toks[COL_TIME_HI]))
            except ValueError:
                return None
            bytepack = (c0 << 16) | c1
            this_year_sec = bytepack / 100.0
            labview_total = ref_sec + this_year_sec
            return LABVIEW_EPOCH.replace(tzinfo=KST) + timedelta(seconds=labview_total)
        return None

    def estimate_row_time(self, row: ParsedRow,
                          row_period_sec: float = 0.97) -> datetime:
        """Cheap timestamp estimate using file mtime + row_idx * row_period.

        Use this for plotting / bulk processing where decode_time() is too
        slow. Per ``r_trend_monitor.py`` docstring, row spacing is ~0.97 s.
        """
        return self.layout.mtime + timedelta(seconds=row.row_idx * row_period_sec)

    # ── Utility ────────────────────────────────────────────────────────────
    @staticmethod
    def _safe_float(s: str) -> float:
        try:
            return float(s)
        except (ValueError, TypeError):
            return float("nan")


__all__ = [
    "RawParser",
    "ParsedRow",
    "FileLayout",
    "HotHKMap",
    "ColdHKMap",
    "FLAG_HEADER", "FLAG_AMBIENT", "FLAG_ZA", "FLAG_ZA_WAIT", "FLAG_ZA_END",
    "FLAG_HE", "FLAG_HE_WAIT", "FLAG_HE_END",
    "FLAG_STABLE", "FLAG_TRANSITIONAL", "FLAG_NAMES",
    "SPEC_PRIMARY", "SPEC_SECONDARY", "SPEC_BLOCK_A",
    "SPEC_CH1_NO2", "SPEC_CH2_UV",   # legacy aliases
    "P_SCALE", "LABVIEW_REF_SEC_2026", "LABVIEW_EPOCH", "KST",
]
