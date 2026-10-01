"""vigil/dashboard/dashboard_window.py — 최소 실시간 대시보드 (설계문서 §6, M0+M1+M2+M3).

M0: 종합 상태 배지(OK/P1/P2/P0) + 파일별 최근 행 시각/지연 + append-only 로그.
M1: 파일별 HK(밴드·포화) 상태 열 + HK 필드 추세 그래프. M2: 파일별 R(거울) 상태 열 + R 추세
그래프. M3: 파일별 농도 상태 열 + 전 레퍼런스 가스 농도 추세 그래프.
"""
from __future__ import annotations

import os
from datetime import datetime

import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from gui.theme import VIGIL, mono_family
from vigil.alert_engine import OK, P0, P1, P2, SKIP

# 밤·등불 테마(gui/theme.py). 등급은 **색 + 모양 + 글자** 셋으로 구분한다 — 색만으로는
# 색각이상·흑백 캡처·멀리서 본 화면에서 갈린다. 평상시(OK) 배지는 조용한 밤 바탕에 등불색
# 선 하나 — 브랜드 청색이 경보색처럼 보이면 안 되고, 경보일 때만 배지 전체가 색으로 찬다.
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

_COLUMNS = ["File", "Last row", "Lag (s)", "HK", "R", "Lamp", "Conc"]

# 채널/가스/HK필드 커브에 순환 배정하는 팔레트 — 등불·감시기 청색 계열만. 노랑·주황·빨강은
# 임계선 전용이라 곡선에 쓰지 않는다(평범한 곡선이 경보처럼 보이던 것, 2026-10-01).
_PALETTE = list(VIGIL.curves)
_WARN_COLOR = VIGIL.p2
_ALARM_COLOR = VIGIL.p0


class DashboardWindow(QMainWindow):
    run_toggled = pyqtSignal(bool)   # Start/Stop 버튼 → True=감시 중, False=정지
    folder_requested = pyqtSignal()  # 'Choose folder…' 버튼 — 고르는 창은 run_vigil 이 띄운다

    def __init__(self, title: str = "Vigil — Pipeline Health"):
        super().__init__()
        self._paused = False
        self.setWindowTitle(title)
        self.resize(1280, 800)
        self._last_status = None   # P0로의 전이에서만 소리내기 위한 상태 기억
        self._curve_items: dict = {}      # 커브 캐시(키→PlotDataItem) — 매 tick 재생성 방지(깜빡임)
        self._threshold_items: dict = {}  # 임계선 캐시(키→[InfiniteLine,...]) — 1회만 그림
        self._color_idx = 0
        self._color_of: dict = {}         # 커브 키→배정된 팔레트 색(관련 커브끼리 색 재사용용)

        root = QWidget()
        lay = QVBoxLayout(root)

        self._base_title = title
        self.badge = QLabel(f"{_LEVEL[SKIP][0]}  Initializing…")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.badge.setStyleSheet(_BADGE_STYLE[SKIP] + _BADGE_BASE)
        self.btn_run = QPushButton("■ Stop")
        self.btn_run.setMinimumWidth(110)
        self.btn_run.setStyleSheet(
            f"QPushButton {{ font-size:15px; font-weight:600; padding:10px; color:{VIGIL.text};"
            f" background:{VIGIL.button}; border:1px solid {VIGIL.rule}; }}"
            f" QPushButton:disabled {{ color:{VIGIL.footer}; background:{VIGIL.surface}; }}")
        self.btn_run.setToolTip("Pause/resume monitoring — raw keeps accumulating while paused; on resume it reads the backlog")
        self.btn_run.clicked.connect(self._toggle_run)
        # 감시 폴더 — 고정 폴더 없이 사람이 고른다. 고르기 전엔 Start 를 못 누른다.
        self.btn_folder = QPushButton("Choose folder…")
        self.btn_folder.setMinimumWidth(150)
        self.btn_folder.setStyleSheet(self.btn_run.styleSheet())
        self.btn_folder.setToolTip("Choose the raw .dat folder to monitor (searched recursively)")
        self.btn_folder.clicked.connect(self.folder_requested.emit)
        self.lbl_folder = QLabel("No folder selected")
        self.lbl_folder.setStyleSheet(f"color:{VIGIL.dim}; padding:0 4px;")
        top = QHBoxLayout()
        top.addWidget(self.badge, stretch=1)
        top.addWidget(self.btn_folder)
        top.addWidget(self.btn_run)
        lay.addLayout(top)
        lay.addWidget(self.lbl_folder)
        self._watch_dir = None

        grid = QGridLayout()
        lay.addLayout(grid, stretch=1)

        self.p_conc = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem(orientation='bottom')})
        self.p_conc.setLabel('left', 'Concentration (ppb)')
        self.p_conc.addLegend(offset=(10, 10))
        self.p_conc.showGrid(x=True, y=True, alpha=0.2)
        self.p_conc.setTitle("Concentration — shown after the ZA (I₀) segment", color=VIGIL.dim, size="10pt")
        grid.addWidget(self.p_conc, 0, 0)

        self.p_r = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem(orientation='bottom')})
        self.p_r.setLabel('left', 'R')
        self.p_r.addLegend(offset=(10, 10))
        self.p_r.showGrid(x=True, y=True, alpha=0.2)
        self.p_r.setTitle("R — shown after ZA/He calibration completes", color=VIGIL.dim, size="10pt")
        grid.addWidget(self.p_r, 0, 1)

        self.p_hk = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem(orientation='bottom')})
        self.p_hk.setLabel('left', 'HK')
        self.p_hk.addLegend(offset=(10, 10))
        self.p_hk.showGrid(x=True, y=True, alpha=0.2)
        self.p_hk.setTitle("HK — waiting for first row", color=VIGIL.dim, size="10pt")
        grid.addWidget(self.p_hk, 1, 0)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # 상태 칸은 이제 '◆ P1' 처럼 짧다 — 내용 폭으로 두고 남는 폭은 파일명에.
        for col in (1, 2, 3, 4, 5, 6):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(2000)   # 몇 주 무인 운용에도 메모리가 안 자라게
        self.log.setMaximumHeight(160)
        self.log.setStyleSheet(f"font-family:'{mono_family()}',monospace; font-size:11px;"
                               f" color:{VIGIL.log};")

        right_panel = QWidget()
        right_lay = QVBoxLayout(right_panel)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.addWidget(self.table, stretch=1)
        right_lay.addWidget(self.log)
        grid.addWidget(right_panel, 1, 1)

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)

        self.setCentralWidget(root)

    # ── 색 배정 ──────────────────────────────────────────────────────────
    def _color_for(self, key) -> str:
        """key(커브 식별자)에 팔레트 색을 1회 배정하고 재사용. 관련 커브(예: R과 그 baseline)는
        같은 base key를 넘겨 색을 맞출 수 있다."""
        col = self._color_of.get(key)
        if col is None:
            col = _PALETTE[self._color_idx % len(_PALETTE)]
            self._color_idx += 1
            self._color_of[key] = col
        return col

    # ── 공개 API — run_vigil의 poll 루프가 매 tick 호출 ─────────────────
    def set_running(self, running: bool) -> None:
        """버튼·배지만 맞춘다(시그널 없음) — 시작 상태를 정할 때."""
        self._paused = not running
        self.btn_run.setText("■ Stop" if running else "▶ Start")
        if not running and not getattr(self, "_watch_dir", None):
            self.badge.setText("○  Choose the raw folder to monitor — 'Choose folder…' at the right")
            self.badge.setStyleSheet(_BADGE_STYLE[SKIP] + _BADGE_BASE)
            self.setWindowTitle(self._base_title)
        elif not running:
            # 정지 배지는 '경보'가 아니라 '사용자가 멈춤' — 경보색을 쓰지 않는다
            self.badge.setText("⏸  Monitoring paused — press Start to read (from the backlog)")
            self.badge.setStyleSheet(_BADGE_STYLE[SKIP] + _BADGE_BASE)
            self.setWindowTitle(f"[paused] {self._base_title}")

    def set_watch_dir(self, path) -> None:
        """감시 폴더 표시. 폴더가 없으면 Start 를 막고 배지로 안내한다."""
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
            self.set_running(False)      # 배지·제목을 새 폴더 기준으로

    def reset_views(self) -> None:
        """폴더를 바꿀 때 — 이전 폴더의 그래프·표·로그 줄을 비운다(다른 데이터와 섞이지 않게)."""
        for pw, title in ((self.p_conc, "Concentration — shown after the ZA (I₀) segment"),
                          (self.p_r, "R — shown after ZA/He calibration completes"),
                          (self.p_hk, "HK — waiting for first row")):
            if pw.plotItem.legend is not None:
                pw.plotItem.legend.clear()
            pw.clear()
            pw.setTitle(title, color=VIGIL.dim, size="10pt")
        self._curve_items.clear()
        self._threshold_items.clear()
        self._color_of.clear()
        self._color_idx = 0
        self.table.setRowCount(0)
        self._last_status = None

    def _toggle_run(self) -> None:
        self.set_running(self._paused)
        self.run_toggled.emit(not self._paused)

    def set_status(self, status: str, msg: str) -> None:
        """종합 상태 배지 갱신(liveness + HK + R 등 전체 aggregate 결과). 정지 중엔 무시한다."""
        if self._paused:
            return
        glyph, level, _col = _LEVEL.get(status, _LEVEL[SKIP])
        self.badge.setText(f"{glyph}  {level}   {msg}")
        self.badge.setStyleSheet(_BADGE_STYLE.get(status, _BADGE_STYLE[SKIP]) + _BADGE_BASE)
        # 작업표시줄에서도 보이게: 경보면 창 제목 앞에 등급, P0 전이 순간엔 작업표시줄 깜빡임+삑
        self.setWindowTitle(f"[{level}] {self._base_title}" if status in (P0, P1, P2) else self._base_title)
        if status == P0 and self._last_status != P0:
            QApplication.beep()   # P0로의 전이 순간에만 (매 tick 울리지 않게)
            QApplication.alert(self)
        self._last_status = status

    def _status_item(self, status, msg) -> QTableWidgetItem:
        glyph, level, color = _LEVEL.get(status, _LEVEL[SKIP])
        # 칸엔 등급만(좁은 칸에서 '◆ P…'로 잘리던 것) — 설명은 툴팁·아래 로그에.
        item = QTableWidgetItem(f"{glyph} {level}")
        if status in (P0, P1, P2, SKIP) or status is None:
            item.setForeground(QColor(color))
        if msg:
            item.setToolTip(msg)          # 셀이 좁아 잘린 메시지를 마우스로 다 볼 수 있게
        return item

    def update_files(self, rows: dict) -> None:
        """rows: {file_path: {"last_row":datetime|None, "lag":float|None,
        "hk_status":str|None, "hk_msg":str|None, "r_status":str|None, "r_msg":str|None,
        "lamp_status":str|None, "lamp_msg":str|None, "conc_status":str|None, "conc_msg":str|None}}.
        어떤 판정이든 아직 없으면 status=None으로 두면 '⏳ —'로 표시된다."""
        self.table.setRowCount(len(rows))
        for i, (path, info) in enumerate(sorted(rows.items())):
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(path)))
            last_row = info.get("last_row")
            last_str = last_row.strftime("%H:%M:%S") if last_row else "—"
            self.table.setItem(i, 1, QTableWidgetItem(last_str))
            lag = info.get("lag")
            lag_str = f"{lag:.1f}" if lag is not None else "—"
            lag_item = QTableWidgetItem(lag_str)
            if lag is not None and lag > 10.0:
                lag_item.setForeground(QColor(VIGIL.p0))
            self.table.setItem(i, 2, lag_item)
            self.table.setItem(i, 3, self._status_item(info.get("hk_status"), info.get("hk_msg")))
            self.table.setItem(i, 4, self._status_item(info.get("r_status"), info.get("r_msg")))
            self.table.setItem(i, 5, self._status_item(info.get("lamp_status"), info.get("lamp_msg")))
            self.table.setItem(i, 6, self._status_item(info.get("conc_status"), info.get("conc_msg")))

    def update_conc_trend(self, trend: dict, meta: dict) -> None:
        """trend: {(profile_id,ch_id): deque[(datetime, {gas: ppb})]}. FitSet에 걸린 레퍼런스
        가스 전부를 채널별로 커브 하나씩(target은 굵게) 그린다. meta: label/target/conc_min_ppb/
        conc_max_ppb."""
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
                    name = f"{label}:{gas}" + (" ★" if is_target else "")
                    item = self.p_conc.plot(pen=pen, name=name)
                    self.p_conc.setTitle(None)
                    self._curve_items[ck] = item
                ys = [gd.get(gas, float('nan')) for _t, gd in dq]
                item.setData(xs, ys)
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

    def update_r_trend(self, trend: dict, meta: dict) -> None:
        """trend: {(profile_id,ch_id): deque[(datetime, R, baseline)]}. 채널별 실측 R(실선)+
        롤링 baseline(점선, 같은 색)을 그린다 — 절대 임계가 아니라 기준선 대비 처짐이 판단
        기준이므로(경보는 drop 기준). meta: label/warn_drop/alarm_drop(참고용, 선은 안 그림)."""
        for key, dq in trend.items():
            if not dq:
                continue
            m = meta.get(key, {})
            label = m.get("label", str(key))
            xs = [t.timestamp() for t, _r, _b in dq]
            ys = [r for _t, r, _b in dq]
            bs = [b if b is not None else float('nan') for _t, _r, b in dq]

            ck = ("r", key)
            item = self._curve_items.get(ck)
            if item is None:
                item = self.p_r.plot(pen=pg.mkPen(self._color_for(ck), width=1.5), name=label)
                self.p_r.setTitle(None)
                self._curve_items[ck] = item
            item.setData(xs, ys)

            bk = ("r_baseline", key)
            bitem = self._curve_items.get(bk)
            if bitem is None:
                bitem = self.p_r.plot(pen=pg.mkPen(self._color_for(ck), width=1.0,
                                                    style=Qt.PenStyle.DotLine))
                self._curve_items[bk] = bitem
            bitem.setData(xs, bs)

    def update_hk_trend(self, trend: dict, meta: dict) -> None:
        """trend: {(profile_id,field_key): deque[(datetime, value)]} — run_vigil가 warn/alarm
        밴드 있는 필드만 이미 걸러 넣는다. meta: label/unit/warn=(lo,hi)/alarm=(lo,hi)."""
        for key, dq in trend.items():
            if not dq:
                continue
            m = meta.get(key, {})
            label = m.get("label", str(key))
            unit = m.get("unit")
            name = f"{label} ({unit})" if unit else label
            xs = [t.timestamp() for t, _v in dq]
            ys = [v for _t, v in dq]

            ck = ("hk", key)
            item = self._curve_items.get(ck)
            if item is None:
                item = self.p_hk.plot(pen=pg.mkPen(self._color_for(ck), width=1.5), name=name)
                self.p_hk.setTitle(None)
                self._curve_items[ck] = item
            item.setData(xs, ys)

            tk = ("hk_thr", key)
            if tk not in self._threshold_items:
                lines = []
                for band, color in ((m.get("warn"), _WARN_COLOR), (m.get("alarm"), _ALARM_COLOR)):
                    if band is None:
                        continue
                    for v in band:
                        if v is not None:
                            line = pg.InfiniteLine(pos=v, angle=0, movable=False,
                                                   pen=pg.mkPen(color, style=Qt.PenStyle.DashLine))
                            self.p_hk.addItem(line)
                            lines.append(line)
                self._threshold_items[tk] = lines

    def log_line(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {text}")
