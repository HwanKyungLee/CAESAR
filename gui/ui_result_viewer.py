"""결과 랩 (Result Lab — UI 탭 라벨; 내부 클래스명은 ResultViewerWidget 유지)
===========================
파이프라인이 저장한 결과 파일을 GUI에 다시 넣어 점검·QC·가공·유도·내보내기까지
하는 탭. "파일 하나(또는 몇 개) 빠르게 보고 손보기"가 주 목적.

── Plot Maker와의 경계 (새 기능 어디 둘지 한 줄 기준) ───────────────────
  · CAESAR 결과의 '의미'가 필요한 작업이면 → 여기(Result Lab).
    예) 가스 선택·RMS 기반 사후 QC·채널 차분(NO2/PNs/ANs)·Status·형제 α 팝업·
        구간 슬라이스/Merge/Export. 단일~소수 결과 파일 대상.
  · 소스 무관한 컬럼 vs 컬럼 자유조합으로 '그림 만들기'면 → Plot Maker.
    예) 산점도+회귀·Allan·Diurnal·Heatmap·Histogram, 여러 소스 합성.
  (이 규칙대로면 현 분할이 이미 맞음 — 옮길 코드 없음. 명문화가 목적.)

지원(헤더/컬럼으로 자동 판별, 수동 선택도 가능):
  · R 트렌드   : Cold_*.dat / Hot_*.dat  (timestamp, R_mean, Leff, …) → R/Leff 시계열
  · R(λ) 곡선  : *_R.dat (wavelength_nm, R_raw, R_fitted, omr_d, Leff_km) → R(λ) + Leff(λ)
  · α 스펙트럼 : optical_depth 배열(헤더 없는 숫자) → α vs 픽셀/파장
  · 레퍼런스   : *.csv (Wavelength, Reflectivity …) → 스펙트럼
  · 농도 피팅  : *.csv (시간 + 가스 농도 컬럼) → 농도 시계열
"""
from __future__ import annotations

import os
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from gui.result_viewer_io import (load_result_time_gas, detect,
                                  detect_sep, load_fit_table,
                                  flag_of, qc_hidden_mask, flag_color, FLAG_KEYS)

# 레인 선(26만 점급)은 화면에서 솎아 그린다(규칙·근거: gui/pg_perf.py). 클릭용 점(ScatterPlotItem)은
# 그대로 전부, Export/Stats는 원본 그대로.
from gui.pg_perf import make_fast as _fast, BIG as _BIG, add_fast_curve
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QComboBox, QSplitter, QListWidget, QListWidgetItem,
    QCheckBox, QMessageBox, QDialog, QPlainTextEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal


# 수동 선택 콤보 라벨 ↔ 내부 kind 매핑
_KIND_BY_LABEL = {
    "Auto": "auto",
    "Fit (gas ppb / RMS)": "fit",
    "R trend": "r_trend",
    "R(λ) curve": "r_curve",
    "α trace": "alpha_trace",
    "Array": "array",
    "Reference": "reference",
    "Concentration": "concentration",
}
_KIND_KO = {
    "fit": "Fit (gas ppb / RMS)",
    "r_trend": "R trend",
    "r_curve": "R(λ) curve",
    "alpha_trace": "α trace",
    "array": "Array",
    "reference": "Reference",
    "concentration": "Concentration",
}
from PyQt6.QtGui import QColor
from gui.theme import AUGUR, SERIES as _SERIES, species_color
_PALETTE = list(_SERIES)   # gui/theme.py 공통 팔레트


class ResultViewerWidget(QWidget):
    """저장된 결과 파일을 불러와 종류를 자동 판별하고 알맞은 그래프로 표시."""

    # 선택/현재 파일들을 Plot Maker 선반으로 보내달라는 신호(app_window가 연결)
    send_to_plotmaker = pyqtSignal(list)

    # 순수 파서는 gui/result_viewer_io.py 로 분리, self._x(...) 호출 유지를 위해 재바인딩
    _load_result_time_gas = staticmethod(load_result_time_gas)
    _detect               = staticmethod(detect)
    _detect_sep           = staticmethod(detect_sep)
    _load_fit_table       = staticmethod(load_fit_table)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = None
        self._region = None      # pg.LinearRegionItem (구간선택)
        self._time_shift_hours = 0.0   # 표시 전용 시각 보정(원본/Export/Stats는 항상 원래 시각)
        self._init_ui()

    # ──────────────────────────────────────────────────────────────
    def _init_ui(self):
        from gui.flow_layout import FlowLayout
        root = QVBoxLayout(self)

        # ── 툴바 1줄: [열기] | [보기] ────────────────────────────────────
        def _sep():
            s = QLabel("|")
            s.setStyleSheet(f"color:{AUGUR.faint}; padding:0 4px;")
            return s

        def _grp(text):
            l = QLabel(text)
            l.setStyleSheet(f"color:{AUGUR.muted}; font-weight:bold;")
            return l

        bar = FlowLayout(spacing=6)
        bar.addWidget(_grp("Open"))
        self._btn = QPushButton("File")
        self._btn.clicked.connect(self._open)
        bar.addWidget(self._btn)
        self._btn_folder = QPushButton("Folder")
        self._btn_folder.clicked.connect(self._open_folder)
        bar.addWidget(self._btn_folder)
        self._btn_dates = QPushButton("Dates")
        self._btn_dates.setToolTip(
            "Pick a date range and series from daily fit buckets ({YYMMDD}/{neg}/{QC}/), auto-merge and open.\n"
            "Merged files are saved in _derived/ (cached for reuse) — original daily files are untouched.")
        self._btn_dates.clicked.connect(self._open_by_date)
        bar.addWidget(self._btn_dates)
        bar.addWidget(QLabel("Type:"))
        self._combo = QComboBox()
        self._combo.addItems(list(_KIND_BY_LABEL.keys()))
        self._combo.setFixedWidth(150)
        self._combo.currentIndexChanged.connect(self._reload)
        bar.addWidget(self._combo)

        bar.addWidget(_sep())
        bar.addWidget(_grp("View"))
        bar.addWidget(QLabel("Gas:"))
        self._gas_combo = QComboBox()
        self._gas_combo.setFixedWidth(110)
        self._gas_combo.currentIndexChanged.connect(self._on_gas_changed)
        bar.addWidget(self._gas_combo)
        self._chk_hide_qc = QCheckBox("Hide QC")
        self._chk_hide_qc.setToolTip(
            "Hide rows with Status QC-* (auto quality filter) from plots and stats.\n"
            "Works by Status even for older files where values are not NaN.")
        self._chk_hide_qc.setChecked(True)
        self._chk_hide_qc.toggled.connect(self._on_gas_changed)
        bar.addWidget(self._chk_hide_qc)
        self._chk_err = QCheckBox("Err bars")
        self._chk_err.setToolTip("Show ±Error bars when a single gas is selected (report format only)")
        self._chk_err.toggled.connect(self._on_gas_changed)
        bar.addWidget(self._chk_err)
        # 사후 QC: 결과파일의 RMS 분포에서 K로 robust 임계를 다시 잡아 이상치 제외.
        # 메인 GUI _apply_auto_qc와 동일 식. QC 적용/미적용 어떤 파일에든 RMS만 있으면 동작.
        from PyQt6.QtWidgets import QDoubleSpinBox
        bar.addWidget(QLabel("QC K:"))
        self._spin_qc_k = QDoubleSpinBox()
        self._spin_qc_k.setRange(0.0, 30.0)
        self._spin_qc_k.setDecimals(1)
        self._spin_qc_k.setSingleStep(1.0)
        self._spin_qc_k.setValue(0.0)
        self._spin_qc_k.setFixedWidth(56)
        self._spin_qc_k.setToolTip(
            "Post-hoc QC sensitivity (0 = off). Recomputes threshold from this file's RMS:\n"
            "  thr = 10^(median(log10 RMS) + K·MAD), per channel.\n"
            "Rows above thr are excluded from plots/stats/export. Lower K = stricter.\n"
            "Works on any result (QC-applied or not) — RMS column is always original.")
        self._spin_qc_k.valueChanged.connect(self._on_gas_changed)
        bar.addWidget(self._spin_qc_k)

        bar.addWidget(QLabel("Time shift:"))
        self._spin_shift = QDoubleSpinBox()
        self._spin_shift.setRange(-72.0, 72.0)
        self._spin_shift.setDecimals(2)
        self._spin_shift.setSingleStep(1.0)
        self._spin_shift.setValue(0.0)
        self._spin_shift.setSuffix(" h")
        self._spin_shift.setFixedWidth(70)
        self._spin_shift.setToolTip(
            "Shift the plot display only by +/- hours (to visually align instrument clock error or timezone mismatch).\n"
            "Export/Merge/Stats/range selection always use the original file times — unaffected by this value.")
        self._spin_shift.valueChanged.connect(self._on_shift_changed)
        bar.addWidget(self._spin_shift)

        root.addLayout(bar)

        self._lbl = QLabel("Open a result file or folder.")
        self._lbl.setStyleSheet(f"color:{AUGUR.muted};")
        # 긴 상태문구가 툴바 최소폭을 강제(→그래프 잘림)하지 않게 가로 Ignored
        from PyQt6.QtWidgets import QSizePolicy
        self._lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self._lbl)

        # ── 툴바 2줄: [분석] | [내보내기] (Overlay·Diurnal은 Plot Maker로 이관) ──
        fbar = FlowLayout(spacing=6)
        fbar.addWidget(_grp("Analyze"))
        self._btn_calc = QPushButton("Calculator")
        self._btn_calc.setToolTip(
            "Data calculator: map result columns to variables (A,B,C…) and combine them with expressions like (A-B)/C\n"
            "→ preview + save CSV. Cross-dataset variables are auto-interpolated onto a time grid.\n"
            "(NO2/PNs/ANs channel differences too: PNs = PNsCh−Cold = 'B-A')")
        self._btn_calc.clicked.connect(self._open_calculator)
        fbar.addWidget(self._btn_calc)
        self._btn_stats = QPushButton("Σ Stats")
        self._btn_stats.setToolTip("Per-gas mean/median/σ/n for current fit (range-aware)")
        self._btn_stats.clicked.connect(self._show_stats)
        fbar.addWidget(self._btn_stats)
        self._btn_to_pm = QPushButton("To Plot Maker")
        self._btn_to_pm.setToolTip("Send the selected (or current) files to the Plot Maker shelf\n"
                                   "for overlays, diurnal plots, scatter plots, etc.")
        self._btn_to_pm.clicked.connect(self._to_plot_maker)
        fbar.addWidget(self._btn_to_pm)

        fbar.addWidget(_sep())
        fbar.addWidget(_grp("Export"))
        self._btn_region = QPushButton("Range")
        self._btn_region.setCheckable(True)
        self._btn_region.setToolTip("Show draggable time-range handles on the plot")
        self._btn_region.toggled.connect(self._toggle_region)
        fbar.addWidget(self._btn_region)
        # 정확한 시각 직접 입력 — 드래그와 양방향 동기 (Export/Stats의 기준값)
        from PyQt6.QtWidgets import QDateTimeEdit
        self._dt_from = QDateTimeEdit()
        self._dt_to = QDateTimeEdit()
        for de in (self._dt_from, self._dt_to):
            de.setDisplayFormat("MM-dd HH:mm")
            de.setFixedWidth(110)
            de.setCalendarPopup(True)
            de.setToolTip("Export/Stats time range (synced with drag handles)")
            de.editingFinished.connect(self._on_range_edited)
            fbar.addWidget(de)
        self._btn_slice = QPushButton("Export")
        self._btn_slice.setToolTip("Save the time range (or all) as a new result file.\n"
                                   "Multiple selected files in the list are merged first.\n"
                                   "Concentration CSV (e.g. Calculator output): saves the whole file "
                                   "with the current Time shift baked into its time column "
                                   "(0 shift = plain copy).")
        self._btn_slice.clicked.connect(self._export_region)
        fbar.addWidget(self._btn_slice)
        self._btn_merge = QPushButton("Merge")
        self._btn_merge.setToolTip("Merge selected same-format result files in time order")
        self._btn_merge.clicked.connect(self._merge_files)
        fbar.addWidget(self._btn_merge)
        self._btn_png = QPushButton("PNG")
        self._btn_png.setToolTip("Export current plots as high-resolution PNG (2400 px wide,\n"
                                 "top+bottom combined). For papers/reports.")
        self._btn_png.clicked.connect(self._export_png)
        fbar.addWidget(self._btn_png)

        self._stats_lbl = QLabel("")
        self._stats_lbl.setStyleSheet(f"color:{AUGUR.sub};")
        from PyQt6.QtWidgets import QSizePolicy as _QSP
        self._stats_lbl.setSizePolicy(_QSP.Policy.Ignored, _QSP.Policy.Preferred)
        root.addLayout(fbar)
        root.addWidget(self._stats_lbl)

        # 좌: 폴더 파일목록(형태별 그룹) / 우: 플롯 2단(위=주, 아래=보조)
        hsplit = QSplitter(Qt.Orientation.Horizontal)
        self._list = QListWidget()
        self._list.setMinimumWidth(180)
        # 다중 선택 → 여러 fit 파일 겹쳐비교 가능
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.itemClicked.connect(self._on_list_item)
        self._list.itemDoubleClicked.connect(self._on_list_double)
        from gui.empty_hint import attach
        attach(self._list, "Open a result file, a folder or a date range\n(File / Folder / Dates above).",
               is_empty=lambda lw: lw.count() == 0 and not self._path)   # File… opens without listing it

        # 좌측 아래: 같은 날·같은 채널의 **버전들**(B3). 파라미터를 바꿔 여러 번 돌리는 게
        # 실제 작업 방식인데 지금껏 파일명으로만 구분했다 — 그런데 파일명이 설정을 다
        # 담지 못한다. `.meta.json`을 읽어 무엇이 달라졌는지 한 줄로 보여준다.
        lsplit = QSplitter(Qt.Orientation.Vertical)
        lsplit.addWidget(self._list)
        _vw = QWidget()
        _vl = QVBoxLayout(_vw)
        _vl.setContentsMargins(0, 4, 0, 0)
        _vl.setSpacing(2)
        self._ver_hdr = QLabel("Versions")
        self._ver_hdr.setStyleSheet(f"color:{AUGUR.muted}; font-weight:bold;")
        _vl.addWidget(self._ver_hdr)
        self._ver_list = QListWidget()
        self._ver_list.setToolTip(
            "Other saved runs of the same day and channel, read from their .meta.json.\n"
            "Each line: version · runid · saved time · median RMS · what changed vs the\n"
            "previous version.  Click one to load it.\n"
            "Files without a .meta.json do not appear — run tools/backfill_meta.py.")
        self._ver_list.itemClicked.connect(self._on_version_click)
        _vl.addWidget(self._ver_list)
        lsplit.addWidget(_vw)
        lsplit.setSizes([320, 200])
        hsplit.addWidget(lsplit)

        self._fit_cache = None   # 최근 로드한 fit 테이블(포인트클릭 α 팝업용)

        psplit = QSplitter(Qt.Orientation.Vertical)
        self._pw_top = pg.PlotWidget()
        self._pw_bot = pg.PlotWidget()
        for pw in (self._pw_top, self._pw_bot):
            pw.setBackground(AUGUR.surface)
            pw.showGrid(x=True, y=True, alpha=0.3)
            pw.addLegend(offset=(10, 10))
        psplit.addWidget(self._pw_top)
        psplit.addWidget(self._pw_bot)
        attach(self._pw_top, "Time series of the opened results show here. Click a point to see "
                             "that scan's spectrum and residual below.")
        attach(self._pw_bot, "A second view shows here for some files (e.g. Leff of an R file).")

        # ── B2: 핏 결과 전용 세로 스택 (종별 레인 + shift/squeeze + RMS) ──
        # 기존 6개 핸들러(r_trend·r_curve·alpha·reference·concentration·array)는
        # 계속 _pw_top/_pw_bot을 쓴다 — fit일 때만 이 스택으로 갈아끼운다.
        self._stack_host = QWidget()
        self._stack_lay = QVBoxLayout(self._stack_host)
        self._stack_lay.setContentsMargins(0, 0, 0, 0)
        self._stack_lay.setSpacing(2)
        self._lanes: list = []          # [(key, PlotWidget)] — 재사용 풀
        psplit.addWidget(self._stack_host)

        # 클릭한 스캔의 상세(아래 패널) — 시계열을 가리지 않고 같은 화면에 뜬다.
        # 예전엔 팝업이라 창을 옮겨가며 봐야 했다.
        self._pw_detail = pg.PlotWidget()
        self._pw_detail.setBackground(AUGUR.surface)
        self._pw_detail.showGrid(x=True, y=True, alpha=0.3)
        self._pw_detail.addLegend(offset=(10, 10))
        self._pw_detail.setLabel("bottom", "Wavelength (nm) / pixel")
        self._pw_detail.setTitle("Scan detail — click a point above")
        psplit.addWidget(self._pw_detail)

        # 잔차 패널 — 그때 설정(.meta.json)으로 재핏해서만 그린다(core/refit.py).
        # α와 스케일이 100배쯤 다르므로 같은 축에 겹치면 잔차가 직선으로 보인다 → 별도 축,
        # x만 링크해서 같은 파장 구간을 본다.
        self._pw_resid = pg.PlotWidget()
        self._pw_resid.setBackground(AUGUR.surface)
        self._pw_resid.showGrid(x=True, y=True, alpha=0.3)
        self._pw_resid.addLegend(offset=(10, 10))
        self._pw_resid.setLabel("left", "residual (cm^-1)")
        self._pw_resid.setTitle("Residual - click a point above")
        self._pw_resid.setXLink(self._pw_detail)
        psplit.addWidget(self._pw_resid)

        self._psplit = psplit
        # fit: five lanes share the third pane — at 500 they were ~90 px and clipped their axis titles
        psplit.setSizes([400, 250, 640, 180, 150])
        # start like a non-fit file (_show): the fit-only lanes, scan detail and residual appear
        # when a fit opens — shown empty they took ~300 px and squashed the panes below
        for w in (self._stack_host, self._pw_detail, self._pw_resid):
            w.hide()
        hsplit.addWidget(psplit)
        hsplit.setSizes([240, 780])
        root.addWidget(hsplit, 1)

    # ── NO2 / PNs / ANs 유도 농도 (TD-CEAS) ──────────────────────────

    def _open_calculator(self):
        """🧮 데이터 계산기 다이얼로그. 목록의 결과파일들을 변수 후보로 넘긴다.
        (구 NO2/PNs/ANs 채널차분은 이 계산기의 특수케이스: PNs = 'B-A' 등)."""
        from gui.dlg_calculator import CalculatorDialog
        paths = []
        for i in range(self._list.count()):
            data = self._list.item(i).data(Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and data[0] == "file" and os.path.isfile(data[1]):
                if data[1] not in paths:
                    paths.append(data[1])
        if self._path and self._path not in paths:
            paths.insert(0, self._path)
        CalculatorDialog(self, datasets=paths).exec()

    # ──────────────────────────────────────────────────────────────
    def _open(self):
        from gui.dlg_dir import dlg_dir
        path, _ = QFileDialog.getOpenFileName(
            self, "Select result file", dlg_dir("result"),
            "Result files (*.dat *.csv *.txt *.tsv);;All Files (*)")
        if path:
            dlg_dir("result", path)
            self._path = path
            self._reload()

    def _open_folder(self):
        """폴더를 받아 내부 결과파일을 형태별로 그룹·목록화. 항목 클릭 → 표시."""
        import glob
        from gui.dlg_dir import dlg_dir
        d = QFileDialog.getExistingDirectory(self, "Select result folder", dlg_dir("result_folder"))
        if d:
            dlg_dir("result_folder", d)
        if not d:
            return
        self._browse_dir(d)

    def _open_by_date(self):
        """일별 버킷에서 기간·시리즈 선택  자동 머지 파일들을 목록에 올리고 첫 개 표시."""
        from gui.dlg_date_load import DateLoadDialog
        dlg = DateLoadDialog(self)
        if not dlg.exec() or not dlg.loaded_paths:
            return
        self._list.clear()
        for p in dlg.loaded_paths:
            it = QListWidgetItem(f"{os.path.basename(p)}")
            it.setData(Qt.ItemDataRole.UserRole, ("file", p))
            self._list.addItem(it)
        self._lbl.setText(f"{len(dlg.loaded_paths)} merged series — click to view")
        self._lbl.setStyleSheet(f"color:{AUGUR.info};")
        self._path = dlg.loaded_paths[0]
        self._reload()

    # ── 미니 파일탐색기 ───────────────────────────────────────────────
    _RESULT_EXTS = ('.dat', '.csv', '.txt', '.tsv')

    def _browse_dir(self, d):
        """현재 폴더의 '하위 폴더 + 이 폴더 직속 결과파일'만 보여준다(재귀 X).
        폴더는 더블클릭으로 진입, '..'로 상위. 파일은 클릭하면 표시."""
        import glob
        self._browse_cwd = d
        self._list.clear()
        # 상위로 가기
        parent = os.path.dirname(d.rstrip('\\/'))
        if parent and parent != d:
            up = QListWidgetItem("..")
            up.setData(Qt.ItemDataRole.UserRole, ("dir", parent))
            self._list.addItem(up)
        # 하위 폴더 (결과파일을 품은 것만 — 빈 트리 숨김)
        subdirs = sorted(p for p in glob.glob(os.path.join(d, '*')) if os.path.isdir(p))
        for p in subdirs:
            has = any(glob.glob(os.path.join(p, '**', '*' + e), recursive=True)
                      for e in self._RESULT_EXTS)
            if not has:
                continue
            nfile = sum(len(glob.glob(os.path.join(p, '**', '*' + e), recursive=True))
                        for e in self._RESULT_EXTS)
            it = QListWidgetItem(f"{os.path.basename(p)}/  ({nfile})")
            it.setData(Qt.ItemDataRole.UserRole, ("dir", p))
            self._list.addItem(it)
        # 이 폴더 직속 결과파일 (재귀 X)
        files = sorted(f for e in self._RESULT_EXTS
                       for f in glob.glob(os.path.join(d, '*' + e)) if os.path.isfile(f))
        for f in files:
            try:
                k = self._detect(f)
            except Exception:
                k = "array"
            it = QListWidgetItem(f"{os.path.basename(f)}  [{_KIND_KO.get(k, k)}]")
            it.setData(Qt.ItemDataRole.UserRole, ("file", f))
            self._list.addItem(it)
        self._lbl.setText(f"{os.path.basename(d) or d}  —  {len(subdirs)} folders · {len(files)} files"
                          + ("  (double-click folder to enter)" if subdirs else ""))
        self._lbl.setStyleSheet(f"color:{AUGUR.info};")

    def _on_list_item(self, item):
        """단일클릭: 파일이면 표시. 폴더면 무시(더블클릭으로 진입)."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and data[0] == "file":
            self._path = data[1]
            self._reload()

    def _on_list_double(self, item):
        """더블클릭: 폴더면 진입, 파일이면 표시."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, tuple):
            return
        if data[0] == "dir":
            self._browse_dir(data[1])
        else:
            self._path = data[1]
            self._reload()

    # ── 버전 목록 (B3) ────────────────────────────────────────────────
    def _refresh_versions(self, path):
        """현재 파일과 같은 날·채널의 저장본들을 meta에서 읽어 목록으로."""
        from core.run_meta import find_versions, diff_meta, summarize_diff, read_meta
        self._ver_list.clear()
        self._ver_hdr.setText("Versions")
        try:
            versions = find_versions(path) if path else []
        except OSError:
            versions = []
        if not versions:
            self._ver_hdr.setText("Versions  —  no .meta.json found")
            it = QListWidgetItem("(run tools/backfill_meta.py to index existing results)")
            it.setForeground(QColor(AUGUR.muted))
            self._ver_list.addItem(it)
            return

        cur = os.path.abspath(path)
        me = read_meta(path) or {}
        self._ver_hdr.setText(f"Versions  —  {len(versions)} run(s), "
                              f"ch{me.get('channel')} {me.get('label') or ''}".rstrip())
        prev = None
        for i, v in enumerate(versions, 1):
            m = v["meta"]
            when = str(m.get("created") or "")[:16].replace("T", " ")
            rms = self._median_rms(v["path"])
            rms_s = f"RMS {rms:.4g}" if rms is not None else "RMS —"
            active = "  ← open" if os.path.abspath(v["path"]) == cur else ""
            legacy = "  (partial)" if str(m.get("runid", "")).startswith("L") else ""
            if "_archive" in os.path.normpath(v["path"]).split(os.sep):
                legacy += "  (archived)"
            change = summarize_diff(diff_meta(prev, m)) if prev else "first version"
            it = QListWidgetItem(
                f"v{i}  {m.get('runid')}{legacy}{active}\n"
                f"      {when} · {rms_s} · {change}")
            it.setData(Qt.ItemDataRole.UserRole, v["path"])
            it.setToolTip(self._version_tooltip(m, prev))
            if active:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self._ver_list.addItem(it)
            prev = m

    @staticmethod
    def _version_tooltip(meta, prev):
        """그 버전의 전체 설정 diff(줄바꿈). 요약 한 줄로 안 보이는 나머지."""
        from core.run_meta import diff_meta
        head = [f"runid {meta.get('runid')}   saved {meta.get('created')}",
                f"window px {meta.get('window', {}).get('px')}  poly {meta.get('poly_deg')}",
                f"species: {', '.join(s.get('name') or '?' for s in meta.get('species') or [])}"]
        if str(meta.get("runid", "")).startswith("L"):
            head.append("rebuilt from the .dat header — some settings unknown (null)")
        aud = meta.get("day_audit") or {}
        for d, rep in sorted(aud.items()):
            if rep.get("status") in ("WARN", "FAIL"):
                head.append(f"! day audit {rep['status']} on {d}: "
                            + "; ".join(rep.get("messages") or [])[:200])
        if prev:
            d = diff_meta(prev, meta)
            head.append("")
            head.append(f"changed vs previous ({len(d)}):" if d else "no setting change")
            head += [f"  {k}: {o!r} → {n!r}" for k, o, n in d[:20]]
        return "\n".join(head)

    def _median_rms(self, path):
        """그 버전의 RMS 중앙값. 읽기 실패·컬럼 없음이면 None(빈칸으로 표시)."""
        try:
            t = self._load_fit_table(path)
        except Exception:
            return None
        rms = t.get("rms") if isinstance(t, dict) else None
        if rms is None:
            return None
        arr = np.asarray(rms, dtype=float)
        arr = arr[np.isfinite(arr)]
        return float(np.median(arr)) if arr.size else None

    def _on_version_click(self, item):
        p = item.data(Qt.ItemDataRole.UserRole)
        if p and os.path.exists(p):
            self._path = p
            self._reload()

    def _on_shift_changed(self, v):
        self._time_shift_hours = float(v)
        self._range_init_path = None   # 시프트 값이 바뀌면 범위입력칸도 새 시프트로 재초기화
        self._reload()

    def _reload(self):
        if not self._path:
            return
        forced = _KIND_BY_LABEL.get(self._combo.currentText(), "auto")
        kind = self._detect(self._path) if forced == "auto" else forced
        self._current_kind = kind
        self._pw_top.clear()
        self._pw_bot.clear()
        # New file (or type): drop what belonged to the previous one — stats line, plot titles,
        # scan detail/residual (2026-10-02 audit R14). Same file redrawn (shift) keeps them.
        if getattr(self, "_shown", None) != (self._path, kind):
            self._shown = (self._path, kind)
            self._stats_lbl.setText("")
            self._pw_top.setTitle(None)
            self._pw_bot.setTitle(None)
            self._pw_detail.clear()
            self._pw_detail.setTitle("Scan detail — click a point above")
            self._pw_resid.clear()
            self._pw_resid.setTitle("Residual - click a point above")
        # B2 스택은 fit 전용 — 다른 종류는 예전 2단 플롯으로 되돌린다.
        if kind == "fit":
            self._pw_top.hide(); self._pw_bot.hide()
        else:
            self._stack_host.hide()
            self._pw_detail.hide()
            self._pw_resid.hide()
            for pw in self._lanes:
                pw.hide()
            self._pw_top.show(); self._pw_bot.show()
        try:
            handler = {
                "fit": self._plot_fit,
                "r_trend": self._plot_r_trend,
                "r_curve": self._plot_r_curve,
                "alpha_trace": self._plot_alpha_trace,
                "reference": self._plot_reference,
                "concentration": self._plot_concentration,
                "array": self._plot_array,
            }.get(kind, self._plot_array)
            handler(self._path)
            auto = "" if forced != "auto" else " (auto-detected)"
            shift_tag = (f"  ·  time shift {self._time_shift_hours:+g}h (display only)"
                        if self._time_shift_hours else "")
            self._lbl.setText(f"{os.path.basename(self._path)}  —  {_KIND_KO.get(kind, kind)}{auto}{shift_tag}")
            self._lbl.setStyleSheet(f"color:{AUGUR.fail};" if self._time_shift_hours else f"color:{AUGUR.info};")
        except Exception as e:
            self._lbl.setText(f"Failed to display: {e}  (try selecting Type manually)")
            self._lbl.setStyleSheet(f"color:{AUGUR.fail};")
            if kind == "fit":            # don't leave the previous file's lanes on screen
                self._fit_cache = None
                self._stack_host.hide(); self._pw_detail.hide(); self._pw_resid.hide()
        # Range fields drive fit Export/Stats only — grey them out when they mean nothing here
        has_t = (kind == "fit" and bool(self._fit_cache)
                 and self._fit_cache.get("time") is not None)
        for de in (self._dt_from, self._dt_to):
            de.setEnabled(has_t)
        # 버전 목록은 핏 결과에만 의미가 있다(R 커브·α엔 meta가 없다).
        # 표시가 실패해도 목록은 갱신한다 — 어느 버전이 열려 있는지가 그때 더 궁금하다.
        try:
            if kind == "fit":
                self._refresh_versions(self._path)
            else:
                self._ver_list.clear()
                self._ver_hdr.setText("Versions  —  (fit results only)")
        except Exception as _ve:                 # noqa: BLE001 — 부가 패널이 본체를 막지 않는다
            self._ver_hdr.setText(f"Versions  —  unavailable ({_ve})")

    # ── 자동 판별 ──────────────────────────────────────────────────

    # ── 공통: 구분자 추정 후 숫자 표 읽기 ──────────────────────────


    @staticmethod
    def _set_time_axis(pw, on: bool):
        ax = pg.DateAxisItem(orientation="bottom") if on else pg.AxisItem(orientation="bottom")
        pw.setAxisItems({"bottom": ax})

    # ── R 트렌드 (.dat) → R/Leff 시계열 ────────────────────────────
    def _plot_r_trend(self, path):
        ts, rmean, rstd, leff = [], [], [], []
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            for ln in f:
                s = ln.rstrip("\n")
                if not s.strip() or s.startswith("#") or s.lower().startswith("timestamp"):
                    continue
                c = s.split("\t")
                if len(c) < 7:
                    continue
                try:
                    t = datetime.strptime(c[0].strip(), "%Y-%m-%d %H:%M")
                    rmean.append(float(c[2]) * 100.0)
                    rstd.append(float(c[3]) * 100.0)
                    leff.append(float(c[6]))
                    ts.append(t.timestamp())
                except (ValueError, IndexError):
                    continue
        if not ts:
            raise ValueError("No R-trend data rows found")
        ts = np.array(ts); rmean = np.array(rmean); rstd = np.array(rstd); leff = np.array(leff)
        if self._time_shift_hours:
            ts = ts + self._time_shift_hours * 3600.0
        self._set_time_axis(self._pw_top, True)
        self._set_time_axis(self._pw_bot, True)
        col = _PALETTE[0]
        self._pw_top.plot(ts, rmean, pen=pg.mkPen(col, width=2), symbol="o",
                          symbolSize=6, symbolBrush=col, name="R_mean (%)")
        err = pg.ErrorBarItem(x=ts, y=rmean, top=rstd, bottom=rstd, beam=0,
                              pen=pg.mkPen(col, width=1, style=Qt.PenStyle.DotLine))
        self._pw_top.addItem(err)
        self._pw_top.setLabel("left", "R (%)")
        self._pw_top.setTitle(f"R time-series — {len(ts)} cycles")
        # 0.9999 근처 변동 보이게 타이트 줌
        med = float(np.median(rmean)); sd = float(np.std(rmean))
        margin = max(sd * 4.0, 0.0015)
        self._pw_top.setYRange(med - margin, min(med + margin, 100.0 + 5e-4), padding=0)

        self._pw_bot.plot(ts, leff, pen=pg.mkPen(col, width=2), symbol="s",
                          symbolSize=5, symbolBrush=col, name="Leff (km)")
        self._pw_bot.setLabel("left", "Leff (km)")
        self._pw_bot.setLabel("bottom", "Date / Time")
        self._pw_bot.setTitle("Leff time-series")

    # ── 파일별 R(λ) (_R.dat) → R(λ) + Leff(λ) ─────────────────────
    def _plot_r_curve(self, path):
        d = np.loadtxt(path, comments="#", ndmin=2)
        if d.shape[1] < 3:
            raise ValueError("R(λ) columns missing (need wave, R_raw, R_fit)")
        wave, r_raw, r_fit = d[:, 0], d[:, 1], d[:, 2]
        self._set_time_axis(self._pw_top, False)
        self._set_time_axis(self._pw_bot, False)
        self._pw_top.plot(wave, r_raw, pen=None, symbol="o", symbolSize=3,
                          symbolBrush=(150, 150, 150, 140), name="R_raw")
        self._pw_top.plot(wave, r_fit, pen=pg.mkPen(_PALETTE[3], width=2.5),
                          name="R 5th-poly fit")
        self._pw_top.setLabel("left", "Reflectance R")
        self._pw_top.setTitle(f"R(λ) — {os.path.basename(path)}")
        fin = np.isfinite(r_fit)
        if fin.any():
            self._pw_top.setYRange(float(np.nanmin(r_fit[fin])), 1.0, padding=0.1)
        if d.shape[1] >= 5:
            self._pw_bot.plot(wave, d[:, 4], pen=pg.mkPen(_PALETTE[0], width=2),
                              name="Leff (km)")
            self._pw_bot.setLabel("left", "Leff (km)")
            self._pw_bot.setLabel("bottom", "Wavelength (nm)")
            self._pw_bot.show()
        else:
            self._pw_bot.hide()

    # ── α trace (alpha_trace.dat) → 평균 α 스펙트럼 ±1σ ─────────────
    def _plot_alpha_trace(self, path):
        from gui.result_viewer_io import read_alpha_trace
        wave, _ids, a = read_alpha_trace(path)
        if a.size == 0:
            raise ValueError("No alpha data rows")
        m = np.nanmean(a, axis=0); s = np.nanstd(a, axis=0)
        self._set_time_axis(self._pw_top, False)
        self._pw_top.plot(wave, m + s, pen=pg.mkPen((255, 140, 0, 90), width=1))
        self._pw_top.plot(wave, m - s, pen=pg.mkPen((255, 140, 0, 90), width=1))
        self._pw_top.plot(wave, m, pen=pg.mkPen(_PALETTE[1], width=2), name="mean α")
        self._pw_top.setLabel("left", "α (cm⁻¹)")
        self._pw_top.setLabel("bottom", "Wavelength (nm)")
        self._pw_top.setTitle(f"α mean spectrum — {os.path.basename(path)} ({a.shape[0]} scans, ±1σ)")
        self._pw_bot.hide()

    # ── 레퍼런스 스펙트럼 (.csv) ───────────────────────────────────
    def _plot_reference(self, path):
        sep = self._detect_sep(path)
        d = np.loadtxt(path, comments="#", delimiter=sep, ndmin=2)
        if d.shape[1] >= 2:
            x, y = d[:, 0], d[:, 1]
        else:
            x, y = np.arange(len(d)), d[:, 0]
        self._set_time_axis(self._pw_top, False)
        self._pw_top.plot(x, y, pen=pg.mkPen(_PALETTE[4], width=2), name="reference")
        self._pw_top.setLabel("left", "Value")
        self._pw_top.setLabel("bottom", "Wavelength (nm)")
        self._pw_top.setTitle(f"Reference — {os.path.basename(path)}")
        self._pw_bot.hide()

    # ── 농도 시계열 (.csv) ─────────────────────────────────────────
    def _plot_concentration(self, path):
        import pandas as pd
        sep = self._detect_sep(path) or r"\s+"
        df = pd.read_csv(path, sep=sep, comment="#", engine="python", encoding="utf-8-sig")
        # 첫 컬럼을 시간축으로 시도
        xcol = df.columns[0]
        x_dt = pd.to_datetime(df[xcol], errors="coerce")
        if x_dt.notna().mean() > 0.5:
            # naive 시각을 로컬(머신 TZ) epoch으로 — datetime64.astype(int64)는 naive를
            # UTC로 간주해 KST 머신에서 시간축이 9h 밀린다(Plot Maker와 동일 버그 수정).
            x = np.array([t_.timestamp() if pd.notna(t_) else np.nan
                          for t_ in x_dt.dt.to_pydatetime()], dtype=float)
            if self._time_shift_hours:
                x = x + self._time_shift_hours * 3600.0
            self._set_time_axis(self._pw_top, True)
            self._pw_top.setLabel("bottom", "Date / Time")
            ycols = df.columns[1:]
        else:
            x = np.arange(len(df))
            self._set_time_axis(self._pw_top, False)
            self._pw_top.setLabel("bottom", "index")
            ycols = df.columns
        # 개수 컬럼(n_used, *_n)은 스캔 수(신뢰도 메타)지 농도가 아니라 스케일이 달라
        # 같은 축에 그리면 방해만 됨 → 농도 플롯에서 제외(CSV엔 그대로 보존).
        ycols = [c for c in ycols
                 if not (str(c) == "n_used" or str(c).endswith("_n")
                         or str(c) in ("T_used_C", "P_used_mbar")
                         or str(c).endswith("_RealConc"))]
        # Flags, error columns, correction factors (g_prime) and states are not concentrations —
        # drawn with them on one axis, a ΣANs file was an unreadable block of colour (UI audit
        # 2026-10-04). Prefer the *ppb* columns when the file names its unit.
        def _not_conc(c):
            s = str(c).lower()
            return "flag" in s or "err" in s or "state" in s or s.startswith("g_")
        ycols = [c for c in ycols if not _not_conc(c)]
        ppb = [c for c in ycols if "ppb" in str(c).lower()]
        ycols = ppb or ycols
        # the Gas box picks one column (as it picks a gas for fit files)
        self._sync_gas_combo([str(c) for c in ycols])
        sel = self._gas_combo.currentText()
        if sel and sel != "All" and sel in [str(c) for c in ycols]:
            ycols = [c for c in ycols if str(c) == sel]
        n = 0
        for i, c in enumerate(ycols):
            y = pd.to_numeric(df[c], errors="coerce").to_numpy()
            if not np.isfinite(y).any():
                continue
            self._pw_top.plot(np.asarray(x, float), y,
                              pen=pg.mkPen(_PALETTE[i % len(_PALETTE)], width=2),
                              name=str(c))
            n += 1
        if n == 0:
            raise ValueError("No numeric concentration columns found")
        self._pw_top.setLabel("left", "Concentration")
        self._pw_top.setTitle(f"Concentration — {os.path.basename(path)} ({n} columns)")
        self._pw_top.enableAutoRange()      # not the previous file's range
        self._pw_bot.hide()

    # ── α/일반 숫자 배열 → vs 픽셀(또는 1열 vs 2열) ───────────────
    def _plot_array(self, path):
        sep = self._detect_sep(path)
        d = np.loadtxt(path, comments="#", delimiter=sep, ndmin=2)
        self._set_time_axis(self._pw_top, False)
        if d.shape[1] == 1:
            y = d[:, 0]
            self._pw_top.plot(np.arange(len(y)), y,
                              pen=pg.mkPen(_PALETTE[1], width=1.5), name="value")
            self._pw_top.setLabel("bottom", "Pixel / index")
        else:
            # 첫 컬럼을 x로 가정(파장일 수 있음), 나머지 컬럼들 플롯
            x = d[:, 0]
            for j in range(1, min(d.shape[1], 9)):
                self._pw_top.plot(x, d[:, j],
                                  pen=pg.mkPen(_PALETTE[(j - 1) % len(_PALETTE)], width=1.5),
                                  name=f"col{j}")
            self._pw_top.setLabel("bottom", "col0 (x)")
        self._pw_top.setLabel("left", "Value (α / optical depth etc.)")
        self._pw_top.setTitle(f"Array — {os.path.basename(path)}  shape={d.shape}")
        self._pw_bot.hide()

    # ── fit 결과 (_fit.tsv) → 가스별 ppb + RMS + 통계 ────────────────

    def _sync_gas_combo(self, names):
        """가스 콤보를 fit 파일의 가스목록으로 (선택 유지하며) 갱신."""
        want = ["All"] + list(names)
        cur = self._gas_combo.currentText()
        have = [self._gas_combo.itemText(i) for i in range(self._gas_combo.count())]
        if have == want:
            return
        self._gas_combo.blockSignals(True)
        self._gas_combo.clear()
        self._gas_combo.addItems(want)
        if cur in want:
            self._gas_combo.setCurrentText(cur)
        self._gas_combo.blockSignals(False)

    def _on_gas_changed(self, _idx):
        # fit 모드에서 가스 선택 바뀌면 현재 파일 다시 그림. Only when the open file IS a fit —
        # _fit_cache may belong to an earlier file (2026-10-02 audit R4: CSV/alpha re-plotted as fit).
        if getattr(self, "_current_kind", None) == "fit" and self._fit_cache and self._path:
            self._pw_top.clear(); self._pw_bot.clear(); self._pw_bot.show()
            self._plot_fit(self._path)
        elif getattr(self, "_current_kind", None) == "concentration" and self._path:
            self._pw_top.clear()
            self._plot_concentration(self._path)

    def _qc_mask(self, t):
        """숨길/제외할 행 마스크(True) — 두 기준의 OR:
          (1) Hide QC 체크 시 Status가 QC-* 인 행
          (2) Post-hoc QC: K>0이면 RMS 분포에서 robust 임계 초과 행 (채널별)."""
        hide_st = bool(getattr(self, '_chk_hide_qc', None) and self._chk_hide_qc.isChecked())
        K = self._spin_qc_k.value() if hasattr(self, '_spin_qc_k') else 0.0
        # 단일 출처: Plot Maker로 넘긴 규칙도 같은 함수로 마스크를 만든다.
        return qc_hidden_mask(len(t["row_idx"]), status=t.get("status"), rms=t.get("rms"),
                              channel=t.get("channel"), hide_status_qc=hide_st, K=K)

    def view_rules(self):
        """지금 보고 있는 상태(Hide QC·사후 QC K·구간)를 재계산 가능한 규칙으로 번역.
        fit 파일을 보고 있을 때만 의미가 있다(_fit_cache가 다른 파일 것일 수 있음)."""
        if getattr(self, '_current_kind', None) != "fit" or not self._fit_cache:
            return []
        rules = []
        if getattr(self, '_chk_hide_qc', None) and self._chk_hide_qc.isChecked():
            rules.append({"kind": "status_qc"})
        K = self._spin_qc_k.value() if hasattr(self, '_spin_qc_k') else 0.0
        if K > 0:
            rules.append({"kind": "rms_k", "K": float(K)})
        t0, t1 = self._region_times()        # 원본 시각 기준, 전체 범위면 (None, None)
        if t0 is not None:
            rules.append({"kind": "time_range", "t0": t0.timestamp(), "t1": t1.timestamp()})
        return rules

    # ── B2: flag 색 · 세로 스택 레인 ─────────────────────────────────
    # 값은 **절대 지우지 않는다**(헌장 ①) — 색으로만 구분한다. 'Hide QC' 체크박스는
    # 사용자가 명시적으로 켰을 때만 숨기고, 그때도 숨긴 개수를 제목에 적는다.
    # ok=가스 고유색 · unstable=붉음(핏 흔들림) · settling=회색(정착 구간, 값은 살아있음)
    # · qc=주황(자동 QC가 거른 스캔) · cal=보라(ZA/He 교정). 단일 출처: result_viewer_io.flag_color
    _FLAG_COLOR = {k: flag_color(k) for k in FLAG_KEYS}

    _flag_of = staticmethod(flag_of)     # 단일 출처: gui.result_viewer_io.flag_of

    def _lane(self, key, i, n_total):
        """스택 레인 하나를 얻는다(없으면 만들고, 있으면 비워서 재사용).

        레인을 매번 새로 만들면 파일을 바꿀 때마다 위젯이 쌓여 메모리가 샌다.
        X축은 첫 레인에 링크해 시간축을 공유한다."""
        while len(self._lanes) <= i:
            pw = pg.PlotWidget()
            pw.setBackground(AUGUR.surface)
            pw.showGrid(x=True, y=True, alpha=0.3)
            pw.addLegend(offset=(10, 6))
            # no "(x0.001)" suffix — a lane is ~120 px tall and the suffix clipped the gas name
            pw.getAxis("left").enableAutoSIPrefix(False)
            # keeps a gas name on its axis; below this the page scrolls (1366@150 %: ~70 px lanes)
            pw.setMinimumHeight(120)
            self._stack_lay.addWidget(pw)
            self._lanes.append(pw)
        pw = self._lanes[i]
        pw.clear()
        pw.show()
        if i > 0:
            pw.setXLink(self._lanes[0])
        # 맨 아래 레인만 x축 눈금·라벨을 보인다(위쪽은 공간 낭비)
        pw.getAxis("bottom").setStyle(showValues=(i == n_total - 1))
        return pw

    def _hide_extra_lanes(self, n_used):
        for pw in self._lanes[n_used:]:
            pw.hide()

    def _plot_fit(self, path):
        # 같은 파일(경로·수정시각·크기)이면 파싱 결과를 재사용 — 가스 전환·Hide QC·K·시프트를
        # 바꿀 때마다 26만 행을 다시 읽었다(매번 ~3 s, 2026-10-01 실측). 파일이 바뀌면 다시 읽는다.
        try:
            key = (os.path.abspath(path), os.path.getmtime(path), os.path.getsize(path))
        except OSError:
            key = None
        if key is not None and self._fit_cache is not None and getattr(self, "_fit_cache_key", None) == key:
            t = self._fit_cache
        else:
            t = self._load_fit_table(path)
            self._fit_cache_key = key
        self._fit_cache = t
        self._sync_gas_combo(list(t["gases"].keys()))
        sel = self._gas_combo.currentText() or "All"
        names = list(t["gases"].keys()) if sel in ("All", "") else [sel]

        # x축: 실제 시각(datetime)이 있으면 그걸로(실시간 시계열), 없으면 row_idx
        has_time = t.get("time") is not None and np.isfinite(t["time"]).any()
        x = t["time"] if has_time else t["row_idx"]
        # 표시 전용 시각 보정 — t["time"](캐시 원본)·Export/구간선택/클릭 α팝업은 항상 원래 값 사용.
        if has_time and self._time_shift_hours:
            x = x + self._time_shift_hours * 3600.0
        self._set_time_axis(self._pw_top, has_time)
        self._set_time_axis(self._pw_bot, has_time)
        xlabel = "Date / Time" if has_time else "row_idx (≈time)"

        hide = self._qc_mask(t)
        n_hidden = int(hide.sum())

        # 시각 입력칸 초기화: 데이터 전체 범위 (파일 바뀔 때만)
        if has_time and getattr(self, '_range_init_path', None) != path:
            fin_t = x[np.isfinite(x)]
            if fin_t.size:
                self._set_range_edits(fin_t.min(), fin_t.max())
                self._range_init_path = path

        # ── 종별 세로 스택 + 공유 시간축 (B2) ──────────────────────────
        # 예전엔 전 가스를 한 축에 겹쳐 그려서 스케일이 다른 종(H2O ~1e-12 vs NO2 ppb)이
        # 서로를 납작하게 만들었다. 종마다 레인을 주고 x축만 링크한다.
        flags = [self._flag_of(s) for s in (t.get("status") or [""] * len(x))]
        lanes_spec = [("gas", g) for g in names]
        if t.get("shift") is not None or t.get("squeeze") is not None:
            lanes_spec.append(("shsq", None))
        lanes_spec.append(("rms", None))
        n_lanes = len(lanes_spec)

        stats = []
        self._scatters = []       # 레인마다 flag 색 점 산점도
        self._lane_hits = {}      # id(레인) → (x, y, x 정렬 순서) — 클릭 판정은 원본 전부로
        self._lane_thin = {}      # id(레인) → 큰 파일 화면 솎아내기 상태(줌하면 다시 고른다)
        # 화면 솎아내기 배율은 '지금 보이는 x 범위'로 정해진다(gui/pg_perf.py) — 큰 파일이면
        # 그리기 전에 데이터 범위로 잡아둬야 첫 계산부터 맞는다. That turns x auto-range off, so
        # every other file turns it back on (lane 0; the rest follow via the x link) — otherwise
        # all later files were drawn in the big file's stale x window (2026-10-02 audit R5).
        fin_x = x[np.isfinite(x)]
        pre_range = (len(x) > _BIG and fin_x.size > 1 and fin_x.max() > fin_x.min())
        for i, (kind, g) in enumerate(lanes_spec):
            pw = self._lane(kind, i, n_lanes)
            if pre_range:
                # padding=None = 자동 범위와 같은 여백. x 자동 범위를 다시 켜지 않는다 — 켜면 연결된
                # 레인들이 연쇄로 범위를 바꿔 마커를 수십 번 다시 만든다(실측 setData 23회). 'A'로 복귀.
                pw.getViewBox().setXRange(float(fin_x.min()), float(fin_x.max()), padding=None)
            elif i == 0:
                pw.getViewBox().enableAutoRange(x=True)
            self._set_time_axis(pw, has_time)
            if i == n_lanes - 1:
                pw.setLabel("bottom", xlabel)

            if kind == "gas":
                y = t["gases"].get(g)
                if y is None:
                    continue
                y = y.copy()
                y[hide] = np.nan          # 'Hide QC'를 켠 경우에만 숨긴다
                col = species_color(g)   # 같은 기체는 어느 창에서든 같은 색(gui/theme.py)
                if (getattr(self, '_chk_err', None) and self._chk_err.isChecked()):
                    err = (t.get("errs") or {}).get(g)
                    if err is not None:
                        ok = np.isfinite(y) & np.isfinite(err) & np.isfinite(x)
                        xs, ys, es = x[ok], y[ok], err[ok]
                        if xs.size:
                            step = max(1, xs.size // 1500)
                            pw.addItem(pg.ErrorBarItem(
                                x=xs[::step], y=ys[::step], height=2 * es[::step],
                                pen=pg.mkPen(col, width=1)))
                add_fast_curve(pw, x, y, pen=pg.mkPen(col, width=1.2))   # 큰 파일이면 peak 솎아내기
                # 점 색 = flag. 값을 지우는 게 아니라 **표시만** 다르게 한다.
                # 브러시는 flag마다 **한 개를 공유**한다 — 점마다 새 QBrush면 pyqtgraph가 점마다 심볼을
                # 다시 그려 26만 점×가스 4에서 90 s(2026-10-01 실측).
                shared = {k: pg.mkBrush(c or col) for k, c in self._FLAG_COLOR.items()}
                brushes = [shared[f] for f in flags]
                if len(x) > _BIG:
                    # 큰 파일: 화면 3 px 칸마다 점 하나 — 칸마다 **마지막** 점(전부 그렸을 때 위에 남는
                    # 점)이라 flag 색 비율이 전부 그린 그림과 같다. ok 점만 솎고 flag 점을 전부 덧그렸더니
                    # 2 %인 QC가 띠 전체를 덮어 '대부분 QC'처럼 보였다(실측 — 그림이 거짓말). 줌하면 다시.
                    sc = pg.ScatterPlotItem(size=5, pen=None)
                    pw.addItem(sc)
                    self._lane_thin[id(pw)] = {"item": sc, "x": x, "y": y, "brushes": brushes}
                    self._hook_lane_thin(pw)
                    self._rethin_lane(pw, use_extent=True)
                else:
                    sc = pg.ScatterPlotItem(x=x, y=y, size=5, brush=brushes, pen=None)
                    pw.addItem(sc)
                self._scatters.append(sc)
                # 클릭 판정은 산점도가 아니라 원본 전부로(솎아서 안 그려진 점도 집힌다)
                self._lane_hits[id(pw)] = (x, y, np.argsort(x, kind="stable"))
                self._hook_lane_click(pw)
                pw.setLabel("left", f"{g} (ppb)")
                fin = y[np.isfinite(y)]
                if fin.size:
                    stats.append(f"{g}: mu={float(np.mean(fin)):.3g}"
                                 f"+-{float(np.std(fin)):.2g} ppb")

            elif kind == "shsq":
                sh, sq = t.get("shift"), t.get("squeeze")
                if sh is not None:
                    _fast(pw.plot(x, sh, pen=pg.mkPen(_PALETTE[0], width=1.2), name="Shift (px)"))
                if sq is not None:
                    # squeeze는 1.0 근처라 shift(px)와 축이 다르다 → 1을 뺀 편차로 겹친다
                    _fast(pw.plot(x, np.asarray(sq, float) - 1.0,
                                  pen=pg.mkPen(_PALETTE[4], width=1.2), name="Squeeze - 1"))
                pw.setLabel("left", "Shift px / Sq-1")

            else:  # rms
                _fast(pw.plot(x, t["rms"], pen=pg.mkPen(_PALETTE[2], width=1.2), name="RMS"))
                pw.setLabel("left", "RMS (cm^-1)")
        self._hide_extra_lanes(n_lanes)

        # 스택을 쓰는 동안 예전 2단 플롯은 숨긴다(다른 종류 파일은 그쪽을 계속 쓴다)
        self._pw_top.hide()
        self._pw_bot.hide()
        self._stack_host.show()
        self._pw_detail.show()
        self._pw_resid.show()

        n_flag = {f: flags.count(f) for f in set(flags) if f != "ok"}
        flag_tag = ("  ·  " + " ".join(f"{k}:{v}" for k, v in sorted(n_flag.items()))
                    if n_flag else "")
        qc_tag = f" · QC hidden {n_hidden}" if n_hidden else ""
        self._lanes[0].setTitle(
            f"Fit - {os.path.basename(path)} ({len(x)} scans{qc_tag}){flag_tag}")

        # 구간선택이 켜져 있었으면 새 플롯에도 다시 부착
        if getattr(self, '_btn_region', None) and self._btn_region.isChecked():
            self._attach_region()

        self._stats_lbl.setText("   |   ".join(stats))

    def _hook_lane_thin(self, pw):
        """레인 범위·크기가 바뀌면 점을 다시 고르는 연결(레인당 한 번)."""
        if getattr(pw, "_lane_thin_hooked", False):
            return
        pw._lane_thin_hooked = True
        vb = pw.getViewBox()
        vb.sigRangeChanged.connect(lambda *_, pw=pw: self._rethin_lane(pw))
        vb.sigResized.connect(lambda *_, pw=pw: self._rethin_lane(pw))

    def _rethin_lane(self, pw, use_extent=False):
        from gui.pg_perf import thin_indices
        th = getattr(self, "_lane_thin", {}).get(id(pw))
        if not th or th.get("busy") or th["item"].scene() is None:
            return
        x, y = th["x"], th["y"]
        vb = pw.getViewBox()
        if use_extent:
            fx, fy = x[np.isfinite(x)], y[np.isfinite(y)]
            if not (fx.size and fy.size):
                return
            xr, yr = (float(fx.min()), float(fx.max())), (float(fy.min()), float(fy.max()))
        else:
            xr, yr = vb.viewRange()
        idx = thin_indices(x, y, xr, yr, vb.width() or 1200.0, vb.height() or 120.0,
                           cell_px=3.0, keep="last")
        th["busy"] = True
        try:
            th["item"].setData(x=x[idx], y=y[idx], brush=[th["brushes"][i] for i in idx],
                               size=5, pen=None)
        finally:
            th["busy"] = False

    def _hook_lane_click(self, pw):
        """레인 클릭 판정 연결(레인당 한 번 — 레인은 재사용되므로 연결이 쌓이지 않게)."""
        if getattr(pw, "_lane_click_hooked", False):
            return
        pw._lane_click_hooked = True
        pw.scene().sigMouseClicked.connect(lambda ev, pw=pw: self._on_lane_click(pw, ev))

    def _on_lane_click(self, pw, ev):
        """레인 클릭 → 화면상 8 px 안의 **실제 데이터 점** 중 가장 가까운 행을 아래 패널에.
        표시 좌표(x는 시간 시프트가 이미 들어간 값) 그대로 비교하므로 시프트 보정이 필요 없다.
        No `ev.isAccepted()` check: the flag ScatterPlotItem accepts every click on a point,
        so that check made the panel unreachable (2026-10-02 audit R1)."""
        from PyQt6.QtCore import Qt as _Qt
        if ev.button() != _Qt.MouseButton.LeftButton or ev.double():
            return
        hit = getattr(self, "_lane_hits", {}).get(id(pw))
        if hit is None or not self._fit_cache or self._path is None:
            return
        vb = pw.getViewBox()
        pos = ev.scenePos()
        if not vb.sceneBoundingRect().contains(pos):
            return
        j = self.lane_point_at(pw, vb.mapSceneToView(pos))
        if j is not None:
            self._show_scan_detail(j)

    def lane_point_at(self, pw, p):
        """레인 pw에서 데이터 좌표 p(QPointF) 근처(8 px)의 행 번호 — 없으면 None."""
        from gui.pg_perf import nearest_index
        hit = getattr(self, "_lane_hits", {}).get(id(pw))
        if hit is None:
            return None
        x, y, order = hit
        vb = pw.getViewBox()
        (x0, x1), (y0, y1) = vb.viewRange()
        sx = (x1 - x0) / max(vb.width(), 1.0)
        sy = (y1 - y0) / max(vb.height(), 1.0)
        return nearest_index(x, y, order, p.x(), p.y(), sx, sy)

    def _on_lane_points_clicked(self, *args):
        """레인의 점 클릭 → 아래 패널에 그 스캔의 상세. **시계열은 그대로 보인다.**

        예전엔 팝업이 떠서 창을 옮겨가며 봐야 했다. 그리고 클릭 위치에서 가장 가까운
        점을 x좌표로 되짚었는데, 이제 산점도가 **어느 점을 눌렀는지 직접** 알려주므로
        시간 시프트 보정·최근접 탐색이 통째로 사라졌다(오차 원인 하나 제거).
        """
        pts = None
        for a in args:
            if isinstance(a, (list, tuple)) and len(a):
                pts = a
                break
        t = self._fit_cache
        if not pts or not t or self._path is None:
            return
        try:
            j = int(pts[0].index())
        except Exception:
            return
        self._show_scan_detail(j)

    def _show_scan_detail(self, j):
        """행 j의 상세를 아래 패널에 그린다: α 스펙트럼 + 그 스캔의 수치 요약."""
        t = self._fit_cache
        self._pw_detail.clear()
        self._pw_resid.clear()
        self._pw_resid.setTitle("Residual - click a point above")
        try:
            row_idx = int(t["row_idx"][j])
        except Exception:
            return

        files = t.get("file")
        bits = [f"row {row_idx}"] + ([str(files[j])] if files is not None and j < len(files) else [])
        st = (t.get("status") or [None] * (j + 1))[j]
        if st:
            bits.append(str(st))
        if t.get("rms") is not None and np.isfinite(t["rms"][j]):
            bits.append(f"RMS {t['rms'][j]:.4g}")
        for k, lab in (("shift", "shift"), ("squeeze", "squeeze")):
            arr = t.get(k)
            if arr is not None and np.isfinite(arr[j]):
                bits.append(f"{lab} {arr[j]:.4g}")
        for g, y in (t.get("gases") or {}).items():
            if np.isfinite(y[j]):
                bits.append(f"{g} {y[j]:.4g}")

        alpha_path, wave, alpha, alpha_id, why = self._alpha_row(j)
        if alpha is None:
            # α가 없어도 수치 요약은 보여준다 — 클릭이 아무 반응 없는 것보다 낫다.
            self._pw_detail.setTitle("  ·  ".join(bits) + f"   |   {why} -> no spectrum")
            self._stats_lbl.setText(f"row {row_idx}: {why}")
            return
        xs = wave if (wave is not None and len(wave) == len(alpha)) else np.arange(len(alpha))
        self._pw_detail.plot(xs, alpha, pen=pg.mkPen(AUGUR.info, width=1.4),
                             name=f"alpha (row_idx {alpha_id})")
        self._pw_detail.setLabel("left", "alpha (cm^-1)")
        self._pw_detail.setLabel(
            "bottom", "Wavelength (nm)" if (wave is not None and len(wave) == len(alpha))
            else "Pixel")
        self._pw_detail.setTitle("  ·  ".join(bits))
        if why:            # spectrum found, but refit-by-row_idx would be ambiguous
            self._pw_resid.setTitle(f"Residual unavailable: {why}")
            return
        self._draw_residual(j, alpha_id, alpha_path)

    def _alpha_row(self, j):
        """α spectrum behind fit row j → (alpha_path, wave, alpha, alpha row_idx value, why).
        alpha is None when not found; `why` says what is missing (shown to the user).

        GUI report: the File cell names the source file and the data-row *position* the
        worker fit — the table's own row number is not an alpha row (2026-10-02 audit R2/R3).
        alpha-fit table (row_idx column): row_idx is the alpha file's row_idx value."""
        t = self._fit_cache
        files = t.get("file")
        if files is None:
            rid = int(t["row_idx"][j])
            path = self._sibling_alpha(self._path)
            if not path:
                return None, None, None, rid, "no sibling *_alpha_trace.dat"
            from gui.result_viewer_io import read_alpha_trace
            wave, alpha = read_alpha_trace(path, want_id=rid)
            return path, wave, alpha, rid, ("" if alpha is not None
                                            else f"row_idx {rid} not in {os.path.basename(path)}")
        from gui.result_viewer_io import parse_file_cell
        src = parse_file_cell(files[j] if j < len(files) else "")
        if src is None:
            return None, None, None, None, f"File cell {files[j]!r} names no source row"
        name, pos = src
        if "alpha_trace" not in name.lower():
            return None, None, None, None, f"source {name} is raw, not an alpha_trace"
        path = self._find_source(name)
        if path is None:
            return None, None, None, None, (f"{name} not found (looked next to the fit file, "
                                            "3 parent folders, last data/alpha folders)")
        from core.data_io import DataIO
        try:
            wave, alpha, _T, _P = DataIO.load_alpha_trace_row_full(path, pos)
            rows = DataIO._alpha_file(path)[2]      # same data-row list the worker indexed
        except Exception as e:                      # noqa: BLE001 — shown, not raised
            return None, None, None, None, f"{name} row {pos}: {e}"
        rid_s = rows[pos].split("\t", 1)[0]
        try:
            rid = int(float(rid_s))
        except ValueError:
            rid = None
        ids = [r.split("\t", 1)[0] for r in rows]
        why = ("" if rid is not None and ids.count(rid_s) == 1 else
               f"row_idx {rid_s!r} not unique in {name} - refit looks rows up by row_idx")
        return path, wave, alpha, rid, why

    def _find_source(self, name):
        """Locate a File-cell source by basename: fit folder, 3 parents, last data/alpha folders.
        The fit file itself is never a candidate."""
        from gui.dlg_dir import dlg_dir
        me = os.path.abspath(self._path)
        dirs, d = [], os.path.dirname(me)
        for _ in range(4):
            dirs.append(d)
            d = os.path.dirname(d)
        dirs += [dlg_dir("data"), dlg_dir("alpha_out")]
        for d in dirs:
            c = os.path.join(d, name) if d else ""
            if c and os.path.isfile(c) and os.path.abspath(c) != me:
                return c
        return None

    def _draw_residual(self, j, row_idx, alpha_path):
        """그 행을 **그때 설정(.meta.json)** 으로 재핏해 잔차를 그린다.

        저장된 결과 파일만으로는 잔차를 복원할 수 없다(`.dat`에 잔차 벡터도 핏 계수도
        없음) — 그래서 재핏한다. 다만 *지금* 설정으로 계산한 잔차는 화면의 *그때* 농도와
        대응하지 않으므로, 설정 복원이나 재현에 실패하면 **그리지 않고 사유만 적는다**
        (규칙·거부 5종은 `core/refit.py` 참조).
        """
        from core.refit import refit_row
        t = self._fit_cache

        def _v(key):
            arr = t.get(key)
            if arr is None or j >= len(arr) or not np.isfinite(arr[j]):
                return None
            return float(arr[j])

        saved = {g: float(y[j]) for g, y in (t.get("gases") or {}).items()
                 if j < len(y) and np.isfinite(y[j])}
        try:
            r = refit_row(self._path, alpha_path, row_idx, saved_conc=saved,
                          saved_shift=_v("shift"), saved_squeeze=_v("squeeze"))
        except Exception as e:                      # noqa: BLE001
            r = {"ok": False, "reason": "Residual unavailable: %s" % e}
        if not r.get("ok"):
            # 사유를 그대로 보여준다 — 빈 패널보다 "왜 없는지"가 중요하다.
            self._pw_resid.setTitle(r.get("reason") or "Residual unavailable")
            return

        x = np.asarray(r["wave"], dtype=float)
        self._pw_resid.plot(x, np.asarray(r["residual"], dtype=float),
                            pen=pg.mkPen(AUGUR.muted, width=1.2), name="residual")
        head = "Residual - RMS %.3g" % r["rms"]
        if r.get("rms_sig") is not None and np.isfinite(r["rms_sig"]):
            head += "  ·  rms/sig %.1f%%" % (r["rms_sig"] * 100)
        if r.get("runid"):
            head += "  ·  %s" % r["runid"]
        self._pw_resid.setTitle(head)
        # 모델을 α 위에 겹쳐 그린다 — "얼마나 맞았나"가 한 화면에서 보인다.
        self._pw_detail.plot(x, np.asarray(r["model"], dtype=float),
                             pen=pg.mkPen(AUGUR.fail, width=1.2,
                                          style=Qt.PenStyle.DashLine),
                             name="model (refit)")

    @staticmethod
    def _sibling_alpha(fit_path):
        """`*_fit.tsv` 옆의 대응 `*_alpha_trace.dat` 경로 추정 (never the fit file itself —
        the old `stem + ".dat"` candidate returned a `.dat` fit result as its own alpha)."""
        base = os.path.basename(fit_path)
        stem = base[:-8] if base.endswith("_fit.tsv") else os.path.splitext(base)[0]
        d = os.path.dirname(fit_path)
        cands = [os.path.join(d, stem + "_alpha_trace.dat")]
        import glob
        cands += glob.glob(os.path.join(d, stem + "*alpha_trace.dat"))
        me = os.path.abspath(fit_path)
        for c in cands:
            if os.path.isfile(c) and os.path.abspath(c) != me:
                return c
        return None

    def _show_alpha_popup(self, alpha_path, row_idx):
        """alpha_trace.dat에서 row_idx 행의 α 스펙트럼을 팝업으로 표시."""
        from gui.result_viewer_io import read_alpha_trace
        wave, target = read_alpha_trace(alpha_path, want_id=row_idx)
        if target is None:
            self._stats_lbl.setText(f"row {row_idx} not in alpha_trace")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"α spectrum — row {row_idx} ({os.path.basename(alpha_path)})")
        dlg.resize(720, 460)
        lay = QVBoxLayout(dlg)
        pw = pg.PlotWidget()
        pw.setBackground("w"); pw.showGrid(x=True, y=True, alpha=0.3)
        pw.plot(wave, target, pen=pg.mkPen(_PALETTE[1], width=1.5))
        pw.setLabel("left", "α (cm⁻¹)"); pw.setLabel("bottom", "Wavelength (nm)")
        pw.setTitle(f"α — row {row_idx}")
        lay.addWidget(pw)
        dlg.show()

    # ══════════════════════════════════════════════════════════════════
    # 구간선택 / 구간저장 / 병합 / 통계 / 일주기  (core.result_io 공용 로직)
    # ══════════════════════════════════════════════════════════════════
    def _primary_plot(self):
        """구간선택·범위 조작이 붙을 주 플롯. fit이면 첫 레인, 아니면 예전 상단 플롯."""
        if getattr(self, '_current_kind', None) == "fit" and getattr(self, '_lanes', None):
            return self._lanes[0]
        return self._pw_top

    def _attach_region(self):
        """현재 상단 플롯 x범위 가운데 1/3에 드래그 가능한 구간 핸들 부착."""
        if self._region is not None:
            try:
                self._primary_plot().removeItem(self._region)
                self._pw_top.removeItem(self._region)
            except Exception:
                pass
            self._region = None
        vb = self._primary_plot().getViewBox()
        (x0, x1), _ = vb.viewRange()
        a = x0 + (x1 - x0) / 3.0
        b = x0 + 2.0 * (x1 - x0) / 3.0
        # 시각 입력칸에 유효 범위가 있으면 그 위치로 핸들 시작
        try:
            ea = self._dt_from.dateTime().toSecsSinceEpoch()
            eb = self._dt_to.dateTime().toSecsSinceEpoch()
            if x0 <= ea < eb <= x1:
                a, b = ea, eb
        except Exception:
            pass
        self._region = pg.LinearRegionItem(values=(a, b), movable=True,
                                           brush=pg.mkBrush(33, 150, 243, 30))
        self._region.setZValue(50)
        self._region.sigRegionChanged.connect(self._on_region_dragged)
        self._primary_plot().addItem(self._region)
        self._on_region_dragged()   # 입력칸 즉시 동기

    def _toggle_region(self, on):
        if on:
            self._attach_region()
            self._stats_lbl.setText("Drag handles or type exact times, then [Export] / [Stats]")
        elif self._region is not None:
            for pw in [self._pw_top] + list(getattr(self, '_lanes', [])):
                try:
                    pw.removeItem(self._region)
                except Exception:
                    pass
            self._region = None

    def _set_range_edits(self, t0_epoch, t1_epoch, block=True):
        """시각 입력칸을 epoch초로 설정(신호 차단 옵션)."""
        from PyQt6.QtCore import QDateTime
        for de, ep in ((self._dt_from, t0_epoch), (self._dt_to, t1_epoch)):
            if not np.isfinite(ep):
                continue
            if block:
                de.blockSignals(True)
            de.setDateTime(QDateTime.fromSecsSinceEpoch(int(ep)))
            if block:
                de.blockSignals(False)

    def _on_range_edited(self):
        """시각 직접 입력 → 드래그 핸들 동기."""
        if self._region is not None:
            a = self._dt_from.dateTime().toSecsSinceEpoch()
            b = self._dt_to.dateTime().toSecsSinceEpoch()
            if a < b:
                self._region.blockSignals(True)
                self._region.setRegion((a, b))
                self._region.blockSignals(False)

    def _on_region_dragged(self):
        """드래그 핸들 → 시각 입력칸 동기."""
        if self._region is not None:
            a, b = self._region.getRegion()
            self._set_range_edits(min(a, b), max(a, b))

    def _region_times(self):
        """Export/Stats 기준 시간범위 → (datetime t0, t1).
        시각 입력칸이 진실원(드래그와 동기). 전체범위와 같으면 (None,None)=전체."""
        t = self._fit_cache
        if not t or t.get("time") is None:
            return None, None
        try:
            a = self._dt_from.dateTime().toSecsSinceEpoch()
            b = self._dt_to.dateTime().toSecsSinceEpoch()
        except Exception:
            return None, None
        if self._time_shift_hours:
            # 입력칸은 표시(시프트된) 시각 기준 — 원본 파일 시각으로 되돌려서 비교/반환.
            off = self._time_shift_hours * 3600.0
            a -= off; b -= off
        if a >= b:
            return None, None
        tt = t["time"]
        fin = tt[np.isfinite(tt)]
        if fin.size and a <= fin.min() and b >= fin.max():
            return None, None     # 전체 범위 = 슬라이스 불필요
        try:
            return datetime.fromtimestamp(a), datetime.fromtimestamp(b)
        except (OSError, OverflowError, ValueError):
            return None, None

    def _selected_paths(self):
        """목록에서 선택된 파일 경로들(없으면 현재 파일)."""
        paths = []
        for it in self._list.selectedItems():
            data = it.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and data[0] == "file" and os.path.isfile(data[1]):
                paths.append(data[1])
        if not paths and self._path:
            paths = [self._path]
        return paths

    def _to_plot_maker(self):
        """선택(없으면 현재) 결과파일을 Plot Maker 선반으로 보낸다.

        경로만 보내면 보던 상태(Hide QC·K·구간·시프트)가 증발한다. 그렇다고 메모리
        배열을 넘기면 Plot Maker 설정을 다시 열 때 재현이 안 된다(원칙 ④). → 경로 +
        재계산 가능한 규칙을 보낸다. 숨김은 삭제가 아니므로 Plot Maker에서 끌 수 있다."""
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "Plot Maker", "Open a result file to send first.")
            return
        rules = self.view_rules()
        self.send_to_plotmaker.emit([{"path": p, "rules": [dict(r) for r in rules],
                                      "shift_h": float(self._time_shift_hours)}
                                     for p in paths])

    def _bake_qc_into_rows(self, colhdr, rows):
        """현재 K>0이면 사후 QC 초과 행의 가스 컬럼을 nan + Status=QC-Auto로 바꾼다.
        반환: (rows, 바꾼 행 수). K=0이면 그대로.

        The mask comes from `qc_hidden_mask` - the same function the screen uses - over
        **all** rows passed in. Callers pass the whole file(s) *before* slicing to the range,
        so the threshold population matches the screen (2026-10-02 audit R6: the old copy
        recomputed thresholds on the sliced rows → 28 rows excluded vs 6 on screen)."""
        K = self._spin_qc_k.value() if hasattr(self, '_spin_qc_k') else 0.0
        if K <= 0 or not rows:
            return rows, 0
        cols = colhdr.split('	')
        idx = {c: i for i, c in enumerate(cols)}
        if 'RMS' not in idx:
            return rows, 0
        ri = idx['RMS']; ci = idx.get('Channel'); si = idx.get('Status')
        # 가스 컬럼 탐지: {gas}_Error 우선(QC/Kalman 무관 항상 존재 — load_fit_table과
        # 동일 규칙. 병렬핏 결과는 _Smooth가 없어 구 탐지가 빈손이었음) → _Smooth →
        # 알려진 종 이름 폴백.
        gases = ([c for c in cols if (c + '_Error') in idx]
                 or [c for c in cols if (c + '_Smooth') in idx]
                 or [c for c in cols if c in ('NO2', 'CHOCHO', 'H2O', 'O4', 'HONO', 'HCHO')])
        gidx = [idx[g] for g in gases] + [idx[g + '_Smooth'] for g in gases if (g + '_Smooth') in idx]
        parts = [line.split('	') for _t, line in rows]
        rv = np.array([float(p[ri]) if ri < len(p) and p[ri].strip() else np.nan
                       for p in parts], dtype=float)
        ch = ([p[ci] if ci < len(p) else '' for p in parts] if ci is not None else None)
        mask = qc_hidden_mask(len(rows), rms=rv, channel=ch, K=K)
        out = []
        for (t, line), p, m in zip(rows, parts, mask):
            if m:
                for j in gidx:
                    if j < len(p):
                        p[j] = 'nan'
                if si is not None and si < len(p):
                    p[si] = f'QC-Auto(K={K:g})'
                line = '	'.join(p)
            out.append((t, line))
        return out, int(mask.sum())

    def _provenance_lines(self, paths, sliced=True):
        """What the viewer did to produce an Export/Merge file (principle 4). The copied input
        header (e.g. "Auto QC K=8", its Code Version) describes the input, not this file."""
        K = self._spin_qc_k.value()
        t0, t1 = self._region_times() if sliced else (None, None)
        return ([f"viewer post-hoc QC K={K:g}"
                 + (" (gas values of rows above the threshold set to nan, Status QC-Auto; "
                    "supersedes any Auto QC K in the header above)" if K > 0 else " (off)"),
                 f"viewer Hide QC {'ON' if self._chk_hide_qc.isChecked() else 'OFF'} "
                 "(display only - rows and Status kept)",
                 "range " + (f"{t0:%Y-%m-%d %H:%M:%S} ~ {t1:%Y-%m-%d %H:%M:%S}" if t0 else "all")
                 + (" (file times)" if sliced else " (Merge ignores the range)"),
                 f"display time shift {self._time_shift_hours:+g} h (NOT applied - times as in input)"]
                + [f"input {os.path.abspath(p)}" for p in paths])

    def _build_export(self, paths):
        """Merge → post-hoc QC on the whole set (as on screen) → slice to the range.
        Returns (comments, colhdr, rows, n_in, nq-in-range). ValueError if nothing to write."""
        from core.result_io import merge_results, slice_rows
        comments, colhdr, rows, _ndup = merge_results(paths)
        n_in = len(rows)
        rows, _ = self._bake_qc_into_rows(colhdr, rows)    # 사후 QC(K>0) — 전체 기준
        t0, t1 = self._region_times()
        rows = slice_rows(rows, t0, t1)
        if not rows:
            raise ValueError("No data in the selected range.")
        K = self._spin_qc_k.value()
        tag = f"QC-Auto(K={K:g})"
        si = colhdr.split('	').index('Status') if 'Status' in colhdr.split('	') else None
        nq = (sum(1 for _t, ln in rows if si is not None and (ln.split('	') + [''] * (si + 1))[si] == tag)
              if K > 0 else 0)
        return comments, colhdr, rows, n_in, nq

    def _export_region(self):
        """선택구간(없으면 전체)을 result_io로 잘라 새 파일로 저장.
        목록에서 여러 파일 선택 시 병합 후 자름."""
        if getattr(self, '_current_kind', None) == 'concentration':
            self._export_concentration_shifted()
            return
        from core.result_io import write_result, bucketed_out_name
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "Export", "Open a result file first.")
            return
        try:
            comments, colhdr, rows, n_in, nq = self._build_export(paths)
        except ValueError as e:
            QMessageBox.warning(self, "Export", str(e))
            return
        # 자동 저장경로: 날짜/neg/QC 버킷(GUI save와 동일). neg·QC는 입력 # 헤더에서 상속,
        # 뷰어가 사후 QC 재적용(K>0)했으면 그 K로 QC 버킷 덮어씀.
        _kv = self._spin_qc_k.value()
        qc_override = f"QCk{_kv:g}" if _kv > 0 else None
        suggest = bucketed_out_name(paths[0], rows, comments, kind='slice',
                                    ext=os.path.splitext(paths[0])[1] or '.dat',
                                    qc_override=qc_override)
        out, _ = QFileDialog.getSaveFileName(self, "Export range", suggest,
                                             "Data (*.dat *.tsv);;All (*)")
        if not out:
            return
        _d = os.path.dirname(out)
        if _d:
            os.makedirs(_d, exist_ok=True)
        write_result(out, comments, colhdr, rows,
                     note=f"{len(paths)} file(s), {n_in}→{len(rows)} rows, QC-excluded {nq} (viewer export)",
                     extra=self._provenance_lines(paths))
        qmsg = f" · QC excluded {nq}" if nq else ""
        self._stats_lbl.setText(
            f"Saved: {os.path.basename(out)}  ({len(rows)} rows{qmsg}, "
            f"{rows[0][0]:%m-%d %H:%M} ~ {rows[-1][0]:%m-%d %H:%M})")

    @classmethod
    def _shifted_concentration_df(cls, path, shift_h):
        """Concentration CSV with **every** time column shifted by shift_h hours, or None if the
        first column is not a time. A shifted column must not keep its timezone label
        (2026-10-02 audit R10: UTC values went out under `time_KST`, and only the first time
        column moved): KST −9 h → UTC, UTC +9 h → KST, anything else gets `_shift±Nh`."""
        import pandas as pd
        sep = cls._detect_sep(path) or r"\s+"
        df = pd.read_csv(path, sep=sep, comment="#", engine="python", encoding="utf-8-sig")
        times = {}
        for c in df.columns:
            if pd.api.types.is_numeric_dtype(df[c]):   # numbers would parse as epoch-ns "times"
                continue
            dt = pd.to_datetime(df[c], errors="coerce")
            if dt.notna().mean() > 0.5:
                times[c] = dt
        if df.columns[0] not in times:
            return None
        out = df.copy()
        if not shift_h:
            return out
        names = {}
        for c, dt in times.items():
            out[c] = (dt + pd.Timedelta(hours=shift_h)).dt.strftime("%Y-%m-%d %H:%M:%S")
            s = str(c)
            if shift_h == -9 and "KST" in s:
                names[c] = s.replace("KST", "UTC")
            elif shift_h == 9 and "UTC" in s:
                names[c] = s.replace("UTC", "KST")
            else:
                names[c] = f"{s}_shift{shift_h:+g}h"
        taken = set(map(str, out.columns))
        for c, n in list(names.items()):       # never collide with an existing column name
            if n in taken and n != str(c):
                names[c] = f"{c}_shift{shift_h:+g}h"
        return out.rename(columns=names)

    def _export_concentration_shifted(self):
        """Concentration 종류(계산기 CSV 등)는 fit용 merge_results/slice_rows 포맷과
        안 맞아 여기서 따로 처리 — 원본을 다시 읽어 time 컬럼에 현재 Time shift만
        반영해 그대로 새 CSV로 저장(구간선택 없이 전체, 시프트=0이면 사본).
        보정 사실은 파일 첫 줄에 남겨 무엇이 바뀌었는지 항상 드러낸다."""
        path = self._path
        if not path:
            QMessageBox.information(self, "Export", "Open a result file first.")
            return
        shift_h = self._time_shift_hours
        out_df = self._shifted_concentration_df(path, shift_h)
        if out_df is None:
            QMessageBox.warning(self, "Export", "No time column found to shift/save.")
            return
        base, ext = os.path.splitext(path)
        tag = f"_shift{shift_h:+g}h" if shift_h else "_copy"
        suggest = f"{base}{tag}{ext or '.csv'}"
        out, _ = QFileDialog.getSaveFileName(self, "Export (time-shifted)", suggest,
                                             "CSV (*.csv);;All (*)")
        if not out:
            return
        _d = os.path.dirname(out)
        if _d:
            os.makedirs(_d, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="") as f:
            from core.provenance import code_version
            f.write(f"# source: {os.path.abspath(path)}\n")
            f.write(f"# exporter code {code_version()} (Result Lab concentration export, "
                    f"{datetime.now():%Y-%m-%d %H:%M})\n")
            if shift_h:
                f.write(f"# time shifted by {shift_h:+g}h vs. source (Result Lab manual correction)\n")
            out_df.to_csv(f, index=False)
        shift_msg = f" · shift {shift_h:+g}h" if shift_h else ""
        self._stats_lbl.setText(f"Saved: {os.path.basename(out)} ({len(out_df)} rows{shift_msg})")

    def _merge_files(self):
        """목록에서 선택한 같은 형식 결과파일들을 시간순 병합 저장."""
        from core.result_io import merge_results, write_result
        paths = self._selected_paths()
        if len(paths) < 2:
            QMessageBox.information(self, "Merge",
                                    "Select 2+ result files in the list (Ctrl+click).")
            return
        try:
            comments, colhdr, rows, ndup = merge_results(paths)
        except ValueError as e:
            QMessageBox.warning(self, "Merge", str(e))
            return
        rows, nq = self._bake_qc_into_rows(colhdr, rows)   # 사후 QC(K>0) 반영
        from core.result_io import bucketed_out_name
        ext = os.path.splitext(paths[0])[1] or '.dat'
        # 자동 저장경로: 날짜/neg/QC 버킷(GUI save와 동일). neg·QC는 첫 입력 # 헤더에서 상속,
        # 뷰어가 사후 QC 재적용(K>0)했으면 그 K로 QC 버킷 덮어씀.
        _kv = self._spin_qc_k.value()
        qc_override = f"QCk{_kv:g}" if _kv > 0 else None
        sug = bucketed_out_name(paths[0], rows, comments, kind='merge', nfiles=len(paths),
                                ext=ext, qc_override=qc_override)
        out, _ = QFileDialog.getSaveFileName(self, "Merge save", sug,
                                             "Data (*.dat *.tsv);;All (*)")
        if not out:
            return
        _d = os.path.dirname(out)
        if _d:
            os.makedirs(_d, exist_ok=True)
        write_result(out, comments, colhdr, rows,
                     note=f"merged {len(paths)} files, {ndup} dups removed, QC-excluded {nq} (viewer)",
                     extra=self._provenance_lines(paths, sliced=False))
        dmsg = (f" · {ndup} dups" if ndup else "") + (f" · QC {nq}" if nq else "")
        self._stats_lbl.setText(f"Merged: {os.path.basename(out)} ({len(rows)} rows{dmsg})")

    def _stats_arrays(self):
        """현재 fit 캐시에서 (QC숨김·구간 반영) 선택마스크 반환. Only while a fit is open —
        _fit_cache may hold an earlier file (2026-10-02 audit R8: CSV open, stats of old fit)."""
        t = self._fit_cache
        if not t or getattr(self, "_current_kind", None) != "fit":
            return None, None
        hide = self._qc_mask(t)
        sel = np.ones(len(t["row_idx"]), bool) & ~hide
        t0, t1 = self._region_times()
        if t0 is not None and t.get("time") is not None:
            tt = t["time"]
            sel &= np.isfinite(tt) & (tt >= t0.timestamp()) & (tt <= t1.timestamp())
        return t, sel

    def _show_stats(self):
        lines = self._stats_lines()
        if lines is None:
            QMessageBox.information(self, "Stats", "Open a fit result first.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Stats (ppb)")
        dlg.resize(720, 380)
        lay = QVBoxLayout(dlg)
        ed = QPlainTextEdit("\n".join(lines))
        ed.setReadOnly(True)
        ed.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        lay.addWidget(ed)
        dlg.show()

    def _stats_lines(self):
        """Stats table lines for the open fit result, or None when no fit is open."""
        t, sel = self._stats_arrays()
        if t is None:
            return None
        t0, t1 = self._region_times()
        rng = (f"{t0:%Y-%m-%d %H:%M} ~ {t1:%Y-%m-%d %H:%M}" if t0 else "all")
        lines = [f"File: {os.path.basename(t['path'])}",
                 f"Range: {rng}   (Hide QC {'ON' if self._chk_hide_qc.isChecked() else 'OFF'})",
                 "",
                 f"{'gas':<10} {'n':>6} {'mean':>9} {'median':>9} {'σ':>8} {'min':>8} {'max':>8}"
                 f"  {'trend /h':>10} {'± SE':>8}"]
        from gui.ui_plot_maker.processing import trend_per_hour   # 구간 즉석 추세(직선)
        tt = t.get("time")
        for g, y in t["gases"].items():
            v = y[sel]
            v = v[np.isfinite(v)]
            if v.size == 0:
                lines.append(f"{g:<10} {0:>6}")
                continue
            tr = trend_per_hour(tt[sel], y[sel]) if tt is not None else None
            trs = f"  {tr[0]:>10.4g} {tr[1]:>8.2g}" if tr else ""
            # %g, not %f: H2O sits near 1e-13 and printed as 0.000 everywhere (R8/R20)
            lines.append(f"{g:<10} {v.size:>6} {np.mean(v):>9.3g} {np.median(v):>9.3g} "
                         f"{np.std(v):>8.3g} {np.min(v):>8.3g} {np.max(v):>8.3g}{trs}")
        r = t["rms"][sel]
        r = r[np.isfinite(r)]
        if r.size:
            lines.append("")
            lines.append(f"RMS median {np.median(r):.3e} / p95 {np.percentile(r, 95):.3e}")
        lines.append("")
        lines.append("trend = straight-line slope over the range (ppb per hour). ± SE assumes "
                     "independent residuals —")
        lines.append("with autocorrelated data (most time series) the real uncertainty is larger.")
        return lines

    def _export_png(self):
        """현재 화면의 그래프를 고해상도(폭 2400px) PNG 합본으로 저장."""
        base = os.path.splitext(os.path.basename(self._path or 'plot'))[0]
        out, _ = QFileDialog.getSaveFileName(self, "Export high-res PNG",
                                             f"{base}.png", "PNG (*.png)")
        if not out:
            return
        if not out.lower().endswith('.png'):
            out += '.png'
        try:
            n = self._save_png(out)
        except Exception as e:
            QMessageBox.warning(self, "PNG export", f"Failed: {e}")
            return
        if not n:
            QMessageBox.warning(self, "PNG export", "No plot is shown - nothing saved.")
            return
        self._stats_lbl.setText(f"PNG saved: {os.path.basename(out)} ({n} plot(s), 2400px)")

    def _save_png(self, out):
        """Stack the plots currently on screen into one 2400 px PNG. Returns how many plots.
        A fit result lives in the lane stack - the old code exported the hidden `_pw_top`
        (a blank 2400x37 strip) and still reported "saved" (2026-10-02 audit R7)."""
        import pyqtgraph.exporters as pgex
        from PyQt6.QtGui import QImage, QPainter
        if getattr(self, '_current_kind', None) == "fit":
            plots = [pw for pw in self._lanes if not pw.isHidden()]
        else:
            plots = [pw for pw in (self._pw_top, self._pw_bot) if not pw.isHidden()]
        imgs = []
        for pw in plots:
            ex = pgex.ImageExporter(pw.plotItem)
            ex.parameters()['width'] = 2400
            imgs.append(ex.export(toBytes=True))   # QImage
        if not imgs:
            return 0
        wmax = max(im.width() for im in imgs)
        htot = sum(im.height() for im in imgs)
        combo = QImage(wmax, htot, QImage.Format.Format_ARGB32)
        combo.fill(0xFFFFFFFF)
        p = QPainter(combo)
        y = 0
        for im in imgs:
            p.drawImage(0, y, im)
            y += im.height()
        p.end()
        combo.save(out)
        return len(imgs)
