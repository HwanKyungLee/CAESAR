# Augur

> **CAESAR** BBCEAS 미량기체 분석 소프트웨어 (구 "CAESAR Pro"). 랩 통합 관측시스템 **ARGUS** 아래, 계측기 **CAESAR**의 데이터를 농도로 확정하는 분석 프로그램이다. (측정 중 실시간 감시는 별도 프로그램 **Oculus**가 맡는다 — 설계: [`docs/Oculus_설계_2026-07.md`](docs/Oculus_설계_2026-07.md))

[![CI](https://github.com/HwanKyungLee/CAESAR/actions/workflows/ci.yml/badge.svg)](https://github.com/HwanKyungLee/CAESAR/actions/workflows/ci.yml)

측정한 광학 분광 데이터 대기 중 미량 기체
(NO₂, CHOCHO 등) 농도를 산출하는 데스크톱 분석 프로그램(PyQt6 GUI)이다.

장비(BBCEAS, 아래 [용어](#용어-사전) 참조)가 1시간마다 떨궈주는 raw `.dat` 파일을
넣으면 → 파장 보정 → 흡광 스펙트럼(α) 생성 → DOAS 피팅으로 기체 농도를 뽑고,
시계열 그래프까지 한 화면에서 만들어 준다.

> **처음 보는 사람**은 [설치](#설치)와 [빠른 시작](#빠른-시작-gui-사용-흐름)만 읽으면 앱을 켤 수 있고,
> [용어 사전](#용어-사전)에 분야 약어를 풀어 두었다.
> **운용자**(캠페인 데이터 처리 순서)는 [`docs/매뉴얼_조작순서.md`](docs/매뉴얼_조작순서.md)를 보면 되고,
> **코드를 고칠 사람**은 그 아래 [폴더 구조](#폴더-구조)·[임포트 구조](#임포트-구조)를 보면 된다.

---

## 설치

- **필요 환경**: Python 3.11+ (개발은 3.14 기준), Windows 권장(아라온 DAQ가 Windows).

```bash
# 1) 저장소 받기
git clone https://github.com/HwanKyungLee/CAESAR.git
cd CAESAR

# 2) 가상환경 + 의존성 (PyQt6 / numpy / scipy / matplotlib / pandas / pyqtgraph / hitran-api / threadpoolctl)
python -m venv .venv
.venv\Scripts\activate        # (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

# 3) 실행
python main.py
```

Windows에서는 `Augur_실행.bat` 더블클릭으로도 켜진다(콘솔 없이 GUI만 뜨고,
크래시 로그는 `logs/crash.log` 에 쌓인다). HITRAN 라인리스트("🌐 Generate from HITRAN"
버튼, Reference Generator에서 새 단면을 만들 때만 필요)는 처음 쓸 때 인터넷으로 받아
`hitran_data/` 에 캐시되고(저장소에는 포함되지 않음, 사용자별) 이후로는 캐시만 쓴다.
현재 쓰는 시나리오(NO2/CHOCHO/O4)는 이미 만들어진 문헌 단면 파일을 쓰므로 일상적인
분석 실행에는 인터넷이 필요 없다. 인터넷이 없는 환경(예: 선상)에서 이 버튼을 눌러
아직 캐시 안 된 종을 새로 받으려 하면 15초 후 타임아웃 에러가 뜬다(멈추지 않음).

문헌 단면(NO2/CHOCHO/O4)과 파장보정 상수는 `reference_data/`에 저장소째 포함돼 있어
별도로 준비할 게 없다. 분석 결과(alpha/fitting/R/figure)는 기본적으로 `output/`에
쌓이며(머신별 재생성 산출물이라 저장소에는 포함 안 됨), 파일 다이얼로그에서 다른
위치를 고르면 다음부터 그 위치를 기억한다.

---

## 빠른 시작 (GUI 사용 흐름)

`python main.py` 를 실행하면 상단 탭 4개가 보인다. 왼쪽에서 오른쪽이 곧 작업 순서다.

| 순서 | 탭 | 하는 일 |
|----|----|--------|
| 1 | 🛠️ **Setup** | raw `.dat` 폴더 지정, 파장 보정·레퍼런스·R(반사율) 준비, 피팅 시나리오 선택 |
| 2 | 📈 **Analysis Monitor** | RUN을 눌러 DOAS 피팅 실행, 진행 상황·실시간 농도 확인 |
| 3 | 📂 **Result Lab** | 산출된 결과 파일(농도 시계열) 열람·자르기·병합·QC 재적용·계산기 |
| 4 | 📉 **Plot Maker** | 종별 시계열/Diurnal(시간대별) 그래프 만들기·내보내기 |

분석에 쓰는 거울 반사율 R 등은 Setup 탭의 **R Calibrator**(R 커브·시계열)에서 만든다.

---

## 용어 사전

도메인 약어를 처음 보는 사람을 위한 최소 설명.

| 용어 | 뜻 |
|------|----|
| **BBCEAS** | Broadband Cavity-Enhanced Absorption Spectroscopy. 양쪽 고반사 거울 사이에 빛을 가둬 광경로를 수 km로 늘려 미량 기체까지 측정하는 분광 기법 |
| **DOAS** | Differential Optical Absorption Spectroscopy. 흡광 스펙트럼의 미분 구조를 기준 단면과 맞춰 기체 농도를 푸는 분석법 |
| **α (알파)** | 흡광 계수 스펙트럼. raw 신호로부터 계산하며 DOAS 피팅의 입력이 된다 |
| **R (반사율)** | 거울 반사율. 광경로 길이를 정하는 핵심 값이라 시간에 따라 보정한다(R(t)) |
| **ILS** | Instrument Line Shape. 분광기가 빛을 번지게 하는 정도. 기준 단면에 적용해 실제 측정과 맞춘다 |
| **etalon** | 광학 부품의 다중 반사로 생기는 잔물결 간섭 패턴(피팅에서 보정 대상) |
| **shift / squeeze** | 파장축의 미세한 이동·신축. 피팅 중 자동 보정한다 |
| **ZA / He** | Zero Air / Helium 보정 스캔. R(반사율) 계산에 쓰는 기준 측정 (flag 500 / 510) |
| **Cold / Hot** | 두 측정 채널(저온·고온 캐비티). 데이터 컬럼 구조와 보정값이 다르다 |

> ⚠ **Shift 부호 규약 — 외부 도구(QDOAS/DOASIS)와 비교할 때 반드시 확인**:
> Augur의 `shift`는 `model(x) = reference(x + shift)`로 정의되어 있다. 이는
> QDOAS/DOASIS 등이 따르는 표준 DOAS 관례(Platt & Stutz), `model(x) =
> reference(x - shift)`와 **부호가 정반대**다 — 즉 `shift_Augur = -shift_표준`.
> Augur 내부적으로는(VarPro/완전비선형/웜스타트 전부 동일 관례를 씀) 전혀
> 문제가 없지만, 외부 도구와 값을 직접 비교하거나 다른 도구의 bound를 그대로
> 가져와 쓸 때는 반드시 부호를 뒤집어야 한다. 자세한 배경은
> `core/engine.py::get_model_components` 독스트링과
> `diagnostics/qdoas_crossval_2026-09/`(2026-09-08 발견) 참조.

---

## 폴더 구조

```
CAESAR/
├── main.py                    ← GUI 진입점 (python main.py)
├── AUGUR.png                   ← 스플래시 스크린 이미지
├── requirements.txt           ← 의존성
├── Augur_실행.bat             ← Windows 실행 배치
│
├── core/                      ← 공용 연산·IO 모듈 (패키지)
│   ├── raw_parser.py          ← raw .dat 컬럼 레이아웃 단일 출처(single source of truth)
│   ├── data_io.py             ← 파일 I/O 게이트키퍼, 아라온 HK 파싱 (raw_parser 기반)
│   ├── engine.py              ← DOAS 분석 엔진 UniversalEngine (shift/squeeze/ILS/etalon)
│   ├── doas_fit.py            ← 공유 VarPro DOAS 피터 (DoasFitter) — GUI/도구 공통
│   ├── physics.py             ← 공용 물리 (RayleighPhysics, KalmanTracker)
│   ├── result_io.py           ← 리트리벌 결과 파일 공통 IO (읽기/자르기/병합)
│   ├── provenance.py          ← 코드 출처(provenance) 스탬프
│   └── session_log.py         ← stdout/stderr를 logs/session_*.log 로 tee
│
├── gui/                       ← PyQt6 UI 레이어 (패키지)
│   ├── app_window.py          ← 메인 창 (CAESARAnalyzer)
│   ├── worker.py              ← 분석 QThread 워커 (AnalysisWorker)
│   ├── r_workers.py           ← R Calibrator 백그라운드 워커 (rt_precompute·r_trend lazy)
│   ├── ui_alpha_gen.py        ← Alpha Generator 팝업 (raw → *_alpha_trace.dat)
│   ├── ui_result_viewer.py    ← 결과 뷰어 (Result Lab)
│   ├── ui_plot_maker/         ← Plot Maker 패키지 (widget/modes/core/data/processing)
│   ├── ui_peak_trend.py       ← Setup 탭 피크 트렌드 뷰어 (flag별 시계열)
│   ├── result_viewer_io.py    ← 결과 뷰어 IO 헬퍼
│   ├── dlg_dir.py             ← 파일 다이얼로그 '버튼별 최근 디렉토리' 헬퍼
│   ├── flow_layout.py         ← 폭 부족 시 자동 줄바꿈 FlowLayout
│   │
│   ├── ui_dialogs.py          ← 하위 호환 re-export wrapper
│   ├── ui_dialogs_calib.py    ← 교정 (NavigationHelper, WavelengthCalibrationDialog, RangeSelectorDialog)
│   ├── ui_dialogs_ref.py      ← 레퍼런스 관리 re-export wrapper
│   ├── ui_dialogs_r.py        ← R 커브 & 시계열 (R_GeneratorDialog, RTrendMonitorDialog)
│   ├── ref_mask_dialog.py     ← MaskDialog
│   ├── ref_properties_dialog.py     ← RefPropertiesDialog
│   ├── reference_generator_dialog.py ← ReferenceGeneratorDialog
│   └── monitor_widget.py      ← MonitorWidget
│
├── tools/                     ← 독립 실행 오프라인 분석 도구
│   ├── reflectance_calc.py    ← 반사율 계산 모듈 (Rayleigh + CEAS, core.physics 기반)
│   ├── r_batch_calculator.py  ← 배치 R 계산기 (ZA/He flag 파싱, 폴더 단위)
│   ├── r_trend_monitor.py     ← R 시계열 모니터 / PNG·DAT 저장
│   ├── r_results_plotter.py   ← 기계산된 _R.dat 파일 시각화 (3채널)
│   ├── rt_precompute.py       ← R(t) 프리컴퓨트 (채널별 R(t) knot → R_<ch>.npz)
│   ├── alpha_wide_to_perbin.py← wide α → 박사님 per-bin 형식 변환기
│   ├── result_slice.py        ← 리트리벌 결과 자르기/합치기 CLI (core.result_io 공용)
│   ├── plot_spectra_by_date.py← flag별 피크값 트렌드 플롯
│   ├── check_timestamps.py    ← 단일 raw .dat 타임스탬프 후보 비교 진단
│   ├── identify_mode.py       ← 콜드 잔차 PCA모드 vs 후보 단면 오버레이 (범인 지목)
│   ├── residual_probe.py      ← 콜드 알파 한 스캔 헤드리스 피팅 → 잔차 그림
│   └── residual_compare.py    ← Cold vs Hot(PNs/ANs) 잔차 진단 비교
│
├── calibration/               ← 교정 파일 생성·갱신 스크립트
│   ├── build_cold_refs.py     ← Cold ILS 적용 reference 재생성
│   └── ils_sigma_sweep.py     ← Hot/Cold ILS sigma 스윕 + Cold 파장 교정
│
├── campaigns/                 ← 캠페인별 데이터 처리
│   └── yeosu_2026/
│       ├── inlet_jno2_jo3.py  ← jNO2/jO3 Inlet 데이터 처리
│       └── hot_cavity_t/      ← Hot 캐비티 온도 백캐스트 (GBR 모델 + 탐색/스크립트)
│
├── diagnostics/               ← 진단·검증 스크립트
│   ├── fwhm_r_check.py        ← Cold/Hot FWHM 측정 + R 진단 (--mode cold|hot)
│   ├── r_trimmed_mean_check.py← R trimmed mean vs 전체 평균 검증
│   ├── alpha_vs_matlab_2025_06_11/ ← α 생성 MATLAB 대조 검증 (FINDINGS.md)
│   ├── cold_validation_2026_05/    ← Cold DOAS 피팅 검증 (FINDINGS.md)
│   └── parallel_shift_bench/       ← shift 안정화 병렬화 벤치 (EXISTING_FIT_LOGIC.md)
│
├── scenarios/                 ← DOAS 피팅 시나리오 JSON
│   └── Doctor_Scenario_Cold_ROI1_ROI2.json
│
├── reference_data/            ← 레포에 번들된 입력 데이터 (core/paths.py 기준 경로)
│   ├── raw/                   ← 문헌 단면 (NO2/CHOCHO/O4)
│   └── wv_cal/                ← 채널별 파장보정 상수 (cold/roi1/roi2)
│
└── docs/                      ← 설계/이력 문서
    ├── refactor_notes.md
    └── HANDOFF.md             ← 세션 핸드오프 노트 (아카이브)
```

> `.venv/`, `.vscode/`, `hitran_data/`, `logs/`, `output/`, `__pycache__/`, R 출력 폴더,
> 도구 출력 PNG 등 머신별·재생성 가능 산출물은 `.gitignore`로 제외된다.

---

## 임포트 구조

```
main.py
 ├── core.session_log
 ├── core.data_io       (ui_scale)
 └── gui.app_window  →  core.engine / core.data_io / core.doas_fit / core.physics
                     →  gui.worker          →  core.data_io / core.physics / core.doas_fit
                     │                       →  tools.rt_precompute (lazy, load_rt)
                     →  gui.ui_alpha_gen / ui_result_viewer / ui_plot_maker / ui_peak_trend
                     →  gui.ui_dialogs(_calib/_ref/_r) → ref_*_dialog / monitor_widget
                     →  gui.r_workers / ui_dialogs_r  →  tools.rt_precompute / r_trend_monitor (lazy)

tools.r_trend_monitor   →  tools.reflectance_calc  →  core.physics
                        →  tools.r_batch_calculator →  tools.reflectance_calc

diagnostics.fwhm_r_check  →  core.physics
```

---

## 오프라인 도구 실행 (CLI)

GUI 없이 터미널에서 돌리는 분석/진단 스크립트들. (앱 자체는 위 [빠른 시작](#빠른-시작-gui-사용-흐름) 참조)

**오프라인 R 시계열 모니터**
```
python tools/r_trend_monitor.py
```

**배치 R 계산 (채널별 폴더 전체)**
```
python tools/r_batch_calculator.py
```

**FWHM + R 진단 (Cold 또는 Hot)**
```
python diagnostics/fwhm_r_check.py --mode cold
python diagnostics/fwhm_r_check.py --mode hot
```

**코드 수정 후 회귀 검증** (CI가 커밋마다 데이터 비의존 부분을 자동 실행)
```
python tools/validate_pipeline.py            # 전체(측정 데이터 있는 머신)
python tools/validate_pipeline.py --no-data  # 데이터 없이 (CI와 동일)
python tools/ci_import_smoke.py              # 전 모듈 임포트 스모크
python tools/validate_plotmaker.py           # 시각화 수정 시 (24항목)
```

---

## raw .dat 파일 구조 요약

> 자세한 내용은 `core/raw_parser.py` 와 `tools/r_trend_monitor.py` 상단 docstring 참조

- **col0·col1** : bytepack 시각 — `(col0<<16)|col1` = 연초(1/1 00:00) 기준 센티초(0.01초) 카운터.
- **타임스탬프** : 행별 bytepack 시각 사용 (박사님 `.mat`의 doy와 std=0.0000s 일치 검증).
  파일 `mtime`은 bytepack을 못 읽을 때의 폴백일 뿐이다.
- **flag=500** : ZA(Zero Air) 스캔 → R 계산 사용
- **flag=510** : He(Helium) 스캔 → R 계산 사용
