# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)
a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=[],
             datas=[(str(root / 'licenses'), 'licenses'),
                    (str(root / 'THIRD_PARTY.md'), '.')],
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=[], noarchive=False)
# Qt 6.12 uses the unversioned ICU API supplied by supported Windows systems.
# Do not shadow the OS library with an incompatible DLL from another program
# found on the build machine's PATH.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in {'icuuc.dll', 'icuin.dll', 'icudt.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AI-Pulse',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
          console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name='AI-Pulse')
