# 재처리 점검 스크립트 (2026-09-28)

결과와 해석: `docs/재처리_점검_2026-09-28.md`.

- `qtstub.py` — PyQt6 없이 `gui.worker`를 불러오기 위한 스텁(QThread/pyqtSignal).
- `build_R_days.py <ch> <newpair|oldpair> <out.npz> [YYYY-MM-DD ...]` — `rt_precompute`로 R(t) knot 재계산. **RL_FACTOR = 1.0**(운영값)으로 고정. `oldpair`는 `DataIO._slot_identity`를 끄고 옛 압력 짝을 쓴다.
- `alpha_days.py <ch> <mode> <R.npz> <outroot> <purge_s> <day ...>` — 날짜별 60 s 알파(앞뒤 파일 1개씩 문맥 포함). 환경변수 RAWSUB=cold, CHDIR=ch3, LABEL=cold로 cold에도 쓴다.
- `fit_run.py <alpha_root> <outdir> <wi> <nw> <step> [day ...]` — 운영 FitSet으로 `param_optimizer.fit_scan` 헤드리스 핏.
- `fit_run_roi.py` — 같지만 ROI_SWAP=1이면 channel 1을 roi1 교정·레퍼런스로 바꾼다.
- `cold_shift_slopes.py <wi> <nw> <outdir>` — QDOAS 교차검증 5364 cold 스펙트럼을 shift 조건별로 다시 핏.
- `r_trend_monitor.py` — `tools/r_trend_monitor.py`의 커밋된 판 사본(이 샌드박스에서 tools/ 원본은 읽기 권한이 없다).

이 샌드박스는 multiprocessing 파이프가 막혀 워커 내부 병렬이 꺼진다. 날짜별로 프로세스를 나눠 병렬로 돌린다.
