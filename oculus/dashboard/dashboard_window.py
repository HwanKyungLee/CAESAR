"""oculus/dashboard/dashboard_window.py — 최소 실시간 대시보드 (설계문서 §6, M0+M1+M2).

M0: 종합 상태 배지(OK/P1/P2/P0) + 파일별 최근 행 시각/지연 + append-only 로그.
M1: 파일별 HK(밴드·포화) 상태 열. M2: 파일별 R(거울) 상태 열. 농도 패널(M3)은 나중에 탭으로.
"""
from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QHeaderView, QLabel, QMainWindow, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from oculus.alert_engine import OK, P0, P1, P2, SKIP

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

_COLUMNS = ["File", "Last row", "Lag (s)", "HK", "R"]


class DashboardWindow(QMainWindow):
    def __init__(self, title: str = "Oculus — Pipeline Health"):
        super().__init__()
        self.setWindowTitle(title)
        self.resize(900, 540)
        self._last_status = None   # P0로의 전이에서만 소리내기 위한 상태 기억

        root = QWidget()
        lay = QVBoxLayout(root)

        self.badge = QLabel("⏳ 초기화 중…")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setStyleSheet(_BADGE_STYLE[SKIP] + " font-size:20px; font-weight:bold; padding:12px;")
        lay.addWidget(self.badge)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (3, 4):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.table, stretch=1)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        self.log.setStyleSheet("font-family:Consolas,monospace; font-size:11px;")
        lay.addWidget(self.log)

        self.setCentralWidget(root)

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
        "hk_status":str|None, "hk_msg":str|None, "r_status":str|None, "r_msg":str|None}}.
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

    def log_line(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {text}")
