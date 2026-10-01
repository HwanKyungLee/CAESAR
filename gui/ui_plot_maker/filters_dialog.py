# -*- coding: utf-8 -*-
"""Plot Maker — 데이터셋 행 필터 대화상자 (D2).

규칙 목록을 보고, 하나씩 켜고 끄고, 조건식 규칙을 더하거나 고친다. Result Lab에서
넘어온 규칙(Hide QC·K·구간)도 같은 목록에 있다. 숨김은 **삭제가 아니다**(헌장 ①) —
규칙을 끄면 행이 돌아오고, 원본 값은 어떤 경우에도 바뀌지 않는다.

조건식은 `core/expr.py`(파생 열과 같은 엔진), 마스크는 `Dataset.rules_mask` 한 곳.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QLabel,
    QPushButton, QComboBox, QLineEdit, QCheckBox, QDialogButtonBox, QGroupBox,
)

from gui.result_viewer_io import describe_rule
from gui.theme import AUGUR

_HELP = ("Keep rows where = only rows meeting the condition stay (NaN comparisons are false → hidden).\n"
         "Hide rows where = rows meeting the condition are hidden.\n"
         'e.g.  Flag == "ok"    ·   (T > 290) & (P < 1020)   ·   (hour >= 9) & (hour < 18)   ·   RMS < 2e-3')


class FiltersDialog(QDialog):
    def __init__(self, ds, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.rules = [dict(r) for r in ds.rules]
        self.setWindowTitle(f"Filters — {ds.name}")
        self.resize(620, 480)
        v = QVBoxLayout(self)

        self._chk_on = QCheckBox("Filters on (uncheck = show everything, rules are kept)")
        self._chk_on.setChecked(ds.rules_on)
        self._chk_on.toggled.connect(self._update_total)
        v.addWidget(self._chk_on)

        v.addWidget(QLabel("Rules (checkbox = on/off · hidden rows are not deleted)"))
        self._list = QListWidget()
        self._list.itemChanged.connect(self._on_item_changed)
        self._list.currentRowChanged.connect(self._on_select)
        v.addWidget(self._list, 1)
        row = QHBoxLayout()
        self._btn_rm = QPushButton("Remove rule")
        self._btn_rm.clicked.connect(self._remove)
        row.addStretch(1)
        row.addWidget(self._btn_rm)
        v.addLayout(row)

        box = QGroupBox("Condition")
        bv = QVBoxLayout(box)
        er = QHBoxLayout()
        self._mode = QComboBox()
        self._mode.addItem("Keep rows where", "keep")
        self._mode.addItem("Hide rows where", "hide")
        self._expr = QLineEdit()
        self._expr.setPlaceholderText('e.g. Flag == "ok"')
        er.addWidget(self._mode)
        er.addWidget(self._expr, 1)
        bv.addLayout(er)
        self._preview = QLabel(" ")
        bv.addWidget(self._preview)
        br = QHBoxLayout()
        self._btn_add = QPushButton("Add as new rule")
        self._btn_upd = QPushButton("Update selected")
        self._btn_add.clicked.connect(lambda: self._commit(new=True))
        self._btn_upd.clicked.connect(lambda: self._commit(new=False))
        br.addStretch(1)
        br.addWidget(self._btn_add)
        br.addWidget(self._btn_upd)
        bv.addLayout(br)
        names = QLabel("Names: " + ", ".join(ds.variables()))
        names.setWordWrap(True)
        names.setStyleSheet(f"color:{AUGUR.faint};")
        bv.addWidget(names)
        hl = QLabel(_HELP)
        hl.setStyleSheet(f"color:{AUGUR.faint};")
        bv.addWidget(hl)
        v.addWidget(box)

        self._total = QLabel(" ")
        v.addWidget(self._total)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        self._timer = QTimer(self, singleShot=True, interval=200)
        self._timer.timeout.connect(self._update_preview)
        self._expr.textChanged.connect(lambda _=None: self._timer.start())
        self._mode.currentIndexChanged.connect(lambda _=None: self._timer.start())
        self._refresh_list()
        self._update_preview()

    # ── 목록 ──────────────────────────────────────────────────────────
    def _refresh_list(self, select=None):
        self._list.blockSignals(True)
        self._list.clear()
        _, errors = self._mask()
        for i, r in enumerate(self.rules):
            text = describe_rule(dict(r, on=True))
            if i in errors:
                text += f"   ✗ {errors[i]}"
            it = QListWidgetItem(text)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if r.get("on", True) else Qt.CheckState.Unchecked)
            if i in errors:
                it.setForeground(Qt.GlobalColor.red)
            self._list.addItem(it)
        self._list.blockSignals(False)
        if select is not None and 0 <= select < self._list.count():
            self._list.setCurrentRow(select)
        self._on_select(self._list.currentRow())
        self._update_total()

    def _on_item_changed(self, it):
        i = self._list.row(it)
        if 0 <= i < len(self.rules):
            self.rules[i]["on"] = it.checkState() == Qt.CheckState.Checked
            self._update_total()

    def _on_select(self, i):
        ok = 0 <= i < len(self.rules)
        self._btn_rm.setEnabled(ok)
        is_expr = ok and self.rules[i].get("kind") == "expr"
        self._btn_upd.setEnabled(is_expr)
        if is_expr:
            r = self.rules[i]
            self._mode.setCurrentIndex(0 if r.get("mode", "keep") == "keep" else 1)
            self._expr.setText(r.get("expr", ""))

    def _remove(self):
        i = self._list.currentRow()
        if 0 <= i < len(self.rules):
            del self.rules[i]
            self._refresh_list(select=min(i, len(self.rules) - 1))

    # ── 조건 편집 ────────────────────────────────────────────────────
    def _draft(self):
        return {"kind": "expr", "expr": self._expr.text().strip(),
                "mode": self._mode.currentData(), "on": True}

    def _update_preview(self):
        """편집 중인 조건 하나만으로 몇 행을 숨기는지(또는 오류)."""
        d = self._draft()
        if not d["expr"]:
            self._preview.setText(" ")
            self._btn_add.setEnabled(False)
            self._btn_upd.setEnabled(False)
            return
        mask, errors = self.ds.rules_mask([d])
        if errors:
            self._preview.setText(f"✗ {errors[0]}")
            self._preview.setStyleSheet(f"color:{AUGUR.fail};")
            self._btn_add.setEnabled(False)
            self._btn_upd.setEnabled(False)
            return
        self._preview.setText(f"✓ this condition alone hides {int(mask.sum())} of {mask.size} rows")
        self._preview.setStyleSheet(f"color:{AUGUR.info};")
        self._btn_add.setEnabled(True)
        i = self._list.currentRow()
        self._btn_upd.setEnabled(0 <= i < len(self.rules) and self.rules[i].get("kind") == "expr")

    def _commit(self, new):
        d = self._draft()
        if not d["expr"]:
            return
        i = self._list.currentRow()
        if new or not (0 <= i < len(self.rules)):
            self.rules.append(d)
            self._refresh_list(select=len(self.rules) - 1)
        else:
            d["on"] = self.rules[i].get("on", True)
            self.rules[i] = d
            self._refresh_list(select=i)

    # ── 합계 ──────────────────────────────────────────────────────────
    def _mask(self):
        return self.ds.rules_mask(self.rules)

    def _update_total(self):
        if not self._chk_on.isChecked():
            self._total.setText("Filters off — all rows shown")
            return
        mask, errors = self._mask()
        bad = f" · ✗ {len(errors)} broken rule(s) hide nothing" if errors else ""
        self._total.setText(f"Total: {int(mask.sum())} of {mask.size} rows hidden{bad}")

    def chosen(self):
        """(규칙 목록, 필터 켬 여부) — QDialog.result()와 이름이 겹치지 않게."""
        return self.rules, self._chk_on.isChecked()
