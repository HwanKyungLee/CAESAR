"""
gui/ui_dialogs.py — 하위 호환 re-export wrapper
===============================================
실제 구현은 아래 세 서브모듈에 분산되어 있다:

  ui_dialogs_calib.py  — NavigationHelper, WavelengthCalibrationDialog, RangeSelectorDialog
  ui_dialogs_ref.py    — MaskDialog, RefPropertiesDialog, ReferenceGeneratorDialog, MonitorWidget
  ui_dialogs_r.py      — _RTrendWorker, RCalibratorDialog
                         (RTrendMonitorDialog = RCalibratorDialog 별칭 포함)

기존 코드가 'from .ui_dialogs import *' 또는 'from gui.ui_dialogs import ...' 형태로
임포트하는 경우, 이 파일을 통해 모두 접근 가능.
"""
from .ui_dialogs_calib import *   # NavigationHelper, WavelengthCalibrationDialog, RangeSelectorDialog
from .ui_dialogs_ref   import *   # MaskDialog, RefPropertiesDialog, ReferenceGeneratorDialog, MonitorWidget
from .ui_dialogs_r     import *   # RCalibratorDialog, RTrendMonitorDialog(alias)
from .ui_dialogs_r     import _RTrendWorker, _ChannelRWorker  # private classes
