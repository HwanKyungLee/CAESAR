# Fit Explorer 골든 데이터 인벤토리 (2026-09)

> 상태: **ROI1 portable 재현 증거 완료 / cold·O4 재측정 미완료**
> 설계 정본: `docs/fit_explorer_design_2026-09.md`

## 1. 증거 라벨

이 문서는 관측과 해석을 섞지 않는다.

- `CONTRACT`: synthetic/unit 회귀로 고정된 코드·정책 계약
- `REPRODUCED`: 명시된 입력 hash와 설정으로 현재 코드에서 다시 실행해 확인
- `HISTORICAL`: 과거 핸드오프에 수치가 있으나 현재 checkout/hash에서 재측정 전
- `CANDIDATE`: 골든 fixture 후보이며 외부 진실이 아님
- `UNRESOLVED`: 물리 정체성 또는 진실값을 현재 자료로 확정할 수 없음
- `EXCLUDED_T3`: 검증된 독립 T3로 인정하지 않음

`CANDIDATE`의 낮은 잔차나 프로덕션 일치는 농도 진실의 증명이 아니다. 재측정이 끝나기 전 과거 수치를
정확한 현재 기대값으로 복사하지 않는다.

## 2. 현재 정책 계약 — Phase A2 완료

| 계약 | 증거 | 상태 |
|---|---|---|
| `allow_negative_gas`는 명시 bool이며 조용한 기본값이 없음 | `tools/test_fit_policy.py` | `CONTRACT` |
| 같은 부호 정책이 seed와 최종 VARPRO fit에 전달됨 | `tools/test_fit_policy.py` | `CONTRACT` |
| O4 계수의 부호가 음수여도 절대량은 크기로 판정 | `tools/test_fit_policy.py` | `CONTRACT` |
| 잔차 자기상관은 `abs(ac1)`로 집계·퇴화 판정 | `tools/test_fit_policy.py`, `tools/test_test_fit_dialog.py` | `CONTRACT` |
| 단일/채널 시나리오가 gas 부호 정책을 저장·복원하고 worker에 전달 | `tools/test_test_fit_dialog.py` | `CONTRACT` |
| 3 window × 3 poly 후보와 서로 다른 controlled start 2개 | `tools/test_fit_explorer.py` | `CONTRACT` |
| 두 start는 동일 유효 bounds에서 target 초깃값만 변경 | `tools/test_fit_explorer.py` | `CONTRACT` |
| T2 입력/앵커가 불완전하면 PASS가 아니라 `UNAVAILABLE` | `tools/test_fit_explorer.py` | `CONTRACT` |
| 좌표·상태·입력/출력 충돌 방지와 JSON/no-Apply | `tools/test_fit_explorer.py` | `CONTRACT` |

이 완료 표시는 정책 단위 테스트의 완료다. 아래 실데이터 골든, worker end-to-end, plateau 판정 완료를
뜻하지 않는다.

V1 CLI는 9개 후보 × 대표 alpha 4개 × start 2개, 총 72 fit 시도를 수행한다. 후보 ranking,
robustness plateau/closure 주장과 Apply는 범위 밖이다. 실행법은 인자를 문서에 중복 고정하지 않고
`python tools/fit_explorer.py --help`에서 확인한다. 모든 JSON은 임시 파일을 fsync한 뒤 원자적으로
교체하고, 평가가 실행된 보고서는 입력 파일 hash, reference/gas 순서, 표본 선택과 git
`HEAD`/tracked diff hash/untracked manifest를 남긴다.
구 FitSet에 `allow_negative_gas`가 정확한 bool로 저장되어 있지 않으면 임의 기본값을 쓰지 않고,
시나리오를 재저장하거나 명시적으로 마이그레이션할 때까지 `ABSTAIN`한다.

## 3. ANs/ROI1 후보 — 정체성과 진실값을 분리

`roi1`/`ch1`은 이 핏 사례를 찾기 위한 **운영 alias**다. 이것이 물리적으로 ANs 셀인지 PNs 셀인지,
또는 차분 부호가 어느 쪽인지에 관해서는 문서·하드웨어 단서가 충돌한다. 물리 정체성은
`docs/ANs_분석_핸드오프_2026-07-23.md`에 따라 `UNRESOLVED`이며 현장 배관 확인 또는 독립 인젝션
전에는 확정하지 않는다. 파일명 `ANs`/`PNs`와 `data_label`을 진실로 사용하지 말고 wavecal/ROI와
원본 채널 provenance로 매칭한다.

과거 기록 후보:

| 사례 | 과거 관측 | 증거 해석 | 현재 상태 |
|---|---|---|---|
| 고정 shift −6 px, nonnegative gas | 로컬 재측정: NO2 **95.9193 ppb**, RMS/signal **19.6327%**, \|ac1\| **0.996908** | 고잔차 behavioral branch | `REPRODUCED` |
| 고정 shift −6 px, signed gas | 로컬 재측정: NO2 **3.61583 ppb**, RMS/signal **3.60902%**, \|ac1\| **0.174020** | production-consistent 저잔차 behavioral branch; 외부 진실 아님 | `REPRODUCED` |

따라서 문서와 테스트에서 95.9 ppb 사례는 “틀린 농도라는 T3 정답”이 아니라 **같은 스캔에서 더 나쁜
잔차·퇴화 의심 분기 거동을 재현하는 failure fixture**로 쓴다. 약 3.6 ppb 사례는 “진짜 해”가 아니라
**production-consistent candidate**라고 부른다.

재측정 시 아래를 확정한다.

- 정확한 alpha 파일 hash, 행 identity(`row_idx`와 데이터행 순번을 구분), 날짜/시간
- wavecal 및 모든 reference 파일 hash와 reference 순서
- engine/scenario hash, git hash와 dirty diff 식별자
- seed grid 전체(`seed_range`, `seed_step`, 평가 순서), 고정 shift grid
- multiplier와 scaling factor/decade normalization
- `allow_negative_gas`, `fit_sign`, W, window 양끝 포함 규약
- alpha px → engine px 변환, absolute center
- poly, shift/squeeze mode·값·bounds, step_limit
- etalon on/off, 주파수 범위와 검출값
- T/P, gas temperature override와 cavity 관련 설정
- 후보별 농도, RMS/signal, `|ac1|`, 수렴/경계 접촉, T2 상태

2026-09-03 재측정은 `2026-07-03-001_ANs_alpha_trace.dat`의 `row_index=0`(파일 내 첫 데이터행),
원본 FitSet SHA-256 `66c5835e…08505`, alpha SHA-256 `5a54b6a5…da01f`, wavecal
`e5213305…22067`, ordered refs `CHOCHO/H2O/NO2`(`a3fd7313…a4c92`, `bcc69cd6…3965`,
`9a0227d1…3ab1`)로 수행했다. suite는 hash-pinned 원본 FitSet을 한 번 읽고 각 case의 런타임 복사본에
정확한 bool 정책을 주입한다. 별도 migrated FitSet 파일은 증거 의존성이 아니다. 두 실행은 window
detector px `599..1270`(양끝 포함), poly 4, squeeze 1.0 Fix, shift −6 Fix이며 정책만 달랐다.
이 비교는 95 ppb 분기가 단순히 shift만의 속성이 아니라
**gas 계수 부호 정책과 결합된 현상**임을 보여준다. signed 저잔차 후보 역시 T3 진실값은 아니다.

내구성 있는 증거는 `diagnostics/fit_explorer/roi1_manifest_v1.json`과
`roi1_result_v1.json`에 있다. manifest에는 데이터 루트 아래의 논리 상대경로·basename·SHA-256만
있으며 raw/alpha/reference 파일 자체는 커밋하지 않는다. `<LOCAL_DATA_ROOT>`는
실행 때만 `--data-root`로 주며 결과에 기록되지 않는다. 재실행은 다음과 같다.

```bash
python tools/test_fit_explorer_external.py --manifest diagnostics/fit_explorer/roi1_manifest_v1.json --data-root <LOCAL_DATA_ROOT>
```

결과는 생성 기준 commit `fd5f93d…8641b`, 그 이후 suite 변경의 tracked diff hash, manifest hash와
artifact self-exclusion을 명시한다. 두 `REPRODUCED` 라벨은 hash-pinned 입력에서 현재 코드가 동일한
두 **정책 상호작용의 behavioral branch**를 재실행한다는 뜻일 뿐, ROI1의 물리 채널 정체성,
3.6 ppb의 진실성, robustness plateau 또는 full golden/T2 검증을 뜻하지 않는다.
manifest의 회귀 판정도 nonnegative 분기의 농도·RMS/signal·`|ac1|`가 signed 분기보다 각각 크다는
**정성적 순서 불변식**뿐이다. 이는 플랫폼 간 수치 동등성이나 과학적 tolerance를 정의하지 않는다.

현재 checkout HEAD의 기준 hash는 실행 시 manifest에 다시 기록한다. working tree가 dirty이면 HEAD만으로
재현성을 주장하지 말고 변경 diff hash도 함께 남긴다.

같은 hash-pinned 첫 데이터행에서 current-code 재측정을 추가했다. signed-gas 고정 shift
`-7.0..0.0 px`(0.5 px 간격)는 각 점의 농도·RMS/signal·`|ac1|`를 관측값으로만 보존한다.
기본 `Limit -10,0.5` 경로는 `seed_range=15 px`, `seed_step=0.25 px`의 선형-fit RMS 격자로
초기화를 고른 뒤 최종 VarPro를 실행했다. 비교용 `Center -5.25,3.75` 경로는 격자 시딩 없이
선언 중심에 앵커된 bounds `[-5.75,-4.75]`를 만들지만, 실제 `fit_scan()` theta0는 현재 shift 0을
그 bounds 안으로 clip한 `-4.75001`이다. 즉 **중심에서 초기화됐다는 증거가 아니며**, 그 실제
theta0·bounds를 그대로 기록했다. 둘 다 단일 alpha 행을
`param_optimizer.fit_scan()`으로 실행한 **offline 관측**이며, `gui.worker`의 시간연속 carry-over,
retry/pre-calibration, QC까지 거친 end-to-end 검증이 아니다. 따라서 이 결과는 Center의 일반 우월성,
plateau, T2/T3 진실을 주장하지 않는다.

## 4. Cold/O4 후보

과거 cold 사례는 O4가 T1에서 매우 좋아 보이지만 fitted amount가 물리 기대보다 수십~수백 배 커져
T2가 기각하는 정책 사례다. 숫자(예: 89배 또는 229배)는 서로 다른 실행 문맥이 섞여 있으므로 현재
입력 hash와 설정을 고정하기 전 단일 골든 숫자로 채택하지 않는다.

골든 판정은 다음 property다.

- 동일 manifest에서 O4 포함 후보가 통계 개선만으로 대표 추천을 이기지 못한다.
- T2 절대량 계산은 계수 부호와 무관하게 magnitude를 사용한다.
- 물리 입력이 실제로 없으면 FAIL을 날조하지 않고 `UNAVAILABLE`이다.
- O4 제외 후보의 농도값을 외부 진실이라고 부르지 않는다.

재측정 manifest에는 §3의 공통 항목과 함께 O4 이론량 식, 산소 몰분율/압력/온도, ZA가 I0에 사용된
여부와 그 provenance를 기록한다.

## 5. Cold/PNs 및 기타 후보

- cold 2026-05-26 production 결과의 약 3.5 ppb 기록은 `HISTORICAL`이며 내부 재현 후보이지 T3가 아니다.
- PNs 다수 날짜 자료는 날짜/상태 홀드아웃과 채널 매칭 후보지만, 구체 fixture는 아직 선정하지 않았다.
- 파일 순서를 바꿔도 같은 판정이 나오는지, 표본 일부를 교체해도 같은 plateau에 남는지는 Explorer
  구현 후 별도 property로 검증한다.

## 6. T3 제외 규칙

현재 NO2 인젝션/ZA/He 관련 기록은 프로토콜 또는 분석 후보이지, 이 Explorer가 사용할 수 있도록
독립 농도·경로·보정과 hash가 검증된 골든 T3가 아니다. 따라서 모두 `EXCLUDED_T3`로 두며 Final
판정의 외부 진실로 사용하지 않는다. T3가 없을 때 결과 라벨은 “내부적으로 강건”을 넘지 않는다.

## 7. Fixture와 CI 분리

CI의 **synthetic 계약 테스트**는 과학적 진실을 증명하지 않고 V1의 후보/초기화, 보수적 T2,
좌표·상태, 안전한 JSON/no-Apply 경계만 검사한다. pruning, graph closure/plateau와 실데이터 manifest
재현은 아직 이 테스트가 검증하지 않는다.

실측 alpha/raw/R 파일을 쓰는 검사는 **optional external-data suite**로 분리한다. manifest 인자와
환경변수가 모두 없을 때만 이유가 명시된 `SKIP`을 출력한다. manifest가 명시된 뒤에는 필요한 파일이
전부 없더라도 missing 또는 hash mismatch를 `FAIL`로 처리한다. 외부 suite 결과는 다음을 남긴다.

- suite 버전, 현재 git/dirty hash, fixture manifest hash
- 수행/실패/SKIP 사례 목록과 이유
- 각 골든 사례의 `REPRODUCED` 승격 여부

## 8. 아직 필요한 인벤토리 작업

1. ~~로컬 데이터에서 ROI1 failure/production-consistent 후보의 정확한 파일·행을 다시 찾는다.~~
2. ~~필요한 alpha·wavecal·reference·FitSet 의존성을 portable manifest로 고정한다.~~
3. raw data는 커밋하지 않고 외부 suite 전용으로 유지한다.
4. ~~current code에서 fixed shift grid와 default/Center 경로를 둘 다 재측정한다.~~
5. O4 사례를 동일 manifest로 재실행해 T2 tri-state와 magnitude 판정을 확인한다.
6. cold/O4는 그 뒤에만 `HISTORICAL`에서 `REPRODUCED`로 승격한다.
