#!/usr/bin/env python
"""DOAS 벤치마크(249케이스)를 **Augur 운영 핏 경로**로 돌려 submission 을 낸다.

무엇을 쓰나
----------
`core.doas_fit.DoasFitter.execute_varpro_fit` — production `param_optimizer.fit_scan`
이 부르는 그 함수다. 얇은 래퍼는 `diagnostics/etalon_freq_2026-09/etalon_freq.py`
의 `Channel` 과 같은 호출 규약을 쓴다(그쪽은 `fit_scan` 과 바이트 일치가 매
실행 자체검증된다).

벤치마크가 주는 것과 Augur 의 차이 — 미리 밝혀 둔다
--------------------------------------------------
* 벤치마크 전방모델은 σ 를 **선형보간**으로 옮긴다. Augur 는 **3차**를 쓴다.
  shift≠0 인 A군 케이스에서 이 차이가 그대로 오차로 나온다. 구현 결함이 아니라
  보간 차수 차이이므로, A군은 shift=0 / shift≠0 을 갈라서 읽어야 한다.
* squeeze 는 manifest 가 준다 → `sq_mode="Fix"` 로 고정한다(추정하지 않는다).
* 에탈론 주파수도 manifest 가 준다 → 검출하지 않고 그 값을 고정한다.

보고 불확도 두 판본
------------------
Augur 는 오차를 두 개 낸다. 어느 쪽이 "보고 불확도" 인지가 §3 의 논점이라
**둘 다** 제출한다.
  `--sigma lin`   : 조건부 선형 오차 `c_perr` (기존 `<gas>_Error` 열)
  `--sigma joint` : shift·squeeze 결합 오차 `perr_joint` (`<gas>_ErrorJoint`)

재현
----
    python diagnostics/doas_benchmark_2026-09/run_augur_benchmark.py \
        --bench "C:/GHL/benchmark/doas_benchmark_v1" --sigma joint --out sub_joint.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scipy.interpolate import interp1d

from core.doas_fit import DoasFitter, alpha_fit_scale
from core.engine import UniversalEngine
from core.parallel import max_workers

GASES = ("NO2", "CHOCHO", "H2O")
SHIFT_LIMIT = 8.0          # 진값이 ±4 px 안에 있다 — 상자를 그보다 넉넉히
STEP_LIMIT = 8.0           # 한 스캔 보폭 제한. 벤치마크는 시계열이 아니라 제한 없음과 같게


def load_channel(bench, channel):
    """그 채널의 파장축과 기체별 σ (벤치마크가 준 격자 그대로)."""
    path = os.path.join(bench, "reference", f"cross_sections_{channel}.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    wave = np.array([float(r["wavelength_nm"]) for r in rows])
    sig = {g: np.array([float(r["sigma_" + g + "_cm2"]) for r in rows]) for g in GASES}
    return wave, sig


def build_engine(wave, sig, kind="cubic", gases=GASES):
    """`za_gas_sigma.build_engine` 과 같은 구성 — 단면은 이미 ILS 적용본이다.

    파일이 아니라 배열로 등록한다(벤치마크가 CSV 한 장에 세 기체를 준다). 등록
    이후 경로는 운영과 동일하다: 3차 보간자 + 피크 정규화 + `apply_ils_convolution(0)`.
    """
    eng = UniversalEngine()
    eng.set_wavelength_axis(wave)
    # ⚠ **요청된 기체만** 등록한다. `DoasFitter.gas_active_in_window` 는
    # ref_properties 에 없는 이름도 True 를 돌려주므로(active_bands 가 비면 활성),
    # 엔진에 들고만 있어도 그 기체는 핏에 **들어간다**. 세 기체를 다 등록해 두면
    # C 군의 "흡수체 누락" 케이스가 누락이 아니게 된다 — 2026-09-21 실측으로
    # 걸렸다(편향 10.4 % 로 나왔는데 실제로는 누락 자체가 없었다).
    for g in gases:
        v = np.asarray(sig[g], float)
        eng.raw_references[g] = v
        eng.interpolators[g] = interp1d(np.arange(len(v)), v, kind=kind,
                                        fill_value="extrapolate")
        eng.scaling_factors[g] = float(np.max(np.abs(v))) or 1.0
        eng.multipliers[g] = 1.0
        eng.gas_list.append(g)
    eng.apply_ils_convolution(0.0)
    if kind != "cubic":
        # `UniversalEngine._set_interpolator` 는 3차를 **하드코딩**한다(단일 출처).
        # 그래서 여기서 덮으려면 ILS 적용 **뒤**여야 한다 — 그 호출이 보간자를
        # 다시 만든다. 진단용 스위치일 뿐 운영 경로는 3차 그대로다.
        from scipy.interpolate import make_interp_spline
        for g in eng.gas_list:
            v = np.asarray(eng.raw_references[g], float)
            x = np.arange(len(v))
            eng.interpolators[g] = interp1d(x, v, kind=kind, bounds_error=False,
                                            fill_value="extrapolate")
            eng.ref_derivatives[g] = make_interp_spline(x, v, k=1).derivative()
    return eng


def props(gases, squeeze):
    """NO2 앵커 + 동반종 Link — 운영 FitSet 구조. squeeze 는 manifest 값으로 **고정**."""
    sq = f"{squeeze - 1.0:.10g}"          # Augur 의 squeeze 는 1 로부터의 편차
    p = {"NO2": {"sh_mode": "Limit", "sh_val": f"-{SHIFT_LIMIT}, {SHIFT_LIMIT}",
                 "sq_mode": "Fix", "sq_val": sq, "t_ref": 25.0, "t_coeff": 0.0}}
    for g in gases:
        if g != "NO2":
            p[g] = {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link",
                    "sq_val": "NO2", "t_ref": 25.0, "t_coeff": 0.0}
    return p


def fit_case(eng, fitter, y, px, centre, gases, squeeze, order, e_f, seed_grid):
    """격자 시딩 → VarPro. 운영 `fit_scan` 의 controlled_start=None 경로와 같은 규약."""
    s = alpha_fit_scale(y)
    ys = y * s
    w = np.ones(len(px))
    rp = props(gases, squeeze)
    best = None
    for sh0 in seed_grid:
        act, fx, lk, t0, lb, ub = fitter.setup_fit_parameters(rp, sh0, [sh0, 1.0], STEP_LIMIT)
        try:
            out, diag = fitter.execute_varpro_fit(
                px, ys, w, act, fx, lk, t0, lb, ub, order, float(e_f),
                centre, 1.0, rp, 25.0, 0.0, False,
                allow_negative_gas=True, return_diagnostics=True)
        except Exception:
            continue
        obj = float(diag.get("objective_final", np.inf))
        if best is None or obj < best[0]:
            best = (obj, out, diag, act, lb, ub)
    return best


def run(bench, sigma_kind, out_path, limit=None, kind="cubic"):
    man = list(csv.DictReader(open(os.path.join(bench, "cases", "manifest.csv"),
                                   encoding="utf-8")))
    Z = np.load(os.path.join(bench, "cases", "spectra.npz"))
    chans, waves = {}, {}
    rows = []
    seed_grid = np.arange(-6.0, 6.001, 1.0)
    for i, r in enumerate(man):
        if limit and i >= limit:
            break
        ch = r["channel"]
        gases = tuple(r["gases_to_fit"].split(","))
        key = (ch, gases)
        if key not in chans:
            if ch not in waves:
                waves[ch] = load_channel(bench, ch)
            wave, sig = waves[ch]
            eng = build_engine(wave, sig, kind, gases)
            chans[key] = (eng, DoasFitter(eng), np.asarray(Z[f"pixel__{ch}"], float))
        eng, fitter, px = chans[key]
        y = np.asarray(Z[r["case_id"]], float)
        best = fit_case(eng, fitter, y, px, float(r["centre_pixel"]),
                        gases, float(r["squeeze_factor"]), int(r["fit_poly_order"]),
                        float(r["fit_etalon_f"]), seed_grid)
        if best is None:
            rows.append(dict(case_id=r["case_id"], NO2=np.nan, NO2_sigma=np.nan,
                             shift_px=np.nan, shift_sigma=np.inf,
                             at_grid_edge=True, termination="FAILED"))
            continue
        _, out, diag, act, lb, ub = best
        gi = eng.gas_list.index("NO2")
        c = float(out[2][gi]) / alpha_fit_scale(y)
        c = c / eng.scaling_factors["NO2"] * eng.multipliers["NO2"]
        if sigma_kind == "joint":
            pj = diag.get("perr_joint") or []
            e = float(pj[gi]) if gi < len(pj) else np.nan
        else:
            e = float(out[6][gi])
        e = abs(e) / alpha_fit_scale(y) / eng.scaling_factors["NO2"] * eng.multipliers["NO2"]
        sh = float(out[0][gi])
        te = diag.get("theta_err_joint") or {}
        ssig = float(te.get("NO2_sh", np.nan))
        if not np.isfinite(ssig):
            ssig = np.inf
        k = act.index("NO2_sh") if "NO2_sh" in act else None
        edge = bool(k is not None and min(abs(sh - lb[k]), abs(sh - ub[k]))
                    <= 1e-6 * max(1.0, abs(lb[k]), abs(ub[k])))
        rows.append(dict(case_id=r["case_id"], NO2=c, NO2_sigma=e, shift_px=sh,
                         shift_sigma=ssig, at_grid_edge=edge,
                         termination=str((diag.get("solver_termination") or {}).get("status", ""))))
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(man)}", flush=True)

    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"→ {out_path}  ({len(rows)} rows, sigma={sigma_kind})")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", required=True)
    ap.add_argument("--sigma", choices=("lin", "joint"), default="joint")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--interp", choices=("cubic", "linear"), default="cubic",
                    help="레퍼런스 보간 차수. 운영은 cubic — 벤치마크 전방모델은 linear 다")
    a = ap.parse_args()
    run(a.bench, a.sigma, a.out, a.limit, a.interp)


if __name__ == "__main__":
    main()
