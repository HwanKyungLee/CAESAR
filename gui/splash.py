"""Augur 부팅 스플래시 — 새가 램프 스펙트럼을 긋고, 흡수가 새겨지고, 핏이 수렴한다.

로그 줄은 **실제로 끝난 부팅 단계만** 찍는다(`step`). 고정 문구를 두지 않는다 —
사용자·세팅마다 값이 다르고, 틀린 정보를 띄우는 스플래시는 장식보다 나쁘다.

애니메이션은 경과 시간으로 그리므로, 메인 스레드가 막힌 동안엔 멈췄다가 이어진다.
그래서 `main.py` 는 무거운 import 를 스레드로 돌리며 `wait_while` 로 프레임을 펌프하고,
메인 스레드가 막히는 창 생성은 `wait_settled` 로 애니메이션이 끝난 뒤에 한다.
클릭하면 닫힌다(QSplashScreen 기본) — 대기 루프도 그 즉시 빠져나온다.
"""
from __future__ import annotations

import math
import random
import time

from PyQt6.QtCore import QElapsedTimer, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
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

_BG = QColor("#10131a")
_GOLD = QColor("#d9a441")
_IVORY = QColor("#f2ecdf")
_MUTED = QColor("#8d93a0")
_TRACK = QColor("#232834")

SPEED = 2.0               # 타임라인 배속. 2.0 → 1.3 s 에 끝나 import(≈1.2 s)와 겹친다 — 부팅을 늘리지 않는다
SETTLE_MS = 2600 / SPEED  # 이 시각 이후 화면이 더 변하지 않는다 → 막혀도 티가 안 난다


def _ease(q: float) -> float:
    q = min(1.0, max(0.0, q))
    return 1.0 - (1.0 - q) ** 3


def _tau(u: float) -> float:
    f = u * (len(_TAU) - 1)
    i = min(len(_TAU) - 2, max(0, int(f)))
    a = f - i
    return _TAU[i] * (1 - a) + _TAU[i + 1] * a


def _hump(u: float) -> float:
    return math.exp(-((u - 0.5) / 0.36) ** 2)


class BootSplash(QSplashScreen):
    """Augur·Vigil 공통 틀: 장면(_draw_scene) + 워드마크·약어 + 부팅 로그. 장면만 서브클래스가 그린다."""
    NAME = ""
    W, H = 560, 390

    def __init__(self, version: str, subtitle: str = "", n_steps: int = 6):
        pm = QPixmap(self.W, self.H)
        pm.fill(_BG)
        super().__init__(pm, Qt.WindowType.WindowStaysOnTopHint)
        self._version = version
        self._n_steps = max(1, n_steps)
        self._subtitle = subtitle
        self._steps: list[tuple[str, str, str]] = []   # (status, label, value)
        self._clock = QElapsedTimer()
        self._clock.start()

    # ── 공개 API ────────────────────────────────────────────────────────
    def step(self, label: str, value: str, status: str = "ok") -> None:
        """끝난 부팅 단계 한 줄. status: ok / skip / fail."""
        self._steps.append((status, label, value))
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
        """애니메이션이 끝날 때까지(최대 SETTLE_MS) 돌린다. 이미 지났으면 즉시 반환."""
        self.wait_while(lambda: self._clock.elapsed() < SETTLE_MS, max_s=SETTLE_MS / 1000)

    # ── 그리기 ──────────────────────────────────────────────────────────
    def _draw_acronym(self, p: QPainter, text: str, y: float) -> None:
        """가운데 정렬로 그리되 대문자로 시작하는 단어의 첫 글자만 금색("of" 같은 소문자 단어는 제외)."""
        fm = p.fontMetrics()
        x = (self.W - fm.horizontalAdvance(text)) / 2
        base = y + fm.ascent()
        prev = " "
        for ch in text:
            p.setPen(_GOLD if (prev == " " and ch.isupper()) else _MUTED)
            p.drawText(QPointF(x, base), ch)
            x += fm.horizontalAdvance(ch)
            prev = ch


    def drawContents(self, p: QPainter) -> None:            # noqa: N802 (Qt 규약)
        t = float(self._clock.elapsed()) * SPEED
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, 0, self.W, self.H), _BG)
        M, TOP, RH = 28.0, 170.0, 30.0
        small = QFont(self.font()); small.setPointSizeF(8)
        self._draw_scene(p, t, small)

        Wq = _ease((t - 2000) / 600)                               # 워드마크
        if Wq > 0:
            p.setOpacity(Wq)
            big = QFont("Georgia"); big.setPointSizeF(24); big.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 114)
            p.setFont(big); p.setPen(_IVORY)
            p.drawText(QRectF(0, TOP + RH + 10, self.W, 40), Qt.AlignmentFlag.AlignCenter, self.NAME)
            if self._subtitle:
                p.setFont(small)
                self._draw_acronym(p, self._subtitle, TOP + RH + 50)
            p.setOpacity(1.0)

        # 로그: 실제로 끝난 단계만. 진행바 = 끝난 단계 / 예정 단계 수(n_steps).
        ly = TOP + RH + 76
        p.fillRect(QRectF(M, ly, self.W - 2 * M, 2), _TRACK)
        mono = QFont("Consolas"); mono.setPointSizeF(8.5)
        p.setFont(mono)
        shown = self._steps[-6:]
        for i, (st, lab, val) in enumerate(shown):
            y = ly + 10 + i * 16
            p.setPen({"ok": _GOLD, "skip": _MUTED}.get(st, QColor("#e0795b")))
            p.drawText(QRectF(M, y, 40, 16), Qt.AlignmentFlag.AlignLeft, st)
            p.setPen(_MUTED)
            p.drawText(QRectF(M + 40, y, self.W - 2 * M - 40, 16), Qt.AlignmentFlag.AlignLeft,
                       f"{lab} · {val}")
        if self._steps:
            done = min(1.0, len(self._steps) / self._n_steps)
            p.fillRect(QRectF(M, ly, (self.W - 2 * M) * done, 2), _GOLD)

        p.setFont(small); p.setPen(_MUTED)
        p.drawText(QRectF(0, 10, self.W - 14, 14), Qt.AlignmentFlag.AlignRight,
                   f"v{self._version}")


class AugurSplash(BootSplash):
    """새가 램프 스펙트럼을 긋고, 네 기체의 흡수가 새겨지고, 핏이 수렴하고, 잔차가 잦아든다."""
    NAME = "Augur"

    def _draw_scene(self, p: QPainter, t: float, small: QFont) -> None:
        M, TOP, RH = 28.0, 170.0, 30.0
        px = lambda u: M + u * (self.W - 2 * M)                   # noqa: E731
        py = lambda v: TOP - 26 - v * (TOP - 56)                  # noqa: E731

        ub = _ease(t / 1150) * 1.1
        um = min(ub, 1.0)
        D = _ease((t - 950) / 650)                                 # 흡수 새김
        Z = max(0.0, 1 - _ease((t - 2100) / 500)) * D              # 광자 잡음
        F = _ease((t - 1700) / 600)                                # 핏 선
        s = lambda u, d=D: _hump(u) * (1 - 0.2 * d * _tau(u))     # noqa: E731

        def curve(f, upto, n=360):
            path = QPainterPath()
            for i in range(n + 1):
                u = i / n * upto
                pt = QPointF(px(u), f(u))
                path.lineTo(pt) if i else path.moveTo(pt)
            return path

        p.setPen(QPen(_GOLD, 1.4))
        p.drawPath(curve(lambda u: py(s(u) + (random.random() - .5) * .035 * Z * _hump(u)), um))
        if F > 0:
            c = QColor(_IVORY); c.setAlphaF(0.85)
            p.setPen(QPen(c, 1.0))
            p.drawPath(curve(lambda u: py(s(u, 1.0)), F))

        p.setFont(small)
        if D > 0:
            c = QColor(_MUTED); c.setAlphaF(D)
            p.setPen(c)
            for wl, lab in ((430, "430"), (450, "450 nm"), (470, "470")):
                x = px((wl - _WL0) / (_WL1 - _WL0))
                p.drawLine(QPointF(x, TOP - 22), QPointF(x, TOP - 18))
                p.drawText(QRectF(x - 40, TOP - 18, 80, 14), Qt.AlignmentFlag.AlignCenter, lab)

        Rq = _ease((t - 1700) / 400)                               # 잔차
        if Rq > 0:
            y0 = TOP + RH / 2
            amp = RH * .45 * (.15 + .85 * max(0.0, 1 - _ease((t - 2000) / 500)))
            c = QColor(_MUTED); c.setAlphaF(0.9 * Rq)
            p.setPen(QPen(c, 0.8))
            p.drawPath(curve(lambda u: y0 + (random.random() - .5) * 2 * amp * _hump(u), 1.0, 240))
            p.drawText(QRectF(M, TOP, 120, 14), Qt.AlignmentFlag.AlignLeft, "residual")

        if ub < 1.1:                                               # 새
            bx, by, fl = px(ub), py(s(um)) - 16, math.sin(t / 65)
            path = QPainterPath(QPointF(bx - 9, by - 2 - 4 * fl))
            path.quadTo(QPointF(bx - 4, by - 1), QPointF(bx, by + 2))
            path.quadTo(QPointF(bx + 4, by - 1), QPointF(bx + 9, by - 2 - 4 * fl))
            c = QColor(_IVORY); c.setAlphaF(max(0.0, min(1.0, 1 - (ub - .95) * 7)))
            p.setPen(QPen(c, 1.5))
            p.drawPath(path)


def _ecg(u: float) -> float:
    """심전도 한 박(P·QRS·T) — raw 유입 = 계기의 맥박."""
    f = (u * 5.0) % 1.0
    return (0.18 * math.exp(-((f - 0.18) / 0.03) ** 2) - 0.25 * math.exp(-((f - 0.38) / 0.012) ** 2)
            + 1.0 * math.exp(-((f - 0.42) / 0.012) ** 2) - 0.35 * math.exp(-((f - 0.46) / 0.012) ** 2)
            + 0.30 * math.exp(-((f - 0.68) / 0.05) ** 2))


class VigilSplash(BootSplash):
    """환자 모니터: 감시기 다섯(유입·HK·R·램프·농도)의 선을 커서가 쓸고 지나가며 긋고,
    끝의 상태 점이 차례로 켜진다. 선 모양은 각 감시기가 실제로 보는 신호의 성격을 흉내낸다."""
    NAME = "Vigil"
    _LANES = ("ingest", "HK", "R", "lamp", "conc")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        rnd = random.Random(7)                      # 고정 시드 — 프레임마다 선이 떨리지 않게
        walk, acc = [], 0.0
        for _ in range(241):
            acc = 0.85 * acc + rnd.gauss(0, 0.35)
            walk.append(acc)
        self._noise = [rnd.gauss(0, 1) for _ in range(241)]
        self._walk = walk

    def _signal(self, k: int, u: float) -> float:
        i = min(240, int(u * 240))
        if k == 0:
            return _ecg(u)
        if k == 1:
            return 0.45 * math.sin(2 * math.pi * (u * 1.3 + 0.1)) + 0.04 * self._noise[i]
        if k == 2:
            return -0.15 * u + 0.05 * self._noise[i]
        if k == 3:
            return 0.55 if ((u * 4.0) % 1.0) < 0.12 else -0.05 + 0.03 * self._noise[i]
        return 0.30 * self._walk[i]

    def _draw_scene(self, p: QPainter, t: float, small: QFont) -> None:
        M, TOP = 28.0, 170.0
        x0, x1 = M + 52, self.W - M - 18
        cur = _ease(t / 1500)                                   # 스윕 커서
        p.setFont(small)
        for k, name in enumerate(self._LANES):
            yc = 40 + k * 26
            p.setPen(_MUTED)
            p.drawText(QRectF(M, yc - 7, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
            track = QColor(_TRACK)
            p.setPen(QPen(track, 0.6))
            p.drawLine(QPointF(x0, yc), QPointF(x1, yc))
            if cur > 0:
                path = QPainterPath()
                n = max(2, int(300 * cur))
                for i in range(n + 1):
                    u = i / 300
                    pt = QPointF(x0 + u * (x1 - x0), yc - 10 * self._signal(k, u))
                    path.lineTo(pt) if i else path.moveTo(pt)
                p.setPen(QPen(_GOLD, 1.2))
                p.drawPath(path)
            on = _ease((t - 1450 - 110 * k) / 180)              # 점검 통과 → 점 점등
            dot = QColor(_GOLD if on > 0 else _TRACK)
            if on > 0:
                dot.setAlphaF(on)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(dot)
            p.drawEllipse(QPointF(x1 + 10, yc), 3.2, 3.2)
            p.setBrush(Qt.BrushStyle.NoBrush)
        if 0 < cur < 1:
            c = QColor(_IVORY); c.setAlphaF(0.5)
            p.setPen(QPen(c, 1.0))
            xc = x0 + cur * (x1 - x0)
            p.drawLine(QPointF(xc, 26), QPointF(xc, 40 + 4 * 26 + 14))

