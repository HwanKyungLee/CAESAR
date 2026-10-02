# 섹터 3 — Analysis Monitor 심층 감사 (2026-10-02)

(서브에이전트 보고 원문을 코디네이터가 저장. 증거: 같은 폴더 s3_audit.py·run_s3.py, log_p1/p23/p4/p5/p14_post.json, shots/, saved/)
대상: gui/monitor_widget.py, gui/app_window_results.py, gui/app_window_save.py(replay 336–529), gui/pg_perf.py. 정식 Auto-save는 하네스에서 끔.
코디네이터 직접 확인: R1 — `ViewBox.autoRangeEnabled()`가 `[False, False]`를 반환하고 `bool([False, False]) == True` (실측). R3 — app_window_results.py:219의 cap 안내를 :279가 덮어씀(코드).

## 15줄 요약
1. [높음·실측] Step 실시간 런 중 Conc/Trend를 x로 확대해도 1.5 s 안에 원래대로 — `autoRangeEnabled()`가 리스트라 조건이 항상 참(monitor_widget.py:533-538, 700-701). `[0]`만 붙이면 해결
2. [높음·실측] Step 멀티채널에서 비활성 채널을 보면 Components의 가스 곡선을 활성 채널 엔진으로 계산 — NO2 곡선이 맞는 값과 최대 18.8% 다른데 경고 없음. Fit View를 다녀와도 같음(`_on_tab_changed`)
3. [높음·실측] 3일 런 12,528행 중 5,000행만 표에 — "표는 5,000행만 미리보기" 안내가 즉시 "Analysis Completed!"로 덮임(app_window_results.py:219 → 279). 이 실행에선 CH1 05-20·05-21 행이 표에 하나도 없음
4. [높음·실측] 생산 fitset 기본값 QC 꺼짐 — 3일 Conc에서 cold 이상치(±800 ppb)가 y 자동범위를 차지해 사흘이 평평한 선. Unstable·QC 표시가 그래프에 전혀 없음
5. [중간·실측] 표 Status 색은 "OK"·"Recovered"와 정확히 같을 때만 정상 — `OK · AT_BOUND`, `OK · STEP_LIMITED` 등 224행(5.4%)이 Unstable과 같은 빨강. result_io "머리말로 읽는다" 규약과 어긋남
6. [중간·실측] replay 때 Polynomial Baseline 패널이 poly를 두 번 더함(점 = α + baseline) — 폴리선과의 차이가 잔차 σ의 20배. Fit View도 실시간(차분 Meas, 흡수 Fit)과 replay(α 전체, 전체 모델)가 같은 이름 "Intensity"로 다른 양
7. [중간·실측] RUN을 다시 해도 Fit View·Components에 이전 런 스캔(`[CH3] ...017_cold`) 잔존 — `_latest_by_channel` 미초기화
8. [중간·실측] Fast(기본) 모드에선 RUN 도중 4개 서브탭과 표가 끝까지 빔. Update/N 무시(`interval=-1`), Show channel 콤보 무동작. 그런데 탭 이름에 "(Fast)"
9. [중간·실측] Trend Δ기준인 "첫 스캔" Shift가 세 채널 모두 초기값 −0.5 → CH1(중앙값 −6.0 px)은 처음부터 −5.5 px 계단. Step Trend는 N스캔마다 한 점, 채널들이 throttle 시각을 공유해 CH1 곡선이 18 s 동안 한 점도 안 그려짐
10. [중간·실측] replay가 채널을 `setCurrentIndex(ch-1)`로 선택 — 콤보가 [CH2, CH3]이면 CH2 replay 막힘. Reapply는 QC 꺼져 있어도 "QC (K=8)" 표시, 멀티채널 표의 "Set as I0"는 조용히 무동작
11. [중간·실측] Conc/Trend 점 클릭 → replay(0.25 s)는 되지만 표의 해당 행이 선택 안 됨. 가스 그래프끼리·Trend 3개끼리 X축 미연동. 표 행 순서는 실행마다 채널 완료 순서로 바뀜
12. [낮음·실측] 더블클릭 시 replay 2회. 우클릭에 pyqtgraph 기본 메뉴(FFT, Export…) 노출, hover 값 표시 없음. 범례가 데이터를 가림. H2O 축 "ppb"인데 실제 ×1e-12. 빈 Conc 축 눈금 "00.050"
13. 성능(post): 1일 RUN 9.4 s(최대 멈춤 174 ms), 3일 17.0 s(385 ms). 표 클릭 19–86 ms, 5,000행 스크롤 최대 멈춤 13 ms. 갱신 전(8.6 s/18.9 s)과 차이는 잡음 수준
14. 잘 된 점: 클릭 판정이 화면에 그려진 점이 아니라 원본 전체로. replay 엔진이 원본과 다르면 status에 이유, 결과는 파일명+채널로 찾음. 자동 QC는 지우지 않고 표시만(복원 가능). Trend는 매시 퍼지 스파이크 진단에 좋음
15. 코드 리뷰 R1–R17 아래. 죽은 코드: Quick View 위젯, clear_conc, stopped=True 분기, `_fast_pending` 계열, 탭 인덱스 3 경로, 모듈 수준 pg.setConfigOption

## 저장소 갱신 반영
감사 도중 46cecef → dcfb50b(cc9e8c7: data_io 행 캐시 스레드별 LRU-1). 이 섹터 파일은 불변. data_io를 거치는 수치는 갱신 후 재측정(post). Step·STOP·두 번째 RUN·Phase 5는 갱신 전 측정이지만 data_io 속도와 무관.

| 측정 | 갱신 전 | post |
|---|---|---|
| 1일 Fast RUN (4,172) | 8.6 s / 146 ms | 9.4 s / 174 ms |
| 3일 Fast RUN (12,528) | 18.9 s / 328 ms | 17.0 s / 385 ms |
| 표 클릭 → replay | 28–75 ms | 19–86 ms |
| Conc/Trend 점 클릭 | 0.25 s | 0.25 s |

## 1. Show channel 콤보
- 무엇: Components·Fit View에 어느 채널 스캔을 그릴지 고름
- 왜: 채널 스캔이 한 그래프에 섞이지 않게(monitor_widget.py:48-50). 데이터 없는 채널은 콤보에서 뺌(`set_available_channels` 351-370)
- 써본 결과: Conc·Trend엔 영향 없음. Fast 런 뒤엔 콤보를 바꿔도 무동작(`_latest_by_channel` 비어 있음). 표 행 클릭 시 replay가 콤보를 그 채널로 옮김
- [중간] Fast에선 쓸모없는데 활성 상태(실측). [중간] 네 탭 공통 위치라 Conc·Trend도 거르는 것처럼 보임(실측). [중간] `_replay_result`가 `setCurrentIndex(ch-1)`(app_window_save.py:413) — 콤보 [CH2, CH3]에서 CH2 replay하면 CH3 선택 + "stuck on CH3"로 그래프 건너뜀(상태 주입으로 재현)
- 개선: 콤보를 Components/Fit View 탭 안으로, `findData(ch)`로 선택, Fast 런 끝나면 채널마다 마지막 결과 replay로 두 탭 채우기

## 2. Components (Fast)
- 무엇: 가스마다 (잔차 + 그 가스 기여) 점과 기여 선, 아래에 Polynomial Baseline·Residual 패널
- 왜: 곡선을 한 번 만들고 setData 반복(깜빡임 방지, 417-429), 보이는 탭만 그림(406-408), 레이아웃은 가스 이름 튜플로 판정(433-435)
- 써본 결과: Fast 런 도중·직후 빔. Step 런에선 실시간(p2_step_N10_mid_012s_Compon.png). 지금 보이는 스캔 표시 없음
- [높음] Step 런에서 비활성 채널을 보면 활성 엔진으로 계산 — CH1 활성·CH3 보기에서 NO2 기여 최대 18.8% 차(step_engine_check, p2_components_live_CH3.png, 실측)
- [중간] replay는 올바른 엔진을 잠시 끼워 그리지만, Fit View 다녀오면 `_on_tab_changed`가 활성 엔진으로 다시 그림(384-385) — CH2 replay에서 CHOCHO 0.16%, NO2 0.025% 변화(tab_roundtrip, 실측)
- [중간] replay 때 Polynomial 패널이 다른 양: 실시간 점 = 신호 − 에탈론, replay 점 = α + baseline(poly 이중 가산). 점 평균 2.74e-8, 선 평균 −4.7e-9, 차이가 잔차 σ(1.5e-9)의 20배(p1_25_...png, 실측)
- [낮음] 패널에 스캔·채널 식별자 없음
- 개선: 채널별 엔진 캐시 또는 emit에 실어 `update_components`에 넘기기. replay 호출부에서 `raw − (fit − poly)` 형태로. 폴리 패널 점을 신호 − Σ흡수 − 에탈론으로 바꾸면 폴리 적합을 눈으로 판정 가능

## 3. Fit View (Fast)
- 무엇: 위 측정·핏, 아래 잔차(X축 연동)
- 써본 결과: replay 시 제목 "… (Replay)", y 라벨 "Intensity (x1e-09)"
- [중간] 같은 라벨로 다른 양 — 실시간 Meas = 차분(신호 − poly − 에탈론)·Fit = 흡수, replay Meas = α 전체·Fit = 전체 모델. 단위 표기 없음(실측)
- [중간] 두 번째 RUN 뒤에도 이전 런 스캔(`[CH3] 2026-05-20-017_cold…`) 잔존 — RUN 시작 때 `_latest_by_channel`·`latest_fit_data` 미초기화(p3_fitview_after_second_run.png, 실측)
- 개선: RUN 시작 때 두 상태 비우고 곡선 지우기. 라벨을 α(cm⁻¹)/ΔOD로, 실시간과 replay가 같은 양을 그리게 통일

## 4. Conc
- 무엇: 가스마다 3채널 농도 시계열. Show gas, Reset View, Save PNG, 점 클릭 replay
- 왜: 그래프 단위 peak 다운샘플(633-635, pg_perf가 정리한 pyqtgraph 0.14 함정), 클릭 판정은 원본 전체 점
- 써본 결과: 런 도중 빈 축에 "00.050…" 눈금. Show gas 전환 0.3 s, Reset 정확 복원. Save PNG 1241×856 0.5 s + "Saved" 팝업. 점 클릭 replay 0.25 s, 화면은 Components로 넘어가지만 표 행 선택 안 됨(1481 → 1481)
- [높음] 상태 표시 없음, y 자동범위가 이상치에 끌려감 — QC 꺼진 3일 런에서 cold ±800 ppb 때문에 사흘이 평평(p4_conc_all.png, 실측)
- [중간] 그래프 → 표 연결 없음, 5,000행 cap 밖 행은 그래프 클릭으로만 볼 수 있다는 안내 없음(실측)
- [중간] 가스 그래프끼리 X축 미연동(conc_wheel, 실측)
- [낮음] 범례가 데이터를 가림. H2O 라벨 "(ppb) (x1e-12)"인데 실제 단위는 ppb가 아님. x축 "Time"뿐 — 실제 UTC이고, 같은 05-20 로드인데 hot은 05-19 15:41부터, cold는 05-20 00:42부터라 9 h 어긋난 구간(실측)
- 개선: Unstable·QC 플래그 행을 빈 마커로(삭제 아닌 표시), y 자동범위 1–99 백분위, `setXLink`, 점 클릭 시 표 `selectRow`, 축 라벨 "Time (UTC)"

## 5. Trend (Fast)
- 무엇: ΔShift, Squeeze, RMS(log)를 채널별로, 점 클릭 replay
- 왜: 첫 스캔 기준 Δ(506-508), 150 ms 단위로 묶어 다시 그림(515-518)
- 써본 결과: 매시 퍼지 RMS 스파이크와 Squeeze 경계 진동이 잘 보임. 클릭 replay 0.25 s
- [중간] 첫 행 Shift가 세 채널 모두 −0.5(초기값), CH1 중앙값 −6.0~−6.2라 ΔShift가 처음부터 −5.5 px 계단(shift_stats, 실측)
- [중간] Step Trend는 N스캔마다 한 점(108스캔에 11점), 런이 끝나도 `rebuild_trend`는 Fast에서만 호출(실측)
- [중간] throttle 시각을 채널이 공유해 CH1이 18 s 동안 한 점도 안 그려짐(실측)
- [낮음] 세 그래프 X축 미연동
- 개선: Δ 기준을 처음 N개 OK 스캔의 중앙값으로 하거나 절대값 + 경계선, throttle 시각 채널별, Step 런 끝에 `rebuild_trend`, `setXLink`

## 6. 결과 표
- 써본 결과(post): 단일 클릭 19–86 ms(파일 로드 1회), 더블클릭 로드 2회 38–96 ms, 스크롤 최대 멈춤 13 ms(4,172·5,000행), 3일 런 12,528행 중 5,000행만 표에. 행 순서는 채널 묶음 단위로 워커 완료 순서에 따라 실행마다 다름
- [높음] cap 안내 덮어씀(219-222 → 279), 완료 팝업에도 언급 없음(실측)
- [중간] Status 색을 글자 정확 일치로(146-149) — 노트 붙은 OK/Recovered가 빨강(1일 224행, 3일 표 343행). 판정 기준은 `result_io.quality_label`(chi2 ≤ 1.5 → OK, 재시도 후 성공 → Recovered, 그 밖 Unstable)(실측)
- [중간] 행이 시간순 아니고 실행마다 순서 바뀜(실측)
- [중간] 멀티채널 표에서 "Set as I0"가 col 0("CHn")을 읽어 무동작(app_window_inputs.py:531, 실측)
- [낮음] 더블클릭 replay 2회. Status 열 폭 72 px라 노트 잘림
- 개선: Status 머리말(`split(' · ')[0]`)로 색, 노트는 경고색 따로. cap 안내를 완료 문구 뒤에. 표를 (Time, Ch) 정렬. 더블클릭 연결·"Set as I0" 정리

## 7. Reset·마우스·우클릭·hover
- 써본 결과: 휠 확대·드래그 이동 됨. 우클릭에 pyqtgraph 전체 메뉴(View All, X/Y axis, Mouse Mode, Plot Options(Transforms, Downsample, Average, Alpha, Grid, Points), Export…). hover 수신자 0개라 값 툴팁 없음. "A" 버튼 노출
- [높음] 실시간 런 중 x 확대 리셋 — 조건이 `autoRangeEnabled()`(리스트)라 항상 참(533-538, 700-701). 0.3배 확대가 1.5 s 뒤 전체 범위로(실측)
- [낮음] FFT·Export 메뉴 노출, Export는 dlg_dir 규약 밖. hover로 값 확인 불가
- 개선: 조건을 `[0]`으로. `setMenuEnabled(False)` 또는 Export만 남기기. crosshair 같은 값 표시

## 8. RUN 중·후, Update/N, STOP, 두 번째 RUN, 왼쪽 채널 탭
- Fast: 런 동안 4개 탭과 표가 끝까지 빔. Update/N은 Fast에서 무시(app_window_run.py:182-184), Step에선 RUN 시작 때 한 번만 읽음
- Step 렌더 가벼움: N=10이면 24 s에 325스캔(최대 멈춤 124 ms), N=1·지연 0이면 15 s에 1,146스캔(126 ms)
- STOP은 현재 스캔을 마치고 멈춤. 두 번째 RUN에서 Conc/Trend는 정상으로 다시 그려지고 Fit/Components는 이전 런 잔존
- 왼쪽 채널 탭 전환 0.3 s, 결과 유지(의도대로), 단 §2 엔진 불일치가 따라옴
- [중간] 탭 이름 "(Fast)"와 Fast에서 실시간이 없다는 사실이 반대로 읽힘, Update/N도 Fast에서 활성처럼 보임(실측)
- [중간] Fast 런 도중에도 결과는 이미 메모리에(3일 런 9 s 시점 3,900개) 있는데 Conc는 빔(실측)
- 개선: `_flush_fast`에서 2–5 s마다 `rebuild_conc`, 탭 이름에서 "(Fast)" 제거, Fast에선 Update/N 비활성

## 코드 리뷰
| # | 등급 | 위치 | 시나리오 | 확인 |
|---|---|---|---|---|
| R1 | 높음 | monitor_widget.py:533-538, 700-701 | autoRangeEnabled 리스트가 항상 참 → 실시간 런 중 확대 리셋 | 실측 |
| R2 | 높음 | monitor_widget.py:469 + app_window_run.py:412 | 비활성 채널 Components를 활성 엔진으로 계산 → 18.8% 틀린 그림 | 실측 |
| R3 | 높음 | app_window_results.py:219-222 vs 279 | cap 안내 덮어씀 → 7,528행 누락을 숨기고 성공만 표시 | 실측 |
| R4 | 중간 | monitor_widget.py:380-387 | 탭 전환 시 바꿔 끼운 replay 엔진 대신 활성 엔진으로 다시 그림 | 실측 |
| R5 | 중간 | app_window_save.py:464-466 / monitor_widget.py:475 | replay가 α 전체 + poly를 넘김 → poly 이중 가산, 실시간과 의미 다름 | 실측 |
| R6 | 중간 | app_window_save.py:413 | `ch-1` 인덱스 가정 → [2,3] 콤보에서 CH2 replay 실패 | 실측(상태 주입) |
| R7 | 중간 | app_window_results.py:146-149, 482-485 | Status 정확 일치 비교 → 노트 붙은 OK가 실패색, result_io 규약 위반 | 실측 |
| R8 | 중간 | monitor_widget.py:519-523 | throttle 시각 채널 공유 → CH1 18 s 미표시 | 실측 |
| R9 | 중간 | monitor_widget.py:351-370, app_window_run.py:139-150 | RUN 시작 때 스펙트럼 상태 미초기화 → 이전 런 스캔 표시 | 실측 |
| R10 | 중간 | app_window_results.py:314-318 | QC 꺼져 있어도 "QC (K=8)" 표시(chk_qc=False 실측) | 실측 |
| R11 | 중간 | app_window_inputs.py:531 | 멀티채널에서 Set as I0 조용히 무동작 | 실측 |
| R12 | 중간 | monitor_widget.py:497-499, 671-673, 714-716, 748-750 | 채널이 1–3 밖이면 CH1으로 합침 → "+"로 만든 CH4 결과가 CH1 곡선에 섞임 | 코드 추정 |
| R13 | 낮음 | app_window_results.py:395, 418, 453, 154 | QC/Settling NaN 처리·표 열이 활성 채널 가스 이름만 대상 → 채널마다 가스 이름 다르면 값 남고 0.00e+00 표시. 생산 fitset은 이름이 같아 현재 무해 | 코드 추정 |
| R14 | 낮음 | app_window_save.py:480-487 + app_window.py:739-740 | 더블클릭에 replay 2회 | 실측 |
| R15 | 낮음 | 죽은 코드 | Quick View 위젯(200-243), refresh_viewer/roi_selected, on_table_single_click:488(인덱스 3은 이제 Trend, 실측 no-op), clear_conc(호출 없음), analysis_finished stopped=True 분기(시그널에 인자 없음), `_fast_pending/_rows_shown/_cap_noted`(쓰기만) | 실측/코드 |
| R16 | 낮음 | monitor_widget.py:12-13 | 모듈 임포트 때 pg 전역 배경 변경 → 임포트 순서에 따라 결과 다름 | 코드 추정 |
| R17 | 낮음 | app_window_save.py:476-478 | replay 예외를 print·status로만, status는 곧 덮어써짐 | 코드 추정 |

스레드: 워커↔GUI 모두 시그널(큐 연결), 문제 못 찾음. 시그널 중복 연결·자원 누수도 못 찾음.

## 잘 된 점
- 클릭 판정을 원본 전체 점으로(`pg_perf.nearest_index`), 8 px 밖 클릭은 무시(빈 곳 클릭 시 로드 0)
- replay가 파일명+채널로 결과를 찾고 비활성 채널은 일회용 엔진, 엔진이 원본과 다르면 status에 이유(`_diffs`)
- 렌더 효율: Fast는 곡선마다 setData 1회, Step은 20 fps 제한, 3채널 12,528행에서도 최대 멈춤 400 ms 미만, 스크롤 매끄러움
- `set_available_channels`가 "선택했는데 백지" 상태를 원천 차단
- 자동 QC는 지우지 않고 표시만(`_qc_orig`), 문턱은 `robust_rms_thresholds` 한 곳
- Trend의 진단 가치(퍼지 스파이크, Squeeze 경계 진동)
- 채널 탭을 바꿔도 결과 표 유지, 그 사실을 status로 알림
