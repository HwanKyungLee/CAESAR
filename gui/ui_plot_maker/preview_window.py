# -*- coding: utf-8 -*-
"""Plot Maker — 모덜리스 Publish 미리보기 (M-P).

전엔 모덜 다이얼로그(`exec()`)라 띄워두고 고칠 수 없었다. 이제 옆에 띄워두면 설정을
바꿀 때마다 **최종 출력물 그대로** 다시 그린다 — Publish와 같은 함수(`_build_publish_fig`)라
미리보기 = 저장 파일이다. 조판(M2)의 전제이기도 하다.

갱신 규칙: 화면을 바꾸는 경로가 수십 곳이라 거기마다 훅을 걸지 않는다. 대신 짧은 주기로
그림을 재현하는 상태 전부의 지문(`host.preview_signature()`)을 보고, **바뀐 뒤 한 박자 동안
그대로면** 다시 그린다 — 타이핑 중에는 안 그리고, 빠뜨리는 경로도 없다.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QCheckBox, QPushButton,
)

from gui.theme import AUGUR


class PreviewWindow(QDialog):
    TICK_MS = 500

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setModal(False)
        self.setWindowTitle("Publish preview — exactly as output (save with Publish)")
        self.n_renders = 0
        self._last_sig = None      # 마지막으로 그린 지문
        self._pending = None       # 바뀌었지만 아직 안정 안 된 지문
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        self._chk_auto = QCheckBox("Auto-refresh")
        self._chk_auto.setChecked(True)
        self._chk_auto.setToolTip("Redraw whenever the plot settings change (after a short pause).")
        b = QPushButton("Refresh")
        b.clicked.connect(self.refresh)
        self._info = QLabel(" ")
        self._info.setStyleSheet(f"color:{AUGUR.sub};")
        bar.addWidget(self._chk_auto)
        bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self._info)
        v.addLayout(bar)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        self._lbl = QLabel()
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sa.setWidget(self._lbl)
        v.addWidget(sa, 1)
        self._timer = QTimer(self, interval=self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        if not (self.isVisible() and self._chk_auto.isChecked()):
            return
        try:
            sig = self.host.preview_signature()
        except Exception:
            return
        if sig == self._last_sig:
            self._pending = None
            return
        if sig != self._pending:       # 방금 바뀜 — 한 박자 더 기다린다(타이핑 중)
            self._pending = sig
            return
        self.refresh(sig)

    def refresh(self, sig=None):
        t0 = time.perf_counter()
        try:
            png = self.host.render_preview_png()
        except NotImplementedError:
            self._show_msg("This mode does not support high-res output yet.", AUGUR.warn)
            return
        except Exception as e:          # 자동 갱신 중 오류는 창 안에 — 팝업 폭탄 금지
            self._show_msg(f"✗ {type(e).__name__}: {e}", AUGUR.fail)
            self._last_sig = sig or self._safe_sig()
            return
        self._last_sig = sig or self._safe_sig()
        self._pending = None
        if png is None:
            self._show_msg("Nothing to draw.", AUGUR.sub)
            return
        pix = QPixmap()
        pix.loadFromData(png, "PNG")
        self._lbl.setPixmap(pix)
        self.n_renders += 1
        first = self.n_renders == 1
        self._info.setText(f"rendered {time.strftime('%H:%M:%S')} · {time.perf_counter() - t0:.2f} s")
        self._info.setStyleSheet(f"color:{AUGUR.sub};")
        if first:
            self.resize(min(pix.width() + 40, 1280), min(pix.height() + 90, 860))

    def _safe_sig(self):
        try:
            return self.host.preview_signature()
        except Exception:
            return None

    def _show_msg(self, text, color):
        self._info.setText(text)
        self._info.setStyleSheet(f"color:{color};")
