# Araon closure 결과 (2026-09)

## 실행한 closure 순서

중앙 창·poly 4에서 sparse Stage 2 후보의 누락 shift 정책을 Stage 1로 추가 평가했다.
모든 실행은 같은 4개 대표행과 controlled start 2개를 사용했다.

1. squeeze `0.9999–1.0001`: 8개 shift 정책 모두 경계 접촉
2. squeeze `0.9995–1.0005`: 8개 shift 정책 모두 경계 접촉
3. squeeze `0.995–1.005`: 대부분 경계 접촉; shift `[-5,5]`만 3/8로 감소
4. squeeze `0.98–1.02`, shift `[-5,5]`: 경계 접촉 0/8

## 결정적 관찰

가장 넓은 후보는 경계에는 닿지 않았지만, 같은 scan의 두 controlled start가 일부 행에서
서로 다른 shift/squeeze/NO2 해로 수렴했다. 예를 들어 한 행에서 `shift=-2.478`,
`squeeze=0.988952`, `NO2=0.049`와 `shift=1.938`, `squeeze=1.008581`,
`NO2=-0.240`가 동시에 나왔다. 이는 seed stability가 성립하지 않는다는 뜻이다.

## 최종 판정

Araon 2025 blue의 이 창·reference·후보 도메인은 현재 입력으로 robustness plateau를 만들지
못했다. 따라서 이 미션의 현재 판정은 `NON_IDENTIFIABLE_OR_ABSTAIN`이다.

이 판정은 데이터나 후보를 삭제/배제하지 않는다. 다음 재시도 조건은 독립 absolute anchor를
추가하거나, wavecal/reference/창 자체를 별도 설계 단계에서 재검토하는 것이다. 현재 후보를
Stage 2 또는 대표 FitSet으로 승격하지 않으며 자동 Apply는 하지 않는다.
