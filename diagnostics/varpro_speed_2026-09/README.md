# VarPro 속도/채택근거 검증 (2026-09)

`core/doas_fit.py`(실제 VarPro `execute_varpro_fit`, 수정 없이 그대로 import)를
"완전 비선형"(농도·배경·etalon·shift/squeeze를 전부 하나의 비선형 벡터로 최적화하는
방식 — VarPro가 대체하려는 대상 클래스, 이 폴더의 스크립트가 같은 모델식·같은
bound로 직접 구현) 베이스라인과 합성 데이터로 비교.

## ⚠⚠ 최신 (2026-09-15 3차) — 해석적 자코비안 도입, "차원축소 덕" 실증

아래 2차 정정도 아직 절반이었다. 남은 절반은 **scipy 기본 2점 유한차분 자코비안**.
실측(실제 프리셋 d=2, 실캠페인 알파): 목적함수 호출의 **67%가 유한차분용**,
목적함수가 총 시간의 66~72% → **유한차분이 총 시간의 약 47%**.

**Golub–Pereyra 완전식**으로 교체: `J_k = −[P⊥ D_k c + A⁺ᵀ D_kᵀ r]`, `P⊥ = I−QQᵀ`,
`A⁺ᵀ = QR⁻ᵀ`. ±Neg ON(무제약)일 때 선형 단계를 QR로 풀고 그 Q/R을 재활용한다.

⚠ **Kaufman 근사(2항 생략)는 안 된다** — 먼저 시도했다가 유한차분과 40~67% 어긋나
폐기했다. 2항은 k-벡터 삼각해 하나 + Q 곱 하나라 사실상 공짜다. 같은 함정 반복 금지.

**이 폴더 스크립트 재실행(2026-09-15)**:

| 테스트 | VarPro warm | 완전비선형 warm | VarPro cold | 완전비선형 cold |
|---|---|---|---|---|
| Cold d=2 (`run_cold.py`) | **2.54** ms/scan | 10.37 (4.1배) | **2.83** | 15.21 (5.4배) |
| Hot ROI1 d=8 (`run_hot_unlinked_stress.py`) | **6.78** | 36.33 (5.4배) | **7.45** | 57.27 (7.7배) |

d=8은 원래 VarPro가 **1.9배 지던** 케이스(세션 시작 시 44.7 ms/scan). 이제 5.4배 이기고,
**차원이 커질수록 이득이 커진다** — Golub–Pereyra가 예측하는 거동이 해석적 자코비안을
넣고 나서야 나타났다.

검증: `validate_analytic_jacobian.py` — (1) 핏 도중 자코비안 전수를 `approx_derivative`와
대조(480회, 최대 상대차 8.6e-07), (2) **cold-start를 판정 기준**으로(캐리오버 없음) 8개
조건 × 500스캔에서 shift max|diff| ≤ 1e-5 px, 농도 상대차 ≤ 1e-6, corr=1.00000000.
속도는 직전 커밋 대비 1.51~1.71배(중앙값 1.57배).

---

## ⚠ 최신 정정 (2026-09-14 2차) — 아래 "결론 한 줄"은 무효다

**원인은 알고리즘이 아니라 구현 버그였다.** `execute_varpro_fit`가 픽셀 가중 W를
**밀집 n×n 대각행렬**로 받아 목적함수 호출마다 `W @ A`(O(n²k))를 돌렸다. W는 언제나
대각이라 `A * w[:,None]`(O(nk))와 동치인데, n=775px 기준 산술량이 약 775배.
`y_weighted = W @ optical_depth`는 theta 불변인데도 매 호출 재계산했다.

| 호출당 (Cold 775px, k=10) | ms | 비중 |
|---|---|---|
| `W @ A` + `W @ y` | 0.247 | **62%** |
| 설계행렬 조립(보간+column_stack) | 0.106 | 27% |
| `lsq_linear` | 0.044 | 11% |
| (동치인 행스케일) | 0.0085 | — |

아래 §"원인 정정(2026-09-14)"이 지목한 **"설계행렬 재조립"도 진범이 아니다**(27%).
`objective_varpro` 자기시간 49%의 정체는 저 밀집 곱이다 — `@`는 C 빌트인이라 별도
함수로 안 잡히고 호출한 함수의 자기시간에 흡수된다.

**수정 후(W를 벡터로, `core/doas_fit.py`+`gui/worker.py`+호출부 7곳)**, 이 폴더의
같은 스크립트 재실행:

| 테스트 | VarPro warm | 완전비선형 warm | VarPro cold | 완전비선형 cold |
|---|---|---|---|---|
| Cold d=2 (`run_cold.py`) | **4.28** ms/scan | 10.32 | **4.62** | 15.22 |
| Hot ROI1 d=8 Link해제 (`run_hot_unlinked_stress.py`) | **21.21** | 37.72 | **24.05** | 59.17 |

**"차원이 커지면 VarPro가 진다"는 결론은 뒤집혔다** (d=8에서 1.9배 패배 → 1.8배 승리).
모든 조건에서 VarPro가 빠르다. 다만 해석적 자코비안(Golub–Pereyra)은 여전히 미구현이므로
"차원축소 덕"이라고 단정하지 말고 측정값으로만 쓸 것.

동일성 검증: `validate_dense_w_removal.py` — 수정 전 코드를 `git show <ref>:core/doas_fit.py`로
꺼내 같은 하네스로 실캠페인 알파에 돌려 스캔별 대조. Cold 5/17·6/5 + Hot ROI1/ROI2 ×
warm/cold-start = 8개 조건 × 700스캔에서 **max|diff| = 0.000e+00(비트단위 동일)**,
속도 2.17~2.51배(중앙값 2.36배).

남은 후보: `Link`된 종의 중복 보간 캐시(호출당 ~14%). 미적용.

---

## 결론 한 줄

**VarPro가 "느리다"는 아니다(완전비선형과 최대 ~2배 이내, Beirle et al. 2013이
말한 "2자릿수"와는 다른 스케일; Cold 채널은 합성·실캠페인 데이터 모두에서
VarPro가 오히려 더 빠름, ~1.2배). 하지만 "차원축소 덕에 빠르다"는 이 구현에서는
실증되지 않았고, 비선형 차원이 커질수록(Link 없이 기체가 많을수록) 오히려
완전비선형보다 느려진다.

**⚠ 원인 정정(2026-09-14, 프로파일로 확정)**: 위 줄은 원래 "유한차분 자코비안이 외부
차원 수만큼 내부 `lsq_linear`(bound 제약 반복 solver) 호출을 요구하기 때문"이라고
적혀 있었다. **측정 결과 그 설명은 틀렸다.**
  · `lsq_linear`는 ±Neg ON(=모든 하한 −∞)이면 scipy가 무제약 해를 먼저 풀고 bound
    안이면 **즉시 반환**한다(반복 0회, 호출당 0.047 ms). `scipy_lstsq`(gelsy, 0.135 ms)
    보다 오히려 빠르다 — "무제약이면 lstsq로 분기" 최적화는 **무효**다.
  · 프로파일(실제 콜드 레퍼런스 4종, px774-1550, poly4)에서 `lsq_linear`는 상위 14개
    항목에 **들어오지도 않는다**.
  · 진짜 비용은 **목적함수 호출 수 × 설계행렬 재조립**이다:

    | | d=2(Link) | d=8(Free) |
    |---|---|---|
    | 총 | 10.7 ms/scan | 33.6 ms/scan |
    | `objective_varpro` 호출 | 60회 | 270회 |
    | 그 함수 자기시간 비중 | — | **49%** |
    | `evaluate_spline`(레퍼런스 보간) | 280회 | 1,120회 |

    즉 비싼 건 "선형해를 다시 푸는 것"이 아니라 **"레퍼런스를 shift/squeeze로 다시
    보간해 설계행렬을 다시 만드는 것"**이다.
  · 남은 개선 여지: `Link`된 종들은 shift/squeeze가 **같은 값**인데도 종마다 따로
    보간한다. 같은 (shift, squeeze)의 보간 결과를 재사용하면 호출을 줄일 수 있다
    (미적용 — 핏 수치 경로라 동일성 검증 필요). 정확도는 **cold-start
(캐리오버 없음)에서는 Cold·Hot 모든 실캠페인 조건에서 사실상 동일**(r>0.9999,
최대 0.02px 이내)하지만, **warm-start(캐리오버 있음)에서는 조건에 따라 강한
상관관계 수준(r=0.88~0.99, 스캔별 최대 ~1px 차이)까지 완화될 수 있음** — 최악의
사례는 처음엔 "shift가 ±2px 벽에 자주 붙는 극단적으로 불안정한 날"(Cold
2026-05-17, r=0.958~0.993)로 보였지만, Hot 채널까지 검증해보니 **평범한 날
(2026-06-05)의 특정 채널(Hot ROI2/ANs)에서 r=0.884로 더 낮은 값**이 나옴 —
즉 이탈은 "극단적인 날"이 아니라 **warm-start 캐리오버의 경로 의존성**이
근본 원인이고 shift 불안정성은 그 유발 요인 중 하나일 뿐. Cold(5/17·6/5)·Hot
(ROI1·ROI2, 6/5) 실캠페인 검증 결과, 아래 "미완 작업" 참조.
VarPro를 계속 쓰는 근거는 속도가 아니라 ±Neg/Tikhonov/Robust IRLS/etalon-기체
공선성 진단을 선형 단계에 깔끔히 얹을 수 있는 구조(유지보수성·검증가능성)로
재구성해야 한다. 자세한 배경: 클라우드 세션에서 먼저 이 결과가 나왔고(코어 2개
샌드박스), 이 폴더는 **실제 저장소의 실제 코드를 그대로 import**해 사용자 본인
장비(멀티코어, 실제 GUI와 같은 코드 버전)에서 재현하기 위한 것.

## 파일 구조

```
bench_common.py             ← 엔진 생성·합성 스캔 생성·VarPro/베이스라인 실행·요약 (공용)
run_cold.py                 ← Cold 채널, 실제 프리셋(Link 유지)
run_hot_reallink.py         ← Hot ROI1, 실제 프리셋(Link 유지) — Cold와 같은 2차원
run_hot_unlinked_stress.py  ← Hot ROI1, 의도적 스트레스 케이스(Link 해제, 4기체 독립)
run_parallel_chunk.py       ← 청크+워밍업 병렬 vs 순차 (§5.7 재현, 실제 코어 수 사용)
run_cold_real.py            ← Cold, 합성 아닌 실캠페인(여수) alpha 데이터로 VarPro vs 완전비선형
run_hot_real.py             ← Hot ROI1/ROI2, 위와 같은 비교(--channel roi1|roi2)
validate_dense_w_removal.py     ← 밀집 W 제거 전/후 대조(비트동일 게이트)
validate_analytic_jacobian.py   ← 해석적 자코비안 전/후 대조(자코비안 FD 대조 + cold-start 게이트)
results_*.json              ← 각 실행 결과(재실행 시 덮어씀). **이것만 .gitignore 대상**
                               — 폴더 자체는 추적된다(2026-09-15 변경).
```

⚠ `validate_*.py` 두 개는 **`--before-ref`가 필수**다. 예전엔 기본값이 `HEAD`였는데,
변경이 머지된 뒤로는 "지금 코드 vs 지금 코드"가 되어 **아무것도 검증하지 않고 PASS를
찍는다**. 기준 커밋: 밀집 W는 `944c7bd`(직전)/`33f6f3e`(적용), 해석적 자코비안은
`aece86f`(직전)/`5d42ad4`(적용). 캠페인 폴더는 `--alpha-root`로 준다(없으면 SKIP 후
exit 2 — 조용히 통과하지 않는다).

**CI에서 매번 도는 축소판은 `tools/test_varpro_jacobian.py`**다. 합성 레퍼런스로
영속 불변식 5개(스플라인 동치 · 자코비안 vs 유한차분 · W 벡터/밀집 동치 · ±Neg OFF
폴백 · 창 밖 기체 계수 0)를 1초에 검사한다. 이 폴더 스크립트는 실캠페인 **일회성**
대조용이고, 상시 회귀 게이트는 그쪽이다.

## 스크립트

| 파일 | 역할 |
|---|---|
| `run_cold.py` | Doctor_Scenario Cold 설정(775-1550px, poly4, NO2 Limit ±2px/±0.02, CHOCHO·H2O Link→NO2) 그대로 사용. VarPro 비선형 차원=2. |
| `run_hot_reallink.py` | Doctor_Scenario Hot ROI1 설정(600-1270px, poly4, 나머지 동일 Link 구조). VarPro 비선형 차원도 동일하게 2 — "채널/창이 바뀌면 속도가 바뀌는가"만 격리해서 봄. |
| `run_hot_unlinked_stress.py` | 위와 같은 창이지만 O4까지 포함해 4기체를 전부 Link 없이 독립 Limit로 풀어 VarPro 비선형 차원을 8로 늘림(완전비선형은 19차원). "차원이 커지면 VarPro가 유리해지는가"를 스트레스 테스트 — **실제 프리셋이 아님, 의도적 실험**. |
| `run_parallel_chunk.py` | `gui/worker.py`의 `AnalysisWorker._run_parallel`과 같은 공식(nproc=max(2,min(8,cpu//2)), warmup=40, chunk_size 공식)으로 청크+워밍업 병렬 vs 순차를 비교. 디스패치 로직은 재현(worker.py 자체는 Qt에 강결합돼 있어 그대로 못 씀)이지만 **매 스캔 피팅은 `core/doas_fit.py` 실제 함수**. 속도(스캔당 ms, speedup)와 §5.7이 주장하는 "순차와 동일한 답" 검증(청크경계 포함 shift/농도 diff)을 같이 출력. `--nproc N`(기본: production 공식), `--scans N`(기본 1500)으로 조절 가능. |
| `run_cold_real.py` | 위 세 스크립트와 같은 VarPro-vs-완전비선형 비교인데, **합성 데이터가 아니라 실캠페인(여수, `C:\GHL\2026 yeosu\Output\alpha\10s\cold\`) alpha 데이터**로 돌림. 실데이터는 참값(true_shift/true_c)이 없으므로 RMSE-vs-truth 대신 `bench.py`/`validate_chunk.py`처럼 **VarPro 결과를 완전비선형 결과와 직접 비교**(shift/계수 diff·상관계수)한다. 기본 날짜는 2026-05-17(콜드 shift가 ±2px 양쪽 벽을 오가는, 지금까지 본 것 중 가장 불안정한 날 — 사용자 확인: "콜드가 전체적으로 그렇고 5/17이 유독 심함") — "매끈한 합성 드리프트가 아니라 진짜 지저분한 데이터에서도 VarPro==완전비선형 정확도"라는 결론이 유지되는지가 이 스크립트의 존재 이유. `--alpha-dir`/`--day`/`--nfiles`로 다른 날짜·파일수 지정 가능. |
| `run_hot_real.py` | `run_cold_real.py`와 같은 비교를 **Hot ROI1/ROI2**(`run_hot_reallink.py`와 같은 프리셋 — 600-1270px, Link 유지, 비선형 차원 2)로, 실캠페인 데이터(`alpha\10s\hot\ch1\`=ROI1/ANs, `ch2\`=ROI2/PNs)에서 돌림. Cold는 이미 극단(5/17)·보통(6/5) 두 날짜로 검증됐지만 Hot은 지금까지 합성 데이터로만 비교돼서 이 구멍을 메움. `--channel roi1\|roi2`로 채널 선택, 기본 날짜 2026-06-05(Cold와 같은 "보통" 날 — 이날은 hot 데이터도 존재). |

앞 세 스크립트(run_cold/run_hot_reallink/run_hot_unlinked_stress): 220개 합성
스캔(느린 랜덤워크 shift/squeeze 드리프트 + 100번째 스캔에 미러클리닝급 급점프
+1.3px/+0.008), warm-start(직전 스캔 값 이어받기)와 cold-start(매번 0/1에서
시작) 두 조건, `time.perf_counter()`로 피팅 호출만 측정, 정확도는 참값 대비
RMSE(정상상태/점프직후/회복구간 3구간). `run_parallel_chunk.py`는 스캔 수를
늘려(기본 1500) 여러 청크가 생기게 하고, 점프는 스캔 400에 배치. `run_cold_real.py`도
warm/cold-start 두 조건은 같지만 합성이 아니므로 점프 위치는 없고(실제 데이터에
있으면 있는 그대로), 정확도는 참값이 아니라 VarPro-vs-완전비선형 직접 비교로 측정.

## 재현 순서

```
cd diagnostics/varpro_speed_2026-09
python run_cold.py
python run_hot_reallink.py
python run_hot_unlinked_stress.py
python run_parallel_chunk.py                 # 이 컴퓨터 코어 수로 자동 결정(기본 nproc)
python run_parallel_chunk.py --nproc 1       # 병렬 오버헤드만 보고 싶을 때(1워커=사실상 순차+풀 오버헤드)
python run_parallel_chunk.py --nproc 8 --scans 4000   # production 기본값과 같은 조건, 더 긴 캠페인 흉내
python run_cold_real.py                                          # 2026-05-17(최악의 날), 4파일 ~1400스캔
python run_cold_real.py --day 2026-06-05                          # 비교용 "보통" 날짜
python run_cold_real.py --alpha-dir "C:\GHL\2026 yeosu\Output\alpha\10s\cold" --day 2026-06-05 --nfiles 4
python run_hot_real.py --channel roi1                             # Hot ROI1(ch1/ANs), 2026-06-05
python run_hot_real.py --channel roi2                             # Hot ROI2(ch2/PNs), 2026-06-05
python run_hot_real.py --channel roi1 --day 2026-05-18            # Hot 데이터 최초 날짜
```
의존성: numpy, scipy, (선택) threadpoolctl — 전부 레포 `requirements.txt`에 이미 포함.
`core/paths.WV_CAL_DIR`로 `reference_data/wv_cal/{cold,roi1}/Ref_*_Dynamic-ILS-Applied.dat`를
읽으므로 저장소 루트에서(또는 이 폴더에서 상대 import가 되도록) 실행하면 된다.
`run_parallel_chunk.py`는 `concurrent.futures.ProcessPoolExecutor`를 쓰므로 Windows에서는
`if __name__ == "__main__":` 가드 안에서 실행돼야 하는데(이미 그렇게 작성됨), 대화형
인터프리터(REPL)가 아니라 `python run_parallel_chunk.py`로 직접 실행해야 한다.

## 핵심 발견 (클라우드 세션 사전 실행, 코어 2개 샌드박스 — 재현용 숫자는 결과 JSON 참조)

| 테스트 | VarPro (warm) | 완전비선형 (warm) | VarPro (cold) | 완전비선형 (cold) |
|---|---|---|---|---|
| Cold (2차원) | ~27 ms/scan | ~25 ms/scan (더 빠름) | ~29 ms/scan | ~36 ms/scan (VarPro가 ~19%↑) |
| Hot ROI1 Link유지 (2차원) | ~17 ms/scan | ~11-15 ms/scan (더 빠름) | ~18 ms/scan | ~18-19 ms/scan (비슷) |
| Hot ROI1 Link해제 (8차원, 스트레스) | ~85-89 ms/scan | ~45-47 ms/scan (~1.9배 빠름) | ~108-110 ms/scan | ~75-86 ms/scan |

정확도(shift/squeeze/농도 RMSE)는 모든 셀에서 VarPro와 완전비선형이 사실상 동일 —
완전비선형이 지역해에 빠진 사례 없음. Hot ROI1은 창이 Cold보다 좁아(670px vs
775px) Link 유지 시 오히려 Cold보다 빠르다 — "핫 채널이 콜드보다 느려야 할 이유"는
채널 자체가 아니라 Link 해제로 인한 차원 증가였음을 확인.

메커니즘: `execute_varpro_fit`의 비선형 탐색(shift/squeeze) 매 반복마다 내부에서
`scipy.optimize.lsq_linear`(bound 제약 반복 solver, ±Neg/Tikhonov 때문에 닫힌형
대신 사용)를 다시 부른다. scipy `least_squares`의 기본 유한차분 자코비안은 외부
차원 수만큼 함수평가(=내부 solve 호출)를 요구하므로, 차원이 커질수록 "차원축소
이점"이 "내부 solve 호출 증가 페널티"에 잠식된다. 완전비선형은 매 평가가 모델
1회 계산(내부 solve 없음)이라 이 페널티가 없다.

## 이미 있던 관련 도구 (2026-09-05 확인 — 이 폴더와 겹치지 않게 참고)

- `diagnostics/parallel_shift_bench/`(`bench.py`, `validate_chunk.py`, `validate_chunk_pp.py`,
  `compare_3ch.py`, `compare_fast_vs_step.py`, `compare_june.py`, `EXISTING_FIT_LOGIC.md`) —
  `AnalysisWorker.run()`의 스캔간 캐리오버 상태를 정밀 분석하고 shift 안정화 방식
  4가지(seq/indep/twopass/chunk)를 실 콜드 알파 시계열로 비교하는, 이 폴더보다
  먼저 만들어진 검증 스위트. `bench.py`는 원래 `C:\Doasis_Work\Output\alpha\cold`를
  참조했는데 이 세션에서 그 폴더 권한을 못 받아서, 대신 사용자가 연결해준
  `C:\GHL\2026 yeosu\Output`(여수 캠페인, alpha 2026-05-17~, wv_cal 완비)로
  `--alpha-dir`/`--ref-dir` 옵션을 추가해 패치함(2026-09-05). `validate_chunk.py`도
  같은 이유로 패치했는데, 그 과정에서 버그 하나 발견: `ROOT`가 존재하지도 않는
  `C:\Doasis_Work\CAESAR\CAESAR`로 하드코딩돼 있어서 스크립트 파일 위치 기준
  상대경로로 고쳐 항상 "지금 실행 중인 이 저장소"를 쓰도록 수정. `bench.py`
  자신도 "inner fit은 production VarPro의 단순화판"이라고 명시(이 폴더의
  스크립트들과 같은 종류의 절충)하지만, `validate_chunk.py`는 실제
  `AnalysisWorker._fit_alpha_range`를 그대로 호출 — 진짜 프로덕션 코드로 실캠페인
  데이터에서 "청크==순차"를 검증하는 가장 강한 테스트. 2026-05-17 실행 결과:
  NO2/CHOCHO ppb Δmax=0.0000e+00(비트단위 완전일치). 같은 실행에서 shift가 하루
  동안 ±2px 양쪽 벽을 다 치는 것도 확인(min=-2.000 max=+2.000 std=1.561) —
  사용자 확인: 콜드 채널 전반의 특성이고 5/17이 유독 심함(코드 버그 아님).
- `diagnostics/alpha_pass2_parallel/validate_pass2_parallel.py` — DOAS 핏이 아니라
  Pass2(raw→α 생성) 단계의 병렬화 검증(전체 캠페인용 수동 실행 버전). 그 축소판인
  `tools/test_pass2_parallel.py`가 CI에서 매 push마다 자동 실행되지만, fixture가
  150행×2파일뿐이라 **정확성만** 검증하고 속도 벤치마크는 아님.

## 미완 작업

- [x] **§5.7 청크+병렬화 실측** — `run_parallel_chunk.py`로 추가함(2026-09-05).
      클라우드 샌드박스(코어 2개)에서 정확성(순차 대비 shift 최대 diff ~7e-7px,
      농도 diff ~1e-10)은 확인됨 — production이 주장하는 "~1e-6 ppb 일치"를
      합성 데이터에서 재확인.

      **실제 20코어 장비에서 실행 완료(2026-09-05, 사용자 실행)**:

      | scans | nproc | chunk_size | n_chunks | 순차 | 병렬 | speedup |
      |---|---|---|---|---|---|---|
      | 1500 | 8 | 150 | 10 | 13.897s (9.264 ms/scan) | 7.821s (5.214 ms/scan) | **1.78x** |
      | 4000 | 8 | 150 | 27 | 37.378s (9.345 ms/scan) | 15.739s (3.935 ms/scan) | **2.37x** |

      정확도: shift 최대 diff 1.69-1.82e-6px(평균 ~2e-7px), 농도 최대 diff
      ~9e-10~1.1e-9(평균 ~1e-10) — 순차와 사실상 동일, §5.7의 "~1e-6 ppb 일치"
      주장을 20코어 실기기·실제 `core/doas_fit.py`로 재확인.

      **왜 8배가 아니라 1.78~2.37배인가**: 두 실행 다 `chunk_size`가 공식의
      최솟값 150으로 클램프됨(`n/(nproc*6)`이 150보다 작아서). `warmup=40`은
      매 청크마다 계산은 하지만 버려지는 스캔이므로, 청크당 "유효" 작업 비율은
      150/(150+40)≈79%뿐 — 이것만 반영하면 이론적으로는 8×0.79≈6.3배가 나와야
      하는데 실측은 그 1/3 수준(1.78~2.37배)에 그침. 나머지 격차는
      `ProcessPoolExecutor` 생성·워커 초기화(`_chunk_init`에서 매 워커가 엔진·
      레퍼런스 스펙트럼·보간기를 다시 구성) 같은 고정 오버헤드로 보인다 — 스캔
      수를 1500→4000(2.7배)로 늘렸을 때 speedup이 1.78x→2.37x로 개선된 것이
      바로 이 고정비용이 총 작업량 대비 희석됐다는 신호. 즉 **캠페인이 길수록
      병렬화 이득이 커지고, 짧은 테스트만으로는 실제 이득을 과소평가**하게 된다.

      **아직 안 한 것**: `--nproc 1`로 순수 풀 오버헤드만 분리 측정, warmup을
      줄이거나 chunk_size 상한(400)을 키웠을 때 speedup이 얼마나 더 개선되는지,
      그리고 실제 캠페인 길이(수만 스캔)에서 speedup이 어디로 수렴하는지.
- [ ] **여러 노이즈 시드 반복** — 지금은 시드 1개(20260905)뿐. 오차막대 필요.
- [ ] **해석적 축소 자코비안 실험(선택)** — scipy 기본 유한차분 대신 VarPro
      원논문(Golub–Pereyra)식 해석적 자코비안을 구현하면 이론적 속도 이점이
      실제로 나타나는지 확인 가능. `core/doas_fit.py` 본체를 건드리는 실험이라
      회귀테스트 없이 진행하면 안 됨 — 별도 브랜치 권장.
- [x] **청크+워밍업 정확성, 실캠페인 데이터로 확인(2일치)** — `parallel_shift_bench/validate_chunk.py`를
      2026-05-17(최악의 날)과 2026-06-05("보통" 날, 24파일 중 4파일/1412스캔)
      둘 다로 실행:

      | 날짜 | seq shift 범위 | seq shift std | shift Δmax(청크-순차) | NO2 ppb Δmax | 최대상대오차 |
      |---|---|---|---|---|---|
      | 2026-05-17 | -2.000~+2.000 (양쪽 벽) | 1.561 | 0.0000e+00(비트단위) | 0.0000e+00 | 0 |
      | 2026-06-05 | -2.000~+0.916 (한쪽 벽만) | 0.568 | 6.4e-4px | 3.73e-6 | 2.81e-6 |

      **정정**: "청크==순차, 항상 비트단위 완전일치"가 아니었음 — 5/17이 비트단위로
      맞은 건 우연이 아니라, shift가 거의 항상 ±2px 경계에 붙잡혀 있어서(bound-clamped)
      워밍업으로 재현한 캐리오버 상태가 정확히 같지 않아도 최적화가 같은 경계값으로
      수렴하기 때문(경로 의존성이 사라짐). 6/5처럼 shift가 경계 안쪽에서 자유롭게
      움직이는 "보통" 조건에서는 워밍업 재현 캐리오버가 완전 동일하지 않아 아주 작은
      (px 단위 6e-4, ppb 상대오차 ~3e-6) 실차이가 남는다. 이 크기는 논문의 "~1e-6
      ppb 일치" 주장 스케일과 거의 맞고 실질적으로 무해하지만, "항상 정확히 0"이라는
      표현은 부정확하므로 "일반 조건에서 ppb 상대오차 ~1e-6 수준으로 사실상 일치,
      shift가 경계에 포화된 특수 조건에서는 비트단위 일치"로 서술 필요.
      부산물로 콜드 shift가 5/17엔 ±2px 양쪽 벽을, 6/5엔 -2px 쪽만 오가는 현상 확인
      (코드 문제 아님, 사용자 확인: 콜드 채널 전반 특성, 5/17이 특히 심함) —
      VarPro/병렬화 결론과는 별개 이슈, 논문 Discussion 한계 항목으로 서술 예정.
- [x] **VarPro vs 완전비선형, 실캠페인 데이터로 비교** — `run_cold_real.py`
      신규 추가(2026-09-06). 지금까지 "정확도 동일" 결론은 전부 합성(매끈한
      드리프트) 데이터 기준이었는데, 실데이터(특히 5/17처럼 shift가 벽을 치는
      불안정한 날)에서도 두 방법이 같은 답을 내는지는 아직 확인 안 됨 — 이
      스크립트가 그 구멍을 메움.

      **1차 실행(2026-09-06) 결과는 버그로 무효** — 사용자가 실제 5/17 데이터로
      돌려보니 VarPro의 shift가 warm/cold-start 둘 다 **정확히 0.000으로 얼어붙어**
      있었음(완전비선형은 warm-start에서만 정상적으로 -2~+2px를 움직임). 원인
      조사 결과 VarPro 버그가 아니라 **이 진단 스크립트(`bench_common.py`)의
      결함**이었음: `gui/worker.py`의 실제 `_fit_alpha_range`는 핏 직전에
      `avg_raw = mean(y); scale_factor = 10**(-floor(log10(|avg_raw|)))` (단,
      `|avg_raw| < 1e-4`일 때만)로 데이터를 위로 스케일링하는 언더플로 방지
      단계가 있는데, `run_varpro`/`run_baseline`은 이 단계를 빠뜨리고 있었음.
      지금까지 이 폴더의 합성 데이터는 진폭이 전부 ~1e-3~0.3(스케일링 문턱값
      1e-4보다 훨씬 큼)이라 이 버그가 드러날 일이 없었는데, 실제 여수 alpha
      데이터는 그보다 훨씬 작은 진폭이라 처음으로 노출됨 — scipy 기본 유한차분
      자코비안이 이 정도로 작은 절대 스케일에서는 사실상 기울기를 0으로
      감지해서 최적화가 초기값에서 전혀 안 움직인 것. 합성 데이터를 진폭만
      1e-5로 낮춰 동일 증상을 재현해 원인을 확정한 뒤, `bench_common.py`의
      `run_varpro`/`run_baseline`에 동일한 `scale_factor` 로직을 추가하고
      (계수는 다시 나눠서 원래 단위로 환산) 수정 전후로 정확도가 똑같이
      나오는지(정상 진폭 데이터, `run_cold.py` 재실행) 회귀 확인함 — 문제없음.

      **수정판 재실행 결과(2026-09-06, 사용자 실행, 5/17, 1402스캔) — 진짜 결과**:
      두 방법 다 이제 -2~+2px 양쪽 벽을 정상적으로 오감(`validate_chunk.py`가
      확인한 실제 거동과 일치, 버그 해소 확인). 하지만 합성데이터와 달리
      **완전히 같지는 않음**:

      | 조건 | shift rms_diff | shift max_diff | shift corr | VarPro | 완전비선형 |
      |---|---|---|---|---|---|
      | warm-start | 0.1696px | 1.0000px | 0.9933 | 29.6 ms/scan | 36.4 ms/scan |
      | cold-start | 0.1428px | 1.0000px | 0.9585 | 32.3 ms/scan | 40.4 ms/scan |

      상관계수 0.96~0.99로 두 방법이 강하게 같은 방향으로 움직이지만(합성
      드리프트 테스트의 "사실상 동일"과는 다르게), 실제 불안정한(벽에 붙는) 날
      에는 스캔별로 최대 1px까지 다른 답을 내는 경우가 존재함 — 어느 쪽이
      "더 맞는지"는 참값이 없어 판단 불가. 농도 계수는 절대 diff는 극히 작지만
      (~1e-9~1e-10) 평균 농도 자체가 그만큼 작은(노이즈 바닥 근처) 스캔이 많아
      상대오차(max_rel)는 크게 보일 수 있음 — 이런 스캔에서는 상대오차보다
      상관계수가 더 의미 있는 지표. 속도는 실데이터에서도 VarPro가 계속 더
      빠름(~1.2배) — Cold(2차원)에서의 합성데이터 결과와 일관됨.

      **"보통" 날짜(2026-06-05, 24파일 중 4파일/1412스캔) 결과 — 훨씬 좋음**:
      shift가 대부분 -2~+0.9px 범위(한쪽 벽만 가끔) 안에서 자유롭게 움직이는
      조건에서는 VarPro와 완전비선형이 **사실상 동일**, 합성데이터 결론과 일치:

      | 조건 | shift rms_diff | shift max_diff | shift corr | VarPro | 완전비선형 |
      |---|---|---|---|---|---|
      | warm-start | 0.0047px | 0.0615px | 0.999962 | 16.1 ms/scan | 21.6 ms/scan |
      | cold-start | 0.0054px | 0.1950px | 0.999830 | 15.1 ms/scan | 24.9 ms/scan |

      5/17(최악의 날, r=0.958~0.993, 최대 1px 차이) 대비 상관계수가 0.9998~1.000로
      대폭 개선되고 최대 차이도 1px→0.06~0.2px로 줄어듦 — **"VarPro==완전비선형"
      결론은 shift가 경계에 자주 포화되지 않는 일반적인 조건에서는 그대로
      유지되고, 5/17 같은 극단적 wall-hugging 날이 사실상의 최악-사례 하한선**
      이라는 그림이 됨. 속도도 6/5가 5/17보다 두 방법 다 약 2배 빠름(계산이 벽
      근처에서 더 오래 걸림을 시사) — VarPro는 두 날 모두, 그리고 warm/cold-start
      모두에서 일관되게 더 빠름(6/5: ~1.3~1.65배, 5/17: ~1.2배).

      **논문에 쓸 최종 결론**: "VarPro==완전비선형" 주장은 **일반적인(경계 비포화)
      조건에서는 r>0.9998, 최대 0.2px 이내로 사실상 동치가 유지**되고, **경계에
      자주 포화되는 불안정한 조건(5/17)에서만 강한 상관(r=0.96~0.99, 최대 1px
      차이)으로 완화**해서 서술 — 즉 "대체로 동일, 극단적 조건에서만 소폭 이탈"이
      가장 정확한 표현. 이 이탈 자체를 Discussion 한계로 명시하고, 원인 후보로
      경계 근처에서의 비선형 최적화 경로 의존성(청크+워밍업 정확성 검증에서도
      같은 메커니즘 발견, 위 참조)을 제시. 속도 면에서는 Cold 채널 기준 VarPro가
      두 날 모두, 두 시작조건 모두에서 일관되게 완전비선형보다 빠름.
- [x] **Hot ROI1/ROI2, 실캠페인 데이터로 비교** — `run_hot_real.py`, 매핑
      수정판으로 재실행 완료(2026-09-06). Cold는 이미 최악(5/17)·보통(6/5)
      두 날짜로 끝났으니 마지막 남은 채널 구멍.

      **1차 실행(2026-09-06) 결과는 채널 매핑 오류로 폐기**: 1차 버전은
      device folder `ch1`(`*_ANs_alpha_trace.dat`)을 "roi1"로, `ch2`
      (`*_PNs_alpha_trace.dat`)를 "roi2"로 라벨링하고 둘 다 같은
      600-1270px/poly4 창으로 돌렸음(정렬 순서만 보고 짝지은 것) —
      `scenarios/Doctor_Scenario_Cold_ROI1_ROI2.json`·`docs/매뉴얼_조작순서.md`
      확인 결과 실제로는 **ROI1(600-1270px, poly4)=PNs(`ch2`)**,
      **ROI2(900-1450px, poly3)=ANs(`ch1`)**로 반대였음 — 매핑 수정 후 재실행.

      **수정판 결과(2026-09-06, 사용자 실행, 2026-06-05, 1410스캔)**:

      | 채널 | 창/차수 | 조건 | shift rms_diff | shift max_diff | shift corr | VarPro | 완전비선형 |
      |---|---|---|---|---|---|---|---|
      | ROI1(PNs/ch2) | 600-1270px poly4 | warm | 0.0383px | 0.9999px | 0.998045 | 17.0 ms/scan | 18.5 ms/scan |
      | ROI1(PNs/ch2) | 600-1270px poly4 | cold | 0.0004px | 0.0043px | 0.999999 | 16.8 ms/scan | 17.4 ms/scan |
      | ROI2(ANs/ch1) | 900-1450px poly3 | warm | 0.0298px | **1.0000px** | **0.883777** | 7.8 ms/scan | 8.5 ms/scan |
      | ROI2(ANs/ch1) | 900-1450px poly3 | cold | 0.0005px | 0.0191px | 0.999921 | 11.2 ms/scan | 13.0 ms/scan |

      **새로운 최악-사례 발견**: ROI2(ANs, 진짜 900-1450px/poly3 창) warm-start의
      상관계수 **0.884**는 지금까지 본 모든 실캠페인 비교 중 가장 낮음 —
      Cold 5/17(최악의 불안정한 날, r=0.958~0.993)보다도 낮은 값이 "보통 날"
      (6/5)의 warm-start에서 나옴. 다만 절대적 max_diff(1.0000px)는 Cold
      5/17과 같은 스케일이고 rms_diff(0.0298px)는 오히려 작음 — **상관계수가
      낮아 보이는 건 ROI2 warm-start의 shift 값 범위 자체가 좁기 때문**
      (VarPro/완전비선형 둘 다 [-2.000,-0.500] 구간에 몰려 있음, 폭 1.5px) —
      분산이 작은 신호에 같은 크기의 절대 이탈이 섞이면 상관계수가 훨씬
      민감하게 깎인다. 즉 **r 하나만으로 조건 간 심각도를 비교하면 안 되고,
      rms/max_diff 같은 절대값 지표를 같이 봐야 함** — 이번 발견으로 얻은
      방법론적 교훈.

      cold-start는 두 채널 다 사실상 완벽(r=0.999921~0.999999) — Cold에서도
      본 "cold-start는 안전, warm-start 캐리오버 사슬에서만 이탈" 패턴이
      Hot에서도 반복됨(오히려 ROI2에서 가장 심하게). 속도는 두 채널 다
      VarPro가 근소 우위(~1.03~1.16배) — Cold보다 마진이 작다는 이전 결론도
      유지(ROI1 wider window/poly4가 ROI2 narrower window/poly3보다 느림은
      당연히 창 크기 차이).

      **논문에 쓸 결론**: "VarPro==완전비선형" 이탈의 최악-사례는 극단적으로
      불안정한 날(Cold 5/17)이 아니라 **특정 채널의 특정 warm-start 캐리오버
      사슬(Hot ROI2/ANs, 평범한 날에도)**일 수 있음 — "극단적인 날에만
      이탈"이라는 서술은 완전히 폐기하고, "채널·창·warm-start 조합에 따라
      r=0.88~1.00 범위로 갈릴 수 있으며, 원인은 shift 안정성보다 warm-start
      경로 의존성 쪽에 무게가 실린다"로 서술. 정확도 지표는 상관계수 단독이
      아니라 rms/max_diff를 함께 보고할 것.
