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
    if "wavelength" in head and "reflect" in head:
        return "reference"
    if any(k in head for k in ("datetime", "timestamp", "doy", "no2", "hcho",
                               "ppb", "ppt", "concentration", "conc")):
        return "concentration"
    return "array"


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


def load_fit_table(path):
    """fit 표 파싱 — 3가지 포맷 지원.
    ① 구 alpha-fit: row_idx T_C P_mbar <gases> rms_cm-1
    ② 신 alpha-fit: row_idx doy datetime T_C P_mbar <gases> rms_cm-1
    ③ GUI 분석 리포트: File [Ch] Time RMS … Status <gas blocks> Shift Squeeze
    반환: {'row_idx','T','P','rms','doy','time'(epoch초),'gases':{name:ndarray},
           'errs':{name:ndarray|None},'status':list|None,'path'}."""
    import datetime as _dt
    hdr, rows = None, []
    is_report = False
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            s = ln.rstrip("\n")
            if not s.strip() or s.startswith("#"):
                continue
            if hdr is None and s.lower().startswith("row_idx"):
                hdr = s.split("\t")
                continue
            if hdr is None and s.startswith("File\t"):
                hdr = s.split("\t")
                is_report = True
                continue
            if hdr is None:
                continue
            rows.append(s.split("\t"))
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

        def colf_r(j):
            out = np.full(len(rows), np.nan)
            for k, r in enumerate(rows):
                if j is not None and j < len(r):
                    try:
                        out[k] = float(r[j])
                    except ValueError:
                        pass
            return out

        ts = np.full(len(rows), np.nan)
        ti = idx.get("Time")
        for k, r in enumerate(rows):
            if ti is not None and ti < len(r) and r[ti].strip():
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                    try:
                        ts[k] = _dt.datetime.strptime(r[ti].strip()[:26], fmt).timestamp()
                        break
                    except ValueError:
                        pass
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
               "status": status, "channel": channel, "path": path}
        return out
    idx = {n: i for i, n in enumerate(hdr)}
    rms_i = idx.get("rms_cm-1", len(hdr) - 1)
    p_i = idx.get("P_mbar", 2)
    gas_cols = list(range(p_i + 1, rms_i))   # P_mbar 다음 ~ rms 직전 = 가스들

    def colf(j):
        out = np.full(len(rows), np.nan)
        for k, r in enumerate(rows):
            if j is not None and j < len(r):
                try:
                    out[k] = float(r[j])
                except ValueError:
                    pass
        return out

    out = {"row_idx": colf(idx.get("row_idx", 0)), "T": colf(idx.get("T_C")),
           "P": colf(p_i), "rms": colf(rms_i), "doy": colf(idx.get("doy")),
           "time": None, "gases": {}, "errs": {}, "status": None,
           "channel": None, "path": path}
    for j in gas_cols:
        out["gases"][hdr[j]] = colf(j)

    # datetime 컬럼 → epoch 초(시간축용)
    di = idx.get("datetime")
    if di is not None:
        ts = np.full(len(rows), np.nan)
        for k, r in enumerate(rows):
            if di < len(r) and r[di].strip():
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                    try:
                        ts[k] = _dt.datetime.strptime(r[di].strip(), fmt).timestamp()
                        break
                    except ValueError:
                        pass
        if np.isfinite(ts).any():
            out["time"] = ts
    return out

