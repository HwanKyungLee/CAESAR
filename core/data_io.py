import os
import re
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

# Column-layout constants live in raw_parser — the single source of truth.
# DataIO shares the scalar/block constants from there so the two parsers can
# never drift apart on basic geometry. (HK relative offsets stay local — see
# the _HK_REL note below for why.)
from .raw_parser import (
    META_COLS as _RP_META_COLS,
    CH_PIXELS as _RP_CH_PIXELS,
    P_SCALE as _RP_P_SCALE,
    P_VALID_LO as _RP_P_LO,
    P_VALID_HI as _RP_P_HI,
    SPEC_PRIMARY as _RP_SPEC_PRIMARY,
    SPEC_SECONDARY as _RP_SPEC_SECONDARY,
)


def ui_scale() -> float:
    """Return a UI scale factor relative to 1080p reference height.
    Clamps between 0.75 and 1.25 to avoid extreme layouts."""
    try:
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen is None:
            return 1.0
        h = screen.availableGeometry().height()
        return max(0.75, min(1.25, h / 1080.0))
    except Exception:
        return 1.0


class DataIO:
    """
    CAESAR Pro Data Input/Output Manager.

    Centralizes all file-reading logic so the engine and UI stay clean.
    Supports two measurement formats:
      - Araon 2025 Mega-Matrix (.dat): one scan per row, 6175+ columns
      - Standard 1D DOAS / BBCEAS text files: one intensity value per line

    All methods are @staticmethod — call them as DataIO.load_reference(path),
    no instance required.
    """

    # ── Araon Mega-Matrix row cache ─────────────────────────────────────────
    # Without caching, _read_row_raw scans from line 0 every call → O(n²) for
    # n-row files.  The cache stores the entire file as a list[np.ndarray] keyed
    # by (filepath, mtime).  Stays in memory only for the most-recently-used file
    # (LRU-1) so a folder of many files doesn't exhaust RAM.
    _row_cache: dict = {}   # { (path, mtime): [row0_arr, row1_arr, ...] }
    _cached_key: tuple | None = None  # key of the currently cached file

    @staticmethod
    def enforce_1d_array(data):
        """
        Defensive helper: normalizes any wavelength input into a flat 1D float array.

        Why this exists: several callers pass wavelength data in different shapes
        (None, a tuple from a loader, a 2-D matrix, etc.).  This function handles
        every case so the rest of the engine never has to check.

        Returns np.array([0.0]) when data is None (signals 'no wavelength axis').
        """
        if data is None:
            return np.array([0.0])
        if isinstance(data, tuple):
            data = data[0]   # Some loaders return (wavelength, intensity) as a tuple
        return np.atleast_1d(data).flatten().astype(float)

    # ─────────────────────────────────────────────────────────────────────────
    # Araon Mega-Matrix helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_line_to_array(line: str) -> np.ndarray:
        """Parse a tab-delimited line into a float numpy array.

        Fast path: np.array(dtype=float) (C-level, ~1.6x faster than a Python
        per-value float() loop — this dominates alpha/raw read time on 6000+ col
        Mega-Matrix rows). Falls back to NaN-tolerant per-value parse only when a
        token is non-numeric (rare)."""
        vals = line.strip().split('\t')
        try:
            return np.array(vals, dtype=np.float64)
        except (ValueError, TypeError):
            raw = np.empty(len(vals), dtype=float)
            for j, v in enumerate(vals):
                try:
                    raw[j] = float(v)
                except (ValueError, TypeError):
                    raw[j] = np.nan
            return raw

    @staticmethod
    def _parse_megamatrix_row(vals: list, keep_ranges) -> np.ndarray:
        """Mega-Matrix 행을 '활성 컬럼 범위만' float 변환(나머지 NaN). keep_ranges =
        [(s,e),...] = 헤더[0:5] + 활성 채널블록들 + HK. 비수치 토큰이면 전체 안전 파싱 폴백."""
        n = len(vals)
        try:
            raw = np.full(n, np.nan)
            for s, e in keep_ranges:
                e = min(e, n)
                if e > s:
                    raw[s:e] = np.array(vals[s:e], dtype=np.float64)
            return raw
        except (ValueError, TypeError):
            return DataIO._parse_line_to_array('\t'.join(vals))

    @staticmethod
    def _load_file_to_cache(filepath: str) -> list:
        """Read the entire Mega-Matrix file into a list of row arrays (once per file).

        Uses an LRU-1 cache keyed by (filepath, mtime) so re-reading the same
        file within one session is O(1).  Switching to a different file evicts the
        old entry to keep memory usage bounded.
        """
        try:
            mtime = os.path.getmtime(filepath)
        except OSError:
            mtime = 0.0
        key = (filepath, mtime)

        if DataIO._cached_key == key and key in DataIO._row_cache:
            return DataIO._row_cache[key]

        # Evict previous cached file to free memory
        DataIO._row_cache.clear()

        # 모든 비어있지 않은 라인 수집
        with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
            lines = [s for s in (ln.strip() for ln in fh) if s]

        rows: list = []
        if lines:
            split0 = lines[0].split('\t')
            META, CH = DataIO._META_COLS, DataIO._CH_PIXELS
            ncol = len(split0)
            # Mega-Matrix면: 2048 블록들 중 '활성(신호 있는)' 것만 파싱(빈/legacy 채널 스킵).
            # 활성 판정은 파일 전반 샘플 행들의 블록별 최대값으로(첫 행이 ZA/dark여도 견고).
            if ncol >= META + CH:
                nblk = (ncol - 5) // CH          # 5(헤더) 뒤 2048 블록 개수
                hk_start = 5 + nblk * CH
                # 샘플 행 파싱(최대 ~24개 균등)
                step = max(1, len(lines) // 24)
                blk_max = np.zeros(nblk)
                for s in lines[::step][:24]:
                    arr = DataIO._parse_line_to_array(s)
                    for i in range(nblk):
                        a = 5 + i * CH; b = a + CH
                        if b <= len(arr):
                            m = np.nanmax(arr[a:b])
                            if np.isfinite(m) and m > blk_max[i]:
                                blk_max[i] = m
                active = [i for i in range(nblk) if blk_max[i] > DataIO._SIG_THRESHOLD]
                if not active:
                    active = [min(1, nblk - 1)]   # 안전장치: 최소 1블록(보통 ch1) 유지
                # 보존 범위: 헤더[0:5] + 활성 블록들 + HK[hk_start:]
                keep = [(0, 5)] + [(5 + i * CH, 5 + (i + 1) * CH) for i in active] + [(hk_start, ncol)]
                for ln in lines:
                    rows.append(DataIO._parse_megamatrix_row(ln.split('\t'), keep))
            else:
                for ln in lines:
                    rows.append(DataIO._parse_line_to_array(ln))

        DataIO._row_cache[key] = rows
        DataIO._cached_key = key
        return rows

    @staticmethod
    def _read_row_raw(filepath, row_index):
        """
        Returns one row from a tab-delimited file as a float numpy array.

        For Araon Mega-Matrix files (6175+ columns) the whole file is read once
        and cached in memory so repeated calls for different row_index values are
        O(1) after the first call instead of O(n) each.
        Rows with different column counts are handled correctly because we parse
        line-by-line rather than using pandas.
        """
        rows = DataIO._load_file_to_cache(filepath)
        if row_index < len(rows):
            return rows[row_index]
        raise ValueError(f"Row {row_index} not found in {os.path.basename(filepath)} ({len(rows)} rows)")

    # Mega-Matrix detection threshold: META block (2053) + one full spectrum
    # channel (2048) = 4101 columns. A row this wide is unambiguously an Araon
    # multi-scan file (a plain 1D spectrum has ~1 col; a 2-col reference has 2).
    # NOTE: must be ≤ the *truncated* cold width (6174). LabVIEW time-error +
    # Continue can drop the trailing HK columns, leaving the first row at 6174
    # (normal cold = 6179). The old ≥6175 threshold mis-classified those files
    # as single-scan, so expand_to_scan_list() returned only [(fp, 0)] and alpha
    # generation emitted just one trace per bin. 4101 keeps normal 6179/6177
    # files detected while also catching the 6174 truncated files. See
    # cold-alpha-6175-threshold-bug-2026-06.
    _MEGA_MATRIX_MIN_COLS = _RP_META_COLS + _RP_CH_PIXELS   # 4101

    @staticmethod
    def is_araon_mega_matrix(filepath):
        """
        Returns True when the first non-empty row has ≥4101 tab-separated
        columns (META + ≥1 spectrum channel) — the signature of the Araon
        LabVIEW Mega-Matrix format, tolerant of trailing-HK truncation.
        """
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    if line.strip():
                        return len(line.strip().split('\t')) >= DataIO._MEGA_MATRIX_MIN_COLS
        except Exception:
            pass
        return False

    # ── Multi-channel layout constants ───────────────────────────────────────
    # Araon Mega-Matrix column layout:
    #   META block  : cols    0 – 2052   (2053 cols, metadata + UTC + flags)
    #   CH1 spectrum: cols 2053 – 4100   (2048 px)
    #   CH2 spectrum: cols 4101 – 6148   (2048 px)  — Hot ROI2/ANs only
    #   CH3 spectrum: cols 6149 – 8196   (2048 px)  — 3-channel config only
    #   HK block    : cols (2053 + N×2048) onward
    #
    # HK offsets *relative* to hk_start (so they work for any channel count):
    _META_COLS = _RP_META_COLS   # 2053 — shared with raw_parser
    _CH_PIXELS = _RP_CH_PIXELS   # 2048 — shared with raw_parser
    _SIG_THRESHOLD = 5000.0     # ADU — below this = noise / inactive channel
    # Relative HK column offsets (verified from 2-channel hot file 2026-05-18).
    # NOTE: these are offsets from DataIO's *dynamic* hk_start
    # (= META_COLS + n_active_channels × CH_PIXELS), which for 2-ch hot files
    # equals raw_parser.HK_START (6149). They therefore resolve to the same
    # absolute columns as raw_parser.HotHKMap / ColdHKMap for hot files
    # (hot_p→6162=P_PNs, oven_pns→6154, etc.). They are intentionally NOT
    # replaced by the raw_parser maps because DataIO's hk_start is computed
    # from the active-channel count, so changing the offset scheme here could
    # shift cold-file HK reads — out of scope for a constants-only merge.
    _HK_REL = {
        'cold_p':   11,   # Cold inlet pressure raw count → ×0.6895 = mbar
        'hot_p':    13,   # Hot CH1(PNs) pressure raw count → ×0.6895 = mbar (abs 6162)
        'hot_p_ans':15,   # Hot CH2(ANs) pressure raw count → ×0.6895 = mbar (abs 6164)
        'hot_cav_t': 6,   # Cell-heater SETPOINT (~75°C) — 가스온도 아님(과냉방지용)
        'cold_cav_t':24,  # Unheated cavity temperature  → /100 = °C (~24°C)
        'oven_pns': 5,    # PNs oven setpoint             → /100 = °C (~180°C)
        'oven_ans': 2,    # ANs oven setpoint             → /100 = °C (~300°C)
        # 셀 통과 가스의 실측 온도(tempcell, 박사님 확인 2026-06-10). ppb 밀도보정(n_air)
        # 기준은 설정값(hot_cav_t 75°C)이 아니라 이 실측값이다 (CH1≈34, CH2≈31.5°C).
        'tempcell1': 25,  # CH1(PNs) cell gas temperature → /100 = °C
        'tempcell2': 26,  # CH2(ANs) cell gas temperature → /100 = °C
    }
    _P_SCALE = _RP_P_SCALE                 # raw count → mbar (~0.6895), shared
    _P_LO, _P_HI = _RP_P_LO, _RP_P_HI      # plausible atmospheric pressure range, shared

    @staticmethod
    def _detect_n_channels_from_row(raw: np.ndarray) -> int:
        """Returns the number of active spectrum channels (1–3) in one row array.

        Checks each 2048-pixel block after the 2053-col metadata section.
        A block is considered active when its max exceeds _SIG_THRESHOLD ADU.
        """
        n = 0
        for i in range(1, 4):
            start = DataIO._META_COLS + (i - 1) * DataIO._CH_PIXELS
            end   = start + DataIO._CH_PIXELS
            if end > len(raw):
                break
            block = raw[start:end]
            # 활성블록 파싱 최적화로 비활성 채널은 NaN으로 채워질 수 있음 → all-NaN이면 부재
            if np.all(np.isnan(block)):
                break
            if float(np.nanmax(block)) > DataIO._SIG_THRESHOLD:
                n = i
            else:
                break   # channel absent → no point checking further
        return max(n, 1)

    @staticmethod
    def detect_channels(filepath) -> int:
        """Auto-detect the number of active spectrum channels in an Araon file.

        Returns 1, 2, or 3.  Uses the first non-empty row (fast: cache hit after
        the first call).  Non-Araon files always return 1.
        """
        if not DataIO.is_araon_mega_matrix(filepath):
            return 1
        try:
            rows = DataIO._load_file_to_cache(filepath)
            for raw in rows:
                if len(raw) >= DataIO._META_COLS + DataIO._CH_PIXELS:
                    return DataIO._detect_n_channels_from_row(raw)
        except Exception:
            pass
        return 1

    @staticmethod
    def has_ch2(filepath) -> bool:
        """Convenience wrapper — True when the file has ≥ 2 active channels."""
        return DataIO.detect_channels(filepath) >= 2

    @staticmethod
    def count_scan_rows(filepath):
        """Counts the number of non-empty rows (= scans) in a Mega-Matrix file."""
        count = 0
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    if line.strip():
                        count += 1
        except Exception:
            pass
        return count

    _alpha_fmt_cache: dict = {}   # (path, mtime) -> bool, alpha 포맷 판정 캐시

    @staticmethod
    def _is_alpha_trace_format(filepath) -> bool:
        """Returns True when the file is a CAESAR Pro alpha_trace.dat (multi-scan TSV).
        (path,mtime) 캐시 — 스캔마다 호출돼도 파일을 한 번만 연다."""
        try:
            key = (filepath, os.path.getmtime(filepath))
        except OSError:
            key = (filepath, 0.0)
        cached = DataIO._alpha_fmt_cache.get(key)
        if cached is not None:
            return cached
        result = False
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    s = line.strip()
                    if not s:
                        continue
                    if s.startswith('# wavelength_nm:') or s.startswith('row_idx\t'):
                        result = True
                        break
                    if s.startswith('#'):
                        continue
                    break
        except Exception:
            result = False
        if len(DataIO._alpha_fmt_cache) > 256:
            DataIO._alpha_fmt_cache.clear()
        DataIO._alpha_fmt_cache[key] = result
        return result

    @staticmethod
    def _count_alpha_trace_data_rows(filepath) -> int:
        """Count ambient data rows in an alpha_trace.dat file."""
        count = 0
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    s = line.strip()
                    if s and not s.startswith('#') and not s.startswith('row_idx'):
                        count += 1
        except Exception:
            pass
        return max(count, 1)

    @staticmethod
    def _alpha_layout(filepath):
        """alpha_trace 헤더 파싱 → (alpha_start_col, t_idx, p_idx, px_start, wave_nm).

        구포맷: row_idx  T_C  P_mbar  px...
        신포맷: row_idx  doy  datetime  T_C  P_mbar  px...   (타임스탬프 컬럼 추가)
        컬럼 위치를 헤더에서 읽어 둘 다 지원한다. wave_nm 은 '# wavelength_nm:' 배열."""
        wave_nm = None
        hdr = None
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    if line.startswith('# wavelength_nm:'):
                        try:
                            wave_nm = np.array([float(v) for v in line.split(':', 1)[1].strip().split('\t')
                                                if v.strip()], dtype=float)
                        except Exception:
                            pass
                        continue
                    if line.startswith('row_idx'):
                        hdr = line.rstrip('\n').split('\t')
                        break
                    if not line.startswith('#') and line.strip():
                        break
        except Exception:
            pass
        if not hdr:
            return 3, 1, 2, 0, wave_nm
        first_px = next((i for i, c in enumerate(hdr) if c.startswith('px')), 3)
        t_idx = hdr.index('T_C') if 'T_C' in hdr else 1
        p_idx = hdr.index('P_mbar') if 'P_mbar' in hdr else 2
        px_start = 0
        if first_px < len(hdr) and hdr[first_px].startswith('px'):
            try:
                px_start = int(hdr[first_px][2:])
            except ValueError:
                px_start = 0
        return first_px, t_idx, p_idx, px_start, wave_nm

    @staticmethod
    def read_alpha_trace_wavelengths(filepath):
        """alpha_trace.dat의 '# wavelength_nm:' 채널별 파장축(없으면 None)."""
        return DataIO._alpha_layout(filepath)[4]

    @staticmethod
    def _load_alpha_trace_row(filepath, row_index, pixel_min=0, pixel_max=None):
        """Load one data row from an alpha_trace.dat file (구·신 포맷 호환).

        헤더 위치로 T_C/P_mbar/alpha 컬럼을 판정(타임스탬프 doy/datetime 컬럼 대응).
        Pads the alpha array to 2048 pixels (zeros outside the exported range)
        so the caller's pixel_min/pixel_max slicing works.
        Returns (pixel_idx, intensity_raw, state_flag=1, env_t, env_p).
        """
        first_px, t_idx, p_idx, px_start, _wave = DataIO._alpha_layout(filepath)
        data_rows = []
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    s = line.strip()
                    if not s or s.startswith('#') or s.startswith('row_idx'):
                        continue
                    data_rows.append(s)
        except Exception as e:
            raise RuntimeError(
                f"HK Data Load Failed ({os.path.basename(filepath)}): {e}")

        if row_index >= len(data_rows):
            raise RuntimeError(
                f"HK Data Load Failed ({os.path.basename(filepath)}): "
                f"row {row_index} not found ({len(data_rows)} data rows)")

        parts = data_rows[row_index].split('\t')
        try:
            env_t = float(parts[t_idx])
            env_p = float(parts[p_idx])
            alpha_vals = np.array([float(v) for v in parts[first_px:]], dtype=float)
        except (ValueError, IndexError) as e:
            raise RuntimeError(
                f"HK Data Load Failed ({os.path.basename(filepath)}): parse error: {e}")

        n_alpha = len(alpha_vals)
        full_alpha = np.zeros(2048, dtype=float)
        end_px = min(px_start + n_alpha, 2048)
        full_alpha[px_start:end_px] = alpha_vals[:end_px - px_start]

        p_min = int(pixel_min)
        p_max = (end_px if pixel_max is None or int(pixel_max) > 2048
                 else int(pixel_max))
        intensity_raw = full_alpha[p_min:p_max]
        pixel_idx = np.arange(p_min, p_max)

        return pixel_idx, intensity_raw, 1, env_t, env_p

    @staticmethod
    def load_alpha_trace_row_full(filepath, row_index):
        """alpha_trace 한 행을 (wave_nm, alpha, T, P)로 — 패딩/슬라이스 없이 실제 데이터.

        AnalysisWorker가 알파를 그 채널 자체 파장축으로 피팅하도록 쓰는 경로
        (마스터 wavecal이 아니라 알파에 박힌 채널별 파장 사용)."""
        first_px, t_idx, p_idx, px_start, wave_nm = DataIO._alpha_layout(filepath)
        data_rows = []
        with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith('#') or s.startswith('row_idx'):
                    continue
                data_rows.append(s)
        if row_index >= len(data_rows):
            raise RuntimeError(f"alpha row {row_index} not found ({len(data_rows)} rows)")
        parts = data_rows[row_index].split('\t')
        env_t = float(parts[t_idx])
        env_p = float(parts[p_idx])
        alpha = np.array([float(v) for v in parts[first_px:]], dtype=float)
        if wave_nm is None or len(wave_nm) != len(alpha):
            wave_nm = np.arange(len(alpha), dtype=float)
        return wave_nm, alpha, env_t, env_p

    @staticmethod
    def expand_to_scan_list(filepath):
        """
        Expands a file path into a list of (filepath, row_index) tuples.

        For Araon Mega-Matrix files (one scan per row), every row becomes a
        separate scan entry.  For plain 1D files the result is always a
        single-element list: [(filepath, 0)].
        """
        if DataIO.is_araon_mega_matrix(filepath):
            n = DataIO.count_scan_rows(filepath)
            return [(filepath, i) for i in range(n)]
        if DataIO._is_alpha_trace_format(filepath):
            n = DataIO._count_alpha_trace_data_rows(filepath)
            return [(filepath, i) for i in range(n)]
        return [(filepath, 0)]

    # ─────────────────────────────────────────────────────────────────────────
    # Reference and measurement loaders
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def load_reference(filepath):
        """
        Loads a cross-section reference file (e.g., NO2 absorption spectrum from HITRAN).

        Expected file format:
          - Two columns:  wavelength (nm) | cross-section (cm²/molecule)
          - OR one column: cross-section only (no wavelength axis)
          - Lines starting with '#' are treated as comments and skipped.

        Returns:
          (wave_nm, intensity_raw)  — wave_nm is None when the file has only one column.
        """
        try:
            # Try whitespace-delimited first (most common HITRAN / DOASIS format),
            # then fall back to comma-delimited if that fails
            try:
                df = pd.read_csv(filepath, sep=r'\s+', header=None, comment='#')
            except Exception:
                df = pd.read_csv(filepath, sep=',', header=None, comment='#')

            if len(df.columns) >= 2:
                # Two-column file: col 0 = wavelength (nm), col 1 = cross-section
                wave_nm = pd.to_numeric(df.iloc[:, 0], errors='coerce').values
                intensity_raw = pd.to_numeric(df.iloc[:, 1], errors='coerce').values
            else:
                # Single-column file: intensity only, caller must supply its own axis
                wave_nm = None
                intensity_raw = pd.to_numeric(df.iloc[:, -1], errors='coerce').values

            return wave_nm, intensity_raw

        except Exception as e:
            raise RuntimeError(f"Reference load failed: {str(e)}")

    @staticmethod
    def load_measurement(filepath, pixel_min=0, pixel_max=None):
        """
        Loads a simple 1D spectrum file (one raw intensity value per line).

        The pixel range [pixel_min, pixel_max) lets the caller slice out only
        the wavelength window relevant to the fit, reducing memory and noise.

        Returns:
          (pixel_idx, intensity_raw)
            - pixel_idx: integer array [pixel_min, pixel_min+1, ..., pixel_max-1]
            - intensity_raw: float array of intensities within that range

        Raises RuntimeError if the file cannot be parsed or the data is garbage.
        """
        try:
            # Read all values as strings first, then convert — handles mixed formats
            # that would choke a direct float parser (e.g., trailing units or headers)
            df = pd.read_csv(filepath, sep=r'\s+', header=None, dtype=str)
            intensity_full = pd.to_numeric(df.iloc[:, 0], errors='coerce').values

            # Strip NaN / Inf values that would corrupt fitting later
            valid_mask = ~np.isnan(intensity_full) & np.isfinite(intensity_full)
            intensity_clean = intensity_full[valid_mask]

            p_min = int(pixel_min)
            if len(intensity_clean) < p_min + 10:
                raise ValueError("Data length is shorter than the specified pixel minimum.")

            # If no upper bound given, read to the end of the file
            if pixel_max is None or int(pixel_max) > len(intensity_clean):
                p_max = len(intensity_clean)
            else:
                p_max = int(pixel_max)

            intensity_raw = intensity_clean[p_min:p_max]
            pixel_idx = np.arange(p_min, p_max)

            # Sanity check: all-zero or near-zero files are usually empty or corrupt
            if np.max(np.abs(intensity_raw)) < 1e-10:
                raise ValueError("Garbage data detected (values too small)")

            return pixel_idx, intensity_raw

        except Exception as e:
            raise RuntimeError(
                f"Failed to read measurement file ({os.path.basename(filepath)}): {str(e)}"
            )

    # Araon Mega-Matrix spectrum column offsets
    # CH1 (ROI1 / PNs / 180°C inlet):  cols 2053–4100  (2048 px)
    # CH2 (ROI2 / ANs / 300°C inlet):  cols 4101–6148  (2048 px)
    # HK block starts at col 6149.
    # Cold files have CH1 only (CH2 block is noise ~500 ADU).
    # Blocks shared with raw_parser (SPEC_PRIMARY / SPEC_SECONDARY).
    _CH_OFFSET = {1: _RP_SPEC_PRIMARY, 2: _RP_SPEC_SECONDARY}

    @staticmethod
    def load_measurement_with_hk(filepath, pixel_min=0, pixel_max=None,
                                 row_index=0, channel=1):
        """
        Extracts spectrum + housekeeping scalars from the Araon Raw .dat format.

        The Araon LabVIEW system saves each scan as a single horizontal row with
        6175+ columns (the 'Mega-Matrix' format):

          Column range  2053–4100  →  CH1 spectrum  (ROI1 / PNs / 180°C inlet)
          Column range  4101–6148  →  CH2 spectrum  (ROI2 / ANs / 300°C inlet)
          Column        4          →  state flag  (1=Ambient, 500~503=ZA, 510~513=He)
          HK block      6149+      →  T, P, oven temps, etc.

        channel : int, 1 or 2
            Which spectrum to extract.  Default=1 (CH1/ROI1).
            Use channel=2 for CH2/ROI2 (ANs, hot files only).

        row_index selects which row (scan) to read from a multi-scan file.
        Falls back to treating the whole file as a plain 1D spectrum when the
        file has fewer than 6175 columns per row.

        Returns:
          (pixel_idx, intensity_raw, state_flag, env_t, env_p)
        """
        try:
            # alpha_trace.dat format: early return before _read_row_raw
            # (comment lines would mislead the Araon vs. 1D branch decision)
            if DataIO._is_alpha_trace_format(filepath):
                return DataIO._load_alpha_trace_row(
                    filepath, row_index, pixel_min, pixel_max)

            # Read the target row directly — avoids pandas column-count enforcement
            # which breaks on Araon files that mix 6177-col and 6181-col rows.
            raw_probe = DataIO._read_row_raw(filepath, row_index)

            # Safe defaults in case housekeeping columns are missing
            state_flag = 0
            env_t = 25.0
            env_p = 1013.25

            # Araon row gate: a single full channel (META + CH1 = 4101 cols) is
            # enough to parse spectrum + HK. The old 6175 floor mis-routed rows
            # that were truncated by a few tail-HK columns (e.g. a LabVIEW write
            # cut short) into the 1D fallback below, which re-reads the *entire*
            # multi-MB file per row → O(n²) hang. Spectrum/P/T live well before
            # 4101, and missing tail HK is already guarded as NaN in _hk().
            if len(raw_probe) >= DataIO._META_COLS + DataIO._CH_PIXELS:
                # ── Araon Mega-Matrix format ─────────────────────────────────
                # Dynamic channel slice: CH1=2053:4101, CH2=4101:6149, CH3=6149:8197
                # n_slots: 컬럼수 기반(구조적) — HK는 모든 슬롯 뒤 고정 위치라 신호유무와
                # 무관하다. (구버전은 신호기반 감지를 써서 Cold[ch2 노이즈]가 n=1로 잡혀
                # HK를 4101에서 읽어 T/P가 쓰레기였음 → 슬롯기반으로 교정.)
                n_slots = max(1, (len(raw_probe) - DataIO._META_COLS) // DataIO._CH_PIXELS)
                ch = max(1, min(channel, n_slots))   # clamp to available channels
                col_start = DataIO._META_COLS + (ch - 1) * DataIO._CH_PIXELS
                col_end   = col_start + DataIO._CH_PIXELS
                intensity_full = raw_probe[col_start:col_end]

                state_flag = int(raw_probe[4])   # Measurement state flag (col 4)

                # ── HK reading — relative offsets from the HK block start ────
                # HK block begins immediately after all spectrum slots:
                #   hk_start = META_COLS + n_slots × CH_PIXELS
                hk = DataIO._META_COLS + n_slots * DataIO._CH_PIXELS

                # HK-block truncation guard: an interrupted LabVIEW write can drop
                # the *leading* few HK columns, shifting every HK reading left
                # while leaving the spectrum (before `hk`) and the HK *tail*
                # intact (observed on cold 2026-06-11-020: 6174 cols vs 6179, with
                # the tail values still aligned). If this row is a little shorter
                # than the standard cold/hot width we infer how many leading HK
                # cols were lost and shift reads left to match. Bounded to a few
                # cols so genuinely short / 1-channel rows aren't touched; the
                # pressure-plausibility scan below independently validates the
                # result (a wrong shift simply fails the 800–1200 mbar gate and
                # falls back to the default, i.e. no worse than before).
                hk_shift = 0
                _std = next((s for s in (6179, 6181) if s >= len(raw_probe)), None)
                if _std is not None and 0 < (_std - len(raw_probe)) <= 64:
                    hk_shift = _std - len(raw_probe)

                def _hk(rel):
                    c = hk + rel - hk_shift
                    v = raw_probe[c] if 0 <= c < len(raw_probe) else np.nan
                    return v if (np.isfinite(v) and v not in (0, 65535)) else np.nan

                raw_p_count = np.nan
                _t_rel = DataIO._HK_REL['cold_cav_t']   # default: cold cavity T
                _is_hot = False
                for p_rel, t_rel, is_hot in (
                    (DataIO._HK_REL['cold_p'], DataIO._HK_REL['cold_cav_t'], False),
                    (DataIO._HK_REL['hot_p'],  DataIO._HK_REL['hot_cav_t'],  True),
                ):
                    pv = _hk(p_rel)
                    if np.isfinite(pv):
                        pm = float(pv) * DataIO._P_SCALE
                        if DataIO._P_LO <= pm <= DataIO._P_HI:
                            raw_p_count = pv
                            _t_rel = t_rel
                            _is_hot = is_hot
                            break

                if np.isfinite(raw_p_count):
                    env_p = float(raw_p_count) * DataIO._P_SCALE
                # Hot: 채널별 실측 가스온도(tempcell)를 우선 사용. hot_cav_t(75°C)는
                # 셀히터 설정값이라 ppb 밀도보정에 쓰면 NO2 과소평가(폴백으로만 유지).
                if _is_hot:
                    tc_rel = DataIO._HK_REL['tempcell1' if ch == 1 else 'tempcell2']
                    tc = _hk(tc_rel)
                    if np.isfinite(tc) and 0.0 < float(tc) / 100.0 < 100.0:
                        _t_rel = tc_rel
                    # CH2(ANs)는 전용 압력 컬럼(hot_p_ans, abs 6164) 사용
                    if ch == 2:
                        pv2 = _hk(DataIO._HK_REL['hot_p_ans'])
                        if np.isfinite(pv2):
                            pm2 = float(pv2) * DataIO._P_SCALE
                            if DataIO._P_LO <= pm2 <= DataIO._P_HI:
                                env_p = pm2
                tv = _hk(_t_rel)
                if np.isfinite(tv):
                    env_t = float(tv) / 100.0
            else:
                # ── Regular 1D file (one value per line, e.g. alpha trace) ──
                # Re-read the whole file to get all rows, not just the target row.
                df_full = pd.read_csv(filepath, sep=r'\s+', header=None, dtype=str)
                raw_data = pd.to_numeric(df_full.values.flatten(), errors='coerce')
                intensity_full = raw_data

            # Remove NaN / Inf before slicing to the requested pixel range
            valid_mask = ~np.isnan(intensity_full) & np.isfinite(intensity_full)
            intensity_clean = intensity_full[valid_mask]

            p_min = int(pixel_min)
            p_max = (
                len(intensity_clean)
                if (pixel_max is None or int(pixel_max) > len(intensity_clean))
                else int(pixel_max)
            )

            intensity_raw = intensity_clean[p_min:p_max]
            pixel_idx = np.arange(p_min, p_max)

            return pixel_idx, intensity_raw, state_flag, env_t, env_p

        except Exception as e:
            raise RuntimeError(
                f"HK Data Load Failed ({os.path.basename(filepath)}): {str(e)}"
            )

    # ── LabVIEW bytepack 시각(박사님 doy와 동일) ──────────────────────────
    # col0=상위16bit, col1=하위16bit. bytepack=(col0<<16)|col1 은 "연초(1/1 00:00)
    # 이후 centisecond(0.01초)" 카운터. 박사님 .mat 의 doy 와 검증결과 std=0.0000s 로
    # 완전 일치(Cold·Hot). 행간격이 일정 0.97s 가 아니라 실제 갭(-수십초~+수초)이
    # 있으므로 row_index×0.97 합성이 아니라 이 값을 읽어야 한다.
    _DATE_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})')

    @staticmethod
    def _bytepack_year_seconds(col0, col1):
        """(col0,col1) → 연초 기준 초(centisecond/100). 박사님 doy = 초/86400 + 1."""
        bp = (int(col0) << 16) | (int(col1) & 0xFFFF)
        return bp / 100.0

    @staticmethod
    def _file_year(filepath):
        m = DataIO._DATE_RE.search(os.path.basename(filepath))
        return int(m.group(1)) if m else None

    @staticmethod
    def parse_row_timestamp(filepath, row_index=0):
        """Araon row의 (col0,col1) bytepack → naive datetime (박사님 doy와 동일, 타임존 변환 없음).

        연도는 파일명 YYYY-MM-DD 에서 취한다(bytepack은 연초 기준이라 연도 필요).
        파일명에 날짜가 없거나 실패하면 파일 수정시각으로 폴백.
        """
        try:
            raw = DataIO._read_row_raw(filepath, row_index)
            year = DataIO._file_year(filepath)
            if len(raw) >= 2 and year:
                sec = DataIO._bytepack_year_seconds(raw[0], raw[1])
                return datetime(year, 1, 1) + timedelta(seconds=sec)
        except Exception:
            pass
        try:
            return datetime.fromtimestamp(os.path.getmtime(filepath))
        except Exception:
            return None

    @staticmethod
    def parse_alpha_row_time(filepath, row_index=0):
        """alpha_trace 한 행의 측정시각(datetime). 신포맷의 datetime 컬럼을 우선 읽고,
        없으면 doy 컬럼→datetime(파일 연도 기준). 둘 다 없으면(구포맷) None."""
        hdr = None
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    if line.startswith('row_idx'):
                        hdr = line.rstrip('\n').split('\t')
                        break
                    if not line.startswith('#') and line.strip():
                        break
        except Exception:
            return None
        if not hdr:
            return None
        dt_idx = hdr.index('datetime') if 'datetime' in hdr else None
        doy_idx = hdr.index('doy') if 'doy' in hdr else None
        if dt_idx is None and doy_idx is None:
            return None
        # 해당 데이터 행 읽기
        parts = None
        try:
            cnt = 0
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    s = line.strip()
                    if not s or s.startswith('#') or s.startswith('row_idx'):
                        continue
                    if cnt == row_index:
                        parts = s.split('\t')
                        break
                    cnt += 1
        except Exception:
            return None
        if not parts:
            return None
        if dt_idx is not None and dt_idx < len(parts):
            for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
                try:
                    return datetime.strptime(parts[dt_idx], fmt)
                except (ValueError, IndexError):
                    pass
        if doy_idx is not None and doy_idx < len(parts):
            try:
                yr = DataIO._file_year(filepath) or 2026
                return datetime(yr, 1, 1) + timedelta(days=float(parts[doy_idx]) - 1.0)
            except (ValueError, IndexError):
                pass
        return None

    @staticmethod
    def parse_row_doy(filepath, row_index=0):
        """행의 day-of-year(소수, 1-based) — 박사님 doy 와 동일. 실패 시 None."""
        try:
            raw = DataIO._read_row_raw(filepath, row_index)
            return DataIO._bytepack_year_seconds(raw[0], raw[1]) / 86400.0 + 1.0
        except Exception:
            return None

    @staticmethod
    def all_row_seconds(filepath):
        """파일 전 행의 연초기준 초 배열(벡터화). 60s 평균/시간축용. 실패 시 None."""
        try:
            rows = DataIO._load_file_to_cache(filepath)
            import numpy as _np
            out = _np.full(len(rows), _np.nan)
            for i, r in enumerate(rows):
                if len(r) >= 2:
                    out[i] = DataIO._bytepack_year_seconds(r[0], r[1])
            return out
        except Exception:
            return None

    @staticmethod
    def extract_gas_name(filepath):
        """Returns the gas species name by stripping the path and extension from a filename."""
        base = os.path.basename(filepath)
        return os.path.splitext(base)[0]


# ── 병렬 파싱 워커 (모듈 최상위) ───────────────────────────────────────────────
# multiprocessing 'spawn'(Windows 기본) 자식이 임포트하는 모듈은 이 함수가 사는
# core.data_io 뿐 — Qt 비의존이라 자식 기동이 가볍다. 알파생성 Pass1의 행별
# load_measurement_with_hk 호출을 그대로 워커에서 수행해 '동일 결과'를 보장하고,
# 메인은 결과 배열만 받아 분류/스풀/계산을 한다(로직 이동 0).
RAW_LOAD_FAIL = -999999   # flags[i]가 이 값이면 그 행 로드 실패 → 메인이 SKIP

def extract_raw_file_for_parallel(task):
    """한 raw 파일을 행별로 파싱·추출해 compact 배열로 반환(순수함수, 부작용 없음).

    task = (path, pixel_min, pixel_max, channel)
    반환: (path, flags[int64,(n,)], T[f64,(n,)], P[f64,(n,)],
           specs[f32,(n,npix)], secs[f64,(n,)])

    각 행은 순차 경로와 '같은' DataIO.load_measurement_with_hk 로 추출하므로
    raw 카운트(정수)는 f32에 무손실 → 순차 결과와 바이트 동일.
    """
    path, pixel_min, pixel_max, channel = task
    try:
        n = len(DataIO.expand_to_scan_list(path))
    except Exception:
        n = 0
    flags = np.full(n, RAW_LOAD_FAIL, dtype=np.int64)
    Ts = np.full(n, np.nan, dtype=np.float64)
    Ps = np.full(n, np.nan, dtype=np.float64)
    specs = None
    for i in range(n):
        try:
            _, spec, flag, t, p = DataIO.load_measurement_with_hk(
                path, pixel_min, pixel_max, row_index=i, channel=channel)
        except Exception:
            continue   # 로드 실패 행 → flags[i]=RAW_LOAD_FAIL 유지(메인 SKIP)
        s = np.asarray(spec, dtype=np.float32)
        if specs is None:
            specs = np.zeros((n, len(s)), dtype=np.float32)
        if len(s) != specs.shape[1]:
            continue   # 길이 불일치 행은 skip(정렬 안전, 순차도 spool 깨지는 케이스)
        specs[i] = s
        flags[i] = int(flag)
        Ts[i] = float(t)
        Ps[i] = float(p)
    if specs is None:
        specs = np.zeros((n, 0), dtype=np.float32)
    secs = DataIO.all_row_seconds(path)
    secs = (np.asarray(secs, dtype=np.float64)
            if secs is not None else np.full(n, np.nan, dtype=np.float64))
    return path, flags, Ts, Ps, specs, secs


def read_scans_via_dataio(fp, channel, min_peak=1000.0):
    """data_io 단일파스로 (za, he) 블록 반환 — r_batch_calculator.read_all_scans 대체.

    스펙트럼·스캔선택(MIN_PEAK·플래그 500/510·NaN드롭)은 read_all_scans와 동일,
    T/P는 hk_shift라 트렁케이트(6174)도 실측. 채널 스펙트럼=data_io 채널인덱스
    (1=2053:4101, 2=4101:6149 — read_all_scans SPEC_DEFAULT/ANS와 일치 확인됨).
    중립 모듈(data_io, Qt·r_trend 비의존)에 둬 R Trend·알파 둘 다 순환없이 공유.
    반환: (za, he), 각 원소 (intensity[f64], T_c, P_mbar). 순수함수."""
    _, flags, Ts, Ps, specs, _ = extract_raw_file_for_parallel((fp, 0, _RP_CH_PIXELS, channel))
    za = []
    he = []
    for i in range(len(flags)):
        f = int(flags[i])
        if f == RAW_LOAD_FAIL:
            continue
        sp = np.asarray(specs[i], dtype=float)
        sp = sp[np.isfinite(sp)]
        if sp.size == 0 or float(np.max(sp)) < min_peak:
            continue
        rec = (sp, float(Ts[i]), float(Ps[i]))
        if f == 500:
            za.append(rec)
        elif f == 510:
            he.append(rec)
    return za, he


def scans_worker_for_parallel(task):
    """병렬 파싱 워커(모듈 최상위 — spawn 자식이 Qt 없이 임포트).
    task=(fp, channel, min_peak) → (fp, za, he). 순수함수."""
    fp, channel, min_peak = task
    try:
        za, he = read_scans_via_dataio(fp, channel, min_peak)
    except Exception:
        za, he = [], []
    return fp, za, he
