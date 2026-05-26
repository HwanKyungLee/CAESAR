import os
import re
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone


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
        """Parse a tab-delimited line into a float numpy array."""
        vals = line.strip().split('\t')
        raw = np.empty(len(vals), dtype=float)
        for j, v in enumerate(vals):
            try:
                raw[j] = float(v)
            except (ValueError, TypeError):
                raw[j] = np.nan
        return raw

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

        rows: list = []
        with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rows.append(DataIO._parse_line_to_array(line))

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

    @staticmethod
    def is_araon_mega_matrix(filepath):
        """
        Returns True when the first non-empty row has ≥6175 tab-separated
        columns — the signature of the Araon LabVIEW Mega-Matrix format.
        """
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    if line.strip():
                        return len(line.strip().split('\t')) >= 6175
        except Exception:
            pass
        return False

    # ── Multi-channel layout constants ───────────────────────────────────────
    # Araon Mega-Matrix column layout:
    #   META block  : cols    0 – 2052   (2053 cols, metadata + UTC + flags)
    #   CH1 spectrum: cols 2053 – 4100   (2048 px)
    #   CH2 spectrum: cols 4101 – 6148   (2048 px)  — Hot ROI2/PNs only
    #   CH3 spectrum: cols 6149 – 8196   (2048 px)  — 3-channel config only
    #   HK block    : cols (2053 + N×2048) onward
    #
    # HK offsets *relative* to hk_start (so they work for any channel count):
    _META_COLS = 2053
    _CH_PIXELS = 2048
    _SIG_THRESHOLD = 5000.0     # ADU — below this = noise / inactive channel
    # Relative HK column offsets (verified from 2-channel hot file 2026-05-18):
    _HK_REL = {
        'cold_p':   11,   # Cold inlet pressure raw count → ×0.6895 = mbar
        'hot_p':    13,   # Hot inlet pressure  raw count → ×0.6895 = mbar
        'hot_cav_t': 6,   # Heated cavity temperature    → /100 = °C (~75°C)
        'cold_cav_t':24,  # Unheated cavity temperature  → /100 = °C (~24°C)
        'oven_ans': 5,    # ANs oven setpoint             → /100 = °C (~180°C)
        'oven_pns': 2,    # PNs oven setpoint             → /100 = °C (~300°C)
    }
    _P_SCALE = 0.01 * 6894.73326 / 100.0   # raw count → mbar (~0.6895)
    _P_LO, _P_HI = 800.0, 1200.0           # plausible atmospheric pressure range

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
            if float(np.nanmax(raw[start:end])) > DataIO._SIG_THRESHOLD:
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

    @staticmethod
    def _is_alpha_trace_format(filepath) -> bool:
        """Returns True when the file is a CAESAR Pro alpha_trace.dat (multi-scan TSV)."""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    s = line.strip()
                    if not s:
                        continue
                    if s.startswith('# wavelength_nm:') or s.startswith('row_idx\t'):
                        return True
                    if s.startswith('#'):
                        continue
                    break
        except Exception:
            pass
        return False

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
    def _load_alpha_trace_row(filepath, row_index, pixel_min=0, pixel_max=None):
        """Load one data row from an alpha_trace.dat file.

        Reads T_C, P_mbar, and alpha values for the given data-row index.
        Pads the alpha array to 2048 pixels (zeros outside the exported range)
        so that the caller's pixel_min/pixel_max slicing works correctly.

        Returns (pixel_idx, intensity_raw, state_flag=1, env_t, env_p).
        """
        px_start = 0
        data_rows = []
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    s = line.strip()
                    if not s or s.startswith('#'):
                        continue
                    if s.startswith('row_idx'):
                        cols = s.split('\t')
                        for c in cols[3:]:
                            if c.startswith('px'):
                                try:
                                    px_start = int(c[2:])
                                except ValueError:
                                    pass
                                break
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
            env_t = float(parts[1])
            env_p = float(parts[2])
            alpha_vals = np.array([float(v) for v in parts[3:]], dtype=float)
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
    # CH1 (ROI1 / ANs / 180°C inlet):  cols 2053–4100  (2048 px)
    # CH2 (ROI2 / PNs / 300°C inlet):  cols 4101–6148  (2048 px)
    # HK block starts at col 6149.
    # Cold files have CH1 only (CH2 block is noise ~500 ADU).
    _CH_OFFSET = {1: (2053, 4101), 2: (4101, 6149)}

    @staticmethod
    def load_measurement_with_hk(filepath, pixel_min=0, pixel_max=None,
                                 row_index=0, channel=1):
        """
        Extracts spectrum + housekeeping scalars from the Araon Raw .dat format.

        The Araon LabVIEW system saves each scan as a single horizontal row with
        6175+ columns (the 'Mega-Matrix' format):

          Column range  2053–4100  →  CH1 spectrum  (ROI1 / ANs / 180°C inlet)
          Column range  4101–6148  →  CH2 spectrum  (ROI2 / PNs / 300°C inlet)
          Column        4          →  state flag  (1=Ambient, 500~503=ZA, 510~513=He)
          HK block      6149+      →  T, P, oven temps, etc.

        channel : int, 1 or 2
            Which spectrum to extract.  Default=1 (CH1/ROI1).
            Use channel=2 for CH2/ROI2 (PNs, hot files only).

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

            if len(raw_probe) >= 6175:
                # ── Araon Mega-Matrix format ─────────────────────────────────
                # Dynamic channel slice: CH1=2053:4101, CH2=4101:6149, CH3=6149:8197
                n_ch_in_file = DataIO._detect_n_channels_from_row(raw_probe)
                ch = max(1, min(channel, n_ch_in_file))   # clamp to available channels
                col_start = DataIO._META_COLS + (ch - 1) * DataIO._CH_PIXELS
                col_end   = col_start + DataIO._CH_PIXELS
                intensity_full = raw_probe[col_start:col_end]

                state_flag = int(raw_probe[4])   # Measurement state flag (col 4)

                # ── HK reading — relative offsets from the HK block start ────
                # HK block begins immediately after all spectrum channels:
                #   hk_start = META_COLS + n_channels × CH_PIXELS
                # Using relative offsets makes this layout-independent so the
                # same code works for 1-, 2- and 3-channel Araon files.
                hk = DataIO._META_COLS + n_ch_in_file * DataIO._CH_PIXELS

                def _hk(rel):
                    c = hk + rel
                    v = raw_probe[c] if c < len(raw_probe) else np.nan
                    return v if (np.isfinite(v) and v not in (0, 65535)) else np.nan

                raw_p_count = np.nan
                _t_rel = DataIO._HK_REL['cold_cav_t']   # default: cold cavity T
                for p_rel, t_rel in (
                    (DataIO._HK_REL['cold_p'], DataIO._HK_REL['cold_cav_t']),
                    (DataIO._HK_REL['hot_p'],  DataIO._HK_REL['hot_cav_t']),
                ):
                    pv = _hk(p_rel)
                    if np.isfinite(pv):
                        pm = float(pv) * DataIO._P_SCALE
                        if DataIO._P_LO <= pm <= DataIO._P_HI:
                            raw_p_count = pv
                            _t_rel = t_rel
                            break

                if np.isfinite(raw_p_count):
                    env_p = float(raw_p_count) * DataIO._P_SCALE
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

    @staticmethod
    def parse_row_timestamp(filepath, row_index=0):
        """
        Reconstructs a measurement datetime from an Araon Mega-Matrix row.

        Column layout (verified against 2026-05-18 .dat sample, 6179 cols):
          col 0  → absolute scan counter (constant within one file — NOT a date)
          col 1  → seconds since UTC midnight  (e.g. 44207 = 12:16:47 UTC)

        The calendar date (UTC) is extracted from the filename by the pattern
        "YYYY-MM-DD" (e.g. "2026-05-18-023.dat").  col 1 gives the UTC time
        within that day; the result is then converted to KST (UTC+9).

        Falls back to the file's modification time → KST when the date pattern
        is absent or col 1 is out of the [0, 86400) range.

        Returns: datetime with KST timezone, or None on total failure.
        """
        UTC = timezone.utc
        KST = timezone(timedelta(hours=9))
        _DATE_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})')

        try:
            raw = DataIO._read_row_raw(filepath, row_index)
            if len(raw) >= 6175:
                secs = float(raw[1])   # seconds since UTC midnight (col 1)
                if 0.0 <= secs < 86400.0:
                    fname = os.path.basename(filepath)
                    m = _DATE_RE.search(fname)
                    if m:
                        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
                        base_utc = datetime(year, month, day, tzinfo=UTC)
                        return (base_utc + timedelta(seconds=secs)).astimezone(KST)
        except Exception:
            pass

        # Fallback: file modification time → KST
        try:
            return datetime.fromtimestamp(os.path.getmtime(filepath), tz=KST)
        except Exception:
            return None

    @staticmethod
    def extract_gas_name(filepath):
        """Returns the gas species name by stripping the path and extension from a filename."""
        base = os.path.basename(filepath)
        return os.path.splitext(base)[0]
