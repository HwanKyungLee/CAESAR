# CAESAR Pro — 세션 핸드오프 노트

> 다른 컴퓨터/세션의 Claude Code가 이어받기 위한 진행 상황 기록.
> 최종 업데이트: **2026-09-14**. 맨 위가 최신 세션. 그 아래는 시간순이 뒤섞여 있으니
> (08-14 → 09-14 → 08-04 …) 날짜 제목을 보고 찾을 것.

---

## 2026-09-14 (2차) — VarPro가 LM보다 느렸던 진짜 이유: 밀집 W

**증상**: "VarPro인데 왜 완전비선형/LM보다 느린가". 기존 기록은 원인을 (a) 내부
`lsq_linear` 호출, 이어서 (b) 설계행렬 재조립으로 지목했는데 **둘 다 측정으로 기각**됐다.

**진짜 원인**: `execute_varpro_fit`가 픽셀 가중 W를 **밀집 n×n 대각행렬**로 받아
목적함수 호출마다 `W @ A`(O(n²k))를 돌렸다. W는 언제나 대각이라 `A * w[:,None]`(O(nk))와
동치인데, n=775px 기준 산술량이 약 775배였다. 추가로 `y_weighted = W @ optical_depth`는
theta와 무관한데도 매 호출 재계산했다.

| 호출당 (Cold 775px, k=10) | ms | 비중 |
|---|---|---|
| `W @ A` + `W @ y` | 0.247 | **62%** |
| 설계행렬 조립(보간+column_stack) | 0.106 | 27% |
| `lsq_linear` | 0.044 | 11% |
| (동치인 행스케일 `A*w[:,None]`) | 0.0085 | — |

프로파일에서 `objective_varpro` **자기시간 49%**로 보이던 것의 정체가 이 곱이다 —
`@`는 C 빌트인이라 별도 함수로 안 잡히고 호출한 함수의 자기시간에 흡수된다.
**프로파일 해석 시 주의할 함정.**

**수정**: W를 벡터로. `core/doas_fit.py`(대각 추출 1줄 + 행스케일 3곳 + y 가중 호이스팅),
`gui/worker.py` 2곳은 `np.diag(weights)` 대신 벡터를 넘긴다. 나머지 호출부 7곳
(`fit_optimizer`·`param_optimizer`·`app_window`·`tools/*`)의 `np.eye(len(a))`도
`np.ones(len(a))`로 — n² 배열을 스캔마다 만들어 즉시 대각만 꺼내던 낭비. `W_initial`은
**밀집 행렬도 계속 받는다**(구 호출부·외부 스크립트 호환, 대각만 꺼내 씀).

**검증** — `diagnostics/varpro_speed_2026-09/validate_dense_w_removal.py` 신규.
수정 전 코드를 `git show <ref>:core/doas_fit.py`로 꺼내 별도 모듈로 임포트하고, **같은
하네스**로 실캠페인 알파를 양쪽에 돌려 스캔별 대조한다(작업트리를 되돌릴 필요 없음).
Cold 5/17(벽에 붙는 최악의 날)·6/5 + Hot ROI1/ROI2, warm/cold-start **8개 조건 ×
700스캔 = 5,600스캔에서 shift·squeeze·농도 max|diff| = 0.000e+00(비트단위 동일)**,
속도 2.17~2.51배(중앙값 2.36배). 회귀: `tools/test_etalon_collinearity.py`(10 PASS),
`test_fit_policy.py`(11), `test_pass2_parallel.py`(5), `test_health_checks.py`(13),
`python -m core.refit` 통과.

**결론이 뒤집힌 것**: "비선형 차원이 커지면 VarPro가 완전비선형보다 느리다"(d=8에서
1.9배 패배)는 **구현 버그 때문이었다**. 수정 후 d=8에서 21.2 vs 37.7 ms/scan(1.8배 승),
Cold d=2에서 4.28 vs 10.32(2.4배 승) — 모든 조건에서 VarPro가 빠르다.
`docs/논문_주장구조_2026-09.md` 1단의 "쓰지 말 것" 항목을 이에 맞게 고쳐뒀다.
단, 해석적 자코비안(Golub–Pereyra)은 여전히 미구현이라 **"차원축소 덕에 빠르다"는
아직 주장할 수 없다** — 측정값으로만 쓸 것.

⚠ `diagnostics/` 전체가 `.gitignore`에 있어 위 검증 스크립트는 **커밋되지 않는다**
(이 폴더의 다른 스크립트들과 동일). 다른 컴퓨터에서 이어받으려면 따로 복사할 것.

---

## 2026-08-14 세션 — 멀티채널 결과 테이블 더블클릭 리플레이 버그 3건

`app_window.py`의 `on_table_double_click`(결과행 더블클릭 → 오른쪽 Analysis Monitor에 fit
리플레이)이 멀티채널 모드에서 사실상 항상 조용히 실패하던 걸 발견·수정. 전부 같은 뿌리:
GUI가 "활성 채널" 상태를 `self.engine` / `self.file_list` / `txt_min`·`txt_max` 라는
**공유 슬롯 하나**에 담아두고, 채널 탭 전환마다 `_channel_configs`/`_channel_files`에
스냅숏·복원하는 구조라서, 비활성 채널의 데이터를 건드리는 코드는 매번 재구성이 필요했는데
안 하고 있었음.

1. **파일 lookup이 활성 탭 채널로만 스코프됨**: `self.file_list`는 지금 선택된 채널 탭의
   파일만 담고 있는데, 결과 테이블은 전 채널을 한 테이블에 같이 보여줌 → 다른 채널 탭을 보는
   동안 결과행을 더블클릭하면 "파일 못 찾음"으로 조용히 실패. `_entry_from_display_name`에
   `file_list` 인자를 추가해 클릭한 행의 채널(`self._channel_files[ch]`)에서 찾도록 수정.
2. **채널탭 전환 시 결과 테이블이 통째로 사라짐**: `_show_channel_files`가 탭 바꿀 때마다
   `self.table.clearContents()`로 "그 채널의 입력파일 목록" 미리보기를 새로 그려서, 피팅
   끝낸 뒤 탭을 바꾸면 결과가 화면에서 사라진 것처럼 보였음(`self.results`엔 남아있었음).
   `self.results`가 있으면 테이블을 건드리지 않도록 가드 추가.
3. **비활성 채널 리플레이가 활성 탭의 엔진/레인지로 잘못 계산됨**: `self.engine`/`txt_min`/
   `txt_max`가 활성 탭 것만 반영하므로, 다른 채널 결과를 리플레이하면 엉뚱한 레퍼런스·wavecal·
   핏레인지로 재계산되고 있었음. `_build_engine_from_config`(원래 병렬 fit worker용으로 있던
   함수)를 재사용해 클릭한 결과 채널의 임시 엔진을 만들어 리플레이하도록 수정.

부수적으로: 파일명에서 스캔 row index를 항상 0으로 가정하던 버그도 같이 발견·수정
(`_row_index_from_display_name` 신설 — 테이블 표시명 끝의 `[NNNN]`에서 실제 row를 파싱),
그리고 `on_table_double_click`이 raw 파일을 원시 `DataIO.load_measurement`(고정 컬럼수
CSV 파서)로 읽어서 `alpha_trace.dat`(가변 컬럼) 형식에서 tokenizing 에러가 나던 것도
`DataIO.load_measurement_with_hk`(alpha_trace/Mega-Matrix/1D 전부 처리)로 통일해 해결.

**후속 회귀 (같은 세션에서 바로 발견·수정)**: 위 2번 가드(`self.results`가 있으면 탭 전환 시
표를 안 건드림)가 너무 거칠었음 — 예전 Run의 stale한 `self.results`가 남아있는 채로 **새
데이터를 로드**하면, 채널탭을 눌러도 그 채널의 새 파일목록이 안 보이고 계속 이전(첫번째) 탭의
내용만 보여서 "채널별로 데이터가 잘 들어갔는지 확인이 안 됨" 문제가 생겼음. `_update_file_table`
/ `_distribute_channels`(둘 다 새 데이터 로드 진입점) 맨 앞에 `self.results = []`를 추가해
해결 — 새 파일셋을 로드하면 그 전 Run의 결과는 어차피 이 파일셋에 대한 게 아니므로 자동 무효화.

**구조적 부채 (의도적으로 보류)**: 위 3버그가 전부 "GUI는 활성 채널 하나만 공유 슬롯에 담고
스냅숏/복원"하는 설계에서 나옴. 실제 피팅 Worker는 이미 채널마다 완전히 독립된 엔진 인스턴스를
쓰는데, 인터랙티브 GUI만 이 패턴을 안 따름. 근본 해법은 GUI도 `self._channel_engines[ch]`처럼
채널별 영구 엔진 인스턴스를 갖고 탭 전환은 "어느 걸 보여줄지"만 바꾸는 구조로 가는 것 —
그런데 Setup/레퍼런스락 UI 전반을 건드리는 큰 리팩터라 지금은 보류. **이런 유형("비활성 채널
데이터를 만지면 어긋남") 버그가 더 나오면 그때 구조 개편을 검토할 것.**

---

## 2026-09-14 세션 — 파이프라인 점검 (커밋 7개, main 머지됨)

무엇을 했는지는 커밋 메시지에 다 있다(`git log b7a107e..058cf34`). 여기엔 **다음 세션이
바로 집을 수 있는 것**만 적는다.

### 바로 할 수 있는 것

1. ~~**`objective_varpro`의 중복 보간 제거**~~ — ✅ **더 큰 원인을 먼저 잡았다**
   (아래 "2026-09-14 (2차)" 참조: 밀집 W 제거, 2.4배). `Link` 중복 보간은 **아직 남아
   있고** 호출당 약 14%짜리로 여전히 유효한 다음 후보다(`evaluate_spline` d=2 280회 /
   d=8 1,120회). ⚠ 핏 수치 경로 — `diagnostics/varpro_speed_2026-09/
   validate_dense_w_removal.py`를 그대로 재사용해 동일성 검증을 붙일 것.

2. **squeeze의 모르는 모드가 조용히 사라진다** — `core/doas_fit.py` setup_fit_parameters의
   squeeze 사다리는 Limit/Free/Fix/Link만 본다. `Center` 같은 값을 주면 변수가 등록 안 되고
   나중에 `KeyError: '<gas>_sq'`로 터진다. shift 쪽은 `?모드`로 드러내게 고쳤는데 squeeze는
   아직. (실제로 당했다)

3. **Cold CHOCHO 결정 검증** — Cold를 shift **자유**로 재실행해 QDOAS와 조건을 맞추면
   Deming 기울기가 0.72에서 1 쪽으로 움직이는지. 지금 근거(차등공선성 0.003 = 축퇴 아님,
   ΔCHOCHO↔ΔH2O −0.96, Hot PNs 대조군 1.02)는 `docs/논문_주장구조_2026-09.md`에 있다.

### 사람이 화면에서 확인할 것 (코드는 끝남)

- Result Lab에서 점 클릭 → 잔차 레인이 뜨는지, 재현 실패율이 쓸 만한지
  (`REPRO_TOL_REL` 1%가 빡빡하면 `core/refit.py` 한 줄)
- 알파·R·그림이 `output/{campaign}/…`로 떨어지는지

### 새로 생긴 자기검증 (수정 후 돌릴 것)

```
python -m core.physics        # ppb 환산 단일 출처 + Rayleigh와 같은 상수
python -m core.refit          # 잔차 재핏 + 거부 5종
python -m core.agreement      # Deming/BA/블록부트스트랩
python -m core.error_budget   # 오차 예산(미정량 항이 숨지 않는지)
python tools/test_raw_layout.py
```

### 건드리지 않은 것

`oculus/`(conc_monitor·profiles·watcher·state_log·run_oculus)와 `core/profile.py`의
워킹트리 변경은 **사용자 병렬 작업**이라 커밋에서 제외했다.

---

## 최신 세션 (2026-08-04~12) 요약

**브랜치: `claude/oculus-realtime-monitoring-pbjudz`** — origin에 push 완료, 다른 컴퓨터에선
`git pull origin main` 한 방이면 아래 항목 전부 받아짐 (이번 세션에서 이 브랜치를 main으로 fast-forward merge).

### 완료된 작업

1. **Test Fit 2탭 다이얼로그** (`gui/test_fit_dialog.py`, 커밋 `5a3313b`)
   - 탭1: 12스캔 샘플로 파라미터 자동 최적화 + Apply
   - 탭2: 기존 1스캔 미리보기 (하위호환 유지)
   - px_start 디텍터 오프셋 버그 수정 포함. `app_window.py`의 `_test_fit`을
     `_compute_1scan_preview` + 헬퍼로 리팩터링, 구 Test Fit 메서드 삭제.
   - 유닛테스트 `test_test_fit_dialog.py` 15개 통과.
   - 상세 설계 근거: `docs/fit_optimizer_handoff.md`.

2. **Pass 2 (알파 계산) 병렬화** (`gui/worker.py`, 커밋 `b492681`, `5fd08f7`, `a3f9dc2`)
   - `AlphaExportWorker`를 `ProcessPoolExecutor` 기반 청크 병렬처리로 전환 (Pass 1과 동일 패턴 재사용).
   - 순차 대비 byte-exact 회귀 검증 스크립트 (`diagnostics/alpha_pass2_parallel/validate_pass2_parallel.py`)
     추가하고 CI에 자동화.
   - `run_alpha.py` 진단 스크립트가 물리식을 재구현하지 않고 `worker.py`의 순수함수를 재사용하도록 정리
     (단일 출처 원칙 준수).

### 완료 — 2026-08-13 세션에서 이어받아 끝낸 것

**α Health 탭 → 전체 파이프라인 헬스체크 전환** ✅ 완료
- `app_window.py`의 `"🩺 α Health"` 탭을 `"🩺 Pipeline Health"`로 확장. 기존 `_alpha_qc_scan_folder`
  (알파 파일 스캔)는 그대로 두고, `core/health_checks.py`의 wavecal·references·Rayleigh·R 체크를
  같이 돌려 PASS/WARN/FAIL/SKIP 하나로 종합 판정.
- 같은 세션에서 `core/fitset_builder.build_fitset()`에도 `check_wavecal`/`check_references`를
  후보 refs셋 평가 전 게이트로 연결(fit_optimizer_handoff.md §10-C.4) — 연결 과정에서
  `check_references`의 절대-std 평평함 판정 버그(O4를 항상 퇴화로 오판)도 발견·수정.
  `tools/test_health_checks.py` 신규.

### 미완료 — 다음에 이어받을 것

(현재 없음 — 위 항목까지 완료된 상태. `docs/Oculus_설계_2026-07.md` §7·§8을 보면 Oculus
M0~M3도 이후 완료됨. NIER 제출(R0, 8/14 마감) 관련은 별도 워크플로,
`docs/NO2_인젝션_실험_핸드오프_2026-08.md` 참조.)

### 알아둘 것 — dirty 상태로 남겨둔 것들

이 세션엔 위 완료 항목과 무관한 변경도 워킹트리에 섞여 있었음 (NIER 제출용 `tools/build_nier_submission.py`
등 수정, NO2 인젝션 실험 문서, `R_ANs.npz`/`R_PNs.npz` 바이너리). **의도적으로 커밋/merge에서 제외** —
main엔 완료된 커밋들만 올라감. 이어받을 때 `git status`로 이 미완성 변경이 로컬에 남아있는지 확인.

---

## 0. 이전 세션 (2026-05-27) 한 줄 요약

**CAESAR Pro의 알파+DOAS 파이프라인이 정상 작동함을 cold setup 데이터로 end-to-end 검증 완료.**
2025-06-11 데이터의 알파 이슈는 코드 결함이 아니라 그 데이터셋의 He/ZA contrast 0.35% 문제로 판명. 부수적으로 발견한 두 가지 코드 개선사항은 PR 브랜치에 푸시 완료.

---

## A. 이번 세션 작업 (2026-05-27)

### A1. 검증 작업 ★

- **2025-06-11 ch1 데이터** (`raw(ex)/2025-06/2025-06-11-*.dat`, 24 files)로 박사님 MATLAB
  알파(`C:\Doasis_Work\LGH\아라온호 데이터분석\alpha_trace\ch1_20250611_000000\`,
  1399 bins × 2048 px)와 비교 시도 → **r ≈ 0** (의미있는 일치 없음).
  - 원인: 그 데이터의 He/ZA I_peak 차이가 0.35% (45929 vs 45767)밖에 안 됨 → R-cal이
    노이즈에 묻힘. 박사님 MATLAB 알파도 UV 영역(300-400 nm)에선 garbage임.
  - 산출물: `diagnostics/alpha_vs_matlab_2025_06_11/FINDINGS.md` + scripts + plots/
- **2026-05-17 ch1 cold setup** (`F:\CAESAR cold\2026-05\2026-05-17-*.dat`, 16 files)로
  재검증 → **He/ZA contrast 17.1%**, R-cal 16/16 ZA blocks 통과, **Leff = 1.32 km**,
  알파 mean\|α\| = 1.1e-7 cm⁻¹, NO2 differential structure 명확히 보임.
  - DOAS 피팅 결과: **NO2 median 0.64 ppb, RMS 3e-8 cm⁻¹**, bin 800-950에 NO2 plume(5-6 ppb) 캡처.
  - 산출물: `diagnostics/cold_validation_2026_05/` (scripts + docs) +
    `D:\GHL\CAESAR_Pro_validation_2026_05\` (.npz 데이터 + plots, git에 안 들어감)

### A2. ★ 코드 개선 PR (별도 브랜치)

**브랜치: `claude/strict-flags-and-rcal-threshold`** (push 완료)
**PR 생성 URL**: https://github.com/HwanKyungLee/CEASER/pull/new/claude/strict-flags-and-rcal-threshold

두 가지 수정:
1. **ZA/He flag 기본값 strict화** (`gui/app_window.py`):
   "500,501,502,503"/"510,511,512,513" → "500"/"510". 501-503/511-513은 setflow/wait
   전환구간이라 cavity 미충전 — I0/R-cal에 들어가면 오염시킴. (Tooltip 의도와도 일치)
2. **R-cal threshold configurable** (`gui/worker.py:1166` `AlphaExportWorker`):
   하드코딩 0.90/1e-5 → 생성자 인자 `r_cal_valid_min`, `r_cal_omr_max`. 기본값 유지 →
   high-finesse cavity (R>0.999)은 동작 변화 없음. Low-finesse 셋업엔 docstring에서
   `0.50 / 1e-3` 권장. GUI 노출은 follow-up PR로.

### A3. 다음 세션 할 일 (2026-05-27 최종 업데이트)

**완료된 항목** ✅
- [x] PR 머지: `claude/strict-flags-and-rcal-threshold` → main (commit `d982b62`)
- [x] 05-17/18/19 멀티데이 알파 검증 (각 5-8 파일, `diagnostics/cold_validation_2026_05/multi_day_report.txt`)
- [x] DOAS v1 vs v2 비교 (v2가 1.6-3.2x RMS 개선; shift=0/sq=1, 윈도우 변경 효과)
- [x] Leff misleading 발견·정정 (full mean ≠ real cavity; LED-center 사용해야)

**남은 우선순위** (TODO)

**P1 — `worker.py:1175` Leff 보고 로직 fix**
- 현재 `1.0/np.mean(best_omr_d)*1e-5` → LED 밖 가장자리 spike에 부풀려짐
- 05-19에선 0.28 km 보고했지만 실제 LED-center mean으론 10.77 km
- 수정: `np.mean(best_omr_d[led_mask])` 또는 `np.median(best_omr_d)` 사용
- 간단한 PR, 별도 브랜치 권장

**P2 — GUI 알파 검증 (사용자 직접 작업)**
- main 머지됨 → strict flag 기본값으로 GUI 동작
- 사용자가 `python main.py` → Stage 4 (Alpha Export, cavity=51.8cm CH1) → Stage 5 (DOAS)
- GUI 결과와 내 검증 결과(`D:\GHL\multi_2026_05_*/alpha_caesar.npz`) 픽셀별 일치 확인 필요
- 불일치 시: GUI에 들어간 cavity_len, dark 파라미터 점검

**P3 — shift/squeeze 옵티마이저 동작 확인**
- `doas_fit_v2.py`는 3일 모두 shift=0, squeeze=1 반환
- 가능성 (a) 진짜 wavelength cal이 정확해서 0 옵티멈, (b) L-BFGS-B가 flat region에 갇힘
- 확인 방법: 초기값 perturb (shift=±2 px), `scipy.optimize.differential_evolution` 시도
- 만약 (b)이면 nonlinear 부분 다시 디자인

**P4 — `worker.py` R-cal 알고리즘 개선**
- 현재 `best_omr_d = median across all candidates` (단일 시간 상수)
- 박사님 MATLAB은 `alpha_cavity_fit` 시간보간 (PCHIP) 사용
- He 사이클 매 3파일 → ZA 사이 구간은 직전 He block과 PCHIP으로 R 보간하는 게 정확
- 옵션화: `r_cal_mode='median' | 'pchip'`

**P5 — 1% 잔차 도전 (HANDOFF.md §4 표 참조)**
- Dark frame 측정 (셔터 닫고 측정) — `AlphaExportWorker(dark_spectrum=...)` 인자 이미 있음
- 측정 ref 사용 (박사님 `no2_meas_spectrum_blue_240511.dat` 같은)
- 05-18 cold v2 RMS 5.2e-9 / mean\|α\| 4.2e-8 = 12% 잔차 → 추가 개선 여지

**P6 — Hot setup (Yeosu 2026) 동일 검증**
- `campaigns/yeosu_2026/` 데이터로 같은 멀티데이 절차
- CH2 (PNs)도 확인 — strict flag 변경이 회귀 안 일으키는지 검증

---

## B. 이전 세션 (2026-05-26) 노트 — 이력 보존

### 0. 한 줄 요약 (이전)

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

1. ~~**(정리) RANGE-DEBUG 로그 제거**~~ — ✅ 완료 (5곳 모두 제거).
2. ~~**(미해결) 핏레인지가 Run 시 바뀌는 버그**~~ — ✅ 완료. `apply_roi_from_graph`/`update_range`에 `_analysis_running` 가드 추가 → Run 중에는 모니터 ROI 신호가 txt_min/max를 덮어쓰지 않음.
3. **(품질) 1% 도전** — 4번 표대로 dark 프레임 + 측정 레퍼런스 확보 후.
4. **(백로그) #1 전체 60개 파일 R 시계열 계산** — `tools/r_trend_monitor.py`.
5. **(완료) He/ZA 인덱싱 검증 intensity 시계열 + α_cavity 패널** — 남 우희 박사님 요청
   (Fig 41/66, 42/43 레퍼런스 반영). R 그림 생성 시 채널별로 다음을 함께 출력:
   - `Intensity_scanidx_{Cold,Hot_PNs,Hot_ANs}.png` — **scan index** x축 (박사님 Fig 41/66).
     ambient를 채널색으로 옅게 깔고 ZA(검정 빈 원)·He(검정 채운 삼각형)를 덮어 인덱싱이
     제대로 잡혔는지(검정이 elevated row에 안착하는지) 행 단위 확인. 파일 경계 세로선.
   - `Intensity_time_{...}.png` — **시간축** x축. ZA ~1시간 주입 cadence 확인용.
   - `R_curve_{...}.png` — R / Path Length(Leff) / **α_cavity** 3패널 (박사님 Fig 42/43).
     ⚠️ α_cavity = (1−R)/d 는 **5차 다항식으로 보간된 R**(r_curve_fit)에서 계산
     (reflectance_calc.omr_d_fitted와 동일 정의), raw R 아님.
   - 구현: `collect_intensity_by_flag()`(scan idx+time+파일경계 수집),
     `plot_intensity_index()`, `plot_intensity_timeseries()`, 확장된
     `plot_r_curves_per_channel()`. `SHOW_INTENSITY_INDEX`/`INTENSITY_AMBIENT_STRIDE`로 토글.
   - `main()` 반환 시그니처(GUI `_RTrendWorker`)는 유지.

---

## 7. 재개 순서 (다음 세션, 금요일 이후)

1. `git pull origin main` (또는 clone)
2. 알파 fix 동작 확인하려면: `python main.py` → Stage 4(알파 추출, raw=`D:\CAESAR cold\2026-05\`) → Stage 5(피팅) → 잔차 ~10% 확인
3. 1% 원하면 4번 표 진행 (dark 프레임이 최우선·필요조건)
