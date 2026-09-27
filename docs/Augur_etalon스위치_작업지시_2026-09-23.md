# 작업지시 — etalon 끄기 스위치 추가 (2026-09-23)

대상 저장소: `C:\GHL\CAESAR` (main). 작업은 새 브랜치/worktree에서. 완료 후 아래 §6 형식으로 보고.

## 0. 배경 — 왜 필요한가

`core/doas_fit.py` `execute_varpro_fit`는 etalon sin·cos 두 선형 열을 **무조건** 설계행렬에 넣는다.

```python
# doas_fit.py 482행 (현행)
const_cols += [np.sin(fixed_e_f * pixel_idx), np.cos(fixed_e_f * pixel_idx)]
```

- 끌 방법이 없다. `fixed_e_f = 0`을 주면 cos 열이 상수항과 같아져 `LinAlgError: singular matrix`.
- 2026-09-23 Augur vs QDOAS 합성 비교(결과 메모 artifact `d09286e9-8411-48fc-8f55-2ea922fb4df4`)에서,
  etalon이 **없는** 합성 스펙트럼을 좁은 창(450–462 nm, 250 px, poly 3, 잡음 ×3)으로 풀면
  - 현행 Augur(etalon 강제 ON, f = 0.12 rad/px): NO₂ 상대 산포 **8.27 %**
  - etalon 열만 뺀 Augur: **4.09 %** / QDOAS: 4.11 % (둘의 차이 산포 0.58 %)
  - 즉 불필요한 etalon 두 열이 좁은 창에서 NO₂와 겹쳐 정밀도를 두 배 나쁘게 만든다. 넓은 창(444–471 nm)에서는 영향 작음.
- 별도 발견: `core/fit_explorer_v2_runtime.py` 404행은 정책에 `"etalon": "DISABLED"`를 **기록**하지만,
  실제 피팅 경로 `core/param_optimizer.fit_scan`(124·173행)은 etalon 주파수를 검출해 **켠 채로** 푼다.
  기록과 동작이 불일치한다.

## 1. 목표 (필수)

1. `execute_varpro_fit`에 etalon을 끌 수 있는 **명시적** 방법을 추가한다.
   - 권장: `fixed_e_f is None` → etalon 열 0개. (0·NaN·음수는 명시 오류로 거부 — 조용한 의미 부여 금지)
   - 반환 튜플의 `etalon_amp`, `etalon_phase`는 OFF일 때 `0.0`, `0.0`. `diag`에 `"etalon_enabled": False` 추가.
   - 열 순서(gas → poly → custom → sin → cos)에 의존하는 하류 인덱싱(≈810행 `a_et, b_et` 추출, 공분산·
     `c_perr` 인덱스, Golub–Pereyra 자코비안 준비부, Tikhonov 행, robust/IRLS 경로)을 전부 OFF에서도 맞게.
2. **기본 동작은 현행과 바이트 동일**. 기존 호출부·기존 FitSet은 아무것도 바꾸지 않으면 ON(현행)으로 돈다.
3. 설정에서 켜고 끌 수 있게 배관한다.
   - FitSet/시나리오 JSON에 채널별 키 추가(예: `"etalon": {"enabled": true}`). **키가 없으면 true**(하위호환).
   - OFF이면 `detect_etalon_frequency`를 **호출하지 않는다**.
   - 경로: `gui/worker.py`(853–855행 검출·캐시), `core/param_optimizer.py`(`fit_scan`), `core/fit_optimizer.py`,
     `gui/app_window_fitsetup.py`(Test Fit, 311·341행), Oculus 실시간 경로가 같은 워커/코어를 쓰는지 확인 후 동일 적용.
   - GUI: 기존 etalon 주파수 탐색 범위 설정 옆에 체크박스 하나("Fit etalon"). 시나리오 저장·복원 포함.
4. 재현성 기록.
   - 결과 파일 헤더와 `.meta.json`(run_meta)에 `etalon_enabled`와 사용 주파수(OFF면 null) 기록.
   - runid(설정 해시)에 이 값이 들어가게 한다. 단, 키가 없는 **기존 설정의 runid는 변하지 않게**(기본값 true는 해시에서
     기존과 같은 표현이 되도록) — 불가능하면 그 사실과 이유를 보고.
5. V2 기록 불일치 해소 — **동작은 바꾸지 말고 기록을 진실로**.
   - `fit_explorer_v2_runtime.py`의 정책 기록을 실제 전달값에서 만들도록 수정(현재 동작이면 `"ENABLED"` + 검출 주파수).
   - V2를 실제로 OFF로 돌릴지는 **사용자 결정 사항**. 이번 작업에서 바꾸지 말 것. 불일치가 과거 V2/V1 evidence 문서에
     어떤 영향을 주는지(기록만 틀렸는지) 목록으로 보고.

## 2. 하지 말 것

- 운영 FitSet(`C:\GHL\2026 yeosu\Output\fit setting\...`)의 기본값 변경, 운영 결과 재생성.
- 어느 창에서 etalon을 끄는 것이 맞는지 판단(별도 작업: `tools/etalon_collinearity_probe.py`,
  `diagnostics/etalon_freq_2026-09`의 근거로 사용자와 결정).
- `fixed_e_f = 0`을 "끔"으로 해석하는 방식(특이행렬 문제를 숨김).

## 3. 검증 (전부 통과해야 완료)

1. **ON 회귀 = 바이트 동일**: 기존 pytest 전체, `validate_pipeline --no-data`, `tools/test_varpro_jacobian.py`,
   `tools/test_joint_covariance.py`, `tools/test_etalon_collinearity.py`, `tools/test_varpro_synthetic_ext.py`,
   `tools/test_fit_policy.py`, `tools/test_step_limited.py`. 변경 전후 대표 스캔 몇 개의 출력 튜플이 비트 동일함을 확인.
2. **OFF 정답 재현**: etalon 없는 합성(아래 레시피)을 OFF로 풀어, 2026-09-23 메모리 내 패치본과 같은 값인지.
   - 레시피: `tools/test_varpro_synthetic_ext.py`류의 합성, 창 450–462 nm, poly 3, NO₂ 1e12 + CHOCHO·H₂O 동반,
     squeeze 1.002, shift −1.96, 잡음 3 × 6.16e-9, `np.random.default_rng(20260953)`, 300 실현.
   - 기대: NO₂ 상대 산포 ≈ 0.0409, pull SD(z) ≈ 0.97 (허용 ±0.002 / ±0.01). ON이면 ≈ 0.0827.
   - 이 비교를 새 단위테스트로 추가(실현 수는 테스트 속도에 맞게 줄이되 ON/OFF 산포 비 > 1.5를 단언).
3. **OFF 자코비안**: 해석적 Golub–Pereyra 자코비안이 OFF에서도 유한차분과 일치(기존 test_varpro_jacobian 방식).
4. **OFF 결합 공분산**: `test_joint_covariance`의 OFF 버전 — 공분산 차원·gas 블록 인덱스가 맞는지.
5. **진단 함수**: `etalon_collinearity`·`format_etalon_collinearity`가 OFF에서 `n/a`로 처리(예외 없음).
6. **배관**: FitSet에 `enabled: false` → 워커가 `detect_etalon_frequency`를 호출하지 않음(mock으로 확인),
   결과 헤더·meta에 `etalon_enabled=false`. 키 없는 기존 FitSet → ON, runid 불변.
7. CI(GitHub Actions) green.

## 4. 문서

- `README.md` 용어/설정 설명, `docs/매뉴얼_조작순서.md`의 피팅 설정 부분에 스위치 한 줄.
- `docs/Augur_소개_2026-07.md` §9.2 표의 "Etalon" 행: "FFT 검출 + sin/cos 선형화 내장 (채널별 on/off)".

## 5. 참고 코드 위치

- `core/doas_fit.py`: 118 `detect_etalon_frequency`, 136 `etalon_collinearity`, 392 `execute_varpro_fit`,
  479–483 상수열 조립, ≈810 etalon 진폭·위상 추출.
- `gui/worker.py` 241, 257, 853–855 · `core/param_optimizer.py` 124, 173 · `core/fit_optimizer.py` 58, 62 ·
  `gui/app_window_fitsetup.py` 311, 341 · `gui/app_window_save.py` 173–175, 440–442 · `core/fit_explorer_v2_runtime.py` 404.

## 6. 보고 형식

1. 변경 파일 목록과 요지
2. §3 검증 1–7 각각 통과/실패 + 수치(특히 2번의 ON/OFF 산포, SD(z))
3. runid 하위호환 여부
4. V2 기록 불일치 영향 목록(§1-5)
5. 하지 못한 것 / 판단을 사용자에게 넘긴 것
