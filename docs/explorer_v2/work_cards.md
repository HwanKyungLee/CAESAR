# 테라 실행 카드

한 번에 카드 하나 또는 명시적으로 지정한 묶음만 수행한다. 이전 대화 전체를 다시 분석하지 않는다.
공통 선행: git status, 적용 AGENTS.md, README/contracts/progress, 해당 카드의 코드만 읽는다.
각 카드 완료 후 변경·검증·남은 한계·커밋을 progress에 기록한다. 미완료를 완료로 표시하지 않는다.

## 1. V2 평가 계약과 legacy 경계

범위: core/fit_explorer.py의 t2_tri_state, t2_from_attempts, t2_diagnostic_checks,
tools/run_fit_explorer_batch.py의 execute_candidate, core/fit_explorer_batch.py의 공개 schema.
기존 tri-state를 없애지 않고 별도 v2 checks adapter를 구현한다. 외부/이론량 검사 부재가
공선성·solver 증거까지 막지 않도록 한다. 계획 시도 수 기준 완전성을 적용한다.
추천·graph·기존 evidence 수정은 범위 밖이다.

검증: anchor 없는 정상 입력의 내부 checks 수행, T/P fallback의 의존 검사 차단,
실패 시도 누락 시 완전성 통과 금지. producer→public validator 통합 payload를 함께 검사한다.

## 2. 수동 FitSet 없는 mission→plan

재사용: core/data_io.py, tools/optimize_params.py의 build_engine_from_config,
core/fit_explorer.py의 reference_observability, validate_coordinates, zero_base_policy_candidates,
translate_zero_base_policy. 기존 generator는 cfg와 target 기본값에 의존하므로 그대로 범용이라 부르지 않는다.
범위: mission loader, 단위/축/ILS 검사, runtime cfg 생성, 유한 후보·edge·budget·split 직렬화.
관심종과 driver를 분리하고 임의 종명을 지원한다. legacy FitSet 없이 실행 가능하게 한다.
policy 파일에 근거가 없는 종별 민감도는 미설정 상태로 보존한다.

검증: synthetic Species_A/Species_B와 불투명 채널 ID에서 실행, 미상 단위/좌표 불일치 거부,
같은 입력의 같은 candidate identity, 입력 hash 변경 시 새 identity, holdout 중복 탐지.
아스트라 체크포인트: 기본 탐색 정책·분할·과학적 기준 근거를 검토한다.

## 3. 다종 후보 평가와 동일 행 비교

재사용: production_stage1_callback, run_stage1_vertical_slice, run_stage2_vertical_slice,
tools/run_zero_base_stage1.py의 load_selected_scans/reuse_stage2_samples,
core/reference_ablation.py, tools/fit_profile.py. 모델 전체 fit에서 종별 결과를 수집한다.
종마다 동일 fit을 불필요하게 중복하지 않는다. driver/정합 정책이 달라질 때만 별도 후보다.
범위: 종별 seed 재현성, 동일 행 candidate delta, 기준 없는 COMPUTED, 실패 분모 보존,
공통 평가 파장/noise가 없는 잔차 비교 제한. 기존 batch의 hash 재개·불변 저장을 재사용한다.

검증: 실제 날짜 농도 변화가 안정성 FAIL을 만들지 않음, 같은 행 모델 민감성 검출,
저신호 종과 다중 해 구분, 미등록 종이나 누락 coeff를 조용히 건너뛰지 않음.

## 4. 유한 graph/closure와 대표 후보

현재 범용 구현이 없으므로 새 최소 evaluator로 추가한다. stdlib graph 순회로 충분하다.
입력은 plan의 명시 edge와 카드 3의 비교 증거다. evaluated/pruned/unknown을 구분하고
예산 안에서 frontier 평가를 요청한다. 선언 범위 밖으로 자동 확대하지 않는다.
대표 대비 성분 전체 차이 검사와 복잡도 우선 동률 해소를 구현한다.
holdout 미완료 결과는 PROVISIONAL이다. RMSE 단일 점수와 legacy T2 필수 PASS를 도입하지 않는다.

검증: A-B와 B-C만 일치하고 A-C가 불일치하는 chain, unknown frontier, budget 소진,
범주형 edge, 고립 노드, 다종 상충을 합성 증거로 확인한다.
아스트라 체크포인트: graph가 지원하지 않는 과학적 주장을 하지 않는지 검토한다.

## 5. 동결 후보 holdout·추천 JSON·FitSet export

재사용: 기존 sample manifest, batch executor, atomic_write_json. tools/fit_explorer_review.py는
사람 verdict 입력 도구이므로 자동 추천 계산기로 착각하지 않는다. v2 경로를 별도 연결한다.
범위: holdout 사용 이력 검증, 계약의 status 산출, 종별 제한/대안, 새 FitSet 저장·worker roundtrip.
외부 validation은 독립 필드로 표시한다. GUI active config는 바꾸지 않는다.

검증: anchor 없이 내부+holdout 통과 시 추천, holdout 부족 시 잠정, 다중 해 시 보류,
holdout 재사용을 독립으로 표시하지 않음, export 충돌/정책 누락 거부.

## 6. GUI 및 운영 인수

범위: gui/test_fit_dialog.py의 Explorer 탭에 mission 입력·plan 미리보기·예산·실행/재개·
결과·새 FitSet export를 연결한다. 기존 batch CLI 실행 경로를 재사용한다.
이전 review JSON은 기존 의미로 읽는다. 구현 세부 schema 편집을 사용자 필수 작업으로 만들지 않는다.
현재 window/reference 구조만 확인 가능한 경우 알려진 미션 전체에 추천됐다고 표시하지 않는다.

검증: GUI 또는 headless GUI 계약으로 입력부터 export까지 실행; 미션/종 이름 변경 확인;
실제 여러 미션에서는 추천 성공만 요구하지 않고 판정 근거의 타당성을 확인한다.
아스트라 최종 검토: 사용자 흐름·추천 의미·미션 의존 코드·미해결 실패를 확인한다.

## 검증 비용과 커밋

문서 변경은 링크·diff 확인만 한다. 코드 변경은 관련 회귀와 producer→consumer 검사를 실행한다.
주요 체크포인트에서 tools/validate_pipeline.py --no-data, tools/ci_import_smoke.py를 실행한다.
기존 실패라고 단정하지 말고 시작 baseline과 비교한다. 새로운 실패·미검증 변경을 완료로 commit/push하지 않는다.
사용자 변경은 stage하지 않는다. Git 게시 요청이 유효한 실행에서는 검증된 파일만 명시 stage하고
origin 변경을 확인한 뒤 codex/fit-explorer-phase-a에 push한다. 강제 push 금지.

## 다음 모델에 전달할 짧은 프롬프트

docs/explorer_v2/README.md, contracts.md, progress.md를 읽고 work_cards.md의 다음 미완료 카드 하나를
구현하라. 적용 AGENTS.md와 사용자 변경을 보존하라. 과학적 기준을 발명하지 말고 계약을 구현하라.
관련 검증 후 progress에 결과와 다음 작업을 기록하라. 광범위한 데이터 재실행은 카드가 요구할 때만 하라.
