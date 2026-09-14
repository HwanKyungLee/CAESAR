"""파일 다이얼로그 '버튼별 최근 디렉토리' 공용 헬퍼.

모든 위젯(app_window / ui_dialogs_* / ui_result_viewer)이 같은 QSettings
네임스페이스를 공유하도록 모듈 함수로 제공한다.

사용:
    from gui.dlg_dir import dlg_dir
    path, _ = QFileDialog.getOpenFileName(self, "제목", dlg_dir("i0"), filt)
    dlg_dir("i0", path)        # 선택 후 폴더 기억(빈 값이면 무시)
"""
import os
from PyQt6.QtCore import QSettings


def dlg_dir(key: str, save: str | None = None) -> str:
    """key별 마지막 디렉토리. save 없으면 시작 dir 반환, 주면 그 폴더를 기억."""
    s = QSettings("CAESAR", "app")
    if save:
        d = save if os.path.isdir(save) else os.path.dirname(save)
        if d:
            s.setValue(f"dlgdir/{key}", d)
        return d
    return s.value(f"dlgdir/{key}", "", type=str)


def campaign_of(widget, default=None) -> str:
    """부모 사슬을 따라 메인창의 `Campaign:` 값을 찾는다. 못 찾으면 'default'.

    산출물(핏·알파·R·그림)을 전부 같은 캠페인 폴더로 모으려면 다이얼로그마다 캠페인을
    알아야 하는데, 그걸 생성자 인자로 다 흘려보내면 시그니처가 지저분해지고 빼먹기 쉽다.
    Qt는 어차피 부모를 들고 있으므로 여기서 한 번만 올라간다 — **읽기 전용**.
    """
    from core.paths import DEFAULT_CAMPAIGN
    w = widget
    seen = 0
    while w is not None and seen < 12:      # 깊이 제한: 부모 사슬이 꼬여도 안 돈다
        fn = getattr(w, "_campaign", None)
        if callable(fn):
            try:
                v = str(fn() or "").strip()
                if v:
                    return v
            except Exception:               # noqa: BLE001
                pass
        w = w.parent() if hasattr(w, "parent") else None
        seen += 1
    return default or DEFAULT_CAMPAIGN
