# Vigil V3 — 대시보드·운용자 경험 감사 (2026-10-02)

(서브에이전트 보고를 코디네이터가 저장. 증거: `%TEMP%\claude\...\scratchpad\vigil\v3_dashboard\` — harness.py, bench*.py, 시나리오 폴더 normal/hk/conc/backlog/restart/g100/g150a/g150b 별 PNG·result.json·state\. 실제 `run_vigil.main()` 을 offscreen 으로 띄우고 QSettings 는 scratch ini, 폴더 선택만 대본. 재생: 실 raw 2026-06-03-004/005/006(핫, 005 에 ZA+He). raw 재생 데이터 삭제, 남은 프로세스 없음)

## 15줄 요약
1. 실제 run_vigil.main() 으로 실 raw 재생 7개 시나리오, 화면 36장 — 정상·rollover·정지 P0·HK P1·농도 스파이크·백로그·정지/재개·폴더 변경·재시작·1366×768·150 %
2. [치명] 평상시 화면이 늘 주황 P1 — 첫 ZA 직후부터 농도 카드 644473.54 ppb, 1346398.96 ppb, P1 이 끝나지 않음(원인은 monitors 쪽 OD/α). UI 에 "감시기 자체를 믿을 수 없음" 상태가 없어 진짜 HK P1 이 겹쳐도 배지는 P1 ×2 → P1 ×3 뿐. 상시 경보라 운용자가 무시하게 되고 진짜 경보가 묻힘
3. [높음] 배지가 무엇이 문제인지 말하지 않음 — `P0 ×1 — check now (P1 2 · P2 0)`(alert_engine.py:31-39). 측정 정지인지 압력인지는 Alarms 탭·신선도 칸을 읽어야 앎. 3초 판단은 "색이 무엇인가"까지만
4. [높음] 창을 닫으면 감시가 말없이 멈춤 — closeEvent 확인 없음, status.jsonl 에 종료 기록 없음. 재시작 사이 16 s 공백이 status.jsonl 에서 구분 안 됨(실측)
5. [높음] 기본이 '정지 상태로 시작' — Vigil_실행.bat 은 --autostart 를 넘길 방법이 없어 재부팅·실수 재실행이면 회색 '일시정지'로 영원히 감시 안 함, 경보·깜빡임 없음
6. [높음] 빈 폴더·잘못된 폴더는 영원히 회색 'waiting for data'(liveness SKIP, 실측 e09) — 감시하지 않는 상태가 경보로 안 올라감
7. [높음] 1366×768 @150 % 에서 창이 화면보다 넓음 — 최소 폭 논리 1219 px = 실제 1829 px, Stop·폴더 버튼이 화면 밖(g150a). 100 %(1366×768)와 1920×1080 @150 % 는 들어감
8. [중간] HK 그래프 판독 불가 — mbar(~950)와 °C(17–300)를 한 y축에, 임계 점선 ~14개와 범례가 곡선을 덮음
9. [중간] 일시정지 중 신선도가 굳음 — "last row 7 s ago" 흰 글씨 그대로(실제 21 s 경과), 카드·표도 옛 값
10. [중간] 백로그 따라잡는 동안 시각축이 '읽은 시각' — 1시간치 raw 가 26 s 폭으로 접혀 그려지고 신선도 "0 s ago"(정상처럼 보임). 농도 throttle 10 s 도 벽시계 기준이라 1시간 백로그에서 핏 2–3번
11. [중간] 장기 실행 비용 — 추세 deque 가 TREND_MAXLEN=720 으로 차면 매 tick 무조건 setData + antialias·굵은 펜·점선 재그리기, 그래프 갱신만 tick 당 231 ms(합성, R 2×720점 120–200 ms, 칠하기가 원인). 지금 정상 tick p50 17 ms, p95 34 ms, 최대 루프 공백 202–251 ms
12. [중간] 경보표 버그(실측) — 변경 감지 서명이 최근 50건만 봄(dashboard_window.py:423), 51번째 이전 경보가 해소돼도 "ongoing", 탭 개수도 안 바뀜(bench: Alarms (60) 그대로)
13. [중간] 시각대 표기 혼재 — 축·신선도엔 KST/UTC, 표 머리글·Log 줄·status.jsonl(시간대 없는 로컬 시각)엔 없음. 1분 기록 파일 이름은 UTC 날짜라 KST 00–09시가 전날 파일로. 열 구성이 바뀌면 새 파일이라 5분 실행에 .vrec 3개
14. [낮음] ★(대상 기체)와 ⏸ 가 □ 로 깨짐. 램프 카드 `Lamp ch_ans`, 경보 출처 `conc:ch_pns` 처럼 id 사용. 빈 그래프 x축 `00.250` 눈금. rollover 뒤 지난 파일 Lag 가 10분간 빨강
15. 잘 된 점: 정지 P0 는 마지막 행 뒤 11 s(grace 10 s), HK P1 시작·해소 시각 정확, 재시작 커서 이어 읽기, 정지/재개·폴더 변경 흐름 정확, tick 예외 격리·읽기 상한 덕에 백로그 중에도 루프 공백 ≤251 ms

## 1. 상단 배지 · 신선도 (3초 판단)
- 무엇/왜: 종합 등급을 색·모양(●▲◆■○)·글자로(dashboard_window.py:34-48, 385-394), 신선도는 "마지막 행 몇 초 전"(:396-404, 설계 §7-Z)
- 정상(a01): `● OK normal — all 2 OK`, "last row 0 s ago 05:38:13 KST" 명확. 정지(b01): 05:42:16 행 멈춤 → 05:42:27 P0 빨강, 신선도 빨강 "49 s ago" — 색으로 3초 판단 가능. 그러나 배지 글자에 "측정 정지"가 없음. HK P1(c01)도 `P1 ×1 — quality at risk` 뿐, 원인은 카드 테두리나 Alarms 탭 `ANs cavity P=689.50 mbar out of band` 로만
- [높음] 배지에 원인·행동 없음(aggregate() 가 개수만 요약). 야간 비전문가에겐 "P0 = LabVIEW 확인" 같은 행동 문구 필요
- [치명] 농도 P1 상시 → 평상시 배지가 OK 인 적 없음, 진짜 HK P1 이 와도 배지 색 그대로
- [중간] 일시정지 중 신선도 굳음 — tick() 이 정지 중 바로 return(run_vigil.py:347), e05→e06 13 s 동안 "7 s ago" 흰색 고정
- [중간] 백로그 중 arrival_time = 읽은 시각 → 1시간 묵은 행도 "0 s ago"(e03)
- 개선: 배지 문구를 가장 심한 항목 메시지 + 행동 한 줄로(예 `P0 측정 정지 — 49 s 동안 새 행 없음. LabVIEW 수집 확인`). "감시기 결함"(농도 init 실패, 물리적으로 불가능한 자릿수)은 P1 이 아니라 회색 '감시 불능' 칸으로 분리해 종합 배지에서 뺌. 일시정지 중 신선도는 "paused"

## 2. P0 확대 · 창 수명
- P0 전환 시 한 번 QApplication.alert(self)(작업표시줄 깜빡임, :392-393), 소리는 의도적으로 없음(§7-Z)
- [높음](코드) 창 닫으면 감시 종료 — closeEvent 재정의 없음, aboutToQuit 은 커서 flush 뿐(run_vigil.py:371-373, 721). status.jsonl 에 시작/종료 줄 없음 — restart 실측 10:24:54 P1 다음 줄이 10:25:21 SKIP, 중단 구간 기록상 안 보임(vigil.log 에만 "Vigil exited"). Vigil.spec console=True 라 콘솔 X 도 같음
- [중간](코드) P0 확대는 한 번 깜빡임뿐, 창이 활성이면 효과 없고 P0 가 계속돼도 다시 안 알림
- [높음](실측) 기본 정지 상태 시작(run_vigil.py:739-742), Vigil_실행.bat 은 %1 만 넘김 → 무인 재시작은 영원히 정지
- [높음](실측 e09) 빈 폴더·.dat 없는 폴더는 `SKIP waiting for data` 회색 무기한(liveness_monitor.py:31), 폴더 오선택을 알 수 없음
- 개선: 닫기 확인창("감시가 멈춥니다"), 시작·종료(rc 포함)를 status.jsonl kind=lifecycle 로, bat 에 --autostart, 시작/Start 후 N분 동안 행 0개면 P1 "감시 폴더에 raw 없음", P0 지속 시 N분마다 재알림

## 3. 카드 · 그래프
- 카드 HK 6, R 2, Lamp 2, Conc 2 = 12장. HK P1 이면 해당 카드 테두리 주황(c02) — 좋음
- [중간] HK 그래프 단위 혼합 단일 축(dashboard_window.py:542-574), 0–1000 범위에 온도선이 바닥에 눌림, 임계 점선 ~14개·범례 겹침(b01, c02)
- [낮음] ★(:494)·⏸(:342) □ 로 깨짐(폰트 글리프 없음)
- [낮음] 램프 카드 제목 `Lamp ch_ans`(run_vigil.py:426, id), R 카드는 라벨(`R ANs`). 경보 출처도 `conc:ch_pns`, `hk:2026-06-03-006.dat` 처럼 id·파일명
- [낮음] 농도 카드 `.2f` 로 7자리, 카드 순서는 생성 순서라 실행마다 바뀜
- [낮음] 빈 그래프 x축 `00.100 … 00.900`(c02), R 은 교정당 한 점이라 첫 몇 시간 오른쪽 끝에 점 1개
- [낮음] rollover 뒤 지난 파일 Lag 빨강(`262.0`, b01) — 퇴역 600 s(run_vigil.py:57) 동안, 빨강 임계 10.0 하드코딩(:473, grace 와 별개)
- 개선: HK 를 단위별 소그래프 2개 또는 밴드 대비 % 정규화, 임계선은 선택 필드만. 라벨 통일. 지난 파일은 회색 "closed"

## 4. 농도 P1 상시 (UI 가 어떻게 전달하나)
- normal, conc, backlog, g100 모두 첫 ZA 직후부터 conc:ch_ans·conc:ch_pns P1 "ongoing", 값 1e5–4e7 ppb. --gas-spike 300 ppb(d01)는 3.9e7 ppb 로 뛰지만 이미 P1 이라 화면 변화 없음 — 스파이크 경보 시험 불가
- 메시지 `unphysical (too high) 1346399.0>50.0ppb; low fit confidence …; sudden change Δ334643ppb` 가 길어 표에서 잘림(툴팁에만 전체)
- [치명] UI 가 "감시기 고장"과 "대기 오염/품질 위험"을 구분 못 함 → 상시 P1 경보 피로
- [중간] 경보 메시지가 핏마다 바뀌어 경보표 전체(최대 200행)를 10 s 마다 다시 그림, 정지 P0 중엔 liveness 메시지("… 51s ago")가 매초 바뀌어 매초 재그리기(5.8 ms/회, 지금은 감당 가능)
- 개선: 물리 한계를 10³배 넘는 값은 "감시기 설정/계산 오류"로 별도 회색, 카드는 "신뢰 불가"로 흐리게

## 5. 경보 이력 (Alarms 탭)
- HK 시나리오: 압력 05:43:30–05:44:00, 오븐 05:44:05–05:44:20 각각 한 줄 시작·해소 정확, `Alarms (1)` 맞음
- [중간](bench) 서명 `sig = (len, 최근 50건)`(dashboard_window.py:423) 때문에 51번째 이전 경보가 해소돼도 "ongoing", 탭 `Alarms (60)` 그대로
- [중간](코드) HK 출처가 파일별 `hk:<파일명>`(run_vigil.py:502) — 같은 고장도 rollover 마다 새 줄, 옛 줄은 퇴역(10분) 때 '해소'로 찍혀 해소 시각 틀림, 한 파일에서 압력·오븐 동시 이탈이면 한 줄로 msg 덮어씀
- [낮음] 확인(ack)·음소거 없음(설계상), 상시 농도 P1 을 끌 방법 없음
- 개선: 서명을 `(len, open 개수, 마지막 갱신 id)`, HK 출처는 `hk:<profile>:<field>`

## 6. 시각대 표기
- KST/UTC 전환(a07)에서 축 라벨·신선도·파일 표 시각이 함께 바뀜 — 좋음
- [중간] tz 없는 곳: 표 머리글 `Last row`/`Start`/`End`, Log 줄 `[05:38:07]`(전환 전 줄은 옛 tz 로 남아 섞임, :577), status.jsonl `ts`(state_log.py:36), vigil.log asctime
- [중간] 1분 기록 파일 이름이 UTC 날짜(record.py:51) — KST 05:38 실행이 `2026-10-01.vrec` 로
- [중간] 열 구성이 바뀌면 새 파일(record.py:52) — HK만 → R/램프 → 농도로 붙으면서 5분 실행에 `2026-10-01`, `_2`, `_3`(열 2/12/18), 재시작마다 반복
- 개선: 머리글 `(KST)`, jsonl 에 `+09:00`, vrec 날짜는 로컬 기준, 열은 프로파일에서 미리 확정

## 7. 정지/재개 · 폴더 선택 · 재시작 · 백로그
- Stop: 배지 `⏸ Monitoring paused…`(⏸ □), 창 제목 `[paused]`, 버튼 `▶ Start`. Start 직후 정지된 파일이면 바로 P0(e07) 정확. 폴더 변경(e08): 정지 상태로·경보 이력·표·카드 초기화·Log 기록 — 정확. 재시작(f01–f03): 커서에서 이어 읽고 "Catching up… / Caught up — live" 1 tick. 백로그: 100 MB 를 26 s(4 MB/tick), tick 최대 233 ms, 루프 공백 최대 251 ms
- [중간] 재시작하면 R·램프·농도 기준선과 추세 그래프 전부 사라짐, "building baseline 1/3" 3사이클(≈3 h) 동안 R 경보 공백, 화면에 "재시작 — 기준선 재구축 중" 표시 없음, .vrec 에서 추세 복원 안 함
- [중간] 백로그 행을 읽은 시각으로 그림(run_vigil.py:462 `now`) — 1시간치가 26 s 폭에 접힘(e06 05:47:17–05:47:41)

## 8. 창 크기 · 배율
| 조건 | 결과 |
|---|---|
| 1366×768 @100 %(g100) | 들어감, 최소 힌트 1213×354, 카드 2줄 접힘, 그래프 높이 ~230 px |
| 1920×1080 @150 % = 논리 1280×720(g150b) | 들어감 |
| 1366×768 @150 % = 논리 911×512(g150a) | [높음] 논리 1219 = 실제 1829 px 로 강제돼 화면 밖, Stop·폴더 버튼 안 보임, 그래프 ~140 px, 범례가 곡선 가림 |
- 원인: 맨 위 가로 줄(배지, 신선도 190, 버튼 150+110)과 info 줄 최소폭, lbl_folder 가 전체 경로를 elide 없이 표시
- 개선: 경로 elide, 상단을 2줄 FlowLayout, 그래프·탭을 QSplitter

## 9. 성능
| 시나리오 | tick p50 / p95 / max (ms) | 루프 공백 p99 / max (ms) |
|---|---|---|
| normal 306 s | 17.5 / 34.3 / 189 | 31 / 202 |
| hk | 16.7 / 24.1 / 50 | 31 / 63 |
| conc | 18.9 / 48 / 131 | 34 / 152 |
| backlog | 1.8 / 107 / 234 | 35 / 251 |
- [중간](bench, 합성) deque 가 꽉 찼을 때(720) 그래프 갱신만 tick 당 231 ms(conc 2.4, HK 28, R 200). cProfile 99 % 가 PlotCurveItem.paint → drawPath. 원인: antialias=True(gui/theme.py:208), 굵은 펜(1.5–2.5), 점선 기준선, 잡음 곡선, 데이터가 안 바뀌어도 매 tick setData(:498, 531, 559). R 은 교정당 1점이라 30일 뒤 720점, HK 는 2시간 만에 참
- 개선: deque 길이·마지막 시각 같으면 건너뜀, 실시간 곡선은 antialias 끔·width 1, 기준선은 실선 저알파
- 증가 상한: alarms 500(run_vigil.py:53), Log 2000블록, 파일 퇴역 600 s, 카드는 키 수만큼 — 무한 증가 없음

## 10. 패키징 (읽기 전용)
- [낮음] Vigil.spec datas 에 icons/ 없음, EXE icon= 없음 → exe 에선 창·작업표시줄 아이콘 없음(gui/splash.py:124 는 repo icons/vigil.ico 를 찾음)
- [낮음] console=True 라 콘솔 X 로 종료하면 aboutToQuit 없이 끝남(커서 ≤5 s 재독, 무해), QuickEdit 꺼짐
- [낮음] 시작 시 콘솔에 한글 `[channel_map] ⚠ … roi2 vs roi1` 경고 2줄(tools.optimize_params 임포트), 운용자 로그엔 안 남음

## 코드 리뷰
| 위치 | 실패 시나리오 | 근거 |
|---|---|---|
| dashboard_window.py:423 | 최근 50건 밖 경보가 해소돼도 표·탭 "ongoing" 유지 | 실측(bench) |
| dashboard_window.py:389 / alert_engine.py:31-39 | 배지에 원인·행동 없음 | 실측 |
| dashboard_window.py:385-387 + run_vigil.py:347 | 일시정지 중 신선도·카드·Lag 가 굳어 정상처럼 보임 | 실측 e06 |
| dashboard_window.py:473 | Lag 빨강 10.0 하드코딩, grace_sec 와 중복, 지난 파일 10분간 빨강 | 실측 b01 |
| dashboard_window.py:498/531/559 | 변화 없어도 매초 setData + antialias 재그리기, 장기 231 ms/tick | 실측(bench) |
| dashboard_window.py:542-574 | 단위 섞인 단일 축, 범례·임계선 과밀 | 실측 |
| dashboard_window.py:494, 342 | ★·⏸ 글리프 □ | 실측 |
| dashboard_window.py:577 | Log 시각 tz 없음, 전환 전후 섞임 | 코드+실측 |
| dashboard_window.py(전체) | closeEvent 없음 → 확인 없이 감시 종료 | 코드 |
| run_vigil.py:371-373, 721 | 종료가 status.jsonl 에 안 남음 | 실측 restart |
| run_vigil.py:739-742, Vigil_실행.bat | 기본 정지 상태 시작, bat 로 autostart 불가 | 실측 e00 |
| liveness_monitor.py:31 | 행을 한 번도 못 보면 무기한 SKIP, 빈 폴더·오선택 무경보 | 실측 e09 |
| run_vigil.py:502 | HK 출처가 파일 단위 — rollover 마다 경보 재생성, 동시 이상 msg 덮어씀 | 코드+실측 c04 |
| run_vigil.py:462 | 백로그 행에 now 시각 → 추세 왜곡, 농도 throttle 벽시계 | 실측 e06 |
| run_vigil.py:287-300 | `_combine_channels`(218-232)와 같은 로직 복붙 | 코드 |
| run_vigil.py:382 | watcher._profile_cache 사적 멤버 직접 pop | 코드 |
| run_vigil.py:426 | 램프 카드 제목이 id(ch_ans), R 은 라벨 | 실측 |
| run_vigil.py:647-657 | 대시보드 모듈을 비 GUI 스레드에서 import, 예외 무시(실제 임포트 자리가 다시 보고하므로 위험 낮음) | 코드 |
| record.py:51-52 | UTC 날짜 파일명, 열 변경마다 새 파일(5분에 3개) | 실측 |
| state_log.py:36 | ts 에 시간대 오프셋 없음 | 코드 |
| Vigil.spec | icons 미포함, console=True | 코드 |

QTimer 는 단일 GUI 스레드라 tick 이 겹치지 않고, Qt 객체를 다른 스레드에서 만지는 일 없음. except 는 tick 격리(run_vigil.py:351)와 농도 init(:266) — 둘 다 로그·배지로 보고. 조용히 삼키는 곳은 prewarm(:651, 656)뿐.

## 잘 된 점
- 정지 P0 정확: 마지막 행 + 11 s 에 빨간 배지, 빨간 신선도, 창 제목 [P0], 작업표시줄 alert
- HK 밴드 이탈·복귀 시작·해소 시각 정확, 해당 카드 테두리만 색 변경
- 정지/재개, 폴더 변경, 재시작 이어 읽기, 백로그 상한 모두 설계대로, 백로그 중에도 루프 공백 ≤251 ms
- 색 + 모양 + 글자 3중 표기, 밤 테마 대비 좋음, 1366×768 @100 %·1920×1080 @150 % 잘림 없음
- 증가 상한 전부 묶여 있음(경보 500, Log 2000, 파일 퇴역)
- 1분 기록이 가볍고(레코드 16 B + 4 B/열) 잘린 꼬리에 견딤
