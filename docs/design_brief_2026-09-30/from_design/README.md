# Handoff: Augur · Vigil 부팅 스플래시

## Overview
대기화학 연구실 계측 소프트웨어 두 개(ARGUS 가족)의 부팅 스플래시.
- **Augur** — 측정 스펙트럼을 기체별 농도로 확정하는 분석 프로그램. 밝은 종이 + 잉크.
- **Vigil** — 측정 PC에서 계속 켜져 농도를 실시간으로 보여 주고 하드웨어를 감시하는 프로그램. 어두운 배경 + 청색 등불.

두 스플래시는 같은 구조를 공유한다: 위쪽 = 엠블럼(입력) → 결과물(출력) 장면, 가운데 = 워드마크 + 약어 부제 + 버전, 아래 = 진행선 + 부팅 로그, 우하단 = `ARGUS · CAESAR`.

## About the Design Files
이 폴더의 `.dc.html` 파일은 **HTML로 만든 디자인 레퍼런스**다. 모양과 동작을 보여 주는 프로토타입이며, 그대로 배포할 코드가 아니다. 과제는 이 디자인을 **PyQt6 `QSplashScreen` + `QPainter`**(브리프의 대상 환경)로 다시 구현하는 것이다. 브라우저에서 파일을 열면(같은 폴더의 `support.js` 필요) 애니메이션을 볼 수 있고, 클릭하면 마지막 프레임으로 건너뛴다. 각 파일 하단 `<script>`의 `renderVals()`에 모든 타이밍·좌표 계산이 있다.

## Fidelity
**High-fidelity.** 색, 서체, 좌표, 타이밍은 최종값이다. 좌표는 560 × 390 px 캔버스 기준 절대 좌표.

## 공통 제약 (브리프)
- 크기 560 × 390 px, 벡터(선·다각형·원·텍스트)만. 그라데이션·비트맵 없음.
- 모션 **1.3 s** 안에 끝나고 마지막 프레임에서 정지. 클릭하면 즉시 마지막 프레임.
- **부팅 로그는 실제 정보**: 실제로 끝난 단계만 한 줄씩 찍는다. 상태 `ok` / `skip` / `fail`. 최대 6줄.
- 부제에서 약어 머리글자(A·U·G·U·R / V·I·G·I·L)를 강조색 굵게.
- 추천 구현: `QTimer`(~16 ms)로 t 를 0→1.3 s 증가, 매 프레임 `renderVals(t)` 와 같은 계산 후 `repaint()`.

### 이징
- `ease(v) = 1 − (1 − clamp(v))³` (ease-out cubic)
- `back(v)`(오버슈트) = `1 + (c+1)(v−1)³ + c(v−1)²`, c = 2.2 (Vigil 등불)

### 공통 하단 레이아웃 (두 화면 동일)
| 요소 | 위치 | 스타일 |
|---|---|---|
| 워드마크 행 | left 30, top 188, baseline 정렬, gap 16 | 아래 각 앱 참고 |
| 진행선 트랙 | left 30 → right 30, y 240, 1 px | Augur `#D8D3C7` / Vigil `#1C2333` |
| 진행선 채움 | 폭 = 500 × t/1.3 | Augur `#1A1D24` / Vigil `#6E7686` |
| 부팅 로그 | left 30, top 252, 줄 간격 12 + gap 3 | IBM Plex Mono 10.5 px. 상태 열 폭 28 + gap 18. 상태 weight 500 |
| 로그 등장 | 줄 i 가 t ≥ 0.15 + 0.2·i 에 표시 | (실제 앱: 단계 완료 시점) |
| `ARGUS · CAESAR` | right 30, bottom 16 | Plex Mono 9 px, letter-spacing 0.12em |

---

## Screen 1 — Augur (`AugurSplash.dc.html`)

**배경** `#F4F1EA`, 기본 잉크 `#1A1D24`.

### 장면 (위쪽 0–180 px)
1. **입력 스펙트럼** — 폴리라인, x 28→128 (1.5 px 간격), `y = 105 + 7·sin(x/3.1)·sin(x/11) + noise(±1.5)`. stroke `#1A1D24` 1.6 px, round join/cap. **0–0.30 s** 에 왼쪽부터 점 개수를 늘려 그림(ease).
2. **육각 프리즘** (엠블럼) — 채움 육각 `152,79 174.5,92 174.5,118 152,131 129.5,118 129.5,92` fill `#1A1D24`. 안쪽 육각 `152,88 166.7,96.5 166.7,113.5 152,122 137.3,113.5 137.3,96.5` stroke `#F4F1EA` 1.1. 가운데 점선 y 105, x 138→(138+28·ease((t−0.32)/0.12)), dash 2.5/2. 전체 불투명도 ease((t−0.22)/0.15).
3. **갈래(레퍼런스 개수 K 만큼)** — 시작 (176,105) → 끝 (294, yᵢ). 길이 u = ease((t − 0.42 − 0.035·i)/0.24) 로 뻗음. stroke 2.6 px(K ≤ 4) / 2 px(K > 4), round cap.
4. **농도 행** — left 302, 행 중심 yᵢ. 구성(gap 10, baseline):
   - 기체명: Spectral 700, 13 px(K ≤ 4) / 11.5 px, 폭 66, 색 = 갈래 색
   - 값: Plex Mono, 19 px / 14 px, 폭 62 오른쪽 정렬
   - `± 불확도` Plex Mono 10 px `#6B6F78`, 단위 10 px `#9A9A96`, `✓` 10 px `#B4473A`
   - 행 등장 ease((t − 0.58 − 0.03·i)/0.1)
   - **확정 연출**: lockᵢ = 0.78 + i·min(0.12, 0.34/(K−1)) 전에는 값이 매 프레임(40 fps 기준) 무작위로 흔들림(회색 `#9A9A96`, weight 400). lockᵢ 이후 최종값, `#1A1D24` weight 600, ✓ 표시.

### 레퍼런스 개수 대응
- 행 간격 `gap = min(34, 126/(K−1))`, 중심 y 105 기준 대칭(`y0 = 105 − gap·(K−1)/2`).
- **0개**(프로파일 없음): 한 행 `σ`, 값 `—`, 색 `#9A9A96`.
- **1–6개**: 모두 표시.
- **7개 이상**: 앞 5개 + 여섯째 행 `+n` `more`(회색, ✓ 없음).
- 갈래 색 순서: `#3B63B5` `#5B4FA6` `#7E4A86` `#4C6A7C` `#2F7A8C` `#6A5D9E`

### 데이터 출처
- 기체명: 지난 세션 파일에서 읽음(아래 제안). `NO2 → NO₂` 식 아래첨자 변환은 스플래시에서.
- 숫자: **장식용**(스플래시는 아트). 형식만 맞춘 고정값을 쓴다. 목업 기본값: NO₂ 8.42±0.11 ppb, CHOCHO 0.186±0.021 ppb, H₂O 1.27±0.04 %, O₄ 0.98±0.03 rel.

### 워드마크 행
- `AUGUR` Spectral 700 30 px, letter-spacing 0.12em. 불투명도 ease((t−0.3)/0.3).
- 부제 Spectral italic 11.5 px `#4A4E57`: "**A**nalyzer of **U**nseen **G**ases **U**sing **R**esonators" — 머리글자 roman 700 `#B4473A`.
- 버전 `v0.2.0` 우상단 right 30, top 16, Plex Mono 10 px `#6B6F78`.
- 로그 상태색: ok `#1A1D24`, skip `#9A9A96`, fail `#B4473A`. 메시지 `#3B3F48`.

---

## Screen 2 — Vigil (`VigilSplash.dc.html`)

**배경** `#0B0F1A`, 선·글자 `#DCE1EA`, 브랜드(등불) `#7FC3F0`.
브랜드색은 경보색(OK 초록 · P2 노랑 `#B36B00` · P1 주황 `#E65100` · P0 빨강)과 겹치지 않는 청색 계열만 쓴다.

### 장면
1. **기준선** y 100, x 30→530, `#161D2B` 1 px.
2. **엠블럼 맥박선** — 꼭짓점 `(30,100) (70,100) (78,112) (86,88) (96,60) (106,126) (114,100) (150,100)`, stroke `#DCE1EA` 3.4 px round. **0–0.32 s** 에 경로 길이 비율로 그림.
3. **등불** — 중심 (96,44). 맥박선이 R파 꼭대기(꼭짓점 4)에 닿는 시각 tₚ 부터: 채움 원 r = 9·back((t−tₚ)/0.25) `#7FC3F0`, 안쪽 링 r = 5·같은 값 stroke `#0B0F1A` 1.2. 빛 링 r 9→25, 불투명도 0.8→0, 0.45 s.
4. **실시간 트레이스** — x 150→(150 + 380·ease((t−0.3)/0.35)). 주기 64 px 박동이 왼쪽으로 흐름(phase = (t−0.3)·90 px/s). `m = (x+phase) mod 64`, `y = 100 + 0.6·sin(u/5.3) − 14·g(m,32,1.4) + 4·g(m,36,1.6) − 2·g(m,22,3)`, g = 가우시안 exp(−((x−c)/w)²). stroke `#DCE1EA` 1.4, 불투명도 0.75. 머리에 점 r 3 `#7FC3F0`.
5. **감시기 상태등 5개** — top 136, left 30 → right 30 균등 배치(space-between). 각: 점 9 px + 이름(Plex Mono 10.5 `#B4BAC6`) + `ok`(600, 점과 같은 색).
   - 순서/색/음: ingest `#7FC3F0` 880 Hz · HK `#8FA8F5` 988 · R `#A99BF0` 1109 · lamp `#6FD0DA` 1175 · conc `#B7C7DA` 1319
   - i번째가 t = 0.62 + 0.07·i 에 켜짐: 불투명도 0.18 → 1, 링 9→23 px(0.35 s, 0.9→0), `ok` 표시, 짧은 삐 소리(사인파, 60 ms, 게인 0.1).
   - 소리는 옵션(기본 끔). Qt: `QSoundEffect`.
6. **LIVE 시계** — right 30, top 16. 점 6 px `#7FC3F0`(모션 중 4 Hz 깜빡임, 정지 후 켜짐) + `LIVE HH:MM:SS`(실제 PC 시각) Plex Mono 10 `#8A93A3`. 등장 ease((t−0.35)/0.2).
   - 실제 경보 상태에서 이 점의 색을 바꾸지 말 것(스플래시는 평상시 화면).

### 워드마크 행
- `VIGIL` IBM Plex Sans 600 28 px, letter-spacing 0.24em.
- 부제 Plex Sans 11 px `#8A93A3`: "**V**ital-signs **I**nspector for **G**as **I**nstruments, **L**ive" — 머리글자 600 `#7FC3F0`.
- 버전 `v0.0.1` Plex Mono 10 px `#6E7686`, 부제 오른쪽.
- 로그 상태색: ok `#7FC3F0`, skip `#6E7686`, fail `#E5484D`. 메시지 `#B4BAC6`.

---

## 엠블럼 (흑백, 앱 밖 사용)
- `emblem_augur.svg` — 육각 프리즘: 입력선 → 채움 육각(흰 안쪽 육각 + 점선) → 네 갈래.
- `emblem_vigil.svg` — 박동 위의 불빛: 채움 원(흰 안쪽 링) + R파가 솟은 맥박선.
- ARGUS 엠블럼과 같은 굵은 흑백 계열. 색은 앱 안에서만 입힌다.
- 앱 아이콘은 이 엠블럼을 32 px 이하에서 단순화(Augur 갈래 2개, Vigil 삼각 봉우리)한다. 개요 파일의 TURN 3 섹션 참고.

## Design Tokens
**Augur**: 종이 `#F4F1EA`, 잉크 `#1A1D24`, 보조 `#4A4E57`, 회색 `#6B6F78`, 연회색 `#9A9A96`, 구분선 `#D8D3C7`, 브랜드 주홍 `#B4473A`, 성분 `#3B63B5 #5B4FA6 #7E4A86 #4C6A7C #2F7A8C #6A5D9E`
**Vigil**: 밤 `#0B0F1A`, 글자 `#DCE1EA`, 보조 `#8A93A3`, 로그 `#B4BAC6`, 흐림 `#6E7686`, 구분선 `#1C2333`, 푸터 `#4A5264`, 등불 `#7FC3F0`, 감시기 `#7FC3F0 #8FA8F5 #A99BF0 #6FD0DA #B7C7DA`, fail `#E5484D`
**서체**: Spectral(700, italic 400) · IBM Plex Sans(400/600) · IBM Plex Mono(400/500/600). 모두 OFL. 앱에 번들하고 `QFontDatabase.addApplicationFont` 로 등록.

## State / 데이터
- 스플래시 입력: `t`(경과 시간), 부팅 로그 배열(실제 단계 결과), Augur 는 기체명 목록.
- 제안: `%APPDATA%/Augur/last_session.json`
  ```json
  { "profile": "hot", "window_nm": [427, 473], "species": ["NO2", "CHOCHO", "H2O", "O4"] }
  ```
  fit 설정 확정·종료 시 덮어쓰고, 스플래시 직전에 이 파일만 읽는다. 없거나 깨지면 σ 대체 — 스플래시는 절대 실패하지 않게.

## Files
- `AugurSplash.dc.html` — Augur 스플래시 (원본: `AugurSplash9.dc.html`, 개요의 11a)
- `VigilSplash.dc.html` — Vigil 스플래시 (원본: `VigilSplash11.dc.html`, 개요의 11b)
- `support.js` — 위 HTML 을 브라우저에서 열기 위한 런타임 (구현에는 불필요)
- `emblem_augur.svg`, `emblem_vigil.svg` — 흑백 엠블럼
