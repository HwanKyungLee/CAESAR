"""gui/result_viewer_io.py
결과 뷰어용 순수 파서 함수 (ui_result_viewer.py에서 분리).
self·Qt 비의존 — 파일 포맷 판별/숫자표 읽기/fit표 파싱. 위젯은 staticmethod로 재바인딩.
"""
import os
import numpy as np


def load_result_time_gas(path, gas='NO2'):
    """결과파일(_fit/_CH*.dat 등)에서 (시각 epoch[], gas 농도[])를 정렬해 반환."""
    import pandas as pd
    from datetime import datetime
    df = pd.read_csv(path, sep=None, engine='python', comment='#')
    df.columns = [str(c).strip() for c in df.columns]
    gcol = next((c for c in df.columns if c.lower() == gas.lower()), None)
    tcol = next((c for c in df.columns if c.lower() == 'time'), None)
    if gcol is None:
        raise RuntimeError(f"{os.path.basename(path)}: '{gas}' column not found (columns: {list(df.columns)[:8]})")
    gv = pd.to_numeric(df[gcol], errors='coerce').to_numpy(dtype=float)
    if tcol is None:
        t = np.arange(len(gv), dtype=float)
    else:
        t = np.full(len(gv), np.nan)
        for i, s in enumerate(df[tcol].astype(str)):
            for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
                try:
                    t[i] = datetime.strptime(s, fmt).timestamp(); break
                except ValueError:
                    pass
    m = np.isfinite(t) & np.isfinite(gv)
    t, gv = t[m], gv[m]
    o = np.argsort(t)
    return t[o], gv[o]


def detect(path: str) -> str:
    name = os.path.basename(path).lower()
    lines = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for _ in range(40):
                ln = f.readline()
                if not ln:
                    break
                lines.append(ln)
    except OSError:
        return "array"
    head = "".join(lines).lower()

    if "timestamp" in head and "r_mean" in head:
        return "r_trend"
    if "wavelength_nm" in head and ("r_fitted" in head or "r_raw" in head):
        return "r_curve"
    if name.endswith("_r.dat"):
        return "r_curve"
    if "_alpha_trace" in name or "alpha export" in head:
        return "alpha_trace"
    # fit 결과: 헤더 row_idx … rms_cm-1 (가스별 ppb 컬럼)
    if name.endswith("_fit.tsv") or ("row_idx" in head and "rms_cm" in head):
        return "fit"
    # GUI 분석 리포트(File/Time/RMS/…/Chi2/DOF/SNR/Status) — fit으로 취급해
    # 가스선택·QC필터·통계·구간내보내기 등 fit 기능을 전부 사용 가능하게.
    if "file\t" in head and "\tstatus" in head and "\tchi2" in head:
        return "fit"
    if name.endswith(".tsv") or "rms_cm" in head:
        return "concentration"
    # 데이터 계산기 출력(ANs/PNs 등 임의 이름) — gui/dlg_calculator.py가 쓰는
    # "# Data Calculator result: ..." 시그니처로 가스명과 무관하게 인식.
    if "data calculator result" in head:
        return "concentration"
    if "wavelength" in head and "reflect" in head:
        return "reference"
    if any(k in head for k in ("datetime", "timestamp", "doy", "no2", "hcho",
                               "ppb", "ppt", "concentration", "conc")):
        return "concentration"
    return "array"


def parse_file_cell(s):
    """Fit-report File cell `"x_alpha_trace.dat [0016]"` → ("x_alpha_trace.dat", 16), else None.
    The number is the data-row *position* in that source (worker: expand_to_scan_list)."""
    import re
    m = re.match(r"^(.*?)\s*\[(\d+)\]\s*$", str(s or ""))
    return (m.group(1), int(m.group(2))) if m and m.group(1) else None


def read_numeric(path, sep=None):
    return np.loadtxt(path, comments="#", delimiter=sep, ndmin=2)


def detect_sep(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            if "\t" in s:
                return "\t"
            if "," in s:
                return ","
            return None   # whitespace
    return None


def read_alpha_trace(path, want_id=None):
    """alpha_trace.dat 공통 파서 (뷰어의 α평균 플롯과 포인트클릭 α팝업이 공유).

    헤더 규약: '# wavelength_nm:'(있으면 파장축), 'row_idx …' 헤더의 'px*' 컬럼
    위치로 α 시작열(alpha_start) 자동 탐지(기본 3). '#' 줄은 건너뜀.

    want_id=None : (wave, ids, alpha2d) — 전체 데이터 행.
        wave: 파장 ndarray(없거나 길이 불일치면 픽셀 인덱스).
        ids : 각 행의 row_idx(첫 컬럼) float ndarray.
        alpha2d: (행, 파장) ndarray. 데이터 없으면 (0,0).
    want_id=정수 : (wave, alpha1d) — 그 row_idx 행만 찾아 '조기종료'(대용량 파일에서
        클릭마다 전체를 읽지 않게). 못 찾으면 (wave, None).
    """
    wave = None
    alpha_start = 3
    ids, rows = [], []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            if ln.startswith("# wavelength_nm:"):
                try:
                    wave = np.array([float(v) for v in ln.split(":", 1)[1].strip().split("\t")
                                     if v.strip()], dtype=float)
                except Exception:
                    pass
                continue
            if ln.lower().startswith("row_idx"):
                cols = ln.rstrip("\n").split("\t")
                fp = next((i for i, c in enumerate(cols) if c.startswith("px")), None)
                if fp is not None:
                    alpha_start = fp
                continue
            if ln.startswith("#"):
                continue
            p = ln.rstrip().split("\t")
            if len(p) <= alpha_start:
                continue
            if want_id is not None:
                try:
                    if int(float(p[0])) != want_id:
                        continue
                    vals = np.array([float(x) for x in p[alpha_start:]], dtype=float)
                except ValueError:
                    continue
                w = wave if (wave is not None and len(wave) == len(vals)) \
                    else np.arange(len(vals), dtype=float)
                return w, vals
            try:
                vals = [float(x) for x in p[alpha_start:]]
            except ValueError:
                continue
            try:
                rid = int(float(p[0]))
            except ValueError:
                rid = len(ids)
            ids.append(rid)
            rows.append(vals)
    if want_id is not None:
        return wave, None
    if not rows:
        return wave, np.array([], dtype=float), np.empty((0, 0), dtype=float)
    a = np.array(rows, dtype=float)
    if wave is None or len(wave) != a.shape[1]:
        wave = np.arange(a.shape[1], dtype=float)
    return wave, np.array(ids, dtype=float), a


class _Grid:
    """행 목록(list[list[str]])을 열 단위로 꺼내는 그릇 — `zip_longest`로 C 수준에서 한 번에 전치한다
    (짧은 행은 빈 칸 "" = 예전 `r[j] if j < len(r) else ""`와 같은 뜻). 열마다 리스트를 다시 만들던 것이
    26만 행에서 ~1 s였다. 열은 처음 꺼낼 때 object 배열로 바꿔 둔다."""

    def __init__(self, rows, width):
        from itertools import zip_longest
        self.n = len(rows)
        self.width = width
        self._t = list(zip_longest(*rows, fillvalue="")) if rows else []
        self._cache = {}

    def col(self, j):
        if j is None or j >= self.width or j >= len(self._t):
            return np.full(self.n, "", dtype=object)
        a = self._cache.get(j)
        if a is None:
            a = self._cache[j] = np.array(self._t[j], dtype=object)
        return a


def _col_float(grid, j):
    """j번째 칸 → float 배열(없거나 못 읽으면 NaN). object 배열의 astype(float)은 원소마다 파이썬
    float()을 C 루프에서 부른다 — 칸마다 float()과 **결과가 같고** 훨씬 빠르다. 한 칸이라도 못 읽는
    열만 예전처럼 칸마다 시도한다."""
    if j is None:
        return np.full(grid.n, np.nan)
    vals = grid.col(j)
    try:
        return vals.astype(float)
    except (ValueError, TypeError):
        out = np.full(grid.n, np.nan)
        for k, v in enumerate(vals):
            try:
                out[k] = float(v)
            except ValueError:
                pass
        return out


def _local_offsets(naive_s):
    """naive 로컬 시각(1970 기준 초, 정수) → 그 시각의 `datetime.timestamp() - naive` 오프셋(초).
    시(hour) 단위로 한 번씩만 계산한다. 한 시간 안에서 오프셋이 바뀌는 시간(DST 전환 등)은 NaN —
    호출측이 그 행만 행별 경로로 처리한다."""
    import datetime as _dt
    base = _dt.datetime(1970, 1, 1)
    hours = naive_s // 3600
    uh, inv = np.unique(hours, return_inverse=True)
    off = np.empty(len(uh))
    for i, h in enumerate(uh):
        h = int(h)
        a = (base + _dt.timedelta(seconds=h * 3600)).timestamp() - h * 3600
        b = (base + _dt.timedelta(seconds=h * 3600 + 3599)).timestamp() - (h * 3600 + 3599)
        off[i] = a if a == b else np.nan
    return off[inv]


def _col_time(grid, j, cut=True):
    """j번째 칸 → epoch초 배열(못 읽으면 NaN). 시각 의미의 단일 출처는 core.result_io.parse_row_time.
    빠른 길: `YYYY-mm-dd HH:MM:SS` 형식에 맞는 값은 pandas로 한꺼번에 읽고 로컬 오프셋을 시 단위로
    더한다. 나머지(분수 초·이상한 모양·DST 전환 시간)는 예전처럼 parse_row_time 행별 경로 —
    결과는 같다(tools/test_fit_table_fast.py가 행별 구현과 대조).
    cut=False면 26자를 넘는 문자열은 읽지 않는다(옛 alpha-fit 경로가 잘라 읽지 않았던 규칙 유지)."""
    from core.result_io import parse_row_time
    ts = np.full(grid.n, np.nan)
    if j is None or grid.n == 0:
        return ts
    import pandas as pd
    s = pd.Series(grid.col(j), dtype=object).str.strip()
    ln = s.str.len().to_numpy()
    keep = ln > 0 if cut else (ln > 0) & (ln <= 26)
    s26 = s.str.slice(0, 26)
    dt = pd.to_datetime(s26.where(keep, None), format="%Y-%m-%d %H:%M:%S", errors="coerce")
    ok = dt.notna().to_numpy() & keep
    if ok.any():
        naive = dt[ok].to_numpy(dtype="datetime64[s]").astype(np.int64)
        off = _local_offsets(naive)
        good = np.isfinite(off)
        idx = np.flatnonzero(ok)
        ts[idx[good]] = naive[good] + off[good]
        ok[idx[~good]] = False          # DST 전환 시간 → 아래 행별 경로
    sv = s.to_numpy()
    for k in np.flatnonzero(keep & ~ok):
        d = parse_row_time(sv[k])
        if d is not None:
            ts[k] = d.timestamp()
    return ts


_FIT_CACHE = {}          # (절대경로, mtime_ns, 크기) → 파싱 결과 — 최근 몇 개만(LRU)
_FIT_CACHE_MAX = 3


def _copy_table(t):
    """캐시된 결과를 넘길 때 배열·리스트를 복사 — 호출측이 고쳐 써도 캐시가 오염되지 않게."""
    out = {}
    for k, v in t.items():
        if isinstance(v, np.ndarray):
            out[k] = v.copy()
        elif isinstance(v, dict):
            out[k] = {g: (a.copy() if isinstance(a, np.ndarray) else a) for g, a in v.items()}
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out


def load_fit_table(path):
    """fit 표 파싱(캐시됨). 같은 파일(경로·수정시각·크기)을 다시 열면 다시 읽지 않는다 — Result Lab에서
    연 파일을 Plot Maker로 보내거나 Dates로 같은 기간을 다시 열 때 26만 행 ~3 s가 반복됐다
    (2026-10-02). 파일이 바뀌면 키가 달라져 다시 읽는다. 돌려주는 건 복사본."""
    try:
        st = os.stat(path)
        key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key is not None and key in _FIT_CACHE:
        t = _FIT_CACHE.pop(key)
        _FIT_CACHE[key] = t                      # 최근 사용으로(dict 순서 = LRU)
        out = _copy_table(t)
        out["path"] = path                       # 같은 파일을 다른 경로 문자열로 연 경우
        return out
    t = _load_fit_table_uncached(path)
    if key is not None:
        _FIT_CACHE[key] = t
        while len(_FIT_CACHE) > _FIT_CACHE_MAX:
            _FIT_CACHE.pop(next(iter(_FIT_CACHE)))
    return _copy_table(t)


def _load_fit_table_uncached(path):
    """fit 표 파싱 — 3가지 포맷 지원.
    ① 구 alpha-fit: row_idx T_C P_mbar <gases> rms_cm-1
    ② 신 alpha-fit: row_idx doy datetime T_C P_mbar <gases> rms_cm-1
    ③ GUI 분석 리포트: File [Ch] Time RMS … Status <gas blocks> Shift Squeeze
    반환: {'row_idx','T','P','rms','doy','time'(epoch초),'gases':{name:ndarray},
           'errs':{name:ndarray|None},'status':list|None,'path'}."""
    hdr, rows = None, []
    is_report = False
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")
    # 헤더 찾기(예전 한 줄씩 규칙 그대로) → 그 뒤 데이터 줄은 한 번에 거른다(줄마다 파이썬 분기가
    # 26만 행에서 ~1 s였다). 거르는 규칙도 같다: 빈 줄·공백뿐인 줄·'#' 주석 줄은 건너뛴다.
    h = None
    for i, s in enumerate(lines):
        if not s.strip() or s.startswith("#"):
            continue
        if s.lower().startswith("row_idx"):
            hdr, h = s.split("\t"), i
            break
        if s.startswith("File\t"):
            hdr, h, is_report = s.split("\t"), i, True
            break
    if hdr is not None:
        rows = [s.split("\t") for s in lines[h + 1:]
                if s and s[0] != "#" and not s.isspace()]
    if hdr is None or not rows:
        raise ValueError("No fit-result header/data rows found")

    if is_report:
        # ── GUI 리포트 포맷 ───────────────────────────────────────
        idx = {n: i for i, n in enumerate(hdr)}
        # 주 가스 컬럼: <gas>_Error 가 있는 베이스 컬럼(QC-ON/OFF 무관, 항상 존재).
        # 과거엔 _Smooth로 탐지했으나 QC/Kalman OFF 파일엔 _Smooth가 없어 가스가
        # 하나도 안 잡히던 버그가 있었음. _Error 우선, 없으면 _Smooth로 폴백.
        gases = [c for c in hdr if (c + "_Error") in idx]
        if not gases:
            gases = [c for c in hdr if (c + "_Smooth") in idx]   # 구 포맷 호환

        grid = _Grid(rows, len(hdr))

        def colf_r(j):
            return _col_float(grid, j)

        ts = _col_time(grid, idx.get("Time"))
        si = idx.get("Status")
        status = [r[si] if (si is not None and si < len(r)) else "" for r in rows]
        chi = idx.get("Channel")
        channel = ([r[chi] if (chi is not None and chi < len(r)) else "1" for r in rows]
                   if chi is not None else None)
        out = {"row_idx": np.arange(len(rows), dtype=float),
               "T": np.full(len(rows), np.nan), "P": np.full(len(rows), np.nan),
               "rms": colf_r(idx.get("RMS")), "doy": np.full(len(rows), np.nan),
               "time": ts if np.isfinite(ts).any() else None,
               "gases": {g: colf_r(idx[g]) for g in gases},
               "errs": {g: (colf_r(idx[g + "_Error"]) if (g + "_Error") in idx else None)
                        for g in gases},
               "status": status, "channel": channel, "path": path,
               # File cell "<source> [NNNN]" = source file + data-row position the worker fit
               # (scan detail needs it; row_idx here is just the row number in this table).
               "file": ([r[idx["File"]] if idx["File"] < len(r) else "" for r in rows]
                        if "File" in idx else None),
               # B2: shift/squeeze 레인용. 전역 컬럼(Shift/Squeeze)이 있으면 그걸,
               # 없으면 첫 가스의 것으로 폴백(구 포맷). 없으면 None.
               "shift": (colf_r(idx["Shift"]) if "Shift" in idx else
                         (colf_r(idx[gases[0] + "_Shift"])
                          if gases and (gases[0] + "_Shift") in idx else None)),
               "squeeze": (colf_r(idx["Squeeze"]) if "Squeeze" in idx else
                           (colf_r(idx[gases[0] + "_Squeeze"])
                            if gases and (gases[0] + "_Squeeze") in idx else None))}
        return out
    idx = {n: i for i, n in enumerate(hdr)}
    rms_i = idx.get("rms_cm-1", len(hdr) - 1)
    p_i = idx.get("P_mbar", 2)
    gas_cols = list(range(p_i + 1, rms_i))   # P_mbar 다음 ~ rms 직전 = 가스들

    grid = _Grid(rows, len(hdr))

    def colf(j):
        return _col_float(grid, j)

    out = {"row_idx": colf(idx.get("row_idx", 0)), "T": colf(idx.get("T_C")),
           "P": colf(p_i), "rms": colf(rms_i), "doy": colf(idx.get("doy")),
           "time": None, "gases": {}, "errs": {}, "status": None,
           "channel": None, "path": path, "shift": None, "squeeze": None}
    for j in gas_cols:
        out["gases"][hdr[j]] = colf(j)

    # datetime 컬럼 → epoch 초(시간축용)
    di = idx.get("datetime")
    if di is not None:
        ts = _col_time(grid, di, cut=False)
        if np.isfinite(ts).any():
            out["time"] = ts
    return out


# ── 행 flag · 숨김 규칙 — Result Lab과 Plot Maker가 같이 쓰는 단일 출처 ──────────
# 숨김은 삭제가 아니다(헌장 ①): 여기 함수들은 마스크만 만들고 값은 건드리지 않는다.
# RMS 임계식 자체는 core.result_io.robust_rms_thresholds 한 곳에만 있다.

def flag_of(status):
    """Status 문자열 → flag 키(ok/qc/unstable/settling/cal). 자유형식이라 부분일치로 본다."""
    s = (status or "").strip().lower()
    if not s:
        return "ok"
    if s.startswith("qc"):
        return "qc"
    if "unstable" in s:
        return "unstable"
    if "settl" in s:
        return "settling"
    if "zero-air" in s or "helium" in s or s.startswith("skip"):
        return "cal"
    return "ok"


def qc_hidden_mask(n, status=None, rms=None, channel=None, hide_status_qc=False, K=0.0):
    """숨길 행 마스크(True) — 두 기준의 OR:
      (1) hide_status_qc 이면 Status가 QC-* 인 행
      (2) K>0이면 RMS 분포에서 채널별 robust 임계 초과 행 (사후 QC)."""
    mask = np.zeros(n, bool)
    if hide_status_qc and status is not None and len(status):
        mask |= np.array([str(s).startswith("QC") for s in status], bool)[:n]
    if K > 0 and rms is not None:
        from core.result_io import robust_rms_thresholds
        rms = np.asarray(rms, float)
        chans = [channel[i] if (channel is not None and i < len(channel)) else 0
                 for i in range(n)]
        thr = robust_rms_thresholds(rms, chans, K=K, min_n=5)
        for i in range(n):
            ti = thr.get(chans[i], np.inf)
            if np.isfinite(rms[i]) and rms[i] > ti:
                mask[i] = True
    return mask


def rules_hidden_mask(rules, n, time=None, status=None, rms=None, channel=None,
                      variables=None):
    """보기 규칙(list[dict]) → 숨길 행 마스크. 규칙은 재계산 가능한 레시피라
    설정 파일에 그대로 저장되고 열 때 다시 적용된다(원칙 ④).

      {"kind": "status_qc"}            Status QC-* 행
      {"kind": "rms_k", "K": 3.0}      채널별 robust RMS 임계 초과 행
      {"kind": "time_range", "t0", "t1"}  [t0, t1](원본 epoch초) 밖 + 시각 없는 행
      {"kind": "expr", "expr": "T > 290", "mode": "keep"|"hide"}
                                       조건식(core/expr.py). keep = 조건이 **참인 행만** 남김
                                       (NaN 비교는 거짓 → 숨김), hide = 참인 행을 숨김.
                                       variables(열 이름 → 배열)가 필요하다.
    모든 규칙은 "on": False 로 개별로 끌 수 있다(지우지 않고).

    모르는 kind는 ValueError — 조용히 무시하면 사용자는 걸렀다고 믿는다.
    식 오류는 core.expr.ExprError(ValueError 하위)로 그대로 올린다."""
    mask = np.zeros(n, bool)
    for r in rules or ():
        if not r.get("on", True):
            continue
        k = r.get("kind")
        if k == "expr":
            from core.expr import eval_mask
            cond = eval_mask(r.get("expr", ""), variables or {}, n)
            mask |= ~cond if r.get("mode", "keep") == "keep" else cond
        elif k == "status_qc":
            mask |= qc_hidden_mask(n, status=status, hide_status_qc=True)
        elif k == "rms_k":
            mask |= qc_hidden_mask(n, rms=rms, channel=channel, K=float(r.get("K", 0.0)))
        elif k == "time_range":
            if time is None:
                continue          # 시각축 없는 데이터셋엔 구간 규칙이 의미 없다
            t = np.asarray(time, float)
            ok = np.isfinite(t) & (t >= float(r["t0"])) & (t <= float(r["t1"]))
            mask |= ~ok
        else:
            raise ValueError(f"unknown view rule kind: {k!r}")
    return mask


def describe_rule(r):
    """규칙 한 줄 설명(툴팁·상태줄용)."""
    import datetime as _dt
    k = r.get("kind")
    off = "" if r.get("on", True) else "  (off)"
    if k == "expr":
        verb = "Keep rows where" if r.get("mode", "keep") == "keep" else "Hide rows where"
        return f"{verb} {r.get('expr', '')}{off}"
    if k == "status_qc":
        return "Hide Status QC-*" + off
    if k == "rms_k":
        return f"Post-hoc QC: RMS > robust K={float(r.get('K', 0)):g} (per channel){off}"
    if k == "time_range":
        f = lambda e: _dt.datetime.fromtimestamp(float(e)).strftime("%Y-%m-%d %H:%M")
        return f"Time range {f(r['t0'])} ~ {f(r['t1'])}{off}"
    return str(r)


# flag 키 → 의미 역할 색(gui/theme). Result Lab 점 색과 Plot Maker 'Color by Flag'가 같은 색.
_FLAG_ROLE = {"unstable": "fail", "settling": "faint", "qc": "warn", "cal": "special"}
FLAG_KEYS = ("ok", "unstable", "settling", "qc", "cal")


def flag_color(key):
    """flag 키의 색(hex). ok는 None = 시리즈 고유색 그대로."""
    from gui.theme import AUGUR
    role = _FLAG_ROLE.get(key)
    return getattr(AUGUR, role) if role else None

