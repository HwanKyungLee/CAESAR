"""oculus/profile.py 단위테스트 (데이터 비의존, 합성 raw 행).

커버:
  1) 기본 폴더 프로파일 로드 + 스키마 검증
  2) 잘못된 프로파일 → ProfileError
  3) ProfileSet.route: n_columns / filename / 무매치
  4) Flags.role_of (의미 역할 매핑)
  5) 채널 slice + signal_channels (label 비의존)
  6) HK 물리값 환산 + 밴드 평가(None/warn/alarm)
  7) 포화 판정
  8) 채널 자동탐지(블록 최대값 → signal/noise)
  9) bytepack 시각 복원

사용: python oculus/test_profile.py  → 전부 PASS면 exit 0
"""
import os
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from oculus.profile import (Profile, ProfileSet, ProfileError, HKField,
                            validate_profile_dict, load_profiles)

_n_pass = 0
_n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


COLD_ID = "caesar_cold_2026yeosu"
HOT_ID = "caesar_hot_2026yeosu"


def _make_row(n_columns, fill=800):
    return [fill] * n_columns


def test_load_and_validate():
    print("[1] 기본 폴더 로드 + 스키마 검증")
    ps = ProfileSet.load_default()
    check("2개 이상 프로파일 로드", len(ps) >= 2, f"got {len(ps)}")
    check("cold 프로파일 존재", ps.by_id(COLD_ID) is not None)
    check("hot 프로파일 존재", ps.by_id(HOT_ID) is not None)
    # 모든 프로파일이 검증 통과했다는 것 = load_profiles가 예외 없이 반환
    profs = load_profiles(validate=True)
    check("load_profiles 검증 통과", len(profs) == len(ps.profiles))


def test_invalid_profile():
    print("[2] 잘못된 프로파일 → ProfileError")
    for bad, why in [({}, "빈 dict"),
                     ({"profile_id": "x", "profile_version": "1.0.0",
                       "match": {"n_columns": 10}, "header": {},
                       "flags": {}, "channels": [], "hk": {}, "cadence": {}}, "channels 비고 hk 불완전")]:
        raised = False
        try:
            validate_profile_dict(bad)
        except ProfileError:
            raised = True
        check(f"reject: {why}", raised)


def test_routing():
    print("[3] ProfileSet.route")
    ps = ProfileSet.load_default()
    check("n_columns=6179 → cold",
          getattr(ps.route(n_columns=6179), "profile_id", None) == COLD_ID)
    check("n_columns=6181 → hot",
          getattr(ps.route(n_columns=6181), "profile_id", None) == HOT_ID)
    check("filename '*Hot*' → hot",
          getattr(ps.route(filename="2026-05-26-001 Hot.dat"), "profile_id", None) == HOT_ID)
    check("filename '*Cold*' → cold",
          getattr(ps.route(filename="foo Cold.dat"), "profile_id", None) == COLD_ID)
    check("무매치(열수 이상) → None", ps.route(n_columns=999) is None)
    # n_columns가 filename보다 우선: Cold 이름인데 열수가 hot이면 열수 승
    check("n_columns 우선(6181 + Cold이름) → hot",
          getattr(ps.route(filename="weird Cold.dat", n_columns=6181), "profile_id", None) == HOT_ID)


def test_flags():
    print("[4] Flags.role_of")
    hot = ProfileSet.load_default().by_id(HOT_ID)
    check("flag 1 → atmosphere", hot.flag_role(1) == "atmosphere")
    check("flag 500 → za", hot.flag_role(500) == "za")
    check("flag 510 → he", hot.flag_role(510) == "he")
    check("flag 502 → za_wait", hot.flag_role(502) == "za_wait")
    check("미정의 flag 777 → None", hot.flag_role(777) is None)


def test_channels():
    print("[5] 채널 slice + signal_channels")
    hot = ProfileSet.load_default().by_id(HOT_ID)
    cold = ProfileSet.load_default().by_id(COLD_ID)
    sig_hot = [c.id for c in hot.signal_channels()]
    check("hot signal 2채널 (PNs,ANs)", sig_hot == ["ch_pns", "ch_ans"], f"got {sig_hot}")
    check("cold signal 1채널 (NO2)",
          [c.id for c in cold.signal_channels()] == ["ch_no2"])
    # slice: PNs 채널 columns (2053,4100) → 길이 2048
    row = _make_row(6181)
    pns = hot.channel("ch_pns")
    seg = pns.slice(row)
    check("PNs slice 길이 2048", len(seg) == 2048, f"got {len(seg)}")
    # 로직이 label에 의존하지 않음을 확인: id로 접근 가능
    check("id로 채널 접근", hot.channel("ch_ans") is not None)


def test_hk_conversion_and_bands():
    print("[6] HK 물리값 환산 + 밴드 평가")
    hot = ProfileSet.load_default().by_id(HOT_ID)
    row = _make_row(6181)
    # p_pns_cavity: rel13 → col 6162, scale 0.6895
    fld = hot.hk.field("p_pns_cavity")
    row[hot.hk.start_col + fld.rel] = 1400
    check("압력 환산 raw1400×0.6895≈965.3",
          abs(fld.value(row, hot.hk.start_col) - 1400 * 0.6895) < 1e-6)
    # oven_pns_setpoint: rel5, scale 0.01
    ov = hot.hk.field("oven_pns_setpoint")
    row[hot.hk.start_col + ov.rel] = 18000
    check("오븐 환산 raw18000×0.01=180", abs(ov.value(row, hot.hk.start_col) - 180.0) < 1e-9)

    # 밴드 평가: oven_pns warn (175,185), alarm (165,195)
    check("evaluate 180 → None", ov.evaluate(180.0) is None)
    check("evaluate 170 → warn", ov.evaluate(170.0) == "warn")
    check("evaluate 160 → alarm", ov.evaluate(160.0) == "alarm")
    check("evaluate 200 → alarm", ov.evaluate(200.0) == "alarm")

    # 밴드 없는 필드는 항상 None (표시만)
    f_no_band = HKField(key="x", rel=0)
    check("밴드 없으면 None", f_no_band.evaluate(1e9) is None)

    # HK.read: 한 번에 {key:(값,심각도)}
    readout = hot.hk.read(row)
    check("HK.read 오븐 심각도 None(180 정상)", readout["oven_pns_setpoint"][1] is None)


def test_saturation():
    print("[7] 포화 판정")
    hot = ProfileSet.load_default().by_id(HOT_ID)
    check("60001 픽셀 → 포화", hot.is_saturated([100, 60001, 200]) is True)
    check("정상 픽셀 → 비포화", hot.is_saturated([100, 200, 59000]) is False)


def test_autodetect():
    print("[8] 채널 자동탐지 (블록 최대값)")
    hot = ProfileSet.load_default().by_id(HOT_ID)
    # 합성 행: 전부 800(노이즈), block1(2053~)·block2(4101~)에 신호 픽셀 삽입
    rows = []
    for _ in range(3):
        r = _make_row(6181, fill=800)
        r[3000] = 40000   # block1 (2053..4100) 안
        r[5000] = 38000   # block2 (4101..6148) 안
        rows.append(r)
    detected = hot.autodetect_channels(rows)
    roles = [c.role for c in detected]
    check("3블록 탐지", len(detected) == 3, f"got {len(detected)}")
    check("block0 noise, block1/2 signal",
          roles == ["noise", "signal", "signal"], f"got {roles}")
    # 탐지된 signal 열범위가 선언된 것과 일치
    sig_cols = [c.columns for c in detected if c.role == "signal"]
    declared = [c.columns for c in hot.signal_channels()]
    check("탐지 signal 열범위 == 선언 열범위", sig_cols == declared,
          f"detected={sig_cols} declared={declared}")


def test_time_bytepack():
    print("[9] bytepack 시각 복원")
    hot = ProfileSet.load_default().by_id(HOT_ID)
    tb = hot.header.time_bytepack
    # 2026-01-02 00:00:00 = 1일 = 86400초 = 8,640,000 센티초
    cs = 8_640_000
    row = _make_row(6181)
    row[tb.hi_col] = (cs >> 16) & 0xFFFF
    row[tb.lo_col] = cs & 0xFFFF
    check("centiseconds 복원", tb.centiseconds(row) == cs, f"got {tb.centiseconds(row)}")
    dt = tb.to_datetime(row, year=2026)
    check("to_datetime == 2026-01-02", dt == datetime(2026, 1, 2, 0, 0, 0), f"got {dt}")


def main():
    for t in (test_load_and_validate, test_invalid_profile, test_routing,
              test_flags, test_channels, test_hk_conversion_and_bands,
              test_saturation, test_autodetect, test_time_bytepack):
        t()
    print(f"\nprofile tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
