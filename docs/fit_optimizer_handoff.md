# CAESAR Pro — 핏세팅 최적화 프로그램 핸드오프

> 다른 세션이 이 문서 하나로 맥락을 잡고 이어가도록 정리. 작성 2026-06-30.
> 저장소: `C:\Doasis_Work\CAESAR\CAESAR` (중첩 CAESAR 폴더 주의).
> 관련 메모리: `fit-optimizer-stage1-2026-07`, `filtering-philosophy`,
> `hot-channel-swap-ans-2026-06`, `cold-residual-fixed-pattern-2026-06`,
> `settling-scan-bias-and-tool-2026-06`.

---

## 0. 한 줄 목표
채널별 핏세팅(핏시나리오)을 자동 최적화. **목표 = 농도가 안 움직이고(농도불변) · shift가 물리적으로
안정하며 · 잔차가 흰(white) 상태를 만드는 "가장 단순한" 세팅** (Occam + 데이터 무결성 헌장).
잔차 RMS 최소화가 목표가 **아님** — 그러면 poly↑·창잘라먹기·shift다풀기로 수렴해 농도가 물리적으로 깨짐.

## 1. 현재 채택 방향 (★중요, 2026-07-21 방향전환)
- **핏레인지 자동탐색은 폐기.** perr(핏 불확실도)가 물리를 몰라 창을 480/422nm로 스프롤 → 실제 창(438-466)과 안 맞음.
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

## 10. 착수 상태 & 다음 스텝
- 기존 파일: `core/fit_optimizer.py`(Stage1 핏레인지+poly, 방향전환으로 참고용), `tools/optimize_fitrange.py`(CLI),
  `tools/residual_compare.py`(load_alpha/build_engine — ⚠️§4대로 실제 핏 빌드와 다름, 주의).
- **NEW (2026-07-22)**:
  - `core/param_optimizer.py` — `fit_scan`(shift/squeeze/계수 반환) · `evaluate` · `optimize_poly`(무릎점)
    · `recommend_shift`(넓게풀어 분포로 bounds 결정) · `recommend_secondary_link`(Link vs 독립).
  - `core/fit_physics.py` — **T2 물리 심판**: `differential_collinearity` · `fitted_amount_health` · `judge_reference`.
  - `tools/optimize_params.py` — FitSet json baseline CLI(§4 엔진빌드 복제 포함). `tools/t2_reference_check.py` — O4 판정 CLI.
- **결정**: 기존 **Test Fit 버튼을 이 최적화 기능으로 대체**(사용자 지시 2026-07-22). 기존 핏 실행·플롯 로직 재활용.
- 미해결: ①param_optimizer에 **T2 절대량 앵커 통합**(현재 judge_reference는 공선성+상수성만 — §2-B 3번 미반영)
  ②Test Fit 버튼 이식 ③**콜드 핏 ill-posed 근본원인**(O4 제외 시 NO2 CV 874% — 진짜 문제, §12 부수발견)
  ④ANs 2/3 퇴화 근본원인.
- **PoC 증명됨**: 맨바닥 창생성은 design-driven(NO2 차등SNR×분리도cond×빛세기노이즈)이면 핏 없이 cold 438-470nm 재현 가능.

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

## 11. 이번 세션(2026-06-30)에 바뀐 것 (참고)
핏 파이프라인/최적화와 무관하지만 코드가 바뀐 것들: Plot Maker 대폭 강화(색·스타일·에러밴드·야간음영·주석·커서·범례·템플릿·서브플롯),
정착 스캔 제외 체크박스(`chk_settle`), Result Lab 계산기(`dlg_calculator`), α Health Fit-window 버튼, **`core/health_checks.py` 신설**.
→ 옵티마이저 관점 유효: `health_checks`(§7), `chk_settle`(§5 QC default), settling 저편향(`settling-scan-bias-and-tool-2026-06`).
