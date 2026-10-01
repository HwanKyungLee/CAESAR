# Result Lab · Plot Maker 데이터 자유도 설계 (2026-10-01)

> 그래프 쪽 자유도(표현 타입·주석·출판 규격·조판)는
> [`PlotMaker_자유도_설계_2026-09-21.md`](PlotMaker_자유도_설계_2026-09-21.md)에 있다.
> 이 문서는 그 문서가 다루지 않은 **데이터를 자유롭게 만지는 축**이다.
> 결정 기록이므로 안 하기로 한 것과 그 이유도 같이 남긴다.

## 0. 결정 요약 (2026-10-01)

| 질문 | 결정 |
|---|---|
| 다른 GUI 프레임워크로 갈아탈까 | **아니다.** 답답함의 원인은 Qt가 아니라 앱 구조(경로만 넘김, 숫자 열만, 파생/필터 없음)다. CustomTkinter·Streamlit·Flet·Dear PyGui·웹 프론트 모두 이 용도에선 후퇴이거나 전면 재작성 |
| 역할 분담 | **Result Lab = 진단·QC 현미경, Plot Maker = 가공·그림 작업대.** Result Lab에 표 편집·가공을 넣지 않는다 |
| 조판 A/B (09-21 §4 보류분) | **(B) mpl 전용 조판 + Preview 모덜리스·자동갱신.** 비용 ≈7곳 vs ≈83곳+가드 재작성 |
| 내장 파이썬 콘솔 | **넣는다, 맨 마지막(D3).** 레시피로 남지 않아 재현성을 깨므로, 자주 쓰는 조작을 D1·D2 레시피로 먼저 흡수한 뒤 진짜 예외만 맡긴다 |
| 외부 레퍼런스에서 추가 | ResultLab **구간 즉석 피팅**(OLS + Deming), **Copernicus 스타일 프리셋** 하나. 진짜 LaTeX(usetex)·ParameterTree·PlotPy 엔진 도입은 기각(§6) |

## 1. 진단 — 데이터가 자유롭지 않은 이유 (코드로 확인)

1. **두 탭이 경로만 주고받는다.** `ResultViewerWidget._to_plot_maker`(`gui/ui_result_viewer.py:1221`)는
   `send_to_plotmaker(list[str])`로 경로만 보내고 Plot Maker가 디스크에서 다시 읽는다.
   Result Lab의 Hide QC·사후 QC K·시간 시프트·선택 구간이 전부 증발한다.
2. **Plot Maker는 숫자 열만 안다.** `Dataset.cols`는 float 배열뿐(`gui/ui_plot_maker/data.py:17`).
   fit 파일의 `status`·`channel`은 `load_fit_table`이 주는데 `load_dataset`이 버린다.
   T·P·Shift·Squeeze도 버린다. → 헌장 ①("지우지 말고 flag")이 그림에서 끊긴다(09-21 부록 ①).
3. **파생 열·조건 거르기가 없다.** `gui/dlg_calculator.py`의 `safe_eval`은 순수 함수로 재사용
   가능하지만 비교·논리 연산이 없고(`where(A>5,…)` 불가), Calculator 다이얼로그는 fit 파일만
   읽으며 결과를 CSV로만 내보낸다.
4. **데이터셋 간 정렬이 Calculator에만 있고 최대 간격 가드가 없다**(09-21 부록 ④).
5. **탈출구가 없다** — 버튼에 없는 조작을 할 방법이 없다.

## 2. 핵심 원칙 — "값이 아니라 레시피를 넘기고 저장한다"

Plot Maker 설정(`.pmcfg.json`)은 데이터셋을 `이름 → 경로`로 저장하고 열 때 다시 읽는다.
이 구조를 깨고 메모리 배열을 넘기면 설정을 다시 열 때 재현이 안 된다(원칙 ④).

→ **Dataset은 계속 경로가 뿌리다.** 그 위에 얹는 모든 것(Result Lab에서 넘어온 QC·구간·시프트,
파생 열 식, 행 필터 조건)은 **재계산 가능한 규칙(dict)**으로 들고 다니고 설정에 같이 저장한다.
열 때 파일을 다시 읽고 규칙을 다시 적용한다. 값은 캐시일 뿐이다.

숨김은 **삭제가 아니다**(헌장 ①): 규칙은 `hidden` 마스크를 만들 뿐이고 `ds.cols` 원본은 불변,
규칙을 끄면 즉시 돌아온다.

## 3. 로드맵

### D0. 공용 데이터 모델 + 레시피 다리 *(모든 것의 전제)*

**Dataset 확장** (`gui/ui_plot_maker/data.py`)
- `cats: {이름: ndarray[str]}` — 범주형 열. fit이면 `Status`·`Channel`·`Flag`(ok/unstable/settling/qc/cal).
  `cols`(숫자)와 분리 — 기존 `column_choices`·모드 코드는 숫자 열만 보므로 영향 없음.
- fit 파일에서 버리던 숫자 열 `T`·`P`·`Shift`·`Squeeze`도 `cols`에 싣는다.
- `rules: list[dict]` + `rules_on: bool` — 보기 규칙. `hidden` 마스크는 규칙에서 계산(캐시).
- `shift_h: float` — **데이터셋별** 표시 시각 보정(전역 시프트에 더해짐). 채널마다 tz 기준이
  다른 문제(09-21 부록 ②)의 첫 발판이기도 하다.

**규칙 종류 (D0에서 넣는 것)**
| kind | 의미 | 출처 |
|---|---|---|
| `status_qc` | Status가 `QC*`인 행 숨김 | Result Lab "Hide QC" |
| `rms_k` | 채널별 robust RMS 임계(K) 초과 행 숨김 — `core.result_io.robust_rms_thresholds` 그대로 | Result Lab 사후 QC K |
| `time_range` | `[t0, t1]` 밖 행 숨김 (원본 시각 기준) | Result Lab Range 선택 |

**단일 출처**
- `_flag_of`(Status → flag 키)와 QC 마스크 조립을 `gui/result_viewer_io.py`의 순수 함수
  `flag_of()`·`qc_hidden_mask()`로 뺀다. Result Lab과 Plot Maker가 같은 함수를 쓴다(원칙 ③).
  RMS 임계식 자체는 계속 `core/result_io.py`에만 있다.

**다리**
- `send_to_plotmaker`가 `list[dict]`(`{"path", "rules", "shift_h"}`)를 보낸다.
  Result Lab은 현재 상태를 규칙으로 번역만 한다.
- Plot Maker `add_specs(specs)` 신설, `add_paths`는 그 얇은 래퍼(다른 호출부 그대로).
- `resolve()`가 `rules_on`이면 `hidden` 행을 NaN으로 낸다 → 모든 모드·Publish가 같은 경로로 받는다
  (화면·출력 드리프트 없음). 데이터셋 시프트도 `resolve()`에서 더한다.

**UI (최소)**
- 데이터 트리의 데이터셋 줄에 `· N hidden` 표시, 툴팁에 규칙 목록과 시프트.
- 데이터셋 줄 우클릭: **Filters on/off**, **Clear filters**.
- Publish 바닥글(이미 전역 시프트를 적고 있음)에 데이터셋 시프트·숨김 수를 같이 적는다.

**설정 저장**: `datasets: {이름: 경로}` → `{이름: {"path", "rules", "rules_on", "shift_h"}}`.
읽는 쪽은 문자열(옛 형식)도 받는다.

**검증**: `validate_plotmaker.py`에 ① 다리 왕복(규칙→hidden 마스크가 Result Lab `_qc_mask`와
행 단위 동일) ② 규칙 끄면 원본 복원 ③ 설정 저장→열기 후 마스크 동일 ④ 옛 형식 설정 열림.

**구현 메모 (2026-10-01, 완료 — 검증 34번)**

- 비교 기준은 Result Lab의 `_stats_arrays()` 선택 마스크(Σ Stats가 쓰는 것)다. 합성 리포트
  120행에서 Plot Maker 숨김 47행이 행 단위로 정확히 같다.
- 규칙 번역은 **fit 파일을 보고 있을 때만** 한다(`view_rules`). `_fit_cache`는 마지막으로 연
  fit 파일 것이라, 농도 CSV를 보는 중에 쓰면 엉뚱한 파일의 QC·구간이 실린다. 시프트는 종류 무관.
- 구간 규칙은 Export/Stats와 같은 `_region_times()`를 쓴다 — 전체 범위면 규칙을 만들지 않는다.
- 모르는 규칙 kind는 `ValueError`(조용히 무시하면 걸렀다고 믿는다). `load_spec`이 로드 시점에 한 번 계산해 즉시 터뜨린다.
- **출력이 바뀌는 곳 하나**: fit 데이터셋에 `T`·`P`·`Shift`·`Squeeze` 열이 생겨서, 아무 열도
  고르지 않은 채 상관 히트맵을 열면(전 열 폴백) 그 열들도 들어간다. 전부 NaN인 열은 싣지 않는다.
- 우클릭 메뉴: Filters on / Clear filters / Clear dataset time shift. 규칙 편집 UI는 D2.

### D1. 파생 열 (식을 저장)

- 데이터셋 우클릭 → **New column…**: `이름 = 식`. 예 `NO2_ugm3 = NO2 * 1.88`, `ratio = NO2 / O3`.
- `safe_eval` 재사용 + 비교(`< <= > >= == !=`)·논리(`& | ~`)·`nan`·`isfinite`·`clip` 추가.
  `eval()`은 여전히 금지.
- 범주형 열과의 비교 허용: `where(Flag == "ok", NO2, nan)`.
- 같은 데이터셋 안에서만(시간축이 같다). 데이터셋 간 계산은 정렬(D1+) 뒤.
- `ds.derived: list[{"name","expr"}]`로 저장, 열 때 재계산. 트리에 `ƒ` 표시. 식이 깨지면(열 이름 변경 등)
  조용히 빼지 않고 빨간 표시 + 툴팁에 오류.
- `dlg_calculator.py`는 당분간 그대로 둔다(산출물이 CSV인 별도 흐름). 식 엔진만 공유.

**구현 메모 (2026-10-01, 완료 — 검증 35번 + `tools/test_core_expr.py`)**

- 식 엔진을 `gui/dlg_calculator.py`에서 **`core/expr.py`**(Qt 비의존)로 옮겼다. 계산기는 그걸
  import만 한다 — 옛 식은 그대로, 비교·논리·`isfinite`·`clip`·`mean/median/std`가 덤으로 생겼다.
- 식에서 쓸 수 있는 이름: 숫자 열, 범주형 열(`Status`·`Flag`·`Channel`), `time`(epoch초),
  `hour`(로컬 0–24, **데이터셋 시프트를 따른다** — 시프트를 바꾸면 재계산). `hour`는 머신 TZ
  오프셋 하나를 쓴다(한국은 DST 없음).
- 우클릭: 데이터셋/열 → **New column…**, 파생 열 → **Edit / Delete**. 대화상자가 타이핑을
  200 ms 모아 평가해 `✓ 유효 개수 · 범위` 또는 `✗ 오류`를 보여주고, 오류면 OK가 꺼진다.
- **잡은 버그(구현 중)**: 처음엔 재계산 때 "지금 목록에 있는 파생 열"만 걷어냈다 → 열을
  지우거나 이름을 바꾸면 **옛 값이 cols에 남아** 그걸 쓰던 식이 멀쩡히 계산됐다(의존 깨짐이
  안 드러남). 이제 `_dcols`(마지막으로 채운 열)를 걷어낸다. 같은 수정으로, 설정 파일을 손으로
  고쳐 원본과 같은 이름의 파생 식이 와도 **원본 열은 절대 지워지지 않고** 그 식이 빨갛게 뜬다.
- 깨진 식은 그 열만 빠지고 `✗`로 트리에 남는다(플롯 대상 아님). 의존 열을 지우면 연쇄 열도 `✗`.

### D2. 행 필터 + flag 색

- 규칙 종류에 `expr`(사용자 조건식, 예 `T > 290 & Flag == "ok"`) 추가 — D0 규칙 틀 그대로.
- 데이터셋 우클릭 → **Filters…** 대화상자에서 규칙 목록 보기·켜고 끄기·추가.
- TimeSeries 시리즈 스타일에 **Color by: Flag** — Result Lab `_FLAG_COLOR`와 같은 색(`gui/theme`).

**구현 메모 (2026-10-01, 완료 — 검증 36번)**

- 규칙 `{"kind": "expr", "expr", "mode": "keep"|"hide"}`. **keep = 조건이 참인 행만 남김** —
  NaN 비교는 거짓이라 숨겨진다(예 `T > 290`이면 T 없는 행도 숨김). 반대로 숨기고 싶으면 hide.
  모든 규칙에 `"on": False`(개별 끄기, 지우지 않음).
- **필터는 데이터셋 단위만** 넣었다(시리즈 단위는 안 함). 같은 데이터셋의 열들이 서로 다른 행을
  보여주면 Scatter·상관에서 짝이 어긋난다. 시리즈마다 다르게 거르고 싶으면 파생 열
  `where(조건, X, nan)`로 된다.
- 조건식은 파생 열을 쓸 수 있다(파생 → 필터 순으로 계산).
- **깨진 조건식 규칙은 그 규칙만 아무것도 안 숨긴다** + 트리 `✗ N broken filter`·툴팁·대화상자에 빨간 표시.
  과필터링이 더 위험하다는 헌장과도 맞고, 열 이름이 바뀐 파일 때문에 데이터셋을 통째로 못 여는 것도
  막는다. 모르는 kind(레시피 자체 오류)는 여전히 ValueError.
- 우클릭 → **Filters…**: 목록(체크=on/off)·Remove·조건 편집(Add/Update)·조건 하나만의 숨김 수
  미리보기·전체 숨김 수. 식이 깨지면 Add가 꺼진다.
- **Flag 색칠은 Raw일 때만**: 리샘플·평활은 여러 행을 섞어 "그 점의 flag"가 없다 → 끄고 상태줄에
  `flag colours off while resampled/smoothed`. ok가 아닌 점만 Result Lab과 같은 색으로 덧그리고,
  범례에 `flag: qc` 등 flag마다 한 번. 색은 `result_viewer_io.flag_color` 단일 출처(Result Lab도 이걸 씀).
- **덤으로 잡은 버그**: 시리즈 스타일 창에서 OK를 누르면 스타일 dict를 통째로 덮어써서 **숨겨둔
  시리즈가 다시 나타났다**(M-O 표시 토글과 충돌). 이제 대화상자에 없는 키는 보존.

### D1+. 데이터셋 간 시간 정렬

- `align(ds_a, ds_b, max_gap)` 한 함수 — 최근접/선형, `max_gap` 넘으면 NaN.
  Scatter `_xy()`(`modes.py`)의 `np.interp`와 Calculator 정렬이 이걸 쓰게 한다(부록 ④의 앞절반).
- 결과는 새 가상 데이터셋 `A⋈B`(규칙: 두 출처 + max_gap — 역시 레시피).

**구현 메모 (2026-10-01, 완료 — 검증 37번 + `tools/test_core_align.py`)**

- 정렬 함수는 **`core/align.py`**(Qt 비의존) `align_to(t_ref, t_src, v_src, max_gap, method)`.
  Plot Maker `processing`은 재노출만. linear = 감싸는 두 점 간격 ≤ max_gap일 때만 보간,
  nearest = 가장 가까운 점이 max_gap/2 안일 때만(동점은 앞 점). 같은 시각은 언제나 그 값.
- 기본 max_gap = 원본 간격 중앙값 × **`core/day_audit.GAP_FACTOR_FAIL`(2.8, 연속 결손)** — 판정
  배수 단일 출처. 같은 파일의 1.8(`GAP_FACTOR`)은 너무 예민해 정상 지터에도 끊긴다.
- **출력이 바뀌는 곳 둘** (부록 ④의 수정 자체):
  1. Scatter에서 X·Y가 다른 데이터셋이면, 예전엔 `np.interp`가 결손을 가로질러 직선으로 메운 점까지
     짝지어 회귀·R²에 넣었다. 이제 그 점은 빠지고 상태줄에 `N X times left unpaired (Y gap > … min)`.
  2. Result Lab 데이터 계산기도 같은 함수 — 결손 구간 결과가 NaN이 되고 메시지에 개수를 적는다.
- **Join(⋈) 데이터셋**: 데이터셋 우클릭 → *Join with another dataset…* (상대·접미사·방법·max gap
  auto/분, 미리보기 `N of M base rows get a value · K left empty`). 시간축 = base(데이터셋 시프트 반영),
  base 열은 그대로, 상대 열은 `열+접미사`(기본 `_B`). 범주형 열은 base 것만(Status를 보간할 수는 없다).
- 재료는 **보이는 그대로** 들어간다(재료의 시프트·숨김 규칙·파생 열). 재료가 바뀌면 `_refresh_tree()`
  한 곳에서 다시 만든다 — 선반이 바뀌는 모든 경로가 거기를 지난다. 재료 숨김 행은 '없는 점'이라
  양옆 간격이 max_gap 안이면 보간된다(점 하나 거른 자리를 이웃이 메우는 것은 정렬이지 날조가 아님).
- 저장: `{"join": {...}, "rules", "derived"}` — 열 때 파일 데이터셋을 먼저 다 열고 Join을 만든다.
  재료가 없으면 **열을 비우고** `⋈ ✗ source dataset missing` — 묵은 값을 남기지 않는다.

### 그래프 트랙 (09-21 문서 이어서)

- **M-P** Preview 모덜리스 + 자동 갱신 — **완료(2026-10-01, 검증 40번)**
  - `gui/ui_plot_maker/preview_window.py`. Preview 버튼 = 싱글턴 창(이미 열려 있으면 앞으로 + 즉시 갱신).
  - 갱신 규칙: 화면을 바꾸는 경로마다 훅을 거는 대신 500 ms마다 `preview_signature()`(설정 저장과
    같은 `config_dict()` + 모드 색·범례 크기)를 보고 **바뀐 뒤 한 박자 동안 그대로면** 다시 그린다.
    타이핑 중엔 안 그리고, 무변화면 안 그리고, 빠뜨리는 경로가 없다. `Auto-refresh` 체크로 끌 수 있다.
  - 그리는 함수는 Publish와 같은 `_build_publish_fig` → 미리보기 = 저장 파일. 렌더 오류는 팝업이 아니라
    창 상단 줄에(자동 갱신 중 메시지박스 폭탄 금지).
  - 덤: `_save_cfg`의 dict 조립을 `config_dict()`로 뽑았다(지문과 저장이 같은 출처).
- **M1** `render_mpl(fig)` → `render_mpl(fig, ax)` — **완료(2026-10-01, 검증 41번)**
  - 6개 모드 `render_mpl(fig, ax=None)`. ax=None이면 예전 그대로(그림 전체), ax가 오면 그 패널 안에만.
    베이스 `PlotMode._target_ax`·`_fmt_xdate`를 쓰고 모드는 그림 전체 호출을 직접 하지 않는다.
  - **함정 하나**: `fig.autofmt_xdate()`는 "맨 아래 행이 아닌 축"의 x 라벨을 **그림 전체에서** 숨긴다 →
    패널 모드에선 그 축만 돌린다(그림을 통째로 가졌을 땐 예전 호출 그대로 — 출력 불변).
  - 분할 시계열은 패널 칸을 `subgridspec`으로 다시 쪼갠다. 컬러바는 이미 `ax=`라 패널 단위.
  - `_apply_axes_mpl(fig, axes=None)` — M2가 패널 축만 넘길 수 있게.
  - **바이트 동일 확인**: 6개 모드 + 분할의 Publish SVG sha1이 M1 전후 7개 모두 같다.
    검증 41번이 옛 동작을 실제로 잡는지도 변형 시험으로 확인했다(autofmt_xdate·add_subplot(111)로
    바꾸면 FAIL, 되돌리면 PASS).
- **M2** Composer (패널 그리드, (a)(b)(c), 공유축, inset) — 결정 (B) — **완료(2026-10-01, 검증 42·43번)**
  - `gui/ui_plot_maker/composer.py` + Plot Maker **Layout 탭**. 화면(pg)은 편집 중인 패널 하나, 조판은
    Preview·Publish(mpl)에서만. 화면 코드(`self.p1` 83곳)는 손대지 않았다.
  - **패널 = 그 패널을 재현하는 설정 조각**(모드·모드 설정·라벨·라벨 스타일·축 상태·주석·리샘플/평활/
    시프트). `Add current plot`이 지금 화면을 찍고, 그릴 때 패널마다 조각을 호스트에 잠시 끼워 넣고
    (축 위젯은 신호를 막고) **같은 함수**로 그린 뒤 되돌린다 — 그리는 로직이 하나라 드리프트가 없다.
    패널 모드는 새 인스턴스(옵션 위젯 신호 차단)라 편집기 모드·화면을 건드리지 않는다.
  - **룩은 그림 전체**: 눈금 크기·방향·길이·격자는 패널 것이 아니라 편집기 현재값을 전 패널에 쓴다
    (패널을 다 만든 뒤 Copernicus 프리셋을 걸어도 전부에 먹게).
  - 편집 연결: 패널 더블클릭(Edit) → 그 조각이 편집기에 실리고, 이후 다른 탭의 변경이 그 패널로
    (`✎`). 그림을 만들 때·다른 패널로 옮길 때 자동 반영.
  - 배치: 행·열, 높이·폭 비율(`2,1`), `Cell / inset…`(위치·span 또는 다른 패널 안 inset, 축 비율 rect),
    `Share x within a column`(같은 열 단일 축 패널끼리 x 범위 합집합 공유, 맨 아래만 눈금),
    `(a)(b)(c)`(왼쪽 제목으로 — constrained layout이 자리를 잡아준다). 설정 파일 `compose`.
  - **구현 중 잡은 것들**
    1. *함정*: 처음엔 `Add current plot` 직후 편집기를 새 패널에 묶었다 → 다음 패널을 만들려고 화면을
       바꾸는 순간 **방금 추가한 패널이 덮어써졌다**. 추가 후엔 안 묶고, 묶는 건 명시적 Edit만.
    2. inset 축은 `fig.axes`가 아니라 꽂힌 축의 `child_axes`에 있다 → 빠뜨리면 축 설정이 안 먹는다.
    3. 실제 렌더로 본 것: `tight_layout`은 inset이 있으면 포기(제목 겹침·아래 공백) → constrained layout.
       칸이 다 차서 늘린 줄의 패널을 inset으로 옮기면 빈 줄이 남았다 → 쓰는 크기로 그리드를 줄인다.
       모드 자동 제목(회귀식 등)은 패널 폭을 넘쳐 옆 글자와 겹친다 → 조판에선 직접 단 제목만.
       inset은 제목·축 라벨·범례를 빼고 눈금 글자를 줄이고 로그 보조 눈금 숫자를 뺀다.
    4. **기존 버그(단일 그림에도 있었다)**: `_apply_axes_mpl`이 R축(twinx)·컬러바에도 `labelleft`/
       `labelbottom`을 켜서, R축 눈금 숫자가 **왼쪽 축 숫자 옆에 겹쳐** 찍히고 히트맵 컬러바 숫자가
       컬러바 왼쪽에 한 벌 더 찍혀 히트맵을 파고들었다. 오른쪽 축엔 오른쪽 눈금만 건다(검증 43번).
       → **출력이 바뀌는 곳**: R축을 쓴 시계열 Publish, 상관 히트맵 Publish(둘 다 버그가 사라지는 쪽).
       나머지 모드는 M1 전 해시와 같다.

### 끼워 넣을 작은 것

- **Result Lab 구간 즉석 피팅**: Range 선택 구간에 평균±σ, OLS·Deming 기울기, r² — Σ Stats 옆.
  - **완료(2026-10-01, 검증 38번)** — 설계에서 바뀐 것: Result Lab 구간은 **시계열**이라 거기서
    의미 있는 건 X·Y 회귀가 아니라 **구간 추세**다. 그래서 둘로 나눴다.
    ① Result Lab Σ Stats에 `trend /h ± SE` 열(직선 추세, ppb/h). SE는 잔차 독립 가정이라
    자기상관이 있으면 과소평가 — 대화상자에 그렇게 적었다.
    ② Plot Maker Scatter에 `Fit: OLS | Deming (λ=1) | Deming (λ from 1σ errors)`.
    두 기기·채널 비교처럼 x에도 오차가 있으면 OLS 기울기가 0쪽으로 감쇠한다(합성 검증: 참 1.5에서
    OLS 1.337, Deming 1.492). λ from 1σ = mean(σy²)/mean(σx²)(fit `_Error` 열; 다른 데이터셋이면
    같은 결손 가드로 정렬). **기본은 OLS이고 제목·범례 문자열도 예전과 같다**(출력 무변경).
- **Copernicus 스타일 프리셋**: 폰트·선 굵기·눈금·1/2컬럼 크기를 묶은 `.pmstyle.json` 하나 기본 동봉.
  - **완료(2026-10-01, 검증 39번)** — 설계에서 바뀐 것: 파일을 동봉하지 않고 이미 있는 **Theme 콤보**에
    `Copernicus (ACP/AMT) — 1 column / 2 columns` 두 항목으로 넣었다(`.pmstyle.json`은 Publish 크기·
    팔레트를 안 담아서 '한 번에'가 안 된다). 적용: Publish 8.3×6.2 cm(3.27×2.45 in)/17 cm @300 dpi
    (autosize 해제), 라벨 8/9 pt, 눈금·범례 7/8 pt, 눈금 안쪽, 격자 끔, 선 1, Okabe-Ito.
  - **규정에서 온 것과 우리가 고른 것을 구분해 둔다**: 폭·벡터+폰트 임베딩(M-F)·한 sans-serif(M-K)는
    Copernicus 저자 규정, 글자 크기·눈금 방향·격자는 우리 출발값(툴팁에도 그렇게 적었다).

### D3. 내장 파이썬 콘솔 (탈출구, 맨 마지막)

- Plot Maker 옆 도킹 패널에 `qtconsole` in-process 커널. 네임스페이스: `shelf`, `ds(name)`,
  `df(name)`(pandas 뷰), `push(df_or_arrays, name)`.
- `push`로 올린 데이터셋/열은 출처 `manual (console)` + 입력 기록을 설정에 남긴다 —
  재현은 못 해도 **무엇을 했는지는** 남는다.
- `qtconsole`은 선택 의존성. 없으면 패널 버튼만 숨긴다. PyInstaller 크기 영향은 그때 실측.

## 4. 순서

1. ~~**D0** 모델·다리~~ — 완료(2026-10-01, 검증 34번)
2. ~~**D1** 파생 열~~ — 완료(2026-10-01, 검증 35번) → ~~**D2** 필터·flag 색~~ — 완료(검증 36번) → ~~**D1+** 정렬·Join~~ — 완료(검증 37번) (+ 구간 피팅은 아직)
3. **M-P** → **M1** → **M2** (+ Copernicus 프리셋)
4. **D3** 콘솔

각 단계 끝에 `pytest` · `python tools/validate_plotmaker.py` · `python tools/validate_pipeline.py --no-data`
· `python tools/ci_import_smoke.py`.

## 5. 범위 경계

- `vigil/`은 건드리지 않는다(병행 세션). `gui/theme.py`는 읽기만.
- Result Lab의 기존 Export/Merge/Stats는 동작을 바꾸지 않는다 — 규칙 번역만 추가.

## 6. 기각

| 항목 | 이유 |
|---|---|
| GUI 프레임워크 교체 | §0. 원인이 프레임워크가 아니다 |
| 메모리 배열을 그대로 넘기는 다리 | 설정 재열기 시 재현 불가(원칙 ④). 레시피로 넘긴다 |
| Result Lab에 표 편집·가공 | 역할 분담. 같은 기능을 두 탭에 복제하게 된다 |
| 진짜 LaTeX(usetex) | TeX 설치 필요·느림·배포판에서 깨짐. mathtext로 실사용 99% |
| pyqtgraph ParameterTree | 스타일 창이 이미 그 역할 |
| PlotPy 엔진 도입 | 세 번째 렌더러 = 패리티 가드 3중화(09-21 §5). ROI·피팅 UI만 참고 |
| 저널별 프리셋 다수(IEEE·Nature…) | 실제 투고처(Copernicus)만. 필요해지면 템플릿 하나 더 |
