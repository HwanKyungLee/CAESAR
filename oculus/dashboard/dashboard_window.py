"""oculus/dashboard/dashboard_window.py — 최소 실시간 대시보드 (설계문서 §6, M0+M1+M2+M3).

M0: 종합 상태 배지(OK/P1/P2/P0) + 파일별 최근 행 시각/지연 + append-only 로그.
M1: 파일별 HK(밴드·포화) 상태 열 + HK 필드 추세 그래프. M2: 파일별 R(거울) 상태 열 + R 추세
그래프. M3: 파일별 농도 상태 열 + 전 레퍼런스 가스 농도 추세 그래프.
"""
from __future__ import annotations

import os
from datetime import datetime

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QGridLayout, QHeaderView, QLabel, QMainWindow, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from oculus.alert_engine import OK, P0, P1, P2, SKIP

pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')

_BADGE_STYLE = {
    OK:   "background:#2E7D32; color:white;",
    P2:   "background:#F9A825; color:black;",
    P1:   "background:#E65100; color:white;",
    P0:   "background:#C62828; color:white;",
    SKIP: "background:#78909C; color:white;",
}
_BADGE_ICON = {OK: "🟢", P2: "🟡", P1: "🟠", P0: "🔴", SKIP: "⏳"}
_CELL_COLOR = {OK: None, P2: QColor("#B36B00"), P1: QColor("#E65100"),
              P0: QColor("red"), SKIP: None}

_COLUMNS = ["File", "Last row", "Lag (s)", "HK", "R", "Conc"]

# 채널/가스/HK필드 커브에 순환 배정하는 정성 팔레트(gui/monitor_widget.py의 3채널 팔레트보다
# 종류가 많아야 함 — 레퍼런스 가스 수가 FitSet마다 다르므로).
_PALETTE = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
           '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
_WARN_COLOR = '#F9A825'
_ALARM_COLOR = '#C62828'


class DashboardWindow(QMainWindow):
    def __init__(self, title: str = "Oculus — Pipeline Health"):
        super().__init__()
        self.setWindowTitle(title)
        self.resize(1280, 800)
        self._last_status = None   # P0로의 전이에서만 소리내기 위한 상태 기억
        self._curve_items: dict = {}      # 커브 캐시(키→PlotDataItem) — 매 tick 재생성 방지(깜빡임)
        self._threshold_items: dict = {}  # 임계선 캐시(키→[InfiniteLine,...]) — 1회만 그림
        self._color_idx = 0
        self._color_of: dict = {}         # 커브 키→배정된 팔레트 색(관련 커브끼리 색 재사용용)

        root = QWidget()
        lay = QVBoxLayout(root)

        self.badge = QLabel("⏳ 초기화 중…")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setStyleSheet(_BADGE_STYLE[SKIP] + " font-size:20px; font-weight:bold; padding:12px;")
        lay.addWidget(self.badge)

        grid = QGridLayout()
        lay.addLayout(grid, stretch=1)

        self.p_conc = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem(orientation='bottom')})
        self.p_conc.setLabel('left', 'Concentration (ppb)')
        self.p_conc.addLegend(offset=(10, 10))
        self.p_conc.showGrid(x=True, y=True, alpha=0.2)
        grid.addWidget(self.p_conc, 0, 0)

        self.p_r = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem(orientation='bottom')})
        self.p_r.setLabel('left', 'R')
        self.p_r.addLegend(offset=(10, 10))
        self.p_r.showGrid(x=True, y=True, alpha=0.2)
        grid.addWidget(self.p_r, 0, 1)

        self.p_hk = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem(orientation='bottom')})
        self.p_hk.setLabel('left', 'HK')
        self.p_hk.addLegend(offset=(10, 10))
        self.p_hk.showGrid(x=True, y=True, alpha=0.2)
        grid.addWidget(self.p_hk, 1, 0)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (3, 4, 5):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        self.log.setStyleSheet("font-family:Consolas,monospace; font-size:11px;")

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

    # ── 공개 API — run_oculus의 poll 루프가 매 tick 호출 ─────────────────
    def set_status(self, status: str, msg: str) -> None:
        """종합 상태 배지 갱신(liveness + HK + R 등 전체 aggregate 결과)."""
        self.badge.setText(f"{_BADGE_ICON.get(status, '?')} {msg}")
        self.badge.setStyleSheet(
            _BADGE_STYLE.get(status, _BADGE_STYLE[SKIP])
            + " font-size:20px; font-weight:bold; padding:12px;")
        if status == P0 and self._last_status != P0:
            QApplication.beep()   # P0로의 전이 순간에만 (매 tick 울리지 않게)
        self._last_status = status

    def _status_item(self, status, msg) -> QTableWidgetItem:
        item = QTableWidgetItem(f"{_BADGE_ICON.get(status, '⏳')} {msg or '—'}")
        color = _CELL_COLOR.get(status)
        if color is not None:
            item.setForeground(color)
        return item

    def update_files(self, rows: dict) -> None:
        """rows: {file_path: {"last_row":datetime|None, "lag":float|None,
        "hk_status":str|None, "hk_msg":str|None, "r_status":str|None, "r_msg":str|None,
        "conc_status":str|None, "conc_msg":str|None}}.
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
                lag_item.setForeground(QColor("red"))
            self.table.setItem(i, 2, lag_item)
            self.table.setItem(i, 3, self._status_item(info.get("hk_status"), info.get("hk_msg")))
            self.table.setItem(i, 4, self._status_item(info.get("r_status"), info.get("r_msg")))
            self.table.setItem(i, 5, self._status_item(info.get("conc_status"), info.get("conc_msg")))

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
        """trend: {(profile_id,field_key): deque[(datetime, value)]} — run_oculus가 warn/alarm
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
