# Changelog

이 파일은 릴리즈 태그(`git tag vX.Y.Z`)를 찍을 때마다 갱신한다.
버전 번호 규칙: `core/__version__.py` 참조.

## 릴리즈 체크리스트 (태그 찍기 전 매번)

1. `core/__version__.py`의 `__version__` 값을 새 버전으로 올린다
2. `python tools/validate_pipeline.py` 실행 → FAIL 0 확인
   (raw 파싱 / 웨이브칼 / 레퍼런스 ILS / Rayleigh 물리 / R 값 / 핏 출력 —
   하나라도 FAIL이면 태깅 중단하고 원인부터 고친다. 외부 대조 데이터가
   없는 머신에선 raw 파싱·핏 출력이 SKIP으로 뜰 수 있음 — SKIP은 허용,
   가능하면 데이터 있는 머신에서 6 PASS로 확인)
3. 의존성이 바뀌었으면 `pip freeze > requirements-lock.txt` 갱신
4. 이번 버전에서 뭐가 바뀌었는지 아래에 새 항목으로 추가(검증 결과 포함)
5. 커밋 → `git tag -a vX.Y.Z -m "..."` → `git push origin main --tags`

## v0.2.0 — 2026-06~07 누적 기능 + 전수조사 + 미팅 문서 세트

- **기능**: 📅 날짜 로더(dlg_date_load — Result Lab·Plot Maker 공용, 기간선택→
  일별 자동머지), 알파 생성 입력 화이트리스트(YYYY-MM-DD-NNN — 2026-07-09
  알파 오염사고 재발 방지), Plot Maker 확장(라벨스타일 pg/mpl 패리티·
  TimeShift 표시전용·CustomResample·X패딩 분리), R Calibrator UX(증분 npz·
  Verify), 일별 저장 마이그레이션 도구(migrate_fitting_daily, 바이트검증),
  알파 Pass1 캐시 모듈 뼈대(alpha_cache)
- **전수조사(2026-07-14)**: 전 모듈 감사 — 코어 물리/피팅 이상 없음 확인,
  ±Neg/QC 툴팁-기본값 불일치 교정, README 드리프트 3건 수정, 미수정
  잠재이슈 5건 문서화(docs/전수조사_2026-07-14.md)
- **문서 세트**: 프로그램 소개(논문 스타일)·핵심개념 스터디노트·미팅
  디스커션 아젠다·소프트웨어 개선 로드맵(문헌 벤치마크 기반)
- **검증**: validate_pipeline 4 PASS·0 FAIL·2 SKIP(외부 대조 데이터 없는
  머신이라 raw 파싱·핏 출력 실행 불가 — 코드 문제 아님),
  validate_plotmaker 24/24 PASS. 의존성 변경 없음(requirements-lock 그대로)

## v0.1.0 — 패키징 1단계: 경로 이식성 + 버전 태깅

- 다른 컴퓨터에서 clone만으로 돌아가도록 절대경로 하드코딩 제거
  - `gui/app_window.py`의 `C:\Doasis_Work\Output\...` 폴백 경로 3곳 → `core/paths.py` 기반 상대경로
  - `scenarios/Doctor_Scenario_Cold_ROI1_ROI2.json`의 레퍼런스/파장보정 경로를 저장소 상대경로로 전환
  - 문헌 단면(`reference_data/raw/`)과 파장보정 상수(`reference_data/wv_cal/`)를 저장소에 번들
- 사람이 읽는 릴리즈 버전(`core/__version__.py`, SemVer) 도입 — 스플래시/창 제목에 표시
  (결과 파일에 스탬프되는 git 해시 기반 정밀 버전은 `core/provenance.py`, 그대로 유지)
- HITRAN fetch에 소켓 타임아웃(15s) 추가 — 오프라인 환경에서 GUI 무한 정지 방지
- `requirements.txt` 버전 고정(`>=`→`==`), `requirements-lock.txt` 추가 — 이 버전
  검증에 쓰인 정확한 패키지 조합 기록
- **검증**: `tools/validate_pipeline.py` 6/6 PASS (raw 파싱·웨이브칼·레퍼런스 ILS·
  Rayleigh 물리·R 값·핏 출력 전부 통과, 회귀 없음)
