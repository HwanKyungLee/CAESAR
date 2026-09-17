"""tools/za_gas_sigma.py 자체검증 — 순수 함수의 계약.

여기 걸린 것들은 전부 **실제로 틀렸다가 고친 자리**다:

  1. 스케일을 '평균의 비'로 잡았더니 파일마다 값이 튀고 부호까지 뒤집혔다. 원인은
     alpha = s*q + c 의 c(Rayleigh 차)가 q 와 무관한 **덧셈** 항이라는 것. 기울기
     회귀로 바꿔야 c 가 절편으로 빠진다. -> test_offset_does_not_bias_slope
  2. 설정을 손으로 짐작했더니 창·차수가 어긋나 NO2 가 생산 대비 49배, CHOCHO
     5300배 틀렸다. fitset 이 단일 출처여야 하고, 없는 채널이면 기본값을 지어내지
     말고 죽어야 한다. -> test_missing_channel_raises
  3. 생산 대조를 전체 기간 중앙값으로 했다가 "재현 실패"로 오판했다. 같은 파일·같은
     행 번호로 짝지어야 한다. -> test_production_rows_are_keyed_by_row_index

sigma 값 자체는 안 건다 — 실측 데이터가 있어야 나오는 값이고, 값을 테스트에 박으면
캠페인이 바뀔 때 의미 없이 깨진다.
"""
import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.za_gas_sigma import load_fitset, matched_bins, fit_scale, load_production


def _tmp(name, text):
    p = os.path.join(tempfile.mkdtemp(), name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def test_fitset_is_the_single_source():
    p = _tmp("fs.json", json.dumps({"channels": {"2": {
        "data_label": "PNs", "fit_start_nm": 444.1, "fit_end_nm": 470.6, "poly_deg": 3}}}))
    cfg = load_fitset(p, 2)
    assert cfg["fit_start_nm"] == 444.1 and cfg["poly_deg"] == 3
    assert load_fitset(p, "2")["data_label"] == "PNs"      # int/str 둘 다


def test_missing_channel_raises():
    """없는 채널에 기본값을 지어내면 조용히 틀린 창으로 핏한다 — 죽는 게 맞다."""
    p = _tmp("fs.json", json.dumps({"channels": {"2": {"poly_deg": 3}}}))
    try:
        load_fitset(p, 9)
    except KeyError:
        return
    raise AssertionError("없는 채널인데 예외가 안 났다")


def test_fit_scale_recovers_a_known_slope():
    rng = np.random.default_rng(0)
    npx, nb = 40, 200
    s_true = np.linspace(1e-6, 2e-6, npx)
    Q = rng.normal(0.0, 1e-2, (nb, npx))
    Y = Q * s_true
    got = fit_scale([(Q, Y)])
    assert np.allclose(got, s_true, rtol=1e-6), np.max(np.abs(got / s_true - 1))


def test_offset_does_not_bias_slope():
    """Rayleigh 차(덧셈 항)가 기울기에 새면 안 된다 — 이게 원래 버그였다."""
    rng = np.random.default_rng(1)
    npx, nb = 30, 300
    s_true = np.full(npx, 1.5e-6)
    Q = rng.normal(0.0, 1e-2, (nb, npx))
    c = np.linspace(-5e-8, 5e-8, npx)          # q 와 무관한 파장별 상수
    got = fit_scale([(Q, Q * s_true + c)])
    assert np.allclose(got, s_true, rtol=1e-6), np.max(np.abs(got / s_true - 1))


def test_pooling_blocks_beats_one_block():
    """블록 하나는 q 분산이 작아 기울기가 흔들린다 — 모으면 좋아져야 한다."""
    rng = np.random.default_rng(2)
    npx, s_true = 20, np.full(20, 1e-6)
    blocks = []
    for _ in range(12):
        Q = rng.normal(0.0, 2e-3, (25, npx))
        blocks.append((Q, Q * s_true + rng.normal(0.0, 2e-9, (25, npx))))
    one = float(np.max(np.abs(fit_scale(blocks[:1]) / s_true - 1)))
    pooled = float(np.max(np.abs(fit_scale(blocks) / s_true - 1)))
    assert pooled < one, (pooled, one)


def test_matched_bins_pairs_the_right_raw_rows():
    """알파 한 행 = raw 의 한 60초 빈. 빈 경계를 틀리면 스케일이 통째로 어긋난다."""
    nb = 10                                   # matched_bins 는 8빈 미만이면 None
    ri = np.arange(nb) * 3
    A = np.array([[float(k), float(k)] for k in range(nb)])
    amb_idx = list(range(nb * 3))
    q = np.array([[float(i), float(i)] for i in range(nb * 3)])
    Q, Y = matched_bins(A, ri, q, amb_idx)
    assert Q.shape == (nb, 2) and Y.shape == (nb, 2)
    # 빈 k = raw 행 3k..3k+2 의 평균 = 3k+1
    assert np.allclose(Q[:, 0], np.arange(nb) * 3 + 1), Q[:, 0]


def test_matched_bins_returns_none_when_too_few():
    ri = np.array([0, 3])
    A = np.array([[1.0], [2.0]])
    assert matched_bins(A, ri, np.array([[0.0], [1.0], [2.0], [3.0]]), [0, 1, 2, 3]) is None


def test_production_rows_are_keyed_by_row_index():
    """생산 File 열이 `<trace>.dat [0000]` 이라 스캔별로 정확히 짝지어진다."""
    txt = ("# header\n"
           "File\tNO2\n"
           "a_PNs_alpha_trace.dat [0000]\t1.5\n"
           "a_PNs_alpha_trace.dat [0002]\t2.5\n"
           "b_PNs_alpha_trace.dat [0000]\t9.9\n")
    rows = load_production(_tmp("r.dat", txt), "a_PNs")
    assert sorted(rows) == [0, 2], sorted(rows)
    assert rows[2]["NO2"] == "2.5"
    assert load_production(_tmp("r.dat", txt), "zzz") == {}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("  OK  " + name)
    print("za_gas_sigma helpers: all passed")
