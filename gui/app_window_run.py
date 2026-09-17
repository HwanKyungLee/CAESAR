"""gui/app_window_run.py
CAESARAnalyzer §11 — 분석 실행 / 워커 / autosave / closeEvent (gui/app_window.py에서 분리).

**순수 이동이다.** 메서드 본문은 한 글자도 안 고쳤다 — 호출부가 전부 self.xxx()라
믹스인으로 옮기는 것만으로 동작이 같다. 로직 개선은 다음 PR로.
가드는 tools/test_app_window_smoke.py (표면 골든 + 믹스인 이름 충돌 검사).
"""
import copy
import os
import numpy as np

from PyQt6.QtWidgets import QDialog, QMessageBox, QVBoxLayout
from core import run_meta
from core.__version__ import __version__
from core.data_io import DataIO
from core.paths import (DEFAULT_CAMPAIGN, DEFAULT_OUTPUT_DIR,
                        campaign_dir as _campaign_dir, special_dir as _special_dir)
from .app_window_policy import _channel_worker_gas_policy
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialogButtonBox
from .dlg_dir import dlg_dir
from .worker import AnalysisWorker


class AnalysisRunMixin:
    """§11 — 분석 실행 / 워커 / autosave / closeEvent. CAESARAnalyzer에 믹스인된다."""

    # ══════════════════════════════════════════════════════════════════════
    # §11 분석 실행 / 워커 / autosave / closeEvent
    # ══════════════════════════════════════════════════════════════════════
    def start_analysis(self):
        """
        Validates settings, builds the initial parameter vector p0, and starts
        the AnalysisWorker background thread.

        p0 layout: [shift, squeeze, gas_0, gas_1, …, poly_0, poly_1, …]
          - shift    : initial wavelength offset guess (pixels)
          - squeeze  : initial stretch factor (dimensionless, ~1.0)
          - gas_i    : initial concentration guess for each loaded gas
          - poly_j   : initial polynomial coefficient guesses
        """
        if not self.file_list: 
            return
        if not self.engine.is_engine_ready():
            QMessageBox.warning(self, "Warning", "Please lock references into the Engine first.")
            return
        # L5: Lock 안 된 레퍼런스 변경이 있으면 경고
        if getattr(self, '_refs_dirty', False):
            ret = QMessageBox.question(
                self, "References not locked",
                "References were changed but  Lock was not pressed.\n"
                "The engine will fit with the previously locked set. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return
            
        try:
            pixel_min, pixel_max = int(self.txt_min.text()), int(self.txt_max.text())
        except Exception:
            QMessageBox.warning(self, "Input Error", "Please enter valid integers for Pixel Min/Max.")
            return
        self._analysis_running = True
        
        self.results = []

        # ── 채널 = 좌측 채널 탭. 각 탭이 자기 데이터를 보유(자동분배 안 함) ──
        # 현재 활성 채널 데이터 동기화(로드 후 탭 전환 안 했을 수 있음)
        if self._active_channel in self._channel_configs:
            self._channel_files[self._active_channel] = list(self.file_list)
        active_chs = sorted(c for c, v in self._channel_configs.items() if v is not None) \
                     or [self._active_channel]
        chs_with_data = [c for c in active_chs if self._channel_files.get(c)]
        empty_chs = [c for c in active_chs if not self._channel_files.get(c)]
        if not chs_with_data:
            QMessageBox.warning(self, "No data",
                                "No data in any channel.\nSelect a channel tab and load data.")
            self._analysis_running = False
            return
        if empty_chs:
            self.status.setText(f"Skipped channels with no data: {', '.join('CH'+str(c) for c in empty_chs)}")

        # ── 핏은 알파 입력 전용 (2026-06 워크플로 변경) ──────────────────────
        # 워크플로가 'raw→알파 생성 후 알파 핏'으로 통일됨. raw(Araon mega-matrix/
        # plain) 직접 핏은 거부한다. raw→알파 변환은 Setup의 Alpha Generator 담당.
        # ※ AnalysisWorker.run 의 raw 핏 분기는 당분간 보존(되돌리기 쉽게) — 이 가드만
        #   제거하면 raw 핏이 복원된다. R Trend Monitor·Alpha Generator 등 raw를 쓰는
        #   다른 기능은 별도 경로라 영향 없음.
        _raw_chs = []
        for _c in chs_with_data:
            _f = self._entry_filepath(self._channel_files[_c][0])
            try:
                if not (_f and DataIO._is_alpha_trace_format(_f)):
                    _raw_chs.append(_c)
            except Exception:
                _raw_chs.append(_c)
        if _raw_chs:
            QMessageBox.warning(
                self, "Alpha input required",
                "Fitting now supports alpha (*_alpha_trace.dat) input only.\n"
                f"Channels that look like raw: {', '.join('CH'+str(c) for c in _raw_chs)}\n\n"
                "Generate raw → alpha first with the Alpha Generator in Setup,\n"
                "then load the generated alpha files to fit.")
            self._analysis_running = False
            return

        self._alpha_groups = {c: list(self._channel_files[c]) for c in chs_with_data}
        n_ch = len(chs_with_data)
        self._multi_channel_mode = (n_ch > 1)
        self._workers = []
        self._run_summary = []   # L2: 채널별 설정 요약(RUN 확인 다이얼로그)
        self._workers_done = 0
        self._workers_total = n_ch
        self._next_table_row = 0   # dynamic row counter for multi-channel append
        self._scan_counts = {}     # channel → expanded-scan count (progress denominator)

        # 🌟 UI Table Reset: start empty — rows are added dynamically as scans complete
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(0)

        # Lock in column headers dynamically based on loaded gases
        # Add "Ch" prefix column when multiple channels detected
        if self._multi_channel_mode:
            cols = ["Ch", "File", "Time", "RMS", "Chi2", "SNR", "Status"] + self.engine.gas_list + ["Shift", "Squeeze"]
        else:
            cols = ["File", "Time", "RMS", "Chi2", "SNR", "Status"] + self.engine.gas_list + ["Shift", "Squeeze"]
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self._compact_table_columns(cols)

        # Progress bar: maximum is unknown until the worker expands Araon files.
        # Set to 0 (indeterminate / busy animation) until scan_count_ready fires.
        self.pbar.setMinimum(0)
        self.pbar.setMaximum(0)
        self.pbar.setValue(0)
        
        self.monitor.clear_trend()

        # 농도 시계열 탭: 레퍼런스 가스(채널 union)별 플롯 구성 + 히스토리 초기화
        conc_gases = list(getattr(self.engine, 'gas_list', []) or [])
        for _ch, _cfg in self._channel_configs.items():
            if _cfg:
                for _r in _cfg.get('refs', []):
                    _nm = _r.get('name')
                    if _nm and _nm not in conc_gases:
                        conc_gases.append(_nm)
        if hasattr(self.monitor, 'setup_conc_plots'):
            self.monitor.setup_conc_plots(conc_gases)

        # R-curve from a previous run is in fit-pixel-range length, not full-spectrum
        # length, so the slicing guard below would misfire. Clear it so this run
        # derives R fresh from its own He/ZA scans.
        if getattr(self, '_r_auto_derived', False):
            self.r_data = None
            self._r_auto_derived = False

        # Configure Initial Parameters and Bounds
        num_gases = len(self.engine.gas_list)
        
        start_shift = 0.0  
        step_limit_val = self.spin_step_limit.value()
        
        poly_deg = self.spin_poly_deg.value()
        num_poly_params = poly_deg + 1
        
        # p0 layout: [shift, squeeze, gas_0 ... gas_N, poly_0 ... poly_P]
        # bounds_low / bounds_high define the search box for the optimizer:
        #   - shift is unconstrained globally (rolling window applied inside the worker)
        #   - squeeze is limited to ±5% of 1.0  (physically reasonable range)
        #   - gas concentrations are lower-bounded at 0 (NNLS ensures this anyway)
        p0 = [start_shift, self.calib_squeeze] + [0.1] * num_gases + [0] * num_poly_params
        bounds_low  = [-np.inf, 0.95] + [0.0]    * num_gases + [-np.inf] * num_poly_params
        bounds_high = [ np.inf, 1.05] + [np.inf] * num_gases + [ np.inf] * num_poly_params
        
        interval = self.spin_update.value()
        
        # Fitting mode: Fast (parallel) vs Step (sequential, slow, inspect each fit).
        _disp = self.cb_display_mode.currentText() if hasattr(self, 'cb_display_mode') else "Fast (parallel)"
        _fast_mode = _disp.startswith("Fast")
        if _fast_mode:
            interval = -1     # no live per-scan spectrum overlay; results fill in as chunks arrive
            delay_ms = 0
        else:                 # Step
            # 스캔당 지연 = 사람이 한 핏씩 들여다보는 속도(스핀박스). 0이면 지연 없음.
            # 그래프 폭주 방지는 worker 쪽 20fps emit 상한이 따로 한다.
            delay_ms = self.spin_step_delay.value() if hasattr(self, 'spin_step_delay') else 200
            
        # [ BBCEAS Data Preparation ]
        sliced_i0   = None
        sliced_r    = None
        sliced_dark = None
        cavity_d    = self.spin_d_len.value()

        if hasattr(self, 'i0_data') and self.i0_data is not None:
            if len(self.i0_data) > pixel_max:
                sliced_i0 = self.i0_data[pixel_min:pixel_max]
            else:
                QMessageBox.warning(self, "Warning", "I0 data length is shorter than Fit Max Pixel.")
                return

        if hasattr(self, 'r_data') and self.r_data is not None:
            if len(self.r_data) > pixel_max:
                sliced_r = self.r_data[pixel_min:pixel_max]
            else:
                # Plain 1D files (alpha traces, pre-computed OD) run in linear mode
                # and never use R — silently ignore stale R from a previous BBCEAS run.
                # Only block when the input is a BBCEAS Araon Mega-Matrix file.
                first_is_matrix = (bool(self.file_list) and
                                   DataIO.is_araon_mega_matrix(self.file_list[0]))
                if first_is_matrix:
                    QMessageBox.warning(self, "Warning", "Reflectivity (R) data length mismatch.")
                    return
                # else: sliced_r stays None → fallback handled below

        if hasattr(self, 'dark_data') and self.dark_data is not None:
            if len(self.dark_data) >= pixel_max:
                sliced_dark = self.dark_data[pixel_min:pixel_max]

        sliced_offset = None
        if hasattr(self, 'offset_data') and self.offset_data is not None:
            if len(self.offset_data) >= pixel_max:
                sliced_offset = self.offset_data[pixel_min:pixel_max]
            else:
                QMessageBox.warning(self, "Warning", "Offset data length is shorter than Fit Max Pixel — offset ignored.")

        use_temporal = self.chk_temporal_i0.isChecked()

        # 알파 입력이면 I0/R 경고 자체를 건너뜀 — 알파는 이미 BBCEAS(I0·R) 적용된
        # 산물이라 워커가 I0/R를 쓰지 않는다. (매 RUN마다 Yes 누르던 노이즈 제거)
        _first = self._entry_filepath(self.file_list[0]) if self.file_list else None
        _is_alpha_input = bool(_first) and DataIO._is_alpha_trace_format(_first)

        if (sliced_i0 is None or sliced_r is None) and not _is_alpha_input:
            # Check if the first file is an Araon Mega-Matrix — if so, the worker
            # will auto-derive I0 and R from the He/ZA rows embedded in each file.
            has_embedded_calib = bool(self.file_list) and DataIO.is_araon_mega_matrix(self.file_list[0])
            if has_embedded_calib:
                ans = QMessageBox.question(
                    self, "BBCEAS auto-calibration",
                    "R / I₀ files were not loaded separately.\n\n"
                    "He scans (flag 510~513) and ZA scans (flag 500~503) in the measurement file\n"
                    "are present, so R-curve (flag 510) and I₀ (flag 500) are computed automatically.\n\n"
                    "Start fitting?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if ans == QMessageBox.StandardButton.No:
                    self.b_run.setEnabled(True)
                    return
            else:
                ans = QMessageBox.question(
                    self, "Missing BBCEAS Params",
                    "I0 or R is missing.\nFallback to standard DOAS (Log intensity ratio)?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if ans == QMessageBox.StandardButton.No:
                    self.b_run.setEnabled(True)
                    return

        # Initialize and fire Worker Thread(s) — one per detected channel
        # All channels run in parallel from the same file list
        flag_za  = self._parse_flags(self.txt_flag_za.text())
        flag_he  = self._parse_flags(self.txt_flag_he.text())
        flag_amb = self._parse_flags(self.txt_flag_amb.text())

        # 채널 = 좌측 채널 탭. 각 탭이 자기 데이터로 병렬 피팅(현재 탭 설정 먼저 스냅샷).
        if self._active_channel in self._channel_configs:
            self._channel_configs[self._active_channel] = self._capture_config()
        # .meta.json 용 동결: 핏설정·캘리브는 **이 숫자를 만든 값**이어야 하므로 RUN 시점에
        # 얼려둔다(RUN 뒤 Save 전에 UI를 만져도 meta는 안 흔들린다). QC는 재핏 없는 후처리라
        # 저장 시점 값이 맞아서 여기서 얼리지 않는다 — save()가 그때 읽는다.
        self._run_frozen = {
            "configs": copy.deepcopy(self._channel_configs),
            "calibration": self._calibration_state(),
        }
        ch_list = sorted(self._alpha_groups)        # 데이터 있는 채널만(early 블록에서 구성)
        per_channel = len(ch_list) > 1
        self._workers_total = len(ch_list)
        self._scan_counts = {}

        for ch in ch_list:
            files_for_ch = self._alpha_groups.get(ch) or []
            if not files_for_ch:
                continue   # 데이터 없는 채널 스킵
            # 활성+단일이면 라이브 엔진/설정, 아니면(병렬 or 비활성 채널) 채널 config로 빌드
            use_cfg = per_channel or (ch != self._active_channel)

            # 채널별 설정 vs 공용(라이브)
            if use_cfg:
                cfg = self._channel_configs[ch]
                neg_ch = _channel_worker_gas_policy(True, cfg, self.chk_allow_neg.isChecked())
                eng_ch = self._build_engine_from_config(cfg)
                rp_ch = cfg.get('ref_props', {})
                ng = len(eng_ch.gas_list)
                npoly = int(cfg.get('poly_deg', 3)) + 1
                p0_ch = [0.0, self.calib_squeeze] + [0.1] * ng + [0] * npoly
                lo_ch = [-np.inf, 0.95] + [0.0] * ng + [-np.inf] * npoly
                hi_ch = [np.inf, 1.05] + [np.inf] * ng + [np.inf] * npoly
                funit_ch = cfg.get('fit_unit', 'nm')
                fnm_lo_ch = float(cfg.get('fit_start_nm', 435.0))
                fnm_hi_ch = float(cfg.get('fit_end_nm', 480.0))
                tz_val_ch = cfg.get('time_shift_h', cfg.get('input_tz', 0.0))
                gtemp_ch = float(cfg.get('gas_temp', 0.0) or 0.0)
                wl_ch = cfg.get('wl_path', '')
                lbl_ch = (cfg.get('data_label') or '').strip()
                if funit_ch == 'px':
                    # 박사님 시나리오: 픽셀 인덱스를 그대로 사용(예 Cold 775-1550)
                    try:
                        pmin, pmax = int(cfg.get('f_min', 0)), int(cfg.get('f_max', 2047))
                    except Exception:
                        pmin, pmax = pixel_min, pixel_max
                    if pmin > pmax:
                        pmin, pmax = pmax, pmin
                else:
                    wax = getattr(eng_ch, '_wave_axis', None)
                    if wax is not None:
                        wa = np.asarray(wax, dtype=float).flatten()
                        pmin = int(np.abs(wa - fnm_lo_ch).argmin())
                        pmax = int(np.abs(wa - fnm_hi_ch).argmin())
                        if pmin > pmax:
                            pmin, pmax = pmax, pmin
                    else:
                        pmin, pmax = pixel_min, pixel_max
                cav_ch = cfg.get('cavity_d', cavity_d); rl_ch = cfg.get('rl_factor', 1.0)
                lam_ch = cfg.get('tikhonov_lambda', 0.0); rob_ch = cfg.get('use_robust', False)
                step_ch = cfg.get('step_limit', 0.5)
                kq_ch = cfg.get('kalman_q', self.spin_kalman_q.value())
                kr_ch = cfg.get('kalman_r', self.spin_kalman_r.value())
            else:
                neg_ch = _channel_worker_gas_policy(False, {}, self.chk_allow_neg.isChecked())
                eng_ch = self.engine; rp_ch = getattr(self, 'ref_props', {})
                p0_ch, lo_ch, hi_ch = p0, bounds_low, bounds_high
                funit_ch = self.cb_fit_unit.currentText() if hasattr(self, 'cb_fit_unit') else 'nm'
                fnm_lo_ch = self.spin_fit_start_nm.value(); fnm_hi_ch = self.spin_fit_end_nm.value()
                tz_val_ch = self.spin_time_shift.value() if hasattr(self, 'spin_time_shift') else 0.0
                gtemp_ch = float(self.spin_gas_temp.value()) if hasattr(self, 'spin_gas_temp') else 0.0
                wl_ch = getattr(self, 'loaded_wl_path', '')
                lbl_ch = self._ed_ch_datalabel.text().strip() if hasattr(self, '_ed_ch_datalabel') else ''
                pmin, pmax = pixel_min, pixel_max
                cav_ch = cavity_d; rl_ch = self.spin_rl_factor.value()
                lam_ch = self.spin_lambda.value(); rob_ch = self.chk_robust.isChecked()
                step_ch = step_limit_val
                kq_ch = self.spin_kalman_q.value(); kr_ch = self.spin_kalman_r.value()

            w = AnalysisWorker(
                eng_ch, files_for_ch, pmin, pmax,
                p0_ch, (lo_ch, hi_ch), interval, delay_ms,
                ref_properties=rp_ch,
                i0_array=sliced_i0, r_array=sliced_r, cavity_len=cav_ch,
                dark_array=sliced_dark,
                dark_scale_factor=self.spin_dark_scale.value(),
                offset_array=sliced_offset,
                offset_scale_factor=self.spin_offset_scale.value(),
                stray_light_fraction=self.spin_stray_light.value(),
                use_temporal_i0=use_temporal,
                flag_za=flag_za,
                flag_he=flag_he,
                flag_amb=flag_amb,
                save_alpha=False,   # α 저장은 Alpha Generator 전담
                alpha_save_dir=getattr(self, 'alpha_save_dir', ''),
                rl_factor=rl_ch,
                channel=ch
            )

            w.step_limit = step_ch
            w.tikhonov_lambda = lam_ch
            w.use_robust_fitting = rob_ch
            w.allow_negative_gas = neg_ch
            w.qc_enabled = self.chk_qc.isChecked() if hasattr(self, 'chk_qc') else True
            w.qc_rms_abs = self.spin_qc_rms.value() if hasattr(self, 'spin_qc_rms') else 0.0
            w.qc_snr_min = self.spin_qc_snr.value() if hasattr(self, 'spin_qc_snr') else 0.0
            w.kalman_q = kq_ch
            w.kalman_r = kr_ch
            # 알파 피팅 핏범위(px면 알파를 픽셀구간으로 슬라이스)
            w.fit_unit = funit_ch
            w.fit_lo_nm = fnm_lo_ch
            w.fit_hi_nm = fnm_hi_ch
            # 채널 시각에 그대로 더할 시프트(시간→초). 순수 시간이동, TZ 라벨 없음.
            w.tz_offset_sec = int(round(self._time_shift_hours(tz_val_ch) * 3600))
            # 가스온도 오버라이드(>0이면 ppb 밀도보정에 그 온도 사용; 0=자동 HK)
            w.gas_temp_override = gtemp_ch if gtemp_ch > 0 else None
            w.temperature = self.spin_temp.value()
            w.pressure = self.spin_pres.value()
            w.ok_rms_threshold = self.spin_rms_thresh.value() / 100.0
            # Fast mode → parallel chunked fitting (AnalysisWorker._run_parallel).
            # Step mode → existing sequential loop (with delay for live inspection).
            w.parallel = _fast_mode
            # Channels run as concurrent workers, each with its OWN process pool.
            # Total process budget = ~half the machine's logical cores (adapts per PC,
            # leaving the other half for the GUI/OS). That budget is split across the
            # active channels so adding channels never multiplies the load
            # (e.g. without this, 3ch × 6 = 18 procs on 12 cores → ~100% + lag).
            import os as _os
            _budget = max(2, (_os.cpu_count() or 4) // 2)
            w.fit_nproc = max(1, _budget // max(1, len(self._alpha_groups)))

            # Connect signals
            #   Progress is driven by completed-result count vs total scans across
            #   ALL channels (see update_table / _on_scan_count_ready), NOT by each
            #   worker's local file counter — otherwise parallel workers race and the
            #   bar caps at 100/N % (the "2채널이면 50%에서 멈춤" bug).
            w.result_ready.connect(self.update_table)
            w.plot_update.connect(self.monitor.update_spectrum)
            w.trend_update.connect(self.monitor.update_trend)
            # 실패를 상태바에 — AlphaExportWorker와 같은 규약(app_window_inputs 참고).
            w.status_msg.connect(
                lambda m, _ch=ch: (print(f"[Analysis CH{_ch}] {m}"),
                                   self.status.setText(f"[CH{_ch}] {m}")))
            w.finished.connect(self.analysis_finished)
            w.r_curve_update.connect(self._on_r_curve_update)
            w.scan_count_ready.connect(lambda n, ch=ch: self._on_scan_count_ready(n, ch))

            # L2: RUN 확인 다이얼로그용 채널별 설정 요약
            _wlname = os.path.basename(wl_ch) if wl_ch else 'none'
            _gt = f"{gtemp_ch:.0f}°C" if gtemp_ch > 0 else "auto"
            _gases = list(eng_ch.gas_list)
            self._run_summary.append(
                f"CH{ch} {lbl_ch or ''}\n"
                f"{_wlname}\n"
                f"   range px {pmin}-{pmax} ({funit_ch}) · Poly{cfg.get('poly_deg', self.spin_poly_deg.value()) if ch != self._active_channel and self._channel_configs.get(ch) else self.spin_poly_deg.value()}\n"
                f"   refs {len(_gases)}: {', '.join(_gases)}\n"
                f"   {self._shsq_text(_gases, rp_ch)}\n"
                f"   Shift {self._time_shift_hours(tz_val_ch):+g}h · GasT {_gt}")
            self._workers.append(w)

        if not self._workers:
            QMessageBox.warning(self, "Channel/data mismatch",
                                "No data matches the channel tabs.\n"
                                "(check the _PNs_/_ANs_ channel in the alpha filename and the number of tabs)")
            self.b_run.setEnabled(True)
            return

        # Keep self.worker pointing to CH1 worker for legacy stop/wait references
        self.worker = self._workers[0]

        # ── L2: RUN 직전 설정 확인 — TZ 혼합·구버전 wavecal·온도 실수 등 예방 ──
        if not getattr(self, '_skip_run_confirm', False) and self._run_summary:
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit, \
                QDialogButtonBox, QCheckBox as _QCB
            _qcK = self.spin_qc_k.value() if hasattr(self, 'spin_qc_k') else 0
            _qc = (f"K={_qcK:g}" if (hasattr(self, 'chk_qc') and self.chk_qc.isChecked()
                                     and _qcK > 0) else "off")
            _asave = "on" if (hasattr(self, 'chk_auto_save')
                              and self.chk_auto_save.isChecked()) else "off"
            txt = ("\n\n".join(self._run_summary)
                   + f"\n\nCommon: AutoQC {_qc} · auto-save {_asave}"
                   + f" · files {sum(len(v) for v in self._alpha_groups.values())}")
            dlg = QDialog(self)
            dlg.setWindowTitle("Start with these settings?")
            dlg.resize(int(560 * self._s), int(380 * self._s))
            lay = QVBoxLayout(dlg)
            ed = QPlainTextEdit(txt)
            ed.setReadOnly(True)
            ed.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
            lay.addWidget(ed)
            _cb = _QCB("Don't ask again this session")
            lay.addWidget(_cb)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                  | QDialogButtonBox.StandardButton.Cancel)
            bb.button(QDialogButtonBox.StandardButton.Ok).setText("▶ Start")
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            lay.addWidget(bb)
            ok = dlg.exec()
            if _cb.isChecked():
                self._skip_run_confirm = True
            if not ok:
                self._analysis_running = False
                self.status.setText("RUN cancelled (settings review)")
                return

        # Lock UI controls to prevent interference
        self.b_run.setEnabled(False)
        self.b_stop.setEnabled(True)
        self.status.setText("Analysis in progress...")

        # Switch to the Analysis Monitor automatically
        self.main_tabs.setCurrentWidget(self._tab_pages.get(self.monitor, self.monitor))

        # 크래시 대비 실시간 자동저장 시작 (결과 도착마다 TSV append)
        self._autosave_start()

        # Fast mode: buffer incoming results and flush the table in batches on a timer
        # (see update_table / _flush_fast) so large parallel runs don't freeze the GUI.
        self._fast_mode_active = bool(_fast_mode)
        if self._fast_mode_active:
            self._fast_pending = []
            self._fast_rows_shown = 0
            self._fast_cap_noted = False
            self._fast_table_cap = 5000   # live-table preview cap (full data in plots+autosave)
            if not hasattr(self, '_fast_timer'):
                from PyQt6.QtCore import QTimer
                self._fast_timer = QTimer(self)
                self._fast_timer.setInterval(250)
                self._fast_timer.timeout.connect(self._flush_fast)
            self._fast_timer.start()

        for w in self._workers:
            w.start()
        
    def _on_scan_count_ready(self, total_scans, ch=1):
        """Called once a worker has finished expanding all files into individual scans.

        Progress denominator = SUM of expanded-scan counts across every channel
        worker (each worker reports its own count for its channel). The bar value
        is the number of completed results (see update_table), so it reaches 100%
        only when every channel's every scan is done.
        """
        self._scan_counts[ch] = total_scans
        total_all = max(1, sum(self._scan_counts.values()))
        self.pbar.setMaximum(total_all)
        if self._multi_channel_mode:
            # Multi-channel: rows arrive interleaved from parallel workers — grow dynamically
            n_ch = self._workers_total
            self.status.setText(
                f"{total_all:,} scans ({n_ch} CH) / {len(self.file_list)} file(s) — processing..."
            )
        elif getattr(self, '_fast_mode_active', False):
            # Fast mode renders the table once at the end (capped) — don't pre-allocate
            # tens of thousands of empty rows here (memory + slow).
            self.status.setText(f"Fast: {total_scans:,} scans / {len(self.file_list)} file(s) — fitting...")
        else:
            # Single-channel Step: pre-allocate rows for O(1) update_table writes
            self.table.setRowCount(total_scans)
            self.status.setText(f"{total_scans:,} scans / {len(self.file_list)} file(s) — processing...")

    def stop_analysis(self):
        """Safely stops all worker threads and re-enables UI controls."""
        workers = getattr(self, '_workers', [])
        if not workers and hasattr(self, 'worker'):
            workers = [self.worker]   # legacy fallback

        running = [w for w in workers if w.isRunning()]
        if running:
            # 논블로킹 정지: w.wait()로 UI 스레드를 막으면 '응답없음'이 뜬다.
            # stop()이 is_running=False로 만들면 워커는 현재 스캔만 끝내고 루프를
            # 빠져나와 finished를 emit → analysis_finished()가 정상 흐름으로 호출되어
            # UI 복구 + 자동 QC(부분 결과 대상)를 수행한다.
            self._stop_requested = True
            for w in running:
                w.stop()
            self.status.setText("Stopping… (finishing current scan)")
            self.status.setStyleSheet("color: red; font-weight: bold;")
            self.b_stop.setEnabled(False)

    def _active_workers(self):
        """모든 백그라운드 워커(분석 핏 + 알파 생성)를 한 곳에서 모은다.
        Fast 핏·알파 생성은 ProcessPoolExecutor 자식을 띄우므로, 창을 그냥 닫으면
        QThread가 중간에 죽으며 자식 프로세스가 고아(orphan)로 남아 CPU를 계속 먹는다."""
        ws = list(getattr(self, '_workers', []) or [])
        w0 = getattr(self, 'worker', None)
        if w0 is not None and w0 not in ws:
            ws.append(w0)
        ax = getattr(self, '_alpha_export_worker', None)
        if ax is not None:
            ws.append(ax)
        return [w for w in ws if w is not None and w.isRunning()]

    def closeEvent(self, event):
        """창을 닫을 때 실행 중인 워커를 깨끗이 정지시켜 고아 프로세스를 막는다.
        stop()이 is_running=False로 만들면 워커는 현재 청크를 마치고 루프를 빠져나오며
        ProcessPoolExecutor의 with 블록이 풀을 정리한다. wait()로 정리를 기다리되,
        제한시간을 넘기면 terminate()로 강제 종료한다(좀비 방지)."""
        running = self._active_workers()
        if running:
            reply = QMessageBox.question(
                self, "Confirm exit",
                f"{len(running)} background task(s) are running.\n"
                "Stop and exit? (running fits/alpha generation will be aborted)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for w in running:
                try:
                    w.stop()
                except Exception:
                    pass
            for w in running:
                try:
                    if not w.wait(8000):       # 정상 정리 대기(최대 8초)
                        w.terminate()          # 안 멈추면 강제 종료 → 자식 정리
                        w.wait(2000)
                except Exception:
                    pass
        event.accept()

    def _campaign(self):
        """산출물 최상위 스코프. 비면 'default' — save()·autosave가 같은 값을 써야 한다."""
        w = getattr(self, '_ed_campaign', None)
        return (w.text().strip() if w is not None else "") or DEFAULT_CAMPAIGN

    def _input_layout(self, ch):
        """이 채널의 **첫 입력 파일**이 어떤 raw 구성에서 나왔는지. 모르면 None.

        알파 입력이면 그 헤더의 `# raw_layout:` 줄(알파 생성 때 기록됨)을 읽고, raw 입력이면
        열 수로 레지스트리를 본다 — 판단은 `core.run_meta.layout_from_input`이 한다.
        """
        try:
            files = (self._channel_files.get(int(ch)) or self.file_list or [])
            if not files:
                return None
            return run_meta.layout_from_input(self._entry_filepath(files[0]))
        except Exception:                       # noqa: BLE001 — provenance가 저장을 막지 않는다
            return None

    def _build_run_meta(self, ch, *, campaign=None, data_days=(), rows=None):
        """채널 하나의 `.meta.json`. 실패하면 None(저장 자체는 살린다).

        save()와 autosave가 **같은 runid**를 쓰도록 한 곳에 둔다 — autosave 파일명이
        `{runid}.tsv`인데 나중에 저장되는 결과의 runid와 다르면 그 이름이 거짓말이 된다.
        `data_days`·`rows`는 runid 해시에 안 들어가므로 autosave가 비워 불러도
        같은 값이 나온다.
        """
        try:
            ch = int(ch) if ch is not None else int(self._active_channel)
            frozen = getattr(self, '_run_frozen', None) or {}
            cfg = ((frozen.get('configs') or self._channel_configs).get(ch)
                   or self._channel_configs.get(ch) or {})
            from core.provenance import code_version as _cv
            meta = run_meta.build_meta(
                cfg, channel=ch,
                qc=self._qc_state(),
                calibration=frozen.get('calibration') or self._calibration_state(),
                data_days=data_days, rows=rows,
                campaign=campaign if campaign is not None else self._campaign(),
                scenario=getattr(self, '_scenario_name', None),
                code_version=_cv(), app_version=__version__,
                # 이 결과가 어떤 raw 구성에서 나왔나(B안). 선택은 데이터(열 수)가 하고
                # 여기선 기록만 한다 — 사람이 친 campaign 라벨과 달라도 그건 정보다.
                layout=self._input_layout(ch),
            )
            # 측정일 감사(D1) 결과를 결과 파일에 붙인다 — "이 농도가 R(t) 외삽 구간
            # 위에서 나왔나"를 나중에 물을 수 있어야 한다. runid 해시엔 안 들어간다
            # (설정이 아니라 그날 데이터의 성질).
            audit = getattr(self, '_day_audit', None) or {}
            hit = {d: audit[d].to_meta() for d in data_days if d in audit}
            if hit:
                meta['day_audit'] = hit
            return meta
        except Exception as e:                  # noqa: BLE001 — meta가 저장을 막지 않는다
            print(f"[run_meta] no sidecar: {e}")
            return None

    def _run_runids(self):
        """이번 런에 걸린 채널들의 runid(정렬·중복제거). autosave 파일명용."""
        chans = sorted((getattr(self, '_run_frozen', None) or {}).get('configs')
                       or self._channel_configs or {self._active_channel: None})
        out = []
        for ch in chans:
            m = self._build_run_meta(ch)
            if m and m.get('runid') not in out:
                out.append(m['runid'])
        return out

    def _autosave_retire(self):
        """정식 저장이 성공했으면 그 런의 autosave를 치운다 (E3).

        autosave의 존재 이유는 "이 런은 아직 정식 저장이 없다"이므로, 저장이 끝나면
        남아 있을 이유가 없다 — 남겨두면 `_autosave/`가 어느 게 미완인지 알 수 없는
        더미가 된다. **지우지 않고** `_archive/`로 옮긴다(헌장 ①).
        """
        p = getattr(self, '_autosave_path', None)
        if not p or not os.path.exists(p):
            return
        try:
            self._autosave_close()
            from core.result_io import archive_existing
            from gui.dlg_dir import dlg_dir
            base = dlg_dir('save_results') or os.path.join(DEFAULT_OUTPUT_DIR, 'fitting')
            archive_existing(p, _campaign_dir(base, self._campaign()))
            self._autosave_path = None
        except Exception as e:                  # noqa: BLE001 — 정리 실패가 저장을 무르지 않는다
            print(f"[autosave] retire skipped: {e}")

    # ── 실시간 자동저장(autosave) ─────────────────────────────────────────
    # 밤샘 런이 크래시로 죽어도 그 시점까지의 결과가 디스크에 남도록, 결과가
    # 도착할 때마다 TSV에 append한다(50행마다 flush). 완료 시 정식 Save와 별개로
    # _autosave/ 폴더에 전체 기록이 남는다(QC 적용 전 원본값 기준).
    def _autosave_start(self):
        try:
            import time as _t
            try:
                from gui.dlg_dir import dlg_dir
                base = dlg_dir('save_results') or os.path.join(DEFAULT_OUTPUT_DIR, 'fitting')
            except Exception:
                base = os.getcwd()
            # E3: 캠페인 안으로 + 이름을 runid로. 예전 `autosave_20260908_143207.tsv`는
            # 실행 시각뿐이라 여러 런 뒤 _autosave/를 열면 어느 설정이었는지 열어봐야 알았다.
            folder = _special_dir(base, self._campaign(), '_autosave')
            os.makedirs(folder, exist_ok=True)
            rids = self._run_runids()
            stem = "_".join(rids) if rids else f'autosave_{_t.strftime("%Y%m%d_%H%M%S")}'
            self._autosave_path = os.path.join(folder, f'{stem}.tsv')
            # 같은 설정으로 다시 돌리면 이름이 겹친다 — 남아 있는 건 **정식 저장이 안 된
            # 런**(크래시 등)이므로 덮지 않고 _archive로 밀어둔다(헌장 ①: 지우지 말 것).
            if os.path.exists(self._autosave_path):
                from core.result_io import archive_existing
                archive_existing(self._autosave_path, _campaign_dir(base, self._campaign()))
            cols = ['File', 'Channel', 'Time', 'RMS', 'Chi2', 'SNR', 'Status',
                    'Shift', 'Squeeze', 'T_used_C', 'P_used_mbar']
            for g in self.engine.gas_list:
                cols += [g, f'{g}_RealConc', f'{g}_Error', f'{g}_Smooth']
            self._autosave_cols = cols
            self._autosave_fh = open(self._autosave_path, 'w', encoding='utf-8')
            self._autosave_fh.write('\t'.join(cols) + '\n')
            self._autosave_fh.flush()
            self._autosave_n = 0
        except Exception:
            self._autosave_fh = None

    def _autosave_row(self, result_dict):
        fh = getattr(self, '_autosave_fh', None)
        if fh is None:
            return
        try:
            vals = []
            for c in self._autosave_cols:
                v = result_dict.get(c, '')
                if isinstance(v, float):
                    vals.append(f'{v:.6g}')
                else:
                    vals.append(str(v))
            fh.write('\t'.join(vals) + '\n')
            self._autosave_n += 1
            if self._autosave_n % 50 == 0:
                fh.flush()
        except Exception:
            pass

    def _autosave_close(self):
        fh = getattr(self, '_autosave_fh', None)
        if fh is not None:
            try:
                fh.flush()
                fh.close()
            except Exception:
                pass
            self._autosave_fh = None

