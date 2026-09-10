# 진행 기록

2026-09-10 / 확인 baseline: codex/fit-explorer-phase-a @ 73086f5.

| 카드 | 상태 | 근거 |
|---|---|---|
| 문서 패키지 | 완료 | README, contracts, work_cards, 이 기록 |
| 1 평가 계약 | 완료 | legacy T2 보존, anchor-independent retrieval_integrity 추가 |
| 2 mission→plan | 완료 | FitSet-free mission 검증 및 유한 candidate plan |
| 3 다종 비교 | 완료 | 전체 coeff 재사용·동일 observation/start 종별 delta |
| 4 graph/closure | 완료 | 명시 edge graph·finite closure·대표 후보 진단 |
| 5 holdout/export | 완료 | frozen evidence 추천 상태·명시 export/worker roundtrip |
| 6 GUI 인수 | 완료 (bridge) | V2 mission→plan·recommendation/export + V1 batch 실행/재개 |

2026-09-10 / 카드 1 / `core/fit_explorer.py`, batch CLI/schema 및 계약 테스트 /
`retrieval_integrity`가 계획한 모든 시도의 완료, target 공선성, 유한 계수를 별도로
판정한다. 외부 절대량·T/P provenance는 이 내부 판정의 필수조건이 아니며 legacy
`t2_gate`는 변경하지 않았다. `test_fit_explorer.py`, `test_fit_explorer_batch.py`,
`test_zero_base_candidates.py`, `validate_pipeline.py --no-data` 통과. / 다음: 카드 2.

2026-09-10 / 카드 2 / `core/fit_explorer_v2.py`, `tools/test_fit_explorer_v2.py` /
명시한 mission 파장축·reference·관측 identity·유한 search policy만으로 FitSet-free
후보 계획을 만든다. 후보 identity는 input hash, 파장 좌표, ordered reference content,
window/poly/registration 정책을 포함하며, candidate runtime spec은 worker 적용 전의
순수 구성 정보다. 미상 단위·ILS 상태·좌표/holdout overlap·누락 driver는 거부한다.
graph edge와 과학적 sensitivity criterion은 아직 선언하지 않아 각각 Card 4 및 Astra
검토 전 `UNSET`이다. / 다음: 카드 3.

2026-09-10 / 카드 3 / `core/fit_explorer_v2.py`, `tools/test_fit_explorer_v2_multispecies.py` /
한 candidate fit attempt의 전체 `coeffs`에서 요청한 모든 종의 완료분모·계수 누락·seed별
값을 수집하고, candidate 간에는 동일 `scan_id`/`start_id`인 행만 pair하여 delta를 계산한다.
날짜별 실제 농도 변화는 비교 대상이 아니다. sensitivity/detection 기준이 없으므로 결과는
`COMPUTED` 또는 `UNAVAILABLE` 진단이며 PASS/FAIL 또는 residual 순위를 만들지 않는다.
실제 V2 execution adapter와 graph edge는 다음 카드 범위다. / 다음: 카드 4.

2026-09-10 / 카드 4 / `core/fit_explorer_v2.py`, `tools/test_fit_explorer_v2_graph.py` /
명시된 candidate edge와 upstream 종별 edge state만으로 PASS 연결성분을 계산한다. unknown은
실패가 아니라 예산 안 closure 요청이며 선언 영역 밖으로 후보를 만들지 않는다. 대표 후보는
경계 hop이 큰 내부점 중 낮은 poly/작은 창을 동률 해소에만 사용한다. component는 대표와
전체 pair 증거를 모두 요구하므로 A-B/B-C 통과만으로 A-C 불일치를 숨기지 않는다. 그래프
자체는 추천을 내리지 않으며 holdout·export는 Card 5 범위다. / 다음: 카드 5.

2026-09-10 / 카드 5 / `core/fit_explorer_v2.py`, `tools/test_fit_explorer_v2_recommendation.py` /
동결 plan의 closed internal component와 명시 assessment/독립 holdout으로만 V2 상태를
산출한다. external validation은 기록하지만 상태를 자동 승격하지 않는다. holdout 부재는
`PROVISIONAL`, multi-solution 또는 내부/종별 실패는 `ABSTAIN`이다. export는 추천된 후보를
기존 FitSet config의 복사본에 번역하고 실제 worker bounds parser/validate_fitset을 되읽은
뒤 새 파일에만 exclusive write한다. 활성 GUI/원본 config는 바꾸지 않는다. / 다음: 카드 6.

2026-09-10 / 카드 6 / `gui/test_fit_dialog.py`, `tools/run_fit_explorer_v2.py`, GUI/CLI 계약 테스트 /
Test Fit Explorer 탭에서 V2 mission JSON→frozen plan 생성/재사용, plan/recommendation 표시,
추천 후보의 명시 FitSet export를 제공한다. 기존 batch config의 validate/run/resume 경로는 그대로
실제 반복 fit을 수행한다. V2 mission은 현재 input identity/hash만 보관하므로 V2 plan 자체를
실제 alpha/reference 파일에서 실행하는 runtime adapter는 아직 없다; 이를 V2 실행이라고 표시하지
않는다. `ci_import_smoke.py`는 기존 QDOAS 진단의 고정 `/root/.claude/uploads/...ASC` 경로 때문에
1 FAIL(160 OK/31 SKIP)이고, V2/GUI/Explorer 관련 검사는 통과했다. / 후속: mission runtime adapter.

## 재사용 가능한 자산

- 실제 VARPRO controlled starts, 정규화, solver/boundary 진단.
- Stage 1/2 표본, 배치 hash 재개, 불변 evidence, reference 구조/ablation, GUI batch 실행.
- 로컬 diagnostics/yeosu_reprovenanced_alpha_2026-09: 두 채널 alpha 및 Stage 1/2 실행 기록.
  이는 네 raw 파일 부분집합으로 재생성한 alpha다. 운영 전체 alpha와 I0가 동등하다고 보장하지 않는다.
  이 네 날짜는 반복 검토했으므로 새로운 독립 holdout으로 사용하지 않는다.
- 현재 PNs 세 bounds 후보의 일치는 창/poly/reference 전반의 plateau 증명이 아니다.

## 구현 전 확인할 제한

- 종별 민감도 기준의 과학적 근거와 신규 독립 holdout은 아직 확정되지 않았다.
  카드 1~3 계약 구현은 가능하다. 해당 값이 없는 상태에서 최종 추천을 만들지 않는다.
- 과거 import smoke는 untracked QDOAS 진단의 누락 외부 파일 때문에 실패한 적이 있다.
  다음 코드 작업에서 실제 baseline을 다시 확인한다.
- README.md, core/engine.py, parallel_shift_bench 파일, Augur 소개 문서 및 여러 untracked
  diagnostics는 기존 사용자 변경이다. 일괄 add/clean/reset하지 않는다.

업데이트 형식: 날짜 / 카드 / 변경 파일 / 검사·결과 / 남은 한계 / 커밋 / 다음 카드.
