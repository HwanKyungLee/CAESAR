# CAESAR Pro

아라온 선상 BBCEAS(Broadband Cavity-Enhanced Absorption Spectroscopy) 실시간 분석 소프트웨어.
raw .dat 데이터에서 파장 보정·ILS 적용·α 스펙트럼 생성·DOAS 피팅까지 한 번에 처리한다.

---

## 폴더 구조

```
CAESAR/
├── main.py                    ← GUI 진입점 (python main.py)
├── Argos.png                  ← 스플래시 스크린 이미지
├── requirements.txt           ← 의존성
├── CAESAR_Pro_실행.bat        ← Windows 실행 배치
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
│   ├── ui_result_viewer.py    ← 결과 뷰어 (Result Viewer)
│   ├── ui_plot_maker.py       ← Plot Maker (시계열/Diurnal 플롯)
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
└── docs/                      ← 설계/이력 문서
    ├── refactor_notes.md
    └── HANDOFF.md             ← 세션 핸드오프 노트 (아카이브)
```

> `.venv/`, `.vscode/`, `hitran_data/`, `logs/`, `__pycache__/`, R 출력 폴더,
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

## 실행 방법

**GUI 앱 실행**
```
python main.py
```

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

---

## raw .dat 파일 구조 요약

> 자세한 내용은 `core/raw_parser.py` 와 `tools/r_trend_monitor.py` 상단 docstring 참조

- **col1** : 센티초(centiseconds) 단위. UTC 초가 아님.
- **타임스탬프** : 파일 `mtime` 사용 (DAQ가 파일 열 때 기록, 1시간 간격).
- **flag=500** : ZA(Zero Air) 스캔 → R 계산 사용
- **flag=510** : He(Helium) 스캔 → R 계산 사용
