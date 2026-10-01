# fonts/ — Augur·Vigil 브랜드 서체 (2026-10-01)

디자인 브리프(`docs/design_brief_2026-09-30/from_design/README.md` "Design Tokens")가 정한 서체.
설치하지 않고 앱이 시작할 때 `gui/theme.py` `register_fonts()` 가 등록한다 — 다른 PC·현장 exe 에서도
같은 모양이 나온다(`Vigil.spec` 이 이 폴더를 통째로 싣는다).

| 서체 | 파일 | 쓰는 곳 | 출처 |
|---|---|---|---|
| Spectral 400 · 700 · 400 italic | `Spectral-*.ttf` | Augur 워드마크·부제 | google/fonts `ofl/spectral` |
| IBM Plex Sans 400 · 600 | `IBMPlexSans-*.ttf` | Vigil 화면 글꼴·워드마크 | IBM/plex `packages/plex-sans/fonts/complete/ttf` (Google 판은 가변 폰트뿐이라) |
| IBM Plex Mono 400 · 500 · 600 | `IBMPlexMono-*.ttf` | 부팅 로그·대시보드 로그 | google/fonts `ofl/ibmplexmono` |

**라이선스**: 모두 SIL Open Font License 1.1 — 재배포·번들 허용, 서체만 따로 팔면 안 됨.
`OFL-Spectral.txt`, `OFL-IBMPlex.txt` 를 함께 두어야 한다(지우지 말 것). "Plex" 는 IBM 의 예약 서체명이라
글꼴 파일을 고쳐 다시 배포할 땐 이름을 바꿔야 한다(그대로 싣는 건 상관없음).

한글 글리프는 이 서체들에 없다 — Qt 가 글자 단위로 시스템 서체(맑은 고딕)로 넘긴다.
