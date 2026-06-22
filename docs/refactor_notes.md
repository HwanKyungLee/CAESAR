# 리팩토링 / 개선 노트

코드를 파일별로 읽으며 발견한 **모듈 분리 지점**과 **개선 후보**를 누적 기록한다.
지금 당장 분리하지 않고(테스트 부재로 위험), 나중에 안전하게 쪼개기 좋게 미리 표시해 둔다.

규칙(2026-06-20 합의):
- **주석·docstring = 한글 유지** (코드 읽을 때 설명은 한글)
- **모든 문자열 리터럴 = 영어** (UI + print/로그/예외 전부)
- **예외(언어 무관 그대로 둠)**: 다른 코드가 파싱하는 토큰 — 파일 헤더 키
  (`# wavelength_nm:`, `row_idx` 등), dict/QSettings 키(`"alpha_gen_raw"` 등),
  가스명, 정규식·glob 패턴, 경로. 번역하면 I/O가 깨짐.
- **`박사님`/특정 인물·랩 지칭은 UI 문자열에선 기능으로 설명** (예: "Dr. Nam format" →
  "Per-bin format"). 외부 사용자가 봐도 이해되게. 한글 주석엔 `박사님` 그대로 둬도 됨.
- **이모지(🧪📂💾📈) 유지** — 가독성. 더 나은 이모지로 개선은 OK.
- 톤 = 간결한 명령형 ("Select raw files first.")
- **UI 폴리시(저위험만 적용)**: 라벨/버튼 문구 일관성, 간격·정렬, 툴팁 명료화,
  이모지 일관성. **큰 레이아웃 재배치는 직접 안 하고 여기 '제안'으로 기록** 후 확인받기.
- 모듈 분리는 보수적으로(저위험만), 분리 지점은 여기 기록
- 진행 방식 = 작은~중간 파일 묶음 처리, 큰 파일(ui_result_viewer/ui_dialogs_r/
  ui_dialogs_ref/app_window)은 개별 신중히.

---

## 분리 지점 (split candidates)

### gui/app_window.py (4973줄, 최대 모놀리식 — CAESARAnalyzer 단일 QMainWindow ~150 메서드)
**기능별 메서드 군집 → Mixin 분리 후보**(단일 거대 클래스라 별도파일 클래스분리는 불가,
Mixin 상속이 현실적). 각 Mixin은 self.* 위젯 공유 가정. 중위험(런타임 호출 헤드리스 미검증).
- **AlphaExportMixin**: export_alpha_files, _start_next_alpha_export, open_alpha_generator,
  _alpha_*, _build_alpha_channel_configs, _on_alpha_channel_done (~알파 생성 묶음)
- **RCalibMixin**: open_r_*, open_r_trend_monitor, _update_daily_rt_chart,
  _update_setup_rt_charts, _on_setup_rt_point_clicked, _show_setup_r_spectrum
- **AnalysisMixin**: start_analysis, stop_analysis, closeEvent, _active_workers, _fast_*,
  update_table, _write_row_cells, analysis_finished, save
- **QcMixin**: reapply_qc, _apply_auto_qc, _refresh_after_qc, _reapply_*
- **RefWavecalMixin**: open_ref_properties, batch_load_refs, add_ref_row, load_wavelength_cal,
  apply_new_wavelength, _channel_wave_cal
- **SetupTabsMixin**: setup_daily_run_tab, setup_cavity_tab, _fwhm_* (셋업탭 구성)
- 권장: Mixin 1개씩 빼고 매번 GUI 기동(메서드 내부 호출은 import-time 미검증).
  먼저 결합도 낮은 SetupTabsMixin/QcMixin부터. (이번 세션은 번역만)

---

## 분리 지점 — gui/ui_result_viewer.py (1441줄, ResultViewerWidget 단일)
- UI(_init_ui)는 이미 영어·잘 정리됨(툴바 Open|View/Analyze/Export 그룹). 폴리시 불필요.
- 저위험 분리 후보(나중): ①정적 파서들(`_load_result_time_gas`,`_read_numeric`,
  `_detect_sep`,`_load_fit_table`,`_detect`)을 `result_viewer_io.py`로 → 순수함수라 안전.
  ②플롯 메서드군(`_plot_r_trend/_r_curve/_alpha_trace/_reference/_concentration/_array/
  _fit/_diurnal`)을 Mixin으로. 단 self._pw_top/_bot 공유라 Mixin 형태여야.
- 지금은 분리 안 함(테스트 부재). 위 ①이 가장 안전한 첫 후보.

## ★분리 계획 — gui/ui_dialogs_ref.py (2433줄, 4개 독립 클래스)
**4개 클래스가 서로 참조 안 함(독립) → 클래스별 파일 분리 안전성 높음.** 가장 가치 큰 정리.
- MaskDialog (50~156, ~107줄) — 소형 config 다이얼로그
- RefPropertiesDialog (157~327, ~170줄) — Shift/Squeeze bounds
- ReferenceGeneratorDialog (328~1135, ~807줄) — HITRAN·ILS·FWHM (scipy/matplotlib 무거움)
- **MonitorWidget (1137~2433, ~1300줄)** — 라이브 플롯(fit/trend/viewer/R/conc 탭). ★최대 분리이득
- import 경로: `app_window → gui.ui_dialogs(import *) → ui_dialogs_ref`. app_window가
  MonitorWidget·Ref*·Mask 직접 사용(669·2360·2369·2824). 분리시 ui_dialogs_ref.py에
  `from .xxx import YYY` 재노출 추가하면 `import *` 무회귀.
- **위험**: 메서드 내부 scipy/pg/plt 호출은 import-time에 안 잡힘 → 헤드리스 import만으론
  부족, **GUI 실행 테스트 필요**. 각 새 파일에 상단 import 블록 복제 정확히 해야.
- **권장 순서**: ① MonitorWidget(이득 최대) → ② ReferenceGeneratorDialog → ③ 소형 2개.
  각 단계 후 GUI 기동 확인. (이번 세션은 번역만, 분리는 사용자 확인 후 별도 실행)

## ✅ 분리 완료 — gui/r_workers.py (2026-06-20, 1단계)
- `_LiveStream` + 워커 5종(_RTrendWorker·_RTExportWorker·_RTAppendWorker·_ChannelRWorker·
  _HeCheckWorker) → **gui/r_workers.py** 로 이동(원본 바이트 그대로 복사).
- `_CH_COLORS`(팔레트)는 dialog만 사용 → ui_dialogs_r 잔류.
- ui_dialogs_r 상단에 `from gui.r_workers import (...)` 재노출 → `ui_dialogs.py`의
  `from .ui_dialogs_r import _RTrendWorker, _ChannelRWorker`·RCalibratorDialog 내부참조 무회귀.
- 검증: 양쪽 compile OK + import 체인(r_workers→ui_dialogs_r→ui_dialogs) + 재노출 동일성 통과.
  워커는 모듈레벨 무거운 import 0(전부 run() lazy)이라 헤드리스로 거의 완전 검증됨.
- ⚠️ 잔여 GUI 확인(권장): R Calibrator 열기 → 채널 로드 → 계산 시작/α R(t) 저장 1회.

## 개선 후보 (improvements)

### gui/ui_alpha_gen.py
- (사소·해결) `QCheckBox(f"Generate")` 불필요 f-string → 제거함.
- 구조 양호: 371줄 자체 완결 다이얼로그. 분리 불필요(이미 독립 모듈).
- `_ch_rt`는 `_refresh_tab_rows`에서 초기화되는데 `_generate`는 `getattr(self,'_ch_rt',{})`로
  방어적 접근 — raw 로드 전 생성 누르면 빈 dict. 현재 동작상 무해(파일 가드가 먼저 막음).

---

## 진행 현황 (파일별)

| 파일 | UI 영문화 | 개선검토 | 분리노트 |
|------|:--:|:--:|:--:|
| gui/ui_alpha_gen.py | ✅ | ✅ | 분리불필요(독립) |
| gui/ui_peak_trend.py | ✅ | ✅ | 분리불필요(독립, 252줄) |
| core/* (data_io·doas_fit·engine·raw_parser 등) | — (한글=docstring/주석뿐) | — | — |
| core/result_io.py | ✅ (예외·헤더문자열) | ✅ | OK |
| core/session_log.py·main.py | ✅ (로그문자열) | — | — |
| gui/worker.py | ✅ (status/로그 26개) | 검토完 | ★분리후보 아래 |
| gui/dr_nam_alpha_worker.py | ✅ (3개) | ✅ | OK |
| gui/ui_dialogs_calib.py | ✅ (2개) | 대기(전체검토 미完) | 대기 |
| gui/app_window.py | ✅ 149→0 | ✅ | ★Mixin 6종 분리계획 기록 |
| gui/ui_dialogs_r.py | ✅ 124→0 | ✅ | 분리후보(워커5종→r_workers) |
| gui/ui_dialogs_ref.py | ✅ 39→0 | ✅ | ★분리계획 기록(4클래스→4파일) |
| gui/ui_result_viewer.py | ✅ 38→0 | ✅ (UI 이미 정리됨) | 노트기록(파서 추출 후보) |
| tools/* (8개 파일) | ✅ (CLI/print 65개) | ✅ | — |

**★ 번역 단계 완료(2026-06-20): 전 프로젝트 한글 UI/로그/문자열 → 영어, 주석·docstring 한글 유지.**
유일 예외 = r_results_plotter.py:16 BASE_DIR(한글 폴더명 실제 경로, 유지). r_trend_monitor
콘솔 박스 2줄은 영어화하며 정렬도 62칸으로 교정. 다음 = 분리 단계(클래스 단위 + GUI 테스트).
