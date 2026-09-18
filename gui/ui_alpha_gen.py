"""Alpha Generator 팝업 — raw 측정파일 → α 스펙트럼(*_alpha_trace.dat) 생성.

분석(좌측 RUN)은 '알파를 넣고 피팅'에 집중하고, 알파 생성만 이 창에서 분리 수행한다.
wavecal / 핏레인지 / cavity / flags 등은 메인 UI 설정을 그대로 재사용한다
(생성 로직은 메인의 export_alpha_files 재사용).
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QListWidget, QDoubleSpinBox, QMessageBox, QCheckBox, QWidget, QGroupBox,
    QComboBox, QProgressBar, QSpinBox,
)

from gui.dlg_dir import dlg_dir
from core.parallel import set_max_workers


def _qsettings():
    """메인 창과 **같은** 저장소(CAESAR/app). CPU 스핀 값을 둘이 공유한다."""
    from PyQt6.QtCore import QSettings
    return QSettings("CAESAR", "app")


class AlphaGeneratorDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self._app = parent          # CAESARAnalyzer
        self._raw_files = []
        self._out_dir = ""
        self._ch_tab_map = {}       # {raw 채널:int -> 사용할 채널 탭:int} 핏세팅(wavecal/범위) 출처
        self._tab_combos = {}       # {raw 채널 -> QComboBox}
        self._ch_enable = {}        # {raw 채널 -> QCheckBox} 생성 여부
        self.setWindowTitle("Alpha Generator — Raw → Alpha")
        self.resize(640, 520)
        self._build()

    # ──────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)

        info = QLabel("Generate α spectra (*_alpha_trace.dat) from raw measurement files.\n"
                      "wavecal / fit range / cavity / flags use the main window settings.")
        info.setStyleSheet("color:#546E7A;")
        root.addWidget(info)

        # raw 파일 로드 버튼
        bar = QHBoxLayout()
        btn_files = QPushButton("Select Raw Files")
        btn_files.clicked.connect(self._pick_files)
        btn_folder = QPushButton("Select Raw Folder")
        btn_folder.clicked.connect(self._pick_folder)
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._clear)
        bar.addWidget(btn_files)
        bar.addWidget(btn_folder)
        bar.addWidget(btn_clear)
        bar.addStretch(1)
        root.addLayout(bar)

        self._list = QListWidget()
        root.addWidget(self._list, 1)

        # ambient 평균(초)
        opt = QHBoxLayout()
        opt.addWidget(QLabel("Ambient avg (s):"))
        self._spin_avg = QDoubleSpinBox()
        self._spin_avg.setRange(0.0, 600.0)
        self._spin_avg.setDecimals(0)
        self._spin_avg.setSingleStep(10.0)
        self._spin_avg.setValue(60.0)
        self._spin_avg.setFixedWidth(90)
        self._spin_avg.setToolTip("Time-average ambient over this many seconds before α (default 60s). 0 = no averaging.")
        opt.addWidget(self._spin_avg)
        # 교정 직후 퍼지 세틀링(초) — 밸브가 ambient 로 돌아와도 캐비티엔 ZA/He 가
        # 남아 있다. 플러시 시간은 유량·셀부피에 달려 계기/채널마다 다르니 손잡이로 둔다
        # (여수 콜드 실측 ~60s). 0 = 옛 동작(제외 안 함).
        opt.addWidget(QLabel("  Purge settle (s):"))
        self._spin_purge = QDoubleSpinBox()
        self._spin_purge.setRange(0.0, 600.0)
        self._spin_purge.setDecimals(0)
        self._spin_purge.setSingleStep(10.0)
        self._spin_purge.setValue(60.0)
        self._spin_purge.setFixedWidth(90)
        self._spin_purge.setToolTip(
            "Drop ambient scans within this many seconds after a ZA/He block "
            "(cavity still holding purge gas — Yeosu cold measured ~60s). 0 = keep them.")
        opt.addWidget(self._spin_purge)
        # 생성 px범위 — 알파 파일에는 이 구간만 저장됨(밖 픽셀은 파일에 없어
        # 나중에 더 넓게 피팅하려면 재생성 필요). 핏 윈도우보다 넉넉하게 두면
        # 이후 핏범위 실험을 알파 재생성 없이 할 수 있다.
        opt.addWidget(QLabel("  Gen px:"))
        self._spin_px0 = QSpinBox()
        self._spin_px0.setRange(0, 2047); self._spin_px0.setValue(0)
        self._spin_px0.setFixedWidth(70)
        opt.addWidget(self._spin_px0)
        opt.addWidget(QLabel("~"))
        self._spin_px1 = QSpinBox()
        self._spin_px1.setRange(1, 2048); self._spin_px1.setValue(2048)
        self._spin_px1.setFixedWidth(70)
        opt.addWidget(self._spin_px1)
        self._chk_px_fit = QCheckBox("Use fit range")
        self._chk_px_fit.setChecked(False)
        self._chk_px_fit.setToolTip(
            "Checked: gen range = current channel tab's fit range (legacy behavior).\n"
            "Unchecked (default): use the 'Gen px' range on the left — generated wider than the fit window.\n"
            "(Per-bin format is always the full 2048px, independent of this setting)")
        self._chk_px_fit.toggled.connect(
            lambda on: (self._spin_px0.setEnabled(not on), self._spin_px1.setEnabled(not on)))
        opt.addWidget(self._chk_px_fit)
        # 병렬 워커 수 — 값은 core.parallel(환경변수) 단일 출처라 메인 창의 `CPU`
        # 스핀과 같은 것을 가리킨다. 여기 또 두는 이유는 **긴 작업이 여기서 돈다**:
        # 메인 창에만 있으면 알파를 돌리는 사람 눈에 안 보인다.
        opt.addWidget(QLabel("  CPU:"))
        _cpu_max = os.cpu_count() or 4
        self._spin_cores = QSpinBox()
        self._spin_cores.setRange(1, _cpu_max)
        self._spin_cores.setSuffix(f"/{_cpu_max}")
        self._spin_cores.setFixedWidth(75)
        self._spin_cores.setValue(_qsettings().value("cpu_workers", _cpu_max, type=int))
        self._spin_cores.setToolTip(
            "Worker processes for alpha generation (Pass 1 parsing and Pass 2 alpha).\n"
            "Shared with the main window CPU box and with Fast fitting / R(t).\n"
            f"Default {_cpu_max} = all logical cores. Raw on a USB HDD is disk-bound,\n"
            "so past ~8 there is nothing to gain; drop it if the GUI feels stuck.\n"
            "Remembered between sessions.")
        self._spin_cores.valueChanged.connect(
            lambda n: (set_max_workers(n), _qsettings().setValue("cpu_workers", n)))
        set_max_workers(self._spin_cores.value())
        opt.addWidget(self._spin_cores)
        opt.addStretch(1)
        root.addLayout(opt)

        # raw 채널 → 사용할 핏세팅 탭(wavecal/범위 출처) 매핑
        self._wc_group = QGroupBox("Fit-setting tab (raw channel → which channel tab's settings to generate alpha with)")
        self._wc_layout = QVBoxLayout(self._wc_group)
        self._wc_hint = QLabel("One row per channel appears after raw is loaded.\n"
                               "e.g. to build cold raw with the cold wavecal/range you keep on 'CH3 tab', select CH3.")
        self._wc_hint.setStyleSheet("color:gray;")
        self._wc_layout.addWidget(self._wc_hint)
        root.addWidget(self._wc_group)

        # 저장 폴더
        sav = QHBoxLayout()
        btn_out = QPushButton("Output Folder")
        btn_out.clicked.connect(self._pick_out)
        self._lbl_out = QLabel("(no output folder)")
        self._lbl_out.setStyleSheet("color:gray;")
        sav.addWidget(btn_out)
        sav.addWidget(self._lbl_out, 1)
        root.addLayout(sav)

        # 박사님 형식(per-bin .dat) 옵션
        drn = QHBoxLayout()
        self._chk_drnam = QCheckBox("Per-bin format (full 2048px · per-bin .dat)")
        self._chk_drnam.setToolTip(
            "If checked, save as ch{N}_{YYYYMMDD}_NNNNNN.dat (2048 lines · 1 column · no header).\n"
            "Binned onto the std_t grid of _avg_60s.mat → readable by external DOASIS.")
        self._chk_drnam.toggled.connect(lambda on: self._mat_row.setVisible(on))
        drn.addWidget(self._chk_drnam)
        drn.addStretch(1)
        root.addLayout(drn)

        self._mat_row = QWidget()
        mr = QHBoxLayout(self._mat_row); mr.setContentsMargins(0, 0, 0, 0)
        btn_mat = QPushButton("_avg_60s.mat (std_t grid)")
        btn_mat.clicked.connect(self._pick_mat)
        self._lbl_mat = QLabel("(no std_t .mat)")
        self._lbl_mat.setStyleSheet("color:gray;")
        mr.addWidget(btn_mat); mr.addWidget(self._lbl_mat, 1)
        self._mat_row.setVisible(False)
        self._drnam_mat = ""
        root.addWidget(self._mat_row)
        # (R(t)는 위 '핏세팅 탭 선택' 채널 행마다 개별 지정 — 핫 2채널도 한 번에 정확히.)

        # 상태 + 진행바 + 실행
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color:#1565C0;")
        root.addWidget(self._lbl_status)

        self._pbar = QProgressBar()
        self._pbar.setRange(0, 100)
        self._pbar.setValue(0)
        self._pbar.setTextVisible(True)
        self._pbar.setFormat("%p%")
        root.addWidget(self._pbar)

        run = QHBoxLayout()
        self._btn_gen = QPushButton("Generate Alpha")
        self._btn_gen.setStyleSheet("font-weight:bold; padding:8px;")
        self._btn_gen.clicked.connect(self._generate)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        run.addWidget(self._btn_gen, 1)
        run.addWidget(btn_close)
        root.addLayout(run)

    # ──────────────────────────────────────────────────────────────
    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Raw Files", dlg_dir("alpha_gen_raw"),
            "Data Files (*.dat *.txt *.csv);;All Files (*)")
        if files:
            dlg_dir("alpha_gen_raw", files[0])
            self._add(files)

    def _pick_folder(self):
        """raw 폴더 선택 — 하위 폴더(월별: 2026-05/2026-06 등)까지 재귀로 모은 뒤,
        파일명 날짜가 여러 개면 날짜 다중선택 다이얼로그로 골라 추가한다.
        (상위 폴더 하나만 찍으면 월 경계를 넘는 기간도 한 번에 로드 가능.)"""
        d = QFileDialog.getExistingDirectory(self, "Select Raw Folder (incl. subfolders)", dlg_dir("alpha_gen_raw"))
        if not d:
            return
        dlg_dir("alpha_gen_raw", d)
        import re as _re
        exts = (".dat", ".txt", ".csv")
        # os.walk 로 수집(파일마다 stat 하는 glob "**/*" 대비 빠름) + 'alpha' 출력
        # 하위트리는 아예 내려가지 않게 가지치기 → 대형 폴더 선택 시 메인스레드 블로킹 완화.
        from PyQt6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            files = []
            for _root, _dirs, _names in os.walk(d):
                _dirs[:] = [_dd for _dd in _dirs if _dd.lower() != 'alpha']  # 알파 출력 제외
                for _fn in _names:
                    # 측정 파일(YYYY-MM-DD-NNN)만 — Ref/FWHM/Calib/merge 등 잡파일은 여기서
                    # 걸러 날짜선택 다이얼로그에도 안 뜨게 한다(그런 파일이 알파에 섞이면 오염).
                    if self._RAW_NAME_RE.match(_fn):
                        files.append(os.path.join(_root, _fn))
            # 파일명(날짜+스캔) 기준 정렬 — 하위폴더가 흩어져도 시간순 유지(전체경로 정렬 X)
            files.sort(key=lambda f: os.path.basename(f))
        finally:
            QApplication.restoreOverrideCursor()
        if not files:
            QMessageBox.warning(self, "None", "No raw files (.dat/.txt/.csv) found in the folder (incl. subfolders).")
            return
        # 파일명에서 날짜 추출 → 여러 날짜면 메인 창의 날짜선택 다이얼로그 재사용
        by_date = {}
        for f in files:
            m = _re.search(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})', os.path.basename(f))
            by_date.setdefault(f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else "(no date)", []).append(f)
        dates = sorted(by_date)
        if len(dates) > 1 and hasattr(self._app, '_pick_dates'):
            sel = self._app._pick_dates(dates)
            if sel is None:
                return
            # sel은 순서없는 set → 날짜 정렬 후, 날짜 내 파일도 파일명순으로
            files = [f for dt in sorted(sel)
                     for f in sorted(by_date.get(dt, []), key=lambda f: os.path.basename(f))]
        if files:
            self._add(files)

    # 측정(raw) 파일명 규칙: YYYY-MM-DD-NNN.dat/.txt/.csv. FWHM_Analysis_*·Calib_* 등
    # 분석/출력 파일이 raw 폴더에 섞여 있어도 알파 입력에서 자동 제외한다(그런 파일을
    # 스캔으로 오인 파싱하면 이상 데이터가 주입돼 그 뒤 전 기간 알파가 오염된다 —
    # 2026-07-09 FWHM_Analysis_20260523_cold.dat 사고).
    import re as _re_mod
    _RAW_NAME_RE = _re_mod.compile(r'^\d{4}-\d{2}-\d{2}-\d+\.(?:dat|txt|csv)$', _re_mod.I)

    def _add(self, files):
        skipped = []
        for f in files:
            if not self._RAW_NAME_RE.match(os.path.basename(f)):
                skipped.append(os.path.basename(f))
                continue
            if f not in self._raw_files:
                self._raw_files.append(f)
                self._list.addItem(os.path.basename(f))
        if skipped:
            _shown = skipped if len(skipped) <= 8 else skipped[:8] + [f"… +{len(skipped)-8}개"]
            QMessageBox.warning(
                self, "측정 파일 아님 — 제외됨",
                "다음 파일은 측정 파일 형식(YYYY-MM-DD-NNN)이 아니라 알파 입력에서 제외했습니다"
                "(FWHM/Calib 등 분석 파일을 넣으면 알파가 오염됩니다):\n\n  " + "\n  ".join(_shown))
        self._lbl_status.setText(f"{len(self._raw_files)} raw file(s) selected")
        # 채널 수 감지 → 핏세팅 탭 매핑 행 갱신
        if self._raw_files:
            try:
                from core.data_io import DataIO
                n_ch = int(DataIO.detect_channels(self._raw_files[0]) or 1)
            except Exception:
                n_ch = 1
            self._refresh_tab_rows(n_ch)

    def _available_tabs(self):
        """부모 앱의 현재 채널 탭 번호 목록."""
        tb = getattr(self._app, '_channel_tabbar', None)
        if tb is not None:
            tabs = [tb.tabData(i) for i in range(tb.count())]
            tabs = [int(t) for t in tabs if t is not None]
            if tabs:
                return sorted(tabs)
        return sorted(int(c) for c in getattr(self._app, '_channel_configs', {1: None}).keys())

    def _refresh_tab_rows(self, n_ch):
        """raw 채널 수만큼 '핏세팅 탭 선택' 행 구성. 기본: raw 채널 N → 탭 N(없으면 첫 탭)."""
        while self._wc_layout.count():
            it = self._wc_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._tab_combos = {}
        self._ch_tab_map = {}
        self._ch_enable = {}
        self._ch_rt = {}          # {raw 채널 -> R(t) npz 경로} 채널별 R
        if n_ch <= 0:
            return
        tabs = self._available_tabs() or [1]
        for ch in range(1, n_ch + 1):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            chk = QCheckBox("Generate")
            chk.setChecked(True)
            chk.setToolTip("Whether to generate this channel's alpha. Unchecked = skip (avoid regenerating an already-built channel).")
            row.addWidget(chk)
            self._ch_enable[ch] = chk
            row.addWidget(QLabel(f"raw CH{ch} →  fit-setting tab:"))
            cmb = QComboBox()
            for t in tabs:
                cmb.addItem(f"CH{t}", t)
            default_tab = ch if ch in tabs else tabs[0]
            cmb.setCurrentIndex(tabs.index(default_tab))
            self._ch_tab_map[ch] = default_tab
            cmb.currentIndexChanged.connect(
                lambda _idx, c=ch, box=cmb: self._ch_tab_map.__setitem__(c, box.currentData()))
            row.addWidget(cmb)
            # 이 채널의 R(t) npz — R Trend의 'α용 R(t) 저장'으로 만든 R_<채널>.npz.
            # 지정하면 이 채널 알파에 채널창 기반 R 적용(핫 정상). 비우면 자체 R.
            row.addWidget(QLabel("   R(t):"))
            btn_rt = QPushButton("R(t)")
            btn_rt.setFixedWidth(30)
            btn_rt.setToolTip(f"Pick R(t) npz for raw CH{ch} (none = self R)")
            rt_lbl = QLabel("self R")
            rt_lbl.setStyleSheet("color:gray;")
            btn_rtx = QPushButton("X")
            btn_rtx.setFixedWidth(24)
            btn_rtx.setToolTip("Clear R(t)")
            btn_rt.clicked.connect(lambda _x, c=ch, lb=rt_lbl: self._pick_ch_rt(c, lb))
            btn_rtx.clicked.connect(
                lambda _x, c=ch, lb=rt_lbl: (self._ch_rt.pop(c, None),
                                             lb.setText("self R"), lb.setStyleSheet("color:gray;")))
            row.addWidget(btn_rt)
            row.addWidget(rt_lbl, 1)
            row.addWidget(btn_rtx)
            row.addStretch(1)
            cont = QWidget()
            cont.setLayout(row)
            self._wc_layout.addWidget(cont)
            self._tab_combos[ch] = cmb

    def _pick_ch_rt(self, ch, lbl):
        """raw 채널 ch의 R(t) npz 선택 → self._ch_rt[ch]."""
        f, _ = QFileDialog.getOpenFileName(
            self, f"raw CH{ch} R(t) npz (R_<channel>.npz)", dlg_dir("rt_path"),
            "R(t) npz (*.npz);;All Files (*)")
        if f:
            dlg_dir("rt_path", f)
            self._ch_rt[ch] = f
            lbl.setText(os.path.basename(f))
            lbl.setStyleSheet("color:#1565C0;")
            lbl.setToolTip(f)

    def _clear(self):
        self._raw_files = []
        self._list.clear()
        self._lbl_status.setText("")

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Alpha Output Folder", dlg_dir("alpha_out"))
        if d:
            dlg_dir("alpha_out", d)
            self._out_dir = d
            self._lbl_out.setText(d)

    def _pick_mat(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "_avg_60s.mat (std_t grid)", dlg_dir("drnam_mat"), "MAT (*.mat);;All Files (*)")
        if f:
            dlg_dir("drnam_mat", f)
            self._drnam_mat = f
            self._lbl_mat.setText(os.path.basename(f))

    # ──────────────────────────────────────────────────────────────
    def _generate(self):
        if not self._raw_files:
            QMessageBox.warning(self, "No Files", "Select raw files first.")
            return
        if not self._out_dir:
            QMessageBox.warning(self, "No Output", "Select an output folder.")
            return
        drnam_mat = self._drnam_mat if self._chk_drnam.isChecked() else None
        if self._chk_drnam.isChecked() and not drnam_mat:
            QMessageBox.warning(self, "std_t required", "Per-bin format needs an _avg_60s.mat (std_t).")
            return
        self._btn_gen.setEnabled(False)
        self._pbar.setValue(0)
        self._lbl_status.setText("Starting α generation…")
        ok = self._app.export_alpha_files(
            file_list=self._raw_files,
            out_dir=self._out_dir,
            avg_sec=self._spin_avg.value(),
            purge_settle_sec=self._spin_purge.value(),
            status_cb=self._on_status,
            done_cb=self._on_done,
            drnam_mat=drnam_mat,
            ch_tab_map=dict(self._ch_tab_map),
            channels=[ch for ch, c in self._ch_enable.items() if c.isChecked()] or None,
            progress_cb=self._on_progress,
            gen_px_range=(None if self._chk_px_fit.isChecked()
                          else (self._spin_px0.value(), self._spin_px1.value())),
            rt_map={c: p for c, p in getattr(self, '_ch_rt', {}).items() if p},
        )
        if not ok:
            self._btn_gen.setEnabled(True)

    def _on_status(self, msg):
        self._lbl_status.setText(msg)

    def _on_progress(self, pct, total):
        """알파 생성 진행바(%). app가 (pct, 100)으로 호출."""
        self._pbar.setValue(max(0, min(100, int(pct))))

    def _on_done(self, out_dir, msgs):
        self._btn_gen.setEnabled(True)
        self._pbar.setValue(100)
        self._lbl_status.setText("Done")
        QMessageBox.information(
            self, "Alpha generation complete",
            "Per-channel α saved:\n" + "\n".join(msgs) +
            f"\n\nLocation:\n{out_dir}\n"
            "Filename: {source}_{channel}_alpha_trace.dat\n"
            "Now Load this α file in Analysis (left) → RUN to fit.")
