"""행 시각 vs PC 시계 감시 자체검증 (vigil/monitors/clock_monitor.py, 데이터 불필요, Qt offscreen).

  1) 판정: 수 초 = OK, 거의 −9 h = P2 시간대(2026-05 핫 PC 사건 모양), +10 분 = P2 늦게 도착, −2 분 = P2 앞섬,
     튀는 한 행은 중앙값이라 경보 안 함, 표본 3개 전엔 판정 없음
  2) offset_seconds: PC 로컬 도착 시각 − UTC 행 시각 — PC 시간대 설정과 무관하게 ≈ 0
  3) VigilApp: UTC 로 바르게 찍힌 핫 파일 → OK·카드·1분 기록 열, KST 를 UTC 처럼 찍은 파일 → P2 시간대,
     이미 닫힌(오래전에 쓴) 파일의 끝 행은 표본으로 안 쓴다(시작 때 '늦게 도착' 오보 금지)
"""
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_self_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

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


def _rows(n, t_utc):
    """핫 행 n 개 — bytepack = t_utc(naive UTC) 의 연초 기준 센티초."""
    out = []
    y0 = datetime(t_utc.year, 1, 1)
    for k in range(n):
        cs = int(((t_utc - y0).total_seconds() + k) * 100)
        v = ["500"] * NC
        v[0], v[1], v[4] = str(cs >> 16), str(cs & 0xFFFF), "1"
        v[2053:6149] = ["9000"] * 4096
        out.append("\t".join(v))
    return "\n".join(out) + "\n"


def main():
    from vigil.alert_engine import OK, P2
    from vigil.monitors.clock_monitor import ClockMonitor, offset_seconds

    def run(offs):
        m = ClockMonitor()
        r = None
        for o in offs:
            r = m.observe(o)
        return r

    check("1) 표본 3개 전엔 판정 없음", run([2.0, 3.0]) is None)
    r = run([2, 3, 4, 3])
    check("1) 수 초 = OK", r[0] == OK and abs(r[2]["offset_s"] - 3) < 1, r)
    r = run([-32400 + 3] * 5)
    check("1) −9 h = P2 시간대 변환", r[0] == P2 and "9 h ahead" in r[1] and "time-zone" in r[1], r)
    r = run([600] * 5)
    check("1) +10 분 = P2 늦게 도착", r[0] == P2 and "after their own timestamp" in r[1], r)
    r = run([-120] * 5)
    check("1) −2 분 = P2 앞섬", r[0] == P2 and "ahead of the PC clock" in r[1], r)
    r = run([3, 3, 4, 3, 9000, 3, 3])
    check("1) 튀는 한 행은 무시(중앙값)", r[0] == OK, r)

    now_local = datetime.now()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    off = offset_seconds(now_utc, now_local)
    check("2) 로컬 도착 − UTC 행 시각 ≈ 0 (PC 시간대 무관)", off is not None and abs(off) < 2, off)

    # 3) VigilApp
    from PyQt6.QtCore import QCoreApplication
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    from vigil.profile import DEFAULT_PROFILE_DIR
    from vigil.run_vigil import VigilApp

    def app_with(fname, t_utc, mtime_age=0.0):
        d = tempfile.mkdtemp()
        raw, st = os.path.join(d, "raw"), os.path.join(d, "state")
        os.makedirs(raw)
        f = os.path.join(raw, fname)
        with open(f, "w") as fh:
            fh.write(_rows(5, t_utc))
        if mtime_age:
            t = time.time() - mtime_age
            os.utime(f, (t, t))
        core = VigilApp(raw, DEFAULT_PROFILE_DIR, st, backlog_age_sec=None)
        for k in range(4):                       # 행이 계속 붙는다(계기가 쓰는 중)
            if not mtime_age:
                with open(f, "a") as fh:
                    fh.write(_rows(1, t_utc + timedelta(seconds=5 + k)))
            core.tick()
        return d, st, core

    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    d, st, core = app_with(f"{utc_now:%Y-%m-%d}-001 Hot.dat", utc_now - timedelta(seconds=5))
    try:
        res = core._clock_by_inst.get("caesar_hot_base")
        check("3) UTC 로 바른 파일 → OK", res is not None and res[0] == OK, res)
        cards = [c for c in core._cards() if c["key"][0] == "clock"]
        check("3) 카드 'Clock hot'", cards and cards[0]["title"] == "Clock hot", cards)
        vals = core._record_values(OK, datetime.now())
        check("3) 1분 기록 열 clock:caesar_hot_base_offset_s", "clock:caesar_hot_base_offset_s" in vals, list(vals)[:6])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # KST 를 UTC 처럼 찍은 파일(2026-05 핫 PC) — 행 시각이 9 h 미래
    kst_as_utc = utc_now + timedelta(hours=9) - timedelta(seconds=5)
    d, st, core = app_with(f"{utc_now:%Y-%m-%d}-002 Hot.dat", kst_as_utc)
    try:
        res = core._clock_by_inst.get("caesar_hot_base")
        check("3) KST-as-UTC 파일 → P2 시간대", res is not None and res[0] == P2 and "9 h" in res[1], res)
        recs = [json.loads(x) for x in open(os.path.join(st, "status.jsonl"), encoding="utf-8")]
        check("3) status.jsonl 에 kind=clock", any(r.get("kind") == "clock" and r["status"] == P2 for r in recs))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # 이미 닫힌 파일(1시간 전에 다 쓴 지난 파일)의 끝 행 — 표본 아님
    d, st, core = app_with(f"{utc_now:%Y-%m-%d}-003 Hot.dat", utc_now - timedelta(hours=1), mtime_age=3600)
    try:
        check("3) 닫힌 파일의 끝 행으로 '늦게 도착' 오보 없음", "caesar_hot_base" not in core._clock_by_inst,
              core._clock_by_inst)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\nclock monitor tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
