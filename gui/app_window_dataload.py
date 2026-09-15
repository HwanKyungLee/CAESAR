"""gui/app_window_dataload.py
CAESARAnalyzer §10 — 데이터 로드 + 채널 분배 (gui/app_window.py에서 분리).

**순수 이동이다.** 메서드 본문은 한 글자도 안 고쳤다 — 호출부가 전부 self.xxx()라
믹스인으로 옮기는 것만으로 동작이 같다. 로직 개선은 다음 PR로.
가드는 tools/test_app_window_smoke.py (표면 골든 + 믹스인 이름 충돌 검사).
"""
import os
import re

from PyQt6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidgetItem,
                             QVBoxLayout)
from core.data_io import DataIO
from .ui_dialogs import RangeSelectorDialog


class DataLoadMixin:
    """§10 — 데이터 로드 + 채널 분배. CAESARAnalyzer에 믹스인된다."""

    # ══════════════════════════════════════════════════════════════════════
    # §10 데이터 로드 + 채널 분배
    # ══════════════════════════════════════════════════════════════════════
    def load_data(self):
        """
        Smart router that allows choosing between file or folder loading
        using a single button to keep the main UI clean.
        """
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Select Load Method")
        msg_box.setText("How would you like to load the measurement data?")
        msg_box.setIcon(QMessageBox.Icon.Question)
        
        # Add custom buttons
        btn_files = msg_box.addButton("Select Files", QMessageBox.ButtonRole.ActionRole)
        btn_folder = msg_box.addButton("Load Entire Folder", QMessageBox.ButtonRole.ActionRole)
        msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        
        msg_box.exec()
        
        # Route to the appropriate function based on user selection
        if msg_box.clickedButton() == btn_files:
            self._load_files()
        elif msg_box.clickedButton() == btn_folder:
            self._load_folder()

    def _load_files(self):
        """Loads specific measurement files selected by the user."""
        files, _ = QFileDialog.getOpenFileNames(self, "Select Measurement Files", self._dlg_dir('data'), "Data Files (*.dat *.txt *.csv)")
        if files:
            self._dlg_dir('data', files[0])
            self._update_file_table(sorted(files))

    def _load_folder(self):
        """Scans a selected folder (하위폴더 재귀) and loads all valid measurement files.
        날짜별 폴더(예: out/ch1/2026-05-18/...)에 흩어진 알파도 폴더 하나만 고르면 다 로드."""
        folder_path = QFileDialog.getExistingDirectory(self, "Select Measurement Folder (incl. subfolders)", self._dlg_dir('data'))
        if folder_path:
            self._dlg_dir('data', folder_path)
            valid_extensions = ('.dat', '.txt', '.csv')
            # os.walk + 가지치기: '_'로 시작하는 폴더(_archive/_derived/_autosave 등)와
            # legacy_unified(옛 알파 리네임 사본)는 스캔 제외 — 안 하면 같은 스캔이
            # 여러 벌(신규+사본+아카이브) 쓸려 들어와 중복 경고+수천 파일 렉.
            # 그 폴더를 보고 싶으면 '직접' 루트로 고르면 됨(루트 자체는 가지치기 안 함).
            _SKIP_DIRS = {'legacy_unified'}
            # 측정(raw) 또는 알파 파일만: 둘 다 'YYYY-MM-DD-NNN'으로 시작한다
            # (raw=2026-05-18-001.dat, 알파=2026-05-18-001_ANs_alpha_trace.dat).
            # FWHM_Analysis_·Calib_·Ref_ 같은 분석/레퍼런스 파일은 이 접두가 아니라
            # 제외 — 안 막으면 알파처럼 스캔으로 오인돼 핏이 오염된다(2026-07-09 FWHM 사고).
            import re as _re_meas
            _MEAS_RE = _re_meas.compile(r'^\d{4}-\d{2}-\d{2}-\d+')
            files, _n_skip = [], 0
            for _root, _dirs, _names in os.walk(folder_path):
                _dirs[:] = [d for d in _dirs
                            if not d.startswith('_') and d not in _SKIP_DIRS]
                for _fn in _names:
                    if _fn.lower().endswith(valid_extensions):
                        if _MEAS_RE.match(_fn):
                            files.append(os.path.join(_root, _fn))
                        else:
                            _n_skip += 1
            if _n_skip:
                self.status.setText(f"Skipped {_n_skip} non-measurement file(s) (FWHM/Calib/Ref 등)")
            # 파일명(날짜+스캔) 기준 정렬 — 하위폴더가 흩어져도 시간순 유지
            files = sorted(set(files), key=lambda f: (os.path.basename(f), f))
            if not files:
                QMessageBox.warning(self, "No Data",
                                    "No .dat/.txt/.csv files in the selected folder (incl. subfolders).")
                return
            # 날짜가 여러 개면 다중선택(특정 날짜만 피팅 가능)
            import re as _re
            def _date_of(f):
                m = _re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', os.path.basename(f))
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else "(no date)"
            dates = sorted(set(_date_of(f) for f in files))
            if len(dates) > 1:
                sel = self._pick_dates(dates)
                if sel is None:
                    return   # 취소
                files = [f for f in files if _date_of(f) in sel]
                if not files:
                    QMessageBox.warning(self, "No selection", "No dates selected.")
                    return
            # L10: 알파 헤더(label)로 채널 자동분배 — cold/ch1/ch2가 섞인 루트 폴더를
            # 한 번에 로드해 3채널 탭에 나눠 넣기. 분배 안 되면 기존(활성 채널) 동작.
            if self._distribute_channels(files):
                return
            self._update_file_table(files)

    @staticmethod
    def _alpha_head_label(fp):
        """알파 wide 헤더에서 label 추출 ('# channel=N  label=Cold'). 없으면 None."""
        import re as _re
        try:
            with open(fp, encoding='utf-8', errors='replace') as fh:
                for _ in range(4):
                    ln = fh.readline()
                    if not ln:
                        break
                    m = _re.search(r'#\s*channel=\d+\s+label=(\S+)', ln)
                    if m:
                        return m.group(1)
        except OSError:
            pass
        return None

    def _distribute_channels(self, files):
        """알파 라벨 그룹이 2개 이상이고 채널 탭 라벨과 매칭되면 자동분배.
        반환 True=분배 완료(테이블은 활성 채널 분량 표시), False=해당 없음."""
        # 라벨별 그룹화 (라벨 없는 파일이 섞이면 분배하지 않음 — raw 등)
        groups = {}
        for f in files:
            lab = self._alpha_head_label(f)
            if lab is None:
                return False
            groups.setdefault(lab.lower(), []).append(f)
        if len(groups) < 2:
            return False
        # 채널 탭 라벨 수집 (활성 채널은 현재 입력칸, 나머지는 config 스냅샷)
        tab_label = {}
        for ch in self._channel_configs:
            if ch == self._active_channel:
                lab = self._ed_ch_datalabel.text().strip() if hasattr(self, '_ed_ch_datalabel') else ''
            else:
                lab = ((self._channel_configs.get(ch) or {}).get('data_label') or '').strip()
            tab_label[ch] = lab.lower()
        # 매핑: 그룹라벨 == 탭라벨 (탭라벨 비어있으면 'ch{N}'으로 간주)
        mapping = {}
        for ch, lab in tab_label.items():
            key = lab or f'ch{ch}'
            if key in groups:
                mapping[ch] = key
        if len(mapping) < 2:
            return False
        # 확인 다이얼로그
        lines = [f"  CH{ch} ← {mapping[ch]} ({len(groups[mapping[ch]])} files)" for ch in sorted(mapping)]
        unmatched = [k for k in groups if k not in mapping.values()]
        if unmatched:
            lines.append(f"  (unmatched labels: {', '.join(unmatched)} — not distributed)")
        # 중복 스캔(같은 날짜-스캔이 다른 폴더에 중복 — 라벨 오염 의심) 경고
        import re as _re2
        def _scankey(f):
            m = _re2.search(r'(\d{4}-\d{2}-\d{2}-\d{3})', os.path.basename(f))
            return m.group(1) if m else os.path.basename(f)
        dupwarn = []
        for ch, key in mapping.items():
            keys = [_scankey(f) for f in groups[key]]
            ndup = len(keys) - len(set(keys))
            if ndup:
                dupwarn.append(f"  CH{ch}({key}): {ndup} duplicate scans")
        warn = ("\n\n DUPLICATE scans found (same date-scan in >1 folder —\n"
                "possible mislabeled alphas):\n" + "\n".join(dupwarn)) if dupwarn else ""
        ret = QMessageBox.question(self, "Auto-distribute channels",
                                   "Distribute alpha files to channel tabs by label:\n\n" + "\n".join(lines)
                                   + warn
                                   + "\n\nProceed? (No = all into current channel)",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return False
        self.results = []   # 새로 분배한 파일셋에 대한 결과가 아니므로 이전 Run 결과 무효화
        for ch, key in mapping.items():
            # 파일명(날짜+스캔) 기준 정렬 — 폴더가 흩어져도 시간순 보장(전체경로 정렬 X)
            self._channel_files[ch] = sorted(groups[key], key=lambda f: os.path.basename(f))
        # 활성 채널 분량만 테이블 표시(없으면 첫 매칭 채널)
        act = self._active_channel if self._active_channel in mapping else sorted(mapping)[0]
        self.file_list = list(self._channel_files.get(act, []))
        self.table.setRowCount(len(self.file_list))
        self.table.clearContents()
        for i, fp in enumerate(self.file_list):
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(fp)))
        total = sum(len(self._channel_files[c]) for c in mapping)
        self.status.setText("distributed: " + " · ".join(
            f"CH{c} {len(self._channel_files[c])}" for c in sorted(mapping)) + f" (total {total})")
        self._auto_detect_channels()
        return True

    def _pick_dates(self, dates):
        """날짜 다중선택 다이얼로그. 반환: 선택 날짜 set, None=취소. 기본 전체 선택."""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                                     QPushButton, QLabel, QAbstractItemView)
        dlg = QDialog(self)
        dlg.setWindowTitle("Select dates to fit")
        dlg.resize(int(280 * self._s), int(420 * self._s))
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"{len(dates)} dates found — select (multi):"))
        lw = QListWidget()
        lw.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for d in dates:
            lw.addItem(d)
        lw.selectAll()
        lay.addWidget(lw)
        bar = QHBoxLayout()
        b_all = QPushButton("All"); b_all.clicked.connect(lw.selectAll)
        b_none = QPushButton("None"); b_none.clicked.connect(lw.clearSelection)
        b_ok = QPushButton("OK"); b_ok.clicked.connect(dlg.accept)
        b_cancel = QPushButton("Cancel"); b_cancel.clicked.connect(dlg.reject)
        for b in (b_all, b_none, b_ok, b_cancel):
            bar.addWidget(b)
        lay.addLayout(bar)
        from PyQt6.QtWidgets import QDialog as _QD
        if dlg.exec() != _QD.DialogCode.Accepted:
            return None
        return set(i.text() for i in lw.selectedItems())

    # ── file_list entry helpers ──────────────────────────────────────────────
    def _entry_filepath(self, entry):
        """Returns the raw filepath string from a file_list entry (str or tuple)."""
        return entry[0] if isinstance(entry, tuple) else entry

    def _entry_display_name(self, entry):
        """Returns the display name shown in the table for a file_list entry."""
        if isinstance(entry, tuple):
            fp, ri = entry
            return f"{os.path.basename(fp)} [{ri:04d}]"
        return os.path.basename(entry)

    def _entry_row_index(self, entry):
        """Returns the scan row index (0 for single-scan / plain files)."""
        return entry[1] if isinstance(entry, tuple) else 0

    @staticmethod
    def _row_index_from_display_name(display_name):
        """Table display names always end in ' [NNNN]' (worker.py appends the scan's
        real row index even for single-scan files — see _write_row_cells/'File').
        A plain (non-tuple) file_list entry has no row index of its own, so pull the
        actual scan row straight out of that suffix instead of assuming 0 — a multi-
        scan file (Mega-Matrix/alpha_trace) needs the real row to re-load the right
        scan, not just its first one."""
        m = re.search(r'\[(\d+)\]\s*$', display_name)
        return int(m.group(1)) if m else 0

    def _entry_from_display_name(self, display_name, file_list=None):
        """Finds the file_list entry for display_name's file, ignoring the trailing
        ' [NNNN]' scan-row suffix for plain entries (which don't carry a row index —
        use _row_index_from_display_name for that).

        file_list defaults to self.file_list (the currently active channel tab's
        files) but callers that already know which channel the display_name belongs
        to (e.g. a multi-channel results table row) should pass that channel's own
        list explicitly — self.file_list only ever holds one channel's files."""
        for e in (self.file_list if file_list is None else file_list):
            if isinstance(e, tuple):
                if self._entry_display_name(e) == display_name:
                    return e
            elif display_name.startswith(os.path.basename(e) + " ["):
                return e
        return None

    # ────────────────────────────────────────────────────────────────────────

    def _update_file_table(self, file_list):
        """
        Stores file paths and shows them in the table.

        Araon Mega-Matrix files contain many scans per row — expansion into
        individual (filepath, row_index) entries is deferred to the Worker
        thread so the UI never freezes during large folder loads.
        After loading, auto-detect the channel count from the first file.
        """
        self.file_list = list(file_list)          # plain strings only — no expansion here
        # 새 데이터를 로드하면 이전 Run의 결과는 이 파일셋에 대한 게 아니므로 무효 —
        # 지워야 _show_channel_files의 '결과 있으면 표 유지' 가드가 새로 로드한 파일목록을
        # 계속 가리지 않는다(안 지우면 채널탭 넘겨봐도 예전 결과화면이 계속 붙어있어 다른
        # 채널에 데이터가 제대로 들어갔는지 확인이 안 됨).
        self.results = []
        # 로드한 데이터를 '현재 활성 채널'이 소유(자동분배 X) — RUN이 채널마다 자기 리스트로 핏
        if getattr(self, '_active_channel', None) is not None:
            self._channel_files[self._active_channel] = list(self.file_list)
        self.table.setRowCount(len(self.file_list))
        self.table.clearContents()

        for i, fp in enumerate(self.file_list):
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(fp)))

        ch = getattr(self, '_active_channel', 1)
        # L6: 파일 수 + 날짜범위 요약
        import re as _re
        _ds = sorted({m.group(0) for fp in self.file_list
                      for m in [_re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(fp))] if m})
        _rng = f" · {_ds[0]}~{_ds[-1]}" if len(_ds) > 1 else (f" · {_ds[0]}" if _ds else "")
        self.status.setText(f"CH{ch} — {len(self.file_list)} file(s){_rng}")
        self._auto_detect_channels()
        self._refresh_setup_status()   # 입력 종류(알파/raw) 반영 → I0/R status 갱신

    def _auto_detect_channels(self):
        """Detect how many spectrum channels the loaded files contain and update the UI label."""
        if not self.file_list:
            return
        try:
            first = self._entry_filepath(self.file_list[0])
            from core.data_io import DataIO
            n = DataIO.detect_channels(first)
            self._detected_channels = n
            ch_names = {1: "CH1", 2: "CH1+CH2", 3: "CH1+CH2+CH3"}
            ch_labels = {
                1: "1채널  (Cold / single-cavity)",
                2: "2채널  (Hot:  CH1 PNs 180°C  +  CH2 ANs 300°C)",
                3: "3채널  (CH1 + CH2 + CH3)",
            }
            label = ch_labels.get(n, f"{n}CH")
            self.lbl_channel_info.setText(label)
            # (채널별 설정은 좌측 채널 탭으로 — 여기선 감지 정보만 표시)
            colours = {1: "#1565C0", 2: "#6A1B9A", 3: "#2E7D32"}
            self.lbl_channel_info.setStyleSheet(
                f"color: {colours.get(n, '#333')}; font-weight: bold;")
            self.status.setText(
                f"{len(self.file_list)} file(s) loaded  —  {ch_names.get(n, str(n)+'CH')} detected")
        except Exception as e:
            print(f"[channel detect] {e}")

    def apply_convolution(self):
        """Applies Instrument Line Shape blur (Voigt kernel) based on entered FWHM values."""
        if not self.engine.is_engine_ready():
            QMessageBox.warning(self, "Warning", "Please load references first.")
            return

        fwhm_g = self.spin_fwhm.value()
        fwhm_l = self.spin_fwhm_lorentzian.value()
        self.engine.apply_ils_convolution(fwhm_g, fwhm_l)
        self.refresh_viewer()
        label = (f"Voigt (G={fwhm_g:.2f}, L={fwhm_l:.2f} px)"
                 if fwhm_l > 0.1 else f"Gaussian FWHM={fwhm_g:.2f} px")

        # Mark ILS as applied → button turns green
        self._ils_applied = True
        if hasattr(self, 'btn_apply_ils'):
            self.btn_apply_ils.setStyleSheet(
                "font-weight: bold;")

        self._refresh_setup_status()
        QMessageBox.information(self, "Applied", f"ILS Blur ({label}) successfully applied.")
        
    def open_selector(self):
        """Opens the visual RangeSelectorDialog."""
        if not self.file_list: 
            return
        try: 
            mn, mx = int(self.txt_min.text()), int(self.txt_max.text())
        except Exception: 
            mn, mx = 0, 950
            
        # Use the middle file as a representative spectrum for the visual preview
        mid_entry = self.file_list[len(self.file_list) // 2]
        mid_file = self._entry_filepath(mid_entry)
        # 채널 탭 목록 → 다이얼로그 '적용 채널'로 범위를 채널별 설정
        tb = self._channel_tabbar
        channels = [(tb.tabData(i), tb.tabText(i)) for i in range(tb.count())]
        # 채널별 대표 스펙트럼 경로 — '적용 채널' 바꾸면 그 채널 데이터로 그래프 갱신
        # channel_files: 전체 리스트 → 다이얼로그의 File 콤보/★Score(추천)용
        channel_paths = {}
        channel_files = {}
        for ch, _lbl in channels:
            flist = self._channel_files.get(ch)
            if flist:
                channel_paths[int(ch)] = self._entry_filepath(flist[len(flist) // 2])
                channel_files[int(ch)] = [self._entry_filepath(e) for e in flist]
        # Vis.에서 ★Score/수동으로 고른 '채널별 대표 알파'를 세션 내내 기억 —
        # 다이얼로그는 매번 새로 만들어지므로 선택을 여기(app_window)에 보관해 넘긴다.
        if not hasattr(self, '_vis_chosen_alpha'):
            self._vis_chosen_alpha = {}
        # 채널별 핏레인지(nm) — 다이얼로그가 채널 전환 시 그 채널의 범위를 보여주게.
        # (활성 채널은 스핀박스, 나머지는 채널 config 스냅샷에서)
        channel_ranges = {}
        for ch, _lbl in channels:
            try:
                if ch == self._active_channel:
                    lo_nm = float(self.spin_fit_start_nm.value())
                    hi_nm = float(self.spin_fit_end_nm.value())
                else:
                    cfg = self._channel_configs.get(ch) or {}
                    lo_nm = float(cfg.get('fit_start_nm', 435.0))
                    hi_nm = float(cfg.get('fit_end_nm', 480.0))
                channel_ranges[int(ch)] = (lo_nm, hi_nm, True)
            except (TypeError, ValueError):
                pass
        self.sel_dlg = RangeSelectorDialog(mid_file, mn, mx, self.engine, channels=channels,
                                           channel_paths=channel_paths,
                                           active_channel=self._active_channel,
                                           channel_files=channel_files,
                                           chosen_files=self._vis_chosen_alpha,
                                           channel_ranges=channel_ranges)
        self.sel_dlg.apply_range.connect(self.update_range)
        self.sel_dlg.apply_channel.connect(self._set_channel_range_from_selector)
        self.sel_dlg.exec()

    def update_range(self, min_idx, max_idx):
        """Updates the text boxes with the visual selection."""
        if getattr(self, '_analysis_running', False):
            return
        self.txt_min.setText(str(min_idx))
        self.txt_max.setText(str(max_idx))

    def _set_channel_range_from_selector(self, ch, lo, hi, is_nm):
        """Vis.Select에서 고른 범위를 해당 채널의 nm 범위로 설정."""
        if getattr(self, '_analysis_running', False):
            return
        if lo > hi:
            lo, hi = hi, lo
        if not is_nm:
            # 픽셀 선택이면 마스터 wavecal로 nm 변환(가능할 때)
            wl = getattr(self, 'wavelengths', None)
            if wl is not None and len(wl) > int(hi):
                lo, hi = float(wl[int(lo)]), float(wl[int(hi)])
        if ch == self._active_channel:
            self.spin_fit_start_nm.setValue(lo)
            self.spin_fit_end_nm.setValue(hi)
            self.set_range_from_nm()   # 픽셀 범위(txt_min/max)도 갱신
        else:
            cfg = self._channel_configs.get(ch)
            if cfg is not None:
                cfg['fit_start_nm'] = lo
                cfg['fit_end_nm'] = hi
        self.status.setText(f"CH{ch} Fit range = {lo:.1f}~{hi:.1f} nm")

    def apply_roi_from_graph(self, min_val, max_val):
        """Updates the fitting range directly from the fast monitor ROI selection."""
        if getattr(self, '_analysis_running', False):
            return
        self.txt_min.setText(str(min_val))
        self.txt_max.setText(str(max_val))
        self.status.setText(f"Range Selected: {min_val} ~ {max_val}")

    # ---------------------------------------------------------
    # Multithreading Analysis Execution (Worker)
    # ---------------------------------------------------------
    @staticmethod
    def _alpha_file_meta(fp):
        """알파 파일 헤더에서 (channel_index, label) 추출. 우리 Alpha Export가
        '# channel=N  label=X' 를 항상 기록 → 캠페인 무관 generic 매핑용.
        반환: (int 또는 None, str 소문자 또는 '')."""
        ch, lbl = None, ''
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                for _ in range(15):
                    ln = f.readline()
                    if not ln or not ln.startswith('#'):
                        break
                    if 'channel=' in ln:
                        try:
                            ch = int(ln.split('channel=', 1)[1].strip().split()[0])
                        except (ValueError, IndexError):
                            pass
                    if 'label=' in ln:
                        lbl = ln.split('label=', 1)[1].strip().split()[0].lower()
        except Exception:
            pass
        return ch, lbl

    def _channel_data_groups(self):
        """채널별 데이터 파일 그룹. **알파 헤더의 채널 인덱스(# channel=N)가 최우선**
        → 캠페인 무관(라벨 타이핑 불필요). 헤더 인덱스가 없을 때만 data_label로 매칭
        (파일명/헤더 label/채널index 어느 거로든). 둘 다 없으면 기존 _alpha_groups."""
        if self._active_channel in self._channel_configs:
            self._channel_configs[self._active_channel] = self._capture_config()
        labels = {ch: ((cfg.get('data_label') or '').strip().lower())
                  for ch, cfg in self._channel_configs.items() if cfg}
        tab_chs = set(self._channel_configs.keys())
        groups = {}
        for entry in self.file_list:
            fp = self._entry_filepath(entry)
            name = os.path.basename(str(fp)).lower()
            hdr_ch, hdr_lbl = self._alpha_file_meta(fp)
            assigned = None
            # 1) 알파 헤더의 채널 인덱스(# channel=N)가 최우선 — 유일하게 권위 있는 값.
            #    라벨은 표시용 문자열이라 언제든 바뀔 수 있고, 라벨을 먼저 보면
            #    "파일명 _ANs_ ↔ 다른 탭의 data_label 'ANs'" 처럼 교차 매칭돼
            #    ROI1 알파가 ch2로 들어가는 사고가 난다(2026-07 실제 발생 위험).
            if hdr_ch in tab_chs:
                assigned = hdr_ch
            # 2) 헤더 인덱스가 없을 때(일반 raw 입력 등)만 data_label로 매칭
            if assigned is None:
                for ch, lbl in labels.items():
                    if lbl and (lbl in name or lbl == hdr_lbl or lbl == f"ch{ch}"):
                        assigned = ch
                        break
            if assigned is not None:
                groups.setdefault(assigned, []).append(entry)
        if groups:
            return groups
        return self._alpha_groups

    def _alpha_channel_groups(self, file_list):
        """입력이 모두 알파trace 파일이면 파일명(_PNs_/_ANs_/_CH3_/_Cold_)으로
        채널 그룹화해 {채널idx: [entries]} 반환. 하나라도 알파trace가 아니면 None
        (= 일반 raw 입력이므로 기존 채널 검출 로직 사용)."""
        if not file_list:
            return None
        label_to_ch = {'pns': 1, 'ans': 2, 'ch3': 3, 'cold': 1}
        groups = {}
        for entry in file_list:
            fp = entry if isinstance(entry, str) else self._entry_filepath(entry)
            name = os.path.basename(str(fp)).lower()
            if 'alpha_trace' not in name:
                return None
            ch = 1
            for lbl, c in label_to_ch.items():
                if f'_{lbl}_' in name:
                    ch = c
                    break
            groups.setdefault(ch, []).append(entry)
        return groups or None

