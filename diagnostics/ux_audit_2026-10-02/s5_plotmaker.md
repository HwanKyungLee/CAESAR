# 섹터 5 — Plot Maker 심층 감사 (2026-10-02)

(서브에이전트 보고 원문을 코디네이터가 저장. 증거 파일은 같은 폴더의 shots/, out/, log*.json)

## 15줄 요약
1. [치명] Night 음영이 UTC 시계 위에 칠해짐 — fit 산출물(UTC naive)을 로컬로 읽어 +9h 시프트 없으면 KST 04:40–14:30(낮)이 '밤'. tz 표기 전무 (실측, shots/05_err_night.png)
2. [높음] 주석 값을 자리표시자가 권하는 `MM-DD HH:MM`로 넣으면 서기 1년으로 저장 → 이후 Publish·Preview·조판·콘솔 fig() 전부 "[Errno 22] Invalid argument"로 실패, 이 주석은 config에도 저장됨 (widget.py:871 `_parse_annot_x`)
3. [높음] 같은 파서에 연도를 넣으면 9 h 늦은 자리(12:00→21:00)에 그려짐. 축 범위 파서 `_parse_x`는 올바름 — 이중 구현
4. [높음] Batch Publish 파일 덮어쓰기: CH1·CH2 NO2 둘 다 `timeseries_NO2.png` → "2 saved" 표시인데 파일 1개. Diurnal 배치 동일 (widget.py:2803, 2825)
5. [높음] Export CSV가 시간축 다른 시리즈를 `np.interp`로 결손 가드 없이 맞추고 범위 밖을 끝값으로 외삽 — 05-18 CH1 + 05-20 CH2 내보내면 CH2 열 1249행 전부 2.33581. core.align 미사용 (modes.py:891)
6. [높음] 패널이 참조하는 데이터셋을 지우면 (c) 패널이 빈 0–1 축으로 경고 없이 Publish (out/figC_after_remove_ch2.png)
7. [중간] Split into panels: Y-right 범위가 둘째 패널(좌축 시리즈)에 걸려 데이터 잘림, log Y·Y-left는 첫 패널만 (widget.py:1686-1705)
8. [중간] 데이터셋 Undo가 그걸 쓰던 시리즈를 복원 안 함, 상태줄은 "restored"
9. [중간] Theme이 사용자 선 굵기를 덮어씀(5→1) — "개별 지정 보존" 주석과 반대
10. [중간] Diurnal Hour shift와 전역 Time shift 합산(피크 10시→19시), Diurnal은 열 1개만
11. [중간] 파일 쓰기 부작용 2건: By date가 고른 핏 트리 안 `_derived`에 머지 파일을 씀, Publish 대화상자는 열기만 해도 마지막 결과 폴더 아래 `figures`를 makedirs — 운영 트리 오염 경로
12. [중간] 빨간 시프트 각주가 출판 그림에 끌 수 없이 박히고 조판에서 (c) x 라벨과 겹침. SigmaANs CSV는 `time_KST` 열을 못 알아봐 시간축 없이 읽힘. 일별 파일 4개 → 범례 전부 'NO2 (CH1)' 같은 색
13. 발견성: 그림 (a)에 클릭 ~20회 + 입력 2–3곳, 그중 tz 보정 3단계는 사전지식 필요. `+ Left Y` 툴팁 없음, 선택 없이 눌러도 무반응
14. 잘 된 점: 화면=출력 단일 함수, config 왕복 지문 동일, validate_plotmaker 44/44, Type42/SVG 텍스트, Copernicus 프리셋, 조판 (a)(b)(c) 품질, Deming 회귀(0.8168 vs OLS 0.8154), 숨김≠삭제

## 감사 방법
- 대상: `gui/ui_plot_maker/*`, `gui/dlg_date_load.py`(By date)
- 실제 CAESARAnalyzer의 Plot Maker 탭을 하네스로 조작(`pm_audit.py`, `pm_audit2.py`, main 가드 런처 `run_pm_audit*.py`). 대화상자 패치, 저장 경로는 전부 `out/`
- 데이터: `C:\GHL\2026 yeosu\Output\fitting\new\26yeosu\2026-05-18~21` CH1/CH2 fit 결과의 사본(`data/`, `fit_tree/`), `SigmaANs_5min_KST_chfix_20260927.csv` 사본
- validate_plotmaker: 읽기 전용(tempfile)으로 44 PASS / 0 FAIL
- 버튼은 `.click()` 또는 슬롯 호출. 주석 배치는 `QTest.mouseClick`, 곡선 클릭은 `_on_curve_clicked` 슬롯 직접 호출

## 만든 그림 (`out/`)
- (a) 4일 CH1/CH2 NO2: figA_default.png/pdf/svg/eps, figA_copernicus1col.png/pdf, figA_copernicus2col.png — 품질 좋음(Arial, NO₂ 아래첨자, 잘림 없음). 1열 프리셋에서 마커 3px > 선 1px라 구슬 목걸이처럼 보이고, 기울어진 날짜 눈금이 높이의 1/3
- (b) Diurnal: figB_diurnal.png/pdf
- (c) 3패널 조판: figC_layout.png/pdf, figC_inset.png — constrained layout 깔끔, 빨간 시프트 각주가 (c) x 라벨과 겹침

## 1. 상단 바
### Add data
- 무엇인가: 결과 파일을 선반에 올림(창에 드롭도 됨)
- 왜: 데이터셋은 경로가 뿌리, 값은 캐시 (데이터자유도 설계 §2)
- 써본 결과: 일별 8개 0.09 s. fit 파일 숫자 열 6개 + 범주형 Status/Flag/Channel 인식. 4일치 CH1 NO2를 각각 더블클릭 → 시리즈 4개 모두 'NO2 (CH1)', 색 #1460AC (01b_*.png)
- 문제점: [중간] 일별 파일이면 범례로 날짜 구분 불가 — `_auto_name`(core.py:233)이 이름에서 첫 `CH\d+`만 뽑음 (실측). [중간] SigmaANs CSV 시간축 없이 읽힘 — 시간 열 이름을 time/datetime/timestamp/date 정확 일치로만 인정(data.py:346), 문자열 열 cal_state 버려짐 (실측, 22_sigma_csv_shelf.png)
- 개선: 같은 runid 일별 파일 여러 개 고르면 이어붙이기 제안. 시간 열 인식을 `*_KST`/`*_UTC`까지 넓히고 꼬리를 tz로 기억

### By date
- 무엇인가: 고른 기간을 머지한 파일을 `{base}/_derived/…`에 씀
- 써본 결과: 2시리즈×4일 5457행씩, 머지 0.09 s(대화상자 포함 1.0 s). 두 번째 호출은 캐시 재사용하지만 선반에 `#2` 사본 생김
- 문제점: [중간] 운영 핏 폴더를 고르면 그 안에 파일을 씀, 안내 없음(운영 트리에 이미 `_derived` 있음) (코드 + scratch 실측). [낮음] 목록 문자열 "· 4d10-02 04:42" 구분자 누락(dlg_date_load.py:216)
- 개선: 머지 파일을 캠페인 `_export`나 캐시에 쓰거나 최소한 쓰는 위치를 한 줄 알림

### Preview
- 모덜리스, Publish와 같은 `_build_publish_fig`. 제목 변경 ~2 s 내 갱신, 렌더 0.10 s
- [낮음] 렌더 오류 시 "OSError [Errno 22]"만 보이고 어느 주석이 원인인지 안 알려줌

### Console
- 표준 `code` 콘솔, df/push/fig/rerun 제공. df·push(resample 1h) 정상, 선반에 `⌨ console` 생김, 여러 줄·↑↓ 히스토리 정상. `open(...,'w')`로 파일 쓰기 가능(제한 없음)
- [중간] 완전한 파이썬이라는 경고 없음. [중간] 공유받은 config가 "type rerun('X')"를 안내하는데 실행 전 기록을 안 보여줌 — 남이 준 코드를 사람 손으로 실행하게 유도 (코드 추정). [낮음] GUI 스레드라 무한루프면 앱 멈춤
- 개선: rerun이 실행 전 기록 전체 출력 + 확인

### Publish
- 10×5.5 in @300 → 2996×1656 px 0.25 s. PDF 74 kB, SVG 221 kB, EPS 205 kB(EPS 투명도 경고 — 좋음). 1열 Copernicus 요청 3.27 in → 실제 3.30 in(bbox_inches="tight")
- [중간] 빨간 시프트 각주를 끌 수 없어 출판 그림에 박힘, 조판에선 패널 라벨과 겹침 (실측). [중간] 범례 기본 'NO2 (CH1)' — 축 라벨 NO₂ 표기와 섞이고 ANs/PNs가 아닌 CH 번호. [낮음] `_figure_dir`(widget.py:2715)가 대화상자 전에 makedirs → 취소해도 마지막 결과 폴더 아래 `figures` 생김
- 개선: 각주 on/off를 Export 탭에, 끈 경우 메타데이터 기록. 1열 프리셋 마커 축소. makedirs는 저장 확정 후

## 2. Data 탭
### 선반·검색·Remove
- 검색 "NO2" 정상, Remove 후 Ctrl+Z로 8개 복원
- [중간] Undo가 시리즈를 복원 안 함 — 시리즈 4→0, Undo 후에도 0, 상태줄 "8 dataset(s) restored" (실측)
- 개선: undo payload에 지워진 시리즈·모드 선택 포함

### Mode
| 모드 | 실측 |
|---|---|
| Time series | 정상 |
| Scatter | OLS 0.8154, Deming λ=1 0.8170, λ from 1σ(1.17) 0.8168, R² 0.9953, n 5457 |
| Allan | 최적 평균 ~60 s, 최소 0.191 |
| Histogram | μ 2.757, σ 2.292 |
| Heatmap | 처음 열면 이유 없이 "2 columns", Pin selection 후 Compute → 6×6 |
| Diurnal | 열 하나만 |
- [중간] 툴팁 없는 버튼: Compute, + Left Y, + Right Y, Color, Name, − Remove, Add
- [중간] Diurnal Hour shift + 전역 Time shift 합산, 둘 다 +9면 피크 10시→19시 (실측)
- 개선: 시프트 하나로 통일, Diurnal 다중 열

### Resample · Smooth · Time shift
- 행 수: Raw 5457 / 1 min 5398 / 5 min 1120 / 10 min 560 / 30 min 187 / 1 h 94 / Custom 15 min 374, 조작 0.15 s
- [치명] tz 표기 없음, Night를 UTC 시계 위에 칠함, 기본 x 라벨 "Time" (실측, 05_err_night.png, out/p2_night_utc_noshift.png)
- [낮음] 리샘플 시각이 버킷 평균이라 11:45:47처럼 들쭉날쭉
- 개선: 메타/헤더에서 UTC를 읽어 데이터셋별 tz, 표시 tz는 전역 콤보 하나. 최소한 Night on + UTC 데이터 + 시프트 0이면 경고

## 3. Style 탭
### 발견성
- 첫 화면은 빈 0–1 격자뿐, 다음 할 일을 그래프 영역에 안 알려줌. 안내는 Data 탭 라벨 한 줄과 트리 툴팁(더블클릭)뿐
- [중간] `+ Left Y`를 선택 없이 누르면 무반응(modes.py:140). 그림 (a)에 클릭 ~20 + 입력 2–3, tz 보정 3단계는 사전지식 필요
- 개선: 빈 그래프 안내 문구, 트리 우클릭 "Add to Time series", 선택 없으면 상태줄 안내

### Palette · Theme · Colors · Cursor
- Copernicus 테마가 크기·dpi·글자 8/7 pt·눈금 In·격자 off·Okabe-Ito를 한 번에(좋음). Colors는 Time series에서 비활성이고 툴팁이 이유 설명
- [중간] Theme이 사용자 선 굵기를 덮어씀(5→1, widget.py:2470), 주석과 반대. [낮음] Okabe-Ito 1번 색이 검정

### Annotate
- 클릭 배치(vspan 2클릭, text 1클릭)·숨김 체크 정상. 값 `05-20 12:00` → −6.2e10(서기 1년), 이후 모든 Publish 실패. `2026-05-20 12:00` → 21:00 자리
- [높음] `_parse_annot_x`가 `pd.to_datetime().timestamp()` — 연도 없으면 0001년, naive를 UTC로 취급. 깨진 주석이 `.pmcfg.json`에 저장됨 (실측). [낮음] Publish 주석 글자 8 pt 고정
- 개선: `_parse_x` 재사용(한 줄), mpl 경로에서 범위 밖 x는 건너뛰고 해당 주석 지목

### 시리즈 목록
- Name에 mathtext → 범례 아래첨자 정상. Delete 삭제, Ctrl+Z 복원, 곡선 클릭 → Style 창, step/bar/area/marker 렌더 정상
- [낮음] Style 창 제목은 시리즈 하나지만 OK는 선택된 모든 시리즈에 적용

### Night · Error band · Split
- 에러밴드 1σ ~0.03 ppb라 4일 그림에서 사실상 안 보임
- [중간] Split: Y-right 범위가 둘째 패널에, log·Y-left는 첫 패널에만(split_ylims [[0,5],[10,20]], p2_split.png). [낮음] Split 패널 y 라벨이 Legend 탭 라벨 설정 무시

## 4. Axes 탭
- All (whole days), Last N d, 빨간 테두리(조용한 폴백 없음), 비시간 모드 가드, tick/anchor/In/log/숨김이 화면·Publish에 모두 반영
- [낮음] 범위 입력 오류 시 상태줄 메시지 없음. [낮음] All 범위가 안 그린 데이터셋까지 포함

## 5. Legend 탭
- 라벨마다 C(글자색), ↺(크기·색 초기화), Pin(드래그 배치). C·크기 14·Pin이 화면과 Publish에서 같은 위치. 한글+수식 혼합 경고
- ↺가 행마다 같은 글자 4개라 어느 라벨 것인지 구분 어려움(하네스도 엉뚱한 행을 누름)
- [중간] 약어 라벨, 행 잘림. 개선: "Color… / Reset / Drag"로 풀어 쓰거나 행 끝 메뉴 하나

## 6. Export 탭
- Batch Publish [높음]: 위 4번(덮어쓰기 + 거짓 성공). Diurnal 배치가 Time series 탭 시리즈 목록을 쓰는데 Diurnal 화면엔 안 보임
- Quick PNG / Ctrl+C: 2400 px 정상
- Export CSV [높음]: 위 5번. 시프트·리샘플 적용 여부가 CSV에 안 적힘
- Save/Load config: 왕복 지문 동일(10.9 kB). [낮음] 저장 대화상자가 bare 파일명으로 시작 → 프로세스 cwd(보통 저장소 루트)에 저장되기 쉬움
- Save/Load style: [낮음] "look only" 설명과 달리 time_shift·resample 포함 → 다른 그림에 숨어서 전파

## 7. Layout 탭
- 3패널 조판((a) 1×2 span), inset, Edit → write-back, config 왕복 정상, 결과 품질 좋음
- [높음] 데이터셋 지우면 패널이 빈 축으로 경고 없이 Publish. [중간] 패널 설명이 "NO2"뿐이라 CH1/CH2 구분 불가(composer.py:406). [중간] Compose를 켜도 화면 그대로라 안 되는 줄 앎
- 개선: 빈 패널에 "missing: …" + 경고, 패널 설명에 데이터셋 꼬리표

## 8. 단축키
- Ctrl+Z, Delete, Ctrl+C 동작 실측

## 코드 리뷰
| # | 심각도 | 위치 | 실패 시나리오 | 확인 |
|---|---|---|---|---|
| R1 | 높음 | widget.py:871-884 `_parse_annot_x` | 연도 없으면 0001년 → fromtimestamp OSError 22 → 모든 출력 실패. 연도 있으면 UTC 해석 +9h. `_parse_x`와 이중 구현 | 실측 |
| R2 | 높음 | widget.py:2803, 2825 | 파일명 충돌로 덮어쓰기, 성공 목록엔 둘 다 기록 | 실측 |
| R3 | 높음 | modes.py:871-903 `csv_table` | np.interp 외삽·결손 보간으로 1249행 값 날조 | 실측 |
| R4 | 치명 | modes.py:520-536 + data.py | UTC 데이터 위에 Night | 실측 |
| R5 | 중간 | widget.py:1686-1705 | Split이 axes[1:]을 twinx로 가정 | 실측 |
| R6 | 중간 | widget.py:2470-2475 | Theme이 선 굵기 덮어씀, 주석과 반대 | 실측 |
| R7 | 중간 | widget.py:2141 / modes.py:268 | Undo가 시리즈 미복원 | 실측 |
| R8 | 높음 | composer.py:211-244 | 데이터셋 없는 패널을 경고 없이 빈 축 출력 | 실측 |
| R9 | 중간 | widget.py:2715-2730 | 대화상자 전 makedirs, 운영 트리일 수 있음 | 코드 + scratch 실측 |
| R10 | 중간 | dlg_date_load.py:112-118 | 운영 핏 트리 안에 `_derived` 씀 | 코드 + scratch 실측 |
| R11 | 중간 | modes.py:1662 | 시프트 이중 적용 | 실측 |
| R12 | 낮음 | widget.py:1155, 2842, 2875, 2892 | 저장 대화상자가 cwd에서 시작 | 코드(하네스 로그) |
| R13 | 낮음 | widget.py:1088-1109 | style 템플릿에 시프트 포함 | 코드 |
| R14 | 낮음 | dlg_date_load.py:216 | 문자열 구분자 누락 | 실측 |
| R15 | 낮음 | modes.py:140 | 선택 없이 + Left Y 무반응 | 코드 |
| R16 | 낮음 | widget.py:1210 | 커서가 최근접이 아닌 오른쪽 이웃 값 표시 | 코드 추정 |
| R17 | 중간 | console.py:146 / widget.py:3010 | 기록 미리보기 없이 rerun 유도 | 코드 추정 |

스레드·리소스·예외:
- Preview 타이머는 창이 숨으면 바로 반환 — 문제없음
- 주석·콘솔·Preview 창은 싱글턴이라 재오픈 시 시그널 중복 연결 없음
- 조판 패널 옵션 위젯은 deleteLater로 정리
- [낮음, 코드 추정] `_apply_mpl_rc` 전체가 `except: pass`(widget.py:2627) — 실패하면 Type 3 폰트로 조용히 폴백 가능

## 잘 된 점
- 화면 = 출력 원칙이 실제로 지켜짐: ResolvedSeries 단일 경로, Preview·Publish 같은 함수, config 왕복 지문 동일, validate_plotmaker 44/44
- 출판 기본값: Type42 폰트 임베딩, SVG 텍스트 유지, Arial + 한글 글리프 폴백, mathtext 화면·출력 동일, Okabe-Ito, EPS 투명도 경고, 한글+수식 혼합 경고
- Copernicus 테마가 크기·dpi·글자·눈금·팔레트를 한 번에, 조판(constrained layout + (a)(b)(c)) 결과물이 거의 손볼 데 없음
- 데이터 무결성 헌장 존중: 숨김≠삭제, 필터·파생 열은 레시피로 저장, 깨진 식은 빨갛게 남김, 시프트는 그림에 각주로 밝힘
- 조용한 폴백 없음: 잘못된 축 입력은 빨간 테두리, 시간축 아닌 모드에선 날짜 프리셋을 막고 이유 설명
- Deming 회귀로 두 채널 비교에 맞는 통계
- 성능 충분: 조작 0.1–0.3 s, Publish 0.1–0.7 s

## 파일 (SCRATCH\deep\s5_plotmaker\)
- 하네스: pm_audit.py, pm_audit2.py, run_pm_audit.py, run_pm_audit2.py
- 로그: run.log, run2.log, log.json, log2.json, validate_plotmaker.log
- 스크린샷: shots/
- 산출물: out/ — figA_*, figB_*, figC_*, batch_ts/, batch_di/, figA_ts.csv, p2_*.png, p2_csv_mismatch.csv, audit.pmcfg.json, audit.pmstyle.json
- 입력 사본: data/, fit_tree/ (By date 머지 결과 fit_tree/_derived 포함)
