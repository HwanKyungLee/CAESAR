"""Augur·Vigil 앱 아이콘(.ico) 생성 — Claude Design 엠블럼(docs/design_brief_2026-09-30/from_design)
을 스플래시와 같은 배경 타일 위에 그린다.

엠블럼 원본은 투명 배경의 검은 선이라 어두운 바탕화면에서 안 보인다 → Augur 는 종이 타일에 잉크,
Vigil 은 밤 타일에 밝은 선 + 청색 등불. 32 px 이하는 핸드오프 README 대로 단순화한다
(Augur 갈래 4 → 2, Vigil 맥박선 → 삼각 봉우리 하나).

    python tools/make_icons.py      → icons/augur.ico, icons/vigil.ico (+ 미리보기 png)
"""
import io
import os
import sys

from PyQt6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "icons")
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _tile(p, n, bg):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(bg))
    p.drawRoundedRect(QRectF(0, 0, n, n), n * 0.2, n * 0.2)


def _to_emblem(p, n, box=(-34, -25, 68, 50), fill=0.84):
    """엠블럼 viewBox 좌표계를 타일 가운데로."""
    x, y, w, h = box
    s = n * fill / w
    p.translate(n / 2, n / 2)
    p.scale(s, s)
    p.translate(-(x + w / 2), -(y + h / 2))


def _pen(color, w):
    pen = QPen(QColor(color), w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def draw_augur(p, n):
    ink, paper = "#1A1D24", "#F4F1EA"
    _tile(p, n, paper)
    small = n <= 32
    _to_emblem(p, n)
    p.setPen(_pen(ink, 3.4 if not small else 4.6))
    p.drawLine(QPointF(-33, 0), QPointF(-14, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(ink))
    p.drawPolygon(QPolygonF([QPointF(a, b) for a, b in
                             ((0, -18), (15.6, -9), (15.6, 9), (0, 18), (-15.6, 9), (-15.6, -9))]))
    if n >= 48:                                  # 안쪽 육각 + 점선은 작으면 뭉개진다
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(paper), 1.0))
        p.drawPolygon(QPolygonF([QPointF(a, b) for a, b in
                                 ((0, -12), (10.4, -6), (10.4, 6), (0, 12), (-10.4, 6), (-10.4, -6))]))
        dash = QPen(QColor(paper), 1.0)
        dash.setDashPattern([2, 1.5])
        p.setPen(dash)
        p.drawLine(QPointF(-10, 0), QPointF(10, 0))
    p.setPen(_pen(ink, 2.8 if not small else 4.2))
    for yy in ((-14, 14) if small else (-14, -4.7, 4.7, 14)):
        p.drawLine(QPointF(14, 0), QPointF(33, yy))


def draw_vigil(p, n):
    night, line, lamp = "#0B0F1A", "#DCE1EA", "#7FC3F0"
    _tile(p, n, night)
    small = n <= 32
    _to_emblem(p, n)
    path = QPainterPath()
    pts = (((-32, 12), (-8, 12), (0, -3), (8, 12), (32, 12)) if small else
           ((-32, 12), (-14, 12), (-10, 18), (-5, 6), (0, -3), (5, 22), (9, 12), (32, 12)))
    path.moveTo(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(QPointF(*pt))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(line, 3.4 if not small else 4.8))
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(lamp))
    p.drawEllipse(QPointF(0, -14), 8 if not small else 9, 8 if not small else 9)
    if n >= 48:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(night), 1.0))
        p.drawEllipse(QPointF(0, -14), 4.6, 4.6)


def render(draw, n) -> Image.Image:
    img = QImage(n, n, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(p, n)
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def main():
    QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    os.makedirs(OUT, exist_ok=True)
    for name, draw in (("augur", draw_augur), ("vigil", draw_vigil)):
        imgs = [render(draw, n) for n in SIZES]
        path = os.path.join(OUT, f"{name}.ico")
        imgs[-1].save(path, format="ICO", sizes=[(n, n) for n in SIZES], append_images=imgs[:-1])
        imgs[-1].save(os.path.join(OUT, f"{name}_256.png"))
        # 크기별 한 줄 미리보기(작은 크기 단순화 확인용)
        strip = Image.new("RGBA", (sum(SIZES) + 8 * len(SIZES), 256), (128, 128, 128, 255))
        x = 0
        for im in imgs:
            strip.paste(im, (x, 256 - im.height), im)
            x += im.width + 8
        strip.save(os.path.join(OUT, f"{name}_sizes.png"))
        with Image.open(path) as ico:
            got = sorted(ico.info.get("sizes", []))
        print(f"{name}.ico sizes={got}")
        assert got == sorted((n, n) for n in SIZES), got


if __name__ == "__main__":
    main()
