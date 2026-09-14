"""gui/dlg_calculator.py — Result Lab 데이터 계산기 (다단계 수식).

여러 결과파일의 컬럼을 변수(A,B,C…)에 매핑하고 `(A-B)/C` 같은 수식을 안전하게
평가해 새 시계열을 만든다. 교차-데이터셋이면 기준 변수의 시각격자에 보간 정렬한다.
미리보기 그래프 + CSV 저장. (NO2/PNs/ANs 채널차분 = 이 계산기의 특수케이스: B-A 등)

경계: 컬럼 연산이 '의미 있는 새 값'을 만들어 저장 → Result Lab 영역(Plot Maker는 그림만).
안전성: eval() 안 씀. ast 화이트리스트로 +−×÷**·괄호·소수의 함수만 허용.
"""
import ast
import os

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QMessageBox, QFileDialog, QWidget,
)
from PyQt6.QtCore import Qt

from gui.result_viewer_io import load_fit_table

# 수식에서 허용하는 element-wise 함수
_ALLOWED_FUNCS = {
    "abs": np.abs, "sqrt": np.sqrt, "log": np.log, "log10": np.log10,
    "exp": np.exp, "where": np.where,
}
_VAR_LETTERS = "ABCDEFGH"


def safe_eval(expr, variables):
    """ast 화이트리스트 안전 평가. variables: {name: ndarray|scalar}.
    허용: 숫자·변수명·+ - * / ** · 단항 ± · 괄호 · _ALLOWED_FUNCS 함수호출."""
    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError as e:
        raise ValueError(f"수식 문법 오류: {e}")

    def ev(n):
        if isinstance(n, ast.BinOp):
            l, r = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add):  return l + r
            if isinstance(n.op, ast.Sub):  return l - r
            if isinstance(n.op, ast.Mult): return l * r
            if isinstance(n.op, ast.Div):
                with np.errstate(divide="ignore", invalid="ignore"):
                    return l / r
            if isinstance(n.op, ast.Pow):  return l ** r
            raise ValueError("허용되지 않은 연산자 (+ - * / ** 만)")
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            if isinstance(n.op, ast.USub): return -v
            if isinstance(n.op, ast.UAdd): return +v
            raise ValueError("허용되지 않은 단항 연산")
        if isinstance(n, ast.Constant):
            if isinstance(n.value, (int, float)):
                return n.value
            raise ValueError("숫자 상수만 허용")
        if isinstance(n, ast.Name):
            if n.id in variables:
                return variables[n.id]
            raise ValueError(f"알 수 없는 변수 '{n.id}'")
        if isinstance(n, ast.Call):
            if (isinstance(n.func, ast.Name) and n.func.id in _ALLOWED_FUNCS
                    and not n.keywords):
                return _ALLOWED_FUNCS[n.func.id](*[ev(a) for a in n.args])
            raise ValueError(f"허용되지 않은 함수 (가능: {', '.join(_ALLOWED_FUNCS)})")
        raise ValueError(f"허용되지 않은 식: {type(n).__name__}")

    return ev(node)


class CalculatorDialog(QDialog):
    """결과 데이터 계산기. datasets: [경로,...] (Result Lab에서 로드된 파일들)."""

    def __init__(self, parent=None, datasets=None):
        super().__init__(parent)
        self.setWindowTitle("Data Calculator — 다단계 수식")
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
        btnbar.addWidget(QLabel("변수에 (파일, 컬럼)을 매핑하고 아래 수식을 쓰세요"))
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
        self._expr.setToolTip("예: A-B,  (A-B)/C,  A*2+B,  sqrt(abs(A)),  A/C*100\n"
                              "허용: + - * / **, 괄호, 숫자, abs/sqrt/log/log10/exp/where")
        exprbar.addWidget(self._expr, 1)
        left.addLayout(exprbar)

        refbar = QHBoxLayout()
        refbar.addWidget(QLabel("Align time to:"))
        self._ref = QComboBox()
        self._ref.setToolTip("교차-데이터셋일 때 모든 변수를 이 변수의 시각격자에 보간 정렬")
        refbar.addWidget(self._ref)
        refbar.addWidget(QLabel("   Result name:"))
        self._name = QLineEdit("result")
        refbar.addWidget(self._name, 1)
        left.addLayout(refbar)

        actbar = QHBoxLayout()
        b_calc = QPushButton("▶ Compute")
        b_calc.setStyleSheet("font-weight:bold; background:#2196F3; color:white; padding:4px;")
        b_calc.clicked.connect(self._compute)
        b_save = QPushButton("Save CSV")
        b_save.clicked.connect(self._save_csv)
        actbar.addWidget(b_calc)
        actbar.addWidget(b_save)
        actbar.addStretch(1)
        left.addLayout(actbar)

        self._msg = QLabel("")
        self._msg.setWordWrap(True)
        self._msg.setStyleSheet("color:#555;")
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
            self._last_col_err = f"{os.path.basename(path)}: 가스 컬럼 없음(핏 결과 아님?)"
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
            self._msg.setStyleSheet("color:#c62828;")

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
                raise ValueError(f"{letter}: '{os.path.basename(path)}'에 Time 컬럼이 없어 정렬 불가")
            vv = t["rms"] if cname == "RMS" else t["gases"].get(cname)
            if vv is None:
                raise ValueError(f"{letter}: 컬럼 '{cname}' 없음")
            tt = np.asarray(tt, float); vv = np.asarray(vv, float)
            m = np.isfinite(tt)
            o = np.argsort(tt[m])
            vars_raw[letter] = (tt[m][o], vv[m][o])
        if not vars_raw:
            raise ValueError("변수를 하나 이상 (파일·컬럼) 지정하세요.")
        return vars_raw, (self._ref.currentText() or next(iter(vars_raw)))

    def _compute(self):
        try:
            vars_raw, ref = self._gather()
            if ref not in vars_raw:
                ref = next(iter(vars_raw))
            ref_t, _ = vars_raw[ref]
            # 모든 변수를 기준 시각격자에 보간(범위 밖 NaN). 같은 격자면 사실상 동일.
            aligned = {}
            for letter, (tt, vv) in vars_raw.items():
                if np.array_equal(tt, ref_t):
                    aligned[letter] = vv
                else:
                    aligned[letter] = np.interp(ref_t, tt, vv, left=np.nan, right=np.nan)
            expr = self._expr.text().strip()
            if not expr:
                raise ValueError("수식을 입력하세요.")
            res = safe_eval(expr, aligned)
            res = np.asarray(res, float) * np.ones_like(ref_t)  # 스칼라 결과 방어
        except Exception as e:
            self._msg.setText(f"{e}")
            self._msg.setStyleSheet("color:#c62828;")
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
            f"mean={np.nanmean(res):.4g}   (aligned to {ref})")
        self._msg.setStyleSheet("color:#2E7D32;")

    def _save_csv(self):
        if not self._result:
            QMessageBox.information(self, "Save", "먼저 ▶ Compute 하세요.")
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
            QMessageBox.information(self, "Saved", f"저장됨:\n{out}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))
