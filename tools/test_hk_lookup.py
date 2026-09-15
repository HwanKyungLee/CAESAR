"""tools/test_hk_lookup.py — data_io 의 HK 판독이 **값 탐색이 아니라 열 지도**인지.

2026-09-15 이전 data_io 는 "6160을 읽어 800~1200 mbar 면 cold, 아니면 6162를 읽어…"
식으로 **값이 그럴듯한지로 어느 열이 압력인지** 판별했다. 그래서 그 창을 벗어나는
환경에서는 압력 열을 못 찾고 T·P 가 **조용히** 기본값(1013.25 / 25.0)으로 떨어졌다.
온도도 `0 < T < 100 °C` 게이트라 영하·가열셀에서 같은 식으로 탈락했다.

raw 구성은 **열 수 하나로 결정**되므로(6181 hot / 6179·6174 cold) 레지스트리에서
지도를 받아 박힌 열을 읽으면 된다. 이 검사는 그게 유지되는지를 고정한다.

    python tools/test_hk_lookup.py
"""
from __future__ import annotations

import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.data_io import DataIO
from core.raw_parser import P_SCALE

_FAIL = []


def check(name, cond, extra=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s  %s" % (name, extra))
        _FAIL.append(name)


def _row(d, name, ncols=6181, p_mbar=1000.0, t_c=30.0, flag=1):
    """합성 raw 한 행. 핫(6181) 기준으로 P/T 열을 채운다."""
    v = ["0"] * ncols
    v[0], v[1], v[2], v[3], v[4] = "18125", "43986", "900", "-1000", str(flag)
    for i in range(2053, min(6149, ncols)):
        v[i] = "50000"                      # 스펙트럼(활성으로 보이게)
    if ncols >= 6181:
        v[6162] = str(int(round(p_mbar / P_SCALE)))   # P_PNs
        v[6164] = str(int(round(p_mbar / P_SCALE)))   # P_ANs
        v[6174] = str(int(round(t_c * 100)))          # tempcell1
        v[6155] = "7500"                              # 셀히터 설정값 75 °C(최후 폴백)
    fp = os.path.join(d, name)
    with open(fp, "w", encoding="utf-8") as fh:
        fh.write("\t".join(v) + "\n")
    return fp


def test_pressure_any_environment(d):
    """지상 기대창(800~1200) **밖에서도** 실제 압력이 나와야 한다.

    옛 코드는 이 창을 '어느 열이 압력인가' 판별에 썼다 — 항공/고지대에서 열을 못 찾고
    1013.25 로 조용히 떨어졌다. 5.5 km 면 n_air 가 2배 틀리고 ppb 가 절반이 된다."""
    print("[1] 압력 — 어떤 환경이든 (지상창 밖 포함)")
    for lbl, p in (("지상", 1013.0), ("해양", 975.0), ("고지대", 780.0),
                   ("항공 5.5km", 500.0), ("항공 10km", 265.0), ("성층권", 120.0)):
        fp = _row(d, "p_%d.dat" % int(p), p_mbar=p)
        _, _, _, _, got = DataIO.load_measurement_with_hk(fp, row_index=0, channel=1)
        check("%s %.0f mbar" % (lbl, p), abs(got - p) < 1.0, got)
    # 기본값으로 떨어지지 않았는지 — 1013.25 는 '못 읽었다'의 신호다
    fp = _row(d, "p_low.dat", p_mbar=300.0)
    _, _, _, _, got = DataIO.load_measurement_with_hk(fp, row_index=0, channel=1)
    check("기본값(1013.25)으로 폴백하지 않는다", abs(got - 1013.25) > 1.0, got)


def test_temperature_any_environment(d):
    """영하·가열셀에서도 실측 온도가 나와야 한다(옛 게이트: 0 < T < 100)."""
    print("[2] 온도 — 어떤 환경이든")
    for lbl, t in (("상온", 30.0), ("저온", 5.0), ("한랭", -5.0),
                   ("극한", -40.0), ("가열셀", 120.0)):
        fp = _row(d, "t_%s.dat" % lbl, t_c=t)
        _, _, _, got, _ = DataIO.load_measurement_with_hk(fp, row_index=0, channel=1)
        check("%s %.1f °C" % (lbl, t), abs(got - t) < 0.01, got)
    # 75.00 은 셀히터 **설정값** 폴백의 지문 — 실측이 있는데 이게 나오면 탈락한 것
    fp = _row(d, "t_neg.dat", t_c=-10.0)
    _, _, _, got, _ = DataIO.load_measurement_with_hk(fp, row_index=0, channel=1)
    check("설정값(75 °C)으로 폴백하지 않는다", abs(got - 75.0) > 0.01, got)


def test_columns_not_value_searched(d):
    """압력 열에 **그럴듯하지 않은** 값이 들어 있어도 그 열을 읽어야 한다.

    값으로 열을 찾던 시절엔 이 경우 다른 열로 건너뛰거나 기본값으로 떨어졌다.
    지금은 '열 지도가 정본'이므로 값이 뭐든 그 열을 읽는다(범위는 경보만)."""
    print("[3] 열 지도가 정본 — 값이 이상해도 그 열을 읽는다")
    fp = _row(d, "odd.dat", p_mbar=50.0, t_c=-60.0)
    _, _, _, t, p = DataIO.load_measurement_with_hk(fp, row_index=0, channel=1)
    check("P=50 mbar 를 그대로 읽는다", abs(p - 50.0) < 1.0, p)
    check("T=-60 °C 를 그대로 읽는다", abs(t + 60.0) < 0.01, t)


def test_channel_out_of_range_warns(d):
    """범위를 넘는 channel 은 **조용히** clamp 되면 안 된다.

    옛 동작: 핫에서 channel=3 을 요청하면 경고 없이 channel=2 배열이 돌아왔다.
    (동작 자체는 호환을 위해 유지하되, 침묵만 없앤다.)"""
    print("[4] channel 범위 초과는 경고한다")
    fp = _row(d, "ch.dat")
    DataIO._warned.clear()
    DataIO.load_measurement_with_hk(fp, row_index=0, channel=9)
    msgs = [m for m in DataIO._warned if "channel=9" in m]
    check("경고가 남는다", bool(msgs), sorted(DataIO._warned))
    # 같은 경고는 한 번만(초당 1행이라 로그가 묻히면 안 된다)
    before = len(DataIO._warned)
    DataIO.load_measurement_with_hk(fp, row_index=0, channel=9)
    check("같은 경고는 한 번만", len(DataIO._warned) == before, len(DataIO._warned))


def test_out_of_band_pressure_warns(d):
    """지상창 밖 압력은 **버리지 않고 경고만** 한다(무결성 헌장: 지우지 말고 flag)."""
    print("[5] 지상창 밖 압력은 경고하되 값은 살린다")
    DataIO._warned.clear()
    fp = _row(d, "hi_alt.dat", p_mbar=400.0)
    _, _, _, _, p = DataIO.load_measurement_with_hk(fp, row_index=0, channel=1)
    check("값은 살아있다", abs(p - 400.0) < 1.0, p)
    check("경고가 남는다", any("mbar" in m for m in DataIO._warned), sorted(DataIO._warned))


def main() -> int:
    d = tempfile.mkdtemp(prefix="hk-lookup-")
    test_pressure_any_environment(d)
    test_temperature_any_environment(d)
    test_columns_not_value_searched(d)
    test_channel_out_of_range_warns(d)
    test_out_of_band_pressure_warns(d)
    if _FAIL:
        print("hk lookup tests: %d FAIL" % len(_FAIL))
        return 1
    print("hk lookup self-check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
