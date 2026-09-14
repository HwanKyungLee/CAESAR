"""A3 산출물 배치 회귀 검사 — 경로 규칙 + 읽기 하위호환.

이 검사가 지키는 계약 둘:
  1. 새 저장 경로/파일명이 `output/{campaign}/{YYYY-MM-DD}/{kind}/{날짜}_{CH}_{label}_{runid}`
     이고 이름에 특수문자가 없다.
  2. **읽기는 세 구조를 전부 인식한다** — A3 신규 · 구(핏config 폴더) · 레거시(flat).
     기존 파일을 하나도 안 옮기는 게 A3의 전제라, 여기가 깨지면 옛 결과가 안 보인다.

    python tools/test_result_layout.py
"""
from __future__ import annotations

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import run_meta
from core.paths import (DEFAULT_CAMPAIGN, campaign_dir, day_dir, iso_day,
                        out_name, out_path, safe_token, short_day)

_HDR = "# Augur Analysis Report\n# Fit Range: Pixel 774-1550 (438.4-475.8nm)\n"
_BODY = "File\tTime\tChannel\tNO2\tNO2_Error\nf\t2026-09-04 10:00:00\t1\t3.5\t0.06\n"


def _dat(path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_HDR + _BODY)
    return path


def test_path_rules():
    assert safe_token("ch1_429.5~461.9") == "ch1_429_5_461_9"
    assert safe_token("", "default") == DEFAULT_CAMPAIGN
    assert safe_token("  yeosu 2026 ") == "yeosu_2026"
    assert iso_day("260904") == "2026-09-04" and iso_day("2026-09-04") == "2026-09-04"
    assert short_day("2026-09-04") == "260904" and short_day("260904") == "260904"

    name = out_name("260904", 1, "PNs", "r3f8a1")
    assert name == "260904_CH1_PNs_r3f8a1.dat", name
    # 옛 태그의 금지문자가 이름에 절대 안 들어간다(셸 글롭·엑셀 참조 보호)
    assert not set(out_name("260904", 2, "ANs~[hot]", "r0507f")) & set("[]~ °*?\"<>|")

    p = out_path("/out", "yeosu 2026", "260904", channel=1, label="PNs", runid="r3f8a1")
    assert p.replace("\\", "/").endswith("/out/yeosu_2026/2026-09-04/fitting/"
                                         "260904_CH1_PNs_r3f8a1.dat"), p
    assert day_dir("/out", None, "260904", "alpha").replace("\\", "/") \
        .endswith("/out/default/2026-09-04/alpha")
    assert campaign_dir("/out", "yeosu_2026").replace("\\", "/").endswith("/out/yeosu_2026")


def test_bucket_labels():
    """neg/QC 어휘의 단일 출처. 폴더가 아니라 라벨이 됐지만 값은 그대로여야 한다."""
    base = {"allow_neg": True, "qc": {"enabled": True, "auto_k": 8.0}}
    assert run_meta.bucket_labels(base) == ("neg_o", "QCk8")
    assert run_meta.bucket_labels({**base, "allow_neg": False}) == ("neg_x", "QCk8")
    assert run_meta.bucket_labels({**base, "qc": {"enabled": False}})[1] == "QCoff"
    assert run_meta.bucket_labels({**base, "qc": {"enabled": True}})[1] == "QCmanual"


def test_reader_accepts_all_three_layouts():
    from gui.dlg_date_load import scan_daily_tree      # PyQt import — 이 테스트에서만

    base = tempfile.mkdtemp()
    _dat(os.path.join(base, "260904", "neg_o", "QCoff", "260904_cold.dat"))          # 레거시
    _dat(os.path.join(base, "ch1_429.5~461.9", "260904", "neg_x", "QCk6",
                      "260904_PNs.dat"))                                             # 구
    a3 = _dat(os.path.join(base, "yeosu_2026", "2026-09-04", "fitting",
                           "260904_CH1_PNs_r3f8a1.dat"))                             # A3
    cfg = {"data_label": "PNs", "f_min": "774", "f_max": "1550", "poly_deg": 4,
           "allow_negative_gas": True,
           "refs": [{"name": "NO2", "path": "NO2.dat", "mult": 0}], "ref_props": {}}
    run_meta.write_meta(a3, run_meta.build_meta(
        cfg, channel=1, qc={"enabled": True, "auto_k": 8.0}, calibration={},
        data_days=["2026-09-04"]))
    # meta 없는 A3 파일(사이드카 실패)도 스캔이 죽지 않아야 한다
    _dat(os.path.join(base, "yeosu_2026", "2026-09-05", "fitting",
                      "260905_CH1_PNs_r3f8a1.dat"))
    _dat(os.path.join(base, "_archive", "260904", "neg_o", "QCoff", "old.dat"))

    tree = scan_daily_tree(base)
    assert ("", "cold", "neg_o", "QCoff") in tree, "legacy flat tree lost"
    assert ("ch1_429.5~461.9", "PNs", "neg_x", "QCk6") in tree, "old cfg tree lost"
    assert ("yeosu_2026", "CH1_PNs_r3f8a1", "neg_o", "QCk8") in tree, "A3 layout not read"
    assert ("yeosu_2026", "CH1_PNs_r3f8a1", "neg_?", "QC?") in tree, "meta-less A3 file lost"
    assert not any(k[0].startswith("_") for k in tree), "_archive must be skipped"


def test_version_list_contract():
    """B3 버전 목록이 기대는 두 계약.

    1. `load_fit_table`이 'rms' 키를 준다 — 이름이 바뀌면 RMS 칸이 조용히 빈칸이 된다.
    2. `find_versions` + `diff_meta` + `summarize_diff`가 실제 파일 위에서 이어진다.
    """
    import numpy as np
    from gui.result_viewer_io import load_fit_table
    from core.run_meta import diff_meta, find_versions, summarize_diff

    base = tempfile.mkdtemp()
    day = os.path.join(base, "yeosu_2026", "2026-09-04", "fitting")
    os.makedirs(day)
    cfg = {"data_label": "PNs", "f_min": "774", "f_max": "1550", "fit_unit": "px",
           "allow_negative_gas": True,
           "refs": [{"name": "NO2", "path": "NO2.dat", "mult": 0}],
           "ref_props": {"NO2": {"sh_mode": "Center", "sh_val": "-0.2, 1.9"}}}

    written = []
    for poly in (3, 4):
        c = dict(cfg, poly_deg=poly)
        m = run_meta.build_meta(c, channel=1, qc={"enabled": False}, calibration={},
                                data_days=["2026-09-04"])
        fp = os.path.join(day, f"260904_CH1_PNs_{m['runid']}.dat")
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write(_HDR + "File\tTime\tChannel\tRMS\tStatus\tNO2\tNO2_Error\n"
                     "f1\t2026-09-04 10:00:00\t1\t0.0012\tOK\t3.5\t0.06\n"
                     "f2\t2026-09-04 10:01:00\t1\t0.0018\tOK\t3.6\t0.06\n")
        run_meta.write_meta(fp, m)
        written.append(fp)

    t = load_fit_table(written[0])
    assert "rms" in t, sorted(t)                    # 계약 1
    rms = np.asarray(t["rms"], dtype=float)
    assert float(np.median(rms[np.isfinite(rms)])) == 0.0015

    vs = find_versions(written[0])                  # 계약 2
    assert len(vs) == 2, [v["meta"]["runid"] for v in vs]
    assert all(os.path.exists(v["path"]) for v in vs), [v["path"] for v in vs]
    d = diff_meta(vs[0]["meta"], vs[1]["meta"])
    assert [k for k, _o, _n in d] == ["poly_deg"], d
    assert summarize_diff(d) == "poly_deg 3→4", summarize_diff(d)


def main() -> int:
    for fn in (test_path_rules, test_bucket_labels,
               test_reader_accepts_all_three_layouts,
               test_version_list_contract):
        fn()
        print(f"  PASS  {fn.__name__}")
    print("A3 layout self-check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
