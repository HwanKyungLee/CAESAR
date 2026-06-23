"""gui/ui_dialogs_ref.py
레퍼런스 관리 클래스는 개별 파일로 분리됨. 여기서 재노출(import * 무회귀).
  MaskDialog→ref_mask_dialog, RefPropertiesDialog→ref_properties_dialog,
  ReferenceGeneratorDialog→reference_generator_dialog, MonitorWidget→monitor_widget
"""
from gui.ref_mask_dialog import MaskDialog
from gui.ref_properties_dialog import RefPropertiesDialog
from gui.reference_generator_dialog import ReferenceGeneratorDialog
from gui.monitor_widget import MonitorWidget

__all__ = ['MaskDialog', 'RefPropertiesDialog', 'ReferenceGeneratorDialog', 'MonitorWidget']
