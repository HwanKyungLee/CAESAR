"""📅 날짜로 불러오기 — 일별 핏 버킷({YYMMDD}/{neg}/{QC}/) 스캔 → 기간 선택 → 자동 머지.

Result Lab·Plot Maker 공용. 두 도구 모두 '파일 경로'를 먹는 구조라, 머지 결과를
{base}/_derived/{범위}/{neg}/{QC}/ 실파일로 쓰고 그 경로들을 돌려준다
(기존 로드 파이프라인·플롯 설정 저장/복원 무수정 — ResolvedSeries drift 차단 유지).

파일 증식 방지 = 캐시 재사용: 머지 파일명이 (시리즈+일수+범위)로 결정적이라
같은 요청이면 기존 파일을 그대로 쓰고, 원본 일별 파일이 재핏으로 더 새로우면
자동으로 다시 머지한다. 하루짜리 요청은 머지 없이 일별 파일 경로를 그대로 반환.
"""
from __future__ import annotations

import os
import re

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QDateEdit, QCheckBox, QFileDialog, QMessageBox)

_DAY_DIR = re.compile(r'^\d{6}$')
_ISO_DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')


# ── 스캔/머지 로직(GUI 무관 — 단위테스트 가능) ─────────────────────────────

def _scan_day_root(droot: str, day: str, cfg: str, out: dict) -> None:
    """하나의 {YYMMDD} 폴더({neg}/{QC}/*.dat)를 스캔해 out에 채운다.
    키 = (cfg, stem, neg, qc). cfg='' 는 config 폴더 없는 레거시 flat 트리."""
    for neg in ('neg_o', 'neg_x'):
        nd = os.path.join(droot, neg)
        if not os.path.isdir(nd):
            continue
        for qc in sorted(os.listdir(nd)):
            qd = os.path.join(nd, qc)
            if not qc.startswith('QC') or not os.path.isdir(qd):
                continue
            for f in sorted(os.listdir(qd)):
                if not f.lower().endswith('.dat'):
                    continue
                stem = re.sub(r'^\d{6}_', '', os.path.splitext(f)[0])
                out.setdefault((cfg, stem, neg, qc), {})[day] = os.path.join(qd, f)


def _scan_campaign_day(kind_dir: str, day: str, campaign: str, out: dict) -> None:
    """A3 배치의 하루: `{campaign}/{YYYY-MM-DD}/fitting/*.dat`.

    neg/QC는 이제 폴더가 아니라 `.meta.json`에 있다(같은 어휘를 쓰려면
    `core.run_meta.bucket_labels`가 단일 출처). meta가 없어도 파일명의 runid가
    세팅을 이미 가르므로 시리즈 분리 자체는 깨지지 않는다."""
    from core.run_meta import read_meta, bucket_labels
    for f in sorted(os.listdir(kind_dir)):
        if not f.lower().endswith('.dat'):
            continue
        fp = os.path.join(kind_dir, f)
        meta = read_meta(fp)
        neg, qc = bucket_labels(meta) if meta else ('neg_?', 'QC?')
        stem = re.sub(r'^\d{6}_', '', os.path.splitext(f)[0])
        out.setdefault((campaign, stem, neg, qc), {})[day] = fp


def scan_daily_tree(base: str) -> dict:
    """핏 트리 스캔 → {(cfg, stem, neg, qc): {'YYMMDD': 파일경로}}.
    세 구조를 모두 인식(읽기는 관대하게 — 기존 파일은 하나도 안 옮긴다):
      • A3:     base/{campaign}/{YYYY-MM-DD}/fitting/*.dat  (cfg = campaign, neg/qc는 meta에서)
      • 구:     base/{fit-config}/{YYMMDD}/{neg}/{QC}/*.dat (cfg = config 폴더명)
      • 레거시: base/{YYMMDD}/{neg}/{QC}/*.dat              (cfg = '')
    stem = 파일명에서 날짜 프리픽스·확장자 제거(= 채널/세팅 태그 또는 CH_label_runid)."""
    out: dict = {}
    if not base or not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        top = os.path.join(base, name)
        if not os.path.isdir(top):
            continue
        if _DAY_DIR.match(name):                 # 레거시 flat: base/{YYMMDD}/...
            _scan_day_root(top, name, '', out)
        elif name.startswith('_'):               # _archive/_derived/_autosave/_export
            continue
        else:                                    # campaign 또는 config 폴더
            for day in sorted(os.listdir(top)):
                droot = os.path.join(top, day)
                if not os.path.isdir(droot):
                    continue
                if _ISO_DAY.match(day):          # A3: {campaign}/{YYYY-MM-DD}/{kind}/
                    ymd = f"{day[2:4]}{day[5:7]}{day[8:10]}"
                    for kind in sorted(os.listdir(droot)):
                        kdir = os.path.join(droot, kind)
                        if kind == 'fitting' and os.path.isdir(kdir):
                            _scan_campaign_day(kdir, ymd, name, out)
                elif _DAY_DIR.match(day):        # 구: {cfg}/{YYMMDD}/{neg}/{QC}/
                    _scan_day_root(droot, day, name, out)
    return out


def load_range(base: str, key: tuple, files_by_date: dict,
               d0: str, d1: str) -> str | None:
    """[d0, d1](YYMMDD 문자열, 양끝 포함) 기간의 일별 파일을 머지해 경로 반환.
    기간 내 파일 없으면 None, 1개면 그 파일 그대로(머지 불필요),
    캐시가 원본들보다 새로우면 재머지 없이 캐시 경로."""
    from core.result_io import merge_results, write_result
    days = sorted(d for d in files_by_date if d0 <= d <= d1)
    files = [files_by_date[d] for d in days]
    if not files:
        return None
    if len(files) == 1:
        return files[0]
    cfg, stem, neg, qc = key
    span = f"{days[0]}-{days[-1]}"
    out = os.path.join(base, '_derived', cfg, span, neg, qc,
                       f"{stem}_merge{len(files)}_{span}.dat")
    if os.path.exists(out) and os.path.getmtime(out) > max(map(os.path.getmtime, files)):
        return out
    comments, colhdr, rows, n_dup = merge_results(files)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    write_result(out, comments, colhdr, rows,
                 note=f"date-load merge of {len(files)} daily files ({n_dup} dup removed)")
    return out


def _qdate(d: str) -> QDate:
    return QDate(2000 + int(d[:2]), int(d[2:4]), int(d[4:6]))


def _daystr(q: QDate) -> str:
    return f"{q.year() % 100:02d}{q.month():02d}{q.day():02d}"


# ── 다이얼로그 ────────────────────────────────────────────────────────────

class DateLoadDialog(QDialog):
    """기간 + 시리즈(스템·neg·QC) 선택 → loaded_paths에 머지/일별 파일 경로 목록."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from gui.dlg_dir import dlg_dir
        self.setWindowTitle("Load fit results by date")
        self.resize(560, 420)
        self.loaded_paths: list[str] = []
        self._tree: dict = {}

        v = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Fitting folder:"))
        self._ed_base = QLineEdit(dlg_dir("fitting_base"))
        self._ed_base.editingFinished.connect(self._rescan)
        row.addWidget(self._ed_base, 1)
        b = QPushButton("...")
        b.setToolTip("핏 버킷({핏config}/{YYMMDD}/{neg}/{QC}/ 또는 레거시 {YYMMDD}/...)이 있는 fitting 최상위 폴더")
        b.clicked.connect(self._browse)
        row.addWidget(b)
        v.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("From:"))
        self._d0 = QDateEdit(calendarPopup=True)
        row2.addWidget(self._d0)
        row2.addWidget(QLabel("To:"))
        self._d1 = QDateEdit(calendarPopup=True)
        row2.addWidget(self._d1)
        self._chk_all = QCheckBox("Select all")
        self._chk_all.toggled.connect(self._toggle_all)
        row2.addStretch(1)
        row2.addWidget(self._chk_all)
        v.addLayout(row2)

        self._list = QListWidget()
        v.addWidget(self._list, 1)

        self._lbl = QLabel("")
        self._lbl.setStyleSheet("color:#666;")
        v.addWidget(self._lbl)

        brow = QHBoxLayout()
        brow.addStretch(1)
        b_ok = QPushButton("Load")
        b_ok.setDefault(True)
        b_ok.clicked.connect(self._do_load)
        b_no = QPushButton("Cancel")
        b_no.clicked.connect(self.reject)
        brow.addWidget(b_ok)
        brow.addWidget(b_no)
        v.addLayout(brow)

        self._rescan()

    # ── 내부 ──
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select fitting output folder",
                                             self._ed_base.text())
        if d:
            self._ed_base.setText(d)
            self._rescan()

    def _rescan(self):
        base = self._ed_base.text().strip()
        self._tree = scan_daily_tree(base)
        self._list.clear()
        if not self._tree:
            self._lbl.setText("핏 버킷({핏config}/{YYMMDD}/{neg}/{QC}/*.dat 또는 레거시 {YYMMDD}/...)을 찾지 못했습니다 — 폴더를 확인하세요.")
            return
        all_days = sorted({d for m in self._tree.values() for d in m})
        self._d0.setDate(_qdate(all_days[0]))
        self._d1.setDate(_qdate(all_days[-1]))
        from datetime import datetime
        for key in sorted(self._tree, key=lambda k: (k[0], k[1], k[2], k[3])):
            cfg, stem, neg, qc = key
            days = sorted(self._tree[key])
            # 최근 저장시각 — 재핏 직후 어떤 시리즈가 갱신됐는지 한눈에
            last = max(os.path.getmtime(p) for p in self._tree[key].values())
            cfg_disp = f"{cfg} · " if cfg else ""
            it = QListWidgetItem(
                f"{cfg_disp}{stem}   [{neg}/{qc}]   {days[0]}~{days[-1]} · {len(days)}d"
                f"{datetime.fromtimestamp(last):%m-%d %H:%M}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self._list.addItem(it)
        self._lbl.setText(f"{len(self._tree)} series · {len(all_days)} day(s) available"
                          "  — 체크한 시리즈를 기간으로 잘라 자동 머지합니다.")

    def _toggle_all(self, on):
        st = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(st)

    def _do_load(self):
        from gui.dlg_dir import dlg_dir
        base = self._ed_base.text().strip()
        d0, d1 = _daystr(self._d0.date()), _daystr(self._d1.date())
        if d1 < d0:
            d0, d1 = d1, d0
        keys = [self._list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self._list.count())
                if self._list.item(i).checkState() == Qt.CheckState.Checked]
        if not keys:
            QMessageBox.information(self, "Load by date", "시리즈를 하나 이상 체크하세요.")
            return
        paths, skipped, errors = [], [], []
        for key in keys:
            try:
                p = load_range(base, key, self._tree[key], d0, d1)
            except Exception as e:                       # 컬럼 불일치 등 — 다른 시리즈는 계속
                errors.append(f"{key[1]}: {e}")
                continue
            (paths if p else skipped).append(p if p else key[1])
        if errors:
            QMessageBox.warning(self, "Load by date", "머지 실패:\n" + "\n".join(errors))
        if not paths:
            QMessageBox.information(self, "Load by date",
                                    f"{d0}~{d1} 기간에 해당하는 파일이 없습니다.")
            return
        if skipped:
            QMessageBox.information(self, "Load by date",
                                    "기간 내 파일 없음(건너뜀): " + ", ".join(skipped))
        dlg_dir("fitting_base", base)
        self.loaded_paths = paths
        self.accept()
