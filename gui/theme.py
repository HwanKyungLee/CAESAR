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

import os
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
    # ── 화면 요소의 의미 역할 색(2026-10-01) — 창마다 같은 '성공 초록'이 #2E7D32·#388E3C·#4CAF50,
    # '오류 빨강'이 #C62828·#D32F2F·#B71C1C·#CC0000, '흐림 회색'이 6가지로 흩어져 있던 것을 하나로.
    # 글자색은 종이 바탕에서 읽히는 진한 톤, *_bg 는 칸·상자 배경용 옅은 톤. 그래프 데이터 색은 아래
    # SERIES/CHANNELS/SPECIES 가 따로 맡는다.
    ok: str = "#2E7D32"          # 성공·로드됨·통과
    warn: str = "#E65100"        # 주의·확인 필요
    fail: str = "#C62828"        # 오류·실패·없음(필수인데)
    info: str = "#1565C0"        # 안내·섹션 제목·링크·강조 버튼
    muted: str = "#6B6F78"       # 보조 설명·비활성 안내(= grey)
    special: str = "#6A1B9A"     # 수동 덮어쓰기·고급 설정처럼 '보통과 다른 경로' 표시
    ok_bg: str = "#E8F5E9"
    warn_bg: str = "#FFF3E0"
    fail_bg: str = "#FFEBEE"
    info_bg: str = "#E3F2FD"
    neutral_bg: str = "#ECE8DE"  # 회색 칸·눌리지 않은 토글(종이 톤)


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


# ── Augur 그래프 색 (2026-10-01) ─────────────────────────────────────────────
# 예전엔 창마다 팔레트가 달라 같은 CH1 이 모니터에선 #1f77b4(tab10), R 대화상자·결과 뷰어에선
# #2196F3(Material)였고, 농도 그래프는 기체 순서대로 색을 돌려 써서 NO₂ 가 창마다 다른 색이었다.
# 기준은 Plot Maker 의 체계(가장 다듬어졌고 validate_plotmaker 가 값을 고정) — 그 값을 여기로
# 옮겨 모든 Augur 그래프가 같이 쓴다. Plot Maker 그림의 색은 그대로다.

# 범용 순서 팔레트(이름 없는 시리즈·모르는 기체의 해시 배색) — Plot Maker _PALETTE 와 같은 값.
SERIES = ("#2196F3", "#FF6F00", "#D32F2F", "#388E3C", "#7B1FA2",
          "#0097A7", "#C2185B", "#5D4037", "#455A64", "#689F38")

# 채널 색 — CH1 파랑, CH2 주황, CH3 초록 … 어느 창에서든 같은 채널은 같은 색.
# 빨강은 뒤로 미뤘다(3채널 화면에서 한 채널만 '오류'처럼 보이지 않게).
CHANNELS = ("#2196F3", "#FF6F00", "#388E3C", "#7B1FA2", "#0097A7", "#D32F2F", "#795548")

# 기체(종) 색 — 같은 기체는 어느 창·어느 채널이든 같은 계열. 키는 소문자 종 이름.
SPECIES = {"no2": "#1976D2", "ans": "#2E7D32", "pns": "#EF6C00",
           "chocho": "#8E24AA", "glyoxal": "#8E24AA",
           "h2o": "#00838F", "o4": "#5D4037", "o3": "#C62828"}
# NO₂ 를 셀별로 따로 그릴 때의 확정색(ANs 셀 / PNs 셀).
NO2_IN_CELL = {"ans": "#1565C0", "pns": "#E65100"}


def channel_color(ch: int) -> str:
    """채널 번호(1부터) → 색. 번호가 목록보다 크면 순환."""
    return CHANNELS[(max(int(ch), 1) - 1) % len(CHANNELS)]


def species_color(name: str) -> str:
    """기체 이름 → 색. 'NO2', 'NO2 (CH1)', 'chocho' 모두 받는다(괄호 앞이 종).
    모르는 종은 이름 해시로 SERIES 에서 결정적으로 고른다(실행마다 같은 색). 이미 이름 있는 기체가
    쓰는 색은 피한다 — 안 그러면 HONO 가 O₄ 와 같은 갈색이 되는 식으로 두 기체가 한 색이 된다."""
    import zlib
    species = (name or "").lower().split("(")[0].strip()
    if species in SPECIES:
        return SPECIES[species]
    free = [c for c in SERIES if c not in SPECIES.values()] or list(SERIES)
    return free[zlib.crc32(species.encode("utf-8")) % len(free)]


_FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
_fonts_registered: list = []


def register_fonts() -> list:
    """저장소 `fonts/` 의 브랜드 서체(Spectral · IBM Plex Sans/Mono, 모두 OFL — 라이선스 파일 동봉)를
    이 프로세스에 등록한다. 설치 없이 쓰려는 것 — 다른 PC·현장 exe 에서도 같은 모양. 한 번만 돈다.
    QGuiApplication 이 있어야 한다. 등록된 서체 이름 목록을 돌려준다(없으면 빈 목록 → 시스템 서체)."""
    if _fonts_registered:
        return _fonts_registered
    from PyQt6.QtGui import QFontDatabase
    fams = set()
    try:
        names = sorted(os.listdir(_FONTS_DIR))
    except OSError:
        names = []
    for fn in names:
        if fn.lower().endswith((".ttf", ".otf")):
            fid = QFontDatabase.addApplicationFont(os.path.join(_FONTS_DIR, fn))
            if fid >= 0:
                fams.update(QFontDatabase.applicationFontFamilies(fid))
    _fonts_registered.extend(sorted(fams))
    return _fonts_registered


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
    register_fonts()
    app.setStyle("Fusion")
    _set_scheme(app, dark=False)
    app.setPalette(_palette(
        window=t.paper, window_text=t.ink, base=t.surface, alt_base="#F1EEE6", text=t.ink,
        button=t.button, button_text=t.ink, highlight=t.select, highlighted_text="#FFFFFF",
        mid=t.rule, dark="#A8A396", light="#FFFFFF", disabled_text=t.faint, link=t.select,
        tooltip_base=t.paper, tooltip_text=t.ink, placeholder=t.faint))
    app.setStyleSheet(_augur_qss(t))
    keep_windows_on_screen(app)


def _augur_qss(t) -> str:
    """App-wide widget styling (2026-10-03): sections as cards, one button language.
    Roles are a dynamic property — `set_role(button, "primary" | "danger")` — so a window marks
    *what a button does*, not its colours. Per-widget setStyleSheet still wins where it is set."""
    return f"""
QGroupBox {{ background: {t.surface}; border: 1px solid {t.rule}; border-radius: 6px;
             margin-top: 1.1em; padding: 6px 6px 6px 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {t.ink};
                    font-weight: bold; }}
QPushButton {{ background: {t.button}; border: 1px solid #CFC9BB; border-radius: 4px;
               padding: 3px 6px; min-height: 1.5em; }}
QPushButton:hover {{ background: #E1DCCF; }}
QPushButton:pressed {{ background: #D6D0C1; }}
QPushButton:disabled {{ color: {t.faint}; background: #EEEBE3; border-color: #E2DDD2; }}
QPushButton:flat {{ background: transparent; border: none; }}
QPushButton[role="primary"] {{ background: {t.select}; color: #FFFFFF; border-color: #2F519A;
                              font-weight: bold; }}
QPushButton[role="primary"]:hover {{ background: #33579F; }}
QPushButton[role="primary"]:disabled {{ background: #B9C6E2; color: #F4F6FA; border-color: #B9C6E2; }}
QPushButton[role="danger"] {{ color: {t.fail}; border-color: #E2B4B0; font-weight: bold; }}
QPushButton[role="danger"]:disabled {{ color: {t.faint}; border-color: #E2DDD2; font-weight: normal; }}
QTabBar::tab:selected {{ font-weight: bold; }}
QToolTip {{ background: {t.paper}; color: {t.ink}; border: 1px solid {t.rule}; padding: 4px; }}
"""


_fit_hooked = False


def keep_windows_on_screen(app) -> None:
    """A window (dialogs included) larger than the screen's work area is shrunk to it and centred
    when it gets focus — several dialogs open at 1100×760 or larger, taller than a 1366×768
    laptop at 150 % (512 logical px), with their buttons off-screen (UX audit 2026-10-02 s6).
    Hooked on focusWindowChanged (rare) rather than an app-wide event filter, which would run
    Python on every paint and mouse event."""
    global _fit_hooked
    if _fit_hooked:
        return
    _fit_hooked = True

    def _fit(win):
        if win is None or win.screen() is None:
            return
        area = win.screen().availableGeometry()
        m = win.frameMargins()
        w = min(win.width(), area.width() - m.left() - m.right())
        h = min(win.height(), area.height() - m.top() - m.bottom())
        if (w, h) == (win.width(), win.height()):
            return
        win.resize(max(w, 200), max(h, 150))
        win.setPosition(area.left() + (area.width() - w - m.left() - m.right()) // 2 + m.left(),
                        area.top() + (area.height() - h - m.top() - m.bottom()) // 2 + m.top())

    app.focusWindowChanged.connect(_fit)


def set_role(widget, role) -> None:
    """Mark a button's role for the app stylesheet ("primary", "danger", or None to clear)."""
    widget.setProperty("role", role or "")
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)


def apply_vigil(app) -> None:
    """Vigil: 밤·등불. QApplication 직후, 대시보드를 만들기 전에 부른다."""
    t = VIGIL
    if "IBM Plex Sans" in register_fonts():
        # 브리프: Vigil 의 서체는 IBM Plex Sans. 한글 글리프는 Plex 에 없으니 맑은 고딕으로 넘긴다.
        f = app.font()
        f.setFamilies(["IBM Plex Sans", "Malgun Gothic"])
        app.setFont(f)
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
    """로그·숫자용 고정폭 글꼴 — 브랜드 서체(IBM Plex Mono, register_fonts 로 등록)가 있으면 그것, 없으면 Consolas."""
    from PyQt6.QtGui import QFontDatabase
    fams = set(QFontDatabase.families())
    for f in ("IBM Plex Mono", "Cascadia Mono", "Consolas"):
        if f in fams:
            return f
    return "monospace"
