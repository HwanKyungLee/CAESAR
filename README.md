# CAESAR Pro

아라온 선상 BBCEAS(Broadband Cavity-Enhanced Absorption Spectroscopy) 실시간 분석 소프트웨어.
raw .dat 데이터에서 파장 보정·ILS 적용·DOAS 피팅까지 한 번에 처리한다.

---

## 폴더 구조

```
CEASER/
├── main.py                    ← GUI 진입점 (python main.py)
├── Argos.png                  ← 스플래시 스크린 이미지
│
├── core/                      ← 공용 연산·IO 모듈 (패키지)
│   ├── data_io.py             ← 파일 I/O, 아라온 HK 파싱
│   ├── engine.py              ← DOAS 분석 엔진 (shift/squeeze/ILS/etalon)
│   └── physics.py             ← 공용 물리 클래스 (RayleighPhysics, KalmanTracker)
│
├── gui/                       ← PyQt6 UI 레이어 (패키지)
│   ├── app_window.py          ← 메인 창 (CAESARAnalyzer)
│   ├── ui_dialogs.py          ← re-export wrapper (하위 호환용)
│   ├── ui_dialogs_calib.py    ← 교정 다이얼로그 (NavigationHelper, WavelengthCalibrationDialog, RangeSelectorDialog)
│   ├── ui_dialogs_ref.py      ← 레퍼런스 관리 (MaskDialog, RefPropertiesDialog, ReferenceGeneratorDialog, MonitorWidget)
│   ├── ui_dialogs_r.py        ← R 커브 & 시계열 (R_GeneratorDialog, RTrendMonitorDialog)
│   └── worker.py              ← 분석 QThread 워커
│
├── tools/                     ← 독립 실행 오프라인 분석 도구
│   ├── reflectance_calc.py    ← 반사율 계산 모듈 (Rayleigh + CEAS)
│   ├── r_batch_calculator.py  ← 배치 R 계산기 (ZA/He flag 파싱, 폴더 단위)
│   ├── r_trend_monitor.py     ← R 시계열 모니터 / PNG·DAT 저장
│   └── r_results_plotter.py   ← 기계산된 _R.dat 파일 시각화
│
├── calibration/               ← 교정 파일 생성·갱신 스크립트
│   ├── build_cold_refs.py     ← Cold ILS 적용 reference 재생성
│   └── ils_sigma_sweep.py     ← Hot/Cold ILS sigma 파라미터 스윕 + 파장 교정
│
├── campaigns/                 ← 캠페인별 데이터 처리
│   └── yeosu_2026/
│       └── inlet_jno2_jo3.py  ← jNO2/jO3 Inlet 데이터 처리 (여수 2026)
│
└── diagnostics/               ← 진단·검증 스크립트
    ├── fwhm_r_check.py        ← Cold/Hot FWHM 측정 + R 진단 (--mode cold|hot)
    └── r_trimmed_mean_check.py ← R trimmed mean vs 전체 평균 검증
```

---

## 임포트 구조

```
main.py
 ├── gui.app_window  →  core.engine
 │                  →  core.data_io
 │                  →  gui.worker              →  core.data_io
 │                  │                          →  core.physics  (RayleighPhysics, KalmanTracker)
 │                  →  gui.ui_dialogs          →  gui.ui_dialogs_calib
 │                                             →  gui.ui_dialogs_ref
 │                                             →  gui.ui_dialogs_r
 └── core.data_io

tools/r_trend_monitor.py   →  tools/reflectance_calc.py  →  core.physics
                           →  tools/r_batch_calculator.py →  tools/reflectance_calc.py

diagnostics/fwhm_r_check.py  →  core.physics
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

> 자세한 내용은 `tools/r_trend_monitor.py` 상단 docstring 참조

- **col1** : 센티초(centiseconds) 단위. UTC 초가 아님.
- **타임스탬프** : 파일 `mtime` 사용 (DAQ가 파일 열 때 기록, 1시간 간격).
- **flag=500** : ZA(Zero Air) 스캔 → R 계산 사용
- **flag=510** : He(Helium) 스캔 → R 계산 사용
