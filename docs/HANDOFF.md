# CAESAR Pro — 세션 핸드오프 노트

> 다른 컴퓨터/세션의 Claude Code가 이어받기 위한 진행 상황 기록.
> 최종 업데이트: **2026-09-15**. 맨 위가 최신 세션. 그 아래는 시간순이 뒤섞여 있으니
> (08-14 → 09-14 → 08-04 …) 날짜 제목을 보고 찾을 것.

---

## ★ 다음 세션에 넘김 — 로직·물리식·수치 안정성 감사

except 감사(2026-09-15)는 **"예외를 삼키고 그럴듯한 값으로 갈아치우는 것"** 딱 한 가지
고장 모드만 봤다. 그건 끝났다. 남은 건 **삼킴 없이도 틀릴 수 있는 것들**이다.

### 이미 커버된 것 (다시 하지 말 것)
* 침묵 대체 / 조용한 데이터 유실 — 이 문서 아래 섹션. 회귀는 `test_silent_fallback_guard.py`.
* raw 파싱·flag·시각 — 전수검증 2065파일/7,538,129행(`기초파싱_전수검증_2026-09-15.md`).
* 외부 알고리즘 대조 — QDOAS 교차검증(`diagnostics/qdoas_crossval_2026-09/README.md`).
  NO2 r²>0.99, Deming slope 0.96. **VarPro vs LM은 이미 검증됨.**
* Rayleigh King factor 골든값 · VarPro 자코비안 · Pass2 병렬↔순차 바이트동일 — CI.

### 출발점 (감사하면서 실제로 눈에 걸린 것들, 우선순위순)

1. **`load_wavecal`이 4곳에 복제돼 있다** — `core/refit.py`(자기 docstring이 인정),
   `tools/optimize_params.py`, `gui/app_window_save.py:_load_wavecal_array`, 그리고
   r_trend 계열. 단일 출처 원칙(3) 위반이고 **파장축은 모든 숫자의 x축**이다.
   넷이 미세하게 다르면 경로마다 다른 파장으로 핏한다. 먼저 셋이 같은 답을 내는지
   대조부터 할 것(같으면 통합, 다르면 그게 버그다).
2. **`flag=0`이 두 가지 뜻** — ① LabVIEW 헤더행 ② flag 컬럼 없는 파일의 기본값.
   경로마다 정책이 다르다: `AlphaExportWorker._process_scan`은 건너뛰고,
   `AnalysisWorker._run`은 **ambient로 피팅**한다(T=25/P=1013.25 기본값).
   같은 raw가 경로에 따라 다른 결과를 낸다. 보고서 §4-E에 상세.
3. **스펙트럼 포화(65535) 감지가 없다** — 포화된 픽셀은 흡수를 **과소평가**한다.
   지금은 아무 경고 없이 핏에 들어간다. 보고서 §(C).
4. **수치 바닥값이 흩어져 있다** — `1e-30`, `1e-300`, `max(..., 10.0)`,
   `max(abs(ppb_raw), 1e-30)` 등. 각각은 합리적이지만 **한 번도 같이 검토된 적이 없다.**
   특히 `window_designer`/`fit_optimizer`의 바닥값은 순위 결정에 직접 들어간다.
5. **공분산의 lambda** — `execute_varpro_fit`이 공분산을 계산할 때 override가 아니라
   base `tikhonov_lambda`를 쓴다("원본 동작 보존" 주석). 정규화를 바꿔 핏해놓고 오차는
   다른 정규화로 계산하는 셈이라, 의도된 건지 확인 필요.
6. **`estimate_shift`가 전 스캔 실패 시 shift 0** — 중립값이라 이번엔 뒀지만,
   "정렬 실패"와 "정렬이 0"이 구분되지 않는다.
7. **`_is_alpha_input` 오판** — 포맷 탐지가 실패하면 알파를 raw로 취급한다.
   탐지 자체(`data_io._is_alpha_trace_format`)도 예외를 삼키므로 이중 방어가 없다.
8. **T/P 명목값** — QDOAS 대조가 스캔별 T/P가 없어 명목값(25°C/1013.25)을 썼다.
   `core/error_budget.py`의 `UNQUANTIFIED` 항이 바로 이런 것들이다 — **그 표를 채우는
   작업이 곧 이 감사의 성과물**이 된다. 거기서 시작하면 범위가 저절로 잡힌다.

### 권하는 방법
`error_budget.build()`가 내놓는 `UNQUANTIFIED` 목록을 작업 목록으로 삼아라. 항을 하나씩
정량화하면서 그 항을 만드는 코드를 읽으면, "감사"가 아니라 **논문 Table을 채우는 일**이
된다 — 같은 노동으로 두 가지가 나온다.

---

## 2026-09-15 — 광범위 except 감사 (숫자를 만드는 경로 132건) · 침묵 대체 18곳 제거

**다시 훑지 말 것.** core/의 `except Exception`/bare 78건을 AST로 전수 분류했다
(`gui` 243건 · `oculus` 6건은 손 안 댐 — oculus는 원래 깨끗하다).
판정 기준 하나: **예외를 삼킨 결과가 "숫자" 또는 "데이터 있음/없음"으로 하류에
나가는가.** 로그·캐시·포맷 탐지처럼 나가지 않는 것은 그대로 뒀다.

고친 것 (`397bf2a` `282e468` `4d1e3b7`)

| 어디 | 삼키고 뭘 넣었나 | 왜 위험했나 |
|---|---|---|
| `doas_fit.setup_fit_parameters` ×5 | Center→0±3px, Limit→±3px, Fix→0, sq Limit→±0.01, sq Fix→1.0 | 결과 헤더엔 **선언한** 세팅이 기록 → 기록과 실제가 어긋난 채 런 종료 |
| `fit_optimizer.fit_window` | 같은 ±3.0 (여섯 번째 사본) | 그 창으로 `shift_at_bound` 판정 → 세팅 기각/채택이 뒤집힘 |
| `doas_fit.execute_varpro_fit` | 공분산 실패 시 `perr=0` | `<gas>_Error=0`, `MDL=0`, `perr_rel=0`(=최적) — 과적합에 상 주는 형태 |
| `data_io.read_scans_via_dataio` | 전 행 실패를 `([], [])` | R 트렌드 로그에 "ZA scans=0"으로 찍혀 **계기 문제로 오해** |
| `data_io.scans_worker_for_parallel` | 실패를 `([], [])` | 위와 같은 혼동. 이제 `(None, None)` |
| `data_io.extract_raw_file_for_parallel` | 파일 펼치기 실패를 `n=0` | 호출부의 "SKIP(parse)" 경로가 죽어 있었다 |
| `fit_physics.fitted_amount_health` | 핏 실패 스캔 `continue` | T2 판정이 조용히 줄어든 표본 위에 섬. `n_requested`/`n_failed` 추가 |

덤: `raw_parser.autoload_campaign_layouts`의 "프로파일 건너뜀"이 verbose일 때만
보이던 것을 항상 stderr로. 레이아웃 등록 실패 = HK 열 지도 없이 파싱 = T/P 기본값 대체.

회귀 잠금: `tools/test_silent_fallback_guard.py` **56 PASS**. pytest가 자동 수집한다.

**안 고친 것과 이유** (다음 세션이 다시 열어보지 않도록)

* `session_log` ×5 — 로그 tee. 로깅이 앱을 죽이면 안 된다. 의도된 best-effort.
* `alpha_cache` ×2 — 캐시 실패 시 다음 런이 재파싱(docstring에 명시).
* `data_io` 포맷 탐지 ×8(`is_araon_mega_matrix`·`_is_alpha_trace_format`·
  `_alpha_layout`·`count_scan_rows`·스캔수 캐시) — 탐지 실패는 "이 포맷 아님"이
  맞는 의미. 뒤이은 행 로드가 실패하면 `RAW_LOAD_FAIL`로 flag된다.
* `fit_explorer`·`health_checks`·`engine.add_reference`·`fitset_builder.validate_fitset`
  — 이미 **모범 패턴**이다. 실패를 값/상태로 반환한다
  (`{"state": "UNAVAILABLE", "reason": ..., "exception_class": ...}`, `problems.append`,
  `(False, "Error loading ...")`). 새로 쓰는 코드는 이걸 따라 할 것.
* `provenance._git` → None (git 없는 환경), `run_meta.layout_from_input` →
  `{"ncols": n}` (프로바넌스 degrade지만 임포트가 실패할 일이 실무상 없음).

**2순위 2건도 정리함** (계기 담당자 확인 후)

1. `data_io.parse_row_timestamp` — **mtime 폴백 제거**. 원래 의도는 "초기에
   bytepack 디코드가 가끔 이상해서, raw를 재저장만 안 하면 mtime = 측정 완료
   시각"이라는 차선책이었다(담당자 확인). 그 전제는 파일을 복사·이동하는 순간
   깨지고, 깨져도 **그럴듯한 시각**이 나와서 아무도 모른다. 그리고 전제였던
   "디코드가 가끔 이상하다"가 이제 성립하지 않는다 — 전수검증에서 파일명 날짜 vs
   bytepack **2065/2065 일치**, 행간격 97 cs 전 파일 동일. 원인이던 레이아웃
   오판도 같은 날 고쳐졌다. 이제 못 읽으면 None + stderr 경고(파일당 1회),
   Time 칸은 `row NNNN`.
2. `window_designer.residual_rho` — 전 스캔 lstsq 실패 시 `0.0` → **RuntimeError**.
   하필 0.0이 이 함수 docstring이 경고하는 바로 그 값이었다("ρ≈0이면 유효자유도
   보정이 무력화되고 '넓을수록 좋다' 편향이 되살아난다"). 하류
   `n_eff = n_pix(1-ρ)/(1+ρ)`가 n_pix로 부풀어 F검정 자유도가 커지고, 후보 종이
   우연한 개선만으로 채택된다. 옆의 `model_adequacy()`는 같은 상황에서
   `inf`(=모델 불충분)로 **보수적으로** 실패한다 — 그쪽에 맞췄다.
   일부만 실패하면 몇/몇인지 stderr로 알리고 남은 표본으로 추정한다.
   (`estimate_shift`의 `continue`는 그대로 뒀다 — 실패 시 shift 0은 중립값이고
   설계 입력일 뿐이다.)

### `gui/worker.py` 30건 (추가 감사)

`gui/`에서 **숫자를 만드는 유일한 파일**이라 core와 같은 등급으로 따로 봤다. 6곳 수정.

| 어디 | 삼키고 뭘 넣었나 | 왜 위험했나 |
|---|---|---|
| `_reread_amb_plain` / `_reread_amb` | Pass2 스풀 재읽기 실패를 `[]` | 호출부가 `(fp, None, 0, **err=None**)` = "정상 처리, 0행"으로 보고 → 알파가 통째로 비어 나가는데 **에러가 없다**. 이제 예외(기존 에러 경로가 받는다) |
| R(t) `reflectance_calc` 임포트 실패 | `_RC = None` 후 조용히 진행 | 시간가변 R(t) → **단일 R 강등**. 물리적으로 다른 처리인데 결과만 보면 구분 불가. status_msg로 알린다 |
| R(t) knot 페어 실패 | `continue` | R은 알파 전체의 분모다. 몇 개 knot 위에 세워진 곡선인지 모른 채 진행. 이제 몇/몇인지 알린다 |

**확인했지만 문제 아니었던 것** (다시 열지 말 것)

* `result['RMS'] = 0` (Skip 행) — 숫자 주장처럼 보이지만 `result_io.robust_rms_thresholds`가
  `isfinite & (a > 0)`로 **0을 명시적으로 제외**한다. QC 단일 출처가 지키는 의도된 센티넬.
  같은 행에 `Status="Skip: ..."`도 남는다.
* `_prescan_injection_indices`의 `amb_i.append(idx); continue` — 못 읽은 행을 ambient로
  분류하지만 본체가 어차피 같은 행을 SKIP 처리한다(주석에 근거 있음).
* 핏 재시도 루프 — 마지막 시도에서 `raise e`. 삼키지 않는다.
* `threadpoolctl` 임포트 실패 ×3 — 선택 의존성, `os.environ.setdefault` 폴백.

**나머지 2건도 고침** — `AnalysisWorker`에 `status_msg` 시그널 추가

`_run`(병렬 핏 전체 실패)과 `_run_parallel`(청크 실패)이 `print`로만 남기고
`finished.emit()`을 인자 없이 쏴서, 화면엔 **결과 0건으로 정상 종료**처럼 보였다
(traceback은 `logs/session_*.log`에만). `AnalysisWorker`에 `status_msg = pyqtSignal(str)`
를 추가하고 `app_window_run.py`가 상태바에 연결한다 — `AlphaExportWorker`가 이미 쓰던
규약을 그대로 가져왔다(`app_window_inputs.py:371` 참고). 처음엔 "GUI 배선 판단이
필요하다"고 미뤘는데, 배선 방법이 저장소에 이미 있어서 판단할 게 없었다.

### 2차 — `r_workers.py` 14 + `app_window_save.py` 16 (숫자/출력 파일을 만지는 나머지)

| 어디 | 삼키고 뭘 했나 | 왜 위험했나 |
|---|---|---|
| `_ChannelRWorker` (r_workers) | 기존 R 트렌드 `load_dat` 실패 → `prior=[]` | 바로 아래 `save_dat(plot_results, trend_path)`가 **새 결과만으로 덮어쓴다**. 과거 R 시계열이 복원 불가하게 소실 — 헌장 1번 정면 위반. 이제 읽기 실패 = 덮어쓰기 금지(예외 → 그 채널만 건너뛰고 로그) |
| `save()` (app_window_save) | 핏범위 파싱 실패 → `0, 0` | 결과 헤더 `# Fit Range: Pixel 0-0` = **거짓 기록**. 헤더는 재현 기록이다(원칙 4). 이제 `UNREADABLE`로 적는다 |
| `_build_engine_from_config` | 레퍼런스 누락·ILS 실패·wavecal 폴백을 조용히 | 더블클릭 리플레이 엔진이 **원본 핏과 다른 엔진**이 된다 → 같은 스캔에 다른 숫자 → "핏이 불안정하다"고 오해. 이제 달라진 항목을 모아 상태바에 띄운다 |

**확인했지만 문제 아니었던 것**
* `r_workers`의 나머지 11건 — 대부분 이미 `finished.emit("ERROR: ...")`·`log.emit`·
  `failed.emit`로 보고한다(모범 패턴).
* `done_set = set()`(npz 로드 실패) — 스킵 최적화가 꺼져 **전부 재계산**된다.
  실패 방향이 보수적이라 그대로 뒀다(시간만 손해).
* `ui_result_viewer.py`의 export 경로 — `_export_png`는 `QMessageBox.warning`,
  `_draw_residual`은 `{"ok": False, "reason": ...}`. 둘 다 이미 보고한다. 손댈 것 없음.

**덤 — 죽은 코드**: `gui/r_workers.py`의 `_HeCheckWorker`(33줄)는 저장소 어디서도
호출하지 않는다. `32d4b0b` 분리 리팩터 때 이미 호출부가 없었다. 지우려면 지워도 된다
(감사 범위 밖이라 손 안 댐).

### 감사 종료 — 안 본 것과 그 이유

`gui/`의 나머지 183건(`ui_plot_maker/widget.py` 29, `ui_dialogs_calib.py` 19,
`app_window*.py` 38, 뷰어 표시 경로 등), `tools/` 58, `calibration/` 10,
`diagnostics/` 9, `oculus/` 6 = **약 266건은 보지 않았다.**

멈춘 기준: **숫자를 만들거나 파일로 내보내는 경로는 전부 봤다.** 나머지는 표시·입력·
그림이라 틀리면 **화면에서 눈에 보인다** — 조용히 틀리는 부류가 아니다. 여기서 더
가면 비용 대비 수확이 급격히 떨어진다. 다시 열 거라면 새로 생긴 코드부터.

---

## 2026-09-15 — `gui/app_window.py` 분해: 6418 → 1431줄

**메서드가 이사했다. `gui/app_window.py`만 grep하면 이제 못 찾는다.**
클래스에 있던 §1~§14 목차 주석을 이음매로 써서 §3~§14를 믹스인 9개로 뺐다.
`CAESARAnalyzer`는 그대로고 호출부도 그대로다(전부 `self.xxx()`). 목차 주석에
이사 간 파일이 적혀 있으니 거기서 찾을 것.

| 파일 | § | 내용 |
|---|---|---|
| `app_window.py` | §1 §2 | `init_ui` + Setup 탭 (남은 것) |
| `app_window_cavity.py` | §3 | Cavity 탭 + FWHM/ILS 검증 |
| `app_window_inputs.py` | §4~§6 | 입력 → 알파 생성 → I0/R 진단 |
| `app_window_fitsetup.py` | §7~§9 | 다이얼로그 런처 · Test Fit · 핏범위/레퍼런스 |
| `app_window_dataload.py` | §10 | 데이터 로드 + 채널 분배 |
| `app_window_run.py` | §11 | 분석 실행 / 워커 / autosave / closeEvent |
| `app_window_results.py` | §12 | 결과 테이블 / QC / fast 렌더 |
| `app_window_save.py` | §13 | 결과 저장 + 결과뷰어 연동 |
| `app_window_channels.py` | §14 | 채널 탭 + 시나리오 config |
| `app_window_policy.py` | — | `_scenario_gas_policy` 등. §11·§14가 같이 써서 순환 임포트를 막으려 뺌 |

**순수 이동이다** — 옮긴 4987줄이 분해 전(`0025020`)의 연속 부분문자열임을 확인했다.
동작이 바뀐 곳은 없다. 로직 개선은 손대지 않았다.

### 이어서 작업할 사람이 알아야 할 것

- **앵커: `tools/test_app_window_smoke.py`** (CI 등록됨). 메인창을 offscreen으로
  띄우고 ①분해 직전 표면(클래스 속성 160 + 위젯 152 + 탭 이름) ②믹스인 이름 충돌
  ③`symtable`로 미해결 전역(임포트 유실)을 본다. 믹스인을 더 만들거나 메서드를
  옮길 거면 이게 가드다. 의도적으로 메서드를 지웠다면 골든 목록에서도 지워야 한다.
- ③번은 실제로 버그를 잡아서 생겼다. `campaign_dir as _campaign_dir`의 **별칭이
  이동 중에 흘렀는데** 모듈은 멀쩡히 임포트되고 창도 뜨고 import smoke도 통과했다 —
  autosave가 도는 순간에만 NameError였다. 표면 골든으로는 원리상 안 잡힌다.
- `gui.app_window`가 `_scenario_gas_policy`/`_channel_worker_gas_policy`를 참조 0인
  채로 임포트하고 있다. **재수출이다** — `tools/test_test_fit_dialog.py`가 거기서
  가져간다. 미사용 임포트로 보고 지우지 말 것(`noqa`와 주석 붙여둠).
- **§1 `init_ui`(777줄)는 일부러 안 뺐다.** 전 탭의 위젯을 만들고 믹스인 아홉 개
  전부에 `connect`하는 허브라, 떼면 파일만 하나 늘고 읽기는 더 어려워진다. 쪼갠다면
  "탭별 build 메서드를 각 믹스인으로 넘기는" 구조 변경이고 그건 순수 이동이 아니다.
- 덤으로, 저장소에 있으면서 CI에 등록된 적 없던 `tools/test_ref_properties_table.py`
  (shift 정책 왕복)와 `tools/test_test_fit_dialog.py`(Limit→Center 산식이
  `core/fitset_builder.py`와 같은지)를 ci.yml에 넣었다. 있는데 안 도는 테스트는
  없는 것과 같다.

---

## 2026-09-15 — 해석적 자코비안(Golub–Pereyra). "차원축소 덕"이 드디어 실증됨

비선형 탐색이 scipy 기본 **2점 유한차분** 자코비안을 쓰고 있었다. 실측(실제 프리셋 d=2,
실캠페인 알파): 목적함수 호출의 **67%가 유한차분용**이고 목적함수가 총 시간의 66~72%
→ **유한차분이 총 시간의 약 47%**.

### 바뀐 것

- `core/engine.py`: 레퍼런스 보간기와 **도함수**를 `_set_interpolator()` 한 곳에서 같이
  만든다(네 군데 흩어져 있던 `interp1d(...)` 중복도 여기로 합침). `make_interp_spline(k=3)`이
  `interp1d(kind='cubic', fill_value="extrapolate")`와 **외삽 포함 비트동일**임을 확인하고
  그 `.derivative()`를 보관 — scipy 비공개 속성(`_spline`)에 의존하지 않기 위함.
- `core/doas_fit.py`: ±Neg ON(무제약)이면 선형 단계를 QR로 풀고 그 Q/R을 자코비안에
  재활용. 자코비안은 **Golub–Pereyra 완전식**:

      J_k = −[ P⊥ D_k c  +  A⁺ᵀ D_kᵀ r ],   P⊥ = I − QQᵀ,  A⁺ᵀ = Q R⁻ᵀ

  ⚠ **Kaufman 근사(2항 생략)를 먼저 시도했다가 버렸다** — 유한차분과 40~67% 어긋나
  검증을 게이트로 쓸 수 없었다. 2항은 k-벡터 삼각해 하나 + Q 곱 하나라 사실상 공짜다.
  같은 함정에 다시 빠지지 말 것.
- 창 밖 기체 열은 항상 0이라 A가 랭크부족 → QR이 깨진다. `keep_mask`로 그 열을 빼고
  풀고 계수는 0으로 되돌린다(현 `lsq_linear` 최소노름 해와 같은 값).
- 폴백 둘: ±Neg OFF(하한 0)면 경계에서 투영이 미분 불가능 → 기존 유한차분 경로.
  A가 정확히 랭크부족이면 `LinAlgError`를 잡아 그 핏만 유한차분으로 재시도.
- **최종 선형해는 여전히 `lsq_linear`**(IRLS 반복당 1회). 보고되는 계수·perr의 산출
  경로를 안 건드려서 변화 폭을 탐색 경로로만 한정했다.

### 검증 — `diagnostics/varpro_speed_2026-09/validate_analytic_jacobian.py` (신규)

비트동일 게이트를 쓸 수 없다(자코비안이 바뀌면 같은 답에 다른 경로로 도착). 2단계:

1. **자코비안 자체**: 핏 도중 불린 자코비안 전수를 `approx_derivative`(2점)와 대조 —
   480회, 최대 상대차 **8.6e-07**(유한차분 자체 정확도 한계 ~1e-7 수준).
2. **결과**: **cold-start를 판정 기준**으로(스캔간 캐리오버가 없어 차이가 누적되지 않음),
   warm-start는 보고만. 8개 조건 × 500스캔에서 shift max|diff| ≤ 1e-5 px(최저 6e-14),
   농도 상대차 ≤ 1e-6, **corr = 1.00000000**. warm-start도 같은 수준으로 나왔다.

속도(직전 커밋 대비) 1.51~1.71배, 중앙값 1.57배.

### 결론이 또 뒤집혔다 — 이번엔 이론 쪽

| `run_*.py` 재실행 | VarPro warm | 완전비선형 warm | VarPro cold | 완전비선형 cold |
|---|---|---|---|---|
| Cold d=2 (실제 프리셋) | **2.54** ms/scan | 10.37 (4.1배) | **2.83** | 15.21 (5.4배) |
| Hot ROI1 d=8 (Link 해제) | **6.78** | 36.33 (5.4배) | **7.45** | 57.27 (7.7배) |

d=8이 원래 "VarPro가 1.9배 지던" 케이스였다(이 세션 시작 시점 44.7 ms/scan → 지금 6.78).
**차원이 커질수록 VarPro가 더 유리해진다** — Golub–Pereyra가 예측하는 바로 그 거동이
해석적 자코비안을 넣고 나서야 나타났다. 이제 `docs/논문_주장구조_2026-09.md`의
"~~VarPro라서 빠르다~~ 쓰지 말 것" 항목은 **해제**다(단서는 그 문서에).

### 세션 누적 (Cold d=2 warm 기준)

9.4 → 4.28(밀집 W 제거) → ~4.1(상수열 호이스팅) → **2.54 ms/scan = 3.7배**.

### 다음에 남은 것

- 해석적 자코비안은 **±Neg ON일 때만** 탄다. 사용자는 항상 ON으로 쓰지만, OFF 경로는
  옛 속도 그대로다(의도된 설계 — 그쪽은 수학적으로 해석해가 성립하지 않음).
- `core/refit.py`·`fit_optimizer`·`param_optimizer`도 같은 엔진을 쓰므로 자동으로 빨라진다.
- B-스플라인 basis 공유(조립 1.50배)는 여전히 미채택 — 3차 세션 노트 참조. 이제
  자코비안의 도함수 평가에도 같은 논리가 적용되므로 재검토 가치가 조금 올랐다.

---

## 2026-09-14 (3차) — 설계행렬 상수열 호이스팅 + "Link 중복 보간" 전제 폐기

**닫은 가설**: "`Link`된 종들이 같은 보간을 3번 한다"는 **틀렸다**. 종마다 레퍼런스
스펙트럼이 달라 `interpolators[NO2]`와 `interpolators[H2O]`는 애초에 다른 계산이다.
Link가 공유하는 건 (shift, squeeze) 값뿐 — 캐시할 중복 결과가 없다.

**실제로 있던 낭비 두 가지 (수정함, `core/doas_fit.py`)**:
- theta에 안 걸리는 열(poly Chebyshev·custom_basis·etalon sin/cos)을 목적함수
  **호출마다** 다시 만들고 있었다 → 루프 밖에서 `CONST` 한 번만 조립.
- 창 밖 기체(`gas_active=False`)를 보간한 **뒤에** 0으로 덮었다 → 보간 자체를 건너뜀.
  (창 밖 기체가 있는 세팅에서 스플라인 평가 1회/호출 절약)

목적함수 본문이 20줄 → 1줄(`np.hstack((_gas_columns(val_dict), CONST)) * w[:,None]`)로
줄었고 열 순서(gas→poly→custom→sin→cos)는 그대로라 하류 인덱싱·반환값 불변.

**검증**: `validate_dense_w_removal.py --before-ref HEAD`(직전 커밋 대비) — 같은 8개
조건 × 700스캔에서 **max|diff| = 0.000e+00**, 속도 1.01~1.08배(중앙값 1.04배).
회귀 스위트 동일하게 통과.

**측정했으나 채택 안 한 것 — B-스플라인 basis 공유**: 종간 knot 벡터가 동일하므로
(`interp1d(np.arange(n), ...)`, k=3, len(t)=2052 전 종 동일) `BSpline.design_matrix`를
(shift,squeeze)당 1회 만들고 종별로는 계수 matvec만 하면 설계행렬 조립이
0.102 → 0.080 ms(1.50배)로 줄고, **결과도 비트동일**임을 확인했다. 그럼에도 안 넣은 이유:
(a) `interp1d._spline`이라는 **scipy 비공개 속성**에 의존하고, (b) 계수행렬을 매 호출
쌓으면 이득이 사라져 **엔진 쪽에 캐시 상태**를 둬야 하는데 이는 "DoasFitter는 무상태"
설계원칙과 충돌하며, (c) Link 없는(각 종이 독립 shift) 경우엔 basis 공유가 성립하지
않아 이득이 0이다. 전체 핏 기준 기대 이득은 ~1.1배 — 그 대가로는 비싸다.
**다시 집을 거면 `core/engine.py`에서 레퍼런스 등록 시 공유 basis를 캐시하는 형태로.**

---

## 2026-09-15 — 기초 파싱·flag·시각 전수 검증 (실데이터 2065파일 / 753만행)

전체 보고서: **[`docs/기초파싱_전수검증_2026-09-15.md`](기초파싱_전수검증_2026-09-15.md)**
(근거표·재현 스크립트·미해결 항목이 전부 거기 있다. 아래는 요약 + 다음 사람이 집을 것)

### 확인된 것 — 전수에서 성립
- **flag 표**: 문서에 없는 값 **0건**, 파싱 실패 **0건**(7,538,129행). 100·511만 미출현.
- **시각**: 파일명 날짜 vs bytepack 디코드 **2065/2065 일치**. 행간격 중앙값
  **97 centisec(0.97 s)가 전 파일 동일**, 파일 간 경계도 97 cs.
- **`bytepack=(col0<<16)|col1` 바이트 순서**: `2026-05-17-001.dat` row275→276에서
  `c1`이 0을 넘어 뒤로 감길 때 `c0`이 정확히 1 감소 = **32비트 빌림**. 실데이터 증거.
  `time_lo`/`COL_TIME_LO` 이름이 반대인 건 역사적 오명 — **순서 뒤집지 말 것.**
- **핫 HK 절대열**: 오븐 300.00/180.01 °C, P 962.5/919.1 mbar → 한 칸만 틀려도 안 나오는 값.

### 고친 것
1. **`raw_parser._detect_layout`** — 등록 레이아웃과 맞는 행이 없을 때 **첫 행** 열수를
   쓰다가, 헤더가 데이터보다 **넓으면**(콜드 6177>6174) `iter_rows`의
   `len(toks) < ncols` 가드가 **데이터행을 전부 버렸다**. 실측 `2026-06-11-020.dat`
   3694행 → **1행**. 이제 최빈 열수를 쓴다. 회귀 `[2-C]`.
   → 09-14의 `LAYOUT_PROBE_ROWS` 수정이 **좁은 방향만** 막고 있었다는 뜻.
2. **콜드 6174 레이아웃 등록** + Oculus 프로파일 JSON. `raw_parser`와 `data_io`가
   같은 raw에 다른 답을 내던 상태 해소(원칙 3). 회귀 `[2-D]`·`[4-B]`.
3. **QC 문턱식 사본 제거**(`plot_caesar_weekly.py` → `core.result_io` 호출).
   교체 전 무작위 21,000건 대조로 **동치 증명** — 리포트 숫자 안 바뀜.
4. **Oculus 중복 수집 경고** — `**` 재귀 glob이 사본 폴더를 두 번 먹던 것(지우지 않고 경고).

### ★ 다음 사람이 집을 것

**(A) 계기 담당자 확인 대기 — 핫 분광기 온도 열이 6177이 아닐 수 있다**
핫 **전 파일(1314개 × 5행 = 6570행)** 조사 결과:

| col | 지도상 이름 | 실값 있는 파일 | median |
|---|---|---|---|
| 6152 | templed4 | **0 / 1314** | 전수 sentinel |
| 6176 | tempcell3 | **0 / 1314** | 전수 sentinel |
| **6177** | **tempsptrm** | **0 / 1314** | **전수 sentinel** |
| **6180** | (미지도) | **1239 / 1314** | **29.74 °C** |

즉 지도가 가리키는 `tempsptrm`(6177)은 **한 번도 값이 없고**, 바로 옆 미지도 6180에
콜드 `tempsptrm`(6174, 26.98 °C)과 같은 계열로 보이는 실신호가 있다.
**→ 핫 분광기 온도는 6180일 가능성이 높다.**

- **지금 바꾸지 않았다**: 어느 센서가 어느 열인지는 **하드웨어 사실**이고, 추측으로
  재배치하면 이 모듈이 가장 경계하는 "조용히 틀린 HK"가 된다.
- **당장 피해는 없다**: `tempsptrm`를 읽는 소비자가 없다(`data_io._HK_REL` 최대 rel=26).
- **확인되면 할 일**: `core/raw_parser.py`의 `HotHKMap["tempsptrm"]`을 6180으로 옮기고,
  `oculus/profiles/caesar_hot.example.json`의 `t_spectrometer`(rel 28 → 31)도 같이.
  같이 걸린 **이름 충돌**도 정리할 것 —
  `campaigns/yeosu_2026/hot_cavity_t/scripts/02_backcast_all.py`는 핫 col 6174를
  `T_spt`라 부르는데 `raw_parser`는 같은 열을 `tempcell1`이라 한다.
- 근거 주석은 `core/raw_parser.py`의 `HotHKMap` 바로 위에 박아뒀다.

**(B) 보류 — `flag=0`이 두 가지 뜻으로 겹쳐 있다 (운용자 판단으로 미적용)**
`flag=0` = ① LabVIEW 헤더행, ② flag 컬럼 없는 파일(`data_io.py`의 기본값).
그래서 경로마다 정책이 다르다 — `AlphaExportWorker._process_scan`은 **건너뛰고**,
`AnalysisWorker._run`(worker.py:444)은 **ambient로 피팅**한다(T=25/P=1013.25 기본값).
제안했던 1줄 수정(비-Araon 1D 분기가 `state_flag=1` 반환)은 **출력이 바뀌어** 보류.
자세한 건 보고서 §4-E.

**(C) 미조치 — Augur 본 파이프라인에 스펙트럼 포화(65535) 감지가 없다**
Oculus는 `profile.is_saturated`로 잡는데(adc_max 64000) Augur는 그대로 α·피팅에 넣는다.
무결성 헌장대로라면 **flag만 세우는 것**이 맞다. 보고서 §4-G.

### 알아둘 캠페인 사실
- **이 계기는 "값 없음"을 0 으로 쓴다**(계기 담당자 확인 2026-09-15). 65535 도 섞여 쓴다.
  `SENTINEL_RAW = (0.0, 65535.0)` 은 맞으니 바꾸지 말 것. 대가는 **정확히 0.00 °C 가
  결측과 구분 안 된다**는 것 — 여수(셀 29~33 °C)엔 무해하지만 빙점 근처 운용이면
  반복될 수 있다. 고칠 땐 0 을 빼지 말고 **필드별 sentinel 을 프로파일에** (보고서 §4-K).
- **raw 포맷은 3채널 전제다**(계기 담당자 확인). meta 5열 + **3×2048 슬롯** + HK.
  그래서 스펙트럼 구간은 **언제나 6149열 고정**이고 `ncols − 6149 = HK 열 수`다
  (핫 32 → 6181, 콜드 30 → 6179, 콜드 선두결손 25 → 6174).
  "콜드와 핫은 포맷이 다르다"가 아니라 **"포맷은 같고 HK 개수만 다르다"**가 맞다.
  MATLAB 채널 번호는 슬롯 순서와 다르다 — `ch3`가 파일 맨 앞(5-2052), `ch1`=2053-4100,
  `ch2`=4101-6148 (validate_pipeline `c_raw` 바이트일치로 확정).
  ⚠ **세 번째 슬롯(5-2052)은 두 모듈 다 접근 못 한다**. `channel=3`을 요청하면
  조용히 `channel=2`로 clamp돼 **다른 채널 데이터가 경고 없이 돌아온다**.
  다음 캠페인에서 셋째 캐비티를 켜면 ncols가 안 바뀌어 조용히 사라진다 — 보고서 §4-J.
- **타임아웃 구간은 데이터가 깨지는 게 아니라 결측이다.** 필드로그 3건
  (6/12 Cold · 6/16 Cold · 6/30~7/1 Hot) 전부 확인: 파싱 실패 0, 시각 역행 0,
  잘린 줄 0. 파일이 중간에 깨끗이 끊기고 재개된다.
  · 6/16은 재개 시각이 **07:13:54**로 로그의 "07:14 UTC"와 초 단위 일치(계기시각=UTC).
  · 6/30~7/1 로그의 "22시간"은 **발견 시각** 기준이고 실제 공백은 **9.72시간**이다.
  ⚠ 단, **재시작이 곧 flag=0 헤더행을 만든다** — 6174 구간(6/11~6/15)과 겹치면
  헤더 6177 > 데이터 6174가 되어 오늘 고친 그 버그가 된다. 넓은-헤더 4개
  (`06-11-020`·`06-13-001`·`06-14-010`·`06-15-003`)가 **전부 재시작 직후**였다.
- **콜드 2026-06-11-020 ~ 06-15-026 (97파일, 5일)은 6174열**(HK 선두 5열 결손).
  무보정 절대열로 읽으면 `cavity_T`가 **33.93 °C**(진값 29.16 °C)로 **그럴듯하게 틀린다.**
  `data_io`(hk_shift)와 `raw_parser`(이제 등록됨) 둘 다 정상 복구한다.
- **5/29 시계 도약(−8.50 h)은 핫 전용.** 콜드는 747개 경계에서 역행 **0건** →
  `field_log_summary_2026.md:65`의 "핫인지 콜드인지 확인 필요" 미해결 질문 해소.
- **인젝션 `2026-08-10-005.dat`(최상위)는 He 35행이 `004.dat`에서 스플라이스**돼 있어
  **파일 내 시각이 단조증가가 아니다**(1h29m 역행 후 복귀). 시간축 믿는 코드로 다루지 말 것.
  `(raw)` 접미사가 원본, `데이터 생성용/`은 재라벨만 된 판본.
- `E:/Yeosu_2026/CAESAR_Cold/2026-06/KRISS_10ppm - 복사본/`은 사본 폴더다(3개 중복).

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

⚠ **정정(2026-09-15)**: 위 문단은 원래 "`diagnostics/` 전체가 `.gitignore`에 있어
검증 스크립트가 커밋되지 않는다"였는데 **틀렸다**. `.gitignore`는 `diagnostics/`
하위 폴더를 **하나씩 나열**하는 방식이고 `alpha_pass2_parallel/`·
`cold_validation_2026_05/`·`parallel_shift_bench/` 등은 추적된다. 규칙 위 주석이
의도를 밝혀둔 대로 "재현 가능한 도구는 넣고, 원자료·그림·실행결과 캐시는 뺀다"이다.
`varpro_speed_2026-09/`가 통째로 빠져 있던 건 `results_*.json`(실행 캐시) 때문으로
보이는데, 2026-09-15에 **폴더 무시를 `results_*.json` 무시로 바꿔** 스크립트와
README를 커밋에 포함시켰다. (이미 푸시된 커밋 `33f6f3e`·`aece86f` 메시지에도 같은
오기가 들어갔다 — 메시지는 고칠 수 없으니 이 문단이 정정본이다.)

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

1. ~~**`objective_varpro`의 중복 보간 제거**~~ — ❌ **전제가 틀렸다. 닫는다.**
   "Link된 종들이 같은 계산을 3번 한다"가 아니다 — 종마다 **레퍼런스 스펙트럼이 달라
   스플라인도 다르다**(확인: 세 raw_reference 배열이 서로 다름). Link가 공유하는 건
   (shift, squeeze) **값**뿐이라 캐시할 중복 결과가 없다. 실측도 그렇다: 1종 0.028 ms
   × 3 ≈ 3종 실측 0.077 ms. 대신 실제로 있던 낭비(상수열 재조립)는 잡았다 —
   아래 "2026-09-14 (3차)".

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
