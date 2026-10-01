import ntpath
import os
import re
import sys
import threading
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
    CAMPAIGN_LAYOUTS as _CAMPAIGN_LAYOUTS,
    ROLE_BLOCKS as _RP_ROLE_BLOCKS,
    _in_date_range as _rp_in_date_range,
    FLAG_HEADER,
    FLAG_AMBIENT,
)


# ui_scale 은 core/ui_metrics.py 가 정의한다(부팅 경로가 data_io 전체를 끌어오지 않게). 기존 임포트 호환.
from .ui_metrics import ui_scale  # noqa: E402,F401


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
    # 헤더행 T/P를 끌어올 때 앞쪽으로 몇 행까지 볼지. 헤더행은 파일당 1행이라
    # 보통 +1 에서 끝난다 — 여유는 재시작으로 헤더가 연달아 찍히는 경우 대비.
    _HK_BORROW_LOOKAHEAD = 5

    _row_cache: dict = {}   # { (path, mtime): [row0_arr, row1_arr, ...] }
    _cached_key: tuple | None = None  # key of the currently cached file

    # alpha_trace 파일 텍스트 캐시 (2026-10-01). 핏 루프는 스캔마다
    # `load_alpha_trace_row_full`(파일 전체 읽기) + `parse_alpha_row_time`(두 번 열기) +
    # `_alpha_layout`(헤더) 을 불러 파일 하나를 **행 수만큼 통째로** 다시 읽었다 — 행당 ~77 ms,
    # 핏 2.5 ms 의 30배, 파일 크기에 대해 O(rows²). 이제 파일당 한 번 읽어 (헤더, 파장축,
    # 데이터 줄 문자열)만 들고 있고, **각 행의 파싱은 종전 코드 그대로** 한다 — 출력 바이트동일.
    # 키에 mtime_ns·size 를 넣어 파일이 바뀌면(재생성·append) 다시 읽는다. 작은 LRU + 락:
    # 채널별 QThread 가 서로 다른 파일을 동시에 돈다.
    _ALPHA_CACHE_MAX = 4
    _alpha_cache: dict = {}            # {(abspath, mtime_ns, size): (hdr, wave_nm, data_rows)}
    _alpha_cache_lock = threading.Lock()
    _ncols_cache: dict = {}            # {(abspath, mtime_ns, size): 앞 10줄 최대 열 수} — clock_epoch_offset_sec

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
    # NOTE: must be <= the *truncated* cold width (6174). 2026-06-11 ~ 06-15 의
    # 콜드 raw는 HK **선두 5열**이 빠진 6174열 구성이다(정상 콜드 = 6179).
    # 전수조사(2026-09-15, E:/Yeosu_2026/CAESAR_Cold 751개): 6174가 97개이고
    # 6/11-020 ~ 6/15-026 **5일치 연속 블록**이다 — "첫 행만" 짧은 게 아니라
    # 파일 전체(각 ~3700행)가 그 구성이고, 경계는 둘 다 재시작 직후다
    # (6/11-019가 1572행에서 끊기고 020부터 6174, 6/15-026이 1844행에서
    #  끊기고 027부터 6179로 복귀). 손실이 **선두**라는 근거와 복구 방법은
    # 아래 load_measurement_with_hk 의 hk_shift 주석 참고(거기가 정본).
    # 옛 >=6175 문턱은 이 파일들을 단일스캔으로 오분류해 expand_to_scan_list()가
    # [(fp, 0)]만 돌려줬고 알파가 bin당 한 줄만 나왔다. 4101이면 정상 6179/6177도
    # 잡으면서 6174도 같이 잡는다. See cold-alpha-6175-threshold-bug-2026-06.
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
    #   CH2 spectrum: cols 4101 – 6148   (2048 px)  — Hot only (2026 여수: PNs 180 °C; CH1 = ANs 300 °C — 2026-09-27 판정)
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
    # 같은 경고를 스캔마다 찍으면(초당 1행) 로그가 묻힌다 — 문구당 한 번만.
    _warned: set = set()

    @staticmethod
    def _slot_identity(lay, ch: int, filepath):
        """슬롯 번호 `ch`(1=block 2053, 2=block 4101)에 붙은 채널 **이름**을 돌려준다.

        레이아웃에 이름이 없거나, 이름의 유효 날짜 구간(date_range) 밖 파일이면 None.
        파일명에 날짜가 없으면 raw_parser와 같은 규칙으로 제한하지 않는다.
        """
        if lay is None or not getattr(lay, 'channels', None):
            return None
        dr = getattr(lay, 'date_range', None)
        if dr and not _rp_in_date_range(str(filepath), None, dr):
            return None
        start = DataIO._META_COLS + (int(ch) - 1) * DataIO._CH_PIXELS
        for name, role in lay.channels.items():
            blk = _RP_ROLE_BLOCKS.get(role) if isinstance(role, str) else tuple(role)
            if blk is not None and int(blk[0]) == start:
                return str(name)
        return None

    @staticmethod
    def _warn_once(msg: str) -> None:
        if msg not in DataIO._warned:
            DataIO._warned.add(msg)
            print(f"[data_io][WARN] {msg}")
    _HK_REL = {
        'cold_p':   11,   # Cold inlet pressure raw count → ×0.6895 = mbar
        'hot_p':    13,   # abs 6162 = P_PNs = 180 °C 경로 = 캠페인 block 4101 (레거시 폴백 전용)
        'hot_p_ans':15,   # abs 6164 = P_ANs = 300 °C 경로 = 캠페인 block 2053 (레거시 폴백 전용)
        'hot_cav_t': 6,   # Cell-heater SETPOINT (~75°C) — 가스온도 아님(과냉방지용).
                          # 최후 폴백 전용. 쓰면 ppb 가 ~15% 과대평가(아래 주석 참조).
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

    # 행수 디스크 캐시: raw는 불변이라 (경로,크기,mtime)이 같으면 행수도 같다.
    # 100MB×1200파일 인덱싱(구 텍스트루프 ~20s/파일 = 침묵 7시간!)을 첫 1회 이후 0초로.
    _scan_count_cache: dict | None = None
    _scan_count_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'logs', 'scan_count_cache.json')

    @staticmethod
    def _scan_cache_load():
        if DataIO._scan_count_cache is None:
            try:
                import json
                with open(DataIO._scan_count_path, encoding='utf-8') as fh:
                    DataIO._scan_count_cache = json.load(fh)
            except Exception:
                DataIO._scan_count_cache = {}
        return DataIO._scan_count_cache

    @staticmethod
    def _scan_cache_save():
        try:
            import json
            os.makedirs(os.path.dirname(DataIO._scan_count_path), exist_ok=True)
            with open(DataIO._scan_count_path, 'w', encoding='utf-8') as fh:
                json.dump(DataIO._scan_count_cache, fh)
        except Exception:
            pass

    @staticmethod
    def count_scan_rows(filepath):
        """Counts the number of non-empty rows (= scans) in a Mega-Matrix file.

        바이너리 청크로 비어있지 않은 라인을 센다(구 텍스트 라인루프 대비 ~20배 —
        USB HDD 100MB 기준 20s→~1s). 텍스트 모드와 동일 기준: CRLF/LF 파일에서
        strip 후 비지 않은 라인 수 (raw는 LabVIEW CRLF — 검증됨).
        결과는 (크기,mtime) 키로 logs/scan_count_cache.json 에 캐시."""
        try:
            st = os.stat(filepath)
            key = f"{os.path.abspath(filepath)}|{st.st_size}|{st.st_mtime_ns}"
        except OSError:
            key = None
        if key is not None:
            hit = DataIO._scan_cache_load().get(key)
            if hit is not None:
                return int(hit)
        count = 0
        try:
            with open(filepath, 'rb') as fh:
                tail = b''
                while True:
                    chunk = fh.read(1 << 23)   # 8MB
                    if not chunk:
                        break
                    lines = (tail + chunk).split(b'\n')
                    tail = lines.pop()
                    for ln in lines:
                        if ln.strip():
                            count += 1
                if tail.strip():
                    count += 1
        except Exception:
            pass
        if key is not None and count:
            DataIO._scan_cache_load()[key] = count
            DataIO._scan_cache_save()
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
        try:
            hdr, wave_nm, _rows = DataIO._alpha_file(filepath)
        except Exception:
            hdr, wave_nm = None, None
        if wave_nm is not None:
            wave_nm = wave_nm.copy()   # 캐시 원본을 호출부가 고쳐 쓰지 않게(종전엔 매번 새 배열)
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
    def _alpha_file(filepath):
        """alpha_trace 파일 → (hdr 열 이름 목록|None, wave_nm|None, 데이터 줄 문자열 목록). 캐시됨.

        한 번의 통과로 종전 세 함수의 규칙을 그대로 재현한다:
          - 헤더 탐색(`_alpha_layout`·`parse_alpha_row_time`): '# wavelength_nm:' 은 파장축,
            'row_idx' 로 시작하면 헤더, 그 전에 주석 아닌 빈 줄 아닌 줄이 나오면 헤더 없음.
          - 데이터 행(`load_alpha_trace_row_full`·`parse_alpha_row_time`): strip 한 줄 중
            빈 줄·'#'·'row_idx' 로 시작하는 것 제외.
        읽기 실패는 그대로 던진다(호출부마다 종전 처리 — 기본값/None/예외)."""
        st = os.stat(filepath)
        key = (os.path.abspath(filepath), st.st_mtime_ns, st.st_size)
        with DataIO._alpha_cache_lock:
            hit = DataIO._alpha_cache.pop(key, None)
            if hit is not None:
                DataIO._alpha_cache[key] = hit          # 최근 사용으로(dict 삽입 순서 = LRU)
                return hit
        wave_nm = None
        hdr = None
        hdr_done = False
        data_rows = []
        with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if not hdr_done:
                    if line.startswith('# wavelength_nm:'):
                        try:
                            wave_nm = np.array([float(v) for v in line.split(':', 1)[1].strip().split('\t')
                                                if v.strip()], dtype=float)
                        except Exception:
                            pass
                    elif line.startswith('row_idx'):
                        hdr = line.rstrip('\n').split('\t')
                        hdr_done = True
                    elif not line.startswith('#') and line.strip():
                        hdr_done = True
                s = line.strip()
                if not s or s.startswith('#') or s.startswith('row_idx'):
                    continue
                data_rows.append(s)
        entry = (hdr, wave_nm, data_rows)
        with DataIO._alpha_cache_lock:
            DataIO._alpha_cache[key] = entry
            while len(DataIO._alpha_cache) > DataIO._ALPHA_CACHE_MAX:
                DataIO._alpha_cache.pop(next(iter(DataIO._alpha_cache)))
        return entry

    @staticmethod
    def read_alpha_trace_wavelengths(filepath):
        """alpha_trace.dat의 '# wavelength_nm:' 채널별 파장축(없으면 None)."""
        return DataIO._alpha_layout(filepath)[4]

    @staticmethod
    def load_wavecal_array(path):
        """wavecal 파일 → 1D nm 배열(첫 번째 수치 컬럼). 실패하면 None.

        파장축은 모든 숫자의 x축이라 파서가 갈리면 안 된다 — 이게 **단일 출처**다.
        gui(app_window_fitsetup / app_window_save) · core.refit · tools.optimize_params가
        전부 여기로 위임한다(예전엔 같은 코드가 4벌이었다).

        `comment='#'`이 중요하다: 주석 헤더가 있는 Calib 파일은 헤더 줄의 토큰 수가 달라
        공백 파싱이 ParserError를 내고, **쉼표 파싱 폴백이 우연히 성공**해서 지금까지 맞는
        답이 나왔다. 열이 2개가 되는 날 그 운은 끝난다.

        회귀: `tools/test_wavecal_loader.py` — 저장소의 실측 Calib 파일 전부에 대해
        이 함수와 `np.loadtxt`가 같은 배열을 내는지 본다.
        """
        try:
            try:
                df = pd.read_csv(path, sep=r'\s+', header=None, comment='#')
            except Exception:                       # noqa: BLE001
                df = pd.read_csv(path, sep=',', header=None, comment='#')
            for i in range(df.shape[1]):
                col = pd.to_numeric(df.iloc[:, i], errors='coerce').dropna()
                if len(col) > 10:
                    return col.values.flatten()
        except Exception:                           # noqa: BLE001
            pass
        return None

    @staticmethod
    def wavecal_fwhm_nm(path):
        """Calib 파일 헤더에서 ILS FWHM(nm)을 읽는다. 없으면 None.

        헤더 예: `# Info: Average FWHM: 0.683 nm (calculated from 4 peaks)`

        왜 여기 있나 — 이 값은 `run_meta`의 `calibration.ils_fwhm_nm`으로 결과
        파일에 박히는데, 예전엔 **웨이브캘 다이얼로그를 그 세션에 직접 돌린 경우에만**
        채워졌다. 파일을 불러오기만 하면 0.0이 기록됐고, 0.0은 "ILS 폭을 모른다"가
        아니라 "폭이 0이다"로 읽힌다. 파일이 값을 들고 있으니 파일에서 읽는다.
        """
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    if not line.lstrip().startswith('#'):
                        break                      # 헤더 끝 — 더 볼 필요 없다
                    m = re.search(r'FWHM\s*[:=]\s*([0-9]*\.?[0-9]+)\s*nm', line,
                                  re.IGNORECASE)
                    if m:
                        v = float(m.group(1))
                        return v if v > 0 else None
        except Exception:                           # noqa: BLE001
            pass
        return None

    @staticmethod
    def _load_alpha_trace_row(filepath, row_index, pixel_min=0, pixel_max=None):
        """Load one data row from an alpha_trace.dat file (구·신 포맷 호환).

        헤더 위치로 T_C/P_mbar/alpha 컬럼을 판정(타임스탬프 doy/datetime 컬럼 대응).
        Pads the alpha array to 2048 pixels (zeros outside the exported range)
        so the caller's pixel_min/pixel_max slicing works.
        Returns (pixel_idx, intensity_raw, state_flag=FLAG_AMBIENT, env_t, env_p).
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

        return pixel_idx, intensity_raw, FLAG_AMBIENT, env_t, env_p

    @staticmethod
    def load_alpha_trace_row_full(filepath, row_index):
        """alpha_trace 한 행을 (wave_nm, alpha, T, P)로 — 패딩/슬라이스 없이 실제 데이터.

        AnalysisWorker가 알파를 그 채널 자체 파장축으로 피팅하도록 쓰는 경로
        (마스터 wavecal이 아니라 알파에 박힌 채널별 파장 사용)."""
        first_px, t_idx, p_idx, px_start, wave_nm = DataIO._alpha_layout(filepath)
        data_rows = DataIO._alpha_file(filepath)[2]   # 파일당 1회 읽기(캐시) — 행 파싱은 아래 그대로
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
    def load_alpha_trace_row_mapped(filepath, row_index=0):
        """Full alpha row plus its detector-pixel origin from the parsed header."""
        _first, _t, _p, px_start, _wave = DataIO._alpha_layout(filepath)
        wave, alpha, env_t, env_p = DataIO.load_alpha_trace_row_full(filepath, row_index)
        return wave, alpha, env_t, env_p, int(px_start)

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

    @staticmethod
    def load_measurement_with_hk(filepath, pixel_min=0, pixel_max=None,
                                 row_index=0, channel=1, _borrow_hk=True):
        """
        Extracts spectrum + housekeeping scalars from the Araon Raw .dat format.

        The Araon LabVIEW system saves each scan as a single horizontal row with
        6175+ columns (the 'Mega-Matrix' format):

          Column range  2053–4100  →  CH1 spectrum  (2026 여수: ANs / 300°C inlet, 청색 LED — 2026-09-27 판정)
          Column range  4101–6148  →  CH2 spectrum  (2026 여수: PNs / 180°C inlet, 469 nm LED)
          Column        4          →  state flag  (1=Ambient, 500~503=ZA, 510~513=He)
          HK block      6149+      →  T, P, oven temps, etc.

        channel : int, 1+
            Which spectrum to extract.  Default=1 (CH1/ROI1). Use channel=2 for
            CH2/ROI2 (ANs, hot files). Slicing below is structural (column-count
            based, see `n_slots`), not hardcoded to 1-2 — a file with more active
            channel blocks (e.g. a reconfigured instrument) works automatically;
            only the CH1/CH2 comment above describes today's known configs.

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
            # 이 행의 raw 구성 — **열 수가 곧 구성**이다(6181 hot / 6179·6174 cold).
            # 값이 그럴듯한지로 열을 찾지 않기 위한 단일 진입점.
            _lay = _CAMPAIGN_LAYOUTS.get(len(raw_probe))

            # Safe defaults in case housekeeping columns are missing.
            # flag는 Araon 분기에서 raw col4로 덮어쓰고, 비-Araon 1D 분기는
            # 아래에서 FLAG_AMBIENT로 확정한다 — 여기 0은 두 분기 모두 살아남지
            # 않는다(살아남으면 FLAG_HEADER와 구별이 안 된다).
            state_flag = FLAG_HEADER
            env_t = 25.0
            env_p = 1013.25

            # Araon row gate: a single full channel (META + CH1 = 4101 cols) is
            # enough to parse spectrum + HK. The old 6175 floor mis-routed rows
            # that were truncated by a few tail-HK columns (e.g. a LabVIEW write
            # cut short) into the 1D fallback below, which re-reads the *entire*
            # multi-MB file per row → O(n²) hang. Spectrum/P/T live well before
            # 4101, and missing tail HK is already guarded as NaN in _hk().
            if len(raw_probe) >= DataIO._META_COLS + DataIO._CH_PIXELS:
                # ── Araon Mega-Matrix ─────────────────────────────────────────
                # raw 포맷은 **3채널 전제**다(계기 담당자 확인 2026-09-15):
                #   meta 0-4 · 슬롯A 5-2052 · 슬롯B 2053-4100 · 슬롯C 4101-6148 · HK 6149-
                # META_COLS(2053) = 5 + 1×2048 이라 **슬롯A를 meta에 흡수**한 셈이고,
                # 그래서 아래 n_slots 는 "남은 슬롯 수"(2026 여수 = 2)다. hk 시작이
                # META_COLS + n_slots×CH = 5 + 3×CH = 6149 로 맞아떨어지는 이유.
                # ⚠ 슬롯A는 이 정수 `channel` 로 주소가 없다 — 켜는 구성이 생기면
                #   레이아웃에 block_a 채널을 등록해야 한다(보고서 §4-J).
                n_slots = max(1, (len(raw_probe) - DataIO._META_COLS) // DataIO._CH_PIXELS)
                nch = len(_lay.channels) if _lay is not None else n_slots
                if channel > max(nch, 1):
                    # 예전엔 조용히 clamp 해서 **다른 채널 데이터가 경고 없이** 돌아왔다
                    # (실측: 핫에서 channel=3 이 channel=2 와 같은 배열). 구조적으로
                    # 존재하는 슬롯이면 그대로 주되, 침묵하지는 않는다.
                    DataIO._warn_once(
                        f"channel={channel} requested, but this configuration ({len(raw_probe)} columns) registers "
                        f"{nch} channel(s). Reading slot {min(channel, n_slots)} instead — "
                        f"check the channel number")
                ch = max(1, min(channel, n_slots))   # 구조적으로 있는 슬롯까지만
                col_start = DataIO._META_COLS + (ch - 1) * DataIO._CH_PIXELS
                col_end   = col_start + DataIO._CH_PIXELS
                intensity_full = raw_probe[col_start:col_end]

                state_flag = int(raw_probe[4])   # Measurement state flag (col 4)

                # ── HK — **열 번호는 레지스트리가 안다. 값으로 찾지 않는다.** ──────
                # 예전엔 "6160을 읽어 800~1200 mbar 면 cold, 아니면 6162를 읽어…" 식으로
                # **값이 그럴듯한지로 어느 열이 압력인지를 판별**했다. 그 창을 벗어나는
                # 환경(고지대·항공)에서는 압력 열을 못 찾고 T·P 가 **조용히** 기본값
                # (1013.25 / 25.0)으로 떨어졌다 — 5.5 km 면 n_air 가 2배 틀리고 ppb 가
                # 절반으로 나온다. 온도도 `0 < T < 100 °C` 게이트라 0.00 °C·영하·가열셀에서
                # 같은 식으로 탈락했다.
                # raw 구성은 **열 수 하나로 결정**되므로(6181 hot / 6179·6174 cold)
                # 레지스트리에서 지도를 받아 박힌 열을 읽는다. 값 탐색 0회.
                # 범위(_P_LO~_P_HI)는 이제 **판별이 아니라 경보**로만 쓴다.
                if _lay is not None and _lay.hk_map:
                    def _get(*names):
                        """이름 후보를 순서대로 — 없으면 kind 로 아무거나(미지 캠페인 대비)."""
                        for nm in names:
                            ent = _lay.hk_map.get(nm)
                            if ent is None:
                                continue
                            c = ent[0]
                            if 0 <= c < len(raw_probe):
                                v = raw_probe[c]
                                if np.isfinite(v) and v not in (0, 65535):
                                    return float(v) * ent[1]
                        return np.nan

                    def _any_of_kind(kind):
                        for nm, ent in _lay.hk_map.items():
                            if ent[3] != kind:
                                continue
                            c = ent[0]
                            if 0 <= c < len(raw_probe):
                                v = raw_probe[c]
                                if np.isfinite(v) and v not in (0, 65535):
                                    return float(v) * ent[1]
                        return np.nan

                    # 채널별 선호 이름 → 공통 이름 → 같은 kind 아무거나.
                    # 'Cold'/'Hot' 같은 구성 이름으로 분기하지 않는다(Vigil 설계 §0-A.6).
                    # ★ 압력 센서는 **채널 정체(이름)로** 고른다 — 슬롯 번호로 고르지 않는다
                    #   (2026-09-27 판정, CHANNEL_IDENTITY_YEOSU2026.md §4). 여수 캠페인에서
                    #   P_ANs(6164)는 300 °C 경로 = primary(block 2053, 'ANs'),
                    #   P_PNs(6162)는 180 °C 경로 = secondary(block 4101, 'PNs').
                    #   근거: 6164가 캠페인 내내 ~43 mbar 낮고, 9/27 180 °C 라인만 바꿨을 때
                    #   6162의 He−ZA dP만 18→10 mbar로 변함(6164는 41→43 그대로).
                    #   예전 코드는 슬롯 1 ← P_PNs, 슬롯 2 ← P_ANs 로 **반대**였다(채널당 ~0.6 %).
                    #   이름이 없는 파일(date_range 밖·미등록)은 예전 슬롯 규칙을 유지한다 —
                    #   9/27 이후 실험실 raw는 block 4101 = 300 °C 셀이라 그 규칙이 맞다.
                    _ident = DataIO._slot_identity(_lay, ch, filepath)
                    if _ident == 'ANs':
                        pv = _get('P_ANs', 'cavity_P', 'p_cavity')
                    elif _ident == 'PNs':
                        pv = _get('P_PNs', 'cavity_P', 'p_cavity')
                    elif ch >= 2:
                        pv = _get('P_ANs', 'P_PNs', 'cavity_P', 'p_cavity')
                    else:
                        pv = _get('P_PNs', 'cavity_P', 'p_cavity')
                    # 셀 온도 센서(tempcell1/2)의 캐비티 짝은 데이터로 특정 불가(오븐과 무관하게
                    # 항상 +3.1–3.4 °C 차) — 영향 < 0.1 %라 슬롯 규칙 그대로 둔다.
                    if ch >= 2:
                        tv = _get('tempcell2', 'tempcell1', 'cavity_T', 't_cavity')
                    else:
                        tv = _get('tempcell1', 'tempcell2', 'cavity_T', 't_cavity')
                    if not np.isfinite(pv):
                        pv = _any_of_kind('press')
                    if not np.isfinite(tv):
                        # 최후: 셀히터 **설정값**(~75 °C). 실측 가스온도보다 45 K 높아
                        # ppb 를 ~15 % 과대평가하므로 정말 마지막이다.
                        tv = _get('cavity_gas_T')
                    if not np.isfinite(tv):
                        tv = _any_of_kind('temp')

                    if np.isfinite(pv):
                        env_p = float(pv)
                        if not (DataIO._P_LO <= env_p <= DataIO._P_HI):
                            # **버리지 않는다** — 고지대·항공이면 정상값이다(무결성 헌장).
                            DataIO._warn_once(
                                f"Pressure {env_p:.1f} mbar is outside the expected ground-level range "
                                f"({DataIO._P_LO:.0f}~{DataIO._P_HI:.0f}) — "
                                f"normal at altitude/airborne, otherwise check the HK columns")
                    if np.isfinite(tv):
                        env_t = float(tv)
                else:
                    # ── 미등록 구성 폴백(레거시) ──────────────────────────────
                    # 등록된 레이아웃이 없으면 열 지도를 모른다. 여수 raw 2065개는 전부
                    # 등록 구성(6174/6179/6181)이라 이 경로를 타지 않는다. 새 구성은
                    # 레이아웃을 등록하거나 프로파일 JSON 을 얹는 것이 정답이고, 이
                    # 값-탐색은 그때까지의 임시 버팀목이다(그래서 여기만 남겨둔다).
                    hk = DataIO._META_COLS + n_slots * DataIO._CH_PIXELS
                    hk_shift = 0
                    _std = next((s for s in (6179, 6181) if s >= len(raw_probe)), None)
                    if _std is not None and 0 < (_std - len(raw_probe)) <= 64:
                        hk_shift = _std - len(raw_probe)

                    def _hk(rel):
                        c = hk + rel - hk_shift
                        v = raw_probe[c] if 0 <= c < len(raw_probe) else np.nan
                        return v if (np.isfinite(v) and v not in (0, 65535)) else np.nan

                    _t_rel = DataIO._HK_REL['cold_cav_t']
                    for p_rel, t_rel, is_hot in (
                        (DataIO._HK_REL['cold_p'], DataIO._HK_REL['cold_cav_t'], False),
                        (DataIO._HK_REL['hot_p'],  DataIO._HK_REL['hot_cav_t'],  True),
                    ):
                        pv = _hk(p_rel)
                        if np.isfinite(pv):
                            pm = float(pv) * DataIO._P_SCALE
                            if DataIO._P_LO <= pm <= DataIO._P_HI:
                                env_p = pm
                                _t_rel = t_rel
                                if is_hot:
                                    for _name in (('tempcell1', 'tempcell2') if ch == 1
                                                  else ('tempcell2', 'tempcell1')):
                                        _tc = _hk(DataIO._HK_REL[_name])
                                        if np.isfinite(_tc) and 0.0 < float(_tc) / 100.0 < 100.0:
                                            _t_rel = DataIO._HK_REL[_name]
                                            break
                                break
                    tv = _hk(_t_rel)
                    if np.isfinite(tv):
                        env_t = float(tv) / 100.0
            else:
                # ── Regular 1D file (one value per line, e.g. alpha trace) ──
                # flag 컬럼이 **없는** 파일이다. 예전엔 기본값 0이 그대로 나가서
                # `flag=0`이 "LabVIEW 헤더행"과 "flag 컬럼 없음" 두 뜻으로 겹쳤고,
                # 그래서 같은 raw가 경로마다 다르게 처리됐다(_run은 ambient로 피팅,
                # AlphaExportWorker._process_scan은 skip). 여기서 ambient로 확정해
                # `flag=0`을 **오직 헤더행**으로 남긴다 — 알파 경로가 이미 하던 것과 동일
                # (보고서 docs/기초파싱_전수검증_2026-09-15.md §4-E).
                state_flag = FLAG_AMBIENT
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

            # ── 헤더행(FLAG_HEADER)의 T/P를 이웃 실측행에서 끌어온다 ────────────
            # LabVIEW는 파일 첫 행에 flag=0 을 쓰면서 **HK 28열을 전부 65535(값없음)**
            # 로 남긴다. 그래서 위 로직이 T/P를 못 찾고 기본값 25.0 °C / 1013.25 mbar
            # 로 떨어지는데, 이건 계기가 잰 값이 아니라 코드가 만든 상수다. 그 상수로
            # 계산한 n_air 는 실측 대비 0.2 %(콜드) ~ 3.7 %(핫) 어긋나고, 그 행의
            # α·ppb 가 **아무 표시 없이** 다른 스캔과 같은 표에 섞인다.
            #
            # 인접 행의 T/P 실측 변화는 |ΔT| median 0.0000 °C · |ΔP| median 0.0000 mbar
            # (핫·콜드 각 59행 실측)이라, 약 1~2 초 뒤 행의 값을 쓰면 오차가 사실상 0이다.
            # 그래서 **버리지 않고 끌어온다**(운용자 결정 2026-09-15, 무결성 헌장).
            #
            # 끌어왔다는 사실은 반환값에 따로 안 싣는다 — `state_flag == FLAG_HEADER`
            # 자체가 그 표식이다(비-Araon 1D 분기가 FLAG_AMBIENT를 돌려주게 바뀐 뒤로
            # flag=0 은 **오직 헤더행**을 뜻한다). 소비자는 그 조건으로 출처를 적으면 된다.
            # ponytail: 앞으로만 본다(헤더행은 파일 맨 앞 1행이므로). 파일 끝에도
            #   HK 결손이 생기면 뒤로도 보게 할 것.
            if _borrow_hk and state_flag == FLAG_HEADER:
                for nxt in range(row_index + 1, row_index + 1 + DataIO._HK_BORROW_LOOKAHEAD):
                    try:
                        _, _, f2, t2, p2 = DataIO.load_measurement_with_hk(
                            filepath, 0, 1, row_index=nxt, channel=channel, _borrow_hk=False)
                    except Exception:               # noqa: BLE001
                        break
                    if f2 != FLAG_HEADER:
                        env_t, env_p = t2, p2
                        break

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

    _TS_WARNED = set()          # 파일당 한 번만 경고(행마다 호출된다)

    @staticmethod
    def parse_row_timestamp(filepath, row_index=0):
        """Araon row의 (col0,col1) bytepack → naive datetime (박사님 doy와 동일, 타임존 변환 없음).

        연도는 파일명 YYYY-MM-DD 에서 취한다(bytepack은 연초 기준이라 연도 필요).
        읽지 못하면 **None**. 호출부(worker)는 Time 칸에 "row NNNN"을 적는다.

        2026-09-15 — 파일 수정시각(mtime) 폴백을 없앴다
        ------------------------------------------------
        초기에는 bytepack 디코드가 가끔 이상한 시각을 뱉어서, "raw를 다시 저장만
        안 하면 mtime = 측정 완료 시각"이라는 성질을 차선책으로 썼다. 그 전제는
        파일을 복사·이동·재저장하는 순간 조용히 깨지고(복사 시각이 찍힌다),
        깨져도 **그럴듯한 시각**이 나오기 때문에 아무도 모른다 — 시각은
        프로바넌스라 조용히 틀리면 제일 비싸다.

        그 차선책의 전제였던 "디코드가 가끔 이상하다"는 이제 성립하지 않는다.
        전수검증(2026-09-15, 2065파일/7,538,129행)에서 파일명 날짜 vs bytepack
        디코드가 **2065/2065 일치**, 행간격 중앙값 97 cs가 전 파일·파일경계까지
        동일했다(`docs/기초파싱_전수검증_2026-09-15.md`). 원인이던 레이아웃
        오판(헤더가 데이터보다 넓을 때 데이터행을 통째로 버리던 건)도 같은 날
        고쳐졌다. 그래서 이제 폴백이 뜨면 그건 **뉴스**이고, 조용히 mtime으로
        때우는 대신 시끄럽게 알려야 한다.
        """
        try:
            raw = DataIO._read_row_raw(filepath, row_index)
            year = DataIO._file_year(filepath)
            if len(raw) >= 2 and year:
                # `all_row_seconds`와 같은 시계여야 한다 — 알파 경로와 raw 직접
                # 피팅 경로가 같은 파일에 다른 시각을 매기면 안 된다(핫 5/29).
                sec = (DataIO._bytepack_year_seconds(raw[0], raw[1])
                       + DataIO.clock_epoch_offset_sec(filepath))
                return datetime(year, 1, 1) + timedelta(seconds=sec)
            reason = ("no YYYY-MM-DD in file name" if not year
                      else f"too few columns in row ({len(raw)})")
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"
        if filepath not in DataIO._TS_WARNED:
            DataIO._TS_WARNED.add(filepath)
            print(f"[data_io] ⚠ Could not read scan time — {os.path.basename(filepath)}: "
                  f"{reason}. The mtime fallback was removed on 2026-09-15 (copying files makes it "
                  f"silently wrong). The Time cell stays 'row NNNN'.", file=sys.stderr)
        return None

    @staticmethod
    def parse_alpha_row_time(filepath, row_index=0):
        """alpha_trace 한 행의 측정시각(datetime). 신포맷의 datetime 컬럼을 우선 읽고,
        없으면 doy 컬럼→datetime(파일 연도 기준). 둘 다 없으면(구포맷) None."""
        try:
            hdr, _wave, data_rows = DataIO._alpha_file(filepath)   # 파일당 1회 읽기(캐시)
        except Exception:
            return None
        if not hdr:
            return None
        dt_idx = hdr.index('datetime') if 'datetime' in hdr else None
        doy_idx = hdr.index('doy') if 'doy' in hdr else None
        if dt_idx is None and doy_idx is None:
            return None
        # 해당 데이터 행 (종전: 줄을 세어 row_index 번째 — 음수·범위 밖은 None)
        parts = data_rows[row_index].split('\t') if 0 <= row_index < len(data_rows) else None
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
        """행의 day-of-year(소수, 1-based) — 박사님 doy 와 동일. 실패 시 None.

        `all_row_seconds`와 같은 시계(핫 5/29 epoch 보정 적용)."""
        try:
            raw = DataIO._read_row_raw(filepath, row_index)
            sec = (DataIO._bytepack_year_seconds(raw[0], raw[1])
                   + DataIO.clock_epoch_offset_sec(filepath))
            return sec / 86400.0 + 1.0
        except Exception:
            return None

    # ── 핫 PC 2026-05-29 UTC-toggle 시계 사건 ────────────────────────────────
    # hot PC 는 2026-05-18 배치부터 2026-05-29 09:29 KST 재부팅 **전까지** bytepack 에
    # UTC 변환을 걸지 않았다 — 그 구간의 기록값은 사실상 이미 KST 다. 나머지 캠페인
    # (정상 = UTC)과 같은 축에 놓으려면 그 구간만 −9h 해서 UTC 로 되돌린다.
    # **+9h 를 뒤 구간에 더하면 안 된다** — 하류(migrate_kst_plus9 등)가 전 구간에
    # 다시 +9h 를 걸므로 이중보정된다. 내부 축의 규약은 언제나 '기록 UTC'다.
    #
    #   경계: 2026-05-29-010 (마지막 구컨벤션, 기록 09:37:01)
    #       → 2026-05-29-011 (첫 신컨벤션,  기록 01:06:57)
    #     보정 후 00:37:01 → 01:06:57 로 **전진**(재시작 공백 29m56s).
    #
    #   · 콜드 PC 는 이 문제가 없다 — 31일 전수감사에서 오프셋이 처음부터 끝까지 정상.
    #     그래서 핫/콜드를 갈라야 하는데, 파일명은 두 계기가 똑같아서(YYYY-MM-DD-NNN)
    #     **경로가 아니라 데이터 열수로 가른다**: 핫 데이터행 6181 / 콜드 6179.
    #     열수가 둘 중 어느 쪽도 아니면(예: 콜드 6174 결손 구간) 보정하지 않는다.
    #   · ±65s 잔차는 상수인지 드리프트인지 **원리상 미해결**이라(외부 앵커가 7/13
    #     한 점뿐) 보정하지 않는다 — 데이터 무결성 원칙: 근거 약한 보정보다 원값+flag.
    #
    # 근거: docs/기초파싱_전수검증_2026-09-15.md §3(−8.50 h 경계 실측),
    #       docs/NO2_인젝션_실험_핸드오프_2026-08.md(하류에서 발견된 경위),
    #       필드로그 5/29 "CAESAR-Hot Program restart 09:29 (KST)".
    HOT_NCOLS = 6181                              # 핫 데이터행 열수(콜드 6179)
    HOT_UTC_TOGGLE_STEM = "2026-05-29-011"        # 이 파일**부터** UTC 변환 ON
    HOT_DEPLOY_STEM = "2026-05-18-001"            # 핫 배치 첫 파일(하한)
    HOT_PRE_TOGGLE_SHIFT_SEC = -32400.0           # 구컨벤션(KST 기록) → UTC

    @staticmethod
    def clock_epoch_offset_sec(filepath, rows=None, ncols=None):
        """이 파일의 bytepack 시각에 더해야 할 초. 해당 없으면 0.0.

        파일명 스템(`YYYY-MM-DD-NNN`)은 고정폭이라 사전순 비교가 곧 시간순이다.
        `ncols`(데이터행 폭)를 이미 알면 넘겨라 — 없으면 파일을 펼쳐서 센다(비쌈).
        날짜 범위를 먼저 보므로 대다수 파일은 아무것도 읽지 않고 0.0으로 끝난다."""
        try:
            # ntpath: Windows 경로를 Linux(CI)에서 받아도 파일명을 맞게 뽑는다(Windows 에선 동일).
            stem = os.path.splitext(ntpath.basename(filepath))[0]
            if not (DataIO.HOT_DEPLOY_STEM <= stem < DataIO.HOT_UTC_TOGGLE_STEM):
                return 0.0
            if ncols is None:
                # 헤더행(6177)은 핫·콜드가 같으므로 데이터행 폭으로 판별한다.
                if rows is not None:
                    ncols = max((len(r) for r in rows[:10]), default=0)
                else:
                    # 앞 10줄 탭만 센다 — 파일 통째 로드(1.7 s → 캐시 없는 워커에선
                    # 파일마다 반복)를 피한다. 캐시 판정과 같은 strip·split 규칙.
                    # 결과는 파일(경로·mtime·크기)별로 기억한다 — parse_row_timestamp 가 스캔마다
                    # 불러 같은 파일을 스캔 수만큼 열고 있었다(2026-10-01).
                    st = os.stat(filepath)
                    nkey = (os.path.abspath(filepath), st.st_mtime_ns, st.st_size)
                    ncols = DataIO._ncols_cache.get(nkey)
                    if ncols is None:
                        ncols = 0
                        with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                            seen = 0
                            for ln in fh:
                                s = ln.strip()
                                if not s:
                                    continue
                                ncols = max(ncols, len(s.split('\t')))
                                seen += 1
                                if seen >= 10:
                                    break
                        if len(DataIO._ncols_cache) > 4096:
                            DataIO._ncols_cache.clear()
                        DataIO._ncols_cache[nkey] = ncols
            if int(ncols) != DataIO.HOT_NCOLS:
                return 0.0
            return DataIO.HOT_PRE_TOGGLE_SHIFT_SEC
        except Exception:
            return 0.0

    @staticmethod
    def all_row_seconds(filepath):
        """파일 전 행의 연초기준 초 배열(벡터화). 60s 평균/시간축용. 실패 시 None.

        `clock_epoch_offset_sec`(핫 5/29 UTC-toggle)을 적용해 캠페인 전체가 **UTC
        한 축** 위에 오도록 한다 — 안 하면 5/29 경계에서 시간축이 8.5h 역행해
        I₀/R(t) PCHIP이 `x must be strictly increasing`으로 죽는다."""
        try:
            rows = DataIO._load_file_to_cache(filepath)
            import numpy as _np
            out = _np.full(len(rows), _np.nan)
            for i, r in enumerate(rows):
                if len(r) >= 2:
                    out[i] = DataIO._bytepack_year_seconds(r[0], r[1])
            off = DataIO.clock_epoch_offset_sec(filepath, rows=rows)
            if off:
                out += off
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
    # 파일을 못 펼치면 **예외를 올린다**. 예전에는 n=0으로 삼켜서 "행 0개짜리
    # 정상 파일"로 반환됐고, 호출부(gui/worker.py Pass1)는 이미 예외를 받아
    # "SKIP(parse) <파일>: <이유>"를 띄우도록 돼 있는데 그 경로가 죽어 있었다.
    # 행 단위 실패는 아래에서 flags[i]=RAW_LOAD_FAIL로 flag한다(지우지 않는다) —
    # 파일 단위 실패는 flag를 걸 자리조차 없으므로 조용히 넘어가면 안 된다.
    n = len(DataIO.expand_to_scan_list(path))
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

    # 로드 실패한 행은 위에서 조용히 건너뛰었다. 몇 개였는지는 말해야 한다 —
    # 안 그러면 "읽었는데 ZA/He 블록이 없다"와 "못 읽었다"가 같은 ([], [])로
    # 나가고, R 트렌드 로그에는 "ZA scans=0 (no flag=500 rows)"로 찍힌다.
    # 계기가 교정 블록을 안 넣은 것으로 오해하기 딱 좋은 메시지다.
    n_fail = int(np.count_nonzero(np.asarray(flags, dtype=np.int64) == RAW_LOAD_FAIL))
    if n_fail and n_fail == len(flags):
        raise RuntimeError(
            f"{os.path.basename(fp)}: all {n_fail} rows failed to load — the file could not "
            f"be read (not the same as 'no ZA/He blocks')")
    if n_fail:
        print(f"[data_io] {os.path.basename(fp)}: {n_fail}/{len(flags)} rows failed to load "
              f"(flag={RAW_LOAD_FAIL}) — continuing with the remaining rows", file=sys.stderr)
    return za, he


def scans_worker_for_parallel(task):
    """병렬 파싱 워커(모듈 최상위 — spawn 자식이 Qt 없이 임포트).
    task=(fp, channel, min_peak) → (fp, za, he). 순수함수.

    실패하면 `(fp, None, None)`. **([], [])와 구분되어야 한다** — 전자는
    "못 읽었다", 후자는 "읽었는데 ZA/He 블록이 없다"이고 운영자가 할 일이 다르다.
    예전에는 둘을 같은 값으로 뭉개서, 파싱이 깨진 파일이 R 트렌드 로그에
    "ZA scans=0 (no flag=500 rows)"로 찍혔다 — 계기가 교정 블록을 안 넣은 것으로
    오해하기 딱 좋다. 자식 프로세스라 예외를 올리면 배치 전체가 순차로 되돌아가
    같은 파일에서 다시 죽으므로, 값으로 신호한다."""
    fp, channel, min_peak = task
    try:
        za, he = read_scans_via_dataio(fp, channel, min_peak)
    except Exception as e:
        print(f"[data_io] raw parse failed {os.path.basename(fp)}: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return fp, None, None
    return fp, za, he
