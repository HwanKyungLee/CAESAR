# CAESAR Pro Cold Setup Validation (2026-05)

CAESAR Pro의 알파 추출 + DOAS 피팅 파이프라인을 cold setup 데이터
(`F:\CAESAR cold\2026-05`)로 end-to-end 검증.

## 결론 한 줄

**CAESAR Pro의 알파+DOAS 파이프라인은 정상 작동한다.** (좋은 데이터, strict
flag 사용 시).  2025-06-11 데이터의 알파 이슈는 그 데이터셋의 He/ZA contrast
0.35% 때문이지 코드 결함이 아님.

## 실행 결과 (data 파일은 D:\GHL\ 에 있음 — git 제외)

```
D:\GHL\CAESAR_Pro_validation_2026_05\
├── alpha_caesar.npz             ← (959, 2048) 알파 매트릭스
├── calib.npz                    ← R-cal 결과
├── mean_spectra.npz             ← He/ZA/Ambient 평균
├── doas_fit.tsv                 ← v1 (단순 lstsq) NO2/CHOCHO/H2O/O4 ppb
├── doas_fit_v2.tsv              ← v2 (shift/squeeze fit + link) ppb
├── plots/
│   ├── 01_mean_spectra.png            He vs ZA contrast (17%)
│   ├── 02_iza_ihe_ratio.png           R-cal input ratio
│   ├── 03_omr_d.png                   per-block omr_d
│   ├── 04_alpha_samples.png           샘플 알파 스펙트럼
│   ├── 05_alpha_timeseries.png        알파 시계열 (3 파장)
│   ├── 06_alpha_heatmap.png           알파 히트맵
│   ├── 07_doas_timeseries.png         v1 NO2/CHOCHO/O4/H2O ppb
│   ├── 08_doas_rms.png                v1 잔차
│   ├── 09_doas_examples.png           v1 3 bin 피팅 예시
│   ├── 10_doas_residual_heatmap.png   v1 잔차 히트맵
│   ├── 11_doas_v2_no2_chocho_ts.png   v2 NO2/CHOCHO (+ Kalman)
│   ├── 12_doas_v2_nuisance.png        v2 shift/squeeze/RMS 시계열
│   └── 13_doas_v2_examples.png        v2 피팅 예시
├── report.txt                   ← 알파 단계 텍스트 리포트
├── doas_report.txt              ← DOAS v1 리포트
└── doas_report_v2.txt           ← DOAS v2 리포트
```

## 스크립트 (이 폴더 = repo 내)

| 파일 | 역할 |
|---|---|
| `run_alpha.py` | 알파 파이프라인 (CAESAR Pro `AlphaExportWorker` 로직 standalone). `F:\CAESAR cold\2026-05\2026-05-17-*.dat` → `D:\GHL\...\alpha_caesar.npz` |
| `make_plots.py` | 알파 단계 시각화 (plot 01-06) + report.txt |
| `doas_fit_v1.py` | 단순 linear LSTSQ DOAS (shift/squeeze 없음) |
| `doas_fit_v2.py` | **★ 개선 버전**: NO2 shift/squeeze fit + CHOCHO/H2O/O4 link + Robust/Kalman 옵션 |
| `FINDINGS.md` | 검증 결과 정리 (전체 세션 요약) |
| `report.txt` | 알파 단계 통계 |
| `doas_report.txt` | DOAS v1 통계 |

## 재현 순서 (다른 컴퓨터에서)

1. `git pull origin claude/handoff-cold-validation` (또는 머지된 main)
2. 데이터 경로 확인:
   - Raw: `F:\CAESAR cold\2026-05\*.dat`
   - Wavelength: `F:\CAESAR cold\Calib_20260523_Hg_400-497nm_Poly2_new.txt`
   - References: `F:\CAESAR cold\Ref_*_Dynamic-ILS-Applied.dat` (4종)
3. 출력 폴더 생성: `mkdir D:\GHL\CAESAR_Pro_validation_2026_05`
4. 실행:
   ```
   cd diagnostics\cold_validation_2026_05
   python run_alpha.py        # ~5 min: 16 raw files → alpha .npz
   python make_plots.py       # 알파 단계 플롯·리포트
   python doas_fit_v1.py      # 단순 lstsq DOAS
   python doas_fit_v2.py      # shift/squeeze + link DOAS
   python doas_fit_v2.py --robust --kalman   # 옵션 포함
   ```

## 핵심 발견

| 항목 | 값 | 평가 |
|---|---|---|
| He/ZA contrast | 17.1% (61k vs 53k peak) | 좋음 |
| Cavity Leff | 1.32 km | high-finesse (R≈0.9992) |
| Dark baseline | 348 ADU (HANDOFF의 1500 추정 ✗) | LED 밖 픽셀 평균 추천 |
| Alpha mean\|α\| | 1.1e-7 cm⁻¹ | DOAS 전형값 |
| DOAS NO2 median | +0.64 ppb (v1) | 실험실 ambient 정상 |
| DOAS RMS | 3.0e-8 cm⁻¹ | 매우 깨끗 |
| NO2 plume 검출 | bin 800-950에 5-6 ppb 스파이크 | 실제 대기 이벤트 캡처 |

## ★ 코드 개선 권고 → PR 별도 푸시

`claude/strict-flags-and-rcal-threshold` 브랜치 (PR URL은 HANDOFF.md 참조):

1. **Flag 기본값 strict**: ZA="500", He="510" (501-503/511-513은 transition state)
2. **R-cal threshold configurable**: `r_cal_valid_min`, `r_cal_omr_max` 생성자 인자

## 미완 작업

- [ ] **2026-05-18/19 일부 파일 검증** (스캔 결과 He+ZA 파일 위치는 다음 섹션)
- [ ] DOAS v2 (shift/squeeze) 결과 검증 / v1과 비교
- [ ] Robust/Kalman 옵션 효과 비교
- [ ] 풀 60 파일 (2026-05-17~19) 확장

### 05-18/19 파일 스캔 결과 (He+ZA 둘 다 있는 파일만 골라야 함)
He cycle은 매 3파일마다 (사이클: He → ZA → 샘플 ×N → He → ZA → ...).
중간 ZA 샘플링 구간은 직전 He block의 R로 PCHIP 보간하면 됨.

- **05-18**: He 있는 파일 = 002, 005, 008, 011, 014, 017, 020, 023
- **05-19**: He 있는 파일 = 001, 004, 007, 010, 013, 016, 019

권장 cluster (각 일자 He block 3개 이상 포함):
- 05-18: 001-008 (8 files, He = 002·005·008)
- 05-19: 001-007 (7 files, He = 001·004·007)
