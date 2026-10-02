"""화면 크기에 따른 UI 배율 — 무거운 임포트가 없는 작은 모듈(2026-10-01).

원래 `core/data_io.py` 에 있었는데, main.py 가 부팅 첫 단계에서 이 함수 하나를 쓰려고 data_io 를
불러오면서 numpy·pandas 등(웜 1.2 s)이 스플래시 직후 메인 스레드에 올라왔다. 정의는 여기 하나이고
data_io 는 기존 임포트 경로(`from core.data_io import ui_scale`)를 위해 다시 내보낸다.
"""


def ui_scale() -> float:
    """Return a UI scale factor relative to 1080p reference height.
    Clamps between 1.0 and 1.25. Never below 1: the factor scales fixed widget widths but
    not the font, so on a short screen (1366×768 at 150 % → 512 logical px) 0.75 clipped
    spin boxes and buttons ("435.", "+" blank — UX audit 2026-10-02 / 2026-10-03)."""
    try:
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen is None:
            return 1.0
        h = screen.availableGeometry().height()
        return max(1.0, min(1.25, h / 1080.0))
    except Exception:
        return 1.0
