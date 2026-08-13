# CAESAR Pro — 핏세팅 최적화 프로그램 핸드오프

> 다른 세션이 이 문서 하나로 맥락을 잡고 이어가도록 정리. 작성 2026-06-30, 최종 갱신 2026-08-04.
> **🚀 처음 읽으면 §10(현재 상태)부터.** 그다음 §15(명세) → §2-B(신뢰 3계층) → §16(Center 모드).
> ⚠️§1·§2는 2026-07-21 시점 기록이라 일부 문장이 이후 결론에 의해 갱신됐다(각 절의 갱신 주석 참조).
> 저장소: `C:\Doasis_Work\CAESAR\CAESAR` (중첩 CAESAR 폴더 주의).
> 관련 메모리: `fit-optimizer-stage1-2026-07`, `filtering-philosophy`,
> `hot-channel-swap-ans-2026-06`, `cold-residual-fixed-pattern-2026-06`,
> `settling-scan-bias-and-tool-2026-06`.

---

## 0. 한 줄 목표
채널별 핏세팅(핏시나리오)을 자동 최적화. **목표 = 농도가 안 움직이고(농도불변) · shift가 물리적으로
안정하며 · 잔차가 흰(white) 상태를 만드는 "가장 단순한" 세팅** (Occam + 데이터 무결성 헌장).
잔차 RMS 최소화가 목표가 **아님** — 그러면 poly↑·창잘라먹기·shift다풀기로 수렴해 농도가 물리적으로 깨짐.

## 1. 채택 방향 (2026-07-21 방향전환)
> **📌 갱신(2026-08-04)**: 아래 "핏레인지 자동탐색 폐기"는 **fitting-driven(perr로 채점하는 방식)**만
> 폐기했다는 뜻이다. 이후 **design-driven 창 설계**(핏 없이 c-optimality)를 새로 만들었고 **동작한다**
> — `core/window_designer.py`, §14. 창 설계는 살아있는 기능이니 "창은 고정"으로 오해하지 말 것.
- **핏레인지 자동탐색(perr 기반)은 폐기.** perr가 물리를 몰라 창을 480/422nm로 스프롤 → 실제 창(438-466)과 안 맞음.
- **채택 = 파라미터 최적화** (refs·핏레인지는 **고정**, 사용자 FitSet json이 baseline). 창 고정이라
  degeneracy·스프롤 함정 사라져 목표함수가 신뢰 가능해짐. 사용자 우선도 ★★★★★.

### A. 최적화 대상 (탐색)
- **poly 차수** (최소 무릎점 — 더 올려도 잔차구조 안 줄어드는 지점)
- **ref별 shift 정책 + 크기**, **squeeze 정책 + 크기**, t_coeff
- shift/squeeze 크기는 **넓게 풀어 실제 핏된 분포를 측정 → bounds가 데이터에서 나오게**
  (blind 그리드 아님. ANs 비대칭도 자동 재현).

### B. 최적화 금지 (원칙상 default 고정)
- **Neg 허용** = 헌장(지우지 말고 flag). 기본 ON 유지.
- **QC** (K=6·settling skip) = 최적화 대상 아님. 기본 정책.
- **Tikhonov·Robust·Kalman** = 구조를 가리는 "화장". 기본 OFF. 최적화로 켜지 말 것.

## 2. 목적함수(진실신호) — 무엇으로 좋고 나쁨을 재나
> **📌 갱신(2026-08-04)**: 이 절의 "모델 내부 신호만" 방침은 **§2-B(신뢰 3계층)로 대체**됐다.
> T1(자기일관성)만으로는 과적합을 상 준다는 게 O4로 실증됨. 최종 규칙은 **§15-B**를 따를 것.
- **모델 내부 신호만** 사용 (채널일치·박사님fit 정답 안 씀).
- **perr**(covariance 대각의 √ = 파라미터 불확실도) + **잔차 구조**.
- 자유도↑(poly↑·shift다풀기)면 perr가 부풀어 과적합을 자연히 벌줌.
- **함정(반드시 방어): 순진한 perr-최소는 퇴화해를 상위로 올림.** 3채널 검증에서 드러남 —
  ANs 1·2·3등이 3ppb 붕괴, PNs 1등 194ppb(정상 98의 2배). "정확히 2배"(94↔188) = 계통적 레퍼런스 degeneracy.
  핫에서 더 심함(ANs 42/64, PNs 23/64, Cold 18/64 퇴화).
- **방어책 = 컨센서스 앵커**: 창×차수 다수결의 1x 농도를 **반복 median**(전체median으로 [0.5x,1.5x] 밴드→그 안 median)으로
  잡고, **컨센서스에서 >50% 벗어난 셀은 하드게이트**(off_consensus). 이걸로 3채널 다 정상클러스터가 상위로 올라옴. ✅
- **미해결 편향**: `perr_rel ∝ 1/폭` (넓은 창 선호 편향). 원인 = 잔차 강한 자기상관(|ac1|~1.0)→perr가 독립가정으로
  불확실도 과소평가. 대응 = perr를 √폭으로 정규화. (창 고정 방향으로 가면 이 이슈 완화)

### ★2-B. 신뢰 3계층 (2026-07-22 확립 — 목적함수의 핵심 교훈)
**§2의 "모델 내부 신호만" 방침은 그 자체로 불충분하다.** O4 사례가 증명(§12):
- **T1 자기일관성** (안정성·perr·잔차백색도·컨센서스) — **과적합으로 만족시킬 수 있다.**
  "진짜 좋은 핏"과 "크러치로 떠받친 자신있게 틀린 핏"이 T1 눈엔 동일. **심판으로 쓰면 안 됨**(필요조건일 뿐).
- **T2 핏의 물리 건전성** (외부데이터 불필요) — 과적합 크러치를 잡는 실제 심판:
  1. **차등 공선성**(poly 제거 후 |r|·다중상관). raw 상관(health_checks, 문턱0.98)은 광대역 모양이 지배해
     DOAS degeneracy를 못 잡음 → **반드시 차등으로**. `core/fit_physics.differential_collinearity`.
  2. **계수 상수성** (O4처럼 물리적으로 상수여야 하는 종). ⚠️**단독 사용 금지 — 블라인드스폿**:
     상수 아티팩트(콜드 고정패턴)를 흡수해도 계수가 상수로 나와 속는다.
  3. **★절대량 앵커**(결정타): fitted N을 물리 이론값과 대조. O4는 이론값을 아는 유일한 종([O2]²)이라 최적.
- **T3 외부 진실** (경로·보정 독립): ZA/He 인젝션, 크로스채널 일치, 알려진 농도.
**결론: T2(특히 절대량) 없이는 목적함수가 과적합을 상 준다. T1은 물리적으로 유효한 후보들 사이 tiebreaker로만.**

## 3. 사용자 실제 FitSet (baseline, 최적화 출발점)
경로: `C:\Doasis_Work\Output\fit setting\FitSet_*.json`
- **Cold**: 438-465.8nm / Poly4 / shift bounds(-1,1)
- **ANs** (hot ch1, 300°C): 429.7-466nm / Poly4 / shift(-10,0.5)  ← 비대칭
- **PNs** (hot ch2, 180°C): 444.1-470.6nm / Poly3 / shift(-5,5)
- **refs = CHOCHO · H2O · NO2** (**O4 없음!**). H2O multiplier 지수 = -12 (→1e-12).
- 채널정체성: **ch1=ANs, ch2=PNs** (ANs=CH1−CH2). `hot-channel-swap-ans-2026-06` 참조.

## 4. 헤드리스 엔진 빌드 (GUI 없이 핏 돌리려면 필수)
GUI와 **동일하게** 빌드해야 결과가 일치. app_window의 `_build_engine_from_config` 복제:
- wavecal **파일**이 파장축 (`_load_wavecal_array`)
- `engine.add_reference(name, filepath, wave_nm=wave, multiplier=10.0**mult)` — **mult=10^지수** (H2O -12→1e-12)
- `engine.apply_ils_convolution(0.0)`
- ⚠️ `residual_compare.build_engine`과 **다름**(그건 Calib→alpha resample 방식). 실제 핏은 위 방식.
- 엔진: `core/engine.py` — `gas_list`, `scaling_factors`, `multipliers`, `interpolators[name]`, `add_reference()`.

## 5. 핏 엔진 & 세팅 knob이 사는 곳
- **핏 실행/결과**: `gui/worker.py` (AnalysisWorker). 스캔당 result dict 생성.
  - worker 속성(=knob): `fit_unit`, `fit_lo_nm`, `fit_hi_nm`, `step_limit`(shift step),
    `tikhonov_lambda`, `use_robust_fitting`, `allow_negative_gas`, `qc_enabled`, `qc_rms_abs`,
    `qc_snr_min`, `kalman_q`, `kalman_r`, `tz_offset_sec`, gas온도.
  - Reference constraints: Sh/Sq bounds (Properties 다이얼로그, 가스별 shift/squeeze 정책+크기).
- **VarPro 핏 코어**: `core/doas_fit.py` — `_execute_varpro_fit` → `perr_lin=√diag(cov)`, `c_perr`(가스별 오차), `best_ep`.
- **Setup UI/config 수집**: `gui/app_window.py` — `spin_fit_start_nm`/`spin_fit_end_nm`, `spin_poly_deg`,
  `spin_step_limit`, QC 컨트롤(`chk_qc`/`spin_qc_k`/`spin_qc_rms`/`spin_qc_snr`), Kalman spin,
  `chk_allow_neg`, **`chk_settle`/`spin_settle_n`**(정착 스캔 제외, 이번 세션 추가). 재핏없이 후처리 = `reapply_qc`→`_apply_auto_qc`.

## 6. result dict (핏 품질 평가에 쓸 컬럼) — worker.py:598~695
스캔당: `RMS`, `Shift`, `Squeeze`, `Chi2`(축소, >1이면 잔차구조 잔존), `DOF`, `SNR`, `_signal_mean`, `Status`(OK/Recovered/Unstable).
가스별 `nm`(ppb_raw), `nm_Smooth`(칼만), **`nm_Error`(1σ)**, `nm_TotalError`(T/P전파), `nm_MDL`(3σ), `nm_Shift`, `nm_Squeeze`.
→ **최적화 목적함수 재료**: Chi2(백색도), nm_Error/perr(불확실도), nm(농도 안정성), 잔차 자기상관(직접 계산 필요), Status율.

## 7. 산출물 사전검증 (이번 세션 추가 — 옵티마이저의 ★★ reference/wavelength 검증에 직결)
**`core/health_checks.py`** (NEW, 순수함수 → `(status, msg, metrics)`):
- `check_wavecal(wl, anchors, tol_nm, expect_range)` — 단조·범위·분산·Hg앵커
- `check_references(refs, wl, collin_warn)` — 존재·비퇴화(평평 감지)·격자·**공선성**(쌍별|상관|, degeneracy 조기감지!)
- `check_rayleigh()` — σ_ZA 문헌 골든값 정합(King회귀 감지, 데이터 불필요)
- `check_r(npz_path, band, d_cm)` — R·Leff 물리성·물리불가 knot
- `overall(results)` — FAIL>WARN>PASS 집계 판정
→ **공선성 체크가 §2의 degeneracy 함정을 사전에 잡을 수 있음.** 옵티마이저가 후보 refs셋 평가 전 게이트로 활용 가능.
(관련: `tools/validate_pipeline.py` = 코드회귀용 CLI, 같은 로직 일부. GUI Health 대시보드는 계획만·미착수.)

## 8. 데이터 무결성 헌장 (filtering-philosophy, 항상 먼저)
미량기체(ppb·ppt) 연구 → **과필터링·가공 금지.** 8계명 요지:
①지우지말고 flag ②바뀌는 %를 숫자로 ③입증책임은 빼는쪽 ④물리>통계 ⑤계통오차가 더 무섭다
⑥스무딩=화장, raw 같이 ⑦검증≠필터 ⑧오제거율 먼저. **over-removal > under-removal 죄.**
→ 옵티마이저는 "잔차 줄이려 정보 죽이는" 세팅을 상 주면 안 됨(§1-B가 이 정신).

## 9. 데이터/경로
- 알파: `C:\Doasis_Work\Output\alpha` (2048 single-column, bin당1파일, 일별폴더)
- 골든 콜드 구간: **05-26~06-13** (r 0.96). 06-17 등은 무효(shift Fix 0). `cold-date-alignment-audit-2026-07`.
- 핏 결과: `C:\Doasis_Work\Output\fitting\{YYMMDD-YYMMDD}\{neg}\{QC}\...dat`
- R npz: `C:\Doasis_Work\Output\R\R_*.npz`
- wavecal: `C:\Doasis_Work\Output\wv_cal\...`
- FitSet json: `C:\Doasis_Work\Output\fit setting\FitSet_*.json`

## 10. 현재 상태 & 다음 스텝  ← **여기부터 읽으면 방향 잡힘** (갱신 2026-08-04)

### 10-A. 무엇이 되는가 (동작 확인됨)
```bash
python tools/build_fitset.py cold|ans|pns   # ★맨바닥 FitSet 자동생성 (세팅 입력 0)
python tools/design_window.py  cold|ans|pns # 핏창·poly 사전설계 (핏 없이)
python tools/optimize_params.py cold|ans|pns# 기존 FitSet 기준 파라미터 최적화
python tools/t2_reference_check.py cold     # 레퍼런스 물리 심판(O4 판정)
```
`build_fitset`이 최상위 진입점 — 웨이브칼+`Ref_*.dat`+알파만으로 `scenarios/AutoFitSet_*.json` 생성.
자동 결정: **refs 취사 · mult · 핏창 · poly · shift/squeeze 정책+크기 · step_limit · Link**.
사용자 몫(자동화 제외, 합의됨): `t_ref` · `t_coeff`(dσ/dT) · `active_bands_nm`.
원칙 고정(최적화 금지): Neg · QC · Tikhonov · Robust · Kalman.

### 10-B. 모듈 지도
| 파일 | 역할 |
|---|---|
| `core/fitset_builder.py` | **오케스트레이터**(2패스) + `validate_fitset`(불변식) + `derive_mult` |
| `core/window_designer.py` | 핏창·poly 사전설계(c-optimality MDL·chi·shift 사전추정). **핏 안 함** |
| `core/param_optimizer.py` | shift/squeeze/step_limit/Link. **`_seed_shift` 필수**(§13-E) |
| `core/fit_physics.py` | T2 물리 심판(차등공선성·계수상수성·**절대량 앵커**) |
| `core/doas_fit.py` | VarPro 핏 엔진. **Center 모드 + 교집합 공백 가드**(§16) |
| `core/fit_optimizer.py` | 구 Stage1(핏레인지 perr 탐색). **폐기·참고용**(§1 방향전환) |

### 10-C. 다음 스텝 (우선순위)
1. **Test Fit 버튼 이식** — 기존 `_test_fit`(app_window.py:3135) / `_show_test_fit_popup`(:3261)을
   탭 구조로: **탭1 최적화 결과 + [적용]**, **탭2 1스캔 미리보기 존치**(사용자 지시).
   워커 스레드 + 진행바 필수(표본 12스캔에 수십 초). 자동 적용 금지 — 사람 승인(§15-E 불변식4).
2. **ANs 퇴화 분기 추적** — ANs 스캔 상당수가 95ppb/RMS19.6% 분기에 앉는다(§16-B). 사용자 실측에 직접 영향.
3. **T3 진짜 검증** — 생성 세팅으로 실제 핏 → NO2 인젝션·채널 간 일치로 대조. (인젝션 예정)
   ⚠️현재 "성능"은 **사용자 수동값과의 일치**로 잰 것이라 순환논리(§15-F).
4. ~~웨이브칼 검증(`core/health_checks.py`)을 생성기에 연결~~ — **완료(2026-08-13)**. `build_fitset()`이
   엔진 구성 직후 `check_wavecal`+`check_references`를 후보 refs셋 평가 *전* 게이트로 돌린다
   (FAIL이면 예외로 생성 중단). 연결하며 실측으로 `check_references`의 진짜 버그를 하나 잡음 —
   절대 std 문턱(1e-30)이 O4(피크~1e-46, 충돌유도흡수)를 전부 "평평(퇴화)"으로 오판하고 있었다
   (std/peak 비율은 CHOCHO·H2O와 같은 급이었는데도). 자기 피크 대비 **상대** std로 고쳤다 —
   `tools/test_health_checks.py`에 회귀 테스트 있음.
5. 콜드 ill-posed 근본원인 — NO2 인젝션 후 판단(사용자 보류). 핫보다 콜드가 높은 이유도 미상.

### 10-D. 이 문서 읽는 순서
**§15(명세) → §2-B(신뢰 3계층) → §16(Center 모드) → §14(맨바닥 생성) → §13(하네스 함정)**
나머지(§12 O4 판정, §11)는 배경.

## ★12. O4 판정 — 종결 (2026-07-22)
**질문**: 사용자가 FitSet에서 O4를 뺀 게 옳은가(사용자 주장: O4가 과적합시킴). **결론: 사용자가 옳다. O4 제외 유지.**

증거 사슬:
1. **O4 넣으면 콜드 NO2가 4.7ppb(CV 874%) → 86ppb(CV 20%)로 "안정화"** — T1만 보면 "O4 넣어라"가 나옴(함정).
2. T2-차등공선성: NO2↔O4 |r|=0.34 (낮음) → 단순 NO2/O4 줄다리기는 **아님**.
3. T2-상수성: O4 계수 CV 3% (거의 상수) → **"진짜 O4처럼 보임"으로 오판**. ← 블라인드스폿
4. **★T2-절대량(결정타)**: NO2를 86ppb로 읽는 동일 변환식에서
   `fitted N_O4 = 5.8e39` vs `예상 [O2]² = (0.2095·n_air)² = 2.5e37` → **229배**(범위 161~238).
5. **더 결정적**: 알파 헤더 `I0_mode=PCHIP ZA_count=749` — **I0가 ZA(제로에어=O2 포함 공기)**.
   R 보정이 ZA↔He Rayleigh 대비로 나오는 것 자체가 ZA=공기라는 증거. 그러면 O4 흡수는
   ambient·ZA 양쪽에 동일하게 있어 **α에서 상쇄** → **α 안의 정당한 O4 신호는 ~0이어야 함.**
   0이어야 할 자리에 229배 → 경로·R·보정 가정 없이 **아티팩트 흡수 확정.**

메커니즘(전부 정합): 창 438-466에서 O4 밴드는 피크의 **8%뿐**(σ 5.1e-47 vs 피크 6.5e-46) → 쓰려면 계수를
크게 → **콜드 고정패턴**(`cold-residual-fixed-pattern-2026-06`, fixed/random=73)을 스펀지처럼 흡수 →
그 패턴이 상수라 O4 계수도 상수(CV 3%)로 나와 상수성 체크를 속임.

**부수 발견(중요)**: O4 없이 콜드 NO2가 불안정(CV 874%)한 건 "O4가 필요해서"가 **아니라 콜드 기저가
원래 미결정**이기 때문. O4는 가짜 처방이었고 **진짜 문제(콜드 핏 ill-posed)는 미해결로 남음.**
→ 사용자 판단(2026-07-22): **NO2 인젝션 실험 후에 판단. 일단 보류.** (핫보다 콜드 농도가 높은 이유도 미상.)

### ★12-B. 자동화 완료 + 두 기준의 상보성 (실측 검증)
`fit_physics.theoretical_amount`/`retrieved_amount` 추가 → `fitted_amount_health.abs_ratio` →
`judge_reference`에 `impossible`(abs_ratio > `abs_max_ratio`=3.0) 게이트 통합. **툴이 사람 개입 없이
O4를 기각**(판정이 "포함 타당"→"제외 권고"로 뒤집힘). 3채널 회귀:

| 채널 | 절대량비 | O4 계수 CV | 기각한 기준 |
|---|---|---|---|
| Cold | **229배** ❌ | 3%(정상처럼 보임) | **절대량** |
| PNs | **294배** ❌ | 27% | 절대량 + 상수성 |
| ANs | 1.5배 ✅ | **187%** ❌ | **상수성** |

**★두 기준은 상보적 — 어느 하나만으론 3채널을 다 못 잡는다.** Cold=상수 스펀지(고정패턴 흡수→상수성이 속음,
절대량이 잡음), ANs=출렁이는 스펀지(절대량 멀쩡→상수성이 잡음). **둘 다 유지할 것.**
(부수: ANs는 타깃 NO2 자체가 CV 179% — ANs 퇴화 문제의 재확인.)

### 인젝션 플래그 (T3 앵커용)
`core/data_io.py:655` — raw col 4 = state flag: **`1`=Ambient, `500~503`=ZA, `510~513`=He**.
`data_io.read_scans_via_dataio(fp, channel)` → `(za, he)` 블록 반환.
⚠️ **알파 export엔 ZA/He가 안 남음**(ZA는 I0로, He는 R로 소비). ZA/He를 직접 핏하려면 알파를 따로 생성해야 함.
He는 O2를 밀어내므로 **진짜 O4라면 He에서 0이 되어야 함** — 향후 T3 검증에 쓸 것.

## ★13. 하네스 검증 + 파라미터 최적화 1차 결과 (2026-07-22)

### 13-A. ⚠️ FitSet json 필드 불일치 (하네스 버그의 원인, 반드시 주의)
FitSet json에서 **`f_min`/`f_max`(px)와 `fit_start_nm`/`fit_end_nm`이 서로 안 맞는다.**
앱 저장 결과 헤더(`# Fit Range: Pixel 774-1550 (438.4-475.8nm)`)로 확인 → **px 필드가 진짜**,
nm 필드는 스테일(`fit_unit`이 "nm"여도). cold: px774-1550=438.4-475.8nm ≠ nm필드 438.0-465.8.
→ nm 필드를 쓰면 적색단 10nm를 잘라먹는다. **항상 `f_min`/`f_max`(px)를 쓸 것.**

### 13-B. ★앱 실측 정답지 (헤드리스 검증 기준)
`Output/fitting/{config}/{YYMMDD}/neg_o/QCoff/*.dat` = 앱이 저장한 실제 핏. 260526 cold(n=1404):
`NO2 median=**3.47ppb**(-0.04~15.4), NO2_Error 0.057, NO2_Shift=**-0.5 고정**, CHOCHO 0.095, H2O ~7.7e-13`
→ **내 헤드리스(px774-1550)는 NO2 3.9ppb — 일치. 하네스 검증됨.**
**★콜드 NO2의 진짜 값은 ~3.5ppb(대기값으로 정상).** O4 넣었을 때의 86ppb·메모리의 154ppb는
전부 **부풀려진 값** → §12 O4 판정을 독립적으로 재확증.

### ★13-E. shift 시딩 누락 = 하네스 버그 (13-C를 뒤집음, 반드시 유지할 것)
**DOAS의 shift 지형은 레퍼런스가 진동해 비볼록**이다. x0=0에서 `least_squares`만 돌리면 멀리 있는
진짜 최소를 못 찾고 0에 주저앉는다 → "shift 미결정"이라는 **오진**이 나왔다(13-C는 이 오진의 산물).
앱은 스캔간 `last_valid_shift`를 이어받아 step_limit씩 걸어가므로 도달하지만, **표본 스캔은 시간연속이
아니므로 반드시 스캔마다 전역 격자탐색으로 시드**를 잡아야 한다(`param_optimizer._seed_shift`,
seed_range 15px·step 0.25). `DoasFitter.pre_calibrate`는 ±0.5 국소격자라 여기선 부족.

**시딩 후 앱 실측과 일치(하네스 검증):**
| 채널 | 내 하네스 | 앱 실측 | |
|---|---|---|---|
| ANs | −5.38±0.74 | −4.95 | ✓ |
| PNs | −1.38±0.56 | −1.37 | ✓ |
| cold | **−0.87**±0.19 | −0.5 | ⚠️**앱이 bound에 잘림** |

부수효과: 잔차가 훨씬 희어짐(|ac1| ANs 0.73→0.19, PNs 0.36→0.03) = 핏 자체가 개선.

### ★13-F. 실사용 발견 — 콜드 shift bound가 too tight
콜드 실제 shift ≈ **−0.87px**인데 설정이 `sh_val -1,1` + `step_limit 0.5` → **−0.5에서 잘림.**
앱 결과의 `Shift=-0.5 고정`은 측정값이 아니라 **경계에 박힌 것**. 핏이 최적점에 도달 못 하는 중.
→ **콜드 step_limit을 늘려야 함**(≥1.0). 옵티마이저가 찾아낸 첫 실사용 개선점.

### 13-C. (폐기됨 — 13-E 참조) shift는 실제로 '미결정'이다
bounds를 ±15로 열어도 핏이 x0에서 **한 발도 안 움직임**(shift 0.00±0.00, squeeze 1.00000±0.00000).
앱도 마찬가지로 **-0.5 경계에 박혀 있음**(측정된 값이 아니라 bound). 타깃 신호가 약해서(3.9ppb)
shift를 제약하지 못하는 것. → `recommend_shift`에 **미결정 감지** 추가: 좁은 Limit을 추천하면
"측정된 척"하는 거짓말이 되므로 **Fix 권고 + 사유 보고**. `recommend_step_limit`도 Δ가 전부 0이면
"step_limit 무의미"로 보고.

### 13-D. cold 파라미터 1차 추천 (px774-1550, refs=CHOCHO/H2O/NO2)
- **poly: 3** (현재 4). NO2가 poly3·4에서 3.9로 동일 → 더 낮은 차수로 충분(절약).
  ⚠️ poly **2와 8은 90.6ppb 퇴화 분기**로 빠짐(|ac1|→1.0) — 무릎점 로직이 회피함.
- **NO2 shift: Fix** (데이터가 결정 못 함) / **squeeze: Fix 1.0** / **step_limit: 무의미**
- **CHOCHO·H2O: Link 유지** (독립시켜도 잔차 이득 0%)
- 범위 결정: **T_ref·dσ/dT·active band는 사용자 설정 영역**(자동화 대상 아님, 사용자 지정 07-22).

## ★14. 맨바닥 FitSet 자동생성 — 완성 (2026-07-22)
**요구 재확인**: "레퍼런스·웨이브칼·알파만 넣으면 **아무 세팅 없이** 최적 핏세팅이 나오는 프로그램."
→ `core/fitset_builder.py` + `tools/build_fitset.py`. 세팅 입력 0, 사용자 FitSet 참조 0.
출력 = 앱이 그대로 읽는 FitSet json (`scenarios/AutoFitSet_*.json`).

파이프라인(2패스: 창↔ref 닭-달걀 해소):
`Ref_*.dat 발견 → mult 자동 → 1패스 임시창 → ref 취사(F검정+물리) → 2패스 최종창·poly → shift/squeeze/step/Link → json`

### 14-A. 자동 도출된 것들 (핵심 알고리즘)
* **`mult`(10^지수) = decade(floor) 정렬**: `-floor(log10(peak)) + floor(log10(target))`,
  target=1e-19(일반)·1e-46(O4). **3채널 전부 사용자 수동값과 정확히 일치**(NO2 0·CHOCHO 0·H2O −12).
  ⚠️ratio의 round를 쓰면 6.99e-19에서 한 자릿수 틀린다(−1).
* **ref 취사 = F-검정**(고정 퍼센트 문턱 금지): `F=((RSS_wo−RSS_w)/Δp)/(RSS_w/dof)`,
  **dof는 AR(1) 유효표본수** `n·(1−ρ)/(1+ρ)`. 문턱 퍼센트를 쓰면 1.7% vs 2%로 결정이 뒤집혔다(cold에서
  CHOCHO·H2O가 통째로 빠짐). F>10이면 실재 흡수체 → 포함. **빼는 쪽이 입증책임(헌장③)** — 타깃 MDL만
  보면 실재 흡수체를 빼서 편향을 만든다.
* **창·poly**: 창을 **먼저** 고르고(각 창의 최선 poly로 창끼리 비교) **그 창 안에서** poly 절약선택(8% 이내
  최소 차수). ⚠️창을 가로질러 절약선택하면 MDL 스케일이 섞여 엉뚱한 高poly가 뽑힌다(PNs poly8 실측).
  poly 하한 휴리스틱(min_poly_for_broadband)은 과해서 폐기 — 편향은 `chi`가 직접 잰다. 후보 2..9 고정.
* **`step_limit` = 부호있는 드리프트 기반**: `|median(signed Δshift)|×3`, floor 0.5.
  ⚠️`|Δshift|` 크기를 쓰면 **스캔마다 독립 시딩된 추정 잡음**을 드리프트로 오인해 과대(실측 3.95 vs 정답 0.5).

### 14-B. 성능 (사용자 수동 설정 대비, 맨바닥 생성)
| 항목 | cold | ANs(roi1) | PNs(roi2) |
|---|---|---|---|
| refs | ✅일치 | ✅일치 | ⚠️CHOCHO 제외(F=2.9=신호 미약) |
| mult | ✅일치 | ✅일치 | ✅일치 |
| 핏창 | 448-474 / 사용자 438.4-475.8 | ✅429.0-466.0 / 429.5-462.0 | 439-468 / 444.1-470.6 |
| poly | 3 / 4 | 3 / 4 | 2 / 3 |
| step_limit | 0.75 / 0.5 | ✅0.5 / 0.5 | 0.75 / 0.5 |
| NO2 shift | [−7,6] / [−1,1] | ✅[−9,−1.5] / [−10,0.5] | [−6,4] / [−5,5] |
**ANs가 최고 정합** — 자동 창 429.0-466.0이 사용자 json의 **nm 의도값(429.7-466.0)과 일치**
(실제 런은 px필드 429.5-462.0이라 적색단 4nm 손실 중 = §13-A 불일치의 실증).
poly는 일관되게 사용자보다 1 낮음(절약선택 성향). shift bounds는 자동이 **실측 분포에 맞춰 더 타이트**.

### 14-C. ★O4가 남긴 교훈의 결정판
cold에서 O4는 **F=243.5, RSS 44.4% 감소** — 통계적으로 전 후보 중 압도적 1위.
그런데 **절대량 89배**로 물리가 기각. → **통계(T1)를 심판으로 쓰면 반드시 과적합을 상 준다**(§2-B)의
가장 선명한 실증. 물리 게이트가 통계를 이겨야 한다.

### 14-D. ⚠️FitSet json의 data_label이 뒤바뀌어 있음
파일상 채널1='PNs'/채널2='ANs'이지만 **실제는 채널1=ANs, 채널2=PNs**(사용자 확인 2026-07-22, json이 틀림).
→ 툴은 **라벨이 아니라 wavecal 경로(roi1/roi2/cold)로 채널을 매칭**할 것. 라벨로 찾으면 roi1 창에 roi2
알파를 대조하는 사고가 난다(실제 발생).

## ★15. 알고리즘 명세 (2026-07-22 정립) — **구현 전 이 절을 먼저 읽을 것**
> 이 프로그램은 세션 내내 "터지면 고치는" 식으로 아래에서 위로 만들어졌고, 발견은 쌓였지만
> **일관된 명세가 없었다.** 그 결과 "생성물이 엔진에서 실행 가능해야 한다"는 당연한 불변식이
> 빠져 실행 불가한 세팅을 내보냈다(§15-E). 이 절이 그 명세다.

### 15-A. 목표함수 (한 문장)
> **농도가 (창·차수를 바꿔도) 안 움직이고, shift가 물리적으로 안정하며, 잔차가 흰 상태를
> 만드는 "가장 단순한" 세팅.** 잔차 RMS 최소화가 **아니다**.

### 15-B. 심판 계층 — 우선순위가 절대적
| 계층 | 내용 | 역할 |
|---|---|---|
| **T3 외부 진실** | ZA/He 인젝션, 알려진 농도, 채널 간 일치 | **최종 심판**(있으면 항상 우선) |
| **T2 물리 건전성** | 절대량 앵커 · 계수 상수성 · 차등 공선성 | **실무 심판**(외부데이터 불필요) |
| **T1 자기일관성** | MDL·perr·잔차 백색도·안정성·F검정 | **후보 생성·tiebreaker 전용** |
**★규칙: T1은 절대 단독 심판이 될 수 없다.** 실증 — cold에서 O4는 F=243·RSS 44%↓로 **통계 1위**였으나
절대량 89배로 T2가 기각(§14-C). 통계를 심판으로 쓰면 반드시 과적합을 상 준다.

### 15-C. 결정 순서 (의존성이 순서를 강제)
```
① mult          ← 레퍼런스 파일만 (다른 무엇에도 의존 안 함)
② 정렬 shift0   ← ①  (창·poly 평가의 전제. 안 맞으면 chi가 '미모델 구조'로 오진 §13-E)
③ 임시 창       ← ①②  (ref 취사를 하려면 창이 있어야 함)
④ ref 취사      ← ③   (F검정 + T2 물리 게이트)
⑤ 최종 창·poly  ← ④   (확정 ref 세트로 재설계)
⑥ shift/squeeze ← ⑤   (넓게 풀어 실측 분포 → bounds)
⑦ step_limit    ← ⑥   (연속 스캔의 부호있는 드리프트)
⑧ Link 판정     ← ⑤⑥
⑨ 불변식 검사   ← 전부  (실패 시 출력 금지)
```
③↔④는 닭-달걀이라 **2패스**로 끊는다.

### 15-D. 항목별 결정 규칙
| 항목 | 입력 | 규칙 | 금지 |
|---|---|---|---|
| `mult` | ref 피크 | **decade(floor) 정렬** `-floor(log10 peak)+floor(log10 target)` | ratio의 round(한 자릿수 틀림) |
| ref 취사 | RSS(넣기 전/후) | **F검정**, dof=AR(1) 유효표본 `n(1−ρ)/(1+ρ)`, F>10 → 실재 흡수체 포함 | 고정 % 문턱(1.7 vs 2%로 뒤집힘) |
| ref 물리기각 | 절대량·계수CV | 이론 상한 3배 초과 **또는** 상수여야 할 종이 출렁 → 제외 | T1만으로 포함 결정 |
| 핏창 | MDL·chi·robust | 창끼리 먼저 비교(각 창의 최선 poly로) | 창 가로질러 poly 절약선택 |
| `poly` | 같은 창의 사다리 | 최선 대비 8% 이내 **최소** 차수 | MDL 최소만(계속 올라감) |
| shift 크기 | 넓게 푼 실측 분포 | median ± 4σ → **0 포함하도록 확장**(15-E) | blind 그리드 |
| squeeze 크기 | 넓게 푼 실측 분포 | median ± 4σ. 1.0에서 안 움직이면 Fix | 시딩 없이 판단(Fix 오진) |
| `step_limit` | 연속 스캔 | **부호있는** 드리프트×3, floor 0.5 | `|Δshift|`(추정잡음을 드리프트로 오인) |
| Link | 독립 시 잔차 이득 | ≥5% 이득 **and** shift 안정 → 독립, 아니면 Link | 기본 독립(절약 위배) |
| T_ref·dσ/dT·active band | — | **사용자 몫**(물리·화학 판단) | 자동 결정 |
| Neg·QC·Tikhonov·Robust·Kalman | — | **원칙 고정**(기본 OFF/정책) | 최적화 대상화 |

### 15-E. ★불변식 (생성물이 반드시 만족 — `fitset_builder.validate_fitset`)
1. **실행 가능성**: 워커는 `last_valid_shift=0`에서 시작해 step_limit씩 걸어가고
   `setup_fit_parameters`는 `[전역범위] ∩ [center±step_limit]`를 쓴다 →
   **shift 범위는 0과 교집합이 있어야 한다.** 없으면 첫 스캔에서
   `least_squares: Each lower bound must be strictly less than each upper bound` 크래시.
   실측: `[-9,-1.5]`+step 0.5 → bounds `[-0.5,-1.5]` → 사망. **0까지 확장해 걸어 들어가게 한다.**
   (근본 해결 = 측정 shift를 시작 중심으로 쓰는 **Center 모드**. 엔진 수정 필요, 미구현.)
2. 상하한 역전 금지(shift·squeeze).
3. 핏창 ≥50px, 타깃이 ref_props에 존재.
4. **자동 적용 금지** — 추천 + 근거(변화 %)를 제시하고 사람이 승인(헌장②).

### 15-F. 알려진 한계
* 성능 측정을 "사용자 수동값과의 일치"로 했는데 **사용자 값이 정답이라는 보장이 없다**(순환논리).
  진짜 검증 = 생성 세팅으로 실제 핏 → **T3**(NO2 인젝션·채널 간 일치)로 대조. 미완.
* `F>10`, `8% 절약`, `4σ`, `3배 절대량`은 여전히 튜닝 상수다(다만 통계적/물리적 의미는 있음).
* 웨이브칼 검증(`health_checks`)의 생성기 연결은 **완료**(§10-C.4 참조).
* etalon 주파수 탐색대역 `0.02~0.40` 하드코딩, 미검증.

## ★16. Center 모드 구현 (2026-07-22) — §15-E 불변식1의 근본 해결
**문제**: `Limit`은 허용창을 `initial_shift_center ± step_limit`로 잡고 워커는 항상 **0에서 출발**한다
(worker.py:300). 그래서 0에서 먼 실제 shift(핫 −5.25px)를 쓰려면 범위가 0을 품어야 했고, 그만큼 느슨해졌다.
**실측: `Limit -10,0.5`+step0.5로 0에서 출발하면 8스캔 내내 shift가 +0.00에 주저앉아 못 걸어간다**
(DOAS shift 지형이 비볼록이라 0이 국소최소).

**해결**: `sh_mode="Center"`, `sh_val="중심, 반폭"`. 허용창을 **선언된 중심**에 앵커한다.
- `core/doas_fit.py setup_fit_parameters` — Center 분기 추가. 스캔간 연속성 유지(이전 shift가 창 안이면
  그걸 중심으로 이어가고, 창 밖(첫 스캔의 0)이면 선언 중심에서 시작).
- **교집합 공백 가드 추가**: 예전엔 `[-9,-1.5]`+center0+step0.5 → bounds `[-0.5,-1.5]` →
  `least_squares: lower bound must be strictly less than upper bound`로 **크래시**했다.
  이제 허용범위 쪽으로 한 스텝 다가간 창을 줘 걸어 들어가게 한다(비파괴).
- `gui/ref_properties_dialog.py` — 콤보에 "Center" 추가(shift 전용, 스택 페이지 4). squeeze는 1.0 기준이라 제외.
- `core/fitset_builder.py` — `use_center_mode=True`(기본)면 Center로 출력. `validate_fitset`은 Center를
  0-교집합 불변식에서 면제(중심 앵커라 항상 유효).

**검증**: ANs 260703, 0에서 시작 → `Center -5.25,3.75`가 **첫 스캔부터 −4.75 도달**(앱 실측 −4.95),
NO2 3.60ppb·RMS/sig 3.9%. 같은 조건 `Limit -10,0.5`는 0에 갇힘. **회귀: validate_pipeline 4 PASS·0 FAIL.**
Limit 경로는 기존 동작 불변(여러 케이스 대조 확인).

### ★16-B. 퇴화 분기는 잔차로 식별된다 (중요)
ANs 260703 scan1, shift를 Fix로 고정하며 스캔:
| shift | NO2 | RMS/sig |
|---|---|---|
| −7.0 ~ −6.0 | **95.9** | **19.6%** ← 퇴화 분기 |
| −5.5 ~ 0.0 | 3.2~3.6 | 3.6~8.3% ← 진짜 해 |
**퇴화 분기는 잔차가 5배 나쁘다 → 식별 가능.** 그리고 진짜 분기 안에서 NO2는 3.2~3.6으로 안정(shift 민감도 낮음).
squeeze는 ±0.005 범위에서 NO2에 영향 없음(3.59~3.61).
⚠️단, 8스캔 연속 실행 시 median이 94ppb로 나온 적 있음 = **ANs 스캔 상당수가 퇴화 분기에 앉는다**
(ANs NO2 CV 179%·창 42/64 퇴화와 일관). **코드가 아니라 ANs 자체 문제** — 별도 추적 필요.
→ 시딩(격자 RMS 최소)이 이 분기를 피하는 실질적 방어. `param_optimizer._seed_shift`가 그 역할.

## 11. 부록 — 2026-06-30 세션에 바뀐 것 (배경, 우선순위 낮음)
핏 파이프라인/최적화와 무관하지만 코드가 바뀐 것들: Plot Maker 대폭 강화(색·스타일·에러밴드·야간음영·주석·커서·범례·템플릿·서브플롯),
정착 스캔 제외 체크박스(`chk_settle`), Result Lab 계산기(`dlg_calculator`), α Health Fit-window 버튼, **`core/health_checks.py` 신설**.
→ 옵티마이저 관점 유효: `health_checks`(§7), `chk_settle`(§5 QC default), settling 저편향(`settling-scan-bias-and-tool-2026-06`).
