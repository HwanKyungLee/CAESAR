# -*- coding: utf-8 -*-
"""tools/ci_import_smoke.py — 전 모듈 임포트 스모크 테스트 (bit-rot 감지)

왜? 1인 개발에서 가장 흔한 부패는 '고치다가 다른 모듈의 import를 조용히
깨뜨리는 것'(3차 전수조사에서 잡힌 유형). 데이터 없이도 모든 .py가 최소한
import는 되는지 CI가 커밋마다 확인한다.

- 대상: core/ gui/ tools/ diagnostics/ calibration/ (하위 폴더 포함)
- GUI·플롯은 headless로: matplotlib Agg + QT_QPA_PLATFORM=offscreen
- 모듈 최상위에서 데이터 파일을 여는 스크립트는 EXCLUDE에 사유와 함께 등록
  (스모크는 '임포트 가능'만 본다 — 실행 검증은 validate_pipeline 몫)

사용: python tools/ci_import_smoke.py   → 전부 OK면 exit 0
"""
import importlib
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import matplotlib
matplotlib.use("Agg")

# 스캔 대상 최상위 폴더 (campaigns는 별도 의존성(scikit-learn 등)이라 제외)
SCAN_DIRS = ["core", "gui", "tools", "diagnostics", "calibration", "oculus"]

# 임포트 제외 목록 — {상대경로(슬래시): 사유}. 늘리기 전에 정말 최상위 실행이
# 필요한 스크립트인지 먼저 의심할 것(가능하면 __main__ 가드로 고치는 게 맞다).
EXCLUDE = {
    "tools/etalon_test.py": "레거시 실험 스크립트 — 최상위에서 데이터 로드",
    "tools/fixedpattern_test.py": "레거시 실험 스크립트 — 최상위에서 데이터 로드",
    "tools/rshape_test.py": "레거시 실험 스크립트 — 최상위에서 데이터 로드",
    "tools/source_fix_test.py": "레거시 실험 스크립트 — 최상위에서 데이터 로드",
    "tools/poly_sweep.py": "레거시 실험 스크립트 — 최상위에서 데이터 로드",
    "tools/identify_mode.py": "일회성 진단 — 최상위에서 데이터 로드·PNG 저장",
    "tools/ans_verify.py": "CLI 전용 — 최상위 argv 파싱",
    "tools/build_hot_no2_correction.py": "일회성 스크립트 — 최상위에서 데이터 로드(AQMS 앵커 탐색, R0 미채택)",
    "tools/build_final_g082_submission.py": "일회성 스크립트 — 최상위에서 Downloads 파일 접근(R0 최종 제출본)",
    "tools/build_labshare.py": "일회성 스크립트 — 최상위에서 데이터 로드(연구실 공유용 빌드)",
    "tools/build_labshare_1min.py": "일회성 스크립트 — 최상위에서 데이터 로드(연구실 공유용 1분 빌드)",
    "diagnostics/r_trimmed_mean_check.py": "일회성 진단 — 최상위에서 데이터 로드",
    "calibration/build_cold_refs.py": "교정 재생성 스크립트 — 최상위에서 데이터 로드",
    "calibration/ils_sigma_sweep.py": "교정 스윕 스크립트 — 최상위에서 데이터 로드",
}

# 폴더째 제외 — 일회성 검증 아카이브(결론은 FINDINGS.md에 박제, 코드는 보존용)
EXCLUDE_DIRS = {
    "diagnostics/alpha_vs_matlab_2025_06_11": "일회성 검증 아카이브(FINDINGS.md)",
    "diagnostics/cold_validation_2026_05": "일회성 검증 아카이브(FINDINGS.md)",
    "diagnostics/parallel_shift_bench": "일회성 벤치 아카이브",
}


def module_name(rel_path):
    """상대경로 → import 가능한 모듈명. 패키지(부모에 __init__.py)면 점 표기,
    아니면(tools/diagnostics 등 스크립트 폴더) 파일 단독 모듈로 로드."""
    parts = rel_path[:-3].replace("\\", "/").split("/")
    return ".".join(parts)


def iter_py_files():
    for top in SCAN_DIRS:
        base = os.path.join(ROOT, top)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in sorted(filenames):
                if fn.endswith(".py"):
                    rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
                    yield rel.replace("\\", "/")


def import_one(rel):
    """패키지 모듈은 importlib.import_module, 스크립트는 spec 로드."""
    parts = rel[:-3].split("/")
    # 부모 폴더 전부에 __init__.py 가 있으면 정식 패키지 임포트
    is_pkg = all(os.path.exists(os.path.join(ROOT, *parts[:i], "__init__.py"))
                 for i in range(1, len(parts)))
    if is_pkg:
        importlib.import_module(".".join(parts))
        return
    # 스크립트: 파일 위치를 sys.path에 넣고 단독 모듈로 로드 (도구들이 서로
    # `import r_trend_monitor` 하는 관례와 동일한 환경)
    d = os.path.dirname(os.path.join(ROOT, rel))
    if d not in sys.path:
        sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location(
        "_smoke_" + "_".join(parts), os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)


class _SmokeBuf:
    """redirect용 버퍼 — 스크립트가 sys.stdout.reconfigure()를 불러도 안 죽게."""

    def __init__(self):
        import io
        self._b = io.StringIO()

    def write(self, s):
        return self._b.write(s)

    def flush(self):
        pass

    def reconfigure(self, **kw):
        pass


def main():
    import contextlib
    ok, failed, skipped = 0, [], 0
    real_out, real_err = sys.stdout, sys.stderr
    for rel in iter_py_files():
        _dir_hit = next((d for d in EXCLUDE_DIRS if rel.startswith(d + "/")), None)
        if _dir_hit:
            skipped += 1
            continue
        if rel in EXCLUDE:
            print(f"  SKIP  {rel}  ({EXCLUDE[rel]})")
            skipped += 1
            continue
        # 임포트 중 출력은 버리고, 모듈이 sys.stdout/stderr를 바꾸거나 닫아도
        # (session_log tee 등) 스모크 자체는 살아남도록 매번 복구한다.
        buf = _SmokeBuf()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                import_one(rel)
            ok += 1
        except Exception:
            failed.append((rel, traceback.format_exc(limit=3)))
        finally:
            sys.stdout, sys.stderr = real_out, real_err
        if failed and failed[-1][0] == rel:
            print(f"  FAIL  {rel}")
    print(f"\nimport smoke: {ok} OK · {len(failed)} FAIL · {skipped} SKIP")
    for rel, tb in failed:
        print(f"\n--- {rel} ---\n{tb}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
