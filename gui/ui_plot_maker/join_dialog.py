# -*- coding: utf-8 -*-
"""Plot Maker — Join 대화상자 (D1+).

두 데이터셋을 base 시간축 하나로 맞춘 가상 데이터셋을 만든다. 그러면 Hot−Cold 차이,
두 기기 비교 같은 **데이터셋 간 계산**을 파생 열(`NO2 - NO2_B`)로 할 수 있다.
저장되는 건 레시피(재료 이름·방법·최대 간격)이고, 재료가 바뀌면 다시 만들어진다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QLineEdit, QLabel, QDialogButtonBox,
    QDoubleSpinBox, QCheckBox, QHBoxLayout, QWidget,
)
from PyQt6.QtCore import QTimer

from gui.theme import AUGUR
from .data import JOIN_METHODS, build_join


class JoinDialog(QDialog):
    def __init__(self, base_name, shelf, parent=None):
        super().__init__(parent)
        self.base = base_name
        self.shelf = shelf
        self.setWindowTitle(f"Join — {base_name} ⋈ …")
        self.resize(520, 260)
        form = QFormLayout(self)

        form.addRow("Base (time axis)", QLabel(base_name))
        self._other = QComboBox()
        for n, ds in shelf.items():
            if n != base_name and ds.time is not None:
                self._other.addItem(n)
        form.addRow("Join with", self._other)
        self._suffix = QLineEdit("_B")
        self._suffix.setToolTip("Columns of the joined dataset get this suffix: NO2 → NO2_B")
        form.addRow("Column suffix", self._suffix)
        self._method = QComboBox()
        self._method.addItems(JOIN_METHODS)
        self._method.setToolTip("linear = interpolate between the two surrounding samples\n"
                                "nearest = take the closest sample")
        form.addRow("Method", self._method)

        gw = QWidget(); gl = QHBoxLayout(gw); gl.setContentsMargins(0, 0, 0, 0)
        self._auto = QCheckBox("auto")
        self._auto.setChecked(True)
        self._auto.setToolTip("auto = median sampling interval of the joined dataset × 2.8\n"
                              "(the same 'continuous gap' factor as core/day_audit)")
        self._gap = QDoubleSpinBox()
        self._gap.setRange(0.01, 1e6); self._gap.setDecimals(2); self._gap.setValue(10.0)
        self._gap.setSuffix(" min"); self._gap.setEnabled(False)
        self._auto.toggled.connect(lambda on: self._gap.setEnabled(not on))
        gl.addWidget(self._auto); gl.addWidget(self._gap, 1)
        form.addRow("Max gap", gw)

        self._msg = QLabel(" ")
        self._msg.setWordWrap(True)
        form.addRow(self._msg)
        hint = QLabel("Values are never bridged across a gap longer than Max gap — those rows stay empty.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{AUGUR.faint};")
        form.addRow(hint)
        self._bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                    | QDialogButtonBox.StandardButton.Cancel)
        self._bb.accepted.connect(self.accept)
        self._bb.rejected.connect(self.reject)
        form.addRow(self._bb)

        self._timer = QTimer(self, singleShot=True, interval=150)
        self._timer.timeout.connect(self._preview)
        for sig in (self._other.currentIndexChanged, self._method.currentIndexChanged,
                    self._auto.toggled, self._gap.valueChanged, self._suffix.textChanged):
            sig.connect(lambda *_: self._timer.start())
        self._preview()

    def spec(self):
        return {"base": self.base, "other": self._other.currentText(),
                "suffix": self._suffix.text().strip() or "_B",
                "method": self._method.currentText(),
                "max_gap_s": None if self._auto.isChecked() else self._gap.value() * 60.0}

    def _preview(self):
        ok = self._bb.button(QDialogButtonBox.StandardButton.Ok)
        if not self._other.currentText():
            self._msg.setText("✗ No other dataset with a time axis on the shelf.")
            self._msg.setStyleSheet(f"color:{AUGUR.fail};")
            ok.setEnabled(False)
            return
        try:
            *_, info = build_join(self.spec(), self.shelf)
        except ValueError as e:
            self._msg.setText(f"✗ {e}")
            self._msg.setStyleSheet(f"color:{AUGUR.fail};")
            ok.setEnabled(False)
            return
        gap = info["max_gap_s"]
        self._msg.setText(
            f"✓ {info['matched']} of {info['rows']} base rows get a value"
            f" · {info['n_gap']} left empty by the gap guard"
            f" (max gap {gap / 60:.3g} min)")
        self._msg.setStyleSheet(f"color:{AUGUR.info};")
        ok.setEnabled(True)
