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
from core.result_io import MISFIT_CHI2 as _MISFIT_CHI2
from core.engine import UniversalEngine
from gui.theme import AUGUR
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
                from core.result_io import flatten_qc_backup
                df = flatten_qc_backup(df)

                current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                robust_on = hasattr(self, 'chk_robust') and self.chk_robust.isChecked()
                robust_status = "ON" if robust_on else "OFF"
                etalon_status = "ON" if (not hasattr(self, 'chk_etalon') or self.chk_etalon.isChecked()) else "OFF"

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

                # ── Header: built **per channel from the config frozen at RUN** ──
                # It used to read the live widgets, so every channel file carried the settings of
                # whatever tab was active at save time (CH2 file: "Poly3 444-471nm" on line 1,
                # "Polynomial Degree: 4 / 429.5-462 nm" below) and edits made after RUN leaked in
                # (UX audit 2026-10-02 §6). QC is post-processing, so its save-time value is right.
                _frozen_cfgs = ((getattr(self, '_run_frozen', None) or {}).get('configs')
                                or self._channel_configs)
                _alpha_in = any(DataIO._is_alpha_trace_format(self._entry_filepath(e))
                                for fl in (getattr(self, '_alpha_groups', None) or {}).values()
                                for e in fl[:1])
                _NA_ALPHA = "n/a — alpha input (applied when the alpha was generated; see the alpha header)"

                def _constraint(rp, first_gas, prefix):
                    curr, seen = first_gas, set()
                    while curr and curr not in seen:
                        seen.add(curr)
                        props = rp.get(curr, {})
                        mode = props.get(f"{prefix}_mode", "Limit")
                        val = str(props.get(f"{prefix}_val", "")).strip()
                        if mode == "Free":
                            return "Free"
                        if mode != "Link":
                            return val.replace(" ", "")
                        curr = val
                    return "Unknown"

                def _header_for(ch, sub):
                    cfg = _frozen_cfgs.get(int(ch)) or {}
                    try:
                        int(cfg.get('f_min')); int(cfg.get('f_max'))
                        _cfg_range_ok = True
                    except (TypeError, ValueError):
                        _cfg_range_ok = False
                    if not _cfg_range_ok:
                        # Never write a made-up range into the reproducibility record (principle 4).
                        rng = "UNREADABLE — the channel config has no pixel range (not 0-0)"
                    elif cfg.get('fit_unit') == 'px':
                        rng = f"Pixel {cfg.get('f_min')}-{cfg.get('f_max')} (px window)"
                    else:
                        rng = (f"Pixel {cfg.get('f_min')}-{cfg.get('f_max')} "
                               f"({float(cfg.get('fit_start_nm', 0)):.1f}-{float(cfg.get('fit_end_nm', 0)):.1f}nm)")
                    rp = cfg.get('ref_props', {}) or {}
                    g0 = next((r.get('name') for r in cfg.get('refs', []) if r.get('name')), None)
                    sh = f"Sh[{_constraint(rp, g0, 'sh')}]" if g0 else "Sh[None]"
                    sq = f"Sq[{_constraint(rp, g0, 'sq')}]" if g0 else "Sq[None]"
                    try:
                        _ts = pd.to_datetime(sub['Time'], errors='coerce').dropna()
                        period = (f"{_ts.min():%Y-%m-%d %H:%M} ~ {_ts.max():%Y-%m-%d %H:%M}"
                                  if len(_ts) else span_str)
                    except Exception:
                        period = span_str
                    has_smooth = any(str(c).endswith('_Smooth') for c in sub.columns)
                    kq, kr = cfg.get('kalman_q', kalman_q), cfg.get('kalman_r', kalman_r)
                    neg = "ON" if cfg.get('allow_negative_gas', allow_neg_on) else "OFF"
                    if _alpha_in:
                        phys = [f"# Dark Current Subtraction: {_NA_ALPHA}",
                                f"# Detector Offset Subtraction: {_NA_ALPHA}",
                                f"# Stray Light Correction: {_NA_ALPHA}",
                                f"# Temporal I0 Interpolation: {_NA_ALPHA}",
                                f"# Purge Gas RL Factor: {_NA_ALPHA}",
                                f"# Measurement Flags: {_NA_ALPHA}"]
                    else:
                        phys = [f"# Dark Current Subtraction: {dark_loaded}  (scale={dark_scale_val:.4f})",
                                f"# Detector Offset Subtraction: {offset_loaded}  (scale={offset_scale_val:.4f})",
                                f"# Stray Light Correction: {'ON' if stray_light_val > 0 else 'OFF'}  (epsilon={stray_light_val:.4f})",
                                f"# Temporal I0 Interpolation: {temporal_i0}",
                                f"# Purge Gas RL Factor: {float(cfg.get('rl_factor', 1.0)):.4f}  (1.0 = no correction)",
                                f"# Cavity Length d: {float(cfg.get('cavity_d', self.spin_d_len.value())):.2f} cm",
                                f"# Measurement Flags: Ambient={self.txt_flag_amb.text().strip()}, "
                                f"ZA={self.txt_flag_za.text().strip()}, He={self.txt_flag_he.text().strip()}"]
                    lines = [
                        "# ==========================================================",
                        "# Augur Analysis Report",
                        f"# Generated: {current_time}",
                        f"# Code Version: {_codever()}",
                        f"# Channel: CH{int(ch)} ({(cfg.get('data_label') or '').strip() or '-'})"
                        "  — settings frozen at RUN",
                        f"# Data Period: {period}",
                        f"# Fit Range: {rng}",
                        f"# Polynomial Degree: {cfg.get('poly_deg')}",
                        f"# Tikhonov Lambda: {float(cfg.get('tikhonov_lambda', 0.0) or 0.0):g}",
                        f"# Robust Fitting (IRLS): {'ON' if cfg.get('use_robust') else 'OFF'}",
                        f"# Etalon Term (sin/cos fringe): {'ON' if cfg.get('use_etalon', True) else 'OFF'}",
                        f"# Allow Negative Gas (±Neg): {neg}",
                        f"# Auto QC: {qc_str}",
                        "# Excluded rows: gas columns NaN; pre-exclusion values in {gas}_preQC, Status_preQC",
                        "# Error columns (1 sigma, ppb): {gas}_Error = fit covariance, white residual (product column); "
                        "{gas}_ErrorCorr = same fit with the residual autocorrelation (sandwich); "
                        "{gas}_ErrorJoint = incl. shift/squeeze; {gas}_MDL = 3 x {gas}_Error (fit-based). "
                        "None contains the I0/R/etalon structural terms. Measured floor / MDL: "
                        "tools/zero_air_floor.py on {campaign}/_zeroair/ (written by alpha generation); "
                        "per-record structural terms: tools/structural_budget.py --result <this file>.",
                        "# Calibration context (alpha input): I0_/R_dt_s = s to the nearest knot, I0_/R_gap_h = "
                        "bracketing knot interval, I0_/R_edge = 1 if extrapolated; NaN = knots unknown "
                        "(alpha made before 2026-10-03 without _calknots.json).",
                        "# Reference Masks: " + ("; ".join(
                            f"{r['name']} " + (f"keep px {r['mask']['range'][0]}-{r['mask']['range'][1]}"
                                               if r['mask'].get('mode') == 'manual'
                                               else f"zero <{r['mask'].get('threshold_pct')}% of peak")
                            for r in cfg.get('refs', []) if r.get('mask')) or "none"),
                        f"# Step Limit: {cfg.get('step_limit', step_val)} px",
                        f"# OK RMS Threshold: {rms_thresh_pct:.1f}%  (low-signal retry trigger; "
                        f"OK/Unstable label = Chi2 <= {_MISFIT_CHI2})",
                        (f"# Kalman Filter: Q={float(kq):.4f}, R={float(kr):.3f}  (concentration columns = raw fit; _Smooth = Kalman-filtered)"
                         if has_smooth else
                         "# Kalman Filter: not applied in this file (no _Smooth columns; Fast mode)"),
                        *phys,
                        f"# Reference Constraints: {sh}, {sq}",
                        f"# Etalon-Gas Collinearity (diagnostic only, fit unchanged): {collin_line}",
                        "# ==========================================================\n",
                    ]
                    return "\n".join(lines)
                is_csv = path.endswith('.csv')
                ext = '.csv' if is_csv else '.dat'

                def _write_df(_df, _path, _ch_hdr="", _ch=None):
                    with open(_path, 'w', encoding='utf-8') as f:
                        if _ch_hdr:
                            f.write(_ch_hdr + "\n")
                        f.write(_header_for(self._active_channel if _ch is None else _ch, _df))
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
                        # archive_existing moves the `.meta.json` with it (same archived name).
                        if archive_existing(fpath, arch_base):
                            n_archived += 1
                        _write_df(ssub, fpath, _ch_header(ch) if multi else "", ch)
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
    def _replay_fail(self, msg):
        self.status.setText(f"Replay: {msg}")
        self.status.setStyleSheet(f"color: {AUGUR.fail}; font-weight: bold;")

    def on_table_double_click(self, row, col):
        """Replay the stored fit of a result-table row (see _replay_result)."""
        # File name lives in col 0 normally, but col 1 when the "Ch" column is
        # prepended in multi-channel mode.
        fc = 1 if getattr(self, '_multi_channel_mode', False) else 0
        item = self.table.item(row, fc)
        if item is None:
            self._replay_fail(f"no cell at row {row}, col {fc}")
            return
        fname = self._file_cell_text(item)

        # 클릭한 행의 채널부터 먼저 알아낸다 — 결과 테이블은 모든 채널 탭의 결과를 한
        # 테이블에 같이 보여주지만, 그 파일 경로는 self.file_list(= 지금 선택돼 있는 채널
        # 탭의 파일목록)가 아니라 self._channel_files[그 행의 채널]에만 들어있다. 예전엔
        # self.file_list만 뒤져서, CH3 탭을 보고 있는 동안 CH1/CH2 결과행을 더블클릭하면
        # "파일을 못 찾음"으로 조용히 실패했다(지금은 메시지로 뜸).
        ch_txt = self.table.item(row, 0).text() if fc == 1 else ''
        want_ch = int(ch_txt.replace('CH', '')) if ch_txt.startswith('CH') else None

        # 파일명으로 결과 조회 (행 인덱스가 아니라 → 정렬/순서 어긋나도 안전).
        # 멀티채널이면 같은 파일명이 채널마다 있을 수 있으니 클릭한 행의 채널까지 일치시킨다.
        def _match(r):
            if r.get('File') != fname:
                return False
            return want_ch is None or int(r.get('Channel', 1)) == want_ch
        _res = (self.results[row] if (row < len(self.results) and _match(self.results[row]))
                else next((r for r in self.results if _match(r)), None))
        if _res is None:
            self._replay_fail(f"no stored result matches '{fname}'" + (f" CH{want_ch}" if want_ch else ""))
            return
        self._replay_result(_res)

    def _replay_result(self, _res):
        """
        Replays the stored fit of one result dict (table row or Conc-plot point).

        Re-evaluates the engine model using the fit parameters (shifts, squeezes,
        gas_coeffs, etc.) saved for that scan, then sends the result to the
        monitor — inspect any individual spectrum without re-running the analysis.
        Works the same for Step and Fast runs: both store 'Params' per result.
        """
        _fail = self._replay_fail

        # Bring the Analysis Monitor into view regardless of which main tab the
        # user is currently looking at — otherwise the replay can render correctly
        # in the background while looking, from the user's seat, like nothing happened.
        try:
            self.main_tabs.setCurrentWidget(self._tab_pages.get(self.monitor, self.monitor))
        except Exception:
            pass

        fname = _res.get('File', '')
        want_ch = int(_res.get('Channel', 1)) if getattr(self, '_multi_channel_mode', False) else None
        search_list = self._channel_files.get(want_ch, self.file_list) if want_ch else self.file_list

        entry = self._entry_from_display_name(fname, search_list)
        if not entry:
            _fail(f"'{fname}' not found in CH{want_ch or self._active_channel}'s file list "
                  "(switch to that channel's tab and try again)")
            return
        filepath = self._entry_filepath(entry)
        row_idx  = self._row_index_from_display_name(fname)

        params = _res.get('Params')
        if not params:
            _fail(f"'{fname}' has no saved fit parameters (Status={_res.get('Status', '?')})")
            return

        # 클릭한 결과의 채널로 Monitor 표시채널을 맞춰 채널필터에 막히지 않게 한다.
        ch = 1
        try:
            ch = int(params.get('channel', _res.get('Channel', 1)))
            if hasattr(self.monitor, 'cb_fit_channel'):
                # The combo only lists channels with data (e.g. [CH2, CH3]); index ch-1 picked
                # CH3 for a CH2 replay and the plot was skipped. Select by the stored channel.
                _i = self.monitor.cb_fit_channel.findData(ch)
                if _i >= 0:
                    self.monitor.cb_fit_channel.setCurrentIndex(_i)
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

            intensity_fit, _, intensity_poly, etalon_wave, _ = replay_engine.get_model_components(
                pixel_idx,
                shifts=params['shifts'],
                squeezes=params['squeezes'],
                gas_coeffs=params['gas_coeffs'],
                poly_coeffs=params['poly_coeffs'],
                etalon_amp=params.get('etalon_amp', 0.0),
                etalon_freq=params.get('etalon_freq', 0.0),
                etalon_phase=params.get('etalon_phase', 0.0)
            )

            # Same quantities the live run emits (worker plot_update): Meas = signal − poly −
            # etalon, Fit = model − poly − etalon. Passing α and the full model here made the
            # Polynomial panel add the poly twice (dots = α + poly) and gave "Intensity" a
            # different meaning in replay than during the run.
            _bg = intensity_poly + etalon_wave
            intensity_raw = intensity_raw - _bg
            intensity_fit = intensity_fit - _bg

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
                self.status.setStyleSheet(f"color: {AUGUR.ok};")
        except Exception as e:
            print(f"Double-click viewer failed to load: {e}")
            _fail(f"failed to load '{fname}': {e}")
                
    def on_table_single_click(self, row, col):
        # 결과가 있으면 클릭만으로 그 스캔 fit 그래프(리플레이) 표시; 없으면 기존 raw 뷰어.
        fc = 1 if getattr(self, '_multi_channel_mode', False) else 0
        if 0 <= row < self.table.rowCount() and self.table.item(row, fc) is not None:
            fname = self._file_cell_text(self.table.item(row, fc))
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
            fname = self._file_cell_text(it)
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
        """wavecal 파일 → 1D nm 배열. 단일 출처는 `DataIO.load_wavecal_array`."""
        return DataIO.load_wavecal_array(path)

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
                _diffs.append(f"wavecal read failed ({os.path.basename(wlp)})")
        elif wlp:
            _diffs.append(f"wavecal file missing ({os.path.basename(wlp)})")
        if wave is None:   # 폴백: 현재 로드된 마스터 wavecal
            wl = getattr(self, 'wavelengths', None)
            wave = np.asarray(wl, dtype=float).flatten() if wl is not None else None
            if wave is not None and wlp:
                _diffs.append("fell back to master wavecal (wavelength axis may differ from original)")
        if wave is not None:
            eng.set_wavelength_axis(wave)
        for ref in cfg.get('refs', []):
            ref_path = resolve_ref_path(ref.get('path', ''))
            if not os.path.exists(ref_path):
                _diffs.append(f"{ref.get('name')}: reference file missing")
                continue
            try:
                eng.add_reference(name=ref['name'], filepath=ref_path,
                                  wave_nm=wave, multiplier=10.0 ** ref.get('mult', 0))
                if ref.get('mask'):
                    eng.apply_mask_spec(ref['name'], ref['mask'])
            except Exception as e:
                print(f"[ch engine] ref failed {ref.get('name')}: {e}")
                _diffs.append(f"{ref.get('name')}: load failed ({type(e).__name__})")
        try:
            eng.apply_ils_convolution(0.0)
        except Exception as e:
            _diffs.append(f"ILS apply failed ({type(e).__name__}) — cross-sections differ from original")
        if _diffs:
            _msg = ("⚠ replay engine differs from the original — " + " · ".join(_diffs)
                    + ". The fit shown here may not match the saved results.")
            print(f"[ch engine] {_msg}")
            _status = getattr(self, 'status', None)
            if _status is not None:
                _status.setText(_msg)
        return eng

