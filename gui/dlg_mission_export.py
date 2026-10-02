# -*- coding: utf-8 -*-
"""gui/dlg_mission_export.py — Setup 탭 Vigil 그룹 'Export Mission…' — FitSet 을 Vigil 용 미션 패키지로 내보낸다.

FitSet 은 "어느 raw 의 어느 블록이 어느 셀인가"를 모른다(채널 키 = 탭 번호, data_label 은 뒤바뀐 이력).
여기서 사람이 채널마다 **raw 구성·블록·이름·캐비티 센서**를 한 번 확정하고(raw 파일로 블록 스펙트럼과
'핏 창이 빛 들어오는 구간 안인가'를 확인할 수 있다), core.mission_package 가 FitSet·레퍼런스·wavecal 을
복사해 자기완결 폴더로 묶는다. 같은 미션을 이 PC 의 Augur 에도 설치해 분석과 감시가 같은 정의를 쓰게 한다.
"""
from __future__ import annotations

import json
import os
from datetime import date

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
                             QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QTableWidget, QVBoxLayout, QWidget)

COLS = ("Use", "FitSet channel", "Raw config", "Block", "Cell name", "Pressure sensor",
        "Gas T sensor", "Conc", "R", "Check")


def _bases():
    from core.profile import load_profiles
    return [p for p in load_profiles(validate=False) if not p.is_mission]


def _defaults():
    """(기본 id, 블록) → 지금 있는 미션이 그 블록에 쓰는 (이름, 압력 키, 온도 키) — 표의 기본값."""
    from core.profile import load_profiles
    out = {}
    for p in load_profiles(validate=False):
        if not p.is_mission:
            continue
        for c in p.signal_channels():
            pk, tk = c.pressure_keys(), c.temp_keys()
            out.setdefault((p.base_id, c.id), (c.label or "", pk[0] if pk else "", tk[0] if tk else ""))
    return out


class MissionExportDialog(QDialog):
    def __init__(self, parent=None, fitset_path: str = "", out_root: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Export mission for Vigil")
        self.resize(1100, 560)
        self.bases = _bases()
        self.defaults = _defaults()
        self.out_root = out_root
        self.scen = {}
        self.checks = {}
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "Which raw block is which cell, and which sensors are its pressure / gas temperature, is decided "
            "<b>here, by you</b> — the FitSet does not know (its channel labels have been swapped before). "
            "Use <i>Check with raw…</i> to see each block's spectrum: judge the cell by the LED shape."))
        form = QFormLayout()
        row = QHBoxLayout()
        self.ed_fitset = QLineEdit(fitset_path)
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_fitset)
        row.addWidget(self.ed_fitset, 1)
        row.addWidget(b)
        w = QWidget(); w.setLayout(row)
        form.addRow("FitSet", w)
        self.ed_name = QLineEdit(f"mission_{date.today():%Y%m%d}")
        form.addRow("Mission name", self.ed_name)
        d = QHBoxLayout()
        self.dt_from = QDateEdit(QDate.currentDate()); self.dt_from.setCalendarPopup(True)
        self.dt_to = QDateEdit(QDate(2099, 12, 31)); self.dt_to.setCalendarPopup(True)
        for x in (self.dt_from, self.dt_to):
            x.setDisplayFormat("yyyy-MM-dd")
        d.addWidget(self.dt_from); d.addWidget(QLabel("to")); d.addWidget(self.dt_to)
        d.addWidget(QLabel("(raw file-name dates; leave the end far away while the mission runs)"))
        d.addStretch(1)
        w = QWidget(); w.setLayout(d)
        form.addRow("Dates", w)
        v.addLayout(form)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table, 1)
        h = QHBoxLayout()
        self.btn_check = QPushButton("Check with raw…")
        self.btn_check.setToolTip("Pick a raw .dat of this layout: shows each block's brightness, LED peak and\n"
                                  "whether the FitSet fit window lies inside the lit (half-maximum) band.")
        self.btn_check.clicked.connect(lambda: self._check_raw())
        h.addWidget(self.btn_check)
        self.chk_install = QCheckBox("Also use this mission in Augur on this PC")
        self.chk_install.setChecked(True)
        h.addWidget(self.chk_install)
        b_inst = QPushButton("Install a package…")
        b_inst.setToolTip("Use a mission package made on another PC (USB) in Augur here — it is copied into\n"
                          "vigil/profiles/missions/ (commit that folder so the other analysis PCs get it too).")
        b_inst.clicked.connect(lambda: self.install_package())
        h.addWidget(b_inst)
        h.addStretch(1)
        v.addLayout(h)
        self.plot = None
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_export = bb.addButton("Export…", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.accepted.connect(self._export)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.result_dir = None
        if fitset_path:
            self._load_fitset(fitset_path)

    # ── FitSet ───────────────────────────────────────────────────────
    def _browse_fitset(self):
        p, _ = QFileDialog.getOpenFileName(self, "FitSet", os.path.dirname(self.ed_fitset.text()),
                                           "JSON (*.json)")
        if p:
            self.ed_fitset.setText(p)
            self._load_fitset(p)

    def _load_fitset(self, path):
        from core.mission_package import absolutize_fitset, wl_dir_of
        try:
            self.scen = absolutize_fitset(json.load(open(path, encoding="utf-8")),
                                          os.path.dirname(os.path.abspath(path)))
        except Exception as e:                    # noqa: BLE001
            QMessageBox.warning(self, "FitSet", f"Cannot read FitSet: {e}")
            return
        self.table.setRowCount(0)
        self.checks.clear()
        for key, ch in sorted((self.scen.get("channels") or {}).items()):
            r = self.table.rowCount()
            self.table.insertRow(r)
            use = QCheckBox(); use.setChecked(True)
            self.table.setCellWidget(r, 0, use)
            win = f"{ch.get('fit_start_nm', '?')}–{ch.get('fit_end_nm', '?')} nm"
            lab = QLabel(f"{key}: {wl_dir_of(ch.get('wl_path'))}  {win}")
            lab.setToolTip(f"wl_path: {ch.get('wl_path')}\n(data_label '{ch.get('data_label', '')}' is NOT used)")
            lab.setProperty("key", key)
            self.table.setCellWidget(r, 1, lab)
            cb_base = QComboBox()
            for b in self.bases:
                cb_base.addItem(f"{b.kind} {b.match.n_columns}", b.profile_id)
            cb_blk = QComboBox()
            self.table.setCellWidget(r, 2, cb_base)
            self.table.setCellWidget(r, 3, cb_blk)
            self.table.setCellWidget(r, 4, QLineEdit())
            self.table.setCellWidget(r, 5, QComboBox())
            self.table.setCellWidget(r, 6, QComboBox())
            for c in (7, 8):
                x = QCheckBox(); x.setChecked(True)
                self.table.setCellWidget(r, c, x)
            self.table.setCellWidget(r, 9, QLabel("—"))
            # 블록 기본: 콜드 wavecal → 콜드 1번, roi1/roi2 → 핫 — 추측이지만 사람이 고친다(표시만)
            wd = wl_dir_of(ch.get("wl_path"))
            want = "cold" if wd == "cold" else "hot"
            for i in range(cb_base.count()):
                if cb_base.itemText(i).startswith(want):
                    cb_base.setCurrentIndex(i)
                    break
            cb_base.currentIndexChanged.connect(lambda _i, rr=r: self._fill_row(rr))
            cb_blk.currentIndexChanged.connect(lambda _i, rr=r: self._fill_defaults(rr))
            self._fill_row(r)

    def _base(self, r):
        bid = self.table.cellWidget(r, 2).currentData()
        return next((b for b in self.bases if b.profile_id == bid), None)

    def _fill_row(self, r):
        b = self._base(r)
        cb_blk = self.table.cellWidget(r, 3)
        cb_blk.blockSignals(True)
        cb_blk.clear()
        for c in (b.channels if b else []):
            cb_blk.addItem(f"{c.id} (cols {c.columns[0]}–{c.columns[1]})", c.id)
        cb_blk.setCurrentIndex(min(1, cb_blk.count() - 1))
        cb_blk.blockSignals(False)
        for col, unit in ((5, "mbar"), (6, "degC")):
            cb = self.table.cellWidget(r, col)
            cb.clear()
            for f in (b.hk.fields if b else []):
                if (f.unit or "") == unit:
                    cb.addItem(f"{f.key}  (col {b.hk.start_col + f.rel})", f.key)
        self._fill_defaults(r)

    def _fill_defaults(self, r):
        b = self._base(r)
        blk = self.table.cellWidget(r, 3).currentData()
        lab, pk, tk = self.defaults.get((b.profile_id if b else None, blk), ("", "", ""))
        ed = self.table.cellWidget(r, 4)
        if not ed.text():
            ed.setPlaceholderText(lab or "e.g. ANs")
        for col, key in ((5, pk), (6, tk)):
            cb = self.table.cellWidget(r, col)
            i = cb.findData(key)
            if i >= 0:
                cb.setCurrentIndex(i)

    # ── raw 확인 ─────────────────────────────────────────────────────
    def _check_raw(self, p=None):
        from core.mission_package import block_check
        if not p:
            p, _ = QFileDialog.getOpenFileName(self, "Raw file of this layout", "", "Raw (*.dat)")
        if not p:
            return
        ncols = 0
        with open(p, encoding="utf-8", errors="replace") as fh:   # 앞 몇 줄의 최대 폭(첫 줄은 짧은 헤더행일 수 있다)
            for _ in range(5):
                line = fh.readline()
                if not line:
                    break
                ncols = max(ncols, len(line.split("\t")))
        curves = []
        for r in range(self.table.rowCount()):
            b = self._base(r)
            lab = self.table.cellWidget(r, 9)
            if b is None or b.match.n_columns != ncols:
                lab.setText(f"(raw has {ncols} cols)")
                continue
            ch = next(c for c in b.channels if c.id == self.table.cellWidget(r, 3).currentData())
            fch = self.scen["channels"][self.table.cellWidget(r, 1).property("key")]
            res = block_check(p, ch.columns[0], fch.get("wl_path"),
                              (fch.get("fit_start_nm"), fch.get("fit_end_nm"))
                              if fch.get("fit_start_nm") is not None else None)
            self.checks[r] = res
            if not res.get("n_rows"):
                lab.setText("no ambient rows")
                continue
            txt = ("lit" if res["lit"] else "DARK") + f" max {res['max']:.0f}"
            if "peak_nm" in res:
                txt += f" · peak {res['peak_nm']:.1f} nm"
            if "halfmax_nm" in res:
                txt += f" · LED {res['halfmax_nm'][0]:.0f}–{res['halfmax_nm'][1]:.0f} nm"
            if "window_inside" in res:
                txt += " · window inside ✓" if res["window_inside"] else " · WINDOW OUTSIDE ✗"
            lab.setText(txt)
            lab.setStyleSheet("" if res["lit"] and res.get("window_inside", True) else "color:#b03030;")
            curves.append((f"{ch.id} ({self.table.cellWidget(r, 4).text() or '?'})", res["median"]))
        if curves:
            self._show_plot(curves, os.path.basename(p))

    def _show_plot(self, curves, title):
        import pyqtgraph as pg
        if self.plot is None:
            self.plot = pg.PlotWidget()
            self.plot.setMinimumHeight(180)
            self.plot.addLegend()
            self.layout().insertWidget(self.layout().count() - 1, self.plot)
        self.plot.clear()
        self.plot.setTitle(f"Block spectra (ambient median) — {title}")
        for i, (name, y) in enumerate(curves):
            self.plot.plot(y, pen=pg.intColor(i, hues=max(3, len(curves))), name=name)

    def install_package(self, pkg=None) -> str | None:
        """다른 PC 에서 만든 미션 패키지를 이 PC 의 Augur 에 설치 → 설치 경로(실패·취소면 None)."""
        from core import mission_package as MP
        if not pkg:
            pkg = QFileDialog.getExistingDirectory(self, "Mission package folder", self.out_root)
        if not pkg:
            return None
        root = MP.missions_root()
        try:
            probs = MP.verify_package(pkg) or MP.overlap_problems(pkg, os.path.dirname(root), root)
            if probs:
                raise ValueError("; ".join(probs))
            dst = MP.install_package(pkg, root)
        except Exception as e:                    # noqa: BLE001 — 사람에게 보이고 아무것도 안 바꾼다
            QMessageBox.warning(self, "Install mission", f"{type(e).__name__}: {e}")
            return None
        from core.raw_parser import autoload_campaign_layouts
        autoload_campaign_layouts(verbose=False)
        QMessageBox.information(self, "Mission installed",
                                f"{dst}\n\nAugur now reads raw files in the mission's dates with its cell names and "
                                f"sensors. Commit vigil/profiles/missions/ so the other analysis PCs get it.")
        return dst

    # ── 내보내기 ─────────────────────────────────────────────────────
    def collect(self) -> list:
        """표 → build_package 의 missions 인자(기본 프로파일마다 미션 하나)."""
        lo, hi = self.dt_from.date().toString("yyyy-MM-dd"), self.dt_to.date().toString("yyyy-MM-dd")
        if lo > hi:
            raise ValueError("start date is after end date")
        by_base, seen = {}, set()
        name = self.ed_name.text().strip()
        for r in range(self.table.rowCount()):
            if not self.table.cellWidget(r, 0).isChecked():
                continue
            b = self._base(r)
            blk = self.table.cellWidget(r, 3).currentData()
            label = self.table.cellWidget(r, 4).text().strip()
            key = self.table.cellWidget(r, 1).property("key")
            if not label:
                raise ValueError(f"FitSet channel {key}: enter the cell name (judge it from the LED spectrum)")
            if (b.profile_id, blk) in seen:
                raise ValueError(f"{b.kind} {b.match.n_columns} block {blk} is assigned twice")
            seen.add((b.profile_id, blk))
            pk = self.table.cellWidget(r, 5).currentData()
            tk = self.table.cellWidget(r, 6).currentData()
            tchain = [k for k in (tk, "cell_heater") if k and b.hk.field(k) is not None]
            m = by_base.setdefault(b.profile_id, {
                "base": b.profile_id, "profile_id": f"{name}_{b.kind}_{b.match.n_columns}".lower(),
                "campaign": name, "date_range": [lo, hi], "channels": []})
            m["channels"].append({
                "block": blk, "label": label, "fitset_channel": key,
                "cavity": {k: v for k, v in (("pressure_hk", [pk] if pk else []),
                                             ("temperature_hk", list(dict.fromkeys(tchain)))) if v},
                "concentration": {} if self.table.cellWidget(r, 7).isChecked() else None,
                "reflectance": {} if self.table.cellWidget(r, 8).isChecked() else None})
        if not by_base:
            raise ValueError("no channel selected")
        import re
        for m in by_base.values():
            m["profile_id"] = re.sub(r"[^a-z0-9_]+", "_", m["profile_id"])
        return list(by_base.values())

    def build(self, out_dir: str) -> dict:
        from core import mission_package as MP
        try:
            from core.provenance import code_version
            who = f"Augur {code_version()}"
        except Exception:                         # noqa: BLE001
            who = "Augur"
        return MP.build_package(out_dir, self.ed_fitset.text(), self.collect(),
                                name=self.ed_name.text().strip(), created_by=who)

    def _export(self):
        from core import mission_package as MP
        try:
            missions = self.collect()
        except ValueError as e:
            QMessageBox.warning(self, "Export mission", str(e))
            return
        unchecked = [r for r in range(self.table.rowCount())
                     if self.table.cellWidget(r, 0).isChecked() and r not in self.checks]
        if unchecked and QMessageBox.question(
                self, "Not checked against a raw file",
                "Some channels were not checked against a raw spectrum (Check with raw…).\n"
                "The cell identity is then only your assertion. Export anyway?") != QMessageBox.StandardButton.Yes:
            return
        parent = QFileDialog.getExistingDirectory(self, "Folder to create the mission package in", self.out_root)
        if not parent:
            return
        out = os.path.join(parent, MP._safe(self.ed_name.text().strip()))
        try:
            man = self.build(out)
        except Exception as e:                    # noqa: BLE001
            QMessageBox.critical(self, "Export mission", f"{type(e).__name__}: {e}")
            return
        note = ""
        if self.chk_install.isChecked():
            root = MP.missions_root()
            probs = MP.overlap_problems(out, os.path.dirname(root), root)
            if probs:
                note = "\n\nNOT installed in Augur here: " + "; ".join(probs)
            else:
                MP.install_package(out, root)
                from core.raw_parser import autoload_campaign_layouts
                autoload_campaign_layouts(verbose=False)
                note = f"\n\nAlso installed for Augur on this PC: {root}"
        self.result_dir = out
        QMessageBox.information(self, "Mission exported",
                                f"{out}\n\nCopy this folder to the measurement PC (USB) and press "
                                f"'Load mission…' in Vigil.\n\n" + "\n".join(man.get("provenance", [])) + note)
        self.accept()


def open_mission_export(parent=None):
    qs = getattr(parent, "_qsettings", None)
    last = qs.value("last_fitset", "", type=str) if qs is not None else ""
    MissionExportDialog(parent, fitset_path=last if last and os.path.exists(last) else "").exec()
