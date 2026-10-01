"""Vigil Start/Stop 자체검증 (데이터 불필요, Qt offscreen).

  1) pause 중 tick 은 아무것도 읽지 않는다(커서 정지) — raw 는 계속 쌓인다
  2) pause 즉시 커서를 디스크에 저장한다
  3) resume 하면 밀린 줄부터 이어 읽는다
  4) 정지·재개가 state_log 에 kind=control 로 남고, 같은 상태로 두 번 눌러도 한 번만
  5) 대시보드: 버튼이 run_toggled 를 내고, 정지 배지는 경보색이 아니며, 정지 중 set_status 는 무시
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
# 직접 실행하면 vigil/ 이 sys.path 맨 앞에 와서 vigil/profile.py 가 표준 profile 을 가린다
_self_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PyQt6.QtWidgets import QApplication

_n_pass = _n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


NC = 6181


def _rows(n, t0):
    out = []
    for k in range(n):
        cs = int((t0 + k) * 100)
        v = ["0"] * NC
        v[0], v[1], v[4] = str(cs >> 16), str(cs & 0xFFFF), "1"
        v[2053:6149] = ["9000"] * 4096
        out.append("\t".join(v))
    return "\n".join(out) + "\n"


def main():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from vigil.alert_engine import P0
    from vigil.dashboard.dashboard_window import DashboardWindow
    from vigil.profile import DEFAULT_PROFILE_DIR
    from vigil.run_vigil import VigilApp

    d = tempfile.mkdtemp()
    raw, st = os.path.join(d, "raw"), os.path.join(d, "state")
    os.makedirs(raw)
    f = os.path.join(raw, "2026-06-20-001.dat")
    with open(f, "w") as fh:
        fh.write(_rows(20, 13_000_000))
    try:
        core = VigilApp(raw, DEFAULT_PROFILE_DIR, st)
        core.tick()
        read0 = core.cursor.get(f)
        check("처음 tick 이 읽음", read0 == os.path.getsize(f), f"{read0}/{os.path.getsize(f)}")

        core.pause()
        with open(os.path.join(st, "cursors.json"), encoding="utf-8") as fh:
            on_disk = json.load(fh)
        check("pause 즉시 커서 저장", any(v.get("offset") == read0 for v in on_disk.values()))
        with open(f, "a") as fh:
            fh.write(_rows(10, 13_001_000))
        core.tick(); core.tick()
        check("정지 중엔 읽지 않음", core.cursor.get(f) == read0)
        core.pause()                                    # 두 번 눌러도 기록은 한 번

        core.resume()
        core.tick()
        check("재개하면 밀린 줄부터 이어 읽음", core.cursor.get(f) == os.path.getsize(f))
        kinds = [json.loads(x).get("kind") for x in open(os.path.join(st, "status.jsonl"), encoding="utf-8")]
        check("정지·재개가 state_log 에 한 번씩", kinds.count("control") == 2, kinds.count("control"))

        win = DashboardWindow(title="t")
        got = []
        win.run_toggled.connect(got.append)
        win._toggle_run()
        check("Stop → run_toggled(False), 버튼 Start", got == [False] and "Start" in win.btn_run.text())
        check("정지 배지(경보색 아님)", "정지" in win.badge.text() and "#C62828" not in win.badge.styleSheet())
        win.set_status(P0, "늦게 도착한 경보")
        check("정지 중 set_status 무시", "정지" in win.badge.text())
        win._toggle_run()
        check("Start → run_toggled(True), 버튼 Stop", got == [False, True] and "Stop" in win.btn_run.text())
        win.set_status(P0, "재개 뒤 경보")
        check("재개 뒤 set_status 반영", "재개 뒤 경보" in win.badge.text())
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\npause tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
