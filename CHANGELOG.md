# Changelog

이 파일은 릴리즈 태그(`git tag vX.Y.Z`)를 찍을 때마다 갱신한다.
버전 번호 규칙: `core/__version__.py` 참조.

## v0.1.0 — 패키징 1단계: 경로 이식성 + 버전 태깅

- 다른 컴퓨터에서 clone만으로 돌아가도록 절대경로 하드코딩 제거
  - `gui/app_window.py`의 `C:\Doasis_Work\Output\...` 폴백 경로 3곳 → `core/paths.py` 기반 상대경로
  - `scenarios/Doctor_Scenario_Cold_ROI1_ROI2.json`의 레퍼런스/파장보정 경로를 저장소 상대경로로 전환
  - 문헌 단면(`reference_data/raw/`)과 파장보정 상수(`reference_data/wv_cal/`)를 저장소에 번들
- 사람이 읽는 릴리즈 버전(`core/__version__.py`, SemVer) 도입 — 스플래시/창 제목에 표시
  (결과 파일에 스탬프되는 git 해시 기반 정밀 버전은 `core/provenance.py`, 그대로 유지)
- `requirements-lock.txt` 추가 — 이 버전 검증에 쓰인 정확한 패키지 조합 기록
