# 섹터 2 — Setup 탭(우측 본문) 심층 감사 (2026-10-02)

(서브에이전트 보고 원문을 코디네이터가 저장. 증거: 같은 폴더 log.json, log_h.json, shots\*.png, saved\base, saved\mod, s2_audit.py, s2_audit_h.py, wheel_test.py, run_s2.py)
수치는 전부 pull 이후(dcfb50b) 재측정. 운영 데이터는 읽기만, R Calibrator·Alpha Generator는 열기만.

## 코디네이터 검증 메모
- 확인됨: health_checks.overall(:140-151)은 SKIP을 세지 않아 SKIP뿐이어도 "ready to fit — all N passed".
- 확인됨: set_i0_path(app_window_inputs.py:539-554)는 형식 판별 없이 `DataIO.load_measurement` 1D 로더로 읽음.
- 확인됨: app_window_cavity.py:842-853은 파일들을 열 인덱스로 합산하고 파장축은 첫 파일의 것 사용(채널 구분 없음).
- 요약 2번(채널 라벨 하드코딩)은 섹터 1과 같은 지점(app_window_dataload.py:317).

## 15줄 요약
1. [치명] Browse I₀에 raw(Mega-Matrix) 파일을 주면 각 행의 0열(시각 값) 3715개를 I₀로 받음(app_window_inputs.py:548 → data_io.load_measurement). 상태줄 초록 "I₀: loaded (3715 px)", raw RUN에선 이 값이 I₀로 잘려 쓰임. I₀ 로드·초록 표시까지 실측, raw RUN은 안 돌림
2. [높음] 채널 감지 라벨이 정체를 거꾸로 — raw hot 로드 시 "CH1 PNs 180°C + CH2 ANs 300°C"(app_window_dataload.py:317), 알파 로드 시 hot ANs 탭인데 "1 channel (Cold / single-cavity)" (둘 다 실측)
3. [높음] 알파 입력에서 d=30, RL=0.5, ε=0.05, dark×3, ZA flag=999, T/P 폴백을 바꿔도 3채널 농도·T·P 차이 0.0. 그런데 헤더·메타는 바뀐 값을 기록하고 runid도 바뀜 → 헤더가 이 결과가 RL 0.5·stray ON으로 처리됐다고 잘못 말함 (실측)
4. [높음] .meta.json calibration.d_cm/rl_factor가 활성 채널 위젯 값(app_window_channels.py:191-192) → CH2/CH3 메타에도 CH1 값 30/0.5. 09-19 wavecal에서 고친 것과 같은 종류 (실측)
5. [높음] 포커스 없는 d 스핀박스 위에서 휠 한 칸에 51.8 → 50.8 cm, 경고·변경 표시 없음. Setup은 세로 스크롤 페이지라 스크롤하다 물리값이 바뀔 수 있음 (실측)
6. [높음] R npz config에 RL·d 없음. 알파 생성은 npz의 omr_d에 지금 Setup의 RL을 따로 곱해 더함(worker.py:3013) → R Calibrator 이후 RL을 바꾸면 알파가 경고 없이 일관성을 잃음 (코드 추정)
7. [높음] Pipeline Health mean α는 cold·ANs·PNs 알파 73개를 파장이 아니라 열 번호로 더한 혼합(app_window_cavity.py:842-853), 435·450 nm 근처 계단이 그 흔적. 같은 파일의 FWHM 쪽 평균은 보간하는데 여기는 안 함
8. [높음] 아무것도 로드하지 않고 Pipeline Check → 초록 "ready to fit — all 1 passed"(SKIP 4 + Rayleigh 상수 PASS 1, health_checks.overall). 데이터를 로드한 뒤에도 옛 결과가 무효화되지 않음 (실측)
9. [높음] 운영 경로(알파 입력)에선 Audit Day가 항상 "no raw files loaded"로 건너뜀. raw 하루(2.4 GB)를 직접 넣으면 3.5 s에 PASS(ZA 24블록/60분, He 8블록/180분)로 잘 동작. 알파 헤더에 원본 raw 파일명이 있는데 안 씀
10. [높음] Auto I₀는 파일마다 row 0·채널 1만 읽음 → 05-20 hot raw row 0은 flag 1이라 항상 "No ZA-flagged scans". T/P 폴백 칸은 어느 경로에서도 안 쓰임(HK 값이나 data_io 하드코딩 25/1013.25가 덮어씀)
11. [중간] 알파 자동분배 후 Setup Status I₀/R 줄이 Refresh 전까지 미갱신. 빈 상태 Refresh에서 "Fit range px 0–2047"이 초록. 상태줄은 활성 채널 하나만 봄
12. [중간] R(λ) 그래프 제목·좌우 축 라벨·Y 범위가 이전 그림에서 남음 — Browse I₀ 뒤 I₀가 화면 밖, 제목은 다른 _R.dat. Pipeline Health y축 "α (optical depth)"는 틀림(α는 cm⁻¹ 소광계수)
13. [중간] R/Leff Trend 점 색이 시리즈 색이 아니라 채널 구분 불가. valid% 경고 마크가 이모지 제거 후 `"" if … else ""`로 죽음. L_eff 라벨 범위 "600,000 – 400,000" 역순, 상태줄과 다른 수(평균 vs 중앙값)
14. [중간·코드] `_daily_r_pw`/`_daily_rt_pw` 차트 함수는 위젯이 없어 바로 반환하는 죽은 코드인데 R Calibrator 신호가 아직 연결. DayAuditWorker는 closeEvent의 실행 중 목록에 없어 감사 도중 창 닫으면 QThread 파괴 가능(코드 추정). flag 칸 파싱 실패는 조용히 빈 목록. 표시 함수 `_refresh_setup_status`가 txt_max를 몰래 고침. `check_r`은 band와 d=51.8 하드코딩
15. 잘 된 점: day_audit 설계(읽기 전용, 주기를 데이터에서 뽑음, raw_parser 단일 출처, 결과를 meta에 기록). health_checks를 CLI와 공유. Trend 점 클릭 → R(λ)가 실데이터에서 정확. 저장 시 이전 파일을 지우지 않고 _archive로. 고급 섹션을 펼쳐도 우측 진단 패널 폭 거의 그대로(908 → 894 px)

## 범위·방법
- 대상: main_tabs 0번 Setup 페이지 — Setup Status, Tools, α Pipeline, Advanced(Cavity / Manual Override / Detector), Cavity Diagnostics(R(λ) Spectrum · R/Leff Trend · Pipeline Health)
- 코드: gui/app_window.py, app_window_cavity.py, app_window_inputs.py, app_window_run.py·app_window_save.py·app_window_channels.py(물리값이 RUN·헤더·메타로 가는 길), gui/r_workers.py(DayAuditWorker), core/day_audit.py, core/health_checks.py, gui/worker.py
- RUN은 3채널 4172 스캔에 8.9–9.0 s
- 데이터: 운영 fitset, 05-20 알파(CH1 ANs 24 / CH2 PNs 24 / CH3 cold 25, 자동분배), 05-20 hot raw 24개, Output\R의 R_CH1.npz·R_cold.npz·*_R_trend.dat

## 1. Setup Status 블록
- 무엇: 6줄 체크리스트(wavecal / I₀ / R / refs / fit range / day audit) + Refresh Status, Audit Day
- 왜: 위 다섯 줄은 "로드됐나"만, Day audit은 "그날 데이터가 성립하나"(He 결손 → R(t) 외삽, app_window.py:914-917, day_audit.py:1-23). 알파 입력이면 I₀/R을 N/A 회색으로(:970-1013). 감사는 보고만 하고 RUN을 막지 않음(:1116)
- 써본 결과:
  - 빈 상태 Refresh: wavecal 빨강, I₀/R 주황, refs 빨강, Fit range 초록 "px 0–2047"
  - fitset 로드(0.04 s): wavecal 400.04–498.86 nm 초록, refs 초록, range "px 599–1270 (429.5–462.0 nm)"
  - 알파 하루 로드(0.02 s): I₀/R 여전히 주황 "auto from ZA scans during run", Refresh를 눌러야 N/A 회색(C01_after_alpha.png)
  - 알파 상태 Audit Day: 0.01 s, "no raw files loaded"
  - raw 24개(`_update_file_table` 직접 호출, 1.14 s) 후 Audit Day: 백그라운드 3.5 s(디스크 캐시 따뜻했을 수 있음), "Day audit PASS: 1 day(s), 32 ZA/He blocks, no gaps", 툴팁 "ZA 24 blocks every 60 min · He 8 blocks every 180 min"
- [높음] 운영 경로(알파)에선 Audit Day 항상 SKIP — `_raw_days`가 알파를 뺌(app_window.py:1071), 알파 헤더의 원본 raw 이름 미사용 (실측)
- [중간] 자동분배 로드 뒤 I₀/R 줄 미갱신 — `_distribute_channels`(app_window_dataload.py:180-195)가 `_refresh_setup_status`를 안 부름 (실측)
- [중간] 빈 상태에서도 Fit range 초록 (실측)
- [중간] 상태줄은 활성 채널 하나만 보는데 표시 없음(:953, 1016, 1027) (코드 추정)
- [낮음] 감사 시각은 파일 mtime 기준 로컬시각인데 시간대 표기 없음, 핏 출력은 UTC (코드 추정)
- [낮음] 자정~첫 블록, 마지막 블록~자정 결손은 판정 안 함 (코드 추정)
- 개선: 알파 헤더의 raw 이름으로 원본 raw를 찾아 감사하거나 최소한 "raw 폴더 선택" 버튼. `_distribute_channels` 끝에 `_refresh_setup_status()` 한 줄. 상태줄을 채널별로, 최소한 "(active: CH1 ANs)"

## 2. Tools / α Pipeline (진입점만)
- 빈 상태: Wavelength Calibration Tool → WavelengthCalibrationDialog(1.27 s), Reference Generator → ReferenceGeneratorDialog(1.28 s), R Calibrator → RCalibratorDialog(1.30 s), Alpha Generator → 경고 "Load a wavelength calibration… first", Test Fit → 경고 "Lock references first." — 다섯 개 모두 맞는 대화상자이거나 정상 가드
- [낮음] 전제조건이 없을 때 버튼이 비활성으로 안 보이고 눌러야 경고

## 3. Advanced — Cavity Setup
- d: 기본 51.8 cm, 범위 1–1000, 스텝 1.0. raw RUN의 `(1-R)/d`(worker.py:761), Alpha Generator, R Calibrator 초기값, L_eff 표시에 쓰임. R(t) npz를 쓰는 알파 생성에선 α에 안 쓰임(worker.py:3013이 omr_d를 npz에서 읽음). fitset에 채널별 저장
- RL: 기본 1.0. raw RUN·알파 생성의 `rl·alpha_ref` 항에 쓰임, fitset에 채널별 저장
- 값은 채널별 — "per campaign" 라벨과 달리 탭을 바꾸면 스핀 값이 그 채널 config로 바뀜
- [높음] 채널 감지 라벨 정체 거꾸로: raw hot 로드 시 "CH1 PNs 180°C + CH2 ANs 300°C"(app_window_dataload.py:317), CLAUDE.md·data_io.py:772는 CH1 = ANs 300 °C. 알파 로드 시 "1 channel (Cold / single-cavity)" (실측)
- [높음] 휠 한 칸에 d 51.8 → 50.8 cm, 포커스 없어도(WheelFocus) (실측)
- [높음] 알파 입력에선 이 블록 전체가 무효인데 UI·헤더가 그렇게 말하지 않음 — 바꿔도 농도 변화 0, 헤더·메타는 바꾼 값 기록. 실제 물리값은 알파 헤더(RL=1.0, d=51.8)에만 (실측)
- [높음] npz config에 RL·d 없음(실측 키: fit_window_nm, col_press, col_temp, spec_start, spec_end, ts_tz_hours, label, dio_channel). 알파 생성은 지금 Setup RL로 `rl·alpha_ref` 계산, :3011 주석은 두 항이 같은 RL이라고 전제 → R Calibrator 이후 RL 바꾸면 불일치 (코드 추정)
- [중간] 툴팁·힌트가 2025 Araon 수치(CH1 0.933 등), 2026 여수 CH1(ANs)과 다른 셀. 결과 헤더에도 같은 문구 매번(app_window_save.py:210) (실측)
- [중간] L_eff 라벨: 범위 "600,000 – 400,000" 역순(app_window_inputs.py:487-491), 라벨은 평균(514,214 cm)·상태줄은 중앙값(533,275 cm), NaN 처리 없음, 여기는 cm·Trend 탭은 km, RL 미반영 (실측)
- [중간] d를 바꿔도 상태줄 R 줄 Leff는 Refresh 전까지 옛 값 (실측)
- 개선: 채널 라벨은 raw_parser 레이아웃에서, 알파면 헤더 label. 물리 스핀은 StrongFocus + 휠 무시, fitset과 값이 다르면 표시. 알파 입력이면 이 그룹 비활성 + 헤더엔 알파 헤더의 RL·d. npz config에 RL·d 넣고 알파 생성 때 Setup RL과 다르면 경고

## 4. Advanced — Manual Override
- 기본값: ZA 500, He 510, Amb 1, T 25 °C, P 1013.25 mbar, Temporal I₀ off — 어느 것도 fitset에 저장 안 됨
- 써본 결과: Browse R(합성 2열) 정상 "R: 99.9944%". Browse I₀에 raw → 메인 스레드 4.08 s 멈춘 뒤 초록 "I₀: loaded (3715 px, mean=18331.2)", 값은 각 행 0열(시각). T/P 폴백 바꿔도 알파 입력에서 T/P 불변, raw에서도 data_io.py:810-811 하드코딩이 반환돼 안 쓰임. Amb 라벨 "Aml"로 잘리고 입력칸 넘침(A04_setup_expanded_scrolled.png)
- [치명] raw를 I₀로 받음(app_window_inputs.py:548), 테이블 우클릭 "Set as I0"도 같은 경로
- [높음] Auto I₀는 row 0·채널 1만 읽어 항상 "Not Found"(실측: row 0 flag = 1), 메인 스레드
- [높음] T/P 폴백은 죽은 컨트롤, 툴팁 "col 75/76"도 옛 레이아웃
- [중간] flag 파싱 실패 시 조용히 빈 목록(:88-93)
- [중간] Auto I₀는 500이 있으면 500만, 없으면 첫 값만 — 툴팁 "평균" 설명과 다름
- [낮음] Amb 칸 잘림
- 개선: I₀·R을 받을 때 형식 판별(`is_araon_mega_matrix`), Mega-Matrix면 거부하거나 "flag 500 행 평균 + 채널 선택"으로, 길이가 wavecal과 다르면 빨강. Auto I₀는 raw_parser의 ZA 스캔 재사용 + 워커 스레드. T/P 폴백은 없애거나 HK가 NaN일 때 실제로 쓰이게

## 5. Advanced — Detector Corrections
- 기본값: dark/offset 미로드, 스케일 1.0, ε 0.0, fitset 미저장. 그룹 제목에 옛 번호 "3b." 잔존
- 알파 입력에서 ε=0.05, dark ×3으로 바꿔도 농도 변화 0인데 헤더에 "Stray Light Correction: ON (epsilon=0.0500)"
- [높음] 헤더가 실제로 적용 안 된 보정을 ON으로 기록 (실측)
- [중간] .mat dark 로더가 ch1 하드코딩(:56), dark/offset은 채널 구분 없이 모든 채널에 같은 배열 (코드)
- [낮음] 길이가 짧은 dark는 조용히 무시, offset은 같은 경우 경고
- 개선: 알파 입력이면 비활성 + 헤더는 알파 헤더 값, dark/offset을 채널 config로

## 6. Cavity Diagnostics — R(λ) Spectrum
- 채우는 경로: Browse I₀/R, Auto I₀, raw RUN 중 R 갱신, R Calibrator 완료, Trend 점 클릭. 알파 일상 흐름에선 항상 빈 그래프
- 써본 결과: Trend 점 클릭(QTest 실제 뷰포트 클릭, idx 251 = 2026-06-29-005) → R_CH1/…_R.dat 정상 표시, 초록 핏창(F02_after_click.png). 이어서 Browse R/I₀ 하면 그림이 뒤섞임(G02_browseI0.png): 제목 그대로 "2026-06-29-005_R.dat", 좌축 라벨 "Reflectance R"인데 I₀(평균 18331)가 그 축에 들어가 Y 범위 밖, X 축 0–3700인데 라벨 "Wavelength (nm)"
- [중간] 두 그리기 경로가 공유 축의 제목·라벨·범위를 서로 리셋 안 함 → 오래된 제목, 안 보이는 I₀, 빈 우축 "Reflectivity (R)" 0–0.9 눈금 (실측)
- [중간] 길이 다른 배열을 픽셀 인덱스로 그리면서 nm 라벨 (실측)
- [낮음] 제목에 채널 없음, hover 없음
- 개선: 공통 축 리셋 함수 하나 + 제목에 채널, 알파 입력이면 빈 그래프 대신 안내 문구

## 7. R/Leff Trend
- 채우는 경로: R Calibrator data_ready 신호뿐 — 앱을 새로 켜면 항상 빔, 기존 trend 파일 불러오기 버튼 없음. 이 감사에선 운영 trend dat를 load_dat로 읽어 슬롯 직접 호출(0.07 s, 1046 사이클)
- 써본 결과: readout "CH1 R̄=99.995% Leff=12.09km valid=100% n=503", 그린 뒤 탭 자동 전환(F01_trend.png)
- [중간] 점 색이 전부 기본 색이라 채널 구분 불가(app_window.py:1328) (실측)
- [중간] valid% 경고 마크 죽음(:1359) (코드 확정)
- [중간] trend 시각은 KST인데 naive 해석·시간대 표기 없음, UTC 핏 결과와 9 h 어긋나 읽힘 (코드 추정)
- [낮음] 다른 달의 cold 1사이클이 축을 늘림, 그래프 제목 "R Trend Monitor"인데 버튼 이름 "R Calibrator"
- 개선: symbolBrush를 시리즈 색으로, 경고 마크 텍스트로 복원, "Load R trend…" 버튼(읽기 전용), 축에 "(KST)"

## 8. Pipeline Health
- 써본 결과:
  - 빈 상태 Run: 0.01 s, 초록 "ready to fit — all 1 passed", 상태바도 PASS
  - 데이터 로드 뒤에도 readout "Wavecal not loaded … ready to fit" 잔존(C01)
  - 알파 폴더 + R_CH1.npz: 메인 스레드 1.47 s, 주황 "2 warnings · 3 passed" — α 파일 73개/4,172 스캔·이상 1개(…-007_cold: scans=4), wavecal 0.048 nm/px, refs 최대 r=0.73, Rayleigh 9.6997e-27, R(t) "unphysical knots 101/1261"
  - R_cold.npz로 바꾸면 R(t) PASS(1/667)
  - CH2 탭에서 다시 돌리면 refs만 r=0.72로, 어느 채널을 봤는지 표시 없음
  - Fit window 줌(428.9–462.5 nm)은 흡수 구조가 잘 보임(D02)
- [높음] SKIP만 있어도 "ready to fit"(health_checks.py:140-152) (실측, 코디네이터 재확인)
- [높음] mean α가 3채널을 열 번호로 섞은 평균, 첫 파일(cold) 파장축 사용(app_window_cavity.py:842-853), 435·450 nm 근처 계단 (코드 확정 + 그림 실측, 코디네이터 재확인)
- [중간] 로드·채널 전환 뒤에도 결과 미무효화 (실측)
- [중간] wavecal/refs는 활성 채널만 검사, `check_r`은 band (438, 476)·d=51.8 고정인데 ANs 핏창은 429.5–461.9
- [중간] y축 라벨 "α (optical depth)" 틀림(α는 cm⁻¹), "(x1e-06)" 접두까지
- [중간] 메인 스레드 스캔, 한 달이면 약 45 s 추정
- [낮음] 아이콘이 전부 빈 문자열이라 색으로만 구분, 폴더 라벨 잘림·툴팁 없음, 스캔 1행 파일은 무조건 FLAT 판정(:837)
- 개선: "검사한 것이 없음" 상태 별도, 알파를 label별로 나눠 파장 보간 후 채널별 곡선, 로드·채널 전환 시 결과를 stale로 표시, `check_r`에 채널 핏창·d 전달, 스캔을 QThread로

## 9. 물리 안전 UX — 바꾼 값이 결과에 어떻게 나타나나
- 실험: 기준 RUN 저장 후 CH1 활성 상태에서 d 30, RL 0.5, T −40, P 600, ε 0.05, dark ×3, ZA 999, Temporal ON으로 바꿔 다시 RUN·저장
- 결과: 3채널 NO2·T_used·P_used 최대 차이 0.0. .dat 헤더엔 RL 0.5, Stray ON, ZA=999 기록, d 줄은 헤더에 아예 없음. meta는 3채널 모두 d_cm=30, rl=0.5(CH2/CH3 config는 51.8/1.0 그대로). runid 3채널 모두 바뀜
- 결론: 알파 경로에선 농도는 안전하지만 기록이 거짓. raw·알파 생성 경로에선 실제로 값이 바뀌는데 휠 한 칸 변경, fitset에 저장 안 되는 값(flags·dark·ε·T/P), npz와 따로 노는 RL에 대해 경고가 하나도 없음. 기록은 남음(헤더 RL·flags, 알파 헤더 RL·d) — 이 점은 좋음

## 코드 리뷰
- C-1 [높음] app_window_channels.py:191-192 — `_calibration_state`가 d/RL을 cfg가 아니라 라이브 위젯에서 읽음, 워커는 cfg 사용(app_window_run.py:332) (실측)
- C-2 [높음] app_window_save.py:206-211 — 입력 종류와 무관하게 GUI 값을 헤더에 씀, 알파 입력이면 거짓 기록 + runid 갈림 (실측)
- C-3 [치명] app_window_inputs.py:539-554 → data_io.py:715-756 — Mega-Matrix를 1D 로더로 읽어 시각 열을 I₀로 받음 (실측, 코디네이터 재확인)
- C-4 [높음] app_window_inputs.py:443-475 — Auto I₀가 row 0·채널 1 고정이라 hot에서 항상 실패, 메인 스레드 (실측)
- C-5 [높음] app_window_cavity.py:842-853 — 열 인덱스로 채널 혼합 평균, FWHM 쪽(:732-735)과 중복이면서 불일치 (코드 + 그림)
- C-6 [중간] app_window.py:1182-1263, app_window_fitsetup.py:52 — `_daily_*` 차트 함수는 위젯 없는 죽은 코드인데 신호 연결 (코드)
- C-7 [중간] app_window.py:1359, app_window_cavity.py:966 — 두 분기 모두 `""`라 경고·아이콘 표시 불가 (코드 확정)
- C-8 [중간] app_window_dataload.py:180-195 — 자동분배 경로가 refresh 누락, 상태바 분배 요약도 바로 다음 줄에서 덮어씀 (실측)
- C-9 [중간] app_window_run.py:555-566 — `_audit_worker`가 closeEvent 정리 대상에 없음, 감사 도중 닫으면 QThread 파괴로 abort 가능, stop() 호출처 없음 (코드 추정)
- C-10 [중간] app_window_inputs.py:477-492 — min/max 역순, NaN 미처리, RL 변경과 미연결, 상태줄과 다른 통계 (실측)
- C-11 [중간] 진단 그래프 두 그리기 경로가 축 상태를 부분적으로만 리셋 (실측)
- C-12 [중간] health_checks.overall — SKIP만 있으면 PASS 집계 (실측)
- C-13 [중간] app_window_cavity.py:789 → check_r — band·d 하드코딩 (코드)
- C-14 [중간] app_window_inputs.py:88-93 — flag 파싱 실패를 조용히 삼킴 (코드 추정)
- C-15 [중간] worker.py:634 + data_io.py:810 — GUI T/P 폴백 미사용, 폴백 상수가 두 곳(단일 출처 위반) (코드 + 실측)
- C-16 [중간] app_window.py:959-965 — 표시 함수 `_refresh_setup_status`가 txt_max를 바꾸는 부작용 (코드)
- C-17 [낮음] app_window_inputs.py:56 — .mat dark 로더 ch1 하드코딩
- C-18 [낮음] app_window_dataload.py:315-319 — 채널 정체 하드코딩(틀림), raw_parser 단일 출처 위반 (실측)
- C-19 [낮음] tools/r_trend_monitor.py:59-60 — 임포트할 때 sys.stdout을 다시 감싸 버퍼가 닫힘(하네스에서 재현, main.py의 _Tee는 .buffer가 없어 앱에선 안전). r_workers.py:36은 같은 모듈을 다른 이름으로 한 번 더 로드 (실측)

## 하네스 메모
- 첫 전체 실행은 raw 감사 단계에서 로그 없이 종료(exit 0), H 단계만 따로 돌린 재실행은 정상. 종료 시점(os._exit)에 access violation 한 번 기록, 원인 미확인, 앱 결함으로 보고 안 함
- R/Leff Trend는 슬롯 직접 호출, 점 클릭은 QTest로 실제 뷰포트

## 잘 된 점
- day_audit 설계: 읽기 전용, 기대 주기를 데이터에서 뽑음, raw_parser 단일 출처, 백그라운드 스레드, 결과를 meta에 기록. 2.4 GB를 3.5 s에 훑고 결과 정확
- health_checks가 순수함수라 CLI와 판정 로직 공유, Fit window 줌이 mean에 맞춰 흡수 구조를 잘 보여줌
- Trend 점 클릭 → R(λ)는 메모리 우선, 새·옛 하위폴더 후보 순으로 파일을 찾음, 실데이터에서 정확
- RUN 시점 채널별 캘리브 동결, runid, _archive 비파괴 저장 작동 — 이번 실험에서 이전 파일 6개가 _archive로 옮겨짐
- 알파 입력이면 I₀/R을 N/A로(Refresh 후), RUN 시 I₀/R 팝업 생략 — 판단이 맞음
- 고급 섹션을 펼쳐도 우측 패널 폭 거의 그대로(908 → 894 px)
- Alpha Generator·Test Fit은 전제조건 없으면 명확한 경고로 막음
