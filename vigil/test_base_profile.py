"""기본(구조) 프로파일 + 미션 자체검증 (2026-10-02, 데이터 불필요, Qt offscreen).

미션(셀 정체)이 없는 날짜의 raw 도 Vigil 이 감시해야 한다 — 예전엔 "NOT monitored" 뿐이었다.
  1) 미션이 날짜를 덮으면 미션(ANs/PNs, 농도·R 설정), 안 덮으면 기본(ch0/ch1/ch2, 셀 정체 없음)
  2) 기본 프로파일: 빛이 들어오는 auto 블록만 램프 감시(어두운 ch0 은 안 함), 농도·R 감시기는 안 생김,
     HK 는 평가, P2 'No mission' 한 번
  3) HK 결측: raw 0 은 '값 없음' — 0 °C 로 읽지 않는다. 밴드 없는 표시용 열의 결측은 조용히,
     채널 1순위 캐비티 센서(tempcell1 = ANs 온도)의 결측은 P2
  4) 미션은 구조를 못 바꾼다(열 이동·없는 블록 → 오류)
"""
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_self_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PyQt6.QtCore import QCoreApplication

_n_pass = _n_fail = 0
NC = 6181


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def _rows(n, t0, hk=None):
    """핫 행: ch1·ch2 밝음(9000), ch0 어두움(500), HK 는 그럴듯한 값(raw)."""
    out = []
    for k in range(n):
        cs = int((t0 + k) * 100)
        v = ["500"] * NC
        v[0], v[1], v[4] = str(cs >> 16), str(cs & 0xFFFF), "1"
        v[2053:6149] = ["9000"] * 4096
        for c, val in (hk or {}).items():
            v[c] = str(val)
        out.append("\t".join(v))
    return "\n".join(out) + "\n"


def main():
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    from core.profile import ProfileError, ProfileSet, merge_mission
    from vigil.alert_engine import P2
    from vigil.monitors.hk_monitor import evaluate_hk
    from vigil.profile import DEFAULT_PROFILE_DIR
    from vigil.run_vigil import VigilApp

    ps = ProfileSet.load_default()
    june = ps.route(filename="2026-06-20-001 Hot.dat", n_columns=NC)
    octo = ps.route(filename="2026-10-02-001 Hot.dat", n_columns=NC)
    check("6월 → 미션(ANs/PNs)", june.is_mission and [c.label for c in june.signal_channels()] == ["ANs", "PNs"],
          june.profile_id)
    check("10월 → 기본(구조): ch0 noise · ch1/ch2 auto, 농도·R 없음",
          not octo.is_mission and [(c.id, c.role) for c in octo.channels]
          == [("ch0", "noise"), ("ch1", "auto"), ("ch2", "auto")]
          and all(c.concentration is None and c.reflectance is None for c in octo.channels),
          octo.profile_id)
    check("미션과 기본의 HK 열지도가 같다(구조는 기본 한 곳)",
          [(f.key, f.rel) for f in june.hk.fields] == [(f.key, f.rel) for f in octo.hk.fields])

    # 2) VigilApp — 10월 핫 파일
    d = tempfile.mkdtemp()
    try:
        raw, st = os.path.join(d, "raw"), os.path.join(d, "state")
        os.makedirs(raw)
        f = os.path.join(raw, "2026-10-02-001 Hot.dat")
        hk_ok = {6149: 2400, 6150: 2400, 6151: 30000, 6154: 18000, 6155: 7500,
                 6162: 1400, 6164: 1330, 6174: 3300, 6175: 3100}
        with open(f, "w") as fh:
            fh.write(_rows(5, 23_600_000, hk_ok))
        core = VigilApp(raw, DEFAULT_PROFILE_DIR, st)
        core.tick()
        recs = [json.loads(x) for x in open(os.path.join(st, "status.jsonl"), encoding="utf-8")]
        nm = [r for r in recs if r.get("msg", "").startswith("No mission")]
        check("P2 'No mission'(기본으로 감시) 한 번", len(nm) == 1 and nm[0]["status"] == P2, [r.get("msg") for r in recs])
        check("internal 오류 없음", not [r for r in recs if r.get("kind") == "internal"])
        lamp_ch = sorted(k[1] for k in core._lamp_monitors)
        check("램프 감시: 빛이 들어오는 ch1·ch2 만(어두운 ch0 제외)", lamp_ch == ["ch1", "ch2"], lamp_ch)
        check("농도·R 감시기는 안 생긴다", not core._conc_monitors and not core._r_monitors,
              (list(core._conc_monitors), list(core._r_monitors)))
        check("HK 는 평가된다", bool(core._hk_status))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # 3) HK 결측
    row = [500.0] * NC
    row[4] = 1
    for c, val in hk_ok.items():
        row[c] = float(val)
    st0, msg0, _ = evaluate_hk(june, row, phase="sampling")
    check("정상 행: 늘 죽어 있는 표시용 열(templed4 등 = 0)은 경보 안 함", "templed4" not in msg0
          and "LED4" not in msg0, msg0)
    row[6174] = 0.0                                   # tempcell1 raw 0 = 값 없음
    st1, msg1, mt1 = evaluate_hk(june, row, phase="sampling")
    check("tempcell1 = 0 → '값 없음'(0 °C 아님)", mt1["readings"]["tempcell1"][0] != 0.0
          and mt1["readings"]["tempcell1"][0] != mt1["readings"]["tempcell1"][0], mt1["readings"]["tempcell1"])
    check("ANs 1순위 온도 센서 결측 → P2", st1 == P2 and "missing" in msg1, (st1, msg1))

    # 4) 미션은 구조를 못 바꾼다
    base = json.load(open(os.path.join(DEFAULT_PROFILE_DIR, "base_hot_6181.json"), encoding="utf-8"))
    for bad, why in (({"profile_id": "x", "profile_version": "1.0.0", "base": "caesar_hot_base",
                       "channels": [{"id": "ch1", "columns": [2000, 4047]}]}, "열 이동"),
                     ({"profile_id": "x", "profile_version": "1.0.0", "base": "caesar_hot_base",
                       "channels": [{"id": "ch9", "role": "signal"}]}, "없는 블록"),
                     ({"profile_id": "x", "profile_version": "1.0.0", "base": "caesar_hot_base",
                       "match": {"n_columns": 6179}, "channels": []}, "열 수 변경")):
        try:
            merge_mission(base, bad)
            check(f"미션이 구조를 바꾸면 오류: {why}", False, "오류가 안 났다")
        except ProfileError:
            check(f"미션이 구조를 바꾸면 오류: {why}", True)

    print(f"\nbase profile tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
