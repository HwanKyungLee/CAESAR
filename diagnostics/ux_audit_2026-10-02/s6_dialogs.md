# 섹터 6 — Setup 도구 다이얼로그 심층 감사 (2026-10-02)
(Alpha Generator · R Calibrator · Wavelength Calibration · Reference Generator · Test Fit · Mask · Peak Trend)

(서브에이전트 보고 원문을 코디네이터가 저장. 증거: 같은 폴더 h6.py, st_*.py, tb_alpha.py, run_s6.py, run_tb.py, out_*.log, out\<stage>\log.json, shots\)

## 코디네이터 검증 메모
- 확인됨: worker.py:2482-2483 빈 입력 분기는 5개 반환, :2503-2506 호출부는 6개 언팩 → 핫 raw(He 블록 없음)면 He 호출이 항상 이 분기로 들어가 ValueError. 원인 커밋 `f700cb1`(2026-09-21 "_block_average 분기점을 명시").
- 확인됨: tools/rt_precompute.py:533-542 — 기존 npz 로드 예외를 print만 하고 넘어가 빈 누적에서 새로 시작 → 저장 시 기존 knot 소실.
- 서브에이전트가 만든 %TEMP%\caesar_amb_*.bin 7개(각 58 MB)는 자기가 지웠다고 보고. R Calibrator가 HKCU\Software\CAESAR\app\r_calib/* 를 씀 → 레지스트리 복원 대상.

## 15줄 요약
1. [치명] 핫 알파 생성이 매번 크래시 — worker.py:2482-2483 빈 입력 분기는 5개, 호출부(:2503-2506)는 6개 언팩(2026-09-21 f700cb1 이후). 여수 핫 raw엔 He(510)가 없어 R(t) npz를 지정해도 ANs·PNs 둘 다 실패. pull 후 dcfb50b에서도 재현. 운영 핫 알파는 09-19 산물이라 회귀 이전
2. [치명] 알파 실패가 성공처럼 보임 — 진행바 100 %, 상태 "Done", 팝업 제목 "Alpha generation complete". 실패마다 %TEMP%에 스풀 58 MB 잔존(run()의 except에서 `_cleanup_spool` 미호출)
3. [치명] R npz 읽기 실패 시 누적 npz가 새 결과만으로 덮어써짐(rt_precompute.py:541). 운영 R_cold 사본으로 재현: 667 knot → 1 knot. 저장 비원자·백업 없음. 창을 닫으면 terminate()가 불려 이 경로로 들어갈 수 있음
4. [치명] Test Fit Apply가 지금 활성인 채널에 적용 — 비모달 창이라 CH1에서 최적화 후 CH2 탭으로 바꾸고 Apply하면 ANs의 shift Center −6.07 추천이 PNs에 들어감(실측). 확인창·diff·undo 없음
5. [치명] Mask 기본값 "441-450"은 픽셀 — Apply하면 NO2 −1.3e88 ppb인데 "Success". 역순 범위면 레퍼런스 전체 0. FitSet에도 결과 헤더에도 기록 안 되고 재Lock·채널 탭 왕복이면 말없이 사라짐
6. [높음] 알파 채널 매핑 기본이 탭 번호 — 콜드 raw를 넣으면 ANs 탭(핫 roi2 wavecal, 라벨 ANs)으로 경고 없이 생성. FitSet 없이 쓰는 폴백 매핑(app_window_inputs.py:234)은 채널 정체와 반대라 ch2(PNs)에 roi2
7. [높음] Wavecal "Save & Apply"가 반만 적용 — engine._wave_axis, loaded_wl_path, 채널 wl_path는 옛 값이라 Alpha Generator·R Calibrator·FitSet 저장이 모두 옛 wavecal 사용
8. [높음] Wavecal에서 숫자 아닌 파장 입력은 말없이 빠짐 — 3쌍만 남아 R²=1.000000, 잔차 표시 없음, 저장 파일에 픽셀↔라인 쌍·계수 없음. Auto Suggest는 Hg 4라인 중 2개만 찾음
9. [높음] Test Fit Apply 게이트는 T1(|ac1|)·불변식뿐, T2는 표시만(CHOCHO CV 4530 %인데 Apply 켜짐). Center 추천을 "Limit -6.07, 2.07"로 잘못 표기, 사유 문자열의 `<`가 HTML로 먹혀 잘림
10. [높음] R Calibrator 결과 폴더 기본값 "."이 저장소 루트로 풀림. Skip을 끄고 재계산해도 npz엔 옛 knot이 남고 config만 새 값. Breaks 입력에 시간대 안내 없음(축은 UTC)
11. [높음] 레퍼런스 생성기는 1열로 저장 — 파장축·T/P/출처/wavecal 정보 없음. 운영 H2O 레퍼런스는 셀 온도가 아니라 약 298 K로 만든 것과 일치(r=0.99999998)하지만 헤더로 확인 불가. 자동 등록 시 H2O-HITRAN·NO2 중복 행
12. [중간] 어느 다이얼로그에도 취소 없음 — 알파 창은 닫아도 작업이 계속 돌고 동시에 두 번 돌리면 상태가 섞임. Test Fit 창 닫기는 UI 3 s 정지 후 terminate(). HITRAN 생성은 메인 스레드 8.6 s 동결. Explorer 출력 cp949 모지바케. R Calibrator(1100×760)·Ref Gen(1098×764) 기본 높이가 728 초과
13. [중간] R Calibrator에 연속 기간이 아닌 부분 파일만 넣으면 knot 0개인데 정상 종료처럼 보임. 결과 팝업 제목 "R(t) saved", 본문 "no R(t) saved"
14. 잘한 점: 알파 입력 파일명 가드가 FWHM 파일 혼입을 정확히 차단. 알파 헤더에 git 해시·purge_settle·clock_epoch·R 출처. 생성 중 GUI 정지 ≤42 ms. 운영 NO2 레퍼런스를 상대오차 7e-10, wavecal을 0.004 nm 이내로 재현. Test Fit 7.5 s, 추천·적용 분리, Center 변환. R 트렌드 dat 덮어쓰기 가드와 Verify 잘 만듦
15. Peak Trend는 UI에서 도달 불가(배선 해제). 시간 수치는 전부 pull 후 dcfb50b 재측정

## 감사 조건
- 코드 기준 pull 후 dcfb50b(cc9e8c7 raw 행 캐시 LRU-1 포함). pull 전(46cecef)엔 alpha, alpha3, alpha4 단계만 돌렸고, 시간 수치는 전부 pull 후 재측정(out_alpha2_post.log, out_r.log, out_wl.log, out_ref.log, out_tf.log). pull 전후로 결론 바뀐 항목 없음, 1번 크래시는 dcfb50b에서도 재현
- 방법: 실제 CAESARAnalyzer를 띄워 각 다이얼로그를 열고 버튼 슬롯·마우스 클릭(QTest, matplotlib 캔버스 클릭) 실행, 파일·메시지 박스 자동 응답 패치
- 실데이터: 핫 raw 2026-05-20-001/002, 콜드 raw 2026-05-20-001/002(사본), wv_cal 사본, 운영 R_CH1/CH2/cold.npz 사본(Rcopy\), 운영 FitSet, 05-20 하루치 알파
- 쓰기 범위: 전부 s6_dialogs\ 안. HITRAN db_begin과 DoasisLab QSettings도 스크래치로. 저장소·운영 폴더 불변(git status 확인)
- 1366×768: 모든 다이얼로그 minimumSizeHint는 1366×728 안. 단 기본 높이가 728 넘는 창 둘 — R Calibrator 1100×760(ui_dialogs_r.py:70), Reference Generator 1098×764(reference_generator_dialog.py:77) — 작업표시줄 있으면 하단 잘림

## 1. Alpha Generator (gui/ui_alpha_gen.py; 처리는 app_window_inputs.py:121-438, worker.py AlphaExportWorker)
- 무엇: raw → 채널별 α 파일(`*_alpha_trace.dat`). wavecal·핏범위·cavity·flag 설정은 메인 창 것 사용, 채널마다 어느 탭 설정을 쓸지·어떤 R(t) npz를 쓸지 선택
- 왜: 분석(RUN)과 알파 생성 분리(:1-5), CPU 코어 수는 메인 창과 공유하되 긴 작업 창에서도 보이게(:113-115), purge settle 60 s는 여수 콜드 실측(:77-79), 파일명 정규식 가드는 2026-07-09 FWHM 혼입 사고 이후(:255-258)
- 써본 결과:
  - 열기 0.9 s, 840×520. FWHM 파일 섞어 넣으면 정확히 걸러내고 경고
  - 핫 2파일: 두 채널 모두 실패(`ValueError: not enough values to unpack (expected 6, got 5)`), R(t) npz 지정해도 동일. pull 후: 새 파싱 시 4.6 s 뒤 크래시(파싱 2.25 s 포함), 캐시 있으면 0.8 s 뒤. 트레이스백 worker.py:2505
  - 콜드 성공(R_cold 사본, 탭 CH3 매핑): 1파일 캐시 없이 1.7 s, 2파일 3.6 s, 캐시 있으면 2.0 s, 메인 루프 최대 정지 42 ms
  - 헤더: 있음 — code=g46cecef-dirty, purge_settle_sec=60, clock_epoch=none +0h, external R(t) — R_cold.npz (667 knots). 없음 — wavecal 경로, 매핑한 탭, R npz 전체 경로·해시
  - 콜드를 기본 매핑(raw CH1 → ANs 탭)으로 생성하면 경고 없이 성공: 라벨 ANs, wavecal 핫 roi2, 파장축 400.0416 시작(콜드 실제 400.3151), 파일명 `_ANs_alpha_trace.dat`
  - 생성 중 Close(1.5 s, 캐시 없음): 창만 숨고 워커는 계속 돌아 파일 씀, 완료 팝업이 닫힌 창에서 뜸, 다시 열면 Generate 활성·진행 표시 없음
  - 동시 두 번 실행: 두 팝업 모두 Location run2, 두 번째 팝업 `[cold] [cold]`(out_alpha4.log)
  - 실패 실행마다 58 MB 스풀 잔존(7개)
- [치명] 핫 알파 항상 크래시(실측, pull 후 재확인). 핫 raw엔 He(510) 없음 — 05-20-001 flag 분포 500×34, 502×29, 503×6, 1×3646 → `_block_average` 빈 입력 분기(5튜플, :2482-2483) vs f700cb1 이후 호출부 6개 언팩(:2503-2506). 운영 핫 알파는 09-19 산물, pytest로 안 잡힘
- [치명] 실패해도 화면은 "완료"(실측) — 진행바 100 %, "Done", 제목 "Alpha generation complete", 마지막 줄 "Now Load this α file … RUN"(ui_alpha_gen.py:425-434)
- [높음] 채널 매핑 기본이 "raw 채널 번호 = 탭 번호"(실측, :323) — 콜드 raw가 ANs 설정으로, ncols 6179(콜드) 정보를 매핑에 안 씀
- [높음] 폴백 매핑 `{1:'roi1',2:'roi2'}`가 채널 정체와 반대(실측, app_window_inputs.py:234), wavecal 하나만 로드하면 ch2도 roi2. 경고 문구(:181, :190)도 옛 규약 기준
- [높음] 취소 없음 — `stop()`(worker.py:2066) 호출처 없음, Close는 숨기기만
- [높음] 예외 시 스풀 누수(실측) — run()(worker.py:2069-2073)에 `_cleanup_spool` 없음, 주석(:2123-2127)은 예외 경로도 정리한다고 적어 사실과 다름. 캠페인 단위로 돌다 실패하면 수십 GB
- [중간] 동시 실행 시 상태 덮어씀(실측, app_window_inputs.py:194-211), 다시 연 창은 진행 중인 실행을 모름
- [중간] 성공 메시지가 `"[cold] "`뿐 — 파일 수·bin 수·경로 없음(:423)
- [중간] 로그 모순: "no valid R-calibration → cannot compute alpha" 바로 뒤에 R(t) 로드·저장 성공. R(t) 없는 콜드 1시간 파일은 "no R-calibration or ZA spectrum"으로 끝나는데 R(t) 지정 안내 없음
- [낮음] Indexing 단계에서 파일 수를 "scans"로, 진행률 25 % → 0 % 역행. app_window_inputs.py:299 주석 "기본 700~1700"인데 실제 0~2048
- 개선: 빈 입력 분기를 `..., 0`까지 6개 반환 + "He 없음 + R(t) 지정" 경로를 tools/test_*.py로 고정. 한 채널이라도 실패하면 제목·아이콘·진행바를 실패 상태로. 기본 매핑은 ncols·data_label로, 어긋나면 확인. 폴백 roi 매핑은 raw_parser 단일 출처에서. Close면 stop(), 스풀 정리는 try/finally. 헤더에 wavecal 경로·해시, 매핑 탭, R npz 경로·해시

## 2. R Calibrator (ui_dialogs_r.py, r_workers.py, tools/rt_precompute.py)
- 무엇: 채널별 ZA/He 블록으로 R(λ)·R(t) 계산. Start는 `{out}/{campaign}/calibration/R_<label>.npz`에 증분 병합. Rebuild(전체 덮어쓰기), Verify(읽기 전용 점검), Breaks(수동 분절)
- 왜: 자동 갱신 기본값으로 npz 관리 부담 제거(:213-215), 날짜범위 파일 0개면 전체 스캔으로 넘어가지 않게(:536-538), 트렌드 dat는 읽기 실패 시 덮어쓰지 않음(r_workers.py:273-283, 헌장)
- 써본 결과:
  - 열기 0.56 s, FitSet에서 행 3개 자동 채움
  - Result folder 기본값 "."이 C:\GHL\CAESAR로 풀림(경로 해석만 확인, Start는 스크래치로 바꾼 뒤)
  - Start(핫 2 + 콜드 2) 6.0 s, knot 0개 — 핫 "no He (no last_he either)", 콜드 001 "He/ZA contrast 0.7 % < 5 %", 콜드 002 He 없고 이어받을 앞 파일 He도 없음. 운영 R에도 05-20 00:41 knot이 없으니 결과는 운영과 일치. 다만 로그 "no new files; showing 0 existing"는 틀림(새 파일 계산이 실패한 것)
  - Skip 켠 두 번째 Start 1.7 s, Verify 0.01 s 정확
  - Rebuild 1.8 s, 팝업 제목 "R(t) saved" 본문 "no R(t) saved"
  - 손상 npz 병합 재현: 운영 R_cold 사본을 절반으로 잘라 `_merge_knots_into_npz` 호출 → 667 knot이 1 knot, 흔적은 stdout "creating new" 한 줄
  - 같은 시각 knot을 다른 값으로 재계산 병합하면 옛 값 유지
  - 로그 시각 +9 h인데 TZ 표기 없음(01:41 UTC → "05/20 10:41")
- [치명] npz 읽기 실패 시 누적 npz를 새 결과로 덮어씀(실측, rt_precompute.py:541-542, append_rt :498도 같음). docstring "절대 덮어쓰지 않는다"와 모순, 트렌드 dat의 가드가 npz엔 없음
- [높음] 저장 비원자·백업 없음(코드 추정) — save_rt(:195) 직접 쓰기, 저장 중 창 닫으면 3 s 뒤 terminate()(ui_dialogs_r.py:1065-1070) → npz 잘림 → 다음 Start에서 위 치명 경로. Rebuild도 옛 파일 보관 안 함(:785-800)
- [높음] Skip을 끄고 재계산해도 npz 미반영(실측, rt_precompute.py:563-572) — 같은 시각은 첫 knot 유지, config는 새 값(예: RL 0.9). 툴팁(:229-231)과 다름
- [높음] 출력 폴더 기본값 "." — Verify·Breaks까지 `_out_root()`에서 폴더 생성(:519-526, :684-688)
- [높음] Breaks 입력에 시간대 안내 없음(:747-751), knot 축은 UTC인데 KST로 입력하면 9 h 어긋난 분절 저장
- [중간] 부분 파일 실행이 정상 종료처럼 보임 — 핫은 앞 파일 He를 이어받으므로(last_he) 연속 기간 필요한데 화면 안내 없음, "R(t) saved / no R(t) saved" 모순(:823)
- [중간] 취소 없음 — Esc(reject)는 closeEvent를 안 거침, quit() 무효, Rebuild 워커는 아예 처리 안 함
- [중간] GUI 산출물 이름(R_ANs.npz)이 운영 규약(Output\R\R_CH1.npz)과 달라 운영 npz를 Verify·Breaks로 바로 점검 불가
- [낮음] 시각 표시 TZ 라벨 없음, 결과가 비면 축 눈금 "00.100" 같은 쓰레기 값
- 개선: npz는 임시 파일에 쓰고 os.replace, 덮어쓰기 전 .bak/아카이브. npz 로드 실패는 예외로 올리고 해당 채널만 건너뜀. 재계산은 같은 시각 knot 교체 + 옛 값 아카이브. 기본 출력 폴더는 메인 창 Output. Breaks 입력에 UTC 명시 + KST 환산 병기

## 3. Wavelength Calibration (ui_dialogs_calib.py:156-873, 런처 app_window_fitsetup.py:56-120)
- 무엇: Hg 램프 피크 → 픽셀↔파장 2차식, FWHM 기록, 메인 창에 적용
- 왜: 단계 버튼 1~4 번호, 클릭하면 ±10 px 스냅 + 가우시안 서브픽셀(:256-266), FWHM 창은 반치폭에서 자동(:452-458)
- 써본 결과:
  - 램프 CSV(61만 행) 로드 0.13 s
  - Auto Suggest는 피크 2개만(핏엔 최소 3쌍 필요)
  - 캔버스 클릭으로 156 px·1893 px 피크 추가, 같은 피크 재클릭 시 중복 행
  - 파장 칸에 "404,6565"(쉼표) → 그 쌍이 말없이 빠지고 남은 3쌍으로 R²=1.00000, 운영과 0.004 nm 차
  - 4쌍 잔차 ±0.0009 nm인데 UI엔 잔차 표시 없음, 운영 roi2와 최대 차 0.0039 nm
  - Fit을 누르면 우클릭으로 기록한 FWHM이 지워짐(:703)
  - Save & Apply 후: 바뀜 — win.wavelengths, engine.wavelengths(400.0425). 안 바뀜 — engine._wave_axis(400.0416), loaded_wl_path, 채널 wl_path, Alpha Generator가 쓰는 CH1 wavecal. 팝업 두 번
- [높음] Apply가 반만 적용(실측, app_window_fitsetup.py:60-77) — 알파 생성·R 계산·FitSet 저장이 옛 wavecal인데 팝업은 "applied to the system instantly"
- [높음] 잘못된 입력 말없이 무시(실측, :665-674)
- [높음] 품질 지표가 R² 하나(:684-694), 잔차·자유도 미표시 — 물리 > 통계 원칙 위배
- [중간] 저장 헤더에 재현 정보 없음(:794) — 쌍 목록·계수·램프 파일 없음. 운영 Calib 파일도 같아 어떤 피크가 어떤 Hg 라인이었는지 복원 불가. 파일명에 Hg·Poly2 하드코딩(:770)
- [중간] 표가 예고 없이 비워짐 — Auto Suggest는 표를 비우고(:635), Fit은 FWHM 기록 삭제, 중복 피크 허용
- [중간] Hg 라인 자동 배정 없음, 우클릭 FWHM 기능이 도움말에 없음
- [낮음] 팝업 2개, 결과도 모달 matplotlib 팝업으로 따로
- 개선: Apply는 `load_wavelength_cal(auto_path=저장경로)` 하나로 일원화. 라인별 잔차 표시, 쌍이 3개뿐이면 경고, 숫자 아닌 칸 있으면 핏 거부. 헤더에 쌍·계수·램프 경로, Hg 표준선 자동 배정

## 4. Reference Generator (reference_generator_dialog.py)
- 무엇: 문헌 단면적·HITRAN에 픽셀별 σ 동적 ILS 컨볼루션 → 레퍼런스, 저장하면 메인 창에 자동 등록
- 왜: 분산 덧셈 방식(:56-70), 문헌 FWHM은 파일명에서 자동 추정(:293-326), HITRAN 다운로드 HTTPS + 15 s 타임아웃(:371-418)
- 써본 결과:
  - 열기 시 T=298.15 K(메인 fallback 25 °C에서 온 값)
  - 입력 없이 Generate → 정상 경고
  - HITRAN H2O 생성 8.7 s 동안 메인 루프 8635 ms 정지(로컬 캐시 사용)
  - Auto-pickup(roi2) 정상, 팝업 2개, 컨볼루션 0.77 s(772 ms 정지)
  - 운영 roi2 H2O와 비교 r=0.99999998, 최대값 비 1.00006 → 운영 레퍼런스가 셀 온도(ANs 573 K)가 아니라 약 298 K로 만들어졌다는 뜻(툴팁은 573 K 권장, 헤더에 T가 없어 확정 불가)
  - NO2(Vandaele)는 운영과 상대오차 7×10⁻¹⁰ 재현
  - 자동 등록이 중복: "H2O-HITRAN"이 4번째로 추가, NO2도 중복 행. 같은 이름(NO2)은 Lock 시 엔진에서 덮여 실제 3종(실측), H2O-HITRAN은 이름이 달라 Lock하면 H2O 두 열(코드 추정)
  - 저장 파일은 1열 2048줄, 헤더엔 Gas·Math만
- [높음] 파장축·생성 조건 미저장(실측, :853-867) — T, P, 원본 파일, 문헌 FWHM, wavecal·FWHM 경로, git 해시 없음. 운영 레퍼런스도 같은 형식
- [높음] 자동 등록이 중복·공선 행 생성(실측, :870), 대체 여부 질문 없음
- [중간] HITRAN 생성·컨볼루션이 메인 스레드(실측 8.6 s, 0.8 s 정지), 첫 다운로드는 15 s 넘게 응답 없음
- [중간] 첫 다운로드가 저장소 안 hitran_data/에 씀(:399-405)
- [중간] T 기본값이 fallback 25 °C, 툴팁 권장 셀 온도와 다름(:146-150)
- [중간] QSettings 조직이 다름 — 다른 다이얼로그는 CAESAR, 여기만 DoasisLab/CAESARPro(:479)
- [낮음] 창 제목 "Deconvolution"인데 실제 연산은 컨볼루션
- [낮음] auto_load_lamp_data(:620-632) 죽은 코드인데 런처는 "✅ … auto-configured" 출력(app_window_fitsetup.py:38)
- [낮음] σ 외삽값이 0 이하면 그 픽셀은 컨볼루션 없이 그대로 샘플링(:663-685, 코드 추정)
- 개선: 2열 저장 + 헤더에 생성 조건 전부·해시(로더는 이미 2열 지원). 등록 시 같은 종이 있으면 대체/추가/취소 질문. 계산은 QThread로. T 기본값은 채널 셀 온도

## 5. Test Fit — Optimize / Preview / Explorer (test_fit_dialog.py, app_window_fitsetup.py:199-355)
- 무엇: Optimize 24스캔으로 파라미터 추천 → Apply로 적용. Preview 1스캔 핏. Explorer는 CLI 배치 실행·결과 검토 카드
- 왜: 자동 적용 금지(§15-E.4, :5-7), Center 모드 변환(§16, :124-158), |ac1|로 퇴화 판정 시 Apply 차단(§16-B, :654-668), Explorer 카드는 Apply 금지 계약 검증(:434-435)
- 써본 결과:
  - 열기 0.35 s, Preview는 창 생성 때 동기 계산, NO2=3.30 ppb
  - Optimizer 7.5 s(최대 정지 18 ms). 추천: poly 4→3, NO2 Center −6.07±2.07, squeeze ±0.0035, step 0.5, Link 정책. CV: CHOCHO 4530 %, H2O 13 %, NO2 53 %. Apply 활성, 누를 때 확인창 없음
  - CH1에서 최적화 → CH2 탭 → Apply → CH2 live 값·cfg2 ref_props 변경(cfg1 그대로)
  - 표시는 "recommended Limit -6.07, 2.07"인데 실제 적용은 Center [−8.14, −4.0]
  - 사유 "independent gain 0%("가 잘림 — `(<5%)`의 `<`가 HTML로 먹힘
  - 최적화 도중 창 닫기 3.01 s
  - Explorer dry-run 1.4 s, 출력 한글 모지바케, 결론 ABSTAIN, "Export V2" 버튼 항상 비활성
- [치명] Apply가 활성 채널에 적용(실측, app_window_fitsetup.py:345-355), 결과 데이터에 채널 정보 없음 → PNs가 ANs shift 창을 받아 조용히 틀린 농도 가능
- [높음] Apply 게이트가 T1·불변식뿐(실측, :715-730), T2는 표시만, T3 없음 — §15-B("T1 단독 심판 금지") 위반
- [높음] Center를 Limit으로 표기(실측, :672-677)
- [높음] Apply에 확인·diff·undo 없음(:732-737), §15-E.4 요구 "변화 % 근거" 누락
- [중간] 사유 텍스트 HTML 이스케이프 안 함(:549, :700, 실측)
- [중간] 창 닫으면 3 s 정지 후 terminate()(:1002-1013), 라이브 엔진을 스레드에서 공유해 재Lock과 경합 가능(코드 추정), subprocess 자식이 고아로 남을 수 있음(코드 추정)
- [중간] Explorer 출력 깨짐 — cp949 디코딩(:240-242, :261-262, 실측), `encoding="utf-8"` 필요
- [중간] Preview 갱신 안 됨(:940)
- [낮음] "24-scan"(버튼)과 "12-scan"(app_window_cavity.py:91, docstring :5, :271) 혼재, Export 버튼 죽음(:794-797), Preview "Shift"는 실제로 CHOCHO의 shift
- 개선: 결과에 채널 정보, 다른 채널 적용은 거부. Apply 전 diff·농도 변화 % 확인창 + undo. T2 실패 시 Apply 차단, T3 근거 없으면 "미검증" 배지. 실제 적용 형식으로 표기, 사유는 html.escape

## 6. Mask (ref_mask_dialog.py, app_window_fitsetup.py:498-523, engine.py:206-262)
- 무엇: 레퍼런스 범위 밖 픽셀을 0으로(Manual) 또는 피크 X % 미만을 0으로(Auto)
- 왜: 가장자리 잡음·겹치는 흡수대가 핏을 오염시키지 않게(:52-64)
- 써본 결과(Preview ppb, 원래 NO2 3.302):

| 조작 | 결과 |
|---|---|
| 기본값 "441-450"(px) | "Success", NO2 −1.3×10⁸⁸ |
| 재Lock | 원래 값 복귀(마스크 소실) |
| Auto 1 % | 효과 없음 |
| 역순 "900-600" | "Success", NO2 0 |
| "abc" | 형식 경고(정상) |
| H2O에 "430-460" | "Success", H2O 4.3×10⁷² |
| 채널 탭 왕복 | 마스크 소실 |

- [치명] 물리적으로 불가능한 결과에도 "Success"(실측), 기본값만으로 핏 붕괴, 마스크는 px인데 다른 곳 범위는 nm라 혼동, 범위 검증 없음(app_window_fitsetup.py:509-516)
- [높음] 마스크가 어디에도 기록 안 됨(실측·grep) — FitSet·결과 헤더에 없고 Lock·채널 전환 시 소실. Auto는 반복하면 누적(engine.py:222-237), undo 없음
- [중간] 미리보기 없음, 빨간 Mask 버튼에 툴팁 없음
- 개선: 마스크를 nm 단위 ref_props 항목으로 FitSet에 저장(기존 active_bands_nm과 통합 우선 검토), Lock 때 재적용 + 헤더 기록, 남는 픽셀 수·핏창 교집합 검증, 미리보기, 기본값 비움

## 7. Peak Trend (ui_peak_trend.py)
- UI에서 도달 불가(배선 해제, app_window_cavity.py:64-66). 메서드 이름만 스모크 테스트가 고정, 실행 안 함
- [낮음] 디버깅용 진입점을 남길지, CLI(tools/plot_spectra_by_date.py)로 일원화할지 결정 필요

## 8. 공통 평가
| | Alpha | R Cal | Wavecal | Ref Gen | Test Fit | Mask |
|---|---|---|---|---|---|---|
| 단계 안내 | 없음 | 없음 | 1~4 번호 | 1~4 그룹 | 탭 | 없음 |
| 진행 표시 | %바(비단조) | 무한바+경과 | – | 대기커서(8.6 s 동결) | 9단계 | – |
| 취소 | 없음 | 없음 | – | 없음 | 닫기=3 s 정지+terminate | – |
| 실패 표시 | 성공처럼 | 성공처럼 | 입력 무시 | 정상 | 정상 | 성공처럼 |
| 중간 닫기 | 계속 돌고 팝업 | terminate(npz 손상 위험) | – | – | 3 s 정지 | – |
- 버튼 색 하드코딩으로 다이얼로그마다 다름(예: #00796B ui_dialogs_r.py:249)
- 그래프 라이브러리 matplotlib·pyqtgraph 혼재(기존 보고와 같은 계열)

## 코드 리뷰
1. [치명] worker.py:2482-2483 vs :2500, :2503-2506 — `_block_average` 반환 개수 5 vs 6, He 없는 입력이면 채널 전체 실패 (실측, 코디네이터 재확인)
2. [치명] rt_precompute.py:533-542, :491-499 — 로드 실패 시 빈 누적으로 덮어씀, 667 → 1 knot (실측, 코디네이터 재확인)
3. [치명] app_window_fitsetup.py:345-355 + test_fit_dialog.py:732-737 — 추천 채널과 적용 채널 불일치 (실측)
4. [치명] app_window_fitsetup.py:509-523 + ref_mask_dialog.py:106 — 마스크 검증 없이 Success, NO2 −1.3e88 (실측)
5. [치명] ui_alpha_gen.py:425-434 / app_window_inputs.py:418-438 — 실패를 완료로 표시 (실측)
6. [높음] worker.py:2069-2073 — 예외 시 스풀 미정리, 주석(:2123-2127)과 모순 (실측)
7. [높음] app_window_inputs.py:234 — 폴백 roi 매핑 반대·하드코딩(단일 출처 위반) (실측)
8. [높음] app_window_fitsetup.py:60-77 — load_wavelength_cal을 부분 중복 구현해 엔진 축·경로 미갱신 (실측)
9. [높음] ui_dialogs_calib.py:661-674 — 파싱 실패를 삼키고 R²=1 (실측)
10. [높음] rt_precompute.py:195 + ui_dialogs_r.py:1065-1070 — 비원자 저장 중 terminate()면 잘린 npz → 2번으로 연결 (코드 추정, 구성 요소 2번은 실측)
11. [높음] rt_precompute.py:563-572 — 중복 knot은 옛 값 유지, config만 새 값 (실측)
12. [높음] test_fit_dialog.py:672-677 — Center를 "Limit"으로 표기 (실측)
13. [높음] ui_alpha_gen.py:323 — 콜드 → ANs 탭 기본 매핑 (실측)
14. [중간] app_window_inputs.py:194-211 — 알파 상태가 단일 속성이라 동시 실행이 섞임 (실측)
15. [중간] ui_dialogs_r.py:170, :519-526, :684-688 — 기본 출력 ".", 읽기 전용 기능도 폴더 생성 (경로 해석 실측, 폴더 생성은 코드 추정)
16. [중간] test_fit_dialog.py:549, :700 — HTML 이스케이프 누락 (실측)
17. [중간] test_fit_dialog.py:240-242, :261-262 — subprocess 출력 디코딩 (실측)
18. [중간] test_fit_dialog.py:1002-1013, ui_dialogs_r.py:1065-1070 — quit() 무효, wait(3000) 후 terminate() (3 s 정지 실측, Esc가 closeEvent 우회는 코드 추정)
19. [중간] reference_generator_dialog.py:386-447, :637-727 — 메인 스레드 계산 8.6 s, 0.8 s 정지 (실측)
20. [중간] reference_generator_dialog.py:399-405 — 저장소 안 hitran_data/에 씀 (코드)
21. [중간] engine.py:206-237 + lock_ref — 마스크가 메모리에만 있다 소실, Auto 누적 (실측)
22. [중간] r_workers.py:259-289, ui_dialogs_r.py:823 — 실패를 "no new files", "R(t) saved"로 표시 (실측)
23. [낮음] 죽은 코드·틀린 주석: reference_generator_dialog.py:620-632 + 런처 print(app_window_fitsetup.py:38), test_fit_dialog.py:794-797, "12스캔" 표기(test_fit_dialog.py:5, :271, app_window_cavity.py:91), app_window_inputs.py:299, worker.py:2123-2127 (실측·grep)
24. [낮음] 닫은 창 미해제 — AlphaGeneratorDialog는 exec 후 해제 없음(app_window_inputs.py:398-399), TestFit은 show()인데 WA_DeleteOnClose 없음(app_window_fitsetup.py:210) (코드 추정)

## 잘한 점
- 알파 입력 파일명 가드: 실제 사고에서 나온 방어선, 이번에도 정확히 작동
- 알파 헤더 풍부: git 해시, purge_settle, clock_epoch, T_P_PROVENANCE, R 출처·knot 수
- 알파 생성 성능: 병렬 + 캐시로 GUI 정지 ≤42 ms, 상태줄이 무엇을 왜 제외했는지 사람 말로 설명
- Reference Generator 재현성: NO2 7×10⁻¹⁰, H2O r=0.99999998, 오프라인 대응(HTTPS, 타임아웃, 로컬 캐시)
- Test Fit 구조: 추천·적용 분리, Center 변환으로 불변식 보호, 판단 근거 표, 퇴화 차단, 7.5 s 스레드 처리, Explorer는 Apply 금지 계약 검증
- R Calibrator 데이터 가드: 날짜 0개 가드, 트렌드 dat 덮어쓰기 금지, 즉시 끝나는 Verify, 계단 가드 — npz에만 같은 가드가 빠짐
- Wavecal 정확도·안내: 운영 값을 0.004 nm 안에서 재현, 번호 매긴 단계 버튼이 이 섹터에서 가장 명확한 안내
- 모든 다이얼로그 최소 크기가 1366×768에 들어감
