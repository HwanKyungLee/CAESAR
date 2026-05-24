# CAESAR Pro — 세션 핸드오프 노트

> 다른 컴퓨터/세션의 Claude Code가 이어받기 위한 진행 상황 기록.
> 최종 업데이트: 2026-05-24

---

## 0. 현재 깃 상태

- **작업 브랜치**: `claude/great-bardeen-s28sN` (GitHub PR #6, DRAFT)
- **PR #6 = main + 4커밋** (충돌 없음, main보다 앞서 있음):
  ```
  7b49bdd  fix: HITRAN 생성 시 로컬 캐시 재사용 (오프라인/API 다운 대응)   ← 이번 세션
  6a00399  fix: FWHM 프로파일 로더가 AVERAGE 요약 행에서 죽던 문제 해결      ← 이번 세션
  b017f26  Make reference-generator ILS convolution robust ...            ← 클라우드 세션(원래 PR#6)
  d89e2fb  Fix O4 band-gating, shift drift lock, and pre-calibration grid ← 클라우드 세션(원래 PR#6)
  ```
- **main 브랜치**에는 이 세션 전반부의 리팩토링이 이미 푸시됨 (아래 2번). PR #6는 그 위에서 분기되어 전부 포함.

---

## 1. 이번 세션 전반부 — 깃 구조 리팩토링 (main에 푸시 완료)

원래 평평했던 루트를 패키지/폴더 구조로 정리하고 GitHub에 푸시.

| 커밋 | 내용 |
|---|---|
| `06a8577` | `RayleighPhysics`, `KalmanTracker` 중복 제거 → `core/physics.py`로 통합. `gui/worker.py`·`tools/reflectance_calc.py`가 거기서 import |
| `fe6c6bd` | 144KB짜리 `gui/ui_dialogs.py`를 3개로 분리: `ui_dialogs_calib.py`(교정), `ui_dialogs_ref.py`(레퍼런스/모니터), `ui_dialogs_r.py`(R 도구). 기존 `ui_dialogs.py`는 하위호환 re-export wrapper |
| `a70ad5c` | `diagnostics/cold_fwhm_r_check.py` + `hot_fwhm_r_check.py` → `fwhm_r_check.py`로 병합 (`--mode cold\|hot`) |
| `ac0f1fa` | README를 새 구조로 갱신 |
| `e4c998a` | `app_window.py`에 남아있던 `from data_io import` (lazy import 2곳) → `from core.data_io import`로 수정 |

폴더 구조 요약: `core/`(연산·IO·물리), `gui/`(PyQt6 UI), `tools/`(오프라인 R 계산), `calibration/`, `campaigns/`, `diagnostics/`. 자세한 건 `README.md` 참조.

---

## 2. PR #6 검증 결과 (실제 데이터로 검증함)

클라우드 세션이 만든 DOAS 피팅 수정 2커밋(`d89e2fb`, `b017f26`)을 로컬 실데이터로 검증.

### 수정 내용 & 판정
| 수정 | 판정 |
|---|---|
| **O4 밴드 게이팅** — `ref_properties`에 `active_bands_nm`(예 `460,495`) 추가, 피팅 윈도우가 밴드와 안 겹치면 해당 가스 컬럼을 0으로 | ✅ 작동. 실제 교정으로 426-440nm→O4 비활성, 432-480nm→활성 확인 |
| **Shift 드리프트 락 해제** — `last_valid_shift`를 OK일 때만 갱신하던 걸 항상 갱신. `step_limit`(0.5px/scan)이 폭주 방지 | ✅ 타당. ±0.49999 영구 고착 해소 |
| **pre-calibrate 그리드** — shift 3포인트(0.5px) → 11포인트(0.1px) | ✅ (커밋 제목 "coarser"는 오기, 실제론 finer) |
| **Ref generator 견고화** — 좁은/무효 커널이면 직접 샘플링 fallback (kernel-sum=0 회피) | ✅ |

### ⚠️ 발견한 미결 이슈 — O4 보고값 (결정 보류)
- 게이팅된 가스 컬럼을 0으로 만들면 설계행렬이 특이(cond≈4e16)가 되고, `lsq_linear`가 O4 계수를 **0이 아닌 임의값(테스트에서 0.1)** 으로 반환.
- 2.4e29 발산은 확실히 막고(크래시는 `np.linalg.pinv`로 방지됨, worker.py:424), 타 가스(NO2/CHOCHO/H2O)는 보호됨(비트 동일). 하지만 O4 칸에 깨끗한 0 대신 무의미한 값이 찍힘.
- **제안 패치 (worker.py:435 `return` 직전)**:
  ```python
  c_gas = c_opt[0:num_gases].copy()
  for i, name in enumerate(self.engine.gas_list):
      if not gas_active[name]:
          c_gas[i] = 0.0   # 게이팅된 가스는 깨끗한 0으로 보고
  # 그리고 반환 시 c_opt[0:num_gases] 대신 c_gas 사용
  ```
- **사용자 결정**: "GUI로 실제 피팅부터 보고 결정" → 아직 실측 O4 값 확인 못 함 (다음 세션에서 진행).

---

## 3. 이번 세션 후반부 — GUI 실데이터 테스트 중 발견·수정한 버그

### (a) FWHM 로더 크래시 — 수정 완료 (`6a00399`)
- 증상: Reference Generator에서 "could not convert string to float: 'AVERAGE'".
- 원인: `gui/ui_dialogs_ref.py::load_fwhm_profile`이 FWHM 파일 끝의 요약 행(`AVERAGE 0.7775 0.3302`)까지 데이터로 읽음 → `ils_sigmas.astype(float)` 실패. (PR#6 무관한 기존 버그)
- 수정: `pd.to_numeric(errors='coerce')` 후 NaN 행 제거 + 3컬럼 포맷 처리.
- 트리거 파일 예: `D:\CAESAR cold\FWHM_Analysis_20260523_cold.txt`

### (b) HITRAN 생성 실패 — 수정 완료 (`7b49bdd`)
- 증상: H2O 생성 시 "cannot connect to http://hitran.org".
- 원인: `generate_hitran_gas`가 매번 `hapi.fetch()`로 다운로드 시도. hitran.org 홈은 200이지만 hapi API 엔드포인트가 불안정. 게다가 `db_begin('hitran_data')`가 상대경로라 기존 캐시(`C:\LGH\hitran_data`)를 못 봄.
- 수정: db_begin을 리포 루트 절대경로로 고정 + 테이블이 이미 `hapi.LOCAL_TABLE_CACHE`에 있으면 fetch 생략.
- **캐시 위치**: `<repo>/hitran_data/H2O_Lines.data`(7.4MB)+`.header`를 `C:\LGH\hitran_data`에서 복사해 둠. `.gitignore`에 `hitran_data/` 등록(깃에 안 올라감). **다른 컴퓨터에선 이 폴더가 없으므로**, 인터넷이 되면 자동 다운로드되거나, H2O는 hitran_data 폴더에 캐시를 복사해 두면 됨.

---

## 4. ★ 미해결 — 진행 중인 버그: 핏 레인지가 Run 시 멋대로 바뀜

### 증상
사용자가 픽셀 min/max를 설정하고 Run을 누르면 범위가 바뀜.
끊긴 결과 파일 헤더: `Fit Range: Pixel 600-848 (430.0-441.9nm)`.

### 정적 분석으로 확인한 것
- 파장 캘리브레이션 파일은 전부 2048점 → px848은 클램프 아님(실제 사용값).
- `start_analysis`(Run 핸들러)는 `txt_min`/`txt_max`를 **직접 안 바꿈** (worker에 값만 전달).
- 결과 파일명/헤더의 nm 범위는 **save 시점**의 `txt_min`/`txt_max`를 nm로 변환한 값 (app_window.py:2345-2361).
- 600-848 = 430-441.9nm는 `set_range_from_nm`(target±window, 예 436±6nm) 또는 모니터 ROI 드래그가 만드는 값과 일치.

### 유력 가설 (미확정)
Run 시 `start_analysis`가 **모니터 탭으로 자동 전환**(app_window.py:2195 `self.main_tabs.setCurrentIndex(2)`)함.
이때 그동안 숨어있던 모니터의 `pg.LinearRegionItem`(ROI)이 처음 렌더되며 `sigRegionChangeFinished`가 발화 →
`on_select_span_pg`(ui_dialogs_ref.py:1487) → `roi_selected.emit` →
`apply_roi_from_graph`(app_window.py:1976) → `txt_min/max.setText`로 덮어쓰기.
(연결: app_window.py:387 `self.monitor.roi_selected.connect(self.apply_roi_from_graph)`)
즉 예전에 ROI를 ~430-442nm로 드래그해뒀다면, Run 시 그 값이 사용자가 직접 입력한 값을 덮어씀.

### 다음 세션이 할 일 (진단 로그 이미 심어둠)
`app_window.py`에 임시 `[RANGE-DEBUG]` print를 4곳에 심어 둠 (커밋 `WIP: range-debug`):
- `update_range`, `apply_roi_from_graph`, `set_range_from_nm`, `_refresh_setup_status`의 클램프, `start_analysis` 시작점.
1. GUI 실행(`py -3 main.py`) → 데이터·레퍼런스·파장 로드.
2. 픽셀 min/max 직접 입력(예 536, 827) → Run.
3. 콘솔/출력파일의 `[RANGE-DEBUG]` 순서 확인. 만약
   ```
   [RANGE-DEBUG] === start_analysis READ pixel_min=536 pixel_max=827 ...
   [RANGE-DEBUG] apply_roi_from_graph(monitor ROI) -> 600,848  running=True
   ```
   이렇게 찍히면 **ROI 자동 덮어쓰기가 범인** 확정.
4. 확정 시 수정안: `apply_roi_from_graph`/`update_range`에서 `self._analysis_running`(이미 플래그 추가됨)이 True면 return하여 분석 중 덮어쓰기 차단. 또는 탭 전환 전 `self.region.blockSignals(True)` 처리.
5. **근본 원인 확정 후 `[RANGE-DEBUG]` print들 전부 제거할 것** (grep `RANGE-DEBUG`).

---

## 5. 환경 / 로컬 데이터 메모 (이 컴퓨터 기준)

- Python 실행: PowerShell에서 `py -3` (Bash의 `python`은 PATH에 없음, exit 127).
- 콘솔 한글/특수문자 깨지면 `$env:PYTHONIOENCODING="utf-8"`.
- GUI 실행: `py -3 main.py` (PyQt6 창).
- 로컬 데이터(이 컴퓨터에만 있음, 깃에 없음):
  - `D:\CAESAR cold\` — Cold 측정·교정·레퍼런스 (`2026-05\*.dat` 98MB Araon mega-matrix, `Calib_*_Poly2.txt` 2048점, `Ref_*_Dynamic-ILS-Applied(...).dat`)
  - `D:\CAESAR hot\` — Hot (roi1/roi2)
  - `C:\LGH\` — 작업 폴더, `hitran_data\`(HITRAN 캐시), `Absorption cross-section\`, 결과 .dat 등
- raw .dat 구조: col1=센티초(centiseconds, UTC초 아님), 타임스탬프는 파일 mtime, flag 500=ZA / 510=He. (자세히는 `tools/r_trend_monitor.py` 상단 docstring)

---

## 6. 재개 순서 (다음 세션)
1. `git checkout claude/great-bardeen-s28sN && git pull`
2. 4번(핏 레인지 버그) 진단 로그로 원인 확정 → 수정 → RANGE-DEBUG print 제거.
3. 2번 O4 보고값: GUI에서 426-440nm 피팅 돌려 O4 칸 실측값 확인 → 무의미하면 제안 패치 적용.
4. PR #6 정리 후 DRAFT 해제 / main 머지 검토.
5. (별개 백로그) `#1 전체 60개 파일 R 시계열 계산` — `tools/r_trend_monitor.py`.
