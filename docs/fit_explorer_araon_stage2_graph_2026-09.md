# Araon Stage 2 후보 인접 그래프 (2026-09)

## 그래프 규칙

이번 단계에서는 결과값으로 후보를 묶지 않는다. Stage 2 manifest에 선언된 후보 순서를
파라미터 lattice로 사용하고, squeeze 정책이 같은 후보 사이에서 shift 정책이 한 단계
바뀌는 경우만 edge로 연결한다. 이 순서는 자동 추정값이 아니라 실행 manifest의 명시적
candidate order다.

## 노드와 edge

모든 노드는 동일한 squeeze limit `0.9999–1.0001`을 공유한다.

```text
zb_bd63c27c61fc2fda  (shift = -5 fixed)
          |
zb_392ebc09d6272202  (shift = -2 fixed)
          |
zb_8d910bd9d05ea6fa  (shift = 0 fixed)
          |
zb_8a275e59f548fef8  (shift = -5..5 limit)
```

연결 성분은 1개이며, 노드 4개와 edge 3개다. 이 결과는 **그래프 연결성만** 말한다.
아직 plateau라고 선언하지 않는다.

## 현재 그래프 상태

- 후보 실행: 모두 Stage 2 COMPLETE
- 내부 consistency: 모두 PASS
- 절대 T2: 모두 `UNAVAILABLE` (독립 농도 anchor 없음)
- unknown frontier: 후보 lattice 바깥의 확장 후보는 아직 평가하지 않음
- closure: 미실행

따라서 현재 연결 성분은 `INTERNAL_CONSISTENCY_COMPONENT`로만 기록한다. 다음 단계에서
이 연결 성분의 one-step 이웃을 평가해 closure를 수행해야 하며, 그 전에는 대표 후보나
`RECOMMENDABLE_INTERNAL`을 선택하지 않는다.
