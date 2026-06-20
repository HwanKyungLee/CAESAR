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

### gui/app_window.py (4973줄, 최대 모놀리식)
- _(읽으며 채울 예정)_ 기능별 후보: 알파 생성 / R 캘리브 / 핏 실행·QC / 결과뷰어 연동 / 셋업탭
  각 블록의 메서드 군집을 mixin 또는 별도 모듈로 뺄 수 있는지 표시.

---

## 분리 지점 — gui/ui_result_viewer.py (1441줄, ResultViewerWidget 단일)
- UI(_init_ui)는 이미 영어·잘 정리됨(툴바 Open|View/Analyze/Export 그룹). 폴리시 불필요.
- 저위험 분리 후보(나중): ①정적 파서들(`_load_result_time_gas`,`_read_numeric`,
  `_detect_sep`,`_load_fit_table`,`_detect`)을 `result_viewer_io.py`로 → 순수함수라 안전.
  ②플롯 메서드군(`_plot_r_trend/_r_curve/_alpha_trace/_reference/_concentration/_array/
  _fit/_diurnal`)을 Mixin으로. 단 self._pw_top/_bot 공유라 Mixin 형태여야.
- 지금은 분리 안 함(테스트 부재). 위 ①이 가장 안전한 첫 후보.

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
| **gui/app_window.py** | ⏳ 141 | ⏳ | ★최대 분리대상 |
| **gui/ui_dialogs_r.py** | ⏳ 112 | ⏳ | ⏳ |
| **gui/ui_dialogs_ref.py** | ⏳ 37 | ⏳ | ⏳ |
| gui/ui_result_viewer.py | ✅ 38→0 | ✅ (UI 이미 정리됨) | 노트기록(파서 추출 후보) |
| tools/* (r_trend_monitor·alpha_wide_to_perbin 등) | ⏳ (CLI문자열 ~60) | ⏳ | 별도 배치 |
