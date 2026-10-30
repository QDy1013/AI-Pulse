"""App icon: a luminous signal line on a graphite tile, drawn crisply at any size."""
from __future__ import annotations

import math
import struct

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
# Echo lines behind the main signal: (amplitude, phase, width, peak alpha), on a 128 unit grid.
ECHOES = ((11.0, 1.6, 0.8, 70), (15.5, 0.9, 1.05, 90), (22.0, 0.3, 1.25, 120))


def squircle(size, inset=0.06, n=5.0):
    """Superellipse tile: the continuous corner modern app icons use."""
    c, r = size / 2, size / 2 * (1 - 2 * inset)
    path = QPainterPath()
    for i in range(361):
        t = math.radians(i)
        ct, st = math.cos(t), math.sin(t)
        point = QPointF(c + r * math.copysign(abs(ct) ** (2 / n), ct), c + r * math.copysign(abs(st) ** (2 / n), st))
        path.moveTo(point) if i == 0 else path.lineTo(point)
    path.closeSubpath()
    return path


def wave(amp, phase, width=92.0, steps=120):
    """A heartbeat-like trace: calm at both ends, one strong swing in the middle."""
    path = QPainterPath()
    for i in range(steps + 1):
        u = i / steps
        envelope = math.exp(-((u - 0.5) / 0.22) ** 2)
        point = QPointF(64 - width / 2 + width * u, 64 - amp * envelope * math.sin(2 * math.pi * 2.2 * u + phase))
        path.moveTo(point) if i == 0 else path.lineTo(point)
    return path


def paint(p, size, bleed=False):
    """Draw the icon into a size x size area. bleed fills the square edge to edge, for home
    screens that apply their own mask (iOS, Android adaptive icons)."""
    s = size / 128
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(s, s)  # Everything below is on the 128 unit grid.
    if bleed:
        tile = QPainterPath()
        tile.addRect(QRectF(0, 0, 128, 128))
    else:
        tile = squircle(128)
    base = QLinearGradient(0, 0, 0, 128)
    base.setColorAt(0, QColor('#30333b'))
    base.setColorAt(1, QColor('#101216'))
    p.fillPath(tile, base)
    glow = QRadialGradient(QPointF(64, 64), 56)
    glow.setColorAt(0, QColor(140, 150, 255, 46))
    glow.setColorAt(1, QColor(140, 150, 255, 0))
    p.fillPath(tile, glow)

    p.setClipPath(tile)
    if bleed:
        # Keep the line inside the safe zone that home-screen masks never cut.
        p.translate(64, 64)
        p.scale(0.84, 0.84)
        p.translate(-64, -64)
    if size >= 48:  # The echoes are detail; at small sizes they only blur the line.
        for amp, phase, width, alpha in ECHOES:
            echo = QLinearGradient(20, 0, 108, 0)
            echo.setColorAt(0, QColor(143, 163, 255, 0))
            echo.setColorAt(0.5, QColor(170, 180, 255, alpha))
            echo.setColorAt(1, QColor(241, 195, 142, 0))
            p.setPen(QPen(echo, width))
            p.drawPath(wave(amp, phase, 96))
    main = QLinearGradient(18, 0, 110, 0)
    main.setColorAt(0, QColor('#8fa3ff'))
    main.setColorAt(0.5, QColor('#ffffff'))
    main.setColorAt(1, QColor('#f1c38e'))
    # At least ~1.7 device pixels so the line survives at 16 px.
    width = max(5.2, 1.7 / s) if size >= 32 else max(7.5, 1.6 / s)
    p.setPen(QPen(main, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(wave(26, 0.0))
    p.setClipping(False)

    if not bleed and size >= 32:
        # A light edge along the top, as if the tile caught a soft overhead light.
        rim = QLinearGradient(0, 0, 0, 128)
        rim.setColorAt(0, QColor(255, 255, 255, 70))
        rim.setColorAt(0.3, QColor(255, 255, 255, 0))
        p.setPen(QPen(rim, max(1.6, 1 / s)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(tile)
    p.restore()


def image(size, bleed=False):
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    paint(p, size, bleed)
    p.end()
    return img


def png(size, bleed=False):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image(size, bleed).save(buffer, 'PNG')
    buffer.close()
    return bytes(data)


def svg():
    """The same mark as a small SVG, for the phone page's favicon."""
    def points(amp, phase, width=92.0, steps=60):
        out = []
        for i in range(steps + 1):
            u = i / steps
            envelope = math.exp(-((u - 0.5) / 0.22) ** 2)
            out.append(f'{64 - width / 2 + width * u:.1f},{64 - amp * envelope * math.sin(2 * math.pi * 2.2 * u + phase):.1f}')
        return ' '.join(out)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
            '<defs><linearGradient id="b" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="#30333b"/><stop offset="1" stop-color="#101216"/></linearGradient>'
            '<linearGradient id="l" x1="18" y1="0" x2="110" y2="0" gradientUnits="userSpaceOnUse">'
            '<stop offset="0" stop-color="#8fa3ff"/><stop offset=".5" stop-color="#fff"/>'
            '<stop offset="1" stop-color="#f1c38e"/></linearGradient></defs>'
            '<rect x="7.7" y="7.7" width="112.6" height="112.6" rx="30" fill="url(#b)"/>'
            f'<polyline points="{points(26, 0.0)}" fill="none" stroke="url(#l)" stroke-width="7" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def ico(sizes=ICO_SIZES):
    """A Windows .ico holding one PNG-compressed image per size (Vista and later)."""
    images = [(size, png(size)) for size in sizes]
    offset = 6 + 16 * len(images)
    entries, blobs = b'', b''
    for size, blob in images:
        # Width and height 0 mean 256.
        entries += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(blob), offset + len(blobs))
        blobs += blob
    return struct.pack('<HHH', 0, 1, len(images)) + entries + blobs
