"""핫 5/29 UTC-toggle 시계보정 + 시각축 단조성 가드 자체검증.

두 가지를 건다:
  1) `DataIO.clock_epoch_offset_sec` — 어느 파일에 −9h 가 붙고 어디엔 안 붙나.
     핫/콜드는 **경로가 아니라 데이터 열수**(6181/6179)로 갈리므로 그것도 검증.
  2) `resolve_time_axis` — 시각이 역행/중복이면 인덱스축으로 폴백하고 사유를 알린다.
     이게 없으면 5/29 경계 하나 때문에 캠페인 전체 런이 죽는다(실측: 484만 스캔).

raw 데이터가 없어도 돌도록 열수는 가짜 행으로 흉내낸다. E: 가 붙어 있으면
실제 경계 파일(2026-05-29-010/011)로 보정 후 전진하는지까지 확인한다.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data_io import DataIO
from core.step_guard import resolve_time_axis

HOT = [[0] * DataIO.HOT_NCOLS]          # 핫 데이터행 폭
COLD = [[0] * 6179]                     # 콜드 데이터행 폭
SHORT = [[0] * 6174]                    # 콜드 HK 결손 구간(6/11~6/15)
SHIFT = DataIO.HOT_PRE_TOGGLE_SHIFT_SEC


def test_offset_applies_only_to_pre_toggle_hot():
    # 경계 직전 = 구컨벤션 → −9h
    assert DataIO.clock_epoch_offset_sec("2026-05-29-010.dat", rows=HOT) == SHIFT
    # 경계 파일부터 = 신컨벤션 → 무보정
    assert DataIO.clock_epoch_offset_sec("2026-05-29-011.dat", rows=HOT) == 0.0
    # 배치 첫 파일(하한 포함)
    assert DataIO.clock_epoch_offset_sec("2026-05-18-001.dat", rows=HOT) == SHIFT
    # 배치 전 · 토글 이후 날짜는 둘 다 무보정
    assert DataIO.clock_epoch_offset_sec("2026-05-17-001.dat", rows=HOT) == 0.0
    assert DataIO.clock_epoch_offset_sec("2026-06-01-001.dat", rows=HOT) == 0.0
    assert DataIO.clock_epoch_offset_sec("2026-07-09-014.dat", rows=HOT) == 0.0


def test_cold_is_never_shifted():
    """콜드 PC 는 이 문제가 없다 — 파일명이 같아도 열수로 걸러져야 한다."""
    for stem in ("2026-05-18-001", "2026-05-29-010", "2026-05-28-009"):
        assert DataIO.clock_epoch_offset_sec(stem + ".dat", rows=COLD) == 0.0
        assert DataIO.clock_epoch_offset_sec(stem + ".dat", rows=SHORT) == 0.0


def test_full_path_and_extension_do_not_matter():
    p = r"E:\Yeosu_2026\CAESAR_Hot\2026-05\2026-05-20-007.dat"
    assert DataIO.clock_epoch_offset_sec(p, rows=HOT) == SHIFT
    assert DataIO.clock_epoch_offset_sec("garbage.dat", rows=HOT) == 0.0


def test_time_axis_rejects_backwards_and_duplicates():
    idx = np.arange(5, dtype=float)
    # 정상: 시각축을 쓴다
    x, ok = resolve_time_axis(idx, [10.0, 11.0, 12.0, 13.0, 14.0])
    assert ok and x[0] == 10.0
    # 역행(5/29 경계 모양): 폴백 + 사유 보고
    msgs = []
    x, ok = resolve_time_axis(idx, [10.0, 11.0, 2.0, 3.0, 4.0], warn=msgs.append)
    assert not ok and np.array_equal(x, idx)
    assert msgs and "역행" in msgs[0]
    # 중복(2026-05-28-009 모양): diff==0 도 strictly increasing 위반이다
    msgs = []
    x, ok = resolve_time_axis(idx, [10.0, 11.0, 11.0, 12.0, 13.0], warn=msgs.append)
    assert not ok and "중복" in msgs[0]
    # 콜백 없이도 죽지 않는다
    assert resolve_time_axis(idx, [10.0, 9.0, 8.0, 7.0, 6.0])[1] is False
    # NaN 은 종전대로 폴백
    assert resolve_time_axis(idx, [10.0, np.nan, 12.0, 13.0, 14.0])[1] is False


def test_all_time_readers_agree():
    """같은 파일·같은 행에 대해 세 함수가 **같은 시계**를 말해야 한다.

    알파 경로(`all_row_seconds`)만 보정하고 raw 직접 피팅 경로
    (`parse_row_timestamp`)를 놔두면 같은 스캔이 9시간 다른 시각을 갖는다.
    """
    f = r"E:\Yeosu_2026\CAESAR_Hot\2026-05\2026-05-20-001.dat"   # 핫 pre-toggle
    if not os.path.exists(f):
        print("  SKIP test_all_time_readers_agree (raw 없음)")
        return
    row = 1                                   # 0은 헤더행
    secs = DataIO.all_row_seconds(f)
    ts = DataIO.parse_row_timestamp(f, row_index=row)
    doy = DataIO.parse_row_doy(f, row_index=row)
    assert ts is not None and doy is not None
    from datetime import datetime
    ts_sec = (ts - datetime(ts.year, 1, 1)).total_seconds()
    assert abs(ts_sec - secs[row]) < 0.02, f"timestamp {ts_sec} != rows {secs[row]}"
    assert abs((doy - 1.0) * 86400.0 - secs[row]) < 0.02, "doy 가 다른 시계다"
    # 그리고 실제로 보정이 걸린 파일이어야 이 검사가 의미가 있다
    assert DataIO.clock_epoch_offset_sec(f) == SHIFT


def test_real_boundary_moves_forward():
    """E: 가 있으면 실제 5/29 경계가 보정 후 전진하는지 본다(없으면 SKIP)."""
    d = r"E:\Yeosu_2026\CAESAR_Hot\2026-05"
    a, b = os.path.join(d, "2026-05-29-010.dat"), os.path.join(d, "2026-05-29-011.dat")
    if not (os.path.exists(a) and os.path.exists(b)):
        print("  SKIP test_real_boundary_moves_forward (raw 없음)")
        return
    ea = np.nanmax(DataIO.all_row_seconds(a))
    sb = np.nanmin(DataIO.all_row_seconds(b))
    assert sb > ea, f"보정 후에도 역행: {ea:.2f} -> {sb:.2f}"
    gap = sb - ea
    assert 0 < gap < 3600, f"재시작 공백이 비상식적: {gap:.1f}s"
    print(f"  실측 경계 OK: gap {gap:.1f}s (재시작 공백)")


def test_header_row_width_silently_disables_the_shift():
    """★함정: 파일 **첫 줄**(LabVIEW 헤더행 6177)의 폭을 넘기면 보정이 조용히 꺼진다.

    핫 raw 는 헤더 6177 / 데이터행 6181 로 폭이 다르다(실측 2026-05-18-001 앞 6줄
    = [6177, 6181x5]). 호출부가 "첫 줄 폭"을 ncols 로 넘기면 HOT_NCOLS 와 안 맞아
    0.0 이 나오고 **틀렸다는 신호 없이** 9h 가 안 붙는다. 실제로
    `gui.worker._pass2_write_file` 이 첫 줄만 보고 있었다(2026-09-19 수정).
    """
    HEADER = [[0] * 6177]
    assert DataIO.clock_epoch_offset_sec("2026-05-20-003.dat", rows=HEADER) == 0.0
    assert DataIO.clock_epoch_offset_sec("2026-05-20-003.dat", rows=HOT) == SHIFT
    # ncols 를 직접 넘기는 경로도 같다 — 헤더 폭이면 꺼지고 데이터행 폭이면 켜진다.
    assert DataIO.clock_epoch_offset_sec("2026-05-20-003.dat", ncols=6177) == 0.0
    assert DataIO.clock_epoch_offset_sec("2026-05-20-003.dat", ncols=DataIO.HOT_NCOLS) == SHIFT



if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    print(f"\n{'OK' if not fails else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)
