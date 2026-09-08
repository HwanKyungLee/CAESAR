# Stage 2 후보 결과 인벤토리 (Araon 2025 blue)

## 수집 규칙

동일 후보의 재실행 checkpoint는 하나의 논리 후보로 deduplicate하고, 12행 × 2 seed의
정식 Stage 2 보고서(총 24 attempts)를 기준으로 집계한다. Stage 1의 8 attempts와
중간/불완전 checkpoint는 이 인벤토리에서 제외한다.

공통 표본은 `2025-06-10`부터 `2025-06-13`까지 4개 날짜에서 날짜당 3행이다.

## 후보별 결과

| 후보 | 정책 요약 | 상태 | 경계 접촉 | 내부 T2 | 절대 T2 |
|---|---|---|---:|---|---|
| `zb_bd63c27c61fc2fda` | shift 고정 -5, squeeze 0.9999–1.0001 | COMPLETE | 21/24 | PASS | UNAVAILABLE |
| `zb_392ebc09d6272202` | shift 고정 -2, squeeze 0.9999–1.0001 | COMPLETE | 21/24 | PASS | UNAVAILABLE |
| `zb_8d910bd9d05ea6fa` | shift 고정 0, squeeze 0.9999–1.0001 | COMPLETE | 20/24 | PASS | UNAVAILABLE |
| `zb_8a275e59f548fef8` | shift -5–5, squeeze 0.9999–1.0001 | COMPLETE | 24/24 | PASS | UNAVAILABLE |

공선성 진단의 target multiple-R은 모든 후보에서 약 `0.0574`로 기준 `0.7`보다 낮았다.
따라서 현재 자료에서 후보를 탈락시킬 근거는 경계 접촉이지 T2 절대량이 아니다.

## 1단계 판정

후보별 Stage 2 결과 수집은 완료했다. 다음 단계에서는 네 후보를 정책 좌표로 정렬해
인접 그래프를 만들되, `T2=UNAVAILABLE`을 `PASS`로 바꾸지 않고 “내부 consistency
그래프”와 “절대 anchor 그래프”를 분리해서 기록해야 한다.
