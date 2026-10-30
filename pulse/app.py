"""Qt desktop interface: device-independent layout and vector rendering."""
from __future__ import annotations
import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen, QLinearGradient, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QButtonGroup, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
    QDialog, QTabWidget, QTextEdit, QComboBox, QDialogButtonBox, QToolTip, QSizePolicy)
from .collector import APPS, Collector, defaults

BG, PANEL, BORDER, TEXT, MUTED, ACCENT = '#101216', '#191c22', '#2c3039', '#f1f3f7', '#a3abba', '#c2f287'
COLORS = {'Codex':'#c2f287', 'Claude':'#e9ae91', 'Reasonix':'#b6a7fa', 'Antigravity':'#80baff', 'WorkBuddy':'#78dcc6'}
DISPLAY = {'Codex':'Codex','Claude':'Claude Code','Reasonix':'Reasonix','Antigravity':'反重力','WorkBuddy':'WorkBuddy'}

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

def label(text='', name='', color=None):
    w = QLabel(text)
    if name: w.setObjectName(name)
    if color: w.setStyleSheet(f'color:{color};')
    return w

def button(text, fn=None, name=''):
    b = QPushButton(text); b.setCursor(Qt.CursorShape.PointingHandCursor)
    if name: b.setObjectName(name)
    if fn: b.clicked.connect(fn)
    return b

def compact(n):
    return f'{n/1e9:.2f} B' if n >= 1e9 else f'{n/1e6:.2f} M' if n >= 1e6 else f'{n:,}'

def config_path():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'.config'))) / 'AI-Pulse/settings.json'

def load_config():
    c = defaults()
    try:
        saved = json.loads(config_path().read_text(encoding='utf-8'))
        for key in ('roots', 'imports'):
            for app, paths in saved.get(key, {}).items():
                if app in APPS and isinstance(paths,list) and all(isinstance(p,str) for p in paths): c[key][app]=paths
    except (OSError, ValueError, TypeError, AttributeError): pass
    return c

def app_icon():
    image = QPixmap(128,128); image.fill(Qt.GlobalColor.transparent)
    p=QPainter(image); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor('#222e1d')); p.setPen(Qt.PenStyle.NoPen); p.drawRoundedRect(QRectF(4,4,120,120),28,28)
    path=QPainterPath(QPointF(20,67));path.lineTo(43,67);path.lineTo(53,34);path.lineTo(73,93);path.lineTo(85,57);path.lineTo(108,57)
    p.setPen(QPen(QColor(ACCENT),7,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));p.drawPath(path);p.end()
    return QIcon(image)

def configure_fonts():
    # Windows' offscreen platform can omit system font discovery; register the
    # installed fonts directly when needed. Font files are never redistributed.
    directory=Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'
    for file in ['msyh.ttc','msyhbd.ttc','segoeui.ttf','segoeuib.ttf']:
        if (directory/file).exists():QFontDatabase.addApplicationFont(str(directory/file))

class ScanWorker(QThread):
    result = Signal(object)
    error = Signal(str)
    def __init__(self, collector): super().__init__(); self.collector=collector
    def run(self):
        try: self.result.emit(self.collector.scan())
        except Exception as e: self.error.emit(type(e).__name__)

class Metric(QFrame):
    def __init__(self, title, unit, primary=False):
        super().__init__();self.setObjectName('metric');self.setProperty('primary',primary)
        box=QVBoxLayout(self);box.setContentsMargins(19,17,19,17);box.setSpacing(5)
        titleline=QHBoxLayout();titleline.addWidget(label(title,'muted'));titleline.addStretch();titleline.addWidget(label(unit,'muted'));box.addLayout(titleline)
        self.value=label('—','number',ACCENT if primary else None);self.value.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);box.addWidget(self.value)
        self.detail=label('等待用量记录','muted');self.detail.setWordWrap(True);box.addWidget(self.detail)
        self.setMinimumWidth(155)
    def update_value(self, value, detail, exact=''):
        self.value.setText(value); self.detail.setText(detail);self.setToolTip(exact or detail)

class SpeedChart(QWidget):
    def __init__(self):
        super().__init__();self.rows=[];self.hover=-1;self.setMouseTracking(True);self.setMinimumHeight(175)
    def set_rows(self, rows): self.rows=[r for r in rows if r.speed is not None][-40:];self.hover=-1;self.update()
    def plot_rect(self): return QRectF(40,14,max(1,self.width()-58),max(1,self.height()-45))
    def point(self,i,maximum):
        rect=self.plot_rect();return QPointF(rect.left()+rect.width()*i/max(1,len(self.rows)-1),rect.bottom()-rect.height()*self.rows[i].speed/maximum)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font=QFont('Segoe UI');font.setPixelSize(11);p.setFont(font)
        rect=self.plot_rect();maximum=max([r.speed for r in self.rows]+[1])*1.18
        for i in range(4):
            y=rect.top()+rect.height()*i/3
            p.setPen(QPen(QColor('#303641'),1,Qt.PenStyle.DashLine));p.drawLine(QPointF(rect.left(),y),QPointF(rect.right(),y))
            p.setPen(QColor('#9aa4b5'));p.drawText(QRectF(0,y-9,30,18),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,f'{maximum*(1-i/3):.0f}')
        p.drawText(QRectF(rect.left(),rect.bottom()+10,100,20),'较早');p.drawText(QRectF(rect.right()-70,rect.bottom()+10,70,20),Qt.AlignmentFlag.AlignRight,'最近')
        if not self.rows:
            p.setPen(QColor(MUTED));p.drawText(rect,Qt.AlignmentFlag.AlignCenter,'此时间范围暂无可计算速度的请求');return
        points=[self.point(i,maximum) for i in range(len(self.rows))]
        path=QPainterPath(points[0])
        for a,b in zip(points,points[1:]):
            mid=(a.x()+b.x())/2;path.cubicTo(QPointF(mid,a.y()),QPointF(mid,b.y()),b)
        fill=QPainterPath(path);fill.lineTo(points[-1].x(),rect.bottom());fill.lineTo(points[0].x(),rect.bottom());fill.closeSubpath()
        gradient=QLinearGradient(rect.topLeft(),rect.bottomLeft());gradient.setColorAt(0,QColor(194,242,135,65));gradient.setColorAt(1,QColor(194,242,135,0))
        p.fillPath(fill,gradient);p.setPen(QPen(QColor(ACCENT),2.2));p.drawPath(path)
        p.setBrush(QColor(ACCENT));p.setPen(Qt.PenStyle.NoPen);p.drawEllipse(points[-1],3.5,3.5)
        if self.hover>=0:
            pt=points[self.hover];p.setPen(QPen(QColor('#7b8771'),1,Qt.PenStyle.DashLine));p.drawLine(QPointF(pt.x(),rect.top()),QPointF(pt.x(),rect.bottom()))
            p.setBrush(QColor(ACCENT));p.setPen(QPen(QColor(PANEL),2));p.drawEllipse(pt,5,5)
    def mouseMoveEvent(self,event):
        if not self.rows:return
        rect=self.plot_rect();i=round((event.position().x()-rect.left())/rect.width()*max(1,len(self.rows)-1));self.hover=max(0,min(len(self.rows)-1,i))
        r=self.rows[self.hover];QToolTip.showText(event.globalPosition().toPoint(),f'{DISPLAY[r.app]}  ·  {datetime.fromtimestamp(r.timestamp):%m-%d %H:%M:%S}\n≈ {r.speed:.1f} tokens/s',self);self.update()
    def leaveEvent(self,event):self.hover=-1;QToolTip.hideText();self.update()

class Breakdown(QWidget):
    def __init__(self):super().__init__();self.totals={a:0 for a in APPS};self.setMinimumWidth(200);self.setMinimumHeight(175)
    def set_rows(self,rows):self.totals={a:sum(r.output for r in rows if r.app==a) for a in APPS};self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font=QFont('Microsoft YaHei UI');font.setPixelSize(12);p.setFont(font)
        highest=max(max(self.totals.values()),1);line=self.height()/5
        for i,app in enumerate(APPS):
            y=i*line;p.setPen(QColor(TEXT));p.drawText(QRectF(0,y,self.width()-65,20),DISPLAY[app]);p.setPen(QColor(MUTED));p.drawText(QRectF(self.width()-80,y,80,20),Qt.AlignmentFlag.AlignRight,compact(self.totals[app]))
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#2b3039'));p.drawRoundedRect(QRectF(0,y+24,self.width(),4),2,2)
            if self.totals[app]:p.setBrush(QColor(COLORS[app]));p.drawRoundedRect(QRectF(0,y+24,max(4,self.width()*self.totals[app]/highest),4),2,2)

class Pulse(QMainWindow):
    def __init__(self,smoke=False):
        super().__init__();self.setWindowTitle('AI Pulse · AI 用量工作台');self.setWindowIcon(app_icon())
        configure_fonts()
        self.collector=Collector(load_config());self.data={};self.rows=[];self.selected='全部软件';self.paused=False;self.worker=None
        self.setStyleSheet(STYLE)
        self.setMinimumSize(980,620)
        available=QApplication.primaryScreen().availableGeometry()
        self.resize(min(1380,available.width()-50),min(880,available.height()-60))
        self.move(available.center()-self.rect().center())
        root=QWidget();root.setObjectName('root');self.setCentralWidget(root);layout=QHBoxLayout(root);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        sidebar=QFrame();sidebar.setObjectName('sidebar');sidebar.setFixedWidth(190);side=QVBoxLayout(sidebar);side.setContentsMargins(16,27,16,21);side.setSpacing(7)
        brand=QHBoxLayout();icon=QLabel();icon.setPixmap(app_icon().pixmap(30,30));brand.addWidget(icon);logo=label('AI PULSE');logo.setStyleSheet('font-family:Segoe UI;font-size:20px;font-weight:700;letter-spacing:1px;');brand.addWidget(logo);brand.addStretch();side.addLayout(brand)
        side.addWidget(label('AI 用量工作台','muted'));side.addSpacing(31);side.addWidget(label('工作空间','eyebrow'));side.addSpacing(5)
        self.nav={};nav_group=QButtonGroup(self);nav_group.setExclusive(True)
        for app in ('全部软件',)+APPS:
            b=button('用量总览' if app=='全部软件' else '   '+DISPLAY[app],lambda checked=False,a=app:self.select(a),'nav');b.setCheckable(True);nav_group.addButton(b);side.addWidget(b);self.nav[app]=b
        side.addStretch();self.connection=label('●  正在连接本地记录','muted');side.addWidget(self.connection);side.addWidget(label('本地运行  ·  只读访问','muted'));side.addSpacing(7);side.addWidget(label('v0.2.0  /  DESKTOP','eyebrow'));layout.addWidget(sidebar)
        scroll=QScrollArea();scroll.viewport().setObjectName('viewport');scroll.setWidgetResizable(True);layout.addWidget(scroll,1)
        self.content=QWidget();self.content.setObjectName('content');scroll.setWidget(self.content);main=QVBoxLayout(self.content);main.setContentsMargins(26,22,26,18);main.setSpacing(17)
        header=QHBoxLayout();titles=QVBoxLayout();titles.setSpacing(3);titles.addWidget(label('OVERVIEW','eyebrow'));self.heading=label('用量总览','heading');titles.addWidget(self.heading);header.addLayout(titles);header.addStretch()
        segments=QFrame();segments.setObjectName('segments');segbox=QHBoxLayout(segments);segbox.setContentsMargins(4,4,4,4);segbox.setSpacing(2);group=QButtonGroup(self);group.setExclusive(True);self.period='今天'
        self.period_buttons={}
        for text in ('今天','近 7 天','全部记录'):
            b=button(text,lambda checked=False,t=text:self.set_period(t),'period');b.setCheckable(True);group.addButton(b);segbox.addWidget(b);self.period_buttons[text]=b
        self.period_buttons['今天'].setChecked(True);header.addWidget(segments,0,Qt.AlignmentFlag.AlignVCenter);main.addLayout(header)
        toolbar=QHBoxLayout();self.status=label('正在读取本地用量记录…','muted');toolbar.addWidget(self.status,1)
        self.pause_button=button('暂停',self.pause);toolbar.addWidget(self.pause_button)
        for title,fn in [('导入',self.import_file),('导出 CSV',self.export),('数据源',self.settings)]:toolbar.addWidget(button(title,fn))
        main.addLayout(toolbar)
        metrics=QHBoxLayout();metrics.setSpacing(12);self.cards=[]
        for title,unit,primary in [('最近请求速度','tok/s',True),('平均请求速度','tok/s',False),('累计输出','tokens',False),('累计输入','tokens',False)]:
            card=Metric(title,unit,primary);metrics.addWidget(card,1);self.cards.append(card)
        main.addLayout(metrics)
        charts=QHBoxLayout();charts.setSpacing(14)
        trend=QFrame();trend.setObjectName('panel');trendbox=QVBoxLayout(trend);trendbox.setContentsMargins(18,16,18,12);trendbox.setSpacing(8)
        ch=QHBoxLayout();ch.addWidget(label('请求速度趋势','section'));ch.addStretch();ch.addWidget(label('最近 40 次 · 估算','muted'));trendbox.addLayout(ch);self.chart=SpeedChart();trendbox.addWidget(self.chart,1);charts.addWidget(trend,3)
        split=QFrame();split.setObjectName('panel');splitbox=QVBoxLayout(split);splitbox.setContentsMargins(18,16,18,12);splitbox.setSpacing(8);splitbox.addWidget(label('输出分布','section'));self.breakdown=Breakdown();splitbox.addWidget(self.breakdown,1);charts.addWidget(split,1);main.addLayout(charts)
        recent=QFrame();recent.setObjectName('panel');recentbox=QVBoxLayout(recent);recentbox.setContentsMargins(0,15,0,4);recentbox.setSpacing(12)
        th=QHBoxLayout();th.setContentsMargins(18,0,18,0);th.addWidget(label('最近请求','section'));th.addStretch();self.request_count=label('等待记录','muted');th.addWidget(self.request_count);recentbox.addLayout(th)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['时间','软件','模型','输出 Token','思考 Token','速度 /s']);self.table.verticalHeader().hide();self.table.setShowGrid(False);self.table.setAlternatingRowColors(True);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(185);self.table.verticalHeader().setDefaultSectionSize(40)
        for col,width in enumerate([150,120,180,108,108,95]):self.table.setColumnWidth(col,width)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch);self.table.horizontalHeader().setMinimumSectionSize(70)
        recentbox.addWidget(self.table,1);main.addWidget(recent,1)
        footer=QHBoxLayout();note=label('速度包含记录中的等待与工具耗时；思考 Token 不重复计入输出。','muted');note.setWordWrap(True);footer.addWidget(note,1);self.updated=label('等待同步','muted');footer.addWidget(self.updated);main.addLayout(footer)
        self.select('全部软件')
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(3000);QTimer.singleShot(100,self.refresh)
        if smoke:QTimer.singleShot(120000,self.close)

    @property
    def busy(self): return self.worker is not None and self.worker.isRunning()
    def refresh(self):
        if self.paused or self.busy:return
        self.worker=ScanWorker(self.collector);self.worker.result.connect(self.received);self.worker.error.connect(lambda e:self.status.setText('读取异常：'+e));self.worker.start()
    def received(self,data):self.data=data;self.updated.setText('同步于 '+datetime.now().strftime('%H:%M:%S'));self.render()
    def select(self,app):self.selected=app;self.nav[app].setChecked(True);self.heading.setText('用量总览' if app=='全部软件' else DISPLAY[app]);self.render()
    def set_period(self,text):self.period=text;self.period_buttons[text].setChecked(True);self.render()
    def pause(self):self.paused=not self.paused;self.pause_button.setText('继续' if self.paused else '暂停');self.render();self.refresh()
    def render(self):
        if not self.data:return
        apps=APPS if self.selected=='全部软件' else [self.selected]
        cutoff=datetime.now().replace(hour=0,minute=0,second=0,microsecond=0).timestamp() if self.period=='今天' else time.time()-7*86400 if self.period=='近 7 天' else 0
        self.rows=sorted([r for a in apps for r in self.data[a]['requests'] if r.timestamp>=cutoff],key=lambda r:r.timestamp)
        timed=[r for r in self.rows if r.speed is not None];last=self.rows[-1] if self.rows else None
        avg=sum(r.output for r in timed)/sum(r.seconds for r in timed) if timed else None
        self.cards[0].update_value(f'{last.speed:.1f}' if last and last.speed is not None else '—','≈ 请求耗时口径' if last and last.speed is not None else '缺少单次耗时记录')
        self.cards[1].update_value(f'{avg:.1f}' if avg is not None else '—',f'{len(timed):,} 次有耗时的请求')
        output=sum(r.output for r in self.rows);inp=sum(r.input for r in self.rows)
        self.cards[2].update_value(compact(output),'思考 '+compact(sum(r.reasoning for r in self.rows)),f'完整输出 Token：{output:,}')
        self.cards[3].update_value(compact(inp),'缓存读取 '+compact(sum(r.cached for r in self.rows)),f'完整输入 Token：{inp:,}')
        ready=sum(bool(d['requests']) for d in self.data.values());self.connection.setText(f'●  {ready} / 5 个来源已连接');self.connection.setStyleSheet(f'color:{ACCENT};font-size:12px;')
        status=f'{ready} 个来源已接入 · 每 3 秒自动同步' if self.selected=='全部软件' else self.data[self.selected]['status']
        errors=sum(self.data[a]['errors'] for a in apps)
        if errors:status+=f' · {errors} 条异常记录'
        self.status.setText(('已暂停 · ' if self.paused else '')+status)
        self.request_count.setText(f'{len(self.rows):,} 次请求 · 显示最近 100 条')
        self.chart.set_rows(self.rows);self.breakdown.set_rows(self.rows)
        self.table.setUpdatesEnabled(False);self.table.setRowCount(min(100,len(self.rows)))
        for row,r in enumerate(self.rows[-100:][::-1]):
            values=[datetime.fromtimestamp(r.timestamp).strftime('%m-%d %H:%M:%S'),DISPLAY[r.app],r.model or '未记录',f'{r.output:,}',f'{r.reasoning:,}',f'≈ {r.speed:.1f}' if r.speed is not None else '—']
            for col,value in enumerate(values):
                item=QTableWidgetItem(value);item.setToolTip(value)
                if col>=3:item.setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
                if col==1:item.setForeground(QColor(COLORS[r.app]))
                if col in (0,4):item.setForeground(QColor(MUTED))
                self.table.setItem(row,col,item)
        self.table.setUpdatesEnabled(True)
    def save_config(self,config):
        path=config_path();path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path);self.collector=Collector(config);self.status.setText('设置已保存，等待同步')
    def settings(self):
        if self.busy:QMessageBox.information(self,'正在同步','请等待本次读取完成后再打开数据源。');return
        win=QDialog(self);win.setWindowTitle('数据源设置');win.resize(760,610);box=QVBoxLayout(win);box.setContentsMargins(22,22,22,22);box.setSpacing(14);box.addWidget(label('管理本地数据源','heading'));box.addWidget(label('只读取用量与时间信息，设置仅保存在本机。','muted'))
        tabs=QTabWidget();box.addWidget(tabs,1);fields={};config=json.loads(json.dumps(self.collector.config))
        for app in APPS:
            tab=QWidget();form=QVBoxLayout(tab);form.setSpacing(10);form.addWidget(label(self.data.get(app,{}).get('status','等待检测'),'muted'));form.addWidget(label('记录目录（每行一个）','section'));roots=QTextEdit();roots.setPlainText('\n'.join(config['roots'][app]));roots.setMaximumHeight(105);form.addWidget(roots)
            def pick(checked=False,t=roots):
                p=QFileDialog.getExistingDirectory(win,'选择记录目录')
                if p:t.append(p)
            form.addWidget(button('选择目录',pick),0,Qt.AlignmentFlag.AlignLeft);form.addWidget(label('标准导入文件（每行一个 JSONL 路径）','section'));imports=QTextEdit();imports.setPlainText('\n'.join(config['imports'][app]));imports.setMaximumHeight(85);form.addWidget(imports)
            note=label('反重力读取 conversations 下的 SQLite；模型暂显示原始编号。' if app=='Antigravity' else 'Codex / Claude / WorkBuddy 选择会话目录；Reasonix 选择 stats 目录。','muted');note.setWordWrap(True);form.addWidget(note);form.addStretch();tabs.addTab(tab,DISPLAY[app]);fields[app]=(roots,imports)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存设置');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');box.addWidget(buttons);buttons.rejected.connect(win.reject)
        was_active=self.timer.isActive();self.timer.stop()
        def save():
            for app,(roots,imports) in fields.items():
                config['roots'][app]=[p.strip() for p in roots.toPlainText().splitlines() if p.strip()];config['imports'][app]=[p.strip() for p in imports.toPlainText().splitlines() if p.strip()]
            try:self.save_config(config);win.accept()
            except OSError as e:QMessageBox.critical(win,'保存失败',str(e))
        buttons.accepted.connect(save);win.exec()
        if was_active:self.timer.start(3000)
    def import_file(self):
        if self.busy:QMessageBox.information(self,'正在同步','请等待本次读取完成。');return
        win=QDialog(self);win.setWindowTitle('导入用量记录');win.resize(450,200);box=QVBoxLayout(win);box.setContentsMargins(24,24,24,24);box.setSpacing(18);box.addWidget(label('选择记录所属软件','section'));choice=QComboBox();choice.addItems(APPS);box.addWidget(choice)
        def pick():
            path,_=QFileDialog.getOpenFileName(win,'选择 ai-pulse/v1 文件','','JSON Lines (*.jsonl)')
            if not path:return
            try:
                with open(path,encoding='utf-8') as f:sample=json.loads(f.readline())
                if sample.get('schema')!='ai-pulse/v1':raise ValueError('文件须使用 ai-pulse/v1 格式，请参阅 README。')
                config=json.loads(json.dumps(self.collector.config));app=choice.currentText()
                if path not in config['imports'][app]:config['imports'][app].append(path)
                self.save_config(config);win.accept()
            except (ValueError,OSError,AttributeError) as e:QMessageBox.critical(win,'导入失败',str(e))
        box.addWidget(button('选择 JSONL 文件',pick));self.timer.stop();win.exec();self.timer.start(3000)
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'导出当前筛选结果','ai-pulse-usage.csv','CSV (*.csv)')
        if not path:return
        try:
            with open(path,'w',encoding='utf-8-sig',newline='') as f:
                cols=['app','timestamp','model','input','output','reasoning','cached','seconds','timing','speed'];writer=csv.DictWriter(f,fieldnames=cols);writer.writeheader()
                for r in self.rows:
                    row=r.public();row['timestamp']=datetime.fromtimestamp(r.timestamp,timezone.utc).astimezone().isoformat()
                    if row['model'].startswith(('=','+','-','@')):row['model']="'"+row['model']
                    writer.writerow(row)
            QMessageBox.information(self,'导出完成',f'已导出 {len(self.rows):,} 条用量记录。')
        except OSError as e:QMessageBox.critical(self,'导出失败',str(e))
    def closeEvent(self,event):
        self.timer.stop()
        if self.busy:self.worker.wait()
        event.accept()

def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app=QApplication(sys.argv);app.setApplicationName('AI Pulse');app.setOrganizationName('AI Pulse');app.setStyle('Fusion');font=QFont('Microsoft YaHei UI');font.setPixelSize(13);app.setFont(font)
    window=Pulse(smoke='--smoke' in sys.argv);window.show();sys.exit(app.exec())

if __name__=='__main__':main()
