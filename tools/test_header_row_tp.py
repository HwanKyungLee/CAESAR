"""헤더행(flag=0) T/P 차용 회귀 — 데이터 없이 도는 합성 검증.

왜: LabVIEW는 파일 첫 행에 flag=0 을 쓰면서 HK 28열을 전부 65535(값없음)로 남긴다.
예전엔 `load_measurement_with_hk`가 T=25.0 / P=1013.25 **상수**로 떨어졌고, 그 상수로
계산한 n_air 가 실측 대비 0.2 %(콜드) ~ 3.7 %(핫) 어긋난 채 아무 표시 없이 결과에
섞였다(핫 22파일 · 콜드 44파일). 운용자 결정(2026-09-15)에 따라 **버리지 않고 다음
실측행의 T/P를 끌어온다**.

이 테스트가 지키는 것:
  1. 헤더행의 T/P가 상수 기본값이 아니라 **다음 실측행 값**으로 온다
  2. 실측행 자신의 T/P는 아무 영향도 안 받는다
  3. flag=0 은 오직 헤더행을 뜻한다(비-Araon 1D 파일은 FLAG_AMBIENT로 온다)

`python tools/test_header_row_tp.py` 로 단독 실행 가능.
"""
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.data_io import DataIO                       # noqa: E402
from core.raw_parser import FLAG_AMBIENT, FLAG_HEADER  # noqa: E402

_NCOL_DATA = 6179          # 콜드 실측행
_HK_START = 6149
_P_COL, _T_COL = 6160, 6173        # cavity_P / cavity_T (콜드 절대열)


def _row(flag, spec_peak, p_raw=None, t_raw=None, ncol=_NCOL_DATA):
    """합성 Araon 행. p_raw/t_raw가 None이면 HK 전부 65535(= 헤더행)."""
    r = np.zeros(ncol)
    r[4] = flag
    r[2053:4101] = spec_peak                  # 슬롯B = channel 1
    if p_raw is None:
        r[_HK_START:] = 65535
    else:
        r[_HK_START:] = 65535
        r[_P_COL] = p_raw
        r[_T_COL] = t_raw
    return r


def _write(rows):
    fd, path = tempfile.mkstemp(suffix=".dat")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write("\t".join(f"{v:g}" for v in r) + "\n")
    return path


def test_header_row_borrows_next_tp():
    """헤더행 T/P == 다음 실측행 T/P (상수 25.0/1013.25가 아니다)."""
    # P_raw 1462 → ×0.6895 ≈ 1008.0 mbar,  T_raw 2916 → /100 = 29.16 °C
    path = _write([_row(FLAG_HEADER, 40000, ncol=6177),
                   _row(FLAG_AMBIENT, 40000, p_raw=1462, t_raw=2916),
                   _row(FLAG_AMBIENT, 40000, p_raw=1462, t_raw=2916)])
    try:
        _, _, f0, t0, p0 = DataIO.load_measurement_with_hk(path, 0, None, row_index=0, channel=1)
        _, _, f1, t1, p1 = DataIO.load_measurement_with_hk(path, 0, None, row_index=1, channel=1)
        assert f0 == FLAG_HEADER, f"헤더행 flag가 {f0}"
        assert (t0, p0) != (25.0, 1013.25), "T/P가 아직 상수 기본값이다 — 차용이 안 됐다"
        assert (t0, p0) == (t1, p1), f"차용값 불일치: 헤더행 {(t0, p0)} vs 실측행 {(t1, p1)}"
        assert abs(t1 - 29.16) < 0.01 and abs(p1 - 1008.0) < 1.0, f"실측행 T/P 해석이 이상: {(t1, p1)}"
    finally:
        os.unlink(path)


def test_measured_rows_untouched():
    """실측행은 차용 로직과 무관하게 자기 HK를 쓴다."""
    path = _write([_row(FLAG_HEADER, 40000, ncol=6177),
                   _row(FLAG_AMBIENT, 40000, p_raw=1462, t_raw=2916),
                   _row(FLAG_AMBIENT, 40000, p_raw=1400, t_raw=3000)])
    try:
        _, _, _, t1, p1 = DataIO.load_measurement_with_hk(path, 0, None, row_index=1, channel=1)
        _, _, _, t2, p2 = DataIO.load_measurement_with_hk(path, 0, None, row_index=2, channel=1)
        assert (t1, p1) != (t2, p2), "실측행끼리 값이 같다 — 행별 HK를 안 읽고 있다"
        assert abs(t2 - 30.0) < 0.01, f"row2 T={t2}"
    finally:
        os.unlink(path)


def test_plain_1d_file_is_ambient_not_header():
    """flag 컬럼이 없는 1D 파일은 FLAG_AMBIENT — flag=0 은 오직 헤더행을 뜻한다."""
    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for v in np.linspace(1000, 2000, 50):
            fh.write(f"{v:.3f}\n")
    try:
        _, _, flag, _, _ = DataIO.load_measurement_with_hk(path, 0, None, row_index=0)
        assert flag == FLAG_AMBIENT, f"1D 파일 flag가 {flag} (FLAG_HEADER면 헤더행과 구별 불가)"
    finally:
        os.unlink(path)


if __name__ == "__main__":
    test_header_row_borrows_next_tp()
    test_measured_rows_untouched()
    test_plain_1d_file_is_ambient_not_header()
    print("OK: header-row T/P borrowing verified")
