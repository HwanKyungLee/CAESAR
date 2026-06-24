"""FlowLayout — 폭이 모자라면 자동으로 다음 줄로 흐르는 레이아웃.
툴바 버튼이 창 폭을 넘어 잘리는 것을 막는다(Qt 공식 FlowLayout 예제의 PyQt6 포팅).
"""
from PyQt6.QtWidgets import QLayout, QSizePolicy
from PyQt6.QtCore import Qt, QSize, QRect, QPoint


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        right = rect.right() - m.right()
        line_h = 0
        sp = self.spacing()
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            if x + w > right and line_h > 0:      # 줄바꿈
                x = rect.x() + m.left()
                y = y + line_h + sp
                line_h = 0
            if not test:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = x + w + sp
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()
