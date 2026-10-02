# -*- coding: utf-8 -*-
"""Plot Maker — Composer: 한 그림에 패널 여러 개 (M2, 결정 (B) mpl 전용 조판).

화면(pg)은 지금처럼 **편집 중인 패널 하나**만 보여주고, 조판 전체는 Preview·Publish(mpl)에서만
합친다. 그래서 화면 코드(`self.p1` 83곳)는 그대로이고, 패널 하나 안의 화면↔출력 규약도 그대로다.

패널 = 그 패널을 재현하는 **설정 조각**: 모드·모드 설정·라벨·라벨 스타일·축 상태·주석·리샘플/평활/
시프트. 편집기 상태를 찍어 패널로 만들고(`snapshot`), Publish할 때 패널마다 그 조각을 호스트에
잠시 끼워 넣고 같은 함수로 그린 뒤 되돌린다(`_render_panel`) — 그리는 로직이 하나라 화면·출력
드리프트가 생길 수 없다. 글자·눈금 크기·눈금 방향·격자는 **그림 전체의 룩**이라 패널 것이 아니라
편집기 현재값을 모든 패널에 쓴다(Copernicus 프리셋을 나중에 걸어도 전 패널에 먹게).

편집 연결: 패널을 'Edit'하면 그 조각이 편집기에 실리고, 이후 다른 탭에서 바꾼 것은 그 패널로
들어간다(조판 그림을 만들 때·다른 패널로 옮길 때 자동 반영).
"""
from __future__ import annotations

import copy

from PyQt6.QtCore import QObject, QSignalBlocker
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QCheckBox, QSpinBox, QLineEdit,
    QListWidget, QPushButton, QLabel, QDialog, QDialogButtonBox, QDoubleSpinBox, QComboBox,
)

from gui.theme import AUGUR

LETTERS = "abcdefghijklmnopqrstuvwxyz"
# 그림 전체의 룩 — 패널이 아니라 편집기 현재값을 모든 패널에 쓴다.
LOOK_KEYS = ("tick_size", "tick_dir", "tick_len", "grid", "grid_minor")


def _is_colorbar(a):
    return getattr(a, "_colorbar", None) is not None or a.get_label() == "<colorbar>"


def _is_date_axis(a):
    import matplotlib.dates as mdates
    return isinstance(a.xaxis.get_major_formatter(),
                      (mdates.DateFormatter, mdates.AutoDateFormatter, mdates.ConciseDateFormatter))


def _parse_ratios(text, n):
    try:
        vals = [float(v) for v in str(text or "").replace(";", ",").split(",") if v.strip()]
    except ValueError:
        return None
    return vals if len(vals) == n and all(v > 0 for v in vals) else None



def _missing_datasets(cfg, shelf):
    """Dataset names referenced by a panel's mode config ('ds:col' strings, also as dict keys)
    that are not on the shelf."""
    out = set()

    def walk(v):
        if isinstance(v, str):
            if ":" in v and v.split(":", 1)[0] and v.split(":", 1)[0] not in shelf:
                out.add(v.split(":", 1)[0])
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(k); walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
    walk(cfg or {})
    return out

class Composer:
    def __init__(self, host):
        self.host = host
        self.on = False
        self.rows, self.cols = 1, 2
        self.hratios = ""
        self.wratios = ""
        self.sharex = False
        self.letters = True
        self.panels = []       # 패널 조각 + "cell": [r, c, rowspan, colspan] 또는 "inset": {"in", "rect"}
        self.editing = None    # 편집기가 묶인 패널 번호(None = 자유 편집)
        self._w = None

    # ── 상태 ──────────────────────────────────────────────────────────
    def active(self):
        return self.on and bool(self.panels)

    def to_config(self):
        return {"on": self.on, "rows": self.rows, "cols": self.cols, "hratios": self.hratios,
                "wratios": self.wratios, "sharex": self.sharex, "letters": self.letters,
                "panels": copy.deepcopy(self.panels), "editing": self.editing}

    def from_config(self, cfg):
        cfg = cfg or {}
        self.on = bool(cfg.get("on", False))
        self.rows, self.cols = int(cfg.get("rows", 1)), int(cfg.get("cols", 2))
        self.hratios, self.wratios = cfg.get("hratios", ""), cfg.get("wratios", "")
        self.sharex, self.letters = bool(cfg.get("sharex", False)), bool(cfg.get("letters", True))
        self.panels = copy.deepcopy(cfg.get("panels") or [])
        ed = cfg.get("editing")
        self.editing = ed if isinstance(ed, int) and 0 <= ed < len(self.panels) else None
        self.sync_widgets()

    # ── 조각 찍기 / 편집기에 싣기 ──────────────────────────────────────
    def snapshot(self):
        """편집기 현재 상태 → 패널 조각(셀 정보 제외)."""
        h = self.host
        m = h._mode
        return {"mode": m.key, "mode_cfg": copy.deepcopy(m.to_config()),
                "mode_colors": dict(getattr(m, "colors", {}) or {}),
                "labels": dict(h.custom), "label_style": copy.deepcopy(h.label_style),
                "axes": h._axes_state(), "annots": copy.deepcopy(h._annots),
                "resample": h._res_combo.currentText(),
                "resample_custom_min": h._res_custom_spin.value(),
                "smooth": h._smooth_spin.value(), "time_shift_h": h._shift_spin.value(),
                "resample_sec": h.resample_sec, "smooth_n": h.smooth_n,
                "time_shift_hours": h.time_shift_hours}

    def write_back(self):
        """편집기가 패널에 묶여 있으면 지금 상태를 그 패널로(셀·inset 정보는 유지)."""
        if self.editing is None or not (0 <= self.editing < len(self.panels)):
            return
        p = self.panels[self.editing]
        keep = {k: p[k] for k in ("cell", "inset") if k in p}
        self.panels[self.editing] = {**self.snapshot(), **keep}

    def load_into_editor(self, p):
        h = self.host
        for i, m in enumerate(h._modes):
            if m.key == p.get("mode"):
                m.from_config(copy.deepcopy(p.get("mode_cfg") or {}))
                m.colors = dict(p.get("mode_colors") or {})
                h._mode_combo.setCurrentIndex(i)
                break
        h._res_custom_spin.setValue(float(p.get("resample_custom_min", 2.0)))
        h._res_combo.setCurrentText(p.get("resample", "Raw"))
        h._smooth_spin.setValue(int(p.get("smooth", 1)))
        h._shift_spin.setValue(float(p.get("time_shift_h", 0.0)))
        lab = p.get("labels") or {}
        h._ed_title.setText(lab.get("title", "")); h._ed_x.setText(lab.get("xlabel", ""))
        h._ed_y.setText(lab.get("ylabel", "")); h._ed_r.setText(lab.get("rlabel", ""))
        h.custom = {k: lab.get(k, "") for k in ("title", "xlabel", "ylabel", "rlabel")}
        for k, v in (p.get("label_style") or {}).items():
            pos = v.get("pos")
            h.label_style[k] = {"pos": tuple(pos) if pos else None,
                                "size": v.get("size"), "color": v.get("color")}
        h._sync_label_style_widgets()
        look = {k: h._axes_state()[k] for k in LOOK_KEYS}
        h._set_axes_widgets({**(p.get("axes") or {}), **look})
        h._annots = [h._annot_norm(a) for a in (p.get("annots") or [])]
        h._on_transform_changed()

    # ── 패널 조작 ────────────────────────────────────────────────────
    def _covered(self):
        cov = set()
        for p in self.panels:
            if "cell" in p:
                r, c, rs, cs = p["cell"]
                cov |= {(rr, cc) for rr in range(r, r + rs) for cc in range(c, c + cs)}
        return cov

    def _free_cell(self):
        cov = self._covered()
        for r in range(self.rows):
            for c in range(self.cols):
                if (r, c) not in cov:
                    return [r, c, 1, 1]
        self.rows += 1                       # 칸이 다 찼으면 한 줄 늘린다
        return [self.rows - 1, 0, 1, 1]

    def add_current(self):
        """지금 화면을 새 패널로. 추가한 뒤 편집기는 **어느 패널에도 묶지 않는다** — 묶어 두면
        다음 패널을 만들려고 화면을 바꾸는 순간 방금 추가한 패널이 덮어써진다(구현 중 잡은 함정).
        패널을 고치려면 명시적으로 Edit(더블클릭)."""
        self.write_back()
        p = self.snapshot()
        p["cell"] = self._free_cell()
        self.panels.append(p)
        self.editing = None
        self.on = True
        self.sync_widgets()
        return len(self.panels) - 1

    def edit(self, i):
        if not (0 <= i < len(self.panels)):
            return
        self.write_back()
        self.editing = i
        self.load_into_editor(self.panels[i])
        self.sync_widgets()

    def stop_editing(self):
        self.write_back()
        self.editing = None
        self.sync_widgets()

    def remove(self, i):
        if not (0 <= i < len(self.panels)):
            return
        self.write_back()
        del self.panels[i]
        for p in self.panels:                # 지운 패널에 꽂힌 inset은 첫 패널로
            ins = p.get("inset")
            if ins and ins.get("in") is not None:
                if ins["in"] == i:
                    ins["in"] = 0
                elif ins["in"] > i:
                    ins["in"] -= 1
        if self.editing is not None:
            self.editing = None if self.editing == i else (self.editing - (self.editing > i))
        self._fit_grid()
        self.sync_widgets()

    # ── 그리기 ────────────────────────────────────────────────────────
    def _mode_instance(self, p):
        """패널 전용 모드 인스턴스 — 편집기의 모드(화면)를 건드리지 않게 새로 만든다.
        옵션 위젯의 신호를 막아 from_config가 화면 render()를 부르지 않게 한다."""
        h = self.host
        cls = next((type(m) for m in h._modes if m.key == p.get("mode")), None)
        if cls is None:
            raise ValueError(f"unknown mode: {p.get('mode')!r}")
        m = cls(h)
        w = m.options_widget()
        blockers = []
        if w is not None:
            blockers = [QSignalBlocker(o) for o in [w] + w.findChildren(QObject)]
        m.from_config(copy.deepcopy(p.get("mode_cfg") or {}))
        m.colors = dict(p.get("mode_colors") or {})
        return m, w, blockers

    def _render_panel(self, fig, ax, p):
        """패널 조각을 호스트에 잠시 끼워 넣고 그 모드로 ax에 그린다 → 그 패널의 주 축 목록."""
        h = self.host
        saved = dict(custom=h.custom, label_style=h.label_style, annots=h._annots,
                     rs=h.resample_sec, sm=h.smooth_n, sh=h.time_shift_hours,
                     axes=h._axes_state(), time_axis=getattr(h, "_time_axis", False))
        look = {k: saved["axes"][k] for k in LOOK_KEYS}
        w = None
        try:
            h.custom = dict(p.get("labels") or {})
            h.label_style = {k: {"pos": tuple(v["pos"]) if v.get("pos") else None,
                                 "size": v.get("size"), "color": v.get("color")}
                             for k, v in (p.get("label_style") or saved["label_style"]).items()}
            h._annots = [h._annot_norm(a) for a in (p.get("annots") or [])]
            h.resample_sec = p.get("resample_sec", 0)
            h.smooth_n = p.get("smooth_n", 1)
            h.time_shift_hours = p.get("time_shift_hours", 0.0)
            h._set_axes_widgets({**(p.get("axes") or {}), **look}, block=True)
            m, w, _bl = self._mode_instance(p)
            missing = sorted(_missing_datasets(p.get("mode_cfg"), h.shelf))
            if missing:
                # The panel's data is gone — say so on the panel and in the status line
                # instead of publishing silent empty axes.
                ax.text(0.5, 0.5, "missing: " + ", ".join(missing), transform=ax.transAxes,
                        ha="center", va="center", color="#b00", fontsize=9)
                warns = getattr(h, "_publish_warnings", None)
                if warns is not None:
                    idx = next((i for i, q in enumerate(self.panels) if q is p), 0)
                    warns.append(f"panel ({LETTERS[idx % 26]}) missing dataset(s): "
                                 + ", ".join(missing))
            before = set(fig.axes)
            m.render_mpl(fig, ax)
            # ax가 아직 살아 있나: 분할 시계열은 ax를 지우고 칸을 쪼갠다. inset 축은 fig.axes가
            # 아니라 꽂힌 축의 child_axes에 있다(구현 중 잡은 함정 — 빠뜨리면 축 설정이 안 먹는다).
            alive = ax in fig.axes or any(ax in getattr(a, "child_axes", ()) for a in fig.axes)
            axes = ([ax] if alive else []) + [a for a in fig.axes if a not in before]
            axes = [a for a in axes if not _is_colorbar(a)]
            h._time_axis = any(_is_date_axis(a) for a in axes)
            h._apply_axes_mpl(fig, axes=axes)
            if not (h.custom.get("title") or "").strip():
                # 모드 자동 제목(회귀식·μ/σ 등)은 패널 폭을 넘쳐 옆 패널 글자와 겹친다(실측) —
                # 조판에선 패널 글자가 구분을 맡고, 통계는 범례에 남아 있다. 직접 단 제목만 쓴다.
                for a in axes:
                    a.set_title("")
            return axes
        finally:
            h.custom, h.label_style, h._annots = saved["custom"], saved["label_style"], saved["annots"]
            h.resample_sec, h.smooth_n, h.time_shift_hours = saved["rs"], saved["sm"], saved["sh"]
            h._set_axes_widgets(saved["axes"], block=True)
            h._time_axis = saved["time_axis"]
            if w is not None:
                w.deleteLater()

    def build_fig(self, fig):
        """조판 그림을 fig에 채운다. 편집 중인 패널은 지금 편집기 상태로 먼저 갱신."""
        self.write_back()
        # constrained layout — tight_layout은 inset이 있으면 포기해 제목이 겹치고 아래가 빈다(실측).
        # 패널 글자를 왼쪽 제목으로 다는 것도 이 엔진이 자리를 계산해 주기 때문.
        fig.set_layout_engine("constrained")
        rows, cols = max(1, self.rows), max(1, self.cols)
        gs = fig.add_gridspec(rows, cols, height_ratios=_parse_ratios(self.hratios, rows),
                              width_ratios=_parse_ratios(self.wratios, cols))
        drawn = {}                                    # 패널 번호 → 주 축 목록
        for i, p in enumerate(self.panels):
            if "inset" in p:
                continue
            r, c, rs, cs = p.get("cell", [0, 0, 1, 1])
            r, c = min(max(r, 0), rows - 1), min(max(c, 0), cols - 1)
            rs, cs = max(1, min(rs, rows - r)), max(1, min(cs, cols - c))
            ax = fig.add_subplot(gs[r:r + rs, c:c + cs])
            drawn[i] = self._render_panel(fig, ax, p)
        for i, p in enumerate(self.panels):
            if "inset" not in p:
                continue
            host_axes = drawn.get(p["inset"].get("in"))
            if not host_axes:
                continue                              # 꽂을 패널이 없다 — 그리지 않는다
            rect = p["inset"].get("rect") or [0.58, 0.58, 0.38, 0.38]
            ax = host_axes[0].inset_axes(rect)
            drawn[i] = self._render_panel(fig, ax, p)
            self._tidy_inset(drawn[i], p)
        if self.sharex:
            self._share_x(drawn)
        if self.letters:
            size = (self.host._lbl_size.value() or 10) + 1
            for i in sorted(drawn):
                axes = drawn[i]
                if not axes or "inset" in self.panels[i]:
                    continue        # inset은 꽂힌 패널의 일부 — 글자를 따로 달지 않는다
                top = max(axes, key=lambda a: a.get_position().y1)
                top.set_title(f"({LETTERS[i % 26]})", loc="left", fontweight="bold", fontsize=size)
        return drawn

    def _tidy_inset(self, axes, p):
        """inset은 작다 — 사용자가 직접 단 라벨이 아니면 제목·축 라벨·범례를 빼고 눈금 글자를 줄인다."""
        lab = p.get("labels") or {}
        small = max((self.host._tick_pt() or 8) - 2, 5)
        for a in axes:
            if not (lab.get("title") or "").strip():
                a.set_title("")
            if not (lab.get("xlabel") or "").strip():
                a.set_xlabel("")
            if not (lab.get("ylabel") or "").strip():
                a.set_ylabel("")
            if a.get_legend() is not None:
                a.get_legend().remove()
            a.tick_params(labelsize=small)
            from matplotlib.ticker import NullFormatter
            a.xaxis.set_minor_formatter(NullFormatter())   # 로그축 보조 눈금 숫자가 작은 칸에서 겹친다
            a.yaxis.set_minor_formatter(NullFormatter())

    def _share_x(self, drawn):
        """같은 열(1칸 폭)의 단일 축 패널끼리 x 범위를 합쳐 공유하고, 맨 아래만 x 눈금·라벨."""
        cols = {}
        for i, axes in drawn.items():
            p = self.panels[i]
            if "cell" not in p or len(axes) != 1 or p["cell"][3] != 1:
                continue
            cols.setdefault(p["cell"][1], []).append((p["cell"][0], axes[0]))
        for group in cols.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda t: t[0])
            lo = min(a.get_xlim()[0] for _, a in group)
            hi = max(a.get_xlim()[1] for _, a in group)
            ref = group[-1][1]
            for _, a in group[:-1]:
                a.sharex(ref)
                a.tick_params(axis="x", labelbottom=False)
                a.set_xlabel("")
            ref.set_xlim(lo, hi)

    def tight(self, fig):
        """조판은 constrained layout이 맡는다(build_fig에서 설정) — 여기선 아무것도 안 한다.
        호출측(_build_publish_fig)이 단일 그림과 같은 자리에서 부르도록 남겨둔 훅."""
        return fig

    # ── UI (Layout 탭) ─────────────────────────────────────────────────
    def widget(self):
        if self._w is not None:
            return self._w
        w = self._w = QWidget()
        v = QVBoxLayout(w)
        self._chk_on = QCheckBox("Compose a multi-panel figure (Preview / Publish)")
        self._chk_on.setToolTip("The screen keeps showing one panel (the one you edit).\n"
                                "Preview and Publish draw the whole layout.")
        self._chk_on.toggled.connect(self._on_toggle)
        v.addWidget(self._chk_on)
        form = QFormLayout()
        g = QHBoxLayout()
        self._sp_rows = QSpinBox(); self._sp_rows.setRange(1, 6)
        self._sp_cols = QSpinBox(); self._sp_cols.setRange(1, 6)
        g.addWidget(QLabel("rows")); g.addWidget(self._sp_rows)
        g.addWidget(QLabel("cols")); g.addWidget(self._sp_cols)
        form.addRow("Grid", g)
        self._ed_hr = QLineEdit(); self._ed_hr.setPlaceholderText("e.g. 2,1  (empty = equal)")
        self._ed_wr = QLineEdit(); self._ed_wr.setPlaceholderText("e.g. 1,1")
        form.addRow("Row heights", self._ed_hr)
        form.addRow("Column widths", self._ed_wr)
        self._chk_sx = QCheckBox("Share x within a column (only the bottom panel shows x ticks)")
        self._chk_lt = QCheckBox("Panel letters (a) (b) (c)")
        form.addRow(self._chk_sx)
        form.addRow(self._chk_lt)
        v.addLayout(form)
        for sp in (self._sp_rows, self._sp_cols):
            sp.valueChanged.connect(self._pull)
        for ed in (self._ed_hr, self._ed_wr):
            ed.editingFinished.connect(self._pull)
        for ch in (self._chk_sx, self._chk_lt):
            ch.toggled.connect(self._pull)

        v.addWidget(QLabel("Panels (double-click = edit in the other tabs)"))
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda it: self.edit(self._list.row(it)))
        v.addWidget(self._list, 1)
        r1 = QHBoxLayout()
        for txt, fn, tip in (
                ("Add current plot", self.add_current, "Add what the screen shows now as a new panel"),
                ("Edit", lambda: self.edit(self._list.currentRow()),
                 "Load the selected panel into the editor — changes in the other tabs go into it"),
                ("Stop editing", self.stop_editing, "Unbind the editor (panels stay as they are)")):
            b = QPushButton(txt); b.setToolTip(tip); b.clicked.connect(fn); r1.addWidget(b)
        v.addLayout(r1)
        r2 = QHBoxLayout()
        for txt, fn, tip in (
                ("Cell / inset…", self._edit_cell, "Position, span, or put it as an inset in another panel"),
                ("Remove", lambda: self.remove(self._list.currentRow()), "Remove the selected panel")):
            b = QPushButton(txt); b.setToolTip(tip); b.clicked.connect(fn); r2.addWidget(b)
        r2.addStretch(1)
        v.addLayout(r2)
        self._lbl = QLabel(" ")
        self._lbl.setWordWrap(True)
        v.addWidget(self._lbl)
        self.sync_widgets()
        return w

    def _on_toggle(self, on):
        self.on = bool(on)
        self.sync_widgets()

    def _pull(self, *_):
        self.rows, self.cols = self._sp_rows.value(), self._sp_cols.value()
        self.hratios, self.wratios = self._ed_hr.text().strip(), self._ed_wr.text().strip()
        self.sharex, self.letters = self._chk_sx.isChecked(), self._chk_lt.isChecked()
        self.sync_widgets(list_only=True)

    def describe(self, i):
        p = self.panels[i]
        mode = next((m.label for m in self.host._modes if m.key == p.get("mode")), p.get("mode"))
        cols = []
        def walk(v):
            if isinstance(v, str) and ":" in v:
                cols.append(v.split(":", 1)[1])
            elif isinstance(v, (list, tuple)):
                for x in v:
                    walk(x)
            elif isinstance(v, dict):
                for x in v.values():
                    walk(x)
        walk(p.get("mode_cfg"))
        where = ""
        if "cell" in p:
            r, c, rs, cs = p["cell"]
            span = f" ({rs}×{cs})" if (rs, cs) != (1, 1) else ""
            where = f"r{r + 1}c{c + 1}{span}"
        elif "inset" in p:
            where = f"inset in ({LETTERS[p['inset'].get('in', 0) % 26]})"
        what = ", ".join(dict.fromkeys(cols))[:60]
        mark = "  ✎" if i == self.editing else ""
        return f"({LETTERS[i % 26]}) {where} · {mode}{' · ' + what if what else ''}{mark}"

    def sync_widgets(self, list_only=False):
        if self._w is None:
            return
        if not list_only:
            for wdg, val in ((self._chk_on, self.on), (self._chk_sx, self.sharex),
                             (self._chk_lt, self.letters)):
                b = QSignalBlocker(wdg); wdg.setChecked(val); del b
            for wdg, val in ((self._sp_rows, self.rows), (self._sp_cols, self.cols)):
                b = QSignalBlocker(wdg); wdg.setValue(val); del b
            for wdg, val in ((self._ed_hr, self.hratios), (self._ed_wr, self.wratios)):
                b = QSignalBlocker(wdg); wdg.setText(val); del b
        cur = self._list.currentRow()
        self._list.clear()
        for i in range(len(self.panels)):
            self._list.addItem(self.describe(i))
        if 0 <= cur < self._list.count():
            self._list.setCurrentRow(cur)
        if self.editing is not None:
            self._lbl.setText(f"✎ Editing panel ({LETTERS[self.editing % 26]}) — changes in the other "
                              "tabs go into this panel.")
            self._lbl.setStyleSheet(f"color:{AUGUR.info};")
        else:
            self._lbl.setText("Editor not bound to a panel — 'Add current plot' or double-click a panel.")
            self._lbl.setStyleSheet(f"color:{AUGUR.sub};")

    def _edit_cell(self):
        i = self._list.currentRow()
        if not (0 <= i < len(self.panels)):
            return
        p = self.panels[i]
        dlg = QDialog(self._w)
        dlg.setWindowTitle(f"Panel ({LETTERS[i % 26]}) — position")
        f = QFormLayout(dlg)
        r, c, rs, cs = p.get("cell", [0, 0, 1, 1])
        sp = []
        for lab, val, hi in (("Row", r + 1, 6), ("Column", c + 1, 6), ("Row span", rs, 6), ("Column span", cs, 6)):
            s = QSpinBox(); s.setRange(1, hi); s.setValue(val); f.addRow(lab, s); sp.append(s)
        chk = QCheckBox("Inset inside another panel")
        chk.setChecked("inset" in p)
        f.addRow(chk)
        cb = QComboBox()
        others = [j for j in range(len(self.panels)) if j != i and "inset" not in self.panels[j]]
        for j in others:
            cb.addItem(f"({LETTERS[j % 26]})", j)
        ins = p.get("inset") or {}
        if ins.get("in") in others:
            cb.setCurrentIndex(others.index(ins["in"]))
        f.addRow("Inside", cb)
        rect = ins.get("rect") or [0.58, 0.58, 0.38, 0.38]
        rs_ = []
        for lab, val in zip(("x", "y", "width", "height"), rect):
            d = QDoubleSpinBox(); d.setRange(0.0, 1.0); d.setDecimals(2); d.setSingleStep(0.05)
            d.setValue(val); f.addRow(f"Inset {lab} (axes fraction)", d); rs_.append(d)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.set_position(i, cell=[sp[0].value() - 1, sp[1].value() - 1, sp[2].value(), sp[3].value()],
                          inset=({"in": cb.currentData(), "rect": [d.value() for d in rs_]}
                                 if chk.isChecked() and cb.count() else None))

    def set_position(self, i, cell=None, inset=None):
        p = self.panels[i]
        if inset is not None:
            p.pop("cell", None)
            p["inset"] = dict(inset)
        else:
            p.pop("inset", None)
            p["cell"] = list(cell)
            r, c, rs, cs = p["cell"]
            self.rows, self.cols = max(self.rows, r + rs), max(self.cols, c + cs)
        self._fit_grid()
        self.sync_widgets()

    def _fit_grid(self):
        """쓰지 않는 행·열을 걷어낸다 — 칸이 다 차서 늘린 줄에 있던 패널을 inset으로 옮기면 빈 줄이
        그림 아래에 남았다(실측: 그림 1/4이 공백)."""
        cells = [p["cell"] for p in self.panels if "cell" in p]
        if not cells:
            return
        self.rows = max(1, max(r + rs for r, c, rs, cs in cells))
        self.cols = max(1, max(c + cs for r, c, rs, cs in cells))

