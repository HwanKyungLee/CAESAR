"""dense-W 제거(2026-09-14) 전/후 대조  -  실캠페인 알파 데이터.

무엇을 바꿨나
-------------
`core/doas_fit.py`의 `execute_varpro_fit`는 픽셀 가중 W를 **밀집 nxn 대각행렬**로
받아 목적함수 매 호출마다 `W @ A`(O(n^2k))를 돌렸다. W는 언제나 대각이므로
`A * w[:,None]`(O(nk))와 동치인데, n=775px 기준 그 곱 하나가 objective 호출
비용의 62%를 먹고 있었다(측정: `W@A` 0.182 + `W@y` 0.065 vs 행스케일 0.0085 ms).
추가로 `y_weighted = W @ optical_depth`는 theta와 무관한데 매 호출 재계산했다.

왜 이 스크립트가 필요한가
-------------------------
핏 수치 경로다. 부동소수점으로도 비트동일이어야 한다(off-diagonal이 정확히 0이므로
수학적으로만이 아니라 비트단위로도 같아야 정상). 합성 데이터가 아니라 **실캠페인
알파**로, 이 폴더의 기존 하네스(`bench_common.run_varpro`)를 **양쪽에 똑같이** 써서
대조한다. 수정 전 코드는 `git show <ref>:core/doas_fit.py`로 꺼내 별도 모듈로
임포트하므로, 작업트리를 되돌릴 필요가 없다.

실행
----
    python validate_dense_w_removal.py --before-ref 944c7bd                      # cold 5/17 + 6/5, hot roi1/roi2
    python validate_dense_w_removal.py --before-ref 944c7bd --nfiles 1           # 빠른 스모크
    python validate_dense_w_removal.py --before-ref HEAD~1  # 다른 기준 커밋과 대조

종료코드 0 = 모든 케이스에서 shift/squeeze/농도가 **정확히 일치**(diff 0.0).
"""
from __future__ import annotations
import argparse, glob, importlib.util, os, subprocess, sys, tempfile
import numpy as np

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
for _p in (_REPO_ROOT, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bench_common
from bench_common import build_engine, run_varpro, load_real_alpha_scans

LINKED = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2",
          "t_ref": 25.0, "t_coeff": 0.0}
ANCHOR = {"sh_mode": "Limit", "sh_val": "-2.0, 2.0", "sq_mode": "Limit", "sq_val": "-0.02, 0.02",
          "t_ref": 25.0, "t_coeff": 0.0}
REF_PROPS = {"NO2": ANCHOR, "CHOCHO": dict(LINKED), "H2O": dict(LINKED)}
SPECIES = {"NO2": ("NO2", 1.0), "CHOCHO": ("CHOCHO", -1.0), "H2O": ("H2O-HITRAN", 1.0)}

# (라벨, wv_cal 서브폴더, 알파 폴더, 날짜, 픽셀창, poly차수)
# Hot 채널 매핑은 README.md 참조  -  ROI1(600-1270px, poly4)=PNs(ch2),
# ROI2(900-1450px, poly3)=ANs(ch1). 순서로 짝지으면 반대로 틀린다.
CASES = [
    ("cold 2026-05-17 (벽에 붙는 최악의 날)", "cold", os.path.join("alpha", "10s", "cold"),
     "2026-05-17", np.arange(775, 1550), 4),
    ("cold 2026-06-05 (보통 날)", "cold", os.path.join("alpha", "10s", "cold"),
     "2026-06-05", np.arange(775, 1550), 4),
    ("hot ROI1/PNs 2026-06-05", "roi1", os.path.join("alpha", "10s", "hot", "ch2"),
     "2026-06-05", np.arange(600, 1270), 4),
    ("hot ROI2/ANs 2026-06-05", "roi1", os.path.join("alpha", "10s", "hot", "ch1"),
     "2026-06-05", np.arange(900, 1450), 3),
]
FIXED_E_F, STEP_LIMIT = 0.12, 0.5


def load_fitter_before(ref: str):
    """수정 전 `core/doas_fit.py`를 git에서 꺼내 `DoasFitter`만 임포트한다.
    그 파일은 numpy/scipy 외 의존이 없어 패키지 밖에서도 단독 임포트된다."""
    src = subprocess.run(["git", "show", f"{ref}:core/doas_fit.py"], cwd=_REPO_ROOT,
                         capture_output=True, check=True).stdout
    fd, path = tempfile.mkstemp(suffix="_doas_fit_before.py")
    with os.fdopen(fd, "wb") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("doas_fit_before", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DoasFitter


def compare(label, before, after):
    """shift/squeeze/농도를 스캔별로 대조. 비트단위 동일이 기대값."""
    keys = [("shift", lambda o: o["shift"]), ("squeeze", lambda o: o["squeeze"])]
    keys += [(g, (lambda g: lambda o: o["c"][g])(g)) for g in before[0]["c"]]
    worst = 0.0
    lines = []
    for name, get in keys:
        a = np.array([get(o) for o in before], dtype=float)
        b = np.array([get(o) for o in after], dtype=float)
        d = float(np.max(np.abs(a - b)))
        worst = max(worst, d)
        lines.append(f"    {name:8s} max|diff| = {d:.3e}   (|값| 평균 {np.mean(np.abs(a)):.4e})")
    tb = 1000 * float(np.mean([o["dt"] for o in before]))
    ta = 1000 * float(np.mean([o["dt"] for o in after]))
    print("\n".join(lines))
    print(f"    속도: 전 {tb:7.2f} ms/scan  ->  후 {ta:7.2f} ms/scan   ({tb/ta:.2f}x)")
    return worst, tb, ta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before-ref", required=True,
                    help="수정 전 core/doas_fit.py를 꺼내올 git ref. **필수** — 예전엔 기본값이 "
                         "HEAD였는데, 변경이 머지된 뒤로는 '지금 코드 vs 지금 코드'가 되어 "
                         "아무것도 검증하지 않고 PASS를 찍는다. 밀집 W 제거 대조의 기준은 "
                         "944c7bd(직전) / 적용본은 33f6f3e.")
    ap.add_argument("--alpha-root", default=r"C:\GHL\2026 yeosu\Output",
                    help="캠페인 Output 폴더. 그 아래 alpha/10s/{cold,hot/ch1,hot/ch2}/<날짜>/ 를 읽는다.")
    ap.add_argument("--nfiles", type=int, default=2, help="케이스당 알파 파일 수")
    ap.add_argument("--max-scans", type=int, default=700, help="케이스당 스캔 상한(0=제한없음)")
    args = ap.parse_args()

    DoasFitterBefore = load_fitter_before(args.before_ref)
    print(f"수정 전 = {args.before_ref}:core/doas_fit.py (밀집 W)   수정 후 = 작업트리 (가중 벡터)")

    worst_all, speedups, skipped, ncase = 0.0, [], [], 0
    for label, subdir, alpha_dir, day, pixel_idx, poly_order in CASES:
        files = sorted(glob.glob(os.path.join(args.alpha_root, alpha_dir, day, "*_alpha_trace.dat")))[:args.nfiles]
        if not files:
            skipped.append(f"{label}  ({alpha_dir}\\{day} 없음)")
            continue
        eng = build_engine(subdir, SPECIES)
        scans = load_real_alpha_scans(files, pixel_idx)
        if args.max_scans and len(scans) > args.max_scans:
            scans = scans[:args.max_scans]
        n = len(pixel_idx)
        print(f"\n=== {label}  -  {len(scans)} scans, {n}px, poly{poly_order} ===", flush=True)
        for warm in (True, False):
            print(f"  [{'warm' if warm else 'cold'}-start]", flush=True)
            common = (eng, pixel_idx, scans, REF_PROPS, poly_order, STEP_LIMIT, FIXED_E_F, warm)
            before = run_varpro(*common, fitter_cls=DoasFitterBefore, W0=np.eye(n))
            after = run_varpro(*common, W0=np.ones(n))
            d, tb, ta = compare(label, before, after)
            worst_all = max(worst_all, d)
            speedups.append(tb / ta)
            ncase += 1

    print("\n" + "=" * 70)
    for s in skipped:
        print(f"  SKIP: {s}")
    if not ncase:
        print("  실행된 케이스 없음  -  캠페인 폴더가 연결돼 있는지 확인")
        return 2
    print(f"  전체 {ncase}개 조건에서 max|diff| = {worst_all:.3e}")
    print(f"  속도: {np.min(speedups):.2f}x ~ {np.max(speedups):.2f}x (중앙값 {np.median(speedups):.2f}x)")
    if worst_all == 0.0:
        print("  PASS  -  수정 전후 결과 비트단위 동일")
        return 0
    print("  FAIL  -  결과가 달라졌다. 대각 가중 가정이 깨진 호출부가 있는지 확인할 것")
    return 1


if __name__ == "__main__":
    sys.exit(main())
