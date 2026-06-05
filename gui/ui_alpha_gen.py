"""Alpha Generator 팝업 — raw 측정파일 → α 스펙트럼(*_alpha_trace.dat) 생성.

분석(좌측 RUN)은 '알파를 넣고 피팅'에 집중하고, 알파 생성만 이 창에서 분리 수행한다.
wavecal / 핏레인지 / cavity / flags 등은 메인 UI 설정을 그대로 재사용한다
(생성 로직은 메인의 export_alpha_files 재사용).
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QListWidget, QDoubleSpinBox, QMessageBox,
)

from gui.dlg_dir import dlg_dir


class AlphaGeneratorDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self._app = parent          # CAESARAnalyzer
        self._raw_files = []
        self._out_dir = ""
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
        opt.addStretch(1)
        root.addLayout(opt)

        # 저장 폴더
        sav = QHBoxLayout()
        btn_out = QPushButton("💾 저장 폴더")
        btn_out.clicked.connect(self._pick_out)
        self._lbl_out = QLabel("(저장 폴더 미설정)")
        self._lbl_out.setStyleSheet("color:gray;")
        sav.addWidget(btn_out)
        sav.addWidget(self._lbl_out, 1)
        root.addLayout(sav)

        # 상태 + 실행
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color:#1565C0;")
        root.addWidget(self._lbl_status)

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
        d = QFileDialog.getExistingDirectory(self, "Raw 폴더 선택", dlg_dir("alpha_gen_raw"))
        if not d:
            return
        dlg_dir("alpha_gen_raw", d)
        exts = (".dat", ".txt", ".csv")
        files = [os.path.join(d, f) for f in sorted(os.listdir(d))
                 if f.lower().endswith(exts)]
        if files:
            self._add(files)
        else:
            QMessageBox.warning(self, "없음", "폴더에 raw 파일(.dat/.txt/.csv)이 없습니다.")

    def _add(self, files):
        for f in files:
            if f not in self._raw_files:
                self._raw_files.append(f)
                self._list.addItem(os.path.basename(f))
        self._lbl_status.setText(f"raw {len(self._raw_files)}개 선택됨")

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

    # ──────────────────────────────────────────────────────────────
    def _generate(self):
        if not self._raw_files:
            QMessageBox.warning(self, "No Files", "raw 파일을 먼저 선택하세요.")
            return
        if not self._out_dir:
            QMessageBox.warning(self, "No Output", "저장 폴더를 선택하세요.")
            return
        self._btn_gen.setEnabled(False)
        self._lbl_status.setText("α 생성 시작…")
        ok = self._app.export_alpha_files(
            file_list=self._raw_files,
            out_dir=self._out_dir,
            avg_sec=self._spin_avg.value(),
            status_cb=self._on_status,
            done_cb=self._on_done,
        )
        if not ok:
            self._btn_gen.setEnabled(True)

    def _on_status(self, msg):
        self._lbl_status.setText(msg)

    def _on_done(self, out_dir, msgs):
        self._btn_gen.setEnabled(True)
        self._lbl_status.setText("✅ 완료")
        QMessageBox.information(
            self, "Alpha 생성 완료",
            "채널별 α 저장 완료:\n" + "\n".join(msgs) +
            f"\n\n저장 위치:\n{out_dir}\n"
            "파일명: {소스}_{채널}_alpha_trace.dat\n"
            "이제 분석(좌측)에서 이 α 파일을 Load → RUN 하면 피팅됩니다.")
