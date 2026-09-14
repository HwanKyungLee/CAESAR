"""해석적(Golub-Pereyra) 자코비안 도입 전/후 대조 - 실캠페인 알파.

무엇이 달라졌나
---------------
`execute_varpro_fit`의 비선형 탐색이 scipy 기본 **2점 유한차분** 자코비안을 쓰고
있었다(외부 차원 d면 자코비안 1회에 목적함수 d+1회). 실측: 실제 프리셋(d=2)에서
목적함수 호출의 67%가 유한차분용이고, 목적함수가 총 시간의 66~72%
-> 유한차분이 총 시간의 약 47%.

바뀐 것:
  * ±Neg ON(=기체 계수 하한 -inf, 무제약)일 때 선형 단계를 QR로 풀고, 그 Q/R을
    자코비안의 투영 P⊥=I-QQ^T 와 A⁺ᵀ=QR⁻ᵀ 에 그대로 재활용
  * 자코비안 = Golub-Pereyra **완전** 식 (Kaufman 근사 아님):
        J_k = -[ P⊥ D_k c + A⁺ᵀ D_k^T r ]
    2항을 빼면(Kaufman) 유한차분과 40~67% 어긋나 검증을 게이트로 못 쓴다.
    2항은 k-벡터 삼각해 하나 + Q 곱 하나라 사실상 공짜.
  * ±Neg OFF(하한 0)면 해가 경계에 붙는 순간 투영이 미분 불가능해져 해석해가
    틀린 값을 준다 -> 그때는 기존 유한차분 경로 그대로.

왜 "비트동일"로 검증하지 않나
-----------------------------
자코비안은 최적화가 **어느 방향으로 움직일지**를 정한다. 바꾸면 같은 답에
다른 경로로 도착하므로 스캔별 끝자리가 달라진다. 그래서 두 단계로 본다:

  1. **자코비안 자체가 맞는가** - 실제 핏 도중 매 자코비안을 scipy
     `approx_derivative`(2점)와 대조. 유한차분 자체의 정확도가 ~1e-7이므로
     상대차 ~1e-6이면 일치로 본다. 이게 1차 게이트.
  2. **결과가 같은가** - cold-start를 **판정 기준**으로 쓴다. 매 스캔을 0에서
     새로 시작하니 스캔간 캐리오버가 없어, 차이가 누적되지 않는다(이 저장소가
     이미 확인한 "cold-start는 r>0.9999"가 그 근거). warm-start는 캐리오버
     경로의존성이 섞여 자코비안 탓과 구분이 안 되므로 **보고만** 한다.

실행
----
    python validate_analytic_jacobian.py --before-ref aece86f                 # 전체
    python validate_analytic_jacobian.py --before-ref aece86f --nfiles 1 --max-scans 120   # 빠른 스모크
    python validate_analytic_jacobian.py --before-ref HEAD~1

종료코드 0 = 자코비안 일치 + cold-start 결과가 허용오차 안.
"""
from __future__ import annotations
import argparse, glob, importlib.util, os, subprocess, sys, tempfile
import numpy as np
from scipy.optimize._numdiff import approx_derivative

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
for _p in (_REPO_ROOT, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import core.doas_fit as df
from bench_common import build_engine, run_varpro, load_real_alpha_scans

LINKED = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2",
          "t_ref": 25.0, "t_coeff": 0.0}
ANCHOR = {"sh_mode": "Limit", "sh_val": "-2.0, 2.0", "sq_mode": "Limit", "sq_val": "-0.02, 0.02",
          "t_ref": 25.0, "t_coeff": 0.0}
REF_PROPS = {"NO2": ANCHOR, "CHOCHO": dict(LINKED), "H2O": dict(LINKED)}
SPECIES = {"NO2": ("NO2", 1.0), "CHOCHO": ("CHOCHO", -1.0), "H2O": ("H2O-HITRAN", 1.0)}

# Hot 채널 매핑은 README.md 참조 - ROI1(600-1270px, poly4)=PNs(ch2),
# ROI2(900-1450px, poly3)=ANs(ch1).
CASES = [
    ("cold 2026-05-17 (worst wall-hugging day)", "cold", os.path.join("alpha", "10s", "cold"),
     "2026-05-17", np.arange(775, 1550), 4),
    ("cold 2026-06-05 (calm day)", "cold", os.path.join("alpha", "10s", "cold"),
     "2026-06-05", np.arange(775, 1550), 4),
    ("hot ROI1/PNs 2026-06-05", "roi1", os.path.join("alpha", "10s", "hot", "ch2"),
     "2026-06-05", np.arange(600, 1270), 4),
    ("hot ROI2/ANs 2026-06-05", "roi1", os.path.join("alpha", "10s", "hot", "ch1"),
     "2026-06-05", np.arange(900, 1450), 3),
]
FIXED_E_F, STEP_LIMIT = 0.12, 0.5

# 게이트(cold-start 기준). shift는 핏레인지 대비 무시할 수준, 농도는 상대오차.
TOL_JAC_REL = 1e-4     # 유한차분 자체가 ~1e-7 수준이라 1e-6이 정상, 1e-4면 확실히 버그
TOL_SHIFT_PX = 0.01
TOL_CONC_REL = 1e-3


def load_fitter_before(ref: str):
    """수정 전 core/doas_fit.py를 git에서 꺼내 DoasFitter만 임포트한다."""
    src = subprocess.run(["git", "show", f"{ref}:core/doas_fit.py"], cwd=_REPO_ROOT,
                         capture_output=True, check=True).stdout
    fd, path = tempfile.mkstemp(suffix="_doas_fit_before.py")
    with os.fdopen(fd, "wb") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("doas_fit_before", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DoasFitter


class JacSpy:
    """핏 도중 불리는 모든 해석적 자코비안을 유한차분과 대조한다.
    `core.doas_fit.least_squares`를 감싸서 자코비안 함수를 가로챈다."""
    def __init__(self):
        self.worst = 0.0
        self.count = 0
        self._orig = df.least_squares

    def __enter__(self):
        def spy(fun, x0, **kw):
            jac = kw.get("jac")
            if callable(jac):
                x = np.asarray(x0, dtype=float)
                J = jac(x)
                Jfd = approx_derivative(fun, x, method="2-point",
                                        bounds=kw.get("bounds", (-np.inf, np.inf)))
                scale = max(float(np.abs(Jfd).max()), 1e-300)
                self.worst = max(self.worst, float(np.abs(J - Jfd).max()) / scale)
                self.count += 1
            return self._orig(fun, x0, **kw)
        df.least_squares = spy
        return self

    def __exit__(self, *exc):
        df.least_squares = self._orig
        return False


def compare(before, after, gases):
    sh_b = np.array([o["shift"] for o in before]); sh_a = np.array([o["shift"] for o in after])
    sq_b = np.array([o["squeeze"] for o in before]); sq_a = np.array([o["squeeze"] for o in after])
    d_sh = float(np.max(np.abs(sh_b - sh_a)))
    d_sq = float(np.max(np.abs(sq_b - sq_a)))
    corr = float(np.corrcoef(sh_b, sh_a)[0, 1]) if np.std(sh_b) > 0 and np.std(sh_a) > 0 else float("nan")
    worst_rel = 0.0
    conc_lines = []
    for g in gases:
        a = np.array([o["c"][g] for o in before]); b = np.array([o["c"][g] for o in after])
        denom = np.mean(np.abs(a))            # 스캔별 상대오차는 0 근처에서 발산 -> 평균 크기로 정규화
        rel = float(np.max(np.abs(a - b)) / denom) if denom > 0 else 0.0
        worst_rel = max(worst_rel, rel)
        conc_lines.append(f"      {g:7s} max|diff|/mean|c| = {rel:.2e}")
    tb = 1000 * float(np.mean([o["dt"] for o in before]))
    ta = 1000 * float(np.mean([o["dt"] for o in after]))
    print(f"      shift   max|diff| = {d_sh:.3e} px   corr = {corr:.8f}")
    print(f"      squeeze max|diff| = {d_sq:.3e}")
    print("\n".join(conc_lines))
    print(f"      speed: before {tb:7.2f} ms/scan  ->  after {ta:7.2f} ms/scan   ({tb/ta:.2f}x)")
    return d_sh, worst_rel, tb / ta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before-ref", required=True,
                    help="수정 전 core/doas_fit.py를 꺼내올 git ref. **필수** — 예전엔 기본값이 "
                         "HEAD였는데, 변경이 머지된 뒤로는 '지금 코드 vs 지금 코드'가 되어 "
                         "아무것도 검증하지 않고 PASS를 찍는다. 해석적 자코비안 대조의 기준은 "
                         "aece86f(직전) / 적용본은 5d42ad4.")
    ap.add_argument("--alpha-root", default=r"C:\GHL\2026 yeosu\Output",
                    help="캠페인 Output 폴더. 그 아래 alpha/10s/{cold,hot/ch1,hot/ch2}/<날짜>/ 를 읽는다.")
    ap.add_argument("--nfiles", type=int, default=2)
    ap.add_argument("--max-scans", type=int, default=500)
    args = ap.parse_args()

    Before = load_fitter_before(args.before_ref)
    print(f"BEFORE = {args.before_ref}:core/doas_fit.py (finite-difference jac)   "
          f"AFTER = working tree (analytic Golub-Pereyra jac)")

    fails, speedups, skipped = [], [], []
    jac_worst, jac_n, ncase = 0.0, 0, 0
    for label, subdir, alpha_dir, day, pixel_idx, poly_order in CASES:
        files = sorted(glob.glob(os.path.join(args.alpha_root, alpha_dir, day, "*_alpha_trace.dat")))[:args.nfiles]
        if not files:
            skipped.append(f"{label}  (no files under {alpha_dir}\\{day})")
            continue
        eng = build_engine(subdir, SPECIES)
        scans = load_real_alpha_scans(files, pixel_idx)
        if args.max_scans and len(scans) > args.max_scans:
            scans = scans[:args.max_scans]
        n = len(pixel_idx)
        print(f"\n=== {label} | {len(scans)} scans, {n}px, poly{poly_order} ===", flush=True)
        for warm in (False, True):
            tag = "warm-start (report only)" if warm else "cold-start (GATE)"
            print(f"  [{tag}]", flush=True)
            common = (eng, pixel_idx, scans, REF_PROPS, poly_order, STEP_LIMIT, FIXED_E_F, warm)
            before = run_varpro(*common, fitter_cls=Before, W0=np.ones(n))
            after = run_varpro(*common, W0=np.ones(n))          # 타이밍용 - 계측 없음
            # 자코비안 검증은 **별도 패스**로. spy가 핏 안에서 유한차분을 한 번 더
            # 돌리므로 같은 패스에서 시간을 재면 'after'가 느려 보인다.
            n_spy = min(60, len(scans))
            with JacSpy() as spy:
                run_varpro(eng, pixel_idx, scans[:n_spy], REF_PROPS, poly_order,
                           STEP_LIMIT, FIXED_E_F, warm, W0=np.ones(n))
            jac_worst = max(jac_worst, spy.worst); jac_n += spy.count
            print(f"      jacobian vs finite-diff: {spy.count} checks, max rel = {spy.worst:.2e}")
            d_sh, rel, sp = compare(before, after, eng.gas_list)
            speedups.append(sp)
            ncase += 1
            if spy.worst > TOL_JAC_REL:
                fails.append(f"{label} [{tag}] jacobian rel {spy.worst:.2e} > {TOL_JAC_REL:.0e}")
            if not warm:
                if d_sh > TOL_SHIFT_PX:
                    fails.append(f"{label} [cold-start] shift diff {d_sh:.3e} px > {TOL_SHIFT_PX}")
                if rel > TOL_CONC_REL:
                    fails.append(f"{label} [cold-start] conc rel {rel:.2e} > {TOL_CONC_REL:.0e}")

    print("\n" + "=" * 70)
    for s in skipped:
        print(f"  SKIP: {s}")
    if not ncase:
        print("  no case ran - check that the campaign folder is connected")
        return 2
    print(f"  jacobian checks: {jac_n}, worst rel vs finite-diff = {jac_worst:.2e} (tol {TOL_JAC_REL:.0e})")
    print(f"  speedup: {np.min(speedups):.2f}x ~ {np.max(speedups):.2f}x (median {np.median(speedups):.2f}x)")
    if fails:
        print(f"  FAIL ({len(fails)}):")
        for f in fails:
            print(f"    - {f}")
        return 1
    print(f"  PASS - jacobian matches finite differences; cold-start results within "
          f"{TOL_SHIFT_PX} px / {TOL_CONC_REL:.0e} rel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
