"""Augur·Vigil 색 체계 — 디자인 토큰의 단일 출처 (2026-10-01).

정본은 `docs/design_brief_2026-09-30/from_design/README.md` 의 "Design Tokens". 스플래시만 그 토큰을
쓰고 나머지 창은 Fusion 기본값 + 곳곳의 하드코딩 색이라, Windows 가 다크 모드면 Augur 가 어두운 창에
흰 바탕 위젯이 섞이고(흰 글씨가 흰 바탕에 묻힘), Vigil 은 '밤' 정체성인데 흰 그래프였다.

  Augur — 낮·사무실·학자: 종이 + 잉크. 운영체제 다크 모드와 무관하게 **밝게 고정**.
  Vigil — 밤·현장·당직자: 어둠 + 청색 등불. **어둡게 고정**. 브랜드 청색은 경보색(초록·노랑·
          주황·빨강)과 겹치지 않는다 — 평상시 화면이 경보로 읽히면 안 된다(브리프 §5).

여기서 하는 것은 앱 전체 팔레트·pyqtgraph 기본값까지다. 논문 그림(matplotlib Publish)은 건드리지
않는다 — 출판물 모양은 Plot Maker 가 따로 정한다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AugurTokens:
    paper: str = "#F4F1EA"       # 배경(종이)
    ink: str = "#1A1D24"         # 기본 글자·선
    sub: str = "#4A4E57"         # 보조 글자
    grey: str = "#6B6F78"
    faint: str = "#9A9A96"       # 흐린 글자·비활성
    rule: str = "#D8D3C7"        # 구분선·트랙
    brand: str = "#B4473A"       # 주홍 — 머리글자·확정 ✓·fail
    msg: str = "#3B3F48"
    # 위젯 표면(토큰에서 파생 — 입력칸·표는 종이보다 한 단 밝게, 버튼은 한 단 어둡게)
    surface: str = "#FCFBF8"
    button: str = "#E9E5DB"
    select: str = "#3B63B5"      # 선택 강조 = 성분색 1번(청)
    components: tuple = ("#3B63B5", "#5B4FA6", "#7E4A86", "#4C6A7C", "#2F7A8C", "#6A5D9E")


@dataclass(frozen=True)
class VigilTokens:
    night: str = "#0B0F1A"       # 배경(밤)
    text: str = "#DCE1EA"
    sub: str = "#8A93A3"
    log: str = "#B4BAC6"
    dim: str = "#6E7686"
    rule: str = "#1C2333"        # 구분선·트랙
    footer: str = "#4A5264"
    lamp: str = "#7FC3F0"        # 브랜드 청색(등불)
    fail: str = "#E5484D"
    monitors: tuple = ("#7FC3F0", "#8FA8F5", "#A99BF0", "#6FD0DA", "#B7C7DA")
    # 위젯 표면(파생)
    surface: str = "#111725"     # 표·입력칸·그래프 바탕
    surface_alt: str = "#151C2C"
    button: str = "#182033"
    # 경보색 — 어두운 바탕에서 읽히는 밝기로(밝은 바탕용 #B36B00·#E65100 은 밤 바탕에서 탁하다).
    # 색만으로 구분하지 않는다: 대시보드는 모양(●▲◆■○)과 등급 글자를 같이 쓴다.
    ok: str = "#5FB98A"
    p2: str = "#E3B341"
    p1: str = "#F0883E"
    p0: str = "#E5484D"
    skip: str = "#6E7686"
    # 그래프 곡선 — 등불·감시기 계열 + 청록·회청. 노랑·주황·빨강은 **임계선 전용**이라 곡선에 안 쓴다.
    curves: tuple = ("#7FC3F0", "#A99BF0", "#6FD0DA", "#8FA8F5", "#B7C7DA",
                     "#5E9FD6", "#C3A6F5", "#4FB3BF", "#9DB4E8", "#D7DEE8")


AUGUR = AugurTokens()
VIGIL = VigilTokens()


def _palette(window, window_text, base, alt_base, text, button, button_text,
             highlight, highlighted_text, mid, dark, light, disabled_text, link, tooltip_base,
             tooltip_text, placeholder):
    from PyQt6.QtGui import QColor, QPalette
    P, G = QPalette.ColorRole, QPalette.ColorGroup
    pal = QPalette()
    for role, col in ((P.Window, window), (P.WindowText, window_text), (P.Base, base),
                      (P.AlternateBase, alt_base), (P.Text, text), (P.Button, button),
                      (P.ButtonText, button_text), (P.Highlight, highlight),
                      (P.HighlightedText, highlighted_text), (P.Mid, mid), (P.Dark, dark),
                      (P.Light, light), (P.Midlight, light), (P.Shadow, dark), (P.Link, link),
                      (P.ToolTipBase, tooltip_base), (P.ToolTipText, tooltip_text),
                      (P.PlaceholderText, placeholder), (P.BrightText, highlighted_text)):
        pal.setColor(role, QColor(col))
    for role in (P.WindowText, P.Text, P.ButtonText):
        pal.setColor(G.Disabled, role, QColor(disabled_text))
    return pal


def _set_scheme(app, dark: bool) -> None:
    """운영체제 다크/라이트 설정과 무관하게 이 앱의 색 체계를 고정(Qt 6.8+)."""
    try:
        from PyQt6.QtCore import Qt
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light)
    except (AttributeError, TypeError):
        pass


def apply_augur(app) -> None:
    """Augur: 종이·잉크. QApplication 직후, 창을 만들기 전에 부른다."""
    t = AUGUR
    app.setStyle("Fusion")
    _set_scheme(app, dark=False)
    app.setPalette(_palette(
        window=t.paper, window_text=t.ink, base=t.surface, alt_base="#F1EEE6", text=t.ink,
        button=t.button, button_text=t.ink, highlight=t.select, highlighted_text="#FFFFFF",
        mid=t.rule, dark="#A8A396", light="#FFFFFF", disabled_text=t.faint, link=t.select,
        tooltip_base=t.paper, tooltip_text=t.ink, placeholder=t.faint))


def apply_vigil(app) -> None:
    """Vigil: 밤·등불. QApplication 직후, 대시보드를 만들기 전에 부른다."""
    t = VIGIL
    app.setStyle("Fusion")
    _set_scheme(app, dark=True)
    app.setPalette(_palette(
        window=t.night, window_text=t.text, base=t.surface, alt_base=t.surface_alt, text=t.text,
        button=t.button, button_text=t.text, highlight=t.lamp, highlighted_text=t.night,
        mid=t.rule, dark="#05070D", light="#2A3347", disabled_text=t.dim, link=t.lamp,
        tooltip_base="#182033", tooltip_text=t.text, placeholder=t.dim))
    try:
        import pyqtgraph as pg
        pg.setConfigOption("background", t.surface)
        pg.setConfigOption("foreground", t.sub)
        pg.setConfigOption("antialias", True)
    except ImportError:
        pass


def mono_family() -> str:
    """로그·숫자용 고정폭 글꼴 — 브랜드 서체(IBM Plex Mono)가 설치돼 있으면 그것, 없으면 Consolas."""
    from PyQt6.QtGui import QFontDatabase
    fams = set(QFontDatabase.families())
    for f in ("IBM Plex Mono", "Cascadia Mono", "Consolas"):
        if f in fams:
            return f
    return "monospace"
