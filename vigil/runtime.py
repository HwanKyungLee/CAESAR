"""vigil/runtime.py — 현장 PC 운용 보호막 (2026-10-01).

Vigil 은 DAQ PC 에서 LabVIEW 옆에 무인으로 돈다(설계문서 §0-A.1). 감시기 자신이 죽거나,
LabVIEW 를 굶기거나, 흔적 없이 사라지면 안 된다. 여기 모은 것:

- 파일 로그: 상태 폴더의 `vigil.log`(5 MB × 5 순환). 콘솔 출력은 어디에도 안 남는다.
- 크래시 흔적: 처리 안 된 예외 → 로그, 네이티브 크래시 → `vigil_crash.log`(faulthandler).
- LabVIEW 보호: 프로세스 우선순위 '보통 미만'. (BLAS 스레드 1개 고정은 numpy 임포트 전이어야
  해서 run_vigil.py 맨 위에서 한다.)
- 콘솔 QuickEdit 끄기: 운용자가 콘솔을 클릭하면 Windows 가 출력을 멈추고, print 가 막히면서
  GUI 까지 멈춘다.
- 상태 폴더 위치: exe(PyInstaller onedir)로 돌 땐 `%LOCALAPPDATA%\\Vigil` — 새 빌드를 다른
  폴더에 배포해도 커서가 살아남는다(2026-09-30 사고: 새 exe 폴더 → 커서 없음 → 백로그 일괄
  읽기 → PC 다운). 옛 위치에 상태가 있으면 **복사**해 온다(원본은 그대로 둔다).
"""
from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import os
import shutil
import sys
from typing import Optional

log = logging.getLogger("vigil")

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 5
_STATE_FILES = ("cursors.json", "status.jsonl")


def setup_logging(state_dir: str) -> str:
    """'vigil' 로거에 순환 파일 핸들러를 단다(+콘솔). 로그 파일 경로를 반환."""
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, "vigil.log")
    log.setLevel(logging.INFO)
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in log.handlers):
        fh = logging.handlers.RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES,
                                                  backupCount=LOG_BACKUPS, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("[vigil] %(levelname)s %(message)s"))
        log.addHandler(sh)
    return path


def install_crash_handlers(state_dir: str):
    """처리 안 된 예외는 로그로, 네이티브 크래시(segfault 등)는 vigil_crash.log 로.
    faulthandler 가 쓰는 파일 객체를 돌려준다 — 프로세스 끝까지 열어 둬야 한다."""
    def _hook(exc_type, exc, tb):
        log.critical("처리 안 된 예외", exc_info=(exc_type, exc, tb))
    sys.excepthook = _hook
    try:
        fh = open(os.path.join(state_dir, "vigil_crash.log"), "a", encoding="utf-8")
        faulthandler.enable(fh)
        return fh
    except OSError as e:
        log.warning("faulthandler 파일을 못 열었다: %s", e)
        return None


def lower_priority() -> bool:
    """Windows 에서 프로세스 우선순위를 BELOW_NORMAL 로. 다른 OS·실패 시 False."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        # 64비트에서 의사 핸들(-1)이 int 로 잘려 '핸들이 잘못되었습니다'가 되지 않게 타입을 박는다.
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k32.SetPriorityClass.restype = wintypes.BOOL
        return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000))  # BELOW_NORMAL
    except Exception:                         # noqa: BLE001
        return False


def disable_quickedit() -> bool:
    """콘솔 QuickEdit 모드를 끈다(클릭 한 번에 출력·GUI 가 멈추는 것 방지). 콘솔 없으면 False."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.GetStdHandle.restype = wintypes.HANDLE
        k32.GetConsoleMode.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.SetConsoleMode.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        h = k32.GetStdHandle(-10)             # STD_INPUT_HANDLE
        mode = wintypes.DWORD()
        if not k32.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        new = (mode.value & ~0x0040) | 0x0080  # ~ENABLE_QUICK_EDIT_MODE | ENABLE_EXTENDED_FLAGS
        return bool(k32.SetConsoleMode(h, new))
    except Exception:                         # noqa: BLE001
        return False


def default_state_dir(root: str, frozen: Optional[bool] = None,
                      local_appdata: Optional[str] = None, exe_dir: Optional[str] = None) -> str:
    """상태 폴더 기본값.

    - 소스 실행: `<repo>/vigil_state`(옛 `oculus_state` 만 있으면 그것) — 종전 그대로.
    - exe 실행: `%LOCALAPPDATA%\\Vigil`. 비어 있으면 옛 위치(exe 옆·`_internal` 안의
      vigil_state / oculus_state)에서 커서·상태 로그를 복사해 온다.
    """
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not frozen:
        new, old = os.path.join(root, "vigil_state"), os.path.join(root, "oculus_state")
        return old if (os.path.isdir(old) and not os.path.isdir(new)) else new

    local_appdata = local_appdata if local_appdata is not None else os.environ.get("LOCALAPPDATA")
    exe_dir = exe_dir or os.path.dirname(os.path.abspath(sys.executable))
    if not local_appdata:
        return os.path.join(exe_dir, "vigil_state")
    target = os.path.join(local_appdata, "Vigil")
    if not os.path.isfile(os.path.join(target, "cursors.json")):
        for base in (exe_dir, root):
            for name in ("vigil_state", "oculus_state"):
                src = os.path.join(base, name)
                if os.path.isfile(os.path.join(src, "cursors.json")):
                    _copy_state(src, target)
                    return target
    return target


def _copy_state(src: str, dst: str) -> None:
    os.makedirs(dst, exist_ok=True)
    for fn in _STATE_FILES:
        s = os.path.join(src, fn)
        if os.path.isfile(s) and not os.path.exists(os.path.join(dst, fn)):
            shutil.copy2(s, os.path.join(dst, fn))
    log.info("옛 상태 폴더 %s 의 커서·상태 로그를 %s 로 복사했다(원본은 그대로)", src, dst)
