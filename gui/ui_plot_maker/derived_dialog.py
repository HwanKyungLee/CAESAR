# -*- coding: utf-8 -*-
"""Plot Maker — 파생 열 대화상자 (D1).

`이름 = 식`을 입력하면 그 자리에서 평가해 결과 요약(유효 개수·범위)이나 오류를
보여준다. 저장되는 건 **식**이다 — 값은 데이터셋을 열 때마다 다시 계산된다
(`Dataset.apply_derived`). 식 엔진은 `core/expr.py` 하나(Result Lab 계산기와 공유).
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QLabel, QListWidget,
    QDialogButtonBox,
)
from PyQt6.QtCore import QTimer

from gui.theme import AUGUR

_EXAMPLES = (
    "Examples\n"
    "  NO2 * 1.88                      unit conversion (ppb → µg/m³ at 25 °C)\n"
    "  NO2 / O3                        ratio\n"
    "  NO2 - mean(NO2)                 anomaly\n"
    "  where(Flag == \"ok\", NO2, nan)    keep only ok-flagged rows\n"
    "  where((hour >= 9) & (hour < 18), NO2, nan)\n"
    "Operators: + - * / **  < <= > >= == !=  & | ~   (use parentheses with & |)\n"
    "Functions: abs sqrt log log10 exp where isfinite isnan clip minimum maximum mean median std\n"
    "Names: columns of this dataset, Status/Flag/Channel, time (epoch s), hour (local, 0–24).\n"
    "Columns with odd names: col(\"name\")"
)


class DerivedColumnDialog(QDialog):
    """ds: 대상 Dataset. editing: 편집 중인 파생 열 이름(새로 만들면 None)."""

    def __init__(self, ds, editing=None, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.editing = editing
        self._idx = ds.derived_names().index(editing) if editing else None
        cur = ds.derived[self._idx] if editing else {}
        self.setWindowTitle(f"{'Edit' if editing else 'New'} column — {ds.name}")
        self.resize(560, 520)
        v = QVBoxLayout(self)

        form = QFormLayout()
        self._name = QLineEdit(cur.get("name", ""))
        self._name.setPlaceholderText("e.g. NO2_ugm3")
        self._expr = QLineEdit(cur.get("expr", ""))
        self._expr.setPlaceholderText("e.g. NO2 * 1.88")
        self._unit = QLineEdit(cur.get("unit", "") or "")
        self._unit.setPlaceholderText("optional, e.g. $\\mu$g m$^{-3}$")
        form.addRow("Name", self._name)
        form.addRow("Expression", self._expr)
        form.addRow("Unit", self._unit)
        v.addLayout(form)

        self._msg = QLabel(" ")
        self._msg.setWordWrap(True)
        v.addWidget(self._msg)

        v.addWidget(QLabel("Available names (double-click to insert)"))
        self._vars = QListWidget()
        for k in self._var_names():
            self._vars.addItem(k)
        self._vars.itemDoubleClicked.connect(self._insert_var)
        v.addWidget(self._vars, 1)

        ex = QLabel(_EXAMPLES)
        ex.setStyleSheet(f"color:{AUGUR.faint}; font-family: Consolas, monospace; font-size: 9pt;")
        v.addWidget(ex)

        self._bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                    | QDialogButtonBox.StandardButton.Cancel)
        self._bb.accepted.connect(self.accept)
        self._bb.rejected.connect(self.reject)
        v.addWidget(self._bb)

        # 타이핑마다 평가하면 큰 데이터셋에서 버벅인다 → 짧게 모아서 한 번
        self._timer = QTimer(self, singleShot=True, interval=200)
        self._timer.timeout.connect(self._validate)
        for ed in (self._name, self._expr):
            ed.textChanged.connect(lambda _=None: self._timer.start())
        self._validate()

    def _var_names(self):
        return list(self.ds.variables(upto=self._idx))

    def _insert_var(self, item):
        name = item.text()
        token = name if name.isidentifier() else f'col("{name}")'
        self._expr.insert(token)
        self._expr.setFocus()

    def evaluate(self):
        """(값 ndarray | None, 오류문 | None)."""
        from core.expr import eval_column
        err = self.ds.check_derived_name(self._name.text(), editing=self.editing)
        if err:
            return None, err
        try:
            return eval_column(self._expr.text(), self.ds.variables(upto=self._idx),
                               self.ds.n_rows()), None
        except Exception as e:
            return None, str(e)

    def _validate(self):
        y, err = self.evaluate()
        ok_btn = self._bb.button(QDialogButtonBox.StandardButton.Ok)
        if err:
            self._msg.setText(f"✗ {err}")
            self._msg.setStyleSheet(f"color:{AUGUR.fail};")
            ok_btn.setEnabled(False)
            return
        fin = y[np.isfinite(y)]
        rng = f" · range {fin.min():.4g} … {fin.max():.4g}" if fin.size else ""
        self._msg.setText(f"✓ {fin.size} finite of {y.size} rows{rng}")
        self._msg.setStyleSheet(f"color:{AUGUR.info};")
        ok_btn.setEnabled(True)

    def spec(self):
        d = {"name": self._name.text().strip(), "expr": self._expr.text().strip()}
        if self._unit.text().strip():
            d["unit"] = self._unit.text().strip()
        return d
