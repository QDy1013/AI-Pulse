"""Qt desktop interface: device-independent layout and vector rendering."""
from __future__ import annotations

import csv
import ctypes
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QThread, Signal, QPoint, QPointF, QRectF, QSize, QSizeF
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen,
    QLinearGradient, QRadialGradient, QIcon, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QLineEdit,
    QVBoxLayout, QHBoxLayout, QScrollArea, QButtonGroup, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
    QDialog, QTabWidget, QTextEdit, QComboBox, QDialogButtonBox, QToolTip, QSizePolicy, QCheckBox,
    QSystemTrayIcon, QMenu,
)

from . import autostart, icon, insights
from .collector import APPS, Collector, defaults
from .pricing import (
    DEFAULT_USD_TO_CNY, estimate_usd, format_cny, format_custom_rates, format_usd, parse_custom_rates,
)
from .remote import RemoteService, find_cloudflared, new_token

# Paper and ink: white glass panels on a warm off-white page ruled with fine lines.
# The accent is ink itself; amber is reserved for money, red and orange for limits.
BG, SIDEBAR, PANEL, RAISED = '#f3f3f0', '#f9f9f7', '#ffffff', '#ffffff'
# Grid and track are ink at low alpha (#AARRGGBB) so they sit evenly on paper and glass.
BORDER, LINE, GRID, TRACK = '#e3e3de', '#cfd0cb', '#1411141c', '#1711141c'
TEXT, SECONDARY, MUTED = '#16181d', '#4a4f58', '#737882'
ACCENT, GOLD, WARN, DANGER = '#1d2026', '#a26f16', '#c47a06', '#cf3f37'
INK = (17, 20, 28)
# Type: CJK sans for reading, a serif for titles, DIN-style figures for numbers.
# configure_fonts() falls back when a family is not installed.
SANS, SERIF, NUM, LATIN = 'Microsoft YaHei UI', 'Noto Serif SC', 'Bahnschrift', 'Segoe UI Variable Text'
# App hues are a validated categorical set (adjacent-pair CVD ΔE ≥ 8 and ≥ 3:1 contrast on
# white) in this fixed order; models and projects reuse the same order, never cycled.
COLORS = {
    'Codex': '#199e70',
    'Claude': '#d95926',
    'Reasonix': '#9085e9',
    'Antigravity': '#d55181',
    'WorkBuddy': '#3987e5',
}
OTHER = '#9a9ea6'
DISPLAY = {
    'Codex': 'Codex',
    'Claude': 'Claude Code',
    'Reasonix': 'Reasonix',
    'Antigravity': '反重力',
    'WorkBuddy': 'WorkBuddy',
}
MODEL_PALETTE = tuple(COLORS.values())


def series_color(i):
    return MODEL_PALETTE[i] if i < len(MODEL_PALETTE) else OTHER

ALL = '全部软件'
PERIODS = ('今天', '近 7 天', '全部记录')
TABLE_LIMIT = 100

def ink_css(alpha):
    return f'rgba({INK[0]}, {INK[1]}, {INK[2]}, {alpha})'


def stylesheet():
    # Built after configure_fonts() so the families fall back to what is installed.
    return f'''
QWidget {{ color: {TEXT}; font-family: "{SANS}"; font-size: 13px; }}
QMainWindow, QDialog, QWidget#root, QWidget#viewport {{ background: {BG}; }}
QLabel {{ background: transparent; border: none; }}
QFrame#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QLabel#muted {{ color: {MUTED}; font-size: 12px; }}
QLabel#eyebrow {{ color: {MUTED}; font-family: "{LATIN}"; font-size: 10px; font-weight: 600; letter-spacing: 3px; }}
QLabel#heading {{ font-family: "{SERIF}"; font-size: 28px; font-weight: 600; color: {TEXT}; letter-spacing: 1.5px; }}
QLabel#section {{ font-family: "{SERIF}"; font-size: 15px; font-weight: 600; color: {TEXT}; letter-spacing: 0.6px; }}
QLabel#figure {{ font-family: "{NUM}"; font-size: 17px; font-weight: 400; color: {TEXT}; }}
QLabel#unit {{ color: {MUTED}; background: transparent; border: 1px solid {ink_css(0.12)}; border-radius: 7px; padding: 1px 7px; font-family: "{LATIN}"; font-size: 10px; font-weight: 600; letter-spacing: 0.6px; }}
QLabel#unit[primary="true"] {{ color: {PANEL}; background: {ACCENT}; border-color: {ACCENT}; }}
QLabel#unit[quota="true"] {{ color: {GOLD}; background: rgba(162, 111, 22, 0.07); border-color: rgba(162, 111, 22, 0.30); }}
QLabel#number {{ font-family: "{NUM}"; font-size: 34px; font-weight: 400; color: {TEXT}; }}
QPushButton {{ background: rgba(255, 255, 255, 0.82); border: 1px solid {ink_css(0.10)}; border-bottom-color: {ink_css(0.16)}; border-radius: 10px; padding: 7px 15px; font-weight: 500; color: {SECONDARY}; }}
QPushButton:hover {{ background: {PANEL}; border-color: {ink_css(0.18)}; color: {TEXT}; }}
QPushButton:pressed {{ background: {ink_css(0.04)}; }}
QPushButton:disabled {{ color: #b0b3b9; }}
QPushButton#nav {{ text-align: left; background: transparent; border: 1px solid transparent; border-radius: 10px; padding: 9px 12px; color: {SECONDARY}; font-weight: 500; }}
QPushButton#nav:hover {{ background: {ink_css(0.035)}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {PANEL}; border-color: {ink_css(0.09)}; border-bottom-color: {ink_css(0.15)}; color: {TEXT}; font-weight: 600; }}
QPushButton#period {{ background: transparent; border: 1px solid transparent; border-radius: 9px; color: {MUTED}; padding: 6px 14px; font-weight: 500; }}
QPushButton#period:hover {{ color: {TEXT}; }}
QPushButton#period:checked {{ background: {PANEL}; border-color: {ink_css(0.09)}; border-bottom-color: {ink_css(0.16)}; color: {TEXT}; font-weight: 600; }}
QFrame#segments {{ background: {ink_css(0.035)}; border: 1px solid {ink_css(0.06)}; border-radius: 13px; }}
QTableWidget {{ background: transparent; alternate-background-color: {ink_css(0.018)}; border: none; gridline-color: {ink_css(0.05)}; selection-background-color: {ink_css(0.06)}; selection-color: {TEXT}; outline: none; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: transparent; color: {MUTED}; border: none; border-bottom: 1px solid {ink_css(0.10)}; padding: 10px 12px; font-size: 12px; font-weight: 600; }}
QTableWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {ink_css(0.05)}; }}
QTableCornerButton::section {{ background: transparent; border: none; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 0; }}
QScrollBar::handle:vertical {{ background: {ink_css(0.16)}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {ink_css(0.28)}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ height: 8px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: {ink_css(0.16)}; border-radius: 4px; min-width: 30px; }}
QTextEdit, QLineEdit {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 8px; selection-background-color: {ink_css(0.14)}; }}
QTextEdit:focus, QLineEdit:focus {{ border-color: {ink_css(0.35)}; }}
QComboBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; padding: 8px; }}
QCheckBox {{ spacing: 9px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 10px; padding: 10px; background: {PANEL}; }}
QTabBar::tab {{ background: transparent; padding: 9px 14px; color: {MUTED}; border-bottom: 2px solid transparent; margin-right: 4px; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; font-weight: 600; }}
QToolTip {{ color: {TEXT}; background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 8px; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 7px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ink_css(0.06)}; color: {TEXT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
'''


# --------------------------------------------------------------------------- helpers

def apply_dark_frame(window):
    """Override Windows 11 accent-colored titlebar and outer frame with the paper tones."""
    if sys.platform != 'win32' or QApplication.platformName() == 'offscreen':
        return
    if not isinstance(window, (QMainWindow, QDialog)):
        return
    try:
        hwnd = int(window.winId())
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi
        for attr, val in (
            (20, ctypes.c_int(0)),              # DWMWA_USE_IMMERSIVE_DARK_MODE off
            (34, ctypes.c_uint32(0x00DEE3E3)),  # DWMWA_BORDER_COLOR (#e3e3de, COLORREF is BGR)
            (35, ctypes.c_uint32(0x00F7F9F9)),  # DWMWA_CAPTION_COLOR (#f9f9f7)
            (36, ctypes.c_uint32(0x001D1816)),  # DWMWA_TEXT_COLOR (#16181d)
        ):
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


class DarkFrameFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, (QMainWindow, QDialog)):
            apply_dark_frame(obj)
        return False


def label(text='', name='', color=None):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    if color:
        w.setStyleSheet(f'color:{color};')
    return w


def button(text, fn=None, name=''):
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if name:
        b.setObjectName(name)
    if fn:
        b.clicked.connect(fn)
    return b


def panel():
    frame = Glass()
    frame.setObjectName('panel')
    return frame


def compact(n):
    if n >= 1e9:
        return f'{n / 1e9:.2f} B'
    if n >= 1e6:
        return f'{n / 1e6:.2f} M'
    return f'{n:,}'


def start_of_today():
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def config_path():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.config'))) / 'AI-Pulse/settings.json'


def load_config():
    c = defaults()
    try:
        saved = json.loads(config_path().read_text(encoding='utf-8'))
        for key in ('roots', 'imports'):
            for app, paths in saved.get(key, {}).items():
                if app in APPS and isinstance(paths, list) and all(isinstance(p, str) for p in paths):
                    c[key][app] = paths
        if 'interval' in saved:
            c['interval'] = saved['interval']
        models = saved.get('antigravity_models', {})
        if isinstance(models, dict):
            c['antigravity_models'] = {str(k): v.strip() for k, v in models.items()
                                       if str(k).isdigit() and isinstance(v, str) and v.strip()}
        rate = saved.get('usd_to_cny')
        if isinstance(rate, (int, float)) and not isinstance(rate, bool) and 0 < float(rate) < 10000:
            c['usd_to_cny'] = float(rate)
        custom = saved.get('model_rates', {})
        if isinstance(custom, dict):
            valid_rates = {}
            for k, vals in custom.items():
                if isinstance(k, str) and k.strip() and isinstance(vals, list) and len(vals) >= 3:
                    try:
                        nums = [float(x) for x in vals[:4]]
                        if all(0 <= x < 100000 for x in nums):
                            valid_rates[k.strip()] = nums
                    except (TypeError, ValueError):
                        pass
            c['model_rates'] = valid_rates
        remote = saved.get('remote', {})
        if isinstance(remote, dict):
            r = c['remote']
            for k in ('enabled', 'tunnel', 'lan'):
                if isinstance(remote.get(k), bool):
                    r[k] = remote[k]
            port = remote.get('port')
            if isinstance(port, int) and not isinstance(port, bool) and 0 <= port < 65536:
                r['port'] = port
            for k in ('token', 'cloudflared', 'tunnel_token', 'public_url'):
                if isinstance(remote.get(k), str):
                    r[k] = remote[k].strip()
        if isinstance(saved.get('tray'), bool):
            c['tray'] = saved['tray']
        budget = saved.get('budget', {})
        if isinstance(budget, dict):
            for k in ('daily_cny', 'monthly_cny'):
                v = budget.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v < 1e9:
                    c['budget'][k] = float(v)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return c


def copy_config(config):
    return json.loads(json.dumps(config))


def parse_model_names(text):
    """Parse lines like '1401 = Claude Opus 5.5' into {'1401': 'Claude Opus 5.5'}."""
    names = {}
    for line in text.splitlines():
        number, sep, name = line.partition('=')
        if sep and number.strip().isdigit() and name.strip():
            names[number.strip()] = name.strip()
    return names


def format_model_names(names):
    return '\n'.join(f'{k} = {v}' for k, v in sorted(names.items(), key=lambda kv: int(kv[0])))


def app_icon():
    # One pixmap per common size so the title bar, taskbar and tray each get a crisp one.
    result = QIcon()
    for size in icon.ICO_SIZES:
        result.addPixmap(QPixmap.fromImage(icon.image(size)))
    return result


def nav_dot_icon(color_hex, overview=False):
    """Render a crisp vector badge icon for sidebar navigation items."""
    pix = QPixmap(28, 28)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color_hex)
    if overview:
        p.setPen(Qt.PenStyle.NoPen)
        for idx, (dx, dy) in enumerate([(6, 6), (15, 6), (6, 15), (15, 15)]):
            cell = QColor(c)
            cell.setAlpha(235 if idx == 0 else 155)
            p.setBrush(cell)
            p.drawRoundedRect(QRectF(dx, dy, 7, 7), 2.2, 2.2)
    else:
        halo = QColor(c)
        halo.setAlpha(45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(14, 14), 8.5, 8.5)
        p.setBrush(c)
        p.drawEllipse(QPointF(14, 14), 4.8, 4.8)
    p.end()
    return QIcon(pix)


def configure_fonts():
    # Windows' offscreen platform can omit system font discovery; register the
    # installed fonts directly when needed. Font files are never redistributed.
    global SERIF, NUM, LATIN
    directories = [Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts',
                   Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Microsoft/Windows/Fonts']
    families = set(QFontDatabase.families())
    if SANS not in families:
        for directory in directories:
            for file in ['msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf', 'segoeuib.ttf', 'SegUIVar.ttf',
                         'bahnschrift.ttf', 'NotoSerifSC-VF.ttf']:
                if (directory / file).exists():
                    QFontDatabase.addApplicationFont(str(directory / file))
        families = set(QFontDatabase.families())
    # Optional display faces: fall back to what every Windows install has.
    SERIF = next((f for f in ('Noto Serif SC', 'Source Han Serif SC', 'Source Han Serif CN') if f in families), SANS)
    NUM = 'Bahnschrift' if 'Bahnschrift' in families else 'Segoe UI'
    LATIN = next((f for f in ('Segoe UI Variable Text', 'Segoe UI') if f in families), SANS)


def qr_pixmap(text, size):
    """Render a QR code for the phone link; empty pixmap if segno is unavailable."""
    pix = QPixmap(size, size)
    pix.fill(QColor('#ffffff'))
    try:
        import segno
        rows = list(segno.make_qr(text, error='m').matrix_iter(scale=1, border=2))
    except Exception:
        return QPixmap()
    cell = size / len(rows)
    p = QPainter(pix)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#000000'))
    for y, row in enumerate(rows):
        for x, dark in enumerate(row):
            if dark:
                p.drawRect(QRectF(x * cell, y * cell, cell + 0.5, cell + 0.5))
    p.end()
    return pix


class RemoteSignal(QObject):
    # Tunnel threads report URL changes; the signal moves them onto the UI thread.
    changed = Signal()


def nice_max(value, intervals=3):
    """Round an axis maximum up so each of `intervals` ticks lands on a round number."""
    step = value / intervals
    magnitude = 10 ** math.floor(math.log10(step)) if step > 0 else 1
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * magnitude >= step:
            return m * magnitude * intervals
    return step * intervals


def painter(widget, family, size):
    p = QPainter(widget)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont(family)
    font.setPixelSize(size)
    p.setFont(font)
    return p


def ink(alpha):
    return QColor(*INK, alpha)


def white(alpha):
    return QColor(255, 255, 255, alpha)


# --------------------------------------------------------------------------- widgets

class Glass(QFrame):
    """Frosted white glass: the ruled page shows faintly through, with a bright top edge."""
    RADIUS = 14.0
    FILL = QColor(255, 255, 255, 214)

    def __init__(self, tint=None):
        super().__init__()
        self.tint = tint
        self.hovered = False
        self.cache, self.cache_key = None, None

    def enterEvent(self, event):
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        # The surface only changes with size and hover, so it is drawn once into a pixmap.
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, self.hovered)
        if key != self.cache_key:
            pix = QPixmap(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            self.paint_surface(p)
            p.end()
            self.cache, self.cache_key = pix, key
        p = QPainter(self)
        p.drawPixmap(0, 0, self.cache)
        p.end()

    def paint_surface(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        shape = QPainterPath()
        shape.addRoundedRect(r, self.RADIUS, self.RADIUS)
        p.fillPath(shape, white(232) if self.hovered else self.FILL)
        sheen = QLinearGradient(0, r.top(), 0, r.bottom())
        sheen.setColorAt(0, white(150))
        sheen.setColorAt(0.4, white(0))
        p.fillPath(shape, sheen)
        if self.tint:
            glow = QRadialGradient(QPointF(r.center().x(), r.top()), max(60.0, r.width() * 0.6))
            c = QColor(self.tint)
            c.setAlpha(22)
            glow.setColorAt(0, c)
            c.setAlpha(0)
            glow.setColorAt(1, c)
            p.fillPath(shape, glow)

        # Hairline rim, a touch darker toward the bottom where the glass meets its shadow.
        lift = 8 if self.hovered else 0
        rim = QLinearGradient(0, r.top(), 0, r.bottom())
        rim.setColorAt(0, ink(15 + lift))
        rim.setColorAt(1, ink(26 + lift))
        p.setPen(QPen(QBrush(rim), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(shape)
        # Inner edge: the thickness of the glass, a pure white line along the top.
        inner = r.adjusted(1, 1, -1, -1)
        edge = QLinearGradient(0, inner.top(), 0, inner.bottom())
        edge.setColorAt(0, white(255))
        edge.setColorAt(min(0.4, 22 / max(1.0, inner.height())), white(0))
        p.setPen(QPen(QBrush(edge), 1))
        p.drawRoundedRect(inner, self.RADIUS - 1, self.RADIUS - 1)


class Backdrop(QWidget):
    """Scrolling page surface: paper ruled with a fine grid, with glass panel shadows."""
    # (x, y, radius) as fractions of the page size, color and peak alpha: faint daylight washes.
    GLOWS = (
        (0.0, 0.0, 0.7, '#dfe4f2', 200),
        (1.0, 1.0, 0.6, '#f1e7da', 170),
    )
    CELL, MAJOR = 24, 4  # Minor rule spacing in px; every MAJOR-th rule is stronger.

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.cache, self.cache_key, self.panels = None, None, []
        # Rebuild the backdrop once a resize settles; until then the old one is stretched.
        self.rebuild = QTimer(self, singleShot=True, interval=120)
        self.rebuild.timeout.connect(lambda: (setattr(self, 'cache', None), self.update()))

    def track_panels(self):
        self.panels = self.findChildren(Glass)
        for g in self.panels:
            g.installEventFilter(self)

    def eventFilter(self, obj, event):
        # Shadows sit outside each panel, so redraw when a panel moves, resizes or toggles.
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide):
            self.update()
        return False

    def key(self):
        # Page size plus where each visible panel sits: the shadows are baked into the cache.
        rects = tuple(QRectF(QPointF(g.mapTo(self, QPoint(0, 0))), QSizeF(g.size()))
                      for g in self.panels if g.isVisibleTo(self))
        return self.width(), self.height(), self.devicePixelRatioF(), rects

    def render_base(self, key):
        w, h, dpr, rects = key
        pix = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
        pix.setDevicePixelRatio(dpr)
        pix.fill(QColor(BG))
        p = QPainter(pix)
        p.setPen(Qt.PenStyle.NoPen)
        page = QRectF(0, 0, w, h)
        for x, y, radius, color, alpha in self.GLOWS:
            glow = QRadialGradient(QPointF(w * x, h * y), max(200.0, w * radius))
            c = QColor(color)
            for stop, k in ((0, 1), (0.45, 0.5), (1, 0)):
                c.setAlpha(round(alpha * k))
                glow.setColorAt(stop, c)
            p.fillRect(page, glow)
        # The ruling: hairlines on a fixed grid, crisp at any scale factor.
        step = self.CELL
        for i in range(int(w // step) + 1):
            p.fillRect(QRectF(i * step, 0, 1 / dpr, h), ink(18 if i % self.MAJOR == 0 else 9))
        for i in range(int(h // step) + 1):
            p.fillRect(QRectF(0, i * step, w, 1 / dpr), ink(18 if i % self.MAJOR == 0 else 9))
        # Let the ruling fade out down the page so it frames the header and stays quiet below.
        fade = QLinearGradient(0, 0, 0, min(h, 900))
        paper = QColor(BG)
        paper.setAlpha(0)
        fade.setColorAt(0, paper)
        paper.setAlpha(190)
        fade.setColorAt(1, paper)
        p.fillRect(page, fade)
        if rects:
            # Soft layered shadow below each panel, kept off the glass itself so it stays clean.
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            holes = QPainterPath()
            for rect in rects:
                holes.addRoundedRect(rect, Glass.RADIUS, Glass.RADIUS)
            outside = QPainterPath()
            outside.addRect(page)
            p.setClipPath(outside.subtracted(holes))
            for rect in rects:
                for spread, alpha, dy in ((18, 3, 12), (11, 5, 8), (6, 7, 4), (2, 9, 1)):
                    p.setBrush(QColor(20, 26, 40, alpha))
                    p.drawRoundedRect(rect.adjusted(-spread, -spread + dy, spread, spread + dy),
                                      Glass.RADIUS + spread, Glass.RADIUS + spread)
        p.end()
        self.cache, self.cache_key = pix, key

    def paintEvent(self, event):
        key = self.key()
        if self.cache is None:
            self.render_base(key)
        elif key != self.cache_key and not self.rebuild.isActive():
            # Resizing or a panel moved: stretch the old backdrop until the layout settles.
            self.rebuild.start()
        p = QPainter(self)
        if self.cache_key[:3] == key[:3]:
            p.drawPixmap(0, 0, self.cache)
        else:
            p.drawPixmap(self.rect(), self.cache)


class ScanWorker(QThread):
    result = Signal(object)
    error = Signal(str)

    def __init__(self, collector):
        super().__init__()
        self.collector = collector

    def run(self):
        try:
            self.result.emit(self.collector.scan())
        except Exception as e:
            self.error.emit(type(e).__name__)


class Metric(Glass):
    def __init__(self, title, unit, primary=False, accent=ACCENT, quota=False):
        super().__init__(accent if quota else None)
        self.primary = primary
        self.quota = quota
        self.accent = accent
        self.setObjectName('metric')
        self.setProperty('primary', primary)
        self.setProperty('quota', quota)
        self.setMinimumWidth(124)
        box = QVBoxLayout(self)
        box.setContentsMargins(15, 14, 15, 14)
        box.setSpacing(6)

        titleline = QHBoxLayout()
        titleline.setSpacing(6)
        titleline.addWidget(label(title, 'muted'))
        titleline.addStretch()
        badge = label(unit, 'unit')
        badge.setProperty('primary', primary)
        badge.setProperty('quota', quota)
        titleline.addWidget(badge)
        box.addLayout(titleline)

        # Figures stay in text ink; only money wears amber. The accent lives in the top rule.
        self.value = label('—', 'number', GOLD if quota else None)
        self.value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        box.addWidget(self.value)

        self.detail = label('等待用量记录', 'muted')
        self.detail.setWordWrap(True)
        box.addWidget(self.detail)

    def update_value(self, value, detail, exact=''):
        self.value.setText(value)
        self.detail.setText(detail)
        self.setToolTip(exact or detail)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = QRectF(22, 0.6, self.width() - 44, 1.4)
        grad = QLinearGradient(top.topLeft(), top.topRight())
        # Only money gets the amber rule; the speed card is marked by its inked badge.
        if not self.quota:
            return
        c = QColor(self.accent)
        c.setAlpha(200)
        fade = QColor(self.accent)
        fade.setAlpha(0)
        grad.setColorAt(0, fade)
        grad.setColorAt(0.5, c)
        grad.setColorAt(1, fade)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(top, 1, 1)


class SpeedChart(QWidget):
    LIMIT = 40

    def __init__(self):
        super().__init__()
        self.rows = []
        self.hover = -1
        self.color = ACCENT
        self.setMouseTracking(True)
        self.setMinimumHeight(180)

    def set_rows(self, rows, color=ACCENT):
        self.rows = [r for r in rows if r.speed is not None][-self.LIMIT:]
        self.color = color
        self.hover = -1
        self.update()

    def plot_rect(self):
        return QRectF(42, 14, max(1, self.width() - 58), max(1, self.height() - 45))

    def point(self, i, maximum):
        rect = self.plot_rect()
        if len(self.rows) == 1:
            x = rect.center().x()
        else:
            x = rect.left() + rect.width() * i / (len(self.rows) - 1)
        y = rect.bottom() - rect.height() * self.rows[i].speed / maximum
        return QPointF(x, y)

    def paintEvent(self, event):
        p = painter(self, NUM, 11)
        rect = self.plot_rect()
        raw_max = max((r.speed for r in self.rows), default=0)
        maximum = nice_max(raw_max * 1.08) if raw_max > 0 else 60.0
        accent = QColor(self.color)

        # Grid and axis labels.
        for i in range(4):
            y = rect.top() + rect.height() * i / 3
            p.setPen(QPen(QColor(GRID if i < 3 else LINE), 1))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            p.setPen(QColor(MUTED))
            tick = f'{maximum * (1 - i / 3):.0f}' if self.rows else ('—' if i < 3 else '0')
            p.drawText(QRectF(0, y - 9, 34, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, tick)
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(rect.left(), rect.bottom() + 10, 100, 20), '较早')
        p.drawText(QRectF(rect.right() - 70, rect.bottom() + 10, 70, 20), Qt.AlignmentFlag.AlignRight, '最近')

        if not self.rows:
            badge = QRectF(rect.center().x() - 135, rect.center().y() - 18, 270, 36)
            p.setPen(QPen(ink(22), 1))
            p.setBrush(ink(8))
            p.drawRoundedRect(badge, 10, 10)
            f = QFont(SANS)
            f.setPixelSize(12)
            p.setFont(f)
            p.setPen(QColor(MUTED))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, '此时间范围暂无可计算速度的请求')
            return

        # Weighted average reference line when multiple points exist.
        points = [self.point(i, maximum) for i in range(len(self.rows))]
        if len(self.rows) >= 2:
            avg = sum(r.output for r in self.rows) / sum(r.seconds for r in self.rows)
            avg_y = rect.bottom() - rect.height() * min(avg, maximum) / maximum
            avg_pen = QPen(accent, 1, Qt.PenStyle.DotLine)
            c_line = QColor(accent)
            c_line.setAlpha(95)
            avg_pen.setColor(c_line)
            p.setPen(avg_pen)
            p.drawLine(QPointF(rect.left(), avg_y), QPointF(rect.right(), avg_y))

        # Smooth curve with a gradient fill underneath.
        if len(points) == 1:
            path = QPainterPath(QPointF(rect.left(), points[0].y()))
            path.lineTo(QPointF(rect.right(), points[0].y()))
            fill_left, fill_right = rect.left(), rect.right()
        else:
            path = QPainterPath(points[0])
            for a, b in zip(points, points[1:]):
                mid = (a.x() + b.x()) / 2
                path.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
            fill_left, fill_right = points[0].x(), points[-1].x()

        fill = QPainterPath(path)
        fill.lineTo(fill_right, rect.bottom())
        fill.lineTo(fill_left, rect.bottom())
        fill.closeSubpath()
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        top_fill = QColor(accent)
        top_fill.setAlpha(46)
        bot_fill = QColor(accent)
        bot_fill.setAlpha(0)
        gradient.setColorAt(0, top_fill)
        gradient.setColorAt(1, bot_fill)
        p.fillPath(fill, gradient)
        p.setPen(QPen(accent, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)

        # Halo + endpoint dot.
        last_pt = points[-1]
        halo = QRadialGradient(last_pt, 11)
        glow = QColor(accent)
        glow.setAlpha(95)
        halo.setColorAt(0, glow)
        halo.setColorAt(1, bot_fill)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(last_pt, 11, 11)
        p.setBrush(accent)
        p.drawEllipse(last_pt, 4.0, 4.0)

        if 0 <= self.hover < len(points):
            pt = points[self.hover]
            guide = QColor(accent)
            guide.setAlpha(130)
            p.setPen(QPen(guide, 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(pt.x(), rect.top()), QPointF(pt.x(), rect.bottom()))
            p.setBrush(accent)
            p.setPen(QPen(QColor(PANEL), 2.2))
            p.drawEllipse(pt, 5.5, 5.5)

    def mouseMoveEvent(self, event):
        if not self.rows:
            return
        rect = self.plot_rect()
        i = round((event.position().x() - rect.left()) / rect.width() * max(1, len(self.rows) - 1))
        self.hover = max(0, min(len(self.rows) - 1, i))
        r = self.rows[self.hover]
        model = f'  ·  {r.model}' if r.model else ''
        QToolTip.showText(
            event.globalPosition().toPoint(),
            f'{DISPLAY[r.app]}{model}\n{datetime.fromtimestamp(r.timestamp):%m-%d %H:%M:%S}  ·  ≈ {r.speed:.1f} tokens/s',
            self,
        )
        self.update()

    def leaveEvent(self, event):
        self.hover = -1
        QToolTip.hideText()
        self.update()


class Breakdown(QWidget):
    def __init__(self):
        super().__init__()
        self.totals = {a: 0 for a in APPS}
        self.items = [(DISPLAY[a], 0, 0.0, COLORS[a]) for a in APPS]
        self.tips = []
        self.usd_to_cny = DEFAULT_USD_TO_CNY
        self.setMouseTracking(True)
        self.setMinimumWidth(215)
        self.setMinimumHeight(180)

    def set_rows(self, rows, selected=ALL, custom_rates=None, usd_to_cny=DEFAULT_USD_TO_CNY):
        self.usd_to_cny = usd_to_cny
        self.tips = []
        self.totals = {a: sum(r.output for r in rows if r.app == a) for a in APPS}
        if selected != ALL and rows:
            by_model = {}
            cost_by_model = {}
            for r in rows:
                name = r.model or '未记录'
                by_model[name] = by_model.get(name, 0) + r.output
                usd, _ = estimate_usd(r, custom_rates)
                cost_by_model[name] = cost_by_model.get(name, 0.0) + usd
            ranked = sorted(by_model.items(), key=lambda kv: (kv[1], cost_by_model[kv[0]]), reverse=True)[:len(APPS)]
            self.items = [
                (name, val, cost_by_model[name], series_color(i))
                for i, (name, val) in enumerate(ranked)
            ]
        else:
            costs = {a: sum(estimate_usd(r, custom_rates)[0] for r in rows if r.app == a) for a in APPS}
            self.items = [(DISPLAY[a], self.totals[a], costs[a], COLORS[a]) for a in APPS]
        self.update()

    def paintEvent(self, event):
        p = painter(self, SANS, 12)
        values = [val for _, val, _, _ in self.items]
        highest = max(values + [1])
        slots = max(len(APPS), len(self.items))
        line = self.height() / slots
        width = self.width()

        for i, (name, total, usd, color_hex) in enumerate(self.items):
            y = i * line
            color = QColor(color_hex)
            active = total > 0 or usd > 0

            # Colored indicator dot + name.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color if active else ink(40))
            p.drawEllipse(QPointF(5, y + 10), 3.5, 3.5)

            right_text = f'{format_usd(usd)} · {compact(total)}' if active else '0'
            rw = p.fontMetrics().horizontalAdvance(right_text)

            p.setPen(QColor(TEXT if active else MUTED))
            avail = int(max(36, width - rw - 24))
            elided = p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, avail)
            p.drawText(QRectF(15, y, avail + 2, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

            p.setPen(QColor(SECONDARY if active else MUTED))
            p.drawText(QRectF(width - rw - 2, y, rw + 2, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right_text)

            # Progress bar track + fill.
            track = QRectF(0, y + 24, width, 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(TRACK))
            p.drawRoundedRect(track, 2, 2)
            if total:
                p.setBrush(color)
                p.drawRoundedRect(QRectF(0, y + 24, max(4.0, width * total / highest), 4), 2, 2)

    def mouseMoveEvent(self, event):
        if not self.items:
            return
        slots = max(len(APPS), len(self.items))
        line = max(1.0, self.height() / slots)
        idx = int(event.position().y() // line)
        if not (0 <= idx < len(self.items)):
            QToolTip.hideText()
            return
        name, total, usd, _ = self.items[idx]
        grand = sum(v for _, v, _, _ in self.items)
        pct = f'（{total * 100 / grand:.1f}%）' if grand and total else ''
        cny = usd * self.usd_to_cny
        tip = self.tips[idx] + '\n' if idx < len(self.tips) and self.tips[idx] else ''
        QToolTip.showText(
            event.globalPosition().toPoint(),
            f'{name}\n{tip}输出 {total:,} tokens{pct}\n折算额度 {format_usd(usd)}（约 {format_cny(cny)}）',
            self,
        )

    def set_items(self, items, tips=(), usd_to_cny=DEFAULT_USD_TO_CNY):
        """Show arbitrary (name, output, usd, color) rows, e.g. projects."""
        self.items, self.tips, self.usd_to_cny = list(items), list(tips), usd_to_cny
        self.update()

    def leaveEvent(self, event):
        QToolTip.hideText()


def level_color(pct, normal=ACCENT):
    return DANGER if pct >= 100 else (WARN if pct >= insights.WARN_PERCENT else normal)


class Gauge(Glass):
    """Compact limit card: value, usage bar and reset / limit detail."""

    def __init__(self):
        super().__init__()
        self.setObjectName('panel')
        self.pct, self.color = 0.0, ACCENT
        box = QVBoxLayout(self)
        box.setContentsMargins(15, 11, 15, 12)
        box.setSpacing(4)
        head = QHBoxLayout()
        self.title = label('', 'muted')
        head.addWidget(self.title)
        head.addStretch()
        self.value = label('', 'figure')
        head.addWidget(self.value)
        box.addLayout(head)
        box.addSpacing(16)  # Room for the painted usage bar.
        self.detail = label('', 'muted')
        box.addWidget(self.detail)

    def set(self, title, value, detail, pct, color, tip=''):
        self.title.setText(title)
        self.value.setText(value)
        # Text stays in ink unless the bar is in a warning state.
        self.value.setStyleSheet(f'color:{color if color in (WARN, DANGER) else TEXT};')
        self.detail.setText(detail)
        self.setToolTip(tip or detail)
        self.pct, self.color = pct, color
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(15, self.detail.y() - 10, self.width() - 30, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(TRACK))
        p.drawRoundedRect(track, 2, 2)
        if self.pct > 0:
            fill = QRectF(track.left(), track.top(), max(4.0, track.width() * min(self.pct, 100) / 100), 4)
            # A soft glow under the bar, then the bar brightening toward its end.
            halo = QColor(self.color)
            halo.setAlpha(40)
            p.setBrush(halo)
            p.drawRoundedRect(fill.adjusted(-1, -2, 1, 2), 4, 4)
            grad = QLinearGradient(fill.topLeft(), fill.topRight())
            start = QColor(self.color)
            start.setAlpha(170)
            grad.setColorAt(0, start)
            grad.setColorAt(1, QColor(self.color).lighter(118))
            p.setBrush(grad)
            p.drawRoundedRect(fill, 2, 2)


class DailyChart(QWidget):
    """Per-day estimated cost, stacked by app on the overview."""

    def __init__(self):
        super().__init__()
        self.days = []
        self.color = None
        self.fx = DEFAULT_USD_TO_CNY
        self.hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(190)

    def set_days(self, days, color=None, fx=DEFAULT_USD_TO_CNY):
        self.days, self.color, self.fx, self.hover = days, color, fx, -1
        self.update()

    def plot_rect(self):
        return QRectF(50, 10, max(1, self.width() - 56), max(1, self.height() - 38))

    def segments(self, day):
        if self.color:
            return [(self.color, day['usd'])]
        return [(COLORS[a], day['apps'].get(a, 0.0)) for a in APPS]

    def paintEvent(self, event):
        p = painter(self, NUM, 11)
        rect = self.plot_rect()
        top =max((d['usd'] for d in self.days), default=0)
        maximum = nice_max(top * 1.05) if top > 0 else 1.0
        for i in range(4):
            y = rect.top() + rect.height() * i / 3
            p.setPen(QPen(QColor(GRID if i < 3 else LINE), 1))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            p.setPen(QColor(MUTED))
            value = maximum * (1 - i / 3)
            tick = (f'${value:,.0f}' if value >= 10 or not value else format_usd(value)) if top > 0 else ('—' if i < 3 else '$0')
            p.drawText(QRectF(0, y - 9, 44, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, tick)
        if not self.days:
            return
        slot = rect.width() / len(self.days)
        bar = max(2.0, min(slot * 0.62, 18.0))
        p.setPen(QColor(MUTED))
        for i in range(len(self.days) - 1, -1, -7):
            x = rect.left() + slot * (i + 0.5)
            p.drawText(QRectF(x - 30, rect.bottom() + 8, 60, 18), Qt.AlignmentFlag.AlignCenter, self.days[i]['date'][5:])
        if top <= 0:
            badge = QRectF(rect.center().x() - 120, rect.center().y() - 18, 240, 36)
            p.setPen(QPen(ink(22), 1))
            p.setBrush(ink(8))
            p.drawRoundedRect(badge, 10, 10)
            f = QFont(SANS)
            f.setPixelSize(12)
            p.setFont(f)
            p.setPen(QColor(MUTED))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, f'近 {len(self.days)} 天暂无折算额度')
            return
        p.setPen(Qt.PenStyle.NoPen)
        radius = min(3.0, bar / 2)
        for i, day in enumerate(self.days):
            x = rect.left() + slot * i + (slot - bar) / 2
            y = rect.bottom()
            if self.hover == i:
                p.setBrush(ink(9))
                p.drawRoundedRect(QRectF(rect.left() + slot * i, rect.top(), slot, rect.height()), 4, 4)
            parts = [(c, v) for c, v in self.segments(day) if v > 0]
            for n, (color, value) in enumerate(parts):
                h = max(1.5, rect.height() * value / maximum)
                c = QColor(color)
                if self.hover not in (-1, i):
                    c.setAlpha(110)
                p.setBrush(c)
                # Stacked segments are separated by a 1.5px surface gap; only the top end is rounded.
                seg = QRectF(x, y - h, bar, h - (1.5 if n and h > 3 else 0))
                if n == len(parts) - 1:
                    path = QPainterPath()
                    path.addRoundedRect(seg, radius, radius)
                    path.addRect(QRectF(seg.left(), seg.bottom() - min(radius, seg.height() / 2), seg.width(), min(radius, seg.height() / 2)))
                    p.drawPath(path.simplified())
                else:
                    p.drawRect(seg)
                y -= h

    def mouseMoveEvent(self, event):
        if not self.days:
            return
        rect = self.plot_rect()
        i = int((event.position().x() - rect.left()) / (rect.width() / len(self.days)))
        if not 0 <= i < len(self.days):
            self.leaveEvent(event)
            return
        self.hover = i
        d = self.days[i]
        lines = [f'{d["date"]}  ·  {d["count"]:,} 次请求',
                 f'折算额度 {format_usd(d["usd"])}（约 {format_cny(d["usd"] * self.fx)}）  ·  输出 {compact(d["output"])}']
        if not self.color:
            lines += [f'{DISPLAY[a]}  {format_usd(v)}' for a, v in sorted(d['apps'].items(), key=lambda kv: -kv[1]) if v > 0]
        QToolTip.showText(event.globalPosition().toPoint(), '\n'.join(lines), self)
        self.update()

    def leaveEvent(self, event):
        self.hover = -1
        QToolTip.hideText()
        self.update()


# --------------------------------------------------------------------------- main window

class Pulse(QMainWindow):
    def __init__(self, smoke=False):
        super().__init__()
        configure_fonts()
        qapp = QApplication.instance()
        if qapp is not None and not getattr(qapp, '_dark_frame_filter', None):
            qapp._dark_frame_filter = DarkFrameFilter(qapp)
            qapp.installEventFilter(qapp._dark_frame_filter)
        self.collector = Collector(load_config())
        self.data = {}
        self.rows = []
        self.selected = ALL
        self.period = PERIODS[0]
        self.paused = False
        self.worker = None
        self.auto_period = True
        self.signature = None
        self.tray = None
        self.quitting = False
        self.tray_hinted = False
        self.notified = set()
        self.insights_at = 0.0

        self.setWindowTitle('AI Pulse · AI 用量工作台')
        self.setWindowIcon(app_icon())
        self.setStyleSheet(stylesheet())
        self.setMinimumSize(980, 620)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1380, available.width() - 50), min(880, available.height() - 60))
        self.move(available.center() - self.rect().center())
        apply_dark_frame(self)

        root = QWidget()
        root.setObjectName('root')
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.build_sidebar())

        scroll = QScrollArea()
        scroll.viewport().setObjectName('viewport')
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)
        self.content = Backdrop()
        self.content.setObjectName('content')
        scroll.setWidget(self.content)
        main = QVBoxLayout(self.content)
        main.setContentsMargins(24, 22, 24, 18)
        main.setSpacing(17)
        main.addLayout(self.build_header())
        main.addLayout(self.build_toolbar())
        main.addWidget(self.build_gauges())
        main.addLayout(self.build_metrics())
        main.addLayout(self.build_charts())
        main.addLayout(self.build_history())
        main.addWidget(self.build_table(), 1)
        main.addLayout(self.build_footer())
        self.content.track_panels()

        self.remote_signal = RemoteSignal(self)
        self.remote_signal.changed.connect(self.render_remote)
        self.remote = RemoteService(self.remote_signal.changed.emit)
        self.remote.apply(self.collector.config.get('remote', {}))
        self.setup_tray()

        self.select(ALL)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.interval_ms())
        QTimer.singleShot(100, self.refresh)
        if smoke:
            QTimer.singleShot(120000, self.quit_app)

    def showEvent(self, event):
        super().showEvent(event)
        apply_dark_frame(self)

    # ---- layout builders

    def build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(196)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 26, 16, 20)
        side.setSpacing(6)

        brand = QHBoxLayout()
        logo_mark = QLabel()
        logo_mark.setPixmap(app_icon().pixmap(32, 32))
        brand.addWidget(logo_mark)
        logo = label('AI PULSE')
        logo.setStyleSheet(f'font-family:"{LATIN}";font-size:17px;font-weight:700;letter-spacing:3px;color:{TEXT};')
        brand.addWidget(logo)
        brand.addStretch()
        side.addLayout(brand)
        side.addWidget(label('AI 用量监控工作台', 'muted'))
        side.addSpacing(26)
        side.addWidget(label('工作空间', 'eyebrow'))
        side.addSpacing(4)

        self.nav = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for app in (ALL,) + APPS:
            text = '用量总览' if app == ALL else DISPLAY[app]
            b = button(text, lambda checked=False, a=app: self.select(a), 'nav')
            b.setCheckable(True)
            b.setIcon(nav_dot_icon(ACCENT if app == ALL else COLORS[app], overview=(app == ALL)))
            b.setIconSize(QSize(18, 18))
            group.addButton(b)
            side.addWidget(b)
            self.nav[app] = b

        side.addStretch()
        self.connection = label('●  正在连接本地记录', 'muted')
        side.addWidget(self.connection)
        self.remote_label = label('', 'muted')
        self.remote_label.setWordWrap(True)
        side.addWidget(self.remote_label)
        side.addWidget(label('本地运行  ·  只读访问', 'muted'))
        side.addSpacing(6)
        side.addWidget(label('v0.2.0  /  DESKTOP', 'eyebrow'))
        return sidebar

    def build_header(self):
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(3)
        self.eyebrow = label('OVERVIEW', 'eyebrow')
        titles.addWidget(self.eyebrow)
        self.heading = label('用量总览', 'heading')
        titles.addWidget(self.heading)
        header.addLayout(titles)
        header.addStretch()

        segments = QFrame()
        segments.setObjectName('segments')
        box = QHBoxLayout(segments)
        box.setContentsMargins(4, 4, 4, 4)
        box.setSpacing(3)
        group = QButtonGroup(self)
        group.setExclusive(True)
        self.period_buttons = {}
        for text in PERIODS:
            b = button(text, lambda checked=False, t=text: self.set_period(t), 'period')
            b.setCheckable(True)
            group.addButton(b)
            box.addWidget(b)
            self.period_buttons[text] = b
        self.period_buttons[self.period].setChecked(True)
        header.addWidget(segments, 0, Qt.AlignmentFlag.AlignVCenter)
        return header

    def build_toolbar(self):
        toolbar = QHBoxLayout()
        self.status = label('正在读取本地用量记录…', 'muted')
        toolbar.addWidget(self.status, 1)
        self.pause_button = button('暂停', self.pause)
        toolbar.addWidget(self.pause_button)
        for title, fn in [('手机查看', self.remote_dialog), ('导入', self.import_file),
                          ('导出 CSV', self.export), ('设置', self.settings)]:
            toolbar.addWidget(button(title, fn))
        return toolbar

    def build_gauges(self):
        # Codex quota windows and spending budgets; hidden when neither is available.
        self.gauge_row = QWidget()
        row = QHBoxLayout(self.gauge_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.gauges = []
        for _ in range(4):
            g = Gauge()
            g.hide()
            row.addWidget(g, 1)
            self.gauges.append(g)
        self.gauge_row.hide()
        return self.gauge_row

    def build_history(self):
        row = QHBoxLayout()
        row.setSpacing(14)
        daily = panel()
        box = QVBoxLayout(daily)
        box.setContentsMargins(18, 16, 18, 12)
        box.setSpacing(8)
        title = QHBoxLayout()
        title.addWidget(label('每日折算额度', 'section'))
        title.addSpacing(14)
        self.daily_legend = label('', 'muted')
        self.daily_legend.setTextFormat(Qt.TextFormat.RichText)
        # Never widen the window for the legend; it clips on narrow layouts (the tooltip has every name).
        self.daily_legend.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title.addWidget(self.daily_legend, 1)
        self.daily_sub = label(f'近 {insights.HISTORY_DAYS} 天', 'muted')
        title.addWidget(self.daily_sub)
        box.addLayout(title)
        self.daily = DailyChart()
        box.addWidget(self.daily, 1)
        row.addWidget(daily, 12)

        side = panel()
        box = QVBoxLayout(side)
        box.setContentsMargins(18, 16, 18, 12)
        box.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(label('项目分布', 'section'))
        head.addStretch()
        head.addWidget(label('按工作目录 · 额度 · 输出', 'muted'))
        box.addLayout(head)
        self.projects = Breakdown()
        self.projects.setMinimumHeight(190)
        box.addWidget(self.projects, 1)
        row.addWidget(side, 5)
        return row

    def build_metrics(self):
        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self.cards = []
        specs = [
            ('最近速度', 'tok/s', True, ACCENT, False),
            ('平均速度', 'tok/s', False, SECONDARY, False),
            ('累计输出', 'tokens', False, SECONDARY, False),
            ('累计输入', 'tokens', False, SECONDARY, False),
            ('折算额度', 'USD', False, GOLD, True),
        ]
        for title, unit, primary, accent, quota in specs:
            card = Metric(title, unit, primary, accent, quota)
            metrics.addWidget(card, 1)
            self.cards.append(card)
        return metrics

    def build_charts(self):
        charts = QHBoxLayout()
        charts.setSpacing(14)

        trend = panel()
        box = QVBoxLayout(trend)
        box.setContentsMargins(18, 16, 18, 12)
        box.setSpacing(8)
        title = QHBoxLayout()
        title.addWidget(label('请求速度趋势', 'section'))
        title.addStretch()
        title.addWidget(label(f'最近 {SpeedChart.LIMIT} 次 · 虚线为均值', 'muted'))
        box.addLayout(title)
        self.chart = SpeedChart()
        box.addWidget(self.chart, 1)
        charts.addWidget(trend, 12)

        split = panel()
        box = QVBoxLayout(split)
        box.setContentsMargins(18, 16, 18, 12)
        box.setSpacing(8)
        split_head = QHBoxLayout()
        self.breakdown_title = label('软件输出分布', 'section')
        split_head.addWidget(self.breakdown_title)
        split_head.addStretch()
        self.breakdown_sub = label('额度 · 输出', 'muted')
        split_head.addWidget(self.breakdown_sub)
        box.addLayout(split_head)
        self.breakdown = Breakdown()
        box.addWidget(self.breakdown, 1)
        charts.addWidget(split, 5)
        return charts

    def build_table(self):
        recent = panel()
        box = QVBoxLayout(recent)
        box.setContentsMargins(0, 15, 0, 4)
        box.setSpacing(10)
        title = QHBoxLayout()
        title.setContentsMargins(18, 0, 18, 0)
        title.addWidget(label('最近请求', 'section'))
        title.addStretch()
        self.request_count = label('等待记录', 'muted')
        title.addWidget(self.request_count)
        box.addLayout(title)

        headers = ['时间', '软件', '模型', '输出 Token', '思考 Token', '速度 /s', '折算额度']
        t = self.table = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        for col in range(len(headers)):
            item = t.horizontalHeaderItem(col)
            if item:
                align = Qt.AlignmentFlag.AlignRight if col >= 3 else Qt.AlignmentFlag.AlignLeft
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        t.verticalHeader().hide()
        t.verticalHeader().setDefaultSectionSize(40)
        t.setShowGrid(False)
        t.setAlternatingRowColors(True)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setMinimumHeight(185)
        for col, width in enumerate([132, 138, 160, 96, 90, 96, 94]):
            t.setColumnWidth(col, width)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setMinimumSectionSize(70)
        box.addWidget(t, 1)
        return recent

    def build_footer(self):
        footer = QHBoxLayout()
        note = label('速度含记录中的等待与工具耗时；思考 Token 不重复计入输出或计费；API 额度按公开单价本地折算。', 'muted')
        note.setWordWrap(True)
        footer.addWidget(note, 1)
        self.updated = label('等待同步', 'muted')
        footer.addWidget(self.updated)
        return footer

    # ---- refresh cycle

    @property
    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def interval_ms(self):
        try:
            return max(1000, int(float(self.collector.config.get('interval', 3)) * 1000))
        except (TypeError, ValueError):
            return 3000

    def custom_rates(self):
        rates = self.collector.config.get('model_rates')
        return rates if isinstance(rates, dict) else None

    def usd_to_cny(self):
        try:
            v = float(self.collector.config.get('usd_to_cny', DEFAULT_USD_TO_CNY))
            return v if v > 0 else DEFAULT_USD_TO_CNY
        except (TypeError, ValueError):
            return DEFAULT_USD_TO_CNY

    def budget_limits(self):
        b = self.collector.config.get('budget')
        return b if isinstance(b, dict) else {}

    def refresh(self):
        if self.paused or self.busy:
            return
        self.worker = ScanWorker(self.collector)
        self.worker.result.connect(self.received)
        self.worker.error.connect(lambda e: self.status.setText('读取异常：' + e))
        self.worker.start()

    def received(self, data):
        self.updated.setText('同步于 ' + datetime.now().strftime('%H:%M:%S'))
        # Skip re-rendering unchanged data so table selection and scroll position survive.
        # The date is part of the signature so "today" / "last 7 days" roll over at midnight.
        signature = (datetime.now().date(),) + tuple(
            (a, d['status'], d['errors'], len(d['requests']),
             d['requests'][-1].timestamp if d['requests'] else 0,
             sum(r.output for r in d['requests']), (d.get('limits') or {}).get('t'))
            for a, d in data.items())
        if signature == self.signature:
            # Quota windows can reset without new records; checking twice a minute is plenty.
            if time.time() - self.insights_at >= 30:
                self.render_insights()
            return
        self.signature = signature
        self.data = data
        self.remote.set_data(data, self.custom_rates(), self.usd_to_cny(), self.budget_limits())
        if self.auto_period:
            # First load only: fall back to all records when nothing was recorded today.
            self.auto_period = False
            today = start_of_today()
            rows = [r for d in data.values() for r in d['requests']]
            if self.period == PERIODS[0] and rows and not any(r.timestamp >= today for r in rows):
                self.set_period('全部记录')
                return
        self.render()

    def select(self, app):
        self.selected = app
        self.nav[app].setChecked(True)
        self.eyebrow.setText('OVERVIEW' if app == ALL else f'WORKSPACE  ·  {app.upper()}')
        self.heading.setText('用量总览' if app == ALL else DISPLAY[app])
        self.breakdown_title.setText('软件输出分布' if app == ALL else '模型输出分布')
        self.render()

    def set_period(self, text):
        self.period = text
        self.auto_period = False
        self.period_buttons[text].setChecked(True)
        self.render()

    def pause(self):
        self.paused = not self.paused
        self.pause_button.setText('继续' if self.paused else '暂停')
        if self.tray:
            self.tray_pause.setText('继续同步' if self.paused else '暂停同步')
        self.render()
        self.refresh()

    def cutoff(self):
        if self.period == '今天':
            return start_of_today()
        if self.period == '近 7 天':
            return time.time() - 7 * 86400
        return 0

    # ---- rendering

    def render(self):
        if not self.data:
            return
        apps = APPS if self.selected == ALL else [self.selected]
        cutoff = self.cutoff()
        self.rows = sorted((r for a in apps for r in self.data[a]['requests'] if r.timestamp >= cutoff),
                           key=lambda r: r.timestamp)
        theme_color = ACCENT if self.selected == ALL else COLORS[self.selected]
        self.cards[0].accent = theme_color
        self.cards[0].update()
        self.render_metrics()
        self.render_status(apps)
        self.chart.set_rows(self.rows, theme_color)
        self.breakdown.set_rows(self.rows, self.selected, self.custom_rates(), self.usd_to_cny())
        self.render_history(apps)
        self.render_table()
        self.render_insights()

    def render_history(self, apps):
        rates = self.custom_rates()
        fx = self.usd_to_cny()
        days = insights.history(self.data, apps, rates)
        self.daily.set_days(days, None if self.selected == ALL else COLORS[self.selected], fx)
        total = sum(d['usd'] for d in days)
        used = [a for a in apps if any(d['apps'].get(a) for d in days)]
        self.daily_legend.setText('&nbsp;&nbsp;&nbsp;'.join(
            f'<span style="color:{COLORS[a]}">●</span>&nbsp;{DISPLAY[a]}' for a in used) if len(used) > 1 else '')
        self.daily_sub.setText(f'近 {len(days)} 天 · 合计 {format_usd(total)}（约 {format_cny(total * fx)}）')
        groups = insights.projects(self.rows, rates, limit=6)
        self.projects.set_items(
            [(g['name'], g['output'], g['usd'], series_color(i)) for i, g in enumerate(groups)],
            [g['path'] or '日志未记录工作目录（如 Reasonix、反重力）' for g in groups], fx)

    def render_insights(self):
        """Quota / budget gauges, tray tooltip and once-per-window warnings."""
        if not self.data:
            return
        self.insights_at = time.time()
        fx = self.usd_to_cny()
        quota = insights.quota(self.data)
        budget = insights.budget(self.data, self.budget_limits(), self.custom_rates(), fx)
        cards = []
        for q in quota:
            reset = f'{datetime.fromtimestamp(q["resets_at"]):%m-%d %H:%M} 重置' if q['resets_at'] else '已重置'
            color = DANGER if q['left'] <= 10 else (WARN if q['left'] <= 25 else ACCENT)
            cards.append((q['name'], f'剩 {q["left"]:.0f}%', f'已用 {q["used"]:.0f}% · {reset}', q['used'], color,
                          f'截至 {datetime.fromtimestamp(q["as_of"]):%m-%d %H:%M} 的 Codex 记录'
                          + (f'（{q["plan"]} 套餐）' if q['plan'] else '')))
        for b in budget:
            cards.append((b['name'], format_cny(b['spent']), f'上限 ¥{b["limit"]:g} · 已用 {b["pct"]:.0f}%',
                          b['pct'], level_color(b['pct']), ''))
        for g, card in zip(self.gauges, cards + [None] * len(self.gauges)):
            g.setVisible(card is not None)
            if card:
                g.set(*card)
        self.gauge_row.setVisible(bool(cards))

        if self.tray:
            today = insights.spend_usd(self.data, insights.day_start(time.time()), self.custom_rates())
            tip = f'AI Pulse\n今日 {format_usd(today)}（约 {format_cny(today * fx)}）'
            tip += ''.join(f'\n{q["name"]} 剩 {q["left"]:.0f}%' for q in quota)
            self.tray.setToolTip(tip)
        for key, title, message in insights.alerts(quota, budget):
            if key in self.notified:
                continue
            self.notified.add(key)
            if self.tray:
                self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Warning, 8000)

    def render_metrics(self):
        rows = self.rows
        timed = [r for r in rows if r.speed is not None]
        recent_timed = timed[-1] if timed else None
        avg = sum(r.output for r in timed) / sum(r.seconds for r in timed) if timed else None
        if recent_timed:
            self.cards[0].update_value(f'{recent_timed.speed:.1f}', f'≈ 请求耗时口径 · {DISPLAY[recent_timed.app]}')
        else:
            self.cards[0].update_value('—', '缺少单次耗时记录')
        self.cards[1].update_value(f'{avg:.1f}' if avg is not None else '—', f'{len(timed):,} / {len(rows):,} 次含耗时请求')
        output = sum(r.output for r in rows)
        inp = sum(r.input for r in rows)
        self.cards[2].update_value(compact(output), '思考 ' + compact(sum(r.reasoning for r in rows)),
                                   f'完整输出 Token：{output:,}')
        self.cards[3].update_value(compact(inp), '缓存读取 ' + compact(sum(r.cached for r in rows)),
                                   f'完整输入 Token：{inp:,}')
        rates = self.custom_rates()
        fx = self.usd_to_cny()
        total_usd = 0.0
        full_usd = 0.0
        for r in rows:
            u, full = estimate_usd(r, rates)
            total_usd += u
            full_usd += full
        total_cny = total_usd * fx
        saved_usd = max(0.0, full_usd - total_usd)
        if not rows:
            self.cards[4].update_value('—', '等待用量记录')
        else:
            detail = f'约 {format_cny(total_cny)}'
            detail += f' · 缓存省 {format_usd(saved_usd)}' if saved_usd >= 0.01 else ' · 按单价折算'
            exact = (
                f'折算 API 额度：${total_usd:,.4f}（约 ¥{total_cny:,.2f}，汇率 {fx:g}）\n'
                f'无缓存原价折算：${full_usd:,.4f}（缓存节省 ${saved_usd:,.4f}）\n'
                '可在「设置 → API 计费」修改汇率与自定义模型单价'
            )
            self.cards[4].update_value(format_usd(total_usd), detail, exact)

    def render_status(self, apps):
        ready = sum(bool(d['requests']) for d in self.data.values())
        self.connection.setText(f'●  {ready} / {len(APPS)} 个来源已连接')
        self.connection.setStyleSheet(f'color:{ACCENT};font-size:12px;')
        if self.selected == ALL:
            status = f'{ready} 个来源已接入 · 每 {self.interval_ms() / 1000:g} 秒自动同步'
        else:
            status = self.data[self.selected]['status']
        errors = sum(self.data[a]['errors'] for a in apps)
        if errors:
            status += f' · {errors} 条异常记录'
        self.status.setText(('已暂停 · ' if self.paused else '') + status)
        self.request_count.setText(f'{len(self.rows):,} 次请求 · 显示最近 {TABLE_LIMIT} 条')

    def render_table(self):
        t = self.table
        selected = t.currentRow()
        t.setUpdatesEnabled(False)
        t.setRowCount(min(TABLE_LIMIT, len(self.rows)))
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        rates = self.custom_rates()
        fx = self.usd_to_cny()
        icons = {a: nav_dot_icon(COLORS[a]) for a in APPS}  # Identity on the dot; the name stays in ink.
        for row, r in enumerate(reversed(self.rows[-TABLE_LIMIT:])):
            usd, _ = estimate_usd(r, rates)
            cny = usd * fx
            values = [
                datetime.fromtimestamp(r.timestamp).strftime('%m-%d %H:%M:%S'),
                DISPLAY[r.app],
                r.model or '未记录',
                f'{r.output:,}',
                f'{r.reasoning:,}',
                f'≈ {r.speed:.1f}' if r.speed is not None else '—',
                format_usd(usd),
            ]
            cw_note = f'  ·  缓存写入 {r.cache_write:,}' if r.cache_write else ''
            tip = (f'{DISPLAY[r.app]}  ·  {r.model or "未记录"}\n'
                   f'输入 {r.input:,}  ·  缓存 {r.cached:,}{cw_note}  ·  输出 {r.output:,}  ·  思考 {r.reasoning:,}\n'
                   f'折算额度 {format_usd(usd)}（约 {format_cny(cny)}）')
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(tip)
                if col >= 3:
                    item.setTextAlignment(right)
                if col == 1:
                    item.setIcon(icons[r.app])
                elif col == 5 and r.speed is not None:
                    item.setForeground(QColor(SECONDARY))
                elif col == 6:
                    item.setForeground(QColor(GOLD if usd > 0 else MUTED))
                elif col in (0, 4):
                    item.setForeground(QColor(MUTED))
                t.setItem(row, col, item)
        if 0 <= selected < t.rowCount():
            t.selectRow(selected)
        t.setUpdatesEnabled(True)

    # ---- dialogs and actions

    def save_config(self, config):
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)
        old_remote = self.collector.config.get('remote')
        self.collector = Collector(config)
        if config.get('remote') != old_remote:
            self.remote.apply(config.get('remote', {}))
        self.remote.set_data(self.data, self.custom_rates(), self.usd_to_cny(), self.budget_limits())
        self.signature = None  # New collector: force the next scan result to render.
        if self.data:
            self.render()
        self.status.setText('设置已保存，等待同步' if not self.paused else '设置已保存（当前已暂停自动同步）')
        QTimer.singleShot(50, self.refresh)

    def run_dialog(self, win):
        """Pause automatic scans while a modal dialog is open."""
        apply_dark_frame(win)
        was_active = self.timer.isActive()
        self.timer.stop()
        win.exec()
        if was_active:
            self.timer.start(self.interval_ms())

    def settings(self):
        if self.busy:
            QMessageBox.information(self, '正在同步', '请等待本次读取完成后再打开数据源。')
            return
        win = QDialog(self)
        win.setWindowTitle('设置')
        win.resize(780, 620)
        box = QVBoxLayout(win)
        box.setContentsMargins(22, 22, 22, 22)
        box.setSpacing(14)
        box.addWidget(label('设置', 'heading'))
        box.addWidget(label('数据源、API 计费、预算与后台运行。只读取本地用量与时间信息，配置仅保存在本机。', 'muted'))
        tabs = QTabWidget()
        box.addWidget(tabs, 1)
        fields = {}
        config = copy_config(self.collector.config)

        for app in APPS:
            tab = QWidget()
            form = QVBoxLayout(tab)
            form.setSpacing(10)
            form.addWidget(label(self.data.get(app, {}).get('status', '等待检测'), 'muted'))
            form.addWidget(label('记录目录（每行一个）', 'section'))
            roots = QTextEdit()
            roots.setPlainText('\n'.join(config['roots'][app]))
            roots.setMaximumHeight(105)
            form.addWidget(roots)

            def pick(checked=False, target=roots):
                p = QFileDialog.getExistingDirectory(win, '选择记录目录')
                if p:
                    target.append(p)

            form.addWidget(button('选择目录', pick), 0, Qt.AlignmentFlag.AlignLeft)
            form.addWidget(label('标准导入文件（每行一个 JSONL 路径）', 'section'))
            imports = QTextEdit()
            imports.setPlainText('\n'.join(config['imports'][app]))
            imports.setMaximumHeight(85)
            form.addWidget(imports)
            if app == 'Antigravity':
                hint = '反重力读取 conversations 下的 SQLite。'
                form.addWidget(label('模型名称（每行：编号 = 名称）', 'section'))
                model_names = QTextEdit()
                model_names.setPlaceholderText('1401 = Claude Opus 5.5')
                model_names.setPlainText(format_model_names(config.get('antigravity_models', {})))
                model_names.setMaximumHeight(85)
                form.addWidget(model_names)
                seen = sorted({r.model.removeprefix('未命名模型 #') for r in self.data.get(app, {}).get('requests', [])
                               if r.model.startswith('未命名模型 #')}, key=int)
                if seen:
                    hint += ' 尚未命名的编号：' + '、'.join(seen) + '。'
                hint += ' 模型名称自动从同目录 brain 日志读取；若日志缺失可在此手动补充或覆盖。'
            else:
                hint = 'Codex / Claude / WorkBuddy 选择会话目录；Reasonix 选择 stats 目录。'
            note = label(hint, 'muted')
            note.setWordWrap(True)
            form.addWidget(note)
            form.addStretch()
            tabs.addTab(tab, DISPLAY[app])
            fields[app] = (roots, imports)

        billing = QWidget()
        bform = QVBoxLayout(billing)
        bform.setSpacing(10)
        bform.addWidget(label('按各模型公开 API 单价（每百万 Token 美元）将本地 Token 用量折算为 API 额度与人民币金额。', 'muted'))
        bform.addWidget(label('美元兑人民币汇率（1 USD = ? CNY）', 'section'))
        fx_input = QLineEdit(f"{config.get('usd_to_cny', DEFAULT_USD_TO_CNY):g}")
        fx_input.setPlaceholderText(str(DEFAULT_USD_TO_CNY))
        fx_input.setMaximumWidth(200)
        bform.addWidget(fx_input)

        bform.addWidget(label('自定义模型单价（每行：模型关键字 = 输入, 缓存读取, 输出 [, 缓存写入]）', 'section'))
        rate_edit = QTextEdit()
        rate_edit.setPlaceholderText(
            'claude-opus-5-5 = 4.0, 0.2, 20.0, 8.0\n'
            'gpt-6.1-sol = 2.0, 0.2, 10.0\n'
            'deepseek-v4 = 0.15, 0.003, 0.6'
        )
        rate_edit.setPlainText(format_custom_rates(config.get('model_rates', {})))
        rate_edit.setMaximumHeight(170)
        bform.addWidget(rate_edit)

        bnote = label(
            '单位均为「美元 / 百万 Token」。已内置 OpenAI / Codex、Claude、Gemini、DeepSeek、Kimi、GLM、Qwen 等常用模型单价'
            '（自动区分缓存读取与 Claude 缓存写入，Reasonix 优先采用原始账单估值，思考 Token 不重复计费）。'
            '上方自定义规则按关键字不分大小写优先匹配；留空则使用内置单价。',
            'muted',
        )
        bnote.setWordWrap(True)
        bform.addWidget(bnote)
        bform.addStretch()
        tabs.addTab(billing, 'API 计费')

        general = QWidget()
        gform = QVBoxLayout(general)
        gform.setSpacing(10)
        gform.addWidget(label('后台运行', 'section'))
        tray_box = QCheckBox('关闭窗口时最小化到托盘（统计、预算提醒和手机查看继续工作）')
        tray_box.setChecked(bool(config.get('tray', True)))
        gform.addWidget(tray_box)
        startup_box = QCheckBox('开机自动启动（启动后直接最小化到托盘）')
        was_startup = autostart.enabled()
        startup_box.setChecked(was_startup)
        startup_box.setEnabled(autostart.supported())
        gform.addWidget(startup_box)
        gform.addSpacing(8)
        gform.addWidget(label('预算提醒（人民币，按折算额度计算，0 或留空表示不限制）', 'section'))
        budget_cfg = config.get('budget') or {}
        budget_fields = {}
        for key, title in (('daily_cny', '每日预算 ¥'), ('monthly_cny', '每月预算 ¥')):
            line = QHBoxLayout()
            name = label(title)
            name.setFixedWidth(90)
            line.addWidget(name)
            edit = QLineEdit(f'{budget_cfg.get(key, 0):g}' if budget_cfg.get(key) else '')
            edit.setPlaceholderText('不限制')
            edit.setMaximumWidth(200)
            line.addWidget(edit)
            line.addStretch()
            gform.addLayout(line)
            budget_fields[key] = edit
        gnote = label('用量达到预算的 80% 和 100% 时各提醒一次（托盘通知），手机页面顶部同步显示。'
                      'Codex 5 小时或每周额度剩余不足 10% 时也会提醒。', 'muted')
        gnote.setWordWrap(True)
        gform.addWidget(gnote)
        gform.addStretch()
        tabs.addTab(general, '常规与预算')

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存设置')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        box.addWidget(buttons)

        def lines(edit):
            return [p.strip() for p in edit.toPlainText().splitlines() if p.strip()]

        def save():
            raw_fx = fx_input.text().strip()
            if raw_fx:
                try:
                    fx_val = float(raw_fx)
                    if not (0 < fx_val < 10000):
                        raise ValueError
                    config['usd_to_cny'] = fx_val
                except ValueError:
                    QMessageBox.warning(win, '汇率格式无效', '请输入大于 0 的有效汇率数字（例如 7.15）。')
                    return
            else:
                config['usd_to_cny'] = DEFAULT_USD_TO_CNY
            budget = {}
            for key, edit in budget_fields.items():
                try:
                    value = float(edit.text().strip() or 0)
                    if not 0 <= value < 1e9:
                        raise ValueError
                except ValueError:
                    QMessageBox.warning(win, '预算格式无效', '预算请输入不小于 0 的数字，留空表示不限制。')
                    return
                budget[key] = value
            config['budget'] = budget
            config['tray'] = tray_box.isChecked()
            if startup_box.isChecked() or was_startup:
                try:
                    autostart.set_enabled(startup_box.isChecked())
                except OSError as e:
                    QMessageBox.warning(win, '开机启动设置失败', str(e))
                    return
            for app, (roots, imports) in fields.items():
                config['roots'][app] = lines(roots)
                config['imports'][app] = lines(imports)
            config['antigravity_models'] = parse_model_names(model_names.toPlainText())
            config['model_rates'] = parse_custom_rates(rate_edit.toPlainText())
            try:
                self.save_config(config)
                win.accept()
            except OSError as e:
                QMessageBox.critical(win, '保存失败', str(e))

        buttons.accepted.connect(save)
        buttons.rejected.connect(win.reject)
        self.run_dialog(win)

    def import_file(self):
        if self.busy:
            QMessageBox.information(self, '正在同步', '请等待本次读取完成。')
            return
        win = QDialog(self)
        win.setWindowTitle('导入用量记录')
        win.resize(450, 200)
        box = QVBoxLayout(win)
        box.setContentsMargins(24, 24, 24, 24)
        box.setSpacing(18)
        box.addWidget(label('选择记录所属软件', 'section'))
        choice = QComboBox()
        choice.addItems(APPS)
        box.addWidget(choice)

        def pick():
            path, _ = QFileDialog.getOpenFileName(win, '选择 ai-pulse/v1 文件', '', 'JSON Lines (*.jsonl)')
            if not path:
                return
            try:
                with open(path, encoding='utf-8') as f:
                    sample = json.loads(f.readline())
                if sample.get('schema') != 'ai-pulse/v1':
                    raise ValueError('文件须使用 ai-pulse/v1 格式，请参阅 README。')
                config = copy_config(self.collector.config)
                app = choice.currentText()
                if path not in config['imports'][app]:
                    config['imports'][app].append(path)
                self.save_config(config)
                win.accept()
            except (ValueError, OSError, AttributeError) as e:
                QMessageBox.critical(win, '导入失败', str(e))

        box.addWidget(button('选择 JSONL 文件', pick))
        self.run_dialog(win)

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出当前筛选结果', 'ai-pulse-usage.csv', 'CSV (*.csv)')
        if not path:
            return
        cols = [
            'app', 'timestamp', 'model', 'input', 'output', 'reasoning',
            'cached', 'cache_write', 'cache_write_1h', 'seconds', 'timing', 'speed', 'cost_usd', 'cost_cny',
            'project',
        ]
        rates = self.custom_rates()
        fx = self.usd_to_cny()
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=cols)
                writer.writeheader()
                for r in self.rows:
                    row = r.public()
                    usd, _ = estimate_usd(r, rates)
                    row['cost_usd'] = round(usd, 6)
                    row['cost_cny'] = round(usd * fx, 4)
                    row['timestamp'] = datetime.fromtimestamp(r.timestamp, timezone.utc).astimezone().isoformat()
                    # Neutralize spreadsheet formula injection (OWASP CSV injection prefixes).
                    if row['model'].startswith(('=', '+', '-', '@', '\t', '\r')):
                        row['model'] = "'" + row['model']
                    writer.writerow(row)
            QMessageBox.information(self, '导出完成', f'已导出 {len(self.rows):,} 条用量记录。')
        except OSError as e:
            QMessageBox.critical(self, '导出失败', str(e))

    def render_remote(self):
        headline, detail = self.remote.state()
        on = self.remote.running
        self.remote_label.setText(f'{"●" if on else "○"}  手机查看：{headline}')
        self.remote_label.setToolTip(detail)
        self.remote_label.setStyleSheet(f'color:{ACCENT if on and not detail else MUTED};font-size:12px;')

    def remote_dialog(self):
        win = QDialog(self)
        win.setWindowTitle('手机查看')
        win.resize(560, 720)
        box = QVBoxLayout(win)
        box.setContentsMargins(22, 22, 22, 22)
        box.setSpacing(12)
        box.addWidget(label('手机查看', 'heading'))
        intro = label('在手机浏览器中查看与桌面版相同的统计。只传输 Token 数、模型名、时间与折算额度，'
                      '不包含对话内容。需保持本程序运行。', 'muted')
        intro.setWordWrap(True)
        box.addWidget(intro)

        cfg = copy_config(self.collector.config).get('remote') or defaults()['remote']
        enabled = QCheckBox('开启手机查看')
        enabled.setChecked(cfg['enabled'])
        tunnel = QCheckBox('外网访问（通过 Cloudflare 通道，手机不在同一网络也能打开）')
        tunnel.setChecked(cfg['tunnel'])
        lan = QCheckBox('允许同一局域网的设备直接访问')
        lan.setChecked(cfg['lan'])
        for w in (enabled, tunnel, lan):
            box.addWidget(w)

        state = label('', 'section')
        box.addWidget(state)
        qr = QLabel()
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr.setFixedSize(230, 230)
        box.addWidget(qr, 0, Qt.AlignmentFlag.AlignHCenter)
        link = label('', 'muted')
        link.setWordWrap(True)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(link)

        actions = QHBoxLayout()
        copy_button = button('复制链接')
        reset_button = button('重置密钥')
        actions.addWidget(copy_button)
        actions.addWidget(reset_button)
        actions.addStretch()
        box.addLayout(actions)

        box.addWidget(label('高级设置', 'section'))
        port = QLineEdit(str(cfg['port']))
        port.setPlaceholderText('端口，默认 8765')
        exe = QLineEdit(cfg['cloudflared'])
        exe.setPlaceholderText(find_cloudflared() or '未找到 cloudflared，可安装后自动识别或在此填写路径')
        fixed_token = QLineEdit(cfg['tunnel_token'])
        fixed_token.setEchoMode(QLineEdit.EchoMode.Password)
        fixed_token.setPlaceholderText('可选：Cloudflare 固定通道令牌（不填则使用每次启动随机分配的地址）')
        fixed_url = QLineEdit(cfg['public_url'])
        fixed_url.setPlaceholderText('可选：固定通道对应的外网地址，例如 https://pulse.example.com')
        for w in (port, exe, fixed_token, fixed_url):
            box.addWidget(w)
        box.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存并应用')
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('关闭')
        box.addWidget(buttons)

        def current_link():
            return self.remote.public_url() or self.remote.local_url()

        def refresh_view():
            headline, detail = self.remote.state()
            state.setText(f'状态：{headline}' + (f'（{detail}）' if detail else ''))
            url = current_link()
            if url:
                qr.setPixmap(qr_pixmap(url, 230))
                kind = '外网链接' if self.remote.public_url() else '本机链接（外网地址生成前仅限这台电脑或局域网）'
                link.setText(f'{kind}：{url}')
            else:
                qr.setPixmap(QPixmap())
                qr.setText('开启后在此显示二维码')
                link.setText('')
            copy_button.setEnabled(bool(url))

        def copy():
            QApplication.clipboard().setText(current_link())
            copy_button.setText('已复制')
            QTimer.singleShot(1500, lambda: copy_button.setText('复制链接'))

        def apply(reset=False):
            try:
                port_value = int(port.text().strip() or 8765)
                if not 0 < port_value < 65536:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(win, '端口无效', '请输入 1–65535 之间的端口号。')
                return
            config = copy_config(self.collector.config)
            r = config.setdefault('remote', defaults()['remote'])
            r.update({'enabled': enabled.isChecked(), 'tunnel': tunnel.isChecked(), 'lan': lan.isChecked(),
                      'port': port_value, 'cloudflared': exe.text().strip(),
                      'tunnel_token': fixed_token.text().strip(), 'public_url': fixed_url.text().strip()})
            if reset or not r.get('token'):
                r['token'] = new_token()
            try:
                self.save_config(config)
            except OSError as e:
                QMessageBox.critical(win, '保存失败', str(e))

        def reset():
            if QMessageBox.question(win, '重置密钥', '重置后旧链接和已添加到主屏幕的入口都会失效，需要重新扫码。继续？') \
                    == QMessageBox.StandardButton.Yes:
                apply(reset=True)

        copy_button.clicked.connect(copy)
        reset_button.clicked.connect(reset)
        buttons.accepted.connect(apply)
        buttons.rejected.connect(win.reject)
        self.remote_signal.changed.connect(refresh_view)
        refresh_view()
        try:
            self.run_dialog(win)
        finally:
            self.remote_signal.changed.disconnect(refresh_view)

    # ---- tray

    def setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu(self)
        menu.addAction('显示窗口', self.show_window)
        self.tray_pause = menu.addAction('暂停同步', self.pause)
        menu.addSeparator()
        menu.addAction('退出 AI Pulse', self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.setToolTip('AI Pulse')
        self.tray.show()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self.quitting = True
        self.close()

    def closeEvent(self, event):
        if self.tray and self.tray.isVisible() and self.collector.config.get('tray', True) and not self.quitting:
            # Keep scanning (and serving the phone page) in the background.
            event.ignore()
            self.hide()
            if not self.tray_hinted:
                self.tray_hinted = True
                self.tray.showMessage('AI Pulse 仍在后台运行', '统计、预算提醒和手机查看会继续工作。右键托盘图标可以退出。',
                                      QSystemTrayIcon.MessageIcon.Information, 5000)
            return
        if self.tray:
            self.tray.hide()
        self.remote.stop()
        self.timer.stop()
        if self.busy:
            self.worker.wait()
        event.accept()
        QApplication.quit()


INSTANCE = 'AI-Pulse-' + (os.environ.get('USERNAME') or os.environ.get('USER') or 'user')


def main():
    if sys.platform == 'win32':
        # Own taskbar identity: otherwise a source run is grouped under (and shows) Python's icon.
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('AIPulse.Desktop')
        except (AttributeError, OSError):
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName('AI Pulse')
    app.setOrganizationName('AI Pulse')
    app.setWindowIcon(app_icon())
    app.setStyle('Fusion')
    font = QFont('Microsoft YaHei UI')
    font.setPixelSize(13)
    app.setFont(font)
    # One instance per user: a second launch (e.g. double-click while hidden in the tray)
    # asks the running one to show its window instead of competing for the phone port.
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    probe = QLocalSocket()
    probe.connectToServer(INSTANCE)
    if probe.waitForConnected(500):
        probe.write(b'show')
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        return
    # The window hides into the tray; quitting is explicit (closeEvent / tray menu).
    app.setQuitOnLastWindowClosed(False)
    window = Pulse(smoke='--smoke' in sys.argv)
    server = QLocalServer(window)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), window.show_window()))
    server.listen(INSTANCE)
    if autostart.MINIMIZED not in sys.argv or not window.tray:
        window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
