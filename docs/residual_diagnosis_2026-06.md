# 잔차 진단 메모 (2026-06)

콜드/핫 채널의 핏 잔차(~17–20% of signal)가 데이터 문제인지 소프트웨어 문제인지 추적한 결과.
진단 도구: `tools/residual_compare.py`(3채널 비교+구조지표), `tools/poly_sweep.py`(다항식 차수 스윕),
`tools/etalon_test.py`(etalon freq_min 스윕). 표본: 채널당 18스캔, 캠페인 전체.

## 배제 추적 (원인 후보 제거)

1. ❌ 랜덤 노이즈(데이터 한계) — autocorr1≠0, PCA 단일모드 지배 → 구조적.
2. ❌ 미모델링 흡수체(O4/H2O) — 정식 ILS 단면(`Output/wv_cal/{cold,roi1,roi2}/Ref_*_Dynamic-ILS-Applied.dat`)
   넣어도 잔존.
3. ❌ NO2 ILS/파장 부정합 — 정식 단면으로 흡수선형 잔차 소멸(1차 진단은 raw 단면 사용 탓 허상이었음).
4. ❌ 채널별 웨이브캘 격자 불일치 — Hot은 알파 헤더 ≠ 레퍼런스 Calib(PNs ~0.6px). 실재하나 핏 shift(±2px)가
   흡수 → 잔차 불변. 원인에서 제외.

## 채널별 남은 구조와 처방

| 채널 | 잔차 성격 | fixed/random | 처방 |
|---|---|---|---|
| Hot-PNs | 거의 깨끗 | 0.3 | 없음 |
| Hot-ANs | ~78px fringe | 3.1 | etalon_freq_min ↓ (아래, **보류**) |
| Cold | 복잡한 고정 광대역 구조(단일 사인 아님) | 30 | 후보정 / 고정패턴 기저 |

### Hot-ANs: etalon_freq_min 낮추기 — 보류(메모만)
시나리오 ch3(ANs)의 `etalon_freq_min`을 0.02 → ~0.012로 낮추면 ~78px fringe가 잡혀
NO2 83→56ppb, 잔차 autocorr 0.84→0.63으로 개선. **단 효과가 크지 않아 지금은 적용하지 않고 메모만 남김.**
적용 시 과적합/실신호 잠식 여부 검증 필요.

### Cold: etalon 불가 → 후보정이 현실적
etalon freq_min을 0.005까지 낮춰도 autocorr1=1.00 불변 → 콜드 구조는 단일 주파수 fringe가 아니라
복잡한 광대역 모양이라 etalon 항으로 못 잡음. 이 매끄러운 고정 구조가 NO2의 넓은 성분과 겹쳐
**NO2 베이스라인에 누설 → 콜드 NO2가 핫보다 높게 찍힘**(다항식 차수에 NO2가 극민감한 것이 그 증거).
- 현실적 해법: 콜드 NO2 경험적 후보정(오프셋/베이스라인).
- 모델 차원 해법(욕심내면): 평균 잔차를 고정패턴 기저(`custom_basis`)로 추가, NO2와 직교화 필수.
