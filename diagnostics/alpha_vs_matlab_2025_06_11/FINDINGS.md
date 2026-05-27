# 알파 계산 검증 결과 — 2025-06-11 ch1

CAESAR Pro의 `AlphaExportWorker` 로직을 헤드리스로 재현해 박사님 MATLAB
(`Alpha_CAESAR_Araon_2025_3ch.m`)이 같은 raw 데이터로 만든 알파와 비교.

---

## 핵심 결론 ★

**2025-06-11 ch1 데이터는 ZA/He flag 라벨이 CAESAR Pro 기본값과 반대다.**

| Flag | Cell P (mbar) | I_peak (LED 중심) | 실제 정체 |
|---|---|---|---|
| 500-503 (CAESAR 기본 = ZA) | **854** (He bottle 설정압) | **45,911 (밝음)** | **He** |
| 510-513 (CAESAR 기본 = He) | **922** (대기에서 충전) | 45,761 (어두움) | **ZA** |

근거 두 가지가 일치:
1. **Cavity 투과강도 차이**: I_500 > I_510 → 500-스캔이 He (Rayleigh 산란 적음 → 더 밝게 투과)
2. **Cell 압력 차이**: P_500 = 854 mbar는 He 가스병 기준압 (실험실 표준 0.84 atm), P_510 = 922 mbar는 대기 흡입 ZA

→ **수정 방법: CAESAR Pro GUI에서 ZA/He flag 입력 box swap**
- 현재: ZA = "500,501,502,503", He = "510,511,512,513"
- 수정: ZA = "510,511,512,513", He = "500,501,502,503"

이렇게만 하면 `Stage 4 → 5` 피팅 잔차가 의미있게 줄어들 가능성이 큼.
박사님 MATLAB은 처음부터 swap된 flag로 처리하고 있었다 (Rs/Zs 스크립트
이 폴더에 없어 직접 확인은 못 했지만 결과 정합성으로 추정).

---

## 진단 과정 요약

### Pass 1: 4 variants 비교 (CAESAR 기본 flag)

| Tag | dark | σ | omr_d | Leff | 비고 |
|---|---|---|---|---|---|
| A | None | Sellmeier | 2.97e-5 | 0.34 km | CAESAR 기본 동작 |
| B | 1500 | Sellmeier | 2.97e-6 | 3.36 km | **broken** — 대부분 픽셀 신호<1500 |
| C | None | MATLAB 경험식 | 3.07e-5 | 0.33 km | σ 차이 미미 (~3%) |
| D | 1500 | MATLAB | 3.06e-6 | 3.27 km | **broken** |

**결과**: σ 소스(Sellmeier vs MATLAB)는 알파에 거의 영향 없음. dark=1500은 unphysical
(스펙트럼 LED 밖에서는 신호 ~600 ADU, 1500 빼면 음수 → 클램프됨).
MATLAB과 픽셀-픽셀 상관계수 ≈ 0 (의미있는 일치 없음).

### Pass 2: LED 프로파일 + R-cal 분석

`deeper_diag.py` 산출 (plots/06-08):
- **LED는 430-480 nm만 비춤** (피크 ~460 nm, intensity ~45k ADU)
- 그 외 파장: spectrum ≈ 600 ADU (dark baseline)
- ambient min ≈ 25k ADU in LED range (절대 dark까지 안 떨어짐)
- **omr_d가 LED 구간에서 음수** → ratio = I_ZA/I_He > 1 (Washenfelder 공식 깨짐)
- CAESAR의 `omr_d > 0` 필터 → LED 안쪽 픽셀 다 버려지고, 노이즈가 우연히 만든 가장자리 양수만 채택 → 의미없는 R-cal

### Pass 3: flag swap 검증 (variant E,F)

스왑 후 (3 파일 smoke test):
- ratio = I_ZA(new)/I_He(new) = 1.0000 (이전 1.025) — 부호 정상화
- omr_d 평균 = **3.1e-4 cm⁻¹** (이전 3e-5보다 10x ↑)
- Leff ≈ 32 m → (1-R)/d = 6.7e-4 with d=100, R=0.933 (박사님 MATLAB RL=0.9330 코멘트와 부합)

→ 풀 24 파일 결과는 run_swap.log 참조

---

## 부차적 발견

### 1. R-cal 임계값이 high-finesse 가정으로 하드코딩됨
`gui/worker.py:1166`:
```python
if valid.mean() >= 0.90 and np.nanmean(omr_d[valid]) < 1e-5:
```
`< 1e-5` 임계값은 (1-R)/d < 1e-5 → R > 0.999 (high-finesse mirrors) 가정.
**이 setup은 R~0.93 (low-finesse)** → 정상 omr_d ~ 5e-4가 임계값 통과 못 함.
이 데이터를 CAESAR Pro 기본 설정으로 돌리면 "no valid R calibration" 에러 나거나
임계값을 통과한 노이즈 후보만 median에 들어가 garbage alpha 생성됨.

**제안**: cavity 종류별 임계값 자동/수동 조정 옵션. 또는 사용자 입력으로
expected (1-R)/d 받고 그 5x 정도까지 허용.

### 2. dark 추정값
- HANDOFF.md의 "dark = 1000~2000" 가정은 이 데이터에 비현실적
- 실제 dark baseline = 약 580 ADU (스펙트럼 LED 밖 영역에서 측정)
- 진짜 dark는 셔터 닫고 측정한 dark 프레임 필요. 셔터 데이터 없으면 LED 밖 픽셀 평균(~580)을 dark 상수로 쓰면 됨.

### 3. CAESAR Pro 알파 자체 노이즈 패턴 (no swap 기준)
- LED 활성구간 425-475 nm에 ~2.5e-5 cm⁻¹ DC offset (bump)
- LED 모양 따라가는 구조 → R-cal 오류가 알파에 그대로 흘러간 흔적
- swap 후엔 이게 줄어들고 시간-가변 알파가 나올 것 (확인 중)

### 4. MATLAB 알파 자체 노이즈 (300-400 nm)
- MATLAB α @ 300-400 nm 에 RMS ~1e-2 cm⁻¹ 스파이크 있음
- 이 영역은 LED 빛 없음 → I_sample / (I_sample-dark) 노이즈가 R_interp에 곱해져 폭주
- MATLAB도 이 영역 알파는 못 쓰는 거고, DOAS 피팅 윈도우(보통 425-475 nm)에서만 의미.

---

## 권장 다음 단계

1. **CAESAR Pro GUI flag box swap 후 Stage 4 → 5 재실행** — 잔차/신호 변화 확인
2. **R-cal 임계값 옵션화** — `worker.py:1166`의 `< 1e-5`를 cavity finesse에 맞게
3. **dark 추정** — LED 밖 평균(~580 ADU)을 상수 dark로 시도 (1500 대신)
4. **MATLAB Rs/Zs 스크립트 확보** — `Rs_CAESAR_Araon_2025_3ch.m`, `Zs_CAESAR_Araon_2025_3ch.m`
   박사님 측에서 받으면 omr_d/alpha_cavity_fit 정의·임계값 직접 비교 가능
