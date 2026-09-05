# Fit Setting Explorer 설계 정본 (2026-09)

> 상태: **설계 고정 / Phase A2·Explorer V1·Stage 0 synthetic·ROI1 및 cold·O4 portable 재현 증거 완료**
> 선행 문서: `docs/fit_optimizer_handoff.md`, `docs/NO2_인젝션_실험_핸드오프_2026-08.md`,
> `docs/ANs_분석_핸드오프_2026-07-23.md`  
> 골든 사례와 재현 메타데이터: `docs/fit_explorer_golden_inventory_2026-09.md`
> 정본 범위: 아래 계약은 Explorer와 현행 optimizer handoff에만 적용한다. 과거 NO2/채널 문서는 역사적
> 기록으로 유지하며, 별도 정리 작업 전에는 이 계약을 소급해 고치지 않는다.

## 1. 목적과 비목적

Explorer는 단 하나의 “정답 파라미터”를 예측하지 않는다. 실제 DOAS/VARPRO 엔진으로 후보를 반복
평가해, 물리적으로 허용되며 작은 설정 변화와 표본·날짜 변화에도 농도 결론이 유지되는
**robustness plateau**를 찾는다. 출력은 대표 설정, 동등 대안, 민감도, 기각/보류 근거다.

다음은 목표가 아니다.

- 잔차 RMS·perr·F검정 등의 단일 점수 최소화
- `core/fit_optimizer.py`의 폐기된 fitting-driven 창 탐색 부활
- LLM이나 ML이 핏 결과의 진실 여부를 판정하거나 숫자를 직접 선택
- 추천 설정의 자동 Apply 또는 사람 승인 없는 실행 설정 변경

현행 Test Fit은 현재 설정 안에서 poly와 shift/squeeze 등을 진단·추천하는 도구이고,
FitSet Builder는 맨바닥 초기 설정 생성기다. Explorer는 둘을 대체하지 않고, 그 위에서 여러 후보의
물리 타당성과 강건성을 비교하는 검증 계층이다.

## 2. 판정 계층과 순서

판정은 아래 순서를 바꿀 수 없다.

1. **실행 가능성**: 입력·좌표·reference coverage·엔진 실행·불변식
2. **T2 물리 건전성**: 차등 공선성, 물리적으로 상수인 계수의 거동, 가능한 종의 절대량 앵커
3. **강건성**: 인접 설정, seed, 표본, 날짜를 바꿔도 결론이 유지되는가
4. **Pareto 비교**: 살아남은 후보의 잔차 구조, 농도 변동, 불확실도, 자유도, 창 폭
5. **대표 선택**: plateau 안에서 경계와 멀고 가장 단순한 후보

T2 결과는 반드시 세 상태로 기록한다.

- `PASS`: 필요한 T2 검사가 수행됐고 위반이 없음
- `FAIL`: 수행된 T2 검사에서 물리 위반이 확인됨
- `UNAVAILABLE`: 대상 종에 적용할 물리 앵커가 없거나 필요한 입력이 없어 판단할 수 없음

Explorer의 T2 adapter는 각 gate마다 먼저 **적용 가능성**과 **필수 입력 완전성**을 판정한 뒤,
적용 가능한 gate의 결과만 합성한다. 적용 가능한 gate에서 위반이 하나라도 나오면 `FAIL`, 적용 가능한
필수 gate가 모두 실행되고 위반이 없을 때만 `PASS`, 적용 대상 gate가 없거나 필요한 입력이 하나라도
부족해 필수 판정을 끝내지 못하면 `UNAVAILABLE`이다. 현재 `fit_physics.judge_reference()`의
`exclude=False`는 단지 구현된 제외 조건이 참이 아니었다는 뜻이며, 이를 곧바로 T2 `PASS`로 매핑하지
않는다. adapter는 `abs_ratio` 등 각 gate 입력의 유한성, 대상 종의 이론 앵커 존재 여부, 표본 수를
별도 필드로 보존한다.

`UNAVAILABLE`은 `PASS`가 아니다. 특히 NO2 자체에는 O4 같은 직접 절대량 앵커가 없으므로, T3가
없는 결과는 **“물리 검증 완료”가 아니라 “내부적으로 강건한 후보”**라고만 보고한다. T3(알려진
농도 인젝션, 독립 경로, 검증된 채널 간 대조)가 있으면 항상 T2/T1보다 우선하지만, 현재 인젝션
자료는 검증된 골든 정답으로 포함하지 않는다.

T1은 후보 생성과 마지막 동률 해소에만 쓴다. 물리 FAIL을 좋은 잔차가 상쇄하는 종합점수는 만들지
않는다. 문턱과 허용오차는 기존 단일 출처 또는 검증 자료에서 오며, 근거와 버전을 기록한다.
근거 없는 기본 tolerance를 새로 발명하지 않는다. 정할 수 없으면 `UNAVAILABLE` 또는 판단 보류다.

## 3. 후보 도메인과 plateau 그래프

각 후보는 탐색 도메인에서 정확히 한 상태를 갖는다.

- `UNEVALUATED`: 아직 필요한 평가를 받지 않음
- `EVALUATED_PASS`: 해당 단계의 필수 평가를 수행하고 통과
- `EVALUATED_FAIL`: 해당 단계의 실제 평가에서 명시된 이유로 실패

예산 때문에 다음 단계로 승격되지 않은 후보는 과학적 실패가 아니다. **pruned**라는 실행 이력을
별도로 기록하되 도메인 상태는 `UNEVALUATED`로 남긴다. 이를 `EVALUATED_FAIL`로 바꾸면 plateau
경계를 인위적으로 만들게 된다.

인접성은 한 번에 한 축만 한 단계 변하는 관계로 정의한다. 초기 축은 창 시작/끝 한 grid step,
poly ±1, reference 하나 포함/제외, Link/Independent 한 단계, shift 정책 또는 범위 한 단계다.
grid와 축별 step도 실행 manifest에 기록한다.

reference 포함/제외는 기존 엔진의 `gas_list`나 fitter를 제자리에서 바꾸지 않는다. 후보마다 확정된
reference 목록과 순서로 `fitset_builder.build_engine()`을 호출해 엔진을 다시 만들고, 그 엔진에 대응하는
fitter와 `ref_props`를 함께 새로 만들거나 동일 identity의 완성된 묶음만 캐시한다. candidate identity에는
최소한 ordered gas list, 각 reference 파일 hash와 순서, wavecal hash, multiplier/scaling 및 fit 설정을
포함한다. 서로 다른 identity 사이에 엔진·fitter·`ref_props`를 섞어 재사용하지 않는다.

plateau 후보를 선언하기 전 **closure 단계**에서 그 연결 성분의 모든 one-step 이웃을 확인한다. closure는
한 번의 둘레 검사로 끝내지 않고 고정점까지 반복한다. 즉 새로 평가되어 `EVALUATED_PASS`가 된 이웃을
연결 성분에 합친 뒤 그 노드의 one-step 이웃도 다시 평가하며, 더 이상 새 PASS 노드나 대표성에 영향을
주는 미평가 이웃이 생기지 않을 때만 종료한다.
이웃이 도메인 밖이면 실제 경계이고, 평가되어 FAIL이면 관측된 경계다. 그러나 도메인 안의 이웃이
`UNEVALUATED`이면 unknown frontier다. 대표 후보까지의 경계 거리를 말하려면 필요한 frontier를
추가 평가해야 하며, 예산 종료 후에도 unknown frontier가 대표성에 영향을 주면 추천을 보류한다.

경계 거리는 후보 그래프에서 가장 가까운 도메인 밖 또는 `EVALUATED_FAIL` 노드까지의 최단
**hop 수**로 정의한다. 출력 농도만 비슷한 클러스터는 plateau가 아니다. plateau는 다음을 모두
만족해야 한다.

1. 필수 T2가 `PASS`이거나, `UNAVAILABLE`임을 명시하고 그 한계를 수용한 내부 강건성 후보일 것
2. 파라미터 공간에서 `EVALUATED_PASS` 노드들이 연결될 것
3. 인접 후보 간 과학적 결론이 근거가 기록된 tolerance 안에서 일치할 것
4. 날짜·표본 교체와 seed 변화에도 연결 성분과 결론이 유지될 것
5. 대표성에 영향을 주는 unknown frontier가 없을 것

## 4. 대표 설정과 판단 보류

plateau가 성립한 뒤 대표는 아래 순서로 선택한다.

1. 그래프 경계까지 hop 수가 큼
2. 자유 파라미터 수가 적음
3. poly가 낮음
4. 충분한 reference coverage를 유지하면서 창이 넓음
5. T1 지표는 마지막 동률 해소에만 사용

서로 다른 plateau가 동등하거나, T2가 필요한데 불가능하고 강건성만으로도 구분되지 않거나,
unknown frontier가 남거나, 표본/날짜 교체에 따라 결론이 바뀌면 `ABSTAIN`한다. 출력은 대표 하나를
강제하지 않고 `추천 가능 / 불안정 / 근거 부족` 상태와 동등 대안 1~2개를 허용한다. 자동 Apply는
어느 상태에서도 하지 않는다.

## 5. 평가 예산과 구현 순서

### 5.1 최소 수직 조각 — halving 없음

먼저 현재 FitSet 주변의 창 3개 × poly 3개 = 9개 후보를 대표 스캔 4개와 최소 2 seed로 **모두**
평가한다. 이 단계에서는 successive halving을 구현하지 않는다. CLI 표와 JSON 보고서만 만들고 GUI,
Apply, 새 최적화 프레임워크는 만들지 않는다. 후보별 per-scan 결과, 실패 이유, 실행시간을 보존한다.

여기서 최소 2 seed는 같은 deterministic shift grid를 두 번 실행한다는 뜻이 아니라, 최종 VarPro에
전달되는 **서로 다른 초기화**다. 각 seed는 명시적인 shift/squeeze 시작 후보와 그 값의 provenance를
가져야 한다. 현 `param_optimizer.fit_scan()`은 deterministic grid에서 최선 하나를 고른 뒤 최종 fit을
한 번 호출하므로 이 계약을 직접 제공하지 않는다. 따라서 최소 Explorer는 evaluator에 작은 controlled-start
주입 경로를 추가하거나, 동일 bounds·정책 아래 서로 다른 shift/squeeze 시작값으로 최종 fit을 직접
호출해야 한다. 그 경로가 구현되기 전에는 “2 seed 평가 완료”로 보고하지 않는다.

**V1 구현 완료 범위**: `core/fit_explorer.py`와 `tools/fit_explorer.py`는 3개 translated window ×
3개 poly = 9개 후보를, 균등 선택한 대표 alpha 4개 × controlled start 2개로 전수 평가한다
(총 72 fit 시도). 두 start는 공통 유효 target shift bounds의 내부 사분위점이며, target의 최종 VarPro
shift/squeeze 초깃값만 바꾼다. 다른 gas의 초깃값과 두 실행의 유효 bounds는 동일하다. V1은 후보별
실행/T2 상태와 요약치를 기록하지만 **ranking, plateau/closure 판정, Apply는 하지 않는다**.

실행 인자와 현재 CLI 계약은 추측해 복사하지 말고 다음 도움말을 정본으로 확인한다.

```text
python tools/fit_explorer.py --help
```

### 5.2 규모 확장 — successive halving 필수

| 단계 | 대략적 규모 | 평가와 목적 |
|---|---:|---|
| Stage 0 | 100~300 후보 | 핏 없이 창 폭·coverage·좌표·공선성·정적 불변식 검사 |
| Stage 1 | 50~100 후보 | 상태가 다른 대표 4스캔 × 최소 2 seed; 명백한 실패만 제거 |
| Stage 2 | 10~20 후보 | 12~24 균등 스캔 × 멀티시드; 잔차·농도·shift·표본 안정성 |
| Stage 3 | 3~5 후보 | 날짜별 시간 연속 블록; step_limit과 시간 연속성 |
| Final | 1~3 후보 | 독립 홀드아웃 날짜, 가능하면 검증된 T3 |

Stage 0의 최소 사전검사는 candidate 정수 inclusive bounds, engine wave의 유한·단조성, gas 순서와
engine에 처리된 reference 배열의 shape/finite/index coverage, target 존재, poly 자유도, 그리고
`core.fit_physics.COLLIN_HI_DEFAULT`를 **초과한** target differential multiple-R만 검사한다. 진단값이
없거나 계산이 실패하면 PASS로 간주하지 않고 `UNAVAILABLE`로 중단한다. 이 경우에도 candidate의
canonical evaluation state는 새 상태를 만들지 않고 `UNEVALUATED`로 유지하며 preflight 상태를 별도로 기록한다. engine reference는 이미
보간·외삽된 배열이므로 원본 spectroscopy 파일의 실제 파장 coverage는 이 검사로 증명할 수 없으며
별도 provenance가 생길 때까지 `UNAVAILABLE`로 기록한다. Stage 0 PASS도 실제 fit 전에는 UNEVALUATED다.

100개 이상 규모에서는 halving이 선택 사항이 아니라 실행 예산의 필수 장치다. 단, Stage 1은 seed
하나나 같은 상태의 2~3스캔만으로 공격적으로 제거하지 않는다. 애매한 후보는 승격하며, 조기 pruning은
과학적 FAIL로 기록하지 않는다. 최종 후보군에는 §3의 one-step-neighbor closure를 수행한다.

## 6. 재현성과 보고서 계약

모든 실행은 다음을 기록해야 한다.

- source data/fixture manifest와 각 파일 hash, git `HEAD`, 정규화한 tracked diff의 hash, untracked
  manifest(저장소 상대경로와 파일 hash). 단순 dirty bool은 보조 표시로만 사용
- wavecal·reference 파일 hash와 **reference 순서**
- alpha row/file identity, 표본 방식, 날짜/상태, seed grid 전체
- `allow_negative_gas`, `fit_sign`, W 구성, window 양끝의 inclusive/exclusive 규약
- px/nm 변환과 alpha 좌표↔engine reference 좌표의 provenance
- poly, shift/squeeze 정책·초깃값·bounds, step_limit
- multiplier, scaling factor, etalon 설정/검출값, T/P와 온도 override
- 각 gate의 입력, 결과(`PASS/FAIL/UNAVAILABLE`), tolerance 값과 그 출처
- pruning/승격/추가 closure 평가의 이유와 실행시간

Phase A 테스트는 정확한 부동소수점 스냅샷이 아니라 과학적·정책적 불변식을 검증한다. 현재
`tools/test_fit_policy.py`와 `tools/test_test_fit_dialog.py`가 다음 정책 계약을 고정하며 **Phase A2의
이 부분은 완료**다: gas 계수 부호 정책은 명시 bool이어야 함, seed와 최종 fit에 같은 정책 전달,
음수 O4도 절대량 위반으로 검출, `ac1`은 부호가 아닌 크기로 판정, 시나리오 저장·복원과 worker 전달.
`tools/test_fit_explorer.py`는 V1의 3×3 후보, 서로 다른 2 start, 동일 bounds/target-only 초기화, 보수적
T2 tri-state, 좌표·상태·출력 충돌 방지와 JSON/no-Apply 계약을 synthetic으로 고정한다. 모든 JSON은
임시 파일을 fsync한 뒤 원자적으로 교체하며, 평가가 실행된 보고서는 입력 hash, reference/gas 순서,
표본 선택, `HEAD`, 정규화 tracked diff hash와 untracked manifest를 기록한다. 기존 FitSet에
`allow_negative_gas`가 정확한 bool로
저장되어 있지 않으면 CLI 플래그로 추정하지 않고 재저장/마이그레이션 전까지 `ABSTAIN`한다.

ROI1의 정책별 behavioral branch와 단일행 fixed-shift grid/default Limit/Center 초기화 관측은
portable manifest/result로 재현된다. 이는 full external golden이나 T2/plateau 증거가 아니며,
검증하는 것은 두 분기의 정성적 순서이지 플랫폼 간 수치 동등성이나 과학적 tolerance가 아니다.
Limit/Center 측정은 offline `param_optimizer.fit_scan()` 범위이며 worker end-to-end가 아니다.
파일 순서/표본 교체, worker end-to-end, halving,
plateau/closure/ranking은 아직 완료가 아니다.

Cold/O4는 hash-pinned 균등 표본 15개에서 두 gas 부호 정책 모두 현재 코드로 T2 `FAIL`을 재현했다.
nonnegative 정책은 O4 중앙 절대량비 230.998배로 절대량 게이트가 기각했다. signed 정책은 절대량비가
2.207배라 그 게이트는 통과했지만, O4 계수 CV가 타깃 CV보다 큰 상수성 위반으로 기각됐다. 따라서
과거 수치와의 비교에는 부호 정책까지 포함해야 하며, 이 결과는 농도 진실·T3·plateau를 확정하지 않는다.

## 7. ML·LLM과 탐색 가속

초기 구현에는 ML, LLM, Bayesian optimization을 넣지 않는다. 우선순위는 결과 캐시, 중복 후보 제거,
Stage 0 사전검사와 예산 측정이다. 그래도 필요하면 혼합형·불연속·게이트형 공간에 맞는 tree-based
또는 constrained surrogate를 별도 검토한다. 표준 GP+단일 expected improvement를 기본값으로 두지 않는다.

ANs 퇴화 분류기는 별도 트랙이며 결과 삭제/농도 대체가 아니라 flag와 재시딩 요청만 할 수 있다.
독립 라벨이 확보되고 명시적 규칙보다 우수할 때만 채택한다. LLM은 기각 이유 설명, 보고서 작성,
필드로그 요약처럼 언어가 필요한 바깥 계층에만 쓰며 핵심 판정자가 아니다.

## 8. 단계별 완료 상태

- [x] 설계 원칙 합의
- [x] Phase A2 정책 계약: explicit `allow_negative_gas`, seed/final 일치, signed T2, `|ac1|`, 저장·복원
- [x] Explorer V1 synthetic 계약: 3×3 × 대표 4스캔 × controlled start 2개, 보수적 T2, 원자적 보고서
- [x] ROI1 외부 실데이터의 hash-pinned portable behavioral evidence (정책 상호작용만, raw 미커밋)
- [ ] full external golden/T2/plateau evidence
- [x] cold/O4 외부 실데이터의 현재 코드/hash·양쪽 부호 정책 기준 T2 재측정
- [x] synthetic CI 계약 테스트
- [x] optional external-data suite: manifest 미지정만 SKIP, 명시 manifest의 missing/hash mismatch는 FAIL
- [x] Stage 0 최소 사전검사: fit-free 정적 FAIL/UNAVAILABLE, 공선성 단일 기존 문턱, no-Apply
- [ ] 규모 확장 successive halving
- [ ] plateau graph, closure, hop-distance, abstention
- [ ] 독립 날짜 및 검증된 T3 최종 평가
