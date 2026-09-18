# CLAUDE.md — Augur / CAESAR 저장소 가이드

> **이 파일이 있는 위치가 저장소 루트다.** 체크아웃 경로는 PC마다 다르다
> (`C:\GHL\CAESAR`, `C:\Doasis_Work\CAESAR\CAESAR`, …). 후자에는 **이름이 같은 `CAESAR`
> 폴더가 바깥에 하나 더 있다** — 그건 저장소를 담는 부모 폴더일 뿐 git 저장소가 아니다.
> `git status`가 이상하면 `pwd`부터 확인.

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
| NO2 인젝션 실험(g 축퇴·핫채널 30% 결손 해결) | [`docs/NO2_인젝션_실험_핸드오프_2026-08.md`](docs/NO2_인젝션_실험_핸드오프_2026-08.md) 전체 |
| 수치·오차·QC 감사 관련(공분산, σ̂², n_eff, 포화, flag=0) | [`docs/감사_교차검증_2026-09-16.md`](docs/감사_교차검증_2026-09-16.md) — 항목마다 재현 명령·확신 수준·**정정 목록**이 있다 |

## 절대 어기면 안 되는 원칙 (요약, 근거는 위 문서에)

1. **데이터 무결성 헌장**: 지우지 말고 flag. 과필터링이 부족한 필터링보다 위험. 원본은 항상 복원 가능해야 함.
2. **물리 > 통계**: 통계(F검정·perr·MDL)만으로 레퍼런스/세팅을 심판하면 과적합을 상 준다
   (O4 사건이 실증 — `fit_optimizer_handoff.md` §12, §14-C). **T1(자기일관성)은 절대 단독 심판이 될 수 없다.**
   외부 진실(T3) > 물리 건전성(T2) > 자기일관성(T1) 순.
3. **단일 출처 원칙**: raw 컬럼 배치는 `core/raw_parser.py`, Rayleigh 물리는 `core/physics.py`,
   QC 문턱식은 `core/result_io.py` 한 곳에만 — 사본을 만들지 말 것.
4. **재현성**: 결과 파일 헤더에 git 해시 + 세팅 전체가 자동 기록되어야 함. 자동 처리는 사람 승인 없이 적용 금지.

## 지금 상태 (파악 시점 2026-09-19, 이후 바뀔 수 있음 — `git log`/`git status`로 재확인할 것)

- **2026-09-19 (성능)**: 알파 Pass 1 에 **프리페치 리더**를 넣어 콜드 HDD 에서 3배
  (25.2 → 74.7 MB/s). 워커마다 파일을 열던 것이 헤드를 긁고 있었다. 병렬 워커 수는
  이제 `core/parallel.py` 단일 출처 + GUI `CPU` 스핀(메인 창·Alpha Generator 팝업 둘 다).
  **raw 가 USB HDD 면 디스크가 병목이라 코어를 8 이상 줘도 이득이 없다.**
  실측 표·기각한 대안은 `docs/HANDOFF.md` 2026-09-19 절 §2·§5.

- **2026-09-19 (정확도)**: 핫 PC 는 2026-05-18~05-29 09:29 구간에 bytepack 시각을
  UTC 로 안 바꿨다 → `DataIO.clock_epoch_offset_sec` 가 −9h 보정. **그 전에 만든 핫
  알파는 이 구간이 9h 어긋나 있다**(헤더에 `# clock_epoch=` 줄이 없으면 옛 산물).

- **2026-09-17**: Conc 그래프의 "시간당 한 번 튀는" 스파이크 = 교정(He/ZA) 직후 캐비티에
  남은 퍼지가스. 알파 생성에 `purge_settle_sec`(기본 60초) 제외 규칙을 넣었다 —
  **기존 알파는 재생성해야 반영된다.** 근거·수치·미해결은 `docs/HANDOFF.md` 2026-09-17 절.

- 작업 브랜치 `main`, 작업트리 clean, **origin/main 과 동기화됨**(2026-09-19 푸시). 브랜치는 `main` 하나뿐이다.
- 최근 두 주는 **수치 감사**였다: 파장축 파서 단일 출처화, `flag=0` 헤더행 T/P 차용,
  CCD 포화 감지, 공분산 λ 불일치, σ̂² 분모 `RSS/n` → `RSS/(n-p)`. 무엇이 **출력을 바꿨고**
  무엇이 안 바꿨는지는 `docs/감사_교차검증_2026-09-16.md` §1 표에 한눈에 있다.
- 남은 감사 항목은 `docs/HANDOFF.md`의 "출발점" 절 4·6·7·8번
  (수치 바닥값 산재 / `estimate_shift` 실패=0 / `_is_alpha_input` 오판 / T/P 명목값 → 오차예산).

## 회귀 검증 (코드 수정 후 반드시)

```
pytest                                        # 저장소의 test_*.py 전부 (~30초, 데이터 불필요)
python tools/validate_pipeline.py --no-data   # 데이터 없이(CI와 동일)
python tools/ci_import_smoke.py               # 전 모듈 임포트 스모크
python tools/validate_plotmaker.py            # 시각화 수정 시
```

새 자체검증을 만들면 `tools/`나 `oculus/`에 `test_*.py`로 두면 된다 —
`tests/test_script_suite.py`가 자동으로 주워서 CI에서 돌린다. CI 파일은 안 건드려도 된다.

## 메모리 스코프 주의

`.claude` 프로젝트 메모리는 **`claude`를 실행한 정확한 디렉터리**에 묶인다. 체크아웃이 여러 개라
기억도 갈라져 있다 (2026-09-17 기준):

| 실행 디렉터리 | 쌓인 기억 |
|---|---|
| `C:\Doasis_Work\CAESAR` | **53개** — 2026-06~08 축적분(알파 병렬화, ANs 에폭, R 캘리브 등) |
| `C:\GHL\CAESAR` | 4개 — 최근분(계기 sentinel 규약, HK 열 배치) |

**어느 쪽에서 켜든 반대쪽 기억은 안 보인다.** 옛 맥락이 필요하면 그쪽 `MEMORY.md`를 직접 읽으면 된다
(`C:\Users\<user>\.claude\projects\C--Doasis-Work-CAESAR\memory\`).
어차피 저장소 지식의 본체는 `docs/`에 있다 — 기억은 보조다.
