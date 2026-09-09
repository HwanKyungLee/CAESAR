# V2 데이터 및 판정 계약

이 문서의 필드는 신규 제안 계약이다. 현재 구현된 API로 간주하지 않는다.
기존 v1 report를 제자리에서 수정하거나 v2로 자동 승격하지 않는다.

## 입력: explorer-mission-v2

| 필드 | 계약 |
|---|---|
| schema | explorer-mission-v2 |
| mission_id | 표시용 불투명 ID |
| channels | 비어 있지 않은 채널 목록 |
| channel_id | 불투명 ID; 물리 채널 매핑 provenance 별도 |
| alpha_inputs | 파일 identity/hash, 픽셀 대응, 시간·T/P 값과 출처 |
| wavelength | 파일/hash, 단위, 픽셀 대응 |
| references | ordered 목록; species_id, 파일/hash, 단위·scale, wavelength/pixel 대응, ILS 처리 상태 |
| requested_species | 생략하면 등록된 전체 종; 중복·미등록 종 거부 |
| legacy_fitset | 선택적 비교 입력; 후보 생성의 필수 의존성 금지 |
| instrument_metadata | 있을 때 파장 정확도·분해능·유효 검출영역 등 탐색 근거 |

숫자만 있는 reference는 대응 축·단위가 확인돼야 사용한다. ILS 적용을 추측하거나 이중 적용하지 않는다.
모르는 단위는 임의 ppb로 표시하지 않는다. 관심종과 registration driver는 별도 필드로 전달한다.
관심종은 내보낼 농도 목적이고 driver는 정합 변수의 기준이다. 둘을 기존 target 인자 하나에 섞지 않는다.

## 탐색 계획: explorer-plan-v2

- input_hash, policy_version, domain, candidates, edges, split, budget, criteria, assumptions.
- domain은 유한 축 값·원본 coverage·변환 규약·비교 edge를 포함한다.
- candidate identity는 실제 창, poly, ordered reference hash/scale, wavecal, 정합 정책을 포함한다.
  기존 후보 ID는 legacy_id로 보존하고 완전한 identity와 혼용하지 않는다.
- split은 discovery / validation / holdout의 파일·행·시간블록 identity와 사용 이력을 기록한다.
  같은 물리 관측의 alias, 시간상 겹침을 검사한다. 적절한 독립 블록이 부족하면 잠정 후보까지만 가능하다.
- budget은 최대 fit 시도 수와 closure 한도를 명시한다. 한도 소진은 실패가 아닌 미평가다.
- criteria는 수치 재현성, 종별 설정 민감도, 잔차 구조, 허용 실패율을 각각 값·단위·근거로 저장한다.

첫 버전은 검증된 명시 탐색 정책을 사용한다. shift/squeeze 범위를 데이터에서 무제한 확대하지 않는다.
추가 범위가 필요하면 새 plan 버전이며 기존 holdout 사용 이력을 계승한다.

## 평가 상태

각 check: applicability(APPLICABLE/NOT_APPLICABLE/UNKNOWN), state(PASS/FAIL/UNAVAILABLE/COMPUTED),
reason, required_for, evidence_refs, criterion_ref를 기록한다.

- NOT_APPLICABLE은 PASS가 아니다. required_for에 지정된 산출물만 해당 검사 누락으로 제한한다.
- 입력 오류는 관련 실행을 차단한다. T/P 누락은 그것을 요구하는 산출물·검사에만 영향을 준다.
- boundary hit는 진단이다. 단독으로 물리 FAIL이 되지 않는다. 활성 변수의 반복 경계 수렴은
  정합이 제한됐다는 사유로 추천을 보류한다. 의도적 Fix는 boundary failure가 아니다.
- 모든 계획 시도의 identity·성공·실패를 분모에 포함한다. 성공한 행만으로 완전성 PASS를 만들지 않는다.
- 실제 종별 이론 제약과 외부 장비/인젝션 검증은 서로 다른 항목이며 적용 범위를 명시한다.
- 외부 자료는 독립 여부와 검증하는 양(상대 반응/절대량)을 기록한다. 같은 자료로 튜닝했다면 독립 검증이 아니다.

## 허용오차와 비교

같은 관측행, 같은 종, 같은 단위에서 후보 간 차이를 계산한다. 다른 날짜의 실제 농도 차이를 벌점으로 쓰지 않는다.
종별 비교는 절대/상대 허용오차를 함께 지원하되 0 근처를 상대오차로만 판정하지 않는다.
반복 측정·noise 자료 등 근거가 없으면 값을 계산해 COMPUTED로 보고하고 잠정 상태로 제한한다.
기존 seed 기준 0.1 ppb/5%, 0.01 px, 1e-5 등을 전체 종·모델 변경 비교의 기본값으로 복사하지 않는다.
서로 다른 창의 raw RMS는 직접 순위화하지 않는다. 공통 평가 파장 또는 검증된 noise 정규화가 필요하다.
graph edge별 차이와 대표 후보 대비 전체 성분 차이를 모두 저장한다. reference 제외 실험은 종별 누락흡수
진단과 함께 다루며, 약한 흡수종의 농도가 안정적으로 0이라는 이유만으로 정량 가능 판정을 내리지 않는다.

## 출력: explorer-recommendation-v2

필수 필드: schema, plan_hash, input_hash, code_provenance, status, scope, species_results,
candidate_refs, checks, frontier, holdout, external_validation, reasons, exportable_candidate_ids.

| status | 조건 |
|---|---|
| MISSION_RECOMMENDED | 요구된 입력·수치·종별 민감도 검사, 선언 영역 closure, 독립 holdout 통과 |
| PROVISIONAL | 실행 가능한 후보가 있으나 기준 근거·표본·holdout·frontier가 부족 |
| ABSTAIN | 요구 관심종/산출물에 적합한 후보가 없거나 입력·식별 실패 |

scope는 항상 해당 입력·미션·평가한 장비상태·탐색축에 한정한다. 종별 상태를 별도로 표시한다.
일부 관심종만 추천 가능한 경우 전체 요청 충족이라고 표시하지 않고 부분 결과와 대안을 제공한다.
외부 검증 없음은 MISSION_RECOMMENDED를 차단하지 않는다. 외부 검증 있음도 자동 승격 사유가 아니다.
legacy 판정 문자열은 legacy 뷰에서만 표시한다. 사람 입력 verdict와 알고리즘 판정을 섞지 않는다.
추천/잠정 후보는 사용자가 새 FitSet으로 내보낼 수 있다. 실제 worker parser로 되읽어 의미를 검증하고
파일 충돌 시 덮어쓰지 않는다. 현재 GUI의 활성 FitSet 변경은 이 흐름에 포함하지 않는다.
