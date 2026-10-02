# Augur 전 기능 심층 점검 보고서 (2026-10-02)

> 코드 기준 `dcfb50b`. GUI를 실제 여수 데이터로 직접 조작하고, 실행한 기능마다 구현 코드를 읽었다(전문 코드리뷰 관점).
> 코드 수정 없음. 모든 출력은 스크래치 폴더로 보냈고 운영 Output·R npz에는 쓰지 않았다.
> 섹터별 전문(무엇인가 / 왜 이렇게 만들었나 / 써본 결과 / 문제점 / 개선 / 코드 리뷰 / 잘 된 점)은 같은 폴더의 6개 파일에 있다.

| 파일 | 섹터 | 조작한 것 |
|---|---|---|
| [s1_setup_left.md](s1_setup_left.md) | Setup 왼쪽 패널 | 채널 탭, 레퍼런스(Lock·Mask·x1e), 핏 범위, 파라미터, 정책표, RUN/STOP(1·3·8일), F5 재진입, 실행 중 설정 변경 |
| [s2_setup_right.md](s2_setup_right.md) | Setup 오른쪽 | Status, Audit Day(raw 2.4 GB), Cavity·Override·Detector 값 변경 후 결과·헤더 비교, R(λ)·Trend·Pipeline Health |
| [s3_monitor.md](s3_monitor.md) | Analysis Monitor | 하위 탭 4개, Fast/Step 실시간 갱신, 3일 런, 표·그래프 클릭 replay, 마우스 확대 |
| [s4_resultlab.md](s4_resultlab.md) | Result Lab | 파일 6종 열기, QC·시프트, Calculator, Stats, Export·Merge·PNG 산출물 헤더 검사, 74,667행 대용량 |
| [s5_plotmaker.md](s5_plotmaker.md) | Plot Maker | 연구용 그림 3종 직접 제작, 모드 6개, Publish·Batch·CSV 출력물 검사 |
| [s6_dialogs.md](s6_dialogs.md) | 도구 창 | 실제 raw로 알파 생성, R Calibrator, 파장 보정, 레퍼런스 생성(HITRAN), Test Fit 최적화, Mask |

표기: **[치명]** 결과가 틀리거나 실패를 숨김 / **[높음]** 사용자를 막거나 오도함 / **[중간]** 마찰 / **[낮음]** 다듬기.
**(실측)**은 재현했다는 뜻이고 **(코드)**는 읽어서 추정했다는 뜻이다. ✔ 표시는 코디네이터가 코드를 직접 다시 확인한 항목이다.

---

## 1. 지금 운영에 영향이 있는 것 — 먼저 확인할 것

1. **✔ 현재 코드로는 핫 알파를 만들 수 없다.** [치명·실측]
   - `_block_average`의 빈 입력 분기는 값을 5개 반환하는데, 호출부는 6개로 받는다(`gui/worker.py:2482` vs `:2503`).
   - 여수 핫 raw에는 He 블록이 없어서 매번 이 분기를 탄다. 원인 커밋은 `f700cb1`(2026-09-21)이다.
   - 그런데 화면에는 100 %와 "Alpha generation complete"가 뜨고, 실패할 때마다 %TEMP%에 58 MB가 남는다.
   - 운영 핫 알파(09-19)는 이 회귀 이전 산물이다. **9/21 이후 핫 알파를 다시 만든 적이 있다면 결과물이 실제로 생겼는지 확인할 것.**
2. **결과 `.dat` 헤더가 채널별 설정이 아니다.** [치명·실측]
   - Poly, Fit Range, λ, Robust, Constraints 줄에는 **저장 시점 화면에 떠 있던 채널의 값**이 모든 채널 파일에 찍힌다(`app_window_save.py`).
   - 예: CH2 파일 첫 줄은 "Poly3 444-471nm"인데, 그 아래 헤더는 "Poly 4 / 429.5-462 nm"다.
   - `.meta.json`의 d·RL과 qc 블록(λ·Robust)도 같은 문제가 있다(`app_window_channels.py:191-219`).
   - **기존 운영 결과 파일의 헤더도 같은 방식으로 기록됐을 가능성이 높다.** 재현성 원칙 4번 위반이다.
3. **"settings frozen for this run" 문구가 사실이 아니다.** [치명·실측]
   - RUN 도중 QC K를 바꾸면 그 런 결과에 그대로 적용된다(1,976행 NaN).
   - Poly·λ·Robust를 바꾸면 헤더와 meta에 기록되지만, 실제 핏은 바꾸기 전 값으로 돌았다.
4. **✔ R npz가 통째로 덮어써질 수 있다.** [치명·실측]
   - 누적 npz를 읽다 실패하면, 새로 계산한 knot만으로 저장한다(`tools/rt_precompute.py:541`).
   - 운영 R_cold 사본으로 재현했다: knot 667개 → 1개.
   - 저장이 원자적이지 않고 백업도 없다. 저장 중에 창을 닫으면 `terminate()`로 파일이 잘릴 수 있다.

## 2. 프로그램 전체에 반복되는 패턴 6가지

결함 대부분은 아래 여섯 패턴의 사례다. 하나하나 고치기보다 **패턴 단위로 고치는 편이 싸다.**

### A. 실패를 성공으로 보고한다

| 어디서 | 실제 상황 | 화면 표시 |
|---|---|---|
| 병렬 피팅 | 실패, 결과 0건 | "All files analyzed successfully" |
| 핫 알파 생성 | 크래시 | "complete" |
| 핏 범위 | wavecal 밖 → 전체 범위로 핏 | "성공" ✔ |
| 레퍼런스 | 0개인 채로 핏 | "성공" |
| Mask | NO2 −1.3e88 ppb | "Success" |
| Pipeline Check | 아무것도 검사 안 함(SKIP만) | "ready to fit" ✔ |
| Batch Publish | 덮어써서 파일 1개 | "2 saved" ✔ |
| Result Lab PNG | 빈 37 px 띠 | "saved" |
| R Calibrator | knot 0개 | "R(t) saved" |
| 표 5,000행 cap | 7,528행이 표에서 빠짐 | 안내가 "Completed!"에 덮임 ✔ |

→ **고칠 방향:** 완료 처리 경로 하나에 "성공 조건"(결과 행 수 > 0, 산출 파일 수 = 요청 수, 검사 수 > 0)을 두고, 그 조건이 맞을 때만 성공 문구를 띄운다.

### B. 기록이 실제와 다르다 (재현성 원칙 4)

- 결과 헤더와 meta가 화면에 떠 있는 위젯 값을 읽는다(1번 섹션 2·3번 항목).
- 알파 입력에서는 d·RL·ε·dark·flag가 결과에 아무 영향을 주지 않는다. 그런데 헤더는 "RL 0.5, Stray ON"이라고 쓰고 runid도 바뀐다.
- Export·Merge·Calculator 산출물에는 git 해시, 실제로 쓴 K, 구간, 시프트, 입력 경로가 없다.
- 레퍼런스와 wavecal 파일에도 생성 조건(T/P, 쌍 목록, 계수)이 없다.
- Mask는 어디에도 기록되지 않고, Lock하거나 탭을 바꾸면 사라진다.

→ **고칠 방향:** 헤더와 meta는 오직 `_run_frozen['configs'][ch]`에서 만든다. 산출물마다 provenance 블록을 공통 함수 하나로 찍는다.

### C. 시간대 표기가 없다

- 핏 결과는 UTC다. R trend, Audit, 일부 CSV는 KST다. 그런데 화면 어디에도 표기가 없다.
- 그 결과 생기는 일:
  - Plot Maker의 야간 음영이 UTC 시각 위에 칠해진다(KST 낮이 '밤'으로 표시).
  - Diurnal 시프트가 이중으로 적용된다.
  - UTC 값이 `time_KST` 열 이름으로 저장된다.
  - 주석 시각이 +9 h 어긋난다 ✔.
  - R Breaks 입력이 KST와 UTC 사이에서 모호하다.
  - 05-20을 불러오면 05-19 파일이 생긴다.

→ **고칠 방향:** 데이터셋마다 tz를 메타에서 읽어 들고 다닌다. 표시 tz는 전역 설정 하나로 정하고, 모든 시간축 라벨에 "(UTC)/(KST)"를 붙인다.

### D. 실행 중이거나 이전 상태가 새어 든다

- **✔ RUN 재진입 가드가 없다.** F5를 누르면 워커가 이중으로 돌고, STOP 뒤에도 옛 워커가 남는다.
- 단일 채널 런은 화면의 라이브 엔진을 같이 쓴다. 그래서 실행 중에 탭을 바꾸면 cold 레퍼런스로 핏한다(AT_BOUND 9 → 300건).
- 파일을 바꾸거나 RUN을 다시 해도 이전 통계, 제목, 상세 패널, Fit View가 남는다.
- **✔ Result Lab의 x 자동범위가 한 번 꺼지면 다시 켜지지 않는다.**
- Test Fit의 Apply가 **추천을 계산한 채널이 아니라 지금 활성 채널**에 적용된다.

→ **고칠 방향:** RUN 동안 입력을 잠근다. 단일 채널도 config로 빌드한 독립 엔진을 쓴다. "새 파일·새 런" 진입점 하나에서 상태를 초기화한다.

### E. 채널 정체가 하드코딩돼 있거나 반대로 들어가 있다

- **✔** `app_window_dataload.py:317`의 문구가 "CH1 PNs 180°C + CH2 ANs 300°C"다. 철회된 판정이다.
- 알파 생성의 폴백 roi 매핑이 반대다(`app_window_inputs.py:234`).
- 알파 생성 기본 매핑이 탭 번호 기준이라, cold raw가 ANs 설정으로 처리된다.
- **✔** Pipeline Health의 mean α가 3채널을 열 번호로 섞은 평균이다.
- Monitor의 비활성 채널 그림을 활성 채널 엔진으로 계산한다(최대 18.8 % 차이).

→ **고칠 방향:** 채널 이름·온도·roi는 `raw_parser`(또는 fitset의 data_label) 단일 출처에서만 가져온다.

### F. 설계 의도와 실제 동작이 어긋난다

| 무엇 | 주석·문구 | 실제 동작 |
|---|---|---|
| ✔ Result Lab x 자동범위 | "다 그린 뒤 되돌린다" | 되돌리는 코드 없음 |
| Plot Maker Theme | "개별 지정 보존" | 사용자가 정한 선 굵기를 덮어씀 |
| R npz 저장 | "절대 덮어쓰지 않는다" | 덮어씀 |
| 알파 스풀 | "예외 경로도 정리한다" | 정리 안 함 |
| Reapply 툴팁 | "OK RMS% re-judge" | 재판정 효과 0 |
| Wavecal 팝업 | "applied to the system instantly" | 엔진 축·경로는 옛 값 그대로 |

→ 주석은 정확한데 구현이 빠진 경우가 많다. 고치기 쉬운 편이다.

## 3. 섹터별 핵심 결함 (상세는 각 파일)

| # | 등급 | 섹터 | 결함 | 위치 |
|---|---|---|---|---|
| 1 | 치명 | 도구 | ✔ 핫 알파 생성 크래시 + "complete" 표시 | worker.py:2482/2503 |
| 2 | 치명 | Setup좌 | 헤더·meta가 채널별이 아니라 화면 값 | app_window_save.py, channels.py:191-219 |
| 3 | 치명 | Setup좌 | 실행 중 QC 변경이 그 런에 적용, "frozen" 거짓 | app_window_run.py |
| 4 | 치명 | Setup좌 | ✔ wavecal 밖 핏 범위 → 전체 범위 핏 + 성공 | worker.py:215-222 |
| 5 | 치명 | Setup좌 | 단일 채널 런 중 탭 전환 → 다른 레퍼런스로 핏 | run.py:338, channels.py:284 |
| 6 | 치명 | Setup좌 | ✔ F5 재진입 → 이중 워커·고아 워커 | run.py:33-64 |
| 7 | 치명 | Setup좌/도구 | Mask: 기본값이 px, NO2 −1.3e88에도 Success, 다채널에선 무시되고 기록 없음 | fitsetup.py:498-523 |
| 8 | 치명 | 도구 | ✔ R npz 로드 실패 → 누적 knot 소실 | rt_precompute.py:541 |
| 9 | 치명 | 도구 | Test Fit Apply가 다른 채널에 적용 | fitsetup.py:345-355 |
| 10 | 치명 | Setup우 | ✔ raw 파일을 I₀로 받음(시각 열 3715개) | app_window_inputs.py:548 |
| 11 | 치명 | Result Lab | ✔ 그래프 점 클릭이 절대 동작 안 함(Scan detail 불가) | ui_result_viewer.py:1024 |
| 12 | 치명 | Plot Maker | 야간 음영을 UTC 위에 칠함 | modes.py:520-536 |
| 13 | 높음 | Result Lab | ✔ α 찾기가 핏 파일 자신을 고르고, 맞는 파일이 있어도 다른 스캔을 그림 | ui_result_viewer.py:1170 |
| 14 | 높음 | Result Lab | Export QC가 화면과 다름, 산출물 provenance 없음, BOM CSV 못 엶 | :1325-1373, :1412 |
| 15 | 높음 | Plot Maker | ✔ Batch Publish 덮어쓰기, ✔ CSV 보간·외삽 날조, ✔ 주석 시각 파서 오류 | widget.py:2803, modes.py:891, widget.py:871 |
| 16 | 높음 | Monitor | ✔ 실시간 런 중 확대가 1.5 s 만에 풀림, ✔ 5,000행 cap 안내 덮임 | monitor_widget.py:533, results.py:219/279 |
| 17 | 높음 | Monitor | 비활성 채널 Components를 활성 엔진으로 계산(18.8 %) | monitor_widget.py:469 |
| 18 | 높음 | Setup우 | 알파 입력에선 Cavity·Detector 값이 무효인데 헤더엔 적용됐다고 기록 | app_window_save.py:206-211 |
| 19 | 높음 | Setup우 | 휠 한 칸에 d 51.8→50.8 cm(포커스 없어도) | Cavity 스핀박스 |
| 20 | 높음 | 도구 | Wavecal Apply가 반만 적용, 잘못된 입력을 무시하고 R²=1 | fitsetup.py:60-77, calib.py:665 |
| 21 | 높음 | 도구 | Test Fit Apply 게이트가 T1뿐(§15-B 위반), Center를 Limit으로 표기 | test_fit_dialog.py:715-730 |
| 22 | 높음 | Setup좌 | Lock 후 편집이 dirty를 안 켬, 레퍼런스 0개로 RUN 허용 | fitsetup.py:428-483, run.py:72-106 |
| 23 | 높음 | 공통 | ✔ 철회된 채널 정체 하드코딩 | app_window_dataload.py:317 |

중간·낮음 등급까지 합치면 섹터당 20~30개다. 각 파일의 "코드 리뷰" 절에 위치와 재현 시나리오가 있다.

## 4. 코디네이터 정정

- **x1e 배율 (섹터 1에서 [높음]으로 보고) → [중간·UX]로 낮춤.**
  - 레퍼런스에 곱한 배율을 계수에 다시 곱해 약분하는 구조이고(`engine.py:141`, `worker.py:1045-1053`), 주석대로 수치 조건화용이다. 그래서 농도가 변하지 않는 것은 설계상 맞다.
  - 실제 문제는 두 가지다. UI가 단위 배율처럼 보여서 오해를 부르고, 결과가 같은데 runid만 달라진다.
  - H2O 4e-13 ppb 문제는 이 스핀으로는 해결되지 않는다. 레퍼런스 단위 쪽에서 따로 봐야 한다.
- **Pipeline Health "ready to fit"**: `overall()`이 SKIP을 세지 않는 것을 직접 확인했다.

## 5. 잘 된 점 (공정하게)

- **성능이 충분하다.**
  - 하루 3채널 4,172스캔을 약 8–9 s에 핏한다. 3일치는 17 s다.
  - 실행 중 화면 멈춤은 최대 0.4 s 미만이다.
  - 74,667행 파일을 1.3 s에 연다.
  - 알파 생성 중 GUI 정지는 42 ms 이하다.
- **데이터 무결성 헌장이 대체로 지켜진다.**
  - QC는 비파괴다(Reapply를 반복해도 원복된다).
  - 같은 runid는 덮지 않고 `_archive`로 옮긴다.
  - Result Lab과 Plot Maker는 값을 지우지 않고 표시만 숨긴다.
  - 트렌드 dat 덮어쓰기 가드가 있다.
- **사고에서 나온 방어선이 실제로 작동한다.**
  - 알파 입력 파일명 가드가 FWHM 혼입을 막는다.
  - 날짜 0개 가드, 중복 스캔 경고가 동작한다.
  - Test Fit은 추천과 적용을 분리했고 Center 변환을 한다.
- **RUN 확인 요약이 훌륭하다.** 이번에 찾은 이상(refs 0, px 0-0, 잠그지 않은 이름)이 전부 이 요약에 드러났다. **여기에 "진행 불가" 가드만 붙이면 치명 결함 여러 개가 한 번에 막힌다.**
- **재현 정확도가 높다.** 운영 NO2 레퍼런스를 7e-10, wavecal을 0.004 nm 이내로 재현했다.
- **Plot Maker의 출판 품질이 좋다.** Type42 폰트, Copernicus 프리셋, (a)(b)(c) 조판, 화면과 출력의 일치. `validate_plotmaker` 44/44 통과.
- **day_audit과 health_checks의 설계**가 깔끔하다. 읽기 전용, 단일 출처, CLI와 공유한다.

## 6. 권장 순서

1. **운영 확인 (오늘)**
   - 9/21 이후에 만든 핫 알파가 있는지 확인한다.
   - 운영 결과 `.dat` 헤더의 Poly/Range를 파일명과 대조한다.
   - 운영 R npz를 백업한다.
2. **한 줄~수십 줄짜리 치명 수정**
   - `_block_average` 반환값을 6개로 맞추고 "He 없음" 테스트를 추가한다.
   - RUN 재진입 가드.
   - wavecal 밖 범위 거부.
   - Pipeline SKIP 판정.
   - Result Lab 클릭(`isAccepted` 제거).
   - Monitor의 `autoRangeEnabled()[0]`.
   - npz 로드 실패 시 예외로 중단.
   - Batch 파일명.
   - CSV 보간 가드.
   - `dataload.py:317` 문구.
3. **패턴 수정**
   - A(성공 조건): 완료 처리 경로 일원화.
   - B(provenance): 헤더·meta를 frozen config에서 생성.
   - D(실행 중 입력 잠금 + 독립 엔진).
4. **패턴 C (시간대 전역 설정)** — 범위가 넓으니 설계 문서를 먼저 쓴다.
5. **UX 정리** — 레이아웃(CH3 탭, 1366 화면), 빈 상태 안내, 툴팁, 그래프 라이브러리 통일.

## 7. 이번에도 못 본 것

- 장시간(며칠) 연속 실행에서의 메모리 증가.
- 한 달치 이상 RUN. 3일과 8일까지만 측정했다.
- 콜드 cold 시각축이 hot보다 11–13 h 뒤로 보이는 현상(섹터 1이 다른 섹터 확인 요망으로 남김). 시각축 규약 확인이 필요하다.

---
## 부록: 점검이 남긴 것
- 증거(하네스, 로그, 스크린샷, 산출물): `%TEMP%\claude\...\scratchpad\deep\s{1..6}_*\`
- 레지스트리: 기존 값은 그대로다. 점검 중 아래 두 키가 새로 생겼다. `r_calib`는 스크래치 경로를 가리키므로 지우는 것을 권한다.
  ```
  reg delete "HKCU\Software\CAESAR\app\r_calib" /f
  reg delete "HKCU\Software\CAESAR\app\plotmaker" /f
  ```
