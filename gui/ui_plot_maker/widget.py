# -*- coding: utf-8 -*-
"""Plot Maker — 호스트 위젯(PlotMakerWidget): 탭 UI(Data/Style/Axes/Legend/Export)·
데이터 선반·설정 저장/불러오기·Publish. 6개 모드(core._MODES)를 갈아끼우며 그린다.
"""
from __future__ import annotations

import os
import json
import re
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QComboBox, QSplitter, QTreeWidget, QTreeWidgetItem, QListWidget,
    QMessageBox, QSpinBox, QDoubleSpinBox, QSizePolicy,
    QStackedWidget, QCheckBox, QLineEdit, QGroupBox, QFormLayout, QTabWidget,
    QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt, QSettings

from .core import _MODES, _shade, mathtext_to_html, has_markup
from gui.theme import AUGUR
from .data import Dataset, load_spec, make_join
from . import modes as _modes_registration  # noqa: F401 — import 자체가 @register_mode 실행(등록) 트리거


class _DraggableLabel(pg.TextItem):
    """제목/축라벨 자유배치용 — ViewBox(데이터좌표계)가 아니라 씬에 직접 붙여서
    ViewBox 범위 밖(축 여백)에도 보이게 한다(ViewBox는 자기 view range 밖의
    자식 아이템을 안 그리는 걸 실측으로 확인 — data 좌표 기반으로는 여백 배치가
    근본적으로 불가능했음). 위치는 matplotlib의 transAxes와 같은 개념인 'ViewBox
    사각형 기준 비율(fx,fy)'로 저장 — 창 크기가 바뀌어도, pg 미리보기·mpl
    Publish 둘 다 같은 (fx,fy)로 항상 같은 상대 위치에 온다."""

    def __init__(self, host, key, **kw):
        super().__init__(**kw)
        self.host = host
        self.key = key
        self._moving = False

    def _vb(self):
        return self.host.vb_right if self.key == "rlabel" else self.host.p1.getViewBox()

    def mouseDragEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ev.accept()
        if ev.isStart():
            self._moving = True
            self._cursor_offset = self.pos() - self.mapToParent(ev.buttonDownPos())
        if not self._moving:
            return
        new_pos = self._cursor_offset + self.mapToParent(ev.pos())
        self.setPos(new_pos)
        if ev.isFinish():
            self._moving = False
            rect = self._vb().sceneBoundingRect()
            fx = (new_pos.x() - rect.left()) / rect.width() if rect.width() else 0.5
            fy = (rect.bottom() - new_pos.y()) / rect.height() if rect.height() else 0.5
            st = self.host.label_style.setdefault(self.key, {})
            st["pos"] = (float(fx), float(fy))
            self.host.set_status(f"'{self.key}' label moved — use Reset positions to undo")


# 리샘플 콤보 라벨 → 초. 0 = 원본 유지. Custom은 옆 스핀박스(분)로 사용자가 직접 지정.
_RESAMPLE_CUSTOM = "Custom…"
_RESAMPLE = {"Raw": 0, "1 min": 60, "5 min": 300, "10 min": 600,
             "30 min": 1800, "1 hour": 3600, _RESAMPLE_CUSTOM: -1}

# 범례 위치: pyqtgraph offset(음수=우/하단 기준) · matplotlib loc 문자열
_LEGEND_OFFSET = {"TL": (10, 10), "TR": (-10, 10), "BL": (10, -10), "BR": (-10, -10)}
_LEGEND_MPL = {"auto": "best", "TL": "upper left", "TR": "upper right",
               "BL": "lower left", "BR": "lower right"}


# 색 계열 프리셋: 계통색 하나 고르면 그 계열 톤들로 자동 배색.
# 값 = 대표(중간 톤). 여러 시리즈/곡선은 _family_shades로 진↔연 퍼뜨림.
_FAMILIES = {
    "Red": "#E53935", "Orange": "#FB8C00", "Yellow": "#F9A825", "Green": "#43A047",
    "Teal": "#00ACC1", "Blue": "#1E88E5", "Indigo": "#3949AB", "Purple": "#8E24AA",
    "Pink": "#D81B60", "Brown": "#6D4C41", "Gray": "#757575",
}
_PALETTE_AUTO = "Auto (by species)"

# 범주형(categorical) 팔레트 — _FAMILIES처럼 한 색의 진↔연이 아니라, **서로 구분되는
# 색 목록**을 시리즈 순서대로 쓴다.
# Okabe-Ito: 세 가지 색각이상(P·D·T) 모두에서 구분되게 설계된 사실상의 표준
# (R 4.0+ 기본 팔레트, Nature/Science 계열 접근성 권고). 순서도 원안 그대로 —
# 앞쪽 4개만 써도 구분되게 배열돼 있다.
# ⚠ 5번째 노랑(#F0E442)은 흰 배경의 **가는 선**에서 잘 안 보인다. 시리즈가 5개를
#    넘으면 그 시리즈만 색을 따로 잡거나 선을 굵게 하는 게 낫다.
# Publish 크기 프리셋 → (가로 in, 세로 in, dpi).
# 논문 폭은 Copernicus(ACP·AMT) 규정에서: 최소 8 cm, 단컬럼 8.3 cm(3.27 in),
# 양컬럼 17 cm(6.69 in), 300 dpi. 높이는 흔한 비율의 출발점일 뿐 — 손으로 바꾸면 된다.
_PUBLISH_PRESETS = {
    "Paper, 1 column (8.3 cm)": (3.27, 2.45, 300),
    "Paper, 2 columns (17 cm)": (6.69, 3.94, 300),
    "Slide (16:9)": (13.33, 7.50, 150),
    "Report (wide)": (10.0, 5.5, 200),
}

_CATEGORICAL = {
    "Okabe-Ito (colorblind-safe)": ["#000000", "#E69F00", "#56B4E9", "#009E73",
                             "#F0E442", "#0072B2", "#D55E00", "#CC79A7"],
}


def _family_shades(base, n):
    """계통색 base에서 n개의 '같은 계열' 톤을 진한→연한 순으로. n=1이면 base 그대로.
    같은 종/그룹임을 유지하면서 구분되게(진↔연). diurnal 3곡선·다중 시리즈 공용."""
    if n <= 1:
        return [base]
    out = []
    for i in range(n):
        f = -0.12 + (0.62 - (-0.12)) * (i / (n - 1))   # -0.12(약간 진함)~+0.62(연함)
        out.append(_shade(base, f))
    return out


# 모드별 권장 Publish 크기(인치, W×H). 해석자 관점에서 적합한 종횡비.
# 시계열=가로로 길게, diurnal/scatter/histogram=정사각에 가깝게.
_RECOMMENDED_SIZE = {
    "timeseries": (10.0, 3.6), "diurnal": (6.0, 5.2), "scatter": (5.6, 5.2),
    "allan": (6.0, 5.0), "histogram": (6.4, 4.4), "heatmap": (7.2, 5.0),
}

# 테마 프리셋: 한 번에 폰트/선두께/범례/팔레트 톤을 맞춤. _apply_theme에서 사용.
_THEMES = {
    "Default":  {"font": 0,  "line": 2, "legend": 0,  "grid": True},
    "Paper":  {"font": 11, "line": 1, "legend": 9,  "grid": True},
    "PPT":   {"font": 16, "line": 3, "legend": 15, "grid": True},
    "Dark":  {"font": 13, "line": 2, "legend": 12, "grid": True},
    # 저널 프리셋 — 크기·색까지 한 번에. **규정에서 온 것**: 폭(8.3/17 cm), 벡터+폰트 임베딩
    # (M-F에서 이미 기본), 한 sans-serif 패밀리(M-K). **우리가 고른 출발값**(규정 아님):
    # 8 pt 라벨·7 pt 눈금/범례(1열 폭에서 읽히는 최소 근처), 눈금 안쪽, 격자 끔, Okabe-Ito.
    "Copernicus (ACP/AMT) — 1 column": {
        "font": 8, "line": 1, "legend": 7, "grid": False, "tick": 7, "tick_dir": "In",
        "palette": "Okabe-Ito (colorblind-safe)", "publish": "Paper, 1 column (8.3 cm)"},
    "Copernicus (ACP/AMT) — 2 columns": {
        "font": 9, "line": 1, "legend": 8, "grid": False, "tick": 8, "tick_dir": "In",
        "palette": "Okabe-Ito (colorblind-safe)", "publish": "Paper, 2 columns (17 cm)"},
}


class PlotMakerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.shelf = {}        # name → Dataset
        self.resample_sec = 0
        self.smooth_n = 1
        self.time_shift_hours = 0.0   # 표시 전용 시각 보정(원본 파일은 그대로) — resolve()에서 적용
        self.legend = None
        # 라벨 오버라이드(빈 문자열=자동). 모드가 host.lbl(key, default)로 참조.
        self.custom = {"title": "", "xlabel": "", "ylabel": "", "rlabel": ""}
        # 라벨별 스타일: size/color(둘 다 None=자동) + pos(None=기본 위치,
        # (x,y) 데이터좌표=드래그로 자유배치). pg_label()/mpl_label()이 참조하는
        # 단일 진실원 — 화면(pg)·Publish(mpl)가 같은 값을 그린다.
        self.label_style = {k: {"pos": None, "size": None, "color": None}
                            for k in ("title", "xlabel", "ylabel", "rlabel")}
        self._custom_label_items = {}   # key → 화면에 떠 있는 _DraggableLabel(pg)
        # 주석(마커선): [{kind:'vline'/'hline', val:float, label:str, color:str}, ...]
        self._annots = []
        self._annot_dlg = None      # 열려있는 Annotate 창(모덜리스 싱글턴)
        self._annot_pick = None     # 클릭으로 값 찍는 중이면 {"kind","label","color"}, 아니면 None
        self._undo_slot = None   # 가벼운 1단계 undo(전체 스택 아님) — 방금 지운 것만 기억
        self._modes = [cls(self) for cls in _MODES]
        self._mode = self._modes[0]
        from .composer import Composer
        self.composer = Composer(self)   # 다중 패널 조판(M2) — Layout 탭
        self._console_pending = {}       # 설정에서 읽은 콘솔 데이터셋 {이름: spec} — rerun() 전까지 대기
        self._console_dlg = None
        self._init_ui()
        self._rebuild_mode_options()
        self.setAcceptDrops(True)   # 탐색기에서 파일을 창에 끌어놓으면 선반에 추가

    _DROP_EXTS = (".dat", ".csv", ".txt", ".tsv")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
                u.toLocalFile().lower().endswith(self._DROP_EXTS)
                for u in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.toLocalFile().lower().endswith(self._DROP_EXTS)]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def lbl(self, key, default):
        """라벨 오버라이드가 있으면 그것을, 없으면 기본값을 반환."""
        v = (self.custom.get(key) or "").strip()
        return v if v else default

    # ── UI ────────────────────────────────────────────────────────────
    def _init_ui(self):
        from gui.flow_layout import FlowLayout
        root = QVBoxLayout(self)

        def _hline():
            f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
            f.setFrameShadow(QFrame.Shadow.Sunken); f.setStyleSheet(f"color:{AUGUR.rule};")
            return f

        def _scroll(inner):
            sa = QScrollArea(); sa.setWidgetResizable(True)
            sa.setWidget(inner); sa.setFrameShape(QScrollArea.Shape.NoFrame)
            # 가로 스크롤 끔 → 내용이 폭에 맞춰 접히고 좌측 잘림 방지
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            return sa

        # ── 상단: 핵심 액션만 (세부는 전부 좌측 탭으로) ──
        bar = FlowLayout(spacing=6)
        for txt, fn, tip in (
                ("Add data", self._add_data, "Add result files (.dat/.csv) to the shelf"),
                ("By date", self._add_data_by_date,
                 "Pick a date range and series from daily fit buckets, auto-merge, and add to the shelf"),
                ("Preview", self._preview_publish, "Preview exactly as Publish will output"),
                ("Console", self._open_console,
                 "Python console with the shelf loaded (df(name), push(obj, name)) — for one-off analysis"),
                ("Publish", self._export_publish, "Save high-res PNG / vector PDF·SVG")):
            b = QPushButton(txt); b.setToolTip(tip); b.clicked.connect(fn)
            bar.addWidget(b)
        root.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        self._tabs = QTabWidget()
        self._tabs.setMinimumWidth(310)   # 270→310: 좁아서 버튼줄 잘리던 문제(2026-07-03) 여유폭 확보

        # ═══════════ Data 탭 ═══════════
        tab_data = QWidget(); dv = QVBoxLayout(tab_data)
        drow = QHBoxLayout()
        b_add2 = QPushButton("Add"); b_add2.clicked.connect(self._add_data)
        b_date2 = QPushButton("By date"); b_date2.setToolTip("Pick a date range from daily fit buckets and auto-merge")
        b_date2.clicked.connect(self._add_data_by_date)
        b_rm = QPushButton("Remove"); b_rm.setToolTip("Remove selected dataset")
        b_rm.clicked.connect(self._remove_data)
        drow.addWidget(b_add2); drow.addWidget(b_date2); drow.addWidget(b_rm); dv.addLayout(drow)
        dv.addWidget(QLabel("Data shelf — select columns, then add them in the Style tab"))
        self._tree_search = QLineEdit()
        self._tree_search.setPlaceholderText("Search datasets/columns")
        self._tree_search.setClearButtonEnabled(True)
        self._tree_search.textChanged.connect(self._filter_tree)
        dv.addWidget(self._tree_search)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self._tree.setToolTip("Double-click a column = plot it now (current mode). For several, select them and add in the Style tab.\n"
                              "Files dropped onto this window are added too.")
        self._tree.itemDoubleClicked.connect(self._on_tree_double_click)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_menu)
        dv.addWidget(self._tree, 1)
        mrow = QHBoxLayout(); mrow.addWidget(QLabel("Mode"))
        self._mode_combo = QComboBox()
        for m in self._modes:
            self._mode_combo.addItem(m.label)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mrow.addWidget(self._mode_combo, 1); dv.addLayout(mrow)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Resample"))
        self._res_combo = QComboBox(); self._res_combo.addItems(list(_RESAMPLE.keys()))
        self._res_combo.currentIndexChanged.connect(self._on_transform_changed)
        trow.addWidget(self._res_combo)
        self._res_custom_spin = QDoubleSpinBox()
        self._res_custom_spin.setRange(0.1, 1440.0); self._res_custom_spin.setValue(2.0)
        self._res_custom_spin.setSuffix(" min"); self._res_custom_spin.setDecimals(1)
        self._res_custom_spin.setToolTip("Averaging interval (min) when Resample = Custom")
        self._res_custom_spin.setEnabled(False)
        self._res_custom_spin.valueChanged.connect(self._on_transform_changed)
        trow.addWidget(self._res_custom_spin)
        trow.addWidget(QLabel("Smooth"))
        self._smooth_spin = QSpinBox(); self._smooth_spin.setRange(1, 999); self._smooth_spin.setValue(1)
        self._smooth_spin.setToolTip("Rolling-mean window in points (1 = off)")
        self._smooth_spin.valueChanged.connect(self._on_transform_changed)
        trow.addWidget(self._smooth_spin); dv.addLayout(trow)
        trow2 = QHBoxLayout()
        trow2.addWidget(QLabel("Time shift"))
        self._shift_spin = QDoubleSpinBox()
        self._shift_spin.setRange(-72.0, 72.0); self._shift_spin.setValue(0.0)
        self._shift_spin.setSuffix(" h"); self._shift_spin.setDecimals(2); self._shift_spin.setSingleStep(1.0)
        self._shift_spin.setToolTip("Shift the whole time axis by +/- hours for display (source file unchanged, display only).\n"
                                    "Use it to eyeball instrument clock drift or time-zone mismatch.")
        self._shift_spin.valueChanged.connect(self._on_transform_changed)
        trow2.addWidget(self._shift_spin); trow2.addStretch(1); dv.addLayout(trow2)
        self._tabs.addTab(_scroll(tab_data), "Data")

        # ═══════════ Style 탭 ═══════════
        tab_style = QWidget(); sv = QVBoxLayout(tab_style)
        prow = QHBoxLayout(); prow.addWidget(QLabel("Palette"))
        self._palette_combo = QComboBox()
        self._palette_combo.addItems([_PALETTE_AUTO] + list(_CATEGORICAL.keys())
                                     + list(_FAMILIES.keys()))
        self._palette_combo.setToolTip(
            "'Auto (by species)' = color from the species name (e.g. ANs green).\n"
            "'Okabe-Ito (colorblind-safe)' = standard 8 colors distinguishable under all three\n"
            "   color-vision deficiencies, in series order. Recommended default for papers/talks.\n"
            "   (5th color, yellow, is faint as a thin line on white — check if > 5 series)\n"
            "Other color families = automatic dark↔light shades of that color.")
        self._palette_combo.activated.connect(
            lambda *_: self._apply_palette(self._palette_combo.currentText()))
        prow.addWidget(self._palette_combo, 1); sv.addLayout(prow)
        thr = QHBoxLayout(); thr.addWidget(QLabel("Theme"))
        self._theme_combo = QComboBox(); self._theme_combo.addItems(list(_THEMES.keys()))
        self._theme_combo.setToolTip(
            "Look preset: font, line width, legend and grid in one go (colors unaffected).\n"
            "Copernicus (ACP/AMT) presets also set the Publish size (8.3 / 17 cm @ 300 dpi),\n"
            "tick size/direction and the Okabe-Ito palette. Width, vector output with embedded\n"
            "fonts and one sans-serif family follow the journal guidelines; the font sizes,\n"
            "inward ticks and no grid are our starting choice, not a journal rule.")
        self._theme_combo.activated.connect(lambda *_: self._on_theme_combo_changed())
        thr.addWidget(self._theme_combo, 1); sv.addLayout(thr)
        crow = QHBoxLayout()
        self._btn_colors = QPushButton("Colors")
        self._btn_colors.setToolTip("Fixed color elements of the current mode (Scatter/Allan/Histogram/Diurnal).\n"
                                    "For Time series, use the per-series Color below.")
        self._btn_colors.clicked.connect(self._edit_colors)
        self._btn_colors.setEnabled(bool(self._mode.color_keys()))
        self._btn_cursor = QPushButton("Cursor"); self._btn_cursor.setCheckable(True)
        self._btn_cursor.setToolTip("Data cursor (crosshair): shows x·y at the mouse position")
        self._btn_cursor.toggled.connect(self._toggle_cursor)
        b_annot = QPushButton("Annotate")
        b_annot.setToolTip("Annotation layer: vertical/horizontal lines · shaded spans · text · arrows · rectangles\n"
                           "Click the plot to place (twice for 2-point kinds). Labels use mathtext syntax.")
        b_annot.clicked.connect(self._edit_annotations)
        crow.addWidget(self._btn_colors); crow.addWidget(self._btn_cursor); crow.addWidget(b_annot)
        sv.addLayout(crow)
        sv.addWidget(_hline())
        sv.addWidget(QLabel("Series / mode options"))
        self._opt_stack = QStackedWidget()
        for m in self._modes:
            w = m.options_widget() or QWidget()
            self._opt_stack.addWidget(w)
        sv.addWidget(self._opt_stack, 1)
        self._tabs.addTab(_scroll(tab_style), "Style")

        # ═══════════ Axes 탭 ═══════════
        tab_axes = QWidget(); av = QVBoxLayout(tab_axes)
        gb2 = QGroupBox("Range (blank = auto)")
        gb2.setToolTip("Unparseable values get a red border (never silently fall back to auto).")
        fl2 = QFormLayout(gb2)
        self._ax_xmin = QLineEdit(); self._ax_xmax = QLineEdit()
        self._ax_ymin = QLineEdit(); self._ax_ymax = QLineEdit()
        self._ax_rmin = QLineEdit(); self._ax_rmax = QLineEdit()
        for e in (self._ax_xmin, self._ax_xmax,
                  self._ax_ymin, self._ax_ymax, self._ax_rmin, self._ax_rmax):
            e.setPlaceholderText("auto")
            e.editingFinished.connect(self._on_axes_changed)
        self._ax_xmin.setPlaceholderText("auto / 06-22 00:00")
        self._ax_xmax.setPlaceholderText("auto / 06-29 00:00")
        rowX = QHBoxLayout()
        rowX.addWidget(self._ax_xmin); rowX.addWidget(QLabel("~")); rowX.addWidget(self._ax_xmax)
        fl2.addRow("X", rowX)
        # 날짜범위 프리셋 — 매주 X min/max를 손으로 타이핑하던 걸 원클릭으로.
        # 왼쪽 패널이 좁아 버튼 3개+스핀박스를 한 줄에 다 못 넣는다(실제 GUI에서
        # "✕ 초기화"가 잘려서 안 보였던 걸 발견 → 2줄로 분리, 2026-07-03).
        b_full = QPushButton("All (whole days)")
        b_full.setToolTip("Fill X with the full shelf data range, snapped to day boundaries (00:00)\n"
                          "— same as the lab figure convention (tight x limits).")
        b_full.clicked.connect(self._preset_x_full)
        fl2.addRow("", b_full)
        rowXp = QHBoxLayout()
        b_recent = QPushButton("Last")
        self._preset_days = QSpinBox(); self._preset_days.setRange(1, 90); self._preset_days.setValue(7)
        self._preset_days.setSuffix(" d")
        b_recent.setToolTip("Fill X with the last N days of data (from 00:00, N days before the last day).")
        b_recent.clicked.connect(lambda: self._preset_x_recent(self._preset_days.value()))
        rowXp.addWidget(b_recent); rowXp.addWidget(self._preset_days)
        b_clear = QPushButton("Clear")
        b_clear.setToolTip("Clear the X range (back to auto).")
        b_clear.clicked.connect(self._preset_x_clear)
        rowXp.addWidget(b_clear)
        fl2.addRow("", rowXp)
        rowY = QHBoxLayout()
        rowY.addWidget(self._ax_ymin); rowY.addWidget(QLabel("~")); rowY.addWidget(self._ax_ymax)
        fl2.addRow("Y-left", rowY)
        rowR = QHBoxLayout()
        rowR.addWidget(self._ax_rmin); rowR.addWidget(QLabel("~")); rowR.addWidget(self._ax_rmax)
        fl2.addRow("Y-right", rowR)
        rowL = QHBoxLayout()
        self._chk_logx = QCheckBox("log X"); self._chk_logy = QCheckBox("log Y")
        self._chk_logx.toggled.connect(self._on_axes_changed)
        self._chk_logy.toggled.connect(self._on_axes_changed)
        rowL.addWidget(self._chk_logx); rowL.addWidget(self._chk_logy); rowL.addStretch(1)
        fl2.addRow("Scale", rowL)
        av.addWidget(gb2)
        # 그리드 / 눈금 제어
        gbg = QGroupBox("Grid / ticks")
        flg = QFormLayout(gbg)
        grow = QHBoxLayout()
        self._chk_grid = QCheckBox("major"); self._chk_grid.setChecked(True)
        self._chk_grid_minor = QCheckBox("minor (Publish only)")
        self._chk_grid_minor.setToolTip("The pyqtgraph view only auto-shows minor ticks — no separate\n"
                                        "on/off. Applies to Publish (matplotlib) only.")
        self._chk_grid.toggled.connect(self._on_axes_changed)
        self._chk_grid_minor.toggled.connect(self._on_axes_changed)
        grow.addWidget(self._chk_grid); grow.addWidget(self._chk_grid_minor); grow.addStretch(1)
        flg.addRow("Grid", grow)
        self._tick_x = QLineEdit(); self._tick_x.setPlaceholderText("auto (time axis = days, e.g. 1)")
        self._tick_y = QLineEdit(); self._tick_y.setPlaceholderText("auto (e.g. 0.5)")
        self._tick_x.setToolTip("X tick spacing. On a time axis, in days (1 = a tick every 00:00). Blank = auto.\n"
                                "Check the exact spacing in Publish/Preview (the screen is approximate).")
        self._tick_y.setToolTip("Y tick spacing (in data units). Blank = auto.\n"
                                "Check the exact spacing in Publish/Preview (the screen is approximate).")
        self._tick_x.editingFinished.connect(self._on_axes_changed)
        self._tick_y.editingFinished.connect(self._on_axes_changed)
        trow_x = QHBoxLayout()
        trow_x.addWidget(self._tick_x, 1)
        self._tick_x_anchor = QLineEdit()
        self._tick_x_anchor.setPlaceholderText("Anchor (e.g. 06-29)")
        self._tick_x_anchor.setToolTip("Reference date for time-axis ticks — ticks every N days (left field) from this date.\n"
                                       "e.g. anchor 06-29 + spacing 7 → 06-29, 07-06, 07-13… (and back: 06-22, 06-15…)\n"
                                       "Blank = automatic (calendar-based). Applies to screen and Publish.")
        self._tick_x_anchor.editingFinished.connect(self._on_axes_changed)
        trow_x.addWidget(self._tick_x_anchor, 1)
        flg.addRow("X tick", trow_x)
        flg.addRow("Y tick", self._tick_y)
        srow = QHBoxLayout()
        self._tick_dir = QComboBox(); self._tick_dir.addItems(["Out", "In"])
        self._tick_dir.setToolTip("Tick direction — outside or inside the axes. Applies to screen and Publish.")
        self._tick_dir.currentIndexChanged.connect(self._on_axes_changed)
        srow.addWidget(self._tick_dir)
        srow.addWidget(QLabel("Length"))
        self._tick_len = QSpinBox()
        self._tick_len.setRange(0, 20); self._tick_len.setValue(0)
        self._tick_len.setSpecialValueText("auto"); self._tick_len.setSuffix(" px")
        self._tick_len.setToolTip("Tick length (0 = auto ≈ 5 px). Applies to screen and Publish.")
        self._tick_len.valueChanged.connect(self._on_axes_changed)
        srow.addWidget(self._tick_len); srow.addStretch(1)
        flg.addRow("Tick marks", srow)
        av.addWidget(gbg)
        # 축 라벨·눈금 표시 토글 (끄면 아예 안 그림)
        gbsh = QGroupBox("Show (uncheck to hide)")
        flsh = QFormLayout(gbsh)
        self._chk_xlabel = QCheckBox("label"); self._chk_xticks = QCheckBox("Tick labels")
        self._chk_ylabel = QCheckBox("label"); self._chk_yticks = QCheckBox("Tick labels")
        self._chk_xtickmarks = QCheckBox("Ticks"); self._chk_ytickmarks = QCheckBox("Ticks")
        for c in (self._chk_xlabel, self._chk_xticks, self._chk_ylabel, self._chk_yticks,
                  self._chk_xtickmarks, self._chk_ytickmarks):
            c.setChecked(True); c.toggled.connect(self._on_axes_changed)
        self._chk_xlabel.setToolTip("Show the X-axis title (e.g. Time)")
        self._chk_xticks.setToolTip("Show X-axis tick labels (numbers/dates)")
        self._chk_xtickmarks.setToolTip("Show X-axis tick marks — can keep the marks with tick labels hidden")
        self._chk_ytickmarks.setToolTip("Show Y-axis tick marks — can keep the marks with tick labels hidden")
        rxs = QHBoxLayout(); rxs.addWidget(self._chk_xlabel); rxs.addWidget(self._chk_xticks)
        rxs.addWidget(self._chk_xtickmarks); rxs.addStretch(1)
        rys = QHBoxLayout(); rys.addWidget(self._chk_ylabel); rys.addWidget(self._chk_yticks)
        rys.addWidget(self._chk_ytickmarks); rys.addStretch(1)
        flsh.addRow("X axis", rxs)
        flsh.addRow("Y axis", rys)
        av.addWidget(gbsh)
        av.addStretch(1)
        self._tabs.addTab(_scroll(tab_axes), "Axes")

        # ═══════════ Legend & Labels 탭 ═══════════
        tab_leg = QWidget(); gv = QVBoxLayout(tab_leg)
        gbl = QGroupBox("Legend")
        fll = QFormLayout(gbl)
        self._legend_combo = QComboBox()
        self._legend_combo.addItems(["auto", "TL", "TR", "BL", "BR", "off"])
        self._legend_combo.setToolTip("Legend position (auto = placed clear of data · TL/TR/BL/BR · off = hidden)")
        self._legend_combo.currentIndexChanged.connect(self._on_legend_changed)
        fll.addRow("Position", self._legend_combo)
        self._legend_size = QSpinBox()
        self._legend_size.setRange(0, 40); self._legend_size.setValue(0)
        self._legend_size.setSpecialValueText("auto"); self._legend_size.setSuffix(" pt")
        self._legend_size.setToolTip("Legend font size (0 = auto). Applies to Publish.")
        self._legend_size.valueChanged.connect(self._on_legend_changed)
        fll.addRow("Size", self._legend_size)
        gv.addWidget(gbl)
        gb = QGroupBox("Labels (override, blank=auto)")
        gb.setToolTip("Math uses mathtext syntax — rendered identically on screen and in Publish.\n"
                      "  NO$_2$        → NO₂\n"
                      "  $\\mu$g m$^{-3}$ → μg m⁻³\n"
                      "  $\\times$10$^{-9}$ → ×10⁻⁹\n"
                      "The same syntax works in legend names (series ✎ Rename) and annotation labels.\n"
                      "⚠ Mixing Korean text and $…$ in **one** label renders the Korean as □\n"
                      "   (matplotlib's math engine has no Hangul glyphs). Use one or the other.")
        fl = QFormLayout(gb)
        self._label_style_widgets = {}
        self._ed_title = QLineEdit(); self._ed_x = QLineEdit()
        self._ed_y = QLineEdit(); self._ed_r = QLineEdit()
        fl.addRow("Title", self._build_label_row("title", self._ed_title))
        fl.addRow("X", self._build_label_row("xlabel", self._ed_x))
        fl.addRow("Y-left", self._build_label_row("ylabel", self._ed_y))
        fl.addRow("Y-right", self._build_label_row("rlabel", self._ed_r))
        self._lbl_size = QSpinBox()
        self._lbl_size.setRange(0, 40); self._lbl_size.setValue(0)
        self._lbl_size.setSpecialValueText("auto"); self._lbl_size.setSuffix(" pt")
        self._lbl_size.setToolTip("Global default font size (0 = auto). Used by any label whose Size is 0.")
        self._lbl_size.valueChanged.connect(self._on_labels_changed)
        fl.addRow("Font size (default)", self._lbl_size)
        self._tick_size = QSpinBox()
        self._tick_size.setRange(0, 40); self._tick_size.setValue(0)
        self._tick_size.setSpecialValueText("auto"); self._tick_size.setSuffix(" pt")
        self._tick_size.setToolTip("Tick label font size (0 = auto: global Font size − 2).\n"
                                   "Applies to the screen preview and Publish.")
        self._tick_size.valueChanged.connect(self._on_labels_changed)
        fl.addRow("Tick size", self._tick_size)
        btn_reset_pos = QPushButton("↺ Reset positions")
        btn_reset_pos.setToolTip("Reset all dragged label positions to default (size/color kept)")
        btn_reset_pos.clicked.connect(self.reset_label_positions)
        fl.addRow("", btn_reset_pos)
        gv.addWidget(gb)
        gv.addStretch(1)
        self._tabs.addTab(_scroll(tab_leg), "Legend")

        # ═══════════ Export 탭 ═══════════
        tab_exp = QWidget(); xv = QVBoxLayout(tab_exp)
        gbs = QGroupBox("Publish size")
        fls = QFormLayout(gbs)
        self._preset_combo = QComboBox()
        self._preset_combo.addItems(["(Custom)"] + list(_PUBLISH_PRESETS.keys()))
        self._preset_combo.setToolTip(
            "Size/resolution presets by purpose. Paper widths follow Copernicus (ACP·AMT)\n"
            "— single column 8.3 cm, double column 17 cm, 300 dpi (min. width 8 cm).\n"
            "Choosing one turns off 'Auto size per mode' (so mode changes don't overwrite it).")
        self._preset_combo.activated.connect(
            lambda *_: self._apply_publish_preset(self._preset_combo.currentText()))
        fls.addRow("Preset", self._preset_combo)
        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(72, 1200); self._dpi_spin.setValue(300); self._dpi_spin.setSingleStep(50)
        self._dpi_spin.setToolTip("Publish PNG resolution (not used for vector PDF/SVG). PPT = 150–200, paper = 300–600")
        fls.addRow("DPI (PNG)", self._dpi_spin)
        szr = QHBoxLayout()
        self._fig_w = QDoubleSpinBox(); self._fig_w.setRange(2.0, 40.0); self._fig_w.setValue(10.0)
        self._fig_w.setSingleStep(0.5); self._fig_w.setDecimals(2); self._fig_w.setToolTip("Width (in)")
        self._fig_h = QDoubleSpinBox(); self._fig_h.setRange(1.5, 40.0); self._fig_h.setValue(5.5)
        self._fig_h.setSingleStep(0.5); self._fig_h.setDecimals(2); self._fig_h.setToolTip("Height (in)")
        szr.addWidget(QLabel("W")); szr.addWidget(self._fig_w)
        szr.addWidget(QLabel("H")); szr.addWidget(self._fig_h)
        fls.addRow("Size (in)", szr)
        self._chk_autosize = QCheckBox("Auto size per mode")
        self._chk_autosize.setChecked(True)
        self._chk_autosize.setToolTip("On mode change, set the recommended W×H for that plot type\n"
                                      "(time series = wide, diurnal = square, etc.). Off = keep manual size.")
        b_fit = QPushButton("Apply recommended size")
        b_fit.setToolTip("Apply the current mode's recommended size now")
        b_fit.clicked.connect(lambda: self._apply_recommended_size(force=True))
        fls.addRow(self._chk_autosize)
        fls.addRow(b_fit)
        xv.addWidget(gbs)
        # 버튼 9개를 flat하게 쌓지 않고 성격별로 그룹박스 분리(스캔하기 쉽게,
        # Axes 탭의 Range/Grid/Show 구분과 같은 관례). 2026-07-03 실GUI로
        # 훑어보며 "Export만 그룹 없이 튄다"고 짚인 것 반영.
        def _btn_group(title, entries):
            gb = QGroupBox(title)
            lay = QVBoxLayout(gb)
            for txt, fn, tip in entries:
                b = QPushButton(txt); b.setToolTip(tip); b.clicked.connect(fn)
                lay.addWidget(b)
            xv.addWidget(gb)

        _btn_group("Export image", [
            ("Publish (PNG/PDF/SVG)", self._export_publish, "matplotlib high-res output"),
            ("Batch Publish (per species)", self._batch_publish,
             "Save each column of the Time series/Diurnal series list as its own PNG in one go\n"
             "— automates the weekly per-species Publish. Uses the Time series list in the Style tab."),
            ("Quick PNG (as on screen)", self._export_png, "Quick pyqtgraph capture (2400 px)"),
            ("Copy to clipboard (Ctrl+C)", self._copy_to_clipboard,
             "Copy without saving a file → Ctrl+V into PPT/documents"),
        ])
        _btn_group("Export data", [
            ("Export CSV", self._export_csv, "Current mode data as CSV"),
        ])
        _btn_group("Save / load settings", [
            ("Save config", self._save_cfg, "Save the whole plot (data + axes + labels + colors) — like a MATLAB .fig"),
            ("Load config", self._load_cfg, "Load a saved plot config"),
            ("Save style", self._save_template, "Save the look only (colors, fonts, legend, night shading) as a template"),
            ("Load style", self._load_template, "Apply a saved look to the current plot"),
        ])
        xv.addStretch(1)
        self._tabs.addTab(_scroll(tab_exp), "Export")
        self._tabs.addTab(_scroll(self.composer.widget()), "Layout")

        split.addWidget(self._tabs)

        # 우: 플롯
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.pw = pg.PlotWidget()
        self.pw.setBackground("w")
        self.pw.showGrid(x=True, y=True, alpha=0.3)
        self.p1 = self.pw.plotItem
        # pg auto-SI-prefix 끔 — 켜져 있으면 축 범위가 작을 때(예: 0~0.6 ppb)
        # 값을 ×1000해 200/400/600으로 표시하고 "(×0.001)"을 붙임. matplotlib
        # Publish는 원시값 그대로라 화면-출력이 어긋난다(2026-07-07 실GUI 발견).
        for _nm in ("left", "right", "bottom"):
            self.p1.getAxis(_nm).enableAutoSIPrefix(False)
        self.legend = self.p1.addLegend(offset=(10, 10))
        # 우측 Y축용 보조 ViewBox
        self.vb_right = pg.ViewBox()
        self.p1.scene().addItem(self.vb_right)
        self.p1.getAxis("right").linkToView(self.vb_right)
        self.vb_right.setXLink(self.p1)
        self.p1.vb.sigResized.connect(self.update_views)
        # 줌/팬/창크기 변경 → 화살촉 각도 재계산(각도는 픽셀 기준이라 범위에 딸림)
        self.p1.vb.sigRangeChanged.connect(lambda *_: self._update_annot_arrows())
        self.p1.vb.sigResized.connect(lambda *_: self._update_annot_arrows())
        self._annot_arrows = []
        # 데이터 커서(크로스헤어) — ⌖ Cursor 토글로 켜짐
        self._time_axis = False
        self._cursor_on = False
        self._cur_v = pg.InfiniteLine(angle=90, movable=False,
                                      pen=pg.mkPen("#888", style=Qt.PenStyle.DashLine))
        self._cur_h = pg.InfiniteLine(angle=0, movable=False,
                                      pen=pg.mkPen("#888", style=Qt.PenStyle.DashLine))
        for _ln in (self._cur_v, self._cur_h):
            _ln.setZValue(200); _ln.setVisible(False)
            self.p1.addItem(_ln, ignoreBounds=True)
        self.p1.scene().sigMouseMoved.connect(self._on_cursor_move)
        self.p1.scene().sigMouseClicked.connect(self._on_plot_clicked)
        rv.addWidget(self.pw, 1)
        self._status = QLabel("")
        self._status.setStyleSheet(f"color:{AUGUR.sub};")
        self._status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        rv.addWidget(self._status)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)        # 플롯이 늘어나는 쪽
        split.setSizes([340, 840])   # 초기 폭도 같이 넓힘(저장된 QSettings 있으면 그게 우선)
        root.addWidget(split, 1)
        self._split = split   # 창 상태 기억(스플리터 폭)용 보관

        # 창 상태 기억(스플리터 폭·마지막 탭·마지막 테마) — 앱 전역 공용
        # QSettings("CAESAR","app") 재사용(dlg_dir.py와 같은 네임스페이스 관례,
        # 키만 "plotmaker/"로 구분). 세션 넘어 유지되면 좋은 것만(리샘플·시리즈
        # 선택 등 데이터 종속 상태는 제외 — 그건 💾 Save config의 몫).
        self._qs = QSettings("CAESAR", "app")
        self._restore_window_state()
        split.splitterMoved.connect(lambda *_: self._save_window_state())
        self._tabs.currentChanged.connect(lambda *_: self._save_window_state())

        # 플롯 영역 안에서만 Ctrl+C = 클립보드 복사(다른 탭 QLineEdit의 텍스트
        # 복사와 안 겹치게 self 전체가 아닌 right 패널에만 건다).
        from PyQt6.QtGui import QShortcut as _QSC, QKeySequence as _QKS
        _QSC(_QKS.StandardKey.Copy, right,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut
            ).activated.connect(self._copy_to_clipboard)

        # ── 전역 단축키(이 탭 안에서만 — WidgetWithChildrenShortcut) ──────
        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence.StandardKey.Undo, self,
                 context=Qt.ShortcutContext.WidgetWithChildrenShortcut
                 ).activated.connect(self.undo_last)              # Ctrl+Z
        QShortcut(QKeySequence.StandardKey.Save, self,
                 context=Qt.ShortcutContext.WidgetWithChildrenShortcut
                 ).activated.connect(self._save_cfg)               # Ctrl+S

    # ── 플롯 헬퍼(모드에서 호출) ────────────────────────────────────────
    def clear_plot(self):
        # 이전 legend를 명시적으로 제거(아직 scene에 붙어 있으면) 후 plotItem clear.
        if self.legend is not None:
            sc = self.legend.scene()
            if sc is not None:
                sc.removeItem(self.legend)
        self.p1.clear()
        self.vb_right.clear()
        self.p1.setLogMode(x=False, y=False)
        # 히트맵이 남긴 invertY/커스텀틱을 원복(다른 모드 오염 방지)
        self.p1.invertY(False)
        for axn in ("bottom", "left"):
            self.p1.getAxis(axn).setTicks(None)
        loc = self._legend_combo.currentText() if hasattr(self, "_legend_combo") else "TL"
        self.legend = (None if loc == "off"
                       else self.p1.addLegend(offset=_LEGEND_OFFSET.get(loc, (10, 10))))
        # p1.clear()가 크로스헤어도 제거 → 재추가(가시성 유지)
        if hasattr(self, "_cur_v"):
            for _ln in (self._cur_v, self._cur_h):
                self.p1.addItem(_ln, ignoreBounds=True)
                _ln.setVisible(self._cursor_on)
        self._draw_annotations_pg()

    # ── 주석 레이어 (M3) ────────────────────────────────────────────────
    # kind → (표시명, 필요한 클릭 수, 값 입력으로도 만들 수 있나)
    # 좌표는 전부 **데이터 좌표**다. 축 비율 좌표("그림 왼쪽 위에 (a)")는 일부러
    # 안 넣었다 — pg는 줌하면 어긋나고(화면≠출력), 그 용도는 M2 Composer의 패널
    # 자동 라벨이 더 싸게 해결한다.
    _ANNOT_KINDS = {
        "vline": ("Vertical line (x)", 1, True),
        "hline": ("Horizontal line (y)", 1, True),
        "vspan": ("Vertical shaded span (x1–x2)", 2, True),
        "hspan": ("Horizontal shaded span (y1–y2)", 2, True),
        "text":  ("Text", 1, False),
        "arrow": ("Arrow (point → label)", 2, False),
        "rect":  ("Rectangle", 2, False),
    }

    @staticmethod
    def _annot_norm(a):
        """옛 레코드({"kind","val",…})를 현재 스키마(x1,y1,x2,y2)로 올린다.
        예전 설정/세션이 그대로 살아야 하므로 읽는 쪽에서 흡수한다."""
        if "val" in a and "x1" not in a and "y1" not in a:
            a = dict(a)
            v = a.pop("val")
            a["y1" if a.get("kind") == "hline" else "x1"] = v
        if "visible" not in a:      # 옛 레코드에는 없다 — 기본은 보이기
            a = dict(a)
            a["visible"] = True
        return a

    @staticmethod
    def _annot_from_points(kind, pts, label, color):
        """클릭 좌표 [(x,y), …] → 주석 레코드. 종류마다 쓰는 좌표가 다르다:
        세로선은 x만, 가로선은 y만, 구간은 그 축의 두 값, 화살표는
        (첫 클릭=가리킬 점, 둘째=라벨 자리), 사각형은 두 모서리."""
        rec = {"kind": kind, "label": label, "color": color}
        (x1, y1) = pts[0]
        (x2, y2) = pts[1] if len(pts) > 1 else (None, None)
        if kind == "vline":
            rec["x1"] = x1
        elif kind == "hline":
            rec["y1"] = y1
        elif kind == "vspan":
            rec["x1"], rec["x2"] = x1, x2
        elif kind == "hspan":
            rec["y1"], rec["y2"] = y1, y2
        else:                                   # text / arrow / rect
            rec["x1"], rec["y1"] = x1, y1
            if x2 is not None:
                rec["x2"], rec["y2"] = x2, y2
        return rec

    def _update_annot_arrows(self):
        """화살촉 각도를 **현재 축 범위 기준으로** 다시 계산한다.

        각도는 화면(씬) 좌표로 재야 한다 — x가 epoch초, y가 ppb처럼 단위 스케일이
        딴판이라 데이터 좌표로 잰 각도는 화면에서 엉뚱한 방향을 가리킨다.
        그런데 주석은 `clear_plot()` 시점, 즉 **데이터를 그리기 전·autoscale 전**에
        만들어져서 그때 매핑을 쓰면 *직전 렌더의 범위*로 계산된 각도가 박힌다
        (헤드리스 실측: 위로 향해야 할 화살표가 179.9° = 거의 수평으로 나왔다).
        그래서 생성 때는 각도를 비워두고, 범위가 확정된 뒤(autoscale 끝·줌/팬 때)
        여기서 채운다."""
        import math
        vb = self.p1.vb
        for ar, (x1, y1), (x2, y2) in getattr(self, "_annot_arrows", []):
            try:
                pt = vb.mapViewToScene(pg.Point(x1, y1))
                pf = vb.mapViewToScene(pg.Point(x2, y2))
                ar.setStyle(angle=math.degrees(math.atan2(pf.y() - pt.y(),
                                                          pf.x() - pt.x())))
            except Exception:
                pass          # 부가 표시가 본 플롯을 막지 않는다

    def _annot_line_with_label(self, at, angle, col, lbl, visible=True):
        """InfiniteLine + 라벨. 라벨 위치 계산을 pg에 맡기려고 구간 음영의 라벨도
        '펜 없는(보이지 않는) 선'에 붙인다 — 주석은 clear_plot 시점(데이터 그리기
        **전**)에 그려져서 뷰 범위를 모르기 때문에 직접 계산할 수가 없다."""
        pen = (pg.mkPen(col, width=1, style=Qt.PenStyle.DashLine) if visible
               else pg.mkPen(None))
        ln = pg.InfiniteLine(at, angle=angle, movable=False, pen=pen, label=lbl,
                             labelOpts={"position": 0.92 if angle == 90 else 0.08,
                                        "color": col, "fill": (255, 255, 255, 160)})
        ln.setZValue(150)
        self.p1.addItem(ln, ignoreBounds=True)

    def _draw_annotations_pg(self):
        """주석 레이어(선·구간·텍스트·화살표·사각형)를 p1에 그림. clear_plot마다 재추가.
        mpl 쪽(_apply_axes_mpl)에 **같은 분기**가 있다 — 한쪽만 고치면 화면과
        Publish가 갈라진다(2026-07-06에 실제로 겪은 버그류)."""
        from PyQt6.QtWidgets import QGraphicsRectItem
        from PyQt6.QtCore import QRectF
        self._annot_arrows = []      # (ArrowItem, 가리킬 점, 꼬리 점) — 각도 재계산용
        for a in [self._annot_norm(x) for x in getattr(self, "_annots", [])]:
            if not a.get("visible", True):      # 체크 해제 = 숨김(삭제 아님)
                continue
            kind = a.get("kind")
            col = a.get("color") or "#555"
            lbl = mathtext_to_html(a.get("label") or "")
            x1, y1, x2, y2 = a.get("x1"), a.get("y1"), a.get("x2"), a.get("y2")
            fill = pg.mkColor(col); fill.setAlpha(45)

            if kind == "vline" and x1 is not None:
                self._annot_line_with_label(x1, 90, col, lbl)
            elif kind == "hline" and y1 is not None:
                self._annot_line_with_label(y1, 0, col, lbl)
            elif kind == "vspan" and None not in (x1, x2):
                reg = pg.LinearRegionItem([x1, x2], orientation="vertical", movable=False,
                                          brush=pg.mkBrush(fill), pen=pg.mkPen(None))
                reg.setZValue(-90)
                self.p1.addItem(reg, ignoreBounds=True)
                if lbl:
                    self._annot_line_with_label(x1, 90, col, lbl, visible=False)
            elif kind == "hspan" and None not in (y1, y2):
                reg = pg.LinearRegionItem([y1, y2], orientation="horizontal", movable=False,
                                          brush=pg.mkBrush(fill), pen=pg.mkPen(None))
                reg.setZValue(-90)
                self.p1.addItem(reg, ignoreBounds=True)
                if lbl:
                    self._annot_line_with_label(y1, 0, col, lbl, visible=False)
            elif kind == "text" and None not in (x1, y1):
                ti = pg.TextItem(html=f'<span style="color:{col};">{lbl}</span>', anchor=(0, 1))
                ti.setPos(x1, y1); ti.setZValue(160)
                self.p1.addItem(ti, ignoreBounds=True)
            elif kind == "arrow" and None not in (x1, y1, x2, y2):
                self.p1.addItem(pg.PlotDataItem([x2, x1], [y2, y1],
                                                pen=pg.mkPen(col, width=1)), ignoreBounds=True)
                ar = pg.ArrowItem(pos=(x1, y1), headLen=12,
                                  pen=pg.mkPen(col), brush=pg.mkBrush(col))
                ar.setZValue(160)
                self.p1.addItem(ar, ignoreBounds=True)
                # 각도는 여기서 정하지 않는다 — 아래 _update_annot_arrows() 참고.
                self._annot_arrows.append((ar, (x1, y1), (x2, y2)))
                if lbl:
                    ti = pg.TextItem(html=f'<span style="color:{col};">{lbl}</span>',
                                     anchor=(0.5, 1))
                    ti.setPos(x2, y2); ti.setZValue(160)
                    self.p1.addItem(ti, ignoreBounds=True)
            elif kind == "rect" and None not in (x1, y1, x2, y2):
                r = QGraphicsRectItem(QRectF(min(x1, x2), min(y1, y2),
                                             abs(x2 - x1), abs(y2 - y1)))
                r.setPen(pg.mkPen(col, width=1)); r.setBrush(pg.mkBrush(fill))
                r.setZValue(-80)
                self.p1.addItem(r, ignoreBounds=True)
                if lbl:
                    ti = pg.TextItem(html=f'<span style="color:{col};">{lbl}</span>', anchor=(0, 1))
                    ti.setPos(min(x1, x2), max(y1, y2)); ti.setZValue(160)
                    self.p1.addItem(ti, ignoreBounds=True)

    def _parse_annot_x(self, text):
        """주석 세로선 값 파싱: 시간축이면 날짜시각→epoch, 아니면 숫자. 실패 None."""
        text = (text or "").strip()
        if self._time_axis:
            try:
                import pandas as pd
                ts = pd.to_datetime(text)
                return float(ts.timestamp())
            except Exception:
                pass
        try:
            return float(text)
        except ValueError:
            return None

    def _edit_annotations(self):
        # 모덜리스 싱글턴 — 이미 열려있으면 새로 안 만들고 앞으로 가져옴(그래프 클릭이
        # 통하려면 모덜(exec)이면 안 됨 — 모덜 창은 뒤 그래프의 마우스클릭을 막는다).
        if self._annot_dlg is not None:
            try:
                self._annot_dlg.raise_(); self._annot_dlg.activateWindow()
                return
            except RuntimeError:
                self._annot_dlg = None
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                                     QListWidgetItem, QComboBox, QLineEdit, QPushButton,
                                     QLabel, QColorDialog)
        from PyQt6.QtGui import QColor
        import datetime as _dt
        dlg = QDialog(self)
        dlg.setModal(False)
        dlg.setWindowTitle("Annotations — lines · spans · text · arrows")
        dlg.resize(520, 380)
        v = QVBoxLayout(dlg)
        lst = QListWidget()

        def _fmt(val, is_x):
            if val is None:
                return None
            if is_x and self._time_axis:
                try:
                    return _dt.datetime.fromtimestamp(val).strftime("%m-%d %H:%M")
                except Exception:
                    pass
            return f"{val:.6g}"

        def refresh():
            lst.blockSignals(True)
            lst.clear()
            for a0 in self._annots:
                a = self._annot_norm(a0)
                nm = self._ANNOT_KINDS.get(a.get("kind"), (a.get("kind"), 1, False))[0]
                bits = [f"{k}={_fmt(a.get(k), k.startswith('x'))}"
                        for k in ("x1", "y1", "x2", "y2") if a.get(k) is not None]
                it = QListWidgetItem(f"{nm}  {' '.join(bits)}   {a.get('label', '')}")
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if a.get("visible", True)
                                 else Qt.CheckState.Unchecked)
                lst.addItem(it)
            lst.blockSignals(False)

        def on_checked(item):
            """체크 해제 = 그림에서만 숨김(삭제 아님). 시리즈 목록과 같은 규칙."""
            i = lst.row(item)
            if 0 <= i < len(self._annots):
                self._annots[i] = self._annot_norm(self._annots[i])
                self._annots[i]["visible"] = item.checkState() == Qt.CheckState.Checked
                self._mode.render()
        lst.itemChanged.connect(on_checked)
        refresh()
        self._annot_dlg_refresh = refresh   # _on_plot_clicked가 클릭 추가 후 여기 갱신
        v.addWidget(QLabel("Current annotations — uncheck = hide (not delete) · select, then Remove\n"
                           "Labels support mathtext syntax"))
        v.addWidget(lst, 1)

        row = QHBoxLayout()
        _kinds = list(self._ANNOT_KINDS.keys())
        cb = QComboBox()
        for _k in _kinds:
            cb.addItem(self._ANNOT_KINDS[_k][0])
        cb.setToolTip("Text, arrows and rectangles need 2+ coordinates, so they are created only by **clicking the plot**.\n"
                      "Arrow: 1st click = point to mark, 2nd click = label position.")

        def cur_kind():
            return _kinds[max(0, cb.currentIndex())]
        ed_lab = QLineEdit(); ed_lab.setPlaceholderText("Label (optional)")
        cstate = {"c": "#d32f2f"}
        b_col = QPushButton("Col"); b_col.setFixedWidth(34)
        b_col.setStyleSheet(f"background:{cstate['c']};color:white;")

        def pick_col():
            c = QColorDialog.getColor(QColor(cstate["c"]), dlg)
            if c.isValid():
                cstate["c"] = c.name()
                b_col.setStyleSheet(f"background:{c.name()};color:white;")
        b_col.clicked.connect(pick_col)
        b_pick = QPushButton("Click on plot to place")
        b_pick.setToolTip("Press, then click the desired spot on the plot to add the annotation there.\n"
                          "Two-point kinds need two clicks. Right-click to cancel.")

        def start_pick():
            kind = cur_kind()
            nm, need, _ = self._ANNOT_KINDS[kind]
            self._annot_pick = {"kind": kind, "label": ed_lab.text().strip(),
                                "color": cstate["c"], "pts": []}
            self.set_status(f"Click the plot {need}× to add '{nm}' — right-click = cancel")
        b_pick.clicked.connect(start_pick)
        row.addWidget(cb); row.addWidget(ed_lab, 1); row.addWidget(b_col); row.addWidget(b_pick)
        v.addLayout(row)

        row1b = QHBoxLayout()
        ed_val = QLineEdit(); ed_val.setPlaceholderText("Value 1 — number; for a time x-axis use 'MM-DD HH:MM'")
        ed_val2 = QLineEdit(); ed_val2.setPlaceholderText("Value 2 (for spans)")
        b_add = QPushButton("+ Add (typed)")

        def add():
            kind = cur_kind()
            nm, need, typed_ok = self._ANNOT_KINDS[kind]
            if not typed_ok:
                self.set_status(f"'{nm}' needs both x and y, so it can only be added by clicking the plot.")
                return
            is_x = kind in ("vline", "vspan")

            def _num(t):
                try:
                    return float((t or "").strip())
                except ValueError:
                    return None
            p1 = self._parse_annot_x(ed_val.text()) if is_x else _num(ed_val.text())
            p2 = ((self._parse_annot_x(ed_val2.text()) if is_x else _num(ed_val2.text()))
                  if need == 2 else None)
            if p1 is None or (need == 2 and p2 is None):
                self.set_status("Could not parse the annotation value — enter a number (date-time for a time x-axis) or use click-to-place above.")
                return
            rec = {"kind": kind, "label": ed_lab.text().strip(), "color": cstate["c"]}
            rec["x1" if is_x else "y1"] = p1
            if need == 2:
                rec["x2" if is_x else "y2"] = p2
            self._annots.append(rec)
            ed_val.clear(); ed_val2.clear(); refresh(); self._mode.render()
        b_add.clicked.connect(add)
        row1b.addWidget(ed_val, 1); row1b.addWidget(ed_val2, 1); row1b.addWidget(b_add)
        v.addLayout(row1b)

        row2 = QHBoxLayout()
        b_rm = QPushButton("− Remove selected")

        def rm():
            i = lst.currentRow()
            if 0 <= i < len(self._annots):
                self._annots.pop(i); refresh(); self._mode.render()
        b_rm.clicked.connect(rm)
        b_close = QPushButton("Close"); b_close.clicked.connect(dlg.close)
        row2.addWidget(b_rm); row2.addStretch(1); row2.addWidget(b_close)
        v.addLayout(row2)

        def on_finished(*_):
            self._annot_dlg = None
            self._annot_dlg_refresh = None
            self._annot_pick = None
        dlg.finished.connect(on_finished)
        self._annot_dlg = dlg
        dlg.show()

    def enable_right_axis(self, on):
        self.p1.showAxis("right", show=on)
        self.vb_right.setGeometry(self.p1.vb.sceneBoundingRect())

    def set_time_axis(self, on):
        self._time_axis = on
        if getattr(self, "_time_axis_installed", None) == on:
            return   # 이미 같은 종류 축이 꽂혀있음 — 재생성 생략.
            # (매 render()마다 DateAxisItem을 새로 만들어 통째로 교체하면 pg가
            # 눈금 캐시를 못 넘겨받아, 여러 시리즈를 연달아 추가할 때 초기뷰의
            # X축이 "22, 23, 24..." 대신 "00.050, 00.100..." 같은 깨진 라벨로
            # 뜨는 버그가 있었음(축 자체는 살아있고 줌 조작하면 정상화됨 — 즉
            # 데이터 문제가 아니라 축 스왑 부작용). 2026-07-03 실제 GUI로 CH1의
            # CHOCHO+H2O+NO2 3개를 연달아 더블클릭해 추가하다 발견.)
        self._time_axis_installed = on
        ax = pg.DateAxisItem(orientation="bottom") if on else pg.AxisItem(orientation="bottom")
        ax.enableAutoSIPrefix(False)   # 새 축도 SI 스케일 금지(위 init 주석 참고)
        self.pw.setAxisItems({"bottom": ax})

    def update_views(self):
        self.vb_right.setGeometry(self.p1.vb.sceneBoundingRect())
        self.vb_right.linkedViewChanged(self.p1.vb, self.vb_right.XAxis)

    def _on_legend_changed(self, *_):
        self._mode.render()

    # ── 스타일 템플릿(룩만, 데이터 무관) ──────────────────────
    _STYLE_VERSION = 1
    _CFG_VERSION = 2

    def _migrate_style(self, st: dict) -> dict:
        """구버전(.pmstyle.json, _version 없음=v1) → 현재 버전으로 필드 보정.
        기존 필드가 전부 .get() 기반이라 실제 마이그레이션할 게 아직 없음 —
        훅만 마련해두고, 향후 breaking change는 여기 한 곳에 추가."""
        v = st.get("_version", 1)
        if v > self._STYLE_VERSION:
            self.set_status(f"This style was saved by a newer version (v{v}) — some settings may be ignored.")
            return st
        st["_version"] = self._STYLE_VERSION
        return st

    def _migrate_cfg(self, cfg: dict) -> dict:
        """구버전(.pmcfg.json, _version 없음=v1) → 현재 버전으로 필드 보정.
        v1→v2: 기존 필드가 전부 .get() 기반이라 별도 보정 불필요(Heatmap의
        mode_cfg["cols"]도 없으면 그냥 빈 dict로 취급돼 문제없음). 향후 실제
        breaking change가 생기면 여기 한 곳에 추가하면 됨."""
        v = cfg.get("_version", 1)
        if v > self._CFG_VERSION:
            self.set_status(f"This config was saved by a newer version (v{v}) — some features may be ignored.")
            return cfg
        cfg["_version"] = self._CFG_VERSION
        return cfg

    def _gather_style(self):
        """현재 '룩'만 추출. 시리즈별 색/스타일·주석은 데이터(라벨) 의존이라 제외."""
        ts = next((m for m in self._modes if m.key == "timeseries"), None)
        night = {}
        if ts is not None:
            on = ts._chk_night.isChecked() if hasattr(ts, "_chk_night") else ts._night_on
            night = {"on": on, "start": list(ts._night_start),
                     "end": list(ts._night_end), "color": ts._night_color}
        return {
            "_version": self._STYLE_VERSION,
            "font_size": self._lbl_size.value(),
            "tick_size": self._tick_size.value(),
            "legend": self._legend_combo.currentText(),
            "legend_size": self._legend_size.value(),
            "resample": self._res_combo.currentText(),
            "resample_custom_min": self._res_custom_spin.value(),
            "smooth": self._smooth_spin.value(),
            "time_shift_h": self._shift_spin.value(),
            "mode_colors": {m.key: dict(m.colors) for m in self._modes if m.colors},
            "night": night,
            "label_style": self.label_style,
        }

    def _apply_style(self, st):
        if "font_size" in st:
            self._lbl_size.setValue(int(st["font_size"]))
        if "tick_size" in st:
            self._tick_size.setValue(int(st["tick_size"]))
        if st.get("legend") in ("auto", "TL", "TR", "BL", "BR", "off"):
            self._legend_combo.setCurrentText(st["legend"])
        if "legend_size" in st:
            self._legend_size.setValue(int(st["legend_size"]))
        if "resample_custom_min" in st:
            self._res_custom_spin.setValue(float(st["resample_custom_min"]))
        if st.get("resample"):
            i = self._res_combo.findText(st["resample"])
            if i >= 0:
                self._res_combo.setCurrentIndex(i)
        if "smooth" in st:
            self._smooth_spin.setValue(int(st["smooth"]))
        if "time_shift_h" in st:
            self._shift_spin.setValue(float(st["time_shift_h"]))
        if "label_style" in st:
            for k, v in st["label_style"].items():
                pos = v.get("pos")
                self.label_style[k] = {"pos": tuple(pos) if pos else None,
                                       "size": v.get("size"), "color": v.get("color")}
            self._sync_label_style_widgets()
        for m in self._modes:
            mc = (st.get("mode_colors") or {}).get(m.key)
            if mc:
                m.colors = dict(mc)
        nd = st.get("night") or {}
        ts = next((m for m in self._modes if m.key == "timeseries"), None)
        if ts is not None and nd:
            ts._night_start = tuple(nd.get("start", ts._night_start))
            ts._night_end = tuple(nd.get("end", ts._night_end))
            ts._night_color = nd.get("color", ts._night_color)
            if hasattr(ts, "_chk_night"):
                from PyQt6.QtCore import QTime
                ts._te_ns.setTime(QTime(*ts._night_start))
                ts._te_ne.setTime(QTime(*ts._night_end))
                ts._chk_night.setChecked(bool(nd.get("on", False)))
        self._mode.render()

    def _save_template(self):
        out, _ = QFileDialog.getSaveFileName(
            self, "Save style template",
            self._default_export_name() + ".pmstyle.json", "Style (*.json)")
        if not out:
            return
        if not out.lower().endswith(".json"):
            out += ".json"
        import json
        try:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(self._gather_style(), f, ensure_ascii=False, indent=2)
            self.set_status(f"Style saved: {os.path.basename(out)}")
        except Exception as e:
            QMessageBox.warning(self, "Style", f"Save failed:\n{e}")

    def _load_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load style template", "",
                                              "Style (*.json);;All (*)")
        if not path:
            return
        import json
        try:
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Style", f"Load failed:\n{e}")
            return
        st = self._migrate_style(st)
        self._apply_style(st)
        self.set_status(f"Style applied: {os.path.basename(path)}")

    def _toggle_cursor(self, on):
        from PyQt6.QtWidgets import QToolTip
        self._cursor_on = on
        self._cur_v.setVisible(on); self._cur_h.setVisible(on)
        if not on:
            self.set_status("")
            QToolTip.hideText()

    def _hover_tooltip_text(self, mp):
        """호버 말풍선(및 상태바) 텍스트 — x/y + (Time series 모드면) 그 지점의
        각 시리즈 값도 함께. 시리즈가 여러 개일 때 특히 유용(Origin류 data tip)."""
        if self._time_axis:
            import datetime as _dt
            try:
                xs = _dt.datetime.fromtimestamp(mp.x()).strftime("%m/%d %H:%M:%S")
            except (OSError, ValueError, OverflowError):
                xs = f"{mp.x():.6g}"
        else:
            xs = f"{mp.x():.6g}"
        lines = [f"x = {xs}", f"y = {mp.y():.6g}"]
        if getattr(self._mode, "key", None) == "timeseries":
            try:
                for s in self._mode._resolve_specs():
                    if s.x is None or len(s.x) == 0:
                        continue
                    i = int(np.searchsorted(s.x, mp.x()))
                    i = max(0, min(i, len(s.x) - 1))
                    lines.append(f"{s.display_name}: {s.y[i]:.4g}")
            except Exception:
                pass
        return "\n".join(lines)

    def _on_cursor_move(self, pos):
        from PyQt6.QtWidgets import QToolTip
        if not self._cursor_on or not self.p1.sceneBoundingRect().contains(pos):
            QToolTip.hideText()
            return
        mp = self.p1.vb.mapSceneToView(pos)
        self._cur_v.setPos(mp.x()); self._cur_h.setPos(mp.y())
        text = self._hover_tooltip_text(mp)
        self.set_status("" + text.replace("\n", "    "))
        gp = self.pw.viewport().mapToGlobal(self.pw.mapFromScene(pos))
        QToolTip.showText(gp, text, self.pw)

    def _on_plot_clicked(self, ev):
        """🖱 Pick 모드일 때만 반응 — 클릭 위치를 그대로 마커 값으로 채택.
        우클릭=취소. 값 입력칸 대신 그래프에서 직접 찍는 방식(_edit_annotations 참고)."""
        if self._annot_pick is None:
            return
        if ev.button() == Qt.MouseButton.RightButton:
            self._annot_pick = None
            self.set_status("Marker placement cancelled")
            return
        if not self.p1.sceneBoundingRect().contains(ev.scenePos()):
            return
        mp = self.p1.vb.mapSceneToView(ev.scenePos())
        kind = self._annot_pick["kind"]
        nm, need, _ = self._ANNOT_KINDS.get(kind, ("Annotation", 1, True))
        pts = self._annot_pick.setdefault("pts", [])
        pts.append((float(mp.x()), float(mp.y())))
        if len(pts) < need:      # 2점짜리는 한 번 더 받는다
            self.set_status(f"'{nm}' — click {need - len(pts)} more point(s) (right-click = cancel)")
            return
        self._annots.append(self._annot_from_points(
            kind, pts, self._annot_pick.get("label", ""),
            self._annot_pick.get("color", "#d32f2f")))
        self._annot_pick = None
        self._mode.render()
        self.set_status(f"Annotation added: {nm}")
        refresh = getattr(self, "_annot_dlg_refresh", None)
        if refresh:
            try:
                refresh()
            except Exception:
                pass

    def autoscale(self):
        """데이터에 맞춰 양축 범위 재설정. 빈 우측 ViewBox가 X를 [0,1]에 묶어
        시간축이 깨지던 문제(autorange 미작동)를 매 render 끝에 강제 해소한다.
        이후 사용자 축 설정(범위/로그)을 덮어쓴다."""
        vb = self.p1.getViewBox()
        self.vb_right.enableAutoRange(y=True)
        vb.enableAutoRange(x=True, y=True)
        vb.autoRange()
        self.update_views()
        self.apply_axes()
        self._update_annot_arrows()   # 범위가 정해진 뒤에야 화살촉 각도가 맞는다

    # ── 라벨(제목/축) 그리기 — pg(화면)·mpl(Publish) 공용 진입점 ─────────────
    # 모드들은 p1.setLabel/setTitle·ax.set_ylabel 등을 직접 부르지 않고 이 두
    # 메서드만 호출한다 — label_style(pos/size/color)가 화면·Publish에서
    # 절대 어긋나지 않게(ResolvedSeries와 같은 설계 원칙).
    _AXIS_OF_KEY = {"xlabel": "bottom", "ylabel": "left", "rlabel": "right"}

    def _default_label_pos(self, key):
        """자유배치를 처음 켤 때 시작 위치 — ViewBox 사각형 기준 비율(fx,fy),
        matplotlib의 ax.transAxes와 같은 개념(0-1 밖=축 여백 쪽). 전형적인
        축라벨 오프셋과 비슷한 값으로 시작해서 드래그로 다듬게 한다."""
        return {"title": (0.5, 1.05), "xlabel": (0.5, -0.09),
               "ylabel": (-0.09, 0.5), "rlabel": (1.09, 0.5)}.get(key, (0.5, 0.5))

    def _label_scene_pos(self, key, fx, fy):
        """(fx,fy) 비율 → 현재 창 크기 기준 실제 씬(픽셀) 좌표."""
        vb = self.vb_right if key == "rlabel" else self.p1.getViewBox()
        rect = vb.sceneBoundingRect()
        return (rect.left() + fx * rect.width(), rect.bottom() - fy * rect.height())

    def pg_label(self, key, text):
        """key: 'title'/'xlabel'/'ylabel'/'rlabel'. label_style[key]['pos']가
        없으면 pg 기본 축라벨/제목으로, 있으면 드래그 가능한 자유배치 텍스트로
        — ViewBox가 아니라 씬에 직접 붙여서 축 여백 쪽에도 놓일 수 있게 한다
        (ViewBox 자식은 view range 밖이면 아예 안 그려지는 걸 확인했음)."""
        st = self.label_style.setdefault(key, {"pos": None, "size": None, "color": None})
        old = self._custom_label_items.pop(key, None)
        if old is not None:
            try:
                self.p1.scene().removeItem(old)
            except Exception:
                pass
        size = st.get("size") or (self._lbl_size.value() or 10)
        color = st.get("color")
        # 입력은 mathtext 문법(예 NO$_2$) — pg는 HTML만 알아들으므로 여기서 변환.
        # mpl 쪽(mpl_label)은 원문 그대로 넘긴다. 이게 M5의 전부다.
        html = mathtext_to_html(text)
        if st.get("pos") is None:
            if key == "title":
                self.p1.setTitle(html, size=f"{size}pt", **({"color": color} if color else {}))
            else:
                ax = self.p1.getAxis(self._AXIS_OF_KEY[key])
                style = {"font-size": f"{size}pt"}
                if color:
                    style["color"] = color
                ax.setLabel(html, **style)
            return
        # 자유배치: 원래 자리는 비우고 드래그 가능한 텍스트로 대체
        if key == "title":
            self.p1.setTitle(None)   # None=완전히 숨김(""는 빈 줄 30px가 남음)
        else:
            self.p1.getAxis(self._AXIS_OF_KEY[key]).setLabel("")
        if not text:
            return
        # ylabel/rlabel은 원래 pg 축라벨처럼 세로로 회전(안 그러면 가로 텍스트가
        # 데이터 한복판에 그냥 떠 있는 것처럼 보임 — 실사용에서 발견된 버그).
        angle = 90 if key in ("ylabel", "rlabel") else 0
        item = _DraggableLabel(self, key, text=text, color=color or "#000000",
                               anchor=(0.5, 0.5), angle=angle)
        from PyQt6.QtGui import QFont
        font = QFont(); font.setPointSize(int(size)); item.setFont(font)
        if has_markup(text):   # TextItem(text=)는 평문 경로 — 마크업이 있을 때만 HTML로
            item.setHtml('<span style="color:%s; font-size:%dpt;">%s</span>'
                         % (color or "#000000", int(size), html))
        fx, fy = st["pos"]
        sx, sy = self._label_scene_pos(key, fx, fy)
        item.setPos(sx, sy)
        self.p1.scene().addItem(item)   # ViewBox 대신 씬에 직접 → 여백 쪽도 표시됨
        self._custom_label_items[key] = item

    def mpl_label(self, ax, key, text):
        """key: 'title'/'xlabel'/'ylabel'/'rlabel'. ax는 해당 라벨이 붙을 Axes
        (rlabel이면 twinx된 오른쪽 축). pg_label과 동일한 label_style 참조."""
        st = self.label_style.get(key, {"pos": None, "size": None, "color": None})
        size = st.get("size") or (self._lbl_size.value() or None)
        color = st.get("color")
        setter = {"title": ax.set_title, "xlabel": ax.set_xlabel,
                 "ylabel": ax.set_ylabel, "rlabel": ax.set_ylabel}[key]
        if st.get("pos") is None:
            setter(text, fontsize=size, **({"color": color} if color else {}))
            return
        setter("")
        if not text:
            return
        # pg와 동일하게 축(ax) 사각형 기준 비율(fx,fy) — transAxes는 정확히 이 개념이라
        # 데이터 범위/줌과 무관하게 pg 미리보기와 항상 같은 상대 위치가 된다.
        rot = 90 if key in ("ylabel", "rlabel") else 0
        fx, fy = st["pos"]
        ax.text(fx, fy, text, transform=ax.transAxes, fontsize=size or 10,
               color=color or "black", rotation=rot, ha="center", va="center", clip_on=False)

    def toggle_label_free_pos(self, key, on):
        """라벨 자유배치 on/off. on이면 기본 시작위치(_default_label_pos)를 잡아
        드래그 가능하게, off면 pos를 지워 원래 축 자리로 되돌림."""
        st = self.label_style.setdefault(key, {"pos": None, "size": None, "color": None})
        st["pos"] = self._default_label_pos(key) if on else None
        self._mode.render()

    def reset_label_positions(self):
        self.label_style = {k: {"pos": None, "size": v.get("size"), "color": v.get("color")}
                            for k, v in self.label_style.items()}
        for w in getattr(self, "_label_style_widgets", {}).values():
            chk = w.get("free_chk")
            if chk is not None:
                chk.blockSignals(True); chk.setChecked(False); chk.blockSignals(False)
        self._mode.render()
        self.set_status("All label positions reset to default")

    def _edit_colors(self):
        """현재 모드의 color_keys() 요소들 색을 지정하는 다이얼로그(라이브 적용)."""
        keys = self._mode.color_keys()
        if not keys:
            self.set_status("This mode has no color-assignable elements "
                            "(for Time series, use Color in the options panel).")
            return
        from PyQt6.QtWidgets import (QDialog, QFormLayout, QDialogButtonBox,
                                     QColorDialog)
        from PyQt6.QtGui import QColor
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Colors — {self._mode.label}")
        form = QFormLayout(dlg)

        def _swatch(btn, c):
            btn.setText(c)
            btn.setStyleSheet(f"background:{c}; color:white; padding:3px; font-weight:bold;")

        for key, label, default in keys:
            b = QPushButton()
            _swatch(b, self._mode.colors.get(key) or default)

            def mk(k, button, dflt):
                def pick():
                    init = QColor(self._mode.colors.get(k) or dflt)
                    c = QColorDialog.getColor(init, dlg, "Pick color")
                    if c.isValid():
                        self._mode.colors[k] = c.name()
                        _swatch(button, c.name())
                        self._mode.render()
                return pick
            b.clicked.connect(mk(key, b, default))
            form.addRow(label, b)

        bb = QDialogButtonBox()
        b_reset = bb.addButton("Reset defaults", QDialogButtonBox.ButtonRole.ResetRole)
        bb.addButton(QDialogButtonBox.StandardButton.Close)

        def _reset():
            self._mode.colors.clear()
            self._mode.render()
            dlg.accept()
        b_reset.clicked.connect(_reset)
        bb.rejected.connect(dlg.accept)
        bb.accepted.connect(dlg.accept)
        form.addRow(bb)
        dlg.exec()

    @staticmethod
    def _axis_val(edit):
        try:
            return float(edit.text().strip())
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _mark_invalid(edit, invalid):
        """입력값이 비어있지 않은데 파싱 실패면 빨간 테두리로 표시(조용히 무시 X).
        빈칸/파싱성공이면 원상복구. apply_axes()가 매 변경마다 호출하므로 그때그때 갱신."""
        edit.setStyleSheet(f"border: 1px solid {AUGUR.fail};" if invalid else "")

    def _x_ref_year(self):
        """날짜 입력에 연도를 안 적었을 때 쓸 기준연도 = 현재 데이터의 연도."""
        import datetime as _dt
        for lab in self.column_choices():
            r = self.resolve(lab)
            if r is not None and r[3] is not None and len(r[3]):
                try:
                    return _dt.datetime.fromtimestamp(float(np.nanmin(r[3]))).year
                except Exception:
                    pass
        return _dt.date.today().year

    def _parse_x(self, text):
        """X 범위 입력 → 값. 시간축이면 날짜문자열을 epoch초로(연도 생략 시 데이터
        연도 사용), 아니면 float. 빈칸/파싱불가 = None(자동)."""
        s = (text or "").strip()
        if not s:
            return None
        if not self._time_axis:
            try:
                return float(s)
            except ValueError:
                return None
        import datetime as _dt
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d",
                    "%m-%d %H:%M", "%m-%d", "%m/%d %H:%M", "%m/%d"):
            try:
                d = _dt.datetime.strptime(s, fmt)
            except ValueError:
                continue
            if d.year == 1900:        # 연도 생략 → 데이터 연도
                d = d.replace(year=self._x_ref_year())
            return d.timestamp()
        return None

    def _data_time_range(self):
        """현재 선반(전체 데이터셋)의 시간범위 (lo, hi) epoch초. 시간축 데이터
        없으면 (None, None). 날짜 프리셋 버튼들의 기준값."""
        lo = hi = None
        for ds in self.shelf.values():
            if ds.time is None or len(ds.time) == 0:
                continue
            finite = ds.time[np.isfinite(ds.time)]
            if finite.size == 0:
                continue
            a, b = float(finite.min()), float(finite.max())
            lo = a if lo is None else min(lo, a)
            hi = b if hi is None else max(hi, b)
        return lo, hi

    def _set_x_range_text(self, d0, d1):
        self._ax_xmin.setText(d0.strftime("%Y-%m-%d %H:%M"))
        self._ax_xmax.setText(d1.strftime("%Y-%m-%d %H:%M"))
        self._on_axes_changed()

    def _preset_x_time_guard(self):
        """날짜 프리셋은 시간축 모드에서만 의미가 있다 — Scatter처럼 X가 시간이
        아닌 모드에서 누르면 날짜문자열이 파싱 실패로 빨간 테두리가 되면서도
        상태바는 '성공'이라 뜨는 모순이 있었다(2026-06-30 자체 감사에서 발견).
        여기서 미리 막고 이유를 알려준다."""
        if not self._time_axis:
            self.set_status(f"'{self._mode.label}' mode has no time X axis — date presets don't apply.")
            return False
        return True

    def _preset_x_full(self):
        """전체 데이터 범위를 하루 경계(00:00)에 맞춰 X에 채움 — 박사님 그림
        규약(x 양끝 tight, 매일 00:00 눈금)과 동일한 결과를 매주 손타이핑 없이."""
        if not self._preset_x_time_guard():
            return
        lo, hi = self._data_time_range()
        if lo is None:
            self.set_status("No data with a time axis — add data first.")
            return
        import datetime as _dt
        d0 = _dt.datetime.fromtimestamp(lo).replace(hour=0, minute=0, second=0, microsecond=0)
        d1 = (_dt.datetime.fromtimestamp(hi).replace(hour=0, minute=0, second=0, microsecond=0)
              + _dt.timedelta(days=1))
        self._set_x_range_text(d0, d1)
        self.set_status(f"X range: {d0:%Y-%m-%d} – {d1:%Y-%m-%d} (all, whole days)")

    def _preset_x_recent(self, days):
        """데이터 마지막 날 기준 최근 N일(00:00 경계)을 X에 채움."""
        if not self._preset_x_time_guard():
            return
        lo, hi = self._data_time_range()
        if hi is None:
            self.set_status("No data with a time axis — add data first.")
            return
        import datetime as _dt
        d1 = (_dt.datetime.fromtimestamp(hi).replace(hour=0, minute=0, second=0, microsecond=0)
              + _dt.timedelta(days=1))
        d0 = d1 - _dt.timedelta(days=days)
        self._set_x_range_text(d0, d1)
        self.set_status(f"X range: last {days} d ({d0:%Y-%m-%d} – {d1:%Y-%m-%d})")

    def _preset_x_clear(self):
        self._ax_xmin.setText(""); self._ax_xmax.setText("")
        self._on_axes_changed()
        self.set_status("X range cleared (auto)")

    def apply_axes(self):
        """사용자 지정 축 범위/로그를 현재 플롯에 적용(빈칸/미체크는 자동 유지).
        로그는 모드 기본값(예: Allan)을 끄지 않고 OR로 얹는다."""
        import math
        if not hasattr(self, "_chk_logx"):
            return
        ax_b = self.p1.getAxis("bottom"); ax_l = self.p1.getAxis("left")
        fx = bool(getattr(ax_b, "logMode", False)) or self._chk_logx.isChecked()
        fy = bool(getattr(ax_l, "logMode", False)) or self._chk_logy.isChecked()
        self.p1.setLogMode(x=fx, y=fy)
        vb = self.p1.getViewBox()

        def conv(v, islog):
            if v is None:
                return None
            if islog:
                return math.log10(v) if v > 0 else None
            return v
        xmin = self._parse_x(self._ax_xmin.text()); xmax = self._parse_x(self._ax_xmax.text())
        self._mark_invalid(self._ax_xmin, bool(self._ax_xmin.text().strip()) and xmin is None)
        self._mark_invalid(self._ax_xmax, bool(self._ax_xmax.text().strip()) and xmax is None)
        if xmin is not None and xmax is not None and xmin < xmax:
            # 시간축(DateAxisItem)은 padding=0이면 양 끝 눈금 라벨이 축 경계를 벗어나
            # 아예 그려지지 않는 pyqtgraph 특성이 있음 → 화면표시만 살짝 여백(2%)을 둬서
            # 29일/5일 같은 경계 날짜가 잘리지 않고 보이게 함(Publish/저장 좌표는 그대로 tight).
            pad = 0.02 if self._time_axis and not fx else 0
            vb.setXRange(conv(xmin, fx), conv(xmax, fx), padding=pad)
        ymin_raw = self._axis_val(self._ax_ymin); ymax_raw = self._axis_val(self._ax_ymax)
        self._mark_invalid(self._ax_ymin, bool(self._ax_ymin.text().strip()) and ymin_raw is None)
        self._mark_invalid(self._ax_ymax, bool(self._ax_ymax.text().strip()) and ymax_raw is None)
        ymin = conv(ymin_raw, fy); ymax = conv(ymax_raw, fy)
        if ymin is not None and ymax is not None and ymin < ymax:
            vb.setYRange(ymin, ymax, padding=0)
        rmin = self._axis_val(self._ax_rmin); rmax = self._axis_val(self._ax_rmax)
        self._mark_invalid(self._ax_rmin, bool(self._ax_rmin.text().strip()) and rmin is None)
        self._mark_invalid(self._ax_rmax, bool(self._ax_rmax.text().strip()) and rmax is None)
        if rmin is not None and rmax is not None and rmin < rmax:
            self.vb_right.setYRange(rmin, rmax, padding=0)
        # 그리드 on/off (화면)
        if hasattr(self, "_chk_grid"):
            g = self._chk_grid.isChecked()
            self.p1.showGrid(x=g, y=g, alpha=0.3)
        # 눈금 간격(화면, best-effort — 정확한 값은 Publish에서 확인. 시간축 X는
        # '일'→초 환산. 로그축이면 건너뜀). 실패해도 무음으로 삼키지 않고 상태바에 표시
        # — pg AxisItem이 항상 지원하는 게 아니라 화면-Publish 불일치를 정직하게 알림.
        ty = self._axis_val(self._tick_y)
        self._mark_invalid(self._tick_y, bool(self._tick_y.text().strip()) and not (ty and ty > 0))
        if ty and ty > 0 and not fy:
            try:
                self.p1.getAxis("left").setTickSpacing(major=ty, minor=ty / 5.0)
            except Exception as e:
                self.set_status(f"Y tick spacing failed (screen only; Publish unaffected): {e}")
        tx = self._axis_val(self._tick_x)
        self._mark_invalid(self._tick_x, bool(self._tick_x.text().strip()) and not (tx and tx > 0))
        if tx and tx > 0 and not fx:
            anchored = self._anchored_x_ticks(tx)
            try:
                if anchored is not None:
                    # 앵커 날짜 기준 고정 눈금 — pg setTickSpacing은 epoch 0 기준
                    # 위상이라 임의 날짜 앵커가 안 됨 → 명시적 setTicks로 통일.
                    self.p1.getAxis("bottom").setTicks([anchored])
                else:
                    step = tx * 86400.0 if self._time_axis else tx
                    self.p1.getAxis("bottom").setTickSpacing(major=step, minor=step / 2.0)
            except Exception as e:
                self.set_status(f"X tick spacing failed (screen only; Publish unaffected): {e}")
        # 눈금 글자 크기 (화면) — Publish(_apply_axes_mpl)와 같은 규칙(_tick_pt)
        ts_pt = self._tick_pt()
        try:
            from PyQt6.QtGui import QFont
            tf = None
            if ts_pt > 0:
                tf = QFont(); tf.setPointSize(ts_pt)
            for nm in ("bottom", "left", "right"):
                self.p1.getAxis(nm).setStyle(tickFont=tf)   # None=pg 기본
        except Exception: pass
        # 축 라벨·눈금 표시/숨김 (화면) — 숫자(텍스트)와 눈금선(마크)은 독립 토글
        if hasattr(self, "_chk_xlabel"):
            bax = self.p1.getAxis("bottom"); lax = self.p1.getAxis("left")
            try:
                sx_pg = self._chk_xticks.isChecked(); sy_pg = self._chk_yticks.isChecked()
                mx_pg = self._chk_xtickmarks.isChecked(); my_pg = self._chk_ytickmarks.isChecked()
                tick_px = self._tick_geom_px()   # 부호 = 방향(pg: 양수=바깥, 음수=안)
                bax.setStyle(showValues=sx_pg, tickLength=tick_px if mx_pg else 0)
                lax.setStyle(showValues=sy_pg, tickLength=tick_px if my_pg else 0)
                bax.showLabel(self._chk_xlabel.isChecked())
                lax.showLabel(self._chk_ylabel.isChecked())
            except Exception: pass

    def _tick_geom_px(self):
        """눈금선 부호있는 길이(px) — pg·mpl 공용 단일 규칙.
        길이 = Tick 선 길이(0=auto→5), 부호 = 방향(바깥 out=+ / 안 in=−).
        pg AxisItem은 bottom/left 기준 양수가 텍스트쪽(바깥), 음수가 플롯 안쪽."""
        n = self._tick_len.value() if hasattr(self, "_tick_len") else 0
        length = n if n > 0 else 5
        is_in = hasattr(self, "_tick_dir") and self._tick_dir.currentIndex() == 1
        return -length if is_in else length

    def _anchored_x_ticks(self, tx_days):
        """앵커 날짜 + N일 간격의 X 눈금 목록 [(epoch, 라벨), ...] — 시간축이고
        앵커 입력이 있을 때만(아니면 None=기존 자동/등간격 로직). 앵커는 위상
        기준이라 화면 범위 앞뒤로도 같은 간격으로 이어진다. pg·mpl 공용."""
        if not self._time_axis:
            return None
        txt = (getattr(self, "_tick_x_anchor", None) and self._tick_x_anchor.text().strip()) or ""
        if not txt:
            if hasattr(self, "_tick_x_anchor"):
                self._mark_invalid(self._tick_x_anchor, False)   # 지웠으면 오류표시도 해제
            return None
        anchor = self._parse_x(txt)
        self._mark_invalid(self._tick_x_anchor, anchor is None)
        if anchor is None:
            return None
        (x0, x1), _ = self.p1.getViewBox().viewRange()
        step = tx_days * 86400.0
        import math, datetime as _dt
        k0 = math.floor((x0 - anchor) / step)
        k1 = math.ceil((x1 - anchor) / step)
        fmt = "%m-%d" if tx_days >= 1 else "%m-%d %H:%M"
        out = []
        for k in range(int(k0), int(k1) + 1):
            p = anchor + k * step
            try:
                out.append((p, _dt.datetime.fromtimestamp(p).strftime(fmt)))
            except (OSError, OverflowError, ValueError):
                continue
        return out or None

    def _tick_pt(self):
        """눈금 글자 크기(pt) — pg·mpl 공용 단일 규칙.
        Tick size 지정 시 그 값, 0(auto)이면 전역 Font size−2(최소 6), 둘 다 auto면 0(=기본)."""
        t = self._tick_size.value() if hasattr(self, "_tick_size") else 0
        if t > 0:
            return t
        sz = self._lbl_size.value() if hasattr(self, "_lbl_size") else 0
        return max(sz - 2, 6) if sz > 0 else 0

    def _apply_axes_mpl(self, fig, axes=None):
        """Publish(matplotlib)에도 동일한 축 범위/로그 적용.
        axes=None → 그림의 모든 축(예전 그대로). 조판(M2)은 패널 하나의 축들만 넘긴다."""
        axes = list(axes) if axes is not None else fig.axes
        if not axes:
            return
        ax = axes[0]
        if self._chk_logx.isChecked():
            try: ax.set_xscale("log")
            except Exception: pass
        if self._chk_logy.isChecked():
            try: ax.set_yscale("log")
            except Exception: pass
        xmin = self._parse_x(self._ax_xmin.text()); xmax = self._parse_x(self._ax_xmax.text())
        if xmin is not None and xmax is not None and xmin < xmax:
            import datetime as _dt2
            lo, hi = ((_dt2.datetime.fromtimestamp(xmin), _dt2.datetime.fromtimestamp(xmax))
                      if self._time_axis else (xmin, xmax))
            for a in axes:        # 분할 모드면 x축 공유 → 전체 패널에
                a.set_xlim(lo, hi)
        ymin = self._axis_val(self._ax_ymin); ymax = self._axis_val(self._ax_ymax)
        if ymin is not None and ymax is not None and ymin < ymax:
            ax.set_ylim(ymin, ymax)
        rmin = self._axis_val(self._ax_rmin); rmax = self._axis_val(self._ax_rmax)
        if rmin is not None and rmax is not None and rmin < rmax:
            for a in axes[1:]:        # twinx 우측 축
                a.set_ylim(rmin, rmax)
        # 그리드 on/off (+ minor) — render_mpl 기본 grid를 여기서 덮어씀
        if hasattr(self, "_chk_grid"):
            g = self._chk_grid.isChecked()
            gm = self._chk_grid_minor.isChecked()
            for a in axes:
                if g:
                    a.grid(True, which="major", alpha=0.3)
                else:
                    a.grid(False, which="major")
                if gm:
                    a.minorticks_on(); a.grid(True, which="minor", alpha=0.15)
        # 눈금 간격 지정(빈칸=자동). X는 시간축이면 '일' 간격(박사님 약속 눈금).
        import matplotlib.ticker as _mtick
        ty = self._axis_val(self._tick_y)
        if ty and ty > 0:
            for a in axes:
                a.yaxis.set_major_locator(_mtick.MultipleLocator(ty))
        tx = self._axis_val(self._tick_x)
        if tx and tx > 0:
            if self._time_axis:
                import matplotlib.dates as _mdates
                anchored = self._anchored_x_ticks(tx)
                if anchored is not None:
                    # 앵커 날짜 기준 고정 눈금 — pg(apply_axes)와 같은 위치 목록 사용
                    import datetime as _dt2
                    locs = [_mdates.date2num(_dt2.datetime.fromtimestamp(p))
                            for p, _lbl in anchored]
                    axes[-1].xaxis.set_major_locator(_mtick.FixedLocator(locs))
                else:
                    axes[-1].xaxis.set_major_locator(_mdates.DayLocator(interval=max(1, int(tx))))
            else:
                for a in axes:
                    a.xaxis.set_major_locator(_mtick.MultipleLocator(tx))
        # 라벨·제목 글자 크기(0=auto면 기본 유지) — 출판 figure에 적용
        sz = self._lbl_size.value() if hasattr(self, "_lbl_size") else 0
        if sz > 0:
            for a in axes:
                a.xaxis.label.set_fontsize(sz)
                a.yaxis.label.set_fontsize(sz)
                a.title.set_fontsize(sz + 1)
        ts_pt = self._tick_pt()   # 눈금 글자 크기 — 화면(apply_axes)과 같은 규칙
        if ts_pt > 0:
            for a in axes:
                a.tick_params(labelsize=ts_pt)
        # 축 라벨·눈금 표시/숨김 (Publish). 끄면 아예 안 그림.
        if hasattr(self, "_chk_xlabel"):
            hide_xl = not self._chk_xlabel.isChecked()
            hide_yl = not self._chk_ylabel.isChecked()
            sx = self._chk_xticks.isChecked(); sy = self._chk_yticks.isChecked()
            mx = self._chk_xtickmarks.isChecked(); my = self._chk_ytickmarks.isChecked()
            tick_px = self._tick_geom_px()   # 부호=방향, 절대값=길이 — 화면(pg)과 동일 규칙
            tdir = "in" if tick_px < 0 else "out"
            for a in axes:
                if hide_xl:
                    a.set_xlabel("")
                if hide_yl:
                    a.set_ylabel("")
                if a.yaxis.get_label_position() == "right":
                    # 오른쪽 축(twinx): 오른쪽 눈금만. 전엔 left/labelleft를 같이 켜서 R축 눈금
                    # 숫자가 **왼쪽 축 숫자 옆에 겹쳐** 찍혔다(2026-10-01 조판 렌더로 발견 —
                    # 단일 그림 Publish에도 있던 버그). x는 주 축 것이라 건드리지 않는다.
                    a.tick_params(axis="y", which="both", right=my, labelright=sy,
                                  direction=tdir, length=abs(tick_px))
                    continue
                a.tick_params(axis="x", which="both", bottom=mx, labelbottom=sx,
                              direction=tdir, length=abs(tick_px))
                a.tick_params(axis="y", which="both", left=my, labelleft=sy,
                              direction=tdir, length=abs(tick_px))
        # 주석 마커선(세로=이벤트, 가로=LOD/임계) — 모든 패널에(분할 시 x축 공유).
        # 화면(pg InfiniteLine)은 라벨을 선 옆에 직접 띄우고 범례엔 안 넣는다 — Publish도
        # 동일하게 axvline(label=)이 아니라 text()로 선 옆에 그려서 legend on/off와
        # 무관하게 항상 보이게 한다(이전엔 label=만 줘서 범례가 꺼져 있으면 안 보였음).
        import datetime as _dt
        if getattr(self, "_annots", []):
            # pg는 ignoreBounds=True로 넣어 마커선이 화면 범위를 못 늘리는데, mpl의
            # axvline/axhline은 자동범위(datalim)에 포함된다 → 다른 좌표계 모드
            # (Diurnal 0-23h 등)에서 epoch 초 세로선이 x축을 17억까지 늘려 데이터가
            # 압착되는 실버그(2026-07-07). 자동범위를 먼저 확정·고정해두고 주석을
            # 그린 뒤 되돌려서 pg와 같은 의미론(선은 범위에 무영향)으로 맞춘다.
            for a in axes:
                a.autoscale_view()          # 사용자가 xlim/ylim 지정했으면 그대로 유지됨
            saved_lims = [(a, a.get_xlim(), a.get_ylim()) for a in axes]
        from matplotlib.patches import Rectangle as _Rect
        _bbox = dict(facecolor="white", edgecolor="none", alpha=0.7, pad=1)

        def _xconv(v):
            """x 데이터값 → mpl 축 값(시간축이면 datetime)."""
            return _dt.datetime.fromtimestamp(v) if self._time_axis else v

        for an in [self._annot_norm(x) for x in getattr(self, "_annots", [])]:
            if not an.get("visible", True):     # 화면과 같은 규칙으로 숨긴다
                continue
            kind = an.get("kind")
            col = an.get("color") or "#555"
            lbl = an.get("label") or None
            x1, y1, x2, y2 = an.get("x1"), an.get("y1"), an.get("x2"), an.get("y2")
            for ai, a in enumerate(axes):
                show_label = (ai == 0) and lbl   # 라벨은 첫 패널에만(중복 방지)
                # 라벨은 axvline(label=)이 아니라 text()로 — 범례를 꺼도 보여야 한다
                # (2026-07-06 실버그: label=만 줘서 범례 off면 증발).
                if kind == "vline" and x1 is not None:
                    a.axvline(_xconv(x1), color=col, ls="--", lw=1)
                    if show_label:
                        a.text(_xconv(x1), a.get_ylim()[1], f" {lbl}", color=col, fontsize=8,
                               va="top", ha="left", clip_on=True, bbox=_bbox)
                elif kind == "hline" and y1 is not None:
                    a.axhline(y1, color=col, ls="--", lw=1)
                    if show_label:
                        a.text(a.get_xlim()[0], y1, f"{lbl} ", color=col, fontsize=8,
                               va="bottom", ha="left", clip_on=True, bbox=_bbox)
                elif kind == "vspan" and None not in (x1, x2):
                    a.axvspan(_xconv(x1), _xconv(x2), color=col, alpha=0.18, lw=0, zorder=0)
                    if show_label:
                        a.text(_xconv(x1), a.get_ylim()[1], f" {lbl}", color=col, fontsize=8,
                               va="top", ha="left", clip_on=True, bbox=_bbox)
                elif kind == "hspan" and None not in (y1, y2):
                    a.axhspan(y1, y2, color=col, alpha=0.18, lw=0, zorder=0)
                    if show_label:
                        a.text(a.get_xlim()[0], y1, f"{lbl} ", color=col, fontsize=8,
                               va="bottom", ha="left", clip_on=True, bbox=_bbox)
                elif kind == "text" and None not in (x1, y1):
                    if lbl and ai == 0:
                        a.text(_xconv(x1), y1, lbl, color=col, fontsize=8,
                               va="bottom", ha="left", clip_on=True, bbox=_bbox)
                elif kind == "arrow" and None not in (x1, y1, x2, y2):
                    if ai == 0:
                        a.annotate(lbl or "", xy=(_xconv(x1), y1), xytext=(_xconv(x2), y2),
                                   color=col, fontsize=8, ha="center", va="bottom",
                                   annotation_clip=True,
                                   arrowprops=dict(arrowstyle="->", color=col, lw=1))
                elif kind == "rect" and None not in (x1, y1, x2, y2):
                    # Rectangle은 폭이 숫자여야 한다 — 시간축이면 mpl 날짜수(일)로
                    # 바꿔서 넣는다(datetime - datetime = timedelta라 그냥은 안 된다).
                    import matplotlib.dates as _mdates
                    conv = (lambda v: _mdates.date2num(_dt.datetime.fromtimestamp(v))
                            ) if self._time_axis else (lambda v: v)
                    xa, xb = conv(min(x1, x2)), conv(max(x1, x2))
                    a.add_patch(_Rect((xa, min(y1, y2)),
                                      (xb - xa), abs(y2 - y1),
                                      facecolor=col, alpha=0.18, edgecolor=col, lw=1, zorder=0))
                    if show_label:
                        a.text(xa, max(y1, y2), f" {lbl}", color=col, fontsize=8,
                               va="bottom", ha="left", clip_on=True, bbox=_bbox)
        if getattr(self, "_annots", []):
            for a, xl, yl in saved_lims:    # 주석이 늘려놓은 범위 원상복구(ignoreBounds 동치)
                a.set_xlim(xl); a.set_ylim(yl)
        # 범례 위치/끄기 — 모드가 만든 범례를 중앙에서 재배치
        loc = self._legend_combo.currentText() if hasattr(self, "_legend_combo") else "TL"
        a0 = axes[0]
        lg = a0.get_legend()
        if loc == "off":
            for a in axes:
                if a.get_legend() is not None:
                    a.get_legend().remove()
        elif lg is not None:
            handles = getattr(lg, "legend_handles", None) or getattr(lg, "legendHandles", [])
            labels = [t.get_text() for t in lg.get_texts()]
            if handles:
                lsz = self._legend_size.value() if hasattr(self, "_legend_size") else 0
                lfs = lsz if lsz > 0 else (sz if sz > 0 else 9)   # 범례 전용크기 > 라벨크기 > 9
                a0.legend(handles, labels, loc=_LEGEND_MPL.get(loc, "best"), fontsize=lfs)

    def set_status(self, text):
        self._status.setText(text)

    def _default_export_name(self):
        """자동 파일명 베이스(확장자 제외): {데이터}_{모드}_{시리즈}_{저장시각}.
        예) 260622-260629-CH1_timeseries_NO2-CHOCHO_260629-1612.  실패 시 'plot'."""
        import re as _re
        from datetime import datetime as _dt

        def _san(s):
            return _re.sub(r"[^0-9A-Za-z가-힣]+", "-", str(s)).strip("-")

        # 어떤 데이터를 썼는지(선반의 데이터셋=파일 이름). 길면 각 22자로 축약.
        ds_names = list(self.shelf.keys())
        if not ds_names:
            ds = ""
        elif len(ds_names) <= 2:
            ds = "-".join(_san(n)[:22] for n in ds_names)
        else:
            ds = "-".join(_san(n)[:22] for n in ds_names[:2]) + f"-plus{len(ds_names) - 2}"

        mode = getattr(self._mode, "key", "") or getattr(self._mode, "label", "") or "plot"
        series = []
        try:
            tbl = self._mode.csv_table()
            if tbl and tbl[0]:
                for h in tbl[0]:
                    if str(h).strip().lower() in ("datetime", "time", "index"):
                        continue
                    series.append(str(h))
        except Exception:
            pass
        parts = [p for p in (_san(s) for s in series) if p]
        if len(parts) > 3:
            ser = "-".join(parts[:3]) + f"-plus{len(parts) - 3}"
        else:
            ser = "-".join(parts)

        stamp = _dt.now().strftime("%y%m%d-%H%M")
        base = "_".join(x for x in (ds, _san(mode), ser, stamp) if x)
        return base or "plot"

    # ── 선반 ────────────────────────────────────────────────────────────
    def column_choices(self):
        return [f"{name}:{col}" for name, ds in self.shelf.items() for col in ds.cols]

    def selected_columns(self):
        out = []
        for it in self._tree.selectedItems():
            data = it.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and data[0] == "col":
                out.append(f"{data[1]}:{data[2]}")
        return out

    def resolve(self, label):
        """"ds:col" → (Dataset, col, y, t) 또는 None.

        모든 모드·Publish가 데이터를 받는 **유일한 길목**이다. 그래서 보기 상태도 여기서만 건다:
          · t: 전역 time_shift_hours + 데이터셋 shift_h 만큼 표시용으로 이동(ds.time 원본 불변)
          · y: 데이터셋 숨김 규칙에 걸린 행은 NaN(사본) — ds.cols 원본 불변, 규칙 끄면 복원"""
        if not label or ":" not in label:
            return None
        name, col = label.split(":", 1)
        ds = self.shelf.get(name)
        if ds is None or col not in ds.cols:
            return None
        t = ds.time
        shift_h = self.time_shift_hours + ds.shift_h
        if t is not None and shift_h:
            t = t + shift_h * 3600.0
        y = ds.cols[col]
        hidden = ds.hidden_mask()
        if hidden is not None and hidden.any():
            y = np.where(hidden, np.nan, y)
        return ds, col, y, t

    # 명시 단위가 없을 때 ppb로 볼 미량기체 농도 컬럼(정확 매칭 — _Shift/_Squeeze 등 제외).
    _PPB_COLS = {"no2", "ans", "pns", "chocho", "glyoxal", "h2o",
                 "o4", "o3", "hcho", "co", "so2"}

    def unit_of(self, label):
        """"ds:col"의 단위 문자열(모르면 None). 명시 단위 없으면 인식되는 미량기체
        농도 컬럼은 ppb 기본(박사님 요청: ANs 등 단위 표기)."""
        if not label or ":" not in label:
            return None
        name, col = label.split(":", 1)
        ds = self.shelf.get(name)
        u = ds.units.get(col) if ds else None
        if u:
            return u
        return "ppb" if (col or "").strip().lower() in self._PPB_COLS else None

    def error_of(self, label):
        """"ds:col"의 1σ 오차배열(fit 결과 {gas}_Error). 없으면 None — 에러밴드용."""
        if not label or ":" not in label:
            return None
        name, col = label.split(":", 1)
        ds = self.shelf.get(name)
        return ds.errs.get(col) if ds is not None else None

    def _add_data(self):
        from gui.dlg_dir import dlg_dir
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add result file(s)", dlg_dir("result"),
            "Result files (*.dat *.csv *.txt *.tsv);;All Files (*)")
        if not paths:
            return
        dlg_dir("result", paths[0])
        self.add_paths(paths)

    def _add_data_by_date(self):
        """일별 핏 버킷에서 기간·시리즈 선택  자동 머지 파일을 선반에 추가."""
        from gui.dlg_date_load import DateLoadDialog
        dlg = DateLoadDialog(self)
        if dlg.exec() and dlg.loaded_paths:
            self.add_paths(dlg.loaded_paths)

    def add_paths(self, paths):
        """파일 경로 목록을 선반에 로드(파일 추가·날짜 로드·드롭에서 호출)."""
        return self.add_specs(paths)

    def add_specs(self, specs):
        """레시피 목록을 선반에 로드 — 경로 문자열 또는 {"path","rules","shift_h"}.
        Result Lab의 'To Plot Maker'가 보던 상태(QC·구간·시프트)를 규칙으로 실어 보낸다."""
        added = 0
        n_hidden = 0
        for spec in specs:
            p = spec if isinstance(spec, str) else spec.get("path", "")
            try:
                ds = load_spec(spec)
            except Exception as e:
                QMessageBox.warning(self, "Load failed", f"{os.path.basename(p)}: {e}")
                continue
            n_hidden += ds.n_hidden()
            name = ds.name
            i = 2
            while name in self.shelf:        # 이름 충돌 → 번호
                name = f"{ds.name}#{i}"
                i += 1
            ds.name = name
            self.shelf[name] = ds
            added += 1
        if added:
            self._refresh_tree()
            self._notify_modes()
            hid = (f" · {n_hidden} rows hidden by carried filters (right-click dataset to turn off)"
                   if n_hidden else "")
            self.set_status(f"Added {added} dataset(s) · {len(self.shelf)} on shelf{hid}")
        return added

    def _on_tree_double_click(self, item, _col=0):
        """Data 탭에서 컬럼 더블클릭 → 현재 모드로 바로 플롯. 데이터셋 헤더는 무시(펼침)."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not (isinstance(data, tuple) and data[0] == "col"):
            return
        label = f"{data[1]}:{data[2]}"
        if self._mode.on_column_activated(label):
            self.set_status(f"Plotted: {label} ({self._mode.label})")

    def _dataset_at(self, item):
        data = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        return self.shelf.get(data[1]) if isinstance(data, tuple) else None

    def _on_tree_menu(self, pos):
        """데이터셋 우클릭 — 실어 온 숨김 규칙·시프트를 켜고 끄거나 지운다."""
        from PyQt6.QtWidgets import QMenu
        item = self._tree.itemAt(pos)
        ds = self._dataset_at(item)
        if ds is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        col = data[2] if data[0] in ("col", "bad") else None
        menu = QMenu(self)
        a_new = menu.addAction("New column…")
        a_join = menu.addAction("Join with another dataset…")
        a_join.setEnabled(ds.time is not None and len(self.shelf) > 1)
        a_edit = a_del = None
        if col in ds.derived_names():
            a_edit = menu.addAction(f"Edit column '{col}'…")
            a_del = menu.addAction(f"Delete column '{col}'")
        menu.addSeparator()
        a_flt = menu.addAction("Filters…")
        a_on = menu.addAction("Filters on")
        a_on.setCheckable(True)
        a_on.setChecked(ds.rules_on)
        a_on.setEnabled(bool(ds.rules))
        a_clr = menu.addAction("Clear filters")
        a_clr.setEnabled(bool(ds.rules))
        a_sh = menu.addAction(f"Clear dataset time shift ({ds.shift_h:+g}h)")
        a_sh.setEnabled(bool(ds.shift_h))
        act = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if act is None:
            return
        if act is a_new or act is a_edit:
            from .derived_dialog import DerivedColumnDialog
            editing = col if act is a_edit else None
            dlg = DerivedColumnDialog(ds, editing=editing, parent=self)
            if dlg.exec():
                self.set_derived(ds.name, dlg.spec(), replace=editing)
        elif act is a_del:
            self.delete_derived(ds.name, col)
        elif act is a_join:
            from .join_dialog import JoinDialog
            dlg = JoinDialog(ds.name, self.shelf, parent=self)
            if dlg.exec():
                self.add_join(dlg.spec())
        elif act is a_flt:
            from .filters_dialog import FiltersDialog
            dlg = FiltersDialog(ds, parent=self)
            if dlg.exec():
                rules, on = dlg.chosen()
                self.set_dataset_view(ds.name, rules=rules, rules_on=on)
        elif act is a_on:
            self.set_dataset_view(ds.name, rules_on=a_on.isChecked())
        elif act is a_clr:
            self.set_dataset_view(ds.name, rules=[])
        elif act is a_sh:
            self.set_dataset_view(ds.name, shift_h=0.0)

    def set_dataset_view(self, name, rules=None, rules_on=None, shift_h=None):
        """데이터셋 보기 상태 변경 → 트리·모드 갱신. 원본 값은 건드리지 않는다."""
        ds = self.shelf.get(name)
        if ds is None:
            return
        ds.set_rules(rules, rules_on)
        if shift_h is not None:
            ds.shift_h = float(shift_h)
            if ds.derived:
                ds.apply_derived()        # `hour`는 데이터셋 시프트를 따른다
        ds.hidden_mask()                  # rule_errors 갱신(트리 ✗ 표시용)
        self._refresh_tree()
        self._notify_modes()
        self._mode.render()
        state = ("off" if not ds.rules_on else f"{ds.n_hidden()} hidden") if ds.rules else "none"
        self.set_status(f"{name}: filters {state} · shift {ds.shift_h:+g}h")

    def set_derived(self, name, spec, replace=None):
        """파생 열 추가(replace=None) 또는 교체. 이름을 바꿔 교체하면 그 열을 쓰던 시리즈는
        on_shelf_changed가 정리한다(없는 열을 가리키게 두지 않는다). 반환: 오류문|None."""
        ds = self.shelf.get(name)
        if ds is None:
            return "no such dataset"
        err = ds.check_derived_name(spec.get("name"), editing=replace)
        if err:
            return err
        spec = {"name": spec["name"].strip(), "expr": (spec.get("expr") or "").strip(),
                **({"unit": spec["unit"]} if spec.get("unit") else {})}
        if replace is not None and replace in ds.derived_names():
            ds.derived[ds.derived_names().index(replace)] = spec
        else:
            ds.derived.append(spec)
        ds.apply_derived()
        self._after_derived_change(ds, spec["name"])
        return ds.derived_errors.get(spec["name"])

    def delete_derived(self, name, col):
        ds = self.shelf.get(name)
        if ds is None or col not in ds.derived_names():
            return
        ds.derived = [d for d in ds.derived if d["name"] != col]
        ds.apply_derived()          # 이 열을 쓰던 다른 파생 열은 빨갛게 드러난다
        self._after_derived_change(ds, col, deleted=True)

    def _after_derived_change(self, ds, col, deleted=False):
        self._refresh_tree()
        self._notify_modes()
        self._mode.render()
        bad = [n for n in ds.derived_errors]
        msg = f"{ds.name}: column '{col}' {'deleted' if deleted else 'updated'}"
        if bad:
            msg += f" · ✗ broken: {', '.join(bad)}"
        self.set_status(msg)

    def _remove_data(self):
        names = set()
        for it in self._tree.selectedItems():
            data = it.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple):
                names.add(data[1])
        if names:
            self.push_undo("dataset", [(n, self.shelf[n]) for n in names if n in self.shelf])
        for n in names:
            self.shelf.pop(n, None)
        if names:
            self.set_status(f"{len(names)} dataset(s) removed — Ctrl+Z to restore")
            self._refresh_tree()
            self._notify_modes()

    def add_dataset(self, ds):
        """메모리에서 만든 데이터셋(콘솔 push 등)을 선반에 → 실제 이름. 설정에서 대기 중이던
        같은 이름의 콘솔 데이터셋이면 저장돼 있던 필터·파생 열을 다시 건다."""
        base, name, i = ds.name, ds.name, 2
        while name in self.shelf:
            name = f"{base}#{i}"; i += 1
        ds.name = name
        spec = self._console_pending.pop(name, None)
        if spec and ds.origin:
            ds.set_rules(spec.get("rules") or [], spec.get("rules_on", True))
            ds.derived = [dict(d) for d in (spec.get("derived") or [])]
            if ds.derived:
                ds.apply_derived()
        self.shelf[name] = ds
        self._refresh_tree()
        self._notify_modes()
        return name

    def _open_console(self):
        from .console import ConsoleWindow
        if self._console_dlg is None:
            self._console_dlg = ConsoleWindow(self)
        self._console_dlg.show()
        self._console_dlg.raise_()
        self._console_dlg.activateWindow()
        if self._console_pending:
            self._console_dlg._write(
                "# saved console datasets (not re-run automatically): "
                + ", ".join(f"rerun({n!r})" for n in self._console_pending) + "\n")

    def _rebuild_joins(self):
        """Join 데이터셋을 재료에서 다시 만든다 — 재료의 규칙·파생 열·시프트가 바뀌었거나
        재료가 지워졌을 때. 선반 순서대로(Join의 Join도 재료가 앞에 있으면 된다)."""
        for ds in self.shelf.values():
            if ds.join:
                ds.rebuild_join(self.shelf)

    def add_join(self, join, name=None):
        """Join 데이터셋을 선반에 추가 → 이름(실패면 None, 오류는 상태줄)."""
        base = name or f"{join['base']}⋈{join['other']}"
        name, i = base, 2
        while name in self.shelf:
            name = f"{base}#{i}"; i += 1
        ds = make_join(name, join, self.shelf)
        if ds.join_info.get("error"):
            self.set_status(f"Join failed: {ds.join_info['error']}")
            return None
        self.shelf[name] = ds
        self._refresh_tree()
        self._notify_modes()
        ji = ds.join_info
        self.set_status(f"Joined {name}: {ji['matched']} of {ji['rows']} rows paired · "
                        f"{ji['n_gap']} left empty (gap > {ji['max_gap_s'] / 60:.3g} min)")
        return name

    def _refresh_tree(self):
        self._rebuild_joins()          # 트리를 다시 그리는 모든 경로 = 선반이 바뀐 경로
        self._tree.clear()
        from gui.result_viewer_io import describe_rule
        for name, ds in self.shelf.items():
            tags = []
            if ds.join:
                tags.append("⋈ " + ("✗ " + ds.join_info["error"] if ds.join_info.get("error")
                                    else f"{ds.join_info.get('matched', 0)} paired"))
            if ds.origin and ds.origin.get("kind") == "console":
                tags.append("⌨ console")
            if ds.rules:
                tags.append(f"{ds.n_hidden()} hidden" if ds.rules_on else "filters off")
                if ds.rule_errors:            # n_hidden()이 방금 갱신했다
                    tags.append(f"✗ {len(ds.rule_errors)} broken filter")
            if ds.shift_h:
                tags.append(f"{ds.shift_h:+g}h")
            tag = ("  · " + " · ".join(tags)) if tags else ""
            top = QTreeWidgetItem([f"{name}  ({len(ds)}×{len(ds.cols)}){tag}"])
            top.setData(0, Qt.ItemDataRole.UserRole, ("ds", name))
            tip = ["time axis " if ds.time is not None else "no time axis"]
            if ds.join:
                j, ji = ds.join, ds.join_info
                tip.append(f"join: {j['base']} (time axis) ⋈ {j['other']} → columns +'{j.get('suffix', '_B')}'")
                if ji.get("error"):
                    tip.append(f"✗ {ji['error']}")
                else:
                    tip.append(f"  {ji['method']} · max gap {ji['max_gap_s'] / 60:.3g} min · "
                               f"{ji['matched']} of {ji['rows']} rows paired, {ji['n_gap']} left empty")
                tip.append("  rebuilt from its sources whenever they change (sources' filters apply)")
            if ds.origin and ds.origin.get("kind") == "console":
                hist = ds.origin.get("history") or []
                tip.append(f"made in the console — not reproducible from files. {len(hist)} input line(s) saved:")
                tip += [f"  >>> {ln}" for ln in hist[-8:]]
            if ds.cats:
                tip.append("categorical: " + ", ".join(ds.cats))
            if ds.rules:
                tip.append(f"filters ({'on' if ds.rules_on else 'OFF'}) — hidden, not deleted:")
                tip += [f"  • {describe_rule(r)}"
                        + (f"   ✗ {ds.rule_errors[i]} (hides nothing)" if i in ds.rule_errors else "")
                        for i, r in enumerate(ds.rules)]
            if ds.shift_h:
                tip.append(f"dataset time shift {ds.shift_h:+g}h (display only)")
            tip.append("Right-click: new column · Filters… · on/off · clear")
            top.setToolTip(0, f"{ds.path}\n" + "\n".join(tip))
            for col in ds.cols:
                if col in ds._dcols:
                    continue                  # 파생 열은 아래에 식 순서대로
                ch = QTreeWidgetItem([col])
                ch.setData(0, Qt.ItemDataRole.UserRole, ("col", name, col))
                top.addChild(ch)
            for d in ds.derived:
                col = d["name"]
                if col in ds.derived_errors:
                    # 깨진 식은 조용히 빼지 않는다 — 빨갛게 보이고, 플롯 대상은 아니다
                    ch = QTreeWidgetItem([f"ƒ {col}  ✗"])
                    ch.setData(0, Qt.ItemDataRole.UserRole, ("bad", name, col))
                    ch.setForeground(0, pg.mkColor(AUGUR.fail))
                    ch.setToolTip(0, f"{col} = {d['expr']}\n✗ {ds.derived_errors[col]}\n"
                                     "Right-click → Edit column…")
                else:
                    ch = QTreeWidgetItem([f"ƒ {col}"])
                    ch.setData(0, Qt.ItemDataRole.UserRole, ("col", name, col))
                    ch.setToolTip(0, f"{col} = {d['expr']}\n(derived — recomputed from the "
                                     "expression whenever the dataset is loaded)")
                top.addChild(ch)
            self._tree.addTopLevelItem(top)
            top.setExpanded(True)
        if hasattr(self, "_tree_search") and self._tree_search.text():
            self._filter_tree(self._tree_search.text())   # 검색 중이었으면 새 트리에도 재적용

    def _filter_tree(self, text):
        """Data 탭 검색상자 — 데이터셋명 또는 컬럼명에 부분일치(대소문자 무관).
        일치하는 컬럼이 있으면 그 부모 데이터셋도 보이게 유지."""
        q = (text or "").strip().lower()
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            top_match = q in top.text(0).lower()
            any_child_match = False
            for j in range(top.childCount()):
                ch = top.child(j)
                # 데이터셋명 자체가 일치하면 그 안의 모든 컬럼을 보여줌(부분필터 X)
                m = (not q) or top_match or (q in ch.text(0).lower())
                ch.setHidden(not m)
                any_child_match = any_child_match or m
            top.setHidden(bool(q) and not top_match and not any_child_match)

    def _notify_modes(self):
        for m in self._modes:
            m.on_shelf_changed()

    def is_active_mode(self, mode):
        """현재 화면에 표시 중인 모드인가 — on_shelf_changed()가 비활성 모드까지
        불필요하게 재렌더하지 않도록 각 모드가 이걸로 판단한다."""
        return self._mode is mode

    def push_undo(self, kind, payload):
        """가벼운 1단계 undo — 방금 지운 것만 기억(전체 실행취소 스택 아님).
        Ctrl+Z로 되돌리기(undo_last). kind: 'dataset' | 'timeseries_series'."""
        self._undo_slot = (kind, payload)

    def undo_last(self):
        if self._undo_slot is None:
            self.set_status("Nothing to undo.")
            return
        kind, payload = self._undo_slot
        self._undo_slot = None
        if kind == "dataset":
            restored = 0
            for name, ds in payload:
                if name not in self.shelf:
                    self.shelf[name] = ds
                    restored += 1
            self._refresh_tree()
            self._notify_modes()
            self.set_status(f"{restored} dataset(s) restored")
        elif kind == "timeseries_series":
            ts = next((m for m in self._modes if m.key == "timeseries"), None)
            if ts is not None:
                for s in payload:
                    if not any(s is existing for existing in ts._series):
                        ts._series.append(s)
                if ts._w:
                    ts._refresh_list()
                if self.is_active_mode(ts):
                    ts.render()
                self.set_status(f"↩ {len(payload)} series restored")

    # ── 창 상태 기억(QSettings — dlg_dir.py와 같은 네임스페이스 관례) ──────
    def _save_window_state(self):
        self._qs.setValue("plotmaker/splitter", self._split.sizes())
        self._qs.setValue("plotmaker/tab", self._tabs.currentIndex())
        if hasattr(self, "_theme_combo"):
            self._qs.setValue("plotmaker/theme", self._theme_combo.currentText())

    def _restore_window_state(self):
        sizes = self._qs.value("plotmaker/splitter", None)
        if sizes:
            try:
                self._split.setSizes([int(v) for v in sizes])
            except (TypeError, ValueError):
                pass
        tab = self._qs.value("plotmaker/tab", None)
        if tab is not None:
            try:
                i = int(tab)
                if 0 <= i < self._tabs.count():
                    self._tabs.setCurrentIndex(i)
            except (TypeError, ValueError):
                pass
        theme = self._qs.value("plotmaker/theme", None)
        # 2026-10-01 UI 영어화 이전에 저장된 한글 테마 이름도 복원한다.
        theme = {"기본": "Default", "논문": "Paper", "다크": "Dark"}.get(theme, theme)
        if theme and hasattr(self, "_theme_combo"):
            i = self._theme_combo.findText(theme)
            if i >= 0:
                self._theme_combo.setCurrentIndex(i)
                self._apply_theme(theme)   # 시작 시 데이터 없어 무해 — 지난 세션 룩 그대로 복원

    def _on_theme_combo_changed(self):
        self._apply_theme(self._theme_combo.currentText())
        self._save_window_state()

    # ── 모드 전환 / 가공 변경 ───────────────────────────────────────────
    def _rebuild_mode_options(self):
        idx = self._modes.index(self._mode)
        self._opt_stack.setCurrentIndex(idx)

    def _on_mode_changed(self, idx):
        self._mode = self._modes[idx]
        self._opt_stack.setCurrentIndex(idx)
        # 🎨 Colors는 고정 색요소(color_keys)가 있는 모드에서만 활성
        if hasattr(self, "_btn_colors"):
            self._btn_colors.setEnabled(bool(self._mode.color_keys()))
        self._apply_recommended_size()      # 모드별 권장 크기 자동(체크 시)
        self._mode.render()

    def _apply_publish_preset(self, name):
        """크기·해상도 프리셋 적용. '모드별 권장 크기 자동'은 끈다 — 안 그러면
        모드를 바꾸는 순간 프리셋이 조용히 덮여서 논문 폭으로 맞춘 게 풀린다."""
        pre = _PUBLISH_PRESETS.get(name)
        if not pre:
            return
        w, h, dpi = pre
        self._chk_autosize.setChecked(False)
        self._fig_w.setValue(w); self._fig_h.setValue(h); self._dpi_spin.setValue(dpi)
        self.set_status(f"Publish preset: {name} — {w}×{h} in @ {dpi} dpi "
                        f"(Auto size per mode turned off)")

    def _apply_recommended_size(self, force=False):
        """현재 모드에 맞는 권장 Publish 크기(W×H 인치)를 적용.
        force=False면 '자동' 체크가 켜졌을 때만(모드 전환용). force=True면 버튼."""
        if not hasattr(self, "_fig_w"):
            return
        if not force and not (hasattr(self, "_chk_autosize") and self._chk_autosize.isChecked()):
            return
        wh = _RECOMMENDED_SIZE.get(getattr(self._mode, "key", ""))
        if not wh:
            return
        self._fig_w.blockSignals(True); self._fig_h.blockSignals(True)
        self._fig_w.setValue(wh[0]); self._fig_h.setValue(wh[1])
        self._fig_w.blockSignals(False); self._fig_h.blockSignals(False)
        if force:
            self.set_status(f"Recommended size applied: {wh[0]}×{wh[1]} in ({self._mode.label})")

    def _apply_palette(self, family):
        """색 계열 프리셋 → 현재 모드 색을 그 계열 톤으로 자동 배색.
        '자동(종별)'이면 오버라이드를 지워 종 이름 기반 색으로 되돌린다.
        시계열=시리즈마다 진↔연, color_keys 모드(diurnal/scatter/…)=요소마다 진↔연."""
        mode = self._mode
        if family == _PALETTE_AUTO:
            ts = next((m for m in self._modes if m.key == "timeseries"), None)
            if ts is not None:
                for s in ts._series:
                    s[2] = None
            if mode.color_keys():
                mode.colors.clear()
            self.set_status("Color: back to Auto (by species)")
            self._mode.render()
            return
        # 범주형(Okabe-Ito 등)은 목록을 순서대로 돌려 쓰고, 계통색은 진↔연 톤을 만든다.
        cat = _CATEGORICAL.get(family)
        base = _FAMILIES.get(family)
        if cat is None and not base:
            return

        def colors_for(n):
            if cat is not None:
                return [cat[i % len(cat)] for i in range(max(n, 1))]
            return _family_shades(base, max(n, 1))

        if mode.key == "timeseries":
            shades = colors_for(len(mode._series))
            for i, s in enumerate(mode._series):
                s[2] = shades[i]
            if hasattr(mode, "_refresh_list"):
                mode._refresh_list()
        else:
            keys = mode.color_keys()
            if keys:
                shades = colors_for(len(keys))
                for (key, _lab, _def), c in zip(keys, shades):
                    mode.colors[key] = c
        self.set_status(f"Color family applied: {family}")
        self._mode.render()

    def _apply_theme(self, name):
        """테마 프리셋 → 폰트·범례 크기·그리드를 일괄 설정하고 시리즈 선두께도 맞춤."""
        th = _THEMES.get(name)
        if not th:
            return
        self._lbl_size.blockSignals(True); self._legend_size.blockSignals(True)
        self._lbl_size.setValue(int(th["font"]))
        self._legend_size.setValue(int(th["legend"]))
        self._lbl_size.blockSignals(False); self._legend_size.blockSignals(False)
        if hasattr(self, "_chk_grid"):
            self._chk_grid.blockSignals(True)
            self._chk_grid.setChecked(bool(th["grid"]))
            self._chk_grid.blockSignals(False)
        # 시계열 시리즈 기본 선두께를 테마에 맞춤(개별 지정은 보존)
        ts = next((m for m in self._modes if m.key == "timeseries"), None)
        if ts is not None:
            for lab in [s[0] for s in getattr(ts, "_series", [])]:
                st = ts._styles.setdefault(lab, {})
                st["width"] = int(th["line"])
        # 저널 프리셋의 추가 항목(일반 테마엔 없다 — 색·크기는 안 건드린다)
        extra = []
        if "tick" in th:
            self._tick_size.blockSignals(True); self._tick_size.setValue(int(th["tick"]))
            self._tick_size.blockSignals(False)
        if "tick_dir" in th:
            self._tick_dir.blockSignals(True); self._tick_dir.setCurrentText(th["tick_dir"])
            self._tick_dir.blockSignals(False)
        if th.get("palette"):
            self._palette_combo.setCurrentText(th["palette"])
            self._apply_palette(th["palette"])
            extra.append(th["palette"].split(" (")[0])
        if th.get("publish"):
            self._preset_combo.setCurrentText(th["publish"])
            self._apply_publish_preset(th["publish"])
            w, h, dpi = _PUBLISH_PRESETS[th["publish"]]
            extra.append(f"{w}×{h} in @ {dpi} dpi")
        self.set_status(f"Theme applied: {name}" + (f" — {', '.join(extra)}" if extra else ""))
        self._mode.render()

    def _on_transform_changed(self, *_):
        is_custom = self._res_combo.currentText() == _RESAMPLE_CUSTOM
        self._res_custom_spin.setEnabled(is_custom)
        if is_custom:
            self.resample_sec = self._res_custom_spin.value() * 60.0
        else:
            self.resample_sec = _RESAMPLE.get(self._res_combo.currentText(), 0)
        self.smooth_n = self._smooth_spin.value()
        self.time_shift_hours = self._shift_spin.value()
        self._mode.render()

    def _on_labels_changed(self):
        self.custom = {"title": self._ed_title.text(), "xlabel": self._ed_x.text(),
                       "ylabel": self._ed_y.text(), "rlabel": self._ed_r.text()}
        self._mode.render()

    def _build_label_row(self, key, line_edit):
        """Labels 그룹박스 한 줄: [텍스트][크기(0=전역)][🎨 색][↺ 리셋][📍 자유배치].
        self._label_style_widgets[key]에 위젯들을 저장해 설정 저장/불러오기 때 재사용."""
        line_edit.editingFinished.connect(self._on_labels_changed)
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line_edit, 1)
        sp = QSpinBox(); sp.setRange(0, 40); sp.setSpecialValueText("−"); sp.setSuffix("pt")
        sp.setFixedWidth(58)
        sp.setToolTip("Font size for this label only (0 = use global Font size)")
        sp.valueChanged.connect(lambda v, k=key: self._on_label_style_changed(k))
        row.addWidget(sp)
        btn = QPushButton("C"); btn.setFixedWidth(26)
        btn.setToolTip("Set this label's text color (left-click to pick)")
        btn.clicked.connect(lambda _, k=key, b=btn: self._pick_label_color(k, b))
        row.addWidget(btn)
        btn_rst = QPushButton("↺"); btn_rst.setFixedWidth(22)
        btn_rst.setToolTip("Reset this label's size and color to auto")
        btn_rst.clicked.connect(lambda _, k=key: self._reset_label_style(k))
        row.addWidget(btn_rst)
        chk = QCheckBox("Pin")
        chk.setToolTip("When checked, drag it anywhere inside the plot or into the margins.\n"
                      "Position is stored as a fraction of the view, so screen and Publish always match.")
        chk.toggled.connect(lambda on, k=key: self.toggle_label_free_pos(k, on))
        row.addWidget(chk)
        self._label_style_widgets[key] = {"size": sp, "color_btn": btn, "free_chk": chk}
        w = QWidget(); w.setLayout(row)
        return w

    def _on_label_style_changed(self, key):
        sp = self._label_style_widgets[key]["size"]
        st = self.label_style.setdefault(key, {"pos": None, "size": None, "color": None})
        st["size"] = sp.value() or None
        self._mode.render()

    def _pick_label_color(self, key, btn):
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor
        cur = (self.label_style.get(key) or {}).get("color") or "#000000"
        c = QColorDialog.getColor(QColor(cur), self, f"{key} color")
        if not c.isValid():
            return
        st = self.label_style.setdefault(key, {"pos": None, "size": None, "color": None})
        st["color"] = c.name()
        btn.setStyleSheet(f"background:{c.name()};")
        self._mode.render()

    def _sync_label_style_widgets(self):
        """label_style(설정 불러오기 등으로 바뀜)  Size/색/ 위젯 표시 동기화."""
        for k, w in getattr(self, "_label_style_widgets", {}).items():
            st = self.label_style.get(k) or {}
            sp, btn, chk = w["size"], w["color_btn"], w["free_chk"]
            sp.blockSignals(True); sp.setValue(int(st.get("size") or 0)); sp.blockSignals(False)
            btn.setStyleSheet(f"background:{st['color']};" if st.get("color") else "")
            chk.blockSignals(True); chk.setChecked(st.get("pos") is not None); chk.blockSignals(False)

    def _reset_label_style(self, key):
        st = self.label_style.setdefault(key, {"pos": None, "size": None, "color": None})
        st["size"] = None; st["color"] = None
        w = self._label_style_widgets.get(key)
        if w:
            w["size"].blockSignals(True); w["size"].setValue(0); w["size"].blockSignals(False)
            w["color_btn"].setStyleSheet("")
        self._mode.render()

    def _on_axes_changed(self, *_):
        self._mode.render()

    # ── Export / config ────────────────────────────────────────────────
    @staticmethod
    def _apply_mpl_rc(matplotlib):
        """Publish(matplotlib) 전역 설정 1회 — 한글 폰트 + **출판용 폰트 처리**.

        폰트 타입 (2026-09-21 추가, 근거: Copernicus(ACP·AMT) 저자 규정
        "vector graphics first, fonts must be embedded"):

          · `pdf.fonttype`/`ps.fonttype` = **42**(TrueType). matplotlib 기본은
            **3**(Type 3)인데, Type 3는 임베딩돼 있어도 **투고 시스템이 거부하는
            곳이 있다**(IEEE·AAAI 보고 사례). 그림은 잘 보이는데 제출에서 막히는,
            제일 늦게 발견되는 종류의 사고다. 파일이 조금 커지는 값은 치를 만하다.
            ⚠ EPS 출력을 나중에 붙일 때: mpl에 Type 42 + EPS 조합 버그가 보고돼
              있다(matplotlib#27328) — 그때 실제 파일로 확인할 것.
          · `svg.fonttype` = **"none"**(글자를 글자로). 기본 `'path'`는 글자를
            패스로 바꿔 박아서 **Illustrator/Inkscape에서 편집이 불가능**하다.
            우리 설계는 "마지막 5%는 SVG로 넘겨 벡터 편집"이므로 기본이 정반대였다.
            대가: SVG를 여는 쪽에 그 폰트가 없으면 다른 글꼴로 대체된다 →
            **배포·열람용은 PDF**(폰트 임베딩됨), **편집용은 SVG**로 나눠 쓴다.
        """
        if getattr(PlotMakerWidget, "_kfont_done", False):
            return
        PlotMakerWidget._kfont_done = True
        try:
            from matplotlib import font_manager as fm
            avail = {f.name for f in fm.fontManager.ttflist}
            # 한글 폰트를 **전역 family로 걸지 않는다**(2026-09-21).
            # 예전엔 `font.family = "Malgun Gothic"`이라 한글이 한 글자도 없는 논문
            # 그림까지 한글 폰트로 찍혔다 — 임베딩이 무겁고, Copernicus의 "한 폰트
            # 패밀리·sans-serif 권장"과도 어긋난다.
            # 대신 **`font.family`에 목록**을 준다 → matplotlib이 글리프 단위로
            # 폴백해서 ASCII는 Arial로, 한글 글자만 한글 폰트로 찍힌다.
            # ⚠ `font.sans-serif` 목록으로는 안 된다(실측): 그건 "하나를 고르는
            #    후보 목록"이라 첫 폰트에 없는 글리프는 그냥 □가 된다.
            #    family=['sans-serif'] + sans-serif=[Arial,Malgun] → 한글 4자 누락,
            #    family=['Arial','Malgun Gothic']                  → 누락 0.
            ko = next((c for c in ("Malgun Gothic", "NanumGothic", "AppleGothic",
                                   "Noto Sans CJK KR", "Noto Sans KR", "Gulim", "Batang")
                       if c in avail), None)
            fams = [f for f in ("Arial", "Helvetica") if f in avail]
            if ko:
                fams.append(ko)
            fams.append("DejaVu Sans")          # mpl 기본(항상 있음)
            matplotlib.rcParams["font.family"] = fams
            matplotlib.rcParams["axes.unicode_minus"] = False   # 음수 기호 깨짐 방지
            matplotlib.rcParams["pdf.fonttype"] = 42
            matplotlib.rcParams["ps.fonttype"] = 42
            matplotlib.rcParams["svg.fonttype"] = "none"
        except Exception:
            pass

    # 한글 음절 + 자모 (라벨에 한글이 섞였는지 판정용)
    _HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")

    def _mixed_hangul_mathtext(self):
        """한글과 수식(`$…$`)이 **한 문자열에 섞인** 라벨 목록.

        matplotlib의 mathtext 엔진은 `$`가 하나라도 있으면 문자열 전체를 자기
        폰트셋으로 그리는데 거기엔 한글이 없다 → **한글만 조용히 □로 깨진다**
        (`mathtext.fontset='custom'`으로도 안 고쳐지는 걸 실측했다).
        한글만·수식만 있으면 멀쩡하다. 그래서 고치는 대신 **알려준다** —
        Publish PDF에서야 발견하는 게 제일 나쁘다."""
        texts = [t for t in self.custom.values() if t]
        ts = next((m for m in self._modes if m.key == "timeseries"), None)
        if ts is not None:
            texts += [s[3] for s in ts._series if s[3]]
        texts += [a.get("label") for a in getattr(self, "_annots", []) if a.get("label")]
        return [t for t in texts if "$" in t and self._HANGUL_RE.search(t)]

    def _build_publish_fig(self):
        """Publish용 matplotlib Figure 생성 — 미리보기·저장 공용(완전 동일 경로).
        실패 시 None(메시지 표시). NotImplementedError는 호출측에서 처리."""
        try:
            import matplotlib
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
        except Exception as e:
            QMessageBox.warning(self, "Publish", f"matplotlib unavailable: {e}")
            return None
        self._apply_mpl_rc(matplotlib)
        fig = Figure(figsize=(self._fig_w.value(), self._fig_h.value()))
        FigureCanvasAgg(fig)              # savefig용 캔버스 부착(백엔드 무관)
        notes = []
        composing = self.composer.active()
        if composing:                     # 다중 패널(M2) — 패널마다 자기 조각으로 그린다
            self.composer.build_fig(fig)
            from .composer import LETTERS
            sh = [f"({LETTERS[i % 26]}) {p.get('time_shift_hours', 0):+g}h"
                  for i, p in enumerate(self.composer.panels) if p.get("time_shift_hours")]
            if sh:
                notes.append("time shift applied (display only): " + ", ".join(sh))
        else:
            self._mode.render_mpl(fig)
            self._apply_axes_mpl(fig)
        # 조용한 시각 조작 금지 — 전역이든 데이터셋별이든 시프트가 걸렸으면 그림에 적는다.
        if self.time_shift_hours and not composing:
            notes.append(f"time shift {self.time_shift_hours:+g}h applied (display only)")
        ds_sh = [f"{n} {ds.shift_h:+g}h" for n, ds in self.shelf.items() if ds.shift_h]
        if ds_sh:
            notes.append("dataset shift: " + ", ".join(ds_sh))
        if notes:
            fig.text(0.995, 0.005, " · ".join(notes),
                     ha="right", va="bottom", fontsize=7, color="#b00")
        if composing:
            self.composer.tight(fig)      # inset이 있으면 tight_layout이 경고만 낸다
        else:
            fig.tight_layout()
        return fig

    def render_preview_png(self, dpi=110):
        """Publish와 **같은 함수**(`_build_publish_fig`)로 그린 PNG 바이트 — 미리보기 = 저장 파일.
        None = 그릴 게 없음. NotImplementedError/예외는 호출측이 처리."""
        fig = self._build_publish_fig()
        if fig is None:
            return None
        import io
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")  # 화면용 해상도
        mixed = self._mixed_hangul_mathtext()
        if mixed:
            self.set_status(f"⚠ {len(mixed)} label(s) mix Korean text and math — the Korean renders as □"
                            f" (e.g. {mixed[0][:20]}). Remove $…$ from Korean labels.")
        return buf.getvalue()

    def _preview_publish(self):
        """Publish 미리보기 — **모덜리스** 창(M-P). 띄워둔 채 고치면 자동으로 다시 그린다.
        이미 열려 있으면 앞으로 가져와 즉시 갱신(창은 하나만)."""
        from .preview_window import PreviewWindow
        dlg = getattr(self, "_preview_dlg", None)
        if dlg is None:
            dlg = self._preview_dlg = PreviewWindow(self)
        dlg.refresh()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _figure_dir(self):
        """그림 저장 다이얼로그가 처음 열릴 폴더: `{마지막 폴더}/{campaign}/figures/`.

        핏·알파·R과 같은 캠페인 아래로 그림도 모은다(A3). 다만 **강제하지 않는다** —
        저장 다이얼로그의 시작 위치일 뿐이라 사용자는 어디로든 갈 수 있다.
        날짜 폴더를 쓰지 않는 이유: 그림은 보통 여러 날을 걸친다.
        """
        from gui.dlg_dir import dlg_dir, campaign_of
        from core.paths import campaign_dir
        base = dlg_dir("figure") or dlg_dir("result") or "."
        d = os.path.join(campaign_dir(base, campaign_of(self)), "figures")
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            return base
        return d

    def _export_publish(self):
        """현재 모드를 matplotlib로 재렌더 → 고화질 PNG / 벡터 PDF·SVG."""
        out, _ = QFileDialog.getSaveFileName(
            self, "Publish (high quality)",
            os.path.join(self._figure_dir(), self._default_export_name() + ".png"),
            "PNG (*.png);;PDF (*.pdf);;SVG (*.svg);;EPS (*.eps)")
        if not out:
            return
        from gui.dlg_dir import dlg_dir as _dd
        _dd("figure", out)          # 다음 저장은 여기서 시작
        if not os.path.splitext(out)[1]:
            out += ".png"
        try:
            fig = self._build_publish_fig()
            if fig is None:
                return
            fig.savefig(out, dpi=self._dpi_spin.value(), bbox_inches="tight")
            ext = os.path.splitext(out)[1].lstrip(".").upper()
            extra = f" @ {self._dpi_spin.value()}dpi" if ext == "PNG" else " (vector)"
            msg = f"Published: {os.path.basename(out)} [{ext}{extra}]"
            mixed = self._mixed_hangul_mathtext()
            if mixed:
                msg += (f"  ⚠ {len(mixed)} label(s) mixing Korean text and math will render the Korean as □"
                        f" (e.g. {mixed[0][:20]}) — remove $…$ from Korean labels.")
            if ext == "EPS":
                # PostScript에는 알파 채널이 없다 — 반투명이 불투명하게 찍힌다.
                # 조용히 다른 그림이 나가는 것보다 말해주는 게 낫다.
                msg += ("  ⚠ EPS does not support transparency — error bands, night shading and "
                        "area/band fills come out opaque. Use PDF if you need transparency.")
            self.set_status(msg)
        except NotImplementedError:
            QMessageBox.information(self, "Publish",
                                   "This mode does not support high-res output yet.")
        except Exception as e:
            QMessageBox.warning(self, "Publish", f"Failed: {e}")

    def _batch_publish(self):
        """Time series/Diurnal 모드에서, Style 탭 TimeSeries 시리즈 목록에 있는
        각 컬럼을 종별로 개별 Publish PNG로 한 번에 저장한다. 매주 종(NO2·PNs·
        ANs·CHOCHO)마다 시계열·diurnal 각각 Publish를 반복하던 걸 자동화 —
        그 목록 자체를 "이번 주 보고할 종의 집합"으로 재사용한다(공용 소스)."""
        ts = next((m for m in self._modes if m.key == "timeseries"), None)
        if ts is None or not ts._series:
            QMessageBox.information(self, "Batch Publish",
                "Add series to Time series in the Style tab first — that list is what gets batched.")
            return
        if self._mode.key not in ("timeseries", "diurnal"):
            QMessageBox.information(self, "Batch Publish",
                "Batch Publish works only in Time series and Diurnal modes (switch mode in the Data tab).")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Batch Publish — choose output folder")
        if not out_dir:
            return

        cols = list(dict.fromkeys(s[0] for s in ts._series))   # "ds:col" 중복제거, 순서유지
        saved, failed = [], []
        dpi = self._dpi_spin.value()

        if self._mode.key == "timeseries":
            orig_series = ts._series
            try:
                for lab in cols:
                    entry = next((s for s in orig_series if s[0] == lab), None)
                    if entry is None:
                        continue
                    ts._series = [[entry[0], "L", entry[2], entry[3]]]   # 단독 좌축으로 고정
                    try:
                        fig = self._build_publish_fig()
                        if fig is None:
                            failed.append(f"{lab}: figure creation failed"); continue
                        col = lab.split(":", 1)[-1]
                        path = os.path.join(out_dir, f"timeseries_{col}.png")
                        fig.savefig(path, dpi=dpi, bbox_inches="tight")
                        saved.append(os.path.basename(path))
                    except Exception as e:
                        failed.append(f"{lab}: {e}")
            finally:
                ts._series = orig_series
                self._mode.render()
        else:   # diurnal
            dm = self._mode
            orig_index = dm._c.currentIndex()   # 텍스트가 아닌 인덱스로 복원(선택없음=-1도 정확히 복원)
            try:
                for lab in cols:
                    dm._c.setCurrentText(lab)
                    if dm._c.currentText() != lab:   # 콤보에 없는 컬럼(시간축 없음 등) 스킵
                        failed.append(f"{lab}: not in the diurnal list (column without a time axis?)")
                        continue
                    try:
                        fig = self._build_publish_fig()
                        if fig is None:
                            failed.append(f"{lab}: figure creation failed"); continue
                        col = lab.split(":", 1)[-1]
                        path = os.path.join(out_dir, f"diurnal_{col}.png")
                        fig.savefig(path, dpi=dpi, bbox_inches="tight")
                        saved.append(os.path.basename(path))
                    except Exception as e:
                        failed.append(f"{lab}: {e}")
            finally:
                dm._c.setCurrentIndex(orig_index)   # -1(선택없음)도 그대로 복원됨
                dm.render()

        msg = f"{len(saved)} saved: {', '.join(saved)}" if saved else "No files saved"
        if failed:
            msg += f"\nFailed/skipped ({len(failed)}): {'; '.join(failed)}"
        self.set_status(f"Batch Publish: {len(saved)} saved" + (f", {len(failed)} failed" if failed else ""))
        QMessageBox.information(self, "Batch Publish", msg)

    def _export_png(self):
        import pyqtgraph.exporters as pgex
        out, _ = QFileDialog.getSaveFileName(self, "Export PNG",
                                             self._default_export_name() + ".png", "PNG (*.png)")
        if not out:
            return
        if not out.lower().endswith(".png"):
            out += ".png"
        try:
            ex = pgex.ImageExporter(self.p1)
            ex.parameters()["width"] = 2400
            ex.export(out)
            self.set_status(f"PNG saved: {os.path.basename(out)} (2400px)")
        except Exception as e:
            QMessageBox.warning(self, "PNG export", f"Failed: {e}")

    def _copy_to_clipboard(self):
        """Ctrl+C — 파일 저장 없이 현재 화면을 바로 클립보드에 복사(PPT/문서에 Ctrl+V)."""
        import pyqtgraph.exporters as pgex
        try:
            ex = pgex.ImageExporter(self.p1)
            ex.parameters()["width"] = 2400
            ex.export(copy=True)
            self.set_status("Copied to clipboard (paste with Ctrl+V)")
        except Exception as e:
            QMessageBox.warning(self, "Copy", f"Failed: {e}")

    def _export_csv(self):
        """현재 모드가 제공하는 데이터(csv_table)를 CSV로 저장."""
        table = self._mode.csv_table()
        if not table:
            QMessageBox.information(self, "CSV",
                                   "Nothing to export for the current mode/selection.")
            return
        headers, rows = table
        out, _ = QFileDialog.getSaveFileName(self, "Export CSV",
                                             self._default_export_name() + ".csv", "CSV (*.csv)")
        if not out:
            return
        if not out.lower().endswith(".csv"):
            out += ".csv"
        try:
            import csv
            with open(out, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(headers)
                w.writerows(rows)
            self.set_status(f"CSV saved: {os.path.basename(out)} ({len(rows)} rows)")
        except Exception as e:
            QMessageBox.warning(self, "CSV export", f"Failed: {e}")

    def _save_cfg(self):
        out, _ = QFileDialog.getSaveFileName(self, "Save plot config",
                                             self._default_export_name() + ".pmcfg.json",
                                             "Plot config (*.json)")
        if not out:
            return
        cfg = self.config_dict()
        try:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            self.set_status(f"Config saved: {os.path.basename(out)}")
        except Exception as e:
            QMessageBox.warning(self, "Save config", f"Failed: {e}")

    def preview_signature(self):
        """그림을 바꿀 수 있는 상태 전부의 지문 — Preview 자동 갱신이 '바뀌었나'를 이것 하나로 본다.
        설정 저장과 같은 dict(그림을 재현하는 전부)를 쓰고, 화면 전용인 것(창 크기 등)은 안 든다.
        시리즈 색처럼 설정 dict 밖에 있는 것도 있어 모드 색·팔레트를 덧붙인다."""
        cfg = self.config_dict()
        cfg["_mode_colors"] = {m.key: dict(getattr(m, "colors", {}) or {}) for m in self._modes}
        cfg["_legend"] = (self._legend_combo.currentText(), self._legend_size.value(),
                          self._lbl_size.value())
        return json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str)

    def _axes_state(self):
        """축 탭 상태 dict — 설정 파일 "axes"·조판 패널이 같은 형식을 쓴다."""
        return {"xmin": self._ax_xmin.text(), "xmax": self._ax_xmax.text(),
                "ymin": self._ax_ymin.text(), "ymax": self._ax_ymax.text(),
                "rmin": self._ax_rmin.text(), "rmax": self._ax_rmax.text(),
                "logx": self._chk_logx.isChecked(), "logy": self._chk_logy.isChecked(),
                "grid": self._chk_grid.isChecked(), "grid_minor": self._chk_grid_minor.isChecked(),
                "tick_x": self._tick_x.text(), "tick_y": self._tick_y.text(),
                "tick_x_anchor": self._tick_x_anchor.text(),
                "tick_size": self._tick_size.value(),
                "tick_dir": self._tick_dir.currentIndex(),
                "tick_len": self._tick_len.value(),
                "xlabel_on": self._chk_xlabel.isChecked(), "ylabel_on": self._chk_ylabel.isChecked(),
                "xticks_on": self._chk_xticks.isChecked(), "yticks_on": self._chk_yticks.isChecked(),
                "xtickmarks_on": self._chk_xtickmarks.isChecked(),
                "ytickmarks_on": self._chk_ytickmarks.isChecked()}

    def config_dict(self):
        """`.pmcfg.json`에 쓰는 dict — 그림을 재현하는 전부(데이터 레시피·모드·라벨·축·주석)."""
        return {
            "_version": self._CFG_VERSION,
            # 이름 → 레시피(경로 + 숨김 규칙 + 데이터셋 시프트). 옛 형식(이름 → 경로)도 읽힌다.
            "datasets": {n: ds.to_spec() for n, ds in self.shelf.items()},
            "mode": self._mode.key,
            "resample": self._res_combo.currentText(),
            "resample_custom_min": self._res_custom_spin.value(),
            "smooth": self._smooth_spin.value(),
            "time_shift_h": self._shift_spin.value(),
            "labels": dict(self.custom),
            "label_style": self.label_style,
            "axes": self._axes_state(),
            "fig_size": [self._fig_w.value(), self._fig_h.value()], "dpi": self._dpi_spin.value(),
            "mode_cfg": {m.key: m.to_config() for m in self._modes},
            # 주석은 데이터 좌표에 묶인 '그 그림만의 것'이라 style 템플릿이 아니라
            # 여기(plot config)에 저장한다. 전엔 아예 저장되지 않아 불러오면 사라졌다.
            "annots": [self._annot_norm(a) for a in self._annots],
            "compose": self.composer.to_config(),     # 다중 패널 조판(M2)
        }

    def _set_axes_widgets(self, axc, block=False):
        """축 탭 위젯에 axes dict(설정 파일·조판 패널과 같은 형식)를 채운다.
        block=True면 신호를 막는다 — 조판이 패널마다 잠시 끼워 넣고 되돌릴 때 화면을 다시 안 그리게."""
        from PyQt6.QtCore import QSignalBlocker
        _bl = [QSignalBlocker(w) for w in self._axes_widgets()] if block else []
        self._ax_xmin.setText(str(axc.get("xmin", ""))); self._ax_xmax.setText(str(axc.get("xmax", "")))
        self._ax_ymin.setText(str(axc.get("ymin", ""))); self._ax_ymax.setText(str(axc.get("ymax", "")))
        self._ax_rmin.setText(str(axc.get("rmin", ""))); self._ax_rmax.setText(str(axc.get("rmax", "")))
        self._chk_logx.setChecked(bool(axc.get("logx", False)))
        self._chk_logy.setChecked(bool(axc.get("logy", False)))
        self._chk_grid.setChecked(bool(axc.get("grid", True)))
        self._chk_grid_minor.setChecked(bool(axc.get("grid_minor", False)))
        self._tick_x.setText(str(axc.get("tick_x", ""))); self._tick_y.setText(str(axc.get("tick_y", "")))
        self._tick_x_anchor.setText(str(axc.get("tick_x_anchor", "")))
        self._tick_size.setValue(int(axc.get("tick_size", 0)))
        self._tick_dir.setCurrentIndex(int(axc.get("tick_dir", 0)))
        self._tick_len.setValue(int(axc.get("tick_len", 0)))
        self._chk_xlabel.setChecked(bool(axc.get("xlabel_on", True)))
        self._chk_ylabel.setChecked(bool(axc.get("ylabel_on", True)))
        self._chk_xticks.setChecked(bool(axc.get("xticks_on", True)))
        self._chk_yticks.setChecked(bool(axc.get("yticks_on", True)))
        # 구버전 설정(눈금선 키 없음)은 당시 동작(숫자와 함께 on/off)을 따라감
        self._chk_xtickmarks.setChecked(bool(axc.get("xtickmarks_on", axc.get("xticks_on", True))))
        self._chk_ytickmarks.setChecked(bool(axc.get("ytickmarks_on", axc.get("yticks_on", True))))
        del _bl

    def _axes_widgets(self):
        return [self._ax_xmin, self._ax_xmax, self._ax_ymin, self._ax_ymax, self._ax_rmin,
                self._ax_rmax, self._chk_logx, self._chk_logy, self._chk_grid, self._chk_grid_minor,
                self._tick_x, self._tick_y, self._tick_x_anchor, self._tick_size, self._tick_dir,
                self._tick_len, self._chk_xlabel, self._chk_ylabel, self._chk_xticks,
                self._chk_yticks, self._chk_xtickmarks, self._chk_ytickmarks]

    def _load_cfg(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load plot config", "",
                                              "Plot config (*.json);;All (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Load config", f"Failed: {e}")
            return
        cfg = self._migrate_cfg(cfg)
        missing = []
        joins = []
        for name, spec in cfg.get("datasets", {}).items():
            if name in self.shelf:
                continue
            if isinstance(spec, dict) and spec.get("join"):
                joins.append((name, spec))     # 재료(파일 데이터셋)를 다 연 뒤에 만든다
                continue
            if isinstance(spec, dict) and spec.get("console"):
                # 콘솔 데이터셋은 값이 없다 — 코드를 자동 실행하지 않고 대기만(rerun은 사람이)
                self._console_pending[name] = spec
                missing.append(f"{name} (console — open Console and type rerun({name!r}))")
                continue
            p = spec if isinstance(spec, str) else (spec or {}).get("path")
            if not (p and os.path.isfile(p)):
                missing.append(name)
                continue
            try:
                ds = load_spec(spec)
                ds.name = name
                self.shelf[name] = ds
            except Exception:
                missing.append(name)
        for name, spec in joins:
            ds = make_join(name, spec["join"], self.shelf, rules=spec.get("rules"),
                           rules_on=spec.get("rules_on", True), derived=spec.get("derived"))
            self.shelf[name] = ds              # 재료가 없으면 ✗로 남는다(조용히 빠지지 않게)
            if ds.join_info.get("error"):
                missing.append(f"{name} ({ds.join_info['error']})")
        self._refresh_tree()
        self._notify_modes()
        self._res_custom_spin.setValue(float(cfg.get("resample_custom_min", 2.0)))
        self._res_combo.setCurrentText(cfg.get("resample", "Raw"))
        self._smooth_spin.setValue(int(cfg.get("smooth", 1)))
        self._shift_spin.setValue(float(cfg.get("time_shift_h", 0.0)))
        if "annots" in cfg:     # 없는 옛 설정은 현재 주석을 건드리지 않는다
            self._annots = [self._annot_norm(a) for a in (cfg.get("annots") or [])]
        lab = cfg.get("labels", {})
        self._ed_title.setText(lab.get("title", ""))
        self._ed_x.setText(lab.get("xlabel", ""))
        self._ed_y.setText(lab.get("ylabel", ""))
        self._ed_r.setText(lab.get("rlabel", ""))
        self.custom = {"title": lab.get("title", ""), "xlabel": lab.get("xlabel", ""),
                       "ylabel": lab.get("ylabel", ""), "rlabel": lab.get("rlabel", "")}
        if "label_style" in cfg:
            for k, v in cfg["label_style"].items():
                pos = v.get("pos")
                self.label_style[k] = {"pos": tuple(pos) if pos else None,
                                       "size": v.get("size"), "color": v.get("color")}
            self._sync_label_style_widgets()
        self._set_axes_widgets(cfg.get("axes", {}))
        fsz = cfg.get("fig_size")
        if isinstance(fsz, (list, tuple)) and len(fsz) == 2:
            self._chk_autosize.setChecked(False)   # 저장된 크기 유지(자동 덮어쓰기 끔)
            self._fig_w.setValue(float(fsz[0])); self._fig_h.setValue(float(fsz[1]))
        if cfg.get("dpi"):
            self._dpi_spin.setValue(int(cfg["dpi"]))
        for m in self._modes:
            m.from_config(cfg.get("mode_cfg", {}).get(m.key, {}))
        # 모드 선택 복원
        for i, m in enumerate(self._modes):
            if m.key == cfg.get("mode"):
                self._mode_combo.setCurrentIndex(i)
                break
        self._on_transform_changed()
        if "compose" in cfg:          # 없는 옛 설정은 지금 조판을 건드리지 않는다
            self.composer.from_config(cfg.get("compose"))
        if missing:
            self.set_status(f"Loaded · missing datasets: {', '.join(missing)}")
        else:
            self.set_status(f"Config loaded: {os.path.basename(path)}")
