# 섹터 4 — Result Lab 심층 감사 (2026-10-02)

(서브에이전트 보고 원문을 코디네이터가 저장. 증거: 같은 폴더 log.json, run_*.log, shots/, saved/, s4_audit.py + run_s4.py, click_dbg*.py, data/)
pull(dcfb50b) 뒤 data_io 경유 경로(Scan detail·Residual)는 재측정 — 결과 동일. 나머지 타이밍은 46cecef 기준(data_io 무관).
코디네이터 직접 확인: R1(`ui_result_viewer.py:1024` `ev.isAccepted()` return), R2(`:1170` 후보 `stem + ".dat"` = 핏 파일 자신), R5(`:889-897` 주석은 "자동 범위로 되돌린다"인데 복구 코드 없음).

## 15줄 요약
1. [치명] 그래프 점 클릭으로 Scan detail/Residual이 절대 안 열림 — flag 색 ScatterPlotItem이 조밀한 데이터에서 모든 좌클릭을 accept, `_on_lane_click`은 accepted면 return(:1024). 점 위·6–12 px 옆 4/4 재현. `tools/test_result_lanes.py`는 `_show_scan_detail`을 직접 불러 이 경로를 안 탐
2. [높음] 실제 폴더 배치에서 α 찾기 고장 — `_sibling_alpha`가 핏 .dat 자신을 반환 → "row N not in alpha_trace". α를 핏 옆에 두면 행 위치를 α row_idx로 써서 다른 스캔을 조용히 그림. 핏 행의 File 열(`…alpha_trace.dat [0016]`)이 정답 파일·행을 이미 갖고 있는데 안 씀
3. [높음] CSV/α로 바꾼 뒤 Hide QC·K·Gas·Err 조작 → 그 파일을 핏으로 다시 그림: CSV는 미처리 ValueError, α는 2,048 픽셀 '가스' 레인·UI 36 s 정지(:771-775)
4. [높음] 2만 행 넘는 파일을 한 번 보면 x 자동 범위가 영구히 꺼짐(:897, :889 주석과 불일치) — 이후 모든 파일이 묵은 x 창에 그려짐
5. [높음] 핏 결과 PNG 내보내기가 2400×37 빈 띠(숨겨진 `_pw_top`) 저장 + "PNG saved"
6. [높음] Export가 화면과 다른 QC 적용 — 화면 K 문턱은 파일 전체 기준(창 안 6행 숨김), Export는 잘린 행만으로 재계산(28행 NaN). `qc_hidden_mask` 대신 로직 복사
7. [높음] 모든 산출물에 출처 없음 — Export·Merge·Calculator CSV에 exporter git 해시·K·Hide QC·구간·시프트·입력 경로 없음. K=3 재QC 결과 헤더엔 원본 "Auto QC K=8". Calculator CSV는 A/B/C가 뭔지 안 적힘
8. [높음] Concentration Export + 시간 시프트 → UTC 값이 `time_KST` 열 이름 아래로 나감, 첫 시간 열만 이동
9. [높음] NIER 제출 KST CSV가 UTF-8 BOM 때문에 안 열림(utf-8-sig로 해결)
10. [높음] CSV를 보는 중 Σ Stats가 이전 핏 파일 숫자를 보여줌. H2O 통계 전부 0.000(1e-13에 %.3f)
11. [중간] 무결성: K로 거른 Export가 가스 값을 NaN으로 덮고 백업 없음. QC-on 파일 원본은 `_qc_orig`에 Python repr 문자열(`np.float64(...)`)로만 남아 파서가 없어 Hide QC를 꺼도 안 돌아옴
12. [중간] Merge가 CH1+CH2를 경고 없이 합치고 첫 파일 헤더만 유지. Versions는 `_archive`로 밀린 덮어쓴 run을 안 보여줌. Dates는 고른 운영 트리 안에 `_derived` 머지를 묻지 않고 씀
13. [중간] 파일 전환 시 이전 상태 잔존 — 통계줄·플롯 제목·날짜칸·상세 패널. 페이지 높이 4,425 px라 NO2 레인·상세 패널이 첫 화면 밖
14. [중간] Calculator 다단계 불가 — 변수로 핏 표만 허용(자기 출력 CSV·Sigma CSV·KST CSV 거부). 화면의 Hide QC·K·Range 무시
15. 잘 된 점: flag 색 레인이 값 불변(표시 사본만 마스킹), 74,667행 1.3 s, 시프트는 표시 전용이고 원본 시각으로 정확히 역변환, Plot Maker로 레시피 규칙 전달(7,394행 숨김 일치), Calculator 정렬이 결손을 메우지 않음, refit의 "같은 설정 아니면 사유 표시", Dates 캐시 0.01 s

## 범위·방법
- 대상: gui/ui_result_viewer.py, gui/result_viewer_io.py, gui/dlg_calculator.py, gui/dlg_date_load.py, core/result_io.py (+ core/refit.py, core/run_meta.py, core/align.py, core/expr.py)
- 실제 CAESARAnalyzer 창 Result Lab 탭을 하네스로 구동. 파일 대화상자는 사본 경로로, 저장은 saved\로(앱 제안 기본 경로는 log의 `suggested`)
- 데이터(전부 data\ 사본): fitA3 = run2 산물(A3 + meta) / prodA3 = 운영 new/26yeosu 2일 / legacy/cfg10s = 10s 버킷 3일 × ANs/PNs, 8.4k행/일 / sigma = SigmaANs 60s·5min / kst = NIER 제출 CSV / alpha = α trace / big = 54일 병합 51 MB(74,667행)

## 1. Open
### File
- 무엇: 파일을 골라 `detect()`로 종류 판별 후 그림. 왜: "빠르게 보고 손보기"(:1-12), 판별 규칙 result_viewer_io.py:36-76
- 써본 결과:

| 파일 | 판별 | 시간 |
|---|---|---|
| A3 핏 917행 | Fit | 0.17 s |
| 레거시 8,446행 | Fit | 0.17 s |
| Sigma60 74,668행 | Concentration | 0.42 s |
| Sigma5 | Concentration | 0.08 s |
| α | α trace | 0.04 s |
| NIER KST | 실패 | — |

- [높음] NIER 제출 CSV 안 열림("No numeric concentration columns") — BOM: `﻿# …` 줄이 주석이 아니라 헤더가 됨. utf-8-sig면 정상(실측)
- [중간] CSV·α를 열어도 통계줄·날짜칸에 이전 핏 값 잔존(실측, shots/open_sig60.png)
- [중간] 페이지 높이 4,425 px, NO2 레인·상세 패널이 첫 화면 밖(실측, open_legacy_full.png)
- [낮음] File로 열면 왼쪽 목록이 비거나 무관한 내용. 상태 문자열 `(auto-detected)time shift` 구분자 누락
- 개선: utf-8-sig로 읽기, `_reload`에서 상태 초기화, 상세 패널을 레인 옆(가로 분할)

### Type 콤보
- 맞지 않는 종류는 거부, 예외 문자열 그대로 노출
- [중간] 실패해도 위쪽 플롯 제목이 다른 파일 것으로 남음(`clear()`가 제목을 안 지움, 실측). [낮음] CSV에 Fit 강제 시 Versions에 "backfill_meta 실행" 안내

### Folder
- 단계별 ≤0.01 s, .meta.json은 목록에서 숨김
- [중간] 한 번에 한 폴더만 → A3(하루=폴더)에선 여러 날 Merge 불가(실측). [낮음] 하위 폴더마다 glob(**) 8번(코드 추정)

### Dates
- 레거시 3일 × 2시리즈 병합 0.32 s(25,299행), 같은 요청 재실행 0.01 s(캐시), A3 0.03 s
- [중간] 고른 핏 폴더(운영 트리) 안에 `_derived`를 확인 없이 씀(dlg_date_load.py:112-119). [낮음] 목록 줄 `2d10-02 04:40` 공백 누락

## 2. View
- 무엇: 핏 결과 표시만 바꿈(Gas, Hide QC, Err bars, QC K, Time shift). 왜: 헌장 ① — 값은 안 지우고 색으로만(:803-807), K는 `robust_rms_thresholds` 단일 출처, 시프트는 표시 전용
- 써본 결과: 가스 전환 0.02–0.2 s. K 8/3/1 → 숨김 22/221/2,176행. Time shift +9 h → 날짜칸 09:00~08:59. 캐시 원본 불변(사본만 마스킹)
- [높음] 2만 행 넘는 파일 뒤 x 자동 범위 영구 꺼짐 → 이후 파일이 묵은 창에(실측, shots/shift_9.png, 54일 → 1일)
- [높음] Hide QC·K·Gas·Err 조작이 `_fit_cache`만 보고 현재 경로를 핏으로 그림 — CSV ValueError, α 2,048 레인·36 s 정지(실측, leak_qck_alpha.png)
- [중간] QC 적용 파일에서 Hide QC를 꺼도 값이 안 돌아옴 — 원본은 `_qc_orig`에 Python repr로만, 파서 없음
- [중간] Concentration에선 Hide QC·K 무효. qc_flag·g_prime·n_60s가 ppb와 같은 축에
- [중간] Sigma60은 time_UTC를 시간축으로 쓰는데 시간대 표기 없음 → 5min_KST 파일과 9 h 차이가 라벨 없이 섞임
- [중간] H2O 축 라벨 ppb인데 값 4e-13(기존 지적 심화)
- 개선: 그린 뒤 `enableAutoRange(x=True)`, `_current_kind == "fit"`일 때만 재그리기, `_qc_orig`를 JSON으로 저장하고 Hide QC 해제 시 회색 점, CSV의 qc_flag를 flag로 사용

## 3. Analyze
### Calculator
- 무엇: 파일·열을 변수 A~H에 매핑 → `safe_eval` → `align_to`로 시각 맞춤 → CSV 저장
- 써본 결과: A=CH1 NO2, B=CH2 NO2, C=CH1 RMS, 식 `where(C<3e-9,(A-B)/A*100,nan)` → 911/917 유효, 0.002 s(CH1·CH2 시각 격자 동일). cold → CH1 정렬 857/917 유효, 결손 18점은 비워 둠. 금지 식은 전부 명확한 메시지로 거부
- [높음] 저장 CSV에 A/B/C의 파일·열, git 해시, 시간대 없음(원칙 ④, 실측)
- [높음] 변수로 핏 표만 — 자기 출력 CSV·Sigma·KST 거부 → 다단계 계산 불가(실측)
- [중간] 화면의 Hide QC·K·Range 무시하고 원본 전부로 계산. [낮음] 결과 메시지 라벨 잘림

### Σ Stats
- 구간 03~06 h + K=3에서 NO2 n=1052, mean 0.855, 추세 0.29 ± 0.0078 ppb/h, 0.03 s. 마스크가 Plot Maker로 넘긴 규칙과 같음
- [높음] CSV를 보는 중 이전 핏 파일(54일 병합) 통계 표시(실측). [중간] H2O `%.3f` → 0.000. [낮음] σ는 ddof=0인데 표에 표기 없음, 누를 때마다 새 대화상자가 쌓임

### To Plot Maker
- status_qc, rms_k 3, time_range, shift_h=9 전달, 7,394행 숨김 표시 — 설계대로

## 4. Export
### Range
- 표시 12~15 h 입력 → 원본 03~06 h로 정확히 자름. 드래그 핸들 ↔ 입력칸 동기화 정상
- [낮음] `MM-dd HH:mm` 형식이라 연도·초 안 보임

### Export (핏)
- 전체 8,446행, 구간 1,058행 `QC-excluded 28`. 시프트는 굽지 않음(툴팁대로)
- [높음] 화면 K 문턱은 파일 전체 기준(구간 6행), Export는 잘린 행 기준(28행) — 실측 + 오프라인 재계산 2.71e-9 vs 2.52e-9
- [높음] 헤더를 원본에서 복사(`Auto QC K=8`, 원본 Code Version). 실제 쓴 K·Hide QC·구간·시프트·경로·exporter git 해시 없음
- [중간] K로 거른 행 값을 NaN으로 덮어씀(백업 없음). [낮음] A3에선 제안 경로가 날짜 폴더 안 `_derived`라 Dates 위치와 다름

### Export (Concentration CSV)
- [높음] 시프트 −9 h 후에도 열 이름 `time_KST`(값은 UTC, 실측)
- [중간] 시간 열이 둘(UTC/KST)이면 첫 열만 밈(코드). [중간] 핏 Export와 의미 반대(CSV는 시프트를 굽고 구간 무시)

### Merge
- CH1 + CH2 병합 1,834행
- [중간] 채널이 섞여도 경고 없음, 헤더에 첫 파일 설정만(CH2 설정·코드 버전 유실), 파일 이름 `CH1_…merge2`

### PNG
- [높음] 핏 결과에서 2400×37 px 빈 이미지 + "saved"(실측). CSV에선 정상(0.41 s)

## 5. Versions
- 무엇: 같은 날·채널 .meta.json → 버전·runid·저장 시각·RMS 중앙값·설정 diff, 클릭하면 그 버전 열기
- 1 run, 툴팁 diff 정상, 레거시 안내 정상
- [중간] `_archive`로 옮겨진 이전 저장본 안 보임(실측). [낮음] 열 때마다 버전별 .dat 전체 재파싱(코드 추정)

## 6. 그래프 상호작용 (pull 후 재측정)
- 무엇: 점 클릭 → 아래 패널에 행 요약 + α 스펙트럼, .meta.json 설정으로 재핏해 잔차
- 실제 클릭 무반응 — ScatterPlotItem이 accept, 핸들러 return (4/4)
- `_show_scan_detail` 직접 호출 시 0.2 s에 요약, 그러나 "row N not in alpha_trace"(핏 파일을 α로 읽음)
- α를 핏 옆에 두면 j=0에서 α row_idx 0을 그림. 실제 출처는 [0016]이고 α row_idx는 0, 258, 310… → 다른 스캔
- 잔차는 "file not found — roi2/Calib_20260619_Hg…"로 거부
- 파일을 바꿔도 이전 상세 패널 잔존. x 링크 확대는 5개 레인 정상 0.03 s
- 개선: accepted 검사 제거(Monitor 클릭 핸들러엔 없음), File 열을 파싱해 α 파일·행 찾기 + α 루트 지정, 자기 자신은 후보에서 제외

## 7. 큰 파일
- 54일 병합 51 MB(74,667행): 열기 1.33 s(루프 최대 정지 1.04 s), 확대 0.11 s, 가스 전환 0.40 s, Hide QC 0.14 s, Stats 0.04 s. Sigma60 0.48 s
- 문제는 그 뒤 x 범위 고정뿐(§2)

## 코드 리뷰
| # | 심각도 | 위치 | 시나리오 → 결과 | 확인 |
|---|---|---|---|---|
| R1 | 치명 | ui_result_viewer.py:1024 | Scatter가 클릭 accept → `_on_lane_click` return → 상세 패널 영원히 안 뜸, 테스트는 이벤트 경로 우회 | 실측 |
| R2 | 높음 | :1163-1175 | 후보 `stem + ".dat"` = 핏 파일 자신 | 실측 |
| R3 | 높음 | :1078, 1104, result_viewer_io.py:344 | 위치 인덱스를 α row_idx로 → 다른 스캔 | 실측 |
| R4 | 높음 | :771-775 | CSV/α에서 View 조작 → ValueError / 2,048 레인·36 s 정지 | 실측 |
| R5 | 높음 | :890-897 | 자동 범위 미복구(주석과 불일치) | 실측 |
| R6 | 높음 | :1325-1373 vs :777-785 | QC 문턱 모집단이 화면과 다름, 단일 출처 우회 | 실측 |
| R7 | 높음 | :1547-1584 | 숨겨진 플롯 내보내 빈 PNG + 성공 메시지 | 실측 |
| R8 | 높음 | :1491-1545 | 다른 파일의 Stats 표시 | 실측 |
| R9 | 높음 | :1412, result_io.py:289, dlg_calculator.py:313 | 산출물 출처 없음, 낡은 K 헤더 | 실측 |
| R10 | 높음 | :1430-1438 | UTC 값에 KST 라벨, 첫 열만 이동 | 실측/코드 |
| R11 | 높음 | :693, :1430, result_viewer_io.py:83 | BOM 처리 실패 | 실측 |
| R12 | 중간 | :1364-1368 | 파생 파일에서 값을 NaN으로 덮음 | 실측 |
| R13 | 중간 | result_io.py:192 | 첫 파일 주석만 유지 | 실측 |
| R14 | 중간 | :536-546, :1074 | 상태 초기화 누락 | 실측 |
| R15 | 중간 | app_window_results.py:394-405 | `_qc_orig`가 repr로 저장 | 실측 |
| R16 | 중간 | run_meta.py:254 | `_archive` 제외 | 실측 |
| R17 | 낮음 | :1537 | Stats QDialog 누적 | 코드 |
| R18 | 낮음 | :1050, :1177, :75 | 죽은 코드 `_on_lane_points_clicked`, `_show_alpha_popup`, `_load_result_time_gas`, docstring이 현재 동작과 반대 | 코드 |
| R19 | 낮음 | :559, dlg_date_load.py:216 | 문자열 구분자 누락 | 실측 |
| R20 | 낮음 | :1526 | %.3f로 H2O 0 | 실측 |

Result Lab엔 워커 스레드가 없고 모두 GUI 스레드. 레인 재사용 시 신호 중복 연결은 `_lane_*_hooked` 플래그로 막힘.

## 잘 된 점
- 종별 레인 + flag 색, 값 불변(캐시 복사 보호)
- 큰 파일 솎아내기가 flag 비율 보존, 1.3 s에 열림
- 시프트 표시 전용, 원본 시각으로 정확히 되돌려 자름
- Plot Maker로 값이 아닌 레시피 규칙 전달(7,394행 숨김 일치)
- Calculator: eval 없는 화이트리스트, 결손 안 메우는 정렬, 명확한 메시지
- refit의 "그때 설정이 아니면 그리지 않고 사유 표시" 원칙
- Dates 캐시 0.01 s, 원본 무수정
- 파서 성능 작업과 대조 테스트
