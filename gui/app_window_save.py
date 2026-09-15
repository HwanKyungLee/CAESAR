"""gui/app_window_save.py
CAESARAnalyzer §13 — 결과 저장 + 결과뷰어 연동 (gui/app_window.py에서 분리).

**순수 이동이다.** 메서드 본문은 한 글자도 안 고쳤다 — 호출부가 전부 self.xxx()라
믹스인으로 옮기는 것만으로 동작이 같다. 로직 개선은 다음 PR로.
가드는 tools/test_app_window_smoke.py (표면 골든 + 믹스인 이름 충돌 검사).
"""
import datetime
import os
import numpy as np
import pandas as pd

from PyQt6.QtWidgets import QFileDialog, QMessageBox
from core import run_meta
from core.data_io import DataIO
from core.engine import UniversalEngine
from core.paths import (DEFAULT_CAMPAIGN, DEFAULT_OUTPUT_DIR, campaign_dir as _campaign_dir, out_path as _out_path,
                        resolve_ref_path)


class SaveExportMixin:
    """§13 — 결과 저장 + 결과뷰어 연동. CAESARAnalyzer에 믹스인된다."""

    # ══════════════════════════════════════════════════════════════════════
    # §13 저장 + 결과뷰어 연동
    # ══════════════════════════════════════════════════════════════════════
    def save(self, auto=False):
        """
        Exports all analysis results to a tab-separated .dat or .csv file.

        The auto-generated filename encodes the key fit settings so you can
        identify the run later without opening the file:
          e.g.  240420_1523_Result_NO2_H2O_445.0-465.0nm_Poly3_L0.0001_Robust_Step[0.5]_...dat

        A metadata header block is prepended with the exact fit parameters,
        followed by the data table (one row per measurement file).
        """
        if not hasattr(self, 'results') or not self.results:
            QMessageBox.warning(self, "Warning", "No analysis results to save. Please RUN the analysis first.")
            return
            
        now_str = datetime.datetime.now().strftime("%y%m%d_%H%M") 
        
        gas_list_str = "_".join(self.engine.gas_list) if hasattr(self, 'engine') and self.engine.gas_list else "NoRefs"
        poly_deg = self.spin_poly_deg.value()
        step_val = self.spin_step_limit.value() if hasattr(self, 'spin_step_limit') else 0.5
        
        # 1. Read pixel indices from UI text boxes
        try:
            f_min_px = int(self.txt_min.text())
            f_max_px = int(self.txt_max.text())
            _range_ok = True
        except Exception:
            # 0,0은 **실제 값이 아니다**. 결과 헤더의 "Fit Range"는 이 파일을
            # 재현하는 기록이라(원칙 4), 못 읽은 걸 구체적 숫자로 적으면 안 된다.
            # 계산용으로만 0,0을 쓰고 기록에는 읽지 못했다고 남긴다.
            f_min_px, f_max_px = 0, 0
            _range_ok = False
            
        wl_str = f"{f_min_px}-{f_max_px}px" # Default fallback
        
        # 🌟 2. Convert Pixel to Wavelength (nm) for filename clarity!
        wl_array = None
        if hasattr(self, 'monitor') and getattr(self.monitor, 'wavelengths', None) is not None:
            wl_array = self.monitor.wavelengths
            
        if wl_array is not None and len(wl_array) > max(f_min_px, f_max_px):
            try:
                wl_min = wl_array[f_min_px]
                wl_max = wl_array[f_max_px]
                wl_str = f"{wl_min:.1f}-{wl_max:.1f}nm" # e.g., 445.0-465.0nm
            except Exception as e:
                print(f"Filename wavelength conversion error: {e}")

        # =========================================================
        # 3. Trace linked Shift/Squeeze properties for filename
        # =========================================================
        sh_str, sq_str = "Sh[None]", "Sq[None]"
        if hasattr(self, 'engine') and self.engine.gas_list and hasattr(self, 'ref_props'):
            first_gas = self.engine.gas_list[0]
            
            def get_real_value(gas, prop_prefix):
                curr_gas = gas
                visited = set() 
                
                while curr_gas and curr_gas not in visited:
                    visited.add(curr_gas)
                    props = self.ref_props.get(curr_gas, {})
                    mode = props.get(f"{prop_prefix}_mode", "Limit")
                    val = str(props.get(f"{prop_prefix}_val", "")).strip()
                    
                    if mode == "Free":
                        return "Free"
                    elif mode == "Link":
                        curr_gas = val 
                    else:
                        return val.replace(" ", "") 
                return "Unknown"

            real_sh = get_real_value(first_gas, "sh")
            real_sq = get_real_value(first_gas, "sq")
            
            sh_str = f"Sh[{real_sh}]"
            sq_str = f"Sq[{real_sq}]"

        lam_val = self.spin_lambda.value() if hasattr(self, 'spin_lambda') else 0.0
        robust_str = "Robust" if hasattr(self, 'chk_robust') and self.chk_robust.isChecked() else "Std"

        # 파일명: 데이터(raw) 날짜범위 + 채널라벨 + 핵심세팅 (실행날짜 X)
        _drange = self._results_date_range() or now_str
        _albl, _atag = self._channel_settings_tag(self._active_channel)
        default_fname = f"{_drange}_{_albl}_{_atag}.dat"

        if auto:
            # L3: 완료 시 자동 저장 — 다이얼로그 없이 기존 파일명 규칙으로
            _base = self._dlg_dir('save') or os.path.join(DEFAULT_OUTPUT_DIR, 'fitting')
            os.makedirs(_base, exist_ok=True)
            path = os.path.join(_base, default_fname)
        else:
            _start = os.path.join(self._dlg_dir('save'), default_fname) if self._dlg_dir('save') else default_fname
            path, _ = QFileDialog.getSaveFileName(self, "Save Data (auto per-channel name if multi-channel)", _start, "Data Files (*.dat);;CSV Files (*.csv)")
            self._dlg_dir('save', path)

        if path:
            try:
                df = pd.DataFrame(self.results)
                
                if 'Params' in df.columns:
                    df = df.drop(columns=['Params'])
                    
                current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                robust_on = hasattr(self, 'chk_robust') and self.chk_robust.isChecked()
                robust_status = "ON" if robust_on else "OFF"

                kalman_q = self.spin_kalman_q.value()
                kalman_r = self.spin_kalman_r.value()
                rms_thresh_pct = self.spin_rms_thresh.value()
                temporal_i0 = "ON" if self.chk_temporal_i0.isChecked() else "OFF"
                dark_loaded = "YES" if (hasattr(self, 'dark_data') and self.dark_data is not None) else "NO"
                dark_scale_val = self.spin_dark_scale.value()
                offset_loaded = "YES" if (hasattr(self, 'offset_data') and self.offset_data is not None) else "NO"
                offset_scale_val = self.spin_offset_scale.value()
                stray_light_val = self.spin_stray_light.value()

                from core.provenance import code_version as _codever

                # ── QC / ±Neg / 데이터기간: 폴더명·_SETTINGS.txt·인라인헤더 공용으로 먼저 계산 ──
                # (인라인 헤더에 넣어야 머지/슬라이스 후에도 .dat 자체에 세팅이 남는다.)
                allow_neg_on = hasattr(self, 'chk_allow_neg') and self.chk_allow_neg.isChecked()
                allow_neg = "ON" if allow_neg_on else "OFF"
                qc_on = hasattr(self, 'chk_qc') and self.chk_qc.isChecked()
                qc_k = self.spin_qc_k.value() if hasattr(self, 'spin_qc_k') else 0.0
                if qc_on and qc_k > 0:
                    qc_str = f"ON  (auto threshold K={qc_k:g}·MAD)"
                elif qc_on:
                    qc_str = "ON  (auto off — manual RMS max only)"
                else:
                    qc_str = "OFF"
                try:
                    _tt = pd.to_datetime(df['Time'], errors='coerce').dropna()
                    span_str = (f"{_tt.min():%Y-%m-%d %H:%M} ~ {_tt.max():%Y-%m-%d %H:%M}"
                                if len(_tt) else (_drange or "(unknown)"))
                except Exception:
                    span_str = _drange or "(unknown)"

                # ── etalon–기체 공선성 진단(보고 전용, 핏 불변) ──
                # 이번 런이 실제 쓴 etalon 주파수(Params.etalon_freq)에서, 현재
                # 핏창·poly·레퍼런스로 differential 공간 r·VIF를 계산해 헤더에 기록.
                # (shift/squeeze는 0/1 — 서브픽셀 이동은 r에 영향 미미)
                collin_line = "n/a (engine not ready or no etalon freq)"
                try:
                    _ef = next((float(r.get('Params', {}).get('etalon_freq', 0.0))
                                for r in self.results
                                if r.get('Params', {}).get('etalon_freq')), 0.0)
                    if _ef > 0 and self.engine.is_engine_ready():
                        from core.doas_fit import DoasFitter as _DF
                        _pi = np.arange(f_min_px, f_max_px + 1, dtype=float)
                        _diag = _DF(self.engine).etalon_collinearity(
                            _pi, _ef, poly_deg, getattr(self, 'ref_props', {}))
                        collin_line = _DF.format_etalon_collinearity(_diag)
                except Exception as _ce:
                    collin_line = f"n/a ({_ce})"

                header_lines = [
                    "# ==========================================================",
                    "# Augur Analysis Report",
                    f"# Generated: {current_time}",
                    f"# Code Version: {_codever()}",
                    f"# Data Period: {span_str}",
                    (f"# Fit Range: Pixel {f_min_px}-{f_max_px} ({wl_str})"
                     if _range_ok else
                     "# Fit Range: UNREADABLE — UI 핏범위 입력을 읽지 못했다 (0-0은 실제 값이 아님)"),
                    f"# Polynomial Degree: {poly_deg}",
                    f"# Tikhonov Lambda: {lam_val:g}",
                    f"# Robust Fitting (IRLS): {robust_status}",
                    f"# Allow Negative Gas (±Neg): {allow_neg}",
                    f"# Auto QC: {qc_str}",
                    f"# Step Limit: {step_val} px",
                    f"# OK RMS Threshold: {rms_thresh_pct:.1f}%  (fit accepted when RMS/signal < threshold)",
                    f"# Kalman Filter: Q={kalman_q:.4f}, R={kalman_r:.3f}  (concentration columns = raw fit; _Smooth = Kalman-filtered)",
                    f"# Dark Current Subtraction: {dark_loaded}  (scale={dark_scale_val:.4f})",
                    f"# Detector Offset Subtraction: {offset_loaded}  (scale={offset_scale_val:.4f})",
                    f"# Stray Light Correction: {'ON' if stray_light_val > 0 else 'OFF'}  (epsilon={stray_light_val:.4f})",
                    f"# Temporal I0 Interpolation: {temporal_i0}",
                    f"# Purge Gas RL Factor: {self.spin_rl_factor.value():.4f}  (1.0 = no correction; CAESAR CH1=0.9330 CH2=0.9950 CH3=0.9968)",
                    f"# Measurement Flags: Ambient={self.txt_flag_amb.text().strip()}, ZA={self.txt_flag_za.text().strip()}, He={self.txt_flag_he.text().strip()}",
                    f"# Reference Constraints: {sh_str}, {sq_str}",
                    f"# Etalon-Gas Collinearity (diagnostic only, fit unchanged): {collin_line}",
                    "# ==========================================================\n"
                ]

                header_txt = "\n".join(header_lines)
                is_csv = path.endswith('.csv')
                ext = '.csv' if is_csv else '.dat'

                def _write_df(_df, _path, _ch_hdr=""):
                    with open(_path, 'w', encoding='utf-8') as f:
                        if _ch_hdr:
                            f.write(_ch_hdr + "\n")
                        f.write(header_txt)
                        if is_csv:
                            _df.to_csv(f, index=False, lineterminator='\n')
                        else:
                            _df.to_csv(f, sep='\t', index=False, lineterminator='\n')

                def _build_meta(_df, _ch, campaign):
                    """이 파일 몫의 meta. **파일명보다 먼저** 필요하다 — runid가 이름이 된다.

                    실제 조립은 `_build_run_meta`(메서드)가 한다 — autosave 파일명도 같은
                    runid를 써야 하므로 클로저에 가둬둘 수 없다."""
                    try:
                        _t = pd.to_datetime(_df['Time'], errors='coerce').dropna()
                        days = sorted({d.strftime('%Y-%m-%d') for d in _t})
                    except Exception:
                        days = []
                    return self._build_run_meta(_ch, campaign=campaign,
                                                data_days=days, rows=_meta_rows(_df))

                def _meta_rows(_df):
                    """행수 요약. Status 문자열이 자유형식이라 고정 3분류 대신 실측 집계."""
                    out = {"total": int(len(_df))}
                    if 'Status' in _df.columns:
                        counts = _df['Status'].astype(str).value_counts()
                        out["by_status"] = {str(k): int(v) for k, v in counts.items()}
                    return out

                def _ch_header(ch):
                    """채널별 세팅 헤더 한 줄(파일 상단)."""
                    lbl, tag = self._channel_settings_tag(int(ch))
                    cfg = self._channel_configs.get(int(ch)) or {}
                    return (f"# Channel {int(ch)} ({lbl}) settings: {tag}  "
                            f"gas_temp={cfg.get('gas_temp', 0)}°C  refs={','.join(g for g in self.engine.gas_list)}")

                # ── 배치: output/{campaign}/{YYYY-MM-DD}/fitting/ (A3) ──
                # 디렉터리는 **시간축만** 인코딩한다. 옛 `{창}/{날짜}/{neg}/{QC}/` 4단은
                # 파일시스템을 인덱스로 쓴 것이라 패싯 순서가 고정됐다("QC 끈 것 전부"를
                # 보려면 창 폴더를 전부 걸어야 함). 이제 그 패싯은 전부 `.meta.json`에
                # 있으므로 폴더로 나눌 이유가 없다.
                # 세팅 구분은 파일명의 **runid**가 한다 — 다른 세팅 = 다른 runid = 다른
                # 파일이라 서로 못 덮는다. 같은 세팅 재핏만 같은 이름으로 와서
                # `_archive`로 밀린다(비파괴 — 이전 버전 전부 보존).
                # 핏은 스캔 단위 독립이라 날짜별로 잘라 저장해도 무손실.
                from core.result_io import archive_existing
                campaign = (getattr(self, '_ed_campaign', None)
                            and self._ed_campaign.text().strip()) or DEFAULT_CAMPAIGN

                chans = sorted(df['Channel'].dropna().unique()) if 'Channel' in df.columns else []
                base_dir = os.path.dirname(path) or (self._dlg_dir('save') or '.')
                arch_base = _campaign_dir(base_dir, campaign)   # {base}/{campaign}/_archive/…
                _tt_all = pd.to_datetime(df['Time'], errors='coerce')
                day_keys = _tt_all.dt.strftime('%y%m%d').where(_tt_all.notna(), 'nodate')
                multi = len(chans) > 1

                written, n_files, n_archived, runids = [], 0, 0, []
                for day_tag in sorted(day_keys.unique()):
                    dsub = df[day_keys == day_tag]
                    if multi:
                        targets = [(ch, dsub[dsub['Channel'] == ch]) for ch in chans]
                    else:
                        targets = [((chans[0] if chans else self._active_channel), dsub)]
                    for ch, ssub in targets:
                        if ssub.empty:
                            continue
                        meta = _build_meta(ssub, ch, campaign)
                        lbl, _tag = self._channel_settings_tag(int(ch))
                        fpath = _out_path(base_dir, campaign, day_tag, kind='fitting',
                                          channel=ch, label=lbl,
                                          runid=(meta or {}).get('runid'), ext=ext)
                        os.makedirs(os.path.dirname(fpath), exist_ok=True)
                        # 밀려나는 `.dat`의 meta도 같이 보낸다 — 안 그러면 아카이브된
                        # 결과가 설정 없는 고아가 되고, 새 meta가 그 자리를 덮는다.
                        if archive_existing(fpath, arch_base):
                            n_archived += 1
                            archive_existing(run_meta.meta_path_for(fpath), arch_base)
                        _write_df(ssub, fpath, _ch_header(ch) if multi else "")
                        if meta:
                            run_meta.write_meta(fpath, meta)   # `.dat` 포맷 불변 — 옆에 쓴다
                            runids.append(meta['runid'])
                        n_files += 1
                        written.append(f"{os.path.basename(fpath)}  ({len(ssub)} rows)")

                self._autosave_retire()   # E3: 정식 저장 성공 → autosave는 역할 끝

                n_days = day_keys.nunique()
                arch_note = f", {n_archived} previous → _archive" if n_archived else ""
                rid_disp = "/".join(sorted(set(runids))) or "no-runid"
                if auto:
                    self.status.setText(
                        f"Auto-saved → {campaign}/{n_days} day(s)/fitting  "
                        f"[{rid_disp}] ({n_files} file{arch_note})")
                else:
                    _shown = written if len(written) <= 12 else written[:12] + [f"… +{len(written)-12} more"]
                    QMessageBox.information(
                        self, "Success",
                        "Saved!\n\n"
                        f"{base_dir}\\{campaign}\\{{YYYY-MM-DD}}\\fitting\n"
                        f"   runid {rid_disp}  (±Neg={allow_neg} / QC={qc_str})\n"
                        f"   {n_days} day(s), {n_files} file(s){arch_note}\n\n"
                        "Saved files:\n  " + "\n  ".join(_shown) +
                        "\n\n※ Every .dat has a .meta.json beside it with the full settings,\n"
                        "   and the same settings stay in the .dat's top # header.\n"
                        "※ The file dialog now picks the LOCATION; the name is uniform\n"
                        "   ({date}_{CH}_{label}_{runid}) so different settings never collide.")
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"An error occurred while saving:\n{e}")

    # ---------------------------------------------------------
    # Viewer Events (Table Click Sync)
    # ---------------------------------------------------------
    def on_table_double_click(self, row, col):
        """
        Replays the stored fit for a completed row.

        Double-clicking a result row re-evaluates the engine model using the
        fit parameters (shifts, squeezes, gas_coeffs, etc.) that were saved for
        that file, then sends the result to the monitor — allowing you to inspect
        any individual spectrum without re-running the full analysis.
        """
        def _fail(msg):
            self.status.setText(f"Double-click: {msg}")
            self.status.setStyleSheet("color: red; font-weight: bold;")

        # Bring the Analysis Monitor into view regardless of which main tab the
        # user is currently looking at — otherwise the replay can render correctly
        # in the background while looking, from the user's seat, like nothing happened.
        try:
            self.main_tabs.setCurrentWidget(self._tab_pages.get(self.monitor, self.monitor))
        except Exception:
            pass

        # File name lives in col 0 normally, but col 1 when the "Ch" column is
        # prepended in multi-channel mode.
        fc = 1 if getattr(self, '_multi_channel_mode', False) else 0
        item = self.table.item(row, fc)
        if item is None:
            _fail(f"no cell at row {row}, col {fc}")
            return
        fname = item.text()

        # 클릭한 행의 채널부터 먼저 알아낸다 — 결과 테이블은 모든 채널 탭의 결과를 한
        # 테이블에 같이 보여주지만, 그 파일 경로는 self.file_list(= 지금 선택돼 있는 채널
        # 탭의 파일목록)가 아니라 self._channel_files[그 행의 채널]에만 들어있다. 예전엔
        # self.file_list만 뒤져서, CH3 탭을 보고 있는 동안 CH1/CH2 결과행을 더블클릭하면
        # "파일을 못 찾음"으로 조용히 실패했다(지금은 메시지로 뜸).
        ch_txt = self.table.item(row, 0).text() if fc == 1 else ''
        want_ch = int(ch_txt.replace('CH', '')) if ch_txt.startswith('CH') else None
        search_list = self._channel_files.get(want_ch, self.file_list) if want_ch else self.file_list

        entry = self._entry_from_display_name(fname, search_list)
        if not entry:
            _fail(f"'{fname}' not found in CH{want_ch or self._active_channel}'s file list "
                  "(switch to that channel's tab and try again)")
            return
        filepath = self._entry_filepath(entry)
        row_idx  = self._row_index_from_display_name(fname)

        # 파일명으로 결과 조회 (행 인덱스가 아니라 → 정렬/순서 어긋나도 안전).
        # 멀티채널이면 같은 파일명이 채널마다 있을 수 있으니 클릭한 행의 채널까지 일치시킨다.
        def _match(r):
            if r.get('File') != fname:
                return False
            return want_ch is None or int(r.get('Channel', 1)) == want_ch
        _res = (self.results[row] if (row < len(self.results) and _match(self.results[row]))
                else next((r for r in self.results if _match(r)), None))
        if _res is None:
            _fail(f"no stored result matches '{fname}'" + (f" CH{want_ch}" if want_ch else ""))
            return
        params = _res.get('Params')
        if not params:
            _fail(f"'{fname}' has no saved fit parameters (Status={_res.get('Status', '?')})")
            return

        # 클릭한 결과의 채널로 Monitor 표시채널을 맞춰 채널필터에 막히지 않게 한다.
        ch = 1
        try:
            ch = int(params.get('channel', _res.get('Channel', 1)))
            if hasattr(self.monitor, 'cb_fit_channel'):
                self.monitor.cb_fit_channel.setCurrentIndex(max(0, min(ch - 1, self.monitor.cb_fit_channel.count() - 1)))
        except Exception:
            pass

        # self.engine / txt_min / txt_max only ever reflect the currently active
        # channel TAB (_apply_config swaps them on every tab switch) — if the
        # clicked result is a different channel, replaying with them would rebuild
        # the model using the wrong references/wavecal/fit-range. Build that
        # channel's own (throwaway) engine instead, same as the parallel-fit
        # workers already do via _build_engine_from_config.
        replay_engine = self.engine
        f_min_txt, f_max_txt = self.txt_min.text(), self.txt_max.text()
        if ch != self._active_channel:
            cfg = self._channel_configs.get(ch)
            if cfg is not None:
                try:
                    replay_engine = self._build_engine_from_config(cfg)
                    f_min_txt = cfg.get('f_min', f_min_txt)
                    f_max_txt = cfg.get('f_max', f_max_txt)
                except Exception as e:
                    print(f"Replay: falling back to active engine for CH{ch}: {e}")

        try:
            f_min, f_max = int(f_min_txt), int(f_max_txt)

            # load_measurement_with_hk handles alpha_trace.dat, Araon Mega-Matrix,
            # and plain 1D spectra internally — unlike the naive load_measurement
            # (fixed column-count CSV parser), which chokes on alpha_trace.dat's
            # ragged field counts. Always route through it, passing the fit's own
            # channel so Mega-Matrix multi-channel rows slice the right columns.
            pixel_idx, intensity_raw, _, _, _ = DataIO.load_measurement_with_hk(
                filepath, f_min, f_max, row_index=row_idx, channel=ch)

            intensity_fit, _, intensity_poly, _, _ = replay_engine.get_model_components(
                pixel_idx,
                shifts=params['shifts'],
                squeezes=params['squeezes'],
                gas_coeffs=params['gas_coeffs'],
                poly_coeffs=params['poly_coeffs'],
                etalon_amp=params.get('etalon_amp', 0.0),
                etalon_freq=params.get('etalon_freq', 0.0),
                etalon_phase=params.get('etalon_phase', 0.0)
            )

            self.monitor.tabs.setCurrentIndex(0)

            # Components 탭도 replay_engine의 gas_list/interpolators로 그려야 하므로
            # monitor의 엔진 참조를 렌더링 동안만 바꿔치기하고 원복한다.
            old_monitor_engine = self.monitor.engine
            self.monitor.engine = replay_engine
            try:
                self.monitor.update_spectrum(
                    pixel_idx, intensity_raw, intensity_fit, intensity_poly, params, f"{fname} (Replay)"
                )
            finally:
                self.monitor.engine = old_monitor_engine
            view_ch = getattr(self.monitor, '_view_channel', 1)
            if view_ch != ch:
                _fail(f"replay is CH{ch} but Monitor 'Show channel' is stuck on CH{view_ch} "
                      "— plot was skipped by the channel filter.")
            else:
                self.status.setText(f"Replay: {fname} (CH{ch})")
                self.status.setStyleSheet("color: green;")
        except Exception as e:
            print(f"Double-click viewer failed to load: {e}")
            _fail(f"failed to load '{fname}': {e}")
                
    def on_table_single_click(self, row, col):
        # 결과가 있으면 클릭만으로 그 스캔 fit 그래프(리플레이) 표시; 없으면 기존 raw 뷰어.
        fc = 1 if getattr(self, '_multi_channel_mode', False) else 0
        if 0 <= row < self.table.rowCount() and self.table.item(row, fc) is not None:
            fname = self.table.item(row, fc).text()
            if any(r.get('File') == fname for r in self.results):
                self.on_table_double_click(row, col)
                return
        if self.monitor.tabs.currentIndex() == 3 and self.monitor.cb_view.currentIndex() == 0:
            self.refresh_viewer()
            
    def refresh_viewer(self):
        """Updates the fast viewer tab with raw measurement or reference data."""
        idx = self.monitor.cb_view.currentIndex()
        # Target fit band (nm) — used to zoom the reference view to the fit window.
        try:
            band = (self.spin_fit_start_nm.value(), self.spin_fit_end_nm.value())
        except Exception:
            band = None

        if idx == 0: # Measurement Data
            row = self.table.currentRow()
            if row < 0 or row >= self.table.rowCount():
                return

            fc = 1 if getattr(self, '_multi_channel_mode', False) else 0
            it = self.table.item(row, fc)
            if it is None:
                return
            fname = it.text()
            entry = self._entry_from_display_name(fname)
            if entry:
                fp  = self._entry_filepath(entry)
                ri  = self._row_index_from_display_name(fname)
                try:
                    pixel_idx, intensity_raw, _, _, _ = DataIO.load_measurement_with_hk(fp, pixel_min=0, row_index=ri)
                    self.monitor.plot_viewer(pixel_idx, intensity_raw, f"Meas: {fname}", 'b')
                except Exception as e:
                    print(f"Viewer load failed: {e}")
        else: # Reference Data
            ref_name = self.monitor.cb_view.currentText().replace("Ref: ", "")
            is_raw = self.monitor.chk_raw.isChecked() 
            
            if is_raw and ref_name in self.engine.raw_references:
                y = self.engine.raw_references[ref_name]
                self.monitor.plot_viewer(np.arange(len(y)), y, f"Ref (RAW): {ref_name}", 'r', style='.', xband=band)
            elif ref_name in self.engine.interpolators:
                y = self.engine.interpolators[ref_name](np.arange(len(self.engine.raw_references[ref_name])))
                self.monitor.plot_viewer(np.arange(len(y)), y, f"Ref (Conv): {ref_name}", 'r', style='-', xband=band)


    @staticmethod
    def _load_wavecal_array(path):
        """wavecal 파일 → 1D nm 배열(load_wavelength_cal과 동일 파싱). 실패 시 None."""
        try:
            try:
                df = pd.read_csv(path, sep=r'\s+', header=None)
            except Exception:
                df = pd.read_csv(path, sep=',', header=None)
            for i in range(df.shape[1]):
                col = pd.to_numeric(df.iloc[:, i], errors='coerce').dropna()
                if len(col) > 10:
                    return col.values.flatten()
        except Exception:
            pass
        return None

    def _build_engine_from_config(self, cfg):
        """채널 config(dict)로 독립 UniversalEngine 생성(자체 wavecal+references+scaling).
        채널별 병렬 피팅용. 실패한 ref는 건너뛴다."""
        from core.engine import UniversalEngine
        eng = UniversalEngine()
        wave = None
        # 리플레이 엔진이 원본 핏의 엔진과 달라지면, 같은 스캔인데 다른 숫자가
        # 나오고 사용자는 "핏이 불안정하다"고 오해한다. 달라진 항목을 모아 알린다.
        _diffs = []
        wlp = resolve_ref_path(cfg.get('wl_path', ''))
        if wlp and os.path.exists(wlp):
            wave = self._load_wavecal_array(wlp)
            if wave is None:
                _diffs.append(f"wavecal 읽기 실패({os.path.basename(wlp)})")
        elif wlp:
            _diffs.append(f"wavecal 파일 없음({os.path.basename(wlp)})")
        if wave is None:   # 폴백: 현재 로드된 마스터 wavecal
            wl = getattr(self, 'wavelengths', None)
            wave = np.asarray(wl, dtype=float).flatten() if wl is not None else None
            if wave is not None and wlp:
                _diffs.append("마스터 wavecal로 대체(파장축이 원본과 다를 수 있음)")
        if wave is not None:
            eng.set_wavelength_axis(wave)
        for ref in cfg.get('refs', []):
            ref_path = resolve_ref_path(ref.get('path', ''))
            if not os.path.exists(ref_path):
                _diffs.append(f"{ref.get('name')}: 레퍼런스 파일 없음")
                continue
            try:
                eng.add_reference(name=ref['name'], filepath=ref_path,
                                  wave_nm=wave, multiplier=10.0 ** ref.get('mult', 0))
            except Exception as e:
                print(f"[ch engine] ref failed {ref.get('name')}: {e}")
                _diffs.append(f"{ref.get('name')}: 로드 실패({type(e).__name__})")
        try:
            eng.apply_ils_convolution(0.0)
        except Exception as e:
            _diffs.append(f"ILS 적용 실패({type(e).__name__}) — 단면이 원본과 다름")
        if _diffs:
            _msg = ("⚠ 리플레이 엔진이 원본과 다르다 — " + " · ".join(_diffs)
                    + ". 여기 보이는 핏은 저장된 결과와 같지 않을 수 있다.")
            print(f"[ch engine] {_msg}")
            _status = getattr(self, 'status', None)
            if _status is not None:
                _status.setText(_msg)
        return eng

