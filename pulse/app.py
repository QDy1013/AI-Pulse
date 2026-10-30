"""Qt desktop interface: device-independent layout and vector rendering."""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen, QLinearGradient, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QScrollArea, QButtonGroup, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
    QDialog, QTabWidget, QTextEdit, QComboBox, QDialogButtonBox, QToolTip, QSizePolicy,
)

from .collector import APPS, Collector, defaults

BG, PANEL, BORDER, TEXT, MUTED, ACCENT = '#101216', '#191c22', '#2c3039', '#f1f3f7', '#a3abba', '#c2f287'
COLORS = {'Codex': '#c2f287', 'Claude': '#e9ae91', 'Reasonix': '#b6a7fa', 'Antigravity': '#80baff', 'WorkBuddy': '#78dcc6'}
DISPLAY = {'Codex': 'Codex', 'Claude': 'Claude Code', 'Reasonix': 'Reasonix', 'Antigravity': '反重力', 'WorkBuddy': 'WorkBuddy'}

ALL = '全部软件'
PERIODS = ('今天', '近 7 天', '全部记录')
TABLE_LIMIT = 100

STYLE = f'''
QWidget {{ color: {TEXT}; font-family: "Microsoft YaHei UI"; font-size: 13px; }}
QMainWindow, QDialog, QWidget#root, QWidget#content, QWidget#viewport {{ background: {BG}; }}
QLabel {{ background: transparent; border: none; }}
QFrame#sidebar {{ background: #15171c; border-right: 1px solid #262a31; }}
QFrame#panel, QFrame#metric {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#metric[primary="true"] {{ background: #20291d; border: 1px solid #435336; }}
QLabel#muted {{ color: {MUTED}; font-size: 12px; }}
QLabel#eyebrow {{ color: #8f98aa; font-size: 11px; font-weight: 600; letter-spacing: 2px; }}
QLabel#heading {{ font-size: 27px; font-weight: 700; }}
QLabel#section {{ font-size: 14px; font-weight: 600; }}
QLabel#number {{ font-family: "Segoe UI"; font-size: 34px; font-weight: 600; letter-spacing: -1px; }}
QLabel#pill {{ color: {ACCENT}; background: #283523; border-radius: 10px; padding: 5px 10px; font-size: 11px; }}
QPushButton {{ background: #22262e; border: 1px solid #343a45; border-radius: 8px; padding: 8px 13px; font-weight: 500; }}
QPushButton:hover {{ background: #303641; border-color: #525d6b; }}
QPushButton:pressed {{ background: #3b4350; }}
QPushButton:disabled {{ color: #6c7483; }}
QPushButton#nav {{ text-align: left; background: transparent; border: 1px solid transparent; border-radius: 9px; padding: 12px; color: #b8bfcb; }}
QPushButton#nav:hover {{ background: #242830; color: white; }}
QPushButton#nav:checked {{ background: #2a3524; border-color: #3a4b30; color: {ACCENT}; font-weight: 600; }}
QPushButton#period {{ background: transparent; border: none; color: #aab2c0; padding: 7px 13px; }}
QPushButton#period:checked {{ background: #383e48; color: white; }}
QFrame#segments {{ background: #1e2229; border: 1px solid #303640; border-radius: 10px; }}
QTableWidget {{ background: transparent; alternate-background-color: #1d2128; border: none; gridline-color: #282d36; selection-background-color: #303d2b; selection-color: white; outline: none; }}
QHeaderView::section {{ background: #20242c; color: #aeb7c6; border: none; padding: 10px 12px; text-align: left; font-weight: 500; }}
QTableWidget::item {{ padding: 8px 12px; border-bottom: 1px solid #282d36; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 0; }}
QScrollBar::handle:vertical {{ background: #434b58; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ height: 8px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: #434b58; border-radius: 4px; min-width: 30px; }}
QTextEdit {{ background: #111419; color: {TEXT}; border: 1px solid #3d4654; border-radius: 7px; padding: 8px; selection-background-color: #425338; }}
QComboBox {{ background: #252b34; border: 1px solid #414a58; border-radius: 7px; padding: 8px; }}
QTabWidget::pane {{ border: 1px solid #343b47; border-radius: 8px; padding: 10px; }}
QTabBar::tab {{ background: #222731; padding: 10px 15px; color: #aeb7c6; }}
QTabBar::tab:selected {{ color: {ACCENT}; background: #303b29; }}
QToolTip {{ color: {TEXT}; background: #303743; border: 1px solid #566273; padding: 8px; }}
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
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return c


def copy_config(config):
    return json.loads(json.dumps(config))


def app_icon():
    image = QPixmap(128, 128)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor('#222e1d'))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(4, 4, 120, 120), 28, 28)
    path = QPainterPath(QPointF(20, 67))
    for x, y in [(43, 67), (53, 34), (73, 93), (85, 57), (108, 57)]:
        path.lineTo(x, y)
    p.setPen(QPen(QColor(ACCENT), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)
    p.end()
    return QIcon(image)


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
    def __init__(self, title, unit, primary=False):
        super().__init__()
        self.setObjectName('metric')
        self.setProperty('primary', primary)
        self.setMinimumWidth(155)
        box = QVBoxLayout(self)
        box.setContentsMargins(19, 17, 19, 17)
        box.setSpacing(5)

        titleline = QHBoxLayout()
        titleline.addWidget(label(title, 'muted'))
        titleline.addStretch()
        titleline.addWidget(label(unit, 'muted'))
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


class SpeedChart(QWidget):
    LIMIT = 40

    def __init__(self):
        super().__init__()
        self.rows = []
        self.hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(175)

    def set_rows(self, rows):
        self.rows = [r for r in rows if r.speed is not None][-self.LIMIT:]
        self.hover = -1
        self.update()

    def plot_rect(self):
        return QRectF(40, 14, max(1, self.width() - 58), max(1, self.height() - 45))

    def point(self, i, maximum):
        rect = self.plot_rect()
        x = rect.left() + rect.width() * i / max(1, len(self.rows) - 1)
        y = rect.bottom() - rect.height() * self.rows[i].speed / maximum
        return QPointF(x, y)

    def paintEvent(self, event):
        p = painter(self, 'Segoe UI', 11)
        rect = self.plot_rect()
        maximum = max([r.speed for r in self.rows] + [1]) * 1.18

        # Grid and axis labels.
        for i in range(4):
            y = rect.top() + rect.height() * i / 3
            p.setPen(QPen(QColor('#303641'), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            p.setPen(QColor('#9aa4b5'))
            p.drawText(QRectF(0, y - 9, 30, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f'{maximum * (1 - i / 3):.0f}')
        p.drawText(QRectF(rect.left(), rect.bottom() + 10, 100, 20), '较早')
        p.drawText(QRectF(rect.right() - 70, rect.bottom() + 10, 70, 20), Qt.AlignmentFlag.AlignRight, '最近')

        if not self.rows:
            p.setPen(QColor(MUTED))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, '此时间范围暂无可计算速度的请求')
            return

        # Smooth curve with a gradient fill underneath.
        points = [self.point(i, maximum) for i in range(len(self.rows))]
        path = QPainterPath(points[0])
        for a, b in zip(points, points[1:]):
            mid = (a.x() + b.x()) / 2
            path.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
        fill = QPainterPath(path)
        fill.lineTo(points[-1].x(), rect.bottom())
        fill.lineTo(points[0].x(), rect.bottom())
        fill.closeSubpath()
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0, QColor(194, 242, 135, 65))
        gradient.setColorAt(1, QColor(194, 242, 135, 0))
        p.fillPath(fill, gradient)
        p.setPen(QPen(QColor(ACCENT), 2.2))
        p.drawPath(path)
        p.setBrush(QColor(ACCENT))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(points[-1], 3.5, 3.5)

        if self.hover >= 0:
            pt = points[self.hover]
            p.setPen(QPen(QColor('#7b8771'), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(pt.x(), rect.top()), QPointF(pt.x(), rect.bottom()))
            p.setBrush(QColor(ACCENT))
            p.setPen(QPen(QColor(PANEL), 2))
            p.drawEllipse(pt, 5, 5)

    def mouseMoveEvent(self, event):
        if not self.rows:
            return
        rect = self.plot_rect()
        i = round((event.position().x() - rect.left()) / rect.width() * max(1, len(self.rows) - 1))
        self.hover = max(0, min(len(self.rows) - 1, i))
        r = self.rows[self.hover]
        QToolTip.showText(event.globalPosition().toPoint(),
                          f'{DISPLAY[r.app]}  ·  {datetime.fromtimestamp(r.timestamp):%m-%d %H:%M:%S}\n≈ {r.speed:.1f} tokens/s',
                          self)
        self.update()

    def leaveEvent(self, event):
        self.hover = -1
        QToolTip.hideText()
        self.update()


class Breakdown(QWidget):
    def __init__(self):
        super().__init__()
        self.totals = {a: 0 for a in APPS}
        self.setMinimumWidth(200)
        self.setMinimumHeight(175)

    def set_rows(self, rows):
        self.totals = {a: sum(r.output for r in rows if r.app == a) for a in APPS}
        self.update()

    def paintEvent(self, event):
        p = painter(self, 'Microsoft YaHei UI', 12)
        highest = max(max(self.totals.values()), 1)
        line = self.height() / len(APPS)
        width = self.width()
        for i, app in enumerate(APPS):
            y = i * line
            total = self.totals[app]
            p.setPen(QColor(TEXT))
            p.drawText(QRectF(0, y, width - 65, 20), DISPLAY[app])
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(width - 80, y, 80, 20), Qt.AlignmentFlag.AlignRight, compact(total))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#2b3039'))
            p.drawRoundedRect(QRectF(0, y + 24, width, 4), 2, 2)
            if total:
                p.setBrush(QColor(COLORS[app]))
                p.drawRoundedRect(QRectF(0, y + 24, max(4, width * total / highest), 4), 2, 2)


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
        sidebar.setFixedWidth(190)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 27, 16, 21)
        side.setSpacing(7)

        brand = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(30, 30))
        brand.addWidget(icon)
        logo = label('AI PULSE')
        logo.setStyleSheet('font-family:Segoe UI;font-size:20px;font-weight:700;letter-spacing:1px;')
        brand.addWidget(logo)
        brand.addStretch()
        side.addLayout(brand)
        side.addWidget(label('AI 用量工作台', 'muted'))
        side.addSpacing(31)
        side.addWidget(label('工作空间', 'eyebrow'))
        side.addSpacing(5)

        self.nav = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for app in (ALL,) + APPS:
            text = '用量总览' if app == ALL else '   ' + DISPLAY[app]
            b = button(text, lambda checked=False, a=app: self.select(a), 'nav')
            b.setCheckable(True)
            group.addButton(b)
            side.addWidget(b)
            self.nav[app] = b

        side.addStretch()
        self.connection = label('●  正在连接本地记录', 'muted')
        side.addWidget(self.connection)
        side.addWidget(label('本地运行  ·  只读访问', 'muted'))
        side.addSpacing(7)
        side.addWidget(label('v0.2.0  /  DESKTOP', 'eyebrow'))
        return sidebar

    def build_header(self):
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(3)
        titles.addWidget(label('OVERVIEW', 'eyebrow'))
        self.heading = label('用量总览', 'heading')
        titles.addWidget(self.heading)
        header.addLayout(titles)
        header.addStretch()

        segments = QFrame()
        segments.setObjectName('segments')
        box = QHBoxLayout(segments)
        box.setContentsMargins(4, 4, 4, 4)
        box.setSpacing(2)
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
        for title, unit, primary in [('最近请求速度', 'tok/s', True), ('平均请求速度', 'tok/s', False),
                                     ('累计输出', 'tokens', False), ('累计输入', 'tokens', False)]:
            card = Metric(title, unit, primary)
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
        title.addWidget(label(f'最近 {SpeedChart.LIMIT} 次 · 估算', 'muted'))
        box.addLayout(title)
        self.chart = SpeedChart()
        box.addWidget(self.chart, 1)
        charts.addWidget(trend, 3)

        split = panel()
        box = QVBoxLayout(split)
        box.setContentsMargins(18, 16, 18, 12)
        box.setSpacing(8)
        box.addWidget(label('输出分布', 'section'))
        self.breakdown = Breakdown()
        box.addWidget(self.breakdown, 1)
        charts.addWidget(split, 1)
        return charts

    def build_table(self):
        recent = panel()
        box = QVBoxLayout(recent)
        box.setContentsMargins(0, 15, 0, 4)
        box.setSpacing(12)
        title = QHBoxLayout()
        title.setContentsMargins(18, 0, 18, 0)
        title.addWidget(label('最近请求', 'section'))
        title.addStretch()
        self.request_count = label('等待记录', 'muted')
        title.addWidget(self.request_count)
        box.addLayout(title)

        t = self.table = QTableWidget(0, 6)
        t.setHorizontalHeaderLabels(['时间', '软件', '模型', '输出 Token', '思考 Token', '速度 /s'])
        t.verticalHeader().hide()
        t.verticalHeader().setDefaultSectionSize(40)
        t.setShowGrid(False)
        t.setAlternatingRowColors(True)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setMinimumHeight(185)
        for col, width in enumerate([150, 120, 180, 108, 108, 95]):
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
        self.heading.setText('用量总览' if app == ALL else DISPLAY[app])
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
        self.render_metrics()
        self.render_status(apps)
        self.chart.set_rows(self.rows)
        self.breakdown.set_rows(self.rows)
        self.render_table()

    def render_metrics(self):
        rows = self.rows
        timed = [r for r in rows if r.speed is not None]
        last = rows[-1] if rows else None
        avg = sum(r.output for r in timed) / sum(r.seconds for r in timed) if timed else None
        if last and last.speed is not None:
            self.cards[0].update_value(f'{last.speed:.1f}', '≈ 请求耗时口径')
        else:
            self.cards[0].update_value('—', '缺少单次耗时记录')
        self.cards[1].update_value(f'{avg:.1f}' if avg is not None else '—', f'{len(timed):,} 次有耗时的请求')
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
                DISPLAY[r.app],
                r.model or '未记录',
                f'{r.output:,}',
                f'{r.reasoning:,}',
                f'≈ {r.speed:.1f}' if r.speed is not None else '—',
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if col >= 3:
                    item.setTextAlignment(right)
                if col == 1:
                    item.setForeground(QColor(COLORS[r.app]))
                if col in (0, 4):
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
                hint = '反重力读取 conversations 下的 SQLite；模型暂显示原始编号。'
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
