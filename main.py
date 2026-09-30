import sys
import os

# ── 크래시 로그 ──────────────────────────────────────────────────────────────
# 밤샘 런 중 프로세스가 소리없이 죽으면(OOM/액세스 위반/미처리 예외) 원인을 알 수
# 없으므로, 하드크래시는 faulthandler가, 파이썬 예외는 excepthook이 logs/에 남긴다.
import faulthandler
import traceback
import datetime as _dt

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(_LOG_DIR, exist_ok=True)
_crash_fh = open(os.path.join(_LOG_DIR, 'crash.log'), 'a', encoding='utf-8')
_crash_fh.write(f"\n===== session start {_dt.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
_crash_fh.flush()
faulthandler.enable(file=_crash_fh, all_threads=True)

def _excepthook(etype, value, tb):
    try:
        _crash_fh.write(f"\n[uncaught exception {_dt.datetime.now():%Y-%m-%d %H:%M:%S}]\n")
        traceback.print_exception(etype, value, tb, file=_crash_fh)
        _crash_fh.flush()
    except Exception:
        pass
    sys.__excepthook__(etype, value, tb)
sys.excepthook = _excepthook

# stdout/stderr를 logs/session_*.log 로도 남긴다(진단 print 사후 추적용).
from core.session_log import install as _install_session_log
_install_session_log()

# NOTE: keep these top-level imports lightweight. The heavy import
# (`gui.app_window`, which pulls in matplotlib + scipy via the dialog
# modules) is deferred until *after* the splash is on screen — otherwise
# the logo can't appear until ~a second of import work finishes first.
from PyQt6.QtWidgets import QApplication

from core.__version__ import __version__

# ─── Entry point ────────────────────────────────────────────────────────────
# Everything starts here when you run  python main.py
if __name__ == '__main__':
    # Qt requires one QApplication instance per process before any widgets exist
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Fusion style: clean, modern look on all platforms

    # ── Splash screen ────────────────────────────────────────────────────────
    # Show it FIRST, before any heavy import or window build. Every log line on it
    # is a boot step that actually finished (gui/splash.py) — no canned text.
    from gui.splash import AugurSplash
    splash = AugurSplash(__version__, "Analyzer of Unseen Gases Using Resonators", n_steps=6)
    splash.show()
    splash.pump()
    splash.step("engine", f"Augur v{__version__}")

    # Heavy third-party imports (numpy/scipy/matplotlib ≈ 1 s) run in a thread so the
    # animation keeps moving. Qt-touching modules stay on the main thread below.
    import threading, importlib
    def _prewarm():
        for _m in ("numpy", "scipy.interpolate", "scipy.optimize", "scipy.signal",
                   "scipy.ndimage", "matplotlib", "matplotlib.figure"):
            try:
                importlib.import_module(_m)
            except Exception:   # noqa: BLE001 — the real import below reports it
                pass
    _pre = threading.Thread(target=_prewarm, daemon=True)
    _pre.start()

    # Scale font size relative to screen height (reference: 1080p → 9pt)
    from core.data_io import ui_scale
    _s = ui_scale()
    _font = app.font()
    _font.setPointSize(max(7, round(9 * _s)))
    app.setFont(_font)

    # ── 캠페인 레이아웃 등록 ──────────────────────────────────────────────────
    # raw .dat의 컬럼 배치(채널 블록·HK 열)는 캠페인마다 다르다. 기본 등록은 2026 여수
    # 구성이고, `oculus/profiles/`에 다른 구성의 프로파일 JSON이 있으면 여기서 함께
    # 등록된다 — **새 캠페인은 코드를 고치지 않고 JSON만 얹으면 된다**(열 수로 자동 라우팅).
    # 이미 아는 열 수는 덮지 않는다. 실패해도 앱은 그대로 뜬다.
    try:
        from core.raw_parser import autoload_campaign_layouts, CAMPAIGN_LAYOUTS
        _new = autoload_campaign_layouts()
        splash.step("layouts", f"{len(CAMPAIGN_LAYOUTS)} known ({len(_new)} from profiles)")
    except Exception as _e:   # noqa: BLE001
        print(f"[main] 캠페인 레이아웃 자동등록 건너뜀: {_e}")
        splash.step("layouts", f"{type(_e).__name__}", "fail")

    # 지난 세션에 남긴 사용자 설정 — 창이 같은 키로 다시 읽는다(gui/app_window.py).
    from PyQt6.QtCore import QSettings
    _qs = QSettings("CAESAR", "app")
    _camp = _qs.value("campaign", "", type=str)
    splash.step("campaign", _camp or "not set", "ok" if _camp else "skip")
    _cpu = _qs.value("cpu_workers", 0, type=int)
    splash.step("workers", f"{_cpu} cpu" if _cpu else f"default ({os.cpu_count()} cpu)")

    from core.provenance import code_version
    _ver = code_version()
    splash.step("build", _ver, "ok" if not _ver.endswith(("-dirty", "-unknown")) and _ver != "nogit" else "skip")

    splash.wait_while(_pre.is_alive)

    # ── Main window initialization ───────────────────────────────────────────
    # Building the window blocks the main thread (~1 s), which freezes the
    # animation — so let it reach its still final frame first.
    from gui.app_window import CAESARAnalyzer  # The main application window class
    splash.wait_settled()
    ex = CAESARAnalyzer()
    splash.step("interface", "ready")

    ex.showMaximized()

    # Dissolve the splash and bring the fully loaded main window to the front
    if 'splash' in locals():
        splash.finish(ex)

    # Hand control over to the Qt event loop.
    # This call blocks until the user closes the window, then returns an exit code.
    sys.exit(app.exec())
