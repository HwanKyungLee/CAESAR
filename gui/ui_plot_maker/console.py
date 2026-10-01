# -*- coding: utf-8 -*-
"""Plot Maker — 내장 파이썬 콘솔 (D3, 탈출구).

버튼·식·필터로 안 되는 일회성 분석용. 표준 라이브러리 `code`로 만든다 — qtconsole(IPython)은
새 의존성·배포 번들 크기를 부르고, 여기서 필요한 건 실행·여러 줄·히스토리·데이터 주고받기뿐이다.

이름공간
  np, pd          numpy / pandas
  shelf           선반 {이름: Dataset}
  ds(name)        Dataset 하나
  df(name)        pandas DataFrame — **보이는 그대로**(숨김 행 NaN·시프트 반영). raw=True면 원본
  push(obj, name) DataFrame / Series / {열: 배열} 을 선반에 새 데이터셋으로 올린다
  fig()           지금 Publish 그림(matplotlib Figure) — 손으로 다듬어 저장할 때
  rerun(name)     설정 파일에 저장된 그 데이터셋의 콘솔 기록을 **직접** 다시 실행

재현성: 콘솔은 레시피로 남지 않는다(원칙 ④의 예외). 그래서 push한 데이터셋에 그때까지 실행한
입력 기록을 붙여 설정 파일에 저장하고 트리에 `⌨ console`로 표시한다. 설정을 다시 열 때 그 코드를
**자동 실행하지 않는다** — 공유받은 설정 파일이 임의 코드를 돌리면 안 된다. `rerun()`은 사람이 친다.
계산은 GUI 스레드에서 돈다 — 오래 걸리는 계산은 창을 멈춘다.
"""
from __future__ import annotations

import code
import contextlib
import io
from datetime import datetime

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QKeyEvent
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit, QLineEdit, QLabel

from gui.theme import AUGUR
from .data import Dataset

_BANNER = ("Plot Maker console — np, pd, shelf, ds(name), df(name), push(obj, name), fig(), rerun(name)\n"
           "Pushed datasets carry this console's input history (saved with the config, never auto-run).\n")


def frame_to_dataset(obj, name, time=None):
    """DataFrame / Series / {열: 배열} → Dataset 재료(time, cols, cats). 숫자 열은 cols, 글자 열은 cats.
    시각: DatetimeIndex(naive = 로컬로 간주 — 파일 로더와 같은 규칙) 또는 'time' 열 또는 time 인자."""
    import pandas as pd
    if isinstance(obj, pd.Series):
        obj = obj.to_frame(name=obj.name if obj.name is not None else "value")
    if isinstance(obj, dict):
        obj = pd.DataFrame({k: np.asarray(v) for k, v in obj.items()})
    if not isinstance(obj, pd.DataFrame):
        raise TypeError("push() takes a DataFrame, Series or {column: array}")
    t = None
    if time is not None:
        t = np.asarray(time, float)
    elif isinstance(obj.index, pd.DatetimeIndex):
        idx = obj.index
        if idx.tz is not None:
            t = idx.tz_convert("UTC").asi8 / 1e9
        else:
            t = np.array([d.timestamp() for d in idx.to_pydatetime()], float)
    elif "time" in obj.columns:
        tc = obj["time"]
        if np.issubdtype(tc.dtype, np.datetime64):
            t = np.array([d.timestamp() if pd.notna(d) else np.nan for d in tc.dt.to_pydatetime()], float)
        else:
            t = pd.to_numeric(tc, errors="coerce").to_numpy(float)
        obj = obj.drop(columns=["time"])
    cols, cats = {}, {}
    for c in obj.columns:
        s = obj[c]
        if s.dtype == bool or np.issubdtype(s.dtype, np.number):
            cols[str(c)] = s.to_numpy(dtype=float)
        else:
            cats[str(c)] = s.astype(str).to_numpy(dtype=object)
    if not cols:
        raise ValueError("nothing numeric to push")
    return t, cols, cats


class ConsoleWindow(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setModal(False)
        self.setWindowTitle("Plot Maker — Python console")
        self.resize(760, 480)
        self.history = []          # 성공·실패 무관, 실행한 입력 줄 전부(푸시에 붙는 기록)
        self._nav = 0
        self._buf = []
        v = QVBoxLayout(self)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(mono)
        self.out.setPlainText(_BANNER)
        v.addWidget(self.out, 1)
        self.prompt = QLabel(">>>")
        self.inp = QLineEdit()
        self.inp.setFont(mono)
        self.inp.returnPressed.connect(self._on_enter)
        self.inp.installEventFilter(self)
        v.addWidget(self.prompt)
        v.addWidget(self.inp)
        hint = QLabel("Runs on the GUI thread — long computations freeze the window. ↑/↓ = history.")
        hint.setStyleSheet(f"color:{AUGUR.faint};")
        v.addWidget(hint)
        self.ns = self._namespace()
        self.interp = code.InteractiveInterpreter(self.ns)
        self.interp.write = self._write          # 트레이스백을 창으로

    # ── 이름공간 ────────────────────────────────────────────────────────
    def _namespace(self):
        h = self.host

        def ds(name):
            return h.shelf[name]

        def df(name, raw=False):
            import pandas as pd
            d = h.shelf[name]
            data = {}
            hid = None if raw else d.hidden_mask()
            for c, a in d.cols.items():
                a = np.asarray(a, float)
                data[c] = np.where(hid, np.nan, a) if hid is not None and hid.any() else a
            for c, a in d.cats.items():
                data[c] = a
            t = d.time
            if t is not None:
                sh = 0.0 if raw else (h.time_shift_hours + d.shift_h)
                idx = pd.DatetimeIndex([datetime.fromtimestamp(x + sh * 3600.0) if np.isfinite(x) else pd.NaT
                                        for x in t], name="time")
                return pd.DataFrame(data, index=idx)
            return pd.DataFrame(data)

        def push(obj, name="console", time=None):
            t, cols, cats = frame_to_dataset(obj, name, time)
            new = Dataset(name, "<console>", t, cols, cats=cats)
            new.origin = {"kind": "console", "history": list(self.history)}
            nm = h.add_dataset(new)
            print(f"pushed '{nm}' ({len(new)} rows × {len(cols)} columns) to the shelf")
            return nm

        def fig():
            return h._build_publish_fig()

        def rerun(name):
            spec = (h._console_pending or {}).get(name) or {}
            lines = (spec.get("console") or {}).get("history")
            if not lines:
                raise KeyError(f"no saved console history for {name!r}")
            self._write(f"# re-running {len(lines)} saved line(s) for '{name}'\n")
            for ln in lines:
                self.execute(ln, record=True)

        import pandas as pd
        return {"np": np, "pd": pd, "shelf": h.shelf, "ds": ds, "df": df, "push": push,
                "fig": fig, "rerun": rerun, "__name__": "__console__"}

    # ── 실행 ────────────────────────────────────────────────────────────
    def _write(self, text):
        self.out.moveCursor(self.out.textCursor().MoveOperation.End)
        self.out.insertPlainText(text)
        self.out.moveCursor(self.out.textCursor().MoveOperation.End)

    def execute(self, line, record=True):
        """한 줄 실행(여러 줄 블록은 빈 줄로 끝). 반환: 더 입력이 필요하면 True."""
        self._write(("... " if self._buf else ">>> ") + line + "\n")
        if record:
            self.history.append(line)
        # 버퍼는 실행 **전에** 비운다 — rerun()처럼 실행 도중 execute()를 다시 부르면(재진입) 같은
        # 버퍼에 줄이 섞여 'multiple statements'가 났다(구현 중 잡음). 더 입력이 필요할 때만 되살린다.
        lines, self._buf = self._buf + [line], []
        src = "\n".join(lines)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            more = self.interp.runsource(src, "<console>")
        if buf.getvalue():
            self._write(buf.getvalue())
        if more:
            self._buf = lines
        self.prompt.setText("..." if more else ">>>")
        return more

    def _on_enter(self):
        line = self.inp.text()
        self.inp.clear()
        self._nav = len(self.history) + 1
        self.execute(line)

    def eventFilter(self, obj, ev):
        if obj is self.inp and isinstance(ev, QKeyEvent) and ev.type() == ev.Type.KeyPress:
            if ev.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.history:
                self._nav = max(0, min(len(self.history),
                                       self._nav + (-1 if ev.key() == Qt.Key.Key_Up else 1)))
                self.inp.setText(self.history[self._nav] if self._nav < len(self.history) else "")
                return True
        return super().eventFilter(obj, ev)
