"""Qt desktop interface: device-independent layout and vector rendering."""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPointF, QRectF, QSize
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen,
    QLinearGradient, QRadialGradient, QIcon, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QScrollArea, QButtonGroup, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
    QDialog, QTabWidget, QTextEdit, QComboBox, QDialogButtonBox, QToolTip, QSizePolicy,
)

from .collector import APPS, Collector, defaults

BG, PANEL, BORDER, TEXT, MUTED, ACCENT = '#0d1015', '#161a22', '#262c38', '#f1f4f9', '#949eb0', '#c2f287'
COLORS = {
    'Codex': '#c2f287',
    'Claude': '#f0a986',
    'Reasonix': '#b8a9ff',
    'Antigravity': '#7cc0ff',
    'WorkBuddy': '#6ee2c9',
}
DISPLAY = {
    'Codex': 'Codex',
    'Claude': 'Claude Code',
    'Reasonix': 'Reasonix',
    'Antigravity': '反重力',
    'WorkBuddy': 'WorkBuddy',
}
MODEL_PALETTE = ('#7cc0ff', '#c2f287', '#f0a986', '#b8a9ff', '#6ee2c9')

ALL = '全部软件'
PERIODS = ('今天', '近 7 天', '全部记录')
TABLE_LIMIT = 100

STYLE = f'''
QWidget {{ color: {TEXT}; font-family: "Microsoft YaHei UI"; font-size: 13px; }}
QMainWindow, QDialog, QWidget#root, QWidget#content, QWidget#viewport {{ background: {BG}; }}
QLabel {{ background: transparent; border: none; }}
QFrame#sidebar {{ background: #12151c; border-right: 1px solid #222733; }}
QFrame#panel, QFrame#metric {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#metric[primary="true"] {{ background: #192219; border: 1px solid #3c4f31; }}
QLabel#muted {{ color: {MUTED}; font-size: 12px; }}
QLabel#eyebrow {{ color: #7e889b; font-size: 11px; font-weight: 700; letter-spacing: 2px; }}
QLabel#heading {{ font-size: 26px; font-weight: 700; color: #f8fafd; }}
QLabel#section {{ font-size: 14px; font-weight: 600; color: #eef2f8; }}
QLabel#unit {{ color: #8c96a9; background: #202632; border: 1px solid #2d3545; border-radius: 9px; padding: 2px 8px; font-family: "Segoe UI"; font-size: 11px; font-weight: 600; }}
QLabel#unit[primary="true"] {{ color: {ACCENT}; background: #243220; border-color: #3a4f31; }}
QLabel#number {{ font-family: "Segoe UI"; font-size: 34px; font-weight: 700; letter-spacing: -1px; }}
QLabel#pill {{ color: {ACCENT}; background: #23301f; border: 1px solid #36492e; border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 600; }}
QPushButton {{ background: #1d222c; border: 1px solid #2e3646; border-radius: 8px; padding: 7px 14px; font-weight: 500; color: #dce2ec; }}
QPushButton:hover {{ background: #282f3d; border-color: #49556b; color: white; }}
QPushButton:pressed {{ background: #323b4c; }}
QPushButton:disabled {{ color: #6c7483; }}
QPushButton#nav {{ text-align: left; background: transparent; border: 1px solid transparent; border-radius: 10px; padding: 10px 12px; color: #b2bac9; font-weight: 500; }}
QPushButton#nav:hover {{ background: #1c212b; color: #f1f4f9; }}
QPushButton#nav:checked {{ background: #222c1f; border-color: #384a30; color: {ACCENT}; font-weight: 600; }}
QPushButton#period {{ background: transparent; border: none; border-radius: 7px; color: #9ea7b8; padding: 6px 14px; font-weight: 500; }}
QPushButton#period:hover {{ color: #e4e9f2; }}
QPushButton#period:checked {{ background: #2d3544; color: white; font-weight: 600; }}
QFrame#segments {{ background: #171b24; border: 1px solid #29303e; border-radius: 10px; }}
QTableWidget {{ background: transparent; alternate-background-color: #1a1f29; border: none; gridline-color: #242a36; selection-background-color: #263323; selection-color: white; outline: none; }}
QHeaderView::section {{ background: #1b202a; color: #97a2b5; border: none; border-bottom: 1px solid #282f3d; padding: 10px 12px; font-size: 12px; font-weight: 600; }}
QTableWidget::item {{ padding: 8px 12px; border-bottom: 1px solid #202632; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 0; }}
QScrollBar::handle:vertical {{ background: #3b4352; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #505b6e; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ height: 8px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: #3b4352; border-radius: 4px; min-width: 30px; }}
QTextEdit {{ background: #101319; color: {TEXT}; border: 1px solid #343d4d; border-radius: 8px; padding: 8px; selection-background-color: #3c4f31; }}
QComboBox {{ background: #1f2530; border: 1px solid #394354; border-radius: 8px; padding: 8px; }}
QTabWidget::pane {{ border: 1px solid #2d3442; border-radius: 10px; padding: 10px; background: #151921; }}
QTabBar::tab {{ background: #1b202a; padding: 9px 15px; color: #9ea7b8; border-top-left-radius: 7px; border-top-right-radius: 7px; margin-right: 3px; }}
QTabBar::tab:selected {{ color: {ACCENT}; background: #263222; font-weight: 600; }}
QToolTip {{ color: {TEXT}; background: #232936; border: 1px solid #475368; border-radius: 6px; padding: 8px; }}
'''


# --------------------------------------------------------------------------- helpers

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
    frame = QFrame()
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
    image = QPixmap(128, 128)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, 128, 128)
    grad.setColorAt(0, QColor('#263520'))
    grad.setColorAt(1, QColor('#172015'))
    p.setBrush(grad)
    p.setPen(QPen(QColor('#3e5633'), 3))
    p.drawRoundedRect(QRectF(6, 6, 116, 116), 28, 28)
    path = QPainterPath(QPointF(22, 67))
    for x, y in [(43, 67), (54, 34), (73, 93), (85, 57), (106, 57)]:
        path.lineTo(x, y)
    p.setPen(QPen(QColor(ACCENT), 7.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)
    p.end()
    return QIcon(image)


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
    directory = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts'
    for file in ['msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf', 'segoeuib.ttf']:
        if (directory / file).exists():
            QFontDatabase.addApplicationFont(str(directory / file))


def painter(widget, family, size):
    p = QPainter(widget)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont(family)
    font.setPixelSize(size)
    p.setFont(font)
    return p


# --------------------------------------------------------------------------- widgets

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


class Metric(QFrame):
    def __init__(self, title, unit, primary=False, accent=ACCENT):
        super().__init__()
        self.primary = primary
        self.accent = accent
        self.setObjectName('metric')
        self.setProperty('primary', primary)
        self.setMinimumWidth(155)
        box = QVBoxLayout(self)
        box.setContentsMargins(19, 16, 19, 16)
        box.setSpacing(6)

        titleline = QHBoxLayout()
        titleline.addWidget(label(title, 'muted'))
        titleline.addStretch()
        badge = label(unit, 'unit')
        badge.setProperty('primary', primary)
        titleline.addWidget(badge)
        box.addLayout(titleline)

        self.value = label('—', 'number', ACCENT if primary else None)
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
        top = QRectF(16, 1, self.width() - 32, 2.2)
        grad = QLinearGradient(top.topLeft(), top.topRight())
        c = QColor(self.accent)
        c.setAlpha(185 if self.primary else 75)
        fade = QColor(self.accent)
        fade.setAlpha(0)
        grad.setColorAt(0, c)
        grad.setColorAt(0.65, c if self.primary else fade)
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
        p = painter(self, 'Segoe UI', 11)
        rect = self.plot_rect()
        raw_max = max((r.speed for r in self.rows), default=0)
        maximum = max(raw_max * 1.18, 60.0 if not self.rows else 10.0)
        accent = QColor(self.color)

        # Grid and axis labels.
        for i in range(4):
            y = rect.top() + rect.height() * i / 3
            p.setPen(QPen(QColor('#262d3a'), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            p.setPen(QColor('#7f8a9e'))
            tick = f'{maximum * (1 - i / 3):.0f}' if self.rows else ('—' if i < 3 else '0')
            p.drawText(QRectF(0, y - 9, 34, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, tick)
        p.setPen(QColor('#7f8a9e'))
        p.drawText(QRectF(rect.left(), rect.bottom() + 10, 100, 20), '较早')
        p.drawText(QRectF(rect.right() - 70, rect.bottom() + 10, 70, 20), Qt.AlignmentFlag.AlignRight, '最近')

        if not self.rows:
            badge = QRectF(rect.center().x() - 135, rect.center().y() - 18, 270, 36)
            p.setPen(QPen(QColor('#293140'), 1))
            p.setBrush(QColor('#131720'))
            p.drawRoundedRect(badge, 10, 10)
            f = QFont('Microsoft YaHei UI')
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
        top_fill.setAlpha(72)
        bot_fill = QColor(accent)
        bot_fill.setAlpha(0)
        gradient.setColorAt(0, top_fill)
        gradient.setColorAt(1, bot_fill)
        p.fillPath(fill, gradient)
        p.setPen(QPen(accent, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
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
        self.items = [(DISPLAY[a], 0, COLORS[a]) for a in APPS]
        self.setMinimumWidth(215)
        self.setMinimumHeight(180)

    def set_rows(self, rows, selected=ALL):
        self.totals = {a: sum(r.output for r in rows if r.app == a) for a in APPS}
        if selected != ALL and rows:
            by_model = {}
            for r in rows:
                name = r.model or '未记录'
                by_model[name] = by_model.get(name, 0) + r.output
            ranked = sorted(by_model.items(), key=lambda kv: kv[1], reverse=True)[:len(APPS)]
            self.items = [
                (name, val, MODEL_PALETTE[i % len(MODEL_PALETTE)])
                for i, (name, val) in enumerate(ranked)
            ]
        else:
            self.items = [(DISPLAY[a], self.totals[a], COLORS[a]) for a in APPS]
        self.update()

    def paintEvent(self, event):
        p = painter(self, 'Microsoft YaHei UI', 12)
        values = [val for _, val, _ in self.items]
        highest = max(values + [1])
        grand = sum(values)
        slots = max(len(APPS), len(self.items))
        line = self.height() / slots
        width = self.width()

        for i, (name, total, color_hex) in enumerate(self.items):
            y = i * line
            color = QColor(color_hex)

            # Colored indicator dot + name.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color if total else QColor('#3d4554'))
            p.drawEllipse(QPointF(5, y + 10), 3.8, 3.8)

            p.setPen(QColor(TEXT if total else MUTED))
            elided = p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, int(max(40, width - 98)))
            p.drawText(QRectF(15, y, width - 94, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

            share = f'{total * 100 / grand:.0f}% · {compact(total)}' if grand and total else compact(total)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(width - 96, y, 96, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, share)

            # Progress bar track + fill.
            track = QRectF(0, y + 23, width, 5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#232833'))
            p.drawRoundedRect(track, 2.5, 2.5)
            if total:
                bar_w = max(6.0, width * total / highest)
                grad = QLinearGradient(0, 0, bar_w, 0)
                bright = QColor(color)
                soft = QColor(color)
                soft.setAlpha(185)
                grad.setColorAt(0, soft)
                grad.setColorAt(1, bright)
                p.setBrush(grad)
                p.drawRoundedRect(QRectF(0, y + 23, bar_w, 5), 2.5, 2.5)


# --------------------------------------------------------------------------- main window

class Pulse(QMainWindow):
    def __init__(self, smoke=False):
        super().__init__()
        configure_fonts()
        self.collector = Collector(load_config())
        self.data = {}
        self.rows = []
        self.selected = ALL
        self.period = PERIODS[0]
        self.paused = False
        self.worker = None
        self.auto_period = True
        self.signature = None

        self.setWindowTitle('AI Pulse · AI 用量工作台')
        self.setWindowIcon(app_icon())
        self.setStyleSheet(STYLE)
        self.setMinimumSize(980, 620)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1380, available.width() - 50), min(880, available.height() - 60))
        self.move(available.center() - self.rect().center())

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
        self.content = QWidget()
        self.content.setObjectName('content')
        scroll.setWidget(self.content)
        main = QVBoxLayout(self.content)
        main.setContentsMargins(26, 22, 26, 18)
        main.setSpacing(17)
        main.addLayout(self.build_header())
        main.addLayout(self.build_toolbar())
        main.addLayout(self.build_metrics())
        main.addLayout(self.build_charts())
        main.addWidget(self.build_table(), 1)
        main.addLayout(self.build_footer())

        self.select(ALL)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.interval_ms())
        QTimer.singleShot(100, self.refresh)
        if smoke:
            QTimer.singleShot(120000, self.close)

    # ---- layout builders

    def build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(196)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 26, 16, 20)
        side.setSpacing(6)

        brand = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(32, 32))
        brand.addWidget(icon)
        logo = label('AI PULSE')
        logo.setStyleSheet('font-family:"Segoe UI";font-size:19px;font-weight:700;letter-spacing:1.2px;color:#f5f7fb;')
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
        for title, fn in [('导入', self.import_file), ('导出 CSV', self.export), ('数据源', self.settings)]:
            toolbar.addWidget(button(title, fn))
        return toolbar

    def build_metrics(self):
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.cards = []
        specs = [
            ('最近请求速度', 'tok/s', True, ACCENT),
            ('平均请求速度', 'tok/s', False, '#7cc0ff'),
            ('累计输出', 'tokens', False, '#b8a9ff'),
            ('累计输入', 'tokens', False, '#f0a986'),
        ]
        for title, unit, primary, accent in specs:
            card = Metric(title, unit, primary, accent)
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
        self.breakdown_sub = label('按输出 Token', 'muted')
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

        t = self.table = QTableWidget(0, 6)
        headers = ['时间', '软件', '模型', '输出 Token', '思考 Token', '速度 /s']
        t.setHorizontalHeaderLabels(headers)
        for col in range(6):
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
        for col, width in enumerate([140, 108, 210, 96, 92, 84]):
            t.setColumnWidth(col, width)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setMinimumSectionSize(70)
        box.addWidget(t, 1)
        return recent

    def build_footer(self):
        footer = QHBoxLayout()
        note = label('速度包含记录中的等待与工具耗时；思考 Token 不重复计入输出。', 'muted')
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
             sum(r.output for r in d['requests']))
            for a, d in data.items())
        if signature == self.signature:
            return
        self.signature = signature
        self.data = data
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
        self.cards[0].value.setStyleSheet(f'color:{theme_color};')
        self.cards[0].update()
        self.render_metrics()
        self.render_status(apps)
        self.chart.set_rows(self.rows, theme_color)
        self.breakdown.set_rows(self.rows, self.selected)
        self.render_table()

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
        for row, r in enumerate(reversed(self.rows[-TABLE_LIMIT:])):
            values = [
                datetime.fromtimestamp(r.timestamp).strftime('%m-%d %H:%M:%S'),
                '●  ' + DISPLAY[r.app],
                r.model or '未记录',
                f'{r.output:,}',
                f'{r.reasoning:,}',
                f'≈ {r.speed:.1f}' if r.speed is not None else '—',
            ]
            tip = (f'{DISPLAY[r.app]}  ·  {r.model or "未记录"}\n'
                   f'输入 {r.input:,}  ·  缓存 {r.cached:,}  ·  输出 {r.output:,}  ·  思考 {r.reasoning:,}')
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(tip)
                if col >= 3:
                    item.setTextAlignment(right)
                if col == 1:
                    item.setForeground(QColor(COLORS[r.app]))
                elif col == 5 and r.speed is not None:
                    item.setForeground(QColor(ACCENT))
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
        self.collector = Collector(config)
        self.signature = None  # New collector: force the next scan result to render.
        self.status.setText('设置已保存，等待同步')

    def run_dialog(self, win):
        """Pause automatic scans while a modal dialog is open."""
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
        win.setWindowTitle('数据源设置')
        win.resize(760, 610)
        box = QVBoxLayout(win)
        box.setContentsMargins(22, 22, 22, 22)
        box.setSpacing(14)
        box.addWidget(label('管理本地数据源', 'heading'))
        box.addWidget(label('只读取用量与时间信息，设置仅保存在本机。', 'muted'))
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

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存设置')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        box.addWidget(buttons)

        def lines(edit):
            return [p.strip() for p in edit.toPlainText().splitlines() if p.strip()]

        def save():
            for app, (roots, imports) in fields.items():
                config['roots'][app] = lines(roots)
                config['imports'][app] = lines(imports)
            config['antigravity_models'] = parse_model_names(model_names.toPlainText())
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
        cols = ['app', 'timestamp', 'model', 'input', 'output', 'reasoning', 'cached', 'seconds', 'timing', 'speed']
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=cols)
                writer.writeheader()
                for r in self.rows:
                    row = r.public()
                    row['timestamp'] = datetime.fromtimestamp(r.timestamp, timezone.utc).astimezone().isoformat()
                    # Neutralize spreadsheet formula injection (OWASP CSV injection prefixes).
                    if row['model'].startswith(('=', '+', '-', '@', '\t', '\r')):
                        row['model'] = "'" + row['model']
                    writer.writerow(row)
            QMessageBox.information(self, '导出完成', f'已导出 {len(self.rows):,} 条用量记录。')
        except OSError as e:
            QMessageBox.critical(self, '导出失败', str(e))

    def closeEvent(self, event):
        self.timer.stop()
        if self.busy:
            self.worker.wait()
        event.accept()


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName('AI Pulse')
    app.setOrganizationName('AI Pulse')
    app.setStyle('Fusion')
    font = QFont('Microsoft YaHei UI')
    font.setPixelSize(13)
    app.setFont(font)
    window = Pulse(smoke='--smoke' in sys.argv)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
