# Claude Science 쪽 근거 파일 (2026-09-20 반입)

1단계 결과 문서가 UNVERIFIED 로 남긴 항(R(t) 3.30 %, 에탈론 진폭 4.90 %, ILS)의
원자료다. 저장소 밖(Claude Science 아티팩트)에 있어서 재현 경로가 없었던 것이므로
여기로 옮긴다. **전부 합성 스펙트럼 기반이며 운영 자료가 아니다.**

| 파일 | 무엇 | 주의 |
|---|---|---|
| `rt_sensitivity_table.csv` | R(t) 보간 민감도 4 케이스. case (d) 의 `no2_rel=-0.0330` 이 "R(t) 3.30 %" 의 출처 | **⚠ 무효 — 아래 §무효 사유** |
| `augur_Rt_sensitivity_memo.md` | 위의 서술판 | 〃 |
| `varpro_synth_results.csv` | 합성 검정 70행. `g3b_unmodeled_etalon` 이 "에탈론 4.90 %", `g3a_ils_mismatch` 가 ILS 항의 출처 | 무잡음. 분모가 항마다 다름 |
| `varpro_synthetic_validation_report.md` | 위의 서술판(부록 C 초안) | |
| `test_varpro_synthetic_ext.py` | 29 PASS 게이트. 위 수치를 재생성하는 스크립트 | **`tools/` 로 옮겼다**(2026-09-20) — 여기 두면 저장소 루트 탐색이 어긋나 CI 가 깨진다 |
| `varpro_synth_g4_landscape.csv` | Hot/PNs 창 프로파일 목적함수 241점 | T6 기준값 |
| `cold_shift_landscape.csv` | Cold 창 12 스펙트럼 × 241점 | T6 기준값 |
| `augur_Cold_shift_identifiability_memo.md` | Cold shift 비식별성 전문 | |

## ⚠ 무효 사유 — R(t) 3.30 % 는 운영 R 파일로 계산되지 않았다

`rt_sensitivity_table.csv` 는 `R_PNs.npz` / `R_ANs.npz` 를 썼다. 두 파일은
**knot 3개, 전체 구간 0.1일(2.4시간)** 짜리이고, leave-one-out 이 예측한 간격은
**2.75 h** 였다. 운영 R 파일은 다르다:

| 파일 | knots | 구간 | gap p50 | p95 | p99 | max | >2h | >4h |
|---|---|---|---|---|---|---|---|---|
| `R_CH1.npz` | 1261 | 52.5 d | **1.00 h** | 1.00 | 1.00 | 10.63 | 0.2 % | 0.1 % |
| `R_CH2.npz` | 1261 | 52.5 d | **1.00 h** | 1.00 | 1.00 | 10.63 | 0.2 % | 0.1 % |
| `R_cold.npz` | 667 | 30.8 d | **1.00 h** | 1.12 | 5.09 | 11.80 | 4.2 % | 1.4 % |
| (쓰인 것) `R_PNs/R_ANs` | **3** | **0.1 d** | 1.38 | — | — | 1.49 | — | — |

운영 간격은 **1.00 h 가 99 %** 다. LOO 가 본 2.75 h 는 운영의 **2.75배**다.
PCHIP 보간의 누락 곡률 오차는 sagitta ≈ (1/8)·f''·h² 로 **h² 스케일**이므로 보정계수는
(1/2.75)² = 0.132 →

> **3.30 % × 0.132 ≈ 0.44 %** (추정치다. 반드시 운영 파일로 재측정할 것.)

즉 **R(t) 항은 한 자릿수 작아질 가능성이 크고, 현재 오차예산에서 최대 구조항이라는
지위를 잃는다.** T1 이 겪은 것과 같은 실패 — LOO 간격이 운영 간격보다 훨씬 컸다.

### 재측정 지침 (T5 와 합칠 것)

1. `R_CH1/R_CH2/R_cold.npz` 로 knot LOO 를 돌린다. 스칼라 하나가 아니라
   **간격별 분포**를 낸다 — 운영의 99 % 는 1 h 이고 꼬리에 5~12 h 가 있다.
2. 결과물은 **구간별 불확도**여야 한다(그 스캔이 속한 knot 간격·곡률의 함수).
   단일 캠페인 평균치는 꼬리를 숨긴다.
3. T1 과 같은 수용 게이트를 건다 — 채널 독립 항이므로 ΣANs 시계열로 검정,
   채널당 ≤ 0.059 ppb.
4. `_invalid_cloudonly/` 아래 두 파일(`R_cold_cyclegate`, `R_cold_gate014`)은
   폴더명대로 쓰지 말 것.
