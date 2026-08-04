# CLAUDE.md — Augur / CAESAR 저장소 가이드

> 이 파일이 있는 위치가 저장소 루트다 (`C:\Doasis_Work\CAESAR\CAESAR`).
> **바깥에 이름이 같은 `CAESAR` 폴더가 하나 더 있다** — 그건 이 저장소를 담는 부모 폴더일 뿐,
> git 저장소가 아니다. `git status`가 이상하면 `pwd`부터 확인.

## 뭘 만드는 저장소인가

- **Augur** (구 "CAESAR Pro"): BBCEAS 미량기체 분석 GUI. raw → α → DOAS 피팅 → 농도.
  개요: [`docs/Augur_소개_2026-07.md`](docs/Augur_소개_2026-07.md), 사용법: [`README.md`](README.md).
- **Oculus** (`oculus/`): 측정 중 실시간 감시 프로그램(별도 진입점, 이 저장소 안에 패키지로 존재).
  설계: [`docs/Oculus_설계_2026-07.md`](docs/Oculus_설계_2026-07.md) — 로드맵 M0~M4, M0(프로파일 계층)는 구현됨.

## 작업 시작 전 필독 — 하는 일에 따라 갈라짐

**"코드 구조 파악해줘"로 시작하지 말 것.** 코드를 읽어도 세션들이 힘들게 얻은 함정 회피 지식은
문서에만 있다. 아래 표대로 먼저 읽는다.

| 작업 종류 | 먼저 읽을 문서 |
|---|---|
| 핏세팅 자동 최적화 (`core/fit_optimizer.py`, `param_optimizer.py`, `fitset_builder.py`, `tools/optimize_*`, `tools/build_fitset.py`) | [`docs/fit_optimizer_handoff.md`](docs/fit_optimizer_handoff.md) 전체, 특히 **§15(알고리즘 명세)·§2-B(신뢰 3계층)·§16(Center 모드)** |
| Oculus (실시간 감시) | [`docs/Oculus_설계_2026-07.md`](docs/Oculus_설계_2026-07.md) 전체 |
| 그 외 Augur GUI/코어 일반 작업 | [`docs/HANDOFF.md`](docs/HANDOFF.md)(최신 세션 노트) + `README.md`의 폴더구조·임포트구조 |
| ANs/ANs 퇴화·NIER 제출 관련 | [`docs/ANs_분석_핸드오프_2026-07-23.md`](docs/ANs_분석_핸드오프_2026-07-23.md) |

## 절대 어기면 안 되는 원칙 (요약, 근거는 위 문서에)

1. **데이터 무결성 헌장**: 지우지 말고 flag. 과필터링이 부족한 필터링보다 위험. 원본은 항상 복원 가능해야 함.
2. **물리 > 통계**: 통계(F검정·perr·MDL)만으로 레퍼런스/세팅을 심판하면 과적합을 상 준다
   (O4 사건이 실증 — `fit_optimizer_handoff.md` §12, §14-C). **T1(자기일관성)은 절대 단독 심판이 될 수 없다.**
   외부 진실(T3) > 물리 건전성(T2) > 자기일관성(T1) 순.
3. **단일 출처 원칙**: raw 컬럼 배치는 `core/raw_parser.py`, Rayleigh 물리는 `core/physics.py`,
   QC 문턱식은 `core/result_io.py` 한 곳에만 — 사본을 만들지 말 것.
4. **재현성**: 결과 파일 헤더에 git 해시 + 세팅 전체가 자동 기록되어야 함. 자동 처리는 사람 승인 없이 적용 금지.

## 지금 상태 (파악 시점 2026-08-04, 이후 바뀔 수 있음 — `git log`/`git status`로 재확인할 것)

- 최근 작업 브랜치: `claude/oculus-realtime-monitoring-pbjudz`.
- **주의**: 이 브랜치에 커밋 안 된 변경(core/data_io.py 등)과, ANs/NIER 제출 관련으로 보이는 untracked
  파일들(`tools/build_nier_submission.py`, `scenarios/AutoFitSet_*.json` 등)이 섞여 있었다.
  Oculus 작업을 새로 시작하기 전에 이게 정리됐는지 `git status`로 먼저 확인할 것.

## 회귀 검증 (코드 수정 후 반드시)

```
python tools/validate_pipeline.py --no-data   # 데이터 없이(CI와 동일)
python tools/ci_import_smoke.py               # 전 모듈 임포트 스모크
python tools/validate_plotmaker.py            # 시각화 수정 시
```

## 메모리 스코프 주의

`.claude` 프로젝트 메모리는 **`claude`를 실행한 정확한 디렉터리**에 묶인다. 이 저장소 관련 축적 기억은
바깥 `C:\Doasis_Work\CAESAR`에서 실행했을 때 쌓인 것들이다 — 안쪽(`CAESAR\CAESAR`, 여기)이나 다른
경로에서 실행하면 그 기억들이 안 보인다. **`C:\Doasis_Work\CAESAR`에서 `claude`를 켤 것.**
