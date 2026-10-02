"""vigil/dashboard/dashboard_window.py — 실시간 감시 대시보드 (설계문서 §6).

Vigil 은 분석기가 아니라 **한눈에 '괜찮나'를 보는** 감시기다. 화면은 위에서 아래로:
  1. 종합 배지 · 신선도(마지막 행 몇 초 전) · 폴더 버튼 · Start/Stop
  2. 감시 폴더 · Augur 데이터 폴더 · 시각 기준(KST/UTC)
  3. 현재 값 카드 — 채널별 농도·R·램프, 밴드 있는 HK (그래프를 읽지 않아도 지금 값이 보이게)
  4. 추세 그래프 3개(농도 · R · HK) + 오른쪽 탭(파일 · 경보 이력 · 로그)

설계 원칙(2026-10-01 개편):
  · 등급은 색 + 모양(●▲◆■○) + 글자로 — 색만으론 흑백 캡처·색각이상에서 갈린다.
  · 브랜드 청색은 경보색과 안 겹친다. 평상시 배지는 조용한 밤 바탕, 경보일 때만 색으로 찬다.
  · 그래프 y축은 **정상 범위 기준**(이상값 하나가 축을 뭉개지 않게) — 범위 밖 점은 가장자리에 ▲▼.
  · 시간축은 HH:MM, 표시 시각대(KST/UTC)를 축·표·카드·로그에 함께 적용하고 이름을 붙인다.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from gui.flow_layout import FlowLayout
from gui.theme import VIGIL, mono_family
from vigil.alert_engine import OK, P0, P1, P2, SKIP

_LEVEL = {   # status → (모양, 글자, 색)
    OK:   ("●", "OK", VIGIL.ok),
    P2:   ("▲", "P2", VIGIL.p2),
    P1:   ("◆", "P1", VIGIL.p1),
    P0:   ("■", "P0", VIGIL.p0),
    SKIP: ("○", "waiting", VIGIL.skip),
}
_BADGE_BASE = " font-size:18px; font-weight:600; padding:12px 16px;"
_BADGE_STYLE = {
    OK:   f"background:{VIGIL.surface}; color:{VIGIL.text}; border-left:6px solid {VIGIL.lamp};",
    P2:   f"background:{VIGIL.p2}; color:{VIGIL.night};",
    P1:   f"background:{VIGIL.p1}; color:{VIGIL.night};",
    P0:   f"background:{VIGIL.p0}; color:#FFFFFF;",
    SKIP: f"background:{VIGIL.surface}; color:{VIGIL.dim}; border-left:6px solid {VIGIL.rule};",
}
_BTN_STYLE = (f"QPushButton {{ font-size:15px; font-weight:600; padding:10px; color:{VIGIL.text};"
              f" background:{VIGIL.button}; border:1px solid {VIGIL.rule}; }}"
              f" QPushButton:disabled {{ color:{VIGIL.footer}; background:{VIGIL.surface}; }}")
_SMALL_BTN = (f"QPushButton {{ padding:3px 10px; color:{VIGIL.text}; background:{VIGIL.button};"
              f" border:1px solid {VIGIL.rule}; }}")

# Non-ASCII glyphs allowed in UI strings. The bundled IBM Plex has none of the shapes; these few come
# from the system fallback and were seen to render. ★ and ⏸ rendered as □ (2026-10-02 audit) — use text.
UI_GLYPHS = set("●▲◆■○▶—…₀·×–≥≤")

_COLUMNS = ["File", "Last row", "Lag (s)", "HK", "R", "Lamp", "Conc"]
_ALARM_COLUMNS = ["Start", "End", "Level", "Source", "Message"]

# 곡선 팔레트 — 등불·감시기 청색 계열만. 노랑·주황·빨강은 임계선 전용.
_PALETTE = list(VIGIL.curves)
_WARN_COLOR = VIGIL.p2
_ALARM_COLOR = VIGIL.p0

# 시각 기준 — 표시만 바꾼다(저장·판정은 모두 실제 시각 epoch). pyqtgraph DateAxisItem 의 utcOffset 은
# '표시 = 실제 − offset' 규칙이라 UTC+9 는 −32400.
TZ_CHOICES = {"KST": 9.0, "UTC": 0.0}

_PLACEHOLDER = {
    "conc": "Concentration — shown after the ZA (I₀) segment",
    "r": "R — shown after ZA/He calibration completes",
    "hk": "HK — waiting for first row",
}


def _robust_range(series, lines=()):
    """정상 범위 기준 y 범위 — series: [(xs, ys), …]. 값이 없으면 None.
    최대·최소로 잡으면 스파이크 하나가 나머지를 한 줄로 뭉갰다. 그래서 몸통(양끝 1 %·최소 1점 뺀 범위)을
    잡고, 몸통 폭의 3배 안에 있는 점은 다시 넣는다 — 서서히 이어지는 드리프트·계단은 그대로 보이고
    동떨어진 튀는 점만 빠진다(그 점은 _fit_view 가 가장자리 ▲▼ 로 표시)."""
    vals = [np.asarray(ys, float) for _xs, ys in series if len(ys)]
    vals = np.sort(np.concatenate(vals)) if vals else np.array([])
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return None
    if vals.size >= 20:
        k = max(1, int(0.01 * vals.size))
        b_lo, b_hi = vals[k], vals[-k - 1]
        reach = 3.0 * max(b_hi - b_lo, abs(b_hi) * 1e-6, 1e-12)
        keep = vals[(vals >= b_lo - reach) & (vals <= b_hi + reach)]
        lo, hi = keep[0], keep[-1]
    else:
        lo, hi = vals[0], vals[-1]
    for v in lines:
        if v is not None and math.isfinite(v):
            lo, hi = min(lo, v), max(hi, v)
    span = hi - lo
    pad = 0.1 * span if span > 0 else max(abs(hi) * 0.05, 1e-9)
    return float(lo - pad), float(hi + pad)


class _Card(QFrame):
    """현재 값 카드 — 제목 · 큰 값 · 보조 줄. 왼쪽 띠 색이 등급."""

    def __init__(self, mono: str):
        super().__init__()
        self.setMinimumWidth(150)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(1)
        self.t = QLabel(); self.v = QLabel(); self.s = QLabel()
        self.t.setStyleSheet(f"color:{VIGIL.sub}; font-size:11px;")
        self.v.setStyleSheet(f"color:{VIGIL.text}; font-size:18px; font-weight:600; font-family:'{mono}';")
        self.s.setStyleSheet(f"color:{VIGIL.dim}; font-size:10px;")
        for w in (self.t, self.v, self.s):
            lay.addWidget(w)
        self._status = None

    def set(self, title, value, sub, status, tip=""):
        self.t.setText(title); self.v.setText(value); self.s.setText(sub); self.setToolTip(tip)
        if status != self._status:
            glyph, _lvl, col = _LEVEL.get(status, _LEVEL[SKIP])
            self.setStyleSheet(f"_Card {{ background:{VIGIL.surface}; border-left:4px solid "
                               f"{VIGIL.lamp if status == OK else col}; }}")
            self._status = status


class DashboardWindow(QMainWindow):
    run_toggled = pyqtSignal(bool)        # Start/Stop → True=감시 중, False=정지
    folder_requested = pyqtSignal()       # 'Choose folder…' — 고르는 창은 run_vigil 이 띄운다
    data_root_requested = pyqtSignal()    # 'Augur data…' — 다른 PC 의 Augur 출력 폴더
    tz_changed = pyqtSignal(str)          # 'KST' | 'UTC'

    def __init__(self, title: str = "Vigil — Pipeline Health", tz: str = "KST"):
        super().__init__()
        self._paused = False
        self.setWindowTitle(title)
        self.resize(1360, 860)
        self._last_status = None
        self._curve_items: dict = {}      # 커브 캐시(키→PlotDataItem)
        self._threshold_items: dict = {}  # 임계선 캐시(키→[InfiniteLine,...])
        self._out_items: dict = {}        # 범위 밖 표시 ▲▼ (plot 키 → ScatterPlotItem)
        self._color_idx = 0
        self._color_of: dict = {}
        self._cards: dict = {}
        self._row_of: dict = {}           # 파일 표: path → 행 번호(바뀐 칸만 갱신)
        self._tz = tz if tz in TZ_CHOICES else "KST"
        self._mono = mono_family()
        self._watch_dir = None

        root = QWidget()
        lay = QVBoxLayout(root)

        # 1) 배지 · 신선도 · 폴더 · Start
        self._base_title = title
        self.badge = QLabel(f"{_LEVEL[SKIP][0]}  Initializing…")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.badge.setStyleSheet(_BADGE_STYLE[SKIP] + _BADGE_BASE)
        self.fresh = QLabel("last row —")
        self.fresh.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fresh.setMinimumWidth(190)
        self.fresh.setToolTip("Time since the newest raw row arrived (liveness). Red when beyond the grace period.")
        self._fresh_style(None)
        self.btn_run = QPushButton("■ Stop")
        self.btn_run.setMinimumWidth(110)
        self.btn_run.setStyleSheet(_BTN_STYLE)
        self.btn_run.setToolTip("Pause/resume monitoring — raw keeps accumulating while paused; on resume it reads the backlog")
        self.btn_run.clicked.connect(self._toggle_run)
        self.btn_folder = QPushButton("Choose folder…")
        self.btn_folder.setMinimumWidth(150)
        self.btn_folder.setStyleSheet(_BTN_STYLE)
        self.btn_folder.setToolTip("Choose the raw .dat folder to monitor (searched recursively)")
        self.btn_folder.clicked.connect(self.folder_requested.emit)
        top = QHBoxLayout()
        top.addWidget(self.badge, stretch=1)
        top.addWidget(self.fresh)
        top.addWidget(self.btn_folder)
        top.addWidget(self.btn_run)
        lay.addLayout(top)

        # 2) 폴더 · Augur 데이터 폴더 · 시각 기준
        info = QHBoxLayout()
        self.lbl_folder = QLabel("No folder selected")
        self.lbl_folder.setStyleSheet(f"color:{VIGIL.dim}; padding:0 4px;")
        self.lbl_data = QLabel("Augur data: not set")
        self.lbl_data.setStyleSheet(f"color:{VIGIL.dim}; padding:0 4px;")
        self.lbl_data.setToolTip("Where this PC keeps Augur outputs (FitSets, wavelength calibrations, references).\n"
                                 "Needed only when the profile's paths were made on another PC.")
        self.btn_data = QPushButton("Augur data…")
        self.btn_data.setStyleSheet(_SMALL_BTN)
        self.btn_data.clicked.connect(self.data_root_requested.emit)
        self.cb_tz = QComboBox()
        self.cb_tz.addItems(list(TZ_CHOICES))
        self.cb_tz.setCurrentText(self._tz)
        self.cb_tz.setToolTip("Time zone for the time axis, tables, cards and log (display only)")
        self.cb_tz.currentTextChanged.connect(self._on_tz)
        info.addWidget(self.lbl_folder, stretch=1)
        info.addWidget(self.lbl_data)
        info.addWidget(self.btn_data)
        info.addSpacing(12)
        info.addWidget(QLabel("Time:"))
        info.addWidget(self.cb_tz)
        lay.addLayout(info)

        # 3) 현재 값 카드
        self._cards_box = QWidget()
        self._cards_flow = FlowLayout(self._cards_box, margin=0, spacing=6)
        self._cards_empty = QLabel("Current values appear here once rows arrive.")
        self._cards_empty.setStyleSheet(f"color:{VIGIL.dim}; padding:4px;")
        self._cards_flow.addWidget(self._cards_empty)
        lay.addWidget(self._cards_box)

        # 4) 그래프 + 탭
        grid = QGridLayout()
        lay.addLayout(grid, stretch=1)
        self.p_conc = self._make_plot("Concentration (ppb)", "conc")
        self.p_r = self._make_plot("R", "r")
        self.p_hk = self._make_plot("HK", "hk")
        grid.addWidget(self.p_conc, 0, 0)
        grid.addWidget(self.p_r, 0, 1)
        grid.addWidget(self.p_hk, 1, 0)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(_COLUMNS)):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.alarm_table = QTableWidget(0, len(_ALARM_COLUMNS))
        self.alarm_table.setHorizontalHeaderLabels(_ALARM_COLUMNS)
        hh = self.alarm_table.horizontalHeader()
        for col in range(4):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.alarm_table.verticalHeader().setVisible(False)
        self.alarm_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._alarm_sig = None

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(2000)
        self.log.setStyleSheet(f"font-family:'{self._mono}',monospace; font-size:11px; color:{VIGIL.log};")

        self.tabs = QTabWidget()
        self.tabs.addTab(self.table, "Files")
        self.tabs.addTab(self.alarm_table, "Alarms")
        self.tabs.addTab(self.log, "Log")
        grid.addWidget(self.tabs, 1, 1)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)

        self.setCentralWidget(root)

    # ── 공통 ─────────────────────────────────────────────────────────────
    def _make_plot(self, ylabel, kind):
        pw = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem(orientation='bottom',
                                                                utcOffset=self._utc_offset())})
        pw.getAxis('left').enableAutoSIPrefix(False)   # R 이 '999.955 (×0.001)' 로 읽히던 것
        pw.setLabel('left', ylabel)
        pw.setLabel('bottom', f"Time ({self._tz})")
        pw.addLegend(offset=(10, 10))
        pw.showGrid(x=True, y=True, alpha=0.2)
        pw.setTitle(_PLACEHOLDER[kind], color=VIGIL.dim, size="10pt")
        pw.setMouseEnabled(x=True, y=False)
        return pw

    def _utc_offset(self) -> int:
        return int(-TZ_CHOICES[self._tz] * 3600)

    def _fmt_time(self, t, fmt="%H:%M:%S") -> str:
        """실제 시각(naive local datetime 또는 epoch) → 선택 시각대 문자열."""
        if t is None:
            return "—"
        ep = t.timestamp() if isinstance(t, datetime) else float(t)
        return datetime.fromtimestamp(ep + TZ_CHOICES[self._tz] * 3600, tz=timezone.utc).strftime(fmt)

    def _on_tz(self, tz) -> None:
        self._tz = tz
        for pw in (self.p_conc, self.p_r, self.p_hk):
            ax = pw.getAxis('bottom')
            ax.utcOffset = self._utc_offset()
            if getattr(ax, "zoomLevel", None) is not None:
                ax.zoomLevel.utcOffset = ax.utcOffset
            pw.setLabel('bottom', f"Time ({tz})")
            ax.picture = None
            ax.update()
        self._row_of.clear(); self.table.setRowCount(0)   # 시각 칸 다시 쓰기
        self._alarm_sig = None
        self.tz_changed.emit(tz)

    def _color_for(self, key) -> str:
        col = self._color_of.get(key)
        if col is None:
            col = _PALETTE[self._color_idx % len(_PALETTE)]
            self._color_idx += 1
            self._color_of[key] = col
        return col

    def _fresh_style(self, bad) -> None:
        col = VIGIL.dim if bad is None else (VIGIL.p0 if bad else VIGIL.text)
        self.fresh.setStyleSheet(f"color:{col}; background:{VIGIL.surface}; font-size:14px;"
                                 f" font-weight:600; padding:10px; font-family:'{self._mono}';")

    def _fit_view(self, pw, series, lines=(), key=None) -> None:
        """y 를 정상 범위로, x 를 최근 데이터로(최소 10분 폭 — 짧으면 '43.400' 같은 초 눈금이 나왔다).
        범위 밖 점은 위/아래 가장자리에 ▲▼ 로 위치만 표시한다."""
        xs = [x for xa, _ya in series for x in xa]
        if not xs:
            return
        x1 = max(xs); x0 = min(min(xs), x1 - 600)
        pw.setXRange(x0, x1 + 0.02 * (x1 - x0), padding=0)
        rng = _robust_range(series, lines)
        if rng is None:
            return
        lo, hi = rng
        pw.setYRange(lo, hi, padding=0)
        ox, oy, sym = [], [], []
        for xa, ya in series:
            for x, y in zip(xa, ya):
                if y == y and (y > hi or y < lo):
                    ox.append(x); oy.append(hi if y > hi else lo); sym.append('t1' if y > hi else 't')
        item = self._out_items.get(key)
        if item is None:
            item = pg.ScatterPlotItem(size=9, pen=None, brush=pg.mkBrush(VIGIL.p1))
            pw.addItem(item)
            self._out_items[key] = item
        item.setData(ox, oy, symbol=sym or 't')
        item.setZValue(10)

    # ── 공개 API ─────────────────────────────────────────────────────────
    def set_running(self, running: bool) -> None:
        """버튼·배지만 맞춘다(시그널 없음)."""
        self._paused = not running
        self.btn_run.setText("■ Stop" if running else "▶ Start")
        if not running:
            # tick stops while paused, so the age would freeze at e.g. "7 s ago" and look healthy.
            self.fresh.setText("paused\nnot reading"); self._fresh_style(None)
        if not running and not self._watch_dir:
            self.badge.setText("○  Choose the raw folder to monitor — 'Choose folder…' at the right")
            self.badge.setStyleSheet(_BADGE_STYLE[SKIP] + _BADGE_BASE)
            self.setWindowTitle(self._base_title)
        elif not running:
            self.badge.setText("○  PAUSED — monitoring paused, press Start to read (from the backlog)")
            self.badge.setStyleSheet(_BADGE_STYLE[SKIP] + _BADGE_BASE)
            self.setWindowTitle(f"[paused] {self._base_title}")

    def set_watch_dir(self, path) -> None:
        self._watch_dir = path or None
        self.btn_run.setEnabled(bool(path))
        self.btn_folder.setText("Change folder…" if path else "Choose folder…")
        self.lbl_folder.setText(f"Watching: {path}" if path else "No folder selected")
        self.lbl_folder.setToolTip(path or "")
        self._base_title = f"Vigil — {path}" if path else "Vigil"
        if not path:
            self.badge.setText("○  Choose the raw folder to monitor — 'Choose folder…' at the right")
            self.badge.setStyleSheet(_BADGE_STYLE[SKIP] + _BADGE_BASE)
            self.setWindowTitle(self._base_title)
        elif self._paused:
            self.set_running(False)

    def set_data_root(self, path) -> None:
        self.lbl_data.setText(f"Augur data: {path}" if path else "Augur data: not set")

    def reset_views(self) -> None:
        """폴더를 바꿀 때 — 이전 폴더의 그래프·표·카드·경보 이력을 비운다."""
        for pw, kind in ((self.p_conc, "conc"), (self.p_r, "r"), (self.p_hk, "hk")):
            if pw.plotItem.legend is not None:
                pw.plotItem.legend.clear()
            pw.clear()
            pw.setTitle(_PLACEHOLDER[kind], color=VIGIL.dim, size="10pt")
        self._curve_items.clear(); self._threshold_items.clear(); self._out_items.clear()
        self._color_of.clear(); self._color_idx = 0
        self.table.setRowCount(0); self._row_of.clear()
        self.alarm_table.setRowCount(0); self._alarm_sig = None
        for c in self._cards.values():
            c.setParent(None)
        self._cards.clear()
        self._cards_empty.show()
        self._last_status = None
        self.fresh.setText("last row —"); self._fresh_style(None)

    def _toggle_run(self) -> None:
        self.set_running(self._paused)
        self.run_toggled.emit(not self._paused)

    def set_status(self, status: str, msg: str) -> None:
        if self._paused:
            return
        glyph, level, _col = _LEVEL.get(status, _LEVEL[SKIP])
        self.badge.setText(f"{glyph}  {level}   {msg}")
        self.badge.setStyleSheet(_BADGE_STYLE.get(status, _BADGE_STYLE[SKIP]) + _BADGE_BASE)
        self.setWindowTitle(f"[{level}] {self._base_title}" if status in (P0, P1, P2) else self._base_title)
        if status == P0 and self._last_status != P0:
            QApplication.alert(self)      # 작업표시줄 깜빡임
        self._last_status = status

    def set_freshness(self, last_arrival, now, grace_sec) -> None:
        """마지막 raw 행이 몇 초 전에 왔나 — 측정 정지(P0)의 1차 신호를 크게."""
        if last_arrival is None:
            self.fresh.setText("last row —"); self._fresh_style(None)
            return
        age = (now - last_arrival).total_seconds()
        txt = f"{age:.0f} s ago" if age < 120 else (f"{age / 60:.0f} min ago" if age < 7200 else f"{age / 3600:.1f} h ago")
        self.fresh.setText(f"last row {txt}\n{self._fmt_time(last_arrival)} {self._tz}")
        self._fresh_style(age > grace_sec)

    def update_cards(self, cards: list) -> None:
        """cards: [{key, title, value, sub, status}] — 새 키만 위젯을 만들고 나머지는 글자만 바꾼다."""
        seen = set()
        for c in cards:
            w = self._cards.get(c["key"])
            if w is None:
                w = _Card(self._mono)
                self._cards[c["key"]] = w
                self._cards_flow.addWidget(w)
            w.set(c["title"], c["value"], c.get("sub", ""), c.get("status"), c.get("tip", ""))
            seen.add(c["key"])
        for k in [k for k in self._cards if k not in seen]:
            self._cards.pop(k).setParent(None)
        self._cards_empty.setVisible(not self._cards)

    def update_alarms(self, alarms: list) -> None:
        """경보 이력 — 최근 것이 위, 진행 중(End 없음)은 등급색. 바뀐 게 없으면 다시 그리지 않는다."""
        # 서명은 '진행 중인 것 전부' + 맨 끝 항목 — 예전엔 최근 50건만 봐서 그보다 오래된 경보가 닫혀도
        # 'ongoing'·열린 개수가 안 바뀌었고, 500건 상한에 닿으면 len 도 멈췄다(2026-10-02 리뷰).
        last = alarms[-1] if alarms else None
        sig = (len(alarms),
               (last["start"], last["source"], last["level"], last["end"]) if last else None,
               tuple((a["start"], a["source"], a["level"], a["msg"]) for a in alarms if a["end"] is None))
        if sig == self._alarm_sig:
            return
        self._alarm_sig = sig
        rows = list(reversed(alarms[-200:]))
        self.alarm_table.setRowCount(len(rows))
        for i, a in enumerate(rows):
            glyph, level, col = _LEVEL.get(a["level"], _LEVEL[SKIP])
            cells = [self._fmt_time(a["start"], "%m-%d %H:%M:%S"),
                     self._fmt_time(a["end"], "%H:%M:%S") if a["end"] else "ongoing",
                     f"{glyph} {level}", a["source"], a["msg"]]
            for j, txt in enumerate(cells):
                it = QTableWidgetItem(txt)
                if a["end"] is None:
                    it.setForeground(QColor(col))
                if j == 4:
                    it.setToolTip(txt)
                self.alarm_table.setItem(i, j, it)
        n_open = sum(1 for a in alarms if a["end"] is None)
        self.tabs.setTabText(1, f"Alarms ({n_open})" if n_open else "Alarms")

    def _status_text(self, status):
        glyph, level, color = _LEVEL.get(status, _LEVEL[SKIP])
        # OK 는 기본 글자색(표가 초록으로 도배되면 정작 경보가 안 보인다)
        return f"{glyph} {level}", (VIGIL.text if status == OK else color)

    def _set_cell(self, r, c, text, color=None, tip=None) -> None:
        it = self.table.item(r, c)
        if it is None:
            it = QTableWidgetItem(text)
            self.table.setItem(r, c, it)
        elif it.text() != text:
            it.setText(text)
        if color is not None:
            it.setForeground(QColor(color))
        if tip is not None and it.toolTip() != tip:
            it.setToolTip(tip)

    def update_files(self, rows: dict) -> None:
        """파일 표 — 행을 매번 새로 만들지 않고 바뀐 칸만 고친다(매초 호출)."""
        if set(rows) != set(self._row_of):
            self._row_of = {p: i for i, p in enumerate(sorted(rows))}
            self.table.setRowCount(0)
            self.table.setRowCount(len(rows))
        for path, info in rows.items():
            r = self._row_of[path]
            self._set_cell(r, 0, os.path.basename(path), tip=path)
            self._set_cell(r, 1, self._fmt_time(info.get("last_row")))
            lag = info.get("lag")
            self._set_cell(r, 2, f"{lag:.1f}" if lag is not None else "—",
                           VIGIL.p0 if lag is not None and lag > 10.0 else VIGIL.text)
            for c, k in ((3, "hk"), (4, "r"), (5, "lamp"), (6, "conc")):
                txt, col = self._status_text(info.get(f"{k}_status"))
                self._set_cell(r, c, txt, col, info.get(f"{k}_msg") or "")

    def update_conc_trend(self, trend: dict, meta: dict) -> None:
        arrays = []
        for key, dq in trend.items():
            if not dq:
                continue
            m = meta.get(key, {})
            label = m.get("label", str(key))
            target = m.get("target")
            gases = sorted({g for _t, gd in dq for g in gd})
            xs = [t.timestamp() for t, _gd in dq]
            for gas in gases:
                ck = ("conc", key, gas)
                item = self._curve_items.get(ck)
                if item is None:
                    is_target = gas == target
                    pen = pg.mkPen(self._color_for(ck), width=2.5 if is_target else 1.0)
                    item = self.p_conc.plot(pen=pen, name=f"{label}:{gas}" + (" (target)" if is_target else ""))
                    self.p_conc.setTitle(None)
                    self._curve_items[ck] = item
                ys = [gd.get(gas, float('nan')) for _t, gd in dq]
                item.setData(xs, ys)
                arrays.append((xs, ys))
            tk = ("conc_thr", key)
            if tk not in self._threshold_items:
                lines = []
                for v in (m.get("conc_min_ppb"), m.get("conc_max_ppb")):
                    if v is not None:
                        line = pg.InfiniteLine(pos=v, angle=0, movable=False,
                                               pen=pg.mkPen(_ALARM_COLOR, style=Qt.PenStyle.DashLine))
                        self.p_conc.addItem(line)
                        lines.append(line)
                self._threshold_items[tk] = lines
        if arrays:
            # 임계선(예: 상한 500 ppb)을 범위에 넣으면 수 ppb 추세가 바닥에 붙는다 — 데이터 기준으로만.
            self._fit_view(self.p_conc, arrays, key="conc")

    def update_r_trend(self, trend: dict, meta: dict) -> None:
        arrays = []
        for key, dq in trend.items():
            if not dq:
                continue
            m = meta.get(key, {})
            label = m.get("label", str(key))
            xs = [t.timestamp() for t, _r, _b in dq]
            ys = [r if r is not None else float('nan') for _t, r, _b in dq]
            bs = [b if b is not None else float('nan') for _t, _r, b in dq]
            ck = ("r", key)
            item = self._curve_items.get(ck)
            if item is None:
                item = self.p_r.plot(pen=pg.mkPen(self._color_for(ck), width=1.5), symbol='o',
                                     symbolSize=4, symbolBrush=self._color_for(ck), name=label)
                self.p_r.setTitle(None)
                self._curve_items[ck] = item
            item.setData(xs, ys)
            bk = ("r_baseline", key)
            bitem = self._curve_items.get(bk)
            if bitem is None:
                bitem = self.p_r.plot(pen=pg.mkPen(self._color_for(ck), width=1.0, style=Qt.PenStyle.DotLine))
                self._curve_items[bk] = bitem
            bitem.setData(xs, bs)
            arrays += [(xs, ys), (xs, bs)]
        if arrays:
            self._fit_view(self.p_r, arrays, key="r")

    def update_hk_trend(self, trend: dict, meta: dict) -> None:
        arrays = []
        for key, dq in trend.items():
            if not dq:
                continue
            m = meta.get(key, {})
            label = m.get("label", str(key))
            unit = m.get("unit")
            xs = [t.timestamp() for t, _v in dq]
            ys = [v for _t, v in dq]
            ck = ("hk", key)
            item = self._curve_items.get(ck)
            if item is None:
                item = self.p_hk.plot(pen=pg.mkPen(self._color_for(ck), width=1.5),
                                      name=f"{label} ({unit})" if unit else label)
                self.p_hk.setTitle(None)
                self._curve_items[ck] = item
            item.setData(xs, ys)
            arrays.append((xs, ys))
            tk = ("hk_thr", key)
            if tk not in self._threshold_items:
                lines = []
                for band, color in ((m.get("warn"), _WARN_COLOR), (m.get("alarm"), _ALARM_COLOR)):
                    for v in (band or ()):
                        if v is not None:
                            line = pg.InfiniteLine(pos=v, angle=0, movable=False,
                                                   pen=pg.mkPen(color, style=Qt.PenStyle.DashLine))
                            self.p_hk.addItem(line)
                            lines.append(line)
                self._threshold_items[tk] = lines
        if arrays:
            # HK 는 단위가 섞여 있어(mbar·°C) 임계선을 범위에 넣지 않는다 — 넣으면 다른 필드가 뭉개진다.
            self._fit_view(self.p_hk, arrays, key="hk")

    def log_line(self, text: str) -> None:
        self.log.append(f"[{self._fmt_time(datetime.now())}] {text}")

