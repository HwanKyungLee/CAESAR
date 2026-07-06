# -*- coding: utf-8 -*-
"""Plot Maker — 패키지 진입점.

`gui.ui_plot_maker`를 그대로 쓰던 외부(app_window.py, ui_result_viewer.py의
send_to_plotmaker, tools/validate_plotmaker.py)가 하나도 안 바뀌도록, 단일
모듈이던 걸 패키지로 바꾸되 import 경로(`from gui.ui_plot_maker import ...`)와
공개 심볼은 그대로 재export한다.

내부 구성(2026-06 분할):
  data.py       Dataset(데이터 모델) + load_dataset(로더)
  processing.py 리샘플·평활·회귀·Allan 편차(공통 가공)
  core.py       ResolvedSeries + PlotMode 베이스 + 모드 레지스트리
  modes.py      TimeSeries·Scatter·Allan·Heatmap·Histogram·Diurnal 6개 모드
  widget.py     PlotMakerWidget(호스트) — 탭 UI·Export·설정 저장/불러오기
"""
from .data import Dataset, load_dataset
from .core import ResolvedSeries, PlotMode, register_mode
from .widget import PlotMakerWidget

__all__ = ["Dataset", "load_dataset", "ResolvedSeries", "PlotMode",
           "register_mode", "PlotMakerWidget"]
