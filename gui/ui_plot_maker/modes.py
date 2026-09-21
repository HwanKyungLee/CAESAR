# -*- coding: utf-8 -*-
"""Plot Maker — 구체 모드 6종: TimeSeries·Scatter·Allan·Heatmap·Histogram·Diurnal.

각 모드는 PlotMode(core.py)를 상속하고 @register_mode로 콤보에 자동 등록된다.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QHBoxLayout, QPushButton, QLabel, QComboBox,
    QListWidget, QListWidgetItem, QCheckBox, QSpinBox,
)
from PyQt6.QtCore import Qt

from .core import (ResolvedSeries, PlotMode, register_mode, _shade,
                   mathtext_to_html)
from .processing import (resample_mean, smooth, regress, allan_deviation,
                         step_xy, bar_width)


@register_mode
class TimeSeriesMode(PlotMode):
    key = "timeseries"
    label = "Time series"

    def __init__(self, host):
        super().__init__(host)
        self._series = []   # [[label, axis 'L'/'R', color|None, name|None], ...]
        self._styles = {}   # 라벨 → {width, dash, marker, msize} (선/마커 스타일)
        self._w = None
        # 야간음영(저녁~새벽 회색 밴드, 일별) — 박사님 MATLAB 기본 19:40~05:30
        self._night_on = False
        self._night_start = (19, 40)
        self._night_end = (5, 30)
        self._night_color = "#9e9e9e"

    def options_widget(self):
        w, lay, is_new = self._new_options_widget()
        if not is_new:
            return w
        row = QHBoxLayout()
        b_l = QPushButton("+ Left Y")
        b_r = QPushButton("+ Right Y")
        b_l.clicked.connect(lambda: self._add("L"))
        b_r.clicked.connect(lambda: self._add("R"))
        row.addWidget(b_l)
        row.addWidget(b_r)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        b_c = QPushButton("Color")
        b_s = QPushButton("Style")
        b_n = QPushButton("Name")
        b_del = QPushButton("− Remove")
        b_c.clicked.connect(self._pick_color)
        b_s.clicked.connect(self._edit_style)
        b_s.setToolTip("선 두께·점선/실선·마커 모양/크기")
        b_n.clicked.connect(self._rename)
        b_del.clicked.connect(self._remove)
        row2.addWidget(b_c)
        row2.addWidget(b_s)
        row2.addWidget(b_n)
        row2.addWidget(b_del)
        lay.addLayout(row2)
        # 야간음영 컨트롤(토글 + 시각 HH:MM + 색)
        from PyQt6.QtWidgets import QTimeEdit
        from PyQt6.QtCore import QTime
        nrow = QHBoxLayout()
        self._chk_night = QCheckBox("Night")
        self._chk_night.setToolTip("저녁~새벽 구간 음영(일별). 시각·색 지정 가능.\n"
                                   "시간축이 있을 때만 적용.")
        self._chk_night.toggled.connect(lambda *_: self.render())
        self._te_ns = QTimeEdit(QTime(*self._night_start)); self._te_ns.setDisplayFormat("HH:mm")
        self._te_ne = QTimeEdit(QTime(*self._night_end)); self._te_ne.setDisplayFormat("HH:mm")
        for te in (self._te_ns, self._te_ne):
            te.setFixedWidth(62)
            te.timeChanged.connect(lambda *_: self._sync_night())
        b_nc = QPushButton("Col"); b_nc.setFixedWidth(30); b_nc.setToolTip("음영 색")
        b_nc.clicked.connect(self._pick_night_color)
        nrow.addWidget(self._chk_night)
        nrow.addWidget(self._te_ns); nrow.addWidget(QLabel("→")); nrow.addWidget(self._te_ne)
        nrow.addWidget(b_nc)
        nrow.addStretch(1)
        lay.addLayout(nrow)
        self._chk_err = QCheckBox("± Error band (1σ)")
        self._chk_err.setToolTip("각 시리즈에 fit 1σ 오차({gas}_Error) 음영밴드.\n"
                                 "오차 컬럼이 있는 시리즈에만 표시.")
        self._chk_err.toggled.connect(lambda *_: self.render())
        lay.addWidget(self._chk_err)
        self._chk_split = QCheckBox("Split into panels (Publish)")
        self._chk_split.setToolTip("내보내기( Publish) 시 시리즈를 종별 패널(세로 스택, x축 공유)로\n"
                                   "분리. 화면 미리보기는 겹쳐 표시(논문그림용).")
        self._chk_split.toggled.connect(
            lambda on: self.host.set_status("Split panels: Publish 시 적용됨" if on else ""))
        lay.addWidget(self._chk_split)
        from PyQt6.QtWidgets import QAbstractItemView
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setToolTip("선반에서 컬럼 선택 후 [+ Left/Right Y].\n"
                              "더블클릭 = 좌↔우 전환, 우클릭 = 빠른 메뉴,\n"
                              "드래그 = 그리는 순서(범례·겹침순서) 변경, Delete = 제거.")
        self._list.itemDoubleClicked.connect(self._toggle_axis)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.model().rowsMoved.connect(lambda *a: self._sync_order_from_list())
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_list_context_menu)
        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self._list,
                 context=Qt.ShortcutContext.WidgetShortcut).activated.connect(self._remove)
        lay.addWidget(self._list)
        return w

    def _show_list_context_menu(self, pos):
        """리스트 우클릭 — 버튼 찾아다니지 않고 바로 색/스타일/이름/축전환/제거.
        우클릭한 항목이 선택돼 있지 않으면 먼저 그 항목만 선택(흔한 관례)."""
        from PyQt6.QtWidgets import QMenu
        item = self._list.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self._list.clearSelection()
            item.setSelected(True)
        menu = QMenu(self._list)
        menu.addAction("Color", self._pick_color)
        menu.addAction("Style", self._edit_style)
        menu.addAction("Rename", self._rename)
        menu.addAction("↔ Toggle L/R axis", lambda: self._toggle_axis(item))
        menu.addSeparator()
        menu.addAction("− Remove", self._remove)
        menu.exec(self._list.mapToGlobal(pos))

    def _add(self, axis):
        for lab in self.host.selected_columns():
            if not any(s[0] == lab and s[1] == axis for s in self._series):
                self._series.append([lab, axis, None, None])
        self._refresh_list()
        self.render()

    def on_column_activated(self, label):
        """Data 탭 더블클릭 → 좌축(Left Y) 시리즈로 추가하고 렌더."""
        if not any(s[0] == label and s[1] == "L" for s in self._series):
            self._series.append([label, "L", None, None])
            self._refresh_list()
        self.render()
        return True

    def _series_by_id(self, id_val):
        """id(엔트리) 값 → self._series의 실제 엔트리. PyQt6은 QListWidgetItem에
        저장한 plain list를 꺼낼 때 '같은 값이지만 다른 객체'로 복사해서 반환하므로
        (identity 비보존 — 실측 확인됨), 객체 자체 대신 안정적인 int(id값)를
        아이템 데이터로 저장하고 여기서 되찾는다."""
        return next((s for s in self._series if id(s) == id_val), None)

    def _selected_series(self):
        """리스트에서 선택된 시리즈들 — self._series의 실제 항목(참조)을 반환.
        드래그로 순서가 바뀌어도 안전(인덱스 어긋남 없음)."""
        out = []
        for it in self._list.selectedItems():
            s = self._series_by_id(it.data(Qt.ItemDataRole.UserRole))
            if s is not None:
                out.append(s)
        return out

    def _sync_order_from_list(self):
        """드래그로 리스트 순서가 바뀐 뒤 self._series를 화면 순서에 맞춰 재정렬.
        그리는 순서(겹침)·범례 순서가 이 리스트 순서를 그대로 따른다."""
        new_order = [self._series_by_id(self._list.item(i).data(Qt.ItemDataRole.UserRole))
                     for i in range(self._list.count())]
        if all(s is not None for s in new_order) and len(new_order) == len(self._series):
            self._series = new_order
        self.render()

    def _effective_color(self, lab, color, name):
        """시리즈의 실제 표시색(오버라이드 또는 자동) — 리스트 색상자 스와치가
        render()/_resolve_specs()와 항상 같은 색을 보여주도록 단일화."""
        return color or self._auto_color(self._display(lab, name))

    def _remove(self, keep_undo=True):
        sel = self._selected_series()
        if not sel:
            return
        sel_set = {id(s) for s in sel}
        if keep_undo:
            self.host.push_undo("timeseries_series", list(sel))
        self._series = [s for s in self._series if id(s) not in sel_set]
        self._refresh_list()
        self.render()
        if keep_undo:
            n = len(sel)
            self.host.set_status(f"{n}개 시리즈 제거됨 — Ctrl+Z로 복원")

    def _toggle_axis(self, item):
        s = self._series_by_id(item.data(Qt.ItemDataRole.UserRole))
        if s is not None:
            s[1] = "R" if s[1] == "L" else "L"
            self._refresh_list()
            self.render()

    def _pick_color(self):
        from PyQt6.QtWidgets import QColorDialog
        sel = self._selected_series()
        if not sel:
            self.host.set_status("색을 바꿀 시리즈를 목록에서 선택하세요.")
            return
        c = QColorDialog.getColor()
        if not c.isValid():
            return
        for s in sel:
            s[2] = c.name()
        self._refresh_list()
        self.render()

    def _rename(self):
        from PyQt6.QtWidgets import QInputDialog
        sel = self._selected_series()
        if not sel:
            self.host.set_status("이름을 바꿀 시리즈를 목록에서 선택하세요.")
            return
        s = sel[0]
        cur = s[3] or self._auto_name(s[0])
        text, ok = QInputDialog.getText(self._w, "Series name",
                                        "범례 이름 (빈칸 = 자동):", text=cur)
        if not ok:
            return
        s[3] = text.strip() or None
        self._refresh_list()
        self.render()

    def _refresh_list(self):
        from PyQt6.QtGui import QPixmap, QIcon, QColor
        self._list.clear()
        for s in self._series:
            lab, axis, color, name = s
            disp = self._display(lab, name)
            it = QListWidgetItem(f"[{axis}] {disp}")
            it.setToolTip(f"{lab}\n드래그로 순서 변경 · Delete로 제거")
            pix = QPixmap(14, 14); pix.fill(QColor(self._effective_color(lab, color, name)))
            it.setIcon(QIcon(pix))
            it.setData(Qt.ItemDataRole.UserRole, id(s))   # id값(int) 저장 — 객체 자체는 identity 안 보존됨
            self._list.addItem(it)

    def on_shelf_changed(self):
        valid = set(self.host.column_choices())
        before = len(self._series)
        self._series = [s for s in self._series if s[0] in valid]
        if self._w:
            self._refresh_list()
        if len(self._series) != before and self.host.is_active_mode(self):
            self.render()   # 제거된 시리즈가 있었으면 화면이 즉시 반영되게

    def to_config(self):
        on = self._chk_night.isChecked() if hasattr(self, "_chk_night") else self._night_on
        split = self._chk_split.isChecked() if hasattr(self, "_chk_split") else False
        err = self._chk_err.isChecked() if hasattr(self, "_chk_err") else False
        return {"series": self._series, "styles": self._styles, "split": split, "err": err,
                "night": {"on": on, "start": list(self._night_start),
                          "end": list(self._night_end), "color": self._night_color}}

    def from_config(self, cfg):
        self._series = []
        for s in cfg.get("series", []):
            s = list(s)
            while len(s) < 4:
                s.append(None)
            self._series.append([s[0], s[1], s[2], s[3]])
        self._styles = dict(cfg.get("styles") or {})
        nd = cfg.get("night") or {}
        if nd:
            self._night_start = tuple(nd.get("start", self._night_start))
            self._night_end = tuple(nd.get("end", self._night_end))
            self._night_color = nd.get("color", self._night_color)
            self._night_on = bool(nd.get("on", False))
        if self._w:
            from PyQt6.QtCore import QTime
            self._chk_night.setChecked(self._night_on)
            self._te_ns.setTime(QTime(*self._night_start))
            self._te_ne.setTime(QTime(*self._night_end))
            self._chk_split.setChecked(bool(cfg.get("split", False)))
            self._chk_err.setChecked(bool(cfg.get("err", False)))
            self._refresh_list()

    def _proc(self, y, t):
        """리샘플+평활 적용 → (x, y). 시간 없으면 인덱스."""
        if t is not None:
            xs, ys = resample_mean(t, y, self.host.resample_sec)
        else:
            xs, ys = np.arange(len(y), dtype=float), y
        return xs, smooth(ys, self.host.smooth_n)

    def _resolve_specs(self):
        """render()/render_mpl()/_render_mpl_split()/csv_table() 공용 진입점 —
        색상·범례이름·스타일·가공(resample+smooth)·에러밴드를 여기서 딱 한 번만
        계산한다. 화면(pg)과 Publish(mpl)가 절대 다른 값을 볼 수 없다."""
        host = self.host
        err_on = self._chk_err.isChecked() if hasattr(self, "_chk_err") else False
        out = []
        for lab, axis, color, name in self._series:
            res = host.resolve(lab)
            if res is None:
                continue
            ds, col, y, t = res
            xs, ys = self._proc(y, t)
            disp = self._display(lab, name)
            ci = color or self._auto_color(disp)
            st = self._style_of(lab)
            elo = ehi = None
            if err_on:
                err = host.error_of(lab)
                if err is not None and len(err) == len(y):
                    _, yse = self._proc(err, t)
                    elo, ehi = ys - yse, ys + yse
            out.append(ResolvedSeries(
                label=lab, display_name=disp, color=ci, axis=axis,
                x=xs, y=ys, err_lo=elo, err_hi=ehi,
                width=st["width"], dash=st["dash"], marker=st["marker"],
                msize=st["msize"], kind=st["kind"], alpha=st["alpha"],
                unit=host.unit_of(lab),
                extra={"has_time": t is not None, "col": col}))
        return out

    def _auto_ylabel_from_specs(self, specs, axis, default):
        """해당 축 시리즈들의 단위로 기본 Y라벨 생성(_resolve_specs 결과 기반).
        한 종이면 'NO2 [ppb]', 같은 단위 여럿이면 'Concentration [ppb]'."""
        matched = [s for s in specs if s.axis == axis]
        if not matched:
            return default
        units = {s.unit for s in matched}
        u = next(iter(units)) if len(units) == 1 else None
        if len(matched) == 1:
            col = matched[0].extra.get("col") or matched[0].display_name
            return f"{col} [{u}]" if u else col
        if u == "ppb":
            return "Concentration [ppb]"
        return f"Value [{u}]" if u else default

    # ── 시리즈 선/마커 스타일 ─────────────────────────────────
    _DASH = {"solid": Qt.PenStyle.SolidLine, "dash": Qt.PenStyle.DashLine,
             "dot": Qt.PenStyle.DotLine, "dashdot": Qt.PenStyle.DashDotLine,
             "none": Qt.PenStyle.NoPen}    # 선 없이 마커만(데이터 공백에서 호도 방지)
    _MPL_DASH = {"solid": "-", "dash": "--", "dot": ":", "dashdot": "-.", "none": "None"}
    # 키 = pyqtgraph 심볼(화면), 값 = matplotlib 마커(Publish). 둘 다 유효해야 함.
    _MPL_MARK = {"none": None, "o": "o", "s": "s", "t": "^", "t1": "v",
                 "d": "D", "+": "+", "x": "x", "star": "*", "p": "p", "h": "h"}

    # 표현 방식(kind). 색·선스타일과 직교 — "무엇으로 그리나"만 고른다.
    KINDS = ["line", "marker", "step", "bar", "area", "band", "errorbar"]
    _KIND_TIP = ("line=선 · marker=점만 · step=계단 · bar=막대 · area=0까지 채움\n"
                 "band=**목록의 바로 다음 시리즈**와의 사이를 채움(순서는 드래그로 바꿈)\n"
                 "errorbar=오차막대(캡). ± Error band 체크가 켜져 있어야 값이 있음")
    _STYLE_DEFAULT = {"width": 2, "dash": "solid", "marker": "o", "msize": 3,
                      "kind": "line", "alpha": 1.0}

    def _style_of(self, lab):
        """라벨별 스타일 dict(빠진 키는 기본값으로 채워서 반환).
        기본: 실선 2px + 점마커(o, 3px) — 박사님 요청(시계열은 선+데이터점 표시).
        점 빼고 싶으면 시리즈별 ✏에서 marker=none."""
        st = dict(self._STYLE_DEFAULT)
        st.update(self._styles.get(lab, {}))
        st["width"] = int(st["width"]); st["msize"] = int(st["msize"])
        st["alpha"] = float(st["alpha"])
        if st["kind"] not in self.KINDS:      # 옛/깨진 설정 방어
            st["kind"] = "line"
        return st

    def _edit_style(self):
        sel = self._selected_series()
        if not sel:
            self.host.set_status("스타일을 바꿀 시리즈를 목록에서 선택하세요.")
            return
        lab = sel[0][0]
        st0 = self._style_of(lab)
        from PyQt6.QtWidgets import (QDialog, QFormLayout, QSpinBox, QComboBox,
                                     QDialogButtonBox, QDoubleSpinBox)
        dlg = QDialog(self._w)
        dlg.setWindowTitle(f"Series style — {self._display(sel[0][0], sel[0][3])}")
        form = QFormLayout(dlg)
        cb_k = QComboBox(); cb_k.addItems(self.KINDS); cb_k.setCurrentText(st0["kind"])
        cb_k.setToolTip(self._KIND_TIP)
        sp_w = QSpinBox(); sp_w.setRange(1, 12); sp_w.setValue(st0["width"])
        cb_d = QComboBox(); cb_d.addItems(list(self._DASH.keys()))
        cb_d.setCurrentText(st0["dash"])
        cb_m = QComboBox()
        cb_m.addItems(["none", "o", "s", "t", "t1", "d", "+", "x", "star", "p", "h"])
        cb_m.setCurrentText(st0["marker"])
        cb_m.setToolTip("o=원 s=사각 t=세모 t1=역세모 d=마름모 +=십자 x=엑스 star=별 p=오각 h=육각")
        sp_m = QSpinBox(); sp_m.setRange(2, 20); sp_m.setValue(st0["msize"])
        sp_a = QDoubleSpinBox(); sp_a.setRange(0.05, 1.0); sp_a.setSingleStep(0.05)
        sp_a.setDecimals(2); sp_a.setValue(st0["alpha"])
        sp_a.setToolTip("불투명도(1=불투명). 시리즈가 겹쳐 뒤가 안 보일 때 낮춤.")
        form.addRow("Type", cb_k)
        form.addRow("Line width", sp_w)
        form.addRow("Line style", cb_d)
        form.addRow("Marker", cb_m)
        form.addRow("Marker size", sp_m)
        form.addRow("Opacity", sp_a)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # 선택한 모든 시리즈에 적용
        style = {"width": sp_w.value(), "dash": cb_d.currentText(),
                 "marker": cb_m.currentText(), "msize": sp_m.value(),
                 "kind": cb_k.currentText(), "alpha": sp_a.value()}
        for s in sel:
            self._styles[s[0]] = dict(style)
        self.render()

    # ── 야간음영 ──────────────────────────────────────────────
    def _sync_night(self):
        self._night_start = (self._te_ns.time().hour(), self._te_ns.time().minute())
        self._night_end = (self._te_ne.time().hour(), self._te_ne.time().minute())
        if self._chk_night.isChecked():
            self.render()

    def _pick_night_color(self):
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor
        c = QColorDialog.getColor(QColor(self._night_color), self._w, "Night shade color")
        if c.isValid():
            self._night_color = c.name()
            if self._chk_night.isChecked():
                self.render()

    def _night_spans(self, t0, t1):
        """t0~t1(epoch초) 사이 야간 구간 [(a,b)...]: 매일 start ~ 익일 end(일별).
        단독 주간스크립트 _shade_nights와 동일 알고리즘(전날밤 앞에서 시작해 첫날 새벽도 포함)."""
        import datetime as _dt
        sh, sm = self._night_start
        eh, em = self._night_end
        d = _dt.datetime.fromtimestamp(t0).replace(hour=0, minute=0, second=0,
                                                   microsecond=0) - _dt.timedelta(days=1)
        spans = []
        while d.timestamp() <= t1:
            ns = (d + _dt.timedelta(hours=sh, minutes=sm)).timestamp()
            ne = (d + _dt.timedelta(days=1, hours=eh, minutes=em)).timestamp()
            a, b = max(ns, t0), min(ne, t1)
            if a < b:
                spans.append((a, b))
            d += _dt.timedelta(days=1)
        return spans

    # ── kind별 그리기 (pg·mpl 공용 규칙) ──────────────────────────────
    # 두 렌더러가 **같은 분기**를 갖는다. 새 kind를 넣으면 반드시 양쪽에 넣을 것
    # (한쪽만 고쳐 화면·Publish가 갈라지는 게 이 파일의 단골 버그였다).

    @staticmethod
    def _rgba(color, alpha):
        c = pg.mkColor(color)
        c.setAlpha(max(0, min(255, int(round(255 * alpha)))))
        return c

    def _partner_y(self, s, specs):
        """band용 짝 = **목록의 바로 다음 시리즈**. x가 다르면 s.x 위로 보간.

        ponytail: 짝 지정 UI를 따로 두지 않는다 — 시리즈 목록은 이미 드래그로
        순서를 바꿀 수 있어서 '위아래로 붙이면 밴드'가 규칙으로 충분하다.
        다음 시리즈가 없으면 None → 호출측이 선으로 폴백."""
        try:
            i = specs.index(s)
        except ValueError:
            return None
        if i + 1 >= len(specs):
            return None
        p = specs[i + 1]
        if p.x is None or p.y is None or len(p.x) < 2:
            return None
        if len(p.x) == len(s.x):
            return p.y
        return np.interp(s.x, p.x, p.y, left=np.nan, right=np.nan)

    def _fill_base(self, s, specs):
        """area/band의 채움 기준선. band인데 짝이 없으면 None(선으로 폴백)."""
        if s.kind == "area":
            return np.zeros_like(s.y)
        return self._partner_y(s, specs)

    def _draw_pg_series(self, host, s, specs):
        """화면(pg)에서 시리즈 하나 그리기 — kind 분기."""
        vb = host.vb_right if s.axis == "R" else host.p1
        # 범례도 라벨과 같은 규칙 — 입력은 mathtext, pg에 넣기 직전 HTML로(M5).
        name = mathtext_to_html(f"{s.display_name} (R)" if s.axis == "R" else s.display_name)
        col = self._rgba(s.color, s.alpha)

        if s.kind == "bar":
            w = bar_width(s.x) or 1.0
            vb.addItem(pg.BarGraphItem(x=s.x, height=s.y, width=w,
                                       brush=pg.mkBrush(col), pen=pg.mkPen(None)))
            if host.legend is not None:   # BarGraphItem은 범례에 안 잡혀 대리 항목
                host.legend.addItem(pg.PlotDataItem([], [], pen=pg.mkPen(col, width=6)), name)
            return

        if s.kind in ("area", "band"):
            base = self._fill_base(s, specs)
            if base is not None:
                c0 = pg.PlotDataItem(s.x, base, pen=pg.mkPen(None))
                c1 = pg.PlotDataItem(s.x, s.y, pen=pg.mkPen(None))
                fb = pg.FillBetweenItem(c0, c1, brush=pg.mkBrush(self._rgba(s.color, 0.30 * s.alpha)))
                fb.setZValue(-40)
                vb.addItem(fb)

        if s.kind == "errorbar" and s.err_lo is not None:
            eb = pg.ErrorBarItem(x=s.x, y=s.y, top=s.err_hi - s.y, bottom=s.y - s.err_lo,
                                 beam=(bar_width(s.x) or 1.0) * 0.3, pen=pg.mkPen(col, width=1))
            vb.addItem(eb)

        xs, ys = (step_xy(s.x, s.y) if s.kind == "step" else (s.x, s.y))
        line_off = (s.dash == "none") or (s.kind == "marker")
        pen = None if line_off else pg.mkPen(col, width=s.width,
                                             style=self._DASH.get(s.dash, Qt.PenStyle.SolidLine))
        sym = None if s.marker == "none" else s.marker
        if line_off and sym is None:          # 둘 다 없으면 안 보이니 마커로 폴백
            sym = "o"
        if s.kind == "step" and sym is not None:
            # 계단은 좌표를 편 상태라 그 위에 마커를 찍으면 점이 두 배가 된다 →
            # 선은 편 좌표로, 마커는 원래 점 위치에 따로.
            curve = pg.PlotDataItem(xs, ys, pen=pen, name=name)
            self._add_pg(host, vb, curve, name)
            self._add_pg(host, vb, pg.PlotDataItem(s.x, s.y, pen=None, symbol=sym,
                                                   symbolSize=s.msize, symbolBrush=col,
                                                   symbolPen=None), None)
            return
        curve = pg.PlotDataItem(xs, ys, pen=pen, name=name, symbol=sym,
                                symbolSize=s.msize, symbolBrush=col, symbolPen=None)
        self._add_pg(host, vb, curve, name)

    @staticmethod
    def _add_pg(host, vb, item, legend_name):
        """PlotItem.addItem은 name이 있으면 범례에 자동 등록하지만, 오른쪽 축은
        보조 ViewBox(p1이 아님)라 자동이 안 된다 — 그때만 명시적으로 넣는다."""
        vb.addItem(item)
        if legend_name and host.legend is not None and vb is not host.p1:
            host.legend.addItem(item, legend_name)

    def _draw_mpl_series(self, ax, s, specs):
        """Publish(mpl)에서 시리즈 하나 그리기 — _draw_pg_series와 같은 분기.
        범례용 (handle, label)을 반환(없으면 (None, None))."""
        has_t = bool(s.extra.get("has_time"))
        conv = (lambda a: [datetime.fromtimestamp(v) for v in a]) if has_t else (lambda a: a)
        name = s.display_name
        col = s.color
        al = s.alpha

        if s.kind == "bar":
            w = bar_width(s.x)
            if w and has_t:
                w /= 86400.0                   # mpl 날짜축의 폭 단위는 '일'
            h = ax.bar(conv(s.x), s.y, width=(w or 0.8), color=col, alpha=al,
                       linewidth=0, label=name)
            return h, name

        if s.kind in ("area", "band"):
            base = self._fill_base(s, specs)
            if base is not None:
                ax.fill_between(conv(s.x), base, s.y, color=col, alpha=0.30 * al, lw=0)

        if s.kind == "errorbar" and s.err_lo is not None:
            ax.errorbar(conv(s.x), s.y, yerr=[s.y - s.err_lo, s.err_hi - s.y],
                        fmt="none", ecolor=col, elinewidth=1, capsize=2, alpha=al)

        ls = self._MPL_DASH.get(s.dash, "-")
        mk = self._MPL_MARK.get(s.marker)
        if s.kind == "marker":
            ls = "None"
        if ls == "None" and mk is None:        # 둘 다 none → 마커로 폴백
            mk = "o"
        if s.kind == "step":
            xs, ys = step_xy(s.x, s.y)
            line, = ax.plot(conv(xs), ys, color=col, lw=s.width, ls=ls, alpha=al, label=name)
            if mk is not None:                 # 마커는 원래 점 위치에(pg와 동일 규칙)
                ax.plot(conv(s.x), s.y, color=col, ls="None", marker=mk, ms=s.msize, alpha=al)
            return line, name
        line, = ax.plot(conv(s.x), s.y, color=col, lw=s.width, ls=ls, marker=mk,
                        ms=s.msize, alpha=al, label=name)
        return line, name

    def _draw_err_band(self, host, axis, xs, lo, hi, ci):
        col = pg.mkColor(ci); col.setAlpha(55)
        c_lo = pg.PlotDataItem(xs, lo, pen=pg.mkPen(None))
        c_hi = pg.PlotDataItem(xs, hi, pen=pg.mkPen(None))
        fb = pg.FillBetweenItem(c_lo, c_hi, brush=pg.mkBrush(col))
        fb.setZValue(-50)
        (host.vb_right if axis == "R" else host.p1).addItem(fb)

    def _draw_night_pg(self, host, t0, t1):
        col = pg.mkColor(self._night_color); col.setAlpha(45)
        for a, b in self._night_spans(t0, t1):
            reg = pg.LinearRegionItem([a, b], movable=False,
                                      brush=pg.mkBrush(col), pen=pg.mkPen(None))
            reg.setZValue(-100)
            host.p1.addItem(reg)

    def render(self):
        host = self.host
        host.clear_plot()
        specs = self._resolve_specs()
        use_right = any(s.axis == "R" for s in specs)
        host.enable_right_axis(use_right)
        any_time = any(s.extra["has_time"] for s in specs)
        tspan = self._tspan(specs)
        for s in specs:
            # errorbar는 밴드 대신 캡 막대로 그린다(_draw_pg_series) — 둘 다 그리면 중복
            if s.err_lo is not None and s.kind != "errorbar":
                self._draw_err_band(host, s.axis, s.x, s.err_lo, s.err_hi, s.color)
            self._draw_pg_series(host, s, specs)
        if (self._chk_night.isChecked() if hasattr(self, "_chk_night") else False) \
                and any_time and tspan[0] is not None:
            self._draw_night_pg(host, tspan[0], tspan[1])
        host.set_time_axis(any_time)
        host.pg_label("xlabel", host.lbl("xlabel", "Time" if any_time else "index"))
        host.pg_label("ylabel", host.lbl("ylabel", self._auto_ylabel_from_specs(specs, "L", "Value")))
        if use_right:
            host.pg_label("rlabel", host.lbl("rlabel", self._auto_ylabel_from_specs(specs, "R", "Value")))
        host.pg_label("title", host.lbl("title", ""))   # 기본 제목 없음(사용자가 지정)
        host.autoscale()
        if specs:
            host.set_status(f"{len(specs)} series"
                            + (f" · resample {host.resample_sec:g}s" if host.resample_sec else "")
                            + (f" · smooth {host.smooth_n}" if host.smooth_n > 1 else "")
                            + (f"·  time shift {host.time_shift_hours:+g}h" if host.time_shift_hours else ""))

    def _render_mpl_split(self, specs, fig):
        """Publish 분할: 시리즈마다 패널 1개(세로 스택, x축 공유). 종별 분리 그림.
        specs는 render_mpl()이 이미 _resolve_specs()로 만들어둔 것 — 재계산 안 함."""
        import matplotlib.dates as mdates
        import datetime as _dt
        axes = fig.subplots(len(specs), 1, sharex=True, squeeze=False)[:, 0]
        any_time = any(s.extra["has_time"] for s in specs)
        tspan = self._tspan(specs)
        night_on = ((self._chk_night.isChecked() if hasattr(self, "_chk_night") else False)
                    and any_time and tspan[0] is not None)
        for a, s in zip(axes, specs):
            xv = ([datetime.fromtimestamp(v) for v in s.x] if s.extra["has_time"] else s.x)
            if night_on:
                for s0, s1 in self._night_spans(tspan[0], tspan[1]):
                    a.axvspan(_dt.datetime.fromtimestamp(s0), _dt.datetime.fromtimestamp(s1),
                              color=self._night_color, alpha=0.18, lw=0, zorder=0)
            self._draw_mpl_series(a, s, specs)
            if s.err_lo is not None and s.kind != "errorbar":
                a.fill_between(xv, s.err_lo, s.err_hi, color=s.color, alpha=0.2, lw=0)
            a.set_ylabel(f"{s.display_name} [{s.unit}]" if s.unit else s.display_name)
            a.grid(True, alpha=0.3)
            a.legend(loc="best", fontsize=8)
        self.host.mpl_label(axes[-1], "xlabel", self.host.lbl("xlabel", "Time" if any_time else "index"))
        self.host.mpl_label(axes[0], "title", self.host.lbl("title", ""))
        if any_time:
            axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
            if tspan[0] is not None:    # x축 공유 → 마지막 패널에 tight xlim(양 끝 공백 제거)
                axes[-1].set_xlim(_dt.datetime.fromtimestamp(tspan[0]),
                                  _dt.datetime.fromtimestamp(tspan[1]))
            fig.autofmt_xdate()

    def render_mpl(self, fig):
        specs = self._resolve_specs()
        if (self._chk_split.isChecked() if hasattr(self, "_chk_split") else False) and len(specs) > 1:
            self._render_mpl_split(specs, fig)
            return
        import matplotlib.dates as mdates
        host = self.host
        ax = fig.add_subplot(111)
        ax_r = None
        any_time = any(s.extra["has_time"] for s in specs)
        tspan = self._tspan(specs)
        hl, ll = [], []   # 두 축 범례 통합
        for s in specs:
            xv = ([datetime.fromtimestamp(v) for v in s.x] if s.extra["has_time"] else s.x)
            if s.axis == "R":
                if ax_r is None:
                    ax_r = ax.twinx()
                target = ax_r
            else:
                target = ax
            line, lbl = self._draw_mpl_series(target, s, specs)
            if s.err_lo is not None and s.kind != "errorbar":
                target.fill_between(xv, s.err_lo, s.err_hi, color=s.color, alpha=0.2, lw=0)
            if line is not None:
                hl.append(line)
                ll.append(f"{lbl} (R)" if s.axis == "R" else lbl)
        if (self._chk_night.isChecked() if hasattr(self, "_chk_night") else False) \
                and any_time and tspan[0] is not None:
            import datetime as _dt
            for a, b in self._night_spans(tspan[0], tspan[1]):
                ax.axvspan(_dt.datetime.fromtimestamp(a), _dt.datetime.fromtimestamp(b),
                           color=self._night_color, alpha=0.18, lw=0, zorder=0)
        host.mpl_label(ax, "xlabel", host.lbl("xlabel", "Time" if any_time else "index"))
        host.mpl_label(ax, "ylabel", host.lbl("ylabel", self._auto_ylabel_from_specs(specs, "L", "Value")))
        if ax_r is not None:
            host.mpl_label(ax_r, "rlabel", host.lbl("rlabel", self._auto_ylabel_from_specs(specs, "R", "Value")))
        host.mpl_label(ax, "title", host.lbl("title", ""))
        ax.grid(True, alpha=0.3)
        if any_time:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
            # x축을 데이터 양 끝에 딱 맞춤(기본 5% 마진 제거) → 시작·끝 공백 없이 깔끔.
            # 사용자가 X min/max를 지정하면 _apply_axes_mpl에서 이 위로 덮어씀.
            if tspan[0] is not None:
                ax.set_xlim(datetime.fromtimestamp(tspan[0]),
                            datetime.fromtimestamp(tspan[1]))
            fig.autofmt_xdate()
        if hl:
            ax.legend(hl, ll, loc="best", fontsize=9)

    def csv_table(self):
        specs = self._resolve_specs()
        cols, time_ref = {}, None
        for s in specs:
            xs = s.x if s.extra["has_time"] else None
            key = s.display_name
            while key in cols:        # 이름 충돌 방지
                key += "_2"
            cols[key] = (xs, s.y)
            if time_ref is None and xs is not None:
                time_ref = xs
        if not cols:
            return None
        if time_ref is not None:
            headers = ["datetime"] + list(cols.keys())
            rows = []
            for i, tv in enumerate(time_ref):
                row = [datetime.fromtimestamp(tv).strftime("%Y-%m-%d %H:%M:%S")]
                for lab in cols:
                    xs, ys = cols[lab]
                    if xs is time_ref and i < len(ys):
                        row.append(f"{ys[i]:.6g}")
                    elif xs is not None:
                        row.append(f"{np.interp(tv, xs, ys):.6g}")
                    else:
                        row.append("")
                rows.append(row)
            return headers, rows
        headers = ["index"] + list(cols.keys())
        n = max(len(v[1]) for v in cols.values())
        rows = [[i] + [f"{cols[l][1][i]:.6g}" if i < len(cols[l][1]) else ""
                       for l in cols] for i in range(n)]
        return headers, rows


# ── Scatter + regression ──────────────────────────────────────────────
@register_mode
class ScatterMode(PlotMode):
    key = "scatter"
    label = "Scatter + regression"

    def __init__(self, host):
        super().__init__(host)
        self._w = None

    def color_keys(self):
        return [("points", "Data points", "#2196F3"), ("fit", "Fit line", "#D32F2F")]

    def options_widget(self):
        w, lay, is_new = self._new_options_widget()
        if not is_new:
            return w
        self._cx = QComboBox()
        self._cy = QComboBox()
        for c in (self._cx, self._cy):
            c.currentIndexChanged.connect(lambda *_: self.render())
        lay.addWidget(QLabel("X:"))
        lay.addWidget(self._cx)
        lay.addWidget(QLabel("Y:"))
        lay.addWidget(self._cy)
        self._chk_ct = QCheckBox("Color by time")
        self._chk_ct.setToolTip("점을 시각 순서대로 색칠(시간축 있을 때)")
        self._chk_ct.toggled.connect(lambda *_: self.render())
        lay.addWidget(self._chk_ct)
        lay.addStretch(1)
        self.on_shelf_changed()
        return w

    def on_shelf_changed(self):
        if not self._w:
            return
        choices = self.host.column_choices()
        for c in (self._cx, self._cy):
            self._rebuild_combo(c, choices, render_if_active=False)   # 둘 다 재구성 후 1회만 render
        if self.host.is_active_mode(self):
            self.render()

    def to_config(self):
        if not self._w:
            return {}
        return {"x": self._cx.currentText(), "y": self._cy.currentText(),
                "color_time": self._chk_ct.isChecked()}

    def from_config(self, cfg):
        if self._w:
            self._cx.setCurrentText(cfg.get("x", ""))
            self._cy.setCurrentText(cfg.get("y", ""))
            self._chk_ct.setChecked(bool(cfg.get("color_time", False)))

    def _xy(self):
        """선택한 X/Y → (xv, yv, tcolor). 다른 데이터셋이면 시간 보간. tcolor=X시각(없으면 None)."""
        host = self.host
        rx = host.resolve(self._cx.currentText())
        ry = host.resolve(self._cy.currentText())
        if rx is None or ry is None:
            return None
        dx, cx, xv, tx = rx
        dy, cy, yv, ty = ry
        if dx is not dy and tx is not None and ty is not None:
            mt = np.isfinite(ty) & np.isfinite(yv)
            if mt.sum() >= 2:
                o = np.argsort(ty[mt])
                yv = np.interp(tx, ty[mt][o], yv[mt][o], left=np.nan, right=np.nan)
                xv = xv.copy()
            tcolor = tx
        else:
            n = min(len(xv), len(yv))
            xv, yv = xv[:n], yv[:n]
            tcolor = tx[:n] if tx is not None else None
        return xv, yv, tcolor

    def render(self):
        host = self.host
        host.clear_plot()
        host.enable_right_axis(False)
        host.set_time_axis(False)
        xy = self._xy()
        if xy is None:
            host.set_status("Pick X and Y columns.")
            return
        xv, yv, tcolor = xy
        m = np.isfinite(xv) & np.isfinite(yv)
        if self._chk_ct.isChecked() and tcolor is not None and np.isfinite(tcolor[m]).any():
            tc = tcolor[m].astype(float)
            lo, hi = np.nanmin(tc), np.nanmax(tc)
            frac = (tc - lo) / (hi - lo) if hi > lo else np.zeros_like(tc)
            cmap = pg.colormap.get("viridis")
            brushes = [pg.mkBrush(cmap.map(f, mode="qcolor")) for f in frac]
            sp = pg.ScatterPlotItem(x=xv[m], y=yv[m], size=6, pen=None, brush=brushes)
            host.p1.addItem(sp)
        else:
            _pt = pg.mkColor(self.color("points", "#2196F3")); _pt.setAlpha(120)
            host.p1.plot(xv[m], yv[m], pen=None, symbol="o", symbolSize=5,
                         symbolBrush=_pt, symbolPen=None, name="data")
        host.pg_label("xlabel", host.lbl("xlabel", self._cx.currentText()))
        host.pg_label("ylabel", host.lbl("ylabel", self._cy.currentText()))
        r = regress(xv, yv)
        if r:
            slope, inter, r2, n = r
            xline = np.array([np.nanmin(xv[m]), np.nanmax(xv[m])])
            host.p1.plot(xline, slope * xline + inter,
                         pen=pg.mkPen(self.color("fit", "#D32F2F"), width=2), name="fit")
            host.pg_label("title", host.lbl("title",
                          f"y = {slope:.4g}·x + {inter:.4g}   R² = {r2:.4f}   n = {n}"))
            host.set_status(f"slope={slope:.5g}  intercept={inter:.5g}  R²={r2:.5f}  n={n}")
        else:
            host.pg_label("title", host.lbl("title", "Scatter"))
            host.set_status("Not enough finite points for regression.")
        host.autoscale()

    def render_mpl(self, fig):
        host = self.host
        ax = fig.add_subplot(111)
        xy = self._xy()
        if xy is None:
            ax.set_title("Scatter — pick X and Y")
            return
        xv, yv, tcolor = xy
        m = np.isfinite(xv) & np.isfinite(yv)
        if self._chk_ct.isChecked() and tcolor is not None and np.isfinite(tcolor[m]).any():
            sc = ax.scatter(xv[m], yv[m], s=16, c=tcolor[m], cmap="viridis",
                            alpha=0.7, edgecolors="none")
            cb = fig.colorbar(sc, ax=ax)
            cb.set_label("time (epoch s)")
        else:
            ax.scatter(xv[m], yv[m], s=14, c=self.color("points", "#2196F3"), alpha=0.5,
                       edgecolors="none", label="data")
        host.mpl_label(ax, "xlabel", host.lbl("xlabel", self._cx.currentText()))
        host.mpl_label(ax, "ylabel", host.lbl("ylabel", self._cy.currentText()))
        r = regress(xv, yv)
        if r:
            slope, inter, r2, n = r
            xline = np.array([np.nanmin(xv[m]), np.nanmax(xv[m])])
            ax.plot(xline, slope * xline + inter, color=self.color("fit", "#D32F2F"), lw=2,
                    label=f"y={slope:.4g}x+{inter:.4g}\n$R^2$={r2:.4f}, n={n}")
            host.mpl_label(ax, "title", host.lbl("title",
                           f"y = {slope:.4g}·x + {inter:.4g}   R² = {r2:.4f}   n = {n}"))
        else:
            host.mpl_label(ax, "title", host.lbl("title", "Scatter"))
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=9)

    def csv_table(self):
        xy = self._xy()
        if xy is None:
            return None
        xv, yv, _ = xy
        m = np.isfinite(xv) & np.isfinite(yv)
        headers = [self._cx.currentText(), self._cy.currentText()]
        rows = [[f"{a:.6g}", f"{b:.6g}"] for a, b in zip(xv[m], yv[m])]
        return headers, rows


# ── Allan deviation ───────────────────────────────────────────────────
@register_mode
class AllanMode(PlotMode):
    key = "allan"
    label = "Allan deviation"

    def __init__(self, host):
        super().__init__(host)
        self._w = None

    def color_keys(self):
        return [("curve", "Allan curve", "#2196F3")]

    def options_widget(self):
        w, lay, is_new = self._new_options_widget()
        if not is_new:
            return w
        self._c = QComboBox()
        self._c.currentIndexChanged.connect(lambda *_: self.render())
        lay.addWidget(QLabel("Signal:"))
        lay.addWidget(self._c)
        lay.addWidget(QLabel("최적 적분시간 = 곡선 최저점.\n−½ 기울기 = 백색잡음(평균화 이득)."))
        lay.addStretch(1)
        self.on_shelf_changed()
        return w

    def on_shelf_changed(self):
        if self._w:
            self._rebuild_combo(self._c, self.host.column_choices())

    def to_config(self):
        return {"signal": self._c.currentText()} if self._w else {}

    def from_config(self, cfg):
        if self._w:
            self._c.setCurrentText(cfg.get("signal", ""))

    def render(self):
        host = self.host
        host.clear_plot()
        host.enable_right_axis(False)
        host.set_time_axis(False)
        res = host.resolve(self._c.currentText())
        if res is None:
            host.set_status("Pick a signal (needs a time axis).")
            return
        ds, col, y, t = res
        out = allan_deviation(t, y)
        if out is None:
            host.set_status("Allan needs ≥16 finite points on a regular time axis.")
            host.p1.setTitle("Allan deviation — insufficient/irregular data")
            return
        taus, ad = out
        _cv = self.color("curve", "#2196F3")
        host.p1.setLogMode(x=True, y=True)
        host.p1.plot(taus, ad, pen=pg.mkPen(_cv, width=2), symbol="o",
                     symbolSize=6, symbolBrush=_cv, name=self._c.currentText())
        host.pg_label("xlabel", host.lbl("xlabel", "Averaging time τ (s)"))
        host.pg_label("ylabel", host.lbl("ylabel", "Allan deviation σ(τ)"))
        imin = int(np.argmin(ad))
        host.pg_label("title", host.lbl("title",
                      f"Allan deviation — min σ={ad[imin]:.3g} @ τ={taus[imin]:.0f}s"))
        host.set_status(f"optimal averaging ≈ {taus[imin]:.0f} s  (min Allan dev {ad[imin]:.3g})")
        host.autoscale()

    def render_mpl(self, fig):
        host = self.host
        ax = fig.add_subplot(111)
        res = host.resolve(self._c.currentText())
        out = None
        if res:
            ds, col, y, t = res
            out = allan_deviation(t, y)
        if out is None:
            ax.set_title("Allan deviation — insufficient/irregular data")
            return
        taus, ad = out
        ax.loglog(taus, ad, "o-", color=self.color("curve", "#2196F3"), lw=1.8, ms=5,
                  label=self._c.currentText())
        imin = int(np.argmin(ad))
        ax.axvline(taus[imin], color="#888", ls="--", lw=1)
        host.mpl_label(ax, "xlabel", host.lbl("xlabel", r"Averaging time $\tau$ (s)"))
        host.mpl_label(ax, "ylabel", host.lbl("ylabel", r"Allan deviation $\sigma(\tau)$"))
        host.mpl_label(ax, "title", host.lbl("title",
                       f"Allan deviation — min σ={ad[imin]:.3g} @ τ={taus[imin]:.0f}s"))
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(loc="best", fontsize=9)

    def csv_table(self):
        res = self.host.resolve(self._c.currentText())
        if not res:
            return None
        ds, col, y, t = res
        out = allan_deviation(t, y)
        if out is None:
            return None
        taus, ad = out
        return ["tau_s", "allan_dev"], [[f"{a:.6g}", f"{b:.6g}"] for a, b in zip(taus, ad)]


# ── Correlation heatmap ───────────────────────────────────────────────
@register_mode
class HeatmapMode(PlotMode):
    key = "heatmap"
    label = "Correlation heatmap"

    def __init__(self, host):
        super().__init__(host)
        self._w = None
        self._pinned_cols = None   # None=트리 선택 사용, list=핀 고정(저장/불러오기 가능)

    def options_widget(self):
        w, lay, is_new = self._new_options_widget()
        if not is_new:
            return w
        lay.addWidget(QLabel("선반에서 컬럼 2개 이상 선택\n(없으면 전체 컬럼 사용).\n"
                             "시간축이 있으면 첫 컬럼 시각격자에 맞춰 정렬."))
        row = QHBoxLayout()
        b_pin = QPushButton("Pin selection")
        b_pin.setToolTip("현재 트리에서 선택된 컬럼들을 고정 — 이후 트리 선택이 바뀌어도\n"
                         "이 집합을 계속 사용하고, 설정 저장/불러오기에도 보존됨.")
        b_pin.clicked.connect(self._pin_selection)
        b_unpin = QPushButton("Unpin")
        b_unpin.setToolTip("고정 해제 — 다시 트리 선택을 실시간으로 따라감.")
        b_unpin.clicked.connect(self._unpin_selection)
        row.addWidget(b_pin); row.addWidget(b_unpin)
        lay.addLayout(row)
        self._lbl_pin = QLabel("")
        self._lbl_pin.setStyleSheet("color:#666;")
        lay.addWidget(self._lbl_pin)
        b = QPushButton("Compute")
        b.clicked.connect(self.render)
        lay.addWidget(b)
        lay.addStretch(1)
        self._update_pin_label()
        return w

    def _update_pin_label(self):
        if hasattr(self, "_lbl_pin"):
            self._lbl_pin.setText(f"{len(self._pinned_cols)}개 컬럼 핀됨"
                                  if self._pinned_cols else "핀 없음 (트리 선택 사용)")

    def _pin_selection(self):
        cols = list(dict.fromkeys(self.host.selected_columns()))
        if not cols:
            self.host.set_status("핀할 컬럼이 없습니다 — Data 탭에서 트리 선택 후 다시 시도.")
            return
        self._pinned_cols = cols
        self._update_pin_label()
        self.render()

    def _unpin_selection(self):
        self._pinned_cols = None
        self._update_pin_label()
        self.render()

    def on_column_activated(self, label):
        """Heatmap은 단일컬럼 콤보가 없어 더블클릭이 '이 컬럼 하나만'을 뜻할 수
        없다(상관행렬은 ≥2 필요) — 현재 트리 선택 기준으로 즉시 재계산한다."""
        self.render()
        return True

    def to_config(self):
        return {"cols": self._pinned_cols} if self._pinned_cols else {}

    def from_config(self, cfg):
        cols = cfg.get("cols")
        self._pinned_cols = list(cols) if cols else None
        self._update_pin_label()

    def _matrix(self):
        """선택(또는 전체) 컬럼들의 Pearson 상관행렬 → (names, 2D ndarray) 또는 None."""
        import pandas as pd
        host = self.host
        labels = self._pinned_cols or host.selected_columns() or host.column_choices()
        labels = list(dict.fromkeys(labels))
        series, ref_t = {}, None
        for lab in labels:
            r = host.resolve(lab)
            if r is None:
                continue
            ds, col, y, t = r
            series[lab] = (y, t)
            if ref_t is None and t is not None:
                ref_t = t
        if len(series) < 2:
            return None
        data = {}
        if ref_t is not None:
            for lab, (y, t) in series.items():
                if t is not None:
                    m = np.isfinite(t) & np.isfinite(y)
                    if m.sum() >= 2:
                        o = np.argsort(t[m])
                        data[lab] = np.interp(ref_t, t[m][o], y[m][o],
                                              left=np.nan, right=np.nan)
                        continue
                yy = np.full(len(ref_t), np.nan)
                n = min(len(ref_t), len(y))
                yy[:n] = y[:n]
                data[lab] = yy
        else:
            n = min(len(y) for y, _ in series.values())
            for lab, (y, t) in series.items():
                data[lab] = y[:n]
        corr = pd.DataFrame(data).corr()
        return list(corr.columns), corr.to_numpy()

    @staticmethod
    def _short(names):
        return [n.split(":")[-1] for n in names]

    def render(self):
        host = self.host
        host.clear_plot()
        host.enable_right_axis(False)
        host.set_time_axis(False)
        mat = self._matrix()
        if mat is None:
            host.set_status("상관 히트맵: 컬럼 2개 이상 필요.")
            host.p1.setTitle("Correlation heatmap — need ≥2 columns")
            return
        names, C = mat
        img = pg.ImageItem()
        img.setOpts(axisOrder="row-major")
        img.setImage(C)
        img.setLevels([-1, 1])
        try:
            lut = pg.colormap.getFromMatplotlib("bwr").getLookupTable(0.0, 1.0, 256)
            img.setLookupTable(lut)
        except Exception:
            pass
        host.p1.addItem(img)
        short = self._short(names)
        ticks = [(i + 0.5, s) for i, s in enumerate(short)]
        host.p1.getAxis("bottom").setTicks([ticks])
        host.p1.getAxis("left").setTicks([ticks])
        # 셀 값 주석
        for i in range(len(names)):
            for j in range(len(names)):
                ti = pg.TextItem(f"{C[i, j]:.2f}", anchor=(0.5, 0.5),
                                 color="w" if abs(C[i, j]) > 0.5 else "k")
                ti.setPos(j + 0.5, i + 0.5)
                host.p1.addItem(ti)
        host.p1.invertY(True)
        host.pg_label("title", host.lbl("title", "Correlation matrix (Pearson r)"))
        host.autoscale()
        host.set_status(f"{len(names)} columns")

    def render_mpl(self, fig):
        mat = self._matrix()
        ax = fig.add_subplot(111)
        if mat is None:
            ax.set_title("Correlation heatmap — need ≥2 columns")
            return
        names, C = mat
        short = self._short(names)
        im = ax.imshow(C, vmin=-1, vmax=1, cmap="bwr")
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(short, rotation=45, ha="right")
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(short)
        for i in range(len(names)):
            for j in range(len(names)):
                ax.text(j, i, f"{C[i, j]:.2f}", ha="center", va="center",
                        fontsize=8, color="white" if abs(C[i, j]) > 0.5 else "black")
        fig.colorbar(im, ax=ax, shrink=0.8)
        self.host.mpl_label(ax, "title", self.host.lbl("title", "Correlation matrix (Pearson r)"))

    def csv_table(self):
        mat = self._matrix()
        if mat is None:
            return None
        names, C = mat
        short = self._short(names)
        headers = [""] + short
        rows = [[short[i]] + [f"{C[i, j]:.4f}" for j in range(len(names))]
                for i in range(len(names))]
        return headers, rows


# ── Histogram ─────────────────────────────────────────────────────────
@register_mode
class HistogramMode(PlotMode):
    key = "histogram"
    label = "Histogram"

    def __init__(self, host):
        super().__init__(host)
        self._w = None

    def color_keys(self):
        return [("bars", "Bars", "#2196F3"), ("mean", "Mean line", "#D32F2F"),
                ("median", "Median line", "#388E3C"), ("lod", "≈3σ line", "#7B1FA2")]

    def options_widget(self):
        w, lay, is_new = self._new_options_widget()
        if not is_new:
            return w
        self._c = QComboBox()
        self._c.currentIndexChanged.connect(lambda *_: self.render())
        lay.addWidget(QLabel("Column:"))
        lay.addWidget(self._c)
        lay.addWidget(QLabel("Bins:"))
        self._bins = QSpinBox()
        self._bins.setRange(5, 500)
        self._bins.setValue(40)
        self._bins.valueChanged.connect(lambda *_: self.render())
        lay.addWidget(self._bins)
        self._chk_lod = QCheckBox("Show ≈3σ (LOD)")
        self._chk_lod.setToolTip("평균+3σ 위치에 검출한계 추정선")
        self._chk_lod.toggled.connect(lambda *_: self.render())
        lay.addWidget(self._chk_lod)
        lay.addStretch(1)
        self.on_shelf_changed()
        return w

    def on_shelf_changed(self):
        if self._w:
            self._rebuild_combo(self._c, self.host.column_choices())

    def to_config(self):
        return ({"col": self._c.currentText(), "bins": self._bins.value(),
                 "lod": self._chk_lod.isChecked()} if self._w else {})

    def from_config(self, cfg):
        if self._w:
            self._c.setCurrentText(cfg.get("col", ""))
            self._bins.setValue(int(cfg.get("bins", 40)))
            self._chk_lod.setChecked(bool(cfg.get("lod", False)))

    def _vals(self):
        r = self.host.resolve(self._c.currentText())
        if not r:
            return None
        y = r[2]
        return y[np.isfinite(y)]

    def _resolve_hist(self):
        """render()/render_mpl() 공용 — 값·히스토그램·통계·색을 여기서 한 번만
        계산. 반환 dict 또는 컬럼 없으면 None."""
        v = self._vals()
        if v is None or v.size == 0:
            return None
        counts, edges = np.histogram(v, bins=self._bins.value())
        x = (edges[:-1] + edges[1:]) / 2.0
        widths = np.diff(edges)
        mu, md, sd = float(np.mean(v)), float(np.median(v)), float(np.std(v))
        lod = mu + 3 * sd if self._chk_lod.isChecked() else None
        return {"v": v, "counts": counts, "edges": edges, "x": x, "widths": widths,
                "mu": mu, "md": md, "sd": sd, "lod": lod,
                "bar_color": self.color("bars", "#2196F3"),
                "mean_color": self.color("mean", "#D32F2F"),
                "median_color": self.color("median", "#388E3C"),
                "lod_color": self.color("lod", "#7B1FA2")}

    def render(self):
        host = self.host
        host.clear_plot()
        host.enable_right_axis(False)
        host.set_time_axis(False)
        h = self._resolve_hist()
        if h is None:
            host.set_status("Pick a column.")
            host.p1.setTitle("Histogram — pick a column")
            return
        _bar = pg.mkColor(h["bar_color"]); _bar.setAlpha(150)
        host.p1.addItem(pg.BarGraphItem(x=h["x"], height=h["counts"], width=h["widths"] * 0.95,
                                        brush=_bar, pen=None))
        host.p1.addItem(pg.InfiniteLine(h["mu"], angle=90,
                        pen=pg.mkPen(h["mean_color"], width=2), label="mean"))
        host.p1.addItem(pg.InfiniteLine(h["md"], angle=90,
                        pen=pg.mkPen(h["median_color"], width=1,
                                     style=Qt.PenStyle.DashLine), label="median"))
        if h["lod"] is not None:
            host.p1.addItem(pg.InfiniteLine(h["lod"], angle=90,
                            pen=pg.mkPen(h["lod_color"], width=1,
                                         style=Qt.PenStyle.DotLine), label="≈3σ"))
        host.pg_label("xlabel", host.lbl("xlabel", self._c.currentText()))
        host.pg_label("ylabel", host.lbl("ylabel", "count"))
        host.pg_label("title", host.lbl("title", f"Histogram — μ={h['mu']:.3g} σ={h['sd']:.3g} n={h['v'].size}"))
        host.autoscale()
        host.set_status(f"n={h['v'].size}  μ={h['mu']:.4g}  median={h['md']:.4g}  σ={h['sd']:.4g}")

    def render_mpl(self, fig):
        host = self.host
        ax = fig.add_subplot(111)
        h = self._resolve_hist()
        if h is None:
            ax.set_title("Histogram — pick a column")
            return
        ax.hist(h["v"], bins=self._bins.value(), color=h["bar_color"], alpha=0.75,
                edgecolor="white")
        ax.axvline(h["mu"], color=h["mean_color"], lw=2, label=f"mean={h['mu']:.3g}")
        ax.axvline(h["md"], color=h["median_color"], lw=1.2, ls="--",
                   label=f"median={h['md']:.3g}")
        if h["lod"] is not None:
            ax.axvline(h["lod"], color=h["lod_color"], lw=1, ls=":",
                       label=f"≈3σ={h['lod']:.3g}")
        host.mpl_label(ax, "xlabel", host.lbl("xlabel", self._c.currentText()))
        host.mpl_label(ax, "ylabel", host.lbl("ylabel", "count"))
        host.mpl_label(ax, "title", host.lbl("title", f"Histogram — μ={h['mu']:.3g} σ={h['sd']:.3g} n={h['v'].size}"))
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)

    def csv_table(self):
        v = self._vals()
        if v is None or v.size == 0:
            return None
        counts, edges = np.histogram(v, bins=self._bins.value())
        x = (edges[:-1] + edges[1:]) / 2.0
        return ["bin_center", "count"], [[f"{a:.6g}", int(b)] for a, b in zip(x, counts)]


# ── Diurnal (hour of day) ─────────────────────────────────────────────
@register_mode
class DiurnalMode(PlotMode):
    key = "diurnal"
    label = "Diurnal (hour of day)"

    def __init__(self, host):
        super().__init__(host)
        self._w = None

    def _family(self):
        """현재 컬럼의 종 색을 기준으로 median/mean/band를 '같은 계열'로 묶어 반환.
        median=종색(진함), mean=같은 종 연한 변형, band=종색(반투명). 색 통일 강화."""
        base = self._auto_color(self._display(self._c.currentText(), None)) \
            if hasattr(self, "_c") else "#1976D2"
        return base, _shade(base, 0.45), base   # (median, mean, band)

    def color_keys(self):
        med, mn, bd = self._family()
        return [("median", "Median line", med), ("mean", "Mean line", mn),
                ("band", "IQR band (25–75%)", bd)]

    def options_widget(self):
        w, lay, is_new = self._new_options_widget()
        if not is_new:
            return w
        self._c = QComboBox()
        self._c.currentIndexChanged.connect(lambda *_: self.render())
        lay.addWidget(QLabel("Column:"))
        lay.addWidget(self._c)
        lay.addWidget(QLabel("Hour shift:"))
        self._shift = QSpinBox()
        self._shift.setRange(-12, 14)
        self._shift.setValue(0)
        self._shift.setToolTip("로컬 시각에 더할 시간(예: 데이터가 UTC면 KST=+9)")
        self._shift.valueChanged.connect(lambda *_: self.render())
        lay.addWidget(self._shift)
        self._chk_wrap = QCheckBox("하루 닫기 (024h)")
        self._chk_wrap.setToolTip("0시 값을 24시에 복제해 하루 주기를 닫음 → 선이 오른쪽 끝까지\n"
                                  "이어져 '23~24시 빈 곳' 착시 제거. (데이터는 그대로 0–23시 24개)")
        self._chk_wrap.toggled.connect(lambda *_: self.render())
        lay.addWidget(self._chk_wrap)
        lay.addWidget(QLabel("선 = 중앙값/평균,\n밴드 = 25–75 백분위수."))
        lay.addStretch(1)
        self.on_shelf_changed()
        return w

    def _wrap24(self, H, mean, med, p25, p75, cnt):
        """하루 닫기: 0시 값을 24시로 복제(H에 24 추가). 체크 꺼지면 그대로."""
        if not (hasattr(self, "_chk_wrap") and self._chk_wrap.isChecked()):
            return H, mean, med, p25, p75, cnt
        ap = lambda a: np.append(a, a[0])
        return np.append(H, 24), ap(mean), ap(med), ap(p25), ap(p75), np.append(cnt, cnt[0])

    def on_shelf_changed(self):
        if self._w:
            self._rebuild_combo(self._c, self.host.column_choices())

    def to_config(self):
        return ({"col": self._c.currentText(), "shift": self._shift.value(),
                 "wrap": self._chk_wrap.isChecked()} if self._w else {})

    def from_config(self, cfg):
        if self._w:
            self._c.setCurrentText(cfg.get("col", ""))
            self._shift.setValue(int(cfg.get("shift", 0)))
            self._chk_wrap.setChecked(bool(cfg.get("wrap", False)))

    def _stats(self):
        """시(0–23)별 mean/median/25–75% → (H, mean, med, p25, p75, cnt, col) 또는 None."""
        import datetime as _dt
        r = self.host.resolve(self._c.currentText())
        if not r:
            return None
        ds, col, y, t = r
        if t is None:
            return None
        m = np.isfinite(t) & np.isfinite(y)
        if m.sum() < 1:
            return None
        sh = self._shift.value()
        hrs = np.array([(_dt.datetime.fromtimestamp(v).hour + sh) % 24 for v in t[m]])
        vals = y[m]
        H = np.arange(24)
        mean = np.full(24, np.nan); med = np.full(24, np.nan)
        p25 = np.full(24, np.nan); p75 = np.full(24, np.nan); cnt = np.zeros(24, int)
        for h in range(24):
            vv = vals[hrs == h]
            if vv.size:
                mean[h] = np.mean(vv); med[h] = np.median(vv)
                p25[h] = np.percentile(vv, 25); p75[h] = np.percentile(vv, 75)
                cnt[h] = vv.size
        return H, mean, med, p25, p75, cnt, col

    def _ylabel(self, col):
        u = self.host.unit_of(self._c.currentText())
        return self.host.lbl("ylabel", f"{col} [{u}]" if u else col)

    def _resolve_specs(self):
        """render()/render_mpl() 공용 — median/mean/band 3개 ResolvedSeries를
        여기서 한 번만 계산(_family()+color() 조합) → 화면·Publish 색 drift 불가.
        반환 (specs, col, cnt) 또는 시간축 컬럼이 없으면 None."""
        s = self._stats()
        if s is None:
            return None
        H, mean, med, p25, p75, cnt, col = s
        H, mean, med, p25, p75, cnt = self._wrap24(H, mean, med, p25, p75, cnt)
        # 시계열과 동일한 이름해석기(_display)를 거쳐 색을 뽑는다 → 같은 종은 두 그래프
        # 색이 일치(ANs→초록), NO2 셀 구분(ANs/PNs 꼬리표)도 동일하게 반영.
        med_c, mean_c, band_c = self._family()
        specs = [
            ResolvedSeries(label="median", display_name="Median",
                           color=self.color("median", med_c), x=H, y=med,
                           width=2, marker="o", msize=6, extra={"kind": "median"}),
            ResolvedSeries(label="mean", display_name="Mean",
                           color=self.color("mean", mean_c), x=H, y=mean,
                           width=2, dash="dash", marker="s", msize=6, extra={"kind": "mean"}),
            ResolvedSeries(label="band", display_name="25–75%",
                           color=self.color("band", band_c), x=H, y=None,
                           err_lo=p25, err_hi=p75, extra={"kind": "band"}),
        ]
        return specs, col, cnt

    def render(self):
        host = self.host
        host.clear_plot()
        host.enable_right_axis(False)
        host.set_time_axis(False)
        out = self._resolve_specs()
        if out is None:
            host.set_status("시간축이 있는 컬럼을 고르세요.")
            host.p1.setTitle("Diurnal — needs a time axis")
            return
        specs, col, cnt = out
        band = next(s for s in specs if s.extra["kind"] == "band")
        med = next(s for s in specs if s.extra["kind"] == "median")
        mn = next(s for s in specs if s.extra["kind"] == "mean")
        bd = pg.mkColor(band.color); bd.setAlpha(60)
        lo = host.p1.plot(band.x, band.err_lo, pen=pg.mkPen((33, 150, 243, 0)))
        hi = host.p1.plot(band.x, band.err_hi, pen=pg.mkPen((33, 150, 243, 0)))
        host.p1.addItem(pg.FillBetweenItem(lo, hi, brush=pg.mkBrush(bd)))
        host.p1.plot(med.x, med.y, pen=pg.mkPen(med.color, width=med.width),
                     symbol=med.marker, symbolSize=med.msize, symbolBrush=med.color,
                     name=med.display_name)
        host.p1.plot(mn.x, mn.y, pen=pg.mkPen(mn.color, width=mn.width, style=Qt.PenStyle.DashLine),
                     symbol=mn.marker, symbolSize=mn.msize, symbolBrush=mn.color,
                     name=mn.display_name)
        host.pg_label("xlabel", host.lbl("xlabel", "Hour of day"))
        host.pg_label("ylabel", self._ylabel(col))
        host.pg_label("title", host.lbl("title", ""))
        host.autoscale()
        host.set_status(f"{col} diurnal · n={int(cnt.sum())} (band = 25–75%)")

    def render_mpl(self, fig):
        host = self.host
        ax = fig.add_subplot(111)
        out = self._resolve_specs()
        if out is None:
            ax.set_title("Diurnal — needs a time axis")
            return
        specs, col, cnt = out
        band = next(s for s in specs if s.extra["kind"] == "band")
        med = next(s for s in specs if s.extra["kind"] == "median")
        mn = next(s for s in specs if s.extra["kind"] == "mean")
        ax.fill_between(band.x, band.err_lo, band.err_hi, color=band.color, alpha=0.25,
                        label=band.display_name)
        ax.plot(med.x, med.y, "-o", color=med.color, lw=med.width, ms=med.msize,
                label=med.display_name)
        ax.plot(mn.x, mn.y, "--s", color=mn.color, lw=mn.width, ms=mn.msize,
                label=mn.display_name)
        host.mpl_label(ax, "xlabel", host.lbl("xlabel", "Hour of day"))
        host.mpl_label(ax, "ylabel", self._ylabel(col))
        host.mpl_label(ax, "title", host.lbl("title", ""))
        ax.set_xticks(range(0, 24, 3))
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=9)

    def csv_table(self):
        s = self._stats()
        if s is None:
            return None
        H, mean, med, p25, p75, cnt, col = s
        headers = ["hour", "n", "mean", "median", "p25", "p75"]
        rows = [[int(h), int(cnt[h]),
                 f"{mean[h]:.6g}", f"{med[h]:.6g}", f"{p25[h]:.6g}", f"{p75[h]:.6g}"]
                for h in range(24)]
        return headers, rows


