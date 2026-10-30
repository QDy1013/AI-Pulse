from __future__ import annotations
import csv
import json
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk
from .collector import APPS, Collector, defaults

BG, PANEL, BORDER, TEXT, MUTED, ACCENT = '#101719', '#182225', '#2a383b', '#ecf3ee', '#98aaa6', '#a9edc9'

def config_path():
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.config')))
    return base / 'AI-Pulse/settings.json'

def load_config():
    c = defaults()
    try:
        saved = json.loads(config_path().read_text(encoding='utf-8'))
        for key in ('roots', 'imports'):
            for app, paths in saved.get(key, {}).items():
                if app in APPS and isinstance(paths, list) and all(isinstance(p, str) for p in paths):
                    c[key][app] = paths
    except (OSError, ValueError, TypeError): pass
    return c

class Pulse(ctk.CTk):
    def __init__(self, smoke=False):
        ctk.set_widget_scaling(1.0)
        ctk.set_window_scaling(1.0)
        ctk.ThemeManager.theme['CTkFont']['family'] = 'Microsoft YaHei UI'
        super().__init__()
        # Keep the initial window inside the physical desktop on high-DPI screens.
        dpi_scale = self._get_window_scaling()
        fit_scale = min(1.0, (self.winfo_screenheight() - 100) / (870 * dpi_scale))
        ctk.set_widget_scaling(fit_scale)
        ctk.set_window_scaling(fit_scale)
        self.title('AI Pulse · AI 用量监控')
        self.geometry(f'{min(1220, self.winfo_screenwidth()-80)}x{min(870, self.winfo_screenheight()-100)}')
        self.minsize(940, 620)
        self.configure(fg_color=BG)
        self.collector = Collector(load_config())
        self.data, self.rows = {}, []
        self.selected = '全部软件'
        self.paused, self.busy, self.closed = False, False, False
        self.mailbox = queue.Queue()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        side = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color='#131d20')
        side.grid(row=0, column=0, sticky='nsew')
        side.grid_propagate(False)
        ctk.CTkLabel(side, text='◉  AI PULSE', font=('Segoe UI', 24, 'bold'), text_color=ACCENT).pack(anchor='w', padx=24, pady=(32, 2))
        ctk.CTkLabel(side, text='你的 AI，尽在一处', text_color=MUTED, font=('Microsoft YaHei UI', 12)).pack(anchor='w', padx=26, pady=(0, 32))
        self.nav = {}
        for app in ('全部软件',) + APPS:
            b = ctk.CTkButton(side, text=('Claude / Code' if app == 'Claude' else app), anchor='w', height=43,
                              fg_color='transparent', hover_color='#243638', text_color=TEXT,
                              font=('Segoe UI', 14), command=lambda a=app: self.select(a))
            b.pack(fill='x', padx=16, pady=4)
            self.nav[app] = b
        ctk.CTkLabel(side, text='LOCAL FIRST\n仅在本机读取用量记录', justify='left', text_color=MUTED, font=('Microsoft YaHei UI', 11)).pack(side='bottom', anchor='w', padx=24, pady=24)
        self.main = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0)
        self.main.grid(row=0, column=1, sticky='nsew', padx=28, pady=24)
        self.main.grid_columnconfigure((0, 1), weight=1)
        self.main.grid_rowconfigure(5, weight=1)
        header = ctk.CTkFrame(self.main, fg_color='transparent')
        header.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 16))
        self.heading = ctk.CTkLabel(header, text='用量总览', text_color=TEXT, font=('Microsoft YaHei UI', 25, 'bold'))
        self.heading.pack(side='left')
        self.period = ctk.CTkSegmentedButton(header, values=['今天', '近 7 天', '全部记录'], command=lambda _: self.render(), selected_color='#34544a', selected_hover_color='#426c5c', font=('Microsoft YaHei UI', 12))
        self.period.set('今天')
        self.period.pack(side='right')
        toolbar = ctk.CTkFrame(self.main, fg_color='transparent')
        toolbar.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 16))
        self.status = ctk.CTkLabel(toolbar, text='正在读取本地记录…', text_color=MUTED, font=('Microsoft YaHei UI', 11))
        self.status.pack(side='left')
        for title, fn in [('设置来源', self.settings), ('导入', self.import_file), ('导出 CSV', self.export)]:
            ctk.CTkButton(toolbar, text=title, width=85, height=30, fg_color='#263638', hover_color='#35494b', command=fn).pack(side='right', padx=(6, 0))
        self.pause_button = ctk.CTkButton(toolbar, text='暂停', width=60, height=30, fg_color='#263638', command=self.pause)
        self.pause_button.pack(side='right', padx=6)
        self.cards = []
        for i, (title, hint) in enumerate([
            ('最近请求速度', '输出 Token / 记录耗时 · 估算'),
            ('平均请求速度', '有耗时记录的输出总量 / 耗时之和'),
            ('累计输出 Token', '按所选软件与时间范围统计'),
            ('累计输入 Token', '包含已记录的缓存读取与写入')]):
            f = ctk.CTkFrame(self.main, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=14)
            f.grid(row=2 + i // 2, column=i % 2, sticky='ew', padx=(0, 7) if i % 2 == 0 else (7, 0), pady=(0, 12))
            ctk.CTkLabel(f, text=title, font=('Microsoft YaHei UI', 12), text_color=MUTED).pack(anchor='w', padx=20, pady=(14, 3))
            val = ctk.CTkLabel(f, text='—', font=('Segoe UI', 29, 'bold'), text_color=ACCENT if i < 2 else TEXT)
            val.pack(anchor='w', padx=20)
            sub = ctk.CTkLabel(f, text=hint, font=('Microsoft YaHei UI', 10), text_color=MUTED)
            sub.pack(anchor='w', padx=20, pady=(2, 14))
            self.cards.append((val, sub))
        chart_frame = ctk.CTkFrame(self.main, fg_color=PANEL, corner_radius=14, border_width=1, border_color=BORDER)
        chart_frame.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(0, 14))
        self.chart_title = ctk.CTkLabel(chart_frame, text='最近 40 次有耗时记录的请求  ·  tokens/s', text_color=TEXT, font=('Microsoft YaHei UI', 12, 'bold'))
        self.chart_title.pack(anchor='w', padx=20, pady=(14, 0))
        self.chart = tk.Canvas(chart_frame, height=155, bg=PANEL, highlightthickness=0)
        self.chart.pack(fill='x', padx=14, pady=(4, 12))
        self.chart.bind('<Configure>', lambda _: self.draw_chart())
        bottom = ctk.CTkFrame(self.main, fg_color=PANEL, corner_radius=14)
        bottom.grid(row=5, column=0, columnspan=2, sticky='nsew')
        ctk.CTkLabel(bottom, text='最近请求', font=('Microsoft YaHei UI', 12, 'bold'), text_color=TEXT).pack(anchor='w', padx=20, pady=(12, 8))
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=29, borderwidth=0, font=('Segoe UI', 10))
        style.configure('Treeview.Heading', background='#223034', foreground=MUTED, relief='flat', font=('Microsoft YaHei UI', 10))
        style.map('Treeview', background=[('selected', '#34544a')])
        table_frame = tk.Frame(bottom, bg=PANEL)
        table_frame.pack(fill='both', expand=True, padx=15, pady=(0, 12))
        cols = ('time', 'app', 'model', 'output', 'reasoning', 'speed')
        self.table = ttk.Treeview(table_frame, columns=cols, show='headings', height=4)
        for col, title, width in zip(cols, ['时间', '软件', '模型', '输出', '思考', '速度 /s'], [142, 95, 220, 75, 75, 95]):
            self.table.heading(col, text=title)
            self.table.column(col, width=width, minwidth=60, stretch=col == 'model')
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.table.pack(fill='both', expand=True)
        ctk.CTkLabel(self.main, text='速度为请求耗时口径，可能包含工具与等待；无耗时数据时显示 —。思考量是输出量的子集，不重复相加。', wraplength=900, text_color=MUTED, font=('Microsoft YaHei UI', 10)).grid(row=6, column=0, columnspan=2, sticky='w', pady=(10, 0))
        self.select('全部软件')
        self.after(100, self.poll)
        self.after(150, self.refresh)
        if smoke:
            self.after(120000, self.close)

    def close(self):
        self.closed = True
        self.destroy()

    def select(self, app):
        self.selected = app
        for k, b in self.nav.items(): b.configure(fg_color='#2b443c' if k == app else 'transparent', text_color=ACCENT if k == app else TEXT)
        self.heading.configure(text='用量总览' if app == '全部软件' else app)
        self.render()

    def refresh(self):
        if not self.paused and not self.busy:
            self.busy = True
            def work():
                try: self.mailbox.put(('data', self.collector.scan()))
                except Exception as e: self.mailbox.put(('error', type(e).__name__))
            threading.Thread(target=work, daemon=True).start()
        if not self.closed: self.after(3000, self.refresh)

    def poll(self):
        try:
            kind, value = self.mailbox.get_nowait()
            self.busy = False
            if kind == 'data': self.data = value; self.render()
            else: self.status.configure(text='读取失败：' + value)
        except queue.Empty: pass
        if not self.closed: self.after(150, self.poll)

    def render(self):
        if not self.data: return
        apps = APPS if self.selected == '全部软件' else [self.selected]
        period = self.period.get()
        now = time.time()
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() if period == '今天' else now - 7 * 86400 if period == '近 7 天' else 0
        self.rows = sorted([r for a in apps for r in self.data[a]['requests'] if r.timestamp >= cutoff], key=lambda r: r.timestamp)
        timed = [r for r in self.rows if r.speed is not None]
        last = self.rows[-1] if self.rows else None
        speed = f'{last.speed:.1f} tokens/s' if last and last.speed is not None else '—'
        avg = sum(r.output for r in timed) / sum(r.seconds for r in timed) if timed else None
        values = [speed, f'{avg:.1f} tokens/s' if avg is not None else '—', f'{sum(r.output for r in self.rows):,}', f'{sum(r.input for r in self.rows):,}']
        for (label, _), value in zip(self.cards, values): label.configure(text=value)
        self.cards[2][1].configure(text=f'其中思考 {sum(r.reasoning for r in self.rows):,} · {len(self.rows):,} 次请求')
        self.cards[3][1].configure(text=f'其中缓存读取 {sum(r.cached for r in self.rows):,} Token')
        if self.selected == '全部软件':
            ready = sum(bool(d['requests']) for d in self.data.values())
            status = f'{ready} / 5 个来源有用量记录 · 每 3 秒刷新'
        else: status = self.data[self.selected]['status']
        errors = sum(self.data[a]['errors'] for a in apps)
        if errors: status += f' · 跳过 {errors} 条异常记录'
        self.status.configure(text=('已暂停 · ' if self.paused else '') + status)
        self.table.delete(*self.table.get_children())
        for r in self.rows[-100:][::-1]:
            self.table.insert('', 'end', values=(datetime.fromtimestamp(r.timestamp).strftime('%m-%d %H:%M:%S'), r.app, r.model or '未记录', f'{r.output:,}', f'{r.reasoning:,}', f'≈ {r.speed:.1f}' if r.speed is not None else '—'))
        self.draw_chart()

    def draw_chart(self):
        c = self.chart
        c.delete('all')
        w, h = c.winfo_width(), 155
        rows = [r for r in self.rows if r.speed is not None][-40:]
        maximum = max([r.speed for r in rows] + [1]) * 1.12
        for i in range(4):
            y = 16 + i * 36
            c.create_line(48, y, w - 20, y, fill=BORDER)
            c.create_text(38, y, text=f'{maximum * (1-i/3):.0f}', fill=MUTED, anchor='e', font=('Segoe UI', 9))
        if not rows:
            c.create_text(w / 2, h / 2, text='当前范围暂无可计算速度的记录', fill=MUTED, font=('Microsoft YaHei UI', 12))
            return
        points = [(48 + i * max(1, w - 70) / max(1, len(rows)-1), 124 - r.speed / maximum * 108) for i, r in enumerate(rows)]
        if len(points) > 1: c.create_line(*[v for p in points for v in p], fill=ACCENT, width=2)
        for x, y in points: c.create_oval(x-2, y-2, x+2, y+2, fill=ACCENT, outline='')
        c.create_text(48, 145, text='较早', fill=MUTED, anchor='w', font=('Microsoft YaHei UI', 9))
        c.create_text(w-20, 145, text='最近', fill=MUTED, anchor='e', font=('Microsoft YaHei UI', 9))

    def pause(self):
        self.paused = not self.paused
        self.pause_button.configure(text='继续' if self.paused else '暂停')
        self.render()

    def save_config(self, config):
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)
        self.collector = Collector(config)
        self.status.configure(text='设置已保存，等待刷新')

    def settings(self):
        if self.busy:
            messagebox.showinfo('正在读取', '首次读取尚未完成，请稍后打开设置。'); return
        win = ctk.CTkToplevel(self)
        win.title('数据来源 · AI Pulse')
        win.geometry('740x590')
        win.transient(self)
        win.grab_set()
        tabs = ctk.CTkTabview(win)
        tabs.pack(fill='both', expand=True, padx=18, pady=18)
        fields = {}
        config = json.loads(json.dumps(self.collector.config))
        for app in APPS:
            tab = tabs.add(app)
            state = self.data.get(app, {}).get('status', '待检测')
            ctk.CTkLabel(tab, text=state, text_color=ACCENT).pack(anchor='w', pady=12)
            ctk.CTkLabel(tab, text='记录目录（每行一个；Codex / Claude 递归读取 JSONL，Reasonix 选择 stats 目录）', wraplength=650, justify='left').pack(anchor='w', pady=6)
            text = ctk.CTkTextbox(tab, height=115)
            text.pack(fill='x'); text.insert('1.0', '\n'.join(config['roots'][app]))
            ctk.CTkButton(tab, text='选择目录', command=lambda t=text: self.pick_directory(t)).pack(anchor='w', pady=8)
            ctk.CTkLabel(tab, text='标准导入文件（每行一个 JSONL 路径；清空即可移除导入）').pack(anchor='w', pady=6)
            imports = ctk.CTkTextbox(tab, height=85)
            imports.pack(fill='x'); imports.insert('1.0', '\n'.join(config['imports'][app]))
            ctk.CTkLabel(tab, text='Antigravity：读取 conversations 目录下的 SQLite 计量字段。\n模型名称暂以原始模型编号显示。' if app == 'Antigravity' else '只提取用量、时间、模型字段。不会保存对话正文。', justify='left', text_color=MUTED).pack(anchor='w', pady=12)
            fields[app] = (text, imports)
        def save():
            try:
                for app, (roots, imports) in fields.items():
                    config['roots'][app] = [p.strip() for p in roots.get('1.0', 'end').splitlines() if p.strip()]
                    config['imports'][app] = [p.strip() for p in imports.get('1.0', 'end').splitlines() if p.strip()]
                if self.busy: messagebox.showinfo('正在读取', '请等待本次读取完成后再保存。', parent=win); return
                self.save_config(config); win.destroy()
            except OSError as e: messagebox.showerror('保存失败', str(e), parent=win)
        ctk.CTkButton(win, text='保存设置', command=save, fg_color='#355b49').pack(pady=(0, 18))

    def pick_directory(self, text):
        path = filedialog.askdirectory()
        if path: text.insert('end', '\n' + path)

    def import_file(self):
        if self.busy: messagebox.showinfo('正在读取', '请等待本次读取完成。'); return
        win = ctk.CTkToplevel(self); win.title('导入标准用量记录'); win.geometry('440x220'); win.transient(self); win.grab_set()
        ctk.CTkLabel(win, text='选择记录所属软件；文件须使用 ai-pulse/v1 格式。', wraplength=400).pack(pady=24)
        choice = ctk.CTkOptionMenu(win, values=list(APPS)); choice.pack()
        def pick():
            p = filedialog.askopenfilename(parent=win, filetypes=[('JSON Lines', '*.jsonl')])
            if not p: return
            try:
                with open(p, encoding='utf-8') as f: sample = json.loads(f.readline())
                if sample.get('schema') != 'ai-pulse/v1': raise ValueError('首行不是 ai-pulse/v1 标准记录；请查看 README 格式说明。')
                if self.busy: raise ValueError('正在刷新，请稍后重试。')
                config = json.loads(json.dumps(self.collector.config))
                if p not in config['imports'][choice.get()]: config['imports'][choice.get()].append(p)
                self.save_config(config); win.destroy()
            except (ValueError, OSError, AttributeError) as e: messagebox.showerror('导入失败', str(e), parent=win)
        ctk.CTkButton(win, text='选择 JSONL 文件', command=pick).pack(pady=24)

    def export(self):
        p = filedialog.asksaveasfilename(defaultextension='.csv', initialfile='ai-pulse-usage.csv', filetypes=[('CSV', '*.csv')])
        if not p: return
        try:
            with open(p, 'w', encoding='utf-8-sig', newline='') as f:
                cols = ['app', 'timestamp', 'model', 'input', 'output', 'reasoning', 'cached', 'seconds', 'timing', 'speed']
                writer = csv.DictWriter(f, fieldnames=cols); writer.writeheader()
                for r in self.rows:
                    row = r.public(); row['timestamp'] = datetime.fromtimestamp(r.timestamp, timezone.utc).astimezone().isoformat()
                    # Avoid spreadsheet formula execution from model names.
                    if row['model'].startswith(('=', '+', '-', '@')): row['model'] = "'" + row['model']
                    writer.writerow(row)
            messagebox.showinfo('导出完成', f'已导出 {len(self.rows)} 条用量记录。')
        except OSError as e: messagebox.showerror('导出失败', str(e))

def main():
    ctk.set_appearance_mode('dark')
    Pulse(smoke='--smoke' in sys.argv).mainloop()

if __name__ == '__main__': main()
