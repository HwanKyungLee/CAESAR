"""core/refit.py — 저장된 결과의 한 스캔을 **그때 설정 그대로** 다시 핏해서 잔차를 얻는다.

왜 필요한가
-----------
Result Lab에서 이상한 점을 클릭했을 때 "왜 이상한가"의 답은 잔차 구조에 있다. 그런데
결과 `.dat`에는 스캔당 RMS만 있고 **잔차 벡터도 핏 계수도 없다**(저장 시 `Params` 컬럼을
drop한다). 그래서 그 스캔을 다시 핏하는 수밖에 없는데 — *지금* GUI 설정으로 계산한 잔차는
화면에 떠 있는 *그때* 농도와 대응하지 않는다. **조용히 틀린 그림**이 된다.

그래서 규칙이 하나다:

    그때 설정(`.meta.json`)을 그대로 복원해서만 핏한다.
    복원이 불완전하거나 재현이 안 되면 **잔차를 아예 안 보여준다.**

거부 사유 5종(호출부는 이 문자열을 사람에게 그대로 보여주면 된다):
  1. meta 없음        — 레거시 파일. `tools/backfill_meta.py`로 생성 가능
  2. legacy meta      — `.dat` 헤더에서 복원한 부분 설정(runid `L…`)이라 설정 전량이 아님
  3. 캘리브 확정 불가  — wavecal/레퍼런스를 못 찾거나, 같은 이름이 여러 채널 폴더에 있어 확정 불가
  4. 알파 행 없음      — 옆에 알파가 없거나 그 row_idx가 없음
  5. 재현 실패        — 재핏 농도가 저장 농도와 `REPRO_TOL_REL` 넘게 어긋남

자기검증: `python -m core.refit`
"""
from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd

from core import fitset_builder as FB
from core import param_optimizer as PO
from core.data_io import DataIO
from core.doas_fit import DoasFitter
from core.paths import REFERENCE_DIR, WV_CAL_DIR
from core.run_meta import meta_to_cfg, read_meta

# 재현 판정 허용오차(상대). 재핏 농도가 저장 농도와 이보다 벌어지면 잔차를 거부한다.
# 1%는 "웜스타트 캐리오버를 복원 못 해 다른 국소해로 갔다"를 잡기엔 충분히 좁고,
# 부동소수·BLAS 차이로 오경보를 내기엔 충분히 넓다. 실측하며 조일 것.
REPRO_TOL_REL = 0.01

# 알파의 파장축과 wavecal 후보가 "같은 채널"인지 볼 때의 허용 오차(nm).
# 파장보정 검증 기준선이 ±0.07 nm(Hg 4라인)이므로 그보다 넉넉하되, 채널이 다르면
# 수 nm씩 어긋나므로 채널 구별에는 충분하다.
_WAVE_MATCH_NM = 0.5


def load_wavecal_array(path):
    """wavecal 파일 → 1D nm 배열. 실패하면 None.

    ponytail: 같은 파서가 `gui/app_window._load_wavecal_array`와
    `tools/optimize_params.load_wavecal`에도 복제돼 있다(각 파일에 "복제"라고 적혀 있음).
    core에 있는 이 구현이 단일 출처가 되어야 하고 저 둘은 여기로 위임시키면 된다 —
    이번 변경 범위 밖이라 4번째 사본을 만들지 않는 선에서 멈춘다.
    """
    try:
        try:
            df = pd.read_csv(path, sep=r"\s+", header=None)
        except Exception:                       # noqa: BLE001
            df = pd.read_csv(path, sep=",", header=None)
        for i in range(df.shape[1]):
            col = pd.to_numeric(df.iloc[:, i], errors="coerce").dropna()
            if len(col) > 10:
                return col.values.flatten()
    except Exception:                           # noqa: BLE001
        pass
    return None


def read_alpha_row(path, row_idx):
    """alpha_trace.dat에서 **row_idx 컬럼값이 일치하는** 행 -> (wave, alpha, px_start, T, P).

    주의: `DataIO.load_alpha_trace_row_full`은 **몇 번째 데이터행**으로 찾는다(위치 인덱스).
    결과 표의 `row_idx`는 컬럼에 적힌 값이라 둘이 같다는 보장이 없다 — 여기선 값으로 찾는다.
    헤더 해석(px_start·T/P 열 위치)은 `DataIO._alpha_layout`이 단일 출처다.
    """
    first_px, t_idx, p_idx, px_start, wave = DataIO._alpha_layout(path)
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.rstrip("\n")
            if not s.strip() or s.startswith("#") or s.startswith("row_idx"):
                continue
            parts = s.split("\t")
            try:
                if int(float(parts[0])) != int(row_idx):
                    continue
            except (ValueError, IndexError):
                continue
            alpha = np.array([float(v) for v in parts[first_px:]], dtype=float)
            t = float(parts[t_idx]) if t_idx < len(parts) else float("nan")
            p = float(parts[p_idx]) if p_idx < len(parts) else float("nan")
            if wave is None or len(wave) != len(alpha):
                wave = np.arange(len(alpha), dtype=float)
            return wave, alpha, int(px_start), t, p
    return None, None, 0, float("nan"), float("nan")


def resolve_calibration_dir(meta, alpha_wave, px_start, roots=None):
    """meta의 wavecal basename이 어느 채널 폴더의 것인지 **알파 자신의 파장축으로** 확정.

    meta는 머신 독립을 위해 basename만 갖고 있는데(runid 계약),
    `Ref_NO2_Dynamic-ILS-Applied.dat`·`Calib_20260619_…txt`는 cold/roi1/roi2에 **같은
    이름·다른 내용**으로 존재한다. 이름만 보고 고르면 다른 채널 단면으로 핏하게 된다.

    알파 파일은 자기 채널의 파장축을 헤더에 갖고 있으므로, 후보 wavecal을 각각 읽어
    `wavecal[px_start:px_start+N]`이 그 축과 맞는지 보면 채널이 **데이터로** 정해진다.

    반환 (dir, reason). dir=None이면 reason이 거부 사유.
    """
    name = ((meta.get("calibration") or {}).get("wavecal") or "").strip()
    if not name:
        return None, "meta에 wavecal이 기록돼 있지 않음"
    roots = roots or [WV_CAL_DIR, REFERENCE_DIR]
    cands = []
    for root in roots:
        cands += glob.glob(os.path.join(root, "**", name), recursive=True)
    cands = sorted(set(cands))
    if not cands:
        return None, "wavecal '%s'을(를) reference_data에서 못 찾음" % name
    if len(cands) == 1:
        return os.path.dirname(cands[0]), ""

    if alpha_wave is None or not len(alpha_wave):
        return None, "wavecal '%s'이 %d곳에 있는데 알파 파장축이 없어 확정 불가" % (name, len(cands))
    matched = []
    for c in cands:
        arr = load_wavecal_array(c)
        if arr is None or len(arr) < px_start + len(alpha_wave):
            continue
        seg = np.asarray(arr[px_start:px_start + len(alpha_wave)], dtype=float)
        if np.max(np.abs(seg - np.asarray(alpha_wave, dtype=float))) <= _WAVE_MATCH_NM:
            matched.append(c)
    if len(matched) == 1:
        return os.path.dirname(matched[0]), ""
    if not matched:
        return None, ("wavecal '%s' 후보 %d개 중 알파의 파장축과 맞는 게 없음 "
                      "(채널이 다른 파일일 수 있음)" % (name, len(cands)))
    return None, ("wavecal '%s' 후보 %d개가 알파 축과 모두 일치 — 어느 채널 폴더인지 확정 불가"
                  % (name, len(matched)))


def _fit_indices(cfg, wave, px_start):
    """meta의 핏창 -> 알파 배열 인덱스 (px는 검출기 픽셀번호라 px_start를 빼야 한다).

    불변식: `pxNNN` 헤더를 무시하면 조용히 틀린 창을 핏한다
    (docs/augur_improvements_progress.md "절대 깨뜨리지 말 것" 7).
    """
    unit = (cfg.get("fit_unit") or "nm").lower()
    n = len(wave)
    if unit.startswith("px"):
        lo, hi = int(float(cfg["f_min"])), int(float(cfg["f_max"]))
        i0, i1 = lo - px_start, hi - px_start
    else:
        lo, hi = float(cfg["fit_start_nm"]), float(cfg["fit_end_nm"])
        i0 = int(np.abs(wave - lo).argmin())
        i1 = int(np.abs(wave - hi).argmin())
    i0, i1 = sorted((int(i0), int(i1)))
    return max(0, i0), min(n - 1, i1)


def _driver(cfg):
    """정합을 주도하는 종 = Link 대상이 되는 종. 없으면 Fix가 아닌 첫 종."""
    props = cfg.get("ref_props") or {}
    for p in props.values():
        if (p.get("sh_mode") or "") == "Link" and p.get("sh_val") in props:
            return p["sh_val"]
    for name, p in props.items():
        if (p.get("sh_mode") or "") != "Fix":
            return name
    return next(iter(props), None)


def refit_row(fit_path, alpha_path, row_idx, *, saved_conc=None, saved_shift=None,
              saved_squeeze=None, tol_rel=REPRO_TOL_REL):
    """저장된 결과의 한 행을 그때 설정으로 재핏 -> 잔차. 실패하면 사유를 돌려준다.

    `saved_*`는 화면(결과 표)에 떠 있는 그 행의 값이다. shift/squeeze는 **웜스타트
    캐리오버를 복원할 수 없으므로** 시드로 주입한다(Augur 소개 §10-9 경로의존성).
    `saved_conc`는 재현 검증용 — 재핏이 그때 농도를 못 맞추면 그 잔차는 다른 해의 잔차다.

    반환: {"ok": True, wave/alpha/model/residual/rms/conc/runid} 또는
          {"ok": False, "reason": "..."}
    """
    meta = read_meta(fit_path)
    if not meta:
        return {"ok": False, "reason": "잔차 불가: .meta.json 없음 "
                                       "(레거시 결과 — tools/backfill_meta.py로 생성 가능)"}
    if str(meta.get("runid") or "").startswith("L") or \
            ((meta.get("provenance") or {}).get("meta_source") != "live"):
        return {"ok": False, "reason": "잔차 불가: legacy meta(설정 일부 미상) — "
                                       "부분 설정으로 그린 잔차는 이 농도와 대응하지 않음"}

    wave, alpha, px_start, t_row, p_row = read_alpha_row(alpha_path, row_idx)
    if alpha is None:
        return {"ok": False, "reason": "잔차 불가: 알파에 row %s 없음" % row_idx}

    ref_dir, why = resolve_calibration_dir(meta, wave, px_start)
    if ref_dir is None:
        return {"ok": False, "reason": "잔차 불가: " + why}
    cfg, missing = meta_to_cfg(meta, ref_dir)
    if missing:
        return {"ok": False, "reason": "잔차 불가: 파일 못 찾음 — " + ", ".join(missing[:3])}

    eng, _ = FB.build_engine(cfg["wl_path"], cfg["refs"], load_wavecal_array)
    want = [r["name"] for r in cfg["refs"]]
    if list(eng.gas_list) != want:
        return {"ok": False, "reason": "잔차 불가: 레퍼런스 로딩 실패 — 기대 %s, 실제 %s"
                                       % (want, list(eng.gas_list))}

    i0, i1 = _fit_indices(cfg, wave, px_start)
    if i1 - i0 < 10:
        return {"ok": False, "reason": "잔차 불가: 핏창이 알파 범위 밖(idx %d..%d)" % (i0, i1)}

    # 농도 환산 온도: gas_temp(>0)가 있으면 그걸, 없으면 행 실측값.
    # (gui/worker.py `gas_temp_override`와 같은 규약 — 다르면 ppb가 통째로 어긋난다.)
    gt = float(cfg.get("gas_temp") or 0)
    t_used = gt if gt > 0 else t_row
    if not np.isfinite(t_used) or not np.isfinite(p_row):
        return {"ok": False, "reason": "잔차 불가: 그 행의 T/P를 알파에서 못 읽음"}

    target = _driver(cfg)
    if not target:
        return {"ok": False, "reason": "잔차 불가: meta에 레퍼런스가 없음"}

    start = None
    if saved_shift is not None and saved_squeeze is not None \
            and np.isfinite(saved_shift) and np.isfinite(saved_squeeze):
        start = (float(saved_shift), float(saved_squeeze))

    try:
        out = PO.fit_scan(eng, DoasFitter(eng), cfg["ref_props"], wave, alpha,
                          t_used, p_row, i0, i1, int(cfg["poly_deg"]),
                          float(cfg["step_limit"]), target=target,
                          allow_negative_gas=bool(cfg["allow_negative_gas"]),
                          controlled_start=start, return_model=True)
    except Exception as e:                      # noqa: BLE001
        return {"ok": False, "reason": "잔차 불가: 재핏 실패 — %s" % e}

    off = []
    for gas, saved in (saved_conc or {}).items():
        got = (out.get("conc_all") or {}).get(gas)
        if got is None or saved is None or not np.isfinite(saved) or not np.isfinite(got):
            continue
        denom = max(abs(saved), 1e-12)
        if abs(got - saved) / denom > tol_rel:
            off.append("%s %.4g->%.4g" % (gas, saved, got))
    if off:
        return {"ok": False,
                "reason": ("잔차 불가: 재현 실패(웜스타트 이력을 복원 못 함) — "
                           + ", ".join(off[:3]) + " / 허용 %.1f%%" % (tol_rel * 100))}

    return {"ok": True, "runid": meta.get("runid"),
            "wave": out["wavelength_nm"], "alpha": np.asarray(alpha, float)[i0:i1 + 1],
            "model": out["model"], "residual": out["residual"],
            "rms": out["rms"], "rms_sig": out.get("rms_sig"),
            "conc": out.get("conc_all") or {}, "target": target,
            "shifts": out.get("shifts") or {}}


def _demo():
    """자기검증: 합성 스캔 하나로 재핏이 잔차를 복원하는지 + 거부 5종이 실제로 막는지."""
    import shutil
    import tempfile
    from core import run_meta as RM

    root = tempfile.mkdtemp(prefix="refit-demo-")
    try:
        cal = os.path.join(root, "cal")
        os.makedirs(cal)
        npx = 512
        wave_full = 430.0 + 0.04 * np.arange(npx)
        np.savetxt(os.path.join(cal, "Calib_demo.txt"), wave_full)

        # 단면: 좁은 흡수선 몇 개(미분 구조가 있어야 shift가 결정된다)
        sig = np.zeros(npx)
        for c, a in ((150, 1.0), (260, 0.7), (380, 0.9)):
            sig += a * np.exp(-0.5 * ((np.arange(npx) - c) / 6.0) ** 2)
        np.savetxt(os.path.join(cal, "Ref_G1.dat"), np.column_stack((wave_full, sig * 1e-19)))

        px_start = 100
        wave = wave_full[px_start:]
        a_true = 2.5e-7 * sig[px_start:] / sig.max()
        a_true = a_true + 1e-8 * (np.linspace(-1, 1, len(wave)) ** 2)   # 완만한 배경
        alpha_fp = os.path.join(root, "demo_alpha_trace.dat")
        with open(alpha_fp, "w", encoding="utf-8") as fh:
            fh.write("# wavelength_nm:\t" + "\t".join("%.5f" % w for w in wave) + "\n")
            fh.write("row_idx\tT_C\tP_mbar\t"
                     + "\t".join("px%d" % (px_start + i) for i in range(len(wave))) + "\n")
            fh.write("7\t24.5\t1008.0\t" + "\t".join("%.6e" % v for v in a_true) + "\n")

        cfg = {
            "wl_path": os.path.join(cal, "Calib_demo.txt"), "data_label": "demo",
            "refs": [{"name": "G1", "path": os.path.join(cal, "Ref_G1.dat"), "mult": 0}],
            "ref_props": {"G1": {"sh_mode": "Center", "sh_val": "0, 2",
                                 "sq_mode": "Fix", "sq_val": "1.0",
                                 "t_ref": 25.0, "t_coeff": 0.0, "active_bands_nm": ""}},
            "f_min": str(px_start + 20), "f_max": str(px_start + len(wave) - 20),
            "fit_start_nm": None, "fit_end_nm": None, "fit_unit": "px",
            "poly_deg": 3, "step_limit": 0.5, "allow_negative_gas": True, "gas_temp": 0,
        }
        calib = {"wavecal": "Calib_demo.txt"}
        meta = RM.build_meta(cfg, channel=1, qc={"enabled": False}, calibration=calib,
                             data_days=["2026-09-14"])
        fit_fp = os.path.join(root, "demo_fit.dat")
        open(fit_fp, "w").close()
        RM.write_meta(fit_fp, meta)

        g = resolve_calibration_dir.__globals__
        orig_wv, orig_ref = g["WV_CAL_DIR"], g["REFERENCE_DIR"]
        g["WV_CAL_DIR"] = g["REFERENCE_DIR"] = cal
        try:
            r = refit_row(fit_fp, alpha_fp, 7)
            assert r["ok"], r.get("reason")
            # 합성 알파는 모델 그 자체 + 배경이므로 잔차가 신호보다 훨씬 작아야 한다.
            ratio = np.max(np.abs(r["residual"])) / np.max(np.abs(r["alpha"]))
            assert ratio < 0.05, ratio
            got = r["conc"]["G1"]

            # 재현 검증: 같은 값이면 통과, 틀어지면 거부
            ok2 = refit_row(fit_fp, alpha_fp, 7, saved_conc={"G1": got})
            assert ok2["ok"], ok2.get("reason")
            bad = refit_row(fit_fp, alpha_fp, 7, saved_conc={"G1": got * 1.5})
            assert not bad["ok"] and "재현 실패" in bad["reason"], bad

            # 없는 행
            assert not refit_row(fit_fp, alpha_fp, 999)["ok"]

            # legacy meta는 차단
            lm = dict(meta)
            lm["provenance"] = dict(lm["provenance"], meta_source="legacy-header")
            lm["runid"] = "L" + (lm["runid"] or "x")[1:]
            RM.write_meta(fit_fp, lm)
            leg = refit_row(fit_fp, alpha_fp, 7)
            assert not leg["ok"] and "legacy" in leg["reason"], leg

            # meta 없음
            os.remove(RM.meta_path_for(fit_fp))
            assert not refit_row(fit_fp, alpha_fp, 7)["ok"]

            # 같은 basename이 두 폴더에 있으면 알파 축으로 갈라낸다
            RM.write_meta(fit_fp, meta)
            other = os.path.join(root, "other")
            os.makedirs(other)
            shutil.copy(os.path.join(cal, "Ref_G1.dat"), other)
            np.savetxt(os.path.join(other, "Calib_demo.txt"), wave_full + 7.0)  # 다른 채널
            g["WV_CAL_DIR"] = g["REFERENCE_DIR"] = root
            d, why = resolve_calibration_dir(meta, wave, px_start)
            assert d == cal, (d, why)
            assert refit_row(fit_fp, alpha_fp, 7)["ok"]
        finally:
            g["WV_CAL_DIR"], g["REFERENCE_DIR"] = orig_wv, orig_ref
        print("refit self-check OK: conc=%.4g ppb, rms=%.3g" % (got, r["rms"]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    _demo()
