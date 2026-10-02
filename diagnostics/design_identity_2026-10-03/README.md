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
- 격자 흐리게, 축 글자 밝게. (곡선 굵기 1→2 는 되돌렸다 — 꽉 찬 그래프에서 그리기가 틱의 99 % 라는
  실측 때문에 width-1 이 성능 가드(`vigil/test_dashboard_vf2.py` [5])로 묶여 있다.)

## 고친 것 (2026-10-03 후속)
1. ~~FHD 에서 머리띠 단계 칩이 ✔ 만 나온다~~ — 원인은 short 판정이 아니라 칩·캠페인 라벨의
   `QSizePolicy.Ignored`. Ignored 는 sizeHint 를 0 으로 만들어, 공간이 넉넉하면(FHD) 레이아웃이 남는 폭을
   전부 stretch 에 주고 칩 자리는 0 — 위젯은 최소폭(111 px)으로 그려지지만 서로 겹친다(item x 간격 29 px).
   좁은 화면에선 공간이 빠듯해 최소폭이 강제되니 멀쩡해 보였다. 기본 Preferred 로 — 최소폭은 여전히
   `_paint_steps` 의 명시값이 정한다. 캠페인 표시도 같은 이유로 화면 밖에 밀려 있었다.
2. Vigil 카드 묶음이 튜플 아닌 키(테스트의 int)에서 죽던 것 → "other" 묶음.
3. 이 폴더의 measure/shoot 스크립트를 `main()` 으로 — 최상위 실행이 `ci_import_smoke` 를 segfault 시켰다.

## 미해결
- 사용자 검토 후 main 병합 여부 결정.

## 화면 찍는 법 (이 폴더의 스크립트, 실제 창을 화면 밖에 띄워 grab)
    PYTHONIOENCODING=utf-8 python shoot_augur.py 1920 1080 1 fhd          # 빈 상태
    PYTHONIOENCODING=utf-8 python shoot_data.py 1366 768 1.5 small run    # FitSet+05-20 알파 로드(+Fast 런)
    ALARM=1 PYTHONIOENCODING=utf-8 python shoot_vigil.py 1366 768 1.5 data E:/Yeosu_2026/CAESAR_Hot/2026-06/2026-06-01-003.dat
    python measure.py 1.5        # 1366×768@150 % 에서 창·패널 최소폭
결과는 이 폴더의 `shots/`(커밋 안 함). shoot_data 는 C:\Doasis_Work\Output 의 FitSet·60s 알파를 쓴다(경로는 스크립트 안).
