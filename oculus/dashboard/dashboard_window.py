"""oculus/dashboard/dashboard_window.py — 최소 실시간 대시보드 (설계문서 §6, M0).

M0 범위: 종합 상태 배지(OK/P0) + 감시 중인 파일별 최근 행 시각/지연 + append-only
로그 패널. HK/R/농도 패널(M1~M3)은 이 창에 나중에 탭으로 추가한다 — 지금은
"지금 raw가 들어오고 있는가"만 본다(§1.4가 나머지 셋의 전제라 가장 먼저 필요).
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

from oculus.liveness_monitor import OK, P0, SKIP

_BADGE_STYLE = {
    OK:   "background:#2E7D32; color:white;",
    P0:   "background:#C62828; color:white;",
    SKIP: "background:#78909C; color:white;",
}
_BADGE_ICON = {OK: "🟢", P0: "🔴", SKIP: "⏳"}


class DashboardWindow(QMainWindow):
    def __init__(self, title: str = "Oculus — Pipeline Liveness"):
        super().__init__()
        self.setWindowTitle(title)
        self.resize(760, 520)
        self._last_status = None   # OK→P0 전이에서만 소리내기 위한 상태 기억

        root = QWidget()
        lay = QVBoxLayout(root)

        self.badge = QLabel("⏳ 초기화 중…")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setStyleSheet(_BADGE_STYLE[SKIP] + " font-size:20px; font-weight:bold; padding:12px;")
        lay.addWidget(self.badge)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["File", "Last row", "Lag (s)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
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
    def set_liveness(self, status: str, msg: str) -> None:
        self.badge.setText(f"{_BADGE_ICON.get(status, '?')} {msg}")
        self.badge.setStyleSheet(
            _BADGE_STYLE.get(status, _BADGE_STYLE[SKIP])
            + " font-size:20px; font-weight:bold; padding:12px;")
        if status == P0 and self._last_status != P0:
            QApplication.beep()   # OK/SKIP → P0 전이 순간에만 (매 tick 울리지 않게)
        self._last_status = status

    def update_files(self, rows: dict) -> None:
        """rows: {file_path: (last_row_time: datetime|None, lag_sec: float|None)}"""
        self.table.setRowCount(len(rows))
        for i, (path, (last_row, lag)) in enumerate(sorted(rows.items())):
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(path)))
            last_str = last_row.strftime("%H:%M:%S") if last_row else "—"
            self.table.setItem(i, 1, QTableWidgetItem(last_str))
            lag_str = f"{lag:.1f}" if lag is not None else "—"
            item = QTableWidgetItem(lag_str)
            if lag is not None and lag > 10.0:
                item.setForeground(QColor("red"))
            self.table.setItem(i, 2, item)

    def log_line(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {text}")
