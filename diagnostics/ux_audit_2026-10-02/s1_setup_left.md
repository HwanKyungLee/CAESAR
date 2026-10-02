# 섹터 1 — Setup 왼쪽 제어 패널 심층 감사 (2026-10-02)

(서브에이전트 보고 원문을 코디네이터가 저장. 증거: 같은 폴더 h_common.py, p_layout/p_refs/p_range/p_run/p_sel/p_race/p_race2.py, launch_s1.py, out_<phase>\log.json, out_<phase>\shots\*.png)

## 코디네이터 검증 메모
- 확인됨: dataload.py:317 하드코딩 문구 "CH1 PNs 180°C + CH2 ANs 300°C"(철회된 판정). worker.py:215-222 겹치는 픽셀이 2개 미만이면 `None`(=전체 범위) 반환. start_analysis(run.py:33-46) 앞부분에 실행 중 재진입 가드 없음.
- **정정 — x1e(요약 7번)**: engine.py:141은 레퍼런스에 multiplier를 곱하고, worker.py:1045-1053은 계수에 mult를 다시 곱해 물리 단위를 복원한다. 주석대로 x1e는 **수치 조건화용 배율이라 농도에 영향이 없는 게 설계상 맞다**. 문제는 결과가 아니라 UX다: UI가 단위 배율처럼 보여서 H2O 4e-13 ppb를 이 스핀으로 고칠 수 있을 것처럼 오해하게 하고, 값만 바뀌어도 runid가 달라져 같은 결과가 다른 이름으로 쌓인다. 심각도는 [중간·UX]로 낮춘다. H2O 단위 문제는 레퍼런스 단위 쪽에서 따로 봐야 한다.

## 15줄 요약
1. [치명] 결과 .dat 헤더의 Poly, Fit Range, λ, Robust, Reference Constraints, Data Period가 채널별 값이 아님 — 저장 시점 활성 채널 값이 모든 채널 파일에 찍힘. CH2 파일 첫 줄 "Poly3 444-471nm"인데 그 아래 헤더 "Poly 4 / 429.5-462 nm" (실측)
2. [치명] "settings frozen for this run" 문구가 거짓 — RUN 도중 Poly·λ·Robust를 바꾸면 세 채널 헤더에 모두 기록. QC K를 바꾸면 그 런 결과에 즉시 적용돼 1976행 NaN. .meta.json qc 블록에 tikhonov 0.5·robust true가 기록되는데 실제 핏은 λ=0·Std (실측)
3. [치명] 핏 범위를 wavecal 밖(300–350 nm)으로 주면 px 0–0이 되고 경고 없이 알파 전체 범위로 핏. DOF 658→2036, NO2 3.24→1.85 ppb인데 "successfully" (실측)
4. [치명] Mask가 "Success"를 띄우지만 다채널 RUN에선 무시(결과 비트 단위 동일). 탭을 한 번 바꾸면 사라지고 기록 없음. 기본값 "441-450"은 nm가 아니라 px라 그대로 적용하면 9 px만 남음 (실측)
5. [치명] 단일 채널 RUN은 라이브 엔진을 그대로 씀 — 실행 중 채널 탭을 바꾸면 워커가 cold 레퍼런스·wavecal로 핏을 이어감. AT_BOUND(sh,sq) 대조군 9건 → 300건 (실측, 대조군 포함)
6. [치명] RUN 중 F5가 먹힘 — 워커 세트가 하나 더 생기고 STOP 후에도 옛 워커 3개가 계속 돎, 진행 표시 "70 / 14 scans" (실측)
7. [중간·UX, 코디네이터 정정] x1e 배율 스핀은 농도에 영향 없음(설계상 약분) — H2O −12→0, NO2 0→3으로 바꿔도 결과 전 자릿수 동일, runid만 바뀜. UI가 단위 배율처럼 보이는 게 문제
8. [높음] Lock 후 이름·x1e·S(파일 교체)를 편집해도 dirty가 안 켜짐 — 다채널 RUN은 잠그지 않은 그 편집을 그대로 씀. "previously locked set으로 핏한다"는 경고가 실제와 반대 (실측)
9. [높음] 레퍼런스를 전부 지우고 RUN하면 CH1이 레퍼런스 0개로 핏되고 "성공"·자동저장까지. 그 상태에서 Lock을 누르면 실패하면서 엔진까지 비움 (실측)
10. [높음] wavecal 라벨에서 roi1과 roi2가 똑같이 "Calib_202606…nm_Poly2.txt"로 보임(RUN 확인 요약도 같음). Load X-axis로 축을 바꿔도 레퍼런스와 축 불일치 경고 없음 (실측)
11. [높음] Fast STOP(8일치, 6 s 시점) 정지에 4.3 s, 결과 0행, 진행 막대 0/3. Step STOP은 0.25 s에 멈추고 76행 보존. 1일 3채널: Fast CPU20 8.33 s, CPU4 17.3 s, Step 53 s (모두 pull 후 dcfb50b)
12. [높음] 레이아웃: 3채널인데 CH3 탭이 스크롤 화살표 뒤에 숨음, 레퍼런스 2행째가 Batch/Add/Mask 버튼 밑에 겹쳐 그려짐, "Parameters" 제목 두 번
13. [높음] lbl_channel_info 문구가 "CH1 PNs 180°C + CH2 ANs 300°C" — 철회된 옛 채널 판정 하드코딩(app_window_dataload.py:317)
14. 코드 리뷰 추가: _run_parallel 예외 시 finished가 두 번 emit돼 다채널 런이 일찍 "완료"될 수 있음(코드 추정). 순차 _run은 바깥 예외에서 finished를 아예 안 보내 GUI가 묶임(코드 추정). .dat에 내부 열 _qc_orig*가 np repr 문자열로 나감. Fast엔 _Smooth 열이 없는데 헤더는 "Kalman 적용"
15. 잘 된 점: RUN 확인 요약에 모든 이상(refs 0, px 0-0, 잠그지 않은 이름)이 실제로 드러남 — 가드만 붙이면 그대로 차단 장치. 폴더 로드·날짜 선택·라벨 자동분배 견고. QC 비파괴. 리플레이가 채널을 알아서 찾음. 같은 runid는 덮지 않고 _archive 보관. 정책표 상시 노출·즉시 반영

## 범위·방법
- 대상: gui/app_window.py init_ui(87–765), app_window_channels / _fitsetup / _dataload / _run / _results / _save / _policy
- 실제 CAESARAnalyzer를 하네스로 구동, 파일 대화상자·메시지박스·QDialog 패치로 자동 응답, 저장은 전부 섹터 폴더로
- 데이터: 운영 fitset + 05-20 하루치 알파(3채널, 73파일, 4172스캔). 다중일 테스트는 캠페인 상위 폴더(56일)에서 3일·8일 선택
- pull 전후: layout·refs·range 단계는 cc9e8c7 이전(46cecef + dirty), RUN 속도·STOP·Step·CPU 수치는 run·sel·race 단계에서 dcfb50b(pull 후)로 재측정. 1일 Fast RUN pull 전 7.3–10 s, 후 8.33 s로 의미 있는 차이 없음
- 결과 표 헤더만 QTest 실제 마우스 클릭, 나머지는 버튼 .click()이나 슬롯 직접 호출(항목마다 표기)

## 1. 상단 줄: Campaign · 채널 탭 · Label · Time shift · Gas T · Load/Save
- 무엇: Campaign은 저장 경로 최상위 폴더 이름. 채널 탭은 채널마다 독립 설정을 갖고 채널별 워커로 병렬 핏, +는 설정 복사해 채널 추가, X는 삭제. Label은 데이터 자동분배용 라벨, Time shift는 시간 이동(h), Gas T는 ppb 환산 온도(0이면 HK 자동). Load/Save는 전 채널 fitset 읽기·쓰기
- 왜: 캠페인은 채널보다 바깥 스코프(app_window.py:129–130), 탭은 겉모양만 탭이고 실제로는 설정을 갈아끼우는 구조(:122–123), 시나리오 버튼은 "분석의 출발점이라 왼쪽 상단에 상주"(:197)
- 써본 결과:
  - 1920 px에서 왼쪽 패널 폭 613 px, 한 줄에 위젯 10개 → Load/Save 30 px, "Save" 잘림
  - 3채널 fitset 로드 시 탭바 폭 143 px라 CH3 탭이 스크롤 화살표 뒤로(L_05_fitset.png). +를 다섯 번 누르면 CH7/CH8만 보임(L_06_many_tabs.png)
  - 채널 전환 0.038 s(refs 재락 포함)
  - poly, Time shift, Gas T, Label, Etalon은 채널별 보존. QC·K·Settling은 전역 — CH1에서 QC on·K=3이면 CH2에도 그대로
  - 데이터 있는 CH2를 X로 지우면 확인 없이 파일 목록까지 사라짐. 채널이 하나 남으면 X 무반응
  - CH4를 지운 뒤 +를 누르면 CH9 생성
  - fitset Save→Load 왕복 차이는 use_etalon 키 추가뿐. QC·K·Settling·Mask는 fitset에 저장 안 됨
- [높음] 운영 구성이 3채널인데 CH3 탭이 기본 화면에서 안 보임 (실측)
- [중간] 채널별 설정과 전역 설정(QC·Settling·Reapply·Update/N·Mode·CPU·Auto-save)이 시각적 구분 없이 섞임 (실측)
- [중간] 채널 삭제가 확인 없이 데이터까지 버림 (실측)
- [중간] +가 data_label까지 복사 → 같은 라벨 탭이 생기고 dataload.py:148–152가 같은 그룹을 두 탭에 매핑해 같은 데이터를 두 번 핏·저장 (코드 추정)
- [낮음] Load/Save 글자 잘림, "Load"가 Load Data와 헷갈림, Gas T 소수 자리 0이라 툴팁 예시 31.5 °C 입력 불가
- 개선: 상단 두 줄(Campaign + fitset Load/Save / 탭 3개 다 보이는 채널 탭바). 전역 컨트롤은 "모든 채널 공통" 그룹으로, QC/Settling은 fitset·meta에(원칙 4). 데이터 있는 채널 삭제는 확인, +로 복사할 때 라벨은 비움

## 2. References (x1e · 이름 · 파일 · S · X / Batch · Add · Mask · Lock)
- 무엇: 레퍼런스 단면 목록. Lock을 눌러야 엔진에 적재되고 결과 표 컬럼·Monitor 콤보 갱신
- 왜: Lock은 엔진 clear → 재샘플 → 10^x1e 배율 → 보간기 생성(fitsetup.py:525–539). dirty 표시는 L5(:485–490, run.py:49–57). Mask는 노이즈 구간을 0으로(ref_mask_dialog.py:52–64)
- 써본 결과:
  - 정책표나 Advanced를 열면 레퍼런스 영역이 1.5행으로 줄고 2행이 Batch/Add/Mask 버튼 밑에 겹침(L_05, L_06) — 그룹 최소높이 110 px(app_window.py:212)
  - Lock 후 편집이 dirty를 안 켬: 이름 H2O→H2Ox, NO2 x1e 0→1, S로 CHOCHO→O3 교체 모두 Lock 버튼 색 그대로. 그 상태 RUN 요약에 CH1 "refs 3: O3, H2Ox, NO2" — 다채널 RUN의 _capture_config(channels.py:108–111)가 위젯 값을 직접 읽음
  - x1e 실험: H2O −12→0, NO2 0→3, Lock 후 RUN → NO2 평균 3.2422868921463035로 기준과 같고 H2O·CHOCHO·RealConc도 3채널 끝자리까지 동일, runid만 r8a58e→r49d7f (engine.py:141–152 scaling = max|raw·mult|, worker.py:1045–1053 coeff/scale_div·mult로 약분 — 코디네이터 메모 참조: 설계상 맞음)
  - Mask: 기본값 "Pixel Range: 441-450". Apply하면 "Success", NO2 2048 px 중 9 px만 남음. RUN하면 워커 엔진 3개 모두 NO2 비영 픽셀 2048, NO2 결과 기준과 비트 단위 동일. 탭 왕복하면 라이브 엔진도 2048로
  - Batch(O3)·Add(빈 행) 후 Lock → "4 locked", 빈 행은 무음 무시. 표 컬럼·Monitor 콤보 즉시 갱신
  - 레퍼런스를 전부 X로 지우고 RUN → "References were changed but Lock was not pressed. The engine will fit with the previously locked set." 경고, Yes면 요약에 CH1 "refs 0" 찍힌 채 진행 → CH1 1399행이 가스 없이 핏(Unstable, TERMINATED, Chi2 13), "successfully"·자동저장
  - 레퍼런스 0행에서 Lock → 경고 뜨고 엔진 gas_list []가 됨(ready False)
- [치명] Mask가 다채널 RUN에서 무시, 탭 전환으로 사라짐, 기록 없음, 기본값은 nm처럼 보이는 px 범위 (실측)
- [중간·UX] x1e는 농도에 영향 없는데(설계상) UI·fitset(H2O −12)은 의미 있어 보임, runid만 바뀌어 같은 결과가 다른 이름으로 쌓임 (실측, 코디네이터 정정)
- [높음] 이름·x1e·파일 교체가 dirty를 안 켬, 다채널에선 경고 문구가 실제와 반대, Lock 의미가 단일 채널(라이브 엔진)과 다채널(config 재빌드)에서 다름 (실측)
- [높음] 레퍼런스 0개로 RUN 허용, "성공" 종료 (실측)
- [중간] Lock 실패 시 엔진이 비워짐(fitsetup.py:540) (실측)
- [중간] 레퍼런스 영역 겹쳐 그려짐 (실측)
- [낮음] 파일 라벨에 roi1/roi2 폴더가 안 보임
- 개선: 단일 채널도 RUN 때 _build_engine_from_config로 독립 엔진(5절 경합도 해결). 최소 대안은 행 위젯 시그널을 _mark_refs_dirty에 연결. Mask는 config(refs[i].mask)에 넣어 엔진 빌드마다 재적용·meta 기록, 못 하면 버튼 숨김, 범위는 nm로 받고 기본값 비움. x1e는 "수치 조건화용(결과 불변)"으로 명시하거나 runid 계산에서 제외. 데이터 있는 채널에 레퍼런스 0개면 RUN 거부. lock_ref는 새 엔진을 만든 뒤 성공 시에만 교체

## 3. Fit Range (Load X-axis · wavecal · FWHM · nm/px · Unit · Vis.)
- 무엇: 채널별 wavecal과 핏 창. Unit이 모드 스위치, Vis.는 드래그로 범위 선택
- 왜: wavecal 라벨은 0608/0523 오정렬 사고 재발 방지(app_window.py:310–313), nm 칸은 editingFinished에서 px 자동 동기화(:354), Unit 콤보는 F2 모드 스위치(:379)
- 써본 결과:
  - nm 440 → px 815–1268 정상
  - nm 470~440 역순 입력 → 스핀엔 역순 그대로, px·요약은 스왑
  - wavecal 밖(300–350 nm) → px 0~0, 요약 "range px 0-0", 그래도 RUN 진행: CH1 DOF 2036(정상 658), NO2 1.85(정상 3.24), RMS 중앙값 13배, 팝업 "successfully". 원인 worker.py:217–222(슬라이스 2 미만이면 None = 전체 범위)
  - px 모드 "abc"는 RUN 때만 경고, 1500/700은 스왑
  - fitset px 599–1270인데 nm 재계산 599–1268, 헤더·meta엔 1270 기록
  - CH1에 Load X-axis로 roi1 → "Loaded", 툴팁만 roi1로, 라벨은 roi2일 때와 글자 하나 다르지 않음. dirty 안 켜지고 다채널 RUN은 roi1 wavecal + roi2 레퍼런스로 경고 없이 빌드
  - FWHM 라벨에 "WL "만(fitsetup.py:162)
  - Vis.는 데이터 없으면 무음(dataload.py:355), 데이터 있으면 다이얼로그 좋음(dlg_RangeSelectorDialog_*.png)
- [치명] wavecal 밖 범위가 전체 범위 핏으로 바뀌고 "성공" (실측)
- [높음] 라벨·RUN 요약에서 roi1/roi2 구분 불가 (실측)
- [높음] wavecal을 바꿔도 레퍼런스·축 불일치 경고 없음 (실측)
- [중간] 헤더/meta px와 실제 슬라이스가 다름 (실측)
- [낮음] "WL " 표시, 역순 값 방치, Vis. 무음
- 개선: RUN 가드로 창이 wavecal 안에 있고 슬라이스가 충분한지 검사, 워커의 None 폴백은 명시적 "전체 범위" 요청일 때만. 라벨·요약은 _calibration_state._tag(channels.py:163–170)의 parent/basename 형식 재사용. 헤더 px는 실제 슬라이스에서 기록

## 4. Parameters (Step · Poly · ±Neg · QC · K · Settling · Reapply · Sh/Sq · Reference policy · Advanced)
- 무엇: 핏 파라미터와 사후 QC, 가스별 정책표(즉시 반영). Advanced에 Tik λ, Robust, Etalon, OK RMS%, Kalman Q/R
- 왜: Advanced는 "우리 데이터엔 보통 불필요"(app_window.py:590–592), 정책표는 "1급 결정이라 상시 노출"(C1, :565–569)
- 써본 결과:
  - "▼ Parameters" 바로 밑에 그룹 제목 "Parameters" 한 번 더
  - Poly 0: CH1 1399행 중 Unstable 1216. Poly 10: 경고 없이 돌고 OK 1150
  - QC 순서: K=3 → 94행 NaN, Reapply K=8 → 34행, Settling 켜고 Reapply → 219행(73파일 × 3, 비파괴), 전부 끄고 Reapply → 팝업 "Excluded: 220 / 4,172"인데 실제 제외 0행
  - OK RMS% 10→1 후 Reapply → 바뀌는 행 0. 그런데 Reapply 툴팁은 "OK RMS% re-judge", "Settling skip ()" 줄은 깨짐(app_window.py:513–521)
  - 정책표: NO2 Shift "-3, 3" → ref_props·요약 즉시 갱신, 탭 왕복해도 보존. 표 높이 120–220 px, 8열이 613 px에 들어가 열 제목 잘림. Squeeze 값의 뜻이 두 가지(doas_fit.py:368–381): |v|<0.5면 1+v, 그 이상이면 절대값 → Fix 0.4는 1.4, Fix 0.5는 0.5
  - Kalman: Fast 결과 .dat엔 _Smooth 열이 없는데 헤더는 "_Smooth = Kalman-filtered"
- [중간] Reapply 팝업 "Excluded"에 복원된 행까지 포함 (실측)
- [중간] Reapply·OK RMS% 툴팁이 실제와 다름 (실측)
- [중간] Fast에선 Kalman 무효인데 헤더는 적용됐다고 씀 (실측)
- [중간] Squeeze 이중 의미가 UI에 안 드러남 (코드 확인)
- [낮음] 제목 중복, 정책표 열 잘림, Poly 0/10 무경고
- 개선: 그룹 제목 삭제. "사후 처리(재핏 불필요): QC/K/Settling/Reapply" 소그룹과 "핏 파라미터" 영역 분리. Reapply 팝업은 새로 제외/복원을 따로 셈. Squeeze 칸 옆에 해석된 값(→1.004 등) 미리보기

## 5. Analysis (RUN): Load Data · RUN · STOP · Save · Update/N · Mode · delay · CPU · Auto-save
- 무엇: 데이터 로드(파일 선택 또는 폴더 + 날짜 선택 + 라벨 분배) → 채널별 워커 핏 → 저장
- 왜: Load Data 버튼 하나는 "main UI clean"(dataload.py:24–27), 폴더 로드는 가지치기 + 측정 파일 접두 필터(FWHM 사고, :60–69), Fast STOP은 0.5 s마다 확인(worker.py:1356–1358), CPU 스핀은 core.parallel 단일 출처(app_window.py:695–697)
- 써본 결과 (pull 후 dcfb50b):
  - 56일 폴더 → 날짜 선택(360×401, 기본 전체 선택) → 8일 선택 → 분배 193/193/182, 1.12 s
  - 하루치 분배 후 CH1에서 Select Files로 05-21 ANs 2개 → CH1=2, CH2=24, CH3=25(05-20). 상태줄 "2 file(s) loaded"뿐, RUN은 날짜 다른 51파일을 같이 핏

  | 항목 | 결과 |
  |---|---|
  | Fast, CPU 20, 1일 3채널 | 8.33 s |
  | Fast, CPU 4 | 17.29 s |
  | Step, delay 0 | 53.2 s |
  | Step STOP | 0.25 s, 76행, autosave 76행 |
  | Fast STOP (8일치, 6 s 시점) | 정지 4.27 s, 결과 0행, 진행 막대 0/3, 팝업 "Analyzed up to the stop point." |

  - Step은 표·Trend 실시간 갱신. 이벤트 루프 최대 정지 Fast 372 ms, Step 246 ms
  - Fast STOP 진행 막대 0/3 원인: worker.py:1402 finally의 scan_count_ready(max(nxt,1))가 분모를 덮음
  - 자동저장 off → .dat 안 생기고 완료 팝업에 "저장 안 됨" 안내 없음
  - Update/N은 Fast에서 무시(run.py:182)되는데 스핀은 활성
  - RUN 중 F5 → 워커 세트 하나 더, STOP 후에도 옛 워커 [True, True, True] 계속, RUN 버튼 켜지고 진행 "70 / 14 scans". run.py:33–64에 재진입 가드 없음
  - 단일 채널 RUN 중 탭 전환(CH1 6파일 350스캔, Step, 2 s에 CH3로): 탭 전환 AT_BOUND 300·OK 32 / 대조(전환 없음) AT_BOUND 9·OK 103. 워커 엔진 id가 self.engine과 같았고 탭 전환이 그 객체를 clear 후 cold로 다시 채움
- [치명] RUN 중 탭 전환·fitset Load·Lock이 단일 채널 런의 엔진을 바꿔치기 (실측)
- [치명] F5 재진입 → 워커 이중 실행, 고아 워커로 결과·진행·autosave 섞임 (실측)
- [높음] Fast STOP은 연속으로 완료된 청크까지만 남김(초반이면 0행), 결과 0행인데 성공형 문구, 진행 막대 0/3 (실측)
- [높음] Select Files는 활성 채널만 바꾸고 다른 채널에 이전 데이터가 남아 있다는 걸 안 알림 (실측)
- [중간] Fast에서 Update/N 활성, 자동저장 off일 때 완료 팝업 경고 없음 (실측)
- [낮음] RUN 버튼·Vis.가 데이터 없을 때 무음(run.py:44–45) (실측)
- 개선: start_analysis에 _analysis_running 가드 + RUN 동안 왼쪽 입력 잠금(그래야 "frozen"이 참). 단일 채널도 config로 빌드한 독립 엔진. Fast STOP 때 완료된 청크 emit, 빈 구간은 "Skip: stopped" flag, 진행 막대 분모 보존. Select Files 후 다른 채널에 남은 데이터를 상태줄·요약 맨 위에 표시

## 6. Save · 헤더 · meta ("settings frozen" 검증)
- 무엇: {campaign}/{date}/fitting/{date}_CH{n}_{label}_{runid}.dat + .meta.json, 같은 runid면 _archive로
- 왜: meta는 RUN 시점 동결(run.py:270–275), 헤더는 재현 기록(save.py:56–60)
- 써본 결과:
  - run2 산출물 260519_CH2_PNs_r6911a.dat: 첫 줄 "Channel 2 (PNs) settings: 444-471nm_Poly3", 그 아래 헤더 "Fit Range 599-1270 (429.5-462.0nm)", "Polynomial Degree: 4", "Reference Constraints Sh[-10,0.5]" — 모두 CH1 값. 05-19 파일 Data Period "05-19 15:41 ~ 05-21 00:09"
  - frozen 실험(3일, Fast): 2 s 시점에 Poly 2, λ 0.5, Robust, QC on, K=2로 변경. 스핀은 RUN 중에도 활성, 상태줄은 계속 "settings frozen". QC는 K=2로 적용돼 1976행 NaN. 세 채널 헤더 모두 Poly 2 / λ 0.5 / Robust ON / K=2. meta poly_deg는 4/3으로 맞지만 qc 블록에 tikhonov 0.5·robust true(channels.py:196–219), runid r105a2로 바뀜
  - .dat에 _qc_orig, _qc_orig_sm, _qc_orig_status, _signal_mean 열이 {'CHOCHO': np.float64(...)} repr로 기록
- [치명] 헤더 값이 채널별이 아니라 저장 시점 라이브 값, 같은 파일 안에서 첫 줄과 본 헤더가 모순 (실측)
- [치명] meta가 λ·Robust·Etalon을 저장 시점 값으로 기록 (실측)
- [치명] RUN 중 QC 편집이 그 런 결과에 적용 (실측)
- [중간] Data Period가 파일이 아니라 런 전체 기간 (실측)
- [중간] 내부 dict 열이 repr 문자열로 나감 (실측)
- 개선: 헤더는 _run_frozen['configs'][ch]에서 채널별로(_ch_header·_channel_settings_tag와 같은 출처). _qc_state에서 핏 파라미터 빼고 frozen cfg에서 읽기. 저장 전 "_" 접두 키 버리고 원본값은 평탄한 열로

## 7. 상태줄 · 진행 막대 · 결과 표
- 헤더를 QTest로 실제 클릭해도 정렬 안 됨, setSortingEnabled(False)를 다시 켜는 곳 없음
- 단일 클릭(슬롯 호출)이면 CH3 행 리플레이 후 Monitor로. CH3 탭에서 CH1 행 더블클릭도 리플레이
- 탭 전환해도 결과 표 유지("results table kept")
- "Set as I0"는 다채널 표에서 0열이 "CH1"이라 무음 실패(inputs.py:531)
- 상태줄 덮어쓰기로 메시지 유실 — 예: "Skipped N non-measurement"(dataload.py:83)가 :326 메시지에 즉시 덮임
- lbl_channel_info "2 channels (Hot: CH1 PNs 180°C + CH2 ANs 300°C)"(dataload.py:317)는 CLAUDE.md 채널 정체와 반대, cold 데이터 로드해도 "CH1 detected"
- [높음] 철회된 채널 정체 하드코딩 (코드 확인, 코디네이터 재확인)
- [중간] 정렬 안 됨, Set as I0 무음 실패, 상태줄 메시지 유실 (실측)
- 개선: 채널 이름은 raw_parser 단일 출처에서. 리플레이가 파일명 기반이라 정렬 켜도 안전(save.py:359–366). 알파 입력이면 "Set as I0" 메뉴 숨김

## 8. 레이아웃·순서 판단
- 실제 작업 순서는 fitset Load → Load Data → RUN → Save인데, 첫 단계 버튼은 맨 위 줄 오른쪽 끝 30 px 버튼, 둘째 단계는 맨 아래 그룹. References·Fit Range·Parameters는 fitset이 채워 주는 "확인·미세조정" 영역
- 제안: 맨 위에 실행 줄 "① fitset ② Data ③ RUN/STOP ④ Save", 그 아래 채널 탭과 접이식 상세
- 결과 표는 Fast에서 끝날 때까지 비는데 패널 높이 절반 차지 → 접을 수 있게 하거나 Monitor로
- 1366×728에선 세로 스크롤 88 px. 1920에선 Advanced·정책표를 함께 열면 레퍼런스 영역 겹침

## 코드 리뷰
- [치명] run.py:33–64, app_window.py:885 — 재진입 가드 없음. F5면 _workers가 교체되고 옛 QThread 고아화, STOP/closeEvent는 새 목록만 봄(run.py:538, 559) (실측)
- [치명] run.py:338–340 + channels.py:284 — 단일 채널 런은 eng_ch = self.engine 그대로. GUI 스레드의 탭 전환·load_scenario·lock_ref가 워커가 쓰는 같은 객체를 clear·재구성(스레드 경합 + 잘못된 레퍼런스로 핏) (실측, 대조군 포함)
- [치명] save.py:47–48, 108–110, 134–146, 187–213 — 헤더 값을 라이브 위젯에서 읽음 → 다채널이면 모든 파일에 활성 채널 값, RUN 후 편집 값 (실측)
- [치명] channels.py:196–219 _qc_state가 tikhonov·robust·etalon 포함(run.py:634) → meta·runid에 저장 시점 핏 파라미터 (실측)
- [치명] worker.py:217–222 — 겹치는 구간 없는 nm 창이 None(전체 범위)으로 바뀌어 성공 처리 (실측, 코디네이터 재확인)
- [치명] fitsetup.py:498–523 + save.py:536–581 — Mask는 라이브 엔진에만, 엔진 재빌드·_apply_config 재락 때 사라짐, 기록 없음 (실측)
- [높음] worker.py:530–544 + 1399–1403 — _run_parallel finally가 finished emit, 예외가 밖으로 나가면 _run except가 한 번 더 → _workers_done 이중 카운트로 다채널 런이 다른 채널을 안 기다리고 완료·QC·자동저장 (코드 추정)
- [높음] worker.py:548–926 — 순차 _run에서 스캔별 try 바깥 예외면 finished 미emit, run() finally는 덤프만 닫음 → RUN 비활성·STOP 활성으로 GUI 영구 묶임 (코드 추정)
- [높음] fitsetup.py:428–483 — 행 위젯이 _mark_refs_dirty에 미연결, _capture_config는 잠그지 않은 위젯 값을 읽음 (실측)
- [중간·코디네이터 정정] engine.py:141–152 ↔ worker.py:1045–1053 — mult가 약분돼 x1e는 결과 불변(설계상 의도로 보임), 다만 runid가 바뀌고 UI가 단위 배율처럼 보임 (실측)
- [높음] run.py:72–106 — 데이터 있는 채널의 레퍼런스 0개 검사 없음 (실측)
- [높음] worker.py:1402 — finally의 scan_count_ready(max(nxt,1))가 STOP 후 진행 막대 분모 덮어씀 (실측)
- [중간] fitsetup.py:540 — lock_ref가 먼저 clear해서 실패하면 이전 엔진 잃음 (실측)
- [중간] results.py:303–318 — Reapply len(changed)에 복원된 행도 포함, "Excluded"로 표기 (실측)
- [중간] results.py:235–246 — stopped=True 분기 죽은 코드(finished는 인자 없는 시그널) (코드 확인)
- [중간] save.py:128–131 — Params만 drop해서 _qc_orig* repr 열이 나감 (실측)
- [중간] save.py:162–167 — 날짜별 파일마다 Data Period가 런 전체 기간 (실측)
- [중간] dataload.py:148–152 — 같은 라벨 탭이 여럿이면 중복 매핑 (코드 추정)
- [중간] dataload.py:317 — 채널 정체 문구 하드코딩(철회된 판정, raw_parser 단일 출처 위반) (코드 확인)
- [중간] inputs.py:529–537 — 다채널 표에서 Set as I0 무음 실패 (실측)
- [낮음] app_window.py:513–521 — Reapply 툴팁 낡고 깨짐 (실측)
- [낮음] fitsetup.py:162 — "WL " 표시, 숨겨진 ILS 위젯(app_window.py:248–295)은 죽은 UI (코드 확인)
- [낮음] run.py:200, 213, 226 — return할 때 _analysis_running을 되돌리지 않음(지금은 알파 전용이라 거의 안 닿음) (코드 확인)
- [낮음] dataload.py:83 — skip 메시지 즉시 덮어써짐 (코드 확인)
- (하네스 전용) cp949 파이프에서 이모지 print가 예외. main.py는 session_log _Tee가 삼켜 실사용 무해

## 다른 섹터 확인 요망
- Step Trend(23_step_running.png)에서 같은 파일 번호의 cold 시각이 hot보다 약 11–13 h 뒤. 예: 2026-05-20-001_cold [0056] = 05-20 04:40, 2026-05-20-001_PNs [0010] = 05-19 16:52. cold 시각축이 hot과 다른 UTC 규약을 쓰는지 확인 필요
- Monitor 하위 탭 라벨이 Step 실행 중에도 "(Fast)"

## 잘 된 점
- RUN 확인 요약이 채널별 wavecal·px·poly·정책·시간 이동을 다 보여줌 — 이번에 찾은 이상(refs 0, px 0-0, O3/H2Ox)이 전부 여기에 드러남. 가드만 붙이면 그대로 차단 장치
- 다채널 RUN은 채널마다 독립 엔진, 폴백을 상태줄로 알림. meta의 캘리브 동결도 채널별
- 폴더 로드 견고(재귀, 가지치기, 측정 파일 접두 필터, 날짜 다중선택, 라벨 분배, 중복 스캔 경고), 8일치 선택 1.1 s
- QC 비파괴, Reapply 반복해도 원복(94→34→0)
- Step STOP 0.25 s에 멈추고 부분 결과 보존, 같은 runid는 _archive로(헌장 ①)
- 리플레이가 행의 채널을 찾아 그 채널 엔진으로 다시 그림
- 정책표 상시 노출·즉시 반영·탭 전환 보존, Center 모드 요약 정확
- CPU 스핀 효과 뚜렷(8.3 s vs 17.3 s), 툴팁 설명 정직
