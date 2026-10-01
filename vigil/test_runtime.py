"""vigil 현장 운용 보호막 단위테스트 (2026-10-01, 데이터 비의존).

커버:
  1) tick 예외 격리 — 슬롯에서 예외가 새면 PyQt6 가 프로세스를 abort 한다. tick() 이 받아서
     P1 '내부 오류'로 띄우고 다음 tick 을 계속 도는지, 복구되면 카운터가 0 으로 돌아가는지
  2) 파일 퇴역 — 새 행이 끊긴 지 오래된 파일의 파일별 상태가 빠져 종합 경보를 붙잡지 않는지
  3) 커서 저장 — 간격 안에선 디스크에 안 쓰고(flush 로 강제), 저장 실패(PermissionError)에도
     예외 없이 다음에 다시 쓰는지
  4) 상태 로그 — 쓰기 실패에도 예외 없음
  5) 상태 폴더 기본값 — exe 면 %LOCALAPPDATA%\\Vigil, 옛 vigil_state/oculus_state 에서 복사
     (원본 보존), 소스 실행은 종전 그대로

사용: python vigil/test_runtime.py → 전부 PASS면 exit 0
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from vigil.alert_engine import OK, P1
from vigil.ingest_cursor import IngestCursor
from vigil.profile import DEFAULT_PROFILE_DIR
from vigil.run_vigil import VigilApp
from vigil.runtime import default_state_dir
from vigil.state_log import StateLog

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


class _Dash:
    """대시보드 대역 — set_status/log_line 만 기록, 나머지는 무시."""
    def __init__(self):
        self.status, self.lines = [], []

    def set_status(self, s, m):
        self.status.append((s, m))

    def log_line(self, t):
        self.lines.append(t)

    def __getattr__(self, name):          # update_files·update_*_trend
        return lambda *a, **k: None


def test_tick_guard():
    print("[1] tick 예외 격리")
    with tempfile.TemporaryDirectory() as d:
        dash = _Dash()
        app = VigilApp(d, DEFAULT_PROFILE_DIR, os.path.join(d, "st"), dashboard=dash)
        real_poll = app.watcher.poll

        def boom():
            raise PermissionError("cursors.json 잠김(가짜)")
        app.watcher.poll = boom
        try:
            app.tick()
            app.tick()
            ok = True
        except Exception as e:            # noqa: BLE001
            ok = False
            check("예외가 밖으로 안 샌다", False, repr(e))
        if ok:
            check("예외가 밖으로 안 샌다", True)
        check("연속 실패 카운트", app._tick_errors == 2, f"{app._tick_errors}")
        check("배지 P1 '내부 오류'", dash.status and dash.status[-1][0] == P1
              and "internal error" in dash.status[-1][1], f"{dash.status[-1:]}")
        recs = [json.loads(l) for l in open(os.path.join(d, "st", "status.jsonl"), encoding="utf-8")]
        check("상태 로그엔 연속 실패의 첫 번만", sum(r.get("kind") == "internal" for r in recs) == 1)
        app.watcher.poll = real_poll
        app.tick()
        check("복구되면 카운터 0", app._tick_errors == 0)
        recs = [json.loads(l) for l in open(os.path.join(d, "st", "status.jsonl"), encoding="utf-8")]
        check("복구 기록", recs[-1]["status"] == OK and "recovered" in recs[-1]["msg"] or
              any("recovered" in r["msg"] for r in recs))


def test_retire():
    print("[2] 오래 조용한 파일 퇴역 — 지난 파일 경보가 종합을 붙잡지 않는다")
    with tempfile.TemporaryDirectory() as d:
        app = VigilApp(d, DEFAULT_PROFILE_DIR, os.path.join(d, "st"), retire_after_sec=600)
        now = datetime.now()
        old, cur = os.path.join(d, "old.dat"), os.path.join(d, "cur.dat")
        app._files_seen = {old: now - timedelta(seconds=900), cur: now - timedelta(seconds=1)}
        app._hk_status = {old: (P1, "옛 파일 압력 이탈", {}), cur: (OK, "정상", {})}
        app._hk_last_status = {old: P1, cur: OK}
        app._retire_stale_files(now)
        check("오래된 파일 빠짐", old not in app._files_seen and old not in app._hk_status)
        check("현재 파일 유지", cur in app._files_seen and cur in app._hk_status)


def test_cursor_save():
    print("[3] 커서 저장 간격·실패 허용")
    with tempfile.TemporaryDirectory() as d:
        st = os.path.join(d, "cursors.json")
        c = IngestCursor(st)
        c.set("a.dat", 10, save=False)
        check("save=False 면 아직 디스크에 없음", not os.path.exists(st))
        check("flush 가 쓴다", c.flush() and IngestCursor(st).get("a.dat") == 10)
        check("바뀐 게 없으면 flush 는 쓰지 않아도 True", c.flush() is True)

        orig = c._save
        def locked():
            raise PermissionError("[WinError 5] 액세스가 거부되었습니다(가짜)")
        c._save = locked
        c.set("a.dat", 20, save=False)
        try:
            r = c.flush()
            check("저장 실패해도 예외 없음, False", r is False)
        except Exception as e:            # noqa: BLE001
            check("저장 실패해도 예외 없음, False", False, repr(e))
        c._save = orig
        check("다음 flush 에 다시 써진다", c.flush() and IngestCursor(st).get("a.dat") == 20)


def test_state_log_failure():
    print("[4] 상태 로그 쓰기 실패에도 예외 없음")
    with tempfile.TemporaryDirectory() as d:
        sl = StateLog(os.path.join(d, "status.jsonl"))
        sl.path = d                        # 폴더를 파일처럼 열면 OSError
        try:
            sl.append(OK, "테스트")
            check("예외 없음", True)
        except Exception as e:            # noqa: BLE001
            check("예외 없음", False, repr(e))


def test_default_state_dir():
    print("[5] 상태 폴더 기본값·옛 상태 복사")
    with tempfile.TemporaryDirectory() as d:
        root = os.path.join(d, "repo")
        os.makedirs(os.path.join(root, "oculus_state"))
        check("소스 실행: 옛 oculus_state 만 있으면 그것",
              default_state_dir(root, frozen=False) == os.path.join(root, "oculus_state"))

        exe_dir = os.path.join(d, "Vigil_new_build")
        old = os.path.join(exe_dir, "_internal", "oculus_state")
        os.makedirs(old)
        with open(os.path.join(old, "cursors.json"), "w") as fh:
            json.dump({os.path.abspath("x.dat"): {"offset": 7, "mtime": 0}}, fh)
        appdata = os.path.join(d, "LocalAppData")
        got = default_state_dir(os.path.join(exe_dir, "_internal"), frozen=True,
                                local_appdata=appdata, exe_dir=exe_dir)
        check("exe: %LOCALAPPDATA%\\Vigil", got == os.path.join(appdata, "Vigil"), got)
        check("옛 커서 복사됨", IngestCursor(os.path.join(got, "cursors.json")).get("x.dat") == 7)
        check("원본 보존", os.path.isfile(os.path.join(old, "cursors.json")))
        with open(os.path.join(got, "cursors.json"), "w") as fh:
            json.dump({os.path.abspath("x.dat"): {"offset": 99, "mtime": 0}}, fh)
        default_state_dir(os.path.join(exe_dir, "_internal"), frozen=True,
                          local_appdata=appdata, exe_dir=exe_dir)
        check("이미 있으면 덮어쓰지 않음",
              IngestCursor(os.path.join(got, "cursors.json")).get("x.dat") == 99)


def test_priority():
    print("[6] 프로세스 우선순위 '보통 미만' (Windows)")
    if os.name != "nt":
        check("Windows 아님 — False", __import__("vigil.runtime").runtime.lower_priority() is False)
        return
    import ctypes
    from ctypes import wintypes
    from vigil.runtime import lower_priority
    check("lower_priority() True", lower_priority() is True)   # 64비트 의사 핸들 잘림 회귀(2026-10-01)
    k = ctypes.windll.kernel32
    k.GetPriorityClass.argtypes = (wintypes.HANDLE,)
    check("우선순위 클래스 = BELOW_NORMAL", k.GetPriorityClass(k.GetCurrentProcess()) == 0x4000)


def main():
    for t in (test_tick_guard, test_retire, test_cursor_save, test_state_log_failure,
              test_default_state_dir, test_priority):
        t()
    print(f"\nruntime tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
