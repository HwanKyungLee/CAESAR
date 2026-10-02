# Augur 수정 계획 (2026-10-02, 점검 보고서 README.md 기반)

원칙
- 결함마다 **재현 테스트를 먼저** 만들고(가능하면 `tools/test_*.py` 또는 해당 모듈 옆 `test_*.py` — `tests/test_script_suite.py`가 자동 수집), 그다음 고친다.
- 커밋은 수정 단위로 로컬에만 한다. push는 사용자 확인 후.
- 매 커밋 전 `pytest`, `python tools/validate_pipeline.py --no-data`, `python tools/ci_import_smoke.py`(+ Plot Maker면 `tools/validate_plotmaker.py`).
- 핏 수치를 바꾸는 수정은 별도 커밋으로 하고, 05-20 하루치 전후 비교 결과를 커밋 메시지에 적는다.
- 데이터 무결성 헌장: 지우지 말고 flag. 단일 출처: raw_parser / physics / result_io.

작업 분담 (파일이 겹치지 않게 — 병렬 워크트리)

| 묶음 | 파일 | 담당 |
|---|---|---|
| W1 알파·R 파이프라인 | gui/worker.py(AlphaExportWorker 부분), tools/rt_precompute.py, gui/ui_alpha_gen.py, gui/app_window_inputs.py, gui/ui_dialogs_r.py, gui/r_workers.py | 에이전트 |
| W2 Result Lab | gui/ui_result_viewer.py, gui/result_viewer_io.py, gui/dlg_calculator.py, core/result_io.py(헤더 함수만) | 에이전트 |
| W3 Plot Maker | gui/ui_plot_maker/*, gui/dlg_date_load.py | 에이전트 |
| W4 Monitor·완료처리 | gui/monitor_widget.py, gui/app_window_results.py | 에이전트 |
| W5 Setup 코어 | gui/app_window.py, app_window_run.py, app_window_save.py, app_window_channels.py, app_window_fitsetup.py, app_window_dataload.py, app_window_cavity.py, core/health_checks.py, gui/test_fit_dialog.py, gui/ref_mask_dialog.py, gui/ui_dialogs_calib.py, gui/reference_generator_dialog.py, gui/worker.py(AnalysisWorker 부분) | 코디네이터 |

worker.py는 W1(AlphaExportWorker, ~2000행 이후)과 W5(AnalysisWorker, ~1–1400행)가 다른 영역만 건드린다.

## 1단계 — 치명·운영 영향 (작은 수정)

| ID | 결함 | 묶음 |
|---|---|---|
| F1 | `_block_average` 빈 입력 5→6개 반환, "He 없음 핫 raw" 회귀 테스트 | W1 |
| F2 | 알파 생성 실패를 "complete"로 표시 → 실패 상태 표시 / 예외 시 스풀 정리 | W1 |
| F3 | R npz 로드 실패 시 덮어쓰기 → 예외로 중단 + 원자 저장(tmp+os.replace) + .bak | W1 |
| F4 | 알파 폴백 roi 매핑 반대(app_window_inputs.py:234) → 채널 정체 단일 출처 | W1 |
| F5 | Browse I₀/Set as I0가 raw(Mega-Matrix)를 1D로 받음 → 형식 판별 후 거부 | W1 |
| F6 | Result Lab 점 클릭 무동작(`isAccepted`) / `_sibling_alpha`가 자기 자신 반환 / x 자동범위 미복구 | W2 |
| F7 | Plot Maker Batch 파일명 충돌 / CSV 보간·외삽 날조 / 주석 시각 파서 → `_parse_x` 재사용 | W3 |
| F8 | Monitor `autoRangeEnabled()[0]` / 5,000행 cap 안내 덮임 / 병렬 실패를 "successfully"로 | W4 |
| F9 | RUN 재진입 가드 + RUN 동안 입력 잠금("frozen"을 참으로) | W5 |
| F10 | wavecal 밖 핏 범위 → None(전체범위) 폴백 제거, RUN 전 거부 | W5 |
| F11 | 레퍼런스 0개 채널 RUN 거부, lock_ref 실패 시 이전 엔진 보존 | W5 |
| F12 | `health_checks.overall` SKIP만이면 PASS 금지 | W5 |
| F13 | dataload.py:317 철회된 채널 문구 | W5 |
| F14 | Test Fit Apply를 추천 채널에만 | W5 |
| F15 | Mask: 범위 검증(px 범위·역순·남는 픽셀) + 기본값 비움 + 결과 붕괴 시 Success 금지 | W5 |
| F16 | 버튼 `&` → `&&` | W5 |

## 2단계 — 패턴 수정

| ID | 패턴 | 내용 | 묶음 |
|---|---|---|---|
| P1 | B 기록 | 결과 헤더·meta를 `_run_frozen['configs'][ch]`에서 채널별로 생성, `_qc_state`에서 핏 파라미터 제거, 알파 입력이면 무효 물리값 대신 알파 헤더 값, `_qc_orig*` repr 열 제거 | W5 |
| P2 | D 상태 | 단일 채널도 config로 빌드한 독립 엔진 사용(탭 전환 경합 제거) | W5 |
| P3 | B 기록 | Result Lab Export·Merge·Calculator에 provenance(git 해시·K·구간·시프트·입력경로), Export QC를 화면과 같은 `qc_hidden_mask`로, BOM CSV | W2 |
| P4 | A 성공조건 | Status 색은 `quality_label` 머리말 기준, Reapply "Excluded" 정정 | W4 |
| P5 | C 시간대 | 시간축 라벨에 (UTC), Night 음영 tz 경고, `time_KST` 열 이름 보정 | W2/W3/W4 |
| P6 | E 채널 | Pipeline mean α를 label별 파장 보간 평균 | W5 |
| P7 | 물리 안전 | Cavity·Override 스핀 휠 무시, wavecal Apply를 `load_wavelength_cal` 하나로 | W5 |

## 3단계 — UX
- CH3 탭이 숨는 문제, 1366 화면 레이아웃, "Parameters" 중복 제목, 빈 상태 안내, 툴팁, Fast 모드 탭 이름. 범위가 넓어 1·2단계 뒤에.

## 진행 기록
(커밋 해시와 전후 비교를 여기에 덧붙인다)

- 2026-10-02 — 워크트리 `.claude/worktrees/fix-w{1..5}-*`, 브랜치 `fix/w1-alpha-r`, `fix/w2-resultlab`,
  `fix/w3-plotmaker`, `fix/w4-monitor`, `fix/w5-setup` (모두 dcfb50b 기준). pytest 는 .venv 에 없어 시스템 python 으로.
- 1차(사용량 한도로 중단 전): W1 F1 abbe97f, F2 4a4e675, F3 14e6987 / W2 F6a 6cdd75f, F6b 0f23843, F6c 28a68d2 /
  W3 R1 97bc176, R2 b1edd3b / W4 R1 d656a73, R8 02b1497 / W5 F12 0dc4be3, F13 e999be1, F16 7aa7b7a, F9 5433b10, F10 a016930.
- Vigil: 재생기 완료(SCRATCH\vigil\replayer). 점검 V2(경보) 재개, V1(유입)·V3(대시보드)는 대기.
- 완료: W1(5커밋, F1–F5) · W4(9커밋) · W2(11커밋) · W5(F9–F16, P1, Esc/Ctrl+S, 13커밋).
- 통합 브랜치 `fix/integration`(워크트리 `.claude/worktrees/fix-integration`): W1·W4·W5·W2 병합 + status_msg 배선.
  pytest 전부 통과, validate_pipeline 2/2, import smoke 311 OK, validate_plotmaker 통과.
  **실데이터(05-20 3채널) 전후 비교: NO2·H2O·CHOCHO·RMS·Chi2 최대 차이 0.0, 6개 파일 행 수·열 동일** —
  이번 수정은 핏 숫자를 바꾸지 않는다(기록·안내·가드만). 헤더는 채널별(CH1 Poly4/599-1270, CH2 Poly3/899-1450, CH3 Poly4/774-1550), runid 불변.
- P2(단일 채널 런 중 엔진 바꿔치기)는 F9 입력 잠금(채널 탭·fitset Load·Lock 비활성)으로 경로가 막혀 별도 수정 불필요.
- 남은 것: W3(진행 중), W5 잔여(replay poly 이중가산 R5·findData R6, lock_ref 실패 시 엔진 보존, Pipeline mean α 채널별, 휠 무시, wavecal Apply 일원화),
  `core/refit.read_alpha_row` 위치 기반(W2 후속), `_qc_orig` repr 직렬화(원본 복원 불가 — 헌장 ①), Versions 에 _archive 포함, Mask 의 FitSet 저장, 3단계 UX.
- 2026-10-03 — 잔여 4건: `_qc_orig*` repr → `{gas}_preQC`·`Status_preQC` 열(7c85ab8), replay poly 이중가산 R5(38599ba),
  Mask 를 FitSet·config·meta·헤더에 + "Remove mask"(44b135d), Versions 에 `_archive` + meta 짝 유지(78ecbcc).
  핏 숫자 불변(마스크 없는 FitSet). 남은 것: 3단계 UX, Vigil VF3 ②③④⑥⑧·VF4 나머지.
- 2026-10-03 (2) — 3단계 UX + 디자인 다듬기(91ea998 테마, aab7803 Augur, 4eadb6f Vigil): 1366×768 @150 % 에서
  메인 창 최소폭 1027→665 px, Setup 좁으면 위아래 쌓기, 큰 대화상자 화면 안으로, 왼쪽 1~4 단계 + ✓, 상태 기호,
  빈 상태 안내, RUN 주 버튼, Monitor "(Fast)" 제거. 화면은 실제 창(빈 상태·05-20 데이터·Fast 런)으로 찍어 확인.
  남은 것: 결과 표 Status 열 노트 잘림, Plot Maker 툴팁 없는 버튼(Compute·+ Left Y 등)·↺ 라벨, 정책표 열 잘림.
