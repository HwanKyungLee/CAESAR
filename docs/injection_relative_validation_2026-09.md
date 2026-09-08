# 2026-08-11 NO2 인젝션 상대 채널 검증

## 목적

이 검증은 절대농도 표준을 확정하는 T3가 아니다. 2026-08-11 재라벨 원시자료에서
현재 CAESAR 피팅 엔진이 두 핫 채널의 상대 반응을 재현하는지 확인하는 진단이다.
원시자료는 수정하지 않았고, `데이터 생성용/003.dat`에서 production
`AlphaExportWorker`를 통해 알파를 생성했다.

## 입력과 조건

- CH1 = ANs, ROI 429.527–461.890 nm, 58개 60초 평균 행
- CH2 = PNs, ROI 444.146–470.685 nm, 58개 60초 평균 행
- 실제 ROI별 파장보정과 hot reference를 사용한 진단 FitSet
- signed gas coefficients 허용
- zero-base 후보: 기존 poly 차수, shift limit ANs `[-10, 0.5]`, PNs `[-5, 5]`
- squeeze limit: `0.98–1.02`
- 각 행마다 2개 controlled start, 총 채널당 116회

## 결과

- ANs: 116회 완료, 경계 접촉 2회
- PNs: 116회 완료, 경계 접촉 0회
- seed 간 최대 농도 차이: ANs 약 0.0042, PNs 약 `1e-5`
- 전체 58행 origin 회귀: `PNs / ANs = 0.81666`, `r = 0.999918`
- 15 ppb 이상 구간의 구간별 기울기: 약 `0.815–0.819`
- 0–5 ppb 구간 기울기: 약 `0.71`; 저농도에서는 절편·잡음 영향으로 별도 취급해야 한다.

## 판정

이 자료는 기존 독립 기록의 상대계수 `0.815–0.82`를 재현한다. 따라서 두 핫 채널의
상대 gain/consistency anchor로는 유효하다. 그러나 실험 단계의 안정화·혼합·plateau
조건이 절대 표준으로 충분히 입증된 것은 아니므로 절대농도 T3 또는 최종 보정값으로
사용하지 않는다. 최적화기는 이 결과를 “상대 consistency 통과”로만 기록하고,
절대 anchor는 별도 상태로 유지해야 한다.

재현 도구: `tools/generate_alpha_headless.py`, `tools/run_full_alpha_profile.py`.
두 도구 모두 자동 Apply를 수행하지 않는다.
