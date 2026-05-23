# CAESAR Pro

아라온 선상 BBCEAS(Broadband Cavity-Enhanced Absorption Spectroscopy) 실시간 분석 소프트웨어.
raw .dat 데이터에서 파장 보정·ILS 적용·DOAS 피팅까지 한 번에 처리한다.

---

## 폴더 구조

```
CEASER/
├── main.py              ← GUI 진입점 (python main.py)
├── app_window.py        ← PyQt6 메인 창
├── ui_dialogs.py        ← 다이얼로그 / 모니터 위젯
├── worker.py            ← 분석 QThread 워커
├── engine.py            ← DOAS 분석 엔진 (shift/squeeze/ILS/etalon)
├── data_io.py           ← 파일 I/O, 아라온 HK 파싱
├── Argos.png            ← 스플래시 스크린 이미지
│
├── tools/               ← 독립 실행 오프라인 분석 도구
│   ├── reflectance_calc.py   ← 반사율 계산 핵심 모듈 (Rayleigh + CEAS)
│   ├── auto_r_calculator.py  ← 배치 R 계산기 (ZA/He flag 파싱)
│   ├── r_trend_monitor.py    ← R 시계열 모니터 / PNG·DAT 저장
│   └── plot_r_results.py     ← 기계산된 _R.dat 파일 시각화
│
├── calibration/         ← 교정 파일 생성·갱신 스크립트
│   ├── regen_cold_refs.py    ← Cold ILS 적용 reference 재생성
│   └── mission_20260523.py   ← Hot/Cold sigma sweep + 파장 교정 미션
│
├── campaigns/           ← 캠페인별 데이터 처리
│   └── yeosu_2026/
│       └── process_inlet.py  ← jNO2/jO3 Inlet 데이터 처리
│
└── scratch/             ← 일회성 진단·탐색 스크립트
    ├── _fwhm_r_analysis.py      ← Cold FWHM 측정 진단
    ├── _hot_fwhm_r_analysis.py  ← Hot FWHM 측정 진단
    └── _test_rv.py              ← R 값 trim mean 검증
```

---

## 실행 방법

**GUI 앱 실행**
```
python main.py
```

**오프라인 R 시계열 모니터 (tools/)**
```
python tools/r_trend_monitor.py
```
- `COLD_DIR`, `COLD_FILES` 등 스크립트 상단 설정 변수 조정 후 실행
- 출력: `<날짜범위>/R_trend_Cold.png`, `R_trend_Hot.png`, `*.dat`

---

## raw .dat 파일 구조 요약

> 자세한 내용은 `tools/r_trend_monitor.py` 상단 docstring 참조

- **col1** : 센티초(centiseconds) 단위. UTC 초가 아님.
- **타임스탬프** : 파일 `mtime` 사용 (DAQ가 파일 열 때 기록, 1시간 간격).
- **flag=500** : ZA(Zero Air) 스캔 → R 계산 사용
- **flag=510** : He(Helium) 스캔 → R 계산 사용
