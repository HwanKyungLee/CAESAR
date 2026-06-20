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
    QComboBox, QProgressBar,
)

from gui.dlg_dir import dlg_dir


class AlphaGeneratorDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self._app = parent          # CAESARAnalyzer
        self._raw_files = []
        self._out_dir = ""
        self._ch_tab_map = {}       # {raw 채널:int -> 사용할 채널 탭:int} 핏세팅(wavecal/범위) 출처
        self._tab_combos = {}       # {raw 채널 -> QComboBox}
        self._ch_enable = {}        # {raw 채널 -> QCheckBox} 생성 여부
        self.setWindowTitle("🧪 Alpha Generator — Raw → Alpha 생성")
        self.resize(640, 520)
        self._build()

    # ──────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)

        info = QLabel("raw 측정파일을 받아 α 스펙트럼(*_alpha_trace.dat)을 생성합니다.\n"
                      "wavecal·핏레인지·cavity·flags 는 메인 창 설정을 사용합니다.")
        info.setStyleSheet("color:#546E7A;")
        root.addWidget(info)

        # raw 파일 로드 버튼
        bar = QHBoxLayout()
        btn_files = QPushButton("📂 Raw 파일 선택")
        btn_files.clicked.connect(self._pick_files)
        btn_folder = QPushButton("📁 Raw 폴더 선택")
        btn_folder.clicked.connect(self._pick_folder)
        btn_clear = QPushButton("비우기")
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
        opt.addWidget(QLabel("ambient 평균(초):"))
        self._spin_avg = QDoubleSpinBox()
        self._spin_avg.setRange(0.0, 600.0)
        self._spin_avg.setDecimals(0)
        self._spin_avg.setSingleStep(10.0)
        self._spin_avg.setValue(60.0)
        self._spin_avg.setFixedWidth(90)
        self._spin_avg.setToolTip("α 계산 전 ambient를 이 초만큼 시간평균(박사님 기본 60s). 0=평균 없음.")
        opt.addWidget(self._spin_avg)
        # 생성 px범위 — 알파 파일에는 이 구간만 저장됨(밖 픽셀은 파일에 없어
        # 나중에 더 넓게 피팅하려면 재생성 필요). 핏 윈도우보다 넉넉하게 두면
        # 이후 핏범위 실험을 알파 재생성 없이 할 수 있다.
        from PyQt6.QtWidgets import QSpinBox
        opt.addWidget(QLabel("  생성 px:"))
        self._spin_px0 = QSpinBox()
        self._spin_px0.setRange(0, 2047); self._spin_px0.setValue(0)
        self._spin_px0.setFixedWidth(70)
        opt.addWidget(self._spin_px0)
        opt.addWidget(QLabel("~"))
        self._spin_px1 = QSpinBox()
        self._spin_px1.setRange(1, 2048); self._spin_px1.setValue(2048)
        self._spin_px1.setFixedWidth(70)
        opt.addWidget(self._spin_px1)
        self._chk_px_fit = QCheckBox("핏범위 사용")
        self._chk_px_fit.setChecked(False)
        self._chk_px_fit.setToolTip(
            "체크: 생성구간 = 현재 채널 탭의 핏레인지(이전 동작).\n"
            "해제(기본): 왼쪽의 '생성 px' 범위 사용 — 핏 윈도우와 독립적으로 넉넉하게 생성.\n"
            "(박사님 per-bin 형식은 항상 전체 2048px이라 이 설정과 무관)")
        self._chk_px_fit.toggled.connect(
            lambda on: (self._spin_px0.setEnabled(not on), self._spin_px1.setEnabled(not on)))
        opt.addWidget(self._chk_px_fit)
        opt.addStretch(1)
        root.addLayout(opt)

        # raw 채널 → 사용할 핏세팅 탭(wavecal/범위 출처) 매핑
        self._wc_group = QGroupBox("핏세팅 탭 선택 (raw 채널 → 어느 채널 탭 설정으로 알파 생성)")
        self._wc_layout = QVBoxLayout(self._wc_group)
        self._wc_hint = QLabel("raw를 로드하면 채널 수만큼 표시됩니다.\n"
                               "예: 콜드 raw를 'CH3 탭'에 해둔 콜드 wavecal/범위로 만들고 싶으면 CH3 선택.")
        self._wc_hint.setStyleSheet("color:gray;")
        self._wc_layout.addWidget(self._wc_hint)
        root.addWidget(self._wc_group)

        # 저장 폴더
        sav = QHBoxLayout()
        btn_out = QPushButton("💾 저장 폴더")
        btn_out.clicked.connect(self._pick_out)
        self._lbl_out = QLabel("(저장 폴더 미설정)")
        self._lbl_out.setStyleSheet("color:gray;")
        sav.addWidget(btn_out)
        sav.addWidget(self._lbl_out, 1)
        root.addLayout(sav)

        # 박사님 형식(per-bin .dat) 옵션
        drn = QHBoxLayout()
        self._chk_drnam = QCheckBox("박사님 형식 (전체 2048px · per-bin .dat)")
        self._chk_drnam.setToolTip(
            "체크하면 ch{N}_{YYYYMMDD}_NNNNNN.dat (2048줄·1컬럼·헤더없음) 으로 저장.\n"
            "박사님 _avg_60s.mat의 std_t 그리드에 binning → 박사님 doasis가 읽을 수 있음.")
        self._chk_drnam.toggled.connect(lambda on: self._mat_row.setVisible(on))
        drn.addWidget(self._chk_drnam)
        drn.addStretch(1)
        root.addLayout(drn)

        self._mat_row = QWidget()
        mr = QHBoxLayout(self._mat_row); mr.setContentsMargins(0, 0, 0, 0)
        btn_mat = QPushButton("📂 박사님 _avg_60s.mat (std_t)")
        btn_mat.clicked.connect(self._pick_mat)
        self._lbl_mat = QLabel("(std_t .mat 미설정)")
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
        self._btn_gen = QPushButton("🧪 Generate Alpha")
        self._btn_gen.setStyleSheet("font-weight:bold; padding:8px;")
        self._btn_gen.clicked.connect(self._generate)
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.reject)
        run.addWidget(self._btn_gen, 1)
        run.addWidget(btn_close)
        root.addLayout(run)

    # ──────────────────────────────────────────────────────────────
    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Raw 측정파일 선택", dlg_dir("alpha_gen_raw"),
            "Data Files (*.dat *.txt *.csv);;All Files (*)")
        if files:
            dlg_dir("alpha_gen_raw", files[0])
            self._add(files)

    def _pick_folder(self):
        """raw 폴더 선택 — 하위 폴더(월별: 2026-05/2026-06 등)까지 재귀로 모은 뒤,
        파일명 날짜가 여러 개면 날짜 다중선택 다이얼로그로 골라 추가한다.
        (상위 폴더 하나만 찍으면 월 경계를 넘는 기간도 한 번에 로드 가능.)"""
        d = QFileDialog.getExistingDirectory(self, "Raw 폴더 선택(하위폴더 포함)", dlg_dir("alpha_gen_raw"))
        if not d:
            return
        dlg_dir("alpha_gen_raw", d)
        import glob as _glob
        import re as _re
        exts = (".dat", ".txt", ".csv")
        def _is_raw(f):
            if not (f.lower().endswith(exts) and os.path.isfile(f)):
                return False
            rel = os.path.relpath(f, d).lower()
            # 알파 산출물 폴더/파일은 raw가 아님 — 재귀 수집에서 제외
            if (os.sep + 'alpha') in (os.sep + rel) or '_alpha_trace' in rel:
                return False
            return True
        # 파일명(날짜+스캔) 기준 정렬 — 하위폴더가 흩어져도 시간순 유지(전체경로 정렬 X)
        files = sorted((f for f in _glob.glob(os.path.join(d, "**", "*"), recursive=True)
                        if _is_raw(f)), key=lambda f: os.path.basename(f))
        if not files:
            QMessageBox.warning(self, "없음", "폴더(하위 포함)에 raw 파일(.dat/.txt/.csv)이 없습니다.")
            return
        # 파일명에서 날짜 추출 → 여러 날짜면 메인 창의 날짜선택 다이얼로그 재사용
        by_date = {}
        for f in files:
            m = _re.search(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})', os.path.basename(f))
            by_date.setdefault(f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else "(날짜없음)", []).append(f)
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

    def _add(self, files):
        for f in files:
            if f not in self._raw_files:
                self._raw_files.append(f)
                self._list.addItem(os.path.basename(f))
        self._lbl_status.setText(f"raw {len(self._raw_files)}개 선택됨")
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
            chk = QCheckBox(f"생성")
            chk.setChecked(True)
            chk.setToolTip("이 채널 알파를 생성할지. 끄면 건너뜀(이미 만든 채널 재생성 방지).")
            row.addWidget(chk)
            self._ch_enable[ch] = chk
            row.addWidget(QLabel(f"raw CH{ch} →  핏세팅 탭:"))
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
            btn_rt = QPushButton("📈")
            btn_rt.setFixedWidth(30)
            btn_rt.setToolTip(f"raw CH{ch}의 R(t) npz 선택 (없으면 자체 R)")
            rt_lbl = QLabel("자체 R")
            rt_lbl.setStyleSheet("color:gray;")
            btn_rtx = QPushButton("✕")
            btn_rtx.setFixedWidth(24)
            btn_rtx.setToolTip("R(t) 해제")
            btn_rt.clicked.connect(lambda _x, c=ch, lb=rt_lbl: self._pick_ch_rt(c, lb))
            btn_rtx.clicked.connect(
                lambda _x, c=ch, lb=rt_lbl: (self._ch_rt.pop(c, None),
                                             lb.setText("자체 R"), lb.setStyleSheet("color:gray;")))
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
            self, f"raw CH{ch} R(t) npz (R_<채널>.npz)", dlg_dir("rt_path"),
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
        d = QFileDialog.getExistingDirectory(self, "Alpha 저장 폴더", dlg_dir("alpha_out"))
        if d:
            dlg_dir("alpha_out", d)
            self._out_dir = d
            self._lbl_out.setText(d)

    def _pick_mat(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "박사님 _avg_60s.mat (std_t)", dlg_dir("drnam_mat"), "MAT (*.mat);;All Files (*)")
        if f:
            dlg_dir("drnam_mat", f)
            self._drnam_mat = f
            self._lbl_mat.setText(os.path.basename(f))

    # ──────────────────────────────────────────────────────────────
    def _generate(self):
        if not self._raw_files:
            QMessageBox.warning(self, "No Files", "raw 파일을 먼저 선택하세요.")
            return
        if not self._out_dir:
            QMessageBox.warning(self, "No Output", "저장 폴더를 선택하세요.")
            return
        drnam_mat = self._drnam_mat if self._chk_drnam.isChecked() else None
        if self._chk_drnam.isChecked() and not drnam_mat:
            QMessageBox.warning(self, "std_t 필요", "박사님 형식은 _avg_60s.mat(std_t)을 지정하세요.")
            return
        self._btn_gen.setEnabled(False)
        self._pbar.setValue(0)
        self._lbl_status.setText("α 생성 시작…")
        ok = self._app.export_alpha_files(
            file_list=self._raw_files,
            out_dir=self._out_dir,
            avg_sec=self._spin_avg.value(),
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
        self._lbl_status.setText("✅ 완료")
        QMessageBox.information(
            self, "Alpha 생성 완료",
            "채널별 α 저장 완료:\n" + "\n".join(msgs) +
            f"\n\n저장 위치:\n{out_dir}\n"
            "파일명: {소스}_{채널}_alpha_trace.dat\n"
            "이제 분석(좌측)에서 이 α 파일을 Load → RUN 하면 피팅됩니다.")
