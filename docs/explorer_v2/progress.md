# 진행 기록

2026-09-10 / 확인 baseline: codex/fit-explorer-phase-a @ 73086f5.

| 카드 | 상태 | 근거 |
|---|---|---|
| 문서 패키지 | 완료 | README, contracts, work_cards, 이 기록 |
| 1 평가 계약 | 완료 | legacy T2 보존, anchor-independent retrieval_integrity 추가 |
| 2 mission→plan | 완료 | FitSet-free mission 검증 및 유한 candidate plan |
| 3 다종 비교 | 미착수 | 기존 반복 피팅·ablation 재사용 예정 |
| 4 graph/closure | 미착수 | 기존 문서상의 분석과 범용 구현을 구분 |
| 5 holdout/export | 미착수 | 기존 Review verdict는 사람 입력 |
| 6 GUI 인수 | 미착수 | 기존 탭은 batch 실행 및 Review 표시 가능 |

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
