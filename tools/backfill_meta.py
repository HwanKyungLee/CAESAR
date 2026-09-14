"""레거시 결과 `.dat` → 옆에 `.meta.json` 생성 (비파괴, 추가만).

기존 결과를 버릴 수도 없고 이름을 바꿀 필요도 없다. 핏 파라미터는 이미 `.dat` 상단
`#` 헤더에 **텍스트로** 있으므로, 그걸 파싱해 기계가 읽는 사이드카로 옮긴다.

원칙 (`tools/migrate_fitting_daily.py`의 비파괴 관례를 따름)
------------------------------------------------------------
* `.dat`의 **내용·이름·위치·mtime을 건드리지 않는다.** `.meta.json`만 늘어난다.
* 기본은 dry-run(계획만 출력). 실제 쓰기는 `--apply`.
* `_autosave` · `_archive` · `_derived` 폴더는 건드리지 않는다.
* 이미 `.meta.json`이 있으면 건너뛴다(`--force`로 덮어쓰기).

헤더가 담지 못하는 것 (→ `null`, `provenance.meta_source = "legacy-header"`)
---------------------------------------------------------------------------
wavecal · R · ILS FWHM · I0 · dark/offset 파일명 · 종별 단면 파일·mult ·
종별 shift/squeeze 정책 · t_ref · dσ/dT · active bands · QC의 rms_max/snr_floor ·
settling. 헤더의 `Reference Constraints`는 **첫 가스의 해석된 값 하나**뿐이라 특정
종에 귀속시키지 않고 `legacy_source`에 원문 그대로 보관한다.

그래서 legacy runid는 `L…`, 정상(live) runid는 `r…`로 접두사가 갈린다 — 구멍 뚫린
해시가 완전한 해시와 섞여 "같은 설정"으로 오판되면 안 된다.

사용:
  python tools/backfill_meta.py "C:/Doasis_Work/Output/fitting"           # 계획만
  python tools/backfill_meta.py "C:/Doasis_Work/Output/fitting" --apply   # 실제 생성
"""
from __future__ import annotations

import argparse
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import run_meta
from core.result_io import read_result

SKIP_DIRS = {"_autosave", "_archive", "_derived", "__pycache__"}


# ── 헤더 한 줄에서 값 뽑기 ────────────────────────────────────────────────────
def _find(comments, pattern, group=1, cast=None):
    """헤더 주석들에서 첫 매치의 그룹을 반환. 없으면 None(= 헤더에 없던 항목)."""
    rx = re.compile(pattern, re.IGNORECASE)
    for c in comments:
        m = rx.search(c)
        if m:
            raw = m.group(group)
            if cast is None:
                return raw
            try:
                return cast(raw)
            except (TypeError, ValueError):
                return None
    return None


def _onoff(comments, pattern):
    """'…: ON/OFF' 형태 → bool. 줄 자체가 없으면 None(모름 != False)."""
    v = _find(comments, pattern + r"\s*:\s*(ON|OFF|YES|NO)")
    return None if v is None else v.upper() in ("ON", "YES")


def parse_header(comments) -> dict:
    """`.dat` `#` 헤더 → {cfg, qc, calibration, legacy, created, commit, channel}.

    헤더 포맷은 시간에 따라 늘어났다(구파일엔 없는 줄이 있다) → 전부 optional.
    """
    _range = r"Fit Range:\s*Pixel\s*(\d+)\s*-\s*(\d+)"
    _nm = r"Fit Range:.*\(\s*([\d.]+)\s*-\s*([\d.]+)\s*nm\s*\)"

    cfg = {
        "f_min": _find(comments, _range, cast=int),
        "f_max": _find(comments, _range, group=2, cast=int),
        "fit_start_nm": _find(comments, _nm, cast=float),
        "fit_end_nm": _find(comments, _nm, group=2, cast=float),
        # 헤더의 nm은 px에서 변환해 찍은 표시값이라 px와 항상 일치한다(FitSet json의
        # 스테일 nm 필드 문제(§13-A)와는 다름). 어느 단위로 설정했는지는 헤더에
        # 안 남으므로 정본인 px로 기록한다.
        "fit_unit": "px",
        "poly_deg": _find(comments, r"Polynomial Degree:\s*(\d+)", cast=int),
        "step_limit": _find(comments, r"Step Limit:\s*([\d.]+)", cast=float),
        "allow_negative_gas": _onoff(comments, r"Allow Negative Gas[^:]*"),
        "gas_temp": _find(comments, r"gas_temp\s*=\s*([-\d.]+)", cast=float),
        "data_label": _find(comments, r"Channel\s+\d+\s*\(([^)]*)\)"),
        "refs": [],          # 종 이름은 호출부가 컬럼에서 채운다
        "ref_props": {},     # 종별 정책은 헤더에 없다 — 비운다
    }

    qc_line = _find(comments, r"Auto QC:\s*(.+)$") or ""
    qc = {
        "enabled": None if not qc_line else not qc_line.strip().upper().startswith("OFF"),
        "auto_k": _find(comments, r"Auto QC:.*K\s*=\s*([\d.]+)", cast=float),
        "rms_max": None,        # 헤더에 없음
        "snr_floor": None,      # 헤더에 없음
        "settling": None,       # 헤더에 없음
        "settling_n": None,
        "ok_rms_pct": _find(comments, r"OK RMS Threshold:\s*([\d.]+)", cast=float),
        "tikhonov": _find(comments, r"Tikhonov Lambda:\s*([\d.eE+-]+)", cast=float),
        "robust": _onoff(comments, r"Robust Fitting[^:]*"),
        "kalman_q": _find(comments, r"Kalman Filter:\s*Q\s*=\s*([\d.eE+-]+)", cast=float),
        "kalman_r": _find(comments, r"Kalman Filter:.*\bR\s*=\s*([\d.eE+-]+)", cast=float),
    }

    calibration = {
        "wavecal": None, "ils_fwhm_nm": None, "ils_fwhm_px": None,   # 헤더에 없음
        "i0": None, "r": None, "d_cm": None,                          # 헤더에 없음
        "dark": _onoff(comments, r"Dark Current Subtraction"),
        "dark_scale": _find(comments, r"Dark Current Subtraction:.*scale\s*=\s*([\d.]+)", cast=float),
        "offset": _onoff(comments, r"Detector Offset Subtraction"),
        "offset_scale": _find(comments, r"Detector Offset Subtraction:.*scale\s*=\s*([\d.]+)", cast=float),
        "stray_light": _find(comments, r"Stray Light Correction:.*epsilon\s*=\s*([\d.]+)", cast=float),
        "temporal_i0": _onoff(comments, r"Temporal I0 Interpolation"),
        "rl_factor": _find(comments, r"Purge Gas RL Factor:\s*([\d.]+)", cast=float),
    }

    legacy = {
        # 첫 가스의 '해석된' Sh/Sq 하나뿐 — 종에 귀속시키면 거짓이 된다.
        "reference_constraints": _find(comments, r"Reference Constraints:\s*(.+)$"),
        "measurement_flags": _find(comments, r"Measurement Flags:\s*(.+)$"),
        "data_period": _find(comments, r"Data Period:\s*(.+)$"),
        "header_refs": _find(comments, r"refs\s*=\s*([A-Za-z0-9_,]+)"),
    }
    return {
        "cfg": cfg, "qc": qc, "calibration": calibration, "legacy": legacy,
        "created": _find(comments, r"Generated:\s*(.+)$"),
        "commit": _find(comments, r"Code Version:\s*(\S+)"),
        "channel": _find(comments, r"Channel\s+(\d+)\s*\(", cast=int),
    }


def species_from_columns(colhdr: str) -> list:
    """컬럼명에서 종 목록. 'X'와 'X_Error'가 둘 다 있으면 X는 종이다.

    기체명을 코드에 박지 않는다(레포 공통 원칙) — 컬럼 구조만 본다.
    """
    cols = [c.strip() for c in colhdr.split("\t")]
    have = set(cols)
    return [c for c in cols if not c.endswith("_Error") and f"{c}_Error" in have]


def channel_from_rows(colhdr: str, rows):
    """데이터의 Channel 열 첫 값. 채널 헤더 줄이 없는 단일채널 파일용."""
    cols = [c.strip() for c in colhdr.split("\t")]
    if "Channel" not in cols or not rows:
        return None
    i = cols.index("Channel")
    try:
        return int(float(rows[0][1].split("\t")[i]))
    except (IndexError, ValueError):
        return None


def build_for_file(fp: str) -> dict:
    """`.dat` 하나 → meta dict. 읽기만 한다."""
    comments, colhdr, rows = read_result(fp)
    p = parse_header(comments)
    cfg = p["cfg"]

    names = species_from_columns(colhdr)
    if not names and p["legacy"]["header_refs"]:
        names = [n for n in p["legacy"]["header_refs"].split(",") if n]
    # 이름만 안다 — 단면 파일·mult·정책은 헤더에 없으므로 null로 남는다.
    cfg["refs"] = [{"name": n, "path": None, "mult": None} for n in names]

    days = sorted({t.strftime("%Y-%m-%d") for t, _ in rows})
    meta = run_meta.build_meta(
        cfg,
        channel=(p["channel"] if p["channel"] is not None
                 else channel_from_rows(colhdr, rows)),
        qc=p["qc"], calibration=p["calibration"],
        data_days=days, rows={"total": len(rows)},
        code_version=p["commit"],
        meta_source="legacy-header",
    )
    meta["created"] = _iso(p["created"]) or meta["created"]
    meta["legacy_source"] = {"file": os.path.basename(fp), **p["legacy"]}
    return meta


def _iso(text):
    """헤더의 'Generated: 2026-09-04 23:14:07' → ISO. 소비자(B3 버전목록)가 저장시각으로
    정렬하려면 live meta와 같은 형식이어야 한다. 못 읽으면 원문 그대로 둔다."""
    if not text:
        return None
    try:
        from datetime import datetime
        return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S").isoformat(timespec="seconds")
    except ValueError:
        return text.strip()


def iter_results(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.lower().endswith((".dat", ".csv")):
                yield os.path.join(dirpath, fn)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="레거시 결과 .dat 옆에 .meta.json 생성 (비파괴, 추가만)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="결과 폴더(재귀 탐색)")
    ap.add_argument("--apply", action="store_true",
                    help="실제로 .meta.json을 쓴다 (기본: dry-run)")
    ap.add_argument("--force", action="store_true", help="이미 있는 .meta.json도 덮어쓴다")
    ap.add_argument("--quiet", action="store_true", help="파일별 줄 출력 생략")
    a = ap.parse_args(argv)

    if not os.path.isdir(a.root):
        print(f"not a directory: {a.root}")
        return 2

    n_new = n_skip = n_fail = 0
    for fp in iter_results(a.root):
        mp = run_meta.meta_path_for(fp)
        if os.path.exists(mp) and not a.force:
            n_skip += 1
            continue
        try:
            meta = build_for_file(fp)
        except Exception as e:                      # noqa: BLE001 — 못 읽는 파일은 건너뛴다
            n_fail += 1
            if not a.quiet:
                print(f"  SKIP  {os.path.relpath(fp, a.root)}  ({e})")
            continue
        n_new += 1
        if not a.quiet:
            print(f"  {'WRITE' if a.apply else 'PLAN '} {os.path.relpath(mp, a.root)}  "
                  f"runid={meta['runid']} ch={meta['channel']} "
                  f"days={len(meta['data_days'])} rows={meta['rows']['total']} "
                  f"species={[s['name'] for s in meta['species']]}")
        if a.apply:
            run_meta.write_meta(fp, meta)

    verb = "written" if a.apply else "planned"
    print(f"\n{n_new} {verb} - {n_skip} already had meta - {n_fail} unreadable")
    if not a.apply and n_new:
        print("dry-run - 실제로 만들려면 --apply")
    return 0


_DEMO_DAT = """# Channel 1 (PNs) settings: px774-1550_Poly4_Sh[-1,1]_gT25  gas_temp=25C  refs=NO2,CHOCHO,H2O
# ==========================================================
# Augur Analysis Report
# Generated: 2026-09-04 23:14:07
# Code Version: g11d42ca
# Data Period: 2026-09-04 00:00 ~ 2026-09-05 02:00
# Fit Range: Pixel 774-1550 (438.4-475.8nm)
# Polynomial Degree: 4
# Tikhonov Lambda: 0
# Robust Fitting (IRLS): OFF
# Allow Negative Gas (Neg): ON
# Auto QC: ON  (auto threshold K=8-MAD)
# Step Limit: 0.5 px
# OK RMS Threshold: 10.0%  (fit accepted when RMS/signal < threshold)
# Kalman Filter: Q=0.0005, R=0.050  (concentration columns = raw fit)
# Dark Current Subtraction: NO  (scale=1.0000)
# Detector Offset Subtraction: YES  (scale=0.9500)
# Stray Light Correction: OFF  (epsilon=0.0000)
# Temporal I0 Interpolation: ON
# Purge Gas RL Factor: 0.9330  (1.0 = no correction)
# Measurement Flags: Ambient=1, ZA=500, He=510
# Reference Constraints: Sh[-1,1], Sq[None]
# ==========================================================
File\tTime\tChannel\tRMS\tStatus\tNO2\tNO2_Error\tCHOCHO\tCHOCHO_Error
f1\t2026-09-04 10:00:00\t1\t0.001\tOK\t3.5\t0.06\t0.09\t0.02
f2\t2026-09-05 01:00:00\t1\t0.009\tUnstable\t-1.2\t0.90\t0.05\t0.03
"""

# 헤더 줄이 거의 없는 구파일 — 파서가 죽지 않고 모르는 건 None으로 남겨야 한다.
_DEMO_SPARSE = """# Augur Analysis Report
# Fit Range: Pixel 100-200 (430.0-440.0nm)
File\tTime\tNO2\tNO2_Error
f1\t2026-01-02 00:00:00\t1.0\t0.1
"""


def _demo():
    """자기검증: 헤더 파싱 정확도 + `.dat` 불변 + 모르는 값은 None."""
    import tempfile
    root = tempfile.mkdtemp()
    day = os.path.join(root, "260904", "neg_o", "QCoff")
    os.makedirs(day)
    dat = os.path.join(day, "260904_PNs.dat")
    with open(dat, "w", encoding="utf-8") as fh:
        fh.write(_DEMO_DAT)
    before = (os.path.getsize(dat), os.path.getmtime(dat), open(dat, encoding="utf-8").read())

    m = build_for_file(dat)
    assert m["window"]["px"] == [774, 1550] and m["window"]["unit"] == "px", m["window"]
    assert m["window"]["nm"] == [438.4, 475.8]
    assert m["poly_deg"] == 4 and m["step_limit"] == 0.5 and m["allow_neg"] is True
    assert m["channel"] == 1 and m["label"] == "PNs" and m["gas_temp"] == 25
    assert [s["name"] for s in m["species"]] == ["NO2", "CHOCHO"], m["species"]
    assert m["qc"]["enabled"] is True and m["qc"]["auto_k"] == 8.0
    assert m["qc"]["robust"] is False and m["qc"]["kalman_r"] == 0.05
    assert m["calibration"]["offset_scale"] == 0.95 and m["calibration"]["dark"] is False
    assert m["calibration"]["temporal_i0"] is True and m["calibration"]["rl_factor"] == 0.933
    assert m["data_days"] == ["2026-09-04", "2026-09-05"] and m["rows"]["total"] == 2
    assert m["created"] == "2026-09-04T23:14:07", m["created"]
    assert m["provenance"]["commit"] == "g11d42ca"

    # 모르는 것은 반드시 None — ""나 0으로 채우면 소비자가 거짓을 읽는다
    assert m["provenance"]["meta_source"] == "legacy-header"
    assert m["runid"].startswith("L"), m["runid"]      # live 'r…'과 절대 안 섞임
    assert m["calibration"]["wavecal"] is None and m["calibration"]["r"] is None
    assert m["qc"]["rms_max"] is None and m["qc"]["settling"] is None
    for s in m["species"]:
        assert s["xs"] is None and s["mult"] is None and s["sh_mode"] is None, s

    # 원본 `.dat`은 한 바이트도 안 바뀐다
    run_meta.write_meta(dat, m)
    after = (os.path.getsize(dat), os.path.getmtime(dat), open(dat, encoding="utf-8").read())
    assert before == after, "backfill must not touch the .dat"
    assert run_meta.read_meta(dat)["runid"] == m["runid"]

    # dry-run은 아무것도 안 쓴다
    sparse_dir = os.path.join(root, "260101", "neg_x", "QCoff")
    os.makedirs(sparse_dir)
    sparse = os.path.join(sparse_dir, "260101_old.dat")
    with open(sparse, "w", encoding="utf-8") as fh:
        fh.write(_DEMO_SPARSE)
    main([root, "--quiet"])
    assert not os.path.exists(run_meta.meta_path_for(sparse)), "dry-run wrote a file"

    # 헤더가 빈약해도 죽지 않고, 없는 건 None
    s = build_for_file(sparse)
    assert s["poly_deg"] is None and s["allow_neg"] is False and s["qc"]["enabled"] is None
    assert s["window"]["px"] == [100, 200] and [x["name"] for x in s["species"]] == ["NO2"]

    # 건너뛰기(이미 meta 있음) — 재실행이 멱등
    main([root, "--apply", "--quiet"])
    n_meta = sum(1 for _, _, fs in os.walk(root) for f in fs if f.endswith(".meta.json"))
    assert n_meta == 2, n_meta
    print("backfill_meta self-check OK:", m["runid"], s["runid"])


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _demo()
    else:
        raise SystemExit(main())
