# -*- coding: utf-8 -*-
"""Plot Maker — 데이터 모델/로더.

결과 파일 하나를 공통 테이블(Dataset)로 정규화. `gui/ui_plot_maker/__init__.py`가
Dataset·load_dataset을 재export하므로 외부는 여전히
`from gui.ui_plot_maker import Dataset, load_dataset`로 그대로 쓴다.
"""
from __future__ import annotations

import os

import numpy as np

from gui.result_viewer_io import detect, detect_sep, read_numeric, load_fit_table


class Dataset:
    """결과 파일 하나를 공통 테이블로 정규화한 메모리 표현.

    time  : epoch초 ndarray 또는 None(시간축 없음)
    cols  : {컬럼명: float ndarray}  (가스 ppb, RMS, 일반 수치 등)
    units : {컬럼명: 단위문자열}  (예: NO2→'ppb', RMS→'cm⁻¹'). 모르면 없음.
    errs  : {컬럼명: 1σ 오차 ndarray|None}  (fit 결과의 {gas}_Error). 에러밴드용.
    """
    __slots__ = ("name", "path", "time", "cols", "units", "errs")

    def __init__(self, name, path, time, cols, units=None, errs=None):
        self.name = name
        self.path = path
        self.time = time
        self.cols = cols
        self.units = units or {}
        self.errs = errs or {}

    def __len__(self):
        return max((len(v) for v in self.cols.values()), default=0)


def load_dataset(path) -> Dataset:
    """파일 종류를 자동 판별해 Dataset으로 읽는다(기존 뷰어 파서 재사용)."""
    name = os.path.splitext(os.path.basename(path))[0]
    kind = detect(path)

    # ① fit/리포트 → 가스 + RMS + (시각)
    if kind == "fit":
        t = load_fit_table(path)
        cols = {g: v for g, v in t["gases"].items()}
        units = {g: "ppb" for g in t["gases"]}     # CAESAR 가스 농도 = ppb
        if t.get("rms") is not None:
            cols["RMS"] = t["rms"]
            units["RMS"] = "cm⁻¹"
        return Dataset(name, path, t.get("time"), cols, units,
                       errs={g: e for g, e in (t.get("errs") or {}).items() if e is not None})

    # ② 일반 표(csv/tsv/농도) → pandas로 시간컬럼 + 수치컬럼
    try:
        import pandas as pd
        sep = detect_sep(path)
        df = pd.read_csv(path, sep=sep if sep else r"\s+",
                         comment="#", engine="python")
        df.columns = [str(c).strip() for c in df.columns]
        time, tcol = None, None
        for c in df.columns:
            if c.lower() in ("time", "datetime", "timestamp", "date"):
                dt = pd.to_datetime(df[c], errors="coerce")
                if dt.notna().mean() > 0.5:
                    # naive 시각을 로컬(머신 TZ)로 간주해 epoch화 — 야간음영(_night_spans)·
                    # _fit/.dat 경로(datetime.timestamp())와 통일한다. datetime64.astype(int64)는
                    # naive를 UTC로 간주해 KST 머신에서 9h 어긋났음(음영 누락·diurnal/시각축 +9h 밀림).
                    tt = np.array([t_.timestamp() if pd.notna(t_) else np.nan
                                   for t_ in dt.dt.to_pydatetime()], dtype=float)
                    time, tcol = tt, c
                    break
        cols = {}
        for c in df.columns:
            if c == tcol:
                continue
            y = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
            if np.isfinite(y).any():
                cols[c] = y
        if cols:
            return Dataset(name, path, time, cols)
    except Exception:
        pass

    # ③ 마지막 폴백: 순수 숫자배열
    d = read_numeric(path)
    cols = {f"col{j}": d[:, j] for j in range(d.shape[1])}
    return Dataset(name, path, None, cols)
