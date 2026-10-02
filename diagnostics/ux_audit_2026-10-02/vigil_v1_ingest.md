# Vigil V1 감사 — 유입·liveness·커서·재시작·백로그·자원 (2026-10-02)

(서브에이전트 보고를 코디네이터가 저장. 증거: `%TEMP%\claude\...\scratchpad\vigil\v1_ingest\` — 하니스 vh.py(VigilApp(dashboard=None) 1 s tick, vh_rows.tsv·vh_ticks.jsonl), ana.py(폴더 실물 vs Vigil 행 대조), app.py(실 raw 행 append, --header 로 LabVIEW 헤더 행), 실험 e1–e10. 대용량 .dat 1.1 GB 삭제, 잔여 5.5 MB, 잔여 프로세스 없음)

## 15줄 요약
1. [높음·실측] 감시 폴더 안 raw 아닌 .dat(분석 산출물 등)가 자라는 동안 측정 정지가 P0 로 안 뜸 — raw 10:09:41 정지, P0 는 10:11:01(산출물 쓰기 끝나고 11 s 뒤). latest_arrival 이 라우팅 안 된 행까지 셈(run_vigil.py:492)
2. [높음·실측] DAQ 가 죽은 상태로 Vigil 재시작(또는 빈 폴더에서 시작)하면 계속 SKIP, P0 영영 안 뜸 — 45 tick 전부 SKIP(e5 run4). 재부팅 뒤 LabVIEW 미기동이 정확히 이 경우
3. [높음·실측+코드] cursors.json 은 항목을 안 지우고 5 s 마다 파일 전체 재기록 — 13.6만 파일 트리를 한 번이라도 가리키면 18.9 MB/318 ms 쓰기가 5 s 마다(하루 ≈330 GB, GUI 스레드). raw 만 있는 폴더(1.5천 항목)는 5 ms
4. [중간·실측] cursors.json 손상 시: 텍스트 깨짐·빈 파일이면 로그 한 줄 없이 {} 초기화 후 최근 파일 처음부터 재수집(중복). 비UTF-8 바이트면 VigilApp 생성 중 UnicodeDecodeError 로 기동 실패. JSON 모양이 틀리면 tick 예외나 조용한 무수집
5. [중간·실측] 감시 중 파일 이름을 바꾸면 새 파일로 보고 전부 재수집(60행 중복, 일부는 liveness 도 갱신). 핫·콜드 폴더가 섞이면 같은 파일명 때문에 "같은 스캔 두 번 수집" 거짓 경고
6. [중간·실측] §1.4 이상 신호 중 시각 도약·역행, rollover 지연, 헤더만 있는 파일은 미구현 — +3600 s 도약, −7200 s 역행, skip-rollover 모두 경보·로그 0건. row_time 은 디코딩만 하고 안 씀
7. 정상(실측): 60x 3파일 11,145행, 15x 6파일 22,290행 — 누락 0, 중복 0, rollover 감지 1.6–1.9 s
8. 정지·복구(실측): 마지막 행 뒤 약 10–11 s 에 P0, 행이 다시 오면 다음 tick(≤1 s) OK. 5.5분 정지 뒤 새 파일도 1.6 s
9. 빈 폴더 첫 파일 감지 12–29 s(30 s 전체 나열 주기), 그동안 SKIP
10. 강제종료 재시작(실측): 누락 0, 중복 5행·10행(1–2 s 분량, 커서 저장 주기 5 s 이내), 정상 종료는 중복 0
11. 1시간치(100 MB) 일괄 투입도 25 s 에 따라잡음 — tick 당 148행, tick 중앙값 ≈100 ms·최대 212 ms, RSS +35 MB, 누락 0
12. 자원(26분, 15x, 7 h 분량): RSS ≈170 MB 평평, commit ≈196 MB, CPU 코어 하나의 1.4–1.9 %, tick 중앙값 ≈20 ms, 증가 없음, 상태 폴더 26분에 ≈15 KB
13. 읽기 전용(실측+코드): 감시 폴더 크기·mtime·sha256 스냅샷 실행 전후 동일, Vigil 생성 파일 0개, raw 를 여는 곳은 open(path,"rb") 한 곳(watcher.py:321)
14. [중간·코드] tick 중간 예외면 그 tick 남은 행이 처리 안 되고 사라짐 — 커서는 poll 단계에서 이미 전진. 백로그 행엔 도착 시각이 찍혀 추세·lag 왜곡
15. 단일 출처: 행 파싱은 watcher 자체 구현, bytepack 디코딩은 사본 3개(raw_parser, data_io, core/profile.TimeBytepack). Vigil 쪽은 clock_epoch 보정(KST↔UTC) 없음 — 지금은 row_time 을 안 써서 무영향이지만 지연 감시를 구현하는 순간 함정

## 실험
| 실험 | 내용 | 파일 |
|---|---|---|
| e1 | 빈 폴더에서 시작, 1x 3분 | e1/ |
| e2 | 60x, 핫 05-20-001~003 rollover | e2/ana.txt |
| e3 | 정지 40 s → 복구 → 5.5분 정지 → 새 파일 → 헤더만 있는 파일 | e3/steps.log, e3/ana.txt |
| e4 | cursors.json 11가지 변형 | e4.log, e4/result.json |
| e5 | 쓰는 중 kill -9 두 번 → 재시작, 이어서 DAQ 정지 상태로 재시작 | e5/steps.log, e5/ana.txt |
| e6 | 핫+콜드 혼합, 산출물 .dat, 이름 바꾸기·삭제, 읽기 전용 스냅샷 | e6/steps.log, e6/ana.txt, snapA/B.json |
| e7 | 3600행 일괄 투입 | e7/ana.txt |
| e8 | 26분 15x 자원 측정 | e8/ana.txt |
| e9 | 시각 도약·역행, skip-rollover, 반쪽 마지막 줄 | e9/ana.txt |
| e10 | cursors.json 규모별 저장 비용 | e10_cursor_scale.txt |

## 1. 유입(Watcher)
- 무엇: 1 s 폴링으로 완성된 줄만 읽는 증분 리더(watcher.py), tick 당 4 MB 상한, 시작 시 1 h 넘게 안 바뀐 커서 없는 파일은 건너뜀, 전체 나열 30 s 마다·그 사이엔 활성 파일만 stat
- 왜: 설계문서 §2 원칙 1·2, §7 2026-10-01 PC 다운·응답없음 사고 대응(watcher.py:16-24, 64-83)
- 결과: e2·e8 누락·중복 0, rollover 첫 행 감지 1.6–1.9 s, 반쪽 마지막 줄 미수집(199/200), 빈 폴더 첫 파일 12.2 s(e1)·16.2 s(e2)·26.2 s(e3)·28–29 s(e8·e9)(활성 폴더 없어 30 s 전체 나열 대기), 5.5분 정지 뒤 새 파일 1.6 s(e3, _keep 규칙), 백로그 3600행(104.8 MB) 25 tick·tick 당 148행·91–212 ms·RSS 161→196 MB·누락 0
- [중간·실측] 감시 중 이름 바뀐 파일은 새 경로로 처음부터 재수집(e6 60행 전부 중복) — 커서 키가 경로라서. 날짜별 하위 폴더로 옮기는 운용이면 매번 중복
- [중간·실측] 지워진 파일은 조용히 빠지고 커서 항목은 남음
- [낮음·실측] watcher.py:57 주석 "4 MB ≈ 70–90행"은 실측 148행과 다름(행 ≈28 KB)
- [낮음·코드] open() 이 FILE_SHARE_DELETE 없이 열어 Vigil 이 읽는 수 ms 동안 LabVIEW·사용자 이름 바꾸기·삭제가 실패할 수 있음(확률 낮음)
- 개선: 활성 폴더 0개일 땐 루트만 매 poll 얕게 나열, 커서에 (크기, 첫 줄 해시) 같은 동일성 키

## 2. Liveness
- 무엇: 마지막 행의 도착 벽시계 시각과 지금의 차이가 grace 10 s 넘으면 P0(liveness_monitor.py:133)
- 결과: 정지 후 P0 까지 10.4–11 s(e3, e7, e9), 재개 시 같은 tick OK(e3 05:41:10.7 재개 → 05:41:11 OK)
- [높음·실측] latest_arrival(events) 가 profile_id 없는 행까지 셈(run_vigil.py:492) — e6 raw 10:09:41 정지, alpha/ 아래 4열 .dat 가 2 s 마다 자라는 동안 OK, P0 는 10:11:01. 헤더 행 하나만 있는 파일도 liveness 갱신(e3 P0 ≈4 s 지연). 감시 폴더 아래 Augur 산출물을 쓰는 운용이면 측정 정지가 무기한 가려짐
- [높음·실측] 행을 하나도 못 본 상태(last_arrival=None)는 SKIP("initializing") 시간 제한 없음 — 재시작 + DAQ 정지(e5 run4) 45 s 내내 SKIP, 빈 폴더 시작도 무기한. 재부팅 뒤 Vigil 만 자동 시작·LabVIEW 미기동이라는 가장 흔한 무인 사고에서 경보 없음
- [중간·실측] §1.4 "rollover 지연", "헤더만 있는 파일", "시각 역행·도약", "bytepack vs 벽시계 지연" 미구현 — e9 +3600 s 도약·−7200 s 역행·skip-rollover 모두 경보·로그 0. 헤더만 있는 파일도 별도 메시지 없이 liveness P0 로만. 도약·역행은 오경보 위험이 있으니 P2 가 맞다고 판단
- [낮음·코드] 판정을 단조 시계가 아닌 datetime.now() 로 — NTP 가 시계를 앞으로 당기면 순간 P0, 뒤로 돌리면 그만큼 가려짐
- [중간·코드] 백로그 따라잡는 동안 도착 시각이 "지금"이라 liveness OK·대시보드 lag ≈0 s, 행 시각으로는 1 h 묵은 데이터
- 개선: liveness 는 라우팅된 행만으로(한 줄 필터), SKIP 이 grace × N(예 60 s)을 넘으면 P0("raw 가 들어오지 않음"), row_time 과 벽시계 차이로 지연·역행 P2(DataIO.clock_epoch_offset_sec 경유, §6)

## 3. 커서·재시작
- 무엇: 파일 절대경로 → offset 을 JSON 으로 영속, 원자적 교체, 5 s 마다 + 종료 시(ingest_cursor.py, run_vigil.py:58)
- 결과: 정상 재개는 정확(e4 valid_mid). kill -9 두 번(e5) 누락 0·중복 5·10행, 정상 종료 run3→run4 중복 0

| 변형 | 결과 |
|---|---|
| 없음 | 오래된 파일 1개 건너뛰고 최근 파일 101행 전부(설계대로) |
| 깨진 텍스트·잘린 JSON·빈 파일 | 로그 0줄로 {} 초기화, 최근 파일 101행 재수집(중복) |
| 비UTF-8 바이트 | VigilApp() 생성 중 UnicodeDecodeError → 기동 실패(_load 가 JSONDecodeError 만 잡음, ingest_cursor.py:38) |
| JSON 리스트 | 매 tick "tick failed", 행 0, 회복 안 됨 |
| 항목에 offset 없음·문자열 | 첫 poll 예외 → 활성 목록 미생성, 이후 tick 조용히 0행, 30 s 마다 재예외, liveness SKIP 고착 |
| offset > 파일 크기 | 0 으로 되돌려 재수집, 로그 없음 |
| offset 이 줄 중간 | 조각 1행이 미라우팅 행으로 섞임(무해) |

- 저장 규모(e10): 1,500항목 5 ms·0.2 MB, 136,000항목 저장 318 ms·로드 139 ms·18.9 MB
- [높음·코드+실측] 커서 항목이 영원히 안 지워짐(지운 파일, _skip_stale_backlog 가 등록한 파일 전부) — 10-01 사고 폴더(13.6만 .dat)를 한 번만 가리켜도 이후 5 s 주기로 18.9 MB 를 GUI 스레드에서 재기록(318 ms 멈춤, 하루 ≈330 GB 쓰기), 감시 폴더를 좁혀도 남음(set_watch_dir 이 커서 공유)
- [중간·실측] 깨진 커서를 경고 없이 버림 → 최근 1 h 파일 재수집(중복)·이유 모를 동작
- [중간·코드] poll() 이 커서를 전진·저장한 뒤 run_vigil 이 행 처리(watcher.py:349·443, run_vigil.py:458-491) — 처리 중 예외면 그 배치 나머지 행은 다시 안 읽힘, 사라진 행 수는 로그에 없음
- 개선: _load 에서 ValueError·OSError 모두 잡고 깨진 파일은 .bad 로 옮기고 WARNING, 항목 모양 검증(dict, int offset), 존재하지 않거나 감시 폴더 밖 항목은 전체 나열 때 정리·indent 없이 저장, 행 처리 끝난 뒤 커서 확정(최소한 버린 행 수 로그)

## 4. 혼합 폴더·비raw 파일·읽기 전용
- e6: 핫(6181)·콜드(6179) 각각 올바른 프로파일, 4열 alpha .dat 는 미라우팅이지만 매 행 route() 재호출(watcher.py:276 ponytail 주석대로), 2 h 묵은 산출물은 시작 시 "old raw files 1개 건너뜀"(raw 가 아닌데 raw 라고 부름)
- 읽기 전용: Vigil 만 도는 60 s 동안 감시 폴더 모든 파일 (크기, mtime_ns, sha256) 동일(snapA == snapB), 감시 폴더에 Vigil 생성 파일 0, raw 를 여는 곳은 open(path,"rb") 한 곳(watcher.py:321), 나머지 쓰기는 전부 state_dir(cursors, status.jsonl, records, vigil.log, crash log)
- [중간·실측] 핫/ 과 콜드/ 의 같은 파일명(2026-06-01-001.dat)에 "same file name … the same scan is collected twice" WARNING — 정상 구성에서 거짓 경고(watcher.py:353)
- [중간·실측] 비raw .dat 가 liveness 를 가림(§2)
- [낮음·코드] find_flags.py --extract 가 출력 경로가 입력 raw 와 같거나 raw 폴더 안이어도 안 막음(open(out,"w"), find_flags.py:74), int(parts[flag_col]) 은 "1.0" flag 를 조용히 건너뜀(:51) — watcher 는 int(float())
- 개선: 중복 경고는 크기·첫 줄이 같을 때만, 미라우팅 파일은 N행 연속 실패 시 캐시하고 liveness 에서 제외

## 5. 자원
| 경과(분) | RSS MB | commit MB | CPU % (코어 하나) | tick 중앙값 ms | tick 최대 ms |
|---|---|---|---|---|---|
| 0 | 170 | 197 | 1.9 | 20 | 1506 (첫 농도 모니터 초기화) |
| 5 | 172 | 198 | 1.5 | 23 | 86 |
| 10 | 170 | 196 | 1.5 | 21 | 62 |
| 15 | 169 | 196 | 1.4 | 19 | 71 |
| 20 | 170 | 196 | 1.5 | 45 | 112 |
| 25 | 170 | 197 | 1.8 | 22 | 48 |
- 증가 추세 없음, tick 예외 0, 활성 파일 최대 3개, 상태 폴더 26분에 status.jsonl 12 KB(28줄)·records 2 KB·vigil.log 0.8 KB. 1x 정상 운용(e3) CPU 0.3 %, tick 중앙값 0.3 ms. 백로그(e7) tick ≈100 ms(최대 212 ms)·25 s·RSS +35 MB
- [낮음·실측] .vrec 가 한 세션 안에서도 열 구성이 바뀔 때마다 _2, _3 으로 쪼개짐(e8 26분에 3개), 파일명 날짜 UTC(record.py:262)
- [낮음·코드] StateLog.tail() 이 파일 전체 readlines(시작 시 1회라 무해)

## 6. 시각대·row_time·단일 출처
- [중간·코드] row_time 은 core/profile.TimeBytepack.to_datetime 으로 디코딩(naive, 파일명 연도, core/profile.py:81-86), 지금은 안 쓰임
- 이 디코딩은 bytepack 디코딩의 세 번째 사본(raw_parser.py:618, data_io.py:1070 의 & 0xFFFF 와도 다름). clock_epoch_offset_sec(핫 05-18~05-29 09:29 는 KST 기록, 이후 UTC) 보정 없음 — §1.4 지연 감시를 그대로 붙이면 핫 05-29 이후 9 h 지연 P0, 그 전은 0. 연말 파일(12-31 → 1-1)은 cs 리셋으로 1년 역행 디코딩(코드 추정)
- [낮음·코드] 행 파싱 _parse_row(watcher.py:93)는 raw_parser 를 안 쓰는 자체 구현(동작 사실상 같고 비용 이유 납득), 남는 위험은 시각 디코딩
- 제안: RowEvent 에 row_epoch_utc, data_io 보정 함수를 재사용하는 한 함수로 통일

## 7. 기타
- HK 의 status.jsonl 줄에 kind 없음("None", run_vigil.py:472)
- e2·e7·e8 실행 중 농도 모니터 25만–141만 ppb 로 종합 P1 고정(V2 에서 근본원인 확인됨), channel_map 경고("wavecal 폴더 roi2 vs 프로파일 roi1")
- 백로그 행의 HK·R·농도 추세 점에 처리 시각(now)(run_vigil.py:459) — 1 h 백로그가 그래프에서 25 s 로 압축, HK 추세 10 s 벽시계 간격이라 1 h 동안 ≈3점

## 코드 리뷰
| file:line | 실패 시나리오 | 근거 |
|---|---|---|
| run_vigil.py:492 | 미라우팅 행(산출물·헤더·이름 바뀐 파일)이 liveness 갱신 → 측정 정지 P0 가려짐 | 실측 e6·e3 |
| liveness_monitor.py:138 | 행을 한 번도 못 보면 SKIP 무기한 → DAQ 정지 상태 재시작해도 경보 없음 | 실측 e5 |
| ingest_cursor.py:38 | 비UTF-8 이면 기동 실패, 깨진 JSON 은 로그 없이 {} | 실측 e4 |
| ingest_cursor.py:60-61 | 항목 모양 틀리면 KeyError·ValueError → 해당 파일 조용히 안 읽힘 | 실측 e4 |
| ingest_cursor.py:70, watcher.py:298 | 커서 항목 정리 없음, 5 s 마다 전체 재기록(13.6만 항목 318 ms·18.9 MB) | 실측 e10 |
| watcher.py:349 + run_vigil.py:458-491 | 처리 중 예외면 이미 전진한 커서 뒤 남은 행 소실 | 코드 |
| watcher.py:315 / 커서 키=경로 | 이름 바꾼 파일 전부 재수집, 교체됐는데 크기가 같거나 큰 파일은 감지 못 함 | 실측 e6 / 코드 |
| watcher.py:353 | 핫·콜드 같은 파일명에 "같은 스캔 두 번" 거짓 경고 | 실측 e6 |
| watcher.py:421-422, core/profile.py:81 | row_time 미사용, 시각대 보정 없음, 연말 cs 리셋 | 코드 |
| §1.4 미구현 | 도약·역행·rollover 지연·헤더만 있는 파일에 경보 없음 | 실측 e9·e3 |
| liveness_monitor.py:140 | 벽시계 기반이라 NTP 보정에 순간 P0 나 가림 | 코드 |
| find_flags.py:74, :51 | --extract 가 raw 를 덮어쓸 수 있음, "1.0" flag 조용히 건너뜀 | 코드 |
| watcher.py:57 | 주석 70–90행/tick ≠ 실측 148행 | 실측 e7 |

## 잘 된 점
- 행 손실 0: 60x, 15x, 백로그 일괄 투입, kill -9 재시작 모두 누락 없음, 중복도 커서 저장 주기(5 s) 이내
- 메모리 상한이 실제로 작동: 1 h 백로그를 25 s 에 따라잡는 동안 RSS +35 MB 뿐(10-01 사고 땐 파일 크기 × 5배)
- 정상 운용 부담 아주 작음: CPU 0.3–1.9 %, RSS ≈170 MB 평평, 26분 장기 실행 증가 없음
- rollover 와 장기 정지 뒤 재개를 1–2 s 에(_keep 과 폴더 mtime 규칙)
- 완성된 줄만 소비, 읽기 전용 보장 실측 확인(해시·mtime 동일, 감시 폴더 생성 파일 0)
- tick 예외 격리, 원자적 커서 저장, 백로그 건너뜀을 로그로 남기는 설계("조용히 버리지 않는다")
