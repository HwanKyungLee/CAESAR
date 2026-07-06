# -*- coding: utf-8 -*-
"""Plot Maker — 렌더러 공용 데이터(ResolvedSeries) + 모드 레지스트리 + PlotMode 베이스.

render()(pg 화면)/render_mpl()(mpl Publish)이 색·스타일·좌표를 각자 재계산하지
못하게 막는 구조의 핵심(ResolvedSeries + PlotMode._auto_color/_display 등 공용
헬퍼). 새 모드 추가법은 PlotMode 클래스독스트링의 체크리스트 참고.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout

# 이름 기반 자동 배색용 결정적 해시 팔레트(모르는 종은 여기서 crc32로 하나 고름).
_PALETTE = ["#2196F3", "#FF6F00", "#D32F2F", "#388E3C", "#7B1FA2",
            "#0097A7", "#C2185B", "#5D4037", "#455A64", "#689F38"]


def _shade(hex_color, factor):
    """색을 같은 계열로 밝게/어둡게. factor>0=흰색쪽(밝게), <0=검정쪽(어둡게).
    예) _shade('#2E7D32', 0.45) → 연한 초록(같은 종 평균선용). |factor|≤1."""
    try:
        h = (hex_color or "#1976D2").lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        r, g, b = 25, 118, 210
    if factor >= 0:
        r = int(r + (255 - r) * factor); g = int(g + (255 - g) * factor); b = int(b + (255 - b) * factor)
    else:
        f = 1 + factor
        r = int(r * f); g = int(g * f); b = int(b * f)
    return "#%02X%02X%02X" % (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


@dataclass
class ResolvedSeries:
    """render()(화면·pyqtgraph)와 render_mpl()(Publish·matplotlib)이 공용으로
    소비하는 '이미 결정된' 시리즈. 색·이름·스타일·좌표는 각 모드의
    `_resolve_specs()`에서 딱 한 번만 계산하고, 두 렌더러는 이 결과를
    그리기만 한다 — 화면과 Publish가 서로 다른 색/스타일을 보여줄 수 없다
    (이번 세션 "ANs가 시계열은 초록, diurnal은 주황"이었던 버그의 재발 방지)."""
    label: str
    display_name: str
    color: str
    axis: str = "L"            # "L"/"R" — 단일축 모드는 항상 "L"(무시됨)
    x: np.ndarray = None
    y: np.ndarray = None
    err_lo: np.ndarray = None  # 에러밴드/IQR 하한 (없으면 None)
    err_hi: np.ndarray = None
    width: int = 2
    dash: str = "solid"        # _DASH(pg)/_MPL_DASH(mpl) 공용 키
    marker: str = "o"          # pg 심볼 = mpl 마커(둘 다 유효한 값만 사용)
    msize: int = 3
    unit: str = None
    extra: dict = field(default_factory=dict)   # 모드별 부가정보(예: kind="median")


_MODES = []


def register_mode(cls):
    _MODES.append(cls)
    return cls


class PlotMode:
    """모드 베이스. 새 모드는 이걸 상속하고 @register_mode 붙이면 끝.

    host(PlotMakerWidget)가 제공하는 것:
      · host.shelf            : {name: Dataset}
      · host.column_choices() : ["ds:col", ...] 전체 컬럼 목록
      · host.resolve(label)   : "ds:col" → (Dataset, col, y, t)
      · host.resample_sec / host.smooth_n : 전역 가공 파라미터
      · host.pw / host.p1 / host.vb_right  : 플롯 위젯/뷰박스
      · host.set_status(text) : 하단 상태라벨
      · host.is_active_mode(self) : 지금 화면에 보이는 모드인지

    ── 7번째 모드 추가 체크리스트 ──────────────────────────────────
    1. `class MyMode(PlotMode):` + `@register_mode` — 콤보에 자동 등장.
    2. 시리즈가 여러 개면 `_resolve_specs()`를 만들어 `list[ResolvedSeries]`를
       반환(색·이름·스타일·좌표를 여기서 딱 한 번 계산). 단일 시그니처(히트맵류)면
       동등한 `_resolve_xxx()` 하나로 통일(예: HistogramMode._resolve_hist()).
       `render()`(pg)와 `render_mpl(fig)`(mpl)는 그 결과만 그린다 — 절대 각자
       재계산하지 않는다(화면·Publish drift 방지, 이게 핵심).
    3. `options_widget()`은 `self._new_options_widget()`으로 스캐폴드하고
       콤보가 있으면 `on_shelf_changed()`에서 `self._rebuild_combo(combo, choices)`
       사용(제거된 데이터셋을 가리키던 콤보를 암묵적 index-0 대신 명시적으로 비움).
    4. `to_config()`/`from_config()`는 `.get()` 기반으로 방어적으로(구버전 설정
       파일에 새 필드가 없어도 안 죽게).
    """
    key = ""
    label = ""

    def __init__(self, host):
        self.host = host
        self.colors = {}      # 사용자 색 오버라이드: element_key -> "#RRGGBB"

    def color(self, key, default):
        """요소 색(사용자 오버라이드 우선). render에서 하드코딩 대신 이걸 쓴다."""
        return self.colors.get(key) or default

    @staticmethod
    def _tspan(specs, time_key="has_time"):
        """resolved specs 목록에서 시간범위 (lo, hi) 추출(epoch초). 시간축
        시리즈가 없으면 (None, None). TimeSeriesMode의 야간음영/헤더시간축
        판정에서 반복되던 min/max 누적 로직을 한 곳으로 통합."""
        lo = hi = None
        for s in specs:
            if not s.extra.get(time_key) or s.x is None or len(s.x) == 0:
                continue
            a, b = float(np.nanmin(s.x)), float(np.nanmax(s.x))
            lo = a if lo is None else min(lo, a)
            hi = b if hi is None else max(hi, b)
        return lo, hi

    def _rebuild_combo(self, combo, choices, render_if_active=True):
        """콤보를 새 choices로 재구성하되 현재 선택을 최대한 보존. 현재 선택이
        더 이상 유효하지 않으면(예: 그 컬럼의 데이터셋이 선반에서 제거됨) 암묵적
        index-0 폴백 대신 명시적으로 '선택 없음'으로 비운다 — 사용자가 모르는
        사이 다른 컬럼이 그려지는 것 방지. render_if_active=True면 이 모드가
        현재 활성 모드일 때만 재구성 직후 렌더까지 수행."""
        cur = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(choices)
        if cur in choices:
            combo.setCurrentText(cur)
        else:
            combo.setCurrentIndex(-1)   # 명시적 "선택 없음"
        combo.blockSignals(False)
        if render_if_active and self.host.is_active_mode(self):
            self.render()

    # 종(species)→색. NO2는 어느 셀(ANs/PNs)이냐로 추가 구분. 캠페인-특정 채널
    # 매핑은 안 박음(종 색은 보편). 모든 모드 공용.
    _SPECIES_COLORS = {"ans": "#2E7D32", "pns": "#EF6C00",
                       "chocho": "#8E24AA", "glyoxal": "#8E24AA",
                       "h2o": "#00838F", "o4": "#5D4037", "o3": "#C62828"}

    def _auto_color(self, name):
        """이름 기반 결정적 색 — 같은 (종, 채널태그) 조합은 항상 같은 색.
        종(괄호 앞)으로 대표색을 잡고, NO2는 ANs/PNs 셀 태그면 확정색을 쓴다.
        **그 외 채널태그(CH1/CH2/cold/hot 등)가 붙으면 종 대표색 계열 안에서
        태그별로 다른 톤(진↔연)을 골라 구분되게 한다** — 안 그러면 같은 종을
        CH1·CH2 두 채널에서 동시에 그릴 때 완전히 같은 색으로 겹쳐 안 보임
        (2026-07-02 실제 GUI로 CH1·CH2 NO2 동시 플롯해보다 발견한 버그: 둘 다
        플레인 파랑 #1976D2라 서로 구분 불가였음). 모르는 종은 crc32 해시로
        팔레트(seed 무관·안정). 개별 색은 🎨(시리즈/요소별)로 덮어쓰면 그게 우선."""
        import zlib, re
        key = (name or "").lower()
        if ":" in key:                            # "ds:col"(diurnal 등이 넘김) → 컬럼만.
            key = key.split(":", 1)[1]            # 시계열은 깨끗한 이름이라 ":" 없음 → 동일 결과
        species = key.split("(")[0].strip()      # 종 = 괄호 앞 (예: 'no2', 'chocho')
        tag_m = re.search(r"\(([^)]*)\)", key)
        tag = tag_m.group(1).strip() if tag_m else ""

        if species == "no2" and "ans" in tag:
            return "#1565C0"                      # NO2 in ANs cell — 확정색
        if species == "no2" and "pns" in tag:
            return "#E65100"                      # NO2 in PNs cell — 확정색

        if species == "no2":
            base = "#1976D2"                      # plain NO2
        elif species in self._SPECIES_COLORS:
            base = self._SPECIES_COLORS[species]
        else:
            base = _PALETTE[zlib.crc32(species.encode("utf-8")) % len(_PALETTE)]

        if not tag:
            return base
        # 태그별로 종색 계열 안에서 다른 톤(결정적, 순서 무관) — 5단계 진↔연.
        idx = zlib.crc32(tag.encode("utf-8")) % 5
        return _shade(base, (idx - 2) * 0.18)

    def _auto_name(self, lab):
        """기본 범례 이름: 컬럼명(데이터셋 여러 개면 'NO2 (CH1)'처럼 채널 꼬리표).
        모든 모드 공용 — 시계열·diurnal이 같은 이름→같은 색을 내도록 베이스에 둠."""
        import re
        ds, _, col = lab.partition(":")
        if len(self.host.shelf) <= 1:
            return col
        m = re.search(r"(CH\d+|cold|warm|hot|ROI\d+|PNs|ANs)", ds, re.I)
        tag = m.group(1) if m else ds[:10]
        return f"{col} ({tag})"

    def _display(self, lab, name):
        return name if name else self._auto_name(lab)

    def color_keys(self):
        """색 커스텀 가능한 요소 목록 [(key, 표시명, 기본색), ...]. 없으면 []."""
        return []

    def options_widget(self) -> QWidget | None:
        """모드별 입력 UI(좌패널 하단). 없으면 None."""
        return None

    def _new_options_widget(self):
        """options_widget() 스캐폴드 — 캐시 확인 + QWidget/QVBoxLayout(margin 0) 생성을
        6개 모드가 매번 복붙하던 걸 통일. 사용법:
            def options_widget(self):
                w, lay, is_new = self._new_options_widget()
                if not is_new:
                    return w
                ... lay에 위젯 추가 ...
                return w
        반환 (widget, layout|None, is_new). is_new=False면 layout은 None(위젯 이미 있음 — 그대로 반환)."""
        if self._w is not None:
            return self._w, None, False
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self._w = w
        return w, lay, True

    def on_shelf_changed(self):
        """선반(데이터셋 목록)이 바뀌면 호출 — 콤보 재구성 등."""

    def on_column_activated(self, label):
        """Data 탭에서 컬럼을 더블클릭했을 때 — 그 컬럼을 이 모드로 플롯.
        기본: 단일컬럼 모드의 주 콤보(_c) 또는 산점도 Y(_cy)에 반영(→ 렌더)."""
        combo = getattr(self, "_c", None) or getattr(self, "_cy", None)
        if combo is not None:
            if combo.currentText() == label:
                self.render()              # 이미 선택된 컬럼이면 신호 안 뜨니 직접 렌더
            else:
                combo.setCurrentText(label)
            return True
        return False

    def to_config(self) -> dict:
        return {}

    def from_config(self, cfg: dict):
        pass

    def render(self):
        raise NotImplementedError

    def render_mpl(self, fig):
        """출판용 matplotlib 렌더(고화질 PNG/PDF/SVG). 미지원 모드는 NotImplementedError."""
        raise NotImplementedError

    def csv_table(self):
        """CSV 내보내기용 (headers, rows) 반환. 지원 안 하면 None."""
        return None
