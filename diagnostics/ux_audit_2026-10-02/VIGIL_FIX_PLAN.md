# Vigil 수정 계획 (2026-10-02, 점검 vigil_v1_ingest.md · vigil_v2_monitors.md · vigil_v3_dashboard.md 기반)

원칙: Augur FIX_PLAN.md 와 같다(재현 테스트 먼저, 수정 단위 커밋, push 안 함, 모든 브랜치는 `fix/integration` 위).
Vigil 고유 원칙(설계 §2): raw 는 읽기만, 감시기는 죽지 않는다, 자동·무개입 — 그리고 **"감시하지 않는 상태"는 반드시 보여야 한다.**

## 묶음

| 묶음 | 파일 | 내용 |
|---|---|---|
| VC 농도 단위(진행 중) | core/physics.py, gui/worker.py(α 식만), tools/reflectance_calc.py, vigil/monitors/conc_monitor.py(+test), r_monitor.py(omr_d 노출) | 미커밋 09-23 수정 이식(bbceas_alpha 단일 출처, Augur 비트 동일 증명), R 없으면 SKIP, purge_settle 60 s |
| VF1 유입·liveness·커서·경보 | vigil/watcher.py, ingest_cursor.py, monitors/liveness_monitor.py, alert_engine.py, run_vigil.py(liveness·tick 처리부) | ① liveness 는 라우팅된 행만 ② 행을 못 본 SKIP 이 N초(예 60 s) 넘으면 P0 "raw 가 안 들어옴" ③ aggregate: 평가 0개면 SKIP/P2, "OK k/n · 미평가 m" ④ 커서 손상 내성(.bad 이동+WARNING, 모양 검증), 없는/폴더 밖 항목 정리, indent 없이 저장 ⑤ 빈 감시 폴더면 루트 얕은 나열(첫 파일 30 s → 1–2 s) ⑥ 핫/콜드 같은 파일명 거짓 경고 제거 ⑦ 처리 중 예외로 버린 행 수 로그 ⑧ 미지 열수 파일 수를 P2 로 |
| VF2 대시보드·운용 | vigil/dashboard/dashboard_window.py, record.py, state_log.py, Vigil_실행.bat | ① 배지에 원인+행동 한 줄 ② 닫기 확인창 ③ 시작·종료 lifecycle 줄(status.jsonl) ④ bat 에 --autostart ⑤ 일시정지 중 신선도 "paused" ⑥ 경보표 서명 버그(최근 50건) ⑦ ★·⏸ 글리프 ⑧ HK 그래프 단위 분리 또는 % 정규화 ⑨ 변화 없으면 setData 생략·실시간 곡선 antialias 끔 ⑩ 표 머리글·Log·status.jsonl tz 표기 ⑪ vrec 파일 분할(열 변경마다 새 파일) ⑫ 1366×768@150 % 최소폭(경로 elide) ⑬ P0 지속 시 재알림 |
| VF3 HK·R·프로파일(VC 뒤) | core/profile.py, vigil/monitors/hk_monitor.py, r_monitor.py, profiles/*.json | ① sentinel 0 → 결측(raw_parser._is_sentinel 단일 출처), 결측 P2, tempcell2=0 °C 가 농도·R 에 안 들어가게 ② HK 밴드 히스테리시스 ③ R 은 He 뒤 인접 ZA 와 짝 ④ 기준선 축적 중 SKIP ⑤ 핫 rms_sig_alarm 0.15 → 콜드 처방(실측 재설정) ⑥ 프로파일 의미 검증(rel 범위·밴드·roi 순서·키·id), jsonschema 없으면 경고 ⑦ HK IndexError 가 tick 전체를 버리지 않게 ⑧ 같은 열수 프로파일 2개면 경고 |
| VF4 §1.4 시각 감시(마지막) | watcher/liveness + core 시각 디코딩 | row_time 을 clock_epoch 보정 포함 단일 함수로 → 지연·역행·도약 P2, rollover 지연, 헤더만 있는 파일. 오경보 위험이 있어 P2 로 시작 |

## 진행 기록
- 2026-10-02: VC 에이전트 진행 중(fix/vigil-conc). VF1·VF2 착수.
- 2026-10-02 15:00 origin/main(39c400f) 확인 — 다른 세션이 fix/integration·fix/vigil-conc 를 main 에 병합·push 하고
  리뷰 수정을 더했다. **이미 완료:** VC 1–2(b146d84 bbceas_alpha 단일 출처, 02310bb 농도 단위·R 없으면 SKIP),
  VF1 ④ 커서(1b8818c), VF3 ⑦ 짧은 행(f9e442a), VF2 ⑥ 경보표 서명(0707899), 1분 기록 정전 복구(57e4ebc),
  핫 프로파일 날짜 범위·밖이면 P2 NOT monitored(f011538), 채널별 cavity T/P 센서 목록 + 결측 규약(7370d83, VF3 ① 일부),
  레이아웃 단일 출처(39c400f).
- **남은 것** — VC 3–4(퍼지 직후 제외, 재생 검증), VF1 ①②③⑤⑥⑦(버린 행 로그)⑧, VF2 ①–⑤⑦–⑬, VF3 ②–⑥⑧, VF4.
  워크트리를 origin/main 기준으로 다시 만들었다(fix/vf1-ingest, fix/vf2-dashboard, fix/vc-purge).
  메인 체크아웃(C:\GHL\CAESAR)은 다른 세션이 origin/main 병합 중(MERGE_HEAD) — 건드리지 않는다.
- 2026-10-03 — VF3 ② HK 히스테리시스, ③ R 인접 ZA·He 짝(실데이터 05-20 확인), ⑥ 프로파일 의미 검사·jsonschema 없음 경고,
  ⑧ 같은 열수 모호 프로파일 경고 (커밋 7434f2c d9d7116 684c8f1). 남은 것: VF3 ④ 기준선 축적 중 SKIP, VF4 나머지(역행·도약·rollover·헤더만), 3단계 UX.
