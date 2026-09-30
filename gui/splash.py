"""Augur·Vigil 부팅 스플래시 — Claude Design 핸드오프(docs/design_brief_2026-09-30/from_design)를
QPainter 로 옮긴 것. 좌표·색·타이밍은 그 README 가 정본이다.

바꾼 곳(저장소 원칙 때문):
  · Augur 값 자리는 숫자 대신 중립 표기 `··· ± ···` — ✓ 붙은 숫자는 '확정 결과'로 읽힌다.
  · Augur 입력 스펙트럼은 사인파 합성이 아니라 실제 흡수 단면(_TAU).
  · Vigil 감시기는 `ok` 가 아니라 `armed` — 부팅 순간엔 아무것도 확인하지 않았다.
  · 레퍼런스 이름은 새 상태 파일이 아니라 마지막 FitSet 의 활성 채널에서 읽는다(fitset_species).

로그 줄은 실제로 끝난 부팅 단계만 찍는다(`step`). 모션은 경과 시간으로 그리므로 메인 스레드가
막히면 멈췄다가 이어진다 — 호출부는 무거운 import 를 스레드로 돌리며 `wait_while`, 창 생성은
`wait_settled` 뒤에 한다. 클릭하면 닫힌다(QSplashScreen 기본).
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime

from PyQt6.QtCore import QElapsedTimer, QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen, QPixmap,
                         QPolygonF)
from PyQt6.QtWidgets import QApplication, QSplashScreen

# NO2(Vandaele 2002)·CHOCHO·H2O(벤치마크 hot_PNs 단면) + O4(Thalman & Volkamer 2013)의
# 차등 광학두께 합, 421.8–478.3 nm, 220점, |max|=1. 장식용 사본이라 계산에 쓰지 말 것.
_TAU = (
    -0.07, 0.05, 0.10, 0.09, 0.03, -0.06, -0.09, -0.04, 0.04, 0.17, 0.28, 0.32, 0.18, 0.01, -0.09,
    -0.20, -0.30, -0.38, -0.44, -0.41, -0.16, 0.17, 0.43, 0.64, 0.71, 0.58, 0.20, -0.14, -0.40,
    -0.63, -0.68, -0.55, -0.20, 0.16, 0.43, 0.54, 0.48, 0.32, 0.12, -0.14, -0.42, -0.52, -0.47,
    -0.25, -0.05, 0.07, 0.08, -0.03, -0.14, -0.02, 0.29, 0.51, 0.45, 0.27, 0.17, 0.19, 0.20, 0.08,
    -0.15, -0.40, -0.63, -0.71, -0.68, -0.49, -0.18, 0.20, 0.56, 0.70, 0.68, 0.58, 0.54, 0.35,
    -0.07, -0.32, -0.47, -0.54, -0.59, -0.59, -0.47, -0.11, 0.50, 0.69, 0.37, -0.24, -0.55, -0.56,
    -0.17, 0.29, 0.69, 0.85, 0.63, 0.35, 0.12, -0.09, -0.38, -0.59, -0.71, -0.62, -0.31, 0.17, 0.77,
    1.00, 0.83, 0.33, -0.05, -0.29, -0.46, -0.52, -0.46, -0.22, -0.01, 0.10, 0.06, -0.08, -0.24,
    -0.26, -0.15, 0.05, 0.22, 0.32, 0.32, 0.20, -0.06, -0.46, -0.59, -0.39, 0.14, 0.57, 0.90, 0.90,
    0.61, 0.10, -0.29, -0.59, -0.78, -0.72, -0.46, -0.03, 0.27, 0.41, 0.38, 0.25, 0.05, -0.22,
    -0.34, -0.31, -0.16, 0.00, 0.22, 0.34, 0.31, 0.15, -0.01, -0.18, -0.39, -0.49, -0.47, -0.21,
    0.17, 0.50, 0.59, 0.46, 0.24, 0.04, -0.00, 0.02, 0.00, -0.08, -0.28, -0.45, -0.53, -0.44, -0.22,
    0.06, 0.32, 0.37, 0.29, 0.18, 0.11, -0.00, -0.15, -0.18, -0.17, -0.17, -0.13, -0.01, 0.06, 0.07,
    0.00, -0.08, -0.12, -0.13, -0.11, -0.08, -0.05, -0.08, -0.18, -0.26, -0.27, -0.20, 0.01, 0.18,
    0.21, 0.10, 0.01, -0.05, -0.11, -0.16, -0.16, -0.07, 0.12, 0.38, 0.56, 0.66, 0.67, 0.61, 0.51,
    0.36, 0.22, 0.06,
)

_WL0, _WL1 = 421.75, 478.33

T_END = 1.3                           # s — 모션이 끝나는 시각(디자인 사양)
SETTLE_MS = T_END * 1000              # 이 뒤로 화면이 변하지 않는다 → 메인 스레드가 막혀도 티가 안 난다


def _cl(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def _ease(v: float) -> float:
    return 1.0 - (1.0 - _cl(v)) ** 3


def _back(v: float, c: float = 2.2) -> float:
    v = _cl(v)
    return 1 + (c + 1) * (v - 1) ** 3 + c * (v - 1) ** 2


def _g(x: float, c: float, w: float) -> float:
    return math.exp(-(((x - c) / w) ** 2))


def _tau(u: float) -> float:
    f = u * (len(_TAU) - 1)
    i = min(len(_TAU) - 2, max(0, int(f)))
    a = f - i
    return _TAU[i] * (1 - a) + _TAU[i + 1] * a


def _family(*names: str) -> str:
    """설치된 첫 서체. 디자인 서체(Spectral·IBM Plex)가 없으면 시스템 서체로 떨어진다."""
    have = set(QFontDatabase.families())
    return next((n for n in names if n in have), names[-1])


def _font(family: str, px: float, weight: int = 400, italic: bool = False,
          spacing_px: float = 0.0) -> QFont:
    f = QFont(family)
    f.setPixelSize(max(1, round(px)))
    f.setWeight(QFont.Weight(weight))
    f.setItalic(italic)
    if spacing_px:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing_px)
    return f


_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def display_species(name: str) -> str:
    """NO2 → NO₂, H2O → H₂O. 원소 기호 뒤 숫자만 아래첨자로."""
    return re.sub(r"(?<=[A-Za-z)])(\d+)", lambda m: m.group(1).translate(_SUB), name)


def fitset_species(path: str) -> list:
    """FitSet json 의 **활성 채널** 레퍼런스 이름. 없거나 깨지면 [] — 스플래시는 실패하지 않는다."""
    try:
        with open(path, encoding="utf-8") as f:
            sc = json.load(f)
        ch = sc["channels"][str(sc.get("active", sorted(sc["channels"])[0]))] if "channels" in sc else sc
        return [r["name"] for r in ch.get("refs", []) if r.get("name")]
    except Exception:            # noqa: BLE001 — 부팅 장식이 부팅을 막으면 안 된다
        return []


class BootSplash(QSplashScreen):
    """Augur·Vigil 공통 틀: 위 장면(_draw_scene) + 워드마크 행 + 진행선 + 부팅 로그 + 푸터.

    로그는 **실제로 끝난 부팅 단계만**(`step`) — 고정 문구를 두지 않는다. 진행선도 시간이
    아니라 끝난 단계 수로 찬다. 좌표는 560 × 390 절대값(디자인 핸드오프 README)."""
    W, H = 560, 390
    NAME = ""
    THEME: dict = {}

    def __init__(self, version: str, subtitle: str = "", n_steps: int = 6):
        pm = QPixmap(self.W, self.H)
        pm.fill(QColor(self.THEME["bg"]))
        super().__init__(pm, Qt.WindowType.WindowStaysOnTopHint)
        self._version = version
        self._subtitle = subtitle
        self._n_steps = max(1, n_steps)
        self._steps: list = []            # (status, label, value)
        self._clock = QElapsedTimer()
        self._clock.start()
        self._mono = _family("IBM Plex Mono", "Consolas")

    # ── 공개 API ────────────────────────────────────────────────────────
    def step(self, label: str, value: str, status: str = "ok") -> None:
        """끝난 부팅 단계 한 줄. status: ok / skip / fail."""
        self._steps.append((status, label, value))
        self.pump()

    def restart(self) -> None:
        """모션을 처음부터. 메인 스레드를 막는 가벼운 준비(설정·git·레이아웃)를 첫 장면에서 끝낸
        뒤 부른다 — 그 사이 흐른 시간만큼 모션이 건너뛰어지지 않게."""
        self._clock.restart()
        self.pump()

    def pump(self) -> None:
        self.repaint()
        QApplication.processEvents()

    def wait_while(self, busy, max_s: float = 60.0) -> None:
        """busy() 가 참인 동안 프레임을 돌린다(스레드 작업 대기용)."""
        t_end = time.monotonic() + max_s
        while busy() and self.isVisible() and time.monotonic() < t_end:
            self.pump()
            time.sleep(0.012)

    def wait_settled(self) -> None:
        """모션이 끝날 때까지(최대 SETTLE_MS) 돌린다. 이미 지났으면 즉시 반환."""
        self.wait_while(lambda: self._clock.elapsed() < SETTLE_MS, max_s=SETTLE_MS / 1000)

    # ── 공통 그리기 ─────────────────────────────────────────────────────
    def _text(self, p, x, baseline, s, font, color, anchor="left"):
        p.setFont(font)
        p.setPen(QColor(color))
        w = p.fontMetrics().horizontalAdvance(s)
        if anchor == "right":
            x -= w
        p.drawText(QPointF(x, baseline), s)
        return w

    def _acronym(self, p, x, baseline, text, font, color, strong_font, strong_color):
        """대문자로 시작하는 단어의 첫 글자만 강조(굵게·강조색). 'of'·'for' 는 그대로."""
        prev = " "
        for ch in text:
            hit = prev == " " and ch.isupper()
            x += self._text(p, x, baseline, ch, strong_font if hit else font,
                            strong_color if hit else color)
            prev = ch
        return x

    def drawContents(self, p: QPainter) -> None:            # noqa: N802 (Qt 규약)
        th = self.THEME
        t = self._clock.elapsed() / 1000.0
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 0, self.W, self.H), QColor(th["bg"]))
        self._draw_scene(p, t)

        p.setOpacity(_ease((t - 0.3) / 0.3))
        x = 30 + self._text(p, 30, 212, self.NAME, th["word_font"](), th["ink"])
        x = self._acronym(p, x + 16, 212, self._subtitle, th["sub_font"](), th["sub"],
                          th["sub_strong_font"](), th["brand"])
        self._draw_version(p, x)
        p.setOpacity(1.0)

        p.fillRect(QRectF(30, 240, 500, 1), QColor(th["track"]))
        done = min(1.0, len(self._steps) / self._n_steps)
        p.fillRect(QRectF(30, 240, 500 * done, 1), QColor(th["fill"]))
        st_font = _font(self._mono, 10.5, 500)
        msg_font = _font(self._mono, 10.5)
        for i, (st, lab, val) in enumerate(self._steps[-6:]):
            y = 252 + 10 + i * 15
            self._text(p, 30, y, st, st_font, th["log_" + st] if ("log_" + st) in th else th["log_fail"])
            self._text(p, 76, y, f"{lab} · {val}", msg_font, th["msg"])
        self._text(p, self.W - 30, self.H - 18, "ARGUS · CAESAR",
                   _font(self._mono, 9, spacing_px=1.1), th["footer"], anchor="right")

    def _draw_version(self, p, x_after_subtitle):
        raise NotImplementedError

    def _draw_scene(self, p, t):
        raise NotImplementedError


class AugurSplash(BootSplash):
    """밝은 종이 + 잉크. 실제 흡수 스펙트럼 → 육각 프리즘 → 레퍼런스 갈래 → 기체별 행.

    값 자리는 **중립 표기**(`··· ± ···`)다 — 이 프로그램에서 ✓ 붙은 숫자는 '확정 결과'라는
    뜻이라, 스플래시 캡처 한 장이 존재하지 않는 측정값이 되면 안 된다(데이터 무결성 헌장)."""
    NAME = "AUGUR"
    COLS = ("#3B63B5", "#5B4FA6", "#7E4A86", "#4C6A7C", "#2F7A8C", "#6A5D9E")

    def __init__(self, version: str, subtitle: str = "", n_steps: int = 6, species=None):
        serif = _family("Spectral", "Georgia")
        self.THEME = dict(
            bg="#F4F1EA", ink="#1A1D24", sub="#4A4E57", brand="#B4473A", track="#D8D3C7",
            fill="#1A1D24", msg="#3B3F48", footer="#9A9A96",
            log_ok="#1A1D24", log_skip="#9A9A96", log_fail="#B4473A",
            word_font=lambda: _font(serif, 30, 700, spacing_px=3.6),
            sub_font=lambda: _font(serif, 11.5, 400, italic=True),
            sub_strong_font=lambda: _font(serif, 11.5, 700))
        super().__init__(version, subtitle, n_steps)
        self._serif = serif
        self._species = [display_species(s) for s in (species or [])]

    def _draw_version(self, p, _x):
        self._text(p, self.W - 30, 26, f"v{self._version}", _font(self._mono, 10),
                   "#6B6F78", anchor="right")

    def _items(self):
        sp = self._species
        if not sp:
            return [("σ", "#9A9A96", "none")]
        if len(sp) <= 6:
            return [(n, self.COLS[i], "gas") for i, n in enumerate(sp)]
        return ([(n, self.COLS[i], "gas") for i, n in enumerate(sp[:5])]
                + [(f"+{len(sp) - 5}", "#9A9A96", "more")])

    def _draw_scene(self, p, t):
        ink = QColor("#1A1D24")
        paper = QColor("#F4F1EA")
        # 1) 입력 스펙트럼 — 실제 NO2·CHOCHO·H2O·O4 차등 흡수(_TAU), 0–0.30 s 에 왼쪽부터
        xs = [28 + 1.5 * k for k in range(67)]
        n = round(_ease(t / 0.3) * len(xs))
        if n > 1:
            path = QPainterPath(QPointF(xs[0], 105 - 9 * _tau(0)))
            for x in xs[1:n]:
                path.lineTo(QPointF(x, 105 - 9 * _tau((x - 28) / 100)))
            pen = QPen(ink, 1.6); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen); p.drawPath(path)
        # 2) 육각 프리즘(엠블럼)
        p.setOpacity(_ease((t - 0.22) / 0.15))
        outer = QPolygonF([QPointF(a, b) for a, b in ((152, 79), (174.5, 92), (174.5, 118), (152, 131), (129.5, 118), (129.5, 92))])
        inner = QPolygonF([QPointF(a, b) for a, b in ((152, 88), (166.7, 96.5), (166.7, 113.5), (152, 122), (137.3, 113.5), (137.3, 96.5))])
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(ink); p.drawPolygon(outer)
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(paper, 1.1)); p.drawPolygon(inner)
        dash = QPen(paper, 1.1); dash.setDashPattern([2.5 / 1.1, 2 / 1.1]); p.setPen(dash)
        p.drawLine(QPointF(138, 105), QPointF(138 + 28 * _ease((t - 0.32) / 0.12), 105))
        p.setOpacity(1.0)
        # 3) 갈래 + 4) 행 — 레퍼런스 개수만큼
        items = self._items()
        K = len(items)
        gap = 0 if K == 1 else min(34, 126 / (K - 1))
        y0 = 105 - gap * (K - 1) / 2
        big = K <= 4
        frame = int(t * 40)
        name_f = _font(self._serif, 13 if big else 11.5, 700)
        val_f = _font(self._mono, 19 if big else 14, 600)
        val_dim = _font(self._mono, 19 if big else 14, 400)
        small = _font(self._mono, 10)
        for i, (name, col, kind) in enumerate(items):
            yc = y0 + i * gap
            u = _ease((t - 0.42 - 0.035 * i) / 0.24)
            if u > 0:
                pen = QPen(QColor(col), 2.6 if big else 2.0); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawLine(QPointF(176, 105), QPointF(176 + 118 * u, 105 + (yc - 105) * u))
            op = _ease((t - 0.58 - 0.03 * i) / 0.1)
            if op <= 0:
                continue
            p.setOpacity(op)
            base = yc + (5 if big else 4)
            self._text(p, 302, base, name, name_f, col)
            locked = t >= 0.78 + i * min(0.12, 0.34 / max(1, K - 1))
            vx = 302 + 66 + 10 + 62                               # 값 칸 오른쪽 끝
            if kind == "more":
                self._text(p, vx + 10, base, "more", small, "#9A9A96")
            elif kind == "none":
                self._text(p, vx, base, "—", val_f if locked else val_dim,
                           "#1A1D24" if locked else "#9A9A96", anchor="right")
            else:
                dots = "···" if locked else "·" * (1 + (frame + i) % 3)
                self._text(p, vx, base, dots, val_f if locked else val_dim,
                           "#1A1D24" if locked else "#9A9A96", anchor="right")
                w = self._text(p, vx + 10, base, "± ···", small, "#6B6F78")
                if locked:
                    self._text(p, vx + 10 + w + 10, base, "✓", small, "#B4473A")
            p.setOpacity(1.0)


class VigilSplash(BootSplash):
    """어두운 밤 + 청색 등불. 맥박선 엠블럼 → 등불 점등 → 실시간 트레이스 → 감시기 다섯.

    감시기는 부팅 시점에 한 번도 돌지 않았으므로 `ok` 가 아니라 **armed**(대기)로 켠다 —
    스플래시가 확인하지 않은 것을 괜찮다고 말하면 안 된다. 브랜드 청색은 경보색(초록·노랑·
    주황·빨강)과 겹치지 않는다."""
    NAME = "VIGIL"
    EMB = ((30, 100), (70, 100), (78, 112), (86, 88), (96, 60), (106, 126), (114, 100), (150, 100))
    MON = (("ingest", "#7FC3F0"), ("HK", "#8FA8F5"), ("R", "#A99BF0"), ("lamp", "#6FD0DA"), ("conc", "#B7C7DA"))

    def __init__(self, version: str, subtitle: str = "", n_steps: int = 6):
        sans = _family("IBM Plex Sans", "Segoe UI")
        self.THEME = dict(
            bg="#0B0F1A", ink="#DCE1EA", sub="#8A93A3", brand="#7FC3F0", track="#1C2333",
            fill="#6E7686", msg="#B4BAC6", footer="#4A5264",
            log_ok="#7FC3F0", log_skip="#6E7686", log_fail="#E5484D",
            word_font=lambda: _font(sans, 28, 600, spacing_px=6.7),
            sub_font=lambda: _font(sans, 11),
            sub_strong_font=lambda: _font(sans, 11, 600))
        super().__init__(version, subtitle, n_steps)
        L = [0.0]
        for (ax, ay), (bx, by) in zip(self.EMB, self.EMB[1:]):
            L.append(L[-1] + math.hypot(bx - ax, by - ay))
        self._L = L

    def _draw_version(self, p, x):
        self._text(p, x + 16, 212, f"v{self._version}", _font(self._mono, 10), "#6E7686")

    def _draw_scene(self, p, t):
        ink = QColor("#DCE1EA")
        lamp = QColor("#7FC3F0")
        p.setPen(QPen(QColor("#161D2B"), 1)); p.drawLine(QPointF(30, 100), QPointF(530, 100))
        # 실시간 트레이스(엠블럼 뒤)
        phase = max(0.0, t - 0.3) * 90
        reach = 150 + 380 * _ease((t - 0.3) / 0.35)
        hx, hy = 150.0, 100.0
        if reach > 151:
            path = QPainterPath()
            x = 150.0
            while x <= reach:
                u = x + phase
                m = u % 64
                y = 100 + 0.6 * math.sin(u / 5.3) - 14 * _g(m, 32, 1.4) + 4 * _g(m, 36, 1.6) - 2 * _g(m, 22, 3)
                path.lineTo(QPointF(x, y)) if x > 150 else path.moveTo(QPointF(x, y))
                hx, hy = x, y
                x += 1.5
            c = QColor(ink); c.setAlphaF(0.75)
            pen = QPen(c, 1.4); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin); p.setPen(pen)
            p.drawPath(path)
        # 맥박선 엠블럼 — 0–0.32 s, 경로 길이 비율로
        L, tot = self._L, self._L[-1]
        ln = _cl(t / 0.32) * tot
        path = QPainterPath(QPointF(*self.EMB[0]))
        for i in range(1, len(self.EMB)):
            if L[i] <= ln:
                path.lineTo(QPointF(*self.EMB[i]))
            else:
                (ax, ay), (bx, by) = self.EMB[i - 1], self.EMB[i]
                f = (ln - L[i - 1]) / (L[i] - L[i - 1])
                if f > 0:
                    path.lineTo(QPointF(ax + (bx - ax) * f, ay + (by - ay) * f))
                break
        pen = QPen(ink, 3.4); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen); p.drawPath(path)
        # 등불 — R파 꼭대기에 닿는 순간 켜진다
        sL = t - 0.32 * (L[4] / tot)
        if sL >= 0:
            k = _back(sL / 0.25)
            ring = QColor(lamp); ring.setAlphaF(0.8 * (1 - _cl(sL / 0.45)))
            p.setPen(QPen(ring, 0.8)); p.setBrush(Qt.BrushStyle.NoBrush)
            r = 9 + 16 * _ease(sL / 0.45); p.drawEllipse(QPointF(96, 44), r, r)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(lamp); p.drawEllipse(QPointF(96, 44), 9 * k, 9 * k)
            p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(QColor("#0B0F1A"), 1.2))
            p.drawEllipse(QPointF(96, 44), 5 * k, 5 * k)
        if t > 0.3:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(lamp); p.drawEllipse(QPointF(hx, hy), 3, 3)
            p.setBrush(Qt.BrushStyle.NoBrush)
        # 감시기 다섯 — armed(대기). 균등 배치(space-between)
        name_f = _font(self._mono, 10.5)
        lab_f = _font(self._mono, 10.5, 600)
        widths = []
        for name, _c in self.MON:
            p.setFont(name_f); wn = p.fontMetrics().horizontalAdvance(name)
            p.setFont(lab_f); wl = p.fontMetrics().horizontalAdvance("armed")
            widths.append(9 + 8 + wn + 4 + wl)
        gap = (500 - sum(widths)) / (len(widths) - 1)
        x = 30.0
        for i, ((name, col), w) in enumerate(zip(self.MON, widths)):
            s = t - (0.62 + 0.07 * i)
            c = QColor(col); c.setAlphaF(1.0 if s >= 0 else 0.18)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(c); p.drawEllipse(QPointF(x + 4.5, 141), 4.5, 4.5)
            if s >= 0:
                pop = _cl(s / 0.35)
                rc = QColor(col); rc.setAlphaF(0.9 * (1 - pop))
                rr = (9 + 14 * _ease(pop)) / 2
                p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(rc, 1)); p.drawEllipse(QPointF(x + 4.5, 141), rr, rr)
            p.setBrush(Qt.BrushStyle.NoBrush)
            nx = x + 17 + self._text(p, x + 17, 145, name, name_f, "#B4BAC6")
            if s >= 0:
                self._text(p, nx + 4, 145, "armed", lab_f, "#6E7686")
            x += w + gap
        # LIVE 시계 — 실제 PC 시각. 모션 중 4 Hz 깜빡임, 정지 후 켜짐
        p.setOpacity(_ease((t - 0.35) / 0.2))
        clock = "LIVE " + datetime.now().strftime("%H:%M:%S")
        cf = _font(self._mono, 10)
        p.setFont(cf); cw = p.fontMetrics().horizontalAdvance(clock)
        dot = QColor(lamp); dot.setAlphaF(1.0 if t >= T_END or int(t * 4) % 2 == 0 else 0.4)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(dot)
        p.drawEllipse(QPointF(self.W - 30 - cw - 10, 22), 3, 3); p.setBrush(Qt.BrushStyle.NoBrush)
        self._text(p, self.W - 30, 26, clock, cf, "#8A93A3", anchor="right")
        p.setOpacity(1.0)
