# 디자인 정체성 시안 (2026-10-03) — 브랜치 `design/identity-2026-10`

사용자 요청: "Augur 가 너무 단조롭다", Vigil 도 같이. **main 에 병합 안 됨 — 사용자 확인 대기.**

## 한 것
**Augur** (gui/theme.py, gui/app_window.py, app_window_cavity.py, app_window_results.py, ui_result_viewer.py)
- 스플래시의 정체성을 본체로: 앱 글꼴 IBM Plex Sans(+맑은 고딕), 섹션 제목 Spectral 세리프
  (QSS `QGroupBox` 에 세리프 + `QGroupBox *` 로 본문 글꼴 복원 — `::title` 은 글꼴을 못 바꾼다).
- RUN = 잉크 바탕 주 버튼, 탭 = 주홍 밑줄, 진행 막대 = 따뜻한 회색, 표 머리 = 종이 톤.
- 상단 머리띠(`_build_header_band`): 엠블럼 · AUGUR 워드마크 · 태그라인 · 1–4 단계 칩(끝나면 주홍 ✔,
  현재는 잉크 테두리) · 캠페인. 좁으면 태그라인을 숨기고 칩을 숫자로.
- Setup Status 줄을 색 배경 칩으로. ✓ 는 Plex 에서 "√" 로 보여 ✔(U+2714, Segoe UI Symbol) 로.
- pyqtgraph 기본 배경을 종이 표면색으로, Result Lab 그래프도.

**Vigil** (vigil/dashboard/dashboard_window.py, gui/theme.py)
- 배지: OK 면 가는 한 줄, P2/P1/P0 일수록 크게(`_BADGE_SIZE`).
- P0/P1 이면 **창 전체 테두리** 4 px 경보색(`#vigilRoot`).
- 값 카드를 계통별로 묶고 캡션(GAS · MIRROR · LIGHT · CELL · CLOCK, `_relayout_cards`).
- 곡선 굵기 1→2, 격자 흐리게, 축 글자 밝게.

## 미해결 (다음 사람이 할 일)
1. **FHD 에서 머리띠 단계 칩이 숫자/✔ 만 나온다**(이름이 안 보임). `_paint_steps` 의 `short` 판정이
   `_band_width < 1000` 인데 FHD 에서도 short 로 그려진다 — `_Band.resizeEvent` 가 `_grp_ref` 생성 전에만
   불리거나, 마지막 `_refresh_step_marks` 가 resize 전에 돈 것으로 의심. 작은 화면(1366@150)에선 정상.
   확인: `python shoot_data.py 1920 1080 1 fhd` 후 머리띠 크롭.
2. 사용자 검토 후 main 병합 여부 결정. 테스트(pytest)는 이 브랜치에서 아직 안 돌렸다.

## 화면 찍는 법 (이 폴더의 스크립트, 실제 창을 화면 밖에 띄워 grab)
    PYTHONIOENCODING=utf-8 python shoot_augur.py 1920 1080 1 fhd          # 빈 상태
    PYTHONIOENCODING=utf-8 python shoot_data.py 1366 768 1.5 small run    # FitSet+05-20 알파 로드(+Fast 런)
    ALARM=1 PYTHONIOENCODING=utf-8 python shoot_vigil.py 1366 768 1.5 data E:/Yeosu_2026/CAESAR_Hot/2026-06/2026-06-01-003.dat
    python measure.py 1.5        # 1366×768@150 % 에서 창·패널 최소폭
결과는 `%TEMP%\ux3\shots\`. shoot_data 는 C:\Doasis_Work\Output 의 FitSet·60s 알파를 쓴다(경로는 스크립트 안).
