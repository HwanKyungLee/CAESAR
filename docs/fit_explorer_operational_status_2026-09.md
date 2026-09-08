# Fit Explorer 운영 검증 상태 (2026-09)

## 현재 판정

이번 묶음은 후보를 자동 적용하거나 최종 FitSet을 확정하는 단계가 아니다. 각 미션의
입력 계약, 다일 표본, solver 경계 진단을 확인해 다음 단계의 자격을 판정한다.

### Yeosu / Suncheon

기존 4일 프로파일(`2026-05-26`, `05-30`, `06-04`, `06-09`)을 같은 조건으로 비교했다.

- ANs: 첫 3일은 내부 수렴, `06-09`는 squeeze 하한 접촉
- PNs: 네 날짜 모두 경계 접촉 없음
- cold: 네 날짜 중 세 날짜에서 shift 경계 접촉

따라서 핫 채널은 상대적으로 `MISSION_LOCAL_ONLY` 후보 평가를 계속할 수 있지만,
cold는 현재 범위에서 `NON_IDENTIFIABLE_OR_ABSTAIN` 성격으로 보류한다. 이는 cold를
영구 제외한다는 뜻이 아니라, 해당 범위에서 shift를 식별하지 못했다는 뜻이다.

### Araon / 2025 blue

4개 날짜에 대해 12행 Stage 2 manifest가 성립한다. 후보 4개가 동일 계약으로 실행되며,
현재 보고서의 절대 T2는 독립 농도 anchor 부재로 `UNAVAILABLE`이다. 따라서 결과는
solver·날짜 안정성 진단으로만 사용하고 외부 농도 진실이나 T3로 승격하지 않는다.

### Seosan / 2020 winter

MAT alpha와 raw housekeeping의 시간 매칭 및 Stage 0 입력 검증까지 완료됐다. 다일
Stage 2에 필요한 날짜별 alpha 패킷과 명시적 후보 FitSet을 추가 확인해야 하므로 현재는
`UNAVAILABLE`이다.

## 이번 단계의 의미

현재 Explorer는 여러 미션에서 같은 입력·샘플링·signed-gas·경계 진단 계약을 실행할 수
있다. 그러나 `RECOMMENDABLE_INTERNAL`을 선언하려면 아직 후보 간 파라미터 이웃 그래프,
closure, 독립 holdout 날짜 평가가 필요하다. 따라서 현재 최종 상태는 다음과 같다.

| 미션 | 상태 | 다음 조건 |
|---|---|---|
| Yeosu 핫 | `MISSION_LOCAL_ONLY` 후보 | 후보 격자 Stage 2 + plateau graph |
| Yeosu cold | `NON_IDENTIFIABLE_OR_ABSTAIN` (현 범위) | 더 넓은 shift/squeeze 또는 새 데이터 |
| Araon | Stage 2 실행 가능, T2 absolute `UNAVAILABLE` | 후보 비교 + holdout |
| Seosan | 입력/Stage 0 완료 | 다일 alpha 패킷 확정 |

자동 Apply는 모든 상태에서 금지한다.
