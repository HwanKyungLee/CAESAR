# -*- coding: utf-8 -*-
"""Plot Maker — 호스트 위젯(PlotMakerWidget): 탭 UI(Data/Style/Axes/Legend/Export)·
데이터 선반·설정 저장/불러오기·Publish. 6개 모드(core._MODES)를 갈아끼우며 그린다.
"""
from __future__ import annotations

import os
import json
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

from .core import _MODES, _shade
from .data import Dataset, load_dataset
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
            self.host.set_status(f"'{self.key}' 라벨 위치 이동됨 — Reset positions로 되돌릴 수 있음")


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
    "빨강": "#E53935", "주황": "#FB8C00", "노랑": "#F9A825", "초록": "#43A047",
    "청록": "#00ACC1", "파랑": "#1E88E5", "남색": "#3949AB", "보라": "#8E24AA",
    "분홍": "#D81B60", "갈색": "#6D4C41", "회색": "#757575",
}
_PALETTE_AUTO = "자동(종별)"


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
    "기본":  {"font": 0,  "line": 2, "legend": 0,  "grid": True},
    "논문":  {"font": 11, "line": 1, "legend": 9,  "grid": True},
    "PPT":   {"font": 16, "line": 3, "legend": 15, "grid": True},
    "다크":  {"font": 13, "line": 2, "legend": 12, "grid": True},
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
            f.setFrameShadow(QFrame.Shadow.Sunken); f.setStyleSheet("color:#ddd;")
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
                ("➕ Add data", self._add_data, "결과 파일(.dat/.csv)을 선반에 추가"),
                ("📅 By date", self._add_data_by_date,
                 "일별 핏 버킷에서 기간·시리즈를 골라 자동 머지해 선반에 추가"),
                ("🔍 Preview", self._preview_publish, "출력(Publish) 그대로 미리보기"),
                ("🖼 Publish", self._export_publish, "고화질 PNG / 벡터 PDF·SVG 저장")):
            b = QPushButton(txt); b.setToolTip(tip); b.clicked.connect(fn)
            bar.addWidget(b)
        root.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        self._tabs = QTabWidget()
        self._tabs.setMinimumWidth(310)   # 270→310: 좁아서 버튼줄 잘리던 문제(2026-07-03) 여유폭 확보

        # ═══════════ Data 탭 ═══════════
        tab_data = QWidget(); dv = QVBoxLayout(tab_data)
        drow = QHBoxLayout()
        b_add2 = QPushButton("➕ Add"); b_add2.clicked.connect(self._add_data)
        b_date2 = QPushButton("📅 By date"); b_date2.setToolTip("일별 핏 버킷에서 기간 선택 → 자동 머지 추가")
        b_date2.clicked.connect(self._add_data_by_date)
        b_rm = QPushButton("🗑 Remove"); b_rm.setToolTip("선택 데이터셋 제거")
        b_rm.clicked.connect(self._remove_data)
        drow.addWidget(b_add2); drow.addWidget(b_date2); drow.addWidget(b_rm); dv.addLayout(drow)
        dv.addWidget(QLabel("Data shelf — 컬럼 선택 후 Style 탭에서 추가"))
        self._tree_search = QLineEdit()
        self._tree_search.setPlaceholderText("🔍 데이터셋·컬럼 검색")
        self._tree_search.setClearButtonEnabled(True)
        self._tree_search.textChanged.connect(self._filter_tree)
        dv.addWidget(self._tree_search)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self._tree.setToolTip("컬럼 더블클릭 = 바로 플롯(현재 모드에). 여러 개는 선택 후 Style 탭에서 추가.\n"
                              "파일을 이 창에 끌어놓아도 추가됨.")
        self._tree.itemDoubleClicked.connect(self._on_tree_double_click)
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
        self._res_custom_spin.setToolTip("Resample=Custom일 때 평균 낼 구간(분)")
        self._res_custom_spin.setEnabled(False)
        self._res_custom_spin.valueChanged.connect(self._on_transform_changed)
        trow.addWidget(self._res_custom_spin)
        trow.addWidget(QLabel("Smooth"))
        self._smooth_spin = QSpinBox(); self._smooth_spin.setRange(1, 999); self._smooth_spin.setValue(1)
        self._smooth_spin.setToolTip("rolling 평균 점 수(1=끔)")
        self._smooth_spin.valueChanged.connect(self._on_transform_changed)
        trow.addWidget(self._smooth_spin); dv.addLayout(trow)
        trow2 = QHBoxLayout()
        trow2.addWidget(QLabel("Time shift"))
        self._shift_spin = QDoubleSpinBox()
        self._shift_spin.setRange(-72.0, 72.0); self._shift_spin.setValue(0.0)
        self._shift_spin.setSuffix(" h"); self._shift_spin.setDecimals(2); self._shift_spin.setSingleStep(1.0)
        self._shift_spin.setToolTip("시간축 전체를 +/-시간만큼 이동해서 표시(원본 파일은 그대로, 화면만 보정).\n"
                                    "장비 시계 오차/타임존 불일치를 눈으로 맞춰볼 때 사용.")
        self._shift_spin.valueChanged.connect(self._on_transform_changed)
        trow2.addWidget(self._shift_spin); trow2.addStretch(1); dv.addLayout(trow2)
        self._tabs.addTab(_scroll(tab_data), "Data")

        # ═══════════ Style 탭 ═══════════
        tab_style = QWidget(); sv = QVBoxLayout(tab_style)
        prow = QHBoxLayout(); prow.addWidget(QLabel("Palette"))
        self._palette_combo = QComboBox()
        self._palette_combo.addItems([_PALETTE_AUTO] + list(_FAMILIES.keys()))
        self._palette_combo.setToolTip("색 계열 프리셋: 계통색을 고르면 그 계열 톤으로 자동 배색.\n"
                                       "시리즈 여러 개·diurnal 3곡선도 같은 계열 진↔연으로.\n"
                                       "'자동(종별)'=종 이름 기반 색(ANs 초록 등).")
        self._palette_combo.activated.connect(
            lambda *_: self._apply_palette(self._palette_combo.currentText()))
        prow.addWidget(self._palette_combo, 1); sv.addLayout(prow)
        thr = QHBoxLayout(); thr.addWidget(QLabel("Theme"))
        self._theme_combo = QComboBox(); self._theme_combo.addItems(list(_THEMES.keys()))
        self._theme_combo.setToolTip("룩 프리셋: 폰트·선두께·범례·그리드를 한 번에(색과 무관)")
        self._theme_combo.activated.connect(lambda *_: self._on_theme_combo_changed())
        thr.addWidget(self._theme_combo, 1); sv.addLayout(thr)
        crow = QHBoxLayout()
        self._btn_colors = QPushButton("🎨 Colors")
        self._btn_colors.setToolTip("현재 모드의 고정 색요소(Scatter/Allan/Histogram/Diurnal).\n"
                                    "Time series는 아래 시리즈별 🎨 Color 사용.")
        self._btn_colors.clicked.connect(self._edit_colors)
        self._btn_colors.setEnabled(bool(self._mode.color_keys()))
        self._btn_cursor = QPushButton("⌖ Cursor"); self._btn_cursor.setCheckable(True)
        self._btn_cursor.setToolTip("데이터 커서(크로스헤어): 마우스 위치 x·y 표시")
        self._btn_cursor.toggled.connect(self._toggle_cursor)
        b_annot = QPushButton("🏷 Annotate"); b_annot.setToolTip("마커선: 이벤트 세로선·LOD/임계 가로선")
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
        gb2.setToolTip("값을 해석 못하면 빨간 테두리로 표시됨(무시된 채 조용히 auto로 넘어가지 않음).")
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
        b_full = QPushButton("📅 전체(일단위)")
        b_full.setToolTip("선반의 전체 데이터 범위를 하루 경계(00:00)에 맞춰 X에 채움\n"
                          "— 박사님 그림 규약(x 양끝 tight)과 동일한 결과.")
        b_full.clicked.connect(self._preset_x_full)
        fl2.addRow("", b_full)
        rowXp = QHBoxLayout()
        b_recent = QPushButton("최근")
        self._preset_days = QSpinBox(); self._preset_days.setRange(1, 90); self._preset_days.setValue(7)
        self._preset_days.setSuffix("일")
        b_recent.setToolTip("데이터의 마지막 날로부터 N일 전(00:00)까지를 X에 채움.")
        b_recent.clicked.connect(lambda: self._preset_x_recent(self._preset_days.value()))
        rowXp.addWidget(b_recent); rowXp.addWidget(self._preset_days)
        b_clear = QPushButton("✕ 초기화")
        b_clear.setToolTip("X 범위를 비움(auto로 되돌림).")
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
        self._chk_grid_minor.setToolTip("pyqtgraph 화면은 세부눈금 자동표시만 지원 — 별도\n"
                                        "on/off 불가. Publish(matplotlib)에만 적용됩니다.")
        self._chk_grid.toggled.connect(self._on_axes_changed)
        self._chk_grid_minor.toggled.connect(self._on_axes_changed)
        grow.addWidget(self._chk_grid); grow.addWidget(self._chk_grid_minor); grow.addStretch(1)
        flg.addRow("Grid", grow)
        self._tick_x = QLineEdit(); self._tick_x.setPlaceholderText("auto (시간축=일수, 예: 1)")
        self._tick_y = QLineEdit(); self._tick_y.setPlaceholderText("auto (예: 0.5)")
        self._tick_x.setToolTip("X 눈금 간격. 시간축이면 '일' 단위(1=매일 00:00 눈금). 빈칸=자동.\n"
                                "정확한 간격은 Publish/Preview에서 확인하세요(화면은 근사치).")
        self._tick_y.setToolTip("Y 눈금 간격(값 단위). 빈칸=자동.\n"
                                "정확한 간격은 Publish/Preview에서 확인하세요(화면은 근사치).")
        self._tick_x.editingFinished.connect(self._on_axes_changed)
        self._tick_y.editingFinished.connect(self._on_axes_changed)
        trow_x = QHBoxLayout()
        trow_x.addWidget(self._tick_x, 1)
        self._tick_x_anchor = QLineEdit()
        self._tick_x_anchor.setPlaceholderText("앵커 (예: 06-29)")
        self._tick_x_anchor.setToolTip("시간축 눈금의 기준 날짜 — 여기 적은 날짜부터 좌측 간격(일)씩 눈금.\n"
                                       "예: 앵커 06-29 + 간격 7 → 06-29, 07-06, 07-13… (앞쪽으로도 06-22, 06-15…)\n"
                                       "빈칸 = 자동 배치(달력 기준). 화면·Publish 동일 적용.")
        self._tick_x_anchor.editingFinished.connect(self._on_axes_changed)
        trow_x.addWidget(self._tick_x_anchor, 1)
        flg.addRow("X tick", trow_x)
        flg.addRow("Y tick", self._tick_y)
        srow = QHBoxLayout()
        self._tick_dir = QComboBox(); self._tick_dir.addItems(["바깥(out)", "안(in)"])
        self._tick_dir.setToolTip("눈금선 방향 — 그래프 바깥쪽 또는 안쪽. 화면·Publish 동일 적용.")
        self._tick_dir.currentIndexChanged.connect(self._on_axes_changed)
        srow.addWidget(self._tick_dir)
        srow.addWidget(QLabel("길이"))
        self._tick_len = QSpinBox()
        self._tick_len.setRange(0, 20); self._tick_len.setValue(0)
        self._tick_len.setSpecialValueText("auto"); self._tick_len.setSuffix(" px")
        self._tick_len.setToolTip("눈금선 길이(0=auto≈5px). 화면·Publish 동일 적용.")
        self._tick_len.valueChanged.connect(self._on_axes_changed)
        srow.addWidget(self._tick_len); srow.addStretch(1)
        flg.addRow("Tick 선", srow)
        av.addWidget(gbg)
        # 축 라벨·눈금 표시 토글 (끄면 아예 안 그림)
        gbsh = QGroupBox("Show (끄면 숨김)")
        flsh = QFormLayout(gbsh)
        self._chk_xlabel = QCheckBox("label"); self._chk_xticks = QCheckBox("숫자")
        self._chk_ylabel = QCheckBox("label"); self._chk_yticks = QCheckBox("숫자")
        self._chk_xtickmarks = QCheckBox("눈금선"); self._chk_ytickmarks = QCheckBox("눈금선")
        for c in (self._chk_xlabel, self._chk_xticks, self._chk_ylabel, self._chk_yticks,
                  self._chk_xtickmarks, self._chk_ytickmarks):
            c.setChecked(True); c.toggled.connect(self._on_axes_changed)
        self._chk_xlabel.setToolTip("X축 이름(예: Time) 표시")
        self._chk_xticks.setToolTip("X축 눈금 숫자/날짜(텍스트) 표시")
        self._chk_xtickmarks.setToolTip("X축 눈금선(짧은 금) 표시 — 숫자를 꺼도 눈금선만 남길 수 있음")
        self._chk_ytickmarks.setToolTip("Y축 눈금선(짧은 금) 표시 — 숫자를 꺼도 눈금선만 남길 수 있음")
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
        self._legend_combo.setToolTip("범례 위치 (auto=데이터 안 가리게 자동 · TL/TR/BL/BR · off=숨김)")
        self._legend_combo.currentIndexChanged.connect(self._on_legend_changed)
        fll.addRow("Position", self._legend_combo)
        self._legend_size = QSpinBox()
        self._legend_size.setRange(0, 40); self._legend_size.setValue(0)
        self._legend_size.setSpecialValueText("auto"); self._legend_size.setSuffix(" pt")
        self._legend_size.setToolTip("범례 글자 크기 (0=auto). Publish에 적용.")
        self._legend_size.valueChanged.connect(self._on_legend_changed)
        fll.addRow("Size", self._legend_size)
        gv.addWidget(gbl)
        gb = QGroupBox("Labels (override, blank=auto)")
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
        self._lbl_size.setToolTip("전역 기본 글자 크기(0=auto). 각 라벨 옆 Size가 0이면 이 값을 씀.")
        self._lbl_size.valueChanged.connect(self._on_labels_changed)
        fl.addRow("Font size (default)", self._lbl_size)
        self._tick_size = QSpinBox()
        self._tick_size.setRange(0, 40); self._tick_size.setValue(0)
        self._tick_size.setSpecialValueText("auto"); self._tick_size.setSuffix(" pt")
        self._tick_size.setToolTip("눈금 숫자/날짜 글자 크기 (0=auto: 전역 Font size−2).\n"
                                   "화면 미리보기·Publish 모두 적용.")
        self._tick_size.valueChanged.connect(self._on_labels_changed)
        fl.addRow("Tick size", self._tick_size)
        btn_reset_pos = QPushButton("↺ Reset positions")
        btn_reset_pos.setToolTip("드래그로 옮긴 라벨 위치를 전부 기본 자리로 되돌림(크기/색은 유지)")
        btn_reset_pos.clicked.connect(self.reset_label_positions)
        fl.addRow("", btn_reset_pos)
        gv.addWidget(gb)
        gv.addStretch(1)
        self._tabs.addTab(_scroll(tab_leg), "Legend")

        # ═══════════ Export 탭 ═══════════
        tab_exp = QWidget(); xv = QVBoxLayout(tab_exp)
        gbs = QGroupBox("Publish size")
        fls = QFormLayout(gbs)
        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(72, 1200); self._dpi_spin.setValue(300); self._dpi_spin.setSingleStep(50)
        self._dpi_spin.setToolTip("Publish PNG 해상도(벡터 PDF/SVG는 무관). PPT=150~200, 논문=300~600")
        fls.addRow("DPI (PNG)", self._dpi_spin)
        szr = QHBoxLayout()
        self._fig_w = QDoubleSpinBox(); self._fig_w.setRange(2.0, 40.0); self._fig_w.setValue(10.0)
        self._fig_w.setSingleStep(0.5); self._fig_w.setDecimals(1); self._fig_w.setToolTip("가로(인치)")
        self._fig_h = QDoubleSpinBox(); self._fig_h.setRange(1.5, 40.0); self._fig_h.setValue(5.5)
        self._fig_h.setSingleStep(0.5); self._fig_h.setDecimals(1); self._fig_h.setToolTip("세로(인치)")
        szr.addWidget(QLabel("W")); szr.addWidget(self._fig_w)
        szr.addWidget(QLabel("H")); szr.addWidget(self._fig_h)
        fls.addRow("Size (in)", szr)
        self._chk_autosize = QCheckBox("모드별 권장 크기 자동")
        self._chk_autosize.setChecked(True)
        self._chk_autosize.setToolTip("모드 바꿀 때 그래프 종류에 맞는 권장 W×H로 자동 설정\n"
                                      "(시계열=와이드, diurnal=정사각 등). 끄면 수동 유지.")
        b_fit = QPushButton("📐 지금 권장크기 적용")
        b_fit.setToolTip("현재 모드의 권장 크기를 바로 적용")
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

        _btn_group("이미지 내보내기", [
            ("🖼 Publish (PNG/PDF/SVG)", self._export_publish, "matplotlib 고화질 출력"),
            ("📦 Batch Publish (종별 일괄)", self._batch_publish,
             "Time series/Diurnal 시리즈 목록의 각 컬럼을 종별 PNG로 한 번에 저장\n"
             "— 매주 종마다 반복 Publish하던 걸 자동화. 목록은 Style 탭 TimeSeries 것을 씀."),
            ("📷 Quick PNG (화면 그대로)", self._export_png, "pyqtgraph 2400px 빠른 캡처"),
            ("📋 Copy to clipboard (Ctrl+C)", self._copy_to_clipboard,
             "파일 저장 없이 바로 복사 → PPT/문서에 Ctrl+V"),
        ])
        _btn_group("데이터 내보내기", [
            ("📑 Export CSV", self._export_csv, "현재 모드 데이터 CSV"),
        ])
        _btn_group("설정 저장·불러오기", [
            ("💾 Save config", self._save_cfg, "플롯 전체 저장(데이터+축+라벨+색) — MATLAB .fig 역할"),
            ("📂 Load config", self._load_cfg, "저장한 플롯 설정 불러오기"),
            ("💅 Save style", self._save_template, "룩만(색·폰트·범례·야간음영) 템플릿 저장"),
            ("💅 Load style", self._load_template, "저장한 룩을 현재 플롯에 적용"),
        ])
        xv.addStretch(1)
        self._tabs.addTab(_scroll(tab_exp), "Export")

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
        self._status.setStyleSheet("color:#444;")
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

    def _draw_annotations_pg(self):
        """주석 마커선(세로=이벤트, 가로=LOD/임계)을 p1에 그림. clear_plot마다 재추가."""
        for a in getattr(self, "_annots", []):
            col = a.get("color") or "#555"
            vert = a["kind"] == "vline"
            ln = pg.InfiniteLine(
                a["val"], angle=90 if vert else 0, movable=False,
                pen=pg.mkPen(col, width=1, style=Qt.PenStyle.DashLine),
                label=a.get("label") or "",
                labelOpts={"position": 0.92 if vert else 0.08, "color": col,
                           "fill": (255, 255, 255, 160)})
            ln.setZValue(150)
            self.p1.addItem(ln, ignoreBounds=True)

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
                                     QComboBox, QLineEdit, QPushButton, QLabel,
                                     QColorDialog)
        from PyQt6.QtGui import QColor
        dlg = QDialog(self)
        dlg.setModal(False)
        dlg.setWindowTitle("🏷 Annotations (marker lines)")
        dlg.resize(460, 340)
        v = QVBoxLayout(dlg)
        lst = QListWidget()

        def refresh():
            lst.clear()
            for a in self._annots:
                tag = "│ x=" if a["kind"] == "vline" else "─ y="
                if a["kind"] == "vline" and self._time_axis:
                    import datetime as _dt
                    try:
                        vs = _dt.datetime.fromtimestamp(a["val"]).strftime("%m-%d %H:%M")
                    except Exception:
                        vs = f"{a['val']:.6g}"
                else:
                    vs = f"{a['val']:.6g}"
                lst.addItem(f"{tag}{vs}   {a.get('label', '')}")
        refresh()
        self._annot_dlg_refresh = refresh   # _on_plot_clicked가 클릭 추가 후 여기 갱신
        v.addWidget(QLabel("현재 마커선 (선택 후 Remove)"))
        v.addWidget(lst, 1)

        row = QHBoxLayout()
        cb = QComboBox(); cb.addItems(["Vertical (x)", "Horizontal (y)"])
        ed_lab = QLineEdit(); ed_lab.setPlaceholderText("라벨(선택)")
        cstate = {"c": "#d32f2f"}
        b_col = QPushButton("🎨"); b_col.setFixedWidth(34)
        b_col.setStyleSheet(f"background:{cstate['c']};color:white;")

        def pick_col():
            c = QColorDialog.getColor(QColor(cstate["c"]), dlg)
            if c.isValid():
                cstate["c"] = c.name()
                b_col.setStyleSheet(f"background:{c.name()};color:white;")
        b_col.clicked.connect(pick_col)
        b_pick = QPushButton("🖱 그래프에서 클릭해 찍기")
        b_pick.setToolTip("누르고 그래프의 원하는 위치를 클릭하면 그 자리에 마커가 생김.\n"
                          "우클릭하면 취소.")

        def start_pick():
            kind = "vline" if cb.currentIndex() == 0 else "hline"
            self._annot_pick = {"kind": kind, "label": ed_lab.text().strip(),
                                "color": cstate["c"]}
            axis = "세로선(x)" if kind == "vline" else "가로선(y)"
            self.set_status(f"🖱 그래프를 클릭하면 {axis} 마커 추가 — 우클릭=취소")
        b_pick.clicked.connect(start_pick)
        row.addWidget(cb); row.addWidget(ed_lab, 1); row.addWidget(b_col); row.addWidget(b_pick)
        v.addLayout(row)

        row1b = QHBoxLayout()
        ed_val = QLineEdit(); ed_val.setPlaceholderText("직접 값 입력(선택) — 숫자, 시간축 세로선은 'MM-DD HH:MM'")
        b_add = QPushButton("+ Add (typed value)")

        def add():
            kind = "vline" if cb.currentIndex() == 0 else "hline"
            if kind == "vline":
                val = self._parse_annot_x(ed_val.text())
            else:
                try:
                    val = float(ed_val.text().strip())
                except ValueError:
                    val = None
            if val is None:
                self.set_status("주석 값 파싱 실패 — 숫자(시간축 세로선은 날짜시각) 또는 위의 🖱 클릭 찍기 사용.")
                return
            self._annots.append({"kind": kind, "val": val,
                                 "label": ed_lab.text().strip(), "color": cstate["c"]})
            ed_val.clear(); refresh(); self._mode.render()
        b_add.clicked.connect(add)
        row1b.addWidget(ed_val, 1); row1b.addWidget(b_add)
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
            self.set_status(f"⚠ 이 스타일은 더 새 버전(v{v})에서 저장됨 — 일부가 무시될 수 있음.")
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
            self.set_status(f"⚠ 이 설정은 더 새 버전(v{v})에서 저장됨 — 일부 기능이 무시될 수 있음.")
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
            QMessageBox.warning(self, "Style", f"저장 실패:\n{e}")

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
            QMessageBox.warning(self, "Style", f"불러오기 실패:\n{e}")
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
        self.set_status("⌖  " + text.replace("\n", "    "))
        gp = self.pw.viewport().mapToGlobal(self.pw.mapFromScene(pos))
        QToolTip.showText(gp, text, self.pw)

    def _on_plot_clicked(self, ev):
        """🖱 Pick 모드일 때만 반응 — 클릭 위치를 그대로 마커 값으로 채택.
        우클릭=취소. 값 입력칸 대신 그래프에서 직접 찍는 방식(_edit_annotations 참고)."""
        if self._annot_pick is None:
            return
        if ev.button() == Qt.MouseButton.RightButton:
            self._annot_pick = None
            self.set_status("마커 추가 취소됨")
            return
        if not self.p1.sceneBoundingRect().contains(ev.scenePos()):
            return
        mp = self.p1.vb.mapSceneToView(ev.scenePos())
        kind = self._annot_pick["kind"]
        val = float(mp.x() if kind == "vline" else mp.y())
        self._annots.append({"kind": kind, "val": val,
                             "label": self._annot_pick.get("label", ""),
                             "color": self._annot_pick.get("color", "#d32f2f")})
        self._annot_pick = None
        self._mode.render()
        if self._time_axis and kind == "vline":
            import datetime as _dt
            try:
                vs = _dt.datetime.fromtimestamp(val).strftime("%m-%d %H:%M")
            except Exception:
                vs = f"{val:.6g}"
        else:
            vs = f"{val:.6g}"
        self.set_status(f"마커 추가됨: {vs}")
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
        if st.get("pos") is None:
            if key == "title":
                self.p1.setTitle(text, size=f"{size}pt", **({"color": color} if color else {}))
            else:
                ax = self.p1.getAxis(self._AXIS_OF_KEY[key])
                style = {"font-size": f"{size}pt"}
                if color:
                    style["color"] = color
                ax.setLabel(text, **style)
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
        self.set_status("라벨 위치 전부 기본값으로 리셋")

    def _edit_colors(self):
        """현재 모드의 color_keys() 요소들 색을 지정하는 다이얼로그(라이브 적용)."""
        keys = self._mode.color_keys()
        if not keys:
            self.set_status("이 모드는 색 지정 요소가 없습니다 "
                            "(Time series는 옵션 패널의 🎨 Color 사용).")
            return
        from PyQt6.QtWidgets import (QDialog, QFormLayout, QDialogButtonBox,
                                     QColorDialog)
        from PyQt6.QtGui import QColor
        dlg = QDialog(self)
        dlg.setWindowTitle(f"🎨 Colors — {self._mode.label}")
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
        edit.setStyleSheet("border: 1px solid #d32f2f;" if invalid else "")

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
            self.set_status(f"'{self._mode.label}' 모드는 X축이 시간이 아니라 날짜 프리셋을 쓸 수 없습니다.")
            return False
        return True

    def _preset_x_full(self):
        """전체 데이터 범위를 하루 경계(00:00)에 맞춰 X에 채움 — 박사님 그림
        규약(x 양끝 tight, 매일 00:00 눈금)과 동일한 결과를 매주 손타이핑 없이."""
        if not self._preset_x_time_guard():
            return
        lo, hi = self._data_time_range()
        if lo is None:
            self.set_status("시간축 있는 데이터가 없습니다 — 먼저 데이터를 추가하세요.")
            return
        import datetime as _dt
        d0 = _dt.datetime.fromtimestamp(lo).replace(hour=0, minute=0, second=0, microsecond=0)
        d1 = (_dt.datetime.fromtimestamp(hi).replace(hour=0, minute=0, second=0, microsecond=0)
              + _dt.timedelta(days=1))
        self._set_x_range_text(d0, d1)
        self.set_status(f"X 범위: {d0:%Y-%m-%d} ~ {d1:%Y-%m-%d} (전체, 일단위)")

    def _preset_x_recent(self, days):
        """데이터 마지막 날 기준 최근 N일(00:00 경계)을 X에 채움."""
        if not self._preset_x_time_guard():
            return
        lo, hi = self._data_time_range()
        if hi is None:
            self.set_status("시간축 있는 데이터가 없습니다 — 먼저 데이터를 추가하세요.")
            return
        import datetime as _dt
        d1 = (_dt.datetime.fromtimestamp(hi).replace(hour=0, minute=0, second=0, microsecond=0)
              + _dt.timedelta(days=1))
        d0 = d1 - _dt.timedelta(days=days)
        self._set_x_range_text(d0, d1)
        self.set_status(f"X 범위: 최근 {days}일 ({d0:%Y-%m-%d} ~ {d1:%Y-%m-%d})")

    def _preset_x_clear(self):
        self._ax_xmin.setText(""); self._ax_xmax.setText("")
        self._on_axes_changed()
        self.set_status("X 범위 초기화(auto)")

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
                self.set_status(f"⚠ Y tick spacing 적용 실패(화면만, Publish는 정상): {e}")
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
                self.set_status(f"⚠ X tick spacing 적용 실패(화면만, Publish는 정상): {e}")
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

    def _apply_axes_mpl(self, fig):
        """Publish(matplotlib)에도 동일한 축 범위/로그 적용."""
        axes = fig.axes
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
        for an in getattr(self, "_annots", []):
            col = an.get("color") or "#555"
            lbl = an.get("label") or None
            for ai, a in enumerate(axes):
                show_label = (ai == 0) and lbl   # 라벨은 첫 패널에만(중복 방지)
                if an["kind"] == "vline":
                    xv = (_dt.datetime.fromtimestamp(an["val"]) if self._time_axis
                          else an["val"])
                    a.axvline(xv, color=col, ls="--", lw=1)
                    if show_label:
                        ylo, yhi = a.get_ylim()
                        a.text(xv, yhi, f" {lbl}", color=col, fontsize=8,
                              va="top", ha="left", clip_on=True,   # 범위 밖 라벨은 선처럼 안 보이게
                              bbox=dict(facecolor="white", edgecolor="none", alpha=0.7, pad=1))
                else:
                    a.axhline(an["val"], color=col, ls="--", lw=1)
                    if show_label:
                        xlo, xhi = a.get_xlim()
                        a.text(xlo, an["val"], f"{lbl} ", color=col, fontsize=8,
                              va="bottom", ha="left", clip_on=True,
                              bbox=dict(facecolor="white", edgecolor="none", alpha=0.7, pad=1))
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
        t는 time_shift_hours가 있으면 표시용으로만 이동(ds.time 원본은 불변)."""
        if not label or ":" not in label:
            return None
        name, col = label.split(":", 1)
        ds = self.shelf.get(name)
        if ds is None or col not in ds.cols:
            return None
        t = ds.time
        if t is not None and self.time_shift_hours:
            t = t + self.time_shift_hours * 3600.0
        return ds, col, ds.cols[col], t

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
        """📅 일별 핏 버킷에서 기간·시리즈 선택 → 자동 머지 파일을 선반에 추가."""
        from gui.dlg_date_load import DateLoadDialog
        dlg = DateLoadDialog(self)
        if dlg.exec() and dlg.loaded_paths:
            self.add_paths(dlg.loaded_paths)

    def add_paths(self, paths):
        """파일 경로 목록을 선반에 로드(결과뷰어의 'Send to Plot Maker' 등에서 호출)."""
        added = 0
        for p in paths:
            try:
                ds = load_dataset(p)
            except Exception as e:
                QMessageBox.warning(self, "Load failed", f"{os.path.basename(p)}: {e}")
                continue
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
            self.set_status(f"Added {added} dataset(s) · {len(self.shelf)} on shelf")
        return added

    def _on_tree_double_click(self, item, _col=0):
        """Data 탭에서 컬럼 더블클릭 → 현재 모드로 바로 플롯. 데이터셋 헤더는 무시(펼침)."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not (isinstance(data, tuple) and data[0] == "col"):
            return
        label = f"{data[1]}:{data[2]}"
        if self._mode.on_column_activated(label):
            self.set_status(f"플롯: {label} ({self._mode.label})")

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
            self.set_status(f"데이터셋 {len(names)}개 제거됨 — Ctrl+Z로 복원")
            self._refresh_tree()
            self._notify_modes()

    def _refresh_tree(self):
        self._tree.clear()
        for name, ds in self.shelf.items():
            top = QTreeWidgetItem([f"{name}  ({len(ds)}×{len(ds.cols)})"])
            top.setData(0, Qt.ItemDataRole.UserRole, ("ds", name))
            tip = "time axis ✓" if ds.time is not None else "no time axis"
            top.setToolTip(0, f"{ds.path}\n{tip}")
            for col in ds.cols:
                ch = QTreeWidgetItem([col])
                ch.setData(0, Qt.ItemDataRole.UserRole, ("col", name, col))
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
            self.set_status("되돌릴 작업이 없습니다.")
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
            self.set_status(f"↩ 데이터셋 {restored}개 복원됨")
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
                self.set_status(f"↩ 시리즈 {len(payload)}개 복원됨")

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
            self.set_status(f"권장 크기 적용: {wh[0]}×{wh[1]} in ({self._mode.label})")

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
            self.set_status("색: 자동(종별)로 복귀")
            self._mode.render()
            return
        base = _FAMILIES.get(family)
        if not base:
            return
        if mode.key == "timeseries":
            n = len(mode._series)
            shades = _family_shades(base, max(n, 1))
            for i, s in enumerate(mode._series):
                s[2] = shades[i]
            if hasattr(mode, "_refresh_list"):
                mode._refresh_list()
        else:
            keys = mode.color_keys()
            if keys:
                shades = _family_shades(base, len(keys))
                for (key, _lab, _def), c in zip(keys, shades):
                    mode.colors[key] = c
        self.set_status(f"색 계열 적용: {family}")
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
        self.set_status(f"테마 적용: {name}")
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
        sp.setToolTip("이 라벨만 글자 크기(0=전역 Font size 사용)")
        sp.valueChanged.connect(lambda v, k=key: self._on_label_style_changed(k))
        row.addWidget(sp)
        btn = QPushButton("🎨"); btn.setFixedWidth(26)
        btn.setToolTip("이 라벨 글자색 지정(왼쪽 클릭=고르기)")
        btn.clicked.connect(lambda _, k=key, b=btn: self._pick_label_color(k, b))
        row.addWidget(btn)
        btn_rst = QPushButton("↺"); btn_rst.setFixedWidth(22)
        btn_rst.setToolTip("이 라벨의 크기·색을 자동으로 되돌림")
        btn_rst.clicked.connect(lambda _, k=key: self._reset_label_style(k))
        row.addWidget(btn_rst)
        chk = QCheckBox("📍")
        chk.setToolTip("체크하면 그래프 안쪽·바깥 여백 어디든 마우스로 드래그해 놓을 수 있음.\n"
                      "위치는 화면 비율로 저장되어 화면·Publish가 항상 같은 자리에 그림.")
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
        """label_style(설정 불러오기 등으로 바뀜) → Size/색/📍 위젯 표시 동기화."""
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
    def _apply_korean_font(matplotlib):
        """한글 라벨이 □□로 깨지지 않게 한글 지원 폰트를 1회 설정(있으면)."""
        if getattr(PlotMakerWidget, "_kfont_done", False):
            return
        PlotMakerWidget._kfont_done = True
        try:
            from matplotlib import font_manager as fm
            avail = {f.name for f in fm.fontManager.ttflist}
            for cand in ("Malgun Gothic", "NanumGothic", "AppleGothic",
                         "Noto Sans CJK KR", "Noto Sans KR", "Gulim", "Batang"):
                if cand in avail:
                    matplotlib.rcParams["font.family"] = cand
                    break
            matplotlib.rcParams["axes.unicode_minus"] = False   # 음수 기호 깨짐 방지
        except Exception:
            pass

    def _build_publish_fig(self):
        """Publish용 matplotlib Figure 생성 — 미리보기·저장 공용(완전 동일 경로).
        실패 시 None(메시지 표시). NotImplementedError는 호출측에서 처리."""
        try:
            import matplotlib
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
        except Exception as e:
            QMessageBox.warning(self, "Publish", f"matplotlib 사용 불가: {e}")
            return None
        self._apply_korean_font(matplotlib)
        fig = Figure(figsize=(self._fig_w.value(), self._fig_h.value()))
        FigureCanvasAgg(fig)              # savefig용 캔버스 부착(백엔드 무관)
        self._mode.render_mpl(fig)
        self._apply_axes_mpl(fig)
        if self.time_shift_hours:
            fig.text(0.995, 0.005, f"⚠ time shift {self.time_shift_hours:+g}h applied (display only)",
                     ha="right", va="bottom", fontsize=7, color="#b00")
        fig.tight_layout()
        return fig

    def _preview_publish(self):
        """Publish 결과를 그대로 다이얼로그에 띄워 미리보기(저장 안 함).
        범례·폰트·마커·축범위 등 모든 커스텀이 출력과 동일하게 보인다."""
        try:
            fig = self._build_publish_fig()
            if fig is None:
                return
            import io
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")  # 화면용 해상도
            buf.seek(0)
        except NotImplementedError:
            QMessageBox.information(self, "Preview",
                                   "이 모드는 아직 고화질 출력을 지원하지 않습니다.")
            return
        except Exception as e:
            QMessageBox.warning(self, "Preview", f"Failed: {e}")
            return
        from PyQt6.QtGui import QPixmap
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QScrollArea
        pix = QPixmap()
        pix.loadFromData(buf.getvalue(), "PNG")
        dlg = QDialog(self)
        dlg.setWindowTitle("Publish preview — 출력 그대로 (저장은 🖼 Publish)")
        lay = QVBoxLayout(dlg)
        sa = QScrollArea(); sa.setWidgetResizable(True)
        lbl = QLabel(); lbl.setPixmap(pix)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sa.setWidget(lbl)
        lay.addWidget(sa)
        dlg.resize(min(pix.width() + 40, 1280), min(pix.height() + 60, 820))
        dlg.exec()

    def _export_publish(self):
        """현재 모드를 matplotlib로 재렌더 → 고화질 PNG / 벡터 PDF·SVG."""
        out, _ = QFileDialog.getSaveFileName(
            self, "Publish (high quality)", self._default_export_name() + ".png",
            "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if not out:
            return
        if not os.path.splitext(out)[1]:
            out += ".png"
        try:
            fig = self._build_publish_fig()
            if fig is None:
                return
            fig.savefig(out, dpi=self._dpi_spin.value(), bbox_inches="tight")
            ext = os.path.splitext(out)[1].lstrip(".").upper()
            extra = f" @ {self._dpi_spin.value()}dpi" if ext == "PNG" else " (vector)"
            self.set_status(f"Published: {os.path.basename(out)} [{ext}{extra}]")
        except NotImplementedError:
            QMessageBox.information(self, "Publish",
                                   "이 모드는 아직 고화질 출력을 지원하지 않습니다.")
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
                "Style 탭에서 Time series에 시리즈를 먼저 추가하세요 — 그 목록이 배치 대상입니다.")
            return
        if self._mode.key not in ("timeseries", "diurnal"):
            QMessageBox.information(self, "Batch Publish",
                "Batch Publish는 Time series·Diurnal 모드에서만 지원합니다(Data 탭에서 모드 전환).")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Batch Publish — 저장 폴더 선택")
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
                            failed.append(f"{lab}: figure 생성 실패"); continue
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
                        failed.append(f"{lab}: diurnal 콤보에 없음(시간축 없는 컬럼?)")
                        continue
                    try:
                        fig = self._build_publish_fig()
                        if fig is None:
                            failed.append(f"{lab}: figure 생성 실패"); continue
                        col = lab.split(":", 1)[-1]
                        path = os.path.join(out_dir, f"diurnal_{col}.png")
                        fig.savefig(path, dpi=dpi, bbox_inches="tight")
                        saved.append(os.path.basename(path))
                    except Exception as e:
                        failed.append(f"{lab}: {e}")
            finally:
                dm._c.setCurrentIndex(orig_index)   # -1(선택없음)도 그대로 복원됨
                dm.render()

        msg = f"{len(saved)}개 저장됨: {', '.join(saved)}" if saved else "저장된 파일 없음"
        if failed:
            msg += f"\n실패/건너뜀 {len(failed)}개: {'; '.join(failed)}"
        self.set_status(f"Batch Publish: {len(saved)}개 저장" + (f", {len(failed)}개 실패" if failed else ""))
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
            self.set_status("클립보드에 복사됨 (Ctrl+V로 붙여넣기)")
        except Exception as e:
            QMessageBox.warning(self, "Copy", f"Failed: {e}")

    def _export_csv(self):
        """현재 모드가 제공하는 데이터(csv_table)를 CSV로 저장."""
        table = self._mode.csv_table()
        if not table:
            QMessageBox.information(self, "CSV",
                                   "현재 모드/선택에 내보낼 데이터가 없습니다.")
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
        cfg = {
            "_version": self._CFG_VERSION,
            "datasets": {n: ds.path for n, ds in self.shelf.items()},
            "mode": self._mode.key,
            "resample": self._res_combo.currentText(),
            "resample_custom_min": self._res_custom_spin.value(),
            "smooth": self._smooth_spin.value(),
            "time_shift_h": self._shift_spin.value(),
            "labels": dict(self.custom),
            "label_style": self.label_style,
            "axes": {"xmin": self._ax_xmin.text(), "xmax": self._ax_xmax.text(),
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
                     "ytickmarks_on": self._chk_ytickmarks.isChecked()},
            "fig_size": [self._fig_w.value(), self._fig_h.value()], "dpi": self._dpi_spin.value(),
            "mode_cfg": {m.key: m.to_config() for m in self._modes},
        }
        try:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            self.set_status(f"Config saved: {os.path.basename(out)}")
        except Exception as e:
            QMessageBox.warning(self, "Save config", f"Failed: {e}")

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
        for name, p in cfg.get("datasets", {}).items():
            if name in self.shelf:
                continue
            if not (p and os.path.isfile(p)):
                missing.append(name)
                continue
            try:
                ds = load_dataset(p)
                ds.name = name
                self.shelf[name] = ds
            except Exception:
                missing.append(name)
        self._refresh_tree()
        self._notify_modes()
        self._res_custom_spin.setValue(float(cfg.get("resample_custom_min", 2.0)))
        self._res_combo.setCurrentText(cfg.get("resample", "Raw"))
        self._smooth_spin.setValue(int(cfg.get("smooth", 1)))
        self._shift_spin.setValue(float(cfg.get("time_shift_h", 0.0)))
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
        axc = cfg.get("axes", {})
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
        if missing:
            self.set_status(f"Loaded · missing datasets: {', '.join(missing)}")
        else:
            self.set_status(f"Config loaded: {os.path.basename(path)}")
