# -*- coding: utf-8 -*-
"""Plot Maker — 데이터 모델/로더.

결과 파일 하나를 공통 테이블(Dataset)로 정규화. `gui/ui_plot_maker/__init__.py`가
Dataset·load_dataset을 재export하므로 외부는 여전히
`from gui.ui_plot_maker import Dataset, load_dataset`로 그대로 쓴다.
"""
from __future__ import annotations

import os

import numpy as np

from gui.result_viewer_io import (detect, detect_sep, read_numeric, load_fit_table,
                                  flag_of, rules_hidden_mask)


class Dataset:
    """결과 파일 하나를 공통 테이블로 정규화한 메모리 표현.

    time  : epoch초 ndarray 또는 None(시간축 없음)
    cols  : {컬럼명: float ndarray}  (가스 ppb, RMS, 일반 수치 등)
    units : {컬럼명: 단위문자열}  (예: NO2→'ppb', RMS→'cm⁻¹'). 모르면 없음.
    errs  : {컬럼명: 1σ 오차 ndarray|None}  (fit 결과의 {gas}_Error). 에러밴드용.
    cats  : {컬럼명: str ndarray}  범주형 열(fit이면 Status·Channel·Flag). 숫자 열과
            분리해 둔다 — 모드들은 cols만 보므로 그리기 경로에 섞이지 않는다.

    보기 상태 — **값이 아니라 레시피**(경로를 다시 읽고 재적용 가능, 원칙 ④):
    rules    : 숨김 규칙 list[dict] (`result_viewer_io.rules_hidden_mask`)
    rules_on : False면 규칙을 잠시 끈다(숨김≠삭제, 헌장 ①)
    shift_h  : 이 데이터셋만의 표시 시각 보정(전역 시프트에 더해짐). 원본 time은 불변.
    """
    __slots__ = ("name", "path", "time", "cols", "units", "errs", "cats",
                 "rules", "rules_on", "shift_h", "_hidden")

    def __init__(self, name, path, time, cols, units=None, errs=None, cats=None,
                 rules=None, rules_on=True, shift_h=0.0):
        self.name = name
        self.path = path
        self.time = time
        self.cols = cols
        self.units = units or {}
        self.errs = errs or {}
        self.cats = cats or {}
        self.rules = list(rules or [])
        self.rules_on = bool(rules_on)
        self.shift_h = float(shift_h or 0.0)
        self._hidden = None

    def __len__(self):
        return max((len(v) for v in self.cols.values()), default=0)

    def set_rules(self, rules=None, rules_on=None):
        """규칙 교체/켜고 끄기 — 캐시된 마스크를 버린다."""
        if rules is not None:
            self.rules = list(rules)
        if rules_on is not None:
            self.rules_on = bool(rules_on)
        self._hidden = None

    def hidden_mask(self):
        """숨길 행(True). 규칙이 없거나 꺼져 있으면 None(= 아무것도 안 숨김)."""
        if not (self.rules and self.rules_on):
            return None
        if self._hidden is None:
            st = self.cats.get("Status")
            ch = self.cats.get("Channel")
            self._hidden = rules_hidden_mask(
                self.rules, len(self), time=self.time,
                status=list(st) if st is not None else None,
                rms=self.cols.get("RMS"),
                channel=list(ch) if ch is not None else None)
        return self._hidden

    def n_hidden(self):
        m = self.hidden_mask()
        return int(m.sum()) if m is not None else 0

    def to_spec(self):
        """설정 파일용 레시피 — 열 때 `load_spec`으로 그대로 되살린다."""
        return {"path": self.path, "rules": [dict(r) for r in self.rules],
                "rules_on": self.rules_on, "shift_h": self.shift_h}


def load_spec(spec) -> Dataset:
    """레시피(경로 문자열 또는 {"path","rules","rules_on","shift_h"}) → Dataset.
    파일은 항상 다시 읽고 규칙을 다시 건다 — 값은 캐시일 뿐이다."""
    if isinstance(spec, str):
        spec = {"path": spec}
    ds = load_dataset(spec["path"])
    ds.set_rules(spec.get("rules") or [], spec.get("rules_on", True))
    ds.shift_h = float(spec.get("shift_h") or 0.0)
    ds.hidden_mask()          # 규칙이 이 파일에 맞지 않으면(모르는 kind 등) 지금 터뜨린다
    return ds


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
        # 진단용 숫자 열 — 예전엔 버렸다. 전부 NaN인 열(리포트 포맷의 T/P)은 싣지 않는다.
        for key, col, unit in (("T", "T", "°C"), ("P", "P", "mbar"),
                               ("shift", "Shift", "px"), ("squeeze", "Squeeze", None)):
            v = t.get(key)
            if v is not None and col not in cols and np.isfinite(np.asarray(v, float)).any():
                cols[col] = np.asarray(v, float)
                if unit:
                    units[col] = unit
        # 범주형 열 — Result Lab의 flag가 그림까지 이어지게(헌장 ①).
        cats = {}
        if t.get("status") is not None:
            st = np.asarray(t["status"], dtype=object)
            cats["Status"] = st
            cats["Flag"] = np.asarray([flag_of(s) for s in st], dtype=object)
        if t.get("channel") is not None:
            cats["Channel"] = np.asarray(t["channel"], dtype=object)
        return Dataset(name, path, t.get("time"), cols, units,
                       errs={g: e for g, e in (t.get("errs") or {}).items() if e is not None},
                       cats=cats)

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
