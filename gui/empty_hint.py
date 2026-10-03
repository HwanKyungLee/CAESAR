"""gui/empty_hint.py — "nothing here yet, here is what fills it" over a blank plot or table (2026-10-03).

A fresh Augur showed empty 0–1 grids and blank tables with no word on what to do next (UX audit
2026-10-02 s5 "first screen is an empty grid", s1/s3 empty states). `attach(widget, text)` puts a
centred, click-through note on the widget and hides it as soon as the widget has data.

What counts as "has data": pyqtgraph widgets — any curve/scatter/image with points; item views —
at least one row. Pass `is_empty=` for anything else.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QAbstractItemView, QAbstractScrollArea, QGraphicsView, QLabel

from gui.theme import AUGUR

CHECK_MS = 1000  # fallback poll; the view repainting (new data) re-checks immediately


def _pg_empty(widget) -> bool:
    import pyqtgraph as pg
    scene = widget.scene() if hasattr(widget, "scene") else None
    if scene is None:
        return True
    for it in scene.items():
        if isinstance(it, (pg.PlotDataItem, pg.PlotCurveItem, pg.ScatterPlotItem)):
            x = getattr(it, "xData", None)
            if x is None and hasattr(it, "getData"):
                x = it.getData()[0]
            if x is not None and len(x):
                return False
        elif isinstance(it, pg.ImageItem) and it.image is not None:
            return False
    return True


def _view_empty(widget) -> bool:
    m = widget.model()
    return m is None or m.rowCount() == 0


class _Hint(QObject):
    def __init__(self, widget, text, is_empty, color=None):
        super().__init__(widget)
        self.w = widget
        self.is_empty = is_empty
        # tables and pyqtgraph views (QGraphicsView) paint in their viewport — watch that, or new
        # data never triggers the immediate re-check and the note sat on the data until the poll
        host = widget.viewport() if isinstance(widget, QAbstractScrollArea) else widget
        self.label = QLabel(text, host)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.color = color or AUGUR.muted
        # an empty plot is covered whole, in its own background colour: the bare 0–1 axes and
        # grid filled most of the first screen (UX re-evaluation 2026-10-03 s5)
        self.cover = isinstance(widget, QGraphicsView)
        self.host = host
        host.installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(CHECK_MS)
        self._place()
        self.refresh()

    def _place(self):
        r = self.host.rect()
        if self.cover:
            bg = self.w.backgroundBrush().color().name()
            side = max(12, int(r.width() * 0.2))
            self.label.setStyleSheet(f"color: {self.color}; background: {bg}; padding: 12px {side}px;")
            self.label.setMinimumWidth(0)
            self.label.setMaximumWidth(16777215)
            self.label.setGeometry(r)
            return
        self.label.setStyleSheet(f"color: {self.color}; background: transparent; padding: 12px;")
        w = min(r.width() - 24, max(260, int(r.width() * 0.6)))
        self.label.setFixedWidth(max(w, 1))
        self.label.adjustSize()
        self.label.move((r.width() - self.label.width()) // 2, (r.height() - self.label.height()) // 2)

    def eventFilter(self, obj, ev):
        if obj is self.host:
            t = ev.type()
            if t == QEvent.Type.Resize:
                self._place()
            elif t == QEvent.Type.Paint and (not self.label.isHidden()):
                # new data repaints the view — hide at once instead of waiting for the timer
                QTimer.singleShot(0, self.refresh)
        return False

    def refresh(self):
        try:
            empty = bool(self.is_empty(self.w))
        except Exception:      # noqa: BLE001 — a hint must never break the view it sits on
            empty = False
        if empty != (not self.label.isHidden()):
            self.label.setVisible(empty)
            if empty:
                self._place()
                self.label.raise_()


def attach(widget, text: str, is_empty=None, color=None):
    """Show `text` centred on `widget` while it has no data. Returns the hint (keep or ignore).
    `color` = text colour (default Augur muted; Vigil passes its own)."""
    if is_empty is None:
        is_empty = _view_empty if isinstance(widget, QAbstractItemView) else _pg_empty
    return _Hint(widget, text, is_empty, color)
