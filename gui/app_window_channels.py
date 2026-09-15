"""gui/app_window_channels.py
CAESARAnalyzer §14 — 채널 탭(독립 설정) + 시나리오 config (gui/app_window.py에서 분리).

**순수 이동이다.** 메서드 본문은 한 글자도 안 고쳤다 — 호출부가 전부 self.xxx()라
믹스인으로 옮기는 것만으로 동작이 같다. 로직 개선은 다음 PR로.
가드는 tools/test_app_window_smoke.py (표면 골든 + 믹스인 이름 충돌 검사).
"""
import copy
import json
import os

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem
from core.paths import resolve_ref_path
from .app_window_policy import _scenario_gas_policy


class ChannelConfigMixin:
    """§14 — 채널 탭(독립 설정) + 시나리오 config. CAESARAnalyzer에 믹스인된다."""

    # ── 채널 탭(독립 설정) ─────────────────────────────────────────────
    # ══════════════════════════════════════════════════════════════════════
    # §14 채널 탭 + 시나리오 config
    # ══════════════════════════════════════════════════════════════════════
    def _on_channel_tab_changed(self, idx):
        """탭 전환 — 현재 채널 설정을 저장하고 선택 채널 설정을 UI/엔진에 로드."""
        if self._switching_channel or idx < 0:
            return
        ch = self._channel_tabbar.tabData(idx)
        if ch is None or ch == self._active_channel:
            return
        # 현재 채널 스냅샷 저장(단, 방금 삭제된 채널은 다시 저장하지 않음)
        if self._active_channel in self._channel_configs:
            self._channel_configs[self._active_channel] = self._capture_config()
            self._channel_files[self._active_channel] = list(self.file_list)
        self._active_channel = ch
        cfg = self._channel_configs.get(ch)
        if cfg is not None:
            self._switching_channel = True
            try:
                self._apply_config(cfg, load_refs=True)
            finally:
                self._switching_channel = False
        # 표/그래프를 이 채널이 들고 있는 데이터로 교체
        self._show_channel_files(ch)

    def _show_channel_files(self, ch):
        """선택 채널이 보유한 파일 리스트를 표에 표시(소유권은 그대로).

        피팅 결과가 이미 있으면(self.results) 표는 건드리지 않는다 — 멀티채널 결과 테이블은
        모든 채널을 한 표에 같이 보여주는 게 원래 의도라(Ch 칼럼으로 구분), 탭을 바꿀 때마다
        그 채널의 '입력 파일 목록' 미리보기로 표를 갈아치우면 방금 돌린 피팅 결과가 통째로
        사라진 것처럼 보인다. file_list 자체는(Setup 등 다른 코드가 참조하므로) 그대로 갱신한다."""
        self.file_list = list(self._channel_files.get(ch, []))
        if self.results:
            self.status.setText(f"CH{ch} config — results table kept ({len(self.results)} rows)")
            return
        self.table.setRowCount(len(self.file_list))
        self.table.clearContents()
        for i, fp in enumerate(self.file_list):
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(self._entry_filepath(fp))))
        self.status.setText(f"CH{ch} — {len(self.file_list)} file(s)")
        if self.file_list:
            self._auto_detect_channels()

    def _add_channel_tab(self):
        """— 현재 채널 설정을 복사한 새 채널 탭 생성(시작값=복사본)."""
        import copy
        self._channel_configs[self._active_channel] = self._capture_config()
        new_ch = (max(self._channel_configs.keys()) + 1) if self._channel_configs else 1
        self._channel_configs[new_ch] = copy.deepcopy(self._channel_configs[self._active_channel])
        self._channel_files[new_ch] = []          # 새 채널 데이터는 비어서 시작(설정만 복사)
        i = self._channel_tabbar.addTab(f"CH{new_ch}")
        self._channel_tabbar.setTabData(i, new_ch)
        self._channel_tabbar.setCurrentIndex(i)   # currentChanged → 복사본 적용

    def _del_channel_tab(self):
        """— 현재 채널 삭제(최소 1채널 유지)."""
        if self._channel_tabbar.count() <= 1:
            return
        idx = self._channel_tabbar.currentIndex()
        ch = self._channel_tabbar.tabData(idx)
        self._channel_configs.pop(ch, None)
        self._channel_files.pop(ch, None)
        # 제거된 채널을 다시 저장하지 않도록 active를 무효화 후 removeTab
        # → currentChanged가 인접 채널을 로드.
        self._active_channel = None
        self._channel_tabbar.removeTab(idx)

    @staticmethod
    def _time_shift_hours(val):
        """저장값 → 출력 시각에 그대로 더할 시프트(시간, float).
        신규 포맷은 float. 레거시 'input_tz' 문자열 호환: 'KST(+9)'는 옛 동작(출력 −9h)과
        같게 −9.0, 그 외/'UTC'/빈값은 0.0으로 매핑."""
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().upper()
        if s.startswith('KST'):
            return -9.0
        try:
            return float(s.replace('UTC', '').replace('H', '').strip() or 0)
        except ValueError:
            return 0.0

    def _capture_config(self):
        """현재 UI/엔진 설정 전체를 dict로 캡처 — 채널 전환·복사·시나리오 저장에 재사용.
        (레퍼런스 경로·배율, wavecal, 픽셀/nm 핏레인지, poly/step/λ/robust/kalman, cavity)"""
        refs_data = []
        for rw in getattr(self, 'ref_widgets', []):
            if rw['n'].text() and rw['fp']:
                refs_data.append({"name": rw['n'].text(), "path": rw['fp'], "mult": rw['mult'].value()})
        return {
            "wl_path": getattr(self, 'loaded_wl_path', ""),
            "refs": refs_data,
            "data_label": self._ed_ch_datalabel.text().strip() if hasattr(self, '_ed_ch_datalabel') else "",
            "time_shift_h": self.spin_time_shift.value() if hasattr(self, 'spin_time_shift') else 0.0,
            "gas_temp": self.spin_gas_temp.value() if hasattr(self, 'spin_gas_temp') else 0.0,
            "f_min": self.txt_min.text(),
            "f_max": self.txt_max.text(),
            "fit_start_nm": self.spin_fit_start_nm.value(),
            "fit_end_nm": self.spin_fit_end_nm.value(),
            "fit_unit": self.cb_fit_unit.currentText() if hasattr(self, 'cb_fit_unit') else "nm",
            "poly_deg": self.spin_poly_deg.value(),
            "step_limit": self.spin_step_limit.value() if hasattr(self, 'spin_step_limit') else 0.5,
            "ref_props": dict(getattr(self, 'ref_props', {})),
            "tikhonov_lambda": self.spin_lambda.value() if hasattr(self, 'spin_lambda') else 0.0,
            "use_robust": self.chk_robust.isChecked() if hasattr(self, 'chk_robust') else False,
            "allow_negative_gas": self.chk_allow_neg.isChecked(),
            "kalman_q": self.spin_kalman_q.value() if hasattr(self, 'spin_kalman_q') else 0.0005,
            "kalman_r": self.spin_kalman_r.value() if hasattr(self, 'spin_kalman_r') else 0.050,
            "cavity_d": self.spin_d_len.value() if hasattr(self, 'spin_d_len') else 100.0,
            "rl_factor": self.spin_rl_factor.value() if hasattr(self, 'spin_rl_factor') else 1.0,
        }

    def _calibration_state(self):
        """`.meta.json`용 캘리브 세트 식별자. `_capture_config`가 안 담는 것들만 모은다.

        파일은 **basename**으로 남긴다 — 절대경로를 넣으면 같은 캘리브가 머신마다 다른
        runid가 된다. 'Auto from ZA/He scans'처럼 파일이 아닌 상태도 그 문구 그대로 남겨야
        "무엇으로 보정했나"가 보존된다."""
        def _lbl(name, default=""):
            w = getattr(self, name, None)
            return w.text().strip() if w is not None else default

        def _val(name, default=None):
            w = getattr(self, name, None)
            return w.value() if w is not None else default

        return {
            "wavecal": os.path.basename(getattr(self, 'loaded_wl_path', "") or ""),
            "ils_fwhm_nm": _val('spin_fwhm_nm'),
            "ils_fwhm_px": _val('spin_fwhm'),
            "i0": _lbl('lbl_i0_path'),
            "r": _lbl('lbl_r_path'),
            "dark": _lbl('lbl_dark_path'),
            "dark_scale": _val('spin_dark_scale'),
            "offset": _lbl('lbl_offset_path'),
            "offset_scale": _val('spin_offset_scale'),
            "stray_light": _val('spin_stray_light'),
            "temporal_i0": bool(getattr(self, 'chk_temporal_i0', None)
                                and self.chk_temporal_i0.isChecked()),
            "d_cm": _val('spin_d_len'),
            "rl_factor": _val('spin_rl_factor'),
        }

    def _qc_state(self):
        """`.meta.json`용 QC/후처리 상태. 재핏 없이 적용되는 값이라 **저장 시점**이 정본이다."""
        def _val(name, default=None):
            w = getattr(self, name, None)
            return w.value() if w is not None else default

        def _chk(name):
            w = getattr(self, name, None)
            return bool(w is not None and w.isChecked())

        return {
            "enabled": _chk('chk_qc'),
            "auto_k": _val('spin_qc_k'),
            "rms_max": _val('spin_qc_rms'),
            "snr_floor": _val('spin_qc_snr'),
            "settling": _chk('chk_settle'),
            "settling_n": _val('spin_settle_n'),
            "ok_rms_pct": _val('spin_rms_thresh'),
            "tikhonov": _val('spin_lambda', 0.0),
            "robust": _chk('chk_robust'),
            "kalman_q": _val('spin_kalman_q'),
            "kalman_r": _val('spin_kalman_r'),
        }

    def _apply_config(self, scenario, load_refs=True):
        """_capture_config 로 만든 dict를 UI/엔진에 복원. load_refs=False면 레퍼런스/엔진은 건드리지 않음."""
        self.txt_min.setText(str(scenario.get("f_min", "")))
        self.txt_max.setText(str(scenario.get("f_max", "")))
        if hasattr(self, '_ed_ch_datalabel'):
            self._ed_ch_datalabel.setText(scenario.get("data_label", ""))
        if hasattr(self, 'spin_time_shift'):
            self.spin_time_shift.setValue(
                self._time_shift_hours(scenario.get("time_shift_h", scenario.get("input_tz", 0.0))))
        if hasattr(self, 'spin_gas_temp'):
            self.spin_gas_temp.setValue(scenario.get("gas_temp", 0.0))
        if "fit_start_nm" in scenario:
            self.spin_fit_start_nm.setValue(scenario["fit_start_nm"])
        if "fit_end_nm" in scenario:
            self.spin_fit_end_nm.setValue(scenario["fit_end_nm"])
        if hasattr(self, 'cb_fit_unit') and "fit_unit" in scenario:
            self.cb_fit_unit.setCurrentText(scenario.get("fit_unit", "nm"))
        self.spin_poly_deg.setValue(scenario.get("poly_deg", 3))
        if hasattr(self, 'spin_step_limit'):
            self.spin_step_limit.setValue(scenario.get("step_limit", 0.5))
        self.ref_props = scenario.get("ref_props", {})
        if hasattr(self, 'spin_lambda'):
            self.spin_lambda.setValue(scenario.get("tikhonov_lambda", 0.0))
        if hasattr(self, 'chk_robust'):
            self.chk_robust.setChecked(scenario.get("use_robust", False))
        if hasattr(self, 'chk_allow_neg'):
            value, provenance = _scenario_gas_policy(
                scenario, self.chk_allow_neg.isChecked())
            self.chk_allow_neg.setChecked(value)
            self._gas_policy_provenance = provenance
            if provenance.startswith("legacy"):
                QMessageBox.warning(
                    self, "Legacy Fit Scenario",
                    "This scenario does not record the ±Neg gas policy. "
                    "The current checkbox value was preserved; verify it before running.")
        if hasattr(self, 'spin_kalman_q'):
            self.spin_kalman_q.setValue(scenario.get("kalman_q", 0.0005))
        if hasattr(self, 'spin_kalman_r'):
            self.spin_kalman_r.setValue(scenario.get("kalman_r", 0.050))
        if hasattr(self, 'spin_d_len') and "cavity_d" in scenario:
            self.spin_d_len.setValue(scenario["cavity_d"])
        if hasattr(self, 'spin_rl_factor') and "rl_factor" in scenario:
            self.spin_rl_factor.setValue(scenario["rl_factor"])

        wl_path = resolve_ref_path(scenario.get("wl_path", ""))
        if wl_path and os.path.exists(wl_path):
            self.load_wavelength_cal(auto_path=wl_path)
        elif hasattr(self, 'lbl_wavecal'):
            self.lbl_wavecal.setText("wavecal: none")
            self.lbl_wavecal.setStyleSheet("color: #B71C1C; font-weight: bold; padding: 2px;")
            self.lbl_wavecal.setToolTip("No wavelength calibration loaded for this channel tab.")
        # L7: 가스별 Sh/Sq 모드 요약 갱신
        self._refresh_shsq_summary()

        if load_refs:
            refs = scenario.get("refs", [])
            # 기존 레퍼런스 UI/엔진 초기화 후 재구성
            for rw in getattr(self, 'ref_widgets', []):
                rw['w'].deleteLater()
            if hasattr(self, 'ref_widgets'):
                self.ref_widgets.clear()
            self.engine.clear_engine()
            for ref in refs:
                ref_path = resolve_ref_path(ref['path'])
                if os.path.exists(ref_path):
                    self.add_ref_row(name=ref['name'], path=ref_path)
                    self.ref_widgets[-1]['mult'].setValue(ref.get('mult', 0))
            if refs:
                self.lock_ref(silent=True)   # 채널 전환/시나리오 적용 자동 재락 — 팝업 없음

    def save_scenario(self):
        """모든 채널 탭 설정을 하나의 JSON으로 저장(v2). load_scenario로 채널 탭 복원."""
        # 현재 채널 스냅샷
        if self._active_channel in self._channel_configs:
            self._channel_configs[self._active_channel] = self._capture_config()
        chans = {c: v for c, v in self._channel_configs.items() if v is not None}
        if not chans:
            chans = {1: self._capture_config()}
        scenario = {
            "version": 2,
            "active": self._active_channel if self._active_channel in chans else sorted(chans)[0],
            "channels": {str(c): cfg for c, cfg in chans.items()},
        }
        cfg = chans.get(scenario["active"], next(iter(chans.values())))
        robust_str = "Robust" if cfg.get("use_robust") else "Std"

        # 파일명: 채널별 특징(라벨[윈도우_Ppoly_가스T]) 나열 → 한눈에 시나리오 구분
        def _ch_short(c, cc):
            lbl = (cc.get('data_label') or '').strip() or f"CH{c}"
            if cc.get('fit_unit') == 'px':
                win = f"{cc.get('f_min', '?')}-{cc.get('f_max', '?')}px"
            else:
                try:
                    win = f"{float(cc.get('fit_start_nm', 0)):.0f}-{float(cc.get('fit_end_nm', 0)):.0f}nm"
                except Exception:
                    win = "win?"
            try:
                gt = float(cc.get('gas_temp', 0) or 0)
            except Exception:
                gt = 0
            gtag = f"_gT{int(gt)}" if gt > 0 else ""
            return f"{lbl}[{win}_P{cc.get('poly_deg', '?')}{gtag}]"
        parts = [_ch_short(c, chans[c]) for c in sorted(chans)]
        default_fname = f"FitSet_{'_'.join(parts)}_{robust_str}.json"
        _start = os.path.join(self._dlg_dir('scenario'), default_fname) if self._dlg_dir('scenario') else default_fname
        path, _ = QFileDialog.getSaveFileName(self, "Save Fit Scenario", _start, "JSON Files (*.json)")
        self._dlg_dir('scenario', path)
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(scenario, f, indent=4)
                QMessageBox.information(self, "Success", f"{len(chans)} channels config saved!\nFile: {os.path.basename(path)}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Save Failed:\n{e}")

    def load_scenario(self):
        """저장된 fit 설정 JSON 복원. v2(채널들) / v1(단일) 모두 지원."""
        path, _ = QFileDialog.getOpenFileName(self, "Load Fit Scenario", self._dlg_dir('scenario'), "JSON Files (*.json)")
        if not path:
            return
        self._dlg_dir('scenario', path)
        self._scenario_name = os.path.splitext(os.path.basename(path))[0]  # .meta.json provenance
        try:
            with open(path, 'r', encoding='utf-8') as f:
                scenario = json.load(f)
            if isinstance(scenario, dict) and "channels" in scenario:   # v2 멀티채널
                chans = {int(c): cfg for c, cfg in scenario["channels"].items()}
                legacy_channels = [ch for ch, cfg in chans.items()
                                   if "allow_negative_gas" not in cfg]
                if legacy_channels:
                    fallback = self.chk_allow_neg.isChecked()
                    for ch in legacy_channels:
                        chans[ch] = dict(chans[ch], allow_negative_gas=fallback)
                    self._legacy_gas_policy_channels = tuple(legacy_channels)
                    QMessageBox.warning(
                        self, "Legacy Fit Scenario",
                        f"Channels {legacy_channels} do not record the ±Neg policy. "
                        f"They were explicitly migrated to the current value ({fallback}); verify before RUN.")
                self._load_channel_scenario(chans, scenario.get("active", sorted(chans)[0]))
                QMessageBox.information(self, "Auto-Load Success",
                                        f"{len(chans)} channels config restored (channel tabs).\n[Load Data] then RUN!")
            else:   # v1 단일(하위호환)
                self._apply_config(scenario, load_refs=True)
                self._channel_configs = {1: self._capture_config()}
                QMessageBox.information(self, "Success", "Config restored (single channel).")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load scenario:\n{e}")

    def _load_channel_scenario(self, chans, active):
        """여러 채널 config를 채널 탭으로 복원."""
        tb = self._channel_tabbar
        self._switching_channel = True
        while tb.count() > 0:
            tb.removeTab(0)
        for ch in sorted(chans):
            i = tb.addTab(f"CH{ch}")
            tb.setTabData(i, ch)
        self._switching_channel = False
        self._channel_configs = dict(chans)
        # 채널 데이터 저장소: 기존 보유분 유지, 신규 채널만 빈 리스트
        self._channel_files = {ch: self._channel_files.get(ch, []) for ch in chans}
        if active not in chans:
            active = sorted(chans)[0]
        self._active_channel = active
        # 활성 탭 선택(핸들러 억제) 후 직접 apply
        for i in range(tb.count()):
            if tb.tabData(i) == active:
                self._switching_channel = True
                tb.setCurrentIndex(i)
                self._switching_channel = False
                break
        self._apply_config(chans[active], load_refs=True)
