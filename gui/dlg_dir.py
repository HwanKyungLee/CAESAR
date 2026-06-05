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
