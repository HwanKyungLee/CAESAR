# Augur 개선 — 진행 상태

원본 목록: `AUGUR_개선_개발목록.md` (2026-09-11, 시안 5종 + 코드 리딩 기반)
이 파일이 **정본 체크리스트**다. 한 단계 끝날 때마다 여기를 갱신한다.

## 범위 결정 (2026-09-11)

원본 24항목 중 **11개만 한다.** 기준: *이걸 안 하면 뭐가 망가지나.*
과학이 틀리면 필수 · 시간이 낭비되면 가치 있음 · 눈이 불편하면 제외.

**제외/축소한 것과 이유** — 나중에 다시 꺼낼 때 근거가 필요해서 남긴다:

| 항목 | 처분 | 이유 |
|---|---|---|
| A5 Save 확인창 | **축소** → auto-save 로그 한 줄만 | 목적이던 덮어쓰기 사고를 **A3가 구조적으로 제거**(다른 설정 = 다른 runid = 못 덮음). 비교는 저장 후 B3가 자연스럽고, 주 패턴인 auto-save는 다이얼로그를 못 띄운다 |
| D4 캘리브 세트 | **보류** | 추적 문제의 절반은 **A1이 이미 해결**(wavecal·R·dark·offset·ILS가 meta에 있음). 남은 건 정리뿐 |
| B5 Plot Maker | **반만** → 미리보기 정합 | 진짜 아픈 건 pyqtgraph 미리보기 ≠ matplotlib 출력. 5탭 좌우 재배치(L)는 효용 대비 비쌈 |
| B4 산출물 뷰어 | **보류** | 이미 있는 뷰어를 모으는 일. 없어서 못 하는 게 아님 |
| D5 잔차 진단 GUI | **B2에 흡수** | B2의 잔차 패널이 생기면 탭 하나로 훨씬 싸게 붙는다 |
| F1 전역 QSS | **보류** | F2만으로 논문 스크린샷 목적 달성. 나머지는 미관 |
| E1 실행 큐 | **제외** (사용자 결정) | |
| C4 윈도 1:N | **판단 보류** | 한 채널에 두 창을 실제로 돌릴 일이 있는지 확인 필요. 없으면 영구 제외 |
| D3 일일 R 점검 | **판단 보류** | Oculus의 RMonitor·R 추세 대시보드와 겹침. 경계 정리 먼저 |
| B1 날짜범위 로딩 | **판단 보류** | DateLoadDialog가 이미 함. 다운샘플은 실제로 느린지 재보고 결정 |
| C2 출처 배지 / C3 Test Fit 상주 | **후순위** | 값은 있으나 급하지 않음 |

## 완료

- [x] **A1** `.meta.json` 사이드카 — `core/run_meta.py` · `app_window._calibration_state`/`_qc_state` ·
      RUN 시점 설정 동결. `.dat` 포맷 불변. 검사 `python core/run_meta.py`
- [x] **A2** runid = 설정 해시 — 파일·종순서 무관, basename만 해시(머신 독립), legacy는 `L…` 접두
- [x] **A3** 배치 통일 — `output/{campaign}/{YYYY-MM-DD}/{kind}/{날짜}_{CH}_{label}_{runid}`.
      디렉터리는 시간축만, 패싯은 meta로. 읽기는 세 구조 전부.
      검사 `python tools/test_result_layout.py`
      · **2026-09-14 확장**: 핏만 쓰던 것을 **알파·R·그림까지** 같은 캠페인 폴더로 모았다
        (그전엔 각자 사용자가 고른 폴더에 흩어져 "어느 핏이 어느 알파에서 나왔나"가 안 보였다).
        알파 = `{out}/{campaign}/{날짜}/alpha/{채널}/`(worker), R = `{out}/{campaign}/`
        루트만 이동(내부 `R_<채널>/{날짜}/`는 `r_trend_monitor.py` 것을 그대로 — CLI 단독
        실행을 안 깨려고), R(t) npz = `{campaign}/calibration/`, 그림 = `{campaign}/figures/`
        (저장 다이얼로그 **시작 위치**일 뿐 강제 아님. 그림은 여러 날을 걸쳐 날짜 폴더가 무의미).
        캠페인 값은 `gui/dlg_dir.campaign_of(widget)`가 부모 사슬에서 한 번에 찾는다.
      · **라벨↔구성 연결은 B안(2026-09-14 결정)**: 파싱 구성의 **선택은 데이터(raw 열 수)가**
        하고, **기록만** 남긴다. 사람이 친 campaign 라벨(폴더 이름)과 기계가 고른 구성이
        달라도 그건 오류가 아니라 정보다(예: `yeosu_2026` 폴더에 아라온 raw를 넣어 본 경우).
        라벨이 파싱을 강제하는 C안은 **일부러 안 했다** — 열 수는 데이터고 라벨은 사람의
        기억이라, 라벨이 이기면 조용히 틀린 파싱이 된다.
        · 알파 헤더에 `# raw_layout: ncols=… campaign=… parser=DataIO-dynamic` 한 줄.
          ⚠ 알파 생성은 `RawParser`가 아니라 `DataIO` 동적탐지를 쓰므로 레지스트리 이름은
          **참조**일 뿐이다 — `parser=`를 같이 적어 그 구분을 남긴다.
        · 핏 `.meta.json`에 `layout` 블록(`core.run_meta.layout_from_input`이 알파 헤더나
          raw 열 수에서 뽑는다). **runid 해시엔 안 들어간다** — 설정이 아니라 입력의 성질이라
          같은 설정이면 입력이 달라도 runid는 같아야 한다(자기검증에 불변식으로 걸어둠).
        · 모르면 안 적는다(None) — 추측한 provenance는 없느니만 못하다.
- [x] **A4** 레거시 backfill — `tools/backfill_meta.py`, dry-run 기본.
      검사 `python tools/backfill_meta.py --self-check`
- [x] **D1** 측정일 감사 — `core/day_audit.py` (신설) · `gui/r_workers.DayAuditWorker` ·
      Setup Status에 `🩺 Audit Day` 버튼 + 6번째 줄 · 결과를 `.meta.json`의 `day_audit`에 기록.
      검사 `python -m core.day_audit`
      · **기대 주기를 코드에 안 박았다** — 기본은 그날 관측 간격의 중앙값, 아는 주기가 있으면
        `expected_period_sec={'ZA':300,'He':900}`로 고정. 데이터가 기준을 정한다
      · 1회 결손 = WARN, 연속 결손(>2.8×주기) = FAIL, 하루 전무 = FAIL
      · **차단하지 않는다** — 보고만 하고 RUN 여부는 사람이 정한다(헌장: 검증 ≠ 필터)
      · 전이 flag(502/503/512/513)는 블록으로 안 센다. R 계산이 쓰는 안정 구간(500/510)만
      · 알파 입력이면 SKIP — ZA는 I₀로, He는 R로 소비돼 알파엔 안 남는다
      · **사람이 GUI에서 확인할 것**: 실제 캠페인 raw 하루를 로드하고 `🩺 Audit Day` →
        (a) 블록 수·주기가 실제 운용(ZA 30s/5min · He 30s/15min)과 맞는지,
        (b) 2 GB 스캔이 몇 초 걸리는지, (c) 알려진 결손일에 FAIL이 뜨는지
      · **안 한 것**: 24시간 축 타임라인 그림(원본 목록 항목). 한 줄 판정 + 툴팁으로 갈음했다 —
        그림은 B2의 잔차 패널이 생긴 뒤 같은 자리에 붙이는 게 싸다
- [x] **B3** 버전 목록 + 설정 diff — `core/run_meta.py`에 `diff_meta`·`summarize_diff`·
      `find_versions`·`version_search_root` · Result Lab 좌측 아래 Versions 패널.
      검사 `python core/run_meta.py` · `python tools/test_result_layout.py`
      · **diff는 runid 해시와 같은 키 집합(`_RUNID_KEYS`)을 본다.** 목록을 따로 두면
        "runid는 다른데 diff는 비었다"가 나와 버전 목록이 거짓말을 한다.
        자기검증에 **runid 다름 ⟺ diff 비어있지 않음** 불변식을 걸어놨다
      · 종은 인덱스가 아니라 **이름**으로 평탄화 — 순서만 바뀐 걸 전부 다르다고 하지 않는다
      · `version_search_root` = 날짜처럼 생긴 가장 가까운 상위 폴더. A3에선
        `{campaign}/{YYYY-MM-DD}/`, 레거시에선 `{day}/`라 **neg/QC 버킷을 가로질러** 찾는다
        (옛 구조에선 QC만 다른 재핏이 다른 폴더에 있어 파일 폴더만 보면 놓친다)
      · legacy meta(`L…`)는 `⚠ partial`로 표시 + 툴팁에 "일부 설정 미상" 명시
      · 툴팁에 전체 diff(최대 20줄)와 **day audit WARN/FAIL**을 같이 띄운다 —
        "이 버전이 R(t) 외삽 구간 위에서 나왔나"가 버전 비교의 핵심 질문이라서
      · 부가 패널이 본체를 막지 않는다 — 목록 갱신이 실패해도 플롯은 그대로
      · **사람이 GUI에서 확인할 것**: 같은 날 같은 채널을 설정 바꿔 2번 저장 →
        Result Lab에서 하나 열었을 때 (a) 두 버전이 다 보이는지, (b) 바뀐 항목이
        한 줄에 맞게 나오는지, (c) 다른 버전 클릭 시 그게 로드되는지
      · **안 한 것**: 이상치 수 칸(원본 목록). Status 문자열이 자유형식이라
        무엇을 이상치로 셀지가 파일마다 다르다 — RMS 중앙값만 넣었다
- [x] **C1** 종 정책 테이블 상시 노출 — `gui/ref_properties_dialog.py`에
      `RefPropertiesTable(QWidget)` 추출, 다이얼로그는 그걸 감싸기만 한다.
      Setup 탭 Parameters 아래에 접이식으로 상주.
      검사 `python tools/test_ref_properties_table.py` (7 케이스)
      · `get_properties()` 계약 불변 — 다이얼로그의 `.table`/`.gas_list`/`.param_widgets`도
        프로퍼티로 남겨 하위호환
      · 상시 패널은 **OK 버튼이 없다** → `changed` 시그널로 즉시 `ref_props` 반영.
        팝업은 그대로 남긴다(넓은 창 + **Cancel 되돌리기**가 필요한 경우가 있음)
      · 가스 목록 재구성은 `_refresh_shsq_summary()`에 붙였다 — 레퍼런스 락·채널 전환·
        시나리오 적용에서 이미 전부 호출되는 지점이라 새 훅을 안 만들었다.
        재구성 중 `blockSignals`로 `ref_props` 덮어쓰기 차단
      · 토글은 `isVisible()`이 아니라 명시적 플래그 — 부모 탭이 숨으면 `isVisible()`이
        False라 토글이 어긋난다(이 파일의 `_adv_params_visible`과 같은 방식)
      · **덤으로 잡은 기존 버그**: `_shsq_text`의 모드 사다리가 Link/Limit/Fix가 아니면
        전부 'Free'로 떨어져 **`Center -5.25, 1.9`가 'Free'로 표시**됐다. 의미가 정확히
        반대고(Free=제약 없음, Center=선언 중심에 앵커), 같은 함수를 **RUN 직전 확인
        다이얼로그**도 써서 밤샘 런의 마지막 검문이 거짓이었다. Center는 `@중심,반폭`,
        모르는 모드는 `?모드`로 드러낸다(불변식 5)
      · **사람이 GUI에서 확인할 것**: 레퍼런스 락 → Setup에 테이블이 뜨는지,
        (a) 거기서 Link를 바꾸면 위 한 줄 요약이 즉시 따라오는지,
        (b) ⚙️ Properties 팝업과 값이 일치하는지, (c) 좁은 화면에서 레이아웃이 안 밀리는지
      · **안 한 것**: 왼쪽 패널 폭이 좁아 8컬럼이 빡빡할 수 있다. 화면에서 보고
        컬럼을 줄일지(T_ref·dσ/dT를 팝업 전용으로) 판단 필요

- [x] **E3** autosave에 runid — `{campaign}/_autosave/{runid}.tsv`, 정식 저장 성공 시
      `_archive`로 이동(삭제 아님).
      · save()의 meta 조립 클로저를 `_build_run_meta(ch, …)` **메서드로 승격** —
        autosave 파일명과 결과 파일의 runid가 **반드시 같아야** 이름이 거짓말을 안 한다.
        `data_days`·`rows`는 해시에 안 들어가므로 autosave가 비워 불러도 같은 값이 나온다
      · 같은 이름이 이미 있으면(= 정식 저장 못 한 이전 런) 덮지 않고 `_archive`로

- [x] **E2** 진행 표시 정리 — **ETA·처리율은 애초에 없었다**(문서의 지적은 "만들지 말라"는
      경고였고 실제로 만든 적이 없음). 실제로 고친 것:
      · Step 모드에 진행 숫자가 텍스트로 없던 것(막대만 움직였다) → `_progress_text()`로 통일
      · **"settings frozen for this run"** 명시 — RUN 시점에 설정을 동결하는데(A1)
        화면엔 그 사실이 없어서 RUN 중 편집이 반영되는 줄 알 수 있었다
      · 속도 예측은 넣지 않았다 — 워커가 emit하는 건 `progress`/`total_ready` 둘뿐이라
        어떤 추정도 근거가 없다

- [x] **B2** 종 스택 + flag 색 + 클릭 → 아래 패널 — `gui/ui_result_viewer.py` 대폭,
      `gui/result_viewer_io.load_fit_table`에 shift/squeeze 추가.
      검사 `python tools/test_result_lanes.py` (5 케이스)
      · **종마다 레인**, x축만 링크. 예전엔 전 가스를 한 축에 겹쳐서 스케일이 다른 종
        (H2O ~1e-12 vs NO2 ppb)이 서로를 납작하게 만들었다
      · 레인 구성: 종별 N개 + shift/squeeze(squeeze는 1을 빼서 shift와 같은 축에) + RMS.
        맨 아래 레인만 x눈금을 그린다
      · **flag 색** — ok(가스색) / unstable(적) / settling(회) / qc(주황) / cal(보라).
        Status가 자유형식이라 부분일치로 읽고, **값은 지우지 않는다**(헌장 ①).
        'Hide QC'를 켰을 때만 숨기고 그때도 개수를 제목에 적는다
      · **클릭 → 팝업이 아니라 아래 패널.** 시계열이 계속 보인다. 부수효과로
        "클릭 x좌표에서 최근접 점 되짚기 + 시간시프트 역보정"이 통째로 사라졌다 —
        산점도가 어느 점을 눌렀는지 직접 알려주므로 오차 원인 하나가 제거됐다
      · 레인은 풀로 재사용한다(파일 바꿀 때마다 위젯이 쌓이면 메모리가 샌다)
      · **스택은 fit 전용** — R커브·α·레퍼런스 등 나머지 6개 핸들러는 예전 2단 플롯을
        그대로 쓴다(건드리지 않음). 구간선택(region)은 `_primary_plot()`로 따라간다
      · **사람이 GUI에서 확인할 것**: 실제 결과 파일을 열어 (a) 레인 높이가 종 수만큼
        늘어도 볼 만한지(4종이면 6레인), (b) 한 레인을 확대하면 나머지가 같이 움직이는지,
        (c) 이상한 점을 눌렀을 때 아래 α가 3초 안에 뜨는지
      · ✅ **잔차 패널 완료(2026-09-14, B안)** — 아래 "B2 잔차 패널" 절 참조.
        α 패널은 그대로 두고 그 아래 **잔차 전용 레인**을 하나 더 붙였다(x축만 링크)

- [x] **F2** UI 이모지 제거 — 화면 문자열 **0개** 잔존(주석 190·독스트링 142는 화면에
      안 나오므로 건드리지 않음).
      · 아이콘 전용 버튼 11개에 ASCII 라벨(`+` `X` `Load` `Save` `...` `Col` `R(t)` 등)
      · **화살표·기하도형(→ ← ▶ ▼ ✕ │)은 이모지가 아니라 의미**라 보존/복구
      · ⚠ **기계적 스윕이 실제로 코드를 깨뜨렸다 — 다음에 비슷한 걸 할 때 참고**:
        1차 정규식이 `[^\n]`을 "백슬래시와 **문자 n** 제외"로 읽어 'Range'처럼 n이 든
        문자열 103개를 건너뛰었다. 삼중따옴표 독스트링도 걸렸고, `→`·`│`·`▼`가 지워져
        Link 표시와 구분자가 사라졌다. **잡아낸 건 테스트뿐이다**(C1의 `_shsq_text` 검사).
        HEAD 대조 피해 스캔은 **미커밋 신규 코드를 못 본다** — 그 부분은 자기검증이 유일한 방어


## 남은 단계

**없음 — 계획한 11항목 전부 완료.**


## B2 잔차 패널 — **B안(meta 기반 재핏)으로 완료 (2026-09-14, 사용자 결정)**

원본 목록은 "점 클릭 → 잔차"였는데 저장된 `.dat`에는 잔차 벡터도 핏 계수도 없다
(`Params`는 저장 시 drop). 그래서 **그 스캔을 다시 핏**하되, *지금* 설정이 아니라
**그때 설정(`.meta.json`)** 으로만 핏한다 — 지금 설정으로 그린 잔차는 화면의 그때 농도와
대응하지 않는 "조용히 틀린 그림"이기 때문. A1이 설정 전량을 meta에 남겨둔 덕에 가능해졌다.

구현: `core/refit.py`(신설) · `core/run_meta.meta_to_cfg`(build_meta의 역변환) ·
`core/param_optimizer.fit_scan(return_model=True)` · `gui/ui_result_viewer._draw_residual`.
검사 `python -m core.refit` · `python tools/test_result_lanes.py`

**규칙 — 복원이나 재현에 실패하면 잔차를 아예 안 그리고 사유를 적는다.** 거부 5종:

| # | 사유 | 왜 |
|---|---|---|
| 1 | `.meta.json` 없음 | 레거시 결과. `tools/backfill_meta.py`로 생성 가능 |
| 2 | legacy meta(`L…`) | 헤더에서 복원한 **부분** 설정이라 그때 설정이 아님 |
| 3 | 캘리브 확정 불가 | wavecal/레퍼런스를 못 찾거나 채널 확정 불가 |
| 4 | 알파 행 없음 | 옆에 알파가 없거나 그 `row_idx`가 없음 |
| 5 | **재현 실패** | 재핏 농도가 저장 농도와 1%(`REPRO_TOL_REL`) 넘게 어긋남 |

설계상 짚어둘 것:

- **웜스타트는 복원할 수 없다.** 그 행은 직전 스캔의 shift를 이어받아 핏된 결과인데
  (§5.3 시간축 이어받기), 한 스캔만 떼어 재핏하면 그 이력이 없다. 그래서 **결과 표에 저장된
  그 행의 shift/squeeze를 `controlled_start`로 주입**하고, 그래도 농도가 안 맞으면 5번으로
  거부한다. 이것이 §10-9 경로의존성이 이 기능에 나타나는 지점이다.
- **채널 확정은 이름이 아니라 알파의 파장축으로 한다.** meta는 머신 독립을 위해 basename만
  갖는데(runid 계약) `Ref_NO2_Dynamic-ILS-Applied.dat`·`Calib_20260619_….txt`가 cold/roi1/roi2에
  **같은 이름·다른 내용**으로 있다(md5 확인). 이름으로 고르면 다른 채널 단면으로 핏한다.
  `resolve_calibration_dir`이 후보 wavecal을 알파 헤더의 파장축과 대조해 **데이터로** 고르고,
  둘 이상이 맞으면 확정 불가로 거부한다.
- **λ·robust는 meta의 `qc` 블록에서 가져온다.** 기본값(0/False)으로 때우면 다른 핏이 된다.
- **읽기 전용** — 원본 파일도 활성 GUI 엔진도 건드리지 않는다. 임시 엔진을 새로 만든다.

남은 것(사람 확인): 실제 결과 파일에서 (a) 재현이 통과하는 비율이 쓸 만한지,
(b) `REPRO_TOL_REL` 1%가 너무 빡빡하지 않은지 — 실측 후 조정.

## 점검에서 나온 것 (2026-09-14)

- [x] **ppb 환산 단일화** — `n_air`(이상기체 수밀도)가 코어 4곳·GUI 3곳·도구 5곳에 **복사**돼
      있었다. 농도를 만드는 마지막 한 줄인데 정작 `core/physics.py`엔 없었다(헌장 위반,
      과거 Rayleigh 사본으로 R이 틀어진 사고와 같은 패턴).
      `core.physics.air_number_density()` + `N_LOSCHMIDT` 상수로 모으고 전부 위임.
      검사 `python -m core.physics` (STP 값·P/T 의존성·Rayleigh와 같은 상수 사용·
      코어 4모듈이 사본이 아닌 **같은 함수 객체**를 쓰는지)
      · ⚠ **상수가 두 값으로 돌아다니고 있었고, 둘 다 틀렸다**:
        ppb 환산 `2.68678e19`(정답의 6자리 절단, 오차 −4.2e-8) · Rayleigh `2.6867811e19`
        (**CODATA 2014 구값**, 오차 +3.7e-7 — 9배 나쁨). "소수점 많은 쪽"이 정확한 쪽이
        아니었다. 2019 SI 재정의 이후 n₀ = p/(k_B·T)가 **정확히 계산되는 값**이므로
        매직넘버 대신 정의 상수에서 **유도**한다(= CODATA 2018, 2.686780111e19).
        결과 변화: 농도 **−4.2e-8**, Rayleigh α **+3.7e-7** (둘 다 상대) — 계통항이지만
        이 저장소가 이미 잡아낸 계통편향(King factor 0.15%, O₂ 오타 0.5%)보다 네 자릿수 작다.
      · `core/health_checks.py`·`tools/validate_pipeline.py`의 Rayleigh 검사도 **자기 N0 사본**
        으로 α를 σ로 되돌리고 있었다 → 같은 상수를 쓰게 고쳤다. 이제 그 검사는 상수값이
        바뀌어도 흔들리지 않는다(σ는 분자 고유값이라 밀도와 무관해야 하므로 이게 옳다).
      · 보존된 진단 스크립트의 사본은 **일부러 안 고쳤다**(그때 그 계산의 증거라서):
        `cold_validation_2026_05`, `parallel_shift_bench`,
        `alpha_vs_matlab_2025_06_11/compare_alpha.py`(MATLAB 재현이 목적 — 주석 추가),
        `qdoas_crossval_2026-09/compare_*.py`(nominal 값 유지 + 차이 설명 주석).
        진행 중인 `qdoas_crossval_2026-09/AUGUR_realconc_TP_export_task.md`는
        "식을 복사하지 말고 `core.physics.air_number_density`를 임포트하라"로 갱신
      · **MATLAB과의 이탈은 의도된 것**: 두 구현에서 α의 N₀ **지수가 반대**다
        (MATLAB σ에 N₀ 없음 → α ∝ N₀⁺¹ / Augur σ ∝ 1/N₀² → α ∝ N₀⁻¹). 같은 상수를 넣어도
        α는 반대로 움직이므로 상수를 맞춰서 정렬되는 건 없고, 구값의 +3.7e-7 오차만 남는다.
        근거는 `core/physics.py`의 MATLAB 경험식 주석에 기록
      · `test_fit_explorer_cold_o4_*`의 공식 **문자열**(provenance)도 같이 갱신 —
        안 고치면 기록이 거짓이 된다

- [x] **오차 예산 스캐폴드** — `core/error_budget.py` (신설).
      한 농도값의 불확도를 항목별로 분해하고, **정량화 안 된 항을 `미정량`으로 남긴다**
      (빈칸이 보여야 뭘 모르는지 알고, 그게 채워지는 순서가 곧 우선순위).
      검사 `python -m core.error_budget` · 실제 파일 `python -m core.error_budget <결과.dat> [가스]`
      · 지금 계산되는 것: 핏 공분산 · T/P 전파(**TotalError에서 빼서** 분리 — 이중계산 금지)
        · 이상기체 Z 편향(+0.02~0.05%, 계통)
      · 미정량 4항(= 논문 §10-2에서 채워야 할 것): **단면 문헌 불확도**(3~5%로 최대항일
        가능성) · **σ(R)→경로길이** · **캐비티 d·R_L** · **잔차 고정패턴**(§10-1)
      · 무작위(√Σσ²)와 계통(선형합)을 **뭉개지 않는다** — 계통은 평균해도 안 줄어든다
      · 표 하단에 "이 표는 **하한**이다"를 항상 찍는다. 미정량이 남은 채로 총 불확도를
        말하지 않기 위해서

## 절대 깨뜨리지 말 것

1. **flag-only** — QC는 값을 지우지 않는다. 이유를 남긴다
2. **`.dat` 포맷** — 안 바꾼다. meta는 옆에
3. **레거시 파일** — 이름 안 바꾸고 삭제 안 한다. `_archive`로 옮길 뿐
4. **Test Fit Apply 잠금** — 퇴화 분기(|ac1| 문턱) 시 Apply 비활성 유지. 자동 적용 금지
5. **shift Center 변환** — 0을 품지 않는 Limit은 첫 스캔에서 죽는다 (핸드오프 §15-E 불변식1)
6. **QDOAS 부호 규약** — shift 부호 반전은 한 곳에서만
7. **α 파일의 px_start** — `pxNNN` 헤더 무시하면 조용히 틀린 창을 핏한다
8. **UI 문자열은 영문** — 논문 스크린샷용

## 매 단계 회귀 검사

```
python tools/validate_pipeline.py --no-data
python core/run_meta.py
python -m core.physics
python -m core.error_budget
python -m core.refit
python tools/test_raw_layout.py
python -m core.day_audit
python tools/test_result_layout.py
python tools/backfill_meta.py --self-check
python tools/test_ref_properties_table.py
python tools/test_result_lanes.py
python tools/validate_plotmaker.py
```

`tools/ci_import_smoke.py`는 **1 FAIL이 기존 상태**다 — untracked QDOAS 진단의
하드코딩 경로(`/root/.claude/uploads/...ASC`). 내 변경 탓이 아니다.
