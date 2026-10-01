"""gui/dlg_calculator.py — Result Lab 데이터 계산기 (다단계 수식).

여러 결과파일의 컬럼을 변수(A,B,C…)에 매핑하고 `(A-B)/C` 같은 수식을 안전하게
평가해 새 시계열을 만든다. 교차-데이터셋이면 기준 변수의 시각격자에 보간 정렬한다.
미리보기 그래프 + CSV 저장. (NO2/PNs/ANs 채널차분 = 이 계산기의 특수케이스: B-A 등)

경계: 컬럼 연산이 '의미 있는 새 값'을 만들어 저장 → Result Lab 영역(Plot Maker는 그림만).
안전성: eval() 안 씀. ast 화이트리스트로 +−×÷**·괄호·소수의 함수만 허용.
"""
import os

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QMessageBox, QFileDialog, QWidget,
)
from PyQt6.QtCore import Qt

from core.align import align_to   # 단일 출처 — Plot Maker 정렬과 같은 결손 가드
from core.expr import safe_eval   # 단일 출처 — Plot Maker 파생 열과 같은 엔진
from gui.result_viewer_io import load_fit_table
from gui.theme import AUGUR

_VAR_LETTERS = "ABCDEFGH"


class CalculatorDialog(QDialog):
    """결과 데이터 계산기. datasets: [경로,...] (Result Lab에서 로드된 파일들)."""

    def __init__(self, parent=None, datasets=None):
        super().__init__(parent)
        self.setWindowTitle("Data Calculator — multi-step expressions")
        self.resize(940, 560)
        self._tables = {}          # path -> load_fit_table 결과(캐시)
        self._paths = list(datasets or [])
        self._var_rows = []        # [(letter_lbl, ds_combo, col_combo, rm_btn)]
        self._result = None        # (t_epoch, values, name)

        root = QHBoxLayout(self)

        # ── 좌: 입력 ─────────────────────────────────────────────
        left = QVBoxLayout()
        root.addLayout(left, 3)

        btnbar = QHBoxLayout()
        b_add_ds = QPushButton("Add file…")
        b_add_ds.clicked.connect(self._add_dataset_file)
        btnbar.addWidget(b_add_ds)
        btnbar.addWidget(QLabel("Map variables to (file, column), then write an expression below"))
        btnbar.addStretch(1)
        left.addLayout(btnbar)

        self._vgrid = QGridLayout()
        self._vgrid.addWidget(QLabel("<b>Var</b>"), 0, 0)
        self._vgrid.addWidget(QLabel("<b>File</b>"), 0, 1)
        self._vgrid.addWidget(QLabel("<b>Column</b>"), 0, 2)
        _vw = QWidget(); _vw.setLayout(self._vgrid)
        left.addWidget(_vw)

        b_add_var = QPushButton("+ Add variable")
        b_add_var.clicked.connect(self._add_var_row)
        left.addWidget(b_add_var, alignment=Qt.AlignmentFlag.AlignLeft)

        exprbar = QHBoxLayout()
        exprbar.addWidget(QLabel("Expression:"))
        self._expr = QLineEdit("A - B")
        self._expr.setToolTip("e.g. A-B,  (A-B)/C,  A*2+B,  sqrt(abs(A)),  A/C*100\n"
                              "Allowed: + - * / **, parentheses, numbers, comparisons < > ==, & | ~,\n"
                              "abs/sqrt/log/log10/exp/where/isfinite/clip/mean/median/std  (core/expr.py)")
        exprbar.addWidget(self._expr, 1)
        left.addLayout(exprbar)

        refbar = QHBoxLayout()
        refbar.addWidget(QLabel("Align time to:"))
        self._ref = QComboBox()
        self._ref.setToolTip("For cross-dataset expressions, interpolate all variables onto this variable's time grid")
        refbar.addWidget(self._ref)
        refbar.addWidget(QLabel("   Result name:"))
        self._name = QLineEdit("result")
        refbar.addWidget(self._name, 1)
        left.addLayout(refbar)

        actbar = QHBoxLayout()
        b_calc = QPushButton("▶ Compute")
        b_calc.setStyleSheet(f"font-weight:bold; background:{AUGUR.info}; color:white; padding:4px;")
        b_calc.clicked.connect(self._compute)
        b_save = QPushButton("Save CSV")
        b_save.clicked.connect(self._save_csv)
        actbar.addWidget(b_calc)
        actbar.addWidget(b_save)
        actbar.addStretch(1)
        left.addLayout(actbar)

        self._msg = QLabel("")
        self._msg.setWordWrap(True)
        self._msg.setStyleSheet(f"color:{AUGUR.muted};")
        left.addWidget(self._msg)
        left.addStretch(1)

        # ── 우: 미리보기 그래프 ──────────────────────────────────
        right = QVBoxLayout()
        root.addLayout(right, 4)
        right.addWidget(QLabel("Preview"))
        self._pw = pg.PlotWidget()
        self._pw.setBackground("w")
        self._pw.showGrid(x=True, y=True, alpha=0.3)
        self._pw.setAxisItems({"bottom": pg.DateAxisItem(orientation="bottom")})
        right.addWidget(self._pw, 1)

        # 초기 변수 2개(A,B)
        self._add_var_row()
        self._add_var_row()

    def showEvent(self, e):
        """다이얼로그가 실제로 보일 때(위젯 realize 후) 빈 컬럼 콤보를 채운다.
        생성 시점엔 콤보가 아직 realize 안 돼 init 채우기가 빈 결과를 받는 경우가
        있어(Windows) — 여기서 보강하면 첫 화면부터 컬럼이 보장된다."""
        super().showEvent(e)
        for _lbl, ds, col, _rm in self._var_rows:
            if col.count() == 0 and ds.currentData():
                self._fill_cols(ds, col)

    # ── 데이터셋/컬럼 ─────────────────────────────────────────
    def _basenames(self):
        return [os.path.basename(p) for p in self._paths]

    def _table(self, path):
        if path not in self._tables:
            self._tables[path] = load_fit_table(path)
        return self._tables[path]

    def _columns(self, path):
        try:
            t = self._table(path)
        except Exception as e:
            self._last_col_err = f"{os.path.basename(path)}: {e}"
            return []
        self._last_col_err = ""
        cols = list(t.get("gases", {}).keys())
        if t.get("rms") is not None:
            cols.append("RMS")
        if not cols:
            self._last_col_err = f"{os.path.basename(path)}: no gas columns (not a fit result?)"
        return cols

    def _add_dataset_file(self):
        try:
            from gui.dlg_dir import dlg_dir
            start = dlg_dir("result")
        except Exception:
            start = ""
        p, _ = QFileDialog.getOpenFileName(self, "Add result file", start,
                                           "Results (*.dat *.csv *.tsv *.txt);;All Files (*)")
        if not p:
            return
        try:
            from gui.dlg_dir import dlg_dir
            dlg_dir("result", p)
        except Exception:
            pass
        if p not in self._paths:
            self._paths.append(p)
        for _, ds, _c, _b in self._var_rows:
            self._refresh_ds_combo(ds)

    def _refresh_ds_combo(self, combo):
        cur = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for p in self._paths:
            combo.addItem(os.path.basename(p), p)
        if cur in self._paths:
            combo.setCurrentIndex(self._paths.index(cur))
        combo.blockSignals(False)

    def _add_var_row(self):
        if len(self._var_rows) >= len(_VAR_LETTERS):
            return
        letter = _VAR_LETTERS[len(self._var_rows)]
        row = self._vgrid.rowCount()
        lbl = QLabel(f"<b>{letter}</b>")
        ds = QComboBox()
        for p in self._paths:
            ds.addItem(os.path.basename(p), p)
        col = QComboBox()
        ds.currentIndexChanged.connect(lambda *_a, d=ds, c=col: self._fill_cols(d, c))
        rm = QPushButton("−"); rm.setFixedWidth(26)
        rm.clicked.connect(lambda *_a: self._remove_var_row(letter))
        self._vgrid.addWidget(lbl, row, 0)
        self._vgrid.addWidget(ds,  row, 1)
        self._vgrid.addWidget(col, row, 2)
        self._vgrid.addWidget(rm,  row, 3)
        self._var_rows.append((lbl, ds, col, rm))
        self._fill_cols(ds, col)
        self._refresh_ref()

    def _remove_var_row(self, letter):
        # 마지막 변수만 제거(인덱스↔글자 단순 유지). 최소 1개는 남긴다.
        if len(self._var_rows) <= 1:
            return
        lbl, ds, col, rm = self._var_rows.pop()
        for w in (lbl, ds, col, rm):
            self._vgrid.removeWidget(w); w.deleteLater()
        self._refresh_ref()

    def _fill_cols(self, ds_combo, col_combo):
        path = ds_combo.currentData()
        self._last_col_err = ""
        cols = self._columns(path) if path else []
        col_combo.blockSignals(True)
        col_combo.clear()
        if cols:
            col_combo.addItems(cols)
        col_combo.blockSignals(False)
        if path and not cols and getattr(self, "_last_col_err", "") and hasattr(self, "_msg"):
            self._msg.setText(f"{self._last_col_err}")
            self._msg.setStyleSheet(f"color:{AUGUR.fail};")

    def _refresh_ref(self):
        cur = self._ref.currentText()
        self._ref.blockSignals(True)
        self._ref.clear()
        self._ref.addItems([_VAR_LETTERS[i] for i in range(len(self._var_rows))])
        i = self._ref.findText(cur)
        self._ref.setCurrentIndex(i if i >= 0 else 0)
        self._ref.blockSignals(False)

    # ── 계산 ─────────────────────────────────────────────────
    def _gather(self):
        """변수별 (time, value) 로드. 반환 (vars_raw{letter:(t,v)}, ref_letter)."""
        vars_raw = {}
        for i, (_lbl, ds, col, _rm) in enumerate(self._var_rows):
            letter = _VAR_LETTERS[i]
            path = ds.currentData()
            cname = col.currentText()
            if not path or not cname:
                continue
            t = self._table(path)
            tt = t.get("time")
            if tt is None:
                raise ValueError(f"{letter}: '{os.path.basename(path)}' has no Time column; cannot align")
            vv = t["rms"] if cname == "RMS" else t["gases"].get(cname)
            if vv is None:
                raise ValueError(f"{letter}: column '{cname}' not found")
            tt = np.asarray(tt, float); vv = np.asarray(vv, float)
            m = np.isfinite(tt)
            o = np.argsort(tt[m])
            vars_raw[letter] = (tt[m][o], vv[m][o])
        if not vars_raw:
            raise ValueError("Assign at least one variable (file · column).")
        return vars_raw, (self._ref.currentText() or next(iter(vars_raw)))

    def _compute(self):
        try:
            vars_raw, ref = self._gather()
            if ref not in vars_raw:
                ref = next(iter(vars_raw))
            ref_t, _ = vars_raw[ref]
            # 모든 변수를 기준 시각격자에 정렬(범위 밖·결손 구간 NaN). 같은 격자면 그대로.
            # core.align 단일 출처 — 예전 np.interp는 결손을 가로질러 직선으로 메웠다.
            aligned, n_gap = {}, 0
            for letter, (tt, vv) in vars_raw.items():
                if np.array_equal(tt, ref_t):
                    aligned[letter] = vv
                else:
                    aligned[letter], info = align_to(ref_t, tt, vv)
                    n_gap += info["n_gap"]
            expr = self._expr.text().strip()
            if not expr:
                raise ValueError("Enter an expression.")
            res = safe_eval(expr, aligned)
            res = np.asarray(res, float) * np.ones_like(ref_t)  # 스칼라 결과 방어
        except Exception as e:
            self._msg.setText(f"{e}")
            self._msg.setStyleSheet(f"color:{AUGUR.fail};")
            return

        self._result = (ref_t, res, self._name.text().strip() or "result")
        finite = np.isfinite(res)
        self._pw.clear()
        self._pw.addLegend(offset=(10, 10))
        if finite.any():
            self._pw.plot(ref_t[finite], res[finite],
                          pen=pg.mkPen("#1565C0", width=2), name=self._result[2])
        n_ok = int(finite.sum())
        self._msg.setText(
            f"{expr}  →  n={n_ok}/{len(res)} finite, "
            f"min={np.nanmin(res):.4g}  max={np.nanmax(res):.4g}  "
            f"mean={np.nanmean(res):.4g}   (aligned to {ref}"
            + (f"; {n_gap} points not bridged across data gaps)" if n_gap else ")"))
        self._msg.setStyleSheet(f"color:{AUGUR.ok};")

    def _save_csv(self):
        if not self._result:
            QMessageBox.information(self, "Save", "Run ▶ Compute first.")
            return
        t, v, name = self._result
        try:
            from gui.dlg_dir import dlg_dir
            start = dlg_dir("result")
        except Exception:
            start = ""
        out, _ = QFileDialog.getSaveFileName(self, "Save result CSV",
                                             os.path.join(start or "", f"{name}.csv"),
                                             "CSV (*.csv)")
        if not out:
            return
        if not out.lower().endswith(".csv"):
            out += ".csv"
        import datetime as _dt
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(f"# Data Calculator result: {name} = {self._expr.text().strip()}\n")
                f.write(f"# aligned to {self._ref.currentText()} time grid; "
                        f"{int(np.isfinite(v).sum())}/{len(v)} finite\n")
                f.write(f"time,{name}\n")
                for ti, vi in zip(t, v):
                    ts = _dt.datetime.fromtimestamp(ti).strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"{ts},{vi:.8g}\n")
            QMessageBox.information(self, "Saved", f"Saved:\n{out}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))
