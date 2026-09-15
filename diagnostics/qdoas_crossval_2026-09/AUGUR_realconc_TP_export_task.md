# 작업: real_conc(cm⁻³)와 실제 사용된 T/P를 출력 파일에 남기기

## 배경 / 왜 필요한가
AUGUR(CAESAR)는 fitting 결과를 ppb(대기 중 부피혼합비)로만 저장한다 — 변환 전
`real_conc`(cm⁻³, 흡수단면적 계수를 그대로 물리 단위로 환산한 값)와, 그 변환에
실제로 쓰인 스캔별 T(°C)/P(mbar)는 어디에도 남지 않는다. 이게 실제로 문제가
됐던 사례: QDOAS 외부 교차검증(`diagnostics/qdoas_crossval_2026-09/`) 중
"Augur의 ppb 숫자와 QDOAS의 SCD가 14자리나 차이 난다"는 미스터리가 발생했는데,
원인은 단순히 "ppb ≠ real_conc"였을 뿐이었다 — merge.dat에 real_conc나 실제
T/P가 남아 있었다면 애초에 생기지 않았을 혼란이다. 게다가 열분해(TD) 채널
(ANs/PNs)은 `gas_temp_override` 설정에 따라 실제로 어떤 T가 쓰였는지 코드를
직접 안 보면 알 수 없는 상태다 — 이 export가 있으면 매 스캔마다 실제 사용된
T를 그냥 파일에서 읽으면 된다.

이 작업은 `AUGUR_residual_dump_task.md`(잔차 덤프 기능, **이미 구현·커밋
완료됨** — `gui/worker.py`의 `residual_dump_path` 속성과 `_write_residual_dump()`
메서드가 그 결과물이다)와 **완전히 같은 패턴**(opt-in, 두 계산 지점 모두 패치,
회귀 없는 순수 추가)을 따른다. 그 구현을 그대로 스타일 템플릿으로 참고할 것.

## 현재 코드 상태
파일: `gui/worker.py`, 클래스 `AnalysisWorker`.

한 스캔을 피팅하는 두 지점(둘 다 `execute_varpro_fit` 직후, 잔차 덤프와 동일한
두 지점) 모두 `raw_concentrations`(=real_conc, cm⁻³, 가스별 리스트)와
`self.temperature`/`self.pressure`(=n_air 계산에 실제로 쓰인 최종 T/P — TD
채널의 `gas_temp_override`가 켜져 있으면 이미 반영된 값)를 계산 직후에 갖고
있지만, ppb로 변환한 뒤 이 두 값 자체는 버려진다.

**지점 1 — 순차 처리 경로 (2026-09-08 기준 ~line 671-716)**:
```python
raw_concentrations, real_errors = [], []
for gi, nm in enumerate(self.engine.gas_list):
    scale_div = self.engine.scaling_factors[nm]
    mult_i = self.engine.multipliers.get(nm, 1.0)
    if is_linear_mode:
        real_conc = (gas_coeffs_scaled[gi] / scale_factor) / scale_div * mult_i
        real_err  = (gas_errs[gi]           / scale_factor) / scale_div * mult_i
    else:
        real_conc = gas_coeffs_scaled[gi] / scale_div * mult_i
        real_err  = gas_errs[gi]           / scale_div * mult_i
    raw_concentrations.append(real_conc); real_errors.append(real_err)

smooth_concentrations = kalman_filter.process(raw_concentrations)

n_air = air_number_density(self.temperature, self.pressure)   # core.physics 단일 출처
...
for gi, nm in enumerate(self.engine.gas_list):
    ppb_raw    = (raw_concentrations[gi]    / n_air) * 1e9
    ...
    result[nm]                  = ppb_raw
    result[f"{nm}_Smooth"]      = ppb_smooth
    result[f"{nm}_Error"]       = ppb_err
    result[f"{nm}_TotalError"]  = ...
    result[f"{nm}_MDL"]         = 3.0 * ppb_err
    result[f"{nm}_Shift"]       = opt_shifts[gi]
    result[f"{nm}_Squeeze"]     = opt_squeezes[gi]
```

**지점 2 — 배치/병렬 청크 처리 경로 (2026-09-08 기준 ~line 952-974)**: 구조
거의 동일하지만 `is_linear_mode` 분기가 없고 `_Smooth` 컬럼도 없음(잔차 덤프
작업 때와 마찬가지로 두 경로가 완전히 대칭은 아니었음 — 잔차 덤프 패치를
실제로 어떻게 처리했는지 그 커밋을 참고해서 동일한 방식으로 처리할 것).

`self.temperature`/`self.pressure`는 같은 함수 앞부분(~line 428-434)에서
스캔마다 갱신된다:
```python
self.temperature = env_t
self.pressure = env_p
_gt = getattr(self, 'gas_temp_override', None)
if _gt is not None:
    self.temperature = float(_gt)
```
즉 이 두 값을 그대로 기록하면 override 적용 여부와 무관하게 "그 스캔에 실제로
쓰인 T/P"가 남는다 — 이게 이번 작업의 핵심 목적 중 하나(gas_temp_override가
production에서 실제로 켜져 있었는지 스캔 단위로 검증 가능해짐).

## 요구사항

1. **완전히 opt-in이어야 한다** — 는 `AUGUR_residual_dump_task.md`와 동일한
   원칙이지만, 이번엔 굳이 별도 옵션으로 만들 필요 없이 **기존 merge.dat/
   fitting 출력에 컬럼을 추가하는 형태를 우선 검토할 것**. 이유: real_conc와
   T/P는 (잔차 배열과 달리) 스칼라 몇 개뿐이라 파일 크기·성능에 미치는 영향이
   무시할 수준이고, 오히려 항상 켜져 있는 게 향후 디버깅에 유리하다. 단,
   **기존 출력 포맷/열 순서를 바꾸면 하위 호환이 깨질 수 있으므로**, 다음 중
   구현 전 반드시 확인하고 더 안전한 쪽으로 선택할 것:
   - (a) `result` 딕셔너리에 새 키를 추가하는 것만으로 최종 출력 파일(merge.dat
     계열)에 새 컬럼이 자동으로 붙는 구조인지(예: 헤더가 `result.keys()`에서
     동적으로 생성됨) 확인 — 그렇다면 그냥 추가하면 됨, 회귀 없음.
   - (b) 만약 출력 컬럼이 고정 리스트/화이트리스트로 어딘가에 하드코딩돼
     있다면(예: `core/result_io.py`나 다른 파일에), 그 리스트에도 새 컬럼명을
     추가해야 함 — 이 경우 **기존 파일과의 하위 호환(옛 파일엔 이 컬럼이
     없음)을 어떻게 처리하는 기존 관례가 있는지 먼저 파악**하고 그 관례를
     따를 것(예: 병합 시 없는 컬럼은 NaN으로 채우는 기존 로직이 있는지 등).
   - 위 (a)/(b) 중 실제로 어느 쪽인지, 그리고 최종적으로 어떤 방식을 택했는지
     보고에 명시할 것.

2. **추가할 컬럼(가스별로 반복 — `result[nm]`이 있는 곳마다)**:
   - `result[f"{nm}_RealConc"] = raw_concentrations[gi]` (cm⁻³, ppb 변환 전
     값 — 지점 1/2의 for 루프 안, `raw_concentrations.append(...)` 직후가
     아니라 **ppb 변환 루프 안**에 넣어야 gi/nm과 확실히 짝지어짐, 위 코드의
     `result[nm] = ppb_raw` 바로 옆에 추가)
   - 가스별로 반복할 필요 없이 스캔당 한 번만 필요한 것:
     `result['T_used_C'] = self.temperature` (override 반영 후 최종값, °C)
     `result['P_used_mbar'] = self.pressure` (mbar)
   - 이 두 값은 지점 1/2 둘 다에서 동일한 이름으로 추가(두 경로 결과의 컬럼
     구성이 달라지지 않도록).

3. **단위/자체검증**: 구현 후 반드시 확인할 것 —
   `ppb_recomputed = (result[f"{nm}_RealConc"] / n_air(result['T_used_C'], result['P_used_mbar'])) * 1e9`
   가 저장된 `result[nm]`(ppb)과 부동소수점 오차 이내로 일치하는지(n_air 계산식은
   `core.physics.air_number_density(T_C, P_mbar)`를 그대로
   재사용). 이게 안 맞으면 어느 시점 값을 잘못 캡처한 것.

   ⚠ (2026-09-14 갱신) n_air 계산식은 **복사하지 말고 반드시 임포트**할 것:
   `from core.physics import air_number_density` → `air_number_density(T_C, P_mbar)`.
   이 문서가 처음 쓰일 때(2026-09-08) worker.py에 박혀 있던 리터럴
   `2.68678e19`은 현재 `core.physics.N_LOSCHMIDT`(SI 정의 유도값,
   = CODATA 2018 2.686780111e19)로 통일돼 사라졌다. 두 값의 차이는 상대
   4.2e-8 이라 이 과제의 수치 결론에는 영향이 없지만, 식을 복사하면
   Augur와 검증 코드가 다시 갈라진다.

4. **성능**: 스칼라 몇 개 추가하는 것뿐이라 성능 영향은 사실상 없어야 함 —
   그래도 수만 스캔 단위 배치 처리 속도에 유의미한 변화가 없는지 간단히
   확인(예: 패치 전후 같은 데이터로 처리 시간 비교).

## 완료 기준 (Acceptance Criteria)
- [ ] 새 컬럼이 최종 merge.dat/fitting 출력 파일에 실제로 나타난다(순차·병렬
      청크 경로 둘 다).
- [ ] 위 3번의 ppb 재계산 자체검증이 모든 행에서 통과한다(허용오차 내).
- [ ] `AUGUR_residual_dump_task.md` 패치처럼 이번 것도 기존 정상 워크플로우
      (컬럼 추가를 아예 안 하는 옛 버전과 비교 시)의 다른 값들에 회귀가
      없다 — 새 컬럼만 추가되고 기존 컬럼 값은 바이트/수치 단위로 동일한지
      확인.
- [ ] `C:\GHL\2026 yeosu\Output\alpha\10s\hot\ch1\` 또는 `ch2\` 아래 실제
      ANs/PNs 데이터로 소규모 시험 실행(하루 치)해서 `T_used_C` 컬럼 값을
      직접 확인 — **이게 이번 작업의 가장 중요한 부수 효과**: 이 값이 실제로
      ~30°C(하우스키핑/앰비언트, override off) 근방인지 아니면 180/300°C
      근방(override on)인지 스캔 단위로 바로 확인할 수 있음. 결과를 보고에
      포함할 것 — 이건 별도 진행 중인 "TD 채널 실제 가스온도가 몇 도인가"
      조사의 핵심 증거가 된다.

## 범위에 포함되지 않는 것
- `t_ref`/`t_coeff`(흡수단면적 온도보정) 관련 로직 변경 — 별개 이슈, 이번엔
  건드리지 않는다.
- `gas_temp_override`의 기본값이나 활성화 로직 자체를 바꾸는 것 — 이건
  하드웨어 실측(셀 내부 온도 센서 확인) 이후에 사용자가 직접 결정할 사안.
- 이 새 컬럼들을 이용한 실제 재분석/비교 스크립트 작성 — 후속 작업.
