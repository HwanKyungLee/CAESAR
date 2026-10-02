# Vigil V2 감사 — 모니터 4종 · 경보 엔진 · 프로파일 (2026-10-02)

(서브에이전트 보고를 코디네이터가 저장. 증거: `%TEMP%\claude\...\scratchpad\vigil\v2_monitors\` — conc_rootcause.*, drive.py, setA–D_*, flap.*, unk*.*, live_*, order_check.*, r_pairing.*, profile_tests*.log. 재생 데이터 원본 RAW\hot\05\2026-05-20-001…018 읽기 전용, 저장소 무수정)
코디네이터 확인: 09-23 수정본은 워크트리 `vigorous-lederberg-8c5f2a` 에 미커밋(10파일, `oculus/` 경로) — `git status` 로 확인. 메모리 정정함.

## 15줄 요약
1. [치명] 농도 엉터리의 원인은 단위 오류 하나 — `conc_monitor.py:354-355` 가 광학밀도 −ln(I/I0) 를 α[cm⁻¹] 자리에. Vigil/Augur = 정확히 L_eff(ANs ≈1.0e6 cm = 10.1 km, PNs ≈1.66e6 cm = 16.6 km) → 2.5–7.5백만 ppb
2. 같은 raw·I0 에 α = omr_d·(I0/I−1)(운영 R_CHx.npz)만 넣으면 ANs 2.3–3.1, PNs 1.3–2.1 ppb — Augur 운영값(ANs 2.6–3.5, PNs 2.1–2.9)과 자릿수 일치
3. 채널·wavecal·핏창·레퍼런스는 원인 아님(실측) — 운영 알파를 Vigil 엔진(roi1)·운영 핏셋(roi2) 양쪽으로 재핏하면 둘 다 운영값과 ±0.01 ppb. `[channel_map]` 경고는 이 경로에서 무해한 소음(창 안 wavecal 차이 ≤0.029 nm)
4. 이 수정은 2026-09-23 에 만들어졌지만 커밋된 적 없음 — 워크트리에 옛 oculus/ 경로로 미커밋(10파일 +490/−53, core.physics.bbceas_alpha). 메모리는 "수정 완료"로 잘못 적힘. main 회귀 테스트는 I0·exp(−α) 순환 구조라 32/32 PASS 로 이 버그를 통과시킴
5. "ANs 0.0 ppb · rms/sig 2545 %" 정체는 매시 교정 직후 첫 핏 — 퍼지가스 남은 캐비티를 6 s 만에 핏, allow_negative_gas=false 라 0 으로 잘리고 rms/sig 가 rms/0 으로 발산. Augur purge_settle_sec(60 s) 같은 규칙 없음
6. 단위를 고쳐도 핫 프로파일 rms_sig_alarm=0.15 가 분포 한가운데(15–17 %) — 18 h 재생에서 농도 78 % 시간 P1, OK↔P1 354회. 콜드에서 이미 폐기한 지표가 핫에 남음
7. HK 는 주입 즉시(같은 행) 경보·즉시 해제, 압력 689 mbar·오븐 0 °C 는 P1 정상 작동. 단 sentinel 0 은 "결측 P2"가 아니라 "밴드 이탈 P1". hk_monitor.py:172 결측 분기는 실데이터에서 절대 안 걸리는 죽은 코드
8. [높음] tempcell2 가 5월 내내 0(sentinel)인데 PNs 농도·R 기체온도로 0 °C 사용, 밴드 없어 경보 없음, ppb 약 11 % 낮음. core 의 raw_parser.SENTINEL_RAW/_is_sentinel, data_io._get sentinel 처리를 Vigil HK 경로만 안 씀(단일 출처 위반)
9. 램프: ZA ×0.7 → 다음 ZA 블록 P1(−28 %), 지연 최대 1 h. ×0.15 → ANs P0, PNs P1(−78 %), 다음 블록 즉시 OK. 깨끗한 18 h 오경보 0
10. R: He ×0.9 → 첫 판정 사이클 P1(Δ4.2e-5/3.0e-5), 다음 사이클(3 h 뒤) 해제. He ×0.98 은 Δ≈4e-6 이라 무경보. He 3시간 주기라 기준선 9–12 h
11. [중간] R 이 He 블록을 직전 시간(약 1 h 전) ZA 와 짝지음(실측 순서 512→510→513→500) — R 산포 ×1.4–1.7, 최대 오차 2.15e-6(warn 의 33 %). 직전 ZA 가 어두웠으면 다음 He 에서 "R 산출 실패" P1 이 덩달아
12. [높음] 여러 파일 따라잡을 때 watcher 가 파일을 섞어 넘김 — 기본 4 MB/tick 에서 400 tick 동안 시간 역행 144회, 2개 이상 파일 섞인 tick 145회. R·램프·농도의 "구간 끝" 상태기계가 다른 시간의 행을 섞어 먹음(Stop/Start 재개·커서 있는 재시작 때 실제 발생)
13. 경보 엔진: 미지 열수(6175) 파일은 한 행도 배정 안 되는데 종합 상태 "normal — all 1 OK" — Augur health_checks.overall SKIP=통과 버그와 같은 꼴. liveness 도 배정 안 된 행까지 "살아 있음"으로 셈
14. 프로파일: repo venv 에 jsonschema 미설치 → 스키마 검증이 필수 키 검사로 조용히 폴백, 오타 `alrt` 수용·그 필드 밴드 소실. jsonschema 가 있어도 rel 범위·밴드 순서·roi 역순·채널 id 중복 못 잡음. rel 이 행 범위를 넘으면 매 tick IndexError 로 그 tick 행이 통째로 감시에서 빠짐
15. 라우팅은 열수만 봄(filename_glob *Hot*/*Cold* 는 실제 파일명과 불일치). 핫 행을 6179열로 자르면 콜드로 배정돼 R 0.99988, HK P1 같은 "그럴듯한 엉터리". 6174/6179 콜드 변형은 올바르게 라우팅

## 1. 농도 모니터 (§1.1, M3) — 근본원인
- 무엇: ZA 구간 평균을 I0 로, sampling 행마다(10 s throttle) PO.fit_scan 으로 NO2 핏. FitSet 채널은 wl_dir 로 고름(conc_monitor.py:276-283)
- 왜: 설계문서 §7 M3 "−ln(I/I0) 는 의도적 단순화" — 실제로는 자릿수가 틀림
- 실측(2026-05-20-009.dat, 같은 분 UTC):

| 경로 | ANs (block 2053) | PNs (block 4101) |
|---|---|---|
| V: Vigil 그대로 | 1.9–3.1e6 ppb, rms/sig 18–28 %, 전부 P1 | 2.0–3.2e6 ppb |
| B: 같은 raw·I0, α=omr_d·(I0/I−1) | 2.0–3.1 ppb (L_eff 10.1 km) | 1.2–2.1 ppb (L_eff 16.6–16.8 km) |
| P: Augur 운영 (fitting/new/26yeosu/2026-05-20) | 2.6–3.5 ppb | 2.1–2.9 ppb |
| A1: 운영 알파 + Vigil 엔진(roi1) | P 와 ±0.01 | P 와 ±0.01 |
| A2: 운영 알파 + 운영 핏셋(roi2) | A1 과 동일 | A1 과 동일 |

- V/B ≈ L_eff 정확히 성립 → 원인은 α 단위
- 핏셋: Vigil 은 ANs=roi1(Doasis 판 FitSet_ANs[430-466…]), 운영 09-17 은 ANs=roi2, px 창 599–1270 / 899–1450 동일. A1=A2 이므로 wavecal 선택은 무영향
- B 가 P 보다 낮은 이유(ANs ≈−15 %, PNs ≈−35 %)는 일부만 설명: PNs tempcell2=0 °C(−11 %), P 센서 짝 차이(Vigil p_pns 965 vs 운영 920 mbar). 나머지 후보: I0 보간(최근 ZA 평균 vs PCHIP), Rayleigh 항 생략, 60 s 평균 없음 — 단위 수정 뒤 Augur 대비 재검증 필요
- 첫 핏: 교정 종료 6 s 뒤 → 0.0 ppb, rms/sig 2545–10694 %, 수정판에서도 18 h 동안 매시 반복(setB_fixconc.log)
- [치명](실측) OD 를 α 로 사용, 수정본 미커밋, main 테스트 순환(test_conc_monitor.py:120,151)
- [높음](실측) 퍼지 직후 제외 규칙 없어 매시 P1
- [높음](실측) rms_sig_alarm 0.15(caesar_hot.example.json:92,133)로 수정 후에도 78 % P1·354회. conc_min_ppb −20 은 allow_negative_gas=false 에서 사문. conc_max 50 은 콜드가 이미 100 으로 올림
- [중간](코드) 스파이크 판정이 직전 1점 대비라 noise 에 민감. 깨진 단위에선 P1 아래 가려 50 ppb 주입도 판별 불가
- 개선: vigorous-lederberg 의 bbceas α 수정을 vigil/ 경로로 옮겨 머지, R 없으면 SKIP. purge_settle_sec(60 s) Augur 와 같게. 핫 프로파일에 콜드 처방(rms_sig_alarm 제거, rms_alarm) 후 실측 재설정

## 2. HK 모니터 (§1.3, M1)
- 무엇: 매 행 profile.hk.read() 결과를 밴드와 비교 + 포화(hk_monitor.py)

| 주입 | 결과 |
|---|---|
| 6164=1000@4000:600 (689.5 mbar) | 4001행 P1, 4601행 OK — 지연 0행, 해제 즉시 |
| 6151=0 (오븐 SP sentinel) | P1 "0.00 degC out of band" |
| 6164=0 | P1, He 구간에선 OK(phases), phase None 이면 P1 |
| 깨끗한 18 h | 오경보 0 |
| 밴드 경계 ±0.7 mbar | 1 h 에 OK↔P2 204회, 경보 이력 102줄, status.jsonl 209줄 |

- [높음](실측) sentinel 0 이 결측 처리 안 됨 — 밴드 없는 필드(tempcell2, t_spectrometer)는 0 을 정상값처럼 보여주고 다른 모니터 T 입력으로 흘러감. core/profile.py:271 이 raw_parser._is_sentinel(raw_parser.py:278-309)을 안 씀
- [중간](실측) 히스테리시스·디바운스 없음, 이력 상한 500건(run_vigil.py:53)이라 경계 흔들림 ~5 h 면 진짜 경보 이력이 밀려남
- [낮음](코드) is_saturated 파이썬 루프 2×2048 비교, tick p50 0.9 ms 라 실해 없음
- 개선: HKField.value 가 sentinel 이면 NaN(단일 출처), 결측은 P2. 밴드 판정에 N행 연속 또는 마진 히스테리시스

## 3. 램프 모니터 (M3b)
- 무엇: ZA 블록 채널 평균을 24블록 롤링 중앙값과 비교
- ×0.7(@행 22000): 다음 ZA(06:42)에서 ANs −28.5 %, PNs −27.5 % P1, 이후 유지. ×0.15: ANs "20 % of baseline" P0, PNs −78 % P1, 다음 정상 블록(08:43:59) 즉시 OK. 깨끗한 18 h 오경보 0
- 레벨에 dark(≈868 counts) 포함 → 완전히 꺼지면 ANs ≈6 %, PNs ≈8 % 로 P0 성립, 다만 P0 경계가 채널마다 다름
- [중간](실측) 교차경보: 어두운 ZA 블록이 다음 사이클 R 과 짝지어져 "R 산출 실패 P1"(set D 08:42)
- [낮음] 지연 최대 1 h(ZA 주기, 설계대로) — 대시보드에 "다음 판정 예정 시각" 표시 가치

## 4. R 모니터 (§1.2, M2)
- He 사이클 3시간마다(003·006·009·012·015·018 파일) → 기준선 3개에 약 9 h
- ×0.9: 11:42 P1(ANs Δ4.22e-5, PNs Δ2.98e-5), 14:43 해제. ×0.98: Δ≈4e-6 무경보(warn 6.5e-6/6e-6). 깨끗한 18 h 오경보 0
- [중간](실측) 짝짓기(r_monitor.py:181-196): 원시 순서 He→ZA 라 R 은 항상 1시간 전 ZA 로 계산. 8사이클: Vigil 방식 std 1.55e-6 vs 인접 ZA 1.11e-6(ANs), PNs 5.7e-7 vs 3.3e-7. 램프 1 % 변화면 R 오차 2e-6(warn 의 31–33 %)
- [높음](실측) PNs 기체온도 0 °C(tempcell2 sentinel, 5월) → R 의 Rayleigh 항 틀림
- [중간](코드) 9–12 h 동안 "building baseline OK" — 측정 시작 직후 거울 이상은 반나절 침묵, OK 가 아니라 SKIP/P2 "기준선 없음"이 맞음
- 개선: He 구간 끝나면 다음 ZA 끝까지 기다려 인접 ZA 와 짝짓기(Augur R 교정과 같게), 기준선 축적 중엔 SKIP

## 5. Liveness (§1.4)
- 실시간: 마지막 행 10:14:22 → 10:14:33 P0(grace 10 s + tick 1), 새 파일 첫 행 10:14:47 즉시 OK. rollover 사이 bytepack 1 h 건너뛰었는데 무경보(row_time 미사용, 역행/도약 검사 미구현)
- [높음](실측) 배정 안 된 행도 도착으로 셈(run_vigil.py:482, liveness_monitor.py:127-133) — 미지 열수 파일만 쌓이면 "normal" 지속

## 6. 경보 엔진 — P0/P1/P2 의미
- aggregate(alert_engine.py:22-39)에서 SKIP 은 항상 짐: liveness OK 하나뿐 → ('OK','normal — all 1 OK'), liveness OK + 전 모니터 SKIP → 역시 "normal". Augur health_checks.overall 버그와 같은 구조. 미지 열수 재생(unk.log) 600행 0배정, 종합 OK
- §5 대조: 일치 — HK 밴드 P1, warn P2, 전 채널 포화 P0, R 급락 P1/완만 P2/연속 실패 P0, 램프 꺼짐 P0. 어긋남 — sentinel 0 이 P1(설계는 결측 P2), 농도 3연속 핏 실패를 P0(conc_monitor.py:411-414, §5 P0 는 "측정 자체가 멈춤/무의미"라 과격), FitSet 못 찾는 init 실패가 영구 P1·매 행 재시도(run_vigil.py:263-270, 설정 문제라 P2 가 맞음), 내부 오류도 P1
- 이력 관리(run_vigil.py:387-405): 소스명 hk:<파일> 이 rollover 마다 바뀜, 지난 파일 HK 상태는 10분(벽시계) 종합에 남음(코드 추정), 디바운스 없음
- 개선: "평가된 항목 0개"는 SKIP/P2, "OK k/n, 미평가 m" 표시, 배정 실패 파일 수를 P2 로

## 7. 프로파일 (스키마·변형·라우팅)
- repo venv 에 jsonschema 없음(requirements-lock.txt 엔 4.26.0) → validate_profile_dict(core/profile.py:494-516)가 필수 키 검사로 조용히 대체
- 14가지 변형: 폴백에선 14/14 통과. jsonschema 를 넣어도(스크래치 설치) alrt 오타·grace 0 만 거부, 12/14 통과 — rel 6248 > 행 길이, alarm ⊂ warn 역전, warn [305,295] 역순, roi_nm 역순, 채널 열이 HK 와 겹침·행 밖, 채널 id 중복, flag 500 중복 역할, 없는 HK 키 참조, phases 오타, adc_max −1, warn_drop > alarm_drop
- rel 범위 밖이면 evaluate_hk IndexError(실측), run_vigil.py:458-470 보호 없어 tick 전체 예외 — 커서는 이미 넘어가 그 tick 행은 영구히 감시에서 빠짐(코드 추정)
- 라우팅: 6181→hot, 6179→cold, 6174→cold_6174, 6180·6177(헤더)·6175·7000→None(헤더 None 은 의도). filename_glob 3개 모두 실제 파일명과 불일치(장식). 핫 행을 6179열로 자르면 콜드 배정(unk79.log): HK P1 "Cavity P=0", 이어 2413 mbar, R 0.99988, 농도 inf/0.0. 같은 열수 프로파일 둘이면 알파벳순 첫째가 조용히 이김(core/profile.py:572-598)
- 개선: jsonschema 필수화 또는 없으면 경고, 로더에 의미 검사(rel/columns < n_columns, 밴드·roi 순서, 참조 키, id 중복), 라우팅에 autodetect 신호 블록 대조, 같은 열수 후보 2개 이상이면 경고

## 8. Augur 재사용 맵 (§3)
- 핏: core.param_optimizer.fit_scan(오프라인 옵티마이저 함수, 운영 워커 경로 아님) — A1 이 운영값과 일치하므로 결과 동일
- R: tools.reflectance_calc 를 런타임 의존(tools/ 가 실행 의존성)
- wavecal: tools.optimize_params.load_wavecal → DataIO
- α 식: 단일 출처(bbceas_alpha)가 main 에 없음
- sentinel: core 엔 규칙, Vigil 엔 없음
- 압력 짝: Vigil 프로파일 2053↔p_ans(6164)로 CLAUDE.md 와 일치, 운영 09-19 핏은 옛 짝(920/965 반대)
- [channel_map] 경고는 tools.optimize_params 임포트 때 매 실행 2줄, 영향 없음 — 늑대소년 경고

## 9. 코드 리뷰
| file:line | 실패 시나리오 | 근거 |
|---|---|---|
| vigil/monitors/conc_monitor.py:354-355 | OD 를 α 로 → ×L_eff(1e6) ppb, 상시 P1 | 실측 |
| vigil/monitors/test_conc_monitor.py:120,151 | I0·exp(−α) 순환 테스트가 단위 오류 통과 | 실측(32 PASS) |
| vigil/monitors/conc_monitor.py:339-352 | 퍼지 직후 핏 → 0.0 ppb, rms/sig 발산, 매시 P1 | 실측 |
| vigil/profiles/caesar_hot.example.json:88-94,129-134 | rms_sig 0.15 깜빡임, conc_min 사문 | 실측 |
| core/profile.py:271 / vigil/monitors/hk_monitor.py:172 | sentinel 0 을 실측값으로, 결측 분기 죽은 코드 | 실측 |
| vigil/run_vigil.py:276-277, 205-206 | tempcell2=0 °C 가 PNs 농도·R 에 입력(5월) | 실측 |
| vigil/monitors/r_monitor.py:181-196 | He + 1시간 전 ZA → R 산포 ×1.4–1.7, 램프 블립이 R 실패로 번짐 | 실측 |
| vigil/monitors/r_monitor.py:221-222 | 기준선 축적 9–12 h 동안 "OK" | 코드+실측 |
| vigil/watcher.py:382-410 | 남은 예산(<1행)으로도 다음 파일 1행을 읽어 파일 교차·시간 역행 | 실측 |
| vigil/alert_engine.py:22-39 | 미평가 항목을 "normal"로 숨김 | 실측 |
| vigil/run_vigil.py:482 | 배정 안 된 행도 liveness 갱신 | 실측 |
| vigil/run_vigil.py:458-470 | HK IndexError 로 tick 전체 손실(커서는 이미 전진) | 실측+코드 |
| vigil/run_vigil.py:387-405, 53 | 디바운스 없음, 이력 500건이 깜빡임으로 밀려남 | 실측 |
| vigil/run_vigil.py:263-270 | FitSet 없으면 매 행 재시도 + 영구 P1 | 코드 |
| core/profile.py:494-516 | jsonschema 부재 시 조용한 폴백, 오타 키로 밴드 소실 | 실측 |
| core/profile.py:572-598 | 열수 동률이면 첫 후보, glob 은 실제 이름과 불일치 | 실측 |
| vigil/monitors/conc_monitor.py:411-414 | 핏 3연속 실패를 P0 로 격상(§5 의미 초과) | 코드 |

## 10. 잘 된 점
- HK 밴드 판정 지연 0·해제 즉시, phases 로 교정 구간 오경보 차단. 깨끗한 18 h 동안 HK·램프·R·liveness 오경보 0
- liveness 는 grace 10 s 에 정확히 반응·즉시 해제, tick 예외 격리로 감시기가 죽지 않음
- 램프의 적응 문턱과 P0 블록의 기준선 제외 설계 좋음, ZA/He 누적기(RunningMean)로 메모리 유한
- tick p50 0.8–1.0 ms, 최대 ≈290 ms(핏 포함) — CPU 예산 충분
- 테스트 세트(15/14/12/59 PASS)와 프로파일 계층 구조가 범용 리더 원칙을 잘 따름(농도 테스트는 순환이라 다시 짜야 함)
