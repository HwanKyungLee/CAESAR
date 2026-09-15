"""tools/test_app_window_smoke.py
CAESARAnalyzer(6400줄 god object) 분해용 앵커 테스트.

GUI 테스트가 0인 상태에서 app_window.py를 쪼개는 건 저장소에서 제일 위험한 변경이다.
쪼갤 때 실제로 나는 사고는 두 가지뿐이고, 이 파일이 그 둘을 잡는다.

  1. **메서드/위젯 유실** — 옮기다 한 개 빠뜨림. 호출부는 self.foo() 뿐이라
     임포트 스모크도 통과하고, 그 버튼을 누르는 순간에야 AttributeError로 터진다.
     -> 분해 직전(main @ 0025020)의 표면을 통째로 얼려놓고 subset 검사.
  2. **믹스인 이름 충돌** — 두 믹스인이 같은 메서드를 정의하면 MRO에서 하나가
     조용히 이긴다. 이름은 그대로 있으니 1번 검사로는 안 잡힌다.
     -> gui/ 안의 클래스들 중 같은 이름을 정의한 게 2개 이상이면 실패.

추가는 통과시키고 유실만 잡는다(subset). 의도적으로 메서드를 지웠다면 아래 목록에서도
지워라 — 그게 "이건 정말 없애는 게 맞나"를 한 번 더 보게 만드는 유일한 지점이다.
"""
import ast
import builtins
import glob
import importlib
import os
import symtable
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 분해 전 표면 (main @ 0025020에서 생성) ────────────────────────────────
CLASS_ATTRS = """
    _AUDIT_STYLE _WV_CAL_BASE _active_workers _add_channel_tab _alpha_channel_groups
    _alpha_file_meta _alpha_head_label _alpha_on_progress _alpha_qc_after_export
    _alpha_qc_pick_folder _alpha_qc_run _alpha_qc_scan_folder _alpha_qc_zoom_fit _alpha_status
    _apply_auto_qc _apply_config _apply_row_to_table _apply_test_fit_recommendations
    _auto_apply_nm _auto_detect_channels _autosave_close _autosave_retire _autosave_row
    _autosave_start _build_alpha_channel_configs _build_engine_from_config _build_run_meta
    _calibration_state _campaign _capture_config _channel_data_groups _channel_settings_tag
    _channel_wave_cal _channel_wl_path _compact_table_columns _compute_1scan_preview
    _current_fit_px_window _day_audit_worst _del_channel_tab _distribute_channels _dlg_dir
    _entry_display_name _entry_filepath _entry_from_display_name _entry_row_index _fast_finalize
    _fit_nm_for_channel _fit_px_for_channel _fit_unit_for_channel _flush_fast
    _fwhm_auto_find_latest_alpha _fwhm_load_alpha _fwhm_mean_alpha_from_file
    _fwhm_mean_alpha_from_folder _fwhm_parse_fwhm_from_name _fwhm_pick_alpha_file
    _fwhm_pick_alpha_folder _fwhm_pick_sweep_folder _fwhm_run_validation _fwhm_set_active_ref
    _input_layout _load_channel_scenario _load_files _load_folder _load_wavecal_array
    _mark_refs_dirty _on_alpha_channel_done _on_channel_tab_changed _on_day_audit_done
    _on_day_audit_failed _on_ils_dirty _on_main_tab_changed _on_r_curve_update
    _on_scan_count_ready _on_setup_rt_point_clicked _on_shsq_table_changed _open_test_fit_dialog
    _parse_flags _pick_dates _pipeline_health_checks _pipeline_qc_pick_r_npz _progress_text
    _qc_state _raw_days _read_drnam_std_t _reapply_kalman _reapply_ok_rms_status
    _refresh_after_qc _refresh_setup_status _refresh_shsq_summary _render_day_audit
    _render_fast_results _results_date_range _row_index_from_display_name _run_runids
    _set_channel_range_from_selector _setup_shortcuts _show_channel_files _show_setup_r_spectrum
    _show_setup_r_spectrum_from_result _shsq_text _start_day_audit _start_next_alpha_export
    _time_shift_hours _toggle_shsq_table _update_daily_r_chart _update_daily_rt_chart
    _update_file_table _update_fwhm_px_from_nm _update_setup_rt_charts _write_row_cells
    add_ref_row analysis_finished apply_convolution apply_new_wavelength apply_roi_from_graph
    auto_extract_i0 batch_load_refs browse_alpha_save_dir browse_dark_file browse_i0_file
    browse_offset_file browse_r_file closeEvent del_ref export_alpha_files
    get_auto_scale_exponent guess_gas_name init_ui load_data load_scenario load_wavelength_cal
    lock_ref on_table_double_click on_table_single_click open_alpha_generator open_mask_dialog
    open_peak_trend open_r_trend_monitor open_ref_properties open_reference_generator
    open_selector open_wavelength_calibration reapply_qc refresh_viewer save save_scenario
    set_i0_from_table set_i0_path set_range_from_nm setup_cavity_tab setup_daily_run_tab
    showEvent show_table_context_menu start_analysis stop_analysis update_diagnostic_plot
    update_leff update_range update_table
""".split()

INSTANCE_ATTRS = """
    _active_channel _adv_params_container _adv_params_visible _aqc_folder _aqc_pw _aqc_r_npz
    _btn_adv_params _btn_aqc_fitwin _btn_aqc_full _btn_aqc_run _btn_lock_ref _btn_shsq_tbl
    _btn_toggle_cavity _btn_toggle_det _btn_toggle_override _btn_toggle_params _cavity_container
    _cavity_visible _channel_configs _channel_files _channel_tabbar _det_corr_container
    _det_corr_visible _detected_channels _diag_tabs _ed_campaign _ed_ch_datalabel
    _fwhm_alpha_file_path _fwhm_alpha_folder _fwhm_ax _fwhm_best_ref_path _fwhm_canvas _fwhm_fig
    _fwhm_last_scores _fwhm_sweep_folder _ils_applied _ils_container _left_col _left_inner
    _left_scroll _manual_override_container _manual_override_visible _params_container
    _params_visible _qsettings _refs_dirty _s _setup_leff_pw _setup_left_container
    _setup_r_trend_pw _setup_rt_readout _shsq_table_visible _splitter _splitter_inited
    _switching_channel _tab_aqc _tab_fwhm _tab_pages b_run b_save b_stop btn_apply_ils
    btn_day_audit btn_fwhm_run btn_fwhm_set_active btn_reapply_qc calib_squeeze cb_display_mode
    cb_fit_unit chk_allow_neg chk_aqc_auto chk_auto_save chk_qc chk_robust chk_settle
    chk_temporal_i0 daily_run_tab engine file_list lbl_aqc_dir lbl_aqc_readout lbl_aqc_rnpz
    lbl_channel_info lbl_dark_path lbl_fwhm_alpha lbl_fwhm_alpha_dir lbl_fwhm_best
    lbl_fwhm_display lbl_fwhm_folder lbl_i0_path lbl_leff lbl_offset_path lbl_r_path lbl_shsq
    lbl_st_audit lbl_st_i0 lbl_st_r lbl_st_range lbl_st_refs lbl_st_wl lbl_wavecal main_tabs
    monitor p1 p2 pbar plot_diagnostic plot_maker rb_fwhm_alpha_engine rb_fwhm_alpha_file
    rb_fwhm_alpha_folder ref_in ref_lay ref_props ref_widgets result_viewer results scroll
    setup_tab spin_d_len spin_dark_scale spin_fit_end_nm spin_fit_start_nm spin_fwhm
    spin_fwhm_lorentzian spin_fwhm_nm spin_gas_temp spin_kalman_q spin_kalman_r spin_lambda
    spin_offset_scale spin_poly_deg spin_pres spin_qc_k spin_qc_rms spin_qc_snr spin_rl_factor
    spin_rms_thresh spin_settle_n spin_step_limit spin_stray_light spin_temp spin_time_shift
    spin_update status table tbl_shsq txt_flag_amb txt_flag_he txt_flag_za txt_max txt_min
""".split()

MAIN_TABS = ['Setup', 'Analysis Monitor', 'Result Lab', 'Plot Maker']


def _unresolved_globals(path):
    """모듈 안에서 전역으로 찾는 이름 중 어디에도 안 묶인 것.

    분해하다 임포트를 빠뜨리거나 별칭을 흘리면(실제로 났다: core.paths의
    campaign_dir as _campaign_dir가 별칭 없이 옮겨갔다) 임포트는 멀쩡히 되고
    그 메서드를 부르는 순간에만 NameError가 난다. 표면 골든으로는 절대 안 잡힌다.
    symtable로 함수 스코프마다 '전역 조회' 이름을 뽑아 모듈 전역과 대조한다.
    메서드 안 지역 임포트는 지역 심볼이라 자동으로 제외된다.
    """
    src = open(path, encoding="utf-8").read()
    bound = {sym.get_name() for sym in symtable.symtable(src, path, "exec").get_symbols()}
    for node in ast.walk(ast.parse(src)):        # star 임포트가 있으면 그쪽 이름도 인정
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            mod = importlib.import_module("gui." + (node.module or ""))
            bound |= set(dir(mod))

    bad = []

    def walk(tbl, scope):
        for sym in tbl.get_symbols():
            name = sym.get_name()
            if (sym.is_global() and not sym.is_assigned()
                    and name not in bound and not hasattr(builtins, name)
                    and not name.startswith("__")):
                bad.append(f"{scope}: {name}")
        for child in tbl.get_children():
            walk(child, f"{scope}.{child.get_name()}")

    for child in symtable.symtable(src, path, "exec").get_children():
        walk(child, child.get_name())
    return bad


def main():
    from PyQt6.QtWidgets import QApplication
    from gui.app_window import CAESARAnalyzer

    app = QApplication.instance() or QApplication([])
    win = CAESARAnalyzer()          # __init__ -> init_ui(): 창 전체가 여기서 만들어진다
    win.show()
    app.processEvents()

    # 1. 창이 실제로 뜬다 (임포트만이 아니라 위젯 트리 구성까지)
    n_widgets = len(win.findChildren(object))
    assert n_widgets > 500, f"위젯 {n_widgets}개 — init_ui가 중간에 죽었다"
    assert [win.main_tabs.tabText(i) for i in range(win.main_tabs.count())] == MAIN_TABS

    # 2. 메서드 유실 — MRO 전체에서 찾는다(믹스인으로 옮겨가도 통과해야 하니까)
    missing = [n for n in CLASS_ATTRS if not hasattr(CAESARAnalyzer, n)]
    assert not missing, f"메서드/클래스속성 {len(missing)}개 유실: {missing}"

    # 3. 위젯 유실 — init_ui가 만들던 인스턴스 속성
    missing = [n for n in INSTANCE_ATTRS if not hasattr(win, n)]
    assert not missing, f"인스턴스 속성 {len(missing)}개 유실: {missing}"

    # 4. 믹스인 충돌 — gui/ 소속 클래스 중 같은 이름을 정의한 게 2개 이상이면 실패
    dupes = {}
    for name in CLASS_ATTRS:
        owners = [k.__name__ for k in CAESARAnalyzer.__mro__
                  if getattr(k, "__module__", "").startswith("gui.") and name in vars(k)]
        if len(owners) > 1:
            dupes[name] = owners
    assert not dupes, f"믹스인 이름 충돌 — MRO에서 하나가 조용히 진다: {dupes}"

    # 5. 임포트 유실/별칭 유실 — 메서드를 안 돌려도 정적으로 잡힌다
    unresolved = {}
    for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__),
                                              "..", "gui", "app_window*.py"))):
        bad = _unresolved_globals(path)
        if bad:
            unresolved[os.path.basename(path)] = bad
    assert not unresolved, f"전역에서 못 찾는 이름 (임포트 유실): {unresolved}"

    win.close()
    print(f"OK  widgets={n_widgets}  class_attrs={len(CLASS_ATTRS)}  "
          f"inst_attrs={len(INSTANCE_ATTRS)}  mro={len(CAESARAnalyzer.__mro__)}")
    print("PASS")


if __name__ == "__main__":
    main()
