import sys
import os

# WMI 우회 — Python 3.13 의 platform.machine() 은 WMI 에 묻는데, WMI 서비스가 멈추면 영영
# 안 돌아온다. pandas 가 임포트 중에 그걸 불러 Augur 가 로딩에서 멈췄다(2026-10-01 실측).
# _wmi 를 '없음'으로 두면 platform 이 환경변수로 판단한다. platform 이 임포트되기 전이어야 한다.
sys.modules.setdefault("_wmi", None)

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
    # Fusion + 종이·잉크 팔레트를 **밝게 고정** — Windows 다크 모드에서 어두운 창에 흰 바탕
    # 위젯이 섞여 흰 글씨가 묻히던 것(gui/theme.py).
    from gui.theme import apply_augur
    apply_augur(app)

    # 무거운 서드파티 임포트(scipy·matplotlib·pandas·pyqtgraph ≈ 4–5 s 콜드)를 **QApplication 직후, 스플래시보다 먼저**
    # 스레드로 시작한다. 2026-10-01 전엔 아래 가벼운 단계들이 다 끝난 뒤(5.6 s 시점)에야 시작해서
    # 그 앞 단계들과 순서대로 기다렸다(창까지 ~10 s). 스플래시 첫 그리기(~1.5 s)와도 겹치게 그보다 먼저 시작한다. 아래 단계들은 이 임포트를 필요로 하지 않는다.
    import threading, importlib
    def _prewarm():
        # pandas·pyplot·pyqtgraph·scipy.stats 도 여기서 — 빠져 있으면 아래 창 모듈
        # 임포트가 메인 스레드에서 그걸 끌어와 화면이 1.6 s 멈췄다(넣으면 0.45 s, 실측).
        for _m in ("scipy.interpolate", "scipy.optimize", "scipy.signal",
                   "scipy.ndimage", "scipy.stats", "matplotlib", "matplotlib.figure",
                   "matplotlib.pyplot", "pandas", "pyqtgraph", "core.data_io"):
            try:
                importlib.import_module(_m)
            except Exception:   # noqa: BLE001 — the real import below reports it
                pass
    _pre = threading.Thread(target=_prewarm, daemon=True)
    _pre.start()

    # ── Splash screen ────────────────────────────────────────────────────────
    # Show it FIRST, before any heavy import or window build. Every log line on it
    # is a boot step that actually finished (gui/splash.py) — no canned text.
    from gui.splash import AugurSplash, fitset_species, set_app_icon
    set_app_icon(app, "augur")
    from PyQt6.QtCore import QSettings
    # 갈래 = 마지막 FitSet 활성 채널의 레퍼런스(없으면 σ). 이름의 출처는 FitSet 하나다.
    _species = fitset_species(QSettings("CAESAR", "app").value("last_fitset", "", type=str))
    splash = AugurSplash(__version__, "Analyzer of Unseen Gases Using Resonators", n_steps=6,
                         species=_species)
    splash.show()
    splash.pump()

    splash.step("engine", f"Augur v{__version__}")

    # Scale font size relative to screen height (reference: 1080p → 9pt)
    from core.ui_metrics import ui_scale   # 가벼운 모듈 — data_io(numpy·pandas)를 끌어오지 않는다
    _s = ui_scale()
    _font = app.font()
    _font.setPointSize(max(7, round(9 * _s)))
    app.setFont(_font)

    # ── 캠페인 레이아웃 등록 ──────────────────────────────────────────────────
    # raw .dat의 컬럼 배치(채널 블록·HK 열·채널별 압력/온도 센서)는 `vigil/profiles/*.json` 이
    # 단일 출처다(2026-10-02) — raw_parser 가 import 때 읽어 등록하고, 여기서는 상태만 보인다
    # (import 뒤에 폴더에 넣은 프로파일도 이때 등록된다). 실패해도 앱은 그대로 뜬다.
    try:
        from core.raw_parser import autoload_campaign_layouts, CAMPAIGN_LAYOUTS
        _new = autoload_campaign_layouts()
        _n = sum(len(v) for v in CAMPAIGN_LAYOUTS.values())
        splash.step("layouts", f"{_n} from profiles" + (f" (+{len(_new)} new)" if _new else ""),
                    "ok" if _n else "fail")
    except Exception as _e:   # noqa: BLE001
        print(f"[main] skipped campaign layout auto-registration: {_e}")
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

    # 모션은 여기서부터. 무거운 임포트는 스플래시 직후 시작한 `_pre` 스레드가 이미 돌고 있다 —
    # 끝날 때까지 1.3 s 모션을 끊김 없이 재생하며 기다린다(창 모듈 임포트·생성은 그 뒤 메인 스레드).
    splash.restart()
    splash.wait_while(_pre.is_alive)
    splash.wait_settled()

    # ── Main window initialization ───────────────────────────────────────────
    # 창 모듈 임포트(~0.2–0.6 s)와 생성(~0.7 s)은 메인 스레드를 막는다 — 모션이 정지
    # 화면에 닿은 뒤에 한다(전에 임포트를 먼저 해서 ✓ 확정 대목이 0.6 s 끊겼다).
    from gui.app_window import CAESARAnalyzer  # The main application window class
    ex = CAESARAnalyzer()
    splash.step("interface", "ready")

    ex.showMaximized()

    # Dissolve the splash and bring the fully loaded main window to the front
    if 'splash' in locals():
        splash.finish(ex)

    # Hand control over to the Qt event loop.
    # This call blocks until the user closes the window, then returns an exit code.
    sys.exit(app.exec())
