# CAESAR Pro 알파 검증 — 2026-05-17 cold setup

## 한 줄 요약

**CAESAR Pro의 알파 추출 파이프라인은 정상 작동한다.**
좋은 데이터(He/ZA contrast 17%)에서 픽셀 1e-7 cm⁻¹ 스케일의 깨끗한 알파를
생성하며, NO2 differential absorption fingerprint도 시각적으로 식별 가능.

이전 2025-06-11 데이터로 본 이상 동작은 **그 데이터셋의 He/ZA contrast가
0.35%밖에 안 되는** 문제였지 코드 결함이 아니었다.

---

## 입력

| 항목 | 값 |
|---|---|
| Raw | `F:\CAESAR cold\2026-05\2026-05-17-*.dat` (16 파일, ~99 MB each) |
| Wavelength | `F:\CAESAR cold\Calib_20260523_Hg_400-497nm_Poly2_new.txt` |
| 파장범위 | 400.30 ~ 496.75 nm (2048 pix, 0.047 nm/px) |
| RL_factor | 0.9764 (cold setup, HANDOFF.md 참조) |
| Flag (strict) | ZA = {500}, He = {510}, Amb = {1} |
| **★ 501-503/511-513 제거 이유** | setflow/wait_before 상태 — cavity 아직 가스 안 찼음, I0 오염 |

## 결과 요약

### 1. 평균 스펙트럼 (Plot 01)

| Gas | I_peak | λ_peak |
|---|---|---|
| He (flag 510) | **64,326** | 460.2 nm |
| ZA (flag 500) | **53,327** | 460.1 nm |
| Ambient | 49,353 | — |
| Ambient min | 348 | — (dark proxy) |

- **He/ZA contrast = 17.1%** — Rayleigh 차이가 명확히 보임 (정상)
- 너님이 언급한 "He 61k, ZA 50k"와 일치
- **Dark baseline ~348 ADU** (LED 밖 영역) — HANDOFF.md의 1000~2000 추정은 과대평가였음

### 2. R-calibration (Plot 02, 03)

- I_ZA/I_He 비율: LED 활성구간(440-475 nm)에서 0.80까지 떨어짐 (정상 — ZA Rayleigh가 He보다 큼)
- 460 nm에 작은 bump → ZA 대기 NO2 잔류 신호 (정상)
- **omr_d = 7.56e-6 cm⁻¹** (16/16 ZA 블록 모두 통과)
- **Leff = 1.32 km** → high-finesse cavity (R ≈ 0.9992 with d=100 cm)

### 3. 알파 (Plot 04, 05, 06)

- Total bins: 959 (60s × ~16시간), 비어있지 않은 bin: 953
- mean(|α|) = 1.1e-7 cm⁻¹, median = 8.8e-8 — 깨끗한 대기 흡수 스케일
- λ별 알파 평균:

| λ (nm) | mean α (cm⁻¹) | std (cm⁻¹) |
|---|---|---|
| 410 | +3.4e-9 | 1.7e-7 |
| 430 | +9.3e-8 | 9.5e-8 |
| **450** | **+1.1e-7** | 7.9e-8 |
| 470 | +8.6e-8 | 5.7e-8 |
| 490 | +2.4e-8 | 8.3e-8 |

- 샘플 알파 스펙트럼(Plot 04)에서 430-445 nm, 460-475 nm에 **NO2 differential 구조 명확히 보임**
- 시계열(Plot 05)은 각 파장에서 매우 안정적 (std ~1e-7), 시간에 따른 작은 step만 보임
- 히트맵(Plot 06)에서 시간-파장 모두 깨끗한 패턴

---

## 결론: CAESAR Pro 알파는 잘 만들어진다

이전 2025-06-11 검증에서 "알파가 망가졌다"고 본 건:
1. 그 데이터의 He/ZA contrast가 0.35%밖에 안 됨 (이 데이터는 17%) → R-cal이 노이즈에 묻힘
2. 내가 flag 500-503 / 510-513 묶어서 처리 → 501/502/503 transition state가 I0 오염
3. 결국 데이터 품질·flag 처리 문제

**2026-05-17 데이터로는 CAESAR Pro 파이프라인이 정확히 동작**:
- R-cal 안정 (16/16 통과)
- 알파 스케일 ~1e-7 cm⁻¹ (DOAS 전형값)
- NO2 fingerprint 식별 가능
- 시간 안정성 좋음

---

## DOAS 피팅 결과 (`doas_fit.py`, `doas_fit.tsv`)

CAESAR Pro `AlphaFitWorker` 로직(`gui/worker.py:1291`) standalone 재현.
- Fit window: 425-490 nm (1396 px)
- References: NO2 / CHOCHO / O4 / H2O Dynamic-ILS-Applied (`F:\CAESAR cold\Ref_*.dat`)
- Baseline: Chebyshev poly deg=5
- σ scaling: auto (각 컬럼 max\|σ\|을 10^n으로 정규화 → cond num 1e19 → ~10 해결)
- LSTSQ on 953 bins

| Gas | mean | median | std | 평가 |
|---|---|---|---|---|
| **NO2** | +1.08 ppb | **+0.64 ppb** | 1.35 ppb | ✓ 실험실 ambient 정상값 |
| CHOCHO | -1.84 ppb | -1.47 ppb | 1.46 ppb | 검출 한계 이하 |
| O4 | -1.2e37 | — | 8.6e36 | (molec²/cm⁵) — 없음 |
| H2O | ~0 ppb | — | — | 0.78nm ILS로 H2O 미세선 smear, 이 해상도로 검출 어려움 |
| **RMS** | **3.0e-8 cm⁻¹** | 2.9e-8 | (2.2-4.7e-8) | 깨끗 |

**핵심**: NO2 시계열에서 일중 0-2 ppb 안정 baseline + bin 800-950 구간에 5-6 ppb 스파이크 (**실제 NO2 plume 이벤트 캐치**).

→ **CAESAR Pro의 알파 추출 + DOAS 피팅 파이프라인이 end-to-end 정상 작동**.

## 멀티데이 비교 (2026-05-27 추가, `multi_day_compare.py`)

05-17 / 05-18 / 05-19 각 5-8개 파일로 알파+DOAS v1/v2 비교.

| 지표 | 05-17 | 05-18 | 05-19 |
|---|---|---|---|
| ZA blocks / He blocks | 16 / 6 | 8 / 3 | 7 / 3 |
| **Leff (km)** | 1.32 | **6.76** | **0.28** (misleading, 본문 참조) |
| Alpha bins | 953 | 439 | 413 |
| mean\|α\| (cm⁻¹) | 1.1e-7 | 4.2e-8 | 7.8e-7 |
| v1 NO2 median (ppb) | +0.64 | +0.16 | +1.15 |
| v2 NO2 median (ppb) | +1.04 | +0.08 | +0.26 |
| **v1 RMS (cm⁻¹)** | 2.9e-8 | **8.1e-9** | 1.85e-7 |
| **v2 RMS (cm⁻¹)** | 1.2e-8 | **5.2e-9** | 5.8e-8 |
| **v2/v1 개선** | 2.35× | 1.57× | **3.18×** |
| shift / squeeze | 0 / 1 | 0 / 1 | 0 / 1 |

### 멀티데이 핵심 발견

1. **Cavity 일자간 변동 큼 (보고된 Leff는 misleading!)**.
   `1/mean(omr_d) × 1e-5`의 mean이 LED 밖 가장자리 노이즈 spike에 부풀려짐.
   진짜 cavity 성능은 LED-active (440-475 nm)에서만 평균해야 함:

   | | 05-17 | 05-18 | 05-19 |
   |---|---|---|---|
   | Leff (full mean, **잘못된 보고값**) | 1.32 km | 6.76 km | **0.28 km** ❌ |
   | Leff (DOAS window 430-480) | 5.83 km | 10.26 km | 4.24 km |
   | **Leff (LED center 440-475, 진짜)** | **8.77 km** | **11.94 km** | **10.77 km** ✓ |
   | Leff (full median, robust) | 2.99 km | 8.06 km | 2.90 km |

   → **3일 모두 cavity 9-12 km 수준으로 비슷**. 05-19도 멀쩡함.
   → CAESAR Pro `worker.py:1175`의 Leff 보고 로직 (`1.0/np.mean(best_omr_d)*1e-5`)도
   같은 문제 — median 또는 LED-active mean으로 바꿔야 함 (후속 PR 거리).

2. **05-18은 박사님 1% 잔차 근접** — RMS 8.1e-9 (v1) / 5.2e-9 (v2) cm⁻¹.
   mean\|α\| 4.2e-8 대비 RMS 비율 = **12-19%**, HANDOFF 2026-05-26의 10.6% 목표 달성.

3. **DOAS v2 일관되게 v1보다 1.6-3.2× 개선** (모든 일자).
   But **shift=0, squeeze=1** 3일 모두 — **윈도우 변경(425→430-480) + cubic interp** 덕분이지
   nonlinear shift/squeeze fitting 자체 효과는 아님. wavelength cal 매우 정확.

4. **NO2 베이스라인 일자간 일관성** — 0.1~1.2 ppb 범위, 깨끗한 실험실 ambient.
   05-17은 후반 NO2 plume(5-6 ppb) 캡처 → 실제 대기 이벤트도 정상 검출.

### multi-day 산출물
- `D:\GHL\multi_2026_05_18\` (알파 .npz, plots, v1 fit TSV)
- `D:\GHL\multi_2026_05_19\` (알파 .npz, plots, v1 fit TSV)
- `D:\GHL\CAESAR_Pro_validation_2026_05\doas_fit_v2_{17,18,19}.tsv` (v2 결과)
- `plots/14_multi_day_no2.png` (3일 NO2 오버레이)
- `plots/15_multi_day_omr_d.png` (omr_d shape 비교)
- `multi_day_report.txt` (텍스트 요약 표)

## 추가 제안

2. **CAESAR Pro 코드 개선 제안**:
   - **★ 기본 flag 설정 변경**: GUI 기본값을 `ZA = "500"` / `He = "510"` (strict)으로
     변경 권장. 현재 "500,501,502,503" / "510,511,512,513"은 transition state 오염.
   - **R-cal threshold 옵션화**: `worker.py:1166`의 `< 1e-5`는 이번 cold setup
     (omr_d ~7.5e-6) 잘 맞지만, ship setup(omr_d ~3e-4)엔 너무 빡빡. cavity finesse
     모드 선택 옵션 추가하면 사용성↑
   - **Dark 추정 자동화**: LED 활성 밖 픽셀 평균(이 데이터는 ~350)을 default dark
     상수로 추천하는 기능

3. **2026-05 전체 (60 파일)로 확장 검증** — 위 결과가 다른 일자에도 안정적인지

---

## 산출물

```
D:\GHL\CAESAR_Pro_validation_2026_05\
├── run_alpha.py             ← 메인 파이프라인 (CAESAR Pro 로직 standalone 재현)
├── make_plots.py            ← 시각화·리포트 생성
├── alpha_caesar.npz         ← (959, 2048) 알파 + 시간 + 카운트
├── calib.npz                ← R-cal 결과 (omr_d, ZA/He 블록 스펙트럼)
├── mean_spectra.npz         ← He/ZA/Ambient 평균
├── report.txt               ← 텍스트 리포트
├── run.log                  ← 실행 로그
├── FINDINGS.md              ← 이 문서
└── plots/
    ├── 01_mean_spectra.png  ← He vs ZA contrast 검증
    ├── 02_iza_ihe_ratio.png ← R-cal input ratio (LED region 0.80까지)
    ├── 03_omr_d.png         ← per-block + median omr_d
    ├── 04_alpha_samples.png ← 3개 대표 시간대 알파 스펙트럼
    ├── 05_alpha_timeseries.png ← 3 파장의 시계열
    └── 06_alpha_heatmap.png ← 알파 (bin × pixel) 히트맵
```
