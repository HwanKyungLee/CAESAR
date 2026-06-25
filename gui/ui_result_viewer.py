"""결과 뷰어 (Result Viewer)
===========================
파이프라인이 저장한 결과 파일을 GUI에 다시 넣어 바로 볼 수 있게 하는 탭.

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
                                  read_numeric, detect_sep, load_fit_table)
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
_PALETTE = ["#2196F3", "#FF6F00", "#D32F2F", "#388E3C", "#7B1FA2",
            "#0097A7", "#C2185B", "#5D4037"]


class ResultViewerWidget(QWidget):
    """저장된 결과 파일을 불러와 종류를 자동 판별하고 알맞은 그래프로 표시."""

    # 선택/현재 파일들을 Plot Maker 선반으로 보내달라는 신호(app_window가 연결)
    send_to_plotmaker = pyqtSignal(list)

    # 순수 파서는 gui/result_viewer_io.py 로 분리, self._x(...) 호출 유지를 위해 재바인딩
    _load_result_time_gas = staticmethod(load_result_time_gas)
    _detect               = staticmethod(detect)
    _read_numeric         = staticmethod(read_numeric)
    _detect_sep           = staticmethod(detect_sep)
    _load_fit_table       = staticmethod(load_fit_table)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = None
        self._region = None      # pg.LinearRegionItem (구간선택)
        self._init_ui()

    # ──────────────────────────────────────────────────────────────
    def _init_ui(self):
        from gui.flow_layout import FlowLayout
        root = QVBoxLayout(self)

        # ── 툴바 1줄: [열기] | [보기] ────────────────────────────────────
        def _sep():
            s = QLabel("|")
            s.setStyleSheet("color:#bbb; padding:0 4px;")
            return s

        def _grp(text):
            l = QLabel(text)
            l.setStyleSheet("color:#888; font-weight:bold;")
            return l

        bar = FlowLayout(spacing=6)
        bar.addWidget(_grp("Open"))
        self._btn = QPushButton("📂 File")
        self._btn.clicked.connect(self._open)
        bar.addWidget(self._btn)
        self._btn_folder = QPushButton("📁 Folder")
        self._btn_folder.clicked.connect(self._open_folder)
        bar.addWidget(self._btn_folder)
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

        root.addLayout(bar)

        self._lbl = QLabel("Open a result file or folder.")
        self._lbl.setStyleSheet("color:#666;")
        # 긴 상태문구가 툴바 최소폭을 강제(→그래프 잘림)하지 않게 가로 Ignored
        from PyQt6.QtWidgets import QSizePolicy
        self._lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self._lbl)

        # ── 툴바 2줄: [분석] | [내보내기] (Overlay·Diurnal은 Plot Maker로 이관) ──
        fbar = FlowLayout(spacing=6)
        fbar.addWidget(_grp("Analyze"))
        self._btn_td = QPushButton("🧪 NO2/PNs/ANs")
        self._btn_td.setToolTip("Select 3 results (Cold / PNs ROI1 / ANs ROI2) → time-align & difference:\n"
                                "NO2=Cold, PNs=PNs−Cold, ANs=ANs−PNs")
        self._btn_td.clicked.connect(self._derive_no2_pns_ans)
        fbar.addWidget(self._btn_td)
        self._btn_stats = QPushButton("Σ Stats")
        self._btn_stats.setToolTip("Per-gas mean/median/σ/n for current fit (range-aware)")
        self._btn_stats.clicked.connect(self._show_stats)
        fbar.addWidget(self._btn_stats)
        self._btn_to_pm = QPushButton("📉 To Plot Maker")
        self._btn_to_pm.setToolTip("선택(없으면 현재) 파일을 Plot Maker 선반으로 보내\n"
                                   "겹쳐비교·Diurnal·산점도 등 자유 합성")
        self._btn_to_pm.clicked.connect(self._to_plot_maker)
        fbar.addWidget(self._btn_to_pm)

        fbar.addWidget(_sep())
        fbar.addWidget(_grp("Export"))
        self._btn_region = QPushButton("⏱ Range")
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
        self._btn_slice = QPushButton("✂ Export")
        self._btn_slice.setToolTip("Save the time range (or all) as a new result file.\n"
                                   "Multiple selected files in the list are merged first.")
        self._btn_slice.clicked.connect(self._export_region)
        fbar.addWidget(self._btn_slice)
        self._btn_merge = QPushButton("🔗 Merge")
        self._btn_merge.setToolTip("Merge selected same-format result files in time order")
        self._btn_merge.clicked.connect(self._merge_files)
        fbar.addWidget(self._btn_merge)
        self._btn_td_save = QPushButton("💾 Save TD")
        self._btn_td_save.setToolTip("Save computed NO2/PNs/ANs (+raw channel NO2) as TSV")
        self._btn_td_save.setEnabled(False)
        self._btn_td_save.clicked.connect(self._save_td_result)
        fbar.addWidget(self._btn_td_save)
        self._btn_png = QPushButton("📷 PNG")
        self._btn_png.setToolTip("Export current plots as high-resolution PNG (2400 px wide,\n"
                                 "top+bottom combined). For papers/reports.")
        self._btn_png.clicked.connect(self._export_png)
        fbar.addWidget(self._btn_png)

        self._stats_lbl = QLabel("")
        self._stats_lbl.setStyleSheet("color:#444;")
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
        hsplit.addWidget(self._list)

        self._fit_cache = None   # 최근 로드한 fit 테이블(포인트클릭 α 팝업용)

        psplit = QSplitter(Qt.Orientation.Vertical)
        self._pw_top = pg.PlotWidget()
        self._pw_bot = pg.PlotWidget()
        for pw in (self._pw_top, self._pw_bot):
            pw.setBackground('w')
            pw.showGrid(x=True, y=True, alpha=0.3)
            pw.addLegend(offset=(10, 10))
        psplit.addWidget(self._pw_top)
        psplit.addWidget(self._pw_bot)
        psplit.setSizes([400, 250])
        hsplit.addWidget(psplit)
        hsplit.setSizes([240, 780])
        root.addWidget(hsplit, 1)

    # ── NO2 / PNs / ANs 유도 농도 (TD-CEAS) ──────────────────────────

    def _derive_no2_pns_ans(self):
        """Cold/PNs/ANs 결과 3개 → 시간정렬·차분 → NO2/PNs/ANs 유도농도 플롯.
        NO2=Cold, PNs=PNs채널−Cold, ANs=ANs채널−PNs채널."""
        from PyQt6.QtWidgets import QMessageBox
        from gui.dlg_dir import dlg_dir
        paths = {}
        for role, title in (('Cold', "① Select Cold result (NO2)"),
                            ('PNs', "② Select PNs (ROI1, 180°C) result"),
                            ('ANs', "③ Select ANs (ROI2, 300°C) result")):
            p, _ = QFileDialog.getOpenFileName(self, title, dlg_dir("result"),
                                               "Results (*.dat *.csv *.tsv *.txt);;All Files (*)")
            if not p:
                return
            dlg_dir("result", p); paths[role] = p
        try:
            ct, cn = self._load_result_time_gas(paths['Cold'])
            pt, pn = self._load_result_time_gas(paths['PNs'])
            at, an = self._load_result_time_gas(paths['ANs'])
        except Exception as e:
            QMessageBox.warning(self, "Load failed", str(e)); return
        if ct is None or len(ct) < 2:
            QMessageBox.warning(self, "Insufficient data", "Cold result lacks Time/NO2."); return
        # 시간정렬: PNs/ANs 채널 NO2를 Cold 시각격자에 보간(범위 밖은 NaN)
        pn_i = np.interp(ct, pt, pn, left=np.nan, right=np.nan) if len(pt) >= 2 else np.full_like(ct, np.nan)
        an_i = np.interp(ct, at, an, left=np.nan, right=np.nan) if len(at) >= 2 else np.full_like(ct, np.nan)
        no2 = cn
        pns = pn_i - cn
        ans = an_i - pn_i

        # 저장용 보관(시각 epoch + 유도농도 + 원시 채널 NO2)
        self._td_data = {'epoch': ct, 'NO2': no2, 'PNs': pns, 'ANs': ans,
                         'Cold_NO2': cn, 'PNsCh_NO2': pn_i, 'ANsCh_NO2': an_i,
                         'sources': {k: os.path.basename(v) for k, v in paths.items()}}
        if hasattr(self, '_btn_td_save'):
            self._btn_td_save.setEnabled(True)

        # 위: 유도농도(NO2/PNs/ANs), 아래: 원시 채널 NO2
        ax1 = pg.DateAxisItem(orientation='bottom')
        self._pw_top.setAxisItems({'bottom': ax1})
        self._pw_top.clear()
        self._pw_top.addLegend(offset=(10, 10))
        self._pw_top.plot(ct, no2, pen=pg.mkPen('#1f77b4', width=2), name='NO2 (Cold)')
        self._pw_top.plot(ct, pns, pen=pg.mkPen('#ff7f0e', width=2), name='PNs (=PNs−Cold)')
        self._pw_top.plot(ct, ans, pen=pg.mkPen('#2ca02c', width=2), name='ANs (=ANs−PNs)')
        self._pw_top.setLabel('left', 'Concentration (ppb)')
        self._pw_top.setLabel('bottom', 'Time')

        ax2 = pg.DateAxisItem(orientation='bottom')
        self._pw_bot.setAxisItems({'bottom': ax2})
        self._pw_bot.clear()
        self._pw_bot.addLegend(offset=(10, 10))
        self._pw_bot.plot(ct, cn, pen=pg.mkPen('#1f77b4'), name='Cold NO2')
        self._pw_bot.plot(ct, pn_i, pen=pg.mkPen('#ff7f0e'), name='PNs channel NO2')
        self._pw_bot.plot(ct, an_i, pen=pg.mkPen('#2ca02c'), name='ANs channel NO2')
        self._pw_bot.setLabel('left', 'Channel NO2 (ppb)')
        self._pw_bot.setLabel('bottom', 'Time')
        self._lbl.setText("🧪 NO2=Cold, PNs=PNs−Cold, ANs=ANs−PNs (aligned to Cold time grid). "
                          "Negatives = noise/time mismatch.")
        self._lbl.setStyleSheet("color:#1565C0;")
        # 계산 직후 저장까지 한 흐름으로 (별도 버튼 클릭 불필요)
        if QMessageBox.question(self, "Save TD result",
                                "NO2/PNs/ANs computed. Save to TSV now?",
                                QMessageBox.StandardButton.Yes
                                | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._save_td_result()

    def _save_td_result(self):
        """유도농도(NO2/PNs/ANs) + 원시 채널 NO2를 TSV로 저장."""
        from PyQt6.QtWidgets import QMessageBox
        from gui.dlg_dir import dlg_dir
        from datetime import datetime
        d = getattr(self, '_td_data', None)
        if not d:
            QMessageBox.warning(self, "No data", "Compute NO2/PNs/ANs first."); return
        # 자동 파일명: NO2-PNs-ANs_{날짜범위}_[소스라벨].dat
        ep = d['epoch']
        from datetime import datetime as _dt
        rng = ""
        try:
            t0, t1 = _dt.fromtimestamp(float(ep[0])), _dt.fromtimestamp(float(ep[-1]))
            rng = f"{t0:%y%m%d}-{t1:%y%m%d}" if t0.date() != t1.date() else f"{t0:%y%m%d}"
        except Exception:
            pass
        import re as _re
        srcs = d.get('sources', {})
        def _chan(fn, role):
            m = _re.search(r'(cold|CH[123]|PNs|ANs|roi[123])', fn, _re.I)
            return m.group(1) if m else role
        slab = "+".join(_chan(srcs[k], k) for k in ('Cold', 'PNs', 'ANs') if k in srcs)
        auto = f"NO2-PNs-ANs_{rng}_[{slab}].dat" if rng else "NO2-PNs-ANs.dat"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save derived concentrations",
            os.path.join(dlg_dir("result") or "", auto),
            "Data (*.dat *.csv *.tsv);;All (*)")
        if not path:
            return
        dlg_dir("result", path)
        sep = ',' if path.lower().endswith('.csv') else '\t'
        cols = ['datetime', 'NO2', 'PNs', 'ANs', 'Cold_NO2', 'PNsCh_NO2', 'ANsCh_NO2']
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write("# CAESAR Pro derived concentrations (ppb)\n")
                f.write("# NO2=Cold, PNs=PNsCh-Cold, ANs=ANsCh-PNsCh (aligned to Cold time grid)\n")
                f.write(f"# sources: Cold={srcs.get('Cold','?')}  PNs={srcs.get('PNs','?')}  ANs={srcs.get('ANs','?')}\n")
                f.write(sep.join(cols) + "\n")
                ep = d['epoch']
                for i in range(len(ep)):
                    try:
                        dt = datetime.fromtimestamp(float(ep[i])).strftime('%Y-%m-%d %H:%M:%S')
                    except (OSError, ValueError, OverflowError):
                        dt = str(ep[i])
                    row = [dt] + [f"{d[c][i]:.4f}" if np.isfinite(d[c][i]) else "" for c in cols[1:]]
                    f.write(sep.join(row) + "\n")
            QMessageBox.information(self, "Saved", f"Derived concentration saved:\n{os.path.basename(path)}  ({len(d['epoch'])} rows)")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

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
            up = QListWidgetItem("📁  ..")
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
            it = QListWidgetItem(f"📁  {os.path.basename(p)}/   ({nfile})")
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
            it = QListWidgetItem(f"📄  {os.path.basename(f)}   [{_KIND_KO.get(k, k)}]")
            it.setData(Qt.ItemDataRole.UserRole, ("file", f))
            self._list.addItem(it)
        self._lbl.setText(f"📁 {os.path.basename(d) or d}  —  {len(subdirs)} folders · {len(files)} files"
                          + ("  (double-click folder to enter)" if subdirs else ""))
        self._lbl.setStyleSheet("color:#1565C0;")

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

    def _reload(self):
        if not self._path:
            return
        forced = _KIND_BY_LABEL.get(self._combo.currentText(), "auto")
        kind = self._detect(self._path) if forced == "auto" else forced
        self._pw_top.clear()
        self._pw_bot.clear()
        self._pw_bot.show()
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
            self._lbl.setText(f"✅ {os.path.basename(self._path)}  —  {_KIND_KO.get(kind, kind)}{auto}")
            self._lbl.setStyleSheet("color:#1565C0;")
        except Exception as e:
            self._lbl.setText(f"❌ Failed to display: {e}  (try selecting Type manually)")
            self._lbl.setStyleSheet("color:#C62828;")

    # ── 자동 판별 ──────────────────────────────────────────────────

    # ── 공통: 구분자 추정 후 숫자 표 읽기 ──────────────────────────


    @staticmethod
    def _set_time_axis(pw, on: bool):
        ax = pg.DateAxisItem(orientation="bottom") if on else pg.AxisItem(orientation="bottom")
        pw.setAxisItems({"bottom": ax})

    # ── R 트렌드 (.dat) → R/Leff 시계열 ────────────────────────────
    def _plot_r_trend(self, path):
        ts, rmean, rstd, leff = [], [], [], []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
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
        wave = None
        rows = []
        alpha_start = 3   # 'px' 헤더에서 정함(구:3, 신:5 — doy/datetime 추가)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                if ln.startswith("# wavelength_nm:"):
                    try:
                        wave = np.array([float(v) for v in ln.split(":", 1)[1].strip().split("\t")
                                         if v.strip()], dtype=float)
                    except Exception:
                        pass
                    continue
                if ln.lower().startswith("row_idx"):
                    cols = ln.rstrip("\n").split("\t")
                    fp = next((i for i, c in enumerate(cols) if c.startswith("px")), None)
                    if fp is not None:
                        alpha_start = fp
                    continue
                if ln.startswith("#"):
                    continue
                p = ln.rstrip().split("\t")
                if len(p) > alpha_start:
                    try:
                        rows.append([float(x) for x in p[alpha_start:]])
                    except ValueError:
                        pass
        if not rows:
            raise ValueError("No alpha data rows")
        a = np.array(rows, dtype=float)
        if wave is None or len(wave) != a.shape[1]:
            wave = np.arange(a.shape[1], dtype=float)
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
        df = pd.read_csv(path, sep=sep, comment="#", engine="python")
        # 첫 컬럼을 시간축으로 시도
        xcol = df.columns[0]
        x_dt = pd.to_datetime(df[xcol], errors="coerce")
        if x_dt.notna().mean() > 0.5:
            # ns→s epoch. Series.view는 최신 pandas에서 제거됨 → numpy로 안전 변환.
            x = x_dt.to_numpy(dtype="datetime64[ns]").astype("int64") / 1e9
            self._set_time_axis(self._pw_top, True)
            self._pw_top.setLabel("bottom", "Date / Time")
            ycols = df.columns[1:]
        else:
            x = np.arange(len(df))
            self._set_time_axis(self._pw_top, False)
            self._pw_top.setLabel("bottom", "index")
            ycols = df.columns
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
        # fit 모드에서 가스 선택 바뀌면 현재 파일 다시 그림
        if self._fit_cache and self._path:
            self._pw_top.clear(); self._pw_bot.clear(); self._pw_bot.show()
            self._plot_fit(self._path)

    def _qc_mask(self, t):
        """숨길/제외할 행 마스크(True) — 두 기준의 OR:
          (1) Hide QC 체크 시 Status가 QC-* 인 행
          (2) Post-hoc QC: K>0이면 RMS 분포에서 robust 임계 초과 행 (채널별)."""
        n = len(t["row_idx"])
        mask = np.zeros(n, bool)
        # (1) Status 기반
        if getattr(self, '_chk_hide_qc', None) and self._chk_hide_qc.isChecked():
            st = t.get("status")
            if st:
                mask |= np.array([s.startswith("QC") for s in st])
        # (2) RMS robust 임계 (사후 QC)
        K = self._spin_qc_k.value() if hasattr(self, '_spin_qc_k') else 0.0
        if K > 0:
            rms = t.get("rms")
            if rms is not None:
                ch = t.get("channel")   # 채널 배열(없으면 전체 한 그룹)
                groups = {}
                for i in range(n):
                    g = ch[i] if (ch is not None and i < len(ch)) else 0
                    groups.setdefault(g, []).append(i)
                for g, idxs in groups.items():
                    r = rms[idxs]
                    fin = np.isfinite(r) & (r > 0)
                    if fin.sum() < 5:
                        continue
                    la = np.log10(r[fin]); med = np.median(la); mad = np.median(np.abs(la - med))
                    if mad <= 0:
                        continue
                    thr = 10 ** (med + K * mad)
                    for i in idxs:
                        if np.isfinite(rms[i]) and rms[i] > thr:
                            mask[i] = True
        return mask

    def _plot_fit(self, path):
        t = self._load_fit_table(path)
        self._fit_cache = t
        self._sync_gas_combo(list(t["gases"].keys()))
        sel = self._gas_combo.currentText() or "All"
        names = list(t["gases"].keys()) if sel in ("All", "") else [sel]

        # x축: 실제 시각(datetime)이 있으면 그걸로(실시간 시계열), 없으면 row_idx
        has_time = t.get("time") is not None and np.isfinite(t["time"]).any()
        x = t["time"] if has_time else t["row_idx"]
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

        stats = []
        for i, g in enumerate(names):
            y = t["gases"].get(g)
            if y is None:
                continue
            y = y.copy()
            y[hide] = np.nan          # QC행 숨김(시각적 + 통계)
            col = _PALETTE[i % len(_PALETTE)]
            # 오차 표시(단일 가스 + Error 컬럼 있을 때) — NaN 구간을 가로지르는
            # fill 폴리곤이 깨져 보이던 것을 ErrorBar(유한 점만·데시메이션)로 교체.
            if (len(names) == 1 and getattr(self, '_chk_err', None)
                    and self._chk_err.isChecked()):
                err = (t.get("errs") or {}).get(g)
                if err is not None:
                    ok = np.isfinite(y) & np.isfinite(err) & np.isfinite(x)
                    xs, ys, es = x[ok], y[ok], err[ok]
                    if xs.size:
                        step = max(1, xs.size // 1500)
                        eb = pg.ErrorBarItem(x=xs[::step], y=ys[::step],
                                             height=2 * es[::step],
                                             pen=pg.mkPen(col, width=1))
                        self._pw_top.addItem(eb)
            self._pw_top.plot(x, y, pen=pg.mkPen(col, width=2), symbol="o",
                              symbolSize=4, symbolBrush=col, name=f"{g} (ppb)")
            # (±3σ X마커 제거 — QC와 무관한데 혼동만 줬음. 이상치는 Σ Stats에서 확인)
            fin = y[np.isfinite(y)]
            if fin.size:
                mu, sd = float(np.mean(fin)), float(np.std(fin))
                stats.append(f"{g}: μ={mu:.3g}±{sd:.2g} ppb")
        self._pw_top.setLabel("left", "Conc (ppb)")
        self._pw_top.setLabel("bottom", xlabel)
        qc_tag = f" · QC hidden {n_hidden}" if n_hidden else ""
        self._pw_top.setTitle(f"Fit — {os.path.basename(path)} ({len(x)} scans{qc_tag})")
        # 구간선택이 켜져 있었으면 새 플롯에도 다시 부착
        if getattr(self, '_btn_region', None) and self._btn_region.isChecked():
            self._attach_region()

        self._pw_bot.show()
        self._pw_bot.plot(x, t["rms"], pen=pg.mkPen(_PALETTE[2], width=2), name="RMS")
        self._pw_bot.setLabel("left", "RMS (cm⁻¹)")
        self._pw_bot.setLabel("bottom", xlabel)
        self._pw_bot.setTitle("RMS")

        self._stats_lbl.setText("   |   ".join(stats))
        # 포인트 클릭 → 해당 scan의 α 스펙트럼 팝업(형제 alpha_trace.dat 있으면)
        try:
            self._pw_top.scene().sigMouseClicked.disconnect(self._on_fit_point_clicked)
        except (TypeError, RuntimeError):
            pass
        self._pw_top.scene().sigMouseClicked.connect(self._on_fit_point_clicked)

    def _on_fit_point_clicked(self, ev):
        """ppb 그래프 클릭 → 가장 가까운 scan의 α 스펙트럼을 팝업(형제 alpha_trace)."""
        t = self._fit_cache
        if not t or self._path is None:
            return
        try:
            vb = self._pw_top.getViewBox()
            mp = vb.mapSceneToView(ev.scenePos())
            xclick = float(mp.x())
        except Exception:
            return
        # 플롯에 쓴 x축(시간 우선, 없으면 row_idx)으로 가장 가까운 점을 찾는다
        xarr = t["time"] if (t.get("time") is not None and np.isfinite(t["time"]).any()) else t["row_idx"]
        j = int(np.nanargmin(np.abs(xarr - xclick)))
        row_idx = int(t["row_idx"][j])
        alpha_path = self._sibling_alpha(self._path)
        if not alpha_path:
            self._stats_lbl.setText(f"row {row_idx}: sibling alpha_trace.dat not found → cannot open α popup")
            return
        self._show_alpha_popup(alpha_path, row_idx)

    @staticmethod
    def _sibling_alpha(fit_path):
        """`*_fit.tsv` 옆의 대응 `*_alpha_trace.dat` 경로 추정."""
        base = os.path.basename(fit_path)
        stem = base[:-8] if base.endswith("_fit.tsv") else os.path.splitext(base)[0]
        d = os.path.dirname(fit_path)
        cands = [os.path.join(d, stem + "_alpha_trace.dat"),
                 os.path.join(d, stem + ".dat")]
        import glob
        cands += glob.glob(os.path.join(d, stem + "*alpha_trace.dat"))
        for c in cands:
            if os.path.isfile(c):
                return c
        return None

    def _show_alpha_popup(self, alpha_path, row_idx):
        """alpha_trace.dat에서 row_idx 행의 α 스펙트럼을 팝업으로 표시."""
        wave = None
        target = None
        alpha_start = 3
        with open(alpha_path, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                if ln.startswith("# wavelength_nm:"):
                    try:
                        wave = np.array([float(v) for v in ln.split(":", 1)[1].strip().split("\t")
                                         if v.strip()], dtype=float)
                    except Exception:
                        pass
                    continue
                if ln.lower().startswith("row_idx"):
                    cols = ln.rstrip("\n").split("\t")
                    fp = next((i for i, c in enumerate(cols) if c.startswith("px")), None)
                    if fp is not None:
                        alpha_start = fp
                    continue
                if ln.startswith("#"):
                    continue
                p = ln.rstrip().split("\t")
                if len(p) > alpha_start:
                    try:
                        if int(float(p[0])) == row_idx:
                            target = np.array([float(x) for x in p[alpha_start:]], dtype=float)
                            break
                    except ValueError:
                        continue
        if target is None:
            self._stats_lbl.setText(f"row {row_idx} not in alpha_trace")
            return
        if wave is None or len(wave) != len(target):
            wave = np.arange(len(target), dtype=float)
        from PyQt6.QtWidgets import QDialog, QVBoxLayout
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
    def _attach_region(self):
        """현재 상단 플롯 x범위 가운데 1/3에 드래그 가능한 구간 핸들 부착."""
        if self._region is not None:
            try:
                self._pw_top.removeItem(self._region)
            except Exception:
                pass
            self._region = None
        vb = self._pw_top.getViewBox()
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
        self._pw_top.addItem(self._region)
        self._on_region_dragged()   # 입력칸 즉시 동기

    def _toggle_region(self, on):
        if on:
            self._attach_region()
            self._stats_lbl.setText("Drag handles or type exact times, then [✂ Export] / [Σ Stats]")
        elif self._region is not None:
            try:
                self._pw_top.removeItem(self._region)
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
        """선택(없으면 현재) 결과파일을 Plot Maker 선반으로 보낸다."""
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "Plot Maker", "보낼 결과 파일을 먼저 여세요.")
            return
        self.send_to_plotmaker.emit(paths)

    def _bake_qc_into_rows(self, colhdr, rows):
        """현재 K>0이면 rows(텍스트 행)의 RMS 분포로 robust 임계를 잡아 초과 행의
        가스 컬럼을 nan + Status=QC-Auto로 바꾼다. 반환: (rows, 제외수). K=0이면 그대로."""
        K = self._spin_qc_k.value() if hasattr(self, '_spin_qc_k') else 0.0
        if K <= 0 or not rows:
            return rows, 0
        cols = colhdr.split('\t')
        idx = {c: i for i, c in enumerate(cols)}
        if 'RMS' not in idx:
            return rows, 0
        ri = idx['RMS']; ci = idx.get('Channel'); si = idx.get('Status')
        gases = [c for c in cols if (c + '_Smooth') in idx] or \
                [c for c in cols if c in ('NO2', 'CHOCHO', 'H2O', 'O4', 'HONO', 'HCHO')]
        gidx = [idx[g] for g in gases] + [idx[g + '_Smooth'] for g in gases if (g + '_Smooth') in idx]
        # 채널별 임계
        import numpy as _np
        grp = {}
        for k, (_t, line) in enumerate(rows):
            p = line.split('\t')
            ch = p[ci] if (ci is not None and ci < len(p)) else '0'
            try:
                rv = float(p[ri])
            except Exception:
                rv = _np.nan
            grp.setdefault(ch, []).append((k, rv))
        thr = {}
        for ch, lst in grp.items():
            r = _np.array([v for _, v in lst]); fin = _np.isfinite(r) & (r > 0)
            if fin.sum() < 5:
                thr[ch] = _np.inf; continue
            la = _np.log10(r[fin]); med = _np.median(la); mad = _np.median(_np.abs(la - med))
            thr[ch] = 10 ** (med + K * mad) if mad > 0 else _np.inf
        out = []; nq = 0
        for k, (t, line) in enumerate(rows):
            p = line.split('\t')
            ch = p[ci] if (ci is not None and ci < len(p)) else '0'
            try:
                rv = float(p[ri])
            except Exception:
                rv = float('nan')
            if _np.isfinite(rv) and rv > thr.get(ch, _np.inf):
                for j in gidx:
                    if j < len(p):
                        p[j] = 'nan'
                if si is not None and si < len(p):
                    p[si] = f'QC-Auto(K={K:g})'
                nq += 1
                out.append((t, '\t'.join(p)))
            else:
                out.append((t, line))
        return out, nq

    def _export_region(self):
        """선택구간(없으면 전체)을 result_io로 잘라 새 파일로 저장.
        목록에서 여러 파일 선택 시 병합 후 자름."""
        from core.result_io import merge_results, slice_rows, write_result, bucketed_out_name
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "Export", "Open a result file first.")
            return
        try:
            comments, colhdr, rows, _ndup = merge_results(paths)
        except ValueError as e:
            QMessageBox.warning(self, "Export", str(e))
            return
        t0, t1 = self._region_times()
        n_in = len(rows)
        rows = slice_rows(rows, t0, t1)
        if not rows:
            QMessageBox.warning(self, "Export", "No data in the selected range.")
            return
        rows, nq = self._bake_qc_into_rows(colhdr, rows)   # 사후 QC(K>0) 반영
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
                     note=f"{len(paths)} file(s), {n_in}→{len(rows)} rows, QC-excluded {nq} (viewer export)")
        qmsg = f" · QC excluded {nq}" if nq else ""
        self._stats_lbl.setText(
            f"Saved: {os.path.basename(out)}  ({len(rows)} rows{qmsg}, "
            f"{rows[0][0]:%m-%d %H:%M} ~ {rows[-1][0]:%m-%d %H:%M})")

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
                     note=f"merged {len(paths)} files, {ndup} dups removed, QC-excluded {nq} (viewer)")
        dmsg = (f" · {ndup} dups" if ndup else "") + (f" · QC {nq}" if nq else "")
        self._stats_lbl.setText(f"Merged: {os.path.basename(out)} ({len(rows)} rows{dmsg})")

    def _stats_arrays(self):
        """현재 fit 캐시에서 (QC숨김·구간 반영) 선택마스크 반환."""
        t = self._fit_cache
        if not t:
            return None, None
        hide = self._qc_mask(t)
        sel = np.ones(len(t["row_idx"]), bool) & ~hide
        t0, t1 = self._region_times()
        if t0 is not None and t.get("time") is not None:
            tt = t["time"]
            sel &= np.isfinite(tt) & (tt >= t0.timestamp()) & (tt <= t1.timestamp())
        return t, sel

    def _show_stats(self):
        t, sel = self._stats_arrays()
        if t is None:
            QMessageBox.information(self, "Stats", "Open a fit result first.")
            return
        t0, t1 = self._region_times()
        rng = (f"{t0:%Y-%m-%d %H:%M} ~ {t1:%Y-%m-%d %H:%M}" if t0 else "all")
        lines = [f"File: {os.path.basename(t['path'])}",
                 f"Range: {rng}   (Hide QC {'ON' if self._chk_hide_qc.isChecked() else 'OFF'})",
                 "",
                 f"{'gas':<10} {'n':>6} {'mean':>9} {'median':>9} {'σ':>8} {'min':>8} {'max':>8}"]
        for g, y in t["gases"].items():
            v = y[sel]
            v = v[np.isfinite(v)]
            if v.size == 0:
                lines.append(f"{g:<10} {0:>6}")
                continue
            lines.append(f"{g:<10} {v.size:>6} {np.mean(v):>9.3f} {np.median(v):>9.3f} "
                         f"{np.std(v):>8.3f} {np.min(v):>8.2f} {np.max(v):>8.2f}")
        r = t["rms"][sel]
        r = r[np.isfinite(r)]
        if r.size:
            lines.append("")
            lines.append(f"RMS median {np.median(r):.3e} / p95 {np.percentile(r, 95):.3e}")
        dlg = QDialog(self)
        dlg.setWindowTitle("Stats (ppb)")
        dlg.resize(560, 340)
        lay = QVBoxLayout(dlg)
        ed = QPlainTextEdit("\n".join(lines))
        ed.setReadOnly(True)
        ed.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        lay.addWidget(ed)
        dlg.show()

    def _export_png(self):
        """현재 위/아래 그래프를 고해상도(폭 2400px) PNG 합본으로 저장."""
        import pyqtgraph.exporters as pgex
        from PyQt6.QtGui import QImage, QPainter
        base = os.path.splitext(os.path.basename(self._path or 'plot'))[0]
        out, _ = QFileDialog.getSaveFileName(self, "Export high-res PNG",
                                             f"{base}.png", "PNG (*.png)")
        if not out:
            return
        if not out.lower().endswith('.png'):
            out += '.png'
        try:
            imgs = []
            for pw in (self._pw_top, self._pw_bot):
                if not pw.isVisible() and pw is self._pw_bot:
                    continue
                ex = pgex.ImageExporter(pw.plotItem)
                ex.parameters()['width'] = 2400
                imgs.append(ex.export(toBytes=True))   # QImage
            if not imgs:
                return
            if len(imgs) == 1:
                imgs[0].save(out)
            else:
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
            self._stats_lbl.setText(f"PNG saved: {os.path.basename(out)} (2400px)")
        except Exception as e:
            QMessageBox.warning(self, "PNG export", f"Failed: {e}")