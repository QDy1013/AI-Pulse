"""Regenerate pulse/assets from pulse/icon.py: the EXE icon and the phone home-screen icons.

    python tools/make_icons.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QGuiApplication  # noqa: E402
from pulse import icon  # noqa: E402

app = QGuiApplication([])
out = ROOT / 'pulse' / 'assets'
out.mkdir(exist_ok=True)
(out / 'AI-Pulse.ico').write_bytes(icon.ico())
(out / 'icon.svg').write_text(icon.svg(), encoding='utf-8')
# iOS masks and rounds the home-screen icon itself, so these fill the square.
(out / 'apple-touch-icon.png').write_bytes(icon.png(180, bleed=True))
(out / 'icon-192.png').write_bytes(icon.png(192, bleed=True))
(out / 'icon-512.png').write_bytes(icon.png(512, bleed=True))
print('wrote', ', '.join(sorted(p.name for p in out.iterdir())))
