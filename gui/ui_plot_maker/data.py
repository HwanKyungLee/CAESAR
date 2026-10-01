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
    derived  : 파생 열 list[{"name","expr","unit"}] — **식을 저장**하고 값은 `apply_derived`가
               cols에 채운다(캐시). 목록 순서대로 평가하므로 앞의 파생 열을 뒤에서 쓸 수 있다.
    derived_errors : {이름: 오류문} — 깨진 식은 조용히 빼지 않고 여기 남겨 트리에 빨갛게 보인다.
    """
    __slots__ = ("name", "path", "time", "cols", "units", "errs", "cats",
                 "rules", "rules_on", "shift_h", "_hidden", "derived", "derived_errors", "_dcols")

    # 식에서 열 이름 대신 쓸 수 있는 예약 변수 — 파생 열 이름으로 못 쓴다.
    RESERVED = ("time", "hour")

    def __init__(self, name, path, time, cols, units=None, errs=None, cats=None,
                 rules=None, rules_on=True, shift_h=0.0, derived=None):
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
        self.derived = [dict(d) for d in (derived or [])]
        self.derived_errors = {}
        self._dcols = ()     # 마지막으로 cols에 채운 파생 열 이름 — 지우거나 이름을 바꾸면 옛 값을 걷어낸다
        if self.derived:
            self.apply_derived()

    def __len__(self):
        return max((len(v) for v in self.cols.values()), default=0)

    # ── 파생 열 (D1) ────────────────────────────────────────────────────
    def derived_names(self):
        return [d["name"] for d in self.derived]

    def n_rows(self):
        """원본 열 기준 행 수(파생 열은 같은 길이로 만들어진다)."""
        dn = set(self._dcols)
        return max((len(v) for k, v in self.cols.items() if k not in dn), default=0)

    def variables(self, upto=None):
        """식에 넘길 변수 — 숫자 열·범주형 열·time·hour.
        upto=i면 파생 열은 i번째 **앞**까지만(편집 중인 열이 자기·뒤 열을 못 보게)."""
        hide = set(self.derived_names()[upto:]) if upto is not None else set()
        v = {k: a for k, a in self.cols.items() if k not in hide}
        for k, a in self.cats.items():
            v.setdefault(k, a)
        if self.time is not None:
            v["time"] = self.time
            v["hour"] = local_hour(self.time, self.shift_h)
        return v

    def check_derived_name(self, name, editing=None):
        """새 파생 열 이름 검사 — 문제 있으면 오류문, 없으면 None."""
        name = (name or "").strip()
        if not name:
            return "Name is empty"
        if ":" in name:
            return "Name can't contain ':' (it separates dataset and column)"
        if name in self.RESERVED:
            return f"'{name}' is reserved in expressions"
        if name == editing:
            return None
        if name in self.cols or name in self.cats or name in self.derived_errors:
            return f"'{name}' already exists in this dataset"
        return None

    def apply_derived(self):
        """파생 열을 식에서 다시 계산한다(파일을 다시 읽었거나 식·시프트가 바뀌었을 때).
        깨진 식은 그 열만 빠지고 오류가 `derived_errors`에 남는다 — 다른 열은 산다."""
        from core.expr import eval_column
        # 걷어내는 건 **내가 채웠던** 열뿐 — 원본 열은 어떤 경우에도 건드리지 않는다
        for nm in self._dcols:
            self.cols.pop(nm, None)
            self.units.pop(nm, None)
        base = set(self.cols) | set(self.cats)
        self.derived_errors = {}
        n = self.n_rows()
        for d in self.derived:
            nm = d["name"]
            if nm in base:              # 손으로 고친 설정 등 — 원본을 덮어쓰지 않는다
                self.derived_errors[nm] = f"'{nm}' clashes with an original column — rename it"
                continue
            try:
                self.cols[nm] = eval_column(d["expr"], self.variables(), n)
                if d.get("unit"):
                    self.units[nm] = d["unit"]
            except Exception as e:      # ExprError + 데이터 의존 오류(길이 불일치 등)
                self.derived_errors[nm] = str(e)
        self._dcols = tuple(nm for nm in self.derived_names()
                            if nm in self.cols and nm not in base)
        self._hidden = None

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
                "rules_on": self.rules_on, "shift_h": self.shift_h,
                "derived": [dict(d) for d in self.derived]}


def local_hour(t, shift_h=0.0):
    """epoch초 → 로컬 시각의 시(0~24, 소수). 머신 TZ 오프셋 하나를 쓴다 — 한국은 DST가
    없어 충분하다(DST 지역이면 전환일 앞뒤 1시간 어긋남). 데이터셋 시프트를 더한다."""
    import time as _time
    t = np.asarray(t, float)
    fin = t[np.isfinite(t)]
    off = _time.localtime(float(np.median(fin))).tm_gmtoff if fin.size else 0
    with np.errstate(invalid="ignore"):
        return np.mod((t + off + shift_h * 3600.0) / 3600.0, 24.0)


def load_spec(spec) -> Dataset:
    """레시피(경로 문자열 또는 {"path","rules","rules_on","shift_h","derived"}) → Dataset.
    파일은 항상 다시 읽고 규칙·파생 식을 다시 건다 — 값은 캐시일 뿐이다."""
    if isinstance(spec, str):
        spec = {"path": spec}
    ds = load_dataset(spec["path"])
    ds.set_rules(spec.get("rules") or [], spec.get("rules_on", True))
    ds.shift_h = float(spec.get("shift_h") or 0.0)
    ds.derived = [dict(d) for d in (spec.get("derived") or [])]
    if ds.derived:
        ds.apply_derived()
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
