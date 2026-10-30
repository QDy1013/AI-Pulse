# Third-party components

AI Pulse application code is MIT licensed. Third-party components retain their
own licenses and copyright notices.

## Qt / PySide6 / Shiboken6 6.12.0

The application uses unmodified Qt Core, GUI, Widgets and their required runtime
libraries through PySide6-Essentials and Shiboken6. These components are provided
under their applicable open-source licenses, including LGPL v3. Copies of LGPL
v3 and GPL v3 are in `licenses/`.

- Project licensing: https://doc.qt.io/qtforpython-6/licenses.html
- Binding source: https://code.qt.io/cgit/pyside/pyside-setup.git/ (tag v6.12.0)
- Qt source: https://code.qt.io/cgit/qt/ (corresponding v6.12.0 source tags)
- Source downloads: https://download.qt.io/official_releases/QtForPython/
- Upstream distributions: https://pypi.org/project/PySide6-Essentials/6.12.0/

The Windows distribution uses a directory layout with replaceable shared
libraries in `_internal/PySide6` and `_internal/shiboken6`. Keep the directory
layout intact. Compatible modified libraries can replace the corresponding
DLLs / Python extension modules. The complete MIT application source and build
instructions are provided in the public repository so the application can also
be rebuilt with a modified version of the dependencies. Reverse engineering
needed to debug modifications to LGPL components is permitted to the extent
required by their license. No Qt or PySide source modifications are included.

## Python and packager

The binary includes the CPython runtime under the Python Software Foundation
license. PyInstaller's bootloader is used under its GPL license with the
bootloader exception. Corresponding installed license notices are provided
with the Windows package. Application code remains MIT licensed.

The application references Windows-installed Microsoft YaHei UI and Segoe UI;
font files are not redistributed.
