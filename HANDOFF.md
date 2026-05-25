# CAESAR Pro — 세션 핸드오프 노트

> 다른 컴퓨터/세션의 Claude Code가 이어받기 위한 진행 상황 기록.
> 최종 업데이트: **2026-05-26**  (이전 내용은 git history 참조)

---

## 0. 한 줄 요약

**오늘의 성과: Stage 4 알파 추출의 핵심 버그를 찾아 고쳤다.**
DOAS 피팅 잔차가 **96% → 10.6%** 로 개선됨 (못 쓰던 상태 → ~1ppb NO2 검출 가능한 실용 수준).
커밋 `5864c0e` (main에 푸시 완료). 1%(논문급, ~0.2ppb)까지는 추가 작업 필요 (4번 참조).

---

## 1. 현재 깃 상태

- **브랜치: `main`** (모든 작업 머지·푸시 완료). 작업트리 깨끗.
- 오늘 핵심 커밋: **`5864c0e` fix: AlphaExportWorker I0 노이즈 버그 수정**
- 그 아래로 다른 세션/PR들도 머지됨:
  - `d0b502f` Add two-step analysis workflow (Raw→Alpha→Fitting) (#14)
  - `cf24ac9` Hide ILS convolution (#15), `fd0ad43` r_trend_monitor NameError 수정 (#16)
  - PR #13(=이전 great-bardeen 브랜치: core/physics 분리, ui_dialogs 3분할, FWHM/HITRAN 수정 등) 머지됨
- 다른 컴퓨터에서 이어받기: `git clone` 또는 `git pull origin main` 한 방이면 됨.

---

## 2. ★ 오늘 고친 것 — 알파 추출 버그 (`gui/worker.py` `AlphaExportWorker`)

### 증상
Stage 4로 만든 알파(`*_alpha_trace.dat`)를 DOAS 피팅하면 잔차/신호 **96%** → 분자(NO2/CHOCHO/O4/H2O) 농도 추출 불가.

### 진단 여정 (며칠치 압축 — 같은 실수 반복 방지용)
1. 처음엔 "알파 OK, SNR 한계"로 오판 → **틀림**
2. "파장 정렬 어긋남" 의심 → 부분적
3. "측정에 분자신호 없음" 의심 → **틀림** (박사님 알파엔 신호 있음)
4. **진짜 원인 확정**: `AlphaExportWorker`가 I0(ZA 기준 스펙트럼)를 **개별 단일 ZA 스캔**으로 PCHIP 보간해 만듦. 단일 스캔 noise(~1%)가 clean-air 흡수신호(~1%)에 그대로 실려 알파가 망가짐. 평균해도 고정패턴이라 안 사라짐.

### 수정
- 한 injection의 **모든 ZA/He 스캔을 블록평균**(`_block_average`)해서 깨끗한 I0/R 생성.
  (박사님 MATLAB `Zs_*.m`/`Alpha_*.m` 의 blockfinder 평균과 동일 접근)
- 덤: `self.channel` 미정의로 재실행 시 크래시하던 것도 `channel=1` 인자로 수정.

### 검증 (3단계, 모두 통과)
1. ZA 평균 개수↑ → 잔차↓ (68개=10.5%, 3개=493%) → I0 노이즈가 원인
2. 개별 ZA(66.9%) vs 블록평균(10.6%) 시뮬레이션
3. **패치된 워커를 실제 실행** → 알파 재생성 → 피팅 잔차 **10.6%** (end-to-end)

---

## 3. 현재 품질 — 냉정한 평가

| 알파 | 잔차/신호 | NO2 검출한계 | 비고 |
|---|---|---|---|
| 수정 전 | 96% | — | 사용 불가 |
| **수정 후 (지금)** | **10.6%** | **~1 ppb** | 실용 수준, 분산 99% 설명 |
| 박사님 DOASIS / Washenfelder(gold) | ~1% | ~0.04–0.2 ppb | 논문급 |

- dark-free 피팅 최적화(O4·윈도우·poly·shift/squeeze) 다 짜내도 한계 ≈ **8%**.
- 잔차는 **랜덤 노이즈 아님, 고정구조** (3618스캔 평균인데도 박사님 60스캔보다 나쁨).
- 깨끗한 해양대기(NO2<1ppb)엔 아직 부족, ppb급/오염이벤트엔 충분.

---

## 4. ★ 1%(논문급)로 가려면 — 해야 할 일 (우선순위)

> **냉정한 결론: dark 한 가지로는 1% 보장 못 함.** 8-10% 잔차는 여러 고정요인의 합:

| 요인 | 해결책 | 비고 |
|---|---|---|
| ① 구조적 dark (CCD 픽셀패턴) | **dark 프레임 측정** (셔터 닫고 1장, 같은 적분시간) | 재사용 가능. **상수 dark는 효과 없음**(검증함, 1000~2000 무관). 픽셀별 구조가 필요 |
| ② 레퍼런스 lineshape 불일치 | **2026 장비에서 측정한 레퍼런스** 사용 | 박사님은 측정 레퍼런스 씀(`no2_meas_spectrum_blue_*.dat`). 현재 CAESAR는 생성(literature+ILS) 레퍼런스 |
| ③ 캘리브레이션/분산 불일치 | 알파 추출 캘리브 ↔ 레퍼런스 생성 캘리브 **일치** | 피팅에서 +18px shift가 보임 → 둘이 다른 calib일 가능성 |
| ④ 피팅 품질 | DOASIS급 피팅 (또는 CAESAR AlphaFitWorker 정밀화) | |

- **박사님이 같은 장비로 RMS 3e-9(=1%) 실제 달성** → 1%는 이 장비로 가능한 사실. 단 위 ①~④ 전체 패키지 필요.
- **다음에 dark 프레임이 생기면**: `AlphaExportWorker(dark_spectrum=...)`에 넣어 재추출 → 피팅 → ①의 실제 기여 측정. 그때 "3%냐 1%냐"가 데이터로 나옴.

---

## 5. 핵심 자원 / 데이터 위치 (이 PC = kh548 로컬, 드라이브 문자 바뀔 수 있음)

- **raw 측정**: `D:\CAESAR cold\2026-05\2026-05-17~19-*.dat` (Araon mega-matrix, ~94MB, flag: 1=ambient, 500-503=ZA, 510-513=He). `.mat` 변환본도 같이 있음.
- **테스트 워크플로 폴더**: `C:\Doasis work\test\` (Stage 1~5: `1.Wavelength cal`, `2.Reference gen\cold`, `4.alpha`, ...)
- **박사님 DOASIS 워크스페이스(gold standard)**: `D:\doasis\`
  - `ref_spectra\` — **측정 레퍼런스**(`no2_meas_spectrum_blue_240511.dat` 등) + 문헌 XC들
  - `fit_scenario\*.fs` — 박사님 피팅 설정(윈도우 px 1370-1600, poly 4-5, shift/squeeze link)
  - `fit\v25~v28\corrected\alpha_250703_ch1_60s_corrected.dat` — 박사님 **피팅 결과 테이블**(RMS~3e-9 확인 가능)
- **박사님 MATLAB 파이프라인**: `D:\CAESAR cold\2026-05\*.m`
  - `Rs2_*.m`(R/반사율), `Zs_*.m`(ZA 블록평균→I0), `Alpha_*.m`(알파 공식, dark 차감, 60s co-add), `Step2_*.m`(드라이버)
  - 알파 공식: `α = RL·[(1-R)/d + α_Ray_ZA]·(I_ZA/I_amb − 1) − (α_Ray_sample − α_Ray_ZA)` (CAESAR와 동일)
- **dark 파일**: 이 PC엔 **없음**. 박사님은 `dark_250703.mat`(필드 드라이브 `D:\FieldData_Araon_2025\...`, 현재 미연결) 사용. flag=0 스캔은 dark 아님(일반 측정).

---

## 6. 남은 작업 / 정리 항목

1. **(정리) RANGE-DEBUG 로그 제거** — `gui/app_window.py`에 진단용 `print("[RANGE-DEBUG]...")` 5곳이 아직 남아있음. 핏레인지 버그 원인 확정되면 제거.
2. **(미해결) 핏레인지가 Run 시 바뀌는 버그** — 가설: Run 시 모니터 탭 전환(app_window 2195 근처)에서 ROI region 신호가 `apply_roi_from_graph`로 txt_min/max 덮어씀. RANGE-DEBUG 로그로 재현 확인 필요.
3. **(품질) 1% 도전** — 4번 표대로 dark 프레임 + 측정 레퍼런스 확보 후.
4. **(백로그) #1 전체 60개 파일 R 시계열 계산** — `tools/r_trend_monitor.py`.

---

## 7. 재개 순서 (다음 세션, 금요일 이후)

1. `git pull origin main` (또는 clone)
2. 알파 fix 동작 확인하려면: `python main.py` → Stage 4(알파 추출, raw=`D:\CAESAR cold\2026-05\`) → Stage 5(피팅) → 잔차 ~10% 확인
3. 1% 원하면 4번 표 진행 (dark 프레임이 최우선·필요조건)
4. (선택) 2번 핏레인지 버그 마무리 + RANGE-DEBUG 로그 제거
