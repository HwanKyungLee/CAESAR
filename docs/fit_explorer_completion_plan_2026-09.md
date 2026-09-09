# Fit Setting Explorer 완료 계획 (2026-09)

> 2026-09-10: 이 계획은 역사 기록이다. 신규 작업은 [V2 실행 카드](explorer_v2/work_cards.md)와
> [진행 기록](explorer_v2/progress.md)을 따른다. 특히 외부 anchor 부재를 내부 추천의 필수 차단 조건으로 사용하지 않는다.

## 목표와 완료 기준

목표는 한 개의 “정답 FitSet”을 자동 적용하는 것이 아니다. 여러 실제 피팅을 실행해 물리적으로
허용되는 안정 영역을 찾고, 가장 단순한 내부 후보를 **추천 또는 보류**하는 도구를 완성한다.
자동 Apply와 원자료 삭제는 범위 밖이다.

최종 산출물은 각 미션마다 다음 중 하나를 재현 가능하게 보고해야 한다.

- `RECOMMENDABLE_INTERNAL`: T2 통과 후보들로 연결된 plateau가 있고 독립 날짜에서도 유지됨
- `MISSION_LOCAL_ONLY`: 같은 미션에서만 내부 일관성이 있으며 일반 추천 근거가 부족함
- `NON_IDENTIFIABLE_OR_ABSTAIN`: 데이터가 shift/squeeze 또는 target을 식별하지 못함

T3가 없으면 어떤 결과도 외부 농도 진실이라고 부르지 않는다.

## 단계 1 — 입력·미션 패킷 고정

**대상:** 여수, 아라온, 서산.

- alpha 행, 파장축, 채널/target 메타데이터, reference, FitSet/후보 정책을 hash와 함께 고정한다.
- 서산은 MATLAB alpha의 `std_t`와 같은 시각의 raw `doy`를 매칭해 T/P를 복원한다.
- DOASIS `.fs`는 비교 provenance로 보존한다. CAESAR가 읽을 수 없는 필드는 추측해 재현하지 않고
  `PROVISIONAL_BASELINE`로 기록한다.

**완료 조건:** 각 미션에서 최소 두 채널의 alpha+T/P+파장+reference가 CAESAR loader/Stage 0을
통과한다. 불완전한 입력은 명확한 `UNAVAILABLE` 사유를 남긴다.

## 단계 2 — 실제 Stage 1/2 증거 배치

- 후보는 zero-base grid에서 생성하며 기존 수동 FitSet은 비교 후보 하나일 뿐 정답이 아니다.
- Stage 1은 대표 4행×controlled start 2개로 명백한 실패만 제거한다.
- Stage 2는 날짜에 걸친 12–24행과 고정 sample manifest를 사용한다.
- raw T/P가 없는 패킷은 절대량 anchor/T3 판정을 `UNAVAILABLE`로만 보고한다.

**완료 조건:** 여수·아라온·서산 각각에 원자적 batch report와 재실행 가능한 manifest가 생성된다.

## 단계 3 — successive halving과 plateau 판정

- Stage 1에서 `FAIL`만 prune하고, 나머지는 Stage 2로 보존한다.
- T2 통과 후보 사이에서만 파라미터 이웃 그래프를 만들고 closure(누락 이웃 재평가)를 수행한다.
- plateau는 출력값 클러스터가 아니라 파라미터 공간 연결성, 날짜 재표본화, 경계거리로 판정한다.
- 대표 후보는 가장 단순하고 경계에서 먼 내부점으로 고른다.

**완료 조건:** 후보별 `pruned/rerun_required/eligible`, plateau 구성요소, 대표/보류 사유가 보고서에 있다.

## 단계 4 — 독립성·일반화 평가

- 같은 미션의 독립 날짜 블록을 holdout으로 사용한다.
- 미션 간에는 채널명·경로·target 종 하드코딩 없이 같은 실행 계약이 작동하는지만 확인한다.
- NO2 인젝션 등 검증된 T3가 생긴 경우에만 최종 순위를 외부 진실로 평가한다.

**완료 조건:** 각 추천이 `RECOMMENDABLE_INTERNAL`, `MISSION_LOCAL_ONLY`, `NON_IDENTIFIABLE_OR_ABSTAIN`
중 하나로 귀결하며 근거가 provenance에 연결된다.

## 단계 5 — 사람 승인 UX와 인수인계

- GUI/CLI는 후보, plateau, boundary hit, T2/T3 상태, 보류 사유만 표시한다.
- 사용자가 명시적으로 승인할 때만 FitSet을 적용한다.
- 최종 사용법·입력 요구사항·한계와 외부 재실행 방법을 문서화한다.

**완료 조건:** 새 미션에서 `alpha + wavecal + references + target metadata`만 제공하면 단계 1부터
실행할 수 있고, 추천을 자동 적용하지 않는다.

## 현재 우선순위

1. 단계 1의 서산 raw T/P 매칭과 Stage 0 패킷 검증을 끝낸다.
2. 단계 2에서 여수·아라온·서산의 작은 실제 배치를 동일 보고 형식으로 만든다.
3. 그 결과가 충분할 때만 단계 3 코드(halving/graph)를 추가한다.

이 순서는 새 탐색 알고리즘을 먼저 늘리는 대신, 실제 서로 다른 미션 입력이 같은 계약을 만족하는지
먼저 확인하기 위한 것이다.
