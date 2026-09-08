# Araon Stage 2 후보 인접 그래프 (2026-09)

## 그래프 규칙

이번 단계에서는 결과값으로 후보를 묶지 않는다. 그러나 Stage 2 manifest의 네 후보는
전체 zero-base 도메인의 후보 순서가 아니라, 의도적으로 골라 실행한 sparse subset이다.
전체 도메인은 창 3 × poly 3 × shift 정책 8 × squeeze 정책 5 = 360개다.

## 노드와 edge

모든 실행 노드는 동일한 중앙 창, poly 4, squeeze limit `0.9999–1.0001`을 공유한다.

```text
shift = -5 fixed       evaluated
shift = -2 fixed       evaluated
shift = -0.5 fixed     UNEVALUATED  ← one-step frontier
shift = 0 fixed        evaluated
shift = -1..1 limit    UNEVALUATED  ← policy frontier
shift = -5..5 limit    evaluated
```

따라서 네 실행 후보만으로 one-step edge나 연결 성분을 확정할 수 없다. 창 이동, poly
변경, squeeze 폭 변경 축에도 같은 unknown frontier가 있다.

## 현재 그래프 상태

- 후보 실행: 모두 Stage 2 COMPLETE
- 내부 consistency: 모두 PASS
- 절대 T2: 모두 `UNAVAILABLE` (독립 농도 anchor 없음)
- unknown frontier: 도메인 내부의 one-step 후보가 다수 미평가
- closure: `ABSTAIN_UNKNOWN_FRONTIER`

따라서 현재는 연결 성분 자체를 선언하지 않는다. 다음 closure는 전체 360개를 무차별
실행하는 것이 아니라, 후보 선언 시 grid step과 축 순서를 manifest에 고정한 뒤 현재
후보들의 실제 one-step 이웃만 Stage 1로 재평가해야 한다. 그 전에는 대표 후보나
`RECOMMENDABLE_INTERNAL`을 선택하지 않는다.
