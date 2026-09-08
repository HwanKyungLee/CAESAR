# Yeosu hot Explorer 결과 (2026-09)

## PNs

동일한 4일 Stage 2 표본에서 squeeze `0.995–1.005` 후보를 비교했다.

- `shift [-1,1]`: 22/24 경계 접촉 → 관측된 실패 경계
- `shift [-10,0.5]`, `[-3.5,1.5]`, `[-5,5]`: 각각 2/24 경계 접촉,
  seed 안정 및 농도 분포 일치
- 대표 비교 후보 `shift [-3.5,1.5]`의 Stage 2 중앙값: 1.6503 ppb
- 독립 holdout (`2026-06-10`~`06-13`) 중앙값: 1.6449 ppb
- holdout 경계 접촉: 0/24, seed 최대 차이: 약 `1.3e-7 ppb`

PNs는 같은 mission 안에서 재현되는 내부 consistency 성분과 holdout 안정성을 보인다.
그러나 독립 절대량 anchor가 없으므로 외부 농도 진실이나 최종 FitSet으로 승격하지 않는다.
판정은 `MISSION_LOCAL_ONLY`다.

## ANs

현재 Stage 2에서 경계 없는 후보는 `shift [-10,0.5]`, squeeze `0.995–1.005` 하나뿐이다.
단일 후보는 plateau가 아니므로 대표 설정이나 holdout 판정을 내리지 않는다.
판정은 `NON_IDENTIFIABLE_OR_ABSTAIN`이다.

## 공통

자동 Apply는 수행하지 않았다. 이 결과는 Yeosu mission-local evidence이며, Araon/Seosan에
그대로 이식되는 설정값이 아니다. Explorer의 범용성은 같은 입력·Stage 1/2·closure·보류 계약이
다른 mission에서도 작동하는 데 있다.
