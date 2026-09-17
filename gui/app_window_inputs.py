"""gui/app_window_inputs.py
CAESARAnalyzer §4~§6 — 입력(I0/dark/offset/flags) · 알파 생성 · I0/R 진단 (gui/app_window.py에서 분리).

**순수 이동이다.** 메서드 본문은 한 글자도 안 고쳤다 — 호출부가 전부 self.xxx()라
믹스인으로 옮기는 것만으로 동작이 같다. 로직 개선은 다음 PR로.
가드는 tools/test_app_window_smoke.py (표면 골든 + 믹스인 이름 충돌 검사).

한 파일로 묶은 이유: 세 섹션이 raw 입력 -> 알파 -> I0/R 진단으로 한 줄기다.
§4 혼자는 91줄이라 따로 파일을 만들 값이 없다.
"""
import os
import numpy as np
import pandas as pd
import pyqtgraph as pg

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QMenu, QMessageBox
from core.data_io import DataIO
from core.paths import WV_CAL_DIR
from .worker import AlphaExportWorker


class InputsAlphaMixin:
    """§4~§6 — 입력(I0/dark/offset/flags) · 알파 생성 · I0/R 진단. CAESARAnalyzer에 믹스인된다."""

    # ══════════════════════════════════════════════════════════════════════
    # §4  입력: I0 / dark / offset / flags
    # ══════════════════════════════════════════════════════════════════════
    def browse_i0_file(self):
        """Browse and set the I0 (Zero-air) measurement file."""
        filepath, _ = QFileDialog.getOpenFileName(self, "Select I0 File", self._dlg_dir('i0'), "Data Files (*.dat *.txt *.csv)")
        self._dlg_dir('i0', filepath)
        if filepath:
            self.set_i0_path(filepath)

    def browse_dark_file(self):
        """Browse and load a dark current spectrum (.dat/.txt/.csv 또는 MATLAB .mat)."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select Dark Spectrum", self._dlg_dir('dark'),
            "Data Files (*.dat *.txt *.csv *.mat);;All Files (*)")
        if not filepath:
            return
        self._dlg_dir('dark', filepath)
        try:
            import numpy as np
            if filepath.lower().endswith(".mat"):
                import scipy.io
                mat = scipy.io.loadmat(filepath)
                # MATLAB 구조체: Dark_240224.ch1
                struct_keys = [k for k in mat.keys() if not k.startswith('_')]
                if not struct_keys:
                    raise ValueError("No data key in the mat file.")
                struct_key = struct_keys[0]
                struct = mat[struct_key]
                ch_key = "ch1"
                if hasattr(struct, 'dtype') and ch_key in struct.dtype.names:
                    dark_raw = np.asarray(struct[ch_key][0, 0], dtype=float).flatten()
                else:
                    dark_raw = np.asarray(struct, dtype=float).flatten()
            else:
                _, dark_raw = DataIO.load_measurement(filepath, pixel_min=0)
            self.dark_data = dark_raw
            self.lbl_dark_path.setText(os.path.basename(filepath))
            self.lbl_dark_path.setStyleSheet("color: green; font-weight: bold;")
            self.status.setText(
                f"Dark current loaded: {os.path.basename(filepath)}  "
                f"({len(dark_raw)} px, mean={dark_raw.mean():.1f})"
            )
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Failed to load dark file:\n{e}")

    def browse_offset_file(self):
        """Browse and load a detector offset spectrum (ADC pedestal, integration-time independent)."""
        filepath, _ = QFileDialog.getOpenFileName(self, "Select Offset Spectrum", self._dlg_dir('offset'), "Data Files (*.dat *.txt *.csv)")
        self._dlg_dir('offset', filepath)
        if not filepath:
            return
        try:
            _, offset_raw = DataIO.load_measurement(filepath, pixel_min=0)
            self.offset_data = offset_raw
            self.lbl_offset_path.setText(os.path.basename(filepath))
            self.lbl_offset_path.setStyleSheet("color: green; font-weight: bold;")
            self.status.setText(f"Detector offset loaded: {os.path.basename(filepath)}")
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Failed to load offset file:\n{e}")

    def _parse_flags(self, text):
        """'500, 503' → [500, 503]. Returns list of ints; falls back to [] on parse error."""
        try:
            return [int(v.strip()) for v in text.split(',') if v.strip()]
        except ValueError:
            return []

    def browse_alpha_save_dir(self):
        """Browse and set the output directory for intermediate alpha spectra."""
        d = QFileDialog.getExistingDirectory(self, "Select Alpha spool folder", self._dlg_dir('alpha_save'))
        self._dlg_dir('alpha_save', d)
        if d:
            self.alpha_save_dir = d
            self.lbl_alpha_dir.setText(os.path.basename(d) or d)
            self.lbl_alpha_dir.setStyleSheet("color: #1565C0; font-weight: bold;")

    @staticmethod
    def _read_drnam_std_t(mat_path):
        """박사님 _avg_60s.mat 에서 std_t bin 경계(st,end)를 연초기준 초 (N,2)로.
        std_t_st/std_t_end(doy) → sec=(doy-1)*86400. 실패 시 None."""
        try:
            import scipy.io as sio
            m = sio.loadmat(mat_path)
            st = np.asarray(m['std_t_st'], dtype=float).flatten()
            en = np.asarray(m['std_t_end'], dtype=float).flatten()
            n = min(len(st), len(en))
            return np.column_stack([(st[:n] - 1.0) * 86400.0, (en[:n] - 1.0) * 86400.0])
        except Exception:
            return None

    # ══════════════════════════════════════════════════════════════════════
    # §5  알파 생성 (export + generator)
    # ══════════════════════════════════════════════════════════════════════
    def export_alpha_files(self, file_list=None, out_dir=None, avg_sec=None,
                           purge_settle_sec=None,
                           status_cb=None, done_cb=None, drnam_mat=None, ch_tab_map=None,
                           progress_cb=None, channels=None, gen_px_range=None, rt_map=None):
        """BBCEAS alpha만 계산해 저장(피팅 없음). Hot 2채널이면 채널별로 각각.

        Alpha Generator 팝업이 raw 파일목록/출력폴더/avgsec를 넘겨 호출할 수 있다.
        인자가 없으면(레거시) 메인 file_list/프롬프트/메인 avgsec를 사용.
        wavecal/핏레인지/cavity/flags 는 항상 메인 UI 설정을 재사용한다.
        drnam_mat: 박사님 _avg_60s.mat 경로를 주면 그 std_t 그리드에 binning + 전체 2048px
        + per-bin .dat(ch{N}_{YYYYMMDD}_NNNNNN.dat) 박사님 형식으로 출력.
        반환: True(시작됨) / False(검증 실패)."""
        flist = list(file_list) if file_list is not None else getattr(self, 'file_list', None)
        if not flist:
            QMessageBox.warning(self, "No Files", "Load measurement (raw) files first.")
            return False
        # raw 채널 → 핏세팅 탭 매핑(Alpha Generator). 비우면 raw 채널 N → 탭 N.
        self._alpha_ch_tab_map = {int(k): int(v) for k, v in (ch_tab_map or {}).items()}
        # 생성할 채널 선택(None=전체). 이미 만든 채널 재생성 방지용.
        self._alpha_sel_channels = set(int(c) for c in channels) if channels else None
        if getattr(self, 'wavelengths', None) is None and self.engine._wave_axis is None:
            QMessageBox.warning(self, "No Wavelength Cal",
                                "Load a wavelength calibration file first.")
            return False
        if out_dir is None:
            out_dir = QFileDialog.getExistingDirectory(self, "Select Alpha output folder", self._dlg_dir('alpha_out'))
            self._dlg_dir('alpha_out', out_dir)
        if not out_dir:
            return False

        # 채널 수: 넘겨받은 raw 첫 파일에서 감지(메인 _detected_channels도 갱신해 per-ch 설정 일치)
        try:
            from core.data_io import DataIO
            n_ch = int(DataIO.detect_channels(self._entry_filepath(flist[0])) or 1)
        except Exception:
            n_ch = int(getattr(self, '_detected_channels', 1) or 1)
        self._detected_channels = n_ch
        # 현재 채널 탭 설정을 스냅샷(알파 생성이 채널 탭의 wavecal/범위 사용)
        if self._active_channel in self._channel_configs:
            self._channel_configs[self._active_channel] = self._capture_config()

        # 박사님 형식이면 전체 2048px + std_t 그리드
        self._alpha_drnam_bins = None
        self._alpha_drnam_date = ""
        if drnam_mat:
            bins = self._read_drnam_std_t(drnam_mat)
            if bins is None or not len(bins):
                QMessageBox.warning(self, "std_t failed",
                                    "Could not read std_t_st/std_t_end from _avg_60s.mat.")
                return False
            self._alpha_drnam_bins = bins
            import re as _re
            m = _re.search(r'(\d{4})-(\d{2})-(\d{2})', os.path.basename(self._entry_filepath(flist[0])))
            self._alpha_drnam_date = (m.group(1) + m.group(2) + m.group(3)) if m else ""

        configs = self._build_alpha_channel_configs(n_ch, full_px=bool(drnam_mat),
                                                    gen_px_range=gen_px_range)
        if not configs:
            QMessageBox.warning(self, "Channel config failed",
                                "Could not build per-channel wavecal/pixel range.\n"
                                f"Hot (≥2ch) needs the {self._WV_CAL_BASE}\\roi1,roi2 Calib files.")
            return False
        _sel = getattr(self, '_alpha_sel_channels', None)
        _want = _sel if _sel is not None else set(range(1, n_ch + 1))
        got = set(c['channel'] for c in configs)
        _missing = sorted(_want - got)
        if _missing:
            QMessageBox.warning(self, "Some channels lack wavecal",
                                f"Only {sorted(got)} of the selected channels will be generated. Missing: {_missing}.\n"
                                f"Missing channels lack wavecal (channel tab or {self._WV_CAL_BASE}\\roiN)), skipped.\n"
                                "Continuing.")

        # 채널별 워커를 순차 실행(큐). Hot=2채널 → PNs, ANs 각각 생성.
        self._alpha_queue      = list(configs)
        self._alpha_file_list  = flist
        self._alpha_out_dir    = out_dir
        self._alpha_avgsec     = float(avg_sec) if avg_sec is not None else 60.0
        # 교정 직후 퍼지 세틀링(초) — 캐비티 잔류가스. 기본 60 은 여수 콜드 실측.
        self._alpha_purge_settle = float(purge_settle_sec) if purge_settle_sec is not None else 60.0
        self._alpha_rt_map     = dict(rt_map or {})   # {raw채널 -> R(t) npz 경로} 채널별
        self._alpha_dark       = getattr(self, 'dark_data', None)
        self._alpha_done_msgs  = []
        self._alpha_status_cb  = status_cb   # 팝업 진행표시(옵션)
        self._alpha_user_done_cb = done_cb   # 팝업 완료콜백(옵션)
        self._alpha_progress_cb = progress_cb  # 팝업 진행바(done, total) 콜백(옵션)
        self._alpha_total       = 0
        self._alpha_ch_done     = 0          # 완료된 채널 수(멀티채널 진행 표시용)
        self._alpha_n_ch        = n_ch
        self.status.setText(f"Alpha export started ({n_ch} channels)...")
        self._start_next_alpha_export()
        return True

    # wv_cal 자동탐색 베이스 (채널별 파장보정 — 레포 번들 reference_data/wv_cal)
    _WV_CAL_BASE = WV_CAL_DIR

    def _channel_wl_path(self, ch):
        """채널 ch의 wavecal 파일 경로 — 채널 탭 config. 활성 채널은 현재 로드된 경로."""
        if ch == self._active_channel:
            return getattr(self, 'loaded_wl_path', '')
        cfg = self._channel_configs.get(ch) or {}
        return cfg.get('wl_path', '')

    def _channel_wave_cal(self, n_ch, ch):
        """채널(탭) → per-pixel 파장 배열. 우선순위: 채널 탭 wavecal(wl_path) →
        1ch=로드된 cal → ≥2ch=Output\\wv_cal\\{roi1,roi2,..} 최신 Calib."""
        wlp = self._channel_wl_path(ch)
        if wlp and os.path.exists(wlp):
            arr = self._load_wavecal_array(wlp)
            if arr is not None and len(arr):
                return np.asarray(arr, dtype=float).flatten()
        if n_ch == 1:
            wl = getattr(self, 'wavelengths', None)
            return np.asarray(wl, dtype=float).flatten() if wl is not None else None
        roi = {1: 'roi1', 2: 'roi2', 3: 'roi3'}.get(ch)
        if roi:
            import glob
            d = os.path.join(self._WV_CAL_BASE, roi)
            cands = sorted(glob.glob(os.path.join(d, 'Calib_*.txt'))) if os.path.isdir(d) else []
            if cands:
                try:
                    return np.loadtxt(cands[-1]).flatten()
                except Exception:
                    pass
        wl = getattr(self, 'wavelengths', None)   # 폴백: 로드된 단일 cal
        return np.asarray(wl, dtype=float).flatten() if wl is not None else None

    def _fit_nm_for_channel(self, ch):
        """채널별 Fit 범위(nm) — 채널 탭 config. 활성 채널은 현재 스핀값. (lo,hi) 정렬."""
        if ch == self._active_channel:
            lo, hi = self.spin_fit_start_nm.value(), self.spin_fit_end_nm.value()
        else:
            cfg = self._channel_configs.get(ch)
            if cfg:
                lo, hi = cfg.get('fit_start_nm', 435.0), cfg.get('fit_end_nm', 480.0)
            else:
                lo, hi = self.spin_fit_start_nm.value(), self.spin_fit_end_nm.value()
        return (lo, hi) if lo <= hi else (hi, lo)

    def _fit_unit_for_channel(self, ch):
        """채널의 핏 단위('nm'|'px'). 활성 채널은 콤보, 아니면 config."""
        if ch == self._active_channel and hasattr(self, 'cb_fit_unit'):
            return self.cb_fit_unit.currentText()
        cfg = self._channel_configs.get(ch)
        return cfg.get('fit_unit', 'nm') if cfg else 'nm'

    def _fit_px_for_channel(self, ch):
        """채널의 핏범위 픽셀(f_min, f_max). 활성=txt_min/max, 아니면 config."""
        if ch == self._active_channel:
            try:
                a, b = int(self.txt_min.text()), int(self.txt_max.text())
            except Exception:
                a, b = 0, 2047
        else:
            cfg = self._channel_configs.get(ch) or {}
            try:
                a, b = int(cfg.get('f_min', 0)), int(cfg.get('f_max', 2047))
            except Exception:
                a, b = 0, 2047
        return (a, b) if a <= b else (b, a)

    def _build_alpha_channel_configs(self, n_ch, full_px=False, gen_px_range=None):
        """채널마다 (채널idx, 라벨, 파장슬라이스, pixel_min/max).
        full_px=True(박사님 형식)면 핏윈도우 무시하고 전체 2048px 사용."""
        tab_map = getattr(self, '_alpha_ch_tab_map', {}) or {}
        sel = getattr(self, '_alpha_sel_channels', None)
        configs = []
        for ch in range(1, n_ch + 1):
            if sel is not None and ch not in sel:
                continue   # 사용자가 선택 안 한 채널은 생성 안 함(이미 만든 채널 재생성 방지)
            # raw 채널 ch가 어느 채널 탭 설정(wavecal/범위)을 쓸지(기본: 같은 번호 탭)
            tab = int(tab_map.get(ch, ch))
            wave_full = self._channel_wave_cal(n_ch, tab)
            if wave_full is None or len(wave_full) == 0:
                continue
            if full_px:
                pmin, pmax = 0, len(wave_full)
            elif gen_px_range is not None:
                # Alpha Generator의 '생성 px' 범위 — 핏레인지와 독립.
                # 알파엔 이 구간만 저장되므로 핏 윈도우보다 넉넉하게(기본 700~1700).
                pmin = max(0, min(int(gen_px_range[0]), len(wave_full) - 1))
                pmax = max(pmin + 1, min(int(gen_px_range[1]), len(wave_full)))
            elif self._fit_unit_for_channel(tab) == 'px':
                pmin, pmax = self._fit_px_for_channel(tab)
                pmin = max(0, min(pmin, len(wave_full) - 1))
                pmax = max(pmin + 1, min(pmax, len(wave_full)))
            else:
                start_nm, end_nm = self._fit_nm_for_channel(tab)
                pmin = int(np.abs(wave_full - start_nm).argmin())
                pmax = int(np.abs(wave_full - end_nm).argmin())
                if pmin > pmax:
                    pmin, pmax = pmax, pmin
                if pmax <= pmin:
                    pmax = pmin + 1
            # 라벨: 매핑된 탭의 data_label(사용자 지정) 있으면 그걸, 없으면 CH{ch}
            _tcfg = self._channel_configs.get(tab) or {}
            lbl = (_tcfg.get('data_label') or '').strip() or f'CH{ch}'
            configs.append(dict(channel=ch, label=lbl,
                                wave_nm=wave_full[pmin:pmax],
                                pixel_min=pmin, pixel_max=pmax))
        return configs

    def _start_next_alpha_export(self):
        if not getattr(self, '_alpha_queue', None):
            done = getattr(self, '_alpha_done_msgs', [])
            self.status.setText(f"Alpha export complete  {self._alpha_out_dir}")
            cb = getattr(self, '_alpha_user_done_cb', None)
            if cb:   # Alpha Generator 팝업이 띄운 경우 콜백으로 알림(자체 메시지)
                cb(self._alpha_out_dir, list(done))
            else:
                QMessageBox.information(
                    self, "Alpha Export complete",
                    "Per-channel α saved:\n" + "\n".join(done) +
                    f"\n\nLocation:\n{self._alpha_out_dir}\n"
                    "Filename: {source}_{channel}_alpha_trace.dat\n"
                    "Usable in Result Viewer / Analysis (RUN).")
            # close-the-loop: 생성한 폴더를 Pipeline Health에 자동 연결 → 점검 까먹지 않게.
            self._alpha_qc_after_export(self._alpha_out_dir)
            return
        cfg = self._alpha_queue.pop(0)
        self._alpha_status(f"Alpha [{cfg['label']}] computing (px {cfg['pixel_min']}~{cfg['pixel_max']})...")
        self._alpha_export_worker = AlphaExportWorker(
            file_list     = self._alpha_file_list,
            pixel_min     = cfg['pixel_min'],
            pixel_max     = cfg['pixel_max'],
            wave_nm       = cfg['wave_nm'],
            flag_za       = self._parse_flags(self.txt_flag_za.text()),
            flag_he       = self._parse_flags(self.txt_flag_he.text()),
            flag_amb      = self._parse_flags(self.txt_flag_amb.text()),
            rl_factor     = self.spin_rl_factor.value(),
            cavity_len    = self.spin_d_len.value(),
            output_dir    = self._alpha_out_dir,
            dark_spectrum = self._alpha_dark,
            # dark scale·detector offset·stray light — RUN 경로와 물리 일치(기본값=무회귀).
            dark_scale_factor    = self.spin_dark_scale.value(),
            offset_spectrum      = getattr(self, 'offset_data', None),
            offset_scale_factor  = self.spin_offset_scale.value(),
            stray_light_fraction = self.spin_stray_light.value(),
            channel       = cfg['channel'],
            avg_sec       = self._alpha_avgsec,
            purge_settle_sec = self._alpha_purge_settle,
            channel_label = cfg['label'],
            std_t_bins    = getattr(self, '_alpha_drnam_bins', None),
            drnam_date    = getattr(self, '_alpha_drnam_date', ''),
            drnam_chlabel = f"ch{cfg['channel']}",
            # wide 형식: 멀티채널이면 ch{N}/ 하위폴더로 분리(단일이면 평면)
            channel_subdir = (f"ch{cfg['channel']}" if int(getattr(self, '_detected_channels', 1) or 1) > 1 else ""),
            rt_path        = getattr(self, '_alpha_rt_map', {}).get(cfg['channel']),   # 채널별 R(t)
            campaign       = self._campaign(),   # A3: {out}/{campaign}/{날짜}/alpha/…
        )
        n_ch_tot = max(1, int(getattr(self, '_alpha_n_ch', 1) or 1))
        self._alpha_export_worker.total_ready.connect(
            lambda tot: setattr(self, '_alpha_total', max(1, int(tot))))
        self._alpha_export_worker.progress.connect(
            lambda n, lbl=cfg['label']: self._alpha_on_progress(n, lbl, n_ch_tot))
        # 로그(print) + GUI 상태줄/팝업 둘 다 — Indexing/cache/saved 진행이 사용자에게 보이게
        self._alpha_export_worker.status_msg.connect(
            lambda m, _lbl=cfg['label']: (print(f"[AlphaExport] {m}"),
                                          self._alpha_status(f"[{_lbl}] {m}")))
        self._alpha_export_worker.finished.connect(
            lambda res, lbl=cfg['label']: self._on_alpha_channel_done(res, lbl))
        self._alpha_export_worker.start()

    def _alpha_status(self, msg):
        """alpha export 진행 표시 — 메인 상태바 + (팝업 콜백 있으면) 팝업에도."""
        self.status.setText(msg)
        cb = getattr(self, '_alpha_status_cb', None)
        if cb:
            cb(msg)

    def open_alpha_generator(self):
        """Raw → Alpha 생성 팝업창. 메인 UI 설정(wavecal/핏레인지/cavity/flags) 재사용."""
        if getattr(self, 'wavelengths', None) is None and self.engine._wave_axis is None:
            QMessageBox.warning(self, "No Wavelength Cal",
                                "Load a wavelength calibration in the main window first\n"
                                "(Alpha generation uses that setting).")
            return
        from .ui_alpha_gen import AlphaGeneratorDialog
        dlg = AlphaGeneratorDialog(self)
        dlg.exec()

    def open_peak_trend(self):
        """flag별(ZA/He/Sampling) 피크 트렌드 뷰어 팝업."""
        from .ui_peak_trend import PeakTrendDialog
        dlg = PeakTrendDialog(self, default_dir=self._dlg_dir('data'))
        dlg.exec()

    def _alpha_on_progress(self, done, lbl, n_ch_tot):
        """알파 생성 진행을 %로 표시(채널 내 비율 + 채널 진척 합산) + 팝업 진행바 콜백."""
        tot = max(1, int(getattr(self, '_alpha_total', 1)))
        frac = min(1.0, done / tot)
        ch_done = int(getattr(self, '_alpha_ch_done', 0))
        pct = int(((ch_done + frac) / max(1, n_ch_tot)) * 100)
        self._alpha_status(f"[{lbl}] {pct}%  ({done:,}/{tot:,} scans)")
        cb = getattr(self, '_alpha_progress_cb', None)
        if cb:
            cb(pct, 100)

    def _on_alpha_channel_done(self, result, label):
        if str(result).startswith("ERROR"):
            self._alpha_done_msgs.append(f"  [{label}] failed: {result}")
            self.status.setText(f"Alpha [{label}] failed")
        else:
            self._alpha_done_msgs.append(f"[{label}] ")
        self._alpha_ch_done = int(getattr(self, '_alpha_ch_done', 0)) + 1
        self._alpha_total = 0   # 다음 채널 total 재설정 대기
        # 끝난 워커를 wait()로 완전 종료시키고 참조 보관 — 다음 채널 워커로 덮어쓸 때
        # 실행 중인 QThread가 GC돼 "Destroyed while thread is still running"으로
        # 다음 채널이 시작 못 하던 버그 수정.
        w = getattr(self, '_alpha_export_worker', None)
        if w is not None:
            try:
                w.wait(10000)
            except Exception:
                pass
            self._alpha_finished_workers = getattr(self, '_alpha_finished_workers', [])
            self._alpha_finished_workers.append(w)
            self._alpha_export_worker = None
        self._start_next_alpha_export()

    # ══════════════════════════════════════════════════════════════════════
    # §6  I0 / R 진단 (auto-extract, diagnostic plot)
    # ══════════════════════════════════════════════════════════════════════
    def auto_extract_i0(self):
        """Scans the loaded file list for ZA-flagged files and averages them to form I0."""
        if not hasattr(self, 'file_list') or not self.file_list:
            QMessageBox.warning(self, "No Files", "Load a measurement file list first.")
            return

        flag_za_list = self._parse_flags(self.txt_flag_za.text()) if hasattr(self, 'txt_flag_za') else [500, 501, 502, 503]
        # I₀ 추출: 500(injecting)만 사용
        za_meas_flag = 500 if 500 in flag_za_list else flag_za_list[0] if flag_za_list else 500
        za_spectra = []
        for entry in self.file_list:
            fp = self._entry_filepath(entry)
            ri = self._entry_row_index(entry)
            try:
                _, raw, flag, _, _ = DataIO.load_measurement_with_hk(fp, pixel_min=0, row_index=ri)
                if flag == za_meas_flag and len(raw) > 0:
                    za_spectra.append(raw)
            except Exception:
                pass

        if not za_spectra:
            QMessageBox.information(self, "Not Found", "No ZA-flagged scans found in the current file list.")
            return

        # Trim to common length and average
        min_len = min(len(s) for s in za_spectra)
        i0_avg = np.mean([s[:min_len] for s in za_spectra], axis=0)
        self.i0_data = i0_avg
        self.lbl_i0_path.setText(f"Auto ({len(za_spectra)} ZA scans averaged)")
        self.lbl_i0_path.setStyleSheet("color: blue; font-weight: bold;")
        self.status.setText(f"Auto I0: averaged {len(za_spectra)} ZA scans.")
        self.update_diagnostic_plot()
        self._refresh_setup_status()

    def update_leff(self):
        """Recalculates and displays L_eff = d / (1 - R_mean) whenever R or d changes."""
        if not hasattr(self, 'r_data') or self.r_data is None:
            self.lbl_leff.setText("L_eff: — (load R-curve first)")
            return
        d = self.spin_d_len.value()
        r_mean = np.mean(self.r_data)
        r_min  = np.min(self.r_data)
        r_max  = np.max(self.r_data)
        leff_mean = d / (1.0 - r_mean)
        leff_min  = d / (1.0 - r_max)   # higher R → longer path
        leff_max  = d / (1.0 - r_min)
        self.lbl_leff.setText(
            f"L_eff ≈ {leff_mean:,.0f} cm  "
            f"(range {leff_min:,.0f} – {leff_max:,.0f} cm,  R̄ = {r_mean:.6f})"
        )

    def browse_r_file(self):
        """Browse and set the Reflectivity (R-Curve) file."""
        filepath, _ = QFileDialog.getOpenFileName(self, "Select R-Curve File", self._dlg_dir('rcurve'), "Data Files (*.dat *.txt *.csv)")
        self._dlg_dir('rcurve', filepath)
        if filepath:
            self.lbl_r_path.setText(os.path.basename(filepath))
            self.lbl_r_path.setStyleSheet("color: blue; font-weight: bold;")
            
            # 🌟 Load R data and plot
            try:
                # Load logic for a standard R-Curve file (2-column data)
                df = pd.read_csv(filepath, sep=None, engine='python', header=None, comment='#')
                # Assumes column 1 is wavelength/pixel, column 2 is R value
                r_y = pd.to_numeric(df.iloc[:, -1], errors='coerce').dropna().values
                self.r_data = r_y
                self.update_diagnostic_plot()
                self.update_leff()
            except Exception as e:
                print(f"Error loading R file: {e}")
                QMessageBox.warning(self, "Load Error", "Failed to parse Reflectivity (R) file.")
            self._refresh_setup_status()

    def show_table_context_menu(self, pos):
        """Shows context menu on the measurement table."""
        row = self.table.rowAt(pos)
        if row < 0:
            return
            
        menu = QMenu()
        action_i0 = menu.addAction("Set as I0 (Zero-Air)")
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        
        if action == action_i0:
            self.set_i0_from_table(row)

    def set_i0_from_table(self, row):
        """Extracts the filepath from the table row and sets it as I0."""
        fname = self.table.item(row, 0).text()
        entry = self._entry_from_display_name(fname)
        filepath = self._entry_filepath(entry) if entry else None

        if filepath:
            self.set_i0_path(filepath)
            self.main_tabs.setCurrentWidget(self._tab_pages.get(self.setup_tab, self.setup_tab))   # switch to Setup tab
            
    def set_i0_path(self, filepath):
        """Updates the I0 state, loads data, and updates UI."""
        self.lbl_i0_path.setText(os.path.basename(filepath))
        self.lbl_i0_path.setStyleSheet("color: blue; font-weight: bold;")
        self.status.setText(f"I0 set to: {os.path.basename(filepath)}")
        
        # 🌟 Load I0 data and plot
        try:
            # Load I0 file using the same method as the engine (most stable)
            _, intensity_raw = DataIO.load_measurement(filepath, pixel_min=0)
            self.i0_data = intensity_raw
            self.update_diagnostic_plot()
        except Exception as e:
            print(f"Error loading I0 file: {e}")
            QMessageBox.warning(self, "Load Error", "Failed to read I0 measurement file.")
        self._refresh_setup_status()

    def update_diagnostic_plot(self):
        """Draws I0 and R on the diagnostic viewer."""
        self.p1.clear()
        self.p2.clear()
        
        # Apply wavelength (nm) axis if loaded, otherwise use pixel axis
        x_axis = None
        if hasattr(self, 'wavelengths') and self.wavelengths is not None:
            x_axis = np.array(self.wavelengths).flatten()
            self.plot_diagnostic.setLabel('bottom', 'Wavelength (nm)')
        else:
            self.plot_diagnostic.setLabel('bottom', 'Pixel Index')
            
        # 1. Draw I0 as a black line (Left Y-axis)
        if hasattr(self, 'i0_data') and self.i0_data is not None:
            x = x_axis if (x_axis is not None and len(x_axis) == len(self.i0_data)) else np.arange(len(self.i0_data))
            self.p1.plot(x, self.i0_data, pen=pg.mkPen('k', width=1.5), name="I0 (Zero-Air)")
            
        # 2. Draw R as a blue dashed line (Right Y-axis)
        if hasattr(self, 'r_data') and self.r_data is not None:
            x = x_axis if (x_axis is not None and len(x_axis) == len(self.r_data)) else np.arange(len(self.r_data))
            
            curve_r = pg.PlotCurveItem(x, self.r_data, pen=pg.mkPen('b', width=2, style=Qt.PenStyle.DashLine))
            self.p2.addItem(curve_r)

            # Zoom in around the actual R values so ±0.01% changes are visible
            r_arr    = np.asarray(self.r_data, dtype=float)
            r_finite = r_arr[np.isfinite(r_arr)]
            if len(r_finite) > 0:
                r_mean = float(np.mean(r_finite))
                r_std  = float(np.std(r_finite))
                margin = max(r_std * 5.0, 5e-4)   # ≥ ±0.05 % window
                self.p2.setYRange(
                    max(0.0,    r_mean - margin),
                    min(1.0001, r_mean + margin),
                    padding=0,
                )
            else:
                self.p2.autoRange()


    def _on_r_curve_update(self, wave_nm, r_curve):
        """Called by worker whenever a new R-curve is derived from ZA/He pair."""
        self.r_data = np.array(r_curve)
        self._r_auto_derived = True   # mark: this R came from a run, not a manual load
        if wave_nm is not None and len(wave_nm) == len(r_curve):
            self.wavelengths = np.array(wave_nm)
        self.update_diagnostic_plot()
        self.update_leff()
        self._refresh_setup_status()

