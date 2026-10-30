"""Start with Windows through the per-user Run key (no administrator rights needed)."""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
NAME = 'AI Pulse'
MINIMIZED = '--minimized'


def supported():
    return sys.platform == 'win32'


def command():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" {MINIMIZED}'
    exe = Path(sys.executable)
    pythonw = exe.with_name('pythonw.exe')  # No console window at sign-in.
    main = Path(__file__).resolve().parent.parent / 'main.py'
    return f'"{pythonw if pythonw.exists() else exe}" "{main}" {MINIMIZED}'


def enabled(key=RUN_KEY, name=NAME):
    if not supported():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return bool(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return False


def set_enabled(on, key=RUN_KEY, name=NAME):
    """Write or remove the startup entry. Re-writing refreshes a moved program path."""
    if not supported():
        return
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        if on:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
